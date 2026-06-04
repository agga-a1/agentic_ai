import json
import re
from typing import AsyncGenerator, Any, Optional

from google.adk.agents import LoopAgent
from google.adk.agents.base_agent import BaseAgent
from google.adk.events import Event, EventActions
from google.genai import types

from agent.architect_agent.agent import architect_agent
from agent.logging_setup import get_logger
from json_repair import repair_json

# Import centralized keys
from agent.workflow.keys import (
    KEY_ARCH_COMPLETE,
    KEY_HLD_REPORT_JSON,
    KEY_VALIDATION_ERROR,
    KEY_ARCH_VALID,
    KEY_SECTION_RETRY_TARGET,
    KEY_SECTION_RETRY_QUEUE,
    KEY_SECTION_RETRY_COUNTS,
    KEY_SECTION_RETRY_MODE,
)

# ✅ hybrid section-wise assembly helpers
from tools.hld_section_commit_tools import (
    assemble_hld_from_state,
    validate_required_hld_sections,
    validate_hld_section_quality,
    get_missing_hld_sections,
    is_hld_final_validation_ready,
    is_hld_section_committed,
    get_hld_section_commit_function,
    section_name_from_commit_tool_name,
)


logger = get_logger("ArchitectureValidationGate")


# After this many malformed native tool-call retries for the same section,
# stop asking the model to call the tool and commit the extracted payload directly.
MAX_MALFORMED_NATIVE_TOOL_RETRIES = 2


# ==========================================================
# HELPERS
# ==========================================================
def _get_nested(d: dict, *keys):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _has_non_empty_diagrams(value) -> bool:
    if not isinstance(value, list):
        return False
    return any(str(x).strip() for x in value)


def _coerce_hld_to_dict(value: Any) -> Optional[dict]:
    """
    Normalize HLD payload into a dict if possible.
    Supports dict, JSON string, and pydantic-like objects.
    """
    if value is None:
        return None

    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        try:
            fixed_value = repair_json(value)
            parsed = json.loads(fixed_value, strict=False)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None

    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            dumped = value.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass

    if hasattr(value, "dict") and callable(value.dict):
        try:
            dumped = value.dict()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass

    return None


def _resolve_diagrams(hld: dict, canonical_view: str):
    """
    Resolve diagram list from:
    1) direct canonical root keys
    2) current schema paths (WITH UNDERSCORES)
    3) legacy schema paths (WITHOUT UNDERSCORES)

    Canonical targets:
      - logical_view.diagrams
      - physical_view.diagrams
      - process_view.diagrams
      - data_flow.diagrams

    Current schema:
      - design_views.logical_view.diagrams
      - design_views.physical_view.diagrams
      - design_views.process_view.diagrams
      - data_design.data_flow.diagrams

    Legacy shapes:
      - designviews.logicalview.diagrams
      - designviews.physicalview.diagrams
      - designviews.processview.diagrams
      - datadesign.dataflow.diagrams
    """
    # --------------------------------------------------
    # 1) Preferred direct canonical schema
    # --------------------------------------------------
    direct = _get_nested(hld, canonical_view, "diagrams")
    if isinstance(direct, list):
        return direct

    # --------------------------------------------------
    # 2) Current schema fallback (WITH UNDERSCORES)
    # --------------------------------------------------
    current_paths = {
        "logical_view": ("design_views", "logical_view", "diagrams"),
        "physical_view": ("design_views", "physical_view", "diagrams"),
        "process_view": ("design_views", "process_view", "diagrams"),
        "data_flow": ("data_design", "data_flow", "diagrams"),
    }

    path = current_paths.get(canonical_view)
    if path:
        current = _get_nested(hld, *path)
        if isinstance(current, list):
            return current

    # --------------------------------------------------
    # 3) Legacy schema fallback (WITHOUT UNDERSCORES)
    # --------------------------------------------------
    legacy_paths = {
        "logical_view": ("designviews", "logicalview", "diagrams"),
        "physical_view": ("designviews", "physicalview", "diagrams"),
        "process_view": ("designviews", "processview", "diagrams"),
        "data_flow": ("datadesign", "dataflow", "diagrams"),
    }

    path = legacy_paths.get(canonical_view)
    if path:
        legacy = _get_nested(hld, *path)
        if isinstance(legacy, list):
            return legacy

    return None


