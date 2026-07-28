# PROJ-56: DMS Bildanalyse

## Status: Deployed
**Created:** 2026-06-29
**Last Updated:** 2026-07-28

> **Hinweis:** Ursprünglich am 2026-07-03 vollständig deployed (siehe historische Sektionen unten: Tech Design, Implementation Notes, QA Test Results, Deployment). Am 2026-07-21 wurde das Geocoding-Subsystem grundlegend überarbeitet (Nominatim → externer Anbieter, siehe Abschnitt "Refinement Notes" am Ende des Dokuments) — die historischen Sektionen beschreiben den **veralteten** Nominatim-Ansatz und dienen nur noch als Referenz. Status auf "Planned" zurückgesetzt, da das Geocoding-Subsystem eine neue Architektur benötigte (`/architecture` als nächster Schritt). Alle anderen Komponenten (Scanner, EXIF-Extraktion, KI-Bildbeschreibung, Weaviate-Collection, Thumbnails) bleiben unverändert und sind weiterhin gültig — im Weaviate-Schema existierten laut Nutzer noch keine Bilddaten (Schema war nie vollständig deployed), ein Backfill bestehender Objekte ist daher nicht nötig.
>
> **Update 2026-07-26:** Nach Produktiveinsatz wurden zwei Probleme gemeldet: (1) ein Backlog-/Nebenläufigkeits-Problem im Scanner/Processor (betrifft alle Dateitypen, nicht nur Bilder) — als eigenständiges Feature **PROJ-72** ausgegliedert; (2) ein reproduzierbarer Absturz im Geocode-Sub-Flow (`Code: Process Geocode Item`) — siehe "Refinement Notes (2026-07-26)" und "Tech Design Update — 2026-07-26" unten. Status auf "Architected" gesetzt, da der Fix-Ansatz für Problem 2 entschieden ist; nächster Schritt `/backend`.
>
> **Update 2026-07-28 (QA):** Der Geocode-Node-Split wurde vom Nutzer live auf `ki.lan` deployed (Workflow `alice-dms-processor`, n8n-Workflow-ID `qPIg6uLTe8LfOYwv`). QA erfolgte per statischem Code-Review **und** per Live-Produktions-Ausführungsdaten aus n8n (siehe "QA Test Results (Refinement 2026-07-26/28)" unten) — der `InternalTaskRunnerDisconnectAnalyzer`-Absturz ist in einem echten nächtlichen Lauf reproduziert und in einem Lauf nach dem Fix nachweislich behoben. Ein neuer, vom Fix unabhängiger Befund (systematische 2×-Duplizierung in `alice:dms:geocode_pending`, vermutlich derselbe Nebenläufigkeits-Ursprung wie PROJ-72) wurde dokumentiert. Status auf "Approved" gesetzt — kein Critical/High-Bug offen.
>
> **Update 2026-07-28 (Deploy):** Deploy war zu diesem Zeitpunkt bereits erfolgt (siehe QA-Abschnitt oben — die Live-Executions liefen bereits gegen den produktiven Workflow). Dieser Schritt umfasste daher nur noch Doku-Nacharbeit (Spec + INDEX.md) sowie Commit/Push. Siehe "Deployment (Refinement 2026-07-28)" am Ende des Dokuments. Status auf "Deployed" gesetzt.

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

---

## Refinement Notes (2026-07-26)

**Trigger:** Path 2 — Implementation Revealed Gaps (`/refine`), nach Produktiveinsatz gemeldet vom Nutzer.

**Gemeldete Probleme:**

