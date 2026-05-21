# PROJ-19: DMS Processor Workflow (LLM-Klassifikation + Weaviate-Speicherung)

## Status: Deployed
**Created:** 2026-03-09
**Last Updated:** 2026-03-23

## Dependencies
- Requires: PROJ-18 (DMS Extractor Container) — Redis List `alice:dms:plaintext` muss mit extrahierten Texten befüllt sein
- Requires: PROJ-17 (DMS Scanner Multi-Queue) — Scanner muss Dateien in die Extractor-Queues stellen
- Requires: PROJ-15 (DMS Ordnerverwaltung) — `alice.dms_watched_folders` muss existieren
- Weaviate Collections (`Invoice`, `BankStatement`, `Document`, `Email`, `SecuritySettlement`, `Contract`) must exist

## Overview

Implementierung des `alice-dms-processor` n8n Workflows. Er läuft nächtlich, liest fertig extrahierte Plaintext-Einträge aus der Redis List `alice:dms:plaintext` (befüllt von den Extractor-Containern aus PROJ-18) und führt folgende Schritte durch:

1. **LLM-Klassifikation** (nur wenn `suggested_type: auto`) — Qwen3:14b bestimmt den Dokumenttyp
2. **Typenspezifische Feldextraktion** — Qwen3:14b extrahiert strukturierte Felder je Dokumenttyp
3. **Weaviate-Speicherung** — Dokument mit Volltext und Metadaten wird in die passende Collection gespeichert
4. **Redis-Bereinigung** — Hash von `queued_files` entfernen, in `alice:dms:processed` eintragen

Die Textextraktion (PDF, OCR, Office, TXT) findet **nicht** im Processor statt — das ist die Aufgabe der Extractor-Container (PROJ-18). Der Processor erhält bereits fertigen Plaintext aus der Queue.

**Dateien werden nicht verschoben.** Das NAS ist eine Synchronisation von Arbeitsplatz-Rechnern — eine Verschiebung würde Originaldateien auf den Arbeitsplätzen löschen.

Der Workflow läuft nachts und ist auf **2 Stunden** begrenzt, damit nachfolgende nächtliche Analysen ebenfalls auf das LLM zugreifen können. Er verarbeitet Batches à 50 Dateien und stoppt nach Ablauf des Zeitlimits — verbleibende Einträge in der Queue werden in der nächsten Nacht verarbeitet.

## User Stories

- Als System möchte ich Dokumente aller Formate aus der Plaintext-Queue automatisch klassifizieren und in Weaviate speichern, damit neue Dokumente ohne manuellen Aufwand durchsuchbar werden.
- Als System möchte ich den Dokumenttyp via LLM bestimmen lassen, wenn `suggested_type: auto` gesetzt ist, damit auch unstrukturierte Projektordner korrekt klassifiziert werden.
- Als Admin möchte ich, dass fehlerhafte Dokumente (`extraction_failed: true`) ins Fehlerverzeichnis verschoben und in `alice/dms/error` gepublisht werden, damit ich sie manuell prüfen kann.
- Als Admin möchte ich max. 50 Dokumente pro Batch in einem Zeitfernster von 2 Stunden verarbeiten lassen (konfigurierbar), damit der Processor den LLM-Betrieb nicht blockiert.

## Acceptance Criteria

- [ ] n8n Workflow `alice-dms-processor` existiert und ist aktiv
- [ ] Trigger: Schedule, täglich 02:00 Uhr
- [ ] Workflow startet mit Aufzeichnung des Startzeitpunkts und verarbeitet Batches à 50 Dateien in einer Schleife
- [ ] Pro Batch: `LRANGE alice:dms:plaintext 0 49` lesen, verarbeiten, dann `LTRIM alice:dms:plaintext 50 -1`
- [ ] Nach jedem Batch: Prüfung ob Laufzeit < 2 Stunden UND Queue nicht leer → weiterer Batch; sonst Stop
- [ ] Nach 2 Stunden Laufzeit wird kein neuer Batch mehr gestartet — verbleibende Queue-Einträge werden in der nächsten Nacht verarbeitet
- [ ] Nachrichten mit `extraction_failed: true` werden direkt als Fehler behandelt (kein LLM-Aufruf)
- [ ] **LLM-Klassifikation** (Qwen3:14b via Ollama): nur wenn `suggested_type: auto`; bestimmt `document_type`
- [ ] Bei bekanntem `suggested_type` (nicht `auto`): wird direkt als `document_type` übernommen (kein LLM-Klassifikations-Aufruf)
- [ ] **Typenspezifische Feldextraktion** via Qwen3:14b für alle 6 Dokumenttypen (s.u.)
- [ ] Korrekte Weaviate-Collection wird anhand `document_type` gewählt
- [ ] Vor Weaviate-Insert: Prüfung ob bereits ein Eintrag mit `original_path == file_path` existiert → falls ja: DELETE alter Eintrag, dann INSERT (Dateiänderung / Fall 3)
- [ ] Dokument wird in Weaviate gespeichert mit: extrahierten Feldern + `volltext` (max. 10.000 Zeichen) + `original_path` + `file_type`
- [ ] Originaldatei bleibt unverändert auf dem NAS (keine Verschiebung)
- [ ] `file_hash` wird in Redis `alice:dms:processed` eingetragen und aus `alice:dms:queued_files` entfernt
- [ ] Nach erfolgreichem Weaviate-Insert: `alice:dms:path_to_hash` (Redis Hash: Pfad → Hash) und `alice:dms:hash_to_paths:<hash>` (Redis Set: Hash → Pfadmenge) befüllen
- [ ] Erfolgsmeldung wird an `alice/dms/done` gepublisht
- [ ] Bei Fehler (extraction_failed oder LLM/Weaviate-Fehler): Fehler an `alice/dms/error` gepublisht, Datei bleibt auf dem NAS
- [ ] Execution Log: `{ processed, failed, skipped, llm_classified, used_suggested_type, batches_run, runtime_seconds }`
- [ ] LLM-Extraction-Prompts für alle 6 Dokumenttypen definiert

