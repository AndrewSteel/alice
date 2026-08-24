# PROJ-53: Mail-Anhang DMS-Import

## Status: Approved
**Created:** 2026-08-22
**Last Updated:** 2026-08-24 (QA-Nachprüfung bestanden — BUG-16/BUG-17 behoben und verifiziert, keine Critical/High-Bugs)

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

### Anhang-Erkennung & Klassifizierung (⚠️ ab Iteration 4 nicht mehr synchron in `alice-mail-sync` — siehe "Iteration 4" unten für den aktuellen Ablauf; dieser Abschnitt beschreibt die Klassifizierungs-/Ablage-**Logik**, die weiterhin gilt, nur der Trigger-Kontext ändert sich)
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

### Implementation Notes (Iteration 2, Backend, 2026-08-23)

Alle vier Ergänzungen umgesetzt. Backend-only, kein Deployment (erfolgt manuell durch den Admin).

**1. `alice-mail-reader`: neuer Endpunkt `POST /attachment-text`**

- Datei: `docker/compose/automations/alice-mail-reader/app.py`. Eingabe identisch zu `/attachment` (Mailbox-Credentials, `uid`, `attachment_index`). Ausgabe `{ text, page_count, truncated, status }` mit `status ∈ {ok, not_a_pdf, extraction_failed}`.
- **Nicht-PDF und Extraktionsfehler werfen keinen Fehler**, sondern liefern `200` mit leerem `text` + Statusfeld — der Workflow fällt dann wie bei Office-Formaten auf Dateiname+Mail-Kontext zurück. Nur echte Input-/IMAP-Fehler geben weiterhin 400/404/500 zurück (gleiche Posture wie `/attachment`).
- `PLAINTEXT_MAX_CHARS = 50000` wurde 1:1 aus `dms-extractor-pdf/main.js` übernommen, inkl. Truncation-Verhalten (`truncated`-Flag).
- **Refactoring:** Das IMAP-Fetch + MIME-Walk aus `/attachment` wurde in den gemeinsamen Helper `_fetch_attachment_part()` extrahiert, den jetzt beide Endpunkte nutzen (aufbauend auf `_walk_attachment_parts()` aus Iteration 1). Damit adressieren `/attachment` und `/attachment-text` garantiert denselben MIME-Part. Der `/attachment`-Contract ist unverändert (per Test abgesichert).
- Modul-Docstring-Endpunktliste ergänzt.

**PDF-Bibliothek: `pypdf==5.1.0`**

Gewählt statt `pdfplumber`, weil `alice-mail-reader` auf `python:3.12-alpine` läuft: `pypdf` ist ein reines Python-Wheel (`pypdf-5.1.0-py3-none-any.whl`, verifiziert per `pip download`) und installiert auf Alpine/musl ohne Compiler. `pdfplumber` zieht `pdfminer.six` **und `Pillow`** nach; Pillow hat für musl keine vorgebauten Wheels und bräuchte Build-Deps (`gcc`, `zlib-dev`, `jpeg-dev`, …) im Image — deutlich größeres Image und längere Builds für reine Textextraktion. Funktional entspricht `pypdf.PdfReader(...).pages[i].extract_text()` dem, was `pdf-parse` im Node-Extraktor liefert (Volltext + Seitenzahl). Dependency steht in der `pip install`-Zeile des `Dockerfile` (dieser Service hat keine `requirements.txt` — Abhängigkeiten sind dort inline gepflegt, Konvention beibehalten).

**2. Extension-Routing (beide Workflows)**

- `SUPPORTED_EXTENSIONS` in **beiden** Workflows um Video (`.mp4 .mov .avi .mkv .webm`) und Audio (`.mp3 .wav .m4a .ogg .flac`) erweitert, klar als PROJ-53-spezifische Ergänzung kommentiert (**nicht** Teil der geteilten DMS-Allowlist aus `alice-dms-path-worker`).
- Neuer Helper `routeByExtension(ext, mime)` → `'Document'` (Bild, unverändert) / `'Video'` / `'Audio'` / `null` (= LLM-Klassifizierung). Läuft **nach** dem Bild-Müll-Check (<20 KB) und **vor** jedem LLM-Aufruf. Video/Audio unterliegen bewusst **nicht** der 20-KB-Müll-Grenze (die ist bildspezifisch).
- **Neue Konstante `VALID_TARGET_FOLDERS`** (= 5 Schemata + `Video` + `Audio`) gattet den finalen Zielordner. `VALID_SCHEMAS` bleibt **exakt** die fünf DMS-Schemata, weil es auch die LLM-Antwort validiert — verifiziert, dass das LLM `Video`/`Audio` nicht zurückgeben kann.
- `Video/` und `Audio/` werden über denselben `fs.mkdirSync(targetDir, { recursive: true })`-Pfad angelegt wie die fünf Schema-Ordner (gemeinsamer Code-Pfad, kein Sonderfall).
- **Verifiziert statt angenommen:** Kollisions-Suffix, Dateinamensmuster und Pfad-Sanitisierung aus Iteration 1 funktionieren für Video/Audio unverändert (gegen echtes Dateisystem getestet, inkl. Path-Traversal-Payloads in Video-Dateinamen).

**3. PDF-Volltext in der Klassifizierung (beide Workflows)**

Im Klassifizierungszweig ruft jetzt für `.pdf` ein neuer Helper `fetchPdfText()` den Endpunkt `/attachment-text` auf und übergibt das Ergebnis an den bestehenden Prompt (ersetzt den `(no extractable text …)`-Platzhalter **nur für PDF**). TXT/MD behalten die direkte Dekodierung, DOCX/XLSX/ODT/ODS bleiben bei Dateiname+Kontext (PROJ-91). Jeder Fehler → `''` → bestehender Fallback.

**Abweichung (ehrlich): zwei IMAP-Roundtrips pro PDF.** Der Tech-Design-Punkt "nutzt intern denselben MIME-Walk" ist auf Service-Ebene erfüllt (gemeinsamer Helper `_fetch_attachment_part()`), **nicht** aber im Sinne eines einzigen IMAP-Abrufs: Der Workflow ruft für ein PDF erst `/attachment` (Bytes) und dann `/attachment-text` (Text) auf — zwei getrennte HTTP-Requests, jeder mit eigenem IMAP-Login und eigenem RFC822-Fetch. Ursache: Beide Endpunkte sind zustandslos und der n8n-Code-Node kann die bereits geladenen Bytes nicht an den Extraktor zurückgeben, ohne sie erneut (base64) hochzuladen. Für ein PDF wird die Mail also zweimal vom IMAP-Server geladen. Bewusst so belassen, weil die Alternativen schlechter sind: Bytes zurück an den Service posten würde den Base64-Roundtrip **verdoppeln** (genau der Speicherpfad, den BUG-3 begrenzt hat), ein serverseitiger Cache würde die von der Spec ausgeschlossene neue Persistenzschicht einführen. Praktische Kosten: ein zusätzlicher IMAP-Fetch pro **PDF**-Anhang (nicht pro Anhang) — Bild/Video/Audio rufen `/attachment-text` gar nicht auf.

**4. Dry-Run im Backfill**

- `Code: Init Backfill Run` liest `body.confirm`/`query.confirm` mit **wörtlich derselben** Coercion wie `alice-dms-language-backfill` (verifiziert per String-Vergleich gegen den Referenz-Node) und gibt `confirm` weiter.
- `Code: Fetch Mails With Attachments` liest das Flag via `$('Code: Init Backfill Run')` (der direkte Input ist `Code: Cache Mailboxes`, das `confirm` nicht führt) und zählt die Kandidaten. Ohne `confirm: true` endet der Node vor dem Import-Zweig und liefert `{ _empty: true, _dry_run: true, candidates_found, pending_mails }`.
- **Abweichung von der Vorlage (bewusst):** Statt eines separaten `IF: Confirm Mode`-Nodes wie in `alice-dms-language-backfill` nutzt der Dry-Run den **bestehenden** `IF: Queue Empty` → `Code: Empty Summary`-Pfad (`_empty: true`). Grund: Dort liegt bereits die Lock-Freigabe + Redis-Cleanup; ein zusätzlicher Zweig hätte diese Logik dupliziert oder (bei falscher Verdrahtung) den geteilten Processor-Lock hängen lassen. `Code: Empty Summary` unterscheidet die beiden Fälle am `_dry_run`-Flag und antwortet mit `{ dry_run: true, candidates_found, pending_mails, message }`. Die Graph-Topologie ist damit **unverändert** — kein neuer Node, keine neue Connection. Verifiziert: Lock wird auch im Dry-Run freigegeben, und der Kandidaten-Scan-Node macht **keinen** `/attachment`-Aufruf, kein `writeFileSync` und kein `mkdirSync` (einziger Netzwerkaufruf: Weaviate-GraphQL).
- `SCHEMAS` in `Code: Fetch Mails With Attachments` musste um `Video`/`Audio` erweitert werden: Diese Liste steuert `countOnDisk()` und damit die "bereits importiert"-Erkennung. Ohne die Erweiterung wäre **jeder Video-/Audio-Anhang bei jedem Backfill-Lauf erneut importiert** worden (Duplikate). Das ist bewusst eine andere Liste als `VALID_SCHEMAS`.

**Hält das Duplizierungs-Muster aus Iteration 1? — Teilweise, mit konkretem Drift-Risiko**

Für die *reinen* Helper (`routeByExtension`, `fetchPdfText`) ließ sich der Copy-Paste-Ansatz sauber fortführen; ein automatisierter Vergleich beweist, dass Laufzeit- und Backfill-Pfad für alle geprüften Endungen **identisch** routen. Zwei Stellen zeigen aber, dass das Muster nicht mehr trägt:

1. `fetchPdfText()` ist **nicht** byte-identisch: Der Laufzeitpfad liest Credentials aus `ctx` (`ctx.host`, `ctx.passwordEnc`), der Backfill aus dem Redis-Mailbox-Cache (`mailbox.imap_host`, `mailbox.password_enc`). Gleiche Logik, unterschiedliche Feldnamen — genau die Art Divergenz, die ein späterer Copy-Paste-Fix übersieht.
2. Die Endungs-Allowlist steht jetzt an **drei** Stellen im Feature (Laufzeit-Import, Backfill-Import, Backfill-Kandidaten-Scan) plus im `alice-dms-path-worker`. Bei dieser Iteration musste `SUPPORTED_EXTENSIONS` an drei Stellen **gleichzeitig** korrekt erweitert werden; wäre der Kandidaten-Scan vergessen worden, hätte der Backfill Video/Audio dauerhaft als "nichts zu tun" gewertet — ein stiller Ausfall ohne Log. Das ist die in Iteration 1 als BUG-5 (Low) notierte Wartungsschuld, die durch iteration 2 spürbar teurer geworden ist. **Empfehlung:** BUG-5 hochstufen und die Allowlist + Routing-Helper in ein Sub-Workflow oder einen kleinen Shared-Service ziehen, bevor eine dritte Iteration weitere Formate ergänzt.

**Verifikation**

- `app.py`: `py_compile` grün; **27 Assertions** gegen den echten Endpunkt-Code mit einem real erzeugten PDF (Volltext über 2 Seiten, `page_count`, Truncation exakt bei 50000, `not_a_pdf`, `extraction_failed` bei korruptem PDF, 400/404-Inputfälle) — plus Nachweis, dass der `/attachment`-Contract (4 Felder, Byte-Round-Trip) nach dem Refactoring unverändert ist.
- **62 Assertions** gegen den **tatsächlich im Workflow-JSON eingebetteten** Code (mechanisch extrahiert, nicht abgetippt): Routing aller Video-/Audio-/Bild-/Text-Endungen, `VALID_SCHEMAS` unverändert + LLM kann Video/Audio nicht zurückgeben, Prefilter-Grenzwerte (20 KB / 50 MB) unverändert, Kollisions-Suffix und Path-Traversal für Video/Audio gegen echtes Dateisystem, Laufzeit-/Backfill-Parität.
- Beide Workflow-JSONs strukturell validiert: gültiges JSON, eindeutige Node-Namen/IDs, alle Connection- und `$('Node')`-Referenzen auflösbar, keine verwaisten Nodes, alle 15 Code-Nodes `node --check` grün, **0 `console.log`**, Credentials auf allen Postgres-/MQTT-Nodes, nur erlaubte `require`-Module (`axios, redis, winston, crypto, fs, path`).
- Diff-Disziplin: In beiden JSONs haben sich ausschließlich die geänderten `jsCode`-Zeilen (und die Sticky Note) geändert — keine Reformatierung, keine Topologie-Änderung (per Round-Trip-Vergleich abgesichert).
- **Nicht verifizierbar in dieser Umgebung:** kein Lauf gegen echtes n8n/IMAP/Ollama/Weaviate/NAS; `pypdf` wurde lokal in einem venv getestet, **nicht** im Alpine-Image (Image-Build steht aus — beim Deploy muss `alice-mail-reader` neu gebaut werden, sonst fehlt `pypdf`). Die `mcp__n8n-mcp__*`-Tools waren auch in dieser Session nicht verfügbar, daher erneut strukturelle Eigenvalidierung statt `n8n_validate_workflow`.

#### Bugfix nach Produktiv-Test (2026-08-23): Dry-Run-Gate war wirkungslos

**Symptom (vom User in Produktion gefunden):** Aufruf des Webhooks mit `{"confirm": true}` im JSON-Body führte trotzdem zum Dry-Run. Der n8n-Webhook-Node zeigte `body: {confirm: true}` korrekt an, aber `Code: Init Backfill Run` gab `{"confirm": false, …}` aus.

**Root Cause:** `Code: Init Backfill Run` las den Payload über `$input.first().json`. Der reale Graph ist aber:

```text
Webhook: POST /attachment-backfill → Code: Acquire Backfill Lock → IF: Lock Acquired → Code: Init Backfill Run
```

`Code: Acquire Backfill Lock` gibt ein **neu konstruiertes** Objekt zurück (`return [{ json: { _lock_acquired, _lock_error, lock_owner } }]`) und liest `$input` überhaupt nicht — der Webhook-Payload (`body`, `query`, `headers`) wird an dieser Stelle **verworfen**. Bei `Code: Init Backfill Run` war `$input.first().json.body` daher immer `undefined`, `confirmRaw` immer `undefined` und `CONFIRM` **konstant `false`** — unabhängig vom Aufruf. Das Dry-Run-Gate war damit nicht nur fehlerhaft, sondern machte den Import über den Webhook **unerreichbar**.

**Fix:** `Code: Init Backfill Run` liest den Original-Payload jetzt per Node-Namen statt über `$input`:

```js
const item = $('Webhook: POST /attachment-backfill').first().json;
```

Ein Kommentar im Node hält fest, warum `$input` hier nicht verwendet werden darf. Der Lock-Node bleibt bewusst unverändert (siehe unten).

**Warum der Lock-Node den Payload nicht durchreicht (Design-Entscheidung):** Geprüft wurde, ob stattdessen `Code: Acquire Backfill Lock` den Webhook-Payload mergen sollte. Dagegen spricht: `alice-dms-language-backfill` — die Vorlage, aus der das `confirm`-Muster stammt — hat einen **strukturell identischen** Lock-Node, der den Payload ebenfalls verwirft. Ein Merge nur in diesem Workflow würde von der etablierten Konvention abweichen; der Lookup per Node-Namen ist die minimale, lokal begründete Korrektur und ändert die Graph-Topologie nicht.

> **Hinweis außerhalb des PROJ-53-Scopes:** `alice-dms-language-backfill` hat denselben latenten Fehler — auch dort liest `Code: Init Backfill Run` `body`/`query` über `$input`, obwohl der vorgeschaltete Lock-Node den Payload verwirft. Dessen `confirm`-Parameter dürfte damit ebenfalls dauerhaft `false` sein. **Nicht** im Rahmen von PROJ-53 geändert (fremder Workflow), aber als eigener Bug zu erfassen. `alice-dms-classification-backfill` und `alice-dms-thumbnailer-backfill` werten keinen Webhook-Payload aus und sind nicht betroffen.

**Audit auf dieselbe Fehlerklasse in diesem Workflow (alle Nodes geprüft):**

- `Code: Init Backfill Run` war die **einzige** Stelle, die `body`/`query` liest — kein weiterer Node greift auf den Webhook-Payload zu.
- Nachgelagerte Konsumenten sind nicht betroffen: `Code: Fetch Mails With Attachments` liest `$('Code: Init Backfill Run').first().json.confirm` (per Node-Namen, korrekt) und greift **nicht** selbst auf `body`/`query` zu — verifiziert.

**Zusätzlicher Befund: `MAX_RUNTIME_SECONDS` war eine tote Konfiguration.** `Code: Init Backfill Run` gab das Feld aus, aber `Code: Time Check` hatte den Wert `7200` **hartkodiert** und ignorierte es vollständig. Ein Verstellen des Werts (wie vom User zum Testen versucht) hatte deshalb keinerlei Wirkung auf das tatsächliche Timeout — eine stille Falle. Behoben: `Code: Time Check` liest den Wert jetzt per `$('Code: Init Backfill Run')`, und `Init` akzeptiert einen optionalen Override `max_runtime_seconds` (Body oder Query, gleiche Quelle wie `confirm`) mit Fallback auf 7200.

**Verifikation (Lehre aus dem Fehler: kein isoliertes Funktionstesten mehr)**

Der Bug entstand, weil Iteration 2 die `confirm`-Auswertung nur **isoliert mit handgefüttertem Input** geprüft hat — so kann nicht auffallen, dass der Upstream-Node den Payload zerstört. Deshalb jetzt ein **Graph-Trace-Test** (`test_graph_trace.js`), der:

1. den Ausführungspfad **aus dem `connections`-JSON ableitet** (nicht aus einer Annahme) und bestätigt, dass Init über Lock + IF erreicht wird,
2. den **tatsächlich ausgelieferten Node-Code** von `Code: Acquire Backfill Lock`, `Code: Init Backfill Run` und `Code: Time Check` mit n8n-getreuer `$input`/`$('Node')`-Semantik nacheinander ausführt,
3. den Produktionsfall `POST {"confirm": true}` nachstellt.

Ergebnis (18 Assertions, alle grün): Der Lock-Node-Output enthält nachweislich nur `["_lock_acquired","_lock_error","lock_owner"]` (Root Cause reproduziert), der **alte** Code liefert auf genau diesem Trace `confirm=false` (Produktionsbug reproduziert), der **neue** Code liefert `confirm=true`. Zusätzlich abgedeckt: Dry-Run als Default ohne Parameter, `?confirm=true` per Query, `confirm:"true"` als String, `confirm:false`, sowie der `MAX_RUNTIME_SECONDS`-Override inkl. Nachweis, dass `Code: Time Check` ihn nun wirklich konsumiert (180 s greift bei 1000 s Laufzeit, 7200 s nicht). Die 62 Assertions der Routing-/Prefilter-Suite und die strukturelle Validierung beider Workflows laufen unverändert grün.

**Deployment-Hinweise für den Admin**

1. `alice-mail-reader` muss **neu gebaut** werden (`docker compose build`), nicht nur neu gestartet — `pypdf` ist eine neue Abhängigkeit.
2. Backfill zuerst **ohne** `confirm` aufrufen, um die Kandidatenzahl zu sehen; erst danach mit `{"confirm": true}`.
3. `/mnt/nas/ai/Video/` und `/mnt/nas/ai/Audio/` werden automatisch angelegt, sind aber **kein** Weaviate-Schema — vor Aufnahme in `alice.dms_watched_folders` das Verhalten der nachgelagerten Pipeline prüfen (siehe Edge Case oben).

---

## QA Test Results — Iteration 2 (2026-08-23)

**Tested:** 2026-08-23
**Tester:** QA Engineer (AI)
**Commit under test:** `5b2259e` (Diff-Basis: `a010f8f` = Stand vor Iteration 2)
**Scope:** ausschließlich die vier Iteration-2-Ergänzungen (Dry-Run, `/attachment-text`, Extension-Routing, PDF-Volltext) + Regression gegen die in Iteration 1 bereits abgenommene Logik.
**Test method:** Statisch/Logik-Review + **isolierte Re-Ausführung des tatsächlich ausgelieferten Codes**. Die Code-Node-Helper wurden **mechanisch** aus den Workflow-JSONs extrahiert (nicht abgetippt); der Kandidaten-Scan-Node wurde **als Ganzes** ausgeführt (nur `axios`/Weaviate gemockt, `NAS_AI_ROOT` auf ein echtes Temp-Dateisystem gezeigt). `app.py` wurde mit `pypdf==5.1.0` in einem venv gegen **real erzeugte PDFs** (reportlab) getestet. **Keine Live-Ausführung** gegen n8n/IMAP/Ollama/Weaviate/NAS — solche Kriterien sind als `NOT VERIFIABLE` markiert.

