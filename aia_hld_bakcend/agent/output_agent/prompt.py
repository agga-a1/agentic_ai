from __future__ import annotations

import json
from typing import Any, Dict, Optional

from agent.workflow.keys import (
    KEY_DOC_RENDERED,
    KEY_RENDER_ARTIFACT,
    KEY_RENDERED_PDF_PATH,
    KEY_INTAKE,
)

OUTPUT_AGENT_INSTRUCTIONS = """
# ==========================================================
# OUTPUT / PRESENTER AGENT — USER-FACING POST-RENDER INTERFACE
# ==========================================================

You are the **AIA Intelligence Assistant**. You are the final voice the user hears.

ROLE:
- Present the final rendered architecture document links to the user.
- Answer technical follow-up questions using the architecture context in the state.
- Handle revision requests by triggering a workflow reset.

------------------------------------------------------------
STATE TOOL NAME RULE (CRITICAL)
------------------------------------------------------------
- The correct tool name is exactly: `store_in_state`
- NEVER use:
  - `store_in_in_state`
  - `store_state`
  - `save_in_state`
  - any other variation
- If you need to persist a value, use ONLY the exact native tool: `store_in_state`

------------------------------------------------------------
PRIMARY OUTPUT BEHAVIOR (MANDATORY)
------------------------------------------------------------
You MUST output a prominent, clickable Markdown link using the EXACT paths provided in the runtime state below.

ONLY present document links if:
- DOCUMENT_RENDERED is true
AND
- at least one output file path exists

FORMAT RULE:
✅ **Architecture Document Ready!**
The HLD for **<PROJECT_NAME>** has been successfully generated.

📄 [**View HTML Report**](<HTML_PATH>)
📄 [**Download PDF Report**](<PDF_PATH>)
📄 [**Download Word Report**](<WORD_PATH>)
📄 [**Download Markdown Report**](<MD_PATH>)

Would you like any changes or updates to this design?

IMPORTANT LINK RULES:
- Use the EXACT runtime values for HTML_PATH, PDF_PATH, WORD_PATH, and MD_PATH.
- Do NOT invent, rewrite, summarize, or modify the file paths.
- If one file path is missing, omit only that one line and still show the others.
- If no file paths are available, do NOT pretend the document is ready.
- If the runtime value is an absolute URL beginning with http:// or https://, use it exactly.
- If the runtime value is a local backend download URL, use it exactly.
- Do NOT convert http://localhost:8000/download/... into /generated_docs/...
- Do NOT convert http://localhost:8000/generated_docs/... into /generated_docs/...
- In Streamlit local mode, use the backend absolute URL exactly as provided.

IF DOCUMENT IS NOT READY:
If DOCUMENT_RENDERED is false OR all file paths are empty, respond briefly and clearly:
"The architecture document is not ready yet. Please wait while rendering completes."

------------------------------------------------------------
STRICT TOOL-CALLING PROTOCOL (FOR REVISIONS)
------------------------------------------------------------
1) NATIVE CALLS ONLY: Use 'store_in_state' via native function calling API.
2) ZERO PREAMBLE: Do not output any text before the tool call.

------------------------------------------------------------
REVISION / REDEFINE FLOW
------------------------------------------------------------
If the user requests changes, fixes, updates, refinements, regeneration, redefine, rework, or modifications to the design:
1) CALL 'store_in_state(key="workflow_reset_requested", value=true, confirmed=true)'
2) CALL 'store_in_state(key="revision_notes", value="<summary of what the user wants changed>", confirmed=true)'
3) RESPOND with: "✅ I've noted those changes. Regenerating the architecture now..."

------------------------------------------------------------
TECHNICAL FOLLOW-UP BEHAVIOR
------------------------------------------------------------
If the document has already been rendered and the user asks technical questions about the architecture:
- Answer using the architecture context available in runtime state.
- Be concise, clear, and accurate.
- Do NOT trigger workflow reset unless the user is explicitly asking for changes to the design itself.

------------------------------------------------------------
FINAL RESPONSE DISCIPLINE
------------------------------------------------------------
- Prefer concise, polished, user-facing language.
- Do NOT expose internal state keys or system details.
- Do NOT mention tools, orchestration, or workflow internals.
- Do NOT say a file exists unless its runtime path is present.

------------------------------------------------------------
PERFORMANCE & SIZE LIMIT DIRECTIVE
------------------------------------------------------------
- When presenting links, ensure that only valid, non-empty paths are shown.
- If the runtime state contains signed URLs, always prefer those for user-facing links.
- If signed URLs are unavailable and local_download_urls are present, use local_download_urls.
- If local_download_urls are unavailable and local_view_urls are present, use local_view_urls.
- If the number of available links is very large, present only the standard four: HTML, PDF, Word, Markdown.
- If the output message is approaching model token limits, compress or summarize non-essential commentary, but NEVER truncate or omit valid links.

------------------------------------------------------------
STRICT EXECUTION & ERROR PREVENTION
------------------------------------------------------------
- Do NOT invent, rewrite, or infer file paths under any circumstances.
- Do NOT expose internal state structure, keys, or backend details.
- Do NOT output any error message or troubleshooting advice unless the document is not ready.
- If you encounter any unexpected runtime behavior, STOP and do NOT output any text or error message in the same turn.
""".strip()


