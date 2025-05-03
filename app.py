# Major-Project/app.py
import os
import io
import json
import zipfile
import logging
import re
from datetime import datetime
from pathlib import Path
from flask import (Flask, render_template, request, redirect, url_for,
                   send_from_directory, flash, session)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Import local modules
import pdf_utils # Contains hybrid extract_text
import pdf_operations
import gemini_processors

MB = 1024 * 1024
# --- Define File Size Limits ---
LIMIT_CORE_PDF = 50 * MB      # Merge, Split, Rotate, Protect, Unlock
LIMIT_AI = 20 * MB            # Summarize, Translate (based on input PDF size)
LIMIT_PDF_TO_IMAGE = 20 * MB  # Input PDF size for image conversion
LIMIT_IMAGE_TO_PDF = 30 * MB  # Total size of input images
LIMIT_OFFICE_TO_PDF = 15 * MB # Input Office file size (Increased slightly)
LIMIT_COMPRESS_PDF = 60 * MB  # Input PDF size for compression (Allow larger inputs)
LIMIT_PDF_TO_OFFICE = 25 * MB # Input PDF size for PDF->Office (Word/PPT/Excel)

# --- Configuration ---
# (Keep existing Flask app setup, logging, context processor, BASE_DIR, folder configs, Gemini config, folder creation)
# ... existing setup ...
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)


app = Flask(__name__)

app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'default-insecure-secret-key-for-dev')
if app.config['SECRET_KEY'] == 'default-insecure-secret-key-for-dev':
    logger.warning("FLASK_SECRET_KEY is not set or using default. Please set a strong secret key in .env for production.")

@app.context_processor
def inject_now():
    """Injects the current UTC time into the template context."""
    return {'now': datetime.utcnow}

BASE_DIR = Path(__file__).resolve().parent
app.config['UPLOAD_FOLDER'] = BASE_DIR / 'uploads'
app.config['OUTPUT_FOLDER'] = BASE_DIR / 'output'
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB limit

try:
    gemini_processors.configure_gemini()
except (ValueError, ConnectionError) as e:
    logger.critical(f"CRITICAL ERROR: Failed to configure Gemini API - AI features will not work. {e}", exc_info=True)

pdf_operations.ensure_output_dir()
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
# --- Helper Functions ---
# (Keep allowed_file, handle_file_upload, save_temp_file, cleanup_temp_file, process_and_get_download)
# ... existing helpers ...
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
    total_size = 0 # Track total size for multi-uploads

    for file in files:
        if file and allowed_file(file.filename, allowed_extensions):
            s_filename = secure_filename(file.filename)
            try:
                # Read into BytesIO and check size immediately
                file.seek(0, io.SEEK_END)
                file_size = file.tell()
                file.seek(0)

                # We'll check total size later for multi, but good to have individual size info
                logger.info(f"Processing file: {s_filename} ({file_size / (1024*1024):.2f} MB)")

                stream = io.BytesIO(file.read())
                stream.filename = s_filename # Attach filename
                streams.append(stream)
                filenames.append(s_filename)
                total_size += file_size # Add to total

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

    # Return total size along with streams/filenames
    if multi:
        return streams, filenames, total_size, None # filenames corresponds ONLY to streams returned
    else:
        # If multi=False, we expect only one stream/filename if successful
        if streams:
             # single file size is total_size here
             return streams[0], filenames[0], total_size, None
        else:
             # Should not happen if checks above are correct, but safety return
             return None, None, 0, "Failed to process the uploaded file."


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
        # Try to redirect back to the specific tool page if possible
        referrer = request.referrer
        if referrer and ('/pdf-tools' in referrer or '/ai-tools' in referrer):
             return redirect(referrer)
        else:
             return redirect(url_for('index')) # Fallback to index
    elif output_path and Path(output_path).exists(): # Check file exists before proceeding
        flash(success_msg, 'success')
        session['download_file'] = str(output_path.resolve()) # Store absolute path
        session['download_filename'] = Path(output_path).name # Store just the name
        return redirect(url_for('download_page'))
    elif output_path and not Path(output_path).exists():
         logger.error(f"{operation_name} reported success path {output_path} but file does not exist.")
         flash(f'An error occurred after {operation_name}: Output file missing.', 'error')
         referrer = request.referrer
         if referrer and ('/pdf-tools' in referrer or '/ai-tools' in referrer):
              return redirect(referrer)
         else:
              return redirect(url_for('index'))
    else: # No output_path and no error_msg -> Unknown error
        flash(f'An unknown error occurred during {operation_name}.', 'error')
        referrer = request.referrer
        if referrer and ('/pdf-tools' in referrer or '/ai-tools' in referrer):
             return redirect(referrer)
        else:
             return redirect(url_for('index'))

