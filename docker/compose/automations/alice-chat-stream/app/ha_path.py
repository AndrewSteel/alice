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
# Routing decision
# ---------------------------------------------------------------------------
@dataclass
class HARouteDecision:
    path: str            # "HA_FAST" or "LLM_ONLY"
    parts: list[str]
    intents: list[IntentMatch]
    # PROJ-83 — shopping-list item text per part (None = not a shopping-list part).
    shopping_items: list[str | None] | None = None


async def decide_path(message: str, client: httpx.AsyncClient) -> HARouteDecision:
    """
    Project decision: only HA_FAST vs LLM_ONLY (no HYBRID).
    A request is HA_FAST iff every part either matched a Weaviate intent with
    certainty >= threshold OR is a recognised shopping-list command,
    AND no Weaviate error occurred.
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
    path = "HA_FAST" if (all_matched and not any_error) else "LLM_ONLY"
    return HARouteDecision(
        path=path, parts=parts, intents=intents, shopping_items=shopping_items
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


async def execute_ha_intents(
    intents: list[IntentMatch],
    client: httpx.AsyncClient,
    parts: list[str] | None = None,
    shopping_items: list[str | None] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """
    Execute every HA_FAST intent. Returns (response_text, results).

    `parts` and `shopping_items` are parallel to `intents` (PROJ-83): `parts`
    supplies the original text for per-intent value re-extraction, and a
    non-None `shopping_items[i]` marks part i as a shopping-list command.
    """
    if not HA_TOKEN:
        return ("HA_TOKEN fehlt. Bitte Umgebungsvariable setzen.", [])

    n = len(intents)
    parts = (parts or [""] * n)[:n] + [""] * max(0, n - len(parts or []))
    shopping_items = (shopping_items or [None] * n)[:n] + [None] * max(0, n - len(shopping_items or []))

    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }

    needs_confirmation = [i for i in intents if i.requires_confirmation]

    # Pair every intent with its text part / shopping flag.
    work = [
        (intent, part, shop)
        for intent, part, shop in zip(intents, parts, shopping_items)
        if not intent.requires_confirmation
    ]

    if not work and needs_confirmation:
        names = ", ".join(i.entity_id or i.domain or "?" for i in needs_confirmation)
        return (f'Bist du sicher? Ich soll {names} steuern. Bitte bestätige mit "Ja".', [])

    # Friendly names for all involved entities (PROJ-83 BUG-3 — nicer German
    # in success/range messages).
    friendly_names = await _load_friendly_names([i.entity_id for i, _, _ in work if i.entity_id])

    # --- Pass 1: resolve every value-bearing intent BEFORE any HA call, so a
    # missing number aborts the whole HA_FAST path without partial execution. ---
    resolved_by_idx: dict[int, dict[str, Any]] = {}
    for idx, (intent, part, shop) in enumerate(work):
        if shop is not None or not intent.service or "." not in intent.service:
            continue
        resolved = await _resolve_value(intent, part, headers, client, friendly_names)
        if not resolved["ok"] and resolved.get("fallback"):
            raise ValueError(
                f"value-bearing intent {intent.service} without a number in {part!r}"
            )
        resolved_by_idx[idx] = resolved

    results: list[dict[str, Any]] = []
    out_parts: list[str] = []

    for idx, (intent, part, shop) in enumerate(work):
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
        domain, _, service = intent.service.partition(".")
        url = f"{HA_URL}/api/services/{domain}/{service}"
        body = {"entity_id": intent.entity_id, **call_params}
        try:
            resp = await client.post(url, json=body, headers=headers, timeout=10.0)
            if 200 <= resp.status_code < 300:
                r = {"entity": intent.entity_id, "success": True,
                     "status": resp.status_code, "params": call_params}
                results.append(r)
                out_parts.append(_value_action_text(intent, call_params, friendly_names))
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
                out_parts.append(msg)
        except httpx.TimeoutException:
            msg = f"Zeitüberschreitung bei {intent.entity_id or intent.domain}."
            results.append({"entity": intent.entity_id, "success": False,
                            "error": "timeout", "msg": msg})
            out_parts.append(msg)
        except Exception as exc:
            msg = f"Netzwerkfehler bei {intent.entity_id or intent.domain}: {exc}"
            results.append({"entity": intent.entity_id, "success": False,
                            "error": "network", "msg": msg})
            out_parts.append(msg)

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
