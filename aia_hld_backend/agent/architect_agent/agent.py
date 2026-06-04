import os
import json
import logging
from typing import Any, Dict, Optional, List

from dotenv import load_dotenv
from google.adk.agents import LlmAgent

# Existing raw JSON commit tool (KEEP for backward compatibility / hybrid mode)
from tools.commit_hld_to_memory import commit_hld_tool

# New dynamic section commit tools
from tools.hld_section_commit_tools import get_hld_section_commit_tools

from .prompt import get_architecture_prompt
from agent.workflow.keys import (
    KEY_INTAKE,
    KEY_BLUEPRINT_SELECTED,
    KEY_BLUEPRINT_RESULTS,
    KEY_TECHNICAL_RESEARCH_SUMMARY,
    KEY_ARCH_COMPLETE,
    KEY_HLD_REPORT_JSON,
    KEY_VALIDATION_ERROR,
    KEY_SELECTED_SECTIONS,  # ✅ EXISTING: pass selected sections into prompt

    # ✅ NEW: section-only retry support
    KEY_SECTION_RETRY_TARGET,
    KEY_SECTION_RETRY_MODE,
    KEY_SECTION_RETRY_QUEUE,
    KEY_SECTION_RETRY_COUNTS,
)

load_dotenv()
logger = logging.getLogger("ArchitectAgent")


def _safe_json(obj: Any) -> str:
    if obj is None:
        return ""
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj) if obj else ""


def _safe_selected_sections(value: Any) -> str:
    """
    Normalize selected sections from state into a prompt-safe string.
    Supports:
    - list[str]
    - comma-separated string
    - None
    """
    if value is None:
        return ""

    if isinstance(value, list):
        cleaned = [str(x).strip() for x in value if str(x).strip()]
        return ", ".join(cleaned)

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _safe_retry_target(value: Any) -> str:
    """
    Normalize section retry target into a prompt-safe string.
    Supports:
    - str
    - None
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    return str(value).strip()


def _instruction_provider(ctx) -> str:
    """
    Dynamically builds the Architect's instructions using current state.
    """
    session = getattr(ctx, "session", None)
    state = getattr(session, "state", {}) if session else {}
    if state is None:
        state = {}

    # Gather Inputs from Centralized Keys
    intake = state.get(KEY_INTAKE) or {}
    blueprint = state.get(KEY_BLUEPRINT_SELECTED) or state.get(KEY_BLUEPRINT_RESULTS) or {}
    research = state.get(KEY_TECHNICAL_RESEARCH_SUMMARY) or {}

    # Critical: Fetch any error from the Validation Gate
    validation_error = state.get(KEY_VALIDATION_ERROR) or ""

    # ✅ EXISTING: selected sections support
    selected_sections = _safe_selected_sections(state.get(KEY_SELECTED_SECTIONS))

    # ✅ NEW: section-only retry support
    section_retry_target = _safe_retry_target(state.get(KEY_SECTION_RETRY_TARGET))
    section_retry_mode = bool(state.get(KEY_SECTION_RETRY_MODE, False))
    section_retry_queue = state.get(KEY_SECTION_RETRY_QUEUE, []) or []
    section_retry_counts = state.get(KEY_SECTION_RETRY_COUNTS, {}) or {}

    logger.info(
        "[ARCH] instruction_provider | intake=%s | blueprint=%s | research=%s | "
        "validation_error=%s | selected_sections=%s | retry_mode=%s | retry_target=%s | retry_queue=%s | retry_counts=%s",
        bool(intake),
        bool(blueprint),
        bool(research),
        bool(validation_error),
        selected_sections or "ALL (Default)",
        section_retry_mode,
        section_retry_target or "<none>",
        section_retry_queue,
        section_retry_counts,
    )

    return get_architecture_prompt(
        intake_summary=_safe_json(intake),
        blueprint_payload=_safe_json(blueprint),
        research_summary=_safe_json(research),
        validation_error=str(validation_error),
        selected_sections=selected_sections,

        # ✅ NEW: section-only retry support
        section_retry_target=section_retry_target,
        section_retry_mode=section_retry_mode,
    )


class ArchitectSubAgent(LlmAgent):
    async def on_turn_complete(self, context):
        """
        Architecture Step Logic:
        - We return None to end the turn.
        - The 'ArchitectLoop' will then call the 'ArchitectureValidationGate'.
        - If the Gate is happy, the workflow moves to Rendering.
        """
        state = context.session.state or {}

        logger.info(
            "[ARCH] Turn complete. has_hld=%s | complete=%s | error_present=%s | "
            "retry_mode=%s | retry_target=%s | retry_queue=%s | retry_counts=%s",
            KEY_HLD_REPORT_JSON in state,
            state.get(KEY_ARCH_COMPLETE),
            bool(state.get(KEY_VALIDATION_ERROR)),
            bool(state.get(KEY_SECTION_RETRY_MODE, False)),
            state.get(KEY_SECTION_RETRY_TARGET),
            state.get(KEY_SECTION_RETRY_QUEUE, []),
            state.get(KEY_SECTION_RETRY_COUNTS, {}),
        )

        return None


# ==========================================================
# TOOL REGISTRATION (HYBRID MODE)
# ==========================================================
# KEEP existing raw JSON commit tool for backward compatibility.
# ADD dynamic section commit tools for the new section-wise architecture build flow.
section_commit_tools: List[Any] = get_hld_section_commit_tools()

# ✅ EXISTING: defensive dedupe by tool name
_seen_tool_names = set()
all_architect_tools: List[Any] = []

for tool in [commit_hld_tool, *section_commit_tools]:
    tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", None) or str(tool)
    if tool_name not in _seen_tool_names:
        _seen_tool_names.add(tool_name)
        all_architect_tools.append(tool)

logger.info(
    "[ARCH] Registered %s architect tools (%s section tools + fallback commit_hld_tool).",
    len(all_architect_tools),
    len(section_commit_tools),
)


# ✅ UPDATED: safer model resolution with real fallback usage
architect_model = os.getenv("GOOGLE_GENAI_MODEL")
if not architect_model:
    architect_model = "gemini-2.5-flash"
    logger.warning(
        "[ARCH] GOOGLE_GENAI_MODEL not set. Falling back to 'gemini-2.5-flash'."
    )


architect_agent = ArchitectSubAgent(
    name="ArchitectSubAgent",
    model=architect_model,
    instruction=_instruction_provider,
    description=(
        "Generates technical HLD content. Validation and looping are managed by the ArchitectLoop. "
        "Supports both raw JSON commit flow and section-wise commit flow. "
        "Also supports section-only retry mode driven by ArchitectureValidationGate."
    ),
    tools=all_architect_tools,
)
