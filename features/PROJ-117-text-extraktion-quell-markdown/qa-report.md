# QA-Bericht: PROJ-117 Text-Extraktion → Quell-Markdown (#6)

**Spec:** [spec.md](spec.md) · **Design:** [design.md](design.md)
**Getestet am:** 2026-11-22, Nachtrag 2026-11-23 (Office-Gruppe aus dem Inhalt) · **Branch:** `factory/6`

## Ergebnis
**Produktionsreif:** Ja
- Akzeptanzkriterien: 37 von 37 in der Factory prüfbaren bestanden; AK-38 (Live-Test) nach Deploy durch den Menschen
- Bugs: Critical 0 · High 0 · Medium 0 · Low 2 (Hinweise, siehe unten)

Geprüft auf drei Ebenen:
1. **Automatisiert** (`scripts/test-services.sh`): Format-Leser und Arbeitsschleife mit Attrappen (OCR, LibreOffice, Register), End-to-End-Tests mit dem echten Register-Code gegen die Wegwerf-Datenbank und ein temporäres Git-Repo (`tests/test_e2e.py`), Register-Tests für die neuen Schnittstellen-Funktionen.
2. **Container-Rauchtest** (`scripts/test-containers.sh`): echtes LibreOffice 25.2 und Tesseract 5 im gebauten Image, als Nicht-root-Konto 1000:100.
3. **Manuell, Docker-E2E:** Register-Container + Extraktions-Container + Wegwerf-Postgres, Originale in einem Testordner als „NAS“ (nur lesend eingebunden), Aufrufe mit curl.

