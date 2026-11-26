"""Integration: nightly reconciliation (AK-33–39, EC-4), errors (AK-41–45), mass import (AK-46),
levels 5/6 (AK-51/52) and logs (AK-55)."""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from app.archive import TMP_PREFIX

from . import mails
from .conftest import IMAP_LOGIN, NOV1, git


def _mail(i, folder="INBOX"):
    return mails.make(f"Mail {i}", msgid=f"<{folder}-{i}@example.invalid>")


async def _setup(env, n=10):
    uids = [env.imap.add("INBOX", _mail(i), NOV1) for i in range(n)]
    mb = await env.add_mailbox()
    await env.sync(mb)
    await env.extract_all()
    return mb, uids


async def _by_title(env):
    return {s["title"]: s for s in await env.sources()}


async def test_deleted_on_server(env):  # AK-33
    mb, uids = await _setup(env)
    sid = (await _by_title(env))["Mail 0"]["id"]
    files = env.files()
    env.imap.remove("INBOX", uids[0])
    out = await env.importer.nightly()
    assert out["state"] == "done"
    removal = next(iter(out["mailboxes"].values()))["removal"]
    assert removal["removed"] == 1 and removal["deleted"] == 1 and not removal["blocked"]
    src = await env.reg.get_source(sid)
    assert src["deleted"] and src["path"].startswith("deleted/emails/2026/11/")
    fm, _ = env.doc(sid)
    assert fm["deleted"]
    assert env.files() == files  # archive unchanged


