# PROJ-123: Mail-Import in den ETL

**Erstellt:** 2026-11-26
**Phase:** 4.2

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

## Abhängigkeiten
- Benötigt: PROJ-115 (Quelle-der-Wahrheit-Repo + Quellen-Register) — Art `email`, Fundorte „Postfach + Message-ID“, Ablage `emails/<JJJJ>/<MM>/<id>-<slug>.md`, Stufen und Zustände, Retry/Backoff, `manual`-Schutz, Sammel-Commits
- Benötigt: PROJ-116 (Datei-Erkennung) — Regeln für `deleted` (Markdown nach `deleted/`, Reaktivierung, 20-%-Grenze), die hier sinngemäß für Mails gelten
- Benötigt: PROJ-121 (Rollenmodell Haushalt) — Postfächer sind für alle `admin`/`haushalt` sichtbar, Verwaltung nur `admin`
- Benötigt: PROJ-111 (LLM-Gateway mit Prioritäten, Altbestand) — Kategorisierung als Hintergrundlast
- Ändert: PROJ-120 (Neuaufbau + Vollständigkeitsabgleich) — zwei neue Abgleich-Ebenen „IMAP ↔ Register“ und „Register ↔ Mail-Archiv“; Neuaufbau mit Art `email` erzeugt Mail-Markdowns aus dem Archiv
- Ändert: PROJ-117 (Text-Extraktion) — keine inhaltliche Änderung; die Stufe `extract` für `kind: email` übernimmt PROJ-123 (PROJ-117 fasst `email` weiterhin nicht an)
- Grundlage für: PROJ-124 (Mail-Anhänge als Quelldokumente), PROJ-126 (Vorschaubilder), PROJ-127 (RAG-Index), PROJ-128 (Such-Tools), PROJ-129 (Wiki-Ingest), PROJ-143 (Mail-Benachrichtigungen)

## Überblick
PROJ-123 holt die Mails aller konfigurierten IMAP-Postfächer in den neuen ETL:

1. **Import:** Neue Mails aus `INBOX` und dem Gesendet-Ordner werden ab dem Startdatum des Postfachs nur lesend vom Server geholt. Jede Mail wird als `*.eml` im **Mail-Archiv** abgelegt, also auf dem NAS, nicht im Git-Repo. Die echten Anhänge sind dabei aus der `.eml` ausgelagert: Sie liegen als einzelne Dateien daneben, und die `.eml` verweist per Link auf sie. Die Mail wird als Quelle `kind: email` im Register angelegt.
2. **Mail-Markdown:** Aus der archivierten `.eml` entsteht die Quell-Markdown. Das Frontmatter enthält die Mail-Felder, der Inhaltsteil den Mailtext als Markdown und die Links auf die Anhänge. Dafür ist kein LLM nötig.
3. **Kategorie und Zusammenfassung:** Eine LLM-Stufe setzt `category` (Wichtig/Werbung/Social/Spam) und eine kurze deutsche `summary`. Sie läuft als Hintergrundlast.
4. **Abgleich:** Jede Nacht wird je Postfach und Ordner mit dem Server abgeglichen. Mails, die dort verschwunden sind, werden `deleted`. Das Archiv bleibt dabei erhalten.

PROJ-123 **ersetzt** die n8n-Workflows `alice-mail-sync`, `alice-mail-attachment-processor`, `alice-mail-attachment-backfill` und `alice-mail-reconcile`. Sie werden mit dem Deploy deaktiviert, es gibt keinen Parallelbetrieb. Bis PROJ-127/128 gibt es keine Mail-Suche über neue Mails im Chat. Das ist bewusst in Kauf genommen.

Die Anhänge werden in PROJ-123 nur abgelegt. Als Quelldokumente laufen sie erst mit PROJ-124 durch die Pipeline.

Das Feature hat keine neue Oberfläche. Der bestehende Settings-Tab „E-Mail-Postfächer“ zeigt weiter Status, letzte Synchronisierung, letzten Fehler und die Anzahl importierter Mails; diese Werte pflegt künftig PROJ-123. Getestet wird mit einem IMAP-Test-Server bzw. -Mock, Wegwerf-Postgres/Redis, PROJ-115 mit temporärem Git-Repo, einem temporären Ordner als Mail-Archiv und einem gemockten LLM.

## User Stories
- Als Haushaltsmitglied möchte ich jede Mail aus Posteingang und Gesendet als lesbare Markdown-Datei in der Quelle der Wahrheit finden, damit Alice später Fragen zu Mails mit Quellenangabe beantworten kann.
- Als Haushaltsmitglied möchte ich, dass Mails auch dann in Alice erhalten bleiben, wenn ich sie im Postfach lösche, damit ich Speicherplatz beim Mailanbieter sparen kann, ohne Wissen zu verlieren.
- Als Haushaltsmitglied möchte ich die Anhänge einer Mail als eigene Dateien neben der Mail finden, damit sie später wie jedes andere Dokument verarbeitet werden können (PROJ-124).
- Als Haushaltsmitglied möchte ich an jeder Mail eine Kategorie (Wichtig/Werbung/Social/Spam) und eine kurze Zusammenfassung sehen, damit ich und Alice Wichtiges von Werbung unterscheiden können.
- Als Admin möchte ich im Settings-Tab sehen, ob ein Postfach erreichbar ist und wann zuletzt importiert wurde, damit ich Zugangsprobleme schnell bemerke.
- Als Admin möchte ich die gesamte Mail-Historie ab dem Startdatum ohne Eingriff importieren lassen, ohne dass Chat und Sprache dabei langsamer werden.
- Als Admin möchte ich die Mail-Markdowns jederzeit aus dem Archiv neu erzeugen können, auch ohne Verbindung zum Mailserver.

## Fachliches Modell

