# PROJ-124: Mail-Anhänge als Quelldokumente

**Erstellt:** 2026-11-26
**Phase:** 4.2

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-123 (Mail-Import in den ETL) — Mail-Archiv mit den Anhangsdateien, Mail-Markdown mit Feld `attachments` und Abschnitt „Anhänge“, Regeln für `deleted` bei Mails
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Quellen mit mehreren Fundorten, `parents`, Stufen/Zustände, Commits, `manual`-Schutz
- Benötigt: PROJ-116 (Datei-Erkennung) — Erkennungsliste der Endungen je Art (`document`/`image`/`audio`/`video`), Hash `sha256`, Dedup-Regel „bekannter Hash = zusätzlicher Fundort“
- Benötigt: PROJ-117 (Text-Extraktion), PROJ-118 (Klassifizierung), PROJ-119 (strukturierte Dokumentdaten) — verarbeiten Anhangs-Quellen der Art `document` unverändert wie jedes Dokument
- Ändert: PROJ-118 (Klassifizierung) — bei Quellen mit `parents` bekommt das LLM Betreff, Absender und Datum der Mail als Hinweis
- Ändert: PROJ-123 (Mail-Import) — trägt die Quell-`id` je Anhang in `attachments` der Mail-Markdown nach und ergänzt im Abschnitt „Anhänge“ einen Link auf die Anhangs-Markdown
- Ändert: PROJ-120 (Neuaufbau + Vollständigkeitsabgleich) — neue Abgleich-Ebene „Mail ↔ Anhangs-Quellen“
- Grundlage für: PROJ-125 (Bilder in der Quelle der Wahrheit; verarbeitet die hier registrierten Bild-Anhänge), PROJ-127 (RAG-Index), PROJ-128 (Such-Tools), PROJ-129 (Wiki-Ingest)

## Überblick
PROJ-123 legt die echten Anhänge jeder Mail als Dateien im Mail-Archiv ab, verarbeitet sie aber nicht. PROJ-124 macht sie zu **eigenen Quellen** im Register und lässt sie durch dieselbe Pipeline laufen wie jede Datei aus einem überwachten Ordner:

1. **Registrieren:** Zu jeder Mail-Quelle mit Anhängen wird jeder echte Anhang mit erkannter Endung als Quelle angelegt. Das Original bleibt dabei im Mail-Archiv, es wird nicht kopiert und nicht über `/mnt/nas/ai/<Typ>/` geschleust. Der Fundort der Quelle ist die Datei im Archiv.
2. **Dedup per Hash:** Ist der Inhalt schon als Quelle bekannt (DMS-Datei, Anhang einer anderen Mail, derselbe Anhang zweimal), entsteht keine zweite Quelle, sondern ein zusätzlicher Fundort und ein weiterer Eintrag in `parents`.
3. **Pipeline:** Dokumente laufen durch `extract` (PROJ-117), `classify` (PROJ-118) und `database` (PROJ-119), Bilder übernimmt PROJ-125, Audio/Video bleiben bei `skipped` (PROJ-115). Bei der Klassifizierung kennt das LLM den Mail-Kontext.
4. **Verweise in beide Richtungen:** Der Anhang kennt seine Mails über `parents`, die Mail kennt den Anhang über `attachments[].id` und einen Link auf die Anhangs-Markdown.

Anhänge erreichen die Pipeline damit innerhalb von Minuten nach dem Mail-Import, nicht erst nach bis zu einem Tag wie im alten System. Das Feature hat keine Oberfläche. Getestet wird mit temporärem Mail-Archiv (Testmails mit Anhängen), Wegwerf-Postgres/Redis, PROJ-115 mit temporärem Git-Repo und gemocktem LLM/OCR.

