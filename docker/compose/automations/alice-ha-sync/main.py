"""
alice-ha-sync: MQTT-driven HA entity sync worker.

Replaces the n8n workflow alice-ha-intent-sync (PROJ-4) with a pure Python
implementation. Subscribes to MQTT topic alice/ha/sync and syncs HA entities
to PostgreSQL (alice.ha_entities) and Weaviate (HAIntent collection).

Event types:
  ha_start          -> Full sync of all entities
  templates_updated -> Full sync (re-generate all utterances)
  entity_created    -> Incremental sync for a single entity
  entity_removed    -> Remove entity from Weaviate + deactivate in PG
"""

import asyncio
import json
import logging
import os
import queue
import re
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import paho.mqtt.client as mqtt
import psycopg2
import psycopg2.extras
import requests
import websockets
import weaviate
from weaviate.classes.query import Filter

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("alice-ha-sync")

# ---------------------------------------------------------------------------
# Configuration (all from environment variables, never hardcoded)
# ---------------------------------------------------------------------------
HA_URL = os.environ.get("HA_URL", "")
HA_TOKEN = os.environ.get("HA_TOKEN", "")
MQTT_URL = os.environ.get("MQTT_URL", "")
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "")
POSTGRES_CONNECTION = os.environ.get("POSTGRES_CONNECTION", "")
WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "")
CERTAINTY_THRESHOLD = float(os.environ.get("CERTAINTY_THRESHOLD", "0.82"))

MQTT_SUBSCRIBE_TOPIC = "alice/ha/sync"
MQTT_INFO_TOPIC = "alice/system/ha-sync/info"
MQTT_WARNING_TOPIC = "alice/system/ha-sync/warning"
MQTT_ERROR_TOPIC = "alice/system/ha-sync/error"

WEAVIATE_BATCH_SIZE = 100
HEARTBEAT_FILE = "/tmp/heartbeat"
HEARTBEAT_INTERVAL = 30  # seconds

# ---------------------------------------------------------------------------
# Validate required config
# ---------------------------------------------------------------------------
_REQUIRED_VARS = {
    "HA_URL": HA_URL,
    "HA_TOKEN": HA_TOKEN,
    "MQTT_URL": MQTT_URL,
    "MQTT_USER": MQTT_USER,
    "MQTT_PASSWORD": MQTT_PASSWORD,
    "POSTGRES_CONNECTION": POSTGRES_CONNECTION,
    "WEAVIATE_URL": WEAVIATE_URL,
}

for var_name, var_value in _REQUIRED_VARS.items():
    if not var_value:
        logger.error("Required environment variable %s is not set", var_name)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# MQTT Client (persistent connection)
# ---------------------------------------------------------------------------
class MQTTClient:
    """Persistent MQTT client with automatic reconnect and publish capability."""

    def __init__(self, url: str, username: str, password: str, event_queue: queue.Queue):
        parsed = urlparse(url)
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 1883
        self.username = username or parsed.username
        self.password = password or parsed.password
        self.event_queue = event_queue
        self._connected = False

        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="alice-ha-sync",
            protocol=mqtt.MQTTv311,
        )
        if self.username:
            self.client.username_pw_set(self.username, self.password)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)

    def connect(self):
        """Connect to broker and start network loop in background thread."""
        logger.info("Connecting to MQTT broker %s:%d", self.host, self.port)
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            logger.info("MQTT connected, subscribing to %s", MQTT_SUBSCRIBE_TOPIC)
            client.subscribe(MQTT_SUBSCRIBE_TOPIC, qos=1)
            self._connected = True
        else:
            logger.error("MQTT connection failed with code %d", rc)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self._connected = False
        if rc != 0:
            logger.warning("MQTT disconnected unexpectedly (rc=%d), will auto-reconnect", rc)

    def _on_message(self, client, userdata, msg):
        """Parse MQTT message and enqueue for processing."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Invalid MQTT payload: %s", e)
            return

        if not isinstance(payload, dict) or "event" not in payload:
            logger.warning("MQTT payload missing 'event' field: %s", payload)
            return

        logger.info("Received MQTT event: %s", payload.get("event"))
        self.event_queue.put(payload)

    def publish(self, topic: str, payload: dict):
        """Publish a JSON message to a topic."""
        try:
            result = self.client.publish(
                topic, json.dumps(payload), qos=1, retain=False
            )
            result.wait_for_publish(timeout=10)
        except Exception as e:
            logger.error("Failed to publish to %s: %s", topic, e)

    @property
    def is_connected(self) -> bool:
        return self._connected


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------
def get_db_connection():
    """Create a new PostgreSQL connection."""
    return psycopg2.connect(POSTGRES_CONNECTION)


def crash_recovery():
    """Mark stale 'running' sync log entries as 'error' (crash recovery)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE alice.ha_sync_log
                SET status = 'error',
                    error_message = 'Worker crashed during sync (recovered on restart)',
                    completed_at = NOW(),
                    duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
                WHERE status = 'running'
                  AND started_at < NOW() - INTERVAL '5 minutes'
                """
            )
            affected = cur.rowcount
            conn.commit()
        if affected > 0:
            logger.info("Crash recovery: marked %d stale sync entries as error", affected)
    except Exception as e:
        logger.error("Crash recovery failed: %s", e)
    finally:
        if conn:
            conn.close()


def check_concurrent_sync() -> bool:
    """Return True if a sync is already running (< 5 min old)."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM alice.ha_sync_log
                WHERE status = 'running'
                  AND started_at > NOW() - INTERVAL '5 minutes'
                LIMIT 1
                """
            )
            row = cur.fetchone()
        return row is not None
    except Exception as e:
        logger.error("Concurrent sync check failed: %s", e)
        return False
    finally:
        if conn:
            conn.close()


def create_sync_log(sync_type: str, trigger_source: str) -> int | None:
    """Insert a new sync log entry with status 'running'. Returns the log id."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alice.ha_sync_log (sync_type, trigger_source, status, started_at)
                VALUES (%s, %s, 'running', NOW())
                RETURNING id
                """,
                (sync_type, trigger_source),
            )
            log_id = cur.fetchone()[0]
            conn.commit()
        return log_id
    except Exception as e:
        logger.error("Failed to create sync log: %s", e)
        return None
    finally:
        if conn:
            conn.close()


def update_sync_log(
    log_id: int,
    status: str,
    entities_found: int = 0,
    entities_added: int = 0,
    entities_updated: int = 0,
    entities_removed: int = 0,
    intents_generated: int = 0,
    intents_removed: int = 0,
    error_message: str | None = None,
    details: dict | None = None,
):
    """Update an existing sync log entry."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE alice.ha_sync_log
                SET status = %s,
                    entities_found = %s,
                    entities_added = %s,
                    entities_updated = %s,
                    entities_removed = %s,
                    intents_generated = %s,
                    intents_removed = %s,
                    error_message = %s,
                    details = %s,
                    completed_at = NOW(),
                    duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000
                WHERE id = %s
                """,
                (
                    status,
                    entities_found,
                    entities_added,
                    entities_updated,
                    entities_removed,
                    intents_generated,
                    intents_removed,
                    error_message[:500] if error_message else None,
                    json.dumps(details) if details else "{}",
                    log_id,
                ),
            )
            conn.commit()
    except Exception as e:
        logger.error("Failed to update sync log %d: %s", log_id, e)
    finally:
        if conn:
            conn.close()


def load_templates(domain: str | None = None) -> list[dict]:
    """Load active intent templates from PostgreSQL. If domain is None, load all."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if domain:
                cur.execute(
                    """
                    SELECT domain, intent, service, patterns, default_parameters, language
                    FROM alice.ha_intent_templates
                    WHERE is_active = true AND domain = %s
                    ORDER BY priority DESC
                    """,
                    (domain,),
                )
            else:
                cur.execute(
                    """
                    SELECT domain, intent, service, patterns, default_parameters, language
                    FROM alice.ha_intent_templates
                    WHERE is_active = true
                    ORDER BY domain, priority DESC
                    """
                )
            rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error("Failed to load templates: %s", e)
        return []
    finally:
        if conn:
            conn.close()


