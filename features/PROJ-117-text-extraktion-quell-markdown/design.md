# Architektur: PROJ-117 Text-Extraktion → Quell-Markdown (#6)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-22

## A) Betroffene Bausteine
```
alice-text-extraction (neuer Container, Python/FastAPI, Port 8014, nur Docker-Netz, keine nginx-Route)
+-- Arbeitsschleife: holt fällige Arbeit der Stufe `extract` (nur kind = document) aus dem Register,
|   höchstens N Quellen gleichzeitig (Standard 2)
+-- Lebenszeichen an das Register, solange eine Quelle in Arbeit ist (lange Scans, AK-33)
+-- Formate:
|   +-- PDF: Textebene je Seite; Seiten ohne brauchbare Textebene → OCR (Tesseract) einzeln, je Seite mit Zeitgrenze
|   +-- Textdokumente (doc/docx/docm/dotx/odt/ott/rtf): LibreOffice → HTML → Markdown (Überschriften, Absätze, Tabellen)
|   +-- Tabellen (xls/xlsx/xlsm/ods/ots): LibreOffice → xlsx → je Blatt eine Markdown-Tabelle (gespeicherte Werte)
|   +-- Präsentationen (ppt/pptx/pptm/pps/ppsx/odp/otp): LibreOffice → pptx → je Folie Text, Tabellen, Notizen
|   +-- csv, txt, md: Kodierung (UTF-8, sonst Windows-1252/ISO-8859-1) und Trennzeichen erkennen
+-- Spracherkennung ohne LLM (statistisch), OCR-Bereinigung aus dms-extractor-ocr übernommen
+-- liest die NAS-Freigaben nur (nas-volumes.yml wie die DMS-Container)
+-- schreibt ausschließlich über die Schnittstelle von alice-source-registry
+-- GET /health (healthy / warning / unhealthy mit Grund), GET /status (laufende Arbeit)

alice-source-registry (PROJ-115, kleine Erweiterungen der Schnittstelle)
+-- Abschluss „endgültig fehlgeschlagen“: fail mit Kennzeichen permanent → sofort failed_permanent
+-- Lebenszeichen (heartbeat) für eine übernommene Stufe: verschiebt den „hängend“-Zeitpunkt
+-- Übernahme (claim) optional nur für bestimmte Arten (kinds)
+-- Freigeben (release) optional mit Wartezeit: die Quelle wird erst danach wieder vergeben

alice-file-detection (PROJ-116, Änderung)
+-- Standard-Endungsliste `document` um alle Office-Formate erweitert (AK-14)

PostgreSQL, Redis, Weaviate, MQTT, nginx, Frontend, n8n: keine Änderung
dms-extractor-*: keine Änderung (laufen für das alte System weiter)
```

Ein neuer Dienst statt Erweiterung der alten Extraktoren: Die alten Container hängen an MQTT/Redis des alten Systems und dürfen sich nicht ändern (Spec). Ein Container für alle Formate, weil die Stufe genau einen Abschluss je Quelle meldet und PDF (Textebene + OCR) nicht mehr auf zwei Container verteilt sein darf.

## B) Datenmodell
- **Keine neuen Tabellen.** Zustand, Versuche, Fehler und Backoff liegen im Register (PROJ-115). Der Dienst selbst hält nichts dauerhaft; nach einem Neustart fängt das Register hängende Übernahmen ab.
- **Quell-Markdown** (über das Register geschrieben):
  - Inhaltsteil: Text des Originals ohne Kürzung. PDF mit mehr als einer Seite: je nicht leerer Seite `## Seite <n>`; Präsentation: je Folie mit Inhalt `## Folie <n>`, darunter `### Notizen`; Tabellenkalkulation: je Blatt `## Blatt <Name>` mit Markdown-Tabelle. Überschriften aus Textdokumenten rücken eine Ebene nach unten (Ebene 1 → `##`), weil `#` der Titel ist.
  - Frontmatter `extraction` (Inhaltseigenschaft, kein Zustand): `method` (`text`/`ocr`/`mixed`), `ocr_pages` (Liste der OCR-Seiten, sonst leer), `empty` (`true`, wenn kein Text herauskam).
  - Frontmatter `language`: ISO-Code oder leer.
  - Leeres Ergebnis: Hinweis „Kein Text extrahiert“ und Link(s) aufs Original.
- **Register:** Ursachen endgültiger Fehler stehen verständlich in `last_error` der Stufe (z. B. „PDF ist passwortgeschützt“, „Datei zu groß (250 MB, Grenze 200 MB)“), ohne NAS-Pfade.

