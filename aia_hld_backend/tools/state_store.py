# from __future__ import annotations

# from typing import Any, Dict, Optional, Tuple, List
# import copy
# import json
# import re

# from pydantic import ValidationError

# from agent.logging_setup import get_logger
# from schema_types.aia_intake_schema import IntakeSchema
# from google.adk.tools import FunctionTool

# # Centralized Key Imports
# from agent.workflow.keys import (
#     KEY_INTAKE, KEY_INTAKE_CONFIRMED, KEY_INTAKE_COMPLETE, 
#     KEY_INTAKE_MISSING_FIELDS, KEY_INTAKE_VALIDATION_ERROR,
#     KEY_BLUEPRINT_RESULTS, KEY_BLUEPRINT_SEARCH_DONE, KEY_BLUEPRINT_NO_MATCH,
#     KEY_RESEARCH_RESOLVED, KEY_TECHNICAL_RESEARCH_SUMMARY,
#     KEY_ARCH_COMPLETE, KEY_HLD_REPORT_JSON, KEY_ARCH_VALID,
#     KEY_VALIDATION_ERROR, KEY_DOC_RENDERED, KEY_RENDER_ARTIFACT,
#     KEY_WORKFLOW_RESET_REQUESTED, KEY_INITIALIZED,
#     KEY_HLD_COMMIT_TRIGGERED,
#     KEY_SELECTED_SECTIONS # 💥 ADDED NEW KEY
# )

# logger = get_logger("StateStore")

# # =============================================================================
# # Utilities
# # =============================================================================
# def _as_bool(v: Any) -> bool:
#     if isinstance(v, bool): return v
#     if isinstance(v, str): return v.strip().lower() in ("true", "1", "yes", "y")
#     return False

# def _to_snake(name: str) -> str:
#     if not isinstance(name, str): return str(name)
#     return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

# def _is_placeholder(v: Any) -> bool:
#     if v is None: return True
#     if isinstance(v, str):
#         return v.strip().lower() in ("", "tbc", "unknown", "n/a", "pending")
#     return False

# def _deep_merge(dst: Any, src: Any) -> Any:
#     if isinstance(dst, dict) and isinstance(src, dict):
#         for k, v in src.items():
#             dst[k] = _deep_merge(dst[k], v) if k in dst else copy.deepcopy(v)
#         return dst
#     return copy.deepcopy(src)

# # =============================================================================
# # Persistence Helpers
# # =============================================================================
# def _commit_delta(tool_context, delta: Dict[str, Any]) -> None:
#     try:
#         actions = getattr(tool_context, "event_actions", None) or getattr(tool_context, "actions", None)
#         if callable(actions): actions = actions()
        
#         for attr in ("stateDelta", "state_delta"):
#             if hasattr(actions, attr):
#                 sd = getattr(actions, attr) or {}
#                 _deep_merge(sd, delta)
#                 setattr(actions, attr, sd)
#                 return
#     except Exception as e:
#         logger.warning(f"[STATE_STORE] Failed to commit delta: {e}")

# # =============================================================================
# # Schema & Intake Logic
# # =============================================================================
# _INTAKE_KEYMAP = { _to_snake(k): k for k in IntakeSchema.model_fields.keys() }
# _REQUIRED = [k for k, f in IntakeSchema.model_fields.items() if f.is_required()]

# def _canonical(key: str) -> str:
#     norm = _to_snake(key)
#     return _INTAKE_KEYMAP.get(norm, norm)

# def _ingest_to_intake(state: Dict[str, Any], key: str, value: Any, confirmed: bool) -> bool:
#     intake = state.setdefault(KEY_INTAKE, {})
#     conf = state.setdefault(KEY_INTAKE_CONFIRMED, {})
    
#     if isinstance(value, dict):
#         changed = False
#         for k, v in value.items():
#             changed = _ingest_to_intake(state, k, v, confirmed) or changed
#         return changed

#     field = _canonical(key)
#     if field not in IntakeSchema.model_fields: return False

#     if _is_placeholder(value):
#         if field in intake: del intake[field]
#         conf[field] = False
#         return True

#     if field in _REQUIRED and not confirmed:
#         conf[field] = False
#         return False

#     if intake.get(field) != value:
#         intake[field] = value
#         conf[field] = confirmed
#         return True
#     return False

# # =============================================================================
# # Main Tool: store_in_state
# # =============================================================================
# def store_in_state(
#     key: str,
#     value: Any,
#     merge: bool = True,
#     confirmed: bool = False,
#     tool_context=None,
#     **kwargs,
# ):
#     logger.info(f"[STATE_STORE] Writing key={key} | confirmed={confirmed}")
#     if tool_context is None: raise ValueError("tool_context required.")

#     state = tool_context.session.state or {}
#     delta = {}

