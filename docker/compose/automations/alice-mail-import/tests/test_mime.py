"""Unit tests: identity, attachments, archived .eml, encodings (no IMAP, no database)."""
from email import message_from_bytes
from email.policy import default
from zoneinfo import ZoneInfo

import yaml

from app import mailmd, mime

from . import mails

TZ = ZoneInfo("Europe/Berlin")


def archive(raw: bytes, sid="abcdefghijkl"):
    prep = mime.prepare(raw)
    eml = prep.archived_eml(f"{sid}.attachments", raw)
    atts = [{"filename": a.filename, "mime_type": a.mime_type, "size": a.size,
             "path": f"k/2026/11/{sid}.attachments/{a.filename}"} for a in prep.attachments]
    return prep, eml, {"eml_path": f"k/2026/11/{sid}.eml", "attachments": atts}


def test_identity_by_message_id():
    a = mime.prepare(mails.make(msgid="<X@Example.invalid>"))
    b = mime.prepare(mails.make(msgid="<x@example.invalid>", body="anderer Inhalt"))
    assert a.hash == b.hash and a.hash.startswith("mid:")  # EC-3: same Message-ID = same mail
    assert a.location_key == "<X@Example.invalid>"


def test_identity_without_message_id():  # AK-8
    one = mime.prepare(mails.make(msgid=None, body="eins"))
    two = mime.prepare(mails.make(msgid=None, body="zwei"))
    again = mime.prepare(mails.make(msgid=None, body="eins"))
    assert one.hash != two.hash and one.hash == again.hash and one.hash.startswith("mfp:")
    assert one.location_key.startswith("fp:")


def test_pdfs_are_moved_out_byte_identical():  # AK-10, AK-11
    raw = mails.with_pdfs()
    prep, eml, _ = archive(raw)
    assert [a.filename for a in prep.attachments] == ["rechnung-a.pdf", "rechnung-b.pdf"]
    assert prep.attachments[0].data == mails.PDF and prep.attachments[1].data == mails.PDF2
    msg = message_from_bytes(eml, policy=default)
    orig = message_from_bytes(raw, policy=default)
    for h in ("From", "To", "Subject", "Date", "Message-ID"):
        assert msg[h] == orig[h]
    assert msg.get_body(("plain",)).get_content().strip() == mails.DE_TEXT
    assert "Anhang" in msg.get_body(("html",)).get_content()
    refs = [p for p in msg.walk() if p.get_content_type() == "message/external-body"]
    assert [p.get_param("name") for p in refs] == ["abcdefghijkl.attachments/rechnung-a.pdf",
                                                   "abcdefghijkl.attachments/rechnung-b.pdf"]
    assert [p.get_filename() for p in refs] == ["rechnung-a.pdf", "rechnung-b.pdf"]
    assert len(eml) < len(raw) - len(mails.PDF)
    assert mails.PDF[200:260] not in eml and b"JVBERi0xLjQK" not in eml  # no PDF data, raw or base64


def test_cid_images_stay_embedded():  # AK-12
    raw = mails.with_cid_images()
    prep, eml, _ = archive(raw)
    assert [a.filename for a in prep.attachments] == ["foto.png"]
    msg = message_from_bytes(eml, policy=default)
    embedded = [p.get_filename() for p in msg.walk() if p.get_content_type() == "image/png" and p.get_content()]
    assert embedded == ["logo.png", "signatur.png"]  # foto.png only as reference header, without data
    assert mails.PNG + b"real" not in eml


def test_forwarded_mail_is_an_attachment():  # AK-13
    raw, inner = mails.with_forward()
    prep, _, _ = archive(raw)
    assert len(prep.attachments) == 1
    att = prep.attachments[0]
    assert att.mime_type == "message/rfc822" and att.filename.endswith(".eml")
    parsed = message_from_bytes(att.data, policy=default)
    orig = message_from_bytes(inner, policy=default)
    assert parsed["Message-ID"] == "<inner@example.invalid>" and parsed["Subject"] == orig["Subject"]
    assert parsed.get_content().strip() == orig.get_content().strip()
    assert att.data == inner  # byte for byte, CRLF line ends kept


def test_same_names_and_encoded_umlaut():  # AK-14
    prep = mime.prepare(mails.with_same_names())
    assert [a.filename for a in prep.attachments] == ["rechnung.pdf", "rechnung-2.pdf", "Übersicht März.pdf"]


def test_unnamed_and_calendar_attachments():  # EC-7, EC-9
    raw = mails.make("Einladung", attachments=[(None, b"x" * 10, "application", "octet-stream")])
    prep = mime.prepare(raw)
    assert [a.filename for a in prep.attachments] == ["anhang-1.bin"]
    from email.message import EmailMessage
    m = EmailMessage()
    m["Subject"], m["From"], m["Message-ID"] = "Termin", "a@example.invalid", "<cal@example.invalid>"
    m.set_content("Einladung")
    m.add_alternative("BEGIN:VCALENDAR\nEND:VCALENDAR\n", subtype="calendar")
    prep = mime.prepare(m.as_bytes())
    assert [(a.filename, a.mime_type) for a in prep.attachments] == [("anhang-1.ics", "text/calendar")]


def test_bad_characters_in_file_names():
    raw = mails.make("x", attachments=[("../../etc/pass:wd?.pdf", b"1", "application", "pdf")])
    name = mime.prepare(raw).attachments[0].filename
    assert "/" not in name and ":" not in name and "?" not in name and not name.startswith(".")


def test_broken_mime_is_archived_unchanged():  # AK-42
    prep = mime.prepare(mails.BROKEN)
    assert prep.broken and "MIME" in prep.broken
    assert prep.archived_eml("x.attachments", mails.BROKEN) == mails.BROKEN
    assert prep.hash.startswith("mid:")


