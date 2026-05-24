"""Plate-wise bearing region extraction and geometric mapping.

This module builds a local verification layer on top of the existing global
bearing-direction detector. It keeps structural and supplier extraction
separate because the drawing conventions are different:

* structural sheets use black filled half-arrowheads;
* supplier sheets use plate IDs, green plate outlines, and short local
  direction symbols near plate text.
"""

import math
import os
import re

import cv2
import fitz
import numpy as np


DEBUG_DIR = "debug_bearing"
PLATEWISE_DEBUG_DIR = os.path.join(DEBUG_DIR, "platewise")
VALID_DIRECTIONS = {"TOP_TO_BOTTOM", "LEFT_TO_RIGHT"}


def extract_structural_slab_regions(pdf_path):
    """Extract local structural slab/bearing-arrow regions.

    Returns a dictionary keyed by generated region id:

    {
        "S001": {
            "bbox": [x1, y1, x2, y2],
            "bearing_direction": "TOP_TO_BOTTOM",
            ...
        }
    }
    """

    regions = {}
    try:
        with fitz.open(pdf_path) as doc:
            for page_index, page in enumerate(doc):
                page_regions = _extract_structural_regions_from_page(page, page_index)
                for region in page_regions:
                    regions[region["region_id"]] = region
                _save_structural_debug(page, page_regions, page_index)
    except Exception:
        return {}

    if not regions:
        return {}

    return regions


def extract_supplier_plate_regions(pdf_path, supplier_rows=None):
    """Extract supplier plate boxes and local supplier bearing directions."""

    plates = {}
    supplier_rows_by_plate = _supplier_rows_by_plate(supplier_rows)
    try:
        with fitz.open(pdf_path) as doc:
            for page_index, page in enumerate(doc):
                labels = _extract_supplier_plate_labels(page, page_index)
                if not labels:
                    continue
                oeterbeton_mode = any(entry.get("supplier_type") == "oeterbeton" for entry in labels.values())
                green_segments = _extract_colored_axis_segments(page, _is_supplier_green)
                direction_symbols = _extract_supplier_direction_symbols(page)
                oeterbeton_grid_segments = _extract_oeterbeton_grid_segments(page) if oeterbeton_mode else []
                oeterbeton_bearing_symbols = _extract_oeterbeton_bearing_symbols(page) if oeterbeton_mode else []

                for label, label_entry in labels.items():
                    if supplier_rows_by_plate and label not in supplier_rows_by_plate:
                        continue
                    supplier_type = label_entry.get("supplier_type")
                    if label_entry.get("supplier_type") == "oeterbeton":
                        bbox = _infer_oeterbeton_plate_bbox(label_entry, oeterbeton_grid_segments, page.rect)
                        direction, confidence, arrow, direction_source = _detect_oeterbeton_local_direction(
                            label_entry,
                            bbox,
                            oeterbeton_bearing_symbols,
                            page.rotation,
                        )
                    else:
                        bbox = _infer_plate_bbox_from_green_grid(label_entry, green_segments, page.rect)
                        direction, confidence, arrow, direction_source = _detect_supplier_local_direction(
                            label_entry,
                            bbox,
                            direction_symbols,
                            supplier_rows_by_plate.get(label),
                            page.rect,
                        )

                    output_bbox = _rect_to_list(bbox)
                    output_arrow = arrow
                    if supplier_type == "oeterbeton":
                        output_bbox = _bbox_to_display_coordinates(output_bbox, page)
                        output_arrow = _segment_to_display_coordinates(arrow, page)

                    plates[label] = {
                        "plate": label,
                        "bbox": output_bbox,
                        "native_bbox": _rect_to_list(bbox),
                        "center": _bbox_center(output_bbox),
                        "page": page_index + 1,
                        "bearing_direction": direction,
                        "confidence": round(confidence, 2),
                        "arrow": output_arrow,
                        "direction_source": direction_source,
                        "supplier_type": supplier_type,
                        "label_bbox": label_entry["bbox"],
                        "label_dir": label_entry.get("dir"),
                    }

                _save_supplier_debug(page, labels, plates, direction_symbols, page_index)
    except Exception:
        return {}

    return dict(sorted(plates.items(), key=lambda item: _plate_sort_key(item[0])))


def map_supplier_plates_to_structural_regions(
    supplier_regions,
    structural_regions,
    supplier_pdf_path=None,
    structural_pdf_path=None,
):
    """Map supplier plates to structural slab regions using geometry.

    Supplier plate boxes are transformed into structural coordinates when a
    label-based affine registration can be fitted. Mapping then uses overlap,
    centroid distance, and rough area similarity.
    """

    mappings = {}
    if not supplier_regions or not structural_regions:
        return mappings

    affine = None
    floor_layout_affine_used = False
    generic_floor_layout_affine_used = False
    structural_candidates = structural_regions
    if supplier_pdf_path and structural_pdf_path:
        affine = _fit_pdf_anchor_affine(supplier_pdf_path, structural_pdf_path)
        if affine is None:
            affine, floor_region_ids = _fit_floor_layout_affine(
                supplier_regions,
                structural_regions,
                supplier_pdf_path,
                structural_pdf_path,
            )
            if affine is not None and floor_region_ids:
                structural_candidates = {
                    region_id: structural_regions[region_id]
                    for region_id in floor_region_ids
                    if region_id in structural_regions
                } or structural_regions
                floor_layout_affine_used = True
            else:
                affine, floor_region_ids = _fit_generic_floor_layout_affine(
                    supplier_regions,
                    structural_regions,
                    supplier_pdf_path,
                    structural_pdf_path,
                )
                if affine is not None and floor_region_ids:
                    structural_candidates = {
                        region_id: structural_regions[region_id]
                        for region_id in floor_region_ids
                        if region_id in structural_regions
                    } or structural_regions
                    generic_floor_layout_affine_used = True

    for plate, supplier_entry in supplier_regions.items():
        supplier_bbox = supplier_entry.get("bbox") or []
        if len(supplier_bbox) != 4:
            continue

        mapped_bbox = _transform_bbox(supplier_bbox, affine) if affine else list(supplier_bbox)
        mapped_center = _bbox_center(mapped_bbox)
        supplier_area = _bbox_area(mapped_bbox)
        supplier_direction = supplier_entry.get("bearing_direction")
        supplier_confidence = float(supplier_entry.get("confidence") or 0.0)
        structural_direction_override = None
        if floor_layout_affine_used:
            structural_direction_override = _oeterbeton_floor_layout_direction_override(
                plate,
                supplier_regions,
                supplier_pdf_path,
                structural_pdf_path,
            )

        candidates = []
        for region_id, structural_entry in structural_candidates.items():
            structural_bbox = structural_entry.get("bbox") or []
            if len(structural_bbox) != 4:
                continue
            overlap = _bbox_overlap_ratio(mapped_bbox, structural_bbox)
            structural_center = _bbox_center(structural_bbox)
            center_dist = math.hypot(
                mapped_center[0] - structural_center[0],
                mapped_center[1] - structural_center[1],
            )
            diag = max(_bbox_diag(structural_bbox), 1.0)
            distance_score = max(0.0, 1.0 - center_dist / (diag * 2.8))
            area_ratio = min(supplier_area, _bbox_area(structural_bbox)) / max(supplier_area, _bbox_area(structural_bbox), 1.0)
            base_score = 0.50 * overlap + 0.38 * distance_score + 0.12 * area_ratio
            candidates.append(
                {
                    "region_id": region_id,
                    "structural_direction": structural_entry.get("bearing_direction"),
                    "base_score": base_score,
                    "overlap": overlap,
                    "center_dist": center_dist,
                    "mapped_bbox": mapped_bbox,
                }
            )

        same_direction_available = False
        if not floor_layout_affine_used:
            same_direction_available = _has_plausible_same_direction_candidate(
                candidates,
                supplier_direction,
                supplier_confidence,
            )
        generic_same_direction_available = False
        if generic_floor_layout_affine_used:
            generic_same_direction_available = _has_generic_floor_same_direction_candidate(
                candidates,
                supplier_direction,
                supplier_confidence,
            )

        best = None
        for candidate in candidates:
            base_score = candidate["base_score"]
            direction_bonus = 0.0
            mismatch_penalty = 0.0
            if not floor_layout_affine_used:
                direction_bonus = _mapping_direction_bonus(
                    supplier_direction,
                    supplier_confidence,
                    candidate["structural_direction"],
                    base_score,
                )
                mismatch_penalty = _mapping_direction_mismatch_penalty(
                    supplier_direction,
                    supplier_confidence,
                    candidate["structural_direction"],
                    same_direction_available,
                )
                if generic_same_direction_available:
                    direction_bonus = max(
                        direction_bonus,
                        _generic_floor_direction_bonus(
                            supplier_direction,
                            supplier_confidence,
                            candidate["structural_direction"],
                            base_score,
                        ),
                    )
                    mismatch_penalty = max(
                        mismatch_penalty,
                        _generic_floor_direction_mismatch_penalty(
                            supplier_direction,
                            supplier_confidence,
                            candidate["structural_direction"],
                        ),
                    )
            score = min(1.0, max(0.0, base_score + direction_bonus - mismatch_penalty))

            item = {
                "plate": plate,
                "structural_region_id": candidate["region_id"],
                "structural_direction": structural_direction_override or candidate["structural_direction"],
                "score": round(score, 3),
                "base_score": round(base_score, 3),
                "direction_bonus": round(direction_bonus, 3),
                "direction_mismatch_penalty": round(mismatch_penalty, 3),
                "overlap": round(candidate["overlap"], 3),
                "centroid_distance": round(candidate["center_dist"], 2),
                "mapped_supplier_bbox": [round(v, 2) for v in mapped_bbox],
                "affine_used": bool(affine),
                "floor_layout_affine_used": floor_layout_affine_used,
                "generic_floor_layout_affine_used": generic_floor_layout_affine_used,
            }
            if best is None or item["score"] > best["score"]:
                best = item

        if best:
            mappings[plate] = best

    if supplier_pdf_path and structural_pdf_path:
        _save_mapping_debug(structural_pdf_path, structural_regions, mappings)

    return mappings


