# from __future__ import annotations

# import logging
# from typing import Any, Dict, List, Optional, get_args, get_origin, Union
# import types

# from google.adk.tools import FunctionTool
# from pydantic import TypeAdapter

# from schema_types.hld_schema import HLDReport, DesignViewsSection
# from agent.workflow.keys import KEY_HLD_SECTION_STATE_PREFIX


# logger = logging.getLogger("HLDSectionCommitTools")


# # ============================================================
# # HELPERS
# # ============================================================
# def _resolve_state(tool_context: Any) -> Optional[Dict[str, Any]]:
#     if tool_context is None:
#         return None

#     if hasattr(tool_context, "state") and isinstance(tool_context.state, dict):
#         return tool_context.state

#     session = getattr(tool_context, "session", None)
#     if session is not None and hasattr(session, "state") and isinstance(session.state, dict):
#         return session.state

#     return None


# def _resolve_all_state_targets(tool_context: Any) -> List[Dict[str, Any]]:
#     targets: List[Dict[str, Any]] = []

#     if tool_context is None:
#         return targets

#     direct_state = getattr(tool_context, "state", None)
#     if isinstance(direct_state, dict):
#         targets.append(direct_state)

#     session = getattr(tool_context, "session", None)
#     session_state = getattr(session, "state", None) if session is not None else None
#     if isinstance(session_state, dict):
#         if not any(id(t) == id(session_state) for t in targets):
#             targets.append(session_state)

#     return targets


# def _apply_state_delta(tool_context: Any, state_delta: Dict[str, Any]) -> None:
#     if not isinstance(state_delta, dict) or not state_delta:
#         return

#     for target in _resolve_all_state_targets(tool_context):
#         try:
#             target.update(state_delta)
#         except Exception:
#             logger.exception("[HLD_TOOLS] Failed to apply state_delta.")


# def _dump_value(value: Any) -> Any:
#     if value is None:
#         return None

#     if hasattr(value, "model_dump") and callable(value.model_dump):
#         return value.model_dump()

#     if hasattr(value, "dict") and callable(value.dict):
#         return value.dict()

#     if isinstance(value, list):
#         return [_dump_value(v) for v in value]

#     if isinstance(value, dict):
#         return {k: _dump_value(v) for k, v in value.items()}

#     return value


# def _state_key_for_field(field_name: str) -> str:
#     return f"{KEY_HLD_SECTION_STATE_PREFIX}{field_name}"


# # ============================================================
# # NEW: VALIDATION NORMALIZATION HELPERS
# # ============================================================
# def _unwrap_optional_annotation(annotation: Any) -> Any:
#     """
#     Unwrap Optional[T] / T | None style annotations to T when possible.
#     """
#     current = annotation

#     while True:
#         origin = get_origin(current)
#         if origin not in (Union, types.UnionType):
#             return current

#         args = [a for a in get_args(current) if a is not type(None)]
#         if len(args) == 1:
#             current = args[0]
#             continue

#         return current


# def _is_permissive_dict_annotation(annotation: Any) -> bool:
#     """
#     True only for generic dict-like annotations that are effectively:
#     - dict
#     - Dict
#     - dict[str, Any]
#     - Dict[str, Any]

#     We keep this intentionally narrow so we do NOT mutate strict schema models.
#     """
#     ann = _unwrap_optional_annotation(annotation)
#     origin = get_origin(ann)

#     if origin not in (dict, Dict):
#         return False

#     args = get_args(ann)
#     if not args:
#         return True

#     if len(args) != 2:
#         return False

#     key_type, value_type = args
#     key_ok = key_type in (str, Any)
#     value_ok = value_type is Any or value_type == Any
#     return key_ok and value_ok


# def _is_list_of_permissive_dicts(annotation: Any) -> bool:
#     """
#     True only for annotations effectively shaped like:
#     - list[dict[str, Any]]
#     - List[Dict[str, Any]]
#     - Optional[list[dict[str, Any]]]
#     """
#     ann = _unwrap_optional_annotation(annotation)
#     origin = get_origin(ann)

#     if origin not in (list, List):
#         return False

#     args = get_args(ann)
#     if len(args) != 1:
#         return False

#     inner = args[0]
#     return _is_permissive_dict_annotation(inner)


# def _coerce_record_item(item: Any) -> Dict[str, Any]:
#     """
#     Convert a non-dict item into a minimal dict record.
#     This is ONLY used for permissive list[dict[str, Any]] fields.
#     """
#     if isinstance(item, dict):
#         return item

#     if hasattr(item, "model_dump") and callable(item.model_dump):
#         dumped = item.model_dump()
#         if isinstance(dumped, dict):
#             return dumped
#         return {"value": dumped}

#     if hasattr(item, "dict") and callable(item.dict):
#         dumped = item.dict()
#         if isinstance(dumped, dict):
#             return dumped
#         return {"value": dumped}

#     if isinstance(item, str):
#         return {"description": item}

#     if item is None:
#         return {"description": ""}

#     if isinstance(item, list):
#         return {"items": _dump_value(item)}

#     return {"value": _dump_value(item)}


# def _normalize_value_for_annotation(annotation: Any, value: Any) -> Any:
#     """
#     Defensive normalization ONLY for permissive object-list fields.

#     Example:
#       annotation = list[dict[str, Any]]
#       value      = ["a", "b"]

#     becomes:
#       [{"description": "a"}, {"description": "b"}]
#     """
#     if value is None:
#         return value

#     if _is_list_of_permissive_dicts(annotation) and isinstance(value, list):
#         if not all(isinstance(v, dict) for v in value):
#             logger.warning(
#                 "[HLD_TOOLS] Coercing non-dict list items into dict records for permissive annotation %s",
#                 annotation,
#             )
#             return [_coerce_record_item(v) for v in value]

#     return value


# def _validate_payload(annotation: Any, value: Any) -> Any:
#     normalized_value = _normalize_value_for_annotation(annotation, value)
#     adapter = TypeAdapter(annotation)
#     return adapter.validate_python(normalized_value)


# def _is_effectively_empty(value: Any) -> bool:
#     if value is None:
#         return True
#     if isinstance(value, str):
#         return not value.strip()
#     if isinstance(value, list):
#         return len(value) == 0
#     if isinstance(value, dict):
#         return len(value) == 0
#     return False


