# Predal Reinforcement Verification Tool

## Overview
This tool automates the verification of predal reinforcement by comparing structural design PDFs with supplier drawings.

It extracts key engineering parameters from unstructured PDF drawings and generates a structured verification report.

---

## Problem Statement
Manual verification of predal drawings is time-consuming and prone to inconsistencies.

This tool aims to:
- Reduce manual effort
- Improve consistency in checks
- Structure engineering data from drawings

---

## Key Features
- Extract reinforcement (HW / DW) from design drawings  
- Extract slab thickness and build-up  
- Extract supplier predal drawings (multiple formats)  
- Plate-by-plate comparison (design vs supplier)  
- Global parameter verification (concrete, mesh, thickness)  
- Automatic slab bearing direction detection and comparison  
- Plate-wise bearing direction verification by mapped slab/plate region  
- Generate structured PDF report  
- Optional company logo support  
- Landscape / Portrait report layout  

---

## Workflow
1. Upload design PDF and supplier PDF  
2. System extracts relevant engineering data  
3. Detects global and plate-wise slab bearing directions  
4. Maps supplier plates to structural slab regions  
5. Applies reinforcement and bearing-direction comparison logic  
6. Generates a verification report  

---

## Tech Stack
- Python (Flask)
- PyMuPDF (PDF text extraction)
- OpenCV / NumPy (bearing arrow detection)
- ReportLab (PDF generation)
- Regex & rule-based parsing

---

## Core Logic
The system is structured into four main steps:

1. **Extraction**  
   Read PDF and extract text, blocks, and words  

2. **Parsing**  
   Identify reinforcement, thickness, and parameters using pattern matching  

3. **Comparison**  
   Match supplier data with design requirements  

4. **Reporting**  
   Generate a structured PDF output  

---

## Limitations
- Based on defined extraction logic and pattern recognition from drawings  
- Accuracy depends on PDF quality and format consistency    

---

## Future Improvements
- Better handling of different supplier formats  
- Improved parsing accuracy    
- Semi-automated plan interpretation  

---

## Deployment
This app is configured for deployment on Render.

### Quick Deploy
1. Push this repository to GitHub  
2. Connect repository in Render (Blueprint)  
3. Deploy  

---

## Local Run
```bash
pip install -r requirements.txt
python app.py