### Was importiert wird
- **Postfächer:** alle Einträge in der bestehenden Postfach-Verwaltung (Host, Zugangsdaten, Startdatum, Sync-Intervall). Es gibt keine zweite Passwortablage. Die Passwörter liegen weiter verschlüsselt vor und werden mit demselben Schlüssel entschlüsselt wie bisher.
- **Ordner:** `INBOX` und der Gesendet-Ordner des Postfachs. Der Gesendet-Ordner wird über die IMAP-Kennzeichnung für gesendete Mails erkannt (z. B. bei Gmail der lokalisierte Ordner „Gesendet“). Fehlt diese Kennzeichnung, wird ein konfigurierbarer Ordnername verwendet.
- **Nie importiert:** Spam, Papierkorb, Entwürfe, „Alle Nachrichten“ und alle anderen Ordner bzw. Labels.
- **Zeitraum:** Mails ab dem Startdatum des Postfachs. Ohne Startdatum werden nur Mails importiert, die nach dem ersten Import eingehen.
- **Takt:** je Postfach im eingestellten Sync-Intervall (Standard 15 min).
- **Nur lesend:** Der Import setzt keine Flags, auch nicht „gelesen“. Er verschiebt nichts und löscht nichts auf dem Server.

### Identität einer Mail
- Eine Mail ist **eine Quelle**, erkannt an ihrer Message-ID, unabhängig von Postfach und Ordner. Liegt dieselbe Mail in `INBOX` und Gesendet (z. B. an sich selbst geschickt) oder in zwei Postfächern, gibt es eine Quelle mit mehreren Fundorten.
- Ein **Fundort** ist Postfach + Ordner + IMAP-UID (mit Message-ID).
- Mails ohne Message-ID werden an einem Fingerabdruck aus Absender, Datum, Betreff und Inhalt erkannt.

### Mail-Archiv
- Das Archiv liegt in einem eigenen NAS-Ordner (Standard `/mnt/nas/ai/mail/`, konfigurierbar). Es liegt außerhalb des Git-Repos der Quelle der Wahrheit und außerhalb der überwachten DMS-Ordner.
- Struktur: `<Postfach>/<JJJJ>/<MM>/<id>.eml`, die Anhänge in `<Postfach>/<JJJJ>/<MM>/<id>.attachments/<Dateiname>`. `<JJJJ>/<MM>` ist das Mail-Datum, `<id>` die Quell-`id`. Der Postfach-Teil ist dateinamentauglich und stabil, auch wenn der Anzeigename des Postfachs geändert wird.
- Die `.eml` ist die vollständige Original-Mail (alle Header, Text- und HTML-Teil, eingebettete Bilder). Nur die **echten Anhänge** sind entfernt und durch Verweise auf die abgelegten Dateien ersetzt. Die `.eml` bleibt mit einem üblichen Mailprogramm lesbar.
- Bei Mails, die in mehreren Postfächern liegen, wird die `.eml` nur einmal abgelegt, im Postfach des ersten Fundorts.
- Das Archiv ist das **Original** einer Mail. Was einmal abgelegt ist, wird von PROJ-123 nie gelöscht oder überschrieben.

### Echte Anhänge und eingebettete Bilder
- **Echter Anhang:** jeder Teil der Mail mit Dateinamen, der nicht im HTML-Text per `cid:` eingebettet ist. Dazu gehören auch weitergeleitete Mails als Anhang (`message/rfc822`). Sie werden unverändert als `.eml`-Datei abgelegt.
- **Eingebettete Bilder** (per `cid:` im HTML referenziert, z. B. Logos, Signaturen) werden nicht ausgelagert und nicht in `attachments` aufgeführt. Sie bleiben in der archivierten `.eml` enthalten.
- Es gibt keine Größengrenze für Anhänge. Gespeichert wird alles.
- Gleicher Dateiname mehrfach in einer Mail: Ab dem zweiten wird ein Suffix angehängt (`rechnung.pdf`, `rechnung-2.pdf`). Ungültige Zeichen im Dateinamen werden ersetzt, kodierte Dateinamen (z. B. mit Umlauten) werden korrekt dekodiert.

### Mail-Markdown
**Frontmatter:** das Basisschema aus PROJ-115 plus die folgenden Felder.

| Feld | Inhalt |
|---|---|
| `title` | Betreff (Startwert; leerer Betreff → „(ohne Betreff)“) |
| `from` | Name und Adresse |
| `to`, `cc` | Listen aus Name und Adresse |
| `bcc` | nur, wenn in der Mail vorhanden (gesendete Mails) |
| `date` | Mail-Datum |
| `message_id`, `in_reply_to`, `references` | für Threads |
| `locations` | Postfach + Ordner + UID je Fundort |
| `archive` | Pfad der `.eml` im Mail-Archiv |
| `attachments` | Liste der echten Anhänge mit Dateiname, MIME-Typ, Größe und Pfad im Archiv. Die Quell-`id` je Anhang trägt PROJ-124 nach |
| `category` | `important` / `promotion` / `social` / `spam` (leer bis zur Kategorisierung) |
| `summary` | kurze deutsche Zusammenfassung, 2–3 Sätze (leer bis zur Kategorisierung) |
| `language` | Sprache des Mailtexts, ohne LLM erkannt; leer bei zu wenig Text |

**Inhaltsteil:**
- `# <Betreff>`, darunter Von, An, Cc und Datum in lesbarer Form.
- **Mailtext:** Der Text-Teil wird bevorzugt. Gibt es nur einen HTML-Teil, wird er in Markdown umgewandelt. Links bleiben erhalten; Bilder, Tracking-Pixel, Styles und Skripte fallen weg.
- **Keine Kürzung:** Der Mailtext wird vollständig übernommen, einschließlich zitiertem Verlauf (`>`).
- **Anhänge:** Abschnitt „Anhänge“ mit einem Link je echtem Anhang auf die Datei im Archiv (Dateiname, Typ, Größe). Den Abschnitt gibt es nur, wenn die Mail Anhänge hat.
- Zeichenkodierungen werden korrekt dekodiert (Header und Text). Bei falsch deklarierter Kodierung wird eine Rückfall-Kodierung verwendet, statt mit Fehler abzubrechen.
- Steht `content` oder ein Feld in `manual`, wird es nicht überschrieben (PROJ-115).