#     # Protect Workflow Logic Keys from direct LLM manipulation
#     _PROTECTED = {KEY_INTAKE_COMPLETE, KEY_INTAKE_MISSING_FIELDS, KEY_ARCH_COMPLETE, KEY_DOC_RENDERED}
#     if key in _PROTECTED:
#         return {"result": f"Write to {key} ignored; derived logic only.", "stateDelta": delta}

#     # ==========================================
#     # FIXED: Handle Reset properly commits state
#     # ==========================================
#     if key == KEY_WORKFLOW_RESET_REQUESTED and _as_bool(value):
#         state[KEY_WORKFLOW_RESET_REQUESTED] = True
#         delta[KEY_WORKFLOW_RESET_REQUESTED] = True
        
#         state[KEY_ARCH_COMPLETE] = False
#         delta[KEY_ARCH_COMPLETE] = False
        
#         state[KEY_RESEARCH_RESOLVED] = False
#         delta[KEY_RESEARCH_RESOLVED] = False
        
#         tool_context.session.state = state
#         _commit_delta(tool_context, delta)
#         return {"result": "Workflow reset complete. Routing to Orchestrator.", "stateDelta": delta}

#     # 💥 NEW: Safely intercept and format selected HLD sections
#     if key == KEY_SELECTED_SECTIONS:
#         if isinstance(value, str):
#             # Parse comma-separated string back into a clean list
#             parsed_list = [s.strip() for s in value.split(",") if s.strip()]
#             state[key] = parsed_list
#         else:
#             state[key] = value
            
#         delta[key] = copy.deepcopy(state[key])
#         tool_context.session.state = state
#         _commit_delta(tool_context, delta)
#         return {"result": f"Successfully stored {len(state[key])} requested sections.", "stateDelta": delta}


#     # 1. Intake Ingestion
#     intake_complete_before = _as_bool(state.get(KEY_INTAKE_COMPLETE))
#     is_intake_field = _canonical(key) in IntakeSchema.model_fields

#     if (not intake_complete_before) or (intake_complete_before and is_intake_field and confirmed):
#         _ingest_to_intake(state, key, value, confirmed)

#     # 2. Standard Storage
#     if merge and isinstance(state.get(key), dict) and isinstance(value, dict):
#         state[key] = _deep_merge(state[key], value)
#     else:
#         state[key] = value
#     delta[key] = copy.deepcopy(state[key])

#     # 3. DERIVED WORKFLOW LOGIC
    
#     # Blueprint Gate
#     if key == KEY_BLUEPRINT_RESULTS:
#         has_results = isinstance(value, list) and len(value) > 0
#         state[KEY_BLUEPRINT_SEARCH_DONE] = has_results
#         state[KEY_BLUEPRINT_NO_MATCH] = not has_results
#         delta[KEY_BLUEPRINT_SEARCH_DONE] = has_results

#     # Research Gate
#     elif key in (KEY_TECHNICAL_RESEARCH_SUMMARY, "research_output"):
#         state[KEY_RESEARCH_RESOLVED] = value is not None
#         delta[KEY_RESEARCH_RESOLVED] = state[KEY_RESEARCH_RESOLVED]

#     # Architect Gate & Loop Validation
#     elif key in (KEY_HLD_REPORT_JSON, "architecture_output"):
#         try:
#             if isinstance(value, str): json.loads(value)
#             state[KEY_ARCH_COMPLETE] = True
#             state[KEY_ARCH_VALID] = True # Reset validation to True on new design
#         except:
#             state[KEY_ARCH_COMPLETE] = False
#         delta[KEY_ARCH_COMPLETE] = state[KEY_ARCH_COMPLETE]

#     # ROOT VALIDATION: Rejection Logic
#     elif key == KEY_ARCH_VALID:
#         is_valid = _as_bool(value)
#         state[KEY_ARCH_VALID] = is_valid
#         if not is_valid:
#             state[KEY_ARCH_COMPLETE] = False # Force loop back
#             state[KEY_VALIDATION_ERROR] = kwargs.get("reason", "Rejected by validator.")
#             delta[KEY_VALIDATION_ERROR] = state[KEY_VALIDATION_ERROR]
#         delta[KEY_ARCH_VALID] = is_valid
#         delta[KEY_ARCH_COMPLETE] = state[KEY_ARCH_COMPLETE]

#     # 4. RECOMPUTE INTAKE STATUS
#     intake_data = state.get(KEY_INTAKE, {})
#     confirmed_data = state.get(KEY_INTAKE_CONFIRMED, {})
#     missing = [f for f in _REQUIRED if f not in intake_data or not confirmed_data.get(f)]
    
#     state[KEY_INTAKE_MISSING_FIELDS] = missing
    
