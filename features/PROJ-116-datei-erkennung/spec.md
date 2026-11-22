# PROJ-116: Datei-Erkennung

**Erstellt:** 2026-11-22
**Phase:** 4.1

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Quellen, Fundorte, `deleted`, Stufen, Quell-Markdown und Commits über dessen interne Schnittstelle
- Ändert: PROJ-115 — `deleted`-Quellen werden nicht mehr an Worker vergeben (AK-12), Repo zieht auf eine eigene NAS-Freigabe (siehe „Ablage der Quelle der Wahrheit“)
- Liest: `alice.dms_watched_folders` (überwachte NAS-Ordner, gepflegt in den Einstellungen)
- Grundlage für: PROJ-117 (Text-Extraktion), PROJ-120 (Neuaufbau), PROJ-122 (ETL-Status-Ansicht), PROJ-125 (Bilder), PROJ-126 (Vorschaubilder); PROJ-119/126/127/129 legen fest, wie ihre abgeleiteten Daten auf `deleted` reagieren

## Überblick
PROJ-116 findet die Originaldateien in den überwachten NAS-Ordnern und hält das Quellen-Register (PROJ-115) mit ihnen synchron: neue Dateien, zusätzliche Kopien, Verschiebungen, Umbenennungen, an Ort und Stelle geänderte und gelöschte Dateien. Es ersetzt fachlich die n8n-Workflows `alice-dms-scanner`, `-path-worker`, `-lifecycle` und `-reconcile`, die bis PROJ-142 parallel weiterlaufen.

Zwei Läufe:
- **Tagesscan** (häufig, z. B. alle 5 Minuten): findet nur neues Material über geänderte Ordner. Entfernt nie etwas.
- **Nachtlauf** (einmal, z. B. 2 Uhr): voller Abgleich aller Dateien; entfernt verschwundene Fundorte, behandelt an Ort und Stelle geänderte Originale, schreibt eine Zusammenfassung.

Das Feature hat keine Oberfläche. Getestet wird mit temporären Ordnern als „NAS“, Wegwerf-Datenbank und PROJ-115.

## User Stories
- Als Haushaltsmitglied möchte ich, dass eine neu abgelegte Datei innerhalb weniger Minuten von Alice erfasst wird, damit sie bald durchsuchbar ist.
- Als Haushaltsmitglied möchte ich Dateien auf dem NAS verschieben, umbenennen oder kopieren können, ohne dass Alice sie doppelt verarbeitet oder ihre Korrekturen verliert.
- Als Haushaltsmitglied möchte ich im NAS-Ordner der Quelle der Wahrheit auf einen Blick sehen, welche Quellen gelöscht sind, damit ich nicht an veralteten Dateien arbeite.
- Als Admin möchte ich, dass die Quelle der Wahrheit auf einer eigenen Freigabe liegt, die nur ich ändern kann, damit sie nicht versehentlich mit anderen Daten gelöscht wird.
- Als Admin möchte ich sicher sein, dass ein ausgefallenes NAS oder ein vergessener Mount keine Massenlöschung auslöst.
- Als Admin möchte ich jeden Morgen eine Zusammenfassung des Nachtlaufs haben (inkl. nicht bearbeiteter Dateiendungen mit Anzahl), damit ich entscheiden kann, ob weitere Endungen in die Bearbeitung müssen.

## Fachliches Modell

### Was erkannt wird
| Art (`kind`) | Endungen (Groß-/Kleinschreibung egal) |
|---|---|
| `document` | `pdf`, `txt`, `md`, `docx`, `doc`, `xlsx`, `xls`, `odt`, `ods` |
| `image` | `jpg`, `jpeg`, `png`, `webp`, `heic`, `tif`, `tiff` |
| `audio` | `mp3`, `m4a`, `wav`, `flac`, `ogg`, `aac` |
| `video` | `mp4`, `mov`, `mkv`, `avi`, `m4v`, `webm` |

