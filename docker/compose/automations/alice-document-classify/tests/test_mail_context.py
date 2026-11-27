"""PROJ-124: classification of mail attachments with the mail context (AK-24–27)."""
from app.worker import Worker

from .conftest import drain


def _mail(registry, sid, subject, date, sender=None, text="Geheimer Mailtext 4711"):
    registry.docs[sid] = {"id": sid, "content": f"**Von:** x\n\n{text}\n",
                          "frontmatter": {"id": sid, "kind": "email", "title": subject, "date": date,
                                          "captured": date,
                                          "from": sender or {"name": "Stadtwerke", "address": "info@stadtwerke.invalid"}}}


async def _run(settings, registry, classifier):
    await drain(Worker(settings, registry, classifier))


async def test_prompt_contains_mail_context_not_mail_text(settings, registry, classifier, gateway):  # AK-24
    _mail(registry, "mailaaaaaaaa", "Ihre Rechnung Oktober", "2026-01-15T08:30:00+00:00")
    registry.add("attaaaaaaaaa", content="Scan Seite 1", title="scan0001.pdf", parents=["mailaaaaaaaa"])
    await _run(settings, registry, classifier)
    assert registry.state["attaaaaaaaaa"] == "done"
    for task in ("classify", "extract"):
        user = gateway.calls(task)[0]["user"]
        assert "Subject: Ihre Rechnung Oktober" in user
        assert "From: Stadtwerke <info@stadtwerke.invalid>" in user
        assert "Date: 2026-01-15 09:30" in user  # local time (Europe/Berlin)
        assert "Geheimer Mailtext" not in user
        assert user.index("Scan Seite 1") < user.index("<mail>")  # document text first, hint after it


async def test_oldest_mail_is_used(settings, registry, classifier, gateway):  # AK-25
    _mail(registry, "mailnewaaaaa", "AW: Vertrag", "2026-03-01T10:00:00+00:00")
    _mail(registry, "mailoldaaaaa", "Vertrag", "2026-02-01T10:00:00+00:00")
    registry.add("attaaaaaaaaa", title="vertrag.pdf", parents=["mailnewaaaaa", "mailoldaaaaa"])
    await _run(settings, registry, classifier)
    user = gateway.calls("classify")[0]["user"]
    assert "Subject: Vertrag\n" in user and "AW: Vertrag" not in user


async def test_unreadable_mail_runs_without_context(settings, registry, classifier, gateway):  # AK-26
    registry.add("attaaaaaaaaa", title="scan.pdf", parents=["mailgoneaaaa"])  # not in the fake register
    await _run(settings, registry, classifier)
    assert registry.state["attaaaaaaaaa"] == "done"
    assert "<mail>" not in gateway.calls("classify")[0]["user"]


async def test_without_parents_prompt_unchanged(settings, registry, classifier, gateway):  # AK-27
    from app import prompts

    registry.add("docaaaaaaaaa", content="Rechnung Nr. 1", title="rechnung.pdf")
    await _run(settings, registry, classifier)
    sys_c, user_c = prompts.classify("Rechnung Nr. 1", "de")
    call = gateway.calls("classify")[0]
    assert call["user"] == user_c and call["system"] == sys_c
    assert prompts.mail_hint(None) == "" and prompts.mail_hint({}) == ""