#     try:
#         if not missing:
#             IntakeSchema.model_validate(intake_data)
#             state[KEY_INTAKE_COMPLETE] = True
#             state[KEY_INTAKE_VALIDATION_ERROR] = None
#         else:
#             state[KEY_INTAKE_COMPLETE] = False
#     except ValidationError as e:
#         state[KEY_INTAKE_COMPLETE] = False
#         state[KEY_INTAKE_VALIDATION_ERROR] = str(e)

#     # Sync All Intake Metadata to Delta
#     for k in (KEY_INTAKE, KEY_INTAKE_CONFIRMED, KEY_INTAKE_MISSING_FIELDS, KEY_INTAKE_COMPLETE):
#         delta[k] = copy.deepcopy(state.get(k))

#     tool_context.session.state = state
#     _commit_delta(tool_context, delta)

#     return {"result": f"State updated for {key}.", "stateDelta": delta}

# store_in_state_tool = FunctionTool(func=store_in_state)

# from __future__ import annotations

# from typing import Any, Dict, Optional, Tuple, List
# import copy
# import json
# import re

# from pydantic import ValidationError

# from agent.logging_setup import get_logger
# from schema_types.aia_intake_schema import IntakeSchema
# from google.adk.tools import FunctionTool

# # Centralized Key Imports
# from agent.workflow.keys import (
#     KEY_INTAKE, KEY_INTAKE_CONFIRMED, KEY_INTAKE_COMPLETE, 
#     KEY_INTAKE_MISSING_FIELDS, KEY_INTAKE_VALIDATION_ERROR,
#     KEY_BLUEPRINT_RESULTS, KEY_BLUEPRINT_SEARCH_DONE, KEY_BLUEPRINT_NO_MATCH,
#     KEY_RESEARCH_RESOLVED, KEY_TECHNICAL_RESEARCH_SUMMARY,
#     KEY_ARCH_COMPLETE, KEY_HLD_REPORT_JSON, KEY_ARCH_VALID,
#     KEY_VALIDATION_ERROR, KEY_DOC_RENDERED, KEY_RENDER_ARTIFACT,
#     KEY_WORKFLOW_RESET_REQUESTED, KEY_INITIALIZED,
#     KEY_HLD_COMMIT_TRIGGERED,
#     KEY_SELECTED_SECTIONS,   # 💥 ADDED NEW KEY
#     KEY_USER_REQUEST,        # ✅ NEW: needed for revision-safe intercept
#     KEY_REVISION_REQUEST,    # ✅ NEW: dedicated revision request storage
#     KEY_REVISION_READY,      # ✅ NEW: derived workflow lifecycle flag
# )

# logger = get_logger("StateStore")

# # =============================================================================
# # Utilities
# # =============================================================================
# def _as_bool(v: Any) -> bool:
#     if isinstance(v, bool): return v
#     if isinstance(v, str): return v.strip().lower() in ("true", "1", "yes", "y")
#     return False

# def _to_snake(name: str) -> str:
#     if not isinstance(name, str): return str(name)
#     return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()

# def _is_placeholder(v: Any) -> bool:
#     if v is None: return True
#     if isinstance(v, str):
#         return v.strip().lower() in ("", "tbc", "unknown", "n/a", "pending")
#     return False

# def _deep_merge(dst: Any, src: Any) -> Any:
#     if isinstance(dst, dict) and isinstance(src, dict):
#         for k, v in src.items():
#             dst[k] = _deep_merge(dst[k], v) if k in dst else copy.deepcopy(v)
#         return dst
#     return copy.deepcopy(src)

# def _has_text(v: Any) -> bool:
#     return isinstance(v, str) and bool(v.strip())

# # =============================================================================
# # Persistence Helpers
# # =============================================================================
# def _commit_delta(tool_context, delta: Dict[str, Any]) -> None:
#     try:
#         actions = getattr(tool_context, "event_actions", None) or getattr(tool_context, "actions", None)
#         if callable(actions): actions = actions()
        
#         for attr in ("stateDelta", "state_delta"):
#             if hasattr(actions, attr):
#                 sd = getattr(actions, attr) or {}
#                 _deep_merge(sd, delta)
#                 setattr(actions, attr, sd)
#                 return
#     except Exception as e:
#         logger.warning(f"[STATE_STORE] Failed to commit delta: {e}")

# # =============================================================================
# # Schema & Intake Logic
# # =============================================================================
# _INTAKE_KEYMAP = { _to_snake(k): k for k in IntakeSchema.model_fields.keys() }
# _REQUIRED = [k for k, f in IntakeSchema.model_fields.items() if f.is_required()]

# def _canonical(key: str) -> str:
#     norm = _to_snake(key)
#     return _INTAKE_KEYMAP.get(norm, norm)

# def _ingest_to_intake(state: Dict[str, Any], key: str, value: Any, confirmed: bool) -> bool:
#     intake = state.setdefault(KEY_INTAKE, {})
#     conf = state.setdefault(KEY_INTAKE_CONFIRMED, {})
    