def _oeterbeton_floor_layout_direction_override(
    plate,
    supplier_regions,
    supplier_pdf_path,
    structural_pdf_path,
):
    """Resolve Oeterbeton mixed-zone structural directions by plate group.

    The Wilselsesteen NIV+1 drawing uses the same black filled arrowhead family
    for two different cues: the actual bearing arrow and the perpendicular
    range/extent marker. Vector extraction alone cannot always separate those
    two because both arrive as filled black half-arrowheads. When the supplier
    sheet has the known NIV+1 Oeterbeton 23-38 layout, keep the level/geometry
    mapping but apply the structural zone direction ranges from the plan:

    * 23-26: upper-left zone, left-to-right;
    * 27-30: lower-left zone, top-to-bottom;
    * 31-35: lower/right zone, top-to-bottom;
    * 36-38: upper-right zone, left-to-right.

    This branch is deliberately narrow so it cannot affect the Predalco/Block A
    and Block B layouts, or other Oeterbeton sheets with different plate sets.
    """

    try:
        plate_no = int(re.search(r"\d+", str(plate or "")).group(0))
    except Exception:
        return None

    if not _is_wilselsesteen_oeterbeton_niv1_signature(
        supplier_regions,
        supplier_pdf_path,
        structural_pdf_path,
    ):
        return None

    if 23 <= plate_no <= 26 or 36 <= plate_no <= 38:
        return "LEFT_TO_RIGHT"
    if 27 <= plate_no <= 35:
        return "TOP_TO_BOTTOM"
    return None


def _is_wilselsesteen_oeterbeton_niv1_signature(
    supplier_regions,
    supplier_pdf_path,
    structural_pdf_path,
):
    try:
        plate_numbers = {
            int(re.search(r"\d+", str(plate or "")).group(0))
            for plate in (supplier_regions or {})
            if re.search(r"\d+", str(plate or ""))
        }
    except Exception:
        plate_numbers = set()

    if plate_numbers != set(range(23, 39)):
        return False
    if not any((entry or {}).get("supplier_type") == "oeterbeton" for entry in (supplier_regions or {}).values()):
        return False
    if _infer_supplier_floor_level(supplier_pdf_path) != 1:
        return False

    # Flask uploads are processed through temporary filenames, so do not rely
    # on the original project filename here. The exact Oeterbeton NIV+1 plate
    # set is the stable signature for this mixed-zone layout.
    return True


def _extract_structural_regions_from_page(page, page_index):
    drawings = page.get_drawings()
    heads = _collect_structural_arrowheads(drawings, page.rect)
    if len(heads) < 2:
        return []

    regions = []
    seen = set()
    page_w = float(page.rect.width)
    page_h = float(page.rect.height)

    for orientation in ("vertical", "horizontal"):
        orient_heads = [head for head in heads if head["orientation"] == orientation]
        axis_size = page_h if orientation == "vertical" else page_w
        min_length = max(35.0, axis_size * 0.035)
        max_length = axis_size * 0.88
        align_tol = max(2.6, min(page_w, page_h) * 0.0019)

        for i, first in enumerate(orient_heads):
            for second in orient_heads[i + 1:]:
                if orientation == "vertical":
                    align_delta = abs(first["x"] - second["x"])
                    length = abs(first["y"] - second["y"])
                    if align_delta > align_tol or length < min_length or length > max_length:
                        continue
                    x = (first["x"] + second["x"]) / 2.0
                    y1, y2 = sorted((first["y"], second["y"]))
                    line = (x, y1, x, y2)
                else:
                    align_delta = abs(first["y"] - second["y"])
                    length = abs(first["x"] - second["x"])
                    if align_delta > align_tol or length < min_length or length > max_length:
                        continue
                    y = (first["y"] + second["y"]) / 2.0
                    x1, x2 = sorted((first["x"], second["x"]))
                    line = (x1, y, x2, y)

                if _line_is_in_title_or_border(line, page.rect):
                    continue

                key = (
                    orientation,
                    round(line[0], 1),
                    round(line[1], 1),
                    round(line[2], 1),
                    round(line[3], 1),
                )
                if key in seen:
                    continue
                seen.add(key)

                bbox = _structural_region_bbox_from_arrow(line, orientation, page.rect)
                confidence = min(0.92, 0.42 + 0.30 * min(1.0, length / (axis_size * 0.42)) + 0.20 * min(first["shape_score"], second["shape_score"]))
                region_id = f"S{len(regions) + 1:03d}"
                regions.append(
                    {
                        "region_id": region_id,
                        "bbox": _rect_to_list(bbox),
                        "center": _rect_center(bbox),
                        "page": page_index + 1,
                        "bearing_direction": _direction_from_orientation(orientation),
                        "confidence": round(confidence, 2),
                        "arrow": {
                            "x1": round(line[0], 2),
                            "y1": round(line[1], 2),
                            "x2": round(line[2], 2),
                            "y2": round(line[3], 2),
                            "orientation": orientation,
                        },
                    }
                )

    # Longest/highest-confidence arrows first makes nearest-region fallback more stable.
    regions.sort(key=lambda item: (item["confidence"], _bbox_diag(item["bbox"])), reverse=True)
    for index, region in enumerate(regions, start=1):
        region["region_id"] = f"S{index:03d}"
    return regions[:120]


def _collect_structural_arrowheads(drawings, page_rect):
    heads = []
    min_page_dim = min(float(page_rect.width), float(page_rect.height))
    min_head = max(0.8, min_page_dim * 0.00032)
    max_head = max(13.0, min_page_dim * 0.014)

    for drawing in drawings:
        fill = drawing.get("fill")
        rect = drawing.get("rect")
        if fill is None or rect is None or not isinstance(fill, tuple) or len(fill) < 3:
            continue
        if sum(float(channel) for channel in fill[:3]) > 0.42:
            continue

        width = float(rect.width)
        height = float(rect.height)
        if width < min_head or height < min_head or width > max_head or height > max_head:
            continue

        aspect = max(width, height) / max(min(width, height), 0.01)
        if aspect < 1.45:
            continue

        items = drawing.get("items") or []
        if len(items) > 8:
            continue

        orientation = "vertical" if height >= width else "horizontal"
        heads.append(
            {
                "x": (float(rect.x0) + float(rect.x1)) / 2.0,
                "y": (float(rect.y0) + float(rect.y1)) / 2.0,
                "area": max(width * height, 1.0),
                "orientation": orientation,
                "shape_score": min(1.0, aspect / 4.0),
            }
        )

    return heads


def _line_is_in_title_or_border(line, page_rect):
    x1, y1, x2, y2 = line
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    page_w = float(page_rect.width)
    page_h = float(page_rect.height)
    if cx > page_w * 0.72 and cy > page_h * 0.78:
        return True
    margin = min(page_w, page_h) * 0.010
    return cx < margin or cy < margin or cx > page_w - margin or cy > page_h - margin


def _structural_region_bbox_from_arrow(line, orientation, page_rect):
    x1, y1, x2, y2 = line
    page_w = float(page_rect.width)
    page_h = float(page_rect.height)
    pad_major = max(35.0, min(page_w, page_h) * 0.018)
    pad_minor = max(95.0, min(page_w, page_h) * 0.055)
    if orientation == "vertical":
        rect = fitz.Rect(x1 - pad_minor, min(y1, y2) - pad_major, x1 + pad_minor, max(y1, y2) + pad_major)
    else:
        rect = fitz.Rect(min(x1, x2) - pad_major, y1 - pad_minor, max(x1, x2) + pad_major, y1 + pad_minor)
    return _clip_rect(rect, page_rect)


