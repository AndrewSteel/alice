# PROJ-53: Mail-Anhang DMS-Import

## Status: In Progress
**Created:** 2026-08-22
**Last Updated:** 2026-08-22

## Dependencies
- Requires: PROJ-46 (Mail IMAP Integration) — Deployed. Liefert `alice-mail-sync` (Sync-Loop, Message-ID-Dedup, LLM-Kategorisierung Wichtig/Werbung/Social Media/Spam) und `alice-mail-reader` (IMAP-Adapter für Attachment-Zugriff).
- Requires: PROJ-15 (DMS NAS-Ordner-Verwaltung) — Deployed. Admin trägt die neuen Schema-Zielordner manuell in `alice.dms_watched_folders` ein.
- Requires: PROJ-16 (DMS Scanner & NAS Multi-Format-Scan) — Deployed. Liefert `SUPPORTED_EXTENSIONS`-Allowlist, die für den Attachment-Filter wiederverwendet wird.
- Requires: PROJ-55 (DMS Thumbnail-Generierung) — Deployed. `alice-dms-thumbnailer` + Text-Rendering-Logik (TXT/MD) werden für den Mail-Thumbnail-Teil wiederverwendet.
- Requires: PROJ-21/22 (DMS Lifecycle Management) — Deployed. Automatische Pfad-Aktualisierung/Bereinigung bei Datei-Verschiebung durch den Admin läuft bereits generisch für alle überwachten Ordner — kein neuer Aufwand in PROJ-53.
- Voraussetzung (bereits erledigt): NAS-Freigabe `/mnt/nas/ai` ist für den User `ki-server` (GID 1031) auf Lesen+Schreiben gesetzt; alle anderen Freigaben bleiben Read-Only. Betroffene, noch nicht neu gestartete Docker-Container sind von dieser Änderung nicht negativ betroffen.

## Kontext

PROJ-46 indexiert E-Mails samt Anhang-**Metadaten** (Dateiname, MIME-Typ, Größe), lädt aber explizit keine Anhänge herunter oder speist sie in andere Systeme ein — das war bei PROJ-46 bewusst als zukünftiges Feature ausgeklammert. PROJ-53 schließt diese Lücke: Anhänge, die inhaltlich in ein DMS-Schema passen (Rechnung, Kontoauszug, Dokument, Vertrag, Wertpapierabrechnung), werden automatisch erkannt, in feste Zielordner auf der AI-Freigabe gespeichert und laufen von dort aus über die bestehende DMS-Pipeline (Scanner → Processor → Klassifizierung/Weaviate → Thumbnailer) — vollständig automatisch, ohne manuellen Trigger.

Zusätzlich schließt PROJ-53 eine bei PROJ-80 entdeckte Lücke: Mail-Objekte in der Weaviate-`Email`-Collection (aus PROJ-46) bekommen nie ein Thumbnail, weil `alice-mail-sync` das für den Thumbnailer nötige MQTT-Topic `alice/dms/done` nicht publiziert.

## User Stories

- Als Andreas möchte ich, dass Rechnungen, Kontoauszüge, Verträge und Wertpapierabrechnungen, die mir per Mail zugeschickt werden, automatisch ins DMS gelangen, damit ich sie nicht mehr manuell herunterladen und ablegen muss.
- Als Admin möchte ich die von der Mail-Pipeline befüllten Zielordner wie jeden anderen NAS-Ordner in die DMS-Pipeline aufnehmen können, damit ich keinen separaten Verwaltungsmechanismus lernen muss.
- Als Admin möchte ich Dateien zwischen der AI-Freigabe und den anderen NAS-Freigaben frei verschieben können, ohne dass das DMS die Übersicht über den Dokumentenpfad verliert (bereits durch PROJ-21/22 gewährleistet).
- Als Andreas möchte ich, dass eindeutig nicht-relevante Anhänge (z.B. E-Mail-Signatur-Icons) gar nicht erst im DMS landen, damit die Wissensbasis nicht mit Datenmüll verschmutzt wird.
- Als Andreas möchte ich, dass auch Mail-Inhalte (nicht nur Anhänge) ein Vorschaubild bekommen, damit die Flip-Card-Ansicht (PROJ-54) für Mails genauso funktioniert wie für andere Dokumenttypen.

