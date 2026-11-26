"""Integration: import from the fake IMAP server into archive + register (AK-1–9, AK-27, AK-40, AK-47–49)."""
import asyncio
from datetime import date, datetime, timedelta, timezone

from app.importer import Importer

from . import mails
from .conftest import NOV1
from .fakeimap import FakeImapServer


def _mail(i, folder="INBOX", **kw):
    ascii_folder = folder.encode("ascii", "ignore").decode()
    return mails.make(f"Mail {i} {folder}", msgid=f"<{ascii_folder}-{i}@example.invalid>", **kw)


async def test_inbox_and_sent_only_read_only(env):  # AK-1, AK-4, AK-27
    for i in range(3):
        env.imap.add("INBOX", _mail(i), NOV1, flags=["\\Flagged"] if i == 0 else [])
    for i in range(2):
        env.imap.add("Gesendet", _mail(i, "Gesendet"), NOV1, flags=["\\Seen"])
    for folder in ("Spam", "Papierkorb", "Entwürfe", "Archiv"):
        env.imap.add(folder, _mail(9, folder), NOV1)
    before = env.imap.flags()
    mb = await env.add_mailbox()
    out = await env.sync(mb)
    assert out["imported"] == 5 and out["folders"] == ["INBOX", "Gesendet"]
    srcs = await env.sources()
    assert len(srcs) == 5
    assert all(s["path"].startswith("emails/2026/11/") for s in srcs)
    assert {s["title"] for s in srcs} == {"Mail 0 INBOX", "Mail 1 INBOX", "Mail 2 INBOX", "Mail 0 Gesendet",
                                          "Mail 1 Gesendet"}
    # AK-4: flags untouched (not "seen"), nothing moved or deleted, no writing command
    assert env.imap.flags() == before and env.imap.violations == []
    assert {c for c in env.imap.commands} <= {"CAPABILITY", "LOGIN", "LIST", "EXAMINE", "UID SEARCH", "UID FETCH",
                                              "LOGOUT"}
    # AK-27: stage states
    sid = srcs[0]["id"]
    assert (await env.stages(sid))["detect"] == "done" and (await env.stages(sid))["extract"] == "pending"
    await env.extract_all()
    st = await env.stages(sid)
    assert st["detect"] == "done" and st["extract"] == "done" and st["classify"] == "pending"
    assert st["database"] == "skipped"
    locs = await env.locations(sid)
    assert locs[0]["mailbox"].startswith("privat-") and locs[0]["folder"] in ("INBOX", "Gesendet") and locs[0]["uid"]


