
import html
import io
import math
import os
import re
import tempfile
from statistics import mean

import fitz
import numpy as np
from flask import Flask, render_template_string, request, send_file
from reportlab.lib import colors
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
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
    :root{
      --bg:#edf3fa;
      --card:#ffffff;
      --line:#d6e1ef;
      --text:#142133;
      --muted:#607089;
      --primary:#173f6b;
      --primary-2:#255a96;
      --accent:#1fa0a0;
      --soft:#f7fafe;
      --shadow:0 18px 45px rgba(19,39,68,.10);
      --radius:24px;
    }
    *{box-sizing:border-box}
    html,body{margin:0;padding:0}
    body{
      font-family:Arial,sans-serif;
      color:var(--text);
      background:
        radial-gradient(circle at top left, #f9fcff 0, #edf3fa 36%, #e6eef8 100%);
      min-height:100vh;
    }
    .page{
      max-width:1140px;
      margin:36px auto;
      padding:0 18px;
    }
    .shell{
      background:rgba(255,255,255,.82);
      border:1px solid rgba(214,225,239,.95);
      border-radius:30px;
      overflow:hidden;
      box-shadow:var(--shadow);
      backdrop-filter: blur(12px);
    }
    .hero{
      position:relative;
      padding:34px 34px 28px;
      background:linear-gradient(135deg, #173f6b 0%, #255a96 100%);
      color:#fff;
      overflow:hidden;
    }
    .hero:before,
    .hero:after{
      content:"";
      position:absolute;
      border-radius:999px;
      background:rgba(255,255,255,.08);
      filter:blur(2px);
    }
    .hero:before{width:280px;height:280px;right:-90px;top:-120px}
    .hero:after{width:220px;height:220px;left:-60px;bottom:-120px}
    .hero-inner{position:relative;z-index:1}
    .badge{
      display:inline-flex;
      align-items:center;
      gap:8px;
      padding:8px 12px;
      border:1px solid rgba(255,255,255,.18);
      border-radius:999px;
      font-size:12px;
      font-weight:700;
      letter-spacing:.04em;
      text-transform:uppercase;
      background:rgba(255,255,255,.08);
      margin-bottom:14px;
    }
    .hero h1{
      margin:0;
      font-size:40px;
      line-height:1.06;
      font-weight:800;
    }
    .body{padding:30px}
    .top-row{
      display:grid;
      grid-template-columns:1.15fr .85fr;
      gap:18px;
      margin-bottom:18px;
    }
    .field-card{
      background:var(--card);
      border:1px solid var(--line);
      border-radius:22px;
      padding:18px;
      box-shadow:0 8px 24px rgba(14,25,42,.04);
    }
    label{
      display:block;
      font-size:14px;
      font-weight:700;
      margin-bottom:10px;
    }
    .text-input,.select-input{
      width:100%;
      border:1px solid var(--line);
      border-radius:14px;
      padding:14px 16px;
      font-size:15px;
      color:var(--text);
      background:#fbfdff;
      outline:none;
      transition:border-color .18s ease, box-shadow .18s ease, background .18s ease;
    }
    .text-input:focus,.select-input:focus{
      border-color:#8fb2da;
      box-shadow:0 0 0 4px rgba(33,85,141,.10);
      background:#fff;
    }
    .upload-grid{
      display:grid;
      grid-template-columns:repeat(3, 1fr);
      gap:18px;
      margin-top:8px;
    }
    .upload-card{
      position:relative;
      border:1px solid var(--line);
      border-radius:22px;
      padding:18px;
      background:linear-gradient(180deg,#ffffff 0%, #f9fbfe 100%);
      transition:transform .18s ease, box-shadow .18s ease, border-color .18s ease;
    }
    .upload-card:hover{
      transform:translateY(-1px);
      border-color:#a9c1df;
      box-shadow:0 10px 24px rgba(17,38,66,.06);
    }
    .upload-card h3{
      margin:0 0 12px;
      font-size:16px;
    }
    .upload-card p{
      margin:0 0 12px;
      color:var(--muted);
      font-size:13px;
    }
    .dropzone{
      display:flex;
      flex-direction:column;
      align-items:center;
      justify-content:center;
      text-align:center;
      min-height:190px;
      border:1.5px dashed #b3c6dd;
      border-radius:18px;
      background:#fbfdff;
      padding:20px;
      cursor:pointer;
      transition:border-color .18s ease, background .18s ease, transform .18s ease;
    }
    .dropzone:hover{
      background:#f6faff;
      border-color:#6f96c3;
      transform:translateY(-1px);
    }
    .dropzone.active{
      background:#eef6ff;
      border-color:#21558d;
    }
    .icon{
      width:54px;
      height:54px;
      border-radius:16px;
      display:grid;
      place-items:center;
      margin-bottom:12px;
      font-size:24px;
      background:#eaf2fb;
      color:var(--primary);
    }
    .dropzone strong{
      display:block;
      font-size:16px;
      margin-bottom:6px;
    }
    .dropzone span{
      display:block;
      font-size:13px;
      line-height:1.45;
      color:var(--muted);
      max-width:240px;
    }
    .hidden-input{display:none}
    .file-meta{
      margin-top:12px;
      min-height:22px;
      font-size:14px;
      color:var(--muted);
      word-break:break-word;
    }
    .file-meta.ready{color:#1d5b38;font-weight:700}
    .actions{
      display:flex;
      align-items:center;
      justify-content:flex-end;
      gap:16px;
      margin-top:24px;
      flex-wrap:wrap;
    }
    .btn{
      appearance:none;
      border:none;
      border-radius:16px;
      padding:15px 22px;
      min-width:240px;
      background:linear-gradient(135deg,var(--primary) 0%, var(--primary-2) 100%);
      color:#fff;
      font-size:15px;
      font-weight:800;
      cursor:pointer;
      box-shadow:0 12px 24px rgba(21,58,99,.22);
      transition:transform .18s ease, box-shadow .18s ease, opacity .18s ease;
    }
    .btn:hover{transform:translateY(-1px); box-shadow:0 15px 28px rgba(21,58,99,.28)}
    .btn:disabled{opacity:.72; cursor:not-allowed; transform:none}
    @media (max-width: 980px){
      .top-row{grid-template-columns:1fr}
      .upload-grid{grid-template-columns:1fr}
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="shell">
      <div class="hero">
        <div class="hero-inner">
          <div class="badge">PDF Report Builder</div>
          <h1>Predal Reinforcement Verifier</h1>
        </div>
      </div>

      <div class="body">
        <form id="verifyForm" method="post" action="/generate" enctype="multipart/form-data">
          <div class="top-row">
            <div class="field-card">
              <label for="project_title">Project title</label>
              <input class="text-input" type="text" id="project_title" name="project_title" value="">
            </div>
            <div class="field-card">
              <label for="report_orientation">Output layout</label>
              <select class="select-input" id="report_orientation" name="report_orientation">
                <option value="landscape" selected>A3 Landscape</option>
                <option value="portrait">A3 Portrait</option>
              </select>
            </div>
          </div>

          <input type="hidden" id="client_local_date" name="client_local_date" value="">
          <input type="hidden" id="client_time_zone" name="client_time_zone" value="">

          <div class="upload-grid">
            <div class="upload-card">
              <h3>Structural design PDF</h3>
              <p>Required</p>
              <label class="dropzone" for="design_pdf" id="designDrop">
                <div class="icon">📐</div>
                <strong>Choose or drop file</strong>
                <span>PDF only</span>
              </label>
              <input class="hidden-input" type="file" id="design_pdf" name="design_pdf" accept="application/pdf,.pdf" required>
              <div class="file-meta" id="designMeta">No file selected</div>
            </div>

            <div class="upload-card">
              <h3>Supplier Predal PDF</h3>
              <p>Required</p>
              <label class="dropzone" for="supplier_pdf" id="supplierDrop">
                <div class="icon">🏗️</div>
                <strong>Choose or drop file</strong>
                <span>PDF only</span>
              </label>
              <input class="hidden-input" type="file" id="supplier_pdf" name="supplier_pdf" accept="application/pdf,.pdf" required>
              <div class="file-meta" id="supplierMeta">No file selected</div>
            </div>

            <div class="upload-card">
              <h3>Company logo</h3>
              <p>Optional</p>
              <label class="dropzone" for="company_logo" id="logoDrop">
                <div class="icon">🖼️</div>
                <strong>Choose or drop file</strong>
                <span>PNG or JPG</span>
              </label>
              <input class="hidden-input" type="file" id="company_logo" name="company_logo" accept="image/png,image/jpeg,.png,.jpg,.jpeg">
              <div class="file-meta" id="logoMeta">No logo selected</div>
            </div>
          </div>

          <div class="actions">
            <button class="btn" id="submitBtn" type="submit">Generate verification PDF</button>
          </div>
        </form>
      </div>
    </div>
  </div>

  <script>
    function bindDropzone(inputId, metaId, zoneId, mode){
      const input = document.getElementById(inputId);
      const meta = document.getElementById(metaId);
      const zone = document.getElementById(zoneId);

      function setMeta(file){
        if(file){
          meta.textContent = file.name;
          meta.classList.add("ready");
        }else{
          meta.textContent = mode === "logo" ? "No logo selected" : "No file selected";
          meta.classList.remove("ready");
        }
      }

      input.addEventListener("change", function(){
        setMeta(this.files && this.files[0] ? this.files[0] : null);
      });

      ["dragenter","dragover"].forEach(evt => {
        zone.addEventListener(evt, function(e){
          e.preventDefault();
          e.stopPropagation();
          zone.classList.add("active");
        });
      });

      ["dragleave","drop"].forEach(evt => {
        zone.addEventListener(evt, function(e){
          e.preventDefault();
          e.stopPropagation();
          zone.classList.remove("active");
        });
      });

      zone.addEventListener("drop", function(e){
        const file = e.dataTransfer.files && e.dataTransfer.files[0] ? e.dataTransfer.files[0] : null;
        if(!file){ return; }
        const lower = file.name.toLowerCase();
        const ok = mode === "logo"
          ? (lower.endsWith(".png") || lower.endsWith(".jpg") || lower.endsWith(".jpeg") || file.type === "image/png" || file.type === "image/jpeg")
          : (lower.endsWith(".pdf") || file.type === "application/pdf");
        if(!ok){
          meta.textContent = mode === "logo" ? "Please use PNG or JPG" : "Please use a PDF file";
          meta.classList.remove("ready");
          return;
        }
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        setMeta(file);
      });
    }

    bindDropzone("design_pdf", "designMeta", "designDrop", "pdf");
    bindDropzone("supplier_pdf", "supplierMeta", "supplierDrop", "pdf");
    bindDropzone("company_logo", "logoMeta", "logoDrop", "logo");

    function setClientDateFields(){
      const dateField = document.getElementById("client_local_date");
      const tzField = document.getElementById("client_time_zone");
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "";
      const formatted = new Intl.DateTimeFormat("en-GB", {
        timeZone: tz || undefined,
        day: "2-digit",
        month: "2-digit",
        year: "numeric"
      }).format(new Date());
      dateField.value = formatted;
      tzField.value = tz;
    }

    setClientDateFields();

    document.getElementById("verifyForm").addEventListener("submit", function(){
      setClientDateFields();
      const btn = document.getElementById("submitBtn");
      btn.disabled = true;
      btn.textContent = "Generating PDF...";
    });
  </script>
</body>
</html>
"""


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
    return pages, "\n".join(full_text_parts)



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



def normalize_storey_key(text):
    txt = (text or "").upper()
    compact = re.sub(r"\s+", "", txt)
    normalized = re.sub(r"[\r\n\t]+", " ", txt)

    if "FUNDERINGSPLAAT" in compact or "FUNDERING" in compact:
        return "FOUNDATION"

    explicit_patterns = [
        (r"\b(?:AFDEK\.?\s*)?GELIJKVLOERS\b", "LEVEL_0"),
        (r"\bGROUND\s*FLOOR\b", "LEVEL_0"),
        (r"\b(?:RDC|REZ(?:-DE-CHAUSSEE)?)\b", "LEVEL_0"),
        (r"\b(?:BK|NIV|NIVEAU|BOVEN|LEVEL)\s*\+?0\b", "LEVEL_0"),
        (r"\b(?:GL|GV)\b", "LEVEL_0"),
        (r"\b(?:1(?:STE|E)?\s+VERDIEPING|VERDIEP(?:ING)?\s*\+?1|BOVEN\s*\+?1|LEVEL\s*\+?1|BK\s*\+?1|NIV(?:EAU)?\s*\+?1|ETAGE\s*1)\b", "LEVEL_1"),
        (r"\b(?:2(?:DE|E)?\s+VERDIEPING|VERDIEP(?:ING)?\s*\+?2|BOVEN\s*\+?2|LEVEL\s*\+?2|BK\s*\+?2|NIV(?:EAU)?\s*\+?2|ETAGE\s*2)\b", "LEVEL_2"),
        (r"\b(?:DAK|PLAT\s*DAK|ROOF)\b", "ROOF"),
        (r"\b(?:KELDER|SOUTERRAIN|BASEMENT)\b", "LEVEL_-1"),
    ]
    for pattern, value in explicit_patterns:
        if re.search(pattern, normalized, re.I):
            return value

    for pat in [r"NIV\+?(-?\d+)", r"BOVEN\+?(-?\d+)", r"NIVEAU\+?(-?\d+)", r"LEVEL\+?(-?\d+)", r"BK\+?(-?\d+)"]:
        m = re.search(pat, compact)
        if m:
            return f"LEVEL_{m.group(1)}"
    return None



def _bbox_union(blocks):
    xs0 = [b[0] for b in blocks]
    ys0 = [b[1] for b in blocks]
    xs1 = [b[2] for b in blocks]
    ys1 = [b[3] for b in blocks]
    return (min(xs0), min(ys0), max(xs1), max(ys1))

def _bbox_expand(bbox, dx=180, dy=180):
    x0, y0, x1, y1 = bbox
    return (x0 - dx, y0 - dy, x1 + dx, y1 + dy)

def _bbox_intersects(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return not (ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0)

def _most_common(items):
    if not items:
        return None
    counts = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[0][0]

def _storey_plate_prefix(storey_hint):
    if not storey_hint or not storey_hint.startswith("LEVEL_"):
        return None
    try:
        lvl = int(storey_hint.split("_", 1)[1])
    except Exception:
        return None
    if lvl < 0:
        return f"B-{abs(lvl)}."
    return f"B{lvl}."

def _collect_storey_local_text(pages, storey_hint):
    if not storey_hint:
        return ""
    local_text_parts = []

    if storey_hint == "FOUNDATION":
        for page in pages:
            page_text = page["text"]
            if re.search(r"FUNDERINGSPLAAT|FUNDERING", page_text, re.I):
                local_text_parts.append(page_text)
        return "\n".join(local_text_parts)

    prefix = _storey_plate_prefix(storey_hint)
    if not prefix:
        return ""

    prefix_re = re.compile(rf"\b{re.escape(prefix)}\d+[A-Z]?\b", re.I)

    for page in pages:
        blocks = page["blocks"]
        storey_blocks = [b for b in blocks if prefix_re.search(clean_spaces(b[4]))]
        if not storey_blocks:
            continue
        zone = _bbox_expand(_bbox_union(storey_blocks), dx=320, dy=320)
        local_blocks = [b for b in blocks if _bbox_intersects((b[0], b[1], b[2], b[3]), zone)]
        local_text_parts.extend(clean_spaces(b[4]) for b in local_blocks if clean_spaces(b[4]))

    return "\n".join(local_text_parts)


def _extract_storey_regions(pages):
    regions = {}

    for page_index, page in enumerate(pages):
        blocks = page["blocks"]
        anchors_by_storey = {}

        for block in blocks:
            txt = clean_spaces(block[4])
            for m in re.finditer(r"\bB(-?\d+)\.\d+[A-Z]?\b", txt, re.I):
                hint = f"LEVEL_{m.group(1)}"
                anchors_by_storey.setdefault(hint, []).append(block)

        for hint, anchors in anchors_by_storey.items():
            zone = _bbox_expand(_bbox_union(anchors), dx=320, dy=320)
            local_blocks = [b for b in blocks if _bbox_intersects((b[0], b[1], b[2], b[3]), zone)]
            region = regions.setdefault(hint, {"blocks": [], "page_indexes": set(), "anchor_blocks": []})
            region["blocks"].extend(local_blocks)
            region["anchor_blocks"].extend(anchors)
            region["page_indexes"].add(page_index)

    for hint, region in regions.items():
        unique = []
        seen = set()
        for b in region["blocks"]:
            key = (round(b[0], 2), round(b[1], 2), round(b[2], 2), round(b[3], 2), clean_spaces(b[4]))
            if key in seen:
                continue
            seen.add(key)
            unique.append(b)
        region["blocks"] = unique
        region["text"] = "\n".join(clean_spaces(b[4]) for b in unique if clean_spaces(b[4]))
        families = set()
        for b in unique:
            families |= _parse_design_families_from_text(clean_spaces(b[4]))
        if not families:
            families |= _parse_design_families_from_text(region["text"])
        region["families"] = sorted(families)
        region["bbox"] = _bbox_union(unique) if unique else None

    return regions


def _select_storey_region(storey_regions, supplier_full_text):
    hinted = normalize_storey_key(supplier_full_text or "")
    if hinted == "ROOF":
        numeric = []
        for key in storey_regions:
            m = re.match(r"LEVEL_(-?\d+)$", key)
            if m:
                numeric.append((int(m.group(1)), key))
        if numeric:
            numeric.sort()
            return numeric[-1][1], "supplier_text_roof"
        return None, "supplier_text_roof"

    if hinted and hinted in storey_regions:
        return hinted, "supplier_text"

    if hinted == "LEVEL_-1" and hinted in storey_regions:
        return hinted, "supplier_text"

    if len(storey_regions) == 1:
        return next(iter(storey_regions.keys())), "single_design_storey"

    normalized = re.sub(r"[\r\n\t]+", " ", str(supplier_full_text or "").upper())
    if re.search(r"\b(?:GELIJKVLOERS|GROUND\s*FLOOR|RDC|REZ(?:-DE-CHAUSSEE)?|GL|GV)\b", normalized) and "LEVEL_0" in storey_regions:
        return "LEVEL_0", "supplier_keyword"

    return None, "full_document"


def _pages_word_text(pages):
    return " ".join(str(w[4]) for page in pages for w in page.get("words", []))

def _extract_design_total_thickness_mm(text):
    txt = clean_spaces(text or "")
    buildup = re.findall(r"Predallen\s+(\d+)\s*\+\s*(\d+)", txt, re.I)
    totals = [(int(a) + int(b)) * 10 for a, b in buildup]
    if totals:
        return _most_common(totals)

    # Common layout in design PDFs: "22 bk:+302 ok:+280 Predallen"
    leading_notes = []
    for m in re.finditer(r"\b(\d{1,2})\b\s*bk\s*:\s*[+\-]?\d+\s*ok\s*:\s*[+\-]?\d+\s*Predallen", txt, re.I):
        val = int(m.group(1))
        if 5 <= val <= 60:
            leading_notes.append(val * 10)
    if leading_notes:
        return _most_common(leading_notes)

    # Alternative layout: bk / ok first, then infer from level difference.
    diffs = []
    for m in re.finditer(r"bk\s*:\s*([+\-]?\d+)\s*ok\s*:\s*([+\-]?\d+)\s*Predallen", txt, re.I):
        try:
            diff = abs(int(m.group(1)) - int(m.group(2)))
        except Exception:
            continue
        if 5 <= diff <= 60:
            diffs.append(diff * 10)
    if diffs:
        return _most_common(diffs)

    # Fallback: nearby plausible cm value around each Predallen keyword.
    notes = []
    for m in re.finditer(r"Predallen", txt, re.I):
        window = txt[max(0, m.start() - 120): m.end() + 20]
        nums = [int(n) for n in re.findall(r"\b(\d{1,2})\b", window) if 5 <= int(n) <= 60]
        if nums:
            notes.append(max(nums))
    if notes:
        return _most_common(notes) * 10
    return None


def _extract_design_total_thickness_mm_from_blocks(primary_blocks, fallback_blocks=None):
    def _scan(blocks):
        values = []
        if not blocks:
            return values

        number_only_re = re.compile(r"^\s*(\d{1,2})\s*$")
        for block in blocks:
            text = str(block[4] or "")
            compact = clean_spaces(text)
            if not re.search(r"\bPredallen\b", compact, re.I):
                continue

            x0, y0, x1, y1 = block[:4]

            m = re.search(r"bk\s*:\s*([+\-]?\d+)\s*ok\s*:\s*([+\-]?\d+)", compact, re.I)
            if m:
                try:
                    diff = abs(int(m.group(1)) - int(m.group(2)))
                except Exception:
                    diff = None
                if diff is not None and 5 <= diff <= 60:
                    values.append(diff * 10)

            nearby = []
            center_x = (x0 + x1) / 2.0
            for other in blocks:
                other_text = str(other[4] or "")
                m_num = number_only_re.match(other_text)
                if not m_num:
                    continue
                value = int(m_num.group(1))
                if not (5 <= value <= 60):
                    continue

                ox0, oy0, ox1, oy1 = other[:4]
                other_center_x = (ox0 + ox1) / 2.0
                other_center_y = (oy0 + oy1) / 2.0
                dy = y0 - other_center_y
                if -6 <= dy <= 90 and abs(other_center_x - center_x) <= 75:
                    distance = abs(other_center_x - center_x) + max(dy, 0)
                    nearby.append((distance, value))

            if nearby:
                nearby.sort(key=lambda item: item[0])
                values.append(nearby[0][1] * 10)

        return values

    primary_values = _scan(primary_blocks)
    if primary_values:
        return _most_common(primary_values)

    fallback_values = _scan(fallback_blocks)
    if fallback_values:
        return _most_common(fallback_values)

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
    storey_regions = _extract_storey_regions(pages)
    storey_hint, storey_match_method = _select_storey_region(storey_regions, supplier_full_text or "")

    local_blocks = []
    local_text = ""

    if storey_hint and storey_hint in storey_regions:
        region = storey_regions[storey_hint]
        local_blocks = list(region.get("blocks", []))
        local_text = region.get("text", "")

    search_text = local_text or full_text

    families = set()
    for block in local_blocks:
        families |= _parse_design_families_from_text(clean_spaces(block[4]))

    if not families and local_text:
        families |= _parse_design_families_from_text(local_text)

    if not families and storey_regions:
        for region in storey_regions.values():
            for fam in region.get("families", []):
                families.add(tuple(fam))

    if not families:
        for page in pages:
            for block in page["blocks"]:
                families |= _parse_design_families_from_text(clean_spaces(block[4]))

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

    mesh_hits = re.findall(r'\bB\d+-150\b', search_text, re.I)
    if mesh_hits:
        top_mesh = _most_common([m.upper() for m in mesh_hits])

    fire_match = re.search(r"ALGEMEENHEDEN BOVENBOUW.*?brandweerstand:\s*([^\n]+)", full_text, re.S | re.I)
    if fire_match:
        fire_req = clean_spaces(fire_match.group(1))

    slab_notes = sorted(set(re.findall(r"Predallen\s+\d\s*\+\s*\d+", search_text, re.I)))
    supplier_det_note = "supplier" if re.search(r"Dikte van de predalplaat.*leverancier", full_text, re.I) else None
    all_blocks = [block for page in pages for block in page["blocks"]]
    total_thickness_mm = (
        _extract_design_total_thickness_mm_from_blocks(local_blocks, all_blocks)
        or _extract_design_total_thickness_mm(search_text)
        or _extract_design_total_thickness_mm(full_text)
    )

    return {
        "families": sorted(families),
        "concrete": concrete,
        "steel": steel,
        "top_mesh": top_mesh,
        "fire_req": fire_req,
        "slab_notes": slab_notes,
        "supplier_det_note": supplier_det_note,
        "full_text": full_text,
        "storey_hint": storey_hint,
        "storey_match_method": storey_match_method,
        "available_storeys": sorted(storey_regions.keys()),
        "local_text": local_text,
        "total_thickness_mm": total_thickness_mm,
        "source_pdf_path": pdf_path,
    }


def detect_supplier_format(full_text):
    txt = (full_text or "").lower()
    if (("overzichtstabel" in txt and "breedvloerplaten" in txt) or "van thuyne" in txt or "van thuyne-ide" in txt or "breedvloerplaten met benor-merk" in txt):
        return "van_thuyne_table"
    if "oeterbeton" in txt or "o e t e r" in txt:
        return "oeterbeton_drawing"
    if "inclusief tralies" in txt and "glad" in txt and "rei" in txt:
        return "predalco_table"
    return "generic_drawing"


def parse_common_supplier_meta(full_text, word_text=""):
    combined_text = f"{full_text}\n{word_text}".strip()
    compact_text = " ".join(combined_text.split())

    concrete = None
    preferred_concrete_patterns = [
        r"Betonkwaliteit van de platen\s*:\s*standaard\s*(C\d+/\d+)",
        r"betonkwaliteit[^\n\.]{0,80}(C\d+/\d+)",
        r"Opstorten\s*:\s*Vereiste betonkwaliteit[^\n\.]{0,80}(C\d+/\d+)",
    ]
    for pat in preferred_concrete_patterns:
        m = re.search(pat, compact_text, re.I)
        if m:
            concrete = m.group(1).upper()
            break
    if not concrete:
        concrete_matches = re.findall(r"\bC\d+/\d+\b", combined_text, re.I)
        if concrete_matches:
            def _concrete_key(value):
                m = re.match(r"C(\d+)/(\d+)", str(value).upper())
                return (int(m.group(1)), int(m.group(2))) if m else (10**9, 10**9)
            concrete = sorted((c.upper() for c in concrete_matches), key=_concrete_key)[0]

    steel = None
    steel_hits = re.findall(r"\b(DE\s*500\s*BS|BE\s*500(?:ES|BS|TS)?|BE500(?:ES|BS|TS)?)\b", combined_text, re.I)
    if steel_hits:
        unique_hits = []
        for hit in steel_hits:
            normalized = clean_spaces(hit).upper().replace(" ", "")
            if normalized not in unique_hits:
                unique_hits.append(normalized)
        steel = " / ".join(unique_hits)
    else:
        steel_patterns = [
            r"Wapening\s*:\s*staalkwaliteit\s*([^\n\.]+)",
            r"staalkwaliteit[^A-Z0-9]{0,60}(DE\s*500\s*BS|BE\s*500(?:ES|BS|TS)?|BE500(?:ES|BS|TS)?)",
            r"kwaliteit d[' ]acier[^A-Z0-9]{0,60}(DE\s*500\s*BS|BE\s*500(?:ES|BS|TS)?)",
        ]
        for pat in steel_patterns:
            m = re.search(pat, combined_text, re.I)
            if m:
                steel = clean_spaces(m.group(1)).upper().replace(" ", "")
                break

    top_mesh_note = None
    for pat in [
        r"Bovenwapening\s*:\s*(Zie studieplan|Wordt niet meegeleverd|[^\n\.]{1,120})",
        r"Armatures sup[ée]rieures\s*:\s*(Voir plan de l[' ]ing[ée]nieur|[^\n\.]{1,120})",
        r"boven[\-\s]?wapeningsnet\s*150\s*/\s*150\s*/\s*(\d+)\s*/\s*(\d+)",
    ]:
        m = re.search(pat, compact_text if "boven" in pat else combined_text, re.I)
        if m:
            if len(m.groups()) == 2 and m.group(1) == m.group(2):
                top_mesh_note = f"B{m.group(1)}-150"
            else:
                top_mesh_note = clean_spaces(m.group(1))
            if top_mesh_note:
                break

    fire = None
    fire_patterns = [
        r"(REI\s*\d+)",
        r"Standaard brandweerstand\s*(\d+)\s*uur",
        r"\bRf\s*min\b",
    ]
    for pat in fire_patterns:
        m = re.search(pat, compact_text, re.I)
        if not m:
            continue
        if pat == r"Standaard brandweerstand\s*(\d+)\s*uur":
            fire = f"R{int(m.group(1)) * 60}"
        elif pat == r"\bRf\s*min\b":
            fire = "R60"
        else:
            fire = clean_spaces(m.group(1)).upper()
        break

    return {"concrete": concrete, "supplier_steel": steel, "top_mesh_note": top_mesh_note, "fire_default": fire}


def finalize_row(row):
    row["langs_cm2m"] = round(row["langs_mm2m"] / 100.0, 2)
    row["dwars_cm2m"] = round(row["dwars_mm2m"] / 100.0, 2)
    row["plate_size"] = f"{row['length']} x {row['width']}"
    return row



def _int_from_text(value):
    m = re.search(r"-?\d+", str(value or "").replace("±", ""))
    return int(m.group(0)) if m else None


def _split_nonempty_lines(value):
    return [ln.strip() for ln in str(value or "").splitlines() if ln and ln.strip()]




def _word_center_x(word):
    return (float(word[0]) + float(word[2])) / 2.0


def _word_center_y(word):
    return (float(word[1]) + float(word[3])) / 2.0


def _build_plate_column_bounds(plate_columns):
    bounds = []
    xs = [x for _, x in plate_columns]
    if len(xs) == 1:
        x = xs[0]
        return [(plate_columns[0][0], x - 10.0, x + 10.0)]

    for i, (plate, x) in enumerate(plate_columns):
        if i == 0:
            half = abs(xs[i] - xs[i + 1]) / 2.0
            left = x - half
            right = (x + xs[i + 1]) / 2.0
        elif i == len(xs) - 1:
            half = abs(xs[i - 1] - xs[i]) / 2.0
            left = (xs[i - 1] + x) / 2.0
            right = x + half
        else:
            left = (xs[i - 1] + x) / 2.0
            right = (x + xs[i + 1]) / 2.0
        bounds.append((plate, min(left, right), max(left, right)))
    return bounds


def _assign_words_to_plate_columns(words, bounds):
    by_plate = {}
    for plate, _, _ in bounds:
        by_plate[plate] = []

    for word in words:
        x = _word_center_x(word)
        assigned_plate = None
        nearest_plate = None
        nearest_dist = None

        for plate, x0, x1 in bounds:
            if x0 <= x <= x1:
                assigned_plate = plate
                break
            center = (x0 + x1) / 2.0
            dist = abs(x - center)
            if nearest_dist is None or dist < nearest_dist:
                nearest_dist = dist
                nearest_plate = plate

        if assigned_plate is None:
            assigned_plate = nearest_plate

        if assigned_plate is not None:
            by_plate.setdefault(assigned_plate, []).append(word)

    return by_plate


def _extract_van_thuyne_rows_from_words(page, full_text, meta):
    words = page.get_text("words", sort=False)
    if not words:
        return []

    overview_candidates = sorted(
        [
            w for w in words
            if str(w[4]).strip().lower().startswith("overzichtstabel")
        ],
        key=lambda w: (_word_center_y(w), _word_center_x(w)),
    )

    def _try_anchor(overview_anchor):
        overview_x = _word_center_x(overview_anchor)
        overview_y = _word_center_y(overview_anchor)

        breed_matches = [
            w for w in words
            if str(w[4]).strip().lower().startswith("breedvloerplaten")
            and abs(_word_center_x(w) - overview_x) <= 140
            and 0 <= (_word_center_y(w) - overview_y) <= 120
        ]
        if not breed_matches:
            return []

        nr_candidates = [
            w for w in words
            if str(w[4]).strip().lower().startswith("nr")
            and abs(_word_center_y(w) - overview_y) <= 40
            and _word_center_x(w) < overview_x
            and _word_center_x(w) > overview_x - 160
        ]
        if not nr_candidates:
            return []

        nr_anchor = min(
            nr_candidates,
            key=lambda w: (
                abs(_word_center_y(w) - overview_y),
                abs(_word_center_x(w) - overview_x),
            ),
        )

        header_x_min = max(0.0, min(overview_x, _word_center_x(nr_anchor)) - 420.0)
        header_plate_words = [
            w for w in words
            if re.fullmatch(r"\d+", str(w[4]).strip())
            and abs(_word_center_y(w) - _word_center_y(nr_anchor)) <= 15
            and header_x_min <= _word_center_x(w) < _word_center_x(nr_anchor) - 5
        ]
        if not header_plate_words:
            return []

        plate_columns = {}
        for word in header_plate_words:
            plate_no = _int_from_text(word[4])
            if plate_no is None or plate_no <= 0:
                continue
            cx = _word_center_x(word)
            prev = plate_columns.get(plate_no)
            if prev is None or cx > prev:
                plate_columns[plate_no] = cx

        if len(plate_columns) < 5:
            return []

        ordered_columns = sorted(plate_columns.items(), key=lambda item: item[0])
        bounds = _build_plate_column_bounds(ordered_columns)
        min_x = min(x for _, x in ordered_columns)
        max_x = max(x for _, x in ordered_columns)

        label_tokens = [
            ("predal_cm", "Predal"),
            ("opstort_cm", "Opstort"),
            ("total_cm", "Totale"),
            ("finish", "Afwer-"),
            ("length_cm", "Lengte"),
            ("width_cm", "Breedte"),
            ("fire_min", "Rf"),
            ("langs_mm2m", "Hoofd-"),
            ("dwars_mm2m", "Dwars"),
            ("tralie_h", "Tralie-"),
            ("weight_kg", "Gewicht"),
        ]

        label_x_min = _word_center_x(nr_anchor) - 40.0
        label_x_max = max(overview_x, _word_center_x(nr_anchor)) + 25.0
        label_y = {}

        for key, token in label_tokens:
            matches = [
                w for w in words
                if str(w[4]).strip() == token
                and label_x_min <= _word_center_x(w) <= label_x_max
                and _word_center_y(w) >= overview_y - 10
                and _word_center_y(w) <= overview_y + 420
            ]
            if not matches:
                return []
            label_y[key] = min(_word_center_y(w) for w in matches)

        ordered_labels = [key for key, _ in label_tokens]
        y_values = [label_y[key] for key in ordered_labels]
        bands = {}
        for idx, key in enumerate(ordered_labels):
            lower = (y_values[idx - 1] + y_values[idx]) / 2.0 if idx > 0 else y_values[idx] - 20.0
            upper = (y_values[idx] + y_values[idx + 1]) / 2.0 if idx < len(y_values) - 1 else y_values[idx] + 25.0
            bands[key] = (lower, upper)

        row_tokens = {}
        for key, (y0, y1) in bands.items():
            selected = [
                w for w in words
                if y0 <= _word_center_y(w) <= y1
                and (min_x - 15.0) <= _word_center_x(w) <= (max_x + 15.0)
            ]
            row_tokens[key] = _assign_words_to_plate_columns(selected, bounds)

        rows = []
        env_value = "EE2" if re.search(r"Omgevingsklasse\s*EE2", full_text or "", re.I) else None

        for plate, _x in ordered_columns:
            def _cell_text(row_key):
                items = row_tokens.get(row_key, {}).get(plate, [])
                if not items:
                    return ""
                items = sorted(items, key=lambda w: (_word_center_y(w), _word_center_x(w)))
                return " ".join(str(w[4]).strip() for w in items if str(w[4]).strip())

            predal_cm = _int_from_text(_cell_text("predal_cm"))
            total_cm = _int_from_text(_cell_text("total_cm"))
            length_cm = _int_from_text(_cell_text("length_cm"))
            width_cm = _int_from_text(_cell_text("width_cm"))
            fire_min = _int_from_text(_cell_text("fire_min"))
            langs_mm2m = _int_from_text(_cell_text("langs_mm2m"))
            dwars_mm2m = _int_from_text(_cell_text("dwars_mm2m"))
            tralie_h = _int_from_text(_cell_text("tralie_h"))
            weight_kg = _int_from_text(_cell_text("weight_kg"))
            finish = clean_spaces(_cell_text("finish")) or None

            if None in (predal_cm, total_cm, length_cm, width_cm, langs_mm2m, dwars_mm2m):
                continue

            row = {
                "plate": plate,
                "article": None,
                "tralie_h": tralie_h,
                "floor_thk": total_cm * 10,
                "length": length_cm * 10,
                "predal_thk": predal_cm * 10,
                "width": width_cm * 10,
                "langs_mm2m": langs_mm2m,
                "dwars_mm2m": dwars_mm2m,
                "weight_kg": weight_kg,
                "type": finish,
                "uw1": None,
                "uw2": None,
                "cover": None,
                "fire": (f"R{fire_min}" if fire_min is not None else meta.get("fire_default")),
                "env": env_value,
                "concrete": meta.get("concrete"),
                "supplier_format": "Van Thuyne word-grid parser",
            }
            rows.append(finalize_row(row))

        rows.sort(key=lambda x: x["plate"])
        return rows if len(rows) >= 5 else []

    for overview_anchor in overview_candidates:
        rows = _try_anchor(overview_anchor)
        if rows:
            return rows

    return []


def parse_van_thuyne_table(pdf_path, full_text):
    meta = parse_common_supplier_meta(full_text)
    rows = []
    parser_label = "Van Thuyne overview table parser"

    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                try:
                    tables = page.find_tables().tables
                except Exception:
                    tables = []

                for table in tables:
                    try:
                        data = table.extract()
                    except Exception:
                        continue
                    if not data or len(data) < 3:
                        continue

                    header_blob = " ".join(
                        " ".join("" if cell is None else str(cell) for cell in row)
                        for row in data[:3]
                    )
                    if "Overzichtstabel Breedvloerplaten" not in header_blob:
                        continue

                    table_row = data[2]
                    if len(table_row) < 12:
                        continue

                    columns = [_split_nonempty_lines(cell) for cell in table_row[:12]]
                    lengths = [len(col) for col in columns[:10] if col]
                    if not lengths:
                        continue
                    row_count = max(lengths)

                    for col in columns:
                        if len(col) < row_count:
                            col.extend([None] * (row_count - len(col)))

                    for i in range(row_count):
                        plate = _int_from_text(columns[0][i])
                        predal_cm = _int_from_text(columns[1][i])
                        total_cm = _int_from_text(columns[3][i])
                        length_cm = _int_from_text(columns[5][i])
                        width_cm = _int_from_text(columns[6][i])
                        fire_min = _int_from_text(columns[7][i])
                        langs_mm2m = _int_from_text(columns[8][i])
                        dwars_mm2m = _int_from_text(columns[9][i])

                        if None in (plate, predal_cm, total_cm, length_cm, width_cm, langs_mm2m, dwars_mm2m):
                            continue

                        row = {
                            "plate": plate,
                            "article": None,
                            "tralie_h": _int_from_text(columns[10][i]) if len(columns) > 10 else None,
                            "floor_thk": total_cm * 10,
                            "length": length_cm * 10,
                            "predal_thk": predal_cm * 10,
                            "width": width_cm * 10,
                            "langs_mm2m": langs_mm2m,
                            "dwars_mm2m": dwars_mm2m,
                            "weight_kg": _int_from_text(columns[11][i]) if len(columns) > 11 else None,
                            "type": columns[4][i] if len(columns) > 4 else None,
                            "uw1": None,
                            "uw2": None,
                            "cover": None,
                            "fire": (f"R{fire_min}" if fire_min is not None else meta.get("fire_default")),
                            "env": "EE2" if re.search(r"Omgevingsklasse\s*EE2", full_text or "", re.I) else None,
                            "concrete": meta.get("concrete"),
                            "supplier_format": parser_label,
                        }
                        rows.append(finalize_row(row))

                if rows:
                    break

                fallback_rows = _extract_van_thuyne_rows_from_words(page, full_text, meta)
                if fallback_rows:
                    rows = fallback_rows
                    parser_label = "Van Thuyne word-grid parser"
                    break
    except Exception:
        rows = []

    rows.sort(key=lambda x: x["plate"])
    meta["rows"] = rows
    meta["supplier_format"] = parser_label
    return meta


def parse_predalco_table(pages, full_text):
    meta = parse_common_supplier_meta(full_text, _pages_word_text(pages))
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
    meta = parse_common_supplier_meta(full_text, _pages_word_text(pages))
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

    van_thuyne_data = parse_van_thuyne_table(pdf_path, full_text)
    if van_thuyne_data["rows"]:
        data = van_thuyne_data
        supplier_format = "van_thuyne_table"
    else:
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
    data["source_pdf_path"] = pdf_path
    return data


def _storey_label_token(storey_hint):
    if not storey_hint or not str(storey_hint).startswith("LEVEL_"):
        return None
    try:
        lvl = int(str(storey_hint).split("_", 1)[1])
    except Exception:
        return None
    return f"/B{lvl}."


def _iter_predal_labels_from_block_text(text, storey_hint=None):
    txt = str(text or "")
    if not re.search(r':\s*\d+\s*x\s*\d+\b', txt, re.I):
        return []
    if re.search(r':\s*\d+\s*x\s*\d+\s*x\s*\d+', txt, re.I):
        return []
    token = _storey_label_token(storey_hint)
    labels = []
    for m in re.finditer(r'\b([A-Z]/B-?\d+\.\d+[A-Z]?)\b', txt, re.I):
        label = m.group(1).upper()
        if token and token not in label:
            continue
        labels.append(label)
    return labels


def _extract_predal_label_positions(pdf_path, storey_hint=None):
    positions = {}
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                block_fallback = {}
                for block in page.get_text("blocks", sort=False):
                    block_labels = _iter_predal_labels_from_block_text(block[4], storey_hint=storey_hint)
                    if not block_labels:
                        continue
                    entry = {
                        "bbox": (block[0], block[1], block[2], block[3]),
                        "center": ((block[0] + block[2]) / 2.0, (block[1] + block[3]) / 2.0),
                        "page": page.number,
                    }
                    for label in block_labels:
                        block_fallback[label] = entry

                for label, fallback in block_fallback.items():
                    rects = page.search_for(label)
                    if rects:
                        rect = rects[0]
                        positions[label] = {
                            "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                            "center": ((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0),
                            "page": page.number,
                        }
                    else:
                        positions[label] = fallback
    except Exception:
        return {}
    return positions


def _extract_design_label_family_map(pdf_path, storey_hint=None):
    label_positions = _extract_predal_label_positions(pdf_path, storey_hint=storey_hint)
    families = []
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                for block in page.get_text("blocks", sort=False):
                    parsed = _parse_design_families_from_text(clean_spaces(block[4]))
                    if not parsed:
                        continue
                    x0, y0, x1, y1 = block[:4]
                    center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
                    for fam in parsed:
                        families.append({"family": tuple(fam), "center": center, "page": page.number})
    except Exception:
        return {}, label_positions

    label_family_map = {}
    for label, entry in label_positions.items():
        same_page = [f for f in families if f["page"] == entry["page"]] or families
        if not same_page:
            continue
        nearest = min(
            same_page,
            key=lambda item: math.hypot(
                entry["center"][0] - item["center"][0],
                entry["center"][1] - item["center"][1],
            ),
        )
        label_family_map[label] = nearest["family"]
    return label_family_map, label_positions


def _extract_supplier_plan_plate_positions(pdf_path):
    positions = {}
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                page_text = page.get_text("text", sort=False)
                plate_numbers = sorted(set(int(n) for n in re.findall(r'\.(\d{1,3})\.G\b', page_text)))
                for plate in plate_numbers:
                    rects = page.search_for(f".{plate}.G")
                    if rects:
                        rect = rects[0]
                        positions[plate] = {
                            "bbox": (rect.x0, rect.y0, rect.x1, rect.y1),
                            "center": ((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0),
                            "page": page.number,
                        }
                        continue
                    for block in page.get_text("blocks", sort=False):
                        if re.search(rf'\.{plate}\.G\b', str(block[4] or "")):
                            positions[plate] = {
                                "bbox": (block[0], block[1], block[2], block[3]),
                                "center": ((block[0] + block[2]) / 2.0, (block[1] + block[3]) / 2.0),
                                "page": page.number,
                            }
                            break
    except Exception:
        return {}
    return positions


def _fit_affine_transform(source_points, target_points):
    if len(source_points) < 3 or len(target_points) < 3 or len(source_points) != len(target_points):
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


def _apply_affine_transform(point, params):
    if not params:
        return point
    x, y = point
    a, b, c, d, e, f = params
    return (a * x + b * y + c, d * x + e * y + f)


def _iter_page_line_segments(drawings):
    for drawing in drawings or []:
        for item in drawing.get("items", []):
            if not item:
                continue
            op = item[0]
            if op == "l":
                p1, p2 = item[1], item[2]
                yield (float(p1.x), float(p1.y), float(p2.x), float(p2.y))
            elif op == "re":
                rect = item[1]
                yield (float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y0))
                yield (float(rect.x1), float(rect.y0), float(rect.x1), float(rect.y1))
                yield (float(rect.x1), float(rect.y1), float(rect.x0), float(rect.y1))
                yield (float(rect.x0), float(rect.y1), float(rect.x0), float(rect.y0))


def _point_inside_bbox(point, bbox, margin=2.0):
    x, y = point
    x0, y0, x1, y1 = bbox
    return (x0 - margin) <= x <= (x1 + margin) and (y0 - margin) <= y <= (y1 + margin)


def _detect_family_anchor_from_drawings(bbox, drawings):
    best = None
    x0, y0, x1, y1 = bbox
    search_rect = fitz.Rect(x0 - 6, y0 - 6, x1 + 6, y1 + 6)

    for seg in _iter_page_line_segments(drawings):
        sx0, sy0, sx1, sy1 = seg
        seg_rect = fitz.Rect(min(sx0, sx1), min(sy0, sy1), max(sx0, sx1), max(sy0, sy1))
        if not seg_rect.intersects(search_rect):
            continue

        p1 = (sx0, sy0)
        p2 = (sx1, sy1)
        inside1 = _point_inside_bbox(p1, bbox)
        inside2 = _point_inside_bbox(p2, bbox)
        if inside1 == inside2:
            continue

        outside = p2 if inside1 else p1
        dist = math.hypot(sx1 - sx0, sy1 - sy0)
        if best is None or dist > best[0]:
            best = (dist, outside)

    return best[1] if best else None


def _extract_design_family_points(pdf_path, storey_hint=None):
    points = []
    try:
        with fitz.open(pdf_path) as doc:
            for page in doc:
                drawings = page.get_drawings()
                for block in page.get_text("blocks", sort=False):
                    parsed = _parse_design_families_from_text(clean_spaces(block[4]))
                    if not parsed:
                        continue
                    bbox = (float(block[0]), float(block[1]), float(block[2]), float(block[3]))
                    center = ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)
                    anchor = _detect_family_anchor_from_drawings(bbox, drawings)
                    point = anchor or center
                    for fam in parsed:
                        points.append(
                            {
                                "family": tuple(fam),
                                "point": point,
                                "center": center,
                                "bbox": bbox,
                                "page": page.number,
                            }
                        )
    except Exception:
        return []
    return points


def _nearest_design_family_point(point, family_points, page=None):
    if not family_points:
        return None
    candidates = [fp for fp in family_points if page is None or fp.get("page") == page] or list(family_points)
    return min(
        candidates,
        key=lambda item: math.hypot(point[0] - item["point"][0], point[1] - item["point"][1]),
    )


def _design_family_key(fam):
    if not fam:
        return None
    return (
        round(float(fam[0]), 2),
        round(float(fam[1]), 2),
        int(fam[2]) if fam[2] is not None else None,
        int(fam[3]) if fam[3] is not None else None,
    )


def _supplier_exact_family_key(row, design_family_keys):
    if not row:
        return None
    fam = (
        round(float(row.get("langs_cm2m") or 0.0), 2),
        round(float(row.get("dwars_cm2m") or 0.0), 2),
        None,
        None,
    )
    return fam if fam in design_family_keys else None


def _build_supplier_family_components(transformed_positions, supplier_rows_by_plate, design_family_keys, max_dist=320.0):
    adjacency = {}
    supplier_family_by_plate = {}

    for plate, point in transformed_positions.items():
        row = supplier_rows_by_plate.get(int(plate))
        sfam = _supplier_exact_family_key(row, design_family_keys)
        supplier_family_by_plate[int(plate)] = sfam
        adjacency[int(plate)] = set()

    plates = sorted(transformed_positions)
    for i, plate_a in enumerate(plates):
        fam_a = supplier_family_by_plate.get(int(plate_a))
        if not fam_a:
            continue
        pa = transformed_positions[plate_a]
        for plate_b in plates[i + 1:]:
            fam_b = supplier_family_by_plate.get(int(plate_b))
            if fam_b != fam_a:
                continue
            pb = transformed_positions[plate_b]
            if math.hypot(pa[0] - pb[0], pa[1] - pb[1]) <= max_dist:
                adjacency[int(plate_a)].add(int(plate_b))
                adjacency[int(plate_b)].add(int(plate_a))

    components = []
    seen = set()
    for plate in sorted(adjacency):
        if plate in seen:
            continue
        stack = [plate]
        comp = []
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            comp.append(cur)
            stack.extend(sorted(adjacency.get(cur, ())))
        components.append(sorted(comp))

    return components, supplier_family_by_plate


def _smooth_registered_plate_families(initial_map, transformed_positions, supplier_rows_by_plate, design_families):
    design_family_keys = {_design_family_key(fam) for fam in design_families or []}
    components, supplier_family_by_plate = _build_supplier_family_components(
        transformed_positions,
        supplier_rows_by_plate,
        design_family_keys,
    )

    smoothed = dict(initial_map)

    for comp in components:
        if len(comp) < 3:
            continue
        supplier_family = supplier_family_by_plate.get(comp[0])
        if not supplier_family:
            continue

        init_families = [_design_family_key(smoothed.get(plate)) for plate in comp if smoothed.get(plate)]
        if not init_families:
            continue

        distinct_init = {fam for fam in init_families if fam is not None}
        supplier_hits = sum(1 for fam in init_families if fam == supplier_family)

        # Only use supplier-consensus smoothing when the registered design mapping is split
        # AND at least one plate in the contiguous group already lands on that same family.
        # This preserves earlier edited-file fixes where isolated changed plates should not
        # redefine the design family display.
        if len(distinct_init) >= 2 and supplier_hits >= 1:
            for plate in comp:
                smoothed[int(plate)] = supplier_family

    return smoothed

def _build_plan_registered_plate_family_map(design, supplier):
    design_pdf = design.get("source_pdf_path")
    supplier_pdf = supplier.get("source_pdf_path")
    storey_hint = design.get("storey_hint")

    if not design_pdf or not supplier_pdf:
        return {}

    design_family_points = _extract_design_family_points(design_pdf, storey_hint=storey_hint)
    design_label_positions = _extract_predal_label_positions(design_pdf, storey_hint=storey_hint)
    supplier_label_positions = _extract_predal_label_positions(supplier_pdf, storey_hint=storey_hint)
    supplier_plate_positions = _extract_supplier_plan_plate_positions(supplier_pdf)

    common_labels = sorted(set(design_label_positions.keys()) & set(supplier_label_positions.keys()))
    if len(common_labels) < 4 or not supplier_plate_positions or not design_family_points:
        return {}

    source_points = [supplier_label_positions[label]["center"] for label in common_labels]
    target_points = [design_label_positions[label]["center"] for label in common_labels]
    affine = _fit_affine_transform(source_points, target_points)
    if not affine:
        return {}

    transformed_positions = {
        int(plate): _apply_affine_transform(entry["center"], affine)
        for plate, entry in supplier_plate_positions.items()
    }

    plate_family_map = {}
    for plate, transformed in transformed_positions.items():
        nearest = _nearest_design_family_point(transformed, design_family_points)
        if nearest:
            plate_family_map[int(plate)] = nearest["family"]

    supplier_rows_by_plate = {int(row.get("plate") or 0): row for row in supplier.get("rows", [])}
    return _smooth_registered_plate_families(
        plate_family_map,
        transformed_positions,
        supplier_rows_by_plate,
        design.get("families") or [],
    )


def _select_design_family_for_supplier_row_display(row, design_families, rounding_tol=0.10):
    supplier_hw = float(row.get("langs_cm2m") or 0.0)
    supplier_dw = float(row.get("dwars_cm2m") or 0.0)
    candidates = []

    for fam in design_families or []:
        hw, dw, vw_d, vw_l = fam
        if supplier_hw + rounding_tol >= hw:
            hw_surplus = max(0.0, supplier_hw - hw)
            dw_delta = abs(supplier_dw - dw)
            candidates.append((hw_surplus, dw_delta, -hw, -dw, fam))

    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
        return candidates[0][4]

    fallback = []
    for fam in design_families or []:
        hw, dw, vw_d, vw_l = fam
        fallback.append((abs(supplier_hw - hw), abs(supplier_dw - dw), -hw, -dw, fam))

    if not fallback:
        return None

    fallback.sort(key=lambda item: (item[0], item[1], item[2], item[3]))
    return fallback[0][4]


def _supplier_satisfies_design_family(row, family, rounding_tol=0.10):
    if not family:
        return False
    supplier_hw = float(row.get("langs_cm2m") or 0.0)
    supplier_dw = float(row.get("dwars_cm2m") or 0.0)
    hw, dw, vw_d, vw_l = family
    return supplier_hw + rounding_tol >= hw and supplier_dw + rounding_tol >= dw


def _group_supplier_rows_by_length_sequence(rows, split_jump_mm=1500):
    if not rows:
        return []
    ordered = sorted(rows, key=lambda r: int(r.get("plate") or 0))
    groups = [[ordered[0]]]
    for row in ordered[1:]:
        prev = groups[-1][-1]
        prev_len = int(prev.get("length") or 0)
        cur_len = int(row.get("length") or 0)
        if prev_len and cur_len and abs(cur_len - prev_len) > split_jump_mm:
            groups.append([row])
        else:
            groups[-1].append(row)
    return groups


def _cluster_design_families_for_plate_display(rows, design_families):
    families = sorted({tuple(f) for f in (design_families or [])}, key=lambda f: (float(f[0]), float(f[1])))
    if len(families) < 3 or len(rows or []) < 6:
        return {}

    groups = _group_supplier_rows_by_length_sequence(rows)
    if not groups:
        return {}

    lowest = families[0]
    highest = families[-1]
    remaining = families[1:-1]

    assignments = {}

    # 1) Special pass-plate cluster: same / similar long length with one narrow strip + one normal width plate.
    for group in groups:
        widths = [int(r.get("width") or 0) for r in group]
        lengths = [int(r.get("length") or 0) for r in group]
        if not widths or not lengths:
            continue
        if max(lengths) >= 5000 and min(widths) <= 800 and max(widths) >= 1800 and len(group) >= 2:
            for row in group:
                assignments[int(row["plate"])] = highest
            break

    # 2) Remaining groups by geometry-only length band.
    remaining_groups = [g for g in groups if int(g[0]["plate"]) not in assignments]
    long_families = [f for f in remaining if float(f[0]) > float(lowest[0])]
    mid_family = long_families[0] if long_families else (remaining[0] if remaining else highest)
    high_family = long_families[-1] if long_families else highest

    for group in remaining_groups:
        lengths = [int(r.get("length") or 0) for r in group if r.get("length")]
        if not lengths:
            continue
        mean_len = sum(lengths) / float(len(lengths))
        if mean_len < 3000:
            fam = lowest
        elif mean_len < 5000:
            fam = mid_family
        else:
            fam = high_family
        for row in group:
            assignments[int(row["plate"])] = fam

    return assignments




def _is_confident_cluster_plate_family_map(cluster_map, rows, design_families):
    if not cluster_map or not rows or not design_families:
        return False

    assigned = [cluster_map.get(int(r.get("plate") or 0)) for r in rows if cluster_map.get(int(r.get("plate") or 0))]
    distinct_cluster = {_design_family_key(f) for f in assigned if f}
    if len(distinct_cluster) < 2:
        return False

    design_family_keys = {_design_family_key(f) for f in design_families or []}
    supplier_exact = []
    mismatches = 0
    comparable = 0

    for row in rows:
        plate = int(row.get("plate") or 0)
        mapped = cluster_map.get(plate)
        exact = _supplier_exact_family_key(row, design_family_keys)
        if exact:
            supplier_exact.append(exact)
            comparable += 1
            if _design_family_key(mapped) != exact:
                mismatches += 1

    supplier_exact_distinct = set(supplier_exact)
    if len(supplier_exact_distinct) >= 2:
        if len(distinct_cluster) < 2:
            return False
        if comparable and (mismatches / float(comparable)) > 0.35:
            return False

    dominant = max(
        (sum(1 for fam in assigned if _design_family_key(fam) == fam_key) for fam_key in distinct_cluster),
        default=0,
    )
    if assigned and (dominant / float(len(assigned))) > 0.80 and len(distinct_cluster) < min(3, max(2, len(supplier_exact_distinct) or 2)):
        return False

    return True

def _match_design_family_for_supplier_row(row, design_families, rounding_tol=0.10):
    supplier_hw = float(row.get("langs_cm2m") or 0.0)
    supplier_dw = float(row.get("dwars_cm2m") or 0.0)
    candidates = []

    for fam in design_families or []:
        hw, dw, vw_d, vw_l = fam
        if supplier_hw + rounding_tol >= hw and supplier_dw + rounding_tol >= dw:
            surplus = (supplier_hw - hw) + 0.35 * (supplier_dw - dw)
            candidates.append((surplus, -hw, -dw, fam))

    if not candidates:
        return None

    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def build_report_pdf_bytes(design, supplier, project_title="", logo_path=None, report_orientation="landscape", report_date_str=""):
    rows = supplier["rows"]
    design_families = list(design.get("families", []))
    plate_family_map = _build_plan_registered_plate_family_map(design, supplier)
    if not plate_family_map:
        cluster_map = _cluster_design_families_for_plate_display(rows, design_families)
        if _is_confident_cluster_plate_family_map(cluster_map, rows, design_families):
            plate_family_map = cluster_map

    comparison_rows = []
    matched_ok = 0
    for row in rows:
        plate_no = int(row.get("plate") or 0)
        mapped_family = plate_family_map.get(plate_no)
        display_family = mapped_family or _select_design_family_for_supplier_row_display(row, design_families)
        matched_family = mapped_family if mapped_family and _supplier_satisfies_design_family(row, mapped_family) else _match_design_family_for_supplier_row(row, design_families)
        is_match = False
        if mapped_family:
            is_match = _supplier_satisfies_design_family(row, mapped_family)
        else:
            is_match = matched_family is not None
        row["status"] = "OK" if is_match else "CHECK"
        row["matched_design_family"] = matched_family
        row["display_design_family"] = display_family
        row["mapped_design_family"] = mapped_family
        if is_match:
            matched_ok += 1

        if display_family:
            design_note = f"HW {display_family[0]:.2f} / DW {display_family[1]:.2f}"
        else:
            design_note = "No readable family found on selected design storey"

        comparison_rows.append(
            [
                str(row["plate"]),
                row["plate_size"],
                design_note,
                f"Langs {row['langs_mm2m']} / Dwars {row['dwars_mm2m']}",
                row["status"],
            ]
        )

    predal_thicknesses = sorted({row["predal_thk"] for row in rows if row.get("predal_thk") is not None})
    total_thicknesses = sorted({row["floor_thk"] for row in rows if row.get("floor_thk") is not None})
    supplier_concretes = sorted({str(row["concrete"]).upper() for row in rows if row.get("concrete")})
    supplier_fires = sorted({str(row["fire"]).upper() for row in rows if row.get("fire")})

    def _parse_concrete_strength(c):
        m = re.match(r"C(\d+)/(\d+)", str(c or "").upper())
        return (int(m.group(1)), int(m.group(2))) if m else None

    design_concrete = _parse_concrete_strength(design["concrete"])
    supplier_concrete_vals = [_parse_concrete_strength(c) for c in supplier_concretes]
    supplier_concrete_vals = [c for c in supplier_concrete_vals if c]
    concrete_status = "CHECK"
    if design_concrete and supplier_concrete_vals:
        if all(c[0] >= design_concrete[0] and c[1] >= design_concrete[1] for c in supplier_concrete_vals):
            concrete_status = "OK"

    design_steel = normalize_grade(design["steel"])
    supplier_steel = normalize_grade(supplier["supplier_steel"])
    steel_status = (
        "OK"
        if design_steel and supplier_steel and (
            design_steel == supplier_steel
            or design_steel in supplier_steel
            or supplier_steel in design_steel
        )
        else "CHECK"
    )

    predal_status = "OK" if predal_thicknesses else "CHECK"
    total_status = "CHECK"
    if design.get("total_thickness_mm") and total_thicknesses:
        total_status = "OK" if all(t == design["total_thickness_mm"] for t in total_thicknesses) else "CHECK"

    mesh_status = "OK" if design.get("top_mesh") and supplier.get("top_mesh_note") and design["top_mesh"] in supplier["top_mesh_note"].upper() else "CHECK"

    design_fire = parse_fire_rating(design.get("fire_req"))
    supplier_fire_candidates = [parse_fire_rating(v) for v in supplier_fires]
    supplier_default_fire = parse_fire_rating(supplier.get("fire_default"))
    if supplier_default_fire is not None:
        supplier_fire_candidates.append(supplier_default_fire)
    supplier_fire_candidates = [v for v in supplier_fire_candidates if v is not None]
    fire_status = "CHECK"
    if design_fire is not None and supplier_fire_candidates:
        fire_status = "OK" if all(v >= design_fire for v in supplier_fire_candidates) else "CHECK"

    global_rows = [
        ["Detected supplier parser", "Auto detection", supplier.get("supplier_format", "Not found"), "OK" if rows else "CHECK"],
        ["Selected design storey", design.get("storey_hint") or "Full document fallback", design.get("storey_match_method") or "-", "OK" if design.get("storey_hint") else "CHECK"],
        ["Concrete class", f"{design['concrete'] or 'Not found'} minimum", ", ".join(supplier_concretes) or "Not found", concrete_status],
        ["Steel grade", design["steel"] or "Not found", supplier["supplier_steel"] or "Not found", steel_status],
        ["Predal thickness", "Supplier to determine (design note)" if design["supplier_det_note"] else "Design note not found", ", ".join(str(v) for v in predal_thicknesses) + " mm" if predal_thicknesses else "Not found", predal_status],
        ["Total slab thickness", (f"{design['total_thickness_mm']} mm" if design.get("total_thickness_mm") else (", ".join(design["slab_notes"]) if design["slab_notes"] else "Not clearly readable on design sheet")), ", ".join(str(v) for v in total_thicknesses) + " mm" if total_thicknesses else "Not found", total_status],
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
            bin_lines.append(f"{label}: n={len(bucket)}, langs avg={mean(bucket):.1f} mm²/m, range {min(bucket)}-{max(bucket)}")

    sanity_lines = [
        f"Detected parser: {supplier.get('supplier_format', 'Unknown')}.",
        f"Selected design storey: {design.get('storey_hint') or 'full document'} ({design.get('storey_match_method') or '-'}).",
        f"Parsed supplier plates: {len(rows)}." if rows else "No supplier plates could be parsed from the supplier PDF.",
        f"Readable family matches: {matched_ok} / {len(rows)}." if rows else "No plate-by-plate comparison could be completed.",
        f"Transverse reinforcement minimum check (>= 1/5 of main and >= 2.50 cm²/m): {'OK' if dwars_ok and all(dwars_ok) else 'CHECK'}.",
        "Geometric zone mapping, span direction, and supplier-specific plate splitting still require engineer review on the full drawing set.",
    ]
    if bin_lines:
        sanity_lines.append("Length-based reinforcement trend: " + " | ".join(bin_lines))

    design_total_note = f"{design['total_thickness_mm']} mm" if design.get("total_thickness_mm") else "not clearly readable"
    supplier_predal_note = ", ".join(str(v) for v in predal_thicknesses) + " mm" if predal_thicknesses else "not found"
    supplier_total_note = ", ".join(str(v) for v in total_thicknesses) + " mm" if total_thicknesses else "not found"

    conclusion_lines = [
        f"Plate-by-plate reinforcement check: {matched_ok} of {len(rows)} parsed supplier plates satisfy the selected design-storey readable family comparison." if rows else "Plate-by-plate reinforcement check: no supplier plates could be validated automatically.",
        f"Concrete check: supplier provides {', '.join(supplier_concretes) or 'not found'} against design minimum {design['concrete'] or 'not found'}; status {concrete_status}.",
        f"Build-up check: supplier predal thickness {supplier_predal_note} and total slab thickness {supplier_total_note} compared with the design note {design_total_note}; status {total_status}.",
        f"Mesh and fire review: design mesh requirement {design['top_mesh'] or 'not found'} and fire note {design['fire_req'] or 'not found'} should still be visually checked against the complete supplier drawing and architectural package.",
        "Final engineering action: use this report as a verification aid, then confirm zone boundaries, span direction, detailing around openings/supports, and any sheet-specific notes before approval for production.",
    ]

    is_landscape = (report_orientation or "landscape").lower() != "portrait"
    page_size = landscape(A3) if is_landscape else A3

    PREMIUM_NAVY = HexColor("#12263A")
    PREMIUM_GOLD = HexColor("#C9A96E")
    PREMIUM_BORDER = HexColor("#E2D8C7")
    PREMIUM_ROW = HexColor("#F8F3EA")
    PREMIUM_CHIP = HexColor("#F3ECE0")
    PREMIUM_TEXT = HexColor("#2C3440")
    PREMIUM_MUTED = HexColor("#6F7782")
    PREMIUM_PAGE = HexColor("#FBFAF7")

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=24 if is_landscape else 22, leading=29 if is_landscape else 26, textColor=PREMIUM_NAVY, spaceAfter=4))
    styles.add(ParagraphStyle(name="ReportSub", parent=styles["Normal"], fontName="Helvetica", fontSize=11.3, leading=14.4, textColor=PREMIUM_TEXT))
    styles.add(ParagraphStyle(name="SectionHead", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=15 if is_landscape else 13.6, leading=18 if is_landscape else 16.4, textColor=PREMIUM_NAVY, spaceAfter=0, spaceBefore=0))
    styles.add(ParagraphStyle(name="BodyX", parent=styles["Normal"], fontName="Helvetica", fontSize=10.2 if is_landscape else 9.4, leading=13.4 if is_landscape else 12.4, textColor=PREMIUM_TEXT))
    styles.add(ParagraphStyle(name="SmallX", parent=styles["Normal"], fontName="Helvetica", fontSize=8.7, leading=10.9, textColor=PREMIUM_MUTED))
    styles.add(ParagraphStyle(name="TableCell", parent=styles["Normal"], fontName="Helvetica", fontSize=9.4 if is_landscape else 8.6, leading=11.5 if is_landscape else 10.5, textColor=PREMIUM_TEXT))
    styles.add(ParagraphStyle(name="TableHead", parent=styles["Normal"], fontName="Helvetica-Bold", fontSize=9.8 if is_landscape else 9.0, leading=12 if is_landscape else 11, textColor=colors.white))

    pdf_buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        pdf_buffer,
        pagesize=page_size,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=(30 * mm if logo_path else 22 * mm),
        bottomMargin=14 * mm,
    )

    def _draw_common_frame(canvas, doc_obj):
        w, h = doc_obj.pagesize
        canvas.saveState()
        canvas.setFillColor(PREMIUM_PAGE)
        canvas.rect(0, 0, w, h, stroke=0, fill=1)
        canvas.setFillColor(PREMIUM_NAVY)
        canvas.rect(0, h - 6.5 * mm, w, 6.5 * mm, stroke=0, fill=1)
        canvas.setFillColor(PREMIUM_GOLD)
        canvas.rect(w - 58 * mm, h - 6.5 * mm, 58 * mm, 6.5 * mm, stroke=0, fill=1)
        canvas.setStrokeColor(PREMIUM_BORDER)
        canvas.setLineWidth(0.75)
        canvas.line(doc.leftMargin, 13 * mm, w - doc.rightMargin, 13 * mm)
        canvas.setFont("Helvetica", 8.7)
        canvas.setFillColor(PREMIUM_MUTED)
        canvas.drawRightString(w - doc.rightMargin, 8.5 * mm, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    def _draw_first_page(canvas, doc_obj):
        _draw_common_frame(canvas, doc_obj)
        if logo_path:
            w, h = doc_obj.pagesize
            canvas.saveState()
            try:
                reader = ImageReader(logo_path)
                iw, ih = reader.getSize()
                max_w = 92 * mm
                max_h = 28 * mm
                scale = min(max_w / float(iw), max_h / float(ih), 1.0)
                draw_w = iw * scale
                draw_h = ih * scale
                x = w - doc.rightMargin - draw_w
                y = h - draw_h - 8.5 * mm
                canvas.drawImage(reader, x, y, width=draw_w, height=draw_h, preserveAspectRatio=True, mask="auto")
            except Exception:
                pass
            canvas.restoreState()

    def _draw_later_pages(canvas, doc_obj):
        _draw_common_frame(canvas, doc_obj)

    title = project_title.strip() or "Predal reinforcement verification"
    safe_title = html.escape(title)

    def _section_chip(text):
        chip = LongTable([[Paragraph(text, styles["SectionHead"])]], colWidths=[doc.width])
        chip.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), PREMIUM_CHIP),
            ("BOX", (0, 0), (-1, -1), 0.65, PREMIUM_BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 10),
            ("RIGHTPADDING", (0, 0), (-1, -1), 10),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        return chip
    story = []
    story.append(Spacer(1, 4))
    story.append(Paragraph("Predal Reinforcement Verification Report", styles["ReportTitle"]))

    meta_rows = [[Paragraph(f"<b>Project</b>: {safe_title}", styles["ReportSub"])]]
    if report_date_str:
        meta_rows[0].append(Paragraph(f"<b>Date</b>: {report_date_str}", styles["ReportSub"]))
    else:
        meta_rows[0].append(Paragraph("<b>Date</b>: -", styles["ReportSub"]))
    meta_tbl = LongTable(meta_rows, colWidths=[doc.width * 0.68, doc.width * 0.32])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.70, PREMIUM_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, PREMIUM_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_tbl)
    story.append(Spacer(1, 10))

    story.append(_section_chip("Predal Reinforcement Comparison"))
    story.append(Spacer(1, 5))

    if is_landscape:
        comp_col_widths = [22 * mm, 58 * mm, 122 * mm, 132 * mm, 28 * mm]
        global_col_widths = [48 * mm, 96 * mm, 182 * mm, 26 * mm]
    else:
        comp_col_widths = [18 * mm, 44 * mm, 78 * mm, 90 * mm, 22 * mm]
        global_col_widths = [38 * mm, 64 * mm, 110 * mm, 20 * mm]

    comp_table_data = [[
        Paragraph("Plate", styles["TableHead"]),
        Paragraph("Plate size (mm)", styles["TableHead"]),
        Paragraph("Design reinforcement (cm²/m)", styles["TableHead"]),
        Paragraph("Supplier reinforcement (mm²/m)", styles["TableHead"]),
        Paragraph("Status", styles["TableHead"]),
    ]]
    for row in comparison_rows:
        comp_table_data.append([Paragraph(v, styles["TableCell"]) for v in row])

    comp_tbl = LongTable(comp_table_data, colWidths=comp_col_widths, repeatRows=1)
    comp_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PREMIUM_NAVY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, PREMIUM_GOLD),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BOX", (0, 0), (-1, -1), 0.55, PREMIUM_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, PREMIUM_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PREMIUM_ROW]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
    ]))
    for i, r in enumerate(comparison_rows, start=1):
        status = r[-1]
        if status == "OK":
            comp_tbl.setStyle(TableStyle([("TEXTCOLOR", (-1, i), (-1, i), HexColor("#166B45")), ("FONTNAME", (-1, i), (-1, i), "Helvetica-Bold")]))
        else:
            comp_tbl.setStyle(TableStyle([("TEXTCOLOR", (-1, i), (-1, i), HexColor("#A05A00")), ("FONTNAME", (-1, i), (-1, i), "Helvetica-Bold")]))
    story.append(comp_tbl)

    story.append(PageBreak())
    story.append(_section_chip("Global Parameter Comparison"))
    story.append(Spacer(1, 5))
    global_table_data = [[
        Paragraph("Parameter", styles["TableHead"]),
        Paragraph("Design requirement", styles["TableHead"]),
        Paragraph("Supplier provided", styles["TableHead"]),
        Paragraph("Status", styles["TableHead"]),
    ]]
    for row in global_rows:
        global_table_data.append([Paragraph(v, styles["TableCell"]) for v in row])

    global_tbl = LongTable(global_table_data, colWidths=global_col_widths, repeatRows=1)
    global_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), PREMIUM_NAVY),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, PREMIUM_GOLD),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("BOX", (0, 0), (-1, -1), 0.55, PREMIUM_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.35, PREMIUM_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PREMIUM_ROW]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5.5),
    ]))
    for i, r in enumerate(global_rows, start=1):
        status = r[-1]
        color = "#166B45" if status == "OK" else "#A05A00"
        global_tbl.setStyle(TableStyle([("TEXTCOLOR", (-1, i), (-1, i), HexColor(color)), ("FONTNAME", (-1, i), (-1, i), "Helvetica-Bold")]))
    story.append(global_tbl)
    story.append(Spacer(1, 10))

    story.append(_section_chip("Engineering Conclusion"))
    story.append(Spacer(1, 5))
    for line in conclusion_lines:
        story.append(Paragraph("• " + line, styles["BodyX"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Disclaimer: This report is based on automated extraction from the uploaded PDFs. A qualified engineer must still verify zone locations, detailing, and sheet-specific notes before approval.", styles["SmallX"]))

    doc.build(story, onFirstPage=_draw_first_page, onLaterPages=_draw_later_pages)
    pdf_buffer.seek(0)
    return pdf_buffer


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
    client_time_zone = (request.form.get("client_time_zone") or "").strip()
    report_orientation = (request.form.get("report_orientation") or "landscape").strip().lower()

    if report_orientation not in {"landscape", "portrait"}:
        report_orientation = "landscape"

    if not design_file or not supplier_file or not design_file.filename or not supplier_file.filename:
        return "Both PDF files are required.", 400

    if not is_allowed_pdf_filename(design_file.filename) or not is_allowed_pdf_filename(supplier_file.filename):
        return "Both uploaded files must be PDF documents.", 400

    if logo_file and getattr(logo_file, "filename", "") and not is_allowed_logo_filename(logo_file.filename):
        return "Logo must be a PNG or JPG image.", 400

    _ = client_time_zone  # reserved for future timezone-aware report metadata

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
            app.logger.warning("PDF processing failed: %s", exc)
            return str(exc), 400
        except Exception:
            app.logger.exception("Unexpected processing error")
            return "The uploaded files could not be processed. Please try a cleaner PDF export.", 400

        if not supplier["rows"]:
            return (
                "No supplier plates could be parsed from the supplier PDF. "
                f"Detected parser: {supplier.get('supplier_format', 'unknown')}. "
                "Try a cleaner PDF export or update the parser for this supplier layout."
            ), 400

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
