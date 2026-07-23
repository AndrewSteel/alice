"""
dms-extractor-image: MQTT subscriber for alice/dms/image (PROJ-56).

Pipeline per image:
  1. Receive MQTT message from alice/dms/image
  2. Validate file path (/mnt/nas/ prefix required)
  3. Extract EXIF metadata (datetime, GPS, camera)
  4. If GPS present: RPUSH {file_hash, latitude, longitude} to alice:dms:geocode_pending
     (reverse geocoding itself happens decoupled, nightly, in alice-dms-processor via Geoapify)
  5. Generate German AI description via Ollama Vision
  6. RPUSH result JSON to Redis alice:dms:image
  7. On any failure: write extraction_failed=True, still push to Redis
"""

import base64
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from io import BytesIO

import paho.mqtt.client as mqtt
import piexif
import redis
import requests
from PIL import Image, ExifTags

# Register HEIC support if available
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
MQTT_HOST = os.environ.get("MQTT_HOST", "mqtt")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USERNAME = os.environ.get("MQTT_USERNAME", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
MQTT_TOPIC = "alice/dms/image"

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None
REDIS_KEY = "alice:dms:image"
GEOCODE_PENDING_KEY = "alice:dms:geocode_pending"

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "qwen3.5:27b-q4_K_M")

AI_DESCRIPTION_MAX_CHARS = 50000
OLLAMA_MAX_IMAGE_PX = 1024  # resize before sending to Ollama
HEARTBEAT_FILE = "/tmp/heartbeat"
HEARTBEAT_INTERVAL = 30

# ---------------------------------------------------------------------------
# Logging (structured JSON)
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(message)s")
_logger = logging.getLogger("dms-extractor-image")


