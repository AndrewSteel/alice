# PROJ-115: Quelle-der-Wahrheit-Repo + Quellen-Register

**Erstellt:** 2026-11-21
**Phase:** 4.1

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-121 (Rollenmodell Haushalt) — nur Bau-Reihenfolge; fachlich keine Abhängigkeit, da PROJ-115 keine Nutzerzugriffe hat
- Grundlage für: PROJ-116 (Datei-Erkennung), PROJ-117 (Text-Extraktion), PROJ-118 (Klassifizierung), PROJ-119 (Strukturierte Dokumentdaten), PROJ-120 (Neuaufbau), PROJ-122 (ETL-Status-Ansicht), PROJ-123–126 (Mail, Anhänge, Bilder, Vorschaubilder), PROJ-127 (RAG), PROJ-129 (Wiki-Ingest)

## Überblick
PROJ-115 legt das Fundament des neuen ETL, ohne selbst Quellen zu erkennen oder zu verarbeiten:
1. **Repo der Quelle der Wahrheit** — ein Git-versionierter Ordner auf dem NAS mit festgelegter Struktur, Dateibenennung und Frontmatter-Basisschema; eine Markdown-Datei je Quelle (eindeutiger Inhalt).
2. **Quellen-Register** in PostgreSQL — alle Quellen mit ihren Fundorten und dem Verarbeitungszustand je Stufe, Fehlern und Retry.
3. **Interne Schnittstelle** für die späteren Stufen — Quelle registrieren, Fundorte pflegen, Stufenzustand setzen, Markdown mit Frontmatter lesen/schreiben (inkl. Commit), Hand-Korrekturen erkennen.

Das Feature hat keine Oberfläche. Getestet wird über Datenbank, interne API und ein temporäres Git-Repo.

## User Stories
- Als Haushaltsmitglied möchte ich jede Quelle (Dokument, Mail, Bild, Audio, Video) als lesbare Markdown-Datei mit sprechendem Namen im NAS-Ordner finden, damit ich nachvollziehen kann, was Alice über sie weiß.
- Als Haushaltsmitglied möchte ich Fehler der Pipeline direkt in der Markdown-Datei korrigieren können, damit die Korrektur in alle abgeleiteten Daten übernommen und nie wieder automatisch überschrieben wird.
- Als Admin möchte ich jede Änderung der Pipeline in Git nachvollziehen und einzeln zurücknehmen können, damit LLM-Fehler rücksetzbar sind.
- Als Admin möchte ich für jede Quelle den Verarbeitungszustand je Stufe mit Fehler und Retry im Register haben, damit nichts still verloren geht und spätere Features (PROJ-122) ihn anzeigen können.
- Als Entwickler der Folge-Features (PROJ-116 ff.) möchte ich eine einheitliche Schnittstelle zu Register und Repo, damit jede Stufe gleich mit Zustand, Fehlern und Commits umgeht.

## Fachliches Modell

### Quelle und Fundorte
- Eine **Quelle** ist ein eindeutiger Inhalt (Hash des Originals). Sie hat genau eine Quell-Markdown und eine stabile, unveränderliche `id`.
- Die `id` wird nicht aus Pfad oder Dateiname abgeleitet. Alle Verweise (Register, DB, Wiki, Mail → Anhang) laufen über die `id`, nie über den Dateinamen.
- Eine Quelle hat **einen oder mehrere Fundorte** (NAS-Pfad bzw. Postfach + Message-ID). Gleicher Inhalt an mehreren Orten = eine Quelle mit mehreren Fundorten, verarbeitet wird nur einmal.
- Ein Mail-Anhang ist keine eigene Art, sondern eine Quelle mit Beziehung zu einer oder mehreren Mails (`parents`).
- Eine Quelle gilt erst als gelöscht (`deleted`), wenn alle ihre Fundorte verschwunden sind. Gelöschte Quellen bleiben im Register (keine physische Löschung durch PROJ-115).

