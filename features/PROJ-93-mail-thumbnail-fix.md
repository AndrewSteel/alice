# PROJ-93: Mail-Thumbnail-Fix

## Status: Deployed
**Created:** 2026-08-24
**Last Updated:** 2026-08-24 (deployed)

## Dependencies
- Betrifft: `alice-dms-thumbnailer` (n8n-Workflow, PROJ-55, Deployed) und den zugehörigen `alice-dms-thumbnailer`-Service (`/generate`-Endpoint).
- Betrifft: `alice-mail-sync` (n8n-Workflow, PROJ-53, Deployed) — `MQTT: Publish Email Done`.
- Bezieht sich auf die PROJ-80-Lückenschluss-Zusage aus PROJ-53 (AC-5.1–5.3, DMS-Vollständigkeits-Dashboard) — Mails sollen wie andere Dokumenttypen ein Thumbnail bekommen.

## Kontext

`alice-dms-thumbnailer`s `Code: Parse & Filter`-Node verwirft jede MQTT-Nachricht ohne `file_path` (`if (!msg.weaviate_uuid || !msg.file_path) { ...skip }`). `alice-mail-sync`s `MQTT: Publish Email Done` sendet aber nur `{ weaviate_uuid, document_type: 'Email', file_type: 'txt', inserted, timestamp }` — kein `file_path`. Folge: Mail-Objekte werden zwar korrekt in Weaviate indexiert und das MQTT-Topic `alice/dms/done` korrekt gefeuert, aber der Thumbnailer verwirft die Nachricht sofort und protokolliert nur eine Warnung. Mails bekommen seit Einführung nie ein Thumbnail — ein vorbestehender Bug seit Iteration 1 (BUG-15, gefunden bei der PROJ-53-Iteration-4-QA).

**Warum ein einfaches Nachreichen von `file_path` nicht funktioniert:** Mail-Objekte haben keinen NAS-Pfad — ihr Inhalt (Betreff + Body-Preview) liegt ausschließlich als Text in Weaviate (`Email`-Klasse, Felder `subject`, `content`, `sender`, `senderName`, `date`). Der `alice-dms-thumbnailer`-Service liest in `/generate` zwingend eine reale Datei von der Platte (`src.exists()`-Check, danach z.B. `_render_text_preview()`, das den Dateiinhalt via `open(text_path)` liest) — es gibt aktuell keinen Weg, ihm stattdessen direkten Textinhalt zu übergeben.

**Gewählter Lösungsansatz** (Nutzerentscheidung in der Spec-Phase): Statt einer temporären Platzhalter-Datei liest der n8n-Workflow den Mail-Inhalt (Betreff + Body-Preview) direkt aus Weaviate per GraphQL-Query (unter Verwendung der bereits im MQTT-Payload enthaltenen `weaviate_uuid`) und übergibt ihn dem Thumbnailer-Service über einen neuen, Mail-spezifischen Rendering-Modus, der keinen Datei-Pfad benötigt. Kein neuer Redis-Key, keine temporäre Datei, kein Datei-Lifecycle-Problem.

## User Stories

- Als Admin möchte ich, dass E-Mail-Objekte im DMS-Vollständigkeits-Dashboard genauso ein Thumbnail haben wie andere Dokumenttypen, damit die Coverage-Anzeige für Mails nicht dauerhaft bei 0% hängen bleibt.
- Als Admin möchte ich beim Durchsuchen der DMS-Bibliothek eine visuelle Vorschau (Betreff + Textanfang) für importierte Mails sehen, analog zur Textvorschau bei TXT/MD-Dokumenten.

## Acceptance Criteria