- Immer übersprungen: Synology-Systemordner (`@eaDir`, `#recycle`), versteckte Dateien und Ordner (Name beginnt mit `.`), Office-Sperrdateien (`~$…`), temporäre Dateien (`*.tmp`, `*.part`, `*.crdownload`), `Thumbs.db`, `desktop.ini`, symbolische Links, leere Dateien (0 Byte).
- Endungs- und Übersprunglisten sind konfigurierbar.
- Andere Endungen werden nicht registriert, aber im Nachtlauf gezählt (siehe Zusammenfassung).
- Inhalt wird nicht verarbeitet: Bilder (PROJ-125), Audio/Video (laut PROJ-115 `skipped`), Dokumente (PROJ-117).

### Ablage der Quelle der Wahrheit (Änderung an PROJ-115)
- Das Repo der Quelle der Wahrheit liegt auf einer **eigenen NAS-Freigabe** (auf dem Server z. B. als `/mnt/nas/sot` eingebunden), nicht mehr unter der gemischt genutzten Freigabe für Mails und DMS-Daten.
- Nur der Register-Dienst aus PROJ-115 bindet diese Freigabe ein. Sie gehört nicht zu den gemeinsamen NAS-Freigaben der DMS-Container und der Erkennung und kann daher nie als Quelle erkannt werden.
- Zugriff über die NAS-Freigabe (setzt der Mensch auf dem NAS): Admin lesen und schreiben (Hand-Korrekturen, Löschen in `deleted/`), Haushalt nur lesen, Gast kein Zugriff. Die Hand-Korrektur-Story aus PROJ-115 gilt damit für den Admin.
- Das bestehende Repo (inkl. Git-Historie) wird beim Deploy auf die neue Freigabe umgezogen; danach zeigt die Konfiguration des Register-Dienstes dorthin.

### Überwachte Ordner
- Quelle: `alice.dms_watched_folders`. Gescannt werden nur aktive Ordner (`enabled`).
- **Deaktiviert:** nicht mehr gescannt; seine Fundorte bleiben unverändert („eingefroren“), nichts wird entfernt. Nach erneuter Aktivierung läuft alles normal weiter.
- **Aus der Liste gelöscht:** im nächsten Nachtlauf werden alle Fundorte unter diesem Pfad entfernt (Quellen ohne weiteren Fundort → `deleted`). Die 20-%-Grenze gilt dafür nicht (bewusste Admin-Aktion); die Zusammenfassung nennt Ordner und Anzahl.
- **Verschachtelte Ordner** (z. B. `/…/family` und `/…/family/Steuer`): jede Datei wird nur einmal erfasst und dem längsten passenden Ordner zugeordnet.
- Jeder Fundort kennt den überwachten Ordner, zu dem er gehört.

### Tagesscan (nur neues Material)
- Läuft rund um die Uhr in einem konfigurierbaren Intervall (Standard 5 Minuten).
- Erkennt Änderungen über die **Änderungszeit der Ordner** (ändert sich, wenn darin eine Datei hinzukommt, verschwindet oder umbenannt wird); nur geänderte Ordner werden neu gelistet. Der Zeitstempel der Datei allein reicht nicht, weil kopierte Dateien ihre alte Änderungszeit behalten.
- Gehasht wird nur eine Datei, deren Pfad noch nicht als Fundort bekannt ist (Hash `sha256` des Originals).
- **Stabilität:** eine neue Datei wird erst übernommen, wenn Größe und Änderungszeit über zwei aufeinanderfolgende Scans unverändert sind (Datei wird nicht mehr geschrieben).
- Unbekannter Hash → neue Quelle (Basis-Markdown über PROJ-115, Stufe `detect` erledigt). Bekannter Hash → zusätzlicher Fundort der bestehenden Quelle, keine erneute Verarbeitung.
- Entfernt **nie** Fundorte; eine verschobene Datei hat ihren neuen Fundort sofort, der alte verschwindet im Nachtlauf.

