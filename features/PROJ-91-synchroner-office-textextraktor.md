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

### E) Workflow Architecture

PROJ-91 hat keine eigene UI-Komponente. Es erweitert einen bestehenden HTTP-Endpunkt (`alice-mail-reader`) und die Routing-Logik in zwei bestehenden n8n-Workflows — kein neuer Container, kein neuer Trigger.

**Betroffene Bausteine:**

1. **`alice-mail-reader` (Docker-Service, Endpunkt `/attachment-text`):** Der bestehende Endpunkt erkennt bisher nur PDF. Er wird um eine Format-Erkennung für DOCX/XLSX/ODT/ODS erweitert: anhand der Dateiendung/des MIME-Typs (gleiches Muster wie die bestehende PDF-Erkennung) wird die passende Extraktionsroutine gewählt. Das äußere Verhalten (Input: `uid` + `attachment_index`, Output: `{ text, truncated, status }`) bleibt für alle Aufrufer identisch — nur die Menge der erkannten Formate wächst.
2. **`alice-mail-attachment-processor` (n8n-Workflow, Live-Sync):** Die bestehende Weiche "PDF → Volltext holen, sonst nur Dateiname+Kontext" wird um Office-Formate erweitert — ein neues Set von Dateiendungen (analog zum bestehenden PDF-Set) löst denselben Volltextextraktions-Aufruf aus.
3. **`alice-mail-attachment-backfill` (n8n-Workflow, nachträglicher Import):** Erhält dieselbe Erweiterung, damit Live-Sync und Backfill konsistent bleiben (identisch zum bereits etablierten Muster bei der PDF-Einführung).

**Data flow:** Mail-Anhang mit Office-Endung erkannt → Workflow ruft `alice-mail-reader`s `/attachment-text` auf → Service lädt den Anhang, erkennt das Office-Format, extrahiert den Volltext mit einer leichten, format-spezifischen Bibliothek, kappt bei 50.000 Zeichen → Text fließt in denselben bestehenden Klassifizierungs-Prompt wie bisher schon für PDF/TXT/MD.

**Integrationen:** Keine neuen. `alice-mail-reader` bleibt ein reiner HTTP-Service ohne neue externe Abhängigkeiten (nur neue Python-Bibliotheken im Container selbst, siehe Dependencies).

**Fehlerverhalten:** Unverändert zur bestehenden PDF-Konvention — eine fehlgeschlagene oder nicht unterstützte Extraktion liefert einen leeren Text mit einem Statusfeld statt eines HTTP-Fehlers. Der aufrufende Workflow fällt dann automatisch auf die bisherige Klassifizierung anhand von Dateiname + Mail-Kontext zurück (kein neuer Fehlerpfad nötig, bestehendes Fallback-Verhalten greift unverändert).

### Datenmodell (fachlich)

Kein neues Datenbankschema, keine neue Datenstruktur. Der bestehende Response-Vertrag von `/attachment-text` (`text`, `truncated`, `status`) bleibt unverändert — er wird lediglich für mehr Dateiformate befüllt statt für PDF exklusiv.

### Tech-Entscheidungen (Begründung)