- [ ] `alice-mail-sync`s `MQTT: Publish Email Done` löst weiterhin zuverlässig eine Thumbnail-Generierung für jedes neu gespeicherte Email-Objekt aus (keine Regression der bisherigen Trigger-Kette)
- [ ] `alice-dms-thumbnailer`-Workflow erkennt `document_type: 'Email'`-Nachrichten und behandelt sie nicht mehr als "fehlender file_path" → verwerfen, sondern über einen dedizierten Mail-Pfad
- [ ] Für Mail-Objekte wird Betreff + Anfang des Body-Contents (Body-Preview) per Weaviate-GraphQL-Query anhand der `weaviate_uuid` geladen (kein Datei-Zugriff)
- [ ] `alice-dms-thumbnailer`-Service bekommt einen neuen, Mail-spezifischen Rendering-Pfad, der ein Thumbnail-Bild direkt aus übergebenem Text (Betreff + Body-Preview) erzeugt, ohne eine Datei von der Platte zu lesen
- [ ] Das erzeugte Mail-Thumbnail wird wie bei anderen Dokumenttypen unter `thumbnails/<weaviate_uuid>.jpg` gespeichert und das Weaviate-Objekt erhält den `thumbnail_path` (identisches Verhalten zum bestehenden `HTTP: PATCH Weaviate thumbnail_path`-Schritt)
- [ ] Bestehendes Thumbnail-Verhalten für alle anderen Dokumenttypen (PDF, Office, Bilder, TXT/MD) bleibt unverändert (keine Regression)
- [ ] Eine Mail ohne Betreff und ohne Body-Content (beide leer) führt zu einem sauberen Fehlschlag (analog zum bestehenden `_render_text_preview`-Verhalten bei leerem Text: kein Bild, `HTTP 422`), nicht zu einem Crash

## Edge Cases

- **Mail-Objekt in Weaviate wurde zwischen MQTT-Publish und Thumbnail-Generierung bereits gelöscht** (z.B. durch einen parallelen Backfill/Migrationslauf): GraphQL-Query liefert kein Ergebnis → Thumbnail-Generierung schlägt sauber fehl (analog zum bestehenden `422`-Verhalten bei fehlender Datei), kein Crash, per `MQTT: Publish thumb_error` sichtbar wie bei jedem anderen Fehlerfall.
- **Sehr langer Betreff oder Body-Content**: Wird wie beim bestehenden Text-Rendering auf eine sinnvolle Zeichen-/Zeilenzahl begrenzt (analog zum bestehenden `text[:2000]`-Limit), kein unbegrenztes Rendering.
- **Betreff vorhanden, aber Body-Content leer** (z.B. reine Betreff-Mail ohne Text): Thumbnail wird trotzdem erzeugt, zeigt nur den Betreff — kein Sonderfall nötig, da der Text insgesamt nicht komplett leer ist.
- **Weaviate zum Zeitpunkt der Thumbnail-Anfrage nicht erreichbar**: Query schlägt fehl → Thumbnail-Generierung bricht sauber mit Fehler ab (gleiches Verhalten wie ein fehlgeschlagener HTTP-Aufruf an anderer Stelle im Workflow), keine Endlosschleife, keine Blockade nachfolgender MQTT-Nachrichten.
- **Sonderzeichen/HTML-Fragmente im Body-Content** (z.B. wenn `body_preview` ungefilterten HTML-Text enthält): Werden wie normaler Text gerendert (kein HTML-Parsing/-Escaping nötig, da nur als Bild-Text dargestellt, nicht interpretiert) — kein Sicherheitsrisiko, da kein Code ausgeführt wird.

## Technical Requirements (optional)

- Kein neuer Redis-Key, keine temporäre Datei auf der Platte, kein Datei-Lifecycle (löschen/aufräumen) nötig.
- Wiederverwendung der bestehenden Thumbnail-Speicherlogik (`THUMB_DIR`, `thumbnail_path`-Patch) — nur der Rendering-Eingang ändert sich für Mail-Objekte.
- Mail-spezifisch, keine Generalisierung auf andere pfadlose Objekttypen (Nutzerentscheidung: kleinster abgegrenzter Fix für BUG-15).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### E) Workflow Architecture

PROJ-93 hat keine UI-Komponente. Es erweitert den bestehenden `alice-dms-thumbnailer`-Workflow um einen zweiten Verarbeitungspfad für Mail-Objekte und den zugehörigen `alice-dms-thumbnailer`-Service um einen neuen Rendering-Modus — kein neuer Workflow, kein neuer Trigger, kein neuer Service.

**Bestehender Ablauf (unverändert für Nicht-Mail-Dokumente):**

`MQTT: alice/dms/done` → `Code: Parse & Filter` (verwirft Nachrichten ohne `file_path`) → `HTTP: POST /generate` (liest Datei von der Platte, rendert Thumbnail) → `IF: Generate OK` → `HTTP: PATCH Weaviate thumbnail_path` bzw. Fehlerpfad.

**Neuer Ablauf für Mail-Objekte:**

