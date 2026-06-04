import os
import logging
from dotenv import load_dotenv

from google.adk.agents import LlmAgent

from tools.state_store import store_in_state_tool
from .prompt import get_research_prompt
# Synchronize with centralized keys
from agent.workflow.keys import (
    KEY_RESEARCH_RESOLVED,
    KEY_TECHNICAL_RESEARCH_SUMMARY,
    KEY_RESOLVED_SERVICES,
    KEY_INTAKE,
    KEY_BLUEPRINT_SELECTED
)

load_dotenv()
logger = logging.getLogger("ResearchAgent")

def _instruction_provider(ctx) -> str:
    """
    Workflow mode:
    - Research agent computes gaps based on KEY_INTAKE and KEY_BLUEPRINT_SELECTED.
    - We use the prompt wrapper which relies on ADK state templating.
    """
    session = getattr(ctx, "session", None)
    state = getattr(session, "state", {}) if session else {}
    
    # Log availability of inputs for debugging
    logger.info(
        "[RESEARCH] instruction_provider - intake_ready=%s blueprint_ready=%s",
        KEY_INTAKE in state,
        KEY_BLUEPRINT_SELECTED in state or "blueprint_results" in state
    )
    
    return get_research_prompt()

class ResearchSubAgent(LlmAgent):
    """
    Sub-agent responsible for technical gap analysis and fact-finding.
    """
    async def on_turn_complete(self, context):
        """
        Workflow Turn Logic:
        - If research_resolved is true (derived by StateStore after tool call),
          return "proceed" to advance the GatedSequentialAgent.
        """
        try:
            state = context.session.state or {}
            
            resolved = state.get(KEY_RESEARCH_RESOLVED, False)
            has_summary = KEY_TECHNICAL_RESEARCH_SUMMARY in state
            has_services = KEY_RESOLVED_SERVICES in state

            logger.info(
                "[RESEARCH] on_turn_complete - resolved=%s | summary=%s | services=%s",
                resolved, has_summary, has_services
            )

            if resolved:
                # Signal orchestrator to move to Architect stage
                return "proceed"

        except Exception as e:
            logger.error(f"[RESEARCH] Error in on_turn_complete: {e}")

        return None

research_agent = ResearchSubAgent(
    name="ResearchSubAgent",
    model=os.getenv("GOOGLE_GENAI_MODEL"),
    instruction=_instruction_provider,
    description="Technical research agent. Maps intake and blueprints to immutable facts.",
    tools=[store_in_state_tool],
)