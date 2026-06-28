FROM python:3.12-slim

# System packages: poppler for PDF, LibreOffice for Office files
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice \
    libreoffice-writer \
    libreoffice-calc \
    fonts-liberation \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Placeholder image baked into the image (generated at build time)
RUN python3 -c "from PIL import Image, ImageDraw; img = Image.new('RGB', (400, 400), color=(240, 240, 240)); d = ImageDraw.Draw(img); d.rectangle([170, 150, 230, 250], fill=(200, 200, 200)); d.rectangle([150, 190, 250, 260], fill=(200, 200, 200)); img.save('/app/placeholder.jpg', 'JPEG', quality=85)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
