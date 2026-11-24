# PROJ-120: Neuaufbau + Vollständigkeitsabgleich

**Erstellt:** 2026-11-24
**Phase:** 4.1

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Stufen, Stufenzustände, Versuchszähler, „erneut versuchen“, Sammel-Commits, `manual`-Schutz, Sperre bei ungültigem Frontmatter, Ereignisse je Quelle, Git-Historie
- Benötigt: PROJ-116 (Datei-Erkennung) — überwachte Ordner, Endungs-/Übersprunglisten, Registrieren neuer Dateien, Regeln für an Ort und Stelle geänderte Originale, Nachtlauf, Schutz bei nicht lesbaren/leeren Ordnern
- Benötigt: PROJ-117, PROJ-118, PROJ-119 — die Stufen `extract`, `classify`, `database`, die fällige Arbeit selbst abarbeiten; PROJ-119 für den Abgleich Register ↔ DB
- Grundlage für: PROJ-122 (ETL-Status-Ansicht: Fortschritt, Steuerung, Abgleich-Ergebnisse), PROJ-123/125/127/129 (ergänzen ihre Stufen bzw. Abgleich-Ebenen)

## Überblick
PROJ-120 hat zwei Teile:

1. **Neuaufbau:** Der Admin startet einen Lauf, der ab einer gewählten Stufe alle Quellen (optional einer Art) neu verarbeiten lässt — z. B. nach einem Modellwechsel oder einer verbesserten Extraktion. PROJ-120 baut keine Stufen nach, sondern setzt die Stufen gedrosselt in Portionen auf `pending`; die bestehenden Stufen-Dienste arbeiten sie ab. Der Lauf hat einen Fortschritt, lässt sich pausieren, fortsetzen und abbrechen und übersteht Neustarts.
2. **Vollständigkeitsabgleich:** Jede Nacht und auf Abruf vergleicht PROJ-120 NAS, Register, Repo, Stufenzustände und DB. Eindeutige Lücken werden automatisch repariert, alles andere wird gemeldet. Ziel (PRD): 100 % der Quellen haben eine Quell-Markdown oder einen sichtbaren Fehlerstatus, 0 stille Lücken.

Das Feature hat keine Oberfläche; Steuerung und Abruf über eine interne Schnittstelle, die PROJ-122 ohne Erweiterung nutzen kann. Getestet wird mit temporären Ordnern als „NAS“, Wegwerf-Postgres/Redis und PROJ-115 mit temporärem Git-Repo; kein LLM.

## User Stories
- Als Admin möchte ich nach einem Modellwechsel alle Dokumente ab der Klassifizierung neu verarbeiten lassen, ohne dass meine Hand-Korrekturen verloren gehen.
- Als Admin möchte ich den Umfang eines Neuaufbaus wählen (Startstufe, Art), damit nicht unnötig OCR und LLM laufen.
- Als Admin möchte ich den Fortschritt eines Neuaufbaus mit Restzeit sehen und ihn pausieren, fortsetzen oder abbrechen können.
- Als Haushaltsmitglied möchte ich, dass neue Dateien und der Chat während eines Neuaufbaus nicht spürbar langsamer werden.
- Als Admin möchte ich sicher sein, dass keine Datei, Quell-Markdown oder DB-Zeile still fehlt, und jeden Morgen sehen, ob der Abgleich Lücken gefunden oder repariert hat.
- Als Admin möchte ich, dass ein Abgleich bei einem Ausfall (NAS, Fehler im Abgleich) keine Massenreparatur auslöst.

## Fachliches Modell

### Neuaufbau-Lauf
- **Umfang:** Startstufe (z. B. `extract`, `classify`, `database`) und optional eine Art (`document`, `image`, …). Neu laufen die Startstufe **und alle folgenden Stufen** in der Reihenfolge aus PROJ-115, auch später hinzukommende (z. B. `rag`, `wiki`). `detect` ist keine wählbare Startstufe.
- **Momentaufnahme:** Die Menge der Quellen steht beim Start fest. Quellen, die während des Laufs neu hinzukommen, laufen normal und zählen nicht zum Lauf.
- **Inbegriffen:** alle nicht gelöschten Quellen im Umfang, auch mit `failed`/`failed_permanent` (Versuchszähler startet bei 0).
- **Ausgenommen und mit Grund gezählt:** gelöschte Quellen, durch PROJ-115 gesperrte Quellen (ungültiges Frontmatter), Stufen, die für die Art `skipped` sind.
- **Hand-Korrekturen:** Felder in `manual` bleiben durch PROJ-115 geschützt; PROJ-120 fasst Quell-Markdowns nicht selbst an.
- **Sammel-Commits:** Schreibvorgänge der Stufen für Quellen des Laufs laufen als Massenlauf mit Sammel-Commits (PROJ-115).
- Höchstens **ein** Lauf ist gleichzeitig aktiv oder pausiert; ein weiterer Start wird mit Hinweis auf den bestehenden Lauf abgelehnt.