### Arten (`kind`)
`document`, `image`, `email`, `audio`, `video`.
- `audio` und `video` werden registriert und erhalten eine Quell-Markdown mit Basisfeldern und Link aufs Original, aber keine Inhaltsverarbeitung (Stufen außer `detect` = `skipped`).

### Dokumenttyp (`type`)
Wird von PROJ-118 gesetzt, nur bei `kind: document`: `Invoice`, `BankStatement`, `Contract`, `SecuritySettlement`, `Document` (Auffangtyp). `BankTransaction` ist kein Quelltyp (Buchungen entstehen in PROJ-119 aus `BankStatement`).

### Ordnerstruktur und Dateiname
```
<repo>/
  README.md                         # beschreibt Aufbau und Frontmatter-Schema für Menschen
  documents/<JJJJ>/<MM>/<id>-<slug>.md
  images/<JJJJ>/<MM>/<id>-<slug>.md
  emails/<JJJJ>/<MM>/<id>-<slug>.md
  audio/<JJJJ>/<MM>/<id>-<slug>.md
  video/<JJJJ>/<MM>/<id>-<slug>.md
```
- `<JJJJ>/<MM>` = Zeitpunkt der ersten Erfassung (bei Mails: Mail-Datum). Ändert sich danach nicht.
- `<slug>` wird aus `title` gebildet (dateinamentauglich). Startwert von `title` ist der Originalname bzw. Mail-Betreff.
- Ändert sich `title` (durch eine spätere Stufe, z. B. PROJ-118, oder von Hand), wird die Datei per Git-Umbenennung passend umbenannt; Ordner bleibt gleich.
- Verschieben/Umbenennen eines Originals ändert nur die Fundorte, nicht Ort oder Namen der Markdown-Datei.
- Der Repo-Pfad ist konfigurierbar (keine festen Pfade).

### Frontmatter-Basisschema
Pflichtfelder jeder Quell-Markdown (englische Feldnamen; Inhalte wie Titel bleiben in der Sprache der Quelle bzw. Deutsch):

| Feld | Inhalt |
|---|---|
| `id` | stabile, unveränderliche ID |
| `schema` | Versionsnummer des Frontmatter-Formats |
| `kind` | `document` / `image` / `email` / `audio` / `video` |
| `title` | lesbarer Titel; auch als Überschrift im Markdown |
| `locations` | Liste der Fundorte (Pfad bzw. Postfach + Message-ID) |
| `parents` | Liste der IDs der Mails, an denen die Quelle hängt (leer, wenn keine) |
| `hash` | Hash des Originals |
| `size` | Größe des Originals |
| `modified` | Änderungszeit des Originals |
| `captured` | Zeitpunkt der ersten Erfassung |
| `language` | Sprache des Inhalts (leer bis zur Extraktion) |
| `type` | Dokumenttyp (leer bis PROJ-118) |
| `manual` | Liste der von Hand gesetzten Felder (inkl. Inhaltsteil) |

- Fachliche Felder (PROJ-118), Mail-Felder (PROJ-123) und Bild-Felder (PROJ-125) ergänzen das Schema später; das Basisschema muss dafür erweiterbar sein.
- Verarbeitungszustand, Fehler und Retries stehen **nicht** im Frontmatter, nur im Register.

### Stufen und Zustände im Register
- **Stufen** (erweiterbare Liste, neue Stufen ohne Umbau des Registers): `detect` → `extract` → `classify` → `database` → `rag` → `wiki` → `thumbnail`.
- **Zustände je Stufe:** `pending`, `running`, `done`, `failed` (Retry geplant), `failed_permanent` (aufgegeben), `skipped` (Stufe gilt für diese Art nicht).
- Je Stufe gespeichert: Zustand, Anzahl Versuche, letzte Fehlermeldung, Zeitpunkt des letzten Versuchs, nächster Retry-Zeitpunkt.
- **Retry:** exponentielles Backoff 1 min → 5 min → 30 min → 2 h → 12 h; nach 5 Fehlversuchen `failed_permanent`.
- **Manuelles Wiederholen:** setzt die Stufe auf `pending` und den Versuchszähler auf 0 (wird in PROJ-122 in der Oberfläche angeboten; hier nur die Schnittstelle).
- **Hängende Arbeit:** eine Stufe, die länger als eine konfigurierbare Zeitüberschreitung auf `running` steht (z. B. Worker-Absturz), fällt automatisch auf `pending` zurück.
- **Abhängige Stufen:** ändert sich der Inhalt der Quell-Markdown (neue Extraktion, Hand-Korrektur), werden `database`, `rag` und `wiki` wieder auf `pending` gesetzt.
- PostgreSQL ist die Wahrheit über den Zustand; Redis dient nur als Queue/Lock und ist vollständig aus dem Register wiederherstellbar.

