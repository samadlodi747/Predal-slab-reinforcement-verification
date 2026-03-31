
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
    :root{
      --bg:#eef3f9;
      --card:#ffffff;
      --line:#d7e1ee;
      --text:#142033;
      --muted:#617189;
      --primary:#153a63;
      --primary-2:#21558d;
      --soft:#f7fafd;
      --shadow:0 18px 45px rgba(16,32,58,.10);
      --radius:22px;
    }
    *{box-sizing:border-box}
    html,body{margin:0;padding:0}
    body{
      font-family:Arial,sans-serif;
      color:var(--text);
      background:
        radial-gradient(circle at top left, #f8fbff 0, #eef3f9 36%, #e9eff7 100%);
      min-height:100vh;
    }
    .page{
      max-width:1080px;
      margin:36px auto;
      padding:0 20px;
    }
    .shell{
      background:rgba(255,255,255,.78);
      border:1px solid rgba(215,225,238,.95);
      border-radius:28px;
      overflow:hidden;
      box-shadow:var(--shadow);
      backdrop-filter: blur(14px);
    }
    .hero{
      position:relative;
      padding:34px 34px 28px;
      background:
        linear-gradient(135deg, rgba(21,58,99,1) 0%, rgba(33,85,141,1) 100%);
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
    .hero p{
      margin:12px 0 0;
      max-width:700px;
      font-size:17px;
      line-height:1.5;
      color:rgba(255,255,255,.92);
    }
    .body{padding:30px}
    .top-row{
      display:grid;
      grid-template-columns:1.1fr .9fr;
      gap:18px;
      margin-bottom:18px;
    }
    .field-card,
    .mini-card{
      background:var(--card);
      border:1px solid var(--line);
      border-radius:20px;
      padding:18px;
      box-shadow:0 8px 24px rgba(14,25,42,.04);
    }
    .mini-card{
      display:flex;
      align-items:center;
      justify-content:center;
      text-align:center;
      min-height:100%;
      background:linear-gradient(180deg,#ffffff 0%, #f9fbfe 100%);
    }
    .mini-card strong{
      display:block;
      font-size:20px;
      margin-bottom:6px;
    }
    .mini-card span{
      color:var(--muted);
      font-size:14px;
      line-height:1.45;
    }
    label{
      display:block;
      font-size:14px;
      font-weight:700;
      margin-bottom:10px;
    }
    .text-input{
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
    .text-input:focus{
      border-color:#8fb2da;
      box-shadow:0 0 0 4px rgba(33,85,141,.10);
      background:#fff;
    }
    .upload-grid{
      display:grid;
      grid-template-columns:1fr 1fr;
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
      justify-content:space-between;
      gap:16px;
      margin-top:24px;
    }
    .subtle{
      color:var(--muted);
      font-size:13px;
    }
    .btn{
      appearance:none;
      border:none;
      border-radius:16px;
      padding:15px 22px;
      min-width:220px;
      background:linear-gradient(135deg,var(--primary) 0%, var(--primary-2) 100%);
      color:#fff;
      font-size:15px;
      font-weight:800;
      cursor:pointer;
      box-shadow:0 12px 24px rgba(21,58,99,.22);
      transition:transform .18s ease, box-shadow .18s ease, opacity .18s ease;
    }
    .btn:hover{
      transform:translateY(-1px);
      box-shadow:0 16px 30px rgba(21,58,99,.25);
    }
    .btn:disabled{
      opacity:.78;
      cursor:wait;
    }
    @media (max-width: 860px){
      .top-row,
      .upload-grid{grid-template-columns:1fr}
      .hero h1{font-size:32px}
      .actions{flex-direction:column; align-items:stretch}
      .btn{width:100%}
    }
  </style>
</head>
<body>
  <div class="page">
    <div class="shell">
      <div class="hero">
        <div class="hero-inner">
          <div class="badge">A3 PDF Report</div>
          <h1>Predal Reinforcement Verifier</h1>
          <p>Upload the structural design PDF and the supplier Predal PDF to generate a clean verification report.</p>
        </div>
      </div>

      <div class="body">
        <form id="verifyForm" method="post" action="/generate" enctype="multipart/form-data">
          <div class="top-row">
            <div class="field-card">
              <label for="project_title">Project title</label>
              <input class="text-input" type="text" id="project_title" name="project_title" placeholder="Example: 50 appartementen Abeelstraat - Blok A - Afdek +1">
            </div>
            <div class="mini-card">
              <div>
                <strong>2 PDFs in</strong>
                <span>1 A3 verification report out</span>
              </div>
            </div>
          </div>

          <div class="upload-grid">
            <div class="upload-card">
              <h3>Structural design PDF</h3>
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
              <label class="dropzone" for="supplier_pdf" id="supplierDrop">
                <div class="icon">🏗️</div>
                <strong>Choose or drop file</strong>
                <span>PDF only</span>
              </label>
              <input class="hidden-input" type="file" id="supplier_pdf" name="supplier_pdf" accept="application/pdf,.pdf" required>
              <div class="file-meta" id="supplierMeta">No file selected</div>
            </div>
          </div>

          <div class="actions">
            <div class="subtle">Upload both files and generate the report.</div>
            <button class="btn" id="submitBtn" type="submit">Generate verification PDF</button>
          </div>
        </form>
      </div>
    </div>
  </div>

  <script>
    function bindDropzone(inputId, metaId, zoneId){
      const input = document.getElementById(inputId);
      const meta = document.getElementById(metaId);
      const zone = document.getElementById(zoneId);

      function setMeta(file){
        if(file){
          meta.textContent = file.name;
          meta.classList.add("ready");
        }else{
          meta.textContent = "No file selected";
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
        if(!(lower.endsWith(".pdf") || file.type === "application/pdf")){
          meta.textContent = "Please use a PDF file";
          meta.classList.remove("ready");
          return;
        }
        const dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        setMeta(file);
      });
    }

    bindDropzone("design_pdf", "designMeta", "designDrop");
    bindDropzone("supplier_pdf", "supplierMeta", "supplierDrop");

    document.getElementById("verifyForm").addEventListener("submit", function(){
      const btn = document.getElementById("submitBtn");
      btn.disabled = true;
      btn.textContent = "Generating PDF...";
    });
  </script>
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
        return None
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

    prefix_re = re.compile(rf"\b{re.escape(prefix)}\d+\b", re.I)

    for page in pages:
        blocks = page["blocks"]
        storey_blocks = [b for b in blocks if prefix_re.search(clean_spaces(b[4]))]
        if not storey_blocks:
            continue
        zone = _bbox_expand(_bbox_union(storey_blocks), dx=220, dy=220)
        local_blocks = [b for b in blocks if _bbox_intersects((b[0], b[1], b[2], b[3]), zone)]
        local_text_parts.extend(clean_spaces(b[4]) for b in local_blocks if clean_spaces(b[4]))

    return "\n".join(local_text_parts)


def _pages_word_text(pages):
    return " ".join(str(w[4]) for page in pages for w in page.get("words", []))

def _extract_design_total_thickness_mm(text):
    txt = clean_spaces(text or "")
    buildup = re.findall(r"Predallen\s+(\d+)\s*\+\s*(\d+)", txt, re.I)
    totals = [(int(a) + int(b)) * 10 for a, b in buildup]
    if totals:
        return _most_common(totals)

    # Prefer bk/ok level differences on predal notes: bk - ok = total slab thickness in cm.
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
            # Take the largest plausible thickness in the local window; avoids picking 8 from B8-150.
            notes.append(max(nums))
    if notes:
        return _most_common(notes) * 10
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
    storey_hint = normalize_storey_key(supplier_full_text or "")

    local_text = _collect_storey_local_text(pages, storey_hint)
    search_text = local_text or full_text

    families = set()

    if local_text:
        families |= _parse_design_families_from_text(local_text)

    if not families:
        for page in pages:
            for block in page["blocks"]:
                block_text = clean_spaces(block[4])
                families |= _parse_design_families_from_text(block_text)

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

    fire_match = re.search(r"Brandweerstand:\s*([^\n]+)", full_text, re.I)
    if fire_match:
        fire_req = clean_spaces(fire_match.group(1))

    slab_notes = sorted(set(re.findall(r"Predallen\s+\d\s*\+\s*\d+", search_text, re.I)))
    supplier_det_note = "supplier" if re.search(r"Dikte van de predalplaat.*leverancier", full_text, re.I) else None
    total_thickness_mm = _extract_design_total_thickness_mm(search_text)

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
        "local_text": local_text,
        "total_thickness_mm": total_thickness_mm,
    }


def detect_supplier_format(full_text):
    txt = full_text.lower()
    if "oeterbeton" in txt or "o e t e r" in txt:
        return "oeterbeton_drawing"
    if "inclusief tralies" in txt and "glad" in txt and "rei" in txt:
        return "predalco_table"
    return "generic_drawing"


def parse_common_supplier_meta(full_text, word_text=""):
    combined_text = f"{full_text}\n{word_text}".strip()

    concrete = None
    concrete_matches = re.findall(r"\bC\d+/\d+\b", combined_text, re.I)
    if concrete_matches:
        concrete = concrete_matches[0].upper()

    steel = None
    m = re.search(r"\b(DE\s*500\s*BS|BE\s*500(?:ES|BS|TS)?|BE500(?:ES|BS|TS)?)\b", combined_text, re.I)
    if m:
        steel = clean_spaces(m.group(1)).upper().replace(" ", "")
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
        r"Bovenwapening\s*:\s*(Zie studieplan|Wordt niet meegeleverd|[^\n\.]{1,80})",
        r"Armatures sup[ée]rieures\s*:\s*(Voir plan de l[' ]ing[ée]nieur|[^\n\.]{1,80})",
    ]:
        m = re.search(pat, combined_text, re.I)
        if m:
            top_mesh_note = clean_spaces(m.group(1))
            if top_mesh_note:
                break

    fire = None
    m = re.search(r"(REI\s*\d+)", combined_text, re.I)
    if m:
        fire = clean_spaces(m.group(1)).upper()

    return {"concrete": concrete, "supplier_steel": steel, "top_mesh_note": top_mesh_note, "fire_default": fire}


def finalize_row(row):
    row["langs_cm2m"] = round(row["langs_mm2m"] / 100.0, 2)
    row["dwars_cm2m"] = round(row["dwars_mm2m"] / 100.0, 2)
    row["plate_size"] = f"{row['length']} x {row['width']}"
    return row


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

    steel_status = "OK" if design["steel"] and supplier["supplier_steel"] and design["steel"] in supplier["supplier_steel"] else "CHECK"
    predal_status = "OK" if predal_thicknesses else "CHECK"
    total_status = "CHECK"
    if design.get("total_thickness_mm") and total_thicknesses:
        total_status = "OK" if all(t == design["total_thickness_mm"] for t in total_thicknesses) else "CHECK"
    mesh_status = "OK" if design.get("top_mesh") and supplier.get("top_mesh_note") and design["top_mesh"] in supplier["top_mesh_note"].upper() else "CHECK"
    fire_status = "CHECK"

    global_rows = [
        ["Detected supplier parser", "Auto detection", supplier.get("supplier_format", "Not found"), "OK" if rows else "CHECK"],
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
