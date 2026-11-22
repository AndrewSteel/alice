# PROJ-117: Text-Extraktion → Quell-Markdown

**Erstellt:** 2026-11-22
**Phase:** 4.1

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Stufe `extract`, Arbeit übernehmen/abschließen, Quell-Markdown schreiben, `manual`-Schutz, Retry/Backoff
- Benötigt: PROJ-116 (Datei-Erkennung) — legt Quellen der Art `document` mit Stufe `extract` auf `pending` an und setzt sie bei in-place geänderten Originalen zurück
- Ändert: PROJ-116 — die Standard-Endungsliste für `document` wird um alle Office-Formate aus „Was verarbeitet wird“ erweitert (`docm`, `dotx`, `ott`, `rtf`, `xlsm`, `ots`, `csv`, `pptx`, `pptm`, `ppt`, `ppsx`, `pps`, `odp`, `otp`); Dateien mit diesen Endungen, die die Datei-Erkennung bisher nur gezählt hat, werden beim nächsten Nachtlauf registriert
- Ändert: PROJ-115 — die Schnittstelle bekommt einen Abschluss „endgültig fehlgeschlagen" (Stufe sofort `failed_permanent`, ohne die 5 Versuche abzuwarten); alle übrigen Regeln (Backoff, Freigeben ohne Fehlversuch) bleiben
- Grundlage für: PROJ-118 (Klassifizierung + Feldextraktion), PROJ-119, PROJ-120 (Neuaufbau), PROJ-122 (ETL-Status-Ansicht), PROJ-124 (Mail-Anhänge als Quelldokumente), PROJ-127 (RAG-Index)

## Überblick
PROJ-117 füllt den Inhaltsteil der Quell-Markdown von Quellen der Art `document` mit dem Text des Originals. Die Stufe `extract` nimmt fällige Arbeit aus dem Register, liest das Original vom NAS, wandelt es in Markdown um und schreibt es über die Schnittstelle von PROJ-115 in die Quell-Markdown. Sie verarbeitet alle gängigen MS-Office- und OpenDocument-Formate, also auch Präsentationen und `rtf`, die das alte System nicht verarbeitet hat. Sie ersetzt fachlich die Extraktor-Container `dms-extractor-pdf`, `-ocr`, `-office` und `-txt` im neuen ETL; diese laufen unverändert für das alte System weiter, bis PROJ-142 sie abschaltet.

Der Inhalt ist **Text mit Seitenmarken, ohne Kürzung**: je PDF-Seite, Folie bzw. Tabellenblatt ein Abschnitt. Seitenmarken ermöglichen Quellenangaben auf Seitenebene und sind natürliche Schnittstellen für das Chunking im RAG (PROJ-127). Eine Rekonstruktion von Überschriften und Tabellen aus PDF-Layouts findet nicht statt (Fehlrekonstruktion, etwa verrutschte Spalten in Kontoauszügen, wäre schlimmer als reiner Text).

Das Feature hat keine Oberfläche. Getestet wird mit temporären Dateien als „NAS“, Wegwerf-Datenbank, PROJ-115 mit temporärem Git-Repo und einem gemockten OCR/Extraktions-Backend, wo nötig.

## User Stories
- Als Haushaltsmitglied möchte ich den vollständigen Text jedes Dokuments in dessen Quell-Markdown lesen und korrigieren können, damit Alice daraus richtige Antworten ableitet.
- Als Haushaltsmitglied möchte ich, dass auch gescannte Dokumente durchsuchbar werden, damit ich sie nicht von Hand abtippen muss.
- Als Haushaltsmitglied möchte ich Quellenangaben mit Seitenzahl erhalten können, damit ich die Stelle im Original schnell finde.
- Als Admin möchte ich bei Dokumenten, die nicht extrahiert werden können (Passwortschutz, kaputte Datei), sofort eine klare Ursache im Register sehen, damit ich nicht erst nach Stunden von Retries erfahre, dass nichts geht.
- Als Admin möchte ich, dass die Extraktion den Server und das LLM nicht überlastet, damit Chat und Sprache flüssig bleiben.