1. **Backlog/Nebenläufigkeit:** Bei der Erstaufnahme einer neuen Freigabe (z.B. `pictures`, ~70.000 Bilder/Videos) dauert die Abarbeitung allein durch den 5s-Stabilitätscheck pro Datei mehrere Tage. `alice-dms-scanner` läuft aber stündlich (07–22 Uhr) weiter und startet neue Ausführungen, während die vorherige noch läuft — Dateien können dadurch mehrfach verarbeitet werden (Race Condition vor dem Eintrag in `alice:dms:queued_files`), und weil `Code: Scan All Folders` alle aktivierten `dms_watched_folders`-Einträge in eine einzige kombinierte Liste zusammenfasst, blockiert ein großer Backlog in einem Pfad faktisch auch neue Dateien in anderen, unabhängigen DMS-Pfad-Einträgen.
2. **`Code: Process Geocode Item` Absturz:** Der Node wirft reproduzierbar (auch bei kleinen, normalen nächtlichen Läufen, nicht nur unter Backlog-Last) einen `InternalTaskRunnerDisconnectAnalyzer`-Fehler bereits beim ersten übergebenen Datensatz.

**Untersuchung:**
- Problem 1 betrifft den generischen Scanner/Processor-Mechanismus, nicht nur Bilder — ein PDF-Backlog gleicher Größenordnung hätte dasselbe Problem. Kein Bild-/Geocoding-spezifischer Code beteiligt.
- Problem 2 wurde per statischem Codevergleich untersucht: `Code: Process Geocode Item` hat exakt dieselbe Struktur (unguarded `await client.connect()`, redis+axios-Kombination) wie der bereits produktiv funktionierende `Code: Process Image Item` — der Crash ist also kein offensichtlicher Logikfehler in diesem Node selbst. Der einzige strukturelle Unterschied: `Process Geocode Item` ist der einzige Node im Workflow, der aus dem Code-Node/Task-Runner-Sandbox heraus einen rohen `axios`-Call an einen **externen** Host (`api.geoapify.com`) absetzt — alle anderen axios-Aufrufe im Workflow gehen an interne Services (`weaviate`, `ollama`). Das deckt sich mit der generischen n8n-Fehlermeldung, die auf den Task-Runner-Prozess selbst hindeutet, nicht auf einen JS-Fehler im Code. Root Cause nicht 100% verifiziert (keine Live-Logs verfügbar), aber die Auslagerung des externen HTTP-Calls aus der Sandbox ist die naheliegende Behebung unabhängig von der genauen Ursache.

**Getroffene Entscheidungen:**
1. **Scope-Split:** Problem 1 (Backlog-Locking/Nebenläufigkeit) wird als eigenständiges Feature **PROJ-72** ausgegliedert, da es den Scanner/Processor generisch betrifft (alle Dateitypen) und nicht spezifisch zur Bildanalyse gehört (Single-Responsibility-Regel). PROJ-56 bleibt auf die geocode-spezifische Behebung (Problem 2) beschränkt. Nächster Schritt für PROJ-72: `/write-spec PROJ-72`.
2. **Geocode-Fix:** `Code: Process Geocode Item` wird in drei Nodes aufgeteilt — `geo-05a Prepare Request` (Redis-Connect + Quota-Check + Weaviate-Lookup, alles intern/unproblematisch), ein natives `HTTP Request`-Node `geo-05b Call Geoapify` (Aufruf außerhalb der JS-Sandbox) und `geo-05c Process Response` (Quota-Increment, Rate-Limit-Delay, Weaviate-PATCH, Redis-Dequeue). Details siehe "Tech Design Update" unten.
3. **Konsistenzfix:** `await client.connect()` wird in allen Code-Nodes, die dieses Muster verwenden (mindestens `geo-05a`, `Code: Process Image Item`), in ein `try/catch` gefasst — aktuell würde ein Redis-Verbindungsfehler unabgefangen durchschlagen. Kein bestätigter Bug bislang (nur latentes Risiko), wird aber im selben Zuge korrigiert.

**Betroffene Abschnitte:** Status-Header, Tech Design Update (neue Sektion unten ersetzt den `geo-05-process`-Teil aus der Sektion vom 2026-07-21), Dependencies (kein Hard-Dependency zu PROJ-72, aber Hinweis ergänzt).

**Nicht betroffen:** Scanner-Erweiterung, EXIF-Extraktion, KI-Bildbeschreibung, Weaviate-Schema, Thumbnail-Generierung, Quota-/Retry-Semantik des Geocode-Sub-Flows (bleibt fachlich identisch, nur die Node-Aufteilung ändert sich).

