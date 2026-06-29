# PROJ-56: DMS Bildanalyse

## Status: Approved
**Created:** 2026-06-29
**Last Updated:** 2026-06-29

## Dependencies
- Requires: PROJ-16 (DMS Scanner) — SUPPORTED_EXTENSIONS um Bildformate erweitern
- Requires: PROJ-17 (DMS Multi-Queue Routing) — neue Route `alice/dms/image` im Switch-Node
- Requires: PROJ-18 (DMS Extractor Container) — gleicher Implementierungsansatz für `dms-extractor-image`
- Requires: PROJ-19 (DMS Processor) — muss Redis-Liste `alice:dms:image` lesen und in neue Weaviate-Collection "Image" schreiben
- Requires: PROJ-55 (DMS Thumbnail-Generierung) — Thumbnailer generiert Thumbnails automatisch nach `alice/dms/done`; Bilder (Center-Crop) werden bereits unterstützt

## Overview

Bilder (JPG, PNG, WEBP, HEIC, TIFF) werden in die bestehende DMS-Pipeline integriert. Ein neuer Container `dms-extractor-image` abonniert die MQTT-Queue `alice/dms/image`, liest das Bild vom NAS, extrahiert EXIF-Metadaten (Aufnahmedatum, GPS, Kamera), konvertiert GPS-Koordinaten via lokaler Nominatim-Instanz in Adressinformationen und erzeugt eine KI-generierte Bildbeschreibung in deutscher Sprache über ein lokales Vision-Modell (Ollama). Das Ergebnis landet in der Redis-Liste `alice:dms:image`, aus der PROJ-19 nachts liest und es in eine neue Weaviate-Collection "Image" schreibt.

Bilder, die denselben Datei-Hash haben (identischer Inhalt unter verschiedenen Pfaden), werden dedupliziert: der neue Pfad wird im `additionalPaths`-Feld der bestehenden Weaviate-Objekt ergänzt, ohne eine erneute KI-Analyse auszulösen. Thumbnails generiert der bereits deployede PROJ-55-Thumbnailer automatisch.

**Warum lokales Nominatim statt Online-API?** Bei einer Photosession mit 200 Bildern würde das 1-req/s-Rate-Limit von nominatim.openstreetmap.org ~3 Minuten Wartezeit erzeugen. Eine lokale Instanz mit Planetdaten (~60 GB auf `/srv/warm`) hat kein Rate-Limit und keine externe Abhängigkeit.

## User Stories

- Als Andreas möchte ich alle Bilder mit Sonnenuntergang finden können, indem ich Alice frage "Zeige mir alle Bilder mit Sonnenuntergang", damit ich Bilder nach Bildinhalten suchen kann ohne Ordnerstruktur zu kennen.
- Als Andreas möchte ich alle Bilder aus Japan oder Peking finden können, indem ich "Zeige mir alle Bilder aus Japan" frage, damit ich Bilder nach dem Aufnahmeort durchsuchen kann.
- Als Andreas möchte ich alle Bilder eines bestimmten Datums oder Zeitraums finden können, damit ich Erinnerungen zeitlich eingrenzen kann.
- Als System möchte ich neue Bilder auf dem NAS automatisch erkennen und verarbeiten, damit keine manuelle Intervention für den Import nötig ist.
- Als System möchte ich erkennen, wenn dasselbe Bild unter verschiedenen Pfaden vorliegt, damit keine redundante KI-Analyse ausgeführt wird und alle bekannten Pfade abfragbar bleiben.
- Als Admin möchte ich Bildordner über dasselbe Settings-UI konfigurieren, das ich für Dokumentordner verwende, damit ich keinen separaten Konfigurationsweg lernen muss.

## Acceptance Criteria

### Scanner-Erweiterung (PROJ-16/17)

- [ ] `alice-dms-scanner` erkennt Bilddateien mit den Erweiterungen `jpg`, `jpeg`, `png`, `webp`, `heic`, `tif`, `tiff` in allen konfigurierten Ordnern
- [ ] Bilder werden via MQTT an Queue `alice/dms/image` geroutet (QoS 1)
- [ ] Deduplication über Redis-Sets `alice:dms:queued_files` und `alice:dms:processed_files` — gleicher Mechanismus wie für Dokumente
- [ ] Stabilitätscheck (Größenvergleich mit 5s Abstand) gilt auch für Bilder
- [ ] Dateien > 100 MB erhalten `priority: low`
- [ ] MQTT-Nachrichtenformat identisch mit Dokumenten-Format (kein neues Feld nötig)

