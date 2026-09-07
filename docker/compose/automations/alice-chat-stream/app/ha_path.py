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
import math
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

# PROJ-83 — value-bearing intents. Maps (service, parameter-key present in the
# Weaviate match) to the value type we must re-extract from the spoken text.
# Percent types have fixed 0–100 bounds; temperature bounds are read live from HA.
_PERCENT_PARAM_KEYS = {"brightness_pct", "position", "value"}
_TEMPERATURE_PARAM_KEYS = {"temperature"}

# Shopping-list trigger phrases (PROJ-83 baustein 3). Everything before the
# trigger is taken verbatim as the item text.
_SHOPPING_LIST_RE = re.compile(
    r"^\s*(?:schreib(?:e)?\s+|setz(?:e)?\s+|pack(?:e)?\s+|füg(?:e)?\s+)?"
    r"(?P<item>.+?)"
    r"\s+(?:auf|zu|zur|zum|in|an)\s+"
    r"(?:(?:die|der|den|das|meine[rn]?|unsere[rn]?|unser)\s+)?"
    r"einkaufs(?:liste|zettel)"
    r"(?:\s+(?:hinzu(?:fügen)?|schreiben|setzen|packen|aufnehmen))?"
    r"\b.*$",
    re.IGNORECASE,
)
# Trailing verb that may remain after the trigger phrase (e.g. "... hinzufügen").
_SHOPPING_TRAILING_VERB_RE = re.compile(
    r"\s+(?:hinzu(?:fügen)?|schreiben|setzen|packen|aufnehmen)\s*$", re.IGNORECASE
)


def extract_numeric_value(text: str) -> int | None:
    """Extract the first numeric value from a spoken command part.

    Handles: plain digits ("50"), decimals with comma or dot ("21,5" → 22,
    commercial rounding), leading zeros ("050" → 50). Written-out number words
    ("fünfzig") are intentionally not supported — Whisper transcribes German
    numbers as digits. Returns None when no digit group is present.
    """
    m = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not m:
        return None
    raw = m.group(1).replace(",", ".")
    try:
        val = float(raw)
    except ValueError:
        return None
    # Commercial rounding (round-half-up), independent of Python's banker's rounding.
    return int(math.floor(val + 0.5))


def classify_value_type(service: str | None, parameters: dict[str, Any] | None) -> tuple[str, str] | None:
    """Classify a matched intent as value-bearing.

    Returns (value_type, parameter_key) where value_type is "percent" or
    "temperature", or None if the intent carries no re-extractable value.
    """
    params = parameters or {}
    for key in params:
        if key in _TEMPERATURE_PARAM_KEYS:
            return ("temperature", key)
    for key in params:
        if key in _PERCENT_PARAM_KEYS:
            return ("percent", key)
    # cover.set_cover_position may arrive with an empty parameters dict if the
    # template default_parameters were empty — key it off the service name.
    if service == "cover.set_cover_position":
        return ("percent", "position")
    return None


def detect_shopping_list_item(part: str) -> str | None:
    """Detect a 'add X to the shopping list' command and return the item text.

    Returns the free-text item (verbatim, incl. quantity like '2 Packungen
    Milch'), or None if the part is not a shopping-list command.
    """
    m = _SHOPPING_LIST_RE.match(part.strip())
    if not m:
        return None
    item = m.group("item").strip()
    item = _SHOPPING_TRAILING_VERB_RE.sub("", item).strip()
    # Strip a leading imperative verb the outer group didn't catch.
    item = re.sub(
        r"^(?:schreib(?:e)?|setz(?:e)?|pack(?:e)?|füg(?:e)?|nimm)\s+", "", item, flags=re.IGNORECASE
    ).strip()
    return item or None

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
# PROJ-84 — device-area context
# ---------------------------------------------------------------------------
def parse_device_room(source: str | None) -> str | None:
    """Extract the speaking device's room from the request `source`.

    `"esphome:Büro"` → `"Büro"`. The speech gateway replaces spaces in the room
    name with underscores (`wyoming_transport.py`), so they are restored here
    (`"esphome:Wohn_zimmer"` → `"Wohn zimmer"`). Plain `"esphome"`,
    `"webapp_cc"`, `"webapp_mic"` and `None` carry no room → `None`.
    """
    if not source or ":" not in source:
        return None
    prefix, _, room = source.partition(":")
    if prefix != "esphome":
        return None
    return room.strip().replace("_", " ") or None