def load_existing_entities() -> dict[str, dict]:
    """Load all active entities from PostgreSQL as a dict keyed by entity_id."""
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT entity_id, friendly_name, area_id, area_name, aliases, domain
                FROM alice.ha_entities
                WHERE is_active = true
                """
            )
            rows = cur.fetchall()
        return {r["entity_id"]: dict(r) for r in rows}
    except Exception as e:
        logger.error("Failed to load existing entities: %s", e)
        return {}
    finally:
        if conn:
            conn.close()


def upsert_entities(entities: list[dict]):
    """Upsert entities into alice.ha_entities."""
    if not entities:
        return
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            for e in entities:
                friendly_name = e.get("friendly_name") or _fallback_name(e["entity_id"])
                cur.execute(
                    """
                    INSERT INTO alice.ha_entities
                        (entity_id, domain, friendly_name, area_id, area_name,
                         aliases, is_active, weaviate_synced, last_seen_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, true, true, NOW(), NOW())
                    ON CONFLICT (entity_id) DO UPDATE SET
                        domain = EXCLUDED.domain,
                        friendly_name = EXCLUDED.friendly_name,
                        area_id = EXCLUDED.area_id,
                        area_name = EXCLUDED.area_name,
                        aliases = EXCLUDED.aliases,
                        is_active = true,
                        weaviate_synced = true,
                        last_seen_at = NOW(),
                        updated_at = NOW()
                    """,
                    (
                        e["entity_id"],
                        e["domain"],
                        friendly_name,
                        e.get("area_id"),
                        e.get("area_name"),
                        json.dumps(e.get("aliases", [])),
                    ),
                )
            conn.commit()
    except Exception as e:
        logger.error("Failed to upsert entities: %s", e)
    finally:
        if conn:
            conn.close()


def deactivate_entities(entity_ids: list[str]):
    """Mark entities as inactive in alice.ha_entities."""
    if not entity_ids:
        return
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE alice.ha_entities
                SET is_active = false, weaviate_synced = false, updated_at = NOW()
                WHERE entity_id = ANY(%s)
                """,
                (entity_ids,),
            )
            conn.commit()
    except Exception as e:
        logger.error("Failed to deactivate entities: %s", e)
    finally:
        if conn:
            conn.close()


# ---------------------------------------------------------------------------
# Home Assistant API
# ---------------------------------------------------------------------------
def _ha_headers() -> dict:
    return {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}


def _ha_ws_url() -> str:
    """Convert HA_URL (http/https) into a ws/wss WebSocket URL for /api/websocket."""
    parsed = urlparse(HA_URL)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    netloc = parsed.netloc or parsed.path  # tolerate values without scheme
    return f"{scheme}://{netloc}/api/websocket"


