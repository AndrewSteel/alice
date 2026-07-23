# PROJ-56: DMS Bildanalyse

## Status: Deployed
**Created:** 2026-06-29
**Last Updated:** 2026-07-23

> **Hinweis:** Ursprünglich am 2026-07-03 vollständig deployed (siehe historische Sektionen unten: Tech Design, Implementation Notes, QA Test Results, Deployment). Am 2026-07-21 wurde das Geocoding-Subsystem grundlegend überarbeitet (Nominatim → externer Anbieter, siehe Abschnitt "Refinement Notes" am Ende des Dokuments) — die historischen Sektionen beschreiben den **veralteten** Nominatim-Ansatz und dienen nur noch als Referenz. Status auf "Planned" zurückgesetzt, da das Geocoding-Subsystem eine neue Architektur benötigt (`/architecture` als nächster Schritt). Alle anderen Komponenten (Scanner, EXIF-Extraktion, KI-Bildbeschreibung, Weaviate-Collection, Thumbnails) bleiben unverändert und sind weiterhin gültig — im Weaviate-Schema existierten laut Nutzer noch keine Bilddaten (Schema war nie vollständig deployed), ein Backfill bestehender Objekte ist daher nicht nötig.

## Dependencies
- Requires: PROJ-16 (DMS Scanner) — SUPPORTED_EXTENSIONS um Bildformate erweitern
- Requires: PROJ-17 (DMS Multi-Queue Routing) — neue Route `alice/dms/image` im Switch-Node
- Requires: PROJ-18 (DMS Extractor Container) — gleicher Implementierungsansatz für `dms-extractor-image`
- Requires: PROJ-19 (DMS Processor) — muss Redis-Liste `alice:dms:image` lesen und in neue Weaviate-Collection "Image" schreiben
- Requires: PROJ-55 (DMS Thumbnail-Generierung) — Thumbnailer generiert Thumbnails automatisch nach `alice/dms/done`; Bilder (Center-Crop) werden bereits unterstützt

## Overview

Bilder (JPG, PNG, WEBP, HEIC, TIFF) werden in die bestehende DMS-Pipeline integriert. Ein neuer Container `dms-extractor-image` abonniert die MQTT-Queue `alice/dms/image`, liest das Bild vom NAS, extrahiert EXIF-Metadaten (Aufnahmedatum, GPS, Kamera) und erzeugt eine KI-generierte Bildbeschreibung in deutscher Sprache über ein lokales Vision-Modell (Ollama). Das Ergebnis landet in der Redis-Liste `alice:dms:image`, aus der PROJ-19 nachts liest und es in eine neue Weaviate-Collection "Image" schreibt.

Falls GPS-Koordinaten im EXIF vorhanden sind, schreibt der Extractor zusätzlich eine Referenz (`file_hash`, `latitude`, `longitude`) in die separate Redis-Liste `alice:dms:geocode_pending`. Das eigentliche Reverse-Geocoding erfolgt **entkoppelt** als zweite Phase im nächtlichen `alice-dms-processor`-Lauf: nachdem alle Bilder der Nacht in Weaviate eingefügt wurden, ruft der Processor für ausstehende Geocode-Referenzen den externen Anbieter **Geoapify** auf (bis zum konfigurierten Tageslimit) und aktualisiert die bereits bestehenden Weaviate-Objekte per PATCH mit `country`, `country_code`, `city`, `district`. Reste, die das Tageslimit überschreiten, bleiben in der Liste und werden in der folgenden Nacht weiterverarbeitet.

Bilder, die denselben Datei-Hash haben (identischer Inhalt unter verschiedenen Pfaden), werden dedupliziert: der neue Pfad wird im `additionalPaths`-Feld der bestehenden Weaviate-Objekt ergänzt, ohne eine erneute KI-Analyse oder ein erneutes Geocoding auszulösen. Thumbnails generiert der bereits deployede PROJ-55-Thumbnailer automatisch.

**Warum externer Anbieter statt lokalem Nominatim?** Der ursprüngliche Ansatz (lokale Nominatim-Instanz mit ~60 GB Planetdaten auf `/srv/warm`) wurde verworfen: Der Speicherbedarf steht in keinem Verhältnis zum tatsächlichen Bedarf (< 1000 neue Bilder pro Urlaub), zusätzliche lokale Speicher-Investitionen sind aktuell nicht gewünscht, und der Nominatim-Container wurde bereits gestoppt. Bei diesem Volumen ist die Tageslimit-Problematik externer APIs (der ursprüngliche Ablehnungsgrund) irrelevant — ein Urlaubs-Backlog passt bequem in eine einzelne Nacht. Geoapify wurde als Anbieter gewählt (3000 Requests/Tag im Free-Tier, natives Batch-Geocoding passend zur nächtlichen Verarbeitung). Ein Kombinieren mehrerer Anbieter (OpenCage, LocationIQ) zur Erweiterung der Tageslimits wurde geprüft, aber verworfen — bei diesem Volumen unnötige Komplexität. Mapbox wurde ausgeschlossen: Nutzungsbedingungen verlangen i.d.R. Anzeige der Ergebnisse auf einer Mapbox-Karte, was nicht zur reinen Datenspeicherung in Weaviate passt.

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
- [ ] Wenn GPS-Koordinaten vorhanden: Extractor führt **kein** synchrones Geocoding mehr aus, sondern schreibt `{file_hash, latitude, longitude}` via `RPUSH` in die neue Redis-Liste `alice:dms:geocode_pending`
- [ ] KI-generierte Bildbeschreibung in deutscher Sprache via Ollama Vision-Modell (`ai_description`)
- [ ] `ai_description` wird auf max. 50.000 Zeichen begrenzt
- [ ] Output-JSON wird via `RPUSH` in Redis-Liste `alice:dms:image` geschrieben
- [ ] Bei Fehler (Datei nicht lesbar, KI nicht erreichbar): `extraction_failed: true`, `ai_description: ""`, trotzdem in Redis schreiben
- [ ] Container startet automatisch neu (`restart: unless-stopped`)
- [ ] Fehler werden strukturiert geloggt (JSON-Format)
- [ ] Compose-File: `docker/compose/automations/dms-extractor-image/compose.yml`
- [ ] NAS-Mounts via `extends: ../nas-volumes.yml` (read-only)

