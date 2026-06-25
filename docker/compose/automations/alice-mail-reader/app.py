"""
alice-mail-reader — HTTP wrapper around Python's imaplib.
Called by n8n (alice-mail-sync) to fetch email metadata and bodies.

Endpoints:
  GET  /health         — liveness check
  POST /encrypt        — encrypt a plaintext IMAP password (used by alice-mail-api)
  POST /test           — test IMAP login (accepts password_enc)
  POST /fetch          — fetch emails since a given IMAP UID, returns metadata + body preview
  POST /body           — fetch full body of a single email by UID

Passwords are encrypted with AES-256-CBC. The key is derived from MAIL_ENC_KEY (env).
Plaintext passwords never leave this container.
"""

from __future__ import annotations

import email as email_lib
from email.header import decode_header
import hashlib
import imaplib
import logging
import os
from datetime import datetime

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from flask import Flask, request, jsonify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alice-mail-reader")

app = Flask(__name__)
MAX_EMAILS_PER_FETCH = 50


def _get_key() -> bytes:
    raw = os.environ.get("MAIL_ENC_KEY", "")
    if not raw:
        raise RuntimeError("MAIL_ENC_KEY not configured")
    return hashlib.sha256(raw.encode()).digest()


def _encrypt_password(plaintext: str) -> str:
    iv = os.urandom(16)
    cipher = AES.new(_get_key(), AES.MODE_CBC, iv)
    return iv.hex() + ":" + cipher.encrypt(pad(plaintext.encode("utf-8"), 16)).hex()


def _decrypt_password(password_enc: str) -> str:
    iv_hex, enc_hex = password_enc.split(":")
    cipher = AES.new(_get_key(), AES.MODE_CBC, bytes.fromhex(iv_hex))
    return unpad(cipher.decrypt(bytes.fromhex(enc_hex)), 16).decode("utf-8")


def _safe_decode(payload: bytes, charset: str | None) -> str:
    cs = charset or "utf-8"
    try:
        return payload.decode(cs, errors="replace")
    except (LookupError, UnicodeDecodeError):
        return payload.decode("latin-1", errors="replace")


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts = decode_header(value)
    out = []
    for raw, charset in parts:
        if isinstance(raw, bytes):
            out.append(_safe_decode(raw, charset))
        else:
            out.append(raw)
    return " ".join(out).strip()


