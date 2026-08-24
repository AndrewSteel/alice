# PROJ-91: Synchroner Office-Textextraktor

## Status: Planned
**Created:** 2026-08-24
**Last Updated:** 2026-08-24

## Dependencies
- Erweitert: `alice-mail-reader`s `/attachment-text`-Endpunkt (PROJ-53, Deployed) — bisher nur PDF via `pypdf`, wird um DOCX/XLSX/ODT/ODS erweitert.
- Betrifft: `alice-mail-attachment-processor` und `alice-mail-attachment-backfill` (beide PROJ-53, Deployed) — deren Routing-Logik wird erweitert, damit Office-Anhänge den (erweiterten) Endpunkt tatsächlich aufrufen.
- Kein Zusammenhang mit `dms-extractor-office` (async MQTT/Redis-Worker, LibreOffice-basiert) — dieser bleibt unverändert für die DMS-Pfad-Pipeline bestehen. PROJ-91 ist bewusst auf die Mail-Anhang-Klassifizierungslücke aus PROJ-53 begrenzt (kein Ersatz für `dms-extractor-office`).

## Kontext

PROJ-53 hat die synchrone Klassifizierung von Mail-Anhängen eingeführt: für PDF wird der Volltext synchron extrahiert (`alice-mail-reader`s `/attachment-text`, `pypdf`) und an den LLM-Klassifizierungs-Prompt übergeben; für TXT/MD wird direkt dekodiert. Für DOCX/XLSX/ODT/ODS gibt es **keinen** synchronen Extraktor — diese Anhänge werden bisher ausschließlich anhand von Dateiname + Mail-Betreff + Absender + Body-Preview klassifiziert (kein Volltext), eine bewusst dokumentierte Einschränkung mit Verweis auf dieses Ticket.

Der bestehende asynchrone `dms-extractor-office` (LibreOffice headless, MQTT/Redis-Worker, bis zu 120s Laufzeit) ist für die synchrone Mail-Klassifizierung ungeeignet — der Klassifizierungsschritt läuft inline im n8n-Workflow und darf nicht auf eine Message-Queue warten. Ein 1:1-Nachbau mit LibreOffice würde außerdem die Kaltstart-/Ressourcenkosten des DMS-Pipeline-Containers duplizieren.

`alice-mail-reader` läuft auf `python:3.12-alpine` (musl, kein C-Compiler im Image). Aus demselben Grund, aus dem PROJ-53 `pypdf` statt `pdfplumber` gewählt hat (Pillow-Abhängigkeit hat keine vorgebauten musl-Wheels), scheidet die vollständige `markitdown`-Bibliothek aus — sie zieht für verschiedene Formate diverse Abhängigkeiten nach, die denselben Kompatibilitätsengpass riskieren. PROJ-91 verwendet stattdessen gezielt leichte, reine Python-Bibliotheken (`python-docx`, `openpyxl`, `odfpy`), die wie `pypdf` ohne Compiler auf Alpine installierbar sind.

## User Stories

- Als Admin möchte ich, dass Mail-Anhänge im Format DOCX/XLSX/ODT/ODS bei der automatischen Mail-Anhang-Klassifizierung (PROJ-53) anhand ihres tatsächlichen Inhalts eingeordnet werden, nicht nur anhand von Dateiname und Mail-Kontext — analog zu PDF.
- Als Admin möchte ich, dass ein nichtssagender Dateiname (z.B. "Dokument1.docx") kein Hindernis mehr für eine korrekte Erstklassifizierung ist, wenn der Dateiinhalt selbst aussagekräftig ist.

## Acceptance Criteria