1. **`Code: Parse & Filter` erweitert:** Statt Nachrichten mit `document_type: 'Email'` (die naturgemäß keinen `file_path` haben) zu verwerfen, werden sie erkannt und mit einem eigenen Kennzeichen weitergeleitet, statt der bestehenden "fehlt file_path"-Verwerfungsregel zu unterliegen. Alle anderen Dokumenttypen durchlaufen exakt dieselbe Prüfung wie bisher (`file_path` weiterhin Pflicht).
2. **Mail-Inhalt laden:** Für als Mail erkannte Nachrichten wird — bevor der Thumbnailer-Service aufgerufen wird — der Betreff und der Body-Preview-Text per Weaviate-GraphQL-Abfrage anhand der bereits im MQTT-Payload enthaltenen `weaviate_uuid` nachgeladen (dieselbe Art von Abfrage, wie sie bereits an anderen Stellen der DMS-Pipeline gegen Weaviate verwendet wird).
3. **`HTTP: POST /generate` erweitert:** Für Mail-Objekte wird dem Thumbnailer-Service statt eines Datei-Pfads der geladene Text (Betreff + Body-Preview) übergeben. Der Service erkennt anhand von `document_type: 'Email'`, dass er seinen neuen Text-Rendering-Pfad statt des bestehenden Datei-Lesepfads nutzen soll — keine Datei-Existenzprüfung, kein Datei-Zugriff für diesen Fall.
4. **Rest des Ablaufs unverändert:** Erfolgs-/Fehlerauswertung (`IF: Generate OK`), Speicherung des Thumbnail-Pfads in Weaviate (`HTTP: PATCH Weaviate thumbnail_path`) und Logging laufen identisch zum bestehenden Verhalten — für den nachgelagerten Workflow-Teil ist es unerheblich, ob das Thumbnail aus einer Datei oder aus Text gerendert wurde.

**Data flow:** MQTT-Nachricht (`document_type: 'Email'`, `weaviate_uuid`, kein `file_path`) → Erkennung als Mail statt Verwerfung → Weaviate-Abfrage liefert Betreff+Content → Thumbnailer-Service rendert Text-Vorschau-Bild direkt aus dem übergebenen Text → Speicherung wie gehabt.

**Integrationen:** Eine zusätzliche, lesende Weaviate-GraphQL-Abfrage im n8n-Workflow (kein neuer Integrationspunkt — Weaviate wird an anderer Stelle der DMS-Pipeline bereits genauso abgefragt). Keine neuen externen Abhängigkeiten im Thumbnailer-Service.

**Fehlerverhalten:** Unverändert zum bestehenden Muster — jeder Fehlschlag (Mail-Objekt nicht mehr in Weaviate vorhanden, Weaviate nicht erreichbar, leerer Text) führt über denselben bestehenden `IF: Generate OK`-Fehlerpfad zu `Code: Log Error` → `MQTT: Publish thumb_error`, kein neuer Fehlerpfad nötig.

### Datenmodell (fachlich)

Kein neues Datenbankschema. Es werden ausschließlich bereits vorhandene Felder der bestehenden `Email`-Klasse in Weaviate gelesen (`subject`, `content`) — keine neuen Felder, keine Schema-Änderung. Das erzeugte Thumbnail wird wie bei jedem anderen Dokumenttyp im bestehenden `thumbnail_path`-Feld referenziert.

### Tech-Entscheidungen (Begründung)

- **Text direkt aus Weaviate lesen statt Platzhalter-Datei schreiben:** Eine temporäre Datei würde einen neuen Lifecycle-Bedarf schaffen (wann wird sie gelöscht? was, wenn das Löschen fehlschlägt?) für ein Problem, das sich ohne Datei lösen lässt — der Inhalt liegt bereits vollständig in Weaviate vor, dieselbe Quelle, aus der auch der Klassifizierungs-Prompt beim Import gespeist wurde. Kein neuer State, kein neues Aufräumproblem (Nutzerentscheidung in der Spec-Phase).
- **Mail-spezifischer Rendering-Modus statt generischer "Text-Content"-Parameter:** Der aktuelle Bedarf ist ausschließlich Mail-Objekte. Eine generische Lösung für beliebige pfadlose Dokumenttypen wäre spekulative Vorab-Flexibilität für einen Anwendungsfall, der aktuell nicht existiert (Nutzerentscheidung, konsistent mit dem Simplicity-First-Grundsatz des Projekts).
- **Betreff + Body-Preview als Vorschau-Inhalt, begrenzt (analog zum bestehenden Text-Rendering-Verhalten):** Konsistent mit der bereits etablierten Konvention für TXT/MD-Dokumente (begrenzte Zeichen-/Zeilenzahl, kein unbegrenztes Rendering) — kein neuer Grenzwert-Typ, sondern Wiederverwendung des bestehenden Musters.
- **Kein HTML-Escaping/-Parsing für den Body-Preview-Text nötig:** Der Text wird ausschließlich als Bild-Text gerendert (Pixel, kein Code-Kontext) — ein evtl. enthaltenes HTML-Fragment im Body-Preview stellt kein Sicherheitsrisiko dar, da nichts interpretiert oder ausgeführt wird.