## Acceptance Criteria

### Zielordner-Struktur
- [ ] Für jedes der fünf relevanten DMS-Schemata existiert ein fester Unterordner in `/mnt/nas/ai/`, benannt nach dem Weaviate-Klassennamen: `Invoice/`, `BankStatement/`, `Document/`, `Contract/`, `SecuritySettlement/`
- [ ] Fehlt einer dieser Ordner beim ersten Sync-Lauf, wird er automatisch angelegt
- [ ] Die Ordner sind reine Ablageziele der Mail-Pipeline; die Aufnahme in `alice.dms_watched_folders` (inkl. Zuordnung zum passenden deutschen `suggested_type`-Wert) erfolgt manuell durch den Admin — kein automatischer DB-Eintrag durch PROJ-53

### Anhang-Erkennung & Klassifizierung (Erweiterung von `alice-mail-sync`)
- [ ] Für jede neu indexierte Mail mit mindestens einem Anhang wird ein zusätzlicher Klassifizierungsschritt ausgeführt, unabhängig von der bestehenden Wichtig/Werbung/Social-Media/Spam-Kategorisierung aus PROJ-46
- [ ] Nur Anhänge mit einer Dateiendung aus der bestehenden `SUPPORTED_EXTENSIONS`-Allowlist (PROJ-16/55, aktuell u.a. PDF, DOCX, XLSX, ODT, ODS, TXT, MD, JPG, JPEG, PNG, WEBP, HEIC, TIF, TIFF) werden berücksichtigt; die Liste bleibt zentral erweiterbar
- [ ] Offensichtlicher Bild-Datenmüll (typische E-Mail-Signatur-Icons/Logos: Bildformate < 20 KB) wird ohne Klassifizierungsversuch übersprungen — kein Import
- [ ] Jeder verbleibende Anhang wird **einzeln** vom LLM (Ollama/qwen3) klassifiziert — Eingabe: Mail-Betreff + Body-Preview als Kontext, plus Dateiname und extrahierbarer Textinhalt/-vorschau des jeweiligen Anhangs
- [ ] Das LLM ordnet jeden Anhang einem der fünf Schemata zu (Invoice, BankStatement, Document, Contract, SecuritySettlement) oder markiert ihn als nicht eindeutig zuordenbar
- [ ] Nicht eindeutig zuordenbare Anhänge (aber kein gefilterter Bild-Datenmüll) fallen auf `Document` zurück (konsistent mit dem bestehenden Unsicherheits-Verhalten des DMS-Processors, siehe PROJ-78)
- [ ] Eine Mail mit mehreren Anhängen unterschiedlicher Zuordnung speichert jeden Anhang unabhängig im für ihn passenden Zielordner

### Datei-Ablage
- [ ] Der Anhang wird per `alice-mail-reader` (IMAP-Adapter aus PROJ-46) live nachgeladen und im ermittelten Zielordner gespeichert
- [ ] Dateiname beim Speichern: `<Mail-Datum:YYYY-MM-DD>_<Absender-Kurzform>_<Original-Dateiname>` — macht Kollisionen unwahrscheinlich und die Herkunft nachvollziehbar
- [ ] Existiert im Zielordner trotzdem bereits eine Datei mit exakt diesem generierten Namen (z.B. zwei gleichnamige Anhänge in derselben Mail), wird zusätzlich ein fortlaufender Zähler-Suffix `_X` (X = 1, 2, 3, …) vor der Dateiendung angehängt; der Zähler wird nur bei tatsächlicher Kollision verwendet, nicht standardmäßig an jeden Dateinamen angehängt
- [ ] Der Import läuft unabhängig von der PROJ-46-Mail-Kategorie (Wichtig/Werbung/Social Media/Spam) — jeder Anhang jeder Mail wird geprüft
- [ ] Ab Ablage im Zielordner übernimmt die bestehende DMS-Pipeline (Scanner erkennt neue Datei im überwachten Ordner → Processor → Klassifizierung/Weaviate-Insert → Thumbnailer) unverändert; PROJ-53 greift nicht in diese nachgelagerten Schritte ein
- [ ] Erneuter Sync-Lauf (z.B. nach Unterbrechung) führt zu keiner doppelten Anhang-Ablage — abgesichert durch die bestehende Message-ID-Deduplizierung aus `alice-mail-sync` (eine Mail wird nur einmal als "neu" erkannt, ihre Anhänge damit auch nur einmal exportiert) in Kombination mit dem eindeutigen Dateinamen