### Externes Geocoding (Geoapify, nächtliche Batch-Verarbeitung)

- [ ] Reverse-Geocoding erfolgt über die externe Geoapify-API (`GEOAPIFY_API_KEY` als Secret)
- [ ] Verarbeitung erfolgt als zweite Phase im nächtlichen `alice-dms-processor`-Lauf, **nach** dem Insert-Schritt für `alice:dms:image` (garantiert, dass das Weaviate-Objekt beim Geocoding bereits existiert)
- [ ] Processor liest Einträge aus `alice:dms:geocode_pending`, sucht das zugehörige Weaviate-Objekt über `file_hash` und aktualisiert es per PATCH mit `country`, `country_code`, `city`, `district`
- [ ] Tageslimit wird über einen Redis-Zähler (`alice:dms:geocode_quota:<YYYY-MM-DD>`) nachgehalten; Standardwert `GEOAPIFY_DAILY_LIMIT=3000`
- [ ] Wird das Tageslimit während der Nachtverarbeitung erreicht, bricht die Geocoding-Phase ab; verbleibende Einträge bleiben in `alice:dms:geocode_pending` und werden in der nächsten Nacht weiterverarbeitet
- [ ] Liefert Geoapify für eine Koordinate kein Ergebnis (z.B. offene See): Eintrag gilt als verarbeitet (aus Warteschlange entfernt), Geocoding-Felder bleiben leer, kein Fehler
- [ ] Wird zu einem `file_hash` aus `alice:dms:geocode_pending` kein Weaviate-Objekt gefunden (Race Condition, z.B. Prozessor-Neustart zwischen den Phasen): Eintrag bleibt in der Warteschlange und wird im nächsten Lauf erneut versucht
- [ ] Keine lokale Vorhaltung von Kartendaten nötig (kein Nominatim-Container, kein `/srv/warm`-Speicherbedarf für Geodaten)

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
- [ ] **Neue Phase (Geocoding):** nach Abschluss aller Inserts aus `alice:dms:image` verarbeitet der Processor `alice:dms:geocode_pending` gemäß den Kriterien im Abschnitt "Externes Geocoding (Geoapify, nächtliche Batch-Verarbeitung)"

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
  }
}
```

Pflichtfelder (immer vorhanden): `file_path`, `file_hash`, `file_type`, `file_size`, `detected_at`, `extracted_at`, `extractor`, `ai_description`, `extraction_failed`

Optionale Felder: `exif` (komplett oder einzelne Unterfelder)

Das `geocoding`-Objekt ist **nicht mehr Teil** des Extractor-Outputs — Geocoding erfolgt entkoppelt über die nächtliche Processor-Phase (siehe unten).

## Output-Format (Redis-Liste `alice:dms:geocode_pending`)

Nur geschrieben, wenn `exif.latitude`/`exif.longitude` vorhanden sind:

```json
{
  "file_hash": "sha256:abc123...",
  "latitude": 35.6762,
  "longitude": 139.6503
}
```

Der nächtliche Processor löst `file_hash` gegen das bereits in Weaviate eingefügte Objekt auf und aktualisiert es per PATCH mit den von Geoapify gelieferten Feldern (`country`, `country_code`, `city`, `district`).

## Edge Cases

- **Kein EXIF-Datum vorhanden** (Screenshot, WhatsApp-Bild): `exif_datetime` bleibt leer; `detected_at` (Scan-Zeitpunkt) wird nicht als Ersatz gesetzt — fehlende Daten bleiben fehlend
- **Keine GPS-Koordinaten**: Es wird kein Eintrag in `alice:dms:geocode_pending` geschrieben; `country`, `city`, `district` bleiben leer; kein Fehler
- **Geoapify-Tageslimit erreicht**: Geocoding-Phase bricht für die laufende Nacht ab; verbleibende Einträge bleiben in `alice:dms:geocode_pending` und werden in der nächsten Nacht weiterverarbeitet; kein `extraction_failed`
- **Geoapify liefert kein Ergebnis für Koordinate** (z.B. offene See): Eintrag gilt als verarbeitet; Geocoding-Felder bleiben leer; kein Fehler
- **Geoapify nicht erreichbar (Ausfall)**: Geocoding-Phase bricht ab; Einträge bleiben in `alice:dms:geocode_pending`; Bild selbst wurde bereits vollständig verarbeitet (EXIF + KI-Beschreibung unabhängig vom Geocoding)
- **`file_hash` aus `alice:dms:geocode_pending` noch nicht in Weaviate vorhanden** (Race Condition, z.B. Processor-Neustart zwischen Insert- und Geocoding-Phase): Eintrag bleibt in der Warteschlange, wird im nächsten Lauf erneut versucht
- **Vision-Modell (Ollama) nicht erreichbar / Timeout**: `extraction_failed: true`, `ai_description: ""`; trotzdem in Redis schreiben
- **HEIC-Datei ohne EXIF**: KI-Beschreibung wird generiert; alle EXIF-Felder bleiben leer
- **Dasselbe Bild unter zwei Pfaden** (gleicher `file_hash`): Beim zweiten Scanner-Fund → PROJ-19 ergänzt `additionalPaths`; keine neue KI-Analyse; kein neues Thumbnail; kein doppelter Geocode-Eintrag (bereits geocodetes Objekt wird nicht erneut in die Warteschlange aufgenommen)
- **Bild auf NAS nach Scan-Zeitpunkt gelöscht**: Container loggt Fehler; schreibt `extraction_failed: true` in Redis
- **Container-Neustart während Verarbeitung**: MQTT QoS 1 stellt Nachricht erneut zu; PROJ-19 dedupliziert via `file_hash`; idempotent
- **Sehr große Bilddatei (> 50 MB)**: KI-Beschreibung und EXIF-Extraktion werden durchgeführt; `ai_description` auf 50.000 Zeichen begrenzt
- **MQTT-Broker offline**: Container wiederholt Verbindungsversuch mit Backoff; bereits bestätigte Nachrichten (QoS 1) gehen nicht verloren
- **Redis nicht erreichbar**: Extraktionsergebnis wird verworfen; MQTT-Nachricht wurde bereits mit QoS 1 bestätigt; Datei muss beim nächsten Scanner-Lauf erneut erkannt werden
- **Gemischter Ordner** (PDFs und Bilder): Scanner verarbeitet beide Dateitypen aus demselben Ordner parallel in unterschiedlichen MQTT-Queues; keine Kollision

## Technical Requirements

### dms-extractor-image

- **Sprache**: Python (Debian Slim)
- **Bibliotheken**: `Pillow` (Bildverarbeitung), `pillow-heif` (HEIC-Support), `piexif` oder `exifread` (EXIF-Extraktion), `paho-mqtt` (MQTT-Input), `redis` (Output), `requests` (Ollama)
- **Compose**: `docker/compose/automations/dms-extractor-image/compose.yml`

### Geoapify (Geocoding, in alice-dms-processor integriert)

- **Anbieter**: Geoapify Reverse Geocoding API (Free-Tier, 3000 Requests/Tag)
- **Kein eigener Container/Compose-File nötig** — Aufruf erfolgt aus dem bestehenden `alice-dms-processor`-Workflow (n8n HTTP-Request-Node)
- **Quota-Tracking**: Redis-Zähler `alice:dms:geocode_quota:<YYYY-MM-DD>`

### Shared

- **MQTT-Konfiguration**: `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`
- **Redis-Konfiguration**: `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`
- **Geoapify-Konfiguration**: `GEOAPIFY_API_KEY`, `GEOAPIFY_DAILY_LIMIT` (Default `3000`)
- **Ollama-URL**: `OLLAMA_URL` (intern, z.B. `http://ollama:11434`)
- **Ollama-Modell**: `OLLAMA_VISION_MODEL` (Vision-fähiges Modell, in Architektur festlegen)
- **Redis-Listen**: `alice:dms:image`, `alice:dms:geocode_pending`
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
- PostgreSQL-Daten persistent auf `/srv/warm/nominatim` (Volume-Mount auf `/var/lib/postgresql/14/main`)
- One-time planet import (~70 GB Download + mehrstündiger PostgreSQL-Import), danach tägliche OSM-Diff-Updates via `REPLICATION_URL`
- PBF-Datei (`/nominatim/data.osm.pbf`) wird nach dem Import automatisch gelöscht
- Accessible at `http://nominatim:8080` within backend network
- Kein Watchtower-Auto-Update (Standard-Image → manuelle Updates wegen möglichem DB-Schema-Wechsel)
- `dns: [8.8.8.8, 1.1.1.1]` als Fallback falls internes Netzwerk-DNS externe Hostnamen nicht auflöst