- **Erweiterung des bestehenden `/attachment-text`-Endpunkts statt neuem Service/Endpunkt:** Der Aufrufer-Contract (uid + attachment_index → Text) ist bereits etabliert und wird von zwei Workflows genutzt. Ein Format mehr zu erkennen ist eine interne Erweiterung, kein neuer Integrationspunkt — spart Betriebsaufwand (kein neuer Container, kein neuer Healthcheck, keine neue compose-Datei) für eine Funktion, die ohnehin nur von `alice-mail-reader`s bestehenden Aufrufern gebraucht wird.
- **Leichte Einzelbibliotheken (`python-docx`, `openpyxl`, `odfpy`) statt `markitdown`:** `alice-mail-reader` läuft auf `python:3.12-alpine` (musl, kein C-Compiler im Image) — dieselbe Einschränkung, die in PROJ-53 bereits `pdfplumber` zugunsten von `pypdf` ausgeschlossen hat (Pillow-Abhängigkeit ohne vorgebaute musl-Wheels). `markitdown` bündelt Abhängigkeiten für viele Formate und würde denselben Kompatibilitätsengpass riskieren oder einen Wechsel des Base-Images erzwingen — ein deutlich größerer Eingriff in einen bestehenden, produktiven Service für einen Funktionszuwachs, der mit gezielten, bereits musl-erprobten Bibliotheken (reine Python-Wheels, wie das bestehende `pypdf`) günstiger zu haben ist.
- **`dms-extractor-office` bleibt unangetastet:** Die asynchrone, LibreOffice-basierte Pipeline für die DMS-Pfad-Verarbeitung hat andere Anforderungen (Batch-Verarbeitung großer NAS-Bestände, keine Synchronität nötig) und andere Formatgüte (LibreOffice rendert komplexere Layouts potenziell genauer). Ein Ersatz wäre ein eigenständiges, größeres Vorhaben mit eigenem Abwägungsbedarf — bewusst außerhalb des PROJ-91-Scopes (siehe Nutzerentscheidung in der Spec-Phase).
- **Gleiches Truncation-Limit (50.000 Zeichen) wie PDF:** Wiederverwendung des bestehenden `PLAINTEXT_MAX_CHARS`-Werts statt eines neuen, formatabhängigen Grenzwerts — konsistent mit der bereits etablierten Konvention und vermeidet unnötige Konfigurationsvielfalt.
- **Kein Prozess-Timeout-Mechanismus für die neuen Extraktionsroutinen:** Anders als `dms-extractor-office` (LibreOffice-Subprocess mit explizitem 120s-Timeout) laufen `python-docx`/`openpyxl`/`odfpy` In-Process ohne Subprocess-Aufruf — der bestehende `gunicorn --timeout 60` des Containers ist bereits die etablierte äußere Grenze für jeden Request, kein zusätzlicher Mechanismus nötig.

### Dependencies (Pakete)

- **`python-docx`** — Volltextextraktion aus DOCX (reines Python-Wheel, musl-kompatibel).
- **`openpyxl`** — Zellinhalt-Extraktion aus XLSX (reines Python-Wheel, musl-kompatibel).
- **`odfpy`** — Volltextextraktion aus ODT/ODS (reines Python-Wheel, musl-kompatibel).

Alle drei ergänzen die bestehende `pip install`-Zeile im `alice-mail-reader`-Dockerfile (kein `requirements.txt` in diesem Service — Konvention beibehalten, siehe PROJ-53).

### Implementation Notes (Backend)

**Umgesetzt in:**
- `docker/compose/automations/alice-mail-reader/app.py` — `/attachment-text` erweitert
- `docker/compose/automations/alice-mail-reader/Dockerfile` — drei neue Abhängigkeiten
- `workflows/alice-mail-attachment-processor.json` — Routing erweitert (1 Zeile geändert)
- `workflows/alice-mail-attachment-backfill.json` — Routing erweitert (1 Zeile geändert)

**Bibliotheks-Verifikation (vor Implementierung durchgeführt):** `python-docx==1.2.0` und `openpyxl==3.1.5` sind reine Python-Wheels (`py3-none-any`). `odfpy==1.4.1` liefert nur ein sdist, enthält aber laut `setup.py`-Prüfung keine C-Extensions (kein `ext_modules`, keine `.c`/`.pyx`-Dateien) — baut ohne Compiler. Die einzige transitive Sorge war `python-docx`s Abhängigkeit auf `lxml` (historisch C-Extension-lastig): `lxml` liefert ein vorgebautes `musllinux_1_2_x86_64`-Wheel für Python 3.12 — passt zum Alpine-3.24-Base-Image von `alice-mail-reader`. Alle drei Bibliotheken damit ohne Compiler auf Alpine installierbar, wie in der Architektur-Entscheidung vorausgesetzt.

**`app.py`-Änderungen:**

