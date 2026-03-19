"""
dms-extractor-office: Subscribes to MQTT topic alice/dms/office,
converts Office documents (DOCX, DOC, ODT, XLSX, XLS, ODS) to
plaintext using LibreOffice headless, and pushes the result to
Redis list alice:dms:plaintext.

Word-type documents are converted to .txt, spreadsheets to .csv.
"""

import json
import logging
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import time
import threading
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import redis

# ---------------------------------------------------------------------------
# Logging (structured JSON)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("dms-extractor-office")


def log(level: str, message: str, **extra):
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": "dms-extractor-office",
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

MQTT_TOPIC = "alice/dms/office"
REDIS_KEY = "alice:dms:plaintext"
PLAINTEXT_MAX_CHARS = 50000
HEARTBEAT_FILE = "/tmp/heartbeat"
HEARTBEAT_INTERVAL = 30  # seconds
DEDUP_KEY = "alice:dms:office:processing"
DEDUP_TTL = 3600  # 1 hour TTL for dedup entries

# File extensions that should be converted to CSV (spreadsheets)
SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".ods", ".csv"}
# File extensions that should be converted to TXT (documents)
DOCUMENT_EXTENSIONS = {".docx", ".doc", ".odt", ".rtf"}

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
# LibreOffice conversion
# ---------------------------------------------------------------------------
def convert_with_libreoffice(file_path: str, output_format: str) -> str:
    """
    Convert a file using LibreOffice headless.
    Returns the content of the converted file as a string.
    """
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Copy source file to temp dir (LibreOffice needs write access to the dir)
        src_name = os.path.basename(file_path)
        tmp_src = os.path.join(tmp_dir, src_name)
        shutil.copy(file_path, tmp_src)

        # Run LibreOffice conversion
        cmd = [
            "libreoffice",
            "--headless",
            "--convert-to", output_format,
            "--outdir", tmp_dir,
            tmp_src,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,  # 2 minute timeout for large files
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"LibreOffice conversion failed (exit {result.returncode}): "
                f"{result.stderr.strip()}"
            )

        # Find the output file
        stem = Path(src_name).stem
        output_file = os.path.join(tmp_dir, f"{stem}.{output_format}")

        if not os.path.exists(output_file):
            # LibreOffice might use different casing or extension
            candidates = [
                f for f in os.listdir(tmp_dir)
                if f.startswith(stem) and f != src_name
            ]
            if candidates:
                output_file = os.path.join(tmp_dir, candidates[0])
            else:
                raise RuntimeError(
                    f"Converted file not found in {tmp_dir}, "
                    f"files: {os.listdir(tmp_dir)}"
                )

        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            return f.read()


def process_file(file_path: str) -> tuple[str, dict]:
    """Determine file type and convert using LibreOffice."""
    ext = os.path.splitext(file_path)[1].lower()
    metadata = {}

    if ext in SPREADSHEET_EXTENSIONS:
        output_format = "csv"
        metadata["conversion"] = f"{ext} -> csv"
    elif ext in DOCUMENT_EXTENSIONS:
        output_format = "txt"
        metadata["conversion"] = f"{ext} -> txt"
    else:
        # Default to txt conversion
        output_format = "txt"
        metadata["conversion"] = f"{ext} -> txt (fallback)"

    text = convert_with_libreoffice(file_path, output_format)
    metadata["char_count"] = len(text)

    return text, metadata


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

    log("info", "Enqueued office job", file_path=file_path, file_hash=file_hash)
    work_queue.put(payload)


def worker_loop():
    """Process office conversion jobs from the work queue in a dedicated thread."""
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
    file_type = payload.get("file_type", "office")
    file_size = payload.get("file_size", 0)
    suggested_type = payload.get("suggested_type", "")
    priority = payload.get("priority", "normal")
    detected_at = payload.get("detected_at", datetime.now(timezone.utc).isoformat())

    log("info", "Processing office file", file_path=file_path, file_hash=file_hash)

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

        log("info", "Office extraction successful",
            file_path=file_path,
            char_count=metadata.get("char_count", 0),
            conversion=metadata.get("conversion"))

    except subprocess.TimeoutExpired:
        extraction_failed = True
        log("error", "LibreOffice conversion timed out",
            file_path=file_path)
    except Exception as e:
        extraction_failed = True
        log("error", "Office extraction failed",
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
        "extractor": "dms-extractor-office",
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
threading.Thread(target=worker_loop, daemon=True, name="office-worker").start()


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
    client_id="dms-extractor-office",
    clean_session=True,
)
mqtt_client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.on_message = on_message

mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)

log("info", "dms-extractor-office starting",
    mqtt_host=MQTT_HOST, mqtt_topic=MQTT_TOPIC,
    redis_host=REDIS_HOST, redis_key=REDIS_KEY)

mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=300)
mqtt_client.loop_forever()