def log(level: str, message: str, **kwargs) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "service": "dms-extractor-image",
        "message": message,
        **kwargs,
    }
    if level == "error":
        _logger.error(json.dumps(entry, ensure_ascii=False))
    else:
        _logger.info(json.dumps(entry, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------
def write_heartbeat() -> None:
    try:
        with open(HEARTBEAT_FILE, "w") as f:
            f.write(str(int(time.time() * 1000)))
    except Exception as exc:
        log("error", "Failed to write heartbeat", error=str(exc))


def _heartbeat_loop() -> None:
    while True:
        write_heartbeat()
        time.sleep(HEARTBEAT_INTERVAL)


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
_redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    decode_responses=True,
    retry_on_timeout=True,
    socket_connect_timeout=10,
)


# ---------------------------------------------------------------------------
# EXIF extraction
# ---------------------------------------------------------------------------
def _rational_to_float(val) -> float:
    """Convert IFDRational or tuple (num, denom) to float."""
    if hasattr(val, "numerator") and hasattr(val, "denominator"):
        return val.numerator / val.denominator if val.denominator else 0.0
    if isinstance(val, tuple) and len(val) == 2:
        return val[0] / val[1] if val[1] else 0.0
    return float(val)


def _dms_to_decimal(dms_seq, ref: str) -> float | None:
    """Convert DMS sequence + reference letter to signed decimal degrees."""
    try:
        vals = list(dms_seq)
        if len(vals) < 3:
            return None
        d = _rational_to_float(vals[0])
        m = _rational_to_float(vals[1])
        s = _rational_to_float(vals[2])
        decimal = d + m / 60 + s / 3600
        if ref and str(ref).upper() in ("S", "W"):
            decimal = -decimal
        return round(decimal, 7)
    except Exception:
        return None


def extract_exif(file_path: str) -> dict:
    """Extract EXIF metadata. Returns dict with optional fields only."""
    result: dict = {}

    # --- Strategy 1: piexif (fast, works for JPEG/TIFF) ---
    try:
        exif_bytes = piexif.load(file_path)

        # DateTime (prefer DateTimeOriginal from Exif IFD)
        for ifd_name, tag_id in [
            ("Exif", piexif.ExifIFD.DateTimeOriginal),
            ("0th", piexif.ImageIFD.DateTime),
        ]:
            raw = exif_bytes.get(ifd_name, {}).get(tag_id)
            if raw:
                try:
                    dt_str = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    dt = datetime.strptime(dt_str.strip(), "%Y:%m:%d %H:%M:%S")
                    result["datetime"] = dt.isoformat()
                    break
                except Exception:
                    pass

        # Camera make / model
        make = exif_bytes.get("0th", {}).get(piexif.ImageIFD.Make)
        model = exif_bytes.get("0th", {}).get(piexif.ImageIFD.Model)
        if make:
            result["camera_make"] = (
                make.decode("utf-8", errors="replace").strip("\x00").strip()
                if isinstance(make, bytes)
                else str(make).strip()
            )
        if model:
            result["camera_model"] = (
                model.decode("utf-8", errors="replace").strip("\x00").strip()
                if isinstance(model, bytes)
                else str(model).strip()
            )

        # GPS
        gps = exif_bytes.get("GPS", {})
        if gps:
            lat = _dms_to_decimal(
                gps.get(piexif.GPSIFD.GPSLatitude, []),
                gps.get(piexif.GPSIFD.GPSLatitudeRef, b""),
            )
            lon = _dms_to_decimal(
                gps.get(piexif.GPSIFD.GPSLongitude, []),
                gps.get(piexif.GPSIFD.GPSLongitudeRef, b""),
            )
            if lat is not None:
                result["latitude"] = lat
            if lon is not None:
                result["longitude"] = lon
            alt_raw = gps.get(piexif.GPSIFD.GPSAltitude)
            if alt_raw:
                try:
                    result["altitude"] = round(_rational_to_float(alt_raw), 2)
                except Exception:
                    pass

        if result:
            return result
    except Exception:
        pass

    # --- Strategy 2: PIL getexif() (HEIC via pillow-heif, WEBP) ---
    try:
        with Image.open(file_path) as img:
            exif = img.getexif()
            if not exif:
                return result

            tag_map = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}

            # Datetime
            for dt_key in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
                if dt_key in tag_map:
                    try:
                        dt = datetime.strptime(str(tag_map[dt_key]).strip(), "%Y:%m:%d %H:%M:%S")
                        result["datetime"] = dt.isoformat()
                        break
                    except Exception:
                        pass

            # Camera
            if "Make" in tag_map:
                result["camera_make"] = str(tag_map["Make"]).strip("\x00").strip()
            if "Model" in tag_map:
                result["camera_model"] = str(tag_map["Model"]).strip("\x00").strip()

            # GPS via nested IFD (tag 34853)
            try:
                gps_ifd = exif.get_ifd(34853)
                if gps_ifd:
                    gps_map = {ExifTags.GPSTAGS.get(k, k): v for k, v in gps_ifd.items()}
                    lat = _dms_to_decimal(
                        gps_map.get("GPSLatitude", []),
                        gps_map.get("GPSLatitudeRef", ""),
                    )
                    lon = _dms_to_decimal(
                        gps_map.get("GPSLongitude", []),
                        gps_map.get("GPSLongitudeRef", ""),
                    )
                    if lat is not None:
                        result["latitude"] = lat
                    if lon is not None:
                        result["longitude"] = lon
                    alt_raw = gps_map.get("GPSAltitude")
                    if alt_raw is not None:
                        try:
                            result["altitude"] = round(_rational_to_float(alt_raw), 2)
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Ollama Vision — AI description
# ---------------------------------------------------------------------------
def get_ai_description(file_path: str) -> str:
    """Generate German image description via Ollama Vision. Raises on failure."""
    with Image.open(file_path) as img:
        # Ensure RGB for JPEG encoding
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        elif img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background

        # Resize to max OLLAMA_MAX_IMAGE_PX on longest side
        if max(img.size) > OLLAMA_MAX_IMAGE_PX:
            img.thumbnail((OLLAMA_MAX_IMAGE_PX, OLLAMA_MAX_IMAGE_PX), Image.Resampling.LANCZOS)

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_VISION_MODEL,
            "prompt": (
                "Beschreibe dieses Bild ausführlich auf Deutsch in 3-5 Sätzen. "
                "Beschreibe was du siehst: Personen, Objekte, Szene, Ort, Farben, Stimmung."
            ),
            "images": [image_b64],
            "stream": False,
            "options": {"temperature": 0.3},
        },
        timeout=300,
    )
    resp.raise_for_status()
    description = resp.json().get("response", "")
    return description[:AI_DESCRIPTION_MAX_CHARS]


