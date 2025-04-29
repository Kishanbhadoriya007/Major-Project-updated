# Major-Project/pdf_utils.py
import fitz  # PyMuPDF
import os
import logging

logger = logging.getLogger(__name__)

def extract_text(pdf_path: str) -> str:
    """Extracts all text content from a PDF file."""
    text = ""
    if not os.path.exists(pdf_path):
        logger.error(f"PDF file not found at: {pdf_path}")
        raise FileNotFoundError(f"PDF file not found at: {pdf_path}")
    try:
        doc = fitz.open(pdf_path)
        logger.info(f"Processing {doc.page_count} pages in {os.path.basename(pdf_path)} for text extraction...")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text += page.get_text("text") + "\n" # Added newline for spacing
        doc.close()
        logger.info("Successfully extracted text.")
        return text.strip()
    except Exception as e:
        logger.error(f"Failed to extract text from {pdf_path}: {e}", exc_info=True)
        # Raise exception for Flask app to catch
        raise ValueError(f"Failed to extract text from PDF: {e}") from e