## LLM Extraction Prompts (je Dokumenttyp)

### Rechnung
Extrahierte Felder: `absender`, `empfaenger`, `rechnungsnummer`, `rechnungsdatum` (ISO), `faelligkeitsdatum` (ISO), `gesamtbetrag` (Zahl), `waehrung`, `positionen` (Array), `ust_nummer`, `iban`

### Kontoauszug
Extrahierte Felder: `bank`, `kontoinhaber`, `iban`, `zeitraum_von` (ISO), `zeitraum_bis` (ISO), `anfangssaldo`, `endsaldo`, `waehrung`, `transaktionen` (Array: datum, beschreibung, betrag)

### Dokument (generisch)
Extrahierte Felder: `titel`, `dokumentdatum` (ISO), `absender`, `empfaenger`, `betreff`, `schlagwoerter` (Array), `zusammenfassung`

### Email
Extrahierte Felder: `von`, `an`, `datum` (ISO), `betreff`, `schlagwoerter` (Array), `zusammenfassung`

### WertpapierAbrechnung
Extrahierte Felder: `bank`, `depot_nummer`, `abrechnung_datum` (ISO), `wertpapier_name`, `wertpapier_isin`, `transaktionstyp` (Kauf/Verkauf/Dividende), `stueckzahl`, `kurs`, `gesamtbetrag`, `waehrung`

### Vertrag
Extrahierte Felder: `vertragsart`, `vertragspartner`, `vertragsdatum` (ISO), `laufzeit_beginn` (ISO), `laufzeit_ende` (ISO), `kuendigungsfrist`, `monatlicher_betrag`, `jaehrlicher_betrag`, `waehrung`, `zusammenfassung`

## Edge Cases

- **`extraction_failed: true` in Redis-Eintrag**: Kein LLM-Aufruf, kein Weaviate-Insert. Hash aus `queued_files` entfernt, Fehler an `alice/dms/error` gepublisht (MQTT, Monitoring). Datei bleibt auf dem NAS.
- **LLM gibt ungültiges JSON zurück**: Retry 1×. Bei erneutem Fehler: `document_type: "Dokument"`, leeres Feldobjekt, `extraction_failed: true`.
- **`suggested_type: auto` — LLM kann Typ nicht bestimmen**: Fallback auf `document_type: "Dokument"`.
- **Weaviate nicht erreichbar**: Gesamter Run abgebrochen. Hash verbleibt in `queued_files` (nächste Nacht Retry). Keine Redis-Mappings werden geschrieben.
- **Dateiänderung erkannt (gleicher Pfad, anderer Hash)**: Alter Weaviate-Eintrag wird gelöscht; neuer Eintrag wird eingefügt. Alter Hash-Eintrag in `path_to_hash` und `hash_to_paths` wird überschrieben/ersetzt.
- **Datei am Ursprungsort bereits gelöscht**: Warnung ins Log, trotzdem als verarbeitet markieren (Hash in `alice:dms:processed`, `path_to_hash`, `hash_to_paths` eintragen — Pfad bleibt als bekannter, aber nicht mehr erreichbarer Pfad).
- **2-Stunden-Zeitlimit erreicht**: Workflow stoppt nach aktuellem Batch. Verbleibende Queue-Einträge bleiben erhalten für nächste Nacht. Execution Log enthält `runtime_seconds` und Hinweis auf verbleibende Queue-Größe.
- **`plaintext` leer, `extraction_failed: false`** (Extractor-Fehler nicht korrekt gesetzt): LLM versucht Klassifikation trotzdem; bei leerem Text Fallback auf `document_type: "Dokument"`.
- **Gleicher Hash zweimal in Queue**: Zweites Item wird übersprungen (Redis `alice:dms:processed` Check — gemeinsam mit Scanner-Workflow).
- **Redis List leer**: `LRANGE` gibt leeres Array zurück, Workflow endet sofort mit `processed: 0`.
- **Sehr langer Plaintext (> 10.000 Zeichen)**: Wird für Weaviate auf 10.000 Zeichen gekürzt; voller Text für LLM-Extraktion auf 20.000 Zeichen begrenzt.

## Technical Requirements

- **Trigger**: n8n Schedule Trigger, täglich 02:00 Uhr
- **BATCH_SIZE**: 50 Einträge pro Batch (konfigurierbare Konstante im Workflow)
- **MAX_RUNTIME_SECONDS**: 7200 (2 Stunden, konfigurierbare Konstante im Workflow)
- **LLM**: Ollama `qwen3:14b` via n8n Ollama-Node oder HTTP-Request
- **Input-Queue**: Redis List `alice:dms:plaintext` (von PROJ-18 Extractor-Containern via RPUSH befüllt)
- **Queue-Verarbeitung (Schleife)**: Start-Timestamp setzen → `LRANGE 0 49` lesen → verarbeiten → `LTRIM 50 -1` → Zeitcheck → nächster Batch oder Stop
- **Kein Dateizugriff** — Dateien bleiben auf dem NAS; der Workflow benötigt keinen NAS-Mount und keinen File-Ops Endpoint
- **Keine Textextraktion im Workflow** — Plaintext kommt fertig aus Redis
- **Weaviate-Insert**: HTTP-Request an `http://weaviate:8080/v1/objects`
- **Collection-Mapping**:
  ```
  Invoice              → Invoice
  BankStatement        → BankStatement
  Document             → Document
  Email                → Email
  SecuritySettlement   → SecuritySettlement
  Contract             → Contract
  (fallback)           → Document
  ```
