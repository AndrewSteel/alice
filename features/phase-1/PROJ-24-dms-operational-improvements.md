# PROJ-24: DMS Operational Improvements (Stats, LLM-Retry, MQTT-Reliability, Error-Handler)

## Status: Deployed
**Created:** 2026-03-15
**Last Updated:** 2026-03-15

## Dependencies
- Requires: PROJ-16 (DMS Scanner) — Workflow `alice-dms-scanner` muss deployed sein
- Requires: PROJ-18 (DMS Text-Extractor-Container) — alle 4 Extractor-Container müssen deployed sein
- Requires: PROJ-19 (DMS Processor) — Workflow `alice-dms-processor` muss deployed sein
- Requires: PROJ-22 (DMS Lifecycle Workflow) — Workflow `alice-dms-lifecycle` muss deployed sein

## Overview

Behebung von fünf Zuverlässigkeits- und Betriebsqualitäts-Findings aus den QA-Runden von PROJ-16, PROJ-18, PROJ-19, PROJ-21 und PROJ-22. Keine Sicherheitsrelevanz — alle Findings betreffen Monitoring, Retry-Mechanismen und Fehlerbehandlung.

| Bug | Komponente | Schweregrad | Beschreibung |
|-----|------------|-------------|--------------|
| PROJ-16 BUG-2 | `alice-dms-scanner` (n8n) | Medium | Keine finale Stats-Aggregation nach dem File-Loop |
| PROJ-19 BUG-6 | `alice-dms-processor` (n8n) | Medium | Kein LLM-Retry bei ungültigem JSON (Spec: 1× Retry) |
| PROJ-21/22 BUG-9 | `alice-dms-lifecycle` (n8n) | Medium | `errorWorkflow`-Setting fehlt → Error-Trigger-Chain nie aktiv |
| PROJ-18 BUG-5 | Alle 4 Extractor-Container | Low | MQTT `clean_session=true` → Nachrichtenverlust bei Container-Neustart |
| PROJ-18 BUG-4 | `dms-extractor-office` | Low | `shutil.copy2` statt `shutil.copy` → potenzielle Metadaten-Fehler auf NAS |

## User Stories

- Als Admin möchte ich nach jedem Scanner-Lauf eine aggregierte Zusammenfassung (`scanned_dirs`, `scanned_files`, `new_files`, `skipped_files`, `errors`) im Execution Log sehen, damit ich auf einen Blick erkennen kann, ob der Scan wie erwartet verlaufen ist.
- Als System möchte ich bei einem ungültigen LLM-JSON-Response die Anfrage einmalig wiederholen, bevor auf den Fallback-Dokumenttyp "Document" zurückgefallen wird, damit vorübergehende LLM-Ausreißer nicht zu Qualitätsverlust führen.
- Als System möchte ich, dass der `alice-dms-lifecycle` Error-Trigger-Handler bei Workflow-Fehlern tatsächlich feuert und Fehlermeldungen an `alice/dms/error` publiziert, damit Weaviate/Redis-Inkonsistenzen sichtbar werden.
- Als System möchte ich, dass die Extractor-Container bei einem Neustart keine MQTT-Nachrichten verlieren, die während der Downtime eintreffen, damit eine kurze Restart-Periode nicht zu übersprungenen Dateien führt.
- Als System möchte ich, dass der Office-Extractor Dateien vom NAS mit `shutil.copy` statt `shutil.copy2` kopiert, damit restriktive NAS-Metadaten keine Extraktionsfehler erzeugen.

## Acceptance Criteria

### Fix 1: Scanner Stats-Aggregation (PROJ-16 BUG-2)

