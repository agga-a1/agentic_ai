# from __future__ import annotations

# """
# editable_diagram_exporter.py

# Central exporter for editable diagram artefacts.

# Generated per diagram:
#     - <base_name>.dot
#     - <base_name>_editable.svg
#     - <base_name>.png
#     - <base_name>.drawio optional
#     - <base_name>.vsdx optional, if visio_vsdx_exporter.py is present

# Design goals:
#     - Keep Graphviz rendering as the single source of truth.
#     - Keep optional draw.io and VSDX generation decoupled from core asset export.
#     - Never hardcode services, sections, or diagram names.
#     - Keep failures in optional formats non-blocking for DOCX/PDF generation.
# """

# import base64
# import html
# import logging
# import mimetypes
# import re
# import shutil
# import subprocess
# import xml.etree.ElementTree as ET
# from dataclasses import asdict, dataclass
# from pathlib import Path
# from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
# from urllib.parse import unquote
# from xml.sax.saxutils import escape as xml_escape

# from .graphviz_renderer import normalize_to_graphviz_dot, render_graphviz_to_assets

# try:  # VSDX support is optional and deliberately isolated.
#     from .visio_vsdx_exporter import VisioExportOptions, export_vsdx_from_svg
#     _VISIO_EXPORT_AVAILABLE = True
# except Exception:  # pragma: no cover - optional Visio support
#     VisioExportOptions = Any  # type: ignore
#     export_vsdx_from_svg = None  # type: ignore
#     _VISIO_EXPORT_AVAILABLE = False

# logger = logging.getLogger(__name__)

# Matrix = Tuple[float, float, float, float, float, float]
# IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# # =============================================================================
# # Public data models
# # =============================================================================
# @dataclass(frozen=True)
# class DiagramAssets:
#     base_name: str
#     output_dir: Path
#     dot_path: Path
#     svg_path: Path
#     png_path: Path
#     drawio_path: Optional[Path] = None
#     vsdx_path: Optional[Path] = None
#     source: str = "graphviz_renderer"

#     def as_dict(self) -> Dict[str, str]:
#         result: Dict[str, str] = {}
#         for key, value in asdict(self).items():
#             if isinstance(value, Path):
#                 result[key] = str(value)
#             elif value is None:
#                 result[key] = ""
#             else:
#                 result[key] = str(value)
#         return result


# @dataclass
# class DrawioExportOptions:
#     enabled: bool = True
#     page_name: str = "Diagram"
#     page_width: int = 1600
#     page_height: int = 900
#     grid: int = 1
#     grid_size: int = 10
#     preserve_text_as_labels: bool = True
#     include_paths_as_edges: bool = True
#     include_svg_images: bool = True
#     embed_local_images_as_data_uri: bool = True
#     curve_sample_steps: int = 12


# @dataclass(frozen=True)
# class _CoreAssetPaths:
#     safe_base: str
#     output_dir: Path
#     dot_path: Path
#     svg_path: Path
#     png_path: Path
#     drawio_path: Optional[Path]
#     vsdx_path: Optional[Path]


# # =============================================================================
# # Public API
# # =============================================================================
# def export_editable_diagram(
#     diagram_text: str,
#     output_dir: Path | str,
#     base_name: str,
#     *,
#     generate_drawio: bool = True,
#     generate_vsdx: bool = False,
#     graphviz_engine: str = "dot",
#     drawio_options: Optional[DrawioExportOptions] = None,
#     visio_options: Optional[Any] = None,
#     overwrite: bool = True,
# ) -> DiagramAssets:
#     """
#     Export DOT, editable SVG, PNG preview, optional draw.io and optional VSDX.

#     Core assets (.dot/.svg/.png) are mandatory. Optional artefacts (.drawio/.vsdx)
#     are attempted after core assets exist and are intentionally non-blocking.
#     """
#     paths = _build_core_asset_paths(
#         output_dir=output_dir,
#         base_name=base_name,
#         generate_drawio=generate_drawio,
#         generate_vsdx=generate_vsdx,
#     )

#     if _can_reuse_existing_core_assets(paths, overwrite=overwrite):
#         _export_optional_assets(
#             paths=paths,
#             generate_drawio=generate_drawio,
#             generate_vsdx=generate_vsdx,
#             drawio_options=drawio_options,
#             visio_options=visio_options,
#         )
#         return _diagram_assets_from_paths(paths)

#     normalized_dot = _normalise_input_to_dot(diagram_text, base_name)

#     _render_core_assets(
#         normalized_dot=normalized_dot,
#         paths=paths,
#         graphviz_engine=graphviz_engine,
#     )

#     _ensure_core_assets_exist(
#         paths=paths,
#         graphviz_engine=graphviz_engine,
#     )

#     _export_optional_assets(
#         paths=paths,
#         generate_drawio=generate_drawio,
#         generate_vsdx=generate_vsdx,
#         drawio_options=drawio_options,
#         visio_options=visio_options,
#     )

#     return _diagram_assets_from_paths(paths)


# def export_many_editable_diagrams(
#     diagrams: Iterable[Dict[str, Any]],
#     output_dir: Path | str,
#     *,
#     generate_drawio: bool = True,
#     generate_vsdx: bool = False,
#     graphviz_engine: str = "dot",
#     overwrite: bool = True,
# ) -> List[DiagramAssets]:
#     """Export multiple diagram specs using unique safe file names."""
#     used: Dict[str, int] = {}
#     results: List[DiagramAssets] = []

#     for idx, spec in enumerate(diagrams, start=1):
#         diagram_text = str(spec.get("diagram_text") or spec.get("text") or "")
#         raw_name = (
#             spec.get("base_name")
#             or spec.get("section_key")
#             or spec.get("title")
#             or f"diagram_{idx:02d}"
#         )
#         base_name = _unique_name(_safe_filename(str(raw_name)), used)
#         results.append(
#             export_editable_diagram(
#                 diagram_text=diagram_text,
#                 output_dir=output_dir,
#                 base_name=base_name,
#                 generate_drawio=generate_drawio,
#                 generate_vsdx=generate_vsdx,
#                 graphviz_engine=graphviz_engine,
#                 overwrite=overwrite,
#             )
#         )

#     return results


# # =============================================================================
# # Core export orchestration
# # =============================================================================
# def _build_core_asset_paths(
#     output_dir: Path | str,
#     base_name: str,
#     generate_drawio: bool,
#     generate_vsdx: bool,
# ) -> _CoreAssetPaths:
#     out_dir = Path(output_dir)
#     out_dir.mkdir(parents=True, exist_ok=True)

#     safe_base = _safe_filename(base_name)
#     return _CoreAssetPaths(
#         safe_base=safe_base,
#         output_dir=out_dir,
#         dot_path=out_dir / f"{safe_base}.dot",
#         svg_path=out_dir / f"{safe_base}_editable.svg",
#         png_path=out_dir / f"{safe_base}.png",
#         drawio_path=out_dir / f"{safe_base}.drawio" if generate_drawio else None,
#         vsdx_path=out_dir / f"{safe_base}.vsdx" if generate_vsdx else None,
#     )


# def _can_reuse_existing_core_assets(paths: _CoreAssetPaths, overwrite: bool) -> bool:
#     return (
#         not overwrite
#         and paths.dot_path.exists()
#         and paths.svg_path.exists()
#         and paths.png_path.exists()
#     )


# def _normalise_input_to_dot(diagram_text: str, base_name: str) -> str:
#     normalized_dot = normalize_to_graphviz_dot(diagram_text)
#     if not normalized_dot:
#         raise ValueError(f"Diagram text could not be normalized to DOT for {base_name!r}")
#     return _clean_dot(normalized_dot)


# def _render_core_assets(
#     normalized_dot: str,
#     paths: _CoreAssetPaths,
#     graphviz_engine: str,
# ) -> None:
#     """
#     Render mandatory DOT/SVG/PNG assets using the styled Graphviz renderer first.
#     Direct Graphviz rendering is used only as a fallback.
#     """
#     rendered = render_graphviz_to_assets(
#         normalized_dot,
#         output_dir=paths.output_dir,
#         base_name=paths.safe_base,
#     )

#     if rendered:
#         _copy_or_write_asset(
#             source_path=_asset_path(rendered, "dot_path"),
#             target_path=paths.dot_path,
#             fallback_text=normalized_dot,
#             is_text=True,
#         )
#         _copy_or_write_asset(
#             source_path=(
#                 _asset_path(rendered, "editable_svg_path")
#                 or _asset_path(rendered, "svg_path")
#                 or _asset_path(rendered, "svg")
#             ),
#             target_path=paths.svg_path,
#         )
#         _copy_or_write_asset(
#             source_path=(
#                 _asset_path(rendered, "png_path")
#                 or _asset_path(rendered, "preview_path")
#                 or _asset_path(rendered, "png")
#             ),
#             target_path=paths.png_path,
#         )
#         return

#     logger.warning(
#         "Styled Graphviz asset render returned no assets for %s. Trying direct Graphviz fallback.",
#         paths.safe_base,
#     )
#     _render_direct_graphviz(
#         dot_text=normalized_dot,
#         dot_path=paths.dot_path,
#         svg_path=paths.svg_path,
#         png_path=paths.png_path,
#         graphviz_engine=graphviz_engine,
#     )


# def _ensure_core_assets_exist(paths: _CoreAssetPaths, graphviz_engine: str) -> None:
#     if not paths.dot_path.exists():
#         raise RuntimeError(f"DOT source was not generated: {paths.dot_path}")

#     if not paths.svg_path.exists() or not paths.png_path.exists():
#         logger.warning(
#             "Missing SVG/PNG after styled export for %s. Trying direct Graphviz fallback.",
#             paths.safe_base,
#         )
#         _render_direct_graphviz(
#             dot_text=paths.dot_path.read_text(encoding="utf-8"),
#             dot_path=paths.dot_path,
#             svg_path=paths.svg_path,
#             png_path=paths.png_path,
#             graphviz_engine=graphviz_engine,
#             preserve_existing_dot=True,
#         )

#     if not paths.svg_path.exists():
#         raise RuntimeError(f"Editable SVG was not generated: {paths.svg_path}")
#     if not paths.png_path.exists():
#         raise RuntimeError(f"PNG preview was not generated: {paths.png_path}")


# def _export_optional_assets(
#     paths: _CoreAssetPaths,
#     generate_drawio: bool,
#     generate_vsdx: bool,
#     drawio_options: Optional[DrawioExportOptions],
#     visio_options: Optional[Any],
# ) -> None:
#     if generate_drawio and paths.drawio_path:
#         _safe_export_drawio(paths.svg_path, paths.drawio_path, drawio_options, paths.safe_base)

#     if generate_vsdx and paths.vsdx_path:
#         _safe_export_vsdx(paths.svg_path, paths.vsdx_path, visio_options, paths.safe_base)


# def _diagram_assets_from_paths(paths: _CoreAssetPaths) -> DiagramAssets:
#     return DiagramAssets(
#         base_name=paths.safe_base,
#         output_dir=paths.output_dir,
#         dot_path=paths.dot_path,
#         svg_path=paths.svg_path,
#         png_path=paths.png_path,
#         drawio_path=paths.drawio_path if paths.drawio_path and paths.drawio_path.exists() else None,
#         vsdx_path=paths.vsdx_path if paths.vsdx_path and paths.vsdx_path.exists() else None,
#     )


# # =============================================================================
# # Graphviz/direct asset helpers
# # =============================================================================
# def _render_direct_graphviz(
#     *,
#     dot_text: str,
#     dot_path: Path,
#     svg_path: Path,
#     png_path: Path,
#     graphviz_engine: str,
#     preserve_existing_dot: bool = False,
# ) -> None:
#     engine = shutil.which(graphviz_engine)
#     if not engine:
#         raise RuntimeError(f"Graphviz command not found on PATH: {graphviz_engine}")

#     if not preserve_existing_dot:
#         dot_path.write_text(_clean_dot(dot_text), encoding="utf-8")

#     _run_command([engine, "-Tsvg", str(dot_path), "-o", str(svg_path)])
#     _run_command([engine, "-Tpng", str(dot_path), "-o", str(png_path)])


# def _run_command(args: List[str]) -> None:
#     result = subprocess.run(args, capture_output=True, text=True, check=False)
#     if result.returncode != 0:
#         raise RuntimeError(
#             "Command failed: "
#             + " ".join(args)
#             + "\nSTDOUT:\n"
#             + (result.stdout or "")
#             + "\nSTDERR:\n"
#             + (result.stderr or "")
#         )


# def _asset_path(assets: Any, key: str) -> Optional[Path]:
#     if not assets:
#         return None
#     value = assets.get(key) if isinstance(assets, dict) else getattr(assets, key, None)
#     return Path(value) if value else None


# def _copy_or_write_asset(
#     *,
#     source_path: Optional[Path],
#     target_path: Path,
#     fallback_text: Optional[str] = None,
#     is_text: bool = False,
# ) -> None:
#     if source_path and source_path.exists():
#         if source_path.resolve() == target_path.resolve():
#             return
#         if is_text:
#             target_path.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")
#         else:
#             target_path.write_bytes(source_path.read_bytes())
#         return

#     if fallback_text is not None:
#         target_path.write_text(fallback_text, encoding="utf-8")


# def _safe_export_drawio(
#     svg_path: Path,
#     drawio_path: Path,
#     options: Optional[DrawioExportOptions],
#     base_name: str,
# ) -> None:
#     try:
#         opts = options or DrawioExportOptions(page_name=_human_title(base_name))
#         if not opts.enabled:
#             return
#         export_drawio_from_svg(svg_path, drawio_path, options=opts)
#     except Exception:
#         logger.exception("draw.io generation failed for %s", svg_path)
#         _delete_partial_file(drawio_path)


# def _safe_export_vsdx(
#     svg_path: Path,
#     vsdx_path: Path,
#     options: Optional[Any],
#     base_name: str,
# ) -> None:
#     if not _VISIO_EXPORT_AVAILABLE or export_vsdx_from_svg is None:
#         logger.warning(
#             "VSDX generation skipped for %s because visio_vsdx_exporter.py is not available.",
#             svg_path,
#         )
#         return

#     try:
#         if options is None:
#             options = VisioExportOptions(page_name=_human_title(base_name))  # type: ignore
#         export_vsdx_from_svg(svg_path, vsdx_path, options=options)  # type: ignore
#     except Exception:
#         logger.exception("VSDX generation failed for %s", svg_path)
#         _delete_partial_file(vsdx_path)


# def _delete_partial_file(path: Path) -> None:
#     try:
#         if path.exists():
#             path.unlink()
#     except Exception:
#         logger.debug("Failed removing partial file: %s", path, exc_info=True)


# # =============================================================================
# # SVG -> draw.io conversion public function
# # =============================================================================
# def export_drawio_from_svg(
#     svg_path: Path | str,
#     drawio_path: Path | str,
#     *,
#     options: Optional[DrawioExportOptions] = None,
# ) -> Path:
#     """Convert styled SVG into an editable diagrams.net/draw.io file."""
#     opts = options or DrawioExportOptions()
#     svg = Path(svg_path)
#     out = Path(drawio_path)
#     out.parent.mkdir(parents=True, exist_ok=True)