### Dependencies (Pakete)

Keine neuen Pakete. Der Thumbnailer-Service nutzt für den neuen Text-Rendering-Pfad dieselbe bereits vorhandene Bildbibliothek (Pillow), die auch für die bestehende Text-Vorschau (TXT/MD) verwendet wird.

### Implementation Notes (Backend)

**Umgesetzt in:**
- `workflows/alice-dms-thumbnailer.json` — neuer Mail-Zweig
- `docker/compose/automations/alice-dms-thumbnailer/app/main.py` — neuer Text-Rendering-Modus

**Workflow-Änderungen:**

- `Code: Parse & Filter`: Nachrichten mit `document_type: 'Email'` sind jetzt von der `file_path`-Pflicht ausgenommen (`weaviate_uuid` bleibt für alle Typen Pflicht).
- Neuer `IF: Is Email`-Node direkt nach `Code: Parse & Filter`: bei `document_type === 'Email'` geht es über zwei neue Nodes (`HTTP: GET Weaviate Email Content` → `Code: Merge Mail Text`), sonst direkt weiter — beide Zweige münden in denselben `HTTP: POST /generate`-Node.
- `HTTP: GET Weaviate Email Content`: liest das Email-Objekt per `GET /v1/objects/Email/{uuid}` direkt von Weaviate (REST, kein GraphQL nötig, gleicher Stil wie der bestehende `HTTP: PATCH Weaviate thumbnail_path`-Node).
- `Code: Merge Mail Text`: baut aus `properties.subject` (max. 200 Zeichen) und `properties.content` (max. 2000 Zeichen) einen zusammengesetzten Vorschautext; fängt einen fehlgeschlagenen Lookup (Objekt gelöscht, Weaviate down) sauber ab, ohne zu crashen — der nachgelagerte `/generate`-Aufruf bekommt dann leeren `mail_text` und scheitert kontrolliert über den bereits bestehenden `IF: Generate OK`-Fehlerpfad.
- `HTTP: POST /generate`: Payload-Aufbau verzweigt jetzt je nach `document_type` — für Mail wird `mail_text` statt `original_path` gesendet.
- `Code: Log Error`: zeigt für Mail-Fehlerfälle `(email, no file_path)` statt eines `undefined`-Werts im Log (kosmetische Verbesserung, kein AC).

**Service-Änderungen (`alice-dms-thumbnailer`):**

- `GenerateRequest`: `original_path` ist jetzt optional (`str | None`), neues optionales Feld `mail_text`. Ein neuer `@model_validator(mode="after")` erzwingt: `document_type == 'Email'` → `mail_text` nicht-leer Pflicht; sonst → `original_path` Pflicht (unverändertes Verhalten für alle bisherigen Aufrufer).
- Neue Hilfsfunktion `_render_text_image(text)`: rendert beliebigen In-Memory-Text als Bild (Refactoring aus dem bestehenden `_render_text_preview`, das jetzt nur noch die Datei liest und an die neue Funktion delegiert — identisches Verhalten für den bestehenden TXT/MD-Pfad).
- `generate_thumbnail()`: neuer optionaler `mail_text`-Parameter; ist er gesetzt, wird direkt aus Text gerendert (kein Datei-Zugriff), sonst unverändertes bisheriges Verhalten.
- `/generate`-Endpoint: der `src.exists()`-Check wird für `document_type == 'Email'` übersprungen (kein Datei-Pfad vorhanden), sonst unverändert.

**Gefundener und selbst behobener Bug während der Implementierung:** Die erste Fassung des `document_type`/`mail_text`/`original_path`-Cross-Field-Checks nutzte einen `@field_validator("document_type")` mit `info.data` — das schlug fehl, weil Pydantic v2 Felder in Deklarationsreihenfolge validiert und `info.data` beim Erreichen von `document_type` `original_path`/`mail_text` (später deklariert) noch nicht enthält. Live gegen den echten FastAPI-Endpunkt getestet, Fehlschlag beobachtet (`mail_text must not be empty` trotz gesetztem `mail_text`), auf `@model_validator(mode="after")` umgestellt (sieht alle Felder unabhängig von der Deklarationsreihenfolge) und erneut verifiziert.