class HAFetchError:
    """Sentinel returned by fetch helpers on failure to distinguish error types."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason  # "invalid_token" | "ha_unreachable" | "expose_unavailable"
        self.detail = detail


async def _ha_ws_fetch(
    ws_url: str, token: str
) -> tuple[set[str], dict[str, str | None], dict[str, str | None], dict[str, list[str]], dict[str, str]]:
    """Open a single WebSocket session, authenticate, and run the commands
    required for the overhauled sync.

    config/entity_registry/list omits aliases (lightweight format). Aliases are
    fetched individually via config/entity_registry/get for each exposed entity only.

    Returns: (expose_set, entity_area_map, device_area_map, entity_aliases_map, area_name_map)
    """
    expose_set: set[str] = set()
    entity_area_map: dict[str, str | None] = {}
    device_area_map: dict[str, str | None] = {}
    entity_aliases_map: dict[str, list[str]] = {}
    area_name_map: dict[str, str] = {}

    # 10 s connect + per-message timeouts inside the protocol calls below.
    async with websockets.connect(ws_url, open_timeout=10, close_timeout=5, max_size=16 * 1024 * 1024) as ws:
        # 1) auth_required handshake
        greeting = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if greeting.get("type") != "auth_required":
            raise RuntimeError(f"unexpected greeting from HA WS: {greeting}")

        await ws.send(json.dumps({"type": "auth", "access_token": token}))
        auth_resp = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if auth_resp.get("type") != "auth_ok":
            # auth_invalid -> raise so caller maps it to "invalid_token"
            raise PermissionError(
                f"HA WS auth failed: {auth_resp.get('message') or auth_resp}"
            )

        async def _call(msg_id: int, payload: dict):
            await ws.send(json.dumps({"id": msg_id, **payload}))
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=20)
                data = json.loads(raw)
                if data.get("id") != msg_id:
                    # ignore unrelated frames (events, other results)
                    continue
                if data.get("type") != "result":
                    continue
                if not data.get("success", False):
                    err = data.get("error", {})
                    raise RuntimeError(
                        f"HA WS command {payload.get('type')} failed: "
                        f"{err.get('code')} {err.get('message')}"
                    )
                return data.get("result")

        # 2) expose list — keyed by entity_id, value contains per-assistant flags.
        #    Shape: { "exposed_entities": { "<entity_id>": { "conversation": true, ... } } }
        expose_raw = await _call(1, {"type": "homeassistant/expose_entity/list"})
        if isinstance(expose_raw, dict):
            exposed = expose_raw.get("exposed_entities") or {}
            if isinstance(exposed, dict):
                for eid, info in exposed.items():
                    if isinstance(info, dict) and info.get("conversation"):
                        expose_set.add(eid)

        # 3) entity registry — entity_id -> area_id (may be None)
        #    The list response is a lightweight format and does NOT include aliases.
        entity_reg = await _call(2, {"type": "config/entity_registry/list"})
        if isinstance(entity_reg, list):
            for row in entity_reg:
                if not isinstance(row, dict):
                    continue
                eid = row.get("entity_id")
                if not eid:
                    continue
                entity_area_map[eid] = row.get("area_id")
                # Stash device_id alongside under a private key so the caller
                # can resolve area via device registry without a second pass.
                entity_area_map.setdefault(f"__device__:{eid}", row.get("device_id"))

        # 4) device registry — device_id -> area_id (may be None)
        device_reg = await _call(3, {"type": "config/device_registry/list"})
        if isinstance(device_reg, list):
            for row in device_reg:
                if not isinstance(row, dict):
                    continue
                did = row.get("id")
                if not did:
                    continue
                device_area_map[did] = row.get("area_id")

        # 5) area registry — area_id -> area name
        area_reg = await _call(4, {"type": "config/area_registry/list"})
        if isinstance(area_reg, list):
            for row in area_reg:
                if not isinstance(row, dict):
                    continue
                aid = row.get("area_id")
                if aid:
                    area_name_map[aid] = row.get("name", "")

        # 6) aliases — config/entity_registry/get (extended format) for exposed entities only.
        #    The list command omits aliases; get returns the full _entry_ext_dict including them.
        #    Exposed entities are typically 20–100, so sequential calls are fast enough.
        for i, eid in enumerate(expose_set):
            try:
                entry = await _call(5 + i, {"type": "config/entity_registry/get", "entity_id": eid})
                if isinstance(entry, dict):
                    aliases_raw = entry.get("aliases", [])
                    entity_aliases_map[eid] = aliases_raw if isinstance(aliases_raw, list) else []
            except Exception as exc:
                logger.debug("Could not fetch aliases for %s: %s", eid, exc)
                entity_aliases_map.setdefault(eid, [])

    return expose_set, entity_area_map, device_area_map, entity_aliases_map, area_name_map


def fetch_ha_websocket_data() -> (
    tuple[set[str], dict[str, str | None], dict[str, str | None], dict[str, list[str]], dict[str, str]] | HAFetchError
):
    """Synchronous wrapper around the async WebSocket fetch. Returns the four
    lookup structures, or an HAFetchError if the API is unreachable / rejects auth.

    The expose set is the master allow-list. If this call fails the caller MUST
    abort the sync (no fallback to "all entities")."""
    ws_url = _ha_ws_url()
    logger.info("fetch_ha_websocket_data: connecting to %s", ws_url)
    try:
        result = asyncio.run(_ha_ws_fetch(ws_url, HA_TOKEN))
        logger.info("fetch_ha_websocket_data: success, expose_count=%d", len(result[0]))
        return result
    except PermissionError as e:
        logger.error("fetch_ha_websocket_data: invalid_token: %s", e)
        return HAFetchError("invalid_token", str(e)[:500])
    except (OSError, asyncio.TimeoutError, websockets.WebSocketException) as e:
        logger.error("fetch_ha_websocket_data: ha_unreachable: %s", e)
        return HAFetchError("ha_unreachable", str(e)[:500])
    except Exception as e:  # noqa: BLE001 - protocol/parse errors all map here
        logger.error("fetch_ha_websocket_data: expose_unavailable: %s", e)
        return HAFetchError("expose_unavailable", str(e)[:500])


def _resolve_area_for_entity(
    entity_id: str,
    entity_area_map: dict[str, str | None],
    device_area_map: dict[str, str | None],
) -> str | None:
    """Look up area_id for an entity using entity registry first, then fall back
    to the area_id of the entity's device."""
    area_id = entity_area_map.get(entity_id)
    if area_id:
        return area_id
    device_id = entity_area_map.get(f"__device__:{entity_id}")
    if device_id:
        return device_area_map.get(device_id)
    return None