**Testumfang gesamt: 467 Assertions, 0 Fehler** (61 Routing/Schema-Gating, 232 Parität der drei Konstanten-Kopien, 30 Dry-Run-Parität, 82 Iteration-1-Regression, 53 `/attachment-text`, 9 Lock-Semantik + statische Checks).

### Acceptance Criteria Status — neue/geänderte Bereiche

#### AC-1: Zielordner-Struktur (Erweiterung Video/Audio)

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 1.1 | `Video/` + `Audio/` zusätzlich zu den fünf Schemata | PASS | `VALID_TARGET_FOLDERS = new Set([...VALID_SCHEMAS,'Video','Audio'])` in **beiden** Import-Nodes; Größe 7 verifiziert |
| 1.2 | Fehlende Ordner werden automatisch angelegt | PASS | Video/Audio laufen über **denselben** `fs.mkdirSync(targetDir,{recursive:true})`-Pfad wie die Schema-Ordner — kein Sonderfall, kein zweiter Code-Pfad |

#### AC-2: Extension-Routing (der kritische Bereich)

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 2.a | Reihenfolge (a) unsupported → reject | PASS | `prefilterAttachment()` prüft `SUPPORTED_EXTENSIONS` als **erste** Anweisung; `.exe` wird auch bei 999 MB als `unsupported_extension` abgelehnt (kein verschwendeter Folgecheck) |
| 2.b | (b) Bild-Müll < 20 KB → stilles Skip | PASS | Grenzwerte unverändert re-verifiziert: 20479 → `image_junk`, 20480 → Import. `image/*`-MIME mit Dokument-Endung weiterhin als Junk erkannt |
| 2.c | (c) Bild/Video/Audio → Direkt-Routing, **kein** LLM-Aufruf | PASS | `routeByExtension()` liefert für alle 7 Bild-, 5 Video-, 5 Audio-Endungen `Document`/`Video`/`Audio`; im Code liegt der `if (targetFolder)`-Zweig **vor** `classifyAttachment()` — der LLM-Aufruf ist für diese Typen unerreichbar |
| 2.d | (d) PDF/DOCX/XLSX/ODT/ODS/TXT/MD → LLM-Klassifizierung | PASS | `routeByExtension()` gibt für alle 9 Dokument-Endungen `null` zurück → Klassifizierungszweig |
| 2.e | Exact-Match statt Substring | PASS | Gezielt geprüft: `'mp4'` (ohne Punkt), `'.mp4x'` und `'.MP4'` (roh) matchen **nicht**; `Set.has()` ist exakt, kein `includes()`/Regex. Aufrufer lowercased korrekt via `path.extname(...).toLowerCase()` |
| 2.f | Doppel-Endungen nicht fehlgeroutet | PASS | `invoice.pdf.mp4` → `Video` (korrekt: `path.extname` nimmt nur die **letzte** Endung, die Datei *ist* ein MP4); `video.mp4.pdf` → LLM-Klassifizierung. Kein `.docx`, das als Audio/Video durchrutscht — alle 26 Endungen einzeln geprüft |
| 2.g | 20-KB-Müllgrenze gilt **nicht** für Video/Audio | PASS | Kleines `.mp4`/`.mp3` (100 Bytes) wird importiert — die Grenze ist bildspezifisch, wie im Tech Design gefordert |
| 2.h | Video/Audio in `SUPPORTED_EXTENSIONS` | PASS | Alle 10 Medien-Endungen in beiden Listen vorhanden (26 Endungen gesamt) |

#### AC-2.5 / PDF-Volltext in der Klassifizierung

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 2.5a | PDF-Volltext fließt in den Prompt | PASS | `fetchPdfText()` → `POST /attachment-text`, Ergebnis ersetzt den `(no extractable text …)`-Platzhalter. **BUG-4 aus Iteration 1 ist für PDF damit geschlossen** |
| 2.5b | TXT/MD unverändert direkt dekodiert | PASS | `PLAINTEXT_EXTENSIONS`-Zweig unverändert |
| 2.5c | Office ohne Volltext (bewusst, PROJ-91) | PASS (dokumentierte Abweichung) | DOCX/XLSX/ODT/ODS fallen weiterhin auf Dateiname+Kontext zurück — spec-konform |
| 2.5d | Fehler bei Extraktion → Fallback statt Abbruch | PASS | `fetchPdfText()` fängt **jeden** Fehler → `''` → bestehender Prompt-Fallback. Endpoint liefert für Nicht-PDF/Fehler `200` + leerer Text, löst also nicht einmal den catch-Zweig aus |
| 2.5e | Prompt-Längenbegrenzung greift | PASS | `.slice(0, 4000)` im Prompt **plus** `PLAINTEXT_MAX_CHARS = 50000` serverseitig — doppelt gedeckelt |

#### AC-4.x: Backfill Dry-Run

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 4.d1 | Dry-Run ist **Standard** (ohne `confirm`) | PASS | `Code: Init Backfill Run`: `CONFIRM = confirmRaw === true \|\| confirmRaw === 'true'` — Default false. Coercion akzeptiert Body **und** Query, Boolean **und** String |
| 4.d2 | Kein `/attachment`-Call, kein `writeFileSync`, kein `mkdirSync` im Dry-Run | PASS | Kontrollfluss selbst nachvollzogen: Im Kandidaten-Scan-Node existiert **überhaupt kein** `writeFileSync`/`mkdirSync`/`/attachment`-Aufruf (grep = 0 Treffer). Einziger Netzwerkaufruf ist Weaviate-GraphQL (Zeile 105); `fs` wird ausschließlich lesend via `existsSync()` genutzt. Der `return` mit `_dry_run` steht **vor** jedem Import-Zweig. Zusätzlich empirisch: Dry-Run gegen ein leeres Temp-Verzeichnis erzeugt **0 Dateien/0 Verzeichnisse** |
| 4.d3 | **`candidates_found` ist exakt der Umfang des echten Laufs** | PASS | **Gezielt geprüft (Kernrisiko):** Der Zählwert stammt aus **derselben** Pass-1/Pass-2-Kandidatenlogik wie der bestätigte Lauf — es gibt keinen divergenten/approximativen Zweig; der `if (!CONFIRM)`-Return sitzt **hinter** dem vollständigen Reconcile. Empirisch über 8 Szenarien bestätigt: `candidates_found` (Dry-Run) == Summe der `pendingAttachments` (confirmed) in **allen** Fällen, ebenso `pending_mails` == Anzahl Mail-Items. Getestet u.a.: gemischte Typen (3 von 6 Anhängen), EC-9-Geschwister (2), Teil-Import (1 von 2 verbleibend), bereits importiertes Video/Audio (0), mailübergreifend gleicher Basisname (2), nur-Müll-Mail (0) |
| 4.d4 | Response-Form `{ candidates_found, dry_run: true }` | PASS | `Code: Empty Summary` liefert `{ dry_run:true, candidates_found, pending_mails, message }` |
| 4.d5 | Beliebig wiederholbar, kein hängender Lock | PASS | Dry-Run läuft über `IF: Queue Empty` → `Code: Empty Summary`, wo die **owner-geprüfte Lua-Freigabe** auf `alice:dms:processor:lock:run` liegt + Redis-Cleanup. Zwei aufeinanderfolgende Dry-Runs simuliert: beide acquire+release sauber. Zusätzlich `PX: 1800000` als TTL-Backstop. Zwei identische Dry-Runs liefern identische Zahlen |
| 4.d6 | Kein `IF: Confirm Mode`-Node (Abweichung) | PASS (Abweichung akzeptabel) | Graph-Topologie ist **unverändert** (`connections` im Diff nicht angefasst) — die Abweichung vermeidet tatsächlich die duplizierte Lock-Freigabe, die der Implementer als Grund nennt. Verdrahtung verifiziert: `_empty:true` trifft die True-Branch von `IF: Queue Empty` |
| 4.d7 | `SCHEMAS` (countOnDisk) um Video/Audio erweitert | PASS | **Explizit gejagt (Drift-Risiko):** `SCHEMAS` enthält alle 7 Ordner; automatisiert geprüft, dass **jeder** Ordner aus `VALID_TARGET_FOLDERS` in `SCHEMAS` vorkommt. Empirisch: bereits importiertes `.mp4`/`.mp3` wird als erledigt erkannt (0 Kandidaten) → **kein** Endlos-Re-Import |

#### AC-5: `VALID_SCHEMAS` unangetastet

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 5.v1 | `VALID_SCHEMAS` enthält **kein** Video/Audio | PASS | In beiden Import-Nodes exakt die 5 DMS-Schemata, byte-identisch zwischen Laufzeit und Backfill |
| 5.v2 | LLM kann Video/Audio nicht zurückgeben | PASS | `parseClassification('{"document_type":"Video"}')` → `null`, ebenso `Audio`, `Email`, `BankTransaction` |
| 5.v3 | Zielordner-Gate an **jeder** Schreibstelle erweitert | PASS | `if (!VALID_TARGET_FOLDERS.has(targetFolder))` steht in **beiden** Import-Nodes unmittelbar vor `mkdirSync`/`writeFileSync` — Defence-in-Depth intakt |

### Duplizierungs-Audit (die vom Implementer selbst gemeldete Risikostelle)

Gezielt auf Drift zwischen den drei Fundstellen geprüft — **232 Assertions, 0 Abweichungen**:

| Konstante / Helper | Laufzeit (`alice-mail-sync`) | Backfill Kandidaten-Scan | Backfill Import | Ergebnis |
|---|---|---|---|---|
| `SUPPORTED_EXTENSIONS` (26) | ✔ | ✔ | (n/a — nutzt Kandidatenliste) | **identisch** |
| `IMAGE/VIDEO/AUDIO_EXTENSIONS` | ✔ | ✔ (nur IMAGE) | ✔ | **identisch** |
| `ATTACHMENT_MAX_BYTES` / `IMAGE_JUNK_MAX_BYTES` | ✔ | ✔ | ✔ | **identisch** |
| `VALID_SCHEMAS` / `VALID_TARGET_FOLDERS` | ✔ | (n/a) | ✔ | **identisch** |
| `SCHEMAS` (countOnDisk-Ordner) | (n/a) | ✔ 7 Ordner | (n/a) | **korrekt erweitert** |
| `routeByExtension()` | ✔ | (n/a) | ✔ | **verhaltensgleich** für alle 26 Endungen + 4 MIME-Varianten |
| Prefilter-Entscheidung | `prefilterAttachment()` | `isImportCandidate()` | Größencheck | **übereinstimmend** über 162 Endung×Größe-Kombinationen |

Die vom Implementer befürchtete Drift ist in dieser Iteration **nicht** eingetreten. Das Wartungsrisiko bleibt aber real (siehe BUG-5, hochgestuft).

### Regression Check (`a010f8f` → `5b2259e`)

- **Diff-Umfang:** `Dockerfile` (1 Zeile), `app.py` (+153/-32), 2 Workflow-JSONs, `INDEX.md`, Spec. Keine Änderung an anderen Workflows, Compose- oder SQL-Dateien.
- **Workflow-JSONs:** geändert wurden **ausschließlich** `jsCode`-Werte + eine Sticky Note (Text/Höhe). **`connections` in beiden Workflows unverändert** → Graph-Topologie, MQTT-Pfad (AC-5.1) und der Notification-/Status-Zweig unberührt. Keine Nodes hinzugefügt/entfernt (19 bzw. 18).
- **Iteration-1-Logik re-ausgeführt (82 Assertions, alle grün):**
  - `sanitizeFilename()` / `shortenSender()` / `buildBaseFilename()` — **unverändert**, 10 Path-Traversal-Payloads × 3 Zielordner (inkl. der neuen `Video/`, `Audio/`) × 2 Nodes: **kein einziger Ausbruch** aus `/mnt/nas/ai/<Ordner>/`.
  - `resolveCollision()` — **unverändert**, gegen echtes Dateisystem: 5× gleicher Name → `…Anhang.pdf, _1, _2, _3, _4`, kein Überschreiben, Suffix vor der Endung; gleiches Verhalten für `.mp4` in `Video/`. Laufzeit- und Backfill-Variante verhaltensgleich.
  - BUG-2-Fix (`countOnDisk` + globaler Zweit-Pass) — **intakt und jetzt auf 7 Ordner erweitert**: Teil-Import holt genau den fehlenden Anhang nach, mailübergreifend gleicher Basisname wird nicht falsch dedupliziert, EC-9-Geschwister beide importiert.
  - BUG-3-Fix (50-MB-Limit) — **intakt**: Grenzwerte 52428800 → Import / 52428801 → Skip an allen drei Stellen; Prüfung weiterhin **vor** dem Netzwerkaufruf.
  - Fehler-Isolation pro Anhang (`try/catch` + `continue`) und MQTT-Publish nur bei echtem Neu-Insert — **unverändert**.
- **`app.py`:** `/attachment`-Contract nach dem `_fetch_attachment_part()`-Refactoring **unverändert** — 4 Felder, Byte-Round-Trip über Base64 verlustfrei, 400/404-Verhalten identisch. `/fetch`, `/body`, `/test`, `/encrypt` nicht angefasst.
- **Statische Checks erneut grün:** beide JSONs valide, eindeutige Node-Namen/IDs, keine dangling Connection-/`$('Node')`-Referenzen, alle Code-Nodes `node --check` OK, **0 `console.log`**, `require` beschränkt auf `axios, redis, winston, crypto, fs, path`; `app.py` `py_compile` OK.

### Security Audit — Iteration 2

- [x] **`/attachment-text` nutzt exakt denselben Credential-Flow** — kein eigener Entschlüsselungspfad: Der Endpoint enthält **kein** `_decrypt_password` und **kein** `imap.login`, sondern ruft ausschließlich den gemeinsamen Helper `_fetch_attachment_part()` (Zeile 187) auf, der wie `/attachment` `_decrypt_password(data["password_enc"])` → `_connect()` → `login()` mit `readonly=True` ausführt und sauber ausloggt. Die übrigen drei `_decrypt_password`-Aufrufe gehören zu den unveränderten PROJ-46-Endpunkten (`/test`, `/fetch`, `/body`). **Kein neuer Klartext-Passwort-Pfad.**
- [x] **Kein Credential-/Pfad-Leak in der Response** — Response-Keys sind **exakt** `{text, page_count, truncated, status}`; mit Testwerten `password_enc="ENCSECRET"`, `host="mail.secret.de"`, `username="user@x"` erscheint **keiner** dieser Werte (und kein `/app`-/`/mnt`-Pfad) in der Antwort. Fehlerfälle liefern leeren Text statt Stacktrace.
- [x] **Kein Leak in den Logs** — `log.warning("PDF extraction failed for %s: %s", filename, exc)` loggt nur Dateiname + pypdf-Fehlertext, keine Credentials. Workflow-seitig loggt `fetchPdfText()` nur `uid`/`idx`/`e.message`.
- [x] **`pypdf` führt keine Injection-/Pfad-Risiken ein** — Eingabe ist ein **In-Memory-Puffer** (`PdfReader(io.BytesIO(payload))`), kein Dateipfad; es wird nichts auf Platte geschrieben und kein Subprozess gestartet. Rückgabe ist reiner extrahierter Text als JSON. Ein einzelner defekter Page-Parse ist gekapselt und verliert nicht den Rest des Dokuments.
- [x] **Kein 4xx/5xx-Fehlpfad, der den n8n-HTTP-Node in den Error-Zweig zwingt** — Nicht-PDF und Extraktionsfehler liefern nachweislich **HTTP 200** (5 Fallgruppen getestet, inkl. korruptes und leeres PDF).
- [x] **Zielordner-Segment weiterhin nicht angreifbar** — `Video`/`Audio` stammen aus einer festen Endungs-Allowlist, nicht aus LLM- oder Nutzereingabe; `VALID_TARGET_FOLDERS`-Gate vor jedem Schreibzugriff.
- [x] **Path-Traversal für die neuen Ordner mitgeprüft** — 10 Payloads auch in `Video/`/`Audio/`-Dateinamen: kein Ausbruch.
- [x] **Speicher-Risiko (BUG-3) nicht reintroduziert** — `/attachment-text` gibt **keine** Rohbytes zurück (Antwort ≤ ~50 KB Text, unabhängig von der PDF-Größe). Der 50-MB-Check greift **vor** jedem `/attachment-text`-Aufruf (Prefilter → `continue` steht in beiden Nodes **vor** `fetchPdfText()`), ein übergroßes PDF erreicht `pypdf` über diesen Workflow also nie. Siehe BUG-8 für die verbleibende theoretische Lücke bei Direktaufruf.
- [ ] **INFO (unverändert, kein Regress): Webhook ohne Authentifizierung** — Projektkonvention (VPN-only), identisch zu allen anderen Backfill-Workflows. Der Dry-Run **entschärft** dieses Risiko sogar, da ein versehentlicher Aufruf jetzt folgenlos ist.

**Ergebnis:** Keine neue Sicherheitslücke durch Iteration 2.

### Bugs Found — Iteration 2

Keine neuen Critical/High/Medium-Bugs. Zwei Low-Befunde:

#### BUG-8: `/attachment-text` hat keine eigene Größenobergrenze (Defence-in-Depth-Lücke)
- **Severity:** Low
- **Root Cause:** `ATTACHMENT_MAX_BYTES` existiert nur workflow-seitig (n8n). `app.py` kennt keine Obergrenze; `_extract_pdf_text()` lädt das PDF komplett via `PdfReader(io.BytesIO(payload))` in den Speicher.
- **Tatsächliches Verhalten:** Über die **PROJ-53-Workflows nicht auslösbar** — der 50-MB-Prefilter greift nachweislich vor jedem `/attachment-text`-Aufruf (verifiziert in beiden Nodes). Ein **direkter** Aufruf des Endpoints (VPN-intern, Webhook/Service ohne Auth) mit der UID eines 200-MB-PDFs würde die Mail jedoch vollständig in den Speicher des `alice-mail-reader`-Containers laden. Betroffen wäre nur dieser Container (2 gunicorn-Worker), nicht der geteilte n8n-Prozess — der eigentliche BUG-3-Schadensfall ist damit **nicht** reintroduziert.
- **Steps to Reproduce:** 1. `POST /attachment-text` direkt (nicht über den Workflow) mit UID einer Mail mit sehr großem PDF-Anhang. 2. Erwartet: kontrollierte Ablehnung. 3. Tatsächlich: vollständiger RFC822-Fetch + pypdf-Parse im Speicher.
- **Bewertung:** Reine Defence-in-Depth-Lücke; der reale Aufrufpfad ist abgesichert. Analog `/attachment` (hatte in Iteration 1 dieselbe Eigenschaft und wurde als akzeptabel bewertet). Mitigierbar durch ein `len(payload)`-Limit im gemeinsamen Helper.
- **Priority:** Nice to have

#### BUG-9: Dry-Run schreibt trotzdem den Mailbox-Credential-Cache nach Redis
- **Severity:** Low (kosmetisch)
- **Root Cause:** `Code: Cache Mailboxes` liegt im Graphen **vor** `Code: Fetch Mails With Attachments` und läuft daher auch im Dry-Run.
- **Tatsächliches Verhalten:** Ein Dry-Run legt kurzzeitig `alice:mail:backfill:mailboxes` an (Passwörter bleiben dabei **verschlüsselt**, `password_enc` unverändert). `Code: Empty Summary` löscht den Key auf dem Weg nach draußen wieder — es bleibt **kein** Residuum. Es findet **keine** IMAP-Verbindung statt; die Spec-Zusage "keine IMAP-Verbindung, kein NAS-Write" ist eingehalten.
- **Bewertung:** Streng genommen ist der Dry-Run damit nicht 100 % seiteneffektfrei, praktisch aber folgenlos (verschlüsselte Daten, sofort wieder gelöscht, TTL 86400 s als Backstop). Nur relevant, falls jemand "Dry-Run schreibt nichts" wörtlich als Audit-Zusage liest.
- **Priority:** Nice to have (ggf. nur dokumentieren)