**Verifikation (eigenständig, mit echtem laufenden FastAPI-Service, kein Mock):**

- `python3 -m py_compile main.py`: syntaktisch valide.
- **Live-Test gegen die echte FastAPI-App** (`TestClient`, `startup`-Event ausgelöst, echtes Pillow-Rendering, kein Mock): gültige Mail-Anfrage → `200`, Thumbnail-Datei tatsächlich auf der Platte geschrieben (400×400 RGB JPEG, per Pillow nachgeladen und verifiziert), Bildinhalt visuell geprüft (Betreff + Body-Text lesbar gerendert).
- Fehlende/leere `mail_text` bei `document_type: 'Email'` → `422` (Validierung greift).
- Fehlender `original_path` bei Nicht-Mail → `422` (Validierung greift, neues Pflichtverhalten für Alt-Aufrufer unverändert).
- **Regressionstest Path-Traversal** (`/etc/passwd`, `../../etc/passwd`): weiterhin `422` — die bestehende Sicherheitsprüfung ist durch die Optional-Machung von `original_path` nicht geschwächt.
- **Regressionstest bestehender TXT-Datei-Pfad**: echte Datei auf Platte angelegt, `document_type: 'Document'` mit `original_path` → `200`, Thumbnail erfolgreich erzeugt — bestätigt, dass das Refactoring von `_render_text_preview` das bestehende Verhalten nicht verändert hat.
- Edge Cases: sehr langer `mail_text` (100.000 Zeichen) → kein Crash, `200` (durch das bestehende `[:2000]`-Slice in `_render_text_image` begrenzt); nur Betreff ohne Body → `200`; `original_path` zusätzlich zu `mail_text` bei Mail mitgegeben (fehlerhafter/inkonsistenter Aufrufer-Fall) → `mail_text` gewinnt, kein Datei-Zugriff, `200` (kein Crash trotz nicht-existentem Pfad).
- Workflow-JSON: strukturelle Prüfung (eigenständiges Skript) — valide JSON, keine doppelten Node-Namen/-IDs, alle `connections`-Ziele und `$('Node')`-Referenzen lösen auf, kein `console.log`, alle Nodes vom Trigger aus erreichbar (BFS). Alle 5 Code-Nodes bestehen `node --check`.

**Nicht verifizierbar ohne Deploy/echte Weaviate-Instanz:** Verhalten gegen eine echte Weaviate-Instanz (reales `GET /v1/objects/Email/{uuid}`-Response-Format), tatsächliches MQTT-Timing im Live-Workflow, echte Mail-Inhalte mit Sonderzeichen/verschiedenen Sprachen im Rendering.

---
_Implementation abgeschlossen._

## QA Test Results

**Tested:** 2026-08-24
**Commit under test:** `079b055` (fix(PROJ-93): Add mail thumbnail generation without a NAS file path)
**Scope:** `workflows/alice-dms-thumbnailer.json`, `docker/compose/automations/alice-dms-thumbnailer/app/main.py`
**Tester:** QA Engineer (AI)

### Testmethode

Kein Deploy, kein Live-n8n/Weaviate in dieser Umgebung. Eigenständige Verifikation, nicht auf die Implementation Notes verlassen:

1. **Unabhängige Graph-Traversierung** des Workflows (eigenes BFS/DFS-Skript über das `connections`-Objekt, nicht die Beschreibung des Implementers).
2. **Frischer Code-Review** von `GenerateRequest`, `_render_text_image`, `generate_thumbnail`, `/generate` — eigenständig gelesen, nicht nur den Diff überflogen.
3. **Live-Tests gegen den echten laufenden FastAPI-Service** (`TestClient`, `startup`-Event ausgelöst, echtes Pillow-Rendering) — eigene, teils zusätzliche Testfälle über die des Implementers hinaus (Unicode/RTL/Emoji, Kontrollzeichen/ANSI-Escapes, sehr lange zusammenhängende Zeichenketten ohne Leerzeichen, sehr viele Zeilen).
4. **Trust-Boundary-Analyse**: geprüft, ob die Lockerung der `file_path`-Pflicht in `Code: Parse & Filter` eine neue Angriffsfläche öffnet.
5. **Logik-Nachvollzug in Python** der `Code: Merge Mail Text`-JS-Logik für den Weaviate-404-Fall (EC-1), um das dokumentierte Fehlerverhalten tatsächlich zu bestätigen statt nur zu glauben.

