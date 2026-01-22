import os
import re
import json
import logging
from datetime import datetime
from pathlib import Path
import shutil

import streamlit as st
import pdfplumber
from PIL import Image
import pytesseract
import pandas as pd
from dateutil import parser as date_parser

# ==============================
# CONFIGURATION
# ==============================

BASE_FOLDER = Path("/home/appuser/Documents")
WATCH_FOLDER = BASE_FOLDER / "incoming_forms"
OUTPUT_FOLDER = BASE_FOLDER / "processed_output"
LOG_FOLDER = BASE_FOLDER / "logs"
EXCEPTIONS_FOLDER = BASE_FOLDER / "exceptions"

REQUIRED_FIELDS = ["patient_name", "date_of_birth", "policy_number", "provider_name"]

# ==============================
# SETUP FOLDERS
# ==============================

for folder in [WATCH_FOLDER, OUTPUT_FOLDER, LOG_FOLDER, EXCEPTIONS_FOLDER]:
    folder.mkdir(parents=True, exist_ok=True)

# ==============================
# SETUP LOGGING
# ==============================

logging.basicConfig(
    filename=LOG_FOLDER / "form_processor.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

# ==============================
# OCR FUNCTIONS
# ==============================

def extract_text_from_image(image: Image.Image) -> str:
    return pytesseract.image_to_string(image)

def extract_text_from_pdf(pdf_path: Path) -> str:
    """Use pdfplumber instead of pdf2image (no Poppler needed)."""
    full_text = ""
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                full_text += page.extract_text() + "\n"
    except Exception as e:
        logging.error(f"Failed to read PDF {pdf_path.name}: {e}")
    return full_text

# ==============================
# FIELD EXTRACTION
# ==============================

def extract_fields(text: str) -> dict:
    fields = {}

    name_match = re.search(r"Patient Name[:\-]?\s*(.+)", text, re.IGNORECASE)
    dob_match = re.search(r"(DOB|Date of Birth)[:\-]?\s*([\w\/\-]+)", text, re.IGNORECASE)
    policy_match = re.search(r"(Policy Number|Member ID)[:\-]?\s*([A-Za-z0-9\-]+)", text, re.IGNORECASE)
    provider_match = re.search(r"(Provider|Physician) Name[:\-]?\s*(.+)", text, re.IGNORECASE)

    if name_match:
        fields["patient_name"] = name_match.group(1).strip()
    if dob_match:
        try:
            fields["date_of_birth"] = date_parser.parse(dob_match.group(2)).date().isoformat()
        except Exception:
            fields["date_of_birth"] = dob_match.group(2).strip()
    if policy_match:
        fields["policy_number"] = policy_match.group(2).strip()
    if provider_match:
        fields["provider_name"] = provider_match.group(2).strip()

    return fields

# ==============================
# CONFIDENCE SCORING
# ==============================

def calculate_confidence(fields: dict) -> float:
    filled = sum(1 for f in REQUIRED_FIELDS if f in fields and fields[f])
    return round((filled / len(REQUIRED_FIELDS)) * 100, 2)

# ==============================
# VALIDATION
# ==============================

def validate_fields(fields: dict) -> list:
    errors = []
    for field in REQUIRED_FIELDS:
        if field not in fields or not fields[field]:
            errors.append(f"Missing required field: {field}")
    return errors

# ==============================
# OUTPUT + AUDIT
# ==============================

def save_outputs(fields: dict, base_filename: str, confidence: float):
    timestamp = datetime.utcnow().isoformat()
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)

    output_data = {
        "extracted_fields": fields,
        "confidence_score": confidence,
        "processed_at": timestamp,
        "status": "success" if confidence == 100 else "partial"
    }

    json_path = OUTPUT_FOLDER / f"{base_filename}.json"
    csv_path = OUTPUT_FOLDER / f"{base_filename}.csv"

    with open(json_path, "w") as jf:
        json.dump(output_data, jf, indent=2)

    df = pd.DataFrame([fields])
    df.to_csv(csv_path, index=False)

    logging.info(f"Saved outputs for {base_filename} with confidence {confidence}%")

# ==============================
# EXCEPTION HANDLING
# ==============================

def move_to_exceptions(file_path: Path, errors: list):
    EXCEPTIONS_FOLDER.mkdir(parents=True, exist_ok=True)
    target = EXCEPTIONS_FOLDER / file_path.name
    shutil.copy2(file_path, target)
    file_path.unlink()

    error_log = {
        "file": file_path.name,
        "errors": errors,
        "timestamp": datetime.utcnow().isoformat()
    }

    with open(EXCEPTIONS_FOLDER / f"{file_path.stem}_errors.json", "w") as ef:
        json.dump(error_log, ef, indent=2)

    logging.warning(f"Moved {file_path.name} to exceptions: {errors}")

# ==============================
# PROCESS FILE
# ==============================

def process_file(file_path: Path):
    logging.info(f"Processing {file_path.name}")
    base_filename = file_path.stem

    try:
        if file_path.suffix.lower() == ".pdf":
            text = extract_text_from_pdf(file_path)
        else:
            image = Image.open(file_path)
            text = extract_text_from_image(image)

        fields = extract_fields(text)
        errors = validate_fields(fields)
        confidence = calculate_confidence(fields)

        if errors:
            move_to_exceptions(file_path, errors)
            st.error(f"❌ Sent to exceptions: {file_path.name}")
        else:
            save_outputs(fields, base_filename, confidence)
            st.success(f"✅ Processed {file_path.name} — Confidence: {confidence}%")

    except Exception as e:
        logging.exception(f"Failed to process {file_path.name}: {e}")
        move_to_exceptions(file_path, [str(e)])
        st.error(f"🔥 Failed {file_path.name}: {e}")

# ==============================
# STREAMLIT UI
# ==============================

st.title("EDI Form Processor")
st.write("Upload PDF or image forms to extract data automatically.")

uploaded_files = st.file_uploader(
    "Choose files",
    type=["pdf", "png", "jpg", "jpeg", "tiff"],
    accept_multiple_files=True
)

if uploaded_files:
    for uploaded_file in uploaded_files:
        temp_path = WATCH_FOLDER / uploaded_file.name
        with open(temp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        process_file(temp_path)

st.write("✅ Done! Check processed_output and exceptions folders.")