## Fachliches Modell

### Was verarbeitet wird
| Original | Behandlung |
|---|---|
| `pdf` | Text je Seite aus der Textebene; hat eine Seite keine brauchbare Textebene, wird genau diese Seite per OCR gelesen |
| `docx`, `docm`, `doc`, `dotx`, `odt`, `ott`, `rtf` | Text, Überschriften und Tabellen, soweit die Umwandlung sie liefert |
| `xlsx`, `xlsm`, `xls`, `ods`, `ots` | je Tabellenblatt ein Abschnitt, Zellen als Markdown-Tabelle |
| `csv` | ein Abschnitt, Zellen als Markdown-Tabelle; Trennzeichen und Zeichenkodierung werden erkannt |
| `pptx`, `pptm`, `ppt`, `ppsx`, `pps`, `odp`, `otp` | je Folie ein Abschnitt mit dem Text aller Textfelder und Tabellen; Sprechernotizen der Folie werden darunter als „Notizen“ mitgenommen |
| `txt`, `md` | Inhalt unverändert; Zeichenkodierung wird erkannt (UTF-8, sonst ISO-8859-1) |

- Andere Arten (`image`, `email`, `audio`, `video`) sind nicht Teil dieser Stufe. Für sie gilt `extract` wie in PROJ-115/PROJ-125/PROJ-123 festgelegt (`skipped` bzw. eigene Stufe).
- Verarbeitet werden nur Quellen mit Art `document`; die Endung entscheidet über die Behandlung.
- Makros in `docm`/`xlsm`/`pptm` werden nie ausgeführt; gelesen wird nur der Inhalt.
- Apple iWork (`pages`, `numbers`, `key`) wird nicht verarbeitet (nur teilweise lesbar).

### Aufbau des Inhaltsteils
- Nach der Überschrift `# <title>` folgt je PDF-Seite ein Abschnitt `## Seite <n>`, bei Präsentationen je Folie `## Folie <n>`, bei Tabellenkalkulation je Blatt `## Blatt <Name>`. Einseitige Dokumente und `txt`/`md` bekommen keine Seitenmarken.
- Leere Seiten bzw. Folien ohne Text und ohne Notizen werden nicht als eigene Abschnitte geschrieben, die Nummern der übrigen bleiben unverändert (Seite 4 bleibt „Seite 4“).
- **Keine Kürzung:** der Text wird vollständig übernommen. Die frühere Begrenzung auf 50.000 Zeichen entfällt.
- Der Inhaltsteil wird nur geändert, wenn `content` nicht in `manual` steht (Schutz durch PROJ-115).

### OCR je Seite
- Eine PDF-Seite gilt als „ohne brauchbare Textebene“, wenn ihre Textebene leer ist oder nur aus Steuerzeichen/Müll besteht (Schwelle konfigurierbar). Nur diese Seiten gehen an die OCR; Seiten mit Text werden nie per OCR gelesen.
- OCR-Text wird bereinigt (Müllzeichen, kaputte Zeilenumbrüche) wie im bisherigen OCR-Extraktor.
- Im Frontmatter wird die Herkunft vermerkt: `extraction` mit Verfahren je Dokument (`text`, `ocr`, `mixed`) und der Liste der OCR-Seiten, damit man OCR-Qualität einschätzen kann. Das Feld liegt im Frontmatter (kein Verarbeitungszustand), weil es eine Eigenschaft des Inhalts ist.

### Sprache
- Beim Extrahieren wird `language` aus dem Text erkannt (ISO-Code, z. B. `de`, `en`) ohne LLM. Bei zu wenig oder unsicherem Text bleibt das Feld leer.
- Steht `language` in `manual`, wird es nicht überschrieben.

