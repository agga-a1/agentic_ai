# from __future__ import annotations

# import json
# import logging
# from pathlib import Path
# from typing import Any, Dict

# logger = logging.getLogger(__name__)


# # ---------------------------------------------------------------------
# # Path setup
# # ---------------------------------------------------------------------
# PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ICON_DIR = PROJECT_ROOT / "assets" / "icons"
# BRANDING_DIR = PROJECT_ROOT / "assets" / "branding"
# CONFIG_DIR = PROJECT_ROOT / "assets" / "config"


# # ---------------------------------------------------------------------
# # Generic config helpers
# # ---------------------------------------------------------------------
# def deep_merge(
#     default: Dict[str, Any],
#     override: Dict[str, Any],
# ) -> Dict[str, Any]:
#     """
#     Recursively merge override config into default config.

#     This allows JSON config files to contain only values that need overriding
#     without losing nested defaults.
#     """
#     merged = dict(default or {})

#     for key, value in (override or {}).items():
#         if isinstance(value, dict) and isinstance(merged.get(key), dict):
#             merged[key] = deep_merge(merged[key], value)
#         else:
#             merged[key] = value

#     return merged


# def load_json_config(
#     file_name: str,
#     default: Dict[str, Any] | None = None,
# ) -> Dict[str, Any]:
#     """
#     Load JSON config from assets/config.

#     If file is missing:
#       - return default

#     If file exists:
#       - deep merge loaded JSON into default
#       - this allows partial config overrides

#     If file is invalid:
#       - log exception
#       - return default
#     """
#     path = CONFIG_DIR / file_name

#     if not path.exists():
#         logger.warning("Config file not found: %s. Using defaults.", path)
#         return default or {}

#     try:
#         loaded = json.loads(path.read_text(encoding="utf-8"))

#         if default:
#             return deep_merge(default, loaded)

#         return loaded

#     except Exception:
#         logger.exception("Failed loading config file: %s", path)
#         return default or {}


# def cfg_get(
#     section: Dict[str, Any],
#     key: str,
#     default: Any,
# ) -> Any:
#     return section.get(key, default)


# def cfg_int(
#     section: Dict[str, Any],
#     key: str,
#     default: int,
# ) -> int:
#     try:
#         return int(section.get(key, default))
#     except Exception:
#         logger.warning(
#             "Invalid integer config for key=%s. Using default=%s",
#             key,
#             default,
#         )
#         return default


# def cfg_float(
#     section: Dict[str, Any],
#     key: str,
#     default: float,
# ) -> float:
#     try:
#         return float(section.get(key, default))
#     except Exception:
#         logger.warning(
#             "Invalid float config for key=%s. Using default=%s",
#             key,
#             default,
#         )
#         return default


# def cfg_bool(
#     section: Dict[str, Any],
#     key: str,
#     default: bool,
# ) -> bool:
#     value = section.get(key, default)

#     if isinstance(value, bool):
#         return value

#     if isinstance(value, str):
#         return value.strip().lower() in {
#             "true",
#             "1",
#             "yes",
#             "y",
#             "on",
#         }

#     return bool(value)


# def cfg_list_int(
#     section: Dict[str, Any],
#     key: str,
#     default: list[int],
# ) -> list[int]:
#     value = section.get(key, default)

#     try:
#         if isinstance(value, list):
#             return [int(item) for item in value]

#         if isinstance(value, str):
#             return [
#                 int(item.strip())
#                 for item in value.split(",")
#                 if item.strip()
#             ]

#         return default

#     except Exception:
#         logger.warning(
#             "Invalid list[int] config for key=%s. Using default=%s",
#             key,
#             default,
#         )
#         return default


# # ---------------------------------------------------------------------
# # Default config dictionaries
# # ---------------------------------------------------------------------
# DEFAULT_DIAGRAM_CONFIG: Dict[str, Any] = {
#     # Base graph readability
#     "graph_font_size": 18,
#     "cluster_font_size": 16,

#     # Cluster/container styling for zone boxes like On-Premise, GCP, etc.
#     # These values are consumed by graphviz_renderer.py.
#     "cluster_fill_color": "#F3F8FF",
#     "cluster_border_color": "#A8C7FA",
#     "cluster_font_color": "#174EA6",
#     "cluster_style": "rounded,filled",
#     "cluster_penwidth": 1.5,
#     "cluster_margin": 14,
#     "cluster_label_bold": True,

#     "node_font_size": 15,
#     "edge_font_size": 13,

#     # Node card rendering
#     "node_card_size": [430, 290],
#     "node_card_font_size": 30,
#     "node_card_text_bold": True,
#     "node_card_width_in": 3.05,
#     "node_card_height_in": 2.05,

#     # Backward-compatible PDF diagram height
#     "pdf_max_height_px": 680,

#     # Horizontal layout controls
#     "force_rankdir": "LR",
#     "graph_splines": "ortho",
#     "graph_ranksep": 0.85,
#     "graph_nodesep": 0.75,
#     "graph_pad": 0.35,
#     "graph_overlap": False,
#     "graph_output_order": "edgesfirst",
#     "graph_newrank": True,

#     # Edge styling
#     "edge_penwidth": 2.2,
#     "edge_minlen": 2,
#     "edge_arrowsize": 0.9,

#     # Legend styling
#     "legend_title_font_size": 18,
#     "legend_item_font_size": 11,
#     "legend_heading_label": "Flow Legend",
#     "legend_border_color": "#8A8F98",
#     "legend_fill_color": "#F8FAFC",
#     "legend_title_color": "#202124",
#     "legend_item_font_color": "#202124",
#     "legend_item_fill_color": "#FFFFFF",
#     "legend_margin": 14,
#     "legend_pad": 0.12,
#     "legend_nodesep": 0.12,
#     "legend_ranksep": 0.12,
#     "legend_edge_penwidth": 2.0,
#     "legend_edge_arrowsize": 0.65,

#     # Default/fallback node styling
#     "node_default_fill": "#F8F9FA",
#     "node_default_border": "#DADCE0",
#     "node_default_font": "#202124",
#     "node_default_margin": "0.14,0.09",
#     "node_default_penwidth": 1.6,

#     # Fallback text-only card badge
#     "fallback_card_badge_enabled": True,
#     "fallback_card_badge_fill": "#FFFFFF",
#     "fallback_card_badge_font_size": 28,
#     "fallback_card_initials_max_chars": 3,

#     # Optional advanced graph rendering controls
#     "graph_ratio": "compress",
#     "graph_concentrate": True,
#     "graph_compound": True,
#     "graph_dpi": 180,

#     # PNG trimming controls
#     "trim_png_whitespace": True,
#     "trim_png_background_threshold": 248,
#     "trim_png_padding_px": 18,

#     # Node filtering controls
#     "skip_unconnected_nodes": True,
# }

# DEFAULT_ICON_ALIAS_CONFIG: Dict[str, Any] = {
#     "aliases": {},
# }

# DEFAULT_NODE_STYLE_CONFIG: Dict[str, Any] = {
#     "categories": {},
#     "default_category": "external",
# }

# DEFAULT_ISOLATED_NODE_CONFIG: Dict[str, Any] = {
#     "isolated_node_terms": [],
# }

