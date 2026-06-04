# from __future__ import annotations

# import os
# import re
# import json
# import html
# import base64
# import logging
# import tempfile
# from io import BytesIO
# from pathlib import Path
# from typing import Any, Dict, Optional, Tuple, List, Union, get_args, get_origin

# import markdown2
# import graphviz


# from PIL import Image, ImageDraw, ImageFont
# import hashlib

# from numpy import inner
# from pydantic import BaseModel
# from xhtml2pdf import pisa
# from google.adk.tools import FunctionTool

# from docx import Document
# from docx.shared import Inches, Pt
# from docx.enum.text import WD_ALIGN_PARAGRAPH
# from docx.oxml import OxmlElement
# from docx.oxml.ns import qn
# from typing import List
# from schema_types.hld_schema import HLDReport

# ## For GCS Document Storage
# from google.cloud import storage
# from pathlib import Path
# from datetime import timedelta
# from config_load import GetConf


# from google.auth import default
# from google.auth.credentials import Credentials
# from google.auth.exceptions import DefaultCredentialsError
# from google.auth import default

# from agent.workflow.keys import (
#     KEY_HLD_REPORT_JSON,
#     KEY_SELECTED_SECTIONS,
#     KEY_RENDER_SELECTED_SECTIONS,
# )

# from tools.hld_section_commit_tools import (
#     assemble_hld_from_state,
#     validate_required_hld_sections,
# )

# # --------------------------------------------------
# # Logging Setup
# # --------------------------------------------------
# logger = logging.getLogger(__name__)
# logging.basicConfig(level=logging.INFO)
# config = GetConf.load_configs()
# # --------------------------------------------------
# # Path Setup
# # --------------------------------------------------
# THIS_FILE = Path(__file__).resolve()
# PROJECT_ROOT = THIS_FILE.parent.parent
# ICON_DIR = PROJECT_ROOT / "assets" / "icons"
# BRANDING_DIR = PROJECT_ROOT / "assets" / "branding"

# # --------------------------------------------------
# # Diagram readability defaults
# # --------------------------------------------------
# DIAGRAM_GRAPH_FONT_SIZE = 18
# DIAGRAM_CLUSTER_FONT_SIZE = 16
# DIAGRAM_NODE_FONT_SIZE = 15
# DIAGRAM_EDGE_FONT_SIZE = 13

# DIAGRAM_NODE_CARD_SIZE = (430, 290)
# DIAGRAM_NODE_CARD_FONT_SIZE = 30

# DIAGRAM_NODE_CARD_WIDTH_IN = 3.05
# DIAGRAM_NODE_CARD_HEIGHT_IN = 2.05

# DIAGRAM_PDF_MAX_HEIGHT_PX = 680

# # Common aliases for icon resolution.
# # This scans only assets/icons. Branding logos remain under assets/branding.
# ICON_ALIASES = {
#     # Storage
#     "gcs": ["cloud_storage.png", "gcs.png", "google_cloud_storage.png"],
#     "storage": ["cloud_storage.png", "gcs.png", "google_cloud_storage.png"],
#     "cloudstorage": ["cloud_storage.png", "gcs.png", "google_cloud_storage.png"],

#     # Compute
#     "cloudfunctions": ["cloud_functions.png", "cloud_function.png"],
#     "cloudfunction": ["cloud_functions.png", "cloud_function.png"],
#     "functions": ["cloud_functions.png", "cloud_function.png"],
#     "function": ["cloud_functions.png", "cloud_function.png"],
#     "cloudrun": ["cloud_run.png"],

#     # Eventing
#     "eventarc": ["eventarc.png", "cloud_eventarc.png", "event_arc.png"],
#     "eventrouter": ["eventarc.png", "cloud_eventarc.png", "event_arc.png"],

#     # Security / key management
#     "kms": ["cloud_kms.png", "kms.png", "key_management_service.png"],
#     "cloudkms": ["cloud_kms.png", "kms.png", "key_management_service.png"],
#     "secretmanager": ["secret_manager.png", "secrets_manager.png"],
#     "iam": ["cloud_iam.png", "identity_and_access_management.png"],

#     # Data / analytics
#     "bq": ["bigquery.png"],
#     "bigquery": ["bigquery.png"],

#     # Observability
#     "logging": ["cloud_logging.png", "logging.png"],
#     "cloudlogging": ["cloud_logging.png", "logging.png"],
#     "monitoring": ["cloud_monitoring.png", "monitoring.png"],
#     "cloudmonitoring": ["cloud_monitoring.png", "monitoring.png"],

#     # Network / transfer
#     "vpn": ["cloud_vpn.png", "vpn.png"],
#     "interconnect": ["cloud_interconnect.png", "interconnect.png"],
#     "mft": ["transfer.png", "cloud_interconnect.png", "file_transfer.png"],
#     "transfer": ["transfer.png", "cloud_interconnect.png", "file_transfer.png"],

#     # CI/CD
#     "cloudbuild": ["cloud_build.png", "cloudbuild.png"],
#     "terraform": ["terraform.png"],

#     # External/custom
#     "teradata": ["teradata.png", "database.png", "generic_db.png", "bigquery.png"],
#     "collibra": ["collibra.png", "catalog.png"],
#     "database": ["database.png", "generic_db.png"],
#     "catalog": ["catalog.png"],
# }

# def _is_allowed_diagram_icon_file(path: Path) -> bool:
#     """
#     Allow only raster service icon files from assets/icons.
#     Branding logos are stored separately under assets/branding.
#     """
#     if not path or not path.is_file():
#         return False

#     return path.suffix.lower() in {".png", ".jpg", ".jpeg"}


# def _iter_icon_files() -> List[Path]:
#     """
#     Recursively list all usable icon files under assets/icons.
#     Supports nested icon packs like:
#       assets/icons/gcp/cloud_storage.png
#       assets/icons/gcp/cloud_functions.png
#     """
#     if not ICON_DIR.exists():
#         return []

#     return [
#         f for f in ICON_DIR.rglob("*")
#         if _is_allowed_diagram_icon_file(f)
#     ]

# # ============================================================
# # PART 1: TEXT SANITIZER / FORMATTER
# # ============================================================

# def normalize_icon_for_graphviz(icon_path: str, target_size: tuple[int, int] = (128, 72)) -> str:
#     """
#     Resize icon onto a standard transparent canvas so all icons render
#     at a visually consistent size in Graphviz.
#     """
#     try:
#         tmp_dir = Path(tempfile.gettempdir()) / "aia_icon_cache"
#         tmp_dir.mkdir(exist_ok=True)

#         src = Path(icon_path)
#         out_path = tmp_dir / f"{src.stem}_{target_size[0]}x{target_size[1]}.png"

#         if out_path.exists():
#             return str(out_path)

#         with Image.open(src).convert("RGBA") as img:
#             canvas = Image.new("RGBA", target_size, (255, 255, 255, 0))
#             img.thumbnail((target_size[0] - 8, target_size[1] - 8), Image.LANCZOS)
#             x = (target_size[0] - img.width) // 2
#             y = (target_size[1] - img.height) // 2
#             canvas.paste(img, (x, y), img)
#             canvas.save(out_path)

#         return str(out_path)
#     except Exception:
#         logger.exception("Failed to normalize icon for Graphviz: %s", icon_path)
#         return icon_path


# def _strip_html_tags_preserve_breaks(text: str) -> str:
#     """
#     Convert accidental HTML-ish / markdown-ish narrative content into
#     renderer-safe plain text while preserving line breaks / bullet semantics.
#     """
#     if text is None:
#         return ""

#     if not isinstance(text, str):
#         text = str(text)

#     # First unescape any HTML entities
#     text = html.unescape(text)

#     # Normalize literal and escaped break markers
#     text = text.replace("&lt;br/&gt;", "\n").replace("&lt;br&gt;", "\n")
#     text = text.replace("<br/>", "\n").replace("<br />", "\n").replace("<br>", "\n")

#     # Preserve meaningful structural breaks before stripping tags
#     text = re.sub(r'(?i)</p\s*>', '\n', text)
#     text = re.sub(r'(?i)</div\s*>', '\n', text)
#     text = re.sub(r'(?i)</li\s*>', '\n', text)

#     # Convert list item openings to plain bullets
#     text = re.sub(r'(?i)<li\s*>', '- ', text)

#     # Remove list/container tags
#     text = re.sub(r'(?i)</?(ul|ol|p|div|span)[^>]*>', '', text)

#     # Remove emphasis tags but keep content
#     text = re.sub(r'(?i)</?(b|strong|i|em|u)[^>]*>', '', text)

#     # Remove any remaining HTML/XML tags
#     text = re.sub(r'<[^>]+>', '', text)

#     # Strip markdown emphasis markers
#     text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
#     text = re.sub(r'__(.*?)__', r'\1', text)
#     text = re.sub(r'(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)', r'\1', text)
#     text = re.sub(r'(?<!_)_(?!\s)(.*?)(?<!\s)_(?!_)', r'\1', text)

#     # Clean spacing
#     text = text.replace('\r\n', '\n').replace('\r', '\n')
#     text = re.sub(r'\n{3,}', '\n\n', text)
#     text = re.sub(r'[ \t]{2,}', ' ', text)

#     return text.strip()


# def _display_text_for_renderer(value: Any, multiline: bool = True) -> str:
#     """
#     Generic renderer-safe display conversion.

#     - narrative HTML -> plain text
#     - markdown emphasis -> plain text
#     - dict/list -> concise readable display text
#     - avoids raw Python repr-like dumps in tables/cells
#     """
#     if value is None:
#         return "N/A"

#     if isinstance(value, str):
#         cleaned = _strip_html_tags_preserve_breaks(value)
#         return cleaned if cleaned else "N/A"

#     if isinstance(value, dict):
#         if not value:
#             return "N/A"

#         parts = []
#         for k, v in value.items():
#             key = str(k).replace("_", " ").title()
#             val = _display_text_for_renderer(v, multiline=False)
#             parts.append(f"{key}: {val}")

#         sep = "\n" if multiline else "; "
#         return sep.join(parts)

#     if isinstance(value, list):
#         if not value:
#             return "N/A"

#         if all(isinstance(i, dict) for i in value):
#             rows = []
#             for item in value:
#                 rows.append(_display_text_for_renderer(item, multiline=False))
#             sep = "\n" if multiline else " | "
#             return sep.join(rows)

#         rows = [_display_text_for_renderer(i, multiline=False) for i in value]
#         sep = "\n" if multiline else "; "
#         return sep.join(rows)

#     return str(value)

# def _renderer_safe_plain_text(value: Any) -> str:
#     """
#     Plain-text safe output for paragraph-like sections.
#     """
#     txt = _display_text_for_renderer(value, multiline=True)
#     txt = txt.replace('\r\n', '\n').replace('\r', '\n')
#     txt = re.sub(r'\n{3,}', '\n\n', txt)
#     return txt.strip() if txt.strip() else "N/A"


# def insert_soft_breaks(text: str, interval: int = 12) -> str: 
#     if not isinstance(text, str):
#         text = str(text)

#     # Make camelCase slightly more readable
#     text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)

#     def _split_long_token(match):
#         token = match.group(0)
#         # Use normal spaces instead of zero-width spaces for PDF safety
#         return " ".join(token[i:i + interval] for i in range(0, len(token), interval))

#     # Only split very long raw tokens with no natural separators
#     text = re.sub(r'[A-Za-z0-9]{20,}', _split_long_token, text)

#     return text


# def insert_url_breaks(text: str) -> str:
#     """
#     Insert safe wrap opportunities into long URL-like strings so PDF tables
#     can wrap them instead of overflowing across columns.
#     """
#     if not isinstance(text, str):
#         text = str(text)

#     # Add break opportunities after common URL separators
#     text = text.replace("/", "/ ")
#     text = text.replace("?", "? ")
#     text = text.replace("&", "& ")
#     text = text.replace("=", "= ")
#     text = text.replace("-", "- ")

#     return text

# def clean_cell_text(text: Any, apply_soft_breaks: bool = True) -> str:
#     if text is None:
#         return "N/A"

#     val_str = _display_text_for_renderer(text, multiline=True)

#     if not val_str.strip():
#         return "N/A"

#     # Add extra wrap opportunities for URL-like content before escaping
#     val_str = insert_url_breaks(val_str)

#     if apply_soft_breaks:
#         val_str = "\n".join(insert_soft_breaks(line) for line in val_str.splitlines())

#     val_str = html.escape(val_str, quote=False)
#     val_str = val_str.replace("|", "&#124;")
#     val_str = val_str.replace("\r\n", "<br/>").replace("\n", "<br/>")
#     val_str = re.sub(r'(<br/>)?(\d+\.\s+|[•\-\*]\s+)', r'<br/>\2', val_str)
#     val_str = re.sub(r'^(?:<br/>)+', '', val_str)

#     return val_str.strip()


# def format_paragraph_points(text: str) -> str:
#     """
#     Renderer-safe paragraph formatter for narrative text.

#     - strips accidental HTML / markdown emphasis
#     - preserves readable numbering/bullets
#     - returns real <br/> tags for PDF/HTML narrative rendering
#     """
#     if not isinstance(text, str):
#         text = str(text)

#     text = _renderer_safe_plain_text(text)

#     # Put bullets / numbering on new lines
#     text = re.sub(r'(?<!\n)(\d+\.\s+|[•\-\*]\s+)', r'\n\1', text)
#     text = re.sub(r'^\n+', '', text)

#     # Escape everything except our intentional line breaks
#     safe = html.escape(text, quote=False)

#     # Convert actual newlines into real HTML breaks for markdown2/xhtml2pdf
#     safe = safe.replace("\r\n", "<br/>").replace("\n", "<br/>")

#     return safe.strip()



# def unescape_breaks(text: str) -> str:
#     if text is None:
#         return "N/A"

#     text = html.unescape(str(text))
#     text = text.replace("&lt;br/&gt;", "\n").replace("&lt;br&gt;", "\n")
#     text = text.replace("<br/>", "\n").replace("<br />", "\n").replace("<br>", "\n")
#     text = _strip_html_tags_preserve_breaks(text)
#     return text

# # ============================================================
# # PART 2: DYNAMIC SCHEMA INFLATION
# # ============================================================

# def dynamic_inflate(schema_cls: Any, data: Any) -> Any:
#     if data is None:
#         return data

#     origin = get_origin(schema_cls)
#     args = get_args(schema_cls)

#     if origin is Union:
#         non_none_args = [a for a in args if a is not type(None)]
#         if non_none_args:
#             return dynamic_inflate(non_none_args[0], data)
#         return data

#     if origin is list:
#         inner = args[0] if args else Any
#         return [dynamic_inflate(inner, i) for i in (data or [])]

#     if isinstance(schema_cls, type) and issubclass(schema_cls, BaseModel):
#         if isinstance(data, dict):
#             valid_fields = schema_cls.model_fields
#             squashed_to_actual = {k.replace("_", "").lower(): k for k in valid_fields.keys()}
#             inflated_data = {}

#             for raw_k, v in data.items():
#                 sq_k = str(raw_k).replace("_", "").lower()
#                 if sq_k in squashed_to_actual:
#                     actual_k = squashed_to_actual[sq_k]
#                     inflated_data[actual_k] = dynamic_inflate(valid_fields[actual_k].annotation, v)

#             return inflated_data

#     return data


# # ============================================================
# # PART 3: DIAGRAM CLASSIFICATION / NORMALIZATION
# # ============================================================

# def strip_code_fence(text: str) -> str:
#     if not isinstance(text, str):
#         return str(text)
#     raw = text.strip()
#     raw = re.sub(r"^```(?:dot|graphviz|mermaid)?\s*", "", raw)
#     raw = re.sub(r"\s*```$", "", raw)
#     return raw.strip()


# def unescape_graphviz_text(text: str) -> str:
#     """
#     Decode common HTML/entity escaped Graphviz text.

#     Important:
#     - Converts -&gt; / -&amp;gt; variants to real ->
#     - Repeatedly unescapes double/triple escaped DOT strings
#     """
#     if not isinstance(text, str):
#         return str(text)

#     for _ in range(4):
#         new_text = html.unescape(text)
#         if new_text == text:
#             break
#         text = new_text

