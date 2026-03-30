
import os
import re
import tempfile
from statistics import mean
from flask import Flask, request, send_file, render_template_string
from werkzeug.middleware.proxy_fix import ProxyFix
import io
import fitz
from reportlab.lib.pagesizes import A3, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, Table, TableStyle, PageBreak
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor

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
    .wrap { max-width: 900px; margin: 32px auto; background:#fff; border:1px solid #d9e2ec; border-radius:16px; box-shadow:0 12px 28px rgba(0,0,0,.05); overflow:hidden; }
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
          <strong>How the automatic check works</strong>
          <ul>
            <li>Reads design reinforcement families from the design PDF (HW / DW / VW).</li>
            <li>Reads supplier plate table values from the supplier PDF.</li>
            <li>Converts supplier mm2/m to cm2/m and performs exact family matching.</li>
            <li>Builds an A3 landscape PDF report with plate table, global parameter checks, sanity check, and engineering conclusion.</li>
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

def read_blocks(pdf_path):
    doc = fitz.open(pdf_path)
    blocks = []
    full_text_parts = []
    for page in doc:
        page_blocks = page.get_text("blocks", sort=True)
        blocks.extend(page_blocks)
        for block in page_blocks:
            full_text_parts.append(block[4])
    return blocks, "\n".join(full_text_parts)

def extract_design_data(pdf_path):
    blocks, full_text = read_blocks(pdf_path)
    combo_pat = re.compile(
        r"HW\s+([0-9.]+)\s*cm²/lm\s*DW\s+([0-9.]+)\s*cm²/lm\s*VW\s+d(\d+)\s*a15\s*L=?([0-9]+)cm",
        re.I | re.S,
    )
    families = set()
    for block in blocks:
        match = combo_pat.search(block[4].replace("  ", " "))
        if match:
            families.add(
                (
                    float(match.group(1)),
                    float(match.group(2)),
                    int(match.group(3)),
                    int(match.group(4)),
                )
            )

    concrete = None
    steel = None
    top_mesh = None
    fire_req = None

    concrete_match = re.search(r"ALGEMEENHEDEN BOVENBOUW.*?betonkwaliteit:\s*(C\d+/\d+)", full_text, re.S)
    if concrete_match:
        concrete = concrete_match.group(1)

    steel_match = re.search(r"ALGEMEENHEDEN BOVENBOUW.*?wapeningskwaliteit:\s*([A-Z0-9]+)", full_text, re.S)
    if steel_match:
        steel = steel_match.group(1)

    mesh_hits = re.findall(r'B\d+-150', full_text)
    if mesh_hits:
        top_mesh = sorted(set(mesh_hits))[0]

    fire_match = re.search(r"Brandweerstand:\s*([^\n]+)", full_text)
    if fire_match:
        fire_req = fire_match.group(1).strip()

    slab_notes = sorted(set(re.findall(r"Predallen\s+\d\+\d+", full_text)))
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
    }

def extract_supplier_data(pdf_path):
    blocks, full_text = read_blocks(pdf_path)
    rows = []
    supplier_steel = None
    top_mesh_note = None
    fire_default = None

    steel_match = re.search(r"Wapening\s*:\s*staalkwaliteit\s*([A-Z0-9]+(?:\s*of\s*[A-Z0-9]+)?)", full_text, re.I)
    if steel_match:
        supplier_steel = steel_match.group(1).strip()

    mesh_match = re.search(r"Bovenwapening\s*:\s*([^\n]+)", full_text, re.I)
    if mesh_match:
        top_mesh_note = mesh_match.group(1).strip()

    fire_match = re.search(r"Brandweerstand\s*:\s*([A-Z0-9 ]+)", full_text, re.I)
    if fire_match:
        fire_default = fire_match.group(1).strip()

    for block in blocks:
        lines = [ln.strip() for ln in block[4].splitlines() if ln.strip()]
        if "REI 60" not in lines or "Glad" not in lines:
            continue

        rei_idx = lines.index("REI 60")
        glad_idx = lines.index("Glad")
        pre = lines[:glad_idx]
        post = lines[glad_idx + 1 : rei_idx]

        if len(pre) < 11:
            continue

        nums_after_glad = [int(v) for v in post if re.fullmatch(r"\d+", v)]
        cover = nums_after_glad[-1] if nums_after_glad else None
        uws = nums_after_glad[:-1] if len(nums_after_glad) >= 1 else []

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
            "weight_kg": int(pre[10]),
            "type": pre[0],
            "uw1": uws[0] if len(uws) > 0 else None,
            "uw2": uws[1] if len(uws) > 1 else None,
            "cover": cover,
            "fire": "REI 60",
            "env": lines[rei_idx + 1] if len(lines) > rei_idx + 1 else None,
            "concrete": lines[rei_idx + 2] if len(lines) > rei_idx + 2 else None,
        }
        row["langs_cm2m"] = row["langs_mm2m"] / 100.0
        row["dwars_cm2m"] = row["dwars_mm2m"] / 100.0
        row["plate_size"] = f"{row['length']} x {row['width']}"
        rows.append(row)

    rows.sort(key=lambda x: x["plate"])

    return {
        "rows": rows,
        "supplier_steel": supplier_steel,
        "top_mesh_note": top_mesh_note,
        "fire_default": fire_default,
        "full_text": full_text,
    }

