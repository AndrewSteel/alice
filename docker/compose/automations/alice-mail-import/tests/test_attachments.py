"""Integration: mail attachments as sources (PROJ-124) — fake IMAP → archive → extract → attachment loop,
against the real register code, the throwaway PostgreSQL and a temporary git repo."""
import asyncio
import hashlib
import logging
import os
import posixpath
from datetime import datetime, timezone

import pytest

from app.attachments import AttachmentWorker, summary_of
from app.registry import RegistryUnavailable

from . import mails
from .conftest import IMAP_LOGIN, NOV1, git

JAN = "Thu, 15 Jan 2026 10:00:00 +0100"
JPG_5MB = b"\xff\xd8\xff\xe0" + os.urandom(5 * 1024 * 1024)
PNG_3KB = b"\x89PNG\r\n\x1a\n" + os.urandom(3 * 1024)


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _mail(i, attachments, **kw):
    return mails.make(f"Mail {i}", msgid=f"<att-{i}@example.invalid>", attachments=attachments, **kw)


def pdf(name, data=mails.PDF):
    return (name, data, "application", "pdf")


async def _import(env, *raws, classify=False, mb=None):
    for raw in raws:
        env.imap.add("INBOX", raw, NOV1)
    mb = mb or await env.add_mailbox()
    await env.sync(mb)
    await env.extract_all()
    if classify:
        await env.classify_all()
    return mb


async def _mail_id(env, title):
    return next(s["id"] for s in await env.sources() if s["title"] == title)


async def _children(env, kind=None):
    async with env.pool.acquire() as con:
        return [dict(r) for r in await con.fetch(
            "SELECT s.id, s.kind, s.title, s.path, s.deleted, s.hash FROM alice.sources s WHERE s.kind <> 'email' "
            "AND ($1::text IS NULL OR s.kind = $1) ORDER BY s.title, s.id", kind)]


def _read(env, rel):
    import registry_app.markdown as md
    return md.parse((env.repo / rel).read_text())


async def _src(env, sid):
    return await env.reg.get_source(sid)


# ---------------------------------------------------------------- registration
async def test_two_pdfs_become_sources_with_references(env):  # AK-1, AK-2, AK-6, AK-18, AK-19, AK-22
    raw = _mail(1, [pdf("rechnung-a.pdf"), pdf("rechnung-b.pdf", mails.PDF2), ("daten.zip", b"PK\x03\x04zip",
                                                                                 "application", "zip")])
    await _import(env, raw, classify=True)
    mid = await _mail_id(env, "Mail 1")
    assert (await env.stages(mid))["classify"] == "done"
    mail_path = (await _src(env, mid))["path"]
    commits = env.commits()
    assert await env.attachments.step() >= 1
    kids = await _children(env)
    assert [k["title"] for k in kids] == ["rechnung-a.pdf", "rechnung-b.pdf"]
    for k in kids:
        assert k["kind"] == "document" and k["path"].startswith("documents/2026/11/")
        src = await _src(env, k["id"])
        assert src["parents"] == [mid]
        assert src["stages"]["detect"]["state"] == "done" and src["stages"]["extract"]["state"] == "pending"
        # AK-2: the only location is the archive file; nothing copied
        assert [l["path"] for l in src["locations"]] == [
            str(env.archive / f"{posixpath.dirname(next(f for f in env.files() if f.endswith(k['title'])))}/{k['title']}")]
        assert src["locations"][0]["path"].startswith(str(env.archive)) and ".attachments/" in src["locations"][0]["path"]
        fm, content = _read(env, k["path"])
        assert fm["title"] == k["title"] and fm["parents"] == [mid]
        assert (env.repo / k["path"]).read_text().count(f"# {k['title']}") == 1  # AK-6: heading
    assert sum(1 for f in env.files() if f.endswith(".pdf")) == 2
    # AK-18/19: ids and links in the mail
    fm, content = _read(env, mail_path)
    by_name = {a["filename"]: a for a in fm["attachments"]}
    ids = {k["title"]: k["id"] for k in kids}
    assert by_name["rechnung-a.pdf"]["id"] == ids["rechnung-a.pdf"]
    assert by_name["rechnung-b.pdf"]["id"] == ids["rechnung-b.pdf"]
    assert "id" not in by_name["daten.zip"]
    section = content.split("## Anhänge", 1)[1]
    for k in kids:
        line = next(l for l in section.splitlines() if l.startswith(f"- [{k['title']}]"))
        rel = line.split("→ [Markdown](<", 1)[1].split(">)", 1)[0]
        target = posixpath.normpath(posixpath.join(posixpath.dirname(mail_path), rel))
        assert target == k["path"] and (env.repo / target).is_file()
    zip_line = next(l for l in section.splitlines() if "daten.zip" in l)
    assert "Markdown" not in zip_line and str(env.archive) in zip_line
    # AK-22: classify of the mail unchanged, own commit of the pipeline author
    assert (await env.stages(mid))["classify"] == "done"
    log = git(env.repo, "log", "--format=%an|%s", "--", mail_path).splitlines()
    assert log[0].startswith(f"Alice ETL|attachments: {mid}")
    assert env.commits() == commits + 3  # two sources + one mail update