### Stufen für `kind: email`
| Stufe | Bedeutung für Mails |
|---|---|
| `detect` | Mail auf dem Server gefunden, im Archiv abgelegt (inkl. Anhänge), Quelle/Fundort im Register |
| `extract` | Mail-Markdown aus der archivierten `.eml` erzeugt (ohne LLM, ohne IMAP) |
| `classify` | `category` und `summary` per LLM gesetzt |
| `database` | `skipped` (keine fachlichen Tabellen für Mails in PROJ-123) |
| `rag`, `wiki`, `thumbnail` | `pending` bzw. wie von PROJ-126/127/129 festgelegt; PROJ-123 bearbeitet sie nicht |

- Ändert sich der Inhalt der Mail-Markdown (neue Erzeugung, Hand-Korrektur), gelten die Regeln aus PROJ-115 für abhängige Stufen.

### Kategorisierung (Stufe `classify`)
- Das LLM bekommt Absender, Empfänger, Betreff und den Anfang des Mailtexts (Länge konfigurierbar) und liefert eine der vier Kategorien und eine Zusammenfassung.
- Der Aufruf geht über `alice-llm-gateway` als Hintergrundlast (niedrigste Priorität) und ausdrücklich ohne „Thinking“. Der Chat hat immer Vorrang.
- Liefert das LLM eine ungültige Kategorie oder unbrauchbare Antwort, gilt das als vorübergehender Fehler mit Backoff aus PROJ-115.
- Die Zusammenfassung ist immer deutsch, unabhängig von der Sprache der Mail (wie die Dokument-Zusammenfassung in PROJ-118).

### Abgleich mit dem Server (Nachtlauf)
- Jede Nacht werden je Postfach und Ordner alle UIDs auf dem Server mit den Fundorten im Register verglichen.
- **Verschwundene Fundorte** (gelöscht, in Papierkorb/Archiv/anderen Ordner verschoben) werden entfernt. Eine Mail ohne Fundort wird `deleted`: Die Markdown wandert nach `deleted/emails/…` und bekommt `deleted: <Zeitpunkt>`, wie bei PROJ-116.
- **Das Archiv bleibt:** `.eml` und Anhänge einer `deleted`-Mail werden nicht gelöscht.
- **Wieder aufgetaucht** (gleiche Message-ID, beliebiges Postfach/Ordner): Die Quelle wird mit derselben `id` reaktiviert, die Markdown wandert zurück, erledigte Stufen laufen nicht erneut.
- **Fehlende Mails** (auf dem Server ab Startdatum vorhanden, aber nicht im Register) werden nachgeholt.
- **Schutz gegen Massenverlust:** Je Postfach werden pro Nachtlauf höchstens 20 % (konfigurierbar) der bekannten Fundorte entfernt. Wird die Grenze überschritten, wird für dieses Postfach nichts entfernt, und der Lauf meldet es als blockiert.
- Ist ein Postfach nicht erreichbar oder liefert eine leere Ordnerliste, wird für dieses Postfach nichts entfernt.

### Postfach-Änderungen in den Settings
- **Neues Postfach:** wird beim nächsten Takt importiert, ab dem Startdatum.
- **Startdatum früher gesetzt:** Die fehlenden älteren Mails werden nachgeholt.
- **Startdatum später gesetzt:** Bereits importierte Mails bleiben, es wird nichts entfernt.
- **Postfach gelöscht:** Im nächsten Nachtlauf werden alle Fundorte dieses Postfachs entfernt. Mails ohne weiteren Fundort werden `deleted`. Die 20-%-Grenze gilt dafür nicht (bewusste Admin-Aktion). Das Archiv bleibt.
- **Zugangsdaten geändert:** Der nächste Takt nutzt die neuen.

### Status im Settings-Tab
- PROJ-123 pflegt je Postfach die Felder, die der Settings-Tab heute anzeigt: Status (aktiv / synchronisiert gerade / Fehler), Zeitpunkt der letzten erfolgreichen Synchronisierung, letzte Fehlermeldung und Anzahl importierter Mails.
- Der Fortschritt des Imports (bis zu welcher Mail je Ordner) wird so gespeichert, dass ein Neustart dort weitermacht.

### Fehlerarten
- **Postfach nicht erreichbar / Anmeldung abgelehnt / Zeitüberschreitung:** Postfach-Status „Fehler“ mit verständlicher Ursache (z. B. „Anmeldung abgelehnt“). Es gibt keinen Fehlversuch an einzelnen Mails. Der nächste Takt versucht es erneut, ohne sofortige Wiederholungsschleife.
- **Einzelne Mail nicht abrufbar** (Verbindungsabbruch mitten im Abruf): Sie wird beim nächsten Takt erneut versucht, die übrigen Mails laufen weiter.
- **Mail nicht zerlegbar** (kaputter MIME-Aufbau): Die Rohmail wird unverändert und vollständig als `.eml` archiviert, dann ohne Auslagern der Anhänge. Die Quelle wird angelegt, `extract` steht sofort auf `failed_permanent` mit verständlicher Ursache. Nichts geht still verloren.
- **Mail-Archiv nicht erreichbar:** Der Import pausiert ohne Fehlversuche und ohne Register-Änderungen und setzt nach Rückkehr selbstständig fort.
- **LLM nicht erreichbar:** Nur `classify` steht auf `failed` mit Backoff. Import und Markdown sind davon nicht betroffen.