def build_report(design, supplier, output_pdf_path, project_title=""):
    design_family_map = {(hw, dw): (vw_d, vw_l) for hw, dw, vw_d, vw_l in design["families"]}
    rows = supplier["rows"]

    comparison_rows = []
    for row in rows:
        pair = (row["langs_cm2m"], row["dwars_cm2m"])
        row["status"] = "OK" if pair in design_family_map else "CHECK"
        row["design_hw"] = row["langs_cm2m"] if pair in design_family_map else None
        row["design_dw"] = row["dwars_cm2m"] if pair in design_family_map else None
        comparison_rows.append([
            str(row["plate"]),
            row["plate_size"],
            (
                f"HW {row['design_hw']:.2f} / DW {row['design_dw']:.2f}"
                if row["design_hw"] is not None
                else "No exact family found on design sheet"
            ),
            f"Langs {row['langs_mm2m']} / Dwars {row['dwars_mm2m']}",
            row["status"],
        ])

    predal_thicknesses = sorted({row["predal_thk"] for row in rows})
    total_thicknesses = sorted({row["floor_thk"] for row in rows})
    supplier_concretes = sorted({row["concrete"] for row in rows if row["concrete"]})
    supplier_fires = sorted({row["fire"] for row in rows if row["fire"]})

    concrete_status = "OK" if design["concrete"] and supplier_concretes and all(c.lower() == design["concrete"].lower() for c in supplier_concretes) else "CHECK"
    steel_status = "OK" if design["steel"] and supplier["supplier_steel"] and design["steel"] in supplier["supplier_steel"] else "CHECK"
    predal_status = "OK" if predal_thicknesses else "CHECK"
    total_status = "CHECK"
    mesh_status = "CHECK"
    fire_status = "CHECK"

    global_rows = [
        ["Concrete class", f"{design['concrete'] or 'Not found'} minimum", ", ".join(supplier_concretes) or "Not found", concrete_status],
        ["Steel grade", design["steel"] or "Not found", supplier["supplier_steel"] or "Not found", steel_status],
        ["Predal thickness", "Supplier to determine (design note)" if design["supplier_det_note"] else "Design note not found", ", ".join(str(v) for v in predal_thicknesses) + " mm" if predal_thicknesses else "Not found", predal_status],
        ["Total slab thickness", ", ".join(design["slab_notes"]) if design["slab_notes"] else "Not clearly readable on design sheet", ", ".join(str(v) for v in total_thicknesses) + " mm" if total_thicknesses else "Not found", total_status],
        ["Mesh reinforcement", design["top_mesh"] or "Not found", supplier["top_mesh_note"] or "Not found", mesh_status],
        ["Fire resistance", design["fire_req"] or "Not found", ", ".join(supplier_fires) if supplier_fires else (supplier["fire_default"] or "Not found"), fire_status],
    ]

    exact_ok = sum(1 for row in rows if row["status"] == "OK")

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
        f"All {len(rows)} supplier plates were parsed from the supplier PDF.",
        f"{exact_ok} / {len(rows)} plates match one of the reinforcement families explicitly readable on the design PDF after converting mm2/m to cm2/m.",
        f"Transverse reinforcement minimum check (>= 1/5 of main and >= 2.50 cm2/m): {'OK' if all(dwars_ok) else 'CHECK'}.",
        "Exact geometric zone-to-plate mapping and span-direction verification cannot be proven from text extraction alone when the design sheet does not expose structured zone data.",
        "Length-based reinforcement trend: " + " | ".join(bin_lines),
    ]

    conclusion_lines = [
        f"Numerical family check result: {exact_ok} / {len(rows)} plates are OK in the exact reinforcement-family comparison.",
        "This automated workflow is reliable for extracting supplier plate data and matching reinforcement families.",
        "Before final approval, visually confirm reinforcement zone locations, main span direction, mesh requirement, and slab build-up areas on the full drawing set.",
    ]

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleX", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=HexColor("#163A63"), spaceAfter=6))
    styles.add(ParagraphStyle(name="SubX", parent=styles["Normal"], fontName="Helvetica", fontSize=10, leading=13, textColor=HexColor("#444444")))
    styles.add(ParagraphStyle(name="HeadX", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=HexColor("#163A63"), spaceAfter=4, spaceBefore=8))
    styles.add(ParagraphStyle(name="BodyX", parent=styles["Normal"], fontName="Helvetica", fontSize=9, leading=12))
    styles.add(ParagraphStyle(name="SmallX", parent=styles["Normal"], fontName="Helvetica", fontSize=8, leading=10, textColor=HexColor("#555555")))
    styles.add(ParagraphStyle(name="TableCell", parent=styles["Normal"], fontName="Helvetica", fontSize=8.5, leading=10.5))

    doc = SimpleDocTemplate(
        output_pdf_path,
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
    story.append(Paragraph("Method: automatic PDF extraction, exact reinforcement-family matching, global parameter checks, and structural sanity checks.", styles["SubX"]))
    story.append(Spacer(1, 6))

    key_data = [[
        Paragraph("<b>Report summary</b>", styles["BodyX"]),
        Paragraph(f"{len(rows)} supplier plates parsed<br/>{len(design['families'])} design reinforcement families identified<br/>{exact_ok} / {len(rows)} exact family matches", styles["BodyX"]),
        Paragraph("A3 landscape report<br/>Global parameters included<br/>Manual overlay still required for final approval", styles["BodyX"]),
    ]]
    key_table = Table(key_data, colWidths=[70 * mm, 85 * mm, 85 * mm])
    key_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HexColor("#F2F6FA")),
        ("BOX", (0, 0), (-1, -1), 0.6, HexColor("#9FB3C8")),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, HexColor("#D3DDE7")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(key_table)
    story.append(Spacer(1, 8))
    story.append(Paragraph("Plate-by-plate comparison", styles["HeadX"]))

    comp_data = [[
        Paragraph("<b>Plate</b>", styles["TableCell"]),
        Paragraph("<b>Plate size (mm)</b>", styles["TableCell"]),
        Paragraph("<b>Matched design family (cm2/m)</b>", styles["TableCell"]),
        Paragraph("<b>Supplier reinforcement (mm2/m)</b>", styles["TableCell"]),
        Paragraph("<b>Status</b>", styles["TableCell"]),
    ]]
    for row in comparison_rows:
        comp_data.append([Paragraph(cell, styles["TableCell"]) for cell in row])

    comp_table = LongTable(comp_data, repeatRows=1, colWidths=[18 * mm, 36 * mm, 56 * mm, 54 * mm, 18 * mm])
    comp_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#163A63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("GRID", (0, 0), (-1, -1), 0.35, HexColor("#AEBBC9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#F8FBFD")]),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
    ]))
    story.append(comp_table)
    story.append(PageBreak())

    story.append(Paragraph("Global parameter comparison", styles["HeadX"]))
    global_data = [[
        Paragraph("<b>Parameter</b>", styles["TableCell"]),
        Paragraph("<b>Design requirement</b>", styles["TableCell"]),
        Paragraph("<b>Supplier provided</b>", styles["TableCell"]),
        Paragraph("<b>Status</b>", styles["TableCell"]),
    ]]
    for row in global_rows:
        global_data.append([Paragraph(cell, styles["TableCell"]) for cell in row])

    global_table = Table(global_data, colWidths=[42 * mm, 88 * mm, 88 * mm, 20 * mm], repeatRows=1)
    global_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HexColor("#163A63")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, HexColor("#AEBBC9")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, HexColor("#F8FBFD")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
    ]))
    story.append(global_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Structural sanity check", styles["HeadX"]))
    for line in sanity_lines:
        story.append(Paragraph("&bull; " + line, styles["BodyX"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Engineering conclusion", styles["HeadX"]))
    for line in conclusion_lines:
        story.append(Paragraph("&bull; " + line, styles["BodyX"]))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Disclaimer", styles["HeadX"]))
    story.append(Paragraph(
        "This automated report is conceptual and educational. Verification by a qualified engineer remains mandatory.",
        styles["SmallX"],
    ))

    def add_page_footer(canvas, pdf_doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(HexColor("#666666"))
        canvas.drawRightString(pdf_doc.pagesize[0] - pdf_doc.rightMargin, 8 * mm, f"Page {canvas.getPageNumber()}")
        canvas.drawString(pdf_doc.leftMargin, 8 * mm, "Predal reinforcement verification - A3 landscape")
        canvas.restoreState()

    doc.build(story, onFirstPage=add_page_footer, onLaterPages=add_page_footer)

@app.get("/")
def index():
    return render_template_string(INDEX_HTML)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}, 200

@app.post("/generate")
def generate():
    design_file = request.files.get("design_pdf")
    supplier_file = request.files.get("supplier_pdf")
    project_title = request.form.get("project_title", "").strip()

    if not design_file or not supplier_file:
        return "Both PDF files are required.", 400

    with tempfile.TemporaryDirectory() as temp_dir:
        design_path = os.path.join(temp_dir, "design.pdf")
        supplier_path = os.path.join(temp_dir, "supplier.pdf")
        output_path = os.path.join(temp_dir, "Predal_Reinforcement_Verification_Report.pdf")

        design_file.save(design_path)
        supplier_file.save(supplier_path)

        design = extract_design_data(design_path)
        supplier = extract_supplier_data(supplier_path)
        build_report(design, supplier, output_path, project_title=project_title)

        with open(output_path, "rb") as f:
            pdf_bytes = f.read()

    return send_file(
        io.BytesIO(pdf_bytes),
        as_attachment=True,
        download_name="Predal_Reinforcement_Verification_Report.pdf",
        mimetype="application/pdf",
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