### Nachtlauf (voller Abgleich)
- Einmal täglich zu konfigurierbarer Zeit (Standard 2 Uhr), über alle Dateien aller aktiven Ordner; Größe und Änderungszeit werden mit dem Register verglichen.
- Neue Dateien wie im Tagesscan.
- **Verschwundene Fundorte** werden entfernt; eine Quelle ohne Fundort wird `deleted`.
- **An Ort und Stelle geänderte Originale** (gleicher Pfad, andere Größe oder Änderungszeit) werden neu gehasht und nach den Regeln unten behandelt. (Fällt eine solche Änderung schon tagsüber auf, weil sich dabei der Ordner geändert hat, darf sie auch dort behandelt werden.)
- **Erster Lauf / Bestand:** der erste Nachtlauf registriert den gesamten Bestand (Hash, Fundort, Basis-Markdown, kein LLM) mit Sammel-Commits von PROJ-115 und Fortschritt im Log. Reicht eine Nacht nicht, setzt der nächste Nachtlauf fort.
- Ein abgebrochener Nachtlauf (Neustart) wird nachgeholt, wenn der Dienst innerhalb von 6 Stunden (konfigurierbar) wieder läuft; sonst übernimmt der nächste Nachtlauf.

### Sicherungen gegen Massenlöschung
- Ein überwachter Ordner, der nicht lesbar oder plötzlich leer ist (Freigabe nicht gemountet, NAS aus), wird im Lauf übersprungen: keine Fundorte entfernt, nichts als neu gewertet; Healthcheck und Log warnen mit dem Ordner.
- Je Freigabe werden pro Nachtlauf höchstens 20 % (konfigurierbar) ihrer bekannten Fundorte entfernt. Wird die Grenze überschritten, wird für diese Freigabe nichts entfernt, und die Zusammenfassung meldet sie als blockiert. (Ausnahme: aus der Liste gelöschter Ordner.)

### An Ort und Stelle geänderte Originale
1. **Der Pfad war der einzige Fundort der Quelle:** dieselbe Quelle (`id` bleibt), Hash/Größe/Änderungszeit werden aktualisiert, alle Stufen ab `extract` wieder `pending`; Felder in `manual` bleiben geschützt; der alte Stand bleibt in der Git-Historie.
2. **Der alte Inhalt liegt noch an einem anderen Fundort:** die alte Quelle behält die übrigen Fundorte und verliert diesen Pfad; der neue Inhalt wird wie eine neu gefundene Datei behandelt (bekannter Hash → Fundort dort, sonst neue Quelle).
3. **Der neue Hash gehört bereits einer anderen Quelle (und der Pfad war der einzige Fundort):** der Pfad wandert zu dieser Quelle; die alte Quelle wird `deleted`.

### Gelöschte Quellen
- Wird eine Quelle `deleted`, verschiebt der Dienst ihre Quell-Markdown per Git (Umbenennung, Historie bleibt) nach `deleted/` mit gleicher Unterstruktur (z. B. `deleted/documents/2026/11/<id>-<slug>.md`) und setzt im Frontmatter `deleted: <Zeitpunkt>`.
- Eine `deleted`-Quelle wird von keiner Stufe mehr übernommen; offene Stufen bleiben, wie sie sind.
- Wie abgeleitete Daten (DB, RAG, Wiki, Vorschaubilder) auf `deleted` reagieren, legen die jeweiligen Features fest. PROJ-116 sorgt dafür, dass `deleted` mit Zeitpunkt im Register zuverlässig gesetzt und abfragbar ist.
- **Original taucht wieder auf** (gleicher Hash, beliebiger Pfad, auch nach langer Zeit): Quelle wieder aktiv mit derselben `id` und dem neuen Fundort; Markdown wandert aus `deleted/` an ihren regulären Platz zurück, `deleted` verschwindet aus dem Frontmatter; erledigte Stufen werden nicht wiederholt, `manual`-Felder bleiben.
- **Mensch löscht eine Markdown in `deleted/` von Hand:** wird akzeptiert, nicht wiederhergestellt, kein Fehler; der Registereintrag bleibt `deleted`. Taucht das Original später wieder auf, wird der letzte Stand aus der Git-Historie zurückgeholt; ist das nicht möglich, wird die Markdown neu angelegt und die Stufen laufen neu.
- Eine Markdown außerhalb von `deleted/` von Hand zu löschen bleibt ein Fehler mit Wiederherstellung (PROJ-115, EC-5).