def _detect_retry_targets(state: dict, hld: Optional[dict]) -> list[str]:
    """
    Return precise retry targets in priority order.
    Split design_views into sub-section retry targets.
    """
    targets: list[str] = []

    # --------------------------------------------------
    # Section-wise completeness from committed state
    # --------------------------------------------------
    try:
        section_report = validate_required_hld_sections(state)
        missing_sections = section_report.get("missing_sections", []) or []
    except Exception:
        missing_sections = []

    # --------------------------------------------------
    # Split design_views into logical/physical/process
    # --------------------------------------------------
    if "design_views" in missing_sections:
        dv = state.get("hld_design_views") or {}

        if not _has_non_empty_diagrams(_get_nested(dv, "logical_view", "diagrams")):
            targets.append("design_views.logical_view")

        if not _has_non_empty_diagrams(_get_nested(dv, "physical_view", "diagrams")):
            targets.append("design_views.physical_view")

        if not _has_non_empty_diagrams(_get_nested(dv, "process_view", "diagrams")):
            targets.append("design_views.process_view")

    # --------------------------------------------------
    # Other top-level missing sections
    # --------------------------------------------------
    for section in missing_sections:
        if section != "design_views":
            targets.append(section)

    # --------------------------------------------------
    # Additional diagram-level validation from assembled HLD
    # --------------------------------------------------
    if isinstance(hld, dict):
        if not _has_non_empty_diagrams(_resolve_diagrams(hld, "logical_view")):
            if "design_views.logical_view" not in targets:
                targets.append("design_views.logical_view")

        if not _has_non_empty_diagrams(_resolve_diagrams(hld, "physical_view")):
            if "design_views.physical_view" not in targets:
                targets.append("design_views.physical_view")

        if not _has_non_empty_diagrams(_resolve_diagrams(hld, "process_view")):
            if "design_views.process_view" not in targets:
                targets.append("design_views.process_view")

        if not _has_non_empty_diagrams(_resolve_diagrams(hld, "data_flow")):
            if "data_design" not in targets:
                targets.append("data_design")

    # --------------------------------------------------
    # Deduplicate while preserving order
    # --------------------------------------------------
    deduped: list[str] = []
    for target in targets:
        if target not in deduped:
            deduped.append(target)

    return deduped


def _bump_section_retry_count(state: dict, target: Optional[str]) -> dict:
    counts = dict(state.get(KEY_SECTION_RETRY_COUNTS, {}) or {})
    if target:
        counts[target] = int(counts.get(target, 0)) + 1
    return counts


def _filter_retry_targets_for_progress_gate(
    state: dict,
    retry_targets: list[str],
) -> list[str]:
    """
    Progress gate must not fail for future sections that have not yet been generated.

    Rules:
    - If section retry mode is active, only validate the active retry target/queue.
    - If final validation is not ready, do not create retry targets for all missing future sections.
    - If final validation is ready, allow all detected retry targets.
    """
    retry_targets = retry_targets or []

    retry_mode = bool(state.get(KEY_SECTION_RETRY_MODE, False))
    active_target = state.get(KEY_SECTION_RETRY_TARGET)
    active_queue = state.get(KEY_SECTION_RETRY_QUEUE, []) or []

    if retry_mode:
        allowed = []

        if active_target:
            allowed.append(active_target)

        allowed.extend(active_queue)

        allowed_set = {x for x in allowed if x}

        return [target for target in retry_targets if target in allowed_set]

    if not is_hld_final_validation_ready(state):
        # Architect is still generating sections.
        # Do not mark future missing sections as failures.
        return []

    return retry_targets


# ==========================================================
# MALFORMED FUNCTION CALL DETECTION HELPERS
# ==========================================================
def _safe_event_get(event: Any, key: str, default: Any = None) -> Any:
    """
    Safely read a field from either:
    - ADK Event object
    - dict-shaped serialized event
    """
    if isinstance(event, dict):
        return event.get(key, default)

    # Try exact attribute
    if hasattr(event, key):
        return getattr(event, key, default)

    # Try common snake_case variants
    snake_map = {
        "errorCode": "error_code",
        "errorMessage": "error_message",
        "finishReason": "finish_reason",
    }

    snake_key = snake_map.get(key)
    if snake_key and hasattr(event, snake_key):
        return getattr(event, snake_key, default)

    return default


def _extract_recent_events(ctx: Any) -> list[Any]:
    """
    Best-effort extraction of recent session events from ADK context.

    This intentionally does not fail if event access differs by runtime.
    """
    session = getattr(ctx, "session", None)
    if session is None:
        return []

    events = getattr(session, "events", None)
    if isinstance(events, list):
        return events

    # Some runtimes expose events via state, though your JSON shows top-level events.
    state = getattr(session, "state", None)
    if isinstance(state, dict):
        state_events = state.get("events")
        if isinstance(state_events, list):
            return state_events

    return []