async def test_kinds_sizes_and_stages(env):  # AK-3, AK-11, AK-29
    raw = _mail(2, [pdf("brief.pdf"), ("Foto.JPG", JPG_5MB, "image", "jpeg"), ("klein.png", PNG_3KB, "image", "png"),
                    ("ton.mp3", b"ID3" + os.urandom(500), "audio", "mpeg"),
                    ("film.mp4", b"\x00\x00\x00\x18ftyp" + os.urandom(500), "video", "mp4")])
    await _import(env, raw)
    await env.attachments.step()
    kids = {k["title"]: k for k in await _children(env)}
    assert {t: k["kind"] for t, k in kids.items()} == {"brief.pdf": "document", "Foto.JPG": "image",
                                                      "klein.png": "image", "ton.mp3": "audio", "film.mp4": "video"}
    folders = {"document": "documents/", "image": "images/", "audio": "audio/", "video": "video/"}
    for k in kids.values():
        assert k["path"].startswith(folders[k["kind"]] + "2026/11/")
    for t in ("ton.mp3", "film.mp4"):
        st = await env.stages(kids[t]["id"])
        assert st["detect"] == "done" and all(v == "skipped" for s, v in st.items() if s != "detect")
    st = await env.stages(kids["Foto.JPG"]["id"])
    assert st["detect"] == "done" and st["extract"] == "pending"  # PROJ-125 processes images
    assert kids["Foto.JPG"]["hash"] == _sha(JPG_5MB)


async def test_added_extension_without_code_change(env):  # AK-4
    raw = _mail(3, [("notiz.xyz", b"neues format", "application", "octet-stream")])
    await _import(env, raw)
    await env.attachments.step()
    assert await _children(env) == []
    env.detection.exts["xyz"] = "document"
    await env.attachments.step()
    kids = await _children(env)
    assert [k["title"] for k in kids] == ["notiz.xyz"] and kids[0]["kind"] == "document"


async def test_filed_by_mail_date(env):  # AK-5
    await _import(env, _mail(4, [pdf("alt.pdf")], date=JAN))
    await env.attachments.step()
    assert (await _children(env))[0]["path"].startswith("documents/2026/01/")


async def test_second_run_changes_nothing(env):  # AK-7
    await _import(env, _mail(5, [pdf("a.pdf"), pdf("b.pdf", mails.PDF2)]))
    await env.attachments.step()
    commits, files = env.commits(), sorted(p.read_text() for p in env.repo.rglob("*.md"))
    async with env.pool.acquire() as con:
        locs = await con.fetchval("SELECT count(*) FROM alice.source_locations")
        await con.execute("UPDATE alice.mail_attachment_mails SET processed_at = NULL")  # force a full re-run
    await env.attachments.step()
    await env.attachments.step()
    async with env.pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.source_locations") == locs
    assert env.commits() == commits and sorted(p.read_text() for p in env.repo.rglob("*.md")) == files
    assert len(await _children(env)) == 2


async def test_two_instances_register_once(env):  # AK-8
    await _import(env, _mail(6, [pdf("a.pdf"), pdf("b.pdf", mails.PDF2)]))
    other = AttachmentWorker(env.settings, env.pool, env.client, env.importer.archive, env.detection)
    await asyncio.gather(env.attachments.step(), other.step())
    await asyncio.gather(env.attachments.step(), other.step())
    kids = await _children(env)
    assert len(kids) == 2 and len({k["hash"] for k in kids}) == 2