- **n8n Credentials**: Redis (`redis-alice`, Queue-Lesen + State), Ollama (`Ollama 3090`), MQTT (`mqtt-alice`, done/error Notifications)
- **Workflow-Datei**: `workflows/core/alice-dms-processor.json`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

Rein n8n-basierter Batch-Workflow. Kein neuer Container, kein Frontend. Der Processor ist das letzte Glied in der DMS-Pipeline: Er konsumiert fertigen Plaintext aus Redis, lässt ihn vom LLM klassifizieren und extrahieren, und schreibt das Ergebnis in Weaviate.

---

### Workflow-Struktur (n8n)

```
Schedule Trigger (täglich 02:00)
  ↓
Code: Start-Timestamp + Stats-Objekt initialisieren
  ↓
┌─ BATCH-SCHLEIFE ─────────────────────────────────────────────────────┐
│                                                                       │
│  Redis: LRANGE alice:dms:plaintext 0 49 (bis zu 50 Einträge lesen)  │
│    ↓                                                                  │
│  IF: Queue leer? → Schleife beenden                                  │
│    ↓                                                                  │
│  Redis: LTRIM alice:dms:plaintext 50 -1 (gelesene Einträge entfernen)│
│    ↓                                                                  │
│  Split In Batches (jedes Item einzeln verarbeiten)                   │
│    ↓                                                                  │
│  Code: JSON parsen + Duplikat-Check (alice:dms:processed)            │
│    ↓                                                                  │
│  IF: extraction_failed == true?                                       │
│    [JA]  → MQTT: alice/dms/error + SREM queued_files → nächstes Item│
│    [NEIN]→ Weiter                                                    │
│    ↓                                                                  │
│  IF: suggested_type == "auto"?                                        │
│    [JA]  → Ollama LLM: Dokumenttyp bestimmen (Klassifikations-Prompt)│
│    [NEIN]→ Set: document_type = suggested_type                       │
│    ↓                                                                  │
│  Ollama LLM: Typenspezifische Feldextraktion (6 Prompts)            │
│    ↓                                                                  │
│  Code: LLM-JSON parsen + Fallback bei ungültigem JSON (1 Retry)     │
│    ↓                                                                  │
│  HTTP Request: GET → Weaviate (Suche nach original_path)             │
│    ↓                                                                  │
│  IF: Eintrag gefunden? → HTTP DELETE → Weaviate (alter Eintrag)      │
│    ↓                                                                  │
│  HTTP Request: POST → Weaviate /v1/objects (korrekte Collection)     │
│    ↓                                                                  │
│  Redis: SREM queued_files + SADD processed                           │
│       + HSET path_to_hash + SADD hash_to_paths:<hash>                │
│    ↓                                                                  │
│  MQTT: alice/dms/done publizieren                                    │
│    ↓                                                                  │
│  Code: Zeitcheck — elapsed >= MAX_RUNTIME_SECONDS?                   │
│    [JA]  → Schleife beenden (Zeitlimit erreicht)                     │
│    [NEIN]→ Nächster Batch                                            │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
  ↓
Code: Stats aggregieren → Execution Log
```

---

### Komponenten im Detail

#### A) Redis-Queue-Drain mit Zeitlimit

- `LRANGE 0 49` liest, `LTRIM 50 -1` entfernt atomar — kein Item geht verloren
- Leere Queue → Workflow endet sofort mit `processed: 0`
- `BATCH_SIZE = 50` und `MAX_RUNTIME_SECONDS = 7200` als konfigurierbare Konstanten im Workflow
- Nach jedem Batch: Zeitcheck (`now - start_time >= 7200s`) — bei Überschreitung kein weiterer Batch
- Verbleibende Queue-Einträge bleiben erhalten und werden in der nächsten Nacht verarbeitet

#### B) Zwei LLM-Aufrufe (Ollama qwen3:14b)

| Aufruf             | Zweck                                           | Wann                            |
| ------------------ | ----------------------------------------------- | ------------------------------- |
| **Klassifikation** | Bestimmt `document_type` aus Volltext           | Nur wenn `suggested_type: auto` |
| **Feldextraktion** | Extrahiert strukturierte Felder (je Typ anders) | Immer (außer bei Fehler)        |

- LLM-Aufrufe via n8n Ollama-Nodes (Credential: `Ollama 3090`)
- Plaintext für LLM auf 20.000 Zeichen begrenzt (Prompt-Engineering)
- Bei JSON-Parse-Fehler: 1 Retry, dann Fallback auf `document_type: "Dokument"` + leere Felder

#### C) Weaviate-Insert

- HTTP Request POST an `http://weaviate:8080/v1/objects`
- Collection wird anhand `document_type` gewählt (6 Typen + Fallback `Dokument`)
- Payload: extrahierte Felder + `volltext` (max. 10.000 Zeichen) + `original_path` + `file_type`
- Bei Weaviate-Fehler (nicht erreichbar): Run abbrechen, keine Dateien verschieben → nächste Nacht Retry

#### D) Redis-State-Management