**Nächster Schritt:** `/backend` — Umsetzung der Node-Aufteilung in `workflows/alice-dms-processor.json` gemäß Tech Design Update unten.

---

## Tech Design Update (Solution Architect) — 2026-07-26: Geocode Node Robustness Fix

Ersetzt nur den `geo-05-process`-Node-Teil des Geocode-Sub-Flows (siehe Tech Design Update 2026-07-21) — Fetch/Quota-Empty/Continue-Loop-Nodes (`geo-01` bis `geo-04`, `geo-06`) bleiben unverändert.

### Node-Aufteilung

**Vorher:** ein monolithischer Code-Node `geo-05-process` (Redis-Connect, Quota-Check, Weaviate-Lookup, Geoapify-Call, Rate-Limit-Delay, Weaviate-PATCH, Redis-Dequeue — alles in einem Node).

**Nachher:** drei Nodes in Reihe, verdrahtet zwischen `Split: Geocode Batches` und `IF: Geocode Continue Loop`:

1. **`geo-05a Prepare Request`** (Code)
   - `await client.connect()` jetzt in `try/catch` — bei Verbindungsfehler: Item mit `_geo_action: 'redis_error'` zurückgeben, Phase nicht abbrechen (analog zu anderen Redis-Fehlerpfaden)
   - Fehlt `file_hash`/`latitude`/`longitude`: dequeue, `_geo_action: 'skip'`
   - Tageslimit-Check (`alice:dms:geocode_quota:<YYYY-MM-DD>` vs. `GEOAPIFY_DAILY_LIMIT`): erreicht → `_geo_action: 'quota_reached'`, kein Dequeue
   - Weaviate-Lookup per `file_hash` (interner axios-Call, unverändert unproblematisch): nicht gefunden → `_geo_action: 'not_found_yet'`, kein Dequeue
   - Gefunden → gibt `existingId`, `lat`, `lon`, `apiKey` als Felder für den nächsten Node weiter, `_geo_action` bleibt vorerst unbesetzt (wird von `geo-05c` gesetzt)
2. **`IF: geo-05a Should Call Geoapify`** (neuer IF-Node) — routet nur Items ohne bereits gesetztes `_geo_action` (also: gefunden, unter Quota, valide Koordinaten) zum HTTP-Call; alle anderen springen direkt zu `IF: Geocode Continue Loop`
3. **`geo-05b Call Geoapify`** (HTTP Request-Node, nativ)
   - `GET https://api.geoapify.com/v1/geocode/reverse`, Query-Parameter `lat`, `lon`, `format=json`, `apiKey` (aus `$json`, von `geo-05a` durchgereicht)
   - Timeout 10000ms, "Continue On Fail" aktiviert (damit Netzwerkfehler nicht die gesamte Phase abbrechen, sondern als Fehler-Item an `geo-05c` weitergereicht werden)
4. **`geo-05c Process Response`** (Code)
   - Erkennt HTTP-Fehler (aus "Continue On Fail"-Output) → `_geo_action: 'unreachable'`, kein Quota-Increment, kein Dequeue (identisch zum bisherigen Verhalten)
   - Bei Erfolg: Quota-Zähler inkrementieren, danach fixe 220ms-Pause (Geoapify 5 req/s-Limit — unverändert aus Tech Decision 2026-07-21)
   - Kein Ergebnis im Response-Body → dequeue, `_geo_action: 'done_no_match'`
   - Ergebnis vorhanden → Weaviate-PATCH (`country`, `country_code`, `city`, `district`, interner axios-Call), danach dequeue, `_geo_action: 'done'`

### Data Flow

```
Split: Geocode Batches
     ↓
geo-05a Prepare Request        ← Redis (try/catch) + Quota-Check + Weaviate-Lookup (intern)
     ↓
IF: Should Call Geoapify ──(nein: skip/quota_reached/not_found_yet/redis_error)──→ IF: Geocode Continue Loop
     ↓ (ja)
geo-05b Call Geoapify           ← natives HTTP-Request-Node, AUSSERHALB der Code-Node-Sandbox
     ↓
geo-05c Process Response        ← Quota-Increment, 220ms-Delay, Weaviate-PATCH (intern), Dequeue
     ↓
IF: Geocode Continue Loop
```

