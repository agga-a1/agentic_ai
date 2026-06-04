from __future__ import annotations

import base64
import html
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

import markdown2
from xhtml2pdf import pisa

from .config import (
    DOCUMENT_TITLE,
    DOCUMENT_FONT_FAMILY,
    DOCUMENT_FONT_SIZE_PT,
    DOCUMENT_PRIMARY_COLOR,
    DOCUMENT_BODY_COLOR,
    DOCUMENT_LINK_COLOR,
    PDF_PAGE_SIZE,
    PDF_PAGE_MARGIN_CM,
    PDF_PARAGRAPH_LINE_HEIGHT,
    PDF_TABLE_MARGIN,
    PDF_TABLE_HEADER_BACKGROUND,
    PDF_TABLE_BORDER_COLOR,
    PDF_TABLE_HEADER_FONT_SIZE_PT,
    PDF_TABLE_CELL_FONT_SIZE_PT,
    PDF_DIAGRAM_MAX_HEIGHT_PX,
    PDF_DIAGRAM_SINGLE_PAGE,
    PDF_DIAGRAM_PAGE_BREAK_BEFORE,
    PDF_DIAGRAM_PAGE_BREAK_AFTER,
    TOC_ENABLED,
    TOC_CLICKABLE,
    TOC_INCLUDE_HEADING_LEVELS,
    TOC_FONT_SIZE_PT,
    TOC_LINE_HEIGHT,
    TOC_INDENT_PX,
    TOC_LINK_COLOR,
    TOC_UNDERLINE_LINKS,
    TOC_LEVEL_2_BOLD,
    TOC_LEVEL_4_FONT_SIZE_PT,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Internal marker tokens
# ---------------------------------------------------------------------
PDF_SECTION_BLOCK_START_TOKEN = "AIASECTIONBLOCKSTARTTOKEN"
PDF_SECTION_BLOCK_END_TOKEN = "AIASECTIONBLOCKENDTOKEN"


# ---------------------------------------------------------------------
# Image token handling
# ---------------------------------------------------------------------
def image_token_to_html(match):
    """
    Convert IMAGE_TOKEN_START...IMAGE_TOKEN_END placeholders into inline
    base64 image HTML that xhtml2pdf can embed into the generated PDF.

    If PDF_DIAGRAM_SINGLE_PAGE is enabled:
      - diagram is wrapped in a single-page block
      - page break before/after is controlled by config.py/render_defaults.json
    """
    path = str(match.group(1) or "").strip()

    try:
        with open(path, "rb") as image_file:
            encoded = base64.b64encode(image_file.read()).decode("utf-8")

        wrapper_classes = (
            "diagram-wrap diagram-single-page"
            if PDF_DIAGRAM_SINGLE_PAGE
            else "diagram-wrap"
        )

        return (
            f'<div class="{wrapper_classes}">'
            f'<img src="data:image/png;base64,{encoded}" alt="Diagram"/>'
            "</div>"
        )

    except Exception:
        logger.exception(
            "Failed to inline image into PDF/HTML. path=%s",
            path,
        )
        return "<p>[Image Error]</p>"


# ---------------------------------------------------------------------
# Clickable TOC helpers
# ---------------------------------------------------------------------
def _slugify_heading(
    text: str,
    used: dict[str, int],
) -> str:
    """
    Create deterministic PDF-safe anchor IDs.

    Example:
      Architecture Design Views -> architecture-design-views

    Duplicate headings get suffixes:
      overview
      overview-2
      overview-3
    """
    raw = html.unescape(str(text or "")).strip().lower()

    raw = re.sub(r"<[^>]+>", "", raw)
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = raw.strip("-")

    if not raw:
        raw = "section"

    count = used.get(raw, 0) + 1
    used[raw] = count

    if count > 1:
        return f"{raw}-{count}"

    return raw


def _strip_markdown_heading_markup(text: str) -> str:
    """
    Remove basic markdown emphasis/link markup from headings for clean TOC labels.
    """
    text = str(text or "").strip()

    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"__(.*?)__", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)

    # Convert markdown links: [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    return html.unescape(text).strip()


def _toc_level_enabled(level: int) -> bool:
    """
    Decide whether a heading level should be included in the generated PDF TOC.
    Levels are controlled by TOC_INCLUDE_HEADING_LEVELS from config.py.
    """
    return level in TOC_INCLUDE_HEADING_LEVELS