# # ============================================================
# # DESIGN VIEWS MERGE HELPER (NEW)
# # ============================================================
# def _merge_design_view(
#     previous: Optional[Dict[str, Any]],
#     view_key: str,
#     view_value: Dict[str, Any],
# ) -> Dict[str, Any]:
#     """
#     Merge a single design view (logical / physical / process)
#     into existing design_views safely.
#     """
#     merged = previous.copy() if isinstance(previous, dict) else {}

#     merged.setdefault("logical_view", {})
#     merged.setdefault("physical_view", {})
#     merged.setdefault("process_view", {})

#     merged[view_key] = view_value
#     return merged


# # ============================================================
# # DYNAMIC SECTION REGISTRY
# # ============================================================
# def build_hld_section_registry() -> Dict[str, Dict[str, Any]]:
#     registry: Dict[str, Dict[str, Any]] = {}

#     for field_name, field_info in HLDReport.model_fields.items():
#         registry[field_name] = {
#             "field_name": field_name,
#             "annotation": field_info.annotation,
#             "state_key": _state_key_for_field(field_name),
#             "title": getattr(field_info, "title", None) or field_name,
#         }

#     return registry


# HLD_SECTION_REGISTRY = build_hld_section_registry()


# # ============================================================
# # DYNAMIC TOOL FACTORY (UNCHANGED)
# # ============================================================
# def _make_commit_function(field_name: str, annotation: Any, state_key: str):
#     def commit_section(value: Any, tool_context: Any = None, confirmed: bool = True) -> Dict[str, Any]:
#         validated = _validate_payload(annotation, value)
#         dumped = _dump_value(validated)

#         primary_state = _resolve_state(tool_context)
#         previous_value = primary_state.get(state_key) if primary_state else None

#         state_delta = {state_key: dumped}
#         _apply_state_delta(tool_context, state_delta)

#         return {
#             "status": "success",
#             "message": f"Committed section: {field_name}",
#             "confirmed": confirmed,
#             "overwritten": previous_value is not None,
#             "section_name": field_name,
#             "state_key": state_key,
#             "section_value": dumped,
#             "stateDelta": state_delta,
#             "state_delta": state_delta,
#         }

#     commit_section.__name__ = f"commit_{field_name}"
#     return commit_section


# # ============================================================
# # DESIGN VIEW SPLIT TOOL FACTORY (NEW)
# # ============================================================
# def _make_design_view_commit_function(view_key: str):
#     state_key = _state_key_for_field("design_views")

#     def commit_design_view(value: Dict[str, Any], tool_context: Any = None, confirmed: bool = True):
#         primary_state = _resolve_state(tool_context)
#         previous_value = primary_state.get(state_key) if primary_state else None

#         merged = _merge_design_view(previous_value, view_key, value)
#         validated = _validate_payload(DesignViewsSection, merged)
#         dumped = _dump_value(validated)

#         state_delta = {state_key: dumped}
#         _apply_state_delta(tool_context, state_delta)

#         return {
#             "status": "success",
#             "message": f"Committed design_views.{view_key}",
#             "confirmed": confirmed,
#             "overwritten": previous_value is not None,
#             "section_name": f"design_views.{view_key}",
#             "state_key": state_key,
#             "section_value": dumped,
#             "stateDelta": state_delta,
#             "state_delta": state_delta,
#         }

#     commit_design_view.__name__ = f"commit_design_views_{view_key}"
#     return commit_design_view


# # ============================================================
# # EXPORT DYNAMIC COMMIT FUNCTIONS + TOOLS
# # ============================================================
# _DYNAMIC_COMMIT_FUNCTIONS: Dict[str, Any] = {}
# _DYNAMIC_COMMIT_TOOLS: Dict[str, FunctionTool] = {}

# # Existing tools (UNCHANGED)
# for _field_name, _meta in HLD_SECTION_REGISTRY.items():
#     fn = _make_commit_function(
#         field_name=_meta["field_name"],
#         annotation=_meta["annotation"],
#         state_key=_meta["state_key"],
#     )
#     tool = FunctionTool(fn)

#     globals()[fn.__name__] = fn
#     globals()[f"{fn.__name__}_tool"] = tool

#     _DYNAMIC_COMMIT_FUNCTIONS[_field_name] = fn
#     _DYNAMIC_COMMIT_TOOLS[_field_name] = tool


# # ------------------------------------------------------------
# # DESIGN VIEW SPLIT COMMIT TOOLS (NEW)
# # ------------------------------------------------------------
# for _view in ["logical_view", "physical_view", "process_view"]:
#     fn = _make_design_view_commit_function(_view)
#     tool = FunctionTool(fn)

#     globals()[fn.__name__] = fn
#     globals()[f"{fn.__name__}_tool"] = tool

#     _DYNAMIC_COMMIT_FUNCTIONS[f"design_views.{_view}"] = fn
#     _DYNAMIC_COMMIT_TOOLS[f"design_views.{_view}"] = tool


# # ============================================================
# # PUBLIC ACCESSORS (UNCHANGED)
# # ============================================================
# def get_hld_section_commit_tools() -> List[FunctionTool]:
#     return list(_DYNAMIC_COMMIT_TOOLS.values())


# def get_hld_section_commit_tool(section_name: str) -> FunctionTool:
#     if section_name not in _DYNAMIC_COMMIT_TOOLS:
#         raise KeyError(f"Unknown HLD section tool requested: {section_name}")
#     return _DYNAMIC_COMMIT_TOOLS[section_name]


# def get_hld_section_commit_function(section_name: str):
#     if section_name not in _DYNAMIC_COMMIT_FUNCTIONS:
#         raise KeyError(f"Unknown HLD section function requested: {section_name}")
#     return _DYNAMIC_COMMIT_FUNCTIONS[section_name]


# def validate_required_hld_sections(state: Dict[str, Any]) -> Dict[str, Any]:
#     """
#     Deterministic completeness checker based on top-level HLDReport fields.
#     This checks PRESENCE only, not semantic richness.
#     """
#     missing_sections = []

#     for field_name, meta in HLD_SECTION_REGISTRY.items():
#         state_key = meta["state_key"]
#         if state.get(state_key) is None:
#             missing_sections.append(field_name)