### Tech Decisions

| Entscheidung | Wahl | Begründung |
| --- | --- | --- |
| Geoapify-Aufruf-Ort | Natives `HTTP Request`-Node statt `axios` im Code-Node | Einziger Node im gesamten Workflow, der einen rohen HTTP-Call an einen externen Host aus der Code-Node/Task-Runner-Sandbox absetzt; wahrscheinlichster Auslöser des `InternalTaskRunnerDisconnectAnalyzer`-Absturzes. Native Nodes laufen außerhalb der JS-Sandbox und sind für Netzwerk-I/O vorgesehen. |
| Node-Granularität | 3 Nodes (`05a`/`05b`/`05c`) statt 1 | HTTP Request-Node kann keine Redis-/Weaviate-Logik enthalten; Aufteilung ist die direkte Konsequenz aus der vorherigen Entscheidung |
| `client.connect()`-Fix | try/catch ergänzen, in `geo-05a` und `Code: Process Image Item` | Identisches Muster in beiden Nodes; latentes Risiko unabhängig vom eigentlichen Bug, im selben Zug behoben statt separatem Ticket |
| Fachliche Semantik | Unverändert (Quota, Retry, "not found yet", Rate-Limit) | Reine Robustheits-/Infrastruktur-Änderung, keine Verhaltensänderung aus Nutzersicht |

### Dependencies

Keine neuen Packages. Der `HTTP Request`-Node ist ein n8n-Standard-Nodetyp, bereits an anderer Stelle im Projekt im Einsatz.

### No UI Changes Required

Rein workflow-interne Änderung.

---

## Implementation Notes (Refinement 2026-07-26, built 2026-07-28)

Implemented the Node-Aufteilung from "Tech Design Update — 2026-07-26: Geocode Node Robustness Fix" exactly as specified.

**Files modified:**
- `workflows/alice-dms-processor.json`:
  - Removed the monolithic `geo-05-process` ("Code: Process Geocode Item") node.
  - Added `geo-05a-prepare` ("Code: Prepare Geocode Request", Code node) — `client.connect()` now wrapped in try/catch (`_geo_action: 'redis_error'` on failure, phase continues); does the skip/quota/Weaviate-lookup checks exactly as before, but returns `{ existingId, lat, lon, quotaKey }` instead of calling Geoapify itself.
  - Added `geo-05a-if-call` ("IF: Should Call Geoapify") — routes items with no `_geo_action` set (i.e. found, under quota, valid coords) to the HTTP call; everything else (`skip`/`quota_reached`/`not_found_yet`/`redis_error`/`error`) goes straight to `IF: Geocode Continue Loop`. Condition uses the `notExists` string operator on `_geo_action`.
  - Added `geo-05b-call` ("HTTP: Call Geoapify", native `httpRequest` node, `continueOnFail: true`) — `GET https://api.geoapify.com/v1/geocode/reverse` with `lat`/`lon`/`format=json` from the previous item and `apiKey` read directly via `{{ $env.GEOAPIFY_API_KEY }}` (not passed through item data, to avoid the key showing up in execution data). This is the node that moves the external call out of the Code-node/Task-Runner sandbox per the architecture decision.
  - Added `geo-05c-process` ("Code: Process Geocode Response") — reads the HTTP response from `$input`, re-fetches the original item (`existingId`, `quotaKey`, `file_hash`, `_raw_json`, etc.) via `$('Code: Prepare Geocode Request').first().json` (same established pattern already used elsewhere in this workflow, e.g. `Code: Handle Extract Error` / `Code: Parse Extract Result`, since HTTP Request nodes replace `$json` with the response body). Detects `httpResp.error` → `_geo_action: 'unreachable'`; otherwise increments the quota counter, waits the same flat 220ms (BUG-2 rate-limit fix, unchanged), reads `body.results[0]` (defensive `body = httpResp.body ?? httpResp` in case "Include Response" wrapping differs), and PATCHes Weaviate / dequeues exactly as the old node did. `client.connect()` here is also wrapped in try/catch (`_geo_action: 'redis_error'`).
  - `geo-06-continue` ("IF: Geocode Continue Loop") — unchanged logic, only its canvas position shifted right to make room.
  - `img-05-process` ("Code: Process Image Item") — consistency fix from Tech Decision #3: `client.connect()` wrapped in try/catch, returns `_image_action: 'redis_error'` (falls into the existing non-`'new'` branch of `IF: Image Is New`, so it's retried next run) instead of throwing unguarded.
  - Updated the `geo-sticky-note` sticky text to document the 2026-07-26 node split.