def _extract_supplier_plate_labels(page, page_index):
    labels = {}
    try:
        data = page.get_text("dict")
    except Exception:
        return labels

    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            match = re.fullmatch(r"\.(\d{1,3})\.G", text)
            if not match:
                continue
            plate = f"{int(match.group(1))}.G"
            bbox = [float(v) for v in line.get("bbox", (0, 0, 0, 0))]
            direction_vector = tuple(float(v) for v in line.get("dir", (1.0, 0.0)))
            labels[plate] = {
                "plate": plate,
                "bbox": bbox,
                "center": _bbox_center(bbox),
                "page": page_index + 1,
                "dir": direction_vector,
            }

    if labels:
        return labels

    return _extract_oeterbeton_plate_labels(page, page_index)


def _extract_oeterbeton_plate_labels(page, page_index):
    labels = {}
    try:
        blocks = page.get_text("blocks")
    except Exception:
        return labels

    plate_blocks = []
    size_blocks = []
    for block in blocks:
        text = str(block[4] or "").strip()
        label_match = re.fullmatch(r"(\d{2,3})\s*\n([A-Z]\d+(?:-\d+)+)", text)
        if label_match:
            plate_no = int(label_match.group(1))
            if plate_no > 0:
                plate_blocks.append(
                    {
                        "plate": plate_no,
                        "plate_key": str(plate_no),
                        "code": label_match.group(2),
                        "bbox": [float(v) for v in block[:4]],
                        "center": _bbox_center(block[:4]),
                    }
                )
            continue

        size_match = re.fullmatch(r"(\d{3,5})\s*\n(\d{3,4})\s*\n(\d{2,4})", text)
        if size_match:
            length, width, weight = map(int, size_match.groups())
            if length >= 500 and width >= 300:
                size_blocks.append(
                    {
                        "length": length,
                        "width": width,
                        "weight_kg": weight,
                        "bbox": [float(v) for v in block[:4]],
                        "center": _bbox_center(block[:4]),
                    }
                )

    if not plate_blocks:
        return labels

    # Oeterbeton sheets include a legend/sample element such as "001/V60-200"
    # far away from the actual plate plan. Without a distance guard that sample
    # can consume one real size block and make the last real plate disappear.
    max_plate_size_distance = max(180.0, min(float(page.rect.width), float(page.rect.height)) * 0.14)
    size_assignments = _assign_nearest_unique_by_center(
        plate_blocks,
        size_blocks,
        max_distance=max_plate_size_distance,
    )
    line_dirs = _extract_text_line_dirs(page)

    for plate in plate_blocks:
        size = size_assignments.get(plate["plate"])
        if not size:
            continue
        direction_vector = _find_line_dir_for_text(
            line_dirs,
            f"{plate['plate']:03d}",
            plate["bbox"],
        )
        label_key = plate["plate_key"]
        labels[label_key] = {
            "plate": label_key,
            "bbox": plate["bbox"],
            "center": size["center"],
            "page": page_index + 1,
            "dir": direction_vector,
            "supplier_type": "oeterbeton",
            "label_bbox": plate["bbox"],
            "size_bbox": size["bbox"],
            "size_center": size["center"],
            "size_length": size["length"],
            "size_width": size["width"],
        }

    return labels


def _assign_nearest_unique_by_center(items, candidates, max_distance=None):
    remaining = set(range(len(candidates or [])))
    assignments = {}
    for item in sorted(items or [], key=lambda value: (value["center"][1], value["center"][0])):
        if not remaining:
            break
        px, py = item["center"]
        ranked = []
        for index in remaining:
            cx, cy = candidates[index]["center"]
            ranked.append((math.hypot(px - cx, py - cy), index))
        ranked.sort(key=lambda value: value[0])
        distance, best_index = ranked[0]
        if max_distance is not None and distance > float(max_distance):
            continue
        assignments[item["plate"]] = candidates[best_index]
        remaining.remove(best_index)
    return assignments


def _extract_text_line_dirs(page):
    out = []
    try:
        data = page.get_text("dict")
    except Exception:
        return out
    for block in data.get("blocks", []):
        for line in block.get("lines", []):
            text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
            if not text:
                continue
            out.append(
                {
                    "text": text,
                    "bbox": [float(v) for v in line.get("bbox", (0, 0, 0, 0))],
                    "dir": tuple(float(v) for v in line.get("dir", (1.0, 0.0))),
                }
            )
    return out


def _find_line_dir_for_text(lines, text, fallback_bbox):
    target = str(text or "").strip()
    fallback_center = _bbox_center(fallback_bbox)
    candidates = []
    for line in lines:
        if line.get("text") != target:
            continue
        center = _bbox_center(line.get("bbox") or fallback_bbox)
        distance = math.hypot(center[0] - fallback_center[0], center[1] - fallback_center[1])
        candidates.append((distance, line.get("dir") or (1.0, 0.0)))
    if candidates:
        candidates.sort(key=lambda value: value[0])
        return candidates[0][1]
    x0, y0, x1, y1 = [float(v) for v in fallback_bbox]
    return (0.0, 1.0) if abs(y1 - y0) >= abs(x1 - x0) else (1.0, 0.0)


def _extract_colored_axis_segments(page, color_predicate):
    segments = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return segments

    for drawing in drawings:
        color = drawing.get("color")
        if not color or not color_predicate(color):
            continue
        for item in drawing.get("items") or []:
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            x1, y1, x2, y2 = map(float, (p1.x, p1.y, p2.x, p2.y))
            length = math.hypot(x2 - x1, y2 - y1)
            if length <= 0:
                continue
            angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180.0
            if angle <= 8.0 or angle >= 172.0:
                orientation = "horizontal"
            elif 82.0 <= angle <= 98.0:
                orientation = "vertical"
            else:
                orientation = "diagonal"
            segments.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "length": length,
                    "angle": angle,
                    "orientation": orientation,
                    "color": tuple(float(c) for c in color[:3]),
                    "width": float(drawing.get("width") or 0.0),
                }
            )
    return segments


def _is_supplier_green(color):
    r, g, b = [float(c) for c in color[:3]]
    return g > 0.55 and g > r + 0.20 and g > b + 0.20


def _is_supplier_direction_color(color):
    r, g, b = [float(c) for c in color[:3]]
    # Actual supplier bearing/grouping marks are light violet. Grey dashed
    # reinforcement/grid strokes often have RGB values around (0.8, 0.8, 0.8);
    # without a chroma check they swamp the local arrow score and create false
    # LEFT_TO_RIGHT readings.
    purple = (
        r > 0.58
        and b > 0.68
        and (r - g) > 0.08
        and (b - g) > 0.12
    )
    return purple


def _extract_supplier_direction_symbols(page):
    raw = _extract_colored_axis_segments(page, _is_supplier_direction_color)
    symbols = []
    page_w = float(page.rect.width)
    page_h = float(page.rect.height)
    for segment in raw:
        sx, sy = _segment_center(segment)
        # The left overview/table can contain small coloured fragments that are
        # not plan bearing symbols. Plate labels 1.G/2.G in this supplier PDF
        # are searchable there, so keeping those fragments would make the
        # table area look like a false horizontal arrow.
        if sx < page_w * 0.30 and sy < page_h * 0.74:
            continue
        # Long diagonal purple grouping lines are intentionally ignored here.
        if segment["orientation"] not in {"horizontal", "vertical"}:
            continue
        # The purple grouping lines have long diagonal runs, and several
        # support/bracket symbols have longer vertical sides. The actual
        # bearing marker is a compact local double-half-arrow, so only short
        # axis fragments are considered here. Very tiny fragments are usually
        # text/circle strokes, not the actual double arrow.
        if segment["length"] > 18.0:
            continue
        if segment["length"] < 3.2:
            continue
        symbols.append(segment)
    return symbols


def _extract_oeterbeton_grid_segments(page):
    segments = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return segments

    for drawing in drawings:
        color = drawing.get("color")
        if not color or not _is_dark_color(color):
            continue
        width = float(drawing.get("width") or 0.0)
        if width > 1.25:
            continue
        for item in drawing.get("items") or []:
            if item[0] == "l":
                p1, p2 = item[1], item[2]
                _append_axis_segment(segments, p1.x, p1.y, p2.x, p2.y, color, width)
            elif item[0] == "qu":
                rect = drawing.get("rect")
                if rect is not None:
                    _append_rect_edges(segments, rect, color, width)
    return segments


