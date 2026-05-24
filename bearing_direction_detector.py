"""Automatic slab bearing-direction detection for structural PDFs.

The detector looks for the drawing convention used in predal/slab plans:
one long filled black arrow and one perpendicular hollow extent arrow. The
filled arrow is the bearing direction. Raster detection is deliberately kept
separate from the existing text/reinforcement extraction pipeline.
"""

import math
import os

import cv2
import fitz
import numpy as np


DEBUG_DIR = "debug_bearing"
RENDER_SCALE = 4
VALID_DIRECTIONS = {"TOP_TO_BOTTOM", "LEFT_TO_RIGHT"}


def _unknown_result(page=None):
    return {
        "bearing_direction": "UNKNOWN",
        "confidence": 0.0,
        "page": page,
        "line_length": 0,
    }


def extract_structural_bearing_direction(pdf_path):
    """Detect the bearing direction in a structural drawing PDF.

    Structural drawings should contain the filled bearing arrow and the
    perpendicular hollow extent arrow. A strong filled arrow may still be
    accepted when the hollow arrow is too faint, but the confidence is capped.
    """

    return _extract_bearing_direction_from_pdf(
        pdf_path,
        source_label="structural",
        allow_directional_fallback=False,
    )


def extract_supplier_bearing_direction(pdf_path):
    """Detect the bearing direction in a supplier drawing PDF.

    Supplier sheets are often less consistent. Prefer the filled bearing arrow
    when available; otherwise use the strongest long directional arrow as a
    low-confidence fallback so report generation remains useful.
    """

    return _extract_bearing_direction_from_pdf(
        pdf_path,
        source_label="supplier",
        allow_directional_fallback=True,
    )


def detect_bearing_direction(page_image):
    """Detect a bearing direction from a single OpenCV image.

    ``page_image`` may be grayscale, BGR, RGB, or BGRA/RGBA. The public return
    intentionally exposes only the report-level fields requested by the app.
    """

    detection = _detect_bearing_direction_internal(
        page_image,
        allow_directional_fallback=True,
    )
    return _public_result(detection)


def _extract_bearing_direction_from_pdf(pdf_path, source_label, allow_directional_fallback):
    page_results = []

    try:
        with fitz.open(pdf_path) as doc:
            for page_number, page in enumerate(doc, start=1):
                try:
                    image_bgr = _page_to_bgr(page)
                    detection = _detect_bearing_direction_internal(
                        image_bgr,
                        allow_directional_fallback=allow_directional_fallback,
                    )
                    vector_detection = _detect_vector_bearing_direction(page, image_bgr)
                    detection = _choose_detection(detection, vector_detection)
                    detection["page"] = page_number
                    _save_debug_visualization(image_bgr, detection, page_number, source_label)
                    page_results.append(_public_result(detection))
                except Exception:
                    page_results.append(_unknown_result(page=page_number))
    except Exception:
        return _unknown_result()

    if not page_results:
        return _unknown_result()

    _apply_cross_page_consistency_boost(page_results)
    valid_results = [
        result for result in page_results
        if result.get("bearing_direction") in VALID_DIRECTIONS
    ]
    if not valid_results:
        return _unknown_result()

    valid_results.sort(
        key=lambda item: (
            float(item.get("confidence") or 0.0),
            int(item.get("line_length") or 0),
        ),
        reverse=True,
    )
    return valid_results[0]