async def test_removed_from_one_folder_only(env):  # AK-34
    raw = mails.make("Selbst", msgid="<self@example.invalid>")
    u = env.imap.add("INBOX", raw, NOV1)
    for i in range(5):
        env.imap.add("INBOX", _mail(i), NOV1)
    env.imap.add("Gesendet", raw, NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    env.imap.remove("INBOX", u)
    await env.importer.nightly()
    src = (await _by_title(env))["Selbst"]
    assert not src["deleted"]
    locs = await env.locations(src["id"])
    assert [(l["folder"], l["present"]) for l in locs] == [("INBOX", False), ("Gesendet", True)]


async def test_restored_mail_is_reactivated(env):  # AK-35
    mb, uids = await _setup(env)
    sid = (await _by_title(env))["Mail 0"]["id"]
    mail = env.imap.remove("INBOX", uids[0])
    await env.importer.nightly()
    assert (await env.reg.get_source(sid))["deleted"]
    env.gateway.answers.append({"category": "spam", "summary": "x y z."})
    env.imap.add("INBOX", mail.raw, NOV1)  # restored (new UID)
    await env.sync(mb)
    src = await env.reg.get_source(sid)
    assert not src["deleted"] and src["path"].startswith("emails/2026/11/") and src["id"] == sid
    st = await env.stages(sid)
    assert st["detect"] == "done" and st["extract"] == "done"
    assert len(await env.sources()) == 10


async def test_mass_loss_is_blocked(env):  # AK-36
    mb, uids = await _setup(env)
    for u in uids[:3]:
        env.imap.remove("INBOX", u)
    out = await env.importer.nightly()
    removal = next(iter(out["mailboxes"].values()))["removal"]
    assert removal["blocked"] and removal["missing"] == 3 and "30 %" not in removal["reason"]
    assert not any(s["deleted"] for s in await env.sources())


async def test_unreachable_mailbox_removes_nothing(env):  # AK-37
    mb, uids = await _setup(env, 3)
    env.imap.reject_login = True
    for u in uids:
        env.imap.remove("INBOX", u)
    out = await env.importer.nightly()
    assert "error" in next(iter(out["mailboxes"].values()))
    assert not any(s["deleted"] for s in await env.sources())


async def test_empty_folder_list_removes_nothing(env):  # AK-37
    mb, uids = await _setup(env, 3)
    env.imap.folders.clear()
    out = await env.importer.nightly()
    assert next(iter(out["mailboxes"].values()))["removal"]["skipped"]
    assert not any(s["deleted"] for s in await env.sources())


async def test_deleted_mailbox(env):  # AK-38
    mb, uids = await _setup(env, 5)
    files = env.files()
    async with env.pool.acquire() as con:
        await con.execute("DELETE FROM alice.imap_mailboxes WHERE id = $1", mb["id"])
    out = await env.importer.nightly()
    assert list(out["deleted_mailboxes"].values()) == [{"removed": 5, "deleted": 5}]
    assert all(s["deleted"] for s in await env.sources())
    assert env.files() == files


async def test_missing_mails_are_fetched(env):  # AK-39
    mb, uids = await _setup(env, 3)
    sid = (await _by_title(env))["Mail 1"]["id"]
    async with env.pool.acquire() as con:  # after an outage: register lost the source
        await con.execute("DELETE FROM alice.sources WHERE id = $1", sid)
    await env.importer.nightly()
    assert "Mail 1" in await _by_title(env)


async def test_uidvalidity_change(env):  # EC-4
    mb, uids = await _setup(env, 5)
    before = {s["id"] for s in await env.sources()}
    env.imap.renumber("INBOX")
    out = await env.importer.nightly()
    removal = next(iter(out["mailboxes"].values()))["removal"]
    assert removal["removed"] == 0 and not removal["blocked"]
    srcs = await env.sources()
    assert {s["id"] for s in srcs} == before and not any(s["deleted"] for s in srcs)
    server_uids = {m.uid for m in env.imap.folders["INBOX"].mails}
    assert {l["uid"] for l in await env.locations() if l["present"]} == server_uids


async def test_nightly_schedule(env):
    env.settings.nightly_time = "02:30"
    now = datetime(2026, 11, 26, 3, 0, tzinfo=env.settings.tz)
    assert await env.importer.nightly_due(now)
    await env.importer.nightly()
    assert not await env.importer.nightly_due(datetime.now(timezone.utc))


# ================================================================ errors
async def test_login_rejected(env):  # AK-41
    env.imap.add("INBOX", _mail(1), NOV1)
    env.imap.reject_login = True
    mb = await env.add_mailbox()
    await env.sync(mb)
    row = await env.mailbox(mb["id"])
    assert row["status"] == "error" and "Anmeldung abgelehnt" in row["last_error"]
    assert await env.sources() == []
    async with env.pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.source_stages") == 0
    env.imap.reject_login = False
    await env.sync(mb)
    assert len(await env.sources()) == 1 and (await env.mailbox(mb["id"]))["status"] == "active"


async def test_server_unreachable(env):  # AK-41
    mb = await env.add_mailbox()
    port = env.imap.port
    env.imap.close()
    env.servers.remove(env.imap)
    await env.sync(mb)
    row = await env.mailbox(mb["id"])
    assert row["status"] == "error" and "nicht erreichbar" in row["last_error"] and str(port) not in row["last_error"]


async def test_connection_drop(env):  # AK-43
    for i in range(6):
        env.imap.add("INBOX", _mail(i), NOV1)
    env.imap.drop_after_fetches = 3
    mb = await env.add_mailbox()
    await env.sync(mb)
    assert len(await env.sources()) == 3
    assert (await env.mailbox(mb["id"]))["status"] == "error"
    env.imap.drop_after_fetches = None
    await env.sync(mb)
    assert len(await env.sources()) == 6
    assert len([f for f in env.files() if f.endswith(".eml")]) == 6
    assert not any(TMP_PREFIX in f for f in env.files())


async def test_archive_unavailable(env, caplog):  # AK-44
    env.imap.add("INBOX", _mail(1), NOV1)
    mb = await env.add_mailbox()
    os.rename(env.archive, str(env.archive) + ".away")
    with caplog.at_level(logging.WARNING):
        await env.importer.tick()
        await asyncio.gather(*env.importer.running.values())
    assert "Mail import paused" in caplog.text
    assert await env.sources() == [] and not env.importer.running
    async with env.pool.acquire() as con:
        assert await con.fetchval("SELECT count(*) FROM alice.source_locations") == 0
    os.rename(str(env.archive) + ".away", env.archive)
    await env.importer.tick()
    await asyncio.gather(*env.importer.running.values())
    assert len(await env.sources()) == 1


async def test_archive_not_writable_during_import(env):  # AK-44 (share read-only)
    env.imap.add("INBOX", mails.with_pdfs(), NOV1)
    mb = await env.add_mailbox()
    os.chmod(env.archive, 0o555)
    try:
        if os.access(env.archive, os.W_OK):
            return  # running as root: permissions are not enforced
        out = await env.sync(mb)
        assert "paused" in out and await env.sources() == []
    finally:
        os.chmod(env.archive, 0o755)


async def test_restart_leftovers(env):  # AK-45
    mb, uids = await _setup(env, 2)
    sid = (await _by_title(env))["Mail 0"]["id"]
    month = next(env.archive.rglob(f"{sid}.eml")).parent
    leftover = month / f"{TMP_PREFIX}deadbeef"
    leftover.write_bytes(b"half")
    old = datetime.now().timestamp() - 7200
    os.utime(leftover, (old, old))
    assert env.importer.archive.cleanup_tmp() == 1 and not leftover.exists()
    # crash between registration and archive: the .eml is missing; level 6 stores it again
    eml = next(env.archive.rglob(f"{sid}.eml"))
    eml.unlink()
    out = await env.importer.reconcile_check()
    gaps = out["archive"]["missing"]
    assert [(g["gap"], g["source_id"], g["on_server"]) for g in gaps] == [("eml_missing", sid, True)]
    res = await env.importer.reconcile_repair([{"type": "mail_rearchive", "source_id": sid}])
    assert res[0]["repaired"] and eml.exists()
    await env.reg.flush_due(force=True)
    assert git(env.repo, "status", "--porcelain").strip() == ""


async def test_reconcile_levels(env):  # AK-51, AK-52
    mb, uids = await _setup(env, 3)
    gone_sid = (await _by_title(env))["Mail 2"]["id"]
    env.imap.add("INBOX", _mail(7), NOV1)  # on the server, no source yet
    out = await env.importer.reconcile_check()
    assert [(m["folder"], m["uid"]) for m in out["imap"]["missing"]] == [("INBOX", 4)]
    # attachment missing and mail no longer on the server → only reported
    env.imap.add("INBOX", mails.with_pdfs(), NOV1)
    await env.sync(mb)
    pdf_sid = (await _by_title(env))["Ihre Rechnungen"]["id"]
    next(env.archive.rglob("rechnung-b.pdf")).unlink()
    next(env.archive.rglob(f"{gone_sid}.eml")).unlink()
    out = await env.importer.reconcile_check()
    assert out["imap"]["missing"] == []
    gaps = {(g["gap"], g["source_id"]): g for g in out["archive"]["missing"]}
    assert gaps[("attachment_missing", pdf_sid)]["on_server"] and gaps[("eml_missing", gone_sid)]["on_server"]
    res = await env.importer.reconcile_repair([{"type": "mail_rearchive", "source_id": pdf_sid}])
    assert res[0]["repaired"] and next(env.archive.rglob("rechnung-b.pdf")).read_bytes() == mails.PDF2
    env.imap.folders["INBOX"].mails = [m for m in env.imap.folders["INBOX"].mails if b"Mail 2" not in m.raw]
    res = await env.importer.reconcile_repair([{"type": "mail_rearchive", "source_id": gone_sid}])
    assert not res[0]["repaired"] and res[0]["detail"] == "Mail nicht mehr auf dem Server"


async def test_reconcile_repair_imports(env):  # AK-51
    mb, uids = await _setup(env, 2)
    u = env.imap.add("INBOX", _mail(5), NOV1)
    out = await env.importer.reconcile_check()
    items = [{"type": "mail_import", **m} for m in out["imap"]["missing"]]
    assert [i["uid"] for i in items] == [u]
    res = await env.importer.reconcile_repair(items)
    assert res[0]["repaired"] and "Mail 5" in await _by_title(env)


async def test_mass_import_batch_commits(env):  # AK-46
    env.settings.batch_size = 500
    n = 2000
    for i in range(n):
        env.imap.add("INBOX", mails.make(f"Massen {i}", msgid=f"<mass-{i}@example.invalid>", body=f"Text {i}"),
                     NOV1 + timedelta(seconds=i))
    mb = await env.add_mailbox()
    start = env.commits()
    rounds = 0
    while True:
        rounds += 1
        out = await env.sync(mb)
        if not out["more"]:
            break
    await env.reg.flush_due(force=True)
    assert rounds == 4 and len(await env.sources()) == n
    log = git(env.repo, "log", f"-{env.commits() - start}", "--format=%s", "--name-only").strip().split("\n\n")
    sizes = [len([l for l in block.splitlines() if l.endswith(".md")]) for block in log]
    assert max(sizes) <= 500 and sum(sizes) >= n and env.commits() - start <= 8


async def test_no_passwords_or_mail_texts_in_logs(env, caplog):  # AK-55
    secret_text = "Geheimer Inhalt 0815 der Mail"
    env.imap.add("INBOX", mails.make("Log-Test", msgid="<log@example.invalid>", body=secret_text), NOV1)
    env.imap.add("INBOX", mails.BROKEN, NOV1)
    with caplog.at_level(logging.DEBUG):
        mb = await env.add_mailbox()
        await env.sync(mb)
        await env.extract_all()
        await env.classify_all()
        env.imap.reject_login = True
        await env.sync(mb)
    logs = caplog.text
    assert IMAP_LOGIN not in logs and secret_text not in logs
    row = await env.mailbox(mb["id"])
    assert IMAP_LOGIN not in row["last_error"] and row["password_enc"] not in logs
