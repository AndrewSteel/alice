FROM python:3.12-slim

# System packages: poppler for PDF, LibreOffice for Office files, libheif for HEIC support
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libreoffice \
    libreoffice-writer \
    libreoffice-calc \
    fonts-liberation \
    libheif1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Placeholder image — dark theme matching the Alice UI (gray-800 bg, document card)
RUN python3 -c "from PIL import Image, ImageDraw; img = Image.new('RGB', (400, 400), color=(31, 41, 55)); d = ImageDraw.Draw(img); d.rounded_rectangle([115, 100, 285, 300], radius=10, fill=(55, 65, 81)); d.polygon([(235, 118), (268, 151), (268, 118)], fill=(31, 41, 55)); [d.line([(142, y), (258, y)], fill=(107, 114, 128), width=2) for y in [195, 218, 241, 264]]; img.save('/app/placeholder.jpg', 'JPEG', quality=85)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8004"]