# DEFAULT_RENDER_CONFIG: Dict[str, Any] = {
#     "document": {
#         "title": "Universal High Level Design (HLD)",
#         "font_family": "Helvetica, Arial, sans-serif",
#         "font_size_pt": 10,
#         "primary_color": "#E60000",
#         "body_color": "#222",
#         "link_color": "#0645AD",
#     },
#     "pdf": {
#         "page_size": "A4",
#         "page_margin_cm": 1.25,
#         "paragraph_line_height": 1.35,
#         "table_margin": "10px 0 14px 0",
#         "table_header_background": "#f4f7f9",
#         "table_border_color": "#ccc",
#         "table_header_font_size_pt": 9,
#         "table_cell_font_size_pt": 8.5,

#         # Diagram sizing/page behaviour in PDF
#         "diagram_max_height_px": 735,
#         "diagram_single_page": True,

#         # Keep section heading + diagram together.
#         # Page break after prevents multiple diagrams on the same page.
#         "diagram_page_break_before": False,
#         "diagram_page_break_after": True,
#     },
#     "toc": {
#         "enabled": True,
#         "clickable": True,
#         "include_heading_levels": [2, 3, 4],
#         "font_size_pt": 9.5,
#         "line_height": 1.35,
#         "indent_px": 16,
#         "link_color": "#0645AD",
#         "underline_links": True,
#         "level_2_bold": True,
#         "level_4_font_size_pt": 9,
#     },
#     "docx": {
#         "font_name": "Calibri",
#         "font_size_pt": 10,
#         "top_margin_in": 0.65,
#         "bottom_margin_in": 0.65,
#         "left_margin_in": 0.7,
#         "right_margin_in": 0.7,
#         "logo_width_in": 2.0,
#         "max_image_width_fallback_in": 6.2,
#         "max_image_height_fallback_in": 8.0,
#         "toc_outline": "1-3",
#         "update_fields_on_open": True,

#         # Diagram page behaviour in DOCX
#         # Keep heading + edit links + diagram together, then page-break after.
#         "diagram_single_page": True,
#         "diagram_page_break_before": False,
#         "diagram_page_break_after": True,

#         # Optional DOCX editable diagram mode.
#         # This does not impact PDF rendering and does not remove PNG fallback.
#         "editable_diagrams": {
#             "enabled": True,
#             "mode": "svg",
#             "fallback_mode": "png",
#             "embed_svg_instead_of_png": True,
#             "prefer_svg_icons": True,
#             "show_user_instruction": True,
#             "keep_source_links": True,
#             "instruction_text": (
#                 "This diagram is inserted as SVG for better editability. "
#                 "To edit it in Microsoft Word, select the diagram, then use "
#                 "Graphics Format > Convert to Shape where supported."
#             ),
#         },
#     },
# }


# # ---------------------------------------------------------------------
# # Load config files
# # ---------------------------------------------------------------------
# DIAGRAM_DEFAULTS = load_json_config(
#     "diagram_defaults.json",
#     default=DEFAULT_DIAGRAM_CONFIG,
# )

# ICON_ALIAS_CONFIG = load_json_config(
#     "icon_aliases.json",
#     default=DEFAULT_ICON_ALIAS_CONFIG,
# )

# NODE_STYLE_CONFIG = load_json_config(
#     "node_styles.json",
#     default=DEFAULT_NODE_STYLE_CONFIG,
# )

# ISOLATED_NODE_CONFIG = load_json_config(
#     "isolated_nodes.json",
#     default=DEFAULT_ISOLATED_NODE_CONFIG,
# )

# RENDER_DEFAULTS = load_json_config(
#     "render_defaults.json",
#     default=DEFAULT_RENDER_CONFIG,
# )


# # ---------------------------------------------------------------------
# # Raw render sections
# # ---------------------------------------------------------------------
# DOCUMENT_DEFAULTS = RENDER_DEFAULTS.get("document", {})
# PDF_DEFAULTS = RENDER_DEFAULTS.get("pdf", {})
# TOC_DEFAULTS = RENDER_DEFAULTS.get("toc", {})
# DOCX_DEFAULTS = RENDER_DEFAULTS.get("docx", {})
# DOCX_EDITABLE_DIAGRAM_DEFAULTS = DOCX_DEFAULTS.get("editable_diagrams", {})


# # ---------------------------------------------------------------------
# # Resolved diagram defaults
# # ---------------------------------------------------------------------
# DIAGRAM_GRAPH_FONT_SIZE = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "graph_font_size",
#     18,
# )

# DIAGRAM_CLUSTER_FONT_SIZE = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "cluster_font_size",
#     16,
# )

# DIAGRAM_CLUSTER_FILL_COLOR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "cluster_fill_color",
#         "#F3F8FF",
#     )
# )

# DIAGRAM_CLUSTER_BORDER_COLOR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "cluster_border_color",
#         "#A8C7FA",
#     )
# )

# DIAGRAM_CLUSTER_FONT_COLOR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "cluster_font_color",
#         "#174EA6",
#     )
# )

# DIAGRAM_CLUSTER_STYLE = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "cluster_style",
#         "rounded,filled",
#     )
# )

# DIAGRAM_CLUSTER_PENWIDTH = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "cluster_penwidth",
#     1.5,
# )

# DIAGRAM_CLUSTER_MARGIN = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "cluster_margin",
#     14,
# )

# DIAGRAM_CLUSTER_LABEL_BOLD = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "cluster_label_bold",
#     True,
# )

# DIAGRAM_NODE_FONT_SIZE = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "node_font_size",
#     15,
# )

# DIAGRAM_EDGE_FONT_SIZE = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "edge_font_size",
#     13,
# )

# _DIAGRAM_NODE_CARD_SIZE_RAW = DIAGRAM_DEFAULTS.get(
#     "node_card_size",
#     [430, 290],
# )

# try:
#     DIAGRAM_NODE_CARD_SIZE = (
#         int(_DIAGRAM_NODE_CARD_SIZE_RAW[0]),
#         int(_DIAGRAM_NODE_CARD_SIZE_RAW[1]),
#     )
# except Exception:
#     logger.warning(
#         "Invalid node_card_size config. Using default=(430, 290)."
#     )
#     DIAGRAM_NODE_CARD_SIZE = (430, 290)

# DIAGRAM_NODE_CARD_FONT_SIZE = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "node_card_font_size",
#     30,
# )

# DIAGRAM_NODE_CARD_TEXT_BOLD = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "node_card_text_bold",
#     True,
# )

# DIAGRAM_NODE_CARD_WIDTH_IN = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "node_card_width_in",
#     3.05,
# )

# DIAGRAM_NODE_CARD_HEIGHT_IN = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "node_card_height_in",
#     2.05,
# )

# # Backward compatibility for older renderers.
# DIAGRAM_PDF_MAX_HEIGHT_PX = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "pdf_max_height_px",
#     680,
# )


# # ---------------------------------------------------------------------
# # Resolved Graphviz layout defaults
# # ---------------------------------------------------------------------
# DIAGRAM_FORCE_RANKDIR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "force_rankdir",
#         "LR",
#     )
# )

# DIAGRAM_GRAPH_SPLINES = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "graph_splines",
#         "ortho",
#     )
# )

# DIAGRAM_GRAPH_RANKSEP = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "graph_ranksep",
#     0.85,
# )

# DIAGRAM_GRAPH_NODESEP = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "graph_nodesep",
#     0.75,
# )

# DIAGRAM_GRAPH_PAD = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "graph_pad",
#     0.35,
# )

