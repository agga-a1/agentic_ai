# from __future__ import annotations

# """
# visio_vsdx_exporter.py

# Generic Graphviz DOT/SVG -> editable Visio VSDX exporter.

# Latest fixes:
# - Bigger, darker, centrally aligned native editable icons.
# - Better card sizing so labels do not overlap and icon/label zones stay separated.
# - Group/zone boxes are rendered behind nodes with coloured fill and top-aligned header text.
# - SVG clusters are parsed more robustly, including Graphviz cluster groups and generic labelled
#   container groups.
# - No service-name/project-name specific hardcoding.
# """

# import html
# import logging
# import math
# import os
# import re
# import shutil
# import subprocess
# import zipfile
# from dataclasses import dataclass
# from pathlib import Path
# from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
# from urllib.parse import unquote
# from xml.etree import ElementTree as ET

# logger = logging.getLogger(__name__)

# try:
#     from PIL import Image, ImageEnhance
# except Exception:  # pragma: no cover
#     Image = None  # type: ignore
#     ImageEnhance = None  # type: ignore

# try:
#     from .config import PROJECT_ROOT  # type: ignore
# except Exception:
#     PROJECT_ROOT = Path.cwd()  # type: ignore

# try:
#     from .icon_resolver import get_style_for_label, resolve_icon_from_node_label  # type: ignore
# except Exception:
#     get_style_for_label = None  # type: ignore
#     resolve_icon_from_node_label = None  # type: ignore

# try:
#     from .node_card import clean_label, normalize_icon_for_graphviz  # type: ignore
# except Exception:
#     clean_label = None  # type: ignore
#     normalize_icon_for_graphviz = None  # type: ignore

# V_NS = "http://schemas.microsoft.com/office/visio/2012/main"
# R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
# PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
# VISIO_REL_NS = "http://schemas.microsoft.com/visio/2010/relationships"
# SVG_NS = "http://www.w3.org/2000/svg"
# XLINK_NS = "http://www.w3.org/1999/xlink"
# PT_PER_INCH = 72.0
# Matrix = Tuple[float, float, float, float, float, float]
# IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# ET.register_namespace("", V_NS)
# ET.register_namespace("r", R_NS)


# def _v(tag: str) -> str:
#     return f"{{{V_NS}}}{tag}"


# def _r(tag: str) -> str:
#     return f"{{{R_NS}}}{tag}"


# def _svg(tag: str) -> str:
#     return f"{{{SVG_NS}}}{tag}"


# def _xlink(tag: str) -> str:
#     return f"{{{XLINK_NS}}}{tag}"


# @dataclass
# class VisioExportOptions:
#     page_name: str = "Diagram"
#     page_width_in: Optional[float] = None
#     page_height_in: Optional[float] = None
#     include_visual_background: bool = False
#     include_editable_overlay: bool = True
#     lock_visual_background: bool = False
#     overlay_boxes_visible: bool = True
#     overlay_arrows_visible: bool = True
#     overlay_text_visible: bool = False
#     include_icons: bool = True
#     include_flow_legend: bool = True
#     legend_on_separate_page: bool = False
#     legend_items: Optional[List[Tuple[str, str]]] = None
#     node_font_size_pt: float = 13.0
#     node_text_bold: bool = True
#     connector_arrow_type: int = 4
#     connector_arrow_size: int = 2
#     min_page_width_in: float = 11.0
#     min_page_height_in: float = 8.5
#     fail_on_no_nodes: bool = True
#     vector_icon_grid: int = 26
#     min_node_width_in: float = 1.55
#     min_node_height_in: float = 1.05
#     max_node_width_in: float = 2.45
#     max_node_height_in: float = 1.35
#     min_label_band_height_in: float = 0.36
#     max_icon_size_in: float = 0.52
#     cluster_fill: str = "#EEF6FF"
#     cluster_stroke: str = "#A8C7FA"
#     cluster_text: str = "#174EA6"


# @dataclass
# class DotEdge:
#     source: str
#     target: str
#     color: str
#     label: str


# @dataclass
# class DotMetadata:
#     labels: Dict[str, str]
#     attrs: Dict[str, Dict[str, str]]
#     legend_items: List[Tuple[str, str]]
#     edges: List[DotEdge]


# @dataclass
# class SvgNode:
#     node_id: str
#     label: str
#     bbox: Tuple[float, float, float, float]
#     fill: str
#     stroke: str
#     stroke_width: float = 1.0
#     image_href: str = ""
#     icon_path: str = ""
#     icon_text: str = ""
#     font_color: str = "#000000"


# @dataclass
# class SvgEdge:
#     edge_id: str
#     points: List[Tuple[float, float]]
#     color: str = "#666666"
#     width: float = 1.25


# @dataclass
# class SvgCluster:
#     cluster_id: str
#     label: str
#     bbox: Tuple[float, float, float, float]
#     fill: str = "#EEF6FF"
#     stroke: str = "#A8C7FA"
#     font_color: str = "#174EA6"


# @dataclass
# class SvgDiagram:
#     svg_path: Path
#     width_px: float
#     height_px: float
#     viewbox: Tuple[float, float, float, float]
#     nodes: List[SvgNode]
#     edges: List[SvgEdge]
#     clusters: List[SvgCluster]


# def export_vsdx_from_dot(
#     dot_path: os.PathLike | str,
#     vsdx_path: Optional[os.PathLike | str] = None,
#     *,
#     output_vsdx_path: Optional[os.PathLike | str] = None,
#     svg_path: Optional[os.PathLike | str] = None,
#     png_path: Optional[os.PathLike | str] = None,
#     options: Optional[VisioExportOptions] = None,
#     layout_engine: str = "dot",
#     **_: Any,
# ) -> Path:
#     dot = Path(dot_path)
#     out = Path(output_vsdx_path or vsdx_path or dot.with_suffix(".vsdx"))
#     opts = _normalise_options(options or VisioExportOptions())
#     svg = Path(svg_path) if svg_path else out.with_suffix(".svg")
#     if not svg.exists():
#         _run_graphviz(dot, svg, "svg", layout_engine)
#     if not svg.exists():
#         raise FileNotFoundError(f"SVG source not found for VSDX export: {svg}")
#     metadata = _parse_dot_metadata(dot)
#     opts.legend_items = _dedupe_legend_items(opts.legend_items or []) or metadata.legend_items
#     diagram = SvgParser(svg, metadata, fail_on_no_nodes=opts.fail_on_no_nodes, options=opts).parse()
#     return VsdxWriter(diagram, out, opts).write()


# def export_vsdx_from_svg(
#     svg_path: os.PathLike | str,
#     output_vsdx_path: os.PathLike | str,
#     *,
#     png_path: Optional[os.PathLike | str] = None,
#     options: Optional[VisioExportOptions] = None,
# ) -> Path:
#     opts = _normalise_options(options or VisioExportOptions())
#     diagram = SvgParser(Path(svg_path), DotMetadata({}, {}, [], []), fail_on_no_nodes=opts.fail_on_no_nodes, options=opts).parse()
#     return VsdxWriter(diagram, Path(output_vsdx_path), opts).write()


# def _normalise_options(opts: VisioExportOptions) -> VisioExportOptions:
#     opts.include_icons = True
#     opts.include_flow_legend = True
#     opts.node_font_size_pt = max(float(getattr(opts, "node_font_size_pt", 13.0) or 13.0), 13.0)
#     opts.vector_icon_grid = max(20, min(30, int(getattr(opts, "vector_icon_grid", 26) or 26)))
#     opts.min_node_width_in = max(1.30, float(getattr(opts, "min_node_width_in", 1.55) or 1.55))
#     opts.min_node_height_in = max(0.90, float(getattr(opts, "min_node_height_in", 1.05) or 1.05))
#     opts.max_node_width_in = max(opts.min_node_width_in, float(getattr(opts, "max_node_width_in", 2.45) or 2.45))
#     opts.max_node_height_in = max(opts.min_node_height_in, float(getattr(opts, "max_node_height_in", 1.35) or 1.35))
#     opts.max_icon_size_in = max(0.36, min(0.62, float(getattr(opts, "max_icon_size_in", 0.52) or 0.52)))
#     opts.min_label_band_height_in = max(0.32, min(0.52, float(getattr(opts, "min_label_band_height_in", 0.36) or 0.36)))
#     return opts


# class SvgParser:
#     def __init__(self, svg_path: Path, dot_metadata: DotMetadata, fail_on_no_nodes: bool = True, options: Optional[VisioExportOptions] = None):
#         self.svg_path = Path(svg_path)
#         self.dot_metadata = dot_metadata
#         self.fail_on_no_nodes = fail_on_no_nodes
#         self.options = options or VisioExportOptions()
#         self.root = ET.parse(str(svg_path)).getroot()
#         self.viewbox = self._viewbox()
#         self.width_px = _num(self.root.get("width"), self.viewbox[2])
#         self.height_px = _num(self.root.get("height"), self.viewbox[3])

#     def parse(self) -> SvgDiagram:
#         nodes: List[SvgNode] = []
#         edges: List[SvgEdge] = []
#         clusters: List[SvgCluster] = []
#         for elem, matrix, _parents in _iter_svg(self.root):
#             if _local(elem.tag) != "g":
#                 continue
#             classes = _class_tokens(elem.get("class"))
#             if self._is_cluster_group(elem, classes):
#                 cluster = self._parse_cluster(elem, matrix)
#                 if cluster and not self._is_graph_sized(cluster.bbox):
#                     clusters.append(cluster)
#             elif "node" in classes:
#                 node = self._parse_node(elem, matrix)
#                 if node and not self._is_graph_sized(node.bbox):
#                     nodes.append(node)
#             elif "edge" in classes:
#                 edge = self._parse_edge(elem, matrix)
#                 if edge:
#                     edges.append(edge)
#         clusters = _filter_clusters(clusters, nodes)
#         if not nodes and self.fail_on_no_nodes:
#             raise RuntimeError(f"VSDX export failed: no editable node bodies detected from SVG: {self.svg_path}")
#         return SvgDiagram(self.svg_path, self.width_px, self.height_px, self.viewbox, nodes, edges, clusters)

#     def _viewbox(self) -> Tuple[float, float, float, float]:
#         raw = self.root.get("viewBox") or self.root.get("viewbox")
#         if raw:
#             vals = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)]
#             if len(vals) >= 4:
#                 return vals[0], vals[1], vals[2], vals[3]
#         return 0.0, 0.0, _num(self.root.get("width"), 1000.0), _num(self.root.get("height"), 800.0)

#     def _is_graph_sized(self, bbox: Tuple[float, float, float, float]) -> bool:
#         x1, y1, x2, y2 = bbox
#         return abs((x2 - x1) * (y2 - y1)) > max(1.0, self.viewbox[2] * self.viewbox[3]) * 0.85

#     def _is_cluster_group(self, elem: ET.Element, classes: List[str]) -> bool:
#         if "cluster" in classes:
#             return True
#         if any(token in classes for token in ("node", "edge")):
#             return False
#         title = (_title(elem) or "").lower()
#         if title.startswith("cluster") or title.startswith("subgraph"):
#             return True
#         # Generic labelled container group: has visible text and a large rectangle/polygon.
#         label = ""
#         has_body = False
#         for child in elem.iter():
#             tag = _local(child.tag)
#             if tag == "text" and _cleanup_visible_text(_read_text(child)):
#                 label = _cleanup_visible_text(_read_text(child))
#             elif tag in {"polygon", "rect"}:
#                 has_body = True
#         return bool(label and has_body)

#     def _parse_cluster(self, group: ET.Element, matrix: Matrix) -> Optional[SvgCluster]:
#         title = _title(group) or f"cluster_{id(group)}"
#         label = ""
#         bodies: List[Tuple[float, float, float, float, str, str]] = []
#         for child in group.iter():
#             tag = _local(child.tag)
#             style = _style(child)
#             fill = _colour(style.get("fill") or child.get("fill"), self.options.cluster_fill)
#             stroke = _colour(style.get("stroke") or child.get("stroke"), self.options.cluster_stroke)
#             points: List[Tuple[float, float]] = []
#             if tag == "polygon":
#                 points = [_apply(matrix, x, y) for x, y in _points(child.get("points") or "")]
#             elif tag == "rect":
#                 points = _rect_points(child, matrix)
#             elif tag == "text":
#                 t = _cleanup_visible_text(_read_text(child))
#                 if t:
#                     label = t
#             if points:
#                 x1, y1, x2, y2 = _bbox(points)
#                 if abs(x2 - x1) > 15 and abs(y2 - y1) > 15:
#                     bodies.append((x1, y1, x2, y2, fill, stroke))
#         if not bodies:
#             return None
#         body = max(bodies, key=lambda b: abs((b[2] - b[0]) * (b[3] - b[1])))
#         fill = body[4]
#         if fill.upper() in {"#FFFFFF", "#000000"} or _is_near_black(fill):
#             fill = self.options.cluster_fill
#         stroke = body[5]
#         if _is_near_black(stroke):
#             stroke = self.options.cluster_stroke
#         return SvgCluster(title, label or title, (body[0], body[1], body[2], body[3]), fill, stroke, self.options.cluster_text)

#     def _parse_node(self, group: ET.Element, matrix: Matrix) -> Optional[SvgNode]:
#         title = _title(group) or f"node_{id(group)}"
#         dot_attrs = self.dot_metadata.attrs.get(title, {})
#         dot_label = self.dot_metadata.labels.get(title, title)
#         base_style = _node_visual_style(dot_label, title, dot_attrs)
#         bodies: List[Tuple[float, float, float, float, str, str, float, str]] = []
#         texts: List[str] = []
#         image_candidates: List[str] = []
#         if dot_attrs.get("image"):
#             image_candidates.append(dot_attrs.get("image", ""))
#         for child in group.iter():
#             tag = _local(child.tag)
#             style = _style(child)
#             fill = _colour(style.get("fill") or child.get("fill") or dot_attrs.get("fillcolor"), base_style["fill"])
#             stroke = _colour(style.get("stroke") or child.get("stroke") or dot_attrs.get("color"), base_style["border"])
#             stroke_width = max(0.75, _num(style.get("stroke-width") or child.get("stroke-width") or dot_attrs.get("penwidth"), 1.0))
#             points: List[Tuple[float, float]] = []
#             image_href = ""
#             if tag == "polygon":
#                 points = [_apply(matrix, x, y) for x, y in _points(child.get("points") or "")]
#             elif tag == "rect":
#                 points = _rect_points(child, matrix)
#             elif tag == "ellipse":
#                 cx, cy = _num(child.get("cx"), 0.0), _num(child.get("cy"), 0.0)
#                 rx, ry = _num(child.get("rx"), 0.0), _num(child.get("ry"), 0.0)
#                 points = [_apply(matrix, cx - rx, cy - ry), _apply(matrix, cx + rx, cy + ry)]
#             elif tag == "image":
#                 image_href = _svg_href(child)
#                 if image_href:
#                     image_candidates.append(image_href)
#                 x, y = _num(child.get("x"), 0.0), _num(child.get("y"), 0.0)
#                 width, height = _num(child.get("width"), 0.0), _num(child.get("height"), 0.0)
#                 if width > 0 and height > 0:
#                     points = [_apply(matrix, x, y), _apply(matrix, x + width, y), _apply(matrix, x + width, y + height), _apply(matrix, x, y + height)]
#                     fill, stroke = base_style["fill"], base_style["border"]
#             elif tag == "text":
#                 t = _cleanup_visible_text(_read_text(child))
#                 if t:
#                     texts.append(t)
#             if points:
#                 x1, y1, x2, y2 = _bbox(points)
#                 if abs(x2 - x1) > 4 and abs(y2 - y1) > 4 and not self._is_graph_sized((x1, y1, x2, y2)):
#                     if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#                         fill, stroke = base_style["fill"], base_style["border"]
#                     bodies.append((x1, y1, x2, y2, fill, stroke, stroke_width, image_href))
#         label = _cleanup_visible_text(" ".join(texts) or dot_label)
#         if not bodies:
#             return None
#         body = max(bodies, key=lambda b: abs((b[2] - b[0]) * (b[3] - b[1])))
#         fill, stroke = body[4], body[5]
#         if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#             fill, stroke = base_style["fill"], base_style["border"]
#         icon_path = _resolve_icon_path(label)
#         if not icon_path:
#             icon_path = _extract_icon_from_candidates(image_candidates, self.svg_path.parent, label)
#         return SvgNode(title, label or title, (body[0], body[1], body[2], body[3]), fill, stroke, body[6], body[7], icon_path, _icon_abbrev(label), base_style.get("font", "#000000"))

#     def _parse_edge(self, group: ET.Element, matrix: Matrix) -> Optional[SvgEdge]:
#         title = _title(group) or f"edge_{id(group)}"
#         color = "#666666"
#         width = 1.25
#         all_points: List[Tuple[float, float]] = []
#         for path in group.findall(f".//{_svg('path')}"):
#             style = _style(path)
#             color = _colour(style.get("stroke") or path.get("stroke"), color)
#             width = max(1.0, _num(style.get("stroke-width") or path.get("stroke-width"), width))
#             path_points = [_apply(matrix, x, y) for x, y in _path_points(path.get("d") or "")]
#             if path_points:
#                 all_points = path_points
#                 break
#         for poly in group.findall(f".//{_svg('polygon')}"):
#             style = _style(poly)
#             color = _colour(style.get("fill") or style.get("stroke") or poly.get("fill") or poly.get("stroke"), color)
#             poly_points = [_apply(matrix, x, y) for x, y in _points(poly.get("points") or "")]
#             if poly_points:
#                 all_points.append((sum(x for x, _ in poly_points) / len(poly_points), sum(y for _, y in poly_points) / len(poly_points)))
#         simple = _simplify_route(all_points)
#         return SvgEdge(title, simple, color, width) if len(simple) >= 2 else None


# class VsdxWriter:
#     def __init__(self, diagram: SvgDiagram, output_path: Path, options: VisioExportOptions):
#         self.diagram = diagram
#         self.output_path = Path(output_path)
#         self.options = options
#         self.shape_id = 100
#         self.vb_x, self.vb_y, self.vb_w, self.vb_h = diagram.viewbox
#         self.vb_w, self.vb_h = max(1.0, self.vb_w), max(1.0, self.vb_h)
#         base_w = float(options.page_width_in or max(options.min_page_width_in, diagram.width_px / PT_PER_INCH))
#         base_h = float(options.page_height_in or max(options.min_page_height_in, diagram.height_px / PT_PER_INCH))
#         self.legend_items = _dedupe_legend_items(options.legend_items or []) if options.include_flow_legend else []
#         self.legend_space = max(0.0, 0.36 * (len(self.legend_items) + 2) + 0.40) if self.legend_items else 0.0
#         self.page_w = base_w
#         self.page_h = base_h + self.legend_space
#         available_h = max(1.0, self.page_h - self.legend_space - 0.35)
#         self.scale = min(self.page_w / self.vb_w, available_h / self.vb_h)
#         self.offset_x = (self.page_w - self.vb_w * self.scale) / 2.0
#         self.offset_y = self.legend_space + (available_h - self.vb_h * self.scale) / 2.0

#     def write(self) -> Path:
#         self.output_path.parent.mkdir(parents=True, exist_ok=True)
#         tmp = self.output_path.with_suffix(".tmp.vsdx")
#         if tmp.exists():
#             tmp.unlink()
#         template = self._template_path()
#         if template:
#             shutil.copyfile(template, tmp)
#             self._rewrite_template(tmp)
#         else:
#             self._write_minimal(tmp)
#         tmp.replace(self.output_path)
#         self._validate_package(self.output_path)
#         return self.output_path

#     def _template_path(self) -> Optional[Path]:
#         try:
#             import vsdx  # type: ignore
#             path = Path(vsdx.__file__).parent / "media" / "media.vsdx"
#             return path if path.exists() else None
#         except Exception:
#             return None

#     def _rewrite_template(self, path: Path) -> None:
#         replacements = {
#             "visio/pages/page1.xml": self._page_xml().encode("utf-8"),
#             "visio/pages/pages.xml": self._pages_xml().encode("utf-8"),
#             "visio/windows.xml": self._windows_xml().encode("utf-8"),
#             "visio/pages/_rels/page1.xml.rels": self._page_rels_xml().encode("utf-8"),
#         }
#         original = path.with_suffix(".orig.vsdx")
#         path.replace(original)
#         try:
#             with zipfile.ZipFile(original, "r") as zin, zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
#                 seen = set()
#                 for item in zin.infolist():
#                     zout.writestr(item.filename, self._content_types_xml() if item.filename == "[Content_Types].xml" else replacements.get(item.filename, zin.read(item.filename)))
#                     seen.add(item.filename)
#                 for name, data in replacements.items():
#                     if name not in seen:
#                         zout.writestr(name, data)
#         finally:
#             try:
#                 original.unlink()
#             except Exception:
#                 pass

#     def _write_minimal(self, path: Path) -> None:
#         with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
#             z.writestr("[Content_Types].xml", self._content_types_xml())
#             z.writestr("_rels/.rels", self._root_rels_xml())
#             z.writestr("visio/document.xml", self._document_xml())
#             z.writestr("visio/_rels/document.xml.rels", self._document_rels_xml())
#             z.writestr("visio/masters/masters.xml", self._masters_xml())
#             z.writestr("visio/pages/pages.xml", self._pages_xml())
#             z.writestr("visio/pages/_rels/pages.xml.rels", self._pages_rels_xml())
#             z.writestr("visio/pages/page1.xml", self._page_xml())
#             z.writestr("visio/pages/_rels/page1.xml.rels", self._page_rels_xml())
#             z.writestr("visio/windows.xml", self._windows_xml())
#             z.writestr("docProps/app.xml", self._app_xml())
#             z.writestr("docProps/core.xml", self._core_xml())

#     def _page_xml(self) -> str:
#         root = ET.Element(_v("PageContents"), {"xml:space": "preserve"})
#         shapes = ET.SubElement(root, _v("Shapes"))
#         for cluster in self.diagram.clusters:
#             self._append_cluster_shape(shapes, cluster)
#         for edge in self.diagram.edges:
#             self._append_edge_shape(shapes, edge)
#         for node in self.diagram.nodes:
#             self._append_card_shape(shapes, node)
#         if self.legend_items:
#             self._append_legend_items(shapes, self.legend_items)
#         page_sheet = ET.SubElement(root, _v("PageSheet"), {"LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._cell(page_sheet, "PageWidth", self.page_w)
#         self._cell(page_sheet, "PageHeight", self.page_h)
#         self._cell(page_sheet, "DrawingScale", 1)
#         self._cell(page_sheet, "PageScale", 1)
#         return _xml(root)

#     def _append_cluster_shape(self, parent: ET.Element, cluster: SvgCluster) -> None:
#         x1, y1, x2, y2 = cluster.bbox
#         w, h = self._size(x2 - x1, y2 - y1)
#         cx, cy = self._xy((x1 + x2) / 2.0, (y1 + y2) / 2.0)
#         body = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(cluster.cluster_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(body, cx, cy, w, h)
#         self._color_cell(body, "FillForegnd", _colour(cluster.fill, self.options.cluster_fill))
#         self._color_cell(body, "FillBkgnd", _colour(cluster.fill, self.options.cluster_fill))
#         self._cell(body, "FillPattern", 1)
#         self._cell(body, "FillForegndTrans", 15)
#         self._color_cell(body, "LineColor", _colour(cluster.stroke, self.options.cluster_stroke))
#         self._cell(body, "LineWeight", _pt(1.5))
#         self._cell(body, "Rounding", 0.12)
#         self._rectangle_geometry(body)
#         ET.SubElement(body, _v("Text"))
#         # Header text is separate and top-aligned so it never overlaps content inside the cluster.
#         title_h = 0.24
#         title = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(cluster.cluster_id + "_title"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(title, cx, cy + h / 2.0 - title_h / 2.0 - 0.04, max(0.6, w - 0.24), title_h)
#         self._cell(title, "LinePattern", 0)
#         self._cell(title, "FillPattern", 0)
#         self._character_section(title, 12.5, True, cluster.font_color)
#         self._paragraph_section(title, 1)
#         self._text_block(title, left_margin=0.02)
#         self._rectangle_geometry(title, no_line=True, no_fill=True)
#         ET.SubElement(title, _v("Text")).text = _cleanup_visible_text(cluster.label)

#     def _append_card_shape(self, parent: ET.Element, node: SvgNode) -> None:
#         x1, y1, x2, y2 = node.bbox
#         raw_w, raw_h = self._size(x2 - x1, y2 - y1)
#         cx, cy = self._xy((x1 + x2) / 2.0, (y1 + y2) / 2.0)
#         label = _wrap_label(node.label)
#         line_count = max(1, label.count("\n") + 1)
#         label_len = max(len(part) for part in label.split("\n") if part)
#         label_w_need = min(self.options.max_node_width_in, max(self.options.min_node_width_in, label_len * 0.075 + 0.55))
#         min_w = max(self.options.min_node_width_in, min(self.options.max_node_width_in, self.page_w * 0.11), label_w_need)
#         label_h = max(self.options.min_label_band_height_in, min(0.54, 0.23 * line_count + 0.12))
#         min_h = max(self.options.min_node_height_in, label_h + 0.70)
#         w = max(raw_w, min_w)
#         h = max(raw_h, min_h)
#         top_margin = max(0.08, h * 0.07)
#         gap_above_label = max(0.08, h * 0.07)
#         available_icon_h = max(0.22, h - label_h - top_margin - gap_above_label - 0.12)
#         icon_size = max(0.32, min(self.options.max_icon_size_in, available_icon_h, w * 0.25))
#         icon_cy = cy + h / 2.0 - top_margin - icon_size / 2.0
#         band_cy = cy - h / 2.0 + label_h / 2.0 + 0.06
#         body = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(body, cx, cy, w, h)
#         self._color_cell(body, "FillForegnd", node.fill)
#         self._color_cell(body, "FillBkgnd", node.fill)
#         self._cell(body, "FillPattern", 1)
#         self._cell(body, "LinePattern", 1)
#         self._color_cell(body, "LineColor", node.stroke)
#         self._cell(body, "LineWeight", _pt(max(1.0, node.stroke_width)))
#         self._cell(body, "Rounding", 0.08)
#         self._rectangle_geometry(body)
#         ET.SubElement(body, _v("Text"))
#         band = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id + "_label_band"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(band, cx, band_cy, max(0.45, w - 0.18), label_h)
#         self._color_cell(band, "FillForegnd", "#FFFFFF")
#         self._color_cell(band, "FillBkgnd", "#FFFFFF")
#         self._cell(band, "FillPattern", 1)
#         self._cell(band, "LinePattern", 0)
#         self._cell(band, "Rounding", 0.05)
#         font_size = max(9.5, min(12.5, self.options.node_font_size_pt - max(0, line_count - 1) * 1.2))
#         self._character_section(band, font_size, True, node.font_color)
#         self._paragraph_section(band, 1)
#         self._text_block(band, left_margin=0.035)
#         self._rectangle_geometry(band, no_line=True)
#         ET.SubElement(band, _v("Text")).text = label
#         badge = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id + "_icon_badge"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(badge, cx, icon_cy, icon_size, icon_size)
#         self._color_cell(badge, "FillForegnd", _lighten(node.stroke, 0.88))
#         self._color_cell(badge, "FillBkgnd", _lighten(node.stroke, 0.88))
#         self._cell(badge, "FillPattern", 1)
#         self._cell(badge, "LinePattern", 1)
#         self._color_cell(badge, "LineColor", node.stroke)
#         self._cell(badge, "LineWeight", _pt(0.75))
#         self._cell(badge, "Rounding", 0.04)
#         self._rectangle_geometry(badge)
#         if self.options.include_icons and node.icon_path and _can_vectorize_icon(node.icon_path):
#             self._append_icon_vector_mosaic(parent, cx, icon_cy, icon_size * 0.86, node.icon_path, node.node_id)
#             ET.SubElement(badge, _v("Text"))
#         else:
#             self._character_section(badge, 8.5, True, node.stroke)
#             self._paragraph_section(badge, 1)
#             self._text_block(badge, left_margin=0.01)
#             ET.SubElement(badge, _v("Text")).text = node.icon_text

#     def _append_icon_vector_mosaic(self, parent: ET.Element, cx: float, cy: float, size: float, icon_path: str, node_id: str) -> None:
#         cells = _icon_mosaic_cells(icon_path, grid=self.options.vector_icon_grid)
#         if not cells:
#             return
#         grid = max(max(x for x, _, _ in cells) + 1, max(y for _, y, _ in cells) + 1)
#         cell = size / grid
#         origin_x = cx - size / 2.0
#         origin_y = cy + size / 2.0
#         for ix, iy, color in cells:
#             px = origin_x + (ix + 0.5) * cell
#             py = origin_y - (iy + 0.5) * cell
#             shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(f"{node_id}_icon_px"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#             self._base_shape_cells(shape, px, py, cell * 1.12, cell * 1.12)
#             self._color_cell(shape, "FillForegnd", color)
#             self._color_cell(shape, "FillBkgnd", color)
#             self._cell(shape, "FillPattern", 1)
#             self._cell(shape, "LinePattern", 0)
#             self._rectangle_geometry(shape, no_line=True)
#             ET.SubElement(shape, _v("Text"))

#     def _append_edge_shape(self, parent: ET.Element, edge: SvgEdge) -> None:
#         points = [self._xy(x, y) for x, y in edge.points]
#         if len(points) < 2:
#             return
#         min_x, min_y, max_x, max_y = _bbox(points)
#         w, h = max(0.01, max_x - min_x), max(0.01, max_y - min_y)
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(edge.edge_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, min_x + w / 2.0, min_y + h / 2.0, w, h)
#         self._color_cell(shape, "LineColor", edge.color)
#         self._cell(shape, "LineWeight", _pt(max(1.25, edge.width)))
#         self._cell(shape, "LinePattern", 1)
#         self._cell(shape, "BeginArrow", 0)
#         self._cell(shape, "EndArrow", self.options.connector_arrow_type)
#         self._cell(shape, "EndArrowSize", self.options.connector_arrow_size)
#         self._line_geometry(shape, points, min_x, min_y, w, h)
#         ET.SubElement(shape, _v("Text"))

#     def _append_legend_items(self, parent: ET.Element, items: List[Tuple[str, str]]) -> None:
#         items = _dedupe_legend_items(items)
#         if not items:
#             return
#         x = 0.65
#         y = 0.38 + 0.34 * len(items)
#         self._append_free_text(parent, "Flow Legend", x, y + 0.35, 11.5, True)
#         for idx, (color, label) in enumerate(items):
#             row_y = y - 0.34 * idx
#             self._append_page_line(parent, x, row_y, x + 0.70, row_y, color)
#             self._append_free_text(parent, label, x + 0.88, row_y, 8.8, False)

#     def _append_free_text(self, parent: ET.Element, text: str, x: float, y: float, font_pt: float, bold: bool) -> None:
#         text = _cleanup_visible_text(text)
#         w, h = max(0.8, min(11.5, len(text) * font_pt / 72.0 * 0.50)), 0.25
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(text[:40] or "Text"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, x + w / 2.0, y, w, h)
#         self._cell(shape, "LinePattern", 0)
#         self._cell(shape, "FillPattern", 0)
#         self._character_section(shape, font_pt, bold, "#000000")
#         self._paragraph_section(shape, 0)
#         self._rectangle_geometry(shape, no_line=True, no_fill=True)
#         ET.SubElement(shape, _v("Text")).text = text

#     def _append_page_line(self, parent: ET.Element, x1: float, y1: float, x2: float, y2: float, color: str) -> None:
#         min_x, min_y, max_x, max_y = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
#         w, h = max(0.01, max_x - min_x), max(0.01, max_y - min_y)
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": "Legend_Line", "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, min_x + w / 2.0, min_y + h / 2.0, w, h)
#         self._color_cell(shape, "LineColor", color)
#         self._cell(shape, "LineWeight", _pt(1.45))
#         self._cell(shape, "EndArrow", 4)
#         self._line_geometry(shape, [(x1, y1), (x2, y2)], min_x, min_y, w, h)
#         ET.SubElement(shape, _v("Text"))

#     def _base_shape_cells(self, shape: ET.Element, cx: float, cy: float, w: float, h: float) -> None:
#         self._cell(shape, "PinX", cx)
#         self._cell(shape, "PinY", cy)
#         self._cell(shape, "Width", w)
#         self._cell(shape, "Height", h)
#         self._cell(shape, "LocPinX", w / 2.0, "Width*0.5")
#         self._cell(shape, "LocPinY", h / 2.0, "Height*0.5")
#         self._cell(shape, "Angle", 0)
#         self._cell(shape, "FlipX", 0)
#         self._cell(shape, "FlipY", 0)
#         self._cell(shape, "ResizeMode", 0)

#     def _character_section(self, shape: ET.Element, font_pt: float, bold: bool, color: str) -> None:
#         section = ET.SubElement(shape, _v("Section"), {"N": "Character"})
#         row = ET.SubElement(section, _v("Row"), {"IX": "0"})
#         self._cell(row, "Size", _pt(font_pt))
#         self._cell(row, "Style", 17 if bold else 0)
#         self._color_cell(row, "Color", color)

#     def _paragraph_section(self, shape: ET.Element, align: int) -> None:
#         section = ET.SubElement(shape, _v("Section"), {"N": "Paragraph"})
#         row = ET.SubElement(section, _v("Row"), {"IX": "0"})
#         self._cell(row, "HorzAlign", align)

#     def _text_block(self, shape: ET.Element, left_margin: float = 0.06) -> None:
#         block = ET.SubElement(shape, _v("TextBlock"))
#         self._cell(block, "VerticalAlign", 1)
#         self._cell(block, "LeftMargin", left_margin)
#         self._cell(block, "RightMargin", 0.06)
#         self._cell(block, "TopMargin", 0.03)
#         self._cell(block, "BottomMargin", 0.03)

#     def _rectangle_geometry(self, shape: ET.Element, *, no_line: bool = False, no_fill: bool = False) -> None:
#         geom = ET.SubElement(shape, _v("Section"), {"N": "Geometry", "IX": "0"})
#         self._cell(geom, "NoFill", 1 if no_fill else 0)
#         self._cell(geom, "NoLine", 1 if no_line else 0)
#         for row_type, ix, x, y in [("RelMoveTo", 1, 0, 0), ("RelLineTo", 2, 1, 0), ("RelLineTo", 3, 1, 1), ("RelLineTo", 4, 0, 1), ("RelLineTo", 5, 0, 0)]:
#             row = ET.SubElement(geom, _v("Row"), {"T": row_type, "IX": str(ix)})
#             self._cell(row, "X", x)
#             self._cell(row, "Y", y)

#     def _line_geometry(self, shape: ET.Element, points: List[Tuple[float, float]], min_x: float, min_y: float, w: float, h: float) -> None:
#         geom = ET.SubElement(shape, _v("Section"), {"N": "Geometry", "IX": "0"})
#         self._cell(geom, "NoFill", 1)
#         self._cell(geom, "NoLine", 0)
#         for ix, (x, y) in enumerate(points, start=1):
#             row = ET.SubElement(geom, _v("Row"), {"T": "RelMoveTo" if ix == 1 else "RelLineTo", "IX": str(ix)})
#             self._cell(row, "X", 0 if w <= 0 else (x - min_x) / w)
#             self._cell(row, "Y", 0 if h <= 0 else (y - min_y) / h)

#     def _pages_xml(self) -> str:
#         root = ET.Element(_v("Pages"), {"xml:space": "preserve"})
#         page = ET.SubElement(root, _v("Page"), {"ID": "0", "NameU": self.options.page_name or "Diagram", "Name": self.options.page_name or "Diagram", "ViewScale": "1", "ViewCenterX": str(self.page_w / 2.0), "ViewCenterY": str(self.page_h / 2.0)})
#         sheet = ET.SubElement(page, _v("PageSheet"), {"LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._cell(sheet, "PageWidth", self.page_w)
#         self._cell(sheet, "PageHeight", self.page_h)
#         ET.SubElement(page, _v("Rel"), {_r("id"): "rId1"})
#         return _xml(root)

#     def _windows_xml(self) -> str:
#         root = ET.Element(_v("Windows"), {"xml:space": "preserve"})
#         win = ET.SubElement(root, _v("Window"), {"ID": "0", "WindowType": "Drawing", "ContainerType": "Page", "Container": "0"})
#         self._cell(win, "ViewScale", 1)
#         self._cell(win, "ViewCenterX", self.page_w / 2.0)
#         self._cell(win, "ViewCenterY", self.page_h / 2.0)
#         return _xml(root)

