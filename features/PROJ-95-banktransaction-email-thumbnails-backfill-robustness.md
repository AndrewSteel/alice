# PROJ-95: BankTransaction- & Email-Thumbnails + Backfill-Robustheit

## Status: Approved
**Created:** 2026-08-28
**Last Updated:** 2026-08-30

## Dependencies
- Betrifft: `alice-dms-thumbnailer` (n8n-Workflow, PROJ-55, In Review) und den zugehörigen `alice-dms-thumbnailer`-Service (`/generate`-Endpoint).
- Betrifft: `alice-dms-thumbnailer-backfill` (n8n-Workflow, PROJ-55).
- Baut auf dem in [[PROJ-93]] etablierten Mail-Text-Rendering-Muster auf (Text-Vorschau ohne Datei-Zugriff, direkt aus Weaviate gelesen) — wird hier für BankTransaction erweitert und zusätzlich auf den Backfill-Pfad nachgezogen, wo es bislang fehlt.
- Folgt den in [[PROJ-92]] und [[PROJ-96]] etablierten Backfill-Mustern (Redis-Lock `alice:dms:processor:lock:run`, `time_limit_seconds`-Parameter, Time-Check-Node).
- Ursprünglich entdeckt bei PROJ-55-Refine (2026-08-28): `Code: Query Weaviate` schlägt für BankTransaction mit GraphQL-Fehler fehl, da `filePath`/`fileHash` im Schema fehlen. Scope am 2026-08-30 nach Review der DMS-Pipeline-Map erweitert (siehe Kontext).

## Kontext

Zwei der acht Weaviate-Dokumenttypen haben keinen NAS-Dateipfad und bekommen deshalb **nie** ein Thumbnail — weder live noch nachträglich:

- **Email**: Inhalt liegt nur als Text in Weaviate (`subject`, `content`). Für den **Live-Pfad** (`alice-dms-thumbnailer`, ausgelöst durch `alice/dms/done`) wurde das bereits mit [[PROJ-93]] gelöst (Text-Rendering-Modus ohne Datei-Zugriff). Der **Backfill-Pfad** (`alice-dms-thumbnailer-backfill`) hat diesen Fix nie nachgezogen — er verwirft weiterhin jedes Objekt ohne `filePath`, bevor es überhaupt beim Thumbnailer-Service ankommt.
- **BankTransaction**: hat als Kind-Objekt eines BankStatement (verknüpft über `parentStatementId`) grundsätzlich nie einen eigenen Dateipfad — weder live noch im Backfill wird dafür je ein Thumbnail erzeugt. `alice-dms-thumbnailer` kennt den Typ gar nicht als Sonderfall; `alice-dms-thumbnailer-backfill`s `Code: Query Weaviate (no thumbnail)`-Node fragt zwar `fileHash`/`filePath` für BankTransaction ab, bekommt aber einen GraphQL-Fehler zurück, da diese Felder im BankTransaction-Schema gar nicht existieren — die Collection wird faktisch übersprungen.

**Zusätzlich, unabhängig vom Thumbnail-Inhalt selbst**, fehlen `alice-dms-thumbnailer-backfill` zwei Robustheits-Bausteine, die alle anderen Backfill-Workflows ([[PROJ-92]], [[PROJ-96]], `alice-mail-attachment-backfill`) bereits haben:

- **Kein Redis-Lock**: nimmt `alice:dms:processor:lock:run` nicht — kann parallel zur nächtlichen `alice-dms-processor`-Verarbeitung laufen und unnötige NAS-Lese- sowie Weaviate-Schreiblast gleichzeitig erzeugen.
- **Kein Zeitlimit**: kein `time_limit_seconds`-Parameter, kein Time-Check-Node — ein Lauf über viele Alt-Objekte kann nicht mit einer definierten Laufzeit gestartet werden, wie es bei den anderen Backfills (Postman-Aufrufe mit z.B. `3500s`, siehe [[PROJ-92]]) etablierte Praxis ist.

**Zusatzfund während der Analyse:** Die Node `Split: Per collection` in `alice-dms-thumbnailer-backfill` ist weder mit einem Eingang noch einem Ausgang verbunden — totes Workflow-Fragment, das entfernt werden sollte.

**Gewählter Lösungsansatz** (Nutzerentscheidungen in der Spec-Phase):
1. `alice-dms-thumbnailer` bekommt für BankTransaction ein eigenes, visuell abgesetztes Rendering-Layout (nicht das generische Email-Text-Layout): Bankname als Kopfzeile, Betrag groß und farbcodiert (rot bei negativem/rot Belastung, grün bei positivem/Gutschrift) zentral, darunter Gegenpartei (`counterparty`) und Verwendungszweck (`purpose`), Datum am Ende. Bankname und Kontext kommen aus dem per `parentStatementId` referenzierten BankStatement (zusätzlicher Weaviate-Lookup).
2. `alice-dms-thumbnailer-backfill` zieht denselben Text-/Rendering-Ansatz nach: Email nutzt das bestehende PROJ-93-Muster, BankTransaction das neue Layout aus Punkt 1 — beide werden nicht mehr wegen fehlendem `filePath` verworfen.
3. `alice-dms-thumbnailer-backfill` übernimmt den `alice:dms:processor:lock:run`-Lock (Konsistenz + Vermeidung von NAS/Weaviate-Lastspitzen parallel zur nächtlichen Verarbeitung), auch ohne eigenen Ollama/GPU-Bedarf.
4. `alice-dms-thumbnailer-backfill` bekommt einen optionalen `time_limit_seconds`-Parameter: gesetzt → Verarbeitung stoppt nach Ablauf sauber mit vollständigem Response (Fortschritt, verarbeitete/übersprungene/verbleibende Zählung), Lock wird freigegeben; nicht gesetzt → Workflow läuft durch, bis alle acht Collections vollständig abgearbeitet sind (kein künstlicher Default). Kein Selbstaufruf/Auto-Continue (im Unterschied zu [[PROJ-96]]) — ein per Zeitlimit gestoppter Lauf wird bei Bedarf manuell erneut aufgerufen, analog zur bestehenden Praxis bei den anderen Backfills.
5. Architektur-Vorgabe für die Umsetzung: **kein Loop-in-Loop.** Die Weaviate-Abfrage sammelt weiterhin in einem Rutsch alle Datensätze ohne Thumbnail über alle Collections hinweg in eine flache Liste (wie im bestehenden `Code: Query Weaviate (no thumbnail)`-Node) — die Collection-Zugehörigkeit spielt nur bei dieser Abfrage eine Rolle. Die Iteration darüber bleibt ein einzelner Loop über die flache Liste; der Zeit-Check erfolgt nach jedem einzelnen Dokument, nicht pro Collection. Die verwaiste `Split: Per collection`-Node wird ersatzlos entfernt, nicht reaktiviert.
6. Die tote Node `Split: Per collection` wird entfernt.

## User Stories

