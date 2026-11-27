# Architektur: PROJ-125 Bilder in der Quelle der Wahrheit (#21)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-27

## A) Betroffene Bausteine
```
alice-image-processing (neuer Container, Python/FastAPI, Port 8020, nur Docker-Netz, keine nginx-Route)
+-- Schleife „Beschreibung“ (Stufe `extract`, nur kind = image, höchstens N Bilder gleichzeitig, Standard 1)
|   +-- Reihenfolge je Runde: gezielt angestoßene Bilder → neue Bilder → Bestand (nur wenn freigegeben)
|   +-- EXIF aus dem Original (Pillow + pillow-heif: jpg/jpeg/png/webp/heic/tif/tiff)
|   +-- Bild verkleinern bzw. in ≤ 8 Teilbilder zerlegen (Logik aus PROJ-112), richtig gedreht
|   +-- Vision-Aufruf(e) über alice-llm-gateway (eigener Hintergrund-Schlüssel, enable_thinking=false)
|   +-- schreibt EXIF-Felder, description_model, language, Titel und Inhaltsteil über das Register
+-- Schleife „Ort“ (neue Stufe `locate`, nur kind = image, eins nach dem anderen)
|   +-- GPS aus dem Original; ohne GPS → Stufe `skipped`
|   +-- altes Weaviate `Image` per file_hash (nur lesend, abschaltbar) → sonst Geoapify (lang=de)
|   +-- Tageslimit (Zähler in PostgreSQL, Tag = Europe/Berlin) und ≤ 5 Aufrufe/s
|   +-- schreibt `location` und ergänzt den Titel um den Ort
+-- POST /describe/{source_id}: einzelnes Bild gezielt zur Beschreibung anstoßen (auch Bestand)
+-- GET /health, GET /status

alice-source-registry (PROJ-115, kleine, abwärtskompatible Erweiterungen)
+-- claim: optionale Filter `registered_since`, `registered_before` (Registrierungszeit) und `source_ids`
+-- done: optional `skipped: true` → Zustand `skipped` (Ort ohne GPS)
+-- Original in-place geändert (_reset_after): auch `skipped`-Stufen laufen neu, sofern die Art der
    Quelle nicht grundsätzlich übersprungen wird (Bild bekommt nachträglich GPS)

PostgreSQL (Migration 2026-11-27_PROJ-125_images.sql, Abschnitt 22 in init-schema.sql)
+-- Stufen `classify`, `database`: `image` in skip_kinds, vorhandene Bild-Stufen → skipped (AK-5)
+-- neue Stufe `locate` (Position 25, für alle Arten außer image übersprungen)
+-- alice.image_processing_state: Zeitpunkt des ersten Starts (Grenze Bestand/neu)
+-- alice.image_geocode_usage: Geoapify-Aufrufe je Tag
+-- alice.image_describe_requests: gezielt angestoßene Bilder (überstehen Neustarts)

Weaviate: nur lesend (alte Collection `Image`). Redis, MQTT, nginx, Frontend, n8n: keine Änderung.
dms-extractor-image, alice-dms-processor (Geocoding), Backfills: unverändert.
```

**Ein neuer Dienst** statt Erweiterung von `alice-text-extraction` oder `alice-document-classify`: Bilder brauchen andere Bibliotheken (Pillow/HEIF) und das Gateway, Dokumente brauchen LibreOffice/Tesseract. Eine gemeinsame Schleife würde die Parallelität (Text 2, Bilder 1) und die Abhängigkeiten vermischen. Der alte `dms-extractor-image` bleibt unberührt (Spec); seine Beschreibungslogik (Teilbilder, alles oder nichts, Pixelgrenze) wird in den neuen Dienst übernommen.

## B) Datenmodell

### Register-Stufen für Bilder
| Stufe | Bedeutung bei Bildern | Wer |
|---|---|---|
| `detect` | registriert (PROJ-116 / PROJ-124) | bestehend |
| `extract` | **Beschreibung** inkl. EXIF und Titel | alice-image-processing |
| `locate` (neu, Position 25) | **Ort** | alice-image-processing |
| `classify`, `database` | `skipped` (AK-5) | – |
| `rag`, `wiki`, `thumbnail` | unverändert (PROJ-127/129/126) | – |