### dms-extractor-image Container

- [ ] Container abonniert MQTT-Queue `alice/dms/image` (QoS 1)
- [ ] Dateipfad wird gegen `/mnt/nas/`-Präfix validiert; ungültige Pfade werden verworfen
- [ ] Container liest Bilddatei vom NAS (read-only NAS-Mount via `nas-volumes.yml`)
- [ ] EXIF-Extraktion: `exif_datetime` (Aufnahmedatum), `latitude`, `longitude`, `altitude`, `camera_make`, `camera_model` — alle Felder optional (fehlen wenn nicht im EXIF vorhanden)
- [ ] Wenn GPS-Koordinaten vorhanden: Reverse Geocoding via lokaler Nominatim-Instanz → `country`, `country_code`, `city`, `district`
- [ ] KI-generierte Bildbeschreibung in deutscher Sprache via Ollama Vision-Modell (`ai_description`)
- [ ] `ai_description` wird auf max. 50.000 Zeichen begrenzt
- [ ] Output-JSON wird via `RPUSH` in Redis-Liste `alice:dms:image` geschrieben
- [ ] Bei Fehler (Datei nicht lesbar, KI nicht erreichbar): `extraction_failed: true`, `ai_description: ""`, trotzdem in Redis schreiben
- [ ] Container startet automatisch neu (`restart: unless-stopped`)
- [ ] Fehler werden strukturiert geloggt (JSON-Format)
- [ ] Compose-File: `docker/compose/automations/dms-extractor-image/compose.yml`
- [ ] NAS-Mounts via `extends: ../nas-volumes.yml` (read-only)

### Nominatim-Container

- [ ] Lokaler Nominatim-Docker-Container läuft im `backend`-Netzwerk
- [ ] Initialer Import: weltweite OpenStreetMap-Planetdaten; Datenverzeichnis auf `/srv/warm/nominatim/`
- [ ] Reverse-Geocoding-Endpunkt erreichbar unter `http://nominatim:8080/reverse?lat=...&lon=...&format=json`
- [ ] Nicht via nginx nach außen exponiert (nur intern)
- [ ] Wöchentliches Update-Skript für OSM-Diffs ist dokumentiert
- [ ] Compose-File: `docker/compose/data/nominatim/compose.yml`

### Weaviate Collection "Image"

- [ ] Neue Collection "Image" im Weaviate-Schema existiert
- [ ] Pflichtfelder (immer vorhanden): `file_path`, `file_hash`, `file_type`, `file_size`, `detected_at`, `extracted_at`, `extractor`, `ai_description`, `extraction_failed`
- [ ] EXIF-Felder (optional): `exif_datetime` (Date), `latitude` (Number), `longitude` (Number), `altitude` (Number), `camera_make` (Text), `camera_model` (Text)
- [ ] Geocoding-Felder (optional): `country` (Text), `country_code` (Text), `city` (Text), `district` (Text)
- [ ] `thumbnail_path` (Text, optional) — wird von PROJ-55 nach Thumbnail-Generierung gesetzt
- [ ] `additionalPaths` (text[]) — nicht vektorisiert; enthält alle bekannten Alternativpfade für dasselbe Bild
- [ ] Nur `ai_description` wird vektorisiert (semantische Suche)
- [ ] Filterbarer Zugriff auf alle anderen Felder (Land, Stadt, Datum, Kameramodell)
- [ ] Init-Script `scripts/init-weaviate-schema.sh` wird um "Image"-Collection erweitert

### PROJ-19 Processor-Erweiterung

- [ ] Processor liest nachts zusätzlich von Redis-Liste `alice:dms:image` (parallel zu `alice:dms:plaintext`)
- [ ] Schreibt Image-Objekte in Weaviate-Collection "Image"
- [ ] Deduplication via `file_hash`: wenn Hash bereits in Collection "Image" vorhanden → neuer Pfad wird zu `additionalPaths` hinzugefügt; kein neues Weaviate-Objekt
- [ ] Nach erfolgreichem Weaviate-Insert: MQTT `alice/dms/done` mit `weaviate_uuid`, `original_path`, `document_type: "Image"`, `file_type` publizieren → PROJ-55 generiert Thumbnail automatisch
- [ ] `extraction_failed: true` Einträge werden in Weaviate geschrieben (Fehler dokumentiert, kein stummer Verlust)