def _inject_pdf_anchors_and_build_toc(
    md_master: str,
) -> tuple[str, str]:
    """
    Inject explicit named anchors before markdown headings and build a clickable TOC.

    xhtml2pdf is more reliable with explicit:
      <a name="section-id" id="section-id"></a>
      <a href="#section-id">Title</a>

    than relying on markdown2's generated TOC.
    """
    used_slugs: dict[str, int] = {}
    toc_items: list[tuple[int, str, str]] = []
    output_lines: list[str] = []

    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

    for line in md_master.splitlines():
        match = heading_re.match(line)

        if not match:
            output_lines.append(line)
            continue

        level = len(match.group(1))
        heading_text = _strip_markdown_heading_markup(match.group(2))

        # Do not include the TOC heading itself in the TOC.
        if heading_text.lower() == "table of contents":
            output_lines.append(line)
            continue

        anchor_id = _slugify_heading(
            heading_text,
            used_slugs,
        )

        # Explicit anchor for internal PDF navigation.
        output_lines.append(
            f'<a name="{anchor_id}" id="{anchor_id}"></a>'
        )
        output_lines.append(line)

        if TOC_ENABLED and _toc_level_enabled(level):
            toc_items.append(
                (
                    level,
                    heading_text,
                    anchor_id,
                )
            )

    if not toc_items:
        return "\n".join(output_lines), ""

    toc_lines = [
        '<div class="pdf-toc">',
        "<ul>",
    ]

    previous_level = toc_items[0][0]
    base_level = previous_level

    for level, title, anchor_id in toc_items:
        if level > previous_level:
            for _ in range(level - previous_level):
                toc_lines.append("<ul>")
        elif level < previous_level:
            for _ in range(previous_level - level):
                toc_lines.append("</ul>")

        safe_title = html.escape(title)

        if TOC_CLICKABLE:
            title_html = f'<a href="#{anchor_id}">{safe_title}</a>'
        else:
            title_html = safe_title

        toc_lines.append(
            f'<li class="toc-level-{level}">'
            f"{title_html}"
            f"</li>"
        )

        previous_level = level

    for _ in range(previous_level - base_level):
        toc_lines.append("</ul>")

    toc_lines.append("</ul>")
    toc_lines.append("</div>")

    return "\n".join(output_lines), "\n".join(toc_lines)


# ---------------------------------------------------------------------
# HTML cleanup helpers
# ---------------------------------------------------------------------
def _replace_page_break_tokens(html_body: str) -> str:
    """
    Convert PAGE_BREAK placeholders after markdown conversion.
    """
    replacements = {
        "<p>[[PAGE_BREAK]]</p>": '<div class="page-break"></div>',
        "<p>[[PAGE_BREAK]]</p>\n": '<div class="page-break"></div>\n',
        "[[PAGE_BREAK]]": '<div class="page-break"></div>',
    }

    for old, new in replacements.items():
        html_body = html_body.replace(old, new)

    return html_body


def _replace_section_block_tokens(html_body: str) -> str:
    """
    Convert generic keep-together section markers into HTML blocks.

    Supports:
      - new tokens:
          AIASECTIONBLOCKSTARTTOKEN
          AIASECTIONBLOCKENDTOKEN

      - legacy tokens:
          SECTION_BLOCK_START
          SECTION_BLOCK_END
          [[SECTIONBLOCKSTART]]
          [[SECTIONBLOCKEND]]
    """
    replacements = {
        # New token forms after markdown2 paragraph wrapping.
        "<p>[[AIASECTIONBLOCKSTARTTOKEN]]</p>": '<div class="section-block">',
        "<p>[[AIASECTIONBLOCKENDTOKEN]]</p>": "</div>",
        "<p>AIASECTIONBLOCKSTARTTOKEN</p>": '<div class="section-block">',
        "<p>AIASECTIONBLOCKENDTOKEN</p>": "</div>",

        # New token raw forms.
        "[[AIASECTIONBLOCKSTARTTOKEN]]": '<div class="section-block">',
        "[[AIASECTIONBLOCKENDTOKEN]]": "</div>",
        "AIASECTIONBLOCKSTARTTOKEN": '<div class="section-block">',
        "AIASECTIONBLOCKENDTOKEN": "</div>",

        # Legacy underscore token forms.
        "<p>[[SECTION_BLOCK_START]]</p>": '<div class="section-block">',
        "<p>[[SECTION_BLOCK_END]]</p>": "</div>",
        "<p>SECTION_BLOCK_START</p>": '<div class="section-block">',
        "<p>SECTION_BLOCK_END</p>": "</div>",
        "[[SECTION_BLOCK_START]]": '<div class="section-block">',
        "[[SECTION_BLOCK_END]]": "</div>",
        "SECTION_BLOCK_START": '<div class="section-block">',
        "SECTION_BLOCK_END": "</div>",

        # Broken legacy forms caused by markdown underscore emphasis handling.
        "<p>[[SECTIONBLOCKSTART]]</p>": '<div class="section-block">',
        "<p>[[SECTIONBLOCKEND]]</p>": "</div>",
        "[[SECTIONBLOCKSTART]]": '<div class="section-block">',
        "[[SECTIONBLOCKEND]]": "</div>",
    }

    for old, new in replacements.items():
        html_body = html_body.replace(old, new)

    return html_body


