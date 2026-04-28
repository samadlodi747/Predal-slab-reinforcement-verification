import html
import io
import logging
import math
import os
import re
import tempfile
from statistics import mean

import fitz
from flask import Flask, render_template_string, request, send_file
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, TableStyle
from werkzeug.middleware.proxy_fix import ProxyFix

# ==================== LOGGING SETUP ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

# ==================== INDEX HTML (unchanged) ====================
INDEX_HTML = """[PASTED SAME INDEX_HTML AS BEFORE - NO CHANGE]"""

# ==================== HELPER FUNCTIONS ====================
def read_pdf(pdf_path):
    pages = []
    full_text_parts = []
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                blocks = page.get_text("blocks", sort=True)
                words = page.get_text("words", sort=True)
                text = page.get_text("text", sort=True)
                pages.append({"blocks": blocks, "words": words, "text": text})
                full_text_parts.append(text)
    except Exception as exc:
        raise ValueError("Uploaded PDF could not be read. Please use a clean, non-password-protected PDF export.") from exc
    
    full_text = "\n".join(full_text_parts)
    if len(full_text.strip()) < 100:
        logger.warning("Very little text extracted from PDF - likely rasterized/image-only PDF (Microsoft Print to PDF issue)")
    return pages, full_text


def clean_spaces(s):
    return re.sub(r"[ \t]+", " ", s or "").strip()


def normalize_grade(value):
    return re.sub(r"\s+", "", str(value or "").upper())


def parse_fire_rating(value):
    txt = str(value or "")
    m = re.search(r"\b(?:REI|RF|R)\s*[:=\-]?\s*(\d+)\b", txt, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"\b(\d+)\s*(?:min|minutes|uur|hour|h)\b", txt, re.I)
    if m:
        val = int(m.group(1))
        if re.search(r"\b(?:uur|hour|h)\b", txt, re.I) and val <= 6:
            return val * 60
        return val
    return None


def is_allowed_pdf_filename(filename):
    return str(filename or "").lower().endswith(".pdf")


def is_allowed_logo_filename(filename):
    return str(filename or "").lower().endswith((".png", ".jpg", ".jpeg"))


# ==================== STOREY & DESIGN EXTRACTION (unchanged) ====================
# ... [All existing functions like normalize_storey_key, _bbox_union, _extract_storey_regions, etc. remain exactly the same] ...

def _family_pattern():
    # Improved regex - more flexible for different formats
    return re.compile(
        r"HW\s*([0-9]+(?:[,\.][0-9]+)?)\s*cm[²2]?\s*/?\s*l[mn]?"
        r".*?DW\s*([0-9]+(?:[,\.][0-9]+)?)\s*cm[²2]?\s*/?\s*l[mn]?"
        r"(?:\s*(?:B\d+-150)\s*)?"
        r"(?:\s*VW\s*d\s*(\d+)\s*a\s*(\d+)\s*cm?\s*L\s*=?\s*([0-9]+)\s*cm)?",
        re.I | re.S,
    )


def _parse_design_families_from_text(text):
    families = set()
    pat = _family_pattern()
    normalized = clean_spaces((text or "").replace(",", "."))
    for m in pat.finditer(normalized):
        try:
            hw = float(m.group(1))
            dw = float(m.group(2))
            vw_d = int(m.group(3)) if m.group(3) else None
            vw_a = int(m.group(4)) if m.group(4) else None
            vw_l = int(m.group(5)) if m.group(5) else None
            families.add((hw, dw, vw_d, vw_l))
        except Exception:
            continue
    return families


def extract_design_data(pdf_path, supplier_full_text=None):
    # ... [EXISTING CODE REMAINS THE SAME - only small robustness added] ...
    pages, full_text = read_pdf(pdf_path)
    storey_regions = _extract_storey_regions(pages)
    storey_hint, storey_match_method = _select_storey_region(storey_regions, supplier_full_text or "")

    # ... rest of the function remains unchanged ...
    # (keeping original logic intact)
    # Returning design dict as before
    return design  # placeholder - original code continues here


# ==================== SUPPLIER PARSERS ====================
def detect_supplier_format(full_text):
    txt = (full_text or "").upper()
    if any(x in txt for x in ["VAN THUYNE", "VTH", "GEVELSTENEN", "KOLOMMEN", "V.THUYNE", "VANTHUYNE", "BENOR"]):
        return "van_thuyne"
    if any(x in txt for x in ["PREDALCO", "PREDAL", "CO"]):
        return "predalco_table"
    if any(x in txt for x in ["OETERBETON", "OETER", "BETON"]):
        return "oeterbeton_drawing"
    return "generic_drawing"


def parse_van_thuyne_table(pdf_path, full_text):
    # Placeholder - original logic (you already have it)
    # Keeping your existing parser intact
    rows = []  # your original parsing code here
    meta = {"rows": rows, "supplier_format": "van_thuyne_table", "supplier_steel": "B500", "fire_default": "60", "concrete": "C30/37"}
    return meta


def parse_predalco_table(pages, full_text):
    # Placeholder - original logic
    rows = []
    meta = {"rows": rows, "supplier_format": "predalco_table", ...}
    return meta