### Erstimport und Last
- Der Erstimport, also die Historie ab dem Startdatum, läuft in Paketen begrenzter Größe (konfigurierbar) mit Sammel-Commits (PROJ-115) und ist nach einem Neustart fortsetzbar.
- Neue Mails haben Vorrang vor der Historie: Während eines laufenden Erstimports kommt eine neu eingegangene Mail innerhalb eines Takts in die Quelle der Wahrheit.
- Höchstens eine Verbindung je Postfach gleichzeitig. Der Import selbst nutzt keinen LLM-Slot.

### Neuaufbau und Vollständigkeitsabgleich (Erweiterung PROJ-120)
- **Neuaufbau** mit Art `email` ab `extract` erzeugt die Mail-Markdowns aus den archivierten `.eml` neu, ohne Verbindung zum Mailserver. `deleted`-Mails sind wie bei PROJ-120 ausgenommen. `manual` bleibt geschützt.
- **Neue Abgleich-Ebene IMAP ↔ Register:** Jede Mail in `INBOX`/Gesendet ab dem Startdatum hat eine Quelle oder einen sichtbaren Fehlerstatus. Fehlende werden nachgeholt.
- **Neue Abgleich-Ebene Register ↔ Mail-Archiv:** Jede Mail-Quelle hat ihre `.eml`, und jede in `attachments` aufgeführte Datei ist im Archiv vorhanden. Fehlt eine Archivdatei und ist die Mail noch auf dem Server, wird sie neu abgelegt. Sonst wird die Lücke gemeldet.
- Beide Ebenen erscheinen in der Zusammenfassung des Abgleichs (und damit in PROJ-122) mit Zahlen und Liste der Lücken.

### Abschaltung des alten Mail-Imports
- Mit dem Deploy werden `alice-mail-sync`, `alice-mail-attachment-processor`, `alice-mail-attachment-backfill` und `alice-mail-reconcile` deaktiviert.
- **Bleiben unverändert in Betrieb:**
  - `alice-mail-api` und der Container `alice-mail-reader` für die Postfach-Verwaltung in den Settings (Verschlüsseln, Verbindungstest), bis PROJ-140
  - `alice-mail-tools`, der nur noch auf dem eingefrorenen Altbestand sucht, bis PROJ-128
- **Bleiben liegen und werden in PROJ-142 entfernt:** die alte Weaviate-Collection `Email`, die Redis-Queue für Anhänge und die alten Anhangsordner `/mnt/nas/ai/<Typ>/`.
- Die proaktive Chat-Benachrichtigung bei „Wichtig“-Mails entfällt ersatzlos (eigener Roadmap-Eintrag PROJ-143).

## Außerhalb des Umfangs
- Anhänge als Quelldokumente durch die Pipeline (Extraktion, Klassifizierung, Rückverweis `parents`) → PROJ-124
- Vorschaubilder für Mails → PROJ-126
- RAG-Index, Mail-Suche und Mail-Details für den Agenten → PROJ-127, PROJ-128
- Wiki-Pflege aus Mails → PROJ-129
- Proaktive Benachrichtigungen bei wichtigen Mails → PROJ-143 (Roadmap)
- Fachliche DB-Tabellen für Mails (Stufe `database` ist `skipped`); ob die Such-Tools strukturierte Mail-Metadaten in PostgreSQL brauchen, entscheidet PROJ-127/128
- Weitere IMAP-Ordner/Labels, frei wählbare Ordnerliste je Postfach
- Schreibende IMAP-Aktionen (gelesen markieren, verschieben, löschen, senden, antworten)
- Änderungen an der Postfach-Verwaltung in den Settings (Formular, Dialoge, `alice-mail-api`) → PROJ-140
- Löschen der alten Weaviate-Collection `Email`, der Redis-Keys und der alten Anhangsordner `/mnt/nas/ai/<Typ>/` → PROJ-142
- Übernahme alter Kategorien/Zusammenfassungen aus Weaviate (alles wird neu erzeugt)
- OAuth-Anmeldung bei Mailanbietern (weiter Benutzername + Passwort)
- Gesonderte Verarbeitung eingebetteter Bilder (`cid:`)

## Akzeptanzkriterien

### Import
- [ ] AK-1: Angenommen ein Postfach mit Startdatum und 3 Mails in `INBOX` und 2 im Gesendet-Ordner ab diesem Datum sowie Mails in Spam, Papierkorb, Entwürfe und einem weiteren Ordner, wenn der Import läuft, dann gibt es genau 5 Quellen `kind: email` mit je einer Mail-Markdown unter `emails/<JJJJ>/<MM>/`, und die Mails der übrigen Ordner werden nicht importiert.
- [ ] AK-2: Angenommen Mails vor dem Startdatum, wenn der Import läuft, dann werden sie nicht importiert. Ein Postfach ohne Startdatum importiert nur Mails, die nach dem ersten Import eingehen.
- [ ] AK-3: Angenommen ein Postfach, dessen Gesendet-Ordner einen lokalisierten Namen hat und über die IMAP-Kennzeichnung für gesendete Mails markiert ist, wenn der Import läuft, dann werden dessen Mails importiert. Ohne Kennzeichnung wird der konfigurierte Ordnername verwendet.
- [ ] AK-4: Angenommen der Import läuft, wenn man danach die Flags der Mails auf dem Test-Server prüft, dann sind sie unverändert (insbesondere nicht „gelesen“), und keine Mail wurde verschoben oder gelöscht.
- [ ] AK-5: Angenommen ein Postfach mit Sync-Intervall 15 min, wenn eine neue Mail eingeht, dann steht sie spätestens nach dem nächsten Takt als Quelle mit Mail-Markdown im Repo.
- [ ] AK-6: Angenommen ein erneuter Import ohne neue Mails, wenn er läuft, dann entstehen keine neuen Quellen, keine Commits und keine Archivdateien.
- [ ] AK-7: Angenommen dieselbe Mail (gleiche Message-ID) liegt in `INBOX` und Gesendet bzw. in zwei Postfächern, wenn der Import läuft, dann gibt es eine Quelle mit zwei Fundorten, eine Mail-Markdown und eine `.eml` im Archiv.
- [ ] AK-8: Angenommen zwei Mails ohne Message-ID mit unterschiedlichem Inhalt und eine dritte, identisch zur ersten, in einem anderen Ordner, wenn der Import läuft, dann gibt es zwei Quellen, die dritte ist ein weiterer Fundort der ersten.
- [ ] AK-9: Angenommen zwei laufende Instanzen des Dienstes, wenn dasselbe Postfach fällig ist, dann wird jede Mail nur einmal importiert und archiviert.