# --- Routes ---

@app.route('/')
def index():
    """Main landing page."""
    return render_template('index.html')

@app.route('/ai-tools')
def ai_tools_page():
    """Page for AI-based PDF tools."""
    return render_template('ai_tools.html')

@app.route('/pdf-tools')
def pdf_tools_page():
    """Page for standard PDF manipulation tools."""
    return render_template('pdf_tools.html')

# --- AI Tool Processing Routes ---
# (Summarize and Translate routes remain largely the same, but use updated handle_file_upload and limits)
# Major-Project/app.py
# ... (imports) ...

@app.route('/summarize', methods=['POST'])
def summarize_route():
    """Handles PDF summarization, displays results, and offers TXT download.""" # Updated docstring
    stream = None
    temp_pdf_path = None
    filename = "N/A"
    txt_output_path = None # Track generated TXT file path ONLY
    # pdf_output_path = None # REMOVE THIS LINE

    try:
        stream, filename, file_size, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('ai_tools_page'))

        if file_size > LIMIT_AI:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_AI / MB:.0f}MB limit for summarization.", "error")
            if stream: stream.close()
            return redirect(url_for('ai_tools_page'))

        temp_pdf_path = save_temp_file(stream, filename)
        if not temp_pdf_path:
             flash("Failed to save uploaded file for processing.", "error")
             return redirect(url_for('ai_tools_page'))

        text = ""
        results = None
        error_message = None

        logger.info(f"Extracting text from '{filename}' for summarization (with OCR fallback).")
        text, extraction_error = pdf_utils.extract_text(str(temp_pdf_path))

        if extraction_error:
            error_message = f"Text extraction failed: {extraction_error}"
        elif not text:
             error_message = "Could not extract any text from the PDF (direct or OCR)."
        else:
            logger.info(f"Calling Gemini for brief summarization. Text length: {len(text)}")
            results = gemini_processors.summarize_text_gemini(text)

            if results and not results.startswith("Error:"):
                # --- Generate ONLY the TXT output file ---
                output_filename_base = Path(filename).stem
                file_generated = False # Renamed for clarity

                # 1. Generate TXT
                try:
                    txt_output_path = pdf_operations.get_output_filename(output_filename_base, "summary", ".txt")
                    with open(txt_output_path, "w", encoding="utf-8") as f:
                        f.write(results)
                    logger.info(f"Summary TXT file saved to: {txt_output_path}")
                    file_generated = True # Mark TXT file generated
                except Exception as txt_err:
                    logger.error(f"Failed to save summary TXT file: {txt_err}", exc_info=True)
                    error_message = "Failed to save summary as .txt file."
                    if txt_output_path and txt_output_path.exists(): cleanup_temp_file(txt_output_path)
                    txt_output_path = None


                # ---- REMOVE PDF GENERATION BLOCK ----
                # 2. Generate PDF (only if TXT succeeded for simplicity, or handle partial success)
                # if txt_output_path: # Proceed only if TXT was saved
                #     pdf_output_path, pdf_error = pdf_operations.text_to_pdf(results, output_filename_base=output_filename_base)
                #     if pdf_error:
                #         logger.error(f"Failed to generate PDF from summary: {pdf_error}")
                #         # REMOVE flash message about PDF failure
                #         # flash(f"Summary generated and saved as TXT, but failed to create PDF: {pdf_error}", "warning")
                #         pdf_output_path = None # Ensure path is None
                #     else:
                #         logger.info(f"Summary PDF file saved to: {pdf_output_path}")
                #         file_generated = True # Mark generation success
                # ---- END REMOVE PDF GENERATION BLOCK ----


                # --- Render Results Page (if TXT was generated) ---
                if file_generated: # Render only if the TXT file was generated
                    return render_template('summary_result.html',
                                           summary_text=results,
                                           original_filename=filename,
                                           # Pass only the txt filename
                                           txt_filename=txt_output_path.name if txt_output_path else None
                                           # REMOVE pdf_filename=pdf_output_path.name if pdf_output_path else None
                                           )
                # else: fall through to error handling if TXT file failed

            elif results: # Error message from Gemini
                 error_message = results
            else:
                 error_message = "Summarization returned an empty result."

        # If we reach here, there was an error during extraction, gemini, or TXT file saving
        flash(error_message or "An unknown error occurred during summarization.", 'error')
        return redirect(url_for('ai_tools_page'))

    except Exception as e:
        logger.error(f"Unexpected error in /summarize route for {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during summarization.", 'error')
        # Cleanup potentially generated TXT file
        if txt_output_path and txt_output_path.exists(): cleanup_temp_file(txt_output_path)
        # REMOVE PDF cleanup: if pdf_output_path and pdf_output_path.exists(): cleanup_temp_file(pdf_output_path)
        return redirect(url_for('ai_tools_page'))
    finally:
        if stream: stream.close()
        cleanup_temp_file(temp_pdf_path)