def _page_to_bgr(page):
    pix = page.get_pixmap(matrix=fitz.Matrix(RENDER_SCALE, RENDER_SCALE), alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 1:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if pix.n == 3:
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
    if pix.n == 4:
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    return arr[:, :, :3].copy()


def _public_result(detection):
    if not detection:
        return _unknown_result()

    direction = str(detection.get("bearing_direction") or "UNKNOWN").upper()
    if direction not in VALID_DIRECTIONS:
        direction = "UNKNOWN"

    try:
        confidence = float(detection.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0

    try:
        line_length = int(round(float(detection.get("line_length") or 0.0)))
    except (TypeError, ValueError):
        line_length = 0

    return {
        "bearing_direction": direction,
        "confidence": round(max(0.0, min(1.0, confidence)), 2),
        "page": detection.get("page"),
        "line_length": line_length if direction != "UNKNOWN" else 0,
    }


def _apply_cross_page_consistency_boost(page_results):
    directions = [
        result.get("bearing_direction")
        for result in page_results
        if result.get("bearing_direction") in VALID_DIRECTIONS
        and float(result.get("confidence") or 0.0) >= 0.25
    ]
    if len(directions) < 2:
        return

    counts = {direction: directions.count(direction) for direction in set(directions)}
    majority_direction, majority_count = max(counts.items(), key=lambda item: item[1])
    if majority_count < 2:
        return

    boost = min(0.10, 0.04 * (majority_count - 1))
    for result in page_results:
        if result.get("bearing_direction") == majority_direction:
            result["confidence"] = round(
                min(1.0, float(result.get("confidence") or 0.0) + boost),
                2,
            )


def _detect_bearing_direction_internal(page_image, allow_directional_fallback):
    image_bgr = _as_bgr(page_image)
    height, width = image_bgr.shape[:2]
    if height < 80 or width < 80:
        return _unknown_result()

    mask = _preprocess_dark_neutral_mask(image_bgr)
    segments = _detect_long_axis_segments(mask, width, height)
    candidates = _build_line_candidates(segments, mask, width, height)
    if not candidates:
        return _unknown_result()

    pair_result = _select_filled_arrow_with_extent_pair(candidates, width, height)
    if pair_result:
        return pair_result

    filled_result = _select_strong_filled_arrow(candidates, width, height)
    if filled_result:
        return filled_result

    if allow_directional_fallback:
        return _select_supplier_directional_fallback(candidates, width, height)

    return _unknown_result()


def _choose_detection(image_detection, vector_detection):
    if not vector_detection or vector_detection.get("bearing_direction") not in VALID_DIRECTIONS:
        return image_detection
    if not image_detection or image_detection.get("bearing_direction") not in VALID_DIRECTIONS:
        return vector_detection

    image_conf = float(image_detection.get("confidence") or 0.0)
    vector_conf = float(vector_detection.get("confidence") or 0.0)
    if vector_conf > image_conf + 0.08 or image_conf < 0.55:
        return vector_detection
    return image_detection


def _detect_vector_bearing_direction(page, image_bgr):
    """Fallback for vector PDFs with explicit filled arrowhead polygons.

    The raster detector remains the primary path. This fallback is useful for
    CAD exports where filled half-arrowheads are tiny, crisp vector polygons
    that can be paired more reliably before checking the rendered shaft with
    OpenCV.
    """

    try:
        drawings = page.get_drawings()
    except Exception:
        return _unknown_result()

    page_rect = page.rect
    image_height, image_width = image_bgr.shape[:2]
    scale_x = image_width / max(float(page_rect.width), 1.0)
    scale_y = image_height / max(float(page_rect.height), 1.0)
    mask = _preprocess_dark_neutral_mask(image_bgr)
    heads = _collect_vector_filled_arrowheads(drawings, page_rect)
    if len(heads) < 2:
        return _unknown_result()

    best = None
    for orientation in ("vertical", "horizontal"):
        axis_size = float(page_rect.height if orientation == "vertical" else page_rect.width)
        min_length = axis_size * 0.15
        same_axis_tolerance = max(3.0, min(page_rect.width, page_rect.height) * 0.0022)
        orient_heads = [head for head in heads if head["orientation"] == orientation]

        for index, first in enumerate(orient_heads):
            for second in orient_heads[index + 1:]:
                if orientation == "vertical":
                    alignment_delta = abs(first["x"] - second["x"])
                    length_pdf = abs(first["y"] - second["y"])
                    if alignment_delta > same_axis_tolerance or length_pdf < min_length:
                        continue
                    x_pdf = (first["x"] + second["x"]) / 2.0
                    y1_pdf, y2_pdf = sorted((first["y"], second["y"]))
                    line = _normalize_segment(
                        x_pdf * scale_x,
                        y1_pdf * scale_y,
                        x_pdf * scale_x,
                        y2_pdf * scale_y,
                        "vertical",
                    )
                else:
                    alignment_delta = abs(first["y"] - second["y"])
                    length_pdf = abs(first["x"] - second["x"])
                    if alignment_delta > same_axis_tolerance or length_pdf < min_length:
                        continue
                    y_pdf = (first["y"] + second["y"]) / 2.0
                    x1_pdf, x2_pdf = sorted((first["x"], second["x"]))
                    line = _normalize_segment(
                        x1_pdf * scale_x,
                        y_pdf * scale_y,
                        x2_pdf * scale_x,
                        y_pdf * scale_y,
                        "horizontal",
                    )

                line_weight = _line_weight_score(mask, line, image_width, image_height)
                if line_weight < 0.055:
                    continue

                length_score = min(1.0, length_pdf / max(axis_size * 0.66, 1.0))
                alignment_score = max(0.0, 1.0 - alignment_delta / same_axis_tolerance)
                area_balance = min(first["area"], second["area"]) / max(first["area"], second["area"], 1.0)
                shape_score = min(first["shape_score"], second["shape_score"])
                title_penalty = _vector_title_block_penalty(line, image_width, image_height)

                confidence = (
                    0.32
                    + 0.25 * length_score
                    + 0.15 * alignment_score
                    + 0.12 * min(1.0, line_weight / 0.20)
                    + 0.10 * area_balance
                    + 0.06 * shape_score
                    - title_penalty
                )
                confidence = max(0.0, min(0.84, confidence))
                if confidence < 0.42:
                    continue

                result = {
                    "bearing_direction": _direction_from_orientation(orientation),
                    "confidence": confidence,
                    "line_length": line["length"],
                    "bearing_line": line,
                    "extent_line": None,
                }
                if not best or (
                    result["confidence"],
                    result["line_length"],
                ) > (
                    best["confidence"],
                    best["line_length"],
                ):
                    best = result

    return best or _unknown_result()


def _collect_vector_filled_arrowheads(drawings, page_rect):
    heads = []
    min_page_dim = min(float(page_rect.width), float(page_rect.height))
    min_head = max(0.8, min_page_dim * 0.00035)
    max_head = max(12.0, min_page_dim * 0.015)

    for drawing in drawings:
        fill = drawing.get("fill")
        rect = drawing.get("rect")
        if fill is None or rect is None:
            continue
        if not isinstance(fill, tuple) or len(fill) < 3:
            continue
        if sum(float(channel) for channel in fill[:3]) > 0.45:
            continue

        width = float(rect.width)
        height = float(rect.height)
        if width < min_head or height < min_head or width > max_head or height > max_head:
            continue

        long_side = max(width, height)
        short_side = max(min(width, height), 0.01)
        aspect = long_side / short_side
        if aspect < 1.65:
            continue

        items = drawing.get("items") or []
        if len(items) > 8:
            continue

        orientation = "vertical" if height >= width else "horizontal"
        compactness = min(1.0, max(0.0, (aspect - 1.65) / 4.0))
        size_score = min(1.0, long_side / max(min_page_dim * 0.003, 1.0))
        heads.append(
            {
                "x": (float(rect.x0) + float(rect.x1)) / 2.0,
                "y": (float(rect.y0) + float(rect.y1)) / 2.0,
                "area": max(width * height, 1.0),
                "orientation": orientation,
                "shape_score": 0.55 * compactness + 0.45 * size_score,
            }
        )

    return heads


def _vector_title_block_penalty(line, image_width, image_height):
    cx, cy = line["center"] if "center" in line else (
        (line["x1"] + line["x2"]) / 2.0,
        (line["y1"] + line["y2"]) / 2.0,
    )
    in_lower_right = cx > image_width * 0.70 and cy > image_height * 0.62
    near_bottom = cy > image_height * 0.90
    if in_lower_right:
        return 0.16
    if near_bottom:
        return 0.08
    return 0.0


def _as_bgr(page_image):
    arr = np.asarray(page_image)
    if arr.ndim == 2:
        return cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)
    if arr.ndim != 3:
        raise ValueError("page_image must be a grayscale or color image")
    if arr.shape[2] == 4:
        return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
    if arr.shape[2] == 3:
        return arr.copy()
    raise ValueError("page_image has an unsupported channel count")


def _preprocess_dark_neutral_mask(image_bgr):
    """Keep black/gray drawing geometry and suppress saturated annotations.

    Blue dashed reinforcement and red markup tend to have high saturation; the
    bearing/extent arrows are black or gray and remain in the mask.
    """

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]

    neutral_dark = ((value < 218) & (saturation < 95)) | (value < 80)
    gray_dark = gray < 210
    mask = np.where(neutral_dark & gray_dark, 255, 0).astype(np.uint8)

    # Close tiny export gaps in vector lines but keep thin hollow arrowheads.
    mask = cv2.medianBlur(mask, 3)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
    return mask