def test_markdown_text_and_frontmatter():  # AK-17, AK-18, AK-21
    raw = mails.with_pdfs()
    _, eml, entry = archive(raw)
    fields, content = mailmd.build(eml, entry, "/mnt/nas/ai/mail", TZ)
    assert fields["title"] == "Ihre Rechnungen"
    assert fields["from"] == {"name": "Anna Beispiel", "address": "anna@example.invalid"}
    assert fields["to"] == [{"name": "Ben Beispiel", "address": "ben@example.invalid"}] and fields["cc"] == []
    assert "bcc" not in fields
    assert fields["message_id"] == "<pdf@example.invalid>" and fields["references"] == []
    assert fields["archive"] == "/mnt/nas/ai/mail/k/2026/11/abcdefghijkl.eml"
    assert fields["attachments"][0] == {"filename": "rechnung-a.pdf", "mime_type": "application/pdf",
                                        "size": len(mails.PDF),
                                        "path": "/mnt/nas/ai/mail/k/2026/11/abcdefghijkl.attachments/rechnung-a.pdf"}
    assert fields["date"] == "2026-11-05T10:00:00+01:00"
    assert content.startswith("**Von:** Anna Beispiel <anna@example.invalid>")
    assert "**Datum:** 05.11.2026 10:00" in content and mails.DE_TEXT in content
    assert "## Anhänge" in content
    assert "[rechnung-a.pdf](</mnt/nas/ai/mail/k/2026/11/abcdefghijkl.attachments/rechnung-a.pdf>)" in content


def test_no_attachment_section_without_attachments():  # AK-21
    raw = mails.make(cc="Carla <c@example.invalid>", bcc="d@example.invalid",
                     extra_headers={"In-Reply-To": "<a@x>", "References": "<z@x> <a@x>"})
    fields, content = mailmd.build(raw, {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert "Anhänge" not in content and fields["attachments"] == []
    assert fields["bcc"] == [{"name": None, "address": "d@example.invalid"}]
    assert fields["in_reply_to"] == "<a@x>" and fields["references"] == ["<z@x>", "<a@x>"]
    assert "**Cc:** Carla <c@example.invalid>" in content


def test_html_only_to_markdown():  # AK-19
    html = ("<html><head><style>p{color:red}</style><script>alert('x')</script></head><body>"
            "<p>Hallo <a href='https://example.invalid/angebot'>zum Angebot</a></p>"
            "<table><tr><th>Artikel</th><th>Preis</th></tr><tr><td>Tee</td><td>3 €</td></tr></table>"
            "<img src='https://example.invalid/bild.jpg' alt='Bild'><img src='https://t.example.invalid/p.gif' width=1 height=1>"
            "</body></html>")
    raw = mails.make("HTML", body=None, html=html)
    _, content = mailmd.build(raw, {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert "[zum Angebot](https://example.invalid/angebot)" in content
    assert "| Artikel | Preis |" in content and "| Tee | 3 € |" in content
    for bad in ("color:red", "alert(", "bild.jpg", "p.gif", "<img", "<script", "<style"):
        assert bad not in content


def test_long_text_with_quotes_is_complete():  # AK-20
    quoted = "\n".join(f"> Zeile {i} des alten Verlaufs" for i in range(2000))
    body = ("Neuer Text " * 3000) + "\n\n" + quoted + "\nENDE"
    raw = mails.make("Lang", body=body)
    _, content = mailmd.build(raw, {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert len(body) > 50000
    assert "> Zeile 1999 des alten Verlaufs\nENDE" in content and "> Zeile 0 des alten Verlaufs" in content


def test_encodings():  # AK-22
    f, c = mailmd.build(mails.LATIN1, {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert f["title"] == "Grüße aus Köln" and f["from"]["name"] == "Jürgen Müller"
    assert "Schöne Grüße aus Köln" in c
    f, c = mailmd.build(mails.WRONG_CHARSET, {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert "Grüße über alles" in c
    f, c = mailmd.build(mails.UNKNOWN_CHARSET, {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert "Grüße" in c
    raw = mails.make("Ärger mit Öl", sender="Jörg Ü <j@example.invalid>")
    f, _ = mailmd.build(raw, {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert f["title"] == "Ärger mit Öl" and f["from"]["name"] == "Jörg Ü"


def test_no_subject():  # AK-23
    f, _ = mailmd.build(mails.make(subject=None), {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert f["title"] == "(ohne Betreff)"


def test_yaml_breaking_subject_stays_valid():  # AK-24
    subject = 'Re: "Angebot": 50 % --- jetzt: [sofort] # wichtig'
    f, _ = mailmd.build(mails.make(subject), {"eml_path": "k/x.eml", "attachments": []}, "/m", TZ)
    assert f["title"] == subject
    assert yaml.safe_load(yaml.safe_dump(f, allow_unicode=True))["title"] == subject


def test_language():  # AK-25
    assert mailmd.detect_language(mails.DE_TEXT) == "de"
    assert mailmd.detect_language(mails.EN_TEXT) == "en"
    assert mailmd.detect_language("Danke!") is None


def test_encrypted_mail_is_marked():  # EC-8
    raw = (b"From: a@example.invalid\r\nSubject: Geheim\r\nMessage-ID: <enc@example.invalid>\r\nMIME-Version: 1.0\r\n"
           b"Content-Type: application/pkcs7-mime; smime-type=enveloped-data; name=smime.p7m\r\n"
           b"Content-Disposition: attachment; filename=smime.p7m\r\nContent-Transfer-Encoding: base64\r\n\r\nAAAA\r\n")
    _, eml, entry = archive(raw)
    _, content = mailmd.build(eml, entry, "/m", TZ)
    assert "verschlüsselt" in content