## Akzeptanzkriterien
| AK | Ergebnis | Nachweis |
|---|---|---|
| AK-1 Übernehmen → schreiben → `done` | ✅ | `test_e2e.py::test_extract_writes_and_commits`; Docker-E2E (Text-PDF und 30-Seiten-Scan `done`) |
| AK-2 Ein Commit „extract: <id> <title>“ bzw. Sammel-Commit | ✅ | `test_e2e.py::test_extract_writes_and_commits` (genau ein Commit), `::test_batch_commit` („rebuild: extract 3 sources“); Docker-E2E: `git log` im Register-Container |
| AK-3 Keine Bilder/Mails/Audio/Video | ✅ | Übernahme mit Art-Filter: `alice-source-registry/tests/test_extract_interface.py::test_claim_by_kind`; Bild-Markdown unverändert in `test_e2e.py::test_extract_writes_and_commits` |
| AK-4 Zwei Instanzen, einmal verarbeitet | ✅ | `test_e2e.py::test_two_workers_process_once`; exklusive Übernahme aus PROJ-115 |
| AK-5 PDF mit `## Seite <n>`, `text` | ✅ | `test_formats.py::test_pdf_pages_text` |
| AK-6 > 50.000 Zeichen ohne Kürzung | ✅ | `test_formats.py::test_pdf_long_text_not_cut` (9.000 Wörter, alle enthalten) |
| AK-7 3 Text- + 2 Scan-Seiten, OCR nur 2×, `mixed` | ✅ | `test_formats.py::test_pdf_mixed_ocr_only_scanned_pages` (Attrappe zählt Aufrufe); echtes Tesseract im Container-Rauchtest |
| AK-8 Voll gescannt, `ocr`, bereinigt | ✅ | `test_formats.py::test_pdf_fully_scanned_cleaned`; Docker-E2E: 30- und 200-Seiten-Scan `extraction.method: ocr`, Text lesbar |
| AK-9 DOCX/ODT/DOC mit Überschrift, Absätzen, Tabelle | ✅ | `test_formats.py::test_docx_via_html`; Container: doc, docx, odt mit echtem LibreOffice |
| AK-10 XLSX/ODS/XLS, je Blatt `## Blatt <Name>` | ✅ | `test_formats.py::test_sheets`; Container: xlsx, xls, ods (zwei Blätter, Formelwert) |
| AK-11 PPTX/PPT/ODP mit Tabelle und Notizen | ✅ | `test_formats.py::test_slides`; Container: pptx, ppt, odp (3 Folien, Tabelle, `### Notizen`) |
| AK-12 rtf, docm, dotx, ott, xlsm, ots, pptm, ppsx, pps, otp; keine Makros | ✅ | Container-Rauchtest: alle zehn Endungen nach ihrer Gruppe gegliedert; ODT mit an „Dokument laden“ gebundenem Basic-Makro: Inhalt gelesen, Makro nicht ausgeführt; frisches Profil mit höchster Makro-Sicherheit (`test_libreoffice_args_and_profile`). Siehe Hinweis L-2 |
| AK-13 csv mit `;` und ISO-8859-1 | ✅ | `test_formats.py::test_csv_semicolon_latin1` |
| AK-14 `vortrag.pptx` wird registriert | ✅ | `alice-file-detection/tests/test_detection.py::test_office_extensions_registered` (alle 14 neuen Endungen, `extract` `pending`), `test_unit.py::test_defaults` |
| AK-15 txt/md UTF-8 bzw. ISO-8859-1 | ✅ | `test_formats.py::test_txt_md_encodings` (6 Varianten) |
| AK-16 Leere Seiten ohne Abschnitt, Nummern bleiben | ✅ | `test_formats.py::test_pdf_empty_pages_keep_numbers` |
| AK-17 Kein Verarbeitungszustand im Frontmatter | ✅ | `test_worker.py::test_flow_done` (nur `extraction`, `language`), `test_e2e.py::test_extract_writes_and_commits` |
| AK-18 `language` de/en, kurz → leer | ✅ | `test_formats.py::test_language`, `test_worker.py::test_flow_done`; Docker-E2E: Scan `language: de` |
| AK-19 `language` in `manual` bleibt | ✅ | `test_e2e.py::test_manual_protection_and_hand_edit` |
| AK-20 Leeres Ergebnis → `done`, `empty: true`, Hinweis + Link | ✅ | `test_worker.py::test_empty_result`, `test_e2e.py::test_empty_and_special_characters` (Folgestufe `classify` bleibt `pending`, nicht blockiert), `test_formats.py::test_pdf_ocr_without_result`, `::test_empty_txt` |
| AK-21 Passwort-PDF → sofort `failed_permanent` | ✅ | `test_e2e.py::test_permanent_and_retry` (Ursache „PDF ist passwortgeschützt“, 1 Versuch); Office: `test_office_precheck` |
| AK-22 Kaputte Datei → sofort `failed_permanent`, Markdown unverändert | ✅ | `test_formats.py::test_pdf_truncated`, `::test_pdf_garbage`, `::test_office_precheck`; Container: halbiertes DOCX; Markdown unverändert in `test_e2e.py::test_permanent_and_retry` |
| AK-23 Absturz/Zeitüberschreitung → `failed` mit Backoff | ✅ | `test_formats.py::test_libreoffice_timeout_transient`, `::test_libreoffice_crash_transient`, `::test_pdf_ocr_timeout_is_transient`, `test_worker.py::test_transient_error`; Backoff-Folge unverändert aus PROJ-115 (`test_registry.py::test_fail_backoff_and_permanent`) |
| AK-24 NAS weg → `release` ohne Fehlversuch, Warnung, läuft danach weiter | ✅ | `test_worker.py::test_nas_unavailable` (leerer Einhängepunkt) — nicht live geprüft (kein echtes NAS) |
| AK-25 Datei fehlt → zurück ohne Fehlversuch | ✅ | `test_worker.py::test_missing_file` (Freigabe mit Wartezeit 1 h), Register: `test_extract_interface.py::test_release_with_delay` |
| AK-26 Zu groß → `failed_permanent` „Datei zu groß“ + Grenze | ✅ | `test_formats.py::test_size_limit`; Docker-E2E zufällig live: 1,2-GB-Scan → „Datei zu groß (1245 MB, Grenze 200 MB)“, sofort `failed_permanent` |
| AK-27 „Erneut versuchen“ | ✅ | `test_e2e.py::test_permanent_and_retry`; Docker-E2E: `POST …/retry` nach AK-26 → neu extrahiert, `done` |
| AK-28 `content` in `manual` bleibt, `extraction` wird aktualisiert | ✅ | `test_e2e.py::test_manual_content_extraction_updated` (Inhalt bleibt, `extraction` wechselt auf `ocr`), `::test_manual_protection_and_hand_edit` |
| AK-29 Uncommittete Hand-Änderung zuerst committet | ✅ | `test_e2e.py::test_manual_protection_and_hand_edit` (Commit „Alice Hand-Korrektur“) |
| AK-30 Geändertes Original → neuer Inhalt, `database`/`rag`/`wiki` `pending`, Historie | ✅ | `test_e2e.py::test_changed_text_resets_and_same_text_no_commit` |
| AK-31 Gleicher Inhalt → kein Commit, keine Zurücksetzung | ✅ | `test_e2e.py::test_changed_text_resets_and_same_text_no_commit` |
| AK-32 Höchstens 2 gleichzeitig | ✅ | `test_worker.py::test_concurrency_limit` (10 Quellen, nie mehr als 2 `running`) |
| AK-33 200-Seiten-Scan bleibt `running` bis zum Abschluss | ✅ | Docker-E2E: echter 200-Seiten-Scan, „hängend“-Grenze des Registers auf 20 s gesetzt, Dauer ~90 s, `started_at` per Lebenszeichen fortgeschrieben, kein Zurücksetzen, `done` mit 200 `## Seite`-Abschnitten; `test_extract_interface.py::test_heartbeat_keeps_stage_running`, `test_worker.py::test_heartbeat_during_long_extraction` |
| AK-34 Abbruch → nichts halb geschrieben | ✅ | `test_worker.py::test_stop_writes_nothing` (kein Schreib-/Done-Aufruf, Stufe bleibt für den Register-Timeout stehen); geschrieben wird erst nach vollständiger Extraktion in einem Aufruf |
| AK-35 Register weg → Pause, unhealthy mit Grund, danach weiter | ✅ | `test_worker.py::test_registry_unavailable`, `::test_http_health_unhealthy_without_registry`; Docker-E2E: Register gestoppt → nach 60 s `503 unhealthy` „Extraktion pausiert: Register nicht erreichbar: ConnectError“, Register gestartet → `healthy`, Log „reachable again“ |
| AK-36 Keine nginx-Route | ✅ | `test_worker.py::test_no_nginx_route`; Compose ohne `ports:` |
| AK-37 Alte `dms-extractor-*` unberührt | ✅ | `git diff origin/dev` enthält keine Datei unter `dms-extractor-*`; `test_worker.py::test_no_old_system_channels` (kein MQTT/Redis im Code und in den Abhängigkeiten) |
| AK-38 Live-Test nach Deploy | ⏳ | nur nach Deploy durch den Menschen |

