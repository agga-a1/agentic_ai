# import base64, json, logging, re
# from pathlib import Path
# from typing import Any, Dict
# from config_load import GetConf
# from schema_types.hld_schema import HLDReport
# from agent.workflow.keys import KEY_HLD_REPORT_JSON, KEY_SELECTED_SECTIONS, KEY_RENDER_SELECTED_SECTIONS
# from tools.hld_section_commit_tools import assemble_hld_from_state, validate_required_hld_sections
# from .config import BRANDING_DIR
# from .docx_renderer import build_docx
# from .markdown_renderer import build_markdown_master
# from .pdf_renderer import build_pdf
# from .response_builder import build_error_response, build_success_response
# from .schema_utils import dynamic_inflate, extract_metadata_sections, normalize_hld, normalize_selected_sections
# from .storage import generate_signed_urls, upload_outputs

# logger=logging.getLogger(__name__)

# config=GetConf.load_configs()

# extract_metadata_sections(HLDReport)

# def _state_from_tool_context(tool_context) -> Dict[str,Any]:
#     if not tool_context: return {}
#     if hasattr(tool_context,'session') and getattr(tool_context,'session',None): return tool_context.session.state or {}
#     if hasattr(tool_context,'state'): return tool_context.state or {}
#     return {}

# def _resolve_report_payload(report: Dict[str,Any], state: Dict[str,Any]) -> Dict[str,Any]:
#     state_hld=state.get(KEY_HLD_REPORT_JSON) if state else None
#     if state_hld:
#         if isinstance(state_hld,str):
#             try: return json.loads(state_hld)
#             except Exception: logger.warning('session.state[%r] exists but is not valid JSON', KEY_HLD_REPORT_JSON)
#         elif isinstance(state_hld,dict): return state_hld
#     try:
#         section_report=validate_required_hld_sections(state)
#         if section_report.get('all_present'): logger.info('Render tool assembled HLD from section-wise state fallback.'); return assemble_hld_from_state(state)
#     except Exception: logger.exception('Failed to assemble HLD from section-wise state fallback.')
#     return report

# def _logo_data_uri() -> str:
#     p=BRANDING_DIR/'doc_logo.png'
#     try: return 'data:image/png;base64,'+base64.b64encode(p.read_bytes()).decode() if p.exists() else ''
#     except Exception: logger.exception('Failed loading logo'); return ''
    
# def _safe_project_name(data: Dict[str,Any]) -> tuple[str,str]:
#     project_name=(data.get('project_details') or {}).get('project_name') or 'hld'; safe_name=re.sub(r'[^a-zA-Z0-9_-]+','_',project_name).strip('_').lower() or 'hld'; return project_name,safe_name
    
# def _output_paths(safe_name: str) -> Dict[str,str]:
#     out=Path('generated_docs'); out.mkdir(exist_ok=True); return {'pdf':str(out/f'{safe_name}.pdf'),'docx':str(out/f'{safe_name}.docx'),'md':str(out/f'{safe_name}.md'),'html':str(out/f'{safe_name}.html')}
    
# def render_hld_documents(report: Dict[str,Any], tool_context=None) -> Dict[str,Any]:
#     try:
#         state=_state_from_tool_context(tool_context); report=_resolve_report_payload(report,state)
#         selected=normalize_selected_sections(state.get(KEY_RENDER_SELECTED_SECTIONS) or state.get(KEY_SELECTED_SECTIONS) or '')
#         report=normalize_hld(dynamic_inflate(HLDReport,report)); data=HLDReport.model_validate(report).model_dump()
#         project_name,safe_name=_safe_project_name(data); paths=_output_paths(safe_name)
#         md_master=build_markdown_master(data,HLDReport,selected,_logo_data_uri()); Path(paths['md']).write_text(md_master,encoding='utf-8')
#         build_pdf(md_master,paths['pdf'],html_path=paths['html']); build_docx(data,paths['docx'],HLDReport,selected,logo_path=str(BRANDING_DIR/'doc_logo.png'))
#         bucket=config.GCS_BUCKET_NAME; folder=project_name.strip().replace(' ','_')
#         gcs_paths=upload_outputs(bucket,folder,paths); signed_urls=generate_signed_urls(bucket,folder,paths)
#         return build_success_response(paths,gcs_paths,signed_urls)
#     except Exception as exc:
#         logger.exception('Failed to render HLD documents'); return build_error_response(exc)

