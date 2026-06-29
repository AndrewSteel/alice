FROM python:3.12-slim

# libheif for HEIC support; libexiv2 not needed (using Pillow+piexif)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libheif1 \
    libffi-dev \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["python3", "-u", "main.py"]