### Git-Commits
- Die Pipeline committet immer unter einem eigenen, festen Autor (z. B. „Alice ETL“).
- **Normalbetrieb:** ein Commit je Quelle und Stufe mit lesbarer Nachricht, z. B. `classify: <id> <title>`.
- **Massenläufe (Neuaufbau):** Sammel-Commits mit höchstens 500 Dateien bzw. 5 Minuten je Commit, z. B. `rebuild: extract 500 sources`.
- **Hand-Korrekturen:** eigener Commit je erkannter Änderung, als Hand-Korrektur gekennzeichnet.
- Kein Remote/Push; Sicherung über das bestehende NAS-Backup.

### Hand-Korrekturen
- Der Mensch bearbeitet Quell-Markdowns direkt im NAS-Ordner (Editor oder eigener Git-Commit); ein Commit durch den Menschen ist nicht nötig.
- Jede Änderung, die nicht vom Pipeline-Autor stammt (fremder Commit oder uncommittete Änderung), gilt als Hand-Korrektur. Sie wird spätestens 5 Minuten nach dem Speichern erkannt, committet und ans Register gemeldet (abhängige Stufen → `pending`).
- Alle von Hand geänderten Frontmatter-Felder und ein geänderter Inhaltsteil werden in `manual` eingetragen. Spätere Läufe und ein Neuaufbau überschreiben diese Felder nicht, alle übrigen schon.
- Entfernt der Mensch einen Eintrag aus `manual`, darf die Pipeline das Feld beim nächsten Lauf wieder setzen.

## Außerhalb des Umfangs
- Erkennen von Dateien, Hash/Dedup-Entscheidung, Verschieben/Umbenennen/Löschen und Propagation in abgeleitete Daten, Umgang mit in-place geänderten Originalen (PROJ-116); PROJ-115 liefert nur das Modell (Quelle mit Fundorten, `deleted`) und die Schnittstelle
- Text-Extraktion (PROJ-117), Klassifizierung, fachliche Felder und inhaltliche Titelerzeugung durch das LLM (PROJ-118)
- Fachliche Tabellen für Rechnung, Kontoauszug/Buchung usw. (PROJ-119)
- Neuaufbau-Ablauf und Vollständigkeitsabgleich (PROJ-120); PROJ-115 liefert nur die Sammel-Commits
- Oberfläche für Verarbeitungsstand und „erneut versuchen“ (PROJ-122)
- Mail-spezifische Felder, `.eml`-Ablage (PROJ-123), Bild-Felder (PROJ-125), Vorschaubilder (PROJ-126)
- Wiki-Ordner und Wiki-Pflege (PROJ-129)
- Inhaltsverarbeitung von Audio und Video (Transkription, Beschreibung) — spätere Phase
- Git-Remote/Push, eigenes Backup
- Nutzerzugriff auf Register oder Repo über Alice (später über PROJ-122, PROJ-128, PROJ-131); Zugriff auf den NAS-Ordner regelt die NAS-Freigabe
- Migration alter Redis-/Weaviate-Bestände

## Akzeptanzkriterien

