"""
Lightweight package init for agent.workflow.

IMPORTANT:
- Do NOT eagerly import architect_loop / workflow agents here.
- This package is imported transitively when submodules like
  `agent.workflow.keys` are imported.
- Eager imports here can create circular imports with:
    tools.hld_section_commit_tools
    -> agent.workflow.keys
    -> agent.workflow.__init__
    -> agent.workflow.architect_loop
    -> agent.architect_agent.agent
    -> tools.hld_section_commit_tools

Backward compatibility preserved via lazy attribute loading.
"""

from importlib import import_module
from typing import Any

__all__ = [
    "architect_loop",
    "arch_validation_gate",
    "final_arch_validation_gate",
]


def __getattr__(name: str) -> Any:
    if name in {
        "architect_loop",
        "arch_validation_gate",
        "final_arch_validation_gate",
    }:
        module = import_module("agent.workflow.architect_loop")
        return getattr(module, name)

    raise AttributeError(f"module 'agent.workflow' has no attribute '{name}'")