def _detect_long_axis_segments(mask, width, height):
    edges = cv2.Canny(mask, 50, 150, apertureSize=3)
    min_len = max(60, int(min(width, height) * 0.12))
    threshold = max(70, int(min(width, height) * 0.018))
    max_gap = max(18, int(min(width, height) * 0.010))

    raw = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=threshold,
        minLineLength=min_len,
        maxLineGap=max_gap,
    )

    if raw is None:
        raw = cv2.HoughLinesP(
            edges,
            rho=1,
            theta=np.pi / 180.0,
            threshold=max(35, threshold // 2),
            minLineLength=max(40, int(min_len * 0.75)),
            maxLineGap=max_gap * 2,
        )

    segments = []
    if raw is None:
        return segments

    for line in raw.reshape(-1, 4):
        x1, y1, x2, y2 = [int(v) for v in line]
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length <= 0:
            continue
        angle = abs(math.degrees(math.atan2(dy, dx))) % 180.0
        if angle <= 12.0 or angle >= 168.0:
            if length >= width * 0.15:
                segments.append(_normalize_segment(x1, y1, x2, y2, "horizontal"))
        elif 78.0 <= angle <= 102.0:
            if length >= height * 0.15:
                segments.append(_normalize_segment(x1, y1, x2, y2, "vertical"))

    merged = _merge_collinear_segments(segments, width, height)
    return _deduplicate_segments(segments + merged)


def _normalize_segment(x1, y1, x2, y2, orientation):
    if orientation == "horizontal" and x2 < x1:
        x1, y1, x2, y2 = x2, y2, x1, y1
    if orientation == "vertical" and y2 < y1:
        x1, y1, x2, y2 = x2, y2, x1, y1
    return {
        "x1": float(x1),
        "y1": float(y1),
        "x2": float(x2),
        "y2": float(y2),
        "orientation": orientation,
        "length": float(math.hypot(x2 - x1, y2 - y1)),
    }


def _merge_collinear_segments(segments, width, height):
    merged = []
    tolerance = max(10.0, min(width, height) * 0.006)

    for orientation in ("horizontal", "vertical"):
        orient_segments = [seg for seg in segments if seg["orientation"] == orientation]
        if not orient_segments:
            continue

        coord_key = "y1" if orientation == "horizontal" else "x1"
        span_start = "x1" if orientation == "horizontal" else "y1"
        span_end = "x2" if orientation == "horizontal" else "y2"
        max_gap = max(35.0, (width if orientation == "horizontal" else height) * 0.035)

        orient_segments.sort(key=lambda seg: (seg[coord_key], seg[span_start]))
        groups = []
        for segment in orient_segments:
            placed = False
            for group in groups:
                group_coord = np.mean([item[coord_key] for item in group])
                if abs(segment[coord_key] - group_coord) <= tolerance:
                    group.append(segment)
                    placed = True
                    break
            if not placed:
                groups.append([segment])

        for group in groups:
            group.sort(key=lambda seg: seg[span_start])
            cluster = []
            cluster_end = None
            for segment in group:
                if not cluster:
                    cluster = [segment]
                    cluster_end = segment[span_end]
                    continue
                if segment[span_start] - cluster_end <= max_gap:
                    cluster.append(segment)
                    cluster_end = max(cluster_end, segment[span_end])
                else:
                    merged_segment = _segment_from_cluster(cluster, orientation)
                    if merged_segment:
                        merged.append(merged_segment)
                    cluster = [segment]
                    cluster_end = segment[span_end]
            merged_segment = _segment_from_cluster(cluster, orientation)
            if merged_segment:
                merged.append(merged_segment)

    return merged


def _segment_from_cluster(cluster, orientation):
    if not cluster:
        return None
    if orientation == "horizontal":
        x1 = min(item["x1"] for item in cluster)
        x2 = max(item["x2"] for item in cluster)
        y = float(np.mean([(item["y1"] + item["y2"]) / 2.0 for item in cluster]))
        return _normalize_segment(x1, y, x2, y, orientation)

    y1 = min(item["y1"] for item in cluster)
    y2 = max(item["y2"] for item in cluster)
    x = float(np.mean([(item["x1"] + item["x2"]) / 2.0 for item in cluster]))
    return _normalize_segment(x, y1, x, y2, orientation)


def _deduplicate_segments(segments):
    unique = []
    for segment in sorted(segments, key=lambda seg: seg["length"], reverse=True):
        duplicate = False
        for existing in unique:
            if segment["orientation"] != existing["orientation"]:
                continue
            coord_delta = abs(
                ((segment["y1"] + segment["y2"]) - (existing["y1"] + existing["y2"])) / 2.0
                if segment["orientation"] == "horizontal"
                else ((segment["x1"] + segment["x2"]) - (existing["x1"] + existing["x2"])) / 2.0
            )
            start_delta = abs(
                segment["x1"] - existing["x1"]
                if segment["orientation"] == "horizontal"
                else segment["y1"] - existing["y1"]
            )
            end_delta = abs(
                segment["x2"] - existing["x2"]
                if segment["orientation"] == "horizontal"
                else segment["y2"] - existing["y2"]
            )
            if coord_delta < 12.0 and start_delta < 35.0 and end_delta < 35.0:
                duplicate = True
                break
        if not duplicate:
            unique.append(segment)
    return unique


def _build_line_candidates(segments, mask, width, height):
    candidates = []
    for segment in segments:
        orientation = segment["orientation"]
        length = segment["length"]
        if orientation == "horizontal" and length < width * 0.15:
            continue
        if orientation == "vertical" and length < height * 0.15:
            continue

        start = (segment["x1"], segment["y1"])
        end = (segment["x2"], segment["y2"])
        start_head = _classify_arrowhead(mask, start, orientation, (height, width))
        end_head = _classify_arrowhead(mask, end, orientation, (height, width))

        filled_score = _combine_end_scores(start_head["filled"], end_head["filled"])
        hollow_score = _combine_end_scores(start_head["hollow"], end_head["hollow"])
        line_weight = _line_weight_score(mask, segment, width, height)
        border_penalty = _border_penalty(segment, width, height)

        candidate = dict(segment)
        candidate.update(
            {
                "center": ((segment["x1"] + segment["x2"]) / 2.0, (segment["y1"] + segment["y2"]) / 2.0),
                "start_head": start_head,
                "end_head": end_head,
                "filled_score": filled_score,
                "hollow_score": hollow_score,
                "line_weight": line_weight,
                "border_penalty": border_penalty,
            }
        )
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item["filled_score"],
            item["hollow_score"],
            item["length"],
        ),
        reverse=True,
    )
    return candidates