#     text = (
#         text
#         .replace("-&gt;", "->")
#         .replace("-&amp;gt;", "->")
#         .replace("-&amp;amp;gt;", "->")
#         .replace("-&amp;amp;amp;gt;", "->")
#     )

#     return text


# def classify_diagram_text(text: str) -> Tuple[str, str]:
#     if not isinstance(text, str):
#         return "plain", str(text)

#     raw = text.strip()
#     fenced = re.match(r"^```(\w+)?\s*\n(.*?)\n```$", raw, flags=re.DOTALL)
#     if fenced:
#         lang = (fenced.group(1) or "").strip().lower()
#         body = fenced.group(2).strip()
#         if lang in ("dot", "graphviz"):
#             return "graphviz", body
#         if lang == "mermaid":
#             return "mermaid_like", body
#         raw = body

#     lines = raw.splitlines()
#     first_line = lines[0].strip() if lines else ""

#     if raw.startswith("digraph ") or raw.startswith("graph "):
#         if re.match(r"^graph\s+(TD|TB|BT|LR|RL)\b", first_line, flags=re.IGNORECASE):
#             return "mermaid_like", raw
#         return "graphviz", raw

#     if re.match(r"^(graph\s+(TD|TB|BT|LR|RL)|flowchart\s+(TD|TB|BT|LR|RL))\b", first_line, flags=re.IGNORECASE):
#         return "mermaid_like", raw

#     return "plain", raw


# def mermaid_like_to_dot(text: str) -> Optional[str]:
#     """Supports a small Mermaid-like subset by converting to DOT."""
#     if not isinstance(text, str):
#         return None

#     lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
#     if not lines:
#         return None

#     first = lines[0]
#     rankdir = "TB"
#     m_dir = re.match(r"^(graph|flowchart)\s+(TD|TB|BT|LR|RL)$", first, flags=re.IGNORECASE)
#     if m_dir:
#         direction = m_dir.group(2).upper()
#         rankdir_map = {
#             "TD": "TB",
#             "TB": "TB",
#             "BT": "BT",
#             "LR": "LR",
#             "RL": "RL",
#         }
#         rankdir = rankdir_map.get(direction, "TB")
#         lines = lines[1:]

#     nodes: Dict[str, Tuple[str, str]] = {}
#     edges: List[Tuple[str, str, Optional[str]]] = []

#     def parse_node(token: str) -> Tuple[str, str, str]:
#         token = token.strip().rstrip(";").strip()

#         m = re.match(r'^([A-Za-z0-9_]+)\[\((.*?)\)\]$', token)
#         if m:
#             return m.group(1), m.group(2).strip(), "cylinder"

#         m = re.match(r'^([A-Za-z0-9_]+)\[(.*?)\]$', token)
#         if m:
#             return m.group(1), m.group(2).strip(), "box"

#         m = re.match(r'^([A-Za-z0-9_]+)\(\((.*?)\)\)$', token)
#         if m:
#             return m.group(1), m.group(2).strip(), "circle"

#         m = re.match(r'^([A-Za-z0-9_]+)\((.*?)\)$', token)
#         if m:
#             return m.group(1), m.group(2).strip(), "ellipse"

#         m = re.match(r'^([A-Za-z0-9_]+)\{(.*?)\}$', token)
#         if m:
#             return m.group(1), m.group(2).strip(), "diamond"

#         m = re.match(r'^([A-Za-z0-9_]+)$', token)
#         if m:
#             return m.group(1), m.group(1), "box"

#         safe_id = re.sub(r'[^A-Za-z0-9_]', '_', token) or "node"
#         return safe_id, token, "box"

#     edge_patterns = [
#         re.compile(r'^(.*?)\s*-->\|(.*?)\|\s*(.*?)$'),
#         re.compile(r'^(.*?)\s*-->\s*(.*?)$'),
#     ]

#     for line in lines:
#         if line.startswith("%%"):
#             continue

#         matched = False
#         for idx, pat in enumerate(edge_patterns):
#             m = pat.match(line)
#             if m:
#                 matched = True
#                 if idx == 0:
#                     left_raw, edge_label, right_raw = m.group(1), m.group(2), m.group(3)
#                 else:
#                     left_raw, right_raw = m.group(1), m.group(2)
#                     edge_label = None

#                 left_id, left_label, left_shape = parse_node(left_raw)
#                 right_id, right_label, right_shape = parse_node(right_raw)

#                 nodes[left_id] = (left_label, left_shape)
#                 nodes[right_id] = (right_label, right_shape)
#                 edges.append((left_id, right_id, edge_label))
#                 break

#         if not matched:
#             node_id, node_label, node_shape = parse_node(line)
#             nodes[node_id] = (node_label, node_shape)

#     if not nodes and not edges:
#         return None

#     out = [
#         "digraph G {",
#         f"  rankdir={rankdir};",
#         '  graph [splines=polyline, pad="0.40", nodesep="0.80", ranksep="1.10", overlap=false, fontname="Helvetica", outputorder="edgesfirst"];',
#         '  node [fontname="Helvetica", fontsize=10, height=0.72, margin="0.12,0.08", fixedsize=false];',
#         '  edge [fontname="Helvetica", fontsize=9, labelfloat=false, labeldistance=1.8, labelangle=25, minlen=2, penwidth=1.8, color="#1D70B8"];'
#     ]

#     for node_id, (label, shape) in nodes.items():
#         safe_label = label.replace('"', '\\"')
#         out.append(f'  "{node_id}" [label="{safe_label}", shape={shape}];')

#     for left_id, right_id, edge_label in edges:
#         if edge_label:
#             safe_edge_label = edge_label.replace('"', '\\"')
#             out.append(f'  "{left_id}" -> "{right_id}" [xlabel="{safe_edge_label}"];')
#         else:
#             out.append(f'  "{left_id}" -> "{right_id}";')

#     out.append("}")
#     return "\n".join(out)


# def normalize_to_graphviz_dot(text: str) -> Optional[str]:
#     kind, body = classify_diagram_text(text)

#     if kind == "graphviz":
#         return strip_code_fence(body)

#     if kind == "mermaid_like":
#         return mermaid_like_to_dot(body)

#     return None


# # ============================================================
# # PART 4: GRAPHVIZ HARDENING
# # ============================================================

# def wrap_graphviz_label(label: str, max_chars: int = 18, max_lines: int = 2) -> str:
#     """
#     Wrap a label onto at most `max_lines` lines using word boundaries.
#     Keeps labels readable in process/flow diagrams.
#     """
#     if not label:
#         return label

#     words = str(label).split()
#     if not words:
#         return label

#     lines: List[str] = []
#     current: List[str] = []
#     consumed = 0

#     for word in words:
#         trial = " ".join(current + [word]).strip()
#         if len(trial) <= max_chars or not current:
#             current.append(word)
#             consumed += 1
#         else:
#             lines.append(" ".join(current))
#             current = [word]
#             consumed += 1
#             if len(lines) >= max_lines - 1:
#                 break

#     if current:
#         remaining = " ".join(current)
#         leftover_words = words[consumed:]
#         if leftover_words:
#             remaining = remaining + " " + " ".join(leftover_words)
#         lines.append(remaining)

#     if len(lines) > max_lines:
#         lines = lines[:max_lines]

#     return "\\n".join(line.strip() for line in lines if line.strip())


# def split_attr_block(line: str) -> Tuple[str, str, str]:
#     if "[" not in line or "]" not in line:
#         return line, "", ""
#     pre, rest = line.split("[", 1)
#     inner, post = rest.rsplit("]", 1)
#     return pre, inner, post


# EDGE_GROUP_RE = re.compile(
#     r'(?P<src>"?[\w.-]+"?)\s*->\s*\{\s*(?P<dsts>[^}]+?)\s*\}\s*(?:\[(?P<attrs>[^\]]*)\])?\s*;',
#     flags=re.DOTALL,
# )


# def expand_grouped_edges(dot_text: str) -> str:
#     def repl(match):
#         src = match.group("src").strip()
#         dsts_raw = match.group("dsts").strip()
#         attrs = (match.group("attrs") or "").strip()

#         dsts = [d.strip() for d in re.split(r'[\s,]+', dsts_raw) if d.strip()]
#         attr_suffix = f" [{attrs}]" if attrs else ""

#         return "\n".join(
#             f"{src} -> {dst}{attr_suffix};"
#             for dst in dsts
#         )

#     return EDGE_GROUP_RE.sub(repl, dot_text)


# def split_dot_statements(dot_text: str) -> str:
#     out = []
#     in_quotes = False
#     escape = False
#     i = 0
    
#     while i < len(dot_text):
#         ch = dot_text[i]
        
#         if ch == "\\" and not escape:
#             if i + 1 < len(dot_text) and dot_text[i+1] == "n" and not in_quotes:
#                 out.append("\n")
#                 i += 2
#                 continue
                
#             escape = True
#             out.append(ch)
#             i += 1
#             continue

#         if ch == '"' and not escape:
#             in_quotes = not in_quotes
#             out.append(ch)
#             i += 1
#             continue

#         escape = False

#         # 👇 NEW FIX: Convert literal newlines INSIDE quotes into Graphviz-safe \n 👇
#         if ch == "\n" and in_quotes:
#             out.append("\\n")
#             i += 1
#             continue

#         if not in_quotes:
#             if ch == "{":
#                 out.append("{\n")
#                 i += 1
#                 continue
#             elif ch == "}":
#                 out.append("\n}\n")
#                 i += 1
#                 continue
#             elif ch == ";":
#                 out.append(";\n")
#                 i += 1
#                 continue

#         out.append(ch)
#         i += 1

#     text = "".join(out)
#     text = re.sub(r"\n{3,}", "\n\n", text)
#     return text


# def normalize_icon_name(filename: str) -> str:
#     base = os.path.basename(filename)
#     base = os.path.splitext(base)[0].lower()
#     base = re.sub(r'512|color|colour|rgb|icon|logo', '', base)
#     base = re.sub(r'[^a-z0-9]', '', base)
#     return base

# def normalize_for_search(name: str) -> str:
#     """Strips noise words, prefixes, and punctuation for deep fuzzy matching."""
#     n = Path(name).stem.lower()
    
#     # 1. Remove Graphviz/File size noise
#     n = re.sub(r'512|256|128|64|color|colour|rgb|icon|logo', '', n)
    
#     # 2. Replace underscores and dashes with spaces to identify whole words
#     n = n.replace('_', ' ').replace('-', ' ')
    
#     # 3. Aggressively strip ALL noise words ANYWHERE in the string 
#     # (Fixes the "google_cloud_storage_api" vs "cloud_storage" mismatch)
#     n = re.sub(r'\b(google|cloud|gcp|api|apis|service|platform)\b', '', n)
    
#     # 4. Strip all non-alphanumeric characters (removes the spaces)
#     n = re.sub(r'[^a-z0-9]', '', n)
    
#     # 5. De-pluralize (strip trailing 's' if word is long enough)
#     if n.endswith('s') and len(n) > 3:
#         n = n[:-1]
        
#     return n.strip()


# def resolve_image_path(requested_path: str, project_root: Path = PROJECT_ROOT) -> str:
#     """
#     Resolve an icon path from:
#     - explicit relative path
#     - basename under assets/icons recursively
#     - alias map
#     - normalized fuzzy matching

#     This scans only ICON_DIR = assets/icons.
#     Branding logos are not scanned.
#     """
#     if not requested_path:
#         return ""

#     requested_path = str(requested_path).strip().strip('"').strip("'")
#     requested_base = Path(requested_path).name
#     req_stem = Path(requested_base).stem.lower()

#     # ------------------------------------------------------------
#     # 1) Explicit path under project root
#     # ------------------------------------------------------------
#     candidate = (project_root / requested_path).resolve()
#     if _is_allowed_diagram_icon_file(candidate):
#         return str(candidate).replace("\\", "/")

#     # ------------------------------------------------------------
#     # 2) Explicit path under assets/icons
#     # ------------------------------------------------------------
#     candidate = (ICON_DIR / requested_path).resolve()
#     if _is_allowed_diagram_icon_file(candidate):
#         return str(candidate).replace("\\", "/")

#     # ------------------------------------------------------------
#     # 3) Basename match recursively under assets/icons
#     # ------------------------------------------------------------
#     for f in _iter_icon_files():
#         if f.name.lower() == requested_base.lower():
#             return str(f.resolve()).replace("\\", "/")

#     # ------------------------------------------------------------
#     # 4) Alias map
#     # ------------------------------------------------------------
#     if req_stem in ICON_ALIASES:
#         for alias_name in ICON_ALIASES[req_stem]:
#             alias_base = Path(alias_name).name.lower()
#             for f in _iter_icon_files():
#                 if f.name.lower() == alias_base:
#                     return str(f.resolve()).replace("\\", "/")

#     # ------------------------------------------------------------
#     # 5) Normalized fuzzy matching
#     # ------------------------------------------------------------
#     target_norm = normalize_for_search(requested_base or requested_path)
#     if not target_norm:
#         return ""

#     # Pass A: exact normalized match
#     for f in _iter_icon_files():
#         file_norm = normalize_for_search(f.name)
#         if file_norm and target_norm == file_norm:
#             return str(f.resolve()).replace("\\", "/")

#     # Pass B: substring match
#     if len(target_norm) >= 3:
#         for f in _iter_icon_files():
#             file_norm = normalize_for_search(f.name)
#             if file_norm and len(file_norm) >= 2:
#                 if target_norm in file_norm or file_norm in target_norm:
#                     return str(f.resolve()).replace("\\", "/")

#     return ""

# SERVICE_LABEL_ICON_ALIASES = {
#     # Storage
#     "google cloud storage": ["cloud_storage.png", "gcs.png", "google_cloud_storage.png"],
#     "cloud storage": ["cloud_storage.png", "gcs.png", "google_cloud_storage.png"],
#     "gcs bucket": ["cloud_storage.png", "gcs.png", "google_cloud_storage.png"],
#     "gcs": ["cloud_storage.png", "gcs.png", "google_cloud_storage.png"],
#     "bucket": ["cloud_storage.png", "gcs.png", "google_cloud_storage.png"],

#     # Compute
#     "google cloud functions": ["cloud_functions.png", "cloud_function.png"],
#     "cloud functions": ["cloud_functions.png", "cloud_function.png"],
#     "cloud function": ["cloud_functions.png", "cloud_function.png"],
#     "functions": ["cloud_functions.png", "cloud_function.png"],
#     "cloud run": ["cloud_run.png"],

#     # Eventing
#     "eventarc": ["eventarc.png", "cloud_eventarc.png", "event_arc.png"],
#     "event router": ["eventarc.png", "cloud_eventarc.png", "event_arc.png"],
#     "event routing": ["eventarc.png", "cloud_eventarc.png", "event_arc.png"],
#     "gcs event notification": ["eventarc.png", "cloud_pubsub.png", "pubsub.png"],
#     "gcs event": ["eventarc.png", "cloud_pubsub.png", "pubsub.png"],

#     # Security / key management
#     "google cloud key management service": ["cloud_kms.png", "kms.png", "key_management_service.png"],
#     "cloud key management service": ["cloud_kms.png", "kms.png", "key_management_service.png"],
#     "google cloud kms": ["cloud_kms.png", "kms.png", "key_management_service.png"],
#     "cloud kms": ["cloud_kms.png", "kms.png"],
#     "kms": ["cloud_kms.png", "kms.png"],
#     "key access": ["cloud_kms.png", "kms.png"],
#     "cmek": ["cloud_kms.png", "kms.png"],
#     "secret manager": ["secret_manager.png", "secrets_manager.png"],
#     "google cloud secret manager": ["secret_manager.png", "secrets_manager.png"],
#     "secret access": ["secret_manager.png", "secrets_manager.png"],

#     # Observability
#     "google cloud logging": ["cloud_logging.png", "logging.png"],
#     "cloud logging": ["cloud_logging.png", "logging.png"],
#     "logging": ["cloud_logging.png", "logging.png"],
#     "google cloud monitoring": ["cloud_monitoring.png", "monitoring.png"],
#     "cloud monitoring": ["cloud_monitoring.png", "monitoring.png"],
#     "monitoring": ["cloud_monitoring.png", "monitoring.png"],
#     "observability": ["cloud_monitoring.png", "monitoring.png"],