#     def _content_types_xml(self) -> str:
#         root = ET.Element("Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"})
#         for ext, ctype in {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}.items():
#             ET.SubElement(root, "Default", {"Extension": ext, "ContentType": ctype})
#         for part, ctype in {
#             "/visio/document.xml": "application/vnd.ms-visio.drawing.main+xml",
#             "/visio/pages/pages.xml": "application/vnd.ms-visio.pages+xml",
#             "/visio/pages/page1.xml": "application/vnd.ms-visio.page+xml",
#             "/visio/windows.xml": "application/vnd.ms-visio.windows+xml",
#             "/visio/masters/masters.xml": "application/vnd.ms-visio.masters+xml",
#             "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
#             "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
#         }.items():
#             ET.SubElement(root, "Override", {"PartName": part, "ContentType": ctype})
#         return _xml_plain(root)

#     def _root_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/document", "Target": "visio/document.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId2", "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "Target": "docProps/core.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId3", "Type": f"{R_NS}/extended-properties", "Target": "docProps/app.xml"})
#         return _xml_plain(root)

#     def _document_xml(self) -> str:
#         root = ET.Element(_v("VisioDocument"), {"xml:space": "preserve"})
#         ET.SubElement(root, _v("DocumentSettings"))
#         return _xml(root)

#     def _document_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/masters", "Target": "masters/masters.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId2", "Type": f"{VISIO_REL_NS}/pages", "Target": "pages/pages.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId3", "Type": f"{VISIO_REL_NS}/windows", "Target": "windows.xml"})
#         return _xml_plain(root)

#     def _pages_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/page", "Target": "page1.xml"})
#         return _xml_plain(root)

#     def _page_rels_xml(self) -> str:
#         return _xml_plain(ET.Element("Relationships", {"xmlns": PKG_REL_NS}))

#     def _masters_xml(self) -> str:
#         return _xml(ET.Element(_v("Masters"), {"xml:space": "preserve"}))

#     def _app_xml(self) -> str:
#         root = ET.Element("Properties", {"xmlns": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"})
#         ET.SubElement(root, "Application").text = "Microsoft Visio"
#         return _xml_plain(root)

#     def _core_xml(self) -> str:
#         root = ET.Element("cp:coreProperties", {"xmlns:cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties", "xmlns:dc": "http://purl.org/dc/elements/1.1/"})
#         ET.SubElement(root, "dc:title").text = self.options.page_name or "Diagram"
#         return _xml_plain(root)

#     def _xy(self, x: float, y: float) -> Tuple[float, float]:
#         return self.offset_x + (x - self.vb_x) * self.scale, self.offset_y + (self.vb_h - (y - self.vb_y)) * self.scale

#     def _size(self, width: float, height: float) -> Tuple[float, float]:
#         return max(0.02, abs(width) * self.scale), max(0.02, abs(height) * self.scale)

#     def _next_id(self) -> int:
#         self.shape_id += 1
#         return self.shape_id

#     def _cell(self, parent: ET.Element, name: str, value: Any, formula: Optional[str] = None) -> None:
#         attrs = {"N": name, "V": str(value)}
#         if formula:
#             attrs["F"] = formula
#         ET.SubElement(parent, _v("Cell"), attrs)

#     def _color_cell(self, parent: ET.Element, name: str, color: str) -> None:
#         r, g, b = _rgb(color)
#         ET.SubElement(parent, _v("Cell"), {"N": name, "V": _colour(color, "#000000"), "F": f"RGB({r},{g},{b})"})

#     def _validate_package(self, path: Path) -> None:
#         required = {"[Content_Types].xml", "_rels/.rels", "visio/document.xml", "visio/pages/pages.xml", "visio/pages/page1.xml", "visio/pages/_rels/pages.xml.rels", "visio/windows.xml"}
#         with zipfile.ZipFile(path, "r") as z:
#             missing = sorted(required - set(z.namelist()))
#             if missing:
#                 raise RuntimeError(f"Generated VSDX package is missing required parts: {missing}")


# # =============================================================================
# # Helpers
# # =============================================================================
# def _parse_dot_metadata(dot_path: Path) -> DotMetadata:
#     labels: Dict[str, str] = {}
#     attrs_by_node: Dict[str, Dict[str, str]] = {}
#     edges: List[DotEdge] = []
#     if not dot_path.exists():
#         return DotMetadata(labels, attrs_by_node, [], [])
#     statements = _split_dot_statements(dot_path.read_text(encoding="utf-8", errors="replace"))
#     for statement in statements:
#         stripped = statement.strip().rstrip(";")
#         if not stripped or "->" in stripped or "--" in stripped or "[" not in stripped or "]" not in stripped:
#             continue
#         if stripped.lower().startswith(("digraph", "graph", "subgraph", "node ", "edge ")):
#             continue
#         prefix, raw_attrs, _ = _split_dot_attr_statement(stripped)
#         node_id = _clean_dot_id(prefix)
#         if not node_id:
#             continue
#         attrs = _parse_dot_attrs(raw_attrs)
#         attrs_by_node[node_id] = attrs
#         labels[node_id] = _clean_dot_label(attrs.get("label") or attrs.get("xlabel") or attrs.get("tooltip") or node_id) or node_id
#     for statement in statements:
#         stripped = statement.strip().rstrip(";")
#         if not stripped or ("->" not in stripped and "--" not in stripped):
#             continue
#         endpoints = _extract_edge_endpoints(stripped)
#         if len(endpoints) < 2:
#             continue
#         raw_attrs = ""
#         if "[" in stripped and "]" in stripped:
#             _, raw_attrs, _ = _split_dot_attr_statement(stripped)
#         attrs = _parse_dot_attrs(raw_attrs)
#         color = _colour(attrs.get("color"), "#666666")
#         label = _clean_dot_label(attrs.get("label") or attrs.get("xlabel") or "") or _make_edge_fallback_label(endpoints[0], endpoints[-1], labels)
#         edges.append(DotEdge(endpoints[0], endpoints[-1], color, label))
#     return DotMetadata(labels, attrs_by_node, _dedupe_legend_items([(e.color, e.label) for e in edges if e.label]), edges)


# def _filter_clusters(clusters: List[SvgCluster], nodes: List[SvgNode]) -> List[SvgCluster]:
#     if not clusters:
#         return []
#     result: List[SvgCluster] = []
#     seen = set()
#     node_boxes = [n.bbox for n in nodes]
#     for c in sorted(clusters, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]), reverse=True):
#         if not _cleanup_visible_text(c.label):
#             continue
#         x1, y1, x2, y2 = c.bbox
#         contains_node = any(x1 <= (a + b) / 2 <= x2 and y1 <= (d + e) / 2 <= y2 for a, d, b, e in node_boxes)
#         if not contains_node:
#             continue
#         key = (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), c.label.lower())
#         if key in seen:
#             continue
#         seen.add(key)
#         result.append(c)
#     return result


# def _split_dot_statements(text: str) -> List[str]:
#     statements: List[str] = []
#     current: List[str] = []
#     in_quote = False
#     in_html = False
#     bracket_depth = 0
#     escape = False
#     for char in text:
#         current.append(char)
#         if escape:
#             escape = False
#             continue
#         if char == "\\":
#             escape = True
#             continue
#         if char == '"' and not in_html:
#             in_quote = not in_quote
#             continue
#         if char == "<" and not in_quote:
#             in_html = True
#         elif char == ">" and in_html and not in_quote:
#             in_html = False
#         elif char == "[" and not in_quote and not in_html:
#             bracket_depth += 1
#         elif char == "]" and not in_quote and not in_html:
#             bracket_depth = max(0, bracket_depth - 1)
#         elif char == ";" and not in_quote and not in_html and bracket_depth == 0:
#             st = "".join(current).strip()
#             if st:
#                 statements.append(st)
#             current = []
#     tail = "".join(current).strip()
#     if tail:
#         statements.append(tail)
#     return statements


# def _split_dot_attr_statement(statement: str) -> Tuple[str, str, str]:
#     start = statement.find("[")
#     end = statement.rfind("]")
#     if start < 0 or end < start:
#         return statement, "", ""
#     return statement[:start].strip(), statement[start + 1:end].strip(), statement[end + 1:].strip()


# def _parse_dot_attrs(raw: str) -> Dict[str, str]:
#     attrs: Dict[str, str] = {}
#     pattern = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("(?:\\.|[^"])*"|<.*?>|[^,\]]+)', flags=re.S)
#     for key, value in pattern.findall(raw or ""):
#         attrs[key.strip().lower()] = _clean_dot_label(value)
#     return attrs


# def _extract_edge_endpoints(statement: str) -> List[str]:
#     no_attrs = re.sub(r"\[.*?\]", "", statement, flags=re.S).strip().rstrip(";")
#     return [_clean_dot_id(part) for part in re.split(r"->|--", no_attrs) if _clean_dot_id(part)]


# def _clean_dot_id(value: str) -> str:
#     return _cleanup_visible_text(str(value or "").strip().rstrip(";").strip().strip('"').strip("'"))


# def _clean_dot_label(value: str) -> str:
#     return _cleanup_visible_text(str(value or "").strip().strip('"').strip("'"))


# def _cleanup_visible_text(value: str) -> str:
#     text = html.unescape(str(value or ""))
#     text = text.replace("\\n", " ").replace("\\l", " ").replace("\\r", " ")
#     text = re.sub(r"\\+", " ", text)
#     text = re.sub(r"<\s*br\s*/?\s*>", " ", text, flags=re.I)
#     text = re.sub(r"</?\s*b\s*>", "", text, flags=re.I)
#     text = re.sub(r"<[^>]+>", "", text)
#     text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
#     text = re.sub(r"\s+", " ", text)
#     return text.strip()


# def _make_edge_fallback_label(source: str, target: str, labels: Dict[str, str]) -> str:
#     src = labels.get(source, source).strip()
#     dst = labels.get(target, target).strip()
#     return f"{src} to {dst}" if src and dst else ""


# def _extract_icon_from_candidates(candidates: List[str], base_dir: Path, label: str) -> str:
#     if Image is None:
#         return ""
#     card = _resolve_first_raster(candidates, base_dir)
#     if not card:
#         return ""
#     try:
#         src = Path(card)
#         out = Path(os.getenv("TMPDIR", "/tmp")) / f"vsdx_icon_{abs(hash((str(src), label)))}.png"
#         if out.exists():
#             return str(out)
#         with Image.open(src).convert("RGBA") as img:  # type: ignore[union-attr]
#             w, h = img.size
#             crop = img.crop((int(w * 0.30), int(h * 0.03), int(w * 0.70), int(h * 0.43)))
#             crop.thumbnail((160, 120), Image.LANCZOS)
#             canvas = Image.new("RGBA", (160, 120), (255, 255, 255, 0))
#             canvas.paste(crop, ((160 - crop.width) // 2, (120 - crop.height) // 2), crop)
#             canvas.save(out)
#         return str(out)
#     except Exception:
#         logger.exception("Failed extracting fallback icon from card image. label=%r", label)
#         return ""


# def _resolve_first_raster(candidates: List[str], base_dir: Path) -> str:
#     for candidate in candidates:
#         path = _resolve_raster_path(candidate, base_dir)
#         if path:
#             return str(path)
#     return ""


# def _resolve_raster_path(href: Any, base_dir: Path) -> Optional[Path]:
#     if not href:
#         return None
#     raw = str(href).strip().strip('"').strip("'")
#     if raw.startswith("data:image/") or raw.startswith(("http://", "https://")):
#         return None
#     path = Path(unquote(raw))
#     if not path.is_absolute():
#         path = base_dir / path
#     try:
#         path = path.resolve()
#     except Exception:
#         pass
#     if not path.exists() or not path.is_file():
#         return None
#     if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
#         return None
#     return path


# def _can_vectorize_icon(path: str) -> bool:
#     return Image is not None and bool(_resolve_raster_path(path, Path.cwd()))


# def _icon_mosaic_cells(path: str, grid: int = 26) -> List[Tuple[int, int, str]]:
#     resolved = _resolve_raster_path(path, Path.cwd())
#     if Image is None or not resolved:
#         return []
#     try:
#         with Image.open(resolved).convert("RGBA") as img:  # type: ignore[union-attr]
#             grid = max(20, min(30, int(grid or 26)))
#             if ImageEnhance is not None:
#                 img = ImageEnhance.Color(img).enhance(2.0)
#                 img = ImageEnhance.Contrast(img).enhance(1.9)
#                 img = ImageEnhance.Brightness(img).enhance(0.78)
#             bbox = img.getbbox()
#             if bbox:
#                 img = img.crop(bbox)
#             img.thumbnail((grid, grid), Image.LANCZOS)
#             canvas = Image.new("RGBA", (grid, grid), (255, 255, 255, 0))
#             canvas.paste(img, ((grid - img.width) // 2, (grid - img.height) // 2), img)
#             pix = canvas.load()
#             cells: List[Tuple[int, int, str]] = []
#             for y in range(grid):
#                 for x in range(grid):
#                     r, g, b, a = pix[x, y]
#                     if a < 40:
#                         continue
#                     if r > 250 and g > 250 and b > 250:
#                         continue
#                     if a < 235:
#                         mix = max(a / 255.0, 0.68)
#                         r = int(r * mix + 255 * (1 - mix))
#                         g = int(g * mix + 255 * (1 - mix))
#                         b = int(b * mix + 255 * (1 - mix))
#                     luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
#                     if luminance > 180:
#                         factor = 180.0 / max(luminance, 1.0)
#                         r, g, b = int(r * factor), int(g * factor), int(b * factor)
#                     r = max(0, min(255, int(round(r / 8.0) * 8)))
#                     g = max(0, min(255, int(round(g / 8.0) * 8)))
#                     b = max(0, min(255, int(round(b / 8.0) * 8)))
#                     if r > 248 and g > 248 and b > 248:
#                         continue
#                     cells.append((x, y, f"#{r:02X}{g:02X}{b:02X}"))
#             return cells
#     except Exception:
#         logger.exception("Failed to vectorize icon: %s", path)
#         return []


# def _node_visual_style(label: str, seed: str, attrs: Dict[str, str]) -> Dict[str, str]:
#     if get_style_for_label is not None:
#         try:
#             style = get_style_for_label(_normalise_label_for_lookup(label or seed))  # type: ignore[misc]
#             fill = _colour(attrs.get("fillcolor") or style.get("fill"), _pastel_color(seed))
#             border = _colour(attrs.get("color") or style.get("border"), _darker_border(fill))
#             font = _colour(style.get("font"), "#000000")
#             if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#                 fill = _pastel_color(seed)
#                 border = _darker_border(fill)
#             return {"fill": fill, "border": border, "font": font}
#         except Exception:
#             pass
#     fill = _colour(attrs.get("fillcolor"), _pastel_color(seed))
#     if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#         fill = _pastel_color(seed)
#     border = _colour(attrs.get("color"), _darker_border(fill))
#     return {"fill": fill, "border": border, "font": "#000000"}


# def _resolve_icon_path(label: str) -> str:
#     if resolve_icon_from_node_label is None:
#         return ""
#     lookup_values: List[str] = []
#     raw_label = _cleanup_visible_text(label)
#     lookup_values.extend([raw_label, _normalise_label_for_lookup(raw_label), raw_label.replace("_", " "), raw_label.replace("_", "")])
#     if clean_label is not None:
#         try:
#             cleaned = clean_label(raw_label)  # type: ignore[misc]
#             lookup_values.extend([cleaned, _normalise_label_for_lookup(cleaned)])
#         except Exception:
#             pass
#     seen = set()
#     for candidate in lookup_values:
#         candidate = str(candidate or "").strip()
#         if not candidate or candidate.lower() in seen:
#             continue
#         seen.add(candidate.lower())
#         try:
#             icon = resolve_icon_from_node_label(candidate, PROJECT_ROOT)  # type: ignore[misc]
#             if not icon:
#                 continue
#             if normalize_icon_for_graphviz is not None:
#                 try:
#                     icon = normalize_icon_for_graphviz(str(icon))  # type: ignore[misc]
#                 except Exception:
#                     logger.exception("Failed to normalize VSDX icon. label=%r icon=%s", candidate, icon)
#             resolved = _resolve_raster_path(str(icon), Path.cwd())
#             if resolved:
#                 logger.info("[VSDX_ICON] Resolved icon for label=%r -> %s", candidate, resolved)
#                 return str(resolved)
#         except Exception:
#             logger.exception("[VSDX_ICON] Icon resolution failed for label=%r", candidate)
#     return ""


# def _normalise_label_for_lookup(label: str) -> str:
#     text = _cleanup_visible_text(label).replace("_", " ").replace("-", " ")
#     text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
#     return re.sub(r"\s+", " ", text).strip()


# def _icon_abbrev(label: str) -> str:
#     clean = _normalise_label_for_lookup(label)
#     words = [w for w in re.split(r"\s+", clean) if w]
#     if not words:
#         return "•"
#     if len(words) == 1:
#         return words[0][:2].upper()
#     return "".join(word[0] for word in words[:2]).upper()


# def _wrap_label(label: str) -> str:
#     if clean_label is not None:
#         try:
#             text = clean_label(label)  # type: ignore[misc]
#         except Exception:
#             text = _cleanup_visible_text(label).replace("_", " ")
#     else:
#         text = _cleanup_visible_text(label).replace("_", " ")
#     words = text.split()
#     if len(words) <= 2:
#         return text
#     if len(words) <= 4:
#         mid = (len(words) + 1) // 2
#         return " ".join(words[:mid]) + "\n" + " ".join(words[mid:])
#     mid = max(2, len(words) // 2)
#     return " ".join(words[:mid]) + "\n" + " ".join(words[mid:])


# def _run_graphviz(dot: Path, out: Path, fmt: str, engine: str) -> None:
#     result = subprocess.run([engine, f"-T{fmt}", str(dot), "-o", str(out)], capture_output=True, text=True, check=False)
#     if result.returncode != 0:
#         raise RuntimeError(f"Graphviz failed for {fmt}:\n{result.stderr or result.stdout}")


# def _iter_svg(root: ET.Element) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
#     def walk(elem: ET.Element, parent_matrix: Matrix, parent_classes: List[str]) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
#         matrix = _matmul(parent_matrix, _transform(elem.get("transform")))
#         classes = _class_tokens(elem.get("class"))
#         yield elem, matrix, parent_classes
#         for child in list(elem):
#             yield from walk(child, matrix, parent_classes + classes)
#     yield from walk(root, IDENTITY, [])


# def _class_tokens(value: Optional[str]) -> List[str]:
#     return [token.strip().lower() for token in re.split(r"\s+", value or "") if token.strip()]


# def _transform(raw: Optional[str]) -> Matrix:
#     if not raw:
#         return IDENTITY
#     matrix = IDENTITY
#     for name, args in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", raw):
#         nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", args)]
#         local = IDENTITY
#         if name == "matrix" and len(nums) >= 6:
#             local = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
#         elif name == "translate":
#             local = (1.0, 0.0, 0.0, 1.0, nums[0] if nums else 0.0, nums[1] if len(nums) > 1 else 0.0)
#         elif name == "scale":
#             sx = nums[0] if nums else 1.0
#             sy = nums[1] if len(nums) > 1 else sx
#             local = (sx, 0.0, 0.0, sy, 0.0, 0.0)
#         elif name == "rotate" and nums:
#             angle = math.radians(nums[0])
#             c, s = math.cos(angle), math.sin(angle)
#             local = (c, s, -s, c, 0.0, 0.0)
#         matrix = _matmul(matrix, local)
#     return matrix


# def _matmul(a: Matrix, b: Matrix) -> Matrix:
#     a1, b1, c1, d1, e1, f1 = a
#     a2, b2, c2, d2, e2, f2 = b
#     return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


# def _apply(matrix: Matrix, x: float, y: float) -> Tuple[float, float]:
#     a, b, c, d, e, f = matrix
#     return a * x + c * y + e, b * x + d * y + f


# def _style(elem: ET.Element) -> Dict[str, str]:
#     result: Dict[str, str] = {}
#     for part in (elem.get("style") or "").split(";"):
#         if ":" in part:
#             key, value = part.split(":", 1)
#             result[key.strip().lower()] = value.strip()
#     for key, value in elem.attrib.items():
#         if key.lower() in {"fill", "stroke", "stroke-width", "font-size", "font-weight", "text-anchor"}:
#             result[key.lower()] = value
#     return result


# def _title(group: ET.Element) -> str:
#     title = group.find(_svg("title"))
#     return _read_text(title) if title is not None else ""


# def _read_text(elem: Optional[ET.Element]) -> str:
#     if elem is None:
#         return ""
#     parts: List[str] = []
#     if elem.text:
#         parts.append(elem.text)
#     for child in list(elem):
#         child_text = _read_text(child)
#         if child_text:
#             parts.append(child_text)
#         if child.tail:
#             parts.append(child.tail)
#     return html.unescape(" ".join(p.strip() for p in parts if p and p.strip())).strip()


# def _svg_href(elem: ET.Element) -> str:
#     return (elem.get("href") or elem.get(_xlink("href")) or elem.get("xlink:href") or "").strip()


# def _rect_points(elem: ET.Element, matrix: Matrix) -> List[Tuple[float, float]]:
#     x, y = _num(elem.get("x"), 0.0), _num(elem.get("y"), 0.0)
#     w, h = _num(elem.get("width"), 0.0), _num(elem.get("height"), 0.0)
#     if w <= 0 or h <= 0:
#         return []
#     return [_apply(matrix, x, y), _apply(matrix, x + w, y), _apply(matrix, x + w, y + h), _apply(matrix, x, y + h)]


# def _points(raw: str) -> List[Tuple[float, float]]:
#     nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw or "")]
#     return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


# def _path_points(raw: str) -> List[Tuple[float, float]]:
#     return _points(raw)


# def _simplify_route(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
#     if len(points) <= 2:
#         return points
#     start, end = points[0], points[-1]
#     mid = points[len(points) // 2]
#     if abs(mid[0] - start[0]) > 8 and abs(mid[1] - end[1]) > 8:
#         return [start, mid, end]
#     return [start, end]


# def _bbox(points: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
#     xs, ys = [p[0] for p in points], [p[1] for p in points]
#     return min(xs), min(ys), max(xs), max(ys)


# def _num(value: Any, default: float = 0.0) -> float:
#     try:
#         return float(re.sub(r"(px|pt|in|cm|mm|%)$", "", str(value).strip(), flags=re.I))
#     except Exception:
#         return default


# def _colour(value: Any, default: str) -> str:
#     raw = str(value or "").strip()
#     if not raw:
#         return default
#     if raw.lower() in {"none", "transparent"}:
#         return "#FFFFFF"
#     named = {"black": "#000000", "white": "#FFFFFF", "red": "#FF0000", "green": "#008000", "blue": "#0000FF", "gray": "#808080", "grey": "#808080", "orange": "#FFA500", "purple": "#800080", "yellow": "#FFFF00", "cyan": "#00FFFF", "magenta": "#FF00FF", "brown": "#A52A2A", "pink": "#FFC0CB", "teal": "#008080"}
#     if raw.lower() in named:
#         return named[raw.lower()]
#     if raw.startswith("#"):
#         if len(raw) == 4:
#             return "#" + "".join(ch * 2 for ch in raw[1:]).upper()
#         return raw[:7].upper()
#     rgb = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", raw, flags=re.I)
#     if rgb:
#         return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in rgb.groups())
#     return default


# def _rgb(color: str) -> Tuple[int, int, int]:
#     color = _colour(color, "#000000")
#     return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


# def _pt(value: float) -> float:
#     return max(0.01, float(value) / PT_PER_INCH)


# def _is_near_black(color: str) -> bool:
#     try:
#         r, g, b = _rgb(color)
#         return r < 24 and g < 24 and b < 24
#     except Exception:
#         return False


# def _pastel_color(seed: Any) -> str:
#     palette = ["#E8F0FE", "#E6F4EA", "#FEF7E0", "#FCE8E6", "#F3E8FD", "#E0F2F1", "#FFF3E0", "#E8EAED", "#E3F2FD", "#F1F8E9"]
#     value = sum(ord(ch) for ch in str(seed or "node"))
#     return palette[value % len(palette)]


# def _darker_border(fill: str) -> str:
#     try:
#         r, g, b = _rgb(fill)
#         return f"#{int(r * 0.72):02X}{int(g * 0.72):02X}{int(b * 0.72):02X}"
#     except Exception:
#         return "#666666"


# def _lighten(color: str, factor: float = 0.35) -> str:
#     try:
#         r, g, b = _rgb(color)
#         return f"#{int(r + (255-r)*factor):02X}{int(g + (255-g)*factor):02X}{int(b + (255-b)*factor):02X}"
#     except Exception:
#         return "#FFFFFF"


# def _dedupe_legend_items(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
#     result: List[Tuple[str, str]] = []
#     seen = set()
#     for color, label in items or []:
#         safe_color = _colour(color, "#666666")
#         safe_label = _cleanup_visible_text(label)
#         if not safe_label:
#             continue
#         key = (safe_color.lower(), safe_label.lower())
#         if key in seen:
#             continue
#         seen.add(key)
#         result.append((safe_color, safe_label))
#     return result


# def _local(tag: str) -> str:
#     return str(tag).split("}", 1)[-1].lower()


# def _safe(value: str) -> str:
#     return re.sub(r"[^A-Za-z0-9_. -]+", "_", str(value or "Shape"))[:120] or "Shape"


# def _xml(root: ET.Element) -> str:
#     return "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + ET.tostring(root, encoding="unicode")


# def _xml_plain(root: ET.Element) -> str:
#     return "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + ET.tostring(root, encoding="unicode")


# __all__ = ["VisioExportOptions", "export_vsdx_from_dot", "export_vsdx_from_svg"]


# from __future__ import annotations

# """
# visio_vsdx_exporter.py

# Generic Graphviz DOT/SVG -> editable Visio VSDX exporter.

# Latest updates:
# - Bigger, darker, centrally aligned editable icons.
# - Automatic environment/platform separation zones when Graphviz clusters are missing.
# - Preserves explicit Graphviz clusters when present.
# - Larger flow legend placed in reserved bottom area so the main diagram is not compressed.
# - Text wrapping and label-band sizing to avoid overlap.
# - No project-specific or service-specific logic required by callers; zone labels/rules are
#   configurable through VisioExportOptions.
# """

# import html
# import logging
# import math
# import os
# import re
# import shutil
# import subprocess
# import zipfile
# from dataclasses import dataclass
# from pathlib import Path
# from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
# from urllib.parse import unquote
# from xml.etree import ElementTree as ET

# logger = logging.getLogger(__name__)

# try:
#     from PIL import Image, ImageEnhance
# except Exception:  # pragma: no cover
#     Image = None  # type: ignore
#     ImageEnhance = None  # type: ignore

# try:
#     from .config import PROJECT_ROOT  # type: ignore
# except Exception:
#     PROJECT_ROOT = Path.cwd()  # type: ignore

# try:
#     from .icon_resolver import get_style_for_label, resolve_icon_from_node_label  # type: ignore
# except Exception:
#     get_style_for_label = None  # type: ignore
#     resolve_icon_from_node_label = None  # type: ignore

# try:
#     from .node_card import clean_label, normalize_icon_for_graphviz  # type: ignore
# except Exception:
#     clean_label = None  # type: ignore
#     normalize_icon_for_graphviz = None  # type: ignore

# V_NS = "http://schemas.microsoft.com/office/visio/2012/main"
# R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
# PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
# VISIO_REL_NS = "http://schemas.microsoft.com/visio/2010/relationships"
# SVG_NS = "http://www.w3.org/2000/svg"
# XLINK_NS = "http://www.w3.org/1999/xlink"
# PT_PER_INCH = 72.0
# Matrix = Tuple[float, float, float, float, float, float]
# IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# ET.register_namespace("", V_NS)
# ET.register_namespace("r", R_NS)


# def _v(tag: str) -> str:
#     return f"{{{V_NS}}}{tag}"


# def _r(tag: str) -> str:
#     return f"{{{R_NS}}}{tag}"


# def _svg(tag: str) -> str:
#     return f"{{{SVG_NS}}}{tag}"


# def _xlink(tag: str) -> str:
#     return f"{{{XLINK_NS}}}{tag}"


# @dataclass
# class VisioExportOptions:
#     page_name: str = "Diagram"
#     page_width_in: Optional[float] = None
#     page_height_in: Optional[float] = None
#     include_visual_background: bool = False
#     include_editable_overlay: bool = True
#     lock_visual_background: bool = False
#     overlay_boxes_visible: bool = True
#     overlay_arrows_visible: bool = True
#     overlay_text_visible: bool = False
#     include_icons: bool = True
#     include_flow_legend: bool = True
#     legend_on_separate_page: bool = False
#     legend_items: Optional[List[Tuple[str, str]]] = None
#     node_font_size_pt: float = 13.0
#     node_text_bold: bool = True
#     connector_arrow_type: int = 4
#     connector_arrow_size: int = 2
#     min_page_width_in: float = 11.0
#     min_page_height_in: float = 8.5
#     fail_on_no_nodes: bool = True

#     # Card and icon tuning.
#     vector_icon_grid: int = 28
#     min_node_width_in: float = 1.55
#     min_node_height_in: float = 1.05
#     max_node_width_in: float = 2.45
#     max_node_height_in: float = 1.38
#     min_label_band_height_in: float = 0.36
#     max_icon_size_in: float = 0.56

#     # Flow legend tuning. Reserved space is added below diagram so main diagram is not impacted.
#     legend_font_size_pt: float = 10.5
#     legend_title_font_size_pt: float = 14.0
#     legend_row_height_in: float = 0.42
#     legend_arrow_length_in: float = 1.05

#     # Zone/group rendering. Explicit DOT/SVG clusters are used first. Auto zones are generated
#     # only when cluster boxes are missing.
#     include_auto_zones: bool = True
#     auto_zone_only_when_no_clusters: bool = True
#     on_prem_zone_label: str = "On-Premise Environment"
#     cloud_zone_label: str = "Google Cloud Platform (GCP)"
#     external_zone_label: str = "External Services"
#     on_prem_zone_regex: str = r"\b(on[- ]?prem|on premise|on-premise|teradata|source|mft|managed file transfer)\b"
#     cloud_zone_regex: str = r"\b(gcp|google|cloud|gcs|bucket|pub/?sub|function|kms|cmek|collibra|target)\b"
#     external_zone_regex: str = r"\b(external|vault|hashi|secret|key management|gpg)\b"
#     cluster_fill: str = "#EEF6FF"
#     cluster_stroke: str = "#A8C7FA"
#     cluster_text: str = "#174EA6"


# @dataclass
# class DotEdge:
#     source: str
#     target: str
#     color: str
#     label: str


# @dataclass
# class DotMetadata:
#     labels: Dict[str, str]
#     attrs: Dict[str, Dict[str, str]]
#     legend_items: List[Tuple[str, str]]
#     edges: List[DotEdge]


# @dataclass
# class SvgNode:
#     node_id: str
#     label: str
#     bbox: Tuple[float, float, float, float]
#     fill: str
#     stroke: str
#     stroke_width: float = 1.0
#     image_href: str = ""
#     icon_path: str = ""
#     icon_text: str = ""
#     font_color: str = "#000000"


# @dataclass
# class SvgEdge:
#     edge_id: str
#     points: List[Tuple[float, float]]
#     color: str = "#666666"
#     width: float = 1.25


# @dataclass
# class SvgCluster:
#     cluster_id: str
#     label: str
#     bbox: Tuple[float, float, float, float]
#     fill: str = "#EEF6FF"
#     stroke: str = "#A8C7FA"
#     font_color: str = "#174EA6"


# @dataclass
# class SvgDiagram:
#     svg_path: Path
#     width_px: float
#     height_px: float
#     viewbox: Tuple[float, float, float, float]
#     nodes: List[SvgNode]
#     edges: List[SvgEdge]
#     clusters: List[SvgCluster]


# def export_vsdx_from_dot(
#     dot_path: os.PathLike | str,
#     vsdx_path: Optional[os.PathLike | str] = None,
#     *,
#     output_vsdx_path: Optional[os.PathLike | str] = None,
#     svg_path: Optional[os.PathLike | str] = None,
#     png_path: Optional[os.PathLike | str] = None,
#     options: Optional[VisioExportOptions] = None,
#     layout_engine: str = "dot",
#     **_: Any,
# ) -> Path:
#     dot = Path(dot_path)
#     out = Path(output_vsdx_path or vsdx_path or dot.with_suffix(".vsdx"))
#     opts = _normalise_options(options or VisioExportOptions())
#     svg = Path(svg_path) if svg_path else out.with_suffix(".svg")
#     if not svg.exists():
#         _run_graphviz(dot, svg, "svg", layout_engine)
#     if not svg.exists():
#         raise FileNotFoundError(f"SVG source not found for VSDX export: {svg}")
#     metadata = _parse_dot_metadata(dot)
#     opts.legend_items = _dedupe_legend_items(opts.legend_items or []) or metadata.legend_items
#     diagram = SvgParser(svg, metadata, fail_on_no_nodes=opts.fail_on_no_nodes, options=opts).parse()
#     return VsdxWriter(diagram, out, opts).write()


# def export_vsdx_from_svg(
#     svg_path: os.PathLike | str,
#     output_vsdx_path: os.PathLike | str,
#     *,
#     png_path: Optional[os.PathLike | str] = None,
#     options: Optional[VisioExportOptions] = None,
# ) -> Path:
#     opts = _normalise_options(options or VisioExportOptions())
#     diagram = SvgParser(Path(svg_path), DotMetadata({}, {}, [], []), fail_on_no_nodes=opts.fail_on_no_nodes, options=opts).parse()
#     return VsdxWriter(diagram, Path(output_vsdx_path), opts).write()


# def _normalise_options(opts: VisioExportOptions) -> VisioExportOptions:
#     opts.include_icons = True
#     opts.include_flow_legend = True
#     opts.node_font_size_pt = max(float(getattr(opts, "node_font_size_pt", 13.0) or 13.0), 13.0)
#     opts.vector_icon_grid = max(22, min(32, int(getattr(opts, "vector_icon_grid", 28) or 28)))
#     opts.max_icon_size_in = max(0.40, min(0.66, float(getattr(opts, "max_icon_size_in", 0.56) or 0.56)))
#     opts.min_label_band_height_in = max(0.32, min(0.56, float(getattr(opts, "min_label_band_height_in", 0.36) or 0.36)))
#     opts.legend_font_size_pt = max(8.0, min(16.0, float(getattr(opts, "legend_font_size_pt", 10.5) or 10.5)))
#     opts.legend_title_font_size_pt = max(10.0, min(20.0, float(getattr(opts, "legend_title_font_size_pt", 14.0) or 14.0)))
#     opts.legend_row_height_in = max(0.32, min(0.60, float(getattr(opts, "legend_row_height_in", 0.42) or 0.42)))
#     opts.legend_arrow_length_in = max(0.75, min(1.60, float(getattr(opts, "legend_arrow_length_in", 1.05) or 1.05)))
#     return opts


# class SvgParser:
#     def __init__(self, svg_path: Path, dot_metadata: DotMetadata, fail_on_no_nodes: bool = True, options: Optional[VisioExportOptions] = None):
#         self.svg_path = Path(svg_path)
#         self.dot_metadata = dot_metadata
#         self.fail_on_no_nodes = fail_on_no_nodes
#         self.options = options or VisioExportOptions()
#         self.root = ET.parse(str(svg_path)).getroot()
#         self.viewbox = self._viewbox()
#         self.width_px = _num(self.root.get("width"), self.viewbox[2])
#         self.height_px = _num(self.root.get("height"), self.viewbox[3])

#     def parse(self) -> SvgDiagram:
#         nodes: List[SvgNode] = []
#         edges: List[SvgEdge] = []
#         clusters: List[SvgCluster] = []
#         for elem, matrix, _parents in _iter_svg(self.root):
#             if _local(elem.tag) != "g":
#                 continue
#             classes = _class_tokens(elem.get("class"))
#             if self._is_cluster_group(elem, classes):
#                 cluster = self._parse_cluster(elem, matrix)
#                 if cluster and not self._is_graph_sized(cluster.bbox):
#                     clusters.append(cluster)
#             elif "node" in classes:
#                 node = self._parse_node(elem, matrix)
#                 if node and not self._is_graph_sized(node.bbox):
#                     nodes.append(node)
#             elif "edge" in classes:
#                 edge = self._parse_edge(elem, matrix)
#                 if edge:
#                     edges.append(edge)
#         clusters = _filter_clusters(clusters, nodes)
#         if self.options.include_auto_zones and (not clusters or not self.options.auto_zone_only_when_no_clusters):
#             clusters.extend(_auto_zones(nodes, self.options))
#             clusters = _filter_clusters(clusters, nodes)
#         if not nodes and self.fail_on_no_nodes:
#             raise RuntimeError(f"VSDX export failed: no editable node bodies detected from SVG: {self.svg_path}")
#         return SvgDiagram(self.svg_path, self.width_px, self.height_px, self.viewbox, nodes, edges, clusters)

