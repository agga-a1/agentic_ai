import os
import re
import json
from typing import AsyncGenerator, Any, Optional

from google.adk.agents import SequentialAgent
from google.adk.events import Event, EventActions
from google.genai import types
from json_repair import repair_json

from .logging_setup import get_logger

from tools.hld_section_commit_tools import (
    assemble_hld_from_state,
    validate_required_hld_sections,
    validate_hld_section_quality,
    get_missing_hld_sections,
    is_hld_final_validation_ready,
    section_name_from_commit_tool_name,
    is_hld_section_committed,
)

from agent.intake_agent.agent import intake_agent
from agent.blueprint_agent.agent import blueprint_agent
from agent.research_agent.agent import research_agent
from agent.doc_rendering_agent.agent import doc_rendering_agent
from agent.output_agent.agent import output_agent
from agent.workflow.architect_loop import architect_loop, final_arch_validation_gate
from schema_types.aia_intake_schema import IntakeSchema

# Import centralized keys for gate logic
from agent.workflow.keys import (
    KEY_INTAKE,
    KEY_INTAKE_COMPLETE,
    KEY_INTAKE_CONFIRMED,
    KEY_INTAKE_MISSING_FIELDS,
    KEY_INTAKE_VALIDATION_ERROR,

    KEY_BLUEPRINT_RESULTS,
    KEY_BLUEPRINT_SELECTED,
    KEY_BLUEPRINT_SEARCH_DONE,
    KEY_BLUEPRINT_NO_MATCH,

    KEY_RESEARCH_RESOLVED,
    KEY_TECHNICAL_RESEARCH_SUMMARY,
    KEY_RESOLVED_SERVICES,
    KEY_RESEARCH_RETRY_COUNT,
    KEY_RESEARCH_RETRY_MAX,
    KEY_RESEARCH_RETRY_REASON,

    KEY_ARCH_COMPLETE,
    KEY_ARCH_VALID,
    KEY_VALIDATION_ERROR,
    KEY_HLD_REPORT_JSON,
    KEY_HLD_COMMIT_TRIGGERED,
    KEY_HLD_SECTION_STATE_PREFIX,

    KEY_DOC_RENDERED,
    KEY_RENDER_ARTIFACT,
    KEY_RENDERED_PDF_PATH,
    KEY_LOCAL_DOWNLOAD_URLS,
    KEY_LOCAL_VIEW_URLS,

    KEY_WORKFLOW_RESET_REQUESTED,
    KEY_REVISION_REQUESTED,
    KEY_REVISION_NOTES,
    KEY_REVISION_CONTEXT,
    KEY_REVISION_READY,
    KEY_ORIGINAL_USER_REQUEST,

    KEY_SELECTED_SECTIONS,
    KEY_RENDER_SELECTED_SECTIONS,
    KEY_USER_REQUEST,

    KEY_SECTION_RETRY_TARGET,
    KEY_SECTION_RETRY_QUEUE,
    KEY_SECTION_RETRY_COUNTS,
    KEY_SECTION_RETRY_MODE,
)


logger = get_logger("AIA_Engine")


# ==========================================================
# INTERNAL / PRIVATE STATE KEYS
# ==========================================================
INTERNAL_LAST_REVISION_USER_EVENT_ID = "_last_revision_user_event_id"
INTERNAL_LAST_REVISION_TEXT = "_last_revision_text"

# Output lifecycle guards.
# These prevent normal intake / auto-continue messages from being treated as revisions.
INTERNAL_OUTPUT_PENDING = "_output_pending"
INTERNAL_OUTPUT_DELIVERED = "_output_delivered"
INTERNAL_FINAL_OUTPUT_READY = "_final_output_ready"
INTERNAL_REVISION_RUN_ACTIVE = "_revision_run_active"
DEFAULT_RESEARCH_RETRY_MAX = 2


# ==========================================================
# HELPERS
# ==========================================================
async def _run_arch_validation_gate_if_needed(self, context, validation_gate):
    """
    Force/re-run the architecture validation gate so that retry target/queue
    is rebuilt whenever the architecture is invalid or incomplete.
    Safe additive helper.
    """
    if validation_gate is None:
        return

    async for gate_event in validation_gate.run_async(context):
        yield gate_event

        gate_state_delta = _get_event_state_delta_from_gate_event(gate_event)
        if gate_state_delta:
            context.session.state.update(gate_state_delta)


def _normalize_selected_sections(value: Any) -> list[str]:
    """
    Normalize selected sections from UI/state.

    Supports:
    - list[str]
    - comma-separated string
    - JSON string list
    """
    if value is None:
        return []

    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []

        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass

        return [x.strip() for x in raw.split(",") if x.strip()]

    return []


def _preserve_render_selected_sections(state: dict) -> None:
    """
    Preserve user/UI-selected sections for final rendering.

    KEY_SELECTED_SECTIONS may be temporarily overwritten during section retry.
    KEY_RENDER_SELECTED_SECTIONS is the stable final document filter.
    """
    if not isinstance(state, dict):
        return

    existing_render_sections = _normalize_selected_sections(
        state.get(KEY_RENDER_SELECTED_SECTIONS)
    )
    if existing_render_sections:
        return

    selected_sections = _normalize_selected_sections(state.get(KEY_SELECTED_SECTIONS))
    if selected_sections:
        state[KEY_RENDER_SELECTED_SECTIONS] = selected_sections


def _apply_state_delta_to_session(context, state_delta: dict) -> None:
    """
    Apply a state_delta to current session state immediately.

    Important:
    - None means delete/pop locally.
    - Non-None means set/update locally.
    - The same state_delta can still be emitted via EventActions for durable state.
    """
    if not isinstance(state_delta, dict):
        return

    state = context.session.state or {}

    for key, value in state_delta.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value

    context.session.state = state


def _get_intake_schema_field_names(include_optional: bool = True) -> list[str]:
    """
    Return canonical intake field names from IntakeSchema.
    """
    if IntakeSchema is None:
        logger.warning(
            "[FLOW] IntakeSchema import unavailable. Falling back to existing intake/top-level keys."
        )
        return []

    fields = []
    for field_name, field_info in IntakeSchema.model_fields.items():
        if include_optional or field_info.is_required():
            fields.append(field_name)

    return fields


def _get_required_intake_schema_field_names() -> list[str]:
    """
    Return only required intake fields from IntakeSchema.
    Optional fields such as additional_context are excluded.
    """
    if IntakeSchema is None:
        return []

    return [
        field_name
        for field_name, field_info in IntakeSchema.model_fields.items()
        if field_info.is_required()
    ]
    
def _get_intake_field_aliases(field_name: str, field_info) -> list[str]:
    """
    Return canonical field name plus validation aliases from IntakeSchema.

    This is needed because fast-track document/table parsing may store
    display labels such as "Project Name", while orchestrator recovery
    expects canonical snake_case keys such as "project_name".

    Example:
        field_name = "project_name"
        aliases -> ["project_name", "Project Name"]
    """
    aliases = [field_name]

    validation_alias = getattr(field_info, "validation_alias", None)

    if validation_alias is None:
        return aliases

    # Pydantic AliasChoices exposes aliases via .choices
    choices = getattr(validation_alias, "choices", None)

    if choices:
        for choice in choices:
            if isinstance(choice, str) and choice not in aliases:
                aliases.append(choice)
        return aliases

    # Defensive fallback if validation_alias is a direct string
    if isinstance(validation_alias, str) and validation_alias not in aliases:
        aliases.append(validation_alias)

    return aliases

def _build_intake_from_state_using_schema(state: dict) -> dict:
    """
    Rebuild canonical intake dict using IntakeSchema field names.

    Priority:
    1. state[KEY_INTAKE][canonical field]
    2. state[canonical field]
    3. state[KEY_INTAKE][validation alias]
    4. state[validation alias]

    Important:
    - IntakeSchema supports aliases such as "Project Name".
    - Fast-track document/table parsing may store those display labels.
    - This function must recover aliases and normalize them back to canonical
      snake_case field names.
    """
    if not isinstance(state, dict):
        return {}

    intake = state.get(KEY_INTAKE)
    if not isinstance(intake, dict):
        intake = {}

    if IntakeSchema is None:
        logger.warning(
            "[FLOW] IntakeSchema import unavailable. Falling back to existing intake/top-level keys."
        )

        recovered_intake = {}

        for key, value in intake.items():
            if _is_non_empty_value(value):
                recovered_intake[key] = value

        for key, value in state.items():
            if (
                isinstance(key, str)
                and not key.startswith("_")
                and _is_non_empty_value(value)
                and key not in recovered_intake
            ):
                recovered_intake[key] = value

        return recovered_intake

    recovered_intake = {}

    for field_name, field_info in IntakeSchema.model_fields.items():
        aliases = _get_intake_field_aliases(field_name, field_info)

        value = None

        # 1. Canonical field inside KEY_INTAKE
        if _is_non_empty_value(intake.get(field_name)):
            value = intake.get(field_name)

        # 2. Canonical field at top-level state
        elif _is_non_empty_value(state.get(field_name)):
            value = state.get(field_name)

        # 3. Alias keys inside KEY_INTAKE or top-level state
        else:
            for alias in aliases:
                if _is_non_empty_value(intake.get(alias)):
                    value = intake.get(alias)
                    break

                if _is_non_empty_value(state.get(alias)):
                    value = state.get(alias)
                    break

        if _is_non_empty_value(value):
            recovered_intake[field_name] = value

    return recovered_intake


def _missing_required_intake_fields_using_schema(intake_payload: dict) -> list[str]:
    """
    Determine missing required intake fields using IntakeSchema.
    """
    required_fields = _get_required_intake_schema_field_names()

    if not required_fields:
        return []

    if not isinstance(intake_payload, dict):
        intake_payload = {}

    return [
        field_name
        for field_name in required_fields
        if not _is_non_empty_value(intake_payload.get(field_name))
    ]

# def _get_intake_field_aliases(field_name: str, field_info) -> list[str]:
#     """
#     Return canonical field name plus validation aliases from IntakeSchema.

#     Required because fast-track document/table extraction may store display labels
#     such as "Project Name", while orchestrator recovery expects canonical keys
#     such as "project_name".
#     """
#     aliases = [field_name]

#     validation_alias = getattr(field_info, "validation_alias", None)

#     if validation_alias is not None:
#         choices = getattr(validation_alias, "choices", None)

#         if choices:
#             for choice in choices:
#                 if isinstance(choice, str) and choice not in aliases:
#                     aliases.append(choice)
#         elif isinstance(validation

def _validate_intake_payload_with_schema(intake_payload: dict) -> bool:
    """
    Validate intake payload against IntakeSchema.
    """
    if IntakeSchema is None:
        missing = _missing_required_intake_fields_using_schema(intake_payload)
        return not missing

    try:
        IntakeSchema.model_validate(intake_payload)
        return True
    except Exception as exc:
        logger.warning("[FLOW] IntakeSchema validation failed during recovery: %s", exc)
        return False


def _looks_like_malformed_tool_text(text: str) -> bool:
    """
    Detect assistant-visible pseudo tool-call text such as:
    - print(default_api.commit_xxx(...))
    - default_api.commit_xxx(...)
    - textual commit_xxx(...)
    """
    if not text:
        return False

    lowered = text.lower()

    if "print(" in lowered:
        return True

    if "default_api." in lowered:
        return True

    if "commit_" in lowered and "(" in lowered and ")" in lowered:
        return True

    return False


def _infer_section_from_malformed_tool_text(text: str) -> Optional[str]:
    """
    Infer section retry target from malformed textual tool call.
    """
    if not text:
        return None

    match = re.search(r"\b(commit_[a-zA-Z0-9_]+)\s*\(", text)
    if not match:
        return None

    return section_name_from_commit_tool_name(match.group(1))


def _is_malformed_retry_error(state: dict) -> bool:
    """
    True when current invalid/retry state is caused by malformed tool-call output.
    """
    error_text = str(state.get(KEY_VALIDATION_ERROR) or "")
    error_lower = error_text.lower()

    return (
        "malformed_function_call" in error_lower
        or "malformed function call" in error_lower
        or "malformed textual" in error_lower
        or "pseudo tool" in error_lower
        or "default_api." in error_text
        or "print(default_api." in error_text
    )