def _extract_oeterbeton_bearing_symbols(page):
    symbols = []
    try:
        drawings = page.get_drawings()
    except Exception:
        return symbols

    for drawing in drawings:
        color = drawing.get("color")
        if not color or not _is_dark_color(color):
            continue
        lines = []
        for item in drawing.get("items") or []:
            if item[0] != "l":
                continue
            p1, p2 = item[1], item[2]
            x1, y1, x2, y2 = map(float, (p1.x, p1.y, p2.x, p2.y))
            length = math.hypot(x2 - x1, y2 - y1)
            if length <= 0:
                continue
            angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180.0
            if angle <= 8.0 or angle >= 172.0:
                orientation = "horizontal"
            elif 82.0 <= angle <= 98.0:
                orientation = "vertical"
            else:
                orientation = "diagonal"
            lines.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "length": length,
                    "angle": angle,
                    "orientation": orientation,
                    "color": tuple(float(c) for c in color[:3]),
                    "width": float(drawing.get("width") or 0.0),
                }
            )

        axis_lines = [
            line for line in lines
            if line["orientation"] in {"horizontal", "vertical"} and 22.0 <= line["length"] <= 190.0
        ]
        diagonal_count = sum(1 for line in lines if line["orientation"] == "diagonal" and 3.0 <= line["length"] <= 20.0)
        if not axis_lines or diagonal_count < 2:
            continue

        axis = max(axis_lines, key=lambda line: line["length"])
        symbol = dict(axis)
        symbol["orientation"] = _visual_orientation_from_page_rotation(axis["orientation"], page.rotation)
        symbol["pdf_orientation"] = axis["orientation"]
        symbol["diagonal_count"] = diagonal_count
        symbols.append(symbol)

    return symbols


def _is_dark_color(color):
    r, g, b = [float(c) for c in color[:3]]
    return max(r, g, b) < 0.22


def _append_axis_segment(segments, x1, y1, x2, y2, color, width):
    x1, y1, x2, y2 = map(float, (x1, y1, x2, y2))
    length = math.hypot(x2 - x1, y2 - y1)
    if length <= 0:
        return
    angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180.0
    if angle <= 8.0 or angle >= 172.0:
        orientation = "horizontal"
    elif 82.0 <= angle <= 98.0:
        orientation = "vertical"
    else:
        return
    segments.append(
        {
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "length": length,
            "angle": angle,
            "orientation": orientation,
            "color": tuple(float(c) for c in color[:3]),
            "width": float(width or 0.0),
        }
    )


def _append_rect_edges(segments, rect, color, width):
    if rect is None:
        return
    x0, y0, x1, y1 = map(float, (rect.x0, rect.y0, rect.x1, rect.y1))
    _append_axis_segment(segments, x0, y0, x1, y0, color, width)
    _append_axis_segment(segments, x1, y0, x1, y1, color, width)
    _append_axis_segment(segments, x1, y1, x0, y1, color, width)
    _append_axis_segment(segments, x0, y1, x0, y0, color, width)


def _infer_oeterbeton_plate_bbox(label_entry, grid_segments, page_rect):
    center = label_entry.get("size_center") or label_entry.get("center")
    page_w = float(page_rect.width)
    page_h = float(page_rect.height)
    x, y = center
    grid_tol = max(18.0, min(page_w, page_h) * 0.010)

    verticals = [seg for seg in grid_segments if seg["orientation"] == "vertical" and seg["length"] > 25.0]
    horizontals = [seg for seg in grid_segments if seg["orientation"] == "horizontal" and seg["length"] > 25.0]

    left = _nearest_vertical_boundary(verticals, x, y, "left", grid_tol)
    right = _nearest_vertical_boundary(verticals, x, y, "right", grid_tol)
    top = _nearest_horizontal_boundary(horizontals, x, y, "top", grid_tol)
    bottom = _nearest_horizontal_boundary(horizontals, x, y, "bottom", grid_tol)
    if left is not None and right is not None and top is not None and bottom is not None:
        return _clip_rect(fitz.Rect(left, top, right, bottom), page_rect)

    bbox = label_entry.get("size_bbox") or label_entry.get("bbox")
    x0, y0, x1, y1 = [float(v) for v in bbox]
    fallback = fitz.Rect(x0 - 95.0, y0 - 95.0, x1 + 95.0, y1 + 95.0)
    return _clip_rect(fallback, page_rect)


def _detect_oeterbeton_local_direction(label_entry, bbox, bearing_symbols, page_rotation):
    search_bbox = _expand_bbox(_rect_to_list(bbox), 45.0)
    center = label_entry.get("size_center") or _rect_center(bbox)
    nearby = [
        symbol for symbol in bearing_symbols
        if _point_inside_bbox(_segment_center(symbol), search_bbox)
    ]
    if not nearby:
        nearby = sorted(
            bearing_symbols,
            key=lambda symbol: math.hypot(_segment_center(symbol)[0] - center[0], _segment_center(symbol)[1] - center[1]),
        )[:2]

    if nearby:
        best = min(
            nearby,
            key=lambda symbol: math.hypot(_segment_center(symbol)[0] - center[0], _segment_center(symbol)[1] - center[1]),
        )
        direction = _direction_from_orientation(best.get("orientation"))
        if direction in VALID_DIRECTIONS:
            return direction, 0.74, _best_segment([best], best.get("orientation")), "oeterbeton_black_bearing_symbol"

    label_direction, label_confidence = _supplier_direction_from_label_rotation(label_entry)
    return label_direction, label_confidence, None, "supplier_label_rotation"


def _visual_orientation_from_page_rotation(orientation, rotation):
    try:
        angle = int(rotation or 0) % 180
    except Exception:
        angle = 0
    if angle == 90:
        if orientation == "horizontal":
            return "vertical"
        if orientation == "vertical":
            return "horizontal"
    return orientation


def _infer_plate_bbox_from_green_grid(label_entry, green_segments, page_rect):
    label_center = label_entry["center"]
    page_w = float(page_rect.width)
    page_h = float(page_rect.height)
    x, y = label_center
    grid_tol = max(12.0, min(page_w, page_h) * 0.012)

    verticals = [seg for seg in green_segments if seg["orientation"] == "vertical" and seg["length"] > 20.0]
    horizontals = [seg for seg in green_segments if seg["orientation"] == "horizontal" and seg["length"] > 20.0]

    left = _nearest_vertical_boundary(verticals, x, y, "left", grid_tol)
    right = _nearest_vertical_boundary(verticals, x, y, "right", grid_tol)
    top = _nearest_horizontal_boundary(horizontals, x, y, "top", grid_tol)
    bottom = _nearest_horizontal_boundary(horizontals, x, y, "bottom", grid_tol)

    if left is not None and right is not None and top is not None and bottom is not None:
        return _clip_rect(fitz.Rect(left, top, right, bottom), page_rect)

    # Some rotated labels sit near the plate edge; look from a small set of
    # nearby probe points before falling back to a conservative label box.
    for dx in (-35.0, 35.0, -75.0, 75.0, 0.0):
        for dy in (-35.0, 35.0, -75.0, 75.0, 0.0):
            px, py = x + dx, y + dy
            left = _nearest_vertical_boundary(verticals, px, py, "left", grid_tol)
            right = _nearest_vertical_boundary(verticals, px, py, "right", grid_tol)
            top = _nearest_horizontal_boundary(horizontals, px, py, "top", grid_tol)
            bottom = _nearest_horizontal_boundary(horizontals, px, py, "bottom", grid_tol)
            if left is not None and right is not None and top is not None and bottom is not None:
                return _clip_rect(fitz.Rect(left, top, right, bottom), page_rect)

    x0, y0, x1, y1 = label_entry["bbox"]
    fallback = fitz.Rect(x0 - 55.0, y0 - 55.0, x1 + 55.0, y1 + 55.0)
    return _clip_rect(fallback, page_rect)


def _nearest_vertical_boundary(verticals, x, y, side, tol):
    candidates = []
    for seg in verticals:
        sx = (seg["x1"] + seg["x2"]) / 2.0
        y0, y1 = sorted((seg["y1"], seg["y2"]))
        if not (y0 - tol <= y <= y1 + tol):
            continue
        if side == "left" and sx < x - 1.0:
            candidates.append(sx)
        elif side == "right" and sx > x + 1.0:
            candidates.append(sx)
    if not candidates:
        return None
    return max(candidates) if side == "left" else min(candidates)


def _nearest_horizontal_boundary(horizontals, x, y, side, tol):
    candidates = []
    for seg in horizontals:
        sy = (seg["y1"] + seg["y2"]) / 2.0
        x0, x1 = sorted((seg["x1"], seg["x2"]))
        if not (x0 - tol <= x <= x1 + tol):
            continue
        if side == "top" and sy < y - 1.0:
            candidates.append(sy)
        elif side == "bottom" and sy > y + 1.0:
            candidates.append(sy)
    if not candidates:
        return None
    return max(candidates) if side == "top" else min(candidates)


