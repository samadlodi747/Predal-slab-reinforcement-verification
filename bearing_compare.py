"""Bearing-direction comparison helpers.

This module intentionally stays small: detection belongs in
``bearing_direction_detector.py`` and reporting belongs in the Flask app.
"""


VALID_DIRECTIONS = {"TOP_TO_BOTTOM", "LEFT_TO_RIGHT"}


def _normalize_direction(result):
    direction = str((result or {}).get("bearing_direction") or "UNKNOWN").upper()
    if direction in VALID_DIRECTIONS:
        return direction
    return "UNKNOWN"


def _confidence(result):
    try:
        return max(0.0, min(1.0, float((result or {}).get("confidence") or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def compare_bearing_direction(structural_result, supplier_result):
    """Compare structural and supplier slab bearing directions.

    The caller can pass the raw dictionaries returned by the detector. The
    returned shape is report-friendly and never raises on missing or partial
    detector output.
    """

    structural_direction = _normalize_direction(structural_result)
    supplier_direction = _normalize_direction(supplier_result)
    structural_confidence = _confidence(structural_result)
    supplier_confidence = _confidence(supplier_result)

    status = "OK" if (
        structural_direction in VALID_DIRECTIONS
        and structural_direction == supplier_direction
    ) else "MISMATCH"

    reason = ""
    if structural_direction == "UNKNOWN" or supplier_direction == "UNKNOWN":
        reason = "One or both bearing directions could not be detected reliably."
    elif status == "MISMATCH":
        reason = "Detected bearing directions are perpendicular or otherwise different."

    return {
        "structural_direction": structural_direction,
        "supplier_direction": supplier_direction,
        "status": status,
        "confidence": round(min(structural_confidence, supplier_confidence), 2),
        "structural_confidence": round(structural_confidence, 2),
        "supplier_confidence": round(supplier_confidence, 2),
        "structural_page": (structural_result or {}).get("page"),
        "supplier_page": (supplier_result or {}).get("page"),
        "structural_line_length": int((structural_result or {}).get("line_length") or 0),
        "supplier_line_length": int((supplier_result or {}).get("line_length") or 0),
        "reason": reason,
    }