### Leeres Ergebnis
- Kommt technisch ohne Fehler kein verwertbarer Text heraus (leere Datei, nur leere Seiten, OCR ohne Text), steht die Stufe auf `done`. Das Frontmatter vermerkt `extraction.empty: true`, der Inhaltsteil enthält einen Hinweis „Kein Text extrahiert“ mit Link aufs Original. Die Folgestufen laufen weiter (Klassifizierung mit dem Auffangtyp).

### Fehlerarten
- **Endgültig (sofort `failed_permanent`, klare Ursache im Register):** Passwortschutz/Verschlüsselung, strukturell kaputte Datei (nicht lesbar/öffnebar), nicht unterstützte Variante des Formats.
- **Vorübergehend (normaler Backoff aus PROJ-115, nach 5 Fehlversuchen `failed_permanent`):** Zeitüberschreitung, Absturz des Umwandlungsprogramms (z. B. LibreOffice), Speichermangel, unerwarteter Fehler.
- **NAS nicht erreichbar:** Original nicht lesbar, weil die Freigabe fehlt → Arbeit ohne Fehlversuch zurückgeben (`release`), Pause bis zur Rückkehr. Fehlt dagegen nur die einzelne Datei, obwohl die Freigabe erreichbar ist, wird die Arbeit ohne Fehlversuch zurückgegeben und der Fundort der Datei-Erkennung (PROJ-116) überlassen; die Quelle wird dadurch nicht als Fehler markiert.
- Die Fehlermeldung enthält Ursache in verständlicher Form (z. B. „PDF ist passwortgeschützt“), keine Pfade vom NAS im Klartext über das hinaus, was das Register ohnehin kennt.

### Last und Grenzen
- **Begrenzte Parallelität:** höchstens N Quellen gleichzeitig (konfigurierbar, Standard 2); OCR-lastige Dokumente zählen wie alle anderen. Die Extraktion nutzt keinen LLM-Slot und beeinflusst `alice-llm-gateway` nicht.
- **Zeitüberschreitung:** je Seite (OCR) bzw. je Datei (sonstige Umwandlung) konfigurierbar. Langes gescanntes Dokument (z. B. 300 Seiten) scheitert nicht pauschal an einer Gesamtzeit, sondern wird seitenweise mit Fortschritt abgearbeitet.
- **Größe:** sehr große Originale (konfigurierbare Obergrenze, Standard 200 MB) werden nicht verarbeitet → endgültiger Fehler mit klarer Ursache.
- Nach einem Absturz mitten in der Verarbeitung ist nichts halb geschrieben: Quell-Markdown und Commit entstehen erst nach vollständiger Extraktion; hängende `running`-Stufen fängt PROJ-115 ab.

### Neuaufbau und Änderungen
- Wird das Original verändert (PROJ-116 setzt `extract` zurück), extrahiert die Stufe neu; `content`, `language` und weitere Felder in `manual` bleiben geschützt.
- Beim Neuaufbau (PROJ-120) läuft die Stufe als Massenlauf mit Sammel-Commits (Mechanismus aus PROJ-115).
- Ändert sich der Inhalt, gehen `classify` (soweit konfiguriert) sowie `database`, `rag`, `wiki` wie in PROJ-115 auf `pending`.

