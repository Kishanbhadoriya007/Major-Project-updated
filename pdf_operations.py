# 1. Ensure OUTPUT_DIR points to the correct place relative to the merged project root.
# 2. Ensure POPPLER_PATH configuration is handled (maybe via environment variables).

import os
import warnings
from datetime import datetime
from pathlib import Path
from pypdf import PdfReader, PdfWriter # Removed Transformation as it wasn't used
from pypdf.errors import PdfReadError, FileNotDecryptedError
from PIL import Image # Keep Pillow
from pdf2image import convert_from_path # Keep pdf2image
import subprocess # For optional LibreOffice conversion
import io
import logging # Use logging

logger = logging.getLogger(__name__)

# --- Configuration ---
# Use Path for better cross-platform compatibility, relative to this file's location
# Assume this script is in the project root. If moved, adjust accordingly.
OUTPUT_DIR = Path("output") # App will ensure this exists
# POPPLER_PATH can be set via environment variable or detected
POPPLER_PATH = os.environ.get('POPPLER_PATH', None)

# Suppress specific warnings from pypdf if needed
warnings.filterwarnings("ignore", category=UserWarning, module='pypdf')

# --- Helper Functions ---
def get_output_filename(base_name, suffix, extension):
    """Generates a unique output filename in the OUTPUT_DIR."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # Sanitize base_name for file system safety
    safe_base = "".join(c if c.isalnum() or c in ('_', '-') else '_' for c in str(base_name))
    # Limit length to avoid issues on some filesystems
    max_base_len = 100
    safe_base = safe_base[:max_base_len]
    filename = f"{safe_base}_{suffix}_{timestamp}{extension}"
    return OUTPUT_DIR / filename

def ensure_output_dir():
    """Creates the output directory if it doesn't exist."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger.info(f"Ensured output directory exists: {OUTPUT_DIR.resolve()}")


# --- Core PDF Operations ---

def merge_pdfs(pdf_files, output_filename_base="merged"):
    """Merges multiple PDF file streams into one."""
    ensure_output_dir()
    merger = PdfWriter()
    processed_count = 0
    try:
        for pdf_stream in pdf_files:
            filename_for_log = getattr(pdf_stream, 'filename', 'N/A')
            try:
                reader = PdfReader(pdf_stream)
                if reader.is_encrypted:
                    try:
                        if reader.decrypt('') == 0: # Try empty password
                             logger.warning(f"Skipping encrypted file (password needed): {filename_for_log}")
                             continue # Skip this file
                    except FileNotDecryptedError:
                        logger.warning(f"Skipping encrypted file (password needed): {filename_for_log}")
                        continue # Skip this file
                    except Exception as decrypt_err:
                         logger.warning(f"Skipping file {filename_for_log} due to decryption check error: {decrypt_err}")
                         continue

                merger.append(reader)
                processed_count += 1
                logger.info(f"Appended '{filename_for_log}' to merge.")
            except PdfReadError as read_err:
                 logger.error(f"Error reading PDF stream '{filename_for_log}': {read_err}. Skipping.")
                 continue # Skip invalid PDF
            except Exception as e:
                logger.error(f"Unexpected error processing stream '{filename_for_log}' for merge: {e}. Skipping.", exc_info=True)
                continue # Skip on other errors

        if processed_count < 1: # Or maybe < 2 depending on desired behavior
            return None, "No valid PDF files could be processed for merging."

        output_path = get_output_filename(output_filename_base, "merged", ".pdf")
        with open(output_path, "wb") as f_out:
            merger.write(f_out)
        merger.close()
        logger.info(f"Successfully merged {processed_count} files into {output_path}")
        return output_path, None # Return path and no error
    except Exception as e:
        logger.error(f"Error during final merge write operation: {e}", exc_info=True)
        if merger: merger.close() # Attempt to close merger if open
        return None, f"Error finalizing merged PDF: {e}"

# ... (Keep split_pdf, rotate_pdf, add_password, remove_password as they were in the original pdf_operations.py, just ensure they use logger) ...

