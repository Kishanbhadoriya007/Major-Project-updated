# Major-Project/app.py

from datetime import datetime
import os
import io
import json
import zipfile
import logging

from pathlib import Path
from flask import (Flask, render_template, request, redirect, url_for,
                   send_from_directory, flash, session)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Import local modules
import pdf_utils
import pdf_operations
import gemini_processors

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
    # You might want the app to exit or disable AI routes if Gemini isn't configured
    # For now, it will log the error and likely fail at runtime when routes are hit.

# Ensure Folders Exist (use methods from pdf_operations)
pdf_operations.ensure_output_dir() # Ensures output dir exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True) # Ensure uploads dir exists


# --- Helper Functions ---
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

    if not files or files[0].filename == '':
        flash('No selected file(s).', 'error')
        return None, None, 'No selected file(s).'

    streams = []
    filenames = []
    for file in files:
        if file and allowed_file(file.filename, allowed_extensions):
            # Secure filename and read into memory stream
            s_filename = secure_filename(file.filename)
            stream = io.BytesIO(file.read())
            stream.filename = s_filename # Attach filename for logging/output naming
            streams.append(stream)
            filenames.append(s_filename)
            logger.info(f"Received file: {s_filename} ({len(stream.getvalue())} bytes)")
        elif file.filename == '':
             # This case is handled above, but good to be explicit
             continue
        else:
            err_msg = f'Invalid file type: {file.filename}. Allowed: {", ".join(allowed_extensions)}'
            flash(err_msg, 'error')
            # Clean up already read streams if one file is invalid
            for s in streams: s.close()
            return None, None, err_msg

    if not streams:
         # This happens if only invalid files were uploaded
         flash('No valid files were uploaded.', 'error')
         return None, None, 'No valid files uploaded.'

    if multi:
        return streams, filenames, None
    else:
        return streams[0], filenames[0], None # Return single stream/filename


def save_temp_file(stream, filename):
    """Saves a stream temporarily to the UPLOAD_FOLDER for tools needing a file path."""
    temp_dir = Path(app.config['UPLOAD_FOLDER'])
    temp_dir.mkdir(parents=True, exist_ok=True) # Ensure it exists
    temp_filepath = temp_dir / secure_filename(f"{datetime.now().strftime('%Y%m%d%H%M%S%f')}_{filename}")
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
    if filepath and Path(filepath).exists():
        try:
            os.remove(filepath)
            logger.info(f"Removed temporary file: {filepath}")
        except OSError as e:
            logger.warning(f"Could not remove temporary file {filepath}: {e}")


def process_and_get_download(output_path, error_msg, success_msg, operation_name):
    """Handles output path/error, flashes message, sets session for download."""
    if error_msg:
        flash(f"{operation_name} failed: {error_msg}", 'error')
        return redirect(request.referrer or url_for('index')) # Go back to referring page
    elif output_path:
        flash(success_msg, 'success')
        session['download_file'] = str(output_path.resolve()) # Store absolute path
        session['download_filename'] = output_path.name # Store just the name for display
        return redirect(url_for('download_page'))
    else:
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

# --- AI Tool Processing Routes ---

@app.route('/summarize', methods=['POST'])
def summarize_route():
    """Handles PDF summarization requests."""
    stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
    if error:
        return redirect(url_for('ai_tools_page'))

    temp_pdf_path = save_temp_file(stream, filename)
    if not temp_pdf_path:
         flash("Failed to save uploaded file for processing.", "error")
         stream.close()
         return redirect(url_for('ai_tools_page'))

    text = ""
    results = None
    error_message = None
    output_file_path = None

    try:
        min_len = request.form.get('min_summary_length', 50, type=int)
        max_len = request.form.get('max_summary_length', 300, type=int)

        logger.info(f"Extracting text from '{filename}' for summarization.")
        text = pdf_utils.extract_text(str(temp_pdf_path)) # Needs path string

        if text:
            logger.info(f"Calling Gemini for summarization (min: {min_len}, max: {max_len}).")
            results = gemini_processors.summarize_text_gemini(text, max_length=max_len, min_length=min_len)

            if results and not results.startswith("Error:"):
                 # Save result to file
                output_filename_base = Path(filename).stem
                output_file_path = pdf_operations.get_output_filename(output_filename_base, "summary", ".txt")
                with open(output_file_path, "w", encoding="utf-8") as f:
                    f.write(results)
                logger.info(f"Summary saved to: {output_file_path}")
                success_msg = f"Successfully summarized '{filename}'!"
                return process_and_get_download(output_file_path, None, success_msg, "Summarization")
            elif results.startswith("Error:"):
                 error_message = results # Use the error from Gemini
            else:
                 error_message = "Gemini summarization returned empty result."

        else:
             error_message = "Could not extract text from the PDF."

    except ValueError as ve:
         logger.error(f"Value error during summarization: {ve}", exc_info=True)
         error_message = f"Input error: {ve}"
    except Exception as e:
        logger.error(f"Error during summarization for '{filename}': {e}", exc_info=True)
        error_message = f"An unexpected error occurred: {e}"
    finally:
        stream.close()
        cleanup_temp_file(temp_pdf_path)

    # If we reached here, there was an error
    flash(error_message, 'error')
    return redirect(url_for('ai_tools_page'))