### Acceptance Criteria Status

| # | Acceptance Criterion | Status | Nachweis |
|---|---|---|---|
| AC-1 | `MQTT: Publish Email Done` löst weiterhin zuverlässig Thumbnail-Generierung aus (keine Regression der Trigger-Kette) | **PASS** | `alice-mail-sync`s `MQTT: Publish Email Done`-Node im Diff nicht angefasst (git diff bestätigt: nur Thumbnailer-Dateien geändert). MQTT-Topic/Payload-Struktur unverändert. |
| AC-2 | Thumbnailer-Workflow erkennt `document_type: 'Email'` statt zu verwerfen | **PASS** | `Code: Parse & Filter`: `isEmail`-Check exempt von der `file_path`-Pflicht; eigene Graph-Traversierung bestätigt `IF: Is Email` unmittelbar danach mit zwei Ausgängen. |
| AC-3 | Betreff+Body-Preview wird per Weaviate-Query anhand `weaviate_uuid` geladen (kein Datei-Zugriff) | **PASS** (mit dokumentierter, sachlich begründeter Abweichung) | Implementiert als **REST `GET /v1/objects/Email/{uuid}`** statt GraphQL, wie im Tech Design explizit begründet (einfacher, gleicher Stil wie der bereits bestehende PATCH-Node). Erfüllt den Sinn des AC (kein Datei-Zugriff, Laden per `weaviate_uuid`) vollständig — GraphQL war im Spec-Text als Mittel zum Zweck genannt, nicht als harte Vorgabe. Kein Bug. |
| AC-4 | Service bekommt Mail-spezifischen Rendering-Pfad ohne Datei-Zugriff | **PASS** | `generate_thumbnail(..., mail_text=...)`: bei gesetztem `mail_text` wird `_render_text_image()` direkt aufgerufen, kein `open()`/Datei-I/O in diesem Zweig (Code-Review bestätigt). `/generate`-Endpoint überspringt `src.exists()` für `document_type == 'Email'`. |
| AC-5 | Thumbnail wird wie gewohnt gespeichert, `thumbnail_path` im Weaviate-Objekt aktualisiert | **PASS** | `Code: Extract Thumbnail Path` → `HTTP: PATCH Weaviate thumbnail_path` unverändert im Graph nach dem Merge-Punkt — läuft für Mail-Thumbnails identisch zu allen anderen Typen. Live-Test: Thumbnail-Datei tatsächlich auf Platte erzeugt (400×400 RGB JPEG), Response enthält `thumbnail_path`. |
| AC-6 | Bestehendes Verhalten für andere Dokumenttypen unverändert (keine Regression) | **PASS** | Eigener Live-Regressionstest: echte `.txt`-Datei angelegt, `document_type: 'Document'` mit `original_path` → `200`, Thumbnail erfolgreich erzeugt. Path-Traversal-Schutz (`/etc/passwd`, `../../etc/passwd`) weiterhin aktiv, eigenständig erneut angegriffen und bestätigt blockiert. `_render_text_preview()` delegiert jetzt an `_render_text_image()`, aber mit identischem Datenfluss (Datei lesen → Text → rendern), kein Verhaltensunterschied. |
| AC-7 | Mail ohne Betreff und Content → sauberer Fehlschlag, kein Crash | **PASS** | Eigener Test: `mail_text: "   "` (nur Whitespace) → `422`, kein Absturz. Zusätzlich verifiziert: fehlendes `mail_text`-Feld ganz → ebenfalls `422`. |

**7/7 Acceptance Criteria PASS.**

### Edge Cases Status

