"""Reading images: EXIF (time, GPS, camera, displayed size) and the JPEGs sent to the vision model.

Tiling of wide/tall images (PROJ-112, taken over from dms-extractor-image): up to 2:1 / 1:2 one
image, beyond that up to 8 overlapping ~3:2 tiles along the long side, each with its longest side
<= max_side. The pixel limit is checked from the header before anything is decoded.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from PIL import Image, ImageFile

from .errors import PermanentError

try:  # HEIC/HEIF (pillow-heif)
    import pillow_heif

    pillow_heif.register_heif_opener()
    # libheif refuses allocations > 512 MB (200 MP photos); the own pixel limit applies instead
    pillow_heif.options.DISABLE_SECURITY_LIMITS = True
except ImportError:  # pragma: no cover
    pass

# Pillow's decompression bomb guard would reject 200 MP photos; the limit is checked from the header.
Image.MAX_IMAGE_PIXELS = None

SINGLE_IMAGE_MAX_RATIO = 2.0  # up to 2:1 / 1:2 -> one image
TILE_RATIO = 1.5              # tiles are ~3:2 (portrait: 2:3)
TILE_OVERLAP = 0.1            # neighbouring tiles overlap by ~10 %
MAX_TILES = 8

TAG_ORIENTATION = 0x0112
TAG_MAKE, TAG_MODEL, TAG_DATETIME = 0x010F, 0x0110, 0x0132
IFD_EXIF, IFD_GPS = 0x8769, 0x8825
TAG_DATETIME_ORIGINAL, TAG_DATETIME_DIGITIZED = 0x9003, 0x9004
TAG_OFFSET_TIME_ORIGINAL, TAG_OFFSET_TIME_DIGITIZED, TAG_OFFSET_TIME = 0x9011, 0x9012, 0x9010
GPS_LAT_REF, GPS_LAT, GPS_LON_REF, GPS_LON, GPS_ALT_REF, GPS_ALT = 1, 2, 3, 4, 5, 6


@dataclass
class ImageInfo:
    width: int
    height: int
    taken: str | None = None
    gps: dict | None = None
    camera: dict | None = None

    def fields(self) -> dict:
        return {"taken": self.taken, "width": self.width, "height": self.height, "gps": self.gps,
                "camera": self.camera}


@dataclass
class Prepared:
    info: ImageInfo
    jpegs: list[str] = field(default_factory=list)  # base64, in reading order
    landscape: bool = True


# ---------------------------------------------------------------- EXIF
def _num(value) -> float | None:
    try:
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            return value.numerator / value.denominator if value.denominator else None
        if isinstance(value, tuple) and len(value) == 2:
            return value[0] / value[1] if value[1] else None
        out = float(value)
        return out if math.isfinite(out) else None
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _text(value) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).replace("\x00", "").strip() if value is not None else ""


def dms_to_decimal(dms, ref) -> float | None:
    """Degrees/minutes/seconds + N/S/E/W → signed decimal degrees (AK-8)."""
    try:
        parts = [_num(v) for v in list(dms)[:3]]
    except TypeError:
        return None
    if len(parts) < 3 or any(p is None for p in parts):
        return None
    value = parts[0] + parts[1] / 60 + parts[2] / 3600
    if _text(ref).upper() in ("S", "W"):
        value = -value
    return round(value, 7)


def _gps(gps_ifd) -> dict | None:
    if not gps_ifd:
        return None
    lat = dms_to_decimal(gps_ifd.get(GPS_LAT, ()), gps_ifd.get(GPS_LAT_REF, ""))
    lon = dms_to_decimal(gps_ifd.get(GPS_LON, ()), gps_ifd.get(GPS_LON_REF, ""))
    # 0/0 or out of range counts as no GPS (EC-3)
    if lat is None or lon is None or (lat == 0 and lon == 0) or abs(lat) > 90 or abs(lon) > 180:
        return None
    alt = _num(gps_ifd.get(GPS_ALT)) if gps_ifd.get(GPS_ALT) is not None else None
    if alt is not None:
        ref = gps_ifd.get(GPS_ALT_REF)
        if (ref[0] if isinstance(ref, bytes) and ref else ref) == 1:  # below sea level
            alt = -alt
        alt = round(alt, 2)
    return {"latitude": lat, "longitude": lon, "altitude": alt}


def _taken(base, exif_ifd) -> str | None:
    """`YYYY-MM-DDThh:mm:ss` of the camera clock, with offset if the image states one; taken as read
    (EC-2)."""
    for tag, offset_tag, ifd in ((TAG_DATETIME_ORIGINAL, TAG_OFFSET_TIME_ORIGINAL, exif_ifd),
                                 (TAG_DATETIME_DIGITIZED, TAG_OFFSET_TIME_DIGITIZED, exif_ifd),
                                 (TAG_DATETIME, TAG_OFFSET_TIME, base)):
        raw = _text(ifd.get(tag)) if ifd else ""
        if not raw:
            continue
        try:
            dt = datetime.strptime(raw[:19], "%Y:%m:%d %H:%M:%S")
        except ValueError:
            continue
        out = dt.strftime("%Y-%m-%dT%H:%M:%S")
        offset = _text(exif_ifd.get(offset_tag)) if exif_ifd else ""
        if len(offset) == 6 and offset[0] in "+-" and offset[3] == ":":
            out += offset
        return out
    return None


def read_info(img: Image.Image) -> ImageInfo:
    """EXIF of an opened image (all formats; HEIC through pillow-heif, EC-1). Missing EXIF is no error."""
    try:
        exif = img.getexif()
    except Exception:
        exif = None
    width, height = img.size
    base = exif or {}
    orientation = base.get(TAG_ORIENTATION) if exif else None
    if orientation in (5, 6, 7, 8):  # rotated by 90°: displayed size is swapped (EC-10)
        width, height = height, width
    info = ImageInfo(width=width, height=height)
    if not exif:
        return info
    try:
        exif_ifd = exif.get_ifd(IFD_EXIF)
    except Exception:
        exif_ifd = {}
    try:
        gps_ifd = exif.get_ifd(IFD_GPS)
    except Exception:
        gps_ifd = {}
    info.taken = _taken(base, exif_ifd)
    info.gps = _gps(gps_ifd)
    make, model = _text(base.get(TAG_MAKE)), _text(base.get(TAG_MODEL))
    info.camera = {"make": make or None, "model": model or None} if (make or model) else None
    return info


def open_image(path: str) -> Image.Image:
    """Open lazily (header only). Unreadable / not decodable → PermanentError; file system errors
    (missing, NAS) propagate as OSError with errno."""
    try:
        img = Image.open(path)
    except OSError as exc:
        if exc.errno is not None:
            raise
        raise PermanentError(f"Bilddatei nicht lesbar ({_short(exc)})") from None
    except Exception as exc:  # Image.DecompressionBombError, ValueError, SyntaxError of plugins
        raise PermanentError(f"Bilddatei nicht lesbar ({_short(exc)})") from None
    return img


def _short(exc: Exception) -> str:
    return (str(exc) or exc.__class__.__name__).splitlines()[0][:200]


def read_exif(path: str) -> ImageInfo:
    with open_image(path) as img:
        return read_info(img)


# ---------------------------------------------------------------- tiles
def tile_boxes(width: int, height: int) -> list[tuple[int, int, int, int]]:
    """Crop boxes (left, upper, right, lower): the whole image up to 2:1 / 1:2, otherwise up to
    MAX_TILES overlapping ~3:2 tiles along the long side (PROJ-112)."""
    long_side, short_side = max(width, height), min(width, height)
    if long_side <= SINGLE_IMAGE_MAX_RATIO * short_side:
        return [(0, 0, width, height)]
    tile = TILE_RATIO * short_side
    count = math.ceil((long_side - tile) / (tile * (1 - TILE_OVERLAP))) + 1
    if count > MAX_TILES:
        # wider tiles so MAX_TILES cover the image with the same overlap (extreme panoramas)
        count = MAX_TILES
        tile = long_side / (1 + (count - 1) * (1 - TILE_OVERLAP))
    tile = min(long_side, math.ceil(tile))
    step = (long_side - tile) / (count - 1)
    starts = [round(i * step) for i in range(count)]
    if width >= height:
        return [(s, 0, s + tile, height) for s in starts]
    return [(0, s, width, s + tile) for s in starts]


def _to_rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.getchannel("A"))
        return background
    if img.mode != "RGB":
        return img.convert("RGB")
    return img


_TRANSPOSE = {2: Image.Transpose.FLIP_LEFT_RIGHT, 3: Image.Transpose.ROTATE_180,
              4: Image.Transpose.FLIP_TOP_BOTTOM, 5: Image.Transpose.TRANSPOSE, 6: Image.Transpose.ROTATE_270,
              7: Image.Transpose.TRANSVERSE, 8: Image.Transpose.ROTATE_90}


def _rotated_size(size: tuple[int, int], orientation) -> tuple[int, int]:
    return (size[1], size[0]) if orientation in (5, 6, 7, 8) else size


def _prepare(path: str, max_side: int, max_pixels: int) -> Prepared:
    with open_image(path) as img:
        raw_w, raw_h = img.size
        if raw_w * raw_h > max_pixels:
            raise PermanentError(f"Bild zu groß ({round(raw_w * raw_h / 1_000_000)} MP, Grenze "
                                 f"{round(max_pixels / 1_000_000)} MP)")
        info = read_info(img)
        try:
            orientation = img.getexif().get(TAG_ORIENTATION)
        except Exception:
            orientation = None
        width, height = info.width, info.height  # displayed size
        boxes = tile_boxes(width, height)
        tile_long = max(max(r - l, b - u) for l, u, r, b in boxes)
        scale = min(1.0, max_side / tile_long)
        target = _rotated_size((math.ceil(width * scale), math.ceil(height * scale)), orientation)
        img.draft("RGB", target)  # JPEG: decode at reduced scale, 200 MP never sit in RAM
        frame = img
        if frame.mode in ("1", "P", "I;16", "I", "F"):
            frame = _to_rgb(frame)  # resize() would fall back to nearest neighbour for these modes
        if frame.size[0] > target[0]:
            frame = frame.resize(target, Image.Resampling.LANCZOS, reducing_gap=3.0)
        else:
            frame.load()
        if orientation in _TRANSPOSE:  # upright as displayed (EC-10); resize() dropped the EXIF
            frame = frame.transpose(_TRANSPOSE[orientation])
        rgb = _to_rgb(frame)
        sx, sy = rgb.size[0] / width, rgb.size[1] / height
        jpegs = []
        for l, u, r, b in boxes:
            tile = rgb.crop((round(l * sx), round(u * sy), round(r * sx), round(b * sy)))
            tile.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            buf = BytesIO()
            tile.save(buf, format="JPEG", quality=85)
            jpegs.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        return Prepared(info=info, jpegs=jpegs, landscape=width >= height)


def prepare(path: str, max_side: int, max_megapixels: float) -> Prepared:
    """EXIF + JPEG(s) for the vision model (first frame/page only, EC-9; turned upright, EC-10).
    Retried once with Pillow's truncated-image tolerance (Samsung panoramas carry a non-standard
    marker after the scan data that only libjpeg tolerates)."""
    max_pixels = int(max_megapixels * 1_000_000)
    try:
        return _prepare(path, max_side, max_pixels)
    except PermanentError:
        raise
    except OSError as exc:
        if exc.errno is not None:  # file system error (missing, NAS), not a decoder error
            raise
        first = exc
    except Exception as exc:
        raise PermanentError(f"Bild nicht dekodierbar ({_short(exc)})") from None
    ImageFile.LOAD_TRUNCATED_IMAGES = True  # global, but the worker prepares one image at a time
    try:
        return _prepare(path, max_side, max_pixels)
    except PermanentError:
        raise
    except OSError as exc:
        if exc.errno is not None:
            raise
        raise PermanentError(f"Bild nicht dekodierbar ({_short(first)})") from None
    except Exception as exc:
        raise PermanentError(f"Bild nicht dekodierbar ({_short(exc)})") from None
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = False
