from __future__ import annotations

import hashlib
import html
import logging
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import graphviz
from PIL import Image

from . import config as render_config
from .config import (
    PROJECT_ROOT,
    DIAGRAM_GRAPH_FONT_SIZE,
    DIAGRAM_NODE_FONT_SIZE,
    DIAGRAM_EDGE_FONT_SIZE,
    DIAGRAM_NODE_CARD_WIDTH_IN,
    DIAGRAM_NODE_CARD_HEIGHT_IN,
    DIAGRAM_NODE_CARD_SIZE,
    DIAGRAM_FORCE_RANKDIR,
    DIAGRAM_GRAPH_SPLINES,
    DIAGRAM_GRAPH_RANKSEP,
    DIAGRAM_GRAPH_NODESEP,
    DIAGRAM_GRAPH_PAD,
    DIAGRAM_GRAPH_OVERLAP,
    DIAGRAM_GRAPH_OUTPUT_ORDER,
    DIAGRAM_GRAPH_NEWRANK,
    DIAGRAM_EDGE_PENWIDTH,
    DIAGRAM_EDGE_MINLEN,
    DIAGRAM_EDGE_ARROWSIZE,
    DIAGRAM_LEGEND_TITLE_FONT_SIZE,
    DIAGRAM_LEGEND_ITEM_FONT_SIZE,
    DIAGRAM_LEGEND_HEADING_LABEL,
    DIAGRAM_LEGEND_BORDER_COLOR,
    DIAGRAM_LEGEND_FILL_COLOR,
    DIAGRAM_LEGEND_TITLE_COLOR,
    DIAGRAM_LEGEND_ITEM_FONT_COLOR,
    DIAGRAM_LEGEND_ITEM_FILL_COLOR,
    DIAGRAM_LEGEND_MARGIN,
    DIAGRAM_LEGEND_PAD,
    DIAGRAM_LEGEND_NODESEP,
    DIAGRAM_LEGEND_RANKSEP,
    DIAGRAM_LEGEND_EDGE_PENWIDTH,
    DIAGRAM_LEGEND_EDGE_ARROWSIZE,
    DIAGRAM_NODE_DEFAULT_FILL,
    DIAGRAM_NODE_DEFAULT_BORDER,
    DIAGRAM_NODE_DEFAULT_MARGIN,
    DIAGRAM_NODE_DEFAULT_PENWIDTH,
    DIAGRAM_CLUSTER_FONT_SIZE,
    DIAGRAM_CLUSTER_FILL_COLOR,
    DIAGRAM_CLUSTER_BORDER_COLOR,
    DIAGRAM_CLUSTER_FONT_COLOR,
    DIAGRAM_CLUSTER_STYLE,
    DIAGRAM_CLUSTER_PENWIDTH,
    DIAGRAM_CLUSTER_MARGIN,
    DIAGRAM_CLUSTER_LABEL_BOLD,
)
from .icon_resolver import (
    get_style_for_label,
    is_isolated_node_name_or_label,
    iter_icon_files,
    resolve_icon_from_node_label,
)
from .node_card import (
    clean_label,
    make_composite_node_card,
    normalize_icon_for_graphviz,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------
# Optional diagram config keys
# ---------------------------------------------------------------------
DIAGRAM_GRAPH_RATIO = getattr(render_config, "DIAGRAM_GRAPH_RATIO", "compress")
DIAGRAM_GRAPH_CONCENTRATE = getattr(render_config, "DIAGRAM_GRAPH_CONCENTRATE", True)
DIAGRAM_GRAPH_COMPOUND = getattr(render_config, "DIAGRAM_GRAPH_COMPOUND", True)
DIAGRAM_GRAPH_DPI = getattr(render_config, "DIAGRAM_GRAPH_DPI", 180)
DIAGRAM_TRIM_PNG_WHITESPACE = getattr(render_config, "DIAGRAM_TRIM_PNG_WHITESPACE", True)
DIAGRAM_TRIM_PNG_BACKGROUND_THRESHOLD = getattr(render_config, "DIAGRAM_TRIM_PNG_BACKGROUND_THRESHOLD", 248)
DIAGRAM_TRIM_PNG_PADDING_PX = getattr(render_config, "DIAGRAM_TRIM_PNG_PADDING_PX", 18)
DIAGRAM_SKIP_UNCONNECTED_NODES = getattr(render_config, "DIAGRAM_SKIP_UNCONNECTED_NODES", True)

# ---------------------------------------------------------------------
# DOT escaping / quoting helpers
# ---------------------------------------------------------------------
def dot_escape(value: Any) -> str:
    """Escape a value safely for Graphviz quoted strings."""
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _quote_dot_id(value: Any) -> str:
    raw = str(value or "").strip().rstrip(";")
    if not raw:
        return '"node"'
    if raw.startswith('"') and raw.endswith('"'):
        return raw
    if raw.startswith("<") and raw.endswith(">"):
        return raw
    return f'"{dot_escape(raw.strip(chr(34)))}"'


def _clean_dot_endpoint(value: str) -> str:
    cleaned = str(value or "").strip().strip('"').strip("'").rstrip(";")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _extract_edge_endpoints(line: str) -> List[str]:
    edge_without_attrs = re.sub(r"\[.*?\]", "", line, flags=re.DOTALL).strip().rstrip(";")
    if "->" in edge_without_attrs:
        parts = re.split(r"->", edge_without_attrs)
    elif "--" in edge_without_attrs:
        parts = re.split(r"--", edge_without_attrs)
    else:
        return []
    return [_clean_dot_endpoint(part) for part in parts if _clean_dot_endpoint(part)]


def _is_node_declaration(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if stripped.lower().startswith(("graph ", "node ", "edge ")):
        return False
    if "->" in stripped or "--" in stripped:
        return False
    return "[" in stripped and "]" in stripped


def _normalize_edge_prefix(edge_prefix: str) -> str:
    raw = str(edge_prefix or "").strip().rstrip(";")
    if "->" in raw:
        operator = "->"
    elif "--" in raw:
        operator = "--"
    else:
        return _quote_dot_id(raw)
    parts = [part.strip().strip('"') for part in re.split(r"->|--", raw) if part.strip()]
    if len(parts) < 2:
        return raw
    return f" {operator} ".join(_quote_dot_id(part) for part in parts)


def _dedupe_legend_items(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    deduped: List[Tuple[str, str]] = []
    seen = set()
    for color, label in items:
        safe_color = str(color or "#666666").strip()
        safe_label = str(label or "").strip()
        if not safe_label:
            continue
        key = (safe_color.lower(), safe_label.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((safe_color, safe_label))
    return deduped


def _make_fallback_flow_label(endpoints: List[str], labels: Dict[str, str]) -> str:
    if len(endpoints) < 2:
        return ""
    source = endpoints[0]
    target = endpoints[-1]
    source_label = clean_label(labels.get(source, source))
    target_label = clean_label(labels.get(target, target))
    if not source_label or not target_label:
        return ""
    return f"{source_label} to {target_label}"


def _is_bare_node_statement(line: str) -> bool:
    stripped = str(line or "").strip().rstrip(";")
    if not stripped:
        return False
    lowered = stripped.lower()
    if stripped in {"{", "}"}:
        return False
    if "->" in stripped or "--" in stripped:
        return False
    if "[" in stripped or "]" in stripped:
        return False
    if "=" in stripped:
        return False
    if lowered.startswith(("digraph ", "graph ", "subgraph ", "node ", "edge ")):
        return False
    return True


def _count_dot_brace_delta(dot_text: str) -> int:
    in_quote = False
    escaped = False
    delta = 0
    for char in dot_text:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if char == "{":
            delta += 1
        elif char == "}":
            delta -= 1
    return delta


def _balance_dot_braces(dot_text: str) -> str:
    if not dot_text:
        return dot_text
    delta = _count_dot_brace_delta(dot_text)
    if delta > 0:
        logger.warning("Graphviz DOT had %s missing closing brace(s). Auto-appending.", delta)
        return dot_text.rstrip() + ("\n}" * delta) + "\n"
    if delta < 0:
        logger.warning("Graphviz DOT has %s extra closing brace(s). Leaving unchanged for debug visibility.", abs(delta))
    return dot_text

# ---------------------------------------------------------------------
# Debug helpers
# ---------------------------------------------------------------------
def write_graphviz_debug_file(safe_dot: str, prefix: str = "aia_graphviz_failed") -> Path:
    debug_path = Path(tempfile.gettempdir()) / f"{prefix}_{hashlib.sha1(safe_dot.encode()).hexdigest()[:8]}.dot"
    debug_path.write_text(safe_dot, encoding="utf-8")
    logger.error("Failed Graphviz DOT written to: %s", debug_path)
    for idx, line in enumerate(safe_dot.splitlines(), start=1):
        logger.error("DOT %03d: %s", idx, line)
    return debug_path

# ---------------------------------------------------------------------
# PNG trim helper
# ---------------------------------------------------------------------
def trim_png_whitespace(
    image_path: str,
    background_threshold: int = DIAGRAM_TRIM_PNG_BACKGROUND_THRESHOLD,
    padding_px: int = DIAGRAM_TRIM_PNG_PADDING_PX,
) -> str:
    if not DIAGRAM_TRIM_PNG_WHITESPACE:
        return image_path
    try:
        path = Path(image_path)
        if not path.exists():
            return image_path
        raw_image = Image.open(path).convert("RGBA")
        white_background = Image.new("RGBA", raw_image.size, "white")
        image = Image.alpha_composite(white_background, raw_image).convert("RGB")
        pixels = image.load()
        width, height = image.size
        left, top, right, bottom = width, height, 0, 0
        for y in range(height):
            for x in range(width):
                r, g, b = pixels[x, y]
                if not (r >= background_threshold and g >= background_threshold and b >= background_threshold):
                    left = min(left, x)
                    top = min(top, y)
                    right = max(right, x)
                    bottom = max(bottom, y)
        if right <= left or bottom <= top:
            return image_path
        left = max(0, left - padding_px)
        top = max(0, top - padding_px)
        right = min(width, right + padding_px)
        bottom = min(height, bottom + padding_px)
        image.crop((left, top, right, bottom)).save(path, "PNG")
        return str(path)
    except Exception:
        logger.exception("Failed to trim Graphviz PNG whitespace. image_path=%s", image_path)
        return image_path

# ---------------------------------------------------------------------
# Text normalization / diagram classification
# ---------------------------------------------------------------------
def preprocess_diagram_text(text: Any) -> str:
    if text is None:
        return ""
    text = str(text)
    for _ in range(4):
        new_text = html.unescape(text)
        if new_text == text:
            break
        text = new_text
    replacements = {
        "--&amp;amp;amp;amp;amp;gt;": "->",
        "-&amp;amp;amp;amp;amp;gt;": "->",
        "--&amp;amp;amp;amp;gt;": "->",
        "-&amp;amp;amp;amp;gt;": "->",
        "--&amp;amp;amp;gt;": "->",
        "-&amp;amp;amp;gt;": "->",
        "--&amp;amp;gt;": "->",
        "-&amp;amp;gt;": "->",
        "--&amp;gt;": "->",
        "-&amp;gt;": "->",
        "--&gt;": "->",
        "-&gt;": "->",
        "-\\>": "->",
        "→": "->",
        "\\[": "[",
        "\\]": "]",
        "\\{": "{",
        "\\}": "}",
        "\\_": "_",
        "\\#": "#",
        "\\;": ";",
        "\\(": "(",
        "\\)": ")",
        "&lt;br/&gt;": "\\n",
        "&lt;br /&gt;": "\\n",
        "&lt;br&gt;": "\\n",
        "<br/>": "\\n",
        "<br />": "\\n",
        "<br>": "\\n",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.strip()


def strip_code_fence(text: Any) -> str:
    raw = preprocess_diagram_text(text).strip()
    raw = re.sub(r"^```(?:dot|graphviz|mermaid|gv)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def classify_diagram_text(text: Any) -> Tuple[str, str]:
    raw = strip_code_fence(text)
    lines = raw.splitlines()
    first = lines[0].strip() if lines else ""
    if raw.startswith(("digraph ", "graph ")):
        if re.match(r"^graph\s+(TD|TB|BT|LR|RL)\b", first, re.IGNORECASE):
            return "mermaid_like", raw
        return "graphviz", raw
    if re.match(r"^(graph|flowchart)\s+(TD|TB|BT|LR|RL)\b", first, re.IGNORECASE):
        return "mermaid_like", raw
    return "plain", raw


def mermaid_like_to_dot(text: str) -> Optional[str]:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return None
    rankdir = DIAGRAM_FORCE_RANKDIR or "LR"
    first_match = re.match(r"^(graph|flowchart)\s+(TD|TB|BT|LR|RL)$", lines[0], re.IGNORECASE)
    if first_match:
        mermaid_dir = first_match.group(2).upper()
        detected_rankdir = {"TD": "TB", "TB": "TB", "BT": "BT", "LR": "LR", "RL": "RL"}.get(mermaid_dir, rankdir)
        rankdir = DIAGRAM_FORCE_RANKDIR or detected_rankdir
        lines = lines[1:]
    out = ["digraph G {", f"  rankdir={rankdir};"]
    for line in lines:
        match = (
            re.match(r"^(.*?)\s*-->\|(.*?)\|\s*(.*?)$", line)
            or re.match(r"^(.*?)\s*-->\s*(.*?)$", line)
            or re.match(r"^(.*?)\s*->\|(.*?)\|\s*(.*?)$", line)
            or re.match(r"^(.*?)\s*->\s*(.*?)$", line)
        )
        if not match:
            continue
        if len(match.groups()) == 3:
            left, edge_label, right = match.group(1), match.group(2), match.group(3)
        else:
            left, right, edge_label = match.group(1), match.group(2), None
        edge = f'  "{dot_escape(left.strip().strip(chr(34)))}" -> "{dot_escape(right.strip().strip(chr(34)))}"'
        if edge_label:
            edge += f' [label="{dot_escape(edge_label)}"]'
        out.append(edge + ";")
    out.append("}")
    return "\n".join(out)


def normalize_to_graphviz_dot(text: Any) -> Optional[str]:
    text = preprocess_diagram_text(text)
    kind, body = classify_diagram_text(text)
    if kind == "graphviz":
        return strip_code_fence(body)
    if kind == "mermaid_like":
        return mermaid_like_to_dot(body)
    return None

# ---------------------------------------------------------------------
# DOT helpers
# ---------------------------------------------------------------------
def wrap_label(text: Any, width: int = 16) -> str:
    words = str(text or "").replace("\\n", " ").replace("\n", " ").split()
    lines: List[str] = []
    current: List[str] = []
    current_len = 0
    for word in words:
        if current and current_len + len(word) > width:
            lines.append(" ".join(current))
            current = [word]
            current_len = len(word)
        else:
            current.append(word)
            current_len += len(word) + 1
    if current:
        lines.append(" ".join(current))
    return "\\n".join(lines)


def normalize_edges(dot: str) -> str:
    if re.search(r"^\s*digraph\b", dot, re.IGNORECASE):
        return dot.replace("--", "->")
    if re.search(r"^\s*graph\b", dot, re.IGNORECASE):
        return dot.replace("->", "--")
    return dot


def force_graph_rankdir(dot: str) -> str:
    if not dot:
        return dot
    target_rankdir = DIAGRAM_FORCE_RANKDIR or "LR"
    if re.search(r"\brankdir\s*=", dot, flags=re.IGNORECASE):
        return re.sub(r"\brankdir\s*=\s*(LR|RL|TB|BT|TD)\s*;", f"rankdir={target_rankdir};", dot, flags=re.IGNORECASE)
    return dot.replace("{", f"{{\n  rankdir={target_rankdir};", 1)


def split_attr(line: str) -> Tuple[str, str, str]:
    if "[" not in line or "]" not in line:
        return line, "", ""
    prefix, rest = line.split("[", 1)
    inner, postfix = rest.rsplit("]", 1)
    return prefix, inner, postfix


def extract_label(inner: str, fallback: str) -> str:
    match = re.search(r'label\s*=\s*"(.*?)"', inner or "")
    return match.group(1) if match else fallback


def _graph_bool(value: bool) -> str:
    return "true" if value else "false"


def _cluster_style_lines() -> List[str]:
    cluster_font_name = "Helvetica-Bold" if DIAGRAM_CLUSTER_LABEL_BOLD else "Helvetica"
    return [
        f'    style="{DIAGRAM_CLUSTER_STYLE}";',
        f'    fillcolor="{DIAGRAM_CLUSTER_FILL_COLOR}";',
        f'    color="{DIAGRAM_CLUSTER_BORDER_COLOR}";',
        f'    fontcolor="{DIAGRAM_CLUSTER_FONT_COLOR}";',
        f'    fontname="{cluster_font_name}";',
        f"    fontsize={DIAGRAM_CLUSTER_FONT_SIZE};",
        f"    penwidth={DIAGRAM_CLUSTER_PENWIDTH};",
        f"    margin={DIAGRAM_CLUSTER_MARGIN};",
    ]


def _strip_existing_attr_key(inner: str, key: str) -> str:
    if not inner:
        return ""
    pattern = rf'\b{re.escape(key)}\s*=\s*("[^"]*"|[^,\]]+)\s*,?'
    cleaned = re.sub(pattern, "", inner, flags=re.IGNORECASE)
    cleaned = re.sub(r",\s*,", ",", cleaned)
    return cleaned.strip().strip(",")


def _merge_edge_attributes(inner: str, color: str) -> str:
    cleaned = inner or ""
    for key in ["label", "xlabel", "headlabel", "taillabel", "color", "penwidth", "minlen", "arrowsize"]:
        cleaned = _strip_existing_attr_key(cleaned, key)
    attrs: List[str] = []
    if cleaned.strip():
        attrs.append(cleaned.strip())
    attrs.extend([
        f'color="{color}"',
        f"penwidth={DIAGRAM_EDGE_PENWIDTH}",
        f"minlen={DIAGRAM_EDGE_MINLEN}",
        f"arrowsize={DIAGRAM_EDGE_ARROWSIZE}",
    ])
    return ",".join(attrs)

# ---------------------------------------------------------------------
# Node styling
# ---------------------------------------------------------------------
def styled_node(node_ref: str, label: str, shape: str) -> str:
    safe_node_ref = _quote_dot_id(node_ref)
    label_clean = clean_label(label)
    style = get_style_for_label(label_clean)
    icon = resolve_icon_from_node_label(label_clean, PROJECT_ROOT)
    normalized_icon = None
    if icon:
        try:
            normalized_icon = normalize_icon_for_graphviz(icon)
            logger.info("[ICON] Resolved icon for label=%r -> %s", label_clean, normalized_icon)
        except Exception:
            logger.exception("[ICON] Failed normalizing icon for label=%r icon=%s", label_clean, icon)
            normalized_icon = None
    else:
        logger.warning("[ICON] No icon resolved for label=%r. Using colored text-only node card.", label_clean)
    card = make_composite_node_card(
        label=label_clean,
        icon_path=normalized_icon,
        fill=style["fill"],
        border=style["border"],
        font_color=style["font"],
        target_size=DIAGRAM_NODE_CARD_SIZE,
    )
    if card:
        safe_card = str(card).replace("\\", "/").replace('"', '\\"')
        return (
            f'{safe_node_ref} ['
            f'shape=none,'
            f'label="",'
            f'image="{safe_card}",'
            f'imagescale=true,'
            f'fixedsize=true,'
            f'width={DIAGRAM_NODE_CARD_WIDTH_IN},'
            f'height={DIAGRAM_NODE_CARD_HEIGHT_IN},'
            f'margin=0'
            f'];'
        )
    return (
        f'{safe_node_ref} ['
        f'shape={shape},'
        f'style="rounded,filled",'
        f'fillcolor="{style.get("fill", "#F8F9FA")}",'
        f'color="{style.get("border", "#DADCE0")}",'
        f'fontcolor="{style.get("font", "#202124")}",'
        f'label="{dot_escape(wrap_label(label_clean, 18))}",'
        f'fontsize={DIAGRAM_NODE_FONT_SIZE},'
        f'fontname="Helvetica-Bold",'
        f'penwidth={DIAGRAM_NODE_DEFAULT_PENWIDTH},'
        f'margin="{DIAGRAM_NODE_DEFAULT_MARGIN}"'
        f'];'
    )

# ---------------------------------------------------------------------
# DOT normalization / rendering preparation
# ---------------------------------------------------------------------
def normalize_dot_for_graphviz(dot_text: str) -> Tuple[str, List[Tuple[str, str]]]:
    dot = preprocess_diagram_text(strip_code_fence(dot_text))
    dot = force_graph_rankdir(dot)
    dot = normalize_edges(dot)
    dot = re.sub(r"([{};])", r"\1\n", dot)
    dot = re.sub(r"\[([^\]]*)\]", lambda match: "[" + match.group(1).replace("\n", " ") + "]", dot, flags=re.DOTALL)
    lines = [line.strip() for line in dot.splitlines() if line.strip()]

    out: List[str] = []
    legend: List[Tuple[str, str]] = []
    fallback_legend: List[Tuple[str, str]] = []
    isolated: set[str] = set()
    labels: Dict[str, str] = {}
    connected_nodes: set[str] = set()
    edge_colors = ["#E60000", "#1D70B8", "#28A197", "#F47738", "#4C2C92", "#6F72AF"]
    edge_index = 0

    for line in lines:
        if "->" in line or "--" in line:
            for endpoint in _extract_edge_endpoints(line):
                connected_nodes.add(endpoint)

    for line in lines:
        if _is_node_declaration(line):
            prefix, inner, _ = split_attr(line)
            name = _clean_dot_endpoint(prefix)
            label = extract_label(inner, name)
            labels[name] = label
            if is_isolated_node_name_or_label(name) or is_isolated_node_name_or_label(label):
                isolated.add(name)

    root_graph_defaults_injected = False

    for line in lines:
        stripped = line.strip()
        lower = stripped.lower()

        if stripped.startswith(("digraph ", "graph ")):
            out.append(line)
            continue

        if re.match(r"^\s*subgraph\s+cluster", stripped, flags=re.IGNORECASE):
            out.append(line)
            continue

        if stripped == "{":
            if not root_graph_defaults_injected:
                root_graph_defaults_injected = True
                out.extend([
                    "{",
                    "  graph [",
                    '    bgcolor="white",',
                    f'    splines="{DIAGRAM_GRAPH_SPLINES}",',
                    f'    ratio="{DIAGRAM_GRAPH_RATIO}",',
                    f"    concentrate={_graph_bool(bool(DIAGRAM_GRAPH_CONCENTRATE))},",
                    f"    compound={_graph_bool(bool(DIAGRAM_GRAPH_COMPOUND))},",
                    f"    dpi={DIAGRAM_GRAPH_DPI},",
                    f"    overlap={_graph_bool(DIAGRAM_GRAPH_OVERLAP)},",
                    f'    outputorder="{DIAGRAM_GRAPH_OUTPUT_ORDER}",',
                    '    fontname="Helvetica-Bold",',
                    f"    fontsize={DIAGRAM_GRAPH_FONT_SIZE},",
                    f"    ranksep={DIAGRAM_GRAPH_RANKSEP},",
                    f"    nodesep={DIAGRAM_GRAPH_NODESEP},",
                    f"    pad={DIAGRAM_GRAPH_PAD},",
                    f"    newrank={_graph_bool(DIAGRAM_GRAPH_NEWRANK)}",
                    "  ];",
                    "  node [",
                    "    shape=box,",
                    '    style="rounded,filled",',
                    f'    fillcolor="{DIAGRAM_NODE_DEFAULT_FILL}",',
                    f'    color="{DIAGRAM_NODE_DEFAULT_BORDER}",',
                    '    fontname="Helvetica-Bold",',
                    f"    fontsize={DIAGRAM_NODE_FONT_SIZE},",
                    f'    margin="{DIAGRAM_NODE_DEFAULT_MARGIN}",',
                    f"    penwidth={DIAGRAM_NODE_DEFAULT_PENWIDTH}",
                    "  ];",
                    "  edge [",
                    '    fontname="Helvetica-Bold",',
                    f"    fontsize={DIAGRAM_EDGE_FONT_SIZE},",
                    f"    penwidth={DIAGRAM_EDGE_PENWIDTH},",
                    f"    minlen={DIAGRAM_EDGE_MINLEN},",
                    f"    arrowsize={DIAGRAM_EDGE_ARROWSIZE},",
                    '    color="#5F6368"',
                    "  ];",
                ])
            else:
                out.append("{")
                out.extend(_cluster_style_lines())
            continue

        if stripped == "}":
            out.append(line)
            continue

        if lower.startswith(("node ", "edge ", "graph ")):
            continue

        if lower.startswith(("style=", "fillcolor=", "fontcolor=", "fontname=", "fontsize=", "penwidth=", "margin=", "labelloc=", "labeljust=")):
            continue

        if lower.startswith("color="):
            continue

        if "->" in stripped or "--" in stripped:
            endpoints = _extract_edge_endpoints(line)
            if any(part in isolated or is_isolated_node_name_or_label(labels.get(part, "")) for part in endpoints):
                continue
            prefix, inner, postfix = split_attr(line)
            label_match = re.search(r"(xlabel|label)\s*=\s*\"(.*?)\"", inner)
            edge_label = label_match.group(2).strip() if label_match and label_match.group(2).strip() else ""
            color = edge_colors[edge_index % len(edge_colors)]
            edge_index += 1
            if edge_label:
                legend.append((color, edge_label))
            else:
                fallback_label = _make_fallback_flow_label(endpoints=endpoints, labels=labels)
                if fallback_label:
                    fallback_legend.append((color, fallback_label))
            merged_attrs = _merge_edge_attributes(inner=inner, color=color)
            if "[" in line:
                safe_edge_prefix = _normalize_edge_prefix(prefix)
                safe_postfix = postfix
                if not safe_postfix.strip().endswith(";"):
                    safe_postfix = safe_postfix.rstrip() + ";"
                out.append(f"{safe_edge_prefix} [{merged_attrs}]{safe_postfix}")
            else:
                safe_edge_prefix = _normalize_edge_prefix(line.rstrip(";"))
                out.append(f"{safe_edge_prefix} [{merged_attrs}];")
            continue

        if _is_node_declaration(line):
            prefix, inner, _ = split_attr(line)
            raw_node_name = _clean_dot_endpoint(prefix)
            node_label = extract_label(inner, raw_node_name)
            if DIAGRAM_SKIP_UNCONNECTED_NODES and connected_nodes and raw_node_name not in connected_nodes:
                logger.info("Skipping unconnected diagram node. node=%s label=%s", raw_node_name, node_label)
                continue
            if raw_node_name in isolated or is_isolated_node_name_or_label(node_label):
                logger.info("Skipping isolated diagram node. node=%s label=%s", raw_node_name, node_label)
                continue
            shape_match = re.search(r"shape\s*=\s*[\"']?(\w+)", inner)
            shape = shape_match.group(1) if shape_match else "box"
            out.append(styled_node(node_ref=raw_node_name, label=node_label, shape=shape))
            continue

        if _is_bare_node_statement(line):
            raw_node_name = _clean_dot_endpoint(line)
            node_label = clean_label(raw_node_name)
            if DIAGRAM_SKIP_UNCONNECTED_NODES and connected_nodes and raw_node_name not in connected_nodes:
                logger.info("Skipping unconnected bare diagram node. node=%s", raw_node_name)
                continue
            if is_isolated_node_name_or_label(raw_node_name):
                logger.info("Skipping isolated bare diagram node. node=%s", raw_node_name)
                continue
            out.append(styled_node(node_ref=raw_node_name, label=node_label, shape="box"))
            continue

        out.append(line)

    final_dot = normalize_edges("\n".join(out))
    final_dot = preprocess_diagram_text(final_dot)
    final_dot = _balance_dot_braces(final_dot)
    final_legend = _dedupe_legend_items(legend if legend else fallback_legend)
    return final_dot, final_legend

# ---------------------------------------------------------------------
# Legend rendering
# ---------------------------------------------------------------------
def build_legend_dot(items: List[Tuple[str, str]]) -> str:
    if not items:
        return ""
    dot = [
        "digraph Legend {",
        "  rankdir=LR;",
        "  graph [",
        '    bgcolor="white",',
        f"    pad={DIAGRAM_LEGEND_PAD},",
        f"    nodesep={DIAGRAM_LEGEND_NODESEP},",
        f"    ranksep={DIAGRAM_LEGEND_RANKSEP},",
        '    fontname="Helvetica-Bold"',
        "  ];",
        "",
        "  subgraph cluster_legend {",
        f'    label="{dot_escape(DIAGRAM_LEGEND_HEADING_LABEL)}";',
        f"    fontsize={DIAGRAM_LEGEND_TITLE_FONT_SIZE};",
        '    fontname="Helvetica-Bold";',
        f'    fontcolor="{DIAGRAM_LEGEND_TITLE_COLOR}";',
        f'    color="{DIAGRAM_LEGEND_BORDER_COLOR}";',
        f'    fillcolor="{DIAGRAM_LEGEND_FILL_COLOR}";',
        '    style="rounded,filled";',
        "    penwidth=1.2;",
        f"    margin={DIAGRAM_LEGEND_MARGIN};",
        '    labelloc="t";',
        '    labeljust="c";',
        "",
        "    node [",
        "      shape=box,",
        '      style="rounded,filled",',
        f'      fillcolor="{DIAGRAM_LEGEND_ITEM_FILL_COLOR}";',
        f'      color="{DIAGRAM_LEGEND_BORDER_COLOR}";',
        '      fontname="Helvetica-Bold",',
        f"      fontsize={DIAGRAM_LEGEND_ITEM_FONT_SIZE},",
        f'      fontcolor="{DIAGRAM_LEGEND_ITEM_FONT_COLOR}",',
        '      margin="0.14,0.08",',
        "      height=0.36,",
        "      penwidth=1.2",
        "    ];",
        "",
        "    edge [",
        f"      penwidth={DIAGRAM_LEGEND_EDGE_PENWIDTH},",
        f"      arrowsize={DIAGRAM_LEGEND_EDGE_ARROWSIZE}",
        "    ];",
        "",
    ]
    previous_target = None
    for idx, (color, label) in enumerate(items, start=1):
        source = f"legend_src_{idx}"
        target = f"legend_item_{idx}"
        safe_label = dot_escape(str(label).replace("\n", " ").strip())
        dot.extend([
            f'    "{source}" [',
            '      label="",',
            "      shape=point,",
            "      width=0.04,",
            "      height=0.04",
            "    ];",
            "",
            f'    "{target}" [',
            f'      label="{safe_label}"',
            "    ];",
            "",
            f'    "{source}" -> "{target}" [',
            f'      color="{color}",',
            "      minlen=1",
            "    ];",
            "",
        ])
        if previous_target:
            dot.append(f'    "{previous_target}" -> "{source}" [style=invis, weight=10, minlen=1];')
        previous_target = target
    same_rank_nodes = []
    for idx in range(1, len(items) + 1):
        same_rank_nodes.append(f'"legend_src_{idx}"')
        same_rank_nodes.append(f'"legend_item_{idx}"')
    dot.append("    { rank=same; " + "; ".join(same_rank_nodes) + "; }")
    dot.extend(["  }", "}"])
    return "\n".join(dot)


def render_legend_diagram(items: List[Tuple[str, str]]) -> Optional[str]:
    dot = build_legend_dot(items)
    if not dot:
        return None
    try:
        path = graphviz.Source(dot, format="png").render(filename="legend", directory=tempfile.mkdtemp(), cleanup=True)
        return trim_png_whitespace(path) if Path(path).exists() else None
    except Exception:
        debug_path = write_graphviz_debug_file(dot, prefix="aia_graphviz_legend_failed")
        logger.exception("Legend rendering failed. Debug DOT: %s", debug_path)
        return None

# ---------------------------------------------------------------------
# Public render functions
# ---------------------------------------------------------------------
def render_graphviz_to_png(text: str) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
    dot = normalize_to_graphviz_dot(text)
    if not dot:
        return None
    safe_dot, legend = normalize_dot_for_graphviz(dot)
    logger.info("Icon files found under ICON_DIR: %s", len(iter_icon_files()))
    try:
        path = graphviz.Source(safe_dot, format="png").render(filename="diagram", directory=tempfile.mkdtemp(), cleanup=True)
        if Path(path).exists():
            return trim_png_whitespace(path), legend
        return None
    except Exception:
        debug_path = write_graphviz_debug_file(safe_dot, prefix="aia_graphviz_failed")
        logger.exception("Graphviz render failed. Debug DOT: %s", debug_path)
        return None


def render_graphviz_to_assets(text: str, output_dir: str | Path, base_name: str = "diagram") -> Optional[Dict[str, Any]]:
    """
    Render Graphviz diagram into reusable assets:
      - <base_name>.png preview for DOCX/PDF
      - <base_name>_editable.svg vector file for draw.io/Visio conversion
      - <base_name>.dot source file for editing/regeneration

    Returns:
      {
        "png_path": "...",
        "svg_path": "...",
        "editable_svg_path": "...",
        "dot_path": "...",
        "legend": [...]
      }
    """
    dot = normalize_to_graphviz_dot(text)
    if not dot:
        return None
    safe_dot, legend = normalize_dot_for_graphviz(dot)
    try:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_base = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(base_name or "diagram")).strip("._").lower() or "diagram"
        dot_path = output_dir / f"{safe_base}.dot"
        dot_path.write_text(safe_dot, encoding="utf-8")

        png_path = graphviz.Source(safe_dot, format="png").render(filename=safe_base, directory=str(output_dir), cleanup=True)
        if Path(png_path).exists():
            png_path = trim_png_whitespace(png_path)

        svg_path = graphviz.Source(safe_dot, format="svg").render(filename=f"{safe_base}_editable", directory=str(output_dir), cleanup=True)

        if not Path(png_path).exists():
            logger.error("PNG diagram asset was not generated: %s", png_path)
            return None
        if not Path(svg_path).exists():
            logger.warning("SVG diagram asset was not generated: %s", svg_path)

        return {
            "png_path": str(png_path),
            "svg_path": str(svg_path) if Path(svg_path).exists() else None,
            "editable_svg_path": str(svg_path) if Path(svg_path).exists() else None,
            "dot_path": str(dot_path),
            "legend": legend,
        }
    except Exception:
        debug_path = write_graphviz_debug_file(safe_dot, prefix="aia_graphviz_asset_failed")
        logger.exception("Graphviz asset rendering failed. Debug DOT: %s", debug_path)
        return None


def inline_image_token(path: Optional[str]) -> str:
    if not path:
        return "N/A"
    return "IMAGE_TOKEN_START" + Path(path).resolve().as_posix() + "IMAGE_TOKEN_END"

# from __future__ import annotations

# """
# graphviz_renderer.py

# Full regenerated Graphviz renderer for AIA HLD diagrams.

# Purpose of this version:
# - Keep main process/data flow left-to-right.
# - Keep flow legends rendered and aligned using an HTML-table legend.
# - Preserve declared support clusters such as Observability and CI/CD/IaC instead of
#   incorrectly treating support components as junk nodes.
# - Avoid random arrows from non-flow/support/control edges disturbing the primary flow.
# - Fix malformed Graphviz HTML labels, including spaced labels such as:
#       label = < <B>GCP Ingestion & Processing</B> >;
#   into:
#       label=<<B>GCP Ingestion &amp; Processing</B>>;
# - Remove // comments outside quoted strings so comments never become fake nodes.
# - Keep the implementation generic: no project-specific, section-specific, or
#   service-specific hardcoding.
# - Fix DOT cleanup so valid root/subgraph closing braces are not removed.
# """

# import hashlib
# import html
# import logging
# import re
# import tempfile
# from dataclasses import dataclass
# from pathlib import Path
# from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# import graphviz
# from PIL import Image

# from . import config as render_config
# from .config import (
#     PROJECT_ROOT,
#     DIAGRAM_GRAPH_FONT_SIZE,
#     DIAGRAM_NODE_FONT_SIZE,
#     DIAGRAM_EDGE_FONT_SIZE,
#     DIAGRAM_NODE_CARD_WIDTH_IN,
#     DIAGRAM_NODE_CARD_HEIGHT_IN,
#     DIAGRAM_NODE_CARD_SIZE,
#     DIAGRAM_FORCE_RANKDIR,
#     DIAGRAM_GRAPH_SPLINES,
#     DIAGRAM_GRAPH_RANKSEP,
#     DIAGRAM_GRAPH_NODESEP,
#     DIAGRAM_GRAPH_PAD,
#     DIAGRAM_GRAPH_OVERLAP,
#     DIAGRAM_GRAPH_OUTPUT_ORDER,
#     DIAGRAM_GRAPH_NEWRANK,
#     DIAGRAM_EDGE_PENWIDTH,
#     DIAGRAM_EDGE_MINLEN,
#     DIAGRAM_EDGE_ARROWSIZE,
#     DIAGRAM_LEGEND_TITLE_FONT_SIZE,
#     DIAGRAM_LEGEND_ITEM_FONT_SIZE,
#     DIAGRAM_LEGEND_HEADING_LABEL,
#     DIAGRAM_LEGEND_BORDER_COLOR,
#     DIAGRAM_LEGEND_FILL_COLOR,
#     DIAGRAM_LEGEND_TITLE_COLOR,
#     DIAGRAM_LEGEND_ITEM_FONT_COLOR,
#     DIAGRAM_LEGEND_ITEM_FILL_COLOR,
#     DIAGRAM_LEGEND_MARGIN,
#     DIAGRAM_LEGEND_PAD,
#     DIAGRAM_LEGEND_NODESEP,
#     DIAGRAM_LEGEND_RANKSEP,
#     DIAGRAM_LEGEND_EDGE_PENWIDTH,
#     DIAGRAM_LEGEND_EDGE_ARROWSIZE,
#     DIAGRAM_NODE_DEFAULT_FILL,
#     DIAGRAM_NODE_DEFAULT_BORDER,
#     DIAGRAM_NODE_DEFAULT_MARGIN,
#     DIAGRAM_NODE_DEFAULT_PENWIDTH,
#     DIAGRAM_CLUSTER_FONT_SIZE,
#     DIAGRAM_CLUSTER_FILL_COLOR,
#     DIAGRAM_CLUSTER_BORDER_COLOR,
#     DIAGRAM_CLUSTER_FONT_COLOR,
#     DIAGRAM_CLUSTER_STYLE,
#     DIAGRAM_CLUSTER_PENWIDTH,
#     DIAGRAM_CLUSTER_MARGIN,
#     DIAGRAM_CLUSTER_LABEL_BOLD,
# )
# from .icon_resolver import (
#     get_style_for_label,
#     is_isolated_node_name_or_label,
#     iter_icon_files,
#     resolve_icon_from_node_label,
# )
# from .node_card import clean_label, make_composite_node_card, normalize_icon_for_graphviz

# logger = logging.getLogger(__name__)

# # ---------------------------------------------------------------------
# # Optional config values with safe defaults
# # ---------------------------------------------------------------------
# DIAGRAM_GRAPH_RATIO = getattr(render_config, "DIAGRAM_GRAPH_RATIO", "compress")
# DIAGRAM_GRAPH_CONCENTRATE = getattr(render_config, "DIAGRAM_GRAPH_CONCENTRATE", False)
# DIAGRAM_GRAPH_COMPOUND = getattr(render_config, "DIAGRAM_GRAPH_COMPOUND", True)
# DIAGRAM_GRAPH_DPI = getattr(render_config, "DIAGRAM_GRAPH_DPI", 180)
# DIAGRAM_TRIM_PNG_WHITESPACE = getattr(render_config, "DIAGRAM_TRIM_PNG_WHITESPACE", True)
# DIAGRAM_TRIM_PNG_BACKGROUND_THRESHOLD = getattr(render_config, "DIAGRAM_TRIM_PNG_BACKGROUND_THRESHOLD", 248)
# DIAGRAM_TRIM_PNG_PADDING_PX = getattr(render_config, "DIAGRAM_TRIM_PNG_PADDING_PX", 18)
# DIAGRAM_SKIP_UNCONNECTED_NODES = getattr(render_config, "DIAGRAM_SKIP_UNCONNECTED_NODES", True)
# DIAGRAM_USE_IMAGE_CARDS_FOR_PNG = getattr(render_config, "DIAGRAM_USE_IMAGE_CARDS_FOR_PNG", True)
# DIAGRAM_USE_IMAGE_CARDS_FOR_EDITABLE_SVG = getattr(render_config, "DIAGRAM_USE_IMAGE_CARDS_FOR_EDITABLE_SVG", False)

# # Generic edge policy. These are semantic categories, not project-specific names.
# DIAGRAM_FILTER_NON_FLOW_EDGES = getattr(render_config, "DIAGRAM_FILTER_NON_FLOW_EDGES", True)
# DIAGRAM_EDGE_TYPE_ATTRS = tuple(
#     getattr(
#         render_config,
#         "DIAGRAM_EDGE_TYPE_ATTRS",
#         (
#             "edge_type",
#             "type",
#             "category",
#             "purpose",
#             "relationship",
#             "flow_type",
#         ),
#     )
# )
# DIAGRAM_PRIMARY_EDGE_TYPES = tuple(
#     getattr(
#         render_config,
#         "DIAGRAM_PRIMARY_EDGE_TYPES",
#         (
#             "data",
#             "data_flow",
#             "process",
#             "process_flow",
#             "runtime",
#             "runtime_flow",
#             "integration",
#             "application_flow",
#             "request",
#             "response",
#             "event",
#             "message",
#             "file_transfer",
#             "dependency",
#             "support",
#             "key_access",
#         ),
#     )
# )
# DIAGRAM_NON_RENDER_EDGE_TYPES = tuple(
#     getattr(
#         render_config,
#         "DIAGRAM_NON_RENDER_EDGE_TYPES",
#         (
#             "control",
#             "control_flow",
#             "security",
#             "governance",
#             "policy",
#             "boundary",
#             "perimeter",
#             "annotation",
#             "note",
#             "legend",
#             "observability",
#             "monitoring",
#             "logging",
#             "audit",
#             "compliance",
#             "guardrail",
#             "cicd",
#             "ci_cd",
#             "iac",
#         ),
#     )
# )
# DIAGRAM_EDGE_RENDER_ATTRS = tuple(getattr(render_config, "DIAGRAM_EDGE_RENDER_ATTRS", ("render", "show", "visible", "include")))
# DIAGRAM_EDGE_LEGEND_ATTRS = tuple(getattr(render_config, "DIAGRAM_EDGE_LEGEND_ATTRS", ("legend", "legend_include", "show_in_legend")))
# DIAGRAM_EDGE_FLOW_ATTRS = tuple(getattr(render_config, "DIAGRAM_EDGE_FLOW_ATTRS", ("flow", "is_flow", "primary_flow")))
# DIAGRAM_ENABLE_EDGE_LABEL_FALLBACK = getattr(render_config, "DIAGRAM_ENABLE_EDGE_LABEL_FALLBACK", True)
# DIAGRAM_NON_FLOW_LABEL_PATTERNS = tuple(
#     getattr(
#         render_config,
#         "DIAGRAM_NON_FLOW_LABEL_PATTERNS",
#         (
#             r"\bsecurity\b",
#             r"\bgovernance\b",
#             r"\bpolicy\b",
#             r"\bpolicies\b",
#             r"\bcontrol\b",
#             r"\bcontrols\b",
#             r"\bboundary\b",
#             r"\bperimeter\b",
#             r"\bcompliance\b",
#             r"\bguardrail\b",
#             r"\bguardrails\b",
#             r"\baudit\b",
#             r"\blogging\b",
#             r"\bmonitoring\b",
#             r"\bmetrics\b",
#             r"\balerts?\b",
#             r"\bobservability\b",
#             r"\bci\s*/?\s*cd\b",
#             r"\biac\b",
#             r"\bterraform\b",
#         ),
#     )
# )


# @dataclass(frozen=True)
# class _EdgePolicyDecision:
#     keep: bool
#     include_in_legend: bool
#     reason: str = ""


# # ---------------------------------------------------------------------
# # Core escaping / cleanup helpers
# # ---------------------------------------------------------------------
# def dot_escape(value: Any) -> str:
#     """Escape a value for Graphviz quoted strings."""
#     return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# def _html_escape_text(value: Any) -> str:
#     return html.escape(str(value or ""), quote=True)


# def _safe_hex_color(value: Any, fallback: str = "#666666") -> str:
#     text = str(value or "").strip()
#     if re.match(r"^#[0-9A-Fa-f]{6}$", text):
#         return text
#     return fallback


# def _graph_bool(value: bool) -> str:
#     return "true" if value else "false"


# def _quote_dot_id(value: Any) -> str:
#     raw = str(value or "").strip().rstrip(";")
#     if not raw:
#         return '"node"'
#     if raw.startswith('"') and raw.endswith('"'):
#         return raw
#     if raw.startswith("<") and raw.endswith(">"):
#         return raw
#     return f'"{dot_escape(raw.strip(chr(34)))}"'


# def _clean_dot_endpoint(value: str) -> str:
#     cleaned = str(value or "").strip().strip('"').strip("'").rstrip(";")
#     cleaned = re.sub(r"\s+", " ", cleaned)
#     return cleaned


# def _strip_port_suffix(endpoint: str) -> str:
#     endpoint = _clean_dot_endpoint(endpoint)
#     if ":" in endpoint and not endpoint.startswith("<"):
#         return endpoint.split(":", 1)[0].strip()
#     return endpoint


# def _strip_dot_line_comments_preserve_urls(dot_text: str) -> str:
#     """Remove // comments outside quoted strings, preserving URLs inside quoted attributes."""
#     cleaned_lines: List[str] = []
#     for raw_line in str(dot_text or "").splitlines():
#         line = raw_line.rstrip()
#         out: List[str] = []
#         in_quote = False
#         escaped = False
#         i = 0

#         while i < len(line):
#             ch = line[i]
#             nxt = line[i + 1] if i + 1 < len(line) else ""

#             if escaped:
#                 out.append(ch)
#                 escaped = False
#                 i += 1
#                 continue

#             if ch == "\\" and in_quote:
#                 out.append(ch)
#                 escaped = True
#                 i += 1
#                 continue

#             if ch == '"':
#                 in_quote = not in_quote
#                 out.append(ch)
#                 i += 1
#                 continue

#             if not in_quote and ch == "/" and nxt == "/":
#                 break

#             out.append(ch)
#             i += 1

#         stripped = "".join(out).strip()
#         if stripped:
#             cleaned_lines.append(stripped)

#     return "\n".join(cleaned_lines)


# def _count_dot_brace_delta(dot_text: str) -> int:
#     in_quote = False
#     escaped = False
#     delta = 0

#     for char in str(dot_text or ""):
#         if escaped:
#             escaped = False
#             continue

#         if char == "\\":
#             escaped = True
#             continue

#         if char == '"':
#             in_quote = not in_quote
#             continue

#         if in_quote:
#             continue

#         if char == "{":
#             delta += 1
#         elif char == "}":
#             delta -= 1

#     return delta


# def _remove_orphan_cluster_labels_and_extra_braces(dot_text: str) -> str:
#     """
#     Safely remove only truly orphan root-level labels and extra closing braces.

#     Important:
#     - Do NOT remove valid graph/subgraph closing braces.
#     - Do NOT assume depth <= 1 means a brace is invalid.
#     - Preserve empty support clusters such as Observability and CI/CD.
#     - Rebalance missing final braces generically.
#     """
#     lines = [line.rstrip() for line in str(dot_text or "").splitlines() if line.strip()]
#     if not lines:
#         return "digraph G {\n  rankdir=LR;\n}\n"

#     cleaned: List[str] = []
#     depth = 0

#     for raw in lines:
#         line = raw.strip()

#         # Drop only unmatched extra closing braces.
#         # A brace at depth 1 is valid because it closes the root graph.
#         if line == "}" and depth <= 0:
#             logger.warning("Dropping extra root-level closing brace from DOT cleanup.")
#             continue

#         # Drop only labels that are completely outside the graph body.
#         # Graph-level labels inside digraph { ... } and cluster labels must be preserved.
#         if depth == 0 and re.match(
#             r"^label\s*=\s*(?:<<.*?>>|<.*?>|\".*?\")\s*;?$",
#             line,
#             flags=re.IGNORECASE | re.DOTALL,
#         ):
#             logger.warning("Dropping orphan label outside DOT graph body: %s", line)
#             continue

#         cleaned.append(raw)

#         depth += _count_dot_brace_delta(raw)
#         if depth < 0:
#             depth = 0

#     text = "\n".join(cleaned).rstrip()
#     if not text:
#         return "digraph G {\n  rankdir=LR;\n}\n"

#     delta = _count_dot_brace_delta(text)

#     if delta > 0:
#         logger.warning("DOT cleanup detected %s missing closing brace(s). Auto-appending.", delta)
#         text += ("\n}" * delta)

#     elif delta < 0:
#         logger.warning("DOT cleanup detected %s extra closing brace(s). Removing from end.", abs(delta))
#         while _count_dot_brace_delta(text) < 0:
#             idx = text.rfind("}")
#             if idx == -1:
#                 break
#             text = text[:idx] + text[idx + 1:]

#     return text.rstrip() + "\n"


# def _balance_dot_braces(dot_text: str) -> str:
#     delta = _count_dot_brace_delta(dot_text)

#     if delta > 0:
#         logger.warning("Graphviz DOT had %s missing closing brace(s). Auto-appending.", delta)
#         return str(dot_text or "").rstrip() + ("\n}" * delta) + "\n"

#     if delta < 0:
#         logger.warning("Graphviz DOT has %s extra closing brace(s). Cleaning extra braces.", abs(delta))
#         return _remove_orphan_cluster_labels_and_extra_braces(dot_text)

#     return str(dot_text or "").rstrip() + "\n"


# def _validate_dot_brace_balance(dot_text: str, context: str = "graphviz_dot") -> str:
#     """
#     Generic DOT structural validation helper.

#     This does not understand service names or project-specific labels.
#     It only checks the final brace balance and appends/removes braces safely.
#     """
#     safe_dot = str(dot_text or "").rstrip()
#     delta = _count_dot_brace_delta(safe_dot)

#     if delta > 0:
#         logger.warning(
#             "%s has %s missing closing brace(s). Auto-appending.",
#             context,
#             delta,
#         )
#         safe_dot += ("\n}" * delta)

#     elif delta < 0:
#         logger.warning(
#             "%s has %s extra closing brace(s). Removing unmatched closing brace(s).",
#             context,
#             abs(delta),
#         )
#         while _count_dot_brace_delta(safe_dot) < 0:
#             idx = safe_dot.rfind("}")
#             if idx == -1:
#                 break
#             safe_dot = safe_dot[:idx] + safe_dot[idx + 1:]

#     return safe_dot.rstrip() + "\n"


# # ---------------------------------------------------------------------
# # Graphviz HTML label sanitization
# # ---------------------------------------------------------------------
# def _sanitize_graphviz_html_like_labels(dot_text: str) -> str:
#     """Normalize Graphviz HTML labels and escaped arrows."""
#     if not dot_text:
#         return dot_text

#     text = str(dot_text)

#     text = (
#         text.replace("-&amp;amp;amp;amp;amp;gt;", "->")
#         .replace("-&amp;amp;amp;amp;gt;", "->")
#         .replace("-&amp;amp;amp;gt;", "->")
#         .replace("-&amp;amp;gt;", "->")
#         .replace("-&amp;gt;", "->")
#         .replace("-&gt;", "->")
#         .replace("→", "->")
#     )

#     text = re.sub(r"\bsubgraph\s+cluster_(?:cluster_)+", "subgraph cluster_", text)
#     text = re.sub(
#         r'(subgraph\s+cluster_[A-Za-z0-9_]+\s*\{\s*)label="cluster_[^"]+";\s*(label=)',
#         r"\1\2",
#         text,
#         flags=re.IGNORECASE,
#     )

#     def _html_body_to_graphviz(body: str) -> str:
#         body = html.unescape(str(body or "")).strip()
#         body = re.sub(r"^\s*<\s*<\s*", "<<", body)
#         body = re.sub(r"\s*>\s*>\s*$", ">>", body)

#         if body.startswith("<<") and body.endswith(">>"):
#             body = body[2:-2]
#         elif body.startswith("<") and body.endswith(">"):
#             body = body[1:-1]

#         body = re.sub(r"<\s*b\s*>", "<B>", body, flags=re.IGNORECASE)
#         body = re.sub(r"<\s*/\s*b\s*>", "</B>", body, flags=re.IGNORECASE)
#         body = re.sub(r"<\s*br\s*/?\s*>", "<BR/>", body, flags=re.IGNORECASE)
#         body = re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#x[0-9A-Fa-f]+;)", "&amp;", body)

#         return f"<<{body}>>"

#     html_label_patterns = [
#         r"label\s*=\s*(&lt;\s*&lt;.*?&gt;\s*&gt;)\s*;?",
#         r"label\s*=\s*(<\s*<.*?>\s*>)\s*;?",
#         r"label\s*=\s*(&lt;&lt;.*?&gt;&gt;)\s*;?",
#         r"label\s*=\s*(<<.*?>>)\s*;?",
#     ]

#     for pattern in html_label_patterns:
#         text = re.sub(
#             pattern,
#             lambda m: f"label={_html_body_to_graphviz(m.group(1))};",
#             text,
#             flags=re.IGNORECASE | re.DOTALL,
#         )

#     return text


# # ---------------------------------------------------------------------
# # DOT statement and attribute parsing
# # ---------------------------------------------------------------------
# def _split_dot_statements(dot: str) -> List[str]:
#     statements: List[str] = []
#     buffer: List[str] = []
#     in_quote = False
#     escaped = False
#     attr_depth = 0
#     html_depth = 0

#     text = _strip_dot_line_comments_preserve_urls(str(dot or ""))

#     for char in text:
#         buffer.append(char)

#         if escaped:
#             escaped = False
#             continue

#         if char == "\\":
#             escaped = True
#             continue

#         if char == '"':
#             in_quote = not in_quote
#             continue

#         if in_quote:
#             continue

#         if char == "<":
#             html_depth += 1
#             continue

#         if char == ">" and html_depth > 0:
#             html_depth -= 1
#             continue

#         if html_depth > 0:
#             continue

#         if char == "[":
#             attr_depth += 1
#             continue

#         if char == "]":
#             attr_depth = max(0, attr_depth - 1)
#             continue

#         if attr_depth == 0 and char in "{};":
#             statement = "".join(buffer).strip()
#             buffer = []
#             if statement:
#                 statements.append(statement)

#     tail = "".join(buffer).strip()
#     if tail:
#         statements.append(tail)

#     return statements


# def split_attr(line: str) -> Tuple[str, str, str]:
#     if "[" not in line or "]" not in line:
#         return line, "", ""

#     prefix, rest = line.split("[", 1)
#     inner, postfix = rest.rsplit("]", 1)
#     return prefix, inner, postfix


# def _remove_attrs_from_edge(line: str) -> str:
#     out: List[str] = []
#     in_quote = False
#     escaped = False
#     attr_depth = 0
#     html_depth = 0

#     for char in str(line or ""):
#         if escaped:
#             if attr_depth == 0:
#                 out.append(char)
#             escaped = False
#             continue

#         if char == "\\":
#             if attr_depth == 0:
#                 out.append(char)
#             escaped = True
#             continue

#         if char == '"':
#             if attr_depth == 0:
#                 out.append(char)
#             in_quote = not in_quote
#             continue

#         if not in_quote:
#             if char == "<":
#                 html_depth += 1
#             elif char == ">" and html_depth > 0:
#                 html_depth -= 1
#             elif char == "[" and html_depth == 0:
#                 attr_depth += 1
#                 continue
#             elif char == "]" and attr_depth > 0 and html_depth == 0:
#                 attr_depth -= 1
#                 continue

#         if attr_depth == 0:
#             out.append(char)

#     return "".join(out)


# def _extract_edge_endpoints(line: str) -> List[str]:
#     edge_without_attrs = _remove_attrs_from_edge(line).strip().rstrip(";")

#     if "->" in edge_without_attrs:
#         parts = re.split(r"->", edge_without_attrs)
#     elif "--" in edge_without_attrs:
#         parts = re.split(r"--", edge_without_attrs)
#     else:
#         return []

#     return [_strip_port_suffix(part) for part in parts if _clean_dot_endpoint(part)]


# def _split_attrs(inner: str) -> List[str]:
#     parts: List[str] = []
#     buf: List[str] = []
#     in_quote = False
#     escaped = False
#     html_depth = 0

#     for ch in str(inner or ""):
#         if escaped:
#             buf.append(ch)
#             escaped = False
#             continue

#         if ch == "\\" and in_quote:
#             buf.append(ch)
#             escaped = True
#             continue

#         if ch == '"':
#             in_quote = not in_quote
#             buf.append(ch)
#             continue

#         if not in_quote:
#             if ch == "<":
#                 html_depth += 1
#             elif ch == ">" and html_depth > 0:
#                 html_depth -= 1
#             elif ch == "," and html_depth == 0:
#                 part = "".join(buf).strip()
#                 if part:
#                     parts.append(part)
#                 buf = []
#                 continue

#         buf.append(ch)

#     part = "".join(buf).strip()
#     if part:
#         parts.append(part)

#     return parts


# def _decode_attr_value(value: str) -> str:
#     text = str(value or "").strip()

#     if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
#         text = text[1:-1]

#     if text.startswith("<") and text.endswith(">"):
#         text = re.sub(r"<\s*BR\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
#         text = re.sub(r"<\s*/?\s*B\s*>", "", text, flags=re.IGNORECASE)
#         text = re.sub(r"<[^>]+>", "", text)

#     text = html.unescape(text).replace("\\n", "\n").replace('\\"', '"').strip()
#     return "" if text in {"<", ">", "<<", ">>"} else text


# def _parse_dot_attrs(inner: str) -> Dict[str, str]:
#     attrs: Dict[str, str] = {}

#     for part in _split_attrs(inner or ""):
#         if "=" not in part:
#             continue

#         key, value = part.split("=", 1)
#         key = key.strip().lower()

#         if key:
#             attrs[key] = _decode_attr_value(value)

#     return attrs


# def _first_attr(attrs: Dict[str, str], names: Sequence[str]) -> str:
#     for name in names:
#         value = attrs.get(str(name).lower())
#         if value not in (None, ""):
#             return str(value)
#     return ""


# def _parse_bool_attr(value: Any) -> Optional[bool]:
#     text = str(value or "").strip().lower()

#     if text in {"true", "yes", "y", "1", "on"}:
#         return True

#     if text in {"false", "no", "n", "0", "off"}:
#         return False

#     return None


# def _first_bool_attr(attrs: Dict[str, str], names: Sequence[str]) -> Optional[bool]:
#     for name in names:
#         key = str(name).lower()
#         if key not in attrs:
#             continue

#         parsed = _parse_bool_attr(attrs.get(key))
#         if parsed is not None:
#             return parsed

#     return None


# def _normalize_policy_token(value: Any) -> str:
#     return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


# def _matches_any_pattern(text: str, patterns: Iterable[str]) -> bool:
#     source = str(text or "").strip().lower()
#     if not source:
#         return False

#     for pattern in patterns:
#         try:
#             if re.search(pattern, source, flags=re.IGNORECASE):
#                 return True
#         except re.error:
#             logger.warning("Invalid diagram non-flow regex ignored: %s", pattern)

#     return False


# def _edge_policy_decision(inner: str) -> _EdgePolicyDecision:
#     if not DIAGRAM_FILTER_NON_FLOW_EDGES:
#         return _EdgePolicyDecision(True, True, "filter_disabled")

#     attrs = _parse_dot_attrs(inner)

#     explicit_render = _first_bool_attr(attrs, DIAGRAM_EDGE_RENDER_ATTRS)
#     if explicit_render is False:
#         return _EdgePolicyDecision(False, False, "explicit_render_false")

#     explicit_legend = _first_bool_attr(attrs, DIAGRAM_EDGE_LEGEND_ATTRS)
#     explicit_flow = _first_bool_attr(attrs, DIAGRAM_EDGE_FLOW_ATTRS)

#     if explicit_flow is True:
#         return _EdgePolicyDecision(True, explicit_legend is not False, "explicit_flow_true")

#     edge_type = _normalize_policy_token(_first_attr(attrs, DIAGRAM_EDGE_TYPE_ATTRS))
#     primary_types = {_normalize_policy_token(v) for v in DIAGRAM_PRIMARY_EDGE_TYPES}
#     non_render_types = {_normalize_policy_token(v) for v in DIAGRAM_NON_RENDER_EDGE_TYPES}

#     if edge_type in primary_types:
#         return _EdgePolicyDecision(True, explicit_legend is not False, f"primary_type:{edge_type}")

#     if edge_type in non_render_types:
#         return _EdgePolicyDecision(False, False, f"non_render_type:{edge_type}")

#     if explicit_render is True:
#         return _EdgePolicyDecision(True, explicit_legend is not False, "explicit_render_true")

#     label = attrs.get("label") or attrs.get("xlabel") or attrs.get("headlabel") or attrs.get("taillabel") or ""

#     if DIAGRAM_ENABLE_EDGE_LABEL_FALLBACK and _matches_any_pattern(label, DIAGRAM_NON_FLOW_LABEL_PATTERNS):
#         return _EdgePolicyDecision(False, False, "non_flow_label_pattern")

#     if explicit_legend is False:
#         return _EdgePolicyDecision(True, False, "explicit_legend_false")

#     return _EdgePolicyDecision(True, True, "default_keep")


# def _strip_existing_attr_key(inner: str, key: str) -> str:
#     if not inner:
#         return ""

#     pattern = rf'\b{re.escape(key)}\s*=\s*("[^"]*"|<<.*?>>|<.*?>|[^,\]]+)\s*,?'
#     cleaned = re.sub(pattern, "", inner, flags=re.IGNORECASE | re.DOTALL)
#     cleaned = re.sub(r",\s*,", ",", cleaned)
#     return cleaned.strip().strip(",")


# def _merge_edge_attributes(inner: str, color: str) -> str:
#     cleaned = inner or ""

#     for key in [
#         "label",
#         "xlabel",
#         "headlabel",
#         "taillabel",
#         "color",
#         "penwidth",
#         "minlen",
#         "arrowsize",
#         "constraint",
#         "weight",
#     ]:
#         cleaned = _strip_existing_attr_key(cleaned, key)

#     attrs: List[str] = []

#     if cleaned.strip():
#         attrs.append(cleaned.strip())

#     attrs.extend(
#         [
#             f'color="{_safe_hex_color(color)}"',
#             f"penwidth={DIAGRAM_EDGE_PENWIDTH}",
#             f"minlen={DIAGRAM_EDGE_MINLEN}",
#             f"arrowsize={DIAGRAM_EDGE_ARROWSIZE}",
#             "constraint=true",
#             "weight=10",
#         ]
#     )

#     return ",".join(attrs)


# def _is_node_declaration(line: str) -> bool:
#     stripped = line.strip()
#     if not stripped:
#         return False

#     if stripped.lower().startswith(("graph ", "node ", "edge ")):
#         return False

#     if "->" in stripped or "--" in stripped:
#         return False

#     return "[" in stripped and "]" in stripped


# def _is_bare_node_statement(line: str) -> bool:
#     stripped = str(line or "").strip().rstrip(";")
#     if not stripped or stripped in {"{", "}"}:
#         return False

#     lowered = stripped.lower()

#     if "->" in stripped or "--" in stripped:
#         return False

#     if "[" in stripped or "]" in stripped or "=" in stripped:
#         return False

#     if lowered.startswith(("digraph ", "graph ", "subgraph ", "node ", "edge ")):
#         return False

#     if stripped.startswith("//") or stripped.startswith("#"):
#         return False

#     return True


# def _normalize_edge_prefix(edge_prefix: str) -> str:
#     raw = str(edge_prefix or "").strip().rstrip(";")

#     if "->" in raw:
#         operator = "->"
#     elif "--" in raw:
#         operator = "--"
#     else:
#         return _quote_dot_id(raw)

#     parts = [part.strip().strip('"') for part in re.split(r"->|--", raw) if part.strip()]
#     if len(parts) < 2:
#         return raw

#     return f" {operator} ".join(_quote_dot_id(_strip_port_suffix(part)) for part in parts)


# def _dedupe_legend_items(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
#     deduped: List[Tuple[str, str]] = []
#     seen = set()

#     for color, label in items:
#         safe_color = _safe_hex_color(color)
#         safe_label = str(label or "").strip()

#         if not safe_label:
#             continue

#         key = (safe_color.lower(), safe_label.lower())
#         if key in seen:
#             continue

#         seen.add(key)
#         deduped.append((safe_color, safe_label))

#     return deduped


# def _make_fallback_flow_label(endpoints: List[str], labels: Dict[str, str]) -> str:
#     if len(endpoints) < 2:
#         return ""

#     source_label = clean_label(labels.get(endpoints[0], endpoints[0]))
#     target_label = clean_label(labels.get(endpoints[-1], endpoints[-1]))

#     if not source_label or not target_label:
#         return ""

#     return f"{source_label} to {target_label}"


# # ---------------------------------------------------------------------
# # Debug and image helpers
# # ---------------------------------------------------------------------
# def write_graphviz_debug_file(safe_dot: str, prefix: str = "aia_graphviz_failed") -> Path:
#     debug_path = Path(tempfile.gettempdir()) / f"{prefix}_{hashlib.sha1(safe_dot.encode()).hexdigest()[:8]}.dot"
#     debug_path.write_text(safe_dot, encoding="utf-8")

#     logger.error("Failed Graphviz DOT written to: %s", debug_path)

#     for idx, line in enumerate(safe_dot.splitlines(), start=1):
#         logger.error("DOT %03d: %s", idx, line)

#     return debug_path


# def trim_png_whitespace(
#     image_path: str,
#     background_threshold: int = DIAGRAM_TRIM_PNG_BACKGROUND_THRESHOLD,
#     padding_px: int = DIAGRAM_TRIM_PNG_PADDING_PX,
# ) -> str:
#     if not DIAGRAM_TRIM_PNG_WHITESPACE:
#         return image_path

#     try:
#         path = Path(image_path)
#         if not path.exists():
#             return image_path

#         raw_image = Image.open(path).convert("RGBA")
#         white_background = Image.new("RGBA", raw_image.size, "white")
#         image = Image.alpha_composite(white_background, raw_image).convert("RGB")

#         pixels = image.load()
#         width, height = image.size

#         left, top, right, bottom = width, height, 0, 0

#         for y in range(height):
#             for x in range(width):
#                 r, g, b = pixels[x, y]
#                 if not (
#                     r >= background_threshold
#                     and g >= background_threshold
#                     and b >= background_threshold
#                 ):
#                     left = min(left, x)
#                     top = min(top, y)
#                     right = max(right, x)
#                     bottom = max(bottom, y)

#         if right <= left or bottom <= top:
#             return image_path

#         left = max(0, left - padding_px)
#         top = max(0, top - padding_px)
#         right = min(width, right + padding_px)
#         bottom = min(height, bottom + padding_px)

#         image.crop((left, top, right, bottom)).save(path, "PNG")
#         return str(path)

#     except Exception:
#         logger.exception("Failed to trim Graphviz PNG whitespace. image_path=%s", image_path)
#         return image_path


# # ---------------------------------------------------------------------
# # Text normalization and conversion
# # ---------------------------------------------------------------------
# def preprocess_diagram_text(text: Any) -> str:
#     if text is None:
#         return ""

#     text = str(text)

#     for _ in range(4):
#         new_text = html.unescape(text)
#         if new_text == text:
#             break
#         text = new_text

#     replacements = {
#         "--&amp;amp;amp;amp;amp;amp;amp;amp;amp;amp;gt;": "->",
#         "-&amp;amp;amp;amp;amp;amp;amp;amp;amp;amp;gt;": "->",
#         "--&amp;amp;amp;amp;amp;amp;amp;amp;amp;gt;": "->",
#         "-&amp;amp;amp;amp;amp;amp;amp;amp;amp;gt;": "->",
#         "--&amp;amp;amp;amp;amp;amp;amp;amp;gt;": "->",
#         "-&amp;amp;amp;amp;amp;amp;amp;amp;gt;": "->",
#         "--&amp;amp;amp;amp;amp;amp;amp;gt;": "->",
#         "-&amp;amp;amp;amp;amp;amp;amp;gt;": "->",
#         "--&amp;amp;amp;amp;amp;amp;gt;": "->",
#         "-&amp;amp;amp;amp;amp;amp;gt;": "->",
#         "--&amp;amp;amp;amp;amp;gt;": "->",
#         "-&amp;amp;amp;amp;amp;gt;": "->",
#         "-&amp;amp;amp;gt;": "->",
#         "-&amp;amp;gt;": "->",
#         "-&amp;gt;": "->",
#         "-&gt;": "->",
#         "-\\>": "->",
#         "→": "->",
#         "\\[": "[",
#         "\\]": "]",
#         "\\{": "{",
#         "\\}": "}",
#         "\\_": "_",
#         "\\#": "#",
#         "\\;": ";",
#         "\\(": "(",
#         "\\)": ")",
#         "<br/>": "\\n",
#         "<br />": "\\n",
#         "<br>": "\\n",
#     }

#     for old, new in replacements.items():
#         text = text.replace(old, new)

#     return text.strip()


# def strip_code_fence(text: Any) -> str:
#     raw = preprocess_diagram_text(text).strip()
#     raw = re.sub(r"^```(?:dot|graphviz|mermaid|gv)?\s*", "", raw, flags=re.IGNORECASE)
#     raw = re.sub(r"\s*```$", "", raw)
#     return raw.strip()


# def classify_diagram_text(text: Any) -> Tuple[str, str]:
#     raw = strip_code_fence(text)
#     lines = raw.splitlines()
#     first = lines[0].strip() if lines else ""

#     if raw.startswith(("digraph ", "graph ")):
#         if re.match(r"^graph\s+(TD|TB|BT|LR|RL)\b", first, re.IGNORECASE):
#             return "mermaid_like", raw
#         return "graphviz", raw

#     if re.match(r"^(graph|flowchart)\s+(TD|TB|BT|LR|RL)\b", first, re.IGNORECASE):
#         return "mermaid_like", raw

#     return "plain", raw


# def mermaid_like_to_dot(text: str) -> Optional[str]:
#     lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
#     if not lines:
#         return None

#     rankdir = DIAGRAM_FORCE_RANKDIR or "LR"

#     first_match = re.match(r"^(graph|flowchart)\s+(TD|TB|BT|LR|RL)$", lines[0], re.IGNORECASE)
#     if first_match:
#         mermaid_dir = first_match.group(2).upper()
#         detected_rankdir = {
#             "TD": "TB",
#             "TB": "TB",
#             "BT": "BT",
#             "LR": "LR",
#             "RL": "RL",
#         }.get(mermaid_dir, rankdir)
#         rankdir = DIAGRAM_FORCE_RANKDIR or detected_rankdir
#         lines = lines[1:]

#     out = ["digraph G {", f"  rankdir={rankdir};"]

#     for line in lines:
#         match = (
#             re.match(r"^(.*?)\s*-->\|(.*?)\|\s*(.*?)$", line)
#             or re.match(r"^(.*?)\s*-->\s*(.*?)$", line)
#             or re.match(r"^(.*?)\s*->\|(.*?)\|\s*(.*?)$", line)
#             or re.match(r"^(.*?)\s*->\s*(.*?)$", line)
#         )

#         if not match:
#             continue

#         if len(match.groups()) == 3:
#             left, edge_label, right = match.group(1), match.group(2), match.group(3)
#         else:
#             left, right, edge_label = match.group(1), match.group(2), None

#         edge = f'  "{dot_escape(left.strip().strip(chr(34)))}" -> "{dot_escape(right.strip().strip(chr(34)))}"'
#         if edge_label:
#             edge += f' [label="{dot_escape(edge_label)}"]'
#         out.append(edge + ";")

#     out.append("}")
#     return "\n".join(out)


# def normalize_to_graphviz_dot(text: Any) -> Optional[str]:
#     text = preprocess_diagram_text(text)
#     kind, body = classify_diagram_text(text)

#     if kind == "graphviz":
#         return _sanitize_graphviz_html_like_labels(strip_code_fence(body))

#     if kind == "mermaid_like":
#         dot = mermaid_like_to_dot(body)
#         return _sanitize_graphviz_html_like_labels(dot or "") if dot else None

#     return None


# def wrap_label(text: Any, width: int = 16) -> str:
#     words = str(text or "").replace("\\n", " ").replace("\n", " ").split()
#     lines: List[str] = []
#     current: List[str] = []
#     current_len = 0

#     for word in words:
#         if current and current_len + len(word) > width:
#             lines.append(" ".join(current))
#             current = [word]
#             current_len = len(word)
#         else:
#             current.append(word)
#             current_len += len(word) + 1

#     if current:
#         lines.append(" ".join(current))

#     return "\\n".join(lines)


# def normalize_edges(dot: str) -> str:
#     if re.search(r"^\s*digraph\b", dot, re.IGNORECASE):
#         return dot.replace("--", "->")

#     if re.search(r"^\s*graph\b", dot, re.IGNORECASE):
#         return dot.replace("->", "--")

#     return dot


# def force_graph_rankdir(dot: str) -> str:
#     if not dot:
#         return dot

#     target_rankdir = DIAGRAM_FORCE_RANKDIR or "LR"

#     if re.search(r"\brankdir\s*=", dot, flags=re.IGNORECASE):
#         return re.sub(
#             r"\brankdir\s*=\s*(LR|RL|TB|BT|TD)\s*;?",
#             f"rankdir={target_rankdir};",
#             dot,
#             flags=re.IGNORECASE,
#         )

#     return dot.replace("{", f"{{\n  rankdir={target_rankdir};", 1)


# def extract_label(inner: str, fallback: str) -> str:
#     match = re.search(r'label\s*=\s*"(.*?)"', inner or "", flags=re.DOTALL)
#     if match:
#         value = _decode_attr_value(match.group(1))
#         return value or fallback

#     match = re.search(r"label\s*=\s*(<<.*?>>|<.*?>)", inner or "", flags=re.DOTALL)
#     if match:
#         value = _decode_attr_value(match.group(1))
#         return value or fallback

#     return fallback


# def _cluster_style_lines() -> List[str]:
#     cluster_font_name = "Helvetica-Bold" if DIAGRAM_CLUSTER_LABEL_BOLD else "Helvetica"

#     return [
#         f'    style="{DIAGRAM_CLUSTER_STYLE}";',
#         f'    fillcolor="{DIAGRAM_CLUSTER_FILL_COLOR}";',
#         f'    color="{DIAGRAM_CLUSTER_BORDER_COLOR}";',
#         f'    fontcolor="{DIAGRAM_CLUSTER_FONT_COLOR}";',
#         f'    fontname="{cluster_font_name}";',
#         f"    fontsize={DIAGRAM_CLUSTER_FONT_SIZE};",
#         f"    penwidth={DIAGRAM_CLUSTER_PENWIDTH};",
#         f"    margin={DIAGRAM_CLUSTER_MARGIN};",
#     ]


# # ---------------------------------------------------------------------
# # Node styling
# # ---------------------------------------------------------------------
# def styled_node(node_ref: str, label: str, shape: str, use_image_cards: bool = True) -> str:
#     safe_node_ref = _quote_dot_id(node_ref)
#     label_clean = clean_label(label) or clean_label(node_ref)
#     style = get_style_for_label(label_clean)

#     if use_image_cards:
#         icon = resolve_icon_from_node_label(label_clean, PROJECT_ROOT)
#         normalized_icon = None

#         if icon:
#             try:
#                 normalized_icon = normalize_icon_for_graphviz(icon)
#                 logger.info("[ICON] Resolved icon for label=%r -> %s", label_clean, normalized_icon)
#             except Exception:
#                 logger.exception("[ICON] Failed normalizing icon for label=%r icon=%s", label_clean, icon)
#                 normalized_icon = None
#         else:
#             logger.warning("[ICON] No icon resolved for label=%r. Using colored text-only node card.", label_clean)

#         card = make_composite_node_card(
#             label=label_clean,
#             icon_path=normalized_icon,
#             fill=style["fill"],
#             border=style["border"],
#             font_color=style["font"],
#             target_size=DIAGRAM_NODE_CARD_SIZE,
#         )

#         if card:
#             safe_card = str(card).replace("\\", "/").replace('"', '\\"')
#             return (
#                 f'{safe_node_ref} ['
#                 f'shape=none,label="",image="{safe_card}",imagescale=true,fixedsize=true,'
#                 f'width={DIAGRAM_NODE_CARD_WIDTH_IN},height={DIAGRAM_NODE_CARD_HEIGHT_IN},margin=0];'
#             )

#     safe_shape = shape or "box"

#     return (
#         f'{safe_node_ref} ['
#         f'shape={safe_shape},style="rounded,filled",'
#         f'fillcolor="{style.get("fill", "#F8F9FA")}",'
#         f'color="{style.get("border", "#DADCE0")}",'
#         f'fontcolor="{style.get("font", "#202124")}",'
#         f'label="{dot_escape(wrap_label(label_clean, 18))}",'
#         f'fontsize={DIAGRAM_NODE_FONT_SIZE},fontname="Helvetica-Bold",'
#         f'penwidth={DIAGRAM_NODE_DEFAULT_PENWIDTH},margin="{DIAGRAM_NODE_DEFAULT_MARGIN}"];'
#     )


# # ---------------------------------------------------------------------
# # DOT normalization / rendering preparation
# # ---------------------------------------------------------------------
# def normalize_dot_for_graphviz(dot_text: str, use_image_cards: bool = True) -> Tuple[str, List[Tuple[str, str]]]:
#     dot = preprocess_diagram_text(strip_code_fence(dot_text))
#     dot = _strip_dot_line_comments_preserve_urls(dot)
#     dot = _sanitize_graphviz_html_like_labels(dot)
#     dot = force_graph_rankdir(dot)
#     dot = normalize_edges(dot)
#     dot = _sanitize_graphviz_html_like_labels(dot)

#     lines = _split_dot_statements(dot)

#     out: List[str] = []
#     legend: List[Tuple[str, str]] = []
#     fallback_legend: List[Tuple[str, str]] = []
#     isolated: set[str] = set()
#     labels: Dict[str, str] = {}
#     connected_nodes: set[str] = set()
#     cluster_member_nodes: set[str] = set()

#     edge_colors = ["#E60000", "#1D70B8", "#28A197", "#F47738", "#4C2C92", "#6F72AF"]
#     edge_index = 0

#     scan_cluster_depth = 0

#     for line in lines:
#         stripped = line.strip()

#         if re.match(r"^\s*subgraph\s+cluster", stripped, flags=re.IGNORECASE):
#             scan_cluster_depth += 1
#             continue

#         if stripped == "}":
#             scan_cluster_depth = max(0, scan_cluster_depth - 1)
#             continue

#         if _is_node_declaration(line):
#             prefix, inner, _ = split_attr(line)
#             name = _strip_port_suffix(_clean_dot_endpoint(prefix))
#             label = extract_label(inner, name)
#             labels[name] = label

#             if scan_cluster_depth > 0:
#                 cluster_member_nodes.add(name)

#             if is_isolated_node_name_or_label(name) or is_isolated_node_name_or_label(label):
#                 isolated.add(name)

#         if "->" in line or "--" in line:
#             _prefix, inner, _postfix = split_attr(line)
#             decision = _edge_policy_decision(inner)

#             if decision.keep:
#                 for endpoint in _extract_edge_endpoints(line):
#                     connected_nodes.add(endpoint)

#     root_graph_defaults_injected = False
#     cluster_depth = 0

#     for line in lines:
#         stripped = line.strip()
#         lower = stripped.lower()

#         if not stripped:
#             continue

#         if stripped.startswith(("digraph ", "graph ")):
#             out.append(line)
#             continue

#         if re.match(r"^\s*subgraph\s+cluster", stripped, flags=re.IGNORECASE):
#             out.append(re.sub(r"\bsubgraph\s+cluster_(?:cluster_)+", "subgraph cluster_", line))
#             cluster_depth += 1
#             continue

#         if stripped == "{":
#             if not root_graph_defaults_injected:
#                 root_graph_defaults_injected = True
#                 out.extend(
#                     [
#                         "{",
#                         "  graph [",
#                         '    bgcolor="white",',
#                         f'    splines="{DIAGRAM_GRAPH_SPLINES}",',
#                         f'    ratio="{DIAGRAM_GRAPH_RATIO}",',
#                         f"    concentrate={_graph_bool(bool(DIAGRAM_GRAPH_CONCENTRATE))},",
#                         f"    compound={_graph_bool(bool(DIAGRAM_GRAPH_COMPOUND))},",
#                         f"    dpi={DIAGRAM_GRAPH_DPI},",
#                         f"    overlap={_graph_bool(bool(DIAGRAM_GRAPH_OVERLAP))},",
#                         f'    outputorder="{DIAGRAM_GRAPH_OUTPUT_ORDER}",',
#                         '    fontname="Helvetica-Bold",',
#                         f"    fontsize={DIAGRAM_GRAPH_FONT_SIZE},",
#                         f"    ranksep={DIAGRAM_GRAPH_RANKSEP},",
#                         f"    nodesep={DIAGRAM_GRAPH_NODESEP},",
#                         f"    pad={DIAGRAM_GRAPH_PAD},",
#                         f"    newrank={_graph_bool(bool(DIAGRAM_GRAPH_NEWRANK))}",
#                         "  ];",
#                         "  node [",
#                         "    shape=box,",
#                         '    style="rounded,filled",',
#                         f'    fillcolor="{DIAGRAM_NODE_DEFAULT_FILL}",',
#                         f'    color="{DIAGRAM_NODE_DEFAULT_BORDER}",',
#                         '    fontname="Helvetica-Bold",',
#                         f"    fontsize={DIAGRAM_NODE_FONT_SIZE},",
#                         f'    margin="{DIAGRAM_NODE_DEFAULT_MARGIN}",',
#                         f"    penwidth={DIAGRAM_NODE_DEFAULT_PENWIDTH}",
#                         "  ];",
#                         "  edge [",
#                         '    fontname="Helvetica-Bold",',
#                         f"    fontsize={DIAGRAM_EDGE_FONT_SIZE},",
#                         f"    penwidth={DIAGRAM_EDGE_PENWIDTH},",
#                         f"    minlen={DIAGRAM_EDGE_MINLEN},",
#                         f"    arrowsize={DIAGRAM_EDGE_ARROWSIZE},",
#                         "    constraint=true,",
#                         "    weight=10,",
#                         '    color="#5F6368"',
#                         "  ];",
#                     ]
#                 )
#             else:
#                 out.append("{")
#                 out.extend(_cluster_style_lines())
#             continue

#         if stripped == "}":
#             out.append(line)
#             if cluster_depth > 0:
#                 cluster_depth -= 1
#             continue

#         if lower.startswith(("node ", "edge ", "graph ")):
#             continue

#         if lower.startswith(
#             (
#                 "style=",
#                 "fillcolor=",
#                 "fontcolor=",
#                 "fontname=",
#                 "fontsize=",
#                 "penwidth=",
#                 "margin=",
#                 "labelloc=",
#                 "labeljust=",
#             )
#         ):
#             continue

#         if lower.startswith("color="):
#             continue

#         if lower.startswith("label="):
#             if cluster_depth > 0:
#                 out.append(_sanitize_graphviz_html_like_labels(line))
#             continue

#         if "->" in stripped or "--" in stripped:
#             endpoints = _extract_edge_endpoints(line)

#             if any(part in isolated or is_isolated_node_name_or_label(labels.get(part, "")) for part in endpoints):
#                 continue

#             prefix, inner, postfix = split_attr(line)
#             decision = _edge_policy_decision(inner)

#             if not decision.keep:
#                 logger.info(
#                     "Dropping non-flow/control diagram edge before render. endpoints=%s reason=%s line=%s",
#                     endpoints,
#                     decision.reason,
#                     stripped,
#                 )
#                 continue

#             label_match = re.search(r"(xlabel|label)\s*=\s*\"(.*?)\"", inner, flags=re.DOTALL)
#             edge_label = label_match.group(2).strip() if label_match and label_match.group(2).strip() else ""

#             color = edge_colors[edge_index % len(edge_colors)]
#             edge_index += 1

#             if decision.include_in_legend:
#                 if edge_label:
#                     legend.append((color, edge_label))
#                 else:
#                     fallback_label = _make_fallback_flow_label(endpoints=endpoints, labels=labels)
#                     if fallback_label:
#                         fallback_legend.append((color, fallback_label))

#             merged_attrs = _merge_edge_attributes(inner=inner, color=color)

#             if "[" in line:
#                 safe_edge_prefix = _normalize_edge_prefix(prefix)
#                 safe_postfix = postfix
#                 if not safe_postfix.strip().endswith(";"):
#                     safe_postfix = safe_postfix.rstrip() + ";"
#                 out.append(f"{safe_edge_prefix} [{merged_attrs}]{safe_postfix}")
#             else:
#                 safe_edge_prefix = _normalize_edge_prefix(line.rstrip(";"))
#                 out.append(f"{safe_edge_prefix} [{merged_attrs}];")

#             continue

#         if _is_node_declaration(line):
#             prefix, inner, _ = split_attr(line)
#             raw_node_name = _strip_port_suffix(_clean_dot_endpoint(prefix))
#             node_label = extract_label(inner, raw_node_name)
#             preserve_cluster_member = raw_node_name in cluster_member_nodes

#             if (
#                 DIAGRAM_SKIP_UNCONNECTED_NODES
#                 and connected_nodes
#                 and raw_node_name not in connected_nodes
#                 and not preserve_cluster_member
#             ):
#                 logger.info("Skipping unconnected diagram node. node=%s label=%s", raw_node_name, node_label)
#                 continue

#             if raw_node_name in isolated or is_isolated_node_name_or_label(node_label):
#                 logger.info("Skipping isolated diagram node. node=%s label=%s", raw_node_name, node_label)
#                 continue

#             shape_match = re.search(r"shape\s*=\s*[\"']?(\w+)", inner)
#             shape = shape_match.group(1) if shape_match else "box"

#             out.append(styled_node(raw_node_name, node_label, shape, use_image_cards=use_image_cards))
#             continue

#         if _is_bare_node_statement(line):
#             raw_node_name = _strip_port_suffix(_clean_dot_endpoint(line))
#             node_label = clean_label(raw_node_name)

#             if DIAGRAM_SKIP_UNCONNECTED_NODES and connected_nodes and raw_node_name not in connected_nodes:
#                 logger.info("Skipping unconnected bare diagram node. node=%s", raw_node_name)
#                 continue

#             if is_isolated_node_name_or_label(raw_node_name):
#                 logger.info("Skipping isolated bare diagram node. node=%s", raw_node_name)
#                 continue

#             out.append(styled_node(raw_node_name, node_label, "box", use_image_cards=use_image_cards))
#             continue

#         out.append(line)

#     final_dot = normalize_edges("\n".join(out))
#     final_dot = preprocess_diagram_text(final_dot)
#     final_dot = _sanitize_graphviz_html_like_labels(final_dot)
#     final_dot = _remove_orphan_cluster_labels_and_extra_braces(final_dot)
#     final_dot = _validate_dot_brace_balance(final_dot, context="normalize_dot_for_graphviz")

#     final_legend = _dedupe_legend_items(legend if legend else fallback_legend)

#     return final_dot, final_legend


# # ---------------------------------------------------------------------
# # Legend rendering - aligned HTML table legend
# # ---------------------------------------------------------------------
# def build_legend_dot(items: List[Tuple[str, str]]) -> str:
#     deduped = _dedupe_legend_items(items or [])

#     if not deduped:
#         return ""

#     rows: List[str] = []

#     rows.append(
#         f'<TR><TD COLSPAN="2" ALIGN="CENTER" BGCOLOR="{_safe_hex_color(DIAGRAM_LEGEND_FILL_COLOR, "#F8FAFC")}">'
#         f'<FONT POINT-SIZE="{DIAGRAM_LEGEND_TITLE_FONT_SIZE}" COLOR="{_safe_hex_color(DIAGRAM_LEGEND_TITLE_COLOR, "#202124")}">'
#         f"<B>{_html_escape_text(DIAGRAM_LEGEND_HEADING_LABEL)}</B></FONT></TD></TR>"
#     )

#     for color, label in deduped:
#         safe_color = _safe_hex_color(color)
#         safe_label = _html_escape_text(str(label).replace("\n", " ").strip())

#         rows.append(
#             "<TR>"
#             f'<TD ALIGN="CENTER" WIDTH="70"><FONT POINT-SIZE="{DIAGRAM_LEGEND_ITEM_FONT_SIZE}" COLOR="{safe_color}">━━▶</FONT></TD>'
#             f'<TD ALIGN="LEFT" BALIGN="LEFT" BGCOLOR="{_safe_hex_color(DIAGRAM_LEGEND_ITEM_FILL_COLOR, "#FFFFFF")}">'
#             f'<FONT POINT-SIZE="{DIAGRAM_LEGEND_ITEM_FONT_SIZE}" COLOR="{_safe_hex_color(DIAGRAM_LEGEND_ITEM_FONT_COLOR, "#202124")}">{safe_label}</FONT>'
#             "</TD>"
#             "</TR>"
#         )

#     table_label = (
#         '<<TABLE BORDER="1" CELLBORDER="1" CELLSPACING="0" CELLPADDING="8" '
#         f'COLOR="{_safe_hex_color(DIAGRAM_LEGEND_BORDER_COLOR, "#8A8F98")}">'
#         + "".join(rows)
#         + "</TABLE>>"
#     )

#     return "\n".join(
#         [
#             "digraph Legend {",
#             "  rankdir=TB;",
#             "  graph [",
#             '    bgcolor="white",',
#             f"    pad={DIAGRAM_LEGEND_PAD},",
#             f"    nodesep={DIAGRAM_LEGEND_NODESEP},",
#             f"    ranksep={DIAGRAM_LEGEND_RANKSEP},",
#             '    fontname="Helvetica-Bold"',
#             "  ];",
#             "  node [shape=plain, margin=0];",
#             f"  legend_table [label={table_label}];",
#             "}",
#         ]
#     )


# def render_legend_diagram(items: List[Tuple[str, str]]) -> Optional[str]:
#     dot = build_legend_dot(items)

#     if not dot:
#         return None

#     try:
#         path = graphviz.Source(dot, format="png").render(
#             filename="legend",
#             directory=tempfile.mkdtemp(),
#             cleanup=True,
#         )
#         return trim_png_whitespace(path) if Path(path).exists() else None

#     except Exception:
#         debug_path = write_graphviz_debug_file(dot, prefix="aia_graphviz_legend_failed")
#         logger.exception("Legend rendering failed. Debug DOT: %s", debug_path)
#         return None


# # ---------------------------------------------------------------------
# # Public render functions
# # ---------------------------------------------------------------------
# def render_graphviz_to_png(text: str) -> Optional[Tuple[str, List[Tuple[str, str]]]]:
#     dot = normalize_to_graphviz_dot(text)

#     if not dot:
#         return None

#     safe_dot, legend = normalize_dot_for_graphviz(
#         dot,
#         use_image_cards=DIAGRAM_USE_IMAGE_CARDS_FOR_PNG,
#     )

#     safe_dot = _sanitize_graphviz_html_like_labels(safe_dot)
#     safe_dot = _remove_orphan_cluster_labels_and_extra_braces(safe_dot)
#     safe_dot = _validate_dot_brace_balance(safe_dot, context="render_graphviz_to_png")

#     logger.info("Icon files found under ICON_DIR: %s", len(list(iter_icon_files())))

#     try:
#         path = graphviz.Source(safe_dot, format="png").render(
#             filename="diagram",
#             directory=tempfile.mkdtemp(),
#             cleanup=True,
#         )

#         if Path(path).exists():
#             return trim_png_whitespace(path), legend

#         logger.error("Graphviz PNG render completed but output file was not found: %s", path)
#         return None

#     except Exception:
#         debug_dot = _sanitize_graphviz_html_like_labels(safe_dot)
#         debug_dot = _remove_orphan_cluster_labels_and_extra_braces(debug_dot)
#         debug_dot = _validate_dot_brace_balance(debug_dot, context="render_graphviz_to_png_debug")

#         debug_path = write_graphviz_debug_file(debug_dot, prefix="aia_graphviz_failed")
#         logger.exception("Graphviz render failed. Debug DOT: %s", debug_path)
#         return None


# def render_graphviz_to_assets(
#     text: str,
#     output_dir: str | Path,
#     base_name: str = "diagram",
# ) -> Optional[Dict[str, Any]]:
#     dot = normalize_to_graphviz_dot(text)

#     if not dot:
#         logger.warning("No Graphviz-compatible DOT generated from input text.")
#         return None

#     output_dir = Path(output_dir)
#     output_dir.mkdir(parents=True, exist_ok=True)

#     safe_base = (
#         re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(base_name or "diagram"))
#         .strip("._")
#         .lower()
#         or "diagram"
#     )

#     try:
#         png_dot, legend = normalize_dot_for_graphviz(
#             dot,
#             use_image_cards=DIAGRAM_USE_IMAGE_CARDS_FOR_PNG,
#         )

#         editable_dot, editable_legend = normalize_dot_for_graphviz(
#             dot,
#             use_image_cards=DIAGRAM_USE_IMAGE_CARDS_FOR_EDITABLE_SVG,
#         )

#         png_dot = _sanitize_graphviz_html_like_labels(png_dot)
#         editable_dot = _sanitize_graphviz_html_like_labels(editable_dot)

#         png_dot = _remove_orphan_cluster_labels_and_extra_braces(png_dot)
#         editable_dot = _remove_orphan_cluster_labels_and_extra_braces(editable_dot)

#         png_dot = _validate_dot_brace_balance(png_dot, context=f"{safe_base}.png_dot")
#         editable_dot = _validate_dot_brace_balance(editable_dot, context=f"{safe_base}.editable_dot")

#         final_legend = legend or editable_legend

#         dot_path = output_dir / f"{safe_base}.dot"
#         editable_dot_path = output_dir / f"{safe_base}_editable.dot"

#         dot_path.write_text(png_dot, encoding="utf-8")
#         editable_dot_path.write_text(editable_dot, encoding="utf-8")

#         png_path = graphviz.Source(png_dot, format="png").render(
#             filename=safe_base,
#             directory=str(output_dir),
#             cleanup=True,
#         )

#         if Path(png_path).exists():
#             png_path = trim_png_whitespace(png_path)

#         editable_svg_path = graphviz.Source(editable_dot, format="svg").render(
#             filename=f"{safe_base}_editable",
#             directory=str(output_dir),
#             cleanup=True,
#         )

#         if not Path(png_path).exists():
#             logger.error("PNG diagram asset was not generated: %s", png_path)
#             return None

#         if not Path(editable_svg_path).exists():
#             logger.warning("Editable SVG diagram asset was not generated: %s", editable_svg_path)

#         editable_svg = str(editable_svg_path) if Path(editable_svg_path).exists() else None

#         return {
#             "png_path": str(png_path),
#             "svg_path": editable_svg,
#             "editable_svg_path": editable_svg,
#             "dot_path": str(dot_path),
#             "editable_dot_path": str(editable_dot_path),
#             "legend": final_legend,
#         }

#     except Exception:
#         debug_source = locals().get("editable_dot") or locals().get("png_dot") or dot

#         debug_source = _sanitize_graphviz_html_like_labels(debug_source)
#         debug_source = _remove_orphan_cluster_labels_and_extra_braces(debug_source)
#         debug_source = _validate_dot_brace_balance(debug_source, context=f"{safe_base}.debug_dot")

#         debug_path = write_graphviz_debug_file(
#             debug_source,
#             prefix="aia_graphviz_asset_failed",
#         )

#         logger.exception("Graphviz asset rendering failed. Debug DOT: %s", debug_path)
#         return None


# def inline_image_token(path: Optional[str]) -> str:
#     if not path:
#         return "N/A"

#     return "IMAGE_TOKEN_START" + Path(path).resolve().as_posix() + "IMAGE_TOKEN_END"