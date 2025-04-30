# Major-Project/app.py
import os
import io
import json
import zipfile # Ensure zipfile is imported
import logging
import re # Ensure re is imported (used in pdf_operations potentially)
from datetime import datetime
from pathlib import Path
from flask import (Flask, render_template, request, redirect, url_for,
                   send_from_directory, flash, session)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Import local modules
import pdf_utils # Will now contain the hybrid extract_text
import pdf_operations
import gemini_processors

MB = 1024 * 1024
LIMIT_CORE_PDF = 50 * MB      # For merge, split, rotate, protect, unlock
LIMIT_AI = 20 * MB            # For translate, summarize (based on input PDF size)
LIMIT_PDF_TO_IMAGE = 20 * MB  # Input PDF size
LIMIT_IMAGE_TO_PDF = 30 * MB  # *Total* size of input images
LIMIT_OFFICE_TO_PDF = 10 * MB # Input Office file size

# --- Configuration ---
load_dotenv() # Load .env file for API keys

# Basic Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'default-insecure-secret-key-for-dev')
if app.config['SECRET_KEY'] == 'default-insecure-secret-key-for-dev':
    logger.warning("FLASK_SECRET_KEY is not set or using default. Please set a strong secret key in .env for production.")

@app.context_processor
def inject_now():
    """Injects the current UTC time into the template context."""
    return {'now': datetime.utcnow}

# Define base directory relative to this file
BASE_DIR = Path(__file__).resolve().parent
app.config['UPLOAD_FOLDER'] = BASE_DIR / 'uploads'
app.config['OUTPUT_FOLDER'] = BASE_DIR / 'output'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB limit

# Configure Gemini API (call this once at startup)
try:
    gemini_processors.configure_gemini()
except (ValueError, ConnectionError) as e:
    logger.critical(f"CRITICAL ERROR: Failed to configure Gemini API - AI features will not work. {e}", exc_info=True)