#     # Network / transfer
#     "cloud vpn": ["cloud_vpn.png", "vpn.png"],
#     "google cloud vpn": ["cloud_vpn.png", "vpn.png"],
#     "ha vpn": ["cloud_vpn.png", "vpn.png"],
#     "cloud interconnect": ["cloud_interconnect.png", "interconnect.png"],
#     "google cloud interconnect": ["cloud_interconnect.png", "interconnect.png"],
#     "interconnect": ["cloud_interconnect.png", "interconnect.png"],
#     "managed file transfer": ["transfer.png", "cloud_interconnect.png", "file_transfer.png"],
#     "mft": ["transfer.png", "cloud_interconnect.png", "file_transfer.png"],
#     "transfer": ["transfer.png", "cloud_interconnect.png", "file_transfer.png"],

#     # CI/CD
#     "cloud build": ["cloud_build.png", "cloudbuild.png"],
#     "google cloud build": ["cloud_build.png", "cloudbuild.png"],
#     "terraform": ["terraform.png"],

#     # External/custom
#     "teradata": ["teradata.png", "database.png", "generic_db.png"],
#     "database": ["database.png", "generic_db.png"],
#     "collibra": ["collibra.png", "catalog.png"],
#     "catalog": ["catalog.png"],
# }


# PASTEL_CATEGORY_STYLE = {
#     "storage": {
#         "fill": "#E8F0FE",
#         "border": "#4285F4",
#         "font": "#174EA6",
#     },
#     "compute": {
#         "fill": "#E6F4EA",
#         "border": "#34A853",
#         "font": "#137333",
#     },
#     "security": {
#         "fill": "#FEF7E0",
#         "border": "#FBBC04",
#         "font": "#B06000",
#     },
#     "network": {
#         "fill": "#E0F2F1",
#         "border": "#00ACC1",
#         "font": "#006064",
#     },
#     "observability": {
#         "fill": "#F3E8FD",
#         "border": "#A142F4",
#         "font": "#6A1B9A",
#     },
#     "cicd": {
#         "fill": "#FCE8E6",
#         "border": "#EA4335",
#         "font": "#A50E0E",
#     },
#     "external": {
#         "fill": "#F1F3F4",
#         "border": "#5F6368",
#         "font": "#3C4043",
#     },
# }


# def normalize_service_label(label: str) -> str:
#     text = str(label or "").lower()
#     text = text.replace("\\n", " ")
#     text = text.replace("\n", " ")
#     text = text.replace("(", " ")
#     text = text.replace(")", " ")
#     text = re.sub(r"[^a-z0-9/+ ]+", " ", text)
#     text = re.sub(r"\s+", " ", text).strip()
#     return text


# def resolve_icon_from_node_label(label: str, project_root: Path = PROJECT_ROOT) -> str:
#     """
#     Resolve icon from canonical service label generated by the architect.

#     Example:
#       Google Cloud Storage\\n(Encrypted Landing Bucket)
#       -> assets/icons/.../cloud_storage.png
#     """
#     normalized = normalize_service_label(label)

#     for service_key, candidates in SERVICE_LABEL_ICON_ALIASES.items():
#         if service_key in normalized:
#             for candidate in candidates:
#                 resolved = resolve_image_path(candidate, project_root)
#                 if resolved:
#                     return resolved

#     return resolve_image_path(label, project_root)


# def classify_node_category(label: str) -> str:
#     normalized = normalize_service_label(label)

#     if any(x in normalized for x in ["google cloud storage", "cloud storage", "gcs", "bucket"]):
#         return "storage"

#     if any(x in normalized for x in ["cloud functions", "cloud function", "cloud run", "function"]):
#         return "compute"

#     if any(x in normalized for x in ["kms", "key management", "secret", "iam", "security", "cmek"]):
#         return "security"

#     if any(x in normalized for x in ["eventarc", "event router", "event routing", "pubsub", "pub sub"]):
#         return "network"

#     if any(x in normalized for x in ["vpn", "interconnect", "network", "mft", "transfer"]):
#         return "network"

#     if any(x in normalized for x in ["logging", "monitoring", "observability"]):
#         return "observability"

#     if any(x in normalized for x in ["cloud build", "terraform", "ci/cd", "deployment"]):
#         return "cicd"

#     return "external"


# def get_pastel_style_for_label(label: str) -> Dict[str, str]:
#     return PASTEL_CATEGORY_STYLE.get(
#         classify_node_category(label),
#         PASTEL_CATEGORY_STYLE["external"],
#     )


# def _clean_dot_label(label: str) -> str:
#     label = str(label or "")
#     label = label.replace("\\n", " ")
#     label = label.replace("\n", " ")
#     label = re.sub(r"\s+", " ", label).strip()
#     return label


# def _extract_label_from_attrs(inner: str, fallback: str) -> str:
#     label_match = re.search(r'label\s*=\s*"(.*?)"', inner or "")
#     if label_match:
#         return label_match.group(1)
#     return fallback


# def _is_control_statement(stripped: str) -> bool:
#     lower = stripped.lower().strip()

#     if not lower:
#         return True

#     if lower in {"{", "}"}:
#         return True

#     control_prefixes = (
#         "rankdir",
#         "label",
#         "color",
#         "fillcolor",
#         "style",
#         "fontsize",
#         "fontname",
#         "margin",
#         "nodesep",
#         "ranksep",
#         "splines",
#         "overlap",
#         "outputorder",
#         "subgraph",
#     )

#     return lower.startswith(control_prefixes)

# def _dot_html_escape(value: Any) -> str:
#     """
#     Escape text for Graphviz HTML-like labels.
#     Converts Graphviz-style \\n into <BR/>.
#     """
#     if value is None:
#         return ""

#     text = str(value)
#     text = text.replace("\\n", "\n")
#     text = html.escape(text, quote=False)
#     text = text.replace("\n", "<BR/>")
#     return text


# def _dot_attr_escape(value: Any) -> str:
#     """
#     Escape text for standard DOT quoted attributes.
#     """
#     if value is None:
#         return ""

#     text = str(value)
#     text = text.replace("\\", "\\\\")
#     text = text.replace('"', '\\"')
#     text = text.replace("\n", "\\n")
#     return text


# def _dot_path_escape(path: str) -> str:
#     """
#     Escape file path for Graphviz HTML IMG SRC.
#     """
#     return (
#         str(path)
#         .replace("\\", "/")
#         .replace("&", "&amp;")
#         .replace('"', "&quot;")
#     )


# def log_available_icons_once():
#     """
#     Debug helper: logs all icon files found by renderer.
#     This tells you immediately whether Cloud Run/Docker contains assets/icons.
#     """
#     icons = _iter_icon_files()

#     logger.info("[ICON] PROJECT_ROOT=%s", PROJECT_ROOT)
#     logger.info("[ICON] ICON_DIR=%s exists=%s", ICON_DIR, ICON_DIR.exists())
#     logger.info("[ICON] Found %s icon files", len(icons))

#     for f in icons[:120]:
#         logger.info("[ICON] available: %s normalized=%s", f, normalize_for_search(f.name))


# def _safe_graphviz_image_path(path: str) -> str:
#     """
#     Escape an image path for DOT image="...".
#     """
#     return str(path).replace("\\", "/").replace('"', '\\"')


# def _load_card_font(size: int, bold: bool = False):
#     """
#     Best-effort font loader for node-card image generation.
#     Works in local macOS/Linux/Cloud Run with fallback to PIL default.
#     """
#     candidate_fonts = []

#     if bold:
#         candidate_fonts.extend([
#             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
#             "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
#             "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
#             "/Library/Fonts/Arial Bold.ttf",
#         ])
#     else:
#         candidate_fonts.extend([
#             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
#             "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
#             "/System/Library/Fonts/Supplemental/Arial.ttf",
#             "/Library/Fonts/Arial.ttf",
#         ])

#     for font_path in candidate_fonts:
#         try:
#             if Path(font_path).exists():
#                 return ImageFont.truetype(font_path, size=size)
#         except Exception:
#             pass

#     return ImageFont.load_default()


# def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
#     """
#     Pillow-version-safe text size helper.
#     """
#     try:
#         bbox = draw.textbbox((0, 0), text, font=font)
#         return bbox[2] - bbox[0], bbox[3] - bbox[1]
#     except Exception:
#         return draw.textsize(text, font=font)


# def _wrap_text_for_card(
#     draw: ImageDraw.ImageDraw,
#     text: str,
#     font,
#     max_width_px: int,
#     max_lines: int = 3,
# ) -> list[str]:
#     """
#     Wrap node card label into a few lines that fit image width.
#     """
#     text = str(text or "").replace("\\n", " ").replace("\n", " ")
#     text = re.sub(r"\s+", " ", text).strip()

#     if not text:
#         return [""]

#     words = text.split()
#     lines: list[str] = []
#     current: list[str] = []

#     for word in words:
#         candidate = " ".join(current + [word]).strip()
#         w, _ = _text_size(draw, candidate, font)

#         if w <= max_width_px or not current:
#             current.append(word)
#         else:
#             lines.append(" ".join(current))
#             current = [word]

#             if len(lines) >= max_lines - 1:
#                 break

#     if current:
#         remaining = " ".join(current)
#         consumed_words = " ".join(lines + [remaining]).split()
#         if len(consumed_words) < len(words):
#             leftover = words[len(consumed_words):]
#             remaining = remaining + " " + " ".join(leftover)

#         lines.append(remaining)

#     lines = lines[:max_lines]

#     # Ellipsize last line if still too long
#     if lines:
#         last = lines[-1]
#         while last and _text_size(draw, last + "...", font)[0] > max_width_px:
#             last = last[:-1]
#         if last != lines[-1]:
#             lines[-1] = last.rstrip() + "..."

#     return lines


# def _make_composite_node_card(
#     label: str,
#     icon_path: str,
#     fill: str,
#     border: str,
#     font_color: str,
#     target_size: tuple[int, int] = DIAGRAM_NODE_CARD_SIZE,
# ) -> Optional[str]:
#     """
#     Build a PNG node card containing:
#     - pastel rounded rectangle
#     - service icon
#     - wrapped label

#     This avoids Graphviz HTML <IMG> label parsing issues.
#     Graphviz will only receive image="node_card.png".
#     """
#     try:
#         src_icon = Path(icon_path)
#         if not src_icon.exists():
#             logger.warning("[ICON] Composite card skipped; icon does not exist: %s", icon_path)
#             return None

#         cache_dir = Path(tempfile.gettempdir()) / "aia_node_card_cache"
#         cache_dir.mkdir(parents=True, exist_ok=True)

#         cache_key = hashlib.sha1(
#             json.dumps(
#                 {
#                     "label": label,
#                     "icon_path": str(src_icon.resolve()),
#                     "fill": fill,
#                     "border": border,
#                     "font_color": font_color,
#                     "target_size": target_size,
#                     "font_size": DIAGRAM_NODE_CARD_FONT_SIZE,
#                     "mtime": src_icon.stat().st_mtime,
#                 },
#                 sort_keys=True,
#             ).encode("utf-8")
#         ).hexdigest()

#         out_path = cache_dir / f"node_card_{cache_key}.png"
#         if out_path.exists():
#             return str(out_path)

#         width, height = target_size

#         card = Image.new("RGBA", target_size, (255, 255, 255, 0))
#         draw = ImageDraw.Draw(card)

#         # Rounded rectangle background
#         try:
#             draw.rounded_rectangle(
#                 [(2, 2), (width - 3, height - 3)],
#                 radius=18,
#                 fill=fill,
#                 outline=border,
#                 width=4,
#             )
#         except Exception:
#             draw.rectangle(
#                 [(2, 2), (width - 3, height - 3)],
#                 fill=fill,
#                 outline=border,
#                 width=4,
#             )

#         # Icon area
#         with Image.open(src_icon).convert("RGBA") as icon_img:
#             icon_max_w = int(width * 0.48)
#             icon_max_h = int(height * 0.42)
#             icon_img.thumbnail((icon_max_w, icon_max_h), Image.LANCZOS)

#             icon_x = (width - icon_img.width) // 2
#             icon_y = 22
#             card.paste(icon_img, (icon_x, icon_y), icon_img)

#         # Label area
#         # font = _load_card_font(size=20, bold=True)
#         # font = _load_card_font(size=23, bold=True)
#         font = _load_card_font(size=DIAGRAM_NODE_CARD_FONT_SIZE, bold=True)
#         label_clean = _clean_dot_label(label)
#         lines = _wrap_text_for_card(
#             draw=draw,
#             text=label_clean,
#             font=font,
#             max_width_px=width - 34,
#             max_lines=3,
#         )

#         line_heights = [_text_size(draw, line, font)[1] for line in lines]
#         total_text_h = sum(line_heights) + max(0, len(lines) - 1) * 6

#         text_y = height - total_text_h - 20

#         for line in lines:
#             tw, th = _text_size(draw, line, font)
#             tx = (width - tw) // 2
#             draw.text((tx, text_y), line, fill=font_color, font=font)
#             text_y += th + 6

#         card.save(out_path)
#         return str(out_path)

#     except Exception:
#         logger.exception("[ICON] Failed to create composite node card for label=%r icon=%s", label, icon_path)
#         return None

# def _build_styled_node_line(
#     node_ref: str,
#     label: str,
#     shape: str,
#     is_process_view: bool,
#     project_root: Path,
# ) -> str:
#     """
#     Create a styled Graphviz node line with pastel color and visible service icon.

#     IMPORTANT:
#     - Does NOT use Graphviz HTML <IMG> labels.
#     - Instead creates a composite PNG node card using Pillow.
#     - Graphviz receives image="...png", which is much more stable.
#     """
#     clean_node_ref = node_ref.strip()
#     clean_label = _clean_dot_label(label)

#     if is_process_view:
#         wrapped_label = wrap_graphviz_label(clean_label, width=14)
#     else:
#         wrapped_label = wrap_graphviz_label(clean_label, width=18)

#     style = get_pastel_style_for_label(clean_label)

#     if is_process_view:
#         process_fill_map = {
#             "oval": "#FFE5E5",
#             "diamond": "#FFF1CD",
#             "box": "#E5F0FF",
#             "cylinder": "#F1F3F4",
#             "folder": "#E8F0FE",
#             "hexagon": "#FEF7E0",
#             "octagon": "#FEF7E0",
#         }
#         fill = process_fill_map.get(shape, style["fill"])
#     else:
#         fill = style["fill"]

#     # Resolve icons for ALL views, including process view.
#     icon = resolve_icon_from_node_label(clean_label, project_root)

#     if icon:
#         logger.info(
#             "[ICON] Resolved icon for label=%r -> %s",
#             clean_label,
#             icon,
#         )

#         # Normalize raw icon first
#         normalized_icon = normalize_icon_for_graphviz(icon, target_size=(128, 72))

#         # Build full node card PNG: icon + label + pastel border
#         node_card = _make_composite_node_card(
#             label=clean_label,
#             icon_path=normalized_icon,
#             fill=fill,
#             border=style["border"],
#             font_color=style["font"],
#             # target_size=(340, 230),
#             target_size=DIAGRAM_NODE_CARD_SIZE,
#         )

#         if node_card:
#             safe_card_path = _safe_graphviz_image_path(node_card)

#             # 300x210 card ratio. Width/height are in inches.
#             # Increase slightly if icons/text look too small.
#             return (
#                 f'{clean_node_ref} ['
#                 f'shape=none, '
#                 f'label="", '
#                 f'image="{safe_card_path}", '
#                 f'imagescale=true, '
#                 f'fixedsize=true, '
#                 # f'width=2.45, '
#                 # f'height=1.72, '
#                 f'width={DIAGRAM_NODE_CARD_WIDTH_IN}, '
#                 f'height={DIAGRAM_NODE_CARD_HEIGHT_IN}, '
#                 f'margin=0'
#                 f'];'
#             )

#         logger.warning(
#             "[ICON] Icon resolved but node card generation failed for label=%r. Falling back to colored node.",
#             clean_label,
#         )

#     else:
#         logger.warning(
#             "[ICON] No icon resolved for label=%r. Falling back to colored node.",
#             clean_label,
#         )