### Backfill für bereits indexierte Mails
- [ ] Ein manuell auslösbarer n8n-Workflow `alice-mail-attachment-backfill` existiert (analog `alice-dms-thumbnailer-backfill`)
- [ ] Backfill listet alle bereits in Weaviate indexierten `Email`-Objekte mit mindestens einem Eintrag in `attachments` auf, für die noch kein Anhang-Import stattgefunden hat
- [ ] Pro betroffener Mail wird die zugehörige Mailbox erneut per `alice-mail-reader` (IMAP) kontaktiert, um die Original-Anhänge nachzuladen
- [ ] Backfill nutzt dieselbe Klassifizierungs- und Ablage-Logik (inkl. Bild-Müll-Filter, Kollisions-Suffix) wie der Laufzeit-Pfad in `alice-mail-sync`
- [ ] Backfill verarbeitet Postfächer/Mails in Batches und kann unterbrochen/neu gestartet werden, ohne bereits importierte Anhänge erneut abzulegen
- [ ] Fortschritt wird im n8n-Execution-Log sichtbar (`{ processed, imported, skipped_no_match, failed, remaining }`)
- [ ] Ist eine Mailbox beim Backfill nicht erreichbar (IMAP-Fehler, gelöschtes Postfach, geändertes Passwort seit Indexierung): betroffene Mails werden übersprungen und geloggt, Backfill läuft mit den übrigen Postfächern weiter

### Mail-Thumbnails (Lückenschluss aus PROJ-80)
- [ ] `alice-mail-sync` publiziert nach jedem erfolgreichen Weaviate-Insert eines Mail-Objekts das MQTT-Topic `alice/dms/done` mit den für den Thumbnailer nötigen Feldern (`weaviate_uuid`, `document_type: Email`, `file_type` als Text-Typ)
- [ ] `alice-dms-thumbnailer` verarbeitet Mail-Objekte über die bestehende TXT/MD-Rendering-Regel (Betreff + erste Zeilen des Mail-Bodys als gerendertes Vorschaubild), ohne neuen Konvertierungspfad
- [ ] Bereits vorhandene Mail-Objekte ohne Thumbnail werden vom bestehenden `alice-dms-thumbnailer-backfill` erfasst (Backfill listet laut PROJ-55-Spec bereits alle Collections inkl. `Email` — nach diesem Fix funktioniert das tatsächlich)

## Edge Cases