### Erkennungsprobleme
- Eine Datei, die nicht gelesen werden kann (fehlende Rechte, Lesefehler, verschwindet beim Hashen), wird in einer Liste der Erkennungsprobleme geführt: Pfad, Ursache, erstes und letztes Auftreten.
- Jeder Scan versucht es erneut; gelingt es, verschwindet der Eintrag von selbst.

### Zusammenfassung des Nachtlaufs
- Am Ende jedes Nachtlaufs: ein Log-Eintrag **und** eine gespeicherte Zusammenfassung (für PROJ-122), mindestens mit:
  - Dauer, Anzahl gescannter Dateien und Ordner
  - neue Quellen, neue Fundorte, entfernte Fundorte, neu `deleted`, wieder aktivierte Quellen, an Ort und Stelle geänderte Originale
  - **nicht bearbeitete Dateiendungen mit Anzahl**, je überwachtem Ordner und gesamt
  - übersprungene (nicht erreichbare/leere) Ordner, durch die 20-%-Grenze blockierte Freigaben, entfernte gelöschte Ordner
  - Anzahl und Liste der offenen Erkennungsprobleme
- Ältere Zusammenfassungen bleiben mindestens 30 Tage abrufbar.

### Betrieb
- Tagesscan und Nachtlauf laufen nie gleichzeitig; ein Lauf, der länger als das Intervall dauert, wird nicht doppelt gestartet.
- Ist PROJ-115 (Register/Repo) nicht erreichbar, pausiert der Scan und versucht es im nächsten Intervall erneut; Änderungen werden dann gefunden, nichts geht verloren.
- Tagesscan und Nachtlauf lassen sich über eine interne Schnittstelle sofort auslösen (erster Start, Live-Test, Fehlersuche); Oberfläche dafür in PROJ-122.
- Parallelbetrieb: Das alte System (n8n-Workflows, Redis-Schlüssel, Weaviate) bleibt unverändert. PROJ-116 liest nur Originale und `dms_watched_folders` und schreibt nur über PROJ-115. Originale werden nie verändert, verschoben oder gelöscht.

## Außerhalb des Umfangs
- Text-Extraktion (PROJ-117), Klassifizierung und Nutzung des `suggested_type` der Ordner (PROJ-118)
- Reaktion abgeleiteter Daten auf `deleted` (PROJ-119, PROJ-126, PROJ-127, PROJ-129)
- Verarbeitung des Bestands über die Erkennung hinaus und Vollständigkeitsabgleich inkl. Neu-Hashen aller Dateien (PROJ-120)
- Oberfläche für Zusammenfassung, Erkennungsprobleme und manuelles Auslösen (PROJ-122)
- Mails und Mail-Anhänge (PROJ-123, PROJ-124)
- Bildbeschreibung, EXIF, Ort (PROJ-125); Inhaltsverarbeitung von Audio/Video
- Abschaltung der alten n8n-Workflows und Redis-Schlüssel (PROJ-142)
- Verwaltung der überwachten Ordner (bestehende Einstellungen; Ablösung der Ordner-API in PROJ-139)
- Dateisystem-Ereignisse (inotify o. Ä.) — auf NFS nicht verlässlich

## Akzeptanzkriterien

### Erkennen neuer Dateien
- [ ] AK-1: Angenommen ein aktiver überwachter Ordner, wenn darin eine neue Datei `rechnung.pdf` abgelegt wird und zwei Tagesscans sie unverändert sehen, dann ist sie im Register als Quelle `kind: document` mit `sha256`-Hash, Größe, Änderungszeit und Fundort registriert, ihre Basis-Markdown liegt im Repo, und die Stufe `detect` ist erledigt.
- [ ] AK-2: Angenommen eine Datei, deren Größe sich zwischen zwei Tagesscans ändert (wird noch geschrieben), wenn der zweite Scan läuft, dann ist sie noch nicht registriert; erst nach einem weiteren Scan ohne Änderung wird sie übernommen.
- [ ] AK-3: Angenommen eine Datei wird mit alter Änderungszeit in einen Ordner kopiert (Zeitstempel beibehalten), wenn der Tagesscan läuft, dann wird sie trotzdem als neu erkannt.
- [ ] AK-4: Angenommen ein überwachter Ordnerbaum mit 10.000 bekannten Dateien und keiner Änderung, wenn ein Tagesscan läuft, dann wird keine Datei gelesen oder gehasht und kein unveränderter Unterordner neu gelistet.
- [ ] AK-5: Angenommen Dateien mit den Endungen aus der Tabelle (gemischte Groß-/Kleinschreibung), wenn sie erkannt werden, dann erhalten sie die zugehörige Art `document`/`image`/`audio`/`video`.
- [ ] AK-6: Angenommen Dateien in `@eaDir` und `#recycle`, versteckte Dateien, `~$`-Sperrdateien, `*.tmp`/`*.part`/`*.crdownload`, `Thumbs.db`, `desktop.ini`, symbolische Links und 0-Byte-Dateien, wenn gescannt wird, dann wird keine davon registriert oder als nicht bearbeitete Endung gezählt.