### Last und Vorrang
- **Normalbetrieb hat Vorrang:** Fällige Arbeit, die nicht aus einem Neuaufbau stammt (neue/geänderte Dateien, Hand-Korrekturen, „erneut versuchen“), wird von den Stufen immer vor Neuaufbau-Arbeit übernommen. Das Aktualitätsziel ≤ 15 min bis zur DB gilt auch während eines Neuaufbaus.
- **Chat hat Vorrang:** LLM-Aufrufe des Neuaufbaus laufen im LLM-Gateway als Hintergrundlast.
- **Drosselung:** Je Stufe sind höchstens N Quellen des Laufs gleichzeitig freigegeben (`pending`/`running`), N einstellbar. Eine neue Portion wird erst freigegeben, wenn Platz ist.
- Kein Zeitfenster: der Lauf arbeitet rund um die Uhr.

### Steuerung
- **Pausieren:** keine neuen Portionen; bereits freigegebene Quellen laufen zu Ende. **Fortsetzen** macht an derselben Stelle weiter.
- **Abbrechen:** keine neuen Portionen, freigegebene laufen zu Ende; der Lauf endet als `abgebrochen` mit Zahlen. Nicht erreichte Quellen behalten ihren alten, gültigen Stand. Kein Zurückrollen.
- **Neustart des Dienstes:** ein laufender Lauf setzt selbstständig fort, ein pausierter bleibt pausiert.
- **Ende:** `abgeschlossen`, wenn alle Quellen des Laufs die Stufen im Umfang mit `done` oder Fehler (`failed_permanent`) durchlaufen haben. Danach startet automatisch ein Vollständigkeitsabgleich, dessen Ergebnis am Lauf hängt.
- Status eines Laufs: `läuft`, `pausiert`, `wartet` (mit Grund, z. B. Repo nicht erreichbar), `abgeschlossen`, `abgebrochen`.

### Fortschritt
- Je Lauf: Umfang, Status (ggf. mit Grund), Start, Ende, „gestartet von“, Anzahl Quellen gesamt und ausgenommen je Grund.
- Je Stufe des Laufs: erledigt, fehlgeschlagen (`failed`/`failed_permanent`), in Arbeit, offen.
- Durchsatz (Quellen pro Stunde über die letzte Stunde) und daraus geschätzte Restzeit; Zeitpunkt des Stands.
- Fehlerliste des Laufs: `id`, Titel, Stufe, Fehlermeldung.
- Log: Fortschrittszeile alle 15 Minuten (einstellbar) sowie bei Start, Pause, Fortsetzen, Abbruch, Ende.
- Abgeschlossene und abgebrochene Läufe bleiben mit ihren Zahlen dauerhaft abrufbar.
- Keine aktive Benachrichtigung (Push/Mail).

### Vollständigkeitsabgleich — Ebenen
1. **NAS ↔ Register:** Jede Datei mit erkannter Endung in einem aktiven überwachten Ordner (Endungs-/Übersprunglisten aus PROJ-116) ist als vorhandener Fundort registriert; jeder vorhandene Fundort existiert. **Neu-Hashen:** der Hash (`sha256`) der Originale wird neu berechnet und mit dem Register verglichen.
2. **Register ↔ Repo:** Jede Quelle hat genau eine Quell-Markdown am erwarteten Ort (gelöschte unter `deleted/`); keine Markdown ohne Registereintrag; `id` und `kind` im Frontmatter stimmen mit dem Register.
3. **Stufen:** Jede nicht gelöschte Quelle hat in jeder geltenden Stufe `done`, `skipped` oder einen sichtbaren Fehler. Gemeldet wird eine Stufe, die länger als eine einstellbare Grenze (Standard 24 h) `pending` ist. Quellen, die in einem aktiven Neuaufbau-Lauf gerade offen sind, zählen nicht als Lücke. Hängendes `running` regelt PROJ-115.
4. **Register ↔ DB (PROJ-119):** Jedes Dokument mit `database` = `done` hat seine Dokument-Zeile; keine DB-Zeile zu einer gelöschten oder unbekannten Quelle.