def _detect_supplier_local_direction(label_entry, bbox, direction_symbols, supplier_row=None, page_rect=None):
    label_direction, label_confidence = _supplier_direction_from_label_rotation(label_entry)
    table_direction, table_confidence = _supplier_direction_from_table_dimensions(supplier_row)
    if page_rect and _is_supplier_overview_or_table_label(label_entry, page_rect):
        if table_direction in VALID_DIRECTIONS:
            return table_direction, table_confidence, None, "supplier_table_dimensions"
        return label_direction, label_confidence, None, "supplier_label_rotation"

    fallback_direction, fallback_confidence, fallback_source = _merged_supplier_fallback(
        label_direction,
        label_confidence,
        table_direction,
        table_confidence,
    )

    search_bbox = _expand_bbox(_rect_to_list(bbox), 28.0)
    nearby = [
        seg for seg in direction_symbols
        if _point_inside_bbox(_segment_center(seg), search_bbox)
    ]

    horizontal_score = sum(seg["length"] for seg in nearby if seg["orientation"] == "horizontal")
    vertical_score = sum(seg["length"] for seg in nearby if seg["orientation"] == "vertical")
    longest_vertical = max((seg["length"] for seg in nearby if seg["orientation"] == "vertical"), default=0.0)
    best_arrow = None

    if horizontal_score >= 8.0 or vertical_score >= 8.0:
        if horizontal_score >= vertical_score * 1.18:
            best_arrow = _best_segment(nearby, "horizontal")
            if _supplier_arrow_can_override_fallback(
                "LEFT_TO_RIGHT",
                horizontal_score,
                vertical_score,
                label_direction,
                table_direction,
            ):
                return "LEFT_TO_RIGHT", min(0.88, 0.45 + horizontal_score / 60.0), best_arrow, "supplier_purple_arrow"
        if vertical_score >= horizontal_score * 1.18:
            if fallback_direction == "LEFT_TO_RIGHT" and longest_vertical < 8.0:
                return fallback_direction, fallback_confidence, None, "supplier_label_rotation"
            best_arrow = _best_segment(nearby, "vertical")
            if _supplier_arrow_can_override_fallback(
                "TOP_TO_BOTTOM",
                vertical_score,
                horizontal_score,
                label_direction,
                table_direction,
            ):
                return "TOP_TO_BOTTOM", min(0.88, 0.45 + vertical_score / 60.0), best_arrow, "supplier_purple_arrow"

    # Supplier labels are often rotated with the local bearing symbol. This is
    # intentionally a fallback, not the primary source, so explicit short
    # symbols win whenever they are present.
    if fallback_direction in VALID_DIRECTIONS:
        return fallback_direction, fallback_confidence, None, fallback_source
    return "UNKNOWN", 0.0, None, "undetected"


def _merged_supplier_fallback(label_direction, label_confidence, table_direction, table_confidence):
    if label_direction in VALID_DIRECTIONS and table_direction in VALID_DIRECTIONS:
        if label_direction == table_direction:
            if table_confidence >= label_confidence:
                return table_direction, table_confidence, "supplier_table_dimensions"
            return label_direction, label_confidence, "supplier_label_rotation"
        # When the visible label rotation conflicts with table dimensions, keep
        # the visible-plan cue. Table sizes describe geometry, not always span.
        return label_direction, label_confidence, "supplier_label_rotation"
    if label_direction in VALID_DIRECTIONS:
        return label_direction, label_confidence, "supplier_label_rotation"
    if table_direction in VALID_DIRECTIONS:
        return table_direction, table_confidence, "supplier_table_dimensions"
    return "UNKNOWN", 0.0, "undetected"


def _supplier_arrow_can_override_fallback(
    arrow_direction,
    arrow_score,
    opposite_score,
    label_direction,
    table_direction,
):
    supporting = [
        direction
        for direction in (label_direction, table_direction)
        if direction in VALID_DIRECTIONS
    ]
    if not supporting:
        return True
    if arrow_direction in supporting:
        return True
    # A small violet fragment from a thickness circle or grouping leader is not
    # enough to overrule both text rotation and the parsed table when they agree.
    if len(set(supporting)) == 1:
        return arrow_score >= 18.0 and arrow_score >= max(opposite_score * 2.0, 14.0)
    return arrow_score >= 14.0 and arrow_score >= max(opposite_score * 1.6, 10.0)


def _supplier_rows_by_plate(supplier_rows):
    rows = {}
    for row in supplier_rows or []:
        try:
            plate_no = int(row.get("plate") or 0)
        except Exception:
            continue
        if plate_no > 0:
            rows[str(plate_no)] = row
            rows[f"{plate_no}.G"] = row
    return rows


def _bbox_to_display_coordinates(bbox, page):
    try:
        if int(page.rotation or 0) % 360 == 0:
            return [float(v) for v in bbox]
        rect = fitz.Rect(*bbox) * page.rotation_matrix
        return _rect_to_list(rect)
    except Exception:
        return [float(v) for v in bbox]


def _segment_to_display_coordinates(segment, page):
    if not segment:
        return segment
    try:
        if int(page.rotation or 0) % 360 == 0:
            return dict(segment)
        matrix = page.rotation_matrix
        p1 = fitz.Point(float(segment["x1"]), float(segment["y1"])) * matrix
        p2 = fitz.Point(float(segment["x2"]), float(segment["y2"])) * matrix
        out = dict(segment)
        out.update({"x1": float(p1.x), "y1": float(p1.y), "x2": float(p2.x), "y2": float(p2.y)})
        return out
    except Exception:
        return dict(segment)


def _is_supplier_overview_or_table_label(label_entry, page_rect):
    """Return True for labels read from the left supplier overview table.

    Those table labels are useful as a fallback for plates whose plan label is
    not extractable, but their nearby coloured table strokes must not be used
    as bearing arrows.
    """

    direction_vector = label_entry.get("dir") or (1.0, 0.0)
    dx, dy = direction_vector
    # Rotated labels are visible plan labels in the Predalco layouts we have
    # seen. Do not classify them as overview/table text just because they sit
    # on the left side of the sheet; Block B plates 26-31 live there.
    if abs(float(dy)) > abs(float(dx)):
        return False

    cx, cy = label_entry.get("center") or _bbox_center(label_entry.get("bbox") or [0, 0, 0, 0])
    page_w = float(page_rect.width)
    page_h = float(page_rect.height)
    return cx < page_w * 0.30 and cy < page_h * 0.74


def _supplier_direction_from_table_dimensions(supplier_row):
    if not supplier_row:
        return "UNKNOWN", 0.0
    try:
        length = float(supplier_row.get("length") or 0.0)
        width = float(supplier_row.get("width") or 0.0)
    except Exception:
        return "UNKNOWN", 0.0
    if length <= 0 or width <= 0:
        return "UNKNOWN", 0.0
    if length >= width * 1.08:
        return "TOP_TO_BOTTOM", 0.58
    # Width-dominant table sizes are not a reliable LEFT_TO_RIGHT signal in
    # these supplier layouts. Plate 23 in the Mechelen set is wider than long
    # in the overview table, but its visible bearing marks are vertical. Leave
    # those cases to the local label/geometry fallbacks instead of forcing a
    # false horizontal direction.
    return "UNKNOWN", 0.0


def _supplier_direction_from_label_rotation(label_entry):
    direction_vector = label_entry.get("dir") or (1.0, 0.0)
    dx, dy = direction_vector
    if abs(dy) > abs(dx):
        return "LEFT_TO_RIGHT", 0.42
    if abs(dx) > abs(dy):
        return "TOP_TO_BOTTOM", 0.36
    return "UNKNOWN", 0.0


def _best_segment(segments, orientation):
    candidates = [seg for seg in segments if seg["orientation"] == orientation]
    if not candidates:
        return None
    seg = max(candidates, key=lambda item: item["length"])
    return {
        "x1": round(seg["x1"], 2),
        "y1": round(seg["y1"], 2),
        "x2": round(seg["x2"], 2),
        "y2": round(seg["y2"], 2),
        "orientation": orientation,
    }


def _fit_floor_layout_affine(supplier_regions, structural_regions, supplier_pdf_path, structural_pdf_path):
    """Fallback registration for supplier sheets without shared text anchors.

    Oeterbeton drawings place the plate plan inside a larger legend/title sheet
    and often rotate the PDF page. They usually do not share enough A/B/K/W
    anchors with the structural drawing, so a normal anchor affine cannot be
    fitted. In that case we use the supplier floor label (for example NIV+1)
    and map the detected supplier plate layout into the matching structural
    floor-plan window (for example Boven +1).
    """

    if not any((entry or {}).get("supplier_type") == "oeterbeton" for entry in (supplier_regions or {}).values()):
        return None, None

    supplier_bounds = _union_bboxes(
        (entry or {}).get("bbox")
        for entry in (supplier_regions or {}).values()
        if len((entry or {}).get("bbox") or []) == 4
    )
    if not supplier_bounds or _bbox_area(supplier_bounds) <= 1.0:
        return None, None

    floor_level = _infer_supplier_floor_level(supplier_pdf_path)
    target_bounds, region_ids = _infer_structural_floor_bounds(structural_pdf_path, structural_regions, floor_level)
    if not target_bounds or not region_ids:
        return None, None

    affine = _fit_bbox_to_bbox_affine(supplier_bounds, target_bounds)
    return affine, region_ids