## User Stories
- Als Haushaltsmitglied möchte ich, dass die Anhänge meiner Mails (Rechnungen, Verträge, Fotos) wie jedes andere Dokument durchsuchbar und ausgewertet sind, damit Alice Fragen dazu mit Quellenangabe beantworten kann.
- Als Haushaltsmitglied möchte ich von einer Mail direkt zur Markdown ihres Anhangs springen können und vom Anhang zurück zur Mail, damit ich Zusammenhänge nachvollziehen kann.
- Als Haushaltsmitglied möchte ich, dass ein Anhang, den ich schon als Datei im NAS habe, nicht doppelt verarbeitet wird, damit es keine doppelten Treffer und keine doppelte Arbeit gibt.
- Als Haushaltsmitglied möchte ich, dass ein Anhang wie `scan0001.pdf` mit Hilfe von Betreff und Absender der Mail richtig eingeordnet wird, damit auch nichtssagende Dateinamen kein Problem sind.
- Als Haushaltsmitglied möchte ich, dass Anhänge in Alice erhalten bleiben, auch wenn ich die Mail im Postfach lösche, damit ich Speicherplatz beim Mailanbieter sparen kann, ohne Wissen zu verlieren.
- Als Admin möchte ich sehen, welche Anhänge nicht verarbeitet werden (nicht erkannte Endungen, z. B. `zip`, `ics`, weitergeleitete Mails) mit Anzahl, damit ich entscheiden kann, ob weitere Endungen nötig sind.

## Fachliches Modell

### Welche Anhänge zu Quellen werden
- Grundlage ist die Liste `attachments` der Mail-Markdown aus PROJ-123, also die **echten Anhänge** (Teile mit Dateinamen, die nicht per `cid:` im HTML eingebettet sind). Eingebettete Bilder (Logos, Signaturen) sind nie betroffen; sie bleiben in der `.eml`.
- Ein Anhang wird Quelle, wenn seine Endung in der Erkennungsliste von PROJ-116 (inkl. Erweiterung durch PROJ-117) steht. Die Art ergibt sich aus der Endung (`document`, `image`, `audio`, `video`), Groß-/Kleinschreibung egal. Die Liste ist dieselbe wie in PROJ-116 und wird nicht doppelt gepflegt.
- **Kein weiterer Filter:** Es gibt keine Mindestgröße und keine Namensmuster. Das Rauschen kleiner Logos ist bereits durch die `cid:`-Regel in PROJ-123 ausgeschlossen.
- Alle anderen Anhänge (z. B. `zip`, `ics`, `vcf`, `winmail.dat`, **weitergeleitete Mails als `.eml`**) werden nicht registriert. Sie bleiben im Archiv und in `attachments` (ohne `id`) und werden gezählt (siehe „Nicht verarbeitete Anhänge“). Das Auspacken von Archiven und weitergeleiteten Mails ist ausdrücklich nicht Teil dieses Features.
- Leere Anhänge (0 Byte) werden nicht registriert, aber wie nicht erkannte Anhänge gezählt.

### Registrierung einer Anhangs-Quelle
- **Auslöser:** Sobald eine Mail-Quelle ihre Markdown mit `attachments` hat (PROJ-123, Stufe `extract` der Mail `done`), registriert PROJ-124 deren Anhänge. Es wird nicht gescannt: Der Weg führt von der Mail zu den Anhängen, nicht über einen überwachten Ordner.
- **Fundort:** die Anhangsdatei im Mail-Archiv (`<id>.attachments/<Dateiname>`). Gehasht wird sie mit `sha256` wie in PROJ-116. Der Pfad ist stabil, weil PROJ-123 Archivdateien nie überschreibt oder löscht.
- **Neuer Hash:** neue Quelle mit neuer stabiler `id`, Basis-Markdown über PROJ-115, Stufe `detect` erledigt, `parents` = `[<Mail-id>]`. Weitere Stufen stehen wie bei jeder Datei der Art auf `pending` bzw. `skipped`.
- **Bekannter Hash:** keine neue Quelle. Der Archivpfad kommt als zusätzlicher Fundort an die bestehende Quelle, und die Mail-`id` kommt in deren `parents`. Es gibt keine erneute Verarbeitung; erledigte Stufen bleiben erledigt. Das gilt unabhängig davon, ob die bestehende Quelle aus einem DMS-Ordner, aus einer anderen Mail oder aus derselben Mail stammt.
- **Derselbe Inhalt zweimal in einer Mail** (gleicher Hash, verschiedene Dateinamen): eine Quelle mit zwei Fundorten; beide Einträge in `attachments` zeigen auf dieselbe `id`.
- **Umgekehrte Richtung:** Taucht ein Anhangs-Inhalt später auch in einem DMS-Ordner auf, gilt die Regel „bekannter Hash“ aus PROJ-116 (zusätzlicher Fundort). `parents` bleibt unverändert, die Quelle behält ihre Mail-Beziehung.
- **Ablage der Markdown:** unter der Art der Quelle (`documents/`, `images/`, `audio/`, `video/`) mit `<JJJJ>/<MM>` des **Mail-Datums der ersten Mail**, nicht des Registrierungszeitpunkts. `title` startet mit dem Dateinamen des Anhangs (PROJ-115/118 dürfen ihn wie bei jedem Dokument später ändern).
- Eine Anhangs-Quelle ist keine eigene Art und keine eigene Markdown-Form. Sie ist eine normale Quelle mit gefülltem `parents`.