async def _load_area_names() -> list[str]:
    """Distinct area_name values across all active entities."""
    from . import memory

    try:
        rows = await memory.pool().fetch(
            "SELECT DISTINCT area_name FROM alice.ha_entities "
            "WHERE area_name IS NOT NULL AND is_active = TRUE"
        )
    except Exception as exc:
        logger.warning("Area-name lookup failed: %s", exc)
        return []
    return [r["area_name"] for r in rows if r["area_name"]]


async def _load_entity_name_index() -> list[tuple[str, str]]:
    """(lowercased name, entity_id) for every active entity's friendly_name
    and each of its aliases — used for the 'text names a device' check."""
    from . import memory

    try:
        rows = await memory.pool().fetch(
            "SELECT entity_id, friendly_name, aliases FROM alice.ha_entities "
            "WHERE is_active = TRUE"
        )
    except Exception as exc:
        logger.warning("Entity-name index lookup failed: %s", exc)
        return []
    index: list[tuple[str, str]] = []
    for r in rows:
        if r["friendly_name"]:
            index.append((r["friendly_name"].lower(), r["entity_id"]))
        raw = r["aliases"]
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        for a in raw or []:
            if isinstance(a, str) and a:
                index.append((a.lower(), r["entity_id"]))
    return index


async def _load_area_entities(area_name: str, domain: str) -> list[str]:
    """All active entity_ids of `domain` in `area_name` (case-insensitive)."""
    from . import memory

    try:
        rows = await memory.pool().fetch(
            "SELECT entity_id FROM alice.ha_entities "
            "WHERE LOWER(area_name) = LOWER($1) AND domain = $2 AND is_active = TRUE "
            "ORDER BY entity_id",
            area_name,
            domain,
        )
    except Exception as exc:
        logger.warning("Area-entity lookup failed for %s/%s: %s", area_name, domain, exc)
        return []
    return [r["entity_id"] for r in rows if r["entity_id"]]


@dataclass
class AreaResolution:
    """Per-part outcome of the PROJ-84 precedence.

    mode:
      "entity" — text named a device; use the Weaviate single-entity match as-is
      "area"   — resolved to a room; `entity_ids` holds every target, `area` the room
      "ask"    — no room anywhere; Alice must ask back (`domain` for the question)
    """
    mode: str
    area: str | None = None
    entity_ids: list[str] | None = None
    domain: str | None = None


def _text_names_area(part: str, area_names: list[str]) -> str | None:
    low = part.lower()
    for a in area_names:
        if a.lower() in low:
            return a
    return None


def _text_names_entity(part: str, entity_index: list[tuple[str, str]]) -> bool:
    low = part.lower()
    return any(name in low for name, _ in entity_index)


# ---------------------------------------------------------------------------
# Routing decision
# ---------------------------------------------------------------------------
@dataclass
class HARouteDecision:
    path: str            # "HA_FAST" or "LLM_ONLY"
    parts: list[str]
    intents: list[IntentMatch]
    # PROJ-83 — shopping-list item text per part (None = not a shopping-list part).
    shopping_items: list[str | None] | None = None
    # PROJ-84 — per-part area resolution (None = not applicable, e.g. shopping list).
    area_targets: list[AreaResolution | None] | None = None