- **Mail ohne Anhang**: Kein Klassifizierungsschritt, kein Import — nur die bestehende PROJ-46-Verarbeitung (Kategorisierung, Weaviate-Metadaten) läuft.
- **Anhang exakt an der 20-KB-Bild-Müll-Grenze oder größeres Signatur-Bild**: Größenschwelle ist eine Heuristik, kein hartes Sicherheitsnetz — größere Signatur-Logos können fälschlich als `Document` importiert werden. Akzeptiertes Risiko; keine Verifikation über Bildinhalt (z.B. Logo-Erkennung) in PROJ-53.
- **LLM nicht erreichbar (Ollama down) während der Anhang-Klassifizierung**: Anhang wird nicht importiert (kein Fallback-Import ohne Klassifizierung); Fehler wird geloggt; der nächste Sync-Zyklus versucht es bei derselben Mail nicht erneut, da die Mail bereits als indexiert gilt (Message-ID-Dedup) — analog zum bestehenden PROJ-46-Verhalten bei Ollama-Ausfall (Mail wird dann als "unklassifiziert" markiert, kein Retry-Loop).
- **Zielordner nicht beschreibbar** (z.B. NAS-Berechtigung fehlerhaft trotz Vorab-Konfiguration): Fehler wird geloggt, Sync-Zyklus läuft für die übrigen Mails/Anhänge weiter; betroffener Anhang wird beim nächsten Zyklus nicht automatisch nachgeholt (Mail gilt bereits als verarbeitet).
- **Admin hat den Zielordner noch nicht in `dms_watched_folders` eingetragen**: Datei liegt auf der AI-Freigabe, wird aber vom DMS-Scanner nicht erkannt, bis der Admin den Ordner aufnimmt — kein Datenverlust, nur verzögerte Verarbeitung.
- **Admin verschiebt eine bereits importierte Datei von der AI-Freigabe in eine andere NAS-Freigabe**: Wird durch die bestehende PROJ-21/22-Lifecycle-Logik gehandhabt (Pfad wird aktualisiert bzw. bei Nichtauffindbarkeit als verwaist behandelt) — kein PROJ-53-spezifisches Verhalten nötig.
- **Sehr großer Anhang** (z.B. mehrseitiges Scan-PDF): Kein Größenlimit für den Import selbst; nachgelagerte DMS-Pipeline (Scanner/Processor/Thumbnailer) behandelt große Dateien bereits nach bestehendem Verhalten (siehe PROJ-16/55).
- **Mail-Objekt ohne extrahierbaren Body-Text** (z.B. reine HTML-Mail ohne Preview): Mail-Thumbnail zeigt nur den Betreff, analog zum bestehenden Verhalten bei sehr kurzen TXT/MD-Dateien.
- **Zwei gleichnamige Anhänge in derselben Mail** (z.B. zwei Dateien namens `Anhang.pdf`): Der zweite erhält automatisch den Kollisions-Suffix `_1` vor der Dateiendung; der erste bleibt ohne Suffix.
- **Backfill läuft nach einem vorherigen Teil-Lauf erneut**: Bereits erfolgreich importierte Anhänge (per Mail-Message-ID + Anhang-Index nachvollziehbar) werden nicht erneut heruntergeladen oder gespeichert; nur Mails ohne bisherigen Import-Versuch werden berücksichtigt.

## Technical Requirements (optional)

- Kein neues NAS-Mount/keine neue Berechtigung nötig — die Schreibrechte auf `/mnt/nas/ai` sind bereits vorbereitet (siehe Dependencies).
- Wiederverwendung bestehender Bausteine: `alice-mail-reader` (Attachment-Abruf), `SUPPORTED_EXTENSIONS`-Allowlist (PROJ-16), LLM-Klassifizierungsmuster analog PROJ-78, `alice-dms-thumbnailer` TXT/MD-Renderpfad (PROJ-55).
- Kein neuer n8n-Workflow zwingend erforderlich — Erweiterung von `alice-mail-sync` (neuer Klassifizierungs- + Speicher-Schritt pro Anhang, plus MQTT-Publish für Thumbnails) ist der naheliegende Ansatz; endgültige Workflow-Aufteilung obliegt `/architecture`.
- Kein neues Caching, keine neue Persistenzschicht — Ablage direkt auf dem NAS-Dateisystem, alles Weitere läuft über bestehende DMS-Pipeline-Zustände (Redis, Weaviate).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### E) Workflow Architecture

PROJ-53 hat keine UI-Komponente. Es erweitert zwei bestehende Bausteine (`alice-mail-sync`-Workflow, `alice-mail-reader`-Service) und fügt einen neuen manuell auslösbaren Backfill-Workflow hinzu.

#### Baustein 1: Neuer HTTP-Endpunkt in `alice-mail-reader`

Der Service kennt Mails bisher nur als Metadaten (`/fetch`) oder Volltext (`/body`) — es gibt keinen Weg, die rohen Bytes eines einzelnen Anhangs zu bekommen. Neuer Endpunkt `POST /attachment`:

- **Eingabe:** Mailbox-Zugangsdaten (wie bei `/body`), IMAP-UID der Mail, Index des gewünschten Anhangs innerhalb der Mail
- **Verhalten:** Lädt die Mail erneut per IMAP (gleiches Muster wie `/body`), läuft die MIME-Teile ab, extrahiert genau den Anhang am angegebenen Index
- **Ausgabe:** Dateiname, MIME-Typ, Größe, Anhang-Inhalt Base64-kodiert
- Die eigentliche Datei wird **nicht** vom `alice-mail-reader`-Container geschrieben — er liefert nur Bytes zurück. Das Schreiben auf die NAS-Freigabe passiert im aufrufenden n8n-Workflow, der bereits Zugriff auf `/mnt/nas/ai` hat.

#### Baustein 2: Erweiterung von `alice-mail-sync` (Laufzeit-Pfad)

