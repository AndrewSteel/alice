"""
Shared fixtures.

Integration environment (`env`): the real register code (alice-source-registry, loaded in-process)
with the throwaway PostgreSQL (TEST_POSTGRES_DSN) and a temporary git repo, a temporary folder as
mail archive, the fake IMAP server (tests/fakeimap.py, real protocol over TCP) and the importer /
stage workers of this service. Skipped without TEST_POSTGRES_DSN (scripts/test-services.sh sets it).
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import uuid
from datetime import date, datetime, timezone

import httpx
import pytest

from app.config import Settings
from app.crypto import encrypt_password
from app.attachments import AttachmentWorker, Paused
from app.importer import Importer
from app.registry import RegistryClient
from app.workers import ClassifyWorker, ExtractWorker

from .fakeimap import FakeImapServer

DSN = os.environ.get("TEST_POSTGRES_DSN")
REGISTRY_DIR = pathlib.Path(__file__).resolve().parents[2] / "alice-source-registry" / "app"
ENC_KEY = "test-enc-key"
IMAP_LOGIN = "imap-login-4711"  # throwaway value of the fake IMAP server
NOV1 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)


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


def git(repo, *args) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "safe.directory=*", *args], capture_output=True,
                          text=True, check=True).stdout


class FakeGateway:
    """OpenAI compatible stand-in for alice-llm-gateway; records every request."""

    def __init__(self):
        self.requests: list[dict] = []
        self.answers: list = []
        self.default = {"category": "Werbung", "summary": "Ein Angebot eines Händlers. Es gibt Rabatt."}
        self.down = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("gateway down", request=request)
        body = json.loads(request.content)
        self.requests.append({"body": body, "auth": request.headers.get("authorization")})
        content = self.answers.pop(0) if self.answers else self.default
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": content}}]})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url="http://alice-llm-gateway:8011", transport=httpx.MockTransport(self.handler))


DETECTION_LIST = {  # same defaults as alice-file-detection (the service reads them via GET /extensions)
    "document": "pdf,txt,md,docx,doc,xlsx,xls,odt,ods,docm,dotx,ott,rtf,xlsm,ots,csv,pptx,pptm,ppt,ppsx,pps,odp,otp",
    "image": "jpg,jpeg,png,webp,heic,tif,tiff",
    "audio": "mp3,m4a,wav,flac,ogg,aac",
    "video": "mp4,mov,mkv,avi,m4v,webm",
}


class FakeDetection:
    """Stand-in for GET /extensions of alice-file-detection."""

    def __init__(self):
        self.exts = {e: k for k, v in DETECTION_LIST.items() for e in v.split(",")}
        self.down = False

    async def extensions(self):
        if self.down:
            raise Paused("Erkennungsliste der Datei-Erkennung nicht abrufbar (ConnectError)")
        return dict(self.exts)

    async def close(self):
        pass


class Env:
    pass


@pytest.fixture
async def env(tmp_path):
    if not DSN:
        pytest.skip("TEST_POSTGRES_DSN not set")
    import asyncpg

    rmain, rconfig, rservice = _load_registry()
    pool = await asyncpg.create_pool(dsn=DSN, min_size=2, max_size=20)
    async with pool.acquire() as con:
        await con.execute("TRUNCATE alice.sources, alice.mail_import_mailboxes, alice.mail_import_runs, "
                          "alice.mail_attachment_runs CASCADE")
        await con.execute("DELETE FROM alice.imap_mailboxes")
        await con.execute("DELETE FROM alice.users WHERE username = 'mailtest'")
        owner = await con.fetchval("INSERT INTO alice.users (username, role) VALUES ('mailtest', 'admin') RETURNING id")
    repo = tmp_path / "sot"
    repo.mkdir()
    reg = rservice.Registry(rconfig.Settings(repo_path=str(repo), postgres_dsn=DSN), pool, None)
    await reg.startup()
    rmain.app.state.reg = reg
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=rmain.app), base_url="http://registry", timeout=600)
    client = RegistryClient("http://registry", client=http)
    archive = tmp_path / "mail"
    archive.mkdir()
    settings = Settings(postgres_dsn=DSN, mail_enc_key=ENC_KEY, archive_path=str(archive), tick_seconds=0.01,
                        history_pause_seconds=0, imap_timeout_seconds=10, extract_poll_seconds=0.01,
                        classify_poll_seconds=0.01, gateway_key="test-background-key", model="test-model",
                        classify_chars=300, llm_retry_seconds=0)
    imap = FakeImapServer(password=IMAP_LOGIN)

    e = Env()
    e.pool, e.reg, e.repo, e.archive, e.settings, e.imap, e.client = pool, reg, repo, archive, settings, imap, client
    e.owner = owner
    e.importer = Importer(settings, pool, client)
    e.detection = FakeDetection()
    e.attachments = AttachmentWorker(settings, pool, client, e.importer.archive, e.detection)
    e.extract = ExtractWorker(settings, client, e.importer, e.attachments.known_links)
    e.gateway = FakeGateway()
    e.classify = ClassifyWorker(settings, client, http=e.gateway.client())
    e.servers = [imap]

    async def add_mailbox(name="Privat", start_date: date | None = date(2026, 11, 1), interval=15, server=None,
                          password=IMAP_LOGIN):
        server = server or imap
        async with pool.acquire() as con:
            row = await con.fetchrow(
                "INSERT INTO alice.imap_mailboxes (owner_id, display_name, imap_host, imap_port, imap_username, "
                "password_enc, ssl_enabled, sync_interval, start_date) VALUES ($1, $2, '127.0.0.1', $3, $4, $5, "
                "FALSE, $6, $7) RETURNING *", owner, name, server.port, server.username,
                encrypt_password(password, ENC_KEY, os.urandom(16)), interval, start_date)
        return dict(row)

    async def mailbox(mb_id):
        async with pool.acquire() as con:
            return dict(await con.fetchrow("SELECT * FROM alice.imap_mailboxes WHERE id = $1", mb_id))

    async def sync(mb, importer=None, nightly=False):
        return await (importer or e.importer).sync_mailbox(await mailbox(mb["id"]), nightly=nightly)

    async def sources():
        async with pool.acquire() as con:
            return [dict(r) for r in await con.fetch(
                "SELECT id, title, path, deleted, captured FROM alice.sources WHERE kind = 'email' ORDER BY captured, id")]

    async def locations(sid=None):
        async with pool.acquire() as con:
            return [dict(r) for r in await con.fetch(
                "SELECT source_id, mailbox, folder, uid, message_id, present FROM alice.source_locations "
                "WHERE ($1::text IS NULL OR source_id = $1) ORDER BY id", sid)]

    async def stages(sid):
        return {k: v["state"] for k, v in (await reg.get_source(sid))["stages"].items()}

    async def extract_all():
        n = 0
        while await e.extract.step():
            n += 1
        return n

    async def classify_all():
        while await e.classify.step():
            pass

    def files():
        return sorted(str(p.relative_to(archive)) for p in archive.rglob("*") if p.is_file())

    def commits():
        return int(git(repo, "rev-list", "--count", "HEAD").strip())

    def doc(sid):
        import registry_app.markdown as md
        path = next(p for p in repo.rglob(f"{sid}-*.md"))
        return md.parse(path.read_text())

    e.add_mailbox, e.mailbox, e.sync, e.sources, e.locations, e.stages = add_mailbox, mailbox, sync, sources, locations, stages
    e.extract_all, e.classify_all, e.files, e.commits, e.doc = extract_all, classify_all, files, commits, doc
    e.uuid = uuid
    yield e
    for s in e.servers:
        s.close()
    await e.classify.close()
    await http.aclose()
    await pool.close()
