"""
HA Fast-Path — fully implemented in Python (no n8n call).

Pipeline:
  1. Split the user message into command parts (German connectors)
  2. For each part: nearText query against Weaviate HAIntent
  3. If EVERY part matches with certainty >= INTENT_MIN_CERTAINTY → HA_FAST
     Otherwise → LLM_ONLY (no HYBRID per project decision)
  4. On HA_FAST: POST to HA REST API for each non-confirmation intent
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger("alice-chat-stream.ha_path")

WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "http://weaviate:8080").rstrip("/")
HA_URL = os.environ.get("HA_URL", "http://homeassistant:8123").rstrip("/")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
INTENT_MIN_CERTAINTY = float(os.environ.get("INTENT_MIN_CERTAINTY", "0.82"))
INTENT_MAX_RESULTS = int(os.environ.get("INTENT_MAX_RESULTS", "5"))

CONFIRMATION_DOMAINS = {"lock", "alarm_control_panel"}

_SPLITTERS = [
    "und dann", "und danach", "und außerdem",
    "und", "dann", "danach", "außerdem", "sowie", "zusätzlich", "auch noch",
]
_FILLER_RE = re.compile(r"^(bitte|mal|noch|auch|doch|kurz)\s+", re.IGNORECASE)
_PUNCT_RE = re.compile(r"[,\.;]+")


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------
def split_message(text: str) -> list[str]:
    """Split a user message into command parts. Mirrors the n8n splitter."""
    parts: list[str] = [text]
    for sep in _SPLITTERS:
        rx = re.compile(rf"\b{re.escape(sep)}\b", re.IGNORECASE)
        new_parts: list[str] = []
        for p in parts:
            new_parts.extend(rx.split(p))
        parts = new_parts
    final: list[str] = []
    for p in parts:
        for sub in _PUNCT_RE.split(p):
            sub = sub.strip()
            # Strip leading fillers iteratively
            prev = ""
            while sub != prev:
                prev = sub
                sub = _FILLER_RE.sub("", sub).strip()
            if len(sub) >= 4:
                final.append(sub)
    return final or [text.strip()]


# ---------------------------------------------------------------------------
# Weaviate nearText for HAIntent
# ---------------------------------------------------------------------------
@dataclass
class IntentMatch:
    matched: bool
    certainty: float
    entity_id: str | None = None
    domain: str | None = None
    service: str | None = None
    parameters: dict[str, Any] | None = None
    intent_template: str | None = None
    requires_confirmation: bool = False
    weaviate_error: bool = False


def _safe_concept(s: str) -> str:
    return (
        s.replace("\\", "\\\\")
        .replace('"', "'")
        .replace("\n", " ")
        .replace("\r", " ")
        .replace("\t", " ")
    )[:500]


def _parse_parameters(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            v = json.loads(raw)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}
    return {}


async def lookup_intent(part: str, client: httpx.AsyncClient) -> IntentMatch:
    """
    nearText query for a single command part. Returns the best match if its
    certainty meets the threshold, otherwise IntentMatch(matched=False).
    """
    concept = _safe_concept(part)
    gql = (
        '{ Get { HAIntent('
        f'nearText: {{ concepts: ["{concept}"] }} '
        f'limit: {INTENT_MAX_RESULTS}'
        ') { utterance entityId domain service parameters intentTemplate _additional { certainty } } } }'
    )

    try:
        resp = await client.post(
            f"{WEAVIATE_URL}/v1/graphql",
            json={"query": gql},
            headers={"Content-Type": "application/json"},
        )
        data = resp.json()
    except Exception as exc:
        logger.warning("Weaviate HAIntent lookup failed for %r: %s", part, exc)
        return IntentMatch(matched=False, certainty=0.0, weaviate_error=True)

    candidates = (data.get("data") or {}).get("Get", {}).get("HAIntent") or []
    qualified = sorted(
        [c for c in candidates if (c.get("_additional") or {}).get("certainty", 0.0) >= INTENT_MIN_CERTAINTY],
        key=lambda c: c["_additional"]["certainty"],
        reverse=True,
    )
    if not qualified:
        top = (candidates[0]["_additional"]["certainty"] if candidates else 0.0)
        return IntentMatch(matched=False, certainty=top)

    best = qualified[0]
    domain = best.get("domain") or ""
    return IntentMatch(
        matched=True,
        certainty=best["_additional"]["certainty"],
        entity_id=best.get("entityId"),
        domain=domain,
        service=best.get("service"),
        parameters=_parse_parameters(best.get("parameters")),
        intent_template=best.get("intentTemplate"),
        requires_confirmation=domain in CONFIRMATION_DOMAINS,
    )


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------
@dataclass
class HARouteDecision:
    path: str            # "HA_FAST" or "LLM_ONLY"
    parts: list[str]
    intents: list[IntentMatch]


async def decide_path(message: str, client: httpx.AsyncClient) -> HARouteDecision:
    """
    Project decision: only HA_FAST vs LLM_ONLY (no HYBRID).
    A request is HA_FAST iff every part matched with certainty >= threshold
    AND no Weaviate error occurred.
    """
    parts = split_message(message)
    intents: list[IntentMatch] = []
    for p in parts:
        intents.append(await lookup_intent(p, client))

    any_error = any(i.weaviate_error for i in intents)
    all_matched = bool(intents) and all(i.matched for i in intents)
    path = "HA_FAST" if (all_matched and not any_error) else "LLM_ONLY"
    return HARouteDecision(path=path, parts=parts, intents=intents)


# ---------------------------------------------------------------------------
# HA REST execution
# ---------------------------------------------------------------------------
def _action_text(service: str | None) -> str:
    s = service or ""
    if "turn_on" in s: return "eingeschaltet"
    if "turn_off" in s: return "ausgeschaltet"
    if "open" in s: return "geöffnet"
    if "close" in s: return "geschlossen"
    if "start" in s: return "gestartet"
    if "stop" in s: return "gestoppt"
    if "return" in s: return "zurückgeschickt"
    if "lock" in s: return "gesperrt"
    if "unlock" in s: return "entsperrt"
    if "arm" in s: return "scharf geschaltet"
    if "disarm" in s: return "deaktiviert"
    if "set_temperature" in s: return "eingestellt"
    return "ausgeführt"


def _entity_label(intent: IntentMatch) -> str:
    raw = intent.entity_id or intent.domain or "Aktion"
    name = raw.split(".")[-1].replace("_", " ")
    return name[:1].upper() + name[1:]


async def execute_ha_intents(
    intents: list[IntentMatch],
    client: httpx.AsyncClient,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Call HA REST for every non-confirmation intent. Returns (response_text, results).
    """
    if not HA_TOKEN:
        return ("HA_TOKEN fehlt. Bitte Umgebungsvariable setzen.", [])

    needs_confirmation = [i for i in intents if i.requires_confirmation]
    executable = [i for i in intents if not i.requires_confirmation]

    if not executable and needs_confirmation:
        names = ", ".join(i.entity_id or i.domain or "?" for i in needs_confirmation)
        return (f'Bist du sicher? Ich soll {names} steuern. Bitte bestätige mit "Ja".', [])

    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }

    results: list[dict[str, Any]] = []
    for intent in executable:
        if not intent.service or "." not in intent.service:
            results.append({
                "entity": intent.entity_id, "success": False,
                "msg": f"Ungültiger Service: {intent.service}",
            })
            continue
        domain, _, service = intent.service.partition(".")
        url = f"{HA_URL}/api/services/{domain}/{service}"
        body = {"entity_id": intent.entity_id, **(intent.parameters or {})}
        try:
            resp = await client.post(url, json=body, headers=headers, timeout=10.0)
            if 200 <= resp.status_code < 300:
                results.append({"entity": intent.entity_id, "success": True, "status": resp.status_code})
            else:
                err = "auth" if resp.status_code == 401 else "notfound" if resp.status_code == 404 else "unknown"
                msg = (
                    "HA-Verbindung fehlgeschlagen, bitte Token prüfen." if err == "auth"
                    else f"Ich konnte {intent.entity_id or intent.domain} nicht finden." if err == "notfound"
                    else f"Fehler bei {intent.entity_id or intent.domain}: HTTP {resp.status_code}"
                )
                results.append({
                    "entity": intent.entity_id, "success": False,
                    "status": resp.status_code, "error": err, "msg": msg,
                })
        except httpx.TimeoutException:
            results.append({
                "entity": intent.entity_id, "success": False,
                "error": "timeout", "msg": f"Zeitüberschreitung bei {intent.entity_id or intent.domain}.",
            })
        except Exception as exc:
            results.append({
                "entity": intent.entity_id, "success": False,
                "error": "network", "msg": f"Netzwerkfehler bei {intent.entity_id or intent.domain}: {exc}",
            })

    parts: list[str] = []
    for r, intent in zip(results, executable):
        if r["success"]:
            parts.append(f"{_entity_label(intent)} {_action_text(intent.service)}.")
        else:
            parts.append(r.get("msg") or "Fehler.")

    if needs_confirmation:
        names = ", ".join(i.entity_id or i.domain or "?" for i in needs_confirmation)
        parts.append(f"Für {names} benötige ich noch deine Bestätigung.")

    return (" ".join(parts) or "Erledigt.", results)