async def test_new_mail_first_while_stock_runs(env):  # AK-9, AK-35, AK-36, AK-41 (restart)
    env.settings.attachment_batch_size = 10
    env.settings.batch_threshold = 5
    raws = [_mail(100 + i, [pdf(f"alt-{i}.pdf", mails.PDF + bytes([i]))]) for i in range(25)]
    mb = await _import(env, *raws)
    commits = env.commits()
    assert await env.attachments.step() >= 10
    assert len(await _children(env)) == 10
    assert env.commits() - commits <= 2  # batch commits (sources + mail references)
    # new mail arrives while the stock is not finished
    await _import(env, _mail(999, [pdf("neu.pdf", mails.PDF2)]), mb=mb)
    restarted = AttachmentWorker(env.settings, env.pool, env.client, env.importer.archive, env.detection)
    await restarted.step()  # after a restart: continues, the new mail comes first
    titles = {k["title"] for k in await _children(env)}
    assert "neu.pdf" in titles and len(titles) == 20
    while await restarted.step():
        pass
    kids = await _children(env)
    assert len(kids) == 26 and len({k["hash"] for k in kids}) == 26
    async with env.pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.mail_attachment_mails WHERE links_ok") == 26
    max_files = max(len([l for l in git(env.repo, "show", "--name-only", "--format=", c).splitlines() if l])
                    for c in git(env.repo, "rev-list", "HEAD").split())
    assert max_files <= 500


# ---------------------------------------------------------------- selection
async def test_cid_images_are_no_sources(env):  # AK-10
    await _import(env, mails.with_cid_images())
    await env.attachments.step()
    assert [k["title"] for k in await _children(env)] == ["foto.png"]


async def test_not_recognised_and_empty_are_counted(env):  # AK-12, AK-13, AK-34
    fwd, _inner = mails.with_forward()
    raw = _mail(7, [("a.zip", b"PK1", "application", "zip"), ("b.zip", b"PK2", "application", "zip"),
                    ("c.zip", b"PK3", "application", "zip"), ("termin.ics", b"BEGIN:VCALENDAR", "text", "calendar"),
                    ("zwei.ics", b"BEGIN:VCALENDAR2", "text", "calendar"), pdf("leer.pdf", b"")])
    await _import(env, raw, fwd)
    before = {f: (env.archive / f).read_bytes() for f in env.files()}
    await env.attachments.step()
    assert await _children(env) == []
    assert {f: (env.archive / f).read_bytes() for f in env.files()} == before  # archive untouched
    for title in ("Mail 7", "Fwd: Original"):
        fm, _ = env.doc(await _mail_id(env, title))
        assert all("id" not in a for a in fm["attachments"])
    runs = await env.attachments.runs()
    s = runs[0]["summary"]
    assert runs[0]["kind"] == "tick" and s["total"] == 7 and s["empty"] == 1
    assert s["by_extension"] == {"zip": 3, "ics": 2, "eml": 1, "pdf": 1}
    (box,) = s["by_mailbox"]
    assert box.startswith("privat-") and s["by_mailbox"][box]["zip"] == 3
    assert env.attachments.paused_reason == ""  # informative only, no warning


def test_summary_shape():
    from collections import Counter
    s = summary_of(Counter({("a", "zip"): 2, ("b", "zip"): 1, ("b", "ics"): 1}), 0)
    assert s == {"total": 4, "empty": 0, "by_extension": {"zip": 3, "ics": 1},
                 "by_mailbox": {"a": {"zip": 2}, "b": {"ics": 1, "zip": 1}}}


# ---------------------------------------------------------------- dedup
async def test_same_hash_as_dms_source(env):  # AK-14, EC-1
    dms = await env.reg.register(kind="document", hash=_sha(mails.PDF), title="rechnung.pdf",
                                 location={"path": "/mnt/nas/dms/rechnung.pdf"}, complete=True)
    tok = (await env.reg.claim("extract", 1, ["document"]))["items"][0]["token"]
    await env.reg.complete(dms["id"], "extract", tok)
    await _import(env, _mail(8, [pdf("scan0001.pdf")]))
    await env.attachments.step()
    kids = await _children(env)
    assert [k["id"] for k in kids] == [dms["id"]]
    src = await _src(env, dms["id"])
    mid = await _mail_id(env, "Mail 8")
    assert src["parents"] == [mid] and len(src["locations"]) == 2
    assert src["stages"]["extract"]["state"] == "done"
    fm, _ = env.doc(mid)
    assert fm["attachments"][0]["id"] == dms["id"]