**Design deviations from architecture doc:** None. `apiKey` is read via `$env` directly inside `geo-05b`'s query parameter expression rather than being passed through `geo-05a`'s output — this wasn't specified either way in the tech design, and avoids putting the secret into item data that n8n stores per-node in execution history (same class of concern as the existing "no secret in workflow JSON" rule, just extended to execution data).

**Validation performed (no live n8n server available):**
- `node --check` on all three modified/added Code-node bodies (`geo-05a-prepare`, `geo-05c-process`, `img-05-process`) — all pass.
- Verified programmatically that the old node id/name (`geo-05-process` / "Code: Process Geocode Item") no longer exists and is no longer referenced anywhere in `connections`; no duplicate node ids/names; every connection source and target resolves to an existing node.
- `mcp__n8n-mcp__validate_workflow_connections` and `mcp__n8n-mcp__validate_workflow_expressions` run against the geocode sub-flow + the two `img-05`/`img-06` neighbor nodes: both report `valid: true`, zero errors. The three "missing onError: continueErrorOutput" warnings on the IF-type nodes are the same generic warning already present on the pre-existing, untouched `IF: Geocode Continue Loop` node — not something introduced by this change.

**Update 2026-07-28:** User deployed the updated workflow to `ki.lan` and ran it manually against the real backlog. See "QA Test Results (Refinement 2026-07-26/28)" below for the live execution evidence — the `InternalTaskRunnerDisconnectAnalyzer` crash is confirmed fixed.

**Next step:** `/deploy` — no further code changes required for this refinement; see QA verdict below.

---

## QA Test Results (Refinement 2026-07-26/28)

**Date:** 2026-07-28 | **Method:** Static code review + JS syntax check + **live production execution analysis** (n8n workflow `alice-dms-processor`, id `qPIg6uLTe8LfOYwv`, deployed by user on `ki.lan`, queried via n8n-mcp — a significant upgrade over the previous "no live server available" QA passes for this feature).

### Root-Cause Confirmation (Pre-Fix)

Live executions confirm the reported crash is real and reproducible, and is isolated to the geocode sub-flow (the image sub-flow completes cleanly in the same runs):

| Execution | Trigger | Started | Result |
| --- | --- | --- | --- |
| `49841` | Nightly 02:00 | 2026-07-25 | Image phase: 3690 items processed successfully. Geocode phase: crashes on the **first** geocode item at `Code: Process Geocode Item` with `InternalTaskRunnerDisconnectAnalyzer` / "Node execution failed". |
| `59108` | Nightly 02:00 | 2026-07-28 (before the 09:38 fix deploy) | Identical crash, same node, same stack trace, again on the first item. |

Both stack traces are identical (`InternalTaskRunnerDisconnectAnalyzer.toDisconnectError` → `TaskBrokerWsServer.removeConnection`), confirming this is the Task-Runner-sandbox disconnect described in the 2026-07-26 Tech Design Update, not an intermittent fluke.

### Post-Fix Confirmation

| Execution | Trigger | Started | Result |
| --- | --- | --- | --- |
| `59708` | Manual | 2026-07-28, 09:51 (13 min after the 09:38 workflow update) | **Success.** All 18 executed nodes green. `Code: Fetch Geocode Items` → 1680 pending entries → all 1680 flow through `Code: Prepare Geocode Request` → `IF: Should Call Geoapify` → `HTTP: Call Geoapify` → `Code: Process Geocode Response` → `IF: Geocode Continue Loop` → `End: Geocode Done`, zero node errors, run completes in ~19.4 minutes. |