- `extract` wird für Bilder wiederverwendet: Die Stufe stand bei allen Bildern schon auf `pending`, und keiner holt sie bisher ab (`alice-text-extraction` holt nur `document`). Eine eigene Stufe würde nur eine zweite, ewig offene Zeile pro Bild erzeugen.
- `locate` steht nach `extract`: Ein Neuaufbau ab `extract` (PROJ-120) beschreibt **und** verortet neu. Die Reihenfolge „Ort möglichst vor der Beschreibung“ ergibt sich nicht aus der Position, sondern daraus, dass der Ort schnell geht und unabhängig läuft. Die Beschreibung wartet nie auf ihn (kein `requires`).
- `locate` hat weder `resets_on_content_change` noch `resets_on_fields`: Eine Handkorrektur ändert nichts am GPS.

### Frontmatter (über das Register geschrieben)
| Feld | Schreibt | Inhalt |
|---|---|---|
| `taken` | extract | `YYYY-MM-DDThh:mm:ss` aus `DateTimeOriginal` (sonst `DateTimeDigitized`/`DateTime`), mit Zeitzone, wenn `OffsetTimeOriginal` gesetzt ist; sonst `null` |
| `width`, `height` | extract | angezeigte Maße (nach EXIF-Drehung, EC-10) |
| `gps` | extract | `{latitude, longitude, altitude}` (Dezimalgrad mit Vorzeichen, Meter, unter Meereshöhe negativ) oder `null`; 0/0 oder außerhalb ±90/±180 gilt als kein GPS (EC-3) |
| `camera` | extract | `{make, model}` oder `null` |
| `description_model` | extract | Feld `model` der Gateway-Antwort, ersatzweise das konfigurierte Modell |
| `language` | extract | `de` |
| `title` | extract, locate | `<Zeitpunkt> <Kurztitel>[ – <Ort>]` |
| `location` | locate | `{country, country_code, city, district}` oder `null` (kein GPS) |

- Inhaltsteil (extract): Beschreibung, darunter bei lesbarem Text `## Text im Bild` mit der Abschrift in einem Code-Block (Zaun länger als jede Backtick-Folge der Abschrift, EC-8), darunter die Links aufs Original (wie bei PROJ-115).
- `manual` schützt alles wie bisher (Register): `title`, `location.city`, `content` usw.

### Neue Tabellen (nur alice-image-processing)
- `alice.image_processing_state (id = 1, first_start TIMESTAMPTZ)`: einmal beim ersten Start gesetzt. **Bestand** = Bilder mit `sources.created_at < first_start`, **neu** = danach registrierte.
- `alice.image_geocode_usage (day DATE PK, calls INT)`: Geoapify-Aufrufe je Kalendertag (Europe/Berlin). Ein Aufruf wird vorher atomar reserviert (`INSERT … ON CONFLICT DO UPDATE … WHERE calls < limit`). So kann auch ein Neustart das Limit nicht überschreiten.
- `alice.image_describe_requests (source_id PK, requested_at)`: angestoßene Einzelbilder. Ein Eintrag wird gelöscht, sobald das Bild übernommen ist.

## C) Abläufe

### Beschreibung (Stufe `extract`)
1. **Arbeit holen:** ist ein Platz frei (Standard 1, AK-34), in dieser Reihenfolge:
   1. angestoßene Bilder (`source_ids` aus `image_describe_requests`)
   2. neue Bilder (`registered_since = first_start`, AK-32)
   3. Bestand (`registered_before = first_start`), nur wenn `IMAGE_BACKLOG_RELEASED=true` (AK-31)

   Immer mit `kinds=["image"]`: Gelöschte Quellen und andere Arten bekommt der Dienst nicht (AK-4, AK-6).