Weitere Ebenen (Mails/IMAP, RAG, Wiki) ergänzen ihre Features; der Abgleich ist dafür erweiterbar.

### Vollständigkeitsabgleich — Zeitpunkte
- **Nachts** nach dem Nachtlauf von PROJ-116: Ebenen 1 (ohne Neu-Hashen), 2, 3, 4. Abgleich und PROJ-116-Nachtlauf laufen nie gleichzeitig; der Abgleich wartet.
- **Neu-Hashen rollierend:** jede Nacht eine begrenzte Portion (einstellbare Zeit- bzw. Datenmengengrenze), sodass der ganze Bestand innerhalb eines einstellbaren Zyklus (Standard 30 Tage) einmal geprüft ist. Ein Neustart setzt an derselben Stelle fort.
- **Auf Abruf:** Abgleich (Ebenen 1 ohne Neu-Hashen bis 4) und vollständiges Neu-Hashen.
- Jeder Abgleich speichert ein **Ergebnis**: Zeitpunkt, Dauer, Art (nachts, auf Abruf, nach Neuaufbau), Status (`vollständig`/`unvollständig` mit Grund), je Ebene Anzahl und Liste der Lücken, getroffene Reparaturen, gemeldete Fälle, übersprungene Ordner, Fortschritt des Hash-Zyklus. Zusätzlich ein Log-Eintrag. Ergebnisse bleiben mindestens 30 Tage abrufbar.

### Vollständigkeitsabgleich — Reaktion auf Lücken
| Lücke | Reaktion |
|---|---|
| Datei auf dem NAS, nicht registriert | registrieren wie eine neu gefundene Datei (Regeln PROJ-116) |
| Vorhandener Fundort, Datei fehlt | nur melden (Entfernen bleibt beim PROJ-116-Nachtlauf mit 20-%-Sicherung) |
| Hash beim Neu-Hashen abweichend | behandeln wie ein an Ort und Stelle geändertes Original (Regeln PROJ-116) |
| Quelle ohne Quell-Markdown | letzten Stand aus der Git-Historie wiederherstellen; geht das nicht, Basis-Markdown neu anlegen und Stufen ab `extract` auf `pending` |
| Markdown ohne Registereintrag oder `id`/`kind` passen nicht | nur melden, nichts ändern oder löschen |
| Markdown am falschen Ort (z. B. gelöschte Quelle außerhalb `deleted/` oder umgekehrt) | per Git-Umbenennung an den richtigen Ort |
| Stufe länger als Grenze `pending` | nur melden |
| `database` = `done`, DB-Zeile fehlt | `database` auf `pending` |
| DB-Zeile zu gelöschter oder unbekannter Quelle | aus der DB entfernen (inkl. abhängiger Datensätze) |

- Jede Reparatur wird als Ereignis an der Quelle protokolliert (PROJ-115) und im Ergebnis gezählt.
- **Sicherung gegen Massenreparatur:** Betreffen die Reparaturen eines Abgleichs mehr als einen einstellbaren Anteil der Quellen (Standard 5 %), repariert er nichts und meldet nur; das Ergebnis weist das aus.

### Störungen
- **Register/Repo (PROJ-115) nicht erreichbar:** laufender Neuaufbau geht auf `wartet` mit Grund und setzt nach Rückkehr selbstständig fort. Ein Abgleich bricht ab, speichert ein Ergebnis `unvollständig` mit Grund und repariert nichts.
- **Überwachter Ordner nicht lesbar oder leer:** auf Ebene 1 übersprungen und gemeldet, nichts gilt als fehlend (Logik PROJ-116).
- **Datei verschwindet beim Neu-Hashen oder ist nicht lesbar:** nur melden, nächster Durchlauf versucht es erneut.
- **PostgreSQL nicht erreichbar:** Neuaufbau `wartet`, Abgleich `unvollständig`; danach selbstständig weiter.

### Schnittstelle (für PROJ-122)
- Nur im Docker-Netz, keine nginx-Route; Admin-Zugang über die Oberfläche kommt mit PROJ-122. Beim Start eines Laufs wird ein Name als „gestartet von“ übergeben.
- **Steuerung:** Neuaufbau starten (Startstufe, optional Art), pausieren, fortsetzen, abbrechen; Abgleich auf Abruf; vollständiges Neu-Hashen auf Abruf.
- **Fortschritts-Abruf:** ein Aufruf liefert alles für die Ansicht (Status mit Grund, Umfang, Zahlen gesamt/ausgenommen/je Stufe, Durchsatz, Restzeit, Zeitpunkt des Stands). Ausgelegt auf häufiges Abfragen durch mehrere Oberflächen im Abstand weniger Sekunden: Antwort < 200 ms auch bei 50.000 Quellen im Lauf, keine Last auf NAS oder Repo, Zahlen höchstens 5 Sekunden alt. Die Refresh-Zeit stellt die Oberfläche ein (PROJ-122).
- **Listen mit Seitenweise-Abruf:** Fehlerliste eines Laufs, Liste der Läufe, Liste der Abgleich-Ergebnisse, Lücken eines Abgleichs je Ebene.