```
Nach erfolgreicher Verarbeitung:
  SREM alice:dms:queued_files             <file_hash>
  SADD alice:dms:processed                <file_hash>        ← gemeinsam mit Scanner
  HSET alice:dms:path_to_hash             <file_path> <file_hash>
  SADD alice:dms:hash_to_paths:<hash>     <file_path>

  Bei Dateiänderung (alter Pfad bereits in path_to_hash mit anderem Hash):
  HDEL alice:dms:path_to_hash             <file_path>        ← alten Eintrag löschen
  SREM alice:dms:hash_to_paths:<old_hash> <file_path>        ← aus altem Hash-Set entfernen
  dann normal HSET / SADD mit neuem Hash

Nach Fehler (extraction_failed oder LLM/Weaviate-Fehler):
  SREM alice:dms:queued_files  <file_hash>
  (kein SADD processed, keine path_to_hash / hash_to_paths Einträge)
```

**Übersicht aller Redis-Keys:**

| Key                              | Typ            | Zweck                                                          | Genutzt von                                   |
| -------------------------------- | -------------- | -------------------------------------------------------------- | --------------------------------------------- |
| `alice:dms:plaintext`            | List           | Extrahierte Texte warten auf Klassifikation                    | Extractor (PROJ-18) schreibt, Processor liest |
| `alice:dms:queued_files`         | Set            | Hashes aktuell in Verarbeitung (Processor-intern)              | Processor                                     |
| `alice:dms:processed`            | Set            | Hashes bereits verarbeiteter Dateien (Dedup)                   | Scanner (PROJ-17) + Processor                 |
| `alice:dms:path_to_hash`         | Hash           | Pfad → Hash-Mapping (für Dateiänderungserkennung)              | Processor schreibt; PROJ-21 liest             |
| `alice:dms:hash_to_paths:<hash>` | Set (pro Hash) | Hash → alle bekannten Pfade (1:N für Duplikate/Verschiebungen) | Processor schreibt; PROJ-21 liest             |

#### E) MQTT-Notifications

| Topic             | Zeitpunkt                                      |
| ----------------- | ---------------------------------------------- |
| `alice/dms/done`  | Nach jedem erfolgreich verarbeiteten Dokument  |
| `alice/dms/error` | Bei extraction_failed oder LLM/Weaviate-Fehler |

---

### Benötigte n8n Credentials

| Credential    | Verwendung                                                           |
| ------------- | -------------------------------------------------------------------- |
| `redis-alice` | Queue-Drain, State-Management, path_to_hash + hash_to_paths Mappings |
| `Ollama 3090` | Klassifikation + Feldextraktion                                      |
| `mqtt-alice`  | Done/Error-Notifications                                             |

---

### Daten-Abhängigkeiten (aus PROJ-18)

Das Redis-Item aus der `alice:dms:plaintext` Queue hat folgende Struktur:

```json
{
  "file_path": "/mnt/nas/projekte/kunde-x/2025/rechnung-stadtwerke.pdf",
  "file_hash": "sha256:abc123...",
  "file_type": "pdf",
  "file_size": 125000,
  "suggested_type": "Rechnung",
  "priority": "normal",
  "detected_at": "2026-03-09T10:00:00Z",
  "extracted_at": "2026-03-09T10:01:30Z",
  "extractor": "dms-extractor-pdf",
  "plaintext": "Rechnung\nStadtwerke München GmbH\n...",
  "extraction_failed": false,
  "metadata": {
    "page_count": 2,
    "language": "de",
    "char_count": 1842
  }
}
```

Pflichtfelder (immer vorhanden): `file_path`, `file_hash`, `file_type`, `suggested_type`, `priority`, `detected_at`, `extracted_at`, `extractor`, `plaintext`, `extraction_failed`

Optionale Metadaten je Extraktor: `page_count` (pdf/ocr), `language` (ocr), `char_count` (alle), `encoding` (txt)

---

### Entscheidungen & Begründungen

| Entscheidung                                  | Begründung                                                                                                                                 |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Nachtlauf 02:00 Uhr                           | GPU tagsüber für interaktive Queries frei halten                                                                                           |
| 2-Stunden-Zeitlimit                           | Weitere nächtliche Analysen benötigen ebenfalls das LLM; kein dauerhafter GPU-Block                                                        |
| Mehrere Batches à 50 statt einmalige 50       | Maximale Nutzung des Zeitfensters ohne festes Dokumentlimit                                                                                |
| LTRIM vor SplitInBatches                      | Atomar: kein zweifaches Verarbeiten beim Workflow-Neustart                                                                                 |
| Zwei getrennte LLM-Aufrufe                    | Klassifikation und Extraktion sind unabhängige Aufgaben; erlaubt Bypass der Klassifikation bei bekanntem Typ                               |
| Weaviate-Fehler stoppt Run                    | Konsistenz: lieber nächste Nacht nochmal versuchen als Hash als verarbeitet markieren ohne Weaviate-Eintrag                                |
| Keine Datei-Archivierung                      | NAS ist Synchronisation von Arbeitsplatz-Rechnern; verschobene Dateien würden auf Arbeitsplätzen gelöscht. Dateien bleiben am Originalort. |
| `alice:dms:processed` statt `processed_files` | Vereinheitlichung mit Scanner-Workflow (PROJ-17), der denselben Key für Dedup nutzt                                                        |

---

### Workflow-Datei

`workflows/core/alice-dms-processor.json`

## QA Test Results

**Tested:** 2026-03-12 (initial), 2026-03-12 (re-test after ioredis-to-redis migration), 2026-03-13 (re-test after German-to-English migration), 2026-03-13 (final re-verification)
**Tester:** QA Engineer (AI)
**Method:** Static workflow JSON analysis + schema cross-validation + regression analysis (no browser -- backend n8n workflow)