#     root = ET.parse(str(svg)).getroot()
#     transform = _svg_transform(root, opts)
#     cells = _svg_to_drawio_cells(root, transform, opts, svg.parent)
#     out.write_text(_build_mxfile(cells, opts), encoding="utf-8")
#     return out


# # =============================================================================
# # SVG -> draw.io conversion internals
# # =============================================================================
# @dataclass
# class _Transform:
#     min_x: float
#     min_y: float
#     scale: float


# def _svg_transform(root: ET.Element, opts: DrawioExportOptions) -> _Transform:
#     min_x, min_y, width, height = _svg_viewbox(root)
#     width = max(width, 1.0)
#     height = max(height, 1.0)
#     scale = min(opts.page_width / width, opts.page_height / height)
#     return _Transform(min_x=min_x, min_y=min_y, scale=scale)


# def _to_drawio_xy(x: float, y: float, transform: _Transform) -> Tuple[float, float]:
#     return (x - transform.min_x) * transform.scale, (y - transform.min_y) * transform.scale


# def _svg_to_drawio_cells(
#     root: ET.Element,
#     transform: _Transform,
#     opts: DrawioExportOptions,
#     svg_dir: Path,
# ) -> List[str]:
#     cells: List[str] = []
#     next_id = 2

#     for elem, matrix in _iter_svg_elements_with_matrix(root):
#         tag = _local_name(elem.tag)
#         style = _parse_style(elem)
#         cell = ""

#         if tag == "image" and opts.include_svg_images:
#             cell, next_id = _image_cell(elem, matrix, transform, next_id, opts, svg_dir)
#         elif tag == "rect":
#             cell, next_id = _rect_cell(elem, style, matrix, transform, next_id)
#         elif tag in {"ellipse", "circle"}:
#             cell, next_id = _ellipse_cell(elem, style, matrix, transform, next_id)
#         elif tag == "text" and opts.preserve_text_as_labels:
#             cell, next_id = _text_cell(elem, style, matrix, transform, next_id)
#         elif tag in {"path", "polyline", "polygon"} and opts.include_paths_as_edges:
#             cell, next_id = _path_cell(elem, style, matrix, transform, next_id, opts)

#         if cell:
#             cells.append(cell)

#     return cells


# def _image_cell(
#     elem: ET.Element,
#     matrix: Matrix,
#     transform: _Transform,
#     cell_id: int,
#     opts: DrawioExportOptions,
#     svg_dir: Path,
# ) -> Tuple[str, int]:
#     href = _svg_href(elem)
#     if not href:
#         return "", cell_id

#     x = _num(elem.get("x"), 0.0)
#     y = _num(elem.get("y"), 0.0)
#     width = _num(elem.get("width"), 0.0)
#     height = _num(elem.get("height"), 0.0)
#     if width <= 0 or height <= 0:
#         return "", cell_id

#     x1, y1 = _apply_matrix(matrix, x, y)
#     x2, y2 = _apply_matrix(matrix, x + width, y + height)
#     dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
#     dw = abs(x2 - x1) * transform.scale
#     dh = abs(y2 - y1) * transform.scale

#     image_uri = _normalise_image_href(href, svg_dir, opts)
#     if not image_uri:
#         return "", cell_id

#     mx_style = f"shape=image;html=1;imageAspect=0;aspect=fixed;image={xml_escape(image_uri)};"
#     return _vertex_xml(cell_id, "", mx_style, dx, dy, dw, dh), cell_id + 1


# def _rect_cell(
#     elem: ET.Element,
#     style: Dict[str, str],
#     matrix: Matrix,
#     transform: _Transform,
#     cell_id: int,
# ) -> Tuple[str, int]:
#     x = _num(elem.get("x"), 0.0)
#     y = _num(elem.get("y"), 0.0)
#     width = _num(elem.get("width"), 0.0)
#     height = _num(elem.get("height"), 0.0)
#     if width <= 0 or height <= 0:
#         return "", cell_id

#     x1, y1 = _apply_matrix(matrix, x, y)
#     x2, y2 = _apply_matrix(matrix, x + width, y + height)
#     dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
#     dw = abs(x2 - x1) * transform.scale
#     dh = abs(y2 - y1) * transform.scale
#     rounded = _num(elem.get("rx"), 0.0) > 0 or _num(elem.get("ry"), 0.0) > 0

#     mx_style = _drawio_shape_style(
#         shape="rectangle",
#         fill=style.get("fill") or elem.get("fill") or "#ffffff",
#         stroke=style.get("stroke") or elem.get("stroke") or "#000000",
#         stroke_width=style.get("stroke-width") or elem.get("stroke-width") or "1",
#         rounded=rounded,
#     )
#     return _vertex_xml(cell_id, "", mx_style, dx, dy, dw, dh), cell_id + 1


# def _ellipse_cell(
#     elem: ET.Element,
#     style: Dict[str, str],
#     matrix: Matrix,
#     transform: _Transform,
#     cell_id: int,
# ) -> Tuple[str, int]:
#     tag = _local_name(elem.tag)
#     cx = _num(elem.get("cx"), 0.0)
#     cy = _num(elem.get("cy"), 0.0)
#     if tag == "circle":
#         rx = ry = _num(elem.get("r"), 0.0)
#     else:
#         rx = _num(elem.get("rx"), 0.0)
#         ry = _num(elem.get("ry"), 0.0)
#     if rx <= 0 or ry <= 0:
#         return "", cell_id

#     x1, y1 = _apply_matrix(matrix, cx - rx, cy - ry)
#     x2, y2 = _apply_matrix(matrix, cx + rx, cy + ry)
#     dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
#     width = abs(x2 - x1) * transform.scale
#     height = abs(y2 - y1) * transform.scale
#     mx_style = _drawio_shape_style(
#         shape="ellipse",
#         fill=style.get("fill") or elem.get("fill") or "#ffffff",
#         stroke=style.get("stroke") or elem.get("stroke") or "#000000",
#         stroke_width=style.get("stroke-width") or elem.get("stroke-width") or "1",
#     )
#     return _vertex_xml(cell_id, "", mx_style, dx, dy, width, height), cell_id + 1


# def _text_cell(
#     elem: ET.Element,
#     style: Dict[str, str],
#     matrix: Matrix,
#     transform: _Transform,
#     cell_id: int,
# ) -> Tuple[str, int]:
#     text = _collect_text(elem)
#     if not text:
#         return "", cell_id

#     x = _num(elem.get("x"), 0.0)
#     y = _num(elem.get("y"), 0.0)
#     x, y = _apply_matrix(matrix, x, y)
#     dx, dy = _to_drawio_xy(x, y, transform)
#     font_size = _num(style.get("font-size") or elem.get("font-size"), 12.0) * transform.scale
#     font_size = max(6.0, min(32.0, font_size))
#     width = max(50.0, len(text) * font_size * 0.55)
#     height = max(18.0, font_size * 1.45)

#     anchor = style.get("text-anchor") or elem.get("text-anchor") or "start"
#     if anchor == "middle":
#         dx -= width / 2
#     elif anchor == "end":
#         dx -= width
#     dy -= height * 0.75

#     color = _normalize_color(style.get("fill") or elem.get("fill") or "#000000", "#000000")
#     weight = str(style.get("font-weight") or elem.get("font-weight") or "").lower()
#     font_style = "1" if weight in {"bold", "700", "800"} else "0"
#     mx_style = (
#         "text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;"
#         f"fontColor={color};fontSize={int(font_size)};fontStyle={font_style};"
#     )
#     return _vertex_xml(cell_id, text, mx_style, dx, dy, width, height), cell_id + 1


# def _path_cell(
#     elem: ET.Element,
#     style: Dict[str, str],
#     matrix: Matrix,
#     transform: _Transform,
#     cell_id: int,
#     opts: DrawioExportOptions,
# ) -> Tuple[str, int]:
#     tag = _local_name(elem.tag)
#     if tag == "path":
#         points = _path_points(elem.get("d", ""), opts.curve_sample_steps)
#     else:
#         points = _points_attr(elem.get("points", ""))
#     if len(points) < 2:
#         return "", cell_id

#     points = [_apply_matrix(matrix, x, y) for x, y in points]
#     points = [_to_drawio_xy(x, y, transform) for x, y in points]
#     stroke = _normalize_color(style.get("stroke") or elem.get("stroke") or "#666666", "#666666")
#     width = max(1.0, _num(style.get("stroke-width") or elem.get("stroke-width"), 1.0) * transform.scale)
#     dashed = "1" if (style.get("stroke-dasharray") or elem.get("stroke-dasharray")) else "0"
#     mx_style = (
#         "edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
#         f"strokeColor={stroke};strokeWidth={_fmt(width)};dashed={dashed};endArrow=block;endFill=1;"
#     )
#     return _edge_xml(cell_id, mx_style, points), cell_id + 1


# # =============================================================================
# # draw.io XML builders
# # =============================================================================
# def _build_mxfile(cells: List[str], opts: DrawioExportOptions) -> str:
#     body = "\n".join(cells)
#     lines = [
#         '<mxfile host="app.diagrams.net" agent="AIA-HLD" version="24.0.0" type="device">',
#         f'  <diagram id="diagram-1" name="{xml_escape(opts.page_name)}">',
#         f'    <mxGraphModel dx="1422" dy="794" grid="{opts.grid}" gridSize="{opts.grid_size}" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{opts.page_width}" pageHeight="{opts.page_height}" math="0" shadow="0">',
#         '      <root>',
#         '        <mxCell id="0" />',
#         '        <mxCell id="1" parent="0" />',
#         body,
#         '      </root>',
#         '    </mxGraphModel>',
#         '  </diagram>',
#         '</mxfile>',
#     ]
#     return "\n".join(line for line in lines if line is not None)


# def _vertex_xml(
#     cell_id: int,
#     value: str,
#     style: str,
#     x: float,
#     y: float,
#     width: float,
#     height: float,
# ) -> str:
#     return (
#         f'        <mxCell id="{cell_id}" value="{xml_escape(value)}" style="{xml_escape(style)}" vertex="1" parent="1">\n'
#         f'          <mxGeometry x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(width)}" height="{_fmt(height)}" as="geometry" />\n'
#         f'        </mxCell>'
#     )


# def _edge_xml(cell_id: int, style: str, points: List[Tuple[float, float]]) -> str:
#     source = points[0]
#     target = points[-1]
#     waypoints = points[1:-1]
#     lines = [
#         f'        <mxCell id="{cell_id}" value="" style="{xml_escape(style)}" edge="1" parent="1">',
#         '          <mxGeometry relative="1" as="geometry">',
#         f'            <mxPoint x="{_fmt(source[0])}" y="{_fmt(source[1])}" as="sourcePoint" />',
#         f'            <mxPoint x="{_fmt(target[0])}" y="{_fmt(target[1])}" as="targetPoint" />',
#     ]
#     if waypoints:
#         lines.append('            <Array as="points">')
#         for x, y in waypoints:
#             lines.append(f'              <mxPoint x="{_fmt(x)}" y="{_fmt(y)}" />')
#         lines.append('            </Array>')
#     lines.extend(['          </mxGeometry>', '        </mxCell>'])
#     return "\n".join(lines)


# def _drawio_shape_style(
#     *,
#     shape: str,
#     fill: Optional[str],
#     stroke: Optional[str],
#     stroke_width: Optional[str],
#     rounded: bool = False,
# ) -> str:
#     return (
#         f"shape={shape};html=1;whiteSpace=wrap;rounded={'1' if rounded else '0'};"
#         f"fillColor={_normalize_color(fill, '#ffffff')};"
#         f"strokeColor={_normalize_color(stroke, '#000000')};"
#         f"strokeWidth={_fmt(_num(stroke_width, 1.0))};"
#     )


# # =============================================================================
# # SVG traversal, transforms and parsing helpers
# # =============================================================================
# def _iter_svg_elements_with_matrix(root: ET.Element) -> Iterator[Tuple[ET.Element, Matrix]]:
#     supported = {"rect", "ellipse", "circle", "text", "path", "polyline", "polygon", "image"}

#     def walk(elem: ET.Element, parent_matrix: Matrix) -> Iterator[Tuple[ET.Element, Matrix]]:
#         matrix = _matrix_multiply(parent_matrix, _parse_transform(elem.get("transform")))
#         if _local_name(elem.tag) in supported:
#             yield elem, matrix
#         for child in list(elem):
#             yield from walk(child, matrix)

#     yield from walk(root, IDENTITY)


# def _parse_transform(raw: Optional[str]) -> Matrix:
#     if not raw:
#         return IDENTITY
#     matrix = IDENTITY
#     for name, args in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", raw):
#         nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", args)]
#         local = IDENTITY
#         if name == "matrix" and len(nums) >= 6:
#             local = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
#         elif name == "translate":
#             tx = nums[0] if nums else 0.0
#             ty = nums[1] if len(nums) > 1 else 0.0
#             local = (1.0, 0.0, 0.0, 1.0, tx, ty)
#         elif name == "scale":
#             sx = nums[0] if nums else 1.0
#             sy = nums[1] if len(nums) > 1 else sx
#             local = (sx, 0.0, 0.0, sy, 0.0, 0.0)
#         elif name == "rotate":
#             angle = nums[0] if nums else 0.0
#             if abs(angle) > 0.001:
#                 logger.debug("Ignoring non-zero SVG rotate transform: %s", raw)
#             local = IDENTITY
#         matrix = _matrix_multiply(matrix, local)
#     return matrix


# def _matrix_multiply(m1: Matrix, m2: Matrix) -> Matrix:
#     a1, b1, c1, d1, e1, f1 = m1
#     a2, b2, c2, d2, e2, f2 = m2
#     return (
#         a1 * a2 + c1 * b2,
#         b1 * a2 + d1 * b2,
#         a1 * c2 + c1 * d2,
#         b1 * c2 + d1 * d2,
#         a1 * e2 + c1 * f2 + e1,
#         b1 * e2 + d1 * f2 + f1,
#     )


# def _apply_matrix(m: Matrix, x: float, y: float) -> Tuple[float, float]:
#     a, b, c, d, e, f = m
#     return a * x + c * y + e, b * x + d * y + f


# def _svg_href(elem: ET.Element) -> str:
#     return (
#         elem.get("href")
#         or elem.get("{http://www.w3.org/1999/xlink}href")
#         or elem.get("xlink:href")
#         or ""
#     ).strip()


# def _normalise_image_href(href: str, svg_dir: Path, opts: DrawioExportOptions) -> str:
#     if not href:
#         return ""
#     if href.startswith("data:"):
#         return href.replace(";", "%3B", 1)
#     if href.startswith(("http://", "https://")):
#         return href

#     img_path = Path(unquote(href))
#     if not img_path.is_absolute():
#         img_path = svg_dir / img_path

#     if opts.embed_local_images_as_data_uri and img_path.exists():
#         mime = mimetypes.guess_type(str(img_path))[0] or "image/png"
#         data = base64.b64encode(img_path.read_bytes()).decode("ascii")
#         return f"data:{mime}%3Bbase64,{data}"

#     return img_path.resolve().as_uri() if img_path.exists() else href


