#!/usr/bin/env bash
# Container smoke test (scripts/test-containers.sh): the service runs with the throwaway database,
# answers /health and /status, the reconciliation endpoints validate their input, and the image
# contains everything the import needs (IMAP, MIME, HTML → Markdown, AES). Calls only from inside
# the container; no register, mail server or LLM is reachable here.
set -euo pipefail
docker exec -i "$CT_CONTAINER" python - <<'PY'
import json, urllib.error, urllib.request

BASE = "http://localhost:8019"

def call(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")

status, health = call("GET", "/health")
assert status == 200 and health["status"] in ("healthy", "warning"), health
status, st = call("GET", "/status")
assert status == 200 and st["mailboxes"] == [] and "import" in st, st
status, out = call("POST", "/reconcile/repair", {"items": [{"type": "mail_import"}]})
assert status == 422, (status, out)
status, out = call("POST", "/reconcile/repair", {"items": [{"type": "delete_everything"}]})
assert status == 422, (status, out)

# the parts of the pipeline that need no other service
from app import mailmd, mime
from app.crypto import decrypt_password, encrypt_password
raw = (b"From: =?utf-8?q?J=C3=BCrgen?= <j@example.invalid>\r\nTo: b@example.invalid\r\nSubject: Test\r\n"
       b"Message-ID: <smoke@example.invalid>\r\nMIME-Version: 1.0\r\nContent-Type: text/html; charset=utf-8\r\n\r\n"
       b"<p>Hallo <a href='https://example.invalid'>Link</a><img src='x.png'></p>\r\n")
prep = mime.prepare(raw)
fields, content = mailmd.build(raw, {"eml_path": "k/x.eml", "attachments": []}, "/mnt/nas/ai/mail",
                               __import__("zoneinfo").ZoneInfo("Europe/Berlin"))
assert prep.hash.startswith("mid:") and fields["from"]["name"] == "Jürgen", fields
assert "[Link](https://example.invalid)" in content and "x.png" not in content, content
assert decrypt_password(encrypt_password("pw", "k", b"0" * 16), "k") == "pw"
print("smoke ok")
PY