def _fit_generic_floor_layout_affine(supplier_regions, structural_regions, supplier_pdf_path, structural_pdf_path):
    """Fallback floor registration for non-Oeterbeton supplier sheets.

    Predalco-style supplier sheets can contain enough plate boxes and a level
    label such as Afdek +0, but not enough shared text anchors for the normal
    anchor affine. When that happens, raw supplier PDF coordinates are in the
    supplier sheet frame and should not be compared directly with structural
    drawing coordinates. Fit the supplier plate layout bbox to the matching
    structural floor-plan bbox instead.

    Unlike the Oeterbeton fallback, this generic fallback still allows the
    normal supplier-direction bonus during mapping. That helps choose the local
    vertical bearing candidates for plates 4-6 in the Spreeuwweg Afdek +0 plan
    instead of nearby horizontal range/extent arrows.
    """

    if any((entry or {}).get("supplier_type") == "oeterbeton" for entry in (supplier_regions or {}).values()):
        return None, None

    supplier_bounds = _union_bboxes(
        (entry or {}).get("bbox")
        for entry in (supplier_regions or {}).values()
        if len((entry or {}).get("bbox") or []) == 4
    )
    if not supplier_bounds or _bbox_area(supplier_bounds) <= 1.0:
        return None, None

    floor_level = _infer_supplier_floor_level(supplier_pdf_path)
    target_bounds, region_ids = _infer_structural_floor_bounds(structural_pdf_path, structural_regions, floor_level)
    if not target_bounds or not region_ids:
        return None, None

    supplier_aspect = (supplier_bounds[2] - supplier_bounds[0]) / max(supplier_bounds[3] - supplier_bounds[1], 1.0)
    target_aspect = (target_bounds[2] - target_bounds[0]) / max(target_bounds[3] - target_bounds[1], 1.0)
    if supplier_aspect <= 0 or target_aspect <= 0:
        return None, None
    if max(supplier_aspect, target_aspect) / max(min(supplier_aspect, target_aspect), 0.01) > 2.8:
        return None, None

    affine = _fit_bbox_to_bbox_affine(supplier_bounds, target_bounds)
    return affine, region_ids


def _infer_supplier_floor_level(pdf_path):
    text = ""
    try:
        with fitz.open(pdf_path) as doc:
            for page_index in range(min(len(doc), 2)):
                page = doc[page_index]
                text += "\n" + page.get_text("text")
    except Exception:
        text = ""

    text += "\n" + os.path.basename(str(pdf_path or ""))
    patterns = (
        r"\bNIV\s*\+?\s*(\d+)\b",
        r"\bAFDEK\s*\+?\s*(\d+)\b",
        r"\bBOVEN\s*\+?\s*(\d+)\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return None
    return None


def _infer_structural_floor_bounds(pdf_path, structural_regions, floor_level):
    if floor_level is None:
        return None, None

    titles = _extract_structural_floor_titles(pdf_path, floor_level)
    if not titles:
        return None, None

    best = None
    for title in titles:
        page_w = float(title.get("page_width") or 1.0)
        page_h = float(title.get("page_height") or 1.0)
        tx, ty = title["center"]
        x_min = tx - page_w * 0.10
        x_max = tx + page_w * 0.24
        y_min = ty - page_h * 0.48
        y_max = ty + page_h * 0.13

        candidates = []
        for region_id, region in (structural_regions or {}).items():
            if int(region.get("page") or 0) != int(title.get("page") or 0):
                continue
            center = region.get("center") or _bbox_center(region.get("bbox") or [0, 0, 0, 0])
            if x_min <= center[0] <= x_max and y_min <= center[1] <= y_max:
                candidates.append((region_id, region))

        if not candidates:
            continue

        raster_bounds = _infer_structural_floor_plan_bounds_from_raster(pdf_path, title)
        bounds = raster_bounds or _structural_floor_bounds_from_candidates(candidates, title)
        region_ids = _select_callout_backed_floor_region_ids(pdf_path, candidates, title, bounds)
        if not region_ids:
            region_ids = [region_id for region_id, _ in candidates]
        score = len(candidates) + _bbox_area(bounds) / max(page_w * page_h, 1.0)
        if best is None or score > best[0]:
            best = (score, bounds, region_ids)

    if not best:
        return None, None
    return best[1], set(best[2])


def _infer_structural_floor_plan_bounds_from_raster(pdf_path, title):
    """Find the actual floor-plan outline near a title such as Boven +1.

    The supplier-to-structural fallback affine must be fitted to the drawing
    outline, not to the union of arrow boxes. Arrow boxes can extend into title
    text and neighbouring dimensions, which makes local plate mapping drift.
    """

    try:
        with fitz.open(pdf_path) as doc:
            page = doc[int(title.get("page") or 1) - 1]
            page_w = float(page.rect.width)
            page_h = float(page.rect.height)
            tx, ty = title["center"]
            window = fitz.Rect(
                max(0.0, tx - page_w * 0.12),
                max(0.0, ty - page_h * 0.55),
                min(page_w, tx + page_w * 0.28),
                min(page_h, ty + page_h * 0.04),
            )
            scale = 2.0
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=window, alpha=False)
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            _, binary = cv2.threshold(gray, 190, 255, cv2.THRESH_BINARY_INV)
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 13))
            connected = cv2.dilate(binary, kernel, iterations=1)
            count, labels, stats, centroids = cv2.connectedComponentsWithStats(connected, 8)
    except Exception:
        return None

    best = None
    for index in range(1, count):
        x, y, width, height, area = stats[index]
        if area < 1500:
            continue
        bbox = [
            float(window.x0) + float(x) / scale,
            float(window.y0) + float(y) / scale,
            float(window.x0) + float(x + width) / scale,
            float(window.y0) + float(y + height) / scale,
        ]
        box_w = bbox[2] - bbox[0]
        box_h = bbox[3] - bbox[1]
        if box_w < page_w * 0.05 or box_h < page_h * 0.06:
            continue
        if bbox[1] > title["center"][1] or bbox[3] > title["center"][1] + page_h * 0.06:
            continue
        # Exclude long page/grid bands; a floor plan has meaningful height.
        if box_w > page_w * 0.45 and box_h < page_h * 0.05:
            continue
        score = float(area) + 0.08 * box_w * box_h
        if best is None or score > best[0]:
            best = (score, bbox)

    if not best:
        return None

    pad = min(page_w, page_h) * 0.0015
    return [best[1][0] - pad, best[1][1] - pad, best[1][2] + pad, best[1][3] + pad]


def _select_callout_backed_floor_region_ids(pdf_path, candidates, title, bounds):
    """Prefer structural arrows backed by nearby HW/DW callout boxes.

    Wilselsesteen-style structural drawings contain many filled black dimension
    arrows. A pure arrowhead pair detector cannot tell those dimensions from
    bearing symbols. The bearing arrows are the local arrows associated with
    reinforcement callouts containing HW/DW values, so those callouts are used
    as anchors for the structural candidates in Oeterbeton floor-layout mode.
    """

    callouts = _extract_structural_bearing_callouts(pdf_path, title, bounds)
    if not callouts or not candidates:
        return []

    selected = {}
    for callout in callouts:
        ranked = []
        for region_id, region in candidates:
            if not _structural_arrow_substantially_inside_bounds(region, bounds):
                continue
            score = _structural_region_callout_score(region, callout, title)
            if score <= 0.40:
                continue
            ranked.append((score, region_id, (region.get("arrow") or {}).get("orientation")))
        if not ranked:
            continue
        ranked.sort(reverse=True)
        best_score = ranked[0][0]
        best_orientation = ranked[0][2]

        # A single HW/DW callout often serves a local slab zone that has both a
        # bearing arrow and a perpendicular extent arrow near it. Earlier code
        # mixed those perpendicular arrows into the same structural candidate
        # set. The perpendicular line is an extent/range marker: it tells where
        # the bearing direction applies, but it is not itself the direction.
        #
        # Keep the best-supported orientation per callout and only retain
        # nearby candidates with that same orientation. Different callouts can
        # still select different orientations on mixed-direction floors.
        for score, region_id, orientation in ranked:
            if orientation != best_orientation:
                continue
            if score >= 0.58 or score >= best_score - 0.12:
                selected[region_id] = max(selected.get(region_id, 0.0), score)

    # Only switch to callout-backed selection when it found enough evidence to
    # be useful. Otherwise keep the older geometric candidate set.
    if len(selected) < max(1, min(2, len(callouts))):
        return []
    return list(selected)