### Final Re-Verification (2026-03-13)

Full re-read of all implementation files: workflow JSON (1114 lines, all Code nodes), all 6 Weaviate schema files, SQL migration 010, init-weaviate-schema.py, dms-constants.ts, n8n compose config. Confirmed all previous fixes are correctly applied. No new bugs found.

### Re-Test Scope (2026-03-13, earlier)

German-to-English migration of all DMS document types. Full re-verification of workflow, Weaviate schemas, DB migration, and cross-component consistency.

**Migration verification:**
- [x] All 6 Weaviate schema files use English class names: Invoice, BankStatement, Document, Email, SecuritySettlement, Contract
- [x] All 6 Weaviate schema files use English property names (camelCase)
- [x] All 6 schema files include `fileType`, `filePath`, `fileHash`, `fullText`, `summary`, `fileName`, `createdBy`, `createdAt` properties
- [x] `init-weaviate-schema.py` references English filenames: `invoice.json`, `bank-statement.json`, `document.json`, `email.json`, `security-settlement.json`, `contract.json`
- [x] SQL migration `010-proj19-english-doc-types.sql` correctly updates `permissions_dms`, `role_templates`, `dms_watched_folders` constraints and data
- [x] `init-postgres.sql` base schema uses English type names in CHECK constraints
- [x] `alice-dms-folder-api.json` Create/Update validation uses English type names
- [x] `alice-dms-scanner.json` reads `suggested_type` from DB (will use English values after migration)
- [x] `alice-dms-processor.json` all Code nodes use English type names and English property names
- [x] ~~BUG: Frontend `dms-constants.ts` still uses German type names -- see BUG-13~~ RESOLVED

**Previous re-test (2026-03-12) -- ioredis-to-redis migration:**
- [x] All 8 Code nodes use `require('redis')` (v4 API)
- [x] All nodes use correct `redis.createClient()` config and `await client.connect()`
- [x] All nodes use `try/finally { await client.quit() }` for cleanup
- [x] `NODE_FUNCTION_ALLOW_EXTERNAL` set to `axios,redis`
- [x] `REDIS_PASSWORD` read via `$env.REDIS_PASSWORD` with try/catch fallback

### Acceptance Criteria Status

#### AC-1: Workflow exists and is active
- [x] `workflows/core/alice-dms-processor.json` exists
- [x] `"active": true` is set in JSON
- [x] Workflow name is `alice-dms-processor`

#### AC-2: Schedule Trigger at 02:00
- [x] Schedule Trigger node present with cron `0 2 * * *` (daily at 02:00)

#### AC-3: Start timestamp + batch loop
- [x] `Code: Init` stores start time in Redis `alice:dms:run:start_time` via `client.set()`
- [x] BATCH_SIZE = 50, MAX_RUNTIME_SECONDS = 7200 defined in Init output

#### AC-4: LRANGE/LTRIM batch pattern
- [x] `Code: Fetch Batch` uses `client.lRange('alice:dms:plaintext', 0, 49)`
- [x] LTRIM uses `client.lTrim('alice:dms:plaintext', items.length, -1)` -- see BUG-1 (informational)

#### AC-5: Time limit check per batch
- [x] `Code: Time Check` compares elapsed time against 7200 seconds via `client.get()`
- [x] `IF: Time Limit Reached` routes to `Code: Final Log (Time)` when true
- [x] When time limit NOT reached, routes back to `Code: Fetch Batch` for next batch

#### AC-6: 2-hour time limit stops new batches
- [x] Correct -- `timeLimitReached = elapsed >= 7200` stops the loop

#### AC-7: extraction_failed items treated as error
- [x] `IF: Extraction Failed` checks `extraction_failed == true`
- [x] Routes to `Code: Handle Failed` which does `client.sRem('alice:dms:queued_files', ...)`
- [x] Then publishes to `alice/dms/error` via MQTT

#### AC-8: LLM classification only when suggested_type == "auto"
- [x] `IF: Auto Classify` checks `suggested_type == "auto"`
- [x] True branch goes to `HTTP: Ollama Classify`
- [x] Classification prompt includes all 6 valid types (English names)

#### AC-9: Known suggested_type used directly
- [x] `Code: Use Suggested Type` uses `suggested_type` directly when not "auto"
- [x] Validates against English valid types list with fallback to "Document"

#### AC-10: Field extraction for all 6 document types
- [x] `Code: Build Extraction Prompt` has prompts for all 6 types with English field names
- [x] Each prompt requests type-specific structured fields matching Weaviate schema properties
- [x] ~~BUG-2 FIXED:~~ All property names migrated from German to English, spec and implementation now aligned

#### AC-11: Correct Weaviate collection chosen
- [x] `Code: Build Weaviate Payload` maps `_document_type` to Weaviate class
- [x] All 6 types handled with fallback to "Document" (English)

#### AC-12: Upsert (delete existing before insert)
- [x] `HTTP: Weaviate Search` queries by `filePath` using GraphQL
- [x] `IF: Has Existing Entry` checks for existing ID
- [x] `HTTP: Weaviate Delete` removes old entry before insert
- [x] ~~BUG: `filePath` property has `indexFilterable: false` in all 6 schemas -- see BUG-14~~ RESOLVED

#### AC-13: Document stored with fullText + filePath + fileType
- [x] `fullText` truncated to 10,000 chars
- [x] `filePath` set from `item.file_path`
- [x] ~~BUG-3 FIXED:~~ `fileType` property added to all 6 Weaviate schemas and payload builder