# from __future__ import annotations

# import base64
# import json
# import logging
# import re
# from pathlib import Path
# from typing import Any, Dict

# from config_load import GetConf

# from schema_types.hld_schema import HLDReport
# from agent.workflow.keys import (
#     KEY_HLD_REPORT_JSON,
#     KEY_SELECTED_SECTIONS,
#     KEY_RENDER_SELECTED_SECTIONS,
# )
# from tools.hld_section_commit_tools import (
#     assemble_hld_from_state,
#     validate_required_hld_sections,
# )

# from .config import BRANDING_DIR
# from .docx_renderer import build_docx
# from .markdown_renderer import build_markdown_master
# from .pdf_renderer import build_pdf
# from .pptx_diagram_renderer import build_editable_pptx
# from .response_builder import build_error_response, build_success_response
# from .schema_utils import (
#     dynamic_inflate,
#     extract_metadata_sections,
#     normalize_hld,
#     normalize_selected_sections,
# )
# from .storage import generate_signed_urls, upload_outputs

# logger = logging.getLogger(__name__)

# config = GetConf.load_configs()

# extract_metadata_sections(HLDReport)


# def _state_from_tool_context(tool_context) -> Dict[str, Any]:
#     if not tool_context:
#         return {}

#     if hasattr(tool_context, "session") and getattr(tool_context, "session", None):
#         return tool_context.session.state or {}

#     if hasattr(tool_context, "state"):
#         return tool_context.state or {}

#     return {}


# def _resolve_report_payload(
#     report: Dict[str, Any],
#     state: Dict[str, Any],
# ) -> Dict[str, Any]:
#     state_hld = state.get(KEY_HLD_REPORT_JSON) if state else None

#     if state_hld:
#         if isinstance(state_hld, str):
#             try:
#                 return json.loads(state_hld)
#             except Exception:
#                 logger.warning(
#                     "session.state[%r] exists but is not valid JSON",
#                     KEY_HLD_REPORT_JSON,
#                 )
#         elif isinstance(state_hld, dict):
#             return state_hld

#     try:
#         section_report = validate_required_hld_sections(state)
#         if section_report.get("all_present"):
#             logger.info(
#                 "Render tool assembled HLD from section-wise state fallback."
#             )
#             return assemble_hld_from_state(state)
#     except Exception:
#         logger.exception(
#             "Failed to assemble HLD from section-wise state fallback."
#         )

#     return report


# def _logo_data_uri() -> str:
#     p = BRANDING_DIR / "doc_logo.png"

#     try:
#         if p.exists():
#             return (
#                 "data:image/png;base64,"
#                 + base64.b64encode(p.read_bytes()).decode()
#             )
#         return ""
#     except Exception:
#         logger.exception("Failed loading logo")
#         return ""


# def _safe_project_name(data: Dict[str, Any]) -> tuple[str, str]:
#     project_name = (
#         (data.get("project_details") or {}).get("project_name")
#         or "hld"
#     )

#     safe_name = (
#         re.sub(r"[^a-zA-Z0-9_-]+", "_", project_name)
#         .strip("_")
#         .lower()
#         or "hld"
#     )

#     return project_name, safe_name


# def _output_paths(safe_name: str) -> Dict[str, str]:
#     out = Path("generated_docs")
#     out.mkdir(exist_ok=True)