## Außerhalb des Umfangs
- Erkennen von Dateien, Hash/Dedup, Verschieben/Umbenennen/Löschen (PROJ-116)
- Klassifizierung, Dokumenttyp, Felder, deutsche Zusammenfassung, inhaltlicher Titel (PROJ-118)
- Rekonstruktion von Überschriften/Listen/Tabellen aus PDF-Layouts (bewusst zurückgestellt; Neuextraktion ist jederzeit über den Neuaufbau möglich)
- Bilder als eigenständige Quellen und ihre Beschreibung (PROJ-125); Audio/Video-Inhalte; E-Mail-Inhalte (PROJ-123)
- Chunking und Kürzung für LLM/Weaviate (PROJ-118, PROJ-127)
- Apple iWork (`pages`, `numbers`, `key`), HTML, E-Books und weitere Nicht-Office-Formate (eigenes Feature, wenn Bedarf)
- Bilder, Diagramme und eingebettete Objekte in Office-Dateien (z. B. Text in Grafiken auf Folien): kein OCR
- Abschaltung oder Änderung der alten `dms-extractor-*`-Container (PROJ-142); sie laufen unverändert weiter
- Übernahme alter Extraktionsergebnisse aus Redis/Weaviate
- Oberfläche für Fehler und „erneut versuchen“ (PROJ-122)

## Akzeptanzkriterien

### Ablauf
- [ ] AK-1: Angenommen eine Quelle `kind: document` mit Stufe `extract` auf `pending`, wenn der Dienst läuft, dann übernimmt er die Arbeit (Stufe `running`), schreibt den extrahierten Inhalt in die Quell-Markdown und setzt `extract` auf `done`.
- [ ] AK-2: Angenommen eine Stufe wurde übernommen und die Extraktion ist erfolgreich, wenn die Quell-Markdown geschrieben wird, dann gibt es genau einen Commit des Pipeline-Autors „extract: <id> <title>“ (Normalbetrieb) bzw. einen Sammel-Commit bei einem Massenlauf.
- [ ] AK-3: Angenommen eine Quelle mit Art `image`, `email`, `audio` oder `video`, wenn der Dienst läuft, dann übernimmt er sie nicht und verändert ihre Quell-Markdown nicht.
- [ ] AK-4: Angenommen zwei gleichzeitig laufende Instanzen des Dienstes, wenn dieselbe Quelle fällig ist, dann wird sie nur einmal verarbeitet (Register-Übernahme aus PROJ-115).