#     def _viewbox(self) -> Tuple[float, float, float, float]:
#         raw = self.root.get("viewBox") or self.root.get("viewbox")
#         if raw:
#             vals = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)]
#             if len(vals) >= 4:
#                 return vals[0], vals[1], vals[2], vals[3]
#         return 0.0, 0.0, _num(self.root.get("width"), 1000.0), _num(self.root.get("height"), 800.0)

#     def _is_graph_sized(self, bbox: Tuple[float, float, float, float]) -> bool:
#         x1, y1, x2, y2 = bbox
#         return abs((x2 - x1) * (y2 - y1)) > max(1.0, self.viewbox[2] * self.viewbox[3]) * 0.85

#     def _is_cluster_group(self, elem: ET.Element, classes: List[str]) -> bool:
#         if "cluster" in classes:
#             return True
#         if any(token in classes for token in ("node", "edge")):
#             return False
#         title = (_title(elem) or "").lower()
#         if title.startswith("cluster") or title.startswith("subgraph"):
#             return True
#         label = ""
#         has_body = False
#         for child in elem.iter():
#             tag = _local(child.tag)
#             if tag == "text" and _cleanup_visible_text(_read_text(child)):
#                 label = _cleanup_visible_text(_read_text(child))
#             elif tag in {"polygon", "rect"}:
#                 has_body = True
#         return bool(label and has_body)

#     def _parse_cluster(self, group: ET.Element, matrix: Matrix) -> Optional[SvgCluster]:
#         title = _title(group) or f"cluster_{id(group)}"
#         label = ""
#         bodies: List[Tuple[float, float, float, float, str, str]] = []
#         for child in group.iter():
#             tag = _local(child.tag)
#             style = _style(child)
#             fill = _colour(style.get("fill") or child.get("fill"), self.options.cluster_fill)
#             stroke = _colour(style.get("stroke") or child.get("stroke"), self.options.cluster_stroke)
#             points: List[Tuple[float, float]] = []
#             if tag == "polygon":
#                 points = [_apply(matrix, x, y) for x, y in _points(child.get("points") or "")]
#             elif tag == "rect":
#                 points = _rect_points(child, matrix)
#             elif tag == "text":
#                 t = _cleanup_visible_text(_read_text(child))
#                 if t:
#                     label = t
#             if points:
#                 x1, y1, x2, y2 = _bbox(points)
#                 if abs(x2 - x1) > 15 and abs(y2 - y1) > 15:
#                     bodies.append((x1, y1, x2, y2, fill, stroke))
#         if not bodies:
#             return None
#         body = max(bodies, key=lambda b: abs((b[2] - b[0]) * (b[3] - b[1])))
#         fill = body[4]
#         if fill.upper() in {"#FFFFFF", "#000000"} or _is_near_black(fill):
#             fill = self.options.cluster_fill
#         stroke = body[5]
#         if _is_near_black(stroke):
#             stroke = self.options.cluster_stroke
#         return SvgCluster(title, label or title, (body[0], body[1], body[2], body[3]), fill, stroke, self.options.cluster_text)

#     def _parse_node(self, group: ET.Element, matrix: Matrix) -> Optional[SvgNode]:
#         title = _title(group) or f"node_{id(group)}"
#         dot_attrs = self.dot_metadata.attrs.get(title, {})
#         dot_label = self.dot_metadata.labels.get(title, title)
#         base_style = _node_visual_style(dot_label, title, dot_attrs)
#         bodies: List[Tuple[float, float, float, float, str, str, float, str]] = []
#         texts: List[str] = []
#         image_candidates: List[str] = []
#         if dot_attrs.get("image"):
#             image_candidates.append(dot_attrs.get("image", ""))
#         for child in group.iter():
#             tag = _local(child.tag)
#             style = _style(child)
#             fill = _colour(style.get("fill") or child.get("fill") or dot_attrs.get("fillcolor"), base_style["fill"])
#             stroke = _colour(style.get("stroke") or child.get("stroke") or dot_attrs.get("color"), base_style["border"])
#             stroke_width = max(0.75, _num(style.get("stroke-width") or child.get("stroke-width") or dot_attrs.get("penwidth"), 1.0))
#             points: List[Tuple[float, float]] = []
#             image_href = ""
#             if tag == "polygon":
#                 points = [_apply(matrix, x, y) for x, y in _points(child.get("points") or "")]
#             elif tag == "rect":
#                 points = _rect_points(child, matrix)
#             elif tag == "ellipse":
#                 cx, cy = _num(child.get("cx"), 0.0), _num(child.get("cy"), 0.0)
#                 rx, ry = _num(child.get("rx"), 0.0), _num(child.get("ry"), 0.0)
#                 points = [_apply(matrix, cx - rx, cy - ry), _apply(matrix, cx + rx, cy + ry)]
#             elif tag == "image":
#                 image_href = _svg_href(child)
#                 if image_href:
#                     image_candidates.append(image_href)
#                 x, y = _num(child.get("x"), 0.0), _num(child.get("y"), 0.0)
#                 width, height = _num(child.get("width"), 0.0), _num(child.get("height"), 0.0)
#                 if width > 0 and height > 0:
#                     points = [_apply(matrix, x, y), _apply(matrix, x + width, y), _apply(matrix, x + width, y + height), _apply(matrix, x, y + height)]
#                     fill, stroke = base_style["fill"], base_style["border"]
#             elif tag == "text":
#                 t = _cleanup_visible_text(_read_text(child))
#                 if t:
#                     texts.append(t)
#             if points:
#                 x1, y1, x2, y2 = _bbox(points)
#                 if abs(x2 - x1) > 4 and abs(y2 - y1) > 4 and not self._is_graph_sized((x1, y1, x2, y2)):
#                     if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#                         fill, stroke = base_style["fill"], base_style["border"]
#                     bodies.append((x1, y1, x2, y2, fill, stroke, stroke_width, image_href))
#         label = _cleanup_visible_text(" ".join(texts) or dot_label)
#         if not bodies:
#             return None
#         body = max(bodies, key=lambda b: abs((b[2] - b[0]) * (b[3] - b[1])))
#         fill, stroke = body[4], body[5]
#         if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#             fill, stroke = base_style["fill"], base_style["border"]
#         icon_path = _resolve_icon_path(label) or _extract_icon_from_candidates(image_candidates, self.svg_path.parent, label)
#         return SvgNode(title, label or title, (body[0], body[1], body[2], body[3]), fill, stroke, body[6], body[7], icon_path, _icon_abbrev(label), base_style.get("font", "#000000"))

#     def _parse_edge(self, group: ET.Element, matrix: Matrix) -> Optional[SvgEdge]:
#         title = _title(group) or f"edge_{id(group)}"
#         color = "#666666"
#         width = 1.25
#         all_points: List[Tuple[float, float]] = []
#         for path in group.findall(f".//{_svg('path')}"):
#             style = _style(path)
#             color = _colour(style.get("stroke") or path.get("stroke"), color)
#             width = max(1.0, _num(style.get("stroke-width") or path.get("stroke-width"), width))
#             path_points = [_apply(matrix, x, y) for x, y in _path_points(path.get("d") or "")]
#             if path_points:
#                 all_points = path_points
#                 break
#         for poly in group.findall(f".//{_svg('polygon')}"):
#             style = _style(poly)
#             color = _colour(style.get("fill") or style.get("stroke") or poly.get("fill") or poly.get("stroke"), color)
#             poly_points = [_apply(matrix, x, y) for x, y in _points(poly.get("points") or "")]
#             if poly_points:
#                 all_points.append((sum(x for x, _ in poly_points) / len(poly_points), sum(y for _, y in poly_points) / len(poly_points)))
#         simple = _simplify_route(all_points)
#         return SvgEdge(title, simple, color, width) if len(simple) >= 2 else None


# class VsdxWriter:
#     def __init__(self, diagram: SvgDiagram, output_path: Path, options: VisioExportOptions):
#         self.diagram = diagram
#         self.output_path = Path(output_path)
#         self.options = options
#         self.shape_id = 100
#         self.vb_x, self.vb_y, self.vb_w, self.vb_h = diagram.viewbox
#         self.vb_w, self.vb_h = max(1.0, self.vb_w), max(1.0, self.vb_h)
#         base_w = float(options.page_width_in or max(options.min_page_width_in, diagram.width_px / PT_PER_INCH))
#         base_h = float(options.page_height_in or max(options.min_page_height_in, diagram.height_px / PT_PER_INCH))
#         self.legend_items = _dedupe_legend_items(options.legend_items or []) if options.include_flow_legend else []
#         self.legend_space = self._legend_required_height() if self.legend_items else 0.0
#         self.page_w = base_w
#         self.page_h = base_h + self.legend_space
#         available_h = max(1.0, self.page_h - self.legend_space - 0.35)
#         self.scale = min(self.page_w / self.vb_w, available_h / self.vb_h)
#         self.offset_x = (self.page_w - self.vb_w * self.scale) / 2.0
#         self.offset_y = self.legend_space + (available_h - self.vb_h * self.scale) / 2.0

#     def _legend_required_height(self) -> float:
#         return max(1.2, self.options.legend_row_height_in * (len(self.legend_items) + 1.8) + 0.35)

#     def write(self) -> Path:
#         self.output_path.parent.mkdir(parents=True, exist_ok=True)
#         tmp = self.output_path.with_suffix(".tmp.vsdx")
#         if tmp.exists():
#             tmp.unlink()
#         template = self._template_path()
#         if template:
#             shutil.copyfile(template, tmp)
#             self._rewrite_template(tmp)
#         else:
#             self._write_minimal(tmp)
#         tmp.replace(self.output_path)
#         self._validate_package(self.output_path)
#         return self.output_path

#     def _template_path(self) -> Optional[Path]:
#         try:
#             import vsdx  # type: ignore
#             path = Path(vsdx.__file__).parent / "media" / "media.vsdx"
#             return path if path.exists() else None
#         except Exception:
#             return None

#     def _rewrite_template(self, path: Path) -> None:
#         replacements = {
#             "visio/pages/page1.xml": self._page_xml().encode("utf-8"),
#             "visio/pages/pages.xml": self._pages_xml().encode("utf-8"),
#             "visio/windows.xml": self._windows_xml().encode("utf-8"),
#             "visio/pages/_rels/page1.xml.rels": self._page_rels_xml().encode("utf-8"),
#         }
#         original = path.with_suffix(".orig.vsdx")
#         path.replace(original)
#         try:
#             with zipfile.ZipFile(original, "r") as zin, zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
#                 seen = set()
#                 for item in zin.infolist():
#                     zout.writestr(item.filename, self._content_types_xml() if item.filename == "[Content_Types].xml" else replacements.get(item.filename, zin.read(item.filename)))
#                     seen.add(item.filename)
#                 for name, data in replacements.items():
#                     if name not in seen:
#                         zout.writestr(name, data)
#         finally:
#             try:
#                 original.unlink()
#             except Exception:
#                 pass

#     def _write_minimal(self, path: Path) -> None:
#         with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
#             z.writestr("[Content_Types].xml", self._content_types_xml())
#             z.writestr("_rels/.rels", self._root_rels_xml())
#             z.writestr("visio/document.xml", self._document_xml())
#             z.writestr("visio/_rels/document.xml.rels", self._document_rels_xml())
#             z.writestr("visio/masters/masters.xml", self._masters_xml())
#             z.writestr("visio/pages/pages.xml", self._pages_xml())
#             z.writestr("visio/pages/_rels/pages.xml.rels", self._pages_rels_xml())
#             z.writestr("visio/pages/page1.xml", self._page_xml())
#             z.writestr("visio/pages/_rels/page1.xml.rels", self._page_rels_xml())
#             z.writestr("visio/windows.xml", self._windows_xml())
#             z.writestr("docProps/app.xml", self._app_xml())
#             z.writestr("docProps/core.xml", self._core_xml())

#     def _page_xml(self) -> str:
#         root = ET.Element(_v("PageContents"), {"xml:space": "preserve"})
#         shapes = ET.SubElement(root, _v("Shapes"))
#         for cluster in self.diagram.clusters:
#             self._append_cluster_shape(shapes, cluster)
#         for edge in self.diagram.edges:
#             self._append_edge_shape(shapes, edge)
#         for node in self.diagram.nodes:
#             self._append_card_shape(shapes, node)
#         if self.legend_items:
#             self._append_legend_items(shapes, self.legend_items)
#         page_sheet = ET.SubElement(root, _v("PageSheet"), {"LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._cell(page_sheet, "PageWidth", self.page_w)
#         self._cell(page_sheet, "PageHeight", self.page_h)
#         self._cell(page_sheet, "DrawingScale", 1)
#         self._cell(page_sheet, "PageScale", 1)
#         return _xml(root)

#     def _append_cluster_shape(self, parent: ET.Element, cluster: SvgCluster) -> None:
#         x1, y1, x2, y2 = cluster.bbox
#         w, h = self._size(x2 - x1, y2 - y1)
#         cx, cy = self._xy((x1 + x2) / 2.0, (y1 + y2) / 2.0)
#         body = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(cluster.cluster_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(body, cx, cy, w, h)
#         self._color_cell(body, "FillForegnd", _colour(cluster.fill, self.options.cluster_fill))
#         self._color_cell(body, "FillBkgnd", _colour(cluster.fill, self.options.cluster_fill))
#         self._cell(body, "FillPattern", 1)
#         self._cell(body, "FillForegndTrans", 15)
#         self._color_cell(body, "LineColor", _colour(cluster.stroke, self.options.cluster_stroke))
#         self._cell(body, "LineWeight", _pt(1.5))
#         self._cell(body, "Rounding", 0.12)
#         self._rectangle_geometry(body)
#         ET.SubElement(body, _v("Text"))
#         title_h = 0.26
#         title = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(cluster.cluster_id + "_title"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(title, cx, cy + h / 2.0 - title_h / 2.0 - 0.04, max(0.6, w - 0.24), title_h)
#         self._cell(title, "LinePattern", 0)
#         self._cell(title, "FillPattern", 0)
#         self._character_section(title, 12.5, True, cluster.font_color)
#         self._paragraph_section(title, 1)
#         self._text_block(title, left_margin=0.02)
#         self._rectangle_geometry(title, no_line=True, no_fill=True)
#         ET.SubElement(title, _v("Text")).text = _cleanup_visible_text(cluster.label)

#     def _append_card_shape(self, parent: ET.Element, node: SvgNode) -> None:
#         x1, y1, x2, y2 = node.bbox
#         raw_w, raw_h = self._size(x2 - x1, y2 - y1)
#         cx, cy = self._xy((x1 + x2) / 2.0, (y1 + y2) / 2.0)
#         label = _wrap_label(node.label)
#         line_count = max(1, label.count("\n") + 1)
#         label_len = max(len(part) for part in label.split("\n") if part)
#         label_w_need = min(self.options.max_node_width_in, max(self.options.min_node_width_in, label_len * 0.075 + 0.55))
#         min_w = max(self.options.min_node_width_in, min(self.options.max_node_width_in, self.page_w * 0.11), label_w_need)
#         label_h = max(self.options.min_label_band_height_in, min(0.56, 0.23 * line_count + 0.12))
#         min_h = max(self.options.min_node_height_in, label_h + 0.76)
#         w = max(raw_w, min_w)
#         h = max(raw_h, min_h)
#         top_margin = max(0.07, h * 0.06)
#         gap_above_label = max(0.07, h * 0.06)
#         available_icon_h = max(0.26, h - label_h - top_margin - gap_above_label - 0.10)
#         icon_size = max(0.36, min(self.options.max_icon_size_in, available_icon_h, w * 0.28))
#         icon_cy = cy + h / 2.0 - top_margin - icon_size / 2.0
#         band_cy = cy - h / 2.0 + label_h / 2.0 + 0.06
#         body = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(body, cx, cy, w, h)
#         self._color_cell(body, "FillForegnd", node.fill)
#         self._color_cell(body, "FillBkgnd", node.fill)
#         self._cell(body, "FillPattern", 1)
#         self._cell(body, "LinePattern", 1)
#         self._color_cell(body, "LineColor", node.stroke)
#         self._cell(body, "LineWeight", _pt(max(1.0, node.stroke_width)))
#         self._cell(body, "Rounding", 0.08)
#         self._rectangle_geometry(body)
#         ET.SubElement(body, _v("Text"))
#         band = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id + "_label_band"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(band, cx, band_cy, max(0.45, w - 0.18), label_h)
#         self._color_cell(band, "FillForegnd", "#FFFFFF")
#         self._color_cell(band, "FillBkgnd", "#FFFFFF")
#         self._cell(band, "FillPattern", 1)
#         self._cell(band, "LinePattern", 0)
#         self._cell(band, "Rounding", 0.05)
#         font_size = max(9.5, min(12.5, self.options.node_font_size_pt - max(0, line_count - 1) * 1.2))
#         self._character_section(band, font_size, True, node.font_color)
#         self._paragraph_section(band, 1)
#         self._text_block(band, left_margin=0.035)
#         self._rectangle_geometry(band, no_line=True)
#         ET.SubElement(band, _v("Text")).text = label
#         badge = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id + "_icon_badge"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(badge, cx, icon_cy, icon_size, icon_size)
#         self._color_cell(badge, "FillForegnd", _lighten(node.stroke, 0.88))
#         self._color_cell(badge, "FillBkgnd", _lighten(node.stroke, 0.88))
#         self._cell(badge, "FillPattern", 1)
#         self._cell(badge, "LinePattern", 1)
#         self._color_cell(badge, "LineColor", node.stroke)
#         self._cell(badge, "LineWeight", _pt(0.75))
#         self._cell(badge, "Rounding", 0.04)
#         self._rectangle_geometry(badge)
#         if self.options.include_icons and node.icon_path and _can_vectorize_icon(node.icon_path):
#             self._append_icon_vector_mosaic(parent, cx, icon_cy, icon_size * 0.88, node.icon_path, node.node_id)
#             ET.SubElement(badge, _v("Text"))
#         else:
#             self._character_section(badge, 8.5, True, node.stroke)
#             self._paragraph_section(badge, 1)
#             self._text_block(badge, left_margin=0.01)
#             ET.SubElement(badge, _v("Text")).text = node.icon_text

#     def _append_icon_vector_mosaic(self, parent: ET.Element, cx: float, cy: float, size: float, icon_path: str, node_id: str) -> None:
#         cells = _icon_mosaic_cells(icon_path, grid=self.options.vector_icon_grid)
#         if not cells:
#             return
#         grid = max(max(x for x, _, _ in cells) + 1, max(y for _, y, _ in cells) + 1)
#         cell = size / grid
#         origin_x = cx - size / 2.0
#         origin_y = cy + size / 2.0
#         for ix, iy, color in cells:
#             px = origin_x + (ix + 0.5) * cell
#             py = origin_y - (iy + 0.5) * cell
#             shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(f"{node_id}_icon_px"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#             self._base_shape_cells(shape, px, py, cell * 1.15, cell * 1.15)
#             self._color_cell(shape, "FillForegnd", color)
#             self._color_cell(shape, "FillBkgnd", color)
#             self._cell(shape, "FillPattern", 1)
#             self._cell(shape, "LinePattern", 0)
#             self._rectangle_geometry(shape, no_line=True)
#             ET.SubElement(shape, _v("Text"))

#     def _append_edge_shape(self, parent: ET.Element, edge: SvgEdge) -> None:
#         points = [self._xy(x, y) for x, y in edge.points]
#         if len(points) < 2:
#             return
#         min_x, min_y, max_x, max_y = _bbox(points)
#         w, h = max(0.01, max_x - min_x), max(0.01, max_y - min_y)
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(edge.edge_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, min_x + w / 2.0, min_y + h / 2.0, w, h)
#         self._color_cell(shape, "LineColor", edge.color)
#         self._cell(shape, "LineWeight", _pt(max(1.25, edge.width)))
#         self._cell(shape, "LinePattern", 1)
#         self._cell(shape, "BeginArrow", 0)
#         self._cell(shape, "EndArrow", self.options.connector_arrow_type)
#         self._cell(shape, "EndArrowSize", self.options.connector_arrow_size)
#         self._line_geometry(shape, points, min_x, min_y, w, h)
#         ET.SubElement(shape, _v("Text"))

#     def _append_legend_items(self, parent: ET.Element, items: List[Tuple[str, str]]) -> None:
#         items = _dedupe_legend_items(items)
#         if not items:
#             return
#         x = 0.65
#         y = 0.35 + self.options.legend_row_height_in * len(items)
#         self._append_free_text(parent, "Flow Legend", x, y + 0.38, self.options.legend_title_font_size_pt, True)
#         for idx, (color, label) in enumerate(items):
#             row_y = y - self.options.legend_row_height_in * idx
#             self._append_page_line(parent, x, row_y, x + self.options.legend_arrow_length_in, row_y, color)
#             self._append_free_text(parent, label, x + self.options.legend_arrow_length_in + 0.25, row_y, self.options.legend_font_size_pt, False)

#     def _append_free_text(self, parent: ET.Element, text: str, x: float, y: float, font_pt: float, bold: bool) -> None:
#         text = _cleanup_visible_text(text)
#         w, h = max(1.0, min(13.0, len(text) * font_pt / 72.0 * 0.55)), 0.28
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(text[:40] or "Text"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, x + w / 2.0, y, w, h)
#         self._cell(shape, "LinePattern", 0)
#         self._cell(shape, "FillPattern", 0)
#         self._character_section(shape, font_pt, bold, "#000000")
#         self._paragraph_section(shape, 0)
#         self._rectangle_geometry(shape, no_line=True, no_fill=True)
#         ET.SubElement(shape, _v("Text")).text = text

#     def _append_page_line(self, parent: ET.Element, x1: float, y1: float, x2: float, y2: float, color: str) -> None:
#         min_x, min_y, max_x, max_y = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
#         w, h = max(0.01, max_x - min_x), max(0.01, max_y - min_y)
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": "Legend_Line", "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, min_x + w / 2.0, min_y + h / 2.0, w, h)
#         self._color_cell(shape, "LineColor", color)
#         self._cell(shape, "LineWeight", _pt(1.80))
#         self._cell(shape, "EndArrow", 4)
#         self._line_geometry(shape, [(x1, y1), (x2, y2)], min_x, min_y, w, h)
#         ET.SubElement(shape, _v("Text"))

#     def _base_shape_cells(self, shape: ET.Element, cx: float, cy: float, w: float, h: float) -> None:
#         self._cell(shape, "PinX", cx)
#         self._cell(shape, "PinY", cy)
#         self._cell(shape, "Width", w)
#         self._cell(shape, "Height", h)
#         self._cell(shape, "LocPinX", w / 2.0, "Width*0.5")
#         self._cell(shape, "LocPinY", h / 2.0, "Height*0.5")
#         self._cell(shape, "Angle", 0)
#         self._cell(shape, "FlipX", 0)
#         self._cell(shape, "FlipY", 0)
#         self._cell(shape, "ResizeMode", 0)

#     def _character_section(self, shape: ET.Element, font_pt: float, bold: bool, color: str) -> None:
#         section = ET.SubElement(shape, _v("Section"), {"N": "Character"})
#         row = ET.SubElement(section, _v("Row"), {"IX": "0"})
#         self._cell(row, "Size", _pt(font_pt))
#         self._cell(row, "Style", 17 if bold else 0)
#         self._color_cell(row, "Color", color)

#     def _paragraph_section(self, shape: ET.Element, align: int) -> None:
#         section = ET.SubElement(shape, _v("Section"), {"N": "Paragraph"})
#         row = ET.SubElement(section, _v("Row"), {"IX": "0"})
#         self._cell(row, "HorzAlign", align)

#     def _text_block(self, shape: ET.Element, left_margin: float = 0.06) -> None:
#         block = ET.SubElement(shape, _v("TextBlock"))
#         self._cell(block, "VerticalAlign", 1)
#         self._cell(block, "LeftMargin", left_margin)
#         self._cell(block, "RightMargin", 0.06)
#         self._cell(block, "TopMargin", 0.03)
#         self._cell(block, "BottomMargin", 0.03)

#     def _rectangle_geometry(self, shape: ET.Element, *, no_line: bool = False, no_fill: bool = False) -> None:
#         geom = ET.SubElement(shape, _v("Section"), {"N": "Geometry", "IX": "0"})
#         self._cell(geom, "NoFill", 1 if no_fill else 0)
#         self._cell(geom, "NoLine", 1 if no_line else 0)
#         for row_type, ix, x, y in [("RelMoveTo", 1, 0, 0), ("RelLineTo", 2, 1, 0), ("RelLineTo", 3, 1, 1), ("RelLineTo", 4, 0, 1), ("RelLineTo", 5, 0, 0)]:
#             row = ET.SubElement(geom, _v("Row"), {"T": row_type, "IX": str(ix)})
#             self._cell(row, "X", x)
#             self._cell(row, "Y", y)

#     def _line_geometry(self, shape: ET.Element, points: List[Tuple[float, float]], min_x: float, min_y: float, w: float, h: float) -> None:
#         geom = ET.SubElement(shape, _v("Section"), {"N": "Geometry", "IX": "0"})
#         self._cell(geom, "NoFill", 1)
#         self._cell(geom, "NoLine", 0)
#         for ix, (x, y) in enumerate(points, start=1):
#             row = ET.SubElement(geom, _v("Row"), {"T": "RelMoveTo" if ix == 1 else "RelLineTo", "IX": str(ix)})
#             self._cell(row, "X", 0 if w <= 0 else (x - min_x) / w)
#             self._cell(row, "Y", 0 if h <= 0 else (y - min_y) / h)

#     def _pages_xml(self) -> str:
#         root = ET.Element(_v("Pages"), {"xml:space": "preserve"})
#         page = ET.SubElement(root, _v("Page"), {"ID": "0", "NameU": self.options.page_name or "Diagram", "Name": self.options.page_name or "Diagram", "ViewScale": "1", "ViewCenterX": str(self.page_w / 2.0), "ViewCenterY": str(self.page_h / 2.0)})
#         sheet = ET.SubElement(page, _v("PageSheet"), {"LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._cell(sheet, "PageWidth", self.page_w)
#         self._cell(sheet, "PageHeight", self.page_h)
#         ET.SubElement(page, _v("Rel"), {_r("id"): "rId1"})
#         return _xml(root)

#     def _windows_xml(self) -> str:
#         root = ET.Element(_v("Windows"), {"xml:space": "preserve"})
#         win = ET.SubElement(root, _v("Window"), {"ID": "0", "WindowType": "Drawing", "ContainerType": "Page", "Container": "0"})
#         self._cell(win, "ViewScale", 1)
#         self._cell(win, "ViewCenterX", self.page_w / 2.0)
#         self._cell(win, "ViewCenterY", self.page_h / 2.0)
#         return _xml(root)

#     def _content_types_xml(self) -> str:
#         root = ET.Element("Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"})
#         for ext, ctype in {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}.items():
#             ET.SubElement(root, "Default", {"Extension": ext, "ContentType": ctype})
#         for part, ctype in {
#             "/visio/document.xml": "application/vnd.ms-visio.drawing.main+xml",
#             "/visio/pages/pages.xml": "application/vnd.ms-visio.pages+xml",
#             "/visio/pages/page1.xml": "application/vnd.ms-visio.page+xml",
#             "/visio/windows.xml": "application/vnd.ms-visio.windows+xml",
#             "/visio/masters/masters.xml": "application/vnd.ms-visio.masters+xml",
#             "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
#             "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
#         }.items():
#             ET.SubElement(root, "Override", {"PartName": part, "ContentType": ctype})
#         return _xml_plain(root)

#     def _root_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/document", "Target": "visio/document.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId2", "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "Target": "docProps/core.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId3", "Type": f"{R_NS}/extended-properties", "Target": "docProps/app.xml"})
#         return _xml_plain(root)

#     def _document_xml(self) -> str:
#         root = ET.Element(_v("VisioDocument"), {"xml:space": "preserve"})
#         ET.SubElement(root, _v("DocumentSettings"))
#         return _xml(root)

#     def _document_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/masters", "Target": "masters/masters.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId2", "Type": f"{VISIO_REL_NS}/pages", "Target": "pages/pages.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId3", "Type": f"{VISIO_REL_NS}/windows", "Target": "windows.xml"})
#         return _xml_plain(root)

#     def _pages_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/page", "Target": "page1.xml"})
#         return _xml_plain(root)

#     def _page_rels_xml(self) -> str:
#         return _xml_plain(ET.Element("Relationships", {"xmlns": PKG_REL_NS}))

#     def _masters_xml(self) -> str:
#         return _xml(ET.Element(_v("Masters"), {"xml:space": "preserve"}))

#     def _app_xml(self) -> str:
#         root = ET.Element("Properties", {"xmlns": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"})
#         ET.SubElement(root, "Application").text = "Microsoft Visio"
#         return _xml_plain(root)

#     def _core_xml(self) -> str:
#         root = ET.Element("cp:coreProperties", {"xmlns:cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties", "xmlns:dc": "http://purl.org/dc/elements/1.1/"})
#         ET.SubElement(root, "dc:title").text = self.options.page_name or "Diagram"
#         return _xml_plain(root)

#     def _xy(self, x: float, y: float) -> Tuple[float, float]:
#         return self.offset_x + (x - self.vb_x) * self.scale, self.offset_y + (self.vb_h - (y - self.vb_y)) * self.scale

#     def _size(self, width: float, height: float) -> Tuple[float, float]:
#         return max(0.02, abs(width) * self.scale), max(0.02, abs(height) * self.scale)

#     def _next_id(self) -> int:
#         self.shape_id += 1
#         return self.shape_id

#     def _cell(self, parent: ET.Element, name: str, value: Any, formula: Optional[str] = None) -> None:
#         attrs = {"N": name, "V": str(value)}
#         if formula:
#             attrs["F"] = formula
#         ET.SubElement(parent, _v("Cell"), attrs)

#     def _color_cell(self, parent: ET.Element, name: str, color: str) -> None:
#         r, g, b = _rgb(color)
#         ET.SubElement(parent, _v("Cell"), {"N": name, "V": _colour(color, "#000000"), "F": f"RGB({r},{g},{b})"})

#     def _validate_package(self, path: Path) -> None:
#         required = {"[Content_Types].xml", "_rels/.rels", "visio/document.xml", "visio/pages/pages.xml", "visio/pages/page1.xml", "visio/pages/_rels/pages.xml.rels", "visio/windows.xml"}
#         with zipfile.ZipFile(path, "r") as z:
#             missing = sorted(required - set(z.namelist()))
#             if missing:
#                 raise RuntimeError(f"Generated VSDX package is missing required parts: {missing}")


# # Helper functions

# def _parse_dot_metadata(dot_path: Path) -> DotMetadata:
#     labels: Dict[str, str] = {}
#     attrs_by_node: Dict[str, Dict[str, str]] = {}
#     edges: List[DotEdge] = []
#     if not dot_path.exists():
#         return DotMetadata(labels, attrs_by_node, [], [])
#     statements = _split_dot_statements(dot_path.read_text(encoding="utf-8", errors="replace"))
#     for statement in statements:
#         stripped = statement.strip().rstrip(";")
#         if not stripped or "->" in stripped or "--" in stripped or "[" not in stripped or "]" not in stripped:
#             continue
#         if stripped.lower().startswith(("digraph", "graph", "subgraph", "node ", "edge ")):
#             continue
#         prefix, raw_attrs, _ = _split_dot_attr_statement(stripped)
#         node_id = _clean_dot_id(prefix)
#         if not node_id:
#             continue
#         attrs = _parse_dot_attrs(raw_attrs)
#         attrs_by_node[node_id] = attrs
#         labels[node_id] = _clean_dot_label(attrs.get("label") or attrs.get("xlabel") or attrs.get("tooltip") or node_id) or node_id
#     for statement in statements:
#         stripped = statement.strip().rstrip(";")
#         if not stripped or ("->" not in stripped and "--" not in stripped):
#             continue
#         endpoints = _extract_edge_endpoints(stripped)
#         if len(endpoints) < 2:
#             continue
#         raw_attrs = ""
#         if "[" in stripped and "]" in stripped:
#             _, raw_attrs, _ = _split_dot_attr_statement(stripped)
#         attrs = _parse_dot_attrs(raw_attrs)
#         color = _colour(attrs.get("color"), "#666666")
#         label = _clean_dot_label(attrs.get("label") or attrs.get("xlabel") or "") or _make_edge_fallback_label(endpoints[0], endpoints[-1], labels)
#         edges.append(DotEdge(endpoints[0], endpoints[-1], color, label))
#     return DotMetadata(labels, attrs_by_node, _dedupe_legend_items([(e.color, e.label) for e in edges if e.label]), edges)


# def _filter_clusters(clusters: List[SvgCluster], nodes: List[SvgNode]) -> List[SvgCluster]:
#     if not clusters:
#         return []
#     result: List[SvgCluster] = []
#     seen = set()
#     node_centres = [((n.bbox[0] + n.bbox[2]) / 2.0, (n.bbox[1] + n.bbox[3]) / 2.0) for n in nodes]
#     for c in sorted(clusters, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]), reverse=True):
#         if not _cleanup_visible_text(c.label):
#             continue
#         x1, y1, x2, y2 = c.bbox
#         if not any(x1 <= cx <= x2 and y1 <= cy <= y2 for cx, cy in node_centres):
#             continue
#         key = (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), c.label.lower())
#         if key in seen:
#             continue
#         seen.add(key)
#         result.append(c)
#     return result


# def _auto_zones(nodes: List[SvgNode], opts: VisioExportOptions) -> List[SvgCluster]:
#     if not nodes:
#         return []
#     sorted_nodes = sorted(nodes, key=lambda n: (n.bbox[0] + n.bbox[2]) / 2.0)
#     onprem_re = re.compile(opts.on_prem_zone_regex, flags=re.I)
#     cloud_re = re.compile(opts.cloud_zone_regex, flags=re.I)
#     external_re = re.compile(opts.external_zone_regex, flags=re.I)
#     external_nodes = [n for n in sorted_nodes if external_re.search(n.label or "")]
#     onprem_nodes = [n for n in sorted_nodes if onprem_re.search(n.label or "") and n not in external_nodes]
#     cloud_nodes = [n for n in sorted_nodes if n not in external_nodes and n not in onprem_nodes and cloud_re.search(n.label or "")]
#     if not onprem_nodes:
#         first_cloud_idx = next((i for i, n in enumerate(sorted_nodes) if cloud_re.search(n.label or "")), len(sorted_nodes))
#         onprem_nodes = sorted_nodes[:max(0, first_cloud_idx)]
#     if not cloud_nodes:
#         cloud_nodes = [n for n in sorted_nodes if n not in onprem_nodes and n not in external_nodes]
#     zones: List[SvgCluster] = []
#     if onprem_nodes:
#         zones.append(_zone_from_nodes("auto_on_prem", opts.on_prem_zone_label, onprem_nodes, "#EFF6FF", opts.cluster_stroke, opts.cluster_text, pad=32))
#     if cloud_nodes:
#         zones.append(_zone_from_nodes("auto_cloud", opts.cloud_zone_label, cloud_nodes, opts.cluster_fill, opts.cluster_stroke, opts.cluster_text, pad=42))
#     if external_nodes:
#         zones.append(_zone_from_nodes("auto_external", opts.external_zone_label, external_nodes, "#F8FBFF", opts.cluster_stroke, opts.cluster_text, pad=28))
#     return zones


# def _zone_from_nodes(cluster_id: str, label: str, nodes: List[SvgNode], fill: str, stroke: str, text: str, pad: float = 36.0) -> SvgCluster:
#     x1 = min(n.bbox[0] for n in nodes) - pad
#     y1 = min(n.bbox[1] for n in nodes) - pad
#     x2 = max(n.bbox[2] for n in nodes) + pad
#     y2 = max(n.bbox[3] for n in nodes) + pad + 16
#     return SvgCluster(cluster_id, label, (x1, y1, x2, y2), fill, stroke, text)


# def _split_dot_statements(text: str) -> List[str]:
#     statements: List[str] = []
#     current: List[str] = []
#     in_quote = False
#     in_html = False
#     bracket_depth = 0
#     escape = False
#     for char in text:
#         current.append(char)
#         if escape:
#             escape = False
#             continue
#         if char == "\\":
#             escape = True
#             continue
#         if char == '"' and not in_html:
#             in_quote = not in_quote
#             continue
#         if char == "<" and not in_quote:
#             in_html = True
#         elif char == ">" and in_html and not in_quote:
#             in_html = False
#         elif char == "[" and not in_quote and not in_html:
#             bracket_depth += 1
#         elif char == "]" and not in_quote and not in_html:
#             bracket_depth = max(0, bracket_depth - 1)
#         elif char == ";" and not in_quote and not in_html and bracket_depth == 0:
#             st = "".join(current).strip()
#             if st:
#                 statements.append(st)
#             current = []
#     tail = "".join(current).strip()
#     if tail:
#         statements.append(tail)
#     return statements


