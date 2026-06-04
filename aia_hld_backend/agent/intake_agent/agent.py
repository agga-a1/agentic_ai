import os
import json
from typing import Dict, Any
from dotenv import load_dotenv
from google.adk.agents import LlmAgent

from tools.state_store import store_in_state_tool
from agent.intake_agent.prompt import get_intake_prompt

# Import keys to stay consistent
from agent.workflow.keys import (
    KEY_INTAKE_MISSING_FIELDS,
    KEY_INTAKE_COMPLETE,
    KEY_USER_REQUEST,
    KEY_REVISION_NOTES,
    KEY_REVISION_REQUESTED,
    KEY_REVISION_CONTEXT,
    KEY_ORIGINAL_USER_REQUEST,
    KEY_SELECTED_SECTIONS,
    KEY_RENDER_SELECTED_SECTIONS,
)

load_dotenv()


def _normalize_selected_sections(value: Any) -> list[str]:
    """
    Normalize selected sections from state.

    Supports:
    - list[str]
    - comma-separated string
    - JSON string list

    This is defensive because the intake LLM/tool may persist section lists
    either as a native list or as a string depending on the tool schema/model call.
    """
    if value is None:
        return []

    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []

        if raw.startswith("[") and raw.endswith("]"):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass

        return [item.strip() for item in raw.split(",") if item.strip()]

    return []


def _sync_render_selected_sections(state: Dict[str, Any]) -> None:
    """
    Ensure render_selected_sections is populated from selected_sections.

    selected_sections:
        Current/user-selected sections captured by Intake.

    render_selected_sections:
        Stable final document render filter used later by doc rendering.

    Important:
    - Do not overwrite render_selected_sections if it already exists.
    - Only populate it from selected_sections when missing.
    """
    if not isinstance(state, dict):
        return

    render_selected_sections = _normalize_selected_sections(
        state.get(KEY_RENDER_SELECTED_SECTIONS)
    )

    if render_selected_sections:
        state[KEY_RENDER_SELECTED_SECTIONS] = render_selected_sections
        return

    selected_sections = _normalize_selected_sections(
        state.get(KEY_SELECTED_SECTIONS)
    )

    if selected_sections:
        state[KEY_SELECTED_SECTIONS] = selected_sections
        state[KEY_RENDER_SELECTED_SECTIONS] = selected_sections


def _build_effective_request(state: Dict[str, Any]) -> str:
    """
    Build the working request used for downstream stages.

    Revision behavior:
    - Preserve the existing/original architecture request.
    - Apply revision notes on top.
    - Return one effective request for blueprint/research/architect.
    """
    current_request = (state.get(KEY_USER_REQUEST) or "").strip()
    original_request = (state.get(KEY_ORIGINAL_USER_REQUEST) or "").strip()
    revision_notes = (state.get(KEY_REVISION_NOTES) or "").strip()

    # Prefer explicitly preserved original request.
    # Fallback to current user request.
    base_request = original_request or current_request

    if revision_notes and base_request:
        return (
            "Existing architecture request/context:\n"
            f"{base_request}\n\n"
            "User revision/change request:\n"
            f"{revision_notes}\n\n"
            "Instruction:\n"
            "Apply the revision/change request to the existing architecture context. "
            "Preserve all unchanged requirements, assumptions, constraints, integrations, "
            "non-functional requirements, and selected design decisions unless the revision "
            "explicitly changes them."
        ).strip()

    if revision_notes:
        return revision_notes

    return base_request


def _instruction_provider(ctx) -> str:
    """
    Safely retrieves state to build the dynamic system prompt.
    Revision-aware version.
    """
    session = getattr(ctx, "session", None)
    state = getattr(session, "state", {}) if session else {}

    if state is None:
        state = {}

    # Keep render selection synced before prompt is built.
    # This makes selected sections visible/stable for later workflow stages.
    _sync_render_selected_sections(state)

    missing = state.get(KEY_INTAKE_MISSING_FIELDS, [])
    intake_complete = bool(state.get(KEY_INTAKE_COMPLETE, False))
    next_field = missing[0] if missing else None

    current_request = (state.get(KEY_USER_REQUEST) or "").strip()
    original_request = (state.get(KEY_ORIGINAL_USER_REQUEST) or current_request).strip()
    revision_notes = (state.get(KEY_REVISION_NOTES) or "").strip()

    revision_context = state.get(KEY_REVISION_CONTEXT)
    if not isinstance(revision_context, dict):
        revision_context = None

    is_revision = bool(
        revision_notes
        or state.get(KEY_REVISION_REQUESTED)
        or revision_context
    )

    effective_request = _build_effective_request(state)

    return get_intake_prompt(
        missing_fields=missing,
        next_field=next_field,
        intake_complete=intake_complete,
        original_request=original_request,
        revision_request=revision_notes,
        effective_request=effective_request,
        is_revision=is_revision,
        revision_context=revision_context,
    )


class IntakeAgent(LlmAgent):
    """
    Sub-agent that manages user data collection.
    Pauses execution until requirements are met.
    """

    async def on_turn_complete(self, context):
        state = context.session.state or {}

        # Ensure selected sections captured by intake are mirrored into the
        # stable renderer filter key before the orchestrator reaches rendering.
        _sync_render_selected_sections(state)

        # If intake is complete, persist the effective request for downstream stages.
        if state.get(KEY_INTAKE_COMPLETE):
            effective_request = _build_effective_request(state)

            if effective_request:
                # Downstream agents continue reading KEY_USER_REQUEST.
                state[KEY_USER_REQUEST] = effective_request

                # Store latest effective request as baseline for future revisions.
                state[KEY_ORIGINAL_USER_REQUEST] = effective_request

            # Revision has now been normalized into KEY_USER_REQUEST.
            # Clear revision notes so they are not re-applied repeatedly.
            state.pop(KEY_REVISION_NOTES, None)
            state[KEY_REVISION_REQUESTED] = False

            # Keep selected sections stable after any revision normalization.
            _sync_render_selected_sections(state)

            context.session.state = state

            # Signal the GatedSequentialAgent that this step is done.
            return "proceed"

        context.session.state = state

        # Returning None stops the agent from taking another turn
        # and waits for the user's next message.
        return None


intake_agent = IntakeAgent(
    name="IntakeSubAgent",
    model=os.getenv("GOOGLE_GENAI_MODEL"),
    instruction=_instruction_provider,
    description="Collects mandatory architecture intake fields and confirms them via StateStore.",
    tools=[store_in_state_tool],
)