#Translate route
@app.route('/translate', methods=['POST'])
def translate_route():
    """Handles PDF translation requests using Gemini auto-detection."""
    stream = None
    temp_pdf_path = None
    filename = "N/A"
    try:
        stream, filename, file_size, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('ai_tools_page'))

        if file_size > LIMIT_AI:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_AI / MB:.0f}MB limit for translation.", "error")
            if stream: stream.close()
            return redirect(url_for('ai_tools_page'))

        temp_pdf_path = save_temp_file(stream, filename)
        if not temp_pdf_path:
             flash("Failed to save uploaded file for processing.", "error")
             return redirect(url_for('ai_tools_page'))

        text = ""
        results = None
        error_message = None
        output_file_path = None

        # --- Determine Target Language ---
        target_lang_select = request.form.get('target_lang_select')
        target_lang_custom = request.form.get('target_lang_custom', '').strip()

        target_language_name = None
        if target_lang_custom:
            target_language_name = target_lang_custom
            logger.info(f"Using custom target language: {target_language_name}")
        elif target_lang_select and target_lang_select != 'other':
            # Use the value directly from the select dropdown (which should be the language name)
            target_language_name = target_lang_select
            logger.info(f"Using selected target language: {target_language_name}")
        else:
             # Handle case where 'other' was selected but custom field is empty, or no selection
             error_message = "Please select a target language or specify a custom language."


        if not error_message:
            logger.info(f"Extracting text from '{filename}' for translation to '{target_language_name}' (with OCR fallback).")
            text, extraction_error = pdf_utils.extract_text(str(temp_pdf_path))

            if extraction_error:
                error_message = f"Text extraction failed: {extraction_error}"
            elif not text:
                 error_message = "Could not extract any text from the PDF (direct or OCR)."
            else:
                # Call the UPDATED translate function
                logger.info(f"Calling Gemini for translation to '{target_language_name}'. Text length: {len(text)}")
                results = gemini_processors.translate_text_gemini(text, target_language_name=target_language_name) # <-- Pass name

                if results and not results.startswith("Error:"):
                    output_filename_base = Path(filename).stem
                    # Sanitize language name for filename
                    safe_lang_name = "".join(c if c.isalnum() else '_' for c in target_language_name).lower()
                    output_file_path = pdf_operations.get_output_filename(output_filename_base, f"translation_{safe_lang_name}", ".txt")
                    with open(output_file_path, "w", encoding="utf-8") as f:
                        f.write(results)
                    logger.info(f"Translation saved to: {output_file_path}")
                    success_msg = f"Successfully translated '{filename}' to {target_language_name}!"
                    return process_and_get_download(output_file_path, None, success_msg, "Translation")
                elif results: # Error message from Gemini or extraction
                    error_message = results
                else:
                    error_message = "Translation returned an empty result."

        # If we reach here, there was an error
        flash(error_message or "An unknown error occurred during translation.", 'error')
        return redirect(url_for('ai_tools_page'))

    except Exception as e:
        logger.error(f"Unexpected error in /translate route for {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during translation.", 'error')
        return redirect(url_for('ai_tools_page'))
    finally:
        if stream: stream.close()
        cleanup_temp_file(temp_pdf_path)

