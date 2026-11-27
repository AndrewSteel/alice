"""End to end: the real register code (alice-source-registry, loaded in-process) with a throwaway
PostgreSQL and a temporary git repo, the classification worker talking to it over its HTTP interface
and to the fake gateway. Skipped without TEST_POSTGRES_DSN (scripts/test-services.sh sets it)."""
import importlib.util
import os
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

import httpx
import pytest

from app.registry import RegistryClient
from app.worker import Worker

from .test_classifier import DE_SUMMARY, INVOICE
from .test_normalize import VALID_IBAN

DSN = os.environ.get("TEST_POSTGRES_DSN")
REGISTRY_DIR = pathlib.Path(__file__).resolve().parents[2] / "alice-source-registry" / "app"
OCT = datetime(2026, 10, 14, 7, 32, 11, tzinfo=timezone.utc)  # 09.32.11 in Berlin
NOV = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
INVOICE_TEXT = "## Seite 1\n\nRechnung Nr. R-2026-10\n\nBetrag 119,00 EUR\n"
CONTRACT = {"title": "Stromvertrag Stadtwerke", "summary": DE_SUMMARY,
            "fields": {"contract_type": "Stromvertrag", "contract_partner": "Stadtwerke", "monthly_cost": 30}}


def _load_registry():
    if "registry_app" not in sys.modules:
        spec = importlib.util.spec_from_file_location("registry_app", REGISTRY_DIR / "__init__.py",
                                                      submodule_search_locations=[str(REGISTRY_DIR)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules["registry_app"] = mod
        spec.loader.exec_module(mod)
    import registry_app.config as rconfig
    import registry_app.main as rmain
    import registry_app.service as rservice
    return rmain, rconfig, rservice


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=*", *args], capture_output=True,
                          text=True, check=True).stdout


@pytest.fixture
async def env(tmp_path, settings, classifier):
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    rmain, rconfig, rservice = _load_registry()
    pool = await asyncpg.create_pool(dsn=DSN, min_size=1, max_size=10)
    async with pool.acquire() as con:
        await con.execute("TRUNCATE alice.sources CASCADE")
    repo = tmp_path / "sot"
    repo.mkdir()
    reg = rservice.Registry(rconfig.Settings(repo_path=str(repo), postgres_dsn=DSN), pool, None)
    await reg.startup()
    rmain.app.state.reg = reg
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=rmain.app), base_url="http://registry")
    client = RegistryClient("http://registry", client=http)

    class Env:
        pass

    e = Env()
    e.reg, e.repo, e.pool, e.client = reg, repo, pool, client
    e.worker = Worker(settings, client, classifier)
    e.counter = 0

    async def register(title="scan.pdf", kind="document", modified=OCT, path=None):
        e.counter += 1
        res = await reg.register(kind=kind, hash=f"sha256:{e.counter:016d}", title=title,
                                 location={"path": path or f"/mnt/nas/share/{e.counter}-{title}"}, size=1,
                                 modified=modified, captured=NOV, complete=True)
        return res["id"]

    async def extract(sid, content=INVOICE_TEXT, empty=False, language="de"):
        items = (await reg.claim("extract", 100, ["document"]))["items"]
        for it in items:
            if it["source_id"] != sid:
                await reg.release(it["source_id"], "extract", it["token"])
        tok = next(i["token"] for i in items if i["source_id"] == sid)
        await reg.write_document(sid, stage="extract", content=content, fields={
            "language": language, "extraction": {"method": "text", "ocr_pages": [], "empty": empty}})
        await reg.complete(sid, "extract", tok)

    e.register, e.extract = register, extract
    yield e
    await http.aclose()
    await pool.close()


async def run(e):
    for _ in range(50):
        n = await e.worker.step()
        await e.worker.wait_idle()
        if n == 0 and not e.worker.active:
            return


async def stage(e, sid, name="classify"):
    return (await e.reg.get_source(sid))["stages"][name]


async def doc(e, sid):
    return await e.reg.read_document(sid)


def log(e, fmt="%an|%s"):
    return git(e.repo, "log", f"--format={fmt}").splitlines()