### Verweise in der Mail
- Nach der Registrierung trägt PROJ-124 die Quell-`id` im Eintrag der Mail-Markdown unter `attachments` nach (`attachments[].id`).
- Im Abschnitt „Anhänge“ der Mail-Markdown steht je registriertem Anhang zusätzlich zum Link auf die Archivdatei ein Link auf die Anhangs-Markdown (relativer Pfad). Weil die Markdown bei Titeländerung umbenannt wird, werden diese Links nachgeführt (Verweise laufen über die `id`, PROJ-115). Nicht registrierte Anhänge haben nur den Archiv-Link.
- Die Änderung der Mail-Markdown ist ein eigener Commit nach den Regeln von PROJ-115. Felder in `manual` und ein von Hand geänderter Inhaltsteil werden nicht überschrieben; ist der Inhaltsteil in `manual`, wird nur das Frontmatter (`attachments[].id`) ergänzt und die Linkabschnitte bleiben, wie der Mensch sie gesetzt hat.
- Die Stufe `classify` der Mail läuft deswegen nicht erneut.

### Klassifizierung mit Mail-Kontext (Änderung an PROJ-118)
- Hat eine Quelle `parents`, bekommt das LLM bei `classify` zusätzlich zum Dokumenttext **Betreff, Absender und Datum** der Mail als Hinweis. Der Dokumenttext bleibt maßgeblich; der Hinweis hilft bei Dokumenten mit nichtssagendem Namen oder wenig Text.
- Hat die Quelle mehrere Mails, wird die **älteste** genommen.
- Ist die Mail-Markdown nicht lesbar, läuft die Klassifizierung ohne Kontext und scheitert nicht.
- Der Mailtext selbst wird nicht übergeben (Datenschutz, Länge). Quellen ohne `parents` werden unverändert klassifiziert.

### Löschen und Archiv
- **Der Anhang bleibt aktiv, wenn seine Mail `deleted` wird.** Sein Fundort ist die Archivdatei, und das Archiv wird nie gelöscht (PROJ-123). `parents` enthält die `deleted`-Mail weiterhin. Das passt zu „Mails bleiben in Alice, auch wenn ich sie im Postfach lösche“.
- Eine Anhangs-Quelle wird durch PROJ-124 **nie** automatisch `deleted`. Fehlt die Archivdatei, ist das kein Löschen, sondern eine Lücke: Sie wird über den Abgleich gemeldet (Ebene „Register ↔ Mail-Archiv“ aus PROJ-123). Hat die Quelle weitere Fundorte (z. B. eine DMS-Datei), bleibt sie dort erreichbar.
- Wird eine Mail reaktiviert (wieder auf dem Server), ändert sich an den Anhangs-Quellen nichts.
- Eine Quelle, die auch als DMS-Datei existiert und dort verschwindet, verliert nur diesen Fundort; der Archivpfad bleibt, die Quelle bleibt aktiv (Regeln PROJ-116).

### Nicht verarbeitete Anhänge (Meldung)
- Je Lauf (Takt und Abgleich) werden nicht registrierte Anhänge nach Endung gezählt. Eine gespeicherte Zusammenfassung (für PROJ-122) nennt die Endungen mit Anzahl, gesamt und je Postfach. Ältere Zusammenfassungen bleiben mindestens 30 Tage abrufbar (wie PROJ-116).
- Die Meldung ist informativ. Sie erzeugt keinen Fehler und keine Warnung im Healthcheck.