#### AC-14: Original file stays on NAS
- [x] No file operations in workflow -- confirmed, no NAS file moves

#### AC-15: Redis state management (processed + queued_files)
- [x] `Code: Redis State Update` does `client.sRem('alice:dms:queued_files', ...)` and `client.sAdd('alice:dms:processed', ...)`

#### AC-16: path_to_hash and hash_to_paths populated
- [x] `client.hSet('alice:dms:path_to_hash', ...)` with file_path -> file_hash
- [x] `client.sAdd('alice:dms:hash_to_paths:<hash>', ...)` with file_path
- [x] Old hash cleanup via `client.hDel()` + `client.sRem()` when path exists with different hash

#### AC-17: MQTT done notification
- [x] `MQTT: Publish Done` publishes to `alice/dms/done` with QoS 1
- [x] Message includes file_path, file_hash, document_type, llm_classified, inserted, timestamp

#### AC-18: MQTT error notification
- [x] `MQTT: Publish Error` publishes to `alice/dms/error` with QoS 1
- [x] ~~BUG-4 FIXED:~~ `IF: Insert Success` node routes Weaviate failures to `MQTT: Publish Error (Weaviate)` then `Code: Abort Run`

#### AC-19: Execution Log with stats
- [x] ~~BUG-5 FIXED:~~ Both Final Log nodes now read `alice:dms:run:stats` Redis Hash and output `{ processed, failed, skipped, llm_classified, used_suggested_type, batches_run, runtime_seconds, remaining_queue }`

#### AC-20: LLM extraction prompts for all 6 types
- [x] All 6 types have extraction prompts in `Code: Build Extraction Prompt` with English field names

### Edge Cases Status

#### EC-1: extraction_failed: true
- [x] Handled -- routes to error path, SREM queued_files, MQTT error

#### EC-2: LLM returns invalid JSON
- [ ] BUG: No retry mechanism implemented -- see BUG-6

#### EC-3: suggested_type: auto -- LLM cannot determine type
- [x] Fallback to "Document" (English) when parsed type not in valid list

#### EC-4: Weaviate unreachable
- [x] ~~BUG-7 FIXED:~~ `Code: Redis State Update` no longer removes from `queued_files` on Weaviate failure; `IF: Insert Success` routes failures to `Code: Abort Run` which throws to stop the entire run

#### EC-5: File change (same path, different hash)
- [x] Weaviate delete-then-insert implemented
- [x] Redis old hash cleanup in `Code: Redis State Update`
- [x] ~~Upsert query may silently fail due to BUG-14 (filePath not filterable)~~ RESOLVED

#### EC-6: File already deleted at origin
- [x] No file access needed -- workflow processes from Redis only

#### EC-7: 2-hour time limit reached
- [x] Time check after each batch, stops loop correctly
- [x] Final Log records runtime_seconds and remaining_queue

#### EC-8: Empty plaintext with extraction_failed: false
- [x] LLM receives empty string, classification still attempted
- [x] Fallback to "Document" (English) when no valid type returned

#### EC-9: Duplicate hash in queue
- [x] `Code: Parse + Dedup Check` checks `alice:dms:processed` via `client.sIsMember()`
- [x] Skip item with `_skip: true` if already processed

#### EC-10: Empty Redis list
- [x] `Code: Fetch Batch` returns `{ _empty: true }` for empty list
- [x] `IF: Queue Empty` routes to Final Log

#### EC-11: Very long plaintext (>10,000 chars)
- [x] Weaviate fullText: `.slice(0, 10000)` in Build Weaviate Payload
- [x] LLM prompt: `.slice(0, 20000)` in Build Extraction Prompt and Classify

### Regression Test Results

#### PROJ-15: DMS Folder Management
- [x] `alice-dms-folder-api.json` Create/Update endpoints validate against English type names
- [x] DB constraint in migration `010` correctly updates `dms_watched_folders.suggested_type` CHECK
- [x] ~~BUG: Frontend `dms-constants.ts` still uses German type names -- see BUG-13~~ RESOLVED

#### PROJ-16/17: DMS Scanner
- [x] Scanner reads `suggested_type` from DB -- will use English values after migration runs
- [x] No hardcoded German type names in scanner workflow
- [x] MQTT messages pass through `suggested_type` as-is from DB

### Security Audit Results