### Repo
- [ ] AK-1: Angenommen ein leerer, konfigurierter Repo-Ordner, wenn das System startet, dann ist er ein Git-Repo mit den Ordnern `documents/`, `images/`, `emails/`, `audio/`, `video/` und einer `README.md`, die Ordnerstruktur, Dateibenennung, Frontmatter-Basisschema und Hand-Korrektur-Regeln beschreibt, als erster Commit des Pipeline-Autors.
- [ ] AK-2: Angenommen ein bereits initialisiertes Repo mit Inhalten, wenn das System neu startet, dann wird es unverändert weiterverwendet (kein neuer Init, keine Änderung an bestehenden Dateien).
- [ ] AK-3: Angenommen ein Repo-Ordner, der Dateien enthält, aber kein Git-Repo ist, wenn das System startet, dann startet es nicht, meldet einen klaren Fehler und verändert den Ordner nicht.
- [ ] AK-4: Angenommen eine neu registrierte Quelle `kind: document` mit Originalname `scan_0042.pdf`, erfasst im November 2026, wenn ihre Quell-Markdown geschrieben wird, dann liegt sie unter `documents/2026/11/<id>-<slug>.md`, enthält alle Pflichtfelder des Basisschemas mit gültigen Werten, `title` = Originalname, und der Titel steht als Überschrift im Markdown.
- [ ] AK-5: Angenommen eine Quelle mit Datei `documents/2026/11/<id>-scan-0042.md`, wenn eine Stufe den `title` auf „Stromrechnung Stadtwerke Okt 2026“ ändert, dann ist die Datei per Git-Umbenennung in `documents/2026/11/<id>-<slug-des-neuen-titels>.md` umbenannt (Historie bleibt über `git log --follow` erhalten), der Ordner unverändert, und die Quelle ist über ihre `id` weiterhin auffindbar.
- [ ] AK-6: Angenommen eine Quelle, wenn ein Fundort hinzukommt oder sich ändert (Original verschoben/umbenannt), dann ändert sich nur `locations` im Frontmatter und im Register; Ordner und Dateiname der Markdown bleiben gleich.
- [ ] AK-7: Angenommen eine Stufe schreibt eine Quell-Markdown im Normalbetrieb, wenn der Schreibvorgang abgeschlossen ist, dann gibt es genau einen Commit des Pipeline-Autors für diese Quelle und Stufe, dessen Nachricht Stufe, `id` und `title` enthält.
- [ ] AK-8: Angenommen ein Massenlauf schreibt 1.200 Quell-Markdowns, wenn er abgeschlossen ist, dann sind sie in Sammel-Commits mit je höchstens 500 Dateien zusammengefasst; ein angefangener Sammel-Commit wird spätestens nach 5 Minuten abgeschlossen.
- [ ] AK-9: Angenommen eine Quell-Markdown, wenn man sie liest, dann enthält das Frontmatter keinen Verarbeitungszustand, keine Fehlermeldung und keinen Retry-Zähler.
- [ ] AK-10: Angenommen Quellen der Arten `audio` und `video`, wenn sie registriert werden, dann bekommen sie eine Quell-Markdown mit Basisfeldern und Link aufs Original unter `audio/` bzw. `video/`, und alle Stufen außer `detect` stehen auf `skipped`.