### Bestand und Neuaufbau
- **Bestand:** Beim ersten Lauf nach dem Deploy holt PROJ-124 die Registrierung für alle bereits importierten Mails von PROJ-123 nach (auch für `deleted`-Mails, deren Archiv noch vorhanden ist), in Paketen begrenzter Größe mit Sammel-Commits (PROJ-115) und fortsetzbar nach Neustart. Neue Mails haben Vorrang vor dem Bestand.
- **Neuaufbau (PROJ-120):** Ein Neuaufbau ab `detect` oder `extract` mit Art `email` legt die Anhangs-Quellen aus Archiv und Mail-Markdown wieder an. Dank Hash-Dedup entstehen keine Duplikate; bestehende `id`s bleiben erhalten.
- **Neue Abgleich-Ebene „Mail ↔ Anhangs-Quellen“:** Jeder Anhang mit erkannter Endung in `attachments` einer Mail hat eine Quelle (`id` gesetzt, `parents` enthält die Mail, Archivpfad ist Fundort). Fehlende Registrierungen werden nachgeholt (unter der Reparaturgrenze von PROJ-120), fehlende Archivdateien nur gemeldet. Die Ebene erscheint in der Zusammenfassung des Abgleichs (und damit in PROJ-122) mit Zahlen und Liste der Lücken.

### Fehler
- **Mail-Archiv nicht erreichbar / Anhangsdatei nicht lesbar:** Registrierung pausiert ohne Fehlversuche und ohne Register-Änderung für die betroffene Mail; die übrigen laufen weiter. Nach Rückkehr geht es selbstständig weiter.
- **Register/Repo (PROJ-115) nicht erreichbar:** Registrierung pausiert und holt nach Rückkehr alles nach; nichts geht verloren.
- **Anhang nicht extrahierbar** (Passwortschutz, kaputt): Das ist Sache der Stufe `extract` (PROJ-117) mit `failed_permanent`; die Quelle bleibt registriert und sichtbar. Die Mail ist davon nicht betroffen.
- **Mail-Markdown nicht schreibbar / `manual`-Konflikt beim Nachtragen der `id`:** Die Registrierung der Anhangs-Quelle bleibt bestehen; das Nachtragen wird wiederholt (Backoff wie PROJ-115). Der Fehler steht im Register.

## Außerhalb des Umfangs
- Das Ablegen der Anhänge im Mail-Archiv (PROJ-123)
- Inhaltsverarbeitung von Bildern (Beschreibung, OCR, Bild-Felder) → PROJ-125; hier wird nur registriert
- Vorschaubilder für Anhänge → PROJ-126
- Auspacken von Archiven (`zip` usw.) und Verarbeiten weitergeleiteter Mails (`.eml`) als eigene Mail-Quelle, auch rekursiv; sie werden nur gezählt
- Registrieren von `cid:`-eingebetteten Bildern (bleiben in der `.eml`, PROJ-123)
- Mindestgröße oder Namensfilter für Anhänge
- RAG-Index, Suche, Wiki für Anhänge (PROJ-127–129)
- Übernahme der alten Anhangsordner `/mnt/nas/ai/<Typ>/` und der alten Redis-Queue; sie bleiben bis PROJ-142 liegen. Sind sie als überwachter Ordner eingetragen, gilt die normale Hash-Dedup (siehe EC-6)
- Die komplette Mail als Kontext im LLM (nur Betreff, Absender, Datum)
- Oberfläche für Anhänge oder nicht verarbeitete Endungen (PROJ-122)
- Automatisches `deleted` einer Anhangs-Quelle wegen fehlender Archivdatei
- Neue Zugriffsrechte; es gelten die Regeln aus PROJ-121 (`admin` und `haushalt` lesen alles, `guest` nichts)

## Akzeptanzkriterien

