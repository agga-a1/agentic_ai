# tools/state_store_alias.py
from typing import Any

from tools.state_store import store_in_state
from google.adk.tools import FunctionTool
def default_in_state(
    key: str,
    value: Any,
    merge: bool = True,
    tool_context=None,
    **kwargs,
) -> str:
    """
    Alias tool: default_in_state -> store_in_state

    This prevents workflow failures when the model hallucinates 'default_in_state'.
    """
    return store_in_state(
        key=key,
        value=value,
        merge=merge,
        tool_context=tool_context,
        **kwargs,
    )

default_in_state_tool = FunctionTool(func=default_in_state)