#     # Fallback colored node when icon is missing or card generation fails.
#     attrs = [
#         f'shape={shape}',
#         'style="rounded,filled"',
#         f'fillcolor="{fill}"',
#         f'color="{style["border"]}"',
#         f'fontcolor="{style["font"]}"',
#         f'label="{_dot_attr_escape(wrapped_label)}"',
#         # 'fontsize=12',
#         f'fontsize={DIAGRAM_NODE_FONT_SIZE}',
#         'fontname="Helvetica-Bold"',
#         'penwidth=1.6',
#         'margin="0.10,0.07"',
#     ]

#     return f'{clean_node_ref} [{", ".join(attrs)}];'

# def cleanup_attr_commas(attr_text: str) -> str:
#     if not attr_text:
#         return ""
#     attr_text = re.sub(r"\s*,\s*,+", ", ", attr_text)
#     attr_text = re.sub(r"^\s*,\s*", "", attr_text)
#     attr_text = re.sub(r"\s*,\s*$", "", attr_text)
#     attr_text = re.sub(r"\s{2,}", " ", attr_text)
#     return attr_text.strip()


# def detect_process_view(dot_text: str) -> bool:
#     txt = dot_text.lower()
#     keywords = [
#         "start process", "end process", "flowchart", "process", "decision",
#         "invoke", "trigger", "extract", "decrypt", "save decrypted",
#         "consume decrypted", "rankdir=tb"
#     ]
#     return sum(1 for k in keywords if k in txt) >= 2


# def wrap_graphviz_label(text: str, width: int = 16) -> str:
#     """Inserts Graphviz newlines (\\n) into labels to prevent box overflow."""
#     if not text:
#         return ""
#     words = text.split()
#     lines = []
#     current_line = []
#     current_len = 0
    
#     for word in words:
#         # If adding this word exceeds width, push current line to lines
#         if current_len + len(word) > width and current_line:
#             lines.append(" ".join(current_line))
#             current_line = [word]
#             current_len = len(word)
#         else:
#             current_line.append(word)
#             current_len += len(word) + 1
            
#     if current_line:
#         lines.append(" ".join(current_line))
    
#     return "\\n".join(lines)

# def _cluster_style_for_name(cluster_name: str) -> Dict[str, str]:
#     """
#     Return very light background and bold label styling for Graphviz cluster boxes.
#     """
#     name = str(cluster_name or "").lower()

#     if any(x in name for x in ["gcp", "project", "cloud"]):
#         return {
#             "fill": "#F8FBFF",
#             "border": "#5F6368",
#             "font": "#202124",
#             "fontsize": "14",
#         }

#     if any(x in name for x in ["onprem", "on_prem", "on-prem", "teradata", "source"]):
#         return {
#             "fill": "#F7FCFC",
#             "border": "#5F6368",
#             "font": "#202124",
#             "fontsize": "13",
#         }

#     if any(x in name for x in ["observability", "logging", "monitoring", "support"]):
#         return {
#             "fill": "#FAF5FF",
#             "border": "#A142F4",
#             "font": "#202124",
#             "fontsize": "13",
#         }

#     if any(x in name for x in ["cicd", "ci_cd", "ci-cd", "deployment", "build", "terraform"]):
#         return {
#             "fill": "#FFF4F2",
#             "border": "#EA4335",
#             "font": "#202124",
#             "fontsize": "13",
#         }

#     if any(x in name for x in ["security", "kms", "secret"]):
#         return {
#             "fill": "#FFFBF0",
#             "border": "#FBBC04",
#             "font": "#202124",
#             "fontsize": "13",
#         }

#     if any(x in name for x in ["data", "target", "storage", "bucket"]):
#         return {
#             "fill": "#F8FBFF",
#             "border": "#5F6368",
#             "font": "#202124",
#             "fontsize": "13",
#         }

#     if any(x in name for x in ["compute", "function", "processing"]):
#         return {
#             "fill": "#F7FCF8",
#             "border": "#34A853",
#             "font": "#202124",
#             "fontsize": "13",
#         }

#     return {
#         "fill": "#FAFAFA",
#         "border": "#9AA0A6",
#         "font": "#202124",
#         "fontsize": "13",
#     }


# def _cluster_style_lines(cluster_name: str, indent: str = "  ") -> List[str]:
#     """
#     Build Graphviz cluster attribute lines.
#     """
#     style = _cluster_style_for_name(cluster_name)
#     cluster_font_size = max(int(style.get("fontsize", "13")), DIAGRAM_CLUSTER_FONT_SIZE)
#     return [
#         f'{indent}style="rounded,filled";',
#         f'{indent}fillcolor="{style["fill"]}";',
#         f'{indent}color="{style["border"]}";',
#         f'{indent}fontcolor="{style["font"]}";',
#         f'{indent}fontname="Helvetica-Bold";',
#         # f'{indent}fontsize={style["fontsize"]};',
#         f'{indent}fontsize={cluster_font_size};',
#         f'{indent}penwidth=1.6;',
#         f'{indent}margin=16;',
#         f'{indent}labeljust="c";',
#         f'{indent}labelloc="t";',
#     ]

# def _normalize_edge_operators_for_graph_type(dot_text: str) -> str:
#     """
#     Fix Graphviz edge operators based on graph type.

#     DOT rule:
#       - digraph must use ->
#       - graph must use --
#     """
#     if not isinstance(dot_text, str) or not dot_text.strip():
#         return dot_text

#     is_directed = bool(
#         re.search(
#             r"^\s*digraph\b",
#             dot_text,
#             flags=re.IGNORECASE,
#         )
#     )
#     is_undirected = bool(
#         re.search(
#             r"^\s*graph\b",
#             dot_text,
#             flags=re.IGNORECASE,
#         )
#     )

#     if not is_directed and not is_undirected:
#         return dot_text

#     out: list[str] = []
#     in_quotes = False
#     escape = False
#     i = 0

#     while i < len(dot_text):
#         ch = dot_text[i]

#         if ch == "\\" and not escape:
#             escape = True
#             out.append(ch)
#             i += 1
#             continue

#         if ch == '"' and not escape:
#             in_quotes = not in_quotes
#             out.append(ch)
#             i += 1
#             continue

#         escape = False

#         if not in_quotes:
#             two = dot_text[i:i + 2]

#             if is_directed and two == "--":
#                 out.append("->")
#                 i += 2
#                 continue

#             if is_undirected and two == "->":
#                 out.append("--")
#                 i += 2
#                 continue

#         out.append(ch)
#         i += 1

#     return "".join(out)

# def _normalize_dot_node_ref(value: str) -> str:
#     """
#     Normalize a DOT node reference for comparison.
#     """
#     if value is None:
#         return ""

#     text = str(value).strip()
#     text = text.strip(";")
#     text = text.strip()
#     text = text.strip('"').strip("'")
#     return text


# def _is_isolated_diagram_node_name_or_label(value: str) -> bool:
#     """
#     Nodes that must be visible but disconnected from runtime/data-flow.

#     Applies to:
#     - Cloud Logging
#     - Cloud Monitoring
#     - Observability
#     - Cloud Build
#     - Terraform
#     - CI/CD / deployment / IaC orchestration
#     """
#     text = str(value or "").lower()
#     text = text.replace("\\n", " ")
#     text = text.replace("\n", " ")
#     text = text.replace("_", " ")
#     text = text.replace("-", " ")
#     text = re.sub(r"\s+", " ", text).strip()

#     isolated_keywords = [
#         # Observability
#         "cloud logging",
#         "logging",
#         "cloud monitoring",
#         "monitoring",
#         "observability",
#         "logs",
#         "metrics",
#         "alerts",

#         # CI/CD / orchestration / IaC
#         "cloud build",
#         "terraform",
#         "ci/cd",
#         "ci cd",
#         "cicd",
#         "deployment",
#         "iac",
#         "orchestration",
#     ]

#     return any(keyword in text for keyword in isolated_keywords)


# def _extract_dot_edge_endpoints(line: str) -> Optional[Tuple[str, str]]:
#     """
#     Extract source and destination node refs from a simple DOT edge line.

#     Supports:
#       A -> B [label="x"];
#       A -- B [label="x"];
#       "A Node" -> "B Node";
#     """
#     if not isinstance(line, str):
#         return None

#     no_attrs = re.sub(r"\[.*?\]", "", line, flags=re.DOTALL).strip().rstrip(";")

#     match = re.match(
#         r'^\s*(?P<src>"[^"]+"|[A-Za-z_][A-Za-z0-9_.-]*)\s*(?P<op>->|--)\s*(?P<dst>"[^"]+"|[A-Za-z_][A-Za-z0-9_.-]*)',
#         no_attrs,
#     )

#     if not match:
#         return None

#     src = _normalize_dot_node_ref(match.group("src"))
#     dst = _normalize_dot_node_ref(match.group("dst"))

#     return src, dst

# def _edge_touches_isolated_node(
#     line: str,
#     isolated_node_ids: set[str],
#     node_label_lookup: Dict[str, str],
# ) -> bool:
#     """
#     Return True if an edge source/destination is an isolated node.

#     This is the hard guardrail that prevents arrows to/from:
#       - Cloud Logging
#       - Cloud Monitoring
#       - Observability
#       - Cloud Build
#       - Terraform
#     """
#     endpoints = _extract_dot_edge_endpoints(line)
#     if not endpoints:
#         return False

#     src, dst = endpoints

#     candidates = [src, dst]

#     for node_ref in candidates:
#         normalized_ref = _normalize_dot_node_ref(node_ref)

#         if normalized_ref in isolated_node_ids:
#             return True

#         label = node_label_lookup.get(normalized_ref, "")

#         if _is_isolated_diagram_node_name_or_label(normalized_ref):
#             return True

#         if _is_isolated_diagram_node_name_or_label(label):
#             return True

#     return False


# def normalize_dot_for_graphviz(
#     dot_text: str,
#     project_root: Path = PROJECT_ROOT
# ) -> Tuple[str, List[Tuple[str, str]]]:
#     """
#     Normalize LLM-generated DOT so Graphviz can render reliably.

#     Fixes:
#     - Escaped arrows such as -&gt; / -&amp;gt; into real ->
#     - Invalid digraph edges using -- converted to ->
#     - Weak node/edge styling replaced with renderer styling
#     - Cluster/subgraph styling injected
#     - Node labels converted to icon cards where possible
#     - Edge labels converted into external legend entries
#     - Observability / CI-CD / orchestration nodes kept visible but disconnected
#     """
#     original_dot = dot_text

#     dot_text = strip_code_fence(dot_text)
#     dot_text = unescape_graphviz_text(dot_text)

#     # ------------------------------------------------------------
#     # Normalize escaped line breaks into DOT-safe label breaks.
#     # ------------------------------------------------------------
#     dot_text = (
#         dot_text
#         .replace("<br/>", "\\n")
#         .replace("<br>", "\\n")
#         .replace("&lt;br/&gt;", "\\n")
#         .replace("&lt;br&gt;", "\\n")
#         .replace("&amp;lt;br/&amp;gt;", "\\n")
#         .replace("&amp;lt;br&amp;gt;", "\\n")
#         .replace("&amp;amp;lt;br/&amp;amp;gt;", "\\n")
#         .replace("&amp;amp;lt;br&amp;amp;gt;", "\\n")
#         .replace("&amp;amp;amp;lt;br/&amp;amp;amp;gt;", "\\n")
#         .replace("&amp;amp;amp;lt;br&amp;amp;amp;gt;", "\\n")
#     )

#     # ------------------------------------------------------------
#     # Normalize escaped arrows before parsing.
#     #
#     # IMPORTANT:
#     # Python source must contain real Graphviz operator "->",
#     # not HTML text "-&gt;".
#     # ------------------------------------------------------------
#     dot_text = (
#         dot_text
#         .replace("-&gt;", "->")
#         .replace("-&amp;gt;", "->")
#         .replace("-&amp;amp;gt;", "->")
#         .replace("-&amp;amp;amp;gt;", "->")
#         .replace("-&amp;amp;amp;amp;gt;", "->")
#         .replace("-&amp;amp;amp;amp;amp;gt;", "->")
#     )

#     # ------------------------------------------------------------
#     # Fix invalid edge operators.
#     #
#     # DOT rule:
#     # - digraph requires ->
#     # - graph requires --
#     #
#     # Example fixed:
#     #   digraph G { A -- B; }
#     # becomes:
#     #   digraph G { A -> B; }
#     # ------------------------------------------------------------
#     dot_text = _normalize_edge_operators_for_graph_type(dot_text)

#     is_directed_graph = bool(
#         re.search(
#             r"^\s*digraph\b",
#             dot_text,
#             flags=re.IGNORECASE,
#         )
#     )

#     is_process_view = detect_process_view(original_dot)

#     # ------------------------------------------------------------
#     # Force process views to render horizontally.
#     # ------------------------------------------------------------
#     if is_process_view:
#         dot_text = re.sub(
#             r"rankdir\s*=\s*(TB|TD|BT)\s*;",
#             "rankdir=LR;",
#             dot_text,
#             flags=re.IGNORECASE,
#         )

#         if "rankdir=" not in dot_text:
#             dot_text = dot_text.replace("{", "{\n  rankdir=LR;", 1)

#     dot_text = expand_grouped_edges(dot_text)
#     dot_text = _normalize_edge_operators_for_graph_type(dot_text)
#     dot_text = split_dot_statements(dot_text)

#     # ------------------------------------------------------------
#     # Keep attributes single-line.
#     # ------------------------------------------------------------
#     dot_text = re.sub(
#         r'\[([^\]]*)\]',
#         lambda m: '[' + m.group(1).replace('\n', ' ') + ']',
#         dot_text,
#         flags=re.DOTALL,
#     )

#     lines = [ln.rstrip() for ln in dot_text.splitlines() if ln.strip()]
#     new_lines: List[str] = []
#     legend_items: List[Tuple[str, str]] = []

#     # ------------------------------------------------------------
#     # Nodes that must be visible but disconnected.
#     #
#     # HARD RULE:
#     # No edges to/from:
#     # - Cloud Logging
#     # - Cloud Monitoring
#     # - Observability
#     # - Cloud Build
#     # - Terraform
#     # - CI/CD / orchestration / IaC nodes
#     # ------------------------------------------------------------
#     isolated_node_ids: set[str] = set()
#     node_label_lookup: Dict[str, str] = {}

#     # ------------------------------------------------------------
#     # Pre-scan node declarations before processing edges.
#     #
#     # This is required because DOT can contain edges before node declarations.
#     # Without this pre-scan, an edge to CloudLogging could be processed before
#     # CloudLogging is known to be isolated.
#     # ------------------------------------------------------------
#     for pre_scan_line in lines:
#         pre_scan_stripped = pre_scan_line.strip()

#         if "[" not in pre_scan_stripped or "]" not in pre_scan_stripped:
#             continue

#         if (
#             "->" in pre_scan_stripped
#             or "--" in pre_scan_stripped
#         ):
#             continue

#         pre, inner, _post = split_attr_block(pre_scan_line)
#         node_name = pre.strip()

#         if node_name in {"node", "edge", "graph"}:
#             continue

#         if _is_control_statement(node_name):
#             continue

#         clean_name = node_name.strip('"')
#         label = _extract_label_from_attrs(inner, clean_name)

#         normalized_node_id = _normalize_dot_node_ref(clean_name)
#         node_label_lookup[normalized_node_id] = label

#         if (
#             _is_isolated_diagram_node_name_or_label(normalized_node_id)
#             or _is_isolated_diagram_node_name_or_label(label)
#         ):
#             isolated_node_ids.add(normalized_node_id)

#     edge_colors = ["#E60000", "#1D70B8", "#28A197", "#F47738", "#4C2C92", "#6F72AF"]
#     edge_idx = 0
#     graph_defaults_inserted = False

#     for line in lines:
#         stripped = line.strip()

#         # ------------------------------------------------------------
#         # Graph start
#         # ------------------------------------------------------------
#         if stripped.startswith(("digraph ", "graph ")):
#             new_lines.append(line)
#             continue

#         if stripped == "{":
#             new_lines.append(line)

