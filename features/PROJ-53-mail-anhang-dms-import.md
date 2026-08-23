# PROJ-53: Mail-Anhang DMS-Import

## Status: Planned
**Created:** 2026-08-22
**Last Updated:** 2026-08-23

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
- [ ] Für jedes der relevanten DMS-Schemata existiert ein fester Unterordner in `/mnt/nas/ai/`, benannt nach dem Weaviate-Klassennamen: `Invoice/`, `BankStatement/`, `Document/`, `Contract/`, `SecuritySettlement/`, sowie zusätzlich `Video/` und `Audio/` für extensionbasiert geroutete Medien (siehe unten)
- [ ] Fehlt einer dieser Ordner beim ersten Sync-Lauf, wird er automatisch angelegt
- [ ] Die Ordner sind reine Ablageziele der Mail-Pipeline; die Aufnahme in `alice.dms_watched_folders` (inkl. Zuordnung zum passenden deutschen `suggested_type`-Wert) erfolgt manuell durch den Admin — kein automatischer DB-Eintrag durch PROJ-53

### Anhang-Erkennung & Klassifizierung (Erweiterung von `alice-mail-sync`)
- [ ] Für jede neu indexierte Mail mit mindestens einem Anhang wird ein zusätzlicher Klassifizierungsschritt ausgeführt, unabhängig von der bestehenden Wichtig/Werbung/Social-Media/Spam-Kategorisierung aus PROJ-46
- [ ] Nur Anhänge mit einer Dateiendung aus der `SUPPORTED_EXTENSIONS`-Allowlist werden berücksichtigt; die Liste bleibt zentral erweiterbar
- [ ] Offensichtlicher Bild-Datenmüll (typische E-Mail-Signatur-Icons/Logos: Bildformate < 20 KB) wird ohne Klassifizierungsversuch übersprungen — kein Import
- [ ] **Bild-, Video- und Audio-Anhänge (jenseits der 20-KB-Müll-Grenze) werden rein anhand der Dateiendung geroutet — kein LLM-Aufruf.** Bilder (JPG, JPEG, PNG, WEBP, HEIC, TIF, TIFF) → `Document/` (unverändert, wie bisher); neu: Video-Endungen (u.a. MP4, MOV, AVI, MKV, WEBM) → `Video/`; Audio-Endungen (u.a. MP3, WAV, M4A, OGG, FLAC) → `Audio/`. Für diese Formate ist eine inhaltliche Prüfung nicht erforderlich und nicht vorgesehen.
- [ ] Für Text-basierte DMS-Kandidaten (PDF, DOCX, XLSX, ODT, ODS, TXT, MD) wird jeder verbleibende Anhang **einzeln** vom LLM (Ollama/qwen3) klassifiziert — Eingabe: Mail-Betreff + Body-Preview als Kontext, plus Dateiname und extrahierter Textinhalt des jeweiligen Anhangs:
  - **PDF**: Volltext wird synchron im Workflow extrahiert (gleiche Technik wie `dms-extractor-pdf`, `pdf-parse`, aber ohne Umweg über MQTT/Redis) und vollständig (bis zur bestehenden Prompt-Längenbegrenzung) an den Klassifizierungs-Prompt übergeben — nicht nur ein Textextrakt/Preview.
  - **DOCX/XLSX/ODT/ODS**: Es gibt (noch) keinen synchronen Extraktor für Office-Formate (`dms-extractor-office` läuft asynchron über LibreOffice headless). Diese Anhänge werden bis auf Weiteres nur anhand von Dateiname + Mail-Betreff + Absender + Body-Preview klassifiziert (kein Volltext) — bewusste Einschränkung, siehe PROJ-91 für die geplante Schließung dieser Lücke.
  - **TXT/MD**: Volltext wird wie bisher direkt dekodiert und übergeben.
- [ ] Das LLM ordnet jeden Text-Anhang einem der fünf Schemata zu (Invoice, BankStatement, Document, Contract, SecuritySettlement) oder markiert ihn als nicht eindeutig zuordenbar
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
- [ ] **Der Backfill hat einen Vorschau-Modus (Dry-Run) als Standardverhalten** — analog zum `confirm`-Parameter aus `alice-dms-language-backfill`: Ohne `confirm: true` im Request-Body (bzw. Query-Parameter) werden Kandidaten ermittelt und gezählt, aber **keine** IMAP-Anhänge abgerufen und **keine** Dateien auf dem NAS geschrieben — die Response liefert nur die Anzahl der Kandidaten (`{ candidates_found, dry_run: true }`). Erst ein Aufruf mit `confirm: true` (bzw. `?confirm=true`) führt den Import tatsächlich aus.
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
- **Video-/Audio-Anhänge**: `Video/` und `Audio/` sind reine Ablageordner auf der AI-Freigabe, **kein** Weaviate-Schema (anders als Invoice/BankStatement/Document/Contract/SecuritySettitlement). Nimmt der Admin diese Ordner in `alice.dms_watched_folders` auf, laufen sie durch den generischen DMS-Scanner, aber ohne ein passendes Klassifizierungsschema landen sie dort nach bestehendem DMS-Verhalten (siehe PROJ-16) vermutlich im `Document`-Fallback oder werden vom Scanner ignoriert, je nach aktueller Handhabung nicht unterstützter Medientypen — PROJ-53 selbst greift hier nicht ein, das Ablageverhalten der nachgelagerten Pipeline für diese zwei neuen Ordner ist vom Admin zu prüfen, bevor er sie einträgt.
- **Backfill-Dry-Run ohne `confirm`**: Ein Aufruf ohne den `confirm`-Parameter verändert nichts (keine IMAP-Verbindung, kein NAS-Write) und ist beliebig oft wiederholbar, um die Anzahl betroffener Mails vorab zu sehen.

## Technical Requirements (optional)

- Kein neues NAS-Mount/keine neue Berechtigung nötig — die Schreibrechte auf `/mnt/nas/ai` sind bereits vorbereitet (siehe Dependencies).
- Wiederverwendung bestehender Bausteine: `alice-mail-reader` (Attachment-Abruf), `SUPPORTED_EXTENSIONS`-Allowlist (PROJ-16, für diesen Workflow um Video-/Audio-Endungen erweitert), LLM-Klassifizierungsmuster analog PROJ-78, `alice-dms-thumbnailer` TXT/MD-Renderpfad (PROJ-55), PDF-Textextraktion analog `dms-extractor-pdf` (`pdf-parse`), aber synchron statt über MQTT/Redis.
- Kein neuer n8n-Workflow zwingend erforderlich — Erweiterung von `alice-mail-sync` (neuer Klassifizierungs- + Speicher-Schritt pro Anhang, plus MQTT-Publish für Thumbnails) ist der naheliegende Ansatz; endgültige Workflow-Aufteilung obliegt `/architecture`.
- Kein neues Caching, keine neue Persistenzschicht — Ablage direkt auf dem NAS-Dateisystem, alles Weitere läuft über bestehende DMS-Pipeline-Zustände (Redis, Weaviate).
- Office-Formate (DOCX/XLSX/ODT/ODS) bleiben ohne Volltext-Klassifizierung, da kein synchroner Extraktor existiert (siehe PROJ-91 für die geplante Schließung dieser Lücke) — kein neuer HTTP-Wrapper-Service wird im Rahmen von PROJ-53 gebaut.

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
- Der Anhang-Zweig und der Notification-/Status-Zweig hängen **beide am selben Ausgang (Index 0)** von `Process + Classify + Store Emails` als parallele Zweige. n8n arbeitet parallele Zweige desselben Outputs sequenziell in Listenreihenfolge ab, und `Code: Import Attachments` steht in dieser Liste **vor** `Notify: Passthrough` — der Anhang-Import läuft also **vor** dem Status-Reset durch `PG: Update Sync Status`. Bei mehreren großen Anhängen kann eine Mailbox dadurch länger auf `syncing` stehen. (Korrigiert nach QA-BUG-6: eine frühere Fassung dieser Notiz sprach fälschlich von "erstem"/"zweitem Ausgang".)

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