def _get_event_state_delta_from_gate_event(gate_event) -> dict:
    """
    Safely extract state delta from validation gate events.
    """
    gate_actions = getattr(gate_event, "actions", None)

    if gate_actions is None:
        return {}

    gate_state_delta = (
        getattr(gate_actions, "state_delta", None)
        or getattr(gate_actions, "stateDelta", None)
        or (gate_actions.get("state_delta") if isinstance(gate_actions, dict) else None)
        or (gate_actions.get("stateDelta") if isinstance(gate_actions, dict) else None)
        or {}
    )

    return gate_state_delta if isinstance(gate_state_delta, dict) else {}


def _strip_code_fences(text: str) -> str:
    """
    Removes markdown code fences such as:
    ```json
    {...}
    ```
    """
    if not text:
        return ""

    text = text.strip()

    fenced_match = re.match(r"^```(?:json|JSON)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced_match:
        return fenced_match.group(1).strip()

    text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_hld_json(payload: Any) -> Optional[dict]:
    """
    Normalize payload into a dict if possible.
    """
    if payload is None:
        return None

    if isinstance(payload, dict):
        return payload

    if hasattr(payload, "model_dump") and callable(payload.model_dump):
        try:
            dumped = payload.model_dump()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass

    if hasattr(payload, "dict") and callable(payload.dict):
        try:
            dumped = payload.dict()
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass

    if isinstance(payload, str):
        cleaned = _strip_code_fences(payload)
        if not cleaned:
            return None

        try:
            parsed = json.loads(cleaned, strict=False)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            try:
                fixed_cleaned = repair_json(cleaned)
                parsed = json.loads(fixed_cleaned, strict=False)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

        start_idx = cleaned.find("{")
        if start_idx != -1:
            raw_input = cleaned[start_idx:]
            try:
                decoder = json.JSONDecoder(strict=False)
                parsed, _ = decoder.raw_decode(raw_input)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

    return None


def _store_hld_in_state(context, hld_payload: dict) -> None:
    """
    Persist parsed HLD JSON into session state.
    """
    state = context.session.state or {}
    state[KEY_HLD_REPORT_JSON] = hld_payload
    state[KEY_HLD_COMMIT_TRIGGERED] = False
    context.session.state = state
    logger.info("✅ HLD payload stored in session state.")


def _persist_hld_state(context, hld_payload: dict) -> dict:
    """
    Persist parsed HLD JSON into session state AND return a state_delta
    so it can also be emitted as an internal event for durable persistence.
    """
    state_delta = {
        KEY_HLD_REPORT_JSON: hld_payload,
        KEY_HLD_COMMIT_TRIGGERED: False,
    }

    state = context.session.state or {}
    state.update(state_delta)
    context.session.state = state

    logger.info(
        "✅ HLD payload stored in session state. Top-level keys: %s",
        list(hld_payload.keys())[:20] if isinstance(hld_payload, dict) else "non-dict",
    )
    return state_delta


def _architect_author_names(loop_agent) -> set:
    """
    Best-effort architect agent author-name detection.
    """
    names = {"ArchitectSubAgent", "architect_agent"}
    try:
        sub_agents = getattr(loop_agent, "sub_agents", []) or []
        if sub_agents:
            agent_name = getattr(sub_agents[0], "name", None)
            if agent_name:
                names.add(agent_name)
    except Exception:
        pass
    return names


def _promote_retry_target_from_queue(state: dict) -> None:
    """
    If retry queue exists but target is missing, promote first queue item.
    """
    retry_queue = state.get(KEY_SECTION_RETRY_QUEUE, []) or []
    retry_target = state.get(KEY_SECTION_RETRY_TARGET)

    if not retry_target and retry_queue:
        state[KEY_SECTION_RETRY_TARGET] = retry_queue[0]
        state[KEY_SECTION_RETRY_MODE] = True


def _force_selected_sections_for_retry(state: dict) -> None:
    """
    Force architect to generate only retry target.
    This prevents full document regeneration during section-only retry.

    Important:
    Preserve original UI-selected render sections before temporarily overriding
    KEY_SELECTED_SECTIONS for retry.
    """
    _preserve_render_selected_sections(state)
    _promote_retry_target_from_queue(state)

    retry_target = state.get(KEY_SECTION_RETRY_TARGET)
    retry_mode = bool(state.get(KEY_SECTION_RETRY_MODE, False))

    if retry_mode and retry_target:
        state[KEY_SELECTED_SECTIONS] = [retry_target]


def _remove_committed_retry_target(state: dict, section_name: str) -> None:
    """
    Remove successfully committed retry target from retry queue.
    """
    if not section_name:
        return

    retry_queue = state.get(KEY_SECTION_RETRY_QUEUE, []) or []
    retry_queue = [x for x in retry_queue if x != section_name]

    state[KEY_SECTION_RETRY_QUEUE] = retry_queue

    if retry_queue:
        state[KEY_SECTION_RETRY_TARGET] = retry_queue[0]
        state[KEY_SECTION_RETRY_MODE] = True
        state[KEY_SELECTED_SECTIONS] = [retry_queue[0]]
    else:
        state[KEY_SECTION_RETRY_TARGET] = None
        state[KEY_SECTION_RETRY_MODE] = False
        state.pop(KEY_SELECTED_SECTIONS, None)


def _clear_stale_arch_validation_error_if_not_final_ready(state: dict) -> None:
    """
    If document generation is still in progress, missing future sections
    should not keep architecture invalid.
    """
    if not is_hld_final_validation_ready(state):
        state[KEY_ARCH_VALID] = True
        state.pop(KEY_VALIDATION_ERROR, None)


def _is_non_empty_value(value: Any) -> bool:
    """
    Generic meaningful-value check used only for deterministic intake recovery.
    """
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(_is_non_empty_value(v) for v in value)
    if isinstance(value, dict):
        return any(_is_non_empty_value(v) for v in value.values())
    return True


# def _recover_intake_complete_if_state_has_confirmed_fields(state: dict) -> Optional[dict]:
#     """
#     Defensive recovery for revision reruns where IntakeSubAgent emits
#     "✅ Intake complete" but no durable intake_complete=True.
#     """
#     if not isinstance(state, dict):
#         return None
    
# # Do not run intake recovery after document/output completion.
#     # _get_intake_field_aliases is useful during real intake/revision recovery,
#     # but it must not revive a completed workflow or a workflow waiting for output.
#     if (
#         state.get(KEY_DOC_RENDERED) is True
#         or state.get(KEY_REVISION_READY) is True
#         or state.get(INTERNAL_OUTPUT_PENDING) is True
#         or state.get(INTERNAL_OUTPUT_DELIVERED) is True
#         or state.get(INTERNAL_FINAL_OUTPUT_READY) is True
#         or state.get("final_output_ready") is True
#         or state.get("output_delivered") is True
#     ):
#         logger.info(
#             "[FLOW] Intake recovery skipped because document/output is already "
#             "rendered or delivered. doc_rendered=%s revision_ready=%s "
#             "output_pending=%s output_delivered=%s",
#             state.get(KEY_DOC_RENDERED),
#             state.get(KEY_REVISION_READY),
#             state.get(INTERNAL_OUTPUT_PENDING),
#             state.get(INTERNAL_OUTPUT_DELIVERED),
#         )
#         return None

#     if state.get(KEY_INTAKE_COMPLETE) is True:
#         return None

#     recovered_intake = _build_intake_from_state_using_schema(state)

#     missing_required_fields = _missing_required_intake_fields_using_schema(recovered_intake)

#     if missing_required_fields:
#         logger.warning(
#             "[FLOW] Intake recovery skipped. Missing required schema fields=%s",
#             missing_required_fields,
#         )
#         return None

#     if not _validate_intake_payload_with_schema(recovered_intake):
#         logger.warning(
#             "[FLOW] Intake recovery skipped. Recovered payload failed IntakeSchema validation."
#         )
#         return None

#     confirmed = state.get(KEY_INTAKE_CONFIRMED)
#     if not isinstance(confirmed, dict):
#         confirmed = {}

#     recovered_confirmed = dict(confirmed)

#     for field_name, value in recovered_intake.items():
#         if _is_non_empty_value(value):
#             recovered_confirmed[field_name] = True

#     recovery_delta = {
#         KEY_INTAKE_COMPLETE: True,
#         KEY_INTAKE: recovered_intake,
#         KEY_INTAKE_CONFIRMED: recovered_confirmed,
#         KEY_INTAKE_MISSING_FIELDS: [],
#         KEY_INTAKE_VALIDATION_ERROR: None,
#     }

#     for key, value in recovered_intake.items():
#         recovery_delta[key] = value

#     logger.warning(
#         "[FLOW] Recovered intake completion using IntakeSchema. fields=%s",
#         list(recovered_intake.keys()),
#     )

#     return recovery_delta
def _recover_intake_complete_if_state_has_confirmed_fields(state: dict) -> Optional[dict]:
    """
    Defensive recovery for revision reruns where IntakeSubAgent emits
    "✅ Intake complete" but no durable intake_complete=True.

    Important:
    - Do not revive intake after a normal completed workflow.
    - But DO allow intake recovery during an active revision rerun.
    """
    if not isinstance(state, dict):
        return None

    revision_run_active = state.get(INTERNAL_REVISION_RUN_ACTIVE) is True

    # Do not run intake recovery after document/output completion,
    # except during an active revision rerun.
    #
    # Why:
    # In a normal completed workflow, output_delivered/final_output_ready means
    # we should not revive intake.
    #
    # But in a revision rerun, previous output flags may exist from the earlier
    # completed run. In that case, _revision_run_active=True should allow the
    # intake recovery to proceed.
    if not revision_run_active and (
        state.get(KEY_DOC_RENDERED) is True
        or state.get(KEY_REVISION_READY) is True
        or state.get(INTERNAL_OUTPUT_PENDING) is True
        or state.get(INTERNAL_OUTPUT_DELIVERED) is True
        or state.get(INTERNAL_FINAL_OUTPUT_READY) is True
        or state.get("final_output_ready") is True
        or state.get("output_delivered") is True
    ):
        logger.info(
            "[FLOW] Intake recovery skipped because document/output is already "
            "rendered or delivered. doc_rendered=%s revision_ready=%s "
            "output_pending=%s output_delivered=%s final_output_ready=%s "
            "revision_run_active=%s",
            state.get(KEY_DOC_RENDERED),
            state.get(KEY_REVISION_READY),
            state.get(INTERNAL_OUTPUT_PENDING),
            state.get(INTERNAL_OUTPUT_DELIVERED),
            state.get(INTERNAL_FINAL_OUTPUT_READY),
            revision_run_active,
        )
        return None

    if state.get(KEY_INTAKE_COMPLETE) is True:
        return None

    recovered_intake = _build_intake_from_state_using_schema(state)

    missing_required_fields = _missing_required_intake_fields_using_schema(recovered_intake)

    if missing_required_fields:
        logger.warning(
            "[FLOW] Intake recovery skipped. Missing required schema fields=%s "
            "revision_run_active=%s",
            missing_required_fields,
            revision_run_active,
        )
        return None

    if not _validate_intake_payload_with_schema(recovered_intake):
        logger.warning(
            "[FLOW] Intake recovery skipped. Recovered payload failed IntakeSchema validation. "
            "revision_run_active=%s",
            revision_run_active,
        )
        return None

    confirmed = state.get(KEY_INTAKE_CONFIRMED)
    if not isinstance(confirmed, dict):
        confirmed = {}

    recovered_confirmed = dict(confirmed)

    for field_name, value in recovered_intake.items():
        if _is_non_empty_value(value):
            recovered_confirmed[field_name] = True

    recovery_delta = {
        KEY_INTAKE_COMPLETE: True,
        KEY_INTAKE: recovered_intake,
        KEY_INTAKE_CONFIRMED: recovered_confirmed,
        KEY_INTAKE_MISSING_FIELDS: [],
        KEY_INTAKE_VALIDATION_ERROR: None,
    }

    for key, value in recovered_intake.items():
        recovery_delta[key] = value

    logger.warning(
        "[FLOW] Recovered intake completion using IntakeSchema. "
        "fields=%s revision_run_active=%s",
        list(recovered_intake.keys()),
        revision_run_active,
    )

    return recovery_delta

def _extract_latest_user_message_event(context) -> tuple[Optional[str], Optional[str]]:
    """
    Extract latest real user message from ADK session events.

    Returns:
        (event_id, text)
    """
    session = getattr(context, "session", None)
    if session is None:
        return None, None

    events = getattr(session, "events", None) or []
    if not isinstance(events, list):
        return None, None

    for event in reversed(events):
        author = getattr(event, "author", None)
        if author != "user":
            continue

        content = getattr(event, "content", None)
        parts = getattr(content, "parts", None) if content else None
        if not parts:
            continue

        text_chunks = []
        for part in parts:
            text = getattr(part, "text", None)
            if text and str(text).strip():
                text_chunks.append(str(text).strip())

        if text_chunks:
            event_id = getattr(event, "id", None)
            return event_id, "\n".join(text_chunks).strip()

    return None, None


def _is_revision_request_text(message: Optional[str]) -> bool:
    """
    Detect user intent to modify an already generated document/design.
    """
    if not message:
        return False

    msg = message.lower().strip()

    revision_patterns = [
        "change",
        "update",
        "modify",
        "revise",
        "edit",
        "replace",
        "redo",
        "regenerate",
        "re-generate",
        "instead of",
        "rather than",
        "can you change",
        "please change",
        "use ",
        "switch",
        "move from",
        "move to",
    ]

    return any(pattern in msg for pattern in revision_patterns)


# def _workflow_has_completed_or_reached_output(state: dict) -> bool:
#     """
#     True when the previous workflow reached a point where a follow-up user
#     message should be treated as a revision/change request.
#     """
#     return bool(
#         state.get(KEY_REVISION_READY)
#         or state.get(KEY_DOC_RENDERED)
#         or state.get(KEY_ARCH_COMPLETE)
#         or state.get("render_artifacts_committed")
#         or state.get(KEY_RENDERED_PDF_PATH)
#         or state.get("word_file")
#         or state.get("md_file")
#         or state.get("gcs_pdf")
#     )
def _workflow_has_completed_or_reached_output(state: dict) -> bool:
    """
    True only when the final output has been delivered and the workflow is
    ready to accept a genuine user revision/change request.

    IMPORTANT:
    Do NOT treat architecture_complete or document_rendered alone as revision-ready.
    A revision should only be accepted after OutputAgent has completed.
    """
    if not isinstance(state, dict):
        return False

    return bool(
        state.get(KEY_REVISION_READY) is True
        or state.get(INTERNAL_OUTPUT_DELIVERED) is True
        or state.get(INTERNAL_FINAL_OUTPUT_READY) is True
        or state.get("final_output_ready") is True
        or state.get("output_delivered") is True
    )
def _is_auto_continue_text(text: Optional[str]) -> bool:
    """
    Detect frontend/system generated continue_workflow calls.
    These must never be treated as user revision requests.
    """
    if not text:
        return False

    raw = str(text).strip()
    lowered = raw.lower()

    if not raw:
        return False

    markers = (
        "post_intake_auto_continue",
        "continue_workflow",
        '"action": "continue_workflow"',
        "'action': 'continue_workflow'",
        "[system automation: continue workflow]",
        "workflow_continue",
    )

    if any(marker in lowered for marker in markers):
        return True

    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed.get("action") == "continue_workflow"
        except Exception:
            pass

    return False


def _extract_real_user_message_text(text: Optional[str]) -> Optional[str]:
    """
    If frontend sends JSON user_message, extract only the human message.
    Ignore system actions such as continue_workflow and fast_track_intake.
    """
    if not text:
        return None

    raw = str(text).strip()
    if not raw:
        return None

    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                action = parsed.get("action")

                if action == "user_message":
                    message = parsed.get("message")
                    return str(message).strip() if message else None

                if action in {
                    "continue_workflow",
                    "fast_track_intake",
                    "workflow_continue",
                }:
                    return None
        except Exception:
            pass

    return raw

# def _should_reset_for_new_revision(context, state: dict) -> tuple[bool, Optional[str], Optional[str]]:
#     """
#     Decide if the latest user message should restart the full workflow.
#     """
#     latest_event_id, latest_text = _extract_latest_user_message_event(context)

#     if not latest_text:
#         return False, latest_event_id, latest_text

#     if latest_event_id and latest_event_id == state.get(INTERNAL_LAST_REVISION_USER_EVENT_ID):
#         return False, latest_event_id, latest_text

#     if not _workflow_has_completed_or_reached_output(state):
#         return False, latest_event_id, latest_text

#     if not _is_revision_request_text(latest_text):
#         return False, latest_event_id, latest_text

#     return True, latest_event_id, latest_text

def _should_reset_for_new_revision(context, state: dict) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Decide if latest real user message should restart the full workflow.

    Revision reset is allowed ONLY after final output has been delivered.
    Normal first-run intake answers must never populate revision_context/revision_notes.
    """
    latest_event_id, latest_text = _extract_latest_user_message_event(context)

    if not latest_text:
        return False, latest_event_id, latest_text

    # Never treat UI/system auto-continue as a revision.
    if _is_auto_continue_text(latest_text):
        logger.info(
            "[FLOW] Auto-continue detected. Not treating as revision. event_id=%s text=%r",
            latest_event_id,
            latest_text,
        )
        return False, latest_event_id, latest_text

    # If rendering is done but output has not been delivered yet,
    # do not evaluate any user event as revision.
    if state.get(INTERNAL_OUTPUT_PENDING) is True and not _workflow_has_completed_or_reached_output(state):
        logger.info(
            "[FLOW] Output pending. Not evaluating latest event as revision. event_id=%s",
            latest_event_id,
        )
        return False, latest_event_id, latest_text

    real_user_text = _extract_real_user_message_text(latest_text)

    if not real_user_text:
        return False, latest_event_id, latest_text

    if latest_event_id and latest_event_id == state.get(INTERNAL_LAST_REVISION_USER_EVENT_ID):
        return False, latest_event_id, real_user_text

    # Critical guard:
    # Do not allow revision until OutputAgent has completed.
    if not _workflow_has_completed_or_reached_output(state):
        logger.info(
            "[FLOW] Workflow is not revision-ready. Ignoring revision detection. "
            "event_id=%s revision_ready=%s doc_rendered=%s arch_complete=%s",
            latest_event_id,
            state.get(KEY_REVISION_READY),
            state.get(KEY_DOC_RENDERED),
            state.get(KEY_ARCH_COMPLETE),
        )
        return False, latest_event_id, real_user_text

    if not _is_revision_request_text(real_user_text):
        return False, latest_event_id, real_user_text

    return True, latest_event_id, real_user_text

def _clear_stale_revision_state_if_not_revision_ready(state: dict) -> None:
    """
    On a normal first run, revision fields should not exist.

    If workflow is not revision-ready and no explicit revision/reset flag is active,
    clear accidental stale revision context.
    """
    if not isinstance(state, dict):
        return

    if state.get(KEY_REVISION_READY) is True:
        return

    if state.get(KEY_WORKFLOW_RESET_REQUESTED) or state.get(KEY_REVISION_REQUESTED):
        return

    state.pop(KEY_REVISION_NOTES, None)
    state.pop(KEY_REVISION_CONTEXT, None)
    
def _compose_revision_user_request(state: dict, revision_request: str) -> str:
    """
    Build a complete user request for full rerun.
    """
    original_request = (
        state.get(KEY_ORIGINAL_USER_REQUEST)
        or state.get(KEY_USER_REQUEST)
        or ""
    )

    original_request = str(original_request).strip()
    revision_request = str(revision_request or "").strip()

    if not original_request:
        return revision_request

    return (
        f"{original_request}\n\n"
        f"Revision/update requested by user:\n"
        f"{revision_request}\n\n"
        "Regenerate the HLD by applying the revision above while preserving all previously "
        "confirmed project context unless contradicted."
    )


def _is_research_complete(state: dict) -> bool:
    """
    Research is complete when durable research state exists.

    Accept any of these valid completion signals:
    - KEY_RESEARCH_RESOLVED / "research_resolved" is True
    - technical_research_summary.research_metadata.research_resolved is True

    And require:
    - technical_research_summary exists and is non-empty
    - resolved_services exists either at top-level or inside summary
    """
    if not isinstance(state, dict):
        return False

    summary = state.get(KEY_TECHNICAL_RESEARCH_SUMMARY)
    if not isinstance(summary, dict) or not summary:
        return False

    summary_metadata = summary.get("research_metadata")
    if not isinstance(summary_metadata, dict):
        summary_metadata = {}

    research_resolved = (
        state.get(KEY_RESEARCH_RESOLVED) is True
        or state.get("research_resolved") is True
        or summary_metadata.get(KEY_RESEARCH_RESOLVED) is True
        or summary_metadata.get("research_resolved") is True
    )

    if not research_resolved:
        return False

    top_level_services = state.get(KEY_RESOLVED_SERVICES)
    summary_services = summary.get(KEY_RESOLVED_SERVICES) or summary.get("resolved_services")

    has_top_level_services = (
        isinstance(top_level_services, list)
        and len(top_level_services) > 0
    )

    has_summary_services = (
        isinstance(summary_services, list)
        and len(summary_services) > 0
    )

    has_services = has_top_level_services or has_summary_services

    if not has_services:
        logger.warning(
            "[FLOW] Research completion check failed. "
            "Research resolved flag is true but resolved_services is missing. "
            "top_level_services_type=%s summary_services_type=%s",
            type(top_level_services).__name__,
            type(summary_services).__name__,
        )
        return False

    return True

def _clear_stale_research_validation_error_if_research_complete(state: dict) -> Optional[dict]:
    """
    Clear stale malformed research validation errors when durable research state
    is already complete.

    This handles resumed sessions where:
    - research_resolved=True
    - technical_research_summary exists
    - resolved_services exists
    - but validation_error still contains old malformed research tool-call text.
    """
    if not isinstance(state, dict):
        return None

    if not _is_research_complete(state):
        return None

    validation_error = state.get(KEY_VALIDATION_ERROR)

    if not validation_error:
        return None

    validation_error_text = str(validation_error).lower()

    is_research_malformed_error = (
        "malformed function call" in validation_error_text
        or "malformed_function_call" in validation_error_text
        or "print(default_api.store_in_state" in validation_error_text
        or "default_api.store_in_state" in validation_error_text
    ) and (
        "technical_research_summary" in validation_error_text
        or "resolved_services" in validation_error_text
        or "research" in validation_error_text
    )

    if not is_research_malformed_error:
        return None

    return {
        KEY_RESEARCH_RESOLVED: True,
        "research_resolved": True,
        KEY_RESEARCH_RETRY_COUNT: 0,
        KEY_RESEARCH_RETRY_REASON: None,
        KEY_VALIDATION_ERROR: None,
    }

def _research_retry_delta(state: dict, reason: str) -> dict:
    """
    Clear research-only outputs and increment retry count.
    Intake and blueprint are intentionally preserved.
    """
    retry_count = int(state.get(KEY_RESEARCH_RETRY_COUNT) or 0) + 1

    return {
        KEY_RESEARCH_RESOLVED: False,
        "research_resolved": False,
        KEY_TECHNICAL_RESEARCH_SUMMARY: None,
        KEY_RESOLVED_SERVICES: [],
        KEY_RESEARCH_RETRY_COUNT: retry_count,
        KEY_RESEARCH_RETRY_REASON: reason,
    }


def _event_has_malformed_function_call(event) -> bool:
    """
    Detect model/tool malformed function-call failures from an ADK event.
    """
    finish_reason = (
        getattr(event, "finishReason", None)
        or getattr(event, "finish_reason", None)
        or ""
    )

    if str(finish_reason).upper() == "MALFORMED_FUNCTION_CALL":
        return True

    error_message = (
        getattr(event, "errorMessage", None)
        or getattr(event, "error_message", None)
        or ""
    )

    error_lower = str(error_message or "").lower()

    if (
        "malformed_function_call" in error_lower
        or "malformed function call" in error_lower
        or "default_api." in error_lower
        or "print(default_api." in error_lower
    ):
        return True

    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) if content else None

    if parts:
        for part in parts:
            text = getattr(part, "text", None)
            if not text:
                continue

            text_lower = str(text).lower()

            if (
                "print(default_api." in text_lower
                or "default_api." in text_lower
                or (
                    "store_in_state" in text_lower
                    and "(" in text_lower
                    and ")" in text_lower
                )
            ):
                return True

    return False


def _events_have_malformed_function_call(events: list) -> bool:
    """
    Detect malformed function call across a batch of events.
    """
    if not isinstance(events, list):
        return False

    return any(_event_has_malformed_function_call(event) for event in events)


# def _reset_pipeline_for_revision(
#     context,
#     full_rerun: bool = True,
#     revision_request: Optional[str] = None,
# ) -> dict:
#     """
#     Reset workflow state for a post-generation revision request.
#     """
#     state = context.session.state or {}

#     revision_request = (
#         revision_request
#         or state.get(KEY_REVISION_NOTES)
#         or ""
#     )
#     revision_request = revision_request.strip() if isinstance(revision_request, str) else ""

#     original_request = (
#         state.get(KEY_ORIGINAL_USER_REQUEST)
#         or state.get(KEY_USER_REQUEST)
#         or ""
#     )
#     original_request = str(original_request).strip()

#     composed_user_request = _compose_revision_user_request(state, revision_request)

#     state_delta: dict = {}

#     if original_request:
#         state_delta[KEY_ORIGINAL_USER_REQUEST] = original_request

#     if composed_user_request:
#         state_delta[KEY_USER_REQUEST] = composed_user_request

#     if revision_request:
#         state_delta[KEY_REVISION_NOTES] = revision_request

#     state_delta[KEY_REVISION_CONTEXT] = {
#         "revision_request": revision_request,
#         "original_user_request": original_request,
#         "composed_user_request": composed_user_request,
#         "instruction": (
#             "Apply the revision request to the existing confirmed project context. "
#             "Only update fields or architecture choices explicitly contradicted by the revision. "
#             "Preserve all other confirmed intake fields and project context."
#         ),
#     }

#     if full_rerun:
#         state_delta[KEY_INTAKE_COMPLETE] = False
#         state_delta[KEY_BLUEPRINT_SEARCH_DONE] = False
#         state_delta[KEY_RESEARCH_RESOLVED] = False

#         preserved_intake = _build_intake_from_state_using_schema(state)
#         missing_required_fields = _missing_required_intake_fields_using_schema(preserved_intake)

#         preserved_confirmed: dict = {}
#         existing_confirmed = state.get(KEY_INTAKE_CONFIRMED)
#         if isinstance(existing_confirmed, dict):
#             preserved_confirmed.update(existing_confirmed)

#         for field_name, value in preserved_intake.items():
#             if _is_non_empty_value(value):
#                 preserved_confirmed[field_name] = True

#         state_delta[KEY_INTAKE] = preserved_intake

#         for field_name, value in preserved_intake.items():
#             if _is_non_empty_value(value):
#                 state_delta[field_name] = value

#         state_delta[KEY_INTAKE_CONFIRMED] = preserved_confirmed
#         state_delta[KEY_INTAKE_MISSING_FIELDS] = missing_required_fields
#         state_delta[KEY_INTAKE_VALIDATION_ERROR] = None

#     state_delta[KEY_ARCH_COMPLETE] = False
#     state_delta[KEY_ARCH_VALID] = True
#     state_delta[KEY_DOC_RENDERED] = False

#     state_delta[KEY_WORKFLOW_RESET_REQUESTED] = False
#     state_delta[KEY_REVISION_REQUESTED] = False
#     state_delta[KEY_REVISION_READY] = False

#     state_delta[KEY_VALIDATION_ERROR] = None
#     state_delta[KEY_SECTION_RETRY_TARGET] = None
#     state_delta[KEY_SECTION_RETRY_QUEUE] = []
#     state_delta[KEY_SECTION_RETRY_COUNTS] = {}
#     state_delta[KEY_SECTION_RETRY_MODE] = False
#     state_delta[KEY_SELECTED_SECTIONS] = None

#     state_delta[KEY_RESEARCH_RETRY_COUNT] = 0
#     state_delta[KEY_RESEARCH_RETRY_REASON] = None

#     state_delta[KEY_HLD_COMMIT_TRIGGERED] = False
#     state_delta[KEY_HLD_REPORT_JSON] = None

#     for state_key in list(state.keys()):
#         if isinstance(state_key, str) and state_key.startswith(KEY_HLD_SECTION_STATE_PREFIX):
#             state_delta[state_key] = None

#     if full_rerun:
#         state_delta[KEY_BLUEPRINT_RESULTS] = []
#         state_delta[KEY_BLUEPRINT_SELECTED] = None
#         state_delta[KEY_BLUEPRINT_NO_MATCH] = False
#         state_delta[KEY_TECHNICAL_RESEARCH_SUMMARY] = None
#         state_delta[KEY_RESEARCH_RESOLVED] = False
#         state_delta["research_resolved"] = False
#         state_delta[KEY_RESOLVED_SERVICES] = []

#         # Preserve final render section filter across revision.
# # Preserve final render section filter across revision.
#         render_selected_sections = (
#             _normalize_selected_sections(state.get(KEY_RENDER_SELECTED_SECTIONS))
#             or _normalize_selected_sections(state.get(KEY_SELECTED_SECTIONS))
#         )

#         if render_selected_sections:
#             state_delta[KEY_RENDER_SELECTED_SECTIONS] = render_selected_sections

#     state_delta[KEY_RENDER_ARTIFACT] = None
#     state_delta[KEY_RENDERED_PDF_PATH] = None
#     state_delta[KEY_LOCAL_DOWNLOAD_URLS] = None
#     state_delta[KEY_LOCAL_VIEW_URLS] = None

#     state_delta["word_file"] = None
#     state_delta["md_file"] = None
#     state_delta["html_file"] = None
#     state_delta["signed_urls"] = None
#     state_delta["gcs_pdf"] = None
#     state_delta["gcs_docx"] = None
#     state_delta["gcs_md"] = None
#     state_delta["gcs_html"] = None
#     state_delta["render_artifacts_committed"] = False

#     for key, value in state_delta.items():
#         if value is None:
#             state.pop(key, None)
#         else:
#             state[key] = value

#     context.session.state = state

#     logger.info(
#         "[FLOW] Revision reset applied. "
#         "full_rerun=%s | intake=%s | blueprint=%s | research=%s | arch=%s | render=%s | "
#         "preserved_intake_fields=%s | missing_required_intake_fields=%s | revision_present=%s | "
#         "research_retry_count=%s | render_selected_sections=%s",
#         full_rerun,
#         state.get(KEY_INTAKE_COMPLETE),
#         state.get(KEY_BLUEPRINT_SEARCH_DONE),
#         state.get(KEY_RESEARCH_RESOLVED),
#         state.get(KEY_ARCH_COMPLETE),
#         state.get(KEY_DOC_RENDERED),
#         list((state.get(KEY_INTAKE) or {}).keys()) if isinstance(state.get(KEY_INTAKE), dict) else [],
#         state.get(KEY_INTAKE_MISSING_FIELDS),
#         bool(revision_request),
#         state.get(KEY_RESEARCH_RETRY_COUNT),
#         state.get(KEY_RENDER_SELECTED_SECTIONS),
#     )

#     return state_delta

def _reset_pipeline_for_revision(
    context,
    full_rerun: bool = True,
    revision_request: Optional[str] = None,
) -> dict:
    """
    Reset workflow state for a post-generation revision request.

    Important behaviour:
    - Preserve confirmed intake/project context.
    - Preserve selected render sections, if user selected a subset.
    - Clear all downstream stage completion flags.
    - Clear all previous render/output artifacts.
    - Clear previous output-delivered lifecycle flags.
    - Mark revision rerun as active so intake recovery/transition is not blocked.
    """
    state = context.session.state or {}

    revision_request = (
        revision_request
        or state.get(KEY_REVISION_NOTES)
        or ""
    )
    revision_request = revision_request.strip() if isinstance(revision_request, str) else ""

    original_request = (
        state.get(KEY_ORIGINAL_USER_REQUEST)
        or state.get(KEY_USER_REQUEST)
        or ""
    )
    original_request = str(original_request).strip()

    composed_user_request = _compose_revision_user_request(state, revision_request)

    state_delta: dict = {}

    if original_request:
        state_delta[KEY_ORIGINAL_USER_REQUEST] = original_request

    if composed_user_request:
        state_delta[KEY_USER_REQUEST] = composed_user_request

    if revision_request:
        state_delta[KEY_REVISION_NOTES] = revision_request

    state_delta[KEY_REVISION_CONTEXT] = {
        "revision_request": revision_request,
        "original_user_request": original_request,
        "composed_user_request": composed_user_request,
        "instruction": (
            "Apply the revision request to the existing confirmed project context. "
            "Only update fields or architecture choices explicitly contradicted by the revision. "
            "Preserve all other confirmed intake fields and project context."
        ),
    }

    # ---------------------------------------------------------------------
    # Revision lifecycle flags
    # ---------------------------------------------------------------------
    # Revision run has started. This allows intake recovery/transition logic
    # to continue even though a previous output may have been delivered.
    state_delta[INTERNAL_REVISION_RUN_ACTIVE] = True

    # During revision rerun, workflow is not ready for another revision yet.
    state_delta[KEY_WORKFLOW_RESET_REQUESTED] = False
    state_delta[KEY_REVISION_REQUESTED] = False
    state_delta[KEY_REVISION_READY] = False

    # ---------------------------------------------------------------------
    # CRITICAL FIX:
    # Clear previous output lifecycle flags.
    # Without this, orchestrator may believe the previous output is still final
    # and can stop after intake during revision rerun.
    # ---------------------------------------------------------------------
    state_delta[INTERNAL_OUTPUT_PENDING] = False
    state_delta[INTERNAL_OUTPUT_DELIVERED] = False
    state_delta[INTERNAL_FINAL_OUTPUT_READY] = False

    state_delta["_output_pending"] = False
    state_delta["_output_delivered"] = False
    state_delta["_final_output_ready"] = False

    state_delta["output_delivered"] = False
    state_delta["final_output_ready"] = False

    # ---------------------------------------------------------------------
    # Preserve selected section filter across revision.
    # Do this before clearing KEY_SELECTED_SECTIONS.
    # ---------------------------------------------------------------------
    render_selected_sections = (
        _normalize_selected_sections(state.get(KEY_RENDER_SELECTED_SECTIONS))
        or _normalize_selected_sections(state.get(KEY_SELECTED_SECTIONS))
    )

    if full_rerun:
        # -----------------------------------------------------------------
        # Reset intake stage but preserve confirmed values.
        # Intake can either be re-confirmed by IntakeAgent or recovered by
        # orchestrator if all required fields are already present.
        # -----------------------------------------------------------------
        state_delta[KEY_INTAKE_COMPLETE] = False
        state_delta[KEY_BLUEPRINT_SEARCH_DONE] = False
        state_delta[KEY_RESEARCH_RESOLVED] = False

        preserved_intake = _build_intake_from_state_using_schema(state)

        # Apply common revision-specific intake correction.
        # This is generic enough for your current case and does not hardcode
        # the whole use case. It only reacts if user explicitly mentions Eventarc.
        if revision_request and "eventarc" in revision_request.lower():
            preserved_intake["execution_model"] = (
                "Event-driven using Eventarc trigger for Cloud Storage object finalization events"
            )

        missing_required_fields = _missing_required_intake_fields_using_schema(preserved_intake)

        preserved_confirmed: dict = {}
        existing_confirmed = state.get(KEY_INTAKE_CONFIRMED)
        if isinstance(existing_confirmed, dict):
            preserved_confirmed.update(existing_confirmed)

        for field_name, value in preserved_intake.items():
            if _is_non_empty_value(value):
                preserved_confirmed[field_name] = True

        state_delta[KEY_INTAKE] = preserved_intake

        for field_name, value in preserved_intake.items():
            if _is_non_empty_value(value):
                state_delta[field_name] = value

        state_delta[KEY_INTAKE_CONFIRMED] = preserved_confirmed
        state_delta[KEY_INTAKE_MISSING_FIELDS] = missing_required_fields
        state_delta[KEY_INTAKE_VALIDATION_ERROR] = None

    # ---------------------------------------------------------------------
    # Reset architecture stage
    # ---------------------------------------------------------------------
    state_delta[KEY_ARCH_COMPLETE] = False

    # Keep this True only if your existing orchestrator expects "valid until
    # proven invalid". If your validator uses this as completion signal, set
    # it to False instead.
    state_delta[KEY_ARCH_VALID] = True

    state_delta[KEY_DOC_RENDERED] = False
    state_delta["document_rendered"] = False

    state_delta[KEY_VALIDATION_ERROR] = None
    state_delta[KEY_SECTION_RETRY_TARGET] = None
    state_delta[KEY_SECTION_RETRY_QUEUE] = []
    state_delta[KEY_SECTION_RETRY_COUNTS] = {}
    state_delta[KEY_SECTION_RETRY_MODE] = False

    # Do not wipe selected sections permanently.
    # If there was a user-selected subset, preserve it for rendering.
    if render_selected_sections:
        state_delta[KEY_SELECTED_SECTIONS] = render_selected_sections
        state_delta[KEY_RENDER_SELECTED_SECTIONS] = render_selected_sections
    else:
        state_delta[KEY_SELECTED_SECTIONS] = None
        state_delta[KEY_RENDER_SELECTED_SECTIONS] = None

    # ---------------------------------------------------------------------
    # Reset research retry state
    # ---------------------------------------------------------------------
    state_delta[KEY_RESEARCH_RETRY_COUNT] = 0
    state_delta[KEY_RESEARCH_RETRY_REASON] = None

    # ---------------------------------------------------------------------
    # Reset HLD commit/report state
    # ---------------------------------------------------------------------
    state_delta[KEY_HLD_COMMIT_TRIGGERED] = False
    state_delta[KEY_HLD_REPORT_JSON] = None

    for state_key in list(state.keys()):
        if isinstance(state_key, str) and state_key.startswith(KEY_HLD_SECTION_STATE_PREFIX):
            state_delta[state_key] = None

    if full_rerun:
        # -----------------------------------------------------------------
        # Reset blueprint stage
        # -----------------------------------------------------------------
        state_delta[KEY_BLUEPRINT_RESULTS] = []
        state_delta[KEY_BLUEPRINT_SELECTED] = None
        state_delta[KEY_BLUEPRINT_NO_MATCH] = False
        state_delta["blueprint_results"] = []
        state_delta["blueprint_selected"] = None
        state_delta["blueprint_no_match"] = False
        state_delta["blueprint_search_done"] = False

        # -----------------------------------------------------------------
        # Reset research stage
        # -----------------------------------------------------------------
        state_delta[KEY_TECHNICAL_RESEARCH_SUMMARY] = None
        state_delta[KEY_RESEARCH_RESOLVED] = False
        state_delta["research_resolved"] = False
        state_delta[KEY_RESOLVED_SERVICES] = []
        state_delta["resolved_services"] = []

    # ---------------------------------------------------------------------
    # Reset render artifacts
    # ---------------------------------------------------------------------
    state_delta[KEY_RENDER_ARTIFACT] = None
    state_delta[KEY_RENDERED_PDF_PATH] = None
    state_delta[KEY_LOCAL_DOWNLOAD_URLS] = None
    state_delta[KEY_LOCAL_VIEW_URLS] = None

    state_delta["output_file"] = None
    state_delta["pdf_file"] = None
    state_delta["word_file"] = None
    state_delta["docx_file"] = None
    state_delta["md_file"] = None
    state_delta["html_file"] = None

    state_delta["pdf_url"] = None
    state_delta["docx_url"] = None
    state_delta["md_url"] = None
    state_delta["html_url"] = None

    state_delta["signed_urls"] = None
    state_delta["local_download_urls"] = None
    state_delta["local_view_urls"] = None

    state_delta["gcs_pdf"] = None
    state_delta["gcs_docx"] = None
    state_delta["gcs_md"] = None
    state_delta["gcs_html"] = None

    state_delta["render_artifacts_committed"] = False

    # ---------------------------------------------------------------------
    # Apply delta into session state.
    # Existing behaviour preserved:
    # - None removes key.
    # - Non-None writes key.
    # ---------------------------------------------------------------------
    for key, value in state_delta.items():
        if value is None:
            state.pop(key, None)
        else:
            state[key] = value

    context.session.state = state

    logger.info(
        "[FLOW] Revision reset applied. "
        "full_rerun=%s | revision_run_active=%s | intake=%s | blueprint=%s | research=%s | "
        "arch=%s | render=%s | output_pending=%s | output_delivered=%s | final_output_ready=%s | "
        "preserved_intake_fields=%s | missing_required_intake_fields=%s | revision_present=%s | "
        "research_retry_count=%s | selected_sections=%s | render_selected_sections=%s",
        full_rerun,
        state.get(INTERNAL_REVISION_RUN_ACTIVE),
        state.get(KEY_INTAKE_COMPLETE),
        state.get(KEY_BLUEPRINT_SEARCH_DONE),
        state.get(KEY_RESEARCH_RESOLVED),
        state.get(KEY_ARCH_COMPLETE),
        state.get(KEY_DOC_RENDERED),
        state.get(INTERNAL_OUTPUT_PENDING),
        state.get(INTERNAL_OUTPUT_DELIVERED),
        state.get(INTERNAL_FINAL_OUTPUT_READY),
        list((state.get(KEY_INTAKE) or {}).keys()) if isinstance(state.get(KEY_INTAKE), dict) else [],
        state.get(KEY_INTAKE_MISSING_FIELDS),
        bool(revision_request),
        state.get(KEY_RESEARCH_RETRY_COUNT),
        state.get(KEY_SELECTED_SECTIONS),
        state.get(KEY_RENDER_SELECTED_SECTIONS),
    )

    return state_delta

def has_new_user_message(context):
    """
    Legacy helper retained for compatibility.
    """
    return getattr(context, "new_user_message", False)


def get_latest_user_message(context):
    """
    Legacy helper retained for compatibility.
    """
    return getattr(context, "latest_user_message", "")


def is_revision_request(message):
    """
    Legacy helper retained for compatibility.
    """
    return _is_revision_request_text(message)


# ==========================================================
# ORCHESTRATOR
# ==========================================================
class GatedSequentialAgent(SequentialAgent):
    """
    Deterministic Orchestrator for AIA.
    """

    async def _run_async_impl(self, context) -> AsyncGenerator[Event, None]:
        while True:
            state = context.session.state or {}
            _preserve_render_selected_sections(state)
            
             # Revision fields must not exist during a normal first run.
            # They should only be populated after final output is delivered
            # and a genuine user change request is received.
            _clear_stale_revision_state_if_not_revision_ready(state)

            context.session.state = state

            # ==========================================================
            # TOP PRIORITY: POST-COMPLETION USER REVISION REQUEST
            # ==========================================================
            should_reset, latest_user_event_id, latest_user_text = _should_reset_for_new_revision(
                context,
                state,
            )

            if should_reset:
                logger.info(
                    "[FLOW] New post-completion revision request detected. "
                    "Restarting FULL workflow from intake. user_event_id=%s text=%r",
                    latest_user_event_id,
                    latest_user_text,
                )

                reset_delta = _reset_pipeline_for_revision(
                    context,
                    full_rerun=True,
                    revision_request=latest_user_text,
                )

                reset_delta[INTERNAL_LAST_REVISION_USER_EVENT_ID] = latest_user_event_id
                reset_delta[INTERNAL_LAST_REVISION_TEXT] = latest_user_text
                reset_delta[KEY_WORKFLOW_RESET_REQUESTED] = False
                reset_delta[KEY_REVISION_REQUESTED] = False
                reset_delta[KEY_REVISION_READY] = False

                _apply_state_delta_to_session(context, reset_delta)

                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text=(
                                    "🔄 Change request detected. Restarting the full workflow "
                                    "from intake, then blueprint, research, architecture, rendering, and output."
                                )
                            )
                        ],
                    ),
                    actions=EventActions(
                        state_delta=reset_delta,
                        escalate=False,
                    ),
                )

                continue

            # ==========================================================
            # EXPLICIT RESET FLAG: FULL REVISION RERUN
            # ==========================================================
            if state.get(KEY_WORKFLOW_RESET_REQUESTED):
                revision_text_present = bool((state.get(KEY_REVISION_NOTES) or "").strip())

                logger.info(
                    "[FLOW] Revision reset pre-check triggered. "
                    "Restarting full workflow from intake. "
                    "revision_request_present=%s",
                    revision_text_present,
                )

                reset_delta = _reset_pipeline_for_revision(
                    context,
                    full_rerun=True,
                    revision_request=(context.session.state or {}).get(KEY_REVISION_NOTES),
                )

                reset_delta[KEY_WORKFLOW_RESET_REQUESTED] = False
                reset_delta[KEY_REVISION_REQUESTED] = False
                reset_delta[KEY_REVISION_READY] = False

                _apply_state_delta_to_session(context, reset_delta)

                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text=(
                                    "🔄 Revision reset requested. Restarting full workflow "
                                    "from intake."
                                )
                            )
                        ],
                    ),
                    actions=EventActions(
                        state_delta=reset_delta,
                        escalate=False,
                    ),
                )

                state = context.session.state or {}
                continue

            # ==========================================================
            # GLOBAL ERROR HALT
            # ==========================================================
            last_msg = (
                getattr(context, "last_model_message", None)
                or getattr(context, "last_assistant_message", None)
            )

            if last_msg:
                reason = getattr(last_msg, "finishReason", None) or getattr(
                    last_msg, "finish_reason", None
                )

                reason_str = str(reason or "").upper()

                if reason_str == "MALFORMED_FUNCTION_CALL":
                    logger.warning(
                        "[FLOW] Global MALFORMED_FUNCTION_CALL observed. "
                        "Skipping fatal halt so architect section-only retry can recover."
                    )

                elif reason_str.endswith("_ERROR"):
                    logger.error("[FLOW] FATAL ERROR DETECTED: %s. Halting pipeline.", reason_str)

                    yield Event(
                        author=self.name,
                        content=types.Content(
                            role="model",
                            parts=[
                                types.Part(
                                    text=(
                                        "⚠️ Pipeline Halted due to an internal error: "
                                        f"{reason_str}. Check console logs."
                                    )
                                )
                            ],
                        ),
                    )
                    return

            # ==========================================================
            # STEP 1: INTAKE GATE
            # ==========================================================
            if not state.get(KEY_INTAKE_COMPLETE):
                user_req_present = bool((context.session.state or {}).get(KEY_USER_REQUEST))
                logger.info("[FLOW] Intake Phase Active. KEY_USER_REQUEST present=%s", user_req_present)

                async for event in self.sub_agents[0].run_async(context):
                    yield event

                if not context.session.state.get(KEY_INTAKE_COMPLETE):
                    intake_recovery_delta = _recover_intake_complete_if_state_has_confirmed_fields(
                        context.session.state or {}
                    )

                    if intake_recovery_delta:
                        logger.warning(
                            "[FLOW] IntakeSubAgent completed without durable intake_complete=True. "
                            "Recovered intake completion from existing confirmed intake fields. keys=%s",
                            list((intake_recovery_delta.get(KEY_INTAKE) or {}).keys()),
                        )

                        _apply_state_delta_to_session(context, intake_recovery_delta)

                        yield Event(
                            author=self.name,
                            content=types.Content(
                                role="model",
                                parts=[types.Part(text="")],
                            ),
                            actions=EventActions(
                                state_delta=intake_recovery_delta,
                                escalate=False,
                            ),
                        )
                    else:
                        return

                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text="✅ Intake complete (15%). Proceeding to blueprint matching."
                            )
                        ],
                    ),
                )
                continue

            # ==========================================================
            # STEP 2: BLUEPRINT GATE
            # ==========================================================
            if not state.get(KEY_BLUEPRINT_SEARCH_DONE):
                if state.get(KEY_VALIDATION_ERROR):
                    context.session.state[KEY_INTAKE_COMPLETE] = False
                    continue

                logger.info("[FLOW] Blueprint Phase Active.")

                async for event in self.sub_agents[1].run_async(context):
                    yield event

                if not context.session.state.get(KEY_BLUEPRINT_SEARCH_DONE):
                    return

                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(text="✅ Blueprint search executed (30%). Continuing.")
                        ],
                    ),
                )
                continue

            # ==========================================================
            # STEP 3: RESEARCH GATE
            # ==========================================================
            if not state.get(KEY_RESEARCH_RESOLVED):
                logger.info("[FLOW] Research Phase Active.")

                research_events = []

                async for event in self.sub_agents[2].run_async(context):
                    research_events.append(event)
                    yield event

                state_after_research = context.session.state or {}

                malformed_research_call = _events_have_malformed_function_call(research_events)
                research_complete = _is_research_complete(state_after_research)

                # ----------------------------------------------------------
                # IMPORTANT FIX:
                #
                # Do NOT retry research only because a malformed function call
                # was observed if durable research state is already complete.
                #
                # Some model turns can successfully commit:
                #   - technical_research_summary
                #   - resolved_services
                #   - research_resolved=True
                #
                # and still include a malformed tool-call artefact in the same
                # invocation. In that case, the correct action is to accept the
                # durable state and clear stale validation/retry errors.
                #
                # Old incorrect behaviour:
                #   if malformed_research_call or not research_complete:
                #       retry
                #
                # New correct behaviour:
                #   if research_complete:
                #       accept and continue
                #   else:
                #       retry
                # ----------------------------------------------------------
                if research_complete:
                    if malformed_research_call:
                        logger.warning(
                            "[FLOW] Research emitted malformed function call, "
                            "but durable research state is complete. "
                            "Accepting research output and clearing stale error."
                        )
                    else:
                        logger.info(
                            "[FLOW] Research completed cleanly with durable state."
                        )

                    research_success_delta = {
                        KEY_RESEARCH_RESOLVED: True,
                        "research_resolved": True,

                        KEY_RESEARCH_RETRY_COUNT: 0,
                        KEY_RESEARCH_RETRY_REASON: None,

                        # Critical:
                        # Clear any stale malformed-function-call error.
                        # Without this, the later architect/validation gate can
                        # keep looping on an old research error even after
                        # research succeeded.
                        KEY_VALIDATION_ERROR: None,
                    }

                    _apply_state_delta_to_session(context, research_success_delta)

                    yield Event(
                        author=self.name,
                        content=types.Content(
                            role="model",
                            parts=[
                                types.Part(
                                    text="✅ Research completed (45%). Preparing architecture."
                                )
                            ],
                        ),
                        actions=EventActions(
                            state_delta=research_success_delta,
                            escalate=False,
                        ),
                    )

                    continue

                # ----------------------------------------------------------
                # Only reach this point if durable research state is incomplete.
                # Now retry is valid.
                # ----------------------------------------------------------
                retry_count = int(state_after_research.get(KEY_RESEARCH_RETRY_COUNT) or 0)
                retry_max = int(
                    state_after_research.get(KEY_RESEARCH_RETRY_MAX)
                    or DEFAULT_RESEARCH_RETRY_MAX
                )

                reason = (
                    "Malformed function call from ResearchSubAgent"
                    if malformed_research_call
                    else "ResearchSubAgent output incomplete"
                )

                logger.warning(
                    "[FLOW] Research did not complete cleanly. "
                    "reason=%s retry_count=%s retry_max=%s research_complete=%s malformed=%s",
                    reason,
                    retry_count,
                    retry_max,
                    research_complete,
                    malformed_research_call,
                )

                if retry_count < retry_max:
                    retry_delta = _research_retry_delta(
                        state_after_research,
                        reason=reason,
                    )

                    _apply_state_delta_to_session(context, retry_delta)

                    yield Event(
                        author=self.name,
                        content=types.Content(
                            role="model",
                            parts=[
                                types.Part(
                                    text=(
                                        "⚠️ Research output was incomplete or malformed. "
                                        "Retrying research with the same intake and blueprint context."
                                    )
                                )
                            ],
                        ),
                        actions=EventActions(
                            state_delta=retry_delta,
                            escalate=False,
                        ),
                    )

                    continue

                failure_delta = {
                    KEY_RESEARCH_RESOLVED: False,
                    "research_resolved": False,
                    KEY_VALIDATION_ERROR: {
                        "stage": "research",
                        "error": (
                            "ResearchSubAgent failed to produce valid research output "
                            "after retry limit."
                        ),
                        "reason": reason,
                        "retry_count": retry_count,
                        "retry_max": retry_max,
                    },
                }

                _apply_state_delta_to_session(context, failure_delta)

                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text=(
                                    "❌ Research failed after retry limit. "
                                    "Architecture generation cannot continue safely."
                                )
                            )
                        ],
                    ),
                    actions=EventActions(
                        state_delta=failure_delta,
                        escalate=False,
                    ),
                )

                return    
            # ==========================================================
            # DEFENSIVE CLEANUP:
            # Research may already be complete, but a stale malformed
            # research validation_error may remain from a previous attempt.
            # Clear it before entering Architect phase.
            # ==========================================================
            stale_research_cleanup_delta = _clear_stale_research_validation_error_if_research_complete(
                context.session.state or {}
            )

            if stale_research_cleanup_delta:
                logger.warning(
                    "[FLOW] Cleared stale malformed research validation_error "
                    "because durable research state is already complete."
                )

                _apply_state_delta_to_session(context, stale_research_cleanup_delta)

                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[types.Part(text="")],
                    ),
                    actions=EventActions(
                        state_delta=stale_research_cleanup_delta,
                        escalate=False,
                    ),
                )

                state = context.session.state or {}                    
            # if not state.get(KEY_RESEARCH_RESOLVED):
            #     logger.info("[FLOW] Research Phase Active.")

            #     research_events = []

            #     async for event in self.sub_agents[2].run_async(context):
            #         research_events.append(event)
            #         yield event

            #     state_after_research = context.session.state or {}

            #     malformed_research_call = _events_have_malformed_function_call(research_events)
            #     research_complete = _is_research_complete(state_after_research)

            #     if malformed_research_call or not research_complete:
            #         retry_count = int(state_after_research.get(KEY_RESEARCH_RETRY_COUNT) or 0)
            #         retry_max = int(
            #             state_after_research.get(KEY_RESEARCH_RETRY_MAX)
            #             or DEFAULT_RESEARCH_RETRY_MAX
            #         )

            #         reason = (
            #             "Malformed function call from ResearchSubAgent"
            #             if malformed_research_call
            #             else "ResearchSubAgent output incomplete"
            #         )

            #         logger.warning(
            #             "[FLOW] Research did not complete cleanly. "
            #             "reason=%s retry_count=%s retry_max=%s research_complete=%s malformed=%s",
            #             reason,
            #             retry_count,
            #             retry_max,
            #             research_complete,
            #             malformed_research_call,
            #         )

            #         if retry_count < retry_max:
            #             retry_delta = _research_retry_delta(
            #                 state_after_research,
            #                 reason=reason,
            #             )

            #             _apply_state_delta_to_session(context, retry_delta)

            #             yield Event(
            #                 author=self.name,
            #                 content=types.Content(
            #                     role="model",
            #                     parts=[
            #                         types.Part(
            #                             text=(
            #                                 "⚠️ Research output was incomplete or malformed. "
            #                                 "Retrying research with the same intake and blueprint context."
            #                             )
            #                         )
            #                     ],
            #                 ),
            #                 actions=EventActions(
            #                     state_delta=retry_delta,
            #                     escalate=False,
            #                 ),
            #             )

            #             continue

            #         failure_delta = {
            #             KEY_RESEARCH_RESOLVED: False,
            #             "research_resolved": False,
            #             KEY_VALIDATION_ERROR: {
            #                 "stage": "research",
            #                 "error": (
            #                     "ResearchSubAgent failed to produce valid research output "
            #                     "after retry limit."
            #                 ),
            #                 "reason": reason,
            #                 "retry_count": retry_count,
            #                 "retry_max": retry_max,
            #             },
            #         }

            #         _apply_state_delta_to_session(context, failure_delta)

            #         yield Event(
            #             author=self.name,
            #             content=types.Content(
            #                 role="model",
            #                 parts=[
            #                     types.Part(
            #                         text=(
            #                             "❌ Research failed after retry limit. "
            #                             "Architecture generation cannot continue safely."
            #                         )
            #                     )
            #                 ],
            #             ),
            #             actions=EventActions(
            #                 state_delta=failure_delta,
            #                 escalate=False,
            #             ),
            #         )

            #         return

            #     research_success_delta = {
            #         KEY_RESEARCH_RETRY_COUNT: 0,
            #         KEY_RESEARCH_RETRY_REASON: None,
            #     }

            #     _apply_state_delta_to_session(context, research_success_delta)

            #     yield Event(
            #         author=self.name,
            #         content=types.Content(
            #             role="model",
            #             parts=[
            #                 types.Part(
            #                     text="✅ Research completed (45%). Preparing architecture."
            #                 )
            #             ],
            #         ),
            #         actions=EventActions(
            #             state_delta=research_success_delta,
            #             escalate=False,
            #         ),
            #     )
            #     continue

            # ==========================================================
            # STEP 4: ARCHITECT LOOP
            # HYBRID MODE: SECTION-WISE PRIMARY, RAW JSON FALLBACK
            # ==========================================================
            is_arch_done = state.get(KEY_ARCH_COMPLETE)
            is_arch_valid = state.get(KEY_ARCH_VALID, True)

            if not is_arch_done or is_arch_valid is False:
                section_retry_counts = context.session.state.get(KEY_SECTION_RETRY_COUNTS, {}) or {}
                retry_target = context.session.state.get(KEY_SECTION_RETRY_TARGET)
                retry_queue = context.session.state.get(KEY_SECTION_RETRY_QUEUE, []) or []
                retry_mode = bool(context.session.state.get(KEY_SECTION_RETRY_MODE, False))

                _force_selected_sections_for_retry(context.session.state)

                retry_target = context.session.state.get(KEY_SECTION_RETRY_TARGET)
                retry_queue = context.session.state.get(KEY_SECTION_RETRY_QUEUE, []) or []
                retry_mode = bool(context.session.state.get(KEY_SECTION_RETRY_MODE, False))

                if retry_target and int(section_retry_counts.get(retry_target, 0)) >= 3:
                    if _is_malformed_retry_error(context.session.state):
                        logger.warning(
                            "[FLOW] Retry count >= 3 for %s but error is malformed-tool-call related. "
                            "Allowing ArchitectureValidationGate to perform recovery.",
                            retry_target,
                        )
                    else:
                        error_msg = (
                            f"⚠️ **Pipeline Halted:** Section-only retry exhausted for `{retry_target}`. "
                            "The system could not generate this section after repeated attempts."
                        )
                        logger.error("[FLOW] %s", error_msg)
                        yield Event(
                            author=self.name,
                            content=types.Content(
                                role="model",
                                parts=[types.Part(text=error_msg)],
                            ),
                        )
                        return

                if retry_mode and retry_target:
                    logger.info(
                        "[FLOW] Architect Loop Active. "
                        "Section-only retry target: %s. Retry queue: %s",
                        retry_target,
                        retry_queue,
                    )
                else:
                    selected = context.session.state.get(KEY_SELECTED_SECTIONS, "ALL (Default)")
                    logger.info("[FLOW] Architect Loop Active. Target Sections: %s", selected)

                validation_gate = None
                try:
                    validation_gate = self.sub_agents[3].sub_agents[1]
                except Exception:
                    validation_gate = None

                async def _run_section_progress_gate():
                    if validation_gate is None:
                        return

                    async for gate_event in validation_gate.run_async(context):
                        yield gate_event

                        gate_state_delta = _get_event_state_delta_from_gate_event(gate_event)
                        if gate_state_delta:
                            context.session.state.update(gate_state_delta)

                architect_text_buffer = ""
                commit_seen_this_pass = False
                section_commit_seen_this_pass = False

                malformed_tool_text_detected = False
                malformed_retry_target = None

                architect_authors = {"ArchitectSubAgent"}
                try:
                    architect_agent_name = getattr(self.sub_agents[3].sub_agents[0], "name", None)
                    if architect_agent_name:
                        architect_authors.add(architect_agent_name)
                except Exception:
                    pass

                async for event in self.sub_agents[3].run_async(context):
                    event_author = getattr(event, "author", "") or ""

                    event_finish_reason = (
                        getattr(event, "finishReason", None)
                        or getattr(event, "finish_reason", None)
                        or ""
                    )

                    event_error_message = (
                        getattr(event, "errorMessage", None)
                        or getattr(event, "error_message", None)
                        or ""
                    )

                    if str(event_finish_reason).upper() == "MALFORMED_FUNCTION_CALL":
                        malformed_tool_text_detected = True

                        inferred_target = _infer_section_from_malformed_tool_text(
                            str(event_error_message)
                        )
                        if inferred_target:
                            malformed_retry_target = inferred_target

                        logger.error(
                            "[FLOW] Event-level MALFORMED_FUNCTION_CALL detected. "
                            "inferred_target=%s error=%s",
                            malformed_retry_target,
                            event_error_message,
                        )

                        context.session.state[KEY_ARCH_VALID] = False
                        context.session.state[KEY_ARCH_COMPLETE] = False
                        context.session.state[KEY_VALIDATION_ERROR] = (
                            "Malformed function call detected in architect event."
                        )

                        yield event
                        continue

                    if hasattr(event, "content") and event.content and hasattr(event.content, "parts"):
                        for part in event.content.parts:
                            if hasattr(part, "text") and part.text:
                                architect_text_buffer += part.text

                                if (
                                    event_author in architect_authors
                                    and _looks_like_malformed_tool_text(part.text)
                                ):
                                    malformed_tool_text_detected = True
                                    inferred_target = _infer_section_from_malformed_tool_text(part.text)
                                    if inferred_target:
                                        malformed_retry_target = inferred_target

                                    logger.error(
                                        "[FLOW] Detected malformed textual tool-call output "
                                        "from architect author=%s inferred_target=%s",
                                        event_author,
                                        malformed_retry_target,
                                    )

                                    context.session.state[KEY_ARCH_VALID] = False
                                    context.session.state[KEY_ARCH_COMPLETE] = False
                                    context.session.state[KEY_VALIDATION_ERROR] = (
                                        "Malformed textual tool call detected in architect output."
                                    )

                                part.text = ""

                            if hasattr(part, "function_call") and part.function_call:
                                fc = part.function_call
                                if fc.name == "commit_hld_to_memory":
                                    commit_seen_this_pass = True
                                    logger.info("[FLOW] commit_hld_to_memory function call detected.")

                                    args = fc.args or {}
                                    payload = (
                                        args.get("hld_report_json")
                                        or args.get("report")
                                        or args.get("payload")
                                    )

                                    parsed = _parse_hld_json(payload)
                                    if parsed:
                                        if isinstance(payload, dict):
                                            context.session.state[KEY_HLD_REPORT_JSON] = payload
                                            context.session.state[KEY_HLD_COMMIT_TRIGGERED] = False
                                            logger.info(
                                                "✅ HLD loaded directly from commit tool dict payload."
                                            )
                                        elif isinstance(payload, str):
                                            try:
                                                fixed_payload = repair_json(payload)
                                                context.session.state[KEY_HLD_REPORT_JSON] = json.loads(
                                                    fixed_payload,
                                                    strict=False,
                                                )
                                                context.session.state[KEY_HLD_COMMIT_TRIGGERED] = False
                                                logger.info(
                                                    "✅ HLD loaded directly from commit tool string payload."
                                                )
                                            except Exception as e:
                                                logger.warning(
                                                    "Failed to parse JSON string from tool args: %s",
                                                    e,
                                                )

                            if hasattr(part, "function_response") and part.function_response:
                                fr = part.function_response

                                if fr.name == "commit_hld_to_memory":
                                    commit_seen_this_pass = True
                                    logger.info(
                                        "[FLOW] commit_hld_to_memory function response observed."
                                    )

                                elif fr.name and fr.name.startswith("commit_"):
                                    try:
                                        response_payload = getattr(fr, "response", None) or {}

                                        if hasattr(response_payload, "model_dump"):
                                            response_payload = response_payload.model_dump()
                                        elif hasattr(response_payload, "dict"):
                                            response_payload = response_payload.dict()

                                        state_delta = (
                                            response_payload.get("stateDelta")
                                            or response_payload.get("state_delta")
                                            or {}
                                        )

                                        if isinstance(state_delta, dict) and state_delta:
                                            context.session.state.update(state_delta)
                                            section_commit_seen_this_pass = True

                                            logger.info(
                                                "[FLOW] Applied section-wise state delta from %s -> keys=%s",
                                                fr.name,
                                                list(state_delta.keys()),
                                            )

                                            committed_section_name = section_name_from_commit_tool_name(fr.name)

                                            if committed_section_name:
                                                logger.info(
                                                    "[FLOW] Commit tool %s mapped dynamically to section=%s",
                                                    fr.name,
                                                    committed_section_name,
                                                )

                                                if is_hld_section_committed(
                                                    context.session.state,
                                                    committed_section_name,
                                                ):
                                                    _remove_committed_retry_target(
                                                        context.session.state,
                                                        committed_section_name,
                                                    )

                                                    logger.info(
                                                        "[FLOW] Section committed successfully. "
                                                        "section=%s retry_target=%s retry_queue=%s",
                                                        committed_section_name,
                                                        context.session.state.get(KEY_SECTION_RETRY_TARGET),
                                                        context.session.state.get(KEY_SECTION_RETRY_QUEUE),
                                                    )

                                            if retry_mode and retry_target:
                                                logger.info(
                                                    "[FLOW] Section-only retry mode active during %s. "
                                                    "Current retry target=%s",
                                                    fr.name,
                                                    retry_target,
                                                )

                                            try:
                                                if is_hld_final_validation_ready(context.session.state):
                                                    assembled_hld = assemble_hld_from_state(
                                                        context.session.state
                                                    )
                                                    context.session.state[KEY_HLD_REPORT_JSON] = assembled_hld

                                                    logger.info(
                                                        "[FLOW] Successfully assembled %s from "
                                                        "complete section-wise state.",
                                                        KEY_HLD_REPORT_JSON,
                                                    )
                                                else:
                                                    logger.info(
                                                        "[FLOW] Assembly deferred after %s. "
                                                        "Missing sections=%s",
                                                        fr.name,
                                                        get_missing_hld_sections(context.session.state),
                                                    )
                                            except Exception as e:
                                                logger.debug(
                                                    "[FLOW] Section-wise assembly not ready yet "
                                                    "after %s: %s",
                                                    fr.name,
                                                    e,
                                                )

                                    except Exception as e:
                                        logger.exception(
                                            "[FLOW] Failed applying section-wise state delta from %s: %s",
                                            getattr(fr, "name", "<unknown>"),
                                            e,
                                        )

                    yield event

                    if (
                        (
                            commit_seen_this_pass
                            or context.session.state.get(KEY_HLD_COMMIT_TRIGGERED)
                        )
                        and not context.session.state.get(KEY_HLD_REPORT_JSON)
                    ):
                        logger.info("[FLOW] Commit signal detected. Processing fallback payload...")

                        existing_payload = context.session.state.get(KEY_HLD_REPORT_JSON)

                        if isinstance(existing_payload, dict) and len(existing_payload) > 0:
                            context.session.state[KEY_HLD_COMMIT_TRIGGERED] = False
                        else:
                            match = re.search(r"(\{.*\})", architect_text_buffer, re.DOTALL)
                            if match:
                                raw_input = match.group(1).strip()
                                try:
                                    fixed_raw_input = repair_json(raw_input)
                                    hld_data = json.loads(fixed_raw_input, strict=False)

                                    context.session.state[KEY_HLD_REPORT_JSON] = hld_data
                                    context.session.state[KEY_HLD_COMMIT_TRIGGERED] = False
                                except Exception as e:
                                    context.session.state[KEY_ARCH_VALID] = False
                                    context.session.state[KEY_VALIDATION_ERROR] = str(e)

                if section_commit_seen_this_pass and not context.session.state.get(KEY_HLD_REPORT_JSON):
                    try:
                        if is_hld_final_validation_ready(context.session.state):
                            context.session.state[KEY_HLD_REPORT_JSON] = assemble_hld_from_state(
                                context.session.state
                            )
                            logger.info("[FLOW] HLD assembled from complete section-wise state.")
                        else:
                            missing_sections = get_missing_hld_sections(context.session.state)

                            logger.info(
                                "[FLOW] Post-pass assembly deferred. "
                                "Missing sections still pending=%s",
                                missing_sections,
                            )

                            _clear_stale_arch_validation_error_if_not_final_ready(
                                context.session.state
                            )

                    except Exception as e:
                        context.session.state[KEY_ARCH_VALID] = False
                        context.session.state[KEY_VALIDATION_ERROR] = str(e)

                if malformed_tool_text_detected:
                    context.session.state[KEY_ARCH_COMPLETE] = False
                    context.session.state[KEY_ARCH_VALID] = False

                    context.session.state[KEY_VALIDATION_ERROR] = (
                        context.session.state.get(KEY_VALIDATION_ERROR)
                        or "Malformed textual/function tool call detected in architect output."
                    )

                    retry_target = (
                        context.session.state.get(KEY_SECTION_RETRY_TARGET)
                        or malformed_retry_target
                    )

                    if retry_target:
                        context.session.state[KEY_SECTION_RETRY_TARGET] = retry_target
                        context.session.state[KEY_SECTION_RETRY_QUEUE] = [retry_target]
                        context.session.state[KEY_SECTION_RETRY_MODE] = True
                        context.session.state[KEY_SELECTED_SECTIONS] = [retry_target]

                        logger.warning(
                            "[FLOW] Malformed tool call detected. Delegating recovery to ArchitectureValidationGate. "
                            "retry_target=%s",
                            retry_target,
                        )

                    async for gate_event in _run_section_progress_gate():
                        yield gate_event

                if (
                    context.session.state.get(KEY_ARCH_COMPLETE) is not True
                    and context.session.state.get(KEY_ARCH_VALID) is False
                    and not bool(context.session.state.get(KEY_SECTION_RETRY_MODE, False))
                    and not (context.session.state.get(KEY_SECTION_RETRY_QUEUE, []) or [])
                ):
                    if not is_hld_final_validation_ready(context.session.state):
                        logger.info(
                            "[FLOW] Invalid state ignored because final validation is not ready. "
                            "Pending=%s",
                            get_missing_hld_sections(context.session.state),
                        )

                        _clear_stale_arch_validation_error_if_not_final_ready(
                            context.session.state
                        )
                    else:
                        logger.warning(
                            "[FLOW] Invalid architecture state with complete sections. "
                            "Running progress gate."
                        )

                        async for gate_event in _run_section_progress_gate():
                            yield gate_event

                retry_target = context.session.state.get(KEY_SECTION_RETRY_TARGET)
                retry_queue = context.session.state.get(KEY_SECTION_RETRY_QUEUE, []) or []
                retry_mode = bool(context.session.state.get(KEY_SECTION_RETRY_MODE, False))

                if retry_mode or retry_queue:
                    logger.info(
                        "[FLOW] Architect loop completed pass but retry is still pending. "
                        "retry_target=%s retry_queue=%s",
                        retry_target,
                        retry_queue,
                    )
                    continue

                if not is_hld_final_validation_ready(context.session.state):
                    missing_sections = get_missing_hld_sections(context.session.state)

                    logger.info(
                        "[FLOW] Final validation skipped. Sections still pending=%s",
                        missing_sections,
                    )

                    _clear_stale_arch_validation_error_if_not_final_ready(context.session.state)
                    continue

                logger.info(
                    "[FLOW] Section generation settled. Running final architecture validation once."
                )

                async for gate_event in final_arch_validation_gate.run_async(context):
                    yield gate_event

                    gate_state_delta = _get_event_state_delta_from_gate_event(gate_event)
                    if gate_state_delta:
                        context.session.state.update(gate_state_delta)

                final_retry_target = context.session.state.get(KEY_SECTION_RETRY_TARGET)
                final_retry_counts = context.session.state.get(KEY_SECTION_RETRY_COUNTS, {}) or {}
                final_retry_queue = context.session.state.get(KEY_SECTION_RETRY_QUEUE, []) or []
                final_retry_mode = bool(context.session.state.get(KEY_SECTION_RETRY_MODE, False))

                _force_selected_sections_for_retry(context.session.state)

                final_retry_target = context.session.state.get(KEY_SECTION_RETRY_TARGET)
                final_retry_counts = context.session.state.get(KEY_SECTION_RETRY_COUNTS, {}) or {}
                final_retry_queue = context.session.state.get(KEY_SECTION_RETRY_QUEUE, []) or []
                final_retry_mode = bool(context.session.state.get(KEY_SECTION_RETRY_MODE, False))

                if (
                    context.session.state.get(KEY_ARCH_COMPLETE) is not True
                    and context.session.state.get(KEY_ARCH_VALID) is False
                    and not final_retry_mode
                    and not final_retry_queue
                ):
                    logger.warning(
                        "[FLOW] Final validation left architecture invalid with empty retry queue. "
                        "Recovering retry target via section-progress gate."
                    )

                    async for gate_event in _run_section_progress_gate():
                        yield gate_event

                    _force_selected_sections_for_retry(context.session.state)

                    final_retry_target = context.session.state.get(KEY_SECTION_RETRY_TARGET)
                    final_retry_counts = context.session.state.get(KEY_SECTION_RETRY_COUNTS, {}) or {}
                    final_retry_queue = context.session.state.get(KEY_SECTION_RETRY_QUEUE, []) or []
                    final_retry_mode = bool(context.session.state.get(KEY_SECTION_RETRY_MODE, False))

                if final_retry_target and int(final_retry_counts.get(final_retry_target, 0)) >= 3:
                    if _is_malformed_retry_error(context.session.state):
                        logger.warning(
                            "[FLOW] Final retry count >= 3 for %s but error is malformed-tool-call related. "
                            "Allowing ArchitectureValidationGate recovery path.",
                            final_retry_target,
                        )
                    else:
                        error_msg = (
                            f"⚠️ **Pipeline Halted:** Section-only retry exhausted for "
                            f"`{final_retry_target}` after final validation failure."
                        )
                        logger.error("[FLOW] %s", error_msg)

                        yield Event(
                            author=self.name,
                            content=types.Content(
                                role="model",
                                parts=[types.Part(text=error_msg)],
                            ),
                        )
                        return

                if (
                    not context.session.state.get(KEY_ARCH_COMPLETE)
                    or context.session.state.get(KEY_ARCH_VALID) is False
                    or final_retry_mode
                    or final_retry_queue
                ):
                    continue

            # ----------------------------------------------------------
            # Restore UI-selected sections before final rendering.
            # KEY_SELECTED_SECTIONS may have been temporarily overwritten
            # for section-only retry. For final rendering, use the stable
            # user/UI-selected render section list.
            # ----------------------------------------------------------
            if (
                context.session.state.get(KEY_ARCH_COMPLETE) is True
                and context.session.state.get(KEY_ARCH_VALID) is True
                and not bool(context.session.state.get(KEY_SECTION_RETRY_MODE, False))
                and not (context.session.state.get(KEY_SECTION_RETRY_QUEUE, []) or [])
                and not context.session.state.get(KEY_SECTION_RETRY_TARGET)
            ):
                render_selected_sections = _normalize_selected_sections(
                    context.session.state.get(KEY_RENDER_SELECTED_SECTIONS)
                )

                if render_selected_sections:
                    logger.info(
                        "[FLOW] Restoring UI-selected sections before final render: %s",
                        render_selected_sections,
                    )
                    context.session.state[KEY_SELECTED_SECTIONS] = render_selected_sections
                else:
                    if context.session.state.get(KEY_SELECTED_SECTIONS):
                        logger.info(
                            "[FLOW] Clearing stale retry-only selected sections before final render: %s",
                            context.session.state.get(KEY_SELECTED_SECTIONS),
                        )
                    context.session.state.pop(KEY_SELECTED_SECTIONS, None)

            state = context.session.state or {}

            # ==========================================================
            # STEP 5: DOCUMENT RENDERING GATE
            # ==========================================================
            if not state.get(KEY_DOC_RENDERED):
                render_selected_sections = (
                    _normalize_selected_sections(state.get(KEY_RENDER_SELECTED_SECTIONS))
                    or _normalize_selected_sections(state.get(KEY_SELECTED_SECTIONS))
                )

                if render_selected_sections:
                    context.session.state[KEY_SELECTED_SECTIONS] = render_selected_sections
                    context.session.state[KEY_RENDER_SELECTED_SECTIONS] = render_selected_sections

                logger.info(
                    "[FLOW] Rendering Phase Active. Applying section filter: %s",
                    render_selected_sections or "None",
                )

                async for event in self.sub_agents[4].run_async(context):
                    if hasattr(event, "content") and event.content:
                        for part in event.content.parts:
                            if hasattr(part, "function_response") and part.function_response:
                                resp = part.function_response.response

                                if resp and resp.get("status") == "success":
                                    raw_signed_urls = resp.get("signed_urls") or {}
                                    clean_signed_urls = {
                                        k: v
                                        for k, v in raw_signed_urls.items()
                                        if isinstance(v, str) and v.strip()
                                    } if isinstance(raw_signed_urls, dict) else {}

                                    render_state_delta = {
                                        KEY_RENDER_ARTIFACT: (
                                            resp.get("html_path") or resp.get("html_file")
                                        ),
                                        KEY_RENDERED_PDF_PATH: resp.get("output_file"),
                                        "word_file": resp.get("word_file"),
                                        "md_file": resp.get("md_file"),
                                        "html_file": resp.get("html_file"),
                                        KEY_DOC_RENDERED: True,
                                        "render_artifacts_committed": True,
                                    }

                                    if render_selected_sections:
                                        render_state_delta[KEY_RENDER_SELECTED_SECTIONS] = render_selected_sections
                                        render_state_delta[KEY_SELECTED_SECTIONS] = render_selected_sections

                                    if clean_signed_urls:
                                        render_state_delta["signed_urls"] = clean_signed_urls

                                    local_download_urls = resp.get(KEY_LOCAL_DOWNLOAD_URLS) or {}
                                    clean_local_download_urls = {
                                        k: v
                                        for k, v in local_download_urls.items()
                                        if isinstance(v, str) and v.strip()
                                    } if isinstance(local_download_urls, dict) else {}

                                    if clean_local_download_urls:
                                        render_state_delta[KEY_LOCAL_DOWNLOAD_URLS] = clean_local_download_urls

                                    local_view_urls = resp.get(KEY_LOCAL_VIEW_URLS) or {}
                                    clean_local_view_urls = {
                                        k: v
                                        for k, v in local_view_urls.items()
                                        if isinstance(v, str) and v.strip()
                                    } if isinstance(local_view_urls, dict) else {}

                                    if clean_local_view_urls:
                                        render_state_delta[KEY_LOCAL_VIEW_URLS] = clean_local_view_urls

                                    if resp.get("gcs_pdf"):
                                        render_state_delta["gcs_pdf"] = resp.get("gcs_pdf")
                                    if resp.get("gcs_docx"):
                                        render_state_delta["gcs_docx"] = resp.get("gcs_docx")
                                    if resp.get("gcs_md"):
                                        render_state_delta["gcs_md"] = resp.get("gcs_md")
                                    if resp.get("gcs_html"):
                                        render_state_delta["gcs_html"] = resp.get("gcs_html")

                                    _apply_state_delta_to_session(context, render_state_delta)

                                    logger.info(
                                        "✅ Render artifacts committed to state | "
                                        "HTML=%s | PDF=%s | SIGNED_URLS=%s | LOCAL_DOWNLOAD_URLS=%s | SECTIONS=%s",
                                        render_state_delta.get(KEY_RENDER_ARTIFACT),
                                        render_state_delta.get(KEY_RENDERED_PDF_PATH),
                                        "yes" if clean_signed_urls else "no",
                                        "yes" if clean_local_download_urls else "no",
                                        render_selected_sections or "ALL",
                                    )

                                    yield Event(
                                        author=self.name,
                                        content=types.Content(
                                            role="model",
                                            parts=[types.Part(text="")],
                                        ),
                                        actions=EventActions(
                                            state_delta=render_state_delta,
                                            escalate=False,
                                        ),
                                    )

                                    assert (
                                        context.session.state.get("signed_urls")
                                        or context.session.state.get(KEY_LOCAL_DOWNLOAD_URLS)
                                        or context.session.state.get(KEY_LOCAL_VIEW_URLS)
                                        or context.session.state.get(KEY_RENDER_ARTIFACT)
                                        or context.session.state.get(KEY_RENDERED_PDF_PATH)
                                    ), (
                                        "Invariant violation: Document rendered but no artifacts, "
                                        "local URLs, or signed URLs present in session state"
                                    )

                                elif resp and resp.get("status") == "error":
                                    error_msg = resp.get("message", "Unknown error")
                                    logger.error(
                                        "🛑 Fatal Tool Error: %s. Halting pipeline.",
                                        error_msg,
                                    )

                                    yield Event(
                                        author=self.name,
                                        content=types.Content(
                                            role="model",
                                            parts=[
                                                types.Part(
                                                    text=(
                                                        "⚠️ **Document Rendering Failed:**\n"
                                                        f"`{error_msg}`\n\n"
                                                        "The pipeline has been halted."
                                                    )
                                                )
                                            ],
                                        ),
                                    )
                                    return

                    yield event

                # if not context.session.state.get(KEY_DOC_RENDERED):
                #     return

                # yield Event(
                #     author=self.name,
                #     content=types.Content(
                #         role="model",
                #         parts=[
                #             types.Part(
                #                 text="✅ Document rendered successfully (90%). Preparing output."
                #             )
                #         ],
                #     ),
                # )
                # continue
                if not context.session.state.get(KEY_DOC_RENDERED):
                    return

                logger.info(
                    "[FLOW] Document rendered successfully. "
                    "Proceeding to OutputAgent in the same orchestrator invocation."
                )

                render_to_output_delta = {
                    INTERNAL_OUTPUT_PENDING: True,
                    INTERNAL_OUTPUT_DELIVERED: False,
                    INTERNAL_FINAL_OUTPUT_READY: False,
                }

                _apply_state_delta_to_session(context, render_to_output_delta)

                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text="✅ Document rendered successfully (90%). Preparing output."
                            )
                        ],
                    ),
                    actions=EventActions(
                        state_delta=render_to_output_delta,
                        escalate=False,
                    ),
                )

                # IMPORTANT:
                # Do NOT use `continue` here.
                # Falling through allows STEP 6 OutputAgent to run immediately
                # in the same orchestrator invocation.
                state = context.session.state or {}            

            # ==========================================================
            # STEP 6: OUTPUT & REVISION ROUTING
            # ==========================================================
            logger.info("[FLOW] Output Phase Active.")

            async for event in self.sub_agents[5].run_async(context):
                yield event

            if context.session.state.get(KEY_WORKFLOW_RESET_REQUESTED):
                logger.info(
                    "🔄 Revision requested! Re-entering workflow from intake as full revision."
                )

                reset_delta = _reset_pipeline_for_revision(
                    context,
                    full_rerun=True,
                    revision_request=(context.session.state or {}).get(KEY_REVISION_NOTES),
                )

                reset_delta[KEY_WORKFLOW_RESET_REQUESTED] = False
                reset_delta[KEY_REVISION_REQUESTED] = False
                reset_delta[KEY_REVISION_READY] = False

                _apply_state_delta_to_session(context, reset_delta)
                context.session.state.pop("revision_mode", None)

                yield Event(
                    author=self.name,
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                text=(
                                    "🔄 Revision requested from output phase. "
                                    "Restarting full workflow from intake."
                                )
                            )
                        ],
                    ),
                    actions=EventActions(
                        state_delta=reset_delta,
                        escalate=False,
                    ),
                )

                continue

            completion_delta = {
                KEY_REVISION_READY: True,
                KEY_WORKFLOW_RESET_REQUESTED: False,
                KEY_REVISION_REQUESTED: False,

                # Revision rerun is now complete because OutputAgent has delivered output.
                INTERNAL_REVISION_RUN_ACTIVE: False,

                # Output lifecycle is now complete.
                INTERNAL_OUTPUT_PENDING: False,
                INTERNAL_OUTPUT_DELIVERED: True,
                INTERNAL_FINAL_OUTPUT_READY: True,
                "final_output_ready": True,
                "output_delivered": True,
            }
            _apply_state_delta_to_session(context, completion_delta)

            yield Event(
                author=self.name,
                content=types.Content(
                    role="model",
                    parts=[types.Part(text="✅ Workflow complete (100%). Final output ready.")],
                ),
                actions=EventActions(
                    state_delta=completion_delta,
                    escalate=False,
                ),
            )

            logger.info("[FLOW] Waiting for new user input or revision request...")
            return


root_agent = GatedSequentialAgent(
    name="AIA_Engine",
    description=(
        "AIA Orchestrator with signal-driven architect extraction, "
        "Word support, resilient parsing, and full workflow revision reset."
    ),
    sub_agents=[
        intake_agent,         # [0]
        blueprint_agent,      # [1]
        research_agent,       # [2]
        architect_loop,       # [3]
        doc_rendering_agent,  # [4]
        output_agent,         # [5]
    ],
)