### Mail-Archiv und Anhänge
- [ ] AK-10: Angenommen eine Mail mit zwei PDF-Anhängen, wenn sie importiert wird, dann liegen `<Postfach>/<JJJJ>/<MM>/<id>.eml` und beide PDFs unter `<id>.attachments/` im Archiv. Die Anhangsdateien sind byte-gleich mit den Anhängen der Original-Mail.
- [ ] AK-11: Angenommen dieselbe Mail, wenn man die archivierte `.eml` mit einem Standard-Mail-Parser öffnet, dann enthält sie alle Header sowie Text- und HTML-Teil, aber keine Binärdaten der beiden PDFs, stattdessen je einen Verweis auf die abgelegte Datei.
- [ ] AK-12: Angenommen eine HTML-Mail mit zwei per `cid:` eingebetteten Bildern (Logo, Signatur) und einem echten Bild-Anhang, wenn sie importiert wird, dann wird nur der echte Anhang ausgelagert und in `attachments` aufgeführt. Die eingebetteten Bilder bleiben in der `.eml` und erscheinen nicht in `attachments`.
- [ ] AK-13: Angenommen eine Mail mit einer weitergeleiteten Mail als Anhang (`message/rfc822`), wenn sie importiert wird, dann liegt die weitergeleitete Mail unverändert als `.eml`-Datei unter `<id>.attachments/` und ist in `attachments` aufgeführt.
- [ ] AK-14: Angenommen eine Mail mit zwei Anhängen namens `rechnung.pdf` und einem Anhang mit kodiertem Umlaut-Dateinamen, wenn sie importiert wird, dann heißen die Dateien `rechnung.pdf`, `rechnung-2.pdf` und der Umlaut-Name korrekt dekodiert.
- [ ] AK-15: Angenommen ein Anhang über 100 MB, wenn die Mail importiert wird, dann wird er vollständig abgelegt.
- [ ] AK-16: Angenommen eine bereits archivierte Mail, wenn sie erneut importiert oder neu aufgebaut wird, dann werden `.eml` und Anhangsdateien nicht überschrieben.

### Mail-Markdown
- [ ] AK-17: Angenommen eine importierte Mail, wenn man das Frontmatter liest, dann enthält es das Basisschema aus PROJ-115 und `from`, `to`, `cc`, `date`, `message_id`, `in_reply_to`, `references`, `locations` (Postfach + Ordner + UID), `archive` und `attachments` (Dateiname, MIME-Typ, Größe, Archivpfad). `bcc` gibt es nur, wenn die Mail es enthält. Verarbeitungszustand, Fehler oder Retry-Zähler stehen nicht darin.
- [ ] AK-18: Angenommen eine Mail mit Text- und HTML-Teil, wenn die Markdown erzeugt wird, dann enthält der Inhaltsteil Überschrift `# <Betreff>`, Von/An/Cc/Datum und den Text-Teil vollständig.
- [ ] AK-19: Angenommen eine reine HTML-Mail mit Links, Tabelle, Bildern, Tracking-Pixel, Style- und Script-Blöcken, wenn die Markdown erzeugt wird, dann ist der Text als Markdown mit funktionierenden Links enthalten, ohne Bilder, Tracking-Pixel, CSS oder Skript-Code.
- [ ] AK-20: Angenommen eine Mail mit über 50.000 Zeichen Text und zitiertem Verlauf, wenn die Markdown erzeugt wird, dann ist der gesamte Text einschließlich Zitaten ohne Kürzung enthalten.
- [ ] AK-21: Angenommen eine Mail mit Anhängen, wenn die Markdown erzeugt wird, dann gibt es einen Abschnitt „Anhänge“ mit einem Link je echtem Anhang auf die Datei im Archiv. Eine Mail ohne Anhänge hat keinen solchen Abschnitt.
- [ ] AK-22: Angenommen Mails mit kodierten Headern (Umlaute im Betreff/Absender), mit ISO-8859-1- und mit falsch deklarierter Kodierung, wenn die Markdown erzeugt wird, dann stehen Umlaute korrekt bzw. lesbar darin, und keine Mail scheitert an der Kodierung.
- [ ] AK-23: Angenommen eine Mail ohne Betreff, wenn sie importiert wird, dann lautet `title` „(ohne Betreff)“, und der Dateiname ist gültig.
- [ ] AK-24: Angenommen ein Betreff mit Zeichen, die YAML/Markdown stören (Doppelpunkt, Anführungszeichen, `---`), wenn die Markdown erzeugt wird, dann ist das Frontmatter gültig, und der Betreff steht unverändert in `title`.
- [ ] AK-25: Angenommen ein deutscher und ein englischer Mailtext, wenn die Markdown erzeugt wird, dann steht `language` auf `de` bzw. `en`, ohne LLM. Bei sehr kurzem Text bleibt es leer.
- [ ] AK-26: Angenommen `content` oder `title` steht in `manual`, wenn die Markdown erneut erzeugt wird, dann bleiben diese unverändert.
- [ ] AK-27: Angenommen eine importierte Mail, wenn man das Register liest, dann steht `detect` und `extract` auf `done`, `classify` auf `pending` und `database` auf `skipped`. PROJ-117 übernimmt die Quelle nicht.