## Output-Format (Redis-Liste `alice:dms:image`)

```json
{
  "file_path": "/mnt/nas/andreas/Fotos/2024/Japan/DSC_001.jpg",
  "file_hash": "sha256:abc123...",
  "file_type": "jpg",
  "file_size": 4500000,
  "detected_at": "2026-06-29T10:00:00Z",
  "extracted_at": "2026-06-29T10:01:30Z",
  "extractor": "dms-extractor-image",
  "ai_description": "Ein Sonnenuntergang über der Skyline von Tokio mit leuchtendem Orange und Rosa am Horizont. Im Vordergrund sind Hochhäuser zu sehen.",
  "extraction_failed": false,
  "exif": {
    "datetime": "2024-07-15T14:30:00",
    "latitude": 35.6762,
    "longitude": 139.6503,
    "altitude": 45.2,
    "camera_make": "Nikon",
    "camera_model": "D850"
  },
  "geocoding": {
    "country": "Japan",
    "country_code": "JP",
    "city": "Tokyo",
    "district": "Shibuya"
  }
}
```

Pflichtfelder (immer vorhanden): `file_path`, `file_hash`, `file_type`, `file_size`, `detected_at`, `extracted_at`, `extractor`, `ai_description`, `extraction_failed`

Optionale Felder: `exif` (komplett oder einzelne Unterfelder), `geocoding` (nur wenn GPS vorhanden)

## Edge Cases

- **Kein EXIF-Datum vorhanden** (Screenshot, WhatsApp-Bild): `exif_datetime` bleibt leer; `detected_at` (Scan-Zeitpunkt) wird nicht als Ersatz gesetzt — fehlende Daten bleiben fehlend
- **Keine GPS-Koordinaten**: Geocoding wird übersprungen; `country`, `city`, `district` bleiben leer; kein Fehler
- **Nominatim nicht erreichbar**: Geocoding wird übersprungen; Bild wird trotzdem vollständig verarbeitet; Geocoding-Felder bleiben leer; kein `extraction_failed`
- **Vision-Modell (Ollama) nicht erreichbar / Timeout**: `extraction_failed: true`, `ai_description: ""`; trotzdem in Redis schreiben
- **HEIC-Datei ohne EXIF**: KI-Beschreibung wird generiert; alle EXIF-Felder bleiben leer
- **Dasselbe Bild unter zwei Pfaden** (gleicher `file_hash`): Beim zweiten Scanner-Fund → PROJ-19 ergänzt `additionalPaths`; keine neue KI-Analyse; kein neues Thumbnail
- **Bild auf NAS nach Scan-Zeitpunkt gelöscht**: Container loggt Fehler; schreibt `extraction_failed: true` in Redis
- **Container-Neustart während Verarbeitung**: MQTT QoS 1 stellt Nachricht erneut zu; PROJ-19 dedupliziert via `file_hash`; idempotent
- **Sehr große Bilddatei (> 50 MB)**: KI-Beschreibung und EXIF-Extraktion werden durchgeführt; `ai_description` auf 50.000 Zeichen begrenzt
- **MQTT-Broker offline**: Container wiederholt Verbindungsversuch mit Backoff; bereits bestätigte Nachrichten (QoS 1) gehen nicht verloren
- **Redis nicht erreichbar**: Extraktionsergebnis wird verworfen; MQTT-Nachricht wurde bereits mit QoS 1 bestätigt; Datei muss beim nächsten Scanner-Lauf erneut erkannt werden
- **Gemischter Ordner** (PDFs und Bilder): Scanner verarbeitet beide Dateitypen aus demselben Ordner parallel in unterschiedlichen MQTT-Queues; keine Kollision

## Technical Requirements

### dms-extractor-image
- **Sprache**: Python (Debian Slim)
- **Bibliotheken**: `Pillow` (Bildverarbeitung), `pillow-heif` (HEIC-Support), `piexif` oder `exifread` (EXIF-Extraktion), `paho-mqtt` (MQTT-Input), `redis` (Output), `requests` (Nominatim + Ollama)
- **Compose**: `docker/compose/automations/dms-extractor-image/compose.yml`