#     return {
#         "pdf": str(out / f"{safe_name}.pdf"),
#         "docx": str(out / f"{safe_name}.docx"),
#         "md": str(out / f"{safe_name}.md"),
#         "html": str(out / f"{safe_name}.html"),
#         "pptx": str(out / f"{safe_name}_editable_diagrams.pptx"),
#     }


# def _existing_output_paths(paths: Dict[str, str]) -> Dict[str, str]:
#     """
#     Return only files that actually exist on disk.

#     This is important so optional artifacts like PPTX do not break
#     upload/signing if generation fails.
#     """
#     existing: Dict[str, str] = {}

#     for key, path in paths.items():
#         try:
#             if path and Path(path).exists():
#                 existing[key] = path
#         except Exception:
#             logger.debug(
#                 "Failed checking output existence for key=%s path=%s",
#                 key,
#                 path,
#                 exc_info=True,
#             )

#     return existing


# def _build_editable_pptx_safe(
#     data: Dict[str, Any],
#     pptx_path: str,
#     selected_sections_set,
# ):
#     """
#     Generate editable PPTX as an optional artifact.

#     IMPORTANT:
#       - Must not break existing DOCX/PDF/MD/HTML generation.
#       - If PPTX generation fails, we log and continue.
#     """
#     try:
#         build_editable_pptx(
#             data=data,
#             pptx_path=pptx_path,
#             hld_model=HLDReport,
#             selected_sections_set=selected_sections_set,
#         )
#         logger.info("Editable PPTX generated successfully: %s", pptx_path)

#     except Exception:
#         logger.exception(
#             "Editable PPTX generation failed. Continuing without PPTX. path=%s",
#             pptx_path,
#         )


# def render_hld_documents(
#     report: Dict[str, Any],
#     tool_context=None,
# ) -> Dict[str, Any]:
#     try:
#         state = _state_from_tool_context(tool_context)
#         report = _resolve_report_payload(report, state)

#         selected = normalize_selected_sections(
#             state.get(KEY_RENDER_SELECTED_SECTIONS)
#             or state.get(KEY_SELECTED_SECTIONS)
#             or ""
#         )

#         report = normalize_hld(dynamic_inflate(HLDReport, report))
#         data = HLDReport.model_validate(report).model_dump()

#         project_name, safe_name = _safe_project_name(data)
#         paths = _output_paths(safe_name)

#         # Markdown master
#         md_master = build_markdown_master(
#             data,
#             HLDReport,
#             selected,
#             _logo_data_uri(),
#         )
#         Path(paths["md"]).write_text(md_master, encoding="utf-8")

#         # PDF
#         build_pdf(
#             md_master,
#             paths["pdf"],
#             html_path=paths["html"],
#         )

#         # DOCX
#         build_docx(
#             data,
#             paths["docx"],
#             HLDReport,
#             selected,
#             logo_path=str(BRANDING_DIR / "doc_logo.png"),
#         )

#         # Editable PPTX (optional, non-breaking)
#         _build_editable_pptx_safe(
#             data=data,
#             pptx_path=paths["pptx"],
#             selected_sections_set=selected,
#         )

#         # Upload only files that exist
#         existing_paths = _existing_output_paths(paths)

#         bucket = config.GCS_BUCKET_NAME
#         folder = project_name.strip().replace(" ", "_")

#         gcs_paths = upload_outputs(
#             bucket,
#             folder,
#             existing_paths,
#         )

#         signed_urls = generate_signed_urls(
#             bucket,
#             folder,
#             existing_paths,
#         )

#         return build_success_response(
#             existing_paths,
#             gcs_paths,
#             signed_urls,
#         )

#     except Exception as exc:
#         logger.exception("Failed to render HLD documents")
#         return build_error_response(exc)



# from __future__ import annotations

# import base64
# import json
# import logging
# import re
# from pathlib import Path
# from typing import Any, Dict

# from config_load import GetConf

