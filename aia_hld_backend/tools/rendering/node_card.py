# import hashlib, json, logging, tempfile, re
# from pathlib import Path
# from typing import Optional
# from PIL import Image, ImageDraw, ImageFont
# from .config import DIAGRAM_NODE_CARD_FONT_SIZE, DIAGRAM_NODE_CARD_SIZE
# logger=logging.getLogger(__name__)
# def normalize_icon_for_graphviz(icon_path: str, target_size: tuple[int,int]=(128,72)) -> str:
#     try:
#         tmp=Path(tempfile.gettempdir())/'aia_icon_cache'; tmp.mkdir(exist_ok=True); src=Path(icon_path); out=tmp/f'{src.stem}_{target_size[0]}x{target_size[1]}.png'
#         if out.exists(): return str(out)
#         with Image.open(src).convert('RGBA') as img:
#             canvas=Image.new('RGBA',target_size,(255,255,255,0)); img.thumbnail((target_size[0]-8,target_size[1]-8),Image.LANCZOS); canvas.paste(img,((target_size[0]-img.width)//2,(target_size[1]-img.height)//2),img); canvas.save(out)
#         return str(out)
#     except Exception: logger.exception('Failed to normalize icon: %s',icon_path); return icon_path
# def load_card_font(size:int,bold:bool=False):
#     candidates=['/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf','/System/Library/Fonts/Supplemental/Arial Bold.ttf' if bold else '/System/Library/Fonts/Supplemental/Arial.ttf','/Library/Fonts/Arial Bold.ttf' if bold else '/Library/Fonts/Arial.ttf']
#     for fp in candidates:
#         try:
#             if Path(fp).exists(): return ImageFont.truetype(fp,size=size)
#         except Exception: pass
#     return ImageFont.load_default()
# def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int,int]:
#     try: b=draw.textbbox((0,0),text,font=font); return b[2]-b[0],b[3]-b[1]
#     except Exception: return draw.textsize(text,font=font)
# def clean_label(label: str) -> str: return re.sub(r'\s+',' ',str(label or '').replace('\\n',' ').replace('\n',' ')).strip()
# def wrap_text_for_card(draw, text, font, max_width_px:int, max_lines:int=3) -> list[str]:
#     words=clean_label(text).split(); lines=[]; cur=[]
#     for word in words:
#         candidate=' '.join(cur+[word]).strip()
#         if text_size(draw,candidate,font)[0] <= max_width_px or not cur: cur.append(word)
#         else:
#             lines.append(' '.join(cur)); cur=[word]
#             if len(lines)>=max_lines-1: break
#     if cur: lines.append(' '.join(cur))
#     return lines[:max_lines] or ['']
# def make_composite_node_card(
#     label: str,
#     icon_path: Optional[str],
#     fill: str,
#     border: str,
#     font_color: str,
#     target_size: tuple[int, int] = DIAGRAM_NODE_CARD_SIZE,
# ) -> Optional[str]:
#     """
#     Build a PNG node card containing:
#       - pastel rounded rectangle
#       - optional service icon
#       - wrapped label

#     Important:
#       - icon_path is optional.
#       - if icon is missing, this still creates a styled pastel card.
#       - this guarantees all diagram boxes have light background color.
#     """
#     try:
#         cache_dir = Path(tempfile.gettempdir()) / "aia_node_card_cache"
#         cache_dir.mkdir(parents=True, exist_ok=True)

#         icon_mtime = None
#         icon_resolved = None

#         if icon_path:
#             src_icon = Path(icon_path)
#             if src_icon.exists():
#                 icon_resolved = src_icon
#                 icon_mtime = src_icon.stat().st_mtime

#         cache_key = hashlib.sha1(
#             json.dumps(
#                 {
#                     "label": label,
#                     "icon_path": str(icon_resolved.resolve()) if icon_resolved else "",
#                     "fill": fill,
#                     "border": border,
#                     "font_color": font_color,
#                     "target_size": target_size,
#                     "font_size": DIAGRAM_NODE_CARD_FONT_SIZE,
#                     "mtime": icon_mtime,
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

#         label_top_y = 92

#         # Optional icon.
#         if icon_resolved:
#             try:
#                 with Image.open(icon_resolved).convert("RGBA") as icon_img:
#                     icon_max_w = int(width * 0.46)
#                     icon_max_h = int(height * 0.36)
#                     icon_img.thumbnail((icon_max_w, icon_max_h), Image.LANCZOS)

#                     icon_x = (width - icon_img.width) // 2
#                     icon_y = 20