#### BUG-5 (aus Iteration 1): Hochstufung Low → **Medium** empfohlen
- **Status:** weiterhin **offen**, in dieser Iteration **nicht** schadenswirksam geworden (alle drei Kopien nachweislich synchron).
- **Begründung der Hochstufung:** Der Implementer hat selbst gemeldet, dass Iteration 2 die Allowlist an drei Stellen **gleichzeitig** ändern musste und dass `fetchPdfText()` bewusst **nicht** byte-identisch ist (Laufzeit liest `ctx.host`/`ctx.passwordEnc`, Backfill `mailbox.imap_host`/`mailbox.password_enc`). Das ist bestätigt. Der Fehlerfall wäre **still**: Ein vergessener Kandidaten-Scan hätte Video/Audio dauerhaft als "nichts zu tun" gewertet (kein Log) bzw. bei fehlendem `SCHEMAS`-Eintrag jeden Lauf Duplikate erzeugt. Beides wurde diesmal vermieden — die Wahrscheinlichkeit steigt aber mit jeder weiteren Iteration.
- **Priority:** Fix in next sprint (vor einer dritten Iteration mit weiteren Formaten) — **kein Deployment-Blocker**

### Nicht bestätigte Verdachtsmomente (Negativbefunde)

Gezielt gesucht, **nicht** vorhanden:

- **Dry-Run zählt falsch (über-/unterzählt):** Kein Fehler. Identische Kandidatenlogik, empirisch über 8 Szenarien gegen den confirmed-Pfad abgeglichen.
- **Dry-Run löst doch IMAP/NAS-Zugriff aus:** Kein Fehler. Im Scan-Node existiert kein einziger `/attachment`-, `mkdirSync`- oder `writeFileSync`-Aufruf.
- **Substring-Bug im Extension-Match:** Kein Fehler — `Set.has()`, exakte Treffer; `'mp4'`, `'.mp4x'` matchen nicht.
- **Doppel-Endung `invoice.pdf.mp4` fehlgeroutet:** Kein Fehler im Sinne einer Fehlklassifizierung — `path.extname` liefert `.mp4`, die Datei ist ein MP4 und gehört nach `Video/`.
- **`.docx` versehentlich als Audio/Video geroutet:** Kein Fehler — alle 26 Endungen einzeln geprüft, alle 9 Dokumenttypen gehen in die LLM-Klassifizierung.
- **Video/Audio in `VALID_SCHEMAS` durchgesickert:** Kein Fehler — beide Listen sauber getrennt, LLM kann Video/Audio nicht liefern.
- **`SCHEMAS`-Drift (2 von 3 Stellen erweitert):** Kein Fehler — alle drei Stellen konsistent.
- **Hängender Lock nach Dry-Run:** Kein Fehler — owner-geprüfte Freigabe im Dry-Run-Pfad, TTL als Backstop, zwei Läufe hintereinander sauber.
- **`/attachment-text` bricht den n8n-Error-Zweig:** Kein Fehler — 200 in allen Nicht-PDF-/Fehlerfällen.
- **Regression an `resolveCollision`/`sanitizeFilename`/`countOnDisk`:** Kein Fehler — unverändert, re-ausgeführt.

### Nicht verifizierbar in dieser Umgebung

| # | Kriterium | Grund |
|---|-----------|-------|
| NV-1 | `pypdf` installiert im **Alpine**-Image | `pypdf==5.1.0` steht korrekt in der `pip install`-Zeile des `Dockerfile` (reines py3-none-any-Wheel, Alpine-tauglich) und wurde lokal im venv gegen echte PDFs getestet — der **Image-Build** steht aus. `alice-mail-reader` muss **neu gebaut** werden (`docker compose build`), ein Restart genügt nicht |
| NV-2 | Ende-zu-Ende-Lauf gegen IMAP/Ollama/Weaviate/NAS | Kein Zugriff in dieser Umgebung |
| NV-3 | AC-5.2 / AC-5.3 (Mail-Thumbnail-Rendering) | Unverändert offen aus Iteration 1 |
| NV-4 | Reale PDF-Klassifizierungsqualität | Hängt vom LLM ab; der Volltext erreicht den Prompt nachweislich |

### Summary — Iteration 2

- **Acceptance Criteria (neu/geändert):** **25/25 PASS**, 0 FAIL. Alle vier Ergänzungen sind vollständig und korrekt umgesetzt.
- **Kernrisiken der Aufgabenstellung:** alle vier gezielt geprüft und **entkräftet** — Dry-Run-Zählung ist exakt (nicht divergent), Extension-Routing-Reihenfolge stimmt (kein LLM-Aufruf für Medien, kein Dokument im falschen Ordner), keine `SUPPORTED_EXTENSIONS`/`SCHEMAS`-Drift, `VALID_SCHEMAS` unangetastet.
- **Regression:** **keine.** Iteration-1-Logik (BUG-2-Dedup, BUG-3-Limit, Pfad-Sanitisierung, Kollisions-Suffix, Fehler-Isolation, MQTT-nur-bei-Neu-Insert) unverändert und re-verifiziert; `connections` beider Workflows byte-identisch.
- **Bugs:** 2 neue (BUG-8, BUG-9 — beide **Low**, beide über den realen Aufrufpfad nicht auslösbar) + Empfehlung, BUG-5 auf Medium hochzustufen (Wartungsschuld, kein Funktionsfehler). **0 Critical, 0 High, 0 blockierende Medium.**
- **Security:** **Pass.** Kein neuer Credential-Pfad, kein Leak in Response/Logs, `pypdf` arbeitet rein In-Memory ohne Pfad-/Subprozess-Risiko.
- **Production Ready:** **YES — READY**
- **Recommendation:** **Deploy** — mit der zwingenden Voraussetzung, dass `alice-mail-reader` **neu gebaut** wird (NV-1); ohne `pypdf` im Image schlägt jeder `/attachment-text`-Aufruf fehl. Das degradiert zwar nur (leerer Text → Fallback auf Dateiname+Kontext, also Iteration-1-Verhalten) und bricht den Import nicht, würde aber den Hauptzweck von Iteration 2 stillschweigend aushebeln. Nach dem Deploy: Backfill zuerst **ohne** `confirm` aufrufen und die Kandidatenzahl prüfen; danach AC-5.2/5.3 gegen den laufenden Thumbnailer verifizieren.

---

## QA Test Results — Bugfix-Nachprüfung `confirm`-Parameter (2026-08-23)

**Tested:** 2026-08-23
**Tester:** QA Engineer (AI)
**Commit under test:** `8581996` (Diff-Basis: `b1c47cc` = Stand der als Approved abgenommenen Iteration 2)
**Scope:** Gezielte Nachprüfung des Produktivfehlers "Backfill lief trotz `{"confirm": true}` im Dry-Run" + `MAX_RUNTIME_SECONDS`-Totkonfiguration + eng gefasster Regressionscheck. **Kein** vollständiger Feature-Review (Iteration 1+2 sind abgenommen).

### Methodik: Graph-Trace statt isoliertem Funktionstest (der eigentliche Lernpunkt)

Dieser Durchlauf verwendet bewusst eine **andere Methodik** als die vorherige Prüfung, weil **genau die Methodik der Iteration-2-QA den Bug durchgelassen hat**: Iteration 2 hat die `confirm`-Auswertung isoliert getestet, indem sie dem extrahierten Node-Code ein **handgefüttertes** `$input.first().json = { body: { confirm: true } }` untergeschoben hat. Unter dieser Annahme war die Coercion-Logik tatsächlich korrekt — der Test war grün, der Node in Produktion trotzdem kaputt. Der Fehler saß **nicht in der Funktion, sondern in der Annahme über ihren Input**: Der reale Vorgänger-Node liefert diesen Input nie. Ein isolierter Funktionstest kann diese Fehlerklasse **prinzipiell nicht** finden, weil er den Input selbst erfindet.

Konsequenz für diesen Durchlauf — der Ausführungspfad wurde **nicht angenommen, sondern abgeleitet und ausgeführt**:

1. **Pfadableitung aus dem `connections`-JSON** (DFS vom Trigger-Node, unabhängig in Python und JS re-implementiert) statt aus der Beschreibung des Entwicklers oder aus dem Node-Layout.
2. **Ausführung des tatsächlich ausgelieferten Node-Codes** entlang dieses Pfads, in korrekter Reihenfolge, mit n8n-getreuer Semantik: `$input` liefert **ausschließlich** die Items des direkten Graph-Vorgängers; `$('X')` liefert die Run-Daten des Nodes X aus **dieser** Ausführung. Nur `redis`/`winston` sind gemockt (In-Memory-Store), der Payload-Fluss ist echt.
3. **IF-Node aus seiner ausgelieferten Condition ausgewertet** (`={{ $json._lock_acquired }}` strict boolean equals `true`), nicht als angenommener Durchreicher.

**Abgeleiteter Pfad (aus `connections`, nicht angenommen) — genau ein Pfad Webhook → Init:**

```text
Webhook: POST /attachment-backfill
  --[out 0]--> Code: Acquire Backfill Lock
  --[out 0]--> IF: Lock Acquired
  --[out 0]--> Code: Init Backfill Run
```

Damit ist die im Fix-Commit behauptete Topologie **unabhängig bestätigt**. `Code: Init Backfill Run` hängt an der **True**-Branch (Output-Index 0) von `IF: Lock Acquired`.

**Testumfang: 37 Assertions Graph-Trace (0 Fehler)** + 4 Assertions Payload-/Trigger-Audit + statische Checks.

### Verifikation des Node-Namens-Lookups (Silent-Failure-Risiko)

Ein getippfehlerter Node-Name in `$('…')` ist die naheliegendste Art, wie dieser Fix selbst hätte fehlschlagen können. Gezielt geprüft:

| # | Prüfung | Status | Nachweis |
|---|---------|--------|----------|
| N-1 | Referenzierter Name stimmt **exakt** mit dem Webhook-Node überein | PASS | Aus dem Code extrahiert: `$('Webhook: POST /attachment-backfill')`; Zeichen-für-Zeichen-Vergleich gegen `nodes[].name` → identisch (inkl. Leerzeichen und `/`) |
| N-2 | Alle `$('Node')`-Referenzen **beider** Workflows lösen auf | PASS | 8 Referenzen im Backfill, alle vorhanden; 0 dangling. In `alice-mail-sync` ebenfalls 0 dangling |
| N-3 | Referenzierter Node ist **Vorfahr** im Graphen (nicht nur existent) | PASS | Ancestor-Berechnung über die invertierten `connections`: `Webhook…` ist Vorfahr von `Init`; `Init`+`Lock` sind Vorfahren von `Time Check`; `Init` ist Vorfahr von `Fetch Mails` — alle Lookups sind zur Laufzeit garantiert befüllt |
| N-4 | Ein falscher Name würde **laut** scheitern, nicht still | PASS | Simuliert: Lookup ohne Run-Daten wirft (`No run data for …`) → n8n bricht den Node ab. Kein stilles `undefined` — der Fix kann nicht unbemerkt wirkungslos werden |
| N-5 | `Init` liest den Payload **nicht mehr** über `$input` | PASS | Nach Entfernen aller Kommentare/Blockkommentare: **0** `$input`-Vorkommen im ausführbaren Code des Nodes (die zwei Treffer im Rohtext stehen ausschließlich im erklärenden Kommentar) |

### Root-Cause-Reproduktion (Punkt 2 der Aufgabe)

Der Lock-Node wurde **ausgeführt**, nicht gelesen:

- `Code: Acquire Backfill Lock` liest `$input` an keiner Stelle und gibt ein frisch konstruiertes Item zurück. Tatsächlicher Output-Key-Satz aus der Ausführung: **`["_lock_acquired","_lock_error","lock_owner"]`** — `body`/`query`/`headers` sind **nachweislich `undefined`**. Root Cause reproduziert.
- `IF: Lock Acquired` reicht dieses Item bei erfolgreichem Acquire unverändert über Output 0 weiter (aus der ausgelieferten Condition ausgewertet). Es findet **kein** Merge des Webhook-Payloads statt.
- An der Stelle, an der `Code: Init Backfill Run` läuft, löst `$('Webhook: POST /attachment-backfill').first().json` auf die **Original-Webhook-Items** auf — `body.confirm` ist intakt. Bestätigt: Es ist genuin der Webhook-Payload, nicht das Lock-Item.
- **Gegenprobe mit dem Pre-Fix-Code** auf **demselben** Trace: liefert `confirm=false`. Der Produktionsbug ist damit auf diesem Trace reproduziert **und** der Fix auf demselben Trace als wirksam belegt — nicht nur behauptet.

### `confirm`-Parsing: alle Szenarien über den vollen Pfad (Punkt 3)

Jede Zeile ist ein **vollständiger** Durchlauf Webhook → Lock → IF → Init mit ausgeführtem Node-Code, keine Direktaufrufe der Coercion.

| # | Aufruf | Erwartet | Tatsächlich | Status |
|---|--------|----------|-------------|--------|
| C-1 | **`POST {"confirm": true}`** (exakte Produktions-Repro) | `confirm: true` | **`{"confirm":true,"MAX_RUNTIME_SECONDS":7200}`** | **PASS** — der gemeldete Fehler ist behoben |
| C-2 | Kein Body, keine Query (`body:{}`, `query:{}`) | `false` (Dry-Run bleibt Default) | `false` | PASS |
| C-3 | `body`/`query` im Payload gar nicht vorhanden | `false` | `false` | PASS — kein Crash trotz fehlender Felder (`item.body \|\| {}`) |
| C-4 | `?confirm=true` als **Query-Parameter** | `true` | `true` | PASS |
| C-5 | `{"confirm": "true"}` als **String** | `true` | `true` | PASS |
| C-6 | `{"confirm": true}` als **Boolean** | `true` | `true` | PASS |
| C-7 | `{"confirm": false}` explizit | `false` | `false` | PASS |
| C-8 | `{"confirm": "false"}` als String | `false` | `false` | PASS |
| C-9 | `{"confirm": 1}` (numerisch) | `false` | `false` | PASS — strikte Coercion, kein Truthy-Fallstrick |
| C-10 | Body `confirm:false` + Query `confirm:true` | `false` (Body gewinnt) | `false` | PASS — Präzedenz wie im Referenz-Workflow |

**Der Default kippt nicht:** In allen vier Fällen ohne expliziten `true`-Wert (C-2, C-3, C-7, C-8, C-9) bleibt `confirm=false` — die Sicherheitszusage "ohne `confirm` passiert nichts" ist intakt.

### `MAX_RUNTIME_SECONDS` (Punkt 4)

`Code: Time Check` wurde ebenfalls **ausgeführt**, mit `Split In Batches` als direktem Input (so wie im Graphen) und `$('Code: Init Backfill Run')` aus den echten Run-Daten des vorangegangenen Init-Laufs.

| # | Szenario | Erwartet | Tatsächlich | Status |
|---|----------|----------|-------------|--------|
| M-1 | Kein Override → Init emittiert Default | `7200` | `7200` | PASS |
| M-2 | Default 7200, 1000 s Laufzeit | `_time_limit_reached: false` | `false` | PASS |
| M-3 | Default 7200, 7300 s Laufzeit | `true` | `true` | PASS — Default greift weiterhin korrekt |
| M-4 | `max_runtime_seconds: 180` im Body → Init | `180` | `180` | PASS |
| M-5 | **Override 180, 1000 s Laufzeit** | `true` | `true` | **PASS — Beweis, dass `Time Check` den Wert wirklich konsumiert.** Mit dem alten hartkodierten `7200` wäre hier `false` herausgekommen |
| M-6 | Override 180, 100 s Laufzeit | `false` | `false` | PASS |
| M-7 | `?max_runtime_seconds=300` als Query-String | `300` | `300` | PASS |
| M-8 | Müll-Overrides `"abc"`, `0`, `-5`, `""` | Fallback `7200` | jeweils `7200` | PASS (4 Assertions) — `parseInt`+`>0`-Guard hält |

Die tote Konfiguration ist damit real behoben, nicht nur umgeschrieben.

### Downstream-Konsumenten (Punkt 5)

| # | Prüfung | Status | Nachweis |
|---|---------|--------|----------|
| D-1 | Output-**Shape** von `Init` unverändert | PASS | Ausgeführter Output-Key-Satz ist exakt `["MAX_RUNTIME_SECONDS","confirm"]` — dieselben zwei Felder wie vor dem Fix, keine Umbenennung, kein Zusatzfeld |
| D-2 | `confirm` ist weiterhin **Boolean** | PASS | `typeof === 'boolean'` in allen 10 Szenarien; `Fetch` vergleicht mit `=== true`, ein String hätte still zu Dry-Run geführt |
| D-3 | `Code: Fetch Mails With Attachments` liest korrekt | PASS | Node-Code **unverändert** (Hash-Vergleich `b1c47cc` vs. `8581996`): `$('Code: Init Backfill Run').first().json.confirm === true`. Der Konsumenten-Ausdruck wurde gegen die echten Init-Run-Daten ausgewertet → `true` bei bestätigtem Lauf, `false` bei Dry-Run |
| D-4 | `Init` bleibt einziger Payload-Leser | PASS | Audit über **alle** Nodes beider Workflows (kommentarbereinigt): `Code: Init Backfill Run` ist die **einzige** Stelle, die `.body`/`.query` liest |

### Regression (Punkt 6) — Diff `b1c47cc..8581996`

- **Diff-Umfang:** `features/INDEX.md` (1 Zeile), Spec (+42/-1), `workflows/alice-mail-attachment-backfill.json` (**+2/-2**). **Keine** Änderung an `alice-mail-sync.json`, `app.py`, `Dockerfile`, Compose- oder SQL-Dateien. Der Fix ist so eng gefasst wie im Commit beschrieben.
- **Node-für-Node-Vergleich** des Backfill-Workflows (`jsCode`-Vergleich aller 10 Code-Nodes gegen `b1c47cc`): geändert sind **exakt** `Code: Init Backfill Run` und `Code: Time Check`. Die übrigen 8 (`Acquire Backfill Lock`, `Respond Already Running`, `Cache Mailboxes`, `Fetch Mails With Attachments`, `Empty Summary`, `Import Mail Attachments`, `Track Progress`, `Build Summary`) sind **byte-identisch**.
- **`connections` beider Workflows byte-identisch**, Node-Anzahl (18 bzw. 19) und Node-Namen unverändert → Graph-Topologie nicht angefasst, MQTT-Pfad (AC-5.1) und Notification-/Status-Zweig unberührt.
- **Iteration-1/2-Logik nicht angetastet** (diff-gescopte Prüfung, keine Wiederholung der 467-Assertion-Suite — der Diff berührt keine dieser Funktionen): `countOnDisk`/globaler Zweit-Pass (BUG-2-Fix), `resolveCollision`, `sanitizeFilename`/`shortenSender` (Path-Traversal), `ATTACHMENT_MAX_BYTES = 52428800` (BUG-3-Fix), `routeByExtension`, `VALID_TARGET_FOLDERS`, `fetchPdfText`/`/attachment-text` — alle in **unveränderten** Nodes und im HEAD-Stand unverändert vorhanden.
- **Statische Checks grün:** beide JSONs valide, eindeutige Node-Namen/IDs, 0 dangling Connection-/`$('Node')`-Referenzen, alle **15** Code-Nodes `node --check` OK, **0 `console.log`**, `require` weiterhin auf `axios, crypto, fs, path, redis, winston` beschränkt.
- **Security:** unverändert. Der Fix ändert nur, **woher** ein bereits zuvor gelesener Parameter stammt; keine neue Eingabe, kein neuer Schreibpfad, kein neuer Credential-Fluss, keine neue Log-Zeile mit Nutzerdaten. Der Webhook bleibt ohne Auth (bekannte Projektkonvention, VPN-only) — durch den **jetzt tatsächlich wirksamen** Dry-Run-Default ist ein versehentlicher Aufruf sogar folgenloser als vorher.

### Sanity-Check `alice-mail-sync` (Punkt 7) — nicht betroffen

| # | Prüfung | Status | Nachweis |
|---|---------|--------|----------|
| S-1 | Kein Webhook-Trigger | PASS | Einziger Trigger ist `Schedule: Every Minute` (`n8n-nodes-base.scheduleTrigger`); **kein** Node vom Typ `n8n-nodes-base.webhook` → es existiert gar kein Webhook-Payload, der verloren gehen könnte |
| S-2 | Kein Node liest `body`/`query` | PASS | Audit über alle 19 Nodes (kommentarbereinigt): 0 Treffer |
| S-3 | `$input`-Konsumenten lesen einen echten Vorgänger-Output | PASS | Die drei `$input`-Nutzer geprüft: `Notify: Passthrough` und `Code: Import Attachments` hängen beide an `Process + Classify + Store Emails` (das `{processed, wichtig, maxUid, storedEmails}` liefert — genau was sie lesen); `Code: Split Stored Emails` hängt an `Code: Import Attachments`. **Kein** payload-verwerfender Node dazwischen |
| S-4 | Alle `$('Node')`-Referenzen lösen auf | PASS | 0 dangling |

**Ergebnis:** Die Fehlerklasse ist in `alice-mail-sync` **nicht anwendbar** — bestätigt, nicht angenommen.

### Bugs Found