# Example adjustment for split_pdf using logger:
def split_pdf(pdf_file, ranges_str, output_filename_base="split"):
    """Splits a PDF based on page ranges (e.g., '1-3, 5, 8-')."""
    ensure_output_dir()
    output_paths = []
    filename_for_log = getattr(pdf_file, 'filename', 'N/A')
    try:
        reader = PdfReader(pdf_file)
        if reader.is_encrypted:
            try:
                if reader.decrypt('') == 0:
                    err_msg = f"Error: Input PDF '{filename_for_log}' is password protected."
                    logger.error(err_msg)
                    return [], err_msg
            except FileNotDecryptedError:
                 err_msg = f"Error: Input PDF '{filename_for_log}' is password protected."
                 logger.error(err_msg)
                 return [], err_msg

        total_pages = len(reader.pages)
        logger.info(f"Parsing ranges '{ranges_str}' for '{filename_for_log}' ({total_pages} pages total).")

        # Parse ranges (this is a simplified parser)
        parts = ranges_str.split(',')
        page_indices_to_extract = set() # Use 0-based indexing

        for part in parts:
            part = part.strip()
            if not part: continue # Skip empty parts

            if '-' in part:
                start_str, end_str = part.split('-', 1)
                try:
                    start = int(start_str) if start_str else 1
                    end = int(end_str) if end_str else total_pages
                    if start < 1 or end > total_pages or start > end:
                        raise ValueError(f"Range values out of bounds (1-{total_pages})")
                    page_indices_to_extract.update(range(start - 1, end))
                except ValueError as ve:
                     err_msg = f"Invalid range format: '{part}'. {ve}"
                     logger.error(err_msg)
                     return [], err_msg # Return error immediately
            else:
                try:
                    page_num = int(part)
                    if 1 <= page_num <= total_pages:
                        page_indices_to_extract.add(page_num - 1)
                    else:
                        raise ValueError(f"Page number out of bounds (1-{total_pages})")
                except ValueError as ve:
                     err_msg = f"Invalid page number: '{part}'. {ve}"
                     logger.error(err_msg)
                     return [], err_msg # Return error immediately

        if not page_indices_to_extract:
            logger.warning("No valid pages selected for splitting.")
            return [], "No valid pages selected for splitting."

        # Sort indices to process in order
        sorted_indices = sorted(list(page_indices_to_extract))
        logger.info(f"Selected page indices (0-based): {sorted_indices}")


        writer = PdfWriter()
        for index in sorted_indices:
            writer.add_page(reader.pages[index])

        # Create a more descriptive filename suffix from ranges
        range_suffix = ranges_str.replace(',', '_').replace('-', 'to').replace(' ', '')
        # Truncate if too long
        if len(range_suffix) > 50: range_suffix = range_suffix[:47] + '...'

        output_path = get_output_filename(output_filename_base, f"split_{range_suffix}", ".pdf")
        with open(output_path, "wb") as f_out:
            writer.write(f_out)
        writer.close()
        output_paths.append(output_path)
        logger.info(f"Successfully created split PDF: {output_path}")

        return output_paths, None
    except FileNotDecryptedError:
        err_msg = f"Error: Input PDF '{filename_for_log}' is password protected."
        logger.error(err_msg)
        return [], err_msg
    except PdfReadError as read_err:
        err_msg = f"Error reading PDF '{filename_for_log}': {read_err}"
        logger.error(err_msg)
        return [], err_msg
    except Exception as e:
        logger.error(f"Error splitting PDF '{filename_for_log}': {e}", exc_info=True)
        if 'writer' in locals() and writer: writer.close() # Attempt cleanup
        return [], f"Error splitting PDF: {e}"


# ... Implement similar logging updates for rotate_pdf, add_password, remove_password ...