### Formate und Inhalt
- [ ] AK-5: Angenommen ein mehrseitiges PDF mit Textebene, wenn es extrahiert wird, dann enthält der Inhaltsteil je Seite einen Abschnitt `## Seite <n>` mit dem vollständigen Text dieser Seite, in Seitenreihenfolge, und `extraction` im Frontmatter lautet `text`.
- [ ] AK-6: Angenommen ein PDF mit mehr als 50.000 Zeichen Text, wenn es extrahiert wird, dann ist der gesamte Text enthalten, ohne Kürzung und ohne Hinweis auf eine Kürzung.
- [ ] AK-7: Angenommen ein PDF, das aus 3 Textseiten und 2 gescannten Seiten (ohne Textebene) besteht, wenn es extrahiert wird, dann enthalten alle 5 Seiten Text, nur die 2 gescannten Seiten wurden per OCR gelesen (Test-Mock zählt die Aufrufe), `extraction` lautet `mixed`, und die OCR-Seiten sind im Frontmatter aufgeführt.
- [ ] AK-8: Angenommen ein vollständig gescanntes PDF, wenn es extrahiert wird, dann stammt der Text aller Seiten aus der OCR, `extraction` lautet `ocr`, und der OCR-Text ist bereinigt (keine Steuerzeichen, keine zerrissenen Wörter durch Umbrüche in Testdaten).
- [ ] AK-9: Angenommen ein DOCX/ODT-Dokument mit Überschrift, Absätzen und Tabelle, wenn es extrahiert wird, dann enthält der Inhaltsteil Überschrift, Absätze und die Tabelle als Markdown-Tabelle, und `.doc` wird mit demselben Ergebnis verarbeitet.
- [ ] AK-10: Angenommen eine XLSX/ODS-Datei mit zwei Tabellenblättern, wenn sie extrahiert wird, dann gibt es je Blatt einen Abschnitt `## Blatt <Name>` mit den Zellen als Markdown-Tabelle; `.xls` wird ebenso verarbeitet.
- [ ] AK-11: Angenommen eine PPTX-, eine PPT- und eine ODP-Präsentation mit je drei Folien, davon eine mit Tabelle und eine mit Sprechernotizen, wenn sie extrahiert werden, dann enthält der Inhaltsteil je Folie einen Abschnitt `## Folie <n>` mit dem Text aller Textfelder, die Tabelle als Markdown-Tabelle und die Notizen unter der jeweiligen Folie.
- [ ] AK-12: Angenommen je eine Testdatei in `rtf`, `docm`, `dotx`, `ott`, `xlsm`, `ots`, `pptm`, `ppsx`, `pps` und `otp`, wenn sie extrahiert werden, dann ist jeweils der Text vollständig im Inhaltsteil, gegliedert nach der Regel ihrer Gruppe (Text, Blätter, Folien), und enthaltene Makros wurden nicht ausgeführt.
- [ ] AK-13: Angenommen eine `csv`-Datei mit Semikolon als Trennzeichen und ISO-8859-1-Kodierung, wenn sie extrahiert wird, dann stehen alle Zeilen als Markdown-Tabelle mit korrekten Umlauten im Inhaltsteil.
- [ ] AK-14: Angenommen eine Datei `vortrag.pptx` liegt in einem überwachten Ordner, wenn die Datei-Erkennung (PROJ-116) mit der Standard-Endungsliste läuft, dann wird sie als Quelle `kind: document` registriert und `extract` steht auf `pending`; dasselbe gilt für alle in „Was verarbeitet wird“ genannten Endungen.
- [ ] AK-15: Angenommen eine `txt`- oder `md`-Datei in UTF-8 bzw. ISO-8859-1 mit Umlauten, wenn sie extrahiert wird, dann stehen die Umlaute korrekt im Inhaltsteil, ohne Seitenmarken, und der Text ist vollständig.
- [ ] AK-16: Angenommen ein PDF mit leeren Seiten zwischen Textseiten, wenn es extrahiert wird, dann gibt es für leere Seiten keinen Abschnitt, und die Seitennummern der übrigen Abschnitte entsprechen den Seiten im Original.
- [ ] AK-17: Angenommen eine Quell-Markdown nach der Extraktion, wenn man das Frontmatter liest, dann enthält es keinen Verarbeitungszustand, keine Fehlermeldung und keinen Retry-Zähler (nur die Inhaltseigenschaft `extraction`).

### Sprache und leeres Ergebnis
- [ ] AK-18: Angenommen ein deutscher und ein englischer Beispieltext (je mindestens ein Absatz), wenn sie extrahiert werden, dann steht `language` auf `de` bzw. `en`; bei einem Text mit weniger als einer konfigurierbaren Mindestlänge oder unsicherer Erkennung bleibt `language` leer.
- [ ] AK-19: Angenommen `language` steht in `manual`, wenn die Quelle erneut extrahiert wird, dann bleibt der von Hand gesetzte Wert unverändert.
- [ ] AK-20: Angenommen ein Dokument ohne verwertbaren Text (leere Datei bzw. PDF nur aus leeren Seiten, OCR ohne Ergebnis), wenn es extrahiert wird, dann steht `extract` auf `done`, `extraction.empty` ist `true`, der Inhaltsteil enthält den Hinweis „Kein Text extrahiert“ mit Link aufs Original, und die Folgestufen sind nicht blockiert.