### Kategorisierung
- [ ] AK-28: Angenommen eine Mail mit `classify` auf `pending` und ein LLM-Mock, der „Werbung“ und eine Zusammenfassung liefert, wenn die Stufe läuft, dann steht `category: promotion` und die Zusammenfassung in `summary`, `classify` steht auf `done`, und es gibt einen Commit „classify: <id> <title>“.
- [ ] AK-29: Angenommen die Stufe `classify` ruft das LLM, wenn man den Aufruf am Gateway-Mock prüft, dann läuft er mit Hintergrund-Priorität und ohne Thinking, und der Mailtext ist auf die konfigurierte Länge begrenzt.
- [ ] AK-30: Angenommen ein englischer Mailtext, wenn er kategorisiert wird, dann wird die Zusammenfassung auf Deutsch angefordert.
- [ ] AK-31: Angenommen der LLM-Mock liefert eine unbekannte Kategorie bzw. ist nicht erreichbar, wenn die Stufe läuft, dann steht `classify` auf `failed` mit Fehlermeldung und Backoff nach PROJ-115. Die Mail-Markdown ist im Übrigen unverändert und vollständig.
- [ ] AK-32: Angenommen `category` steht in `manual`, wenn die Stufe erneut läuft, dann bleibt die Kategorie unverändert, `summary` wird aktualisiert.

### Abgleich und Löschen
- [ ] AK-33: Angenommen eine importierte Mail wird auf dem Server gelöscht, wenn der Nachtlauf läuft, dann wird ihr Fundort entfernt, die Quelle ist `deleted`, die Markdown liegt unter `deleted/emails/…` mit `deleted: <Zeitpunkt>`, und `.eml` sowie Anhänge liegen weiter unverändert im Archiv.
- [ ] AK-34: Angenommen eine Mail liegt in `INBOX` und Gesendet und wird nur aus `INBOX` entfernt, wenn der Nachtlauf läuft, dann wird nur dieser Fundort entfernt, und die Quelle bleibt aktiv.
- [ ] AK-35: Angenommen eine `deleted`-Mail wird auf dem Server wiederhergestellt (gleiche Message-ID), wenn der Import bzw. Nachtlauf läuft, dann ist die Quelle mit derselben `id` wieder aktiv, die Markdown liegt wieder an ihrem regulären Platz, und erledigte Stufen laufen nicht erneut.
- [ ] AK-36: Angenommen in einem Postfach fehlen auf dem Server mehr als 20 % der bekannten Fundorte, wenn der Nachtlauf läuft, dann wird für dieses Postfach nichts entfernt, und die Zusammenfassung meldet es als blockiert.
- [ ] AK-37: Angenommen ein Postfach ist beim Nachtlauf nicht erreichbar, wenn der Abgleich läuft, dann wird für dieses Postfach nichts entfernt.
- [ ] AK-38: Angenommen ein Postfach wird in den Settings gelöscht, wenn der Nachtlauf läuft, dann werden alle seine Fundorte entfernt (ohne 20-%-Grenze), Mails ohne weiteren Fundort sind `deleted`, und das Archiv bleibt unverändert.
- [ ] AK-39: Angenommen eine Mail ab Startdatum ist auf dem Server, aber nicht im Register (z. B. nach einem Ausfall), wenn der Nachtlauf läuft, dann wird sie nachgeholt.
- [ ] AK-40: Angenommen das Startdatum eines Postfachs wird früher gesetzt, wenn der nächste Takt läuft, dann werden die älteren Mails nachgeholt. Wird es später gesetzt, bleiben bereits importierte Mails erhalten.

### Fehler
- [ ] AK-41: Angenommen der IMAP-Server lehnt die Anmeldung ab bzw. ist nicht erreichbar, wenn der Takt läuft, dann zeigt der Postfach-Status „Fehler“ mit verständlicher Ursache. Es entsteht kein Fehlversuch an Mail-Quellen und kein Register-Eintrag. Nach Rückkehr bzw. Korrektur der Zugangsdaten läuft der Import ohne Eingriff weiter.
- [ ] AK-42: Angenommen eine Mail mit kaputtem MIME-Aufbau, wenn sie importiert wird, dann liegt die Rohmail vollständig als `.eml` im Archiv, die Quelle existiert, und `extract` steht sofort auf `failed_permanent` mit verständlicher Ursache. Die übrigen Mails laufen weiter.
- [ ] AK-43: Angenommen die Verbindung bricht mitten im Abruf ab, wenn der nächste Takt läuft, dann werden die fehlenden Mails nachgeholt, ohne Duplikate und ohne halbe Archivdateien.
- [ ] AK-44: Angenommen das Mail-Archiv ist nicht beschreibbar bzw. nicht erreichbar, wenn der Import läuft, dann pausiert er mit Warnung im Log, ohne Register-Änderungen, und setzt nach Rückkehr selbstständig fort.
- [ ] AK-45: Angenommen der Dienst wird mitten im Import beendet, wenn er neu startet, dann gibt es keine halbe `.eml`, keine halbe Markdown und keinen halben Commit, und er setzt an der richtigen Stelle fort.

