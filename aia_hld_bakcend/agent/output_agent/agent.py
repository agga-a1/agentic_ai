import os
import logging

from dotenv import load_dotenv
from google.adk.agents import LlmAgent

from tools.state_store import store_in_state_tool
from .prompt import get_output_prompt

from agent.workflow.keys import KEY_DOC_RENDERED, KEY_RENDER_ARTIFACT

load_dotenv()
logger = logging.getLogger("OutputAgent")


def _instruction_provider(ctx) -> str:
    """
    Dynamic instruction builder:
    Injects the full state so the agent can narrate the final HLD location
    and handle specific follow-up questions about the architecture.
    """
    session = getattr(ctx, "session", None)
    state = getattr(session, "state", {}) if session else {}
    if state is None:
        state = {}

    return get_output_prompt(state)


class OutputSubAgent(LlmAgent):
    """
    The 'Finisher' Agent.
    It presents the final result and stays active for user feedback.
    """

    async def on_turn_complete(self, context):
        """
        Terminal Turn Logic:
        - If the user provides feedback, the model will use store_in_state_tool
          to set workflow reset fields.
        - This agent returns None to wait for the user, allowing the
          GatedSequentialAgent to decide if it needs to loop back.
        """
        state = context.session.state or {}

        logger.info(
            "[OUTPUT] turn complete. %s=%s | %s=%s | local_download_urls=%s | signed_urls=%s",
            KEY_DOC_RENDERED,
            state.get(KEY_DOC_RENDERED),
            KEY_RENDER_ARTIFACT,
            bool(state.get(KEY_RENDER_ARTIFACT)),
            bool(state.get("local_download_urls")),
            bool(state.get("signed_urls")),
        )

        # OutputAgent is terminal/conversational.
        return None


output_agent = OutputSubAgent(
    name="OutputSubAgent",
    model=os.getenv("GOOGLE_GENAI_MODEL"),
    instruction=_instruction_provider,
    description="Final output agent. Presents the HLD link and handles revision requests.",
    tools=[store_in_state_tool],
)