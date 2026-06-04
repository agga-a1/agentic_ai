"""
Lightweight package init for agent.architect_agent.

IMPORTANT:
- Do NOT eagerly import architect_agent here.
- Eager imports can participate in circular import chains when
  architect_loop imports agent.architect_agent.agent while the
  package is still initializing.

Backward compatibility preserved:
- `from agent.architect_agent import architect_agent` still works.
"""

from importlib import import_module
from typing import Any
__all__ = ["architect_agent"]


def __getattr__(name: str) -> Any:
    if name == "architect_agent":
        module = import_module("agent.architect_agent.agent")
        return module.architect_agent
    raise AttributeError(f"module 'agent.architect_agent' has no attribute '{name}'")