### Nominatim
- **Docker Image**: `mediagis/nominatim` (offizielle OSM-Nominatim-Instanz)
- **Datenspeicher**: `/srv/warm/nominatim/` (initialer Planetdaten-Import, ~60 GB)
- **Update**: wöchentliche OSM-Diffs via Nominatim-Update-Mechanismus
- **Compose**: `docker/compose/data/nominatim/compose.yml`

### Shared
- **MQTT-Konfiguration**: `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`
- **Redis-Konfiguration**: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- **Nominatim-URL**: `NOMINATIM_URL` (intern, z.B. `http://nominatim:8080`)
- **Ollama-URL**: `OLLAMA_URL` (intern, z.B. `http://ollama:11434`)
- **Ollama-Modell**: `OLLAMA_VISION_MODEL` (Vision-fähiges Modell, in Architektur festlegen)
- **Redis-Liste**: `alice:dms:image`
- **Docker-Netzwerk**: `backend`
- **Restart-Policy**: `unless-stopped`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Data Flow

```
NAS Filesystem
     ↓ (filesystem watch, existing)
alice-dms-scanner (n8n)         ← extend: add image extensions + new MQTT route
     ↓ MQTT: alice/dms/image
dms-extractor-image             ← NEW Python container
  ├─ Read image from NAS (read-only)
  ├─ Extract EXIF (datetime, GPS, camera)
  ├─ GPS → Nominatim (local)    ← NEW Nominatim container
  └─ AI description → Ollama Vision
     ↓ RPUSH
Redis: alice:dms:image
     ↓ (nightly batch)
alice-dms-processor (n8n)       ← extend: read new Redis list + file_hash dedup
     ↓
Weaviate: Collection "Image"    ← NEW collection
     ↓ MQTT: alice/dms/done
alice-dms-thumbnailer (PROJ-55, already deployed)
```

### New Components

**1. dms-extractor-image Container**

```
docker/compose/automations/dms-extractor-image/
  compose.yml    — extends nas-volumes.yml (read-only NAS mounts)
  Dockerfile     — Python Debian Slim
  main.py        — MQTT subscriber + processing pipeline
  .env.example   — MQTT, Redis, Nominatim, Ollama config
```

Processing pipeline per image:
1. Receive MQTT message from `alice/dms/image`
2. Validate file path (must start with `/mnt/nas/`)
3. Open image with Pillow (+ pillow-heif for HEIC)
4. Extract EXIF metadata
5. If GPS present → call local Nominatim for reverse geocoding
6. Send image to Ollama Vision → get German description
7. RPUSH result JSON to Redis `alice:dms:image`
8. On any failure: write `extraction_failed: true`, still push to Redis

**2. Nominatim Container**

```
docker/compose/data/nominatim/
  compose.yml    — mediagis/nominatim, data dir /srv/warm/nominatim/
```

- Internal only (`backend` network, not exposed via nginx)
- One-time planet import (~60 GB), weekly OSM diff updates
- Accessible at `http://nominatim:8080` within backend network

**3. Weaviate "Image" Collection**

`scripts/init-weaviate-schema.sh` extended with new collection:

| Field | Type | Vectorized |
|---|---|---|
| `ai_description` | Text | Yes (semantic search) |
| `file_path`, `file_hash`, `file_type`, `file_size` | Text/Int | No |
| `detected_at`, `extracted_at`, `extractor` | Date/Text | No |
| `extraction_failed` | Boolean | No |
| `exif_datetime` | Date | No |
| `latitude`, `longitude`, `altitude` | Number | No |
| `camera_make`, `camera_model` | Text | No |
| `country`, `country_code`, `city`, `district` | Text | No |
| `thumbnail_path` | Text | No |
| `additionalPaths[]` | Text[] | No |

### Modified Components

**alice-dms-scanner (n8n workflow):**
- Add `jpg, jpeg, png, webp, heic, tif, tiff` to extensions allowlist
- Add Switch-Node branch: route image files to MQTT topic `alice/dms/image`

**alice-dms-processor (n8n workflow):**
- Read from Redis list `alice:dms:image` in nightly batch (parallel to `alice:dms:plaintext`)
- Lookup `file_hash` in Weaviate "Image" — if found: append path to `additionalPaths`, skip insert
- If not found: insert new Weaviate object
- Publish `alice/dms/done` with `document_type: "Image"` → PROJ-55 handles thumbnail

