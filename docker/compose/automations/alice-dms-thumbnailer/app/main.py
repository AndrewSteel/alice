"""
alice-dms-thumbnailer — FastAPI service for DMS thumbnail generation (PROJ-55).

Endpoints:
  POST /generate           — generate thumbnail from file, save to warm storage
  GET  /thumbnail/{uuid}   — serve thumbnail (or placeholder), JWT auth required
  GET  /health
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import uuid as uuid_mod
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, field_validator, model_validator

from .auth import verify_jwt

# Register HEIC support if available
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
except ImportError:
    pass

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("alice-dms-thumbnailer")

DOCUMENTS_ROOT = os.environ.get("DOCUMENTS_ROOT", "/srv/warm/documents")
THUMB_DIR = Path(os.environ.get("THUMB_DIR", "/srv/warm/documents/thumbnails"))
THUMB_SIZE = 400
PLACEHOLDER_PATH = Path("/app/placeholder.jpg")

app = FastAPI(title="alice-dms-thumbnailer", version="1.0.0")


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    THUMB_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Thumbnail directory: %s", THUMB_DIR)
    if not PLACEHOLDER_PATH.exists():
        logger.warning("Placeholder not found at %s — generating fallback", PLACEHOLDER_PATH)
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (400, 400), color=(31, 41, 55))  # type: ignore[arg-type]
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([115, 100, 285, 300], radius=10, fill=(55, 65, 81))
            d.polygon([(235, 118), (268, 151), (268, 118)], fill=(31, 41, 55))
            for _y in [195, 218, 241, 264]:
                d.line([(142, _y), (258, _y)], fill=(107, 114, 128), width=2)
            img.save(str(PLACEHOLDER_PATH), "JPEG", quality=85)
            logger.info("Fallback placeholder written to %s", PLACEHOLDER_PATH)
        except Exception as exc:
            logger.error("Could not generate placeholder: %s", exc)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class GenerateRequest(BaseModel):
    weaviate_uuid: str
    document_type: str
    file_type: str
    # PROJ-93: Email objects have no NAS file - original_path is required for
    # every other document_type, mail_text is required (and exclusive) for Email.
    original_path: str | None = None
    mail_text: str | None = None

    @field_validator("weaviate_uuid")
    @classmethod
    def _check_uuid(cls, v: str) -> str:
        try:
            uuid_mod.UUID(v)
        except Exception as exc:
            raise ValueError("weaviate_uuid must be a valid UUID") from exc
        return v

    @field_validator("original_path")
    @classmethod
    def _check_path(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("original_path must not be empty")
        # Prevent path traversal
        resolved = Path(v).resolve()
        if not str(resolved).startswith(DOCUMENTS_ROOT):
            raise ValueError(f"original_path not in allowed locations: {v}")
        return v

    @model_validator(mode="after")
    def _check_document_type_pairing(self):
        # A model-level validator (not field_validator) so it can see every
        # field regardless of declaration order.
        if self.document_type == "Email":
            if not (self.mail_text or "").strip():
                raise ValueError("mail_text must not be empty when document_type is Email")
        elif not self.original_path:
            raise ValueError("original_path is required when document_type is not Email")
        return self


# ---------------------------------------------------------------------------
# Thumbnail generation helpers
# ---------------------------------------------------------------------------
def _square_crop(img: Image.Image, top_crop: bool = False) -> Image.Image:
    """Crop image to square. top_crop=True uses top portion; False uses center."""
    w, h = img.size
    size = min(w, h)
    if top_crop:
        left, upper = (w - size) // 2, 0
    else:
        left, upper = (w - size) // 2, (h - size) // 2
    return img.crop((left, upper, left + size, upper + size))


def _run_with_timeout_kill(cmd: list[str], timeout: int) -> None:
    """Run cmd, killing its whole process group on timeout.

    subprocess.run(timeout=...) only terminates the direct child. LibreOffice
    forks a soffice.bin worker that survives that kill, keeps the outdir's
    FDs open, and made shutil.rmtree()/TemporaryDirectory cleanup fail
    (observed as "Too many open files" and orphaned empty /tmp/tmpXXXXXXXX
    dirs after many backfill requests). Running in a new session lets us
    kill the whole group instead of just the immediate child.
    """
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
    )
    try:
        _, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, cmd, stderr=stderr)


def _render_pdf_first_page(pdf_path: str) -> Image.Image | None:
    """Use pdftoppm to render first page of PDF, return PIL Image."""
    tmpdir = tempfile.mkdtemp()
    try:
        out_prefix = os.path.join(tmpdir, "page")
        try:
            _run_with_timeout_kill(
                ["pdftoppm", "-r", "150", "-l", "1", "-jpeg", pdf_path, out_prefix], timeout=60,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("pdftoppm failed for %s: %s", pdf_path, exc)
            return None
        pages = sorted(Path(tmpdir).glob("*.jpg"))
        if not pages:
            return None
        with Image.open(pages[0]) as im:
            return im.copy()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _convert_office_to_pdf(office_path: str) -> str | None:
    """Use LibreOffice headless to convert Office file to PDF, return PDF path."""
    tmpdir = tempfile.mkdtemp()
    try:
        try:
            _run_with_timeout_kill(
                [
                    "libreoffice", "--headless", "--convert-to", "pdf",
                    "--outdir", tmpdir, office_path
                ],
                timeout=120,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
            logger.warning("LibreOffice conversion failed for %s: %s", office_path, exc)
            return None
        pdfs = list(Path(tmpdir).glob("*.pdf"))
        if not pdfs:
            return None
        # Copy to a stable temp file (tmpdir will be deleted)
        stable = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        stable.write(pdfs[0].read_bytes())
        stable.close()
        return stable.name
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _render_text_image(text: str) -> Image.Image | None:
    """Render plaintext (already in memory) as an image. Shared by the
    file-based text preview and the mail preview (PROJ-93, no file on disk)."""
    text = text.strip()
    if not text:
        return None
    img = Image.new("RGB", (800, 800), color=(255, 255, 255))  # type: ignore[arg-type]
    from PIL import ImageDraw, ImageFont
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    draw.multiline_text((10, 10), text[:2000], fill=(30, 30, 30), font=font, spacing=4)
    return img


def _render_text_preview(text_path: str) -> Image.Image | None:
    """Render first N lines of text file as an image."""
    try:
        with open(text_path, encoding="utf-8", errors="replace") as f:
            lines = [f.readline() for _ in range(30)]
        text = "".join(lines)
        return _render_text_image(text)
    except Exception as exc:
        logger.warning("Text render failed for %s: %s", text_path, exc)
        return None


def generate_thumbnail(
    original_path: str | None, file_type: str, mail_text: str | None = None
) -> Image.Image | None:
    """Generate thumbnail image. Returns PIL Image or None on failure.

    PROJ-93: when mail_text is given (Email objects have no NAS file), render
    directly from that text instead of reading original_path.
    """
    if mail_text is not None:
        img = _render_text_image(mail_text)
        if img is None:
            return None
        img = _square_crop(img, top_crop=True)
        img = img.resize((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img

    ext = file_type.lower().lstrip(".")
    img: Image.Image | None = None
    tmp_pdf: str | None = None

    try:
        if ext == "pdf":
            img = _render_pdf_first_page(original_path)
            if img:
                img = _square_crop(img, top_crop=True)

        elif ext in ("docx", "xlsx", "odt", "ods", "doc", "xls"):
            tmp_pdf = _convert_office_to_pdf(original_path)
            if tmp_pdf:
                img = _render_pdf_first_page(tmp_pdf)
                if img:
                    img = _square_crop(img, top_crop=True)

        elif ext in ("jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic"):
            try:
                img = Image.open(original_path).copy()
                img = _square_crop(img, top_crop=False)
            except Exception as exc:
                logger.warning("Image open failed for %s: %s", original_path, exc)

        elif ext in ("txt", "md", "csv"):
            img = _render_text_preview(original_path)
            if img:
                img = _square_crop(img, top_crop=True)

        else:
            logger.info("No thumbnail handler for extension '%s', using placeholder logic", ext)

        if img is None:
            return None

        img = img.resize((THUMB_SIZE, THUMB_SIZE), Image.Resampling.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        return img

    finally:
        if tmp_pdf:
            try:
                os.unlink(tmp_pdf)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------
@app.post("/generate")
async def generate(req: GenerateRequest):
    """
    Generate a 400×400 JPEG thumbnail for the given document.
    Called by the alice-dms-thumbnailer n8n workflow.
    No JWT auth — internal-only endpoint (not exposed via nginx).
    """
    thumb_path = THUMB_DIR / f"{req.weaviate_uuid}.jpg"

    if req.document_type != "Email":
        src = Path(req.original_path)  # type: ignore[arg-type]
        if not src.exists():
            logger.warning("Source file not found: %s", req.original_path)
            raise HTTPException(status_code=422, detail=f"Source file not found: {req.original_path}")

    try:
        # generate_thumbnail() is blocking (subprocess.run, Pillow) and can run
        # for up to ~120s; calling it directly here would block uvicorn's
        # event loop and stall every other in-flight request behind it. Under
        # the backfill's unthrottled concurrency (n8n fires all batch items in
        # parallel) that queued up hundreds of accepted-but-unserved
        # connections until the container hit its open-file limit.
        img = await run_in_threadpool(
            generate_thumbnail, req.original_path, req.file_type, req.mail_text
        )
    except Exception as exc:
        logger.warning(
            "Thumbnail generation raised for %s (type=%s): %s: %s",
            req.original_path, req.file_type, type(exc).__name__, exc,
        )
        raise HTTPException(
            status_code=422,
            detail=f"Thumbnail generation failed: {type(exc).__name__}: {exc}",
        ) from exc

    if img is None:
        logger.warning("Thumbnail generation returned None for %s (type=%s)", req.original_path, req.file_type)
        raise HTTPException(status_code=422, detail="Thumbnail generation failed")

    try:
        img.save(str(thumb_path), "JPEG", quality=85)
    except Exception as exc:
        logger.warning("Thumbnail save failed for %s: %s: %s", thumb_path, type(exc).__name__, exc)
        raise HTTPException(
            status_code=422,
            detail=f"Thumbnail save failed: {type(exc).__name__}: {exc}",
        ) from exc

    logger.info("Thumbnail saved: %s", thumb_path)
    return {"thumbnail_path": str(thumb_path), "weaviate_uuid": req.weaviate_uuid, "document_type": req.document_type}


# ---------------------------------------------------------------------------
# GET /thumbnail/{uuid}
# ---------------------------------------------------------------------------
@app.get("/thumbnail/{weaviate_uuid}")
async def serve_thumbnail(
    weaviate_uuid: str,
    _jwt: dict = Depends(verify_jwt),
):
    """Serve thumbnail JPEG. Falls back to bundled placeholder — never returns 404."""
    # Validate UUID format to prevent path traversal
    safe = re.fullmatch(r"[0-9a-f-]{36}", weaviate_uuid)
    if not safe:
        # Fall through to placeholder
        return FileResponse(
            str(PLACEHOLDER_PATH),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=60"},
        )

    thumb_path = THUMB_DIR / f"{weaviate_uuid}.jpg"
    if thumb_path.exists():
        return FileResponse(
            str(thumb_path),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    return FileResponse(
        str(PLACEHOLDER_PATH),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=60"},
    )


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    thumb_dir_ok = THUMB_DIR.exists()
    jwt_ok = bool(os.environ.get("JWT_PUBLIC_KEY_PATH"))
    status = "ok" if (thumb_dir_ok and jwt_ok) else "degraded"
    return {
        "status": status,
        "thumb_dir": str(THUMB_DIR),
        "thumb_dir_exists": thumb_dir_ok,
        "documents_root": DOCUMENTS_ROOT,
    }