### Fehler und Retry
- [ ] AK-21: Angenommen ein passwortgeschütztes PDF, wenn die Extraktion läuft, dann steht `extract` sofort auf `failed_permanent` mit der Ursache „passwortgeschützt“ (verständlich formuliert), ohne Wiederholungsversuche.
- [ ] AK-22: Angenommen eine strukturell kaputte Datei (z. B. abgeschnittenes PDF, beschädigtes DOCX), wenn die Extraktion läuft, dann steht `extract` sofort auf `failed_permanent` mit verständlicher Ursache, und die Quell-Markdown behält ihren bisherigen Inhalt.
- [ ] AK-23: Angenommen das Umwandlungsprogramm bricht ab oder die Zeitüberschreitung greift, wenn die Extraktion läuft, dann steht `extract` auf `failed` mit Fehlermeldung und Backoff nach PROJ-115 (1 min, 5 min, 30 min, 2 h, 12 h); nach dem 5. Fehlversuch `failed_permanent`.
- [ ] AK-24: Angenommen die NAS-Freigabe ist nicht erreichbar, wenn eine Quelle übernommen wird, dann wird die Arbeit ohne Fehlversuch zurückgegeben (`release`), der Versuchszähler bleibt unverändert, im Log steht eine Warnung, und nach Rückkehr der Freigabe läuft die Verarbeitung ohne Eingriff weiter.
- [ ] AK-25: Angenommen eine Quelle, deren Original-Datei am Fundort fehlt, obwohl die Freigabe erreichbar ist, wenn die Extraktion läuft, dann wird die Arbeit ohne Fehlversuch zurückgegeben und die Quelle nicht als Fehler markiert.
- [ ] AK-26: Angenommen ein Original über der konfigurierten Größenobergrenze, wenn die Extraktion läuft, dann steht `extract` sofort auf `failed_permanent` mit der Ursache „Datei zu groß“ und der Grenze.
- [ ] AK-27: Angenommen eine Stufe auf `failed_permanent`, wenn über die Schnittstelle „erneut versuchen“ ausgelöst wird (PROJ-115), dann wird sie erneut extrahiert.

### Handkorrekturen und Änderungen
- [ ] AK-28: Angenommen `content` steht in `manual`, wenn die Quelle erneut extrahiert wird, dann bleibt der Inhaltsteil unverändert, und nicht geschützte Felder (z. B. `extraction`) werden aktualisiert.
- [ ] AK-29: Angenommen eine Quelle mit uncommitteter Hand-Änderung an der Quell-Markdown, wenn `extract` schreibt, dann wird die Hand-Änderung zuerst als Hand-Korrektur committet (PROJ-115, AK-27), und der Inhalt geht nicht verloren.
- [ ] AK-30: Angenommen eine erfolgreich extrahierte Quelle mit `database`, `rag`, `wiki` auf `done`, wenn das Original in-place geändert und neu extrahiert wird (Stufen ab `extract` auf `pending` durch PROJ-116) und sich der Text ändert, dann bleibt die `id` gleich, der Inhaltsteil ist aktualisiert, `database`, `rag` und `wiki` stehen auf `pending`, und der alte Inhalt ist in der Git-Historie erhalten.
- [ ] AK-31: Angenommen die erneute Extraktion liefert exakt denselben Inhalt wie zuvor, wenn die Stufe schreibt, dann entsteht kein neuer Commit und `database`/`rag`/`wiki` werden nicht zurückgesetzt.