# --- Standard PDF Tool Processing Routes ---

@app.route('/merge', methods=['POST'])
def merge_route():
    streams = None
    try:
        # Updated to get total_size from helper
        streams, filenames, total_size, error = handle_file_upload('pdf_files', {'pdf'}, multi=True)
        if error:
            # Error flashed in helper
            return redirect(url_for('pdf_tools_page'))

        if total_size > LIMIT_CORE_PDF:
            flash(f"Total file size ({total_size / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for merging.", "error")
            for s in streams: s.close()
            return redirect(url_for('pdf_tools_page'))

        if len(streams) < 2:
            flash('Please select at least two PDF files to merge.', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filenames[0]).stem
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
                 except Exception: pass

# (Split route - using updated helper and limit)
@app.route('/split', methods=['POST'])
def split_route():
    stream = None
    output_paths = []
    zip_file_path_obj = None
    filename = "N/A"

    try:
        stream, filename, file_size, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))

        if file_size > LIMIT_CORE_PDF:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for splitting.", "error")
            if stream: stream.close()
            return redirect(url_for('pdf_tools_page'))

        ranges_str = request.form.get('ranges')
        if not ranges_str:
            flash('Page ranges are required for splitting.', 'error')
            return redirect(url_for('pdf_tools_page'))

        # ... (rest of split logic: call multi-split, handle single/zip output)
        base_name = Path(filename).stem
        logger.info(f"Processing multi-split request for '{filename}' with ranges '{ranges_str}'.")

        output_paths, error_msg = pdf_operations.split_pdf_to_multiple_files(stream, ranges_str, output_filename_base=base_name)

        if error_msg:
            flash(f"Split failed: {error_msg}", 'error')
            return redirect(url_for('pdf_tools_page'))

        if not output_paths:
            flash('No pages were extracted based on the specified ranges.', 'warning')
            return redirect(url_for('pdf_tools_page'))

        if len(output_paths) == 1:
            logger.info("Single split file created, proceeding with direct download.")
            output_path_obj = output_paths[0]
            success_msg = f'Successfully extracted pages "{ranges_str}" into one file!'
            return process_and_get_download(output_path_obj, None, success_msg, "Extract Pages")

        else:
            logger.info(f"Multiple ({len(output_paths)}) split files created, creating zip archive.")
            zip_basename = f"{base_name}_split_pages"
            zip_file_path_obj = pdf_operations.get_output_filename(zip_basename, "archive", ".zip")

            try:
                with zipfile.ZipFile(zip_file_path_obj, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for pdf_path in output_paths:
                        if pdf_path.exists() and pdf_path.is_file():
                             zipf.write(pdf_path, arcname=pdf_path.name)
                        else:
                             logger.warning(f"Split PDF file {pdf_path} not found for zipping, skipping.")
                logger.info(f"Successfully created zip archive: {zip_file_path_obj}")

                success_msg = f'Successfully split PDF into {len(output_paths)} files (zipped)!'
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
        if stream:
            try: stream.close()
            except Exception: pass
        if zip_file_path_obj and zip_file_path_obj.exists():
             logger.info("Cleaning up individual split PDF files after zipping.")
             for pdf_path in output_paths:
                 cleanup_temp_file(pdf_path)


# (Rotate route - using updated helper and limit)
@app.route('/rotate', methods=['POST'])
def rotate_route():
    stream = None
    filename = "N/A"
    try:
        stream, filename, file_size, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))

        if file_size > LIMIT_CORE_PDF:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for rotation.", "error")
            if stream: stream.close()
            return redirect(url_for('pdf_tools_page'))

        angle = request.form.get('angle', type=int)
        if angle not in [90, 180, 270]:
            flash('Invalid rotation angle selected (must be 90, 180, or 270).', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        output_path, error_msg = pdf_operations.rotate_pdf(stream, angle, output_filename_base=base_name)

        success_msg = f'Successfully rotated PDF by {angle} degrees!'
        return process_and_get_download(output_path, error_msg, success_msg, "Rotate")

    except Exception as e:
        logger.error(f"Unexpected error in /rotate route for file {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during rotation.", 'error')
        return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass

# (Protect route - using updated helper and limit)
@app.route('/protect', methods=['POST'])
def protect_route():
    stream = None
    filename = "N/A"
    try:
        stream, filename, file_size, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))

        if file_size > LIMIT_CORE_PDF:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for protection.", "error")
            if stream: stream.close()
            return redirect(url_for('pdf_tools_page'))

        password = request.form.get('password')
        if not password:
            flash('Password cannot be empty for protection.', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        output_path, error_msg = pdf_operations.add_password(stream, password, output_filename_base=base_name)

        success_msg = 'Successfully protected PDF with password!'
        return process_and_get_download(output_path, error_msg, success_msg, "Protect")

    except Exception as e:
        logger.error(f"Unexpected error in /protect route for file {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during protection.", 'error')
        return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass

# (Unlock route - using updated helper and limit)
@app.route('/unlock', methods=['POST'])
def unlock_route():
    stream = None
    filename = "N/A"
    try:
        stream, filename, file_size, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))

        if file_size > LIMIT_CORE_PDF:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_CORE_PDF / MB:.0f}MB limit for unlocking.", "error")
            if stream: stream.close()
            return redirect(url_for('pdf_tools_page'))

        password = request.form.get('password')
        if not password:
            flash('Password is required to unlock the PDF.', 'error')
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
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