@app.route('/translate', methods=['POST'])
def translate_route():
    """Handles PDF translation requests."""
    stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
    if error:
        return redirect(url_for('ai_tools_page'))

    temp_pdf_path = save_temp_file(stream, filename)
    if not temp_pdf_path:
         flash("Failed to save uploaded file for processing.", "error")
         stream.close()
         return redirect(url_for('ai_tools_page'))

    text = ""
    results = None
    error_message = None
    output_file_path = None

    try:
        target_lang = request.form.get('target_lang', 'fr') # Default fr
        logger.info(f"Extracting text from '{filename}' for translation to '{target_lang}'.")
        text = pdf_utils.extract_text(str(temp_pdf_path))

        if text:
            logger.info(f"Calling Gemini for translation to '{target_lang}'.")
            results = gemini_processors.translate_text_gemini(text, target_lang=target_lang)

            if results and not results.startswith("Error:"):
                 # Save result to file
                output_filename_base = Path(filename).stem
                output_file_path = pdf_operations.get_output_filename(output_filename_base, f"translation_{target_lang}", ".txt")
                with open(output_file_path, "w", encoding="utf-8") as f:
                    f.write(results)
                logger.info(f"Translation saved to: {output_file_path}")
                success_msg = f"Successfully translated '{filename}' to {target_lang}!"
                return process_and_get_download(output_file_path, None, success_msg, "Translation")
            elif results.startswith("Error:"):
                error_message = results # Use the error from Gemini
            else:
                error_message = "Gemini translation returned empty result."
        else:
             error_message = "Could not extract text from the PDF."

    except ValueError as ve:
         logger.error(f"Value error during translation: {ve}", exc_info=True)
         error_message = f"Input error: {ve}"
    except Exception as e:
        logger.error(f"Error during translation for '{filename}': {e}", exc_info=True)
        error_message = f"An unexpected error occurred: {e}"
    finally:
        stream.close()
        cleanup_temp_file(temp_pdf_path)

    # If we reached here, there was an error
    flash(error_message, 'error')
    return redirect(url_for('ai_tools_page'))


# --- Standard PDF Tool Processing Routes ---

@app.route('/merge', methods=['POST'])
def merge_route():
    streams, filenames, error = handle_file_upload('pdf_files', {'pdf'}, multi=True)
    if error:
        return redirect(url_for('pdf_tools_page'))

    if len(streams) < 2:
        flash('Please select at least two PDF files to merge.', 'error')
        for s in streams: s.close()
        return redirect(url_for('pdf_tools_page'))

    base_name = Path(filenames[0]).stem # Use first filename stem
    output_path, error = pdf_operations.merge_pdfs(streams, output_filename_base=base_name)

    # Close streams
    for s in streams: s.close()

    success_msg = f'Successfully merged {len(filenames)} files!'
    return process_and_get_download(output_path, error, success_msg, "Merge")


@app.route('/split', methods=['POST'])
def split_route():
    stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
    if error:
        return redirect(url_for('pdf_tools_page'))

    ranges_str = request.form.get('ranges')
    if not ranges_str:
        flash('Page ranges are required for splitting.', 'error')
        stream.close()
        return redirect(url_for('pdf_tools_page'))

    base_name = Path(filename).stem
    # Split returns a list of paths, but we usually expect one file for this simple split
    output_paths, error = pdf_operations.split_pdf(stream, ranges_str, output_filename_base=base_name)
    stream.close()

    output_path = output_paths[0] if output_paths else None
    success_msg = f'Successfully split PDF based on ranges "{ranges_str}"!'
    # Note: If split logic creates multiple files, zipping might be needed here.
    # Current pdf_operations.split_pdf creates one file based on selected ranges.
    return process_and_get_download(output_path, error, success_msg, "Split")


