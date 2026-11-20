# PROJ-91: Synchroner Office-Textextraktor

## Status: Deployed
**Created:** 2026-08-24
**Last Updated:** 2026-08-24 (deployed)

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

**Tested:** 2026-08-24
**Commit under test:** `bde6f8a` (feat(PROJ-91): Add synchronous Office text extraction to alice-mail-reader)
**Scope:** `docker/compose/automations/alice-mail-reader/app.py`, `Dockerfile`, `workflows/alice-mail-attachment-processor.json`, `workflows/alice-mail-attachment-backfill.json`
**Tester:** QA Engineer (AI)

### Testmethode

Kein Deploy, kein Live-Container in dieser Umgebung. Eigenständige Verifikation (nicht auf die Implementation Notes verlassen):

1. **Isolierte Bibliotheks-Re-Verifikation:** `python-docx`/`openpyxl`/`odfpy` selbst frisch in einem venv installiert, Wheel-Typ und transitive Abhängigkeiten (`lxml`, `et-xmlfile`) unabhängig gegen musllinux-Wheels geprüft.
2. **Re-Execution der echten Extraktionsfunktionen** gegen frisch selbst erzeugte DOCX/XLSX/ODT/ODS-Dateien (nicht die des Implementers wiederverwendet).
3. **End-to-End-HTTP-Test** über den echten Flask-Testclient (`_fetch_attachment_part` gemockt) für alle Formate + Fehlerfälle.
4. **Gezielter Security-Red-Team-Test:** XXE-Injection-Versuch gegen `odf_load`/`python-docx`/`lxml` mit selbst gebauten bösartigen ODT-/DOCX-Dateien; Ressourcenverbrauch (Zeit/Speicher) bei stark komprimierbaren "Zip-Bomb"-artigen Office-Dateien gemessen, nicht nur angenommen.
5. **Struktureller Diff-Review** `bde6f8a~1` → `bde6f8a`: bestätigt, dass die PDF-Zweig-Logik nur umstrukturiert (nicht funktional verändert) wurde.

### Acceptance Criteria Status

| # | Acceptance Criterion | Status | Nachweis |
|---|---|---|---|
| AC-1 | `/attachment-text` erkennt DOCX/XLSX/ODT/ODS zusätzlich zu PDF | **PASS** | `_office_format()` per Dateiendung, case-insensitive getestet (`.DOCX`, `.ODS` etc. korrekt erkannt); End-to-End-Test über alle 4 Formate erfolgreich. |
| AC-2 | DOCX-Volltext via `python-docx` (Absätze, Lesereihenfolge) | **PASS** | Eigene Testdatei mit zwei Absätzen erzeugt → `'Rechnung Nr. 12345\nBetrag: 199,99 EUR'`, Reihenfolge korrekt. |
| AC-3 | XLSX-Volltext via `openpyxl` (alle Tabellenblätter, Zellinhalte) | **PASS** | Eigene Testdatei → `'Datum\tBetrag\n2026-08-24\t199.99'`, Tab-getrennt, Zeilenumbruch pro Zeile. |
| AC-4 | ODT/ODS-Volltext via `odfpy` | **PASS** | Beide eigenständig getestet: ODT → Absatztexte korrekt; ODS → Tabellenzellen Tab-getrennt korrekt. |
| AC-5 | Truncation bei 50.000 Zeichen, `truncated: true` | **PASS** | 60.000-Zeichen-DOCX → Endpunkt-Response exakt 50.000 Zeichen (`PLAINTEXT_MAX_CHARS`-Konstante wiederverwendet, kein neuer Wert). |
| AC-6 | Nicht unterstützte Formate → `status`-Feld statt Fehler | **PASS** (mit Namensabweichung, siehe unten) | `.zip`, legacy `.doc` → HTTP 200, `status: "unsupported_format"`, leerer Text. Status-Naming wurde wie in der Spec als Option vorgesehen generalisiert (`"not_a_pdf"` → `"unsupported_format"`); kein Aufrufer im Repo prüft den alten String-Wert (verifiziert per Grep), keine Regression. |
| AC-7 | Fehlgeschlagene Office-Extraktion → `status: "extraction_failed"`, kein HTTP-Fehler | **PASS** | Korrupte Bytes für alle 4 Formate → sauber gefangene Exception (`BadZipFile`), HTTP 200 mit `status: "extraction_failed"`. |
| AC-8 | `alice-mail-attachment-processor` ruft erweiterten Endpunkt für Office-Anhänge auf | **PASS** | `OFFICE_EXTENSIONS`-Set hinzugefügt, Aufruf-Bedingung um `\|\| OFFICE_EXTENSIONS.has(pre.ext)` erweitert, `fetchExtractedText()` (umbenannt von `fetchPdfText`) wird jetzt für beide Fälle aufgerufen. `node --check` bestanden. |
| AC-9 | `alice-mail-attachment-backfill` erhält dieselbe Erweiterung | **PASS** | Identische Änderung, unabhängig verifiziert (eigenes `OFFICE_EXTENSIONS`-Set, eigener Aufruf-Standort). `node --check` bestanden. |
| AC-10 | Bestehendes Verhalten für PDF/TXT/MD/andere unverändert | **PASS** | Diff-Review: PDF-Zweig nur invertiert (`if not _is_pdf` → `if _is_pdf`), Logik identisch. TXT/MD-Zweig in beiden Workflows nicht angefasst. `routeByExtension` (Image/Video/Audio) nicht angefasst. |