## Außerhalb des Umfangs
- Oberfläche für Fortschritt, Steuerung und Abgleich-Ergebnisse; Admin-Authentifizierung; Einstellen der Refresh-Zeit (PROJ-122)
- Neuaufbau einzelner Quellen (das ist „erneut versuchen“, PROJ-115/PROJ-122)
- Eigene Stufen-Logik: Extraktion, Klassifizierung, DB-Eintrag laufen in PROJ-117/118/119
- Abgleich-Ebenen und Stufen für Mails/IMAP, Bilder, RAG, Wiki (PROJ-123, PROJ-125, PROJ-127, PROJ-129)
- Übernahme vorhandener Bildbeschreibungen beim Neuaufbau (PROJ-125); Neubeschreibung des Bildbestands (PROJ-114)
- Entfernen verschwundener Fundorte (bleibt beim PROJ-116-Nachtlauf)
- Löschen oder Ändern von Markdowns ohne Registereintrag
- Zeitfenster für den Neuaufbau, mehrere gleichzeitige Läufe, Zurückrollen eines Laufs
- Aktive Benachrichtigungen (Push, Mail)
- Änderungen am Altsystem (n8n, alte Redis-Schlüssel, Weaviate) — PROJ-142

## Akzeptanzkriterien

### Neuaufbau: Start und Umfang
- [ ] AK-1: Angenommen 10 Dokumente mit allen Stufen `done`, wenn ein Neuaufbau mit Startstufe `classify` gestartet wird, dann laufen für alle 10 `classify` und `database` erneut, `extract` bleibt `done`, und der Lauf steht danach auf `abgeschlossen`.
- [ ] AK-2: Angenommen Quellen der Arten `document` und `image`, wenn ein Neuaufbau mit Startstufe `extract` und Art `document` gestartet wird, dann gehören nur die Dokumente zum Lauf, und keine Stufe einer Bild-Quelle wird zurückgesetzt.
- [ ] AK-3: Angenommen eine zusätzliche Stufe wird nach `database` in PROJ-115 registriert, wenn ein Neuaufbau ab `database` gestartet wird, dann gehört auch die neue Stufe zum Umfang.
- [ ] AK-4: Angenommen eine Quelle mit `classify` auf `failed_permanent` und Versuchszähler 5, wenn ein Neuaufbau ab `classify` sie erreicht, dann steht `classify` auf `pending` mit Versuchszähler 0.
- [ ] AK-5: Angenommen eine gelöschte Quelle, eine von PROJ-115 gesperrte Quelle und eine `audio`-Quelle, wenn ein Neuaufbau ab `extract` ohne Art-Filter startet, dann wird keine ihrer Stufen zurückgesetzt, und der Fortschritt zählt sie als ausgenommen mit dem jeweiligen Grund.
- [ ] AK-6: Angenommen ein laufender Neuaufbau, wenn während des Laufs eine neue Quelle registriert wird, dann gehört sie nicht zum Lauf (Gesamtzahl unverändert) und wird normal verarbeitet.
- [ ] AK-7: Angenommen ein aktiver oder pausierter Lauf, wenn ein weiterer Neuaufbau gestartet wird, dann wird der Start mit Hinweis auf den bestehenden Lauf abgelehnt.
- [ ] AK-8: Angenommen ein Feld steht in `manual`, wenn ein Neuaufbau ab `extract` die Quelle durchlaufen hat, dann steht der Hand-Wert unverändert in der Quell-Markdown und in der DB.
- [ ] AK-9: Angenommen ein Neuaufbau über 1.200 Quellen, wenn er durchgelaufen ist, dann sind die Schreibvorgänge der Stufen in Sammel-Commits (≤ 500 Dateien) statt in Einzel-Commits committet.