async def decide_path(
    message: str, client: httpx.AsyncClient, source: str | None = None
) -> HARouteDecision:
    """
    Project decision: only HA_FAST vs LLM_ONLY (no HYBRID).
    A request is HA_FAST iff every part either matched a Weaviate intent with
    certainty >= threshold OR is a recognised shopping-list command,
    AND no Weaviate error occurred.

    PROJ-84: for a matched part that names no device, the target entities are
    re-resolved from the named room, else the speaking device's room (`source`),
    else the part is marked for a room clarification.
    """
    parts = split_message(message)

    # PROJ-83 — shopping-list commands are free text and never match Weaviate;
    # detect them up front so a part is not misrouted to LLM_ONLY.
    shopping_items: list[str | None] = [detect_shopping_list_item(p) for p in parts]

    intents: list[IntentMatch] = []
    for p, shop in zip(parts, shopping_items):
        if shop is not None:
            # Placeholder — this part is handled by the shopping-list branch.
            intents.append(IntentMatch(matched=True, certainty=1.0, domain="todo"))
        else:
            intents.append(await lookup_intent(p, client))

    any_error = any(i.weaviate_error for i in intents)
    all_matched = bool(intents) and all(i.matched for i in intents)

    # --- PROJ-84 — area resolution per part ---
    device_room = parse_device_room(source)
    area_targets: list[AreaResolution | None] = [None] * len(parts)
    area_lookup_failed = False
    if all_matched and not any_error:
        needs_area = any(
            shop is None and i.domain and i.domain != "todo"
            for i, shop in zip(intents, shopping_items)
        )
        area_names = await _load_area_names() if needs_area else []
        entity_index = await _load_entity_name_index() if needs_area else []
        for idx, (p, shop, intent) in enumerate(zip(parts, shopping_items, intents)):
            if shop is not None or not intent.domain or intent.domain == "todo":
                continue
            if _text_names_entity(p, entity_index):
                area_targets[idx] = AreaResolution(mode="entity")
                continue
            named = _text_names_area(p, area_names)
            room = named or device_room
            if room is None:
                area_targets[idx] = AreaResolution(mode="ask", domain=intent.domain)
                continue
            ids = await _load_area_entities(room, intent.domain)
            if not ids:
                # Room known but no entity of this domain there → treat the part
                # as an overall non-match, fall back to LLM (spec AC).
                area_lookup_failed = True
                break
            area_targets[idx] = AreaResolution(
                mode="area", area=room, entity_ids=ids, domain=intent.domain
            )

    path = (
        "HA_FAST"
        if (all_matched and not any_error and not area_lookup_failed)
        else "LLM_ONLY"
    )
    return HARouteDecision(
        path=path, parts=parts, intents=intents, shopping_items=shopping_items,
        area_targets=area_targets,
    )


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


def _entity_label(intent: IntentMatch, friendly_names: dict[str, str] | None = None) -> str:
    """Human-readable entity label.

    Prefers the HA friendly name from alice.ha_entities (PROJ-83 BUG-3 —
    "HT Büro" instead of "Ht buro"); falls back to the entity_id slug.
    """
    if friendly_names and intent.entity_id:
        fn = friendly_names.get(intent.entity_id)
        if fn:
            return fn
    raw = intent.entity_id or intent.domain or "Aktion"
    name = raw.split(".")[-1].replace("_", " ")
    return name[:1].upper() + name[1:]


async def _load_friendly_names(entity_ids: list[str]) -> dict[str, str]:
    """Look up friendly names for a batch of entity_ids from alice.ha_entities."""
    ids = [e for e in entity_ids if e]
    if not ids:
        return {}
    from . import memory

    try:
        rows = await memory.pool().fetch(
            "SELECT entity_id, friendly_name FROM alice.ha_entities "
            "WHERE entity_id = ANY($1::text[]) AND friendly_name IS NOT NULL",
            ids,
        )
    except Exception as exc:
        logger.warning("Friendly-name lookup failed: %s", exc)
        return {}
    return {r["entity_id"]: r["friendly_name"] for r in rows}


# ---------------------------------------------------------------------------
# PROJ-83 — value re-extraction, range checks, shopping list
# ---------------------------------------------------------------------------
async def _fetch_temp_range(entity_id: str, headers: dict, client: httpx.AsyncClient) -> tuple[float, float] | None:
    """Read min_temp/max_temp for a climate entity from HA. None on any failure."""
    try:
        resp = await client.get(
            f"{HA_URL}/api/states/{entity_id}", headers=headers, timeout=10.0
        )
        if not (200 <= resp.status_code < 300):
            return None
        attrs = (resp.json() or {}).get("attributes") or {}
        lo, hi = attrs.get("min_temp"), attrs.get("max_temp")
        if lo is None or hi is None:
            return None
        return (float(lo), float(hi))
    except Exception as exc:
        logger.warning("Temp-range fetch failed for %s: %s", entity_id, exc)
        return None