#             if not graph_defaults_inserted:
#                 new_lines.extend([
#                     '  graph [',
#                     '    bgcolor="white",',
#                     '    splines=ortho,',
#                     '    overlap=false,',
#                     '    outputorder="edgesfirst",',
#                     '    fontname="Helvetica-Bold",',
#                     f'    fontsize={DIAGRAM_GRAPH_FONT_SIZE},',
#                     '    ranksep=0.95,',
#                     '    nodesep=0.95,',
#                     '    pad=0.35',
#                     '  ];',
#                     '  node [shape=box, style="rounded,filled", fillcolor="#F8F9FA", color="#DADCE0", '
#                     f'fontname="Helvetica-Bold", fontsize={DIAGRAM_NODE_FONT_SIZE}, '
#                     'margin="0.14,0.09", penwidth=1.6];',
#                     f'  edge [fontname="Helvetica-Bold", fontsize={DIAGRAM_EDGE_FONT_SIZE}, '
#                     'penwidth=2.2, minlen=2, arrowsize=0.9, color="#5F6368"];',
#                 ])
#                 graph_defaults_inserted = True

#             continue

#         # ------------------------------------------------------------
#         # Subgraph / cluster line.
#         #
#         # Supports both:
#         #   subgraph cluster_source {
#         #   subgraph clustersource {
#         # ------------------------------------------------------------
#         if stripped.startswith("subgraph "):
#             new_lines.append(line)

#             cluster_match = re.search(
#                 r"subgraph\s+(cluster[A-Za-z0-9_.-]*)\s*\{",
#                 stripped,
#                 flags=re.IGNORECASE,
#             )

#             if cluster_match:
#                 cluster_name = cluster_match.group(1)
#                 base_indent_match = re.match(r"^(\s*)", line)
#                 base_indent = base_indent_match.group(1) if base_indent_match else ""
#                 attr_indent = base_indent + "  "

#                 new_lines.extend(
#                     _cluster_style_lines(
#                         cluster_name=cluster_name,
#                         indent=attr_indent,
#                     )
#                 )

#             continue

#         # ------------------------------------------------------------
#         # Replace weak default node/edge declarations emitted by LLM.
#         # ------------------------------------------------------------
#         if stripped.lower().startswith("node "):
#             new_lines.append(
#                 f'  node [shape=box, style="rounded,filled", fillcolor="#F8F9FA", '
#                 f'color="#DADCE0", fontname="Helvetica-Bold", fontsize={DIAGRAM_NODE_FONT_SIZE}, '
#                 # f'margin="0.10,0.07", penwidth=1.4];'
#                 f'margin="0.14,0.09", penwidth=1.6];'
#             )
#             continue

#         if stripped.lower().startswith("edge "):
#             new_lines.append(
#                 f'  edge [fontname="Helvetica-Bold", fontsize={DIAGRAM_EDGE_FONT_SIZE}, penwidth=2.0, '
#                 # 'minlen=1, arrowsize=0.8, color="#5F6368"];'
#                 'minlen=2, arrowsize=0.9, color="#5F6368"];'
#             )
#             continue

#         if stripped.lower().startswith("graph "):
#             new_lines.append(line)
#             continue

#         # ------------------------------------------------------------
#         # EDGE HANDLING
#         # ------------------------------------------------------------
#         if (
#             "->" in stripped
#             or "--" in stripped
#         ) and not stripped.lower().startswith(("node ", "edge ", "graph ")):

#             # Extra safety: if graph is directed, do not allow -- to reach Graphviz.
#             if is_directed_graph and "--" in line:
#                 line = _normalize_edge_operators_for_graph_type(line)
#                 stripped = line.strip()

#             # HARD RULE:
#             # Observability and CI/CD / orchestration nodes must remain visible
#             # but disconnected from runtime/data-flow.
#             if _edge_touches_isolated_node(
#                 line=line,
#                 isolated_node_ids=isolated_node_ids,
#                 node_label_lookup=node_label_lookup,
#             ):
#                 logger.info(
#                     "[DIAGRAM] Removed edge touching isolated node: %s",
#                     line,
#                 )
#                 continue

#             pre, inner, post = split_attr_block(line)

#             lbl_match = re.search(r'(xlabel|label)\s*=\s*"(.*?)"', inner)
#             lbl = lbl_match.group(2).strip() if lbl_match and lbl_match.group(2).strip() else ""

#             color = edge_colors[edge_idx % len(edge_colors)]
#             edge_idx += 1

#             if lbl:
#                 legend_items.append((color, lbl))

#             cleaned_inner = re.sub(
#                 r'(?:^|,)\s*(label|xlabel|fontcolor|labeldistance|labelangle|penwidth|color|minlen|arrowsize)'
#                 r'\s*=\s*("[^"]*"|<[^>]+>|&lt;[^&gt;]+&gt;|[^,\]]+)',
#                 '',
#                 inner,
#             )
#             cleaned_inner = cleanup_attr_commas(cleaned_inner)

#             attrs = f'color="{color}", penwidth=2.0, minlen=2, arrowsize=0.8'
#             if cleaned_inner:
#                 attrs = f"{cleaned_inner}, {attrs}"

#             attrs = cleanup_attr_commas(attrs)

#             if "[" in line:
#                 new_lines.append(f"{pre}[{attrs}]{post}")
#             else:
#                 new_lines.append(f"{line.rstrip(';')} [{attrs}];")

#             continue

#         # ------------------------------------------------------------
#         # NODE HANDLING WITH ATTRIBUTE BLOCK
#         #
#         # Example:
#         #   CloudFunction [label="Cloud Functions\nDecrypt File"];
#         # ------------------------------------------------------------
#         if "[" in stripped and "]" in stripped:
#             pre, inner, post = split_attr_block(line)
#             node_name = pre.strip()

#             if node_name == "node":
#                 new_lines.append(
#                     f'  node [shape=box, style="rounded,filled", fillcolor="#F8F9FA", '
#                     f'color="#DADCE0", fontname="Helvetica-Bold", fontsize={DIAGRAM_NODE_FONT_SIZE}, '
#                     # f'margin="0.10,0.07", penwidth=1.4];'
#                     f'margin="0.14,0.09", penwidth=1.6];'
#                 )
#                 continue

#             if node_name == "edge":
#                 new_lines.append(
#                     f'  edge [fontname="Helvetica-Bold", fontsize={DIAGRAM_EDGE_FONT_SIZE}, penwidth=2.0, '
#                     # f'minlen=1, arrowsize=0.8, color="#5F6368"];'
#                     f'minlen=2, arrowsize=0.9, color="#5F6368"];'
#                 )
#                 continue

#             if node_name == "graph":
#                 new_lines.append(line)
#                 continue

#             if _is_control_statement(node_name):
#                 new_lines.append(line)
#                 continue

#             clean_name = node_name.strip('"')

#             shape_match = re.search(r'shape\s*=\s*["\']?(\w+)["\']?', inner)
#             shape = shape_match.group(1) if shape_match else "box"

#             label = _extract_label_from_attrs(inner, clean_name)

#             normalized_node_id = _normalize_dot_node_ref(clean_name)
#             node_label_lookup[normalized_node_id] = label

#             if (
#                 _is_isolated_diagram_node_name_or_label(normalized_node_id)
#                 or _is_isolated_diagram_node_name_or_label(label)
#             ):
#                 isolated_node_ids.add(normalized_node_id)

#             new_lines.append(
#                 _build_styled_node_line(
#                     node_ref=node_name,
#                     label=label,
#                     shape=shape,
#                     is_process_view=is_process_view,
#                     project_root=project_root,
#                 )
#             )
#             continue

#         # ------------------------------------------------------------
#         # BARE NODE HANDLING
#         #
#         # Handles:
#         #   Terraform;
#         #   CloudBuild;
#         #   "Google Cloud Storage";
#         # ------------------------------------------------------------
#         bare_node_match = re.match(
#             r'^(?P<node_ref>"[^"]+"|[A-Za-z_][A-Za-z0-9_.-]*)\s*;?$',
#             stripped,
#         )

#         if bare_node_match and not _is_control_statement(stripped):
#             node_ref = bare_node_match.group("node_ref")
#             clean_name = node_ref.strip('"')

#             normalized_node_id = _normalize_dot_node_ref(clean_name)
#             node_label_lookup[normalized_node_id] = clean_name

#             if _is_isolated_diagram_node_name_or_label(clean_name):
#                 isolated_node_ids.add(normalized_node_id)

#             new_lines.append(
#                 _build_styled_node_line(
#                     node_ref=node_ref,
#                     label=clean_name,
#                     shape="box",
#                     is_process_view=is_process_view,
#                     project_root=project_root,
#                 )
#             )
#             continue

#         new_lines.append(line)

#     safe_dot = "\n".join(new_lines)

#     # ------------------------------------------------------------
#     # Safety net: style any cluster not already styled above.
#     # This catches cluster names generated dynamically by the LLM.
#     # ------------------------------------------------------------
#     def _inject_missing_cluster_style(match):
#         header = match.group(1)
#         cluster_name = match.group(2)

#         following = safe_dot[match.end():match.end() + 350]

#         if 'style="rounded,filled"' in following and "fillcolor=" in following:
#             return header

#         injected = "\n".join(
#             _cluster_style_lines(
#                 cluster_name=cluster_name,
#                 indent="  ",
#             )
#         )

#         return f"{header}\n{injected}"

#     safe_dot = re.sub(
#         r"(subgraph\s+(cluster[A-Za-z0-9_.-]*)\s*\{)",
#         _inject_missing_cluster_style,
#         safe_dot,
#         flags=re.IGNORECASE,
#     )

#     # Final safety before returning.
#     safe_dot = unescape_graphviz_text(safe_dot)
#     safe_dot = _normalize_edge_operators_for_graph_type(safe_dot)

#     return safe_dot, legend_items

# def _extract_graphviz_error_line(exc: Exception) -> Optional[int]:
#     """
#     Extract Graphviz syntax error line from exception text/stderr.

#     Example:
#         Error: diagram: syntax error in line 185
#     """
#     text_parts = [str(exc)]

#     stderr = getattr(exc, "stderr", None)
#     if stderr:
#         try:
#             if isinstance(stderr, bytes):
#                 text_parts.append(stderr.decode("utf-8", errors="ignore"))
#             else:
#                 text_parts.append(str(stderr))
#         except Exception:
#             pass

#     combined = "\n".join(text_parts)

#     match = re.search(
#         r"syntax error in line\s+(\d+)",
#         combined,
#         flags=re.IGNORECASE,
#     )

#     if not match:
#         return None

#     try:
#         return int(match.group(1))
#     except Exception:
#         return None


# def _log_dot_context(dot_source: str, line_number: Optional[int], window: int = 8) -> None:
#     """
#     Log DOT source lines around a Graphviz syntax error line.
#     """
#     if not isinstance(dot_source, str) or not line_number:
#         return

#     lines = dot_source.splitlines()

#     if line_number <= 0 or line_number > len(lines):
#         logger.error(
#             "[DOT] Requested error line %s is outside DOT line range. total_lines=%s",
#             line_number,
#             len(lines),
#         )
#         return

#     start = max(1, line_number - window)
#     end = min(len(lines), line_number + window)

#     logger.error("[DOT] Context around Graphviz error line %s:", line_number)

#     for idx in range(start, end + 1):
#         marker = ">>>" if idx == line_number else "   "
#         logger.error("[DOT] %s %04d: %s", marker, idx, lines[idx - 1])


# def _write_dot_debug_file(dot_source: str, prefix: str) -> Optional[Path]:
#     """
#     Persist DOT source for debugging.
#     """
#     try:
#         debug_dir = Path(tempfile.gettempdir()) / "aia_graphviz_failed_dot"
#         debug_dir.mkdir(parents=True, exist_ok=True)

#         digest = hashlib.sha1(
#             str(dot_source).encode("utf-8", errors="ignore")
#         ).hexdigest()[:12]

#         debug_path = debug_dir / f"{prefix}_{digest}.dot"
#         debug_path.write_text(str(dot_source), encoding="utf-8")

#         logger.error("DOT debug file written to: %s", debug_path)
#         return debug_path

#     except Exception:
#         logger.exception("Could not write DOT debug file.")
#         return None


# def _strip_dot_code_fences(dot_source: str) -> str:
#     """
#     Remove markdown fences if they accidentally reach renderer.
#     """
#     if not isinstance(dot_source, str):
#         return ""

#     dot = dot_source.strip()

#     dot = re.sub(
#         r"^```(?:dot|graphviz|gv)?\s*",
#         "",
#         dot,
#         flags=re.IGNORECASE,
#     )
#     dot = re.sub(r"\s*```$", "", dot)

#     return dot.strip()


# def _escape_dot_attr_value(value: Any) -> str:
#     """
#     Escape text for DOT quoted attributes.

#     Important:
#     - preserves existing Graphviz \\n
#     - converts raw newlines to \\n
#     - escapes quotes/backslashes safely
#     """
#     if value is None:
#         return ""

#     text = str(value)

#     text = text.replace("\r\n", "\n").replace("\r", "\n")

#     # Protect existing escaped newline markers before escaping backslashes.
#     text = text.replace("\\n", "__AIA_DOT_NEWLINE__")

#     text = text.replace("\\", "\\\\")
#     text = text.replace('"', r"\"")
#     text = text.replace("\n", r"\n")

#     text = text.replace("__AIA_DOT_NEWLINE__", r"\n")

#     return text


# def _sanitize_dot_quoted_attr_values(dot_source: str) -> str:
#     """
#     Sanitize quoted label/xlabel attributes.

#     Handles common model-generated issues:
#     - raw newlines inside label values
#     - unescaped double quotes inside label values
#     """
#     if not isinstance(dot_source, str) or not dot_source.strip():
#         return dot_source or ""

#     def repl(match: re.Match) -> str:
#         attr_name = match.group(1)
#         raw_value = match.group(2)
#         return f'{attr_name}="{_escape_dot_attr_value(raw_value)}"'

#     # Only touch label/xlabel. Do not touch image paths or other Graphviz attrs.
#     return re.sub(
#         r'\b(label|xlabel)\s*=\s*"(.*?)"',
#         repl,
#         dot_source,
#         flags=re.IGNORECASE | re.DOTALL,
#     )


# def _quote_unquoted_dot_label_attrs(dot_source: str) -> str:
#     """
#     Quote unquoted label/xlabel values.

#     Example:
#         A -> B [label=Secure Transfer];
#     becomes:
#         A -> B [label="Secure Transfer"];
#     """
#     if not isinstance(dot_source, str) or not dot_source.strip():
#         return dot_source or ""

#     def repl(match: re.Match) -> str:
#         attr = match.group(1)
#         value = match.group(2).strip()

#         if not value:
#             return match.group(0)

#         # Already quoted or HTML-like labels should be left untouched.
#         if value.startswith('"') or value.startswith("<"):
#             return match.group(0)

#         return f'{attr}="{_escape_dot_attr_value(value)}"'

#     return re.sub(
#         r'\b(label|xlabel)\s*=\s*([^,\]\n;]+)',
#         repl,
#         dot_source,
#         flags=re.IGNORECASE,
#     )


# def _sanitize_dot_common_syntax(dot_source: str) -> str:
#     """
#     Common DOT syntax cleanup before Graphviz rendering.

#     This is intentionally conservative and should run after
#     normalize_dot_for_graphviz().
#     """
#     if not isinstance(dot_source, str):
#         return ""

#     dot = _strip_dot_code_fences(dot_source)

#     # Decode common HTML entities.
#     dot = html.unescape(dot)

#     # Mermaid/Markdown style arrows.
#     dot = dot.replace("-->", "->")
#     dot = dot.replace("—>", "->")
#     dot = dot.replace("–>", "->")

#     # Smart quotes.
#     dot = dot.replace("“", '"').replace("”", '"')
#     dot = dot.replace("‘", "'").replace("’", "'")

#     # If model emitted graph but uses directed edges, make it digraph.
#     if re.search(r"^\s*graph\b", dot, flags=re.IGNORECASE) and "->" in dot:
#         dot = re.sub(
#             r"^\s*graph\b",
#             "digraph",
#             dot,
#             count=1,
#             flags=re.IGNORECASE,
#         )

#     # Quote unquoted labels before escaping quoted label values.
#     dot = _quote_unquoted_dot_label_attrs(dot)
#     dot = _sanitize_dot_quoted_attr_values(dot)

#     # Fix edge operator according to graph type.
#     dot = _normalize_edge_operators_for_graph_type(dot)

#     return dot.strip()


# def render_graphviz_to_png(text: str) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
#     """
#     Render Graphviz DOT text to PNG.