## Edge Cases
- ✅ EC-1: Müll-Textebene (Ersatz-/Privatzeichen) gilt als unbrauchbar → OCR (`test_text_layer_quality`)
- ✅ EC-2: Text + Bild auf einer Seite → Textebene, keine OCR (`test_pdf_mixed_ocr_only_scanned_pages`, Seite 5)
- ✅ EC-3: Breite Tabellen/lange Zellen vollständig (`test_sheets`: 3.000 Zeichen in einer Zelle, `test_md_table_escaping`)
- ✅ EC-4: Formeln → gespeicherter Wert (Container: `=SUM` → 350)
- ✅ EC-5: Ausgeblendetes Blatt wird mitgenommen (`test_sheets`, Container)
- ✅ EC-6: PDF mit Endung `.txt` → „keine Textdatei“, kein Binärmüll (`test_binary_with_txt_extension`); Nicht-PDF mit `.pdf` → Fehler
- ✅ EC-7: `---`, Frontmatter-Trenner und Backticks im Inhalt → Frontmatter bleibt gültig (`test_e2e.py::test_empty_and_special_characters`)
- ✅ EC-8: Zweiter Fundort genügt (`test_second_location_used`)
- ✅ EC-9: Datei zwischen Übernahme und Lesen gelöscht → zurück ohne Fehlversuch (`test_deleted_while_reading`)
- ✅ EC-10: Hand-Korrektur vor Extraktion → zuerst committet (`test_manual_protection_and_hand_edit`)
- ✅ EC-11: Redis spielt keine Rolle: der Dienst nutzt Redis nicht, die Übernahme nach Art kommt direkt aus dem Register
- ✅ EC-12: Sehr kurzer Text → `language` leer (`test_language`)

## Bugs
- **L-1 (Low):** Seiten in nichtlateinischer Schrift (z. B. Kyrillisch, Griechisch) mit sauberer Textebene gelten nach der Qualitätsregel als „unbrauchbar“ und gehen an die OCR (deu+eng). Für den Haushalt (deutsch/englisch) ohne Bedeutung; Schwelle über `EXTRACT_TEXT_MIN_QUALITY` einstellbar.
- **L-2 (Low, Testgrenze):** Die Gegenprobe für den Makro-Test (gleiches Dokument mit niedriger Makro-Sicherheit führt das Makro aus) ließ sich nicht herstellen: LibreOffice führt beim Umwandeln im Hintergrund auch ohne Sperre keine Lade-Makros aus. Der Test zeigt also, dass nichts ausgeführt wird, beweist aber nicht allein, dass die Profil-Sperre greift. Die Sperre (höchste Makro-Sicherheit, Makros deaktiviert, frisches Profil je Umwandlung) ist trotzdem gesetzt und geprüft.

