# Major-Project/pdf_utils.py
import fitz  # PyMuPDF
import os
import logging
from pathlib import Path
import io # Needed for BytesIO

# --- OCR Imports ---
try:
    from PIL import Image
    import pytesseract
    from pdf2image import convert_from_path, pdfinfo_from_path
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logging.warning("OCR dependencies (pytesseract, pdf2image, Pillow) not found. OCR functionality will be disabled.")
# --- End OCR Imports ---


logger = logging.getLogger(__name__)

# --- Configuration ---
# POPPLER_PATH can be set via environment variable or detected if needed by pdf2image
POPPLER_PATH = os.environ.get('POPPLER_PATH', None)
# Set TESSERACT_CMD if needed (usually not required if Tesseract is in PATH)
# pytesseract.pytesseract.tesseract_cmd = r'/usr/bin/tesseract'


def extract_text_with_ocr_fallback(pdf_path_or_stream, min_text_length_threshold=100) -> tuple[str | None, str | None]:
    """
    Extracts text content from a PDF file, attempting direct extraction first
    and falling back to OCR if direct extraction yields insufficient text.

    Args:
        pdf_path_or_stream: Path string to the PDF file OR a file-like object (stream).
        min_text_length_threshold: Minimum characters expected from direct extraction
                                    to consider it successful (avoids OCR on likely text PDFs).

    Returns:
        tuple: (extracted_text, error_message). Returns (text, None) on success,
               (None, error_msg) on failure.
    """
    text = ""
    pdf_source_description = ""
    temp_pdf_path_obj = None # To track temporary file if stream is input

    try:
        # --- Stage 1: Attempt Direct Text Extraction (PyMuPDF) ---
        logger.info(f"Attempting direct text extraction...")

        if isinstance(pdf_path_or_stream, (str, Path)):
            pdf_source = str(pdf_path_or_stream)
            pdf_source_description = os.path.basename(pdf_source)
            if not os.path.exists(pdf_source):
                err = f"PDF file not found at: {pdf_source}"
                logger.error(err)
                return None, err
            doc = fitz.open(pdf_source)
        elif isinstance(pdf_path_or_stream, (io.BytesIO, io.BufferedReader)):
             pdf_source_description = getattr(pdf_path_or_stream, 'filename', 'input_stream')
             # Read stream content for fitz
             pdf_path_or_stream.seek(0)
             stream_bytes = pdf_path_or_stream.read()
             pdf_path_or_stream.seek(0) # Reset stream
             if not stream_bytes:
                  return None, "Input stream is empty."
             doc = fitz.open(stream=stream_bytes, filetype="pdf")
        else:
            return None, "Invalid input type. Must be path string or stream."

        logger.info(f"Processing {doc.page_count} pages in '{pdf_source_description}' for direct text extraction...")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text += page.get_text("text") + "\n"
        doc.close()

        text = text.strip()
        logger.info(f"Direct extraction yielded {len(text)} characters.")

        # If direct extraction yielded enough text, return it
        if len(text) >= min_text_length_threshold:
            logger.info("Direct text extraction successful and sufficient.")
            return text, None

        # --- Stage 2: Fallback to OCR (if direct extraction insufficient and OCR available) ---
        logger.info("Direct text extraction yielded insufficient text. Attempting OCR fallback...")

        if not OCR_AVAILABLE:
            warn = "OCR dependencies not available. Cannot perform OCR."
            logger.warning(warn)
            # Return the (possibly empty) text from direct extraction, maybe with a warning?
            # Or return an error stating OCR couldn't run? Let's return what we have.
            if not text:
                 return None, "Could not extract text directly, and OCR is unavailable."
            else:
                 # Return the small amount of text found, maybe UI should warn user?
                 return text, "Warning: Direct text extraction was minimal, OCR unavailable."


        # OCR requires a file path, save stream to temp file if necessary
        if isinstance(pdf_path_or_stream, (io.BytesIO, io.BufferedReader)):
            # Save stream to a temporary file for pdf2image
            temp_dir = Path("uploads") # Use uploads folder temporarily
            temp_dir.mkdir(parents=True, exist_ok=True)
            temp_pdf_path_obj = temp_dir / f"ocr_temp_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.pdf"
            logger.info(f"Saving stream to temporary file for OCR: {temp_pdf_path_obj}")
            try:
                pdf_path_or_stream.seek(0)
                with open(temp_pdf_path_obj, 'wb') as f_temp:
                    f_temp.write(pdf_path_or_stream.read())
                pdf_path_or_stream.seek(0) # Reset original stream
                pdf_path_for_ocr = str(temp_pdf_path_obj)
            except Exception as save_err:
                 err = f"Failed to save stream to temporary file for OCR: {save_err}"
                 logger.error(err, exc_info=True)
                 return None, err
        else:
             pdf_path_for_ocr = pdf_source # Use the original path


        # Perform OCR
        logger.info(f"Starting OCR process for '{pdf_source_description}' using Tesseract...")
        ocr_text_parts = []
        try:
            # Check if PDF is valid before converting (optional but good)
            try:
                 pdfinfo_from_path(pdf_path_for_ocr, poppler_path=POPPLER_PATH)
            except Exception as pdfinfo_err:
                 raise ValueError(f"Input file may not be a valid PDF or Poppler issue: {pdfinfo_err}") from pdfinfo_err

            # Convert PDF to images
            images = convert_from_path(pdf_path_for_ocr, dpi=300, poppler_path=POPPLER_PATH) # Higher DPI for better OCR
            if not images:
                raise RuntimeError("pdf2image failed to convert PDF pages to images.")

            logger.info(f"Converted PDF to {len(images)} images for OCR.")

            # Process each image with Tesseract
            for i, img in enumerate(images):
                logger.debug(f"Performing OCR on page {i+1}...")
                try:
                    # Specify English language ('eng') for Tesseract
                    page_text = pytesseract.image_to_string(img, lang='eng')
                    ocr_text_parts.append(page_text)
                except pytesseract.TesseractNotFoundError:
                     err = "Tesseract executable not found or not in PATH. Install Tesseract and check configuration."
                     logger.error(err)
                     # Cleanup temp file if created
                     if temp_pdf_path_obj and temp_pdf_path_obj.exists():
                         try: os.remove(temp_pdf_path_obj)
                         except OSError: pass
                     return None, err # Critical error, stop processing
                except Exception as ocr_err:
                     logger.warning(f"Error during OCR on page {i+1}: {ocr_err}. Skipping page.")
                     ocr_text_parts.append(f"[OCR Error on page {i+1}]") # Add placeholder

            # Combine text from all pages
            text = "\n\n--- Page Break ---\n\n".join(ocr_text_parts).strip()
            logger.info(f"OCR process completed. Total characters extracted: {len(text)}")

            if not text:
                 # OCR completed but found no text
                 return None, "OCR process ran but extracted no text from the document images."

            return text, None # Success via OCR

        except Exception as ocr_proc_err:
            logger.error(f"Error during OCR processing pipeline: {ocr_proc_err}", exc_info=True)
            return None, f"Error during OCR process: {ocr_proc_err}"
        finally:
            # Clean up temporary PDF file if it was created
            if temp_pdf_path_obj and temp_pdf_path_obj.exists():
                try:
                    os.remove(temp_pdf_path_obj)
                    logger.info(f"Removed temporary OCR file: {temp_pdf_path_obj}")
                except OSError as e_rem:
                    logger.warning(f"Could not remove temporary OCR file {temp_pdf_path_obj}: {e_rem}")

    except Exception as e:
        logger.error(f"General error extracting text from '{pdf_source_description}': {e}", exc_info=True)
        return None, f"Failed to extract text from PDF: {e}"

# Original extract_text function is now replaced by extract_text_with_ocr_fallback
# Keep the name simple for calling from app.py - maybe rename the function above to extract_text
# Let's rename it:
extract_text = extract_text_with_ocr_fallback