def fetch_ha_entities(
    expose_set: set[str],
    entity_area_map: dict[str, str | None],
    device_area_map: dict[str, str | None],
    entity_aliases_map: dict[str, list[str]],
    area_name_map: dict[str, str],
) -> tuple[list[dict], int] | HAFetchError:
    """Fetch entities from HA /api/states, filter to conversation-exposed only,
    and enrich with area data from the registries.

    Returns a tuple `(entities, filtered_count)` on success, where
    `filtered_count` is the number of /api/states entries that were dropped
    because they were not in the expose set. On error returns HAFetchError.

    The expose_set parameter is the master allow-list (from the WebSocket fetch).
    Entities not in the set are dropped — they are not indexed in HAIntent."""
    try:
        states_resp = requests.get(
            f"{HA_URL}/api/states",
            headers=_ha_headers(),
            timeout=30,
        )
        if states_resp.status_code == 401:
            return HAFetchError(
                "invalid_token",
                "HA API returned 401 Unauthorized -- check HA_TOKEN",
            )
        states_resp.raise_for_status()
        all_states = states_resp.json()
    except requests.RequestException as e:
        logger.error("HA API error: %s", e)
        return HAFetchError("ha_unreachable", str(e)[:500])

    entities = []
    filtered_count = 0
    for s in all_states:
        entity_id = s.get("entity_id", "")
        if entity_id not in expose_set:
            filtered_count += 1
            continue  # not conversation-exposed -> skip
        domain = entity_id.split(".")[0] if "." in entity_id else ""
        attrs = s.get("attributes", {})
        friendly_name = attrs.get("friendly_name") or _fallback_name(entity_id)
        area_id = _resolve_area_for_entity(
            entity_id, entity_area_map, device_area_map
        )
        area_name = area_name_map.get(area_id) if area_id else None

        entities.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "friendly_name": friendly_name,
                "area_id": area_id,
                "area_name": area_name,
                "aliases": entity_aliases_map.get(entity_id, []),
                "device_class": attrs.get("device_class"),
            }
        )

    return entities, filtered_count


def fetch_single_entity(
    entity_id: str,
    entity_area_map: dict[str, str | None],
    device_area_map: dict[str, str | None],
    entity_aliases_map: dict[str, list[str]],
    area_name_map: dict[str, str],
) -> dict | None:
    """Fetch a single entity from HA /api/states/{entity_id} and enrich with
    area data from the supplied registries. Returns None if the entity does
    not exist in HA or the request fails."""
    try:
        state_resp = requests.get(
            f"{HA_URL}/api/states/{entity_id}",
            headers=_ha_headers(),
            timeout=15,
        )
        if state_resp.status_code == 404:
            return None  # Entity does not exist in HA
        state_resp.raise_for_status()
        s = state_resp.json()
    except requests.RequestException as e:
        logger.error("HA API error for %s: %s", entity_id, e)
        return None

    attrs = s.get("attributes", {})
    domain = entity_id.split(".")[0] if "." in entity_id else ""
    friendly_name = attrs.get("friendly_name") or _fallback_name(entity_id)
    area_id = _resolve_area_for_entity(entity_id, entity_area_map, device_area_map)

    area_name = area_name_map.get(area_id) if area_id else None

    return {
        "entity_id": entity_id,
        "domain": domain,
        "friendly_name": friendly_name,
        "area_id": area_id,
        "area_name": area_name,
        "aliases": entity_aliases_map.get(entity_id, []),
        "device_class": attrs.get("device_class"),
    }


def _fallback_name(entity_id: str) -> str:
    """Extract a human-readable name from entity_id (e.g. light.wohnzimmer_decke -> wohnzimmer decke)."""
    parts = entity_id.split(".", 1)
    if len(parts) > 1:
        return parts[1].replace("_", " ")
    return entity_id


# ---------------------------------------------------------------------------
# Utterance generation
# ---------------------------------------------------------------------------
def build_template_map(templates: list[dict]) -> dict[str, list[dict]]:
    """Build a lookup: domain -> list of template dicts."""
    tmap: dict[str, list[dict]] = {}
    for t in templates:
        d = t["domain"]
        if d not in tmap:
            tmap[d] = []
        tmap[d].append(t)
    return tmap


# Expansion tables for value placeholders. {message} is intentionally absent —
# free-text payloads (notify) are still skipped.
PERCENT_VALUES = (10, 25, 50, 75, 100)
TEMPERATURE_VALUES = (16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26)

# Domain -> (placeholder key in the rendered utterance, parameter key in the
# Weaviate `parameters` JSON, list of values, value type).
_DOMAIN_VALUE_EXPANSIONS: dict[str, tuple[str, tuple[int, ...]]] = {
    "climate": ("temperature", TEMPERATURE_VALUES),
    "light": ("brightness_pct", PERCENT_VALUES),
    "media_player": ("volume_level_pct", PERCENT_VALUES),
}


def _value_expansion_for(pattern: str, domain: str) -> tuple[str, tuple[int, ...]] | None:
    """Return (parameter_key, values) for a pattern that needs value-expansion.

    Selection order:
      1. {temperature} placeholder -> temperature values
      2. {value} + "Grad"/"°C" in pattern OR domain == climate -> temperature
      3. {value} + domain-specific table (light/media_player/...) -> percent
      4. {value} fallback -> percent
    Returns None for patterns without an expandable placeholder."""
    has_value = "{value}" in pattern
    has_temp = "{temperature}" in pattern

    if not (has_value or has_temp):
        return None

    if has_temp:
        return ("temperature", TEMPERATURE_VALUES)

    # has_value below
    lower = pattern.lower()
    if "grad" in lower or "°c" in lower or domain == "climate":
        return ("temperature", TEMPERATURE_VALUES)

    domain_cfg = _DOMAIN_VALUE_EXPANSIONS.get(domain)
    if domain_cfg:
        return domain_cfg

    return ("value", PERCENT_VALUES)