# def _local_name(tag: str) -> str:
#     return str(tag).split("}", 1)[-1].lower()


# def _parse_style(elem: ET.Element) -> Dict[str, str]:
#     style: Dict[str, str] = {}
#     raw = elem.get("style") or ""
#     for part in raw.split(";"):
#         if ":" in part:
#             key, value = part.split(":", 1)
#             style[key.strip().lower()] = value.strip()
#     for key, value in elem.attrib.items():
#         low = key.lower()
#         if low in {
#             "fill",
#             "stroke",
#             "stroke-width",
#             "stroke-dasharray",
#             "font-size",
#             "font-weight",
#             "text-anchor",
#         }:
#             style[low] = value
#     return style


# def _svg_viewbox(root: ET.Element) -> Tuple[float, float, float, float]:
#     viewbox = root.get("viewBox") or root.get("viewbox")
#     if viewbox:
#         nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", viewbox)]
#         if len(nums) >= 4:
#             return nums[0], nums[1], nums[2], nums[3]
#     return 0.0, 0.0, _num(root.get("width"), 1000.0), _num(root.get("height"), 800.0)


# def _collect_text(elem: ET.Element) -> str:
#     parts: List[str] = []
#     if elem.text:
#         parts.append(elem.text)
#     for child in elem.iter():
#         if child is elem:
#             continue
#         if child.text:
#             parts.append(child.text)
#         if child.tail:
#             parts.append(child.tail)
#     return html.unescape(" ".join(part.strip() for part in parts if part and part.strip())).strip()


# def _points_attr(raw: str) -> List[Tuple[float, float]]:
#     nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", raw or "")]
#     return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


# def _path_points(d: str, steps: int = 12) -> List[Tuple[float, float]]:
#     tokens = re.findall(r"[MmLlHhVvCcQqZz]|-?\d+(?:\.\d+)?", d or "")
#     points: List[Tuple[float, float]] = []
#     i = 0
#     cmd = ""
#     current = (0.0, 0.0)
#     start = (0.0, 0.0)

#     while i < len(tokens):
#         if re.match(r"[A-Za-z]", tokens[i]):
#             cmd = tokens[i]
#             i += 1
#         if not cmd:
#             break

#         absolute = cmd.isupper()
#         c = cmd.upper()

#         try:
#             if c == "M":
#                 x, y = float(tokens[i]), float(tokens[i + 1])
#                 i += 2
#                 current = (x, y) if absolute else (current[0] + x, current[1] + y)
#                 start = current
#                 points.append(current)
#                 cmd = "L" if absolute else "l"
#             elif c == "L":
#                 x, y = float(tokens[i]), float(tokens[i + 1])
#                 i += 2
#                 current = (x, y) if absolute else (current[0] + x, current[1] + y)
#                 points.append(current)
#             elif c == "H":
#                 x = float(tokens[i])
#                 i += 1
#                 current = (x, current[1]) if absolute else (current[0] + x, current[1])
#                 points.append(current)
#             elif c == "V":
#                 y = float(tokens[i])
#                 i += 1
#                 current = (current[0], y) if absolute else (current[0], current[1] + y)
#                 points.append(current)
#             elif c == "C":
#                 x1, y1, x2, y2, x3, y3 = map(float, tokens[i : i + 6])
#                 i += 6
#                 p1 = (x1, y1) if absolute else (current[0] + x1, current[1] + y1)
#                 p2 = (x2, y2) if absolute else (current[0] + x2, current[1] + y2)
#                 p3 = (x3, y3) if absolute else (current[0] + x3, current[1] + y3)
#                 points.extend(_sample_cubic(current, p1, p2, p3, steps))
#                 current = p3
#             elif c == "Q":
#                 x1, y1, x2, y2 = map(float, tokens[i : i + 4])
#                 i += 4
#                 p1 = (x1, y1) if absolute else (current[0] + x1, current[1] + y1)
#                 p2 = (x2, y2) if absolute else (current[0] + x2, current[1] + y2)
#                 points.extend(_sample_quadratic(current, p1, p2, steps))
#                 current = p2
#             elif c == "Z":
#                 current = start
#                 points.append(current)
#             else:
#                 break
#         except Exception:
#             break

#     return _dedupe_points(points)


# def _sample_cubic(
#     p0: Tuple[float, float],
#     p1: Tuple[float, float],
#     p2: Tuple[float, float],
#     p3: Tuple[float, float],
#     steps: int,
# ) -> List[Tuple[float, float]]:
#     result: List[Tuple[float, float]] = []
#     for idx in range(1, steps + 1):
#         t = idx / steps
#         x = (
#             (1 - t) ** 3 * p0[0]
#             + 3 * (1 - t) ** 2 * t * p1[0]
#             + 3 * (1 - t) * t**2 * p2[0]
#             + t**3 * p3[0]
#         )
#         y = (
#             (1 - t) ** 3 * p0[1]
#             + 3 * (1 - t) ** 2 * t * p1[1]
#             + 3 * (1 - t) * t**2 * p2[1]
#             + t**3 * p3[1]
#         )
#         result.append((x, y))
#     return result


# def _sample_quadratic(
#     p0: Tuple[float, float],
#     p1: Tuple[float, float],
#     p2: Tuple[float, float],
#     steps: int,
# ) -> List[Tuple[float, float]]:
#     result: List[Tuple[float, float]] = []
#     for idx in range(1, steps + 1):
#         t = idx / steps
#         x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t**2 * p2[0]
#         y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t**2 * p2[1]
#         result.append((x, y))
#     return result


# def _dedupe_points(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
#     cleaned: List[Tuple[float, float]] = []
#     for point in points:
#         if not cleaned or abs(point[0] - cleaned[-1][0]) > 0.5 or abs(point[1] - cleaned[-1][1]) > 0.5:
#             cleaned.append(point)
#     return cleaned


# # =============================================================================
# # Generic helpers
# # =============================================================================
# def _clean_dot(dot: str) -> str:
#     return html.unescape(dot).replace("-&gt;", "->").replace("→", "->")


# def _safe_filename(value: str) -> str:
#     safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "diagram")).strip("._")
#     return safe or "diagram"


# def _unique_name(base: str, used: Dict[str, int]) -> str:
#     count = used.get(base, 0) + 1
#     used[base] = count
#     return base if count == 1 else f"{base}_{count:02d}"


# def _human_title(value: str) -> str:
#     return re.sub(r"[_-]+", " ", str(value or "Diagram")).strip().title() or "Diagram"


# def _num(value: Any, default: float = 0.0) -> float:
#     if value is None:
#         return default
#     raw = re.sub(r"[a-zA-Z%]+$", "", str(value).strip())
#     try:
#         return float(raw)
#     except Exception:
#         return default


# def _normalize_color(value: Any, default: str) -> str:
#     raw = str(value or "").strip()
#     if not raw or raw.lower() in {"none", "transparent"}:
#         return default

#     if raw.startswith("#") and len(raw) in {4, 7}:
#         if len(raw) == 4:
#             return "#" + "".join(ch * 2 for ch in raw[1:])
#         return raw

#     named_colors = {
#         "black": "#000000",
#         "white": "#ffffff",
#         "red": "#ff0000",
#         "green": "#008000",
#         "blue": "#0000ff",
#         "gray": "#808080",
#         "grey": "#808080",
#         "orange": "#ffa500",
#         "purple": "#800080",
#         "yellow": "#ffff00",
#         "cyan": "#00ffff",
#         "magenta": "#ff00ff",
#         "brown": "#a52a2a",
#         "pink": "#ffc0cb",
#     }
#     return named_colors.get(raw.lower(), default)


# def _fmt(value: float) -> str:
#     if abs(value - round(value)) < 0.001:
#         return str(int(round(value)))
#     return f"{value:.2f}".rstrip("0").rstrip(".")



# from __future__ import annotations

# """
# editable_diagram_exporter.py

# Central exporter for editable diagram artefacts.

# Generated per diagram:
#     - <base_name>.dot
#     - <base_name>_editable.svg
#     - <base_name>.png
#     - <base_name>.drawio optional
#     - <base_name>.vsdx optional, if visio_vsdx_exporter.py is present

# Design goals:
#     - Keep Graphviz rendering as the single source of truth for core assets.
#     - Keep optional draw.io and VSDX generation decoupled from core asset export.
#     - Never hardcode services, sections, project names, node labels or diagram names.
#     - Keep failures in optional formats non-blocking for DOCX/PDF generation.
#     - Repair imperfect DOT generically before every Graphviz execution.
#     - Reuse graphviz_renderer normalization so fallback does not reintroduce unwanted arrows.
#     - Prevent blank draw.io files by falling back to full-SVG embedding when native parsing creates no cells.
#     - Fix escaped Graphviz HTML-like labels before Graphviz execution.
#     - Generate valid draw.io XML by escaping XML attributes including quotes.
# """

# import base64
# import html
# import logging
# import mimetypes
# import re
# import shutil
# import subprocess
# import xml.etree.ElementTree as ET
# from dataclasses import asdict, dataclass
# from pathlib import Path
# from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
# from urllib.parse import unquote
# from xml.sax.saxutils import escape as xml_escape

# from .graphviz_renderer import normalize_dot_for_graphviz, normalize_to_graphviz_dot, render_graphviz_to_assets

# try:
#     from .graphviz_renderer import _sanitize_graphviz_html_like_labels as _renderer_sanitize_graphviz_html_like_labels
# except Exception:  # pragma: no cover
#     _renderer_sanitize_graphviz_html_like_labels = None  # type: ignore

# try:
#     from .visio_vsdx_exporter import VisioExportOptions, export_vsdx_from_dot
#     _VISIO_EXPORT_AVAILABLE = True
# except Exception:  # pragma: no cover
#     VisioExportOptions = Any  # type: ignore
#     export_vsdx_from_dot = None  # type: ignore
#     _VISIO_EXPORT_AVAILABLE = False

# logger = logging.getLogger(__name__)

# Matrix = Tuple[float, float, float, float, float, float]
# IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


# @dataclass(frozen=True)
# class DiagramAssets:
#     base_name: str
#     output_dir: Path
#     dot_path: Path
#     svg_path: Path
#     png_path: Path
#     drawio_path: Optional[Path] = None
#     vsdx_path: Optional[Path] = None
#     source: str = "graphviz_renderer"

#     def as_dict(self) -> Dict[str, str]:
#         result: Dict[str, str] = {}
#         for key, value in asdict(self).items():
#             if isinstance(value, Path):
#                 result[key] = str(value)
#             elif value is None:
#                 result[key] = ""
#             else:
#                 result[key] = str(value)
#         return result


# @dataclass
# class DrawioExportOptions:
#     enabled: bool = True
#     page_name: str = "Diagram"
#     page_width: int = 1600
#     page_height: int = 900
#     grid: int = 1
#     grid_size: int = 10
#     preserve_text_as_labels: bool = True
#     include_paths_as_edges: bool = True
#     include_svg_images: bool = True
#     embed_local_images_as_data_uri: bool = True
#     curve_sample_steps: int = 12
#     include_full_svg_fallback: bool = True
#     full_svg_fallback_only_when_no_cells: bool = True


# @dataclass(frozen=True)
# class _CoreAssetPaths:
#     safe_base: str
#     output_dir: Path
#     dot_path: Path
#     svg_path: Path
#     png_path: Path
#     drawio_path: Optional[Path]
#     vsdx_path: Optional[Path]


# # =============================================================================
# # Sanitization helpers
# # =============================================================================
# def _xml_attr(value: object) -> str:
#     """Escape text safely for XML attribute values, including quotes."""
#     return xml_escape(str(value or ""), {'"': "&quot;", "'": "&apos;"})


# def _escape_raw_ampersands_for_graphviz_html(value: str) -> str:
#     return re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#x[0-9A-Fa-f]+;)", "&amp;", str(value or ""))


# def _local_sanitize_graphviz_html_like_labels(dot_text: str) -> str:
#     if not dot_text:
#         return dot_text
#     text = str(dot_text)
#     for _ in range(3):
#         new_text = html.unescape(text)
#         if new_text == text:
#             break
#         text = new_text
#     text = (text.replace("-&amp;amp;amp;gt;", "->")
#                 .replace("-&amp;amp;gt;", "->")
#                 .replace("-&amp;gt;", "->")
#                 .replace("-&gt;", "->")
#                 .replace("→", "->"))
#     text = re.sub(r"\bsubgraph\s+cluster_(?:cluster_)+", "subgraph cluster_", text)
#     text = re.sub(r'(subgraph\s+cluster_[A-Za-z0-9_]+\s*\{\s*)label="cluster_[^"]+";\s*(label=)', r"\1\2", text, flags=re.I)

#     def decode_body(body: str) -> str:
#         body = str(body or "").replace("&lt;", "<").replace("&gt;", ">")
#         body = re.sub(r"<\s*b\s*>", "<B>", body, flags=re.I)
#         body = re.sub(r"</\s*b\s*>", "</B>", body, flags=re.I)
#         body = re.sub(r"<\s*br\s*/?\s*>", "<BR/>", body, flags=re.I)
#         return _escape_raw_ampersands_for_graphviz_html(body)

#     text = re.sub(r"label\s*=\s*(&lt;.*?&gt;)", lambda m: f"label={decode_body(m.group(1))}", text, flags=re.S)
#     text = re.sub(r"label\s*=\s*(<<.*?>>)", lambda m: f"label={decode_body(m.group(1))}", text, flags=re.S)
#     return text


# def _sanitize_graphviz_html_like_labels(dot_text: str) -> str:
#     if _renderer_sanitize_graphviz_html_like_labels is not None:
#         try:
#             return _renderer_sanitize_graphviz_html_like_labels(dot_text)  # type: ignore[misc]
#         except Exception:
#             logger.debug("graphviz_renderer sanitizer failed; using local fallback", exc_info=True)
#     return _local_sanitize_graphviz_html_like_labels(dot_text)


# # =============================================================================
# # Public API
# # =============================================================================
# def export_editable_diagram(
#     diagram_text: str,
#     output_dir: Path | str,
#     base_name: str,
#     *,
#     generate_drawio: bool = True,
#     generate_vsdx: bool = False,
#     graphviz_engine: str = "dot",
#     drawio_options: Optional[DrawioExportOptions] = None,
#     visio_options: Optional[Any] = None,
#     overwrite: bool = True,
# ) -> DiagramAssets:
#     paths = _build_core_asset_paths(output_dir, base_name, generate_drawio, generate_vsdx)

#     if _can_reuse_existing_core_assets(paths, overwrite=overwrite):
#         _repair_existing_dot_if_present(paths.dot_path)
#         _export_optional_assets(paths, generate_drawio, generate_vsdx, drawio_options, visio_options)
#         return _diagram_assets_from_paths(paths)

#     normalized_dot = _normalise_input_to_dot(diagram_text, base_name)
#     _render_core_assets(normalized_dot=normalized_dot, paths=paths, graphviz_engine=graphviz_engine)
#     _ensure_core_assets_exist(paths=paths, graphviz_engine=graphviz_engine)
#     _export_optional_assets(paths, generate_drawio, generate_vsdx, drawio_options, visio_options)
#     return _diagram_assets_from_paths(paths)


