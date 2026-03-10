# PROJ-17: DMS Processor Workflow (Multi-Format + OCR)

## Status: Planned
**Created:** 2026-03-09
**Last Updated:** 2026-03-09

## Dependencies
- Requires: PROJ-16 (DMS Scanner) — MQTT-Queue muss mit Dokumenten befüllt sein
- Requires: PROJ-15 (DMS Ordnerverwaltung) — `alice.dms_watched_folders` muss existieren
- Weaviate Collections (`Rechnung`, `Kontoauszug`, `Dokument`, `Email`, `WertpapierAbrechnung`, `Vertrag`) müssen existieren
- Tesseract-OCR-Container muss laufen (für gescannte PDFs)
- LibreOffice-headless-Container muss laufen (für Office-Formate)

## Overview

Implementierung des `alice-dms-processor` n8n Workflows. Er läuft nächtlich, liest Nachrichten aus der MQTT-Queue `alice/dms/new` und verarbeitet Dokumente je nach Dateityp:
- **PDF (Textebene vorhanden)**: Text-Extraktion via pdf-parse
- **PDF (gescannt, needs_ocr: true)**: OCR via Tesseract-Container (HTTP API)
- **TXT / MD**: Direktes Einlesen
- **Office-Formate (DOCX, XLSX, ODT, ODS)**: Konvertierung via LibreOffice-headless-Container → Plaintext

Nach der Textextraktion: LLM-Klassifikation (wenn `suggested_type: auto`) und typenspezifische Feldextraktion via Qwen2.5:14b, Speicherung in Weaviate, Archivierung der Originaldatei.

## User Stories

- Als System möchte ich Dokumente aller unterstützten Formate aus der MQTT-Queue automatisch verarbeiten, damit neue Dokumente ohne manuellen Aufwand in Weaviate indexiert werden.
- Als System möchte ich gescannte PDFs via OCR lesbar machen, damit auch eingescannte Dokumente vollständig indexiert werden.
- Als System möchte ich Office-Dateien in Text umwandeln, damit Rechnungen, Tabellen und Dokumente aus Word/Excel/LibreOffice durchsuchbar werden.
- Als System möchte ich den Dokumenttyp via LLM bestimmen lassen, wenn `suggested_type: auto` gesetzt ist, damit auch unstrukturierte Projektordner korrekt klassifiziert werden.
- Als Admin möchte ich, dass fehlerhafte Dokumente ins Fehlerverzeichnis verschoben und in `alice/dms/error` gepublisht werden, damit ich sie manuell prüfen kann.
- Als Admin möchte ich max. 50 Dokumente pro Nacht verarbeiten lassen (konfigurierbar), damit der Processor nicht den LLM-Betrieb blockiert.

## Acceptance Criteria

- [ ] n8n Workflow `alice-dms-processor` existiert und ist aktiv
- [ ] Trigger: Schedule, nächtlich 02:00 Uhr
- [ ] Workflow liest bis zu `MAX_DOCS_PER_RUN` (Default: 50) Nachrichten von MQTT `alice/dms/new`
- [ ] **Text-Extraktion** wird anhand `file_type` geroutet:
  - `pdf` + `needs_ocr: false` → pdf-parse (Code-Node oder HTTP)
  - `pdf` + `needs_ocr: true` → HTTP POST an Tesseract-Container
  - `txt`, `md` → direkte Datei-Lese-Operation
  - `docx`, `doc`, `odt` → HTTP POST an LibreOffice-Container → Plaintext
  - `xlsx`, `xls`, `ods` → HTTP POST an LibreOffice-Container → CSV → Plaintext