async def test_same_attachment_in_two_mails(env):  # AK-15, EC-3
    await _import(env, _mail(9, [pdf("vertrag.pdf")]), _mail(10, [pdf("vertrag_v2.pdf")]))
    await env.attachments.step()
    (kid,) = await _children(env)
    src = await _src(env, kid["id"])
    m9, m10 = await _mail_id(env, "Mail 9"), await _mail_id(env, "Mail 10")
    assert sorted(src["parents"]) == sorted([m9, m10]) and len(src["locations"]) == 2
    for m in (m9, m10):
        assert env.doc(m)[0]["attachments"][0]["id"] == kid["id"]


async def test_same_content_twice_in_one_mail(env):  # AK-16
    await _import(env, _mail(11, [pdf("a.pdf"), pdf("b.pdf")]))
    await env.attachments.step()
    (kid,) = await _children(env)
    assert len((await _src(env, kid["id"]))["locations"]) == 2
    fm, _ = env.doc(await _mail_id(env, "Mail 11"))
    assert [a["id"] for a in fm["attachments"]] == [kid["id"], kid["id"]]


async def test_later_dms_copy_keeps_parents(env):  # AK-17, AK-33
    await _import(env, _mail(12, [pdf("a.pdf")]))
    await env.attachments.step()
    (kid,) = await _children(env)
    mid = await _mail_id(env, "Mail 12")
    r = await env.reg.register(kind="document", hash=_sha(mails.PDF), title="a.pdf",
                               location={"path": "/mnt/nas/dms/a.pdf"}, complete=True)  # what PROJ-116 does
    assert r["id"] == kid["id"] and not r["created"]
    assert (await _src(env, kid["id"]))["parents"] == [mid]
    # the DMS copy disappears (PROJ-116 nightly): the archive path stays, the source stays active
    out = await env.reg.remove_location(kid["id"], {"path": "/mnt/nas/dms/a.pdf"})
    assert out["deleted"] is False and not (await _src(env, kid["id"]))["deleted"]


# ---------------------------------------------------------------- references
async def test_link_follows_renamed_markdown(env):  # AK-20, EC-5
    await _import(env, _mail(13, [pdf("scan0001.pdf")]))
    await env.attachments.step()
    (kid,) = await _children(env)
    await env.reg.write_document(kid["id"], stage="classify", fields={"title": "Stromrechnung Oktober"})
    new_path = (await _src(env, kid["id"]))["path"]
    assert "stromrechnung-oktober" in new_path
    await env.attachments.step()
    mid = await _mail_id(env, "Mail 13")
    fm, content = env.doc(mid)
    mail_path = (await _src(env, mid))["path"]
    rel = content.split("→ [Markdown](<", 1)[1].split(">)", 1)[0]
    assert posixpath.normpath(posixpath.join(posixpath.dirname(mail_path), rel)) == new_path
    assert fm["attachments"][0]["id"] == kid["id"]


async def test_manual_content_only_frontmatter(env):  # AK-21
    await _import(env, _mail(14, [pdf("a.pdf")]))
    mid = await _mail_id(env, "Mail 14")
    path = env.repo / (await _src(env, mid))["path"]
    path.write_text(path.read_text().replace("## Anhänge", "Von Hand ergänzt.\n\n## Anhänge"))
    await env.reg.scan()
    fm, content = env.doc(mid)
    assert "content" in fm["manual"]
    await env.attachments.step()
    (kid,) = await _children(env)
    fm2, content2 = env.doc(mid)
    assert content2 == content and "Markdown" not in content2
    assert fm2["attachments"][0]["id"] == kid["id"]


async def test_manual_attachments_field_retried_with_event(env):  # spec „Fehler“: manual conflict
    await _import(env, _mail(15, [pdf("a.pdf")]))
    mid = await _mail_id(env, "Mail 15")
    path = env.repo / (await _src(env, mid))["path"]
    path.write_text(path.read_text().replace("mime_type: application/pdf", "mime_type: application/x-pdf"))
    await env.reg.scan()
    await env.attachments.step()
    assert len(await _children(env)) == 1  # registration stays
    async with env.pool.acquire() as con:
        row = await con.fetchrow("SELECT links_ok, link_attempts, link_retry_at FROM alice.mail_attachment_mails "
                                 "WHERE mail_id = $1", mid)
    assert not row["links_ok"] and row["link_attempts"] == 1 and row["link_retry_at"] is not None
    events = [e["event"] for e in (await _src(env, mid))["events"]]
    assert "attachment_links_failed" in events


