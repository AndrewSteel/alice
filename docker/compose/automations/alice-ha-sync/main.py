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
import weaviate
from weaviate.classes.query import Filter

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
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


class HAFetchError:
    """Sentinel returned by fetch_ha_entities on failure to distinguish error types."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason  # "invalid_token" or "ha_unreachable"
        self.detail = detail


def fetch_ha_entities() -> list[dict] | HAFetchError:
    """Fetch entity registry + area registry from HA. Returns HAFetchError on error."""
    try:
        entity_resp = requests.get(
            f"{HA_URL}/api/config/entity_registry/list",
            headers=_ha_headers(),
            timeout=30,
        )
        if entity_resp.status_code == 401:
            return HAFetchError(
                "invalid_token",
                "HA API returned 401 Unauthorized -- check HA_TOKEN",
            )
        entity_resp.raise_for_status()
        all_entities = entity_resp.json()

        area_resp = requests.get(
            f"{HA_URL}/api/config/area_registry/list",
            headers=_ha_headers(),
            timeout=30,
        )
        if area_resp.status_code == 401:
            return HAFetchError(
                "invalid_token",
                "HA API returned 401 Unauthorized on area registry -- check HA_TOKEN",
            )
        area_resp.raise_for_status()
        areas = area_resp.json()
    except requests.RequestException as e:
        logger.error("HA API error: %s", e)
        return HAFetchError("ha_unreachable", str(e)[:500])

    area_map = {a["area_id"]: a["name"] for a in areas}

    entities = []
    for e in all_entities:
        opts = e.get("options", {})
        conv = opts.get("conversation", {})
        if conv.get("should_expose") is False:
            continue

        entity_id = e.get("entity_id", "")
        domain = entity_id.split(".")[0] if "." in entity_id else ""
        friendly_name = (
            e.get("name")
            or e.get("original_name")
            or _fallback_name(entity_id)
        )
        area_id = e.get("area_id")
        area_name = area_map.get(area_id) if area_id else None

        entities.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "friendly_name": friendly_name,
                "area_id": area_id,
                "area_name": area_name,
                "aliases": e.get("aliases", []),
                "device_class": e.get("device_class"),
            }
        )

    return entities


def fetch_single_entity(entity_id: str) -> dict | None:
    """Fetch a single entity from HA registry. Returns None on error."""
    try:
        reg_resp = requests.get(
            f"{HA_URL}/api/config/entity_registry/config/{entity_id}",
            headers=_ha_headers(),
            timeout=15,
        )
        reg_resp.raise_for_status()
        entity_reg = reg_resp.json()
    except requests.RequestException as e:
        logger.error("HA API error for %s: %s", entity_id, e)
        return None

    # Check exposure
    opts = entity_reg.get("options", {})
    conv = opts.get("conversation", {})
    if conv.get("should_expose") is False:
        return {"_skip": True, "reason": "not_exposed"}

    # Fetch area name if needed
    area_name = None
    area_id = entity_reg.get("area_id")
    if area_id:
        try:
            area_resp = requests.get(
                f"{HA_URL}/api/config/area_registry/list",
                headers=_ha_headers(),
                timeout=15,
            )
            if area_resp.ok:
                areas = area_resp.json()
                match = next((a for a in areas if a["area_id"] == area_id), None)
                area_name = match["name"] if match else None
        except requests.RequestException:
            pass

    domain = entity_id.split(".")[0] if "." in entity_id else ""
    friendly_name = (
        entity_reg.get("name")
        or entity_reg.get("original_name")
        or _fallback_name(entity_id)
    )

    return {
        "entity_id": entity_id,
        "domain": domain,
        "friendly_name": friendly_name,
        "area_id": area_id,
        "area_name": area_name,
        "aliases": entity_reg.get("aliases", []),
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


def generate_utterances(entity: dict, template_map: dict[str, list[dict]]) -> list[dict]:
    """Generate Weaviate HAIntent utterance objects for a single entity."""
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

        for pattern in patterns:
            if not isinstance(pattern, str):
                continue
            # Skip patterns with value placeholders
            if any(p in pattern for p in ("{value}", "{message}", "{temperature}")):
                continue

            for n in names:
                variants = []

                if "{where}" in pattern:
                    variants.append(pattern.replace("{where}", n))
                    if area:
                        variants.append(pattern.replace("{where}", area))
                elif "{name}" in pattern and "{area}" in pattern:
                    if area:
                        variants.append(
                            pattern.replace("{name}", n).replace("{area}", area)
                        )
                elif "{name}" in pattern:
                    variants.append(pattern.replace("{name}", n))
                elif "{area}" in pattern:
                    if area:
                        variants.append(pattern.replace("{area}", area))
                else:
                    variants.append(pattern + " " + n)

                for utt in variants:
                    utt = utt.strip()
                    if not utt or utt in seen:
                        continue
                    seen.add(utt)

                    default_params = tpl.get("default_parameters", {})
                    if isinstance(default_params, str):
                        try:
                            default_params = json.loads(default_params)
                        except json.JSONDecodeError:
                            default_params = {}

                    utterances.append(
                        {
                            "utterance": utt,
                            "entityId": entity["entity_id"],
                            "domain": domain,
                            "service": tpl["service"],
                            "parameters": json.dumps(default_params or {}),
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

                # Check for errors in the batch result
                failed_count = len(collection.batch.failed_objects) if hasattr(collection.batch, 'failed_objects') else 0
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

    # 1. Fetch entities from HA
    ha_entities = fetch_ha_entities()
    if isinstance(ha_entities, HAFetchError):
        publish_error(
            mqtt_client,
            ha_entities.reason,
            message=ha_entities.detail or f"HA API error: {ha_entities.reason}",
            detail=ha_entities.detail,
        )
        update_sync_log(log_id, "error", error_message=ha_entities.detail[:500] if ha_entities.detail else ha_entities.reason)
        return

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

    for entity in to_process:
        utts = generate_utterances(entity, template_map)
        if not utts and entity["domain"] in template_map:
            pass  # Templates exist but no utterances generated (all filtered out)
        elif not utts:
            warnings.append(f"No template for domain: {entity['domain']} ({entity['entity_id']})")
            publish_warning(
                mqtt_client,
                "no_template",
                entity_id=entity["entity_id"],
                domain=entity["domain"],
                message=f"No template for domain {entity['domain']}",
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
        details={"warnings": warnings, "batch_errors": all_errors},
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

    # Fetch entity from HA
    entity_data = fetch_single_entity(entity_id)
    if entity_data is None:
        error_msg = f"HA API error for {entity_id}"
        publish_error(mqtt_client, "ha_unreachable", message=error_msg)
        update_sync_log(log_id, "error", error_message=error_msg)
        return

    if entity_data.get("_skip"):
        reason = entity_data.get("reason", "not_exposed")
        logger.info("Incremental sync skipped for %s: %s", entity_id, reason)
        update_sync_log(
            log_id, "success", entities_added=0,
            details={"skip_reason": reason, "entity_id": entity_id},
        )
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