# Ensure Folders Exist
pdf_operations.ensure_output_dir()
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- Helper Functions ---
# (Keep allowed_file, handle_file_upload, save_temp_file,
#  cleanup_temp_file, process_and_get_download as they were in previous answers)
def allowed_file(filename, allowed_extensions):
    """Checks if the filename has an allowed extension."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions

def handle_file_upload(request_files_key, allowed_extensions, multi=False):
    """Handles single or multiple file uploads, returning streams and filenames or errors."""
    if request_files_key not in request.files:
        flash('No file part in request.', 'error')
        return None, None, 'No file part in request.'

    files = request.files.getlist(request_files_key) if multi else [request.files[request_files_key]]

    if not files or (not multi and files[0].filename == ''):
        # Check if *any* file has a name if multi=True
        if multi and all(f.filename == '' for f in files):
             flash('No selected file(s).', 'error')
             return None, None, 'No selected file(s).'
        elif not multi and files[0].filename == '':
             flash('No selected file.', 'error')
             return None, None, 'No selected file.'


    streams = []
    filenames = []
    error_occurred = False
    for file in files:
        if file and allowed_file(file.filename, allowed_extensions):
            s_filename = secure_filename(file.filename)
            try:
                stream = io.BytesIO(file.read())
                stream.filename = s_filename # Attach filename
                streams.append(stream)
                filenames.append(s_filename)
                logger.info(f"Received file: {s_filename} ({len(stream.getvalue())} bytes)")
            except Exception as read_err:
                 logger.error(f"Error reading uploaded file {s_filename}: {read_err}", exc_info=True)
                 flash(f"Error reading file: {s_filename}", "error")
                 error_occurred = True
                 # Don't return yet, process other files if multi
        elif file and file.filename != '': # File was present but wrong type
            err_msg = f'Invalid file type: {file.filename}. Allowed: {", ".join(allowed_extensions)}'
            flash(err_msg, 'error')
            error_occurred = True # Mark error, but continue if multi
        # Ignore empty file inputs

    if error_occurred and not streams: # Only errors occurred or no valid files provided
         return None, None, "No valid files were processed due to errors or invalid types."
    elif not streams: # No files provided or selected
         flash('No valid files were uploaded.', 'error') # Should have been caught earlier but safety check
         return None, None, 'No valid files uploaded.'

    # If errors occurred but some files were valid (in multi mode), proceed with valid ones
    # The calling route might want to flash a warning about skipped files.

    if multi:
        return streams, filenames, None # filenames corresponds ONLY to streams returned
    else:
        # If multi=False, we expect only one stream/filename if successful
        if streams:
             return streams[0], filenames[0], None
        else:
             # Should not happen if checks above are correct, but safety return
             return None, None, "Failed to process the uploaded file."

def save_temp_file(stream, filename):
    """Saves a stream temporarily to the UPLOAD_FOLDER for tools needing a file path."""
    temp_dir = Path(app.config['UPLOAD_FOLDER'])
    # temp_dir.mkdir(parents=True, exist_ok=True) # Already done at startup
    # Generate a more unique temp name
    temp_filename = secure_filename(f"{Path(filename).stem}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}{Path(filename).suffix}")
    temp_filepath = temp_dir / temp_filename
    try:
        stream.seek(0) # Ensure stream is at the beginning
        with open(temp_filepath, 'wb') as f:
            f.write(stream.read())
        stream.seek(0) # Reset stream pointer
        logger.info(f"Saved temporary file for processing: {temp_filepath}")
        return temp_filepath
    except Exception as e:
        logger.error(f"Error saving temporary file {temp_filepath}: {e}", exc_info=True)
        return None

def cleanup_temp_file(filepath):
    """Removes a temporary file if it exists."""
    if filepath and Path(filepath).exists() and Path(filepath).is_file(): # Check it's a file
        try:
            os.remove(filepath)
            logger.info(f"Removed temporary file: {filepath}")
        except OSError as e:
            logger.warning(f"Could not remove temporary file {filepath}: {e}")
    elif filepath:
         logger.debug(f"Cleanup requested but file not found or not a file: {filepath}")


def process_and_get_download(output_path, error_msg, success_msg, operation_name):
    """Handles output path/error, flashes message, sets session for download."""
    if error_msg:
        flash(f"{operation_name} failed: {error_msg}", 'error')
        return redirect(request.referrer or url_for('index'))
    elif output_path and Path(output_path).exists(): # Check file exists before proceeding
        flash(success_msg, 'success')
        session['download_file'] = str(output_path.resolve()) # Store absolute path
        session['download_filename'] = Path(output_path).name # Store just the name
        return redirect(url_for('download_page'))
    elif output_path and not Path(output_path).exists():
         logger.error(f"{operation_name} reported success path {output_path} but file does not exist.")
         flash(f'An error occurred after {operation_name}: Output file missing.', 'error')
         return redirect(request.referrer or url_for('index'))
    else: # No output_path and no error_msg -> Unknown error
        flash(f'An unknown error occurred during {operation_name}.', 'error')
        return redirect(request.referrer or url_for('index'))

# --- Routes ---

@app.route('/')
def index():
    """Main landing page."""
    return render_template('index.html')

@app.route('/ai-tools')
def ai_tools_page():
    """Page for AI-based PDF tools (Summarize, Translate)."""
    return render_template('ai_tools.html')

@app.route('/pdf-tools')
def pdf_tools_page():
    """Page for standard PDF manipulation tools."""
    return render_template('pdf_tools.html')

# --- AI Tool Processing Routes (Using OCR Fallback) ---

@app.route('/summarize', methods=['POST'])
def summarize_route():
    """Handles PDF summarization requests with OCR fallback."""
    stream = None
    temp_pdf_path = None
    filename = "N/A"
    try:
        stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('ai_tools_page'))
        
        #mb limit check downwards
        if stream.getbuffer().nbytes > LIMIT_AI:
            flash(f"File size ({stream.getbuffer().nbytes / MB:.1f}MB) exceeds the {LIMIT_AI / MB:.0f}MB limit for summarization.", "error")
            stream.close()
            return redirect(url_for('ai_tools_page'))
        #mb limit check upwards

        # Use temp file because OCR fallback might need it
        temp_pdf_path = save_temp_file(stream, filename)
        if not temp_pdf_path:
             flash("Failed to save uploaded file for processing.", "error")
             return redirect(url_for('ai_tools_page'))

        text = ""
        results = None
        error_message = None
        output_file_path = None

        min_len = request.form.get('min_summary_length', 50, type=int)
        max_len = request.form.get('max_summary_length', 300, type=int)

        logger.info(f"Extracting text from '{filename}' for summarization (with OCR fallback).")
        # Call the HYBRID extraction function
        text, extraction_error = pdf_utils.extract_text(str(temp_pdf_path)) # Pass file path

        if extraction_error:
            error_message = f"Text extraction failed: {extraction_error}"
        elif not text:
             error_message = "Could not extract any text from the PDF (direct or OCR)."
        else:
            # Proceed with summarization if text was extracted
            logger.info(f"Calling Gemini for summarization (min: {min_len}, max: {max_len}). Text length: {len(text)}")
            results = gemini_processors.summarize_text_gemini(text, max_length=max_len, min_length=min_len)

            if results and not results.startswith("Error:"):
                output_filename_base = Path(filename).stem
                output_file_path = pdf_operations.get_output_filename(output_filename_base, "summary", ".txt")
                with open(output_file_path, "w", encoding="utf-8") as f:
                    f.write(results)
                logger.info(f"Summary saved to: {output_file_path}")
                success_msg = f"Successfully summarized '{filename}'!"
                # Use process_and_get_download which handles the redirect
                return process_and_get_download(output_file_path, None, success_msg, "Summarization")
            elif results: # It's an error message from Gemini
                 error_message = results
            else:
                 error_message = "Gemini summarization returned empty result."

        # If we reach here, there was an error during extraction or summarization
        flash(error_message, 'error')
        return redirect(url_for('ai_tools_page'))

    except Exception as e:
        logger.error(f"Unexpected error in /summarize route for {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during summarization.", 'error')
        return redirect(url_for('ai_tools_page'))
    finally:
        if stream: stream.close()
        cleanup_temp_file(temp_pdf_path) # Clean up temp file used for extraction

@app.route('/translate', methods=['POST'])
def translate_route():
    """Handles PDF translation requests with OCR fallback."""
    stream = None
    temp_pdf_path = None
    filename = "N/A"
    try:
        stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('ai_tools_page'))
        
        #mb limit check downwards
        if stream.getbuffer().nbytes > LIMIT_AI:
            flash(f"File size ({stream.getbuffer().nbytes / MB:.1f}MB) exceeds the {LIMIT_AI / MB:.0f}MB limit for translation.", "error")
            stream.close()
            return redirect(url_for('ai_tools_page'))
        #mb limit check upwards

        temp_pdf_path = save_temp_file(stream, filename)
        if not temp_pdf_path:
             flash("Failed to save uploaded file for processing.", "error")
             return redirect(url_for('ai_tools_page'))

        text = ""
        results = None
        error_message = None
        output_file_path = None

        target_lang = request.form.get('target_lang', 'fr')
        logger.info(f"Extracting text from '{filename}' for translation to '{target_lang}' (with OCR fallback).")
        text, extraction_error = pdf_utils.extract_text(str(temp_pdf_path)) # Use hybrid function

        if extraction_error:
            error_message = f"Text extraction failed: {extraction_error}"
        elif not text:
             error_message = "Could not extract any text from the PDF (direct or OCR)."
        else:
            logger.info(f"Calling Gemini for translation to '{target_lang}'. Text length: {len(text)}")
            results = gemini_processors.translate_text_gemini(text, target_lang=target_lang)

            if results and not results.startswith("Error:"):
                output_filename_base = Path(filename).stem
                output_file_path = pdf_operations.get_output_filename(output_filename_base, f"translation_{target_lang}", ".txt")
                with open(output_file_path, "w", encoding="utf-8") as f:
                    f.write(results)
                logger.info(f"Translation saved to: {output_file_path}")
                success_msg = f"Successfully translated '{filename}' to {target_lang}!"
                return process_and_get_download(output_file_path, None, success_msg, "Translation")
            elif results: # Error message from Gemini
                error_message = results
            else:
                error_message = "Gemini translation returned empty result."

        flash(error_message, 'error')
        return redirect(url_for('ai_tools_page'))

    except Exception as e:
        logger.error(f"Unexpected error in /translate route for {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during translation.", 'error')
        return redirect(url_for('ai_tools_page'))
    finally:
        if stream: stream.close()
        cleanup_temp_file(temp_pdf_path)


# --- Standard PDF Tool Processing Routes ---

# (Merge route remains the same - paste working version here)
@app.route('/merge', methods=['POST'])
def merge_route():
    streams = None
    try:
        streams, filenames, error = handle_file_upload('pdf_files', {'pdf'}, multi=True)
        
        if error:
            return redirect(url_for('pdf_tools_page'))
        #mb limit check downwards

        total_size = sum(s.getbuffer().nbytes for s in streams)
        if total_size > LIMIT_CORE_PDF:
            flash(f"Total file size ({total_size / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for merging.", "error")
            for s in streams: s.close()
            return redirect(url_for('pdf_tools_page'))
        
        #mb limit check upwards        

        if len(streams) < 2:
            flash('Please select at least two PDF files to merge.', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filenames[0]).stem # Use first filename stem
        output_path, error_msg = pdf_operations.merge_pdfs(streams, output_filename_base=base_name)

        success_msg = f'Successfully merged {len(filenames)} files!'
        return process_and_get_download(output_path, error_msg, success_msg, "Merge")
    except Exception as e:
         logger.error(f"Unexpected error in /merge route: {e}", exc_info=True)
         flash("An unexpected server error occurred during merge.", 'error')
         return redirect(url_for('pdf_tools_page'))
    finally:
        if streams:
             for s in streams:
                 try: s.close()
                 except Exception: pass # Ignore errors closing streams

# (UPDATED Split route using multi-file logic and zip)
@app.route('/split', methods=['POST'])
def split_route():
    stream = None
    output_paths = [] # Keep track of files to potentially clean up
    zip_file_path_obj = None # Path object for the zip file
    filename = "N/A"

    try:
        stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page')) # Error flashed in helper
        
        #mb limit check upwards 
        if stream.getbuffer().nbytes > LIMIT_CORE_PDF:
            flash(f"File size ({stream.getbuffer().nbytes / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for splitting.", "error")
            stream.close()
            return redirect(url_for('pdf_tools_page'))
        #mb limit check upwards 

        ranges_str = request.form.get('ranges')
        if not ranges_str:
            flash('Page ranges are required for splitting.', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        logger.info(f"Processing multi-split request for '{filename}' with ranges '{ranges_str}'.")

        # Call the NEW split function
        output_paths, error_msg = pdf_operations.split_pdf_to_multiple_files(stream, ranges_str, output_filename_base=base_name)

        if error_msg:
            # Error occurred during splitting, message logged in pdf_operations
            flash(f"Split failed: {error_msg}", 'error')
            return redirect(url_for('pdf_tools_page'))

        if not output_paths:
            flash('No pages were extracted based on the specified ranges.', 'warning')
            return redirect(url_for('pdf_tools_page'))

        # --- Handle single vs multiple output files ---
        if len(output_paths) == 1:
            # Only one file created, download directly
            logger.info("Single split file created, proceeding with direct download.")
            output_path_obj = output_paths[0]
            success_msg = f'Successfully extracted pages "{ranges_str}" into one file!'
            # process_and_get_download handles session/redirect
            return process_and_get_download(output_path_obj, None, success_msg, "Extract Pages")

        else:
            # Multiple files created, zip them
            logger.info(f"Multiple ({len(output_paths)}) split files created, creating zip archive.")
            zip_basename = f"{base_name}_split_pages" # Changed suffix
            zip_file_path_obj = pdf_operations.get_output_filename(zip_basename, "archive", ".zip")

            try:
                with zipfile.ZipFile(zip_file_path_obj, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for pdf_path in output_paths:
                        # Check if file exists before adding (paranoia)
                        if pdf_path.exists() and pdf_path.is_file():
                             zipf.write(pdf_path, arcname=pdf_path.name)
                        else:
                             logger.warning(f"Split PDF file {pdf_path} not found for zipping, skipping.")
                logger.info(f"Successfully created zip archive: {zip_file_path_obj}")

                success_msg = f'Successfully split PDF into {len(output_paths)} files (zipped)!'
                # Pass the zip file path for download
                return process_and_get_download(zip_file_path_obj, None, success_msg, "Split PDF")

            except Exception as zip_err:
                logger.error(f"Failed to create zip archive {zip_file_path_obj}: {zip_err}", exc_info=True)
                flash(f"Error creating zip file: {zip_err}", "error")
                cleanup_temp_file(zip_file_path_obj) # Attempt to remove partial zip
                return redirect(url_for('pdf_tools_page'))

    except Exception as e:
        logger.error(f"Unexpected error in /split route for file {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during splitting.", 'error')
        return redirect(url_for('pdf_tools_page'))

    finally:
        # Cleanup: Close the input stream
        if stream:
            try: stream.close()
            except Exception: pass
        # Cleanup: Remove individual split PDF files ONLY if zipping was successful and zip exists
        if zip_file_path_obj and zip_file_path_obj.exists():
             logger.info("Cleaning up individual split PDF files after zipping.")
             for pdf_path in output_paths:
                 cleanup_temp_file(pdf_path)
        # DO NOT cleanup if only one file was created - it needs to persist for download

# (Rotate route - calling the correct function name)
@app.route('/rotate', methods=['POST'])
def rotate_route():
    stream = None
    filename = "N/A"
    try:
        stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))
        
        #mb limit check downwards  
        if stream.getbuffer().nbytes > LIMIT_CORE_PDF:
            flash(f"File size ({stream.getbuffer().nbytes / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for rotation.", "error")
            stream.close()
            return redirect(url_for('pdf_tools_page'))
        #mb limit check upwards 

        angle = request.form.get('angle', type=int)
        if angle not in [90, 180, 270]:
            flash('Invalid rotation angle selected (must be 90, 180, or 270).', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        logger.info(f"Processing rotation ({angle} degrees) for file: {filename}")
        # CALL THE CORRECT FUNCTION NAME
        output_path, error_msg = pdf_operations.rotate_pdf(stream, angle, output_filename_base=base_name)

        success_msg = f'Successfully rotated PDF by {angle} degrees!'
        return process_and_get_download(output_path, error_msg, success_msg, "Rotate")

    except Exception as e:
        logger.error(f"Unexpected error in /rotate route for file {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during rotation. Please check logs.", 'error')
        return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass

# (Protect route - calling the correct function name)
@app.route('/protect', methods=['POST'])
def protect_route():
    stream = None
    filename = "N/A"
    try:
        stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))
        
        #mb limit check downwards 
        if stream.getbuffer().nbytes > LIMIT_CORE_PDF:
            flash(f"File size ({stream.getbuffer().nbytes / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for protection.", "error")
            stream.close()
            return redirect(url_for('pdf_tools_page'))
        #mb limit check upwards

        password = request.form.get('password')
        if not password:
            flash('Password cannot be empty for protection.', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        logger.info(f"Processing protection request for file: {filename}")
        # CALL THE CORRECT FUNCTION NAME
        output_path, error_msg = pdf_operations.add_password(stream, password, output_filename_base=base_name)

        success_msg = 'Successfully protected PDF with password!'
        return process_and_get_download(output_path, error_msg, success_msg, "Protect")

    except Exception as e:
        logger.error(f"Unexpected error in /protect route for file {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during protection. Please check logs.", 'error')
        return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass

# (Unlock route remains the same - paste working version here)
@app.route('/unlock', methods=['POST'])
def unlock_route():
    stream = None
    filename = "N/A"
    try:
        stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))
        
        #mb limit check downwards 
        if stream.getbuffer().nbytes > LIMIT_CORE_PDF:
            flash(f"File size ({stream.getbuffer().nbytes / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for unlocking.", "error")
            stream.close()
            return redirect(url_for('pdf_tools_page'))
        #mb limit check upwards

        password = request.form.get('password')
        if not password:
            flash('Password is required to unlock the PDF.', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        logger.info(f"Processing unlock request for file: {filename}")
        output_path, error_msg = pdf_operations.remove_password(stream, password, output_filename_base=base_name)

        success_msg = 'Successfully unlocked PDF!'
        return process_and_get_download(output_path, error_msg, success_msg, "Unlock")
    except Exception as e:
         logger.error(f"Unexpected error in /unlock route for file {filename}: {e}", exc_info=True)
         flash("An unexpected server error occurred during unlock.", 'error')
         return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass

# (PDF-to-Image route remains the same - paste working version here)
@app.route('/pdf-to-image', methods=['POST'])
def pdf_to_image_route():
    stream = None
    filename = "N/A"
    temp_pdf_path = None
    output_paths = []
    zip_file_path_obj = None

    try:
        stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))
        
        #mb limit check downwards 
        if stream.getbuffer().nbytes > LIMIT_PDF_TO_IMAGE:
            flash(f"File size ({stream.getbuffer().nbytes / MB:.1f}MB) exceeds the {LIMIT_PDF_TO_IMAGE / MB:.0f}MB limit for PDF-to-Image conversion.", "error")
            stream.close()
            return redirect(url_for('pdf_tools_page'))
        #mb limit check upwards

        fmt = request.form.get('format', 'jpeg')
        dpi = request.form.get('dpi', 200, type=int)
        if fmt not in ['jpeg', 'png']:
            flash("Invalid image format selected.", 'error')
            return redirect(url_for('pdf_tools_page'))
        if not 50 <= dpi <= 600:
             flash("DPI must be between 50 and 600.", 'error')
             return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        temp_pdf_path = save_temp_file(stream, filename)
        if not temp_pdf_path:
             flash("Failed to save uploaded file for processing.", "error")
             return redirect(url_for('pdf_tools_page'))

        logger.info(f"Processing pdf-to-image request for '{filename}' (fmt: {fmt}, dpi: {dpi}).")
        output_paths, error_msg = pdf_operations.pdf_to_images(str(temp_pdf_path), fmt=fmt, dpi=dpi, output_filename_base=base_name)

        if error_msg:
            flash(f"PDF to Image conversion failed: {error_msg}", 'error')
            return redirect(url_for('pdf_tools_page'))
        elif output_paths:
            if len(output_paths) == 1:
                success_msg = 'Successfully converted PDF to image!'
                return process_and_get_download(output_paths[0], None, success_msg, "PDF to Image")
            else:
                zip_basename = f"{Path(filename).stem}_images_{fmt}"
                zip_file_path_obj = pdf_operations.get_output_filename(zip_basename, "archive", ".zip")
                try:
                    logger.info(f"Zipping {len(output_paths)} images into {zip_file_path_obj}...")
                    with zipfile.ZipFile(zip_file_path_obj, 'w', zipfile.ZIP_DEFLATED) as zipf:
                        for img_path in output_paths:
                            if img_path.exists() and img_path.is_file():
                                zipf.write(img_path, arcname=img_path.name)
                            else:
                                logger.warning(f"Image file {img_path} not found for zipping, skipping.")
                    logger.info(f"Successfully created zip archive: {zip_file_path_obj}")
                    success_msg = f'Successfully converted PDF to {len(output_paths)} images (zipped)!'
                    return process_and_get_download(zip_file_path_obj, None, success_msg, "PDF to Image")
                except Exception as zip_err:
                     logger.error(f"Failed to zip output images: {zip_err}", exc_info=True)
                     flash(f"Failed to zip output images: {zip_err}", "error")
                     cleanup_temp_file(zip_file_path_obj) # Clean partial zip
                     return redirect(url_for('pdf_tools_page'))
        else: # No output paths and no error -> Should not happen but handle anyway
            flash('An unknown error occurred: No images were generated.', 'error')
            return redirect(url_for('pdf_tools_page'))

    except Exception as e:
         logger.error(f"Unexpected error in /pdf-to-image route for {filename}: {e}", exc_info=True)
         flash("An unexpected server error occurred during PDF to Image conversion.", 'error')
         return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass
        cleanup_temp_file(temp_pdf_path) # Clean up the temp PDF used for conversion
        # Clean up individual images ONLY if zipping was successful
        if zip_file_path_obj and zip_file_path_obj.exists():
            logger.info("Cleaning up individual image files after zipping.")
            for img_path in output_paths:
                 cleanup_temp_file(img_path)


# (Image-to-PDF route remains the same - paste working version here)
@app.route('/image-to-pdf', methods=['POST'])
def image_to_pdf_route():
    streams = None
    try:
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
        streams, filenames, error = handle_file_upload('image_files', allowed_extensions, multi=True)
        if error:
            return redirect(url_for('pdf_tools_page'))
        
        #mb limit check downwards
        total_size = sum(s.getbuffer().nbytes for s in streams)
        if total_size > LIMIT_IMAGE_TO_PDF:
            flash(f"Total image size ({total_size / MB:.1f}MB) exceeds the {LIMIT_IMAGE_TO_PDF / MB:.0f}MB limit for Image-to-PDF conversion.", "error")
            for s in streams: s.close()
            return redirect(url_for('pdf_tools_page'))
        #mb limit check upwards

        base_name = Path(filenames[0]).stem if filenames else "images"
        logger.info(f"Processing image-to-pdf request for {len(filenames)} file(s).")
        output_path, error_msg = pdf_operations.images_to_pdf(streams, output_filename_base=base_name)

        success_msg = f'Successfully converted {len(filenames)} image(s) to PDF!'
        return process_and_get_download(output_path, error_msg, success_msg, "Image to PDF")

    except Exception as e:
        logger.error(f"Unexpected error in /image-to-pdf route: {e}", exc_info=True)
        flash("An unexpected server error occurred during Image to PDF conversion.", 'error')
        return redirect(url_for('pdf_tools_page'))
    finally:
         if streams:
              for s in streams:
                  try: s.close()
                  except Exception: pass

# (Office-to-PDF route remains the same - paste working version here)
@app.route('/office-to-pdf', methods=['POST'])
def office_to_pdf_route():
    stream = None
    filename = "N/A"
    temp_office_path = None
    try:
        allowed_extensions = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp', 'rtf'}
        stream, filename, error = handle_file_upload('office_file', allowed_extensions)
        if error:
            return redirect(url_for('pdf_tools_page'))
        
        #mb limit check downwards
        if stream.getbuffer().nbytes > LIMIT_OFFICE_TO_PDF:
            flash(f"File size ({stream.getbuffer().nbytes / MB:.1f}MB) exceeds the {LIMIT_OFFICE_TO_PDF / MB:.0f}MB limit for Office conversion.", "error")
            stream.close()
            return redirect(url_for('pdf_tools_page'))
        #mb limit check upwards


        temp_office_path = save_temp_file(stream, filename)
        if not temp_office_path:
             flash("Failed to save uploaded file for processing.", "error")
             return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        logger.info(f"Processing office-to-pdf request for '{filename}'.")
        output_path, error_msg = pdf_operations.office_to_pdf(str(temp_office_path), output_filename_base=base_name)

        success_msg = 'Successfully converted Office document to PDF!'
        return process_and_get_download(output_path, error_msg, success_msg, "Office to PDF")

    except Exception as e:
         logger.error(f"Unexpected error in /office-to-pdf route for {filename}: {e}", exc_info=True)
         flash("An unexpected server error occurred during Office to PDF conversion.", 'error')
         return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass
        cleanup_temp_file(temp_office_path) # Clean up the saved temp file

# --- Download Handling ---
# (Download routes download_page and download_file remain the same - paste working versions)
@app.route('/download-page')
def download_page():
    """Displays a page with the download link."""
    download_file_path_str = session.get('download_file')
    download_filename = session.get('download_filename')

    if not download_file_path_str or not download_filename:
        flash("No file available for download or session expired.", "warning")
        return redirect(url_for('index'))

    file_path = Path(download_file_path_str)
    if not file_path.is_file():
         flash(f"File '{download_filename}' not found. It might have been cleaned up.", "error")
         session.pop('download_file', None)
         session.pop('download_filename', None)
         return redirect(url_for('index'))

    return render_template('download_page.html',
                           filename=download_filename,
                           download_url=url_for('download_file', filename=download_filename))

@app.route('/download/<path:filename>')
def download_file(filename):
    """Serves the processed file for download."""
    output_dir = Path(app.config['OUTPUT_FOLDER']).resolve()
    # Validate filename received from URL
    safe_filename = secure_filename(filename)
    if not safe_filename or safe_filename != filename :
        logger.warning(f"Download attempt with potentially unsafe filename blocked: '{filename}'")
        flash("Invalid filename.", "error")
        return redirect(url_for('index')), 400

    file_path = output_dir / safe_filename

    logger.info(f"Download request for: {safe_filename}")
    logger.debug(f"Serving file path: {file_path}")

    if not str(file_path.resolve()).startswith(str(output_dir)):
         logger.warning(f"Forbidden download attempt: '{safe_filename}' resolves outside OUTPUT_FOLDER.")
         flash("Forbidden: Access denied.", "error")
         return redirect(url_for('index')), 403

    try:
        return send_from_directory(
            directory=output_dir,
            path=safe_filename, # Use the secured filename
            as_attachment=True
            )
    except FileNotFoundError:
        logger.error(f"File not found for download: {file_path}")
        flash(f"Error: File '{safe_filename}' not found.", "error")
        session.pop('download_file', None)
        session.pop('download_filename', None)
        return redirect(url_for('index')), 404
    except Exception as e:
        logger.error(f"Error sending file '{safe_filename}': {e}", exc_info=True)
        flash(f"An error occurred while trying to send the file.", "error")
        return redirect(url_for('index')), 500


# --- Run the App ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    # Use debug=False if env var FLASK_ENV is 'production'
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)