# from schema_types.hld_schema import HLDReport
# from agent.workflow.keys import (
#     KEY_HLD_REPORT_JSON,
#     KEY_SELECTED_SECTIONS,
#     KEY_RENDER_SELECTED_SECTIONS,
# )
# from tools.hld_section_commit_tools import (
#     assemble_hld_from_state,
#     validate_required_hld_sections,
# )

# from .config import BRANDING_DIR
# from .docx_renderer import build_docx
# from .markdown_renderer import build_markdown_master
# from .pdf_renderer import build_pdf
# from .response_builder import build_error_response, build_success_response
# from .schema_utils import (
#     dynamic_inflate,
#     extract_metadata_sections,
#     normalize_hld,
#     normalize_selected_sections,
# )
# from .storage import generate_signed_urls, upload_outputs

# logger = logging.getLogger(__name__)

# config = GetConf.load_configs()

# extract_metadata_sections(HLDReport)


# def _state_from_tool_context(tool_context) -> Dict[str, Any]:
#     if not tool_context:
#         return {}

#     if hasattr(tool_context, "session") and getattr(tool_context, "session", None):
#         return tool_context.session.state or {}

#     if hasattr(tool_context, "state"):
#         return tool_context.state or {}

#     return {}


# def _resolve_report_payload(
#     report: Dict[str, Any],
#     state: Dict[str, Any],
# ) -> Dict[str, Any]:
#     state_hld = state.get(KEY_HLD_REPORT_JSON) if state else None

#     if state_hld:
#         if isinstance(state_hld, str):
#             try:
#                 return json.loads(state_hld)
#             except Exception:
#                 logger.warning(
#                     "session.state[%r] exists but is not valid JSON",
#                     KEY_HLD_REPORT_JSON,
#                 )
#         elif isinstance(state_hld, dict):
#             return state_hld

#     try:
#         section_report = validate_required_hld_sections(state)
#         if section_report.get("all_present"):
#             logger.info("Render tool assembled HLD from section-wise state fallback.")
#             return assemble_hld_from_state(state)
#     except Exception:
#         logger.exception("Failed to assemble HLD from section-wise state fallback.")

#     return report


# def _logo_data_uri() -> str:
#     p = BRANDING_DIR / "doc_logo.png"

#     try:
#         if p.exists():
#             return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
#         return ""
#     except Exception:
#         logger.exception("Failed loading logo")
#         return ""


# def _safe_project_name(data: Dict[str, Any]) -> tuple[str, str]:
#     project_name = (data.get("project_details") or {}).get("project_name") or "hld"

#     safe_name = (
#         re.sub(r"[^a-zA-Z0-9_-]+", "_", project_name)
#         .strip("_")
#         .lower()
#         or "hld"
#     )

#     return project_name, safe_name


# def _output_paths(safe_name: str) -> Dict[str, str]:
#     out = Path("generated_docs")
#     out.mkdir(exist_ok=True)

#     return {
#         "pdf": str(out / f"{safe_name}.pdf"),
#         "docx": str(out / f"{safe_name}.docx"),
#         "md": str(out / f"{safe_name}.md"),
#         "html": str(out / f"{safe_name}.html"),
#     }


# def _existing_output_paths(paths: Dict[str, str]) -> Dict[str, str]:
#     """
#     Return only files that actually exist on disk.

#     This prevents optional artefacts from breaking upload/signing if generation
#     fails or if a selected HLD section has no diagrams.
#     """
#     existing: Dict[str, str] = {}

#     for key, path in paths.items():
#         try:
#             if path and Path(path).exists():
#                 existing[key] = path
#         except Exception:
#             logger.debug(
#                 "Failed checking output existence for key=%s path=%s",
#                 key,
#                 path,
#                 exc_info=True,
#             )

#     return existing


# def _collect_diagram_asset_paths(safe_name: str) -> Dict[str, str]:
#     """
#     Collect editable diagram assets generated by docx_renderer.py.