#     if isinstance(value, dict):
#         changed = False
#         for k, v in value.items():
#             changed = _ingest_to_intake(state, k, v, confirmed) or changed
#         return changed

#     field = _canonical(key)
#     if field not in IntakeSchema.model_fields: return False

#     if _is_placeholder(value):
#         if field in intake: del intake[field]
#         conf[field] = False
#         return True

#     if field in _REQUIRED and not confirmed:
#         conf[field] = False
#         return False

#     if intake.get(field) != value:
#         intake[field] = value
#         conf[field] = confirmed
#         return True
#     return False

# # =============================================================================
# # Main Tool: store_in_state
# # =============================================================================
# def store_in_state(
#     key: str,
#     value: Any,
#     merge: bool = True,
#     confirmed: bool = False,
#     tool_context=None,
#     **kwargs,
# ):
#     logger.info(f"[STATE_STORE] Writing key={key} | confirmed={confirmed}")
#     if tool_context is None: raise ValueError("tool_context required.")

#     state = tool_context.session.state or {}
#     delta = {}

#     # Protect Workflow Logic Keys from direct LLM manipulation
#     _PROTECTED = {
#         KEY_INTAKE_COMPLETE,
#         KEY_INTAKE_MISSING_FIELDS,
#         KEY_ARCH_COMPLETE,
#         KEY_DOC_RENDERED,
#         KEY_REVISION_READY,  # ✅ NEW: derived lifecycle flag only
#     }
#     if key in _PROTECTED:
#         return {"result": f"Write to {key} ignored; derived logic only.", "stateDelta": delta}

#     # ==========================================
#     # ✅ NEW: Dedicated revision request capture
#     # ==========================================
#     if key == KEY_REVISION_REQUEST and _has_text(value):
#         state[KEY_REVISION_REQUEST] = value
#         delta[KEY_REVISION_REQUEST] = copy.deepcopy(value)

#         # Trigger orchestrator rerun
#         state[KEY_WORKFLOW_RESET_REQUESTED] = True
#         delta[KEY_WORKFLOW_RESET_REQUESTED] = True

#         # No longer passively awaiting revision; revision is now active
#         state[KEY_REVISION_READY] = False
#         delta[KEY_REVISION_READY] = False

#         tool_context.session.state = state
#         _commit_delta(tool_context, delta)
#         return {
#             "result": "Revision request stored. Workflow reset requested.",
#             "stateDelta": delta
#         }

#     # ==========================================
#     # ✅ NEW: Safe post-generation intercept
#     # If a new KEY_USER_REQUEST comes in after a completed run,
#     # preserve the original baseline and route the new text as a revision delta.
#     # ==========================================
#     if (
#         key == KEY_USER_REQUEST
#         and _has_text(value)
#         and _as_bool(state.get(KEY_REVISION_READY))
#         and _as_bool(state.get(KEY_DOC_RENDERED))
#     ):
#         logger.info(
#             "[STATE_STORE] Post-generation KEY_USER_REQUEST detected while revision_ready=true. "
#             "Routing value into KEY_REVISION_REQUEST instead of overwriting baseline request."
#         )

#         state[KEY_REVISION_REQUEST] = value
#         delta[KEY_REVISION_REQUEST] = copy.deepcopy(value)

#         state[KEY_WORKFLOW_RESET_REQUESTED] = True
#         delta[KEY_WORKFLOW_RESET_REQUESTED] = True

#         state[KEY_REVISION_READY] = False
#         delta[KEY_REVISION_READY] = False

#         tool_context.session.state = state
#         _commit_delta(tool_context, delta)
#         return {
#             "result": "Post-generation follow-up captured as revision request. Workflow reset requested.",
#             "stateDelta": delta
#         }

#     # ==========================================
#     # FIXED: Handle Reset properly commits state
#     # ==========================================
#     if key == KEY_WORKFLOW_RESET_REQUESTED and _as_bool(value):
#         state[KEY_WORKFLOW_RESET_REQUESTED] = True
#         delta[KEY_WORKFLOW_RESET_REQUESTED] = True
        
#         state[KEY_ARCH_COMPLETE] = False
#         delta[KEY_ARCH_COMPLETE] = False
        
#         state[KEY_RESEARCH_RESOLVED] = False
#         delta[KEY_RESEARCH_RESOLVED] = False

#         # ✅ NEW: reset request means revision flow is now active, not idle-ready
#         state[KEY_REVISION_READY] = False
#         delta[KEY_REVISION_READY] = False
        
#         tool_context.session.state = state
#         _commit_delta(tool_context, delta)
#         return {"result": "Workflow reset complete. Routing to Orchestrator.", "stateDelta": delta}

