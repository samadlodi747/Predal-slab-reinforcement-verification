
import io
import math
import os
import re
from statistics import mean

import fitz
from flask import Flask, render_template_string, request, send_file
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Predal Reinforcement Verifier</title>
  <style>
    body { font-family: Arial, sans-serif; background:#f5f7fb; color:#1c2430; margin:0; }
    .wrap { max-width: 980px; margin: 32px auto; background:#fff; border:1px solid #d9e2ec; border-radius:16px; box-shadow:0 12px 28px rgba(0,0,0,.05); overflow:hidden; }
    .hero { padding: 28px 32px; background:#163A63; color:#fff; }
    .hero h1 { margin:0 0 8px; font-size:28px; }
    .hero p { margin:0; line-height:1.45; opacity:.95; }
    .body { padding: 28px 32px; }
    .grid { display:grid; grid-template-columns:1fr 1fr; gap:18px; }
    .field { margin-bottom:18px; }
    label { display:block; font-weight:700; margin-bottom:8px; }
    input[type="text"], input[type="file"] {
      width:100%; box-sizing:border-box; border:1px solid #c8d4e3; border-radius:10px;
      padding:12px 14px; background:#fff;
    }
    .note {
      background:#f3f7fb; border-left:4px solid #4a6fa1; padding:14px 16px; border-radius:8px; line-height:1.45; margin:18px 0;
    }
    button {
      background:#163A63; color:#fff; border:none; border-radius:10px; padding:12px 18px;
      font-size:15px; font-weight:700; cursor:pointer;
    }
    button:hover { background:#1d4a7d; }
    ul { margin:10px 0 0 18px; line-height:1.5; }
    .footer { color:#5a6b7f; font-size:13px; margin-top:14px; }
    code { background:#eef3f8; padding:2px 6px; border-radius:6px; }
    @media (max-width: 760px) { .grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <h1>Predal Reinforcement Verifier</h1>
      <p>Upload a structural design Predal reinforcement PDF and a supplier Predal legplan/shop drawing PDF. The app generates an A3 landscape verification report in PDF format.</p>
    </div>
    <div class="body">
      <form method="post" action="/generate" enctype="multipart/form-data">
        <div class="field">
          <label for="project_title">Project title (optional)</label>
          <input type="text" id="project_title" name="project_title" placeholder="Example: 50 appartementen Abeelstraat - Blok A - Afdek +1">
        </div>
        <div class="grid">
          <div class="field">
            <label for="design_pdf">Structural design PDF</label>
            <input type="file" id="design_pdf" name="design_pdf" accept="application/pdf" required>
          </div>
          <div class="field">
            <label for="supplier_pdf">Supplier Predal PDF</label>
            <input type="file" id="supplier_pdf" name="supplier_pdf" accept="application/pdf" required>
          </div>
        </div>

        <div class="note">
          <strong>Multi-supplier parsing</strong>
          <ul>
            <li>Supplier format is auto-detected where possible.</li>
            <li>Dedicated parsers are included for tabular Predalco / IBO-type sheets and Oeterbeton / drawing-embedded sheets.</li>
            <li>A generic drawing fallback tries to read plate labels, plate sizes, and reinforcement labels from spatial PDF text blocks.</li>
          </ul>
        </div>

        <div class="note">
          <strong>Important engineering limitation</strong><br>
          If the design PDF does not expose reinforcement zones as machine-readable plate-by-plate data, the tool falls back to <em>reinforcement-family matching + sanity checks</em>. Visual zone overlay still needs engineer review before final approval.
        </div>

        <button type="submit">Generate verification PDF</button>
        <div class="footer">Dependencies: Flask, PyMuPDF, ReportLab</div>
      </form>
    </div>
  </div>
</body>
</html>
"""


def read_pdf(pdf_path):
    doc = fitz.open(pdf_path)
    pages = []
    full_text_parts = []
    for page in doc:
        blocks = page.get_text("blocks", sort=True)
        words = page.get_text("words")
        text = page.get_text("text", sort=True)
        pages.append({"blocks": blocks, "words": words, "text": text})
        full_text_parts.append(text)
    return pages, "\n".join(full_text_parts)



def clean_spaces(s):
    return re.sub(r"[ \t]+", " ", s or "").strip()


def normalize_storey_key(text):
    txt = (text or "").upper()
    compact = re.sub(r"\s+", "", txt)
    if "FUNDERINGSPLAAT" in compact or "FUNDERING" in compact:
        return "FOUNDATION"
    for pat in [r"NIV\+?(-?\d+)", r"BOVEN\+?(-?\d+)", r"NIVEAU\+?(-?\d+)", r"LEVEL\+?(-?\d+)"]:
        m = re.search(pat, compact)
        if m:
            return f"LEVEL_{m.group(1)}"
    return None


def _family_pattern():
    return re.compile(
        r"HW\s*([0-9]+(?:[\.,][0-9]+)?)\s*cm[²2]/l[mn]"
        r"\s*DW\s*([0-9]+(?:[\.,][0-9]+)?)\s*cm[²2]/l[mn]"
        r"(?:\s*(?:B\d+-150)\s*)?"
        r"(?:\s*VW\s*d\s*(\d+)\s*a\s*(\d+)\s*cm?\s*L\s*=?\s*([0-9]+)\s*cm)?",
        re.I | re.S,
    )


def _parse_design_families_from_text(text):
    families = set()
    pat = _family_pattern()
    normalized = clean_spaces((text or "").replace(",", "."))
    for m in pat.finditer(normalized):
        hw = float(m.group(1))
        dw = float(m.group(2))
        vw_d = int(m.group(3)) if m.group(3) else None
        vw_a = int(m.group(4)) if m.group(4) else None
        vw_l = int(m.group(5)) if m.group(5) else None
        families.add((hw, dw, vw_d, vw_l))
    return families


def extract_design_data(pdf_path, supplier_full_text=None):
    pages, full_text = read_pdf(pdf_path)

    families = set()

    # Primary extraction: page blocks
    for page in pages:
        for block in page["blocks"]:
            block_text = clean_spaces(block[4])
            families |= _parse_design_families_from_text(block_text)

    # Fallback extraction: full page text (important when OCR/blocks split or spacing differs like "a 15cm")
    if not families:
        families |= _parse_design_families_from_text(full_text)

    concrete = None
    steel = None
    top_mesh = None
    fire_req = None

    concrete_match = re.search(r"ALGEMEENHEDEN BOVENBOUW.*?betonkwaliteit:\s*(C\d+/\d+)", full_text, re.S | re.I)
    if concrete_match:
        concrete = concrete_match.group(1).upper()

    steel_match = re.search(r"ALGEMEENHEDEN BOVENBOUW.*?wapeningskwaliteit:\s*([A-Z0-9]+)", full_text, re.S | re.I)
    if steel_match:
        steel = steel_match.group(1).upper()

    mesh_hits = re.findall(r'B\d+-150', full_text, re.I)
    if mesh_hits:
        top_mesh = sorted({m.upper() for m in mesh_hits})[0]

    fire_match = re.search(r"Brandweerstand:\s*([^\n]+)", full_text, re.I)
    if fire_match:
        fire_req = clean_spaces(fire_match.group(1))

    slab_notes = sorted(set(re.findall(r"Predallen\s+\d\+\d+", full_text, re.I)))
    supplier_det_note = "supplier" if re.search(r"Dikte van de predalplaat.*leverancier", full_text, re.I) else None

    return {
        "families": sorted(families),
        "concrete": concrete,
        "steel": steel,
        "top_mesh": top_mesh,
        "fire_req": fire_req,
        "slab_notes": slab_notes,
        "supplier_det_note": supplier_det_note,
        "full_text": full_text,
        "storey_hint": normalize_storey_key(supplier_full_text or ""),
    }


def detect_supplier_format(full_text):
    txt = full_text.lower()
    if "oeterbeton" in txt or "o e t e r" in txt:
        return "oeterbeton_drawing"
    if "inclusief tralies" in txt and "glad" in txt and "rei" in txt:
        return "predalco_table"
    return "generic_drawing"


def parse_common_supplier_meta(full_text):
    concrete = None
    concrete_matches = re.findall(r"\bC\d+/\d+\b", full_text, re.I)
    if concrete_matches:
        concrete = concrete_matches[0].upper()

    steel = None
    steel_patterns = [
        r"Wapening\s*:\s*staalkwaliteit\s*([A-Z0-9 ]+(?:of[A-Z0-9 ]+)?)",
        r"staalkwaliteit\s*(DE\s*500\s*BS|BE\s*500(?:ES|BS)?|BE500(?:ES|BS)?)",
        r"kwaliteit d[' ]acier\s*(DE\s*500\s*BS|BE\s*500(?:ES|BS)?)",
    ]
    for pat in steel_patterns:
        m = re.search(pat, full_text, re.I)
        if m:
            steel = clean_spaces(m.group(1)).upper().replace(" ", "")
            break

    top_mesh_note = None
    for pat in [r"Bovenwapening\s*:\s*([^\n]+)", r"Armatures sup[ée]rieures\s*:\s*([^\n]+)"]:
        m = re.search(pat, full_text, re.I)
        if m:
            top_mesh_note = clean_spaces(m.group(1))
            break

    fire = None
    m = re.search(r"(REI\s*\d+)", full_text, re.I)
    if m:
        fire = clean_spaces(m.group(1)).upper()

    return {"concrete": concrete, "supplier_steel": steel, "top_mesh_note": top_mesh_note, "fire_default": fire}


def finalize_row(row):
    row["langs_cm2m"] = round(row["langs_mm2m"] / 100.0, 2)
    row["dwars_cm2m"] = round(row["dwars_mm2m"] / 100.0, 2)
    row["plate_size"] = f"{row['length']} x {row['width']}"
    return row


def parse_predalco_table(pages, full_text):
    meta = parse_common_supplier_meta(full_text)
    rows = []

    for page in pages:
        for block in page["blocks"]:
            lines = [ln.strip() for ln in block[4].splitlines() if ln.strip()]
            glad_idx = next((i for i, ln in enumerate(lines) if ln.lower() == "glad"), None)
            rei_idx = next((i for i, ln in enumerate(lines) if re.fullmatch(r"REI\s*\d+", ln, re.I)), None)
            if glad_idx is None or rei_idx is None or glad_idx >= rei_idx:
                continue

            pre = lines[:glad_idx]
            post = lines[glad_idx + 1 : rei_idx]

            if len(pre) < 10:
                continue
            if not all(re.fullmatch(r"\d+", token) for token in pre[1:10]):
                continue

            nums_after_glad = [int(v) for v in post if re.fullmatch(r"\d+", v)]
            cover = nums_after_glad[-1] if nums_after_glad else None
            uws = nums_after_glad[:-1] if len(nums_after_glad) >= 1 else []
            fire_line = lines[rei_idx]

            try:
                row = {
                    "plate": int(pre[4]),
                    "article": int(pre[1]),
                    "tralie_h": int(pre[2]),
                    "floor_thk": int(pre[3]),
                    "length": int(pre[5]),
                    "predal_thk": int(pre[6]),
                    "width": int(pre[7]),
                    "langs_mm2m": int(pre[8]),
                    "dwars_mm2m": int(pre[9]),
                    "weight_kg": int(pre[10]) if len(pre) > 10 and re.fullmatch(r"\d+", pre[10]) else None,
                    "type": pre[0],
                    "uw1": uws[0] if len(uws) > 0 else None,
                    "uw2": uws[1] if len(uws) > 1 else None,
                    "cover": cover,
                    "fire": clean_spaces(fire_line).upper(),
                    "env": lines[rei_idx + 1] if len(lines) > rei_idx + 1 else None,
                    "concrete": clean_spaces(lines[rei_idx + 2]).upper() if len(lines) > rei_idx + 2 else meta["concrete"],
                    "supplier_format": "Predalco / IBO tabular parser",
                }
            except Exception:
                continue
            rows.append(finalize_row(row))

    rows.sort(key=lambda x: x["plate"])
    meta["rows"] = rows
    meta["supplier_format"] = "Predalco / IBO tabular parser"
    return meta


def _center_from_block(block):
    x0, y0, x1, y1 = block[:4]
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _parse_plate_label_blocks(blocks):
    out = []
    for block in blocks:
        t = block[4].strip()
        m = re.fullmatch(r"(\d{2,3})\s*\n([A-Z]\d+(?:-\d+)+)", t)
        if m:
            out.append(
                {
                    "plate": int(m.group(1)),
                    "code": m.group(2),
                    "block": block,
                    "center": _center_from_block(block),
                }
            )
    return out


def _parse_size_blocks(blocks):
    out = []
    for block in blocks:
        t = block[4].strip()
        m = re.fullmatch(r"(\d{3,5})\s*\n(\d{3,4})\s*\n(\d{2,4})", t)
        if not m:
            continue
        length, width, kg = map(int, m.groups())
        if length < 500 or width < 300 or length < width:
            continue
        out.append(
            {
                "length": length,
                "width": width,
                "weight_kg": kg,
                "block": block,
                "center": _center_from_block(block),
            }
        )
    return out


def _parse_reinf_blocks(blocks):
    out = []
    for block in blocks:
        t = block[4].strip()
        m = re.fullmatch(r"(\d{3,4})\s*\n(\d{3,4})", t)
        if not m:
            continue
        langs, dwars = map(int, m.groups())
        if langs < 250 or langs > 2500 or dwars < 250 or dwars > 1200:
            continue
        if langs < dwars:
            continue
        out.append(
            {
                "langs_mm2m": langs,
                "dwars_mm2m": dwars,
                "block": block,
                "center": _center_from_block(block),
            }
        )
    return out


def _greedy_assign_unique(plates, candidates):
    remaining = set(range(len(candidates)))
    assignments = {}
    for p in sorted(plates, key=lambda item: (item["center"][1], item["center"][0])):
        if not remaining:
            break
        ranked = []
        for i in remaining:
            cx, cy = candidates[i]["center"]
            px, py = p["center"]
            dist = math.hypot(px - cx, py - cy)
            ranked.append((dist, i))
        ranked.sort(key=lambda t: t[0])
        assignments[p["plate"]] = candidates[ranked[0][1]]
        remaining.remove(ranked[0][1])
    return assignments


def _nearest_reinforcement(center, reinforcements):
    px, py = center
    ranked = []
    for item in reinforcements:
        cx, cy = item["center"]
        dist = math.hypot(px - cx, py - cy)
        ranked.append((dist, item))
    ranked.sort(key=lambda t: t[0])
    return ranked[0][1] if ranked else None


def parse_drawing_supplier(pages, full_text, supplier_label):
    meta = parse_common_supplier_meta(full_text)
    plates = []
    size_blocks = []
    rein_blocks = []

    for page in pages:
        blocks = page["blocks"]
        page_plates = [p for p in _parse_plate_label_blocks(blocks) if p["center"][1] > 250]
        if not page_plates:
            continue

        min_x = min(p["block"][0] for p in page_plates) - 240
        max_x = max(p["block"][2] for p in page_plates) + 240
        min_y = min(p["block"][1] for p in page_plates) - 180
        max_y = max(p["block"][3] for p in page_plates) + 220

        def in_region(block):
            x0, y0, x1, y1 = block[:4]
            return x0 >= min_x and x1 <= max_x and y0 >= min_y and y1 <= max_y

        candidate_blocks = [b for b in blocks if in_region(b)]
        plates.extend(page_plates)
        size_blocks.extend(_parse_size_blocks(candidate_blocks))
        rein_blocks.extend(_parse_reinf_blocks(candidate_blocks))

    if not plates or not size_blocks:
        return {**meta, "rows": [], "supplier_format": supplier_label}

    size_assignments = _greedy_assign_unique(plates, size_blocks)
    rows = []

    for plate in sorted(plates, key=lambda x: x["plate"]):
        size = size_assignments.get(plate["plate"])
        if not size:
            continue
        # Use the assigned size block center as the primary anchor for reinforcement lookup.
        # In drawing-based supplier PDFs (e.g. Oeterbeton), the plate label is often placed near
        # a boundary between adjacent plates, while the size block sits inside the actual plate area.
        # Looking up the nearest reinforcement from the label center can therefore snap a boundary
        # plate to a neighbouring reinforcement note (plate 23 in the Wilselsesteenweg case).
        # The size block center is a more stable proxy for the plate interior.
        rein_anchor = size["center"]
        rein = _nearest_reinforcement(rein_anchor, rein_blocks)
        if not rein:
            continue

        predal_thk = None
        floor_thk = None
        code_match = re.match(r"[A-Z](\d+)-(\d+)", plate["code"])
        if code_match:
            predal_thk = int(code_match.group(1))
            floor_thk = int(code_match.group(2))

        row = {
            "plate": plate["plate"],
            "article": None,
            "tralie_h": None,
            "floor_thk": floor_thk,
            "length": size["length"],
            "predal_thk": predal_thk,
            "width": size["width"],
            "langs_mm2m": rein["langs_mm2m"],
            "dwars_mm2m": rein["dwars_mm2m"],
            "weight_kg": size["weight_kg"],
            "type": plate["code"],
            "uw1": None,
            "uw2": None,
            "cover": None,
            "fire": meta["fire_default"],
            "env": None,
            "concrete": meta["concrete"],
            "supplier_format": supplier_label,
        }
        rows.append(finalize_row(row))

    rows.sort(key=lambda x: x["plate"])
    meta["rows"] = rows
    meta["supplier_format"] = supplier_label
    return meta


def extract_supplier_data(pdf_path):
    pages, full_text = read_pdf(pdf_path)
    supplier_format = detect_supplier_format(full_text)

    predalco_data = parse_predalco_table(pages, full_text)
    if predalco_data["rows"]:
        data = predalco_data
        supplier_format = "predalco_table"
    elif supplier_format == "oeterbeton_drawing":
        data = parse_drawing_supplier(pages, full_text, "Oeterbeton drawing parser")
    else:
        data = parse_drawing_supplier(pages, full_text, "Generic drawing parser")

    data["full_text"] = full_text
    data["detected_supplier_format"] = supplier_format
    return data


def build_report_pdf_bytes(design, supplier, project_title=""):
    rows = supplier["rows"]
    design_family_map = {(hw, dw): (vw_d, vw_l) for hw, dw, vw_d, vw_l in design["families"]}

    comparison_rows = []
    exact_ok = 0
    for row in rows:
        pair = (row["langs_cm2m"], row["dwars_cm2m"])
        is_exact = pair in design_family_map
        row["status"] = "OK" if is_exact else "CHECK"
        if is_exact:
            exact_ok += 1
        comparison_rows.append(
            [
                str(row["plate"]),
                row["plate_size"],
                (
                    f"HW {row['langs_cm2m']:.2f} / DW {row['dwars_cm2m']:.2f}"
                    if is_exact
                    else "No exact family found on design sheet"
                ),
                f"Langs {row['langs_mm2m']} / Dwars {row['dwars_mm2m']}",
                row["status"],
            ]
        )

    predal_thicknesses = sorted({row["predal_thk"] for row in rows if row.get("predal_thk") is not None})
    total_thicknesses = sorted({row["floor_thk"] for row in rows if row.get("floor_thk") is not None})
    supplier_concretes = sorted({str(row["concrete"]).upper() for row in rows if row.get("concrete")})
    supplier_fires = sorted({str(row["fire"]).upper() for row in rows if row.get("fire")})

    concrete_status = "OK" if design["concrete"] and supplier_concretes and all(c == design["concrete"] for c in supplier_concretes) else "CHECK"
    steel_status = "OK" if design["steel"] and supplier["supplier_steel"] and design["steel"] in supplier["supplier_steel"] else "CHECK"
    predal_status = "OK" if predal_thicknesses else "CHECK"
    total_status = "CHECK" if total_thicknesses else "CHECK"
    mesh_status = "CHECK"
    fire_status = "CHECK"

    global_rows = [
        ["Detected supplier parser", "Auto detection", supplier.get("supplier_format", "Not found"), "OK" if rows else "CHECK"],
        ["Concrete class", f"{design['concrete'] or 'Not found'} minimum", ", ".join(supplier_concretes) or "Not found", concrete_status],
        ["Steel grade", design["steel"] or "Not found", supplier["supplier_steel"] or "Not found", steel_status],
        ["Predal thickness", "Supplier to determine (design note)" if design["supplier_det_note"] else "Design note not found", ", ".join(str(v) for v in predal_thicknesses) + " mm" if predal_thicknesses else "Not found", predal_status],
        ["Total slab thickness", ", ".join(design["slab_notes"]) if design["slab_notes"] else "Not clearly readable on design sheet", ", ".join(str(v) for v in total_thicknesses) + " mm" if total_thicknesses else "Not found", total_status],
        ["Mesh reinforcement", design["top_mesh"] or "Not found", supplier["top_mesh_note"] or "Not found", mesh_status],
        ["Fire resistance", design["fire_req"] or "Not found", ", ".join(supplier_fires) if supplier_fires else (supplier["fire_default"] or "Not found"), fire_status],
    ]

    dwars_ok = []
    for row in rows:
        min_required = max(row["langs_cm2m"] / 5.0, 2.5)
        dwars_ok.append(row["dwars_cm2m"] >= min_required)

    bins = [
        ("<=3.0m", lambda x: x <= 3000),
        ("3-5m", lambda x: 3000 < x <= 5000),
        ("5-7m", lambda x: 5000 < x <= 7000),
        (">=7m", lambda x: x > 7000),
    ]
    bin_lines = []
    for label, fn in bins:
        bucket = [row["langs_mm2m"] for row in rows if fn(row["length"])]
        if bucket:
            bin_lines.append(f"{label}: n={len(bucket)}, langs avg={mean(bucket):.1f} mm2/m, range {min(bucket)}-{max(bucket)}")

    sanity_lines = [
        f"Detected parser: {supplier.get('supplier_format', 'Unknown')}.",
        f"All {len(rows)} supplier plates parsed from the supplier PDF." if rows else "No supplier plates could be parsed from the supplier PDF.",
        f"{exact_ok} / {len(rows)} plates match one of the reinforcement families explicitly readable on the design PDF after converting mm2/m to cm2/m." if rows else "No plate-by-plate comparison could be completed.",
        f"Transverse reinforcement minimum check (>= 1/5 of main and >= 2.50 cm2/m): {'OK' if dwars_ok and all(dwars_ok) else 'CHECK'}.",
        "Exact geometric zone-to-plate mapping and span-direction verification cannot be proven from text extraction alone when the design sheet does not expose structured zone data.",
    ]
    if bin_lines:
        sanity_lines.append("Length-based reinforcement trend: " + " | ".join(bin_lines))

    conclusion_lines = [
        f"Numerical family check result: {exact_ok} / {len(rows)} plates are OK in the exact reinforcement-family comparison." if rows else "Numerical family check result: no rows parsed.",
        "This automated workflow is reliable for supplier formats that expose readable plate labels, plate sizes, and reinforcement values in PDF text.",
        "Before final approval, visually confirm reinforcement zone locations, main span direction, mesh requirement, and slab build-up areas on the full drawing set.",
    ]

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleX", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=HexColor("#163A63"), spaceAfter=6))
    styles.add(ParagraphStyle(name="SubX", parent=styles["Normal"], fontName="Helvetica", fontSize=10, leading=13, textColor=HexColor("#444444")))
    styles.add(ParagraphStyle(name="HeadX", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=HexColor("#163A63"), spaceAfter=4, spaceBefore=8))
    styles.add(ParagraphStyle(name="BodyX", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="SmallX", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=HexColor("#555555")))
    styles.add(ParagraphStyle(name="TableCell", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, leading=10.5))

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=landscape(A3),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )

    title = project_title.strip() or "Predal reinforcement verification"
    story = []
    story.append(Paragraph("Predal Reinforcement Verification Report", styles["TitleX"]))
    story.append(Paragraph(f"Project: {title}", styles["SubX"]))
    story.append(Paragraph("Method: automatic PDF extraction, supplier auto-detection, exact reinforcement-family matching, global parameter checks, and structural sanity checks.", styles["SubX"]))
    story.append(Spacer(1, 6))

    key_data = [[
        Paragraph("Report summary", styles["BodyX"]),
        Paragraph(
            f"{len(rows)} supplier plates parsed<br/>{len(design['families'])} design reinforcement families identified<br/>{exact_ok} / {len(rows)} exact family matches",
            styles["BodyX"],
        ),
        Paragraph(
            f"A3 landscape report<br/>Detected parser: {supplier.get('supplier_format', 'Unknown')}<br/>Global parameters included",
            styles["BodyX"],
        ),
    ]]
    key_tbl = LongTable(key_data, colWidths=[60 * mm, 95 * mm, 95 * mm])
    key_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#EEF4FA")),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#B8C7D9")),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, HexColor("#C8D4E3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(key_tbl)
    story.append(Spacer(1, 8))

    story.append(Paragraph("Predal Reinforcement Comparison", styles["HeadX"]))
    comp_table_data = [[
        Paragraph("Plate", styles["TableCell"]),
        Paragraph("Plate size (mm)", styles["TableCell"]),
        Paragraph("Design reinforcement (cm2/m)", styles["TableCell"]),
        Paragraph("Supplier reinforcement (mm2/m)", styles["TableCell"]),
        Paragraph("Status", styles["TableCell"]),
    ]]
    for row in comparison_rows:
        comp_table_data.append([Paragraph(v, styles["TableCell"]) for v in row])

    comp_col_widths = [20 * mm, 42 * mm, 68 * mm, 55 * mm, 22 * mm]
    comp_tbl = LongTable(comp_table_data, colWidths=comp_col_widths, repeatRows=1)
    comp_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#163A63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#9FB2C8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, HexColor("#D3DDE8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#F7FAFD")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(comp_tbl)
    story.append(PageBreak())

    story.append(Paragraph("Global Parameter Comparison", styles["HeadX"]))
    global_table_data = [[
        Paragraph("Parameter", styles["TableCell"]),
        Paragraph("Design requirement", styles["TableCell"]),
        Paragraph("Supplier provided", styles["TableCell"]),
        Paragraph("Status", styles["TableCell"]),
    ]]
    for row in global_rows:
        global_table_data.append([Paragraph(v, styles["TableCell"]) for v in row])

    global_tbl = LongTable(global_table_data, colWidths=[46 * mm, 90 * mm, 90 * mm, 22 * mm], repeatRows=1)
    global_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#163A63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.5, HexColor("#9FB2C8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, HexColor("#D3DDE8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#F7FAFD")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(global_tbl)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Structural Sanity Check", styles["HeadX"]))
    for line in sanity_lines:
        story.append(Paragraph("• " + line, styles["BodyX"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Engineering Conclusion", styles["HeadX"]))
    for line in conclusion_lines:
        story.append(Paragraph("• " + line, styles["BodyX"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Disclaimer: This report is based on automated extraction from the uploaded PDFs. A qualified engineer must verify zone locations, detailing, and any additional reinforcement notes on the full drawing set.", styles["SmallX"]))

    doc.build(story)
    pdf_buffer.seek(0)
    return pdf_buffer


@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)


@app.route("/healthz", methods=["GET"])
def healthz():
    return "ok", 200


@app.route("/generate", methods=["POST"])
def generate():
    design_file = request.files.get("design_pdf")
    supplier_file = request.files.get("supplier_pdf")
    project_title = (request.form.get("project_title") or "").strip()

    if not design_file or not supplier_file:
        return "Both PDF files are required.", 400

    import tempfile

    with tempfile.TemporaryDirectory() as temp_dir:
        design_path = os.path.join(temp_dir, "design.pdf")
        supplier_path = os.path.join(temp_dir, "supplier.pdf")
        design_file.save(design_path)
        supplier_file.save(supplier_path)

        supplier = extract_supplier_data(supplier_path)
        design = extract_design_data(design_path, supplier_full_text=supplier.get("full_text", ""))

        if not supplier["rows"]:
            return (
                "No supplier plates could be parsed from the supplier PDF. "
                f"Detected parser: {supplier.get('supplier_format', 'unknown')}. "
                "Try a cleaner PDF export or update the parser for this supplier layout."
            ), 400

        pdf_buffer = build_report_pdf_bytes(design, supplier, project_title=project_title)
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name="Predal_Reinforcement_Verification_Report.pdf",
            mimetype="application/pdf",
        )


if __name__ == "__main__":
    app.run(debug=True)