#     DOCX renderer writes diagram assets here:
#         generated_docs/<safe_name>_diagram_assets/

#     Expected asset types:
#         .dot
#         _editable.svg
#         .png
#         .drawio

#     Important:
#         We collect assets instead of regenerating them in orchestrator. This
#         prevents duplicate/inconsistent diagram names and keeps DOCX-generated
#         links aligned with uploaded artefacts.
#     """
#     assets_dir = Path("generated_docs") / f"{safe_name}_diagram_assets"

#     if not assets_dir.exists():
#         logger.info("No diagram assets directory found: %s", assets_dir)
#         return {}

#     allowed_suffixes = {".dot", ".svg", ".png", ".drawio"}
#     output_paths: Dict[str, str] = {}
#     seen_keys: Dict[str, int] = {}

#     for path in sorted(assets_dir.iterdir()):
#         if not path.is_file():
#             continue

#         suffix = path.suffix.lower()
#         if suffix not in allowed_suffixes:
#             continue

#         asset_type = suffix.lstrip(".")
#         if path.name.lower().endswith("_editable.svg"):
#             asset_type = "svg"

#         safe_stem = (
#             re.sub(r"[^a-zA-Z0-9_-]+", "_", path.stem)
#             .strip("_")
#             .lower()
#             or "diagram_asset"
#         )

#         key_base = f"diagram_{safe_stem}_{asset_type}"
#         count = seen_keys.get(key_base, 0) + 1
#         seen_keys[key_base] = count

#         key = key_base if count == 1 else f"{key_base}_{count:02d}"
#         output_paths[key] = str(path)

#     logger.info(
#         "Collected %s editable diagram assets from %s",
#         len(output_paths),
#         assets_dir,
#     )
#     return output_paths


# def render_hld_documents(
#     report: Dict[str, Any],
#     tool_context=None,
# ) -> Dict[str, Any]:
#     try:
#         state = _state_from_tool_context(tool_context)
#         report = _resolve_report_payload(report, state)

#         selected = normalize_selected_sections(
#             state.get(KEY_RENDER_SELECTED_SECTIONS)
#             or state.get(KEY_SELECTED_SECTIONS)
#             or ""
#         )

#         report = normalize_hld(dynamic_inflate(HLDReport, report))
#         data = HLDReport.model_validate(report).model_dump()

#         project_name, safe_name = _safe_project_name(data)
#         paths = _output_paths(safe_name)

#         # Markdown master
#         md_master = build_markdown_master(
#             data,
#             HLDReport,
#             selected,
#             _logo_data_uri(),
#         )
#         Path(paths["md"]).write_text(md_master, encoding="utf-8")

#         # PDF
#         build_pdf(
#             md_master,
#             paths["pdf"],
#             html_path=paths["html"],
#         )

#         # DOCX
#         # DOCX renderer is now responsible for creating the editable diagram
#         # artefacts in generated_docs/<safe_name>_diagram_assets/.
#         build_docx(
#             data,
#             paths["docx"],
#             HLDReport,
#             selected,
#             logo_path=str(BRANDING_DIR / "doc_logo.png"),
#         )

#         # Collect editable diagram assets generated by DOCX renderer.
#         # Do not regenerate here; regeneration can cause duplicate/mismatched names.
#         diagram_asset_paths = _collect_diagram_asset_paths(safe_name)

#         combined_paths = {
#             **paths,
#             **diagram_asset_paths,
#         }

#         existing_paths = _existing_output_paths(combined_paths)

#         bucket = config.GCS_BUCKET_NAME
#         folder = project_name.strip().replace(" ", "_")

#         gcs_paths = upload_outputs(
#             bucket,
#             folder,
#             existing_paths,
#         )

#         signed_urls = generate_signed_urls(
#             bucket,
#             folder,
#             existing_paths,
#         )

#         return build_success_response(
#             existing_paths,
#             gcs_paths,
#             signed_urls,
#         )

