FROM python:3.12-slim

# Install LibreOffice headless for document conversion
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-headless \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-common \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["python", "-u", "main.py"]