Sample `HTTP: Call Geoapify` output item contains a real Geoapify response body (`country`, `city`, `district`, `suburb`, etc.) — confirms the native HTTP node correctly reaches `api.geoapify.com` and receives valid geocoding results outside the Code-node sandbox. Sample `Code: Process Geocode Response` output shows `_geo_action: "done"` with `existingId` populated — confirms the PATCH path executes.

**Verdict: the `InternalTaskRunnerDisconnectAnalyzer` crash is fixed.** The architecture decision (move the external HTTP call out of the Code-node sandbox into a native `HTTP Request` node) is validated by production data, not just static review.

### Acceptance Criteria — Tech Design Update 2026-07-26 (Geocode Node Robustness Fix)

| Criterion | Result |
| --- | --- |
| Monolithic `geo-05-process` replaced by `geo-05a`/`geo-05b`/`geo-05c` | PASS — confirmed in workflow JSON and live execution node list |
| External Geoapify call moved to native `HTTP Request` node (`geo-05b`), outside Code-node sandbox | PASS — confirmed live: `HTTP: Call Geoapify` executes as its own node with real response data |
| `IF: Should Call Geoapify` correctly routes only found/under-quota/valid-coord items to the HTTP call, all other outcomes (`skip`/`quota_reached`/`not_found_yet`/`redis_error`) straight to the loop-continue check | PASS — condition uses `notExists` on `_geo_action`; static trace confirms every non-passthrough branch in `geo-05a` sets `_geo_action` |
| `geo-05c` re-fetches the original item via `$('Code: Prepare Geocode Request').first().json` (HTTP node replaces `$json` with the response body) | PASS — same established pattern as `Code: Handle Extract Error` elsewhere in this workflow; live execution shows `existingId`/`quotaKey` correctly carried through |
| Quota increment, 220ms rate-limit delay (BUG-2, 2026-07-21), Weaviate PATCH, dequeue — semantics unchanged | PASS — code identical to the pre-split version, only relocated into `geo-05c` |
| `await client.connect()` wrapped in try/catch in `geo-05a`, `geo-05c`, and `img-05-process` (`Code: Process Image Item`) | PASS — all three now return a `redis_error`/`_image_action: 'redis_error'` item instead of throwing; item stays queued (no `lRem` on that path), phase continues to the next item |
| `redis_error` on the image side falls into the existing "not new" branch of `IF: Image Is New`, so it's retried next run | PASS — `IF: Image Is New` checks `_image_action === 'new'` (strict equals); `'redis_error'` fails this and takes the same non-insert branch as `'error'`/`'add_path'` |
| No functional/semantic change to quota, retry, "not found yet", or rate-limit behavior | PASS — confirmed both by diff (identical logic, only moved) and by live execution (`_geo_action: 'done'` items PATCH and dequeue as before) |

**Result: 8/8 PASS**

### Regression Check

- Image sub-flow (unrelated to this refinement) ran cleanly in all three inspected executions (3690 / 3690 items in `49841`, no errors) — confirms the `img-05-process` try/catch consistency fix didn't disturb the existing insert/dedup path.
- `geo-06-continue` ("IF: Geocode Continue Loop") logic is byte-for-byte unchanged (only its canvas position shifted) — confirmed via direct node inspection.

### New Finding (independent of this refinement)

**BUG-3 (Medium): `alice:dms:geocode_pending` contains systematic duplicate entries — every observed `file_hash` appears exactly twice**