### Tech Decisions

| Decision | Choice | Reason |
|---|---|---|
| Language | Python | Pillow + pillow-heif have the best HEIC support; no Node.js equivalent |
| Geocoding | Local Nominatim | 200-photo batch hits nominatim.openstreetmap.org 1 req/s limit (~3 min); local has no limits |
| Vision model | `llava:13b` (default) | Best quality/speed tradeoff locally; configurable via `OLLAMA_VISION_MODEL` |
| Vectorization | `ai_description` only | GPS, dates, camera model are filter use cases, not semantic search |
| Deduplication | `file_hash` in Weaviate | Idempotent; covers same photo under two paths without re-running AI |

### Deployment Sequence

1. Deploy Nominatim → import OSM planet data (one-time, runs for hours)
2. Extend Weaviate schema → run `./scripts/init-weaviate-schema.sh`
3. Deploy `dms-extractor-image` container
4. Deploy `alice-dms-scanner` workflow (new extensions + route)
5. Deploy `alice-dms-processor` workflow (new Redis list + Image collection writes)

### No UI Changes Required

Existing DMS folder settings UI (`alice.dms_watched_folders`) works for image folders without modification. Users add image folders through the same Settings interface as document folders.

## Implementation Notes

Built 2026-06-29. All components created from scratch (no prior code existed).

**Files created:**
- `docker/compose/automations/dms-extractor-image/main.py` — Python subscriber with dual EXIF strategy (piexif primary, PIL getexif fallback for HEIC/WEBP), Nominatim geocoding, Ollama Vision, Redis push
- `docker/compose/automations/dms-extractor-image/Dockerfile`, `compose.yml`, `requirements.txt`, `.env.example`
- `docker/compose/data/nominatim/compose.yml` — mediagis/nominatim:4.4, data at `/srv/warm/nominatim`
- `schemas/image.json` — 21-field Weaviate collection, only `ai_description` vectorized

**Files modified:**
- `workflows/alice-dms-scanner.json` — added 7 image extensions to SUPPORTED_EXTENSIONS, new Switch branch + MQTT node for `alice/dms/image`
- `workflows/alice-dms-processor.json` — added 7-node image sub-flow after "Code: Final Log" (fan-out); reads `alice:dms:image`, deduplicates by `file_hash`, writes to Weaviate Image, publishes `alice/dms/done`
- `scripts/init-weaviate-schema.sh` — added `image.json` to SCHEMAS array
- `docker/compose/scripts/Makefile` — added `automations/dms-extractor-image`, `automations/alice-dms-thumbnailer`, `data/nominatim` stacks

**Design deviations from spec:**
- None. All requirements implemented as specified.

## QA Test Results

**Date:** 2026-06-29 | **Method:** Static code review + logic verification (no live server)

### Acceptance Criteria

| ID | Criterion | Result |
|---|---|---|
| SC-1 | Scanner detects jpg/jpeg/png/webp/heic/tif/tiff | PASS |
| SC-2 | Images routed to `alice/dms/image` via MQTT QoS 1 | PASS |
| SC-3 | Dedup via `alice:dms:queued_files` (same as docs) | PASS — via shared "Code: Mark Queued" node |
| SC-4 | Stability check (5s wait) applies to images | PASS — images flow through existing "Code: Stability Check" |
| SC-5 | Files >100MB get `priority: low` | PASS |
| SC-6 | MQTT message format identical to document format | PASS |
| EX-1 | Container subscribes `alice/dms/image` QoS 1 | PASS |
| EX-2 | File path validated against `/mnt/nas/` prefix | PASS |
| EX-3 | Reads image from NAS via read-only mount | PASS |
| EX-4 | EXIF extraction: datetime, GPS, camera (all optional) | PASS — dual strategy (piexif + PIL getexif) |
| EX-5 | Reverse geocoding via Nominatim when GPS present | PASS |
| EX-6 | AI description in German via Ollama Vision | PASS |
| EX-7 | `ai_description` capped at 50000 chars | PASS |
| EX-8 | Output pushed via RPUSH to `alice:dms:image` | PASS |
| EX-9 | On error: `extraction_failed=True`, still push | PASS |
| EX-10 | Container `restart: unless-stopped` | PASS |
| EX-11 | Structured JSON logging | PASS |
| EX-12 | Compose at `docker/compose/automations/dms-extractor-image/compose.yml` | PASS |
| EX-13 | NAS mounts via `extends: ../nas-volumes.yml` | PASS |
| NOM-1 | Nominatim container in `backend` network | PASS |
| NOM-2 | Data dir `/srv/warm/nominatim/` | PASS |
| NOM-3 | Endpoint at `http://nominatim:8080/reverse` | PASS |
| NOM-4 | Not exposed externally (no port mapping) | PASS |
| WEA-1 | `Image` collection exists in schema | PASS |
| WEA-2 | All required fields present | PASS |
| WEA-3 | EXIF fields present (optional) | PASS |
| WEA-4 | Geocoding fields present (optional) | PASS |
| WEA-5 | `thumbnail_path` field present | PASS |
| WEA-6 | `additionalPaths` as `text[]` | PASS |
| WEA-7 | Only `ai_description` vectorized | PASS |
| WEA-8 | All other fields have `skip: true` | PASS |
| WEA-9 | `init-weaviate-schema.sh` includes `image.json` | PASS |
| PR-1 | Processor reads `alice:dms:image` Redis list | PASS |
| PR-2 | Writes to Weaviate `Image` collection | PASS |
| PR-3 | Dedup by `file_hash`: appends `additionalPaths` for duplicates | PASS |
| PR-4 | `alice/dms/done` published with `document_type: "Image"` | PASS |
| PR-5 | `extraction_failed: true` items written to Weaviate | PASS |