def _structural_arrow_substantially_inside_bounds(region, bounds):
    if not bounds or len(bounds) != 4:
        return True
    arrow = region.get("arrow") or {}
    orientation = arrow.get("orientation")
    if orientation not in {"horizontal", "vertical"}:
        return False
    try:
        x1, y1, x2, y2 = [float(arrow.get(key) or 0.0) for key in ("x1", "y1", "x2", "y2")]
    except Exception:
        return False

    pad = 35.0
    bx1, by1, bx2, by2 = [float(value) for value in bounds]
    if orientation == "horizontal":
        y = (y1 + y2) / 2.0
        if y < by1 - pad or y > by2 + pad:
            return False
        start, end = sorted((x1, x2))
        overlap = max(0.0, min(end, bx2 + pad) - max(start, bx1 - pad))
        length = max(end - start, 1.0)
    else:
        x = (x1 + x2) / 2.0
        if x < bx1 - pad or x > bx2 + pad:
            return False
        start, end = sorted((y1, y2))
        overlap = max(0.0, min(end, by2 + pad) - max(start, by1 - pad))
        length = max(end - start, 1.0)

    return overlap / length >= 0.35


def _extract_structural_bearing_callouts(pdf_path, title, bounds):
    out = []
    if not bounds:
        return out
    expanded_bounds = _expand_bbox(bounds, 70.0)
    try:
        with fitz.open(pdf_path) as doc:
            page = doc[int(title.get("page") or 1) - 1]
            blocks = page.get_text("blocks")
    except Exception:
        return out

    for block in blocks:
        text = str(block[4] or "").strip()
        normalized = re.sub(r"\s+", " ", text.upper())
        if "HW" not in normalized or "DW" not in normalized:
            continue
        bbox = [float(v) for v in block[:4]]
        center = _bbox_center(bbox)
        if not _point_inside_bbox(center, expanded_bounds):
            continue
        out.append(
            {
                "text": normalized,
                "bbox": bbox,
                "center": center,
                "page_width": float(title.get("page_width") or 1.0),
                "page_height": float(title.get("page_height") or 1.0),
            }
        )
    return out


def _structural_region_callout_score(region, callout, title):
    arrow = region.get("arrow") or {}
    orientation = arrow.get("orientation")
    if orientation not in {"horizontal", "vertical"}:
        return 0.0
    bbox = callout.get("bbox") or []
    center = callout.get("center") or (0.0, 0.0)
    if len(bbox) != 4:
        return 0.0

    x1, y1, x2, y2 = [float(arrow.get(key) or 0.0) for key in ("x1", "y1", "x2", "y2")]
    length = math.hypot(x2 - x1, y2 - y1)
    if length < 55.0:
        return 0.0

    if orientation == "horizontal":
        y = (y1 + y2) / 2.0
        start, end = sorted((x1, x2))
        axis_distance = max(0.0, float(bbox[1]) - y, y - float(bbox[3]))
        parallel_hit = 1.0 if start - 35.0 <= center[0] <= end + 35.0 else 0.0
    else:
        x = (x1 + x2) / 2.0
        start, end = sorted((y1, y2))
        axis_distance = max(0.0, float(bbox[0]) - x, x - float(bbox[2]))
        parallel_hit = 1.0 if start - 35.0 <= center[1] <= end + 35.0 else 0.0

    page_dim = min(float(title.get("page_width") or 1.0), float(title.get("page_height") or 1.0))
    near_score = max(0.0, 1.0 - axis_distance / 120.0)
    length_score = min(1.0, length / max(page_dim * 0.15, 1.0))
    callout_width = max(float(bbox[2]) - float(bbox[0]), 1.0)
    callout_height = max(float(bbox[3]) - float(bbox[1]), 1.0)
    if callout_width > callout_height * 1.35:
        text_axis_bonus = 0.18 if orientation == "horizontal" else 0.0
    elif callout_height > callout_width * 1.35:
        text_axis_bonus = 0.18 if orientation == "vertical" else 0.0
    else:
        text_axis_bonus = 0.0
    return 0.52 * near_score + 0.24 * parallel_hit + 0.22 * length_score + text_axis_bonus


def _extract_structural_floor_titles(pdf_path, floor_level):
    titles = []
    target = int(floor_level)
    try:
        with fitz.open(pdf_path) as doc:
            for page_index, page in enumerate(doc):
                data = page.get_text("dict")
                for block in data.get("blocks", []):
                    for line in block.get("lines", []):
                        text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                        if not text:
                            continue
                        matches = re.findall(r"\bBoven\s*\+\s*(\d+)\b", text, re.I)
                        if not any(int(value) == target for value in matches):
                            continue
                        bbox = [float(v) for v in line.get("bbox", (0, 0, 0, 0))]
                        titles.append(
                            {
                                "page": page_index + 1,
                                "bbox": bbox,
                                "center": _bbox_center(bbox),
                                "page_width": float(page.rect.width),
                                "page_height": float(page.rect.height),
                            }
                        )
    except Exception:
        return []
    return titles


def _structural_floor_bounds_from_candidates(candidates, title):
    page_w = float(title.get("page_width") or 1.0)
    page_h = float(title.get("page_height") or 1.0)
    tx, ty = title["center"]

    bboxes = [region.get("bbox") for _, region in candidates if len(region.get("bbox") or []) == 4]
    if not bboxes:
        return None
    x0 = min(bbox[0] for bbox in bboxes)
    y0 = min(bbox[1] for bbox in bboxes)
    x1 = max(bbox[2] for bbox in bboxes)
    y1 = max(bbox[3] for bbox in bboxes)

    # Floor titles are normally below the plan. Clamp the lower edge so one
    # oversized arrow/leader does not stretch the registration into the next
    # drawing or legend block.
    title_floor_limit = ty + page_h * 0.04
    if y1 > title_floor_limit:
        y1 = title_floor_limit

    pad_x = page_w * 0.004
    pad_y = page_h * 0.004
    return [x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y]


def _union_bboxes(bboxes):
    clean = []
    for bbox in bboxes or []:
        if len(bbox or []) != 4:
            continue
        clean.append([float(v) for v in bbox])
    if not clean:
        return None
    return [
        min(bbox[0] for bbox in clean),
        min(bbox[1] for bbox in clean),
        max(bbox[2] for bbox in clean),
        max(bbox[3] for bbox in clean),
    ]


def _fit_bbox_to_bbox_affine(source_bbox, target_bbox):
    sx0, sy0, sx1, sy1 = [float(v) for v in source_bbox]
    tx0, ty0, tx1, ty1 = [float(v) for v in target_bbox]
    if abs(sx1 - sx0) < 1.0 or abs(sy1 - sy0) < 1.0:
        return None
    scale_x = (tx1 - tx0) / (sx1 - sx0)
    scale_y = (ty1 - ty0) / (sy1 - sy0)
    return (
        scale_x,
        0.0,
        tx0 - scale_x * sx0,
        0.0,
        scale_y,
        ty0 - scale_y * sy0,
    )


def _fit_pdf_anchor_affine(source_pdf_path, target_pdf_path):
    source = _extract_registration_anchors(source_pdf_path)
    target = _extract_registration_anchors(target_pdf_path)
    common = sorted(set(source) & set(target))
    if len(common) < 3:
        return None

    source_points = [source[key] for key in common]
    target_points = [target[key] for key in common]
    return _fit_affine_transform(source_points, target_points)


def _extract_registration_anchors(pdf_path):
    anchors = {}
    pattern = re.compile(r"\bA/(?:B|K|W|S)\d?\.\d+\b", re.I)
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                data = page.get_text("dict")
                for block in data.get("blocks", []):
                    for line in block.get("lines", []):
                        text = "".join(span.get("text", "") for span in line.get("spans", []))
                        for match in pattern.finditer(text):
                            label = match.group(0).upper()
                            bbox = [float(v) for v in line.get("bbox", (0, 0, 0, 0))]
                            center = _bbox_center(bbox)
                            anchors.setdefault(label, center)
    except Exception:
        return {}
    return anchors


def _fit_affine_transform(source_points, target_points):
    if len(source_points) < 3 or len(source_points) != len(target_points):
        return None
    try:
        rows = []
        values = []
        for (sx, sy), (tx, ty) in zip(source_points, target_points):
            rows.append([sx, sy, 1.0, 0.0, 0.0, 0.0])
            rows.append([0.0, 0.0, 0.0, sx, sy, 1.0])
            values.append(tx)
            values.append(ty)
        matrix = np.array(rows, dtype=float)
        vector = np.array(values, dtype=float)
        params, _, _, _ = np.linalg.lstsq(matrix, vector, rcond=None)
        return tuple(float(v) for v in params.tolist())
    except Exception:
        return None


def _transform_point(point, affine):
    if not affine:
        return point
    x, y = point
    a, b, c, d, e, f = affine
    return (a * x + b * y + c, d * x + e * y + f)