**3. Weaviate "Image" Collection**

`scripts/init-weaviate-schema.sh` extended with new collection:

| Field                                              | Type      | Vectorized            |
| -------------------------------------------------- | --------- | --------------------- |
| `ai_description`                                   | Text      | Yes (semantic search) |
| `file_path`, `file_hash`, `file_type`, `file_size` | Text/Int  | No                    |
| `detected_at`, `extracted_at`, `extractor`         | Date/Text | No                    |
| `extraction_failed`                                | Boolean   | No                    |
| `exif_datetime`                                    | Date      | No                    |
| `latitude`, `longitude`, `altitude`                | Number    | No                    |
| `camera_make`, `camera_model`                      | Text      | No                    |
| `country`, `country_code`, `city`, `district`      | Text      | No                    |
| `thumbnail_path`                                   | Text      | No                    |
| `additionalPaths[]`                                | Text[]    | No                    |

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

| Decision      | Choice                  | Reason                                                                                       |
| ------------- | ----------------------- | -------------------------------------------------------------------------------------------- |
| Language      | Python                  | Pillow + pillow-heif have the best HEIC support; no Node.js equivalent                       |
| Geocoding     | Local Nominatim         | 200-photo batch hits nominatim.openstreetmap.org 1 req/s limit (~3 min); local has no limits |
| Vision model  | `llava:13b` (default)   | Best quality/speed tradeoff locally; configurable via `OLLAMA_VISION_MODEL`                  |
| Vectorization | `ai_description` only   | GPS, dates, camera model are filter use cases, not semantic search                           |
| Deduplication | `file_hash` in Weaviate | Idempotent; covers same photo under two paths without re-running AI                          |

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
- `docker/compose/data/nominatim/compose.yml` — mediagis/nominatim:4.4, PostgreSQL-Daten auf `/srv/warm/nominatim` (Volume-Mount korrigiert: `/var/lib/postgresql/14/main`, nicht `/nominatim/data`)
- `schemas/image.json` — 21-field Weaviate collection, only `ai_description` vectorized