### Neuaufbau: Drosselung und Vorrang
- [ ] AK-10: Angenommen Drosselung N = 20 und ein Lauf über 500 Quellen, wenn man die Stufenzustände während des Laufs wiederholt prüft, dann sind je Stufe nie mehr als 20 Quellen des Laufs gleichzeitig `pending` oder `running`.
- [ ] AK-11: Angenommen ein laufender Neuaufbau mit freigegebenen Quellen, wenn eine neue Datei registriert wird, dann übernimmt jede Stufe deren Arbeit vor der fälligen Neuaufbau-Arbeit.
- [ ] AK-12: Angenommen ein Neuaufbau ab `classify`, wenn die Stufe LLM-Aufrufe macht (Gateway gemockt), dann laufen sie mit Hintergrund-Priorität.

### Neuaufbau: Steuerung
- [ ] AK-13: Angenommen ein laufender Lauf, wenn er pausiert wird, dann werden keine neuen Quellen freigegeben, bereits freigegebene laufen zu Ende, und der Status ist `pausiert`.
- [ ] AK-14: Angenommen ein pausierter Lauf, wenn er fortgesetzt wird, dann werden nur noch nicht freigegebene Quellen freigegeben, keine wird doppelt verarbeitet, und der Lauf endet als `abgeschlossen` mit vollständigen Zahlen.
- [ ] AK-15: Angenommen ein laufender Lauf über 500 Quellen, von denen 100 freigegeben wurden, wenn er abgebrochen wird, dann laufen die freigegebenen zu Ende, die übrigen 400 behalten ihre Stufenzustände unverändert, und der Lauf steht auf `abgebrochen` mit Zahlen.
- [ ] AK-16: Angenommen ein laufender und (in einem zweiten Test) ein pausierter Lauf, wenn der Dienst neu startet, dann setzt der laufende selbstständig fort, und der pausierte bleibt pausiert; keine Quelle wird doppelt freigegeben.
- [ ] AK-17: Angenommen ein Lauf ist `abgeschlossen`, wenn man die Abgleich-Ergebnisse abruft, dann gibt es ein automatisch gestartetes Ergebnis der Art „nach Neuaufbau“, das dem Lauf zugeordnet ist.

### Neuaufbau: Fortschritt
- [ ] AK-18: Angenommen ein laufender Lauf ab `classify` mit 100 Quellen, davon 3 ausgenommen, wenn der Fortschritt abgerufen wird, dann enthält er Umfang, Status, Start, „gestartet von“, Gesamtzahl 100, ausgenommen 3 mit Grund, je Stufe erledigt/fehlgeschlagen/in Arbeit/offen (Summe je Stufe = Anzahl der Quellen im Lauf), Durchsatz, geschätzte Restzeit und den Zeitpunkt des Stands.
- [ ] AK-19: Angenommen im Lauf schlagen 2 Quellen in `classify` fehl, wenn die Fehlerliste abgerufen wird, dann enthält sie genau diese 2 mit `id`, Titel, Stufe und Fehlermeldung.
- [ ] AK-20: Angenommen ein Lauf mit 50.000 Quellen, wenn der Fortschritt 20-mal pro Sekunde abgerufen wird, dann antwortet jeder Abruf in < 200 ms, es gibt keine Zugriffe auf Repo oder NAS-Ordner, und die Zahlen sind höchstens 5 Sekunden alt.
- [ ] AK-21: Angenommen ein laufender Lauf und Log-Intervall 1 Minute (Testkonfiguration), wenn 3 Minuten vergehen, dann stehen mindestens 3 Fortschrittszeilen im Log; Start, Pause, Fortsetzen, Abbruch und Ende stehen ebenfalls im Log.
- [ ] AK-22: Angenommen zwei beendete Läufe, wenn die Liste der Läufe abgerufen wird, dann sind beide mit Umfang, Status, Zeiten und Endzahlen enthalten.

