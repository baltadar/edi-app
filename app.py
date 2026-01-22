import streamlit as st
from pathlib import Path
from form_processor import process_file  # import your existing processor

st.set_page_config(page_title="Form Processor & EDI Generator", layout="wide")

st.title("📄 Form Processor & EDI Generator")
st.write(
    """
Upload PDF or image forms, and this app will extract required fields,
validate them, generate JSON, CSV, and a simplified EDI 837 file.
"""
)

uploaded_file = st.file_uploader("Choose a PDF or image file", type=["pdf", "png", "jpg", "jpeg", "tiff"])

if uploaded_file is not None:
    # Save uploaded file temporarily
    TEMP_FOLDER = Path("temp_uploads")
    TEMP_FOLDER.mkdir(exist_ok=True)
    temp_file_path = TEMP_FOLDER / uploaded_file.name
    with open(temp_file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    st.info(f"Processing {uploaded_file.name} ...")
    try:
        process_file(temp_file_path)
        st.success("✅ Processed successfully!")

        st.download_button(
            label="Download JSON",
            data=open(f"processed_output/{temp_file_path.stem}.json", "rb").read(),
            file_name=f"{temp_file_path.stem}.json"
        )

        st.download_button(
            label="Download CSV",
            data=open(f"processed_output/{temp_file_path.stem}.csv", "rb").read(),
            file_name=f"{temp_file_path.stem}.csv"
        )

        st.download_button(
            label="Download EDI",
            data=open(f"edi_output/{temp_file_path.stem}.edi", "rb").read(),
            file_name=f"{temp_file_path.stem}.edi"
        )

    except Exception as e:
        st.error(f"🔥 Failed to process file: {e}")