# def export_many_editable_diagrams(
#     diagrams: Iterable[Dict[str, Any]],
#     output_dir: Path | str,
#     *,
#     generate_drawio: bool = True,
#     generate_vsdx: bool = False,
#     graphviz_engine: str = "dot",
#     overwrite: bool = True,
# ) -> List[DiagramAssets]:
#     used: Dict[str, int] = {}
#     results: List[DiagramAssets] = []
#     for idx, spec in enumerate(diagrams, start=1):
#         diagram_text = str(spec.get("diagram_text") or spec.get("text") or "")
#         raw_name = spec.get("base_name") or spec.get("section_key") or spec.get("title") or f"diagram_{idx:02d}"
#         base_name = _unique_name(_safe_filename(str(raw_name)), used)
#         results.append(export_editable_diagram(
#             diagram_text=diagram_text,
#             output_dir=output_dir,
#             base_name=base_name,
#             generate_drawio=generate_drawio,
#             generate_vsdx=generate_vsdx,
#             graphviz_engine=graphviz_engine,
#             overwrite=overwrite,
#         ))
#     return results


# # =============================================================================
# # Core export orchestration
# # =============================================================================
# def _build_core_asset_paths(output_dir: Path | str, base_name: str, generate_drawio: bool, generate_vsdx: bool) -> _CoreAssetPaths:
#     out_dir = Path(output_dir)
#     out_dir.mkdir(parents=True, exist_ok=True)
#     safe_base = _safe_filename(base_name)
#     return _CoreAssetPaths(
#         safe_base=safe_base,
#         output_dir=out_dir,
#         dot_path=out_dir / f"{safe_base}.dot",
#         svg_path=out_dir / f"{safe_base}_editable.svg",
#         png_path=out_dir / f"{safe_base}.png",
#         drawio_path=out_dir / f"{safe_base}.drawio" if generate_drawio else None,
#         vsdx_path=out_dir / f"{safe_base}.vsdx" if generate_vsdx else None,
#     )


# def _can_reuse_existing_core_assets(paths: _CoreAssetPaths, overwrite: bool) -> bool:
#     return not overwrite and paths.dot_path.exists() and paths.svg_path.exists() and paths.png_path.exists()


# def _normalise_input_to_dot(diagram_text: str, base_name: str) -> str:
#     normalized_dot = normalize_to_graphviz_dot(diagram_text)
#     if not normalized_dot:
#         raise ValueError(f"Diagram text could not be normalized to DOT for {base_name!r}")
#     return _clean_and_normalize_dot_for_export(_sanitize_graphviz_html_like_labels(normalized_dot), use_image_cards=False)


# def _render_core_assets(normalized_dot: str, paths: _CoreAssetPaths, graphviz_engine: str) -> None:
#     normalized_dot = _sanitize_graphviz_html_like_labels(normalized_dot)
#     rendered = None
#     try:
#         rendered = render_graphviz_to_assets(normalized_dot, output_dir=paths.output_dir, base_name=paths.safe_base)
#     except Exception:
#         logger.exception("Styled Graphviz asset render failed for %s. Trying direct Graphviz fallback.", paths.safe_base)

#     if rendered:
#         _copy_or_write_asset(_asset_path(rendered, "dot_path"), paths.dot_path, fallback_text=normalized_dot, is_text=True)
#         _copy_or_write_asset(_asset_path(rendered, "editable_svg_path") or _asset_path(rendered, "svg_path") or _asset_path(rendered, "svg"), paths.svg_path)
#         _copy_or_write_asset(_asset_path(rendered, "png_path") or _asset_path(rendered, "preview_path") or _asset_path(rendered, "png"), paths.png_path)
#         return

#     logger.warning("Styled Graphviz asset render returned no assets for %s. Trying direct Graphviz fallback.", paths.safe_base)
#     _render_direct_graphviz(dot_text=normalized_dot, dot_path=paths.dot_path, svg_path=paths.svg_path, png_path=paths.png_path, graphviz_engine=graphviz_engine)


# def _ensure_core_assets_exist(paths: _CoreAssetPaths, graphviz_engine: str) -> None:
#     if not paths.dot_path.exists():
#         raise RuntimeError(f"DOT source was not generated: {paths.dot_path}")
#     _repair_existing_dot_if_present(paths.dot_path)
#     if not paths.svg_path.exists() or not paths.png_path.exists():
#         logger.warning("Missing SVG/PNG after styled export for %s. Trying direct Graphviz fallback.", paths.safe_base)
#         _render_direct_graphviz(dot_text=paths.dot_path.read_text(encoding="utf-8"), dot_path=paths.dot_path, svg_path=paths.svg_path, png_path=paths.png_path, graphviz_engine=graphviz_engine, preserve_existing_dot=True)
#     if not paths.svg_path.exists():
#         raise RuntimeError(f"Editable SVG was not generated: {paths.svg_path}")
#     if not paths.png_path.exists():
#         raise RuntimeError(f"PNG preview was not generated: {paths.png_path}")


# def _export_optional_assets(paths: _CoreAssetPaths, generate_drawio: bool, generate_vsdx: bool, drawio_options: Optional[DrawioExportOptions], visio_options: Optional[Any]) -> None:
#     if generate_drawio and paths.drawio_path:
#         _safe_export_drawio(paths.svg_path, paths.drawio_path, drawio_options, paths.safe_base)
#     if generate_vsdx and paths.vsdx_path:
#         _safe_export_vsdx(paths.dot_path, paths.svg_path, paths.png_path, paths.vsdx_path, visio_options, paths.safe_base)


# def _diagram_assets_from_paths(paths: _CoreAssetPaths) -> DiagramAssets:
#     return DiagramAssets(
#         base_name=paths.safe_base,
#         output_dir=paths.output_dir,
#         dot_path=paths.dot_path,
#         svg_path=paths.svg_path,
#         png_path=paths.png_path,
#         drawio_path=paths.drawio_path if paths.drawio_path and paths.drawio_path.exists() else None,
#         vsdx_path=paths.vsdx_path if paths.vsdx_path and paths.vsdx_path.exists() else None,
#     )


# # =============================================================================
# # Graphviz/direct asset helpers
# # =============================================================================
# def _clean_and_normalize_dot_for_export(dot_text: str, *, use_image_cards: bool = False) -> str:
#     cleaned_dot = _sanitize_graphviz_html_like_labels(_clean_dot(dot_text))
#     try:
#         normalized_dot, _legend = normalize_dot_for_graphviz(cleaned_dot, use_image_cards=use_image_cards)
#         return _sanitize_graphviz_html_like_labels(normalized_dot)
#     except TypeError:
#         # Backward compatibility for older graphviz_renderer.normalize_dot_for_graphviz(dot) signature.
#         try:
#             normalized_dot, _legend = normalize_dot_for_graphviz(cleaned_dot)  # type: ignore[misc]
#             return _sanitize_graphviz_html_like_labels(normalized_dot)
#         except Exception:
#             logger.exception("Generic Graphviz normalization failed in editable diagram exporter. Continuing with repaired DOT only.")
#             return cleaned_dot
#     except Exception:
#         logger.exception("Generic Graphviz normalization failed in editable diagram exporter. Continuing with repaired DOT only.")
#         return cleaned_dot


# def _repair_existing_dot_if_present(dot_path: Path) -> None:
#     if not dot_path.exists():
#         return
#     try:
#         repaired = _clean_and_normalize_dot_for_export(dot_path.read_text(encoding="utf-8"), use_image_cards=False)
#         dot_path.write_text(_sanitize_graphviz_html_like_labels(repaired), encoding="utf-8")
#     except Exception:
#         logger.exception("Failed repairing existing DOT asset: %s", dot_path)


# def _render_direct_graphviz(*, dot_text: str, dot_path: Path, svg_path: Path, png_path: Path, graphviz_engine: str, preserve_existing_dot: bool = False) -> None:
#     engine = shutil.which(graphviz_engine)
#     if not engine:
#         raise RuntimeError(f"Graphviz command not found on PATH: {graphviz_engine}")
#     cleaned_dot = _sanitize_graphviz_html_like_labels(_clean_and_normalize_dot_for_export(dot_text, use_image_cards=False))
#     dot_path.write_text(cleaned_dot, encoding="utf-8")
#     _run_command([engine, "-Tsvg", str(dot_path), "-o", str(svg_path)])
#     _run_command([engine, "-Tpng", str(dot_path), "-o", str(png_path)])


# def _run_command(args: List[str]) -> None:
#     result = subprocess.run(args, capture_output=True, text=True, check=False)
#     if result.returncode != 0:
#         raise RuntimeError("Command failed: " + " ".join(args) + "\nSTDOUT:\n" + (result.stdout or "") + "\nSTDERR:\n" + (result.stderr or ""))


# def _asset_path(assets: Any, key: str) -> Optional[Path]:
#     if not assets:
#         return None
#     value = assets.get(key) if isinstance(assets, dict) else getattr(assets, key, None)
#     return Path(value) if value else None


# def _copy_or_write_asset(source_path: Optional[Path], target_path: Path, fallback_text: Optional[str] = None, is_text: bool = False) -> None:
#     if source_path and source_path.exists():
#         if source_path.resolve() == target_path.resolve():
#             if is_text:
#                 target_path.write_text(_clean_and_normalize_dot_for_export(target_path.read_text(encoding="utf-8"), use_image_cards=False), encoding="utf-8")
#             return
#         if is_text:
#             target_path.write_text(_clean_and_normalize_dot_for_export(source_path.read_text(encoding="utf-8"), use_image_cards=False), encoding="utf-8")
#         else:
#             target_path.write_bytes(source_path.read_bytes())
#         return
#     if fallback_text is not None:
#         target_path.write_text(_clean_and_normalize_dot_for_export(fallback_text, use_image_cards=False), encoding="utf-8")


# def _safe_export_drawio(svg_path: Path, drawio_path: Path, options: Optional[DrawioExportOptions], base_name: str) -> None:
#     try:
#         opts = options or DrawioExportOptions(page_name=_human_title(base_name))
#         if not opts.enabled:
#             return
#         export_drawio_from_svg(svg_path, drawio_path, options=opts)
#     except Exception:
#         logger.exception("draw.io generation failed for %s", svg_path)
#         _delete_partial_file(drawio_path)


# def _safe_export_vsdx(dot_path: Path, svg_path: Path, png_path: Path, vsdx_path: Path, options: Optional[Any], base_name: str) -> None:
#     if not _VISIO_EXPORT_AVAILABLE or export_vsdx_from_dot is None:
#         logger.warning("VSDX generation skipped for %s because visio_vsdx_exporter.py is not available.", dot_path)
#         return
#     try:
#         _repair_existing_dot_if_present(dot_path)
#         if options is None:
#             options = VisioExportOptions(page_name=_human_title(base_name))  # type: ignore
#         export_vsdx_from_dot(dot_path=dot_path, vsdx_path=vsdx_path, svg_path=svg_path, png_path=png_path, options=options)  # type: ignore
#     except Exception:
#         logger.exception("VSDX generation failed for %s", dot_path)
#         _delete_partial_file(vsdx_path)


# def _delete_partial_file(path: Path) -> None:
#     try:
#         if path.exists():
#             path.unlink()
#     except Exception:
#         logger.debug("Failed removing partial file: %s", path, exc_info=True)


# # =============================================================================
# # SVG -> draw.io conversion
# # =============================================================================
# def export_drawio_from_svg(svg_path: Path | str, drawio_path: Path | str, *, options: Optional[DrawioExportOptions] = None) -> Path:
#     opts = options or DrawioExportOptions()
#     svg = Path(svg_path)
#     out = Path(drawio_path)
#     out.parent.mkdir(parents=True, exist_ok=True)
#     root = ET.parse(str(svg)).getroot()
#     transform = _svg_transform(root, opts)
#     cells = _svg_to_drawio_cells(root, transform, opts, svg.parent)
#     if opts.include_full_svg_fallback and (not cells or not opts.full_svg_fallback_only_when_no_cells):
#         fallback_cell = _full_svg_image_cell(svg_path=svg, opts=opts, cell_id=max(2, len(cells) + 2))
#         if fallback_cell:
#             cells = [fallback_cell] if opts.full_svg_fallback_only_when_no_cells else cells + [fallback_cell]
#     if not cells:
#         raise RuntimeError(f"draw.io export produced no cells for SVG: {svg}")
#     out.write_text(_build_mxfile(cells, opts), encoding="utf-8")
#     _validate_drawio_file(out)
#     return out


# @dataclass
# class _Transform:
#     min_x: float
#     min_y: float
#     scale: float


# def _svg_transform(root: ET.Element, opts: DrawioExportOptions) -> _Transform:
#     min_x, min_y, width, height = _svg_viewbox(root)
#     width = max(width, 1.0)
#     height = max(height, 1.0)
#     scale = min(opts.page_width / width, opts.page_height / height)
#     return _Transform(min_x=min_x, min_y=min_y, scale=scale)


# def _to_drawio_xy(x: float, y: float, transform: _Transform) -> Tuple[float, float]:
#     return (x - transform.min_x) * transform.scale, (y - transform.min_y) * transform.scale


# def _svg_to_drawio_cells(root: ET.Element, transform: _Transform, opts: DrawioExportOptions, svg_dir: Path) -> List[str]:
#     cells: List[str] = []
#     next_id = 2
#     for elem, matrix in _iter_svg_elements_with_matrix(root):
#         tag = _local_name(elem.tag)
#         style = _parse_style(elem)
#         cell = ""
#         if tag == "image" and opts.include_svg_images:
#             cell, next_id = _image_cell(elem, matrix, transform, next_id, opts, svg_dir)
#         elif tag == "rect":
#             cell, next_id = _rect_cell(elem, style, matrix, transform, next_id)
#         elif tag in {"ellipse", "circle"}:
#             cell, next_id = _ellipse_cell(elem, style, matrix, transform, next_id)
#         elif tag == "text" and opts.preserve_text_as_labels:
#             cell, next_id = _text_cell(elem, style, matrix, transform, next_id)
#         elif tag in {"path", "polyline", "polygon"} and opts.include_paths_as_edges:
#             cell, next_id = _path_cell(elem, style, matrix, transform, next_id, opts)
#         if cell:
#             cells.append(cell)
#     return cells


# def _full_svg_image_cell(svg_path: Path, opts: DrawioExportOptions, cell_id: int = 2) -> str:
#     try:
#         data = base64.b64encode(svg_path.read_bytes()).decode("ascii")
#         image_uri = f"data:image/svg+xml%3Bbase64,{data}"
#         style = f"shape=image;html=1;imageAspect=0;aspect=fixed;image={image_uri};"
#         return _vertex_xml(cell_id=cell_id, value="", style=style, x=0, y=0, width=float(opts.page_width), height=float(opts.page_height))
#     except Exception:
#         logger.exception("Failed creating full-SVG fallback draw.io cell for %s", svg_path)
#         return ""