# def _split_dot_attr_statement(statement: str) -> Tuple[str, str, str]:
#     start = statement.find("[")
#     end = statement.rfind("]")
#     if start < 0 or end < start:
#         return statement, "", ""
#     return statement[:start].strip(), statement[start + 1:end].strip(), statement[end + 1:].strip()


# def _parse_dot_attrs(raw: str) -> Dict[str, str]:
#     attrs: Dict[str, str] = {}
#     pattern = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*("(?:\\.|[^"])*"|<.*?>|[^,\]]+)', flags=re.S)
#     for key, value in pattern.findall(raw or ""):
#         attrs[key.strip().lower()] = _clean_dot_label(value)
#     return attrs


# def _extract_edge_endpoints(statement: str) -> List[str]:
#     no_attrs = re.sub(r"\[.*?\]", "", statement, flags=re.S).strip().rstrip(";")
#     return [_clean_dot_id(part) for part in re.split(r"->|--", no_attrs) if _clean_dot_id(part)]


# def _clean_dot_id(value: str) -> str:
#     return _cleanup_visible_text(str(value or "").strip().rstrip(";").strip().strip('"').strip("'"))


# def _clean_dot_label(value: str) -> str:
#     return _cleanup_visible_text(str(value or "").strip().strip('"').strip("'"))


# def _cleanup_visible_text(value: str) -> str:
#     text = html.unescape(str(value or ""))
#     text = text.replace("\\n", " ").replace("\\l", " ").replace("\\r", " ")
#     text = re.sub(r"\\+", " ", text)
#     text = re.sub(r"<\s*br\s*/?\s*>", " ", text, flags=re.I)
#     text = re.sub(r"</?\s*b\s*>", "", text, flags=re.I)
#     text = re.sub(r"<[^>]+>", "", text)
#     text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
#     text = re.sub(r"\s+", " ", text)
#     return text.strip()


# def _make_edge_fallback_label(source: str, target: str, labels: Dict[str, str]) -> str:
#     src = labels.get(source, source).strip()
#     dst = labels.get(target, target).strip()
#     return f"{src} to {dst}" if src and dst else ""


# def _extract_icon_from_candidates(candidates: List[str], base_dir: Path, label: str) -> str:
#     if Image is None:
#         return ""
#     card = _resolve_first_raster(candidates, base_dir)
#     if not card:
#         return ""
#     try:
#         src = Path(card)
#         out = Path(os.getenv("TMPDIR", "/tmp")) / f"vsdx_icon_{abs(hash((str(src), label)))}.png"
#         if out.exists():
#             return str(out)
#         with Image.open(src).convert("RGBA") as img:  # type: ignore[union-attr]
#             w, h = img.size
#             crop = img.crop((int(w * 0.30), int(h * 0.03), int(w * 0.70), int(h * 0.43)))
#             crop.thumbnail((160, 120), Image.LANCZOS)
#             canvas = Image.new("RGBA", (160, 120), (255, 255, 255, 0))
#             canvas.paste(crop, ((160 - crop.width) // 2, (120 - crop.height) // 2), crop)
#             canvas.save(out)
#         return str(out)
#     except Exception:
#         logger.exception("Failed extracting fallback icon from card image. label=%r", label)
#         return ""


# def _resolve_first_raster(candidates: List[str], base_dir: Path) -> str:
#     for candidate in candidates:
#         path = _resolve_raster_path(candidate, base_dir)
#         if path:
#             return str(path)
#     return ""


# def _resolve_raster_path(href: Any, base_dir: Path) -> Optional[Path]:
#     if not href:
#         return None
#     raw = str(href).strip().strip('"').strip("'")
#     if raw.startswith("data:image/") or raw.startswith(("http://", "https://")):
#         return None
#     path = Path(unquote(raw))
#     if not path.is_absolute():
#         path = base_dir / path
#     try:
#         path = path.resolve()
#     except Exception:
#         pass
#     if not path.exists() or not path.is_file():
#         return None
#     if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
#         return None
#     return path


# def _can_vectorize_icon(path: str) -> bool:
#     return Image is not None and bool(_resolve_raster_path(path, Path.cwd()))


# def _icon_mosaic_cells(path: str, grid: int = 28) -> List[Tuple[int, int, str]]:
#     resolved = _resolve_raster_path(path, Path.cwd())
#     if Image is None or not resolved:
#         return []
#     try:
#         with Image.open(resolved).convert("RGBA") as img:  # type: ignore[union-attr]
#             grid = max(22, min(32, int(grid or 28)))
#             if ImageEnhance is not None:
#                 img = ImageEnhance.Color(img).enhance(2.0)
#                 img = ImageEnhance.Contrast(img).enhance(1.9)
#                 img = ImageEnhance.Brightness(img).enhance(0.78)
#             bbox = img.getbbox()
#             if bbox:
#                 img = img.crop(bbox)
#             img.thumbnail((grid, grid), Image.LANCZOS)
#             canvas = Image.new("RGBA", (grid, grid), (255, 255, 255, 0))
#             canvas.paste(img, ((grid - img.width) // 2, (grid - img.height) // 2), img)
#             pix = canvas.load()
#             cells: List[Tuple[int, int, str]] = []
#             for y in range(grid):
#                 for x in range(grid):
#                     r, g, b, a = pix[x, y]
#                     if a < 40:
#                         continue
#                     if r > 250 and g > 250 and b > 250:
#                         continue
#                     if a < 235:
#                         mix = max(a / 255.0, 0.68)
#                         r = int(r * mix + 255 * (1 - mix))
#                         g = int(g * mix + 255 * (1 - mix))
#                         b = int(b * mix + 255 * (1 - mix))
#                     lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
#                     if lum > 180:
#                         factor = 180.0 / max(lum, 1.0)
#                         r, g, b = int(r * factor), int(g * factor), int(b * factor)
#                     r = max(0, min(255, int(round(r / 8.0) * 8)))
#                     g = max(0, min(255, int(round(g / 8.0) * 8)))
#                     b = max(0, min(255, int(round(b / 8.0) * 8)))
#                     if r > 248 and g > 248 and b > 248:
#                         continue
#                     cells.append((x, y, f"#{r:02X}{g:02X}{b:02X}"))
#             return cells
#     except Exception:
#         logger.exception("Failed to vectorize icon: %s", path)
#         return []


# def _node_visual_style(label: str, seed: str, attrs: Dict[str, str]) -> Dict[str, str]:
#     if get_style_for_label is not None:
#         try:
#             style = get_style_for_label(_normalise_label_for_lookup(label or seed))  # type: ignore[misc]
#             fill = _colour(attrs.get("fillcolor") or style.get("fill"), _pastel_color(seed))
#             border = _colour(attrs.get("color") or style.get("border"), _darker_border(fill))
#             font = _colour(style.get("font"), "#000000")
#             if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#                 fill = _pastel_color(seed)
#                 border = _darker_border(fill)
#             return {"fill": fill, "border": border, "font": font}
#         except Exception:
#             pass
#     fill = _colour(attrs.get("fillcolor"), _pastel_color(seed))
#     if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#         fill = _pastel_color(seed)
#     border = _colour(attrs.get("color"), _darker_border(fill))
#     return {"fill": fill, "border": border, "font": "#000000"}


# def _resolve_icon_path(label: str) -> str:
#     if resolve_icon_from_node_label is None:
#         return ""
#     lookup_values: List[str] = []
#     raw_label = _cleanup_visible_text(label)
#     lookup_values.extend([raw_label, _normalise_label_for_lookup(raw_label), raw_label.replace("_", " "), raw_label.replace("_", "")])
#     if clean_label is not None:
#         try:
#             cleaned = clean_label(raw_label)  # type: ignore[misc]
#             lookup_values.extend([cleaned, _normalise_label_for_lookup(cleaned)])
#         except Exception:
#             pass
#     seen = set()
#     for candidate in lookup_values:
#         candidate = str(candidate or "").strip()
#         if not candidate or candidate.lower() in seen:
#             continue
#         seen.add(candidate.lower())
#         try:
#             icon = resolve_icon_from_node_label(candidate, PROJECT_ROOT)  # type: ignore[misc]
#             if not icon:
#                 continue
#             if normalize_icon_for_graphviz is not None:
#                 try:
#                     icon = normalize_icon_for_graphviz(str(icon))  # type: ignore[misc]
#                 except Exception:
#                     logger.exception("Failed to normalize VSDX icon. label=%r icon=%s", candidate, icon)
#             resolved = _resolve_raster_path(str(icon), Path.cwd())
#             if resolved:
#                 logger.info("[VSDX_ICON] Resolved icon for label=%r -> %s", candidate, resolved)
#                 return str(resolved)
#         except Exception:
#             logger.exception("[VSDX_ICON] Icon resolution failed for label=%r", candidate)
#     return ""


# def _normalise_label_for_lookup(label: str) -> str:
#     text = _cleanup_visible_text(label).replace("_", " ").replace("-", " ")
#     text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
#     return re.sub(r"\s+", " ", text).strip()


# def _icon_abbrev(label: str) -> str:
#     clean = _normalise_label_for_lookup(label)
#     words = [w for w in re.split(r"\s+", clean) if w]
#     if not words:
#         return "•"
#     if len(words) == 1:
#         return words[0][:2].upper()
#     return "".join(word[0] for word in words[:2]).upper()


# def _wrap_label(label: str) -> str:
#     if clean_label is not None:
#         try:
#             text = clean_label(label)  # type: ignore[misc]
#         except Exception:
#             text = _cleanup_visible_text(label).replace("_", " ")
#     else:
#         text = _cleanup_visible_text(label).replace("_", " ")
#     words = text.split()
#     if len(words) <= 2:
#         return text
#     if len(words) <= 4:
#         mid = (len(words) + 1) // 2
#         return " ".join(words[:mid]) + "\n" + " ".join(words[mid:])
#     mid = max(2, len(words) // 2)
#     return " ".join(words[:mid]) + "\n" + " ".join(words[mid:])


# def _run_graphviz(dot: Path, out: Path, fmt: str, engine: str) -> None:
#     result = subprocess.run([engine, f"-T{fmt}", str(dot), "-o", str(out)], capture_output=True, text=True, check=False)
#     if result.returncode != 0:
#         raise RuntimeError(f"Graphviz failed for {fmt}:\n{result.stderr or result.stdout}")


# def _iter_svg(root: ET.Element) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
#     def walk(elem: ET.Element, parent_matrix: Matrix, parent_classes: List[str]) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
#         matrix = _matmul(parent_matrix, _transform(elem.get("transform")))
#         classes = _class_tokens(elem.get("class"))
#         yield elem, matrix, parent_classes
#         for child in list(elem):
#             yield from walk(child, matrix, parent_classes + classes)
#     yield from walk(root, IDENTITY, [])


# def _class_tokens(value: Optional[str]) -> List[str]:
#     return [token.strip().lower() for token in re.split(r"\s+", value or "") if token.strip()]


# def _transform(raw: Optional[str]) -> Matrix:
#     if not raw:
#         return IDENTITY
#     matrix = IDENTITY
#     for name, args in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", raw):
#         nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", args)]
#         local = IDENTITY
#         if name == "matrix" and len(nums) >= 6:
#             local = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
#         elif name == "translate":
#             local = (1.0, 0.0, 0.0, 1.0, nums[0] if nums else 0.0, nums[1] if len(nums) > 1 else 0.0)
#         elif name == "scale":
#             sx = nums[0] if nums else 1.0
#             sy = nums[1] if len(nums) > 1 else sx
#             local = (sx, 0.0, 0.0, sy, 0.0, 0.0)
#         elif name == "rotate" and nums:
#             angle = math.radians(nums[0])
#             c, s = math.cos(angle), math.sin(angle)
#             local = (c, s, -s, c, 0.0, 0.0)
#         matrix = _matmul(matrix, local)
#     return matrix


# def _matmul(a: Matrix, b: Matrix) -> Matrix:
#     a1, b1, c1, d1, e1, f1 = a
#     a2, b2, c2, d2, e2, f2 = b
#     return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


# def _apply(matrix: Matrix, x: float, y: float) -> Tuple[float, float]:
#     a, b, c, d, e, f = matrix
#     return a * x + c * y + e, b * x + d * y + f


# def _style(elem: ET.Element) -> Dict[str, str]:
#     result: Dict[str, str] = {}
#     for part in (elem.get("style") or "").split(";"):
#         if ":" in part:
#             key, value = part.split(":", 1)
#             result[key.strip().lower()] = value.strip()
#     for key, value in elem.attrib.items():
#         if key.lower() in {"fill", "stroke", "stroke-width", "font-size", "font-weight", "text-anchor"}:
#             result[key.lower()] = value
#     return result


# def _title(group: ET.Element) -> str:
#     title = group.find(_svg("title"))
#     return _read_text(title) if title is not None else ""


# def _read_text(elem: Optional[ET.Element]) -> str:
#     if elem is None:
#         return ""
#     parts: List[str] = []
#     if elem.text:
#         parts.append(elem.text)
#     for child in list(elem):
#         child_text = _read_text(child)
#         if child_text:
#             parts.append(child_text)
#         if child.tail:
#             parts.append(child.tail)
#     return html.unescape(" ".join(p.strip() for p in parts if p and p.strip())).strip()


# def _svg_href(elem: ET.Element) -> str:
#     return (elem.get("href") or elem.get(_xlink("href")) or elem.get("xlink:href") or "").strip()


# def _rect_points(elem: ET.Element, matrix: Matrix) -> List[Tuple[float, float]]:
#     x, y = _num(elem.get("x"), 0.0), _num(elem.get("y"), 0.0)
#     w, h = _num(elem.get("width"), 0.0), _num(elem.get("height"), 0.0)
#     if w <= 0 or h <= 0:
#         return []
#     return [_apply(matrix, x, y), _apply(matrix, x + w, y), _apply(matrix, x + w, y + h), _apply(matrix, x, y + h)]


# def _points(raw: str) -> List[Tuple[float, float]]:
#     nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw or "")]
#     return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


# def _path_points(raw: str) -> List[Tuple[float, float]]:
#     return _points(raw)


# def _simplify_route(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
#     if len(points) <= 2:
#         return points
#     start, end = points[0], points[-1]
#     mid = points[len(points) // 2]
#     if abs(mid[0] - start[0]) > 8 and abs(mid[1] - end[1]) > 8:
#         return [start, mid, end]
#     return [start, end]


# def _bbox(points: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
#     xs, ys = [p[0] for p in points], [p[1] for p in points]
#     return min(xs), min(ys), max(xs), max(ys)


# def _num(value: Any, default: float = 0.0) -> float:
#     try:
#         return float(re.sub(r"(px|pt|in|cm|mm|%)$", "", str(value).strip(), flags=re.I))
#     except Exception:
#         return default


# def _colour(value: Any, default: str) -> str:
#     raw = str(value or "").strip()
#     if not raw:
#         return default
#     if raw.lower() in {"none", "transparent"}:
#         return "#FFFFFF"
#     named = {"black": "#000000", "white": "#FFFFFF", "red": "#FF0000", "green": "#008000", "blue": "#0000FF", "gray": "#808080", "grey": "#808080", "orange": "#FFA500", "purple": "#800080", "yellow": "#FFFF00", "cyan": "#00FFFF", "magenta": "#FF00FF", "brown": "#A52A2A", "pink": "#FFC0CB", "teal": "#008080"}
#     if raw.lower() in named:
#         return named[raw.lower()]
#     if raw.startswith("#"):
#         if len(raw) == 4:
#             return "#" + "".join(ch * 2 for ch in raw[1:]).upper()
#         return raw[:7].upper()
#     rgb = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", raw, flags=re.I)
#     if rgb:
#         return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in rgb.groups())
#     return default


# def _rgb(color: str) -> Tuple[int, int, int]:
#     color = _colour(color, "#000000")
#     return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


# def _pt(value: float) -> float:
#     return max(0.01, float(value) / PT_PER_INCH)


# def _is_near_black(color: str) -> bool:
#     try:
#         r, g, b = _rgb(color)
#         return r < 24 and g < 24 and b < 24
#     except Exception:
#         return False


# def _pastel_color(seed: Any) -> str:
#     palette = ["#E8F0FE", "#E6F4EA", "#FEF7E0", "#FCE8E6", "#F3E8FD", "#E0F2F1", "#FFF3E0", "#E8EAED", "#E3F2FD", "#F1F8E9"]
#     value = sum(ord(ch) for ch in str(seed or "node"))
#     return palette[value % len(palette)]


# def _darker_border(fill: str) -> str:
#     try:
#         r, g, b = _rgb(fill)
#         return f"#{int(r * 0.72):02X}{int(g * 0.72):02X}{int(b * 0.72):02X}"
#     except Exception:
#         return "#666666"


# def _lighten(color: str, factor: float = 0.35) -> str:
#     try:
#         r, g, b = _rgb(color)
#         return f"#{int(r + (255-r)*factor):02X}{int(g + (255-g)*factor):02X}{int(b + (255-b)*factor):02X}"
#     except Exception:
#         return "#FFFFFF"


# def _dedupe_legend_items(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
#     result: List[Tuple[str, str]] = []
#     seen = set()
#     for color, label in items or []:
#         safe_color = _colour(color, "#666666")
#         safe_label = _cleanup_visible_text(label)
#         if not safe_label:
#             continue
#         key = (safe_color.lower(), safe_label.lower())
#         if key in seen:
#             continue
#         seen.add(key)
#         result.append((safe_color, safe_label))
#     return result


# def _local(tag: str) -> str:
#     return str(tag).split("}", 1)[-1].lower()


# def _safe(value: str) -> str:
#     return re.sub(r"[^A-Za-z0-9_. -]+", "_", str(value or "Shape"))[:120] or "Shape"


# def _xml(root: ET.Element) -> str:
#     return "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + ET.tostring(root, encoding="unicode")


# def _xml_plain(root: ET.Element) -> str:
#     return "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + ET.tostring(root, encoding="unicode")


# __all__ = ["VisioExportOptions", "export_vsdx_from_dot", "export_vsdx_from_svg"]





# from __future__ import annotations

# """
# visio_vsdx_exporter.py

# Generic Graphviz DOT/SVG -> editable Visio VSDX exporter.

# Public API retained:
# - VisioExportOptions
# - export_vsdx_from_dot(...)
# - export_vsdx_from_svg(...)

# Fixes in this version:
# - No service-name, project-name, section-name, or node-label hardcoding.
# - DOT edge semantics are the source of truth for connector direction.
#   A DOT edge `source -> target` always renders as source-to-target in Visio.
# - No coordinate/SVG-arrow-polygon based endpoint reversal.
# - Accidental two-sided arrows are prevented. `dir=both` is the only case where both arrowheads are used.
# - Process/data-flow views do not fail when the SVG parser detects no editable nodes; DOT metadata fallback is used.
# - Icons remain visible using compact editable vector cells when raster icons resolve; otherwise a visible abbreviation is shown.
# - Icons are easier to click because icon cells are selection-locked.
# - Connectors are recomputed against current card boundaries after layout reflow.
# - Zones/clusters are expanded after reflow so cards stay inside containers.
# - Flow legend is retained.
# """

# import html
# import logging
# import math
# import os
# import re
# import shutil
# import subprocess
# import zipfile
# from dataclasses import dataclass
# from pathlib import Path
# from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
# from urllib.parse import unquote
# from xml.etree import ElementTree as ET

# logger = logging.getLogger(__name__)

# try:
#     from PIL import Image, ImageEnhance
# except Exception:  # pragma: no cover
#     Image = None  # type: ignore
#     ImageEnhance = None  # type: ignore

# try:
#     from .config import PROJECT_ROOT  # type: ignore
# except Exception:
#     PROJECT_ROOT = Path.cwd()  # type: ignore

# try:
#     from .icon_resolver import get_style_for_label, resolve_icon_from_node_label  # type: ignore
# except Exception:
#     get_style_for_label = None  # type: ignore
#     resolve_icon_from_node_label = None  # type: ignore

# try:
#     from .node_card import clean_label, normalize_icon_for_graphviz  # type: ignore
# except Exception:
#     clean_label = None  # type: ignore
#     normalize_icon_for_graphviz = None  # type: ignore

# V_NS = "http://schemas.microsoft.com/office/visio/2012/main"
# R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
# PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
# VISIO_REL_NS = "http://schemas.microsoft.com/visio/2010/relationships"
# SVG_NS = "http://www.w3.org/2000/svg"
# XLINK_NS = "http://www.w3.org/1999/xlink"
# PT_PER_INCH = 72.0
# Matrix = Tuple[float, float, float, float, float, float]
# IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
# ET.register_namespace("", V_NS)
# ET.register_namespace("r", R_NS)


# def _v(tag: str) -> str:
#     return f"{{{V_NS}}}{tag}"


# def _r(tag: str) -> str:
#     return f"{{{R_NS}}}{tag}"


# def _svg(tag: str) -> str:
#     return f"{{{SVG_NS}}}{tag}"


# def _xlink(tag: str) -> str:
#     return f"{{{XLINK_NS}}}{tag}"


# @dataclass
# class VisioExportOptions:
#     page_name: str = "Diagram"
#     page_width_in: Optional[float] = None
#     page_height_in: Optional[float] = None
#     include_visual_background: bool = False
#     include_editable_overlay: bool = True
#     lock_visual_background: bool = False
#     overlay_boxes_visible: bool = True
#     overlay_arrows_visible: bool = True
#     overlay_text_visible: bool = False
#     include_icons: bool = True
#     include_flow_legend: bool = True
#     legend_on_separate_page: bool = False
#     legend_items: Optional[List[Tuple[str, str]]] = None
#     node_font_size_pt: float = 13.0
#     node_text_bold: bool = True
#     connector_arrow_type: int = 4
#     connector_arrow_size: int = 2
#     min_page_width_in: float = 11.0
#     min_page_height_in: float = 8.5
#     fail_on_no_nodes: bool = True

#     min_node_width_in: float = 1.55
#     min_node_height_in: float = 1.05
#     max_node_width_in: float = 2.65
#     max_node_height_in: float = 1.52
#     min_label_band_height_in: float = 0.36
#     max_icon_size_in: float = 0.62

#     compact_vector_icons: bool = True
#     compact_icon_grid: int = 12
#     max_icon_vector_cells: int = 44
#     lock_icon_cells: bool = True
#     include_icon_badge: bool = True
#     embed_icons_as_pictures: bool = False

#     legend_font_size_pt: float = 10.5
#     legend_title_font_size_pt: float = 14.0
#     legend_row_height_in: float = 0.42
#     legend_arrow_length_in: float = 1.05

#     include_auto_zones: bool = True
#     auto_zone_only_when_no_clusters: bool = True
#     auto_zone_labels: Optional[List[str]] = None
#     zone_attribute_names: Tuple[str, ...] = ("zone", "group", "platform", "environment", "domain", "lane")
#     enable_positional_auto_zones: bool = False
#     max_auto_zones: int = 4
#     zone_gap_factor: float = 2.75
#     default_auto_zone_label: str = "Architecture Zone"
#     cluster_fill: str = "#EEF6FF"
#     cluster_stroke: str = "#A8C7FA"
#     cluster_text: str = "#174EA6"
#     zone_header_px: float = 96.0
#     zone_padding_px: float = 58.0
#     cluster_title_height_in: float = 0.34
#     cluster_title_top_margin_in: float = 0.10

#     shape_warning_limit: int = 900
#     resolve_node_overlaps: bool = True
#     prefer_horizontal_reflow: bool = True
#     node_collision_margin_in: float = 0.24
#     node_collision_iterations: int = 260
#     row_group_tolerance_in: float = 0.75
#     cluster_reflow_padding_in: float = 0.30


# @dataclass
# class DotEdge:
#     source: str
#     target: str
#     color: str
#     label: str
#     direction: str = "forward"


# @dataclass
# class DotMetadata:
#     labels: Dict[str, str]
#     attrs: Dict[str, Dict[str, str]]
#     legend_items: List[Tuple[str, str]]
#     edges: List[DotEdge]


# @dataclass
# class SvgNode:
#     node_id: str
#     label: str
#     bbox: Tuple[float, float, float, float]
#     fill: str
#     stroke: str
#     stroke_width: float = 1.0
#     image_href: str = ""
#     icon_path: str = ""
#     icon_text: str = ""
#     font_color: str = "#000000"
#     attrs: Optional[Dict[str, str]] = None


# @dataclass
# class SvgEdge:
#     edge_id: str
#     points: List[Tuple[float, float]]
#     color: str = "#666666"
#     width: float = 1.25
#     source: str = ""
#     target: str = ""
#     direction: str = "forward"
#     label: str = ""


# @dataclass
# class SvgCluster:
#     cluster_id: str
#     label: str
#     bbox: Tuple[float, float, float, float]
#     fill: str = "#EEF6FF"
#     stroke: str = "#A8C7FA"
#     font_color: str = "#174EA6"


# @dataclass
# class SvgDiagram:
#     svg_path: Path
#     width_px: float
#     height_px: float
#     viewbox: Tuple[float, float, float, float]
#     nodes: List[SvgNode]
#     edges: List[SvgEdge]
#     clusters: List[SvgCluster]


# def export_vsdx_from_dot(
#     dot_path: os.PathLike | str,
#     vsdx_path: Optional[os.PathLike | str] = None,
#     *,
#     output_vsdx_path: Optional[os.PathLike | str] = None,
#     svg_path: Optional[os.PathLike | str] = None,
#     png_path: Optional[os.PathLike | str] = None,
#     options: Optional[VisioExportOptions] = None,
#     layout_engine: str = "dot",
#     **_: Any,
# ) -> Path:
#     dot = Path(dot_path)
#     out = Path(output_vsdx_path or vsdx_path or dot.with_suffix(".vsdx"))
#     opts = _normalise_options(options or VisioExportOptions())
#     svg = Path(svg_path) if svg_path else out.with_suffix(".svg")
#     if not svg.exists():
#         _run_graphviz(dot, svg, "svg", layout_engine)

#     metadata = _parse_dot_metadata(dot)
#     opts.legend_items = _dedupe_legend_items(opts.legend_items or []) or metadata.legend_items

#     # Do not fail at SVG stage. Process/data-flow SVGs can have different group structures.
#     diagram = SvgParser(svg, metadata, fail_on_no_nodes=False, options=opts).parse()

#     if not diagram.nodes:
#         diagram.nodes = _fallback_nodes_from_dot_metadata(metadata)
#         if opts.include_auto_zones and diagram.nodes:
#             diagram.clusters = _auto_zones(diagram.nodes, opts)

#     # Always prefer DOT semantic edges for connector direction. SVG route geometry is only a visual hint.
#     diagram.edges = _merge_svg_routes_with_dot_edges(metadata, diagram.nodes, diagram.edges)

#     if opts.fail_on_no_nodes and not diagram.nodes:
#         raise RuntimeError(f"VSDX export failed: no editable nodes detected from SVG or DOT: {svg}")
#     return VsdxWriter(diagram, out, opts).write()


# def export_vsdx_from_svg(
#     svg_path: os.PathLike | str,
#     output_vsdx_path: os.PathLike | str,
#     *,
#     png_path: Optional[os.PathLike | str] = None,
#     options: Optional[VisioExportOptions] = None,
# ) -> Path:
#     opts = _normalise_options(options or VisioExportOptions())
#     diagram = SvgParser(Path(svg_path), DotMetadata({}, {}, [], []), fail_on_no_nodes=opts.fail_on_no_nodes, options=opts).parse()
#     return VsdxWriter(diagram, Path(output_vsdx_path), opts).write()


# def _normalise_options(opts: VisioExportOptions) -> VisioExportOptions:
#     opts.include_icons = bool(getattr(opts, "include_icons", True))
#     opts.include_flow_legend = bool(getattr(opts, "include_flow_legend", True))
#     opts.compact_vector_icons = bool(getattr(opts, "compact_vector_icons", True))
#     opts.lock_icon_cells = bool(getattr(opts, "lock_icon_cells", True))
#     opts.embed_icons_as_pictures = bool(getattr(opts, "embed_icons_as_pictures", False))
#     opts.node_font_size_pt = max(float(getattr(opts, "node_font_size_pt", 13.0) or 13.0), 13.0)
#     opts.max_icon_size_in = max(0.46, min(0.72, float(getattr(opts, "max_icon_size_in", 0.62) or 0.62)))
#     opts.compact_icon_grid = max(8, min(16, int(getattr(opts, "compact_icon_grid", 12) or 12)))
#     opts.max_icon_vector_cells = max(12, min(60, int(getattr(opts, "max_icon_vector_cells", 44) or 44)))
#     opts.node_collision_margin_in = max(0.05, min(0.60, float(getattr(opts, "node_collision_margin_in", 0.24) or 0.24)))
#     opts.node_collision_iterations = max(20, min(800, int(getattr(opts, "node_collision_iterations", 260) or 260)))
#     opts.row_group_tolerance_in = max(0.20, min(1.50, float(getattr(opts, "row_group_tolerance_in", 0.75) or 0.75)))
#     opts.cluster_reflow_padding_in = max(0.08, min(0.80, float(getattr(opts, "cluster_reflow_padding_in", 0.30) or 0.30)))
#     opts.zone_header_px = max(60.0, min(160.0, float(getattr(opts, "zone_header_px", 96.0) or 96.0)))
#     opts.zone_padding_px = max(36.0, min(130.0, float(getattr(opts, "zone_padding_px", 58.0) or 58.0)))
#     opts.shape_warning_limit = max(200, int(getattr(opts, "shape_warning_limit", 900) or 900))
#     return opts


# class SvgParser:
#     def __init__(self, svg_path: Path, dot_metadata: DotMetadata, fail_on_no_nodes: bool = True, options: Optional[VisioExportOptions] = None):
#         self.svg_path = Path(svg_path)
#         self.dot_metadata = dot_metadata
#         self.fail_on_no_nodes = fail_on_no_nodes
#         self.options = options or VisioExportOptions()
#         self.root = ET.parse(str(svg_path)).getroot()
#         self.viewbox = self._viewbox()
#         self.width_px = _num(self.root.get("width"), self.viewbox[2])
#         self.height_px = _num(self.root.get("height"), self.viewbox[3])

#     def parse(self) -> SvgDiagram:
#         nodes: List[SvgNode] = []
#         edges: List[SvgEdge] = []
#         clusters: List[SvgCluster] = []
#         for elem, matrix, _parents in _iter_svg(self.root):
#             if _local(elem.tag) != "g":
#                 continue
#             classes = _class_tokens(elem.get("class"))
#             if self._is_cluster_group(elem, classes):
#                 cluster = self._parse_cluster(elem, matrix)
#                 if cluster and not self._is_graph_sized(cluster.bbox):
#                     clusters.append(cluster)
#             elif "node" in classes:
#                 node = self._parse_node(elem, matrix)
#                 if node and not self._is_graph_sized(node.bbox):
#                     nodes.append(node)
#             elif "edge" in classes:
#                 edge = self._parse_edge(elem, matrix)
#                 if edge:
#                     edges.append(edge)

#         if not nodes and self.dot_metadata.labels:
#             nodes = _fallback_nodes_from_dot_metadata(self.dot_metadata)

#         clusters = _filter_clusters(clusters, nodes, self.options)
#         if self.options.include_auto_zones and nodes and (not clusters or not self.options.auto_zone_only_when_no_clusters):
#             clusters.extend(_auto_zones(nodes, self.options))
#             clusters = _filter_clusters(clusters, nodes, self.options)

#         if not edges and self.dot_metadata.edges:
#             edges = _fallback_edges_from_dot_metadata(self.dot_metadata, nodes)

#         if not nodes and self.fail_on_no_nodes:
#             raise RuntimeError(f"VSDX export failed: no editable nodes detected from SVG or DOT: {self.svg_path}")
#         return SvgDiagram(self.svg_path, self.width_px, self.height_px, self.viewbox, nodes, edges, clusters)

#     def _viewbox(self) -> Tuple[float, float, float, float]:
#         raw = self.root.get("viewBox") or self.root.get("viewbox")
#         if raw:
#             vals = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)]
#             if len(vals) >= 4:
#                 return vals[0], vals[1], vals[2], vals[3]
#         return 0.0, 0.0, _num(self.root.get("width"), 1000.0), _num(self.root.get("height"), 800.0)

#     def _is_graph_sized(self, bbox: Tuple[float, float, float, float]) -> bool:
#         x1, y1, x2, y2 = bbox
#         return abs((x2 - x1) * (y2 - y1)) > max(1.0, self.viewbox[2] * self.viewbox[3]) * 0.85

#     def _is_cluster_group(self, elem: ET.Element, classes: List[str]) -> bool:
#         if "cluster" in classes:
#             return True
#         if any(token in classes for token in ("node", "edge")):
#             return False
#         title = (_title(elem) or "").lower()
#         return title.startswith("cluster") or title.startswith("subgraph")

#     def _parse_cluster(self, group: ET.Element, matrix: Matrix) -> Optional[SvgCluster]:
#         title = _title(group) or f"cluster_{id(group)}"
#         label = ""
#         bodies: List[Tuple[float, float, float, float, str, str]] = []
#         for child in group.iter():
#             tag = _local(child.tag)
#             style = _style(child)
#             fill = _colour(style.get("fill") or child.get("fill"), self.options.cluster_fill)
#             stroke = _colour(style.get("stroke") or child.get("stroke"), self.options.cluster_stroke)
#             points: List[Tuple[float, float]] = []
#             if tag == "polygon":
#                 points = [_apply(matrix, x, y) for x, y in _points(child.get("points") or "")]
#             elif tag == "rect":
#                 points = _rect_points(child, matrix)
#             elif tag == "text":
#                 t = _cleanup_visible_text(_read_text(child))
#                 if t:
#                     label = t
#             if points:
#                 x1, y1, x2, y2 = _bbox(points)
#                 if abs(x2 - x1) > 15 and abs(y2 - y1) > 15:
#                     bodies.append((x1, y1, x2, y2, fill, stroke))
#         if not bodies:
#             return None
#         body = max(bodies, key=lambda b: abs((b[2] - b[0]) * (b[3] - b[1])))
#         fill = self.options.cluster_fill if _is_near_black(body[4]) else body[4]
#         stroke = self.options.cluster_stroke if _is_near_black(body[5]) else body[5]
#         return SvgCluster(title, label or title, (body[0], body[1], body[2], body[3]), fill, stroke, self.options.cluster_text)

#     def _parse_node(self, group: ET.Element, matrix: Matrix) -> Optional[SvgNode]:
#         title = _title(group) or f"node_{id(group)}"
#         dot_attrs = self.dot_metadata.attrs.get(title, {})
#         dot_label = self.dot_metadata.labels.get(title, title)
#         base_style = _node_visual_style(dot_label, title, dot_attrs)
#         bodies: List[Tuple[float, float, float, float, str, str, float, str]] = []
#         texts: List[str] = []
#         image_candidates: List[str] = []
#         if dot_attrs.get("image"):
#             image_candidates.append(dot_attrs.get("image", ""))
#         for child in group.iter():
#             tag = _local(child.tag)
#             style = _style(child)
#             fill = _colour(style.get("fill") or child.get("fill") or dot_attrs.get("fillcolor"), base_style["fill"])
#             stroke = _colour(style.get("stroke") or child.get("stroke") or dot_attrs.get("color"), base_style["border"])
#             stroke_width = max(0.75, _num(style.get("stroke-width") or child.get("stroke-width") or dot_attrs.get("penwidth"), 1.0))
#             points: List[Tuple[float, float]] = []
#             image_href = ""
#             if tag == "polygon":
#                 points = [_apply(matrix, x, y) for x, y in _points(child.get("points") or "")]
#             elif tag == "rect":
#                 points = _rect_points(child, matrix)
#             elif tag == "ellipse":
#                 cx, cy = _num(child.get("cx"), 0.0), _num(child.get("cy"), 0.0)
#                 rx, ry = _num(child.get("rx"), 0.0), _num(child.get("ry"), 0.0)
#                 points = [_apply(matrix, cx - rx, cy - ry), _apply(matrix, cx + rx, cy + ry)]
#             elif tag == "image":
#                 image_href = _svg_href(child)
#                 if image_href:
#                     image_candidates.append(image_href)
#                 x, y = _num(child.get("x"), 0.0), _num(child.get("y"), 0.0)
#                 width, height = _num(child.get("width"), 0.0), _num(child.get("height"), 0.0)
#                 if width > 0 and height > 0:
#                     points = [_apply(matrix, x, y), _apply(matrix, x + width, y), _apply(matrix, x + width, y + height), _apply(matrix, x, y + height)]
#                     fill, stroke = base_style["fill"], base_style["border"]
#             elif tag == "text":
#                 t = _cleanup_visible_text(_read_text(child))
#                 if t:
#                     texts.append(t)
#             if points:
#                 x1, y1, x2, y2 = _bbox(points)
#                 if abs(x2 - x1) > 4 and abs(y2 - y1) > 4 and not self._is_graph_sized((x1, y1, x2, y2)):
#                     if _is_near_black(fill) or fill.upper() == "#FFFFFF":
#                         fill, stroke = base_style["fill"], base_style["border"]
#                     bodies.append((x1, y1, x2, y2, fill, stroke, stroke_width, image_href))
#         label = _cleanup_visible_text(" ".join(texts) or dot_label)
#         if not bodies:
#             return None
#         body = max(bodies, key=lambda b: abs((b[2] - b[0]) * (b[3] - b[1])))
#         icon_path = _resolve_icon_path(label) or _extract_icon_from_candidates(image_candidates, self.svg_path.parent, label)
#         return SvgNode(title, label or title, (body[0], body[1], body[2], body[3]), body[4], body[5], body[6], body[7], icon_path, _icon_abbrev(label), base_style.get("font", "#000000"), dot_attrs)