- **Evidence:** In both the pre-fix run (`49841`, 2026-07-25) and the post-fix run (`59708`, 2026-07-28), sampling `Code: Fetch Geocode Items`' output shows every `file_hash`/`latitude`/`longitude` triple appearing **exactly twice, back-to-back** (checked 10 distinct hashes × 2 = 20 consecutive items in `59708`; same pattern in `49841`). This is a consistent 2× duplication, not an occasional race — of the 1680 entries processed in `59708`, this implies only ~840 distinct images.
- **Root cause (not 100% confirmed, no extractor logs available in this environment):** Most likely the same backlog/concurrency issue already scoped out as **PROJ-72** — `dms-extractor-image` appears to process some files twice during large-backlog catch-up (matching PROJ-72's description: concurrent scanner runs re-detecting files before they land in `alice:dms:queued_files`), and each processing run independently `RPUSH`es to `alice:dms:geocode_pending` with no pre-check against Weaviate. This is the exact "theoretical race window" the 2026-07-21 QA pass flagged as an accepted risk ("the extractor itself does not check Weaviate before queueing a geocode entry") — except it is not theoretical, it is happening on effectively 100% of GPS-tagged entries during the current backlog.
- **Impact:** No data corruption — the second Geoapify call and Weaviate PATCH for the same `file_hash` are idempotent (same coordinates → same result → same fields overwritten with the same values). The impact is **2× wasted Geoapify quota/requests** per real photo during backlog processing. At `GEOAPIFY_DAILY_LIMIT=3000` this halves effective nightly throughput — not a problem for `59708`'s 1680 entries (840 real, well under quota), but will roughly double the number of nights needed to clear the full 70k-image backlog's geo-tagged subset once the PROJ-72 backlog itself unblocks image scanning.
- **Not a regression from this refinement** — the same duplication pattern is present in `49841` (2026-07-25, before the geo-05 split existed). Not fixed by, and not caused by, the `geo-05a`/`b`/`c` split.
- **Recommendation:** Track alongside PROJ-72 (most likely shares the same root cause and will disappear once the scanner/processor backlog-locking fix ships). If it persists after PROJ-72, consider a cheap independent guard in `geo-05a`: skip the Geoapify call if the Weaviate object's `country`/`city` fields are already non-empty (would also protect against any other duplicate-queuing source).

### Security Audit

| Check | Result |
| --- | --- |
| `GEOAPIFY_API_KEY` in `geo-05b`'s query parameter, not in item data | PASS — read via `{{ $env.GEOAPIFY_API_KEY }}` directly in the node parameter; confirmed via live execution data that the node's stored output (`HTTP: Call Geoapify`) contains only the Geoapify response body, no echoed request/key |
| Weaviate PATCH still scoped to exactly `country`/`country_code`/`city`/`district` | PASS — unchanged in `geo-05c` |
| No secrets in logs | PASS — `console.log` calls only emit `e.message` / generic status strings, never key or full request config |
| New native `HTTP Request` node (`geo-05b`) — SSRF / URL injection | PASS — URL is a hardcoded literal (`https://api.geoapify.com/v1/geocode/reverse`); only `lat`/`lon` (EXIF-derived floats) and the fixed `apiKey`/`format` are parameterized, no user- or file-controlled string reaches the URL itself |

### Production-Ready Decision

**READY** — No Critical or High bugs. The reported crash is fixed and independently confirmed via live production execution data (not just static review). BUG-3 (Medium, duplicate geocode queue entries) is pre-existing, not introduced by this change, does not corrupt data, and is already tracked under the same root cause as PROJ-72.

---

## Deployment (Refinement 2026-07-28)

- **Date:** 2026-07-28
- **Production:** `ki.lan`, n8n workflow `alice-dms-processor` (workflow id `qPIg6uLTe8LfOYwv`)
- Deployed by user directly on `ki.lan`: `alice-dms-processor` re-imported with the geocode node split (`geo-05a`/`geo-05b`/`geo-05c` replacing the monolithic `geo-05-process`, plus the `img-05-process`/`geo-05a`/`geo-05c` `client.connect()` try/catch consistency fix)
- Deploy preceded this bookkeeping step — QA (see above) was performed directly against the already-live workflow via n8n-mcp execution data (executions `59680`, `59708` post-deploy; `49841`, `59108` pre-deploy for root-cause confirmation)
- No frontend, database migration, or nginx changes involved — this refinement is scoped entirely to `workflows/alice-dms-processor.json`
- **Open follow-up (not blocking):** BUG-3 (duplicate `alice:dms:geocode_pending` entries) — tracked alongside PROJ-72, no action taken as part of this deploy
