import os
import json
import logging
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
from google.adk.agents import LlmAgent

from tools.doc_render_tools import render_hld_tool
from .prompt import get_document_render_prompt

# Synchronize with centralized keys
from agent.workflow.keys import (
    KEY_HLD_REPORT_JSON,
    KEY_DOC_RENDERED,
    KEY_RENDER_ARTIFACT,
    KEY_RENDERED_PDF_PATH,
    KEY_DOC_RENDER_ERROR,
    KEY_DOC_RENDER_WARNING
)

load_dotenv()
logger = logging.getLogger("DocRenderingAgent")

MODEL_NAME = os.getenv("GOOGLE_GENAI_MODEL")

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _safe_json(obj: Any) -> str:
    if obj is None:
        return "{}"
    if isinstance(obj, str):
        s = obj.strip()
        return s if s else "{}"
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj) if obj else "{}"

def _extract_render_outputs_from_history(context) -> Tuple[Optional[str], Optional[str]]:
    """
    Scans the session history backwards to find the actual tool execution result.
    This fixes the bug where the final model text message hides the tool result.
    """
    history = getattr(context.session, "history", [])
    
    # Iterate backwards through history to find the latest tool response
    for msg in reversed(history):
        parts = getattr(msg, "parts", [])
        for part in parts:
            # ADK uses different key shapes depending on the specific backend wrapper
            fn_res = getattr(part, "function_response", None) or getattr(part, "functionResponse", None)
            
            # Handle dict-based history items (common in raw JSON dumps)
            if isinstance(part, dict):
                fn_res = part.get("functionResponse") or part.get("function_response")

            if fn_res:
                # Find the render tool response (checking both object and dict access)
                name = getattr(fn_res, "name", "") if not isinstance(fn_res, dict) else fn_res.get("name", "")
                
                if "render_hld" in name:
                    res = getattr(fn_res, "response", {}) if not isinstance(fn_res, dict) else fn_res.get("response", {})
                    
                    # Depending on ADK version, 'status' might be nested inside 'result'
                    actual_res = res.get("result", res) if isinstance(res, dict) and isinstance(res.get("result"), dict) else res
                    
                    if isinstance(actual_res, dict) and actual_res.get("status") == "success":
                        return actual_res.get("html_path"), actual_res.get("output_file")
    
    return None, None

# ---------------------------------------------------------------------
# Instruction provider (workflow mode)
# ---------------------------------------------------------------------
def _instruction_provider(ctx) -> str:
    """
    Workflow mode: Pulls HLD JSON from the centralized state key.
    """
    session = getattr(ctx, "session", None)
    state = getattr(session, "state", {}) if session else {}
    if state is None:
        state = {}

    hld = state.get(KEY_HLD_REPORT_JSON, {})
    hld_json = _safe_json(hld)
    return get_document_render_prompt(hld_json)

# ---------------------------------------------------------------------
# Agent Class
# ---------------------------------------------------------------------
class DocRenderingSubAgent(LlmAgent):
    async def on_turn_complete(self, context):
        """
        Terminal Logic for Rendering:
        - Updates state with file paths using centralized keys.
        - Signals completion so GatedSequentialAgent moves to OutputAgent.
        """
        state = context.session.state or {}
        
        # Use the robust history scanner instead of relying on last_model_message
        html_path, pdf_path = _extract_render_outputs_from_history(context)

        if html_path:
            # Mark as rendered successfully
            state[KEY_DOC_RENDERED] = True
            state[KEY_RENDER_ARTIFACT] = html_path
            
            if pdf_path:
                state[KEY_RENDERED_PDF_PATH] = pdf_path
                
            state[KEY_DOC_RENDER_ERROR] = None
            context.session.state = state
            
            logger.info(f"[DOC] Render success. Artifact: {html_path}")
            return "proceed"

        # Failure path
        state[KEY_DOC_RENDERED] = False
        state[KEY_DOC_RENDER_ERROR] = "Tool execution failed or returned no result in history."
        context.session.state = state
        
        logger.warning("[DOC] Render failed. Could not find html_path in tool response history.")
        return None

doc_rendering_agent = DocRenderingSubAgent(
    name="DocRenderingSubAgent",
    model=MODEL_NAME,
    instruction=_instruction_provider,
    description="Renders the validated HLD JSON into HTML and PDF formats.",
    tools=[render_hld_tool],
)