**Keine neuen Bugs in PROJ-53.** Der gemeldete Produktivfehler ist behoben; es sind keine neuen Critical/High/Medium-Befunde entstanden.

#### BUG-10 (behoben, verifiziert): `confirm`-Parameter im Backfill dauerhaft wirkungslos
- **Status:** **BEHOBEN in `8581996` — per Graph-Trace verifiziert**
- **Severity:** **High** (nachträglich eingestuft) — der Import war über den Webhook **überhaupt nicht auslösbar**; das Hauptfeature des Backfills war in Produktion unerreichbar, und der Fehler war stumm (kein Log, plausibel aussehende Dry-Run-Antwort).
- **Root Cause:** `Code: Init Backfill Run` las den Payload über `$input`, obwohl der Graph-Vorgänger `Code: Acquire Backfill Lock` ein neues Item ohne `body`/`query` zurückgibt.
- **Repro (verifiziert):** `POST /alice-mail-attachment-backfill` mit `{"confirm": true}` → vor dem Fix `confirm=false` (Dry-Run), nach dem Fix `confirm=true`.
- **Warum von QA-Iteration 2 übersehen:** isolierter Funktionstest mit handgefüttertem Input — siehe Methodik-Abschnitt oben. **Prozess-Lehre: Bei Nodes, die Trigger-Payload auswerten, ist der Ausführungspfad aus `connections` abzuleiten und mitzuführen; ein Funktionstest allein ist nicht ausreichend.**

#### BUG-11 (behoben, verifiziert): `MAX_RUNTIME_SECONDS` war tote Konfiguration
- **Status:** **BEHOBEN in `8581996` — verifiziert** (M-1 bis M-8)
- **Severity:** Low — kein Fehlverhalten im Regelbetrieb (der hartkodierte Wert entsprach dem Default), aber eine stille Falle: ein Verstellen des Werts blieb wirkungslos, was beim Debugging in die Irre führt.

#### BUG-12 (offen, **außerhalb PROJ-53**): dieselbe Fehlerklasse in zwei fremden Backfill-Workflows
- **Severity:** Medium (in den betroffenen Features, nicht in PROJ-53)
- **Befund:** Der Audit wurde über **alle 10 Webhook-Workflows** ausgeführt (Payload-Quelle jeweils durch Passthrough-Nodes wie `IF` hindurch bis zum ersten datenerzeugenden Node zurückverfolgt). Betroffen sind **zwei**:
  - `alice-dms-language-backfill` → `Code: Init Backfill Run` (bereits als **PROJ-92** auf der Roadmap erfasst)
  - `alice-dms-classification-backfill` → `Code: Init Backfill Run` (**vom Fix-Commit noch nicht genannt** — der Commit stufte diesen Workflow als "wertet keinen Webhook-Payload aus" ein; der Trace zeigt, dass er es doch tut und dieselbe Vorgänger-Konstellation hat)
  - Nicht betroffen: `alice-dms-thumbnailer-backfill`, `alice-dms-image-description-backfill` (Payload-Quelle ist ein HTTP-Node, der den Payload nicht verwirft), `alice-dms-folder-api`, `alice-mail-api`, `alice-mail-tools`, `alice-session-api`, `alice-tool-search`.
- **Empfehlung:** PROJ-92 um `alice-dms-classification-backfill` erweitern. **Kein PROJ-53-Blocker** — beide Workflows sind hier nicht angefasst worden.

### Nicht verifizierbar in dieser Umgebung

| # | Kriterium | Grund |
|---|-----------|-------|
| NV-1 | Lauf gegen echtes n8n/IMAP/Ollama/Weaviate/NAS | Kein Zugriff. Der Graph-Trace bildet die n8n-Semantik (`$input` = direkter Vorgänger, `$('X')` = Run-Daten) nach, ersetzt aber keinen Produktivlauf. `redis`/`winston` sind gemockt — der Payload-Fluss selbst ist echt |
| NV-2 | `mcp__n8n-mcp__*`-Validierung | Tools in dieser Session nicht verfügbar; erneut strukturelle Eigenvalidierung |
| NV-3 | AC-5.2 / AC-5.3 (Mail-Thumbnail-Rendering) | Unverändert offen aus Iteration 1/2 |
| NV-4 | `pypdf` im Alpine-Image (NV-1 aus Iteration 2) | Unverändert offen — `alice-mail-reader` muss beim Deploy **neu gebaut** werden |

### Summary — Bugfix-Nachprüfung

- **Graph-Trace durchgeführt:** ja. Pfad `Webhook → Lock → IF(true) → Init` aus dem `connections`-JSON **abgeleitet** (genau ein Pfad) und der ausgelieferte Node-Code entlang dieses Pfads ausgeführt.
- **Produktions-Repro:** `POST {"confirm": true}` liefert jetzt `confirm: true`. Pre-Fix-Code auf demselben Trace liefert `false` — Fehler reproduziert **und** Behebung belegt.
- **Ergebnis:** **37/37 Graph-Trace-Assertions grün**, 10/10 `confirm`-Szenarien korrekt, 11/11 `MAX_RUNTIME_SECONDS`-Assertions korrekt, Downstream-Konsument unbeeinflusst, Regression auf 2 Nodes begrenzt und `connections` unverändert.
- **Bugs:** BUG-10 (High) und BUG-11 (Low) **behoben und verifiziert**; BUG-12 betrifft **fremde** Workflows (PROJ-92 erweitern). **0 offene Critical/High/Medium in PROJ-53.**
- **Security:** **Pass** — keine Änderung der Angriffsfläche.
- **Production Ready:** **YES — READY**
- **Recommendation:** **Approved.** Deploy-Voraussetzungen aus Iteration 2 bleiben bestehen: `alice-mail-reader` **neu bauen** (`pypdf`), Backfill zuerst **ohne** `confirm` aufrufen (dieser Default ist jetzt nachweislich der einzige Weg, der nichts tut — und `confirm: true` ist nachweislich der Weg, der importiert), danach AC-5.2/5.3 gegen den laufenden Thumbnailer prüfen.

---

## Iteration 3 — Bugs aus Live-Deployment-Test (2026-08-23)

Nach Deployment (inkl. `alice-mail-reader`-Rebuild) und erstem produktiven Test hat Andreas zwei Probleme gemeldet:

### Bug A: Text-Anhänge werden systematisch nicht klassifiziert (`confidence=0, fallback=true` bei praktisch allen Nicht-Bild-Anhängen)

**Root Cause gefunden:** In `Code: Import Attachments` (`alice-mail-sync.json`) und `Code: Import Mail Attachments` (`alice-mail-attachment-backfill.json`) ist das Ollama-Modell für die Textklassifizierung falsch gesetzt:

```js
let ollamaModel = 'qwen3.5:27b-q4_K_M'; try { ollamaModel = $env.OLLAMA_MODEL_DMS || 'qwen3.5:27b-q4_K_M'; } catch(e) {}
```

`qwen3.5:27b-q4_K_M` ist laut `docker/compose/automations/n8n/.env.example` als `OLLAMA_VISION_MODEL` registriert (Bildbeschreibung/OCR-Pfade, z.B. `dms-extractor-image`) — **kein** Textklassifizierungsmodell. Der korrekte Wert (siehe `alice-dms-classify-document.json`, PROJ-78) ist `$env.OLLAMA_MODEL_DMS` (in `.env.example` = `mistral-small3.2:24b`) mit Fallback-Default `qwen3:14b`. Ein Vision-Modell auf einen reinen Text-Klassifizierungs-Prompt angesetzt liefert vermutlich unzuverlässig valides JSON im geforderten Format → Parse-Fehler bzw. `unclear` bei praktisch jedem Aufruf → der bestehende Unsicherheits-Fallback auf `Document` (siehe PROJ-78-Verhalten) greift dadurch systematisch statt in der Ausnahme.

**Fix:** Modell-Default/Fallback in beiden Workflows auf `$env.OLLAMA_MODEL_DMS || 'qwen3:14b'` korrigieren, exakt wie in `alice-dms-classify-document.json`.

### Bug B: Bild-Anhänge landen in `Document/` statt in einem eigenen `Image/`-Ordner

**Klarstellung nach Prüfung:** Die Weaviate-Klassifizierung selbst ist technisch nicht falsch — der bestehende DMS-Scanner (`Switch: Route by Type` in `alice-dms-path-worker.json`) routet Dateien ausschließlich nach Datei-Endung (`file_type`) in die passende Pipeline (u.a. ins eigenständige Weaviate-Schema `Image` mit KI-Bildbeschreibung/EXIF/GPS-Geocoding), unabhängig vom Quellordner. Ein `.jpg` in `Document/` würde also bereits korrekt als `Image`-Objekt landen, sobald der Ordner überwacht wird.

Dennoch: Konsistent mit der Ordnerstruktur der übrigen fünf DMS-Schemata (+ `Video`/`Audio` aus Iteration 2) soll es einen eigenen `Image/`-Zielordner geben, damit die physische Ablage auf dem NAS nicht irreführend ist (ein Mensch, der den Ordner durchsucht, erwartet Bilder nicht in `Document/`).

**Fix:** Neuer Zielordner `/mnt/nas/ai/Image/` (analog `Video/`/`Audio/`, automatisch angelegt). Extension-Routing (siehe Iteration 2) wird angepasst: Bild-Anhänge (jenseits der 20-KB-Müll-Grenze) routen künftig nach `Image/` statt `Document/`. Betrifft `alice-mail-sync.json` und `alice-mail-attachment-backfill.json` (`routeByExtension()`-Funktion in beiden).

### Ergänzung Acceptance Criteria (Zielordner-Struktur)

- [x] Zusätzlich zu `Invoice/`, `BankStatement/`, `Document/`, `Contract/`, `SecuritySettlement/`, `Video/`, `Audio/` existiert `/mnt/nas/ai/Image/` als Ablageziel für Bild-Anhänge
- [x] Bild-Anhänge (jenseits der 20-KB-Müll-Grenze) werden nach `Image/` geroutet, nicht nach `Document/`
- [x] Text-Anhänge (PDF/DOCX/XLSX/ODT/ODS/TXT/MD) werden mit dem korrekten DMS-Textklassifizierungsmodell (`$env.OLLAMA_MODEL_DMS`, Fallback `qwen3:14b`) klassifiziert, nicht mit dem Vision-Modell

**Nächste Schritte:** `/backend` für beide Fixes, dann erneut `/qa` (inkl. Regressionsprüfung, dass die Änderung des Modell-Fallbacks nicht versehentlich andere Aufrufer/Workflows betrifft, da `OLLAMA_MODEL_DMS` projektweit gesetzt ist).

### Implementation Notes (Iteration 3)

**Bug A — falsches Ollama-Modell (behoben).**

In beiden PROJ-53-Code-Nodes wurde der Fallback-Literal korrigiert:

```js
- let ollamaModel = 'qwen3.5:27b-q4_K_M'; try { ollamaModel = $env.OLLAMA_MODEL_DMS || 'qwen3.5:27b-q4_K_M'; } catch(e) {}
+ let ollamaModel = 'qwen3.5:27b-q4_K_M'; try { ollamaModel = $env.OLLAMA_MODEL_DMS || 'qwen3:14b'; } catch(e) {}
```

Die Zeile ist jetzt **byte-identisch** mit `alice-dms-classify-document.json` (`Code: Two-Attempt Classification`, PROJ-78). Repo-weite Prüfung vorher: 5 Vorkommen mit `|| 'qwen3:14b'` (`alice-dms-classify-document`, `alice-dms-language-check`, `alice-dms-classification-backfill`, `alice-dms-processor`) gegen 2 Vorkommen mit `|| 'qwen3.5:27b-q4_K_M'` — die beiden Ausreißer waren genau die PROJ-53-Nodes. Nachher: 7/7 einheitlich.

- Betroffen: `alice-mail-sync.json` / `Code: Import Attachments` und `alice-mail-attachment-backfill.json` / `Code: Import Mail Attachments` — **sonst nichts**.
- Die Env-Variable `OLLAMA_MODEL_DMS` selbst wurde **nicht** angefasst (keine Änderung an `.env`/`.env.example`/Compose). Andere DMS-Workflows sind unberührt (`git diff --stat` = nur die 2 Workflow-Dateien).
- **Bewusst unverändert gelassen:** der Initialisierungswert `let ollamaModel = 'qwen3.5:27b-q4_K_M'` vor dem `try` ist toter Code (wird im `try` sofort überschrieben; der `catch`-Pfad greift nur, wenn `$env` selbst wirft, dann bliebe der Vision-Modellname stehen). Dieser Schönheitsfehler existiert identisch im Referenz-Workflow `alice-dms-classify-document.json`. Da die Vorgabe war, die Zeile exakt zu kopieren, wurde er nicht "verbessert" — er sollte projektweit in einem eigenen Cleanup adressiert werden, nicht in PROJ-53.

**Bug B — eigener `Image/`-Ordner (behoben).**

`routeByExtension()` gibt für Bilder jetzt `'Image'` statt `'Document'` zurück. Wegen der von Iteration 2 (BUG-5, duplizierte Konstanten) bekannten Dreifach-Duplizierung wurde ein vollständiger Audit gemacht: Referenz war `git show 5b2259e` (Iteration-2-Commit, der `Video`/`Audio` einführte). Ergebnis — die Listen existieren an genau **3 Stellen in 2 Dateien**; `Image` wurde an **allen 3** ergänzt:

| # | Datei | Node | Konstante / Stelle | Änderung |
|---|-------|------|--------------------|----------|
| 1 | `alice-mail-sync.json` | `Code: Import Attachments` | `routeByExtension()` + `VALID_TARGET_FOLDERS` | Bild-Branch → `'Image'`; `Image` in Gate-Set |
| 2 | `alice-mail-attachment-backfill.json` | `Code: Import Mail Attachments` | `routeByExtension()` + `VALID_TARGET_FOLDERS` | identisch zu #1 (Runtime-/Backfill-Parität) |
| 3 | `alice-mail-attachment-backfill.json` | `Code: Fetch Mails With Attachments` | `SCHEMAS` (Basis von `countOnDisk()`) | `Image` ergänzt |

Stelle #3 ist der von Iteration-2-QA explizit benannte Fallstrick: `countOnDisk()` leitet den Zustand "bereits importiert" aus `SCHEMAS` ab. Ohne `Image` würde der Backfill jeden Bild-Anhang bei **jedem** Lauf erneut als Kandidat einstufen und re-importieren (Duplikate `_1`, `_2`, …), weil er in einem Ordner sucht, in den nicht mehr geschrieben wird.

Weitere geprüfte, aber **nicht** betroffene Stellen:

- `VALID_SCHEMAS` (beide Import-Nodes): bewusst **unverändert** bei den 5 DMS-Schemata. Es validiert die LLM-Antwort (`parseClassification()`); Bilder durchlaufen nie das LLM. Gleiche Begründung wie bei `Video`/`Audio` in Iteration 2. Ein Test stellt sicher, dass `Image` dort nicht einleckt.
- `SUPPORTED_EXTENSIONS` / `IMAGE_EXTENSIONS`: unverändert — die Bild-Endungen waren seit Iteration 1 enthalten, nur das Ziel ändert sich.
- Ordner-Anlage: es gibt **keine** separate Bootstrap-/mkdir-Liste. `/mnt/nas/ai/Image/` wird durch das bestehende `fs.mkdirSync(targetDir, { recursive: true })` im Import-Loop beim ersten Bild-Anhang automatisch angelegt — genau wie `Video/`/`Audio/` in Iteration 2. Kein Deploy-Schritt nötig.
- Repo-weite Suche nach `'Video'`/`/Video/` (JSON, SQL, SH, PY, TS, YML): Treffer nur in den 2 Workflows + diesem Spec. Kein Weaviate-Schema, kein `dms_watched_folders`-Seed, kein Script enthält die Ordnerliste.

**Hinweis zum Zusammenspiel mit dem DMS-Scanner:** `Image/` muss in `alice.dms_watched_folders` aufgenommen werden, damit die Bilder auch indexiert werden (siehe Bug-B-Analyse oben: `alice-dms-path-worker` routet nach Datei-Endung, nicht nach Quellordner, das Weaviate-Ergebnis bleibt also `Image`). Das ist eine **Konfigurations-/Deploy-Aufgabe des Users** (Settings → DMS-Ordner), kein Code-Change.

**Strukturelle Validierung** (n8n-mcp als Subagent nicht verfügbar, daher wie Iteration 1/2 statisch):

- Beide Workflows: valides JSON; `json.dumps(indent=2)`-Roundtrip vor der Änderung byte-identisch → der Diff enthält ausschließlich die beabsichtigten Zeilen (3 geänderte JSON-Zeilen, `git diff --stat`: 2 Dateien, +3/−3).
- Alle `connections`-Quellen/-Ziele lösen auf gültige Node-Namen auf; alle `$('Node')`-Referenzen in allen Nodes lösen auf (0 Fehler).
- Alle 16 Code-Nodes beider Workflows: `node --check` grün.
- 0 `console.log` (winston-Regel eingehalten); Credentials-Prüfung: 0 Warnungen.
- Verhaltenstest gegen den **ausgelieferten** JSON-Code (Konstanten + `routeByExtension()` aus der Datei extrahiert): **48/48 Assertions grün** (24 pro Workflow) — Bild-Routing per Endung *und* per MIME-Type (inkl. `.heic` ohne MIME und `image/gif` ohne Endung) → `Image`, Video/Audio unverändert, Text-Typen weiterhin `null` (= LLM-Pfad), alle 8 Zielordner vom Gate akzeptiert, Path-Traversal (`Image/../etc`, `..`, `''`) und LLM-Ausreißer (`unclear`, `Email`) vom Gate abgelehnt, `Image`/`Video`/`Audio` nicht in `VALID_SCHEMAS`.

**Nicht verifizierbar in dieser Umgebung** (für `/qa` / Deploy offen):

- `docker/compose/automations/n8n/.env.example` liegt in einem für den Agenten gesperrten Verzeichnis — der tatsächlich gesetzte Wert von `OLLAMA_MODEL_DMS` (laut Analyse `mistral-small3.2:24b`) wurde **nicht** eigenständig gegengelesen. Der Fix ist davon unabhängig: geändert wurde nur der Fallback, falls die Variable fehlt.
- Kein Live-Ollama-Aufruf: dass das korrekte Modell tatsächlich valides JSON liefert und `confidence>0, fallback=false` erzeugt, muss am laufenden System geprüft werden.
- Kein NAS-Zugriff: die automatische Anlage von `/mnt/nas/ai/Image/` und die Schreibrechte wurden nicht real getestet.
- Weiterhin offen aus Iteration 2: `alice-mail-reader` muss wegen `pypdf` neu gebaut werden.

## QA Test Results — Iteration 3 (2026-08-24)

Zielgerichtete Nachprüfung der beiden Live-Bugs aus Commit `d2c8912`. Methodik wie in den Vorrunden: statische Analyse + Verhaltenstests gegen den **aus dem JSON extrahierten, ausgelieferten** Code (kein nachgebauter Code), plus eigenständiger Audit statt Übernahme der Implementer-Angaben.

### Bug A — Ollama-Modell für Textklassifizierung

| # | Prüfung | Methode | Ergebnis |
|---|---------|---------|----------|
| A-1 | `ollamaModel`-Zeile in `alice-mail-sync` / `Code: Import Attachments` | Zeile aus JSON extrahiert, SHA256-Vergleich | **Pass** — byte-identisch zur Referenz |
| A-2 | `ollamaModel`-Zeile in `alice-mail-attachment-backfill` / `Code: Import Mail Attachments` | dito | **Pass** — byte-identisch |
| A-3 | Referenz `alice-dms-classify-document` / `Code: Two-Attempt Classification` | dito | **Pass** — alle 3 Zeilen SHA256 `f54b82980d18961c`, `len(set())==1` |
| A-4 | Diff-Umfang Bug A | `git diff --word-diff` | **Pass** — genau 1 geänderte Stelle pro Workflow (`'qwen3.5:27b-q4_K_M'` → `'qwen3:14b'` im `||`-Fallback) |
| A-5 | Repo-weite Behauptung „5 andere Workflows schon korrekt" | eigener `grep -ro` über `workflows/*.json` | **Pass (verifiziert, nicht übernommen)** — `alice-dms-classify-document`, `alice-dms-language-check`, `alice-dms-classification-backfill`, `alice-dms-processor` (2×) nutzen alle `\|\| 'qwen3:14b'`. Jetzt 7/7 einheitlich |
| A-6 | Env-Variable `OLLAMA_MODEL_DMS` **nicht** angefasst | `git diff --name-only d2c8912~1 d2c8912` | **Pass** — nur 2 Workflows + 2 Doku-Dateien; kein `.env`, kein `compose.yml`, kein `.env.example` |
| A-7 | Wirksamkeit des Fixes **im Produktivsystem** | Env-Werte gegengelesen + Auflösungslogik ausgeführt | **FAIL → BUG-13** (siehe unten) |