- [ ] Workflow `alice-dms-scanner`: nach dem Ende des File-Loops (`Loop: Files` Output 0 = done) existiert ein neuer Summary-Code-Node
- [ ] Summary-Node liest die akkumulierten Zähler (`new_files`, `skipped_files`, `errors`) aus dem Loop und gibt sie als finales Execution-Log-Item aus
- [ ] Ausgabe-Format: `{ scanned_dirs, scanned_files, new_files, skipped_files, errors, runtime_seconds }`
- [ ] Bei leerem Scan (kein Ordner / keine Dateien): vorhandene `Set: Empty Stats` und `Set: No Files Stats` Nodes werden um `runtime_seconds` ergänzt
- [ ] Kein bestehendes Scan-Verhalten wird geändert

### Fix 2: LLM-Retry in Processor (PROJ-19 BUG-6)

- [ ] Workflow `alice-dms-processor`: `Code: Parse Classify Result` implementiert einen 1× Retry wenn JSON-Parse fehlschlägt
- [ ] Retry: erneuter HTTP-Call an Ollama mit identischem Prompt; Timeout 30s
- [ ] Bei erneutem Fehler: Fallback auf `document_type: "Document"`, leeres Feldobjekt, `_llm_retry_failed: true` ins Item
- [ ] Analog: `Code: Parse Extract Result` implementiert einen 1× Retry bei JSON-Parse-Fehler der Feldextraktion
- [ ] Stats-Zähler `llm_retries` und `llm_retry_failures` werden in `alice:dms:run:stats` ergänzt

### Fix 3: errorWorkflow-Konfiguration (PROJ-21/22 BUG-9)

- [ ] n8n Workflow `alice-dms-lifecycle` hat nach dem Deploy in n8n das Setting **Settings → Error Workflow → `alice-dms-lifecycle`** konfiguriert (Workflow zeigt auf sich selbst)
- [ ] Nach der Konfiguration: Ein manuell erzeugter Workflow-Fehler (Test-Execution mit falschem Weaviate-Host) führt dazu, dass der Error-Trigger feuert und eine Nachricht an `alice/dms/error` publiziert wird
- [ ] Deploy-Checklist in PROJ-22 Deployment-Sektion wird mit diesem Schritt ergänzt
- [ ] Kein Code-Änderung erforderlich — dies ist ein Post-Deploy-Konfigurationsschritt

### Fix 4: MQTT Persistent Sessions in Extractor-Containern (PROJ-18 BUG-5)

- [ ] Alle vier Node.js Extractor-Container (`dms-extractor-pdf`, `dms-extractor-txt`): `mqtt.connect()` mit `clean: false` (statt `true`) und stabiler `clientId` (z.B. `dms-extractor-pdf` ohne Timestamp-Suffix)
- [ ] Beide Python Extractor-Container (`dms-extractor-ocr`, `dms-extractor-office`): `mqtt.Client(client_id="dms-extractor-ocr", clean_session=False)`
- [ ] Alle 4 Container erhalten einen stabilen, eindeutigen `clientId` ohne zufälligen Suffix
- [ ] Bestehende MQTT-Subscription-Logik (QoS 1, Topic, Reconnect) bleibt unverändert
- [ ] Container-Rebuild und Re-Deploy nach Code-Änderung

### Fix 5: shutil.copy statt shutil.copy2 (PROJ-18 BUG-4)

- [ ] `dms-extractor-office/main.py`: `shutil.copy2(src, tmp_path)` → `shutil.copy(src, tmp_path)`
- [ ] Kein weiterer Änderungsaufwand — single-line fix

## Edge Cases

- **Fix 1 – Stats-Zähler gehen verloren bei Workflow-Abbruch**: Stats werden nur im finalen Node ausgegeben, nicht in Redis persistiert — bei Abbruch kein Execution-Log-Summary, akzeptables Verhalten
- **Fix 2 – LLM beim Retry vollständig nicht erreichbar**: Retry schlägt nach Timeout (30s) fehl → Fallback auf "Document" wie heute; `llm_retry_failures` wird hochgezählt
- **Fix 2 – Retry liefert wiederum ungültiges JSON**: Fallback, kein weiterer Retry (max. 1× Retry gemäß Spec)
- **Fix 3 – errorWorkflow auf sich selbst zeigen, Endlosschleife?**: n8n erkennt zirkuläre Error-Workflows und bricht nach einer Ebene ab — kein echtes Risiko
- **Fix 4 – Zwei Container-Instanzen mit gleicher clientId**: MQTT-Broker trennt die ältere Verbindung; da wir nur eine Instanz pro Container betreiben, kein Problem
- **Fix 4 – Nachrichten im Broker für offline Container**: QoS 1 + `clean: false` → Broker hält Nachrichten bis Container wieder verbunden ist (max. MQTT-Broker-Retention); lange Downtime kann zu Backlog führen — akzeptables Verhalten
- **Fix 5 – NAS-Datei ohne Leseberechtigung**: `shutil.copy` schlägt ebenfalls fehl; kein Unterschied in diesem Fall