#     # 💥 NEW: Safely intercept and format selected HLD sections
#     if key == KEY_SELECTED_SECTIONS:
#         if isinstance(value, str):
#             # Parse comma-separated string back into a clean list
#             parsed_list = [s.strip() for s in value.split(",") if s.strip()]
#             state[key] = parsed_list
#         else:
#             state[key] = value
            
#         delta[key] = copy.deepcopy(state[key])
#         tool_context.session.state = state
#         _commit_delta(tool_context, delta)
#         return {"result": f"Successfully stored {len(state[key])} requested sections.", "stateDelta": delta}


#     # 1. Intake Ingestion
#     intake_complete_before = _as_bool(state.get(KEY_INTAKE_COMPLETE))
#     is_intake_field = _canonical(key) in IntakeSchema.model_fields

#     if (not intake_complete_before) or (intake_complete_before and is_intake_field and confirmed):
#         _ingest_to_intake(state, key, value, confirmed)

#     # 2. Standard Storage
#     if merge and isinstance(state.get(key), dict) and isinstance(value, dict):
#         state[key] = _deep_merge(state[key], value)
#     else:
#         state[key] = value
#     delta[key] = copy.deepcopy(state[key])

#     # 3. DERIVED WORKFLOW LOGIC
    
#     # Blueprint Gate
#     if key == KEY_BLUEPRINT_RESULTS:
#         has_results = isinstance(value, list) and len(value) > 0
#         state[KEY_BLUEPRINT_SEARCH_DONE] = has_results
#         state[KEY_BLUEPRINT_NO_MATCH] = not has_results
#         delta[KEY_BLUEPRINT_SEARCH_DONE] = has_results

#     # Research Gate
#     elif key in (KEY_TECHNICAL_RESEARCH_SUMMARY, "research_output"):
#         state[KEY_RESEARCH_RESOLVED] = value is not None
#         delta[KEY_RESEARCH_RESOLVED] = state[KEY_RESEARCH_RESOLVED]

#     # Architect Gate & Loop Validation
#     elif key in (KEY_HLD_REPORT_JSON, "architecture_output"):
#         try:
#             if isinstance(value, str): json.loads(value)
#             state[KEY_ARCH_COMPLETE] = True
#             state[KEY_ARCH_VALID] = True # Reset validation to True on new design
#         except:
#             state[KEY_ARCH_COMPLETE] = False
#         delta[KEY_ARCH_COMPLETE] = state[KEY_ARCH_COMPLETE]

#     # ROOT VALIDATION: Rejection Logic
#     elif key == KEY_ARCH_VALID:
#         is_valid = _as_bool(value)
#         state[KEY_ARCH_VALID] = is_valid
#         if not is_valid:
#             state[KEY_ARCH_COMPLETE] = False # Force loop back
#             state[KEY_VALIDATION_ERROR] = kwargs.get("reason", "Rejected by validator.")
#             delta[KEY_VALIDATION_ERROR] = state[KEY_VALIDATION_ERROR]
#         delta[KEY_ARCH_VALID] = is_valid
#         delta[KEY_ARCH_COMPLETE] = state[KEY_ARCH_COMPLETE]

#     # 4. RECOMPUTE INTAKE STATUS
#     intake_data = state.get(KEY_INTAKE, {})
#     confirmed_data = state.get(KEY_INTAKE_CONFIRMED, {})
#     missing = [f for f in _REQUIRED if f not in intake_data or not confirmed_data.get(f)]
    
#     state[KEY_INTAKE_MISSING_FIELDS] = missing
    
#     try:
#         if not missing:
#             IntakeSchema.model_validate(intake_data)
#             state[KEY_INTAKE_COMPLETE] = True
#             state[KEY_INTAKE_VALIDATION_ERROR] = None
#         else:
#             state[KEY_INTAKE_COMPLETE] = False
#     except ValidationError as e:
#         state[KEY_INTAKE_COMPLETE] = False
#         state[KEY_INTAKE_VALIDATION_ERROR] = str(e)

#     # Sync All Intake Metadata to Delta
#     for k in (KEY_INTAKE, KEY_INTAKE_CONFIRMED, KEY_INTAKE_MISSING_FIELDS, KEY_INTAKE_COMPLETE):
#         delta[k] = copy.deepcopy(state.get(k))

#     tool_context.session.state = state
#     _commit_delta(tool_context, delta)

#     return {"result": f"State updated for {key}.", "stateDelta": delta}

# store_in_state_tool = FunctionTool(func=store_in_state)



from __future__ import annotations

from typing import Any, Dict
import copy
import json
import re

from pydantic import ValidationError

from agent.logging_setup import get_logger
from schema_types.aia_intake_schema import IntakeSchema
from google.adk.tools import FunctionTool

