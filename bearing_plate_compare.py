"""Plate-wise bearing-direction comparison."""


VALID_DIRECTIONS = {"TOP_TO_BOTTOM", "LEFT_TO_RIGHT"}


def compare_plate_bearing_direction(structural_regions, supplier_regions, mapping):
    """Compare mapped supplier plates against structural local directions.

    Returns a report-friendly dictionary:

    {
        "rows": [
            {
                "plate": "47.G",
                "structural_direction": "LEFT_TO_RIGHT",
                "supplier_direction": "LEFT_TO_RIGHT",
                "status": "OK"
            }
        ],
        "summary": {...}
    }
    """

    rows = []
    for plate in sorted(supplier_regions or {}, key=_plate_sort_key):
        supplier_entry = (supplier_regions or {}).get(plate) or {}
        map_entry = (mapping or {}).get(plate) or {}
        structural_entry = (structural_regions or {}).get(map_entry.get("structural_region_id")) or {}

        structural_direction = _normalize_direction(
            map_entry.get("structural_direction") or structural_entry.get("bearing_direction")
        )
        supplier_direction = _normalize_direction(supplier_entry.get("bearing_direction"))
        status = "OK" if (
            structural_direction in VALID_DIRECTIONS
            and structural_direction == supplier_direction
        ) else "CHECK"

        rows.append(
            {
                "plate": plate,
                "structural_direction": structural_direction,
                "supplier_direction": supplier_direction,
                "status": status,
                "structural_region_id": map_entry.get("structural_region_id") or "-",
                "mapping_score": float(map_entry.get("score") or 0.0),
                "structural_confidence": float(structural_entry.get("confidence") or 0.0),
                "supplier_confidence": float(supplier_entry.get("confidence") or 0.0),
            }
        )

    ok_count = sum(1 for row in rows if row["status"] == "OK")
    check_count = sum(1 for row in rows if row["status"] != "OK")

    return {
        "rows": rows,
        "summary": {
            "total": len(rows),
            "ok": ok_count,
            "check": check_count,
        },
    }


def _normalize_direction(value):
    direction = str(value or "UNKNOWN").upper()
    return direction if direction in VALID_DIRECTIONS else "UNKNOWN"


def _plate_sort_key(plate):
    import re

    match = re.search(r"(\d+)", str(plate))
    return (int(match.group(1)) if match else 10**9, str(plate))