def _get_text(msg) -> str:
    """Extract plaintext body (first text/plain part, max 500 chars)."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return _safe_decode(payload, part.get_content_charset())[:500]
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return _safe_decode(payload, msg.get_content_charset())[:500]
    return ""


def _get_full_body(msg) -> str:
    """Extract full body, preferring HTML over plain-text."""
    html_body = ""
    plain_body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            text = _safe_decode(payload, part.get_content_charset())
            if ct == "text/html" and not html_body:
                html_body = text
            elif ct == "text/plain" and not plain_body:
                plain_body = text
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            plain_body = _safe_decode(payload, msg.get_content_charset())
    return html_body or plain_body


def _get_attachments(msg) -> list[dict]:
    attachments = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            continue
        filename = _decode_header(part.get_filename())
        if not filename:
            continue
        payload = part.get_payload(decode=True)
        attachments.append({
            "name": filename,
            "mime_type": part.get_content_type(),
            "size_bytes": len(payload) if payload else 0,
        })
    return attachments


def _connect(data: dict):
    host = data["host"]
    port = int(data.get("port", 993))
    ssl = data.get("ssl", True)
    if ssl:
        return imaplib.IMAP4_SSL(host, port)
    return imaplib.IMAP4(host, port)


@app.route("/health")
def health():
    return jsonify({"status": "ok"})


@app.route("/encrypt", methods=["POST"])
def encrypt_password():
    data = request.json or {}
    plaintext = data.get("password", "")
    if not plaintext:
        return jsonify({"error": "password required"}), 400
    try:
        return jsonify({"password_enc": _encrypt_password(plaintext)})
    except Exception as exc:
        log.exception("encrypt_password failed")
        return jsonify({"error": str(exc)}), 500


@app.route("/test", methods=["POST"])
def test_connection():
    data = request.json or {}
    try:
        password = _decrypt_password(data["password_enc"])
        imap = _connect(data)
        imap.login(data["username"], password)
        imap.select("INBOX", readonly=True)
        imap.logout()
        return jsonify({"ok": True, "message": "Verbindung erfolgreich"})
    except imaplib.IMAP4.error as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    except Exception as exc:
        log.exception("test_connection failed")
        return jsonify({"ok": False, "message": str(exc)}), 500


@app.route("/fetch", methods=["POST"])
def fetch_emails():
    data = request.json or {}
    since_uid = int(data.get("since_uid", 0))
    since_date = data.get("since_date")  # ISO date string e.g. "2026-01-15", only used when since_uid=0
    limit = min(int(data.get("limit", 10)), MAX_EMAILS_PER_FETCH)
    folder = data.get("folder", "INBOX")

    try:
        password = _decrypt_password(data["password_enc"])
        imap = _connect(data)
        imap.login(data["username"], password)
        imap.select(folder, readonly=True)

        if since_uid > 0:
            typ, search_data = imap.uid("search", None, f"UID {since_uid + 1}:*")
        elif since_date:
            try:
                dt = datetime.strptime(since_date[:10], "%Y-%m-%d")
                imap_date = dt.strftime("%d-%b-%Y")  # IMAP format: 15-Jan-2026
                typ, search_data = imap.uid("search", None, f"SINCE {imap_date}")
            except (ValueError, Exception):
                typ, search_data = imap.uid("search", None, "ALL")
        else:
            typ, search_data = imap.uid("search", None, "ALL")

        if typ != "OK":
            imap.logout()
            return jsonify({"emails": [], "max_uid": since_uid, "error": "search failed"})

        uid_bytes = search_data[0].split() if search_data[0] else []
        uid_bytes = uid_bytes[:limit]

        emails = []
        max_uid = since_uid

        for uid_b in uid_bytes:
            uid_str = uid_b.decode()
            uid_int = int(uid_str)

            typ, msg_data = imap.uid("fetch", uid_b, "(RFC822)")
            if typ != "OK" or not msg_data or msg_data[0] is None:
                continue

            raw = msg_data[0][1]
            msg = email_lib.message_from_bytes(raw)

            attachments = _get_attachments(msg)
            emails.append({
                "uid": uid_int,
                "message_id": str(msg.get("Message-ID") or "").strip("<>").strip(),
                "subject": _decode_header(msg.get("Subject")),
                "sender": _decode_header(msg.get("From")),
                "recipients": _decode_header(msg.get("To")),
                "date": str(msg.get("Date") or ""),
                "body_preview": _get_text(msg),
                "attachments": attachments,
                "has_attachments": len(attachments) > 0,
            })
            max_uid = max(max_uid, uid_int)

        imap.logout()
        return jsonify({"emails": emails, "max_uid": max_uid})

    except imaplib.IMAP4.error as exc:
        return jsonify({"emails": [], "max_uid": since_uid, "error": str(exc)}), 400
    except Exception as exc:
        log.exception("fetch_emails failed")
        return jsonify({"emails": [], "max_uid": since_uid, "error": str(exc)}), 500


@app.route("/body", methods=["POST"])
def fetch_body():
    data = request.json or {}
    uid = str(data.get("uid", ""))
    folder = data.get("folder", "INBOX")

    if not uid:
        return jsonify({"error": "uid required"}), 400

    try:
        password = _decrypt_password(data["password_enc"])
        imap = _connect(data)
        imap.login(data["username"], password)
        imap.select(folder, readonly=True)

        typ, msg_data = imap.uid("fetch", uid.encode(), "(RFC822)")
        if typ != "OK" or not msg_data or msg_data[0] is None:
            imap.logout()
            return jsonify({"error": "E-Mail nicht gefunden"}), 404

        raw = msg_data[0][1]
        msg = email_lib.message_from_bytes(raw)
        body = _get_full_body(msg)
        imap.logout()
        return jsonify({"body": body})

    except imaplib.IMAP4.error as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        log.exception("fetch_body failed")
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8007)