## Technical Requirements

- **Betroffene n8n Workflows**: `alice-dms-scanner`, `alice-dms-processor`, `alice-dms-lifecycle`
- **Betroffene Container**: `dms-extractor-pdf`, `dms-extractor-ocr`, `dms-extractor-txt`, `dms-extractor-office`
- **n8n Workflow-Dateien**: `workflows/core/alice-dms-scanner.json`, `workflows/core/alice-dms-processor.json`
- **Container-Dateien**: `docker/compose/automations/dms-extractor-[pdf|ocr|txt|office]/main.[js|py]`
- **Keine DB-Migrationen** erforderlich
- **Keine nginx-Änderungen** erforderlich
- **Kein Frontend-Eingriff** erforderlich
- **Deploy-Reihenfolge**:
  1. n8n Workflows updaten (Scanner, Processor)
  2. Container neu bauen und starten (4× `make rebuild`)
  3. Post-Deploy: `alice-dms-lifecycle` errorWorkflow-Setting in n8n UI konfigurieren

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Scope Overview

This feature touches **two n8n workflows** and **four Docker containers**. No database migrations, no frontend changes, no new services. All five fixes are independent and can be built and deployed separately.

### Fix 1 — Scanner Stats-Aggregation (`alice-dms-scanner`)

**What changes:** A new Summary node is added at the very end of the scanner workflow, after the file loop finishes.

**Current state:** The scanner loop (`Loop: Files`) publishes files to MQTT and marks them as queued in Redis, but never produces a final summary. The two early-exit paths (`Set: Empty Stats`, `Set: No Files Stats`) already exist but lack `runtime_seconds`.

**New node placement:**
```
Loop: Files (done output)
    └── Code: Summary Stats (NEW)
            → logs { scanned_dirs, scanned_files, new_files,
                     skipped_files, errors, runtime_seconds }
```

**How it works:** The scanner already tracks counters per file through the loop. The Summary node reads those accumulated counters from the loop's pass-through data and emits a single final log item. The two early-exit paths (`Set: Empty Stats`, `Set: No Files Stats`) each get a `runtime_seconds` field added.

**Why no Redis for stats:** Stats only need to appear in the n8n Execution Log for operator review — not persisted between runs. Writing to Redis would add complexity without benefit.

---

### Fix 2 — LLM-Retry in Processor (`alice-dms-processor`)

**What changes:** Two existing Code nodes gain inline retry logic. Two new counters are added to the stats hash.

**Current state:** `Code: Parse Classify Result` and `Code: Parse Extract Result` both call Ollama and then try to parse the JSON response. If parsing fails, they fall back to "Document" immediately — no retry attempt.

**New behavior (both nodes):**
```
HTTP: Ollama [Classify|Extract]
    └── Code: Parse [Classify|Extract] Result
            ├── JSON parse succeeds → proceed normally
            └── JSON parse fails
                    ├── Inline retry HTTP call to Ollama (30s timeout)
                    │       ├── Parse succeeds → proceed, llm_retries++
                    │       └── Parse fails → fallback to "Document",
                    │                         _llm_retry_failed: true,
                    │                         llm_retry_failures++
                    └── (no further retry — max 1× per spec)
```