### Registrierung
- [ ] AK-1: Angenommen eine importierte Mail mit zwei PDF-Anhängen unterschiedlichen Inhalts, wenn PROJ-124 läuft, dann gibt es zwei neue Quellen `kind: document` mit je einer Quell-Markdown unter `documents/<JJJJ>/<MM>/`, `parents` = `[<Mail-id>]`, `detect` auf `done` und `extract` auf `pending`.
- [ ] AK-2: Angenommen eine Anhangs-Quelle, wenn man ihre Fundorte liest, dann ist der einzige Fundort die Anhangsdatei im Mail-Archiv, und es gibt keine Kopie der Datei in einem DMS-Ordner oder unter `/mnt/nas/ai/<Typ>/`.
- [ ] AK-3: Angenommen Anhänge mit den Endungen `pdf`, `JPG`, `mp3` und `mp4`, wenn PROJ-124 läuft, dann entstehen Quellen der Art `document`, `image`, `audio` und `video` unter den passenden Ordnern; `audio` und `video` haben alle Stufen außer `detect` auf `skipped`.
- [ ] AK-4: Angenommen die Erkennungsliste von PROJ-116 wird um eine Endung erweitert, wenn PROJ-124 läuft, dann werden Anhänge mit dieser Endung ebenfalls Quellen, ohne dass PROJ-124 geändert werden muss.
- [ ] AK-5: Angenommen die Mail wurde im Januar 2026 empfangen und PROJ-124 läuft im November 2026, wenn die Anhangs-Markdown geschrieben wird, dann liegt sie unter `…/2026/01/`.
- [ ] AK-6: Angenommen ein Anhang `scan0001.pdf`, wenn die Quelle angelegt wird, dann ist `title` = `scan0001.pdf` und der Titel steht als Überschrift im Markdown (PROJ-115).
- [ ] AK-7: Angenommen ein erneuter Lauf ohne neue Anhänge, wenn er läuft, dann entstehen keine neuen Quellen, keine neuen Fundorte, keine Commits und keine Änderung an den Mail-Markdowns.
- [ ] AK-8: Angenommen zwei laufende Instanzen des Dienstes und dieselbe Mail, wenn beide ihre Anhänge registrieren, dann entsteht jede Quelle nur einmal.
- [ ] AK-9: Angenommen eine Mail ist importiert, wenn man die Zeit bis zur Registrierung ihrer Anhänge misst, dann liegen höchstens 5 Minuten (konfigurierbar) zwischen dem Ende von `extract` der Mail und der Registrierung der Anhänge.

### Auswahl der Anhänge
- [ ] AK-10: Angenommen eine HTML-Mail mit zwei `cid:`-eingebetteten Bildern und einem echten PDF-Anhang, wenn PROJ-124 läuft, dann gibt es genau eine Anhangs-Quelle (das PDF).
- [ ] AK-11: Angenommen eine Mail mit einem 3-KB-PNG-Anhang und einem 5-MB-JPG-Anhang, wenn PROJ-124 läuft, dann sind beide registriert (keine Mindestgröße).
- [ ] AK-12: Angenommen Anhänge `daten.zip`, `termin.ics` und eine weitergeleitete Mail `nachricht.eml`, wenn PROJ-124 läuft, dann entsteht dafür keine Quelle; die Dateien liegen unverändert im Archiv und stehen ohne `id` in `attachments`.
- [ ] AK-13: Angenommen ein Anhang mit 0 Byte und Endung `pdf`, wenn PROJ-124 läuft, dann wird keine Quelle angelegt, und der Anhang wird als nicht verarbeitet gezählt.

### Dedup
- [ ] AK-14: Angenommen ein Anhang mit demselben Hash wie eine bestehende DMS-Quelle, wenn PROJ-124 läuft, dann gibt es keine neue Quelle; die bestehende bekommt den Archivpfad als zusätzlichen Fundort und die Mail-`id` in `parents`, und ihre erledigten Stufen bleiben `done`.
- [ ] AK-15: Angenommen derselbe Anhang in zwei verschiedenen Mails, wenn PROJ-124 läuft, dann gibt es eine Quelle mit zwei Fundorten und beiden Mail-`id`s in `parents`, und beide Mails verweisen in `attachments` auf dieselbe `id`.
- [ ] AK-16: Angenommen eine Mail mit demselben Inhalt als `a.pdf` und `b.pdf`, wenn PROJ-124 läuft, dann gibt es eine Quelle mit zwei Fundorten, und beide `attachments`-Einträge tragen dieselbe `id`.
- [ ] AK-17: Angenommen eine Anhangs-Quelle und später eine Datei mit gleichem Hash in einem DMS-Ordner, wenn PROJ-116 läuft, dann wird die Datei zusätzlicher Fundort der bestehenden Quelle, `parents` bleibt unverändert, und es entsteht keine zweite Quelle.