# Centralized Key Imports
from agent.workflow.keys import (
    KEY_INTAKE,
    KEY_INTAKE_CONFIRMED,
    KEY_INTAKE_COMPLETE,
    KEY_INTAKE_MISSING_FIELDS,
    KEY_INTAKE_VALIDATION_ERROR,
    KEY_BLUEPRINT_RESULTS,
    KEY_BLUEPRINT_SEARCH_DONE,
    KEY_BLUEPRINT_NO_MATCH,
    KEY_RESEARCH_RESOLVED,
    KEY_TECHNICAL_RESEARCH_SUMMARY,
    KEY_ARCH_COMPLETE,
    KEY_HLD_REPORT_JSON,
    KEY_ARCH_VALID,
    KEY_VALIDATION_ERROR,
    KEY_DOC_RENDERED,
    KEY_RENDER_ARTIFACT,
    KEY_WORKFLOW_RESET_REQUESTED,
    KEY_INITIALIZED,
    KEY_HLD_COMMIT_TRIGGERED,
    KEY_SELECTED_SECTIONS,
    KEY_USER_REQUEST,
    KEY_ORIGINAL_USER_REQUEST,
    KEY_REVISION_REQUESTED,
    KEY_REVISION_NOTES,
    KEY_REVISION_READY,
)

logger = get_logger("StateStore")


# =============================================================================
# Utilities
# =============================================================================
def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v

    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y")

    return False


def _to_snake(name: str) -> str:
    if not isinstance(name, str):
        return str(name)

    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _is_placeholder(v: Any) -> bool:
    if v is None:
        return True

    if isinstance(v, str):
        return v.strip().lower() in ("", "tbc", "unknown", "n/a", "pending")

    return False


def _deep_merge(dst: Any, src: Any) -> Any:
    if isinstance(dst, dict) and isinstance(src, dict):
        for k, v in src.items():
            dst[k] = _deep_merge(dst[k], v) if k in dst else copy.deepcopy(v)
        return dst

    return copy.deepcopy(src)


def _has_text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _preserve_original_request_if_needed(state: Dict[str, Any]) -> None:
    """
    Preserve the current effective request as the baseline/original request
    before routing a post-generation follow-up into revision flow.

    This prevents a short follow-up like:
      "change DB to Cloud SQL"

    from overwriting the full existing architecture request/context.
    """
    existing_original = state.get(KEY_ORIGINAL_USER_REQUEST)
    current_request = state.get(KEY_USER_REQUEST)

    if _has_text(existing_original):
        return

    if _has_text(current_request):
        state[KEY_ORIGINAL_USER_REQUEST] = current_request


# =============================================================================
# Persistence Helpers
# =============================================================================
def _commit_delta(tool_context, delta: Dict[str, Any]) -> None:
    try:
        actions = getattr(tool_context, "event_actions", None) or getattr(tool_context, "actions", None)

        if callable(actions):
            actions = actions()

        for attr in ("stateDelta", "state_delta"):
            if hasattr(actions, attr):
                sd = getattr(actions, attr) or {}
                _deep_merge(sd, delta)
                setattr(actions, attr, sd)
                return

    except Exception as e:
        logger.warning(f"[STATE_STORE] Failed to commit delta: {e}")


# =============================================================================
# Schema & Intake Logic
# =============================================================================
_INTAKE_KEYMAP = {_to_snake(k): k for k in IntakeSchema.model_fields.keys()}
_REQUIRED = [k for k, f in IntakeSchema.model_fields.items() if f.is_required()]


def _canonical(key: str) -> str:
    norm = _to_snake(key)
    return _INTAKE_KEYMAP.get(norm, norm)


def _ingest_to_intake(state: Dict[str, Any], key: str, value: Any, confirmed: bool) -> bool:
    intake = state.setdefault(KEY_INTAKE, {})
    conf = state.setdefault(KEY_INTAKE_CONFIRMED, {})

    if isinstance(value, dict):
        changed = False
        for k, v in value.items():
            changed = _ingest_to_intake(state, k, v, confirmed) or changed
        return changed

    field = _canonical(key)

    if field not in IntakeSchema.model_fields:
        return False

    if _is_placeholder(value):
        if field in intake:
            del intake[field]

        conf[field] = False
        return True

    if field in _REQUIRED and not confirmed:
        conf[field] = False
        return False

    if intake.get(field) != value:
        intake[field] = value
        conf[field] = confirmed
        return True

    return False