### Erstimport und Last
- [ ] AK-46: Angenommen ein Postfach mit 2.000 Mails ab Startdatum, wenn der Erstimport läuft, dann werden alle importiert, in Paketen der konfigurierten Größe und mit Sammel-Commits (höchstens 500 Dateien je Commit).
- [ ] AK-47: Angenommen ein laufender Erstimport, wenn eine neue Mail eingeht, dann ist sie spätestens nach dem nächsten Takt als Quelle vorhanden, auch wenn die Historie noch nicht fertig ist.
- [ ] AK-48: Angenommen der Import läuft, wenn man die Verbindungen zum Test-Server zählt, dann gibt es höchstens eine gleichzeitige Verbindung je Postfach.

### Settings-Tab
- [ ] AK-49: Angenommen ein erfolgreicher Takt, wenn ein Admin den Tab „E-Mail-Postfächer“ öffnet, dann zeigt das Postfach Status „aktiv“, den Zeitpunkt der letzten Synchronisierung und die Anzahl importierter Mails. Nach einem Fehler zeigt es „Fehler“ mit der Ursache.

### Neuaufbau und Vollständigkeitsabgleich
- [ ] AK-50: Angenommen importierte Mails und ein nicht erreichbarer IMAP-Server, wenn ein Neuaufbau mit Art `email` ab `extract` läuft, dann werden alle nicht gelöschten Mail-Markdowns aus dem Archiv neu erzeugt. Felder in `manual` bleiben erhalten, `classify` folgt wie in PROJ-120.
- [ ] AK-51: Angenommen eine Mail ab Startdatum auf dem Server ohne Quelle, wenn der Vollständigkeitsabgleich läuft, dann erscheint sie in der Ebene „IMAP ↔ Register“ und wird nachgeholt.
- [ ] AK-52: Angenommen eine Mail-Quelle, deren `.eml` oder eine Anhangsdatei im Archiv fehlt, wenn der Vollständigkeitsabgleich läuft, dann wird sie neu abgelegt, wenn die Mail noch auf dem Server ist, sonst als Lücke in der Ebene „Register ↔ Mail-Archiv“ gemeldet.
- [ ] AK-53: Angenommen der Abgleich ist gelaufen, wenn man die Zusammenfassung über die Schnittstelle von PROJ-120 abruft, dann enthält sie beide neuen Ebenen mit Zahlen und Liste der Lücken.

### Betrieb und Ablösung
- [ ] AK-54: Angenommen der Dienst, wenn man ihn von außerhalb des Docker-Netzes (über nginx) aufrufen will, dann ist er nicht erreichbar. Es gibt keine nginx-Route.
- [ ] AK-55: Angenommen Logs und Fehlermeldungen des Dienstes, wenn man sie durchsucht, dann enthalten sie keine Passwörter (auch nicht verschlüsselt) und keine Mailtexte.
- [ ] AK-56: Angenommen die Deploy-Schritte des PRs, wenn man sie liest, dann deaktivieren sie `alice-mail-sync`, `alice-mail-attachment-processor`, `alice-mail-attachment-backfill` und `alice-mail-reconcile`, und `alice-mail-api`, `alice-mail-tools` sowie `alice-mail-reader` bleiben unverändert.
- [ ] AK-57 (Live-Test nach Deploy): Angenommen das produktive Postfach, wenn der Erstimport abgeschlossen ist, dann haben alle Mails aus `INBOX` und Gesendet ab Startdatum eine Mail-Markdown, die Anhänge liegen im Archiv, der Abgleich meldet keine Lücken, und Chat und Sprache waren während des Imports spürbar unverändert.
- [ ] AK-58 (Live-Test nach Deploy): Angenommen eine Testmail mit PDF-Anhang an das produktive Postfach, wenn sie eingeht, dann steht sie nach spätestens 15 min mit Anhang-Link in der Quelle der Wahrheit, und später mit plausibler Kategorie und Zusammenfassung.

## Edge Cases
- EC-1: Mail an sich selbst → liegt in `INBOX` und Gesendet → eine Quelle, zwei Fundorte (AK-7).
- EC-2: Gmail-Mail wird archiviert (verlässt `INBOX`, bleibt in „Alle Nachrichten“) → zählt als verschwunden, Quelle `deleted`, Archiv bleibt. Die Mail bleibt über die Quelle der Wahrheit auffindbar.
- EC-3: Gleiche Message-ID mit abweichendem Inhalt (seltene Fehlkonfiguration bei Absendern) → gilt als dieselbe Mail. Die erste archivierte Fassung bleibt maßgeblich, der Fall wird im Log vermerkt.
- EC-4: IMAP-UIDs eines Ordners werden vom Server neu vergeben (UIDVALIDITY ändert sich) → Fundorte werden über die Message-ID neu zugeordnet, ohne Massen-`deleted` und ohne Duplikate.
- EC-5: Mail mit Datum in der Zukunft oder ohne Datum → Ablage nach Empfangszeitpunkt auf dem Server, kein Fehler.
- EC-6: Sehr große Mail (z. B. 50 MB Anhänge) → wird vollständig abgelegt, blockiert andere Postfächer nicht.
- EC-7: Anhang ohne Dateinamen, aber als Anhang gekennzeichnet → bekommt einen erzeugten Namen aus MIME-Typ und laufender Nummer.
- EC-8: Verschlüsselte oder signierte Mail (S/MIME, PGP) → wird archiviert, Inhalt so weit lesbar übernommen. Verschlüsselter Inhalt wird nicht entschlüsselt, die Markdown vermerkt „verschlüsselt“.
- EC-9: Kalendereinladung (`text/calendar`) → zählt als echter Anhang.
- EC-10: Postfach-Anzeigename wird geändert → Archivpfad und Fundorte bleiben stabil.
- EC-11: Hand-Korrektur der Kategorie in der Markdown → steht in `manual`, wird nie überschrieben (AK-32).
- EC-12: Restart von Redis → keine Auswirkung, Fortschritt und Zustand kommen aus PostgreSQL bzw. dem Register.
- EC-13: Zwei Postfächer mit demselben IMAP-Konto → jede Mail eine Quelle mit Fundorten in beiden Postfächern (AK-7).