**A-7 im Detail (der eigentliche Befund dieser Runde).** Der Implementer konnte `docker/compose/automations/n8n/.env` nicht lesen (gesperrtes Verzeichnis) und hat den Fix deshalb nur gegen die *Fallback*-Semantik verifiziert. Die tatsächlich gesetzten Werte sind:

```
docker/compose/automations/n8n/.env:21:OLLAMA_MODEL_DMS=qwen3.5:27b-q4_K_M   <-- Vision-Modell!
docker/compose/automations/n8n/.env:27:OLLAMA_VISION_MODEL=qwen3.5:27b-q4_K_M
docker/compose/automations/n8n/.env.example:34:OLLAMA_MODEL_DMS=mistral-small3.2:24b
```

Die korrigierte Zeile lautet `ollamaModel = $env.OLLAMA_MODEL_DMS || 'qwen3:14b'`. Da `$env.OLLAMA_MODEL_DMS` in Produktion **gesetzt und truthy** ist, greift der `||`-Zweig nie. Ausführung der exakten Zeile:

| `OLLAMA_MODEL_DMS` | aufgelöstes Modell |
|--------------------|--------------------|
| `qwen3.5:27b-q4_K_M` (**Produktion**) | `qwen3.5:27b-q4_K_M` — **unverändert das Vision-Modell** |
| `mistral-small3.2:24b` (`.env.example`) | `mistral-small3.2:24b` |
| nicht gesetzt / leer | `qwen3:14b` |

Der Code-Fix ist inhaltlich **richtig und soll bleiben** (er beseitigt einen echten Ausreißer und stellt Projekt-Konsistenz her), behebt das vom User gemeldete Symptom aber **nicht**: Die Root Cause liegt eine Ebene tiefer im Env-Wert. `confidence=0, fallback=true` wird nach dem Deploy dieses Fixes unverändert auftreten.

### Bug B — eigener `Image/`-Zielordner

| # | Prüfung | Methode | Ergebnis |
|---|---------|---------|----------|
| B-1 | `routeByExtension()` gibt für Bilder `'Image'` zurück (beide Workflows) | Funktionskörper aus JSON extrahiert und ausgeführt | **Pass** — `.jpg/.jpeg/.png/.webp/.heic/.tif/.tiff` → `Image`; auch per MIME (`image/gif`, `image/svg+xml`) ohne passende Endung |
| B-2 | **Regression** Video/Audio-Branches unberührt | dito | **Pass** — `.mp4/.mov/.avi/.mkv/.webm` → `Video`, `.mp3/.wav/.m4a/.ogg/.flac` → `Audio`, MIME-Varianten ebenso |
| B-3 | **Regression** Text-Typen weiterhin `null` (= LLM-Pfad) | dito | **Pass** — `.pdf/.docx/.xlsx/.odt/.ods/.txt/.md` → `null`, Unbekanntes → `null` |
| B-4 | `VALID_TARGET_FOLDERS` enthält `'Image'` in **beiden** Import-Nodes | Konstante aus JSON extrahiert | **Pass** — `new Set([...VALID_SCHEMAS,'Image','Video','Audio'])`, `size===8` |
| B-5 | `VALID_SCHEMAS` **nicht** angefasst | dito | **Pass** — weiterhin exakt die 5 DMS-Schemata; `Image`/`Video`/`Audio`/`Email` nicht enthalten → für den LLM-Klassifikator unerreichbar |
| B-6 | **3-Stellen-Audit** (BUG-5-Klasse aus Iteration 2) | siehe Tabelle unten | **Pass — eigenständig verifiziert** |
| B-7 | `fs.mkdirSync` deckt `/mnt/nas/ai/Image/` ab | Code-Pfad gelesen | **Pass** — `targetDir = path.join(NAS_AI_ROOT, targetFolder)` + `mkdirSync(targetDir,{recursive:true})`; kein Bootstrap-/Allowlist-Vorabanlegen irgendwo |
| B-8 | Path-Traversal für den neuen Ordnernamen | Gate + `sanitizeFilename` ausgeführt | **Pass** — siehe Security unten |

**B-6: 3-Stellen-Audit — eigenständig nachgeprüft (nicht der Implementer-Tabelle vertraut).** Alle drei Konstanten wurden per Skript direkt aus den ausgelieferten `jsCode`-Feldern extrahiert und wörtlich geprüft:

| # | Datei | Node | Konstante | Extrahierter Ist-Wert | Ergebnis |
|---|-------|------|-----------|----------------------|----------|
| 1 | `alice-mail-sync.json` | `Code: Import Attachments` | `VALID_TARGET_FOLDERS` | `new Set([...VALID_SCHEMAS, 'Image', 'Video', 'Audio'])` | `Image` **vorhanden** |
| 2 | `alice-mail-attachment-backfill.json` | `Code: Import Mail Attachments` | `VALID_TARGET_FOLDERS` | `new Set([...VALID_SCHEMAS, 'Image', 'Video', 'Audio'])` | `Image` **vorhanden** |
| 3 | `alice-mail-attachment-backfill.json` | `Code: Fetch Mails With Attachments` | `SCHEMAS` (Basis von `countOnDisk()`) | `['Invoice','BankStatement','Document','Contract','SecuritySettlement','Image','Video','Audio']` | `Image` **vorhanden** |

Stelle #3 ist der von Iteration-2-QA benannte Fallstrick (fehlender Ordner ⇒ `countOnDisk()` findet nie etwas ⇒ Endlos-Re-Import mit `_1`, `_2`, …). `countOnDisk()` iteriert nachweislich über genau diese `SCHEMAS`-Liste (`SCHEMAS.some(schema => fs.existsSync(path.join(NAS_AI_ROOT, schema, fileName)))`) — mit `Image` darin ist das Re-Import-Szenario ausgeschlossen. **Kein vierter Duplikationsort gefunden**: repo-weite Suche nach `'Video'`/`Audio` in `workflows/`, `sql/`, `scripts/`, `schemas/` liefert außerhalb dieser 3 Stellen keine Ordnerliste.

**Verhaltenstest gegen den ausgelieferten Code:** **144/144 Assertions grün** (72 pro Workflow) — Bild-Routing per Endung und MIME, Video/Audio-Regression, Text→`null`, alle 8 Zielordner vom Gate akzeptiert, `VALID_SCHEMAS` unverändert bei 5, 15 Gate-Ablehnungsfälle, Pfad-Containment, `sanitizeFilename`.

### Security Audit — Iteration 3