# --- NEW: COMPRESS Route ---
@app.route('/compress', methods=['POST'])
def compress_route():
    stream = None
    temp_pdf_path = None
    filename = "N/A"
    try:
        stream, filename, file_size, error = handle_file_upload('pdf_file', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))

        if file_size > LIMIT_COMPRESS_PDF:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_COMPRESS_PDF / MB:.0f}MB limit for compression.", "error")
            if stream: stream.close()
            return redirect(url_for('pdf_tools_page'))

        # Compression function might need a path, use temp file
        temp_pdf_path = save_temp_file(stream, filename)
        if not temp_pdf_path:
             flash("Failed to save uploaded file for processing.", "error")
             return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
        logger.info(f"Processing compression request for file: {filename}")
        # Pass the temp path to the compression function
        output_path, error_msg = pdf_operations.compress_pdf(str(temp_pdf_path), output_filename_base=base_name)

        success_msg = 'Successfully compressed PDF!'
        return process_and_get_download(output_path, error_msg, success_msg, "Compress PDF")

    except Exception as e:
        logger.error(f"Unexpected error in /compress route for file {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during compression.", 'error')
        return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass
        cleanup_temp_file(temp_pdf_path) # Clean up the temp PDF used for compression

# --- NEW: PDF to Word Route ---
@app.route('/pdf-to-word', methods=['POST'])
def pdf_to_word_route():
    stream = None
    temp_pdf_path = None
    filename = "N/A"
    try:
        stream, filename, file_size, error = handle_file_upload('pdf_file_to_word', {'pdf'})
        if error:
            return redirect(url_for('pdf_tools_page'))

        if file_size > LIMIT_PDF_TO_OFFICE:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_PDF_TO_OFFICE / MB:.0f}MB limit for PDF to Word conversion.", "error")
            if stream: stream.close()
            return redirect(url_for('pdf_tools_page'))

        # Function needs path or stream, let's try stream first, fallback to temp if needed by implementation
        # (Our current pdf_to_word handles streams by saving temp anyway)
        # temp_pdf_path = save_temp_file(stream, filename) # Use if function strictly requires path

        base_name = Path(filename).stem
        logger.info(f"Processing PDF-to-Word request for file: {filename}")
        output_path, error_msg = pdf_operations.pdf_to_word(stream, output_filename_base=base_name) # Pass stream

        success_msg = 'Successfully converted PDF to Word (basic formatting)!'
        # Add a warning about formatting loss
        if not error_msg:
            flash('Note: Complex formatting (tables, columns, precise styling) may be lost during PDF to Word conversion.', 'warning')

        return process_and_get_download(output_path, error_msg, success_msg, "PDF to Word")

    except Exception as e:
        logger.error(f"Unexpected error in /pdf-to-word route for file {filename}: {e}", exc_info=True)
        flash("An unexpected server error occurred during PDF to Word conversion.", 'error')
        return redirect(url_for('pdf_tools_page'))
    finally:
        if stream:
             try: stream.close()
             except Exception: pass
        # cleanup_temp_file(temp_pdf_path) # Cleanup if temp was used

