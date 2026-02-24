"""
hassil-parser: FastAPI service for expanding Home Assistant intent templates.

Endpoints:
  GET  /health                   - Health check
  POST /intents/sync             - Download + expand + upsert HA intents
  POST /intents/trigger-entity-sync - Publish MQTT event only
"""

import io
import json
import logging
import os
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
import psycopg2
import psycopg2.extras
import yaml
from fastapi import FastAPI, HTTPException

from expand_ha_intents import parse_intent_yaml

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
POSTGRES_CONNECTION = os.environ.get("POSTGRES_CONNECTION", "")
MQTT_URL = os.environ.get("MQTT_URL", "")
MAX_PATTERNS_PER_INTENT = int(os.environ.get("MAX_PATTERNS_PER_INTENT", "50"))
DATA_INBOX_PATH = Path("/data_inbox")

HA_INTENTS_ZIP_URL = "https://github.com/home-assistant/intents/archive/refs/heads/main.zip"
HA_SENTENCES_PREFIX = "intents-main/sentences/de/"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("hassil-parser")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="hassil-parser", version="1.0.0")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_db_connection():
    """Create a PostgreSQL connection from the POSTGRES_CONNECTION env var."""
    if not POSTGRES_CONNECTION:
        raise RuntimeError("POSTGRES_CONNECTION environment variable is not set")
    return psycopg2.connect(POSTGRES_CONNECTION)


def _publish_mqtt(topic: str, payload: dict) -> None:
    """Publish a single MQTT message and disconnect."""
    import paho.mqtt.client as mqtt

    if not MQTT_URL:
        logger.warning("MQTT_URL not set, skipping publish to %s", topic)
        return

    parsed = urlparse(MQTT_URL)
    host = parsed.hostname or "localhost"
    port = parsed.port or 1883
    username = parsed.username
    password = parsed.password

    client = mqtt.Client(client_id="hassil-parser", protocol=mqtt.MQTTv311)
    if username:
        client.username_pw_set(username, password)

    try:
        client.connect(host, port, keepalive=30)
        result = client.publish(topic, json.dumps(payload), qos=1)
        result.wait_for_publish(timeout=10)
        logger.info("Published MQTT message to %s: %s", topic, payload)
    except Exception as exc:
        logger.error("Failed to publish MQTT message to %s: %s", topic, exc)
        raise
    finally:
        client.disconnect()


def _extract_domain_from_filename(filename: str) -> str:
    """Extract the HA domain from a YAML filename like '_common.yaml' or 'light.yaml'."""
    name = Path(filename).stem
    # Skip underscore-prefixed files like _common.yaml
    if name.startswith("_"):
        return name
    return name


def _download_and_extract_intents() -> dict[str, dict]:
    """
    Download the HA intents ZIP from GitHub and extract German YAML files.
    Returns a dict mapping domain -> parsed YAML data.
    """
    logger.info("Downloading HA intents from %s", HA_INTENTS_ZIP_URL)

    with httpx.Client(timeout=60.0, follow_redirects=True) as client:
        response = client.get(HA_INTENTS_ZIP_URL)
        response.raise_for_status()

    logger.info("Downloaded %d bytes", len(response.content))

    domain_yamls: dict[str, dict] = {}

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        for entry in zf.namelist():
            if not entry.startswith(HA_SENTENCES_PREFIX):
                continue
            if not entry.endswith(".yaml"):
                continue

            filename = entry.split("/")[-1]
            domain = _extract_domain_from_filename(filename)

            with zf.open(entry) as f:
                content = f.read().decode("utf-8")
                parsed = yaml.safe_load(content)
                if parsed and isinstance(parsed, dict):
                    domain_yamls[domain] = parsed
                    logger.info("Parsed YAML for domain: %s", domain)

    logger.info("Extracted %d domain YAML files from ZIP", len(domain_yamls))
    return domain_yamls


def _merge_common_rules(domain_yamls: dict[str, dict]) -> dict[str, list[str]]:
    """Extract expansion_rules from _common.yaml (if present) as shared rules."""
    common = domain_yamls.get("_common", {})
    shared_rules: dict[str, list[str]] = {}

    # expansion_rules from _common
    for rule_name, alternatives in common.get("expansion_rules", {}).items():
        if isinstance(alternatives, list):
            shared_rules[rule_name] = alternatives

    # lists from _common
    for list_name, list_def in common.get("lists", {}).items():
        if list_name not in shared_rules and isinstance(list_def, dict):
            values = list_def.get("values", [])
            str_values = []
            for v in values:
                if isinstance(v, dict) and "in" in v:
                    str_values.append(str(v["in"]))
                elif isinstance(v, str):
                    str_values.append(v)
            if str_values:
                shared_rules[list_name] = str_values

    return shared_rules