# DIAGRAM_GRAPH_OVERLAP = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "graph_overlap",
#     False,
# )

# DIAGRAM_GRAPH_OUTPUT_ORDER = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "graph_output_order",
#         "edgesfirst",
#     )
# )

# DIAGRAM_GRAPH_NEWRANK = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "graph_newrank",
#     True,
# )


# # ---------------------------------------------------------------------
# # Resolved advanced Graphviz defaults
# # ---------------------------------------------------------------------
# DIAGRAM_GRAPH_RATIO = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "graph_ratio",
#         "compress",
#     )
# )

# DIAGRAM_GRAPH_CONCENTRATE = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "graph_concentrate",
#     True,
# )

# DIAGRAM_GRAPH_COMPOUND = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "graph_compound",
#     True,
# )

# DIAGRAM_GRAPH_DPI = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "graph_dpi",
#     180,
# )


# # ---------------------------------------------------------------------
# # Resolved PNG trim defaults
# # ---------------------------------------------------------------------
# DIAGRAM_TRIM_PNG_WHITESPACE = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "trim_png_whitespace",
#     True,
# )

# DIAGRAM_TRIM_PNG_BACKGROUND_THRESHOLD = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "trim_png_background_threshold",
#     248,
# )

# DIAGRAM_TRIM_PNG_PADDING_PX = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "trim_png_padding_px",
#     18,
# )


# # ---------------------------------------------------------------------
# # Resolved node filtering defaults
# # ---------------------------------------------------------------------
# DIAGRAM_SKIP_UNCONNECTED_NODES = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "skip_unconnected_nodes",
#     True,
# )


# # ---------------------------------------------------------------------
# # Resolved Graphviz edge defaults
# # ---------------------------------------------------------------------
# DIAGRAM_EDGE_PENWIDTH = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "edge_penwidth",
#     2.2,
# )

# DIAGRAM_EDGE_MINLEN = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "edge_minlen",
#     2,
# )

# DIAGRAM_EDGE_ARROWSIZE = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "edge_arrowsize",
#     0.9,
# )


# # ---------------------------------------------------------------------
# # Resolved legend defaults
# # ---------------------------------------------------------------------
# DIAGRAM_LEGEND_TITLE_FONT_SIZE = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "legend_title_font_size",
#     18,
# )

# DIAGRAM_LEGEND_ITEM_FONT_SIZE = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "legend_item_font_size",
#     11,
# )

# DIAGRAM_LEGEND_HEADING_LABEL = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "legend_heading_label",
#         "Flow Legend",
#     )
# )

# DIAGRAM_LEGEND_BORDER_COLOR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "legend_border_color",
#         "#8A8F98",
#     )
# )

# DIAGRAM_LEGEND_FILL_COLOR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "legend_fill_color",
#         "#F8FAFC",
#     )
# )

# DIAGRAM_LEGEND_TITLE_COLOR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "legend_title_color",
#         "#202124",
#     )
# )

# DIAGRAM_LEGEND_ITEM_FONT_COLOR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "legend_item_font_color",
#         "#202124",
#     )
# )

# DIAGRAM_LEGEND_ITEM_FILL_COLOR = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "legend_item_fill_color",
#         "#FFFFFF",
#     )
# )

# DIAGRAM_LEGEND_MARGIN = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "legend_margin",
#     14,
# )

# DIAGRAM_LEGEND_PAD = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "legend_pad",
#     0.12,
# )

# DIAGRAM_LEGEND_NODESEP = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "legend_nodesep",
#     0.12,
# )

# DIAGRAM_LEGEND_RANKSEP = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "legend_ranksep",
#     0.12,
# )

# DIAGRAM_LEGEND_EDGE_PENWIDTH = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "legend_edge_penwidth",
#     2.0,
# )

# DIAGRAM_LEGEND_EDGE_ARROWSIZE = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "legend_edge_arrowsize",
#     0.65,
# )


# # ---------------------------------------------------------------------
# # Resolved node fallback defaults
# # ---------------------------------------------------------------------
# DIAGRAM_NODE_DEFAULT_FILL = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "node_default_fill",
#         "#F8F9FA",
#     )
# )

# DIAGRAM_NODE_DEFAULT_BORDER = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "node_default_border",
#         "#DADCE0",
#     )
# )

# DIAGRAM_NODE_DEFAULT_FONT = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "node_default_font",
#         "#202124",
#     )
# )

# DIAGRAM_NODE_DEFAULT_MARGIN = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "node_default_margin",
#         "0.14,0.09",
#     )
# )

# DIAGRAM_NODE_DEFAULT_PENWIDTH = cfg_float(
#     DIAGRAM_DEFAULTS,
#     "node_default_penwidth",
#     1.6,
# )

# DIAGRAM_FALLBACK_CARD_BADGE_ENABLED = cfg_bool(
#     DIAGRAM_DEFAULTS,
#     "fallback_card_badge_enabled",
#     True,
# )

# DIAGRAM_FALLBACK_CARD_BADGE_FILL = str(
#     cfg_get(
#         DIAGRAM_DEFAULTS,
#         "fallback_card_badge_fill",
#         "#FFFFFF",
#     )
# )

# DIAGRAM_FALLBACK_CARD_BADGE_FONT_SIZE = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "fallback_card_badge_font_size",
#     28,
# )

# DIAGRAM_FALLBACK_CARD_INITIALS_MAX_CHARS = cfg_int(
#     DIAGRAM_DEFAULTS,
#     "fallback_card_initials_max_chars",
#     3,
# )


# # ---------------------------------------------------------------------
# # Resolved document defaults
# # ---------------------------------------------------------------------
# DOCUMENT_TITLE = str(
#     cfg_get(
#         DOCUMENT_DEFAULTS,
#         "title",
#         "Universal High Level Design (HLD)",
#     )
# )

# DOCUMENT_FONT_FAMILY = str(
#     cfg_get(
#         DOCUMENT_DEFAULTS,
#         "font_family",
#         "Helvetica, Arial, sans-serif",
#     )
# )

# DOCUMENT_FONT_SIZE_PT = cfg_float(
#     DOCUMENT_DEFAULTS,
#     "font_size_pt",
#     10,
# )

# DOCUMENT_PRIMARY_COLOR = str(
#     cfg_get(
#         DOCUMENT_DEFAULTS,
#         "primary_color",
#         "#E60000",
#     )
# )

# DOCUMENT_BODY_COLOR = str(
#     cfg_get(
#         DOCUMENT_DEFAULTS,
#         "body_color",
#         "#222",
#     )
# )

# DOCUMENT_LINK_COLOR = str(
#     cfg_get(
#         DOCUMENT_DEFAULTS,
#         "link_color",
#         "#0645AD",
#     )
# )


# # ---------------------------------------------------------------------
# # Resolved PDF defaults
# # ---------------------------------------------------------------------
# PDF_PAGE_SIZE = str(
#     cfg_get(
#         PDF_DEFAULTS,
#         "page_size",
#         "A4",
#     )
# )

# PDF_PAGE_MARGIN_CM = cfg_float(
#     PDF_DEFAULTS,
#     "page_margin_cm",
#     1.25,
# )

# PDF_PARAGRAPH_LINE_HEIGHT = cfg_float(
#     PDF_DEFAULTS,
#     "paragraph_line_height",
#     1.35,
# )

