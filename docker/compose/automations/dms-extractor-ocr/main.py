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
import queue
import re
import sys
import time
import threading
import unicodedata
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
DEDUP_KEY = "alice:dms:ocr:processing"
DEDUP_TTL = 3600  # 1 hour TTL for dedup entries

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


def clean_ocr_text(text: str) -> tuple[str, dict]:
    """Remove OCR noise from extracted text while preserving meaningful content.

    Targets noise specific to Tesseract output on PDFs/images:
    - Repeated identical characters (OCR artefacts like 'nnnnn', 'eeeee')
    - Lines dominated by non-Latin scripts (Cyrillic etc. with deu+eng model)
    - Table-of-contents filler sequences ('. . . .', '-----')
    - Non-printable control characters
    - Excessive blank lines

    Does NOT modify: numbers, currency symbols, punctuation, umlauts/special
    Latin characters, structural whitespace (newlines, tabs).
    """
    original_len = len(text)
    lines_in = text.count("\n")

    # 1. Remove non-printable control characters (keep \n, \t, \r)
    text = re.sub(r"[^\S\n\t\r ]+", " ", text)           # collapse weird whitespace
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)  # control chars

    # 2. Remove runs of 5+ identical characters (OCR artefacts like 'nnnnnnn')
    #    Exception: keep runs of digits (e.g. account numbers) and meaningful
    #    punctuation like '...' (up to 4 is fine; 5+ is filler).
    text = re.sub(r"(.)\1{4,}", lambda m: m.group(1) * 4 if m.group(1) in ".-_=" else "", text)

    # 3. Remove ToC filler: lines that are mostly dots/dashes/underscores
    #    e.g. "Chapter 1 ................ 5" -> keep the text, drop the filler run
    text = re.sub(r"[.\-_]{5,}", "", text)

    # 4. Drop lines where >70% of non-space characters are non-Latin/non-digit.
    #    This targets Cyrillic/Greek/Arabic blocks that Tesseract misread.
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            cleaned_lines.append(line)
            continue
        non_space = [c for c in stripped if not c.isspace()]
        if not non_space:
            cleaned_lines.append(line)
            continue
        # Count characters that are Latin letters, digits, or common punctuation
        def is_useful(c):
            if c.isdigit() or c in '.,;:!?()[]{}"\'/\\@#$%&*+-=<>^~`|€$£¥°':
                return True
            cat = unicodedata.category(c)
            # Latin letters: Lu/Ll/Lt/Lm + Latin script
            if cat.startswith("L"):
                name = unicodedata.name(c, "")
                return "LATIN" in name or "COMBINING" in name
            return False
        useful = sum(1 for c in non_space if is_useful(c))
        ratio = useful / len(non_space)
        if ratio >= 0.30 or len(stripped) <= 3:  # keep short lines (dates, codes)
            cleaned_lines.append(line)
    text = "\n".join(cleaned_lines)

    # 5. Collapse 3+ consecutive blank lines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 6. Strip trailing whitespace per line
    text = "\n".join(line.rstrip() for line in text.splitlines())

    text = text.strip()
    cleaned_len = len(text)
    lines_out = text.count("\n")

    stats = {
        "chars_before_clean": original_len,
        "chars_after_clean": cleaned_len,
        "chars_removed": original_len - cleaned_len,
        "reduction_pct": round((original_len - cleaned_len) / max(original_len, 1) * 100, 1),
        "lines_before_clean": lines_in,
        "lines_after_clean": lines_out,
    }
    return text, stats


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
# Work queue: on_message enqueues, worker thread processes
# ---------------------------------------------------------------------------
work_queue = queue.Queue()


def on_message(client, userdata, msg):
    """Enqueue the message and return immediately so the MQTT network loop
    stays responsive (keepalive pings, PUBACK, etc.)."""
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        log("error", "Invalid JSON in MQTT message, discarding",
            error=str(e), raw=msg.payload.decode("utf-8", errors="replace")[:200])
        return

    file_path = payload.get("file_path", "")
    file_hash = payload.get("file_hash", "")

    if not file_path or not file_path.startswith("/mnt/nas/"):
        log("error", "Rejected message with invalid file_path (must start with /mnt/nas/)",
            file_path=file_path)
        return

    # Deduplication: skip if this file_hash is already being processed or was
    # recently processed.  SETNX returns True only if the key did not exist.
    dedup_field = file_hash or file_path
    if dedup_field:
        try:
            is_new = redis_client.set(
                f"{DEDUP_KEY}:{dedup_field}", "1",
                nx=True, ex=DEDUP_TTL,
            )
            if not is_new:
                log("info", "Skipping duplicate message (already processing or recently done)",
                    file_path=file_path, file_hash=file_hash)
                return
        except Exception as e:
            log("warn", "Dedup check failed, processing anyway", error=str(e))

    log("info", "Enqueued OCR job", file_path=file_path, file_hash=file_hash)
    work_queue.put(payload)


def worker_loop():
    """Process OCR jobs from the work queue in a dedicated thread."""
    while True:
        payload = work_queue.get()
        try:
            _process_payload(payload)
        except Exception as e:
            log("error", "Unhandled error in worker", error=str(e))
        finally:
            work_queue.task_done()


def _process_payload(payload: dict):
    file_path = payload.get("file_path", "")
    file_hash = payload.get("file_hash", "")
    file_type = payload.get("file_type", "ocr")
    file_size = payload.get("file_size", 0)
    suggested_type = payload.get("suggested_type", "")
    priority = payload.get("priority", "normal")
    detected_at = payload.get("detected_at", datetime.now(timezone.utc).isoformat())

    log("info", "Processing OCR file", file_path=file_path, file_hash=file_hash)

    plaintext = ""
    extraction_failed = False
    metadata = {}

    try:
        plaintext, metadata = process_file(file_path)

        # Clean OCR noise (repeated chars, non-Latin garbage, ToC filler)
        plaintext, clean_stats = clean_ocr_text(plaintext)
        metadata.update(clean_stats)
        log("info", "OCR text cleaned",
            file_path=file_path,
            chars_before=clean_stats["chars_before_clean"],
            chars_after=clean_stats["chars_after_clean"],
            reduction_pct=clean_stats["reduction_pct"])

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


# Start worker thread
threading.Thread(target=worker_loop, daemon=True, name="ocr-worker").start()


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
    clean_session=True,
)
mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message

mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

log("info", "dms-extractor-ocr starting",
    mqtt_host=MQTT_HOST, mqtt_topic=MQTT_TOPIC,
    redis_host=REDIS_HOST, redis_key=REDIS_KEY)

mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=300)
mqtt_client.loop_forever()