# def _validate_drawio_file(drawio_path: Path) -> None:
#     try:
#         root = ET.parse(str(drawio_path)).getroot()
#     except ET.ParseError as exc:
#         try:
#             lines = drawio_path.read_text(encoding="utf-8", errors="replace").splitlines()
#             line_no = int(getattr(exc, "position", (0, 0))[0] or 0)
#             start = max(0, line_no - 3)
#             end = min(len(lines), line_no + 2)
#             snippet = "\n".join(f"{idx + 1}: {lines[idx]}" for idx in range(start, end))
#             logger.error("Invalid draw.io XML around parse error %s:\n%s", exc, snippet)
#         except Exception:
#             logger.debug("Unable to log invalid draw.io XML snippet", exc_info=True)
#         raise
#     xml_text = ET.tostring(root, encoding="unicode")
#     cell_count = xml_text.count("<mxCell")
#     if cell_count <= 2:
#         raise RuntimeError(f"draw.io file appears blank or contains no diagram cells: {drawio_path}")


# def _image_cell(elem: ET.Element, matrix: Matrix, transform: _Transform, cell_id: int, opts: DrawioExportOptions, svg_dir: Path) -> Tuple[str, int]:
#     href = _svg_href(elem)
#     if not href:
#         return "", cell_id
#     x = _num(elem.get("x"), 0.0)
#     y = _num(elem.get("y"), 0.0)
#     width = _num(elem.get("width"), 0.0)
#     height = _num(elem.get("height"), 0.0)
#     if width <= 0 or height <= 0:
#         return "", cell_id
#     x1, y1 = _apply_matrix(matrix, x, y)
#     x2, y2 = _apply_matrix(matrix, x + width, y + height)
#     dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
#     dw = abs(x2 - x1) * transform.scale
#     dh = abs(y2 - y1) * transform.scale
#     image_uri = _normalise_image_href(href, svg_dir, opts)
#     if not image_uri:
#         return "", cell_id
#     mx_style = f"shape=image;html=1;imageAspect=0;aspect=fixed;image={image_uri};"
#     return _vertex_xml(cell_id, "", mx_style, dx, dy, dw, dh), cell_id + 1


# def _rect_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int) -> Tuple[str, int]:
#     x = _num(elem.get("x"), 0.0)
#     y = _num(elem.get("y"), 0.0)
#     width = _num(elem.get("width"), 0.0)
#     height = _num(elem.get("height"), 0.0)
#     if width <= 0 or height <= 0:
#         return "", cell_id
#     x1, y1 = _apply_matrix(matrix, x, y)
#     x2, y2 = _apply_matrix(matrix, x + width, y + height)
#     dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
#     dw = abs(x2 - x1) * transform.scale
#     dh = abs(y2 - y1) * transform.scale
#     rounded = _num(elem.get("rx"), 0.0) > 0 or _num(elem.get("ry"), 0.0) > 0
#     mx_style = _drawio_shape_style(shape="rectangle", fill=style.get("fill") or elem.get("fill") or "#ffffff", stroke=style.get("stroke") or elem.get("stroke") or "#000000", stroke_width=style.get("stroke-width") or elem.get("stroke-width") or "1", rounded=rounded)
#     return _vertex_xml(cell_id, "", mx_style, dx, dy, dw, dh), cell_id + 1


# def _ellipse_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int) -> Tuple[str, int]:
#     tag = _local_name(elem.tag)
#     cx = _num(elem.get("cx"), 0.0)
#     cy = _num(elem.get("cy"), 0.0)
#     rx = ry = _num(elem.get("r"), 0.0) if tag == "circle" else 0.0
#     if tag != "circle":
#         rx = _num(elem.get("rx"), 0.0)
#         ry = _num(elem.get("ry"), 0.0)
#     if rx <= 0 or ry <= 0:
#         return "", cell_id
#     x1, y1 = _apply_matrix(matrix, cx - rx, cy - ry)
#     x2, y2 = _apply_matrix(matrix, cx + rx, cy + ry)
#     dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
#     width = abs(x2 - x1) * transform.scale
#     height = abs(y2 - y1) * transform.scale
#     mx_style = _drawio_shape_style(shape="ellipse", fill=style.get("fill") or elem.get("fill") or "#ffffff", stroke=style.get("stroke") or elem.get("stroke") or "#000000", stroke_width=style.get("stroke-width") or elem.get("stroke-width") or "1")
#     return _vertex_xml(cell_id, "", mx_style, dx, dy, width, height), cell_id + 1


# def _text_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int) -> Tuple[str, int]:
#     text = _collect_text(elem)
#     if not text:
#         return "", cell_id
#     x = _num(elem.get("x"), 0.0)
#     y = _num(elem.get("y"), 0.0)
#     x, y = _apply_matrix(matrix, x, y)
#     dx, dy = _to_drawio_xy(x, y, transform)
#     font_size = max(6.0, min(32.0, _num(style.get("font-size") or elem.get("font-size"), 12.0) * transform.scale))
#     width = max(50.0, len(text) * font_size * 0.55)
#     height = max(18.0, font_size * 1.45)
#     anchor = style.get("text-anchor") or elem.get("text-anchor") or "start"
#     if anchor == "middle":
#         dx -= width / 2
#     elif anchor == "end":
#         dx -= width
#     dy -= height * 0.75
#     color = _normalize_color(style.get("fill") or elem.get("fill") or "#000000", "#000000")
#     weight = str(style.get("font-weight") or elem.get("font-weight") or "").lower()
#     font_style = "1" if weight in {"bold", "700", "800"} else "0"
#     mx_style = f"text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;fontColor={color};fontSize={int(font_size)};fontStyle={font_style};"
#     return _vertex_xml(cell_id, text, mx_style, dx, dy, width, height), cell_id + 1


# def _path_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int, opts: DrawioExportOptions) -> Tuple[str, int]:
#     tag = _local_name(elem.tag)
#     points = _path_points(elem.get("d", ""), opts.curve_sample_steps) if tag == "path" else _points_attr(elem.get("points", ""))
#     if len(points) < 2:
#         return "", cell_id
#     points = [_to_drawio_xy(*_apply_matrix(matrix, x, y), transform) for x, y in points]
#     stroke = _normalize_color(style.get("stroke") or elem.get("stroke") or "#666666", "#666666")
#     width = max(1.0, _num(style.get("stroke-width") or elem.get("stroke-width"), 1.0) * transform.scale)
#     dashed = "1" if (style.get("stroke-dasharray") or elem.get("stroke-dasharray")) else "0"
#     mx_style = f"edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;strokeColor={stroke};strokeWidth={_fmt(width)};dashed={dashed};endArrow=block;endFill=1;"
#     return _edge_xml(cell_id, mx_style, points), cell_id + 1


# # =============================================================================
# # draw.io XML builders
# # =============================================================================
# def _build_mxfile(cells: List[str], opts: DrawioExportOptions) -> str:
#     body = "\n".join(cells)
#     lines = [
#         '<mxfile host="app.diagrams.net" agent="AIA-HLD" version="24.0.0" type="device">',
#         f'  <diagram id="diagram-1" name="{_xml_attr(opts.page_name)}">',
#         f'    <mxGraphModel dx="1422" dy="794" grid="{opts.grid}" gridSize="{opts.grid_size}" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{opts.page_width}" pageHeight="{opts.page_height}" math="0" shadow="0">',
#         '      <root>',
#         '        <mxCell id="0" />',
#         '        <mxCell id="1" parent="0" />',
#         body,
#         '      </root>',
#         '    </mxGraphModel>',
#         '  </diagram>',
#         '</mxfile>',
#     ]
#     return "\n".join(line for line in lines if line is not None)


# def _vertex_xml(cell_id: int, value: str, style: str, x: float, y: float, width: float, height: float) -> str:
#     return (
#         f'        <mxCell id="{cell_id}" value="{_xml_attr(value)}" style="{_xml_attr(style)}" vertex="1" parent="1">\n'
#         f'          <mxGeometry x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(width)}" height="{_fmt(height)}" as="geometry" />\n'
#         f'        </mxCell>'
#     )


# def _edge_xml(cell_id: int, style: str, points: List[Tuple[float, float]]) -> str:
#     source = points[0]
#     target = points[-1]
#     waypoints = points[1:-1]
#     lines = [
#         f'        <mxCell id="{cell_id}" value="" style="{_xml_attr(style)}" edge="1" parent="1">',
#         '          <mxGeometry relative="1" as="geometry">',
#         f'            <mxPoint x="{_fmt(source[0])}" y="{_fmt(source[1])}" as="sourcePoint" />',
#         f'            <mxPoint x="{_fmt(target[0])}" y="{_fmt(target[1])}" as="targetPoint" />',
#     ]
#     if waypoints:
#         lines.append('            <Array as="points">')
#         for x, y in waypoints:
#             lines.append(f'              <mxPoint x="{_fmt(x)}" y="{_fmt(y)}" />')
#         lines.append('            </Array>')
#     lines.extend(['          </mxGeometry>', '        </mxCell>'])
#     return "\n".join(lines)


# def _drawio_shape_style(*, shape: str, fill: Optional[str], stroke: Optional[str], stroke_width: Optional[str], rounded: bool = False) -> str:
#     return f"shape={shape};html=1;whiteSpace=wrap;rounded={'1' if rounded else '0'};fillColor={_normalize_color(fill, '#ffffff')};strokeColor={_normalize_color(stroke, '#000000')};strokeWidth={_fmt(_num(stroke_width, 1.0))};"


# # =============================================================================
# # SVG traversal, transforms and parsing helpers
# # =============================================================================
# def _iter_svg_elements_with_matrix(root: ET.Element) -> Iterator[Tuple[ET.Element, Matrix]]:
#     supported = {"rect", "ellipse", "circle", "text", "path", "polyline", "polygon", "image"}

#     def walk(elem: ET.Element, parent_matrix: Matrix) -> Iterator[Tuple[ET.Element, Matrix]]:
#         matrix = _matrix_multiply(parent_matrix, _parse_transform(elem.get("transform")))
#         if _local_name(elem.tag) in supported:
#             yield elem, matrix
#         for child in list(elem):
#             yield from walk(child, matrix)
#     yield from walk(root, IDENTITY)


# def _parse_transform(raw: Optional[str]) -> Matrix:
#     if not raw:
#         return IDENTITY
#     matrix = IDENTITY
#     for name, args in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", raw):
#         nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", args)]
#         local = IDENTITY
#         if name == "matrix" and len(nums) >= 6:
#             local = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
#         elif name == "translate":
#             local = (1.0, 0.0, 0.0, 1.0, nums[0] if nums else 0.0, nums[1] if len(nums) > 1 else 0.0)
#         elif name == "scale":
#             sx = nums[0] if nums else 1.0
#             sy = nums[1] if len(nums) > 1 else sx
#             local = (sx, 0.0, 0.0, sy, 0.0, 0.0)
#         elif name == "rotate":
#             if nums and abs(nums[0]) > 0.001:
#                 logger.debug("Ignoring non-zero SVG rotate transform: %s", raw)
#         matrix = _matrix_multiply(matrix, local)
#     return matrix


# def _matrix_multiply(m1: Matrix, m2: Matrix) -> Matrix:
#     a1, b1, c1, d1, e1, f1 = m1
#     a2, b2, c2, d2, e2, f2 = m2
#     return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2, a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


# def _apply_matrix(m: Matrix, x: float, y: float) -> Tuple[float, float]:
#     a, b, c, d, e, f = m
#     return a * x + c * y + e, b * x + d * y + f


# def _svg_href(elem: ET.Element) -> str:
#     return (elem.get("href") or elem.get("{http://www.w3.org/1999/xlink}href") or elem.get("xlink:href") or "").strip()


# def _normalise_image_href(href: str, svg_dir: Path, opts: DrawioExportOptions) -> str:
#     if not href:
#         return ""
#     if href.startswith("data:"):
#         return href.replace(";", "%3B", 1)
#     if href.startswith(("http://", "https://")):
#         return href
#     img_path = Path(unquote(href))
#     if not img_path.is_absolute():
#         img_path = svg_dir / img_path
#     if opts.embed_local_images_as_data_uri and img_path.exists():
#         mime = mimetypes.guess_type(str(img_path))[0] or "image/png"
#         data = base64.b64encode(img_path.read_bytes()).decode("ascii")
#         return f"data:{mime}%3Bbase64,{data}"
#     return img_path.resolve().as_uri() if img_path.exists() else href


# def _local_name(tag: str) -> str:
#     return str(tag).split("}", 1)[-1].lower()


# def _parse_style(elem: ET.Element) -> Dict[str, str]:
#     style: Dict[str, str] = {}
#     raw = elem.get("style") or ""
#     for part in raw.split(";"):
#         if ":" in part:
#             key, value = part.split(":", 1)
#             style[key.strip().lower()] = value.strip()
#     for key, value in elem.attrib.items():
#         low = key.lower()
#         if low in {"fill", "stroke", "stroke-width", "stroke-dasharray", "font-size", "font-weight", "text-anchor"}:
#             style[low] = value
#     return style


# def _svg_viewbox(root: ET.Element) -> Tuple[float, float, float, float]:
#     viewbox = root.get("viewBox") or root.get("viewbox")
#     if viewbox:
#         nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", viewbox)]
#         if len(nums) >= 4:
#             return nums[0], nums[1], nums[2], nums[3]
#     return 0.0, 0.0, _num(root.get("width"), 1000.0), _num(root.get("height"), 800.0)


# def _collect_text(elem: ET.Element) -> str:
#     parts: List[str] = []
#     if elem.text:
#         parts.append(elem.text)
#     for child in elem.iter():
#         if child is elem:
#             continue
#         if child.text:
#             parts.append(child.text)
#         if child.tail:
#             parts.append(child.tail)
#     return html.unescape(" ".join(part.strip() for part in parts if part and part.strip())).strip()


# def _points_attr(raw: str) -> List[Tuple[float, float]]:
#     nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", raw or "")]
#     return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


# def _path_points(d: str, steps: int = 12) -> List[Tuple[float, float]]:
#     nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d or "")]
#     return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


# # =============================================================================
# # Generic helpers
# # =============================================================================
# def _clean_dot(dot: str) -> str:
#     raw = html.unescape(dot or "")
#     raw = (raw.replace("-&amp;amp;amp;gt;", "->")
#               .replace("-&amp;amp;gt;", "->")
#               .replace("-&amp;gt;", "->")
#               .replace("-&gt;", "->")
#               .replace("→", "->"))
#     raw = raw.replace("\r\n", "\n").replace("\r", "\n")
#     raw = re.sub(r"```(?:dot|graphviz)?", "", raw, flags=re.I).replace("```", "")
#     raw = _sanitize_graphviz_html_like_labels(raw)
#     if re.search(r"^\s*(strict\s+)?(di)?graph\b", raw, flags=re.I | re.M):
#         return raw.strip() + "\n"
#     lines = [line.strip() for line in raw.splitlines() if line.strip()]
#     if not lines:
#         return "digraph G {\n  rankdir=LR;\n}\n"
#     out = ["digraph G {", "  rankdir=LR;"]
#     for line in lines:
#         line = line.rstrip(";")
#         if not line or line in {"{", "}"}:
#             continue
#         if not line.endswith(";"):
#             line += ";"
#         out.append("  " + line)
#     out.append("}")
#     return "\n".join(out) + "\n"


# def _safe_filename(value: str) -> str:
#     safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "diagram")).strip("._")
#     return safe or "diagram"