def _infer_retry_target_from_malformed_message(error_message: str) -> Optional[str]:
    """
    Dynamically infer section-only retry target from malformed function call text.

    Examples:
      print(default_api.commit_design_views_logical_view(...))
      -> design_views.logical_view

      default_api.commit_data_design(...)
      -> data_design

      commit_security(...)
      -> security

    Uses hld_section_commit_tools.section_name_from_commit_tool_name()
    as the single source of truth.
    """
    if not error_message:
        return None

    msg = str(error_message)

    # Capture possible commit tool names from malformed pseudo calls.
    # Supports:
    #   print(default_api.commit_xxx(...))
    #   default_api.commit_xxx(...)
    #   commit_xxx(...)
    matches = re.findall(
        r"\b(commit_[A-Za-z0-9_]+)\b",
        msg,
    )

    if not matches:
        return None

    for tool_name in matches:
        try:
            section_name = section_name_from_commit_tool_name(tool_name)

            if section_name:
                return section_name

        except Exception:
            logger.debug(
                "[ARCH_GATE] Could not dynamically map malformed tool name=%s",
                tool_name,
                exc_info=True,
            )

    return None


def _is_malformed_validation_error(error_message: Optional[str]) -> bool:
    """
    True when the validation error represents a malformed function-call issue.
    """
    if not error_message:
        return False

    msg = str(error_message)

    return (
        "MALFORMED_FUNCTION_CALL" in msg
        or "Malformed function call" in msg
        or "print(default_api." in msg
        or "default_api." in msg
    )


def _is_stale_malformed_validation_error(state: dict) -> bool:
    """
    Detect stale malformed validation error that should be cleared.

    This happens when:
    - Previous architect event produced malformed function call.
    - Validation gate set validation_error and retry target.
    - Architect retried the exact section successfully.
    - The old validation_error is still present in state.

    In that case, if the malformed target section is now committed, the error is stale.
    """
    error_message = state.get(KEY_VALIDATION_ERROR)

    if not _is_malformed_validation_error(error_message):
        return False

    retry_target = _infer_retry_target_from_malformed_message(str(error_message))

    if retry_target is None:
        retry_target = state.get(KEY_SECTION_RETRY_TARGET)

    if not retry_target:
        return False

    try:
        committed = is_hld_section_committed(state, retry_target)
    except Exception:
        logger.debug(
            "[ARCH_GATE] Could not check stale malformed committed status for target=%s",
            retry_target,
            exc_info=True,
        )
        return False

    if committed:
        logger.info(
            "[ARCH_GATE] Stale malformed validation error detected and can be cleared. "
            "target=%s",
            retry_target,
        )
        return True

    return False


def _extract_balanced_json_object(text: str, start_index: int) -> Optional[str]:
    """
    Extract a balanced JSON-like object starting at text[start_index] == '{'.

    Handles braces inside quoted strings.
    """
    if not isinstance(text, str):
        return None

    if start_index < 0 or start_index >= len(text) or text[start_index] != "{":
        return None

    depth = 0
    in_string = False
    escape = False

    for idx in range(start_index, len(text)):
        ch = text[idx]

        if ch == "\\" and not escape:
            escape = True
            continue

        if ch == '"' and not escape:
            in_string = not in_string

        escape = False

        if in_string:
            continue

        if ch == "{":
            depth += 1

        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_index:idx + 1]

    return None


def _extract_value_payload_from_malformed_message(error_message: str) -> Optional[dict]:
    """
    Extract the value={...} payload from malformed function call text.

    Supports malformed strings like:
      print(default_api.commit_design_views_process_view(value = {"diagrams": ["..."]}))
      default_api.commit_design_views_process_view(value = {"diagrams": ["..."]})
      commit_design_views_process_view(value = {"diagrams": ["..."]})

    Returns:
      dict payload, for example:
        {"diagrams": ["digraph ..."]}
    """
    if not error_message:
        return None

    text = str(error_message)

    # Prefer explicit "value =" / "value=" anchor.
    value_match = re.search(r"\bvalue\s*=", text)
    if value_match:
        brace_start = text.find("{", value_match.end())
    else:
        # Fallback: first object in the malformed call.
        brace_start = text.find("{")

    if brace_start < 0:
        return None

    obj_text = _extract_balanced_json_object(text, brace_start)
    if not obj_text:
        return None

    try:
        repaired = repair_json(obj_text)
        parsed = json.loads(repaired, strict=False)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        logger.debug(
            "[ARCH_GATE] Failed to parse malformed value payload. obj_text starts=%r",
            obj_text[:300],
            exc_info=True,
        )

    return None