**Why inline (within the Code node) vs. a separate n8n branch:** The retry is a tight "parse-fail → re-ask" loop requiring the original prompt. Doing this inline avoids restructuring the visual flow and keeps the retry logic co-located with the parse logic. This is consistent with how other HTTP calls in the project are handled in Code nodes (using axios).

**New stats counters** added to `alice:dms:run:stats`:
- `llm_retries` — how many times a retry was attempted
- `llm_retry_failures` — how many retries also failed (leading to "Document" fallback)

---

### Fix 3 — errorWorkflow-Konfiguration (`alice-dms-lifecycle`)

**What changes:** Nothing in code. This is a one-time UI configuration step in the n8n admin interface.

**What needs to happen post-deploy:**
```
n8n UI → alice-dms-lifecycle → Settings → Error Workflow → alice-dms-lifecycle
```

The workflow already contains an Error Trigger node and MQTT publish logic for errors — it just isn't wired up as its own error handler. Without this setting, n8n never calls the Error Trigger.

**Why self-referencing works:** n8n's Error Workflow mechanism invokes the named workflow when any execution of the source workflow fails at the top level. Pointing it at itself is the standard pattern for "handle my own errors." n8n prevents infinite loops by not re-triggering error handling if the error workflow itself fails.

**Deploy checklist entry:** The PROJ-22 deployment section will be updated to include this manual step.

---

### Fix 4 — MQTT Persistent Sessions (4 Extractor Containers)

**What changes:** One-line config change per container (2 Node.js, 2 Python).

**Current state — the problem:**
```
clientId: 'dms-extractor-pdf-1741234567890'   ← random on every start
clean: true                                     ← broker forgets subscriptions on disconnect
```

With `clean: true`, when a container restarts, the MQTT broker discards any queued messages. The container starts fresh with a new random ID and immediately misses everything that arrived during the downtime.

**New state — the fix:**
```
clientId: 'dms-extractor-pdf'   ← stable, unique, deterministic
clean: false                     ← broker holds messages until container reconnects
```

With `clean: false` + stable clientId, the broker retains QoS 1 messages for the offline client and delivers them as soon as the container reconnects. This requires the clientId to be stable across restarts — random suffixes break the association.

**Affected files:**
| Container | Language | File |
|-----------|----------|------|
| `dms-extractor-pdf` | Node.js | `main.js` |
| `dms-extractor-txt` | Node.js | `main.js` |
| `dms-extractor-ocr` | Python | `main.py` |
| `dms-extractor-office` | Python | `main.py` |

All four containers require rebuild and re-deploy after the change.

---

### Fix 5 — shutil.copy vs shutil.copy2 (`dms-extractor-office`)

**What changes:** One line in `dms-extractor-office/main.py`.

**Current:** `shutil.copy2` — copies file + preserves source metadata (timestamps, permissions)

**New:** `shutil.copy` — copies file + sets standard permissions, ignores source metadata

**Why it matters:** NAS shares (SMB/NFS) often have restrictive metadata on files (read-only timestamps, extended attributes). When `shutil.copy2` tries to preserve those onto the temp copy, it may fail with a permission error. `shutil.copy` writes fresh metadata for the temp file, which is always writable. Since this is only a temp working copy (discarded after LibreOffice conversion), preserving source metadata has no value.

---

### Component Map

```
alice-dms-scanner (n8n)
    └── [Fix 1] + Code: Summary Stats node
    └── [Fix 1] + runtime_seconds in Set: Empty Stats, Set: No Files Stats

alice-dms-processor (n8n)
    └── [Fix 2] Code: Parse Classify Result  ← inline retry + new counters
    └── [Fix 2] Code: Parse Extract Result   ← inline retry + new counters

alice-dms-lifecycle (n8n)
    └── [Fix 3] Post-deploy UI config only (no code change)

dms-extractor-pdf / dms-extractor-txt (Node.js containers)
    └── [Fix 4] MQTT clientId stable + clean: false

dms-extractor-ocr / dms-extractor-office (Python containers)
    └── [Fix 4] MQTT client_id stable + clean_session=False
    └── [Fix 5] office only: shutil.copy2 → shutil.copy
```