#                     card.paste(icon_img, (icon_x, icon_y), icon_img)
#                     label_top_y = icon_y + icon_img.height + 16

#             except Exception:
#                 logger.exception(
#                     "Failed to paste icon into node card. Continuing with text-only card. icon=%s",
#                     icon_resolved,
#                 )

#         # If no icon, add a simple service initials badge.
#         if not icon_resolved:
#             badge_fill = "#FFFFFF"
#             badge_radius = 38
#             badge_center_x = width // 2
#             badge_center_y = 58

#             try:
#                 draw.ellipse(
#                     [
#                         badge_center_x - badge_radius,
#                         badge_center_y - badge_radius,
#                         badge_center_x + badge_radius,
#                         badge_center_y + badge_radius,
#                     ],
#                     fill=badge_fill,
#                     outline=border,
#                     width=3,
#                 )

#                 initials = "".join(
#                     word[0].upper()
#                     for word in clean_label(label).split()
#                     if word
#                 )[:3] or "AI"

#                 badge_font = load_card_font(size=28, bold=True)
#                 tw, th = text_size(draw, initials, badge_font)

#                 draw.text(
#                     (
#                         badge_center_x - tw // 2,
#                         badge_center_y - th // 2 - 2,
#                     ),
#                     initials,
#                     fill=font_color,
#                     font=badge_font,
#                 )

#                 label_top_y = 108

#             except Exception:
#                 logger.exception("Failed to draw fallback initials badge.")

#         font = load_card_font(
#             size=DIAGRAM_NODE_CARD_FONT_SIZE,
#             bold=True,
#         )

#         label_clean = clean_label(label)

#         lines = wrap_text_for_card(
#             draw=draw,
#             text=label_clean,
#             font=font,
#             max_width_px=width - 34,
#             max_lines=3,
#         )

#         line_heights = [
#             text_size(draw, line, font)[1]
#             for line in lines
#         ]

#         total_text_h = sum(line_heights) + max(0, len(lines) - 1) * 6

#         available_bottom = height - 18
#         text_y = min(
#             max(label_top_y, height - total_text_h - 24),
#             available_bottom - total_text_h,
#         )

#         for line in lines:
#             tw, th = text_size(draw, line, font)
#             tx = (width - tw) // 2

#             draw.text(
#                 (tx, text_y),
#                 line,
#                 fill=font_color,
#                 font=font,
#             )

#             text_y += th + 6

#         card.save(out_path)
#         return str(out_path)

#     except Exception:
#         logger.exception(
#             "Failed to create composite node card for label=%r icon=%s",
#             label,
#             icon_path,
#         )
#         return None
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont

from . import config as render_config
from .config import DIAGRAM_NODE_CARD_FONT_SIZE, DIAGRAM_NODE_CARD_SIZE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------
# Config-driven node-card rendering options
# ---------------------------------------------------------------------
DIAGRAM_NODE_CARD_TEXT_BOLD = bool(getattr(render_config, "DIAGRAM_NODE_CARD_TEXT_BOLD", True))
DIAGRAM_NODE_CARD_MIN_FONT_SIZE = int(getattr(render_config, "DIAGRAM_NODE_CARD_MIN_FONT_SIZE", 22))
DIAGRAM_NODE_CARD_MAX_LINES = int(getattr(render_config, "DIAGRAM_NODE_CARD_MAX_LINES", 3))
DIAGRAM_NODE_CARD_TEXT_PADDING_X = int(getattr(render_config, "DIAGRAM_NODE_CARD_TEXT_PADDING_X", 28))
DIAGRAM_NODE_CARD_TEXT_BOTTOM_PADDING = int(getattr(render_config, "DIAGRAM_NODE_CARD_TEXT_BOTTOM_PADDING", 20))
DIAGRAM_NODE_CARD_TEXT_LINE_GAP = int(getattr(render_config, "DIAGRAM_NODE_CARD_TEXT_LINE_GAP", 7))
DIAGRAM_NODE_CARD_BORDER_WIDTH = int(getattr(render_config, "DIAGRAM_NODE_CARD_BORDER_WIDTH", 4))
DIAGRAM_NODE_CARD_CORNER_RADIUS = int(getattr(render_config, "DIAGRAM_NODE_CARD_CORNER_RADIUS", 20))
DIAGRAM_NODE_CARD_ICON_MAX_WIDTH_RATIO = float(getattr(render_config, "DIAGRAM_NODE_CARD_ICON_MAX_WIDTH_RATIO", 0.44))
DIAGRAM_NODE_CARD_ICON_MAX_HEIGHT_RATIO = float(getattr(render_config, "DIAGRAM_NODE_CARD_ICON_MAX_HEIGHT_RATIO", 0.34))
DIAGRAM_NODE_CARD_ICON_TOP_PADDING = int(getattr(render_config, "DIAGRAM_NODE_CARD_ICON_TOP_PADDING", 18))
DIAGRAM_NODE_CARD_ICON_TEXT_GAP = int(getattr(render_config, "DIAGRAM_NODE_CARD_ICON_TEXT_GAP", 14))
DIAGRAM_NODE_CARD_BADGE_ENABLED = bool(getattr(render_config, "DIAGRAM_FALLBACK_CARD_BADGE_ENABLED", True))
DIAGRAM_NODE_CARD_BADGE_FILL = str(getattr(render_config, "DIAGRAM_FALLBACK_CARD_BADGE_FILL", "#FFFFFF"))
DIAGRAM_NODE_CARD_BADGE_FONT_SIZE = int(getattr(render_config, "DIAGRAM_FALLBACK_CARD_BADGE_FONT_SIZE", 30))
DIAGRAM_NODE_CARD_INITIALS_MAX_CHARS = int(getattr(render_config, "DIAGRAM_FALLBACK_CARD_INITIALS_MAX_CHARS", 3))