def _attempt_direct_commit_from_malformed_call(
    *,
    ctx: Any,
    state: dict,
    malformed_target: Optional[str],
    error_message: str,
) -> Optional[dict]:
    """
    Last-resort recovery for repeated malformed native function calls.

    If the model emitted a malformed text/pseudo call but the payload is present,
    extract the payload and directly invoke the appropriate commit function.
    """
    if not malformed_target:
        return None

    # If section was committed between detection and recovery, do not overwrite.
    try:
        if is_hld_section_committed(state, malformed_target):
            logger.info(
                "[ARCH_GATE] Direct malformed recovery skipped because target is already committed: %s",
                malformed_target,
            )
            return {
                "status": "success",
                "message": f"Target already committed: {malformed_target}",
                "stateDelta": {},
                "state_delta": {},
            }
    except Exception:
        logger.debug(
            "[ARCH_GATE] Could not check committed state before direct recovery. target=%s",
            malformed_target,
            exc_info=True,
        )

    payload = _extract_value_payload_from_malformed_message(error_message)

    if not isinstance(payload, dict):
        logger.warning(
            "[ARCH_GATE] Direct malformed recovery skipped. Could not extract payload. target=%s",
            malformed_target,
        )
        return None

    try:
        commit_fn = get_hld_section_commit_function(malformed_target)
    except Exception:
        logger.exception(
            "[ARCH_GATE] Direct malformed recovery failed. Unknown commit function for target=%s",
            malformed_target,
        )
        return None

    try:
        logger.warning(
            "[ARCH_GATE] Attempting direct commit recovery for repeated malformed call. target=%s",
            malformed_target,
        )

        commit_result = commit_fn(
            value=payload,
            tool_context=ctx,
            confirmed=True,
        )

        if not isinstance(commit_result, dict):
            logger.error(
                "[ARCH_GATE] Direct commit recovery returned non-dict result. target=%s result=%r",
                malformed_target,
                commit_result,
            )
            return None

        if commit_result.get("status") != "success":
            logger.error(
                "[ARCH_GATE] Direct commit recovery failed. target=%s result=%r",
                malformed_target,
                commit_result,
            )
            return None

        logger.warning(
            "[ARCH_GATE] Direct commit recovery succeeded. target=%s",
            malformed_target,
        )

        return commit_result

    except Exception:
        logger.exception(
            "[ARCH_GATE] Direct commit recovery raised exception. target=%s",
            malformed_target,
        )
        return None


def detect_malformed_function_call(
    events: list[Any],
    state: Optional[dict] = None,
) -> Optional[dict]:
    """
    Detect MALFORMED_FUNCTION_CALL from the latest architect turn and convert it
    into a section-only retry instruction.

    Important:
    - Stops scanning when it reaches the previous validation gate event, so old
      malformed errors do not keep triggering forever.
    - If the inferred target is already committed, ignores stale malformed errors.
    """
    if not events:
        return None

    gate_authors = {
        "ArchitectureValidationGate",
        "FinalArchitectureValidationGate",
    }

    for event in reversed(events):
        author = _safe_event_get(event, "author")

        # Stop at previous validation boundary.
        # We only care about events since the previous gate pass.
        if author in gate_authors:
            break

        error_code = _safe_event_get(event, "errorCode")
        finish_reason = _safe_event_get(event, "finishReason")
        error_message = _safe_event_get(event, "errorMessage", "") or ""

        is_malformed = (
            error_code == "MALFORMED_FUNCTION_CALL"
            or finish_reason == "MALFORMED_FUNCTION_CALL"
            or "MALFORMED_FUNCTION_CALL" in error_message
            or "Malformed function call" in error_message
            or "print(default_api." in error_message
            or "default_api." in error_message
        )

        if not is_malformed:
            continue

        retry_target = _infer_retry_target_from_malformed_message(error_message)

        # Fallback to currently active retry target if tool name cannot be inferred.
        if retry_target is None and state is not None:
            retry_target = state.get(KEY_SECTION_RETRY_TARGET)

        # Avoid stale malformed events re-triggering after the section has already succeeded.
        if state is not None and retry_target:
            try:
                if is_hld_section_committed(state, retry_target):
                    logger.info(
                        "[ARCH_GATE] Ignoring stale malformed call because target is already committed: %s",
                        retry_target,
                    )
                    return None
            except Exception:
                logger.debug(
                    "[ARCH_GATE] Could not check committed state for malformed target: %s",
                    retry_target,
                    exc_info=True,
                )

        return {
            KEY_VALIDATION_ERROR: error_message or "MALFORMED_FUNCTION_CALL",
            KEY_ARCH_VALID: False,
            KEY_ARCH_COMPLETE: False,
            KEY_SECTION_RETRY_TARGET: retry_target,
            KEY_SECTION_RETRY_QUEUE: [retry_target] if retry_target else [],
            KEY_SECTION_RETRY_MODE: bool(retry_target),
        }

    return None