### Kopien und Verschiebungen
- [ ] AK-7: Angenommen eine registrierte Quelle mit Hash H, wenn eine Kopie mit Hash H in einem anderen überwachten Ordner auftaucht, dann bekommt die bestehende Quelle einen zusätzlichen Fundort; es entsteht keine zweite Quelle, und keine Stufe wird erneut ausgeführt.
- [ ] AK-8: Angenommen eine registrierte Datei wird tagsüber verschoben oder umbenannt, wenn der Tagesscan läuft, dann hat die Quelle den neuen Fundort zusätzlich und der alte bleibt bis zum Nachtlauf; nach dem Nachtlauf hat sie nur noch den neuen Fundort. Markdown-Datei und `id` bleiben unverändert.
- [ ] AK-9: Angenommen der Tagesscan, wenn eine registrierte Datei gelöscht wurde, dann entfernt er keinen Fundort und setzt keine Quelle auf `deleted`.

### Löschen
- [ ] AK-10: Angenommen eine Quelle mit zwei Fundorten, wenn einer verschwindet und der Nachtlauf läuft, dann wird nur dieser Fundort entfernt und die Quelle bleibt aktiv.
- [ ] AK-11: Angenommen eine Quelle mit einem Fundort, wenn das Original gelöscht ist und der Nachtlauf läuft, dann ist die Quelle `deleted` mit Zeitpunkt, ihre Markdown liegt per Git-Umbenennung unter `deleted/<art>/<JJJJ>/<MM>/` (Historie über `git log --follow` erhalten), und das Frontmatter enthält `deleted` mit Zeitpunkt.
- [ ] AK-12: Angenommen eine `deleted`-Quelle mit offenen Stufen, wenn ein Worker Arbeit für eine dieser Stufen anfordert, dann bekommt er diese Quelle nicht.
- [ ] AK-13: Angenommen eine `deleted`-Quelle mit erledigten Stufen und `manual`-Feldern, wenn eine Datei mit ihrem Hash wieder in einem überwachten Ordner auftaucht, dann ist sie wieder aktiv mit derselben `id` und dem neuen Fundort, die Markdown liegt wieder am regulären Platz ohne `deleted`, erledigte Stufen bleiben erledigt, und die `manual`-Felder sind unverändert.
- [ ] AK-14: Angenommen eine Markdown unter `deleted/`, wenn ein Mensch sie von Hand löscht, dann wird sie nicht wiederhergestellt, es entsteht kein Fehler, und die Quelle bleibt `deleted` im Register.
- [ ] AK-15: Angenommen eine nach AK-14 von Hand gelöschte Markdown, wenn das Original wieder auftaucht, dann wird die Markdown mit ihrem letzten Stand aus der Git-Historie am regulären Platz wiederhergestellt und die Quelle ist aktiv.

### An Ort und Stelle geänderte Originale
- [ ] AK-16: Angenommen eine Quelle mit genau einem Fundort, erledigten Stufen und `title` in `manual`, wenn das Original am selben Pfad geändert wird und der Nachtlauf läuft, dann behält die Quelle ihre `id`, Hash/Größe/Änderungszeit sind aktualisiert, alle Stufen ab `extract` stehen auf `pending`, und `title` ist unverändert.
- [ ] AK-17: Angenommen eine Quelle mit Fundorten A und B (gleicher Inhalt), wenn das Original an A geändert wird und der Nachtlauf läuft, dann behält die alte Quelle nur B, und für A gibt es eine neue Quelle (bzw. A wird Fundort einer bestehenden Quelle mit dem neuen Hash).
- [ ] AK-18: Angenommen Quelle Q1 mit einzigem Fundort A und Quelle Q2 mit Hash H2, wenn das Original an A so geändert wird, dass es Hash H2 hat, und der Nachtlauf läuft, dann ist A Fundort von Q2 und Q1 ist `deleted` (Markdown unter `deleted/`).

