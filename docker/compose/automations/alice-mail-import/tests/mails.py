"""Test mails (built here, no real data): plain, with PDFs, embedded cid images, forwarded mails,
encodings, broken MIME."""
from __future__ import annotations

from email.message import EmailMessage
from email.policy import SMTP

PDF = b"%PDF-1.4\n" + bytes(range(256)) * 20 + b"\n%%EOF\n"
PDF2 = b"%PDF-1.4\n" + bytes(reversed(range(256))) * 30 + b"\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\n" + bytes(range(200))
DE_TEXT = ("Hallo zusammen, ich wollte euch nur kurz sagen, dass die Rechnung für den Strom jetzt da ist und "
           "wir sie bis zum Monatsende bezahlen müssen. Bitte gebt mir Bescheid, wenn ihr noch Fragen habt. "
           "Viele Grüße und bis morgen")
EN_TEXT = ("Hello everyone, I just wanted to let you know that the invoice for the electricity has arrived and "
           "we have to pay it by the end of the month. Please let me know if you have any questions about it. "
           "Thanks and best regards")


def make(subject="Testmail", body=DE_TEXT, *, msgid: str | None = "<m1@example.invalid>", sender="Anna Beispiel <anna@example.invalid>",
         to="Ben Beispiel <ben@example.invalid>", cc=None, bcc=None, date="Thu, 05 Nov 2026 10:00:00 +0100",
         html: str | None = None, attachments=(), extra_headers=None) -> bytes:
    m = EmailMessage()
    if subject is not None:
        m["Subject"] = subject
    m["From"] = sender
    m["To"] = to
    if cc:
        m["Cc"] = cc
    if bcc:
        m["Bcc"] = bcc
    if date:
        m["Date"] = date
    if msgid:
        m["Message-ID"] = msgid
    for k, v in (extra_headers or {}).items():
        m[k] = v
    if body is not None:
        m.set_content(body)
    if html is not None:
        if body is None:
            m.set_content(html, subtype="html")
        else:
            m.add_alternative(html, subtype="html")
    for name, data, maintype, subtype in attachments:
        m.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return m.as_bytes(policy=SMTP)


def with_pdfs(msgid="<pdf@example.invalid>") -> bytes:
    return make("Ihre Rechnungen", msgid=msgid, html="<p>Siehe <b>Anhang</b></p>",
                attachments=[("rechnung-a.pdf", PDF, "application", "pdf"), ("rechnung-b.pdf", PDF2, "application", "pdf")])


def with_cid_images(msgid="<cid@example.invalid>") -> bytes:
    m = EmailMessage()
    m["Subject"] = "Newsletter mit Logo"
    m["From"] = "shop@example.invalid"
    m["To"] = "ben@example.invalid"
    m["Date"] = "Thu, 05 Nov 2026 10:00:00 +0100"
    m["Message-ID"] = msgid
    m.set_content("Text-Teil")
    m.add_alternative('<p>Hallo <img src="cid:logo@x"> und <img src="cid:sig@x"></p>', subtype="html")
    html = m.get_payload()[1]
    html.add_related(PNG, maintype="image", subtype="png", cid="<logo@x>", filename="logo.png")
    html.add_related(PNG[:50], maintype="image", subtype="png", cid="<sig@x>", filename="signatur.png")
    m.add_attachment(PNG + b"real", maintype="image", subtype="png", filename="foto.png")
    return m.as_bytes(policy=SMTP)


def with_forward(msgid="<fwd@example.invalid>") -> tuple[bytes, bytes]:
    inner = make("Original", "Ursprünglicher Text", msgid="<inner@example.invalid>")
    m = EmailMessage()
    m["Subject"] = "Fwd: Original"
    m["From"] = "ben@example.invalid"
    m["To"] = "anna@example.invalid"
    m["Date"] = "Thu, 05 Nov 2026 11:00:00 +0100"
    m["Message-ID"] = msgid
    m.set_content("Siehe weitergeleitete Mail")
    from email import message_from_bytes
    from email.policy import compat32
    m.add_attachment(message_from_bytes(inner, policy=compat32))
    return m.as_bytes(policy=SMTP), inner


def with_same_names(msgid="<names@example.invalid>") -> bytes:
    return make("Drei Anhänge", msgid=msgid, attachments=[
        ("rechnung.pdf", PDF, "application", "pdf"), ("rechnung.pdf", PDF2, "application", "pdf"),
        ("Übersicht März.pdf", PDF[:100], "application", "pdf")])


BROKEN = (b"From: anna@example.invalid\r\nTo: ben@example.invalid\r\nSubject: Kaputt\r\n"
          b"Message-ID: <broken@example.invalid>\r\nDate: Thu, 05 Nov 2026 10:00:00 +0100\r\nMIME-Version: 1.0\r\n"
          b"Content-Type: multipart/mixed; boundary=\"XYZ\"\r\n\r\nkein Boundary hier\r\n--ABC\r\n"
          b"Content-Type: text/plain\r\n\r\nirgendwas\r\n")

LATIN1 = (b"From: =?iso-8859-1?q?J=FCrgen_M=FCller?= <j@example.invalid>\r\nTo: ben@example.invalid\r\n"
          b"Subject: =?iso-8859-1?q?Gr=FC=DFe_aus_K=F6ln?=\r\nMessage-ID: <latin@example.invalid>\r\n"
          b"Date: Thu, 05 Nov 2026 10:00:00 +0100\r\nMIME-Version: 1.0\r\n"
          b"Content-Type: text/plain; charset=iso-8859-1\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
          b"Sch\xf6ne Gr\xfc\xdfe aus K\xf6ln\r\n")

WRONG_CHARSET = (b"From: anna@example.invalid\r\nTo: ben@example.invalid\r\nSubject: Falsch deklariert\r\n"
                 b"Message-ID: <wrong@example.invalid>\r\nDate: Thu, 05 Nov 2026 10:00:00 +0100\r\nMIME-Version: 1.0\r\n"
                 b"Content-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
                 b"Gr\xfc\xdfe \xfcber alles\r\n")

UNKNOWN_CHARSET = (b"From: anna@example.invalid\r\nTo: ben@example.invalid\r\nSubject: Unbekannt\r\n"
                   b"Message-ID: <unknown@example.invalid>\r\nDate: Thu, 05 Nov 2026 10:00:00 +0100\r\nMIME-Version: 1.0\r\n"
                   b"Content-Type: text/plain; charset=x-gibts-nicht\r\nContent-Transfer-Encoding: 8bit\r\n\r\n"
                   b"Gr\xc3\xbc\xc3\x9fe\r\n")