| Vektor | Bewertung |
|--------|-----------|
| Path Traversal über neuen Ordnernamen | **Pass** — `Image` ist ein Literal in einer Allowlist-`Set`; der Ordnername stammt nie aus Angreifer-/LLM-Input, sondern aus `routeByExtension()` (Literal) oder aus `classification.document_type`, das gegen `VALID_TARGET_FOLDERS` geprüft wird. `Image/../etc`, `../Image`, `..`, `''`, `Image/`, `image`, `IMAGE`, `/etc/passwd`, `Email`, `unclear`, `null`, `undefined` werden **alle abgelehnt** (15/15) |
| Dateiname-Injection in `Image/` | **Pass** — `sanitizeFilename()` unverändert; `/` und `\` → `_`, Control-Chars entfernt, führende Punkte gestrippt. `path.join('/mnt/nas/ai','Image',sanitize('../../../etc/passwd'))` bleibt unter `/mnt/nas/ai/Image/` (auch nach `path.resolve`) |
| LLM-gesteuerte Ordnerwahl | **Pass** — `VALID_SCHEMAS` unverändert; das LLM kann `Image`/`Video`/`Audio` nicht ausgeben und damit kein Medien-Routing erzwingen |
| Angriffsfläche gesamt | **unverändert** — keine neuen Inputs, Endpunkte, Credentials oder Netzwerkpfade |
| Secrets im Diff | **Pass** — keine Secrets; `.env`-Dateien nicht angefasst |

### Bugs Found — Iteration 3

| ID | Severity | Titel | Root Cause | Priorität |
|----|----------|-------|------------|-----------|
| BUG-13 | **High** | Bug A ist im Produktivsystem **nicht behoben**: DMS-Textklassifizierung nutzt weiterhin das Vision-Modell | `docker/compose/automations/n8n/.env` Zeile 21 setzt `OLLAMA_MODEL_DMS=qwen3.5:27b-q4_K_M` — identisch mit `OLLAMA_VISION_MODEL` (Zeile 27). Der Fix in `d2c8912` korrigiert nur den `||`-Fallback-Literal, der bei gesetzter Variable nie ausgewertet wird. Der Env-Wert weicht zudem von `.env.example` (`mistral-small3.2:24b`) ab | **P1** — Ein-Zeilen-Config-Änderung + n8n-Neustart. Betrifft **alle 6** DMS-Workflows, die `OLLAMA_MODEL_DMS` lesen, nicht nur PROJ-53 |
| BUG-14 | Low | Edge-Case-Doku (Zeile 84) erwähnt `Image/` nicht und ist für den neuen Ordner irreführend | Der Absatz beschreibt `Video/`/`Audio/` als „reine Ablageordner, **kein** Weaviate-Schema". `Image` verhält sich gegenteilig: `schemas/image.json` existiert (Klasse `Image` mit `ai_description`, EXIF, GPS) und `alice-dms-path-worker` / `Switch: Route by Type` hat einen eigenen `Image`-Output. Wird `Image/` in `dms_watched_folders` aufgenommen, greift eine vollwertige Pipeline — nicht der beschriebene `Document`-Fallback | P3 — Doku-Präzisierung |

**Zu BUG-13, Abgrenzung:** Der Code-Fix aus `d2c8912` ist *korrekt* und soll **nicht** zurückgenommen werden — er beseitigt einen echten Ausreißer (2 von 7 Stellen) und stellt Konsistenz mit PROJ-78 her. Er ist nur **nicht hinreichend**: ohne Korrektur des Env-Werts bleibt das vom User gemeldete Symptom (`confidence=0, fallback=true`) bestehen. Da die Ursache projektweit in der Konfiguration liegt und **alle** DMS-Workflows betrifft, ist die Behebung streng genommen breiter als PROJ-53 — sie ist aber die Voraussetzung dafür, dass PROJ-53s Akzeptanzkriterium „Text-Anhänge werden mit dem korrekten DMS-Textklassifizierungsmodell klassifiziert" erfüllt ist, und blockiert daher die Freigabe.

### Nicht bestätigte Verdachtsmomente (Negativbefunde)

| Verdacht | Befund |
|----------|--------|
| Vierte, übersehene Duplikationsstelle der Ordnerliste | **Nicht bestätigt** — genau 3 Stellen, alle korrigiert |
| `Image` leckt in `VALID_SCHEMAS` und wird LLM-erreichbar | **Nicht bestätigt** — beide Nodes weiterhin bei 5 Schemata |
| Bild-Routing bricht die 20-KB-Müll-Grenze | **Nicht bestätigt** — `isImage`-Prüfung (`IMAGE_EXTENSIONS` + `image/`-MIME) liegt **vor** dem Routing und ist unverändert; Müllbilder werden weiterhin verworfen, bevor `routeByExtension()` läuft |
| Fehlender `IMAGE_JUNK`-Check im Backfill-Import-Node ist eine Regression | **Nicht bestätigt** — Vergleich gegen `5b2259e` zeigt: existierte dort schon nicht; die Müllfilterung sitzt bewusst im vorgelagerten Kandidaten-Scan |
| Weiteres Vision-Modell-Vorkommen in `alice-mail-sync` (`Process + Classify + Store Emails`, `model: 'qwen3.5:27b-q4_K_M'` hartkodiert) ist Teil von Bug A | **Nicht bestätigt als PROJ-53-Regression** — stammt aus Commit `3b94a30` („Model change to qwen3.5"), betrifft die **Mail-Body**-Kategorisierung (PROJ-46), nicht den Anhang-Pfad, und wurde von `d2c8912` nicht berührt. Eigenständig zu bewerten (gleiche Fehlerklasse, andere Feature-Zuständigkeit) |
| `alice-dms-processor` / `Code: BankTransaction Phase B` nutzt Vision-Modell | **Nicht bestätigt** — identisches Muster, nur auf zwei Zeilen verteilt; Fallback korrekt `qwen3:14b` |

### Regression Check (`d2c8912~1` → `d2c8912`)

| Prüfung | Ergebnis |
|---------|----------|
| Diff-Umfang | **Pass** — 4 Dateien: 2 Workflows (**+3/−3 Code-Zeilen**), `INDEX.md`, Spec. Keine `.env`/Compose/SQL/Schema-Änderung |
| Geänderte JSON-Zeilen | **Pass** — `alice-mail-sync`: 1 Zeile; `alice-mail-attachment-backfill`: 2 Zeilen. Sonst nur Kommentartext |
| JSON-Validität beider Workflows | **Pass** |
| Graph-Integrität | **Pass** — `alice-mail-sync` 19 Nodes, `alice-mail-attachment-backfill` 18 Nodes; alle `connections`-Quellen/-Ziele und alle `$('Node')`-Referenzen lösen auf (**0 Fehler**) |
| JS-Syntax aller Code-Nodes | **Pass** — `node --check` grün für **15/15** Code-Nodes |
| winston-Regel | **Pass** — 0 `console.log` in beiden Workflows |
| Dedup (Message-ID / `countOnDisk`) | **Pass** — `countOnDisk()` unverändert, jetzt inkl. `Image`; Pooling-Logik aus Iteration 2 unberührt |
| Größenlimit (50 MB) + 20-KB-Bildmüll | **Pass** — `ATTACHMENT_MAX_BYTES=52428800`, `IMAGE_JUNK_MAX_BYTES=20480` unverändert an allen Stellen |
| PDF-Textklassifizierungs-Pfad | **Pass** — `fetchPdfText()` / `PDF_EXTENSIONS` / `PLAINTEXT_EXTENSIONS` unverändert; Text-Typen routen weiterhin in den LLM-Zweig |
| Dry-Run-Gate | **Pass** — `Code: Init Backfill Run`, `Code: Fetch Mails With Attachments`, `Code: Empty Summary` unverändert |
| `confirm`-Parameter-Fix (letzte QA-Runde) | **Pass** — `body.confirm !== undefined ? body.confirm : query.confirm` + `=== true \|\| === 'true'` unverändert vorhanden |
| `MAX_RUNTIME_SECONDS` | **Pass** — Default 7200, Override-Parsing unverändert |

### Edge Case `Image/` noch nicht in `dms_watched_folders`

Bereits als generisches Muster dokumentiert (Edge-Cases Zeile 78): *„Datei liegt auf der AI-Freigabe, wird aber vom DMS-Scanner nicht erkannt, bis der Admin den Ordner aufnimmt — kein Datenverlust, nur verzögerte Verarbeitung."* Verhalten ist **graceful**: Der Import schreibt die Datei unabhängig von `dms_watched_folders`; ein fehlender Eintrag verzögert nur die Indexierung, verursacht keinen Crash und keinen Retry-Loop. `Image/` wird durch `mkdirSync(...,{recursive:true})` beim ersten Bild-Anhang automatisch angelegt. Präzisierung für `Image` speziell siehe BUG-14.

### Nicht verifizierbar in dieser Umgebung

| # | Kriterium | Grund |
|---|-----------|-------|
| NV-1 | Lauf gegen echtes n8n/IMAP/Ollama/Weaviate/NAS | Kein Zugriff; Verhaltenstests laufen gegen den extrahierten Node-Code |
| NV-2 | `mcp__n8n-mcp__*`-Validierung | Tools nicht verfügbar; erneut strukturelle Eigenvalidierung |
| NV-3 | Reales Anlegen und Schreibrechte von `/mnt/nas/ai/Image/` | Kein NAS-Zugriff |
| NV-4 | Dass das korrekte Textmodell `confidence>0, fallback=false` liefert | Kein Live-Ollama; zusätzlich durch BUG-13 blockiert |
| NV-5 | AC-5.2 / AC-5.3 (Mail-Thumbnail-Rendering) | Unverändert offen aus Iteration 1/2 |

### Summary — Iteration 3

- **Bug B: vollständig behoben und eigenständig verifiziert.** 3-Stellen-Audit selbst durchgeführt (nicht übernommen) — `Image` in allen drei Konstanten wörtlich nachgewiesen. 144/144 Verhaltensassertions grün, inkl. Video/Audio- und Text-Regression. Security unverändert.
- **Bug A: Code-Fix korrekt, Symptom aber nicht behoben.** Die Zeile ist byte-identisch zur PROJ-78-Referenz und der Repo-Survey stimmt (eigenständig nachgeprüft, 7/7 einheitlich). In Produktion ist `OLLAMA_MODEL_DMS` jedoch auf das Vision-Modell gesetzt, wodurch der korrigierte Fallback nie greift → **BUG-13 (High)**.
- **Regression:** eng begrenzt, +3/−3 Code-Zeilen, 15/15 Code-Nodes syntaktisch valide, Graph 0 Fehler, alle stichprobenartig geprüften Iterations-1/2-Mechaniken intakt.
- **Offene Bugs:** **1 × High (BUG-13)**, 1 × Low (BUG-14).
- **Production Ready:** **NO — NOT READY**
- **Recommendation:** **Nicht Approved.** Status bleibt **In Review**. Blocker ist eine Ein-Zeilen-Config-Änderung, kein Code-Rework:
  1. `docker/compose/automations/n8n/.env` Zeile 21 auf ein Textmodell setzen (z.B. `OLLAMA_MODEL_DMS=mistral-small3.2:24b` wie in `.env.example`, oder `qwen3:14b`), n8n neu starten, dann einen Anhang-Import live prüfen (`confidence>0`, `fallback=false`). **Achtung:** wirkt auf alle 6 DMS-Workflows — Gegenprobe an PROJ-78-Klassifizierung empfohlen.
  2. BUG-14: Edge-Case Zeile 84 um `Image` präzisieren (hat im Gegensatz zu `Video`/`Audio` ein echtes Weaviate-Schema).
  3. Danach: `Image/` in `alice.dms_watched_folders` eintragen (Settings → DMS-Ordner), Deploy-Voraussetzungen aus Iteration 2 bleiben bestehen.

---

## Iteration 4 — Anhang-Verarbeitung entkoppelt (2026-08-24)

### Hintergrund

BUG-13 (Iteration 3) war kein Code-Fehler, sondern ein GPU-Ressourcenkonflikt: Andreas betreibt bewusst **ein einziges** Ollama-Modell (`qwen3.5:27b-q4_K_M`) für Chat, Vision **und** DMS-Textklassifizierung, weil die GPU beim gleichzeitigen Einsatz mehrerer Modelle ständig neu laden müsste. Ein Live-Test mit `OLLAMA_MODEL_DMS=mistral-small3.2:24b` zeigt: Mistral klassifiziert DMS-Dokumente deutlich zuverlässiger als das Vision-Modell auf reinem Text. Mistral soll daher produktiv für die DMS-Textklassifizierung genutzt werden — das erfordert aber ein zweites, exklusiv geladenes Modell, was das ursprüngliche Umlade-Problem wieder aufwirft.

**Analyse nach Trigger-Häufigkeit ergibt:** Alle DMS-Klassifizierungs-Workflows außer einem sind unkritisch, weil sie nur manuell oder nightly laufen (kein Kollisionsrisiko mit dem minütlich aktiven Chat-Modell):
- `alice-dms-classify-document` (PROJ-78-Sub-Workflow): getriggert von `alice-dms-processor` (nightly) und manuellen Backfills
- `alice-dms-language-check` / `-backfill`: manuell + nightly
- `alice-mail-attachment-backfill` (PROJ-53): manuell getriggert — unkritisch

**Kritisch ist ausschließlich `alice-mail-sync`**, da es **minütlich** läuft und damit während der Chat-Kernzeit (07:00–23:30 Uhr) ständig mit dem Chat-Modell um die GPU konkurrieren würde, sobald es selbst Mistral für die Anhang-Klassifizierung lädt.

### Entscheidung

Die Anhang-Verarbeitung (Klassifizierung + Ablage) wird aus `alice-mail-sync` **vollständig herausgelöst** in einen neuen, eigenständigen Workflow `alice-mail-attachment-processor`, der **nightly um 02:00 Uhr** läuft (gleicher Zeitpunkt wie `alice-dms-processor`, außerhalb der Chat-Kernzeit) und dort Mistral exklusiv nutzen kann.

- `alice-mail-sync` bleibt **unverändert minütlich** aktiv und verarbeitet Mail-Metadaten (Betreff, Absender, Kategorisierung, Weaviate-`Email`-Insert) wie bisher — Mails sind also weiterhin **sofort** per Chat auffindbar.
- Neu: Pro neu gespeicherter Mail mit mindestens einem klassifizierungswürdigen Anhang (nach dem bestehenden Extension-Vorfilter — offensichtlich irrelevante Anhänge werden weiterhin sofort synchron verworfen, damit die Warteschlange nicht unnötig wächst) trägt `alice-mail-sync` einen Eintrag in eine Redis-Liste ein (Mailbox-ID, Message-ID/UID, Anhang-Metadaten, Weaviate-`Email`-UUID) — keine weitere Verarbeitung an dieser Stelle.
- Der komplette bestehende Anhang-Code (Klassifizierung, `/attachment`- und `/attachment-text`-Abruf, NAS-Ablage, Kollisions-Suffix, MQTT-Publish für Thumbnails) wandert **1:1 unverändert** in den neuen nightly Workflow, der die Redis-Liste batchweise abarbeitet — Struktur analog `alice-dms-processor` (Init → Fetch Batch → Split In Batches mit Time-Check → Verarbeitung → Summary).
- Der bestehende `alice-mail-attachment-backfill`-Workflow bleibt unverändert bestehen (weiterhin manuell/Dry-Run) — er deckt bereits indexierte Alt-Mails ab, der neue nightly Workflow deckt den laufenden Betrieb ab.

**Konsequenz für den Nutzer:** Neue Mails sind sofort im Chat auffindbar (Text/Metadaten), ihre Anhänge werden aber erst beim nächsten nightly Run (spätestens am folgenden Tag um 02:00 Uhr) klassifiziert und ins DMS eingespeist — bewusster Trade-off zwischen Aktualität und GPU-Ressourcenschonung.

### Neue/geänderte Acceptance Criteria

- [ ] `alice-mail-sync` klassifiziert und speichert Anhänge **nicht mehr selbst** — es trägt pro Mail mit mindestens einem (nach Extension-Vorfilter) klassifizierungswürdigen Anhang einen Eintrag in eine Redis-Liste ein und läuft ansonsten unverändert minütlich weiter
- [ ] Ein neuer Workflow `alice-mail-attachment-processor` läuft **nightly um 02:00 Uhr** (`cronExpression: 0 2 * * *`, wie `alice-dms-processor`) und verarbeitet die Redis-Liste batchweise
- [ ] Der Nightly-Workflow nutzt exakt dieselbe Klassifizierungs-/Ablage-/MQTT-Logik wie die bisherige synchrone Implementierung in `alice-mail-sync` (unverändert übernommen, kein Verhaltensunterschied außer dem Zeitpunkt)
- [ ] Der Nightly-Workflow nutzt `OLLAMA_MODEL_DMS` für die Klassifizierung (identisch zu allen anderen DMS-Klassifizierungs-Workflows) — produktiv auf ein Textmodell (z.B. `mistral-small3.2:24b`) gesetzt, ohne dass dies Kollisionen mit dem Chat-Modell verursacht, da der Lauf außerhalb der Kernzeit stattfindet
- [ ] Zeitlimit-Schutz analog `alice-dms-processor` (`Code: Time Check` / `IF: Time Limit Reached`), damit ein sehr langer Lauf nicht bis in die Chat-Kernzeit hineinläuft
- [ ] Ist eine Mail-Redis-Warteschlangen-Eintrag beim nightly Run nicht mehr verarbeitbar (z.B. IMAP-Fehler), wird er übersprungen und geloggt, der Lauf geht mit den übrigen Einträgen weiter — analog zum bisherigen Fehlerverhalten
- [ ] `alice-mail-attachment-backfill` bleibt unverändert bestehen und unabhängig nutzbar
- [ ] Bereits behobene Bugs aus Iteration 3 (Bild-Routing nach `Image/`, korrekter Modell-Zugriff über `$env.OLLAMA_MODEL_DMS`) gelten unverändert für den neuen Nightly-Workflow — reine Verschiebung des Codes, keine Logikänderung

### Edge Cases (neu)

- **Mail mit Anhang kommt kurz vor 02:00 Uhr rein**: Wird im selben nightly Run noch verarbeitet, sofern `alice-mail-sync` den Redis-Eintrag vor dem Start des nightly Runs geschrieben hat; andernfalls erst im nächsten Lauf (24h später) — kein Datenverlust, nur Verzögerung.
- **Nightly Run überschreitet Zeitlimit**: Bricht kontrolliert ab (wie `alice-dms-processor`), verbleibende Redis-Einträge werden beim nächsten Lauf weiterverarbeitet.
- **n8n/Server war während 02:00 Uhr nicht erreichbar**: Schedule-Trigger holt den verpassten Lauf nicht automatisch nach; Redis-Einträge bleiben bestehen und werden beim nächsten regulären nightly Lauf abgearbeitet, sobald der Server wieder verfügbar ist (kein Datenverlust, nur Verzögerung).

### Tech Design Iteration 4 (Solution Architect, 2026-08-24)

#### E) Workflow Architecture

Drei Bausteine ändern sich: `alice-mail-sync` wird verschlankt, ein neuer Workflow `alice-mail-attachment-processor` entsteht, `alice-mail-attachment-backfill` bleibt unangetastet.

**Baustein 1: Verschlankung von `alice-mail-sync`**

- **Entfernt:** Der komplette Anhang-Verarbeitungsblock (`Code: Import Attachments` inkl. Klassifizierung, `/attachment`-/`/attachment-text`-Abruf, NAS-Ablage, MQTT-Publish) sowie der zugehörige Split-Zweig für den Thumbnail-MQTT-Publish.
- **Neu, ersetzt den entfernten Block:** Ein schlanker Code-Schritt direkt nach dem bestehenden "Process + Classify + Store Emails" (Mail-Metadaten-Insert bleibt unverändert). Für jede neu gespeicherte Mail mit mindestens einem Anhang, der den bestehenden Extension-Vorfilter besteht (Format-Allowlist-Check bleibt hier, damit die Warteschlange nicht mit offensichtlich irrelevanten Anhängen — falsche Endung, Bild-Datenmüll < 20 KB — vollläuft), wird **ein Redis-Listeneintrag** geschrieben: Mailbox-Kontext (Verbindungsdaten wie bisher für `/attachment`), IMAP-UID, Attachment-Index(e), Mail-Metadaten (Betreff, Absender, Datum, Body-Preview — für den späteren Klassifizierungs-Prompt), Weaviate-`Email`-UUID.
- **Trigger/Taktung unverändert:** Läuft weiterhin minütlich, Mail-Metadaten-Pfad unverändert schnell.

**Baustein 2: Neuer Workflow `alice-mail-attachment-processor`**

Struktur analog `alice-dms-processor` (Nightly-Batch-Verarbeitung mit Zeitlimit-Schutz):

- **Trigger:** Schedule, `0 2 * * *` (identisch zu `alice-dms-processor`)
- **Ablauf:** Liest die Redis-Liste vollständig ein (Items bleiben in der Liste, bis sie einzeln erfolgreich verarbeitet wurden — Absturz-/Zeitlimit-sicher, gleiches Muster wie `alice-dms-processor`s `Code: Fetch Batch`/`alice:dms:plaintext`) → verarbeitet batchweise mit periodischem Zeitlimit-Check → pro Eintrag: **exakt dieselbe** Klassifizierungs-/Abruf-/Ablage-/MQTT-Logik, die bisher synchron in `alice-mail-sync` lief (1:1 verschobener Code, keine Verhaltensänderung) → entfernt erfolgreich verarbeitete Einträge aus der Redis-Liste
- **Modell:** `$env.OLLAMA_MODEL_DMS` (identisch zu allen anderen DMS-Klassifizierungs-Workflows) — läuft außerhalb der Chat-Kernzeit, daher unkritisch, wenn dort ein anderes Modell als für Chat/Vision geladen wird
- **Zeitlimit-Schutz:** Analog `alice-dms-processor`s `Code: Time Check`/`IF: Time Limit Reached` — bricht kontrolliert ab, bevor der Lauf in die Chat-Kernzeit hineinreicht; unverarbeitete Redis-Einträge bleiben für den nächsten Lauf erhalten
- **Fehlerverhalten:** Einzelner Eintrag schlägt fehl (IMAP-Fehler, Klassifizierung nicht erreichbar, Ablage nicht möglich) → wird geloggt und aus der Liste entfernt (wie bisher: kein automatischer Retry im nächsten Zyklus, konsistent mit dem bereits etablierten PROJ-53-Fehlerverhalten) — **nicht** zu verwechseln mit einem Zeitlimit-Abbruch, der unverarbeitete Einträge bewusst *nicht* entfernt

**Baustein 3: `alice-mail-attachment-backfill` — unverändert**

Deckt weiterhin bereits vor Iteration 4 indexierte Alt-Mails ab (Dateisystem-basierte "bereits importiert"-Prüfung, wie bisher). Kein Zusammenhang mit der neuen Redis-Liste — der Backfill fragt weiterhin Weaviate direkt ab, nicht die Queue.

### Datenmodell (fachlich) — Ergänzung Iteration 4

- **Neue Redis-Liste** `alice:mail:attachment_queue` (Namensvorschlag, konsistent mit bestehenden `alice:mail:*`-Präfixen aus Iteration 2): JSON-Einträge mit Mailbox-Kontext, IMAP-UID, Attachment-Index(es), Mail-Metadaten, Email-UUID. Kein neues Datenbankschema, keine neue Persistenzschicht jenseits von Redis (konsistent mit der bestehenden Projektentscheidung aus der ursprünglichen Spec).
- Kein neues Weaviate-Feld — die Redis-Liste referenziert die bereits existierende `Email`-UUID nur lesend.

### Tech-Entscheidungen (Begründung) — Ergänzung Iteration 4

- **Redis-Liste statt neuer Postgres-Tabelle:** Konsistent mit der bestehenden Projektentscheidung (keine neue Persistenzschicht) und identisch zum bereits etablierten Muster in `alice-dms-processor` (`alice:dms:plaintext`), das exakt dieselbe Anforderung löst (Batch-Queue, crash-sicher durch "erst entfernen nach erfolgreicher Verarbeitung").
- **02:00 Uhr statt eigener Zeitpunkt:** Wiederverwendung des bereits etablierten, GPU-schonenden Zeitfensters von `alice-dms-processor` statt eines neuen Zeitpunkts — vermeidet, zwei nightly Jobs mit unterschiedlichen Zeiten zu pflegen und hält das Modell-Umlade-Risiko auf ein bekanntes Minimum (beide Jobs könnten sogar dasselbe Modell laden, falls sie sich zeitlich überschneiden — kein neues Konfliktpotential gegenüber dem Ist-Zustand).
- **1:1-Code-Verschiebung statt Neuentwicklung:** Die Klassifizierungs-/Ablage-Logik wurde in Iteration 1–3 bereits mehrfach QA-geprüft und gefixt (Dedup, Größenlimit, Pfad-Sanitisierung, Image-Routing, Modell-Referenz). Eine Neuentwicklung würde dieses Risiko unnötig wiederholen; die Architektur-Änderung betrifft ausschließlich **wann** und **wodurch getriggert** der Code läuft, nicht **was** er tut.
- **Kein Trigger-Nachhol-Mechanismus bei verpasstem 02:00-Lauf:** Konsistent mit dem bestehenden Verhalten von `alice-dms-processor` (kein Backfill-Trigger bei verpasstem Schedule) — Redis-Einträge gehen dabei nicht verloren, nur der nächste reguläre Lauf holt sie nach.

### Dependencies (Pakete) — Ergänzung Iteration 4

Keine neuen Pakete — `redis` ist in n8n Code-Nodes bereits erlaubt (`NODE_FUNCTION_ALLOW_EXTERNAL`) und wird bereits in mehreren bestehenden Workflows verwendet.

**Nächste Schritte:** `/backend` für die Umsetzung (Verschlankung von `alice-mail-sync`, neuer Workflow `alice-mail-attachment-processor`), dann erneut `/qa`.

### Implementation Notes (Iteration 4)

**Umgesetzt am 2026-08-24 (`/backend`). Nicht deployt** — Deployment erfolgt manuell durch den Admin (beide Workflows: `alice-mail-sync` **und** neu `alice-mail-attachment-processor`).

#### Baustein 1: `alice-mail-sync` verschlankt

- **Entfernt:** `Code: Import Attachments` (der komplette Anhang-Block). Der Node wurde **nicht gelöscht, sondern verschoben** — siehe Baustein 2.
- **Neu:** `Code: Enqueue Attachment Jobs` (`id: s9b-enqueue-attachments`), hängt am selben Output 0 von `Process + Classify + Store Emails`, parallel zu `Notify: Passthrough` — also exakt an der Stelle des entfernten Nodes.
- Schreibt pro neu gespeicherter Mail **einen** JSON-Eintrag per `rPush` in die Redis-Liste `alice:mail:attachment_queue`, aber nur wenn mindestens ein Anhang den Vorfilter besteht. Eintrag enthält: `mailbox` (mailboxId/host/port/ssl/username/passwordEnc), `uid`, `message_id`, `weaviate_uuid`, `subject`, `sender`, `date`, `body_preview`, `attachments[]` (name/mime_type/size_bytes), `queued_at`.
- Der Vorfilter (`SUPPORTED_EXTENSIONS` + 50-MB-Limit + <20-KB-Bild-Müll) ist **verbatim** aus `Code: Import Attachments` übernommen (`prefilterAttachment` byte-identisch), damit die Queue nicht mit Anhängen vollläuft, die der Processor ohnehin verwerfen würde.

#### Baustein 2: Neuer Workflow `workflows/alice-mail-attachment-processor.json`

17 Nodes, Struktur analog `alice-dms-processor`:

`Schedule: Nightly 02:00` (`0 2 * * *`) → `Code: Init` → `Code: Fetch Batch` (`lRange`, Items bleiben in der Liste) → `IF: Queue Empty` → `Split In Batches` → `Code: Time Check` → `IF: Time Limit Reached` → `IF: Parse Error` → `Code: Process Queue Item` → `IF: Imported Any` → `MQTT: Publish Attachment Done` → zurück zu `Split In Batches`.

- **`Code: Process Queue Item`** enthält den 1:1 verschobenen Anhang-Code. Nachgewiesen per normalisiertem Diff gegen den alten `Code: Import Attachments`: **98,9 % identisch**; die einzigen Deltas sind der Wegfall der äußeren `for (const mail of storedEmails)`-Schleife (jetzt eine Mail pro Queue-Eintrag) und ein Kommentar-Wort. Alle Funktionsrümpfe (`prefilterAttachment`, `routeByExtension`, `fetchPdfText`, `shortenSender`, `mailDateStamp`, `sanitizeFilename`, `buildBaseFilename`, `resolveCollision`, `buildClassificationPrompt`, `parseClassification`, `callOllama`, `classifyAttachment`) sind unverändert.
- **Crash-/Zeitlimit-Sicherheit:** `lRem` erfolgt erst *in* `Code: Process Queue Item`, nachdem der Eintrag abgearbeitet wurde. Ein Zeitlimit-Abbruch greift **vor** diesem Node, unverarbeitete Einträge bleiben also erhalten (gleiches Muster wie `alice:dms:plaintext`).
- **Zeitlimit:** `MAX_RUNTIME_SECONDS = 14400` (4 h) → ein 02:00-Lauf bricht spätestens um 06:00 ab, also vor der Chat-Kernzeit (07:00).
- **Modell:** `$env.OLLAMA_MODEL_DMS || 'qwen3:14b'` (Iteration-3-Fix). Das Vision-Modell-Literal `qwen3.5:27b-q4_K_M` kommt im neuen Workflow **nicht** vor.
- **Fehlerverhalten:** unveränderte Pro-Anhang-`try/catch`-Isolation; ein fehlgeschlagener Eintrag wird geloggt und aus der Liste entfernt (kein Auto-Retry), wie im Tech Design festgelegt.

#### Baustein 3: `alice-mail-attachment-backfill` — unverändert

Bestätigt: `git status` weist die Datei als **nicht geändert** aus. Keine Anbindung an die neue Redis-Liste.

#### Abweichungen vom Tech Design (wichtig für QA)

1. **`MQTT: Publish Email Done` bleibt in `alice-mail-sync`** — bewusste Abweichung von der Formulierung "sowie der zugehörige Split-Zweig für den Thumbnail-MQTT-Publish" (Baustein 1). Begründung: Dieser Publish ist laut AC (Zeile 68) und PROJ-80-Lückenschluss der Trigger für das **Thumbnail der Mail selbst** (`document_type: 'Email'`, gerendert aus Betreff + Body) und hat mit Anhängen nichts zu tun. Er feuert für **jede** neu inserierte Mail. Ein Verschieben in den Nightly-Workflow hätte alle Mails **ohne** Anhang dauerhaft ohne Thumbnail gelassen (Regression gegen das in Iteration 1 QA-geprüfte AC-5.1), da der Processor nur Mails mit Anhang sieht. `Code: Split Stored Emails` → `IF: Has Stored Emails` → `MQTT: Publish Email Done` hängen daher jetzt direkt an `Process + Classify + Store Emails` (nur `position` geändert, Parameter/Credentials unverändert).
2. ~~**Zusätzlicher MQTT-Node im neuen Workflow:** `MQTT: Publish Attachment Done`~~ — **hinfällig, per BUG-16 entfernt** (siehe "Bugfixes nach QA" unten). Der eigene QA-Hinweis an dieser Stelle ("potenziell redundant zum Publish aus Baustein 1") hat sich bestätigt.
3. **`IF: Parse Error` / `Code: Drop Unparseable Item`** sind im Tech Design nicht skizziert, aber nötig, weil `Code: Fetch Batch` (analog `alice-dms-processor`) defekte JSON-Einträge markiert statt zu werfen — sonst bliebe ein unparsebarer Eintrag für immer in der Liste und würde jede Nacht erneut scheitern.
4. **Attachment-Indizes:** Der Queue-Eintrag trägt das **vollständige** `attachments`-Array (nicht nur die gefilterten), weil `/attachment` per `attachment_index` adressiert. Ein Filtern beim Enqueue hätte die Indizes verschoben und den falschen Anhang geladen. Der Vorfilter entscheidet beim Enqueue also nur *ob* die Mail in die Queue kommt; *welche* Anhänge verarbeitet werden, entscheidet unverändert der Processor.
5. **Feldname `mailbox`** statt des im Tech Design genannten "Mailbox-ID"-Felds: Es werden die vollständigen Verbindungsdaten benötigt (der Processor hat keinen `Prepare Mailbox Data`-Kontext und liest die Mailbox nicht erneut aus Postgres).

#### Validierung

Strukturell validiert (n8n-mcp im Subagent nicht verfügbar), alle drei Workflows: gültiges JSON, eindeutige Node-Namen/IDs, alle Connection- und `$('Node')`-Referenzen auflösbar, keine verwaisten Nodes, alle Code-Nodes `node --check` grün, **0 `console.log`**, Credentials auf MQTT-/Postgres-Nodes gesetzt, nur erlaubte `require`-Module (`axios, redis, winston, fs, path`).

Zusätzlich per Mock-Harness (Redis/axios/fs/winston gemockt) zur Laufzeit geprüft:

- Enqueue → `lRange` → Process → `lRem` Round-Trip funktioniert; nur Mails mit Kandidat werden eingereiht (Mail mit reinem Signatur-Icon und Mail ohne Anhang werden korrekt übersprungen).
- Mailbox-Kontext und `weaviate_uuid` überleben den Redis-Round-Trip.
- PDF → `Invoice/2026-05-04_billing_rechnung.pdf` inkl. korrektem Dateinamensschema.
- Iteration-2/3-Fixes verifiziert: Bild → `Image/`, Video → `Video/`, Audio → `Audio/`, **0 LLM-Aufrufe** für Medien, 50-MB-Limit greift.
- Zeitlimit: bei 5 h Laufzeit meldet `Code: Time Check` korrekt `_time_limit_reached: true`.
- Regressionsnachweis `alice-mail-sync`: alle Mail-Metadaten-Nodes (`Process + Classify + Store Emails`, `Notify: Passthrough`, alle PG-Nodes, `Prepare Mailbox Data`) sind **byte-identisch** zu HEAD; genau ein Node ausgetauscht.

#### Nicht verifizierbar in dieser Umgebung

- Kein Lauf gegen echtes Redis/n8n/IMAP/Ollama/NAS — die Mock-Harness ersetzt keinen Integrationstest.
- Ob `mistral-small3.2:24b` produktiv besser klassifiziert (Live-Test des Users, nicht Teil dieser Umsetzung).
- AC-5.2/5.3 (Thumbnail-Rendering für Mail-Objekte) unverändert offen aus Iteration 1–3.
- ~~Kein Lock-Mechanismus wie in `alice-dms-processor` implementiert~~ — **diese Einschätzung war falsch und wurde per BUG-17 korrigiert** (siehe "Bugfixes nach QA" unten). Der Lock schützt nicht gegen Selbst-Overlap, sondern serialisiert die GPU-Nutzung projektweit.

### Bugfixes nach QA (Iteration 4, 2026-08-24)

QA (`7e6d83e`) hat in den eigenen Abweichungen 2 und 5 zwei Medium-Bugs gefunden. Beide sind behoben; **nur** `workflows/alice-mail-attachment-processor.json` wurde angefasst (`alice-mail-sync.json` und `alice-mail-attachment-backfill.json` sind seit `0c92b6d` unverändert).

#### BUG-17 (Medium) — projektweiter GPU-Lock ergänzt

Die ursprüngliche Begründung analysierte das falsche Risiko: `alice:dms:processor:lock:run` verhindert nicht Selbst-Overlap, sondern **serialisiert GPU-Klassifizierung über Workflow-Grenzen hinweg**. Vier Workflows teilen ihn bereits; der neue Processor war der fünfte GPU-Konsument ohne Lock — bei **identischem** Trigger `0 2 * * *` wie `alice-dms-processor` (~2 h Laufzeit) also bis zu 2 h echte Überschneidung. Das ist exakt die Kontention, für deren Beseitigung Iteration 4 existiert (nur verlagert von "Chat vs. DMS" auf "DMS vs. DMS").

Übernommen wurde das Muster aus `alice-mail-attachment-backfill` (gleicher Key, gleiche TTL, gleicher Owner-Check):

- **Neu: `Code: Acquire Processor Lock`** (`SET NX PX 1800000`, Owner-Token via `crypto.randomUUID()`) direkt hinter dem Schedule-Trigger → **`IF: Processor Lock Acquired`**.
- **Lock belegt → sauberer Skip:** `Code: Log Already Running` → `End: Already Running`. Kein Blockieren, kein Retry-Loop; die Redis-Queue bleibt unangetastet und wird in der nächsten Nacht abgearbeitet.
- **Renew pro Item** in `Code: Time Check` (Lua-Owner-Check, TTL-Verlängerung auf 30 min). `_lock_lost` führt über `IF: Time Limit Reached` zum kontrollierten Abbruch — die Bedingung lautet jetzt `_time_limit_reached || _lock_lost` (analog `alice-dms-processor`).
- **Release auf allen drei Terminal-Pfaden:** `Code: Final Log` (Queue leergelaufen), `Code: Final Log (Time)` (Zeitlimit/Lock verloren) und **neu `Code: Empty Summary`** (leere Queue — sonst würde eine Nacht ohne Mails den Lock bis zum TTL-Ablauf halten und `alice-dms-processor` unnötig blockieren). Release immer per Lua mit Owner-Check, damit ein bereits von einem anderen Workflow übernommener Lock nie gelöscht wird.
- **Kein Deadlock möglich:** TTL (30 min) ≪ Laufzeitbudget (4 h); die Renewal ist der Heartbeat. Stirbt n8n mitten im Lauf, verfällt der Lock automatisch.

#### BUG-16 (Medium) — `MQTT: Publish Attachment Done` ersatzlos entfernt

Der Node publizierte `{ weaviate_uuid: <UUID der Mail>, document_type: 'Email' }` — also die Identität der **Mail**, nicht des Anhangs. Fachlich falsch (Anhänge sind Invoice/Document/Image/…, nie `Email`) und redundant zum korrekt in `alice-mail-sync` verbliebenen `MQTT: Publish Email Done`. Anhänge bekommen ihr Thumbnail ohnehin über die reguläre DMS-Pipeline, sobald sie unter `/mnt/nas/ai/<Ordner>/` liegen.

Entfernt wurden der MQTT-Node **und** `IF: Imported Any` (existierte ausschließlich, um diesen Publish zu gaten); `Code: Process Queue Item` führt jetzt direkt zurück auf `Split In Batches`. Das dafür eingeführte Feld `_imported_any` wurde in `Code: Process Queue Item` und `Code: Drop Unparseable Item` ebenfalls entfernt (verwaist). Der neue Workflow enthält damit **keinen MQTT-Node und keine MQTT-Credential** mehr.

#### Verifikation der Fixes

- Struktur-Validierung erneut grün für alle drei Workflows (JSON, Connection-/`$('Node')`-Referenzen, keine verwaisten Nodes, `node --check`, 0 `console.log`, Credentials, erlaubte Module).
- **Lock-Simulation** mit einem Fake-Redis, das `SET NX PX` und die Lua-Skripte (Owner-Check, TTL) nachbildet, gegen den **echten** jsCode der Lock-Nodes — 5 Szenarien, alle bestanden:
  1. `alice-dms-processor` hält den Lock → Acquire schlägt fehl, Skip mit `reason: 'lock_busy'`, fremder Lock unangetastet.
  2. Lock frei → Acquire OK; **zweiter paralleler Acquire schlägt fehl** (Mutual Exclusion); Renew hält Ownership; `Code: Final Log` gibt den Lock frei.
  3. Lock von fremdem Owner übernommen → `_lock_lost: true` (Abbruch), und der fremde Lock wird **nicht** gelöscht.
  4. TTL läuft ohne Renewal ab (simulierter Absturz) → Lock frei, nächster Lauf kann acquiren → **kein Deadlock**.
  5. Leere Queue → `Code: Empty Summary` gibt den Lock frei.
- **Kein funktionaler Regress:** Round-Trip (Enqueue → `lRange` → Process → `lRem`) und Medien-Routing/Limits erneut durchlaufen, Ergebnisse identisch zu vor dem Fix (PDF → `Invoice/`, Bild → `Image/`, Video → `Video/`, Audio → `Audio/`, 0 LLM-Calls für Medien, 50-MB-Limit greift).
- **1:1-Code-Move weiterhin intakt:** Ähnlichkeit des Anhang-Pipeline-Rumpfs zum ursprünglichen `Code: Import Attachments` unverändert **98,9 %**.

#### Nachtrag: Terminierung des Enqueue-Zweigs (2026-08-24)

Vom Nutzer gemeldeter struktureller Lose-Ende-Befund: `Code: Enqueue Attachment Jobs` hatte gar keine Ausgangsverbindung (`{"main": [[]]}`). Funktional war das unkritisch — der `rPush` passiert als Seiteneffekt im Node-Code, die Queue wurde also korrekt befüllt —, aber der Zweig endete im Nichts, während die beiden parallelen Zweige (`Code: Split Stored Emails` → … → `MQTT: Publish Email Done` und `Notify: Passthrough` → … → `PG: Update Sync Status`) sauber terminieren.

Behoben:

- **Neu: `End: Attachment Jobs Enqueued`** (`n8n-nodes-base.noOp`, `id: s9f-end-enqueued`) als sichtbarer Endpunkt, nach der bereits etablierten `End: …`-Konvention (`alice-dms-processor`: `End: Empty Queue`, `End: Time Limit`, `End: Already Running`; `alice-dms-scanner`: `End: No Folders`).
- **`onError: continueRegularOutput` von `Code: Enqueue Attachment Jobs` entfernt.** Das war die eigentliche Ursache dafür, dass ein Fehler in diesem Zweig unsichtbar geblieben wäre: Ein Throw (z.B. Redis nicht erreichbar beim `connect()`) wurde stillschweigend geschluckt. Ohne das Flag erscheint ein solcher Fehler rot in der n8n-Execution-View. Fehler beim `rPush` **einzelner** Jobs werden weiterhin im Code abgefangen und per winston geloggt (unverändert), und da der Zweig parallel zum Mail-Metadaten-Pfad läuft, kann ein Fehler hier den Metadaten-Pfad (`Notify: Passthrough` → PG-Status) nicht beeinträchtigen.
- **Sonst nichts geändert:** `jsCode` des Enqueue-Nodes byte-identisch, alle übrigen Nodes und Verbindungen unverändert (verifiziert per Node-für-Node-Diff gegen den Vorgänger-Commit).
- Die Struktur-Validierung wurde um einen **Dangling-Output-Check** erweitert (nicht-terminale Nodes, deren sämtliche Ausgänge leer sind) — genau die Fehlerklasse, die der bestehende Orphan-Check (nur *eingehende* Kanten) nicht erfasst hatte. Ergebnis: `alice-mail-sync`, `alice-mail-attachment-processor`, `alice-mail-attachment-backfill` und `alice-dms-processor` haben **keine** offenen Ausgänge mehr.

**Weiterhin nicht verifizierbar:** kein Lauf gegen echtes Redis/n8n (die Lock-Simulation bildet Redis-Semantik nach, ersetzt aber keinen Integrationstest — insbesondere echtes n8n-Verhalten bei zeitgleichem Schedule-Feuern zweier Workflows). BUG-15 (pre-existing, Mail-Thumbnail) bleibt bewusst unangetastet und außerhalb dieses Scopes.

## QA Test Results — Iteration 4 (2026-08-24)

**Tested:** 2026-08-24
**Tester:** QA Engineer (AI)
**Commit under test:** `0c92b6d` ("Decouple attachment processing into nightly workflow")
**Test method:** Diff-basierte Regressionsanalyse (`git diff 0c92b6d~1 0c92b6d`), Node-für-Node-Strukturvergleich, AST-/Funktionsrumpf-Diff des verschobenen Codes, Graph-Trace beider Workflows sowie eine **Mock-Harness**, die den *echten* JSON-eingebetteten Code der Nodes `Code: Enqueue Attachment Jobs`, `Code: Fetch Batch`, `Code: Process Queue Item`, `Code: Drop Unparseable Item` und `Code: Time Check` gegen gemocktes Redis/axios/fs/winston ausführt (**37/37 Assertions grün**).
**Keine Live-Ausführung** — kein Zugriff auf n8n/Redis/IMAP/Ollama/Weaviate/NAS.

Iteration 4 ist eine reine **Architektur-Verschiebung** (minütlich → nightly via Redis-Queue), keine Neuentwicklung der Klassifizierungs-/Routing-/Dedup-/Security-Logik. Diese wurde in Iteration 1–3 bereits geprüft; hier wurde daher gezielt verifiziert, dass sie **unverändert** übernommen wurde und dass der neue Trigger-/Queue-Pfad korrekt ist.

### Neue Acceptance Criteria (Iteration 4)

| # | Kriterium | Status | Nachweis |
|---|-----------|--------|----------|
| 4.1 | `alice-mail-sync` klassifiziert/speichert Anhänge nicht mehr selbst, sondern enqueued nur | PASS | `Code: Import Attachments` entfernt, `Code: Enqueue Attachment Jobs` (`rPush` auf `alice:mail:attachment_queue`) an derselben Stelle. Kein `axios`/`fs`-Import mehr im Enqueue-Node — nur `redis`/`path`/`winston` |
| 4.2 | Neuer Workflow nightly `0 2 * * *`, batchweise | PASS | `Schedule: Nightly 02:00` → `cronExpression: 0 2 * * *`; `Code: Fetch Batch` (`lRange`) → `Split In Batches` |
| 4.3 | Exakt dieselbe Klassifizierungs-/Ablage-/MQTT-Logik | PASS | Funktionsrumpf-Diff: 10/12 Helper **byte-identisch**; `buildClassificationPrompt`/`classifyAttachment` unterscheiden sich nur im Parameter-Namen (`mail`→`m`, nötig gegen Shadowing der äußeren `mail`-Konstante) — semantisch identisch. Innerer Schleifenrumpf nach Whitespace-Normalisierung: **1 Kommentarwort** Unterschied |
| 4.4 | Nightly nutzt `OLLAMA_MODEL_DMS` | PASS | `let ollamaModel = 'qwen3:14b'; try { ollamaModel = $env.OLLAMA_MODEL_DMS \|\| 'qwen3:14b'; }` — Vision-Literal `qwen3.5:27b-q4_K_M` kommt im neuen Workflow **nicht** vor (Iteration-3-Fix erhalten, Default sogar sauberer als vorher) |
| 4.5 | Zeitlimit-Schutz analog `alice-dms-processor` | PASS | `MAX_RUNTIME_SECONDS = 14400` (4 h) → Abbruch spätestens 06:00, vor Chat-Kernzeit 07:00. Harness: 3 h → `false`, 4,01 h → `true` |
| 4.6 | Nicht verarbeitbarer Eintrag wird übersprungen/geloggt, Lauf läuft weiter | PASS | Pro-Anhang-`try/catch` unverändert; `Code: Drop Unparseable Item` für korrupte Einträge; `onError: continueRegularOutput` auf `Code: Process Queue Item` |
| 4.7 | `alice-mail-attachment-backfill` unverändert | PASS | `git diff 0c92b6d~1 0c92b6d -- workflows/alice-mail-attachment-backfill.json` → **leer** (0 Bytes Diff) |
| 4.8 | Iteration-2/3-Fixes gelten unverändert | PASS | Harness: Bild >20 KB → `Image/`, PDF → `Invoice/`, 50-MB-Limit greift, Bild-Müll <20 KB ohne LLM verworfen |

### Verdikt zu den 5 selbst gemeldeten Abweichungen

| # | Abweichung | Verdikt | Begründung (eigenständig verifiziert) |
|---|------------|---------|----------------------------------------|
| a | `MQTT: Publish Email Done` bleibt in `alice-mail-sync` | **KORREKT — Abweichung war richtig** | Node ist vorhanden und **neu direkt** an `Process + Classify + Store Emails` (Output 0) verdrahtet, nicht mehr hinter dem Anhang-Node. Er feuert für **alle** `storedEmails` (`Code: Split Stored Emails` filtert nur auf `weaviate_uuid`, **nicht** auf Anhänge) und nur für echte Neu-Inserts (`storedEmails.push()` steht nach `if (alreadyExists) continue;` und nach dem erfolgreichen Weaviate-Insert). AC-5.1 (Zeile 68) fordert den Publish nach **jedem** Mail-Insert — die wörtliche Befolgung der Vorgabe hätte alle anhanglosen Mails dauerhaft ohne Thumbnail-Trigger gelassen. Begründung des Implementers **bestätigt** |
| b | Neuer `MQTT: Publish Attachment Done` | **REDUNDANT + faktisch wirkungslos — siehe BUG-15/BUG-16** | Payload ist `{ weaviate_uuid: <Mail-UUID>, document_type: 'Email', file_type: 'txt', inserted: true }` — also **dieselbe Email-UUID**, die `alice-mail-sync` bereits publiziert hat, **nicht** die der Anhänge. Fachlich inkohärent (Anhänge sind Invoice/Document/Image, keine `Email`-Objekte) und redundant zum Publish aus Baustein 1. Ein Doppel-Processing droht praktisch nicht, weil der Thumbnailer die Nachricht ohnehin verwirft (BUG-15). Kein Datenverlust, kein Security-Impact → **Low** |
| c | `IF: Parse Error` / `Code: Drop Unparseable Item` | **KORREKT UND WIRKSAM** | Harness mit echtem korruptem Eintrag (`{this is not json`): `Code: Fetch Batch` markiert `_parse_error: true` statt zu werfen (Batch läuft weiter, valider Nachbar-Eintrag wird normal verarbeitet), `Code: Drop Unparseable Item` entfernt genau diesen Eintrag per `lRem` und loggt `warn`. **Kein Endlosloop, kein Batch-Crash.** Sinnvolle Ergänzung, nicht im Design skizziert |
| d | Volles `attachments`-Array wird gequeued | **KORREKT — Begründung hält stand** | Verifiziert am kritischen Fall: Mail mit idx0=Signatur-Icon (verworfen), idx1=`.exe` (verworfen), idx2=`rechnung.pdf`, idx3=60 MB (verworfen), idx4=Foto. Nach Queue-Round-Trip ruft der Processor `/attachment` **exakt mit idx 2 und 4** auf, und die korrekten Bytes landen in `Invoice/2026-05-04_billing_rechnung.pdf`. Ein Filtern beim Enqueue hätte die Indizes verschoben. Der Prefilter wird beim Dequeue **erneut** angewandt → verworfene Anhänge werden nicht importiert |
| e | Kein Lock/Mutex im neuen Workflow | **TEILWEISE FALSCH — siehe BUG-17 (Medium)** | Das vom Implementer betrachtete Risiko (**Selbst**-Overlap) besteht tatsächlich nicht: 4 h Budget ≪ 24 h Intervall, Überschreitung ist auf *ein* Item begrenzt. Analysiert wurde aber das **falsche** Risiko. Der Lock `alice:dms:processor:lock:run` existiert nicht gegen Selbst-Overlap, sondern um **GPU-Klassifizierung projektweit zu serialisieren**: `alice-dms-processor`, `alice-dms-classification-backfill`, `alice-dms-language-backfill` und `alice-mail-attachment-backfill` teilen ihn alle. Der neue Processor ist der **fünfte GPU-Konsument und der einzige ohne Lock** — bei **identischem** Trigger `0 2 * * *` wie `alice-dms-processor` (2 h Laufzeit) → bis zu 2 h echte Überschneidung |

### Bugs Found — Iteration 4

#### BUG-15 (Medium, **PRE-EXISTING — nicht durch Iteration 4 verursacht**): `alice-dms-thumbnailer` verwirft alle Mail-Publishes wegen fehlendem `file_path`

- **Severity:** Medium · **Priorität:** hoch für den Nutzen von AC-5, aber **kein Blocker für Iteration 4**
- **Fund:** `alice-dms-thumbnailer` → `Code: Parse & Filter` enthält den Guard
  `if (!msg.weaviate_uuid || !msg.file_path) { logger.warn(...); return []; }`
  Beide `alice/dms/done`-Publishes für Mail-Objekte senden aber **kein** `file_path`: `grep -o "file_path"` liefert **0 Treffer** in `alice-mail-sync.json` *und* in `alice-mail-attachment-processor.json`.
- **Folge:** Mail-Objekte bekommen **nie** ein Thumbnail. Das erklärt und schließt endgültig das seit Iteration 1 offene **AC-5.2** (bisher „NOT VERIFIABLE") — es ist **FAIL**, nicht ungeprüft. AC-5.1 (Publish erfolgt) bleibt PASS; AC-5.3 hängt an 5.2.
- **Root Cause:** Design-Lücke aus Iteration 1: der Thumbnailer-Contract ist dateibasiert (er braucht einen Pfad zum Rendern), Mail-Objekte haben aber keine Datei. Der PROJ-80-Lückenschluss hat den Publish ergänzt, ohne den Consumer-Contract zu prüfen.
- **Nicht durch `0c92b6d` verursacht:** ausdrücklich verifiziert — der Payload ist seit Iteration 1 (`63636f8`) unverändert (`document_type: 'Email', file_type: 'txt', inserted: true`), `alice-dms-thumbnailer.json` wurde in diesem Commit **nicht angefasst** (letzte Änderung: `720d3a4`, weit vor Iteration 4). Iteration 4 hat den Publish nur **umverdrahtet**, nicht inhaltlich geändert.
- **Fix-Vorschlag (eigenes Feature/Folge-Iteration):** entweder Thumbnailer um einen Mail-Renderpfad ohne `file_path` erweitern (Betreff + Body aus Weaviate lesen), oder im Publish ein synthetisches `file_path` mitgeben. **Nicht im Rahmen von Iteration 4 zu fixen.**

#### BUG-16 (Low, neu in Iteration 4): `MQTT: Publish Attachment Done` publiziert die Mail-UUID mit `document_type: 'Email'`

- **Severity:** Low · **Priorität:** niedrig (Aufräumarbeit)
- **Repro:** `alice-mail-attachment-processor` → `IF: Imported Any` → `MQTT: Publish Attachment Done`, Payload `{ weaviate_uuid: $json.weaviate_uuid, document_type: 'Email', file_type: 'txt', inserted: true }`. `$json.weaviate_uuid` stammt aus `Code: Process Queue Item` und ist die **Mail-UUID**, nicht die eines Anhangs.
- **Folge:** Semantisch irreführend (Anhänge sind Invoice/Document/Image, keine `Email`) und redundant zum Publish aus `alice-mail-sync`. **Aktuell wirkungslos**, weil der Thumbnailer die Nachricht mangels `file_path` ohnehin verwirft (BUG-15). Würde BUG-15 gefixt, entstünde ein doppelter Thumbnail-Trigger auf dasselbe Email-Objekt (idempotentes Überschreiben, kein Datenverlust).
- **Bewertung:** Es handelt sich **nicht** um eine Verhaltensänderung gegenüber dem alten Inline-Code — dort feuerte ebenfalls ein Publish pro Mail mit `document_type: 'Email'`. Insofern konsistent mit dem Bestand, aber die vom Implementer selbst gestellte Frage „ist der nötig?" ist mit **nein, streichbar** zu beantworten.
- **Kein** Risiko für Doppel-Import/Doppel-Verarbeitung von Anhängen: die Anhänge laufen über Scanner → Processor → Thumbnailer und werden von diesem Publish nicht berührt.

#### BUG-17 (Medium, neu in Iteration 4): Neuer Nightly-Workflow umgeht den projektweiten GPU-Lock bei identischem 02:00-Trigger

- **Severity:** Medium · **Priorität:** vor Deployment beheben empfohlen (1 Node), **kein Critical/High-Blocker**
- **Repro:** `alice-mail-attachment-processor` startet `0 2 * * *`. `alice-dms-processor` startet **dieselbe Minute** `0 2 * * *`, klassifiziert via Ollama (`HTTP: Ollama Extract`, `Code: BankTransaction Phase B`) und hält dabei `alice:dms:processor:lock:run` (MAX_RUNTIME 2 h). Der neue Workflow acquiriert diesen Lock **nicht** (`grep -c` → **0 Treffer**) und läuft bis zu 4 h.
- **Root Cause:** Der Implementer bewertete den Lock als Schutz gegen *Selbst*-Overlap (dort zu Recht als unnötig eingestuft). Tatsächlich serialisiert der Lock die **GPU-Nutzung über Workflow-Grenzen hinweg** — genau die Anforderung, wegen der Iteration 4 überhaupt existiert (BUG-13/GPU-Kontention). `alice-mail-attachment-backfill` nutzt denselben Key ausdrücklich „damit nie parallel zum Processor auf der GPU klassifiziert wird" (Implementation Notes Iteration 1); der neue Workflow bricht mit dieser etablierten Konvention.
- **Folge:** Bis zu 2 h überlappende Ollama-Last aus zwei Nightly-Jobs. Bei einem Modell (`OLLAMA_MODEL_DMS`) für beide entsteht Queueing/Verlangsamung; bei unterschiedlichen Modellen droht genau das GPU-Umlade-Thrashing, das Iteration 4 vermeiden wollte. **Keine** Datenkorruption: die Queues sind disjunkt (`alice:mail:attachment_queue` vs. `alice:dms:plaintext`), es gibt kein Race auf denselben Items.
- **Fix-Vorschlag:** `Code: Acquire Processor Lock` + `IF: Lock Acquired` aus `alice-mail-attachment-backfill` übernehmen (gleicher Key, Renew im Time-Check, Release am Ende) — oder alternativ den Trigger auf z.B. `0 4 * * *` legen, sodass er nach `alice-dms-processor`s 2-h-Fenster startet. Die Trigger-Variante ist der Ein-Zeilen-Fix, die Lock-Variante die robustere.

**Aus Iteration 3 unverändert offen:** BUG-13 (High) ist **kein Code-Bug in diesem Commit**, sondern eine `.env`-Konfiguration (`OLLAMA_MODEL_DMS` zeigt produktiv auf das Vision-Modell). Iteration 4 adressiert genau diese Ursache architektonisch, indem der Nightly-Lauf ein exklusives Textmodell laden darf — die eigentliche Umstellung bleibt eine Deployment-Aufgabe des Admins. BUG-14 (Low, Doku) unverändert.

### Regression Check (`0c92b6d~1` → `0c92b6d`)

- **Nur 2 Workflow-Dateien berührt:** `alice-mail-sync.json` (+35/−18 Zeilen), `alice-mail-attachment-processor.json` (neu, 514 Zeilen). `alice-mail-attachment-backfill.json`: **0 Bytes Diff** — Anspruch des Implementers bestätigt.
- **Node-für-Node-Vergleich `alice-mail-sync` (alt vs. neu):** genau **1 Node ersetzt** (`Code: Import Attachments` → `Code: Enqueue Attachment Jobs`), **3 Nodes nur `position` geändert** (`Code: Split Stored Emails`, `IF: Has Stored Emails`, `MQTT: Publish Email Done`). **Alle übrigen 15 Nodes byte-identisch**, inkl. `Process + Classify + Store Emails`, `Prepare Mailbox Data`, `Notify: Passthrough` und sämtlicher PG-Nodes.
- **Mail-Metadaten-Pfad (Dedup, Kategorisierung, Weaviate-`Email`-Insert) unangetastet** — verifiziert per Byte-Vergleich des `Process + Classify + Store Emails`-Codes, nicht nur per Diff-Zeilenzahl.
- **Graph-Integrität beider Workflows:** alle Connection-Referenzen und `$('Node')`-Referenzen auflösbar, keine verwaisten Nodes, keine doppelten Namen/IDs.

### Static Checks

| Prüfung | Ergebnis |
|---------|----------|
| Valides JSON (beide Dateien) | PASS |
| Eindeutige Node-Namen und -IDs | PASS |
| Connection-/`$('Node')`-Referenzen auflösbar | PASS (0 Fehler) |
| Verwaiste Nodes | keine |
| `node --check` auf allen Code-Nodes | PASS |
| `console.log` | **0 Treffer** (winston in allen Nodes) |
| Erlaubte `require`-Module | nur `axios, redis, fs, path, winston` |
| Credentials auf MQTT-Nodes | PASS (`mqtt-alice` auf beiden Publishes) |
| Crash-Safety der Queue (`lRem` erst nach Verarbeitung) | PASS — `lRange` liest ohne zu entfernen; `lRem` steht am **Ende** von `Code: Process Queue Item`; der Zeitlimit-Zweig endet **vor** diesem Node, unverarbeitete Einträge bleiben erhalten |
| Zeitlimit greift vor Chat-Kernzeit | PASS (02:00 + 4 h = 06:00 < 07:00) |

### Security Audit — Iteration 4

- [x] **Kein neuer Credential-Pfad.** Der einzige neue Datenpfad ist die Redis-Queue. `passwordEnc` wird **verschlüsselt** aus `Prepare Mailbox Data` übernommen, verschlüsselt in Redis abgelegt und verschlüsselt an `/attachment` bzw. `/attachment-text` weitergereicht. Entschlüsselt wird weiterhin ausschließlich in `alice-mail-reader._decrypt_password()`. Harness-Nachweis: der an `/attachment` übergebene Wert ist byte-identisch zum Original-Blob — **keine Klartext-Materialisierung in n8n**.
- [x] **Keine Credentials in Logs.** Alle winston-Aufrufe des neuen Workflows geprüft: **0** Log-Zeilen enthalten den Password-Blob, **0** enthalten überhaupt das Wort „password". `Code: Drop Unparseable Item` loggt den korrupten Rohstring auf 200 Zeichen gekappt — bei einem korrupten *Mailbox*-Eintrag könnte theoretisch ein Blob-Anfang im Log landen; da der Wert verschlüsselt ist, ist das **kein Klartext-Leak** (Hinweis, kein Bug).
- [x] **Path Traversal weiterhin neutralisiert.** `sanitizeFilename`, `shortenSender` und der `VALID_TARGET_FOLDERS`-Gate sind **byte-identisch** übernommen (Funktionsrumpf-Diff). Der Zielordner bleibt gegen LLM-Halluzination und bösartige Anhangnamen abgesichert.
- [x] **Kein neuer Netzwerk-/Auth-Pfad**, keine neuen Env-Variablen, keine DB-Schema-Änderung, keine RLS-/Auth-Berührung. `REDIS_PASSWORD` wird wie in allen Bestands-Workflows über `$env` gelesen.
- [x] **Queue-Inhalt nicht extern beeinflussbar.** Einträge schreibt ausschließlich `alice-mail-sync`; ein Angreifer müsste bereits Redis-Zugriff haben. Korrupte Einträge führen kontrolliert zum Drop (BUG-15-unabhängig), nicht zu Code-Ausführung — `JSON.parse` in `try/catch`, kein `eval`.

### Nicht verifizierbar in dieser Umgebung

- Kein Lauf gegen echtes n8n/Redis/IMAP/Ollama/Weaviate/NAS — die Mock-Harness ersetzt keinen Integrationstest.
- Reales n8n-Verhalten bei Schedule-Overlap (die Bewertung zu BUG-17 stützt sich auf die Trigger-Konfiguration und die Laufzeitbudgets, nicht auf einen Live-Test).
- Ob `mistral-small3.2:24b` produktiv besser klassifiziert (Live-Test des Users).

### Summary — Iteration 4

- **Kernanspruch „1:1-Code-Verschiebung" bestätigt** — nicht übernommen, sondern per Funktionsrumpf-Diff nachgerechnet: 10/12 Helper byte-identisch, die restlichen 2 nur mit umbenanntem Parameter; innerer Schleifenrumpf nach Whitespace-Normalisierung 1 Kommentarwort Unterschied. Iterations-2/3-Fixes (`Image/`-Routing, `$env.OLLAMA_MODEL_DMS`) nachweislich erhalten.
- **Regression: sauber.** Mail-Metadaten-Pfad byte-identisch, genau 1 Node getauscht, 3 nur verschoben, Backfill 0 Bytes Diff.
- **Abweichungen a, c, d: korrekt** und eigenständig verifiziert (nicht auf die Notes vertraut). **b: redundant** → BUG-16 (Low). **e: Begründung greift zu kurz** → BUG-17 (Medium).
- **Neue Bugs:** 1 × Medium neu (BUG-17), 1 × Low neu (BUG-16), 1 × Medium **pre-existing** (BUG-15, seit Iteration 1, klärt AC-5.2 endgültig als FAIL).
- **Keine neuen Critical/High-Bugs.** Security ohne Befund; kein neuer Credential-Pfad, `passwordEnc` bleibt Ende-zu-Ende verschlüsselt.
- **Production Ready:** **YES — READY** (per Production-Ready-Regel blockieren nur Critical/High; Medium/Low blockieren nicht).
- **Empfehlung:** **Approved.** Vor bzw. beim Deployment abzuarbeiten:
  1. **BUG-17** (empfohlen vor Deploy, ~1 Node): Lock `alice:dms:processor:lock:run` übernehmen **oder** Trigger auf `0 4 * * *` verschieben, damit sich der Lauf nicht mit `alice-dms-processor` überlappt.
  2. **BUG-16**: `MQTT: Publish Attachment Done` ersatzlos streichen (redundant zum Publish aus `alice-mail-sync`).
  3. **BUG-15** als Folge-Feature einplanen — ohne diesen Fix bleibt AC-5.2/5.3 (Mail-Thumbnails) dauerhaft unerfüllt, unabhängig von PROJ-53.
  4. Unverändert aus Iteration 3: `OLLAMA_MODEL_DMS` produktiv auf ein Textmodell setzen (BUG-13) und `Image/` in `alice.dms_watched_folders` eintragen.
  5. Deployment umfasst **beide** Workflows: `alice-mail-sync` (geändert) und `alice-mail-attachment-processor` (neu, muss aktiviert werden).

---

## QA-Nachprüfung — BUG-16 / BUG-17 behoben (2026-08-24)

**Tested:** 2026-08-24
**Tester:** QA Engineer (AI)
**Commit under test:** `ee1696b` (Fix) gegen den zuvor geprüften Stand `0c92b6d`; Folge-Commit `f4a3bc2` (nur INDEX/Status) mitgeprüft.
**Test method:** Node-für-Node-Diff `0c92b6d → ee1696b`, eigenständiges Nachlesen des Lock-Musters in `alice-mail-attachment-backfill.json`, Lua-Skript-Vergleich über alle drei Lock-Workflows, **Lock-Simulation gegen echte Redis-`SET NX PX`-/TTL-Semantik** (23/23 Assertions grün) sowie erneuter Lauf der Iteration-4-Mock-Harness gegen den gefixten Stand (**38/38 grün**).

### BUG-17 — GPU-Lock: **BEHOBEN, verifiziert**

| # | Prüfpunkt | Status | Nachweis |
|---|-----------|--------|----------|
| 1 | Gleicher Lock-Key wie die anderen Lock-Workflows | PASS | **Eigenständig** aus `alice-mail-attachment-backfill.json` gelesen (nicht aus den Notes übernommen): `LOCK_KEY = 'alice:dms:processor:lock:run'`, `LOCK_TTL_MS = 1800000` — identisch im neuen Node. `Code: Acquire Processor Lock` ist nach Abzug von Kommentaren/Leerzeilen **byte-identisch** zu `Code: Acquire Backfill Lock`; einzige Deltas sind die beiden Logger-Identitätsstrings (`workflow`/`node`-Meta und `[MailAttachmentProcessor]` statt `[MailBackfill]`) |
| 1b | Release-/Renew-Lua identisch zum Bestand | PASS | Beide Skripte (`RELEASE` mit `DEL`, `RENEW` mit `SET … PX`) sind **byte-identisch in allen drei** Workflows (`alice-dms-processor`, `alice-mail-attachment-backfill`, neu) — 0 abweichende Varianten |
| 2 | Mutual Exclusion funktioniert real | PASS | Simulation mit echter `SET NX`-Semantik: zweiter Acquirer erhält `nil` → `_lock_acquired: false`, `lock_owner: null` → `IF: Processor Lock Acquired` routet auf `Code: Log Already Running`. Szenario „`alice-dms-processor` und Mail-Processor starten in **derselben** 02:00-Minute": **genau einer** bekommt die GPU |
| 2b | Fremder Lock nicht löschbar | PASS | Owner-geprüftes Lua: Release mit fremdem Token → `0`, Lock bleibt bestehen; nur der echte Owner löscht (`1`) |
| 3 | Kein Deadlock nach Crash | PASS | TTL 1800 s ≪ Laufzeitbudget 14400 s. Simulation: Crash nach 10 min → andere weiterhin blockiert; nach 31 min (> 30 min TTL) acquiriert der nächste Lauf **erfolgreich**. Ein abgestürzter Lauf kann die Nacht also nicht blockieren |
| 3b | Renewal trägt lange gesunde Läufe | PASS | Erneuerung pro Item (`Code: Time Check`): 12 × 25 min = 5 h ohne Ownership-Verlust. Umgekehrt: Lücke > 30 min → `_lock_lost: true` |
| 3c | Ownership-Verlust bricht sauber ab | PASS | `IF: Time Limit Reached` prüft jetzt `_time_limit_reached \|\| _lock_lost`; ein Lauf, dessen Lock übernommen wurde, bricht ab statt parallel weiter auf der GPU zu rechnen, und löscht den fremden Lock nicht |
| 4 | Alle vier Exit-Pfade korrekt | PASS | **busy-skip**: kein Release, Queue unangetastet → nächste Nacht holt alles nach. **empty-queue** (`Code: Empty Summary`, neu): released — verhindert, dass eine leere Nacht den Lock bis TTL-Ablauf hält. **Normalabschluss** (`Code: Final Log`) und **Zeitlimit-Abbruch** (`Code: Final Log (Time)`): released. Alle drei Release-Stellen nutzen das owner-geprüfte Lua |

### BUG-16 — redundanter MQTT-Node: **BEHOBEN, verifiziert**

| # | Prüfpunkt | Status | Nachweis |
|---|-----------|--------|----------|
| 1 | Node + Credential entfernt | PASS | `MQTT: Publish Attachment Done` und `IF: Imported Any` sind aus `nodes` verschwunden. Der Workflow hat **keinen einzigen** Node mit Credentials mehr (vorher: `mqtt-alice`) |
| 2 | Keine hängenden Referenzen | PASS | `grep` auf `_imported_any`, `IF: Imported Any`, `Publish Attachment Done`, `mqtt` im gesamten Workflow-JSON: **0 Treffer**. Graph-Validierung: 0 unaufgelöste Connection-/`$('Node')`-Referenzen, 0 verwaiste Nodes |
| 3 | Direkter Rücksprung zu `Split In Batches` | PASS | Graph-Trace: `Code: Process Queue Item [out0] -> Split In Batches` (vorher über `IF: Imported Any`). `Code: Drop Unparseable Item` ebenfalls unverändert direkt zurück |
| 4 | `alice-mail-sync` unberührt | PASS | `git diff 0c92b6d ee1696b -- workflows/alice-mail-sync.json` → **0 Zeilen**. `MQTT: Publish Email Done` weiterhin vorhanden, Topic `alice/dms/done`, Credential `mqtt-alice` gesetzt. AC-5.1 unverändert erfüllt |

### Regression der bereits verifizierten Iteration-4-Logik

- **Node-Diff `0c92b6d → ee1696b`:** 5 Nodes neu (Lock/Skip/Empty-Summary), 2 entfernt (BUG-16), 4 Code-Nodes geändert, 4 nur `position`. Eng begrenzt wie angekündigt.
- **`Code: Process Queue Item`:** Delta ist **ausschließlich** der Wegfall von `_imported_any` aus dem Return (1 Zeile). Prefilter, Extension-Routing, PDF-Text, Klassifizierung, NAS-Write, Kollisions-Suffix und das `lRem` am Ende sind **unverändert** — der 1:1-Code-Move steht weiterhin.
- **`Code: Drop Unparseable Item`:** nur `_imported_any` aus dem Return entfernt.
- **`Code: Final Log` / `Final Log (Time)`:** nur der owner-geprüfte Release-Block ergänzt; Statistik-/Logging-Logik unverändert.
- **Mock-Harness erneut gegen den gefixten Stand: 38/38 grün** — Queue-Crash-Sicherheit (`lRange` liest ohne Entfernen, `lRem` erst nach Verarbeitung), Index-Integrität (`/attachment` trifft idx 2 und 4), Medien-Routing (`Image/`/`Video/`/`Audio/`), 50-MB-Limit, Bild-Müll-Filter, Zeitlimit (3 h → weiter, 4,01 h → Abbruch) und `$env.OLLAMA_MODEL_DMS` unverändert korrekt.

### Static Checks (beide Workflows)

Valides JSON · eindeutige Node-Namen/IDs · 0 unaufgelöste Connection-/`$('Node')`-Referenzen · keine verwaisten Nodes · alle Code-Nodes `node --check` grün · **0 `console.log`** · `require`-Module `axios, crypto, fs, path, redis, winston` — `crypto` ist in `docker/compose/automations/n8n/compose.yml` über `NODE_FUNCTION_ALLOW_BUILTIN=crypto,fs,path` freigegeben und wird bereits von den drei anderen Lock-Workflows genutzt (kein neues Deployment-Risiko).

### Prüfung des Restaurations-Commits `f4a3bc2`

Kein Phantom-Regress: `f4a3bc2` ändert ausschließlich `features/INDEX.md` (PROJ-93-Zeile, `Next Available ID` → PROJ-94, PROJ-53-Status) und den Status-Header des Specs. **Keine** Workflow-JSONs und **kein** inhaltlicher Spec-Abschnitt berührt.

### Security — Nachprüfung

Unverändert ohne Befund. Der Lock führt keinen neuen Credential-Pfad ein (`crypto.randomUUID()` als Owner-Token, kein Secret); `REDIS_PASSWORD` wird wie im Bestand über `$env` gelesen; kein Log enthält Passwörter. Durch den Wegfall des MQTT-Nodes hat der Workflow jetzt **weniger** Credential-Bindungen als zuvor. `passwordEnc` bleibt Ende-zu-Ende verschlüsselt (Harness-Nachweis erneut grün).

### Summary — Nachprüfung

- **BUG-17: behoben und eigenständig verifiziert.** Lock-Key, TTL und beide Lua-Skripte nachweislich identisch zum etablierten Muster; Mutual Exclusion, TTL-Recovery, Renewal, Ownership-Verlust und alle vier Exit-Pfade simulativ bestätigt (23/23). Der neue Workflow ist damit der fünfte, korrekt serialisierte GPU-Konsument.
- **BUG-16: behoben.** Node, Gate-IF, Credential und Feld restlos entfernt, keine hängenden Referenzen, `alice-mail-sync` nachweislich unberührt.
- **Keine neuen Bugs.** Keine Critical/High offen. BUG-15 bleibt out of scope und ist als **PROJ-93** separat getrackt. BUG-13 (Modell-`.env`) und BUG-14 (Doku) unverändert als Deployment-/Folgeaufgaben.
- **Production Ready:** **YES — READY**
- **Empfehlung:** **Approved.** Verbleibende Deployment-Voraussetzungen: `OLLAMA_MODEL_DMS` auf ein Textmodell setzen (BUG-13), `Image/` in `alice.dms_watched_folders` eintragen, und **beide** Workflows deployen (`alice-mail-sync` geändert, `alice-mail-attachment-processor` neu + aktivieren).

## Deployment
_To be added by /deploy_