#     except Exception as exc:
#         logger.exception("Failed to render HLD documents")
#         return build_error_response(exc)

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict

from config_load import GetConf

from schema_types.hld_schema import HLDReport
from agent.workflow.keys import (
    KEY_HLD_REPORT_JSON,
    KEY_SELECTED_SECTIONS,
    KEY_RENDER_SELECTED_SECTIONS,
)
from tools.hld_section_commit_tools import (
    assemble_hld_from_state,
    validate_required_hld_sections,
)

from .config import BRANDING_DIR
from .docx_renderer import build_docx
from .markdown_renderer import build_markdown_master
from .pdf_renderer import build_pdf
from .response_builder import build_error_response, build_success_response
from .schema_utils import (
    dynamic_inflate,
    extract_metadata_sections,
    normalize_hld,
    normalize_selected_sections,
)
from .storage import generate_signed_urls, upload_outputs

logger = logging.getLogger(__name__)

config = GetConf.load_configs()

extract_metadata_sections(HLDReport)


def _state_from_tool_context(tool_context) -> Dict[str, Any]:
    if not tool_context:
        return {}

    if hasattr(tool_context, "session") and getattr(tool_context, "session", None):
        return tool_context.session.state or {}

    if hasattr(tool_context, "state"):
        return tool_context.state or {}

    return {}


def _resolve_report_payload(
    report: Dict[str, Any],
    state: Dict[str, Any],
) -> Dict[str, Any]:
    state_hld = state.get(KEY_HLD_REPORT_JSON) if state else None

    if state_hld:
        if isinstance(state_hld, str):
            try:
                return json.loads(state_hld)
            except Exception:
                logger.warning(
                    "session.state[%r] exists but is not valid JSON",
                    KEY_HLD_REPORT_JSON,
                )
        elif isinstance(state_hld, dict):
            return state_hld

    try:
        section_report = validate_required_hld_sections(state)
        if section_report.get("all_present"):
            logger.info("Render tool assembled HLD from section-wise state fallback.")
            return assemble_hld_from_state(state)
    except Exception:
        logger.exception("Failed to assemble HLD from section-wise state fallback.")

    return report


def _logo_data_uri() -> str:
    p = BRANDING_DIR / "doc_logo.png"

    try:
        if p.exists():
            return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
        return ""
    except Exception:
        logger.exception("Failed loading logo")
        return ""


def _safe_project_name(data: Dict[str, Any]) -> tuple[str, str]:
    project_name = (data.get("project_details") or {}).get("project_name") or "hld"

    safe_name = (
        re.sub(r"[^a-zA-Z0-9_-]+", "_", project_name)
        .strip("_")
        .lower()
        or "hld"
    )

    return project_name, safe_name


def _output_paths(safe_name: str) -> Dict[str, str]:
    out = Path("generated_docs")
    out.mkdir(exist_ok=True)

    return {
        "pdf": str(out / f"{safe_name}.pdf"),
        "docx": str(out / f"{safe_name}.docx"),
        "md": str(out / f"{safe_name}.md"),
        "html": str(out / f"{safe_name}.html"),
    }


def _existing_output_paths(paths: Dict[str, str]) -> Dict[str, str]:
    """
    Return only files that actually exist on disk.

    This prevents optional artefacts from breaking upload/signing if generation
    fails or if a selected HLD section has no diagrams.
    """
    existing: Dict[str, str] = {}

    for key, path in paths.items():
        try:
            if path and Path(path).exists():
                existing[key] = path
        except Exception:
            logger.debug(
                "Failed checking output existence for key=%s path=%s",
                key,
                path,
                exc_info=True,
            )

    return existing