# PDF_TABLE_MARGIN = str(
#     cfg_get(
#         PDF_DEFAULTS,
#         "table_margin",
#         "10px 0 14px 0",
#     )
# )

# PDF_TABLE_HEADER_BACKGROUND = str(
#     cfg_get(
#         PDF_DEFAULTS,
#         "table_header_background",
#         "#f4f7f9",
#     )
# )

# PDF_TABLE_BORDER_COLOR = str(
#     cfg_get(
#         PDF_DEFAULTS,
#         "table_border_color",
#         "#ccc",
#     )
# )

# PDF_TABLE_HEADER_FONT_SIZE_PT = cfg_float(
#     PDF_DEFAULTS,
#     "table_header_font_size_pt",
#     9,
# )

# PDF_TABLE_CELL_FONT_SIZE_PT = cfg_float(
#     PDF_DEFAULTS,
#     "table_cell_font_size_pt",
#     8.5,
# )

# # Preferred PDF diagram image max height.
# # Uses render_defaults.json first, then falls back to diagram_defaults.json.
# PDF_DIAGRAM_MAX_HEIGHT_PX = cfg_int(
#     PDF_DEFAULTS,
#     "diagram_max_height_px",
#     DIAGRAM_PDF_MAX_HEIGHT_PX,
# )

# PDF_DIAGRAM_SINGLE_PAGE = cfg_bool(
#     PDF_DEFAULTS,
#     "diagram_single_page",
#     True,
# )

# PDF_DIAGRAM_PAGE_BREAK_BEFORE = cfg_bool(
#     PDF_DEFAULTS,
#     "diagram_page_break_before",
#     False,
# )

# PDF_DIAGRAM_PAGE_BREAK_AFTER = cfg_bool(
#     PDF_DEFAULTS,
#     "diagram_page_break_after",
#     True,
# )


# # ---------------------------------------------------------------------
# # Resolved TOC defaults
# # ---------------------------------------------------------------------
# TOC_ENABLED = cfg_bool(
#     TOC_DEFAULTS,
#     "enabled",
#     True,
# )

# TOC_CLICKABLE = cfg_bool(
#     TOC_DEFAULTS,
#     "clickable",
#     True,
# )

# TOC_INCLUDE_HEADING_LEVELS = cfg_list_int(
#     TOC_DEFAULTS,
#     "include_heading_levels",
#     [2, 3, 4],
# )

# TOC_FONT_SIZE_PT = cfg_float(
#     TOC_DEFAULTS,
#     "font_size_pt",
#     9.5,
# )

# TOC_LINE_HEIGHT = cfg_float(
#     TOC_DEFAULTS,
#     "line_height",
#     1.35,
# )

# TOC_INDENT_PX = cfg_int(
#     TOC_DEFAULTS,
#     "indent_px",
#     16,
# )

# TOC_LINK_COLOR = str(
#     cfg_get(
#         TOC_DEFAULTS,
#         "link_color",
#         DOCUMENT_LINK_COLOR,
#     )
# )

# TOC_UNDERLINE_LINKS = cfg_bool(
#     TOC_DEFAULTS,
#     "underline_links",
#     True,
# )

# TOC_LEVEL_2_BOLD = cfg_bool(
#     TOC_DEFAULTS,
#     "level_2_bold",
#     True,
# )

# TOC_LEVEL_4_FONT_SIZE_PT = cfg_float(
#     TOC_DEFAULTS,
#     "level_4_font_size_pt",
#     9,
# )


# # ---------------------------------------------------------------------
# # Resolved DOCX defaults
# # ---------------------------------------------------------------------
# DOCX_FONT_NAME = str(
#     cfg_get(
#         DOCX_DEFAULTS,
#         "font_name",
#         "Calibri",
#     )
# )

# DOCX_FONT_SIZE_PT = cfg_int(
#     DOCX_DEFAULTS,
#     "font_size_pt",
#     10,
# )

# DOCX_TOP_MARGIN_IN = cfg_float(
#     DOCX_DEFAULTS,
#     "top_margin_in",
#     0.65,
# )

# DOCX_BOTTOM_MARGIN_IN = cfg_float(
#     DOCX_DEFAULTS,
#     "bottom_margin_in",
#     0.65,
# )

# DOCX_LEFT_MARGIN_IN = cfg_float(
#     DOCX_DEFAULTS,
#     "left_margin_in",
#     0.7,
# )

# DOCX_RIGHT_MARGIN_IN = cfg_float(
#     DOCX_DEFAULTS,
#     "right_margin_in",
#     0.7,
# )

# DOCX_LOGO_WIDTH_IN = cfg_float(
#     DOCX_DEFAULTS,
#     "logo_width_in",
#     2.0,
# )

# DOCX_MAX_IMAGE_WIDTH_FALLBACK_IN = cfg_float(
#     DOCX_DEFAULTS,
#     "max_image_width_fallback_in",
#     6.2,
# )

# DOCX_MAX_IMAGE_HEIGHT_FALLBACK_IN = cfg_float(
#     DOCX_DEFAULTS,
#     "max_image_height_fallback_in",
#     8.0,
# )

# DOCX_TOC_OUTLINE = str(
#     cfg_get(
#         DOCX_DEFAULTS,
#         "toc_outline",
#         "1-3",
#     )
# )

# DOCX_UPDATE_FIELDS_ON_OPEN = cfg_bool(
#     DOCX_DEFAULTS,
#     "update_fields_on_open",
#     True,
# )

# DOCX_DIAGRAM_SINGLE_PAGE = cfg_bool(
#     DOCX_DEFAULTS,
#     "diagram_single_page",
#     True,
# )

# DOCX_DIAGRAM_PAGE_BREAK_BEFORE = cfg_bool(
#     DOCX_DEFAULTS,
#     "diagram_page_break_before",
#     False,
# )

# DOCX_DIAGRAM_PAGE_BREAK_AFTER = cfg_bool(
#     DOCX_DEFAULTS,
#     "diagram_page_break_after",
#     True,
# )


# # ---------------------------------------------------------------------
# # Resolved DOCX editable diagram defaults
# # ---------------------------------------------------------------------
# DOCX_EDITABLE_DIAGRAMS_ENABLED = cfg_bool(
#     DOCX_EDITABLE_DIAGRAM_DEFAULTS,
#     "enabled",
#     True,
# )

# DOCX_EDITABLE_DIAGRAMS_MODE = str(
#     cfg_get(
#         DOCX_EDITABLE_DIAGRAM_DEFAULTS,
#         "mode",
#         "svg",
#     )
# ).strip().lower()

# DOCX_EDITABLE_DIAGRAMS_FALLBACK_MODE = str(
#     cfg_get(
#         DOCX_EDITABLE_DIAGRAM_DEFAULTS,
#         "fallback_mode",
#         "png",
#     )
# ).strip().lower()

# DOCX_EMBED_SVG_INSTEAD_OF_PNG = cfg_bool(
#     DOCX_EDITABLE_DIAGRAM_DEFAULTS,
#     "embed_svg_instead_of_png",
#     True,
# )

# DOCX_PREFER_SVG_ICONS = cfg_bool(
#     DOCX_EDITABLE_DIAGRAM_DEFAULTS,
#     "prefer_svg_icons",
#     True,
# )

# DOCX_SHOW_EDITABLE_DIAGRAM_INSTRUCTION = cfg_bool(
#     DOCX_EDITABLE_DIAGRAM_DEFAULTS,
#     "show_user_instruction",
#     True,
# )

