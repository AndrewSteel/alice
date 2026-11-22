FROM python:3.12-slim

# LibreOffice (text, spreadsheet, presentation) for all MS Office / OpenDocument formats,
# Tesseract with German and English for scanned PDF pages. No Java: not needed for conversion.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# LibreOffice and Tesseract need a writable HOME when running as the NAS account without passwd entry
ENV HOME=/tmp

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8014"]