### Register und Fundorte
- [ ] AK-11: Angenommen eine neue Quelle, wenn sie über die Schnittstelle registriert wird, dann hat sie im Register eine eindeutige `id`, Art, Hash, mindestens einen Fundort und für jede Stufe einen Zustand (`pending` bzw. `skipped`).
- [ ] AK-12: Angenommen eine registrierte Quelle mit Hash H, wenn derselbe Hash an einem zweiten Fundort (anderer Pfad oder Mail) registriert wird, dann entsteht keine zweite Quelle und keine zweite Markdown; der Fundort wird der bestehenden Quelle hinzugefügt, und bereits erledigte Stufen werden nicht erneut ausgeführt.
- [ ] AK-13: Angenommen eine Datei-Quelle, die zusätzlich als Anhang an Mail M gefunden wird, wenn der Anhang registriert wird, dann enthält `parents` die ID von M, und M verweist auf die bestehende Quelle.
- [ ] AK-14: Angenommen eine Quelle mit zwei Fundorten, wenn einer als verschwunden gemeldet wird, dann bleibt die Quelle aktiv; wenn auch der zweite verschwindet, dann ist sie im Register `deleted` und bleibt als Eintrag erhalten.
- [ ] AK-15: Angenommen eine Stufe in `pending`, wenn ein Worker sie übernimmt, dann steht sie auf `running`; zwei gleichzeitige Worker können dieselbe Stufe derselben Quelle nicht beide übernehmen.
- [ ] AK-16: Angenommen eine Stufe schlägt fehl, wenn der Fehler gemeldet wird, dann steht sie auf `failed` mit Fehlermeldung, Versuchszähler +1 und nächstem Retry nach dem Backoff-Plan (1 min, 5 min, 30 min, 2 h, 12 h).
- [ ] AK-17: Angenommen eine Stufe ist 5-mal fehlgeschlagen, wenn der fünfte Fehler gemeldet wird, dann steht sie auf `failed_permanent` mit letzter Fehlermeldung und Zeitpunkt und wird nicht mehr automatisch wiederholt.
- [ ] AK-18: Angenommen eine Stufe in `failed_permanent`, wenn über die Schnittstelle „erneut versuchen“ ausgelöst wird, dann steht sie auf `pending` mit Versuchszähler 0.
- [ ] AK-19: Angenommen eine Stufe steht länger als die konfigurierte Zeitüberschreitung auf `running` (Worker abgestürzt), wenn die Überwachung läuft, dann fällt sie automatisch auf `pending` zurück, ohne als Fehlversuch zu zählen.
- [ ] AK-20: Angenommen eine Quelle mit `database`, `rag` und `wiki` auf `done`, wenn sich der Inhalt ihrer Quell-Markdown ändert (durch eine Stufe oder von Hand), dann stehen diese drei Stufen wieder auf `pending`.
- [ ] AK-21: Angenommen eine neue Stufe wird von einem Folge-Feature ergänzt, wenn sie angelegt wird, dann erhalten bestehende Quellen für sie einen Zustand, ohne dass das Register umgebaut oder Daten migriert werden müssen.
- [ ] AK-22: Angenommen Redis wird geleert (Neustart ohne Persistenz), wenn das System weiterläuft, dann wird die Arbeits-Queue aus dem Register wiederhergestellt und keine `pending`- oder fälligen `failed`-Stufe geht verloren.

### Hand-Korrekturen
- [ ] AK-23: Angenommen eine Quell-Markdown, wenn ein Mensch das Feld `title` und den Inhaltsteil ändert und speichert (ohne Commit), dann ist die Änderung spätestens 5 Minuten später als Hand-Korrektur committet (nicht unter dem Pipeline-Autor), `manual` enthält `title` und den Inhaltsteil, und die abhängigen Stufen stehen auf `pending`.
- [ ] AK-24: Angenommen ein Mensch committet eine Änderung an einer Quell-Markdown selbst, wenn das System sie erkennt, dann wird sie wie AK-23 als Hand-Korrektur behandelt (Einträge in `manual`, abhängige Stufen `pending`).
- [ ] AK-25: Angenommen ein Feld steht in `manual`, wenn eine Stufe oder ein Neuaufbau das Feld neu setzen will, dann bleibt der von Hand gesetzte Wert erhalten, während nicht geschützte Felder aktualisiert werden.
- [ ] AK-26: Angenommen ein Mensch entfernt ein Feld aus `manual`, wenn die zuständige Stufe das nächste Mal läuft, dann darf sie das Feld wieder überschreiben.
- [ ] AK-27: Angenommen eine Datei hat uncommittete Hand-Änderungen, wenn eine Stufe dieselbe Datei schreiben will, dann wird zuerst die Hand-Änderung als Hand-Korrektur committet (inkl. `manual`) und danach die Stufe unter Beachtung von `manual` geschrieben; die Hand-Änderung geht nicht verloren.
- [ ] AK-28: Angenommen ein Mensch speichert ungültiges Frontmatter (kein gültiges YAML, fehlendes Pflichtfeld oder geänderte `id`), wenn das System die Änderung erkennt, dann wird sie nicht übernommen und die Datei nicht überschrieben, die Quelle bekommt im Register einen Fehler mit verständlicher Ursache, abgeleitete Daten bleiben auf dem letzten gültigen Stand, und die Pipeline fasst die Datei nicht an, bis sie repariert ist.
- [ ] AK-29: Angenommen eine nach AK-28 gesperrte Datei, wenn der Mensch das Frontmatter repariert, dann wird die Korrektur übernommen, der Fehler im Register aufgehoben und die Verarbeitung läuft normal weiter.