# --- NEW: PDF to PowerPoint Route (Placeholder) ---
@app.route('/pdf-to-ppt', methods=['POST'])
def pdf_to_ppt_route():
    # Just flash the error message from the placeholder function
    _, error_msg = pdf_operations.pdf_to_powerpoint(None) # Call function to get message
    flash(error_msg or "PDF to PowerPoint conversion is not currently supported.", 'error')
    return redirect(url_for('pdf_tools_page'))

# --- NEW: PDF to Excel Route (Placeholder) ---
@app.route('/pdf-to-excel', methods=['POST'])
def pdf_to_excel_route():
    # Just flash the error message from the placeholder function
    _, error_msg = pdf_operations.pdf_to_excel(None) # Call function to get message
    flash(error_msg or "PDF to Excel conversion is not currently supported.", 'error')
    return redirect(url_for('pdf_tools_page'))


# (PDF-to-Image route - using updated helper and limit)
@app.route('/pdf-to-image', methods=['POST'])
def pdf_to_image_route():
    stream = None
    filename = "N/A"
    temp_pdf_path = None
    output_paths = []
    zip_file_path_obj = None

    try:
        upload_result = handle_file_upload('pdf_file_to_image', {'pdf'}) # Check input name

        # Check if an error message was returned (3 items)
        if len(upload_result) == 3:
             _stream, _filename, error = upload_result # Unpack error tuple
             # Error already flashed by handle_file_upload, just redirect
             return redirect(url_for('pdf_tools_page'))
        elif len(upload_result) == 4:
             # Unpack success tuple
             stream, filename, file_size, error = upload_result
             # error should be None here, but good practice to check
             if error: # Should ideally not happen if len is 4, but safety check
                  flash(f"File upload failed: {error}", "error")
                  return redirect(url_for('pdf_tools_page'))
        else:
             # Unexpected return value from handle_file_upload
             flash("Internal error during file upload processing.", "error")
             logger.error(f"handle_file_upload returned unexpected number of values: {len(upload_result)}")
             return redirect(url_for('pdf_tools_page'))
        
        if file_size > LIMIT_PDF_TO_IMAGE:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_PDF_TO_IMAGE / MB:.0f}MB limit for PDF-to-Image conversion.", "error")
            if stream: stream.close()
            return redirect(url_for('pdf_tools_page'))


        fmt = request.form.get('format', 'jpeg')
        dpi = request.form.get('dpi', 200, type=int)
        # ... (rest of pdf-to-image logic: validate fmt/dpi, save temp, call pdf_to_images, handle single/zip output)
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
        else: # No output paths and no error
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
        cleanup_temp_file(temp_pdf_path)
        if zip_file_path_obj and zip_file_path_obj.exists():
            logger.info("Cleaning up individual image files after zipping.")
            for img_path in output_paths:
                 cleanup_temp_file(img_path)


