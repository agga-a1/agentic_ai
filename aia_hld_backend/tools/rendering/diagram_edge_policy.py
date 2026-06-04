
from __future__ import annotations

"""
Generic, policy-driven DOT edge sanitizer for AIA HLD diagrams.

Purpose
-------
Clean non-primary/control/annotation edges before Graphviz renders PNG/SVG/PDF
and before legend generation, without hardcoding cloud/service-specific names.

Design
------
- No service-specific names such as GCS, KMS, VPCSC, Vault, Teradata, Collibra.
- Uses generic DOT attributes first: edge_type/type/category/purpose/flow/render/legend.
- Uses configurable semantic label patterns only as fallback.
- Supports external JSON config, so rules can be changed without code changes.

Recommended DOT attributes from Architect/Diagram agents
-------------------------------------------------------
Primary runtime/data flow:
    A -> B [label="Send encrypted file", edge_type="data_flow"];

Control/security/annotation edge that should not render as arrow:
    A -> B [label="Security", edge_type="control", render="false", legend="false"];

Edge visible in diagram but excluded from legend:
    A -> B [label="Access key", edge_type="support", legend="false"];
"""

import html
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EdgeDecision:
    keep: bool
    include_in_legend: bool
    reason: str = ""


@dataclass
class DiagramEdgePolicy:
    """
    Policy config for DOT edge cleanup.

    This is intentionally generic. It does not know about any specific cloud,
    tool, platform, product, or project service names.
    """

    # Attribute names checked to determine edge role/category.
    type_attribute_names: Tuple[str, ...] = (
        "edge_type",
        "type",
        "category",
        "purpose",
        "relationship",
        "flow_type",
    )

    # Values treated as primary flow and preserved.
    primary_flow_types: Tuple[str, ...] = (
        "data",
        "data_flow",
        "process",
        "process_flow",
        "runtime",
        "runtime_flow",
        "integration",
        "application_flow",
        "request",
        "response",
        "event",
        "message",
        "file_transfer",
        "dependency",
        "support",
        "key_access",
    )

    # Values treated as non-flow/control/annotation and removed from rendered arrows.
    non_render_edge_types: Tuple[str, ...] = (
        "control",
        "control_flow",
        "security",
        "governance",
        "policy",
        "boundary",
        "perimeter",
        "annotation",
        "note",
        "legend",
        "observability",
        "monitoring",
        "logging",
        "audit",
        "compliance",
        "guardrail",
    )

    # Generic label patterns. These are not service-specific; override via JSON if needed.
    non_flow_label_patterns: Tuple[str, ...] = (
        r"\bsecurity\b",
        r"\bgovernance\b",
        r"\bpolicy\b",
        r"\bpolicies\b",
        r"\bcontrol\b",
        r"\bcontrols\b",
        r"\bboundary\b",
        r"\bperimeter\b",
        r"\bcompliance\b",
        r"\bguardrail\b",
        r"\bguardrails\b",
        r"\baudit\b",
        r"\blogging\b",
        r"\bmonitoring\b",
        r"\bmetrics\b",
        r"\balerts?\b",
        r"\bobservability\b",
    )

    # Boolean-like attributes.
    render_attribute_names: Tuple[str, ...] = ("render", "show", "visible", "include")
    legend_attribute_names: Tuple[str, ...] = ("legend", "legend_include", "show_in_legend")
    flow_attribute_names: Tuple[str, ...] = ("flow", "is_flow", "primary_flow")

    # If true, label fallback patterns can remove edges without explicit edge_type.
    enable_label_fallback: bool = True

    # If true, any edge explicitly marked as primary flow is kept even if style is dashed.
    explicit_flow_wins: bool = True

    # If true, dashed/dotted edges are NOT automatically removed. They are removed only
    # when their type/label indicates non-flow. This avoids breaking valid async flows.
    dashed_edges_are_allowed: bool = True

    # If true, keep node definitions exactly as they are. This sanitizer removes only edges.
    preserve_nodes: bool = True

    @classmethod
    def from_json_file(cls, path: str | Path) -> "DiagramEdgePolicy":
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiagramEdgePolicy":
        allowed = set(cls.__dataclass_fields__.keys())  # type: ignore[attr-defined]
        kwargs: Dict[str, Any] = {}
        for key, value in (data or {}).items():
            if key not in allowed:
                continue
            if isinstance(value, list):
                kwargs[key] = tuple(str(v) for v in value)
            else:
                kwargs[key] = value
        return cls(**kwargs)