def generate_utterances(entity: dict, template_map: dict[str, list[dict]]) -> list[dict]:
    """Generate Weaviate HAIntent utterance objects for a single entity.

    Patterns containing {value} or {temperature} are expanded into one utterance
    per representative value (see PROJ-39 AC-3/AC-4). Patterns containing
    {message} are still skipped — free-text payloads are not enumerable."""
    domain = entity["domain"]
    name = entity.get("friendly_name") or _fallback_name(entity["entity_id"])
    area = entity.get("area_name")
    aliases = entity.get("aliases", []) if isinstance(entity.get("aliases"), list) else []
    names = [name] + [a for a in aliases if a]

    # Get templates for this domain
    domain_templates = template_map.get(domain, [])
    if not domain_templates:
        return []

    utterances = []
    seen = set()

    for tpl in domain_templates:
        patterns = tpl.get("patterns", [])
        if isinstance(patterns, str):
            try:
                patterns = json.loads(patterns)
            except json.JSONDecodeError:
                patterns = []
        if not isinstance(patterns, list):
            continue

        default_params = tpl.get("default_parameters", {})
        if isinstance(default_params, str):
            try:
                default_params = json.loads(default_params)
            except json.JSONDecodeError:
                default_params = {}
        if not isinstance(default_params, dict):
            default_params = {}

        for pattern in patterns:
            if not isinstance(pattern, str):
                continue
            # {message} stays unsupported — no enumeration of free text.
            if "{message}" in pattern:
                continue

            expansion = _value_expansion_for(pattern, domain)
            # For non-expandable patterns we render one utterance per name/area
            # combination. For expandable patterns we additionally render one
            # utterance per expansion value (both placeholder spellings are
            # substituted by the literal number).
            if expansion is None:
                value_iterations: list[tuple[str, int | None]] = [("", None)]
            else:
                param_key, values = expansion
                value_iterations = [(str(v), v) for v in values]

            for n in names:
                for value_str, value_num in value_iterations:
                    # Substitute the numeric placeholder first (if any).
                    rendered_pattern = pattern
                    if expansion is not None:
                        rendered_pattern = rendered_pattern.replace(
                            "{value}", value_str
                        ).replace("{temperature}", value_str)

                    variants = []

                    if "{where}" in rendered_pattern:
                        variants.append(rendered_pattern.replace("{where}", n))
                        if area:
                            variants.append(rendered_pattern.replace("{where}", area))
                    elif "{name}" in rendered_pattern and "{area}" in rendered_pattern:
                        if area:
                            variants.append(
                                rendered_pattern.replace("{name}", n).replace(
                                    "{area}", area
                                )
                            )
                    elif "{name}" in rendered_pattern:
                        variants.append(rendered_pattern.replace("{name}", n))
                    elif "{area}" in rendered_pattern:
                        if area:
                            variants.append(rendered_pattern.replace("{area}", area))
                    else:
                        variants.append(rendered_pattern + " " + n)

                    # Merge per-value parameter into the template defaults.
                    if expansion is not None and value_num is not None:
                        params = dict(default_params)
                        params[expansion[0]] = value_num
                    else:
                        params = default_params

                    for utt in variants:
                        utt = utt.strip()
                        if not utt or utt in seen:
                            continue
                        seen.add(utt)

                        utterances.append(
                            {
                                "utterance": utt,
                                "entityId": entity["entity_id"],
                                "domain": domain,
                                "service": tpl["service"],
                                "parameters": json.dumps(params or {}),
                                "language": tpl.get("language", "de"),
                                "intentTemplate": f"{domain}:{tpl['intent']}",
                                "certaintyThreshold": CERTAINTY_THRESHOLD,
                            }
                        )

    return utterances


# ---------------------------------------------------------------------------
# Weaviate operations
# ---------------------------------------------------------------------------
def get_weaviate_client():
    """Create a Weaviate v4 client."""
    return weaviate.connect_to_custom(
        http_host=urlparse(WEAVIATE_URL).hostname or "weaviate",
        http_port=urlparse(WEAVIATE_URL).port or 8080,
        http_secure=False,
        grpc_host=urlparse(WEAVIATE_URL).hostname or "weaviate",
        grpc_port=50051,
        grpc_secure=False,
    )


def weaviate_delete_by_entity(entity_ids: list[str]) -> tuple[int, list[str]]:
    """Delete all HAIntent objects for the given entity_ids. Returns (deleted_count, errors)."""
    if not entity_ids:
        return 0, []

    deleted = 0
    errors = []
    try:
        client = get_weaviate_client()
        collection = client.collections.get("HAIntent")
        for eid in entity_ids:
            try:
                result = collection.data.delete_many(
                    where=Filter.by_property("entityId").equal(eid)
                )
                deleted += result.successful
            except Exception as e:
                errors.append(f"Delete failed for {eid}: {str(e)[:200]}")
        client.close()
    except Exception as e:
        errors.append(f"Weaviate connection error: {str(e)[:200]}")

    return deleted, errors


def weaviate_batch_insert(utterances: list[dict]) -> tuple[int, int, list[str]]:
    """Insert utterances into Weaviate HAIntent in batches. Returns (inserted, failed, errors)."""
    if not utterances:
        return 0, 0, []

    total_inserted = 0
    total_failed = 0
    errors = []

    try:
        client = get_weaviate_client()
        collection = client.collections.get("HAIntent")

        for i in range(0, len(utterances), WEAVIATE_BATCH_SIZE):
            batch = utterances[i : i + WEAVIATE_BATCH_SIZE]
            batch_num = i // WEAVIATE_BATCH_SIZE

            try:
                with collection.batch.dynamic() as batch_inserter:
                    for utt in batch:
                        batch_inserter.add_object(properties=utt)

                # Check for errors using the context manager instance (not collection.batch,
                # which creates a new empty batch object and always returns failed_objects=[])
                failed_count = len(getattr(batch_inserter, 'failed_objects', []))
                succeeded = len(batch) - failed_count
                total_inserted += succeeded
                total_failed += failed_count
                if failed_count > 0:
                    errors.append(f"Batch {batch_num}: {failed_count} objects failed")
            except Exception as e:
                errors.append(f"Batch {batch_num} error: {str(e)[:200]}")
                total_failed += len(batch)

        client.close()
    except Exception as e:
        errors.append(f"Weaviate connection error: {str(e)[:200]}")
        total_failed += len(utterances) - total_inserted

    return total_inserted, total_failed, errors