### Bugfixes nach QA-Runde 1 (2026-08-22)

Behoben wurden die beiden Medium-Bugs aus dem QA-Bericht zu Commit `63636f8`. BUG-1/4/5 bleiben bewusst offen (als Nice-to-have bzw. Folge-Feature bewertet), BUG-6 war ein Doku-Fehler und ist oben korrigiert.

**BUG-2 — False-Positive-Dedup im Backfill (`Code: Fetch Mails With Attachments`)**

Die alte `alreadyOnDisk(baseName)`-Prüfung war ein Boolean pro Mail: existiert der Basisname oder eine `_1…_20`-Variante irgendwo, galt der Anhang als erledigt. Da der Basisname weder Message-ID noch Anhang-Index enthält, kollidierten fachlich verschiedene Anhänge auf demselben Schlüssel.

Ersetzt durch eine **zählende, global abgeglichene** Logik:

1. `countOnDisk(baseName)` zählt, **wie viele** Dateien zu einem Basisnamen existieren (exakter Name + zusammenhängender `_1.._N`-Lauf) statt nur "mindestens eine". Die Suche läuft bis zur ersten Lücke und hat **keinen Deckel mehr** — der alte Stopp bei `_20` stand im Widerspruch zu `resolveCollision()`, das bis 999 zählt (BUG-2c: ab `_21` wurde bei jedem Lauf erneut importiert).
2. Der Abgleich passiert nicht mehr pro Mail, sondern in einem **zweiten Pass über alle Mails gemeinsam**: Alle Anhänge, die auf denselben Basisnamen abbilden, werden gepoolt; die ersten `countOnDisk(base)` Ansprüche gelten als erfüllt, jeder weitere bleibt pending. Genau diese "überzähligen" Ansprüche schreibt `resolveCollision()` anschließend als `_N`.

Der Node ist dafür in zwei Phasen geteilt (Pass 1 sammelt alle Kandidaten-Mails, Pass 2 gleicht ab und baut die Pending-Liste). Warum global statt pro Mail: Der Basisname trägt keine Mail-Identität, deshalb teilen sich zwei verschiedene Mails desselben Absenders vom selben Tag mit gleichem Anhangnamen einen Schlüssel — beurteilt man jede Mail isoliert, sieht die zweite immer schon erledigt aus (BUG-2b). Der Dateiname selbst bleibt unverändert, weil AC-3.2 und EC-9 das Muster `<Datum>_<Absender>_<Original>` bzw. das nackte `_1`-Suffix exakt vorschreiben — eine Message-ID im Dateinamen hätte diese Kriterien verletzt. Sortierung nach (Mail-Reihenfolge, `attachment_index`) hält Wiederholungsläufe reproduzierbar.

**BUG-3 — Kein Größenlimit vor dem Base64-Roundtrip**

Neue Obergrenze `ATTACHMENT_MAX_BYTES = 52428800` (50 MB), geprüft im bestehenden Vorfilter anhand des bereits aus `/fetch` vorliegenden `size_bytes` — also **bevor** `/attachment` überhaupt aufgerufen wird, ohne Zusatz-Request. Greift an drei Stellen: Laufzeit-Vorfilter (`prefilterAttachment`, neuer Grund `too_large`), Backfill-Kandidatenermittlung (`isImportCandidate`) und als zweite Absicherung im Backfill-Import-Node, dessen Kandidatenliste aus einem anderen Node stammt.

Zur Wahl von 50 MB: Eine projektweite Reject-Obergrenze existiert nicht. `alice-dms-path-worker` kennt nur `file_size > 104857600` (100 MB) und stuft solche Dateien lediglich auf `priority: 'low'` herunter, lehnt sie also nicht ab — als Limit nicht übertragbar, weil die DMS-Pipeline **dateibasiert** arbeitet. Der PROJ-53-Pfad ist dagegen neu und speicherbasiert: Ein Anhang liegt gleichzeitig als Base64-String (~1,33×) **und** als Buffer im n8n-Heap, zusätzlich als komplette RFC822-Mail im Python-Container. Da n8n von allen Workflows geteilt wird, träfe ein OOM nicht nur diesen Import. 50 MB deckt reale Rechnungen/Kontoauszüge/Scans ab und hält den Spitzenbedarf pro Anhang im dreistelligen MB-Bereich. Anders als Bild-Müll wird ein zu großer Anhang **geloggt** (`skipped_too_large` in den Stats), weil es sich um ein potenziell relevantes Dokument handelt, das bewusst abgelehnt wird — der Admin soll das sehen. Abweichung zu EC-7 ("kein Größenlimit für den Import selbst"): bewusst, da EC-7 auf das dateibasierte Verhalten der nachgelagerten Pipeline verweist, das für diesen Speicherpfad nicht gilt.

**Verifikation der Fixes**