### Verweise in der Mail
- [ ] AK-18: Angenommen eine Mail mit zwei registrierten Anhängen und einem nicht registrierten (`zip`), wenn PROJ-124 gelaufen ist, dann tragen die ersten beiden Einträge in `attachments` die Quell-`id`, der dritte hat keine `id`.
- [ ] AK-19: Angenommen dieselbe Mail, wenn man den Abschnitt „Anhänge“ liest, dann steht bei den beiden registrierten Anhängen zusätzlich zum Archiv-Link ein funktionierender relativer Link auf die Anhangs-Markdown; das `zip` hat nur den Archiv-Link.
- [ ] AK-20: Angenommen eine Anhangs-Markdown wird durch eine Titeländerung umbenannt, wenn die Verweise nachgeführt werden, dann zeigt der Link in der Mail auf den neuen Dateinamen und die `id` ist unverändert.
- [ ] AK-21: Angenommen in der Mail-Markdown steht der Inhaltsteil in `manual`, wenn PROJ-124 die `id` nachträgt, dann wird der Inhaltsteil nicht verändert, und die `id` steht im Frontmatter.
- [ ] AK-22: Angenommen die Mail-Markdown wurde angepasst, wenn man das Register liest, dann ist `classify` der Mail unverändert `done`, und es gibt einen eigenen Commit des Pipeline-Autors für die Ergänzung.

### Pipeline
- [ ] AK-23: Angenommen eine Anhangs-Quelle `kind: document` (PDF mit Textebene), wenn die Pipeline läuft, dann übernimmt PROJ-117 sie, schreibt den Text mit Seitenmarken, und PROJ-118/119 verarbeiten sie wie jedes DMS-Dokument. Der Originalpfad wird nur gelesen, nie verändert.
- [ ] AK-24: Angenommen eine Anhangs-Quelle mit `parents` und ein LLM-Mock, wenn `classify` läuft, dann enthält der Prompt Betreff, Absender und Datum der Mail und nicht den Mailtext.
- [ ] AK-25: Angenommen eine Anhangs-Quelle mit zwei Mails in `parents`, wenn `classify` läuft, dann stammt der Mail-Kontext von der älteren Mail.
- [ ] AK-26: Angenommen die Mail-Markdown der Eltern-Mail ist nicht lesbar, wenn `classify` läuft, dann läuft sie ohne Mail-Kontext und endet nicht in `failed`.
- [ ] AK-27: Angenommen eine Quelle ohne `parents`, wenn `classify` läuft, dann ist der Prompt identisch zum Stand vor PROJ-124.
- [ ] AK-28: Angenommen ein passwortgeschütztes PDF als Anhang, wenn `extract` läuft, dann steht die Stufe sofort auf `failed_permanent` mit Ursache; die Quelle bleibt registriert, die Mail ist unverändert.
- [ ] AK-29: Angenommen ein Bild-Anhang, wenn PROJ-124 gelaufen ist, dann ist er als Quelle `kind: image` registriert und `detect` ist `done`; andere Stufen bearbeitet PROJ-124 nicht (Verarbeitung PROJ-125).

### Löschen
- [ ] AK-30: Angenommen eine Mail mit registriertem Anhang wird `deleted`, wenn der Nachtlauf von PROJ-123 läuft, dann bleibt die Anhangs-Quelle aktiv, ihre Markdown bleibt am regulären Platz, `parents` enthält die Mail weiterhin, und die Archivdatei ist unverändert.
- [ ] AK-31: Angenommen eine `deleted`-Mail, deren Anhänge noch nicht registriert waren, wenn PROJ-124 läuft, dann werden die Anhänge registriert, weil das Archiv noch vorhanden ist.
- [ ] AK-32: Angenommen eine Anhangs-Quelle, deren Archivdatei fehlt, wenn der Abgleich läuft, dann wird sie nicht `deleted`, sondern als Lücke gemeldet.
- [ ] AK-33: Angenommen eine Anhangs-Quelle mit zusätzlichem Fundort in einem DMS-Ordner, dessen Datei dort gelöscht wird, wenn der Nachtlauf von PROJ-116 läuft, dann bleibt die Quelle aktiv (Archivpfad bleibt Fundort).

### Nicht verarbeitete Anhänge
- [ ] AK-34: Angenommen ein Lauf mit drei `zip`-, zwei `ics`- und einem `eml`-Anhang, wenn er abgeschlossen ist, dann nennt die gespeicherte Zusammenfassung diese Endungen mit Anzahl, gesamt und je Postfach, und es gibt weder Fehler noch Healthcheck-Warnung.