# ---------------------------------------------------------------------------
# MQTT output helpers
# ---------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def publish_info(mqtt_client: MQTTClient, event: str, **kwargs):
    msg = {"timestamp": _now_iso(), "event": event, **kwargs}
    # Provide defaults for expected fields
    msg.setdefault("sync_type", "")
    msg.setdefault("message", "")
    msg.setdefault("entities_added", 0)
    msg.setdefault("entities_updated", 0)
    msg.setdefault("entities_removed", 0)
    msg.setdefault("duration_ms", 0)
    mqtt_client.publish(MQTT_INFO_TOPIC, msg)
    logger.info("[info] %s: %s", event, msg.get("message", ""))


def publish_warning(mqtt_client: MQTTClient, event: str, **kwargs):
    msg = {"timestamp": _now_iso(), "event": event, **kwargs}
    msg.setdefault("message", "")
    mqtt_client.publish(MQTT_WARNING_TOPIC, msg)
    logger.warning("[warning] %s: %s", event, msg.get("message", ""))


def publish_error(mqtt_client: MQTTClient, event: str, **kwargs):
    msg = {"timestamp": _now_iso(), "event": event, **kwargs}
    msg.setdefault("message", "")
    msg.setdefault("detail", "")
    mqtt_client.publish(MQTT_ERROR_TOPIC, msg)
    logger.error("[error] %s: %s", event, msg.get("message", ""))


# ---------------------------------------------------------------------------
# Sync operations
# ---------------------------------------------------------------------------
def full_sync(mqtt_client: MQTTClient, trigger_source: str, force_all: bool = False):
    """Execute a full sync of all HA entities.

    Args:
        force_all: If True, regenerate utterances for ALL entities regardless
                   of whether their name/area changed (used for templates_updated).
    """
    start_time = time.time()

    # Concurrent check
    if check_concurrent_sync():
        publish_info(
            mqtt_client,
            "sync_skipped",
            sync_type="full",
            message="Skipped: another sync is already running",
        )
        return

    log_id = create_sync_log("full", trigger_source)
    if log_id is None:
        publish_error(
            mqtt_client,
            "sync_failed",
            message="Failed to create sync log entry",
        )
        return

    publish_info(
        mqtt_client,
        "sync_started",
        sync_type="full",
        message=f"Full sync started (trigger: {trigger_source})",
    )

    # 1a. Fetch WebSocket data: expose list + entity/device registries.
    #     Expose list is the master allow-list. Any failure here aborts the
    #     sync — there is no fallback to "all entities".
    ws_result = fetch_ha_websocket_data()
    if isinstance(ws_result, HAFetchError):
        publish_error(
            mqtt_client,
            ws_result.reason,
            message=ws_result.detail or f"HA WS error: {ws_result.reason}",
            detail=ws_result.detail,
        )
        update_sync_log(
            log_id,
            "error",
            error_message=(ws_result.detail or ws_result.reason)[:500],
            details={"phase": "websocket_fetch", "reason": ws_result.reason},
        )
        return
    expose_set, entity_area_map, device_area_map, entity_aliases_map, area_name_map = ws_result

    # 1b. Fetch entities from HA REST states, filtered to conversation-exposed.
    fetch_result = fetch_ha_entities(expose_set, entity_area_map, device_area_map, entity_aliases_map, area_name_map)
    if isinstance(fetch_result, HAFetchError):
        publish_error(
            mqtt_client,
            fetch_result.reason,
            message=fetch_result.detail or f"HA API error: {fetch_result.reason}",
            detail=fetch_result.detail,
        )
        update_sync_log(
            log_id,
            "error",
            error_message=fetch_result.detail[:500] if fetch_result.detail else fetch_result.reason,
        )
        return
    ha_entities, filtered_count = fetch_result

    # 2. Load existing entities from DB for diff
    existing = load_existing_entities()

    # 3. Compute diff
    incoming_ids = {e["entity_id"] for e in ha_entities}
    existing_ids = set(existing.keys())

    added = [e for e in ha_entities if e["entity_id"] not in existing_ids]
    updated = []
    for e in ha_entities:
        if e["entity_id"] not in existing_ids:
            continue
        ex = existing[e["entity_id"]]
        if (
            ex.get("friendly_name") != e.get("friendly_name")
            or ex.get("area_id") != e.get("area_id")
            or ex.get("area_name") != e.get("area_name")
            or json.dumps(ex.get("aliases", [])) != json.dumps(e.get("aliases", []))
        ):
            updated.append(e)
    removed_ids = [eid for eid in existing_ids if eid not in incoming_ids]

    # 4. Load templates
    templates = load_templates()
    template_map = build_template_map(templates)

    # 5. Generate utterances for added + updated entities
    #    When force_all=True (templates_updated), reprocess ALL entities so that
    #    new/changed templates are applied even if no entity name/area changed.
    to_process = ha_entities if force_all else added + updated
    all_utterances = []
    warnings = []

    warned_domains: set[str] = set()
    for entity in to_process:
        utts = generate_utterances(entity, template_map)
        if not utts and entity["domain"] not in template_map:
            if entity["domain"] not in warned_domains:
                warned_domains.add(entity["domain"])
                warnings.append(f"No template for domain: {entity['domain']}")
                publish_warning(
                    mqtt_client,
                    "no_template",
                    entity_id=entity["entity_id"],
                    domain=entity["domain"],
                    message=f"No template for domain {entity['domain']} (skipping all entities of this domain)",
                )
        all_utterances.extend(utts)

    # 6. Delete Weaviate objects for entities that will be reprocessed + removed
    #    When force_all, delete all existing entities' Weaviate objects before reinserting.
    if force_all:
        delete_ids = [e["entity_id"] for e in ha_entities]
    else:
        delete_ids = [e["entity_id"] for e in updated] + removed_ids
    weaviate_deleted, delete_errors = weaviate_delete_by_entity(delete_ids)

    # 7. Batch insert new utterances into Weaviate
    weaviate_inserted, weaviate_failed, insert_errors = weaviate_batch_insert(all_utterances)

    # 8. Upsert entities in PostgreSQL
    upsert_entities(to_process)
    deactivate_entities(removed_ids)

    # 9. Determine final status
    all_errors = delete_errors + insert_errors
    if all_errors and weaviate_inserted > 0:
        final_status = "partial"
    elif all_errors and weaviate_inserted == 0 and len(all_utterances) > 0:
        final_status = "error"
    else:
        final_status = "success"

    duration_ms = int((time.time() - start_time) * 1000)

    # 10. Update sync log
    update_sync_log(
        log_id,
        final_status,
        entities_found=len(ha_entities),
        entities_added=len(added),
        entities_updated=len(updated),
        entities_removed=len(removed_ids),
        intents_generated=weaviate_inserted,
        intents_removed=weaviate_deleted,
        error_message="; ".join(all_errors)[:500] if all_errors else None,
        details={
            "warnings": warnings,
            "batch_errors": all_errors,
            "expose_count": len(expose_set),
            "filtered_count": filtered_count,
        },
    )

    # 11. Publish result
    if final_status == "error":
        publish_error(
            mqtt_client,
            "sync_failed",
            message=f"Full sync failed: {'; '.join(all_errors)[:200]}",
            detail="; ".join(all_errors)[:500],
        )
    elif final_status == "partial":
        publish_error(
            mqtt_client,
            "partial_sync",
            message=f"Full sync partial: {weaviate_inserted} inserted, {weaviate_failed} failed",
            detail="; ".join(all_errors)[:500],
        )
    else:
        publish_info(
            mqtt_client,
            "sync_success",
            sync_type="full",
            message=f"Full sync complete: {len(added)} added, {len(updated)} updated, {len(removed_ids)} removed",
            entities_added=len(added),
            entities_updated=len(updated),
            entities_removed=len(removed_ids),
            duration_ms=duration_ms,
        )

    logger.info(
        "Full sync done: status=%s, added=%d, updated=%d, removed=%d, intents=%d, duration=%dms",
        final_status,
        len(added),
        len(updated),
        len(removed_ids),
        weaviate_inserted,
        duration_ms,
    )