# ---------------------------------------------------------------- pipeline
async def test_attachment_document_goes_to_extract(env):  # AK-23, AK-28 (hand-over to PROJ-117)
    await _import(env, _mail(16, [pdf("a.pdf")]))
    await env.attachments.step()
    (kid,) = await _children(env)
    items = (await env.reg.claim("extract", 5, ["document"]))["items"]
    assert [i["source_id"] for i in items] == [kid["id"]]
    await env.reg.fail(kid["id"], "extract", items[0]["token"], "Passwortgeschützt", True)
    assert (await env.stages(kid["id"]))["extract"] == "failed_permanent"
    assert not (await _src(env, kid["id"]))["deleted"]
    mid = await _mail_id(env, "Mail 16")
    assert (await env.stages(mid))["extract"] == "done"


# ---------------------------------------------------------------- deleting
async def test_mail_deleted_attachment_stays(env):  # AK-30
    await _import(env, _mail(17, [pdf("a.pdf")]))
    await env.attachments.step()
    (kid,) = await _children(env)
    mid = await _mail_id(env, "Mail 17")
    archive_file = next(f for f in env.files() if f.endswith("a.pdf"))
    data = (env.archive / archive_file).read_bytes()
    for loc in await env.locations(mid):
        await env.reg.remove_location(mid, {k: loc[k] for k in ("mailbox", "folder", "message_id")})
    assert (await _src(env, mid))["deleted"]
    await env.attachments.step()  # references follow the moved mail markdown
    src = await _src(env, kid["id"])
    assert not src["deleted"] and src["parents"] == [mid] and src["path"] == kid["path"]
    assert (env.archive / archive_file).read_bytes() == data
    mail_path = (await _src(env, mid))["path"]
    assert mail_path.startswith("deleted/")
    _, content = env.doc(mid)
    rel = content.split("→ [Markdown](<", 1)[1].split(">)", 1)[0]
    assert (env.repo / posixpath.normpath(posixpath.join(posixpath.dirname(mail_path), rel))).is_file()


async def test_deleted_mail_still_registered(env):  # AK-31
    await _import(env, _mail(18, [pdf("a.pdf")]))
    mid = await _mail_id(env, "Mail 18")
    for loc in await env.locations(mid):
        await env.reg.remove_location(mid, {k: loc[k] for k in ("mailbox", "folder", "message_id")})
    await env.attachments.step()
    (kid,) = await _children(env)
    assert (await _src(env, kid["id"]))["parents"] == [mid]


# ---------------------------------------------------------------- reconciliation (level 7)
async def test_level7_reports_and_repairs(env):  # AK-32, AK-38, EC-4
    await _import(env, _mail(19, [pdf("a.pdf"), pdf("b.pdf", mails.PDF2)]), _mail(20, [pdf("c.pdf", mails.PDF + b"c")]),
                  _mail(21, [pdf("d.pdf", mails.PDF + b"d")]))
    await env.attachments.step()
    m19, m20, m21 = [await _mail_id(env, f"Mail {i}") for i in (19, 20, 21)]
    async with env.pool.acquire() as con:
        await con.execute("DELETE FROM alice.mail_attachments WHERE mail_id = $1", m19)  # registration "lost"
    c_file = next(f for f in env.files() if f.endswith("c.pdf"))
    os.remove(env.archive / c_file)
    d_file = env.archive / next(f for f in env.files() if f.endswith("d.pdf"))
    d_file.write_bytes(b"von Hand ersetzt")
    out = await env.attachments.reconcile_check()
    gaps = {(g["gap"], g["mail_id"]) for g in out["missing"]}
    assert ("attachment_unregistered", m19) in gaps
    assert ("attachment_file_missing", m20) in gaps
    assert ("attachment_changed", m21) in gaps
    assert all(g["repair"] is None for g in out["missing"] if g["gap"] != "attachment_unregistered")
    kid_c = next(k for k in await _children(env) if k["title"] == "c.pdf")
    assert not (await _src(env, kid_c["id"]))["deleted"]  # AK-32: only reported
    res = await env.attachments.reconcile_repair([m19])
    assert res == [{"type": "attachment_register", "source_id": m19, "repaired": True, "detail": "Anhänge registriert"}]
    out = await env.attachments.reconcile_check()
    assert not any(g["mail_id"] == m19 for g in out["missing"])
    assert (await env.attachments.runs(kind="reconcile"))[0]["kind"] == "reconcile"