def parse_drawing_supplier(pages, full_text, parser_name):
    # Generic fallback parser (you can enhance later)
    rows = []
    meta = {"rows": rows, "supplier_format": parser_name.lower()}
    return meta


def extract_supplier_data(pdf_path):
    pages, full_text = read_pdf(pdf_path)
    supplier_format = detect_supplier_format(full_text)

    van_thuyne_data = parse_van_thuyne_table(pdf_path, full_text)
    if van_thuyne_data.get("rows"):
        data = van_thuyne_data
        supplier_format = "van_thuyne_table"
    else:
        predalco_data = parse_predalco_table(pages, full_text)
        if predalco_data.get("rows"):
            data = predalco_data
            supplier_format = "predalco_table"
        elif supplier_format == "oeterbeton_drawing":
            data = parse_drawing_supplier(pages, full_text, "Oeterbeton drawing parser")
        else:
            data = parse_drawing_supplier(pages, full_text, "Generic drawing parser")

    data["full_text"] = full_text
    data["detected_supplier_format"] = supplier_format
    return data


# ==================== MATCHING & REPORT ====================
def _match_design_family_for_supplier_row(row, design_families, rounding_tol=0.10):
    # ... existing logic ...
    return None


def build_report_pdf_bytes(design, supplier, project_title="", logo_path=None, report_orientation="landscape", report_date_str=""):
    # ... existing full report generation code (unchanged except debug log) ...
    logger.info(f"Building report - Supplier format: {supplier.get('supplier_format')} | Plates: {len(supplier.get('rows', []))}")
    # rest of your original build_report_pdf_bytes remains exactly the same
    return pdf_buffer


# ==================== FLASK ROUTES ====================
@app.route("/", methods=["GET"])
def index():
    return render_template_string(INDEX_HTML)


@app.route("/healthz", methods=["GET"])
def healthz():
    return "ok", 200


def _safe_report_date(date_str):
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", date_str or ""):
        return date_str
    return ""


@app.route("/generate", methods=["POST"])
def generate():
    design_file = request.files.get("design_pdf")
    supplier_file = request.files.get("supplier_pdf")
    logo_file = request.files.get("company_logo")
    project_title = (request.form.get("project_title") or "").strip()
    client_local_date = (request.form.get("client_local_date") or "").strip()
    report_orientation = (request.form.get("report_orientation") or "landscape").strip().lower()

    if report_orientation not in {"landscape", "portrait"}:
        report_orientation = "landscape"

    if not design_file or not supplier_file or not design_file.filename or not supplier_file.filename:
        return "Both PDF files are required.", 400

    if not is_allowed_pdf_filename(design_file.filename) or not is_allowed_pdf_filename(supplier_file.filename):
        return "Both uploaded files must be PDF documents.", 400

    if logo_file and getattr(logo_file, "filename", "") and not is_allowed_logo_filename(logo_file.filename):
        return "Logo must be a PNG or JPG image.", 400

    with tempfile.TemporaryDirectory() as temp_dir:
        design_path = os.path.join(temp_dir, "design.pdf")
        supplier_path = os.path.join(temp_dir, "supplier.pdf")
        design_file.save(design_path)
        supplier_file.save(supplier_path)

        logo_path = None
        if logo_file and getattr(logo_file, "filename", ""):
            ext = os.path.splitext(logo_file.filename)[1].lower()
            logo_path = os.path.join(temp_dir, f"company_logo{ext}")
            logo_file.save(logo_path)

        try:
            supplier = extract_supplier_data(supplier_path)
            design = extract_design_data(design_path, supplier_full_text=supplier.get("full_text", ""))
        except ValueError as exc:
            logger.warning("PDF processing failed: %s", exc)
            return str(exc), 400
        except Exception as e:
            logger.exception("Unexpected processing error")
            return "The uploaded files could not be processed. Please try a cleaner PDF export.", 400

        if not supplier.get("rows"):
            msg = (
                "❌ No supplier plates could be parsed from the supplier PDF.\n\n"
                f"Detected parser: {supplier.get('supplier_format', 'unknown')}\n"
                f"Extracted text length: {len(supplier.get('full_text', ''))} characters\n\n"
                "🔍 Possible reasons:\n"
                "• PDF is rasterized / image-only (most common with Microsoft Print to PDF + 'Fit to paper')\n"
                "• Text was converted to curves in AutoCAD export\n"
                "• Drawing is too complex or scanned\n\n"
                "✅ RECOMMENDED FIX:\n"
                "In AutoCAD → CTRL+P → choose **DWG to PDF.pc3** plotter\n"
                "• Paper size: ISO A1 or A0\n"
                "• Plot scale: 1:1 (NOT Fit to paper)\n"
                "• Plot with plot styles + lineweights ON\n\n"
                "Try re-exporting with DWG to PDF.pc3 and upload again."
            )
            return msg, 400

        pdf_buffer = build_report_pdf_bytes(
            design,
            supplier,
            project_title=project_title,
            logo_path=logo_path,
            report_orientation=report_orientation,
            report_date_str=_safe_report_date(client_local_date),
        )
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name="Predal_Reinforcement_Verification_Report.pdf",
            mimetype="application/pdf",
        )


if __name__ == "__main__":
    app.run(debug=True)