**10/10 Acceptance Criteria PASS.**

### Edge Cases Status

| # | Edge Case | Status | Nachweis |
|---|---|---|---|
| EC-1 | Passwortgeschützte/verschlüsselte Office-Datei | **PASS** | Nicht mit einer echten passwortgeschützten Datei nachgestellt (keine Office-Suite verfügbar), aber äquivalent durch korrupte-Bytes-Test abgedeckt: Parser wirft, Endpunkt fängt sauber ab → `extraction_failed`. Gleiches Codepfad-Verhalten wie für jede andere Parser-Exception. |
| EC-2 | Sehr großes XLSX, Truncation statt unbegrenzter Verarbeitung | **TEILWEISE — siehe BUG-1** | Die Response wird korrekt auf 50.000 Zeichen gekappt, **aber erst nachdem die gesamte Datei bereits vollständig extrahiert wurde** — das Truncation-Limit schützt die Response-Größe, nicht die Verarbeitungszeit/den Speicherverbrauch während der Extraktion selbst. Siehe BUG-1. |
| EC-3 | Legacy `.doc`/`.xls` (nicht `.docx`/`.xlsx`) → `unsupported_format` | **PASS** | Eigener Test: `legacy.doc` mit `application/msword` → `status: "unsupported_format"`, kein Fehlrouting in `_extract_docx_text`. |
| EC-4 | Leere Office-Datei, kein Fehler | **ABWEICHUNG von Spec, kein Bug** | Eine wirklich leere Datei (0 Byte) ist kein gültiges ZIP-Archiv → alle vier Extraktoren werfen `BadZipFile` → `status: "extraction_failed"` statt `status: "ok"` mit leerem Text, wie die Spec es beschreibt. Sachlich unproblematisch: der Aufrufer behandelt `extraction_failed` identisch zu `ok` mit leerem Text (beide führen zum Dateiname+Kontext-Fallback) — funktional keine Abweichung im Endergebnis, nur im Statusfeld. Kein Bug, da kein AC verletzt wird und kein Verhaltensunterschied für den Nutzer entsteht. |
| EC-5 | Timeout/hängende Extraktion | **PASS, aber siehe BUG-1** | Kein Subprocess, daher kein separater Timeout-Mechanismus nötig (Spec-Annahme korrekt) — aber die zugrunde liegende Sorge (pathologisch große Datei blockiert den Worker) ist real und wird in BUG-1 quantifiziert. |
| EC-6 | XLSX mit Formeln ohne gecachten Wert | **PASS** | Eigener Test: Zelle mit `=1+1` ohne je in Excel geöffnet worden zu sein → leere Zelle in der Ausgabe, keine Formel als Text, kein Crash. Exakt wie in der Spec beschrieben. |

**5/6 PASS, 1 mit dokumentiertem Bug (EC-2, siehe BUG-1), 1 harmlose Abweichung (EC-4, kein Bug).**

### Security Audit Results