def sanitize_dot_for_rendering(
    dot_text: str,
    *,
    policy: Optional[DiagramEdgePolicy] = None,
    policy_path: Optional[str | Path] = None,
) -> str:
    """
    Remove non-renderable/control/annotation edges before Graphviz renders images/PDF.

    Call this just before writing DOT to disk or before graphviz.Source(dot_text).
    """
    if not dot_text:
        return dot_text

    active_policy = _resolve_policy(policy, policy_path)
    output_lines: List[str] = []
    removed_count = 0

    for raw_line in dot_text.splitlines():
        parsed = parse_dot_edge_line(raw_line)
        if not parsed:
            output_lines.append(raw_line)
            continue

        src, tgt, attrs = parsed
        decision = decide_edge(src, tgt, attrs, active_policy)
        if not decision.keep:
            removed_count += 1
            logger.info(
                "[DIAGRAM_EDGE_POLICY] Dropping non-flow edge before render: %s -> %s label=%r reason=%s attrs=%s",
                src,
                tgt,
                attrs.get("label", ""),
                decision.reason,
                attrs,
            )
            continue

        output_lines.append(raw_line)

    if removed_count:
        logger.info("[DIAGRAM_EDGE_POLICY] Removed %s non-flow edge(s) before Graphviz render", removed_count)

    suffix = "\n" if dot_text.endswith("\n") else ""
    return "\n".join(output_lines) + suffix


def should_include_edge_in_legend(
    src: str,
    tgt: str,
    attrs: Dict[str, str],
    *,
    policy: Optional[DiagramEdgePolicy] = None,
    policy_path: Optional[str | Path] = None,
) -> bool:
    """
    Return whether an edge should appear in the flow legend.

    Use this if your legend generation reads edges independently from rendered DOT.
    """
    active_policy = _resolve_policy(policy, policy_path)
    return decide_edge(src, tgt, attrs, active_policy).include_in_legend


def decide_edge(src: str, tgt: str, attrs: Dict[str, str], policy: DiagramEdgePolicy) -> EdgeDecision:
    attrs_norm = _normalize_attrs(attrs)
    label = attrs_norm.get("label", "")

    # Explicit render flags have highest priority.
    explicit_render = _first_bool_attr(attrs_norm, policy.render_attribute_names)
    if explicit_render is False:
        return EdgeDecision(False, False, "explicit_render_false")

    explicit_legend = _first_bool_attr(attrs_norm, policy.legend_attribute_names)
    explicit_flow = _first_bool_attr(attrs_norm, policy.flow_attribute_names)

    edge_type = _first_text_attr(attrs_norm, policy.type_attribute_names)
    edge_type_norm = _normalize_token(edge_type)

    primary_types = {_normalize_token(x) for x in policy.primary_flow_types}
    non_render_types = {_normalize_token(x) for x in policy.non_render_edge_types}

    if explicit_flow is True and policy.explicit_flow_wins:
        return EdgeDecision(True, explicit_legend is not False, "explicit_flow_true")

    if edge_type_norm in primary_types:
        return EdgeDecision(True, explicit_legend is not False, f"primary_type:{edge_type_norm}")

    if edge_type_norm in non_render_types:
        return EdgeDecision(False, False, f"non_render_type:{edge_type_norm}")

    # Explicit render=true keeps edge unless legend=false excludes legend only.
    if explicit_render is True:
        return EdgeDecision(True, explicit_legend is not False, "explicit_render_true")

    # Generic label fallback. No service names here.
    if policy.enable_label_fallback and _matches_any(label, policy.non_flow_label_patterns):
        return EdgeDecision(False, False, "non_flow_label_pattern")

    # If legend=false, keep diagram edge but exclude from legend.
    if explicit_legend is False:
        return EdgeDecision(True, False, "explicit_legend_false")

    return EdgeDecision(True, True, "default_keep")