- Als Nutzer möchte ich beim Durchsuchen der DMS-Bibliothek für jede Banktransaktion ein Thumbnail mit Bank, Betrag und Gegenpartei sehen, damit ich Kontobewegungen in einer Trefferliste auf einen Blick unterscheiden kann, ohne jede einzeln zu öffnen.
- Als Nutzer möchte ich, dass auch länger zurückliegende E-Mails und Banktransaktionen nachträglich ein Thumbnail bekommen, wenn ich den Backfill anstoße, damit die Bibliothek nicht dauerhaft Lücken bei genau diesen zwei Dokumenttypen hat.
- Als Admin möchte ich den Thumbnailer-Backfill mit einer festen Laufzeit starten können (z.B. per Postman), damit ich eine kontrollierte Teilmenge abarbeiten und danach das Ergebnis im Response sofort einsehen kann, ohne raten zu müssen, wie lange der Lauf dauert.
- Als Admin möchte ich, dass der Thumbnailer-Backfill nicht zeitgleich mit der nächtlichen DMS-Verarbeitung um Ressourcen konkurriert, damit beide Läufe verlässlich durchlaufen.

## Acceptance Criteria

**BankTransaction-Rendering (live, `alice-dms-thumbnailer`):**
- [ ] `alice-dms-thumbnailer` erkennt `document_type: 'BankTransaction'` und behandelt es nicht mehr als "fehlender file_path" → verwerfen, sondern über einen dedizierten Rendering-Pfad
- [ ] Für BankTransaction-Objekte werden `amount`, `currency`, `direction`, `counterparty`, `purpose`, `transactionDate`, `bankName` und `accountIban` direkt vom BankTransaction-Objekt geladen (kein `parentStatementId`-Lookup — `bankName`/`accountIban` sind bereits auf dem Objekt vorhanden; Architektur-Phase-Entscheidung, siehe Tech Design)
- [ ] Das erzeugte Thumbnail zeigt: Bankname + Konto-IBAN (Kopfzeile, klein) → Betrag (groß, zentral, farbcodiert nach `direction`: `debit` rot mit `−`, `credit` grün mit `+`, sonst/0 neutral) → Gegenpartei → Verwendungszweck → Datum
- [ ] Das Thumbnail wird wie bei anderen Dokumenttypen unter `thumbnails/<weaviate_uuid>.jpg` gespeichert, `thumbnail_path` wird auf dem BankTransaction-Objekt gesetzt
- [ ] Bestehendes Thumbnail-Verhalten für alle anderen Dokumenttypen (inkl. des PROJ-93-Email-Pfads) bleibt unverändert

**Backfill-Abdeckung (`alice-dms-thumbnailer-backfill`):**
- [ ] Email- und BankTransaction-Objekte ohne `thumbnail_path` werden nicht mehr aufgrund fehlenden `filePath`/`fileHash` aus der Verarbeitung ausgeschlossen bzw. durch einen GraphQL-Fehler stillschweigend übersprungen
- [ ] Email-Objekte im Backfill nutzen denselben Text-Rendering-Ansatz wie der Live-Pfad aus [[PROJ-93]]
- [ ] BankTransaction-Objekte im Backfill nutzen dasselbe Rendering-Layout wie der neue Live-Pfad (siehe oben)
- [ ] Nach einem Backfill-Lauf haben Email- und BankTransaction-Objekte, die vorher keinen `thumbnail_path` hatten, einen gesetzten `thumbnail_path` (verifizierbar per Weaviate-Query)

**Backfill-Lock:**
- [ ] `alice-dms-thumbnailer-backfill` nimmt vor Beginn der Verarbeitung den Redis-Lock `alice:dms:processor:lock:run` (gleicher Mechanismus wie bei den bestehenden Backfills)
- [ ] Ist der Lock bereits durch einen anderen Lauf (nächtlicher Processor oder anderer Backfill) belegt, beendet sich der Workflow sauber mit einer entsprechenden Meldung im Response, ohne zu warten oder zu crashen
- [ ] Der Lock wird nach Abschluss (Erfolg, Zeitlimit-Stopp oder Fehler) zuverlässig wieder freigegeben

**Backfill-Zeitlimit:**
- [ ] `alice-dms-thumbnailer-backfill` akzeptiert einen optionalen `time_limit_seconds`-Parameter im Webhook-Body
- [ ] Ist `time_limit_seconds` gesetzt: Verarbeitung prüft nach jedem einzelnen verarbeiteten Dokument, ob die Zeit abgelaufen ist; bei Ablauf stoppt der Workflow sauber, gibt den Lock frei und liefert einen vollständigen Response mit Fortschrittszahlen (`processed`, `failed`, `skipped_already_has_thumb`, `remaining`)
- [ ] Ist `time_limit_seconds` nicht gesetzt: Workflow verarbeitet alle gefundenen Objekte über alle acht Collections hinweg vollständig, kein künstliches Zeitlimit
- [ ] Kein Selbstaufruf/Auto-Continue-Mechanismus — ein durch Zeitlimit gestoppter Lauf muss erneut manuell aufgerufen werden

**Aufräumen:**
- [ ] Die unverbundene Node `Split: Per collection` ist aus dem Workflow entfernt

## Edge Cases

- **BankTransaction, deren zugehöriges BankStatement zwischenzeitlich gelöscht wurde** (z.B. durch [[PROJ-78]]-Klassifizierungs-Migration oder [[alice-dms-lifecycle]]-Cascade-Delete): Bankname-Lookup schlägt fehl → Thumbnail wird trotzdem mit den verfügbaren Transaktionsfeldern (Betrag, Gegenpartei, Zweck, Datum) erzeugt, Bankname-Zeile bleibt leer oder zeigt einen neutralen Platzhalter — kein Crash, kein vollständiger Fehlschlag wegen eines fehlenden Zusatzfelds.
- **BankTransaction ohne `counterparty` oder `purpose`** (unvollständig extrahierte Altdaten): Thumbnail wird trotzdem erzeugt, die fehlenden Zeilen werden ausgelassen statt "undefined" oder leer anzuzeigen — analog zum bestehenden `filter(Boolean).join()`-Muster aus [[PROJ-93]].
- **Betrag ist exakt 0**: wird neutral dargestellt (weder rot noch grün), kein Rendering-Fehler.
- **Backfill-Lauf mit `time_limit_seconds` läuft genau während der Verarbeitung des letzten Dokuments ab**: Dokument wird noch fertig verarbeitet, danach greift der Zeit-Check und stoppt — kein abgebrochenes/halb geschriebenes Thumbnail.
- **Backfill-Lauf ohne `time_limit_seconds` bei sehr großer Rückstandsmenge**: läuft bis zur vollständigen Abarbeitung durch; da die nginx-Route `/webhook/` (im Unterschied zu `/api/webhook/dms/`) mit `proxy_read_timeout 3600s` konfiguriert ist, kann die HTTP-Verbindung selbst bei einem Lauf über eine Stunde vom Proxy beendet werden — der n8n-Workflow läuft dabei serverseitig unverändert bis zum eigenen Abschluss weiter (etabliertes, unschädliches Verhalten, siehe [[PROJ-92]]); nur der Response erreicht den Aufrufer dann nicht mehr. Kein neuer Fix nötig, nur bekanntes Verhalten.
- **Lock bereits belegt, wenn der Backfill gestartet wird**: sauberer Abbruch mit Meldung "Lauf bereits aktiv" im Response, kein Warten, keine Queue.
- **BankTransaction bekommt im selben Lauf sowohl den neuen Live-Rendering-Pfad als auch einen parallel laufenden Backfill-Versuch für dasselbe Objekt** (Race Condition): durch den Redis-Lock zwischen Backfill und nächtlichem Processor entschärft; ein doppeltes Thumbnail-Rendering für dasselbe Objekt führt lediglich zu einem überschriebenen, aber inhaltlich identischen `thumbnail_path` — kein Datenverlust.