### Abgleich: Ebenen und Reparaturen
- [ ] AK-23: Angenommen eine Datei mit erkannter Endung in einem aktiven Ordner, die nicht registriert ist, wenn ein Abgleich läuft, dann ist sie danach nach den Regeln von PROJ-116 registriert, und das Ergebnis zählt sie als repariert auf Ebene 1.
- [ ] AK-24: Angenommen ein vorhandener Fundort, dessen Datei fehlt, wenn ein Abgleich läuft, dann bleibt der Fundort unverändert, und das Ergebnis meldet ihn auf Ebene 1.
- [ ] AK-25: Angenommen ein Original wurde so geändert, dass Größe und Änderungszeit gleich bleiben, der Inhalt aber abweicht, wenn das Neu-Hashen es erreicht, dann wird es wie ein an Ort und Stelle geändertes Original nach PROJ-116 behandelt und im Ergebnis gezählt.
- [ ] AK-26: Angenommen eine registrierte Quelle, deren Quell-Markdown im Repo fehlt, aber in der Git-Historie existiert, wenn ein Abgleich läuft, dann ist der letzte Stand wiederhergestellt; fehlt sie auch in der Historie, liegt eine Basis-Markdown vor und die Stufen ab `extract` sind `pending`. In beiden Fällen gibt es ein Ereignis an der Quelle.
- [ ] AK-27: Angenommen eine Markdown ohne Registereintrag bzw. eine Markdown, deren `kind` nicht zum Register passt, wenn ein Abgleich läuft, dann bleibt die Datei unverändert, und das Ergebnis meldet sie auf Ebene 2.
- [ ] AK-28: Angenommen eine gelöschte Quelle, deren Markdown außerhalb von `deleted/` liegt (bzw. eine aktive Quelle mit Markdown unter `deleted/`), wenn ein Abgleich läuft, dann liegt sie danach am richtigen Ort, verschoben per Git-Umbenennung mit erhaltener Historie.
- [ ] AK-29: Angenommen eine Stufe ist seit 25 Stunden `pending` (Grenze 24 h) und eine andere Quelle ist seit 25 Stunden `pending` als Teil eines aktiven Neuaufbaus, wenn ein Abgleich läuft, dann meldet das Ergebnis auf Ebene 3 nur die erste.
- [ ] AK-30: Angenommen ein Dokument mit `database` = `done` ohne Dokument-Zeile in der DB, wenn ein Abgleich läuft, dann steht `database` danach auf `pending`.
- [ ] AK-31: Angenommen eine Dokument-Zeile mit Buchungen zu einer gelöschten Quelle und eine Dokument-Zeile zu einer unbekannten `id`, wenn ein Abgleich läuft, dann sind beide samt abhängigen Datensätzen aus der DB entfernt.
- [ ] AK-32: Angenommen ein konsistenter Bestand, wenn ein Abgleich läuft, dann meldet das Ergebnis 0 Lücken auf allen Ebenen und repariert nichts.
- [ ] AK-33: Angenommen 100 Quellen, von denen bei 6 die Markdown fehlt (Grenze 5 %), wenn ein Abgleich läuft, dann repariert er nichts, meldet die 6 Lücken und weist im Ergebnis aus, dass die Sicherung gegen Massenreparatur gegriffen hat.
- [ ] AK-34: Angenommen ein Abgleich hat repariert, wenn man die Ereignisse der betroffenen Quellen abruft, dann gibt es je Reparatur ein Ereignis.

### Abgleich: Zeitpunkte und Ergebnis
- [ ] AK-35: Angenommen der PROJ-116-Nachtlauf läuft, wenn der nächtliche Abgleich fällig wird, dann startet er erst nach dessen Ende; beide laufen nie gleichzeitig.
- [ ] AK-36: Angenommen ein Bestand und eine Hash-Portion je Nacht von einem Drittel (Testkonfiguration), wenn drei nächtliche Abgleiche gelaufen sind, dann ist jedes Original genau einmal neu gehasht, und das Ergebnis zeigt den Fortschritt des Hash-Zyklus.
- [ ] AK-37: Angenommen das Neu-Hashen wird mitten in einer Portion durch einen Neustart unterbrochen, wenn der nächste Abgleich läuft, dann setzt das Neu-Hashen an der unterbrochenen Stelle fort.
- [ ] AK-38: Angenommen der Dienst läuft, wenn ein Abgleich bzw. ein vollständiges Neu-Hashen über die Schnittstelle angefordert wird, dann läuft er sofort, und das Ergebnis trägt die Art „auf Abruf“.
- [ ] AK-39: Angenommen mehrere Abgleiche über 31 Tage (Zeit im Test vorgestellt), wenn die Ergebnisse abgerufen werden, dann sind mindestens die der letzten 30 Tage mit Zeitpunkt, Dauer, Art, Status und Lücken je Ebene abrufbar; je Abgleich steht ein Eintrag im Log.

