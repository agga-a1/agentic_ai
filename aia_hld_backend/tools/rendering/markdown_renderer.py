from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import Any, Dict, Optional

from PIL import Image, ImageDraw, ImageFont

from .graphviz_renderer import (
    inline_image_token,
    normalize_to_graphviz_dot,
    render_graphviz_to_png,
    render_legend_diagram,
)
from .schema_utils import (
    METADATA_SECTIONS,
    is_simple_metadata_dict,
    should_include_section,
)
from .text_sanitizer import (
    clean_cell_text,
    format_paragraph_points,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Internal PDF-only tokens
# ---------------------------------------------------------------------
PDF_SECTION_BLOCK_START_TOKEN = "AIASECTIONBLOCKSTARTTOKEN"
PDF_SECTION_BLOCK_END_TOKEN = "AIASECTIONBLOCKENDTOKEN"


# ---------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------
def clean_internal_tokens(text: Any) -> str:
    """
    Defensive cleanup so internal renderer tokens never leak into final content.

    This is especially important if the same markdown generation is reused
    by DOCX or preview renderers.
    """
    value = str(text or "")

    tokens = [
        PDF_SECTION_BLOCK_START_TOKEN,
        PDF_SECTION_BLOCK_END_TOKEN,
        "[[AIASECTIONBLOCKSTARTTOKEN]]",
        "[[AIASECTIONBLOCKENDTOKEN]]",
        "SECTION_BLOCK_START",
        "SECTION_BLOCK_END",
        "[[SECTION_BLOCK_START]]",
        "[[SECTION_BLOCK_END]]",
        "[[SECTIONBLOCKSTART]]",
        "[[SECTIONBLOCKEND]]",
    ]

    for token in tokens:
        value = value.replace(token, "")

    return value.strip()


def wrap_section_block(
    title: str,
    content: str,
    enable_pdf_section_blocks: bool = True,
) -> str:
    """
    Wrap a subsection heading and its content as one keep-together block.

    For PDF:
      Adds internal tokens that pdf_renderer.py converts into:
        <div class="section-block">...</div>

    For DOCX or non-PDF:
      Does not add any internal token, so tokens cannot appear in the document.
    """
    normal_block = (
        f"\n\n### {title}\n\n"
        f"{content}"
        "\n\n"
    )

    if not enable_pdf_section_blocks:
        return normal_block

    return (
        f"\n\n{PDF_SECTION_BLOCK_START_TOKEN}\n\n"
        f"### {title}\n\n"
        f"{content}"
        f"\n\n{PDF_SECTION_BLOCK_END_TOKEN}\n\n"
    )


def _is_empty_or_na(value: Any) -> bool:
    """
    Detect empty / N/A values.

    Used mainly to avoid rendering RAID Issues as plain N/A.
    """
    if value is None:
        return True

    if isinstance(value, str):
        return value.strip().lower() in {
            "",
            "n/a",
            "na",
            "none",
            "null",
            "not applicable",
        }

    if isinstance(value, list):
        return len(value) == 0

    if isinstance(value, dict):
        return len(value) == 0

    return False


def _default_issues_rows() -> list[dict[str, str]]:
    """
    Default RAID Issues row when no issues are provided.
    """
    return [
        {
            "id": "I001",
            "description": "TBC - No issues have been identified at draft stage.",
            "status": "Open",
            "mitigation": "TBC",
        }
    ]


def _safe_base_name(value: str) -> str:
    safe_base = re.sub(
        r"[^a-zA-Z0-9_-]+",
        "_",
        str(value or "diagram_block"),
    ).strip("_").lower()

    return safe_base or "diagram_block"


def _build_logo_html(logo_data_uri: str = "") -> str:
    """
    Build logo HTML safely.

    Accepted inputs:
      - full <img ...> HTML
      - raw data:image/png;base64,...
      - empty string

    This prevents raw base64/data URI from appearing as text on the PDF front page.
    """
    logo_value = str(logo_data_uri or "").strip()

    if not logo_value:
        return ""

    if logo_value.lower().startswith("<img"):
        return logo_value

    if logo_value.lower().startswith("data:image"):
        return (
            f'<img src="{logo_value}" '
            f'alt="Universal Logo" '
            f'style="max-height: 700px; max-width: 100%; margin-bottom: 20px;" />'
        )

    # Fallback: treat as already prepared content, but escape to avoid malformed HTML.
    return html.escape(logo_value)


# ---------------------------------------------------------------------
# PDF diagram block image helpers
# ---------------------------------------------------------------------
def _trim_white_margin(
    image: Image.Image,
    background_threshold: int = 248,
    padding_px: int = 12,
) -> Image.Image:
    """
    Trim excessive white margins from diagram/legend images.

    This helps the final PDF use page space better.
    """
    img = image.convert("RGB")
    pixels = img.load()

    width, height = img.size

    left = width
    top = height
    right = 0
    bottom = 0

    for y in range(height):
        for x in range(width):
            r, g, b = pixels[x, y]

            if not (
                r >= background_threshold
                and g >= background_threshold
                and b >= background_threshold
            ):
                left = min(left, x)
                top = min(top, y)
                right = max(right, x)
                bottom = max(bottom, y)

    if right <= left or bottom <= top:
        return image

    left = max(0, left - padding_px)
    top = max(0, top - padding_px)
    right = min(width, right + padding_px)
    bottom = min(height, bottom + padding_px)

    return image.crop((left, top, right, bottom))


def _load_pdf_heading_font(size: int = 34):
    """
    Load a readable heading font for the diagram block image.

    Falls back safely if system fonts are unavailable.
    """
    candidates = [
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]

    for font_path in candidates:
        try:
            if Path(font_path).exists():
                return ImageFont.truetype(font_path, size=size)
        except Exception:
            pass

    return ImageFont.load_default()


def create_pdf_diagram_block_image(
    heading: str,
    diagram_path: str,
    legend_path: Optional[str] = None,
    output_dir: Optional[str | Path] = None,
    base_name: str = "diagram_block",
    parent_heading: Optional[str] = None,
) -> str:
    """
    Create one combined PNG containing:
      - optional parent heading, e.g. Architecture Design Views
      - diagram heading, e.g. Logical View
      - main diagram
      - Flow Legend image, if available

    This keeps parent heading + diagram heading + diagram + legend together
    on one PDF page.
    """
    output_dir = Path(output_dir or Path(diagram_path).parent)
    output_dir.mkdir(parents=True, exist_ok=True)

    heading_text = str(heading or "Diagram").strip()
    parent_heading_text = str(parent_heading or "").strip()

    diagram_img = Image.open(diagram_path).convert("RGBA")
    diagram_img = _trim_white_margin(diagram_img)

    legend_img = None

    if legend_path and Path(legend_path).exists():
        legend_img = Image.open(legend_path).convert("RGBA")
        legend_img = _trim_white_margin(legend_img)

    page_width_px = 1600
    margin_x = 70
    margin_y = 44
    gap_after_parent_heading = 22
    gap_after_heading = 28
    gap_between_diagram_and_legend = 26

    max_content_width = page_width_px - (2 * margin_x)

    def scale_to_width(
        img: Image.Image,
        max_width: int,
    ) -> Image.Image:
        if img.width <= max_width:
            return img

        ratio = max_width / float(img.width)
        new_size = (
            int(img.width * ratio),
            int(img.height * ratio),
        )

        return img.resize(new_size, Image.LANCZOS)

    diagram_img = scale_to_width(
        diagram_img,
        max_content_width,
    )

    if legend_img:
        legend_img = scale_to_width(
            legend_img,
            max_content_width,
        )

    parent_font = _load_pdf_heading_font(size=32)
    heading_font = _load_pdf_heading_font(size=34)

    temp_canvas = Image.new(
        "RGBA",
        (page_width_px, 300),
        "white",
    )
    draw = ImageDraw.Draw(temp_canvas)

    parent_heading_h = 0
    heading_h = 44

    if parent_heading_text:
        try:
            parent_bbox = draw.textbbox(
                (0, 0),
                parent_heading_text,
                font=parent_font,
            )
            parent_heading_h = parent_bbox[3] - parent_bbox[1]
        except Exception:
            parent_heading_h = 40

    try:
        heading_bbox = draw.textbbox(
            (0, 0),
            heading_text,
            font=heading_font,
        )
        heading_h = heading_bbox[3] - heading_bbox[1]
    except Exception:
        heading_h = 44

    total_height = margin_y

    if parent_heading_text:
        total_height += parent_heading_h + gap_after_parent_heading

    total_height += (
        heading_h
        + gap_after_heading
        + diagram_img.height
        + margin_y
    )

    if legend_img:
        total_height += gap_between_diagram_and_legend + legend_img.height

    canvas = Image.new(
        "RGBA",
        (page_width_px, total_height),
        "white",
    )

    draw = ImageDraw.Draw(canvas)

    current_y = margin_y

    if parent_heading_text:
        draw.text(
            (margin_x, current_y),
            parent_heading_text,
            fill="#1F4E79",
            font=parent_font,
        )

        parent_underline_y = current_y + parent_heading_h + 10
        draw.line(
            (
                margin_x,
                parent_underline_y,
                page_width_px - margin_x,
                parent_underline_y,
            ),
            fill="#1F4E79",
            width=2,
        )

        current_y += parent_heading_h + gap_after_parent_heading

    # Left-aligned diagram heading.
    draw.text(
        (margin_x, current_y),
        heading_text,
        fill="#E60000",
        font=heading_font,
    )

    underline_y = current_y + heading_h + 12

    draw.line(
        (
            margin_x,
            underline_y,
            page_width_px - margin_x,
            underline_y,
        ),
        fill="#E60000",
        width=3,
    )

    current_y += heading_h + gap_after_heading

    diagram_x = (page_width_px - diagram_img.width) // 2

    canvas.paste(
        diagram_img,
        (diagram_x, current_y),
        diagram_img,
    )

    current_y += diagram_img.height

    if legend_img:
        current_y += gap_between_diagram_and_legend

        legend_x = (page_width_px - legend_img.width) // 2

        canvas.paste(
            legend_img,
            (legend_x, current_y),
            legend_img,
        )

    safe_base = _safe_base_name(base_name)

    out_path = output_dir / f"{safe_base}_pdf_block.png"

    canvas.convert("RGB").save(
        out_path,
        "PNG",
    )

    return str(out_path)


# ---------------------------------------------------------------------
# Markdown table helpers
# ---------------------------------------------------------------------
def render_metadata_table(data: Dict[str, Any]) -> str:
    if not data:
        return "N/A\n\n"

    keys = list(data.keys())

    md = (
        "\n\n| "
        + " | ".join(k.replace("_", " ").title() for k in keys)
        + " |\n"
        + "| "
        + " | ".join("---" for _ in keys)
        + " |\n"
    )

    md += (
        "| "
        + " | ".join(
            clean_cell_text(
                data.get(k, ""),
                False,
            )
            for k in keys
        )
        + " |\n\n"
    )

    return md


def render_dict_list_as_table(items: list) -> str:
    if not items or not isinstance(items[0], dict):
        return "N/A\n\n"

    keys = []

    for row in items:
        for key in row.keys():
            if key not in keys:
                keys.append(key)

    md = (
        "\n\n| "
        + " | ".join(k.replace("_", " ").title() for k in keys)
        + " |\n"
        + "| "
        + " | ".join("---" for _ in keys)
        + " |\n"
    )

    for row in items:
        md += (
            "| "
            + " | ".join(
                clean_cell_text(
                    row.get(k, ""),
                    False,
                )
                for k in keys
            )
            + " |\n"
        )

    return md + "\n\n"


# ---------------------------------------------------------------------
# Diagram rendering helper for Markdown/PDF flow
# ---------------------------------------------------------------------
def render_diagram_as_pdf_block(
    diagram_text: str,
    section_key: Optional[str] = None,
    section_title: Optional[str] = None,
    parent_section_title: Optional[str] = None,
) -> str:
    """
    Render a diagram as a single combined PDF image block.

    The generated image includes:
      - optional parent heading
      - diagram heading
      - diagram
      - Flow Legend

    This prevents PDF from splitting heading, diagram, and legend
    across different pages.
    """
    diagram_result = render_graphviz_to_png(diagram_text)

    if not diagram_result:
        return (
            "**[Diagram rendering failed]**<br/>"
            "The diagram source was detected but could not be rendered by Graphviz. "
            "Please check renderer logs.\n\n"
        )

    diagram_path, legend = diagram_result

    legend_path = render_legend_diagram(legend) if legend else None

    heading = (
        section_title
        or (section_key.replace("_", " ").title() if section_key else "Diagram")
    )

    combined_block_path = create_pdf_diagram_block_image(
        heading=heading,
        parent_heading=parent_section_title,
        diagram_path=diagram_path,
        legend_path=legend_path,
        output_dir=Path(diagram_path).parent,
        base_name=section_key or heading,
    )

    return inline_image_token(combined_block_path) + "\n\n"


def _contains_nested_diagram(value: Any) -> bool:
    """
    Return True if a dict/list subtree contains a 'diagrams' key
    or any Graphviz/Mermaid diagram string.
    """
    if isinstance(value, str):
        return normalize_to_graphviz_dot(value) is not None

    if isinstance(value, list):
        return any(_contains_nested_diagram(item) for item in value)

    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() == "diagrams":
                return True

            if _contains_nested_diagram(child):
                return True

    return False


# ---------------------------------------------------------------------
# Recursive Markdown value renderer
# ---------------------------------------------------------------------
def render_value(
    val: Any,
    section_key: Optional[str] = None,
    section_title: Optional[str] = None,
    parent_section_title: Optional[str] = None,
    include_parent_heading_once: bool = False,
    enable_pdf_section_blocks: bool = True,
) -> str:
    if val is None:
        return "N/A\n\n"

    if (
        isinstance(val, dict)
        and section_key in METADATA_SECTIONS
        and is_simple_metadata_dict(val)
    ):
        return render_metadata_table(val)

    if isinstance(val, str):
        clean_val = clean_internal_tokens(val)

        is_diagram = normalize_to_graphviz_dot(clean_val) is not None

        if is_diagram:
            return render_diagram_as_pdf_block(
                diagram_text=clean_val,
                section_key=section_key,
                section_title=section_title,
                parent_section_title=(
                    parent_section_title
                    if include_parent_heading_once
                    else None
                ),
            )

        return format_paragraph_points(clean_val) + "\n\n"

    if isinstance(val, list):
        if not val:
            return "N/A\n\n"

        if all(
            isinstance(item, str)
            and normalize_to_graphviz_dot(clean_internal_tokens(item))
            for item in val
        ):
            rendered_items = []

            for idx, item in enumerate(val):
                rendered_items.append(
                    render_value(
                        item,
                        section_key=section_key,
                        section_title=section_title,
                        parent_section_title=parent_section_title,
                        include_parent_heading_once=(
                            include_parent_heading_once
                            and idx == 0
                        ),
                        enable_pdf_section_blocks=enable_pdf_section_blocks,
                    )
                )

            return "".join(rendered_items)

        if all(isinstance(item, dict) for item in val):
            return render_dict_list_as_table(val)

        return (
            "\n"
            + "\n".join(
                f"- {clean_cell_text(clean_internal_tokens(item))}"
                for item in val
            )
            + "\n\n"
        )

    if isinstance(val, dict):
        output_parts: list[str] = []
        parent_heading_pending = include_parent_heading_once

        for key, child_value in val.items():
            key_lower = str(key).lower()
            child_title = str(key).replace("_", " ").title()

            # RAID Issues default.
            if key_lower == "issues" and _is_empty_or_na(child_value):
                output_parts.append(
                    wrap_section_block(
                        title=child_title,
                        content=render_dict_list_as_table(_default_issues_rows()),
                        enable_pdf_section_blocks=enable_pdf_section_blocks,
                    )
                )
                continue

            # Do not add a separate "Diagrams" heading.
            # The combined image already contains the actual heading.
            if key_lower == "diagrams":
                output_parts.append(
                    render_value(
                        child_value,
                        section_key=section_key,
                        section_title=section_title,
                        parent_section_title=parent_section_title,
                        include_parent_heading_once=parent_heading_pending,
                        enable_pdf_section_blocks=enable_pdf_section_blocks,
                    )
                )
                parent_heading_pending = False
                continue

            child_has_diagrams = isinstance(child_value, dict) and any(
                str(k).lower() == "diagrams"
                for k in child_value.keys()
            )

            # If child dict contains diagrams, render only the combined diagram block.
            # Do not add a markdown heading before it because that can split from
            # the image in PDF.
            if child_has_diagrams:
                output_parts.append(
                    render_value(
                        child_value,
                        section_key=key,
                        section_title=child_title,
                        parent_section_title=parent_section_title,
                        include_parent_heading_once=parent_heading_pending,
                        enable_pdf_section_blocks=enable_pdf_section_blocks,
                    )
                )
                parent_heading_pending = False
                continue

            child_content = render_value(
                child_value,
                section_key=key,
                section_title=child_title,
                parent_section_title=None,
                include_parent_heading_once=False,
                enable_pdf_section_blocks=enable_pdf_section_blocks,
            )

            output_parts.append(
                wrap_section_block(
                    title=child_title,
                    content=child_content,
                    enable_pdf_section_blocks=enable_pdf_section_blocks,
                )
            )

        # Insert exactly one page break between sibling diagram blocks.
        # This avoids blank pages caused by CSS page-break-after plus markdown
        # page-break-token both firing.
        final_output = ""

        for idx, part in enumerate(output_parts):
            final_output += part

            is_last = idx == len(output_parts) - 1

            if not is_last:
                current_part_is_diagram_block = "IMAGE_TOKEN_START" in part

                next_part = output_parts[idx + 1]
                next_part_is_diagram_block = "IMAGE_TOKEN_START" in next_part

                if current_part_is_diagram_block or next_part_is_diagram_block:
                    final_output += "\n\nPAGE_BREAK_TOKEN\n\n"

        return final_output

    return html.escape(clean_internal_tokens(str(val))) + "\n\n"


# ---------------------------------------------------------------------
# Main Markdown master builder
# ---------------------------------------------------------------------
def build_markdown_master(
    data: Dict[str, Any],
    hld_model: Any,
    selected_sections_set: set[str],
    logo_data_uri: str = "",
    enable_pdf_section_blocks: bool = True,
) -> str:
    """
    Build Markdown master.

    enable_pdf_section_blocks:
      True  -> PDF flow; section keep-together tokens are emitted.
      False -> DOCX / non-PDF flow; no internal section tokens are emitted.
    """
    logo = _build_logo_html(logo_data_uri)

    md = (
        '<div style="text-align: center; page-break-inside: avoid;">\n'
        f"  {logo}\n"
        '  <h1 style="color: #E60000; border-bottom: 1px solid #E60000; '
        'padding-bottom: 4px; margin-top: 0;">'
        "Universal High Level Design (HLD)"
        "</h1>\n"
        "</div>\n\n"
        "PAGE_BREAK_TOKEN\n\n"
        "## Table of Contents\n\n"
        "[[toc]]\n\n"
        "PAGE_BREAK_TOKEN\n\n"
    )

    first = True

    for field_name, field_info in hld_model.model_fields.items():
        title = field_info.title or field_name.replace("_", " ").title()

        if not should_include_section(
            field_name,
            field_info,
            selected_sections_set,
        ):
            continue

        if not first:
            md += "\n\nPAGE_BREAK_TOKEN\n\n"

        first = False

        section_value = data.get(field_name)

        section_has_nested_diagrams = (
            isinstance(section_value, dict)
            and _contains_nested_diagram(section_value)
        )

        # PDF flow:
        #   Parent section heading is embedded inside first combined diagram image,
        #   so we do not render parent markdown heading separately.
        if section_has_nested_diagrams and enable_pdf_section_blocks:
            # Emit real parent heading so it appears in PDF and TOC.
            # Do not embed parent heading inside the image again, otherwise it appears twice.
            md += f"## {title}\n\n"

            md += render_value(
                section_value,
                section_key=field_name,
                section_title=title,
                parent_section_title=None,
                include_parent_heading_once=False,
                enable_pdf_section_blocks=enable_pdf_section_blocks,
            )
            continue

        # DOCX / normal flow:
        #   Keep parent heading as normal markdown and do not emit PDF tokens.
        md += (
            f"## {title}\n\n"
            + render_value(
                section_value,
                section_key=field_name,
                section_title=title,
                parent_section_title=None,
                include_parent_heading_once=False,
                enable_pdf_section_blocks=enable_pdf_section_blocks,
            )
        )

    return md