Nach dem bestehenden Schritt "Process + Classify + Store Emails" (Wichtig/Werbung/Social-Media/Spam-Kategorisierung + Weaviate-Insert) kommt pro neu gespeicherter Mail mit Anhängen ein zusätzlicher Verarbeitungsblock:

1. **Anhang-Vorfilter:** Nur Anhänge mit unterstützter Dateiendung (bestehende `SUPPORTED_EXTENSIONS`-Liste) werden betrachtet; offensichtlicher Bild-Datenmüll (Bildformate < 20 KB) wird ohne Klassifizierung übersprungen.
2. **Einzel-Klassifizierung je Anhang:** Für jeden verbleibenden Anhang ein LLM-Aufruf (Ollama, gleiches Zwei-Versuch-Muster wie in der bestehenden DMS-Dokumentenklassifizierung) mit Mail-Betreff, Body-Vorschau, Dateiname und extrahiertem Textinhalt/-vorschau des Anhangs als Kontext. Ergebnis: eines der fünf Schemata oder "nicht eindeutig" → Rückfall auf `Document`.
3. **Anhang-Abruf:** Für jeden klassifizierten Anhang ein Aufruf an den neuen `alice-mail-reader`-Endpunkt `/attachment`, um die Bytes zu laden.
4. **Ablage:** Datei wird unter `/mnt/nas/ai/<Schema>/` gespeichert, Dateiname nach Muster `<Mail-Datum>_<Absender-Kurzform>_<Original-Dateiname>`, mit Kollisions-Suffix `_X` bei exaktem Namenskonflikt im Zielordner. Fehlt der Zielordner, wird er beim ersten Lauf angelegt.
5. **Fehlerverhalten:** Schlägt Klassifizierung (Ollama nicht erreichbar) oder Ablage (Zielordner nicht beschreibbar) fehl, wird der betroffene Anhang übersprungen und geloggt; die Mail selbst gilt bereits als indexiert (bestehende Message-ID-Dedup), es gibt also keinen automatischen Retry im nächsten Zyklus.

Ab hier übernimmt die bestehende, unveränderte DMS-Pipeline (Scanner → Processor → Klassifizierung/Weaviate → Thumbnailer) — vorausgesetzt, der Admin hat den Zielordner in `alice.dms_watched_folders` eingetragen.

Zusätzlich publiziert `alice-mail-sync` nach jedem erfolgreichen Weaviate-Insert eines `Email`-Objekts das MQTT-Topic `alice/dms/done` (mit `weaviate_uuid`, `document_type: Email`, `file_type` als Text-Typ), damit `alice-dms-thumbnailer` — unverändert, über den bestehenden TXT/MD-Renderpfad — ein Vorschaubild aus Betreff + Body-Anfang erzeugt. Das ist die in PROJ-80 entdeckte Lücke: Bisher passiert dieser Publish-Schritt schlicht nicht.

#### Baustein 3: Neuer Workflow `alice-mail-attachment-backfill`

Analog zu `alice-dms-thumbnailer-backfill` — manuell per Webhook ausgelöst:

- **Trigger:** Webhook `POST /attachment-backfill`
- **Ablauf:** Listet alle `Email`-Objekte in Weaviate mit mindestens einem Eintrag in `attachments`, für die noch kein Anhang-Import erfolgt ist → verarbeitet Postfächer/Mails batchweise → kontaktiert je betroffener Mail erneut `alice-mail-reader` (IMAP) → nutzt dieselbe Klassifizierungs- und Ablagelogik wie der Laufzeit-Pfad (Schritt 1–4 oben)
- **Fortschritt:** `{ processed, imported, skipped_no_match, failed, remaining }` im n8n-Execution-Log
- **Fehlerverhalten:** Nicht erreichbare Postfächer (IMAP-Fehler, gelöschtes Postfach, geändertes Passwort) werden übersprungen und geloggt; Backfill läuft mit den übrigen Postfächern weiter
- **Wiederholbarkeit:** Bereits importierte Anhänge (nachvollziehbar über Mail-Message-ID + Anhang-Index) werden bei einem erneuten Lauf nicht erneut heruntergeladen