2. **Original finden** wie PROJ-117: erster lesbarer Fundort. Freigabe fehlt → Arbeit ohne Fehlversuch zurück, neue Arbeit pausiert kurz (AK-38). Nur die Datei fehlt → zurück mit Wartezeit (1 h). Mail-Anhänge (AK-3) haben einen Fundort im Mail-Archiv auf dem NAS und laufen genauso.
3. **Markdown lesen** (`location` für den Hinweis, `modified`).
4. **Bild prüfen und vorbereiten** im Arbeits-Thread: öffnen (kaputt/nicht dekodierbar → sofort `failed_permanent`), Pixelzahl aus dem Kopf (über der Grenze → `failed_permanent` mit „Bild zu groß (… MP, Grenze 250 MP)“, AK-25), EXIF lesen, erstes Bild bzw. erste Seite (EC-9), verkleinern (JPEG-Draft), richtig drehen, Teilbilder schneiden.
5. **Vision:**
   - bis 2:1 / 1:2 → **ein** Aufruf (AK-18, AK-22)
   - darüber → je Teilbild ein Aufruf (Beschreibung + Text des Ausschnitts), dann **ein** reiner Text-Aufruf, der Beschreibung, Titel und Abschrift zusammenführt (AK-23)

   Jeder Aufruf geht an `/v1/chat/completions` mit dem Hintergrund-Schlüssel, `chat_template_kwargs.enable_thinking=false` und `response_format: json_object`. Die Antwort ist JSON `{"description", "title", "text_in_image"}`. Der Prompt verlangt Deutsch, etwa 800–1.500 Zeichen, Motiv/Personen (Anzahl, Tätigkeit, keine Identifizierung)/Umgebung/Architektur/Licht/Stimmung/Jahreszeit, einen Kurztitel aus wenigen Wörtern, die wörtliche Abschrift lesbaren Texts und **verbietet** Orts-, Gebäude- und Sehenswürdigkeitsnamen, die nicht durch Beschriftung im Bild oder den mitgegebenen Ort belegt sind. Ist `location` bekannt: „Aufnahmeort laut GPS: <Stadt>, <Land>“ als Hinweis (AK-19).
6. **Prüfen:** Beschreibung oder Titel leer bzw. kein JSON → unbrauchbar → Fehlversuch mit Backoff, nichts geschrieben (EC-7, AK-26). Ein gescheitertes Teilbild lässt die ganze Beschreibung scheitern (AK-24).
7. **Schreiben** (ein Aufruf mit Claim-Token): Felder aus B) plus Inhaltsteil. Der Titel enthält den Ort, falls `location` schon da ist. Danach wird die Markdown neu gelesen. Kam der Ort zwischenzeitlich, wird der Titel ergänzt (zweiter Schreibaufruf, nur wenn nötig). Dann `done`.
8. **Fehler:**
   - Gateway nicht erreichbar, Zeitüberschreitung, 429/5xx, leere oder unbrauchbare Antwort → `fail` mit Backoff (AK-26). Zusätzlich pausiert die Beschreibung kurz (Standard 60 s), damit ein Gateway-Ausfall nicht in Sekunden viele Bilder Fehlversuche kostet.
   - Register/Repo weg (503) oder Markdown gesperrt (409) → zurück ohne Fehlversuch.

### Ort (Stufe `locate`)
1. **Arbeit holen:** erst neue Bilder, dann Bestand, unabhängig von der Freigabe (AK-31). Eins nach dem anderen.
2. Original finden wie oben. Nur den EXIF-Kopf lesen. Kein GPS → `location: null` schreiben, Stufe `skipped` (AK-7).
3. **Übernahme** (Standard an, AK-13 aus): GraphQL `Get { Image(where: file_hash = <hex>) { country country_code city district } }`. Hash: `sha256:<hex>` des Registers ohne Präfix (das alte System speichert reines Hex). Das erste Objekt mit `country` oder `city` gewinnt (EC-5, EC-6) → kein Geoapify (AK-10). Weaviate nicht erreichbar bzw. Fehlerantwort → zurück ohne Fehlversuch mit kurzer Wartezeit (Standard 5 min), kein Geoapify (AK-12).
4. **Geoapify** (AK-11): Aufruf reservieren. Tageslimit erreicht → zurück ohne Fehlversuch mit Wartezeit bis zum nächsten Tag (00:00 Europe/Berlin, AK-14, EC-15). Danach höchstens 5 Aufrufe in einem gleitenden Fenster von 1 s (AK-15). `GET /v1/geocode/reverse?lat&lon&lang=de&format=json&apiKey`, Zuordnung wie im alten Prozess: `country`, `country_code` (groß), `city`, `district` = `suburb` ∨ `district` ∨ `quarter`. Kein Treffer bzw. fehlende Teile → Felder leer, Schritt erledigt (EC-4). HTTP-Fehler oder Zeitüberschreitung → `fail` mit Backoff (AK-16). Die Beschreibung wird dabei nicht angefasst.
5. **Schreiben:** `location` mit Claim-Token. Danach wird die Markdown neu gelesen. Ist das Bild schon beschrieben (`description_model` gesetzt) und `title` nicht in `manual`, wird der Ortszusatz gesetzt bzw. ersetzt (AK-29, AK-30). Dann `done`.