def _combine_end_scores(score_a, score_b):
    high = max(score_a, score_b)
    low = min(score_a, score_b)
    return max(0.0, min(1.0, 0.65 * high + 0.35 * low))


def _classify_arrowhead(mask, endpoint, orientation, image_shape):
    """Classify the geometry near one line endpoint.

    Filled arrowheads produce compact dark triangular blobs after the shaft is
    removed. Hollow arrowheads keep mostly outlines, so their fill ratio is low
    and short diagonal strokes are present.
    """

    height, width = image_shape
    x, y = endpoint
    radius = int(max(26, min(width, height) * 0.016))
    x0 = max(0, int(round(x - radius)))
    x1 = min(width, int(round(x + radius + 1)))
    y0 = max(0, int(round(y - radius)))
    y1 = min(height, int(round(y + radius + 1)))
    if x1 <= x0 or y1 <= y0:
        return {"filled": 0.0, "hollow": 0.0}

    crop = mask[y0:y1, x0:x1].copy()
    local_x = int(round(x - x0))
    local_y = int(round(y - y0))
    original_density = cv2.countNonZero(crop) / float(max(1, crop.size))
    if original_density > 0.20:
        return {"filled": 0.0, "hollow": 0.0}
    clutter_factor = max(0.0, min(1.0, 1.0 - max(0.0, original_density - 0.055) / 0.095))

    # Erase the shaft itself so the contour logic focuses on the arrowhead.
    shaft = max(2, int(radius * 0.08))
    if orientation == "horizontal":
        cv2.line(crop, (0, local_y), (crop.shape[1] - 1, local_y), 0, thickness=shaft * 2 + 1)
    else:
        cv2.line(crop, (local_x, 0), (local_x, crop.shape[0] - 1), 0, thickness=shaft * 2 + 1)

    crop = cv2.morphologyEx(crop, cv2.MORPH_CLOSE, np.ones((2, 2), np.uint8), iterations=1)
    contours, _ = cv2.findContours(crop, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    best_filled = 0.0
    best_hollow = 0.0
    min_area = max(8.0, radius * radius * 0.010)
    max_bbox_area = (2 * radius + 1) * (2 * radius + 1) * 0.80

    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area:
            continue
        bx, by, bw, bh = cv2.boundingRect(contour)
        bbox_area = float(max(1, bw * bh))
        if bbox_area > max_bbox_area:
            continue
        if bw < 4 or bh < 4:
            continue
        if bx <= 1 or by <= 1 or bx + bw >= crop.shape[1] - 2 or by + bh >= crop.shape[0] - 2:
            continue

        aspect = bw / float(bh)
        if aspect < 0.14 or aspect > 7.0:
            continue

        contour_mask = np.zeros_like(crop)
        cv2.drawContours(contour_mask, [contour], -1, 255, thickness=-1)
        black_inside = cv2.countNonZero(cv2.bitwise_and(crop, contour_mask))
        fill_ratio = black_inside / max(area, 1.0)
        bbox_density = cv2.countNonZero(crop[by:by + bh, bx:bx + bw]) / bbox_area
        area_bbox_ratio = area / bbox_area
        moments = cv2.moments(contour)
        if moments["m00"]:
            contour_cx = moments["m10"] / moments["m00"]
            contour_cy = moments["m01"] / moments["m00"]
        else:
            contour_cx = bx + bw / 2.0
            contour_cy = by + bh / 2.0
        if orientation == "horizontal":
            axis_offset = abs(contour_cy - local_y) / float(max(radius, 1))
        else:
            axis_offset = abs(contour_cx - local_x) / float(max(radius, 1))
        if axis_offset > 0.52:
            continue

        hull = cv2.convexHull(contour)
        hull_area = max(float(cv2.contourArea(hull)), 1.0)
        solidity = min(1.0, area / hull_area)
        approx = cv2.approxPolyDP(contour, 0.09 * cv2.arcLength(contour, True), True)
        polygon_score = 1.0 if 3 <= len(approx) <= 6 else 0.45
        size_score = min(1.0, math.sqrt(bbox_area) / max(radius * 0.70, 1.0))

        filled = (
            0.42 * min(1.0, fill_ratio / 0.80)
            + 0.25 * min(1.0, bbox_density / 0.45)
            + 0.18 * solidity
            + 0.15 * polygon_score
        ) * size_score * clutter_factor

        hollow = (
            0.45 * max(0.0, 1.0 - min(1.0, bbox_density / 0.30))
            + 0.25 * polygon_score
            + 0.20 * size_score
            + 0.10 * min(1.0, area / max(radius * radius * 0.05, 1.0))
        ) * max(0.35, clutter_factor)

        if 0.22 <= bbox_density <= 0.82 and 0.16 <= area_bbox_ratio <= 0.72 and fill_ratio >= 0.45:
            best_filled = max(best_filled, filled)
        if bbox_density < 0.30:
            best_hollow = max(best_hollow, hollow)

    diagonal_score = _endpoint_diagonal_stroke_score(crop)
    if diagonal_score > 0:
        best_hollow = max(best_hollow, (0.35 + 0.45 * diagonal_score) * max(0.35, clutter_factor))

    return {
        "filled": round(max(0.0, min(1.0, best_filled)), 3),
        "hollow": round(max(0.0, min(1.0, best_hollow)), 3),
    }


def _endpoint_diagonal_stroke_score(crop):
    if crop.size == 0 or cv2.countNonZero(crop) < 8:
        return 0.0

    edges = cv2.Canny(crop, 40, 130)
    min_len = max(6, int(min(crop.shape[:2]) * 0.22))
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180.0,
        threshold=max(6, int(min(crop.shape[:2]) * 0.10)),
        minLineLength=min_len,
        maxLineGap=4,
    )
    if lines is None:
        return 0.0

    diagonals = 0
    for line in lines.reshape(-1, 4):
        x1, y1, x2, y2 = [int(v) for v in line]
        angle = abs(math.degrees(math.atan2(y2 - y1, x2 - x1))) % 180.0
        if 18.0 <= angle <= 72.0 or 108.0 <= angle <= 162.0:
            diagonals += 1
    return min(1.0, diagonals / 2.0)