async def test_start_date_and_mailbox_without_start_date(env):  # AK-2
    env.imap.add("INBOX", _mail(1), datetime(2026, 10, 31, 12, tzinfo=timezone.utc))
    env.imap.add("INBOX", _mail(2), NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    assert [s["title"] for s in await env.sources()] == ["Mail 2 INBOX"]

    other = FakeImapServer(password="pw2")
    env.servers.append(other)
    other.add("INBOX", _mail(5, extra_headers=None), NOV1)
    mb2 = await env.add_mailbox("Ohne Start", start_date=None, server=other, password="pw2")
    await env.sync(mb2)
    assert len(await env.sources()) == 1  # existing mails are not imported
    other.add("INBOX", mails.make("Neu danach", msgid="<after@example.invalid>"), NOV1)
    await env.sync(mb2)
    assert "Neu danach" in [s["title"] for s in await env.sources()]


async def test_sent_folder_fallback_name(env):  # AK-3
    server = FakeImapServer(password="pw3")
    env.servers.append(server)
    server.folders["Gesendet"].special = ""  # no \Sent flag at all
    from .fakeimap import Folder
    server.folders["Sent"] = Folder("Sent")
    server.add("Sent", mails.make("Gesendet ohne Flag", msgid="<sent@example.invalid>"), NOV1)
    server.add("Gesendet", mails.make("Nicht gewählt", msgid="<notsent@example.invalid>"), NOV1)
    mb = await env.add_mailbox("Fallback", server=server, password="pw3")
    out = await env.sync(mb)
    assert out["folders"] == ["INBOX", "Sent"]
    assert [s["title"] for s in await env.sources()] == ["Gesendet ohne Flag"]


async def test_new_mail_in_next_tick_and_idempotent(env):  # AK-5, AK-6
    env.imap.add("INBOX", _mail(1), NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    await env.extract_all()
    await env.reg.flush_due(force=True)
    commits, files = env.commits(), env.files()
    out = await env.sync(mb)  # nothing new
    await env.reg.flush_due(force=True)
    assert out["imported"] == 0 and out["linked"] == 0
    assert env.commits() == commits and env.files() == files and len(await env.sources()) == 1
    env.imap.add("INBOX", mails.make("Ganz neu", msgid="<new@example.invalid>"), NOV1 + timedelta(days=3))
    await env.sync(mb)
    await env.extract_all()
    new = next(s for s in await env.sources() if s["title"] == "Ganz neu")
    fm, content = env.doc(new["id"])
    assert fm["title"] == "Ganz neu" and "**Von:**" in content
    row = await env.mailbox(mb["id"])
    assert row["next_sync_at"] - datetime.now(timezone.utc) > timedelta(minutes=14)  # interval 15 min


async def test_same_message_id_twice_in_one_folder(env):  # AK-6 (direct + via mailing list)
    env.imap.add("INBOX", mails.make("Doppelt", msgid="<dup@example.invalid>"), NOV1)
    env.imap.add("INBOX", mails.make("Doppelt", msgid="<dup@example.invalid>", extra_headers={"X-List": "yes"}), NOV1)
    env.imap.add("INBOX", _mail(1), NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    await env.extract_all()
    await env.sync(mb)  # the second copy may be seen once more and is remembered
    await env.reg.flush_due(force=True)
    commits, files = env.commits(), env.files()
    fetches = env.imap.commands.count("UID FETCH")
    locs = await env.locations()
    for _ in range(3):
        out = await env.sync(mb)
        assert out["imported"] == 0 and out["linked"] == 0
    await env.reg.flush_due(force=True)
    assert env.commits() == commits and env.files() == files
    assert env.imap.commands.count("UID FETCH") == fetches  # nothing fetched again
    assert await env.locations() == locs and len(await env.sources()) == 2
    # nightly: the copy of the location goes, the other copy stays: still one present location, no deletion
    dup = next(l for l in locs if l["message_id"] == "<dup@example.invalid>")
    env.imap.remove("INBOX", dup["uid"])
    await env.sync(mb, nightly=True)
    now = [l for l in await env.locations(dup["source_id"]) if l["present"]]
    assert len(now) == 1 and now[0]["uid"] != dup["uid"]
    assert not any(s["deleted"] for s in await env.sources())
    out = await env.sync(mb)
    assert out["imported"] == 0 and out["linked"] == 0


async def test_same_mail_in_two_folders_and_two_mailboxes(env):  # AK-7, EC-1, EC-13
    raw = mails.with_pdfs(msgid="<self@example.invalid>")
    env.imap.add("INBOX", raw, NOV1)
    env.imap.add("Gesendet", raw, NOV1)
    second = FakeImapServer(password="pw2")
    env.servers.append(second)
    second.add("INBOX", raw, NOV1)
    mb1 = await env.add_mailbox("Privat")
    mb2 = await env.add_mailbox("Zweites Konto", server=second, password="pw2")
    await env.sync(mb1)
    await env.sync(mb2)
    srcs = await env.sources()
    assert len(srcs) == 1
    locs = await env.locations(srcs[0]["id"])
    assert sorted((l["mailbox"].split("-")[0], l["folder"]) for l in locs) == [
        ("privat", "Gesendet"), ("privat", "INBOX"), ("zweites", "INBOX")]
    emls = [f for f in env.files() if f.endswith(".eml")]
    assert len(emls) == 1 and emls[0].startswith("privat-")
    await env.extract_all()
    fm, _ = env.doc(srcs[0]["id"])
    assert len(fm["locations"]) == 3 and {"mailbox", "folder", "uid", "message_id"} <= set(fm["locations"][0])


async def test_mails_without_message_id(env):  # AK-8
    a = mails.make("Ohne ID", body="erster Inhalt", msgid=None)
    b = mails.make("Ohne ID", body="zweiter Inhalt", msgid=None)
    env.imap.add("INBOX", a, NOV1)
    env.imap.add("INBOX", b, NOV1)
    env.imap.add("Gesendet", a, NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    srcs = await env.sources()
    assert len(srcs) == 2
    counts = sorted([len(await env.locations(s["id"])) for s in srcs])
    assert counts == [1, 2]


async def test_two_instances_one_connection(env):  # AK-9, AK-48
    for i in range(30):
        env.imap.add("INBOX", _mail(i), NOV1)
    mb = await env.add_mailbox()
    other = Importer(env.settings, env.pool, env.client)
    results = await asyncio.gather(env.sync(mb), env.sync(mb, importer=other), env.sync(mb))
    await env.sync(mb, importer=other)
    assert sum(1 for r in results if r.get("skipped") == "busy") >= 1
    assert len(await env.sources()) == 30
    assert len([f for f in env.files() if f.endswith(".eml")]) == 30
    assert env.imap.max_active == 1


async def test_two_instances_ticking(env):  # AK-9 with the real tick loops
    for i in range(10):
        env.imap.add("INBOX", _mail(i), NOV1)
    await env.add_mailbox()
    other = Importer(env.settings, env.pool, env.client)
    for _ in range(5):
        await asyncio.gather(env.importer.tick(), other.tick())
        await asyncio.gather(*env.importer.running.values(), *other.running.values())
    assert len(await env.sources()) == 10 and env.imap.max_active == 1


async def test_history_in_packages_new_mail_first(env):  # AK-46 (small), AK-47
    env.settings.batch_size = 4
    for i in range(10):
        env.imap.add("INBOX", _mail(i), NOV1 + timedelta(minutes=i))
    mb = await env.add_mailbox()
    out = await env.sync(mb)
    assert out["imported"] == 4 and out["more"]
    titles = {s["title"] for s in await env.sources()}
    assert titles == {f"Mail {i} INBOX" for i in (6, 7, 8, 9)}  # newest first
    row = await env.mailbox(mb["id"])
    assert row["next_sync_at"] <= datetime.now(timezone.utc) + timedelta(seconds=1)  # history: due again at once
    env.imap.add("INBOX", mails.make("Eilig", msgid="<urgent@example.invalid>"), NOV1 + timedelta(hours=1))
    await env.sync(mb)
    titles = {s["title"] for s in await env.sources()}
    assert "Eilig" in titles and len(titles) == 8
    while (await env.sync(mb))["more"]:
        pass
    assert len(await env.sources()) == 11


async def test_earlier_and_later_start_date(env):  # AK-40
    env.imap.add("INBOX", _mail(1), datetime(2026, 9, 15, tzinfo=timezone.utc))
    env.imap.add("INBOX", _mail(2), NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    assert len(await env.sources()) == 1
    async with env.pool.acquire() as con:
        await con.execute("UPDATE alice.imap_mailboxes SET start_date = '2026-09-01' WHERE id = $1", mb["id"])
    await env.sync(mb)
    assert len(await env.sources()) == 2
    async with env.pool.acquire() as con:
        await con.execute("UPDATE alice.imap_mailboxes SET start_date = '2026-12-01' WHERE id = $1", mb["id"])
    await env.sync(mb)
    srcs = await env.sources()
    assert len(srcs) == 2 and not any(s["deleted"] for s in srcs)


async def test_status_fields(env):  # AK-49, AK-41
    env.imap.add("INBOX", _mail(1), NOV1)
    env.imap.add("Gesendet", _mail(2, "Gesendet"), NOV1)
    mb = await env.add_mailbox()
    await env.sync(mb)
    row = await env.mailbox(mb["id"])
    assert row["status"] == "active" and row["last_synced_at"] and row["mails_indexed"] == 2
    assert row["last_error"] is None
    env.imap.reject_login = True
    await env.sync(mb)
    row = await env.mailbox(mb["id"])
    assert row["status"] == "error" and row["last_error"].startswith("Anmeldung abgelehnt")
    assert row["mails_indexed"] == 2


async def test_status_and_new_mails_over_ticks(env):
    mb = await env.add_mailbox(start_date=date(2026, 11, 1))
    await env.sync(mb)
    assert (await env.mailbox(mb["id"]))["mails_indexed"] == 0