Da PROJ-53 keinen neuen Persistenzmechanismus einführt (siehe Spec, Technical Requirements), muss der Backfill-Workflow den "bereits importiert"-Zustand aus vorhandenen Daten ableiten (z.B. Abgleich vorhandener Dateien im Zielordner anhand des generierten Dateinamensmusters) statt aus einer neuen Tracking-Tabelle.

### Datenmodell (fachlich)

Kein neues Datenbankschema. Betroffene bestehende Strukturen:

- **Dateisystem** `/mnt/nas/ai/<Invoice|BankStatement|Document|Contract|SecuritySettlement>/`: neue Ablageziele, angelegt beim ersten Bedarf
- **`alice.dms_watched_folders`**: Admin trägt die neuen Ordner manuell ein (kein automatischer Eintrag durch PROJ-53)
- **Weaviate `Email`-Collection**: keine Schemaänderung; PROJ-53 nutzt das bereits vorhandene `attachments`-Feld nur lesend, um zu bestimmen, welche Mails Anhänge haben

### Tech-Entscheidungen (Begründung)

- **Erweiterung von `alice-mail-sync` statt neuer eigenständiger Workflow für den Laufzeit-Pfad:** Die Anhang-Verarbeitung hängt direkt am "neue Mail gefunden"-Ereignis, das bereits in `alice-mail-sync` existiert. Ein separater Workflow bräuchte einen eigenen Trigger-Mechanismus und würde die Message-ID-Dedup duplizieren.
- **Neuer `/attachment`-Endpoint statt Erweiterung von `/fetch`:** Anhang-Bytes werden nur für tatsächlich DMS-relevante Anhänge einzeln benötigt (nach Vorfilter + Klassifizierung). Sie in jede `/fetch`-Antwort einzubetten würde die Antwortgröße für alle Mails aufblähen, auch wenn kein Import stattfindet, und den bestehenden `/fetch`-Contract für andere Aufrufer (z.B. `alice-mail-tools`) verändern.
- **Eigenständiger Backfill-Workflow statt Wiederverwendung des Laufzeit-Pfads:** Gleiches Muster wie `alice-dms-thumbnailer-backfill` — Backfill braucht eigene Paginierung/Batch-Steuerung über bereits indexierte Weaviate-Objekte statt über neu ankommende IMAP-UIDs.
- **Kollisionserkennung über Dateinamen statt neuer Tracking-Tabelle:** Konsistent mit der bestehenden Projektentscheidung, keine neue Persistenzschicht einzuführen; das deterministische Dateinamensmuster macht sowohl Laufzeit-Dedup als auch Backfill-Wiederholbarkeit ohne zusätzlichen State möglich.

### Dependencies (Pakete)

Keine neuen Pakete — `alice-mail-reader` nutzt bereits `imaplib`/`email` (Python Standard Library) für MIME-Parsing; `alice-mail-sync` nutzt bereits `axios` und Node.js `fs` (analog `alice-dms-path-worker`) für Datei-Ablage.

### Implementation Notes (Backend, 2026-08-22)

Umgesetzt wurden alle drei Bausteine. Backend-only — PROJ-53 hat keine UI-Komponente, daher keine API-Routes/Frontend/Vitest-Schritte.

**Baustein 1 — `alice-mail-reader` (`docker/compose/automations/alice-mail-reader/app.py`)**

- Neuer Endpunkt `POST /attachment` (Eingabe wie `/body` + `attachment_index`), Ausgabe `{ filename, mime_type, size_bytes, content_base64 }`. 404 `{"error": "Anhang nicht gefunden"}` bei unbekanntem Index, `imaplib.IMAP4.error` → 400, generisch → 500 + `log.exception` (identisch zum Stil von `/body`).
- **Abweichung (Refactoring):** Das MIME-Part-Walking wurde in einen gemeinsamen Generator `_walk_attachment_parts()` extrahiert, den jetzt sowohl `_get_attachments()` (für `/fetch`) als auch `/attachment` nutzen. Grund: `attachment_index` muss garantiert denselben Part treffen, den `/fetch` an derselben Position gemeldet hat — zwei getrennte Walk-Implementierungen könnten auseinanderlaufen. `/fetch` und `/body` behalten ihren Contract unverändert.
- Modul-Docstring-Endpunktliste ergänzt.

**Baustein 2 — `alice-mail-sync` (`workflows/alice-mail-sync.json`)**

