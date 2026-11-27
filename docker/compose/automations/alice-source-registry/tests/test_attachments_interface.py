"""Interface extensions for mail attachments (PROJ-124): a further parent resets no stage, a document
write with `keep_stages` and its own commit `label`."""
from datetime import datetime, timezone

from .test_registry import _done, log, read_fm, register, stages

NOV = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)


async def _mail(reg, n="m"):
    return (await reg.register(kind="email", hash="mid:" + n * 16, title=f"Mail {n}",
                               location={"mailbox": "inbox", "message_id": f"<{n}@example.invalid>"},
                               captured=NOV))["id"]


async def test_new_parent_keeps_finished_stages(reg, repo_dir):  # PROJ-124 AK-14
    sid = (await register(reg))["id"]
    await _done(reg, sid, "extract", "classify", "database", "rag", "wiki")
    mail = await _mail(reg)
    r = await reg.register(kind="document", hash="sha256:" + "a" * 16, title="anhang.pdf",
                           location={"path": "/mnt/nas/ai/mail/x/2026/11/m.attachments/anhang.pdf"},
                           parents=[mail], complete=True)
    assert r["id"] == sid and not r["created"] and r["changed"]
    st = await stages(reg, sid)
    assert all(st[s]["state"] == "done" for s in ("extract", "classify", "rag", "wiki"))
    # `database` stores the locations (PROJ-119), the new archive path resets it as before
    assert st["database"]["state"] == "pending"
    fm, _ = read_fm(repo_dir, (await reg.get_source(sid))["path"])
    assert fm["parents"] == [mail]


async def test_write_with_keep_stages_and_label(reg, repo_dir):  # PROJ-124 AK-22
    mail = await _mail(reg)
    await _done(reg, mail, "extract", "classify")
    path = (await reg.get_source(mail))["path"]
    r = await reg.write_document(mail, stage="extract", fields={"attachments": [{"filename": "a.pdf", "id": "x"}]},
                                 content="## Anhänge\n\n- a.pdf → [Markdown](<../a.md>)\n", label="attachments",
                                 keep_stages=["classify"])
    assert r["changed"] and "classify" not in r["reset"]
    assert (await stages(reg, mail))["classify"]["state"] == "done"
    assert log(repo_dir, path)[0] == f"Alice ETL|attachments: {mail} Mail m"
    # without keep_stages the content change resets classify (PROJ-118 rule unchanged)
    r = await reg.write_document(mail, stage="extract", content="anders\n")
    assert "classify" in r["reset"]