def pdf_to_images(pdf_file, fmt='jpeg', dpi=200, output_filename_base="page"):
    """Converts each page of a PDF to an image (JPEG or PNG)."""
    ensure_output_dir()
    output_paths = []
    fmt = fmt.lower()
    if fmt not in ['jpeg', 'png']:
        return [], "Error: Unsupported image format. Use 'jpeg' or 'png'."

    temp_pdf_path = None
    filename_for_log = getattr(pdf_file, 'filename', 'N/A')
    input_path_obj = None

    try:
        # Handle stream input by saving temporarily
        if isinstance(pdf_file, (io.BytesIO, io.BufferedReader)):
            temp_pdf_path_obj = OUTPUT_DIR / f"temp_{datetime.now().strftime('%Y%m%d%H%M%S%f')}.pdf"
            logger.info(f"Input is a stream, saving temporarily to {temp_pdf_path_obj}")
            with open(temp_pdf_path_obj, 'wb') as f:
                # Ensure stream is at the beginning
                pdf_file.seek(0)
                content = pdf_file.read()
                f.write(content)
                pdf_file.seek(0) # Reset stream pointer
            input_path_obj = temp_pdf_path_obj
            temp_pdf_path = str(temp_pdf_path_obj) # Keep string path for pdf2image if needed
        elif isinstance(pdf_file, (str, Path)):
             input_path_obj = Path(pdf_file)
             filename_for_log = input_path_obj.name # Use actual filename
        else:
             raise TypeError("Unsupported input type for pdf_file. Must be path or stream.")

        logger.info(f"Attempting to convert PDF '{filename_for_log}' to {fmt} images (DPI: {dpi}).")
        logger.info(f"Using Poppler path: {POPPLER_PATH or 'System PATH'}")

        # Check for encryption *before* passing to pdf2image
        try:
            reader = PdfReader(str(input_path_obj)) # PdfReader needs path string
            if reader.is_encrypted:
                try:
                    if reader.decrypt('') == 0: # Fails with empty password
                         err_msg = f"Error: Input PDF '{filename_for_log}' is password protected."
                         logger.error(err_msg)
                         return [], err_msg
                except FileNotDecryptedError:
                     err_msg = f"Error: Input PDF '{filename_for_log}' is password protected."
                     logger.error(err_msg)
                     return [], err_msg
        except Exception as pdf_err:
            logger.error(f"Error checking PDF encryption for '{filename_for_log}': {pdf_err}")
            return [], f"Error reading input PDF: {pdf_err}"

        # Use the path string for convert_from_path
        images = convert_from_path(
            str(input_path_obj), # Needs path string
            dpi=dpi,
            fmt=fmt,
            poppler_path=POPPLER_PATH,
            thread_count=2 # Limit threads slightly
        )

        if not images:
            # This often happens if Poppler isn't found or fails silently
            logger.error("pdf2image returned no images. Check Poppler installation and PATH variable.")
            return [], "Error converting PDF to images. Check Poppler installation/PATH."

        logger.info(f"Successfully generated {len(images)} image objects from PDF.")

        for i, image in enumerate(images):
            ext = ".jpg" if fmt == 'jpeg' else ".png"
            # Pass the base name from the original file for consistency
            output_path = get_output_filename(Path(filename_for_log).stem, f"page_{i+1}", ext)
            try:
                 image.save(output_path, fmt.upper())
                 output_paths.append(output_path)
                 logger.debug(f"Saved image: {output_path}")
            except Exception as save_err:
                logger.error(f"Failed to save image {i+1} to {output_path}: {save_err}", exc_info=True)
                # Decide whether to continue or fail all
                return [], f"Error saving generated image: {save_err}" # Fail all for now

        logger.info(f"Successfully saved {len(output_paths)} images.")
        return output_paths, None

    except Exception as e:
        logger.error(f"Error converting PDF '{filename_for_log}' to images: {e}", exc_info=True)
        import traceback
        # Check if it's a pdf2image specific error
        if "pdfinfo" in str(e) or "pdftoppm" in str(e) or "Poppler" in str(e):
             return [], f"Error during conversion, likely Poppler related. Is Poppler installed and in PATH? Details: {e}"
        return [], f"Unexpected error converting PDF to images: {e}"
    finally:
        # Clean up temporary file if created
        if temp_pdf_path_obj and temp_pdf_path_obj.exists():
            try:
                os.remove(temp_pdf_path_obj)
                logger.info(f"Removed temporary file: {temp_pdf_path_obj}")
            except OSError as e_rem:
                logger.warning(f"Could not remove temporary file {temp_pdf_path_obj}: {e_rem}")

# ... Implement similar logging updates for images_to_pdf, office_to_pdf ...
# Ensure office_to_pdf uses logger and handles soffice path robustly.