### Ablage der Quelle der Wahrheit (Änderung an PROJ-115)
- Das Repo der Quelle der Wahrheit liegt auf einer **eigenen NAS-Freigabe** (auf dem Server z. B. als `/mnt/nas/sot` eingebunden), nicht mehr unter der gemischt genutzten Freigabe für Mails und DMS-Daten.
- Nur der Register-Dienst aus PROJ-115 bindet diese Freigabe ein. Sie gehört nicht zu den gemeinsamen NAS-Freigaben der DMS-Container und der Erkennung und kann daher nie als Quelle erkannt werden.
- Zugriff über die NAS-Freigabe (setzt der Mensch auf dem NAS): Admin lesen und schreiben (Hand-Korrekturen, Löschen in `deleted/`), Haushalt nur lesen, Gast kein Zugriff. Die Hand-Korrektur-Story aus PROJ-115 gilt damit für den Admin.
- Das bestehende Repo (inkl. Git-Historie) wird beim Deploy auf die neue Freigabe umgezogen; danach zeigt die Konfiguration des Register-Dienstes dorthin.

### Überwachte Ordner
- [ ] AK-19: Angenommen ein überwachter Ordner mit registrierten Dateien wird deaktiviert, wenn Tagesscans und Nachtlauf laufen, dann wird er nicht gescannt und seine Fundorte bleiben unverändert; nach erneuter Aktivierung werden Änderungen darin wieder erkannt.
- [ ] AK-20: Angenommen ein überwachter Ordner wird aus der Liste gelöscht, wenn der nächste Nachtlauf läuft, dann sind alle Fundorte unter seinem Pfad entfernt (Quellen ohne weiteren Fundort `deleted`), auch wenn das mehr als 20 % der Fundorte der Freigabe sind, und die Zusammenfassung nennt Ordner und Anzahl.
- [ ] AK-21: Angenommen zwei verschachtelte überwachte Ordner, wenn eine Datei im inneren liegt, dann hat sie genau einen Fundort, zugeordnet dem inneren Ordner.

### Sicherungen und Fehler
- [ ] AK-22: Angenommen ein überwachter Ordner mit registrierten Dateien ist nicht lesbar oder leer (Mount fehlt), wenn der Nachtlauf läuft, dann wird kein Fundort darunter entfernt, der Healthcheck meldet eine Warnung mit dem Ordner, und nach Rückkehr läuft alles ohne Eingriff weiter.
- [ ] AK-23: Angenommen in einer Freigabe fehlen 25 % der bekannten Fundorte, wenn der Nachtlauf läuft, dann wird für diese Freigabe kein Fundort entfernt und die Zusammenfassung meldet sie als blockiert; bei 15 % werden die fehlenden entfernt.
- [ ] AK-24: Angenommen eine Datei ohne Leserechte, wenn gescannt wird, dann steht sie in der Liste der Erkennungsprobleme mit Pfad, Ursache, erstem und letztem Auftreten; sobald sie lesbar ist, wird sie beim nächsten Scan registriert und der Eintrag verschwindet.
- [ ] AK-25: Angenommen PROJ-115 ist nicht erreichbar, wenn ein Scan läuft, dann pausiert er ohne Datenverlust, und nach Rückkehr werden die zwischenzeitlichen Änderungen beim nächsten Scan erkannt.
- [ ] AK-26: Angenommen ein laufender Nachtlauf, wenn ein Tagesscan fällig wird oder ein weiterer Lauf manuell ausgelöst wird, dann startet kein zweiter Lauf parallel.
- [ ] AK-27: Angenommen der Dienst wird während des Nachtlaufs neu gestartet, wenn er innerhalb der Nachholfrist wieder läuft, dann wird der Nachtlauf nachgeholt, ohne doppelte Quellen oder Fundorte zu erzeugen.