#     return {
#         "all_present": len(missing_sections) == 0,
#         "missing_sections": missing_sections,
#     }


# def validate_hld_section_quality(state: Dict[str, Any]) -> Dict[str, Any]:
#     """
#     Lightweight quality check for emptiness of top-level HLD sections.
#     """
#     empty_sections = []

#     for field_name, meta in HLD_SECTION_REGISTRY.items():
#         state_key = meta["state_key"]
#         value = state.get(state_key)
#         if value is None or value == {} or value == []:
#             empty_sections.append(field_name)

#     return {
#         "all_non_empty": len(empty_sections) == 0,
#         "empty_sections": empty_sections,
#     }


# def assemble_hld_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
#     """
#     Assemble final HLD JSON from section-wise state and validate
#     against the authoritative HLDReport schema.
#     """
#     assembled = {}

#     for field_name, meta in HLD_SECTION_REGISTRY.items():
#         state_key = meta["state_key"]
#         assembled[field_name] = state.get(state_key)

#     validated = HLDReport.model_validate(assembled)
#     return validated.model_dump()

from __future__ import annotations

import logging
import html
import re
import types
from typing import Any, Dict, List, Optional, get_args, get_origin, Union

from google.adk.tools import FunctionTool
from pydantic import TypeAdapter

from schema_types.hld_schema import HLDReport, DesignViewsSection
from agent.workflow.keys import KEY_HLD_SECTION_STATE_PREFIX


logger = logging.getLogger("HLDSectionCommitTools")


# ============================================================
# HELPERS
# ============================================================
def _is_view_section_complete(value: Any) -> bool:
    """
    ViewSection completeness check based on current schema:

    class ViewSection:
        diagrams: List[str]

    A view is complete only when diagrams is a non-empty list
    containing at least one non-empty string.
    """
    if not isinstance(value, dict):
        return False

    diagrams = value.get("diagrams")

    if not isinstance(diagrams, list):
        return False

    return any(isinstance(d, str) and d.strip() for d in diagrams)


def _is_design_views_complete(value: Any) -> bool:
    """
    Dynamic completeness check for design_views.
    Requires every schema-defined design view child to be present
    and to contain at least one non-empty diagram.
    """
    if not isinstance(value, dict):
        return False

    for design_view_name in get_design_view_section_names():
        child_value = value.get(design_view_name)

        if not _is_view_section_complete(child_value):
            return False

    return True


def _resolve_state(tool_context: Any) -> Optional[Dict[str, Any]]:
    if tool_context is None:
        return None

    if hasattr(tool_context, "state") and isinstance(tool_context.state, dict):
        return tool_context.state

    session = getattr(tool_context, "session", None)
    if session is not None and hasattr(session, "state") and isinstance(session.state, dict):
        return session.state

    return None


def _resolve_all_state_targets(tool_context: Any) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []

    if tool_context is None:
        return targets

    direct_state = getattr(tool_context, "state", None)
    if isinstance(direct_state, dict):
        targets.append(direct_state)

    session = getattr(tool_context, "session", None)
    session_state = getattr(session, "state", None) if session is not None else None
    if isinstance(session_state, dict):
        if not any(id(t) == id(session_state) for t in targets):
            targets.append(session_state)

    return targets


def _apply_state_delta(tool_context: Any, state_delta: Dict[str, Any]) -> None:
    if not isinstance(state_delta, dict) or not state_delta:
        return

    for target in _resolve_all_state_targets(tool_context):
        try:
            target.update(state_delta)
        except Exception:
            logger.exception("[HLD_TOOLS] Failed to apply state_delta.")


def _dump_value(value: Any) -> Any:
    if value is None:
        return None

    if hasattr(value, "model_dump") and callable(value.model_dump):
        return value.model_dump()

    if hasattr(value, "dict") and callable(value.dict):
        return value.dict()

    if isinstance(value, list):
        return [_dump_value(v) for v in value]

    if isinstance(value, dict):
        return {k: _dump_value(v) for k, v in value.items()}

    return value


def _state_key_for_field(field_name: str) -> str:
    return f"{KEY_HLD_SECTION_STATE_PREFIX}{field_name}"


# ============================================================
# DIAGRAM SANITIZATION HELPERS
# ============================================================
# Policy markers for clusters/subgraphs that must be visible but disconnected.
# This is intentionally small and policy-based, not schema-section hardcoding.
ISOLATED_CLUSTER_MARKERS = {
    "observability",
    "logging",
    "monitoring",
    "cicd",
    "ci cd",
    "ci/cd",
    "deployment",
    "iac",
    "orchestration",
}

# Small fallback only when the model does not place nodes in an isolated cluster.
ISOLATED_FALLBACK_LABEL_MARKERS = {
    "cloud logging",
    "google cloud logging",
    "cloud monitoring",
    "google cloud monitoring",
    "cloud build",
    "google cloud build",
    "terraform",
}


def _unescape_dot_text(text: str) -> str:
    """
    Normalize escaped DOT content into Graphviz-safe text.
    Converts escaped arrows into real Graphviz arrows.
    """
    if not isinstance(text, str):
        return str(text)

    for _ in range(4):
        new_text = html.unescape(text)
        if new_text == text:
            break
        text = new_text

    text = (
        text
        .replace("-&gt;", "->")
        .replace("-&amp;gt;", "->")
        .replace("-&amp;amp;gt;", "->")
        .replace("-&amp;amp;amp;gt;", "->")
        .replace("-&amp;amp;amp;amp;gt;", "->")
        .replace("&lt;br/&gt;", "\\n")
        .replace("&lt;br&gt;", "\\n")
        .replace("<br/>", "\\n")
        .replace("<br>", "\\n")
    )

    return text


def _normalize_edge_operators_for_dot(dot_text: str) -> str:
    """
    DOT rule:
      - digraph must use ->
      - graph must use --
    """
    if not isinstance(dot_text, str) or not dot_text.strip():
        return dot_text

    is_directed = bool(re.search(r"^\s*digraph\b", dot_text, flags=re.IGNORECASE))
    is_undirected = bool(re.search(r"^\s*graph\b", dot_text, flags=re.IGNORECASE))

    if not is_directed and not is_undirected:
        return dot_text

    out: List[str] = []
    in_quotes = False
    escape = False
    i = 0

    while i < len(dot_text):
        ch = dot_text[i]

        if ch == "\\" and not escape:
            escape = True
            out.append(ch)
            i += 1
            continue

        if ch == '"' and not escape:
            in_quotes = not in_quotes
            out.append(ch)
            i += 1
            continue

        escape = False

        if not in_quotes:
            two = dot_text[i:i + 2]

            if is_directed and two == "--":
                out.append("->")
                i += 2
                continue

            if is_undirected and two == "->":
                out.append("--")
                i += 2
                continue

        out.append(ch)
        i += 1

    return "".join(out)


