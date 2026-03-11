# PROJ-18: DMS Text-Extractor-Container

## Status: Planned
**Created:** 2026-03-11
**Last Updated:** 2026-03-11

## Dependencies
- Requires: PROJ-17 (DMS Scanner Multi-Queue) — Queues `alice/dms/[pdf,ocr,txt,office]` müssen befüllt werden
- NAS-Mount muss in den Extractor-Containern eingebunden sein
- MQTT-Broker muss laufen

## Overview

Implementierung von vier spezialisierten Docker-Containern, die jeweils eine typenspezifische MQTT-Queue (`alice/dms/[pdf,ocr,txt,office]`) abonnieren, die Textextraktion aus der Originaldatei durchführen und das Ergebnis als einheitliche Plaintext-Nachricht an die MQTT-Queue `alice/dms/plaintext` publizieren.

Die Container arbeiten eigenständig und kontinuierlich (MQTT-Subscription, kein Polling). Sie benötigen keine GPU und können daher tagsüber parallel zum `alice-dms-scanner` laufen, ohne GPU-Ressourcen zu belegen. Der `alice-dms-processor` (PROJ-19) liest nachts nur noch aus `alice/dms/plaintext` und muss sich nicht mehr um Extraktion kümmern.

### Container-Übersicht

| Container | Queue (Input) | Extraktion | Besonderheit |
|---|---|---|---|
| `dms-extractor-pdf` | `alice/dms/pdf` | pdf-parse (Node.js) | Nur PDFs mit Textebene |
| `dms-extractor-ocr` | `alice/dms/ocr` | Tesseract-OCR | Gescannte PDFs / Bilder |
| `dms-extractor-txt` | `alice/dms/txt` | Direktes Dateilesen | TXT, MD |
| `dms-extractor-office` | `alice/dms/office` | LibreOffice headless | DOCX, XLSX, ODT, ODS etc. |

Alle Container publizieren an dieselbe Output-Queue `alice/dms/plaintext`.

## User Stories

- Als System möchte ich, dass PDF-Textextraktion in einem dedizierten Container stattfindet, damit n8n keinen Zugriff auf NAS-Dateipfade außerhalb seines Containers benötigt.
- Als System möchte ich, dass OCR-Erkennung in einem dedizierten Container läuft, damit Tesseract isoliert und unabhängig von n8n betrieben werden kann.
- Als System möchte ich, dass Office-Konvertierung in einem dedizierten Container stattfindet, damit LibreOffice headless isoliert läuft und nicht mit anderen Services interferiert.
- Als System möchte ich, dass alle Extractor-Container ein einheitliches Output-Format liefern, damit der `alice-dms-processor` (PROJ-19) unabhängig vom ursprünglichen Dateiformat arbeiten kann.
- Als Admin möchte ich, dass die Container automatisch neu starten und im Fehlerfall das Dokument als fehlgeschlagen markieren, damit keine Nachrichten verloren gehen.

## Acceptance Criteria

### Alle Container (gemeinsam)
- [ ] Jeder Container abonniert seine MQTT-Queue (QoS 1)
- [ ] Jeder Container liest die Originaldatei vom NAS-Mount (`/mnt/nas` read-only)
- [ ] Jeder Container publiziert Ergebnis an `alice/dms/plaintext` (QoS 1)
- [ ] Output-Format ist für alle Container identisch (s.u.)
- [ ] Bei nicht erreichbarer Datei: `extraction_failed: true`, `plaintext: ""`, trotzdem an `alice/dms/plaintext` publizieren
- [ ] Container starten automatisch neu (`restart: unless-stopped`)
- [ ] Fehler werden strukturiert geloggt (JSON-Format)

### dms-extractor-pdf
- [ ] Liest Queue `alice/dms/pdf`
- [ ] Extrahiert Text via `pdf-parse` (Node.js)
- [ ] Befüllt `metadata.page_count` wenn verfügbar
- [ ] Bei Fehler (korrupte PDF): `extraction_failed: true`

### dms-extractor-ocr
- [ ] Liest Queue `alice/dms/ocr`
- [ ] Führt OCR via Tesseract durch (direkt als Library oder lokales Binary)
- [ ] Unterstützte Sprachen: Deutsch (`deu`) und Englisch (`eng`) als Default
- [ ] Bei mehrseitigen PDFs: OCR seitenweise, Ergebnisse zusammengeführt
- [ ] `metadata.ocr_language` gibt erkannte Sprache zurück