### Deploy Order

1. Update `alice-dms-scanner.json` + `alice-dms-processor.json` → deploy both n8n workflows
2. Rebuild + restart all 4 extractor containers (`make rebuild` × 4)
3. Post-deploy: configure `alice-dms-lifecycle` error workflow in n8n UI

### No New Dependencies

All fixes use existing libraries and infrastructure. No new packages, no schema changes, no new services.

## QA Test Results

**Tested:** 2026-03-15
**Tester:** QA Engineer (AI)
**Method:** Static code review of all diffs (n8n workflow JSON + container source code). No frontend or browser testing required (backend-only changes).

### Acceptance Criteria Status

#### Fix 1: Scanner Stats-Aggregation (PROJ-16 BUG-2)

- [x] AC-1.1: New `Code: Summary Stats` node exists after `Loop: Files` done output (node ID `summary-stats-01-alice-dms-scanner-v1`, connected from `Loop: Files` output 0)
- [x] AC-1.2: Summary node reads accumulated counters from `$('Code: Lifecycle Check').all()` and `$('Code: Hash + Size').all()` and aggregates `new_files`, `skipped_files`, `errors`
- [x] AC-1.3: Output format matches spec: `{ scanned_dirs, scanned_files, new_files, skipped_files, errors, runtime_seconds }` -- all six fields present
- [x] AC-1.4: `Set: Empty Stats` and `Set: No Files Stats` nodes both have `runtime_seconds` field added (type: number, value: 0)
- [x] AC-1.5: No existing scan behavior changed -- only new node added at loop end, existing connections preserved

#### Fix 2: LLM-Retry in Processor (PROJ-19 BUG-6)

- [x] AC-2.1: `Code: Parse Classify Result` implements 1x retry on JSON parse failure via inline axios call
- [x] AC-2.2: Retry uses identical prompt (reconstructed from `$('IF: Auto Classify').first().json.plaintext`), timeout set to 30000ms (30s)
- [x] AC-2.3: On retry failure, falls back to `document_type: "Document"`, sets `_llm_retry_failed: true` on the item
- [x] AC-2.4: `Code: Parse Extract Result` implements analogous 1x retry using `item._extraction_prompt` (set upstream by `Code: Build Extraction Prompt`)
- [x] AC-2.5: Stats counters `llm_retries` and `llm_retry_failures` initialized to '0' in `Code: Init Run` and incremented via `hIncrBy` in both parse nodes

#### Fix 3: errorWorkflow-Konfiguration (PROJ-21/22 BUG-9)

- [x] AC-3.1: Workflow JSON `alice-dms-lifecycle.json` now contains `"errorWorkflow": "po2OuxzG5htVHK6E"` in settings, which matches the workflow's own ID (`"id": "po2OuxzG5htVHK6E"`) -- self-referencing as required
- [ ] AC-3.2: Manual verification of Error Trigger firing cannot be tested statically -- requires live n8n execution with intentional error (post-deploy validation)
- [x] AC-3.3: PROJ-22 deployment section already contains the post-deploy instruction for errorWorkflow configuration (added during PROJ-22 QA)
- [x] AC-3.4: The implementation exceeds spec requirements -- errorWorkflow is now baked into the JSON rather than being a manual-only post-deploy step. This is superior to the AC requirement and ensures the setting survives workflow re-imports.

#### Fix 4: MQTT Persistent Sessions in Extractor-Containern (PROJ-18 BUG-5)