# (Image-to-PDF route - using updated helper and limit)
@app.route('/image-to-pdf', methods=['POST'])
def image_to_pdf_route():
    streams = None
    try:
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
        streams, filenames, total_size, error = handle_file_upload('image_files', allowed_extensions, multi=True)
        if error:
            return redirect(url_for('pdf_tools_page'))

        if total_size > LIMIT_IMAGE_TO_PDF:
            flash(f"Total image size ({total_size / MB:.1f}MB) exceeds the {LIMIT_IMAGE_TO_PDF / MB:.0f}MB limit for Image-to-PDF conversion.", "error")
            for s in streams: s.close()
            return redirect(url_for('pdf_tools_page'))

        base_name = Path(filenames[0]).stem if filenames else "images"
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

# (Office-to-PDF route - using updated helper and limit)
@app.route('/office-to-pdf', methods=['POST'])
def office_to_pdf_route():
    stream = None
    filename = "N/A"
    temp_office_path = None
    try:
        allowed_extensions = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp', 'rtf'}
        stream, filename, file_size, error = handle_file_upload('office_file', allowed_extensions)
        if error:
            return redirect(url_for('pdf_tools_page'))

        if file_size > LIMIT_OFFICE_TO_PDF:
            flash(f"File size ({file_size / MB:.1f}MB) exceeds the {LIMIT_OFFICE_TO_PDF / MB:.0f}MB limit for Office conversion.", "error")
            if stream: stream.close()
            return redirect(url_for('pdf_tools_page'))

        temp_office_path = save_temp_file(stream, filename)
        if not temp_office_path:
             flash("Failed to save uploaded file for processing.", "error")
             return redirect(url_for('pdf_tools_page'))

        base_name = Path(filename).stem
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
        cleanup_temp_file(temp_office_path)

# --- Download Handling ---
# (Download routes download_page and download_file remain the same)
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

    # *** Potential location for Chaining Logic ***
    # Here you could determine which *next* actions are valid based on the file type (PDF, TXT, DOCX, ZIP etc.)
    # Example:
    next_actions = []
    file_extension = file_path.suffix.lower()
    if file_extension == '.pdf':
        next_actions = [
            {'name': 'Summarize', 'url': url_for('ai_tools_page')}, # Link to page, user uploads again (simple)
            {'name': 'Split', 'url': url_for('pdf_tools_page')},
             # Add more...
             # To implement *true* chaining, the URL would need to pass the file ID/path
             # e.g., url_for('split_route', source_file_id=session_key_for_this_file)
        ]
    elif file_extension == '.zip':
         # Maybe an "Extract" action if you implement one
         pass
    elif file_extension == '.txt':
         # Maybe "Translate Text File"?
         pass

    return render_template('download_page.html',
                           filename=download_filename,
                           download_url=url_for('download_file', filename=download_filename),
                           next_actions=next_actions # Pass possible next actions to template
                           )


@app.route('/download/<path:filename>')
def download_file(filename):
    """Serves the processed file for download."""
    output_dir = Path(app.config['OUTPUT_FOLDER']).resolve()
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
        # Important: After download, remove the file path from session to prevent reuse
        # But do this *after* send_from_directory finishes, if possible.
        # A simple way is just to pop it before returning, but the user might click back.
        # More robust methods involve tracking download completion.
        # Simple approach:
        session.pop('download_file', None)
        session.pop('download_filename', None)

        return send_from_directory(
            directory=output_dir,
            path=safe_filename, # Use the secured filename
            as_attachment=True
            )
    except FileNotFoundError:
        logger.error(f"File not found for download: {file_path}")
        flash(f"Error: File '{safe_filename}' not found.", "error")
        session.pop('download_file', None) # Clean up session anyway
        session.pop('download_filename', None)
        return redirect(url_for('index')), 404
    except Exception as e:
        logger.error(f"Error sending file '{safe_filename}': {e}", exc_info=True)
        flash(f"An error occurred while trying to send the file.", "error")
        return redirect(url_for('index')), 500


# --- Run the App ---
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    
    debug_mode = os.environ.get('FLASK_ENV') != 'production'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)