# Trinity PDF Suite

A web application built with Python and Flask to provide a suite of tools for processing and manipulating PDF files, including AI-powered features using the Google Gemini API.

## Features

**Standard PDF Tools:**

*   **Merge:** Combine multiple PDF files into one.
*   **Split:** Extract specific page ranges from a PDF into separate files (zipped if multiple outputs).
*   **Compress:** Reduce PDF file size using PyMuPDF optimizations.
*   **Rotate:** Rotate all pages in a PDF by 90, 180, or 270 degrees.
*   **Protect:** Add a password to encrypt a PDF (AES-256).
*   **Unlock:** Remove password protection from a PDF (requires correct password).
*   **PDF to Image:** Convert PDF pages to JPEG or PNG images with adjustable DPI (Requires Poppler).
*   **Image to PDF:** Convert one or more images (JPG, PNG, etc.) into a single PDF.
*   **Office to PDF:** Convert Word, Excel, and PowerPoint documents to PDF (Requires LibreOffice).
*   **PDF to Word:** Basic conversion of PDF text and images to a `.docx` file (Formatting loss is expected; requires `python-docx`).

**AI-Powered Tools (Google Gemini):**

*   **Summarize PDF:** Generate a brief text summary of PDF content (Uses OCR fallback via Tesseract if needed). Output displayed on screen with copy/download options (.txt, .pdf).
*   **Translate PDF:** Translate PDF text content to a chosen language (Source language auto-detected; uses OCR fallback via Tesseract if needed).

**Other:**

*   Responsive user interface.
*   Download processed files directly.
*   File size limits implemented for various operations.

## Technology Stack

*   **Backend:** Python 3.11+, Flask
*   **AI:** Google Gemini API (`google-generativeai`)
*   **PDF Processing:** PyMuPDF (`fitz`), PyPDF (`pypdf`), `pdf2image`
*   **Word Generation:** `python-docx`
*   **Office Conversion:** LibreOffice (via `subprocess`)
*   **OCR:** Tesseract OCR (`pytesseract`)
*   **Image Handling:** Pillow (`PIL`)
*   **Frontend:** HTML, CSS, JavaScript (includes Font Awesome for icons, GSAP for minor animations)
*   **Deployment:** Docker, Gunicorn

## Prerequisites (System Dependencies)

Before running locally (outside Docker), ensure you have installed:

1.  **Python** (3.11 or later recommended) and `pip`.
2.  **Poppler:** Required by `pdf2image` for PDF-to-Image conversion. (e.g., `apt-get install poppler-utils` on Debian/Ubuntu, `brew install poppler` on macOS).
3.  **Tesseract OCR Engine:** Required for OCR fallback in AI tools. (e.g., `apt-get install tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin` on Debian/Ubuntu, `brew install tesseract` on macOS). Install necessary language packs (like `eng`, `hin`).
4.  **LibreOffice:** Required for Office-to-PDF conversion. (e.g., `apt-get install libreoffice-writer` on Debian/Ubuntu).

*(These are handled by the included `Dockerfile` if using containerized deployment.)*

## Setup and Installation (Local)

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd Major-Project-updated # Or your project directory name
    ```
2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Linux/macOS:
    source venv/bin/activate
    # On Windows:
    .\venv\Scripts\activate
    ```
3.  **Install Python requirements:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Configure Environment Variables:**
    Create a `.env` file in the project root directory by copying `.env.example` (if provided) or creating it manually. Add the following:
    ```dotenv
    # Required for AI features
    GOOGLE_API_KEY=YOUR_GOOGLE_API_KEY_HERE

    # Required for Flask session security (change this!)
    FLASK_SECRET_KEY=a_very_strong_random_secret_key

    # Optional: If Poppler/LibreOffice aren't in system PATH
    # POPPLER_PATH=/path/to/poppler/bin
    # SOFFICE_PATH=/path/to/libreoffice/program/soffice
    ```
    *   Replace `YOUR_GOOGLE_API_KEY_HERE` with your actual Gemini API key.
    *   Generate a strong `FLASK_SECRET_KEY`.

## Running the Application

1.  **Development Server:**
    ```bash
    # Ensure virtual environment is active
    # Optional: Set FLASK_ENV for debug mode
    # export FLASK_ENV=development (Linux/macOS)
    # $env:FLASK_ENV = "development" (Windows PowerShell)
    # set FLASK_ENV=development (Windows CMD)

    flask run --host=0.0.0.0 --port=5001
    ```
2.  **Production (using Gunicorn, similar to Docker):**
    ```bash
    # Ensure virtual environment is active
    gunicorn --bind 0.0.0.0:5001 --workers 3 --timeout 120 app:app
    ```

Access the application in your web browser at `http://localhost:5001` (or your server's IP/domain).

## Docker Deployment

A `Dockerfile` is included to build a container image with all necessary system and Python dependencies.

1.  **Build the image:**
    ```bash
    docker build -t trinity-pdf-suite .
    ```
2.  **Run the container:**
    ```bash
    docker run -p 5001:5001 -v $(pwd)/output:/app/output --env-file .env --name pdf-app trinity-pdf-suite
    ```
    *   This maps port 5001, mounts the local `output` directory to the container's output directory, and passes environment variables from your `.env` file.

Access the application via `http://localhost:5001`.