### Last und Betrieb
- [ ] AK-32: Angenommen 10 fällige Quellen und Parallelität 2, wenn der Dienst läuft, dann sind zu keinem Zeitpunkt mehr als 2 Quellen gleichzeitig `running` (durch den Dienst übernommen); die Grenze ist konfigurierbar.
- [ ] AK-33: Angenommen ein gescanntes PDF mit 200 Seiten, deren OCR je Seite unter der Zeitgrenze bleibt, wenn es extrahiert wird, dann gelingt die Extraktion, auch wenn die Gesamtdauer länger als die Zeitgrenze je Seite ist, und die Stufe bleibt `running` bis zum Abschluss, ohne vom „hängend“-Mechanismus zurückgesetzt zu werden.
- [ ] AK-34: Angenommen der Dienst wird während einer Extraktion beendet, wenn er neu startet, dann ist keine halbe Quell-Markdown und kein halber Commit im Repo, und die Stufe wird nach der Zeitüberschreitung aus PROJ-115 erneut übernommen.
- [ ] AK-35: Angenommen die Quellen-Register-Schnittstelle ist nicht erreichbar, wenn der Dienst Arbeit holen will, dann pausiert er mit Warnung im Log, der Healthcheck meldet „unhealthy“ mit Grund, und nach Rückkehr läuft er selbstständig weiter.
- [ ] AK-36: Angenommen der Dienst, wenn man ihn von außerhalb des Docker-Netzes (über nginx) aufrufen will, dann ist er nicht erreichbar; es gibt keine nginx-Route.
- [ ] AK-37: Angenommen das alte System, wenn der neue Dienst läuft, dann verarbeiten die bisherigen `dms-extractor-*`-Container weiter ihre MQTT-/Redis-Aufträge unverändert; der neue Dienst abonniert deren Topics nicht und schreibt nicht in deren Redis-Queues.
- [ ] AK-38 (Live-Test nach Deploy): Angenommen ein echtes gescanntes Dokument und ein echtes Text-PDF auf dem NAS, wenn die Stufe läuft, dann sind beide Quell-Markdowns vollständig und lesbar, das gescannte mit `extraction: ocr`, und die Chat/Sprach-Antwortzeit bleibt spürbar unverändert.

## Edge Cases
- EC-1: PDF mit Textebene, die offensichtlich Müll ist (falsches Encoding) → Seite gilt als „ohne brauchbare Textebene“ und geht an die OCR.
- EC-2: PDF mit Text und eingebettetem Scan auf derselben Seite → die Textebene gewinnt, die Seite wird nicht per OCR gelesen (kein Doppeln).
- EC-3: Sehr breite Tabellen im Tabellenblatt → als Markdown-Tabelle geschrieben, keine Kürzung; sehr lange Zellen bleiben vollständig.
- EC-4: Tabellenblatt mit Formeln → es zählen die gespeicherten Werte, nicht die Formeltexte.
- EC-5: Ausgeblendete Tabellenblätter/Zeilen → werden mit extrahiert, damit nichts still fehlt.
- EC-6: Dokument mit Dateiendung, die nicht zum Inhalt passt (z. B. PDF mit Endung `.txt`) → Fehler „nicht lesbar“ bzw. Erkennung nach Inhalt, kein stilles Schreiben von Binärmüll in die Markdown.
- EC-7: Zeichen im Text, die YAML/Markdown stören würden (Backticks, `---`, Frontmatter-Trenner im Dokument) → Inhaltsteil bleibt gültig, Frontmatter wird nicht zerstört.
- EC-8: Zwei Fundorte derselben Quelle → verarbeitet wird einmal; es genügt, dass einer der Fundorte lesbar ist.
- EC-9: Original ist während der Extraktion nicht mehr vorhanden (zwischen Übernahme und Lesen gelöscht) → wie AK-25, Arbeit ohne Fehlversuch zurück.
- EC-10: Hand-Korrektur und Extraktion kurz nacheinander → Hand-Korrektur zuerst committet, Extraktion respektiert `manual` (PROJ-115).
- EC-11: Restart von Redis → keine Auswirkung auf die Extraktion, Arbeit kommt aus dem Register (PROJ-115).
- EC-12: Dokument sehr kurz (wenige Wörter) → `language` leer, kein Fehler.