### Bestand und Neuaufbau
- [ ] AK-35: Angenommen 500 bereits importierte Mails mit Anhängen aus der Zeit vor PROJ-124, wenn der erste Lauf nach dem Deploy läuft, dann werden ihre Anhänge in Paketen der konfigurierten Größe registriert, mit Sammel-Commits (höchstens 500 Dateien je Commit), und nach einem Neustart in der Mitte geht der Lauf an der richtigen Stelle weiter.
- [ ] AK-36: Angenommen ein laufender Bestandslauf, wenn eine neue Mail mit Anhang importiert wird, dann sind ihre Anhänge nach spätestens dem Zeitfenster aus AK-9 registriert, auch wenn der Bestand noch nicht fertig ist.
- [ ] AK-37: Angenommen ein Neuaufbau mit Art `email` ab `extract` ohne Verbindung zum Mailserver, wenn er abgeschlossen ist, dann haben alle Mail-Anhänge mit erkannter Endung eine Quelle, ohne Duplikate und mit unveränderten `id`s.
- [ ] AK-38: Angenommen ein Anhang mit erkannter Endung, für den keine Quelle existiert, wenn der Abgleich läuft, dann erscheint er in der Ebene „Mail ↔ Anhangs-Quellen“ und wird nachgeholt (unter der Reparaturgrenze von PROJ-120); die Ebene steht mit Zahlen und Lückenliste in der Zusammenfassung.

### Fehler und Betrieb
- [ ] AK-39: Angenommen das Mail-Archiv ist nicht erreichbar, wenn PROJ-124 läuft, dann entstehen keine Fehlversuche und keine Register-Änderungen; nach Rückkehr geht es selbstständig weiter.
- [ ] AK-40: Angenommen PROJ-115 (Register/Repo) ist nicht erreichbar, wenn PROJ-124 läuft, dann pausiert es und holt nach Rückkehr alles nach, ohne Duplikate.
- [ ] AK-41: Angenommen der Dienst wird mitten in einem Lauf beendet, wenn er neu startet, dann gibt es keine halbe Markdown, keinen halben Commit und keine doppelte Quelle.
- [ ] AK-42: Angenommen Logs und Fehlermeldungen, wenn man sie durchsucht, dann enthalten sie keine Mailtexte und keine Passwörter.
- [ ] AK-43: Angenommen der Dienst, wenn man ihn von außerhalb des Docker-Netzes (über nginx) aufrufen will, dann ist er nicht erreichbar.
- [ ] AK-44: Angenommen die Deploy-Schritte des PRs, wenn man sie liest, dann ändern sie `alice-mail-api`, `alice-mail-tools`, `alice-mail-reader` und die Postfach-Verwaltung nicht.
- [ ] AK-45 (Live-Test nach Deploy): Angenommen eine Testmail mit einer echten PDF-Rechnung als Anhang an das produktive Postfach, wenn sie importiert ist, dann steht der Anhang binnen weniger Minuten als Quelle mit `parents` im Repo, wird extrahiert und klassifiziert (plausibler Typ), und die Mail verweist per Link darauf.
- [ ] AK-46 (Live-Test nach Deploy): Angenommen der Bestand ist nachgeholt, wenn der Abgleich läuft, dann meldet die Ebene „Mail ↔ Anhangs-Quellen“ keine Lücken, und Chat und Sprache blieben dabei flüssig.

