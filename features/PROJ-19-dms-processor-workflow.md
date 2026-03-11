# PROJ-19: DMS Processor Workflow (LLM-Klassifikation + Weaviate-Speicherung)

## Status: Planned
**Created:** 2026-03-09
**Last Updated:** 2026-03-11

## Dependencies
- Requires: PROJ-18 (DMS Extractor Container) — Redis List `alice:dms:plaintext` muss mit extrahierten Texten befüllt sein
- Requires: PROJ-17 (DMS Scanner Multi-Queue) — Scanner muss Dateien in die Extractor-Queues stellen
- Requires: PROJ-15 (DMS Ordnerverwaltung) — `alice.dms_watched_folders` muss existieren
- Weaviate Collections (`Rechnung`, `Kontoauszug`, `Dokument`, `Email`, `WertpapierAbrechnung`, `Vertrag`) müssen existieren

## Overview

Implementierung des `alice-dms-processor` n8n Workflows. Er läuft nächtlich, liest fertig extrahierte Plaintext-Einträge aus der Redis List `alice:dms:plaintext` (befüllt von den Extractor-Containern aus PROJ-18) und führt folgende Schritte durch:

1. **LLM-Klassifikation** (nur wenn `suggested_type: auto`) — Qwen3:14b bestimmt den Dokumenttyp
2. **Typenspezifische Feldextraktion** — Qwen3:14b extrahiert strukturierte Felder je Dokumenttyp
3. **Weaviate-Speicherung** — Dokument mit Volltext und Metadaten wird in die passende Collection gespeichert
4. **Archivierung** — Originaldatei wird ins Archivverzeichnis verschoben
5. **Redis-Bereinigung** — Hash von `queued_files` nach `processed_files` übertragen

Die Textextraktion (PDF, OCR, Office, TXT) findet **nicht** im Processor statt — das ist die Aufgabe der Extractor-Container (PROJ-18). Der Processor erhält bereits fertigen Plaintext aus der Queue.

Der Workflow läuft nachts, um die GPU (Qwen3:14b via Ollama) nicht tagsüber für Batch-Verarbeitung zu belasten.

## User Stories

- Als System möchte ich Dokumente aller Formate aus der Plaintext-Queue automatisch klassifizieren und in Weaviate speichern, damit neue Dokumente ohne manuellen Aufwand durchsuchbar werden.
- Als System möchte ich den Dokumenttyp via LLM bestimmen lassen, wenn `suggested_type: auto` gesetzt ist, damit auch unstrukturierte Projektordner korrekt klassifiziert werden.
- Als Admin möchte ich, dass fehlerhafte Dokumente (`extraction_failed: true`) ins Fehlerverzeichnis verschoben und in `alice/dms/error` gepublisht werden, damit ich sie manuell prüfen kann.
- Als Admin möchte ich max. 50 Dokumente pro Nacht verarbeiten lassen (konfigurierbar), damit der Processor den LLM-Betrieb nicht blockiert.

## Acceptance Criteria

- [ ] n8n Workflow `alice-dms-processor` existiert und ist aktiv
- [ ] Trigger: Schedule, täglich 02:00 Uhr
- [ ] Workflow liest bis zu `MAX_DOCS_PER_RUN` (Default: 50) Einträge via `LRANGE alice:dms:plaintext 0 49` aus Redis und entfernt sie anschließend via `LTRIM`
- [ ] Nachrichten mit `extraction_failed: true` werden direkt als Fehler behandelt (kein LLM-Aufruf)
- [ ] **LLM-Klassifikation** (Qwen3:14b via Ollama): nur wenn `suggested_type: auto`; bestimmt `document_type`
- [ ] Bei bekanntem `suggested_type` (nicht `auto`): wird direkt als `document_type` übernommen (kein LLM-Klassifikations-Aufruf)
- [ ] **Typenspezifische Feldextraktion** via Qwen3:14b für alle 6 Dokumenttypen (s.u.)
- [ ] Korrekte Weaviate-Collection wird anhand `document_type` gewählt
- [ ] Dokument wird in Weaviate gespeichert mit: extrahierten Feldern + `volltext` (max. 10.000 Zeichen) + `original_path` + `file_type` + `archive_path`
- [ ] Originaldatei wird nach Verarbeitung ins Archiv verschoben: `<archiv_basis>/YYYY/MM/dateiname.ext`
- [ ] `file_hash` wird in Redis `alice:dms:processed_files` eingetragen und aus `alice:dms:queued_files` entfernt
- [ ] Erfolgsmeldung wird an `alice/dms/done` gepublisht
- [ ] Bei Fehler (extraction_failed oder LLM/Weaviate-Fehler): Datei wird nach `<ordner>/fehler/` verschoben, Fehler an `alice/dms/error` gepublisht
- [ ] Execution Log: `{ processed, failed, skipped, llm_classified, used_suggested_type }`
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