### Erster Lauf und Zusammenfassung
- [ ] AK-28: Angenommen ein leeres Register und ein Bestand von 1.200 Dateien, wenn der erste Nachtlauf läuft, dann sind alle registriert, die Markdowns sind in Sammel-Commits (≤ 500 Dateien) committet, und der Fortschritt steht im Log.
- [ ] AK-29: Angenommen ein Nachtlauf mit Dateien `a.zip` (3×), `b.exe` (1×) und unterstützten Dateien, wenn er endet, dann gibt es einen Log-Eintrag und eine gespeicherte Zusammenfassung mit den Zahlen aus „Zusammenfassung des Nachtlaufs“, darunter `zip: 3` und `exe: 1` je Ordner und gesamt.
- [ ] AK-30: Angenommen die interne Schnittstelle, wenn ein Tagesscan oder ein Nachtlauf manuell ausgelöst wird, dann startet er sofort (sofern kein anderer Lauf aktiv ist), und die Schnittstelle ist nicht über nginx erreichbar.
- [ ] AK-31: Angenommen das alte System läuft parallel, wenn PROJ-116 scannt, dann bleiben Originale, Redis-Schlüssel des alten Systems und Weaviate unverändert.
- [ ] AK-32 (Live-Test nach Deploy): Angenommen die produktiven überwachten Ordner, wenn der erste Nachtlauf manuell ausgelöst wird, dann ist der Bestand registriert und die Zusammenfassung plausibel (Anzahl Quellen, nicht bearbeitete Endungen); eine neu abgelegte Testdatei erscheint nach spätestens 10 Minuten im Register, eine verschobene behält ihre `id`, eine gelöschte liegt nach dem nächsten Nachtlauf unter `deleted/`.

## Edge Cases
- EC-1: Datei wird zwischen Listen und Hashen gelöscht oder umbenannt → kein Fehler im Register; der Pfad wird beim nächsten Scan neu bewertet (bzw. als Erkennungsproblem geführt, wenn er weiter existiert und nicht lesbar ist).
- EC-2: Zwei identische Dateien tauchen im selben Scan in verschiedenen Ordnern auf → eine Quelle mit zwei Fundorten.
- EC-3: Datei wird umbenannt und gleichzeitig inhaltlich geändert → wie neue Datei (neuer Pfad, neuer Hash); der alte Fundort verschwindet im Nachtlauf, die alte Quelle wird ggf. `deleted`.
- EC-4: Sehr große Datei (mehrere GB) → wird gehasht, ohne den Speicher zu sprengen; blockiert den Scan nicht dauerhaft.
- EC-5: Dateinamen mit Umlauten, Leerzeichen, Sonderzeichen oder sehr langen Pfaden → werden korrekt erkannt und als Fundort gespeichert.
- EC-6: Ein überwachter Ordner wird umbenannt (Pfad in der Liste geändert) → alter Pfad gilt als gelöscht, neuer als neu; Dateien werden über den Hash als Fundorte den bestehenden Quellen zugeordnet, nichts wird neu verarbeitet.
- EC-7: Endung passt, Inhalt nicht (z. B. kaputtes PDF) → wird registriert; Fehler entstehen erst in der Extraktion (PROJ-117).
- EC-8: Ordner mit Tausenden Unterordnern und tiefer Verschachtelung → wird vollständig gescannt; Ordner-Schleifen über Links sind ausgeschlossen, weil Links übersprungen werden.
- EC-9: Die Uhr des NAS weicht von der des Servers ab → Erkennung über Änderungen der Ordnerzeit (Vergleich mit dem zuletzt gesehenen Wert), nicht über absolute Zeitpunkte.
- EC-10: Eine Markdown liegt schon in `deleted/` und das Original taucht wieder auf, während der Mensch dieselbe Datei gerade bearbeitet hat → Hand-Änderung wird zuerst übernommen (PROJ-115, AK-27), dann zurückverschoben.