# ---------------------------------------------------------------------
# Icon normalization
# ---------------------------------------------------------------------
def normalize_icon_for_graphviz(icon_path: str, target_size: tuple[int, int] = (128, 72)) -> str:
    """Normalize a local icon to a transparent PNG that Graphviz can embed reliably."""
    try:
        tmp = Path(tempfile.gettempdir()) / "aia_icon_cache"
        tmp.mkdir(exist_ok=True)
        src = Path(icon_path)
        out = tmp / f"{src.stem}_{target_size[0]}x{target_size[1]}.png"

        if out.exists():
            return str(out)

        with Image.open(src).convert("RGBA") as img:
            canvas = Image.new("RGBA", target_size, (255, 255, 255, 0))
            img.thumbnail((target_size[0] - 8, target_size[1] - 8), Image.LANCZOS)
            canvas.paste(
                img,
                ((target_size[0] - img.width) // 2, (target_size[1] - img.height) // 2),
                img,
            )
            canvas.save(out)

        return str(out)
    except Exception:
        logger.exception("Failed to normalize icon: %s", icon_path)
        return icon_path


# ---------------------------------------------------------------------
# Font helpers
# ---------------------------------------------------------------------
def load_card_font(size: int, bold: bool = False):
    """Load a readable cross-platform font with safe fallback."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/System/Library/Fonts/Helvetica.ttc",
    ]

    for fp in candidates:
        try:
            if Path(fp).exists():
                return ImageFont.truetype(fp, size=size)
        except Exception:
            continue

    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple[int, int]:
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        try:
            return draw.textsize(text, font=font)
        except Exception:
            return (len(str(text or "")) * 8, 14)


# ---------------------------------------------------------------------
# Label cleanup and wrapping
# ---------------------------------------------------------------------
def _split_camel_case(value: str) -> str:
    """Convert compact technical names to readable words without service hardcoding."""
    text = str(value or "")
    text = re.sub(r"[_\-]+", " ", text)
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_label(label: str) -> str:
    """Clean labels for node cards while keeping labels generic and readable."""
    text = html.unescape(str(label or ""))
    text = re.sub(r"<\s*br\s*/?\s*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</?\s*b\s*>", "", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\\n", " ").replace("\n", " ")
    text = _split_camel_case(text)
    return re.sub(r"\s+", " ", text).strip()


def _wrap_words(draw: ImageDraw.ImageDraw, text: str, font, max_width_px: int, max_lines: int) -> list[str]:
    words = clean_label(text).split()
    if not words:
        return [""]

    lines: list[str] = []
    current: list[str] = []

    for word in words:
        candidate = " ".join(current + [word]).strip()
        if text_size(draw, candidate, font)[0] <= max_width_px or not current:
            current.append(word)
        else:
            lines.append(" ".join(current))
            current = [word]
            if len(lines) >= max_lines - 1:
                break

    if current and len(lines) < max_lines:
        remaining_words = words[sum(len(line.split()) for line in lines):]
        final_line = " ".join(remaining_words).strip() if remaining_words else " ".join(current)
        lines.append(final_line)

    return [line.strip() for line in lines[:max_lines] if line.strip()] or [""]


def _ellipsize_to_width(draw: ImageDraw.ImageDraw, text: str, font, max_width_px: int) -> str:
    if text_size(draw, text, font)[0] <= max_width_px:
        return text
    suffix = "…"
    source = str(text or "")
    while source and text_size(draw, source + suffix, font)[0] > max_width_px:
        source = source[:-1]
    return (source + suffix).strip() if source else suffix


def _fit_text_lines(
    draw: ImageDraw.ImageDraw,
    label: str,
    max_width_px: int,
    max_height_px: int,
    preferred_size: int,
    min_size: int,
    max_lines: int,
    bold: bool,
) -> tuple[object, list[str], int]:
    """Find the largest font size that fits the node-card text area."""
    preferred_size = max(preferred_size, min_size)
    min_size = max(10, min_size)

    for size in range(preferred_size, min_size - 1, -1):
        font = load_card_font(size=size, bold=bold)
        lines = _wrap_words(draw, label, font, max_width_px, max_lines=max_lines)
        line_heights = [text_size(draw, line, font)[1] for line in lines]
        total_h = sum(line_heights) + max(0, len(lines) - 1) * DIAGRAM_NODE_CARD_TEXT_LINE_GAP
        if total_h <= max_height_px and all(text_size(draw, line, font)[0] <= max_width_px for line in lines):
            return font, lines, size

    font = load_card_font(size=min_size, bold=bold)
    lines = _wrap_words(draw, label, font, max_width_px, max_lines=max_lines)
    lines = [_ellipsize_to_width(draw, line, font, max_width_px) for line in lines]
    return font, lines, min_size


def wrap_text_for_card(draw, text, font, max_width_px: int, max_lines: int = 3) -> list[str]:
    """Backward-compatible wrapper used by older renderer paths."""
    return _wrap_words(draw, text, font, max_width_px=max_width_px, max_lines=max_lines)


# ---------------------------------------------------------------------
# Node-card rendering
# ---------------------------------------------------------------------
def make_composite_node_card(
    label: str,
    icon_path: Optional[str],
    fill: str,
    border: str,
    font_color: str,
    target_size: tuple[int, int] = DIAGRAM_NODE_CARD_SIZE,
) -> Optional[str]:
    """
    Build a readable PNG node card containing:
      - pastel rounded rectangle
      - optional service icon
      - bold, wrapped, readable node name

    Important:
      - icon_path is optional.
      - if icon is missing, this still creates a styled pastel card.
      - text fitting is dynamic so labels do not disappear when diagrams are scaled in DOCX/PDF.
    """
    try:
        cache_dir = Path(tempfile.gettempdir()) / "aia_node_card_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)

        icon_mtime = None
        icon_resolved: Optional[Path] = None
        if icon_path:
            src_icon = Path(icon_path)
            if src_icon.exists():
                icon_resolved = src_icon
                icon_mtime = src_icon.stat().st_mtime

        label_clean = clean_label(label)
        width, height = int(target_size[0]), int(target_size[1])

        cache_key = hashlib.sha1(
            json.dumps(
                {
                    "label": label_clean,
                    "icon_path": str(icon_resolved.resolve()) if icon_resolved else "",
                    "fill": fill,
                    "border": border,
                    "font_color": font_color,
                    "target_size": [width, height],
                    "font_size": DIAGRAM_NODE_CARD_FONT_SIZE,
                    "min_font_size": DIAGRAM_NODE_CARD_MIN_FONT_SIZE,
                    "max_lines": DIAGRAM_NODE_CARD_MAX_LINES,
                    "text_bold": DIAGRAM_NODE_CARD_TEXT_BOLD,
                    "mtime": icon_mtime,
                    "version": 3,
                },
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        out_path = cache_dir / f"node_card_{cache_key}.png"
        if out_path.exists():
            return str(out_path)

        card = Image.new("RGBA", (width, height), (255, 255, 255, 0))
        draw = ImageDraw.Draw(card)

        try:
            draw.rounded_rectangle(
                [(2, 2), (width - 3, height - 3)],
                radius=DIAGRAM_NODE_CARD_CORNER_RADIUS,
                fill=fill,
                outline=border,
                width=DIAGRAM_NODE_CARD_BORDER_WIDTH,
            )
        except Exception:
            draw.rectangle(
                [(2, 2), (width - 3, height - 3)],
                fill=fill,
                outline=border,
                width=DIAGRAM_NODE_CARD_BORDER_WIDTH,
            )

        label_top_y = int(height * 0.42)

        # Optional icon area. Keep icon compact so text remains readable.
        if icon_resolved:
            try:
                with Image.open(icon_resolved).convert("RGBA") as icon_img:
                    icon_max_w = max(48, int(width * DIAGRAM_NODE_CARD_ICON_MAX_WIDTH_RATIO))
                    icon_max_h = max(40, int(height * DIAGRAM_NODE_CARD_ICON_MAX_HEIGHT_RATIO))
                    icon_img.thumbnail((icon_max_w, icon_max_h), Image.LANCZOS)

                    icon_x = (width - icon_img.width) // 2
                    icon_y = DIAGRAM_NODE_CARD_ICON_TOP_PADDING
                    card.paste(icon_img, (icon_x, icon_y), icon_img)
                    label_top_y = icon_y + icon_img.height + DIAGRAM_NODE_CARD_ICON_TEXT_GAP
            except Exception:
                logger.exception("Failed to paste icon into node card. Continuing with text-only card. icon=%s", icon_resolved)

        # If no icon, add a generic initials badge without service hardcoding.
        if not icon_resolved and DIAGRAM_NODE_CARD_BADGE_ENABLED:
            try:
                badge_radius = max(28, int(min(width, height) * 0.13))
                badge_center_x = width // 2
                badge_center_y = max(42, int(height * 0.22))

                draw.ellipse(
                    [
                        badge_center_x - badge_radius,
                        badge_center_y - badge_radius,
                        badge_center_x + badge_radius,
                        badge_center_y + badge_radius,
                    ],
                    fill=DIAGRAM_NODE_CARD_BADGE_FILL,
                    outline=border,
                    width=max(2, DIAGRAM_NODE_CARD_BORDER_WIDTH - 1),
                )

                initials = "".join(word[0].upper() for word in label_clean.split() if word)[:DIAGRAM_NODE_CARD_INITIALS_MAX_CHARS] or "AI"
                badge_font = load_card_font(size=DIAGRAM_NODE_CARD_BADGE_FONT_SIZE, bold=True)
                tw, th = text_size(draw, initials, badge_font)
                draw.text((badge_center_x - tw // 2, badge_center_y - th // 2 - 2), initials, fill=font_color, font=badge_font)
                label_top_y = badge_center_y + badge_radius + DIAGRAM_NODE_CARD_ICON_TEXT_GAP
            except Exception:
                logger.exception("Failed to draw fallback initials badge.")

        text_left = DIAGRAM_NODE_CARD_TEXT_PADDING_X
        text_right = width - DIAGRAM_NODE_CARD_TEXT_PADDING_X
        max_text_width = max(80, text_right - text_left)
        max_text_height = max(40, height - label_top_y - DIAGRAM_NODE_CARD_TEXT_BOTTOM_PADDING)

        font, lines, _font_size = _fit_text_lines(
            draw=draw,
            label=label_clean,
            max_width_px=max_text_width,
            max_height_px=max_text_height,
            preferred_size=DIAGRAM_NODE_CARD_FONT_SIZE,
            min_size=DIAGRAM_NODE_CARD_MIN_FONT_SIZE,
            max_lines=DIAGRAM_NODE_CARD_MAX_LINES,
            bold=DIAGRAM_NODE_CARD_TEXT_BOLD,
        )

        line_heights = [text_size(draw, line, font)[1] for line in lines]
        total_text_h = sum(line_heights) + max(0, len(lines) - 1) * DIAGRAM_NODE_CARD_TEXT_LINE_GAP

        available_bottom = height - DIAGRAM_NODE_CARD_TEXT_BOTTOM_PADDING
        text_y = min(max(label_top_y, available_bottom - total_text_h), available_bottom - total_text_h)
        text_y = max(label_top_y, text_y)

        # Draw a very subtle white text plate for contrast when fills are darker.
        try:
            plate_pad_y = 5
            draw.rounded_rectangle(
                [
                    (DIAGRAM_NODE_CARD_TEXT_PADDING_X // 2, text_y - plate_pad_y),
                    (width - DIAGRAM_NODE_CARD_TEXT_PADDING_X // 2, text_y + total_text_h + plate_pad_y),
                ],
                radius=10,
                fill=(255, 255, 255, 165),
                outline=None,
            )
        except Exception:
            pass

        for idx, line in enumerate(lines):
            safe_line = _ellipsize_to_width(draw, line, font, max_text_width)
            tw, th = text_size(draw, safe_line, font)
            tx = (width - tw) // 2
            draw.text((tx, text_y), safe_line, fill=font_color, font=font)
            text_y += th + DIAGRAM_NODE_CARD_TEXT_LINE_GAP

        card.save(out_path)
        return str(out_path)

    except Exception:
        logger.exception("Failed to create composite node card for label=%r icon=%s", label, icon_path)
        return None