Weil beide Schritte **nach** ihrem eigenen Schreiben die aktuelle Markdown lesen, sieht der zweite immer das Ergebnis des ersten (das Register schreibt nacheinander): Der Titel bekommt den Ort in jeder Reihenfolge. Der Kurztitel enthält nie „ – “ (der Gedankenstrich wird zu „-“). So lässt sich der Ortszusatz eindeutig abtrennen.

### Titel
`<Zeitpunkt>` = `taken` als `YYYY-MM-DD hh.mm.ss` (Kamerazeit, wie gelesen, EC-2), ersatzweise `modified` des Originals in Europe/Berlin (AK-28). `<Ort>` = `city`, sonst `country`.

### Einzelbild anstoßen (AK-33)
`POST /describe/{source_id}`: Die Quelle muss `kind: image` und aktiv sein (sonst 404/409). Läuft ihre Beschreibung gerade → 409. Sonst setzt `retry` im Register die Stufe auf `pending` (Zähler 0), und die ID kommt in `image_describe_requests`. Die nächste Runde holt genau dieses Bild, auch bei gesperrtem Bestand. Aufruf nur im Docker-Netz, z. B. `docker exec alice-image-processing python -c …` oder `curl` aus einem Container im Netz `backend`.

### Register nicht erreichbar, Neustart
Wie PROJ-117/118: keine neue Arbeit, Warnung im Log, nach der Schonfrist (60 s) meldet `/health` „unhealthy“ mit Grund, danach geht es selbstständig weiter (AK-37). Postgres nicht erreichbar → ebenso. Hängende Arbeit setzt das Register nach seiner Zeitüberschreitung zurück, Lebenszeichen alle 60 s (EC-14).