def _line_weight_score(mask, segment, width, height):
    line_mask = np.zeros(mask.shape[:2], dtype=np.uint8)
    band = max(5, int(min(width, height) * 0.0035))
    cv2.line(
        line_mask,
        (int(round(segment["x1"])), int(round(segment["y1"]))),
        (int(round(segment["x2"])), int(round(segment["y2"]))),
        255,
        thickness=band,
    )
    dark_pixels = cv2.countNonZero(cv2.bitwise_and(mask, line_mask))
    expected = max(1.0, segment["length"] * band)
    density = dark_pixels / expected
    return round(max(0.0, min(1.0, density / 0.65)), 3)


def _border_penalty(segment, width, height):
    margin = min(width, height) * 0.025
    cx, cy = (segment["x1"] + segment["x2"]) / 2.0, (segment["y1"] + segment["y2"]) / 2.0
    if cx < margin or cx > width - margin or cy < margin or cy > height - margin:
        return 0.25
    return 0.0


def _select_filled_arrow_with_extent_pair(candidates, width, height):
    best = None
    filled_candidates = [
        item for item in candidates
        if item["filled_score"] >= 0.34
        and item["length"] >= (height * 0.15 if item["orientation"] == "vertical" else width * 0.15)
    ]
    extent_candidates = [
        item for item in candidates
        if item["hollow_score"] >= 0.24 or item["filled_score"] < 0.30
    ]

    for bearing in filled_candidates:
        for extent in extent_candidates:
            if bearing is extent:
                continue
            if bearing["orientation"] == extent["orientation"]:
                continue

            pair_score = _perpendicular_pair_score(bearing, extent, width, height)
            if pair_score <= 0.0:
                continue

            axis_size = height if bearing["orientation"] == "vertical" else width
            length_score = min(1.0, bearing["length"] / max(axis_size * 0.65, 1.0))
            end_balance = min(bearing["start_head"]["filled"], bearing["end_head"]["filled"])
            confidence = (
                0.36 * bearing["filled_score"]
                + 0.22 * pair_score
                + 0.18 * length_score
                + 0.12 * bearing["line_weight"]
                + 0.12 * min(1.0, end_balance / 0.45)
                - bearing["border_penalty"]
            )
            confidence = max(0.0, min(0.98, confidence))
            if confidence < 0.38:
                continue

            result = {
                "bearing_direction": _direction_from_orientation(bearing["orientation"]),
                "confidence": confidence,
                "line_length": bearing["length"],
                "bearing_line": bearing,
                "extent_line": extent,
            }
            if not best or result["confidence"] > best["confidence"]:
                best = result

    return best