- [x] No secrets hardcoded -- Redis connection uses internal Docker hostname, MQTT uses credential ID
- [x] No user-facing endpoints -- schedule trigger only, no webhooks
- [x] ~~BUG-8 FIXED:~~ Ollama URL uses internal Docker network `http://ollama-3090:11434/api/generate`
- [x] No file system writes -- read-only NAS mount confirmed in compose (`/mnt/nas:/mnt/nas:ro`)
- [x] Weaviate access via internal Docker network (http://weaviate:8080)
- [ ] BUG: GraphQL injection possible via file_path in Weaviate query -- see BUG-9
- [x] Redis connections properly closed with try/finally + client.quit()
- [x] No JWT/auth needed -- internal service-to-service communication
- [x] Redis password handled securely via `$env.REDIS_PASSWORD` with try/catch fallback
- [x] SQL migration uses transaction (BEGIN/COMMIT) -- safe rollback on failure
- [x] `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` allows `$env` access -- needed for REDIS_PASSWORD

### Bugs Found

#### BUG-1: LTRIM uses dynamic items.length instead of fixed 50
- **Severity:** Low
- **Location:** `Code: Fetch Batch` node
- **Description:** The spec says `LTRIM alice:dms:plaintext 50 -1` but the implementation uses `client.lTrim('alice:dms:plaintext', items.length, -1)`. This is actually MORE correct than the spec because if fewer than 50 items are returned, using a fixed 50 would still work (LTRIM with out-of-range values is safe in Redis), but `items.length` is semantically cleaner. Functionally equivalent.
- **Priority:** Informational -- no fix needed, implementation is correct

#### ~~BUG-2: Spec-to-implementation field name mismatches in extraction prompts~~ RESOLVED
- **Severity:** ~~Medium~~ Resolved
- **Description:** All Weaviate schemas, extraction prompts, and payload builder migrated from German to English property names. Spec and implementation are now aligned.
- **Fix:** Comprehensive German-to-English migration of all 6 DMS schema files, extraction prompts, and Weaviate payload builder. Class names: Invoice, BankStatement, Document, Email, SecuritySettlement, Contract. All property names now use English camelCase consistently.
- **Resolution date:** 2026-03-13

#### ~~BUG-3: file_type not stored in Weaviate payload~~ RESOLVED
- **Severity:** ~~Medium~~ Resolved
- **Description:** AC-13 required `file_type` to be stored alongside fullText and filePath. Previously missing from all 6 schema files and the payload builder.
- **Fix:** Added `fileType` property (text, keyword tokenization, not vectorized, filterable) to all 6 Weaviate DMS schemas. Updated `Code: Build Weaviate Payload` to include `fileType: item.file_type` in all 6 document type branches.
- **Resolution date:** 2026-03-13

#### ~~BUG-4: LLM/Weaviate errors do not publish to alice/dms/error~~ RESOLVED
- **Severity:** ~~High~~ Resolved
- **Description:** The spec requires errors from LLM or Weaviate failures to be published to `alice/dms/error`. Previously only `extraction_failed: true` items reached the error MQTT topic.
- **Fix:** Added `IF: Insert Success` node after `Code: Redis State Update`. When `_weaviate_inserted` is false, flow routes to `MQTT: Publish Error (Weaviate)` then `Code: Abort Run` (which throws to stop the entire workflow). On success, flow routes to `MQTT: Publish Done` as before.
- **Resolution date:** 2026-03-12

#### ~~BUG-5: Execution Log missing required stats fields~~ RESOLVED
- **Severity:** ~~Medium~~ Resolved
- **Description:** The spec requires an execution log with `{ processed, failed, skipped, llm_classified, used_suggested_type, batches_run, runtime_seconds }`. Previously both Final Log nodes only output `{ runtime_seconds, remaining_queue }`.
- **Fix:** Added Redis Hash `alice:dms:run:stats` initialized in `Code: Init` with all 6 counters. Each processing step increments the relevant counter via `hIncrBy`. Both `Code: Final Log` and `Code: Final Log (Time)` now read and output the full stats. `Code: Abort Run` also outputs stats before throwing.
- **Resolution date:** 2026-03-12

#### BUG-6: No LLM JSON retry mechanism
- **Severity:** Medium
- **Description:** The spec and edge case EC-2 require a 1x retry when the LLM returns invalid JSON, then fallback to `document_type: "Document"` with empty fields. The `Code: Parse Extract Result` node has a try/catch that silently defaults to `{}` on parse error but does NOT retry the LLM call. Similarly, `Code: Parse Classify Result` defaults to "Document" on parse failure without retry.
- **Steps to Reproduce:**
  1. Read `Code: Parse Extract Result` and `Code: Parse Classify Result` code
  2. Note: no retry logic, just catch and fallback
- **Impact:** Lower extraction quality -- a single LLM hiccup loses all structured data for that document.
- **Priority:** Fix in next sprint

#### ~~BUG-7: Weaviate errors do not abort the run~~ RESOLVED
- **Severity:** ~~High~~ Resolved
- **Description:** The spec edge case EC-4 states "Weaviate nicht erreichbar: Gesamter Run abgebrochen". Previously `Code: Redis State Update` removed items from `queued_files` even on Weaviate failure, causing data loss.
- **Fix:** `Code: Redis State Update` now only removes from `queued_files` and adds to `processed` when `insertSuccess` is true. On failure, the item's hash stays in `queued_files` for retry. The new `IF: Insert Success` node routes failures to `MQTT: Publish Error (Weaviate)` then `Code: Abort Run`, which logs stats and throws an error to abort the entire workflow run.
- **Resolution date:** 2026-03-12

#### ~~BUG-8: Ollama URL uses external HTTPS endpoint instead of internal Docker network~~ RESOLVED
- **Severity:** ~~High~~ Resolved
- **Description:** Both `HTTP: Ollama Classify` and `HTTP: Ollama Extract` used `https://ollama3090.happy-mining.de/api/generate` instead of the internal Docker network URL.
- **Fix:** Changed both Ollama HTTP request URLs to `http://ollama-3090:11434/api/generate` (internal Docker network via shared `frontend` network). n8n and ollama-3090 are both on the `frontend` network.
- **Resolution date:** 2026-03-12

#### BUG-9: Potential GraphQL injection via file_path
- **Severity:** Medium
- **Description:** In `Code: Build Weaviate Query`, the `file_path` is inserted into a GraphQL query string with minimal escaping (only backslash and double-quote). If a file path contains GraphQL special characters or Unicode sequences, the query could malform or potentially inject.
- **Code:**
  ```javascript
  const filePath = (item.file_path || '').replace(/\\\\/g, '\\\\\\\\').replace(/"/g, '\\\\"');
  const query = `{ Get { ${className}(where: ... valueText: "${filePath}" ...`;
  ```
- **Steps to Reproduce:**
  1. Create a file with a path containing `\n`, `\t`, or other control characters
  2. Observe: these are not escaped, potentially breaking the GraphQL query
- **Impact:** Could cause Weaviate query failures for certain file paths. Injection risk is limited since Weaviate GraphQL is read-only for Get queries, but query breakage is likely for edge-case paths.
- **Priority:** Fix in next sprint

#### BUG-10: BankStatement payload missing updatedAt field
- **Severity:** Low
- **Description:** The `Invoice`, `Document`, and `Contract` payloads include `updatedAt` in their Weaviate properties, but `BankStatement`, `Email`, and `SecuritySettlement` do not. The Weaviate schemas for `BankStatement` does not have `updatedAt` either, so this is consistent -- but it means those collections lack update tracking.
- **Priority:** Informational -- schema design choice, not a bug

#### ~~BUG-11: Email collection uses "inhalt" instead of "volltext"~~ RESOLVED
- **Severity:** ~~Low~~ Resolved
- **Description:** Previously all document types used `volltext` but Email used `inhalt`. With the German-to-English migration, Email now uses `content` (semantic distinction for email body) while all other types use `fullText`. The workflow payload builder maps correctly.
- **Resolution date:** 2026-03-13

#### ~~BUG-12: N8N_RUNNERS_ENABLED potential issue with ioredis require()~~ RESOLVED
- **Severity:** ~~Medium~~ Resolved
- **Description:** Previously flagged that `require('ioredis')` might fail in the runner sandbox. This is now fully resolved:
  1. All Code nodes migrated from `require('ioredis')` to `require('redis')`
  2. `NODE_FUNCTION_ALLOW_EXTERNAL` updated from `axios,ioredis` to `axios,redis`
  3. `N8N_RUNNERS_ENABLED` is NOT set in the n8n compose file -- no sandbox runner is active
  4. The `redis` npm package ships with the n8n base image (unlike `ioredis` which required manual installation)
- **Resolution date:** 2026-03-12

#### ~~BUG-13: Frontend dms-constants.ts still uses German type names (REGRESSION)~~ RESOLVED
- **Severity:** ~~High~~ Resolved
- **Location:** `frontend/src/components/Settings/dms-constants.ts`
- **Description:** The DMS folder management UI (PROJ-15) used `SUGGESTED_TYPES` from `dms-constants.ts` with German type names. After the DB migration `010`, the CHECK constraint only accepts English values.
- **Fix:** Updated `SUGGESTED_TYPES` array from German (`Rechnung`, `Kontoauszug`, `Dokument`, `WertpapierAbrechnung`, `Vertrag`) to English (`Invoice`, `BankStatement`, `Document`, `SecuritySettlement`, `Contract`). The `Email` type was already in English.
- **Resolution date:** 2026-03-13

#### ~~BUG-14: filePath property not filterable in Weaviate schemas~~ RESOLVED
- **Severity:** ~~High~~ Resolved
- **Location:** All 6 Weaviate schema files (`schemas/invoice.json`, `schemas/bank-statement.json`, etc.)
- **Description:** The upsert mechanism (AC-12) uses a Weaviate `where` filter on `filePath` to find existing entries before delete+insert. `filePath` had `indexFilterable: false` in all 6 schemas, causing the `where` clause to silently return empty results.
- **Fix:** Changed `filePath` to `indexFilterable: true` and added `tokenization: "keyword"` in all 6 Weaviate DMS schema files (invoice, bank-statement, document, email, security-settlement, contract). Keyword tokenization ensures exact path matching in `where` filters.
- **Resolution date:** 2026-03-13

### Summary
- **Acceptance Criteria:** 20/20 passed (AC-12 upsert now functional after BUG-14 fix)
- **Edge Cases:** 10/11 handled correctly (EC-2 still missing retry)
- **Bugs Found:** 3 open (0 critical, 0 high, 2 medium, 1 informational), 10 resolved
- **Open bugs:** BUG-6 (medium, LLM retry), BUG-9 (medium, GraphQL escaping), BUG-1/BUG-10 (informational)
- **Security:** 1 remaining issue (BUG-9 GraphQL injection -- low risk, next sprint)
- **German-to-English Migration:** Backend PASSED, frontend PASSED (BUG-13 resolved)
- **Regression:** None remaining (PROJ-15 DMS folder management UI fixed)
- **Production Ready:** YES -- all HIGH severity bugs resolved
- **Remaining for next sprint:** BUG-6 (LLM retry), BUG-9 (GraphQL escaping)
- **Final verification (2026-03-13):** All implementation files re-read and cross-validated. No new issues found.

## Deployment

**Status:** Deployed
**Deployed:** 2026-03-13
**Git Tag:** v1.19.0-PROJ-19

### Deployed Components
- `workflows/core/alice-dms-processor.json` — n8n workflow (import via n8n UI)
- `schemas/invoice.json`, `bank-statement.json`, `document.json`, `email.json`, `security-settlement.json`, `contract.json` — Weaviate collections (English, `filePath` filterable)
- `sql/migrations/010-proj19-english-doc-types.sql` — DB migration (German → English doc types)
- `frontend/src/components/Settings/dms-constants.ts` — Frontend type names (English)

### Notes
- Weaviate collections were re-created via `./scripts/init-weaviate-schema.sh` (required for `indexFilterable` change on `filePath`)
- DB migration 010 applied via `docker exec postgres psql -U user -d alice -f sql/migrations/010-proj19-english-doc-types.sql`
- Frontend deployed via `./scripts/deploy-frontend.sh` + `./sync-compose.sh`
- Open for next sprint: BUG-6 (LLM retry mechanism), BUG-9 (GraphQL path escaping)