- [x] AC-4.1 (Node.js): `dms-extractor-pdf/main.js` changed from `clientId: \`dms-extractor-pdf-${Date.now()}\`, clean: true` to `clientId: "dms-extractor-pdf", clean: false`
- [x] AC-4.1 (Node.js): `dms-extractor-txt/main.js` changed from `clientId: \`dms-extractor-txt-${Date.now()}\`, clean: true` to `clientId: "dms-extractor-txt", clean: false`
- [x] AC-4.2 (Python): `dms-extractor-ocr/main.py` changed from `client_id=f"dms-extractor-ocr-{int(time.time())}", clean_session=True` to `client_id="dms-extractor-ocr", clean_session=False`
- [x] AC-4.2 (Python): `dms-extractor-office/main.py` changed from `client_id=f"dms-extractor-office-{int(time.time())}", clean_session=True` to `client_id="dms-extractor-office", clean_session=False`
- [x] AC-4.3: All 4 containers now have stable, unique, deterministic clientIds (no random suffix)
- [x] AC-4.4: Existing MQTT subscription logic (QoS 1, topic names, reconnect settings) remains unchanged in all 4 containers
- [ ] AC-4.5: Container rebuild/re-deploy not yet performed (deployment step)

#### Fix 5: shutil.copy statt shutil.copy2 (PROJ-18 BUG-4)

- [x] AC-5.1: `dms-extractor-office/main.py` line 116 changed from `shutil.copy2(file_path, tmp_src)` to `shutil.copy(file_path, tmp_src)`
- [x] AC-5.2: Single-line change, no other modifications to the file beyond the Fix 4 MQTT changes

### Edge Cases Status

#### EC-1: Fix 1 -- Stats lost on workflow abort
- [x] Acceptable behavior as documented. Summary node is only reached at loop completion. No Redis persistence of intermediate stats.

#### EC-2: Fix 2 -- LLM unreachable during retry
- [x] Handled correctly. axios timeout at 30s catches unreachable Ollama. Falls back to "Document" with `_llm_retry_failed: true` and increments `llm_retry_failures`.

#### EC-3: Fix 2 -- Retry also returns invalid JSON
- [x] Handled correctly. Second `JSON.parse` failure in retry catch block sets `retryFailed = true`, no further retry attempted (max 1x per spec).

#### EC-4: Fix 3 -- errorWorkflow self-reference loop
- [x] n8n prevents recursive error handling. No risk of infinite loop.

#### EC-5: Fix 4 -- Two container instances with same clientId
- [x] Documented as acceptable. MQTT broker disconnects older connection. Single-instance deployment model makes this a non-issue.

#### EC-6: Fix 4 -- Messages queued during long container downtime
- [x] Documented as acceptable. QoS 1 + `clean: false` means broker retains messages up to its configured retention limit.

#### EC-7: Fix 5 -- NAS file without read permission
- [x] `shutil.copy` also fails on unreadable files. No behavioral difference from `shutil.copy2` in this case.

### Additional Edge Case Found

#### EC-8: Fix 2 -- Parse Classify Result retry prompt drift risk
- The retry in `Code: Parse Classify Result` reconstructs the classify prompt inline rather than reusing the original HTTP request body. While the current prompt text matches the one in `HTTP: Ollama Classify`, future changes to one must be mirrored in the other manually. This is a maintenance risk, not a bug.

### Security Audit Results

- [x] No authentication/authorization changes -- not applicable (backend pipeline, no user-facing endpoints)
- [x] No new API endpoints exposed
- [x] No secrets hardcoded -- Redis password accessed via `$env.REDIS_PASSWORD` with try/catch fallback
- [x] No injection vectors -- MQTT messages are JSON-parsed with try/catch, invalid messages discarded
- [x] Ollama URL hardcoded as `http://ollama-3090:11434` -- internal Docker network only, not externally accessible
- [x] No new dependencies introduced
- [x] MQTT topics unchanged (`alice/dms/*`) -- no new attack surface
- [ ] BUG: See BUG-1 below regarding information leakage on MQTT Done topics

### Regression Check