- `Process + Classify + Store Emails` gibt jetzt zusätzlich `storedEmails[]` zurück (nur tatsächlich neu in Weaviate eingefügte Mails, inkl. `weaviate_uuid` aus der Insert-Response, Anhang-Metadaten und Body-Preview). Bestehende Felder (`processed`, `wichtig`, `maxUid`) unverändert — `PG: Update Sync Status` und der Notification-Zweig laufen wie bisher.
- Neuer Code-Node `Code: Import Attachments`: Vorfilter (`SUPPORTED_EXTENSIONS` exakt aus `alice-dms-path-worker`; Bild-Müll = Bild-MIME/-Endung **und** < 20480 Bytes → stilles Überspringen ohne Klassifizierung/Fehler-Log) → Klassifizierung → `/attachment`-Abruf → Ablage unter `/mnt/nas/ai/<Schema>/`, Zielordner via `fs.mkdirSync(recursive)`. Dateiname `<YYYY-MM-DD>_<Absender-Kurzform>_<Original>`, `_N` nur bei echter Kollision (Suffix vor der Endung). Fehler bei Klassifizierung/Abruf/Schreiben → nur dieser Anhang wird übersprungen und geloggt, Schleife läuft weiter.
- **Abweichung (MQTT pro Mail):** Der MQTT-Node kann nicht aus einem Code-Node heraus aufgerufen werden. Statt eines Split-Nodes gibt `Code: Split Stored Emails` ein Item pro gespeicherter Mail zurück; n8n führt den nachgelagerten `MQTT: Publish Email Done` dadurch einmal pro Item aus. Das entspricht dem etablierten Muster aus `alice-dms-processor` (`Code: Process Image Item` → `IF: Image Is New` → `MQTT: Publish Image Done`). Payload: `{ weaviate_uuid, document_type: 'Email', file_type: 'txt', inserted: true, timestamp }`, qos 1, Credential `mqtt-alice`. Mails ohne UUID werden ausgefiltert.
- Der Anhang-Zweig hängt als **erster** Ausgang an `Process + Classify + Store Emails`; der Notification-/Status-Zweig ist unverändert der zweite Ausgang, sodass der Mailbox-Loop weiterläuft.

**Baustein 3 — `alice-mail-attachment-backfill` (`workflows/alice-mail-attachment-backfill.json`, neu)**

- Struktur 1:1 nach `alice-dms-classification-backfill`: Webhook `POST /alice-mail-attachment-backfill` → Lock-Acquire (**derselbe** Key `alice:dms:processor:lock:run` wie `alice-dms-processor`, damit nie parallel zum Processor auf der GPU klassifiziert wird) → Init → Mailbox-Credentials laden → Weaviate-Query → `Split In Batches` mit Time-Check/Lock-Renew → Import → Progress → Summary → Respond.
- "Bereits importiert" wird ohne Tracking-Tabelle aus dem deterministischen Dateinamen abgeleitet: existiert der Basisname (oder eine `_1…_20`-Variante) in **einem** der fünf Schema-Ordner, gilt der Anhang als erledigt. Mails, deren Anhänge alle nur Bild-Müll/nicht unterstützt sind, zählen ebenfalls als erledigt — sonst wären sie dauerhaft "pending".
- Anhang-Metadaten stehen in Weaviate nur als Anzeige-String (`name (mime, N bytes)`); der Backfill parst diesen zurück und behält den **ursprünglichen Index**, da `/attachment` per Absolutindex adressiert.
- Mailbox-Credentials kommen aus `alice.imap_mailboxes` (dieselbe Quelle wie `alice-mail-sync`), werden einmal pro Lauf in einen Redis-Hash gelegt und pro Mail daraus gelesen. `password_enc` bleibt durchgehend verschlüsselt — entschlüsseln kann nur `alice-mail-reader`.
- Nicht erreichbare Mailbox (IMAP-Fehler/gelöscht/Passwort geändert) → Mail wird übersprungen und geloggt, Lauf geht mit den übrigen weiter. Fortschritts-Log `{ processed, imported, skipped_no_match, failed, remaining }`.

**Abweichung — Text-Extraktion für Nicht-Plaintext-Anhänge (wichtig für Review)**