### Betrieb und Zugriff
- [ ] AK-30: Angenommen das NAS bzw. der Repo-Ordner ist nicht erreichbar, wenn Stufen schreiben wollen, dann pausieren sie, ihre Zustände bleiben `pending`, es wird kein Fehlversuch gezählt, der Healthcheck meldet „unhealthy“ mit Grund, und im Log steht eine Warnung.
- [ ] AK-31: Angenommen das NAS war nicht erreichbar und ist wieder da, wenn das System weiterläuft, dann wird die Verarbeitung ohne Eingriff fortgesetzt und in der Zwischenzeit gemachte Hand-Korrekturen werden erkannt.
- [ ] AK-32: Angenommen eine verwaiste Git-Sperre nach einem Absturz, wenn das System startet oder schreibt, dann wird sie nach einer Wartezeit sicher entfernt, ohne eine laufende Git-Operation zu stören.
- [ ] AK-33: Angenommen die Schnittstelle zu Register und Repo, wenn man sie von außerhalb des Docker-Netzes (über nginx) aufrufen will, dann ist sie nicht erreichbar; es gibt keine nginx-Route.
- [ ] AK-34 (Live-Test nach Deploy): Angenommen der konfigurierte NAS-Ordner auf dem Produktivsystem, wenn das System startet, dann ist das Repo angelegt und über die NAS-Freigabe mit einem Editor lesbar; eine Test-Hand-Korrektur an einer Testdatei wird innerhalb von 5 Minuten committet.

## Edge Cases
- EC-1: Zwei Quellen ergeben denselben Slug → Dateinamen sind trotzdem eindeutig, weil die `id` vorangestellt ist.
- EC-2: Titel mit Sonderzeichen, Umlauten, Schrägstrichen oder sehr lang → Slug ist dateinamentauglich und in der Länge begrenzt; Umlaute bleiben lesbar (z. B. `ae`/`oe`/`ue`), der volle Titel steht im Frontmatter.
- EC-3: Mensch ändert den `title` und eine Stufe ändert ihn kurz danach ebenfalls → `title` steht in `manual`, die Stufe überschreibt ihn nicht; der Dateiname folgt dem Hand-Titel.
- EC-4: Mensch benennt oder verschiebt die Markdown-Datei selbst → Die Quelle wird über die `id` im Frontmatter weiter zugeordnet; der Name wird beim nächsten Lauf wieder aus `title` gebildet und die Datei in ihren Ordner zurückgelegt (Ort und Name sind keine Hand-Korrektur).
- EC-5: Mensch löscht eine Quell-Markdown → wird als Fehler im Register gemeldet; die Datei wird beim nächsten Lauf aus dem letzten Stand in Git wiederhergestellt (Löschen läuft über das Original, PROJ-116).
- EC-6: Mensch legt eine Markdown-Datei ohne Bezug zu einer Quelle an → wird nicht als Quelle behandelt, im Log gewarnt, nicht gelöscht.
- EC-7: Container-Neustart während eines Sammel-Commits → keine halben Commits im Repo; bereits geschriebene, nicht committete Pipeline-Dateien werden nach dem Neustart unter dem Pipeline-Autor committet, nicht als Hand-Korrektur gewertet.
- EC-8: Original ändert sich an Ort und Stelle (neuer Hash, gleicher Pfad) → Behandlung entscheidet PROJ-116; das Register muss erlauben, den Hash einer bestehenden Quelle zu aktualisieren.
- EC-9: Gleichzeitige Schreibzugriffe mehrerer Stufen auf das Repo → Git-Operationen laufen serialisiert, kein Commit enthält Änderungen einer fremden Stufe.
- EC-10: Pflichtfeld `schema` in einer alten Version → Datei bleibt gültig; spätere Schema-Erweiterungen ergänzen fehlende Felder beim nächsten Schreiben, ohne `manual`-Felder zu überschreiben.

