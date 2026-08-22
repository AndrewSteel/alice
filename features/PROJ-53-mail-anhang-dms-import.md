# PROJ-53: Mail-Anhang DMS-Import

## Status: Planned
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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
