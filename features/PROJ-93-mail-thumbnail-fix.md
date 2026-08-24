# PROJ-93: Mail-Thumbnail-Fix

## Status: Planned
**Created:** 2026-08-24
**Last Updated:** 2026-08-24

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
