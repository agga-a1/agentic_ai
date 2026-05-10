from typing import Any, Dict
from google.adk.tools import FunctionTool

from agent.workflow.keys import KEY_HLD_COMMIT_TRIGGERED


def commit_hld_to_memory(tool_context=None) -> Dict[str, Any]:
    """
    Signals the Orchestrator that the JSON has been printed
    and is ready to be scraped from the event stream.
    """
    if tool_context is None or not hasattr(tool_context, "session"):
        return {
            "status": "error",
            "message": "Context missing.",
            "stateDelta": {}
        }

    state_delta = {
        KEY_HLD_COMMIT_TRIGGERED: True
    }

    state = tool_context.session.state or {}
    state.update(state_delta)
    tool_context.session.state = state

    return {
        "status": "success",
        "message": "Signal sent. Orchestrator will now extract the payload.",
        "stateDelta": state_delta
    }


commit_hld_tool = FunctionTool(func=commit_hld_to_memory)