## D) Technische Entscheidungen
- **Pillow + pillow-heif** (wie `dms-extractor-image`/Thumbnailer). EXIF über `Image.getexif()` inkl. `get_ifd(GPS/Exif)`, für alle Formate gleich (HEIC liefert EXIF über pillow-heif, EC-1). Kein piexif: ein Weg für alle Formate.
- **Pixelgrenze vor dem Dekodieren** (`Image.MAX_IMAGE_PIXELS=None`, eigene Prüfung aus dem Kopf). JPEG wird per `draft()` schon beim Dekodieren verkleinert. Tolerantes zweites Dekodieren bei „broken data stream“ (Samsung-Panoramen) wie PROJ-112.
- **Ein strukturierter Aufruf (JSON)** statt getrennter Aufrufe für Beschreibung, Titel und Text: Die Spec verlangt genau einen Aufruf je Bild.
- **Bestandsgrenze in eigener Tabelle** statt `pipeline_stage_served`: „served“ bedeutet „erste Übernahme“. Gibt es beim Start keine neuen Bilder, läge die Grenze später als die nächste Registrierung, und dieses Bild würde fälschlich zum Bestand.
- **Geoapify-Zähler in PostgreSQL** statt Redis: übersteht Neustarts von Dienst und Redis (EC-14), atomare Reservierung, kein Eingriff in alte Redis-Schlüssel (AK-40).
- **`done` mit `skipped`** statt `done`: Die Spec verlangt „Ort `skipped`“. Damit ein später ersetztes Original mit GPS wieder verortet wird, setzt `_reset_after` auch solche `skipped`-Stufen zurück (nur wenn die Art in der Stufe nicht grundsätzlich übersprungen wird).
- **Gateway-Ausfall = Fehlversuch** (Spec AK-26, anders als PROJ-118), dazu eine kurze Pause der Beschreibung, damit ein Ausfall nicht reihenweise Fehlversuche erzeugt.
- **Keine Sammel-Commits per Schalter:** Neuaufbau-Arbeit (PROJ-120) committet das Register automatisch gesammelt. `IMAGE_BATCH` (Standard aus) gibt es trotzdem für den Bestandsdurchlauf, analog zu PROJ-117/118.

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `httpx`, `asyncpg`, `Pillow`, `pillow-heif`; im Image `tini`.
- Neue Umgebungsvariablen (Platzhalter in `.env.example`): `REGISTRY_URL`, `POSTGRES_DSN`, `LLM_GATEWAY_URL`, `LLM_GATEWAY_KEY`, `IMAGE_VISION_MODEL`, `WEAVIATE_URL`, `GEOAPIFY_API_KEY`, `GEOAPIFY_URL`, `IMAGE_DESCRIBE_CONCURRENCY` (1), `IMAGE_BACKLOG_RELEASED` (false), `IMAGE_LOCATION_TAKEOVER` (true), `IMAGE_GEOAPIFY_DAILY_LIMIT` (3000), `IMAGE_GEOAPIFY_RATE` (5), `IMAGE_MAX_SIDE_PX` (1024), `IMAGE_MAX_MEGAPIXELS` (250), `IMAGE_LLM_TIMEOUT_SECONDS` (900), `IMAGE_LLM_RETRY_SECONDS` (60), `IMAGE_WEAVIATE_RETRY_SECONDS` (300), sowie Poll-/Heartbeat-/NAS-Werte wie PROJ-117.

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1, AK-2, AK-3, AK-21, AK-27 | Dienst gegen echten Register-Code (Test-DB, Temp-Git-Repo), Fake-Gateway, Fake-Geoapify, Test-Weaviate; erzeugte Testbilder in allen Formaten mit EXIF | E2E |
| AK-4, AK-6 | Register-Test: claim mit Art-Filter liefert keine Dokumente bzw. gelöschte Bilder | Integration |
| AK-5 | Migration auf Test-DB: neue Bilder `classify`/`database` = skipped | Integration |
| AK-7–9, EC-3, EC-9, EC-10 | EXIF-Leser mit erzeugten Bildern (S/W-Referenz, ohne EXIF, gedreht, mehrseitig) | Unit |
| AK-10–17 | Ort-Schleife mit Attrappen (Weaviate an/aus/abgeschaltet, Geoapify ok/Fehler/leer, Limit 3 bei 5 Bildern, Zeitmessung der Aufrufe) | Unit + E2E |
| AK-18–26 | Fake-Gateway zählt Aufrufe, prüft Bildgrößen, Prompt, Priorität (Schlüssel) und `enable_thinking`; Panorama 22704×1760 und hoch | Unit |
| AK-28–30, AK-35, AK-36 | Titel/manual/Inhalt `manual`/in-place geändertes Original über echtes Register | E2E |
| AK-31–34 | Reihenfolge, Sperre, Anstoßen, Parallelität mit Register-Attrappe und E2E | Unit + E2E |
| AK-37, AK-38 | Register/NAS weg (Attrappe, Temp-Ordner) | Unit |
| AK-39, AK-40 | keine nginx-Route, kein MQTT/Redis im Code, alter Container unverändert (git diff), Weaviate nur GET/GraphQL-Lesezugriff | Prüfung |
| AK-41–43 | nur live nach dem Deploy | Mensch |