# DOCX_KEEP_DIAGRAM_SOURCE_LINKS = cfg_bool(
#     DOCX_EDITABLE_DIAGRAM_DEFAULTS,
#     "keep_source_links",
#     True,
# )

# DOCX_EDITABLE_DIAGRAM_INSTRUCTION_TEXT = str(
#     cfg_get(
#         DOCX_EDITABLE_DIAGRAM_DEFAULTS,
#         "instruction_text",
#         (
#             "This diagram is inserted as SVG for better editability. "
#             "To edit it in Microsoft Word, select the diagram, then use "
#             "Graphics Format > Convert to Shape where supported."
#         ),
#     )
# )

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]

ICON_DIR = PROJECT_ROOT / "assets" / "icons"
BRANDING_DIR = PROJECT_ROOT / "assets" / "branding"
CONFIG_DIR = PROJECT_ROOT / "assets" / "config"


# ---------------------------------------------------------------------
# Generic config helpers
# ---------------------------------------------------------------------
def deep_merge(default: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override config into default config."""
    merged = dict(default or {})
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_json_config(file_name: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    path = CONFIG_DIR / file_name
    if not path.exists():
        logger.warning("Config file not found: %s. Using defaults.", path)
        return default or {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return deep_merge(default, loaded) if default else loaded
    except Exception:
        logger.exception("Failed loading config file: %s", path)
        return default or {}


def cfg_get(section: Dict[str, Any], key: str, default: Any) -> Any:
    return section.get(key, default)


def cfg_int(section: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(section.get(key, default))
    except Exception:
        logger.warning("Invalid integer config for key=%s. Using default=%s", key, default)
        return default


def cfg_float(section: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(section.get(key, default))
    except Exception:
        logger.warning("Invalid float config for key=%s. Using default=%s", key, default)
        return default


def cfg_bool(section: Dict[str, Any], key: str, default: bool) -> bool:
    value = section.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return bool(value)


def cfg_list_int(section: Dict[str, Any], key: str, default: list[int]) -> list[int]:
    value = section.get(key, default)
    try:
        if isinstance(value, list):
            return [int(item) for item in value]
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return default
    except Exception:
        logger.warning("Invalid list[int] config for key=%s. Using default=%s", key, default)
        return default


# ---------------------------------------------------------------------
# Default config dictionaries
# ---------------------------------------------------------------------
DEFAULT_DIAGRAM_CONFIG: Dict[str, Any] = {
    # Base graph readability
    "graph_font_size": 18,
    "cluster_font_size": 16,

    # Cluster/container styling for zone boxes like On-Premise, GCP, etc.
    "cluster_fill_color": "#F3F8FF",
    "cluster_border_color": "#A8C7FA",
    "cluster_font_color": "#174EA6",
    "cluster_style": "rounded,filled",
    "cluster_penwidth": 1.5,
    "cluster_margin": 14,
    "cluster_label_bold": True,

    "node_font_size": 15,
    "edge_font_size": 13,

    # Node card rendering: increased defaults for readable names in DOCX/PDF.
    "node_card_size": [560, 340],
    "node_card_font_size": 34,
    "node_card_min_font_size": 24,
    "node_card_max_lines": 3,
    "node_card_text_bold": True,
    "node_card_text_padding_x": 34,
    "node_card_text_bottom_padding": 22,
    "node_card_text_line_gap": 7,
    "node_card_border_width": 4,
    "node_card_corner_radius": 22,
    "node_card_icon_max_width_ratio": 0.42,
    "node_card_icon_max_height_ratio": 0.32,
    "node_card_icon_top_padding": 18,
    "node_card_icon_text_gap": 14,

    # Graphviz card dimensions must match the card aspect ratio.
    "node_card_width_in": 3.35,
    "node_card_height_in": 2.05,

    # Backward-compatible PDF diagram height
    "pdf_max_height_px": 680,

    # Horizontal layout controls
    "force_rankdir": "LR",
    "graph_splines": "ortho",
    "graph_ranksep": 0.85,
    "graph_nodesep": 0.75,
    "graph_pad": 0.35,
    "graph_overlap": False,
    "graph_output_order": "edgesfirst",
    "graph_newrank": True,

    # Edge styling
    "edge_penwidth": 2.2,
    "edge_minlen": 2,
    "edge_arrowsize": 0.9,

    # Legend styling
    "legend_title_font_size": 18,
    "legend_item_font_size": 11,
    "legend_heading_label": "Flow Legend",
    "legend_border_color": "#8A8F98",
    "legend_fill_color": "#F8FAFC",
    "legend_title_color": "#202124",
    "legend_item_font_color": "#202124",
    "legend_item_fill_color": "#FFFFFF",
    "legend_margin": 14,
    "legend_pad": 0.12,
    "legend_nodesep": 0.12,
    "legend_ranksep": 0.12,
    "legend_edge_penwidth": 2.0,
    "legend_edge_arrowsize": 0.65,

    # Default/fallback node styling
    "node_default_fill": "#F8F9FA",
    "node_default_border": "#DADCE0",
    "node_default_font": "#202124",
    "node_default_margin": "0.14,0.09",
    "node_default_penwidth": 1.6,

    # Fallback text-only card badge
    "fallback_card_badge_enabled": True,
    "fallback_card_badge_fill": "#FFFFFF",
    "fallback_card_badge_font_size": 30,
    "fallback_card_initials_max_chars": 3,

    # Optional advanced graph rendering controls
    "graph_ratio": "compress",
    "graph_concentrate": True,
    "graph_compound": True,
    "graph_dpi": 180,

    # PNG trimming controls
    "trim_png_whitespace": True,
    "trim_png_background_threshold": 248,
    "trim_png_padding_px": 18,

    # Node filtering controls
    "skip_unconnected_nodes": True,
}

DEFAULT_ICON_ALIAS_CONFIG: Dict[str, Any] = {"aliases": {}}
DEFAULT_NODE_STYLE_CONFIG: Dict[str, Any] = {"categories": {}, "default_category": "external"}
DEFAULT_ISOLATED_NODE_CONFIG: Dict[str, Any] = {"isolated_node_terms": []}

DEFAULT_RENDER_CONFIG: Dict[str, Any] = {
    "document": {
        "title": "Universal High Level Design (HLD)",
        "font_family": "Helvetica, Arial, sans-serif",
        "font_size_pt": 10,
        "primary_color": "#E60000",
        "body_color": "#222",
        "link_color": "#0645AD",
    },
    "pdf": {
        "page_size": "A4",
        "page_margin_cm": 1.25,
        "paragraph_line_height": 1.35,
        "table_margin": "10px 0 14px 0",
        "table_header_background": "#f4f7f9",
        "table_border_color": "#ccc",
        "table_header_font_size_pt": 9,
        "table_cell_font_size_pt": 8.5,
        "diagram_max_height_px": 735,
        "diagram_single_page": True,
        "diagram_page_break_before": False,
        "diagram_page_break_after": True,
    },
    "toc": {
        "enabled": True,
        "clickable": True,
        "include_heading_levels": [2, 3, 4],
        "font_size_pt": 9.5,
        "line_height": 1.35,
        "indent_px": 16,
        "link_color": "#0645AD",
        "underline_links": True,
        "level_2_bold": True,
        "level_4_font_size_pt": 9,
    },
    "docx": {
        "font_name": "Calibri",
        "font_size_pt": 10,
        "top_margin_in": 0.65,
        "bottom_margin_in": 0.65,
        "left_margin_in": 0.7,
        "right_margin_in": 0.7,
        "logo_width_in": 2.0,
        "max_image_width_fallback_in": 6.2,
        "max_image_height_fallback_in": 8.0,
        "toc_outline": "1-3",
        "update_fields_on_open": True,
        "diagram_single_page": True,
        "diagram_page_break_before": False,
        "diagram_page_break_after": True,
        "diagram_legend_enabled": True,
        "diagram_legend_max_width_in": 6.2,
        "editable_diagrams": {
            "enabled": True,
            "mode": "svg",
            "fallback_mode": "png",
            "embed_svg_instead_of_png": True,
            "prefer_svg_icons": True,
            "show_user_instruction": True,
            "keep_source_links": True,
            "instruction_text": (
                "This diagram is inserted as SVG for better editability. "
                "To edit it in Microsoft Word, select the diagram, then use "
                "Graphics Format > Convert to Shape where supported."
            ),
        },
    },
}


# ---------------------------------------------------------------------
# Load config files
# ---------------------------------------------------------------------
DIAGRAM_DEFAULTS = load_json_config("diagram_defaults.json", default=DEFAULT_DIAGRAM_CONFIG)
ICON_ALIAS_CONFIG = load_json_config("icon_aliases.json", default=DEFAULT_ICON_ALIAS_CONFIG)
NODE_STYLE_CONFIG = load_json_config("node_styles.json", default=DEFAULT_NODE_STYLE_CONFIG)
ISOLATED_NODE_CONFIG = load_json_config("isolated_nodes.json", default=DEFAULT_ISOLATED_NODE_CONFIG)
RENDER_DEFAULTS = load_json_config("render_defaults.json", default=DEFAULT_RENDER_CONFIG)


# ---------------------------------------------------------------------
# Raw render sections
# ---------------------------------------------------------------------
DOCUMENT_DEFAULTS = RENDER_DEFAULTS.get("document", {})
PDF_DEFAULTS = RENDER_DEFAULTS.get("pdf", {})
TOC_DEFAULTS = RENDER_DEFAULTS.get("toc", {})
DOCX_DEFAULTS = RENDER_DEFAULTS.get("docx", {})
DOCX_EDITABLE_DIAGRAM_DEFAULTS = DOCX_DEFAULTS.get("editable_diagrams", {})


# ---------------------------------------------------------------------
# Resolved diagram defaults
# ---------------------------------------------------------------------
DIAGRAM_GRAPH_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "graph_font_size", 18)
DIAGRAM_CLUSTER_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "cluster_font_size", 16)
DIAGRAM_CLUSTER_FILL_COLOR = str(cfg_get(DIAGRAM_DEFAULTS, "cluster_fill_color", "#F3F8FF"))
DIAGRAM_CLUSTER_BORDER_COLOR = str(cfg_get(DIAGRAM_DEFAULTS, "cluster_border_color", "#A8C7FA"))
DIAGRAM_CLUSTER_FONT_COLOR = str(cfg_get(DIAGRAM_DEFAULTS, "cluster_font_color", "#174EA6"))
DIAGRAM_CLUSTER_STYLE = str(cfg_get(DIAGRAM_DEFAULTS, "cluster_style", "rounded,filled"))
DIAGRAM_CLUSTER_PENWIDTH = cfg_float(DIAGRAM_DEFAULTS, "cluster_penwidth", 1.5)
DIAGRAM_CLUSTER_MARGIN = cfg_int(DIAGRAM_DEFAULTS, "cluster_margin", 14)
DIAGRAM_CLUSTER_LABEL_BOLD = cfg_bool(DIAGRAM_DEFAULTS, "cluster_label_bold", True)
DIAGRAM_NODE_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "node_font_size", 15)
DIAGRAM_EDGE_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "edge_font_size", 13)

_DIAGRAM_NODE_CARD_SIZE_RAW = DIAGRAM_DEFAULTS.get("node_card_size", [560, 340])
try:
    DIAGRAM_NODE_CARD_SIZE = (int(_DIAGRAM_NODE_CARD_SIZE_RAW[0]), int(_DIAGRAM_NODE_CARD_SIZE_RAW[1]))
except Exception:
    logger.warning("Invalid node_card_size config. Using default=(560, 340).")
    DIAGRAM_NODE_CARD_SIZE = (560, 340)

DIAGRAM_NODE_CARD_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "node_card_font_size", 34)
DIAGRAM_NODE_CARD_MIN_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "node_card_min_font_size", 24)
DIAGRAM_NODE_CARD_MAX_LINES = cfg_int(DIAGRAM_DEFAULTS, "node_card_max_lines", 3)
DIAGRAM_NODE_CARD_TEXT_BOLD = cfg_bool(DIAGRAM_DEFAULTS, "node_card_text_bold", True)
DIAGRAM_NODE_CARD_TEXT_PADDING_X = cfg_int(DIAGRAM_DEFAULTS, "node_card_text_padding_x", 34)
DIAGRAM_NODE_CARD_TEXT_BOTTOM_PADDING = cfg_int(DIAGRAM_DEFAULTS, "node_card_text_bottom_padding", 22)
DIAGRAM_NODE_CARD_TEXT_LINE_GAP = cfg_int(DIAGRAM_DEFAULTS, "node_card_text_line_gap", 7)
DIAGRAM_NODE_CARD_BORDER_WIDTH = cfg_int(DIAGRAM_DEFAULTS, "node_card_border_width", 4)
DIAGRAM_NODE_CARD_CORNER_RADIUS = cfg_int(DIAGRAM_DEFAULTS, "node_card_corner_radius", 22)
DIAGRAM_NODE_CARD_ICON_MAX_WIDTH_RATIO = cfg_float(DIAGRAM_DEFAULTS, "node_card_icon_max_width_ratio", 0.42)
DIAGRAM_NODE_CARD_ICON_MAX_HEIGHT_RATIO = cfg_float(DIAGRAM_DEFAULTS, "node_card_icon_max_height_ratio", 0.32)
DIAGRAM_NODE_CARD_ICON_TOP_PADDING = cfg_int(DIAGRAM_DEFAULTS, "node_card_icon_top_padding", 18)
DIAGRAM_NODE_CARD_ICON_TEXT_GAP = cfg_int(DIAGRAM_DEFAULTS, "node_card_icon_text_gap", 14)
DIAGRAM_NODE_CARD_WIDTH_IN = cfg_float(DIAGRAM_DEFAULTS, "node_card_width_in", 3.35)
DIAGRAM_NODE_CARD_HEIGHT_IN = cfg_float(DIAGRAM_DEFAULTS, "node_card_height_in", 2.05)
DIAGRAM_PDF_MAX_HEIGHT_PX = cfg_int(DIAGRAM_DEFAULTS, "pdf_max_height_px", 680)


# ---------------------------------------------------------------------
# Resolved Graphviz layout defaults
# ---------------------------------------------------------------------
DIAGRAM_FORCE_RANKDIR = str(cfg_get(DIAGRAM_DEFAULTS, "force_rankdir", "LR"))
DIAGRAM_GRAPH_SPLINES = str(cfg_get(DIAGRAM_DEFAULTS, "graph_splines", "ortho"))
DIAGRAM_GRAPH_RANKSEP = cfg_float(DIAGRAM_DEFAULTS, "graph_ranksep", 0.85)
DIAGRAM_GRAPH_NODESEP = cfg_float(DIAGRAM_DEFAULTS, "graph_nodesep", 0.75)
DIAGRAM_GRAPH_PAD = cfg_float(DIAGRAM_DEFAULTS, "graph_pad", 0.35)
DIAGRAM_GRAPH_OVERLAP = cfg_bool(DIAGRAM_DEFAULTS, "graph_overlap", False)
DIAGRAM_GRAPH_OUTPUT_ORDER = str(cfg_get(DIAGRAM_DEFAULTS, "graph_output_order", "edgesfirst"))
DIAGRAM_GRAPH_NEWRANK = cfg_bool(DIAGRAM_DEFAULTS, "graph_newrank", True)
DIAGRAM_GRAPH_RATIO = str(cfg_get(DIAGRAM_DEFAULTS, "graph_ratio", "compress"))
DIAGRAM_GRAPH_CONCENTRATE = cfg_bool(DIAGRAM_DEFAULTS, "graph_concentrate", True)
DIAGRAM_GRAPH_COMPOUND = cfg_bool(DIAGRAM_DEFAULTS, "graph_compound", True)
DIAGRAM_GRAPH_DPI = cfg_int(DIAGRAM_DEFAULTS, "graph_dpi", 180)
DIAGRAM_TRIM_PNG_WHITESPACE = cfg_bool(DIAGRAM_DEFAULTS, "trim_png_whitespace", True)
DIAGRAM_TRIM_PNG_BACKGROUND_THRESHOLD = cfg_int(DIAGRAM_DEFAULTS, "trim_png_background_threshold", 248)
DIAGRAM_TRIM_PNG_PADDING_PX = cfg_int(DIAGRAM_DEFAULTS, "trim_png_padding_px", 18)
DIAGRAM_SKIP_UNCONNECTED_NODES = cfg_bool(DIAGRAM_DEFAULTS, "skip_unconnected_nodes", True)


# ---------------------------------------------------------------------
# Resolved Graphviz edge defaults
# ---------------------------------------------------------------------
DIAGRAM_EDGE_PENWIDTH = cfg_float(DIAGRAM_DEFAULTS, "edge_penwidth", 2.2)
DIAGRAM_EDGE_MINLEN = cfg_int(DIAGRAM_DEFAULTS, "edge_minlen", 2)
DIAGRAM_EDGE_ARROWSIZE = cfg_float(DIAGRAM_DEFAULTS, "edge_arrowsize", 0.9)


# ---------------------------------------------------------------------
# Resolved legend defaults
# ---------------------------------------------------------------------
DIAGRAM_LEGEND_TITLE_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "legend_title_font_size", 18)
DIAGRAM_LEGEND_ITEM_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "legend_item_font_size", 11)
DIAGRAM_LEGEND_HEADING_LABEL = str(cfg_get(DIAGRAM_DEFAULTS, "legend_heading_label", "Flow Legend"))
DIAGRAM_LEGEND_BORDER_COLOR = str(cfg_get(DIAGRAM_DEFAULTS, "legend_border_color", "#8A8F98"))
DIAGRAM_LEGEND_FILL_COLOR = str(cfg_get(DIAGRAM_DEFAULTS, "legend_fill_color", "#F8FAFC"))
DIAGRAM_LEGEND_TITLE_COLOR = str(cfg_get(DIAGRAM_DEFAULTS, "legend_title_color", "#202124"))
DIAGRAM_LEGEND_ITEM_FONT_COLOR = str(cfg_get(DIAGRAM_DEFAULTS, "legend_item_font_color", "#202124"))
DIAGRAM_LEGEND_ITEM_FILL_COLOR = str(cfg_get(DIAGRAM_DEFAULTS, "legend_item_fill_color", "#FFFFFF"))
DIAGRAM_LEGEND_MARGIN = cfg_int(DIAGRAM_DEFAULTS, "legend_margin", 14)
DIAGRAM_LEGEND_PAD = cfg_float(DIAGRAM_DEFAULTS, "legend_pad", 0.12)
DIAGRAM_LEGEND_NODESEP = cfg_float(DIAGRAM_DEFAULTS, "legend_nodesep", 0.12)
DIAGRAM_LEGEND_RANKSEP = cfg_float(DIAGRAM_DEFAULTS, "legend_ranksep", 0.12)
DIAGRAM_LEGEND_EDGE_PENWIDTH = cfg_float(DIAGRAM_DEFAULTS, "legend_edge_penwidth", 2.0)
DIAGRAM_LEGEND_EDGE_ARROWSIZE = cfg_float(DIAGRAM_DEFAULTS, "legend_edge_arrowsize", 0.65)


# ---------------------------------------------------------------------
# Resolved node fallback defaults
# ---------------------------------------------------------------------
DIAGRAM_NODE_DEFAULT_FILL = str(cfg_get(DIAGRAM_DEFAULTS, "node_default_fill", "#F8F9FA"))
DIAGRAM_NODE_DEFAULT_BORDER = str(cfg_get(DIAGRAM_DEFAULTS, "node_default_border", "#DADCE0"))
DIAGRAM_NODE_DEFAULT_FONT = str(cfg_get(DIAGRAM_DEFAULTS, "node_default_font", "#202124"))
DIAGRAM_NODE_DEFAULT_MARGIN = str(cfg_get(DIAGRAM_DEFAULTS, "node_default_margin", "0.14,0.09"))
DIAGRAM_NODE_DEFAULT_PENWIDTH = cfg_float(DIAGRAM_DEFAULTS, "node_default_penwidth", 1.6)
DIAGRAM_FALLBACK_CARD_BADGE_ENABLED = cfg_bool(DIAGRAM_DEFAULTS, "fallback_card_badge_enabled", True)
DIAGRAM_FALLBACK_CARD_BADGE_FILL = str(cfg_get(DIAGRAM_DEFAULTS, "fallback_card_badge_fill", "#FFFFFF"))
DIAGRAM_FALLBACK_CARD_BADGE_FONT_SIZE = cfg_int(DIAGRAM_DEFAULTS, "fallback_card_badge_font_size", 30)
DIAGRAM_FALLBACK_CARD_INITIALS_MAX_CHARS = cfg_int(DIAGRAM_DEFAULTS, "fallback_card_initials_max_chars", 3)


# ---------------------------------------------------------------------
# Resolved document defaults
# ---------------------------------------------------------------------
DOCUMENT_TITLE = str(cfg_get(DOCUMENT_DEFAULTS, "title", "Universal High Level Design (HLD)"))
DOCUMENT_FONT_FAMILY = str(cfg_get(DOCUMENT_DEFAULTS, "font_family", "Helvetica, Arial, sans-serif"))
DOCUMENT_FONT_SIZE_PT = cfg_float(DOCUMENT_DEFAULTS, "font_size_pt", 10)
DOCUMENT_PRIMARY_COLOR = str(cfg_get(DOCUMENT_DEFAULTS, "primary_color", "#E60000"))
DOCUMENT_BODY_COLOR = str(cfg_get(DOCUMENT_DEFAULTS, "body_color", "#222"))
DOCUMENT_LINK_COLOR = str(cfg_get(DOCUMENT_DEFAULTS, "link_color", "#0645AD"))


# ---------------------------------------------------------------------
# Resolved PDF defaults
# ---------------------------------------------------------------------
PDF_PAGE_SIZE = str(cfg_get(PDF_DEFAULTS, "page_size", "A4"))
PDF_PAGE_MARGIN_CM = cfg_float(PDF_DEFAULTS, "page_margin_cm", 1.25)
PDF_PARAGRAPH_LINE_HEIGHT = cfg_float(PDF_DEFAULTS, "paragraph_line_height", 1.35)
PDF_TABLE_MARGIN = str(cfg_get(PDF_DEFAULTS, "table_margin", "10px 0 14px 0"))
PDF_TABLE_HEADER_BACKGROUND = str(cfg_get(PDF_DEFAULTS, "table_header_background", "#f4f7f9"))
PDF_TABLE_BORDER_COLOR = str(cfg_get(PDF_DEFAULTS, "table_border_color", "#ccc"))
PDF_TABLE_HEADER_FONT_SIZE_PT = cfg_float(PDF_DEFAULTS, "table_header_font_size_pt", 9)
PDF_TABLE_CELL_FONT_SIZE_PT = cfg_float(PDF_DEFAULTS, "table_cell_font_size_pt", 8.5)
PDF_DIAGRAM_MAX_HEIGHT_PX = cfg_int(PDF_DEFAULTS, "diagram_max_height_px", DIAGRAM_PDF_MAX_HEIGHT_PX)
PDF_DIAGRAM_SINGLE_PAGE = cfg_bool(PDF_DEFAULTS, "diagram_single_page", True)
PDF_DIAGRAM_PAGE_BREAK_BEFORE = cfg_bool(PDF_DEFAULTS, "diagram_page_break_before", False)
PDF_DIAGRAM_PAGE_BREAK_AFTER = cfg_bool(PDF_DEFAULTS, "diagram_page_break_after", True)


# ---------------------------------------------------------------------
# Resolved TOC defaults
# ---------------------------------------------------------------------
TOC_ENABLED = cfg_bool(TOC_DEFAULTS, "enabled", True)
TOC_CLICKABLE = cfg_bool(TOC_DEFAULTS, "clickable", True)
TOC_INCLUDE_HEADING_LEVELS = cfg_list_int(TOC_DEFAULTS, "include_heading_levels", [2, 3, 4])
TOC_FONT_SIZE_PT = cfg_float(TOC_DEFAULTS, "font_size_pt", 9.5)
TOC_LINE_HEIGHT = cfg_float(TOC_DEFAULTS, "line_height", 1.35)
TOC_INDENT_PX = cfg_int(TOC_DEFAULTS, "indent_px", 16)
TOC_LINK_COLOR = str(cfg_get(TOC_DEFAULTS, "link_color", DOCUMENT_LINK_COLOR))
TOC_UNDERLINE_LINKS = cfg_bool(TOC_DEFAULTS, "underline_links", True)
TOC_LEVEL_2_BOLD = cfg_bool(TOC_DEFAULTS, "level_2_bold", True)
TOC_LEVEL_4_FONT_SIZE_PT = cfg_float(TOC_DEFAULTS, "level_4_font_size_pt", 9)


# ---------------------------------------------------------------------
# Resolved DOCX defaults
# ---------------------------------------------------------------------
DOCX_FONT_NAME = str(cfg_get(DOCX_DEFAULTS, "font_name", "Calibri"))
DOCX_FONT_SIZE_PT = cfg_int(DOCX_DEFAULTS, "font_size_pt", 10)
DOCX_TOP_MARGIN_IN = cfg_float(DOCX_DEFAULTS, "top_margin_in", 0.65)
DOCX_BOTTOM_MARGIN_IN = cfg_float(DOCX_DEFAULTS, "bottom_margin_in", 0.65)
DOCX_LEFT_MARGIN_IN = cfg_float(DOCX_DEFAULTS, "left_margin_in", 0.7)
DOCX_RIGHT_MARGIN_IN = cfg_float(DOCX_DEFAULTS, "right_margin_in", 0.7)
DOCX_LOGO_WIDTH_IN = cfg_float(DOCX_DEFAULTS, "logo_width_in", 2.0)
DOCX_MAX_IMAGE_WIDTH_FALLBACK_IN = cfg_float(DOCX_DEFAULTS, "max_image_width_fallback_in", 6.2)
DOCX_MAX_IMAGE_HEIGHT_FALLBACK_IN = cfg_float(DOCX_DEFAULTS, "max_image_height_fallback_in", 8.0)
DOCX_TOC_OUTLINE = str(cfg_get(DOCX_DEFAULTS, "toc_outline", "1-3"))
DOCX_UPDATE_FIELDS_ON_OPEN = cfg_bool(DOCX_DEFAULTS, "update_fields_on_open", True)
DOCX_DIAGRAM_SINGLE_PAGE = cfg_bool(DOCX_DEFAULTS, "diagram_single_page", True)
DOCX_DIAGRAM_PAGE_BREAK_BEFORE = cfg_bool(DOCX_DEFAULTS, "diagram_page_break_before", False)
DOCX_DIAGRAM_PAGE_BREAK_AFTER = cfg_bool(DOCX_DEFAULTS, "diagram_page_break_after", True)
DOCX_DIAGRAM_LEGEND_ENABLED = cfg_bool(DOCX_DEFAULTS, "diagram_legend_enabled", True)
DOCX_DIAGRAM_LEGEND_MAX_WIDTH_IN = cfg_float(DOCX_DEFAULTS, "diagram_legend_max_width_in", DOCX_MAX_IMAGE_WIDTH_FALLBACK_IN)


# ---------------------------------------------------------------------
# Resolved DOCX editable diagram defaults
# ---------------------------------------------------------------------
DOCX_EDITABLE_DIAGRAMS_ENABLED = cfg_bool(DOCX_EDITABLE_DIAGRAM_DEFAULTS, "enabled", True)
DOCX_EDITABLE_DIAGRAMS_MODE = str(cfg_get(DOCX_EDITABLE_DIAGRAM_DEFAULTS, "mode", "svg")).strip().lower()
DOCX_EDITABLE_DIAGRAMS_FALLBACK_MODE = str(cfg_get(DOCX_EDITABLE_DIAGRAM_DEFAULTS, "fallback_mode", "png")).strip().lower()
DOCX_EMBED_SVG_INSTEAD_OF_PNG = cfg_bool(DOCX_EDITABLE_DIAGRAM_DEFAULTS, "embed_svg_instead_of_png", True)
DOCX_PREFER_SVG_ICONS = cfg_bool(DOCX_EDITABLE_DIAGRAM_DEFAULTS, "prefer_svg_icons", True)
DOCX_SHOW_EDITABLE_DIAGRAM_INSTRUCTION = cfg_bool(DOCX_EDITABLE_DIAGRAM_DEFAULTS, "show_user_instruction", True)
DOCX_KEEP_DIAGRAM_SOURCE_LINKS = cfg_bool(DOCX_EDITABLE_DIAGRAM_DEFAULTS, "keep_source_links", True)
DOCX_EDITABLE_DIAGRAM_INSTRUCTION_TEXT = str(
    cfg_get(
        DOCX_EDITABLE_DIAGRAM_DEFAULTS,
        "instruction_text",
        (
            "This diagram is inserted as SVG for better editability. "
            "To edit it in Microsoft Word, select the diagram, then use "
            "Graphics Format > Convert to Shape where supported."
        ),
    )
)
