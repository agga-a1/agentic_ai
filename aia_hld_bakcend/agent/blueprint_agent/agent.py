import os
import logging
from typing import Any, Dict

from dotenv import load_dotenv
from google.adk.agents import LlmAgent

from tools.search_vector_blueprints import search_blueprint_bundle_tool
from tools.state_store import store_in_state_tool
from .prompt import get_blueprint_prompt

# Synchronize with centralized keys
from agent.workflow.keys import (
    KEY_INTAKE, 
    KEY_USER_REQUEST, 
    KEY_BLUEPRINT_SELECTED, 
    KEY_BLUEPRINT_RESULTS,
    KEY_BLUEPRINT_SEARCH_DONE,
    KEY_REVISION_REQUEST,   # ✅ NEW: additive observability for revision runs
    KEY_SELECTED_SECTIONS,  # ✅ NEW: additive observability for scoped reruns
)

load_dotenv()
logger = logging.getLogger("BlueprintAgent")


def _instruction_provider(ctx) -> str:
    """
    Dynamic instruction builder for Blueprint agent.
    Checks state to ensure required inputs from Intake are available.
    """
    session = getattr(ctx, "session", None)
    state = getattr(session, "state", {}) if session else {}
    if state is None:
        state = {}

    revision_request = state.get(KEY_REVISION_REQUEST)
    selected_sections = state.get(KEY_SELECTED_SECTIONS)

    # Logic-based logging to verify the agent has what it needs
    logger.info(
        "[BLUEPRINT] instruction_provider - %s_present=%s | %s_present=%s | %s_present=%s | %s=%s",
        KEY_INTAKE, isinstance(state.get(KEY_INTAKE), dict),
        KEY_USER_REQUEST, isinstance(state.get(KEY_USER_REQUEST), str),
        KEY_REVISION_REQUEST, isinstance(revision_request, str) and bool(revision_request.strip()),
        KEY_SELECTED_SECTIONS, selected_sections,
    )

    return get_blueprint_prompt()


class BlueprintSubAgent(LlmAgent):
    """
    Sub-agent responsible for blueprint discovery.
    The state store derives KEY_BLUEPRINT_SEARCH_DONE once results are saved.
    """
    async def on_turn_complete(self, context):
        """
        Workflow Turn Logic:
        - If blueprint_search_done is true, we return "proceed" to help the 
          GatedSequentialAgent move to the Research phase.

        Additive resiliency:
        - If blueprint results exist but KEY_BLUEPRINT_SEARCH_DONE was not derived,
          self-heal the flag to avoid getting stuck.
        """
        state = context.session.state or {}
        
        search_done = state.get(KEY_BLUEPRINT_SEARCH_DONE, False)
        has_selected = KEY_BLUEPRINT_SELECTED in state
        has_results = KEY_BLUEPRINT_RESULTS in state

        # ✅ NEW: additive self-heal for derived-state mismatch
        results_value = state.get(KEY_BLUEPRINT_RESULTS)
        if not search_done and isinstance(results_value, list) and len(results_value) > 0:
            state[KEY_BLUEPRINT_SEARCH_DONE] = True
            context.session.state = state
            search_done = True

            logger.warning(
                "[BLUEPRINT] Self-healed %s=True because %s contained %d result(s).",
                KEY_BLUEPRINT_SEARCH_DONE,
                KEY_BLUEPRINT_RESULTS,
                len(results_value),
            )

        logger.info(
            "[BLUEPRINT] turn complete. search_done=%s | has_selected=%s | has_results=%s",
            search_done, has_selected, has_results
        )

        # If search is complete, allow orchestrator to advance
        if search_done:
            return "proceed"
            
        return None


blueprint_agent = BlueprintSubAgent(
    name="BlueprintSubAgent",
    model=os.getenv("GOOGLE_GENAI_MODEL"),
    instruction=_instruction_provider,
    description="Internal blueprint discovery step. Searches blueprints and stores results to state.",
    tools=[
        search_blueprint_bundle_tool,
        # store_in_state_tool,
    ],
)