def _fmt_num(n: float) -> str:
    """5.0 -> '5', 5.5 -> '5,5' (German decimal comma)."""
    if float(n).is_integer():
        return str(int(n))
    return f"{n:.1f}".replace(".", ",")


async def _resolve_value(
    intent: IntentMatch, part: str, headers: dict, client: httpx.AsyncClient,
    friendly_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Resolve the exact spoken value for a value-bearing intent.

    Returns one of:
      {"ok": True, "params": {...}}          -> merge into the HA call body
      {"ok": False, "fallback": True}        -> no number found; abort HA_FAST
      {"ok": False, "range_msg": "..."}      -> value out of range; German reply
    """
    vt = classify_value_type(intent.service, intent.parameters)
    if vt is None:
        return {"ok": True, "params": dict(intent.parameters or {})}

    value_type, param_key = vt
    value = extract_numeric_value(part)
    if value is None:
        return {"ok": False, "fallback": True}

    label = _entity_label(intent, friendly_names)
    if value_type == "percent":
        if not (0 <= value <= 100):
            return {
                "ok": False,
                "range_msg": f"{label} lässt sich nur zwischen 0 und 100 Prozent einstellen.",
            }
        return {"ok": True, "params": {**(intent.parameters or {}), param_key: value}}

    # temperature — live bounds from HA
    rng = await _fetch_temp_range(intent.entity_id or "", headers, client)
    if rng is None:
        # Bounds unknown — accept the value rather than block a valid command.
        return {"ok": True, "params": {**(intent.parameters or {}), param_key: value}}
    lo, hi = rng
    if not (lo <= value <= hi):
        return {
            "ok": False,
            "range_msg": (
                f"{label} lässt sich nur zwischen {_fmt_num(lo)} und {_fmt_num(hi)} Grad einstellen."
            ),
        }
    return {"ok": True, "params": {**(intent.parameters or {}), param_key: value}}


async def _add_shopping_list_item(
    item: str, headers: dict, client: httpx.AsyncClient
) -> dict[str, Any]:
    """Add a free-text item to the first active todo entity."""
    from . import memory

    try:
        row = await memory.pool().fetchrow(
            "SELECT entity_id FROM alice.ha_entities "
            "WHERE domain = 'todo' AND is_active = TRUE "
            "ORDER BY entity_id LIMIT 1"
        )
    except Exception as exc:
        logger.warning("Shopping-list entity lookup failed: %s", exc)
        return {"success": False, "msg": "Ich konnte die Einkaufsliste gerade nicht erreichen."}

    if not row or not row["entity_id"]:
        return {"success": False, "msg": "Es ist keine Einkaufsliste für Alice freigegeben."}

    entity_id = row["entity_id"]
    try:
        resp = await client.post(
            f"{HA_URL}/api/services/todo/add_item",
            json={"entity_id": entity_id, "item": item},
            headers=headers,
            timeout=10.0,
        )
        if 200 <= resp.status_code < 300:
            return {"success": True, "entity": entity_id, "item": item,
                    "msg": f"„{item}“ auf die Einkaufsliste gesetzt."}
        return {"success": False, "entity": entity_id,
                "msg": f"Ich konnte „{item}“ nicht auf die Einkaufsliste setzen (HTTP {resp.status_code})."}
    except httpx.TimeoutException:
        return {"success": False, "entity": entity_id,
                "msg": "Zeitüberschreitung beim Eintrag auf die Einkaufsliste."}
    except Exception as exc:
        return {"success": False, "entity": entity_id,
                "msg": f"Netzwerkfehler beim Eintrag auf die Einkaufsliste: {exc}"}


async def _do_service_call(
    entity_id: str | None, service: str, call_params: dict[str, Any],
    headers: dict, client: httpx.AsyncClient, label: str,
) -> dict[str, Any]:
    """Single HA REST service call for one entity. Returns a per-entity result."""
    domain, _, svc = service.partition(".")
    url = f"{HA_URL}/api/services/{domain}/{svc}"
    body = {"entity_id": entity_id, **call_params}
    try:
        resp = await client.post(url, json=body, headers=headers, timeout=10.0)
        if 200 <= resp.status_code < 300:
            return {"entity": entity_id, "success": True,
                    "status": resp.status_code, "params": call_params}
        err = "auth" if resp.status_code == 401 else "notfound" if resp.status_code == 404 else "unknown"
        msg = (
            "HA-Verbindung fehlgeschlagen, bitte Token prüfen." if err == "auth"
            else f"Ich konnte {label} nicht finden." if err == "notfound"
            else f"Fehler bei {label}: HTTP {resp.status_code}"
        )
        return {"entity": entity_id, "success": False,
                "status": resp.status_code, "error": err, "msg": msg}
    except httpx.TimeoutException:
        return {"entity": entity_id, "success": False, "error": "timeout",
                "msg": f"Zeitüberschreitung bei {label}."}
    except Exception as exc:
        return {"entity": entity_id, "success": False, "error": "network",
                "msg": f"Netzwerkfehler bei {label}: {exc}"}


_DOMAIN_NOUNS = {
    "light": "das Licht", "cover": "die Rolladen", "switch": "den Schalter",
    "climate": "die Heizung", "lock": "das Schloss", "media_player": "den Fernseher",
    "vacuum": "den Staubsauger", "fan": "den Ventilator",
}
# Nominative noun for a domain, used to open a room-scoped sentence.
_DOMAIN_SUBJECT = {
    "light": "Licht", "cover": "Rolladen", "switch": "Schalter",
    "climate": "Heizung", "lock": "Schloss", "media_player": "Fernseher",
    "vacuum": "Staubsauger", "fan": "Ventilator",
}
# German room names that take "in der" instead of "im". Everything else → "im"
# (covers the common neuter/masculine rooms: Büro, Wohnzimmer, Bad, Flur, …).
_FEMININE_ROOMS = {
    "küche", "werkstatt", "garage", "toilette", "diele", "waschküche",
    "kammer", "abstellkammer", "speisekammer", "bibliothek", "sauna",
}


def _room_dat(room: str) -> str:
    """Dative room phrase: 'im Büro' / 'in der Küche'."""
    if room.lower() in _FEMININE_ROOMS:
        return f"in der {room}"
    return f"im {room}"


def _room_question(domains: list[str]) -> str:
    """German clarification when no room is known (PROJ-84 stage 4)."""
    noun = _DOMAIN_NOUNS.get(domains[0], "das") if len(set(domains)) == 1 else "das"
    return f"In welchem Raum möchtest du {noun} steuern?"


def _fail_reason(r: dict[str, Any]) -> str:
    err = r.get("error")
    if err == "timeout":
        return "nicht erreichbar"
    if err == "notfound":
        return "nicht gefunden"
    if r.get("range_error"):
        return "Wert außerhalb des Bereichs"
    return "nicht erreichbar"


def _area_message(area: str, domain: str | None, service: str | None,
                  params: dict[str, Any], ok_labels: list[str],
                  failed: list[tuple[str, str]]) -> str:
    """One room-scoped line for a multi-entity area call (PROJ-84).

    `failed` is a list of (label, reason) pairs. Example outputs:
      "Licht im Büro eingeschaltet."
      "Heizung in der Küche auf 21 Grad gestellt, außer Küche Süd (nur 5–28 Grad)."
    """
    subject = _DOMAIN_SUBJECT.get(domain or "", "")
    where = _room_dat(area)
    if "temperature" in params:
        did = f"Heizung {where} auf {_fmt_num(params['temperature'])} Grad gestellt"
    elif any(k in params for k in ("brightness_pct", "position", "value")):
        v = next(params[k] for k in ("brightness_pct", "position", "value") if k in params)
        head = f"{subject} {where}" if subject else where[0].upper() + where[1:]
        did = f"{head} auf {int(v)} Prozent gestellt"
    else:
        head = f"{subject} {where}" if subject else where[0].upper() + where[1:]
        did = f"{head} {_action_text(service)}"
    if not failed:
        return f"{did}."
    fail_str = ", ".join(f"{lbl} ({why})" for lbl, why in failed)
    if not ok_labels:
        subj = f"{subject} {where}" if subject else where[0].upper() + where[1:]
        return f"{subj}: nichts hat geklappt — {fail_str}."
    return f"{did}, außer {fail_str}."


async def execute_ha_intents(
    intents: list[IntentMatch],
    client: httpx.AsyncClient,
    parts: list[str] | None = None,
    shopping_items: list[str | None] | None = None,
    area_targets: list[AreaResolution | None] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Execute every HA_FAST intent. Returns (response_text, results).

    `parts` and `shopping_items` are parallel to `intents` (PROJ-83): `parts`
    supplies the original text for per-intent value re-extraction, and a
    non-None `shopping_items[i]` marks part i as a shopping-list command.

    `area_targets` is parallel to `intents` (PROJ-84): a non-None entry with
    mode "area" expands the call to every entity in a room; mode "ask" means the
    room is unknown and Alice returns a clarification question instead.
    """
    if not HA_TOKEN:
        return ("HA_TOKEN fehlt. Bitte Umgebungsvariable setzen.", [])

    n = len(intents)
    parts = (parts or [""] * n)[:n] + [""] * max(0, n - len(parts or []))
    shopping_items = (shopping_items or [None] * n)[:n] + [None] * max(0, n - len(shopping_items or []))
    area_targets = (area_targets or [None] * n)[:n] + [None] * max(0, n - len(area_targets or []))

    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }

    # --- PROJ-84 — room unknown for at least one part: ask, execute nothing. ---
    ask_domains = [
        at.domain for at in area_targets if at is not None and at.mode == "ask"
    ]
    if ask_domains:
        return (_room_question(ask_domains), [])

    needs_confirmation = [i for i in intents if i.requires_confirmation]

    # Pair every intent with its text part / shopping flag / area target.
    work = [
        (intent, part, shop, area)
        for intent, part, shop, area in zip(intents, parts, shopping_items, area_targets)
        if not intent.requires_confirmation
    ]

    if not work and needs_confirmation:
        names = ", ".join(i.entity_id or i.domain or "?" for i in needs_confirmation)
        return (f'Bist du sicher? Ich soll {names} steuern. Bitte bestätige mit "Ja".', [])

    # PROJ-84 — for area parts, the target entity_ids come from the room lookup,
    # not from the single Weaviate match.
    def _targets(intent: IntentMatch, area: AreaResolution | None) -> list[str | None]:
        if area is not None and area.mode == "area":
            return list(area.entity_ids or [])
        return [intent.entity_id]

    all_entity_ids = [
        e for i, _, _, a in work for e in _targets(i, a) if e
    ]
    # Friendly names for all involved entities (PROJ-83 BUG-3 — nicer German
    # in success/range messages).
    friendly_names = await _load_friendly_names(all_entity_ids)

    # --- Pass 1: resolve every value-bearing intent BEFORE any HA call, so a
    # missing number aborts the whole HA_FAST path without partial execution.
    # Area parts are resolved per target entity in the area branch below — here
    # they only get the "number present?" check (range checks need the real
    # room entities, not the arbitrary Weaviate match). ---
    resolved_by_idx: dict[int, dict[str, Any]] = {}
    for idx, (intent, part, shop, area) in enumerate(work):
        if shop is not None or not intent.service or "." not in intent.service:
            continue
        is_area = area is not None and area.mode == "area"
        vt = classify_value_type(intent.service, intent.parameters)
        if is_area and vt is not None:
            if extract_numeric_value(part) is None:
                raise ValueError(
                    f"value-bearing intent {intent.service} without a number in {part!r}"
                )
            resolved_by_idx[idx] = {"ok": True, "params": dict(intent.parameters or {})}
            continue
        resolved = await _resolve_value(intent, part, headers, client, friendly_names)
        if not resolved["ok"] and resolved.get("fallback"):
            raise ValueError(
                f"value-bearing intent {intent.service} without a number in {part!r}"
            )
        resolved_by_idx[idx] = resolved

    results: list[dict[str, Any]] = []
    out_parts: list[str] = []

    for idx, (intent, part, shop, area) in enumerate(work):
        # --- Shopping-list branch (PROJ-83 baustein 3) ---
        if shop is not None:
            r = await _add_shopping_list_item(shop, headers, client)
            results.append(r)
            out_parts.append(r.get("msg") or ("Erledigt." if r.get("success") else "Fehler."))
            continue

        if not intent.service or "." not in intent.service:
            r = {"entity": intent.entity_id, "success": False,
                 "msg": f"Ungültiger Service: {intent.service}"}
            results.append(r)
            out_parts.append(r["msg"])
            continue

        # --- Value re-extraction + range check (PROJ-83 baustein 1 & 2) ---
        resolved = resolved_by_idx[idx]
        if not resolved["ok"]:
            r = {"entity": intent.entity_id, "success": False,
                 "range_error": True, "msg": resolved["range_msg"]}
            results.append(r)
            out_parts.append(r["msg"])
            continue

        call_params = resolved["params"]
        targets = _targets(intent, area)

        # --- PROJ-84 area branch: one call per entity, one room-scoped line ---
        if area is not None and area.mode == "area":
            vt = classify_value_type(intent.service, intent.parameters)
            spoken_value = extract_numeric_value(part) if vt else None
            room = area.area or ""

            # Universal 0–100 percent bounds — reject once, room-scoped, no call.
            if vt and vt[0] == "percent" and spoken_value is not None \
                    and not (0 <= spoken_value <= 100):
                subject = _DOMAIN_SUBJECT.get(intent.domain or "", "")
                head = f"{subject} {_room_dat(room)}" if subject \
                    else _room_dat(room)[:1].upper() + _room_dat(room)[1:]
                r = {"entity": None, "success": False, "range_error": True,
                     "msg": f"{head} lässt sich nur zwischen 0 und 100 Prozent einstellen."}
                results.append(r)
                out_parts.append(r["msg"])
                continue

            ok_labels: list[str] = []
            failed: list[tuple[str, str]] = []
            for eid in targets:
                label = friendly_names.get(eid, eid) if eid else "?"
                params_for_eid = call_params
                if vt and spoken_value is not None and eid:
                    if vt[0] == "temperature":
                        # Per-entity live bounds (spec edge case).
                        rng = await _fetch_temp_range(eid, headers, client)
                        if rng and not (rng[0] <= spoken_value <= rng[1]):
                            why = f"nur {_fmt_num(rng[0])}–{_fmt_num(rng[1])} Grad"
                            results.append({"entity": eid, "success": False,
                                            "range_error": True, "msg": f"{label}: {why}"})
                            failed.append((label, why))
                            continue
                    params_for_eid = {**call_params, vt[1]: spoken_value}
                r = await _do_service_call(
                    eid, intent.service, params_for_eid, headers, client, label
                )
                results.append(r)
                if r.get("success"):
                    ok_labels.append(label)
                else:
                    failed.append((label, _fail_reason(r)))
            merged_params = (
                {**call_params, vt[1]: spoken_value}
                if vt and spoken_value is not None else call_params
            )
            out_parts.append(
                _area_message(room, intent.domain, intent.service, merged_params,
                              ok_labels, failed)
            )
            continue

        # --- Single-entity branch (named device / Weaviate match) ---
        label = _entity_label(intent, friendly_names)
        r = await _do_service_call(
            intent.entity_id, intent.service, call_params, headers, client, label
        )
        results.append(r)
        if r.get("success"):
            out_parts.append(_value_action_text(intent, call_params, friendly_names))
        else:
            out_parts.append(r.get("msg") or f"Fehler bei {label}.")

    if needs_confirmation:
        names = ", ".join(i.entity_id or i.domain or "?" for i in needs_confirmation)
        out_parts.append(f"Für {names} benötige ich noch deine Bestätigung.")

    return (" ".join(out_parts) or "Erledigt.", results)


def _value_action_text(
    intent: IntentMatch, params: dict[str, Any], friendly_names: dict[str, str] | None = None
) -> str:
    """German confirmation line for a successful value-bearing call."""
    label = _entity_label(intent, friendly_names)
    if "temperature" in params:
        return f"{label} auf {_fmt_num(params['temperature'])} Grad gestellt."
    for key in ("brightness_pct", "position", "value"):
        if key in params:
            return f"{label} auf {int(params[key])} Prozent gestellt."
    return f"{label} {_action_text(intent.service)}."