## Technische Anforderungen
- Testbar ohne NAS und ohne GPU: temporäre Dateien als Originale, Wegwerf-Postgres/Redis, PROJ-115 mit temporärem Git-Repo; OCR und LibreOffice dürfen in Tests durch kleine Fakes/Testdateien ersetzt werden, solange die Logik (OCR je Seite, Fehlerarten, Zeitüberschreitung) geprüft wird.
- Neuer Dienst; die vorhandenen `dms-extractor-*`-Container bleiben unverändert und laufen für das alte System weiter (Wiederverwendung der Extraktionslogik, nicht der Container). Keine Änderung an deren MQTT-Topics und Redis-Schlüsseln.
- Parallelität, Zeitgrenzen (je Seite/je Datei), Größenobergrenze, Mindestlänge für die Spracherkennung und Schwelle für „brauchbare Textebene“ konfigurierbar; neue Variablen nur als Platzhalter in `.env.example`.
- Zugriff auf Originale wie bei den DMS-Containern über `nas-volumes.yml` (NAS-Konto, kein root, nur lesend); Schreiben der Quell-Markdowns ausschließlich über PROJ-115, nie direkt ins Repo.
- Kein LLM, keine GPU-Last durch diese Stufe außer der OCR, soweit sie GPU nutzt; kein Aufruf von `alice-llm-gateway`.
- Schnittstelle nur intern im Docker-Netz, keine nginx-Route.
- Keine neue Queue-/Event-Infrastruktur.
- Keine echten Pfade, Hostnamen oder personenbezogenen Daten im Code oder in Testdaten.

## Offene Fragen
- Keine

## Product Decisions
- Inhalt = Text mit Seitenmarken, keine Struktur-Rekonstruktion aus PDF-Layouts: Fehlrekonstruktion (verrutschte Spalten, z. B. Kontoauszüge) schadet LLM und Wiki mehr als sie hilft; Seitenmarken liefern Quellenangaben und sinnvolle Chunk-Grenzen für Weaviate; Struktur lässt sich später über einen Neuaufbau nachziehen (2026-11-22)
- 50.000-Zeichen-Kürzung entfällt: sie macht lange Dokumente still unvollständig; Kürzung/Chunking für LLM und Weaviate gehört in PROJ-118/PROJ-127 (2026-11-22)
- OCR automatisch je Seite statt je Dokument: gemischte PDFs werden vollständig, Text-Seiten bleiben ohne OCR-Fehler; Herkunft im Frontmatter (`extraction`) macht OCR-Qualität sichtbar (2026-11-22)
- Neuer Dienst, alte `dms-extractor-*` unberührt: das alte System läuft bis PROJ-142 produktiv weiter, keine Änderungen an Diensten, die es bedienen (2026-11-22)
- Unwiederbringliche Fehler (Passwortschutz, kaputte Datei, zu groß) sofort `failed_permanent`, vorübergehende durch den Backoff: klare Aussage statt ~15 h sinnloser Wiederholungen; Folge: neue Abschlussart in der Schnittstelle von PROJ-115 (2026-11-22)
- NAS-Ausfall und fehlende Einzeldatei zählen nicht als Fehlversuch, das Löschen entscheidet die Datei-Erkennung (PROJ-116) (2026-11-22)
- Leeres Ergebnis ist `done` mit Kennzeichnung statt Fehler: Titel und Metadaten bleiben nutzbar, nichts geht still verloren, kein Retry-Sturm (2026-11-22)
- `language` setzt PROJ-117 per Erkennung ohne LLM: schnell, kein LLM-Slot, vom Feld in PROJ-115 („leer bis zur Extraktion“) vorgesehen; inhaltliche Felder bleiben in PROJ-118 (2026-11-22)
- Alle per LibreOffice umsetzbaren MS-Office- und OpenDocument-Formate inkl. Präsentationen, Vorlagen-, Makro- und Show-Varianten, `rtf` und `csv`; Sprechernotizen werden mitgenommen; Apple iWork bleibt draußen, weil nur teilweise lesbar (2026-11-22)
- Erweiterung der Endungsliste von PROJ-116 in PROJ-117 statt per /refine: PROJ-116 ist bereits in Arbeit (2026-11-22)
- Begrenzte Parallelität (Standard 2, konfigurierbar) und Zeitgrenze je Seite statt je Dokument: lange Scans gelingen, Server und Chat bleiben bedienbar (2026-11-22)