- [x] `alice-dms-scanner.json`: Only additions (new node + connections + runtime_seconds fields). No existing nodes modified. No risk of regression.
- [x] `alice-dms-processor.json`: Parse Classify and Parse Extract nodes modified with additive retry logic. Original happy-path untouched (parse succeeds on first try -> no retry code executes). Init Run node adds two new hash fields -- no impact on existing counters.
- [x] `alice-dms-lifecycle.json`: Node IDs changed (likely from n8n re-export), positions updated, `pinData` and additional settings added. Error Trigger chain unchanged structurally.
- [ ] BUG: See BUG-1 below -- MQTT Done nodes lost their `message` property (regression).
- [x] Extractor containers: Only MQTT client config changed. Message handling, Redis push, heartbeat, extraction logic all unchanged.

### Bugs Found

#### BUG-1: MQTT Done nodes in lifecycle workflow lost `message` property (REGRESSION)
- **Severity:** Medium
- **Component:** `workflows/core/alice-dms-lifecycle.json`
- **Steps to Reproduce:**
  1. Compare the current `alice-dms-lifecycle.json` with `git show HEAD:workflows/core/alice-dms-lifecycle.json`
  2. Observe that `MQTT: Done (add_path)` previously had a `message` parameter with structured JSON: `{ action, file_hash, file_path, weaviate_patched, new_paths_count, timestamp }`
  3. Observe that `MQTT: Done (update_path)` previously had a `message` parameter with structured JSON: `{ action, file_hash, file_path, old_paths, weaviate_patched, timestamp }`
  4. Both nodes now only have `{ "topic": "alice/dms/done", "options": {} }` -- no `message` field
  5. Expected: Structured, curated JSON messages published to `alice/dms/done`
  6. Actual: n8n MQTT node defaults to `sendInputData: true` when no `message` is specified, dumping the entire upstream item (including internal fields like `_weaviate_patched`, Weaviate query results, etc.) to the MQTT topic
- **Impact:** Downstream consumers of `alice/dms/done` will receive a different, larger payload structure than expected. Internal implementation details leak to the MQTT topic.
- **Root Cause:** Likely the workflow was re-exported from n8n UI after manual edits, and the n8n UI dropped the `message` field because the default `sendInputData` behavior covers it. However, the structured message format is intentional and important.
- **Priority:** Fix before deployment

#### BUG-2: Early-exit stats nodes use hardcoded runtime_seconds=0 instead of computed value
- **Severity:** Low
- **Component:** `workflows/core/alice-dms-scanner.json` -- `Set: Empty Stats` and `Set: No Files Stats`
- **Steps to Reproduce:**
  1. Trigger scanner when no folders are configured or when folders exist but contain no files
  2. Expected: `runtime_seconds` reflects actual elapsed time since execution start
  3. Actual: `runtime_seconds` is always 0 (hardcoded in the Set node)
- **Impact:** Minor. For early-exit paths, runtime is typically negligible (< 1 second), so a value of 0 is not misleading. However, the `Code: Summary Stats` node computes actual runtime using `$execution.startedAt`, so the behavior is inconsistent between exit paths.
- **Priority:** Nice to have (fix in next sprint)

### Summary

- **Acceptance Criteria:** 18/20 passed, 2 untestable statically (AC-3.2 requires live n8n, AC-4.5 is a deployment step)
- **Bugs Found:** 2 total (0 critical, 0 high, 1 medium, 1 low)
- **Security:** 1 information leakage finding (BUG-1, medium -- internal fields dumped to MQTT topic)
- **Regression:** 1 regression found (BUG-1 -- MQTT Done message property dropped)
- **Production Ready:** NO
- **Recommendation:** Fix BUG-1 (restore `message` property on both MQTT Done nodes in `alice-dms-lifecycle.json`) before deployment. BUG-2 can be deferred.

## Deployment

**Deployed:** 2026-03-15
**Deployed by:** User (manual n8n import + container rebuild)

- n8n workflows `alice-dms-scanner`, `alice-dms-processor`, `alice-dms-lifecycle` imported and active
- All 4 extractor containers rebuilt and restarted
- BUG-1 (MQTT Done message property regression) fixed by user before deployment
- BUG-2 (hardcoded runtime_seconds=0 in early-exit paths) deferred to next sprint