def _perpendicular_pair_score(bearing, extent, width, height):
    if bearing["orientation"] == "vertical":
        vertical = bearing
        horizontal = extent
    else:
        vertical = extent
        horizontal = bearing

    x_intersect = vertical["x1"]
    y_intersect = horizontal["y1"]
    margin = min(width, height) * 0.035
    on_vertical = vertical["y1"] - margin <= y_intersect <= vertical["y2"] + margin
    on_horizontal = horizontal["x1"] - margin <= x_intersect <= horizontal["x2"] + margin
    if not (on_vertical and on_horizontal):
        return 0.0

    bx, by = bearing["center"]
    ex, ey = extent["center"]
    center_distance = math.hypot(bx - ex, by - ey)
    diag = math.hypot(width, height)
    center_score = max(0.0, 1.0 - center_distance / max(diag * 0.28, 1.0))
    intersection_score = 1.0
    hollow_or_extent_score = max(extent["hollow_score"], 0.30 if extent["filled_score"] < 0.30 else 0.0)
    length_balance = min(bearing["length"], extent["length"]) / max(max(bearing["length"], extent["length"]), 1.0)

    return max(
        0.0,
        min(
            1.0,
            0.36 * intersection_score
            + 0.28 * center_score
            + 0.22 * min(1.0, hollow_or_extent_score / 0.45)
            + 0.14 * length_balance,
        ),
    )