#     def _parse_edge(self, group: ET.Element, matrix: Matrix) -> Optional[SvgEdge]:
#         title = _title(group) or f"edge_{id(group)}"
#         color = "#666666"
#         width = 1.25
#         all_points: List[Tuple[float, float]] = []
#         for path in group.findall(f".//{_svg('path')}"):
#             style = _style(path)
#             color = _colour(style.get("stroke") or path.get("stroke"), color)
#             width = max(1.0, _num(style.get("stroke-width") or path.get("stroke-width"), width))
#             path_points = [_apply(matrix, x, y) for x, y in _path_points(path.get("d") or "")]
#             if path_points:
#                 all_points = path_points
#                 break
#         simple = _simplify_route(all_points)
#         if len(simple) < 2:
#             return None
#         source, target = _edge_title_to_source_target(title)
#         dot_edge = _find_dot_edge(self.dot_metadata, source, target, title)
#         if dot_edge:
#             return SvgEdge(title, simple, dot_edge.color or color, width, dot_edge.source, dot_edge.target, dot_edge.direction, dot_edge.label)
#         return SvgEdge(title, simple, color, width, source, target, "forward", "")


# class VsdxWriter:
#     def __init__(self, diagram: SvgDiagram, output_path: Path, options: VisioExportOptions):
#         self.diagram = diagram
#         self.output_path = Path(output_path)
#         self.options = options
#         self.shape_id = 100
#         self._warned_shape_limit = False
#         self.vb_x, self.vb_y, self.vb_w, self.vb_h = diagram.viewbox
#         self.vb_w, self.vb_h = max(1.0, self.vb_w), max(1.0, self.vb_h)
#         base_w = float(options.page_width_in or max(options.min_page_width_in, diagram.width_px / PT_PER_INCH))
#         base_h = float(options.page_height_in or max(options.min_page_height_in, diagram.height_px / PT_PER_INCH))
#         self.legend_items = _dedupe_legend_items(options.legend_items or []) if options.include_flow_legend else []
#         self.legend_space = self._legend_required_height() if self.legend_items else 0.0
#         self.page_w = base_w
#         self.page_h = base_h + self.legend_space
#         self._compute_scale()
#         self._media_rels: List[Tuple[str, Path, str]] = []
#         self._media_by_path: Dict[str, str] = {}
#         self._next_media_id = 1
#         self._next_rel_id = 1
#         if self.options.resolve_node_overlaps:
#             self._resolve_node_overlaps_in_svg_space()
#             self._expand_clusters_after_node_reflow()
#             self._fit_reflowed_diagram_to_page()

#     def _compute_scale(self) -> None:
#         available_h = max(1.0, self.page_h - self.legend_space - 0.35)
#         self.scale = min(self.page_w / self.vb_w, available_h / self.vb_h)
#         self.offset_x = (self.page_w - self.vb_w * self.scale) / 2.0
#         self.offset_y = self.legend_space + (available_h - self.vb_h * self.scale) / 2.0

#     def _legend_required_height(self) -> float:
#         return max(1.2, self.options.legend_row_height_in * (len(self.legend_items) + 1.8) + 0.35)

#     def _visual_node_size_svg(self, node: SvgNode) -> Tuple[float, float]:
#         x1, y1, x2, y2 = node.bbox
#         raw_w_svg = max(1.0, abs(x2 - x1))
#         raw_h_svg = max(1.0, abs(y2 - y1))
#         label = _wrap_label(node.label)
#         line_count = max(1, label.count("\n") + 1)
#         label_len = max([len(part) for part in label.split("\n") if part] or [1])
#         label_w_need_in = min(self.options.max_node_width_in, max(self.options.min_node_width_in, label_len * 0.075 + 0.55))
#         min_w_in = max(self.options.min_node_width_in, min(self.options.max_node_width_in, self.page_w * 0.11), label_w_need_in)
#         label_h_in = max(self.options.min_label_band_height_in, min(0.62, 0.23 * line_count + 0.12))
#         min_h_in = max(self.options.min_node_height_in, label_h_in + 0.86)
#         return max(raw_w_svg, min_w_in / max(self.scale, 1e-6)), max(raw_h_svg, min_h_in / max(self.scale, 1e-6))

#     def _resolve_node_overlaps_in_svg_space(self) -> None:
#         nodes = list(self.diagram.nodes or [])
#         if len(nodes) < 2:
#             return
#         margin_svg = self.options.node_collision_margin_in / max(self.scale, 1e-6)
#         layout: Dict[str, Dict[str, float]] = {}
#         for node in nodes:
#             x1, y1, x2, y2 = node.bbox
#             w, h = self._visual_node_size_svg(node)
#             layout[node.node_id] = {"cx": (x1 + x2) / 2.0, "cy": (y1 + y2) / 2.0, "w": w, "h": h}
#         if self.options.prefer_horizontal_reflow:
#             self._row_reflow_layout(nodes, layout, margin_svg)
#         for _ in range(self.options.node_collision_iterations):
#             moved = False
#             for i in range(len(nodes)):
#                 a = layout[nodes[i].node_id]
#                 for j in range(i + 1, len(nodes)):
#                     b = layout[nodes[j].node_id]
#                     dx, dy = b["cx"] - a["cx"], b["cy"] - a["cy"]
#                     overlap_x = (a["w"] + b["w"]) / 2.0 + margin_svg - abs(dx)
#                     overlap_y = (a["h"] + b["h"]) / 2.0 + margin_svg - abs(dy)
#                     if overlap_x <= 0 or overlap_y <= 0:
#                         continue
#                     moved = True
#                     same_row = abs(dy) < max(a["h"], b["h"]) * 0.70
#                     if same_row or overlap_x <= overlap_y:
#                         direction = 1.0 if dx >= 0 else -1.0
#                         shift = overlap_x / 2.0
#                         a["cx"] -= direction * shift
#                         b["cx"] += direction * shift
#                     else:
#                         direction = 1.0 if dy >= 0 else -1.0
#                         shift = overlap_y / 2.0
#                         a["cy"] -= direction * shift
#                         b["cy"] += direction * shift
#             if not moved:
#                 break
#         for node in nodes:
#             item = layout[node.node_id]
#             w, h = item["w"], item["h"]
#             node.bbox = (item["cx"] - w / 2.0, item["cy"] - h / 2.0, item["cx"] + w / 2.0, item["cy"] + h / 2.0)

#     def _row_reflow_layout(self, nodes: List[SvgNode], layout: Dict[str, Dict[str, float]], margin_svg: float) -> None:
#         tolerance_svg = self.options.row_group_tolerance_in / max(self.scale, 1e-6)
#         rows: List[List[SvgNode]] = []
#         for node in sorted(nodes, key=lambda n: layout[n.node_id]["cy"]):
#             cy = layout[node.node_id]["cy"]
#             placed = False
#             for row in rows:
#                 row_cy = sum(layout[n.node_id]["cy"] for n in row) / len(row)
#                 if abs(cy - row_cy) <= tolerance_svg:
#                     row.append(node)
#                     placed = True
#                     break
#             if not placed:
#                 rows.append([node])
#         for row in rows:
#             row.sort(key=lambda n: layout[n.node_id]["cx"])
#             if len(row) < 2:
#                 continue
#             row_cy = sum(layout[n.node_id]["cy"] for n in row) / len(row)
#             for node in row:
#                 layout[node.node_id]["cy"] = row_cy
#             for idx in range(1, len(row)):
#                 prev = layout[row[idx - 1].node_id]
#                 cur = layout[row[idx].node_id]
#                 min_cx = prev["cx"] + prev["w"] / 2.0 + cur["w"] / 2.0 + margin_svg
#                 if cur["cx"] < min_cx:
#                     cur["cx"] = min_cx
#             original_centre = sum(((n.bbox[0] + n.bbox[2]) / 2.0) for n in row) / len(row)
#             new_centre = sum(layout[n.node_id]["cx"] for n in row) / len(row)
#             for node in row:
#                 layout[node.node_id]["cx"] += original_centre - new_centre
#             for idx in range(1, len(row)):
#                 prev = layout[row[idx - 1].node_id]
#                 cur = layout[row[idx].node_id]
#                 min_cx = prev["cx"] + prev["w"] / 2.0 + cur["w"] / 2.0 + margin_svg
#                 if cur["cx"] < min_cx:
#                     cur["cx"] = min_cx

#     def _expand_clusters_after_node_reflow(self) -> None:
#         if not self.diagram.clusters or not self.diagram.nodes:
#             return
#         pad_svg = max(self.options.zone_padding_px, self.options.cluster_reflow_padding_in / max(self.scale, 1e-6))
#         header_svg = max(self.options.zone_header_px, pad_svg * 1.70)
#         updated: List[SvgCluster] = []
#         for cluster in self.diagram.clusters:
#             cx1, cy1, cx2, cy2 = cluster.bbox
#             contained = [n for n in self.diagram.nodes if cx1 <= (n.bbox[0] + n.bbox[2]) / 2 <= cx2 and cy1 <= (n.bbox[1] + n.bbox[3]) / 2 <= cy2]
#             if cluster.cluster_id.startswith("auto_zone_") and len(self.diagram.clusters) == 1:
#                 contained = list(self.diagram.nodes)
#             if not contained:
#                 updated.append(cluster)
#                 continue
#             min_x = min(n.bbox[0] for n in contained)
#             min_y = min(n.bbox[1] for n in contained)
#             max_x = max(n.bbox[2] for n in contained)
#             max_y = max(n.bbox[3] for n in contained)
#             updated.append(SvgCluster(cluster.cluster_id, cluster.label, (min(cx1, min_x - pad_svg), min(cy1, min_y - header_svg), max(cx2, max_x + pad_svg), max(cy2, max_y + pad_svg)), cluster.fill, cluster.stroke, cluster.font_color))
#         self.diagram.clusters = updated

#     def _fit_reflowed_diagram_to_page(self) -> None:
#         boxes = [n.bbox for n in self.diagram.nodes] + [c.bbox for c in self.diagram.clusters]
#         if not boxes:
#             return
#         min_x = min(b[0] for b in boxes)
#         min_y = min(b[1] for b in boxes)
#         max_x = max(b[2] for b in boxes)
#         max_y = max(b[3] for b in boxes)
#         pad_x = max(24.0, (max_x - min_x) * 0.035)
#         pad_y = max(24.0, (max_y - min_y) * 0.08)
#         self.vb_x = min_x - pad_x
#         self.vb_y = min_y - pad_y
#         self.vb_w = max(1.0, (max_x - min_x) + 2 * pad_x)
#         self.vb_h = max(1.0, (max_y - min_y) + 2 * pad_y)
#         self._compute_scale()

#     def write(self) -> Path:
#         self.output_path.parent.mkdir(parents=True, exist_ok=True)
#         tmp = self.output_path.with_suffix(".tmp.vsdx")
#         if tmp.exists():
#             tmp.unlink()
#         template = self._template_path()
#         if template:
#             shutil.copyfile(template, tmp)
#             self._rewrite_template(tmp)
#         else:
#             self._write_minimal(tmp)
#         tmp.replace(self.output_path)
#         self._validate_package(self.output_path)
#         return self.output_path

#     def _template_path(self) -> Optional[Path]:
#         try:
#             import vsdx  # type: ignore
#             path = Path(vsdx.__file__).parent / "media" / "media.vsdx"
#             return path if path.exists() else None
#         except Exception:
#             return None

#     def _rewrite_template(self, path: Path) -> None:
#         page_xml = self._page_xml().encode("utf-8")
#         replacements = {
#             "visio/pages/page1.xml": page_xml,
#             "visio/pages/pages.xml": self._pages_xml().encode("utf-8"),
#             "visio/windows.xml": self._windows_xml().encode("utf-8"),
#             "visio/pages/_rels/page1.xml.rels": self._page_rels_xml().encode("utf-8"),
#         }
#         original = path.with_suffix(".orig.vsdx")
#         path.replace(original)
#         try:
#             with zipfile.ZipFile(original, "r") as zin, zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
#                 seen = set()
#                 for item in zin.infolist():
#                     data = self._content_types_xml() if item.filename == "[Content_Types].xml" else replacements.get(item.filename, zin.read(item.filename))
#                     zout.writestr(item.filename, data)
#                     seen.add(item.filename)
#                 for name, data in replacements.items():
#                     if name not in seen:
#                         zout.writestr(name, data)
#                 self._write_media_parts(zout)
#         finally:
#             try:
#                 original.unlink()
#             except Exception:
#                 pass

#     def _write_minimal(self, path: Path) -> None:
#         page_xml = self._page_xml()
#         with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
#             z.writestr("[Content_Types].xml", self._content_types_xml())
#             z.writestr("_rels/.rels", self._root_rels_xml())
#             z.writestr("visio/document.xml", self._document_xml())
#             z.writestr("visio/_rels/document.xml.rels", self._document_rels_xml())
#             z.writestr("visio/masters/masters.xml", self._masters_xml())
#             z.writestr("visio/pages/pages.xml", self._pages_xml())
#             z.writestr("visio/pages/_rels/pages.xml.rels", self._pages_rels_xml())
#             z.writestr("visio/pages/page1.xml", page_xml)
#             z.writestr("visio/pages/_rels/page1.xml.rels", self._page_rels_xml())
#             z.writestr("visio/windows.xml", self._windows_xml())
#             z.writestr("docProps/app.xml", self._app_xml())
#             z.writestr("docProps/core.xml", self._core_xml())
#             self._write_media_parts(z)

#     def _write_media_parts(self, z: zipfile.ZipFile) -> None:
#         written = set()
#         for _rel_id, src, media_name in self._media_rels:
#             arcname = f"visio/media/{media_name}"
#             if arcname not in written and src.exists():
#                 z.write(src, arcname)
#                 written.add(arcname)

#     def _page_xml(self) -> str:
#         root = ET.Element(_v("PageContents"), {"xml:space": "preserve"})
#         shapes = ET.SubElement(root, _v("Shapes"))
#         for cluster in self.diagram.clusters:
#             self._append_cluster_shape(shapes, cluster)
#         for edge in self.diagram.edges:
#             self._append_edge_shape(shapes, edge)
#         for node in self.diagram.nodes:
#             self._append_card_shape(shapes, node)
#         if self.legend_items:
#             self._append_legend_items(shapes, self.legend_items)
#         page_sheet = ET.SubElement(root, _v("PageSheet"), {"LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._cell(page_sheet, "PageWidth", self.page_w)
#         self._cell(page_sheet, "PageHeight", self.page_h)
#         self._cell(page_sheet, "DrawingScale", 1)
#         self._cell(page_sheet, "PageScale", 1)
#         return _xml(root)

#     def _append_cluster_shape(self, parent: ET.Element, cluster: SvgCluster) -> None:
#         x1, y1, x2, y2 = cluster.bbox
#         w, h = self._size(x2 - x1, y2 - y1)
#         cx, cy = self._xy((x1 + x2) / 2, (y1 + y2) / 2)
#         body = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(cluster.cluster_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(body, cx, cy, w, h)
#         self._color_cell(body, "FillForegnd", cluster.fill)
#         self._color_cell(body, "FillBkgnd", cluster.fill)
#         self._cell(body, "FillPattern", 1)
#         self._cell(body, "FillForegndTrans", 15)
#         self._color_cell(body, "LineColor", cluster.stroke)
#         self._cell(body, "LineWeight", _pt(1.5))
#         self._cell(body, "Rounding", 0.12)
#         self._rectangle_geometry(body)
#         ET.SubElement(body, _v("Text"))

#         title = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(cluster.cluster_id + "_title"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         title_h = self.options.cluster_title_height_in
#         self._base_shape_cells(title, cx, cy + h / 2 - title_h / 2 - self.options.cluster_title_top_margin_in, max(0.6, w - 0.24), title_h)
#         self._cell(title, "LinePattern", 0)
#         self._cell(title, "FillPattern", 0)
#         self._character_section(title, 12.5, True, cluster.font_color)
#         self._paragraph_section(title, 1)
#         self._text_block(title, left_margin=0.02)
#         self._rectangle_geometry(title, no_line=True, no_fill=True)
#         ET.SubElement(title, _v("Text")).text = _cleanup_visible_text(cluster.label)

#     def _append_card_shape(self, parent: ET.Element, node: SvgNode) -> None:
#         x1, y1, x2, y2 = node.bbox
#         raw_w, raw_h = self._size(x2 - x1, y2 - y1)
#         cx, cy = self._xy((x1 + x2) / 2, (y1 + y2) / 2)
#         label = _wrap_label(node.label)
#         line_count = max(1, label.count("\n") + 1)
#         label_len = max([len(p) for p in label.split("\n") if p] or [1])
#         label_w_need = min(self.options.max_node_width_in, max(self.options.min_node_width_in, label_len * 0.075 + 0.55))
#         w = max(raw_w, self.options.min_node_width_in, label_w_need)
#         label_h = max(self.options.min_label_band_height_in, min(0.62, 0.23 * line_count + 0.12))
#         h = max(raw_h, self.options.min_node_height_in, label_h + 0.86)
#         icon_size = max(0.40, min(self.options.max_icon_size_in, h - label_h - 0.25, w * 0.32))
#         icon_cy = cy + h / 2 - max(0.08, h * 0.07) - icon_size / 2
#         band_cy = cy - h / 2 + label_h / 2 + 0.06

#         body = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(body, cx, cy, w, h)
#         self._color_cell(body, "FillForegnd", node.fill)
#         self._color_cell(body, "FillBkgnd", node.fill)
#         self._cell(body, "FillPattern", 1)
#         self._cell(body, "LinePattern", 1)
#         self._color_cell(body, "LineColor", node.stroke)
#         self._cell(body, "LineWeight", _pt(max(1.0, node.stroke_width)))
#         self._cell(body, "Rounding", 0.08)
#         self._rectangle_geometry(body)
#         ET.SubElement(body, _v("Text"))

#         band = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id + "_label_band"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(band, cx, band_cy, max(0.45, w - 0.18), label_h)
#         self._color_cell(band, "FillForegnd", "#FFFFFF")
#         self._color_cell(band, "FillBkgnd", "#FFFFFF")
#         self._cell(band, "FillPattern", 1)
#         self._cell(band, "LinePattern", 0)
#         self._cell(band, "Rounding", 0.05)
#         font_size = max(9.5, min(12.5, self.options.node_font_size_pt - max(0, line_count - 1) * 1.2))
#         self._character_section(band, font_size, True, node.font_color)
#         self._paragraph_section(band, 1)
#         self._text_block(band, left_margin=0.035)
#         self._rectangle_geometry(band, no_line=True)
#         ET.SubElement(band, _v("Text")).text = label

#         badge_size = icon_size * 1.08
#         badge = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id + "_icon_badge"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(badge, cx, icon_cy, badge_size, badge_size)
#         self._color_cell(badge, "FillForegnd", _lighten(node.stroke, 0.88))
#         self._color_cell(badge, "FillBkgnd", _lighten(node.stroke, 0.88))
#         self._cell(badge, "FillPattern", 1)
#         self._cell(badge, "LinePattern", 1)
#         self._color_cell(badge, "LineColor", node.stroke)
#         self._cell(badge, "LineWeight", _pt(0.75))
#         self._cell(badge, "Rounding", 0.04)
#         self._rectangle_geometry(badge)
#         icon_added = False
#         if self.options.include_icons and node.icon_path and self.options.compact_vector_icons:
#             icon_added = self._append_icon_compact_vector(parent, cx, icon_cy, icon_size * 0.86, node.icon_path, node.node_id)
#         if icon_added:
#             ET.SubElement(badge, _v("Text"))
#         else:
#             self._character_section(badge, 8.5, True, node.stroke)
#             self._paragraph_section(badge, 1)
#             self._text_block(badge, left_margin=0.01)
#             ET.SubElement(badge, _v("Text")).text = node.icon_text

#     def _append_icon_compact_vector(self, parent: ET.Element, cx: float, cy: float, size: float, icon_path: str, node_id: str) -> bool:
#         cells = _icon_compact_cells(icon_path, grid=self.options.compact_icon_grid, max_cells=self.options.max_icon_vector_cells)
#         if not cells:
#             return False
#         grid = max(1, max(max(x for x, _, _ in cells) + 1, max(y for _, y, _ in cells) + 1))
#         cell = size / grid
#         ox = cx - size / 2
#         oy = cy + size / 2
#         for ix, iy, color in cells:
#             px = ox + (ix + 0.5) * cell
#             py = oy - (iy + 0.5) * cell
#             shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(f"{node_id}_icon_cell"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#             self._base_shape_cells(shape, px, py, cell * 1.18, cell * 1.18)
#             self._color_cell(shape, "FillForegnd", color)
#             self._color_cell(shape, "FillBkgnd", color)
#             self._cell(shape, "FillPattern", 1)
#             self._cell(shape, "LinePattern", 0)
#             self._rectangle_geometry(shape, no_line=True)
#             if self.options.lock_icon_cells:
#                 self._protection_section(shape, lock_select=True)
#             ET.SubElement(shape, _v("Text"))
#         return True

#     def _node_by_id_or_label(self, value: str) -> Optional[SvgNode]:
#         key = _norm_identity(value)
#         if not key:
#             return None
#         for node in self.diagram.nodes:
#             if _norm_identity(node.node_id) == key or _norm_identity(node.label) == key:
#                 return node
#         return None

#     def _edge_points_for_current_layout(self, edge: SvgEdge) -> List[Tuple[float, float]]:
#         if not self.diagram.nodes:
#             return edge.points
#         source = self._node_by_id_or_label(edge.source) if edge.source else None
#         target = self._node_by_id_or_label(edge.target) if edge.target else None
#         if not source or not target:
#             if len(edge.points) < 2:
#                 return edge.points
#             source = self._nearest_node_to_point(edge.points[0])
#             target = self._nearest_node_to_point(edge.points[-1], exclude_id=source.node_id if source else None)
#         if not source or not target or source.node_id == target.node_id:
#             return edge.points
#         # Do not swap using x/y. Connector semantic direction is DOT source -> DOT target.
#         return [self._boundary_point_towards(source.bbox, target.bbox), self._boundary_point_towards(target.bbox, source.bbox)]

#     def _nearest_node_to_point(self, point: Tuple[float, float], exclude_id: Optional[str] = None) -> Optional[SvgNode]:
#         px, py = point
#         best = None
#         best_dist = float("inf")
#         for node in self.diagram.nodes:
#             if exclude_id and node.node_id == exclude_id:
#                 continue
#             x1, y1, x2, y2 = node.bbox
#             cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
#             dx = max(x1 - px, 0, px - x2)
#             dy = max(y1 - py, 0, py - y2)
#             dist = dx * dx + dy * dy + 0.0001 * ((cx - px) ** 2 + (cy - py) ** 2)
#             if dist < best_dist:
#                 best_dist = dist
#                 best = node
#         return best

#     def _boundary_point_towards(self, bbox: Tuple[float, float, float, float], other_bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
#         x1, y1, x2, y2 = bbox
#         ox1, oy1, ox2, oy2 = other_bbox
#         cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
#         ocx, ocy = (ox1 + ox2) / 2, (oy1 + oy2) / 2
#         dx, dy = ocx - cx, ocy - cy
#         return ((x2 if dx >= 0 else x1), cy) if abs(dx) >= abs(dy) else (cx, (y2 if dy >= 0 else y1))

#     def _append_edge_shape(self, parent: ET.Element, edge: SvgEdge) -> None:
#         points = [self._xy(x, y) for x, y in self._edge_points_for_current_layout(edge)]
#         if len(points) < 2:
#             return
#         min_x, min_y, max_x, max_y = _bbox(points)
#         w, h = max(0.01, max_x - min_x), max(0.01, max_y - min_y)
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(edge.edge_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, min_x + w / 2, min_y + h / 2, w, h)
#         self._color_cell(shape, "LineColor", edge.color)
#         self._cell(shape, "LineWeight", _pt(max(1.25, edge.width)))
#         self._cell(shape, "LinePattern", 1)
#         direction = _normalise_dot_direction(edge.direction, directed=True)
#         self._cell(shape, "BeginArrow", self.options.connector_arrow_type if direction in {"back", "both"} else 0)
#         self._cell(shape, "EndArrow", self.options.connector_arrow_type if direction in {"forward", "both"} else 0)
#         self._cell(shape, "BeginArrowSize", self.options.connector_arrow_size)
#         self._cell(shape, "EndArrowSize", self.options.connector_arrow_size)
#         self._line_geometry(shape, points, min_x, min_y, w, h)
#         ET.SubElement(shape, _v("Text"))

#     def _append_legend_items(self, parent: ET.Element, items: List[Tuple[str, str]]) -> None:
#         items = _dedupe_legend_items(items)
#         x = 0.65
#         y = 0.35 + self.options.legend_row_height_in * len(items)
#         self._append_free_text(parent, "Flow Legend", x, y + 0.38, self.options.legend_title_font_size_pt, True)
#         for idx, (color, label) in enumerate(items):
#             row_y = y - self.options.legend_row_height_in * idx
#             self._append_page_line(parent, x, row_y, x + self.options.legend_arrow_length_in, row_y, color)
#             self._append_free_text(parent, label, x + self.options.legend_arrow_length_in + 0.25, row_y, self.options.legend_font_size_pt, False)

#     def _append_free_text(self, parent: ET.Element, text: str, x: float, y: float, font_pt: float, bold: bool) -> None:
#         text = _cleanup_visible_text(text)
#         w, h = max(1.0, min(13.0, len(text) * font_pt / 72.0 * 0.55)), 0.28
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(text[:40] or "Text"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, x + w / 2, y, w, h)
#         self._cell(shape, "LinePattern", 0)
#         self._cell(shape, "FillPattern", 0)
#         self._character_section(shape, font_pt, bold, "#000000")
#         self._paragraph_section(shape, 0)
#         self._rectangle_geometry(shape, no_line=True, no_fill=True)
#         ET.SubElement(shape, _v("Text")).text = text

#     def _append_page_line(self, parent: ET.Element, x1: float, y1: float, x2: float, y2: float, color: str) -> None:
#         min_x, min_y, max_x, max_y = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
#         w, h = max(0.01, max_x - min_x), max(0.01, max_y - min_y)
#         shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": "Legend_Line", "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._base_shape_cells(shape, min_x + w / 2, min_y + h / 2, w, h)
#         self._color_cell(shape, "LineColor", color)
#         self._cell(shape, "LineWeight", _pt(1.80))
#         self._cell(shape, "BeginArrow", 0)
#         self._cell(shape, "EndArrow", 4)
#         self._line_geometry(shape, [(x1, y1), (x2, y2)], min_x, min_y, w, h)
#         ET.SubElement(shape, _v("Text"))

#     def _base_shape_cells(self, shape: ET.Element, cx: float, cy: float, w: float, h: float) -> None:
#         self._cell(shape, "PinX", cx)
#         self._cell(shape, "PinY", cy)
#         self._cell(shape, "Width", w)
#         self._cell(shape, "Height", h)
#         self._cell(shape, "LocPinX", w / 2, "Width*0.5")
#         self._cell(shape, "LocPinY", h / 2, "Height*0.5")
#         self._cell(shape, "Angle", 0)
#         self._cell(shape, "FlipX", 0)
#         self._cell(shape, "FlipY", 0)
#         self._cell(shape, "ResizeMode", 0)

#     def _character_section(self, shape: ET.Element, font_pt: float, bold: bool, color: str) -> None:
#         section = ET.SubElement(shape, _v("Section"), {"N": "Character"})
#         row = ET.SubElement(section, _v("Row"), {"IX": "0"})
#         self._cell(row, "Size", _pt(font_pt))
#         self._cell(row, "Style", 17 if bold else 0)
#         self._color_cell(row, "Color", color)

#     def _paragraph_section(self, shape: ET.Element, align: int) -> None:
#         section = ET.SubElement(shape, _v("Section"), {"N": "Paragraph"})
#         row = ET.SubElement(section, _v("Row"), {"IX": "0"})
#         self._cell(row, "HorzAlign", align)

#     def _text_block(self, shape: ET.Element, left_margin: float = 0.06) -> None:
#         block = ET.SubElement(shape, _v("TextBlock"))
#         self._cell(block, "VerticalAlign", 1)
#         self._cell(block, "LeftMargin", left_margin)
#         self._cell(block, "RightMargin", 0.06)
#         self._cell(block, "TopMargin", 0.03)
#         self._cell(block, "BottomMargin", 0.03)

#     def _rectangle_geometry(self, shape: ET.Element, *, no_line: bool = False, no_fill: bool = False) -> None:
#         geom = ET.SubElement(shape, _v("Section"), {"N": "Geometry", "IX": "0"})
#         self._cell(geom, "NoFill", 1 if no_fill else 0)
#         self._cell(geom, "NoLine", 1 if no_line else 0)
#         for row_type, ix, x, y in [("RelMoveTo", 1, 0, 0), ("RelLineTo", 2, 1, 0), ("RelLineTo", 3, 1, 1), ("RelLineTo", 4, 0, 1), ("RelLineTo", 5, 0, 0)]:
#             row = ET.SubElement(geom, _v("Row"), {"T": row_type, "IX": str(ix)})
#             self._cell(row, "X", x)
#             self._cell(row, "Y", y)

#     def _line_geometry(self, shape: ET.Element, points: List[Tuple[float, float]], min_x: float, min_y: float, w: float, h: float) -> None:
#         geom = ET.SubElement(shape, _v("Section"), {"N": "Geometry", "IX": "0"})
#         self._cell(geom, "NoFill", 1)
#         self._cell(geom, "NoLine", 0)
#         for ix, (x, y) in enumerate(points, start=1):
#             row = ET.SubElement(geom, _v("Row"), {"T": "RelMoveTo" if ix == 1 else "RelLineTo", "IX": str(ix)})
#             self._cell(row, "X", 0 if w <= 0 else (x - min_x) / w)
#             self._cell(row, "Y", 0 if h <= 0 else (y - min_y) / h)

#     def _protection_section(self, shape: ET.Element, *, lock_select: bool = False) -> None:
#         section = ET.SubElement(shape, _v("Section"), {"N": "Protection"})
#         row = ET.SubElement(section, _v("Row"), {"IX": "0"})
#         self._cell(row, "LockSelect", 1 if lock_select else 0)

#     def _pages_xml(self) -> str:
#         root = ET.Element(_v("Pages"), {"xml:space": "preserve"})
#         page = ET.SubElement(root, _v("Page"), {"ID": "0", "NameU": self.options.page_name or "Diagram", "Name": self.options.page_name or "Diagram", "ViewScale": "1", "ViewCenterX": str(self.page_w / 2), "ViewCenterY": str(self.page_h / 2)})
#         sheet = ET.SubElement(page, _v("PageSheet"), {"LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
#         self._cell(sheet, "PageWidth", self.page_w)
#         self._cell(sheet, "PageHeight", self.page_h)
#         ET.SubElement(page, _v("Rel"), {_r("id"): "rId1"})
#         return _xml(root)

#     def _windows_xml(self) -> str:
#         root = ET.Element(_v("Windows"), {"xml:space": "preserve"})
#         win = ET.SubElement(root, _v("Window"), {"ID": "0", "WindowType": "Drawing", "ContainerType": "Page", "Container": "0"})
#         self._cell(win, "ViewScale", 1)
#         self._cell(win, "ViewCenterX", self.page_w / 2)
#         self._cell(win, "ViewCenterY", self.page_h / 2)
#         return _xml(root)

#     def _content_types_xml(self) -> str:
#         root = ET.Element("Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"})
#         for ext, ctype in {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml", "png": "image/png", "jpeg": "image/jpeg", "jpg": "image/jpeg"}.items():
#             ET.SubElement(root, "Default", {"Extension": ext, "ContentType": ctype})
#         for part, ctype in {
#             "/visio/document.xml": "application/vnd.ms-visio.drawing.main+xml",
#             "/visio/pages/pages.xml": "application/vnd.ms-visio.pages+xml",
#             "/visio/pages/page1.xml": "application/vnd.ms-visio.page+xml",
#             "/visio/windows.xml": "application/vnd.ms-visio.windows+xml",
#             "/visio/masters/masters.xml": "application/vnd.ms-visio.masters+xml",
#             "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
#             "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
#         }.items():
#             ET.SubElement(root, "Override", {"PartName": part, "ContentType": ctype})
#         return _xml_plain(root)

#     def _root_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/document", "Target": "visio/document.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId2", "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "Target": "docProps/core.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId3", "Type": f"{R_NS}/extended-properties", "Target": "docProps/app.xml"})
#         return _xml_plain(root)

#     def _document_xml(self) -> str:
#         return _xml(ET.Element(_v("VisioDocument"), {"xml:space": "preserve"}))

#     def _document_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/masters", "Target": "masters/masters.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId2", "Type": f"{VISIO_REL_NS}/pages", "Target": "pages/pages.xml"})
#         ET.SubElement(root, "Relationship", {"Id": "rId3", "Type": f"{VISIO_REL_NS}/windows", "Target": "windows.xml"})
#         return _xml_plain(root)

#     def _pages_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/page", "Target": "page1.xml"})
#         return _xml_plain(root)

#     def _page_rels_xml(self) -> str:
#         root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
#         for rel_id, _src, media_name in self._media_rels:
#             ET.SubElement(root, "Relationship", {"Id": rel_id, "Type": f"{R_NS}/image", "Target": f"../media/{media_name}"})
#         return _xml_plain(root)

#     def _masters_xml(self) -> str:
#         return _xml(ET.Element(_v("Masters"), {"xml:space": "preserve"}))

#     def _app_xml(self) -> str:
#         root = ET.Element("Properties", {"xmlns": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"})
#         ET.SubElement(root, "Application").text = "Microsoft Visio"
#         return _xml_plain(root)

#     def _core_xml(self) -> str:
#         root = ET.Element("cp:coreProperties", {"xmlns:cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties", "xmlns:dc": "http://purl.org/dc/elements/1.1/"})
#         ET.SubElement(root, "dc:title").text = self.options.page_name or "Diagram"
#         return _xml_plain(root)

#     def _xy(self, x: float, y: float) -> Tuple[float, float]:
#         return self.offset_x + (x - self.vb_x) * self.scale, self.offset_y + (self.vb_h - (y - self.vb_y)) * self.scale

#     def _size(self, width: float, height: float) -> Tuple[float, float]:
#         return max(0.02, abs(width) * self.scale), max(0.02, abs(height) * self.scale)

#     def _next_id(self) -> int:
#         self.shape_id += 1
#         if self.shape_id - 100 > self.options.shape_warning_limit and not self._warned_shape_limit:
#             self._warned_shape_limit = True
#             logger.warning("VSDX shape count exceeded warning limit")
#         return self.shape_id

#     def _cell(self, parent: ET.Element, name: str, value: Any, formula: Optional[str] = None) -> None:
#         attrs = {"N": name, "V": str(value)}
#         if formula:
#             attrs["F"] = formula
#         ET.SubElement(parent, _v("Cell"), attrs)

#     def _color_cell(self, parent: ET.Element, name: str, color: str) -> None:
#         r, g, b = _rgb(color)
#         ET.SubElement(parent, _v("Cell"), {"N": name, "V": _colour(color, "#000000"), "F": f"RGB({r},{g},{b})"})

#     def _validate_package(self, path: Path) -> None:
#         required = {"[Content_Types].xml", "_rels/.rels", "visio/document.xml", "visio/pages/pages.xml", "visio/pages/page1.xml", "visio/pages/_rels/pages.xml.rels", "visio/pages/_rels/page1.xml.rels", "visio/windows.xml"}
#         with zipfile.ZipFile(path, "r") as z:
#             missing = sorted(required - set(z.namelist()))
#             if missing:
#                 raise RuntimeError(f"Generated VSDX package is missing required parts: {missing}")