- **B-1 aus Abnahme Runde 1 (High, behoben):** Jede Office-Umwandlung hinterließ Zombie-Prozesse (je DOCX 1× gpg, 1× gpgsm, 3× gpgconf), nach einer Zeitüberschreitung zusätzlich `soffice.bin`. Fix: `tini` als PID 1. Gegenprobe im gebauten Image ohne tini (Entrypoint `uvicorn`): Nach dem Selbsttest gab es 30× gpg, 30× gpgsm, 90× gpgconf und 1× soffice.bin als Zombies. Mit tini waren es 0 (Prüfung `tests/no_zombies.py` im Container-Rauchtest).
- **B-2 aus Abnahme Runde 1 (High, schon in PROJ-115, behoben):** Das Register hinterließ git-Zombies aus der abgekoppelten Hintergrundwartung. Fix: `tini` als PID 1, git mit `gc.autoDetach=false` und `maintenance.autoDetach=false`. Der Container-Rauchtest des Registers prüft auf Zombies.
- **Staging-Befund vom 2026-11-23 (High, behoben):** Eine Tabelle mit der Endung `.odt` endete in `failed_permanent`, weil die Gruppe nur aus der Endung kam (Writer-Filter für ein Calc-Dokument). Fix: Die Gruppe wird jetzt aus dem Inhalt bestimmt (ODF-`mimetype`, OOXML-Hauptteil, OLE-Hauptstrom). Unit-Tests: `test_content_group_markers`, `test_group_from_content_wins` (ods→`.odt`, xlsx→`.docx`, xls→`.doc`, pptx→`.xlsx`, Word→`.ppt`), `test_group_matching_extension_unchanged`, `test_precheck_unchanged_for_wrong_family`, im Worker `test_content_group_logged_with_source_id`. Im Container-Selbsttest mit echtem LibreOffice wurden echte, von LibreOffice erzeugte Dateien umbenannt: ODS als `.odt`, XLSX als `.docx` und XLS als `.doc` ergeben je `## Blatt Einnahmen` und `## Blatt Ausgaben` mit dem Formelwert. PPTX als `.xlsx`, PPT als `.doc` und ODP als `.ods` ergeben 3 Folien. DOC als `.xls` ergibt Text mit Tabelle. Alle 21 Varianten mit passender Endung sind weiter grün.

## Sicherheit
- Keine Endnutzer-Schnittstelle, keine nginx-Route, nur `/health` und `/status` (keine Inhalte, keine Pfade). Keine Zugangsdaten nötig.
- Originale werden nur gelesen; LibreOffice bekommt einen neutralen Dateinamen (`input.<endung>`) per Verweis, NAS-Pfade erscheinen nicht in Fehlermeldungen des Registers (`test_permanent_error`).
- Unvertrauenswürdige Dokumente: Makros deaktiviert, eigenes Profil je Umwandlung, Zeitgrenzen für LibreOffice und je OCR-Seite, Größenobergrenze. Kindprozesse laufen in eigener Prozessgruppe und werden bei Zeitüberschreitung vollständig beendet.
- Markdown-Tabellen maskieren `|` und Zeilenumbrüche; das Register rendert das Frontmatter per YAML, Inhalte können es nicht zerstören (EC-7).

## Nicht live geprüft
- **NAS-Ausfall (AK-24)** und **fehlende Einzeldatei (AK-25):** mit Testordnern nachgebildet. Staging-Prüfung: siehe PR „Deploy-Schritte“.
- **Echte Dokumente vom NAS, Laufzeit neben Chat/Sprache (AK-38):** nur nach Deploy.
- **OCR-Qualität echter Scans:** im Test erzeugte Bild-PDFs; Live-Test mit einem echten Scan.

## Automatisierte Tests
- `scripts/test-services.sh alice-text-extraction`: 73 bestanden (inkl. 8 End-to-End-Tests mit echtem Register-Code)
- `scripts/test-services.sh alice-source-registry`: 83 bestanden (davon 6 neu für die Schnittstellen-Erweiterung)
- `scripts/test-services.sh alice-file-detection`: 66 bestanden (davon 1 neu für AK-14)
- `scripts/test-containers.sh alice-text-extraction alice-source-registry alice-file-detection`: bestanden (Rauchtest der Extraktion mit 21 Office-Varianten, 7 umbenannten Dateien mit abweichender Endung, Makro-Dokument, kaputtem DOCX, erzwungener Zeitüberschreitung und OCR; beide Dienste: PID 1 ist tini, keine Zombies)