# def _unique_name(base: str, used: Dict[str, int]) -> str:
#     count = used.get(base, 0) + 1
#     used[base] = count
#     return base if count == 1 else f"{base}_{count:02d}"


# def _human_title(value: str) -> str:
#     return re.sub(r"[_-]+", " ", str(value or "Diagram")).strip().title() or "Diagram"


# def _num(value: Any, default: float = 0.0) -> float:
#     if value is None:
#         return default
#     raw = re.sub(r"[a-zA-Z%]+$", "", str(value).strip())
#     try:
#         return float(raw)
#     except Exception:
#         return default


# def _normalize_color(value: Any, default: str) -> str:
#     raw = str(value or "").strip()
#     if not raw or raw.lower() in {"none", "transparent"}:
#         return default
#     if raw.startswith("#") and len(raw) in {4, 7}:
#         return "#" + "".join(ch * 2 for ch in raw[1:]) if len(raw) == 4 else raw
#     named = {"black": "#000000", "white": "#ffffff", "red": "#ff0000", "green": "#008000", "blue": "#0000ff", "gray": "#808080", "grey": "#808080", "orange": "#ffa500", "purple": "#800080", "yellow": "#ffff00", "cyan": "#00ffff", "magenta": "#ff00ff", "brown": "#a52a2a", "pink": "#ffc0cb"}
#     return named.get(raw.lower(), default)


# def _fmt(value: float) -> str:
#     try:
#         value = float(value)
#     except Exception:
#         value = 0.0
#     if abs(value - round(value)) < 0.001:
#         return str(int(round(value)))
#     return f"{value:.2f}".rstrip("0").rstrip(".")

from __future__ import annotations

"""
editable_diagram_exporter.py

Central exporter for editable diagram artefacts.

Generated per diagram:
    - <base_name>.dot
    - <base_name>_editable.svg
    - <base_name>.png
    - <base_name>.drawio optional
    - <base_name>.vsdx optional, if visio_vsdx_exporter.py is present
    - <base_name>_legend.json sidecar, used to keep Graphviz and VSDX legends aligned

Design goals:
    - Keep Graphviz rendering as the single source of truth for core assets.
    - Keep optional draw.io and VSDX generation decoupled from core asset export.
    - Never hardcode services, sections, project names, node labels or diagram names.
    - Keep failures in optional formats non-blocking for DOCX/PDF generation.
    - Repair imperfect DOT generically before every Graphviz execution.
    - Reuse graphviz_renderer normalization so fallback does not reintroduce unwanted arrows.
    - Prevent blank draw.io files by falling back to full-SVG embedding when native parsing creates no cells.
    - Fix escaped Graphviz HTML-like labels before Graphviz execution.
    - Generate valid draw.io XML by escaping XML attributes including quotes.
    - Generate native editable VSDX from DOT/plain layout and pass the same legend items used by Graphviz.
"""

import base64
import html
import json
import logging
import mimetypes
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple
from urllib.parse import unquote
from xml.sax.saxutils import escape as xml_escape

from .graphviz_renderer import normalize_dot_for_graphviz, normalize_to_graphviz_dot, render_graphviz_to_assets

try:
    from .graphviz_renderer import _sanitize_graphviz_html_like_labels as _renderer_sanitize_graphviz_html_like_labels
except Exception:  # pragma: no cover
    _renderer_sanitize_graphviz_html_like_labels = None  # type: ignore

try:
    from .visio_vsdx_exporter import VisioExportOptions, export_vsdx_from_dot
    _VISIO_EXPORT_AVAILABLE = True
except Exception:  # pragma: no cover
    VisioExportOptions = Any  # type: ignore
    export_vsdx_from_dot = None  # type: ignore
    _VISIO_EXPORT_AVAILABLE = False

logger = logging.getLogger(__name__)

Matrix = Tuple[float, float, float, float, float, float]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


@dataclass(frozen=True)
class DiagramAssets:
    base_name: str
    output_dir: Path
    dot_path: Path
    svg_path: Path
    png_path: Path
    drawio_path: Optional[Path] = None
    vsdx_path: Optional[Path] = None
    legend_path: Optional[Path] = None
    source: str = "graphviz_renderer"

    def as_dict(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for key, value in asdict(self).items():
            if isinstance(value, Path):
                result[key] = str(value)
            elif value is None:
                result[key] = ""
            else:
                result[key] = str(value)
        return result


@dataclass
class DrawioExportOptions:
    enabled: bool = True
    page_name: str = "Diagram"
    page_width: int = 1600
    page_height: int = 900
    grid: int = 1
    grid_size: int = 10
    preserve_text_as_labels: bool = True
    include_paths_as_edges: bool = True
    include_svg_images: bool = True
    embed_local_images_as_data_uri: bool = True
    curve_sample_steps: int = 12
    include_full_svg_fallback: bool = True
    full_svg_fallback_only_when_no_cells: bool = True


@dataclass(frozen=True)
class _CoreAssetPaths:
    safe_base: str
    output_dir: Path
    dot_path: Path
    svg_path: Path
    png_path: Path
    legend_path: Path
    drawio_path: Optional[Path]
    vsdx_path: Optional[Path]


# =============================================================================
# Sanitization helpers
# =============================================================================
def _xml_attr(value: object) -> str:
    """Escape text safely for XML attribute values, including quotes."""
    return xml_escape(str(value or ""), {'"': "&quot;", "'": "&apos;"})


def _escape_raw_ampersands_for_graphviz_html(value: str) -> str:
    return re.sub(r"&(?!amp;|lt;|gt;|quot;|apos;|#[0-9]+;|#x[0-9A-Fa-f]+;)", "&amp;", str(value or ""))


def _local_sanitize_graphviz_html_like_labels(dot_text: str) -> str:
    if not dot_text:
        return dot_text

    text = str(dot_text)
    for _ in range(3):
        new_text = html.unescape(text)
        if new_text == text:
            break
        text = new_text

    text = (
        text.replace("-&amp;amp;amp;amp;gt;", "->")
        .replace("-&amp;amp;amp;gt;", "->")
        .replace("-&amp;amp;gt;", "->")
        .replace("-&amp;gt;", "->")
        .replace("→", "->")
    )

    text = re.sub(r"\bsubgraph\s+cluster_(?:cluster_)+", "subgraph cluster_", text)
    text = re.sub(
        r'(subgraph\s+cluster_[A-Za-z0-9_]+\s*\{\s*)label="cluster_[^"]+";\s*(label=)',
        r"\1\2",
        text,
        flags=re.I,
    )

    def decode_body(body: str) -> str:
        body = str(body or "").replace("&amp;lt;", "<").replace("&amp;gt;", ">")
        body = re.sub(r"<\s*b\s*>", "<B>", body, flags=re.I)
        body = re.sub(r"</\s*b\s*>", "</B>", body, flags=re.I)
        body = re.sub(r"<\s*br\s*/?\s*>", "<BR/>", body, flags=re.I)
        return _escape_raw_ampersands_for_graphviz_html(body)

    text = re.sub(r"label\s*=\s*(&amp;lt;.*?&amp;gt;)", lambda m: f"label={decode_body(m.group(1))}", text, flags=re.S)
    text = re.sub(r"label\s*=\s*(<<.*?>>)", lambda m: f"label={decode_body(m.group(1))}", text, flags=re.S)
    return text


def _sanitize_graphviz_html_like_labels(dot_text: str) -> str:
    if _renderer_sanitize_graphviz_html_like_labels is not None:
        try:
            return _renderer_sanitize_graphviz_html_like_labels(dot_text)  # type: ignore[misc]
        except Exception:
            logger.debug("graphviz_renderer sanitizer failed; using local fallback", exc_info=True)
    return _local_sanitize_graphviz_html_like_labels(dot_text)


# =============================================================================
# Public API
# =============================================================================
def export_editable_diagram(
    diagram_text: str,
    output_dir: Path | str,
    base_name: str,
    *,
    generate_drawio: bool = True,
    generate_vsdx: bool = False,
    graphviz_engine: str = "dot",
    drawio_options: Optional[DrawioExportOptions] = None,
    visio_options: Optional[Any] = None,
    overwrite: bool = True,
) -> DiagramAssets:
    paths = _build_core_asset_paths(output_dir, base_name, generate_drawio, generate_vsdx)

    if _can_reuse_existing_core_assets(paths, overwrite=overwrite):
        _repair_existing_dot_if_present(paths.dot_path)
        _export_optional_assets(paths, generate_drawio, generate_vsdx, drawio_options, visio_options)
        return _diagram_assets_from_paths(paths)

    normalized_dot = _normalise_input_to_dot(diagram_text, base_name)
    _render_core_assets(normalized_dot=normalized_dot, paths=paths, graphviz_engine=graphviz_engine)
    _ensure_core_assets_exist(paths=paths, graphviz_engine=graphviz_engine)
    _export_optional_assets(paths, generate_drawio, generate_vsdx, drawio_options, visio_options)
    return _diagram_assets_from_paths(paths)


def export_many_editable_diagrams(
    diagrams: Iterable[Dict[str, Any]],
    output_dir: Path | str,
    *,
    generate_drawio: bool = True,
    generate_vsdx: bool = False,
    graphviz_engine: str = "dot",
    overwrite: bool = True,
) -> List[DiagramAssets]:
    used: Dict[str, int] = {}
    results: List[DiagramAssets] = []

    for idx, spec in enumerate(diagrams, start=1):
        diagram_text = str(spec.get("diagram_text") or spec.get("text") or "")
        raw_name = spec.get("base_name") or spec.get("section_key") or spec.get("title") or f"diagram_{idx:02d}"
        base_name = _unique_name(_safe_filename(str(raw_name)), used)
        results.append(
            export_editable_diagram(
                diagram_text=diagram_text,
                output_dir=output_dir,
                base_name=base_name,
                generate_drawio=generate_drawio,
                generate_vsdx=generate_vsdx,
                graphviz_engine=graphviz_engine,
                overwrite=overwrite,
            )
        )

    return results


# =============================================================================
# Core export orchestration
# =============================================================================
def _build_core_asset_paths(output_dir: Path | str, base_name: str, generate_drawio: bool, generate_vsdx: bool) -> _CoreAssetPaths:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_base = _safe_filename(base_name)

    return _CoreAssetPaths(
        safe_base=safe_base,
        output_dir=out_dir,
        dot_path=out_dir / f"{safe_base}.dot",
        svg_path=out_dir / f"{safe_base}_editable.svg",
        png_path=out_dir / f"{safe_base}.png",
        legend_path=out_dir / f"{safe_base}_legend.json",
        drawio_path=out_dir / f"{safe_base}.drawio" if generate_drawio else None,
        vsdx_path=out_dir / f"{safe_base}.vsdx" if generate_vsdx else None,
    )


def _can_reuse_existing_core_assets(paths: _CoreAssetPaths, overwrite: bool) -> bool:
    return not overwrite and paths.dot_path.exists() and paths.svg_path.exists() and paths.png_path.exists()


def _normalise_input_to_dot(diagram_text: str, base_name: str) -> str:
    normalized_dot = normalize_to_graphviz_dot(diagram_text)
    if not normalized_dot:
        raise ValueError(f"Diagram text could not be normalized to DOT for {base_name!r}")
    return _clean_and_normalize_dot_for_export(_sanitize_graphviz_html_like_labels(normalized_dot), use_image_cards=False)


def _render_core_assets(normalized_dot: str, paths: _CoreAssetPaths, graphviz_engine: str) -> None:
    normalized_dot = _sanitize_graphviz_html_like_labels(normalized_dot)
    rendered = None

    try:
        rendered = render_graphviz_to_assets(normalized_dot, output_dir=paths.output_dir, base_name=paths.safe_base)
    except Exception:
        logger.exception("Styled Graphviz asset render failed for %s. Trying direct Graphviz fallback.", paths.safe_base)

    if rendered:
        _copy_or_write_asset(_asset_path(rendered, "dot_path"), paths.dot_path, fallback_text=normalized_dot, is_text=True)
        _copy_or_write_asset(
            _asset_path(rendered, "editable_svg_path") or _asset_path(rendered, "svg_path") or _asset_path(rendered, "svg"),
            paths.svg_path,
        )
        _copy_or_write_asset(
            _asset_path(rendered, "png_path") or _asset_path(rendered, "preview_path") or _asset_path(rendered, "png"),
            paths.png_path,
        )
        _write_legend_items(paths.legend_path, _asset_value(rendered, "legend") or [])
        return

    logger.warning("Styled Graphviz asset render returned no assets for %s. Trying direct Graphviz fallback.", paths.safe_base)
    _render_direct_graphviz(
        dot_text=normalized_dot,
        dot_path=paths.dot_path,
        svg_path=paths.svg_path,
        png_path=paths.png_path,
        graphviz_engine=graphviz_engine,
    )
    _write_legend_items(paths.legend_path, [])


def _ensure_core_assets_exist(paths: _CoreAssetPaths, graphviz_engine: str) -> None:
    if not paths.dot_path.exists():
        raise RuntimeError(f"DOT source was not generated: {paths.dot_path}")

    _repair_existing_dot_if_present(paths.dot_path)

    if not paths.svg_path.exists() or not paths.png_path.exists():
        logger.warning("Missing SVG/PNG after styled export for %s. Trying direct Graphviz fallback.", paths.safe_base)
        _render_direct_graphviz(
            dot_text=paths.dot_path.read_text(encoding="utf-8"),
            dot_path=paths.dot_path,
            svg_path=paths.svg_path,
            png_path=paths.png_path,
            graphviz_engine=graphviz_engine,
            preserve_existing_dot=True,
        )

    if not paths.svg_path.exists():
        raise RuntimeError(f"Editable SVG was not generated: {paths.svg_path}")

    if not paths.png_path.exists():
        raise RuntimeError(f"PNG preview was not generated: {paths.png_path}")


def _export_optional_assets(
    paths: _CoreAssetPaths,
    generate_drawio: bool,
    generate_vsdx: bool,
    drawio_options: Optional[DrawioExportOptions],
    visio_options: Optional[Any],
) -> None:
    if generate_drawio and paths.drawio_path:
        _safe_export_drawio(paths.svg_path, paths.drawio_path, drawio_options, paths.safe_base)

    if generate_vsdx and paths.vsdx_path:
        _safe_export_vsdx(
            paths.dot_path,
            paths.svg_path,
            paths.png_path,
            paths.vsdx_path,
            visio_options,
            paths.safe_base,
            legend_items=_read_legend_items(paths.legend_path),
        )


def _diagram_assets_from_paths(paths: _CoreAssetPaths) -> DiagramAssets:
    return DiagramAssets(
        base_name=paths.safe_base,
        output_dir=paths.output_dir,
        dot_path=paths.dot_path,
        svg_path=paths.svg_path,
        png_path=paths.png_path,
        drawio_path=paths.drawio_path if paths.drawio_path and paths.drawio_path.exists() else None,
        vsdx_path=paths.vsdx_path if paths.vsdx_path and paths.vsdx_path.exists() else None,
        legend_path=paths.legend_path if paths.legend_path.exists() else None,
    )


# =============================================================================
# Graphviz/direct asset helpers
# =============================================================================
def _clean_and_normalize_dot_for_export(dot_text: str, *, use_image_cards: bool = False) -> str:
    cleaned_dot = _sanitize_graphviz_html_like_labels(_clean_dot(dot_text))

    try:
        normalized_dot, _legend = normalize_dot_for_graphviz(cleaned_dot, use_image_cards=use_image_cards)
        return _sanitize_graphviz_html_like_labels(normalized_dot)
    except TypeError:
        # Backward compatibility for older graphviz_renderer.normalize_dot_for_graphviz(dot) signature.
        try:
            normalized_dot, _legend = normalize_dot_for_graphviz(cleaned_dot)  # type: ignore[misc]
            return _sanitize_graphviz_html_like_labels(normalized_dot)
        except Exception:
            logger.exception("Generic Graphviz normalization failed in editable diagram exporter. Continuing with repaired DOT only.")
            return cleaned_dot
    except Exception:
        logger.exception("Generic Graphviz normalization failed in editable diagram exporter. Continuing with repaired DOT only.")
        return cleaned_dot


def _repair_existing_dot_if_present(dot_path: Path) -> None:
    if not dot_path.exists():
        return

    try:
        repaired = _clean_and_normalize_dot_for_export(dot_path.read_text(encoding="utf-8"), use_image_cards=False)
        dot_path.write_text(_sanitize_graphviz_html_like_labels(repaired), encoding="utf-8")
    except Exception:
        logger.exception("Failed repairing existing DOT asset: %s", dot_path)


def _render_direct_graphviz(
    *,
    dot_text: str,
    dot_path: Path,
    svg_path: Path,
    png_path: Path,
    graphviz_engine: str,
    preserve_existing_dot: bool = False,
) -> None:
    engine = shutil.which(graphviz_engine)
    if not engine:
        raise RuntimeError(f"Graphviz command not found on PATH: {graphviz_engine}")

    cleaned_dot = _sanitize_graphviz_html_like_labels(_clean_and_normalize_dot_for_export(dot_text, use_image_cards=False))
    dot_path.write_text(cleaned_dot, encoding="utf-8")
    _run_command([engine, "-Tsvg", str(dot_path), "-o", str(svg_path)])
    _run_command([engine, "-Tpng", str(dot_path), "-o", str(png_path)])


def _run_command(args: List[str]) -> None:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed: "
            + " ".join(args)
            + "\nSTDOUT:\n"
            + (result.stdout or "")
            + "\nSTDERR:\n"
            + (result.stderr or "")
        )