def _select_strong_filled_arrow(candidates, width, height):
    best = None
    for bearing in candidates:
        axis_size = height if bearing["orientation"] == "vertical" else width
        length_score = min(1.0, bearing["length"] / max(axis_size * 0.65, 1.0))
        end_balance = min(bearing["start_head"]["filled"], bearing["end_head"]["filled"])
        confidence = (
            0.52 * bearing["filled_score"]
            + 0.20 * length_score
            + 0.15 * bearing["line_weight"]
            + 0.13 * min(1.0, end_balance / 0.42)
            - bearing["border_penalty"]
        )
        confidence = max(0.0, min(0.62, confidence))
        if bearing["filled_score"] < 0.38 or confidence < 0.34:
            continue
        result = {
            "bearing_direction": _direction_from_orientation(bearing["orientation"]),
            "confidence": confidence,
            "line_length": bearing["length"],
            "bearing_line": bearing,
            "extent_line": None,
        }
        if not best or result["confidence"] > best["confidence"]:
            best = result
    return best


def _select_supplier_directional_fallback(candidates, width, height):
    best = None
    for candidate in candidates:
        axis_size = height if candidate["orientation"] == "vertical" else width
        length_score = min(1.0, candidate["length"] / max(axis_size * 0.70, 1.0))
        arrow_score = max(candidate["filled_score"], candidate["hollow_score"] * 0.75)
        confidence = (
            0.40 * arrow_score
            + 0.30 * length_score
            + 0.20 * candidate["line_weight"]
            - candidate["border_penalty"]
        )
        confidence = max(0.0, min(0.46, confidence))
        if confidence < 0.26:
            continue
        result = {
            "bearing_direction": _direction_from_orientation(candidate["orientation"]),
            "confidence": confidence,
            "line_length": candidate["length"],
            "bearing_line": candidate,
            "extent_line": None,
        }
        if not best or result["confidence"] > best["confidence"]:
            best = result
    return best or _unknown_result()