# def _parse_dot_metadata(dot_path: Path) -> DotMetadata:
#     labels: Dict[str, str] = {}
#     attrs_by_node: Dict[str, Dict[str, str]] = {}
#     edges: List[DotEdge] = []
#     if not dot_path.exists():
#         return DotMetadata(labels, attrs_by_node, [], [])
#     text = dot_path.read_text(encoding="utf-8", errors="replace")
#     statements = _split_dot_statements(text)
#     for statement in statements:
#         stripped = statement.strip().rstrip(";")
#         if not stripped or "->" in stripped or "--" in stripped or "[" not in stripped or "]" not in stripped:
#             continue
#         if stripped.lower().startswith(("digraph", "graph", "subgraph", "node ", "edge ")):
#             continue
#         prefix, raw_attrs, _ = _split_dot_attr_statement(stripped)
#         node_id = _clean_dot_id(prefix)
#         if not node_id:
#             continue
#         attrs = _parse_dot_attrs(raw_attrs)
#         attrs_by_node[node_id] = attrs
#         labels[node_id] = _clean_dot_label(attrs.get("label") or attrs.get("xlabel") or attrs.get("tooltip") or node_id) or node_id
#     for statement in statements:
#         stripped = statement.strip().rstrip(";")
#         if not stripped or ("->" not in stripped and "--" not in stripped):
#             continue
#         endpoints = _extract_edge_endpoints(stripped)
#         if len(endpoints) < 2:
#             continue
#         raw_attrs = _split_dot_attr_statement(stripped)[1] if "[" in stripped and "]" in stripped else ""
#         attrs = _parse_dot_attrs(raw_attrs)
#         color = _colour(attrs.get("color"), "#666666")
#         label = _clean_dot_label(attrs.get("label") or attrs.get("xlabel") or "") or _make_edge_fallback_label(endpoints[0], endpoints[-1], labels)
#         direction = _normalise_dot_direction(attrs.get("dir"), directed="->" in stripped)
#         edges.append(DotEdge(endpoints[0], endpoints[-1], color, label, direction))
#     return DotMetadata(labels, attrs_by_node, _dedupe_legend_items([(e.color, e.label) for e in edges if e.label]), edges)


# def _normalise_dot_direction(value: Any, directed: bool = True) -> str:
#     raw = str(value or "").strip().lower()
#     if raw in {"forward", "back", "both", "none"}:
#         return raw
#     return "forward" if directed else "none"


# def _norm_identity(value: Any) -> str:
#     return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


# def _edge_title_to_source_target(title: str) -> Tuple[str, str]:
#     text = _cleanup_visible_text(title or "")
#     parts = [_clean_dot_id(p) for p in re.split(r"\s*->\s*|\s*--\s*", text) if _clean_dot_id(p)]
#     return (parts[0], parts[-1]) if len(parts) >= 2 else ("", "")


# def _find_dot_edge(metadata: DotMetadata, source: str, target: str, title: str = "") -> Optional[DotEdge]:
#     s_key = _norm_identity(source)
#     t_key = _norm_identity(target)
#     if s_key and t_key:
#         for edge in metadata.edges:
#             if _norm_identity(edge.source) == s_key and _norm_identity(edge.target) == t_key:
#                 return edge
#         # SVG title/path can occasionally be reversed; still return the DOT semantic edge.
#         for edge in metadata.edges:
#             if _norm_identity(edge.source) == t_key and _norm_identity(edge.target) == s_key:
#                 return edge
#     title_key = _norm_identity(title)
#     for edge in metadata.edges:
#         if _norm_identity(f"{edge.source}->{edge.target}") in title_key or _norm_identity(f"{edge.source}--{edge.target}") in title_key:
#             return edge
#     return None


# def _fallback_nodes_from_dot_metadata(metadata: DotMetadata) -> List[SvgNode]:
#     nodes: List[SvgNode] = []
#     node_ids = list(metadata.labels.keys())
#     if not node_ids:
#         for edge in metadata.edges:
#             if edge.source not in node_ids:
#                 node_ids.append(edge.source)
#             if edge.target not in node_ids:
#                 node_ids.append(edge.target)
#     x = 80.0
#     y = 130.0
#     gap = 190.0
#     for idx, node_id in enumerate(node_ids):
#         label = metadata.labels.get(node_id, node_id)
#         attrs = metadata.attrs.get(node_id, {})
#         style = _node_visual_style(label, node_id, attrs)
#         cx = x + idx * gap
#         bbox = (cx - 62.0, y - 42.0, cx + 62.0, y + 42.0)
#         icon_path = _resolve_icon_path(label)
#         nodes.append(SvgNode(node_id, label, bbox, style["fill"], style["border"], 1.0, "", icon_path, _icon_abbrev(label), style.get("font", "#000000"), attrs))
#     return nodes


# def _fallback_edges_from_dot_metadata(metadata: DotMetadata, nodes: List[SvgNode]) -> List[SvgEdge]:
#     by_id = {_norm_identity(n.node_id): n for n in nodes}
#     by_label = {_norm_identity(n.label): n for n in nodes}
#     edges: List[SvgEdge] = []
#     for edge in metadata.edges:
#         source = by_id.get(_norm_identity(edge.source)) or by_label.get(_norm_identity(edge.source))
#         target = by_id.get(_norm_identity(edge.target)) or by_label.get(_norm_identity(edge.target))
#         if not source or not target:
#             continue
#         sx = (source.bbox[0] + source.bbox[2]) / 2.0
#         sy = (source.bbox[1] + source.bbox[3]) / 2.0
#         tx = (target.bbox[0] + target.bbox[2]) / 2.0
#         ty = (target.bbox[1] + target.bbox[3]) / 2.0
#         edges.append(SvgEdge(f"{edge.source}->{edge.target}", [(sx, sy), (tx, ty)], edge.color, 1.25, edge.source, edge.target, edge.direction, edge.label))
#     return edges


# def _merge_svg_routes_with_dot_edges(metadata: DotMetadata, nodes: List[SvgNode], svg_edges: List[SvgEdge]) -> List[SvgEdge]:
#     if not metadata.edges:
#         return svg_edges
#     fallback = _fallback_edges_from_dot_metadata(metadata, nodes)
#     if not svg_edges:
#         return fallback
#     merged: List[SvgEdge] = []
#     used_svg: set[int] = set()
#     for dot_edge in metadata.edges:
#         chosen: Optional[SvgEdge] = None
#         for idx, svg_edge in enumerate(svg_edges):
#             if idx in used_svg:
#                 continue
#             candidate = _find_dot_edge(metadata, svg_edge.source, svg_edge.target, svg_edge.edge_id)
#             if candidate and _norm_identity(candidate.source) == _norm_identity(dot_edge.source) and _norm_identity(candidate.target) == _norm_identity(dot_edge.target):
#                 chosen = svg_edge
#                 used_svg.add(idx)
#                 break
#         if chosen:
#             merged.append(SvgEdge(chosen.edge_id, chosen.points, dot_edge.color or chosen.color, chosen.width, dot_edge.source, dot_edge.target, dot_edge.direction, dot_edge.label))
#         else:
#             for fb in fallback:
#                 if _norm_identity(fb.source) == _norm_identity(dot_edge.source) and _norm_identity(fb.target) == _norm_identity(dot_edge.target):
#                     merged.append(fb)
#                     break
#     return merged or fallback or svg_edges


# def _filter_clusters(clusters: List[SvgCluster], nodes: List[SvgNode], opts: Optional[VisioExportOptions] = None) -> List[SvgCluster]:
#     if not clusters or not nodes:
#         return []
#     opts = opts or VisioExportOptions()
#     result = []
#     seen = set()
#     for c in sorted(clusters, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]), reverse=True):
#         x1, y1, x2, y2 = c.bbox
#         contained = [n for n in nodes if x1 <= (n.bbox[0] + n.bbox[2]) / 2 <= x2 and y1 <= (n.bbox[1] + n.bbox[3]) / 2 <= y2]
#         if not contained:
#             continue
#         min_x = min(n.bbox[0] for n in contained)
#         min_y = min(n.bbox[1] for n in contained)
#         max_x = max(n.bbox[2] for n in contained)
#         max_y = max(n.bbox[3] for n in contained)
#         required_top = max(float(opts.zone_header_px), float(opts.zone_padding_px) * 1.70)
#         if min_y - y1 < required_top:
#             y1 = min_y - required_top
#         x1 = min(x1, min_x - opts.zone_padding_px)
#         x2 = max(x2, max_x + opts.zone_padding_px)
#         y2 = max(y2, max_y + opts.zone_padding_px)
#         key = (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), c.label.lower())
#         if key not in seen:
#             seen.add(key)
#             result.append(SvgCluster(c.cluster_id, c.label, (x1, y1, x2, y2), c.fill, c.stroke, c.font_color))
#     return result


# def _auto_zones(nodes: List[SvgNode], opts: VisioExportOptions) -> List[SvgCluster]:
#     if not nodes:
#         return []
#     groups = _group_nodes_by_zone_metadata(nodes, opts)
#     if groups:
#         return _zones_from_grouped_nodes(groups, opts)
#     return [_zone_from_nodes("auto_zone_1", opts.default_auto_zone_label, nodes, opts.cluster_fill, opts.cluster_stroke, opts.cluster_text, opts)]


# def _group_nodes_by_zone_metadata(nodes: List[SvgNode], opts: VisioExportOptions) -> List[Tuple[str, List[SvgNode]]]:
#     grouped: Dict[str, List[SvgNode]] = {}
#     order: List[str] = []
#     for node in nodes:
#         attrs = node.attrs or {}
#         zone = ""
#         for name in opts.zone_attribute_names:
#             if attrs.get(name):
#                 zone = _cleanup_visible_text(attrs[name])
#                 break
#         if zone:
#             key = zone.lower()
#             grouped.setdefault(key, [])
#             if key not in order:
#                 order.append(key)
#             grouped[key].append(node)
#     if not grouped:
#         return []
#     return [(k, grouped[k]) for k in order if grouped[k]]


# def _zones_from_grouped_nodes(groups: List[Tuple[str, List[SvgNode]]], opts: VisioExportOptions) -> List[SvgCluster]:
#     labels = list(opts.auto_zone_labels or [])
#     zones = []
#     for idx, (key, nodes) in enumerate(groups[: opts.max_auto_zones]):
#         label = labels[idx] if idx < len(labels) and labels[idx] else _humanize_zone_label(key, idx + 1)
#         zones.append(_zone_from_nodes(f"auto_zone_{idx + 1}", label, nodes, _zone_fill(idx), opts.cluster_stroke, opts.cluster_text, opts))
#     return zones


# def _zone_from_nodes(cluster_id: str, label: str, nodes: List[SvgNode], fill: str, stroke: str, text: str, opts: VisioExportOptions) -> SvgCluster:
#     pad = float(opts.zone_padding_px)
#     header = max(float(opts.zone_header_px), pad * 1.70)
#     return SvgCluster(cluster_id, label, (min(n.bbox[0] for n in nodes) - pad, min(n.bbox[1] for n in nodes) - header, max(n.bbox[2] for n in nodes) + pad, max(n.bbox[3] for n in nodes) + pad), fill, stroke, text)


# def _humanize_zone_label(value: str, index: int) -> str:
#     text = _cleanup_visible_text(value).replace("_", " ").replace("-", " ").strip()
#     return f"Zone {index}" if not text or re.fullmatch(r"zone\s*\d+", text, flags=re.I) else re.sub(r"\s+", " ", text).title()


# def _zone_fill(index: int) -> str:
#     return ["#EFF6FF", "#EEF6FF", "#F8FBFF", "#F6FAF3", "#FFF8E8", "#F8F1FF"][index % 6]


# def _split_dot_statements(text: str) -> List[str]:
#     statements = []
#     current = []
#     in_quote = False
#     in_html = False
#     bracket_depth = 0
#     escape = False
#     for char in text:
#         current.append(char)
#         if escape:
#             escape = False
#             continue
#         if char == "\\":
#             escape = True
#             continue
#         if char == '"' and not in_html:
#             in_quote = not in_quote
#             continue
#         if char == "<" and not in_quote:
#             in_html = True
#         elif char == ">" and in_html and not in_quote:
#             in_html = False
#         elif char == "[" and not in_quote and not in_html:
#             bracket_depth += 1
#         elif char == "]" and not in_quote and not in_html:
#             bracket_depth = max(0, bracket_depth - 1)
#         elif char == ";" and not in_quote and not in_html and bracket_depth == 0:
#             st = "".join(current).strip()
#             current = []
#             if st:
#                 statements.append(st)
#     tail = "".join(current).strip()
#     if tail:
#         statements.append(tail)
#     return statements


# def _split_dot_attr_statement(statement: str) -> Tuple[str, str, str]:
#     start = statement.find("[")
#     end = statement.rfind("]")
#     return (statement, "", "") if start < 0 or end < start else (statement[:start].strip(), statement[start + 1 : end].strip(), statement[end + 1 :].strip())


# def _parse_dot_attrs(raw: str) -> Dict[str, str]:
#     attrs: Dict[str, str] = {}
#     pattern = re.compile(r'([A-Za-z_][A-Za-z0-9_:-]*)\s*=\s*("(?:\\.|[^"])*"|<.*?>|[^,\]]+)', flags=re.S)
#     for key, value in pattern.findall(raw or ""):
#         attrs[key.strip().lower()] = _clean_dot_label(value)
#     return attrs


# def _extract_edge_endpoints(statement: str) -> List[str]:
#     no_attrs = re.sub(r"\[.*?\]", "", statement, flags=re.S).strip().rstrip(";")
#     return [_clean_dot_id(part) for part in re.split(r"->|--", no_attrs) if _clean_dot_id(part)]


# def _clean_dot_id(value: str) -> str:
#     return _cleanup_visible_text(str(value or "").strip().rstrip(";").strip().strip('"').strip("'"))


# def _clean_dot_label(value: str) -> str:
#     return _cleanup_visible_text(str(value or "").strip().strip('"').strip("'"))


# def _cleanup_visible_text(value: str) -> str:
#     text = html.unescape(str(value or ""))
#     text = text.replace("\\n", " ").replace("\\l", " ").replace("\\r", " ")
#     text = re.sub(r"\\+", " ", text)
#     text = re.sub(r"<\s*br\s*/?\s*>", " ", text, flags=re.I)
#     text = re.sub(r"</?\s*b\s*>", "", text, flags=re.I)
#     text = re.sub(r"<[^>]+>", "", text)
#     text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
#     return re.sub(r"\s+", " ", text).strip()


# def _make_edge_fallback_label(source: str, target: str, labels: Dict[str, str]) -> str:
#     src = labels.get(source, source).strip()
#     dst = labels.get(target, target).strip()
#     return f"{src} to {dst}" if src and dst else ""


# def _extract_icon_from_candidates(candidates: List[str], base_dir: Path, label: str) -> str:
#     return _resolve_first_raster(candidates, base_dir)


# def _resolve_first_raster(candidates: List[str], base_dir: Path) -> str:
#     for candidate in candidates:
#         path = _resolve_raster_path(candidate, base_dir)
#         if path:
#             return str(path)
#     return ""


# def _resolve_raster_path(href: Any, base_dir: Path) -> Optional[Path]:
#     if not href:
#         return None
#     raw = str(href).strip().strip('"').strip("'")
#     if raw.startswith("data:image/") or raw.startswith(("http://", "https://")):
#         return None
#     path = Path(unquote(raw))
#     roots = [path] if path.is_absolute() else [base_dir / path, Path.cwd() / path, PROJECT_ROOT / path]
#     for candidate in roots:
#         try:
#             candidate = candidate.resolve()
#         except Exception:
#             pass
#         if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}:
#             return candidate
#     return None


# def _icon_compact_cells(path: str, grid: int = 12, max_cells: int = 44) -> List[Tuple[int, int, str]]:
#     resolved = _resolve_raster_path(path, Path.cwd())
#     if Image is None or not resolved:
#         return []
#     try:
#         with Image.open(resolved).convert("RGBA") as img:  # type: ignore[union-attr]
#             grid = max(8, min(16, int(grid or 12)))
#             max_cells = max(12, min(60, int(max_cells or 44)))
#             if ImageEnhance is not None:
#                 img = ImageEnhance.Color(img).enhance(2.2)
#                 img = ImageEnhance.Contrast(img).enhance(2.0)
#                 img = ImageEnhance.Brightness(img).enhance(0.82)
#             bbox = img.getbbox()
#             if bbox:
#                 img = img.crop(bbox)
#             img.thumbnail((grid, grid), Image.LANCZOS)
#             canvas = Image.new("RGBA", (grid, grid), (255, 255, 255, 0))
#             canvas.paste(img, ((grid - img.width) // 2, (grid - img.height) // 2), img)
#             pix = canvas.load()
#             candidates = []
#             for y in range(grid):
#                 for x in range(grid):
#                     r, g, b, a = pix[x, y]
#                     if a < 45 or (r > 248 and g > 248 and b > 248):
#                         continue
#                     alpha = a / 255.0
#                     r = int(r * alpha + 255 * (1 - alpha))
#                     g = int(g * alpha + 255 * (1 - alpha))
#                     b = int(b * alpha + 255 * (1 - alpha))
#                     lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
#                     if lum > 190:
#                         factor = 190.0 / max(lum, 1.0)
#                         r, g, b = int(r * factor), int(g * factor), int(b * factor)
#                         lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
#                     score = (255 - lum) + (max(r, g, b) - min(r, g, b)) + a * 0.35
#                     r = max(0, min(255, int(round(r / 12.0) * 12)))
#                     g = max(0, min(255, int(round(g / 12.0) * 12)))
#                     b = max(0, min(255, int(round(b / 12.0) * 12)))
#                     candidates.append((score, x, y, f"#{r:02X}{g:02X}{b:02X}"))
#             if len(candidates) > max_cells:
#                 candidates = sorted(candidates, key=lambda i: i[0], reverse=True)[:max_cells]
#             return [(x, y, color) for _score, x, y, color in sorted(candidates, key=lambda i: (i[2], i[1]))]
#     except Exception:
#         logger.exception("Failed to create compact icon cells: %s", path)
#         return []


# def _node_visual_style(label: str, seed: str, attrs: Dict[str, str]) -> Dict[str, str]:
#     if get_style_for_label is not None:
#         try:
#             style = get_style_for_label(_normalise_label_for_lookup(label or seed))  # type: ignore[misc]
#             fill = _colour(attrs.get("fillcolor") or style.get("fill"), _pastel_color(seed))
#             border = _colour(attrs.get("color") or style.get("border"), _darker_border(fill))
#             font = _colour(style.get("font"), "#000000")
#             return {"fill": fill, "border": border, "font": font}
#         except Exception:
#             pass
#     fill = _colour(attrs.get("fillcolor"), _pastel_color(seed))
#     border = _colour(attrs.get("color"), _darker_border(fill))
#     return {"fill": fill, "border": border, "font": "#000000"}


# def _resolve_icon_path(label: str) -> str:
#     if resolve_icon_from_node_label is None:
#         return ""
#     raw = _cleanup_visible_text(label)
#     values = [raw, _normalise_label_for_lookup(raw), raw.replace("_", " "), raw.replace("_", "")]
#     if clean_label is not None:
#         try:
#             cleaned = clean_label(raw)  # type: ignore[misc]
#             values.extend([cleaned, _normalise_label_for_lookup(cleaned)])
#         except Exception:
#             pass
#     seen = set()
#     for candidate in values:
#         candidate = str(candidate or "").strip()
#         if not candidate or candidate.lower() in seen:
#             continue
#         seen.add(candidate.lower())
#         try:
#             icon = resolve_icon_from_node_label(candidate, PROJECT_ROOT)  # type: ignore[misc]
#             if icon and normalize_icon_for_graphviz is not None:
#                 try:
#                     icon = normalize_icon_for_graphviz(str(icon))  # type: ignore[misc]
#                 except Exception:
#                     pass
#             resolved = _resolve_raster_path(str(icon), Path.cwd()) if icon else None
#             if resolved:
#                 return str(resolved)
#         except Exception:
#             logger.exception("Icon resolution failed for %r", candidate)
#     return ""


# def _normalise_label_for_lookup(label: str) -> str:
#     text = _cleanup_visible_text(label).replace("_", " ").replace("-", " ")
#     text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
#     return re.sub(r"\s+", " ", text).strip()


# def _icon_abbrev(label: str) -> str:
#     words = [w for w in re.split(r"\s+", _normalise_label_for_lookup(label)) if w]
#     return "•" if not words else (words[0][:2].upper() if len(words) == 1 else "".join(w[0] for w in words[:2]).upper())


# def _wrap_label(label: str) -> str:
#     try:
#         text = clean_label(label) if clean_label is not None else _cleanup_visible_text(label).replace("_", " ")  # type: ignore[misc]
#     except Exception:
#         text = _cleanup_visible_text(label).replace("_", " ")
#     words = text.split()
#     if len(words) <= 2:
#         return text
#     mid = (len(words) + 1) // 2 if len(words) <= 4 else max(2, len(words) // 2)
#     return " ".join(words[:mid]) + "\n" + " ".join(words[mid:])


# def _run_graphviz(dot: Path, out: Path, fmt: str, engine: str) -> None:
#     result = subprocess.run([engine, f"-T{fmt}", str(dot), "-o", str(out)], capture_output=True, text=True, check=False)
#     if result.returncode != 0:
#         raise RuntimeError(f"Graphviz failed for {fmt}:\n{result.stderr or result.stdout}")


# def _iter_svg(root: ET.Element) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
#     def walk(elem: ET.Element, parent_matrix: Matrix, parent_classes: List[str]) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
#         matrix = _matmul(parent_matrix, _transform(elem.get("transform")))
#         classes = _class_tokens(elem.get("class"))
#         yield elem, matrix, parent_classes
#         for child in list(elem):
#             yield from walk(child, matrix, parent_classes + classes)

#     yield from walk(root, IDENTITY, [])


# def _class_tokens(value: Optional[str]) -> List[str]:
#     return [t.strip().lower() for t in re.split(r"\s+", value or "") if t.strip()]


# def _transform(raw: Optional[str]) -> Matrix:
#     if not raw:
#         return IDENTITY
#     matrix = IDENTITY
#     for name, args in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", raw):
#         nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", args)]
#         local = IDENTITY
#         if name == "matrix" and len(nums) >= 6:
#             local = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
#         elif name == "translate":
#             local = (1, 0, 0, 1, nums[0] if nums else 0, nums[1] if len(nums) > 1 else 0)
#         elif name == "scale":
#             sx = nums[0] if nums else 1
#             sy = nums[1] if len(nums) > 1 else sx
#             local = (sx, 0, 0, sy, 0, 0)
#         elif name == "rotate" and nums:
#             angle = math.radians(nums[0])
#             c, s = math.cos(angle), math.sin(angle)
#             local = (c, s, -s, c, 0, 0)
#         matrix = _matmul(matrix, local)
#     return matrix


# def _matmul(a: Matrix, b: Matrix) -> Matrix:
#     a1, b1, c1, d1, e1, f1 = a
#     a2, b2, c2, d2, e2, f2 = b
#     return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


# def _apply(matrix: Matrix, x: float, y: float) -> Tuple[float, float]:
#     a, b, c, d, e, f = matrix
#     return a * x + c * y + e, b * x + d * y + f


# def _style(elem: ET.Element) -> Dict[str, str]:
#     result: Dict[str, str] = {}
#     for part in (elem.get("style") or "").split(";"):
#         if ":" in part:
#             key, value = part.split(":", 1)
#             result[key.strip().lower()] = value.strip()
#     for key, value in elem.attrib.items():
#         if key.lower() in {"fill", "stroke", "stroke-width", "font-size", "font-weight", "text-anchor"}:
#             result[key.lower()] = value
#     return result


# def _title(group: ET.Element) -> str:
#     title = group.find(_svg("title"))
#     return _read_text(title) if title is not None else ""


# def _read_text(elem: Optional[ET.Element]) -> str:
#     if elem is None:
#         return ""
#     parts = []
#     if elem.text:
#         parts.append(elem.text)
#     for child in list(elem):
#         t = _read_text(child)
#         if t:
#             parts.append(t)
#         if child.tail:
#             parts.append(child.tail)
#     return html.unescape(" ".join(p.strip() for p in parts if p and p.strip())).strip()


# def _svg_href(elem: ET.Element) -> str:
#     return (elem.get("href") or elem.get(_xlink("href")) or elem.get("xlink:href") or "").strip()


# def _rect_points(elem: ET.Element, matrix: Matrix) -> List[Tuple[float, float]]:
#     x, y = _num(elem.get("x"), 0), _num(elem.get("y"), 0)
#     w, h = _num(elem.get("width"), 0), _num(elem.get("height"), 0)
#     return [] if w <= 0 or h <= 0 else [_apply(matrix, x, y), _apply(matrix, x + w, y), _apply(matrix, x + w, y + h), _apply(matrix, x, y + h)]


# def _points(raw: str) -> List[Tuple[float, float]]:
#     nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw or "")]
#     return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


# def _path_points(raw: str) -> List[Tuple[float, float]]:
#     return _points(raw)


# def _simplify_route(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
#     if len(points) <= 2:
#         return points
#     start, end = points[0], points[-1]
#     mid = points[len(points) // 2]
#     return [start, mid, end] if abs(mid[0] - start[0]) > 8 and abs(mid[1] - end[1]) > 8 else [start, end]


# def _bbox(points: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
#     xs = [p[0] for p in points]
#     ys = [p[1] for p in points]
#     return min(xs), min(ys), max(xs), max(ys)


# def _num(value: Any, default: float = 0.0) -> float:
#     try:
#         return float(re.sub(r"(px|pt|in|cm|mm|%)$", "", str(value).strip(), flags=re.I))
#     except Exception:
#         return default


# def _colour(value: Any, default: str) -> str:
#     raw = str(value or "").strip()
#     if not raw:
#         return default
#     if raw.lower() in {"none", "transparent"}:
#         return "#FFFFFF"
#     named = {"black": "#000000", "white": "#FFFFFF", "red": "#FF0000", "green": "#008000", "blue": "#0000FF", "gray": "#808080", "grey": "#808080", "orange": "#FFA500", "purple": "#800080", "yellow": "#FFFF00", "cyan": "#00FFFF", "magenta": "#FF00FF", "brown": "#A52A2A", "pink": "#FFC0CB", "teal": "#008080"}
#     if raw.lower() in named:
#         return named[raw.lower()]
#     if raw.startswith("#"):
#         return ("#" + "".join(ch * 2 for ch in raw[1:]).upper()) if len(raw) == 4 else raw[:7].upper()
#     rgb = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", raw, flags=re.I)
#     if rgb:
#         return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in rgb.groups())
#     return default


# def _rgb(color: str) -> Tuple[int, int, int]:
#     color = _colour(color, "#000000")
#     return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


# def _pt(value: float) -> float:
#     return max(0.01, float(value) / PT_PER_INCH)


# def _is_near_black(color: str) -> bool:
#     try:
#         r, g, b = _rgb(color)
#         return r < 24 and g < 24 and b < 24
#     except Exception:
#         return False


# def _pastel_color(seed: Any) -> str:
#     palette = ["#E8F0FE", "#E6F4EA", "#FEF7E0", "#FCE8E6", "#F3E8FD", "#E0F2F1", "#FFF3E0", "#E8EAED", "#E3F2FD", "#F1F8E9"]
#     return palette[sum(ord(ch) for ch in str(seed or "node")) % len(palette)]


# def _darker_border(fill: str) -> str:
#     try:
#         r, g, b = _rgb(fill)
#         return f"#{int(r * 0.72):02X}{int(g * 0.72):02X}{int(b * 0.72):02X}"
#     except Exception:
#         return "#666666"


# def _lighten(color: str, factor: float = 0.35) -> str:
#     try:
#         r, g, b = _rgb(color)
#         return f"#{int(r + (255 - r) * factor):02X}{int(g + (255 - g) * factor):02X}{int(b + (255 - b) * factor):02X}"
#     except Exception:
#         return "#FFFFFF"


# def _dedupe_legend_items(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
#     result = []
#     seen = set()
#     for color, label in items or []:
#         safe_color = _colour(color, "#666666")
#         safe_label = _cleanup_visible_text(label)
#         key = (safe_color.lower(), safe_label.lower())
#         if safe_label and key not in seen:
#             seen.add(key)
#             result.append((safe_color, safe_label))
#     return result


# def _local(tag: str) -> str:
#     return str(tag).split("}", 1)[-1].lower()


# def _safe(value: str) -> str:
#     return re.sub(r"[^A-Za-z0-9_. -]+", "_", str(value or "Shape"))[:120] or "Shape"


# def _xml(root: ET.Element) -> str:
#     return "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + ET.tostring(root, encoding="unicode")


# def _xml_plain(root: ET.Element) -> str:
#     return "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + ET.tostring(root, encoding="unicode")


# __all__ = ["VisioExportOptions", "export_vsdx_from_dot", "export_vsdx_from_svg"]

from __future__ import annotations
"""
visio_vsdx_exporter.py

Generic Graphviz DOT/SVG -> editable Visio VSDX exporter.

Public API retained:
- VisioExportOptions
- export_vsdx_from_dot(...)
- export_vsdx_from_svg(...)

Key fixes in this version:
- Icons are resolved again from node labels/SVG/DOT image attributes.
- Icons are editable/removable as a single Visio GROUP shape.
  The icon group contains editable vector cells; deleting the group removes the entire icon.
- No icon cells are locked and no fixed raster images are embedded.
- Icon size increased and centred inside node cards.
- Graphviz layout indentation is preserved; overlap resolution is conservative.
- Cluster/zone overlap is fixed generically by moving the later overlapping zone and its contained nodes.
- DOT source -> target remains the source of truth for arrow direction.
- No service/project/section/name hardcoding.
"""

import html
import logging
import math
import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import unquote
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance
except Exception:  # pragma: no cover
    Image = None  # type: ignore
    ImageEnhance = None  # type: ignore

try:
    from .config import PROJECT_ROOT  # type: ignore
except Exception:
    PROJECT_ROOT = Path.cwd()  # type: ignore

try:
    from .icon_resolver import get_style_for_label, resolve_icon_from_node_label  # type: ignore
except Exception:
    get_style_for_label = None  # type: ignore
    resolve_icon_from_node_label = None  # type: ignore

try:
    from .node_card import clean_label, normalize_icon_for_graphviz  # type: ignore
except Exception:
    clean_label = None  # type: ignore
    normalize_icon_for_graphviz = None  # type: ignore

V_NS = "http://schemas.microsoft.com/office/visio/2012/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
VISIO_REL_NS = "http://schemas.microsoft.com/visio/2010/relationships"
SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
PT_PER_INCH = 72.0
Matrix = Tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
ET.register_namespace("", V_NS)
ET.register_namespace("r", R_NS)


def _v(tag: str) -> str:
    return f"{{{V_NS}}}{tag}"


def _r(tag: str) -> str:
    return f"{{{R_NS}}}{tag}"


def _svg(tag: str) -> str:
    return f"{{{SVG_NS}}}{tag}"


def _xlink(tag: str) -> str:
    return f"{{{XLINK_NS}}}{tag}"


@dataclass
class VisioExportOptions:
    page_name: str = "Diagram"
    page_width_in: Optional[float] = None
    page_height_in: Optional[float] = None
    include_visual_background: bool = False
    include_editable_overlay: bool = True
    lock_visual_background: bool = False
    overlay_boxes_visible: bool = True
    overlay_arrows_visible: bool = True
    overlay_text_visible: bool = False
    include_icons: bool = True
    include_flow_legend: bool = True
    legend_on_separate_page: bool = False
    legend_items: Optional[List[Tuple[str, str]]] = None
    node_font_size_pt: float = 13.0
    node_text_bold: bool = True
    connector_arrow_type: int = 4
    connector_arrow_size: int = 2
    min_page_width_in: float = 11.0
    min_page_height_in: float = 8.5
    fail_on_no_nodes: bool = True

    min_node_width_in: float = 1.70
    min_node_height_in: float = 1.14
    max_node_width_in: float = 2.85
    max_node_height_in: float = 1.62
    min_label_band_height_in: float = 0.38
    max_icon_size_in: float = 0.78

    compact_vector_icons: bool = True
    compact_icon_grid: int = 14
    max_icon_vector_cells: int = 56
    # Must remain False: icons must be editable/removable.
    lock_icon_cells: bool = False
    include_icon_badge: bool = True
    # Must remain False: embedded pictures are not reliably editable/deletable.
    embed_icons_as_pictures: bool = False

    legend_font_size_pt: float = 10.5
    legend_title_font_size_pt: float = 14.0
    legend_row_height_in: float = 0.42
    legend_arrow_length_in: float = 1.05

    include_auto_zones: bool = True
    auto_zone_only_when_no_clusters: bool = True
    auto_zone_labels: Optional[List[str]] = None
    zone_attribute_names: Tuple[str, ...] = ("zone", "group", "platform", "environment", "domain", "lane")
    enable_positional_auto_zones: bool = False
    max_auto_zones: int = 4
    zone_gap_factor: float = 2.75
    default_auto_zone_label: str = "Architecture Zone"
    cluster_fill: str = "#EEF6FF"
    cluster_stroke: str = "#A8C7FA"
    cluster_text: str = "#174EA6"
    zone_header_px: float = 96.0
    zone_padding_px: float = 58.0
    cluster_title_height_in: float = 0.34
    cluster_title_top_margin_in: float = 0.10
    cluster_separation_in: float = 0.70

    shape_warning_limit: int = 1600
    resolve_node_overlaps: bool = True
    prefer_horizontal_reflow: bool = True
    node_collision_margin_in: float = 0.24
    node_collision_iterations: int = 220
    row_group_tolerance_in: float = 0.75
    cluster_reflow_padding_in: float = 0.30


@dataclass
class DotEdge:
    source: str
    target: str
    color: str
    label: str
    direction: str = "forward"


@dataclass
class DotMetadata:
    labels: Dict[str, str]
    attrs: Dict[str, Dict[str, str]]
    legend_items: List[Tuple[str, str]]
    edges: List[DotEdge]


@dataclass
class SvgNode:
    node_id: str
    label: str
    bbox: Tuple[float, float, float, float]
    fill: str
    stroke: str
    stroke_width: float = 1.0
    image_href: str = ""
    icon_path: str = ""
    icon_text: str = ""
    font_color: str = "#000000"
    attrs: Optional[Dict[str, str]] = None


@dataclass
class SvgEdge:
    edge_id: str
    points: List[Tuple[float, float]]
    color: str = "#666666"
    width: float = 1.25
    source: str = ""
    target: str = ""
    direction: str = "forward"
    label: str = ""


@dataclass
class SvgCluster:
    cluster_id: str
    label: str
    bbox: Tuple[float, float, float, float]
    fill: str = "#EEF6FF"
    stroke: str = "#A8C7FA"
    font_color: str = "#174EA6"


@dataclass
class SvgDiagram:
    svg_path: Path
    width_px: float
    height_px: float
    viewbox: Tuple[float, float, float, float]
    nodes: List[SvgNode]
    edges: List[SvgEdge]
    clusters: List[SvgCluster]


def export_vsdx_from_dot(
    dot_path: os.PathLike | str,
    vsdx_path: Optional[os.PathLike | str] = None,
    *,
    output_vsdx_path: Optional[os.PathLike | str] = None,
    svg_path: Optional[os.PathLike | str] = None,
    png_path: Optional[os.PathLike | str] = None,
    options: Optional[VisioExportOptions] = None,
    layout_engine: str = "dot",
    **_: Any,
) -> Path:
    dot = Path(dot_path)
    out = Path(output_vsdx_path or vsdx_path or dot.with_suffix(".vsdx"))
    opts = _normalise_options(options or VisioExportOptions())
    svg = Path(svg_path) if svg_path else out.with_suffix(".svg")
    if not svg.exists():
        _run_graphviz(dot, svg, "svg", layout_engine)
    metadata = _parse_dot_metadata(dot)
    opts.legend_items = _dedupe_legend_items(opts.legend_items or []) or metadata.legend_items
    diagram = SvgParser(svg, metadata, fail_on_no_nodes=False, options=opts).parse()
    if not diagram.nodes:
        diagram.nodes = _fallback_nodes_from_dot_metadata(metadata)
        if opts.include_auto_zones and diagram.nodes:
            diagram.clusters = _auto_zones(diagram.nodes, opts)
    diagram.edges = _merge_svg_routes_with_dot_edges(metadata, diagram.nodes, diagram.edges)
    if opts.fail_on_no_nodes and not diagram.nodes:
        raise RuntimeError(f"VSDX export failed: no editable nodes detected from SVG or DOT: {svg}")
    return VsdxWriter(diagram, out, opts).write()