#     Behaviour:
#     - normalize input to DOT
#     - apply icon/styling normalization
#     - sanitize common DOT syntax issues
#     - render once
#     - retry once with additional sanitization
#     - log exact Graphviz syntax error context
#     - write final DOT that Graphviz actually received
#     """
#     tmp = None
#     safe_dot = None
#     safe_dot_retry = None
#     legend: List[Tuple[str, str]] = []

#     try:
#         dot_text = normalize_to_graphviz_dot(text)
#         if not dot_text:
#             return None

#         normalized_result = normalize_dot_for_graphviz(dot_text, PROJECT_ROOT)

#         if (
#             not isinstance(normalized_result, tuple)
#             or len(normalized_result) != 2
#         ):
#             logger.error(
#                 "normalize_dot_for_graphviz returned invalid result: %r",
#                 normalized_result,
#             )
#             return None

#         safe_dot, legend = normalized_result

#         # ------------------------------------------------------------
#         # IMPORTANT FIX:
#         # sanitize the actual DOT that will be sent to Graphviz.
#         # Previously _sanitize_dot_common_syntax existed but was not used.
#         # ------------------------------------------------------------
#         safe_dot = _sanitize_dot_common_syntax(safe_dot)

#         logger.info("PROJECT_ROOT resolved as: %s", PROJECT_ROOT)
#         logger.info("ICON_DIR resolved as: %s", ICON_DIR)
#         logger.info("Icon files found under ICON_DIR: %s", len(_iter_icon_files()))
#         logger.info("Final DOT sent to Graphviz:\n%s", safe_dot)

#         tmp = tempfile.mkdtemp()

#         try:
#             src = graphviz.Source(safe_dot, format="png")
#             png_path = src.render(filename="diagram", directory=tmp, cleanup=True)

#         except Exception as first_exc:
#             logger.exception(
#                 "Graphviz render failed on first attempt. "
#                 "Retrying after DOT syntax and edge-operator sanitization."
#             )

#             first_error_line = _extract_graphviz_error_line(first_exc)
#             if first_error_line:
#                 _log_dot_context(safe_dot, first_error_line)

#             _write_dot_debug_file(safe_dot, "first_attempt_failed_diagram")

#             safe_dot_retry = _normalize_edge_operators_for_graph_type(safe_dot)
#             safe_dot_retry = _sanitize_dot_common_syntax(safe_dot_retry)

#             retry_path = Path(tempfile.gettempdir()) / "aia_graphviz_retry.dot"
#             retry_path.write_text(safe_dot_retry, encoding="utf-8")
#             logger.error("Retry DOT written to: %s", retry_path)

#             try:
#                 src = graphviz.Source(safe_dot_retry, format="png")
#                 png_path = src.render(
#                     filename="diagram_retry",
#                     directory=tmp,
#                     cleanup=True,
#                 )

#             except Exception as retry_exc:
#                 logger.exception("Graphviz rendering failed on retry.")

#                 retry_error_line = _extract_graphviz_error_line(retry_exc)
#                 if retry_error_line:
#                     _log_dot_context(safe_dot_retry, retry_error_line)

#                 _write_dot_debug_file(safe_dot_retry, "retry_failed_diagram")

#                 return None

#         if not png_path or not Path(png_path).exists():
#             logger.error(
#                 "Graphviz render returned no PNG path or file does not exist: %s",
#                 png_path,
#             )

#             if safe_dot_retry:
#                 _write_dot_debug_file(safe_dot_retry, "missing_png_retry_diagram")
#             elif safe_dot:
#                 _write_dot_debug_file(safe_dot, "missing_png_diagram")
#             else:
#                 _write_dot_debug_file(str(text), "missing_png_original_diagram")

#             return None

#         return png_path, legend

#     except Exception:
#         logger.exception("Graphviz rendering failed")

#         # Write the final normalized DOT if available, not only original text.
#         if safe_dot_retry:
#             _write_dot_debug_file(safe_dot_retry, "failed_diagram_retry")
#         elif safe_dot:
#             _write_dot_debug_file(safe_dot, "failed_diagram_safe")
#         else:
#             _write_dot_debug_file(str(text), "failed_diagram_original")

#         return None

# def build_html_legend(items: List[Tuple[str, str]]) -> str:
#     # Flow legend intentionally removed
#     return ""


# def inline_image_token(path: Optional[str]) -> str:
#     if not path:
#         return "N/A"
#     abs_path = os.path.abspath(path).replace("\\", "/")
#     return f"IMAGE_TOKEN_START{abs_path}IMAGE_TOKEN_END"


# # ============================================================
# # PART 5: TABLE RENDERING
# # ============================================================

# METADATA_SECTIONS = set()


# def extract_metadata_sections(model: Any):
#     if not isinstance(model, type) or not issubclass(model, BaseModel):
#         return

#     for f_name, f_info in model.model_fields.items():
#         if f_info.json_schema_extra and f_info.json_schema_extra.get("is_metadata"):
#             METADATA_SECTIONS.add(f_name)

#         field_type = f_info.annotation
#         origin = get_origin(field_type)
#         if origin:
#             for a in get_args(field_type):
#                 extract_metadata_sections(a)
#         else:
#             extract_metadata_sections(field_type)


# extract_metadata_sections(HLDReport)


# def render_metadata_table(data: Dict[str, Any]) -> str:
#     if not data:
#         return "N/A\n\n"

#     keys = list(data.keys())
#     md = "\n\n| " + " | ".join(k.replace("_", " ").title() for k in keys) + " |\n"
#     md += "| " + " | ".join("---" for _ in keys) + " |\n"

#     row_values = []
#     for k in keys:
#         v = data.get(k, "")
#         formatted_val = clean_cell_text(v, apply_soft_breaks=False)
#         row_values.append(formatted_val)

#     md += "| " + " | ".join(row_values) + " |\n\n"
#     return md

# def render_dict_list_as_table(items: list) -> str:
#     if not items or not isinstance(items[0], dict):
#         return "N/A\n\n"

#     all_keys = []
#     for row in items:
#         for k in row.keys():
#             if k not in all_keys:
#                 all_keys.append(k)

#     md = "\n\n| " + " | ".join(k.replace("_", " ").title() for k in all_keys) + " |\n"
#     md += "| " + " | ".join("---" for _ in all_keys) + " |\n"

#     for row in items:
#         md += "| " + " | ".join(
#             clean_cell_text(row.get(k, ""), apply_soft_breaks=False) for k in all_keys
#         ) + " |\n"

#     return md + "\n\n"


# def build_legend_dot(legend_items: List[Tuple[str, str]]) -> str:
#     if not legend_items:
#         return ""
#     dot = [
#         "digraph Legend {",
#         '  rankdir=TB;',
#         '  graph [pad="0.03", nodesep="0.06", ranksep="0.06"];',

#         '  subgraph cluster_legend {',
#         '    label="Flow Legend";',
#         '    fontsize=10;',
#         '    fontname="Helvetica-Bold";',
#         '    color="#b0b8c1";',
#         '    style="rounded,dashed";',
#         '    margin=5;',

#         '    node [shape=box, style="rounded,filled", fillcolor="#ffffff", color="#b0b8c1", fontname="Helvetica-Bold", fontsize=8, margin="0.05,0.025", height=0.20];',

#         '    edge [penwidth=0.9, arrowsize=0.45];'
#     ]

#     if len(legend_items) > 1:
#         for idx in range(1, len(legend_items)):
#             dot.append(f'    "legend_src_{idx}" -> "legend_src_{idx+1}" [style=invis, weight=100, minlen=1];')

#     for idx, (color, label) in enumerate(legend_items, start=1):
#         s = f"legend_src_{idx}"
#         d = f"legend_dst_{idx}"
#         safe_label = str(label).replace('"', '\\"').replace("\n", " ")

#         dot.append(f'    "{s}" [label="", shape=point, width=0.01, height=0.01];')
#         dot.append(f'    "{d}" [label="{safe_label}"];')
        
#         # minlen=1 keeps the arrows short
#         dot.append(f'    "{s}" -> "{d}" [color="{color}", minlen=1];')
        
#         dot.append(f'    {{rank=same; "{s}"; "{d}"}}')

#     dot.append("  }")
#     dot.append("}")
#     return "\n".join(dot)

# def render_legend_diagram(legend_items):
#     legend_dot = build_legend_dot(legend_items)

#     if not legend_dot.strip():
#         return None

#     try:
#         src = graphviz.Source(legend_dot, format="png")
#         tmp = tempfile.mkdtemp()
#         png_path = src.render(filename="legend", directory=tmp, cleanup=True)
#         return png_path

#     except Exception:
#         logger.exception("Legend rendering failed; continuing without legend image.")
#         return None

# # ============================================================
# # PART 6: RECURSIVE VALUE RENDERER (PDF/MD/HTML)
# # ============================================================
# def _is_simple_metadata_dict(data: Dict[str, Any]) -> bool:
#     """
#     Generic guard:
#     Only render metadata table when top-level values are simple scalar-ish values.

#     If a dict contains list-of-dicts / complex nested display structures,
#     it should be rendered recursively instead of as one metadata row table.
#     """
#     if not isinstance(data, dict) or not data:
#         return False

#     for v in data.values():
#         if isinstance(v, list):
#             # list of dicts => definitely NOT simple metadata
#             if any(isinstance(i, dict) for i in v):
#                 return False
#         elif isinstance(v, dict):
#             # nested dict with nested list/dict content => not simple metadata
#             for nested_v in v.values():
#                 if isinstance(nested_v, (list, dict)):
#                     return False

#     return True

# def render_value(val: Any, section_key: Optional[str] = None) -> str:
#     if val is None:
#         return "N/A\n\n"

#     if isinstance(val, dict) and section_key in METADATA_SECTIONS and _is_simple_metadata_dict(val):
#         return render_metadata_table(val)

#     if isinstance(val, str):
#         # Detect diagram-like content before attempting render.
#         # This prevents raw DOT being dumped into the PDF when Graphviz fails.
#         is_diagram_text = normalize_to_graphviz_dot(val) is not None

#         res = render_graphviz_to_png(val)
#         if res:
#             path, legend = res

#             legend_img_path = render_legend_diagram(legend)
#             legend_img_token = ""

#             if legend_img_path:
#                 token = inline_image_token(legend_img_path)
#                 legend_img_token = (
#                     f'<div style="float: right; clear: both; margin-top: -20px;">\n\n'
#                     f'{token}\n\n'
#                     f'</div><div style="clear: both;"></div>'
#                 )

#             return inline_image_token(path) + "\n\n" + legend_img_token + "\n\n"

#         # IMPORTANT:
#         # If this was a diagram but Graphviz failed, do not print DOT source into PDF.
#         if is_diagram_text:
#             logger.error(
#                 "Diagram text detected but rendering failed. "
#                 "DOT source will not be printed into PDF. section_key=%s",
#                 section_key,
#             )
#             return (
#                 "**[Diagram rendering failed]**<br/>"
#                 "The diagram source was detected but could not be rendered by Graphviz. "
#                 "Please check renderer logs for the DOT syntax error.\n\n"
#             )

#         return format_paragraph_points(val) + "\n\n"

#     if isinstance(val, list):
#         if not val:
#             return "N/A\n\n"

#         # If the list contains diagram strings, render each item.
#         # If any one fails, render_value(item) will insert a controlled placeholder,
#         # not raw DOT text.
#         if all(isinstance(i, str) and normalize_to_graphviz_dot(i) for i in val):
#             return "".join(render_value(d, section_key=section_key) for d in val)

#         if all(isinstance(i, dict) for i in val):
#             return render_dict_list_as_table(val)

#         return "\n" + "\n".join(f"- {clean_cell_text(i)}" for i in val) + "\n\n"

#     if isinstance(val, dict):
#         md = ""

#         for k, v in val.items():
#             if k.lower() == "diagrams":
#                 md += render_value(v, section_key=section_key)
#             else:
#                 md += f"\n### {k.replace('_', ' ').title()}\n\n"
#                 md += render_value(v, section_key=k)

#         return md

#     return html.escape(str(val)) + "\n\n"

# # ============================================================
# # PART 7: NORMALIZATION
# # ============================================================
# def normalize_hld(d: Dict[str, Any]) -> Dict[str, Any]:
#     if not d:
#         return {}

#     # supporting_artefacts
#     sa = d.get("supporting_artefacts") or []  # 'or []' protects against None
#     if isinstance(sa, list):
#         d["supporting_artefacts"] = [
#             i if isinstance(i, dict) else {"title": str(i), "url": ""}
#             for i in sa
#         ]

#     # entity_summary
#     es = d.get("entity_summary")
#     if not es:
#         d["entity_summary"] = []
#     elif isinstance(es, str):
#         d["entity_summary"] = [{"entity_name": "TBC", "description": es}]
#     elif isinstance(es, dict):
#         d["entity_summary"] = [es]

#     # glossary
#     gl = d.get("glossary") or []  # Protects against None
#     if isinstance(gl, dict):
#         d["glossary"] = [{"term": k, "definition": v} for k, v in gl.items()]
#     elif isinstance(gl, list) and len(gl) > 0 and isinstance(gl[0], str):
#         new_gl = []
#         for i in range(0, len(gl), 2):
#             term = str(gl[i])
#             definition = str(gl[i+1]) if i + 1 < len(gl) else ""
#             new_gl.append({"term": term, "definition": definition})
#         d["glossary"] = new_gl

#     # data_design.subject_areas
#     data_design = d.get("data_design") or {}
#     if isinstance(data_design, dict):
#         subject_areas = data_design.get("subject_areas") or []

#         if isinstance(subject_areas, dict):
#             data_design["subject_areas"] = [subject_areas]
#         elif isinstance(subject_areas, str):
#             data_design["subject_areas"] = [
#                 {
#                     "name": subject_areas,
#                     "description": f"{subject_areas} subject area relevant to the solution.",
#                     "ownership": "Architecture Team",
#                     "domains": subject_areas,
#                 }
#             ]
#         elif isinstance(subject_areas, list):
#             normalized_subject_areas = []
#             for item in subject_areas:
#                 if isinstance(item, dict):
#                     normalized_subject_areas.append(item)
#                 elif isinstance(item, str):
#                     normalized_subject_areas.append(
#                         {
#                             "name": item,
#                             "description": f"{item} subject area relevant to the solution.",
#                             "ownership": "Architecture Team",
#                             "domains": item,
#                         }
#                     )
#             data_design["subject_areas"] = normalized_subject_areas

#         d["data_design"] = data_design

#     return d

# # ============================================================
# # PART 8: DOCX HELPER FUNCTIONS
# # ============================================================

# def set_docx_default_font(doc: Document, font_name: str = "Calibri", font_size: int = 10):
#     styles = doc.styles
#     if "Normal" in styles:
#         styles["Normal"].font.name = font_name
#         styles["Normal"].font.size = Pt(font_size)
#         styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), font_name)


# def set_paragraph_keep_with_next(paragraph, keep_next: bool = True, keep_lines: bool = True):
#     pPr = paragraph._p.get_or_add_pPr()

#     if keep_next:
#         keep_next_el = OxmlElement("w:keepNext")
#         pPr.append(keep_next_el)

#     if keep_lines:
#         keep_lines_el = OxmlElement("w:keepLines")
#         pPr.append(keep_lines_el)


# def set_table_no_row_split(table):
#     if table.rows:
#         trPr = table.rows[0]._tr.get_or_add_trPr()
#         tblHeader = OxmlElement("w:tblHeader")
#         tblHeader.set(qn("w:val"), "true")
#         trPr.append(tblHeader)

#     for row in table.rows:
#         trPr = row._tr.get_or_add_trPr()
#         cant_split = OxmlElement("w:cantSplit")
#         cant_split.set(qn("w:val"), "true")
#         trPr.append(cant_split)


# def get_docx_max_image_size(doc: Document) -> Tuple[float, float]:
#     try:
#         section = doc.sections[-1]
#         page_width = section.page_width.inches
#         page_height = section.page_height.inches
#         left_margin = section.left_margin.inches
#         right_margin = section.right_margin.inches
#         top_margin = section.top_margin.inches
#         bottom_margin = section.bottom_margin.inches