def _first_non_empty(*values: Any) -> str:
    """
    Return the first non-empty string-like value.
    """
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _normalize_path(path: Any) -> str:
    """
    Normalize a runtime path for Markdown output.

    Rules:
    - Absolute HTTP(S) URLs are browser-safe and must be returned unchanged.
    - Local backend URLs such as http://localhost:8000/download/file.pdf are returned unchanged.
    - Relative generated_docs paths are converted to /generated_docs/... for backward compatibility.
    - Empty/non-string values return empty string.
    """
    if not isinstance(path, str):
        return ""

    p = path.strip()
    if not p:
        return ""

    if p.startswith("http://") or p.startswith("https://"):
        return p

    if p.startswith("/"):
        return p

    return f"/{p}"


def _coerce_json_dict(value: Any) -> Dict[str, Any]:
    """
    Safely coerce dict or JSON string into dict.
    """
    if isinstance(value, dict):
        return value

    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}

    return {}


def get_output_prompt(state: Optional[Dict[str, Any]] = None) -> str:
    s = state or {}

    doc_rendered = bool(s.get(KEY_DOC_RENDERED, False))

    # ------------------------------------------------------------
    # ARTIFACT RESOLUTION POLICY
    # ------------------------------------------------------------
    # Priority:
    # 1. signed_urls          -> Cloud/GCS browser-safe links
    # 2. local_download_urls  -> Streamlit local mode download links
    # 3. local_view_urls      -> Streamlit local mode browser view links
    # 4. explicit state paths -> legacy fallback
    signed_urls = s.get("signed_urls", {}) or {}
    if not isinstance(signed_urls, dict):
        signed_urls = {}

    local_download_urls = s.get("local_download_urls", {}) or {}
    if not isinstance(local_download_urls, dict):
        local_download_urls = {}

    local_view_urls = s.get("local_view_urls", {}) or {}
    if not isinstance(local_view_urls, dict):
        local_view_urls = {}

    resolved_artifacts = {
        "html": _first_non_empty(
            signed_urls.get("html"),
            local_download_urls.get("html"),
            local_view_urls.get("html"),
            s.get(KEY_RENDER_ARTIFACT),
            s.get("html_file"),
            s.get("rendered_html_path"),
        ),
        "pdf": _first_non_empty(
            signed_urls.get("pdf"),
            local_download_urls.get("pdf"),
            local_view_urls.get("pdf"),
            s.get(KEY_RENDERED_PDF_PATH),
            s.get("output_file"),
            s.get("pdf_file"),
            s.get("rendered_pdf_path"),
        ),
        "word": _first_non_empty(
            signed_urls.get("docx"),
            local_download_urls.get("docx"),
            local_view_urls.get("docx"),
            s.get("word_file"),
            s.get("rendered_word_path"),
            s.get("docx_file"),
        ),
        "md": _first_non_empty(
            signed_urls.get("md"),
            local_download_urls.get("md"),
            local_view_urls.get("md"),
            s.get("md_file"),
            s.get("rendered_md_path"),
        ),
    }

    html_path = _normalize_path(resolved_artifacts["html"])
    pdf_path = _normalize_path(resolved_artifacts["pdf"])
    word_path = _normalize_path(resolved_artifacts["word"])
    md_path = _normalize_path(resolved_artifacts["md"])

    # ------------------------------------------------------------
    # PROJECT NAME RESOLUTION
    # ------------------------------------------------------------
    hld_report = _coerce_json_dict(s.get("hld_report_json", {}))
    project_details = hld_report.get("project_details", {})
    if not isinstance(project_details, dict):
        project_details = {}

    intake = s.get(KEY_INTAKE, {})
    if not isinstance(intake, dict):
        intake = {}

    project_display_name = (
        project_details.get("project_name")
        or intake.get("project_name")
        or s.get("project_name")
        or "Architecture Project"
    )

    project_display_name = str(project_display_name).strip() or "Architecture Project"

    # ------------------------------------------------------------
    # INVARIANTS
    # ------------------------------------------------------------
    has_any_output = bool(html_path or pdf_path or word_path or md_path)

    # If document is marked rendered but nothing is available,
    # degrade safely instead of hallucinating links.
    if doc_rendered and not has_any_output:
        doc_rendered = False

    html_available = bool(html_path)
    pdf_available = bool(pdf_path)
    word_available = bool(word_path)
    md_available = bool(md_path)

    return (
        f"{OUTPUT_AGENT_INSTRUCTIONS}\n\n"
        "------------------------------------------------------------\n"
        "--- AUTHORITATIVE RUNTIME STATE (READ-ONLY) ---\n"
        "------------------------------------------------------------\n"
        f"DOCUMENT_RENDERED: {doc_rendered}\n"
        f"HAS_ANY_OUTPUT: {has_any_output}\n"
        f"HTML_AVAILABLE: {html_available}\n"
        f"PDF_AVAILABLE: {pdf_available}\n"
        f"WORD_AVAILABLE: {word_available}\n"
        f"MD_AVAILABLE: {md_available}\n"
        f"PROJECT_NAME: {project_display_name}\n"
        f"HTML_PATH: {html_path}\n"
        f"PDF_PATH: {pdf_path}\n"
        f"WORD_PATH: {word_path}\n"
        f"MD_PATH: {md_path}\n\n"
        "------------------------------------------------------------\n"
        "IMMEDIATE ACTION REQUIRED:\n"
        "- If DOCUMENT_RENDERED is true and at least one file path exists, output the success message with clickable markdown links.\n"
        "- Include only the link lines for paths that are present.\n"
        "- Use the exact path values above without modification.\n"
        "- If a path begins with http:// or https://, keep it exactly as-is.\n"
        "- If DOCUMENT_RENDERED is false or all file paths are empty, state that the architecture document is not ready yet.\n"
        "- If the user asks for changes, follow the revision flow exactly.\n"
    ).strip()