def _collect_diagram_asset_paths(safe_name: str) -> Dict[str, str]:
    """
    Collect editable diagram assets generated by docx_renderer.py.

    DOCX renderer writes diagram assets here:
        generated_docs/<safe_name>_diagram_assets/

    Expected asset types:
        .dot
        _editable.svg
        .png
        .drawio
        .vsdx

    Important:
        We collect assets instead of regenerating them in orchestrator. This
        prevents duplicate/inconsistent diagram names and keeps DOCX-generated
        links aligned with uploaded artefacts.
    """
    assets_dir = Path("generated_docs") / f"{safe_name}_diagram_assets"

    if not assets_dir.exists():
        logger.info("No diagram assets directory found: %s", assets_dir)
        return {}

    allowed_suffixes = {".dot", ".svg", ".png", ".drawio", ".vsdx"}
    output_paths: Dict[str, str] = {}
    seen_keys: Dict[str, int] = {}

    for path in sorted(assets_dir.iterdir()):
        if not path.is_file():
            continue

        suffix = path.suffix.lower()
        if suffix not in allowed_suffixes:
            continue

        asset_type = suffix.lstrip(".")
        if path.name.lower().endswith("_editable.svg"):
            asset_type = "svg"

        safe_stem = (
            re.sub(r"[^a-zA-Z0-9_-]+", "_", path.stem)
            .strip("_")
            .lower()
            or "diagram_asset"
        )

        key_base = f"diagram_{safe_stem}_{asset_type}"
        count = seen_keys.get(key_base, 0) + 1
        seen_keys[key_base] = count

        key = key_base if count == 1 else f"{key_base}_{count:02d}"
        output_paths[key] = str(path)

    logger.info(
        "Collected %s editable diagram assets from %s",
        len(output_paths),
        assets_dir,
    )
    return output_paths


def render_hld_documents(
    report: Dict[str, Any],
    tool_context=None,
) -> Dict[str, Any]:
    try:
        state = _state_from_tool_context(tool_context)
        report = _resolve_report_payload(report, state)

        selected = normalize_selected_sections(
            state.get(KEY_RENDER_SELECTED_SECTIONS)
            or state.get(KEY_SELECTED_SECTIONS)
            or ""
        )

        report = normalize_hld(dynamic_inflate(HLDReport, report))
        data = HLDReport.model_validate(report).model_dump()

        project_name, safe_name = _safe_project_name(data)
        paths = _output_paths(safe_name)

        # Markdown master
        md_master = build_markdown_master(
            data,
            HLDReport,
            selected,
            _logo_data_uri(),
        )
        Path(paths["md"]).write_text(md_master, encoding="utf-8")

        # PDF
        build_pdf(
            md_master,
            paths["pdf"],
            html_path=paths["html"],
        )

        # DOCX
        # DOCX renderer is responsible for creating the editable diagram
        # artefacts in generated_docs/<safe_name>_diagram_assets/.
        build_docx(
            data,
            paths["docx"],
            HLDReport,
            selected,
            logo_path=str(BRANDING_DIR / "doc_logo.png"),
        )

        # Collect editable diagram assets generated by DOCX renderer.
        # Do not regenerate here; regeneration can cause duplicate/mismatched names.
        diagram_asset_paths = _collect_diagram_asset_paths(safe_name)

        combined_paths = {
            **paths,
            **diagram_asset_paths,
        }

        existing_paths = _existing_output_paths(combined_paths)

        bucket = config.GCS_BUCKET_NAME
        folder = project_name.strip().replace(" ", "_")

        gcs_paths = upload_outputs(
            bucket,
            folder,
            existing_paths,
        )

        # Important:
        # Pass uploaded_outputs so signed URLs point to the actual uploaded object
        # name if storage.py versions/renames artefacts during upload.
        signed_urls = generate_signed_urls(
            bucket,
            folder,
            existing_paths,
            uploaded_outputs=gcs_paths,
        )

        return build_success_response(
            existing_paths,
            gcs_paths,
            signed_urls,
        )

    except Exception as exc:
        logger.exception("Failed to render HLD documents")
        return build_error_response(exc)