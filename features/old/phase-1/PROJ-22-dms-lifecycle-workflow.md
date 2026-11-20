# PROJ-22: DMS Lifecycle Workflow (alice-dms-lifecycle)

## Status: Deployed
**Created:** 2026-03-12
**Last Updated:** 2026-03-14

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

## Tech Design (Solution Architect)

See **PROJ-21 Tech Design** for the full architecture covering scanner, MQTT queue, Weaviate schema, and this workflow as a producer-consumer pair.

---

<!-- Sections below are added by subsequent skills -->

## QA Test Results

### Re-Test #1 (2026-03-13)

**Tested:** 2026-03-13
**Scope:** Re-test after bug fixes. Static code review of `workflows/core/alice-dms-lifecycle.json` (no browser UI -- backend-only feature)
**Tester:** QA Engineer (AI)
**Trigger:** Fixes applied for BUG-4 (GraphQL injection) and BUG-7 (missing error handler)

### Bug Fix Verification

#### BUG-4 (Critical): GraphQL injection via file_hash -- VERIFIED FIXED
- [x] `Code: Weaviate Find by Hash` now sanitizes: `const fileHash = String(rawHash).replace(/[^a-zA-Z0-9:]/g, '')`
- [x] Warns on sanitization: `console.warn` when sanitized value differs from original
- [x] Guards against empty hash: throws if sanitized hash is empty string
- [x] Regex allows valid SHA-256 format (`sha256:<hex>`) while stripping injection characters

#### BUG-7 (Medium): Missing MQTT error handler -- VERIFIED FIXED (with caveat)
- [x] Error Trigger node added with proper ID
- [x] Code: Format Error node extracts error metadata (message, node, execution_id, timestamp)
- [x] MQTT: Publish Error node publishes to `alice/dms/error` with QoS 1 via mqtt-alice credential
- [x] Connections: Error Trigger -> Code: Format Error -> MQTT: Publish Error
- [ ] BUG-9: NEW -- `errorWorkflow` setting missing from workflow JSON. The Error Trigger node requires n8n's `Settings > Error Workflow` to point to this workflow's own ID. Without it, the error chain is dead code. See PROJ-21 BUG-9 for details.

### Acceptance Criteria Status (re-verified)

#### AC-1: Workflow exists and is active
- [x] `workflows/core/alice-dms-lifecycle.json` exists with `"active": true`

#### AC-2: MQTT Trigger on alice/dms/lifecycle
- [x] MQTT Trigger configured with `topics: "alice/dms/lifecycle"`, credential mqtt-alice (Kqy6cn7hyDDXrBA0)

#### AC-3: Message parsing and action routing
- [x] `Code: Parse & Validate` parses JSON, validates required fields, discards unknown actions

#### AC-4: action: "add_path"
- [x] Weaviate lookup across all 6 collections by sanitized `file_hash`
- [x] PATCH appends to `additionalPaths` with deduplication via `Set`
- [x] Redis: `HSET path_to_hash` + `SADD hash_to_paths`
- [x] MQTT done to `alice/dms/done` with `action: "add_path"`

#### AC-5: action: "update_path"
- [x] Weaviate lookup across all 6 collections by sanitized `file_hash`
- [x] PATCH sets `filePath` to new path
- [x] Redis: `HDEL` + `SREM` old paths, `HSET` + `SADD` new path
- [x] MQTT done to `alice/dms/done` with `action: "update_path"`

#### AC-6: Unknown action handling
- [x] Returns empty array, logs warning

#### AC-7: Weaviate error handling
- [x] Weaviate PATCH failure throws error (structurally handled by Error Trigger chain)
- [ ] BUG-9: Error Trigger chain will not fire until `errorWorkflow` is configured post-deploy

#### AC-8: Weaviate object not found
- [x] Warning logged, `_weaviate_patched: false`, Redis still updated, done message sent

### Edge Cases Status

#### EC-1: Weaviate object not found
- [x] Handled: warning logged, Redis updated, done message sent

#### EC-2: Collection search across all 6
- [x] Sequential search, breaks on first match

#### EC-3: Multiple objects with same hash
- [x] `limit: 1` returns first match (defensive, PROJ-19 dedup prevents duplicates)

#### EC-4: Malformed MQTT message
- [x] Missing fields throw error, invalid JSON throws parse error

#### EC-5: Redis not reachable
- [x] Redis failure throws error, caught by Error Trigger chain (once BUG-9 is resolved)

### Security Audit Results

- [x] GraphQL injection mitigated -- file_hash sanitized (BUG-4 fix verified)
- [x] No secrets hardcoded -- Redis password from `$env` with try/catch
- [x] No external-facing endpoints
- [x] MQTT credential IDs verified correct
- [x] Weaviate calls internal Docker network only

### New Bugs Found (Re-Test)

#### BUG-9: errorWorkflow setting missing (shared with PROJ-21)
- See PROJ-21 BUG-9 for full details
- **Severity:** Medium
- **Impact:** Error handler chain is structurally correct but inactive until post-deploy configuration
- **Priority:** Add to deployment checklist

### Previously Reported Bugs -- Final Status

| Bug | Severity | Status |
|-----|----------|--------|
| BUG-4 | Critical | FIXED and verified |
| BUG-7 | Medium | FIXED (structurally), limited by BUG-9 |
| BUG-9 | Medium | NEW -- deployment config item |

### Summary
- **Acceptance Criteria:** 8/8 passed (AC-7 structurally fixed, pending deploy config)
- **Previous Bugs Fixed:** 2/2 verified (BUG-4, BUG-7)
- **New Bugs Found:** 1 (BUG-9, Medium -- deployment config, not a code defect)
- **Security:** All previous findings resolved. No new security issues.
- **Production Ready:** YES (conditional)
- **Conditions:** BUG-9 must be addressed during deployment (set errorWorkflow in n8n UI after import).

## Deployment

**Deployed:** 2026-03-14

### Deployed Artifacts
- `workflows/core/alice-dms-lifecycle.json` — new MQTT-triggered workflow

### Post-Deploy Action Required
After importing into n8n, configure:
**Settings → Error Workflow → select `alice-dms-lifecycle`** so the Error Trigger node activates on execution failures and publishes to `alice/dms/error`.