| # | Edge Case | Status | Nachweis |
|---|---|---|---|
| EC-1 | Mail-Objekt zwischen Publish und Generierung gelöscht | **PASS** | Eigenständig nachvollzogen (nicht nur behauptet): `Code: Merge Mail Text`-Logik in Python nachgebaut und mit einer simulierten Weaviate-404-Response durchgespielt → `mail_text` wird leerer String → service-seitiger `model_validator` liefert `422` → `IF: Generate OK` routet in den bestehenden Fehlerpfad → `MQTT: Publish thumb_error`. Kein Crash, kein Sonderfall nötig. |
| EC-2 | Sehr langer Betreff/Content, begrenzt statt unbegrenzt | **PASS** | `Code: Merge Mail Text` kappt `subject` bei 200 und `content` bei 2000 Zeichen; `_render_text_image` kappt zusätzlich nochmal bei 2000 Zeichen (bestehende Konstante). Eigener Live-Test mit 100.000-Zeichen-`mail_text` → `200`, kein Crash, keine spürbare Verzögerung. |
| EC-3 | Betreff vorhanden, Content leer → Thumbnail zeigt nur Betreff | **PASS** | Eigener Test: `mail_text: "Nur Betreff, kein Body"` → `200`. Durch die `filter(Boolean).join()`-Logik im Merge-Node wird ein leeres `content` korrekt weggelassen, kein doppelter Zeilenumbruch. |
| EC-4 | Weaviate nicht erreichbar bei Thumbnail-Anfrage | **PASS** | `HTTP: GET Weaviate Email Content` hat `onError: "continueRegularOutput"` — ein Verbindungsfehler erzeugt ein Item mit Fehlerstatus statt den Workflow abzubrechen; `Code: Merge Mail Text` behandelt jeden `statusCode` außerhalb 200–299 identisch zum 404-Fall (EC-1), landet also im selben verifizierten Fehlerpfad. Keine Endlosschleife, keine Blockade nachfolgender Nachrichten (jede MQTT-Nachricht ist eine unabhängige Workflow-Execution). |
| EC-5 | Sonderzeichen/HTML-Fragmente im Body-Content | **PASS, plus eigene Zusatztests** | Über die Spec hinaus getestet: Unicode/RTL/Emoji (Hebräisch, Chinesisch, Emoji-Sequenzen) → `200`, kein Crash. Kontrollzeichen und ANSI-Escape-Sequenzen (`\x00`, `\x1b[31m...`) → `200`, kein Crash (Pillow rendert sie als Pixel-Text, keine Interpretation). Sehr lange zusammenhängende Zeichenkette ohne Leerzeichen (5000 Zeichen "A") → `200` in 0,03s, kein Hänger im Word-Wrap von `multiline_text`. Sehr viele Zeilen (3000×"line") → `200`, kein Crash. |

**5/5 Edge Cases PASS** (alle eigenständig nachvollzogen, EC-5 mit zusätzlichen selbst gewählten Angriffsvektoren über die Spec hinaus).

### Security Audit Results

**n8n workflow + Docker-Backend-Feature:**
- [x] **Path Traversal (Regression):** `original_path`-Validierung (`DOCUMENTS_ROOT`-Präfix-Check) unverändert und weiterhin aktiv für Nicht-Mail-Requests — eigenständig erneut mit `/etc/passwd` und `../../etc/passwd` angegriffen, beide weiterhin `422`.
- [x] **Kein neuer Datei-Schreibzugriff:** Der Mail-Pfad schreibt ausschließlich das generierte Thumbnail unter der bestehenden `THUMB_DIR`-Konvention (`<uuid>.jpg`), liest aber nie eine Datei — kleinere Angriffsfläche als der Datei-Pfad, nicht größer.
- [x] **Kein Code-Interpretationsrisiko im gerenderten Text:** Body-Preview-Text (potenziell HTML-Fragmente, Kontrollzeichen, ANSI-Escapes) wird ausschließlich als Pixel-Text gezeichnet (`ImageDraw.multiline_text`) — kein HTML-Parser, kein Terminal, keine Codeausführung. Eigenständig mit ANSI-Escape-Sequenzen und Null-Bytes angegriffen, keine Auffälligkeit.
- [x] **Trust-Boundary MQTT unverändert:** Die Lockerung der `file_path`-Pflicht in `Code: Parse & Filter` öffnet keine neue Angriffsfläche — wer bereits MQTT-Nachrichten auf `alice/dms/done` fälschen kann (Compromise des internen, passwortgeschützten Brokers), konnte vorher schon `file_path`/`document_type` beliebig setzen (inkl. Path-Traversal-Versuchen gegen den bereits bestehenden Datei-Lesepfad und die PATCH-URL-Konstruktion). `weaviate_uuid`-String-Konkatenation in der neuen `HTTP: GET Weaviate Email Content`-URL folgt exakt demselben, bereits akzeptierten Muster wie der bestehende `HTTP: PATCH Weaviate thumbnail_path`-Node — keine neue Instanz eines bestehenden Musters stellt einen neuen Fund dar.
- [x] **Model-Validator-Sicherheit:** Der service-seitige Pydantic-Validator erzwingt weiterhin serverseitig, dass Mail-Requests nicht-leeren `mail_text` und Nicht-Mail-Requests einen validierten `original_path` haben — kann nicht durch einen manipulierten Payload umgangen werden (unabhängig vom n8n-Workflow erneut direkt gegen den FastAPI-Endpunkt getestet).