def parse_dot_edge_line(line: str) -> Optional[Tuple[str, str, Dict[str, str]]]:
    """
    Parse one simple directed DOT edge line.

    Supports:
        a -> b;
        "a" -> "b" [label="Data Flow", edge_type="data_flow"];

    Non-edge lines return None.
    """
    text = str(line or "").strip()
    if not text or text.startswith("//") or text.startswith("#") or "->" not in text:
        return None

    # Avoid parsing graph-level definitions that happen to contain arrows inside labels.
    text = text.rstrip(";").strip()

    match = re.match(
        r'^("(?:\\.|[^"])+"|[A-Za-z0-9_\.\-]+)\s*->\s*("(?:\\.|[^"])+"|[A-Za-z0-9_\.\-]+)\s*(?:\[(.*?)\])?$',
        text,
    )
    if not match:
        return None

    src = _decode_dot_id(match.group(1))
    tgt = _decode_dot_id(match.group(2))
    attrs = parse_dot_attrs(match.group(3) or "")
    return src, tgt, attrs


def parse_dot_attrs(raw: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    if not raw:
        return attrs

    for key, value in re.findall(r'(\w+)\s*=\s*("(?:\\.|[^"])*"|[^,\]]+)', raw):
        attrs[key.lower()] = _decode_dot_value(value)
    return attrs


def build_policy_json_template() -> str:
    """Return a JSON template users can save as diagram_edge_policy.json."""
    template = DiagramEdgePolicy()
    data = {
        "type_attribute_names": list(template.type_attribute_names),
        "primary_flow_types": list(template.primary_flow_types),
        "non_render_edge_types": list(template.non_render_edge_types),
        "non_flow_label_patterns": list(template.non_flow_label_patterns),
        "render_attribute_names": list(template.render_attribute_names),
        "legend_attribute_names": list(template.legend_attribute_names),
        "flow_attribute_names": list(template.flow_attribute_names),
        "enable_label_fallback": template.enable_label_fallback,
        "explicit_flow_wins": template.explicit_flow_wins,
        "dashed_edges_are_allowed": template.dashed_edges_are_allowed,
        "preserve_nodes": template.preserve_nodes,
    }
    return json.dumps(data, indent=2)


def _resolve_policy(policy: Optional[DiagramEdgePolicy], policy_path: Optional[str | Path]) -> DiagramEdgePolicy:
    if policy is not None:
        return policy
    if policy_path:
        p = Path(policy_path)
        if p.exists():
            return DiagramEdgePolicy.from_json_file(p)
        logger.warning("[DIAGRAM_EDGE_POLICY] policy_path does not exist, using defaults: %s", p)
    return DiagramEdgePolicy()


def _normalize_attrs(attrs: Dict[str, str]) -> Dict[str, str]:
    return {str(k or "").strip().lower(): str(v or "").strip() for k, v in (attrs or {}).items()}


def _first_text_attr(attrs: Dict[str, str], names: Sequence[str]) -> str:
    for name in names:
        val = attrs.get(str(name).lower())
        if val:
            return val
    return ""


def _first_bool_attr(attrs: Dict[str, str], names: Sequence[str]) -> Optional[bool]:
    for name in names:
        key = str(name).lower()
        if key not in attrs:
            continue
        parsed = _parse_bool(attrs.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_bool(value: Any) -> Optional[bool]:
    text = str(value or "").strip().lower()
    if text in {"true", "yes", "y", "1", "on"}:
        return True
    if text in {"false", "no", "n", "0", "off"}:
        return False
    return None


def _normalize_token(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _matches_any(text: str, patterns: Iterable[str]) -> bool:
    source = str(text or "").strip().lower()
    if not source:
        return False
    for pattern in patterns:
        try:
            if re.search(pattern, source, flags=re.IGNORECASE):
                return True
        except re.error:
            logger.warning("[DIAGRAM_EDGE_POLICY] Invalid regex ignored: %s", pattern)
    return False


def _decode_dot_id(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return html.unescape(text).replace('\\"', '"').strip()


def _decode_dot_value(value: str) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == '"' and text[-1] == '"':
        text = text[1:-1]
    return html.unescape(text).replace("\\n", "\n").replace('\\"', '"').strip()