## Technische Anforderungen
- Testbar ohne NAS: temporäre Ordner als überwachte Ordner, Wegwerf-Postgres/Redis, PROJ-115 mit temporärem Git-Repo.
- Scan-Intervall, Nachtlaufzeit, Nachholfrist, Löschgrenze, Endungs-/Übersprung-/Ausschlusslisten konfigurierbar; neue Variablen nur als Platzhalter in `.env.example`.
- Erkennung: Zugriff auf die NAS-Freigaben wie bei den DMS-Containern über `nas-volumes.yml` (NAS-Konto, kein root; siehe Deployment PROJ-115).
- Register-Dienst (PROJ-115): bindet die eigene Freigabe der Quelle der Wahrheit als ganze Freigabe ein (kein Unterordner, wegen NFS root squash), läuft als NAS-Konto; die Freigabe kommt nicht in `nas-volumes.yml`.
- Schnittstelle nur intern im Docker-Netz, keine nginx-Route.
- Keine neue Queue-/Event-Infrastruktur.
- Keine echten Pfade, Hostnamen oder personenbezogenen Daten im Code oder in Testdaten.

## Offene Fragen
- Keine

## Product Decisions
- Löschen sichtbar machen: Markdown einer `deleted`-Quelle wandert nach `deleted/` und trägt `deleted: <Zeitpunkt>` im Frontmatter; dort darf der Mensch sie dauerhaft löschen (2026-11-22)
- Zwei Läufe: Tagesscan nur für neues Material über die Änderungszeit der Ordner, Nachtlauf als voller Abgleich für Löschen und in-place-Änderungen; Belastung tagsüber nur durch neues Material (2026-11-22)
- Ordner-Zeitstempel statt Datei-Zeitstempel: kopierte Dateien behalten ihre alte Änderungszeit (2026-11-22)
- Stabilität über zwei Scans statt fester Wartezeit (2026-11-22)
- Tagsüber nie entfernen; verschobene Dateien haben ihren neuen Fundort sofort, der alte verschwindet nachts — nichts wird doppelt verarbeitet (2026-11-22)
- Sicherungen des alten Systems übernommen: Ordner muss lesbar und nicht leer sein, höchstens 20 % entfernte Fundorte je Freigabe und Nachtlauf (2026-11-22)
- In-place-Änderung: einziger Fundort → gleiche Quelle mit neuem Hash und Stufen ab `extract` neu; alter Inhalt noch an anderem Fundort → Pfad wird neu bewertet; neuer Hash schon vorhanden → Pfad wandert, alte Quelle `deleted` (2026-11-22)
- Audio und Video werden mit erkannt (nur registriert), damit es keine stillen Lücken gibt (2026-11-22)
- Nicht bearbeitete Endungen werden im Nachtlauf je Ordner und gesamt gezählt, als Log-Eintrag und gespeicherte Zusammenfassung — Grundlage für die Entscheidung über weitere Endungen (2026-11-22)
- Deaktivierter Ordner = eingefroren, gelöschter Ordner = Fundorte entfernen ohne 20-%-Grenze; verschachtelte Ordner → längster passender Ordner (2026-11-22)
- `deleted`-Quellen werden von keiner Stufe übernommen; Reaktion abgeleiteter Daten regeln deren Features; wiederauftauchendes Original reaktiviert die Quelle ohne Neuverarbeitung (2026-11-22)
- Nicht lesbare Dateien als Erkennungsprobleme sichtbar statt still übersprungen (2026-11-22)
- PROJ-116 registriert den Bestand im ersten Nachtlauf selbst (reine Erkennung); Verarbeitung des Bestands und Vollständigkeitsabgleich bleiben bei PROJ-120 (2026-11-22)
- Parallelbetrieb: altes System bleibt unverändert, PROJ-116 schreibt nur über PROJ-115; Abschaltung in PROJ-142 (2026-11-22)
- Eigene NAS-Freigabe für die Quelle der Wahrheit, nur im Register-Dienst eingebunden, nicht im DMS: keine Vermischung mit Mail-/DMS-Daten, kein versehentliches Löschen, keine Selbst-Erkennung der Markdowns (2026-11-22)
- Zugriff auf die Freigabe: Admin schreiben, Haushalt lesen, Gast nichts; Hand-Korrekturen macht der Admin (2026-11-22)