**Files modified:**
- `workflows/alice-dms-scanner.json` — added 7 image extensions to SUPPORTED_EXTENSIONS, new Switch branch + MQTT node for `alice/dms/image`
- `workflows/alice-dms-processor.json` — added 7-node image sub-flow after "Code: Final Log" (fan-out); reads `alice:dms:image`, deduplicates by `file_hash`, writes to Weaviate Image, publishes `alice/dms/done`
- `scripts/init-weaviate-schema.sh` — added `image.json` to SCHEMAS array
- `docker/compose/scripts/Makefile` — added `automations/dms-extractor-image`, `automations/alice-dms-thumbnailer`, `data/nominatim` stacks

**Post-deploy fixes (2026-06-30):**
- `OLLAMA_VISION_MODEL` auf `qwen3.5:27b-q4_K_M` geändert (bereits im Einsatz, bessere Deutschkenntnisse als llava:13b)
- Nominatim Volume-Pfad korrigiert: `/nominatim/data` → `/var/lib/postgresql/14/main` (PostgreSQL schreibt nicht in `/nominatim/data`)
- Nominatim `NOMINATIM_PASSWORD` entfernt (irrelevant für HTTP-API-Betrieb)
- Nominatim Watchtower-Label entfernt (Standard-Image, manuelle Updates gewünscht)
- Nominatim `start_period` auf `48h` erhöht (planet import dauert viele Stunden)
- Nominatim `dns: [8.8.8.8, 1.1.1.1]` als Fallback nach Netzwerk-Inkonsistenz beim Neustart
- Nominatim `PBF_URL` auf echte Planet-Download-URL gesetzt (`https://planet.openstreetmap.org/pbf/planet-latest.osm.pbf`) — war leer
- `OLLAMA_URL` in `dms-extractor-image/.env.example` auf `http://ollama-3090:11434` korrigiert (tatsächlicher Hostname im Netzwerk)
- `nas-volumes.yml` um `/mnt/nas/shared:ro`-Mount erweitert
- Sidebar `ServiceLinks.tsx`: neuer "Storage"-Link (`http://storage.lan:5000`) für Zugriff auf NAS-Weboberfläche
- `docs/PRD.md`: PROJ-56 in Feature-Tabelle ergänzt

**Design deviations from spec:**
- None. All requirements implemented as specified.

## QA Test Results

**Date:** 2026-06-29 | **Method:** Static code review + logic verification (no live server)

### Acceptance Criteria

| ID    | Criterion                                                               | Result                                                      |
| ----- | ----------------------------------------------------------------------- | ----------------------------------------------------------- |
| SC-1  | Scanner detects jpg/jpeg/png/webp/heic/tif/tiff                         | PASS                                                        |
| SC-2  | Images routed to `alice/dms/image` via MQTT QoS 1                       | PASS                                                        |
| SC-3  | Dedup via `alice:dms:queued_files` (same as docs)                       | PASS — via shared "Code: Mark Queued" node                  |
| SC-4  | Stability check (5s wait) applies to images                             | PASS — images flow through existing "Code: Stability Check" |
| SC-5  | Files >100MB get `priority: low`                                        | PASS                                                        |
| SC-6  | MQTT message format identical to document format                        | PASS                                                        |
| EX-1  | Container subscribes `alice/dms/image` QoS 1                            | PASS                                                        |
| EX-2  | File path validated against `/mnt/nas/` prefix                          | PASS                                                        |
| EX-3  | Reads image from NAS via read-only mount                                | PASS                                                        |
| EX-4  | EXIF extraction: datetime, GPS, camera (all optional)                   | PASS — dual strategy (piexif + PIL getexif)                 |
| EX-5  | Reverse geocoding via Nominatim when GPS present                        | PASS                                                        |
| EX-6  | AI description in German via Ollama Vision                              | PASS                                                        |
| EX-7  | `ai_description` capped at 50000 chars                                  | PASS                                                        |
| EX-8  | Output pushed via RPUSH to `alice:dms:image`                            | PASS                                                        |
| EX-9  | On error: `extraction_failed=True`, still push                          | PASS                                                        |
| EX-10 | Container `restart: unless-stopped`                                     | PASS                                                        |
| EX-11 | Structured JSON logging                                                 | PASS                                                        |
| EX-12 | Compose at `docker/compose/automations/dms-extractor-image/compose.yml` | PASS                                                        |
| EX-13 | NAS mounts via `extends: ../nas-volumes.yml`                            | PASS                                                        |
| NOM-1 | Nominatim container in `backend` network                                | PASS                                                        |
| NOM-2 | Data dir `/srv/warm/nominatim/`                                         | PASS                                                        |
| NOM-3 | Endpoint at `http://nominatim:8080/reverse`                             | PASS                                                        |
| NOM-4 | Not exposed externally (no port mapping)                                | PASS                                                        |
| WEA-1 | `Image` collection exists in schema                                     | PASS                                                        |
| WEA-2 | All required fields present                                             | PASS                                                        |
| WEA-3 | EXIF fields present (optional)                                          | PASS                                                        |
| WEA-4 | Geocoding fields present (optional)                                     | PASS                                                        |
| WEA-5 | `thumbnail_path` field present                                          | PASS                                                        |
| WEA-6 | `additionalPaths` as `text[]`                                           | PASS                                                        |
| WEA-7 | Only `ai_description` vectorized                                        | PASS                                                        |
| WEA-8 | All other fields have `skip: true`                                      | PASS                                                        |
| WEA-9 | `init-weaviate-schema.sh` includes `image.json`                         | PASS                                                        |
| PR-1  | Processor reads `alice:dms:image` Redis list                            | PASS                                                        |
| PR-2  | Writes to Weaviate `Image` collection                                   | PASS                                                        |
| PR-3  | Dedup by `file_hash`: appends `additionalPaths` for duplicates          | PASS                                                        |
| PR-4  | `alice/dms/done` published with `document_type: "Image"`                | PASS                                                        |
| PR-5  | `extraction_failed: true` items written to Weaviate                     | PASS                                                        |