## C) Abläufe
1. **Arbeit holen:** Ist ein Platz frei, fragt der Dienst das Register nach fälliger `extract`-Arbeit nur für `document` (so werden Bilder, Mails, Audio, Video nie übernommen, AK-3). Die exklusive Übernahme macht das Register (AK-4). Nichts zu tun → kurze Pause (Standard 10 s).
2. **Original finden:** Fundorte der Quelle aus dem Register. Der erste vorhandene lesbare Fundort wird verarbeitet (EC-8).
   - Kein Fundort lesbar, und die Freigabe (erstes Verzeichnis unter `/mnt/nas`) fehlt oder ist leer → NAS nicht erreichbar: Arbeit ohne Fehlversuch zurückgeben, Warnung im Log, neue Arbeit wird pausiert, bis die Freigabe wieder da ist (AK-24).
   - Freigabe da, nur die Datei fehlt → Arbeit ohne Fehlversuch zurückgeben, mit Wartezeit (Standard 1 h), damit die Quelle nicht dauernd neu vergeben wird; die Datei-Erkennung entscheidet über das Löschen (AK-25, EC-9).
3. **Prüfen:** Größe über der Grenze → sofort endgültig „Datei zu groß“ (AK-26). Endung nicht unterstützt → endgültig.
4. **Extrahieren** in einem Arbeits-Thread bzw. in Kindprozessen (LibreOffice, Tesseract) mit Zeitgrenzen:
   - PDF: Textebene je Seite. „Brauchbar“ heißt: genug Buchstaben/Ziffern (Mindestanzahl) und ein Mindestanteil lesbarer Zeichen (EC-1). Sonst wird genau diese Seite gerendert (300 dpi) und per OCR gelesen, je Seite mit eigener Zeitgrenze. Seiten mit Text gehen nie an die OCR (EC-2).
   - LibreOffice läuft mit eigenem, frischem Profil, Makros deaktiviert, ohne Netzwerk-Abrufe; Zeitgrenze je Datei.
5. **Lebenszeichen:** Solange eine Quelle in Arbeit ist, meldet der Dienst regelmäßig (Standard 60 s) ein Lebenszeichen ans Register. So wird ein 200-Seiten-Scan nicht nach 30 min als „hängend“ zurückgesetzt (AK-33). Stirbt der Dienst, bleiben die Lebenszeichen aus und PROJ-115 setzt die Stufe nach der Zeitüberschreitung zurück (AK-34).
6. **Schreiben:** Erst nach vollständiger Extraktion: ein Schreibaufruf ans Register mit `extraction`, `language` und dem Inhaltsteil. Das Register schützt `manual`-Felder und `content`, committet vorher Hand-Änderungen, erzeugt genau einen Commit „extract: <id> <title>“ (bzw. Sammel-Commit im Massenlauf), macht bei gleichem Inhalt keinen Commit und setzt bei geändertem Inhalt `database`/`rag`/`wiki` zurück (AK-2, AK-28–31). Danach `done`.
7. **Fehler:**
   - Endgültig (Passwort, kaputt, nicht unterstützt, zu groß) → `fail` mit Kennzeichen permanent → sofort `failed_permanent`, Markdown unverändert (AK-21, AK-22).
   - Vorübergehend (Zeitüberschreitung, Absturz von LibreOffice/Tesseract, Speicher, Unerwartetes) → normales `fail` mit Backoff aus PROJ-115 (AK-23).
   - Register-Repo nicht erreichbar (503) oder Markdown gesperrt (409) → Arbeit ohne Fehlversuch zurückgeben.
8. **Register nicht erreichbar** → keine neue Arbeit, Warnung im Log; nach einer Schonfrist (Standard 60 s) meldet `/health` „unhealthy“ mit Grund; kommt das Register zurück, geht es ohne Eingriff weiter (AK-35).
9. **Massenlauf:** Ist der Schalter für Sammel-Commits gesetzt, schreibt der Dienst mit dem Kennzeichen „Sammel-Commit“ des Registers (PROJ-115-Mechanismus, AK-2). Wie PROJ-120 den Massenlauf auslöst, entscheidet PROJ-120; bis dahin ist es ein Schalter in der `.env`.