- [ ] `alice-mail-reader`s `/attachment-text`-Endpunkt erkennt zusätzlich zu PDF auch DOCX, XLSX, ODT und ODS (per Dateiendung/MIME-Typ, wie bereits für PDF etabliert) und extrahiert deren Volltext synchron
- [ ] DOCX-Volltext wird mit `python-docx` extrahiert (Absatztexte, in Lesereihenfolge)
- [ ] XLSX-Volltext wird mit `openpyxl` extrahiert (Zellinhalte aller Tabellenblätter als Text)
- [ ] ODT/ODS-Volltext wird mit `odfpy` extrahiert
- [ ] Extrahierter Text wird bei 50.000 Zeichen abgeschnitten (`truncated: true` im Response), identisch zum bestehenden PDF-Limit (`PLAINTEXT_MAX_CHARS`)
- [ ] Für weiterhin nicht unterstützte Dateitypen (z.B. Bilder, ZIP, alte `.doc`/`.xls`-Binärformate) liefert der Endpunkt wie bisher `status: "not_a_pdf"`-äquivalent (kein Fehler, leerer Text) — Statusfeld-Naming wird im Zuge dieser Erweiterung generalisiert (z.B. `"unsupported_format"`)
- [ ] Eine fehlgeschlagene Office-Extraktion (korrupte Datei, Parser-Exception) liefert `status: "extraction_failed"` mit leerem Text statt eines HTTP-Fehlers — identisches Fehlerverhalten wie bei PDF
- [ ] `alice-mail-attachment-processor` ruft für DOCX/XLSX/ODT/ODS-Anhänge den erweiterten `/attachment-text`-Endpunkt auf (neues `OFFICE_EXTENSIONS`-Set analog zu `PDF_EXTENSIONS`) und übergibt den extrahierten Text an den bestehenden Klassifizierungs-Prompt
- [ ] `alice-mail-attachment-backfill` erhält dieselbe Routing-Erweiterung (Konsistenz zwischen Live-Sync und Backfill, wie bereits für PDF etabliert)
- [ ] Bestehendes Verhalten für PDF, TXT/MD und alle anderen Dateitypen bleibt unverändert (keine Regression)

## Edge Cases

- **Passwortgeschützte/verschlüsselte Office-Datei**: Extraktion schlägt fehl (Parser-Exception) → `status: "extraction_failed"`, leerer Text, Aufrufer fällt auf Dateiname+Mail-Kontext zurück (identisch zum bestehenden PDF-Verhalten bei verschlüsselten PDFs).
- **Sehr großes XLSX mit vielen Tabellenblättern/Zeilen**: Extraktion läuft bis zum bestehenden Truncation-Limit (50.000 Zeichen), keine unbegrenzte Verarbeitungszeit. `openpyxl` im `read_only`-Modus vermeidet, dass die gesamte Datei unnötig in den Speicher geladen wird.
- **Altes Binärformat `.doc`/`.xls` (nicht `.docx`/`.xlsx`)**: Wird von `python-docx`/`openpyxl` nicht unterstützt (nur OOXML) → `status: "unsupported_format"`, kein Crash, Fallback auf Dateiname+Kontext (wie heute bereits der Fall).
- **Leere Office-Datei (0 Byte oder Datei ohne Inhalt)**: Liefert leeren Text ohne Fehler, `truncated: false` — Klassifizierung fällt dann faktisch auf Dateiname+Kontext zurück, kein Sonderfall nötig.
- **Timeout bei der Extraktion**: Reine Python-Parser (kein Subprocess wie LibreOffice) — keine Prozess-Timeout-Logik nötig, aber der bestehende `gunicorn --timeout 60` des Containers bleibt die äußere Grenze; sollte eine pathologisch große Datei dennoch hängen bleiben, killt gunicorn den Worker wie bei jedem anderen Request-Timeout.
- **XLSX mit Formeln statt Werten**: `openpyxl` mit `data_only=True` liest die zuletzt beim Speichern berechneten Werte (kein Formel-Nachrechnen) — falls keine gecachten Werte vorhanden sind (z.B. Datei nie in Excel geöffnet), liefert die Zelle `None`/leer statt der Formel als Text.

## Technical Requirements (optional)

- Bibliotheken: `python-docx`, `openpyxl`, `odfpy` — alle reine Python-Wheels, musl/Alpine-kompatibel ohne Compiler (gleiche Anforderung wie das bestehende `pypdf`).
- Wiederverwendung des bestehenden `PLAINTEXT_MAX_CHARS`-Werts (50.000) statt eines neuen Konfigurationswerts.
- Kein neuer Container, kein neuer Service — Erweiterung von `alice-mail-reader` (bestehender Endpunkt `/attachment-text`).
- Kein Eingriff in `dms-extractor-office` oder die DMS-Pfad-Pipeline.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