def _upsert_templates(templates: list[dict]) -> dict[str, int]:
    """
    Upsert templates into alice.ha_intent_templates.
    Returns counts: {"inserted": N, "updated": N, "skipped": N}
    """
    if not templates:
        return {"inserted": 0, "updated": 0, "skipped": 0}

    conn = _get_db_connection()
    inserted = 0
    updated = 0
    skipped = 0

    try:
        with conn.cursor() as cur:
            for tmpl in templates:
                if not tmpl["patterns"]:
                    skipped += 1
                    continue

                cur.execute(
                    """
                    INSERT INTO alice.ha_intent_templates
                        (domain, intent, service, language, patterns, source, default_parameters)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (domain, intent, language) DO UPDATE SET
                        service = EXCLUDED.service,
                        patterns = EXCLUDED.patterns,
                        source = EXCLUDED.source,
                        default_parameters = EXCLUDED.default_parameters,
                        updated_at = NOW()
                    RETURNING (xmax = 0) AS is_insert
                    """,
                    (
                        tmpl["domain"],
                        tmpl["intent"],
                        tmpl["service"],
                        tmpl["language"],
                        json.dumps(tmpl["patterns"]),
                        tmpl["source"],
                        json.dumps(tmpl["default_parameters"] or {}),
                    ),
                )
                row = cur.fetchone()
                if row and row[0]:
                    inserted += 1
                else:
                    updated += 1

        conn.commit()
        logger.info(
            "Upsert complete: inserted=%d, updated=%d, skipped=%d",
            inserted,
            updated,
            skipped,
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return {"inserted": inserted, "updated": updated, "skipped": skipped}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    """Health check endpoint."""
    inbox_accessible = DATA_INBOX_PATH.is_dir()

    if inbox_accessible:
        return {"status": "healthy"}
    else:
        return {"status": "degraded", "inbox_accessible": False}


@app.post("/intents/sync")
async def intents_sync():
    """
    Download HA intents from GitHub, expand Hassil templates,
    and upsert into alice.ha_intent_templates.
    """
    start_time = time.time()

    # Step 1: Download and extract
    try:
        domain_yamls = _download_and_extract_intents()
    except (httpx.HTTPError, zipfile.BadZipFile) as exc:
        logger.error("Failed to download/extract HA intents: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Failed to download HA intents from GitHub: {exc}",
        )

    # Step 2: Get shared expansion rules from _common.yaml
    shared_rules = _merge_common_rules(domain_yamls)
    logger.info("Loaded %d shared expansion rules from _common", len(shared_rules))

    # Step 3: Parse and expand each domain
    all_templates: list[dict] = []

    for domain, yaml_data in domain_yamls.items():
        # Skip meta files
        if domain.startswith("_"):
            continue

        # Merge shared rules into domain-specific rules
        domain_rules = dict(shared_rules)
        domain_rules.update(yaml_data.get("expansion_rules", {}))
        yaml_data["expansion_rules"] = domain_rules

        try:
            templates = parse_intent_yaml(yaml_data, domain, MAX_PATTERNS_PER_INTENT)
            all_templates.extend(templates)
        except Exception as exc:
            logger.error("Failed to parse domain %s: %s", domain, exc)
            # Continue with other domains

    logger.info("Total templates to upsert: %d", len(all_templates))

    # Step 4: Upsert into PostgreSQL
    try:
        counts = _upsert_templates(all_templates)
    except Exception as exc:
        logger.error("Database upsert failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Database upsert failed: {exc}",
        )

    # Step 5: Publish MQTT event
    try:
        _publish_mqtt(
            "alice/ha/sync",
            {"event": "templates_updated", "source": "github"},
        )
    except Exception as exc:
        logger.warning("MQTT publish failed (sync still succeeded): %s", exc)

    duration_ms = int((time.time() - start_time) * 1000)

    return {
        "inserted": counts["inserted"],
        "updated": counts["updated"],
        "skipped": counts["skipped"],
        "duration_ms": duration_ms,
    }


@app.post("/intents/trigger-entity-sync")
async def trigger_entity_sync():
    """Publish MQTT event to trigger entity sync without running a full import."""
    try:
        _publish_mqtt(
            "alice/ha/sync",
            {"event": "templates_updated", "source": "github"},
        )
    except Exception as exc:
        logger.error("MQTT publish failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"MQTT publish failed: {exc}",
        )

    return {"published": True}