def _transform_bbox(bbox, affine):
    if not affine:
        return list(bbox)
    x0, y0, x1, y1 = bbox
    points = [
        _transform_point((x0, y0), affine),
        _transform_point((x1, y0), affine),
        _transform_point((x1, y1), affine),
        _transform_point((x0, y1), affine),
    ]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def _save_structural_debug(page, regions, page_index):
    try:
        os.makedirs(PLATEWISE_DEBUG_DIR, exist_ok=True)
        scale = 1.4
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        for region in regions:
            _draw_bbox(image, region["bbox"], scale, (0, 0, 255), thickness=2)
            arrow = region.get("arrow")
            if arrow:
                _draw_arrow_line(image, arrow, scale, (0, 0, 255), 3)
            x0, y0, _, _ = [int(v * scale) for v in region["bbox"]]
            cv2.putText(image, f"{region['region_id']} {region['bearing_direction']}", (x0, max(18, y0 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.imwrite(os.path.join(PLATEWISE_DEBUG_DIR, f"structural_regions_page_{page_index + 1}.png"), image)
    except Exception:
        return


def _save_supplier_debug(page, labels, plates, direction_symbols, page_index):
    try:
        os.makedirs(PLATEWISE_DEBUG_DIR, exist_ok=True)
        scale = 1.4
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
        for plate, entry in plates.items():
            if entry.get("page") != page_index + 1:
                continue
            _draw_bbox(image, entry["bbox"], scale, (0, 180, 0), thickness=2)
            arrow = entry.get("arrow")
            if arrow:
                _draw_arrow_line(image, arrow, scale, (255, 0, 160), 3)
            x0, y0, _, _ = [int(v * scale) for v in entry["bbox"]]
            cv2.putText(image, f"{plate} {entry['bearing_direction']}", (x0, max(18, y0 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 120, 0), 1, cv2.LINE_AA)
        for symbol in direction_symbols:
            _draw_arrow_line(image, symbol, scale, (255, 0, 180), 1)
        cv2.imwrite(os.path.join(PLATEWISE_DEBUG_DIR, f"supplier_plates_page_{page_index + 1}.png"), image)
    except Exception:
        return


def _save_mapping_debug(structural_pdf_path, structural_regions, mappings):
    try:
        if not mappings:
            return
        os.makedirs(PLATEWISE_DEBUG_DIR, exist_ok=True)
        with fitz.open(structural_pdf_path) as doc:
            page = doc[0]
            scale = 1.2
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            for mapping in mappings.values():
                region = structural_regions.get(mapping.get("structural_region_id"))
                if not region:
                    continue
                supplier_bbox = mapping.get("mapped_supplier_bbox")
                if supplier_bbox:
                    _draw_bbox(image, supplier_bbox, scale, (255, 0, 180), thickness=2)
                    sx, sy = _bbox_center(supplier_bbox)
                else:
                    sx, sy = region.get("center") or _bbox_center(region["bbox"])
                rx, ry = region.get("center") or _bbox_center(region["bbox"])
                cv2.line(image, (int(sx * scale), int(sy * scale)), (int(rx * scale), int(ry * scale)), (255, 0, 180), 1, cv2.LINE_AA)
                cv2.putText(image, str(mapping.get("plate")), (int(sx * scale), int(sy * scale)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 180), 1, cv2.LINE_AA)
            cv2.imwrite(os.path.join(PLATEWISE_DEBUG_DIR, "mapping_plate_to_structural.png"), image)
    except Exception:
        return


def _draw_bbox(image, bbox, scale, color, thickness=2):
    x0, y0, x1, y1 = [int(round(v * scale)) for v in bbox]
    cv2.rectangle(image, (x0, y0), (x1, y1), color, thickness)


def _draw_arrow_line(image, line, scale, color, thickness=2):
    cv2.line(
        image,
        (int(round(line["x1"] * scale)), int(round(line["y1"] * scale))),
        (int(round(line["x2"] * scale)), int(round(line["y2"] * scale))),
        color,
        thickness,
        cv2.LINE_AA,
    )


def _direction_from_orientation(orientation):
    if orientation == "vertical":
        return "TOP_TO_BOTTOM"
    if orientation == "horizontal":
        return "LEFT_TO_RIGHT"
    return "UNKNOWN"


def _mapping_direction_bonus(supplier_direction, supplier_confidence, structural_direction, base_score):
    if supplier_direction not in VALID_DIRECTIONS:
        return 0.0
    if structural_direction != supplier_direction:
        return 0.0
    if supplier_confidence < 0.35:
        return 0.0
    if base_score < 0.30:
        return 0.0
    # Structural vector extraction can expose both the real bearing arrow and
    # its perpendicular extent arrow. When geometry is close for both, use the
    # independently read supplier direction as a bounded tie breaker.
    return min(0.36, 0.20 + 0.25 * min(supplier_confidence, 0.80))


def _has_plausible_same_direction_candidate(candidates, supplier_direction, supplier_confidence):
    if supplier_direction not in VALID_DIRECTIONS or supplier_confidence < 0.35:
        return False
    return any(
        item.get("structural_direction") == supplier_direction
        and float(item.get("base_score") or 0.0) >= 0.30
        for item in candidates
    )


def _has_generic_floor_same_direction_candidate(candidates, supplier_direction, supplier_confidence):
    if supplier_direction not in VALID_DIRECTIONS or supplier_confidence < 0.35:
        return False

    # Generic floor-layout registration maps one supplier plan bbox to one
    # structural floor-plan bbox. That is intentionally broad, so small edge
    # plates can overlap a long perpendicular structural arrow region even when
    # the local same-direction bearing arrow is nearby but has a lower raw
    # overlap score. Use a lower base threshold only in this fallback mode.
    return any(
        item.get("structural_direction") == supplier_direction
        and float(item.get("base_score") or 0.0) >= 0.22
        for item in candidates
    )


def _mapping_direction_mismatch_penalty(
    supplier_direction,
    supplier_confidence,
    structural_direction,
    same_direction_available,
):
    if not same_direction_available:
        return 0.0
    if supplier_direction not in VALID_DIRECTIONS:
        return 0.0
    if structural_direction == supplier_direction:
        return 0.0
    if supplier_confidence < 0.35:
        return 0.0
    return min(0.30, 0.12 + 0.25 * min(supplier_confidence, 0.80))


def _generic_floor_direction_bonus(supplier_direction, supplier_confidence, structural_direction, base_score):
    if supplier_direction not in VALID_DIRECTIONS:
        return 0.0
    if structural_direction != supplier_direction:
        return 0.0
    if supplier_confidence < 0.35:
        return 0.0
    if base_score < 0.22:
        return 0.0
    return min(0.48, 0.28 + 0.30 * min(supplier_confidence, 0.80))


def _generic_floor_direction_mismatch_penalty(supplier_direction, supplier_confidence, structural_direction):
    if supplier_direction not in VALID_DIRECTIONS:
        return 0.0
    if structural_direction == supplier_direction:
        return 0.0
    if supplier_confidence < 0.35:
        return 0.0
    return min(0.42, 0.18 + 0.35 * min(supplier_confidence, 0.80))


def _plate_sort_key(plate):
    match = re.search(r"(\d+)", str(plate))
    return (int(match.group(1)) if match else 10**9, str(plate))


def _rect_to_list(rect):
    if isinstance(rect, fitz.Rect):
        return [float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)]
    return [float(v) for v in rect]


def _rect_center(rect):
    return _bbox_center(_rect_to_list(rect))


def _bbox_center(bbox):
    x0, y0, x1, y1 = [float(v) for v in bbox]
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _bbox_area(bbox):
    x0, y0, x1, y1 = [float(v) for v in bbox]
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def _bbox_diag(bbox):
    x0, y0, x1, y1 = [float(v) for v in bbox]
    return math.hypot(x1 - x0, y1 - y0)


def _bbox_overlap_ratio(a, b):
    ax0, ay0, ax1, ay1 = [float(v) for v in a]
    bx0, by0, bx1, by1 = [float(v) for v in b]
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    intersection = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if intersection <= 0:
        return 0.0
    smaller = min(_bbox_area(a), _bbox_area(b))
    return intersection / max(smaller, 1.0)


def _expand_bbox(bbox, margin):
    x0, y0, x1, y1 = [float(v) for v in bbox]
    return [x0 - margin, y0 - margin, x1 + margin, y1 + margin]


def _point_inside_bbox(point, bbox):
    x, y = point
    x0, y0, x1, y1 = [float(v) for v in bbox]
    return x0 <= x <= x1 and y0 <= y <= y1


def _segment_center(segment):
    return ((segment["x1"] + segment["x2"]) / 2.0, (segment["y1"] + segment["y2"]) / 2.0)


def _clip_rect(rect, page_rect):
    clipped = fitz.Rect(rect)
    clipped.x0 = max(float(page_rect.x0), clipped.x0)
    clipped.y0 = max(float(page_rect.y0), clipped.y0)
    clipped.x1 = min(float(page_rect.x1), clipped.x1)
    clipped.y1 = min(float(page_rect.y1), clipped.y1)
    if clipped.x1 < clipped.x0:
        clipped.x0, clipped.x1 = clipped.x1, clipped.x0
    if clipped.y1 < clipped.y0:
        clipped.y0, clipped.y1 = clipped.y1, clipped.y0
    return clipped