def _cleanup_empty_section_block_paragraphs(html_body: str) -> str:
    """
    Remove empty paragraphs that may appear around converted block tokens.
    """
    html_body = html_body.replace("<p></p>", "")
    html_body = html_body.replace("<p> </p>", "")
    return html_body


# ---------------------------------------------------------------------
# CSS builder from resolved config constants
# ---------------------------------------------------------------------
def _build_css() -> str:
    """
    Build PDF CSS using resolved constants from config.py.

    Important:
    - No '%' string formatting is used.
    - CSS contains values like width: 100%, so old-style '%' formatting
      must never be used here.
    - Renderer does not define fallback defaults. Defaults belong in config.py.
    """
    toc_underline = "underline" if TOC_UNDERLINE_LINKS else "none"
    toc_level_2_weight = "bold" if TOC_LEVEL_2_BOLD else "normal"

    diagram_page_break_before = (
        "always"
        if PDF_DIAGRAM_SINGLE_PAGE and PDF_DIAGRAM_PAGE_BREAK_BEFORE
        else "auto"
    )

    diagram_page_break_after = (
        "always"
        if PDF_DIAGRAM_SINGLE_PAGE and PDF_DIAGRAM_PAGE_BREAK_AFTER
        else "auto"
    )

    return f"""
    <style>
      @page {{
        size: {PDF_PAGE_SIZE};
        margin: {PDF_PAGE_MARGIN_CM}cm;
      }}

      body {{
        font-family: {DOCUMENT_FONT_FAMILY};
        font-size: {DOCUMENT_FONT_SIZE_PT}pt;
        color: {DOCUMENT_BODY_COLOR};
        margin: 0;
        padding: 0;
      }}

      h1 {{
        color: {DOCUMENT_PRIMARY_COLOR};
        border-bottom: 1px solid {DOCUMENT_PRIMARY_COLOR};
        padding-bottom: 4px;
        margin-top: 0;
        page-break-after: avoid;
      }}

      h2 {{
        color: {DOCUMENT_PRIMARY_COLOR};
        border-bottom: 1px solid {DOCUMENT_PRIMARY_COLOR};
        padding-bottom: 3px;
        margin-top: 0;
        page-break-after: avoid;
      }}

      h3 {{
        color: #333;
        margin-top: 12px;
        page-break-after: avoid;
      }}

      h4 {{
        color: #333;
        margin-top: 10px;
        page-break-after: avoid;
      }}

      .section-block {{
        page-break-inside: avoid;
        margin-bottom: 8px;
      }}

      .section-block h3,
      .section-block h4 {{
        page-break-after: avoid;
      }}

      .page-break {{
        page-break-before: always;
        height: 0;
        margin: 0;
        padding: 0;
      }}

      .pdf-toc {{
        font-size: {TOC_FONT_SIZE_PT}pt;
        line-height: {TOC_LINE_HEIGHT};
      }}

      .pdf-toc ul {{
        margin-top: 2px;
        margin-bottom: 2px;
        padding-left: {TOC_INDENT_PX}px;
      }}

      .pdf-toc li {{
        margin-bottom: 2px;
      }}

      .pdf-toc a {{
        color: {TOC_LINK_COLOR};
        text-decoration: {toc_underline};
      }}

      .toc-level-2 {{
        font-weight: {toc_level_2_weight};
      }}

      .toc-level-3 {{
        font-weight: normal;
      }}

      .toc-level-4 {{
        font-size: {TOC_LEVEL_4_FONT_SIZE_PT}pt;
      }}

      p, ul, ol {{
        line-height: {PDF_PARAGRAPH_LINE_HEIGHT};
        page-break-inside: avoid;
        overflow-wrap: anywhere;
        word-break: break-word;
        white-space: normal;
      }}

      table {{
        width: 100%;
        border-collapse: collapse;
        margin: {PDF_TABLE_MARGIN};
        table-layout: fixed;
        page-break-inside: avoid;
      }}

      thead {{
        display: table-header-group;
      }}

      tr {{
        page-break-inside: avoid;
      }}

      th {{
        background: {PDF_TABLE_HEADER_BACKGROUND};
        padding: 6px;
        border: 1px solid {PDF_TABLE_BORDER_COLOR};
        font-size: {PDF_TABLE_HEADER_FONT_SIZE_PT}pt;
        word-wrap: break-word;
        overflow-wrap: anywhere;
        word-break: break-all;
        white-space: normal;
      }}

      td {{
        border: 1px solid {PDF_TABLE_BORDER_COLOR};
        padding: 6px;
        font-size: {PDF_TABLE_CELL_FONT_SIZE_PT}pt;
        vertical-align: top;
        word-wrap: break-word;
        overflow-wrap: anywhere;
        word-break: break-all;
        white-space: normal;
      }}

      .diagram-wrap {{
        width: 100%;
        text-align: center;
        margin: 10px 0 10px 0;
        page-break-inside: avoid;
      }}

      .diagram-single-page {{
        page-break-before: {diagram_page_break_before};
        page-break-after: {diagram_page_break_after};
        page-break-inside: avoid;
      }}

      .diagram-wrap img {{
        width: auto;
        height: auto;
        max-width: 100%;
        max-height: {PDF_DIAGRAM_MAX_HEIGHT_PX}px;
        object-fit: contain;
        display: inline-block;
      }}

      pre, code {{
        white-space: pre-wrap;
        word-wrap: break-word;
      }}

      a {{
        color: {DOCUMENT_LINK_COLOR};
      }}
    </style>
    """