# ==========================================================
# SECTION PROGRESS GATE (IN-LOOP)
# ==========================================================
class ArchitectureValidationGate(BaseAgent):
    """
    IN-LOOP section progress gate.

    IMPORTANT:
    - This gate NO LONGER performs final full-document validation on every pass.
    - It only decides whether more section-level retry is needed.
    - Full HLD / final validation is handled by FinalArchitectureValidationGate
      AFTER the architect loop finishes.

    Behavior:
    - Detect missing/empty committed sections
    - Detect missing required diagram sub-sections
    - Detect malformed function-call failures
    - Set section retry target + queue
    - Stop loop ONLY when no retry targets remain
    """

    name: str = "ArchitectureValidationGate"
    description: str = "In-loop section progress validator and retry target selector."

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        state = ctx.session.state or {}

        arch_valid_flag = state.get(KEY_ARCH_VALID, True)

        # --------------------------------------------------
        # Clear stale malformed validation error if section retry already succeeded.
        # This fixes the case where interfaces retry succeeded but old
        # validation_error kept architecture_valid=false forever.
        # --------------------------------------------------
        if arch_valid_flag is False and _is_stale_malformed_validation_error(state):
            logger.info(
                "[ARCH_GATE] Clearing stale malformed validation error before progress validation."
            )

            arch_valid_flag = True
            state[KEY_ARCH_VALID] = True
            state[KEY_VALIDATION_ERROR] = None
            state[KEY_SECTION_RETRY_TARGET] = None
            state[KEY_SECTION_RETRY_QUEUE] = []
            state[KEY_SECTION_RETRY_MODE] = False

        # --------------------------------------------------
        # Detect malformed native function call from latest architect turn
        # before normal section completeness validation.
        # --------------------------------------------------
        recent_events = _extract_recent_events(ctx)
        logger.debug(
            "[ARCH_GATE] Malformed detection scanning recent events count=%s",
            len(recent_events),
        )

        malformed_result = detect_malformed_function_call(recent_events, state)

        if malformed_result:
            malformed_target = malformed_result.get(KEY_SECTION_RETRY_TARGET)
            malformed_error_message = malformed_result.get(KEY_VALIDATION_ERROR, "") or ""

            section_retry_counts = _bump_section_retry_count(state, malformed_target)
            current_malformed_count = int(
                section_retry_counts.get(malformed_target, 0)
            ) if malformed_target else 0

            # --------------------------------------------------
            # HARD RECOVERY:
            # After repeated malformed native calls for the same section,
            # extract the payload from the malformed text and commit directly.
            # --------------------------------------------------
            if (
                malformed_target
                and current_malformed_count >= MAX_MALFORMED_NATIVE_TOOL_RETRIES
            ):
                commit_result = _attempt_direct_commit_from_malformed_call(
                    ctx=ctx,
                    state=state,
                    malformed_target=malformed_target,
                    error_message=str(malformed_error_message),
                )

                if commit_result and commit_result.get("status") == "success":
                    commit_state_delta = (
                        commit_result.get("stateDelta")
                        or commit_result.get("state_delta")
                        or {}
                    )

                    recovery_state_delta = {
                        **commit_state_delta,
                        KEY_VALIDATION_ERROR: None,
                        KEY_ARCH_VALID: True,
                        KEY_ARCH_COMPLETE: False,
                        KEY_SECTION_RETRY_TARGET: None,
                        KEY_SECTION_RETRY_QUEUE: [],
                        KEY_SECTION_RETRY_MODE: False,
                        KEY_SECTION_RETRY_COUNTS: section_retry_counts,
                    }

                    yield Event(
                        author=self.name,
                        content=types.Content(
                            role="model",
                            parts=[
                                types.Part(
                                    text=(
                                        "✅ Recovered from repeated malformed architect function call.\n"
                                        f"Committed section directly: {malformed_target}\n"
                                        "Continuing section generation."
                                    )
                                )
                            ],
                        ),
                        actions=EventActions(
                            escalate=False,
                            state_delta=recovery_state_delta,
                        ),
                    )
                    return

                logger.warning(
                    "[ARCH_GATE] Direct malformed recovery did not succeed. "
                    "Continuing native retry. target=%s count=%s",
                    malformed_target,
                    current_malformed_count,
                )

            malformed_state_delta = dict(malformed_result)
            malformed_state_delta[KEY_SECTION_RETRY_COUNTS] = section_retry_counts

            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[
                        types.Part(
                            text=(
                                "❌ Malformed architect function call detected.\n"
                                f"Section-only retry target: {malformed_target or 'NONE'}\n"
                                f"Malformed retry count: {current_malformed_count}\n"
                                "ArchitectSubAgent: Retry ONLY the targeted section using a native tool call."
                            )
                        )
                    ],
                ),
                actions=EventActions(
                    escalate=False,
                    state_delta=malformed_state_delta,
                ),
            )
            return

        # --------------------------------------------------
        # Optional best-effort assembly for richer retry detection
        # --------------------------------------------------
        hld = None

        try:
            section_report = validate_required_hld_sections(state)
        except Exception as e:
            logger.exception("[ARCH_GATE] Failed section completeness check: %s", e)
            section_report = {"all_present": False, "missing_sections": []}

        try:
            section_quality_report = validate_hld_section_quality(state)
        except Exception as e:
            logger.exception("[ARCH_GATE] Failed section quality check: %s", e)
            section_quality_report = {"all_non_empty": True, "empty_sections": []}

        if not section_quality_report.get("all_non_empty", True):
            logger.warning(
                "[ARCH_GATE] Some committed HLD sections are present but empty: %s",
                section_quality_report.get("empty_sections", []),
            )

        if section_report.get("all_present"):
            try:
                assembled_hld = assemble_hld_from_state(state)
                state[KEY_HLD_REPORT_JSON] = assembled_hld
                hld = _coerce_hld_to_dict(assembled_hld)
                logger.info("[ARCH_GATE] Section-wise assembly succeeded during progress check.")
            except Exception as e:
                logger.debug("[ARCH_GATE] Assembly not ready during progress check: %s", e)
                hld = _coerce_hld_to_dict(state.get(KEY_HLD_REPORT_JSON))
        else:
            hld = _coerce_hld_to_dict(state.get(KEY_HLD_REPORT_JSON))

        # --------------------------------------------------
        # Detect missing retry targets
        # --------------------------------------------------
        raw_retry_targets = _detect_retry_targets(state, hld)

        # IMPORTANT:
        # Progress gate must not fail for sections that are simply not generated yet.
        retry_targets = _filter_retry_targets_for_progress_gate(state, raw_retry_targets)

        current_retry_target = retry_targets[0] if retry_targets else None

        # --------------------------------------------------
        # If architecture was marked invalid but filtering removed targets,
        # preserve existing active retry target if available.
        # This avoids invalid state with retry_target=None.
        # --------------------------------------------------
        if arch_valid_flag is False and not retry_targets:
            existing_target = state.get(KEY_SECTION_RETRY_TARGET)
            existing_queue = state.get(KEY_SECTION_RETRY_QUEUE, []) or []

            if _is_stale_malformed_validation_error(state):
                logger.info(
                    "[ARCH_GATE] Clearing stale malformed invalid flag after retry target succeeded."
                )

                arch_valid_flag = True
                retry_targets = []
                current_retry_target = None

                state[KEY_ARCH_VALID] = True
                state[KEY_VALIDATION_ERROR] = None
                state[KEY_SECTION_RETRY_TARGET] = None
                state[KEY_SECTION_RETRY_QUEUE] = []
                state[KEY_SECTION_RETRY_MODE] = False

            elif existing_target:
                retry_targets = [existing_target]

            elif existing_queue:
                retry_targets = existing_queue

            elif not is_hld_final_validation_ready(state):
                # Stale invalid flag while architect is still generating future sections.
                # Do not fail progress gate with retry_target=None.
                logger.info(
                    "[ARCH_GATE] Clearing stale invalid flag because final validation is not ready. Pending=%s",
                    get_missing_hld_sections(state),
                )

                arch_valid_flag = True
                retry_targets = []
                state[KEY_ARCH_VALID] = True
                state[KEY_VALIDATION_ERROR] = None
                state[KEY_SECTION_RETRY_TARGET] = None
                state[KEY_SECTION_RETRY_QUEUE] = []
                state[KEY_SECTION_RETRY_MODE] = False

            current_retry_target = retry_targets[0] if retry_targets else None

        if raw_retry_targets and not retry_targets and not is_hld_final_validation_ready(state):
            logger.info(
                "[ARCH_GATE] Progress validation deferred. Pending future sections=%s",
                get_missing_hld_sections(state),
            )

        # --------------------------------------------------
        # SUCCESS / CONTINUE DECISION
        # --------------------------------------------------
        if not retry_targets and arch_valid_flag is not False:
            final_ready = is_hld_final_validation_ready(state)

            if final_ready:
                message = "✅ Section generation complete. Proceeding to final HLD validation."
                should_escalate = True
            else:
                message = (
                    "✅ Section progress check passed for current pass. "
                    "Remaining sections are still pending generation."
                )
                should_escalate = False

            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=message)]
                ),
                actions=EventActions(
                    escalate=should_escalate,
                    state_delta={
                        KEY_VALIDATION_ERROR: None,
                        KEY_ARCH_VALID: True,
                        KEY_ARCH_COMPLETE: False,
                        KEY_SECTION_RETRY_TARGET: None,
                        KEY_SECTION_RETRY_QUEUE: [],
                        KEY_SECTION_RETRY_MODE: False,
                    },
                ),
            )
            return

        # --------------------------------------------------
        # FAILURE / CONTINUE LOOP
        # --------------------------------------------------
        reason_parts = []

        if retry_targets:
            reason_parts.append(f"Missing/invalid section targets: {', '.join(retry_targets)}")

        if arch_valid_flag is False:
            reason_parts.append(state.get(KEY_VALIDATION_ERROR, "Technical requirements not met."))

        reason = " | ".join(reason_parts) if reason_parts else "Section progress incomplete."

        section_retry_counts = _bump_section_retry_count(state, current_retry_target)

        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=(
                            f"❌ Section progress incomplete: {reason}\n"
                            f"Section-only retry target: {current_retry_target or 'NONE'}\n"
                            "ArchitectSubAgent: Please correct ONLY the targeted section and try again."
                        )
                    )
                ],
            ),
            actions=EventActions(
                escalate=False,
                state_delta={
                    KEY_VALIDATION_ERROR: reason,
                    KEY_ARCH_COMPLETE: False,
                    KEY_ARCH_VALID: False,
                    KEY_SECTION_RETRY_TARGET: current_retry_target,
                    KEY_SECTION_RETRY_QUEUE: retry_targets,
                    KEY_SECTION_RETRY_MODE: bool(current_retry_target),
                    KEY_SECTION_RETRY_COUNTS: section_retry_counts,
                },
            ),
        )