Deploy-Schritte (Mensch):
1. Migration `sql/migrations/2026-11-27_PROJ-125_images.sql` anwenden.
2. `alice-source-registry` neu bauen (Schnittstellen-Erweiterungen).
3. Gateway-Schlüssel `image-processing background <key>` in `/srv/warm/llm-gateway/clients`, Gateway neu laden.
4. `.env` für `alice-image-processing` aus `.env.example` (lokal anlegen, wird mitsynchronisiert); Bestand bleibt gesperrt.
5. Sync, `make rebuild s=automations/alice-image-processing`.
6. Stichprobe (AK-41) über `POST /describe/<id>`, danach `IMAGE_BACKLOG_RELEASED=true` und neu starten.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Neuer Dienst `alice-image-processing` | Text-Extraktion oder Klassifizierung erweitern | andere Bibliotheken, andere Parallelität, alte Container unberührt |
| Beschreibung = Stufe `extract` | eigene Stufe `describe` | `extract` war für Bilder schon vorgesehen und offen, keine tote Stufe |
| Ort = neue Stufe `locate` (Position 25) | Position vor `extract` | Neuaufbau ab `extract` umfasst dann beides |
| Bestand über Registrierungszeit vor dem ersten Start | Liste der IDs beim Start | eine Zahl statt 52.000 IDs, neue Bilder ergeben sich von selbst |
| Tageslimit und Anstoß-Liste in PostgreSQL | Redis / Speicher | übersteht Neustarts, keine alten Redis-Schlüssel |
| Titel-Ort nach dem eigenen Schreiben neu prüfen | zusätzliches Feld für den Kurztitel | kein neues Frontmatter-Feld, korrekt in jeder Reihenfolge |

## Umsetzung (Bau, 2026-11-27)
- Gebaut wie oben beschrieben: Dienst `docker/compose/automations/alice-image-processing/` (Port 8020, keine nginx-Route, Eintrag im `Makefile`), Migration `sql/migrations/2026-11-27_PROJ-125_images.sql` (= Abschnitt 22 in `init-schema.sql`), Register-Erweiterungen in `alice-source-registry`.
- Register:
  - `claim` mit `registered_since`/`registered_before` (Vergleich mit `sources.created_at`) und `source_ids`
  - `done` mit `skipped`
  - `_reset_after` setzt auch `skipped`-Stufen zurück, wenn die Art nicht in `skip_kinds` der Stufe steht
  - neuer Index `idx_sources_kind_created`
- `taken` ist die Kamerazeit wie gelesen (`YYYY-MM-DDThh:mm:ss`, mit Offset nur, wenn `OffsetTimeOriginal` gesetzt ist). Der Titel nimmt immer die Kamerazeit, auch bei Offset.
- `location` ist ohne GPS `null` (nicht ein Objekt mit leeren Feldern). `gps.altitude` ist `null`, wenn das Bild keine Höhe hat.
- Die Abschrift steht in einem Code-Block mit Sprache `text` und einem Zaun, der länger ist als jede Backtick-Folge der Abschrift.
- Ein Gateway-Ausfall (nicht erreichbar, Zeitüberschreitung, 401/403/429/5xx) zählt als Fehlversuch mit Backoff. Danach pausiert die Beschreibung `IMAGE_LLM_RETRY_SECONDS`.
- Angestoßene Einzelbilder: Der Eintrag in `image_describe_requests` wird bei der Übernahme gelöscht. Geht das Bild danach ohne Fehlversuch zurück (z. B. NAS weg), muss es neu angestoßen werden, wenn der Bestand gesperrt ist.
- Bilder mit GPS, deren Ort am Tageslimit scheitert, gehen mit Wartezeit bis 00:00 Europe/Berlin (+5 s) zurück. Bilder mit Übernahme aus Weaviate laufen am selben Tag weiter.
- HEIC: pillow-heif wendet die Drehung schon beim Lesen an und meldet danach Orientierung 1. `width`/`height` sind damit die angezeigten Maße wie bei JPEG.
- Neuaufbau (PROJ-120) mit Art `image` ab `extract` umfasst `extract` und `locate`, sobald beide Stufen für Bilder einmal übernommen wurden (Register-Mechanismus „served“). Der Bestand bleibt auch im Neuaufbau bis zur Freigabe gesperrt.
- Tests anderer Dienste: Die Testlisten der Standardstufen (`DEFAULT_STAGES`) und zwei Erwartungen in `alice-etl-status` kennen jetzt `locate`. Zwei Register-Tests erwarten `locate: skipped` bei Dokumenten.
- Abweichungen von der Spec: keine.