## Technische Anforderungen
- Testbar ohne NAS: Factory-Tests mit temporärem Git-Repo im Job-Ordner und Wegwerf-Postgres/Redis.
- Keine neue Queue-/Event-Infrastruktur: PostgreSQL = Zustand (Wahrheit), Redis nur Queue/Lock, MQTT bei Bedarf für Benachrichtigungen.
- Repo-Pfad, Zeitüberschreitung für hängende Stufen und Prüfintervall für Hand-Korrekturen konfigurierbar; neue Variablen nur als Platzhalter in `.env.example`.
- Schnittstelle nur intern im Docker-Netz, keine nginx-Route.
- Keine echten Pfade, Hostnamen oder personenbezogenen Daten im Code oder in Testdaten.

## Offene Fragen
- Keine

## Product Decisions
- Schnitt: PROJ-115 liefert nur Repo, Register und interne Schnittstelle; Erkennung, Extraktion, Klassifizierung, Fachtabellen und Oberfläche bleiben in PROJ-116–122 (2026-11-21)
- Ablage nach Art / Jahr / Monat der Erfassung statt Spiegelung der NAS-Struktur: Verschieben von Originalen erzeugt keine Git-Verschiebungen und bricht keine Links (2026-11-21)
- Identität allein über die `id`; Dateiname `<id>-<slug-aus-title>`, der bei Titeländerung umbenannt wird. Kryptische Originalnamen können so später durch einen inhaltlichen Titel (PROJ-118) ersetzt werden, ohne Verweise zu brechen (2026-11-21)
- Hand-Korrekturen feldgenau über `manual` geschützt statt Schutz der ganzen Datei: so können nicht korrigierte Felder bei Modellwechsel oder Neuaufbau weiter verbessert werden (2026-11-21)
- Erkennung von Hand-Korrekturen über den Git-Autor: alles, was nicht vom Pipeline-Autor stammt, ist Hand-Korrektur; Mensch muss nicht selbst committen (2026-11-21)
- Englische Feldnamen im Frontmatter, konsistent mit DB und Code; Inhalte bleiben in der Sprache der Quelle (2026-11-21)
- `kind` (Medium: document/image/email/audio/video) und `type` (fachlicher Dokumenttyp aus PROJ-118) getrennt; Anhang ist keine Art, sondern Beziehung `parents`; `BankTransaction` ist kein Quelltyp (2026-11-21)
- Audio und Video werden registriert und bekommen eine Basis-Markdown ohne Inhaltsverarbeitung, damit es keine stillen Lücken gibt (2026-11-21)
- Verarbeitungszustand nur im Register, nicht im Frontmatter: sonst erzeugt jeder Retry einen Commit (2026-11-21)
- Retry mit Backoff 1 min / 5 min / 30 min / 2 h / 12 h, danach `failed_permanent`; hängende `running`-Stufen fallen nach Zeitüberschreitung auf `pending` zurück (2026-11-21)
- Ein Commit je Quelle und Stufe im Normalbetrieb, Sammel-Commits (≤ 500 Dateien / 5 min) bei Massenläufen; kein Remote, Sicherung über NAS-Backup (2026-11-21)
- Ungültige Hand-Änderungen werden weder übernommen noch überschrieben, sondern als Fehler gemeldet, bis der Mensch sie repariert (2026-11-21)
- Eine Quelle je eindeutigem Inhalt (Hash) mit mehreren Fundorten: keine doppelten Treffer, keine doppelten LLM-Läufe; Quelle erst `deleted`, wenn alle Fundorte weg sind (2026-11-21)
- NAS-Ausfall zählt nicht als Fehlversuch; Verarbeitung pausiert und läuft danach selbstständig weiter (2026-11-21)
- Kein Nutzerzugriff in PROJ-115; Schnittstelle nur intern, Rollenprüfung in den lesenden Folge-Features (2026-11-21)