def _asset_value(assets: Any, key: str) -> Any:
    if not assets:
        return None
    return assets.get(key) if isinstance(assets, dict) else getattr(assets, key, None)


def _asset_path(assets: Any, key: str) -> Optional[Path]:
    value = _asset_value(assets, key)
    return Path(value) if value else None


def _copy_or_write_asset(
    source_path: Optional[Path],
    target_path: Path,
    fallback_text: Optional[str] = None,
    is_text: bool = False,
) -> None:
    if source_path and source_path.exists():
        if source_path.resolve() == target_path.resolve():
            if is_text:
                target_path.write_text(
                    _clean_and_normalize_dot_for_export(target_path.read_text(encoding="utf-8"), use_image_cards=False),
                    encoding="utf-8",
                )
            return

        if is_text:
            target_path.write_text(
                _clean_and_normalize_dot_for_export(source_path.read_text(encoding="utf-8"), use_image_cards=False),
                encoding="utf-8",
            )
        else:
            target_path.write_bytes(source_path.read_bytes())
        return

    if fallback_text is not None:
        target_path.write_text(_clean_and_normalize_dot_for_export(fallback_text, use_image_cards=False), encoding="utf-8")


def _write_legend_items(path: Path, items: Any) -> None:
    try:
        safe_items: List[Tuple[str, str]] = []
        for item in items or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                color = str(item[0] or "").strip()
                label = str(item[1] or "").strip()
                if color and label:
                    safe_items.append((color, label))
        path.write_text(json.dumps(safe_items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        logger.debug("Failed writing diagram legend sidecar file: %s", path, exc_info=True)


def _read_legend_items(path: Path) -> List[Tuple[str, str]]:
    try:
        if not path.exists():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        items: List[Tuple[str, str]] = []
        for item in raw or []:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                color = str(item[0] or "").strip()
                label = str(item[1] or "").strip()
                if color and label:
                    items.append((color, label))
        return items
    except Exception:
        logger.debug("Failed reading diagram legend sidecar file: %s", path, exc_info=True)
        return []


def _safe_export_drawio(svg_path: Path, drawio_path: Path, options: Optional[DrawioExportOptions], base_name: str) -> None:
    try:
        opts = options or DrawioExportOptions(page_name=_human_title(base_name))
        if not opts.enabled:
            return
        export_drawio_from_svg(svg_path, drawio_path, options=opts)
    except Exception:
        logger.exception("draw.io generation failed for %s", svg_path)
        _delete_partial_file(drawio_path)



# Replace only _safe_export_vsdx in editable_diagram_exporter.py with this version.

def _safe_export_vsdx(
    dot_path: Path,
    svg_path: Path,
    png_path: Path,
    vsdx_path: Path,
    options: Optional[Any],
    base_name: str,
    *,
    legend_items: Optional[List[Tuple[str, str]]] = None,
) -> None:
    if not _VISIO_EXPORT_AVAILABLE or export_vsdx_from_dot is None:
        logger.warning("VSDX generation skipped for %s because no VSDX exporter is available.", dot_path)
        return

    try:
        _repair_existing_dot_if_present(dot_path)

        legend_items = legend_items or []

        if options is None:
            options = VisioExportOptions(
                page_name=_human_title(base_name),
                legend_items=legend_items,
                include_flow_legend=True,
                legend_on_separate_page=False,
                page_width_in=24.0,
                page_height_in=14.0,
                include_visual_background=False,
                include_editable_overlay=True,
                overlay_boxes_visible=True,
                overlay_arrows_visible=True,
                overlay_text_visible=False,
                lock_visual_background=False,
            )
        else:
            if hasattr(options, "page_name") and not getattr(options, "page_name", None):
                options.page_name = _human_title(base_name)
            if hasattr(options, "legend_items"):
                options.legend_items = legend_items
            if hasattr(options, "include_flow_legend"):
                options.include_flow_legend = True
            if hasattr(options, "legend_on_separate_page"):
                options.legend_on_separate_page = False
            if hasattr(options, "include_visual_background"):
                options.include_visual_background = False
            if hasattr(options, "include_editable_overlay"):
                options.include_editable_overlay = True
            if hasattr(options, "overlay_boxes_visible"):
                options.overlay_boxes_visible = True
            if hasattr(options, "overlay_arrows_visible"):
                options.overlay_arrows_visible = True
            if hasattr(options, "overlay_text_visible"):
                options.overlay_text_visible = False
            if hasattr(options, "lock_visual_background"):
                options.lock_visual_background = False

        export_vsdx_from_dot(
            dot_path=dot_path,
            vsdx_path=vsdx_path,
            svg_path=svg_path,
            png_path=png_path,
            options=options,
        )

    except Exception:
        logger.exception("VSDX generation failed for %s", dot_path)
        _delete_partial_file(vsdx_path)



def _delete_partial_file(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        logger.debug("Failed removing partial file: %s", path, exc_info=True)


# =============================================================================
# SVG -> draw.io conversion
# =============================================================================
def export_drawio_from_svg(svg_path: Path | str, drawio_path: Path | str, *, options: Optional[DrawioExportOptions] = None) -> Path:
    opts = options or DrawioExportOptions()
    svg = Path(svg_path)
    out = Path(drawio_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    root = ET.parse(str(svg)).getroot()
    transform = _svg_transform(root, opts)
    cells = _svg_to_drawio_cells(root, transform, opts, svg.parent)

    if opts.include_full_svg_fallback and (not cells or not opts.full_svg_fallback_only_when_no_cells):
        fallback_cell = _full_svg_image_cell(svg_path=svg, opts=opts, cell_id=max(2, len(cells) + 2))
        if fallback_cell:
            cells = [fallback_cell] if opts.full_svg_fallback_only_when_no_cells else cells + [fallback_cell]

    if not cells:
        raise RuntimeError(f"draw.io export produced no cells for SVG: {svg}")

    out.write_text(_build_mxfile(cells, opts), encoding="utf-8")
    _validate_drawio_file(out)
    return out


@dataclass
class _Transform:
    min_x: float
    min_y: float
    scale: float


def _svg_transform(root: ET.Element, opts: DrawioExportOptions) -> _Transform:
    min_x, min_y, width, height = _svg_viewbox(root)
    width = max(width, 1.0)
    height = max(height, 1.0)
    scale = min(opts.page_width / width, opts.page_height / height)
    return _Transform(min_x=min_x, min_y=min_y, scale=scale)


def _to_drawio_xy(x: float, y: float, transform: _Transform) -> Tuple[float, float]:
    return (x - transform.min_x) * transform.scale, (y - transform.min_y) * transform.scale


def _svg_to_drawio_cells(root: ET.Element, transform: _Transform, opts: DrawioExportOptions, svg_dir: Path) -> List[str]:
    cells: List[str] = []
    next_id = 2

    for elem, matrix, classes in _iter_svg_elements_with_matrix(root):
        tag = _local_name(elem.tag)
        style = _parse_style(elem)
        cell = ""

        if tag == "image" and opts.include_svg_images:
            cell, next_id = _image_cell(elem, matrix, transform, next_id, opts, svg_dir)
        elif tag == "rect":
            cell, next_id = _rect_cell(elem, style, matrix, transform, next_id)
        elif tag in {"ellipse", "circle"}:
            cell, next_id = _ellipse_cell(elem, style, matrix, transform, next_id)
        elif tag == "polygon":
            if "edge" in classes:
                continue  # Skip Graphviz arrowheads; _path_cell handles draw.io arrows natively
            elif "graph" in classes:
                continue  # Skip the giant Graphviz background polygon
            else:
                # Safely treat this polygon as a standard node/box
                cell, next_id = _polygon_as_vertex_cell(elem, style, matrix, transform, next_id)
        elif tag == "text" and opts.preserve_text_as_labels:
            cell, next_id = _text_cell(elem, style, matrix, transform, next_id)
        elif tag in {"path", "polyline"} and opts.include_paths_as_edges:
            if "node" in classes:
                # Edge case: Graphviz drew a complex node border as a path
                cell, next_id = _path_as_vertex_cell(elem, style, matrix, transform, next_id, opts)
            else:
                cell, next_id = _path_cell(elem, style, matrix, transform, next_id, opts)

        if cell:
            cells.append(cell)

    return cells

# --- ADD THESE NEW HELPER FUNCTIONS BELOW _path_cell ---

def _polygon_as_vertex_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int) -> Tuple[str, int]:
    points = _points_attr(elem.get("points", ""))
    if len(points) < 3:
        return "", cell_id

    points = [_apply_matrix(matrix, x, y) for x, y in points]
    x1, x2 = min(p[0] for p in points), max(p[0] for p in points)
    y1, y2 = min(p[1] for p in points), max(p[1] for p in points)

    dx, dy = _to_drawio_xy(x1, y1, transform)
    dw, dh = abs(x2 - x1) * transform.scale, abs(y2 - y1) * transform.scale

    mx_style = _drawio_shape_style(
        shape="rectangle",
        fill=style.get("fill") or elem.get("fill") or "#ffffff",
        stroke=style.get("stroke") or elem.get("stroke") or "#000000",
        stroke_width=style.get("stroke-width") or elem.get("stroke-width") or "1",
    )
    return _vertex_xml(cell_id, "", mx_style, dx, dy, dw, dh), cell_id + 1

def _path_as_vertex_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int, opts: DrawioExportOptions) -> Tuple[str, int]:
    tag = _local_name(elem.tag)
    points = _path_points(elem.get("d", ""), opts.curve_sample_steps) if tag == "path" else _points_attr(elem.get("points", ""))

    if len(points) < 2:
        return "", cell_id

    points = [_apply_matrix(matrix, x, y) for x, y in points]
    x1, x2 = min(p[0] for p in points), max(p[0] for p in points)
    y1, y2 = min(p[1] for p in points), max(p[1] for p in points)

    dx, dy = _to_drawio_xy(x1, y1, transform)
    dw, dh = abs(x2 - x1) * transform.scale, abs(y2 - y1) * transform.scale

    mx_style = _drawio_shape_style(
        shape="rectangle",
        fill=style.get("fill") or elem.get("fill") or "#ffffff",
        stroke=style.get("stroke") or elem.get("stroke") or "#000000",
        stroke_width=style.get("stroke-width") or elem.get("stroke-width") or "1",
    )
    return _vertex_xml(cell_id, "", mx_style, dx, dy, dw, dh), cell_id + 1


def _full_svg_image_cell(svg_path: Path, opts: DrawioExportOptions, cell_id: int = 2) -> str:
    try:
        data = base64.b64encode(svg_path.read_bytes()).decode("ascii")
        image_uri = f"data:image/svg+xml%3Bbase64,{data}"
        style = f"shape=image;html=1;imageAspect=0;aspect=fixed;image={image_uri};"
        return _vertex_xml(cell_id=cell_id, value="", style=style, x=0, y=0, width=float(opts.page_width), height=float(opts.page_height))
    except Exception:
        logger.exception("Failed creating full-SVG fallback draw.io cell for %s", svg_path)
        return ""


def _validate_drawio_file(drawio_path: Path) -> None:
    try:
        root = ET.parse(str(drawio_path)).getroot()
    except ET.ParseError as exc:
        try:
            lines = drawio_path.read_text(encoding="utf-8", errors="replace").splitlines()
            line_no = int(getattr(exc, "position", (0, 0))[0] or 0)
            start = max(0, line_no - 3)
            end = min(len(lines), line_no + 2)
            snippet = "\n".join(f"{idx + 1}: {lines[idx]}" for idx in range(start, end))
            logger.error("Invalid draw.io XML around parse error %s:\n%s", exc, snippet)
        except Exception:
            logger.debug("Unable to log invalid draw.io XML snippet", exc_info=True)
        raise

    xml_text = ET.tostring(root, encoding="unicode")
    cell_count = xml_text.count("<mxCell")
    if cell_count <= 2:
        raise RuntimeError(f"draw.io file appears blank or contains no diagram cells: {drawio_path}")


def _image_cell(
    elem: ET.Element,
    matrix: Matrix,
    transform: _Transform,
    cell_id: int,
    opts: DrawioExportOptions,
    svg_dir: Path,
) -> Tuple[str, int]:
    href = _svg_href(elem)
    if not href:
        return "", cell_id

    x = _num(elem.get("x"), 0.0)
    y = _num(elem.get("y"), 0.0)
    width = _num(elem.get("width"), 0.0)
    height = _num(elem.get("height"), 0.0)

    if width <= 0 or height <= 0:
        return "", cell_id

    x1, y1 = _apply_matrix(matrix, x, y)
    x2, y2 = _apply_matrix(matrix, x + width, y + height)
    dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
    dw = abs(x2 - x1) * transform.scale
    dh = abs(y2 - y1) * transform.scale
    image_uri = _normalise_image_href(href, svg_dir, opts)

    if not image_uri:
        return "", cell_id

    mx_style = f"shape=image;html=1;imageAspect=0;aspect=fixed;image={image_uri};"
    return _vertex_xml(cell_id, "", mx_style, dx, dy, dw, dh), cell_id + 1


def _rect_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int) -> Tuple[str, int]:
    x = _num(elem.get("x"), 0.0)
    y = _num(elem.get("y"), 0.0)
    width = _num(elem.get("width"), 0.0)
    height = _num(elem.get("height"), 0.0)

    if width <= 0 or height <= 0:
        return "", cell_id

    x1, y1 = _apply_matrix(matrix, x, y)
    x2, y2 = _apply_matrix(matrix, x + width, y + height)
    dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
    dw = abs(x2 - x1) * transform.scale
    dh = abs(y2 - y1) * transform.scale
    rounded = _num(elem.get("rx"), 0.0) > 0 or _num(elem.get("ry"), 0.0) > 0
    mx_style = _drawio_shape_style(
        shape="rectangle",
        fill=style.get("fill") or elem.get("fill") or "#ffffff",
        stroke=style.get("stroke") or elem.get("stroke") or "#000000",
        stroke_width=style.get("stroke-width") or elem.get("stroke-width") or "1",
        rounded=rounded,
    )
    return _vertex_xml(cell_id, "", mx_style, dx, dy, dw, dh), cell_id + 1


def _ellipse_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int) -> Tuple[str, int]:
    tag = _local_name(elem.tag)
    cx = _num(elem.get("cx"), 0.0)
    cy = _num(elem.get("cy"), 0.0)
    rx = ry = _num(elem.get("r"), 0.0) if tag == "circle" else 0.0

    if tag != "circle":
        rx = _num(elem.get("rx"), 0.0)
        ry = _num(elem.get("ry"), 0.0)

    if rx <= 0 or ry <= 0:
        return "", cell_id

    x1, y1 = _apply_matrix(matrix, cx - rx, cy - ry)
    x2, y2 = _apply_matrix(matrix, cx + rx, cy + ry)
    dx, dy = _to_drawio_xy(min(x1, x2), min(y1, y2), transform)
    width = abs(x2 - x1) * transform.scale
    height = abs(y2 - y1) * transform.scale
    mx_style = _drawio_shape_style(
        shape="ellipse",
        fill=style.get("fill") or elem.get("fill") or "#ffffff",
        stroke=style.get("stroke") or elem.get("stroke") or "#000000",
        stroke_width=style.get("stroke-width") or elem.get("stroke-width") or "1",
    )
    return _vertex_xml(cell_id, "", mx_style, dx, dy, width, height), cell_id + 1