def _normalize_dot_ref(value: Any) -> str:
    text = str(value or "").strip()
    text = text.strip(";").strip()
    text = text.strip('"').strip("'")
    return text


def _normalize_policy_text(value: Any) -> str:
    text = str(value or "").lower()
    text = text.replace("\\n", " ")
    text = text.replace("\n", " ")
    text = text.replace("_", " ")
    text = text.replace("-", " ")
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9/ ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _has_any_marker(value: Any, markers: set[str]) -> bool:
    normalized = _normalize_policy_text(value)
    return any(marker in normalized for marker in markers)


def _is_isolated_cluster_text(value: Any) -> bool:
    return _has_any_marker(value, ISOLATED_CLUSTER_MARKERS)


def _is_isolated_fallback_label(value: Any) -> bool:
    return _has_any_marker(value, ISOLATED_FALLBACK_LABEL_MARKERS)


def _split_dot_statements_for_sanitize(dot_text: str) -> List[str]:
    """
    Split DOT into rough statements while preserving quoted strings.

    This is intentionally conservative:
    - inserts statement breaks after ; outside quotes
    - inserts structural breaks around { and } outside quotes
    """
    statements: List[str] = []
    current: List[str] = []
    in_quotes = False
    escape = False

    for ch in dot_text:
        if ch == "\\" and not escape:
            escape = True
            current.append(ch)
            continue

        if ch == '"' and not escape:
            in_quotes = not in_quotes
            current.append(ch)
            escape = False
            continue

        escape = False

        if not in_quotes and ch in "{}":
            existing = "".join(current).strip()
            if existing:
                statements.append(existing)
                current = []

            statements.append(ch)
            continue

        current.append(ch)

        if not in_quotes and ch == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []

    tail = "".join(current).strip()
    if tail:
        statements.extend([ln.strip() for ln in tail.splitlines() if ln.strip()])

    return [s for s in statements if s.strip()]


def _extract_node_label_from_statement(statement: str) -> Optional[tuple[str, str]]:
    """
    Extract node id and label from:
      NodeA [label="Google Cloud Logging"];
      "Node A" [label="Cloud Monitoring"];
    """
    if not isinstance(statement, str):
        return None

    stripped = statement.strip()

    if "->" in stripped or "--" in stripped:
        return None

    if "[" not in stripped or "]" not in stripped:
        return None

    match = re.match(
        r'^\s*(?P<node>"[^"]+"|[A-Za-z_][A-Za-z0-9_.-]*)\s*\[(?P<attrs>.*?)\]\s*;?$',
        stripped,
        flags=re.DOTALL,
    )

    if not match:
        return None

    node_id = _normalize_dot_ref(match.group("node"))
    attrs = match.group("attrs") or ""

    label_match = re.search(
        r'label\s*=\s*"(?P<label>.*?)"',
        attrs,
        flags=re.DOTALL,
    )
    label = label_match.group("label") if label_match else node_id

    return node_id, label


def _extract_edge_endpoints(statement: str) -> Optional[tuple[str, str]]:
    """
    Extract source/destination from:
      A -> B;
      A -- B;
      "A Node" -> "B Node" [label="x"];
    """
    if not isinstance(statement, str):
        return None

    no_attrs = re.sub(r"\[.*?\]", "", statement, flags=re.DOTALL).strip().rstrip(";")

    match = re.match(
        r'^\s*(?P<src>"[^"]+"|[A-Za-z_][A-Za-z0-9_.-]*)\s*(?P<op>->|--)\s*(?P<dst>"[^"]+"|[A-Za-z_][A-Za-z0-9_.-]*)',
        no_attrs,
    )

    if not match:
        return None

    src = _normalize_dot_ref(match.group("src"))
    dst = _normalize_dot_ref(match.group("dst"))

    return src, dst


def _extract_balanced_subgraph_blocks(dot_text: str) -> List[str]:
    """
    Extract subgraph blocks using brace balancing.

    This lets us detect nodes inside isolated clusters dynamically,
    without hardcoding all service labels.
    """
    if not isinstance(dot_text, str):
        return []

    blocks: List[str] = []

    for match in re.finditer(r"\bsubgraph\b", dot_text, flags=re.IGNORECASE):
        start = match.start()
        brace_start = dot_text.find("{", match.end())

        if brace_start < 0:
            continue

        depth = 0
        in_quotes = False
        escape = False

        for idx in range(brace_start, len(dot_text)):
            ch = dot_text[idx]

            if ch == "\\" and not escape:
                escape = True
                continue

            if ch == '"' and not escape:
                in_quotes = not in_quotes

            escape = False

            if in_quotes:
                continue

            if ch == "{":
                depth += 1

            elif ch == "}":
                depth -= 1
                if depth == 0:
                    blocks.append(dot_text[start:idx + 1])
                    break

    return blocks


