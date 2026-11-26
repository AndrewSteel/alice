"""PROJ-123: levels 5 (IMAP <-> register) and 6 (register <-> mail archive) of the reconciliation, with a
stand-in for alice-mail-import (its own behaviour is tested in alice-mail-import)."""
from app.clients import Unavailable

from .conftest import NOV
from .test_reconcile import gaps, nas_sources, reconcile


class FakeMail:
    def __init__(self):
        self.result = {"imap": {"missing": [], "notes": []}, "archive": {"missing": []}}
        self.repairs: list[list[dict]] = []
        self.down = False

    async def check(self, timeout):
        if self.down:
            raise Unavailable("Mail-Import nicht erreichbar: ConnectError")
        return self.result

    async def repair(self, items, timeout):
        self.repairs.append(items)
        return {"results": [{**it, "repaired": True, "detail": "nachgeholt"} for it in items]}

    async def close(self):
        pass


async def _mail_source(env):
    r = await env.reg.register(kind="email", hash="mid:" + "a" * 64, title="Rechnung per Mail",
                               location={"mailbox": "privat-0001", "folder": "INBOX", "uid": 3,
                                         "message_id": "<r@example.invalid>"}, size=10, captured=NOV, complete=True)
    return r["id"]


async def test_levels_5_and_6(env):  # AK-51, AK-52, AK-53
    await nas_sources(env, 100)  # enough sources: the repairs stay below the 5 % guard
    sid = await _mail_source(env)
    mail = FakeMail()
    env.reconciler.mail = mail
    mail.result = {
        "imap": {"missing": [{"mailbox": "privat-0001", "folder": "INBOX", "uid": 9}], "notes": []},
        "archive": {"missing": [
            {"gap": "attachment_missing", "source_id": sid, "path": "privat-0001/2026/11/x.attachments/a.pdf",
             "on_server": True, "title": "Rechnung per Mail"},
            {"gap": "eml_missing", "source_id": sid, "path": "privat-0001/2026/11/x.eml", "on_server": True,
             "title": "Rechnung per Mail"}]}}
    r = await reconcile(env)
    assert r["state"] == "complete"
    lv = r["summary"]["levels"]
    assert (lv["5"]["gaps"], lv["5"]["repaired"]) == (1, 1)
    assert (lv["6"]["gaps"], lv["6"]["repaired"]) == (2, 2) and lv["6"]["by_gap"] == {"attachment_missing": 1,
                                                                                     "eml_missing": 1}
    assert mail.repairs == [[{"type": "mail_import", "mailbox": "privat-0001", "folder": "INBOX", "uid": 9},
                             {"type": "mail_rearchive", "source_id": sid}]]
    g5 = await gaps(env, r["id"], 5)
    assert g5[0]["gap"] == "mail_unregistered" and g5[0]["path"] == "privat-0001/INBOX/9"
    assert {e["event"] for e in (await env.reg.get_source(sid))["events"]} >= {"reconcile_mail_archive"}


async def test_level6_gap_only_reported_when_gone_from_server(env):  # AK-52
    sid = await _mail_source(env)
    mail = FakeMail()
    env.reconciler.mail = mail
    mail.result["archive"]["missing"] = [{"gap": "eml_missing", "source_id": sid, "path": "k/x.eml",
                                          "on_server": False, "title": "Rechnung per Mail"}]
    r = await reconcile(env)
    assert r["summary"]["levels"]["6"]["reported"] == 1 and mail.repairs == []
    assert "nicht mehr auf dem Server" in (await gaps(env, r["id"], 6))[0]["detail"]


async def test_mail_import_unreachable(env):
    mail = FakeMail()
    mail.down = True
    env.reconciler.mail = mail
    r = await reconcile(env)
    assert r["state"] == "incomplete" and "Ebenen 5/6 nicht geprüft" in r["reason"]


async def test_mailbox_not_checked_is_visible(env):
    mail = FakeMail()
    mail.result["imap"]["notes"] = ["Postfach privat-0001 nicht geprüft: Anmeldung abgelehnt"]
    env.reconciler.mail = mail
    r = await reconcile(env)
    assert r["state"] == "incomplete" and "Anmeldung abgelehnt" in r["reason"]


async def test_without_mail_import_only_four_levels(env):
    r = await reconcile(env)
    assert sorted(r["summary"]["levels"]) == ["1", "2", "3", "4"]