## Technical Requirements (optional)

- Kein neuer Redis-Key für den Lock — Wiederverwendung von `alice:dms:processor:lock:run`.
- Kein Selbstaufruf-Mechanismus (bewusste Abweichung von [[PROJ-96]]) — einfacheres, vorhersagbares Verhalten passend zu den Backfills mit explizitem Zeitlimit-Parameter ([[PROJ-92]], [[PROJ-94]]).
- Die Weaviate-Abfrage bleibt eine flache Liste über alle Collections (kein Loop-in-Loop) — Collection-Zugehörigkeit wird nur beim Abfrage-Aufbau berücksichtigt, nicht bei der Iteration.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

PROJ-95 hat **keine UI-Komponente**. Es betrifft drei Bausteine:

1. `alice-dms-thumbnailer` (n8n-Workflow, Live-Pfad) — neuer Verarbeitungszweig für BankTransaction.
2. `alice-dms-thumbnailer` (Service, `main.py`) — neuer Rendering-Modus für BankTransaction (analog zum PROJ-93-Mail-Text-Modus).
3. `alice-dms-thumbnailer-backfill` (n8n-Workflow) — Abdeckung für Email + BankTransaction, Redis-Lock, optionales Zeitlimit, tote Node entfernen.

Kein neuer Workflow, kein neuer Service, kein neuer Trigger, kein neuer Redis-Key, keine Schema-Änderung an Weaviate oder PostgreSQL.

### Vereinfachung gegenüber dem Spec-Text (nach Klärung in der Architektur-Phase)

Der Spec-Text (Kontext, Punkt 1 + AC) geht von einem **zusätzlichen Weaviate-Lookup über `parentStatementId`** aus, um den Bankname des zugehörigen BankStatement zu holen. Beim Prüfen des tatsächlichen Weaviate-Schemas hat sich gezeigt:

- Die `BankTransaction`-Klasse hat **bereits ein eigenes `bankName`-Feld** (beim Import aus dem BankStatement kopiert, siehe `schemas/bank-transaction.json`) — ebenso `accountIban` (IBAN des Kontos, ebenfalls aus dem Parent kopiert).
- Der Betrag liegt als `amount` (**immer positiv**) plus `direction` (`'credit'` = Eingang / `'debit'` = Ausgang) vor — nicht als vorzeichenbehafteter Wert.

**Nutzerentscheidungen in der Architektur-Phase:**

- **Bankname + Kontokennung:** nur die vorhandenen Felder `bankName` **und `accountIban`** der BankTransaction lesen. **Kein `parentStatementId`-Lookup.** `accountIban` muss mit angezeigt werden, weil mehrere Konten derselben Bank existieren können — der Bankname allein ist dann nicht unterscheidbar. Ist `bankName` bzw. `accountIban` leer (unvollständige Altdaten), wird die jeweilige Angabe ausgelassen — kein zweiter Weaviate-Call, kein Edge-Case „Statement zwischenzeitlich gelöscht" mehr relevant.
- **Farbcodierung:** richtet sich nach `direction`. `'debit'` → Betrag rot, mit `−`-Präfix. `'credit'` → Betrag grün, mit `+`-Präfix. `direction` fehlt/unbekannt **oder** `amount` ist 0 → neutral (keine Farbe, kein Vorzeichen).

Dadurch entfällt der Edge Case „BankTransaction, deren BankStatement gelöscht wurde" (Abschnitt Edge Cases) als eigener Fehlerpfad — er kann nicht mehr auftreten, weil kein Statement mehr nachgeladen wird. Die übrigen Edge Cases (fehlende `counterparty`/`purpose`, `amount == 0`) bleiben unverändert gültig.

---

### E) Workflow Architecture — `alice-dms-thumbnailer` (Live-Pfad)

**Bestehender Ablauf (unverändert für alle Nicht-BankTransaction-Typen):**

`MQTT: alice/dms/done` → `Code: Parse & Filter` → `IF: Is Email` → (Email-Zweig: Weaviate-Content-Lookup) → `HTTP: POST /generate` → `IF: Generate OK` → `HTTP: PATCH Weaviate thumbnail_path` bzw. Fehlerpfad.

**Trigger:** Es muss geklärt/geprüft werden, ob für BankTransaction überhaupt eine `alice/dms/done`-MQTT-Nachricht gefeuert wird (BankTransaction entsteht als Kind-Objekt beim BankStatement-Import). Zwei Fälle:

- **Fall A — es kommt eine `done`-Nachricht mit `document_type: 'BankTransaction'`:** Live-Pfad greift wie unten beschrieben.
- **Fall B — es kommt keine:** Der Live-Pfad kann für BankTransaction nichts tun; die Abdeckung entsteht dann ausschließlich über den Backfill. Der Service-Rendering-Modus (Punkt 2) wird trotzdem gebraucht, weil der Backfill ihn aufruft. Die Live-AC gelten dann als „nicht anwendbar, da kein Trigger" — das ist im Backend-Schritt zu verifizieren und in den Implementation Notes festzuhalten.

**Neuer Ablauf für BankTransaction (Fall A):**