def incremental_sync(mqtt_client: MQTTClient, entity_id: str):
    """Sync a single newly created or changed entity."""
    start_time = time.time()

    # Validate entity_id format
    if not re.match(r"^[a-zA-Z_]+\.[a-zA-Z0-9_\-]+$", entity_id):
        publish_warning(
            mqtt_client,
            "unknown_event",
            entity_id=entity_id,
            message=f"Invalid entity_id format: {entity_id}",
        )
        return

    # Concurrent check
    if check_concurrent_sync():
        publish_info(
            mqtt_client,
            "sync_skipped",
            sync_type="incremental",
            message=f"Skipped incremental for {entity_id}: another sync running",
        )
        return

    log_id = create_sync_log("incremental", "mqtt_entity_created")
    if log_id is None:
        return

    # Fetch WebSocket data: required for both the expose check and the
    # area-registry lookup. A failure aborts the sync.
    ws_result = fetch_ha_websocket_data()
    if isinstance(ws_result, HAFetchError):
        publish_error(
            mqtt_client,
            ws_result.reason,
            message=ws_result.detail or f"HA WS error: {ws_result.reason}",
            detail=ws_result.detail,
        )
        update_sync_log(
            log_id,
            "error",
            error_message=(ws_result.detail or ws_result.reason)[:500],
            details={"phase": "websocket_fetch", "entity_id": entity_id},
        )
        return
    expose_set, entity_area_map, device_area_map, entity_aliases_map, area_name_map = ws_result

    # Expose check: only index conversation-exposed entities.
    if entity_id not in expose_set:
        logger.info(
            "Incremental sync skipped for %s: not conversation-exposed", entity_id
        )
        update_sync_log(
            log_id,
            "success",
            entities_added=0,
            details={
                "skip_reason": "not_conversation_exposed",
                "entity_id": entity_id,
            },
        )
        return

    # Fetch entity from HA
    entity_data = fetch_single_entity(entity_id, entity_area_map, device_area_map, entity_aliases_map, area_name_map)
    if entity_data is None:
        error_msg = f"HA API error for {entity_id}"
        publish_error(mqtt_client, "ha_unreachable", message=error_msg)
        update_sync_log(log_id, "error", error_message=error_msg)
        return

    # Check for no-op (no changes)
    existing = load_existing_entities()
    if entity_id in existing:
        ex = existing[entity_id]
        no_change = (
            ex.get("friendly_name") == entity_data.get("friendly_name")
            and ex.get("area_id") == entity_data.get("area_id")
            and ex.get("area_name") == entity_data.get("area_name")
            and json.dumps(ex.get("aliases", [])) == json.dumps(entity_data.get("aliases", []))
        )
        if no_change:
            logger.info("Incremental sync: no change for %s, skipping", entity_id)
            update_sync_log(
                log_id, "success", entities_added=0,
                details={"skip_reason": "no_change", "entity_id": entity_id},
            )
            return

    # Load templates for this domain
    domain = entity_data["domain"]
    templates = load_templates(domain)
    template_map = build_template_map(templates)

    # Generate utterances
    utterances = generate_utterances(entity_data, template_map)
    if not utterances and domain not in template_map:
        publish_warning(
            mqtt_client,
            "no_template",
            entity_id=entity_id,
            domain=domain,
            message=f"No template for domain {domain}",
        )

    # Delete existing Weaviate objects if updating
    weaviate_deleted = 0
    if entity_id in existing:
        weaviate_deleted, _ = weaviate_delete_by_entity([entity_id])

    # Insert new utterances
    weaviate_inserted, weaviate_failed, insert_errors = weaviate_batch_insert(utterances)

    # Upsert entity in PG
    upsert_entities([entity_data])

    # Determine status
    if insert_errors and weaviate_inserted > 0:
        final_status = "partial"
    elif insert_errors and weaviate_inserted == 0 and utterances:
        final_status = "error"
    else:
        final_status = "success"

    duration_ms = int((time.time() - start_time) * 1000)

    update_sync_log(
        log_id,
        final_status,
        entities_added=1 if entity_id not in existing else 0,
        entities_updated=1 if entity_id in existing else 0,
        intents_generated=weaviate_inserted,
        intents_removed=weaviate_deleted,
        error_message="; ".join(insert_errors)[:500] if insert_errors else None,
    )

    logger.info(
        "Incremental sync for %s: status=%s, intents=%d, duration=%dms",
        entity_id,
        final_status,
        weaviate_inserted,
        duration_ms,
    )


