#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh):
# 1. the service runs and reports the unreachable register (no register in the container test) with its
#    reason: as a warning within IMAGE_REGISTRY_GRACE_SECONDS (60 s), afterwards as unhealthy (AK-37);
#    /status answers (backlog locked by default, backlog boundary from the test PostgreSQL);
#    POST /describe answers 503 while the register is away and 400 for an invalid id;
# 2. inside the image as the non-root NAS account: Pillow + pillow-heif read EXIF of HEIC/TIFF/WebP
#    and prepare a panorama in 8 tiles (installed packages only).
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json, time, urllib.error, urllib.request

def call(path, method="GET"):
    req = urllib.request.Request("http://localhost:8020" + path, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

for _ in range(30):
    status, health = call("/health")
    if any("Register" in m for m in health["warnings"] + health["errors"]):
        break
    time.sleep(1)
assert (status, health["status"]) in ((200, "warning"), (503, "unhealthy")), health
assert any("Register nicht erreichbar" in w for w in health["warnings"] + health["errors"]), health
assert not any("PostgreSQL" in w for w in health["warnings"] + health["errors"]), health
status, body = call("/status")
assert status == 200 and body["active"] == [] and body["concurrency"] == 1, body
assert body["backlog_released"] is False and body["backlog_before"], body
assert body["geoapify"]["daily_limit"] == 3000, body
assert call("/describe/abcdefghijkl", "POST")[0] == 503
assert call("/describe/INVALID", "POST")[0] == 400
print("smoke ok: health", health["status"])
PY
docker exec -i -u 1000:100 "$CT_CONTAINER" python - <<'PY'
import os, tempfile
from PIL import Image
from PIL.TiffImagePlugin import IFDRational as R
from app.imaging import prepare, read_exif

d = tempfile.mkdtemp()
for ext, fmt in (("heic", "HEIF"), ("tif", "TIFF"), ("webp", "WEBP"), ("jpg", "JPEG")):
    e = Image.Exif()
    e[0x010F] = "Canon"
    e.get_ifd(0x8769)[0x9003] = "2024:07:12 14:03:22"
    g = e.get_ifd(0x8825)
    g[1], g[2], g[3], g[4] = "S", (R(33, 1), R(51, 1), R(0, 1)), "W", (R(151, 1), R(12, 1), R(0, 1))
    p = os.path.join(d, "t." + ext)
    Image.new("RGB", (60, 40), (10, 20, 30)).save(p, fmt, exif=e.tobytes())
    info = read_exif(p)
    assert info.taken == "2024-07-12T14:03:22" and info.gps["latitude"] < 0 and info.gps["longitude"] < 0, (ext, info)
    assert len(prepare(p, 1024, 250).jpegs) == 1
pano = os.path.join(d, "pano.jpg")
Image.new("RGB", (22704, 1760), (90, 120, 200)).save(pano, "JPEG")
assert len(prepare(pano, 1024, 250).jpegs) == 8
print("selftest ok")
PY