async def test_invoice_end_to_end(env, gateway):  # AK-1, AK-4, AK-17, AK-46
    sid = await env.register()
    # realistic length: git recognizes the rename by content similarity (the frontmatter grows a lot)
    await env.extract(sid, content=INVOICE_TEXT + "".join(f"Position {i}: Arbeitspreis 0,30 EUR/kWh\n"
                                                         for i in range(80)))
    before = (await doc(env, sid))["content"]
    gateway.push("classify", {"type": "Invoice", "confidence": 0.93})
    gateway.push("extract", INVOICE)
    await run(env)
    assert (await stage(env, sid))["state"] == "done"
    d = await doc(env, sid)
    fm = d["frontmatter"]
    title = "2026-10-14 09.32.11 Stromrechnung Stadtwerke Oktober 2026"
    assert fm["title"] == title and fm["type"] == "Invoice"
    assert fm["classification"] == {"confidence": 0.93, "uncertain": False}
    assert fm["summary"] == INVOICE["summary"] and fm["summary_language_uncertain"] is False
    assert fm["fields"]["amount_gross"] == 119.0 and fm["fields"]["invoice_date"] == "2026-10-14"
    assert d["content"] == before  # content part unchanged (AK-46)
    for key in fm:  # no state, error or retry counter (AK-46)
        assert key not in ("state", "attempts", "error", "last_error", "retries")
    path = (await env.reg.get_source(sid))["path"]
    assert path == f"documents/2026/11/{sid}-2026-10-14-09-32-11-stromrechnung-stadtwerke-oktober-2026.md"
    text = (env.repo / path).read_text()
    assert f"\n# {title}\n" in text
    assert log(env)[0] == f"Alice ETL|classify: {sid} {title}"
    assert sum(1 for line in log(env) if line.startswith("Alice ETL|classify:")) == 1
    # renamed in git (same folder): the history follows the file back to detect and extract
    follow = git(env.repo, "log", "--follow", "--format=%s", "--", path).splitlines()
    assert [m.split(":")[0] for m in follow] == ["classify", "extract", "detect"]
    st = (await env.reg.get_source(sid))["stages"]
    assert st["database"]["state"] == "pending"


async def test_batch_commit(env, settings):  # AK-4 (mass run)
    settings.batch = True
    ids = [await env.register(f"n{i}.pdf") for i in range(3)]
    for i in ids:
        await env.extract(i)
    await run(env)
    await env.reg.flush_due(force=True)
    assert log(env, "%s")[0] == "rebuild: classify 3 sources"
    for i in ids:
        assert (await stage(env, i))["state"] == "done"


async def test_only_documents_after_extract(env, gateway):  # AK-2, AK-3, AK-5, AK-6
    waiting = await env.register("wartet.pdf")
    img = await env.register("foto.jpg", kind="image")
    img_before = (env.repo / (await env.reg.get_source(img))["path"]).read_text()
    folder = await env.register("ordner.pdf", path="/mnt/nas/rechnungen/ordner.pdf")
    async with env.pool.acquire() as con:
        await con.execute("INSERT INTO alice.dms_watched_folders (path, suggested_type) VALUES ($1, 'Invoice') "
                          "ON CONFLICT (path) DO UPDATE SET suggested_type = 'Invoice'", "/mnt/nas/rechnungen")
    try:
        await env.extract(folder)
        gateway.push("classify", {"type": "Contract", "confidence": 0.9})
        await run(env)
        assert (await stage(env, waiting))["state"] == "pending"
        assert (await stage(env, img))["state"] == "skipped"  # classify does not apply to images (PROJ-125)
        assert (env.repo / (await env.reg.get_source(img))["path"]).read_text() == img_before
        assert len(gateway.calls("classify")) == 1  # the folder type is not used (AK-5)
        assert (await doc(env, folder))["frontmatter"]["type"] == "Contract"
        # AK-6: extract done → processed in the next poll round
        await env.extract(waiting)
        await run(env)
        assert (await stage(env, waiting))["state"] == "done"
    finally:
        async with env.pool.acquire() as con:
            await con.execute("DELETE FROM alice.dms_watched_folders WHERE path = $1", "/mnt/nas/rechnungen")