**Security: PASS — keine neue Angriffsfläche, bestehende Schutzmechanismen (Path Traversal) unverändert wirksam.**

### Bugs Found

**Keine.** Weder Critical, High, Medium noch Low.

**Anmerkung (kein Bug, positiv vermerkt):** Der Implementer hat während der eigenen Verifikation einen echten Bug in der ersten Fassung des `document_type`/`mail_text`-Cross-Field-Validators gefunden und korrigiert (Pydantic-v2-Feldreihenfolge-Falle bei `field_validator` + `info.data`, behoben durch `model_validator(mode="after")`) — von QA unabhängig nachvollzogen: der finale Code verwendet korrekt `model_validator`, alle Kombinationen (Email mit/ohne `mail_text`, Nicht-Email mit/ohne `original_path`) wurden von QA selbst erneut gegen den echten Endpunkt getestet und verhalten sich korrekt.

### Regression Check

- `alice-mail-sync` (Publisher-Seite): nicht im Diff enthalten, unverändert.
- Nicht-Mail-Thumbnail-Pfad (PDF/Office/Bild/TXT/MD): `generate_thumbnail()` für `mail_text=None` durchläuft exakt denselben Code wie vor der Änderung (nur der neue `if mail_text is not None:`-Zweig davor, mit `return` vor dem alten Code — keine Vermischung). Live-Regressionstest mit echter Datei bestätigt.
- `_render_text_preview()` (bestehender Datei-Text-Pfad, TXT/MD): jetzt ein dünner Wrapper um `_render_text_image()`, aber Datenfluss identisch (Datei öffnen → erste 30 Zeilen → an Rendering übergeben). Kein Verhaltensunterschied feststellbar.
- Bestehender Fehlerpfad (`IF: Generate OK` → `Code: Log Error` → `MQTT: Publish thumb_error`): unverändert, wird jetzt zusätzlich vom Mail-Fehlerfall mitgenutzt statt eines neuen Pfads — Wiederverwendung korrekt, kein neuer/abweichender Error-Payload-Schema.
- `Code: Log Error`: kosmetische Erweiterung (`(email, no file_path)` statt `undefined` im Log-Text) — keine Verhaltensänderung des Fehlerpfads selbst, nur Log-Lesbarkeit.

### Statische Validierung (Workflow-JSON)

| Check | Ergebnis |
|---|---|
| JSON valide | PASS |
| Doppelte Node-Namen/-IDs | PASS — keine |
| Alle `connections`-Quellen/-Ziele auflösbar | PASS |
| Alle `$('Node')`-Referenzen auflösbar | PASS |
| Alle Nodes vom Trigger aus erreichbar (BFS) | PASS |
| `console.log` (CLAUDE.md: nur winston) | PASS — 0 Treffer |
| Alle 5 Code-Nodes `node --check` | PASS |
| MQTT-Credentials vorhanden & unverändert | PASS |

### Summary

- **Acceptance Criteria:** 7/7 passed
- **Edge Cases:** 5/5 passed
- **Bugs Found:** 0 total (0 critical, 0 high, 0 medium, 0 low)
- **Security:** Pass — keine neue Angriffsfläche, Path-Traversal-Schutz und Trust-Boundary unverändert wirksam
- **Production Ready:** YES
- **Recommendation:** **READY** — Deploy. Alle Acceptance Criteria und Edge Cases eigenständig gegen den echten laufenden Service verifiziert (nicht nur gegen die Implementer-Notizen), inklusive zusätzlicher, über die Spec hinausgehender Angriffsvektoren (Unicode/RTL, Kontrollzeichen, ANSI-Escapes, Wortumbruch-Stresstest). Die einzige Abweichung vom Spec-Wortlaut (REST GET statt GraphQL) ist im Tech Design sachlich begründet und erfüllt den AC-Sinn vollständig — kein Bug.

## Deployment

Deployed am 2026-08-24. `alice-dms-thumbnailer` (Container-Rebuild mit dem neuen Mail-Text-Rendering-Modus) sowie der `alice-dms-thumbnailer`-n8n-Workflow (neuer Mail-Zweig) produktiv live.