# ---------------------------------------------------------------------------
# Message processing
# ---------------------------------------------------------------------------
def process_message(payload: dict) -> None:
    file_path = payload.get("file_path", "")
    file_hash = payload.get("file_hash", "")
    file_type = payload.get("file_type", "")
    file_size = payload.get("file_size", 0)
    detected_at = payload.get("detected_at", datetime.now(timezone.utc).isoformat())

    if not file_path or not file_path.startswith("/mnt/nas/"):
        log("error", "Rejected invalid file_path (must start with /mnt/nas/)", file_path=file_path)
        return

    log("info", "Processing image", file_path=file_path, file_hash=file_hash)

    extraction_failed = False
    exif: dict = {}
    ai_description = ""

    try:
        # Verify file is readable
        with Image.open(file_path) as img:
            img.verify()
    except Exception as exc:
        extraction_failed = True
        log("error", "Image open/verify failed", file_path=file_path, error=str(exc))

    if not extraction_failed:
        # EXIF extraction (non-fatal)
        try:
            exif = extract_exif(file_path)
            log("info", "EXIF extracted", file_path=file_path, fields=list(exif.keys()))
        except Exception as exc:
            log("warn", "EXIF extraction failed", file_path=file_path, error=str(exc))

        # Queue for decoupled reverse geocoding (non-fatal, skipped if no GPS)
        if "latitude" in exif and "longitude" in exif:
            try:
                _redis_client.rpush(
                    GEOCODE_PENDING_KEY,
                    json.dumps(
                        {
                            "file_hash": file_hash,
                            "latitude": exif["latitude"],
                            "longitude": exif["longitude"],
                        },
                        ensure_ascii=False,
                    ),
                )
            except Exception as exc:
                log("warn", "Failed to queue geocode_pending entry", file_path=file_path, error=str(exc))

        # AI description (fatal if fails)
        try:
            ai_description = get_ai_description(file_path)
            log("info", "AI description generated", file_path=file_path, chars=len(ai_description))
        except Exception as exc:
            extraction_failed = True
            log("error", "Ollama Vision failed", file_path=file_path, error=str(exc))

    # Build output
    output: dict = {
        "file_path": file_path,
        "file_hash": file_hash,
        "file_type": file_type,
        "file_size": file_size,
        "detected_at": detected_at,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "extractor": "dms-extractor-image",
        "ai_description": ai_description,
        "extraction_failed": extraction_failed,
    }
    if exif:
        output["exif"] = exif

    # Push to Redis
    try:
        _redis_client.rpush(REDIS_KEY, json.dumps(output, ensure_ascii=False))
        log("info", "Result pushed to Redis", file_path=file_path, redis_key=REDIS_KEY)
    except Exception as exc:
        log("error", "Failed to push to Redis, result lost", file_path=file_path, error=str(exc))

    write_heartbeat()


# ---------------------------------------------------------------------------
# MQTT callbacks
# ---------------------------------------------------------------------------
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        log("info", "Connected to MQTT broker")
        client.subscribe(MQTT_TOPIC, qos=1)
        log("info", "Subscribed to MQTT topic", topic=MQTT_TOPIC)
    else:
        log("error", "MQTT connection failed", rc=rc)


def on_disconnect(client, userdata, rc):
    if rc != 0:
        log("warn", "MQTT disconnected unexpectedly", rc=rc)


def on_message(client, userdata, message):
    try:
        payload = json.loads(message.payload.decode("utf-8"))
    except Exception as exc:
        log("error", "Invalid JSON in MQTT message", error=str(exc))
        return
    try:
        process_message(payload)
    except Exception as exc:
        log("error", "Unhandled error in process_message", error=str(exc))


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------
def _shutdown(sig, frame):
    log("info", f"Received signal {sig}, shutting down")
    sys.exit(0)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Start heartbeat thread
    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb_thread.start()
    write_heartbeat()

    log("info", "dms-extractor-image starting", mqtt_host=MQTT_HOST, mqtt_topic=MQTT_TOPIC,
        redis_host=REDIS_HOST, redis_key=REDIS_KEY, ollama_model=OLLAMA_VISION_MODEL)

    client = mqtt.Client(client_id="dms-extractor-image", clean_session=True)
    if MQTT_USERNAME:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=5, max_delay=60)

    client.connect(MQTT_HOST, MQTT_PORT, keepalive=300)
    client.loop_forever()


if __name__ == "__main__":
    main()