**Docker/Backend-Feature:**
- [x] **XXE (XML External Entity) — gezielt getestet, nicht nur angenommen:** Eigene bösartige ODT-Datei mit `<!ENTITY xxe SYSTEM "file:///etc/hostname">` gegen `odf_load` getestet → `odfpy` wirft `EntitiesForbidden`, Angriff blockiert. `python-docx`/`lxml`: `etree.XMLParser()`-Default hat `resolve_entities=False` (lxml ≥3.x), eigenständig mit einer bösartigen Roh-XML-Payload gegen den nackten lxml-Parser verifiziert (`XMLSyntaxError: Entity 'xxe' not defined`). `openpyxl`: Quellcode-Prüfung bestätigt `safe_parser = XMLParser(resolve_entities=False)` plus `defusedxml`-Nutzung wenn verfügbar (`DEFUSEDXML=True` in dieser Installation). **Keine XXE-Schwachstelle in allen drei neuen Parsern.**
- [x] **Path Traversal / Dateisystem:** Keine neuen Dateipfad-Operationen — Extraktion arbeitet ausschließlich auf In-Memory-`bytes` (`io.BytesIO`), keine temporären Dateien auf Platte (anders als `dms-extractor-office`s LibreOffice-Subprocess-Ansatz).
- [x] **Secrets in Logs:** Neue `log.warning`-Aufrufe loggen nur Dateiname + Exception-Message, keine Payload-Inhalte, keine Credentials.
- [ ] **BUG-1: Unbegrenzter Speicher-/Zeitverbrauch bei hochkomprimierbaren Office-Dateien (Zip-Bomb-artig) — siehe unten.**

### Bugs Found

#### BUG-1: Truncation erfolgt erst nach vollständiger Extraktion — keine Schutzwirkung gegen Speicher-/Zeit-Erschöpfung durch präparierte Anhänge
- **Severity:** Medium
- **Root Cause:** `_extract_xlsx_text`/`_extract_docx_text`/`_extract_odt_text`/`_extract_ods_text` bauen den **gesamten** extrahierten Text im Speicher auf, bevor `fetch_attachment_text()` ihn auf `PLAINTEXT_MAX_CHARS` (50.000) kappt. Office-Formate (ZIP-Container mit XML) haben für stark repetitiven Inhalt sehr hohe Kompressionsraten — eine kleine Datei kann zu einem riesigen extrahierten Text expandieren, lange bevor die Kappung greift.
- **Steps to Reproduce:**
  1. Eine XLSX-Datei mit 2.000.000 identischen Zeilen erzeugen (z.B. `openpyxl`, 50 Zeichen pro Zeile) → Datei ist nur **10,5 MB** komprimiert, liegt weit unter dem bestehenden `ATTACHMENT_MAX_BYTES`-Vorfilter von 50 MB in den aufrufenden Workflows.
  2. Gegen `_extract_office_text(payload, ".xlsx")` ausführen.
  3. **Erwartet:** Verarbeitung bricht früh ab oder ist zumindest zeitlich/speichermäßig begrenzt, sobald das 50.000-Zeichen-Limit erreicht ist.
  4. **Tatsächlich:** Extraktion läuft **24 Sekunden**, produziert **~102 Millionen Zeichen** (≈97 MB) im Speicher, treibt den Python-Prozess auf **512 MB Peak-RSS** — erst danach greift die Kappung auf 50.000 Zeichen für die Response.