def remove_entity(mqtt_client: MQTTClient, entity_id: str):
    """Remove an entity from Weaviate and deactivate in PostgreSQL."""
    if not re.match(r"^[a-zA-Z_]+\.[a-zA-Z0-9_\-]+$", entity_id):
        publish_warning(
            mqtt_client,
            "unknown_event",
            entity_id=entity_id,
            message=f"Invalid entity_id format: {entity_id}",
        )
        return

    # Delete from Weaviate
    deleted, errors = weaviate_delete_by_entity([entity_id])
    if errors:
        publish_error(
            mqtt_client,
            "weaviate_error",
            message=f"Failed to delete {entity_id} from Weaviate",
            detail="; ".join(errors)[:500],
        )

    # Deactivate in PG
    deactivate_entities([entity_id])

    # Log -- status reflects whether Weaviate deletion succeeded
    removal_status = "error" if errors else "success"
    error_msg = "; ".join(errors)[:500] if errors else None
    conn = None
    try:
        conn = get_db_connection()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO alice.ha_sync_log
                    (sync_type, trigger_source, entities_removed, intents_removed,
                     status, error_message, started_at, completed_at, duration_ms)
                VALUES ('incremental', 'mqtt_entity_removed', 1, %s, %s, %s, NOW(), NOW(), 0)
                """,
                (deleted, removal_status, error_msg),
            )
            conn.commit()
    except Exception as e:
        logger.error("Failed to log entity removal: %s", e)
    finally:
        if conn:
            conn.close()

    logger.info("Removed entity %s: %d Weaviate objects deleted", entity_id, deleted)


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------
def worker_loop(event_queue: queue.Queue, mqtt_client: MQTTClient):
    """Process events from the queue sequentially."""
    while True:
        try:
            payload = event_queue.get(timeout=HEARTBEAT_INTERVAL)
        except queue.Empty:
            # No event received, just continue (heartbeat is written separately)
            continue

        event = payload.get("event", "")
        try:
            if event in ("ha_start", "templates_updated"):
                trigger = f"mqtt_{event}"
                force_all = event == "templates_updated"
                full_sync(mqtt_client, trigger, force_all=force_all)
            elif event == "entity_created":
                entity_id = payload.get("entity_id", "")
                if entity_id:
                    incremental_sync(mqtt_client, entity_id)
                else:
                    publish_warning(
                        mqtt_client,
                        "unknown_event",
                        message="entity_created event missing entity_id",
                    )
            elif event == "entity_removed":
                entity_id = payload.get("entity_id", "")
                if entity_id:
                    remove_entity(mqtt_client, entity_id)
                else:
                    publish_warning(
                        mqtt_client,
                        "unknown_event",
                        message="entity_removed event missing entity_id",
                    )
            else:
                publish_warning(
                    mqtt_client,
                    "unknown_event",
                    message=f"Unknown event type: {event}",
                )
        except Exception as e:
            logger.exception("Unhandled error processing event '%s': %s", event, e)
            publish_error(
                mqtt_client,
                "sync_failed",
                message=f"Unhandled error: {str(e)[:200]}",
                detail=str(e)[:500],
            )
        finally:
            event_queue.task_done()


# ---------------------------------------------------------------------------
# Heartbeat thread
# ---------------------------------------------------------------------------
def heartbeat_loop():
    """Write current timestamp to heartbeat file every HEARTBEAT_INTERVAL seconds."""
    while True:
        try:
            with open(HEARTBEAT_FILE, "w") as f:
                f.write(str(time.time()))
        except Exception as e:
            logger.error("Failed to write heartbeat: %s", e)
        time.sleep(HEARTBEAT_INTERVAL)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    logger.info("alice-ha-sync worker starting")

    # Crash recovery: mark stale running entries
    crash_recovery()

    # Event queue for decoupling MQTT callbacks from sync work
    event_queue: queue.Queue = queue.Queue()

    # MQTT client
    mqtt_client = MQTTClient(MQTT_URL, MQTT_USER, MQTT_PASSWORD, event_queue)
    mqtt_client.connect()

    # Start heartbeat thread (daemon so it dies with main)
    heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat_thread.start()

    # Start worker thread (daemon so it dies with main)
    worker_thread = threading.Thread(
        target=worker_loop, args=(event_queue, mqtt_client), daemon=True
    )
    worker_thread.start()

    logger.info("alice-ha-sync worker ready, waiting for MQTT events on %s", MQTT_SUBSCRIBE_TOPIC)

    # Main thread just sleeps; KeyboardInterrupt / SIGTERM will stop the process
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down")
    finally:
        mqtt_client.client.loop_stop()
        mqtt_client.client.disconnect()


if __name__ == "__main__":
    main()
