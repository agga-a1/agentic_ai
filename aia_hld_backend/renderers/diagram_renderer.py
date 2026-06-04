import re
import tempfile
import logging
from typing import Optional, Tuple, Dict, List
from graphviz import Digraph

logger = logging.getLogger(__name__)

# ============================================================
# UTILS
# ============================================================

def normalize_mermaid(text: str) -> str:
    """Normalize HTML-escaped Mermaid syntax."""
    return (
        text.replace("&gt;", ">")
            .replace("&lt;", "<")
            .replace("&amp;", "&")
    )

# ============================================================
# MERMAID PARSING (ENHANCED)
# ============================================================

def extract_node(node_str: str) -> Tuple[str, str]:
    """Extracts the Node ID and Label, handling (), [], {}, and (())."""
    node_str = node_str.strip()
    # Matches patterns like: NodeID[Label] or NodeID(Label)
    m = re.match(r'^([a-zA-Z0-9_-]+)\s*([\[\(\{]+.*?[\]\)\}]+)?$', node_str)
    
    if m:
        node_id = m.group(1)
        label = m.group(2)
        if label:
            # Strip the outer brackets and any quotes
            clean_label = label.strip('[](){} "')
            return node_id, clean_label
        return node_id, node_id
        
    return node_str, node_str

def parse_mermaid(mermaid_text: str) -> Tuple[Dict[str, str], List[Dict], List[Dict]]:
    """
    Parse basic Mermaid flowchart syntax into nodes, edges, and subgraphs.
    """
    mermaid_text = normalize_mermaid(mermaid_text)

    nodes: Dict[str, str] = {}
    edges: List[Dict] = []
    subgraphs: List[Dict] = []

    current_subgraph = None

    for raw_line in mermaid_text.splitlines():
        line = raw_line.strip()

        if not line or line.startswith("graph") or line.startswith("direction"):
            continue

        # Subgraph start
        if line.startswith("subgraph"):
            label = line.replace("subgraph", "").strip() or "Subgraph"
            current_subgraph = {
                "name": f"cluster_{len(subgraphs)}",
                "label": label,
                "nodes": {},
                "edges": [],
            }
            subgraphs.append(current_subgraph)
            continue

        # Subgraph end
        if line == "end":
            current_subgraph = None
            continue

        # Edge Matcher: Supports A --> B, A -- label --> B, A -->|label| B, A --- B
        match = re.search(r'^(.*?)(--\s*(.*?)\s*-->|-->\|(.*?)\||-->|---)(.*)$', line)
        if not match:
            continue

        src_raw = match.group(1).strip()
        # Capture the label regardless of which arrow syntax was used
        label = (match.group(3) or match.group(4) or "").strip()
        dst_raw = match.group(5).strip()

        src_id, src_label = extract_node(src_raw)
        dst_id, dst_label = extract_node(dst_raw)

        target_nodes = current_subgraph["nodes"] if current_subgraph else nodes
        target_nodes[src_id] = src_label
        target_nodes[dst_id] = dst_label

        edge = {"from": src_id, "to": dst_id, "label": label}
        (current_subgraph["edges"] if current_subgraph else edges).append(edge)

    return nodes, edges, subgraphs

# ============================================================
# MERMAID → GRAPHVIZ → PNG
# ============================================================

def render_mermaid_to_png(mermaid_text: str) -> Optional[str]:
    """
    Render Mermaid flowchart text into a PNG image using Graphviz.
    Returns path to generated PNG file or None on failure.
    """
    try:
        nodes, edges, subgraphs = parse_mermaid(mermaid_text)

        if not nodes and not subgraphs:
            logger.warning("No nodes detected in Mermaid diagram")
            return None

        dot = Digraph(format="png")
        dot.attr(rankdir="TB", dpi="300")  # Top-down, High-Res

        # Root nodes
        for node_id, label in nodes.items():
            dot.node(node_id, label, shape="box", style="rounded", fontname="Helvetica")

        for e in edges:
            dot.edge(e["from"], e["to"], label=e["label"], fontname="Helvetica", fontsize="10")

        # Subgraphs
        for sg in subgraphs:
            with dot.subgraph(name=sg["name"]) as sub:
                sub.attr(label=sg["label"], fontname="Helvetica-Bold", style="dashed")
                for nid, lbl in sg["nodes"].items():
                    sub.node(nid, lbl, shape="box", style="rounded", fontname="Helvetica")
                for e in sg["edges"]:
                    sub.edge(e["from"], e["to"], label=e["label"], fontname="Helvetica", fontsize="10")

        tmp_dir = tempfile.mkdtemp()
        output_path = dot.render(directory=tmp_dir, cleanup=True)

        logger.info("Mermaid diagram successfully rendered to %s", output_path)
        return output_path

    except Exception as e:
        logger.exception("Failed to render Mermaid diagram", exc_info=e)
        return None