- **`extraction_failed: true` in Redis-Eintrag**: Kein LLM-Aufruf, kein Weaviate-Insert. Datei wird nach `<ordner>/fehler/` verschoben, Hash aus `queued_files` entfernt, Fehler an `alice/dms/error` gepublisht (MQTT, Monitoring).
- **LLM gibt ungültiges JSON zurück**: Retry 1×. Bei erneutem Fehler: `document_type: "Dokument"`, leeres Feldobjekt, `extraction_failed: true`.
- **`suggested_type: auto` — LLM kann Typ nicht bestimmen**: Fallback auf `document_type: "Dokument"`.
- **Weaviate nicht erreichbar**: Gesamter Run abgebrochen, keine Dateien werden verschoben. Hash verbleibt in `queued_files` (nächste Nacht Retry).
- **Archivordner existiert nicht**: Wird automatisch erstellt (`YYYY/MM/`).
- **Datei am Ursprungsort bereits gelöscht**: Warnung ins Log, trotzdem als verarbeitet markieren.
- **`plaintext` leer, `extraction_failed: false`** (Extractor-Fehler nicht korrekt gesetzt): LLM versucht Klassifikation trotzdem; bei leerem Text Fallback auf `document_type: "Dokument"`.
- **Gleicher Hash zweimal in Queue**: Zweites Item wird übersprungen (Redis `processed_files` Check).
- **Redis List leer**: `LRANGE` gibt leeres Array zurück, Workflow endet sofort mit `processed: 0`.
- **Sehr langer Plaintext (> 10.000 Zeichen)**: Wird für Weaviate auf 10.000 Zeichen gekürzt; voller Text für LLM-Extraktion auf 20.000 Zeichen begrenzt.

## Technical Requirements

- **Trigger**: n8n Schedule Trigger, täglich 02:00 Uhr
- **MAX_DOCS_PER_RUN**: 50 (konfigurierbare Konstante im Workflow)
- **LLM**: Ollama `qwen3:14b` via n8n Ollama-Node oder HTTP-Request
- **Input-Queue**: Redis List `alice:dms:plaintext` (von PROJ-18 Extractor-Containern via RPUSH befüllt)
- **Queue-Verarbeitung**: `LRANGE 0 49` lesen → verarbeiten → `LTRIM 50 -1` (atomares Drainieren der ersten 50 Einträge)
- **Keine Textextraktion im Workflow** — Plaintext kommt fertig aus Redis
- **Weaviate-Insert**: HTTP-Request an `http://weaviate:8080/v1/objects`
- **Collection-Mapping**:
  ```
  Rechnung             → Rechnung
  Kontoauszug          → Kontoauszug
  Dokument             → Dokument
  Email                → Email
  WertpapierAbrechnung → WertpapierAbrechnung
  Vertrag              → Vertrag
  (fallback)           → Dokument
  ```
- **n8n Credentials**: Redis (`redis-alice`, Queue-Lesen), Ollama (`Ollama 3090`), MQTT (`mqtt-alice`, done/error Notifications), PostgreSQL (`pg-alice`)
- **Workflow-Datei**: `workflows/core/alice-dms-processor.json`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
