# Major-Project/Dockerfile

FROM python:3.11-slim-bullseye

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV FLASK_APP=app.py

ENV DEBIAN_FRONTEND=noninteractive


RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice-writer \
    procps \
    curl \
    gnupg \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.txt

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p output uploads && chown -R www-data:www-data output uploads # Example: change ownership if running as www-data


ENV PORT=5001
ENV FLASK_ENV=production

EXPOSE 5001

# gemini calls can be slow so timeout should be givrn appropriately
CMD ["gunicorn", "--bind", "0.0.0.0:5001", "--workers", "3", "--timeout", "120", "app:app"]