# =============================================================================
# Main Tool: store_in_state
# =============================================================================
def store_in_state(
    key: str,
    value: Any,
    merge: bool = True,
    confirmed: bool = False,
    tool_context=None,
    **kwargs,
):
    logger.info(f"[STATE_STORE] Writing key={key} | confirmed={confirmed}")

    if tool_context is None:
        raise ValueError("tool_context required.")

    state = tool_context.session.state or {}
    delta: Dict[str, Any] = {}

    # -------------------------------------------------------------------------
    # Protect Workflow Logic Keys from direct LLM manipulation
    # -------------------------------------------------------------------------
    _PROTECTED = {
        KEY_INTAKE_COMPLETE,
        KEY_INTAKE_MISSING_FIELDS,
        KEY_ARCH_COMPLETE,
        KEY_DOC_RENDERED,
        KEY_REVISION_READY,  # derived lifecycle flag only
    }

    if key in _PROTECTED:
        return {
            "result": f"Write to {key} ignored; derived logic only.",
            "stateDelta": delta,
        }

    # ==========================================
    # Dedicated revision notes capture
    # ==========================================
    if key == KEY_REVISION_NOTES and _has_text(value):
        _preserve_original_request_if_needed(state)

        if KEY_ORIGINAL_USER_REQUEST in state:
            delta[KEY_ORIGINAL_USER_REQUEST] = copy.deepcopy(state[KEY_ORIGINAL_USER_REQUEST])

        state[KEY_REVISION_NOTES] = value
        delta[KEY_REVISION_NOTES] = copy.deepcopy(value)

        state[KEY_REVISION_REQUESTED] = True
        delta[KEY_REVISION_REQUESTED] = True

        # Trigger orchestrator rerun
        state[KEY_WORKFLOW_RESET_REQUESTED] = True
        delta[KEY_WORKFLOW_RESET_REQUESTED] = True

        # No longer passively awaiting revision; revision is now active
        state[KEY_REVISION_READY] = False
        delta[KEY_REVISION_READY] = False

        tool_context.session.state = state
        _commit_delta(tool_context, delta)

        return {
            "result": "Revision notes stored. Workflow reset requested.",
            "stateDelta": delta,
        }

    # ==========================================
    # Safe post-generation intercept
    # If a new KEY_USER_REQUEST comes in after a completed run,
    # preserve the original baseline and route the new text as revision notes.
    # ==========================================
    if (
        key == KEY_USER_REQUEST
        and _has_text(value)
        and _as_bool(state.get(KEY_REVISION_READY))
        and _as_bool(state.get(KEY_DOC_RENDERED))
    ):
        logger.info(
            "[STATE_STORE] Post-generation KEY_USER_REQUEST detected while revision_ready=true. "
            "Routing value into KEY_REVISION_NOTES instead of overwriting baseline request."
        )

        _preserve_original_request_if_needed(state)

        if KEY_ORIGINAL_USER_REQUEST in state:
            delta[KEY_ORIGINAL_USER_REQUEST] = copy.deepcopy(state[KEY_ORIGINAL_USER_REQUEST])

        state[KEY_REVISION_NOTES] = value
        delta[KEY_REVISION_NOTES] = copy.deepcopy(value)

        state[KEY_REVISION_REQUESTED] = True
        delta[KEY_REVISION_REQUESTED] = True

        state[KEY_WORKFLOW_RESET_REQUESTED] = True
        delta[KEY_WORKFLOW_RESET_REQUESTED] = True

        state[KEY_REVISION_READY] = False
        delta[KEY_REVISION_READY] = False

        tool_context.session.state = state
        _commit_delta(tool_context, delta)

        return {
            "result": "Post-generation follow-up captured as revision notes. Workflow reset requested.",
            "stateDelta": delta,
        }

    # ==========================================
    # Handle Workflow Reset Request
    # ==========================================
    if key == KEY_WORKFLOW_RESET_REQUESTED and _as_bool(value):
        _preserve_original_request_if_needed(state)

        if KEY_ORIGINAL_USER_REQUEST in state:
            delta[KEY_ORIGINAL_USER_REQUEST] = copy.deepcopy(state[KEY_ORIGINAL_USER_REQUEST])

        state[KEY_WORKFLOW_RESET_REQUESTED] = True
        delta[KEY_WORKFLOW_RESET_REQUESTED] = True

        # If caller passed revision text as kwargs/value companion, store it safely.
        revision_notes = kwargs.get(KEY_REVISION_NOTES) or kwargs.get("revision_notes")

        if _has_text(revision_notes):
            state[KEY_REVISION_NOTES] = revision_notes
            delta[KEY_REVISION_NOTES] = copy.deepcopy(revision_notes)

            state[KEY_REVISION_REQUESTED] = True
            delta[KEY_REVISION_REQUESTED] = True

        state[KEY_ARCH_COMPLETE] = False
        delta[KEY_ARCH_COMPLETE] = False

        state[KEY_RESEARCH_RESOLVED] = False
        delta[KEY_RESEARCH_RESOLVED] = False

        # Reset request means revision flow is now active, not idle-ready
        state[KEY_REVISION_READY] = False
        delta[KEY_REVISION_READY] = False

        tool_context.session.state = state
        _commit_delta(tool_context, delta)

        return {
            "result": "Workflow reset requested. Routing to Orchestrator.",
            "stateDelta": delta,
        }

    # ==========================================
    # Safely intercept and format selected HLD sections
    # ==========================================
    if key == KEY_SELECTED_SECTIONS:
        if isinstance(value, str):
            parsed_list = [s.strip() for s in value.split(",") if s.strip()]
            state[key] = parsed_list
        else:
            state[key] = value

        delta[key] = copy.deepcopy(state[key])

        tool_context.session.state = state
        _commit_delta(tool_context, delta)

        return {
            "result": f"Successfully stored {len(state[key])} requested sections.",
            "stateDelta": delta,
        }

    # =========================================================================
    # 1. Intake Ingestion
    # =========================================================================
    intake_complete_before = _as_bool(state.get(KEY_INTAKE_COMPLETE))
    is_intake_field = _canonical(key) in IntakeSchema.model_fields

    if (not intake_complete_before) or (intake_complete_before and is_intake_field and confirmed):
        _ingest_to_intake(state, key, value, confirmed)

    # =========================================================================
    # 2. Standard Storage
    # =========================================================================
    if merge and isinstance(state.get(key), dict) and isinstance(value, dict):
        state[key] = _deep_merge(state[key], value)
    else:
        state[key] = value

    delta[key] = copy.deepcopy(state[key])

    # =========================================================================
    # 3. Derived Workflow Logic
    # =========================================================================

    # Blueprint Gate
    if key == KEY_BLUEPRINT_RESULTS:
        has_results = isinstance(value, list) and len(value) > 0

        state[KEY_BLUEPRINT_SEARCH_DONE] = has_results
        state[KEY_BLUEPRINT_NO_MATCH] = not has_results

        delta[KEY_BLUEPRINT_SEARCH_DONE] = has_results
        delta[KEY_BLUEPRINT_NO_MATCH] = not has_results

    # Research Gate
    elif key in (KEY_TECHNICAL_RESEARCH_SUMMARY, "research_output"):
        state[KEY_RESEARCH_RESOLVED] = value is not None
        delta[KEY_RESEARCH_RESOLVED] = state[KEY_RESEARCH_RESOLVED]

    # Architect Gate & Loop Validation
    elif key in (KEY_HLD_REPORT_JSON, "architecture_output"):
        try:
            if isinstance(value, str):
                json.loads(value)

            state[KEY_ARCH_COMPLETE] = True
            state[KEY_ARCH_VALID] = True  # Reset validation to True on new design

        except Exception:
            state[KEY_ARCH_COMPLETE] = False

        delta[KEY_ARCH_COMPLETE] = state[KEY_ARCH_COMPLETE]
        delta[KEY_ARCH_VALID] = state.get(KEY_ARCH_VALID)

    # ROOT VALIDATION: Rejection Logic
    elif key == KEY_ARCH_VALID:
        is_valid = _as_bool(value)

        state[KEY_ARCH_VALID] = is_valid

        if not is_valid:
            state[KEY_ARCH_COMPLETE] = False  # Force loop back
            state[KEY_VALIDATION_ERROR] = kwargs.get("reason", "Rejected by validator.")
            delta[KEY_VALIDATION_ERROR] = state[KEY_VALIDATION_ERROR]

        delta[KEY_ARCH_VALID] = is_valid
        delta[KEY_ARCH_COMPLETE] = state[KEY_ARCH_COMPLETE]

    # =========================================================================
    # 4. Recompute Intake Status
    # =========================================================================
    intake_data = state.get(KEY_INTAKE, {})
    confirmed_data = state.get(KEY_INTAKE_CONFIRMED, {})

    missing = [
        f for f in _REQUIRED
        if f not in intake_data or not confirmed_data.get(f)
    ]

    state[KEY_INTAKE_MISSING_FIELDS] = missing

    try:
        if not missing:
            IntakeSchema.model_validate(intake_data)
            state[KEY_INTAKE_COMPLETE] = True
            state[KEY_INTAKE_VALIDATION_ERROR] = None
        else:
            state[KEY_INTAKE_COMPLETE] = False

    except ValidationError as e:
        state[KEY_INTAKE_COMPLETE] = False
        state[KEY_INTAKE_VALIDATION_ERROR] = str(e)

    # Sync All Intake Metadata to Delta
    for k in (
        KEY_INTAKE,
        KEY_INTAKE_CONFIRMED,
        KEY_INTAKE_MISSING_FIELDS,
        KEY_INTAKE_COMPLETE,
        KEY_INTAKE_VALIDATION_ERROR,
    ):
        delta[k] = copy.deepcopy(state.get(k))

    tool_context.session.state = state
    _commit_delta(tool_context, delta)

    return {
        "result": f"State updated for {key}.",
        "stateDelta": delta,
    }


store_in_state_tool = FunctionTool(func=store_in_state)