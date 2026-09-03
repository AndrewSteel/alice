-- ============================================================
-- Migration 068 — PROJ-83: HA-Agent variable Intents.
-- Adds the cover.set_cover_position intent template so the
-- HA_FAST path can recognise "Rolladen auf X Prozent" commands.
-- Percent-value patterns use the {value} placeholder; the
-- alice-ha-sync worker expands them to the discrete anchor
-- values (10/25/50/75/100) with parameter key `position`
-- (see _DOMAIN_VALUE_EXPANSIONS["cover"]). The exact spoken
-- value is re-extracted at request time in alice-chat-stream.
-- Apply against the alice database after init-schema.sql, then
-- publish an MQTT templates_updated event so the worker runs a
-- full re-sync and the new utterances land in Weaviate.
-- Safe to re-run (idempotent on the domain/intent pair).
-- ============================================================

INSERT INTO alice.ha_intent_templates
    (domain, intent, service, patterns, default_parameters,
     requires_confirmation, language, priority, is_active, source, notes)
VALUES (
    'cover',
    'set_position',
    'cover.set_cover_position',
    '[
        "Rolladen in der {area} auf {value} Prozent",
        "Rolladen in der {area} auf {value} Prozent stellen",
        "Rolladen in der {area} auf {value} Prozent fahren",
        "Rolladen {name} auf {value} Prozent",
        "Rolladen {name} auf {value} Prozent stellen",
        "Jalousie {name} auf {value} Prozent",
        "{name} auf {value} Prozent stellen"
    ]'::jsonb,
    '{}'::jsonb,
    false,
    'de',
    55,
    true,
    'seed',
    'PROJ-83 — variable cover position. {value} expanded to percent anchors by alice-ha-sync; exact value re-extracted in alice-chat-stream.'
)
ON CONFLICT ON CONSTRAINT uq_ha_intent_templates_domain_intent_lang
DO UPDATE SET
    service            = EXCLUDED.service,
    patterns           = EXCLUDED.patterns,
    default_parameters = EXCLUDED.default_parameters,
    priority           = EXCLUDED.priority,
    is_active          = TRUE,
    notes              = EXCLUDED.notes,
    updated_at         = NOW();