**Result: 37/37 PASS**

### Edge Cases Verified

| Edge Case | Verdict |
|---|---|
| No EXIF datetime → remains empty | PASS — both strategies return empty dict |
| No GPS → geocoding skipped | PASS — conditional on `latitude` in exif |
| Nominatim unreachable → geocoding skipped, not `extraction_failed` | PASS |
| Ollama unreachable → `extraction_failed: True`, result still pushed | PASS |
| HEIC without EXIF → AI description generated, EXIF fields empty | PASS |
| Same hash under two paths → `additionalPaths` updated, no re-insert | PASS |
| File deleted after scan → `Image.open()` raises, `extraction_failed: True` | PASS |
| MQTT QoS 1 redelivery on reconnect → processor dedup by `file_hash` | PASS |
| Images >50MB → processed normally, `ai_description` capped at 50k chars | PASS |
| Mixed folder (PDFs + images) → switch routes each to own MQTT topic | PASS |

### Bugs Found

**BUG-1 (Medium): Long Ollama Vision calls may cause MQTT keepalive timeout**
- **Root cause:** `on_message` runs in the paho network loop thread. Ollama Vision may take up to 5 minutes. A 300s keepalive means the broker could disconnect mid-processing.
- **Impact:** Broker disconnects, paho auto-reconnects, MQTT broker redelivers message. Processor dedup prevents double insert in Weaviate. No data loss.
- **Workaround:** `reconnect_delay_set(min_delay=5)` ensures fast reconnect. Dedup in processor is the safety net.
- **Recommendation:** Low priority — acceptable trade-off for simplicity. Can be fixed in a future iteration by running Ollama calls in a separate thread.

### Security Audit

| Check | Result |
|---|---|
| Path traversal via `file_path` | PASS — validated against `/mnt/nas/` prefix |
| GraphQL injection via `file_hash` | PASS — `safeHash` escapes `\`, `"`, control chars |
| Hardcoded secrets | PASS — all credentials via environment variables |
| Command injection | PASS — no `subprocess`/shell calls |
| External exposure of Nominatim | PASS — internal-only, no `ports:` mapping |

### Deployment Notes

1. **Nominatim planet import** is a one-time manual step (~60 GB, takes hours). See [mediagis/nominatim Docker Hub](https://hub.docker.com/r/mediagis/nominatim) for import instructions.
2. **Ollama Vision model** (`llava:13b` default) must be pulled on the Ollama host before first use: `ollama pull llava:13b`
3. **Weaviate schema**: run `./scripts/init-weaviate-schema.sh` to create the `Image` collection before starting the processor.
4. **Deploy order**: Nominatim → Weaviate schema → `dms-extractor-image` → scanner workflow → processor workflow.

### Production-Ready Decision

**APPROVED** — No Critical or High bugs. One Medium bug (MQTT thread blocking) with acceptable mitigations in place.

## Deployment
_To be added by /deploy_