- 23 Assertions gegen ein echtes Dateisystem für die neue Dedup-Logik (alle drei BUG-2-Teilfälle, Idempotenz über drei aufeinanderfolgende Läufe, gemischte Basisnamen, Reihenfolge-Erhalt, Lücken-Erkennung).
- 11 Assertions gegen den **tatsächlich im Workflow-JSON eingebetteten** Code: Die Helper und der Reconcile-Block wurden aus `alice-mail-attachment-backfill.json` extrahiert und mit QA's Repro-Schritten ausgeführt (u.a. QA-Szenario "zwei `Rechnung.pdf` in einer Mail" → erwartet `…Rechnung.pdf` + `…Rechnung_1.pdf`, tatsächlich genau das; Wiederholungslauf ohne Neuschreiben; 25 Dateien jenseits des alten `_20`-Deckels ohne Duplikat).
- 8 Assertions für das Größenlimit inkl. Grenzwerte (exakt 50 MB akzeptiert, +1 Byte abgelehnt, QA's 200-MB-Szenario abgelehnt, Prüfreihenfolge gegenüber `image_junk`/`unsupported_extension` erhalten).
- Bestehende 32 Assertions und der `/attachment`-Indextest erneut grün (keine Regression); beide Workflows erneut strukturell validiert (0 Fehler).

## QA Test Results

**Tested:** 2026-08-22
**Tester:** QA Engineer (AI)
**Test method:** Static/logic review + isolated Node.js re-execution of extracted Code-Node helpers. **Keine Live-Ausführung** — kein Zugriff auf n8n/IMAP/Ollama/Weaviate/NAS in dieser Umgebung. Alle Kriterien, die eine echte Pipeline-Ausführung erfordern, sind als `NOT VERIFIABLE` markiert und müssen beim Deployment nachgeprüft werden.
**Commit under test:** `63636f8` (Erstprüfung) → **`99fb7c2` (Nachprüfung der Fixes für BUG-2/BUG-3, siehe Abschnitt "Re-Test").**

### Acceptance Criteria Status

#### AC-1: Zielordner-Struktur

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 1.1 | Fester Unterordner je Schema in `/mnt/nas/ai/` | PASS | `Code: Import Attachments`: `NAS_AI_ROOT='/mnt/nas/ai'`, `VALID_SCHEMAS=['Invoice','BankStatement','Document','Contract','SecuritySettlement']`, `targetDir = path.join(NAS_AI_ROOT, classification.document_type)` |
| 1.2 | Fehlender Ordner wird automatisch angelegt | PASS | `fs.mkdirSync(targetDir, { recursive: true })` in beiden Import-Nodes, Fehler → `failed++` + Log statt Abbruch |
| 1.3 | Kein automatischer `dms_watched_folders`-Eintrag | PASS | Keine Postgres-Writes auf `dms_watched_folders` in beiden Workflows (nur `SELECT` auf `alice.imap_mailboxes` im Backfill) |

#### AC-2: Anhang-Erkennung & Klassifizierung

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 2.1 | Zusätzlicher Klassifizierungsschritt, unabhängig von PROJ-46-Kategorie | PASS | Neuer Node `Code: Import Attachments` hängt an `Process + Classify + Store Emails`; `category` wird im Import-Pfad nirgends gelesen |
| 2.2 | Nur Endungen aus `SUPPORTED_EXTENSIONS` | PASS | `prefilterAttachment()`: `if (!SUPPORTED_EXTENSIONS.has(ext)) return { keep:false, reason:'unsupported_extension' }`. Liste stimmt mit `alice-dms-path-worker` überein. **Einschränkung siehe BUG-5** (Liste dupliziert, nicht zentral) |
| 2.3 | Bild-Datenmüll < 20 KB ohne Klassifizierungsversuch übersprungen | PASS | `prefilterAttachment()` läuft als **erste** Anweisung im `try`-Block, vor `/attachment`-Fetch und vor `classifyAttachment()`. Prüft **beides**: `(IMAGE_EXTENSIONS.has(ext) \|\| mime.startsWith('image/')) && size_bytes < 20480` |
| 2.4 | Jeder Anhang **einzeln** vom LLM klassifiziert | PASS | `for (let idx=0; idx<attachments.length; idx++)` → ein `classifyAttachment()`-Aufruf je Anhang |
| 2.5 | Eingabe: Betreff + Body-Preview + Dateiname + Textinhalt | **PARTIAL** | `buildClassificationPrompt()` liefert Subject/Sender/Body-Preview/Filename. Echter Anhangstext nur für `.txt`/`.md` — siehe BUG-4 (dokumentierte Abweichung) |
| 2.6 | Zuordnung zu einem der 5 Schemata oder "nicht eindeutig" | PASS | `parseClassification()` akzeptiert nur `VALID_SCHEMAS` + `'unclear'`; alles andere → `null` |
| 2.7 | Nicht eindeutig → Fallback `Document` | PASS | `classifyAttachment()`: `if (!result \|\| result.document_type === 'unclear') return { document_type:'Document', fallback:true }` |
| 2.8 | Mehrere Anhänge unterschiedlicher Zuordnung → je eigener Zielordner | PASS | `targetDir` wird **pro Anhang** innerhalb der Schleife aus dessen eigener `classification` gebildet |

#### AC-3: Datei-Ablage

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 3.1 | Anhang wird per `alice-mail-reader` live nachgeladen | PASS | `axios.post('http://alice-mail-reader:8007/attachment', {...})` mit `uid` + `attachment_index` |
| 3.2 | Dateiname `<YYYY-MM-DD>_<Absender-Kurzform>_<Original>` | PASS | `buildBaseFilename()` = `mailDateStamp()` + `shortenSender()` + `sanitizeFilename()`. Ungültiges Datum → `unknown-date`; leerer Absender → `unknown` |
| 3.3 | Kollisions-Suffix `_X` nur bei echter Kollision | PASS | `resolveCollision()` gibt `baseName` unverändert zurück, wenn keine Datei existiert. Re-Test: 5× gleicher Name → `Anhang.pdf, Anhang_1.pdf, Anhang_2.pdf, Anhang_3.pdf, Anhang_4.pdf`, keine Überschreibung, Suffix vor der Endung. Schleife endet bei 1000, danach `_<Date.now()>` → **kein Endlosloop** |
| 3.4 | Import unabhängig von der Mail-Kategorie | PASS | Siehe 2.1 — kein Kategorie-Filter im Import-Zweig |
| 3.5 | Nachgelagerte DMS-Pipeline unverändert | PASS | Keine Änderungen an `alice-dms-processor` / `alice-dms-scanner` / `alice-dms-thumbnailer` im Commit (`git show 63636f8 --stat`: nur `app.py`, 2 Workflows, 2 Doku-Dateien) |
| 3.6 | Erneuter Sync-Lauf → keine doppelte Ablage | PASS | `storedEmails.push()` steht **nach** `if (alreadyExists) continue;` und **nach** dem erfolgreichen Weaviate-Insert → bereits indexierte Mails erreichen den Import-Zweig nicht. Zusätzlich BUG-2 beachten |

#### AC-4: Backfill

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 4.1 | Manuell auslösbarer Workflow existiert | PASS | `workflows/alice-mail-attachment-backfill.json`, Webhook `POST /alice-mail-attachment-backfill`, `responseMode: responseNode` |
| 4.2 | Listet `Email`-Objekte mit Anhängen ohne bisherigen Import | PASS (mit BUG-2) | `Code: Fetch Mails With Attachments`: GraphQL-Paginierung à 100, `rawAtt.length === 0 → continue`, dann `alreadyOnDisk()`-Filter |
| 4.3 | Pro Mail erneut IMAP via `alice-mail-reader` | PASS | `Code: Import Mail Attachments` → `/attachment` mit `mailbox.*` aus dem Redis-Cache |
| 4.4 | Dieselbe Klassifizierungs-/Ablage-Logik | PASS (mit BUG-5) | Helper-Funktionen sind byte-identisch dupliziert (`shortenSender`, `mailDateStamp`, `sanitizeFilename`, `buildBaseFilename`, `resolveCollision`, `buildClassificationPrompt`, `parseClassification`, `classifyAttachment`) — verhaltensgleich, aber per Copy-Paste |
| 4.5 | Batches, unterbrechbar/neustartbar ohne Doppel-Import | **PARTIAL** | `Split In Batches` + Time-Check (7200 s) + Lock-Renew vorhanden. Resumability ist aber **nur approximativ** — siehe BUG-1 und BUG-2 |
| 4.6 | Fortschritts-Log `{processed, imported, skipped_no_match, failed, remaining}` | PASS | `Code: Track Progress` loggt exakt diese 5 Felder via winston; Redis-Hash `alice:mail:backfill:run:stats` |
| 4.7 | Nicht erreichbare Mailbox → überspringen + loggen, Lauf geht weiter | PASS | Fehlender Redis-Eintrag → `result:'mailbox_unreachable'`, Return statt Throw. Im Fetch-Catch: `status===400 \|\| !e.response` → `mailboxUnreachable=true; break` (nur diese Mail), Workflow läuft über `Track Progress` → `Split In Batches` weiter |

#### AC-5: Mail-Thumbnails

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 5.1 | MQTT `alice/dms/done` nach jedem erfolgreichen Weaviate-Insert | PASS | `Code: Split Stored Emails` → `IF: Has Stored Emails` → `MQTT: Publish Email Done`, Topic `alice/dms/done`, qos 1, Payload `{weaviate_uuid, document_type:'Email', file_type:'txt', inserted:true, timestamp}`. Feuert **nur für echte Neu-Inserts** (siehe 3.6) und nur bei vorhandener UUID (`.filter(m => m.weaviate_uuid)`) |
| 5.2 | Thumbnailer verarbeitet Mails über bestehende TXT/MD-Regel | NOT VERIFIABLE | `file_type:'txt'` ist plausibel gesetzt, aber `alice-dms-thumbnailer` wurde nicht ausgeführt. Beim Deployment prüfen |
| 5.3 | Bestehende Mails ohne Thumbnail via `alice-dms-thumbnailer-backfill` | NOT VERIFIABLE | Kein Code in diesem Commit; hängt an 5.2 |

### Edge Cases Status

| # | Edge Case | Status | Anmerkung |
|---|-----------|--------|-----------|
| EC-1 | Mail ohne Anhang | PASS | `if (attachments.length === 0) continue;` |
| EC-2 | Anhang an der 20-KB-Grenze | PASS | `< 20480` — exakt 20480 Bytes wird importiert. Als akzeptiertes Risiko in der Spec dokumentiert |
| EC-3 | Ollama down während Klassifizierung | PASS | `classifyAttachment()` gibt `null` zurück, wenn beide Versuche mit Nicht-`SyntaxError` fehlschlagen → `failed++`, kein Blind-Import |
| EC-4 | Zielordner nicht beschreibbar | PASS | `mkdirSync`- und `writeFileSync`-Fehler separat gefangen → `failed++` + Log, Schleife läuft weiter |
| EC-5 | Ordner nicht in `dms_watched_folders` | PASS | Kein Code-Pfad; Datei liegt auf NAS |
| EC-6 | Datei verschoben (PROJ-21/22) | PASS | Nicht berührt |
| EC-7 | Sehr großer Anhang | **RISIKO** | Kein Größenlimit — siehe BUG-3 (Memory/Base64) |
| EC-8 | Mail ohne Body-Text | PASS | `String(mail.body_preview \|\| '')` |
| EC-9 | Zwei gleichnamige Anhänge in derselben Mail | PASS (Laufzeit) / **FAIL (Backfill)** | Laufzeit korrekt (`_1`). Backfill: siehe BUG-2 |
| EC-10 | Backfill nach Teil-Lauf | **PARTIAL** | Siehe BUG-1/BUG-2 |

### Security Audit Results

**n8n workflow features:**
- [x] **Path Traversal neutralisiert** — `sanitizeFilename()` ersetzt `/` und `\`, entfernt `\x00-\x1f`, strippt führende Punkte. Verifiziert mit 10 Angriffs-Payloads (`../../etc/cron.d/evil`, `....//....//etc/x.pdf`, `..%2f..%2f`, NUL-Byte, `..`): **kein einziger Fall verlässt `/mnt/nas/ai/<Schema>/`** (`path.resolve(full).startsWith(dir + sep)` in allen Fällen `true`).
- [x] **Absender-Feld nicht ausbrechbar** — `shortenSender()` whitelistet `[A-Za-z0-9._-]`, `/` und `\` sind ausgeschlossen; `../../../root@evil` → `..-..-..-root`.
- [x] **Schema-Segment nicht angreifbar** — `classification.document_type` stammt aus `parseClassification()`, das gegen `VALID_SCHEMAS` prüft; ein halluziniertes LLM-Ergebnis kann keinen beliebigen Pfad erzeugen.
- [x] **Keine Credentials in Logs** — Alle `logger.*`-Aufrufe in beiden Workflows geprüft: kein `password`, `password_enc` oder `passwordEnc` in einem Log-String. `Code: Cache Mailboxes` loggt nur `rows.length`.
- [x] **`password_enc` bleibt Ende-zu-Ende verschlüsselt** — `Prepare Mailbox Data` reicht `passwordEnc` unverändert durch; Backfill cached `password_enc` verschlüsselt in Redis. Kein neuer Klartext-Pfad; Entschlüsselung nur in `alice-mail-reader._decrypt_password()`.
- [x] **`/attachment` nutzt denselben Credential-Flow wie `/body`** — identische Zeilen `_decrypt_password(data["password_enc"])` → `_connect(data)` → `imap.login(...)`, `readonly=True`. Keine Abweichung.
- [x] **Input-Validierung `/attachment`** — `attachment_index` via `int()` in `try/except (TypeError, ValueError)` → 400 statt 500; negativer Index → 404; fehlende `uid` → 400; Index out of range → 404. Posture entspricht `/body`. Kein unbehandelter Crash.
- [x] **Keine `console.log`** — `grep -c console.log` = 0 in beiden Workflow-JSONs (CLAUDE.md-konform, winston durchgängig).
- [x] **Nur erlaubte `require`-Module** — `winston, axios, fs, path, redis, crypto`.
- [ ] **INFO (kein PROJ-53-Regress): Webhook ohne Authentifizierung** — `Webhook: POST /alice-mail-attachment-backfill` hat `authentication: "none"`. Identisch zu `alice-dms-classification-backfill`, `alice-dms-thumbnailer-backfill`, `alice-dms-language-backfill` → **bestehende Projektkonvention** (VPN-only-Zugang). Kein neuer Regress durch PROJ-53, aber: der Endpunkt triggert GPU-Last und IMAP-Verbindungen und ist damit ein DoS-Hebel für jeden, der im VPN ist. Als bekanntes Projekt-Risiko notiert, nicht als PROJ-53-Bug gewertet.

**Ergebnis:** Keine PROJ-53-spezifische Sicherheitslücke gefunden. Der in der Task besonders hervorgehobene Path-Traversal-Vektor über Anhangnamen/Absender ist wirksam neutralisiert.

### Bugs Found

#### BUG-1: Backfill-Dedup ist nicht crash-sicher (Write-then-Verify-Lücke)
- **Severity:** Low
- **Root Cause:** `alreadyOnDisk()` leitet den Import-Status ausschließlich aus der Existenz der Zieldatei ab. Zwischen `fs.writeFileSync()` und dem nächsten Lauf gibt es keinen Commit-Punkt — das ist bei Ableitung aus dem Dateisystem systembedingt.
- **Tatsächliches Verhalten:** `fs.writeFileSync()` ist nicht atomar. Bricht n8n **während** des Schreibvorgangs ab, bleibt eine **abgeschnittene Datei** liegen. Der nächste Backfill-Lauf sieht den Dateinamen, wertet den Anhang als "erledigt" und importiert ihn **nie erneut** → stiller Datenverlust (unvollständige Datei im DMS). Wird der Lauf **vor** dem Write abgebrochen, ist das Verhalten korrekt (erneuter Import).
- **Steps to Reproduce:** 1. Backfill starten. 2. n8n-Container während eines `writeFileSync` eines großen Anhangs killen. 3. Backfill erneut starten. 4. Erwartet: Anhang wird vollständig neu geschrieben. 5. Tatsächlich: Anhang gilt als importiert, Torso-Datei bleibt.
- **Bewertung:** Die Spec verlangt Resumability "ohne bereits importierte Anhänge erneut abzulegen" — das ist erfüllt. Absolute Crash-Sicherheit wird **nicht** verlangt. Mitigierbar durch Write-to-temp + `fs.renameSync()` (atomar innerhalb desselben Dateisystems).
- **Priority:** Nice to have (Verhalten hier dokumentiert, wie in der Aufgabenstellung gefordert)

#### BUG-2: `alreadyOnDisk()` erzeugt False-Positive-Dedup — Anhänge werden im Backfill nie importiert
- **Status:** **BEHOBEN in `99fb7c2` — verifiziert** (siehe Abschnitt "Re-Test")
- **Severity:** Medium
- **Root Cause:** `alreadyOnDisk(baseName)` prüft `baseName` **und** alle Varianten `_1`…`_20` in **allen fünf** Schema-Ordnern und gibt bei **irgendeinem** Treffer `true` zurück. Der Basisname enthält aber nur `<Datum>_<Absender-Kurzform>_<Dateiname>` — **keine** Message-ID und **keinen** Anhang-Index. Damit kollidieren fachlich verschiedene Anhänge auf demselben Schlüssel.
- **Tatsächliches Verhalten (re-verifiziert in Node):**
  - **(a) Gleichnamige Geschwister-Anhänge:** Eine Mail mit zwei Anhängen `R.pdf` erzeugt zwei Kandidaten mit **identischem** `baseName`. Existiert `R.pdf` bereits, liefert `alreadyOnDisk()` für **beide** `true` → der zweite Anhang wird **nie** importiert. Widerspricht EC-9 und AC-4.4 (Kollisions-Suffix soll auch im Backfill greifen).
  - **(b) Mail-übergreifende Falsch-Dedup:** Zwei **verschiedene** Mails desselben Absenders am selben Tag mit gleichem Anhangnamen (z. B. Tagesabrechnungen `Rechnung.pdf`) → die zweite Mail gilt als erledigt, ihr Anhang wird nie importiert.
  - **(c) Deckel bei `_20`:** Ab der 21. Kollision greift die Prüfung nicht mehr; `resolveCollision()` zählt aber bis 999 → ab `_21` wird bei jedem Lauf erneut importiert (**Duplikate**, gegenläufig zu (a)/(b)).
- **Steps to Reproduce:** 1. Mail von `absender@x.de` vom 2026-01-01 mit zwei Anhängen `Rechnung.pdf`. 2. Backfill laufen lassen. 3. Erwartet: `2026-01-01_absender_Rechnung.pdf` **und** `..._Rechnung_1.pdf`. 4. Tatsächlich: nur die erste Datei; der zweite Anhang wird dauerhaft als importiert gewertet.
- **Bewertung:** Kein Datenverlust im Quellsystem (Mail bleibt im Postfach), aber ein **stiller, dauerhafter Import-Ausfall**, den kein Log meldet — die Mail wird als `skippedAlreadyImported` gezählt. Sauber lösbar, indem Message-ID + `attachment_index` in den Dateinamen einfließen oder der Filter pro Kandidat die bereits in **diesem** Lauf belegten Namen mitzählt.
- **Priority:** Fix before deployment

#### BUG-3: Kein Größenlimit — großer Anhang kann den n8n-Prozess sprengen
- **Status:** **BEHOBEN in `99fb7c2` — verifiziert** (siehe Abschnitt "Re-Test")
- **Severity:** Medium
- **Root Cause:** Der komplette Anhang wird als Base64-String über HTTP geladen und im Speicher gehalten: `attData.content_base64` → `Buffer.from(..., 'base64')`. Zusätzlich hält `alice-mail-reader` die gesamte RFC822-Mail via `email_lib.message_from_bytes(raw)` im RAM.
- **Tatsächliches Verhalten:** Für einen 100-MB-Anhang liegen gleichzeitig vor: ~133 MB Base64-String (JS) + ~100 MB Buffer + JSON-Parse-Overhead in n8n, plus ~100 MB+ im Python-Container. Bei mehreren großen Anhängen droht OOM des n8n-Containers — was **den gesamten Sync-Zyklus** und alle anderen Workflows trifft, nicht nur diesen Anhang.
- **Steps to Reproduce:** 1. Mail mit sehr großem PDF-Anhang (z. B. 200 MB Scan) an ein überwachtes Postfach. 2. Sync abwarten. 3. Erwartet: Import oder kontrolliertes Überspringen. 4. Tatsächlich: potenzieller OOM/Heap-Abbruch des n8n-Prozesses.
- **Bewertung:** EC-7 sagt explizit "kein Größenlimit für den Import selbst" und verweist auf bestehendes Pipeline-Verhalten — die **nachgelagerte** Pipeline arbeitet aber dateibasiert, nicht über einen Base64-Roundtrip durch n8n. Der Speicherpfad ist neu in PROJ-53 und damit nicht durch das bestehende Verhalten abgedeckt. Empfehlung: Obergrenze (z. B. 50 MB) im Prefilter anhand des bereits vorliegenden `size_bytes` — kostet keinen zusätzlichen Fetch.
- **Priority:** Fix before deployment

#### BUG-4: Keine echte Textextraktion für PDF/DOCX/XLSX/Bilder (dokumentierte Abweichung)
- **Severity:** Low
- **Root Cause:** Nur `.txt`/`.md` werden dekodiert (`PLAINTEXT_EXTENSIONS`). Für alle Binärtypen bleibt `textPreview` leer, der Prompt erhält `(no extractable text - classify from filename and email context)`.
- **Tatsächliches Verhalten:** AC-2.5 verlangt "extrahierbarer Textinhalt/-vorschau des jeweiligen Anhangs". Für den praktisch wichtigsten Fall (PDF-Rechnungen) wird ausschließlich aus Dateiname + Mail-Kontext klassifiziert. Bei nichtssagenden Namen (`Anhang.pdf`) sinkt die Trefferquote spürbar; der `Document`-Fallback greift.
- **Bewertung der Begründung:** **Nachvollziehbar und korrekt.** Verifiziert, dass `dms-extractor-*` MQTT/Redis-Queue-Worker ohne synchronen HTTP-Endpunkt sind; die Spec schließt neue Infrastruktur aus. Fachliche Auswirkung ist begrenzt, weil die nachgelagerte DMS-Pipeline die Datei nach dem Scan ohnehin anhand des extrahierten Volltexts erneut klassifiziert — der Zielordner ist also nur die **Erst**einsortierung.
- **Priority:** Nice to have (eigenes Folge-Feature: synchroner Extraktor-Endpunkt)

#### BUG-5: `SUPPORTED_EXTENSIONS` und Helper dreifach dupliziert
- **Severity:** Low
- **Root Cause:** Die Allowlist steht wörtlich in `alice-dms-path-worker`, `Code: Import Attachments` und `Code: Fetch Mails With Attachments`; sieben Helper-Funktionen sind zwischen Laufzeit- und Backfill-Node kopiert.
- **Tatsächliches Verhalten:** AC-2.2 fordert "die Liste bleibt zentral erweiterbar" — sie ist **nicht** zentral. Eine neue Endung muss an drei Stellen gepflegt werden; wird eine vergessen, divergieren Laufzeit-Prefilter und Backfill-Kandidatenermittlung (Anhänge würden dauerhaft als "nichts zu tun" gewertet). Aktuell sind alle Kopien **identisch** — kein akuter Fehler, nur Wartungsrisiko.
- **Priority:** Fix in next sprint

#### BUG-6: Implementation Notes beschreiben die Branch-Reihenfolge falsch
- **Status:** **BEHOBEN in `99fb7c2` (Doku-Korrektur) — verifiziert.** Die Notes sagen jetzt korrekt, dass beide Zweige am selben Ausgang (Index 0) hängen und der Import vor dem Status-Reset läuft. Deckt sich mit dem geprüften `connections`-JSON. Kein Verhaltens-Change.
- **Severity:** Low
- **Root Cause:** Die Notes behaupten, der Anhang-Zweig hänge als "**erster Ausgang**" und der Notification-Zweig als "zweiter Ausgang" an `Process + Classify + Store Emails`. Tatsächlich liegen **beide** auf **Output-Index 0** als parallele Zweige.
- **Tatsächliches Verhalten:** n8n arbeitet parallele Zweige desselben Outputs sequenziell in Listenreihenfolge ab. `Code: Import Attachments` steht **vor** `Notify: Passthrough` → der gesamte Anhang-Import (pro Anhang bis zu 120 s Fetch + 2×120 s Ollama) läuft, **bevor** `PG: Update Sync Status` den `syncing`-Status zurücksetzt und die Mailbox-Schleife weiterläuft. Bei einer Mail mit mehreren großen Anhängen kann eine Mailbox dadurch sehr lange auf `syncing` stehen und den Minuten-Trigger blockieren (`IF: Free to Run?`).
- **Bewertung:** Funktional kein Fehler (kein Datenverlust, `onError: continueRegularOutput` verhindert Blockade durch Exceptions), aber ein Durchsatz-/Latenz-Risiko und eine **sachlich falsche Beschreibung** in der Doku, die einen Reviewer in die Irre führt.
- **Priority:** Fix in next sprint (Doku korrigieren; ggf. Zweig-Reihenfolge tauschen, damit der Status-Zweig zuerst läuft)

### Explizit geprüft und **nicht** bestätigt (Negativbefunde)

Diese in der Aufgabenstellung vermuteten Fehlerklassen wurden gezielt gesucht und liegen **nicht** vor:

- **Off-by-one zwischen `_get_attachments()` und `/attachment`:** Kein Fehler. Der Diff belegt echte Vereinheitlichung: `_get_attachments()` besteht nur noch aus `for filename, part in _walk_attachment_parts(msg)`, `/attachment` nutzt `enumerate(_walk_attachment_parts(msg))`. **Eine** Filterkette (`multipart`-Skip, `Content-Disposition is None`-Skip, leerer Dateiname-Skip), damit garantiert identische Reihenfolge. Auch der n8n-seitige Index passt: `idx` ist der Laufindex über das **ungefilterte** `mail.attachments`-Array aus `/fetch`; Prefilter-Skips nutzen `continue` und verschieben `idx` nicht. Der Backfill hält den Absolutindex ebenfalls korrekt (`.map((a, idx) => ({...a, attachment_index: idx}))` **vor** `.filter(...)`).
- **Kollisions-Endlosloop / Überschreiben:** Kein Fehler (siehe AC-3.3, re-verifiziert).
- **Bild-Müll-Check nach der Klassifizierung / nur ein Kriterium:** Kein Fehler — Prefilter läuft vor Fetch und Klassifizierung und prüft Typ **und** Größe (siehe AC-2.3).
- **MQTT feuert unkonditional:** Kein Fehler — `storedEmails` enthält ausschließlich echte Neu-Inserts (nach Dedup-`continue`, nach erfolgreichem `axios.post`), zusätzlich `.filter(m => m.weaviate_uuid)`.
- **Fehlende Error-Isolation:** Kein Fehler — jede Anhang-Iteration ist in `try/catch` gekapselt, alle drei Risiko-Schritte (Fetch, mkdir, write) haben eigene `try/catch` mit `continue`; der äußere `catch` fängt alles Übrige. Zusätzlich `onError: continueRegularOutput` auf `Code: Import Attachments` und `MQTT: Publish Email Done`.
- **`/attachment` crasht bei ungültigem Input:** Kein Fehler (siehe Security Audit).
- **`console.log` in Code-Nodes:** Kein Fehler — 0 Treffer.

### Regression Check

- `git diff 4f44e5b 63636f8 -- workflows/alice-mail-sync.json`: **rein additiv.** Keine Nodes entfernt, 4 hinzugefügt. Einzige Änderung an bestehendem Code: `Process + Classify + Store Emails` gibt zusätzlich `storedEmails` zurück. Message-ID-Dedup, Ollama-Kategorisierung, Weaviate-Insert-Objekt sowie `processed`/`wichtig`/`maxUid` sind **unverändert** → `PG: Update Sync Status` und der Notification-Zweig arbeiten wie bisher. Übrige Diff-Zeilen sind reine Positions-Neuformatierung.
- `/fetch` und `/body` in `app.py`: Contracts unverändert; `_get_attachments()` liefert identische Struktur.
- Kein Eingriff in `alice-dms-processor`, `alice-dms-scanner`, `alice-dms-thumbnailer` oder das `Execute: Classify Document`-Sub-Workflow (bewusste Entscheidung, korrekt begründet).

### Static Checks

- Beide Workflow-JSONs: **gültiges JSON**, eindeutige Node-Namen und IDs.
- Connections: **keine** dangling Source-/Target-Referenzen; alle `$('Node')`-Referenzen existieren; einziger Node ohne Inbound ist ein `stickyNote` (unkritisch).
- Alle **15** Code-Nodes: `node --check` (in async-Wrapper wegen Top-Level-`await`) **grün**.
- `app.py`: `python3 -m py_compile` **grün**.
- `require`-Module auf `winston, axios, fs, path, redis, crypto` beschränkt.
- Der vom Implementer erwähnte Validierungs-Skript liegt weder im Commit noch im Working Tree — die Prüfungen wurden hier unabhängig neu aufgesetzt.

---

## Re-Test der Fixes (Commit `99fb7c2`, 2026-08-22)

Geprüft wurde ausschließlich der Diff `63636f8..99fb7c2` (2 Workflow-Nodes + Doku; `app.py` unverändert). Die Fix-Logik wurde **aus den ausgelieferten Node-JSONs mechanisch extrahiert** (nicht abgetippt) und gegen ein **echtes Dateisystem** ausgeführt, inklusive des ebenfalls ausgelieferten `resolveCollision()`-Writers, um vollständige Backfill-Läufe zu simulieren.

### BUG-2 — Re-Test: **BEHOBEN**

`alreadyOnDisk()` (Boolean, Deckel bei `_20`) ist ersetzt durch `countOnDisk()` (zählt den zusammenhängenden `base`+`_1.._N`-Lauf bis zur ersten Lücke, **ohne Deckel**) plus einen zweiten Pass, der alle Anhänge mit gleichem Basisnamen **über alle Mails hinweg** poolt: die ersten `countOnDisk(base)` Ansprüche gelten als erfüllt, jeder weitere bleibt pending. Logik unabhängig nachvollzogen — die Beschreibung des Entwicklers deckt sich mit dem ausgelieferten Code.

Alle drei ursprünglichen Repro-Szenarien re-ausgeführt, jeweils über **mehrere aufeinanderfolgende Läufe**:

| Szenario | Ergebnis |
| --- | --- |
| (a) Zwei gleichnamige Anhänge in **einer** Mail (EC-9) | **PASS** — Lauf 1 importiert **beide** (`R.pdf` + `R_1.pdf`), Lauf 2 importiert nichts. Vorher: zweiter Anhang wurde nie importiert |
| (b) Zwei **verschiedene** Mails, gleicher Absender/Datum/Dateiname | **PASS** — Lauf 1 importiert beide, Lauf 2 importiert nichts, exakt 2 Dateien auf Platte. Vorher: zweite Mail dauerhaft übersprungen |
| (b2) Wiederaufnahme nach Teil-Lauf (1 von 2 bereits importiert) | **PASS** — genau der **eine** fehlende Anhang wird nachgeholt, kein Doppel-Import |
| (c) 25 Mails, Dateien jenseits des alten `_20`-Deckels | **PASS** — Lauf 1 importiert alle 25, Lauf 2 importiert **nichts**. Vorher: ab `_21` bei jedem Lauf Duplikate |
| (d) Gleicher Basisname in **unterschiedlichen** Schema-Ordnern | **PASS** — vorhandene Datei in `Invoice/` wird mitgezählt, nur der fehlende zweite Anhang importiert |

**Kein Doppel-Import und kein False-Positive-Skip in allen Szenarien.** Idempotenz bestätigt: Wiederholungsläufe schreiben konsistent 0 Dateien.

**Neuer Nebenbefund (Low, nicht blockierend) — BUG-7:** `countOnDisk()` setzt einen **lückenlosen** `_N`-Lauf voraus (Kommentar im Code weist korrekt darauf hin). Löscht ein Admin manuell eine Datei aus der Mitte (z.B. `_1` bleibt weg, `_2` existiert), zählt die Funktion nur bis zur Lücke. Verifiziert: der nächste Lauf füllt die Lücke wieder auf (2 Schreibvorgänge), **konvergiert danach aber auf 0** und **überschreibt bzw. löscht keine vorhandene Datei** (`resolveCollision()` nimmt immer den ersten freien Slot). Effekt ist also begrenzt und selbstheilend, keine unbegrenzte Duplikat-Vermehrung. Auslösbar nur durch manuelles Eingreifen des Admins — genau der Fall, den PROJ-21/22 ohnehin abdeckt. Als Doku-Hinweis notiert, kein Handlungsbedarf vor Deployment.

### BUG-3 — Re-Test: **BEHOBEN**

`ATTACHMENT_MAX_BYTES = 52428800` (50 MB) ist in **allen drei** geforderten Stellen deklariert und durchgesetzt:

| Ort | Durchsetzung | Log bei Skip |
| --- | --- | --- |
| `alice-mail-sync` / `Code: Import Attachments` (Laufzeit-Prefilter) | `if (size > ATTACHMENT_MAX_BYTES) return { keep:false, reason:'too_large' }` | **ja** (`logger.warn`, inkl. uid/Dateiname/Größe), eigener Zähler `skipped_too_large` in `attachmentStats` |
| `alice-mail-attachment-backfill` / `Code: Fetch Mails With Attachments` (Kandidaten-Scan) | `if (size > ATTACHMENT_MAX_BYTES) return false` in `isImportCandidate()` | nein (Kandidat gilt als "nichts zu tun" — konsistent mit der Behandlung von Junk/Unsupported an dieser Stelle; der Importer loggt) |
| `alice-mail-attachment-backfill` / `Code: Import Mail Attachments` (Importer) | `if (Number(att.size_bytes \|\| 0) > ATTACHMENT_MAX_BYTES) { … continue; }` | **ja** (`logger.warn`) |

- **Prüfung erfolgt vor dem Netzwerkaufruf:** Positionsanalyse im ausgelieferten Code bestätigt die Reihenfolge Prefilter → `continue` → `POST /attachment` → Klassifizierung. Ein übergroßer Anhang löst **keinen** Base64-Roundtrip aus. Im Backfill-Importer steht die Prüfung ebenfalls vor dem `/attachment`-Aufruf.
- **Nicht stillschweigend verworfen:** Zwei der drei Stellen loggen explizit; im Laufzeitpfad zusätzlich als eigenes Feld in der Statistik sichtbar. Bewusst lauter behandelt als Bild-Müll, weil hier ein potenziell relevantes Dokument abgelehnt wird.
- **AC-2.2/AC-2.3 nicht beschädigt** — 12 Prefilter-Fälle inkl. Grenzwerten re-ausgeführt, alle PASS: Allowlist greift weiterhin zuerst (`.exe`/`.mkv` → `unsupported_extension`, auch bei riesiger Größe, also kein verschwendeter Check), Bild-Müll-Grenze unverändert (20479 → Skip, 20480 → Import), Größen-Grenze sauber (52428800 → Import, 52428801 → Skip), `image/*`-MIME mit Dokument-Endung weiterhin als Junk erkannt, fehlendes `size_bytes` → `0` → kein Fehlverhalten.

### Regressions-Spot-Check `57d5bc6..99fb7c2`

- **Umfang:** nur `workflows/alice-mail-sync.json` (1 Node), `workflows/alice-mail-attachment-backfill.json` (2 Nodes), `features/PROJ-53-*.md`. **Keine** Änderung an `app.py`, an anderen Workflows oder an Compose-/SQL-Dateien.
- **Keine Nodes hinzugefügt/entfernt**, `connections` in **beiden** Workflows **byte-identisch** unverändert → Graph-Topologie und der in AC-5.1 geprüfte MQTT-Pfad unberührt.
- `Process + Classify + Store Emails`, `Code: Split Stored Emails`, MQTT-Node und der gesamte Notification-/Status-Zweig **unverändert** → AC-3.6/AC-5.1 (MQTT nur für echte Neu-Inserts) weiterhin gültig.
- **Sicherheit unverändert:** `sanitizeFilename()`/`shortenSender()` vom Fix **nicht angefasst**; 10 Path-Traversal-Payloads erneut ausgeführt — kein Ausbruch aus `/mnt/nas/ai/<Schema>/`. Keine Credentials in den neuen Log-Zeilen (geloggt werden nur uid, Dateiname, Größe). Kein neuer `require`.
- **Statische Checks erneut grün:** beide JSONs valide, eindeutige Node-Namen/IDs, keine dangling Connection- oder `$('Node')`-Referenzen, alle 15 Code-Nodes `node --check` OK, 0 `console.log`.

### Summary (nach Re-Test)

- **Acceptance Criteria:** 24/26 PASS, 2 NOT VERIFIABLE (AC-5.2, AC-5.3 — benötigen Live-Deployment), 0 FAILs. AC-4.5 (Backfill-Resumability) und EC-9/EC-10 sind durch den BUG-2-Fix von PARTIAL auf **PASS** gehoben; AC-2.5 bleibt als bewusst akzeptierte, begründete Abweichung (BUG-4) dokumentiert.
- **Bugs:** 7 total (0 critical, 0 high, **0 offene medium**, 7 low/behoben) — BUG-2, BUG-3, BUG-6 **behoben und verifiziert**; BUG-1, BUG-4, BUG-5, BUG-7 offen, alle Low und bewusst akzeptiert.
- **Security:** **Pass** (unverändert, nach dem Fix erneut geprüft).
- **Production Ready:** **YES — READY**
- **Recommendation:** **Deploy.** Beide Medium-Bugs sind sauber und ursachengerecht behoben — der BUG-2-Fix adressiert die eigentliche Ursache (fehlende Mail-Identität im Dedup-Schlüssel) durch globalen Abgleich, statt nur den Symptom-Deckel `_20` hochzusetzen, und behält dabei das von AC-3.2/EC-9 vorgeschriebene Dateinamensmuster bei. Verbleibende Low-Bugs (BUG-1 Crash-Sicherheit, BUG-4 fehlende Binär-Textextraktion, BUG-5 duplizierte Konstanten, BUG-7 Lücken-Annahme) blockieren das Deployment nicht und können als Folgearbeit eingeplant werden.

**Hinweis für den Deploy-Schritt:** AC-5.2/5.3 (Thumbnail-Rendering für Mail-Objekte) konnten statisch nicht verifiziert werden und müssen nach dem Deployment gegen den laufenden `alice-dms-thumbnailer` geprüft werden.

---

## Iteration 2 — Refine nach Produktiv-Feedback (2026-08-23)

Der obige Tech-Design-/Implementation-/QA-Block (bis hier) bezieht sich auf **Iteration 1** (Commits `63636f8`…`c5e87c7`). Nach dem manuellen Deploy und einem ersten Backfill-Testlauf hat Andreas vier Lücken gemeldet, die die Spec jetzt oben (Acceptance Criteria, Edge Cases, Technical Requirements) ergänzt:

1. **Kein Dry-Run im Backfill** — der erste Aufruf hat produktiv Daten verarbeitet, weil (anders als bei anderen Backfill-Workflows, siehe `alice-dms-language-backfill`s `confirm`-Parameter/`IF: Confirm Mode`) kein Vorschau-Modus existierte.
2. **Alle Text-Anhänge landeten in `Document`** — Ursache: die in Iteration 1 bewusst dokumentierte Abweichung (BUG-4), dass nur `.txt`/`.md` Volltext ans LLM bekommen, PDF/DOCX nur Dateiname+Mail-Kontext. Für PDF wird das jetzt durch synchrone Volltextextraktion (`pdf-parse`, analog `dms-extractor-pdf`, aber ohne MQTT/Redis-Umweg) behoben. Office-Formate bleiben bewusst ohne Volltext (kein synchroner Extraktor verfügbar) — siehe PROJ-91 als Folge-Feature.
3. **Bilder landeten ebenfalls in `Document`, statt extensionbasiert geroutet zu werden** — jetzt explizit spezifiziert: Bild/Video/Audio ohne LLM-Aufruf, rein nach Dateiendung.
4. **Neu:** `Video/`- und `Audio/`-Zielordner, `SUPPORTED_EXTENSIONS` für diesen Workflow entsprechend erweitert.

Die 10 bereits fehlklassifizierten Dateien unter `/mnt/nas/ai/Document/` aus dem ungeplanten Live-Backfill-Lauf sind **nicht** in Weaviate registriert (der Ordner war zum Zeitpunkt des Laufs nicht in `alice.dms_watched_folders` eingetragen — geprüft per Direktabfrage). Andreas verschiebt sie manuell; keine Reklassifizierung in Weaviate nötig.

### Tech Design Iteration 2 (Solution Architect, 2026-08-23)

Ergänzung zum bestehenden Tech Design (Bausteine 1–3 oben bleiben in ihrer Grundstruktur bestehen). Vier Änderungen:

#### Ergänzung zu Baustein 1 (`alice-mail-reader`): PDF-Textextraktion

n8n-Code-Nodes dürfen aktuell nur `axios`, `redis`, `winston` (extern) sowie `crypto`, `fs`, `path` (Node-Builtins) nutzen (`NODE_FUNCTION_ALLOW_EXTERNAL`/`_BUILTIN` in `docker/compose/automations/n8n/compose.yml`). `pdf-parse` steht nicht auf dieser Liste, und diese projektweite Konfiguration für ein einzelnes Feature zu erweitern hätte einen Neustart des gemeinsam genutzten n8n-Containers zur Folge — zu großer Blast Radius für eine Feature-lokale Anforderung.

Stattdessen bekommt `alice-mail-reader` einen neuen Endpunkt `POST /attachment-text`:

- **Eingabe:** Dieselben Felder wie `/attachment` (Mailbox-Zugangsdaten, IMAP-UID, Anhang-Index)
- **Verhalten:** Lädt den Anhang wie `/attachment` (nutzt intern denselben MIME-Walk), erkennt PDF anhand der Dateiendung/des MIME-Typs, extrahiert Volltext mit derselben Technik wie `dms-extractor-pdf` (`pdf-parse`), synchron im gleichen Request — kein MQTT/Redis-Umweg
- **Ausgabe:** `{ text, page_count, truncated }`. Für Nicht-PDF-Anhänge (bzw. Extraktionsfehler) liefert der Endpunkt einen leeren Text mit entsprechendem Statusfeld, statt einen Fehler zu werfen — der aufrufende Workflow fällt dann auf Dateiname+Mail-Kontext zurück, wie es für Office-Formate ohnehin bereits vorgesehen ist
- Grund für die Ergänzung *in* `alice-mail-reader` statt eines neuen Service: Die Anhang-Bytes liegen dort durch `/attachment` schon vor; ein separater Service müsste sie erneut per IMAP laden oder durch den n8n-Workflow durchgereicht bekommen — beides unnötiger Umweg

#### Ergänzung zu Baustein 2 (`alice-mail-sync`): Extension-Routing vor Klassifizierung

Der bestehende Anhang-Vorfilter (Schritt 1 in Baustein 2) bekommt eine zusätzliche Weiche, **vor** dem LLM-Klassifizierungsschritt:

1. Extension prüfen gegen die (für diesen Workflow erweiterte) `SUPPORTED_EXTENSIONS`-Liste — neu: Video-Endungen (MP4, MOV, AVI, MKV, WEBM) und Audio-Endungen (MP3, WAV, M4A, OGG, FLAC) kommen hinzu
2. Bild-Datenmüll-Check (< 20 KB) wie bisher, unverändert
3. **Neu:** Ist der Anhang ein Bild (jenseits der Müll-Grenze), Video oder Audio → direkt `Document/` (Bild, unverändertes Verhalten) bzw. `Video/`/`Audio/` (neu) als Zielordner setzen, **kein** LLM-Aufruf, weiter zu Abruf+Ablage (Schritte 3–4 in Baustein 2)
4. Nur PDF/DOCX/XLSX/ODT/ODS/TXT/MD durchlaufen weiterhin die LLM-Klassifizierung (Schritt 2 in Baustein 2)

Für PDF ruft der Klassifizierungsschritt jetzt zusätzlich `POST /attachment-text` auf `alice-mail-reader` auf und übergibt den vollständigen extrahierten Text (statt bisher nichts) an den Klassifizierungs-Prompt. Für TXT/MD bleibt es bei der direkten Dekodierung (unverändert). Für DOCX/XLSX/ODT/ODS bleibt es bei Dateiname+Mail-Kontext ohne Volltext (siehe PROJ-91).

#### Ergänzung zu Baustein 3 (`alice-mail-attachment-backfill`): Dry-Run

Der Workflow bekommt denselben `confirm`-Mechanismus wie `alice-dms-language-backfill`:

- Request-Body/Query-Parameter `confirm` (boolean) wird zu Beginn gelesen
- Ohne `confirm: true`: Kandidaten werden wie gewohnt ermittelt und gezählt, aber der Import-Zweig (IMAP-Abruf, Klassifizierung, NAS-Write) wird übersprungen; Response liefert `{ candidates_found, dry_run: true }`
- Mit `confirm: true`: bisheriges Verhalten (tatsächlicher Import)
- Dieselbe Umsetzung wie Extension-Routing (siehe oben) gilt auch im Backfill-Pfad, da er dieselbe Klassifizierungs-/Ablagelogik dupliziert (siehe Tech-Entscheidungen unten zur Konsistenzpflicht zwischen Laufzeit- und Backfill-Pfad)

### Datenmodell (fachlich) — Ergänzung Iteration 2

- **Dateisystem** `/mnt/nas/ai/Video/` und `/mnt/nas/ai/Audio/`: neue Ablageziele, angelegt beim ersten Bedarf, analog den bestehenden fünf Schema-Ordnern. Anders als diese entsprechen sie **keinem** Weaviate-Schema (siehe Edge Case "Video-/Audio-Anhänge" oben) — reine Dateisystem-Ablage ohne DMS-Klassifizierungsanspruch.

### Tech-Entscheidungen (Begründung) — Ergänzung Iteration 2

- **`/attachment-text` als eigener Endpoint statt `/attachment` zu erweitern:** `/attachment` wird für alle unterstützten Dateitypen aufgerufen (auch Bild/Video/Audio, die keine Textextraktion brauchen) und von der Ablage-Logik konsumiert. Ein eigener Endpoint hält den Attachment-Abruf-Contract unverändert und macht die Textextraktion optional/on-demand, nur für den Klassifizierungsschritt.
- **Kein Vision-Modell-Einsatz für PDF-Klassifizierung:** `pdf-parse`-Volltext an das bestehende Text-Klassifizierungsmodell ist deutlich günstiger und schneller als ein Vision-Call (z.B. `qwen3.5:27b-q4_K_M`, aktuell nur für Bildbeschreibung/OCR-Pfade genutzt) und deckt den Regelfall (textbasierte PDF-Rechnungen/Kontoauszüge) ab. Gescannte Bild-PDFs ohne Textebene bleiben ein bekanntes Restrisiko (führen zu leerem Text → Fallback auf Dateiname+Mail-Kontext, analog Office-Formaten) — Verbesserung dafür wäre ein eigenes Folge-Feature (OCR-Pfad, analog `dms-extractor-ocr`), nicht Teil von PROJ-53.
- **Office-Formate bleiben ohne Volltext-Extraktion in PROJ-53:** `dms-extractor-office` nutzt LibreOffice headless (Subprocess, mehrere Sekunden Laufzeit) — nicht sinnvoll 1:1 synchron in `alice-mail-reader` nachzubauen, ohne die Kaltstart-/Ressourcenkosten des DMS-Pipeline-Containers zu duplizieren. Auf die Roadmap gesetzt als PROJ-91 (z.B. `markitdown`-basierter HTTP-Wrapper), der sowohl PROJ-53 als auch potenziell `dms-extractor-office` selbst ablösen könnte — bewusst nicht Teil dieses Zyklus, um PROJ-53 nicht mit einer neuen, noch nicht produktionserprobten Abhängigkeit zu belasten.
- **`confirm`-Parameter statt separatem Preview-Endpoint:** Konsistent mit dem bereits etablierten Muster aus `alice-dms-language-backfill` — ein Parameter statt zweier Routen hält den Webhook-Contract einfach und macht das Verhalten für den Admin vorhersehbar (derselbe Aufruf, nur ein Flag unterscheidet Vorschau von Ausführung).

**Nächste Schritte:** `/backend` für die Umsetzung der vier obigen Ergänzungen, dann erneut `/qa`.

## Deployment
_To be added by /deploy_