- Neue Konstante `OFFICE_EXTENSIONS = {".docx", ".xlsx", ".odt", ".ods"}` und `_office_format(filename)` — Erkennung ausschließlich per Dateiendung (nicht MIME-Typ, da E-Mail-Clients für Office-Formate inkonsistente MIME-Typen senden; Konvention bereits so in `dms-extractor-office` etabliert).
- Vier neue Extraktionsfunktionen: `_extract_docx_text` (Absätze via `python-docx`), `_extract_xlsx_text` (Zellinhalte via `openpyxl`, `read_only=True` + `data_only=True`), `_extract_odt_text`/`_extract_ods_text` (via `odfpy`, Absätze bzw. Tabellenzeilen/-zellen).
- `fetch_attachment_text()` (`/attachment-text`) umstrukturiert: PDF-Zweig unverändert in der Logik (nur von `if not _is_pdf` auf `if _is_pdf` invertiert, um Platz für den neuen Office-Zweig zu schaffen — Verhalten identisch, per Diff-Review bestätigt), neuer Office-Zweig mit gleichem Truncation-Verhalten (`PLAINTEXT_MAX_CHARS`, wiederverwendet) und gleichem Fehlerverhalten (`status: "extraction_failed"`, kein HTTP-Fehler) wie PDF. Neuer Fallback-Zweig für alles andere: `status: "unsupported_format"` (generalisiert von zuvor `"not_a_pdf"` — kein Aufrufer prüft den konkreten String-Wert, nur `text`).

**Workflow-Änderungen (beide identisch):**

- Neues `OFFICE_EXTENSIONS`-Set neben dem bestehenden `PDF_EXTENSIONS`.
- `fetchPdfText()` → `fetchExtractedText()` umbenannt (Funktionskörper unverändert, nur Name + Kommentar, da die Funktion jetzt PDF und Office bedient).
- Aufruf-Bedingung erweitert: `PDF_EXTENSIONS.has(ext)` → `PDF_EXTENSIONS.has(ext) || OFFICE_EXTENSIONS.has(ext)`.

**`dms-extractor-office` bewusst nicht angefasst** (spec-konform, siehe Nutzerentscheidung).

**Verifikation (eigenständig, mit echten generierten Dateien):**

- `python3 -m py_compile app.py`: syntaktisch valide.
- Echte DOCX/XLSX/ODT/ODS-Testdateien mit `python-docx`/`openpyxl`/`odfpy` selbst erzeugt (nicht nur Mocks) und gegen die vier neuen Extraktionsfunktionen ausgeführt: alle vier liefern den erwarteten Text korrekt (inkl. Tab-getrennter Zellen für XLSX/ODS).
- Format-Erkennung `_office_format()`: Groß-/Kleinschreibung (`.DOCX`, `.ODS`), PDF, Bild, sowie legacy `.doc`/`.xls` (bewusst **nicht** erkannt, da nur OOXML/ODF unterstützt) — alle 8 getesteten Fälle korrekt.
- Fehlerfälle: korrupte/zufällige Bytes für alle vier Formate → sauberer Python-Exception (`BadZipFile` bzw. Äquivalent), kein stiller Fallback auf leeren Text ohne Fehlerkennzeichnung. Leere Datei (0 Byte) → ebenfalls sauberer Fehler, kein Crash.
- Truncation: 60.000-Zeichen-DOCX → korrekt bei 50.000 gekappt.
- XLSX-Formel-Edge-Case (Formel ohne gecachten Wert): liefert leere Zelle statt Formeltext oder Crash — wie in der Spec dokumentiert.
- **End-to-End-HTTP-Test** (Flask-Testclient, `_fetch_attachment_part` gemockt, um ohne echten IMAP-Server zu testen): alle 4 Office-Formate → `200`, `status: "ok"`, korrekter Text; nicht unterstütztes Format (`.zip`) → `200`, `status: "unsupported_format"`; korrupte `.docx`-Bytes → `200`, `status: "extraction_failed"`; legacy `.doc` → `200`, `status: "unsupported_format"` (kein Fehlrouting in einen Office-Extraktor).
- JS-Syntaxcheck (`node --check`) für beide geänderten Workflow-Nodes: bestanden. Kein `console.log` eingeführt. Diff-Scoping: je 1 geänderte Zeile pro Workflow-JSON (nur der `jsCode`-Parameter).

**Nicht verifizierbar ohne Deploy/echte IMAP-Verbindung:** Verhalten mit einer echten, aus einem E-Mail-Client verschickten Office-Datei (reale Formatierungs-Eigenheiten, Verschlüsselung durch Absender-Software), tatsächliche Klassifizierungsqualität des LLM mit dem neuen Volltext, reales Timing unter `gunicorn --timeout 60` bei großen Dateien.

---
_Implementation abgeschlossen._

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