#         usable_width = max(4.5, page_width - left_margin - right_margin)
#         # usable_height = max(5.6, page_height - top_margin - bottom_margin - 1.1)
#         usable_height = max(5.0, page_height - top_margin - bottom_margin - 1.4)
#         return usable_width, usable_height
#     except Exception:
#         return 6.2, 8.0


# def add_picture_fit_to_page(doc: Document, image_path: str):
#     max_width_in, max_height_in = get_docx_max_image_size(doc)
#     width_in = max_width_in
#     height_in = None

#     try:
#         with Image.open(image_path) as img:
#             px_w, px_h = img.size
#             if px_w > 0 and px_h > 0:
#                 aspect = px_h / px_w
#                 predicted_h = width_in * aspect
#                 if predicted_h > max_height_in:
#                     height_in = max_height_in
#                     width_in = height_in / aspect
#     except Exception:
#         logger.warning("Could not inspect image size for %s; using width-only fit", image_path)

#     p = doc.add_paragraph()
#     p.alignment = WD_ALIGN_PARAGRAPH.CENTER
#     run = p.add_run()
#     if height_in is not None:
#         run.add_picture(image_path, width=Inches(width_in), height=Inches(height_in))
#     else:
#         run.add_picture(image_path, width=Inches(width_in))
#     set_paragraph_keep_with_next(p, keep_next=False, keep_lines=True)

# def add_docx_paragraph_from_text(doc: Document, text: str):
#     if not text:
#         doc.add_paragraph("N/A")
#         return

#     text = _renderer_safe_plain_text(text)

#     p = doc.add_paragraph()
#     lines = text.split("\n")

#     for idx, line in enumerate(lines):
#         if idx > 0:
#             p.add_run().add_break()
#         p.add_run(line)


# def add_docx_metadata_table(doc: Document, data: Dict[str, Any]):
#     if not data:
#         doc.add_paragraph("N/A")
#         return

#     table = doc.add_table(rows=2, cols=len(data))
#     table.style = "Table Grid"

#     for idx, (k, v) in enumerate(data.items()):
#         table.cell(0, idx).text = k.replace("_", " ").title()
#         table.cell(1, idx).text = _display_text_for_renderer(v, multiline=True)

#     set_table_no_row_split(table)
#     doc.add_paragraph("")


# def add_docx_table(doc: Document, items: List[Dict[str, Any]]):
#     if not items:
#         doc.add_paragraph("N/A")
#         return

#     all_keys = []
#     for row in items:
#         for k in row.keys():
#             if k not in all_keys:
#                 all_keys.append(k)

#     table = doc.add_table(rows=1, cols=len(all_keys))
#     table.style = "Table Grid"

#     hdr_cells = table.rows[0].cells
#     for i, k in enumerate(all_keys):
#         hdr_cells[i].text = k.replace("_", " ").title()

#     for row in items:
#         row_cells = table.add_row().cells
#         for i, k in enumerate(all_keys):
#             val = row.get(k, "")
#             row_cells[i].text = _display_text_for_renderer(val, multiline=True)

#     set_table_no_row_split(table)
#     doc.add_paragraph("")


# def add_docx_diagram_with_legend(doc: Document, img_path: str, legend: List[Tuple[str, str]]):
#     add_picture_fit_to_page(doc, img_path)
#     add_flow_legend_docx(doc, legend)
    
# def add_docx_value(doc: Document, val: Any, section_key: Optional[str] = None):
#     if val is None:
#         doc.add_paragraph("N/A")
#         return

#     if isinstance(val, dict) and section_key in METADATA_SECTIONS and _is_simple_metadata_dict(val):
#         add_docx_metadata_table(doc, val)
#         return

#     if isinstance(val, str):
#         is_diagram_text = normalize_to_graphviz_dot(val) is not None

#         res = render_graphviz_to_png(val)
#         if res:
#             img_path, legend = res
#             try:
#                 add_docx_diagram_with_legend(doc, img_path, legend)
#             except Exception:
#                 logger.exception("Failed to embed diagram in DOCX")
#                 doc.add_paragraph("[Diagram failed]")
#             return

#         if is_diagram_text:
#             logger.error(
#                 "Diagram text detected but rendering failed. "
#                 "DOT source will not be printed into DOCX. section_key=%s",
#                 section_key,
#             )
#             doc.add_paragraph(
#                 "[Diagram rendering failed] The diagram source was detected but could not be rendered by Graphviz. "
#                 "Please check renderer logs for the DOT syntax error."
#             )
#             return

#         add_docx_paragraph_from_text(doc, val)
#         return

#     if isinstance(val, list):
#         if not val:
#             doc.add_paragraph("N/A")
#             return

#         if all(isinstance(i, str) and normalize_to_graphviz_dot(i) for i in val):
#             for item in val:
#                 add_docx_value(doc, item, section_key=section_key)
#             return

#         if all(isinstance(i, dict) for i in val):
#             add_docx_table(doc, val)
#             return

#         for item in val:
#             doc.add_paragraph(str(item), style="List Bullet")
#         doc.add_paragraph("")
#         return

#     if isinstance(val, dict):
#         items = list(val.items())
#         for k, v in items:
#             hp = doc.add_heading(k.replace("_", " ").title(), level=3)
#             set_paragraph_keep_with_next(hp, keep_next=True, keep_lines=True)
#             add_docx_value(doc, v, section_key=k)
#         return

#     doc.add_paragraph(str(val))

# def add_flow_legend_docx(doc: Document, legend_items: List[Tuple[str, str]]):
#     if not legend_items:
#         return

#     # doc.add_paragraph("Flow Legend", style="Heading 3")
#     legend_heading = doc.add_paragraph()
#     legend_run = legend_heading.add_run("Flow Legend")
#     legend_run.bold = True
#     legend_run.font.size = Pt(9)

#     table = doc.add_table(rows=1, cols=2)
#     table.style = "Table Grid"

#     hdr = table.rows[0].cells
#     hdr[0].text = "Flow"
#     hdr[1].text = "Description"
#     for cell in hdr:
#         for paragraph in cell.paragraphs:
#             for run in paragraph.runs:
#                 run.font.size = Pt(8)
#                 run.bold = True

#     for color, label in legend_items:
#         row = table.add_row().cells
#         # row[0].text = "■"
        
#         p = row[0].paragraphs[0]
#         run = p.add_run("■")
#         run.font.color.rgb = None  # reset
#         from docx.shared import RGBColor
#         hex_color = color.lstrip("#")
#         run.font.color.rgb = RGBColor.from_string(hex_color.upper())
#         row[1].text = label
#         for cell in row:
#             for paragraph in cell.paragraphs:
#                 for run in paragraph.runs:
#                     run.font.size = Pt(8)

#     doc.add_paragraph("")


# def add_docx_toc(doc: Document):
#     p = doc.add_paragraph()
#     run = p.add_run()

#     # Begin field
#     fld_char_begin = OxmlElement("w:fldChar")
#     fld_char_begin.set(qn("w:fldCharType"), "begin")
#     run._r.append(fld_char_begin)

#     # TOC instruction
#     instr_text = OxmlElement("w:instrText")
#     instr_text.set(qn("xml:space"), "preserve")
#     instr_text.text = 'TOC \\o "1-3" \\h \\z \\u'
#     run._r.append(instr_text)

#     # ✅ REQUIRED: field separator
#     fld_char_separate = OxmlElement("w:fldChar")
#     fld_char_separate.set(qn("w:fldCharType"), "separate")
#     run._r.append(fld_char_separate)

#     # End field
#     fld_char_end = OxmlElement("w:fldChar")
#     fld_char_end.set(qn("w:fldCharType"), "end")
#     run._r.append(fld_char_end)

# def enable_docx_update_fields(doc: Document):
#     settings = doc.settings._element
#     update = OxmlElement("w:updateFields")
#     update.set(qn("w:val"), "true")
#     settings.append(update)


# def _normalize_selected_sections(raw_sections: Any) -> set[str]:
#     """
#     Normalize selected sections from state into a lowercase set.

#     Supports:
#     - list[str]
#     - comma-separated string
#     - JSON string list
#     - Python-list-like string: "['A', 'B']"
#     - HTML escaped names like Data Design &amp; Models
#     """
#     if raw_sections is None:
#         return set()

#     items = []

#     if isinstance(raw_sections, list):
#         items = raw_sections

#     elif isinstance(raw_sections, str):
#         raw = html.unescape(raw_sections.strip())

#         if not raw:
#             return set()

#         if raw.startswith("[") and raw.endswith("]"):
#             try:
#                 parsed = json.loads(raw)
#                 if isinstance(parsed, list):
#                     items = parsed
#             except Exception:
#                 try:
#                     import ast
#                     parsed = ast.literal_eval(raw)
#                     if isinstance(parsed, list):
#                         items = parsed
#                 except Exception:
#                     items = [
#                         s.strip().strip("'").strip('"')
#                         for s in raw.split(",")
#                         if s.strip()
#                     ]
#         else:
#             items = [s.strip() for s in raw.split(",") if s.strip()]

#     else:
#         return set()

#     normalized = set()

#     for item in items:
#         text = html.unescape(str(item or "")).strip()
#         text = text.strip("[]").strip().strip("'").strip('"').strip()

#         if text:
#             normalized.add(text.lower())

#     return normalized


# def _should_include_section(
#     field_name: str,
#     field_info: Any,
#     selected_sections_set: set[str],
# ) -> bool:
#     """
#     Decide whether a top-level HLD schema section should be rendered.

#     No hardcoding:
#     - matches schema field name
#     - matches schema title
#     - matches normalized schema title with &amp; converted to &
#     """
#     if not selected_sections_set:
#         return True

#     title = (field_info.title or field_name.replace("_", " ").title()).strip()

#     candidates = {
#         field_name.strip().lower(),
#         title.strip().lower(),
#         html.unescape(title).strip().lower(),
#     }

#     return bool(candidates.intersection(selected_sections_set))

# def build_docx(
#     data: Dict[str, Any],
#     docx_path: str,
#     selected_sections_set: Optional[set[str]] = None
# ):
#     doc = Document()
#     set_docx_default_font(doc, font_name="Calibri", font_size=10)

#     for section in doc.sections:
#         section.top_margin = Inches(0.65)
#         section.bottom_margin = Inches(0.65)
#         section.left_margin = Inches(0.7)
#         section.right_margin = Inches(0.7)

#     title_p = doc.add_heading("Universal High Level Design (HLD)", level=1)
#     title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
#     set_paragraph_keep_with_next(title_p, keep_next=True, keep_lines=True)
#     ICON_DIR_LOGO= PROJECT_ROOT / "assets" / "branding"
#     logo_path = ICON_DIR_LOGO / "doc_logo.png"

#     if logo_path.exists():
#         logo_p = doc.add_paragraph()
#         logo_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
#         logo_p.paragraph_format.space_before = Pt(24)

#         logo_run = logo_p.add_run()
#         logo_run.add_picture(str(logo_path), width=Inches(2.0))
#     else:
#         logger.warning("Logo not found at %s", logo_path)

#     # Title page -> TOC -> content
#     doc.add_page_break()
#     add_docx_toc(doc)
#     doc.add_page_break()
#     enable_docx_update_fields(doc)

#     first = True
#     for f_name, f_info in HLDReport.model_fields.items():
#         title = f_info.title or f_name.replace("_", " ").title()

#         if not _should_include_section(f_name, f_info, selected_sections_set or set()):
#             logger.info("Skipping unselected DOCX section: %s (%s)", title, f_name)
#             continue

#         if not first:
#             doc.add_page_break()
#         first = False

#         hp = doc.add_heading(title, level=2)
#         set_paragraph_keep_with_next(hp, keep_next=True, keep_lines=True)
#         add_docx_value(doc, data.get(f_name), f_name)

#     doc.save(docx_path)
# # ============================================================
# # PART 9: PDF / HTML GENERATION
# # ============================================================

# def image_token_to_html(match):
#     path = match.group(1)
#     try:
#         with open(path, "rb") as f:
#             enc = base64.b64encode(f.read()).decode()

#         return (
#             '<div class="diagram-wrap">'
#             f'<img src="data:image/png;base64,{enc}" alt="Diagram"/>'
#             '</div>'
#         )
#     except Exception:
#         logger.exception("Failed to inline image into PDF/HTML")
#         return "<p>[Image Error]</p>"


# def build_html_content(md_master: str) -> str:
#     # Convert page-break token after markdown conversion to avoid markdown escaping it
#     md_html = md_master.replace("PAGE_BREAK_TOKEN", "\n\n[[PAGE_BREAK]]\n\n")

#     md_html = re.sub(
#         r'IMAGE_TOKEN_START(.*?)IMAGE_TOKEN_END',
#         image_token_to_html,
#         md_html
#     )

#     # html_body = markdown2.markdown(md_html, extras=["tables", "fenced-code-blocks"])
    
#     html_body = markdown2.markdown(
#         md_html,
#         extras=["tables", "fenced-code-blocks", "toc"]
#     )
# # 2. Extract the TOC HTML and manually replace the placeholder
#     toc_content = getattr(html_body, "toc_html", "") or ""    

# # markdown2 might wrap the placeholder in <p> tags, so check for both
#     html_body = str(html_body).replace("<p>[[toc]]</p>", toc_content).replace("[[toc]]", toc_content)
    
#     html_body = html_body.replace("<p>[[PAGE_BREAK]]</p>", '<div class="page-break"></div>')

#     # logo_path = f"{ICON_DIR}/doc_logo.png"
#     ICON_DIR_LOGO= PROJECT_ROOT / "assets" / "branding"
#     logo_path = ICON_DIR_LOGO / "doc_logo.png"
#     with open(logo_path, "rb") as image_file:
#         encoded_string = base64.b64encode(image_file.read()).decode()
#         b64_logo = f"data:image/png;base64,{encoded_string}"
#         # <img src="{b64_logo}" alt="Universal Logo" />
#     html_full = f"""
#     <html>
#       <head>
#         <meta charset="utf-8"/>
#         <title>Universal High Level Design (HLD)</title>
#         <style>
#           @page {{
#             size: A4;
#             margin: 1.25cm;
#           }}

#           body {{
#             font-family: Helvetica, Arial, sans-serif;
#             font-size: 10pt;
#             color: #222;
#             margin: 0;
#             padding: 0;
#           }}

#           h1 {{
#             color: #E60000;
#             border-bottom: 1px solid #E60000;
#             padding-bottom: 4px;
#             margin-top: 0;
#             page-break-after: avoid;
#           }}

#           h2 {{
#             color: #E60000;
#             border-bottom: 1px solid #E60000;
#             padding-bottom: 3px;
#             margin-top: 0;
#             page-break-after: avoid;
#           }}

#           h3 {{
#             color: #333;
#             margin-top: 12px;
#             page-break-after: avoid;
#           }}

#           .page-break {{
#             page-break-before: always;
#             height: 0;
#             margin: 0;
#             padding: 0;
#           }}
#           p, ul, ol {{
#                     line-height: 1.35;
#                     page-break-inside: avoid;
#                     overflow-wrap: anywhere;
#                     word-break: break-word;
#                     white-space: normal;
#                 }}        

#           table {{
#             width: 100%;
#             border-collapse: collapse;
#             margin: 10px 0 14px 0;
#             table-layout: fixed;
#           }}

#           thead {{
#             display: table-header-group;
#           }}

#           tr {{
#             page-break-inside: avoid;
#           }}

#           th {{
#             background: #f4f7f9;
#             padding: 6px;
#             border: 1px solid #ccc;
#             font-size: 9pt;
#             word-wrap: break-word;
#             overflow-wrap: anywhere;
#             word-break: break-all;
#             white-space: normal;
#           }}

#           td {{
#             border: 1px solid #ccc;
#             padding: 6px;
#             font-size: 8.5pt;
#             vertical-align: top;
#             word-wrap: break-word;
#             overflow-wrap: anywhere;
#             word-break: break-all;
#             white-space: normal;
#           }}
#           .diagram-wrap {{
#             width: 100%;
#             text-align: center;
#             margin: 10px 0 10px 0;
#             page-break-inside: avoid;
#           }}

#           .diagram-wrap img {{
#             width: auto;
#             height: auto;
#             max-width: 100%;
#             max-height: {DIAGRAM_PDF_MAX_HEIGHT_PX}px;
#             object-fit: contain;
#             display: inline-block;
#           }}