## D) Technische Entscheidungen
- **PyMuPDF für PDF**, weil es in einem Paket Textebene je Seite, Erkennung von Passwortschutz/Beschädigung und das Rendern einzelner Seiten für die OCR liefert (das alte System brauchte dafür Node + poppler + zwei Container).
- **Abgeschnittene PDFs** (kein Dateiende-Marker am Ende) gelten als kaputt, auch wenn die Bibliothek Reste reparieren könnte: sonst würde ein halbes Dokument still als vollständig gespeichert (AK-22).
- **Tesseract (deu+eng) als OCR**, wie `dms-extractor-ocr`; Bereinigung aus dem alten OCR-Extraktor übernommen und um das Zusammenfügen von Trennungen am Zeilenende ergänzt (AK-8).
- **LibreOffice als einziger Umwandler** für alle MS-/OpenDocument-Formate in drei einheitliche Zwischenformate (HTML, xlsx, pptx), die dann mit kleinen Lesern (eigener HTML-Leser, openpyxl, python-pptx) in Markdown übersetzt werden. Ein Weg je Gruppe statt je Endung: alte Binärformate, Vorlagen, Makro- und Show-Varianten verhalten sich gleich (AK-9–12). Makros: frisches Profil mit höchster Makro-Sicherheit, Umwandlung führt keine Dokument-Makros aus.
- **Tabellenblätter:** gespeicherte Werte, ausgeblendete Blätter/Zeilen werden mitgenommen (EC-4, EC-5), leere Randzeilen/-spalten werden weggelassen, Zellen vollständig (EC-3).
- **Spracherkennung mit `langdetect`** (statistisch, ohne LLM, fester Zufallswert für reproduzierbare Ergebnisse). Unter der Mindestlänge oder bei Wahrscheinlichkeit unter 0,90 bleibt `language` leer (AK-18, EC-12).
- **Kodierung von txt/md/csv:** UTF-8 (mit/ohne BOM), sonst Windows-1252 (Obermenge von ISO-8859-1 für druckbare Zeichen, u. a. €), notfalls ISO-8859-1. Enthält die Datei Null-Bytes, ist es keine Textdatei → endgültiger Fehler statt Binärmüll im Markdown (EC-6).
- **Schnittstellen-Erweiterungen in PROJ-115 statt Umgehungen:** endgültiger Abschluss (Spec), Lebenszeichen (AK-33; ohne würde jede Übernahme nach 30 min pauschal zurückgesetzt), Übernahme nach Art (sonst müsste der Dienst Bilder/Mails übernehmen und sofort wieder zurückgeben, Endlosschleife), Freigeben mit Wartezeit (sonst würde eine fehlende Datei sekündlich neu vergeben). Alle sind optional; bestehende Aufrufer und Regeln bleiben unverändert. Das Lebenszeichen setzt den Übernahmezeitpunkt neu (kein Schema-Umbau nötig).
- **Kein Postgres, kein Redis, kein MQTT im Dienst:** Arbeit kommt nur aus dem Register (EC-11, AK-37).
- **Healthcheck mit Schonfrist:** Kurze Register-Neustarts (Deploy) machen den Dienst nicht sofort „unhealthy“. Im Container-Test läuft kein Register, dort ist die Schonfrist hoch gesetzt und der Rauchtest prüft den gemeldeten Grund.

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `httpx`, `pymupdf`, `openpyxl`, `python-pptx`, `langdetect`; im Container `libreoffice-writer`, `libreoffice-calc`, `libreoffice-impress`, `tesseract-ocr` (+ `deu`, `eng`).
- Neue Umgebungsvariablen (Platzhalter in `.env.example` von `alice-text-extraction`): `REGISTRY_URL`, `EXTRACT_CONCURRENCY` (2), `EXTRACT_POLL_SECONDS` (10), `EXTRACT_HEARTBEAT_SECONDS` (60), `EXTRACT_OCR_PAGE_TIMEOUT_SECONDS` (120), `EXTRACT_FILE_TIMEOUT_SECONDS` (600), `EXTRACT_MAX_FILE_MB` (200), `EXTRACT_LANGUAGE_MIN_CHARS` (100), `EXTRACT_TEXT_MIN_CHARS` (10), `EXTRACT_TEXT_MIN_QUALITY` (0.6), `EXTRACT_OCR_LANGUAGES` (deu+eng), `EXTRACT_OCR_DPI` (300), `EXTRACT_NAS_ROOT` (/mnt/nas), `EXTRACT_MISSING_RETRY_SECONDS` (3600), `EXTRACT_NAS_RETRY_SECONDS` (60), `EXTRACT_REGISTRY_GRACE_SECONDS` (60), `EXTRACT_BATCH` (false).
- `alice-file-detection`: geänderter Standardwert von `DETECT_EXT_DOCUMENT` (nur Kommentar in `.env.example`).

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1, AK-2, AK-4 | Worker gegen Register-Attrappe (übernehmen → schreiben → done); Register-Tests: Übernahme exklusiv; Commit „extract: …“/Sammel-Commit über die bestehenden Register-Tests + E2E | Unit + Integration (Test-DB, Temp-Repo) + E2E |
| AK-3 | Register-Test: Übernahme mit Art-Filter liefert keine Bilder/Mails; Worker fragt nur `document` an | Integration + Unit |
| AK-5–8, AK-16, EC-1, EC-2 | Erzeugte Test-PDFs (Textseiten, Bildseiten, leere Seiten, > 50.000 Zeichen); OCR-Attrappe zählt Aufrufe; Bereinigung | Unit |
| AK-9–12 | Leser-Tests mit erzeugten pptx/xlsx/HTML; echte Umwandlung aller Endungen mit LibreOffice im Container-Rauchtest | Unit + Container |
| AK-13, AK-15, EC-6 | csv/txt/md in UTF-8 und ISO-8859-1, Binärdatei mit Endung .txt | Unit |
| AK-14 | Datei-Erkennung registriert `vortrag.pptx` mit Standardliste | Unit/Integration (alice-file-detection) |
| AK-17–20 | Frontmatter-Felder, Spracherkennung de/en/kurz, leeres Ergebnis | Unit + E2E |
| AK-21–27 | Passwort-PDF, abgeschnittenes PDF, kaputtes DOCX, Zeitüberschreitung (Attrappe), NAS weg/Datei weg (Temp-Ordner), Größe; Register-Tests für permanent/Retry | Unit + Integration |
| AK-28–31 | `manual`-Schutz, Hand-Änderung, Zurücksetzen, gleicher Inhalt → kein Commit: Register-Logik (PROJ-115-Tests) + E2E mit echtem Register | Integration + E2E |
| AK-32 | 10 fällige Quellen, Parallelität 2: Attrappe misst gleichzeitige Übernahmen | Unit |
| AK-33 | Lebenszeichen hält die Stufe `running` trotz kurzer „hängend“-Zeit (Register-Test); Worker sendet Lebenszeichen während langer OCR | Integration + Unit |
| AK-34 | Abbruch vor dem Schreiben: kein Schreibaufruf; Register setzt zurück (PROJ-115) | Unit |
| AK-35 | Register-Attrappe nicht erreichbar → Pause, Health „unhealthy“ mit Grund, danach weiter | Unit |
| AK-36 | keine nginx-Route (Konfiguration geprüft), Port nur im Docker-Netz | Prüfung |
| AK-37 | kein MQTT/Redis im Code und in den Abhängigkeiten, alte Container unverändert (git diff) | Prüfung |
| AK-38 | Live auf dem NAS | nur nach Deploy durch den Menschen |

