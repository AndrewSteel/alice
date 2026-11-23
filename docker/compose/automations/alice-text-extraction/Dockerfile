FROM python:3.12-slim

# LibreOffice (text, spreadsheet, presentation) for all MS Office / OpenDocument formats,
# Tesseract with German and English for scanned PDF pages. No Java: not needed for conversion.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# LibreOffice and Tesseract need a writable HOME when running as the NAS account without passwd entry
ENV HOME=/tmp

# tini as PID 1 reaps orphaned children: LibreOffice spawns gpg/gpgsm/gpgconf for zip based
# formats which get reparented to PID 1 and would stay as zombies under uvicorn.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8014"]