- [ ] Wenn extrahierter Text leer und `needs_ocr: false`: erneuter Versuch mit Tesseract; wenn immer noch leer: `volltext: ""`, `extraction_failed: true`
- [ ] LLM-Klassifikation (Qwen2.5:14b via Ollama): nur wenn `suggested_type: auto`; bestimmt `document_type` und extrahiert typenspezifische Felder
- [ ] Bei bekanntem `suggested_type` (nicht auto): Direktextraktion der typenspezifischen Felder ohne Typ-Bestimmung
- [ ] Korrekte Weaviate-Collection wird anhand `document_type` gewählt
- [ ] Dokument wird in Weaviate gespeichert mit: extrahierten Feldern + `volltext` (max. 10.000 Zeichen) + `original_path` + `file_type` + `archive_path`
- [ ] Originaldatei wird nach Verarbeitung ins Archiv verschoben: `<archiv_basis>/YYYY/MM/dateiname.ext`
- [ ] `file_hash` wird in Redis `alice:dms:processed_files` eingetragen und aus `alice:dms:queued_files` entfernt
- [ ] Erfolgsmeldung wird an `alice/dms/done` gepublisht
- [ ] Bei Fehler: Datei wird nach `<ordner>/fehler/` verschoben, Fehler an `alice/dms/error` gepublisht
- [ ] Execution Log: `{ processed, failed, skipped, ocr_count, office_count }`
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

- **PDF gescannt, OCR gibt leeren Text**: Dokument mit `volltext: ""`, `extraction_failed: true` in Weaviate; kein LLM-Aufruf; in Fehlerordner verschieben.
- **LibreOffice-Container nicht erreichbar**: Alle Office-Dateien in dieser Run werden übersprungen (Fehler geloggt); nächste Run versucht es erneut (Hash bleibt in `queued_files`).
- **LLM gibt ungültiges JSON zurück**: Retry 1×. Bei erneutem Fehler: `document_type: "Dokument"`, leeres Feldobjekt, `extraction_failed: true`.
- **`suggested_type: auto` — LLM kann Typ nicht bestimmen**: Fallback auf `document_type: "Dokument"`.
- **Weaviate nicht erreichbar**: Gesamter Run abgebrochen, keine Dateien werden verschoben.
- **Archivordner existiert nicht**: Wird automatisch erstellt (`YYYY/MM/`).
- **Datei am Ursprungsort bereits gelöscht**: Warnung ins Log, trotzdem als verarbeitet markieren.
- **Excel-Datei mit mehreren Sheets**: Alle Sheets werden als Plaintext (Tabs/Zeilenumbrüche) zusammengeführt.
- **Sehr großes Office-Dokument (> 50 MB)**: Wird mit `priority: low` verarbeitet; Volltext auf 10.000 Zeichen limitiert.
- **Gleicher Hash zweimal in Queue**: Zweites Item wird übersprungen.
- **MQTT Queue leer**: Workflow endet sofort mit `processed: 0`.

## Technical Requirements

- **Trigger**: n8n Schedule Trigger, täglich 02:00 Uhr
- **MAX_DOCS_PER_RUN**: 50 (konfigurierbare Konstante im Workflow)
- **LLM**: Ollama `qwen2.5:14b` via n8n Ollama-Node oder HTTP-Request
- **Tesseract-Container**: HTTP API, Docker-Service `tesseract-ocr`; Endpunkt: `POST http://tesseract:8080/ocr` (multipart/form-data, gibt Plaintext zurück)
- **LibreOffice-Container**: HTTP API, Docker-Service `libreoffice-convert`; Endpunkt: `POST http://libreoffice:3000/convert` (multipart/form-data, Parameter: `target=txt`)
- **PDF-Extraktion**: Code-Node mit `require('pdf-parse')` (Runner-Sandbox, `NODE_FUNCTION_ALLOW_EXTERNAL=pdf-parse` setzen)
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
- **n8n Credentials**: MQTT (`mqtt-local`), Ollama (`Ollama 3090`), Redis, PostgreSQL (`pg-alice`)
- **Workflow-Datei**: `workflows/core/alice-dms-processor.json`
- **Neue Docker-Services** (separate Compose-Files):
  - `docker/compose/automations/tesseract-ocr/compose.yml`
  - `docker/compose/automations/libreoffice-convert/compose.yml`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