def _direction_from_orientation(orientation):
    if orientation == "vertical":
        return "TOP_TO_BOTTOM"
    if orientation == "horizontal":
        return "LEFT_TO_RIGHT"
    return "UNKNOWN"


def _save_debug_visualization(image_bgr, detection, page_number, source_label):
    try:
        os.makedirs(DEBUG_DIR, exist_ok=True)
        debug = image_bgr.copy()
        height, width = debug.shape[:2]
        thickness = max(4, int(min(width, height) * 0.003))

        bearing = detection.get("bearing_line") if detection else None
        extent = detection.get("extent_line") if detection else None

        if extent:
            _draw_candidate_line(debug, extent, (0, 170, 0), thickness)
        if bearing:
            _draw_candidate_line(debug, bearing, (0, 0, 255), thickness + 1)

        label = f"{detection.get('bearing_direction', 'UNKNOWN')}  conf={float(detection.get('confidence') or 0.0):.2f}"
        cv2.rectangle(debug, (20, 20), (min(width - 20, 820), 92), (255, 255, 255), thickness=-1)
        cv2.putText(
            debug,
            label,
            (34, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            max(0.8, min(width, height) / 1800.0),
            (0, 0, 255) if bearing else (0, 120, 255),
            max(2, thickness // 2),
            cv2.LINE_AA,
        )

        max_dim = max(width, height)
        if max_dim > 2200:
            scale = 2200.0 / float(max_dim)
            debug = cv2.resize(debug, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        filename = f"{source_label}_page_{page_number}_detected.png"
        cv2.imwrite(os.path.join(DEBUG_DIR, filename), debug)
        if source_label == "structural":
            cv2.imwrite(os.path.join(DEBUG_DIR, f"page_{page_number}_detected.png"), debug)
    except Exception:
        # Debug output should never block verification/report generation.
        return


def _draw_candidate_line(image, candidate, color, thickness):
    cv2.line(
        image,
        (int(round(candidate["x1"])), int(round(candidate["y1"]))),
        (int(round(candidate["x2"])), int(round(candidate["y2"]))),
        color,
        thickness=thickness,
        lineType=cv2.LINE_AA,
    )