Der Tech-Design-Punkt "extrahierter Textinhalt/-vorschau des Anhangs" ist nur für `.txt`/`.md` vollständig umgesetzt (direktes UTF-8-Dekodieren der Bytes). Für PDF/DOCX/XLSX/Bilder gibt es **keinen** wiederverwendbaren synchronen Extraktor: `dms-extractor-pdf|office|ocr|image` sind MQTT/Redis-getriebene Worker, die Dateipfade aus einer Queue lesen und Plaintext asynchron nach Redis schreiben — kein HTTP-Endpunkt, den ein Code-Node synchron aufrufen könnte. Da die Spec explizit keine neue Infrastruktur will, klassifiziert das LLM diese Typen aus **Dateiname + Mail-Betreff + Absender + Body-Preview**; der Prompt weist das Modell mit `(no extractable text - classify from filename and email context)` ausdrücklich darauf hin. Praktische Folge: bei nichtssagenden Dateinamen (z.B. `Anhang.pdf` ohne Kontext im Betreff) ist die Trefferquote schlechter als bei der DMS-Klassifizierung nach Volltext-Extraktion — der `Document`-Fallback fängt das ab, und die nachgelagerte DMS-Pipeline klassifiziert die Datei nach dem Scan ohnehin noch einmal anhand des extrahierten Volltexts. Eine echte Verbesserung würde einen synchronen Extraktor-Endpunkt erfordern (eigenes Feature).

**Weitere Abweichungen / Hinweise**

- Klassifizierung nutzt das Zwei-Versuch-Muster aus PROJ-78 (temp 0, dann temp 0.3) *inline* statt via `Execute: Classify Document`-Sub-Workflow. Grund: Das Sub-Workflow nimmt nur `{ plaintext }` entgegen und kennt die Typen `Email`/`BankTransaction`, die als Anhang-Ziel unzulässig sind; PROJ-53 braucht Mail-Kontext + Dateiname im Prompt und nur die fünf erlaubten Schemata. Der Sub-Workflow-Contract wurde bewusst nicht geändert, um `alice-dms-processor` und `alice-dms-classification-backfill` nicht zu beeinflussen.
- Unterscheidung "Ollama nicht erreichbar" (→ kein Import, `failed`) vs. "LLM antwortet, aber unklar" (→ `Document`-Fallback, Import) ist implementiert, wie in Spec/Edge Cases gefordert.
- Dateinamen werden saniert (Pfadtrenner/Steuerzeichen/führende Punkte), sodass ein bösartiger Anhangname nicht aus dem Zielordner ausbrechen kann.
- `nas-volumes.yml` gewährt `nas-base` bereits `rw` auf `/mnt/nas/ai`, und der n8n-Container erbt das per `extends` — keine Compose-Änderung nötig. `fs`/`path` sind über `NODE_FUNCTION_ALLOW_BUILTIN` freigegeben.

**Verifikation**

- `app.py`: Syntax-Check + Test, der beweist, dass `attachment_index` bei einer echten Multipart-Mail exakt den Anhang trifft, den `/fetch` an derselben Position meldet (inkl. 404 bei Index out of range).
- Anhang-Logik (Vorfilter inkl. 20-KB-Grenzfälle, Absender-Kurzform, Datumsstempel, Kollisions-Suffix gegen ein echtes Dateisystem, Klassifizierungs-Parsing, Pfad-Traversal): 32 Assertions, alle grün.
- Round-Trip-Test des Weaviate-Anhang-Strings (auch bei Klammern im Dateinamen).
- Beide Workflow-JSONs strukturell validiert: gültiges JSON, eindeutige Node-Namen/IDs, alle Connection-Referenzen und `$('Node')`-Referenzen existieren, keine verwaisten Nodes, alle Code-Nodes syntaktisch gültig, kein `console.log`, Credentials auf Postgres-/MQTT-Nodes gesetzt, nur erlaubte `require`-Module.
- **Nicht verifiziert:** kein Lauf gegen echtes n8n/IMAP/Ollama/Weaviate/NAS. Die `mcp__n8n-mcp__*`-Tools waren in dieser Session nicht verfügbar, daher wurde statt `n8n_validate_workflow` die oben beschriebene strukturelle Eigenvalidierung genutzt. Deployment erfolgt manuell durch den Admin.

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