def _text_cell(elem: ET.Element, style: Dict[str, str], matrix: Matrix, transform: _Transform, cell_id: int) -> Tuple[str, int]:
    text = _collect_text(elem)
    if not text:
        return "", cell_id

    x = _num(elem.get("x"), 0.0)
    y = _num(elem.get("y"), 0.0)
    x, y = _apply_matrix(matrix, x, y)
    dx, dy = _to_drawio_xy(x, y, transform)
    font_size = max(6.0, min(32.0, _num(style.get("font-size") or elem.get("font-size"), 12.0) * transform.scale))
    width = max(50.0, len(text) * font_size * 0.55)
    height = max(18.0, font_size * 1.45)
    anchor = style.get("text-anchor") or elem.get("text-anchor") or "start"

    if anchor == "middle":
        dx -= width / 2
    elif anchor == "end":
        dx -= width

    dy -= height * 0.75
    color = _normalize_color(style.get("fill") or elem.get("fill") or "#000000", "#000000")
    weight = str(style.get("font-weight") or elem.get("font-weight") or "").lower()
    font_style = "1" if weight in {"bold", "700", "800"} else "0"
    mx_style = (
        f"text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;"
        f"fontColor={color};fontSize={int(font_size)};fontStyle={font_style};"
    )
    return _vertex_xml(cell_id, text, mx_style, dx, dy, width, height), cell_id + 1


def _path_cell(
    elem: ET.Element,
    style: Dict[str, str],
    matrix: Matrix,
    transform: _Transform,
    cell_id: int,
    opts: DrawioExportOptions,
) -> Tuple[str, int]:
    tag = _local_name(elem.tag)
    points = _path_points(elem.get("d", ""), opts.curve_sample_steps) if tag == "path" else _points_attr(elem.get("points", ""))

    if len(points) < 2:
        return "", cell_id

    points = [_to_drawio_xy(*_apply_matrix(matrix, x, y), transform) for x, y in points]
    stroke = _normalize_color(style.get("stroke") or elem.get("stroke") or "#666666", "#666666")
    width = max(1.0, _num(style.get("stroke-width") or elem.get("stroke-width"), 1.0) * transform.scale)
    dashed = "1" if (style.get("stroke-dasharray") or elem.get("stroke-dasharray")) else "0"
    mx_style = (
        f"edgeStyle=orthogonalEdgeStyle;rounded=0;orthogonalLoop=1;jettySize=auto;html=1;"
        f"strokeColor={stroke};strokeWidth={_fmt(width)};dashed={dashed};endArrow=block;endFill=1;"
    )
    return _edge_xml(cell_id, mx_style, points), cell_id + 1


# =============================================================================
# draw.io XML builders
# =============================================================================
def _build_mxfile(cells: List[str], opts: DrawioExportOptions) -> str:
    body = "\n".join(cells)
    lines = [
        '<mxfile host="app.diagrams.net" agent="AIA-HLD" version="24.0.0" type="device">',
        f'  <diagram id="diagram-1" name="{_xml_attr(opts.page_name)}">',
        f'    <mxGraphModel dx="1422" dy="794" grid="{opts.grid}" gridSize="{opts.grid_size}" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{opts.page_width}" pageHeight="{opts.page_height}" math="0" shadow="0">',
        '      <root>',
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
        body,
        '      </root>',
        '    </mxGraphModel>',
        '  </diagram>',
        '</mxfile>',
    ]
    return "\n".join(line for line in lines if line is not None)


def _vertex_xml(cell_id: int, value: str, style: str, x: float, y: float, width: float, height: float) -> str:
    return (
        f'        <mxCell id="{cell_id}" value="{_xml_attr(value)}" style="{_xml_attr(style)}" vertex="1" parent="1">\n'
        f'          <mxGeometry x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(width)}" height="{_fmt(height)}" as="geometry" />\n'
        f'        </mxCell>'
    )


def _edge_xml(cell_id: int, style: str, points: List[Tuple[float, float]]) -> str:
    source = points[0]
    target = points[-1]
    waypoints = points[1:-1]
    lines = [
        f'        <mxCell id="{cell_id}" value="" style="{_xml_attr(style)}" edge="1" parent="1">',
        '          <mxGeometry relative="1" as="geometry">',
        f'            <mxPoint x="{_fmt(source[0])}" y="{_fmt(source[1])}" as="sourcePoint" />',
        f'            <mxPoint x="{_fmt(target[0])}" y="{_fmt(target[1])}" as="targetPoint" />',
    ]

    if waypoints:
        lines.append('            <Array as="points">')
        for x, y in waypoints:
            lines.append(f'              <mxPoint x="{_fmt(x)}" y="{_fmt(y)}" />')
        lines.append('            </Array>')

    lines.extend(['          </mxGeometry>', '        </mxCell>'])
    return "\n".join(lines)


def _drawio_shape_style(
    *,
    shape: str,
    fill: Optional[str],
    stroke: Optional[str],
    stroke_width: Optional[str],
    rounded: bool = False,
) -> str:
    return (
        f"shape={shape};html=1;whiteSpace=wrap;rounded={'1' if rounded else '0'};"
        f"fillColor={_normalize_color(fill, '#ffffff')};"
        f"strokeColor={_normalize_color(stroke, '#000000')};"
        f"strokeWidth={_fmt(_num(stroke_width, 1.0))};"
    )


# =============================================================================
# SVG traversal, transforms and parsing helpers
# =============================================================================
def _iter_svg_elements_with_matrix(root: ET.Element) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
    supported = {"rect", "ellipse", "circle", "text", "path", "polyline", "polygon", "image"}

    def walk(elem: ET.Element, parent_matrix: Matrix, parent_classes: List[str]) -> Iterator[Tuple[ET.Element, Matrix, List[str]]]:
        matrix = _matrix_multiply(parent_matrix, _parse_transform(elem.get("transform")))
        
        # Track Graphviz classes like "node", "edge", "graph" down the tree
        raw_class = elem.get("class") or ""
        classes = [c.strip().lower() for c in raw_class.split() if c.strip()]
        current_classes = parent_classes + classes
        
        if _local_name(elem.tag) in supported:
            yield elem, matrix, current_classes
            
        for child in list(elem):
            yield from walk(child, matrix, current_classes)

    yield from walk(root, IDENTITY, [])


def _parse_transform(raw: Optional[str]) -> Matrix:
    if not raw:
        return IDENTITY

    matrix = IDENTITY
    for name, args in re.findall(r"(matrix|translate|scale|rotate)\s*\(([^)]*)\)", raw):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", args)]
        local = IDENTITY

        if name == "matrix" and len(nums) >= 6:
            local = (nums[0], nums[1], nums[2], nums[3], nums[4], nums[5])
        elif name == "translate":
            local = (1.0, 0.0, 0.0, 1.0, nums[0] if nums else 0.0, nums[1] if len(nums) > 1 else 0.0)
        elif name == "scale":
            sx = nums[0] if nums else 1.0
            sy = nums[1] if len(nums) > 1 else sx
            local = (sx, 0.0, 0.0, sy, 0.0, 0.0)
        elif name == "rotate":
            if nums and abs(nums[0]) > 0.001:
                logger.debug("Ignoring non-zero SVG rotate transform: %s", raw)

        matrix = _matrix_multiply(matrix, local)

    return matrix


def _matrix_multiply(m1: Matrix, m2: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def _apply_matrix(m: Matrix, x: float, y: float) -> Tuple[float, float]:
    a, b, c, d, e, f = m
    return a * x + c * y + e, b * x + d * y + f


def _svg_href(elem: ET.Element) -> str:
    return (elem.get("href") or elem.get("{http://www.w3.org/1999/xlink}href") or elem.get("xlink:href") or "").strip()


def _normalise_image_href(href: str, svg_dir: Path, opts: DrawioExportOptions) -> str:
    if not href:
        return ""

    if href.startswith("data:"):
        return href.replace(";", "%3B", 1)

    if href.startswith(("http://", "https://")):
        return href

    img_path = Path(unquote(href))
    if not img_path.is_absolute():
        img_path = svg_dir / img_path

    if opts.embed_local_images_as_data_uri and img_path.exists():
        mime = mimetypes.guess_type(str(img_path))[0] or "image/png"
        data = base64.b64encode(img_path.read_bytes()).decode("ascii")
        return f"data:{mime}%3Bbase64,{data}"

    return img_path.resolve().as_uri() if img_path.exists() else href


def _local_name(tag: str) -> str:
    return str(tag).split("}", 1)[-1].lower()


def _parse_style(elem: ET.Element) -> Dict[str, str]:
    style: Dict[str, str] = {}
    raw = elem.get("style") or ""

    for part in raw.split(";"):
        if ":" in part:
            key, value = part.split(":", 1)
            style[key.strip().lower()] = value.strip()

    for key, value in elem.attrib.items():
        low = key.lower()
        if low in {"fill", "stroke", "stroke-width", "stroke-dasharray", "font-size", "font-weight", "text-anchor"}:
            style[low] = value

    return style


def _svg_viewbox(root: ET.Element) -> Tuple[float, float, float, float]:
    viewbox = root.get("viewBox") or root.get("viewbox")
    if viewbox:
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", viewbox)]
        if len(nums) >= 4:
            return nums[0], nums[1], nums[2], nums[3]

    return 0.0, 0.0, _num(root.get("width"), 1000.0), _num(root.get("height"), 800.0)


def _collect_text(elem: ET.Element) -> str:
    parts: List[str] = []

    if elem.text:
        parts.append(elem.text)

    for child in elem.iter():
        if child is elem:
            continue
        if child.text:
            parts.append(child.text)
        if child.tail:
            parts.append(child.tail)

    return html.unescape(" ".join(part.strip() for part in parts if part and part.strip())).strip()


def _points_attr(raw: str) -> List[Tuple[float, float]]:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", raw or "")]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def _path_points(d: str, steps: int = 12) -> List[Tuple[float, float]]:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", d or "")]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


# =============================================================================
# Generic helpers
# =============================================================================
def _clean_dot(dot: str) -> str:
    raw = html.unescape(dot or "")
    raw = (
        raw.replace("-&amp;amp;amp;amp;gt;", "->")
        .replace("-&amp;amp;amp;gt;", "->")
        .replace("-&amp;amp;gt;", "->")
        .replace("-&amp;gt;", "->")
        .replace("→", "->")
    )
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"```(?:dot|graphviz)?", "", raw, flags=re.I).replace("```", "")
    raw = _sanitize_graphviz_html_like_labels(raw)

    if re.search(r"^\s*(strict\s+)?(di)?graph\b", raw, flags=re.I | re.M):
        return raw.strip() + "\n"

    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return "digraph G {\n  rankdir=LR;\n}\n"

    out = ["digraph G {", "  rankdir=LR;"]
    for line in lines:
        line = line.rstrip(";")
        if not line or line in {"{", "}"}:
            continue
        if not line.endswith(";"):
            line += ";"
        out.append("  " + line)
    out.append("}")
    return "\n".join(out) + "\n"


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "diagram")).strip("._")
    return safe or "diagram"


def _unique_name(base: str, used: Dict[str, int]) -> str:
    count = used.get(base, 0) + 1
    used[base] = count
    return base if count == 1 else f"{base}_{count:02d}"


def _human_title(value: str) -> str:
    return re.sub(r"[_-]+", " ", str(value or "Diagram")).strip().title() or "Diagram"


def _num(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default

    raw = re.sub(r"[a-zA-Z%]+$", "", str(value).strip())
    try:
        return float(raw)
    except Exception:
        return default


def _normalize_color(value: Any, default: str) -> str:
    raw = str(value or "").strip()

    if not raw or raw.lower() in {"none", "transparent"}:
        return default

    if raw.startswith("#") and len(raw) in {4, 7}:
        return "#" + "".join(ch * 2 for ch in raw[1:]) if len(raw) == 4 else raw

    named = {
        "black": "#000000",
        "white": "#ffffff",
        "red": "#ff0000",
        "green": "#008000",
        "blue": "#0000ff",
        "gray": "#808080",
        "grey": "#808080",
        "orange": "#ffa500",
        "purple": "#800080",
        "yellow": "#ffff00",
        "cyan": "#00ffff",
        "magenta": "#ff00ff",
        "brown": "#a52a2a",
        "pink": "#ffc0cb",
    }
    return named.get(raw.lower(), default)


def _fmt(value: float) -> str:
    try:
        value = float(value)
    except Exception:
        value = 0.0

    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))

    return f"{value:.2f}".rstrip("0").rstrip(".")