async def test_rebuild_keeps_ids(env):  # AK-37
    await _import(env, _mail(22, [pdf("a.pdf"), pdf("b.pdf", mails.PDF2)]))
    await env.attachments.step()
    before = {k["title"]: k["id"] for k in await _children(env)}
    mid = await _mail_id(env, "Mail 22")
    async with env.pool.acquire() as con:
        run = await con.fetchval("INSERT INTO alice.rebuild_runs (start_stage, kind, state, started_by) "
                                 "VALUES ('extract', 'email', 'running', 'test') RETURNING id")
    await env.reg.release_rebuild(run, [{"id": mid, "stages": ["extract"]}])
    await env.extract_all()
    fm, content = env.doc(mid)
    assert sorted(a["id"] for a in fm["attachments"]) == sorted(before.values())  # kept by the new extract
    assert content.count("→ [Markdown]") == 2
    await env.attachments.step()
    assert {k["title"]: k["id"] for k in await _children(env)} == before


# ---------------------------------------------------------------- errors and operation
async def test_archive_unavailable_pauses(env):  # AK-39
    await _import(env, _mail(23, [pdf("a.pdf")]))
    moved = env.archive.with_name("mail-weg")
    env.archive.rename(moved)
    commits = env.commits()
    assert await env.attachments.step() == 0
    assert "Mail-Archiv" in env.attachments.paused_reason
    assert await _children(env) == [] and env.commits() == commits
    moved.rename(env.archive)
    await env.attachments.step()
    assert len(await _children(env)) == 1 and env.attachments.paused_reason == ""


async def test_unreadable_file_pauses_only_its_mail(env):  # AK-39 (single file)
    if os.geteuid() == 0:
        pytest.skip("root can read everything")
    await _import(env, _mail(24, [pdf("a.pdf"), pdf("b.pdf", mails.PDF2)]), _mail(25, [pdf("c.pdf", mails.PDF + b"c")]))
    bad = env.archive / next(f for f in env.files() if f.endswith("b.pdf"))
    bad.chmod(0)
    try:
        await env.attachments.step()
        assert [k["title"] for k in await _children(env)] == ["c.pdf"]  # a.pdf of the same mail waits too
        async with env.pool.acquire() as con:
            assert await con.fetchval("SELECT count(*) FROM alice.source_events WHERE level = 'error'") == 0
            await con.execute("UPDATE alice.mail_attachment_mails SET next_try_at = NOW() - INTERVAL '1 second'")
    finally:
        bad.chmod(0o644)
    await env.attachments.step()
    assert len(await _children(env)) == 3


async def test_register_unavailable_pauses_and_catches_up(env, monkeypatch):  # AK-40, AK-41
    await _import(env, _mail(26, [pdf("a.pdf"), pdf("b.pdf", mails.PDF2)]))

    async def down():
        return False, "Register nicht erreichbar: ConnectError"
    real = env.client.available
    monkeypatch.setattr(env.client, "available", down)
    assert await env.attachments.step() == 0 and await _children(env) == []
    monkeypatch.setattr(env.client, "available", real)
    # register goes away in the middle: after the registrations, before the mail references
    real_write = env.client.write_links

    async def broken(*a, **kw):
        raise RegistryUnavailable("Register nicht erreichbar: ReadTimeout")
    monkeypatch.setattr(env.client, "write_links", broken)
    await env.attachments.step()
    assert len(await _children(env)) == 2
    monkeypatch.setattr(env.client, "write_links", real_write)
    await env.attachments.step()
    kids = await _children(env)
    assert len(kids) == 2
    fm, _ = env.doc(await _mail_id(env, "Mail 26"))
    assert sorted(a["id"] for a in fm["attachments"]) == sorted(k["id"] for k in kids)


async def test_detection_list_unavailable_pauses(env):
    await _import(env, _mail(27, [pdf("a.pdf")]))
    env.detection.down = True
    assert await env.attachments.step() == 0 and "Erkennungsliste" in env.attachments.paused_reason
    env.detection.down = False
    await env.attachments.step()
    assert len(await _children(env)) == 1


async def test_logs_without_mail_text_or_password(env, caplog):  # AK-42
    caplog.set_level(logging.DEBUG)
    await _import(env, _mail(28, [pdf("a.pdf"), ("x.zip", b"PK", "application", "zip")]))
    await env.attachments.step()
    await env.attachments.reconcile_check()
    text = caplog.text
    assert mails.DE_TEXT[:40] not in text and IMAP_LOGIN not in text