### dms-extractor-txt
- [ ] Liest Queue `alice/dms/txt`
- [ ] Liest Datei direkt als UTF-8 Text
- [ ] Encoding-Fallback: ISO-8859-1 wenn UTF-8 fehlschlägt
- [ ] MD-Format: Markdown-Syntax bleibt erhalten (kein Strip)

### dms-extractor-office
- [ ] Liest Queue `alice/dms/office`
- [ ] Konvertiert DOCX, DOC, ODT → Plaintext via LibreOffice headless (`libreoffice --headless --convert-to txt`)
- [ ] Konvertiert XLSX, XLS, ODS → CSV via LibreOffice headless, CSV-Inhalt als Plaintext
- [ ] Bei mehrseitigen/mehrtabelligen Dokumenten: Inhalte zeilenweise zusammengeführt

### Compose / Infrastruktur
- [ ] Alle 4 Container haben separate Compose-Files unter `docker/compose/automations/dms-extractor-[pdf,ocr,txt,office]/compose.yml`
- [ ] NAS-Mount `/mnt/nas:/mnt/nas:ro` in allen Containern
- [ ] MQTT-Verbindung via Umgebungsvariablen (kein Hardcoding)
- [ ] Container sind im `backend` Docker-Netzwerk

## Output-Format (`alice/dms/plaintext`)

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

## Edge Cases

- **Datei am NAS nicht mehr vorhanden**: Container loggt Fehler, publiziert `extraction_failed: true` mit leerem `plaintext`. Hash bleibt in Redis `queued_files` (PROJ-19 bereinigt ihn).
- **Sehr große Datei (> 50 MB)**: Extraktion wird durchgeführt, aber `plaintext` wird auf 50.000 Zeichen limitiert (PROJ-19 schneidet für Weaviate nochmals auf 10.000 Zeichen).
- **OCR: Sprache nicht erkennbar**: Tesseract verwendet Default (`deu+eng`), kein Fehler.
- **Office-Dokument mit Makros / passwortgeschützt**: LibreOffice schlägt fehl → `extraction_failed: true`.
- **MQTT-Broker offline**: Container wiederholt Verbindungsversuch mit exponential backoff. Nachrichten gehen nicht verloren (QoS 1 im Broker gepuffert).
- **MQTT-Nachricht im falschen Format (kein JSON)**: Nachricht wird geloggt und verworfen (kein Absturz).
- **Mehrere Container-Instanzen (Skalierung)**: Jede Nachricht wird nur einmal verarbeitet (MQTT QoS 1 + Broker stellt sicher, dass jede Message nur an einen Consumer geht, wenn alle im selben Topic subscriben ohne Shared Subscription). Für zukünftige Skalierung: MQTT Shared Subscriptions verwenden (`$share/dms-pdf/alice/dms/pdf`).
- **Container-Neustart während Verarbeitung**: MQTT QoS 1 — Nachricht wird erneut zugestellt. Container muss idempotent sein (Hash-basierte Deduplizierung oder Accept-Duplicate im Processor).

## Technical Requirements

### dms-extractor-pdf
- **Sprache**: Node.js (Alpine)
- **Bibliothek**: `pdf-parse` npm-Paket
- **MQTT-Client**: `mqtt` npm-Paket
- **Compose**: `docker/compose/automations/dms-extractor-pdf/compose.yml`

### dms-extractor-ocr
- **Sprache**: Python (Debian Slim)
- **Bibliotheken**: `pytesseract`, `Pillow`, `pdf2image`, `paho-mqtt`
- **System-Packages**: `tesseract-ocr`, `tesseract-ocr-deu`, `tesseract-ocr-eng`, `poppler-utils`
- **Compose**: `docker/compose/automations/dms-extractor-ocr/compose.yml`

### dms-extractor-txt
- **Sprache**: Node.js (Alpine)
- **Bibliothek**: Node.js `fs` (Built-in), `chardet` für Encoding-Detection
- **MQTT-Client**: `mqtt` npm-Paket
- **Compose**: `docker/compose/automations/dms-extractor-txt/compose.yml`

### dms-extractor-office
- **Sprache**: Node.js oder Python (Debian wegen LibreOffice)
- **System-Package**: `libreoffice-headless`, `libreoffice-calc`, `libreoffice-writer`
- **MQTT-Client**: `mqtt` npm / `paho-mqtt`
- **Compose**: `docker/compose/automations/dms-extractor-office/compose.yml`

### Shared
- **MQTT-Konfiguration** via Env: `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`
- **NAS-Mount**: `/mnt/nas:/mnt/nas:ro` (read-only)
- **Docker-Netzwerk**: `backend`
- **Restart-Policy**: `unless-stopped`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