### Störungen
- [ ] AK-40: Angenommen ein laufender Neuaufbau, wenn PROJ-115 (Register/Repo) nicht erreichbar ist, dann steht der Lauf auf `wartet` mit Grund, gibt keine neuen Quellen frei und setzt nach Rückkehr selbstständig fort.
- [ ] AK-41: Angenommen ein laufender Abgleich, wenn PROJ-115 nicht erreichbar wird, dann bricht er ab, speichert ein Ergebnis `unvollständig` mit Grund und hat nichts repariert, was nach dem Ausfall gefunden worden wäre.
- [ ] AK-42: Angenommen ein überwachter Ordner ist nicht lesbar bzw. leer, wenn ein Abgleich läuft, dann wird keiner seiner Fundorte als fehlend gemeldet, und das Ergebnis nennt den übersprungenen Ordner.
- [ ] AK-43: Angenommen eine Datei ist beim Neu-Hashen nicht lesbar, wenn der Abgleich läuft, dann wird sie gemeldet, nichts an ihrer Quelle geändert, und der nächste Durchlauf versucht es erneut.

### Betrieb
- [ ] AK-44: Angenommen der Dienst, wenn man ihn von außerhalb des Docker-Netzes (über nginx) aufrufen will, dann ist er nicht erreichbar; es gibt keine nginx-Route.
- [ ] AK-45: Angenommen der neue Dienst läuft, wenn das alte System arbeitet, dann laufen die alten n8n-Workflows unverändert, und der Dienst schreibt weder nach Weaviate noch in Redis-Schlüssel des alten Systems; Originale auf dem NAS werden nie verändert, verschoben oder gelöscht.
- [ ] AK-46: Angenommen ein Schema-Skript (falls nötig), wenn es auf einer frischen Wegwerf-DB und auf einer DB mit bestehendem Phase-4-Schema angewendet wird, dann laufen beide ohne Fehler.

### Live-Tests nach Deploy
- [ ] AK-47 (Live-Test nach Deploy): Angenommen der echte Bestand, wenn der erste nächtliche Abgleich gelaufen ist, dann liegt ein Ergebnis `vollständig` vor; alle gemeldeten Lücken sind erklärbar (oder repariert), und es gibt keine stille Lücke.
- [ ] AK-48 (Live-Test nach Deploy): Angenommen ein Neuaufbau ab `database` über alle Dokumente, wenn er läuft, dann zeigt der Fortschritt plausible Zahlen und Restzeit, eine währenddessen abgelegte neue Datei ist in ≤ 15 Minuten in der DB, und der Lauf endet als `abgeschlossen` mit anschließendem Abgleich.
- [ ] AK-49 (Live-Test nach Deploy): Angenommen ein Neuaufbau ab `classify` über eine kleine Art bzw. Stichprobe, wenn er läuft, dann bleibt der Chat bedienbar, und Pausieren, Fortsetzen und Abbrechen verhalten sich wie beschrieben.

## Edge Cases
- EC-1: Quelle wird während eines Laufs `deleted` → sie wird nicht (mehr) freigegeben und zählt im Fortschritt als ausgenommen; kein Fehler.
- EC-2: Hand-Korrektur an einer Quelle, die gerade im Lauf ist → normaler Vorrang der Hand-Korrektur (PROJ-115), `manual` geschützt; die Quelle zählt im Lauf trotzdem genau einmal.
- EC-3: Quelle des Laufs ist zusätzlich durch Normalbetrieb fällig (z. B. Inhaltsänderung) → wird nur einmal verarbeitet und im Lauf als erledigt gezählt, sobald die Stufen durch sind.
- EC-4: Lauf mit 0 Quellen im Umfang (z. B. Art ohne Quellen) → endet sofort als `abgeschlossen` mit 0, Abgleich läuft trotzdem.
- EC-5: Quelle bleibt im Lauf dauerhaft `failed` (noch nicht `failed_permanent`, wartet auf Backoff) → Lauf bleibt `läuft`, bis sie `done` oder `failed_permanent` ist; Fortschritt zeigt sie als fehlgeschlagen.
- EC-6: Neuaufbau und nächtlicher Abgleich gleichzeitig → beides läuft; Quellen offen im Lauf zählen nicht als Lücke auf Ebene 3; Reparaturen des Abgleichs an Quellen im Lauf sind trotzdem erlaubt.
- EC-7: Quell-Markdown fehlt und die Quelle ist gerade im Lauf → Abgleich repariert sie (Wiederherstellung), der Lauf zählt sie normal weiter.
- EC-8: Ein überwachter Ordner wird zwischen zwei Abgleichen deaktiviert → seine Dateien werden auf Ebene 1 nicht geprüft; seine eingefrorenen Fundorte gelten nicht als Lücke (PROJ-116).
- EC-9: Neu-Hashen findet eine Datei, deren neuer Hash einer anderen Quelle gehört → Regel 3 aus PROJ-116 (Pfad wandert, alte Quelle ggf. `deleted`).
- EC-10: Sehr große Datei (mehrere GB) beim Neu-Hashen → wird vollständig gehasht oder, wenn die Portionsgrenze erreicht ist, in der nächsten Nacht; kein Abbruch mit Fehler.
- EC-11: Redis-Neustart während eines Laufs → keine Auswirkung, Lauf- und Freigabezustand kommen aus PostgreSQL bzw. dem Register.
- EC-12: Zwei Abgleiche auf Abruf kurz hintereinander → der zweite wird abgelehnt, solange der erste läuft, mit Hinweis darauf.
- EC-13: Stufen-Dienst einer Stufe läuft gar nicht (z. B. gestoppt) → Lauf hängt nicht still: Fortschritt zeigt die Stufe mit offenen Quellen und Durchsatz 0, Restzeit unbekannt.