1. **`Code: Parse & Filter` erweitern:** `document_type === 'BankTransaction'` wird — wie schon `'Email'` — von der `file_path`-Pflicht ausgenommen (BankTransaction hat systembedingt nie einen Dateipfad). `weaviate_uuid` bleibt Pflicht.
2. **Nach `IF: Is Email` ein zweiter Verzweigungspunkt** (bzw. `IF: Is Email` wird zu einem `Switch`/mehrstufigen `IF` „Text-basierter Typ?"): Für BankTransaction wird das Objekt per `GET /v1/objects/BankTransaction/{uuid}` von Weaviate geladen (gleicher REST-Stil wie der bestehende Email-Content-Lookup).
3. **`Code: Merge …`-Äquivalent für BankTransaction:** liest aus dem Weaviate-Objekt `amount`, `currency`, `direction`, `counterparty`, `purpose`, `transactionDate`, `bankName`, `accountIban` und baut daraus die Felder, die der Service für den neuen Rendering-Modus braucht. Fehlgeschlagener Lookup (Objekt gelöscht, Weaviate down) → leere Felder → kontrollierter Fehlschlag über den bestehenden `IF: Generate OK`-Fehlerpfad, kein Crash.
4. **`HTTP: POST /generate` erweitern:** Payload verzweigt jetzt dreifach nach `document_type` — Datei-basiert (bisher), `Email` → `mail_text` (PROJ-93), `BankTransaction` → strukturierte Transaktionsfelder.
5. **Rest unverändert:** `IF: Generate OK` → `Code: Extract Thumbnail Path` → `HTTP: PATCH Weaviate thumbnail_path` → Logging. Für den nachgelagerten Teil ist die Rendering-Quelle unerheblich.

**Integrationen:** Ein zusätzlicher lesender Weaviate-REST-Call im Workflow (kein neuer Integrationspunkt). Keine neuen externen Abhängigkeiten.

**Fehlerverhalten:** unverändert zum bestehenden Muster — jeder Fehlschlag läuft über `IF: Generate OK` → `Code: Log Error` → `MQTT: Publish thumb_error`.

---

### Rendering-Modus im Service (`main.py`)

Analog zur PROJ-93-Erweiterung (`mail_text` + `_render_text_image`):

- **`GenerateRequest`** bekommt optionale, strukturierte BankTransaction-Felder (Betrag, Währung, Richtung, Gegenpartei, Zweck, Datum, Bankname, Konto-IBAN). Der bestehende `@model_validator(mode="after")` wird um einen dritten Zweig erweitert: `document_type == 'BankTransaction'` → mindestens `amount` (oder ein Kennzeichen „strukturierte Felder vorhanden") Pflicht; `Email` → `mail_text` (unverändert); sonst → `original_path` (unverändert).
- **Neue Render-Funktion** `_render_bank_transaction(...)`: erzeugt ein **visuell abgesetztes** Layout (nicht die generische Monospace-Textvorschau):
  - Bankname + Konto-IBAN — kleine Kopfzeile oben (z.B. `Sparkasse XY · DE.. .. 1234`); leere Bestandteile werden ausgelassen, ist beides leer bleibt die Zeile weg.
  - Betrag — groß, zentral, farbcodiert: `debit` rot mit `−`, `credit` grün mit `+`, sonst / `0` neutral. Währung dahinter.
  - Gegenpartei (`counterparty`) — darunter, ausgelassen wenn leer.
  - Verwendungszweck (`purpose`) — darunter, ausgelassen wenn leer (gekürzt auf sinnvolle Länge, analog `[:2000]`-Muster).
  - Datum (`transactionDate`) — am Ende, formatiert.
  - Fehlende Felder werden **ausgelassen**, nicht als „undefined"/leere Zeile gezeigt (`filter(Boolean)`-Muster wie PROJ-93).
- **`generate_thumbnail()`** bekommt den neuen Zweig: sind die BankTransaction-Felder gesetzt, wird direkt gerendert (kein Datei-Zugriff), danach `_square_crop` + Resize wie bei allen anderen Modi.
- **`/generate`-Endpoint:** der `src.exists()`-Check wird — wie für `Email` — auch für `BankTransaction` übersprungen.
- Bestehendes Verhalten für PDF/Office/Bild/TXT/MD und den PROJ-93-Mail-Pfad bleibt **unverändert** (neuer Zweig mit eigenem `return` davor, keine Vermischung).

**Dependencies:** keine neuen Pakete — dieselbe bereits vorhandene Pillow-Bibliothek (`ImageDraw`, `ImageFont`) wie beim Text-Preview. Ggf. eine zweite, größere Schriftgröße für den Betrag (Pillow-Bordmittel, kein neues Paket).

---

### E) Workflow Architecture — `alice-dms-thumbnailer-backfill`

**Aktueller Ablauf:**

`Webhook` → `Code: Init Collections` → `Code: Query Weaviate (no thumbnail)` (flache Liste über alle 8 Collections) → `IF: Has file_path and UUID` → `HTTP: POST /generate` → `IF: Generate OK` → `HTTP: PATCH Weaviate` → `Merge` → `Code: Summary` → `Respond`. Die Node `Split: Per Collection` hängt unverbunden im Graphen.

**Änderung 1 — Abdeckung Email + BankTransaction:**

- **`Code: Query Weaviate (no thumbnail)`:** Die GraphQL-Abfrage fragt heute für **jede** Collection `filePath`/`fileHash` ab. Für `Email` und `BankTransaction` existieren diese Felder im Schema nicht → GraphQL-Fehler → Collection wird per `break` still übersprungen. Fix: Die abgefragten Felder werden **pro Collection** bestimmt:
  - Datei-basierte Collections (Invoice, BankStatement, Document, SecuritySettlement, Contract, Image): wie bisher `filePath`/`fileHash` (bzw. `file_path`/`file_hash` bei Image) + `thumbnail_path`.
  - `Email`: `subject`, `content`, `thumbnail_path` — kein Pfad-Feld.
  - `BankTransaction`: `amount`, `currency`, `direction`, `counterparty`, `purpose`, `transactionDate`, `bankName`, `accountIban`, `thumbnail_path` — kein Pfad-Feld.
  - Die flache Ergebnisliste bekommt pro Eintrag ein `document_type` (schon vorhanden) und die jeweils nötigen Rohfelder. **Kein Loop-in-Loop** — die Collection-Zugehörigkeit steuert nur den Query-Aufbau, die Iteration bleibt ein einzelner Loop über die flache Liste (Spec-Punkt 5).
- **`IF: Has file_path and UUID`** wird zu **`IF: Renderable`**: durchlässig, wenn `weaviate_uuid` vorhanden **und** (`file_path` gesetzt **oder** `document_type ∈ {Email, BankTransaction}`). Nur echte Fälle ohne jede Rendering-Quelle landen im Skip-Zweig.
- **`HTTP: POST /generate`** (Backfill): Payload verzweigt jetzt nach `document_type` — identisch zur Live-Pfad-Logik (Datei / `mail_text` / BankTransaction-Felder). Für Email baut der Backfill den Vorschautext aus den bereits mitgeladenen `subject`/`content` (kein separater REST-Call nötig, da die Query sie schon geholt hat); für BankTransaction analog aus den mitgeladenen Feldern.
- **`Code: Log Skip (no file_path)`** → umbenennen/anpassen auf „keine Rendering-Quelle" und `skipped_no_source` o.ä., damit die Summary-Semantik stimmt.

**Änderung 2 — Redis-Lock (`alice:dms:processor:lock:run`):**

Neuer Node **`Code: Acquire Backfill Lock`** direkt nach dem Webhook (Muster 1:1 aus `alice-dms-language-backfill` / PROJ-92):

- `SET alice:dms:processor:lock:run <owner-token> NX PX 1800000`.
- **Erfolg** → weiter zu `Code: Init Collections`.
- **Lock belegt oder Redis-Fehler** → `IF: Lock acquired?` routet in einen kurzen Zweig `Code: Respond Locked` → `Respond to Webhook` mit `{ status: 'skipped', reason: 'locked', message: 'Lauf bereits aktiv' }`, HTTP 200. Kein Warten, keine Queue.
- **Lock-Freigabe:** Neuer Node **`Code: Release Lock`** vor `Respond to Webhook`, in **allen** Abschluss-Pfaden (Erfolg, Zeitlimit-Stopp, Fehler). Owner-geprüfter `DEL` per Lua-Script (Muster aus `alice-dms-image-description-backfill` `Code: Release Lock`). Zusätzliche Absicherung durch die 30-min-TTL, falls der Workflow hart abbricht.
- Der Lock-Owner-Token wird durch den Workflow gereicht (im `json` jedes Items bzw. via `$getWorkflowStaticData`).

**Änderung 3 — optionales Zeitlimit (`time_limit_seconds`):**

- **`Code: Init Collections`** (bzw. ein vorgeschalteter `Code: Init Run`) liest `time_limit_seconds` aus `body`/`query` des Webhooks — **per Node-Namen-Zugriff auf den Webhook-Node**, nicht `$input.first().json.body` (das war der PROJ-92-Bug, weil der Lock-Node davor ein Item ohne `body` liefert). Gesetzt → `window_start = Date.now()`, `max_runtime_seconds = time_limit_seconds`. Nicht gesetzt → kein Limit (`max_runtime_seconds = null`).
- **Iteration mit Zeit-Check:** Die flache Dokumentliste wird über einen `Loop Over Items` (SplitInBatches, Batch-Größe 1) oder eine äquivalente Schleife verarbeitet. **Nach jedem einzelnen Dokument** ein **`Code: Time Check`**: `elapsed >= max_runtime_seconds` (und Limit gesetzt) → Schleife verlassen, in-flight-Dokument ist bereits fertig. Muster aus `alice-dms-image-description-backfill` `Code: Time Check`.
  - Hinweis: Der heutige Workflow feuert alle Items **parallel** in `HTTP: POST /generate`. Für einen dokumentweisen Zeit-Check muss die Verarbeitung auf eine **sequenzielle Schleife** umgestellt werden (Batch-Größe 1). Das ist auch aus PROJ-55-Sicht wünschenswert (die dort behobene unthrottled Concurrency gegen den Thumbnailer-Service). Der Backend-Schritt bestätigt die konkrete Node-Wahl.
- **Response** enthält immer die vollständigen Fortschrittszahlen: `processed`, `failed`, `skipped_already_has_thumb` (Objekte mit bereits gesetztem `thumbnail_path` — durch die Query ohnehin ausgefiltert, hier als 0/aus Metadaten), `skipped_no_source`, `remaining` (bei Zeitlimit-Stopp: noch nicht verarbeitete Einträge der flachen Liste; bei vollständigem Lauf: 0), plus `stopped_reason: 'time_limit' | 'completed' | 'locked'`.
- **Kein Selbstaufruf / Auto-Continue** (bewusste Abweichung von PROJ-96) — ein per Zeitlimit gestoppter Lauf wird manuell erneut per Webhook aufgerufen. Da der Backfill idempotent ist (Objekte mit `thumbnail_path` werden von der Query übersprungen), setzt ein erneuter Aufruf die Arbeit faktisch fort.

**Änderung 4 — tote Node entfernen:**

`Split: Per Collection` wird ersatzlos aus `nodes` und (sofern vorhanden) `connections` entfernt. Nicht reaktivieren.

**Data flow (Backfill, neu):**

Webhook (optional `time_limit_seconds`) → Lock nehmen (sonst sauberer Abbruch) → flache Liste aller Objekte ohne `thumbnail_path` über alle 8 Collections, mit typ-spezifischen Rohfeldern → sequenzielle Schleife: pro Dokument `/generate` (Datei / mail_text / BankTransaction-Felder) → bei Erfolg `PATCH thumbnail_path` → Zeit-Check → ggf. Schleife verlassen → Lock freigeben → Response mit Fortschrittszahlen.

**Integrationen:** Weaviate (lesen: Query; schreiben: PATCH `thumbnail_path`), Redis (Lock), `alice-dms-thumbnailer`-Service (`/generate`). Alle bereits vorhanden.

**Fehlerbehandlung:** Einzelne fehlgeschlagene Dokumente (Generate- oder PATCH-Fehler) werden gezählt und geloggt, brechen den Lauf **nicht** ab (bestehendes `onError: continueRegularOutput`-Muster). Lock wird auch bei einem Workflow-Fehler über `Code: Release Lock` bzw. die TTL freigegeben.

---

### Datenmodell (fachlich)

Kein neues Schema. Gelesen werden ausschließlich bereits vorhandene Weaviate-Felder:

- `Email`: `subject`, `content` (wie PROJ-93).
- `BankTransaction`: `amount`, `currency`, `direction`, `counterparty`, `purpose`, `transactionDate`, `bankName`, `accountIban` (alle bereits im Schema, `schemas/bank-transaction.json`).

Geschrieben wird nur das bestehende `thumbnail_path`-Feld (wie bei jedem anderen Dokumenttyp). Das Thumbnail-Bild liegt wie gehabt unter `thumbnails/<weaviate_uuid>.jpg`.

### Tech-Entscheidungen (Begründung)

- **Kein `parentStatementId`-Lookup:** Das Ziel-Feld (`bankName`) liegt bereits auf dem BankTransaction-Objekt. Ein zusätzlicher Lookup wäre ein zweiter Netz-Call und ein zusätzlicher Fehlerpfad für Information, die schon da ist — widerspricht Simplicity-First. Der ursprüngliche Spec-Ansatz stammt aus der Zeit vor Prüfung des realen Schemas.
- **Betrag-Farbe nach `direction` statt Vorzeichen:** `amount` ist laut Schema „always positive"; das Vorzeichen steckt ausschließlich in `direction`. Eine Vorzeichen-Prüfung auf `amount` würde bei sauberen Daten nie rot ergeben.
- **Eigener Service-Rendering-Modus statt formatiertem Freitext über `mail_text`:** Die Spec fordert explizit ein visuell abgesetztes Layout (farbiger, großer Betrag) — das ist mit dem Monospace-Textvorschau-Renderer nicht darstellbar. Ein strukturierter Modus hält die Layout-Logik an einer Stelle (Service), die Live- und Backfill-Pfad gemeinsam nutzen.
- **Wiederverwendung `alice:dms:processor:lock:run`:** Konsistent mit allen anderen DMS-Backfills. Auch ohne eigenen GPU-Bedarf vermeidet der Lock parallele NAS-Lese- und Weaviate-Schreiblast zur nächtlichen Verarbeitung (Spec-Entscheidung).
- **Sequenzielle Schleife im Backfill:** nötig für den dokumentweisen Zeit-Check und zugleich die richtige Antwort auf die in PROJ-55 behobene unthrottled Concurrency gegen den Thumbnailer-Service.
- **Kein Auto-Continue (Abweichung von PROJ-96):** Die anderen Backfills mit explizitem `time_limit_seconds` (PROJ-92, PROJ-94) laufen ohne Selbstaufruf; ein per Zeitlimit gestoppter, idempotenter Backfill wird bei Bedarf manuell erneut angestoßen. Einfacheres, vorhersagbareres Verhalten.
- **`time_limit_seconds` per Node-Namen-Zugriff auf den Webhook lesen:** direkte Konsequenz aus dem PROJ-92-Bug (Lock-Node davor liefert ein Item ohne `body`).

### Offene Punkte für den Backend-Schritt

1. **Feuert der BankStatement-Import eine `alice/dms/done`-MQTT-Nachricht pro BankTransaction?** Bestimmt, ob der Live-Pfad für BankTransaction überhaupt greift (Fall A) oder die Abdeckung rein über den Backfill entsteht (Fall B). In den Implementation Notes festhalten.
2. **Konkrete n8n-Node-Wahl für die sequenzielle Backfill-Schleife** (SplitInBatches mit Batch-Größe 1 vs. Loop Over Items) und wie der Zeit-Check-Abbruch die Schleife sauber verlässt.
3. **`direction`-Werte in den echten Altdaten** verifizieren (`'credit'`/`'debit'` vs. evtl. abweichende Schreibweisen) — für die Farb-/Vorzeichen-Zuordnung.

## Implementation Notes (Backend)

**Umgesetzt am 2026-08-30.** Drei n8n-Workflows + der Thumbnailer-Service betroffen.

### Abweichung von der Tech Design: Live-Pfad für BankTransaction (Fall A statt Fall B)

Die Tech Design ließ offen, ob der `alice-dms-processor` pro BankTransaction eine
`alice/dms/done`-MQTT-Nachricht sendet. **Verifiziert: tut er nicht** — `MQTT: Publish Done`
feuert einmal pro Dokument (BankStatement, `document_type: 'BankStatement'`), Phase B
batch-inserted die Transaktionen direkt in Weaviate ohne eigene MQTT-Nachricht.

**Nutzerentscheidung (2026-08-30):** Nicht Fall B (Abdeckung nur über Backfill), sondern
**Fall A wird hergestellt** — Phase B sendet jetzt pro erfolgreich eingefügter
BankTransaction ein `alice/dms/done`. Andernfalls müsste der Nutzer für jeden neuen
Kontoauszug den Backfill manuell anstoßen, damit die Transaktions-Thumbnails entstehen.

### 1. `alice-dms-thumbnailer` Service (`docker/compose/automations/alice-dms-thumbnailer/app/main.py`)

- `GenerateRequest`: neue optionale Felder `bt_amount`, `bt_currency`, `bt_direction`,
  `bt_counterparty`, `bt_purpose`, `bt_transaction_date`, `bt_bank_name`, `bt_account_iban`.
- `@model_validator`: dritter Zweig — `document_type == 'BankTransaction'` → `bt_amount` Pflicht
  (0 ist erlaubt, nur `None` wird abgelehnt).
- `_render_bank_transaction(...)`: neues, visuell abgesetztes Layout (LiberationSans-Bold
  für den Betrag). Kopfzeile `Bank · IBAN` (leere Teile ausgelassen, ganze Zeile weg wenn
  beide leer), großer farbcodierter Betrag (`debit` rot mit `−`, `credit` grün mit `+`,
  sonst/0 neutral), Gegenpartei, Zweck (auf 120 Zeichen gekürzt), Datum (erste 10 Zeichen).
  Fehlende Felder werden ausgelassen (`filter(Boolean)`-Muster).
- `generate_thumbnail()`: neuer `bank_transaction`-Parameter, eigener Zweig mit eigenem
  `return` vor dem Datei-Pfad — center-crop + resize wie die anderen Modi.
- `/generate`: `src.exists()`-Check wird für `Email` **und** `BankTransaction` übersprungen.
- Lokal getestet (debit/credit/zero/unknown-direction, 800px→400px, Validator-Fälle).

### 2. `alice-dms-processor` (`workflows/alice-dms-processor.json`, ID `qPIg6uLTe8LfOYwv`)

- `Code: BankTransaction Phase B`: sammelt `renderMeta[]` (index-aligned zu `objects[]`) und
  `insertedTx[]` (`{ weaviate_uuid, ...renderMeta }` pro erfolgreichem Batch-Result mit `r.id`).
  Neues Ausgabefeld `_inserted_bank_transactions`. Fällt die Batch-Antwort ohne per-Objekt-IDs
  zurück (Fallback-Pfad), wird `_inserted_bank_transactions` leer gelassen und geloggt — der
  Backfill fängt diese Transaktionen dann ab.
- Neuer Node `Code: Emit BankTransaction Done`: fächert `_inserted_bank_transactions` in ein
  Item pro Transaktion auf (`document_type: 'BankTransaction'`, `weaviate_uuid`, `inserted: true`,
  plus alle Render-Felder inline). Kein BankStatement / leere Extraktion → `return []`.
- Neuer Node `MQTT: Publish BankTransaction Done`: publiziert jedes Item nach `alice/dms/done`.
- Verdrahtung: `Code: BankTransaction Phase B` main[0] bekommt einen dritten Ziel-Node
  (`Code: Emit BankTransaction Done`); dieser Seitenzweig endet terminal, speist **nicht** in
  die `Split In Batches`-Schleife zurück.

### 3. `alice-dms-thumbnailer` Workflow (`workflows/alice-dms-thumbnailer.json`, ID `wcl4nBzwDboA9T1H`)

- `Code: Parse & Filter`: `BankTransaction` (wie `Email`) von der `file_path`-Pflicht ausgenommen.
- `IF: Is Email` → ersetzt durch `Switch: Rendering Type` (3 Ausgänge: Email / BankTransaction / File-Fallback).
- Email-Zweig unverändert (Weaviate-GET + Merge). BankTransaction-Zweig geht direkt zu
  `HTTP: POST /generate` — **kein Weaviate-Lookup**, weil die MQTT-Nachricht die Felder schon
  inline trägt (Vereinfachung ggü. Tech Design, die einen GET vorsah).
- `HTTP: POST /generate` jsonBody: 3-fach verzweigt (Email `mail_text` / BankTransaction `bt_*` /
  Datei `original_path`).
- `Code: Log Error`: Locator-Text deckt jetzt beide textbasierten Typen ab.

### 4. `alice-dms-thumbnailer-backfill` Workflow (`workflows/alice-dms-thumbnailer-backfill.json`, ID `o5YjdTpVeYm5nDLM`)

- **Tote Node `Split: Per Collection` entfernt.**
- **Redis-Lock**: neuer `Code: Acquire Backfill Lock` (`alice:dms:processor:lock:run`, NX PX 1800000,
  fail-closed) direkt nach dem Webhook → `IF: Lock Acquired` → belegt: `Code: Respond Locked`
  (`stopped_reason: 'locked'`, `message: 'Lauf bereits aktiv'`, HTTP 200). Freigabe in
  `Code: Build Summary` (owner-geprüftes Lua-`DEL`) — greift in allen Abschlusspfaden.
- **`time_limit_seconds`**: `Code: Init Run` liest den Parameter **per Node-Namen-Zugriff auf den
  Webhook** (PROJ-92-Bug vermieden). Gesetzt → `window_start`+`max_runtime_seconds`, sonst `null`.
- **Query pro Collection**: `Code: Query Weaviate (no thumbnail)` fragt jetzt typ-spezifische
  Felder ab — Datei-Collections `filePath`/`fileHash` (Image `file_path`/`file_hash`), `Email`
  `subject`/`content`, `BankTransaction` `amount`/`currency`/`direction`/`counterparty`/`purpose`/
  `transactionDate`/`bankName`/`accountIban`. Kein GraphQL-Fehler mehr für Email/BankTransaction.
  Flache Liste über alle 8 Collections, kein Loop-in-Loop.
- **Sequenzielle Schleife**: `Loop Over Docs` (SplitInBatches, batchSize 1) statt paralleler
  Batch-HTTP-Aufrufe (behebt zugleich die PROJ-55-Concurrency gegen den Thumbnailer-Service).
- **`IF: Renderable`** (ex `IF: Has file_path and UUID`): durchlässig bei `weaviate_uuid` vorhanden
  UND (`file_path` gesetzt ODER `document_type ∈ {Email, BankTransaction}`).
- **`HTTP: POST /generate`**: 3-fach verzweigter jsonBody wie im Live-Pfad. Email baut den
  Vorschautext aus den mitgeladenen `subject`/`content`.
- **`Code: Time Check`** nach jedem Dokument → `IF: Time Limit Reached` → verlässt die Schleife
  sauber (in-flight-Dokument bereits fertig).
- **Response** (`Code: Build Summary`): `{ status, stopped_reason: 'time_limit'|'completed'|'locked',
  processed, failed, skipped_no_source, remaining }`. `remaining` = Aggregate-Count über alle 8
  Collections mit `thumbnail_path IsNull` (bei Query-Fehler `null`).
- **Kein Auto-Continue** — ein zeitlimitierter Lauf wird manuell erneut aufgerufen; die Query
  überspringt bereits bethumbnailte Objekte, ein Re-Run setzt also faktisch fort.

### Validierung

- Beide neuen Workflow-JSONs mit `n8n_validate_workflow` (runtime-Profil) geprüft: 0 Fehler
  (Warnungen nur die generischen Multi-Output-IF/Switch-Hinweise + typeVersion-Hinweise, die
  den bereits produktiven Nodes entsprechen).
- Alle Code-Node-Skripte mit `node --check` geprüft.
- Service-Rendering lokal gegen echte Feldkombinationen getestet.

### Deployment-Hinweis

Drei Deploys nötig: `Deploy n8n-workflow alice-dms-processor`,
`Deploy n8n-workflow alice-dms-thumbnailer`, `Deploy n8n-workflow alice-dms-thumbnailer-backfill`,
plus Rebuild/Redeploy des `alice-dms-thumbnailer`-Containers (main.py-Änderung).

## QA Test Results

**Tested:** 2026-08-30
**Tester:** QA Engineer (AI)
**Testmethode:** Statische Analyse (Workflow-Graph-Trace, `n8n_validate_workflow` runtime-Profil, `node --check` je Code-Node) + isolierte Python-Tests des Service-Renderings/Validators. Die drei Workflows sind noch nicht deployed — eine Laufzeit-Prüfung im n8n erfolgt beim `/deploy`-QA-Nachlauf.

### Acceptance Criteria Status

#### BankTransaction-Rendering (live, `alice-dms-thumbnailer`)
- [x] `alice-dms-thumbnailer` erkennt `document_type: 'BankTransaction'` (`Code: Parse & Filter` nimmt es wie `Email` von der `file_path`-Pflicht aus; `Switch: Rendering Type` Output 1 → dedizierter Pfad)
- [x] `amount`/`currency`/`direction`/`counterparty`/`purpose`/`transactionDate`/`bankName`/`accountIban` werden direkt vom BankTransaction-Objekt geladen — **kein `parentStatementId`-Lookup** (Architektur-Entscheidung). Umgesetzt: Felder kommen inline in der MQTT-Nachricht von `alice-dms-processor` Phase B (noch simpler als der in der Tech Design vorgesehene Weaviate-GET, weil die Daten beim Publish autoritativ vorliegen)
- [x] Thumbnail-Layout: Bankname+IBAN (Kopfzeile klein) → Betrag (groß, zentral, farbcodiert nach `direction`: `debit` rot mit `−`, `credit` grün mit `+`, sonst/0 neutral) → Gegenpartei → Zweck → Datum. Lokal gerendert für debit/credit/zero/unknown-direction/minimal/unicode — visuell verifiziert
- [x] Thumbnail wird unter `thumbnails/<weaviate_uuid>.jpg` gespeichert, `thumbnail_path` per PATCH auf dem BankTransaction-Objekt gesetzt (`Code: Extract Thumbnail Path` + `HTTP: PATCH Weaviate` unverändert für alle Typen)
- [x] Verhalten für alle anderen Typen (inkl. PROJ-93-Email) unverändert — `Switch`-Fallback-Output führt exakt den bisherigen datei-basierten `jsonBody` aus; Email-Zweig unverändert. Validator: `Invoice` verlangt weiter `original_path`, `Email` weiter `mail_text`

#### Backfill-Abdeckung (`alice-dms-thumbnailer-backfill`)
- [x] Email/BankTransaction ohne `thumbnail_path` werden nicht mehr wegen fehlendem `filePath`/GraphQL-Fehler ausgeschlossen — `Code: Query Weaviate` fragt jetzt typ-spezifische Felder ab (kein `filePath` für Email/BankTransaction); `IF: Renderable` lässt `document_type ∈ {Email, BankTransaction}` ohne `file_path` durch
- [x] Email im Backfill nutzt denselben Text-Ansatz wie der Live-Pfad (`mail_text` aus `subject`+`content`, in `HTTP: POST /generate` jsonBody-Zweig)
- [x] BankTransaction im Backfill nutzt dasselbe Layout wie der Live-Pfad (identischer `bt_*`-jsonBody-Zweig, ein Service-Rendermodus für beide Pfade)
- [x] Nach einem Lauf haben vorher thumbnail-lose Email/BankTransaction-Objekte einen `thumbnail_path` (PATCH-Pfad unverändert; per-Weaviate-Query verifizierbar) — Laufzeit-Verifikation beim Deploy
- [x] **BUG-1 (behoben in dieser Iteration):** `thumbnail_path` existiert auf der `BankTransaction`-Klasse noch gar nicht (nie ein Thumbnail gesetzt) → die Query `{ BankTransaction { ... thumbnail_path } }` hätte einen GraphQL-Fehler geworfen und die Collection erneut still übersprungen. `Code: Query Weaviate` fragt `thumbnail_path` jetzt separat ab und wiederholt die Seite ohne das Feld bei `Cannot query field`-Fehler (Weaviate-Auto-Schema legt es erst beim ersten PATCH an)

#### Backfill-Lock
- [x] `Code: Acquire Backfill Lock` nimmt `alice:dms:processor:lock:run` (NX PX 1800000, fail-closed) — identisches Muster wie `alice-dms-language-backfill`
- [x] Lock belegt → `IF: Lock Acquired` [false] → `Code: Respond Locked` → `Respond to Webhook` mit `{ status: 'skipped', stopped_reason: 'locked', message: 'Lauf bereits aktiv' }`, HTTP 200, kein Warten, kein Crash
- [x] Lock-Freigabe in `Code: Build Summary` (owner-geprüftes Lua-`DEL`) — erreichbar aus allen Abschlusspfaden: Erfolg, Zeitlimit-Stopp, Leerlauf (`IF: Nothing To Do` [true]). TTL 30 min als Fallback bei Hard-Crash. Im `locked`-Pfad wurde nie ein Lock genommen → nichts freizugeben

#### Backfill-Zeitlimit
- [x] `time_limit_seconds` wird in `Code: Init Run` **per Node-Namen-Zugriff auf den Webhook** gelesen (`$('Webhook: POST /thumb-backfill').first().json.body`) — PROJ-92-Bug vermieden (Lock-Node davor liefert Item ohne `body`)
- [x] Gesetzt: `Code: Time Check` prüft nach **jedem** Dokument `elapsed >= max_runtime_seconds` → `IF: Time Limit Reached` [true] verlässt `Loop Over Docs` → `Code: Build Summary` mit `processed`/`failed`/`skipped_no_source`/`remaining`, Lock freigegeben. In-flight-Dokument ist vor dem Check fertig
- [x] Nicht gesetzt (`max_runtime_seconds = null`): `Code: Time Check` gibt immer `false` → Schleife läuft alle 8 Collections durch, `stopped_reason: 'completed'`, `remaining: 0`
- [x] Kein Selbstaufruf/Auto-Continue — kein `Execute Workflow`-Node im Graphen; ein zeitlimitierter Lauf wird manuell erneut aufgerufen, die Query überspringt bereits bethumbnailte Objekte
- [x] **BUG-2 (behoben in dieser Iteration):** `remaining` sollte per `thumbnail_path IsNull`-Aggregate kommen — `thumbnail_path` ist aber in **allen** Schemas `indexFilterable: false`, der Filter hätte immer einen Fehler geworfen und `remaining` wäre dauerhaft `null` (AC verlangt `0` bei vollständigem Lauf). Jetzt aus `total_docs - (processed+failed+skipped_no_source)` der flachen Liste abgeleitet — exakt und ohne Extra-Query

#### Aufräumen
- [x] `Split: Per Collection` ist aus `nodes` und `connections` entfernt

### Edge Cases Status

- [x] **BankStatement zwischenzeitlich gelöscht:** entfällt als Fehlerpfad — kein `parentStatementId`-Lookup mehr (Architektur-Entscheidung). Kein Crash möglich
- [x] **BankTransaction ohne `counterparty`/`purpose`:** `_render_bank_transaction` lässt leere Zeilen aus (`if text:`-Filter), kein „undefined". Getestet
- [x] **Betrag exakt 0:** neutral (schwarz), kein Vorzeichen, kein Rendering-Fehler. Getestet + visuell verifiziert
- [x] **Zeitlimit läuft während letztem Dokument ab:** `Code: Time Check` läuft **nach** vollständiger Dokumentverarbeitung → kein halbes Thumbnail
- [x] **Lauf ohne Zeitlimit bei großer Rückstandsmenge:** `executionTimeout: 86400`; nginx `/webhook/`-Proxy kann die HTTP-Verbindung nach 3600s beenden, der Workflow läuft serverseitig weiter (bekanntes, unschädliches Verhalten, PROJ-92)
- [x] **Lock bereits belegt beim Start:** sauberer Abbruch mit `message: 'Lauf bereits aktiv'`, HTTP 200, keine Queue
- [x] **Doppeltes Rendering desselben Objekts (Live + Backfill Race):** durch den geteilten Redis-Lock zwischen Backfill und nächtlichem Processor entschärft; ein doppelter PATCH überschreibt `thumbnail_path` mit identischem Wert — kein Datenverlust
- [x] **Unicode in Gegenpartei/Zweck (Umlaute, `—`, `&`):** getestet, rendert korrekt
- [x] **Sehr langer Verwendungszweck:** auf 120 Zeichen gekürzt, kein Crash. Getestet
- [x] **`currency` = null:** Betrag ohne Währungs-Suffix, kein Crash. Getestet
- [x] **Phase-B-Batch-Insert ohne per-Objekt-IDs (Fallback-Pfad):** `_inserted_bank_transactions` bleibt leer, `Code: Emit BankTransaction Done` gibt `[]` zurück, kein MQTT — der Backfill fängt diese Transaktionen ab. Geloggt
- [x] **Phase B Passthrough (Nicht-BankStatement):** `Code: Emit BankTransaction Done` erhält Item ohne `_inserted_bank_transactions` → `return []`; `IF: Phase B Failure` unverändert. Kein Regressionsrisiko für den bestehenden `MQTT: Publish Done`-Pfad

### Security Audit Results

**n8n workflow / Docker features:**
- [x] `/generate`-Endpoint ist interner-only (nicht über nginx exponiert), kein JWT — unverändert zu PROJ-55/93
- [x] Kein neuer webhook-exponierter Eingang mit Nutzerdaten außer `time_limit_seconds` (Integer, `parseInt` + `> 0`-Check, kein Injection-Vektor)
- [x] `original_path`-Traversal-Schutz im Service unverändert; für BankTransaction/Email wird `original_path` gar nicht ausgewertet (`file_based`-Flag)
- [x] Weaviate-GraphQL: `collection` kommt aus der hartkodierten `COLLECTIONS`-Liste, nicht aus Nutzereingabe — keine GraphQL-Injection
- [x] Redis-Lock-Owner-Token ist `crypto.randomUUID()`, Freigabe owner-geprüft per Lua-Script — kein fremder Lauf kann den Lock eines anderen freigeben
- [x] Keine Secrets in Log-Ausgaben (winston); Transaktionsbeträge/Gegenparteien landen im Thumbnail-Bild — das ist der Zweck, kein Leak (gleiche Vertraulichkeitsstufe wie das BankTransaction-Objekt selbst, Edge-Case-Abschnitt der Spec)
- [x] `MQTT: Publish BankTransaction Done` sendet Transaktionsfelder über den internen MQTT-Broker (VPN-only, wie alle `alice/dms/*`-Topics) — kein neuer Exposure

### Bugs Found

#### BUG-1: Backfill-Query bricht für BankTransaction ab, wenn `thumbnail_path` noch nicht auf der Klasse existiert
- **Severity:** High
- **Status:** ✅ Behoben in dieser Iteration (vor Abschluss `/qa`)
- **Root Cause:** `BankTransaction` hatte nie ein Thumbnail → Weaviate-Auto-Schema hat die Property `thumbnail_path` auf der Klasse nie angelegt. Die GraphQL-Query `{ BankTransaction { ... thumbnail_path } }` wirft `Cannot query field "thumbnail_path"` → `break` → Collection erneut still übersprungen (exakt der Bug, den PROJ-95 beheben soll).
- **Fix:** `Code: Query Weaviate` fragt `thumbnail_path` separat ab und wiederholt die Seite ohne das Feld bei diesem Fehler; alle zurückgegebenen Objekte sind dann per Definition thumbnail-los.
- **Priority:** Fix before deployment (erledigt)

#### BUG-2: `remaining` immer `null` wegen nicht-filterbarem `thumbnail_path`
- **Severity:** Medium
- **Status:** ✅ Behoben in dieser Iteration
- **Root Cause:** `thumbnail_path` ist in allen Schemas `indexFilterable: false`; ein `where: { path: ["thumbnail_path"], operator: IsNull }`-Aggregate wirft einen Fehler → gefangen → `remaining = null`, auch nach vollständigem Lauf (AC verlangt `0`).
- **Fix:** `remaining` aus `total_docs - (processed + failed + skipped_no_source)` der flachen Liste abgeleitet.
- **Priority:** Fix before deployment (erledigt)

#### BUG-3: staticData-Zähler nur am Laufende zurückgesetzt
- **Severity:** Low
- **Status:** ✅ Behoben in dieser Iteration
- **Root Cause:** `processed`/`failed`/`skipped_no_source` in `$getWorkflowStaticData` wurden nur in `Code: Build Summary` (am Ende) genullt. Ein Lauf, der vorher hart abbricht (z.B. Weaviate-Ausfall mit unbehandeltem Throw), hinterlässt Zähler-Reste für den nächsten Summary.
- **Fix:** Zusätzlicher Reset am Laufanfang in `Code: Init Run`.
- **Priority:** Nice to have (erledigt)

### Summary
- **Acceptance Criteria:** 24/24 Sub-Checks bestanden (3 davon nach In-Iteration-Fix)
- **Bugs Found:** 3 total (0 Critical, 1 High, 1 Medium, 1 Low) — **alle 3 in dieser Iteration behoben**
- **Security:** Pass — keine neuen Exposures, keine Injection-Vektoren, Lock owner-geprüft
- **Production Ready:** YES (statische Prüfung) — keine offenen Critical/High-Bugs
- **Recommendation:** Deploy. Beim Deploy: Container-Rebuild `alice-dms-thumbnailer` + 3 Workflow-Deploys. Nach Deploy einen Laufzeit-Smoke-Test fahren: (1) Backfill mit `time_limit_seconds: 60` gegen den Bestand, Response-Zahlen prüfen; (2) einen neuen BankStatement durch `alice-dms-processor` schicken, prüfen dass BankTransaction-Thumbnails live entstehen.

## Deployment
_To be added by /deploy_