## Edge Cases
- EC-1: Gleiche Datei als DMS-Dokument und als Mail-Anhang → eine Quelle, zwei Fundorte (Archivpfad + NAS-Pfad), `parents` gesetzt (AK-14).
- EC-2: Ein Anhang kommt in einer Mail an, die in zwei Postfächern liegt → es ist eine Mail-Quelle (PROJ-123), also eine Anhangs-Quelle mit einem Archivpfad.
- EC-3: Anhang mit gleicher Datei, aber geändertem Namen in einer Antwort-Mail → gleicher Hash, eine Quelle, zwei Fundorte und zwei `parents`.
- EC-4: Anhang wurde zwischen zwei Läufen im Archiv ersetzt (Hash ändert sich) → PROJ-123 überschreibt Archivdateien nie; eine solche Änderung durch Menschen wird als Lücke/Abweichung gemeldet und nicht still übernommen.
- EC-5: Mensch benennt die Anhangs-Markdown um oder korrigiert den Text von Hand → `manual`-Schutz und Hand-Korrektur wie bei jeder Quelle; der Rückverweis in der Mail folgt der `id`.
- EC-6: Alte Anhangsordner `/mnt/nas/ai/<Typ>/` sind noch als überwachter Ordner eingetragen → PROJ-116 registriert dort liegende Kopien. Haben sie denselben Hash wie ein Anhang, werden sie zusätzlicher Fundort (ohne neue Quelle); der Admin kann den Ordner austragen (PROJ-142).
- EC-7: Anhang ohne Dateinamen (PROJ-123 vergibt einen erzeugten Namen aus MIME-Typ und Nummer) → die Endung ergibt sich aus diesem Namen; passt sie nicht zur Erkennungsliste, wird er gezählt.
- EC-8: Dateiname und tatsächlicher Inhalt passen nicht (z. B. `.pdf`, ist aber ein Bild) → die Art folgt der Endung; Fehler dabei behandelt die Stufe `extract` (PROJ-117).
- EC-9: Sehr große Anhänge (>100 MB) → werden gehasht und registriert; Stufen mit eigenen Grenzen (PROJ-117) behandeln sie dort.
- EC-10: Mail mit sehr vielen Anhängen (z. B. 300) → werden in Paketen registriert, andere Mails werden dadurch nicht blockiert.

## Technische Anforderungen
- Kein Kopieren von Anhängen in überwachte Ordner und kein Umweg über `/mnt/nas/ai/<Typ>/`; Originale bleiben im Mail-Archiv und werden nie verändert, verschoben oder gelöscht.
- Keine nginx-Route (nur internes Docker-Netz).
- Der Lauf nutzt keinen LLM-Slot; die LLM-Stufen laufen über die vorhandenen Stufen als Hintergrundlast (PROJ-111).
- Zugriff nur für `admin`/`haushalt` über die vorhandenen Wege; keine neuen Rechte.

## Offene Fragen
- [ ] _Keine blockierenden Fragen._

## Product Decisions
- **Alle erkannten Endungen werden Quellen, Dedup per Hash**: gleiche Liste wie PROJ-116, kein doppelt gepflegtes Regelwerk; gleiche Inhalte laufen nur einmal durch LLM/OCR (2026-11-26)
- **Kein Mindestgrößenfilter**: Das Rauschen von Logos/Signaturen entfällt bereits durch die `cid:`-Regel in PROJ-123; echte kleine Bild-Anhänge bleiben verlustfrei erfasst (2026-11-26)
- **Rückverweis `id` im Frontmatter + Link auf Anhangs-Markdown**: maschinell und für Menschen nachvollziehbar, Links laufen über die `id` und überleben Umbenennungen (2026-11-26)
- **Anhang bleibt aktiv, wenn die Mail `deleted` wird**: Fundort ist die nie gelöschte Archivdatei; passt zur Zusage „Mails/Wissen bleiben trotz gelöschter Mail im Postfach“ (2026-11-26)
- **Kein automatisches `deleted` wegen fehlender Archivdatei, nur Lückenmeldung**: konservativ, passend zum Schutz gegen Massenverlust; ein fehlendes Archiv ist ein Fehler, keine Nutzeraktion (2026-11-26)
- **Weitergeleitete Mails (`.eml`) werden nur gezählt**: rekursives Auspacken braucht eigene Regeln für Identität, Tiefe und Ablage; eigenes Feature, falls gewünscht (2026-11-26)
- **Mail-Kontext (Betreff, Absender, Datum der ältesten Mail) bei der Klassifizierung**: hilft bei nichtssagenden Dateinamen, ohne den Mailtext ins LLM zu geben (2026-11-26)
- **Ablage nach Mail-Datum, nicht nach Registrierungszeitpunkt**: Bestandslauf und Neuaufbau sollen Anhänge dort ablegen, wo die Mail liegt (2026-11-26)
- **Auslöser ist die Mail, nicht ein Scan**: kein zweiter Scanner über das Mail-Archiv; Anhänge erreichen die Pipeline innerhalb von Minuten statt eines Tages (2026-11-26)