@app.route('/rotate', methods=['POST'])
def rotate_route():
    stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
    if error:
        return redirect(url_for('pdf_tools_page'))

    angle = request.form.get('angle', type=int)
    if angle not in [90, 180, 270]:
        flash('Invalid rotation angle selected (must be 90, 180, or 270).', 'error')
        stream.close()
        return redirect(url_for('pdf_tools_page'))

    base_name = Path(filename).stem
    output_path, error = pdf_operations.rotate_pdf(stream, angle, output_filename_base=base_name)
    stream.close()

    success_msg = f'Successfully rotated PDF by {angle} degrees!'
    return process_and_get_download(output_path, error, success_msg, "Rotate")


@app.route('/protect', methods=['POST'])
def protect_route():
    stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
    if error:
        return redirect(url_for('pdf_tools_page'))

    password = request.form.get('password')
    if not password:
        flash('Password cannot be empty for protection.', 'error')
        stream.close()
        return redirect(url_for('pdf_tools_page'))

    base_name = Path(filename).stem
    output_path, error = pdf_operations.add_password(stream, password, output_filename_base=base_name)
    stream.close()

    success_msg = 'Successfully protected PDF with password!'
    return process_and_get_download(output_path, error, success_msg, "Protect")


@app.route('/unlock', methods=['POST'])
def unlock_route():
    stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
    if error:
        return redirect(url_for('pdf_tools_page'))

    password = request.form.get('password')
    if not password:
        flash('Password is required to unlock the PDF.', 'error')
        stream.close()
        return redirect(url_for('pdf_tools_page'))

    base_name = Path(filename).stem
    output_path, error = pdf_operations.remove_password(stream, password, output_filename_base=base_name)
    stream.close()

    success_msg = 'Successfully unlocked PDF!'
    return process_and_get_download(output_path, error, success_msg, "Unlock")


@app.route('/pdf-to-image', methods=['POST'])
def pdf_to_image_route():
    stream, filename, error = handle_file_upload('pdf_file', {'pdf'})
    if error:
        return redirect(url_for('pdf_tools_page'))

    fmt = request.form.get('format', 'jpeg')
    dpi = request.form.get('dpi', 200, type=int)
    if fmt not in ['jpeg', 'png']:
        flash("Invalid image format selected.", 'error')
        stream.close()
        return redirect(url_for('pdf_tools_page'))
    if not 50 <= dpi <= 600:
         flash("DPI must be between 50 and 600.", 'error')
         stream.close()
         return redirect(url_for('pdf_tools_page'))

    base_name = Path(filename).stem
    # pdf_to_images needs a file path, not a stream usually, unless adapted.
    # Let's use the temporary file saving approach.
    temp_pdf_path = save_temp_file(stream, filename)
    if not temp_pdf_path:
         flash("Failed to save uploaded file for processing.", "error")
         stream.close()
         return redirect(url_for('pdf_tools_page'))

    output_paths, error = pdf_operations.pdf_to_images(str(temp_pdf_path), fmt=fmt, dpi=dpi, output_filename_base=base_name)
    stream.close()
    cleanup_temp_file(temp_pdf_path)

    if error:
        flash(f"PDF to Image conversion failed: {error}", 'error')
        return redirect(url_for('pdf_tools_page'))
    elif output_paths:
        if len(output_paths) == 1:
            # Single image output
            success_msg = 'Successfully converted PDF to image!'
            return process_and_get_download(output_paths[0], None, success_msg, "PDF to Image")
        else:
            # Multiple images, zip them
            zip_basename = Path(filename).stem
            zip_filename = pdf_operations.get_output_filename(zip_basename, f"images_{fmt}", ".zip")
            try:
                with zipfile.ZipFile(zip_filename, 'w') as zipf:
                    for img_path in output_paths:
                        zipf.write(img_path, arcname=img_path.name) # Add file to zip using its base name
                        cleanup_temp_file(img_path) # Clean up individual images after zipping
                success_msg = f'Successfully converted PDF to {len(output_paths)} images (zipped)!'
                return process_and_get_download(zip_filename, None, success_msg, "PDF to Image")
            except Exception as zip_err:
                 flash(f"Failed to zip output images: {zip_err}", "error")
                 # Clean up any remaining individual files
                 for img_path in output_paths: cleanup_temp_file(img_path)
                 return redirect(url_for('pdf_tools_page'))
    else:
        flash('An unknown error occurred during PDF to image conversion.', 'error')
        return redirect(url_for('pdf_tools_page'))