**Result: 37/37 PASS**

### Edge Cases Verified

| Edge Case                                                                  | Verdict                                  |
| -------------------------------------------------------------------------- | ---------------------------------------- |
| No EXIF datetime → remains empty                                           | PASS — both strategies return empty dict |
| No GPS → geocoding skipped                                                 | PASS — conditional on `latitude` in exif |
| Nominatim unreachable → geocoding skipped, not `extraction_failed`         | PASS                                     |
| Ollama unreachable → `extraction_failed: True`, result still pushed        | PASS                                     |
| HEIC without EXIF → AI description generated, EXIF fields empty            | PASS                                     |
| Same hash under two paths → `additionalPaths` updated, no re-insert        | PASS                                     |
| File deleted after scan → `Image.open()` raises, `extraction_failed: True` | PASS                                     |
| MQTT QoS 1 redelivery on reconnect → processor dedup by `file_hash`        | PASS                                     |
| Images >50MB → processed normally, `ai_description` capped at 50k chars    | PASS                                     |
| Mixed folder (PDFs + images) → switch routes each to own MQTT topic        | PASS                                     |

### Bugs Found

**BUG-1 (Medium): Long Ollama Vision calls may cause MQTT keepalive timeout**
- **Root cause:** `on_message` runs in the paho network loop thread. Ollama Vision may take up to 5 minutes. A 300s keepalive means the broker could disconnect mid-processing.
- **Impact:** Broker disconnects, paho auto-reconnects, MQTT broker redelivers message. Processor dedup prevents double insert in Weaviate. No data loss.
- **Workaround:** `reconnect_delay_set(min_delay=5)` ensures fast reconnect. Dedup in processor is the safety net.
- **Recommendation:** Low priority — acceptable trade-off for simplicity. Can be fixed in a future iteration by running Ollama calls in a separate thread.

### Security Audit

| Check                             | Result                                            |
| --------------------------------- | ------------------------------------------------- |
| Path traversal via `file_path`    | PASS — validated against `/mnt/nas/` prefix       |
| GraphQL injection via `file_hash` | PASS — `safeHash` escapes `\`, `"`, control chars |
| Hardcoded secrets                 | PASS — all credentials via environment variables  |
| Command injection                 | PASS — no `subprocess`/shell calls                |
| External exposure of Nominatim    | PASS — internal-only, no `ports:` mapping         |

### Deployment Notes