async def test_same_title_two_files(env, gateway):  # AK-19
    a = await env.register("a.pdf", modified=OCT)
    b = await env.register("b.pdf", modified=datetime(2026, 10, 15, 8, 0, 0, tzinfo=timezone.utc))
    await env.extract(a)
    await env.extract(b, content="Andere Rechnung\n")
    gateway.defaults["extract"] = INVOICE
    await run(env)
    ta, tb = (await doc(env, a))["frontmatter"]["title"], (await doc(env, b))["frontmatter"]["title"]
    assert ta != tb and ta.endswith("Stromrechnung Stadtwerke Oktober 2026") and tb.endswith(
        "Stromrechnung Stadtwerke Oktober 2026")
    for sid in (a, b):
        assert (env.repo / (await env.reg.get_source(sid))["path"]).exists()


async def test_original_changed_new_prefix_and_type_change(env, gateway):  # AK-15, AK-20, AK-37
    sid = await env.register()
    await env.extract(sid)
    gateway.push("classify", {"type": "Invoice", "confidence": 0.9})
    gateway.push("extract", INVOICE)
    await run(env)
    # a field of the invoice protected by hand
    path = (await env.reg.get_source(sid))["path"]
    text = (env.repo / path).read_text().replace("recipient: Max Muster", "recipient: Erika Muster")
    (env.repo / path).write_text(text)
    await env.reg.scan()
    assert (await stage(env, sid))["state"] == "done"
    # original changed: new hash and modified → classify pending (decision A), new extraction
    await env.reg.update_original(sid, hash="sha256:changed000000001", size=2,
                                  modified=datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc))
    assert (await stage(env, sid))["state"] == "pending"
    await env.extract(sid, content="Stromvertrag\n\nMonatlich 30 EUR\n")
    gateway.push("classify", {"type": "Contract", "confidence": 0.9})
    gateway.push("extract", CONTRACT)
    await run(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert fm["title"] == "2026-11-20 13.00.00 Stromvertrag Stadtwerke"
    assert fm["type"] == "Contract"
    assert "invoice_number" not in fm["fields"] and "amount_gross" not in fm["fields"]
    assert fm["fields"]["contract_type"] == "Stromvertrag" and fm["fields"]["monthly_cost"] == 30.0
    assert fm["fields"]["recipient"] == "Erika Muster" and "fields.recipient" in fm["manual"]


async def test_hand_type_change(env, gateway):  # AK-34
    sid = await env.register()
    await env.extract(sid)
    await run(env)  # defaults: Document
    path = (await env.reg.get_source(sid))["path"]
    text = (env.repo / path).read_text().replace("type: Document", "type: Invoice")
    (env.repo / path).write_text(text)
    await env.reg.scan()
    assert (await stage(env, sid))["state"] == "pending"
    n_classify = len(gateway.calls("classify"))
    gateway.push("extract", INVOICE)
    await run(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert len(gateway.calls("classify")) == n_classify  # no classification call
    assert fm["type"] == "Invoice" and fm["fields"]["invoice_number"] == "R-2026-10"


async def test_hand_content_correction(env, gateway):  # AK-35
    sid = await env.register()
    await env.extract(sid)
    await run(env)
    path = (await env.reg.get_source(sid))["path"]
    (env.repo / path).write_text((env.repo / path).read_text().replace("119,00", "191,00"))
    await env.reg.scan()
    assert (await stage(env, sid))["state"] == "pending"
    await run(env)
    assert "191,00" in gateway.calls("classify")[-1]["user"]
    assert (await stage(env, sid))["state"] == "done"


async def test_manual_title_summary_iban(env, gateway):  # AK-38
    sid = await env.register()
    await env.extract(sid)
    stmt = {"title": "Kontoauszug Oktober", "summary": DE_SUMMARY,
            "fields": {"iban": VALID_IBAN, "bank_name": "Bank A", "currency": "EUR"}}
    gateway.defaults["classify"] = {"type": "BankStatement", "confidence": 0.9}
    gateway.push("extract", stmt)
    await run(env)
    path = (await env.reg.get_source(sid))["path"]
    text = (env.repo / path).read_text()
    text = text.replace(f"iban: {VALID_IBAN}", "iban: GB82WEST12345698765432")
    text = text.replace("title: 2026-10-14 09.32.11 Kontoauszug Oktober", "title: Mein Konto")
    text = text.replace(f"summary: {DE_SUMMARY}", "summary: Von Hand.")
    (env.repo / path).write_text(text)
    await env.reg.scan()
    await env.reg.retry(sid, "classify")
    gateway.push("extract", {"title": "Neu", "summary": "Die Bank schreibt etwas Neues zum Konto.",
                             "fields": {"iban": VALID_IBAN, "bank_name": "Bank B", "currency": "EUR"}})
    await run(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert fm["title"] == "Mein Konto" and fm["summary"] == "Von Hand."
    assert fm["fields"]["iban"] == "GB82WEST12345698765432"
    assert fm["fields"]["bank_name"] == "Bank B"


async def test_invalid_answers_backoff_permanent_and_retry(env, gateway):  # AK-31, AK-39, AK-44
    sid = await env.register()
    await env.extract(sid)
    before = (env.repo / (await env.reg.get_source(sid))["path"]).read_text()
    gateway.defaults["classify"] = "kein json"
    for attempt in range(1, 6):
        await run(env)
        st = await stage(env, sid)
        assert st["attempts"] == attempt and "Ungültige Antwort des LLM" in st["last_error"]
        async with env.pool.acquire() as con:  # skip the backoff wait
            await con.execute("UPDATE alice.source_stages SET next_retry_at = NOW() WHERE source_id = $1 "
                              "AND stage = 'classify' AND state = 'failed'", sid)
    assert (await stage(env, sid))["state"] == "failed_permanent"
    assert (env.repo / (await env.reg.get_source(sid))["path"]).read_text() == before
    await env.reg.retry(sid, "classify")  # AK-39
    gateway.defaults["classify"] = {"type": "Invoice", "confidence": 0.9}
    await run(env)
    assert (await stage(env, sid))["state"] == "done"


async def test_bank_statement_section_fails_unchanged(env, gateway):  # AK-31
    sid = await env.register()
    content = "".join(f"## Seite {p}\n\n" + ("Buchung " * 1200) + "\n" for p in range(1, 4))
    await env.extract(sid, content=content)
    before = (env.repo / (await env.reg.get_source(sid))["path"]).read_text()
    gateway.push("classify", {"type": "BankStatement", "confidence": 0.9})
    gateway.push("transactions", {"transactions": []}, "kaputt", "kaputt")
    await run(env)
    st = await stage(env, sid)
    assert st["state"] == "failed" and "Buchungen Seite" in st["last_error"]
    assert (env.repo / (await env.reg.get_source(sid))["path"]).read_text() == before


async def test_gateway_down_no_attempt(env, gateway, settings):  # AK-42
    settings.llm_retry_seconds = 0
    sid = await env.register()
    await env.extract(sid)
    gateway.down = True
    await env.worker.step()
    await env.worker.wait_idle()
    st = await stage(env, sid)
    assert st["state"] == "pending" and st["attempts"] == 0
    gateway.down = False
    await run(env)
    assert (await stage(env, sid))["state"] == "done"


async def test_empty_document(env, gateway):  # AK-32
    sid = await env.register("leer.pdf")
    await env.extract(sid, content="Kein Text extrahiert.", empty=True, language=None)
    title_before = (await doc(env, sid))["frontmatter"]["title"]
    await run(env)
    fm = (await doc(env, sid))["frontmatter"]
    assert gateway.requests == []
    assert fm["type"] == "Document" and fm["summary"] == "" and fm["title"] == title_before == "leer.pdf"
    assert fm["fields"] == {"document_date": None, "sender": None, "recipient": None, "tags": None}
    assert (await stage(env, sid))["state"] == "done"


async def test_deleted_during_classification(env, gateway):  # EC-15
    sid = await env.register("weg.pdf", path="/mnt/nas/share/weg.pdf")

    def delete_meanwhile(req):
        return {"type": "Invoice", "confidence": 0.9}

    await env.extract(sid)
    item = (await env.client.claim(1))["items"][0]
    await env.reg.remove_location(sid, {"path": "/mnt/nas/share/weg.pdf"})
    gateway.push("classify", delete_meanwhile)
    before = (env.repo / (await env.reg.get_source(sid))["path"]).read_text()
    assert await env.worker.process(item) == "discarded"
    assert (env.repo / (await env.reg.get_source(sid))["path"]).read_text() == before
    st = await stage(env, sid)
    assert st["state"] == "pending" and st["attempts"] == 0