def _is_isolated_subgraph_block(block_text: str) -> bool:
    """
    A subgraph is isolated when the subgraph name or label declares it as
    observability / CI-CD / IaC / deployment / orchestration.

    This avoids relying on a big list of service labels.
    """
    if not isinstance(block_text, str):
        return False

    # Header up to first opening brace.
    header = block_text.split("{", 1)[0]

    if _is_isolated_cluster_text(header):
        return True

    # Check explicit label within the cluster.
    label_match = re.search(
        r'\blabel\s*=\s*"(?P<label>.*?)"',
        block_text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if label_match and _is_isolated_cluster_text(label_match.group("label")):
        return True

    return False


def _collect_isolated_nodes_from_subgraphs(dot_text: str) -> set[str]:
    """
    Collect all node ids that live inside isolated subgraphs/clusters.
    """
    isolated_node_ids: set[str] = set()

    for block in _extract_balanced_subgraph_blocks(dot_text):
        if not _is_isolated_subgraph_block(block):
            continue

        for stmt in _split_dot_statements_for_sanitize(block):
            node_info = _extract_node_label_from_statement(stmt)
            if not node_info:
                continue

            node_id, _label = node_info
            isolated_node_ids.add(node_id)

    return isolated_node_ids


def _edge_touches_isolated_node(
    statement: str,
    isolated_node_ids: set[str],
    node_label_lookup: Dict[str, str],
) -> bool:
    endpoints = _extract_edge_endpoints(statement)

    if not endpoints:
        return False

    src, dst = endpoints

    for node_id in (src, dst):
        normalized = _normalize_dot_ref(node_id)

        if normalized in isolated_node_ids:
            return True

        label = node_label_lookup.get(normalized, "")

        # Fallback only when cluster-based detection is unavailable or incomplete.
        if _is_isolated_fallback_label(normalized):
            return True

        if _is_isolated_fallback_label(label):
            return True

    return False


def sanitize_graphviz_dot(dot_text: str) -> str:
    """
    Deterministic guardrail before committing DOT into HLD state.

    Enforces:
    - real Graphviz arrows
    - digraph uses ->
    - nodes inside observability / CI-CD / IaC clusters remain visible but disconnected
    - small fallback for explicit Cloud Logging / Monitoring / Cloud Build / Terraform labels
    """
    if not isinstance(dot_text, str):
        return dot_text

    dot_text = _unescape_dot_text(dot_text)
    dot_text = _normalize_edge_operators_for_dot(dot_text)

    statements = _split_dot_statements_for_sanitize(dot_text)

    node_label_lookup: Dict[str, str] = {}

    # Dynamic isolation: collect nodes inside isolated subgraphs.
    isolated_node_ids = _collect_isolated_nodes_from_subgraphs(dot_text)

    # Fallback isolation: collect explicitly labelled isolated service nodes.
    for stmt in statements:
        node_info = _extract_node_label_from_statement(stmt)
        if not node_info:
            continue

        node_id, label = node_info
        node_label_lookup[node_id] = label

        if _is_isolated_fallback_label(node_id) or _is_isolated_fallback_label(label):
            isolated_node_ids.add(node_id)

    cleaned_statements: List[str] = []

    for stmt in statements:
        normalized_stmt = _normalize_edge_operators_for_dot(stmt)

        if "->" in normalized_stmt or "--" in normalized_stmt:
            if _edge_touches_isolated_node(
                statement=normalized_stmt,
                isolated_node_ids=isolated_node_ids,
                node_label_lookup=node_label_lookup,
            ):
                logger.info(
                    "[HLD_TOOLS] Removed diagram edge touching isolated node before commit: %s",
                    normalized_stmt,
                )
                continue

        cleaned_statements.append(normalized_stmt)

    sanitized = "\n".join(cleaned_statements)
    sanitized = _unescape_dot_text(sanitized)
    sanitized = _normalize_edge_operators_for_dot(sanitized)

    return sanitized


def sanitize_view_section_payload(value: Any) -> Any:
    """
    Sanitize ViewSection-shaped payload:
      {"diagrams": ["digraph ..."]}
    """
    if not isinstance(value, dict):
        return value

    diagrams = value.get("diagrams")

    if not isinstance(diagrams, list):
        return value

    updated = dict(value)
    updated["diagrams"] = [
        sanitize_graphviz_dot(diagram) if isinstance(diagram, str) else diagram
        for diagram in diagrams
    ]

    return updated


def sanitize_data_design_payload(value: Any) -> Any:
    """
    Sanitize data_design.data_flow.diagrams before committing data_design.
    """
    if not isinstance(value, dict):
        return value

    updated = dict(value)
    data_flow = updated.get("data_flow")

    if isinstance(data_flow, dict):
        updated["data_flow"] = sanitize_view_section_payload(data_flow)

    return updated


# ============================================================
# NEW: VALIDATION NORMALIZATION HELPERS
# ============================================================
def _unwrap_optional_annotation(annotation: Any) -> Any:
    """
    Unwrap Optional[T] / T | None style annotations to T when possible.
    """
    current = annotation

    while True:
        origin = get_origin(current)
        if origin not in (Union, types.UnionType):
            return current

        args = [a for a in get_args(current) if a is not type(None)]
        if len(args) == 1:
            current = args[0]
            continue

        return current


def _is_permissive_dict_annotation(annotation: Any) -> bool:
    """
    True only for generic dict-like annotations that are effectively:
    - dict
    - Dict
    - dict[str, Any]
    - Dict[str, Any]

    We keep this intentionally narrow so we do NOT mutate strict schema models.
    """
    ann = _unwrap_optional_annotation(annotation)

    # ✅ Bare dict / Dict support
    if ann in (dict, Dict):
        return True

    origin = get_origin(ann)

    if origin not in (dict, Dict):
        return False

    args = get_args(ann)
    if not args:
        return True

    if len(args) != 2:
        return False

    key_type, value_type = args
    key_ok = key_type in (str, Any)
    value_ok = value_type is Any or value_type == Any
    return key_ok and value_ok


def _is_list_of_permissive_dicts(annotation: Any) -> bool:
    """
    True only for annotations effectively shaped like:
    - list[dict[str, Any]]
    - List[Dict[str, Any]]
    - Optional[list[dict[str, Any]]]
    """
    ann = _unwrap_optional_annotation(annotation)
    origin = get_origin(ann)

    if origin not in (list, List):
        return False

    args = get_args(ann)
    if len(args) != 1:
        return False

    inner = args[0]
    return _is_permissive_dict_annotation(inner)


def _coerce_record_item(item: Any) -> Dict[str, Any]:
    """
    Convert a non-dict item into a minimal dict record.
    This is ONLY used for permissive list[dict[str, Any]] fields.
    """
    if isinstance(item, dict):
        return item

    if hasattr(item, "model_dump") and callable(item.model_dump):
        dumped = item.model_dump()
        if isinstance(dumped, dict):
            return dumped
        return {"value": dumped}

    if hasattr(item, "dict") and callable(item.dict):
        dumped = item.dict()
        if isinstance(dumped, dict):
            return dumped
        return {"value": dumped}

    if isinstance(item, str):
        return {"description": item}

    if item is None:
        return {"description": ""}

    if isinstance(item, list):
        return {"items": _dump_value(item)}

    return {"value": _dump_value(item)}


def _normalize_value_for_annotation(annotation: Any, value: Any) -> Any:
    """
    Defensive normalization ONLY for permissive object-list fields.

    Example:
      annotation = list[dict[str, Any]]
      value      = ["a", "b"]

    becomes:
      [{"description": "a"}, {"description": "b"}]
    """
    if value is None:
        return value

    if _is_list_of_permissive_dicts(annotation) and isinstance(value, list):
        if not all(isinstance(v, dict) for v in value):
            logger.warning(
                "[HLD_TOOLS] Coercing non-dict list items into dict records for permissive annotation %s",
                annotation,
            )
            return [_coerce_record_item(v) for v in value]

    return value


def _validate_payload(annotation: Any, value: Any) -> Any:
    normalized_value = _normalize_value_for_annotation(annotation, value)
    adapter = TypeAdapter(annotation)
    return adapter.validate_python(normalized_value)


def _is_data_design_complete(value: Any) -> bool:
    """
    DataDesignSection completeness check.

    Current schema:

    class DataDesignSection:
        data_flow: ViewSection
        impact_summary: List[Dict[str, Any]]
        logical_data_model: List[Dict[str, Any]]
        data_storage: List[Dict[str, Any]]
        subject_areas: List[Dict[str, Any]]

    For rendering quality, data_design is complete only when:
    - section has meaningful content
    - data_flow.diagrams has at least one non-empty Graphviz string
    """
    if not isinstance(value, dict):
        return False

    data_flow = value.get("data_flow")

    if not _is_view_section_complete(data_flow):
        return False

    return is_hld_section_value_present(value)


def _is_effectively_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return len(value) == 0
    if isinstance(value, dict):
        return len(value) == 0
    return False

def _get_schema_model_fields_from_annotation(annotation: Any) -> Dict[str, Any]:
    """
    Resolve Pydantic model fields from an annotation dynamically.

    This avoids hardcoding document_control child names in the validation logic.
    If the schema defines:
      - history
      - key_reviewers
      - key_approvers

    then this function returns those fields dynamically from the schema.
    """
    ann = _unwrap_optional_annotation(annotation)

    model_fields = getattr(ann, "model_fields", None)

    if isinstance(model_fields, dict):
        return model_fields

    return {}


def _is_meaningful_record_collection(value: Any) -> bool:
    """
    True when a value is meaningful enough for renderer/table output.

    Supports:
      - list[dict]
      - dict
      - scalar fallback

    Does not create or inject fallback rows.
    """
    if _is_effectively_empty(value):
        return False

    if isinstance(value, list):
        meaningful_items = []

        for item in value:
            if isinstance(item, dict):
                if any(not _is_effectively_empty(v) for v in item.values()):
                    meaningful_items.append(item)
            elif not _is_effectively_empty(item):
                meaningful_items.append(item)

        return len(meaningful_items) > 0

    if isinstance(value, dict):
        return any(not _is_effectively_empty(v) for v in value.values())

    return not _is_effectively_empty(value)


def _is_document_control_complete(
    value: Any,
    annotation: Any,
) -> bool:
    """
    Document Control completeness check driven by schema fields.

    This does NOT hardcode reviewer/approver rows.
    This does NOT inject TBC values.
    This only rejects incomplete generated payloads.

    If the schema defines child fields such as:
      - history
      - key_reviewers
      - key_approvers

    then each schema-defined child field must be present and non-empty.
    """
    if not isinstance(value, dict):
        return False

    schema_fields = _get_schema_model_fields_from_annotation(annotation)

    if not schema_fields:
        return is_hld_section_value_present(value)

    missing_or_empty_fields: List[str] = []

    for child_field_name in schema_fields.keys():
        child_value = value.get(child_field_name)

        if not _is_meaningful_record_collection(child_value):
            missing_or_empty_fields.append(child_field_name)

    if missing_or_empty_fields:
        logger.warning(
            "[HLD_TOOLS] document_control incomplete. Missing/empty fields=%s",
            missing_or_empty_fields,
        )
        return False

    return True
# ============================================================
# DESIGN VIEWS MERGE HELPER
# ============================================================
def _merge_design_view(
    previous: Optional[Dict[str, Any]],
    view_key: str,
    view_value: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Merge a single design view (logical / physical / process)
    into existing design_views safely.
    """
    merged = previous.copy() if isinstance(previous, dict) else {}

    for design_view_name in get_design_view_section_names():
        merged.setdefault(design_view_name, {})

    merged[view_key] = view_value
    return merged


# ============================================================
# DYNAMIC SECTION REGISTRY
# ============================================================
def build_hld_section_registry() -> Dict[str, Dict[str, Any]]:
    registry: Dict[str, Dict[str, Any]] = {}

    for field_name, field_info in HLDReport.model_fields.items():
        registry[field_name] = {
            "field_name": field_name,
            "annotation": field_info.annotation,
            "state_key": _state_key_for_field(field_name),
            "title": getattr(field_info, "title", None) or field_name,
        }

    return registry


HLD_SECTION_REGISTRY = build_hld_section_registry()


# ============================================================
# DYNAMIC SECTION PROGRESS HELPERS
# ============================================================
def get_design_view_section_names() -> List[str]:
    """
    Dynamic design view names from DesignViewsSection schema.
    No hardcoding.
    """
    return list(DesignViewsSection.model_fields.keys())


def get_design_view_annotation(view_key: str) -> Any:
    """
    Resolve schema annotation for one design view child dynamically.

    Example:
      logical_view -> annotation of DesignViewsSection.logical_view
      physical_view -> annotation of DesignViewsSection.physical_view
      process_view -> annotation of DesignViewsSection.process_view
    """
    if view_key not in DesignViewsSection.model_fields:
        raise KeyError(f"Unknown design view section: {view_key}")

    return DesignViewsSection.model_fields[view_key].annotation


def get_hld_required_section_names() -> List[str]:
    """
    Dynamic required section names from HLDReport schema.
    No hardcoding.
    """
    return list(HLD_SECTION_REGISTRY.keys())


def get_hld_section_state_key(section_name: str) -> str:
    """
    Resolve section state key dynamically from registry.
    Supports:
      - top-level section: data_design
      - dotted sub-section: design_views.logical_view
    """
    top_level = section_name.split(".", 1)[0] if section_name else section_name

    if top_level not in HLD_SECTION_REGISTRY:
        raise KeyError(f"Unknown HLD section name: {section_name}")

    return HLD_SECTION_REGISTRY[top_level]["state_key"]


def normalize_hld_section_name(section_name: Optional[str]) -> Optional[str]:
    """
    Normalize retry/commit section names.

    Examples:
      design_views.logical_view -> design_views.logical_view
      design_views_logical_view -> design_views.logical_view
      data_design -> data_design
    """
    if not section_name:
        return None

    section_name = str(section_name).strip()

    if not section_name:
        return None

    if section_name.startswith("design_views_"):
        return "design_views." + section_name.replace("design_views_", "", 1)

    return section_name


def section_name_from_commit_tool_name(tool_name: Optional[str]) -> Optional[str]:
    """
    Dynamically derive HLD section name from commit tool name.

    Examples:
      commit_data_design -> data_design
      commit_design_views_logical_view -> design_views.logical_view
      commit_hld_to_memory -> None
    """
    if not tool_name or not str(tool_name).startswith("commit_"):
        return None

    raw_name = str(tool_name).replace("commit_", "", 1)

    if raw_name == "hld_to_memory":
        return None

    return normalize_hld_section_name(raw_name)


def is_hld_section_value_present(value: Any) -> bool:
    """
    Generic non-empty check used for section progress tracking.
    Treats nested empty dict/list/string as not meaningful.
    """
    if value is None:
        return False

    if isinstance(value, str):
        return bool(value.strip())

    if isinstance(value, list):
        return any(is_hld_section_value_present(item) for item in value)

    if isinstance(value, dict):
        return any(is_hld_section_value_present(v) for v in value.values())

    return True


def is_hld_section_committed(state: Dict[str, Any], section_name: str) -> bool:
    """
    Dynamic committed-section check.

    For dotted design view sections:
      design_views.logical_view checks hld_design_views.logical_view

    For top-level design_views:
      requires every DesignViewsSection child to be present and non-empty.

    For data_design:
      requires data_design.data_flow.diagrams to be non-empty, plus meaningful section content.
    """
    normalized = normalize_hld_section_name(section_name)
    if not normalized:
        return False

    state_key = get_hld_section_state_key(normalized)
    value = state.get(state_key)

    # ------------------------------------------------------------
    # Dotted sub-section support, e.g. design_views.logical_view
    # ------------------------------------------------------------
    if "." in normalized:
        parent_key, child_key = normalized.split(".", 1)

        if not isinstance(value, dict):
            return False

        child_value = value.get(child_key)

        if parent_key == "design_views":
            return _is_view_section_complete(child_value)

        return is_hld_section_value_present(child_value)

    # ------------------------------------------------------------
    # Dynamic special handling for design_views parent section
    # ------------------------------------------------------------
    if normalized == "design_views":
        return _is_design_views_complete(value)

    # ------------------------------------------------------------
    # Special handling for data_design because data_flow.diagrams
    # must not be empty.
    # ------------------------------------------------------------
    if normalized == "data_design":
        return _is_data_design_complete(value)


    if normalized == "document_control":
        annotation = HLD_SECTION_REGISTRY[normalized]["annotation"]
        return _is_document_control_complete(
            value=value,
            annotation=annotation,
        )

    # ------------------------------------------------------------
    # Generic top-level section check
    # ------------------------------------------------------------
    return is_hld_section_value_present(value)


def get_committed_hld_sections(state: Dict[str, Any]) -> List[str]:
    """
    Return dynamically detected committed top-level HLD sections.
    """
    committed = []

    for section_name in get_hld_required_section_names():
        if is_hld_section_committed(state, section_name):
            committed.append(section_name)

    return committed


def get_missing_hld_sections(state: Dict[str, Any]) -> List[str]:
    """
    Return dynamically detected missing top-level HLD sections.
    """
    missing = []

    for section_name in get_hld_required_section_names():
        if not is_hld_section_committed(state, section_name):
            missing.append(section_name)

    return missing


def is_hld_final_validation_ready(state: Dict[str, Any]) -> bool:
    """
    Final validation is allowed only when every required HLD section
    exists in state.
    """
    return len(get_missing_hld_sections(state)) == 0


# ============================================================
# DYNAMIC TOOL FACTORY
# ============================================================
def _make_commit_function(field_name: str, annotation: Any, state_key: str):
    def commit_section(value: Any, tool_context: Any = None, confirmed: bool = True) -> Dict[str, Any]:
        # Sanitize diagram-bearing top-level sections before schema validation.
        if field_name == "data_design":
            value = sanitize_data_design_payload(value)

        validated = _validate_payload(annotation, value)
        dumped = _dump_value(validated)

        if field_name == "data_design" and not _is_data_design_complete(dumped):
            return {
                "status": "error",
                "message": (
                    "Rejected data_design: data_flow.diagrams must contain "
                    "at least one non-empty Graphviz DOT string."
                ),
                "confirmed": False,
                "overwritten": False,
                "section_name": field_name,
                "state_key": state_key,
                "section_value": dumped,
                "stateDelta": {},
                "state_delta": {},
            }

        if field_name == "document_control" and not _is_document_control_complete(
                    dumped,
                    annotation,
                ):
                schema_fields = _get_schema_model_fields_from_annotation(annotation)
                expected_fields = list(schema_fields.keys())

                return {
                    "status": "error",
                    "message": (
                        "Rejected document_control: generated payload is incomplete. "
                        "The section must include all schema-defined child fields as "
                        f"non-empty structured records. Expected fields: {expected_fields}"
                    ),
                    "confirmed": False,
                    "overwritten": False,
                    "section_name": field_name,
                    "state_key": state_key,
                    "section_value": dumped,
                    "stateDelta": {},
                    "state_delta": {},
                }
        primary_state = _resolve_state(tool_context)
        previous_value = primary_state.get(state_key) if primary_state else None

        state_delta = {state_key: dumped}
        _apply_state_delta(tool_context, state_delta)

        return {
            "status": "success",
            "message": f"Committed section: {field_name}",
            "confirmed": confirmed,
            "overwritten": previous_value is not None,
            "section_name": field_name,
            "state_key": state_key,
            "section_value": dumped,
            "stateDelta": state_delta,
            "state_delta": state_delta,
        }

    commit_section.__name__ = f"commit_{field_name}"
    return commit_section


# ============================================================
# DESIGN VIEW SPLIT TOOL FACTORY
# ============================================================
def _make_design_view_commit_function(view_key: str):
    state_key = _state_key_for_field("design_views")
    view_annotation = get_design_view_annotation(view_key)

    def commit_design_view(value: Dict[str, Any], tool_context: Any = None, confirmed: bool = True):
        primary_state = _resolve_state(tool_context)
        previous_value = primary_state.get(state_key) if primary_state else None

        # ------------------------------------------------------------
        # Validate ONLY this child view.
        # Do NOT validate full DesignViewsSection here.
        # This allows logical/physical/process views to be committed separately.
        # ------------------------------------------------------------

        # Sanitize diagrams before schema validation and before saving state.
        value = sanitize_view_section_payload(value)

        validated_view = _validate_payload(view_annotation, value)
        dumped_view = _dump_value(validated_view)

        if not _is_view_section_complete(dumped_view):
            return {
                "status": "error",
                "message": (
                    f"Rejected design_views.{view_key}: "
                    "diagrams must contain at least one non-empty Graphviz DOT string."
                ),
                "confirmed": False,
                "section_name": f"design_views.{view_key}",
                "state_key": state_key,
                "section_value": dumped_view,
                "stateDelta": {},
                "state_delta": {},
            }

        # ------------------------------------------------------------
        # Merge validated child view into shared hld_design_views state.
        # Final full DesignViewsSection validation happens later in assemble_hld_from_state().
        # ------------------------------------------------------------
        merged = _merge_design_view(previous_value, view_key, dumped_view)

        state_delta = {state_key: merged}
        _apply_state_delta(tool_context, state_delta)

        return {
            "status": "success",
            "message": f"Committed design_views.{view_key}",
            "confirmed": confirmed,
            "overwritten": previous_value is not None,
            "section_name": f"design_views.{view_key}",
            "state_key": state_key,
            "section_value": merged,
            "stateDelta": state_delta,
            "state_delta": state_delta,
        }

    commit_design_view.__name__ = f"commit_design_views_{view_key}"
    return commit_design_view


# ============================================================
# EXPORT DYNAMIC COMMIT FUNCTIONS + TOOLS
# ============================================================
_DYNAMIC_COMMIT_FUNCTIONS: Dict[str, Any] = {}
_DYNAMIC_COMMIT_TOOLS: Dict[str, FunctionTool] = {}

# Existing tools
for _field_name, _meta in HLD_SECTION_REGISTRY.items():
    fn = _make_commit_function(
        field_name=_meta["field_name"],
        annotation=_meta["annotation"],
        state_key=_meta["state_key"],
    )
    tool = FunctionTool(fn)

    globals()[fn.__name__] = fn
    globals()[f"{fn.__name__}_tool"] = tool

    _DYNAMIC_COMMIT_FUNCTIONS[_field_name] = fn
    _DYNAMIC_COMMIT_TOOLS[_field_name] = tool


# ------------------------------------------------------------
# DESIGN VIEW SPLIT COMMIT TOOLS
# ------------------------------------------------------------
for _view in get_design_view_section_names():
    fn = _make_design_view_commit_function(_view)
    tool = FunctionTool(fn)

    globals()[fn.__name__] = fn
    globals()[f"{fn.__name__}_tool"] = tool

    _DYNAMIC_COMMIT_FUNCTIONS[f"design_views.{_view}"] = fn
    _DYNAMIC_COMMIT_TOOLS[f"design_views.{_view}"] = tool


# ============================================================
# PUBLIC ACCESSORS
# ============================================================
def get_hld_section_commit_tools() -> List[FunctionTool]:
    return list(_DYNAMIC_COMMIT_TOOLS.values())


def get_hld_section_commit_tools_for_architect() -> List[FunctionTool]:
    """
    Architect-facing commit tools.

    Excludes parent commit_design_views so architect uses smaller split tools:
      - commit_design_views_logical_view
      - commit_design_views_physical_view
      - commit_design_views_process_view
    """
    tools: List[FunctionTool] = []

    for section_name, tool in _DYNAMIC_COMMIT_TOOLS.items():
        if section_name == "design_views":
            continue
        tools.append(tool)

    return tools


def get_hld_section_commit_tool(section_name: str) -> FunctionTool:
    normalized = normalize_hld_section_name(section_name)

    if normalized not in _DYNAMIC_COMMIT_TOOLS:
        raise KeyError(f"Unknown HLD section tool requested: {section_name}")

    return _DYNAMIC_COMMIT_TOOLS[normalized]


def get_hld_section_commit_function(section_name: str):
    normalized = normalize_hld_section_name(section_name)

    if normalized not in _DYNAMIC_COMMIT_FUNCTIONS:
        raise KeyError(f"Unknown HLD section function requested: {section_name}")

    return _DYNAMIC_COMMIT_FUNCTIONS[normalized]


def validate_required_hld_sections(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deterministic completeness checker based on top-level HLDReport fields.
    This checks PRESENCE only, not semantic richness.

    Uses dynamic registry; no hardcoded section names.
    """
    missing_sections = get_missing_hld_sections(state)

    return {
        "all_present": len(missing_sections) == 0,
        "missing_sections": missing_sections,
    }


def validate_hld_section_quality(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Lightweight quality check for emptiness of top-level HLD sections.

    Uses dynamic registry; no hardcoded section names.
    """
    empty_sections = []

    for field_name in get_hld_required_section_names():
        if not is_hld_section_committed(state, field_name):
            empty_sections.append(field_name)

    return {
        "all_non_empty": len(empty_sections) == 0,
        "empty_sections": empty_sections,
    }


def assemble_hld_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assemble final HLD JSON from section-wise state and validate
    against the authoritative HLDReport schema.
    """
    assembled = {}

    for field_name, meta in HLD_SECTION_REGISTRY.items():
        state_key = meta["state_key"]
        assembled[field_name] = state.get(state_key)

    validated = HLDReport.model_validate(assembled)
    return validated.model_dump()