- **Auswirkung:** Der Vorfilter `ATTACHMENT_MAX_BYTES` (50 MB, komprimiert) in beiden aufrufenden Workflows bietet keinen wirksamen Schutz gegen diese Klasse von Datei, da die Kompression bei repetitivem Inhalt sehr hoch ist. Eine bewusst präparierte E-Mail (kein Admin-Login nötig — jede eingehende Mail an die überwachte Mailbox kann einen Anhang enthalten) könnte den `alice-mail-reader`-Container (`gunicorn --workers 2 --timeout 60`) für mehrere Sekunden bis potenziell über die 60s-Timeout-Grenze hinaus blockieren und mehrere hundert MB bis in den GB-Bereich Speicher binden — bei nur 2 Workern reichen wenige gleichzeitige Anfragen, um den Service für andere Aufrufer (inkl. `/fetch`, `/body`, `/test`) unresponsive zu machen.
- **Einordnung — kein neues Risiko-Muster, aber neue Größenordnung:** Der bereits deployte, QA-akzeptierte PDF-Pfad (`_extract_pdf_text`) hat exakt dasselbe strukturelle Muster (erst vollständig extrahieren, dann kappen) — dies ist also kein von PROJ-91 neu eingeführter Fehlerklassen-Typ. Es verschärft ihn aber real: Office-Container (ZIP+XML) erreichen für repetitiven Inhalt deutlich höhere Kompressionsraten als PDF-Text-Streams, wie der Test zeigt (10,5 MB → 97 MB Text, Faktor ~9), und die Erweiterung vervierfacht die Anzahl der betroffenen Dateiformate (4 neue zusätzlich zu PDF).
- **Priority:** Vor dem produktiven Rollout beheben empfohlen (z.B. Zeilen-/Zellen-Iteration mit frühem Abbruch bei Erreichen von `PLAINTEXT_MAX_CHARS`, analog zu `openpyxl`s bereits genutztem `read_only`-Streaming-Modus) — aber **kein Blocker für "Approved"**, da: (a) dieselbe Schwäche im bereits produktiven PDF-Pfad genauso besteht und dort als akzeptables Risiko bewertet wurde, (b) der Angriff nur einen DoS gegen einen internen, VPN-only-Service darstellt (kein Datenverlust, keine Kompromittierung), (c) die Behebung sauber als eigenständiger Folgefix auf denselben Erkenntnisstand für alle fünf Formate (PDF eingeschlossen) angewendet werden sollte statt isoliert nur für PROJ-91.

### Regression Check

- PDF-Extraktion (`_extract_pdf_text`, `_is_pdf`): Code unverändert, nur die aufrufende `if`-Struktur invertiert — Diff-Review bestätigt identisches Verhalten.
- `/attachment`, `/fetch`, `/body`, `/test`, `/encrypt`, `/health`: keine dieser Routen im Diff berührt.
- `routeByExtension` (Image/Video/Audio-Routing) in beiden Workflows: unverändert, kein Overlap mit dem neuen `OFFICE_EXTENSIONS`-Set (Bild/Video/Audio-Endungen sind disjunkt von `.docx/.xlsx/.odt/.ods`).
- `dms-extractor-office`: nicht im Diff enthalten (`git status` bestätigt), spec-konform unberührt.
- TXT/MD-Zweig: unverändert in beiden Workflows.

### Summary

- **Acceptance Criteria:** 10/10 passed
- **Edge Cases:** 5/6 passed, 1 mit dokumentiertem Bug (BUG-1)
- **Bugs Found:** 1 total (0 critical, 0 high, 1 medium, 0 low)
- **Security:** Pass — XXE gezielt getestet und widerlegt (nicht nur angenommen); ein Medium-DoS-Finding (BUG-1) dokumentiert
- **Production Ready:** YES (mit Empfehlung, BUG-1 zeitnah als Folgefix zu adressieren)
- **Recommendation:** **READY** — Deploy. Alle 10 Acceptance Criteria erfüllt, keine Regression im PDF-/TXT-/MD-Pfad. BUG-1 ist real und quantifiziert (nicht nur theoretisch), aber kein Blocker: gleiches Muster besteht bereits im produktiven, akzeptierten PDF-Pfad, betrifft nur einen internen VPN-only-Service und verursacht keinen Datenverlust — Empfehlung, ihn zeitnah für alle fünf Formate gemeinsam zu beheben statt den Rollout von PROJ-91 dafür zu blockieren.

## Deployment

Deployed am 2026-08-24. `alice-mail-reader` (Container-Rebuild mit `python-docx`/`openpyxl`/`odfpy`) sowie `alice-mail-attachment-processor` und `alice-mail-attachment-backfill` (n8n-Workflows) produktiv live.

**Empfehlung für Post-Deploy-Monitoring:** BUG-1 aus dem QA-Bericht (unbegrenzter Speicher-/Zeitverbrauch bei stark komprimierbaren Office-Anhängen vor der Truncation) im Blick behalten — kein Blocker, aber ein Kandidat für einen zeitnahen Folgefix über alle fünf Formate (inkl. PDF) hinweg.
