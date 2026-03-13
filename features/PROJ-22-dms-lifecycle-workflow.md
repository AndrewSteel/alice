# PROJ-22: DMS Lifecycle Workflow (alice-dms-lifecycle)

## Status: Planned
**Created:** 2026-03-12
**Last Updated:** 2026-03-12

## Dependencies
- Requires: PROJ-19 (DMS Processor) — Redis-Mappings `path_to_hash` und `hash_to_paths` müssen befüllt werden
- Requires: PROJ-21 (DMS Lifecycle Management) — Scanner muss `alice/dms/lifecycle` Queue befüllen
- Weaviate Collections mit `additional_paths` Feld müssen existieren (PROJ-21 Schema-Erweiterung)

## Overview

Neuer eigenständiger n8n Workflow `alice-dms-lifecycle`. Er abonniert die MQTT-Queue `alice/dms/lifecycle` (befüllt vom Scanner in PROJ-21) und verarbeitet eingehende Lifecycle-Ereignisse in Echtzeit:

| Action | Beschreibung | Weaviate-Operation |
|---|---|---|
| `add_path` | Datei mit bekanntem Inhalt an neuem Pfad gefunden (Duplikat) | PATCH: `additional_paths` Array erweitern |
| `update_path` | Datei verschoben — Originalpfad existiert nicht mehr | PATCH: `original_path` auf neuen Pfad setzen |

Kein LLM-Aufruf, keine Textextraktion. Der Workflow führt ausschließlich Weaviate-PATCH-Operationen und Redis-Updates durch. Dadurch ist er leichtgewichtig und kann in Echtzeit auf jeden eingehenden MQTT-Event reagieren.

**Abgrenzung zu alice-dms-processor (PROJ-19):**
- Processor: nächtlicher Batch, LLM-intensiv, neue Dokumente vollständig verarbeiten
- Lifecycle: event-getrieben, kein LLM, bestehende Weaviate-Einträge aktualisieren

## User Stories

- Als System möchte ich, dass Pfadänderungen (Verschiebungen, Duplikate) unmittelbar nach dem nächsten Scanner-Lauf in Weaviate reflektiert werden, damit Suchergebnisse nicht auf veraltete Pfade zeigen.
- Als System möchte ich, dass Lifecycle-Operationen den nächtlichen Processor-Lauf nicht belasten, damit LLM-Ressourcen für Klassifikation und Extraktion frei bleiben.

## Acceptance Criteria

- [ ] n8n Workflow `alice-dms-lifecycle` existiert und ist aktiv
- [ ] Trigger: MQTT Trigger auf Topic `alice/dms/lifecycle`
- [ ] Eingehende Nachricht wird geparst; `action`-Feld bestimmt den Verarbeitungspfad
- [ ] **`action: "add_path"`**:
  - [ ] Weaviate-Lookup: Objekt mit `file_hash == message.file_hash` finden (alle 6 Collections)
  - [ ] Falls gefunden: PATCH — `additional_paths` Array um `file_path` erweitern
  - [ ] Redis: `HSET alice:dms:path_to_hash <file_path> <file_hash>`
  - [ ] Redis: `SADD alice:dms:hash_to_paths:<hash> <file_path>`
  - [ ] MQTT: Erfolgsmeldung an `alice/dms/done` (mit `action: "add_path"`)
- [ ] **`action: "update_path"`**:
  - [ ] Weaviate-Lookup: Objekt mit `file_hash == message.file_hash` finden (alle 6 Collections)
  - [ ] Falls gefunden: PATCH — `original_path` auf `message.file_path` setzen
  - [ ] Redis: alte Pfade aus `alice:dms:path_to_hash` entfernen (`HDEL` für jeden Pfad in `message.old_paths`)
  - [ ] Redis: `HSET alice:dms:path_to_hash <file_path> <file_hash>` (neuer Pfad)
  - [ ] Redis: `SREM alice:dms:hash_to_paths:<hash>` für jeden alten Pfad
  - [ ] Redis: `SADD alice:dms:hash_to_paths:<hash> <file_path>` (neuer Pfad)
  - [ ] MQTT: Erfolgsmeldung an `alice/dms/done` (mit `action: "update_path"`)
- [ ] Bei unbekanntem `action`-Wert: Warnung loggen, Nachricht verwerfen
- [ ] Bei Weaviate-Fehler: MQTT `alice/dms/error` publizieren; Redis-Updates werden nicht durchgeführt (Konsistenz)
- [ ] Bei nicht gefundenem Weaviate-Objekt: Warnung loggen, Redis-Updates trotzdem durchführen (Resilience)

## Workflow-Struktur (n8n)

```
MQTT Trigger: alice/dms/lifecycle
  ↓
Code: JSON parsen + action validieren
  ↓
Switch: action == ?
  ↓                          ↓
"add_path"              "update_path"
  ↓                          ↓
HTTP GET: Weaviate       HTTP GET: Weaviate
(Suche nach file_hash)   (Suche nach file_hash)
  ↓                          ↓
HTTP PATCH: Weaviate     HTTP PATCH: Weaviate
additional_paths++       original_path = neu
  ↓                          ↓
Redis: HSET path_to_hash + SADD hash_to_paths (neu)
Redis: HDEL/SREM alte Pfade (nur update_path)
  ↓
MQTT: alice/dms/done
```

## Edge Cases

- **Weaviate-Objekt nicht gefunden** (Hash existiert in Redis, aber nicht in Weaviate — z.B. manuell gelöscht): Warnung ins Log; Redis-Mappings werden trotzdem aktualisiert. Kein Fehler-Event.
- **Collection unbekannt** (Weaviate-Suche über alle 6 Collections nötig): Sequentielle Suche in allen Collections bis Treffer gefunden; bei keinem Treffer → "Objekt nicht gefunden" Edge Case.
- **Mehrere Objekte mit gleichem Hash** (theoretisch nicht möglich bei korrekter PROJ-19 Dedup-Logik, aber defensiv behandeln): Nur das erste gefundene Objekt wird gepatcht; Warnung ins Log.
- **MQTT-Nachricht malformed** (kein `action`, kein `file_hash`): Nachricht wird verworfen; Fehler ins Execution Log.
- **Redis nicht erreichbar**: Weaviate-PATCH wird trotzdem versucht; Redis-Updates schlagen fehl → MQTT `alice/dms/error` mit Hinweis auf inkonsistenten Redis-State.

## Technical Requirements

- **Trigger**: MQTT Trigger Node auf `alice/dms/lifecycle` (QoS 1)
- **Weaviate-Suche**: HTTP GET über alle 6 Collections — Suche nach `file_hash` Feld
- **Weaviate-PATCH**: HTTP PATCH an `http://weaviate:8080/v1/objects/<collection>/<id>`
- **n8n Credentials**: `mqtt-alice`, `redis-alice`
- **Keine neuen Credentials** — gleiche wie PROJ-19
- **Workflow-Datei**: `workflows/core/alice-dms-lifecycle.json`

## Benötigte n8n Credentials

| Credential | Verwendung |
|---|---|
| `mqtt-alice` | Trigger (lifecycle), Done/Error-Notifications |
| `redis-alice` | path_to_hash + hash_to_paths aktualisieren |

---
<!-- Sections below are added by subsequent skills -->

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