# ==========================================================
# FINAL FULL-DOCUMENT VALIDATION GATE (OUTSIDE LOOP)
# ==========================================================
class FinalArchitectureValidationGate(BaseAgent):
    """
    FINAL validator step:
    - Runs ONCE after architect loop section generation settles
    - Assembles HLD from committed section state if possible
    - Validates full HLD JSON presence / parseability
    - Validates mandatory architecture views
    - On success => marks KEY_ARCH_COMPLETE=True
    - On failure => sets retry targets so orchestrator can re-enter architect loop
    """

    name: str = "FinalArchitectureValidationGate"
    description: str = "Final full-document HLD validator."

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        state = ctx.session.state or {}

        arch_valid_flag = state.get(KEY_ARCH_VALID, True)

        # --------------------------------------------------
        # Clear stale malformed validation error before final validation.
        # This is required because the in-loop retry may have succeeded,
        # but the old validation_error can still remain in state.
        # --------------------------------------------------
        if arch_valid_flag is False and _is_stale_malformed_validation_error(state):
            logger.info(
                "[FINAL_ARCH_GATE] Clearing stale malformed validation error before final validation."
            )

            arch_valid_flag = True
            state[KEY_ARCH_VALID] = True
            state[KEY_VALIDATION_ERROR] = None
            state[KEY_SECTION_RETRY_TARGET] = None
            state[KEY_SECTION_RETRY_QUEUE] = []
            state[KEY_SECTION_RETRY_MODE] = False

        valid = True
        reason = None

        # --------------------------------------------------
        # Do not perform final validation until all dynamic
        # HLD sections are actually present.
        # --------------------------------------------------
        if not is_hld_final_validation_ready(state):
            missing_sections = get_missing_hld_sections(state)
            reason = "Final validation deferred. Missing sections: " + ", ".join(missing_sections)

            logger.info("[FINAL_ARCH_GATE] %s", reason)

            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text=f"ℹ️ {reason}")]
                ),
                actions=EventActions(
                    escalate=False,
                    state_delta={
                        KEY_VALIDATION_ERROR: None,
                        KEY_ARCH_COMPLETE: False,
                        KEY_ARCH_VALID: True,
                        KEY_SECTION_RETRY_TARGET: None,
                        KEY_SECTION_RETRY_QUEUE: [],
                        KEY_SECTION_RETRY_MODE: False,
                    },
                ),
            )
            return

        raw_hld = None
        section_report = {"all_present": False, "missing_sections": []}
        section_quality_report = {"all_non_empty": True, "empty_sections": []}

        try:
            section_report = validate_required_hld_sections(state)
        except Exception as e:
            logger.exception("[FINAL_ARCH_GATE] Failed section completeness check: %s", e)

        try:
            section_quality_report = validate_hld_section_quality(state)
        except Exception as e:
            logger.exception("[FINAL_ARCH_GATE] Failed section quality check: %s", e)

        if not section_quality_report.get("all_non_empty", True):
            logger.warning(
                "[FINAL_ARCH_GATE] Some committed HLD sections are present but empty: %s",
                section_quality_report.get("empty_sections", []),
            )

        if section_report.get("all_present"):
            try:
                assembled_hld = assemble_hld_from_state(state)
                state[KEY_HLD_REPORT_JSON] = assembled_hld
                raw_hld = assembled_hld
                logger.info("[FINAL_ARCH_GATE] ✅ Successfully assembled HLD from section-wise state.")
            except Exception as e:
                logger.exception("[FINAL_ARCH_GATE] ❌ Failed assembling HLD from section-wise state: %s", e)
                raw_hld = state.get(KEY_HLD_REPORT_JSON)
        else:
            raw_hld = state.get(KEY_HLD_REPORT_JSON)

        hld = _coerce_hld_to_dict(raw_hld)

        # --------------------------------------------------
        # A) Presence / parseability of HLD JSON
        # --------------------------------------------------
        if hld is None:
            valid = False
            missing = section_report.get("missing_sections", [])
            empty_sections = section_quality_report.get("empty_sections", [])

            if missing:
                reason = (
                    f"Missing or invalid {KEY_HLD_REPORT_JSON}. "
                    f"Also missing committed HLD sections: {', '.join(missing)}"
                )
            elif empty_sections:
                reason = (
                    f"Missing or invalid {KEY_HLD_REPORT_JSON}. "
                    f"Committed sections exist but some are empty: {', '.join(empty_sections)}"
                )
            else:
                reason = f"Missing or invalid {KEY_HLD_REPORT_JSON}."

        # --------------------------------------------------
        # B) Mandatory architecture diagram validation
        # --------------------------------------------------
        elif isinstance(hld, dict):
            missing_views = []

            for view in ["logical_view", "physical_view", "process_view", "data_flow"]:
                diagrams = _resolve_diagrams(hld, view)
                if not _has_non_empty_diagrams(diagrams):
                    missing_views.append(f"{view}.diagrams")

            if missing_views:
                valid = False
                reason = "MANDATORY ARCHITECTURE VIEW(S) MISSING OR EMPTY: " + ", ".join(missing_views)
                logger.error("❌ Final Diagram Validation Error: %s", reason)

        # --------------------------------------------------
        # C) Technical validity flag coming from orchestrator/backend
        # --------------------------------------------------
        if arch_valid_flag is False:
            # Re-check stale malformed once more to avoid blocking final validation
            # because of old event-level error after successful section retry.
            if _is_stale_malformed_validation_error(state):
                logger.info(
                    "[FINAL_ARCH_GATE] Ignoring stale malformed validation error because target section is committed."
                )

                arch_valid_flag = True
                state[KEY_ARCH_VALID] = True
                state[KEY_VALIDATION_ERROR] = None
                state[KEY_SECTION_RETRY_TARGET] = None
                state[KEY_SECTION_RETRY_QUEUE] = []
                state[KEY_SECTION_RETRY_MODE] = False
            else:
                valid = False
                reason = state.get(KEY_VALIDATION_ERROR, "Technical requirements not met.")

        # --------------------------------------------------
        # SUCCESS PATH
        # --------------------------------------------------
        if valid:
            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="✅ Final architecture validated. Proceeding.")]
                ),
                actions=EventActions(
                    escalate=True,
                    state_delta={
                        KEY_VALIDATION_ERROR: None,
                        KEY_ARCH_VALID: True,
                        KEY_ARCH_COMPLETE: True,
                        "arch_validation_attempts": 0,
                        KEY_SECTION_RETRY_TARGET: None,
                        KEY_SECTION_RETRY_QUEUE: [],
                        KEY_SECTION_RETRY_MODE: False,
                    },
                ),
            )
            return

        # --------------------------------------------------
        # FAILURE PATH
        # --------------------------------------------------
        retry_targets = _detect_retry_targets(state, hld)
        current_retry_target = retry_targets[0] if retry_targets else None
        section_retry_counts = _bump_section_retry_count(state, current_retry_target)

        curr_attempts = int(state.get("arch_validation_attempts", 0)) + 1

        yield Event(
            author=self.name,
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=(
                            f"❌ Final validation failed: {reason}\n"
                            f"Section-only retry target: {current_retry_target or 'NONE'}\n"
                            "ArchitectSubAgent: Please correct ONLY the targeted section and try again."
                        )
                    )
                ],
            ),
            actions=EventActions(
                escalate=False,
                state_delta={
                    KEY_VALIDATION_ERROR: reason,
                    KEY_ARCH_COMPLETE: False,
                    KEY_ARCH_VALID: False,
                    "arch_validation_attempts": curr_attempts,
                    KEY_SECTION_RETRY_TARGET: current_retry_target,
                    KEY_SECTION_RETRY_QUEUE: retry_targets,
                    KEY_SECTION_RETRY_MODE: bool(current_retry_target),
                    KEY_SECTION_RETRY_COUNTS: section_retry_counts,
                },
            ),
        )


# ==========================================================
# LOOP CONFIG
# ==========================================================
arch_validation_gate = ArchitectureValidationGate()
final_arch_validation_gate = FinalArchitectureValidationGate()

architect_loop = LoopAgent(
    name="ArchitectLoop",
    description="Repeat section generation until no more section retry targets remain.",
    sub_agents=[architect_agent, arch_validation_gate],
    # Increased to allow section-only retries across multiple sections
    max_iterations=25,
)