## Technische Anforderungen
- Testbar ohne echten Mailserver, ohne NAS und ohne GPU: IMAP-Test-Server oder -Mock mit Testpostfächern (inkl. Gesendet-Kennzeichnung, UIDVALIDITY-Wechsel, Anmeldefehler), temporärer Ordner als Mail-Archiv, Wegwerf-Postgres/Redis, PROJ-115 mit temporärem Git-Repo, LLM-Gateway gemockt.
- Postfach-Stammdaten und verschlüsselte Passwörter aus der bestehenden Postfach-Tabelle. Keine zweite Passwortablage, derselbe Schlüssel wie der bisherige `alice-mail-reader`. Passwörter erscheinen nie in Logs, Fehlermeldungen oder Register.
- Schreiben der Quell-Markdowns ausschließlich über PROJ-115, nie direkt ins Repo.
- Mail-Archiv-Pfad, Gesendet-Ordner-Fallback, Paketgröße, 20-%-Grenze, Textlänge für die Kategorisierung konfigurierbar; neue Variablen nur als Platzhalter in `.env.example`.
- LLM-Aufrufe nur über `alice-llm-gateway` mit Hintergrund-Priorität und ausdrücklich ohne Thinking.
- Schnittstelle nur intern im Docker-Netz, keine nginx-Route.
- Keine neue Queue-/Event-Infrastruktur.
- Keine Änderung an `alice-mail-api`, `alice-mail-tools`, `alice-mail-reader` und am Settings-Frontend.
- Keine echten Hostnamen, Adressen, Mailinhalte oder personenbezogenen Daten im Code oder in Testdaten.

## Offene Fragen
- Keine

## Product Decisions
- Mail-Archiv unter `/mnt/nas/ai/mail/` statt im Git-Repo: `.eml` und Anhänge sind Originale (wie PDFs) und gehören nicht ins Markdown-Repo. `/mnt/nas/ai` wird mit der Abschaltung des alten Anhang-Imports frei und wird von der Datei-Erkennung nicht überwacht. Der Unterordner `mail/` vermeidet Kollisionen mit den alten Typ-Ordnern, die PROJ-142 löscht (2026-11-26)
- Nur `INBOX` und Gesendet: Gesendete Mails sind für Fragen wie „Was habe ich geschrieben?“ wertvoll. Spam, Papierkorb, Entwürfe und „Alle Nachrichten“ bringen Duplikate oder Müll. Eine frei wählbare Ordnerliste ist nicht nötig (2026-11-26)
- Mail-Identität über die Message-ID, eine Quelle je Mail mit Fundorten je Postfach/Ordner: entspricht dem Quelle-/Fundort-Modell aus PROJ-115 (2026-11-26)
- Auf dem Server gelöschte Mails werden `deleted`, das Archiv bleibt: Löschen im Postfach (z. B. aus Platzgründen) darf in Alice kein Wissen vernichten. Gleiche Schutzregeln wie PROJ-116 (20-%-Grenze, Reaktivierung) (2026-11-26)
- Aufbau der Mail-Markdown: Mail-Felder im Frontmatter, Text-Teil bevorzugt, HTML zu Markdown, zitierter Verlauf ohne Kürzung, Anhänge als Links (2026-11-26)
- Import und Markdown ohne LLM, `category`/`summary` in eigener LLM-Stufe als Hintergrundlast: Die Quelle der Wahrheit spiegelt das Postfach schnell und unabhängig vom LLM, der Chat bleibt flüssig (2026-11-26)
- Kategorie-Werte englisch (`important`/`promotion`/`social`/`spam`) wegen der Konvention „produktintern Englisch“; die Anzeige übersetzt. Zusammenfassung immer deutsch, wie bei Dokumenten (PROJ-118) (2026-11-26)
- Alter Mail-Import wird mit dem Deploy abgeschaltet, kein Parallelbetrieb: Die bisherigen Mail-Antworten im Chat sind ohnehin unbrauchbar. Doppelte Arbeit lohnt nicht, auf Mail-Anfragen wird bis PROJ-127/128 verzichtet. `alice-mail-api`/`-reader` bleiben für die Settings bis PROJ-140, `alice-mail-tools` bis PROJ-128 (2026-11-26)
- PROJ-123 pflegt die Statusfelder des Postfachs, damit der Settings-Tab ohne Frontend-Änderung aussagekräftig bleibt (2026-11-26)
- Proaktive Benachrichtigungen bei „Wichtig“-Mails entfallen ersatzlos, eigener Roadmap-Eintrag PROJ-143: Das ist ein Nutzer-Feature, kein ETL (2026-11-26)
- Erstimport als Massenlauf mit Sammel-Commits, fortsetzbar; neue Mails haben Vorrang vor der Historie (2026-11-26)
- Neuaufbau erzeugt Mail-Markdowns aus dem Archiv, nicht vom IMAP-Server: Gelöschte Mails bleiben erhalten, kein Mailserver nötig. Deshalb ist `extract` für Mails die Erzeugung aus der `.eml` (2026-11-26)
- PROJ-120 bekommt die Abgleich-Ebenen „IMAP ↔ Register“ und „Register ↔ Mail-Archiv“ (2026-11-26)
- Echter Anhang = Teil mit Dateinamen, der nicht per `cid:` eingebettet ist. Eingebettete Bilder bleiben nur in der `.eml`, keine Größengrenze: Logos und Signaturen sollen nicht tausendfach durch PROJ-124/125 laufen. Der seltene eingebettete Scan bleibt über die `.eml` erhalten (2026-11-26)
- Stufe `database` für Mails `skipped`: Ob die Such-Tools strukturierte Mail-Metadaten in PostgreSQL brauchen, entscheidet PROJ-127/128 (2026-11-26)
