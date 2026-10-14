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

PROJ-112: get_ai_description() is the single image description implementation.
It is also exposed as POST /describe (internal backend network only) for the
n8n backfill. Images wider than 2:1 (or taller than 1:2) are split into up to 8
overlapping tiles, each described separately, then merged by a text-only call.
"""

import base64
import json
import logging
import math
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
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from PIL import Image, ExifTags
from pydantic import BaseModel

# Register HEIC support if available
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    # libheif refuses allocations > 512 MB, i.e. 200 MP photos (PROJ-112).
    # The pixel limit is enforced in get_ai_description() instead.
    pillow_heif.options.DISABLE_SECURITY_LIMITS = True
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

# PROJ-99: llama.cpp OpenAI-compatible endpoint. Base URL WITHOUT /v1.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://llama-3090:11434")
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "qwen3.5:27b-q4_K_M")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "").strip()

AI_DESCRIPTION_MAX_CHARS = 50000
OLLAMA_MAX_IMAGE_PX = int(os.environ.get("OLLAMA_MAX_IMAGE_PX", "1024"))  # longest side per (tile) image sent to the LLM
IMAGE_MAX_PIXELS = int(float(os.environ.get("IMAGE_MAX_MEGAPIXELS", "250")) * 1_000_000)

# PROJ-112: tiling of non-standard aspect ratios
SINGLE_IMAGE_MAX_RATIO = 2.0  # up to 2:1 / 1:2 -> described as one image
TILE_RATIO = 1.5              # tiles are ~3:2 (portrait: 2:3)
TILE_OVERLAP = 0.1            # neighbouring tiles overlap by ~10 %
MAX_TILES = 8

HTTP_PORT = 8012
HEARTBEAT_FILE = "/tmp/heartbeat"
HEARTBEAT_INTERVAL = 30

# Pillow's decompression bomb guard (~179 MP) would reject 200 MP photos on open.
# The limit is enforced in get_ai_description() from the header, before decoding.
Image.MAX_IMAGE_PIXELS = None

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
VISION_PROMPT = (
    "Beschreibe dieses Bild ausführlich auf Deutsch in 3-5 Sätzen. "
    "Beschreibe was du siehst: Personen, Objekte, Szene, Ort, Farben, Stimmung."
)


class DescriptionError(Exception):
    """Description failed. reason: unreadable | too_large | vision_failed."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


# One image at a time (MQTT path and /describe): bounds memory for 200+ MP
# images and matches the single LLM slot.
_describe_lock = threading.Lock()


