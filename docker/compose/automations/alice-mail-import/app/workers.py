"""Stage workers for `kind: email`: extract (mail markdown from the archived `.eml`, no LLM, no IMAP)
and classify (category + German summary through alice-llm-gateway as background load)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx

from . import mailmd
from .archive import Archive
from .config import Settings
from .registry import RegistryClient, RegistryConflict, RegistryError, RegistryUnavailable

logger = logging.getLogger("alice-mail-import")

CATEGORIES = {"important": "important", "wichtig": "important", "promotion": "promotion", "werbung": "promotion",
              "social": "social", "sozial": "social", "soziale netzwerke": "social", "spam": "spam"}
MISSING_ENTRY_DELAY = 30       # archive entry not written yet (registration just happened)
MISSING_FILE_DELAY = 900       # `.eml` missing: level 6 of the reconciliation stores it again


class _Loop:
    stage = ""

    def __init__(self, settings: Settings, registry: RegistryClient):
        self.s = settings
        self.registry = registry
        self.last_tick = time.monotonic()
        self.paused_reason = ""
        self.stats = {"done": 0, "failed": 0, "failed_permanent": 0, "released": 0, "discarded": 0}

    poll = 5.0

    async def run(self) -> None:
        while True:
            self.last_tick = time.monotonic()
            try:
                n = await self.step()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s loop step failed", self.stage)
                n = 0
            if not n:
                await asyncio.sleep(self.poll)

    async def _claim(self, limit: int, requires=None) -> list[dict]:
        try:
            res = await self.registry.claim(self.stage, limit, requires)
        except (RegistryUnavailable, RegistryError) as exc:
            if self.paused_reason != str(exc):
                logger.warning("Stage %s paused: %s", self.stage, exc)
            self.paused_reason = str(exc)
            return []
        if res.get("paused"):
            self.paused_reason = res.get("reason") or "pausiert"
            return []
        self.paused_reason = ""
        return res.get("items") or []

    async def _report(self, call, *args, **kw) -> None:
        try:
            await call(*args, **kw)
        except Exception as exc:  # the register takes the stage back after its timeout
            logger.warning("Could not report the %s result of %s: %s", self.stage, args[0], exc)

    async def release(self, sid: str, token: str, delay: int = 0) -> str:
        await self._report(self.registry.release, sid, self.stage, token, delay)
        self.stats["released"] += 1
        return "released"

    async def fail(self, sid: str, token: str, error: str, permanent: bool = False) -> str:
        await self._report(self.registry.fail, sid, self.stage, token, error, permanent)
        key = "failed_permanent" if permanent else "failed"
        self.stats[key] += 1
        return key


# ==================================================================== extract
class ExtractWorker(_Loop):
    stage = "extract"

    def __init__(self, settings: Settings, registry: RegistryClient, importer):
        super().__init__(settings, registry)
        self.importer = importer
        self.archive: Archive = importer.archive
        self.poll = settings.extract_poll_seconds

    async def step(self) -> int:
        items = await self._claim(self.s.extract_batch_limit)
        # several at once (history package, rebuild run) → batch commits of the register (AK-46, AK-50)
        batch = len(items) > 1
        for item in items:
            await self.process(item, batch=batch)
        return len(items)

    async def process(self, item: dict, batch: bool = False) -> str:
        sid, token = item["source_id"], item["token"]
        entry = await self.importer._entry(sid)
        if entry is None:
            return await self.release(sid, token, MISSING_ENTRY_DELAY)
        if entry["broken"]:
            # AK-42: raw mail archived unchanged, the markdown cannot be built from it
            return await self.fail(sid, token, f"Mail nicht zerlegbar: {entry['broken']}", permanent=True)
        try:
            eml = await asyncio.to_thread(self.archive.read, entry["eml_path"])
        except FileNotFoundError:
            logger.warning("Source %s: archived .eml missing (%s); waiting for the reconciliation", sid,
                           entry["eml_path"])
            return await self.release(sid, token, MISSING_FILE_DELAY)
        except OSError as exc:
            logger.warning("Mail archive not readable (%s); extract paused", exc.strerror or exc)
            return await self.release(sid, token, 60)
        try:
            doc = await self.registry.read_document(sid)
            fields, content = mailmd.build(eml, entry, self.s.archive_path, self.s.tz)
        except (RegistryUnavailable, RegistryConflict) as exc:
            logger.warning("Markdown of %s cannot be read now: %s", sid, exc)
            return await self.release(sid, token)
        except Exception as exc:
            logger.warning("Mail markdown of %s failed: %s", sid, exc.__class__.__name__)
            return await self.fail(sid, token, f"Mail-Markdown nicht erzeugbar ({exc.__class__.__name__})")
        fm = doc.get("frontmatter") or {}
        if fields.get("date") is None and fm.get("captured"):
            fields["date"] = fm["captured"]  # EC-5: without Date header the time of receipt
        for name in ("category", "summary"):
            if name not in fm:
                fields[name] = None  # empty until classify (AK-17); never overwritten here
        try:
            res = await self.registry.write(sid, stage=self.stage, fields=fields, content=content, token=token,
                                            batch=batch or bool(item.get("rebuild")))
        except (RegistryUnavailable, RegistryConflict) as exc:
            logger.warning("Writing the markdown of %s not possible now: %s", sid, exc)
            return await self.release(sid, token)
        except RegistryError as exc:
            return await self.fail(sid, token, f"Schreiben abgelehnt: {exc}"[:500])
        if res.get("discarded"):
            self.stats["discarded"] += 1
            return await self.release(sid, token)
        await self._report(self.registry.done, sid, self.stage, token)
        self.stats["done"] += 1
        return "done"


# ==================================================================== classify
class LlmUnavailable(Exception):
    pass


class InvalidAnswer(Exception):
    pass


SYSTEM_PROMPT = """Du ordnest E-Mails eines Privathaushalts ein.
Antworte ausschließlich mit einem JSON-Objekt: {"category": "<Kategorie>", "summary": "<Zusammenfassung>"}.
Kategorien:
- "important": persönliche oder geschäftliche Mails, die gelesen oder beantwortet werden sollten (Rechnungen, Verträge, Behörden, Termine, Nachrichten von Menschen)
- "promotion": Werbung, Newsletter, Angebote, Rabattaktionen
- "social": Benachrichtigungen sozialer Netzwerke und Plattformen
- "spam": unerwünschte, betrügerische oder Phishing-Mails
Die Zusammenfassung hat 2 bis 3 Sätze und ist IMMER auf Deutsch, auch wenn die Mail in einer anderen Sprache geschrieben ist."""

_THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


def parse_answer(text: str) -> dict:
    text = _FENCE.sub("", _THINK.sub("", text or "").strip()).strip()
    try:
        value = json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        try:
            value = json.loads(text[start:end + 1]) if 0 <= start < end else None
        except ValueError:
            value = None
    if not isinstance(value, dict):
        raise InvalidAnswer("Antwort des LLM ist kein JSON-Objekt")
    value = {str(k).strip().lower(): v for k, v in value.items()}
    raw = str(value.get("category") or "").strip().lower()
    category = CATEGORIES.get(raw)
    if category is None:
        raise InvalidAnswer(f"Unbekannte Kategorie vom LLM: {raw[:50] or '(leer)'}")
    summary = value.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise InvalidAnswer("Zusammenfassung fehlt in der Antwort des LLM")
    return {"category": category, "summary": summary.strip()}


def _people(value) -> str:
    if isinstance(value, dict):
        value = [value]
    out = []
    for p in value or []:
        if isinstance(p, dict):
            out.append(f"{p.get('name')} <{p.get('address')}>" if p.get("name") else str(p.get("address") or ""))
    return ", ".join(o for o in out if o)


def mail_text(content: str) -> str:
    """The mail text of the content part (without the Von/An/Datum block and the attachment list)."""
    text = content or ""
    if text.startswith("**Von:**") or text.startswith("**An:**"):
        text = text.split("\n\n", 1)[1] if "\n\n" in text else ""
    return text.split("\n## Anhänge\n", 1)[0].strip()


def build_prompt(fm: dict, content: str, max_chars: int) -> str:
    return (f"Von: {_people(fm.get('from'))}\nAn: {_people(fm.get('to'))}\n"
            + (f"Cc: {_people(fm.get('cc'))}\n" if fm.get("cc") else "")
            + f"Betreff: {fm.get('title') or ''}\n\nText (Anfang):\n{mail_text(content)[:max_chars]}")


class ClassifyWorker(_Loop):
    stage = "classify"

    def __init__(self, settings: Settings, registry: RegistryClient, http: httpx.AsyncClient | None = None):
        super().__init__(settings, registry)
        self.http = http or httpx.AsyncClient(base_url=settings.gateway_url, timeout=settings.llm_timeout_seconds)
        self.poll = settings.classify_poll_seconds
        self.llm_paused_until = 0.0
        self.llm_reason = ""

    async def close(self) -> None:
        await self.http.aclose()

    async def step(self) -> int:
        if self.llm_paused_until > time.monotonic():
            await asyncio.sleep(min(self.poll, self.llm_paused_until - time.monotonic()))
            return 0
        items = await self._claim(1, requires=["extract"])
        for item in items:
            await self.process(item)
        return len(items)

    async def ask(self, prompt: str) -> dict:
        body = {"messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                "temperature": 0.2, "max_tokens": self.s.max_tokens, "stream": False,
                "response_format": {"type": "json_object"},
                # explicitly without thinking: it would block the single GPU slot (AK-29)
                "chat_template_kwargs": {"enable_thinking": False}}
        if self.s.model:
            body["model"] = self.s.model
        headers = {"Authorization": f"Bearer {self.s.gateway_key}"} if self.s.gateway_key else {}
        try:
            r = await self.http.post("/v1/chat/completions", json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise LlmUnavailable(f"Zeitüberschreitung beim LLM-Gateway ({exc.__class__.__name__})") from None
        except httpx.TransportError as exc:
            raise LlmUnavailable(f"LLM-Gateway nicht erreichbar ({exc.__class__.__name__})") from None
        if r.status_code in (401, 403):
            raise LlmUnavailable(f"LLM-Gateway lehnt den Schlüssel ab ({r.status_code})")
        if r.status_code == 429 or r.status_code >= 500:
            raise LlmUnavailable(f"LLM-Gateway antwortet {r.status_code}")
        if r.status_code >= 400:
            raise InvalidAnswer(f"LLM-Gateway lehnt die Anfrage ab ({r.status_code})")
        try:
            text = r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise InvalidAnswer("Antwort des Gateways ohne Inhalt") from None
        return parse_answer(text)

    async def process(self, item: dict) -> str:
        sid, token = item["source_id"], item["token"]
        try:
            doc = await self.registry.read_document(sid)
        except Exception as exc:
            logger.warning("Markdown of %s cannot be read now: %s", sid, exc)
            return await self.release(sid, token)
        prompt = build_prompt(doc.get("frontmatter") or {}, doc.get("content") or "", self.s.classify_chars)
        try:
            fields = await self.ask(prompt)
        except LlmUnavailable as exc:
            # AK-31: classify failed with backoff; import and markdown are not affected
            if self.llm_paused_until <= time.monotonic():
                logger.warning("LLM gateway unavailable (%s); pausing classify for %ss", exc, self.s.llm_retry_seconds)
            self.llm_reason = str(exc)
            self.llm_paused_until = time.monotonic() + self.s.llm_retry_seconds
            return await self.fail(sid, token, str(exc))
        except InvalidAnswer as exc:
            logger.warning("Classification of %s: %s", sid, exc)
            return await self.fail(sid, token, str(exc))
        try:
            res = await self.registry.write(sid, stage=self.stage, fields=fields, content=None, token=token,
                                            batch=bool(item.get("rebuild")))
        except (RegistryUnavailable, RegistryConflict) as exc:
            logger.warning("Writing the markdown of %s not possible now: %s", sid, exc)
            return await self.release(sid, token)
        except RegistryError as exc:
            return await self.fail(sid, token, f"Schreiben abgelehnt: {exc}"[:500])
        if res.get("discarded"):
            self.stats["discarded"] += 1
            return await self.release(sid, token)
        await self._report(self.registry.done, sid, self.stage, token)
        self.stats["done"] += 1
        return "done"