# ---------------------------------------------------------------------
# HTML / PDF builder
# ---------------------------------------------------------------------
def build_html_content(md_master: str) -> str:
    """
    Build full HTML from Markdown master content.

    Features:
    - clickable PDF TOC using explicit named anchors
    - no markdown2 TOC dependency
    - no '%' CSS formatting issue
    - PDF styling is driven by config.py / render_defaults.json
    - generic section-block keep-together support
    """
    md_with_anchors, toc_html = _inject_pdf_anchors_and_build_toc(md_master)

    md_html = md_with_anchors.replace(
        "PAGE_BREAK_TOKEN",
        "\n\n[[PAGE_BREAK]]\n\n",
    )

    # Section keep-together markers.
    # Use tokens without underscores to avoid Markdown emphasis parsing issues.
    md_html = md_html.replace(
        PDF_SECTION_BLOCK_START_TOKEN,
        "\n\n[[AIASECTIONBLOCKSTARTTOKEN]]\n\n",
    )
    md_html = md_html.replace(
        PDF_SECTION_BLOCK_END_TOKEN,
        "\n\n[[AIASECTIONBLOCKENDTOKEN]]\n\n",
    )

    # Backward compatibility for old markers.
    md_html = md_html.replace(
        "SECTION_BLOCK_START",
        "\n\n[[SECTION_BLOCK_START]]\n\n",
    )
    md_html = md_html.replace(
        "SECTION_BLOCK_END",
        "\n\n[[SECTION_BLOCK_END]]\n\n",
    )

    # Replace TOC placeholder before markdown conversion.
    md_html = md_html.replace("[[toc]]", toc_html)

    # Inline rendered diagram images.
    md_html = re.sub(
        r"IMAGE_TOKEN_START(.*?)IMAGE_TOKEN_END",
        image_token_to_html,
        md_html,
        flags=re.DOTALL,
    )

    html_body = markdown2.markdown(
        md_html,
        extras=[
            "tables",
            "fenced-code-blocks",
        ],
    )

    html_body = str(html_body)

    html_body = _replace_page_break_tokens(html_body)
    html_body = _replace_section_block_tokens(html_body)
    html_body = _cleanup_empty_section_block_paragraphs(html_body)

    safe_document_title = html.escape(str(DOCUMENT_TITLE))
    css = _build_css()

    return f"""
    <html>
      <head>
        <meta charset="utf-8"/>
        <title>{safe_document_title}</title>
        {css}
      </head>
      <body>
        {html_body}
      </body>
    </html>
    """


def build_pdf(
    md_master: str,
    pdf_path: str,
    html_path: Optional[str] = None,
):
    """
    Generate PDF from Markdown master content.

    Also writes intermediate HTML if html_path is provided.
    """
    html_full = build_html_content(md_master)

    if html_path:
        Path(html_path).write_text(
            html_full,
            encoding="utf-8",
        )

    with open(pdf_path, "wb") as output_file:
        result = pisa.CreatePDF(
            BytesIO(html_full.encode("utf-8")),
            dest=output_file,
        )

    if result.err:
        raise RuntimeError("PDF generation failed via xhtml2pdf")