#           pre, code {{
#             white-space: pre-wrap;
#             word-wrap: break-word;
#           }}
#         </style>
#       </head>
#       <body>
#         {html_body}
#       </body>
#     </html>
#     """
#     return html_full


# def build_pdf(md_master: str, pdf_path: str, html_path: Optional[str] = None):
#     html_full = build_html_content(md_master)

#     if html_path:
#         Path(html_path).write_text(html_full, encoding="utf-8")

#     with open(pdf_path, "wb") as f:
#         result = pisa.CreatePDF(BytesIO(html_full.encode("utf-8")), dest=f)

#     if result.err:
#         raise RuntimeError("PDF generation failed via xhtml2pdf")

# def wrap_graphviz_label(text: str, width: int = 16) -> str:
#     """
#     Inserts Graphviz newlines (\\n) into labels to prevent box overflow.
    
#     Args:
#         text: The raw label string to be wrapped.
#         width: The maximum character count per line before wrapping.
        
#     Returns:
#         A string with \\n characters inserted at word boundaries.
#     """
#     if not text:
#         return ""

#     # 1. Clean and standardize the input text
#     # Replace existing literal or escaped newlines with spaces to re-flow
#     text = str(text).replace("\\n", " ").replace("\n", " ")
#     words = text.split()
    
#     if not words:
#         return ""

#     lines: List[str] = []
#     current_line: List[str] = []
#     current_len = 0
    
#     # 2. Greedy wrapping logic
#     for word in words:
#         # Check if adding this word (plus a space) exceeds the width
#         # We only wrap if the current_line isn't empty (avoids empty first lines)
#         if current_len + len(word) > width and current_line:
#             lines.append(" ".join(current_line))
#             current_line = [word]
#             current_len = len(word)
#         else:
#             current_line.append(word)
#             # Add length of word plus 1 for the space
#             current_len += len(word) + 1
            
#     # 3. Append the final remaining line
#     if current_line:
#         lines.append(" ".join(current_line))
    
#     # 4. Join with Graphviz-friendly double-backslash newlines
#     return "\\n".join(lines)

# # --- Example Usage for doc_render_tools.py ---
# # label = wrap_graphviz_label("This is a very long architectural component name", width=14)
# # Result: "This is a very\\nlong\\narchitectural\\ncomponent\\nname"

# def build_edge_legend_subgraph(legend_items: List[Tuple[str, str]]) -> List[str]:
#     """
#     Build a legend cluster with colored sample arrows and their descriptions.
#     Each item is (color, label).
#     """
#     if not legend_items:
#         return []

#     lines = [
#         '  subgraph cluster_edge_legend {',
#         '    label="Flow Legend";',
#         '    fontsize=11;',
#         '    fontname="Helvetica-Bold";',
#         '    color="#d9d9d9";',
#         '    style="rounded,dashed";',
#         '    rankdir=TB;',
#         '    margin=12;',
#     ]

#     for idx, (color, label) in enumerate(legend_items, start=1):
#         s = f"legend_src_{idx}"
#         d = f"legend_dst_{idx}"

#         # Escape label safely for DOT
#         safe_label = str(label).replace('"', '\\"').replace("\n", " ")

#         lines.append(
#             f'    "{s}" [label="", shape=point, width=0.01, height=0.01, fixedsize=true];'
#         )
#         lines.append(
#             f'    "{d}" [label="{safe_label}", shape=box, style="rounded,filled", '
#             f'fillcolor="#ffffff", color="#cfcfcf", fontname="Helvetica-Bold", '
#             f'fontsize=10, margin="0.10,0.06"];'
#         )
#         # IMPORTANT: real Graphviz arrow operator
#         lines.append(
#             f'    "{s}" -> "{d}" [color="{color}", penwidth=2.2, arrowsize=0.8];'
#         )

#     lines.append("  }")
#     return lines

# ## Function for GCS File Upload
# def upload_to_gcs(
#     bucket_name: str,
#     local_file_path: str,
#     gcs_destination_path: str
# ) -> str:
#     """
#     Upload a local file to GCS and return the GCS URI.
#     """
#     client = storage.Client()
#     bucket = client.bucket(bucket_name)
#     blob = bucket.blob(gcs_destination_path)

#     blob.upload_from_filename(local_file_path)

#     return f"gs://{bucket_name}/{gcs_destination_path}"



# from datetime import timedelta
# import logging
# from typing import Optional

# from google.cloud import storage
# from google.auth import default
# from google.auth.credentials import Credentials

# logger = logging.getLogger(__name__)


# def generate_signed_gcs_url(
#     bucket_name: str,
#     gcs_object_path: str,
#     expires_minutes: int = 30
# ) -> Optional[str]:
#     """
#     Generate a time-limited signed download URL for a GCS object.

#     ✅ Works when using a Service Account (has private key)
#     ✅ Gracefully returns None when credentials cannot sign (user OAuth / ADC)
#     ✅ NEVER raises and breaks the pipeline
#     """

#     try:
#         # Obtain credentials explicitly
#         credentials, _ = default()

#         # Check whether credentials support signing
#         if not hasattr(credentials, "sign_bytes"):
#             logger.warning(
#                 "Signed URL generation skipped: current credentials "
#                 "do not support signing (no private key present)."
#             )
#             return None

#         client = storage.Client(credentials=credentials)
#         bucket = client.bucket(bucket_name)
#         blob = bucket.blob(gcs_object_path)

#         signed_url = blob.generate_signed_url(
#             expiration=timedelta(minutes=expires_minutes),
#             method="GET"
#         )

#         return signed_url

#     except Exception as e:
#         # ✅ Absolutely critical: never let this crash rendering
#         logger.exception(
#             "Failed to generate signed GCS URL for %s/%s",
#             bucket_name,
#             gcs_object_path
#         )
#         return None


# def can_sign_urls(creds: Credentials) -> bool:
#     return hasattr(creds, "sign_bytes")


# ### Render docs
# def render_hld_documents(report: Dict[str, Any], tool_context=None) -> Dict[str, Any]:
#     try:
#         selected_sections_set: set[str] = set()

#         # --------------------------------------------------
#         # 1) Load HLD payload from session state using centralized keys
#         #    Prefer KEY_HLD_REPORT_JSON
#         #    Fallback defensively to section-wise assembly if needed
#         # --------------------------------------------------
#         state = {}

#         if tool_context:
#             if hasattr(tool_context, "session") and getattr(tool_context, "session", None):
#                 state = tool_context.session.state or {}
#             elif hasattr(tool_context, "state"):
#                 state = tool_context.state or {}
#             # Main assembled/final HLD
            
#             if state:
#                 state_hld = state.get(KEY_HLD_REPORT_JSON)

#             if state_hld:
#                 if isinstance(state_hld, str):
#                     try:
#                         report = json.loads(state_hld)
#                     except Exception:
#                         logger.warning(
#                             "session.state[%r] exists but is not a valid JSON string",
#                             KEY_HLD_REPORT_JSON,
#                         )
#                 elif isinstance(state_hld, dict):
#                     report = state_hld

#             else:
#                 # Defensive fallback: assemble from section-wise committed state
#                 try:
#                     section_report = validate_required_hld_sections(state)
#                     if section_report.get("all_present"):
#                         report = assemble_hld_from_state(state)
#                         logger.info("✅ Render tool assembled HLD from section-wise state fallback.")
#                 except Exception:
#                     logger.exception(
#                         "Failed to assemble HLD from section-wise state inside render tool fallback."
#                     )

#             # Selected sections
#             # raw_sections = state.get(KEY_SELECTED_SECTIONS, "")
#             raw_sections = (
#                 state.get(KEY_RENDER_SELECTED_SECTIONS)
#                 or state.get(KEY_SELECTED_SECTIONS)
#                 or ""
#             )

#             selected_sections_set = _normalize_selected_sections(raw_sections)

#             logger.info(
#                 "[RENDER] Raw selected sections from state: %r",
#                 raw_sections,
#             )
#             logger.info(
#                 "[RENDER] Normalized selected sections for filtering: %s",
#                 sorted(selected_sections_set) if selected_sections_set else "ALL",
#             )

#         # --------------------------------------------------
#         # 2) Normalize + validate final report
#         # --------------------------------------------------
#         report = normalize_hld(dynamic_inflate(HLDReport, report))

#         logger.info(
#             "Normalized subject_areas: %s",
#             report.get("data_design", {}).get("subject_areas")
#         )

#         data = HLDReport.model_validate(report).model_dump()

#         # --------------------------------------------------
#         # 3) Build Markdown master document
#         # --------------------------------------------------
#         # logo_path = ICON_DIR / "doc_logo.png"
#         ICON_DIR_LOGO= PROJECT_ROOT / "assets" / "branding"
#         logo_path = ICON_DIR_LOGO / "doc_logo.png"

#         try:
#             with open(logo_path, "rb") as image_file:
#                 encoded_string = base64.b64encode(image_file.read()).decode()
#                 b64_logo = f"data:image/png;base64,{encoded_string}"
#         except FileNotFoundError:
#             b64_logo = ""

#         logo_html = ""
#         if b64_logo:
#             logo_html = (
#                 f'<img src="{b64_logo}" alt="Universal Logo" '
#                 f'style="max-height: 700px; max-width: 100%; margin-bottom: 20px;" />'
#             )

#         md_master = (
#             f'<div style="text-align: center; page-break-inside: avoid;">\n'
#             f'  {logo_html}\n'
#             f'  <h1 style="color: #E60000; border-bottom: 1px solid #E60000; '
#             f'padding-bottom: 4px; margin-top: 0;">Universal High Level Design (HLD)</h1>\n'
#             f'</div>\n\n'
#             "PAGE_BREAK_TOKEN\n\n"
#             "## Table of Contents\n\n[[toc]]\n\n"
#             "PAGE_BREAK_TOKEN\n\n"
#         )

#         first = True
#         for f_name, f_info in HLDReport.model_fields.items():
#             title = f_info.title or f_name.replace("_", " ").title()

#             if not _should_include_section(f_name, f_info, selected_sections_set):
#                 logger.info("Skipping unselected Markdown/PDF/HTML section: %s (%s)", title, f_name)
#                 continue

#             if not first:
#                 md_master += "\n\nPAGE_BREAK_TOKEN\n\n"
#             first = False

#             md_master += f"## {title}\n\n{render_value(data.get(f_name), f_name)}"

#         # --------------------------------------------------
#         # 4) Output paths
#         # --------------------------------------------------
#         details = data.get("project_details") or {}
#         project_name = details.get("project_name") or "hld"
#         safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", project_name).strip("_").lower()

#         out_dir = Path("generated_docs")
#         out_dir.mkdir(exist_ok=True)

#         pdf_path = str(out_dir / f"{safe_name}.pdf")
#         docx_path = str(out_dir / f"{safe_name}.docx")
#         md_path = str(out_dir / f"{safe_name}.md")
#         html_path = str(out_dir / f"{safe_name}.html")

#         # --------------------------------------------------
#         # 5) Write docs
#         # --------------------------------------------------
#         Path(md_path).write_text(md_master, encoding="utf-8")
#         build_pdf(md_master, pdf_path, html_path=html_path)
#         build_docx(data, docx_path, selected_sections_set)

#         # --------------------------------------------------
#         # 6) Upload to GCS
#         # --------------------------------------------------
#         BUCKET_NAME = config.GCS_BUCKET_NAME
#         project_folder = project_name.strip().replace(" ", "_")

#         gcs_pdf_path = upload_to_gcs(
#             BUCKET_NAME,
#             pdf_path,
#             f"{project_folder}/{safe_name}.pdf"
#         )

#         gcs_docx_path = upload_to_gcs(
#             BUCKET_NAME,
#             docx_path,
#             f"{project_folder}/{safe_name}.docx"
#         )

#         gcs_md_path = upload_to_gcs(
#             BUCKET_NAME,
#             md_path,
#             f"{project_folder}/{safe_name}.md"
#         )

#         gcs_html_path = upload_to_gcs(
#             BUCKET_NAME,
#             html_path,
#             f"{project_folder}/{safe_name}.html"
#         )

#         # --------------------------------------------------
#         # 7) Signed URLs
#         # --------------------------------------------------
#         signed_pdf_url = generate_signed_gcs_url(
#             BUCKET_NAME,
#             f"{project_folder}/{safe_name}.pdf"
#         )

#         signed_docx_url = generate_signed_gcs_url(
#             BUCKET_NAME,
#             f"{project_folder}/{safe_name}.docx"
#         )

#         signed_md_url = generate_signed_gcs_url(
#             BUCKET_NAME,
#             f"{project_folder}/{safe_name}.md"
#         )

#         signed_html_url = generate_signed_gcs_url(
#             BUCKET_NAME,
#             f"{project_folder}/{safe_name}.html"
#         )
#         backend_base_url = os.getenv("BACKEND_BASE_URL", "http://localhost:8000").rstrip("/")

#         return {
#             "status": "success",

#             # Local paths (kept – backward compatible)
#             "output_file": pdf_path,
#             "word_file": docx_path,
#             "md_file": md_path,
#             "html_file": html_path,

#             # Local download URLs for Streamlit/local frontend.
#             # Streamlit runs on :8501, but files are served by backend on :8000.
#             "local_download_urls": {
#                 "pdf": f"{backend_base_url}/download/{Path(pdf_path).name}",
#                 "docx": f"{backend_base_url}/download/{Path(docx_path).name}",
#                 "md": f"{backend_base_url}/download/{Path(md_path).name}",
#                 "html": f"{backend_base_url}/download/{Path(html_path).name}",
#             },

#             # Local view URLs.
#             # Useful for opening HTML/PDF directly in browser if FastAPI mounts /generated_docs.
#             "local_view_urls": {
#                 "pdf": f"{backend_base_url}/generated_docs/{Path(pdf_path).name}",
#                 "docx": f"{backend_base_url}/generated_docs/{Path(docx_path).name}",
#                 "md": f"{backend_base_url}/generated_docs/{Path(md_path).name}",
#                 "html": f"{backend_base_url}/generated_docs/{Path(html_path).name}",
#             },

#             # GCS paths
#             "gcs_pdf": gcs_pdf_path,
#             "gcs_docx": gcs_docx_path,
#             "gcs_md": gcs_md_path,
#             "gcs_html": gcs_html_path,

#             # Signed URLs
#             "signed_urls": {
#                 "pdf": signed_pdf_url,
#                 "docx": signed_docx_url,
#                 "md": signed_md_url,
#                 "html": signed_html_url,
#             },
#         }
#     except Exception as e:
#         logger.exception("Failed to render HLD documents")
#         return {
#             "status": "error",
#             "message": str(e),
#             "output_file": None,
#             "word_file": None,
#             "md_file": None,
#             "html_file": None,
#         }

# render_hld_tool = FunctionTool(func=render_hld_documents)

# from __future__ import annotations

# import os
# import re
# import json
# import html
# import base64
# import logging
# import tempfile
# from io import BytesIO
# from pathlib import Path
# from typing import Any, Dict, Optional, Tuple, List, Union, get_args, get_origin

# import markdown2
# import graphviz


# from PIL import Image, ImageDraw, ImageFont
# import hashlib

# from numpy import inner
# from pydantic import BaseModel
# from xhtml2pdf import pisa
# from google.adk.tools import FunctionTool

# from docx import Document
# from docx.shared import Inches, Pt
# from docx.enum.text import WD_ALIGN_PARAGRAPH
# from docx.oxml import OxmlElement
# from docx.oxml.ns import qn
# from typing import List
# from schema_types.hld_schema import HLDReport

# ## For GCS Document Storage
# from google.cloud import storage
# from pathlib import Path
# from datetime import timedelta
# from config_load import GetConf


# from google.auth import default
# from google.auth.credentials import Credentials
# from google.auth.exceptions import DefaultCredentialsError
# from google.auth import default

# from agent.workflow.keys import (
#     KEY_HLD_REPORT_JSON,
#     KEY_SELECTED_SECTIONS,
#     KEY_RENDER_SELECTED_SECTIONS,
# )

# from tools.hld_section_commit_tools import (
#     assemble_hld_from_state,
#     validate_required_hld_sections,
# )

from google.adk.tools import FunctionTool
from tools.rendering.orchestrator import render_hld_documents
render_hld_tool = FunctionTool(func=render_hld_documents)