## Technische Anforderungen
- Testbar ohne GPU und ohne Produktivsysteme: temporäre Ordner als NAS, Wegwerf-Postgres/Redis, PROJ-115 mit temporärem Git-Repo, LLM-Gateway gemockt.
- Zustände von Läufen, Freigaben, Hash-Zyklus und Abgleich-Ergebnisse überstehen Neustarts (nicht nur in Redis).
- Quell-Markdowns und Stufenzustände nur über PROJ-115 ändern, nie direkt im Repo schreiben.
- Fortschritts-Abruf < 200 ms bei 50.000 Quellen im Lauf, ohne Zugriff auf NAS oder Repo, Daten höchstens 5 s alt.
- Konfigurierbar: Drosselung je Stufe, Log-Intervall, Zeitpunkt des nächtlichen Abgleichs, Hash-Portion je Nacht (Zeit/Datenmenge), Hash-Zyklus (Standard 30 Tage), Grenze „auffällig lange `pending`“ (Standard 24 h), Schwelle der Sicherung gegen Massenreparatur (Standard 5 %); neue Variablen nur als Platzhalter in `.env.example`.
- Schnittstelle nur intern im Docker-Netz, keine nginx-Route.
- Keine neue Queue-/Event-Infrastruktur.
- Keine echten Pfade, Hostnamen oder personenbezogenen Daten im Code oder in Testdaten.

## Offene Fragen
- Keine

## Product Decisions
- Neuaufbau als benannter, vom Admin gestarteter Lauf mit wählbarem Umfang (Startstufe + optional Art) statt eines einzelnen „Alles neu“-Knopfs: OCR und LLM laufen nur, wo nötig (2026-11-24)
- PROJ-120 setzt nur Stufen gedrosselt auf `pending`, die bestehenden Stufen-Dienste arbeiten ab: keine doppelte Stufen-Logik (2026-11-24)
- Startstufe schließt alle folgenden Stufen ein: jede Stufe baut auf der vorigen auf, sonst bleibt z. B. die DB veraltet (2026-11-24)
- Momentaufnahme beim Start; `failed_permanent` inklusive (Zähler 0); gelöschte, gesperrte und `skipped` ausgenommen und gezählt (2026-11-24)
- Normalbetrieb und Chat haben Vorrang, Drosselung je Stufe, kein Zeitfenster: Aktualitätsziel bleibt, der Lauf wird nicht unnötig lang (2026-11-24)
- Pausieren/Abbrechen ohne Zurückrollen, höchstens ein Lauf gleichzeitig: jeder Zwischenstand je Quelle ist konsistent (2026-11-24)
- Vier Abgleich-Ebenen (NAS ↔ Register inkl. Neu-Hashen, Register ↔ Repo, Stufen, Register ↔ DB); Mails, RAG, Wiki ergänzen ihre Features (2026-11-24)
- Abgleich nächtlich nach dem PROJ-116-Nachtlauf, Neu-Hashen rollierend in Portionen (Zyklus 30 Tage), beides auch auf Abruf: NAS wird nie stundenlang voll belastet (2026-11-24)
- Automatische Reparatur nur, wo eindeutig und verlustfrei; Löschen/Entfernen von Fundorten und Markdowns ohne Registereintrag nur melden; Sicherung gegen Massenreparatur (5 %) (2026-11-24)
- Schnittstelle schon jetzt vollständig für PROJ-122 (ein Abruf je Ansicht, häufiges Abfragen tragbar, Steuerung), damit PROJ-122 PROJ-120 nicht erweitern muss; Refresh-Zeit stellt die Oberfläche ein (2026-11-24)
- Keine aktive Benachrichtigung; Sichtbarkeit über Log, Schnittstelle und später PROJ-122 (2026-11-24)