@app.route('/image-to-pdf', methods=['POST'])
def image_to_pdf_route():
    allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}
    streams, filenames, error = handle_file_upload('image_files', allowed_extensions, multi=True)
    if error:
        # Specific error already flashed by handle_file_upload
        return redirect(url_for('pdf_tools_page'))

    base_name = Path(filenames[0]).stem if filenames else "images"
    output_path, error = pdf_operations.images_to_pdf(streams, output_filename_base=base_name)

    # Close streams
    for s in streams: s.close()

    success_msg = f'Successfully converted {len(filenames)} image(s) to PDF!'
    return process_and_get_download(output_path, error, success_msg, "Image to PDF")


@app.route('/office-to-pdf', methods=['POST'])
def office_to_pdf_route():
    allowed_extensions = {'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp', 'rtf'}
    stream, filename, error = handle_file_upload('office_file', allowed_extensions)
    if error:
        return redirect(url_for('pdf_tools_page'))

    # office_to_pdf needs a file path
    temp_office_path = save_temp_file(stream, filename)
    if not temp_office_path:
         flash("Failed to save uploaded file for processing.", "error")
         stream.close()
         return redirect(url_for('pdf_tools_page'))

    base_name = Path(filename).stem
    output_path, error = pdf_operations.office_to_pdf(str(temp_office_path), output_filename_base=base_name)

    stream.close() # Close the original stream
    cleanup_temp_file(temp_office_path) # Clean up the saved temp file

    success_msg = 'Successfully converted Office document to PDF!'
    # The error message from office_to_pdf can be detailed (e.g., soffice not found)
    return process_and_get_download(output_path, error, success_msg, "Office to PDF")


# --- Download Handling ---

@app.route('/download-page')
def download_page():
    """Displays a page with the download link."""
    download_file_path_str = session.get('download_file')
    download_filename = session.get('download_filename')

    if not download_file_path_str or not download_filename:
        flash("No file available for download or session expired.", "warning")
        return redirect(url_for('index'))

    # Verify file still exists before showing the link
    file_path = Path(download_file_path_str)
    if not file_path.is_file():
         flash(f"File '{download_filename}' not found. It might have been cleaned up.", "error")
         session.pop('download_file', None) # Clear invalid session entry
         session.pop('download_filename', None)
         return redirect(url_for('index'))

    # Render download page template
    return render_template('download_page.html',
                           filename=download_filename,
                           download_url=url_for('download_file', filename=download_filename))


@app.route('/download/<path:filename>')
def download_file(filename):
    """Serves the processed file for download."""
    # Get the directory path from config
    output_dir = Path(app.config['OUTPUT_FOLDER']).resolve()
    # Securely join the path
    file_path = output_dir / secure_filename(filename) # Secure filename again just in case

    logger.info(f"Download request for: {filename}")
    logger.debug(f"Expected file path: {file_path}")


    # Security Check: Ensure the resolved path is within the intended output directory
    if not str(file_path.resolve()).startswith(str(output_dir)):
         logger.warning(f"Forbidden download attempt: '{filename}' resolves outside OUTPUT_FOLDER.")
         flash("Forbidden: Access denied.", "error")
         return redirect(url_for('index')), 403

    # Optional: Check if this filename matches the one in session for added safety
    session_filename = session.get('download_filename')
    if not session_filename or session_filename != filename:
        logger.warning(f"Download attempt for '{filename}' does not match session filename '{session_filename}'. Allowing if file exists.")
        # Don't prevent download if file exists, but log it.

    try:
        logger.info(f"Sending file: {file_path}")
        response = send_from_directory(
            directory=output_dir,
            path=filename, # Use the filename directly (send_from_directory handles joining)
            as_attachment=True
            )
        # Optional: Clear session *after* successful send initiation
        # @response.call_on_close
        # def clear_session_data():
        #      logger.info(f"Clearing download session for {filename}")
        #      session.pop('download_file', None)
        #      session.pop('download_filename', None)
        return response
    except FileNotFoundError:
        logger.error(f"File not found for download: {file_path}")
        flash(f"Error: File '{filename}' not found.", "error")
        session.pop('download_file', None) # Clean up session if file doesn't exist
        session.pop('download_filename', None)
        return redirect(url_for('index')), 404
    except Exception as e:
        logger.error(f"Error sending file '{filename}': {e}", exc_info=True)
        flash(f"An error occurred while trying to send the file.", "error")
        return redirect(url_for('index')), 500


# --- Run the App ---
if __name__ == '__main__':
    # Host 0.0.0.0 makes it accessible on the network
    # Debug should be False in production
    # Use a production server like gunicorn instead of app.run for deployment
    port = int(os.environ.get('PORT', 5001)) # Use port 5001 default
    app.run(host='0.0.0.0', port=port, debug=True) # Set debug=False for production!