def tile_boxes(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Crop boxes (left, upper, right, lower): the whole image up to 2:1 / 1:2,
    otherwise up to MAX_TILES overlapping ~3:2 tiles along the long side."""
    long_side, short_side = max(width, height), min(width, height)
    if long_side <= SINGLE_IMAGE_MAX_RATIO * short_side:
        return [(0, 0, width, height)]

    tile = TILE_RATIO * short_side
    count = math.ceil((long_side - tile) / (tile * (1 - TILE_OVERLAP))) + 1
    if count > MAX_TILES:
        # Widen the tiles so MAX_TILES cover the image with the same overlap
        # (beyond ~2:1 per tile for extreme panoramas — accepted, no error).
        count = MAX_TILES
        tile = long_side / (1 + (count - 1) * (1 - TILE_OVERLAP))
    tile = min(long_side, math.ceil(tile))
    step = (long_side - tile) / (count - 1)
    starts = [round(i * step) for i in range(count)]
    if width >= height:
        return [(s, 0, s + tile, height) for s in starts]
    return [(0, s, width, s + tile) for s in starts]


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode == "RGBA":
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))  # not split(): avoids copying all 4 bands
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


def _prepare_jpegs(file_path: str) -> tuple[list[str], bool]:
    """Return one base64 JPEG per tile (longest side <= OLLAMA_MAX_IMAGE_PX),
    ordered left->right / top->bottom, and whether the image is landscape."""
    with Image.open(file_path) as img:
        width, height = img.size
        if width * height > IMAGE_MAX_PIXELS:
            raise DescriptionError("too_large", f"image too large: {round(width * height / 1_000_000)} MP")

        boxes = tile_boxes(width, height)
        # Every tile ends up at <= OLLAMA_MAX_IMAGE_PX, so scale the whole image
        # down first instead of cropping/converting at full resolution. JPEG:
        # libjpeg decodes at reduced scale — 200 MP never sit in RAM.
        tile_long = max(max(r - l, b - u) for l, u, r, b in boxes)
        scale = min(1.0, OLLAMA_MAX_IMAGE_PX / tile_long)
        target = (math.ceil(width * scale), math.ceil(height * scale))
        img.draft("RGB", target)
        if img.mode in ("1", "P"):
            img = _to_rgb(img)  # resize() would fall back to nearest-neighbour for these modes
        if img.size[0] > target[0]:
            img = img.resize(target, Image.Resampling.LANCZOS, reducing_gap=3.0)
        sx, sy = img.size[0] / width, img.size[1] / height

        rgb = _to_rgb(img)
        images = []
        for l, u, r, b in boxes:
            tile = rgb.crop((round(l * sx), round(u * sy), round(r * sx), round(b * sy)))
            tile.thumbnail((OLLAMA_MAX_IMAGE_PX, OLLAMA_MAX_IMAGE_PX), Image.Resampling.LANCZOS)
            buf = BytesIO()
            tile.save(buf, format="JPEG", quality=85)
            images.append(base64.b64encode(buf.getvalue()).decode("utf-8"))
        return images, width >= height


def _chat(content) -> str:
    """Single chat completion; raises on HTTP error or empty answer."""
    headers = {"Content-Type": "application/json"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"

    resp = requests.post(
        f"{OLLAMA_URL}/v1/chat/completions",
        headers=headers,
        json={
            "model": OLLAMA_VISION_MODEL,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "temperature": 0.3,
        },
        timeout=300,
    )
    resp.raise_for_status()
    text = (
        (resp.json().get("choices") or [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    if not text.strip():
        raise RuntimeError("vision model returned an empty description")
    return text


def _image_content(prompt: str, image_b64: str) -> list[dict]:
    return [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
    ]


def get_ai_description(file_path: str) -> str:
    """Generate German image description via the llama.cpp vision model.

    Raises DescriptionError on failure — a failed/empty description must NOT be
    swallowed into a text-only fallback that would produce a meaningless
    description (PROJ-99 edge case: vision request without an mmproj-capable
    model). For tiled images it is all-or-nothing (PROJ-112): any failed tile
    or summary call fails the whole description, no retries.
    """
    with _describe_lock:
        try:
            images, landscape = _prepare_jpegs(file_path)
        except DescriptionError:
            raise
        except Exception as exc:
            raise DescriptionError("unreadable", f"cannot read image: {exc}") from exc

        try:
            if len(images) == 1:
                description = _chat(_image_content(VISION_PROMPT, images[0]))
            else:
                log("info", "Describing image in tiles", file_path=file_path, tiles=len(images))
                parts = []
                for i, image_b64 in enumerate(images, start=1):
                    prompt = (
                        f"Dies ist Ausschnitt {i} von {len(images)} eines Panoramabilds. "
                        "Beschreibe auf Deutsch in 2-3 Sätzen, was du in diesem Ausschnitt siehst: "
                        "Personen, Objekte, Szene, Ort, Farben, Stimmung."
                    )
                    parts.append(_chat(_image_content(prompt, image_b64)).strip())
                direction = "von links nach rechts" if landscape else "von oben nach unten"
                description = _chat(
                    "Die folgenden Texte beschreiben nacheinander überlappende Ausschnitte eines einzigen "
                    f"Panoramabilds, {direction}. Fasse sie zu einer zusammenhängenden Beschreibung des "
                    "gesamten Bildes auf Deutsch in 3-5 Sätzen zusammen. Beschreibe das Bild als eine Szene, "
                    "nicht als Aufzählung der Ausschnitte, und nenne Dinge, die in mehreren Ausschnitten "
                    "vorkommen, nur einmal. Antworte nur mit der Beschreibung.\n\n"
                    + "\n\n".join(f"Ausschnitt {i}: {p}" for i, p in enumerate(parts, start=1))
                )
        except Exception as exc:
            raise DescriptionError("vision_failed", f"vision model failed: {exc}") from exc

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
            log("error", "AI description failed", file_path=file_path, error=str(exc))

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
# Internal HTTP API (PROJ-112) — backend network only, not routed via nginx
# ---------------------------------------------------------------------------
app = FastAPI(title="dms-extractor-image", docs_url=None, redoc_url=None, openapi_url=None)

_ERROR_STATUS = {"invalid_path": 400, "unreadable": 422, "too_large": 422, "vision_failed": 502}


class DescribeRequest(BaseModel):
    file_path: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/describe")
def describe(req: DescribeRequest):
    """Description only (no EXIF/GPS, no Redis). Blocks while another image is processed."""
    file_path = req.file_path
    # realpath: reject ../ escapes out of the NAS mounts
    if not os.path.realpath(file_path).startswith("/mnt/nas/"):
        log("error", "Rejected invalid file_path (must be under /mnt/nas/)", file_path=file_path)
        return JSONResponse({"error": "invalid_path", "detail": "file_path must be under /mnt/nas/"}, status_code=400)

    log("info", "Describe request", file_path=file_path)
    try:
        description = get_ai_description(file_path)
    except DescriptionError as exc:
        log("error", "AI description failed", file_path=file_path, reason=exc.reason, error=str(exc))
        return JSONResponse({"error": exc.reason, "detail": str(exc)}, status_code=_ERROR_STATUS[exc.reason])
    log("info", "AI description generated", file_path=file_path, chars=len(description))
    return {"ai_description": description}


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

    # PROJ-112: a panorama (up to 9 LLM calls, plus gateway queueing) blocks the
    # network loop thread for minutes — keepalive must outlast that.
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=1800)
    client.loop_start()

    uvicorn.run(app, host="0.0.0.0", port=HTTP_PORT, log_level="warning")


if __name__ == "__main__":
    main()
