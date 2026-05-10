"""
Lightweight package init for agent.

IMPORTANT:
- Do NOT eagerly import heavy runtime modules here.
- Eager imports from .agent create circular-import chains during startup.
- Use lazy attribute loading instead.

Backward compatibility preserved:
- `from agent import root_agent` will still work.
"""
from .agent import root_agent
from importlib import import_module
from typing import Any

__all__ = ["root_agent"]


def __getattr__(name: str) -> Any:
    if name == "root_agent":
        module = import_module("agent.agent")
        return module.root_agent
    raise AttributeError(f"module 'agent' has no attribute '{name}'")