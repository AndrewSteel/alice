"""
dms-extractor-ocr: Subscribes to MQTT topic alice/dms/ocr,
performs OCR on image/PDF files using Tesseract, and pushes
the result to Redis list alice:dms:plaintext.

Supported languages: German (deu) and English (eng).
Multi-page PDFs are processed page by page and results are concatenated.
"""

import json
import logging
import os
import sys
import time
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import pytesseract
import redis
from pdf2image import convert_from_path
from PIL import Image

# ---------------------------------------------------------------------------
# Logging (structured JSON)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("dms-extractor-ocr")


def log(level: str, message: str, **extra):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": "dms-extractor-ocr",
        "message": message,
        **extra,
    }
    if level == "error":
        print(json.dumps(entry), file=sys.stderr, flush=True)
    else:
        print(json.dumps(entry), flush=True)


# ---------------------------------------------------------------------------
# Configuration (from environment variables, never hardcoded)
# ---------------------------------------------------------------------------
MQTT_HOST = os.environ.get("MQTT_HOST", "mqtt")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))

MQTT_TOPIC = "alice/dms/ocr"
REDIS_KEY = "alice:dms:plaintext"
PLAINTEXT_MAX_CHARS = 50000
HEARTBEAT_FILE = "/tmp/heartbeat"
HEARTBEAT_INTERVAL = 30  # seconds
OCR_LANGUAGES = "deu+eng"

# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------
def write_heartbeat():
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception as e:
        log("error", "Failed to write heartbeat", error=str(e))


def heartbeat_loop():
    while True:
        write_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)


threading.Thread(target=heartbeat_loop, daemon=True).start()
write_heartbeat()

# ---------------------------------------------------------------------------
# Redis client
# ---------------------------------------------------------------------------
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=os.environ.get("REDIS_PASSWORD") or None,
    decode_responses=True,
    socket_connect_timeout=10,
    retry_on_timeout=True,
)

# ---------------------------------------------------------------------------
# OCR extraction
# ---------------------------------------------------------------------------
def extract_text_from_image(image_path: str) -> tuple[str, dict]:
    """OCR a single image file."""
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img, lang=OCR_LANGUAGES)
    metadata = {
        "char_count": len(text),
        "ocr_language": OCR_LANGUAGES,
    }
    return text, metadata


def extract_text_from_pdf(pdf_path: str) -> tuple[str, dict]:
    """Convert PDF pages to images and OCR each page."""
    images = convert_from_path(pdf_path, dpi=300)
    pages_text = []

    for i, img in enumerate(images):
        page_text = pytesseract.image_to_string(img, lang=OCR_LANGUAGES)
        pages_text.append(page_text)
        log("info", f"OCR page {i + 1}/{len(images)} completed",
            file_path=pdf_path, page=i + 1)

    full_text = "\n\n".join(pages_text)
    metadata = {
        "page_count": len(images),
        "char_count": len(full_text),
        "ocr_language": OCR_LANGUAGES,
    }
    return full_text, metadata


def process_file(file_path: str) -> tuple[str, dict]:
    """Determine file type and run appropriate OCR pipeline."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".gif", ".webp"):
        return extract_text_from_image(file_path)
    else:
        # Try as image anyway
        return extract_text_from_image(file_path)


# ---------------------------------------------------------------------------
# MQTT message handler
# ---------------------------------------------------------------------------
def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log("error", "Invalid JSON in MQTT message, discarding",
            error=str(e), raw=msg.payload.decode("utf-8", errors="replace")[:200])
        return

    file_path = payload.get("file_path", "")
    file_hash = payload.get("file_hash", "")
    file_type = payload.get("file_type", "ocr")
    file_size = payload.get("file_size", 0)
    suggested_type = payload.get("suggested_type", "")
    priority = payload.get("priority", "normal")
    detected_at = payload.get("detected_at", datetime.now(timezone.utc).isoformat())

    if not file_path or not file_path.startswith("/mnt/nas/"):
        log("error", "Rejected message with invalid file_path (must start with /mnt/nas/)",
            file_path=file_path)
        return

    log("info", "Processing OCR file", file_path=file_path, file_hash=file_hash)

    plaintext = ""
    extraction_failed = False
    metadata = {}

    try:
        plaintext, metadata = process_file(file_path)

        # Truncate if too long
        if len(plaintext) > PLAINTEXT_MAX_CHARS:
            metadata["truncated"] = True
            original_length = len(plaintext)
            plaintext = plaintext[:PLAINTEXT_MAX_CHARS]
            log("warn", "Plaintext truncated",
                file_path=file_path,
                original_length=original_length,
                truncated_to=PLAINTEXT_MAX_CHARS)

        log("info", "OCR extraction successful",
            file_path=file_path,
            char_count=metadata.get("char_count", 0),
            page_count=metadata.get("page_count"))

    except Exception as e:
        extraction_failed = True
        log("error", "OCR extraction failed",
            file_path=file_path, error=str(e))

    # Build output message
    output = {
        "file_path": file_path,
        "file_hash": file_hash,
        "file_type": file_type,
        "file_size": file_size,
        "suggested_type": suggested_type,
        "priority": priority,
        "detected_at": detected_at,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "extractor": "dms-extractor-ocr",
        "plaintext": plaintext,
        "extraction_failed": extraction_failed,
        "metadata": metadata,
    }

    # Push to Redis
    try:
        redis_client.rpush(REDIS_KEY, json.dumps(output, ensure_ascii=False))
        log("info", "Result pushed to Redis",
            file_path=file_path, redis_key=REDIS_KEY)
    except Exception as e:
        log("error", "Failed to push to Redis, result lost",
            file_path=file_path, error=str(e))

    write_heartbeat()


# ---------------------------------------------------------------------------
# MQTT setup
# ---------------------------------------------------------------------------
def on_connect(client, userdata, flags, reason_code, properties):
    log("info", "Connected to MQTT broker", reason_code=str(reason_code))
    client.subscribe(MQTT_TOPIC, qos=1)
    log("info", "Subscribed to MQTT topic", topic=MQTT_TOPIC)


def on_disconnect(client, userdata, flags, reason_code, properties):
    log("warn", "Disconnected from MQTT broker", reason_code=str(reason_code))


mqtt_client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2,
    client_id="dms-extractor-ocr",
    clean_session=False,
)
mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message

mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

log("info", "dms-extractor-ocr starting",
    mqtt_host=MQTT_HOST, mqtt_topic=MQTT_TOPIC,
    redis_host=REDIS_HOST, redis_key=REDIS_KEY)

mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
mqtt_client.loop_forever()
