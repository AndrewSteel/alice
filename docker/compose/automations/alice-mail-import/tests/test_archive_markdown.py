"""Integration: mail archive, mail markdown through the register, classify (AK-10–32, AK-42, AK-50)."""
import json
import os
from email import message_from_bytes
from email.policy import default

import yaml

from . import mails
from .conftest import NOV1, git


async def _import(env, raw, folder="INBOX"):
    env.imap.add(folder, raw, NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    await env.extract_all()
    return mb, (await env.sources())[-1]


async def test_archive_layout_and_markdown(env):  # AK-10, AK-11, AK-17, AK-21
    mb, src = await _import(env, mails.with_pdfs())
    sid = src["id"]
    key = (await env.locations(sid))[0]["mailbox"]
    files = env.files()
    assert files == [f"{key}/2026/11/{sid}.attachments/rechnung-a.pdf", f"{key}/2026/11/{sid}.attachments/rechnung-b.pdf",
                     f"{key}/2026/11/{sid}.eml"]
    att = env.archive / f"{key}/2026/11/{sid}.attachments"
    assert (att / "rechnung-a.pdf").read_bytes() == mails.PDF and (att / "rechnung-b.pdf").read_bytes() == mails.PDF2
    msg = message_from_bytes((env.archive / f"{key}/2026/11/{sid}.eml").read_bytes(), policy=default)
    assert msg["Subject"] == "Ihre Rechnungen" and msg.get_body(("html",)) is not None
    assert sorted(p.get_param("name") for p in msg.walk() if p.get_content_type() == "message/external-body") == [
        f"{sid}.attachments/rechnung-a.pdf", f"{sid}.attachments/rechnung-b.pdf"]
    fm, content = env.doc(sid)
    for f in ("id", "schema", "kind", "title", "locations", "parents", "hash", "size", "modified", "captured",
              "language", "type", "manual", "from", "to", "cc", "date", "message_id", "in_reply_to", "references",
              "archive", "attachments", "category", "summary"):
        assert f in fm, f
    assert fm["kind"] == "email" and fm["category"] is None and fm["summary"] is None
    assert "bcc" not in fm
    assert not {"state", "attempts", "error", "stages"} & set(fm)
    assert fm["archive"] == f"{env.archive}/{key}/2026/11/{sid}.eml"
    assert [a["filename"] for a in fm["attachments"]] == ["rechnung-a.pdf", "rechnung-b.pdf"]
    assert fm["locations"] == [{"mailbox": key, "folder": "INBOX", "uid": 1, "message_id": "<pdf@example.invalid>"}]
    assert "## Anhänge" in content and f"({env.archive}/{key}/2026/11/{sid}.attachments/rechnung-a.pdf)" in content.replace("<", "").replace(">", "")
    log = git(env.repo, "log", "--format=%s").splitlines()
    assert log[0] == f"extract: {sid} Ihre Rechnungen" and log[1] == f"detect: {sid} Ihre Rechnungen"


async def test_archive_is_never_overwritten(env):  # AK-16
    mb, src = await _import(env, mails.with_pdfs())
    sid = src["id"]
    eml = next(p for p in env.archive.rglob("*.eml"))
    pdf = next(p for p in env.archive.rglob("rechnung-a.pdf"))
    eml.write_bytes(b"marker")
    pdf.write_bytes(b"marker")
    env.imap.add("Gesendet", mails.with_pdfs(), NOV1)  # same mail again → known source
    await env.sync(mb)
    assert eml.read_bytes() == b"marker" and pdf.read_bytes() == b"marker"
    await env.reg.retry(sid, "extract")  # markdown built again from the archive
    await env.extract_all()
    assert eml.read_bytes() == b"marker" and pdf.read_bytes() == b"marker"


async def test_big_attachment(env):  # AK-15
    big = os.urandom(101 * 1024 * 1024)
    raw = mails.make("Großer Anhang", msgid="<big@example.invalid>",
                     attachments=[("video.bin", big, "application", "octet-stream")])
    mb, src = await _import(env, raw)
    path = next(env.archive.rglob("video.bin"))
    assert path.stat().st_size == len(big) and path.read_bytes() == big
    assert next(env.archive.rglob("*.eml")).stat().st_size < 100_000


async def test_cid_and_forward_through_import(env):  # AK-12, AK-13
    env.imap.add("INBOX", mails.with_cid_images(), NOV1)
    fwd, inner = mails.with_forward()
    env.imap.add("INBOX", fwd, NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    await env.extract_all()
    by_title = {s["title"]: s["id"] for s in await env.sources()}
    fm, _ = env.doc(by_title["Newsletter mit Logo"])
    assert [a["filename"] for a in fm["attachments"]] == ["foto.png"]
    fm, _ = env.doc(by_title["Fwd: Original"])
    assert len(fm["attachments"]) == 1 and fm["attachments"][0]["mime_type"] == "message/rfc822"
    saved = message_from_bytes(open(fm["attachments"][0]["path"], "rb").read(), policy=default)
    assert saved["Message-ID"] == "<inner@example.invalid>"


async def test_markdown_special_cases(env):  # AK-14, AK-22, AK-23, AK-24, AK-25
    env.imap.add("INBOX", mails.with_same_names(), NOV1)
    env.imap.add("INBOX", mails.LATIN1, NOV1)
    env.imap.add("INBOX", mails.WRONG_CHARSET, NOV1)
    env.imap.add("INBOX", mails.make(subject=None, msgid="<nosub@example.invalid>", body=mails.EN_TEXT), NOV1)
    env.imap.add("INBOX", mails.make('Re: "Angebot": 50 % --- jetzt', msgid="<yaml@example.invalid>", body="Kurz."), NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    await env.extract_all()
    docs = {}
    for s in await env.sources():
        fm, content = env.doc(s["id"])
        docs[fm["title"]] = (fm, content, s)
    assert [a["filename"] for a in docs["Drei Anhänge"][0]["attachments"]] == [
        "rechnung.pdf", "rechnung-2.pdf", "Übersicht März.pdf"]
    assert "Schöne Grüße aus Köln" in docs["Grüße aus Köln"][1]
    assert docs["Grüße aus Köln"][0]["from"]["name"] == "Jürgen Müller"
    assert "Grüße über alles" in docs["Falsch deklariert"][1]
    nosub = docs["(ohne Betreff)"]
    assert nosub[2]["path"].endswith("-ohne-betreff.md") and nosub[0]["language"] == "en"
    assert docs['Re: "Angebot": 50 % --- jetzt'][0]["language"] is None
    assert docs["Drei Anhänge"][0]["language"] == "de"


async def test_manual_fields_survive(env):  # AK-26, AK-32 (via the register's manual protection)
    mb, src = await _import(env, mails.make("Original-Betreff", msgid="<man@example.invalid>"))
    sid = src["id"]
    path = next(env.repo.rglob(f"{sid}-*.md"))
    text = path.read_text().replace("title: Original-Betreff", "title: Von Hand")
    text = text.replace(mails.DE_TEXT[:40], "HANDTEXT " + mails.DE_TEXT[:40])
    path.write_text(text)
    git(env.repo, "-c", "user.name=Mensch", "-c", "user.email=m@example.invalid", "commit", "-qam", "edit")
    await env.reg.scan()
    fm, _ = env.doc(sid)
    assert set(fm["manual"]) >= {"title", "content"}
    await env.reg.retry(sid, "extract")
    await env.extract_all()
    fm, content = env.doc(sid)
    assert fm["title"] == "Von Hand" and "HANDTEXT" in content


async def test_broken_mime(env):  # AK-42
    env.imap.add("INBOX", mails.BROKEN, NOV1)
    env.imap.add("INBOX", mails.make("Danach", msgid="<after@example.invalid>"), NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    await env.extract_all()
    srcs = {s["title"]: s for s in await env.sources()}
    assert set(srcs) == {"Kaputt", "Danach"}
    broken = srcs["Kaputt"]["id"]
    eml = next(p for p in env.archive.rglob(f"{broken}.eml"))
    assert eml.read_bytes() == mails.BROKEN
    st = (await env.reg.get_source(broken))["stages"]["extract"]
    assert st["state"] == "failed_permanent" and "MIME" in st["last_error"]
    assert (await env.stages(srcs["Danach"]["id"]))["extract"] == "done"


async def test_classify(env):  # AK-28, AK-29, AK-30
    mb, src = await _import(env, mails.make("Rabatt!", msgid="<promo@example.invalid>", body=mails.EN_TEXT * 5))
    sid = src["id"]
    await env.classify_all()
    fm, _ = env.doc(sid)
    assert fm["category"] == "promotion" and fm["summary"].startswith("Ein Angebot")
    assert (await env.stages(sid))["classify"] == "done"
    assert git(env.repo, "log", "-1", "--format=%s").strip() == f"classify: {sid} Rabatt!"
    req = env.gateway.requests[0]
    assert req["auth"] == "Bearer test-background-key"  # background key = background priority (PROJ-111)
    assert req["body"]["chat_template_kwargs"] == {"enable_thinking": False}
    user = req["body"]["messages"][1]["content"]
    assert "Betreff: Rabatt!" in user and "anna@example.invalid" in user
    assert len(user.split("Text (Anfang):\n", 1)[1]) == 300  # configured length
    assert "Deutsch" in req["body"]["messages"][0]["content"]


async def test_classify_errors(env):  # AK-31
    mb, src = await _import(env, mails.make("Unklar", msgid="<bad@example.invalid>"))
    sid = src["id"]
    before = env.doc(sid)
    env.gateway.answers.append({"category": "Rechnung", "summary": "x"})
    await env.classify.step()
    st = (await env.reg.get_source(sid))["stages"]["classify"]
    assert st["state"] == "failed" and "Unbekannte Kategorie" in st["last_error"] and st["next_retry_at"]
    assert env.doc(sid) == before
    async with env.pool.acquire() as con:
        await con.execute("UPDATE alice.source_stages SET next_retry_at = NOW() WHERE source_id = $1", sid)
    env.gateway.down = True
    await env.classify.step()
    st = (await env.reg.get_source(sid))["stages"]["classify"]
    assert st["state"] == "failed" and "nicht erreichbar" in st["last_error"] and st["attempts"] == 2
    assert env.doc(sid) == before


async def test_category_in_manual(env):  # AK-32, EC-11
    mb, src = await _import(env, mails.make("Wichtig?", msgid="<cat@example.invalid>"))
    sid = src["id"]
    await env.classify_all()
    path = next(env.repo.rglob(f"{sid}-*.md"))
    path.write_text(path.read_text().replace("category: promotion", "category: important"))
    await env.reg.scan()
    env.gateway.answers.append({"category": "spam", "summary": "Neue Zusammenfassung der Mail."})
    await env.reg.retry(sid, "classify")
    await env.classify_all()
    fm, _ = env.doc(sid)
    assert fm["category"] == "important" and fm["summary"] == "Neue Zusammenfassung der Mail."


async def test_rebuild_from_archive_without_imap(env):  # AK-50
    mb, src = await _import(env, mails.with_pdfs())
    sid = src["id"]
    await env.classify_all()
    path = next(env.repo.rglob(f"{sid}-*.md"))
    path.write_text(path.read_text().replace("title: Ihre Rechnungen", "title: Meine Rechnungen"))
    await env.reg.scan()
    env.imap.close()  # mail server unreachable
    env.servers.remove(env.imap)
    out = await env.reg.release_rebuild(1, [{"id": sid, "stages": ["extract", "classify"]}])
    assert out["released"] == [sid]
    await env.extract_all()
    await env.classify_all()
    await env.reg.flush_due(force=True)
    fm, content = env.doc(sid)
    assert fm["title"] == "Meine Rechnungen" and "## Anhänge" in content and fm["category"] == "promotion"
    st = await env.stages(sid)
    assert st["extract"] == "done" and st["classify"] == "done"
    async with env.pool.acquire() as con:  # the rebuild flag is cleared when the work is done
        assert await con.fetchval("SELECT count(*) FROM alice.source_stages WHERE source_id = $1 "
                                  "AND rebuild_run IS NOT NULL AND state <> 'done'", sid) == 0