1. **Nominatim planet import** is a one-time manual step (~60 GB, takes hours). See [mediagis/nominatim Docker Hub](https://hub.docker.com/r/mediagis/nominatim) for import instructions.
2. **Ollama Vision model** (`qwen3.5:27b-q4_K_M` default) must be pulled on the Ollama host before first use: `ollama pull qwen3.5:27b-q4_K_M`
3. **Weaviate schema**: run `./scripts/init-weaviate-schema.sh` to create the `Image` collection before starting the processor.
4. **Deploy order**: Nominatim → Weaviate schema → `dms-extractor-image` → scanner workflow → processor workflow.

### Production-Ready Decision

**APPROVED** — No Critical or High bugs. One Medium bug (MQTT thread blocking) with acceptable mitigations in place.

## Deployment

- **Date:** 2026-07-03
- Deployed by user directly on `ki.lan`: Nominatim planet import, Weaviate "Image" schema, `dms-extractor-image` container, `alice-dms-scanner` + `alice-dms-processor` workflows
- Post-deploy config fixes applied (see Implementation Notes above)

**Diese historische Deployment-Sektion beschreibt den mittlerweile abgelösten Nominatim-Ansatz — siehe [Refinement Notes](#refinement-notes-2026-07-21) unten.**

---

## Refinement Notes (2026-07-21)

**Trigger:** Path 1 — Something Changed (`/refine`)

**Was sich geändert hat:**
Der lokale Nominatim-Ansatz wurde verworfen. Gründe:
- Der Speicherbedarf (~60 GB Planetdaten auf `/srv/warm`) steht in keinem Verhältnis zum tatsächlichen Bedarf — künftige Bilder kommen in kleinen Stückzahlen (< 1000 pro Urlaub) hinzu, für die die eigentliche Motivation für lokales Geocoding (Umgehen externer Rate-Limits bei großen Foto-Sessions) nicht mehr relevant ist
- Keine zusätzlichen lokalen Speicher-Investitionen aktuell gewünscht
- Der Nominatim-Container wurde bereits gestoppt und steht nicht mehr zur Verfügung

**Getroffene Entscheidungen:**
1. **Anbieter:** Geoapify (Free-Tier, 3000 Requests/Tag), einzelner Anbieter — kein Kombinieren mehrerer APIs. Bei < 1000 Bildern/Urlaub reicht ein Anbieter bequem aus (Backlog < 1 Nacht); Kombinieren mehrerer APIs (OpenCage, LocationIQ) wäre unnötige Komplexität bei diesem Volumen. Mapbox ausgeschlossen (Nutzungsbedingungen verlangen i.d.R. Kartenanzeige der Ergebnisse).
2. **Entkopplung:** `dms-extractor-image` löst kein synchrones Geocoding mehr aus, sondern schreibt GPS-Referenzen in die neue Redis-Liste `alice:dms:geocode_pending`. Das eigentliche Geocoding erfolgt als zweite, vom Rest der Bildanalyse unabhängige Phase im bestehenden nächtlichen `alice-dms-processor`-Lauf (nach dem Insert-Schritt), orientiert an Geoapifys Tageslimit. Integration in den bestehenden Workflow statt separatem neuen Workflow — nutzt bestehende Redis-/Weaviate-Verbindungen, ein Wartungspunkt.
3. **Backfill:** Nicht nötig — das Weaviate-Schema für die Collection "Image" wurde nie vollständig deployed, es existieren noch keine Bilddaten in Weaviate.

**Betroffene Abschnitte:** Overview, Acceptance Criteria (Nominatim-Container-Sektion ersetzt durch "Externes Geocoding (Geoapify, nächtliche Batch-Verarbeitung)"; dms-extractor-image- und PROJ-19-Processor-Sektionen aktualisiert), Output-Format (neue Redis-Liste `alice:dms:geocode_pending`), Edge Cases, Technical Requirements.

**Nicht betroffen:** Scanner-Erweiterung, EXIF-Extraktion, KI-Bildbeschreibung (Ollama Vision), Weaviate-Collection-Struktur (Feldnamen `country`/`country_code`/`city`/`district` unverändert — nur die Datenquelle ändert sich), Thumbnail-Generierung (PROJ-55).

**Nächster Schritt:** `/architecture` — Solution-Architect-Entwurf für die neue Geocoding-Phase im `alice-dms-processor`-Workflow (Geoapify-API-Integration, Quota-Zähler-Logik, PATCH-Update-Mechanismus für bestehende Weaviate-Objekte). Der bestehende Tech-Design-Abschnitt oben beschreibt weiterhin korrekt Scanner, Extractor-Grundgerüst und Weaviate-Schema — nur die Nominatim-bezogenen Teile sind obsolet.

---

## Tech Design Update (Solution Architect) — 2026-07-21: Geoapify Geocoding Phase

Ersetzt nur den Nominatim-bezogenen Teil des Tech-Designs oben (Scanner, Extractor-Grundgerüst, Weaviate-Schema bleiben wie oben beschrieben gültig).

### Workflow Architecture

**Trigger:** Kein neuer Trigger. Die Geocoding-Phase ist eine dritte Phase innerhalb des bestehenden nächtlichen `alice-dms-processor`-Laufs (Schedule: Nightly 02:00) — sie startet direkt im Anschluss an die bereits deployte Bild-Phase (endet aktuell bei "MQTT: Publish Image Done").

**Nodes (High-Level, in Ablaufreihenfolge):**

1. **Fetch Geocode Batch** — liest ausstehende Einträge aus der Redis-Liste `alice:dms:geocode_pending`
2. **IF Queue Empty** — keine Einträge → Phase überspringen, Workflow endet regulär
3. **Check Quota** — liest den Redis-Tageszähler `alice:dms:geocode_quota:<YYYY-MM-DD>`; ist das Limit (`GEOAPIFY_DAILY_LIMIT`, Standard 3000) erreicht → Phase sofort abbrechen, verbleibende Einträge bleiben unangetastet in der Warteschlange
4. **Lookup Weaviate Object** — sucht das Image-Objekt anhand `file_hash`
5. **IF Not Found** — Race-Condition-Fall (Objekt noch nicht eingefügt): Eintrag bleibt in der Warteschlange, weiter zum nächsten Eintrag (kein Abbruch der ganzen Phase)
6. **Call Geoapify** — Reverse-Geocoding-Aufruf mit `latitude`/`longitude`; Quota-Zähler wird nach jedem Aufruf erhöht
7. **IF No Result** — Geoapify liefert keinen Treffer (z. B. offene See): Eintrag gilt als erledigt, Geocoding-Felder bleiben leer
8. **Update Weaviate (PATCH)** — aktualisiert nur `country`, `country_code`, `city`, `district` am bestehenden Objekt; alle anderen Felder (inkl. `ai_description`) bleiben unangetastet
9. **Dequeue Entry** — entfernt den erledigten Eintrag aus `alice:dms:geocode_pending`
10. **Loop** — nächster Eintrag, bis Warteschlange leer, Quota erreicht, oder Geoapify nicht erreichbar

**Data Flow:**

```
alice:dms:geocode_pending (Redis)
     ↓ Quota-Check (alice:dms:geocode_quota:<datum>)
     ↓ Weaviate-Lookup per file_hash
     ↓ Geoapify Reverse-Geocoding-Aufruf
     ↓ Weaviate PATCH (country, country_code, city, district)
     ↓ Dequeue
```

**Integrations:**
- **Redis** — Warteschlange (`alice:dms:geocode_pending`) + Tages-Quota-Zähler (`alice:dms:geocode_quota:<YYYY-MM-DD>`), gleiche Redis-Instanz wie der Rest des Processors
- **Geoapify** — externe Reverse-Geocoding-API, Zugriff per API-Key (als n8n-Credential hinterlegt, nicht im Workflow-JSON)
- **Weaviate** — bestehende "Image"-Collection, PATCH-Update auf vorhandene Objekte (kein neues Objekt, kein Re-Insert)

**Error Handling:**
- **Tageslimit erreicht** → Phase bricht kontrolliert ab, keine Fehlermeldung, Rest bleibt für die nächste Nacht in der Warteschlange
- **Geoapify nicht erreichbar** → Phase bricht ab (wie Tageslimit), Warteschlange bleibt bestehen; Bildverarbeitung selbst ist davon unabhängig bereits abgeschlossen
- **Kein Ergebnis für Koordinate** → kein Fehler, Eintrag wird trotzdem als erledigt markiert
- **Weaviate-Objekt nicht gefunden** → kein Fehler, Eintrag bleibt in Warteschlange für nächsten Lauf

### Tech Decisions

| Entscheidung | Wahl | Begründung |
| --- | --- | --- |
| Workflow-Platzierung | Dritte Phase im bestehenden `alice-dms-processor` | Nutzt vorhandene Redis-/Weaviate-Verbindungen und den vorhandenen Nightly-Trigger; kein zweiter Wartungspunkt für einen separaten Workflow |
| Update-Mechanismus | PATCH statt Re-Insert | Verhindert versehentliches Überschreiben von `ai_description` oder anderen bereits gesetzten Feldern |
| Quota-Tracking | Redis-Tageszähler mit datumsbasiertem Key | Selbstzurücksetzend (kein Cleanup-Job nötig), einfache Lese-Erhöhen-Logik ohne Cross-Run-Koordination |
| API-Key-Ablage | n8n-Credential | Konsistent mit "kein Secret im Code" (siehe `.claude/rules/backend.md`); kein Klartext-Key im Workflow-JSON |
| Rate-Limiting (5 req/s) | Fixe 220ms-Pause nach jedem Geoapify-Call | Geoapify Free-Tier begrenzt zusätzlich zum Tageslimit auf 5 Requests/Sekunde. Die Phase verarbeitet Einträge streng sequenziell (ein Item gleichzeitig via `Split In Batches`), daher reicht eine flache Pause pro Call statt eines Token-Buckets über mehrere Läufe hinweg |

### Dependencies

Keine neuen Packages — der Geoapify-Aufruf erfolgt über den bestehenden n8n-HTTP-Request-Node-Typ, der im Workflow bereits für Ollama/Weaviate-Aufrufe verwendet wird.

### No UI Changes Required

Diese Phase ist rein workflow-intern; es gibt keine Nutzeroberfläche für Geocoding-Status oder Quota.

## Implementation Notes (Refinement 2026-07-21)

**Files modified:**
- `docker/compose/automations/dms-extractor-image/main.py` — `reverse_geocode()` (Nominatim call) und `NOMINATIM_URL` entfernt; wenn GPS im EXIF vorhanden, wird stattdessen `{file_hash, latitude, longitude}` via `RPUSH` in die neue Redis-Liste `alice:dms:geocode_pending` geschrieben. Das `geocoding`-Objekt erscheint nicht mehr im `alice:dms:image`-Output.
- `docker/compose/automations/dms-extractor-image/.env.example` — `NOMINATIM_URL`-Block entfernt.
- `docker/compose/automations/n8n/compose.yml` und `.env.example` — `GEOAPIFY_API_KEY` und `GEOAPIFY_DAILY_LIMIT` als neue Environment-Variablen ergänzt.
- `workflows/alice-dms-processor.json` — neue dritte Phase ("Geocode Sub-Flow") mit 6 Nodes + Sticky Note (`geo-01-fetch-items` … `geo-06-continue`, Slug-Konvention analog zu `img-*`), verdrahtet ab `End: Image Done`. Liest `alice:dms:geocode_pending`, prüft den Tages-Quota-Zähler `alice:dms:geocode_quota:<YYYY-MM-DD>` (`GEOAPIFY_DAILY_LIMIT`, Default 3000), sucht das Weaviate-Image-Objekt per `file_hash`, ruft Geoapify auf und aktualisiert `country`/`country_code`/`city`/`district` per PATCH. Quota erreicht oder Geoapify nicht erreichbar bricht die ganze Phase ab (verbleibende Einträge bleiben in der Warteschlange); "nicht gefunden" (Race Condition) lässt nur den einzelnen Eintrag in der Warteschlange, die Phase läuft weiter. Nach jedem tatsächlichen Geoapify-Call wartet der Node fix 220ms, um Geoapifys Limit von 5 Requests/Sekunde einzuhalten (zusätzlich zum Tageslimit; siehe Tech-Decisions-Tabelle und BUG-2 im QA-Abschnitt). `Code: Process Image Item` (bestehender Node) brauchte keine Änderung — `const geo = item.geocoding || {};` behandelt das Fehlen von `geocoding` bereits korrekt.
- `docker/compose/data/nominatim/compose.yml` — gelöscht (Container bereits gestoppt, war schon aus dem Makefile `STACKS` auskommentiert).

**Design deviations from architecture doc:**
- Tech Design Update schlug ein n8n-Credential-Objekt für `GEOAPIFY_API_KEY` vor. Stattdessen wurde ein einfacher Environment-Variable-Ansatz gewählt (Nutzerentscheidung während `/plan`), konsistent mit allen anderen Secrets in diesem Workflow (`REDIS_PASSWORD`, `HA_TOKEN`, `OLLAMA_*`), die ebenfalls ausschließlich über `$env` gelesen werden — kein n8n-Credential existiert in diesem Workflow außer beim MQTT-Node (dort vom Node-Typ erzwungen).

**Nicht betroffen:** `schemas/image.json` (Felder `country`/`country_code`/`city`/`district` existierten bereits, non-vectorized, keine Änderung nötig), `docker/compose/scripts/Makefile` (Nominatim-Zeile war bereits auskommentiert, keine weitere Änderung nötig).

## QA Test Results (Refinement 2026-07-21)

**Method:** Static code review + JS syntax check (`node --check`) + JSON structural/connectivity validation of the workflow (no live server — same methodology as the original PROJ-56 QA pass).

### Acceptance Criteria — Externes Geocoding (Geoapify, nächtliche Batch-Verarbeitung)

| Criterion                                                                    | Result                                                        |
| ----------------------------------------------------------------------------- | -------------------------------------------------------------- |
| Reverse-Geocoding über Geoapify-API, `GEOAPIFY_API_KEY` als Secret            | PASS — env var only, no hardcoded key                          |
| Läuft als zweite/dritte Phase nach Insert-Schritt für `alice:dms:image`       | PASS — wired from `End: Image Done`, the image phase's true terminal node |
| Liest `alice:dms:geocode_pending`, sucht per `file_hash`, PATCH 4 Felder      | PASS — GraphQL lookup + PATCH with only `country`/`country_code`/`city`/`district` |
| Tageslimit via `alice:dms:geocode_quota:<YYYY-MM-DD>`, Default 3000           | PASS                                                            |
| Tageslimit erreicht → Phase bricht ab, Reste bleiben in Warteschlange         | PASS — `quota_reached` routes to `End: Geocode Done`, un-dequeued entries stay |
| Kein Geoapify-Treffer → Eintrag verarbeitet, Felder leer, kein Fehler         | PASS — `done_no_match` dequeues without PATCH                  |
| `file_hash` nicht in Weaviate (Race Condition) → Eintrag bleibt, Retry        | PASS — `not_found_yet` does not dequeue                        |
| Keine lokale Kartendaten nötig                                                | PASS — Nominatim container/compose file removed                |

### Edge Cases Verified

| Edge Case                                                                        | Verdict |
| ----------------------------------------------------------------------------------- | ------- |
| Keine GPS-Koordinaten → kein `geocode_pending`-Eintrag                              | PASS — extractor only RPUSHes when both lat/lon present |
| Geoapify-Tageslimit erreicht während der Nacht                                      | PASS |
| Geoapify liefert kein Ergebnis                                                      | PASS |
| Geoapify nicht erreichbar → Phase bricht ab, Bild selbst bereits verarbeitet        | PASS — `unreachable` stops the loop without touching quota/dequeue |
| `file_hash` noch nicht in Weaviate (Prozessor-Neustart zwischen Phasen)             | PASS |
| Dasselbe Bild unter zwei Pfaden → kein doppelter Geocode-Eintrag                    | PASS with note — relies on the same scanner-level dedup (`alice:dms:queued_files`/`processed_files`) that already covers "no duplicate AI analysis" in the original spec; the extractor itself does not check Weaviate before queueing a geocode entry, so a theoretical race window (both paths in-flight simultaneously before either completes) could double-queue — this is the same accepted race class as the pre-existing AI-dedup behavior, not a new risk introduced by this refinement |

### Security Audit

| Check                                                        | Result                                                    |
| --------------------------------------------------------------- | ------------------------------------------------------------ |
| `GEOAPIFY_API_KEY` never hardcoded                              | PASS — only in `.env`/`.env.example`/`$env`, dummy value in example |
| Weaviate PATCH scoped to exactly `country`/`country_code`/`city`/`district` | PASS — no other properties can be injected from the Geoapify response |
| `file_hash` GraphQL escaping                                    | PASS — identical `safeHash` pattern to the already-audited `img-05-process` node |
| Geoapify request params (`lat`/`lon`/`apiKey`)                  | PASS — passed via axios `params` (URL-encoded), not string-interpolated into the URL; `lat`/`lon` are EXIF-derived floats, not user strings |
| No secrets in logs                                              | PASS — only `e.message` is logged on error, never the API key or full request config |

### Bugs Found

**BUG-2 (Medium, found post-Approval on 2026-07-22, fixed same day): Geoapify 5 req/s rate limit not enforced**
- **Root cause:** The initial implementation relied only on the geocode phase's strict sequential processing (one item in flight at a time via `Split In Batches`) to stay under Geoapify's rate limit, but added no explicit minimum delay between calls. If the surrounding Redis/Weaviate round-trips complete faster than ~200ms (plausible on a local/LAN setup), consecutive Geoapify calls could exceed 5 requests/second and get 429-rate-limited.
- **Fix:** Added a flat `await new Promise((resolve) => setTimeout(resolve, 220))` in `geo-05-process` immediately after each completed Geoapify call (both match and no-match outcomes), guaranteeing ≥220ms spacing. Re-validated: JSON structure/connectivity intact, JS syntax valid.
- **Missed in the original QA pass** because that pass checked the daily quota and the "not found" retry path but did not cross-check Geoapify's separate per-second rate limit — flagged by the user afterwards.

None further (Critical/High). One accepted-risk note carried over from the pre-existing dedup design (see edge case table above) — same class as an already-accepted behavior, not a regression.

### Production-Ready Decision

**APPROVED** — No Critical or High bugs. BUG-2 (Medium) fixed before deployment.

## Deployment (Refinement 2026-07-23)

- **Date:** 2026-07-23
- Deployed by user directly on `ki.lan`:
  1. `dms-extractor-image` container rebuilt and restarted (Nominatim call removed, `alice:dms:geocode_pending` RPUSH active)
  2. `n8n` container updated with `GEOAPIFY_API_KEY` / `GEOAPIFY_DAILY_LIMIT` and recreated
  3. `alice-dms-processor` n8n workflow updated/imported with the new geocode sub-flow (incl. BUG-2 rate-limit fix)
- **Not confirmed as done:** teardown of the old, already-stopped Nominatim container/volume on the server (`/srv/warm/nominatim`, ~60 GB) — optional cleanup, left to the user's discretion, not required for this feature to function.