Nicht ohne Produktivsysteme testbar: echtes NAS (Ausfall der Freigabe) → Attrappe: Temp-Ordner, der entfernt/geleert wird; echte Scans → erzeugte Bild-PDFs; Laufzeitverhalten neben Chat/Sprache → nur AK-38.

Deploy-Schritte für den Menschen:
1. `alice-source-registry` neu bauen (Schnittstellen-Erweiterung, keine Migration).
2. `.env` für `alice-text-extraction` aus `.env.example` anlegen; Staging mit `scripts/stage.sh alice-text-extraction <PR>` (Achtung: arbeitet echte Quellen ab).
3. Nach dem Merge: `sync-compose.sh`, `make rebuild s=automations/alice-source-registry`, `make rebuild s=automations/alice-file-detection`, `make up s=automations/alice-text-extraction`.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Ein neuer Dienst für alle Formate | Alte Extraktoren erweitern / vier neue Container | Alte Container bleiben unberührt (Spec); PDF mit OCR je Seite braucht Textebene und OCR im selben Ablauf |
| PyMuPDF | pdfplumber/pypdf + pdf2image/poppler | Ein Paket für Text, Passwort-/Fehlererkennung und Rendern einzelner Seiten |
| LibreOffice → HTML/xlsx/pptx → kleine Leser | je Format eine eigene Bibliothek (python-docx, xlrd, odfpy …) | Ein Umwandler deckt alle alten, neuen, Vorlagen- und Makro-Varianten gleich ab |
| `langdetect` | lingua, fastText-Modell | Klein, ohne Modelldatei, reicht für de/en; unsichere Fälle bleiben leer |
| Lebenszeichen ans Register | längere „hängend“-Zeit im Register | Lange Scans gelingen, abgestürzte Worker werden trotzdem schnell erkannt |
| Übernahme mit Art-Filter | übernehmen und sofort zurückgeben | Keine Endlosschleife, Bilder/Mails werden nicht angefasst |
| Freigeben mit Wartezeit bei fehlender Datei | sofort freigeben | Keine Dauerschleife bis zum nächsten Nachtlauf der Datei-Erkennung |
| Sammel-Commits per Schalter | automatische Erkennung eines Massenlaufs | PROJ-120 bestimmt den Auslöser; Mechanismus ist schon da |