def export_vsdx_from_svg(
    svg_path: os.PathLike | str,
    output_vsdx_path: os.PathLike | str,
    *,
    png_path: Optional[os.PathLike | str] = None,
    options: Optional[VisioExportOptions] = None,
) -> Path:
    opts = _normalise_options(options or VisioExportOptions())
    diagram = SvgParser(Path(svg_path), DotMetadata({}, {}, [], []), fail_on_no_nodes=opts.fail_on_no_nodes, options=opts).parse()
    return VsdxWriter(diagram, Path(output_vsdx_path), opts).write()


def _normalise_options(opts: VisioExportOptions) -> VisioExportOptions:
    opts.include_icons = bool(getattr(opts, "include_icons", True))
    opts.include_flow_legend = bool(getattr(opts, "include_flow_legend", True))
    opts.compact_vector_icons = bool(getattr(opts, "compact_vector_icons", True))
    opts.lock_icon_cells = False
    opts.embed_icons_as_pictures = False
    opts.node_font_size_pt = max(float(getattr(opts, "node_font_size_pt", 13.0) or 13.0), 13.0)
    opts.max_icon_size_in = max(0.58, min(0.88, float(getattr(opts, "max_icon_size_in", 0.78) or 0.78)))
    opts.compact_icon_grid = max(10, min(18, int(getattr(opts, "compact_icon_grid", 14) or 14)))
    opts.max_icon_vector_cells = max(24, min(80, int(getattr(opts, "max_icon_vector_cells", 56) or 56)))
    opts.node_collision_margin_in = max(0.05, min(0.60, float(getattr(opts, "node_collision_margin_in", 0.24) or 0.24)))
    opts.node_collision_iterations = max(20, min(800, int(getattr(opts, "node_collision_iterations", 220) or 220)))
    opts.row_group_tolerance_in = max(0.20, min(1.50, float(getattr(opts, "row_group_tolerance_in", 0.75) or 0.75)))
    opts.cluster_reflow_padding_in = max(0.08, min(0.80, float(getattr(opts, "cluster_reflow_padding_in", 0.30) or 0.30)))
    opts.cluster_separation_in = max(0.25, min(2.0, float(getattr(opts, "cluster_separation_in", 0.70) or 0.70)))
    opts.zone_header_px = max(60.0, min(180.0, float(getattr(opts, "zone_header_px", 96.0) or 96.0)))
    opts.zone_padding_px = max(36.0, min(150.0, float(getattr(opts, "zone_padding_px", 58.0) or 58.0)))
    opts.shape_warning_limit = max(200, int(getattr(opts, "shape_warning_limit", 1600) or 1600))
    return opts


class SvgParser:
    def __init__(self, svg_path: Path, dot_metadata: DotMetadata, fail_on_no_nodes: bool = True, options: Optional[VisioExportOptions] = None):
        self.svg_path = Path(svg_path)
        self.dot_metadata = dot_metadata
        self.fail_on_no_nodes = fail_on_no_nodes
        self.options = options or VisioExportOptions()
        self.root = ET.parse(str(svg_path)).getroot()
        self.viewbox = self._viewbox()
        self.width_px = _num(self.root.get("width"), self.viewbox[2])
        self.height_px = _num(self.root.get("height"), self.viewbox[3])

    def parse(self) -> SvgDiagram:
        nodes: List[SvgNode] = []
        edges: List[SvgEdge] = []
        clusters: List[SvgCluster] = []
        for elem, matrix, _parents in _iter_svg(self.root):
            if _local(elem.tag) != "g":
                continue
            classes = _class_tokens(elem.get("class"))
            if self._is_cluster_group(elem, classes):
                cluster = self._parse_cluster(elem, matrix)
                if cluster and not self._is_graph_sized(cluster.bbox):
                    clusters.append(cluster)
            elif "node" in classes:
                node = self._parse_node(elem, matrix)
                if node and not self._is_graph_sized(node.bbox):
                    nodes.append(node)
            elif "edge" in classes:
                edge = self._parse_edge(elem, matrix)
                if edge:
                    edges.append(edge)
        if not nodes and self.dot_metadata.labels:
            nodes = _fallback_nodes_from_dot_metadata(self.dot_metadata)
        clusters = _filter_clusters(clusters, nodes, self.options)
        if self.options.include_auto_zones and nodes and (not clusters or not self.options.auto_zone_only_when_no_clusters):
            clusters.extend(_auto_zones(nodes, self.options))
            clusters = _filter_clusters(clusters, nodes, self.options)
        if not edges and self.dot_metadata.edges:
            edges = _fallback_edges_from_dot_metadata(self.dot_metadata, nodes)
        if not nodes and self.fail_on_no_nodes:
            raise RuntimeError(f"VSDX export failed: no editable nodes detected from SVG or DOT: {self.svg_path}")
        return SvgDiagram(self.svg_path, self.width_px, self.height_px, self.viewbox, nodes, edges, clusters)

    def _viewbox(self) -> Tuple[float, float, float, float]:
        raw = self.root.get("viewBox") or self.root.get("viewbox")
        if raw:
            vals = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)]
            if len(vals) >= 4:
                return vals[0], vals[1], vals[2], vals[3]
        return 0.0, 0.0, _num(self.root.get("width"), 1000.0), _num(self.root.get("height"), 800.0)

    def _is_graph_sized(self, bbox: Tuple[float, float, float, float]) -> bool:
        x1, y1, x2, y2 = bbox
        return abs((x2 - x1) * (y2 - y1)) > max(1.0, self.viewbox[2] * self.viewbox[3]) * 0.85

    def _is_cluster_group(self, elem: ET.Element, classes: List[str]) -> bool:
        if "cluster" in classes:
            return True
        if any(token in classes for token in ("node", "edge")):
            return False
        title = (_title(elem) or "").lower()
        return title.startswith("cluster") or title.startswith("subgraph")

    def _parse_cluster(self, group: ET.Element, matrix: Matrix) -> Optional[SvgCluster]:
        title = _title(group) or f"cluster_{id(group)}"
        label = ""
        bodies: List[Tuple[float, float, float, float, str, str]] = []
        for child in group.iter():
            tag = _local(child.tag)
            style = _style(child)
            fill = _colour(style.get("fill") or child.get("fill"), self.options.cluster_fill)
            stroke = _colour(style.get("stroke") or child.get("stroke"), self.options.cluster_stroke)
            points: List[Tuple[float, float]] = []
            if tag == "polygon":
                points = [_apply(matrix, x, y) for x, y in _points(child.get("points") or "")]
            elif tag == "rect":
                points = _rect_points(child, matrix)
            elif tag == "text":
                t = _cleanup_visible_text(_read_text(child))
                if t:
                    label = t
            if points:
                x1, y1, x2, y2 = _bbox(points)
                if abs(x2 - x1) > 15 and abs(y2 - y1) > 15:
                    bodies.append((x1, y1, x2, y2, fill, stroke))
        if not bodies:
            return None
        body = max(bodies, key=lambda b: abs((b[2] - b[0]) * (b[3] - b[1])))
        fill = self.options.cluster_fill if _is_near_black(body[4]) else body[4]
        stroke = self.options.cluster_stroke if _is_near_black(body[5]) else body[5]
        return SvgCluster(title, label or title, (body[0], body[1], body[2], body[3]), fill, stroke, self.options.cluster_text)

    def _parse_node(self, group: ET.Element, matrix: Matrix) -> Optional[SvgNode]:
        title = _title(group) or f"node_{id(group)}"
        dot_attrs = self.dot_metadata.attrs.get(title, {})
        dot_label = self.dot_metadata.labels.get(title, title)
        base_style = _node_visual_style(dot_label, title, dot_attrs)
        bodies: List[Tuple[float, float, float, float, str, str, float, str]] = []
        texts: List[str] = []
        image_candidates: List[str] = []
        if dot_attrs.get("image"):
            image_candidates.append(dot_attrs.get("image", ""))
        for child in group.iter():
            tag = _local(child.tag)
            style = _style(child)
            fill = _colour(style.get("fill") or child.get("fill") or dot_attrs.get("fillcolor"), base_style["fill"])
            stroke = _colour(style.get("stroke") or child.get("stroke") or dot_attrs.get("color"), base_style["border"])
            stroke_width = max(0.75, _num(style.get("stroke-width") or child.get("stroke-width") or dot_attrs.get("penwidth"), 1.0))
            points: List[Tuple[float, float]] = []
            image_href = ""
            if tag == "polygon":
                points = [_apply(matrix, x, y) for x, y in _points(child.get("points") or "")]
            elif tag == "rect":
                points = _rect_points(child, matrix)
            elif tag == "ellipse":
                cx, cy = _num(child.get("cx"), 0.0), _num(child.get("cy"), 0.0)
                rx, ry = _num(child.get("rx"), 0.0), _num(child.get("ry"), 0.0)
                points = [_apply(matrix, cx - rx, cy - ry), _apply(matrix, cx + rx, cy + ry)]
            elif tag == "image":
                image_href = _svg_href(child)
                if image_href:
                    image_candidates.append(image_href)
                x, y = _num(child.get("x"), 0.0), _num(child.get("y"), 0.0)
                width, height = _num(child.get("width"), 0.0), _num(child.get("height"), 0.0)
                if width > 0 and height > 0:
                    points = [_apply(matrix, x, y), _apply(matrix, x + width, y), _apply(matrix, x + width, y + height), _apply(matrix, x, y + height)]
                    fill, stroke = base_style["fill"], base_style["border"]
            elif tag == "text":
                t = _cleanup_visible_text(_read_text(child))
                if t:
                    texts.append(t)
            if points:
                x1, y1, x2, y2 = _bbox(points)
                if abs(x2 - x1) > 4 and abs(y2 - y1) > 4 and not self._is_graph_sized((x1, y1, x2, y2)):
                    if _is_near_black(fill) or fill.upper() == "#FFFFFF":
                        fill, stroke = base_style["fill"], base_style["border"]
                    bodies.append((x1, y1, x2, y2, fill, stroke, stroke_width, image_href))
        label = _cleanup_visible_text(" ".join(texts) or dot_label)
        if not bodies:
            return None
        body = max(bodies, key=lambda b: abs((b[2] - b[0]) * (b[3] - b[1])))
        icon_path = _resolve_icon_path(label) or _extract_icon_from_candidates(image_candidates, self.svg_path.parent)
        return SvgNode(title, label or title, (body[0], body[1], body[2], body[3]), body[4], body[5], body[6], body[7], icon_path, _icon_abbrev(label), base_style.get("font", "#000000"), dot_attrs)

    def _parse_edge(self, group: ET.Element, matrix: Matrix) -> Optional[SvgEdge]:
        title = _title(group) or f"edge_{id(group)}"
        color = "#666666"
        width = 1.25
        all_points: List[Tuple[float, float]] = []
        for path in group.findall(f".//{_svg('path')}"):
            style = _style(path)
            color = _colour(style.get("stroke") or path.get("stroke"), color)
            width = max(1.0, _num(style.get("stroke-width") or path.get("stroke-width"), width))
            path_points = [_apply(matrix, x, y) for x, y in _path_points(path.get("d") or "")]
            if path_points:
                all_points = path_points
                break
        simple = _simplify_route(all_points)
        if len(simple) < 2:
            return None
        source, target = _edge_title_to_source_target(title)
        dot_edge = _find_dot_edge(self.dot_metadata, source, target, title)
        if dot_edge:
            return SvgEdge(title, simple, dot_edge.color or color, width, dot_edge.source, dot_edge.target, dot_edge.direction, dot_edge.label)
        return SvgEdge(title, simple, color, width, source, target, "forward", "")