# Example adjustment for office_to_pdf logging and soffice detection:
def office_to_pdf(office_file_path, output_filename_base="converted"):
    """Converts an Office document (Word, Excel, PPT) to PDF using LibreOffice."""
    ensure_output_dir()
    output_dir_abs = OUTPUT_DIR.resolve() # LibreOffice needs an absolute path
    input_file_path = Path(office_file_path).resolve() # Ensure input is absolute path too
    input_filename = input_file_path.name

    logger.info(f"Attempting to convert Office file '{input_filename}' to PDF.")

    # --- Find soffice ---
    soffice_command = os.environ.get('SOFFICE_PATH') # Prioritize environment variable
    if soffice_command and Path(soffice_command).exists():
         logger.info(f"Using soffice path from SOFFICE_PATH env var: {soffice_command}")
    else:
        possible_paths = [
            "soffice", # If in PATH
            "libreoffice", # Sometimes just 'libreoffice' is in PATH
            "/usr/bin/soffice", # Linux common path
            "/usr/bin/libreoffice", # Another Linux common path
            "/Applications/LibreOffice.app/Contents/MacOS/soffice", # macOS common path
            "C:/Program Files/LibreOffice/program/soffice.exe", # Windows common path
            "C:/Program Files (x86)/LibreOffice/program/soffice.exe" # Windows (x86) common path
        ]
        found = False
        for cmd_path in possible_paths:
            try:
                # Use --version check which usually exits quickly and confirms executable
                logger.debug(f"Checking for soffice at: {cmd_path}")
                result = subprocess.run([cmd_path, '--version'], check=True, capture_output=True, text=True, timeout=10)
                logger.info(f"Found working LibreOffice command: {cmd_path}. Version info: {result.stdout.strip()}")
                soffice_command = cmd_path
                found = True
                break
            except (subprocess.CalledProcessError, FileNotFoundError, PermissionError, subprocess.TimeoutExpired) as check_err:
                logger.debug(f"Checking '{cmd_path}' failed: {check_err}")
                continue # Try next path
        if not found:
             msg = "Error: LibreOffice 'soffice' command not found or not executable. Install LibreOffice or set SOFFICE_PATH environment variable."
             logger.error(msg)
             return None, msg
    # --- End Find soffice ---

    try:
        cmd = [
            soffice_command,
            '--headless',          # Run without UI
            '--convert-to', 'pdf', # Specify output format
            '--outdir', str(output_dir_abs), # Specify output directory
            str(input_file_path)    # The input file path
        ]
        logger.info(f"Running LibreOffice command: {' '.join(cmd)}")
        # Increased timeout as conversions can be slow
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300) # 5 min timeout
        logger.info(f"LibreOffice ({soffice_command}) stdout: {result.stdout}")
        if result.stderr: # Log stderr even on success, might contain warnings
            logger.warning(f"LibreOffice ({soffice_command}) stderr: {result.stderr}")


        # --- Verify output ---
        original_stem = input_file_path.stem
        expected_pdf = output_dir_abs / f"{original_stem}.pdf"

        if expected_pdf.exists():
             logger.info(f"LibreOffice successfully created: {expected_pdf}")
             # Rename it to our standard format
             final_output_path = get_output_filename(output_filename_base or original_stem, "from_office", ".pdf")
             try:
                 expected_pdf.rename(final_output_path)
                 logger.info(f"Renamed output file to: {final_output_path}")
                 return final_output_path, None
             except OSError as rename_err:
                 logger.error(f"Failed to rename '{expected_pdf}' to '{final_output_path}': {rename_err}")
                 # Fallback: return the original name if rename fails but file exists
                 return expected_pdf, None # Return the path with the original name

        else:
            logger.error(f"Error: Expected PDF '{expected_pdf}' was not found after LibreOffice command executed.")
            # Check stderr for specific clues
            err_detail = result.stderr if result.stderr else "No specific error message in stderr."
            if "Error:" in err_detail:
                 return None, f"LibreOffice conversion failed. Check logs. Details: {err_detail[:500]}" # Limit length
            else:
                 return None, "Error: LibreOffice conversion command ran but the expected output PDF was not created."
            # --- End Verify output ---

    except FileNotFoundError:
         # This happens if soffice_command itself wasn't found despite earlier checks (rare)
         msg = f"Error: LibreOffice command '{soffice_command}' not found during execution. Ensure it's correctly installed and PATH is set."
         logger.error(msg)
         return None, msg
    except subprocess.CalledProcessError as e:
        # This means LibreOffice exited with a non-zero status code
        logger.error(f"LibreOffice conversion failed with exit code {e.returncode}.")
        logger.error(f"Command: {' '.join(e.cmd)}")
        logger.error(f"Stderr: {e.stderr}")
        # Provide a user-friendly error, including parts of stderr if available
        err_msg = f"Error during LibreOffice conversion (exit code {e.returncode})."
        if e.stderr:
             err_msg += f" Details: {e.stderr[:500]}" # Show first 500 chars of error
        return None, err_msg
    except subprocess.TimeoutExpired:
        logger.error("Error: LibreOffice conversion timed out.")
        return None, "Error: Office to PDF conversion took too long (> 5 minutes) and timed out."
    except Exception as e:
        logger.error(f"Unexpected error during Office to PDF conversion: {e}", exc_info=True)
        return None, f"Unexpected error during Office to PDF conversion: {e}"