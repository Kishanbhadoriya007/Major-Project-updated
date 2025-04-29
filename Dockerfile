# Major-Project/Dockerfile

# Use a recent stable Python version
FROM python:3.11-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FLASK_APP=app.py
# Set noninteractive frontend for apt commands
ENV DEBIAN_FRONTEND=noninteractive

# Install system dependencies:
# - poppler-utils for pdf2image
# - libreoffice-writer for Office conversion (pulls in core components)
# - procps (useful for debugging running processes)
# - curl, gnupg (often needed for adding external repositories or keys if required later)
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice-writer \
    procps \
    curl \
    gnupg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Create directories expected by the app (ensure correct permissions if needed)
# Note: Gunicorn will run as root by default unless specified otherwise.
RUN mkdir -p output uploads && chown -R www-data:www-data output uploads # Example: change ownership if running as www-data

# Set environment variables for Flask/Gunicorn
# PORT is standard for many hosting platforms (Cloud Run, Render)
ENV PORT=5001
# Let Flask know it's behind a proxy and should trust X-Forwarded-* headers
ENV FLASK_ENV=production

# Expose the port the app runs on
EXPOSE 5001

# Set default command to run Gunicorn
# Use environment variables for flexibility
# workers = 2 * num_cores + 1 (adjust based on target machine/instance)
# Use 'app:app' - filename 'app.py', Flask instance named 'app'
# Consider using --preload for larger apps if memory allows
# Set timeout based on expected request duration (Gemini calls can be slow)
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "3", "--timeout", "120", "app:app"]