class VsdxWriter:
    def __init__(self, diagram: SvgDiagram, output_path: Path, options: VisioExportOptions):
        self.diagram = diagram
        self.output_path = Path(output_path)
        self.options = options
        self.shape_id = 100
        self._warned_shape_limit = False
        self.vb_x, self.vb_y, self.vb_w, self.vb_h = diagram.viewbox
        self.vb_w, self.vb_h = max(1.0, self.vb_w), max(1.0, self.vb_h)
        base_w = float(options.page_width_in or max(options.min_page_width_in, diagram.width_px / PT_PER_INCH))
        base_h = float(options.page_height_in or max(options.min_page_height_in, diagram.height_px / PT_PER_INCH))
        self.legend_items = _dedupe_legend_items(options.legend_items or []) if options.include_flow_legend else []
        self.legend_space = self._legend_required_height() if self.legend_items else 0.0
        self.page_w = base_w
        self.page_h = base_h + self.legend_space
        self._compute_scale()
        if self.options.resolve_node_overlaps:
            self._resolve_node_overlaps_in_svg_space()
            self._expand_clusters_after_node_reflow()
            self._separate_overlapping_clusters()
            self._fit_reflowed_diagram_to_page()

    def _compute_scale(self) -> None:
        available_h = max(1.0, self.page_h - self.legend_space - 0.35)
        self.scale = min(self.page_w / self.vb_w, available_h / self.vb_h)
        self.offset_x = (self.page_w - self.vb_w * self.scale) / 2.0
        self.offset_y = self.legend_space + (available_h - self.vb_h * self.scale) / 2.0

    def _legend_required_height(self) -> float:
        return max(1.2, self.options.legend_row_height_in * (len(self.legend_items) + 1.8) + 0.35)

    def _visual_node_size_svg(self, node: SvgNode) -> Tuple[float, float]:
        x1, y1, x2, y2 = node.bbox
        raw_w_svg = max(1.0, abs(x2 - x1))
        raw_h_svg = max(1.0, abs(y2 - y1))
        label = _wrap_label(node.label)
        line_count = max(1, label.count("\n") + 1)
        label_len = max([len(part) for part in label.split("\n") if part] or [1])
        label_w_need_in = min(self.options.max_node_width_in, max(self.options.min_node_width_in, label_len * 0.075 + 0.55))
        min_w_in = max(self.options.min_node_width_in, min(self.options.max_node_width_in, self.page_w * 0.11), label_w_need_in)
        label_h_in = max(self.options.min_label_band_height_in, min(0.64, 0.23 * line_count + 0.12))
        min_h_in = max(self.options.min_node_height_in, label_h_in + 0.94)
        return max(raw_w_svg, min_w_in / max(self.scale, 1e-6)), max(raw_h_svg, min_h_in / max(self.scale, 1e-6))

    def _resolve_node_overlaps_in_svg_space(self) -> None:
        nodes = list(self.diagram.nodes or [])
        if len(nodes) < 2:
            return
        margin_svg = self.options.node_collision_margin_in / max(self.scale, 1e-6)
        layout: Dict[str, Dict[str, float]] = {}
        for node in nodes:
            x1, y1, x2, y2 = node.bbox
            w, h = self._visual_node_size_svg(node)
            layout[node.node_id] = {"cx": (x1 + x2) / 2.0, "cy": (y1 + y2) / 2.0, "w": w, "h": h}
        if self.options.prefer_horizontal_reflow:
            self._row_reflow_layout(nodes, layout, margin_svg)
        # Conservative pairwise collision resolution only when boxes truly overlap.
        for _ in range(self.options.node_collision_iterations):
            moved = False
            for i in range(len(nodes)):
                a = layout[nodes[i].node_id]
                for j in range(i + 1, len(nodes)):
                    b = layout[nodes[j].node_id]
                    dx, dy = b["cx"] - a["cx"], b["cy"] - a["cy"]
                    overlap_x = (a["w"] + b["w"]) / 2.0 + margin_svg - abs(dx)
                    overlap_y = (a["h"] + b["h"]) / 2.0 + margin_svg - abs(dy)
                    if overlap_x <= 0 or overlap_y <= 0:
                        continue
                    moved = True
                    same_row = abs(dy) < max(a["h"], b["h"]) * 0.70
                    if same_row or overlap_x <= overlap_y:
                        direction = 1.0 if dx >= 0 else -1.0
                        shift = overlap_x / 2.0
                        a["cx"] -= direction * shift
                        b["cx"] += direction * shift
                    else:
                        direction = 1.0 if dy >= 0 else -1.0
                        shift = overlap_y / 2.0
                        a["cy"] -= direction * shift
                        b["cy"] += direction * shift
            if not moved:
                break
        for node in nodes:
            item = layout[node.node_id]
            w, h = item["w"], item["h"]
            node.bbox = (item["cx"] - w / 2.0, item["cy"] - h / 2.0, item["cx"] + w / 2.0, item["cy"] + h / 2.0)

    def _row_reflow_layout(self, nodes: List[SvgNode], layout: Dict[str, Dict[str, float]], margin_svg: float) -> None:
        tolerance_svg = self.options.row_group_tolerance_in / max(self.scale, 1e-6)
        rows: List[List[SvgNode]] = []
        for node in sorted(nodes, key=lambda n: layout[n.node_id]["cy"]):
            cy = layout[node.node_id]["cy"]
            placed = False
            for row in rows:
                row_cy = sum(layout[n.node_id]["cy"] for n in row) / len(row)
                if abs(cy - row_cy) <= tolerance_svg:
                    row.append(node)
                    placed = True
                    break
            if not placed:
                rows.append([node])
        for row in rows:
            row.sort(key=lambda n: layout[n.node_id]["cx"])
            if len(row) < 2:
                continue
            original_centre = sum(layout[n.node_id]["cx"] for n in row) / len(row)
            row_cy = sum(layout[n.node_id]["cy"] for n in row) / len(row)
            for node in row:
                layout[node.node_id]["cy"] = row_cy
            for idx in range(1, len(row)):
                prev = layout[row[idx - 1].node_id]
                cur = layout[row[idx].node_id]
                min_cx = prev["cx"] + prev["w"] / 2.0 + cur["w"] / 2.0 + margin_svg
                if cur["cx"] < min_cx:
                    cur["cx"] = min_cx
            new_centre = sum(layout[n.node_id]["cx"] for n in row) / len(row)
            for node in row:
                layout[node.node_id]["cx"] += original_centre - new_centre

    def _nodes_in_cluster(self, cluster: SvgCluster) -> List[SvgNode]:
        x1, y1, x2, y2 = cluster.bbox
        return [n for n in self.diagram.nodes if x1 <= (n.bbox[0] + n.bbox[2]) / 2 <= x2 and y1 <= (n.bbox[1] + n.bbox[3]) / 2 <= y2]

    def _expand_clusters_after_node_reflow(self) -> None:
        if not self.diagram.clusters or not self.diagram.nodes:
            return
        pad_svg = max(self.options.zone_padding_px, self.options.cluster_reflow_padding_in / max(self.scale, 1e-6))
        header_svg = max(self.options.zone_header_px, pad_svg * 1.70)
        updated: List[SvgCluster] = []
        for cluster in self.diagram.clusters:
            contained = self._nodes_in_cluster(cluster)
            if cluster.cluster_id.startswith("auto_zone_") and len(self.diagram.clusters) == 1:
                contained = list(self.diagram.nodes)
            if not contained:
                updated.append(cluster)
                continue
            min_x = min(n.bbox[0] for n in contained)
            min_y = min(n.bbox[1] for n in contained)
            max_x = max(n.bbox[2] for n in contained)
            max_y = max(n.bbox[3] for n in contained)
            cx1, cy1, cx2, cy2 = cluster.bbox
            updated.append(SvgCluster(cluster.cluster_id, cluster.label, (min(cx1, min_x - pad_svg), min(cy1, min_y - header_svg), max(cx2, max_x + pad_svg), max(cy2, max_y + pad_svg)), cluster.fill, cluster.stroke, cluster.font_color))
        self.diagram.clusters = updated

    def _shift_cluster_and_nodes(self, cluster: SvgCluster, dx: float, dy: float = 0.0) -> SvgCluster:
        contained = self._nodes_in_cluster(cluster)
        for n in contained:
            x1, y1, x2, y2 = n.bbox
            n.bbox = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
        x1, y1, x2, y2 = cluster.bbox
        return SvgCluster(cluster.cluster_id, cluster.label, (x1 + dx, y1 + dy, x2 + dx, y2 + dy), cluster.fill, cluster.stroke, cluster.font_color)

    def _separate_overlapping_clusters(self) -> None:
        clusters = sorted(self.diagram.clusters, key=lambda c: (c.bbox[0], c.bbox[1]))
        if len(clusters) < 2:
            return
        gap = self.options.cluster_separation_in / max(self.scale, 1e-6)
        fixed: List[SvgCluster] = []
        for cluster in clusters:
            current = cluster
            changed = True
            guard = 0
            while changed and guard < 20:
                changed = False
                guard += 1
                for prev in fixed:
                    if _boxes_overlap(current.bbox, prev.bbox, margin=gap):
                        dx = (prev.bbox[2] + gap) - current.bbox[0]
                        current = self._shift_cluster_and_nodes(current, dx, 0.0)
                        changed = True
                        break
            fixed.append(current)
        self.diagram.clusters = fixed

    def _fit_reflowed_diagram_to_page(self) -> None:
        boxes = [n.bbox for n in self.diagram.nodes] + [c.bbox for c in self.diagram.clusters]
        if not boxes:
            return
        min_x = min(b[0] for b in boxes)
        min_y = min(b[1] for b in boxes)
        max_x = max(b[2] for b in boxes)
        max_y = max(b[3] for b in boxes)
        pad_x = max(24.0, (max_x - min_x) * 0.045)
        pad_y = max(24.0, (max_y - min_y) * 0.08)
        self.vb_x = min_x - pad_x
        self.vb_y = min_y - pad_y
        self.vb_w = max(1.0, (max_x - min_x) + 2 * pad_x)
        self.vb_h = max(1.0, (max_y - min_y) + 2 * pad_y)
        self._compute_scale()

    def write(self) -> Path:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.output_path.with_suffix(".tmp.vsdx")
        if tmp.exists():
            tmp.unlink()
        template = self._template_path()
        if template:
            shutil.copyfile(template, tmp)
            self._rewrite_template(tmp)
        else:
            self._write_minimal(tmp)
        tmp.replace(self.output_path)
        self._validate_package(self.output_path)
        return self.output_path

    def _template_path(self) -> Optional[Path]:
        try:
            import vsdx  # type: ignore
            path = Path(vsdx.__file__).parent / "media" / "media.vsdx"
            return path if path.exists() else None
        except Exception:
            return None

    def _rewrite_template(self, path: Path) -> None:
        replacements = {
            "visio/pages/page1.xml": self._page_xml().encode("utf-8"),
            "visio/pages/pages.xml": self._pages_xml().encode("utf-8"),
            "visio/windows.xml": self._windows_xml().encode("utf-8"),
            "visio/pages/_rels/page1.xml.rels": self._page_rels_xml().encode("utf-8"),
        }
        original = path.with_suffix(".orig.vsdx")
        path.replace(original)
        try:
            with zipfile.ZipFile(original, "r") as zin, zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zout:
                seen = set()
                for item in zin.infolist():
                    data = self._content_types_xml() if item.filename == "[Content_Types].xml" else replacements.get(item.filename, zin.read(item.filename))
                    zout.writestr(item.filename, data)
                    seen.add(item.filename)
                for name, data in replacements.items():
                    if name not in seen:
                        zout.writestr(name, data)
        finally:
            try:
                original.unlink()
            except Exception:
                pass

    def _write_minimal(self, path: Path) -> None:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", self._content_types_xml())
            z.writestr("_rels/.rels", self._root_rels_xml())
            z.writestr("visio/document.xml", self._document_xml())
            z.writestr("visio/_rels/document.xml.rels", self._document_rels_xml())
            z.writestr("visio/masters/masters.xml", self._masters_xml())
            z.writestr("visio/pages/pages.xml", self._pages_xml())
            z.writestr("visio/pages/_rels/pages.xml.rels", self._pages_rels_xml())
            z.writestr("visio/pages/page1.xml", self._page_xml())
            z.writestr("visio/pages/_rels/page1.xml.rels", self._page_rels_xml())
            z.writestr("visio/windows.xml", self._windows_xml())
            z.writestr("docProps/app.xml", self._app_xml())
            z.writestr("docProps/core.xml", self._core_xml())

    def _page_xml(self) -> str:
        root = ET.Element(_v("PageContents"), {"xml:space": "preserve"})
        shapes = ET.SubElement(root, _v("Shapes"))
        for cluster in self.diagram.clusters:
            self._append_cluster_shape(shapes, cluster)
        for edge in self.diagram.edges:
            self._append_edge_shape(shapes, edge)
        for node in self.diagram.nodes:
            self._append_card_shape(shapes, node)
        if self.legend_items:
            self._append_legend_items(shapes, self.legend_items)
        page_sheet = ET.SubElement(root, _v("PageSheet"), {"LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._cell(page_sheet, "PageWidth", self.page_w)
        self._cell(page_sheet, "PageHeight", self.page_h)
        self._cell(page_sheet, "DrawingScale", 1)
        self._cell(page_sheet, "PageScale", 1)
        return _xml(root)

    def _append_cluster_shape(self, parent: ET.Element, cluster: SvgCluster) -> None:
        x1, y1, x2, y2 = cluster.bbox
        w, h = self._size(x2 - x1, y2 - y1)
        cx, cy = self._xy((x1 + x2) / 2, (y1 + y2) / 2)
        body = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(cluster.cluster_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(body, cx, cy, w, h)
        self._color_cell(body, "FillForegnd", cluster.fill)
        self._color_cell(body, "FillBkgnd", cluster.fill)
        self._cell(body, "FillPattern", 1)
        self._cell(body, "FillForegndTrans", 15)
        self._color_cell(body, "LineColor", cluster.stroke)
        self._cell(body, "LineWeight", _pt(1.5))
        self._cell(body, "Rounding", 0.12)
        self._rectangle_geometry(body)
        ET.SubElement(body, _v("Text"))
        title = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(cluster.cluster_id + "_title"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        title_h = self.options.cluster_title_height_in
        self._base_shape_cells(title, cx, cy + h / 2 - title_h / 2 - self.options.cluster_title_top_margin_in, max(0.6, w - 0.24), title_h)
        self._cell(title, "LinePattern", 0)
        self._cell(title, "FillPattern", 0)
        self._character_section(title, 12.5, True, cluster.font_color)
        self._paragraph_section(title, 1)
        self._text_block(title, left_margin=0.02)
        self._rectangle_geometry(title, no_line=True, no_fill=True)
        ET.SubElement(title, _v("Text")).text = _cleanup_visible_text(cluster.label)

    def _append_card_shape(self, parent: ET.Element, node: SvgNode) -> None:
        x1, y1, x2, y2 = node.bbox
        raw_w, raw_h = self._size(x2 - x1, y2 - y1)
        cx, cy = self._xy((x1 + x2) / 2, (y1 + y2) / 2)
        label = _wrap_label(node.label)
        line_count = max(1, label.count("\n") + 1)
        label_len = max([len(p) for p in label.split("\n") if p] or [1])
        label_w_need = min(self.options.max_node_width_in, max(self.options.min_node_width_in, label_len * 0.075 + 0.55))
        w = max(raw_w, self.options.min_node_width_in, label_w_need)
        label_h = max(self.options.min_label_band_height_in, min(0.64, 0.23 * line_count + 0.12))
        h = max(raw_h, self.options.min_node_height_in, label_h + 0.94)
        icon_size = max(0.54, min(self.options.max_icon_size_in, h - label_h - 0.18, w * 0.38))
        icon_cy = cy + h / 2 - max(0.07, h * 0.065) - icon_size / 2
        band_cy = cy - h / 2 + label_h / 2 + 0.06

        body = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(body, cx, cy, w, h)
        self._color_cell(body, "FillForegnd", node.fill)
        self._color_cell(body, "FillBkgnd", node.fill)
        self._cell(body, "FillPattern", 1)
        self._cell(body, "LinePattern", 1)
        self._color_cell(body, "LineColor", node.stroke)
        self._cell(body, "LineWeight", _pt(max(1.0, node.stroke_width)))
        self._cell(body, "Rounding", 0.08)
        self._rectangle_geometry(body)
        ET.SubElement(body, _v("Text"))

        band = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node.node_id + "_label_band"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(band, cx, band_cy, max(0.45, w - 0.18), label_h)
        self._color_cell(band, "FillForegnd", "#FFFFFF")
        self._color_cell(band, "FillBkgnd", "#FFFFFF")
        self._cell(band, "FillPattern", 1)
        self._cell(band, "LinePattern", 0)
        self._cell(band, "Rounding", 0.05)
        self._character_section(band, max(9.5, min(12.5, self.options.node_font_size_pt - max(0, line_count - 1) * 1.2)), True, node.font_color)
        self._paragraph_section(band, 1)
        self._text_block(band, left_margin=0.035)
        self._rectangle_geometry(band, no_line=True)
        ET.SubElement(band, _v("Text")).text = label

        if self.options.include_icons:
            if node.icon_path:
                added = self._append_icon_group(parent, cx, icon_cy, icon_size, node.icon_path, node.node_id, node.stroke)
                if not added:
                    self._append_icon_symbol(parent, cx, icon_cy, icon_size, node.node_id, node.icon_text, node.stroke)
            else:
                self._append_icon_symbol(parent, cx, icon_cy, icon_size, node.node_id, node.icon_text, node.stroke)

    def _append_icon_symbol(self, parent: ET.Element, cx: float, cy: float, size: float, node_id: str, text: str, color: str) -> None:
        icon = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node_id + "_editable_icon"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(icon, cx, cy, size * 1.08, size * 1.08)
        self._color_cell(icon, "FillForegnd", _lighten(color, 0.88))
        self._color_cell(icon, "FillBkgnd", _lighten(color, 0.88))
        self._cell(icon, "FillPattern", 1)
        self._cell(icon, "LinePattern", 1)
        self._color_cell(icon, "LineColor", color)
        self._cell(icon, "LineWeight", _pt(0.75))
        self._cell(icon, "Rounding", 0.04)
        self._rectangle_geometry(icon)
        self._character_section(icon, 13.0, True, color)
        self._paragraph_section(icon, 1)
        self._text_block(icon, left_margin=0.01)
        ET.SubElement(icon, _v("Text")).text = text or "•"

    def _append_icon_group(self, parent: ET.Element, cx: float, cy: float, size: float, icon_path: str, node_id: str, border: str) -> bool:
        cells = _icon_compact_cells(icon_path, grid=self.options.compact_icon_grid, max_cells=self.options.max_icon_vector_cells)
        if not cells:
            return False
        group_id = self._next_id()
        group = ET.SubElement(parent, _v("Shape"), {"ID": str(group_id), "Type": "Group", "NameU": _safe(node_id + "_editable_icon_group"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(group, cx, cy, size * 1.10, size * 1.10)
        self._cell(group, "LinePattern", 0)
        self._cell(group, "FillPattern", 0)
        self._rectangle_geometry(group, no_line=True, no_fill=True)
        child_shapes = ET.SubElement(group, _v("Shapes"))

        # Editable background badge inside the group. Deleting group deletes badge and icon cells together.
        badge = ET.SubElement(child_shapes, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(node_id + "_icon_badge"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(badge, size * 0.55, size * 0.55, size * 1.08, size * 1.08)
        self._color_cell(badge, "FillForegnd", _lighten(border, 0.88))
        self._color_cell(badge, "FillBkgnd", _lighten(border, 0.88))
        self._cell(badge, "FillPattern", 1)
        self._cell(badge, "LinePattern", 1)
        self._color_cell(badge, "LineColor", border)
        self._cell(badge, "LineWeight", _pt(0.65))
        self._cell(badge, "Rounding", 0.04)
        self._rectangle_geometry(badge)
        ET.SubElement(badge, _v("Text"))

        grid = max(1, max(max(x for x, _, _ in cells) + 1, max(y for _, y, _ in cells) + 1))
        icon_draw_size = size * 0.78
        cell = icon_draw_size / grid
        ox = (size * 1.10 - icon_draw_size) / 2.0
        oy_top = (size * 1.10 + icon_draw_size) / 2.0
        for ix, iy, color in cells:
            px = ox + (ix + 0.5) * cell
            py = oy_top - (iy + 0.5) * cell
            shape = ET.SubElement(child_shapes, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(f"{node_id}_icon_cell_{ix}_{iy}"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
            self._base_shape_cells(shape, px, py, cell * 1.22, cell * 1.22)
            self._color_cell(shape, "FillForegnd", color)
            self._color_cell(shape, "FillBkgnd", color)
            self._cell(shape, "FillPattern", 1)
            self._cell(shape, "LinePattern", 0)
            self._rectangle_geometry(shape, no_line=True)
            ET.SubElement(shape, _v("Text"))
        return True

    def _node_by_id_or_label(self, value: str) -> Optional[SvgNode]:
        key = _norm_identity(value)
        if not key:
            return None
        for node in self.diagram.nodes:
            if _norm_identity(node.node_id) == key or _norm_identity(node.label) == key:
                return node
        return None

    def _edge_points_for_current_layout(self, edge: SvgEdge) -> List[Tuple[float, float]]:
        if not self.diagram.nodes:
            return edge.points
        source = self._node_by_id_or_label(edge.source) if edge.source else None
        target = self._node_by_id_or_label(edge.target) if edge.target else None
        if not source or not target:
            if len(edge.points) < 2:
                return edge.points
            source = self._nearest_node_to_point(edge.points[0])
            target = self._nearest_node_to_point(edge.points[-1], exclude_id=source.node_id if source else None)
        if not source or not target or source.node_id == target.node_id:
            return edge.points
        return [self._boundary_point_towards(source.bbox, target.bbox), self._boundary_point_towards(target.bbox, source.bbox)]

    def _nearest_node_to_point(self, point: Tuple[float, float], exclude_id: Optional[str] = None) -> Optional[SvgNode]:
        px, py = point
        best = None
        best_dist = float("inf")
        for node in self.diagram.nodes:
            if exclude_id and node.node_id == exclude_id:
                continue
            x1, y1, x2, y2 = node.bbox
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            dx = max(x1 - px, 0, px - x2)
            dy = max(y1 - py, 0, py - y2)
            dist = dx * dx + dy * dy + 0.0001 * ((cx - px) ** 2 + (cy - py) ** 2)
            if dist < best_dist:
                best_dist = dist
                best = node
        return best

    def _boundary_point_towards(self, bbox: Tuple[float, float, float, float], other_bbox: Tuple[float, float, float, float]) -> Tuple[float, float]:
        x1, y1, x2, y2 = bbox
        ox1, oy1, ox2, oy2 = other_bbox
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        ocx, ocy = (ox1 + ox2) / 2, (oy1 + oy2) / 2
        dx, dy = ocx - cx, ocy - cy
        return ((x2 if dx >= 0 else x1), cy) if abs(dx) >= abs(dy) else (cx, (y2 if dy >= 0 else y1))

    def _append_edge_shape(self, parent: ET.Element, edge: SvgEdge) -> None:
        points = [self._xy(x, y) for x, y in self._edge_points_for_current_layout(edge)]
        if len(points) < 2:
            return
        min_x, min_y, max_x, max_y = _bbox(points)
        w, h = max(0.01, max_x - min_x), max(0.01, max_y - min_y)
        shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(edge.edge_id), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(shape, min_x + w / 2, min_y + h / 2, w, h)
        self._color_cell(shape, "LineColor", edge.color)
        self._cell(shape, "LineWeight", _pt(max(1.25, edge.width)))
        self._cell(shape, "LinePattern", 1)
        direction = _normalise_dot_direction(edge.direction, directed=True)
        self._cell(shape, "BeginArrow", self.options.connector_arrow_type if direction in {"back", "both"} else 0)
        self._cell(shape, "EndArrow", self.options.connector_arrow_type if direction in {"forward", "both"} else 0)
        self._cell(shape, "BeginArrowSize", self.options.connector_arrow_size)
        self._cell(shape, "EndArrowSize", self.options.connector_arrow_size)
        self._line_geometry(shape, points, min_x, min_y, w, h)
        ET.SubElement(shape, _v("Text"))

    def _append_legend_items(self, parent: ET.Element, items: List[Tuple[str, str]]) -> None:
        items = _dedupe_legend_items(items)
        x = 0.65
        y = 0.35 + self.options.legend_row_height_in * len(items)
        self._append_free_text(parent, "Flow Legend", x, y + 0.38, self.options.legend_title_font_size_pt, True)
        for idx, (color, label) in enumerate(items):
            row_y = y - self.options.legend_row_height_in * idx
            self._append_page_line(parent, x, row_y, x + self.options.legend_arrow_length_in, row_y, color)
            self._append_free_text(parent, label, x + self.options.legend_arrow_length_in + 0.25, row_y, self.options.legend_font_size_pt, False)

    def _append_free_text(self, parent: ET.Element, text: str, x: float, y: float, font_pt: float, bold: bool) -> None:
        text = _cleanup_visible_text(text)
        w, h = max(1.0, min(13.0, len(text) * font_pt / 72.0 * 0.55)), 0.28
        shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": _safe(text[:40] or "Text"), "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(shape, x + w / 2, y, w, h)
        self._cell(shape, "LinePattern", 0)
        self._cell(shape, "FillPattern", 0)
        self._character_section(shape, font_pt, bold, "#000000")
        self._paragraph_section(shape, 0)
        self._rectangle_geometry(shape, no_line=True, no_fill=True)
        ET.SubElement(shape, _v("Text")).text = text

    def _append_page_line(self, parent: ET.Element, x1: float, y1: float, x2: float, y2: float, color: str) -> None:
        min_x, min_y, max_x, max_y = min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)
        w, h = max(0.01, max_x - min_x), max(0.01, max_y - min_y)
        shape = ET.SubElement(parent, _v("Shape"), {"ID": str(self._next_id()), "Type": "Shape", "NameU": "Legend_Line", "LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._base_shape_cells(shape, min_x + w / 2, min_y + h / 2, w, h)
        self._color_cell(shape, "LineColor", color)
        self._cell(shape, "LineWeight", _pt(1.80))
        self._cell(shape, "BeginArrow", 0)
        self._cell(shape, "EndArrow", 4)
        self._line_geometry(shape, [(x1, y1), (x2, y2)], min_x, min_y, w, h)
        ET.SubElement(shape, _v("Text"))

    def _base_shape_cells(self, shape: ET.Element, cx: float, cy: float, w: float, h: float) -> None:
        self._cell(shape, "PinX", cx)
        self._cell(shape, "PinY", cy)
        self._cell(shape, "Width", w)
        self._cell(shape, "Height", h)
        self._cell(shape, "LocPinX", w / 2, "Width*0.5")
        self._cell(shape, "LocPinY", h / 2, "Height*0.5")
        self._cell(shape, "Angle", 0)
        self._cell(shape, "FlipX", 0)
        self._cell(shape, "FlipY", 0)
        self._cell(shape, "ResizeMode", 0)

    def _character_section(self, shape: ET.Element, font_pt: float, bold: bool, color: str) -> None:
        section = ET.SubElement(shape, _v("Section"), {"N": "Character"})
        row = ET.SubElement(section, _v("Row"), {"IX": "0"})
        self._cell(row, "Size", _pt(font_pt))
        self._cell(row, "Style", 17 if bold else 0)
        self._color_cell(row, "Color", color)

    def _paragraph_section(self, shape: ET.Element, align: int) -> None:
        section = ET.SubElement(shape, _v("Section"), {"N": "Paragraph"})
        row = ET.SubElement(section, _v("Row"), {"IX": "0"})
        self._cell(row, "HorzAlign", align)

    def _text_block(self, shape: ET.Element, left_margin: float = 0.06) -> None:
        block = ET.SubElement(shape, _v("TextBlock"))
        self._cell(block, "VerticalAlign", 1)
        self._cell(block, "LeftMargin", left_margin)
        self._cell(block, "RightMargin", 0.06)
        self._cell(block, "TopMargin", 0.03)
        self._cell(block, "BottomMargin", 0.03)

    def _rectangle_geometry(self, shape: ET.Element, *, no_line: bool = False, no_fill: bool = False) -> None:
        geom = ET.SubElement(shape, _v("Section"), {"N": "Geometry", "IX": "0"})
        self._cell(geom, "NoFill", 1 if no_fill else 0)
        self._cell(geom, "NoLine", 1 if no_line else 0)
        for row_type, ix, x, y in [("RelMoveTo", 1, 0, 0), ("RelLineTo", 2, 1, 0), ("RelLineTo", 3, 1, 1), ("RelLineTo", 4, 0, 1), ("RelLineTo", 5, 0, 0)]:
            row = ET.SubElement(geom, _v("Row"), {"T": row_type, "IX": str(ix)})
            self._cell(row, "X", x)
            self._cell(row, "Y", y)

    def _line_geometry(self, shape: ET.Element, points: List[Tuple[float, float]], min_x: float, min_y: float, w: float, h: float) -> None:
        geom = ET.SubElement(shape, _v("Section"), {"N": "Geometry", "IX": "0"})
        self._cell(geom, "NoFill", 1)
        self._cell(geom, "NoLine", 0)
        for ix, (x, y) in enumerate(points, start=1):
            row = ET.SubElement(geom, _v("Row"), {"T": "RelMoveTo" if ix == 1 else "RelLineTo", "IX": str(ix)})
            self._cell(row, "X", 0 if w <= 0 else (x - min_x) / w)
            self._cell(row, "Y", 0 if h <= 0 else (y - min_y) / h)

    def _pages_xml(self) -> str:
        root = ET.Element(_v("Pages"), {"xml:space": "preserve"})
        page = ET.SubElement(root, _v("Page"), {"ID": "0", "NameU": self.options.page_name or "Diagram", "Name": self.options.page_name or "Diagram", "ViewScale": "1", "ViewCenterX": str(self.page_w / 2), "ViewCenterY": str(self.page_h / 2)})
        sheet = ET.SubElement(page, _v("PageSheet"), {"LineStyle": "0", "FillStyle": "0", "TextStyle": "0"})
        self._cell(sheet, "PageWidth", self.page_w)
        self._cell(sheet, "PageHeight", self.page_h)
        ET.SubElement(page, _v("Rel"), {_r("id"): "rId1"})
        return _xml(root)

    def _windows_xml(self) -> str:
        root = ET.Element(_v("Windows"), {"xml:space": "preserve"})
        win = ET.SubElement(root, _v("Window"), {"ID": "0", "WindowType": "Drawing", "ContainerType": "Page", "Container": "0"})
        self._cell(win, "ViewScale", 1)
        self._cell(win, "ViewCenterX", self.page_w / 2)
        self._cell(win, "ViewCenterY", self.page_h / 2)
        return _xml(root)

    def _content_types_xml(self) -> str:
        root = ET.Element("Types", {"xmlns": "http://schemas.openxmlformats.org/package/2006/content-types"})
        for ext, ctype in {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}.items():
            ET.SubElement(root, "Default", {"Extension": ext, "ContentType": ctype})
        for part, ctype in {
            "/visio/document.xml": "application/vnd.ms-visio.drawing.main+xml",
            "/visio/pages/pages.xml": "application/vnd.ms-visio.pages+xml",
            "/visio/pages/page1.xml": "application/vnd.ms-visio.page+xml",
            "/visio/windows.xml": "application/vnd.ms-visio.windows+xml",
            "/visio/masters/masters.xml": "application/vnd.ms-visio.masters+xml",
            "/docProps/app.xml": "application/vnd.openxmlformats-officedocument.extended-properties+xml",
            "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        }.items():
            ET.SubElement(root, "Override", {"PartName": part, "ContentType": ctype})
        return _xml_plain(root)

    def _root_rels_xml(self) -> str:
        root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
        ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/document", "Target": "visio/document.xml"})
        ET.SubElement(root, "Relationship", {"Id": "rId2", "Type": "http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties", "Target": "docProps/core.xml"})
        ET.SubElement(root, "Relationship", {"Id": "rId3", "Type": f"{R_NS}/extended-properties", "Target": "docProps/app.xml"})
        return _xml_plain(root)

    def _document_xml(self) -> str:
        return _xml(ET.Element(_v("VisioDocument"), {"xml:space": "preserve"}))

    def _document_rels_xml(self) -> str:
        root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
        ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/masters", "Target": "masters/masters.xml"})
        ET.SubElement(root, "Relationship", {"Id": "rId2", "Type": f"{VISIO_REL_NS}/pages", "Target": "pages/pages.xml"})
        ET.SubElement(root, "Relationship", {"Id": "rId3", "Type": f"{VISIO_REL_NS}/windows", "Target": "windows.xml"})
        return _xml_plain(root)

    def _pages_rels_xml(self) -> str:
        root = ET.Element("Relationships", {"xmlns": PKG_REL_NS})
        ET.SubElement(root, "Relationship", {"Id": "rId1", "Type": f"{VISIO_REL_NS}/page", "Target": "page1.xml"})
        return _xml_plain(root)

    def _page_rels_xml(self) -> str:
        return _xml_plain(ET.Element("Relationships", {"xmlns": PKG_REL_NS}))

    def _masters_xml(self) -> str:
        return _xml(ET.Element(_v("Masters"), {"xml:space": "preserve"}))

    def _app_xml(self) -> str:
        root = ET.Element("Properties", {"xmlns": "http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"})
        ET.SubElement(root, "Application").text = "Microsoft Visio"
        return _xml_plain(root)

    def _core_xml(self) -> str:
        root = ET.Element("cp:coreProperties", {"xmlns:cp": "http://schemas.openxmlformats.org/package/2006/metadata/core-properties", "xmlns:dc": "http://purl.org/dc/elements/1.1/"})
        ET.SubElement(root, "dc:title").text = self.options.page_name or "Diagram"
        return _xml_plain(root)

    def _xy(self, x: float, y: float) -> Tuple[float, float]:
        return self.offset_x + (x - self.vb_x) * self.scale, self.offset_y + (self.vb_h - (y - self.vb_y)) * self.scale

    def _size(self, width: float, height: float) -> Tuple[float, float]:
        return max(0.02, abs(width) * self.scale), max(0.02, abs(height) * self.scale)

    def _next_id(self) -> int:
        self.shape_id += 1
        if self.shape_id - 100 > self.options.shape_warning_limit and not self._warned_shape_limit:
            self._warned_shape_limit = True
            logger.warning("VSDX shape count exceeded warning limit")
        return self.shape_id

    def _cell(self, parent: ET.Element, name: str, value: Any, formula: Optional[str] = None) -> None:
        attrs = {"N": name, "V": str(value)}
        if formula:
            attrs["F"] = formula
        ET.SubElement(parent, _v("Cell"), attrs)

    def _color_cell(self, parent: ET.Element, name: str, color: str) -> None:
        r, g, b = _rgb(color)
        ET.SubElement(parent, _v("Cell"), {"N": name, "V": _colour(color, "#000000"), "F": f"RGB({r},{g},{b})"})

    def _validate_package(self, path: Path) -> None:
        required = {"[Content_Types].xml", "_rels/.rels", "visio/document.xml", "visio/pages/pages.xml", "visio/pages/page1.xml", "visio/pages/_rels/pages.xml.rels", "visio/pages/_rels/page1.xml.rels", "visio/windows.xml"}
        with zipfile.ZipFile(path, "r") as z:
            missing = sorted(required - set(z.namelist()))
            if missing:
                raise RuntimeError(f"Generated VSDX package is missing required parts: {missing}")

# ----------------------------- DOT and layout helpers -----------------------------

def _parse_dot_metadata(dot_path: Path) -> DotMetadata:
    labels: Dict[str, str] = {}
    attrs_by_node: Dict[str, Dict[str, str]] = {}
    edges: List[DotEdge] = []
    if not dot_path.exists():
        return DotMetadata(labels, attrs_by_node, [], [])
    statements = _split_dot_statements(dot_path.read_text(encoding="utf-8", errors="replace"))
    for statement in statements:
        stripped = statement.strip().rstrip(";")
        if not stripped or "->" in stripped or "--" in stripped or "[" not in stripped or "]" not in stripped:
            continue
        if stripped.lower().startswith(("digraph", "graph", "subgraph", "node ", "edge ")):
            continue
        prefix, raw_attrs, _ = _split_dot_attr_statement(stripped)
        node_id = _clean_dot_id(prefix)
        if not node_id:
            continue
        attrs = _parse_dot_attrs(raw_attrs)
        attrs_by_node[node_id] = attrs
        labels[node_id] = _clean_dot_label(attrs.get("label") or attrs.get("xlabel") or attrs.get("tooltip") or node_id) or node_id
    for statement in statements:
        stripped = statement.strip().rstrip(";")
        if not stripped or ("->" not in stripped and "--" not in stripped):
            continue
        endpoints = _extract_edge_endpoints(stripped)
        if len(endpoints) < 2:
            continue
        raw_attrs = _split_dot_attr_statement(stripped)[1] if "[" in stripped and "]" in stripped else ""
        attrs = _parse_dot_attrs(raw_attrs)
        color = _colour(attrs.get("color"), "#666666")
        label = _clean_dot_label(attrs.get("label") or attrs.get("xlabel") or "") or _make_edge_fallback_label(endpoints[0], endpoints[-1], labels)
        direction = _normalise_dot_direction(attrs.get("dir"), directed="->" in stripped)
        edges.append(DotEdge(endpoints[0], endpoints[-1], color, label, direction))
    return DotMetadata(labels, attrs_by_node, _dedupe_legend_items([(e.color, e.label) for e in edges if e.label]), edges)


def _normalise_dot_direction(value: Any, directed: bool = True) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"forward", "back", "both", "none"}:
        return raw
    return "forward" if directed else "none"


def _norm_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _edge_title_to_source_target(title: str) -> Tuple[str, str]:
    text = _cleanup_visible_text(title or "")
    parts = [_clean_dot_id(p) for p in re.split(r"\s*->\s*|\s*--\s*", text) if _clean_dot_id(p)]
    return (parts[0], parts[-1]) if len(parts) >= 2 else ("", "")


def _find_dot_edge(metadata: DotMetadata, source: str, target: str, title: str = "") -> Optional[DotEdge]:
    s_key = _norm_identity(source)
    t_key = _norm_identity(target)
    if s_key and t_key:
        for edge in metadata.edges:
            if _norm_identity(edge.source) == s_key and _norm_identity(edge.target) == t_key:
                return edge
        for edge in metadata.edges:
            if _norm_identity(edge.source) == t_key and _norm_identity(edge.target) == s_key:
                return edge
    title_key = _norm_identity(title)
    for edge in metadata.edges:
        if _norm_identity(f"{edge.source}->{edge.target}") in title_key or _norm_identity(f"{edge.source}--{edge.target}") in title_key:
            return edge
    return None


def _fallback_nodes_from_dot_metadata(metadata: DotMetadata) -> List[SvgNode]:
    nodes: List[SvgNode] = []
    node_ids = list(metadata.labels.keys())
    if not node_ids:
        for edge in metadata.edges:
            if edge.source not in node_ids:
                node_ids.append(edge.source)
            if edge.target not in node_ids:
                node_ids.append(edge.target)
    x = 80.0
    y = 130.0
    gap = 190.0
    for idx, node_id in enumerate(node_ids):
        label = metadata.labels.get(node_id, node_id)
        attrs = metadata.attrs.get(node_id, {})
        style = _node_visual_style(label, node_id, attrs)
        cx = x + idx * gap
        bbox = (cx - 62.0, y - 42.0, cx + 62.0, y + 42.0)
        icon_path = _resolve_icon_path(label)
        nodes.append(SvgNode(node_id, label, bbox, style["fill"], style["border"], 1.0, "", icon_path, _icon_abbrev(label), style.get("font", "#000000"), attrs))
    return nodes


def _fallback_edges_from_dot_metadata(metadata: DotMetadata, nodes: List[SvgNode]) -> List[SvgEdge]:
    by_id = {_norm_identity(n.node_id): n for n in nodes}
    by_label = {_norm_identity(n.label): n for n in nodes}
    edges: List[SvgEdge] = []
    for edge in metadata.edges:
        source = by_id.get(_norm_identity(edge.source)) or by_label.get(_norm_identity(edge.source))
        target = by_id.get(_norm_identity(edge.target)) or by_label.get(_norm_identity(edge.target))
        if not source or not target:
            continue
        sx = (source.bbox[0] + source.bbox[2]) / 2.0
        sy = (source.bbox[1] + source.bbox[3]) / 2.0
        tx = (target.bbox[0] + target.bbox[2]) / 2.0
        ty = (target.bbox[1] + target.bbox[3]) / 2.0
        edges.append(SvgEdge(f"{edge.source}->{edge.target}", [(sx, sy), (tx, ty)], edge.color, 1.25, edge.source, edge.target, edge.direction, edge.label))
    return edges


def _merge_svg_routes_with_dot_edges(metadata: DotMetadata, nodes: List[SvgNode], svg_edges: List[SvgEdge]) -> List[SvgEdge]:
    if not metadata.edges:
        return svg_edges
    fallback = _fallback_edges_from_dot_metadata(metadata, nodes)
    if not svg_edges:
        return fallback
    merged: List[SvgEdge] = []
    used_svg: set[int] = set()
    for dot_edge in metadata.edges:
        chosen: Optional[SvgEdge] = None
        for idx, svg_edge in enumerate(svg_edges):
            if idx in used_svg:
                continue
            candidate = _find_dot_edge(metadata, svg_edge.source, svg_edge.target, svg_edge.edge_id)
            if candidate and _norm_identity(candidate.source) == _norm_identity(dot_edge.source) and _norm_identity(candidate.target) == _norm_identity(dot_edge.target):
                chosen = svg_edge
                used_svg.add(idx)
                break
        if chosen:
            merged.append(SvgEdge(chosen.edge_id, chosen.points, dot_edge.color or chosen.color, chosen.width, dot_edge.source, dot_edge.target, dot_edge.direction, dot_edge.label))
        else:
            for fb in fallback:
                if _norm_identity(fb.source) == _norm_identity(dot_edge.source) and _norm_identity(fb.target) == _norm_identity(dot_edge.target):
                    merged.append(fb)
                    break
    return merged or fallback or svg_edges


def _filter_clusters(clusters: List[SvgCluster], nodes: List[SvgNode], opts: Optional[VisioExportOptions] = None) -> List[SvgCluster]:
    if not clusters or not nodes:
        return []
    opts = opts or VisioExportOptions()
    result = []
    seen = set()
    for c in sorted(clusters, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]), reverse=True):
        x1, y1, x2, y2 = c.bbox
        contained = [n for n in nodes if x1 <= (n.bbox[0] + n.bbox[2]) / 2 <= x2 and y1 <= (n.bbox[1] + n.bbox[3]) / 2 <= y2]
        if not contained:
            continue
        min_x = min(n.bbox[0] for n in contained)
        min_y = min(n.bbox[1] for n in contained)
        max_x = max(n.bbox[2] for n in contained)
        max_y = max(n.bbox[3] for n in contained)
        required_top = max(float(opts.zone_header_px), float(opts.zone_padding_px) * 1.70)
        if min_y - y1 < required_top:
            y1 = min_y - required_top
        x1 = min(x1, min_x - opts.zone_padding_px)
        x2 = max(x2, max_x + opts.zone_padding_px)
        y2 = max(y2, max_y + opts.zone_padding_px)
        key = (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), c.label.lower())
        if key not in seen:
            seen.add(key)
            result.append(SvgCluster(c.cluster_id, c.label, (x1, y1, x2, y2), c.fill, c.stroke, c.font_color))
    return result


def _auto_zones(nodes: List[SvgNode], opts: VisioExportOptions) -> List[SvgCluster]:
    if not nodes:
        return []
    groups = _group_nodes_by_zone_metadata(nodes, opts)
    if groups:
        return _zones_from_grouped_nodes(groups, opts)
    return [_zone_from_nodes("auto_zone_1", opts.default_auto_zone_label, nodes, opts.cluster_fill, opts.cluster_stroke, opts.cluster_text, opts)]


def _group_nodes_by_zone_metadata(nodes: List[SvgNode], opts: VisioExportOptions) -> List[Tuple[str, List[SvgNode]]]:
    grouped: Dict[str, List[SvgNode]] = {}
    order: List[str] = []
    for node in nodes:
        attrs = node.attrs or {}
        zone = ""
        for name in opts.zone_attribute_names:
            if attrs.get(name):
                zone = _cleanup_visible_text(attrs[name])
                break
        if zone:
            key = zone.lower()
            grouped.setdefault(key, [])
            if key not in order:
                order.append(key)
            grouped[key].append(node)
    return [(k, grouped[k]) for k in order if grouped.get(k)]


def _zones_from_grouped_nodes(groups: List[Tuple[str, List[SvgNode]]], opts: VisioExportOptions) -> List[SvgCluster]:
    labels = list(opts.auto_zone_labels or [])
    zones = []
    for idx, (key, nodes) in enumerate(groups[: opts.max_auto_zones]):
        label = labels[idx] if idx < len(labels) and labels[idx] else _humanize_zone_label(key, idx + 1)
        zones.append(_zone_from_nodes(f"auto_zone_{idx + 1}", label, nodes, _zone_fill(idx), opts.cluster_stroke, opts.cluster_text, opts))
    return zones


def _zone_from_nodes(cluster_id: str, label: str, nodes: List[SvgNode], fill: str, stroke: str, text: str, opts: VisioExportOptions) -> SvgCluster:
    pad = float(opts.zone_padding_px)
    header = max(float(opts.zone_header_px), pad * 1.70)
    return SvgCluster(cluster_id, label, (min(n.bbox[0] for n in nodes) - pad, min(n.bbox[1] for n in nodes) - header, max(n.bbox[2] for n in nodes) + pad, max(n.bbox[3] for n in nodes) + pad), fill, stroke, text)


def _boxes_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], margin: float = 0.0) -> bool:
    return not (a[2] + margin <= b[0] or b[2] + margin <= a[0] or a[3] + margin <= b[1] or b[3] + margin <= a[1])

# ----------------------------- parsing, icon, svg helpers -----------------------------

def _humanize_zone_label(value: str, index: int) -> str:
    text = _cleanup_visible_text(value).replace("_", " ").replace("-", " ").strip()
    return f"Zone {index}" if not text or re.fullmatch(r"zone\s*\d+", text, flags=re.I) else re.sub(r"\s+", " ", text).title()


def _zone_fill(index: int) -> str:
    return ["#EFF6FF", "#EEF6FF", "#F8FBFF", "#F6FAF3", "#FFF8E8", "#F8F1FF"][index % 6]


def _split_dot_statements(text: str) -> List[str]:
    statements, current = [], []
    in_quote = in_html = False
    bracket_depth = 0
    escape = False
    for char in text:
        current.append(char)
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"' and not in_html:
            in_quote = not in_quote
            continue
        if char == "<" and not in_quote:
            in_html = True
        elif char == ">" and in_html and not in_quote:
            in_html = False
        elif char == "[" and not in_quote and not in_html:
            bracket_depth += 1
        elif char == "]" and not in_quote and not in_html:
            bracket_depth = max(0, bracket_depth - 1)
        elif char == ";" and not in_quote and not in_html and bracket_depth == 0:
            st = "".join(current).strip()
            current = []
            if st:
                statements.append(st)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _split_dot_attr_statement(statement: str) -> Tuple[str, str, str]:
    start = statement.find("[")
    end = statement.rfind("]")
    return (statement, "", "") if start < 0 or end < start else (statement[:start].strip(), statement[start + 1 : end].strip(), statement[end + 1 :].strip())


def _parse_dot_attrs(raw: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    pattern = re.compile(r'([A-Za-z_][A-Za-z0-9_:-]*)\s*=\s*("(?:\\.|[^"])*"|<.*?>|[^,\]]+)', flags=re.S)
    for key, value in pattern.findall(raw or ""):
        attrs[key.strip().lower()] = _clean_dot_label(value)
    return attrs


def _extract_edge_endpoints(statement: str) -> List[str]:
    no_attrs = re.sub(r"\[.*?\]", "", statement, flags=re.S).strip().rstrip(";")
    return [_clean_dot_id(part) for part in re.split(r"->|--", no_attrs) if _clean_dot_id(part)]


def _clean_dot_id(value: str) -> str:
    return _cleanup_visible_text(str(value or "").strip().rstrip(";").strip().strip('"').strip("'"))


def _clean_dot_label(value: str) -> str:
    return _cleanup_visible_text(str(value or "").strip().strip('"').strip("'"))


def _cleanup_visible_text(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\\n", " ").replace("\\l", " ").replace("\\r", " ")
    text = re.sub(r"\\+", " ", text)
    text = re.sub(r"<\s*br\s*/?\s*>", " ", text, flags=re.I)
    text = re.sub(r"</?\s*b\s*>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", text).strip()


def _make_edge_fallback_label(source: str, target: str, labels: Dict[str, str]) -> str:
    src = labels.get(source, source).strip()
    dst = labels.get(target, target).strip()
    return f"{src} to {dst}" if src and dst else ""


def _resolve_icon_path(label: str) -> str:
    if resolve_icon_from_node_label is None:
        return ""
    raw = _cleanup_visible_text(label)
    candidates = [raw, _normalise_label_for_lookup(raw), raw.replace("_", " "), raw.replace("_", "")]
    if clean_label is not None:
        try:
            cleaned = clean_label(raw)  # type: ignore[misc]
            candidates.extend([cleaned, _normalise_label_for_lookup(cleaned)])
        except Exception:
            pass
    seen = set()
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if not candidate or candidate.lower() in seen:
            continue
        seen.add(candidate.lower())
        try:
            icon = resolve_icon_from_node_label(candidate, PROJECT_ROOT)  # type: ignore[misc]
            if icon and normalize_icon_for_graphviz is not None:
                try:
                    icon = normalize_icon_for_graphviz(str(icon))  # type: ignore[misc]
                except Exception:
                    pass
            resolved = _resolve_raster_path(str(icon), Path.cwd()) if icon else None
            if resolved:
                return str(resolved)
        except Exception:
            logger.exception("Icon resolution failed for %r", candidate)
    return ""


def _extract_icon_from_candidates(candidates: List[str], base_dir: Path) -> str:
    for candidate in candidates:
        path = _resolve_raster_path(candidate, base_dir)
        if path:
            return str(path)
    return ""


def _resolve_raster_path(href: Any, base_dir: Path) -> Optional[Path]:
    if not href:
        return None
    raw = str(href).strip().strip('"').strip("'")
    if raw.startswith("data:image/") or raw.startswith(("http://", "https://")):
        return None
    path = Path(unquote(raw))
    roots = [path] if path.is_absolute() else [base_dir / path, Path.cwd() / path, PROJECT_ROOT / path]
    for candidate in roots:
        try:
            candidate = candidate.resolve()
        except Exception:
            pass
        if candidate.exists() and candidate.is_file() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}:
            return candidate
    return None


def _icon_compact_cells(path: str, grid: int = 14, max_cells: int = 56) -> List[Tuple[int, int, str]]:
    resolved = _resolve_raster_path(path, Path.cwd())
    if Image is None or not resolved:
        return []
    try:
        with Image.open(resolved).convert("RGBA") as img:  # type: ignore[union-attr]
            grid = max(10, min(18, int(grid or 14)))
            max_cells = max(24, min(80, int(max_cells or 56)))
            if ImageEnhance is not None:
                img = ImageEnhance.Color(img).enhance(2.25)
                img = ImageEnhance.Contrast(img).enhance(2.10)
                img = ImageEnhance.Brightness(img).enhance(0.86)
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)
            img.thumbnail((grid, grid), Image.LANCZOS)
            canvas = Image.new("RGBA", (grid, grid), (255, 255, 255, 0))
            canvas.paste(img, ((grid - img.width) // 2, (grid - img.height) // 2), img)
            pix = canvas.load()
            candidates = []
            for y in range(grid):
                for x in range(grid):
                    r, g, b, a = pix[x, y]
                    if a < 42 or (r > 248 and g > 248 and b > 248):
                        continue
                    alpha = a / 255.0
                    r = int(r * alpha + 255 * (1 - alpha))
                    g = int(g * alpha + 255 * (1 - alpha))
                    b = int(b * alpha + 255 * (1 - alpha))
                    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                    if lum > 195:
                        factor = 195.0 / max(lum, 1.0)
                        r, g, b = int(r * factor), int(g * factor), int(b * factor)
                        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                    score = (255 - lum) + (max(r, g, b) - min(r, g, b)) + a * 0.35
                    r = max(0, min(255, int(round(r / 10.0) * 10)))
                    g = max(0, min(255, int(round(g / 10.0) * 10)))
                    b = max(0, min(255, int(round(b / 10.0) * 10)))
                    candidates.append((score, x, y, f"#{r:02X}{g:02X}{b:02X}"))
            if len(candidates) > max_cells:
                candidates = sorted(candidates, key=lambda i: i[0], reverse=True)[:max_cells]
            return [(x, y, color) for _score, x, y, color in sorted(candidates, key=lambda i: (i[2], i[1]))]
    except Exception:
        logger.exception("Failed to create compact icon cells: %s", path)
        return []


def _node_visual_style(label: str, seed: str, attrs: Dict[str, str]) -> Dict[str, str]:
    if get_style_for_label is not None:
        try:
            style = get_style_for_label(_normalise_label_for_lookup(label or seed))  # type: ignore[misc]
            fill = _colour(attrs.get("fillcolor") or style.get("fill"), _pastel_color(seed))
            border = _colour(attrs.get("color") or style.get("border"), _darker_border(fill))
            font = _colour(style.get("font"), "#000000")
            return {"fill": fill, "border": border, "font": font}
        except Exception:
            pass
    fill = _colour(attrs.get("fillcolor"), _pastel_color(seed))
    border = _colour(attrs.get("color"), _darker_border(fill))
    return {"fill": fill, "border": border, "font": "#000000"}


def _normalise_label_for_lookup(label: str) -> str:
    text = _cleanup_visible_text(label).replace("_", " ").replace("-", " ")
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _icon_abbrev(label: str) -> str:
    words = [w for w in re.split(r"\s+", _normalise_label_for_lookup(label)) if w]
    return "•" if not words else (words[0][:2].upper() if len(words) == 1 else "".join(w[0] for w in words[:2]).upper())


def _wrap_label(label: str) -> str:
    try:
        text = clean_label(label) if clean_label is not None else _cleanup_visible_text(label).replace("_", " ")  # type: ignore[misc]
    except Exception:
        text = _cleanup_visible_text(label).replace("_", " ")
    words = text.split()
    if len(words) <= 2:
        return text
    mid = (len(words) + 1) // 2 if len(words) <= 4 else max(2, len(words) // 2)
    return " ".join(words[:mid]) + "\n" + " ".join(words[mid:])


def _run_graphviz(dot: Path, out: Path, fmt: str, engine: str) -> None:
    result = subprocess.run([engine, f"-T{fmt}", str(dot), "-o", str(out)], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Graphviz failed for {fmt}:\n{result.stderr or result.stdout}")


def _iter_svg(root: ET.Element) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
    def walk(elem: ET.Element, parent_matrix: Matrix, parent_classes: List[str]) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
        matrix = _matmul(parent_matrix, _transform(elem.get("transform")))
        classes = _class_tokens(elem.get("class"))
        yield elem, matrix, parent_classes
        for child in list(elem):
            yield from walk(child, matrix, parent_classes + classes)
    yield from walk(root, IDENTITY, [])


def _class_tokens(value: Optional[str]) -> List[str]:
    return [t.strip().lower() for t in re.split(r"\s+", value or "") if t.strip()]


def _transform(raw: Optional[str]) -> Matrix:
    if not raw:
        return IDENTITY
    matrix = IDENTITY
    for name, args in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", raw):
        nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", args)]
        local = IDENTITY
        if name == "matrix" and len(nums) >= 6:
            local = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
        elif name == "translate":
            local = (1, 0, 0, 1, nums[0] if nums else 0, nums[1] if len(nums) > 1 else 0)
        elif name == "scale":
            sx = nums[0] if nums else 1
            sy = nums[1] if len(nums) > 1 else sx
            local = (sx, 0, 0, sy, 0, 0)
        elif name == "rotate" and nums:
            angle = math.radians(nums[0])
            c, s = math.cos(angle), math.sin(angle)
            local = (c, s, -s, c, 0, 0)
        matrix = _matmul(matrix, local)
    return matrix


def _matmul(a: Matrix, b: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = a
    a2, b2, c2, d2, e2, f2 = b
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def _apply(matrix: Matrix, x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, e, f = matrix
    return a * x + c * y + e, b * x + d * y + f


def _style(elem: ET.Element) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for part in (elem.get("style") or "").split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            result[key.strip().lower()] = value.strip()
    for key, value in elem.attrib.items():
        if key.lower() in {"fill", "stroke", "stroke-width", "font-size", "font-weight", "text-anchor"}:
            result[key.lower()] = value
    return result


def _title(group: ET.Element) -> str:
    title = group.find(_svg("title"))
    return _read_text(title) if title is not None else ""


def _read_text(elem: Optional[ET.Element]) -> str:
    if elem is None:
        return ""
    parts = []
    if elem.text:
        parts.append(elem.text)
    for child in list(elem):
        t = _read_text(child)
        if t:
            parts.append(t)
        if child.tail:
            parts.append(child.tail)
    return html.unescape(" ".join(p.strip() for p in parts if p and p.strip())).strip()


def _svg_href(elem: ET.Element) -> str:
    return (elem.get("href") or elem.get(_xlink("href")) or elem.get("xlink:href") or "").strip()


def _rect_points(elem: ET.Element, matrix: Matrix) -> List[Tuple[float, float]]:
    x, y = _num(elem.get("x"), 0), _num(elem.get("y"), 0)
    w, h = _num(elem.get("width"), 0), _num(elem.get("height"), 0)
    return [] if w <= 0 or h <= 0 else [_apply(matrix, x, y), _apply(matrix, x + w, y), _apply(matrix, x + w, y + h), _apply(matrix, x, y + h)]


def _points(raw: str) -> List[Tuple[float, float]]:
    nums = [float(x) for x in re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw or "")]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def _path_points(raw: str) -> List[Tuple[float, float]]:
    return _points(raw)


def _simplify_route(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    if len(points) <= 2:
        return points
    start, end = points[0], points[-1]
    mid = points[len(points) // 2]
    return [start, mid, end] if abs(mid[0] - start[0]) > 8 and abs(mid[1] - end[1]) > 8 else [start, end]


def _bbox(points: Sequence[Tuple[float, float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(re.sub(r"(px|pt|in|cm|mm|%)$", "", str(value).strip(), flags=re.I))
    except Exception:
        return default


def _colour(value: Any, default: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return default
    if raw.lower() in {"none", "transparent"}:
        return "#FFFFFF"
    named = {"black": "#000000", "white": "#FFFFFF", "red": "#FF0000", "green": "#008000", "blue": "#0000FF", "gray": "#808080", "grey": "#808080", "orange": "#FFA500", "purple": "#800080", "yellow": "#FFFF00", "cyan": "#00FFFF", "magenta": "#FF00FF", "brown": "#A52A2A", "pink": "#FFC0CB", "teal": "#008080"}
    if raw.lower() in named:
        return named[raw.lower()]
    if raw.startswith("#"):
        return ("#" + "".join(ch * 2 for ch in raw[1:]).upper()) if len(raw) == 4 else raw[:7].upper()
    rgb = re.match(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", raw, flags=re.I)
    if rgb:
        return "#%02X%02X%02X" % tuple(max(0, min(255, int(v))) for v in rgb.groups())
    return default


def _rgb(color: str) -> Tuple[int, int, int]:
    color = _colour(color, "#000000")
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def _pt(value: float) -> float:
    return max(0.01, float(value) / PT_PER_INCH)


def _is_near_black(color: str) -> bool:
    try:
        r, g, b = _rgb(color)
        return r < 24 and g < 24 and b < 24
    except Exception:
        return False


def _pastel_color(seed: Any) -> str:
    palette = ["#E8F0FE", "#E6F4EA", "#FEF7E0", "#FCE8E6", "#F3E8FD", "#E0F2F1", "#FFF3E0", "#E8EAED", "#E3F2FD", "#F1F8E9"]
    return palette[sum(ord(ch) for ch in str(seed or "node")) % len(palette)]


def _darker_border(fill: str) -> str:
    try:
        r, g, b = _rgb(fill)
        return f"#{int(r * 0.72):02X}{int(g * 0.72):02X}{int(b * 0.72):02X}"
    except Exception:
        return "#666666"


def _lighten(color: str, factor: float = 0.35) -> str:
    try:
        r, g, b = _rgb(color)
        return f"#{int(r + (255 - r) * factor):02X}{int(g + (255 - g) * factor):02X}{int(b + (255 - b) * factor):02X}"
    except Exception:
        return "#FFFFFF"


def _dedupe_legend_items(items: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    result = []
    seen = set()
    for color, label in items or []:
        safe_color = _colour(color, "#666666")
        safe_label = _cleanup_visible_text(label)
        key = (safe_color.lower(), safe_label.lower())
        if safe_label and key not in seen:
            seen.add(key)
            result.append((safe_color, safe_label))
    return result


def _boxes_overlap(a: Tuple[float, float, float, float], b: Tuple[float, float, float, float], margin: float = 0.0) -> bool:
    return not (a[2] + margin <= b[0] or b[2] + margin <= a[0] or a[3] + margin <= b[1] or b[3] + margin <= a[1])


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_. -]+", "_", str(value or "Shape"))[:120] or "Shape"


def _local(tag: str) -> str:
    return str(tag).split("}", 1)[-1].lower()


def _xml(root: ET.Element) -> str:
    return "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + ET.tostring(root, encoding="unicode")


def _xml_plain(root: ET.Element) -> str:
    return "<?xml version='1.0' encoding='UTF-8' standalone='yes'?>\n" + ET.tostring(root, encoding="unicode")


__all__ = ["VisioExportOptions", "export_vsdx_from_dot", "export_vsdx_from_svg"]
