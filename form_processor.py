import os
import re
import json
import csv
import logging
from datetime import datetime
from pathlib import Path
import pytesseract
from pdf2image import convert_from_path
from PIL import Image
import pandas as pd
from dateutil import parser as date_parser

# ==============================
# CONFIGURATION
# ==============================

BASE_FOLDER = Path.home() / "Documents"
WATCH_FOLDER = BASE_FOLDER / "incoming_forms"
OUTPUT_FOLDER = BASE_FOLDER / "processed_output"
LOG_FOLDER = BASE_FOLDER / "logs"
EXCEPTIONS_FOLDER = BASE_FOLDER / "exceptions"
EDI_OUTPUT_FOLDER = BASE_FOLDER / "edi_output"

REQUIRED_FIELDS = ["patient_name", "date_of_birth", "policy_number", "provider_name"]

# Dummy EDI sender/receiver info
SENDER_ID = "SENDERID123"
RECEIVER_ID = "RECEIVERID456"
SUBMITTER_NAME = "Demo Health Org"

# ==============================
# SETUP FOLDERS
# ==============================

for folder in [WATCH_FOLDER, OUTPUT_FOLDER, LOG_FOLDER, EXCEPTIONS_FOLDER, EDI_OUTPUT_FOLDER]:
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

def extract_text_from_pdf(pdf_path: str) -> str:
    pages = convert_from_path(pdf_path)
    full_text = ""
    for page in pages:
        full_text += extract_text_from_image(page) + "\n"
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
# EDI GENERATION
# ==============================

def generate_edi_837(fields: dict, base_filename: str):
    """
    Generates a simplified X12 837 professional claim EDI file.
    """
    today = datetime.utcnow().strftime("%Y%m%d")
    now = datetime.utcnow().strftime("%H%M")
    control_number = base_filename[:9].ljust(9, "0")

    edi_content = f"""ISA*00*          *00*          *ZZ*{SENDER_ID:<15}*ZZ*{RECEIVER_ID:<15}*{today}*{now}*^*00501*{control_number}*0*T*:~
GS*HC*{SENDER_ID}*{RECEIVER_ID}*{today}*{now}*1*X*005010X222A1~
ST*837*0001~
BHT*0019*00*0123*{today}*{now}*CH~
NM1*41*2*{SUBMITTER_NAME}*****46*12345~
PER*IC*Support*TE*8005551212~
NM1*40*2*RECEIVER*****46*98765~
HL*1**20*1~
NM1*85*2*{fields.get('provider_name', 'UNKNOWN')}*****XX*1234567893~
HL*2*1*22*0~
NM1*IL*1*{fields.get('patient_name', 'UNKNOWN')}****MI*{fields.get('policy_number', 'UNKNOWN')}~
DMG*D8*{fields.get('date_of_birth', '').replace('-', '')}~
SE*13*0001~
GE*1*1~
IEA*1*{control_number}~
"""

    edi_path = EDI_OUTPUT_FOLDER / f"{base_filename}.edi"
    with open(edi_path, "w") as ef:
        ef.write(edi_content)

    logging.info(f"Generated EDI file for {base_filename}")
    print(f"📤 EDI generated: {edi_path.name}")

# ==============================
# OUTPUT + AUDIT
# ==============================

def save_outputs(fields: dict, base_filename: str, confidence: float):
    timestamp = datetime.utcnow().isoformat()

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

    generate_edi_837(fields, base_filename)

    logging.info(f"Saved outputs + EDI for {base_filename} with confidence {confidence}%")

# ==============================
# EXCEPTION HANDLING
# ==============================

def move_to_exceptions(file_path: Path, errors: list):
    target = EXCEPTIONS_FOLDER / file_path.name
    file_path.rename(target)

    error_log = {
        "file": file_path.name,
        "errors": errors,
        "timestamp": datetime.utcnow().isoformat()
    }

    with open(EXCEPTIONS_FOLDER / f"{file_path.stem}_errors.json", "w") as ef:
        json.dump(error_log, ef, indent=2)

    logging.warning(f"Moved {file_path.name} to exceptions: {errors}")

# ==============================
# MAIN PROCESSOR
# ==============================

def process_file(file_path: Path):
    logging.info(f"Processing {file_path.name}")
    base_filename = file_path.stem

    try:
        if file_path.suffix.lower() == ".pdf":
            text = extract_text_from_pdf(str(file_path))
        else:
            image = Image.open(file_path)
            text = extract_text_from_image(image)

        fields = extract_fields(text)
        errors = validate_fields(fields)
        confidence = calculate_confidence(fields)

        if errors:
            move_to_exceptions(file_path, errors)
            print(f"❌ Sent to exceptions: {file_path.name}")
        else:
            save_outputs(fields, base_filename, confidence)
            print(f"✅ Processed {file_path.name} — Confidence: {confidence}%")

    except Exception as e:
        logging.exception(f"Failed to process {file_path.name}: {e}")
        move_to_exceptions(file_path, [str(e)])
        print(f"🔥 Failed {file_path.name}: {e}")

# ==============================
# RUNNER
# ==============================

def main():
    print("📥 Watching folder:", WATCH_FOLDER)
    for file in WATCH_FOLDER.iterdir():
        if file.suffix.lower() in [".pdf", ".png", ".jpg", ".jpeg", ".tiff"]:
            process_file(file)

if __name__ == "__main__":
    main()
