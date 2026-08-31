# PROJ-98: DMS Email-Konsistenz — IMAP-basierte Waisen-Erkennung

## Status: Approved
**Created:** 2026-08-31
**Last Updated:** 2026-08-31

## Dependencies

- **Ausgegliedert aus [[PROJ-97]]** — dort wurden ausschließlich datei-basierte DMS-Collections + BankTransaction behandelt; `Email` wurde bewusst ausgeklammert und hierher verschoben.
- Baut auf [[PROJ-46]] (Mail-IMAP-Integration) auf: `alice.imap_mailboxes` (Postfach-Config, AES-verschlüsseltes Passwort), `alice-mail-reader` (Python-IMAP-Adapter), Weaviate-Collection `Email` mit `mailboxId` / `imapUid` / `messageId`.
- Betrifft `alice-mail-reader` (`docker/compose/automations/alice-mail-reader/app.py`) — **neuer Endpoint** `POST /list-uids` (siehe Technical Requirements). Erfordert Container-Rebuild + Deploy.
- Betrifft `alice-dms-thumbnailer` (`docker/compose/automations/alice-dms-thumbnailer/app/main.py`) — nutzt den in [[PROJ-97]] angelegten `DELETE /thumbnail/{uuid}`-Endpoint. Keine Service-Änderung nötig.
- Folgt den in [[PROJ-92]] / [[PROJ-94]] / [[PROJ-95]] / [[PROJ-97]] etablierten Backfill-/Reconcile-Mustern (Webhook + `confirm`-Gate + optionaler `time_limit_seconds`, monatlicher Schedule mit implizitem `confirm`, geteilter Redis-Lock `alice:dms:processor:lock:run`, kein Auto-Continue, Node-Namen-Zugriff auf Body-Parameter wegen [[PROJ-92]]-Bug).
- Läuft parallel zum minütlichen `alice-mail-sync` — Synchronisation über den geteilten Lock **und** einen Pro-Postfach-`status='syncing'`-Check.

## Kontext

`alice-mail-sync` ist ein reiner **UID-Vorwärts-Pull**: pro Sync-Zyklus fragt es `UID <lastUid+1>:*` ab und indexiert nur neue Nachrichten. Bereits indexierte UIDs werden **nie wieder besucht**. Es gibt keine Redis-Bestandsliste der indexierten Mails (anders als bei der datei-basierten DMS-Pipeline mit `alice:dms:path_to_hash`). Daraus folgen zwei Waisen-Ursachen, die kein bestehender Workflow behebt:

- **(a) Postfach aus der Config entfernt.** `alice-mail-api` löscht beim Postfach-Löschen über die UI bereits alle `Email`-Objekte per `mailboxId`-Batch-Delete. Waisen bleiben aber übrig, wenn dieser Batch-Delete teilweise fehlschlägt oder ein Postfach direkt in der DB gelöscht wurde. Erkennbar rein über einen DB-Abgleich: `Email.mailboxId` zeigt auf kein `alice.imap_mailboxes`-Row (mehr).
- **(b) Einzelne Mail im Postfach gelöscht.** Der Nutzer löscht eine Mail in der INBOX. `mailboxId` lebt weiter, aber die `imapUid` existiert auf dem IMAP-Server nicht mehr. Das Weaviate-`Email`-Objekt bleibt für immer erhalten und taucht weiter in Suchergebnissen der DMS-Bibliothek und in `search_emails`-Chat-Antworten auf. Erkennbar nur über einen **Live-IMAP-Abgleich** pro Postfach.

**Gewählter Lösungsansatz** (Nutzerentscheidungen in der Spec-Phase):

Ein neuer n8n-Workflow **`alice-mail-reconcile`** (manueller Webhook + monatlicher Schedule), der den `Email`-Weaviate-Bestand gegen zwei Wahrheiten abgleicht: die Postfach-Liste in `alice.imap_mailboxes` (Fall a) und die live vom IMAP-Server geholte UID-Liste je INBOX (Fall b).

1. **Verwaiste-Postfach-Objekte löschen (Fall a).** Ein `Email`-Objekt, dessen `mailboxId` auf kein existierendes `alice.imap_mailboxes`-Row zeigt, gilt als verwaist und wird bei `confirm=true` aus Weaviate gelöscht (inkl. zugehöriger `thumbnails/<uuid>.jpg`). Kein IMAP-Zugriff nötig.
2. **Gelöschte-Mail-Objekte löschen (Fall b).** Pro Postfach mit lebendem `mailboxId` wird **einmal** die volle lebende UID-Liste der INBOX geholt (`POST /list-uids` im `alice-mail-reader`, ein IMAP-Roundtrip pro Postfach). Jedes `Email`-Objekt dieses Postfachs, dessen `imapUid` **nicht** in der lebenden Liste steht, gilt als verwaist und wird bei `confirm=true` gelöscht (inkl. Thumbnail).
3. **Nur INBOX.** `list-uids` prüft ausschließlich die INBOX — konsistent mit dem, was `alice-mail-sync` überhaupt indexiert. Eine aus der INBOX in einen anderen Ordner verschobene Mail gilt als Waise und wird gelöscht (`alice-mail-sync` würde sie ohnehin nicht wieder aufgreifen). Dokumentiert als Edge Case.
4. **Fail-safe bei IMAP-Fehler.** Schlägt die IMAP-Verbindung zu einem Postfach fehl (Server down, Passwort geändert, Netzwerk), wird für dieses Postfach **kein einziges** `Email`-Objekt gelöscht — Postfach wird übersprungen, nächster Lauf versucht es erneut. Fall-a-Objekte (verwaiste `mailboxId`) sind davon nicht betroffen, weil sie ohne IMAP erkannt werden.
5. **Leere UID-Liste = Postfach überspringen.** Liefert `list-uids` eine leere Liste (0 lebende UIDs), ist nicht unterscheidbar, ob das Postfach wirklich leergeräumt wurde oder ein IMAP-Bug vorliegt. Es wird **nichts** gelöscht (winston-Warnung + Zähler `skipped_mailbox_empty`); der Admin prüft manuell.
6. **Kein Attachment-Cascade.** PROJ-53-Mail-Anhänge werden als eigenständige Dateien ins NAS geschrieben und vom `alice-dms-scanner` als normale DMS-Dokumente indexiert — **ohne Rückverweis zur Quellmail**. Das Löschen eines verwaisten `Email`-Objekts lässt die daraus importierten Anhang-Dateien und ihre DMS-Objekte unberührt (das Archiv soll nicht leeren, wenn eine Mail im Postfach gelöscht wird). PROJ-97 kümmert sich um diese datei-basierten Objekte, falls die Datei je verschwindet.
7. **Redis-Cleanup nur bei `fileHash`.** Die meisten sync-indexierten `Email`-Objekte haben keinen `fileHash`. Ein über die DMS-Bibliothek archiviertes `.eml` hat einen — in dem Fall werden beim Löschen die `alice:dms:path_to_hash` / `alice:dms:hash_to_paths:<hash>` / `alice:dms:processed`-Reste bereinigt (Muster [[PROJ-97]]), sofern kein anderes lebendes Objekt denselben Hash nutzt.
8. **`confirm`-Gate (nur Webhook).** Ein Webhook-Aufruf ohne `confirm=true` ist ein reiner Dry-Run: identifiziert + zählt + loggt alle Waisen nach Kategorie, schreibt nichts, ruft `list-uids` trotzdem auf (Live-Zahlen). Mit `confirm=true` werden die Löschungen ausgeführt.
9. **Monatlicher Schedule: `confirm` implizit.** Der `Schedule Trigger` (erster Montag im Monat) fährt immer im Ausführungsmodus mit fest hinterlegtem `max_runtime_seconds`. Es gibt keinen Schedule-Dry-Run. Die Fail-safe-Regeln (Punkte 4 + 5) schützen vor Fehllöschungen.
10. **Geteilter Lock + Pro-Postfach-syncing-Check.** `alice:dms:processor:lock:run` (fail-closed, sauberer Skip bei belegtem Lock) gegen DMS-Prozessoren und parallele Reconcile-Läufe. `alice-mail-sync` nimmt diesen Lock nicht — daher zusätzlich vor jedem Postfach: `alice.imap_mailboxes.status` prüfen, bei `syncing` das Postfach in diesem Lauf überspringen (Zähler `skipped_mailbox_syncing`), nächster Lauf holt es nach.

Kein neuer Redis-Key. Keine Weaviate-Schema-Änderung. `alice-mail-sync`, `alice-mail-api` und alle DMS-Workflows bleiben unverändert. Einzige Service-Änderung: der neue `/list-uids`-Endpoint im `alice-mail-reader`.

## User Stories

- Als Admin möchte ich einen Reconcile-Lauf anstoßen können, der `Email`-Objekte erkennt und entfernt, deren Quell-Postfach nicht mehr konfiguriert ist, damit gescheiterte oder unvollständige Postfach-Löschungen keine Geister-Mails in der Bibliothek hinterlassen.
- Als Admin möchte ich, dass `Email`-Objekte entfernt werden, deren Mail ich im Postfach gelöscht habe, damit die DMS-Bibliothek und die `search_emails`-Chat-Antworten keine Mails mehr anzeigen, die es nicht mehr gibt.
- Als Admin möchte ich den Reconcile zuerst als Dry-Run fahren können, damit ich sehe, wie viele und welche `Email`-Objekte je Kategorie gelöscht würden, bevor ich die irreversible Löschung freigebe.
- Als Admin möchte ich, dass ein Postfach, dessen IMAP-Server gerade nicht erreichbar ist, im Reconcile komplett übersprungen wird, damit ein Verbindungsfehler nie den indexierten Bestand eines Postfachs löscht.
- Als Admin möchte ich den Reconcile mit einer festen Laufzeit starten können, damit ich bei vielen Postfächern oder großem Bestand kontrolliert in Teilmengen abarbeiten kann.
- Als Admin möchte ich, dass der Reconcile nicht zeitgleich mit dem minütlichen Mail-Sync dasselbe Postfach anfasst, damit beide Läufe verlässlich und ohne Race durchlaufen.
- Als Admin möchte ich, dass die Email-Konsistenzprüfung einmal im Monat automatisch läuft, damit sich verwaiste `Email`-Objekte nicht über Monate ansammeln, ohne dass ich daran denken muss.

## Acceptance Criteria

### Trigger & Betriebsmodus

- [ ] `alice-mail-reconcile` wird per `POST /webhook/alice-mail-reconcile` **oder** per `Schedule Trigger` (Cron: erster Montag im Monat; genaue Uhrzeit/UTC-Frage → `/architecture`, analog PROJ-97 `0 0 1-7 * 1`) ausgelöst.
- [ ] **Webhook ohne `confirm=true`:** Dry-Run — der Lauf identifiziert alle Kandidaten (inkl. Live-`list-uids`-Aufruf pro Postfach), zählt sie nach Kategorie, loggt jeden einzelnen per winston (UUID, `mailboxId`, `imapUid`, `subject`, geplante Aktion), führt **keine** Weaviate-Löschung und **keinen** Thumbnail-Delete aus.
- [ ] **Webhook mit `confirm=true`:** Löschungen (Weaviate + Thumbnail-Datei + ggf. Redis-Reste) werden ausgeführt.
- [ ] `confirm` und `time_limit_seconds` werden sowohl aus dem JSON-Body als auch aus dem Query-String gelesen (Muster PROJ-97 BUG-3), per Node-Namen-Zugriff auf den Webhook-Node (nicht `$input.first().json.body` — PROJ-92-Bug).
- [ ] **Schedule Trigger:** läuft immer im Ausführungsmodus (implizites `confirm`), mit fest hinterlegtem `max_runtime_seconds`. Kein Schedule-Dry-Run.
- [ ] Der Ausführungsmodus wird per Node-Namen-Zugriff bestimmt: fired der `Schedule Trigger` → `confirm`; fired der Webhook → `confirm` nur bei `confirm === true` in Body oder Query.
- [ ] `alice-mail-reconcile` nimmt vor Verarbeitungsbeginn den Redis-Lock `alice:dms:processor:lock:run` (NX, TTL ≥ Schedule-Fenster als Fallback). Ist der Lock belegt, beendet sich der Workflow sauber mit `{ status: 'skipped', stopped_reason: 'locked' }`, HTTP 200 (Webhook) bzw. still (Schedule), ohne zu warten. Der Lock wird bei jedem Ausgang (Erfolg, Zeitlimit-Stopp, Fehler via Error-Trigger) zuverlässig freigegeben.
- [ ] Ist Redis beim Lock-Erwerb nicht erreichbar: fail-closed — Abbruch, keine Weaviate-Operationen.
- [ ] Optionaler `time_limit_seconds`-Parameter: gesetzt → nach jedem verarbeiteten Objekt Zeitcheck, bei Ablauf sauberer Stopp mit vollständigem Response; nicht gesetzt (und Webhook) → alle Objekte über alle Postfächer werden verarbeitet. Kein Selbstaufruf/Auto-Continue.

### Fall (a): Verwaiste-Postfach-Objekte

- [ ] Der Workflow lädt einmal die Menge aller `id`-Werte aus `alice.imap_mailboxes`.
- [ ] Ein `Email`-Objekt gilt als **Postfach-Waise**, wenn sein `mailboxId` (a) leer ist oder (b) nicht in dieser Menge steht.
- [ ] Bei `confirm=true` wird ein Postfach-Waisen-Objekt per `DELETE /v1/objects/Email/<uuid>` aus Weaviate entfernt.
- [ ] Für Postfach-Waisen ist **kein** IMAP-Zugriff nötig — sie werden auch dann erkannt und gelöscht, wenn kein einziges Postfach erreichbar ist.

### Fall (b): Gelöschte-Mail-Objekte

- [ ] Pro Postfach mit lebendem `mailboxId` und `status != 'syncing'` ruft der Workflow **genau einmal** `POST /list-uids` im `alice-mail-reader` auf (Postfach-Zugangsdaten + `password_enc` aus `alice.imap_mailboxes`, `folder: 'INBOX'`).
- [ ] `list-uids` liefert die vollständige Liste der lebenden IMAP-UIDs der INBOX (als Integer/String-Liste).
- [ ] Ein `Email`-Objekt dieses Postfachs gilt als **Mail-Waise**, wenn sein `imapUid` (als String verglichen) **nicht** in der lebenden UID-Liste steht.
- [ ] Bei `confirm=true` wird ein Mail-Waisen-Objekt per `DELETE /v1/objects/Email/<uuid>` entfernt.
- [ ] Schlägt der `list-uids`-Aufruf für ein Postfach fehl (HTTP != 2xx, Timeout, Verbindungsfehler): **kein** `Email`-Objekt dieses Postfachs wird gelöscht (auch keine Fall-a-Prüfung wird dadurch blockiert — die läuft ohne IMAP). Zähler `skipped_mailbox_unreachable`++, winston-Warnung.
- [ ] Liefert `list-uids` eine **leere** Liste (0 UIDs): **kein** `Email`-Objekt dieses Postfachs wird gelöscht. Zähler `skipped_mailbox_empty`++, winston-Warnung.
- [ ] Hat das Postfach `status = 'syncing'` (und `updated_at` innerhalb des Sync-Timeout-Fensters, Muster PROJ-46 BUG-10): das Postfach wird in diesem Lauf komplett übersprungen (weder Fall a noch b). Zähler `skipped_mailbox_syncing`++.

### Löschung: Nebenwirkungen

- [ ] Bei jeder Objekt-Löschung wird die zugehörige Thumbnail-Datei per `DELETE /thumbnail/<uuid>` im `alice-dms-thumbnailer`-Service (aus [[PROJ-97]]) mitgelöscht. Ein Fehlschlag (Datei existiert nicht, Service down) wird geloggt und blockiert die Objekt-Löschung **nicht**.
- [ ] Ist auf dem Objekt ein nicht-leerer `fileHash` im SHA-256-Format gesetzt, werden nach der Löschung die Redis-Reste bereinigt: `alice:dms:hash_to_paths:<fileHash>` und die zeigenden `alice:dms:path_to_hash`-Einträge löschen, `fileHash` aus `alice:dms:processed` entfernen — nur sofern kein anderes lebendes Weaviate-Objekt (beliebiger Collection) denselben Hash nutzt.
- [ ] Ein `Email`-Objekt ohne `fileHash` löst keine Redis-Operation aus.
- [ ] Der Workflow published **kein** `alice/dms/done` (reine Löschung, keine Reparatur).

### Nicht-Ziele

- [ ] Der Workflow prüft **nur** die Collection `Email` — keine datei-basierten DMS-Collections, kein BankTransaction (das ist [[PROJ-97]]).
- [ ] Der Workflow prüft **nur** die INBOX jedes Postfachs — keine anderen IMAP-Ordner.
- [ ] Der Workflow löscht **keine** aus PROJ-53-Mail-Anhängen entstandenen DMS-Objekte oder NAS-Dateien (kein Cascade zur Quellmail).
- [ ] Der Workflow re-indexiert keine Mails und ändert keine `Email`-Objekt-Felder — er löscht nur.
- [ ] Der Workflow ändert die Klassifikation (`category`) eines `Email`-Objekts nicht.

### Response & Logging

- [ ] Der Webhook-Response enthält ausschließlich aggregierte Zähler:
  `{ status, mode: 'dry-run'|'confirm', trigger: 'webhook'|'schedule', stopped_reason: 'completed'|'time_limit'|'locked', checked, deleted_orphan_mailbox, deleted_orphan_message, thumbnail_files_removed, redis_hashes_cleaned, skipped_ok, skipped_mailbox_unreachable, skipped_mailbox_empty, skipped_mailbox_syncing, mailboxes_checked, remaining }`.
- [ ] Der Schedule-Lauf hat keinen HTTP-Response — dieselbe Zusammenfassung wird per winston geloggt und nach `alice/mail/reconcile-stats` (MQTT) published (Muster analog `alice-dms-scanner` `MQTT: Publish Stats` / PROJ-97 `alice/dms/reconcile-stats`).
- [ ] Jede einzelne Löschung wird per winston geloggt mit UUID, `mailboxId`, `imapUid`, `subject`, Kategorie (`orphan_mailbox` / `orphan_message`) und Aktion — unabhängig vom Trigger, auch im Dry-Run (dort „geplant").
- [ ] `remaining` = Anzahl noch nicht geprüfter `Email`-Objekte der flachen Arbeitsliste bei Zeitlimit-Stopp; 0 bei vollständigem Lauf.
- [ ] `mailboxes_checked` = Anzahl Postfächer, für die `list-uids` erfolgreich abgefragt wurde.
- [ ] Zähler-Semantik „planned-or-done" wie PROJ-97: `deleted_orphan_mailbox` / `deleted_orphan_message` zählen im Dry-Run die geplanten, im Confirm-Modus die ausgeführten Löschungen (bei Fehlschlag Dekrement + `skipped_ok`++). `thumbnail_files_removed` / `redis_hashes_cleaned` zählen nur echte Aktionen.

## Edge Cases

- **`Email`-Objekt mit lebendem `mailboxId`, `imapUid` in der lebenden UID-Liste:** gesund → `skipped_ok`++, nichts tun.
- **`Email`-Objekt ohne `imapUid` (Altbestand vor PROJ-46 BUG-2-Fix):** kann nicht gegen die UID-Liste geprüft werden → fail-safe behalten, `skipped_ok`++, winston-Warnung. (Fall a greift trotzdem, falls `mailboxId` fehlt.)
- **Mail aus INBOX in einen anderen IMAP-Ordner verschoben:** die UID ist in der INBOX weg → Objekt gilt als Mail-Waise → gelöscht. Bewusst akzeptiert: `alice-mail-sync` (UID-Vorwärts-Pull auf INBOX) würde die Mail ohnehin nicht wieder indexieren, die Mail wäre in Alice so oder so nicht mehr auffindbar.
- **IMAP-Server eines Postfachs down zu Lauf-Beginn:** `list-uids` schlägt fehl → Postfach übersprungen (`skipped_mailbox_unreachable`), Fall-a-Objekte dieses Postfachs (falls vorhanden) werden trotzdem geprüft (kein IMAP nötig), Mail-Waisen dieses Postfachs bleiben unangetastet. Nächster Lauf versucht es erneut.
- **Passwort eines Postfachs wurde nach dem letzten erfolgreichen Sync geändert:** `list-uids` scheitert an der Auth → wie „Server down": Postfach übersprungen, nichts gelöscht.
- **`list-uids` liefert leere Liste, Postfach wurde tatsächlich leergeräumt:** kein automatisches Löschen (`skipped_mailbox_empty`). Der Admin muss nach Sichtprüfung manuell nachhelfen (z.B. Postfach in der UI löschen → `alice-mail-api`-Batch-Delete, oder gezielter Reconcile-Sonderlauf — außerhalb dieser Spec).
- **Postfach hat gerade `status = 'syncing'`:** komplett übersprungen (`skipped_mailbox_syncing`), nächster Reconcile-Lauf holt es nach. Verhindert den Race, dass der Reconcile eine UID als „weg" wertet, die `alice-mail-sync` im selben Moment gerade indexiert.
- **`alice-mail-sync` indexiert eine neue Mail, während der Reconcile die UID-Liste bereits geholt hat:** die neue UID ist in der Reconcile-Momentaufnahme nicht enthalten → das frisch indexierte Objekt könnte als Mail-Waise klassifiziert werden. Schutz: der `status='syncing'`-Check überspringt Postfächer mit laufendem Sync; zusätzlich fail-safe — ein Objekt, das jünger ist als der Zeitpunkt des `list-uids`-Aufrufs (`Email.date` bzw. `createdAt` > Abfragezeitpunkt), wird behalten. (Feinschliff → `/architecture`.)
- **Redis fällt mitten im Lauf aus (nach erfolgreichem Lock):** `fileHash`-Cleanup-Fehler wird geloggt, nicht abgebrochen; die Weaviate-Löschung selbst hängt nicht an Redis. Der Lock läuft per TTL aus.
- **Weaviate-DELETE schlägt für ein Objekt fehl:** loggen, nicht abbrechen, mit dem nächsten Objekt weiter; das Objekt wird im nächsten Lauf erneut geprüft (idempotent).
- **`thumbnail_path` auf dem Objekt zeigt auf eine nicht mehr existierende Datei:** `DELETE /thumbnail/<uuid>` ist idempotent (`missing_ok`, aus PROJ-97) → kein Fehler; Objekt-Löschung läuft normal durch.
- **Dry-Run meldet 40 Mail-Waisen, `confirm`-Lauf findet nur 38:** in der Zwischenzeit hat `alice-mail-sync` 2 Mails neu indexiert oder der Nutzer hat Mails wiederhergestellt — kein Fehler, der `confirm`-Lauf arbeitet mit dem dann aktuellen Stand.
- **Zeitlimit läuft ab, während ein Postfach noch nicht fertig geprüft ist:** sauberer Stopp nach dem aktuellen Objekt; `remaining` > 0. Der `list-uids`-Aufruf für das laufende Postfach wird nicht wiederholt (die Momentaufnahme bleibt für den Rest des Laufs gültig); nächster Lauf beginnt von vorn.
- **Der erste Montag im Monat fällt auf den 1.:** Cron-Ausdruck matcht genau einmal (Tag-1–7-UND-Montag), kein Doppel-Lauf — identisch zur PROJ-97-Analyse.
- **Ein Postfach existiert in `alice.imap_mailboxes`, hat aber 0 indexierte `Email`-Objekte:** `list-uids` wird trotzdem nicht aufgerufen (kein Objekt zu prüfen) bzw. der Lauf iteriert die flache Objektliste, findet nichts für dieses Postfach — kein Sonderfall.
- **Schedule-Lauf bricht mit Fehler ab (Weaviate/Ollama-unabhängig, z.B. Weaviate mitten im Lauf weg):** `Error Trigger`-Zweig gibt den Lock frei; bereits gelöschte Objekte bleiben gelöscht (idempotent), der Rest folgt im nächsten Monatslauf. Kein Auto-Retry.

## Technical Requirements (optional)

- **Neuer Endpoint `POST /list-uids` in `alice-mail-reader`** (`docker/compose/automations/alice-mail-reader/app.py`):
  - Body: `{ host, port, ssl, username, password_enc, folder }` (analog `/fetch`), `folder` default `"INBOX"`.
  - Führt `imap.select(folder, readonly=True)` + `imap.uid("search", None, "ALL")` aus.
  - Response: `{ uids: [<int>, ...], count: <n> }` bei Erfolg; `{ uids: [], error: "<msg>" }` mit HTTP 400/500 bei Fehler.
  - Kein JWT (interner Endpoint, wie die anderen `alice-mail-reader`-Routen). Read-only Select — verändert keine Flags, kein Expunge.
  - Erfordert Container-Rebuild + Deploy von `alice-mail-reader`.
- Kein neuer Redis-Key — Wiederverwendung von `alice:dms:processor:lock:run` und der bestehenden `alice:dms:*`-Map-Keys (nur bei gesetztem `fileHash` angefasst).
- Keine Weaviate-Schema-Änderung.
- Kein Selbstaufruf-Mechanismus (bewusste Abweichung von [[PROJ-96]]) — konsistent mit [[PROJ-92]] / [[PROJ-94]] / [[PROJ-95]] / [[PROJ-97]].
- Weaviate-Abfrage: flache Arbeitsliste aller `Email`-Objekte (`_additional { id }`, `mailboxId`, `imapUid`, `subject`, `date`/`createdAt`, `fileHash`, `thumbnail_path` — Letzteres separat abfragen und bei `Cannot query field`-Fehler weglassen, Muster [[PROJ-95]]). Ein einzelner Loop, kein Loop-in-Loop; `mailboxId` steuert nur, welche `list-uids`-Momentaufnahme herangezogen wird.
- Fail-safe bei Unsicherheit (Muster [[PROJ-97]]): ein `Email`-Objekt wird nur gelöscht, wenn eindeutig entweder (a) sein `mailboxId` tot ist oder (b) seine `imapUid` verlässlich als „nicht mehr vorhanden" bestimmt wurde (erfolgreicher, nicht-leerer `list-uids`-Abgleich). Jeder IMAP-/Redis-/Weaviate-Fehler während der Zuordnung → „behalten".
- `list-uids` pro Postfach genau einmal pro Lauf (Momentaufnahme im Lauf-Speicher halten, Muster PROJ-97 `Code: Load Redis Maps`), nicht pro Objekt.
- Sicherheit: Der Webhook ist wie PROJ-97 VPN-only ohne zusätzliche Auth (`confirm`-Gate + Dry-Run als Schutz). Falls `/architecture` das anders bewertet → dort entscheiden.
- Schedule-Cron-Uhrzeit (UTC vs. Berlin, Kollision mit `alice-mail-sync` gibt es nicht — der läuft ohnehin jede Minute; relevanter ist die Kollision mit den DMS-Schedules und PROJ-97) → `/architecture`.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

PROJ-98 hat **keine UI-Komponente**. Es besteht aus zwei Bausteinen:

1. **Neuer n8n-Workflow `alice-mail-reconcile`** (neue Datei `workflows/alice-mail-reconcile.json`). Baugleich zu [[PROJ-97]] `alice-dms-reconcile` — gleiche Trigger-Struktur, gleicher Lock, gleiches `confirm`-Gate, gleiches Zeitlimit-/Response-Muster. Unterschied: die „Wahrheit", gegen die abgeglichen wird, ist nicht die Redis-Pfad-Map, sondern (a) die Postfach-Liste in `alice.imap_mailboxes` und (b) die live vom IMAP-Server geholte UID-Liste je INBOX.
2. **Neuer Endpoint `POST /list-uids` im Service `alice-mail-reader`** (`docker/compose/automations/alice-mail-reader/app.py`). Ein einziger `UID SEARCH ALL` gegen die read-only geöffnete INBOX. Erfordert Container-Rebuild + Deploy.

Der in [[PROJ-97]] angelegte `DELETE /thumbnail/{uuid}` im `alice-dms-thumbnailer`-Service wird unverändert wiederverwendet. `alice-mail-sync`, `alice-mail-api` und alle DMS-Workflows bleiben unangetastet. Keine Weaviate-Schema-Änderung, kein neuer Redis-Key.

### E) Workflow-Architektur

#### Service-Erweiterung: `POST /list-uids` in `alice-mail-reader`

- **Eingang:** `{ host, port, ssl, username, password_enc, folder }` — dieselben Verbindungsfelder wie `/fetch`, `folder` default `"INBOX"`. Das Passwort bleibt AES-verschlüsselt, wird nur im Container entschlüsselt (bestehendes Muster, `_decrypt_password`).
- **Verarbeitung:** `imap.select(folder, readonly=True)` + `imap.uid("search", None, "ALL")`. Read-only — verändert keine Flags, kein Expunge.
- **Ausgang (Erfolg):** `{ uids: [<int>, ...], count: <n> }`.
- **Ausgang (Fehler):** `{ uids: [], error: "<msg>" }` mit HTTP 400 (IMAP-/Auth-Fehler) bzw. 500 (unerwartet) — dasselbe Fehlerschema wie `/fetch`.
- **Kein JWT** — interner Endpoint, nur aus dem Docker-Netz erreichbar, wie alle anderen `alice-mail-reader`-Routen.

#### Trigger (identisch zu PROJ-97)

Zwei Trigger speisen denselben Verarbeitungsgraphen:

- **`Webhook: POST /webhook/alice-mail-reconcile`** — manueller Lauf. Ohne `confirm=true` (Body **oder** Query) ist es ein reiner **Dry-Run**: identifizieren, zählen, loggen, `list-uids` trotzdem aufrufen (Live-Zahlen), aber **nichts** löschen. Mit `confirm=true` werden die Löschungen ausgeführt. Optionaler `time_limit_seconds`-Parameter (Body oder Query) begrenzt die Laufzeit.
- **`Schedule Trigger: Monthly`** — Cron `0 1 1-7 * 1` (**erster Montag im Monat, 01:00 UTC**). Läuft **immer** im Ausführungsmodus (implizites `confirm`), festes Zeitlimit `max_runtime_seconds = 3600`. Kein Schedule-Dry-Run.

Warum 01:00 UTC: [[PROJ-97]] `alice-dms-reconcile` feuert am selben ersten Montag um 00:00 UTC und hält den geteilten Lock `alice:dms:processor:lock:run` für bis zu 3600 s (bis 01:00 UTC). `alice-mail-reconcile` startet, wenn dieses Fenster gerade endet. Läuft PROJ-97 länger, skippt `alice-mail-reconcile` sauber per Lock (`stopped_reason: 'locked'`) und wird im Folgemonat oder manuell nachgeholt. `alice-dms-processor` läuft erst um 02:00 UTC. „Erster Montag im Monat" = DOM 1–7 UND Wochentag Montag (n8n-/Standard-Cron-UND-Verknüpfung bei beidseitiger Einschränkung); fällt der 1. auf einen Montag, matcht genau dieser eine Tag — kein Doppel-Lauf.

Ein `Code: Init Run`-Node hinter beiden Triggern bestimmt per **Node-Namen-Zugriff** (nicht `$input.first().json.body` — [[PROJ-92]]-Bug), welcher Trigger gefeuert hat: Schedule → `mode = confirm`, `trigger = schedule`, `max_runtime_seconds = 3600`. Webhook → `trigger = webhook`, `mode = confirm` nur bei `confirm === true` in Body oder Query, `max_runtime_seconds` aus `time_limit_seconds` (sonst unbegrenzt).

#### Überlappungsschutz (Lock + Pro-Postfach-syncing-Check)

**Lauf-globaler Lock:** Direkt nach `Code: Init Run` nimmt der Lauf den **bestehenden** Redis-Lock `alice:dms:processor:lock:run` (SET NX, TTL 65 min als Fallback — muss ≥ dem 3600-s-Schedule-Fenster sein). Ist der Lock belegt (DMS-Processor, ein DMS-Backfill, PROJ-97-Reconcile, oder ein parallel gestarteter Mail-Reconcile): sauberer Abbruch mit `{ status: 'skipped', stopped_reason: 'locked' }`, HTTP 200 (Webhook) bzw. stiller Stopp (Schedule), **ohne zu warten**. Ist Redis beim Lock-Erwerb nicht erreichbar: **fail-closed** — Abbruch, keine Weaviate-Operationen. Der Lock wird bei jedem Ausgang (Erfolg, Zeitlimit-Stopp, Fehler via Error-Trigger) über einen `Code: Release Lock`-Node freigegeben; die TTL ist die Rückfallebene. Owner-checked Release per Lua-`eval` im Normalpfad (Muster PROJ-97).

**Warum zusätzlich ein Pro-Postfach-Check:** `alice-mail-sync` läuft **jede Minute** und nimmt den geteilten Lock **nicht**. Ein Reconcile-Lauf könnte also parallel zu einem laufenden Sync desselben Postfachs eine UID als „weg" werten, die der Sync gerade indexiert. Schutz: vor jedem Postfach prüft der Reconcile `alice.imap_mailboxes.status`. Ist es `syncing` (und `updated_at` innerhalb des 30-Minuten-Sync-Timeout-Fensters — Muster PROJ-46 BUG-10, identisch zu `alice-mail-sync` `PG: Check Active Syncs`), wird das Postfach in diesem Lauf **komplett** übersprungen (weder Fall a noch b), Zähler `skipped_mailbox_syncing`++. Der nächste Reconcile-Lauf holt es nach.

#### Verarbeitungsschritte (Nodes, High-Level)

```
Trigger (Webhook | Schedule Monthly)
  |
  +-- Code: Init Run ............... Modus + Zeitlimit + Trigger-Quelle bestimmen
  +-- Code: Acquire Lock .......... alice:dms:processor:lock:run (NX, TTL 65 min)
  +-- IF: Lock Acquired
  |     |-- (nein) --> Code: Respond Locked --> IF: From Webhook --> Ende
  |     |-- (ja)
  +-- PG: Load Mailboxes .......... SELECT id, imap_host, imap_port, imap_username,
  |                                  password_enc, ssl_enabled, status, updated_at
  |                                  FROM alice.imap_mailboxes
  +-- Code: Query Weaviate ........ flache Arbeitsliste ALLER Email-Objekte:
  |                                  _additional { id }, mailboxId, imapUid, subject,
  |                                  date, fileHash  (thumbnail_path separat, bei
  |                                  "Cannot query field" weglassen - Muster PROJ-95)
  +-- Code: Plan Run ............... - Menge lebender mailboxId aus PG bilden
  |                                  - Postfaecher mit >=1 Email-Objekt + lebendem
  |                                    mailboxId + status != 'syncing' bestimmen
  |                                  - fuer JEDES dieser Postfaecher EINMAL list-uids
  |                                    aufrufen, Momentaufnahme (uidSet + Abfragezeit)
  |                                    im Lauf-Speicher (staticData) halten
  |                                  - Ergebnis je Postfach: ok | unreachable | empty | syncing
  +-- IF: Nothing To Do --> Code: Build Summary --> Ende
  +-- Loop Over Objects ........... ein einzelner Loop, kein Loop-in-Loop
  |     |
  |     +-- Code: Classify Object . entscheidet: healthy | orphan_mailbox | orphan_message | keep
  |     |     1. mailboxId leer ODER nicht in lebender Menge  -> orphan_mailbox
  |     |     2. Postfach-Snapshot == syncing/unreachable/empty -> keep (skipped_mailbox_*)
  |     |     3. imapUid leer (Altbestand)                     -> keep (skipped_ok, Warnung)
  |     |     4. Objekt juenger als Snapshot-Abfragezeit       -> keep (fail-safe, Race)
  |     |     5. String(imapUid) in Snapshot-uidSet            -> healthy (skipped_ok)
  |     |     6. sonst                                         -> orphan_message
  |     |
  |     +-- IF: Mode == confirm
  |     |     |-- (dry-run) --> Code: Log Planned (winston) --> zurueck in Loop
  |     |     |-- (confirm)
  |     |           +-- [orphan_mailbox | orphan_message]
  |     |           |     - DELETE /v1/objects/Email/<uuid>  (Weaviate REST)
  |     |           |     - DELETE /thumbnail/<uuid>  (alice-dms-thumbnailer, PROJ-97;
  |     |           |       Fehlschlag blockiert Objekt-Loeschung NICHT)
  |     |           |     - nur bei nicht-leerem SHA-256 fileHash: Redis-Reste bereinigen
  |     |           |       (alice:dms:hash_to_paths:<hash> + zeigende path_to_hash-Keys
  |     |           |        + Eintrag aus alice:dms:processed) - sofern kein anderes
  |     |           |        lebendes Weaviate-Objekt denselben Hash nutzt
  |     |           +-- [healthy | keep]  Zaehler, nichts tun
  |     |
  |     +-- Code: Time Check ....... nach JEDEM Objekt: Zeitlimit erreicht?
  |     +-- IF: Time Limit Reached
  |           |-- (ja)  --> Loop verlassen --> Code: Build Summary
  |           |-- (nein) --> naechstes Objekt
  |
  +-- Code: Build Summary ......... aggregierte Zaehler
  +-- Code: Release Lock
  +-- IF: From Webhook
  |     |-- (ja)  --> Respond to Webhook (JSON-Zaehler)
  |     |-- (nein) --> MQTT: Publish alice/mail/reconcile-stats --> End (NoOp)
```

Ein `Error Trigger` → `Code: Release Lock (error)` → `MQTT: Publish Error`-Zweig (Muster PROJ-97 / `alice-dms-lifecycle`) gibt den Lock nach einem Absturz frei (Owner-checked: nur löschen, wenn der Lock diesem Workflow gehört).

**Kein Loop-in-Loop:** Die `list-uids`-Aufrufe passieren **einmal vorab** in `Code: Plan Run`, nicht im Objekt-Loop. Der Loop iteriert eine einzige flache Objektliste; `mailboxId` steuert nur, welche vorab geholte Momentaufnahme herangezogen wird (Muster PROJ-97 `Code: Load Redis Maps`).

#### Datenfluss

**Rein:** Trigger-Kontext (Webhook-Body/-Query mit `confirm`/`time_limit_seconds`, oder Schedule-Signal). **Verarbeitung:** Postfach-Liste (Postgres) + vollständige `Email`-Objektliste (Weaviate) werden geladen → pro relevantem Postfach genau ein `list-uids`-IMAP-Roundtrip → jedes `Email`-Objekt wird gegen (a) die lebende `mailboxId`-Menge und (b) die Postfach-UID-Momentaufnahme klassifiziert → im Confirm-Modus pro Waise: Weaviate-DELETE + Thumbnail-DELETE + ggf. Redis-Cleanup. **Raus:** Webhook-JSON mit aggregierten Zählern, bzw. (Schedule) winston-Log + `alice/mail/reconcile-stats`-MQTT.

Jede einzelne Löschung wird **immer** per winston geloggt (UUID, `mailboxId`, `imapUid`, `subject`, Kategorie `orphan_mailbox`/`orphan_message`, Aktion) — auch im Dry-Run (dort „geplant").

#### Integrationen

| System | Wofür |
| --- | --- |
| **PostgreSQL** (`alice.imap_mailboxes`) | Lebende Postfach-Menge (Fall a), Verbindungsdaten + `password_enc` für `list-uids`, `status`/`updated_at` für den syncing-Check |
| **`alice-mail-reader`** (neuer `POST /list-uids`) | Live-UID-Liste der INBOX je Postfach (Fall b) — ein IMAP-Roundtrip pro Postfach pro Lauf |
| **Weaviate** | GraphQL-Get (flache `Email`-Objektliste), REST-DELETE (verwaiste Objekte); GraphQL-Count für den „teilt ein anderes Objekt diesen fileHash?"-Check |
| **`alice-dms-thumbnailer`** (`DELETE /thumbnail/{uuid}`, aus PROJ-97) | Thumbnail-Datei zum gelöschten `Email`-Objekt entfernen (idempotent, `missing_ok`) |
| **Redis** | Lock `alice:dms:processor:lock:run`; `alice:dms:*`-Map-Cleanup **nur** bei gesetztem `fileHash` (archivierte `.eml`) |
| **MQTT** | `alice/mail/reconcile-stats` (Monatslauf-Statistik), `alice/mail/error` (Fehlerzweig). **Kein** `alice/dms/done` — reine Löschung, keine Reparatur |

Kein neues externes System — `alice-mail-reader` und `alice-dms-thumbnailer` sind bereits im Einsatz, der Endpoint bzw. Aufruf ist neu.

#### Fehlerverhalten (Fail-safe-Grundregel: im Zweifel behalten)

- **Redis nicht erreichbar zu Lauf-Beginn:** fail-closed, Abbruch mit `stopped_reason: 'locked'`, keine Weaviate-Operation.
- **Postgres nicht erreichbar (`Load Mailboxes` schlägt fehl):** Abbruch, Lock freigeben, nichts löschen — die lebende `mailboxId`-Menge ist die Grundlage für Fall a und darf nie geraten werden.
- **`list-uids` schlägt für ein Postfach fehl** (HTTP != 2xx, Timeout, Verbindungsfehler, Auth-Fehler nach Passwortänderung): Postfach-Snapshot = `unreachable`. **Kein** `Email`-Objekt dieses Postfachs wird als Mail-Waise gelöscht. Fall-a-Prüfung (totes `mailboxId`) läuft für dieses Postfach trotzdem — sie braucht kein IMAP. Zähler `skipped_mailbox_unreachable`++, winston-Warnung. Nächster Lauf versucht es erneut.
- **`list-uids` liefert leere Liste (0 UIDs):** nicht unterscheidbar, ob das Postfach wirklich leer ist oder ein IMAP-Bug vorliegt. Snapshot = `empty`, **kein** Mail-Waisen-Löschen für dieses Postfach. Zähler `skipped_mailbox_empty`++, winston-Warnung. (Fall a greift weiterhin.)
- **Postfach `status = 'syncing'`:** Snapshot = `syncing`, Postfach **komplett** übersprungen (weder Fall a noch b — der Sync könnte gerade auch die Postfach-Konfiguration anfassen). Zähler `skipped_mailbox_syncing`++.
- **`Email`-Objekt ohne `imapUid`** (Altbestand vor PROJ-46 BUG-2): kann nicht gegen die UID-Liste geprüft werden → behalten, `skipped_ok`++, winston-Warnung. (Fall a greift, falls `mailboxId` fehlt.)
- **Race — `alice-mail-sync` indexiert eine neue Mail, nachdem `list-uids` schon lief:** Objekt, dessen `date`/`createdAt` **nach** dem `list-uids`-Abfragezeitpunkt des Postfachs liegt → behalten (fail-safe), `skipped_ok`++. Zusätzlich zum `syncing`-Check.
- **Weaviate-DELETE schlägt für ein Objekt fehl:** loggen, Zähler dekrementieren + `skipped_ok`++, nicht abbrechen, nächstes Objekt. Das Objekt wird im nächsten Lauf erneut geprüft (idempotent).
- **`DELETE /thumbnail/<uuid>` schlägt fehl** (Service down, Datei existiert nicht): loggen, blockiert die Objekt-Löschung **nicht**. `thumbnail_files_removed` zählt nur echte Erfolge.
- **Redis fällt mitten im Lauf aus (nach erfolgreichem Lock):** `fileHash`-Cleanup-Fehler wird geloggt, nicht abgebrochen; die Weaviate-Löschung hängt nicht an Redis. Der Lock läuft per TTL aus.
- **Zeitlimit läuft ab, während ein Postfach noch nicht fertig geprüft ist:** sauberer Stopp nach dem aktuellen Objekt, `remaining` > 0. Die schon geholten `list-uids`-Momentaufnahmen werden nicht wiederholt; nächster Lauf beginnt von vorn.
- **Schedule-Lauf bricht mit Fehler ab:** `Error Trigger`-Zweig gibt den Lock frei; bereits gelöschte Objekte bleiben gelöscht (idempotent), der Rest folgt im nächsten Monatslauf. Kein Auto-Retry.

### B) Datenmodell (fachlich)

**Kein neues Weaviate-Feld, kein neuer Redis-Key, keine Postgres-Änderung.** Der Workflow liest ausschließlich bestehende Strukturen.

Pro geprüftem `Email`-Objekt relevant:

- **UUID** (`_additional.id`) — Objekt-Identität; steuert `DELETE /v1/objects/Email/<uuid>` und `DELETE /thumbnail/<uuid>`
- **mailboxId** — Verweis auf `alice.imap_mailboxes.id`; leer oder nicht in der lebenden Menge = **Postfach-Waise** (Fall a)
- **imapUid** (als String gespeichert) — IMAP-UID der Mail in der INBOX; nicht in der lebenden UID-Liste des Postfachs = **Mail-Waise** (Fall b)
- **subject** — nur fürs Logging
- **date** / **createdAt** — für den Race-Schutz (Objekt jünger als `list-uids`-Abfragezeit → behalten)
- **fileHash** (optional, SHA-256) — nur bei über die DMS-Bibliothek archivierten `.eml`-Mails gesetzt; steuert, ob nach der Löschung Redis-Reste bereinigt werden
- **thumbnail_path** (optional) — separat abfragen, bei `Cannot query field`-Fehler weglassen (Muster PROJ-95); der Thumbnail-Delete läuft ohnehin über die UUID

Aus `alice.imap_mailboxes` gelesen (nur lesend):

- **id** — bildet die „lebende `mailboxId`-Menge" für Fall a
- **imap_host / imap_port / imap_username / password_enc / ssl_enabled** — an `list-uids` durchgereicht (Passwort bleibt verschlüsselt)
- **status / updated_at** — `status = 'syncing'` UND `updated_at` innerhalb 30 min → Postfach überspringen

**Klassifikations-Logik pro Objekt (fachlich):**

```
mailboxId leer ODER nicht in lebender imap_mailboxes-Menge?
    ja -> orphan_mailbox  (loeschen, KEIN IMAP noetig)

Postfach-Snapshot dieses mailboxId == syncing / unreachable / empty?
    ja -> keep  (Zaehler skipped_mailbox_*, nichts tun)

imapUid leer?
    ja -> keep  (skipped_ok, Warnung: Altbestand)

Objekt-date/createdAt > list-uids-Abfragezeit dieses Postfachs?
    ja -> keep  (skipped_ok, fail-safe Race-Schutz)

String(imapUid) in Snapshot-uidSet dieses Postfachs?
    ja -> healthy  (skipped_ok)
    nein -> orphan_message  (loeschen)
```

Jeder IMAP-/Redis-/Weaviate-/Postgres-Fehler während der Zuordnung → Ergebnis `keep`/`skipped_ok` (fail-safe: lieber eine Geister-Mail stehen lassen als ein gültiges `Email`-Objekt inkl. Vektor und LLM-Zusammenfassung löschen).

**Response-/Statistik-Objekt** (Webhook-JSON bzw. MQTT-Payload):

```
status ......................... 'ok' | 'skipped'
mode ........................... 'dry-run' | 'confirm'
trigger ........................ 'webhook' | 'schedule'
stopped_reason ................. 'completed' | 'time_limit' | 'locked'
checked ........................ Email-Objekte insgesamt geprueft
deleted_orphan_mailbox ......... Fall a: verwaiste-Postfach-Objekte (geplant/ausgefuehrt)
deleted_orphan_message ......... Fall b: geloeschte-Mail-Objekte (geplant/ausgefuehrt)
thumbnail_files_removed ........ Thumbnail-Dateien geloescht (nur echte Aktionen)
redis_hashes_cleaned .......... fileHash-Redis-Bereinigungen (nur echte Aktionen)
skipped_ok .................... gesunde + fail-safe-behaltene Objekte
skipped_mailbox_unreachable ... Objekte in Postfaechern mit IMAP-Fehler
skipped_mailbox_empty ......... Objekte in Postfaechern mit leerer UID-Liste
skipped_mailbox_syncing ....... Objekte in Postfaechern mit laufendem Sync
mailboxes_checked ............. Postfaecher mit erfolgreichem list-uids
remaining .................... bei Zeitlimit-Stopp: noch nicht geprueft; sonst 0
```

Zähler-Semantik „planned-or-done" wie [[PROJ-97]]: `deleted_orphan_mailbox` / `deleted_orphan_message` zählen im Dry-Run die **geplanten**, im Confirm-Modus die **ausgeführten** Löschungen (bei Fehlschlag Dekrement + `skipped_ok`++). `thumbnail_files_removed` / `redis_hashes_cleaned` zählen nur echte Aktionen (nur Confirm-Pfad).

### C) Tech-Entscheidungen (Begründung)

- **Eigener Workflow statt Erweiterung von `alice-dms-reconcile` (PROJ-97):** PROJ-97 gleicht gegen die Redis-Pfad-Map ab (datei-basierte Collections). Email hat keine Redis-Bestandsliste — die Wahrheit sitzt im IMAP-Postfach und in Postgres. Zwei fundamental verschiedene Abgleich-Quellen in einem Workflow zu mischen würde beide Läufe schwerer testbar und schwerer abbrechbar machen. Der bewusste Cut in der Spec-Phase (Email aus PROJ-97 ausgegliedert) wird hier fortgeführt.
- **Neuer Service-Endpoint statt IMAP direkt aus n8n:** n8n Code-Nodes haben kein `imaplib` und dürfen nur `axios`/`redis`/`winston` (+ `crypto`/`fs`/`path`). `alice-mail-reader` kapselt bereits die gesamte IMAP-Logik inkl. Passwort-Entschlüsselung — `list-uids` ist dort ein 4-Zeilen-Handler analog zu `/test`. Das Klartext-Passwort verlässt den Container nie.
- **Nur INBOX:** `alice-mail-sync` ist ein reiner UID-Vorwärts-Pull auf die INBOX. Der Reconcile prüft genau das, was der Sync indexiert. Eine aus der INBOX in einen anderen Ordner verschobene Mail gilt bewusst als Waise — der Sync würde sie ohnehin nie wieder aufgreifen, sie wäre in Alice so oder so tot. Dokumentierter Edge Case.
- **Geteilter Lock `alice:dms:processor:lock:run` statt neuem Key:** verhindert Parallel-Schreibzugriff mit PROJ-97-Reconcile, dem DMS-Processor und den DMS-Backfills — die alle denselben Weaviate-Bestand und dieselben Redis-`alice:dms:*`-Maps anfassen. Ein eigener Lock würde diese Konflikte nicht abdecken.
- **Zusätzlicher Pro-Postfach-`syncing`-Check:** `alice-mail-sync` (jede Minute) nimmt den geteilten Lock nicht. Ohne diesen Check könnte der Reconcile eine gerade frisch indexierte UID als „weg" werten. Der `status='syncing'`-Check plus der Race-Schutz über den `list-uids`-Zeitstempel schließen dieses Fenster.
- **Fail-safe-Asymmetrie:** Eine stehen gelassene Geister-Mail ist kosmetisch (ein Treffer zu viel in der DMS-Bibliothek / `search_emails`). Eine Fehllöschung ist irreversibel (Weaviate-Objekt inkl. Vektor und deutscher LLM-Zusammenfassung weg). Deshalb: löschen nur bei eindeutig totem `mailboxId` **oder** verlässlich bestimmter „UID nicht mehr da" (erfolgreicher, nicht-leerer `list-uids`-Abgleich). Jeder Zweifel → behalten.
- **Dry-Run nur für den Webhook, nicht für den Schedule:** identisch zu PROJ-97 — niemand fährt nachts um 01:00 einen manuellen Bestätigungslauf hinterher. Die Fail-safe-Regeln (Punkte 4 + 5 der Spec) plus die monatliche Wiederholung machen den automatischen Ausführungsmodus vertretbar.
- **Kein Attachment-Cascade:** PROJ-53-Mail-Anhänge werden als eigenständige NAS-Dateien vom `alice-dms-scanner` als normale DMS-Dokumente indexiert — ohne Rückverweis zur Quellmail. Das Archiv soll nicht leeren, wenn eine Mail im Postfach gelöscht wird. Falls eine Anhang-Datei je verschwindet, kümmert sich PROJ-97 darum.
- **`list-uids` genau einmal pro Postfach pro Lauf:** Momentaufnahme im Lauf-Speicher (`staticData`, Muster PROJ-97 `Code: Load Redis Maps`), nicht pro Objekt — bei vielen `Email`-Objekten pro Postfach sonst hunderte identische IMAP-Roundtrips.
- **Flache Arbeitsliste, ein Loop (kein Loop-in-Loop):** `SplitInBatches` über eine einzige `Email`-Objektliste mit Per-Objekt-Zeitcheck — dasselbe Muster wie `alice-dms-thumbnailer-backfill` und PROJ-97.
- **Node-Namen-Zugriff für `confirm`/`time_limit_seconds`/Trigger-Erkennung:** der vorgeschaltete Lock-Node gibt ein Item ohne `body`/`query` zurück ([[PROJ-92]]-Bug). `$('Webhook: ...').first()` bzw. `$('Schedule Trigger: Monthly').first()` umgeht das. `confirm`/`time_limit_seconds` aus Body **und** Query (Muster PROJ-97 BUG-3).
- **Cron `0 1 1-7 * 1` (erster Montag 01:00 UTC):** n8n-Cron-Trigger laufen in Container-TZ = UTC. 01:00 UTC = 02:00 (Winter) / 03:00 (Sommer) Berlin. Kollisionsfrei: PROJ-97-Reconcile hält den Lock bis max. 01:00 UTC, `alice-dms-processor` startet erst 02:00 UTC. Bei Überlappung skippt der spätere Lauf sauber per Lock.
- **Sicherheit — Webhook VPN-only ohne zusätzliche Auth:** identisch zu PROJ-97 (dort als BUG-2 bewusst akzeptiert). Schutz: Alice ist nur per VPN erreichbar, der destruktive Pfad hängt hinter dem `confirm`-Gate, und der Dry-Run ist der Default. Falls die QA das anders bewertet → dort entscheiden.

### D) Dependencies (Pakete)

**n8n-Workflow:** keine neuen Pakete. `redis`, `axios`, `winston` sind in n8n Code-Nodes erlaubt und in den DMS-/Mail-Workflows durchgängig im Einsatz.

**`alice-mail-reader`-Service:** keine neuen Python-Pakete. `imaplib` ist Standard-Library und bereits importiert; `_connect` / `_decrypt_password` existieren.

### Referenz-Muster aus bestehenden Workflows / Services

| Baustein | Vorlage |
| --- | --- |
| Kompletter Trigger-/Lock-/Dry-Run-/Zeitlimit-/Response-Rahmen | `alice-dms-reconcile` (PROJ-97, `workflows/alice-dms-reconcile.json`) — 1:1 übernehmbar bis auf die Abgleich-Quelle |
| Redis-Lock (NX + TTL 65 min, sauberer Skip, Owner-checked Release, Error-Trigger-Release) | `alice-dms-reconcile` (`Code: Acquire Lock` / `IF: Lock Acquired` / `Code: Respond Locked` / `Code: Release Lock (error)`) |
| Per-Objekt-Zeitcheck + sauberer Stopp | `alice-dms-reconcile` (`Code: Time Check` / `IF: Time Limit Reached`), `alice-dms-thumbnailer-backfill` |
| `POST /list-uids`-Endpoint (Connect + Login + read-only Select + Fehlerschema) | `alice-mail-reader` `/test` und `/fetch` (`app.py`) |
| Postfach-Liste + `status='syncing'`-Check (30-min-Fenster) | `alice-mail-sync` (`PG: Check Active Syncs` / `PG: Get Pending Mailboxes`) |
| Verbindungsdaten an `alice-mail-reader` durchreichen (`password_enc` unverändert) | `alice-mail-sync` (`Prepare Mailbox Data` / `HTTP: Fetch Emails`) |
| Momentaufnahme zentral laden, per Node-Namen lesen (nicht pro Item kopieren) | `alice-dms-reconcile` (`Code: Load Redis Maps`) |
| `DELETE /thumbnail/<uuid>` aufrufen, Fehlschlag nicht blockierend | `alice-dms-reconcile` (`Code: Process Object`) + `alice-dms-thumbnailer` `app/main.py` |
| Redis-`alice:dms:*`-Cleanup nur bei gesetztem `fileHash` | `alice-dms-reconcile` (`Code: Process Object`), `alice-dms-scanner` (`Code: Find Stale Paths`) |
| `thumbnail_path` bei `Cannot query field` weglassen | PROJ-95 (`alice-dms-thumbnailer-backfill` `Code: Query Weaviate`) |
| Statistik-MQTT-Publish (`alice/mail/reconcile-stats`) | `alice-dms-reconcile` (`MQTT: Publish reconcile-stats`), `alice-dms-scanner` (`MQTT: Publish Stats`) |
| Error-Trigger → Lock-Release → Error-MQTT | `alice-dms-reconcile` (`Error Trigger` / `Code: Release Lock (error)` / `MQTT: Publish Error`) |

### Offene Punkte für `/backend`

- Exakter GraphQL-Feldname für den Objekt-Zeitstempel (`date` vs. `_additional.creationTimeUnix`) für den Race-Schutz — `Code: Query Weaviate` beide abfragen, `creationTimeUnix` bevorzugen (verlässlicher als das aus dem `Date`-Header geparste `date`).
- „Teilt ein anderes lebendes Objekt diesen `fileHash`?"-Check vor dem Redis-Cleanup: GraphQL-Count über **alle** Collections mit `fileHash`-Feld (Muster aus `alice-dms-reconcile` `Code: Process Object`).
- `alice.imap_mailboxes.status`-Wertebereich (`syncing` / `error` / `active` / `idle`?) gegen das reale Schema prüfen — nur `syncing` triggert den Skip.

## Implementation Notes (Backend)

**Stand:** Backend fertig, bereit für `/qa`.

### 1. Service-Endpoint `POST /list-uids` (`docker/compose/automations/alice-mail-reader/app.py`)

- Neuer Flask-Route-Handler analog zu `/test` / `/fetch`. Body: `{ host, port, ssl, username, password_enc, folder }`, `folder` default `"INBOX"`.
- `_connect(data)` → `imap.login(username, _decrypt_password(password_enc))` → `imap.select(folder, readonly=True)` → `imap.uid("search", None, "ALL")`.
- Erfolg: `{ "uids": [<int>, ...], "count": <n> }`. Fehler: `{ "uids": [], "error": "<msg>" }` mit HTTP 400 (`imaplib.IMAP4.error`) bzw. 500 (unerwartet) — gleiches Schema wie `/fetch`.
- Kein JWT (interner Endpoint). Read-only Select — keine Flag-Änderung, kein Expunge.
- **Erfordert Container-Rebuild + Deploy von `alice-mail-reader`** (`make` im compose-scripts-Ordner bzw. `Deploy alice-mail-reader`).

### 2. n8n-Workflow `workflows/alice-mail-reconcile.json` (23 Nodes)

1:1 an `alice-dms-reconcile` (PROJ-97) angelehnt: gleicher Lock, gleiches `confirm`-Gate, gleiches Zeitlimit-/Response-/Error-Trigger-Muster.

- **Trigger:** `Webhook: POST /alice-mail-reconcile` + `Schedule Trigger: Monthly` (Cron `0 1 1-7 * 1` = erster Montag 01:00 UTC).
- **`Code: Init Run`** — Trigger-Erkennung per Node-Namen-Zugriff (nicht `$input.first().json.body`, PROJ-92-Bug). Schedule → `mode=confirm`, `max_runtime_seconds=3600`. Webhook → `confirm` aus Body **oder** Query, `time_limit_seconds` aus Body oder Query. Nullt alle staticData-Zähler am Laufanfang.
- **`Code: Acquire Lock`** — `alice:dms:processor:lock:run` (SET NX, TTL 65 min). Redis-Fehler → `_redis_reachable=false`, fail-closed.
- **`IF: Lock Acquired`** → Nein-Zweig: `Code: Respond Locked` (`status: skipped`, `stopped_reason: locked`).
- **`PG: Load Mailboxes`** — `SELECT id::text, imap_host, imap_port, imap_username, password_enc, ssl_enabled, status, updated_at FROM alice.imap_mailboxes` (pg-alice-Credential).
- **`Code: Query Weaviate`** — flache Arbeitsliste ALLER `Email`-Objekte per GraphQL-Cursor-Paginierung: `_additional { id creationTimeUnix }`, `mailboxId`, `imapUid`, `subject`, `date`, `fileHash`, `thumbnail_path`. `fileHash` / `thumbnail_path` mit Fallback bei `Cannot query field` (PROJ-95-Muster). `imapUid` wird direkt zu `String|null` normalisiert. Weaviate unerreichbar → Sentinel `_weaviate_error`, den `Code: Plan Run` in einen sauberen `abort` (Lock-Release + `stopped_reason: locked`) überführt.
- **`Code: Plan Run`** (Run-Once-for-All-Items) — bildet die lebende `mailboxId`-Menge; bestimmt Postfächer mit ≥1 `Email`-Objekt; ruft für **jedes** dieser Postfächer **genau einmal** `POST /list-uids` auf (Momentaufnahme `{ state, uidSet, query_ts }` je `mailboxId`). `status='syncing'` UND `updated_at` < 30 min → `state=syncing`, kein IMAP-Call. HTTP != 2xx / Exception → `state=unreachable`. Leere UID-Liste → `state=empty`. Kein Loop-in-Loop — die Aufrufe passieren vorab, nicht im Objekt-Loop.
- **`Loop Over Objects`** (SplitInBatches, batchSize 1, `reset:false`) → **`Code: Process Object`**:
  - Klassifikation: `mailboxId` leer/tot → `orphan_mailbox`; Snapshot `syncing`/`unreachable`/`empty` → `keep` + passender `skipped_mailbox_*`-Zähler; kein `imapUid` → `keep` (`skipped_ok`); Objekt jünger als `snapshot.query_ts` (`creationTimeUnix` bevorzugt, sonst `date`) → `keep` (Race-Guard); `imapUid` in `uidSet` → `healthy`; sonst → `orphan_message`.
  - Bei `confirm` + Waise: `DELETE /thumbnail/<uuid>` (Port 8004, idempotent, nicht blockierend) → `DELETE /v1/objects/Email/<uuid>` → bei SHA-256-`fileHash` Redis-Cleanup (`alice:dms:hash_to_paths:<hash>` + zeigende `path_to_hash` + `alice:dms:processed`), aber nur wenn kein lebendes Objekt aus `Invoice/BankStatement/Document/SecuritySettlement/Contract/Email` denselben Hash per GraphQL-`Aggregate`-Count noch nutzt.
  - Weaviate-DELETE-Fehler → Zähler-Dekrement + `skipped_ok`, kein Abbruch.
  - Zähler-Semantik „planned-or-done" wie PROJ-97 (Dry-Run zählt geplant, Confirm zählt ausgeführt).
- **`Code: Time Check`** → **`IF: Time Limit Reached`** — pro Objekt, sauberer Loop-Ausstieg.
- **`Code: Build Summary`** — aggregierte Zähler, Owner-checked Lock-Release per Lua-`eval`. `remaining` = `total_objects - checked` bei Zeitlimit, sonst 0.
- **`IF: From Webhook`** → `Respond to Webhook` (JSON) bzw. `MQTT: Publish alice/mail/reconcile-stats` (qos 1) → `End (Schedule)`.
- **`Error Trigger`** → `Code: Release Lock (error)` (nur DEL wenn `workflow==alice-mail-reconcile`) → `MQTT: Publish alice/mail/error`.
- **Kein `alice/dms/done`** (reine Löschung).
- Error-Workflow: `po2OuxzG5htVHK6E` (alice-dms-lifecycle).

### Abweichungen / Klärungen zur Spec

- **`imap_mailboxes.status`-Wertebereich:** real aktuell nur `syncing` beobachtet; `alice-mail-sync` setzt zusätzlich `active` / `error`. Nur `syncing` (+ 30-min-Fenster) triggert den Skip — exakt wie `alice-mail-sync` `PG: Check Active Syncs`.
- **Race-Zeitstempel:** `Code: Query Weaviate` fragt `_additional { creationTimeUnix }` ab und bevorzugt das gegenüber dem aus dem `Date`-Header geparsten `date` (Spec „Offene Punkte für /backend").
- **fileHash-Shared-Check:** GraphQL-`Aggregate`-Count über alle Collections mit `fileHash`-Feld; jeder Fehler dabei → konservativ „noch benutzt" → kein Redis-Cleanup.
- **Validierung:** `validate_workflow` meldet 24/24 gültige Connections, 0 invalide; die 9 `jsCode`-„Expression"-Fehler sind der bekannte False-Positive des Validators (identische „Korrektur"), die Warnungen (Webhook-typeVersion, Loop-`done`-Output) sind mit dem produktiven `alice-dms-reconcile` deckungsgleich.

### Deploy-Schritte (für `/deploy`)

1. `alice-mail-reader` rebuilden + deployen (neuer `/list-uids`-Endpoint).
2. `Deploy n8n-workflow alice-mail-reconcile`.
3. `./scripts/sync-compose.sh` (falls compose berührt — hier nicht nötig, nur `app.py`).

## QA Test Results

**Tested:** 2026-08-31
**Tester:** QA Engineer (AI) — statische Prüfung
**Prüfumfang:** `workflows/alice-mail-reconcile.json` (23 Nodes) + Service-Change `alice-mail-reader/app.py` (`POST /list-uids`). Kein Live-Lauf möglich (Workflow noch nicht deployed, `alice-mail-reader` noch nicht rebuilt). Verifikation gegen AC per Code-Lesung, Datenfluss-Trace, Node-Syntaxcheck (`node --check` für alle 9 Code-Nodes → OK), n8n-`validate_workflow` (24/24 gültige Connections, 0 invalide) und Vergleich mit dem produktiven `alice-dms-reconcile` (PROJ-97).

### Acceptance Criteria Status

#### Trigger & Betriebsmodus
- [x] `POST /webhook/alice-mail-reconcile` **und** `Schedule Trigger: Monthly` (Cron `0 1 1-7 * 1` = erster Montag 01:00 UTC — exakt wie im Tech Design gewählt, da PROJ-97 den geteilten Lock bis max. 01:00 UTC hält). Beide → `Code: Init Run`.
- [x] Webhook ohne `confirm=true` → `mode='dry-run'`: `Code: Process Object` kapselt alle DELETE/Thumbnail/Redis-Operationen in `if (confirm) {…}`; `list-uids` wird in `Code: Plan Run` **trotzdem** aufgerufen (Live-Zahlen); jede Waise per winston geloggt („DRY-RUN would delete").
- [x] Webhook mit `confirm=true` (Body **oder** Query) → Löschungen aktiv.
- [x] `confirm` und `time_limit_seconds` aus Body **und** Query gelesen (`body.X !== undefined ? body.X : query.X`), per Node-Namen-Zugriff auf den Webhook-Node (nicht `$input.first().json.body` — PROJ-92-Muster). Erledigt den PROJ-97-BUG-3 präventiv.
- [x] Schedule → immer `mode='confirm'`, `max_runtime_seconds=3600` fest. Kein Schedule-Dry-Run.
- [x] Trigger-Quelle per Node-Namen-Zugriff (`$('Schedule Trigger: Monthly').first()` / `$('Webhook: …').first()`, je in try/catch).
- [x] `Code: Acquire Lock` nimmt `alice:dms:processor:lock:run` per `SET NX PX` (TTL 65 min). Belegt → `IF: Lock Acquired` Nein-Zweig → `Code: Respond Locked` → `{ status:'skipped', stopped_reason:'locked', … }` → `IF: From Webhook` → HTTP 200 (Webhook) bzw. stiller Stopp (Schedule, kein Zweig verbunden). Ohne Warten.
- [x] Redis beim Lock-Erwerb nicht erreichbar → `catch` → `acquired=false`, `_redis_reachable=false` → fail-closed über denselben `Respond Locked`-Pfad, keine Weaviate-Operation.
- [x] Lock-Release auf **jedem** Ausgang: `Code: Build Summary` (owner-checked Lua-`eval`, auch im abort- und time_limit-Fall), `Code: Release Lock (error)` (workflow-tag-checked), TTL 65 min als Backstop.
- [x] `time_limit_seconds` → `Code: Time Check` nach **jedem** Objekt → `IF: Time Limit Reached` → sauberer Stopp mit vollständigem Response. Kein Selbstaufruf/Auto-Continue. Nicht gesetzt (Webhook) → `max_runtime_seconds=null` → alle Objekte.

#### Fall (a): Verwaiste-Postfach-Objekte
- [x] `Code: Plan Run` bildet `liveMailboxIds` aus allen `id`-Werten von `PG: Load Mailboxes`.
- [x] `Code: Process Object`: `!mailboxId || !liveMailboxIds.has(mailboxId)` → `orphan_mailbox` (leerer **und** unbekannter `mailboxId`).
- [x] `confirm=true` → `DELETE /v1/objects/Email/<uuid>`.
- [x] Fall (a) läuft **ohne** IMAP-Zugriff — die Klassifikation `orphan_mailbox` steht vor jedem Snapshot-Check; auch bei komplett unerreichbarem `alice-mail-reader` werden Postfach-Waisen erkannt und (confirm) gelöscht.

#### Fall (b): Gelöschte-Mail-Objekte
- [x] `Code: Plan Run` ruft pro Postfach mit ≥1 `Email`-Objekt, lebendem `mailboxId` und `state != 'syncing'` **genau einmal** `POST /list-uids` auf (`host/port/ssl/username/password_enc` aus `alice.imap_mailboxes`, `folder:'INBOX'`). Momentaufnahme `{ state, uidSet, query_ts }` je `mailboxId` in `staticData._plan.snapshots`.
- [x] `/list-uids` (neuer Endpoint): `imap.select('INBOX', readonly=True)` + `imap.uid("search", None, "ALL")` → `{ uids: [<int>], count }`. Read-only, keine Flag-Änderung, kein Expunge.
- [x] `Code: Process Object`: `String(imapUid)` **nicht** in `snap.uidSet` (Set aus `String(u)`) → `orphan_message`.
- [x] `confirm=true` → `DELETE /v1/objects/Email/<uuid>`.
- [x] `list-uids` HTTP != 2xx / Timeout / Exception → `snapshot.state='unreachable'` → **kein** Mail-Waisen-Löschen für dieses Postfach, `skipped_mailbox_unreachable`++ pro Objekt, winston-Warnung. Fall (a) für dieses Postfach läuft trotzdem (steht vor dem Snapshot-Check).
- [x] `list-uids` liefert `[]` → `state='empty'` → kein Löschen, `skipped_mailbox_empty`++, winston-Warnung.
- [x] `status='syncing'` UND `updated_at` < 30 min → `state='syncing'`, Postfach **komplett** übersprungen (weder a noch b — der `orphan_mailbox`-Zweig greift nicht, weil `mailboxId` ja lebt; der Snapshot-Zweig fängt es ab), `skipped_mailbox_syncing`++.

#### Löschung: Nebenwirkungen
- [x] Pro Löschung: `DELETE http://alice-dms-thumbnailer:8004/thumbnail/<uuid>` (PROJ-97-Endpoint, idempotent `missing_ok`, `validateStatus: () => true`). Fehlschlag geloggt, blockiert die Objekt-Löschung **nicht**. `thumbnail_files_removed` zählt nur `tr.data.deleted === true`.
- [x] Nicht-leerer SHA-256-`fileHash` (`/^[a-f0-9]{64}$/i`) → nach der Löschung Redis-Cleanup: `hDel path_to_hash` (alle zeigenden), `del hash_to_paths:<hash>`, `sRem processed` — **nur** wenn GraphQL-`Aggregate`-Count über `Invoice/BankStatement/Document/SecuritySettlement/Contract/Email` = 0. Jeder Aggregate-Fehler → `stillUsed=true` → kein Cleanup (konservativ).
- [x] `Email` ohne `fileHash` → `hashValid=false` → keine Redis-Operation.
- [x] Kein `alice/dms/done`-Publish irgendwo im Graphen.

#### Nicht-Ziele
- [x] `Code: Query Weaviate` fragt **nur** `Email` ab. Kein BankTransaction, keine datei-basierte Collection.
- [x] `list-uids` prüft **nur** `INBOX` (hardcoded `folder:'INBOX'` im Plan-Run-Aufruf).
- [x] Keine Löschung von PROJ-53-Anhang-DMS-Objekten oder NAS-Dateien — der Workflow fasst nur `Email`-UUIDs an.
- [x] Keine Re-Indexierung, kein Feld-PATCH, keine `category`-Änderung — nur `DELETE`.

#### Response & Logging
- [x] Webhook-Response = exakt die geforderten aggregierten Zähler: `status, mode, trigger, stopped_reason, checked, deleted_orphan_mailbox, deleted_orphan_message, thumbnail_files_removed, redis_hashes_cleaned, skipped_ok, skipped_mailbox_unreachable, skipped_mailbox_empty, skipped_mailbox_syncing, mailboxes_checked, remaining`.
- [x] Schedule: kein HTTP-Response; dieselbe Summary per winston + `alice/mail/reconcile-stats` (MQTT qos 1) → `End (Schedule)`.
- [x] Jede Löschung per winston mit UUID, `mailboxId`, `imapUid`, `subject` (JSON-escaped, auf 120 Zeichen gekürzt), Kategorie (`orphan_mailbox`/`orphan_message`), Aktion — auch im Dry-Run.
- [x] `remaining` = `total_objects − checked` bei `stopped_reason='time_limit'`, sonst 0.
- [~] `mailboxes_checked` = Postfächer mit **nicht-leerer** `list-uids`-Antwort. Ein Postfach mit erfolgreicher, aber leerer UID-Liste (`state='empty'`) wird **nicht** mitgezählt — siehe BUG-3 (Low, Semantik-Feinheit).
- [x] Zähler-Semantik „planned-or-done": `deleted_orphan_mailbox`/`deleted_orphan_message` zählen im Dry-Run geplant, im Confirm ausgeführt (bei DELETE-Fehlschlag Dekrement + `skipped_ok`++). `thumbnail_files_removed`/`redis_hashes_cleaned` nur echte Aktionen.

### Edge Cases Status

- [x] Gesundes `Email`-Objekt (lebender `mailboxId`, `imapUid` in Liste) → `healthy` → `skipped_ok`++.
- [x] `Email` ohne `imapUid` (Altbestand) → `keep` → `skipped_ok`++, winston-Warnung. Fall (a) greift trotzdem, falls `mailboxId` fehlt (steht davor).
- [x] Mail aus INBOX verschoben → UID weg aus INBOX-Liste → `orphan_message` → gelöscht. Bewusst akzeptiert (dokumentiert).
- [x] IMAP-Server down zu Lauf-Beginn → `state='unreachable'` → Postfach-Mail-Waisen bleiben; Fall-(a)-Objekte desselben Postfachs trotzdem geprüft.
- [x] Passwort nach letztem Sync geändert → `list-uids` scheitert an Auth → HTTP 400 → `state='unreachable'` → wie „down".
- [x] `list-uids` leer, Postfach real leergeräumt → `state='empty'` → kein Auto-Löschen, `skipped_mailbox_empty`++.
- [x] `status='syncing'` → `skipped_mailbox_syncing`++, komplett übersprungen.
- [x] `alice-mail-sync` indexiert eine neue Mail nachdem `list-uids` schon lief → **Race-Guard:** `Code: Process Object` vergleicht `creationTimeUnix` (bevorzugt) bzw. `new Date(date).getTime()` gegen `snapshot.query_ts`; jünger → `keep`/`skipped_ok`. Zusätzlich zum `syncing`-Check.
- [x] Redis fällt mitten im Lauf aus (nach Lock) → `fileHash`-Cleanup-`catch` loggt, bricht nicht ab; Weaviate-DELETE hängt nicht an Redis; Lock läuft per TTL aus.
- [x] Weaviate-DELETE für ein Objekt schlägt fehl → loggen, Zähler-Dekrement + `skipped_ok`++, weiter mit nächstem Objekt (idempotent im nächsten Lauf).
- [x] `thumbnail_path` zeigt auf gelöschte Datei → Service-`DELETE` idempotent (`{deleted:false}`), kein Zählerinkrement, Objekt-Löschung läuft durch.
- [x] Dry-Run meldet 40, Confirm findet 38 → kein Fehler, Confirm arbeitet mit dann-aktuellem Stand (getrennte Läufe, jeweils frische Query + frische `list-uids`).
- [x] Zeitlimit läuft ab während ein Postfach noch nicht fertig → sauberer Stopp nach aktuellem Objekt, `remaining` > 0; `list-uids`-Momentaufnahmen werden nicht wiederholt; nächster Lauf beginnt von vorn.
- [x] Erster Montag = der 1. → Cron `1-7 * 1` matcht genau einmal (identisch PROJ-97-Analyse).
- [x] Postfach in `alice.imap_mailboxes` mit 0 `Email`-Objekten → `list-uids` wird **nicht** aufgerufen (`mailboxesWithObjects`-Check), kein Sonderfall.
- [x] Schedule-Lauf bricht mit Fehler ab → `Error Trigger` → `Code: Release Lock (error)` (workflow-tag) → `MQTT: Publish alice/mail/error`; bereits gelöschte Objekte bleiben (idempotent). Kein Auto-Retry.
- [x] Weaviate unerreichbar zu Lauf-Beginn (`Code: Query Weaviate` Exception) → Sentinel `_weaviate_error` → `Code: Plan Run` `setAbortPlan('weaviate_unreachable')` → `_empty:true` → `Code: Build Summary` `stopped_reason:'locked'`, `status:'skipped'`, Lock freigegeben, nichts gelöscht.

### Security Audit Results

- [x] Kein User-Input in Weaviate-/Redis-Keys außer `confirm` (`=== true || === 'true'`) und `time_limit_seconds` (`parseInt`, `> 0`). Beide typgeprüft.
- [x] `fileHash` vor GraphQL-`Aggregate`-Nutzung per `SHA256_RE` validiert → keine GraphQL-Injektion. `weaviate_uuid` stammt aus Weaviate selbst, wird nur in die REST-URL (`DELETE /v1/objects/Email/<uuid>`) und die Thumbnailer-URL eingesetzt — akzeptables Muster wie im produktiven `alice-dms-reconcile`.
- [x] `mailboxId` wird **nicht** in GraphQL interpoliert — nur in JS mit `Set.has()` verglichen.
- [x] Neuer Endpoint `POST /list-uids`: kein JWT (interner Endpoint, nicht über nginx exponiert — konsistent mit `/test`, `/fetch`, `/attachment` im selben Service). `readonly=True`-Select — kann das Postfach nicht verändern. Klartext-Passwort verlässt den Container nie (`_decrypt_password` intern, nur `password_enc` über die Leitung).
- [x] Fehlerantworten von `/list-uids` enthalten `str(exc)` — bei fehlendem Feld ist das der Feldname (`'password_enc'`), kein Secret. IMAP-Fehlermeldungen enthalten keine Zugangsdaten.
- [x] Redis-Passwort aus `$env.REDIS_PASSWORD`, nicht hardcoded. Keine Secrets in winston-Logs (nur UUIDs, `mailboxId`, `imapUid`, Betreff, Zähler).
- [~] Webhook **ohne** JWT-Prüfung — identisch zu PROJ-97-BUG-2 (dort vom Nutzer bewusst akzeptiert) und zu allen DMS-Backfills. Destruktiver Pfad hinter `confirm`-Gate (Default Dry-Run) + VPN-only. Siehe BUG-1.

**Regression:** `alice-mail-reader` — `/list-uids` rein additiv; `/health`, `/test`, `/fetch`, `/body`, `/attachment`, `/attachment-text`, `/encrypt` unverändert (`py_compile` OK). `alice-mail-sync`, `alice-mail-api`, alle DMS-Workflows nicht angefasst. Geteilter Lock-Key erweitert die bestehende Skip-Logik um einen Teilnehmer, ändert sie nicht. `alice-dms-thumbnailer` `DELETE /thumbnail/{uuid}` unverändert wiederverwendet.

### Bugs Found

#### BUG-1: Reconcile-Webhook ohne Authentifizierung löst destruktive Löschungen aus — ⚖️ AKZEPTIERT (Nutzerentscheidung 2026-08-31, analog PROJ-97-BUG-2)
- **Severity:** Medium
- **Detail:** `POST /webhook/alice-mail-reconcile` hat keine JWT-/Token-Prüfung. Mit `confirm=true` löscht der Aufruf endgültig `Email`-Weaviate-Objekte (inkl. Vektor + deutscher LLM-Zusammenfassung). Schutz: VPN-only, `confirm`-Gate (Default = Dry-Run), nginx-Pfad, Fail-safe-Regeln.
- **Entscheidung:** Bewusst **so belassen** — konsistent mit `alice-dms-reconcile` und den DMS-Backfills. Kein Auth-Node. VPN-only + `confirm`-Gate gelten als ausreichend.

#### BUG-2: `Code: Plan Run` löschte bei 0 PG-Zeilen potenziell die gesamte `Email`-Collection — ✅ BEHOBEN (in-Iteration)
- **Severity:** High
- **Detail:** Liefert `PG: Load Mailboxes` eine **leere** Ergebnismenge (Postgres gibt `[]` ohne Fehler zurück — z.B. Query-Fehler der als leer durchrutscht, oder alle Postfächer per DB-Direktzugriff gelöscht), war `liveMailboxIds` leer → **jedes** `Email`-Objekt → `orphan_mailbox` → im Confirm-/Schedule-Modus Totallöschung. Verletzt die Fail-safe-Asymmetrie der Spec (irreversible Löschung nur bei Eindeutigkeit).
- **Fix (2026-08-31):** `if (mailboxRows.length === 0 && work.length > 0)` → `setAbortPlan('no_mailbox_rows')` → sauberer `status:'skipped'`, Lock freigegeben, **nichts gelöscht**, winston-Warnung. Bei 0 Postfächern **und** 0 `Email`-Objekten läuft der Workflow normal durch (nichts zu tun). Der legitime „ein Postfach echt gelöscht"-Fall (Postfächer > 0, eines davon fehlt) ist davon unberührt und funktioniert weiter.

#### BUG-3: `mailboxes_checked` zählt Postfächer mit leerer UID-Liste nicht mit — ⚖️ DOKUMENTIERT
- **Severity:** Low
- **Detail:** AC: „`mailboxes_checked` = Anzahl Postfächer, für die `list-uids` erfolgreich abgefragt wurde." Die Implementierung erhöht den Zähler nur bei `state='ok'` (nicht-leere Liste). Ein Postfach mit erfolgreicher, aber leerer Antwort (`state='empty'`) wird als „nicht geprüft" gewertet, obwohl der Call erfolgreich war. `skipped_mailbox_empty` bildet diesen Fall separat ab, die Gesamtzahl ist also rekonstruierbar.
- **Empfehlung:** So belassen (leere Liste = übersprungen, „checked" impliziert verwertbare Daten) oder Ein-Zeilen-Fix (`mailboxesChecked++` auch im `empty`-Zweig). Kein Blocker.

#### BUG-4: Kein Webhook-Response bei Absturz nach Lock-Acquire — ⚖️ DOKUMENTIERT (identisch PROJ-97-BUG-5)
- **Severity:** Low
- **Detail:** Stürzt der Lauf nach erfolgreichem Lock ab, greift `Error Trigger` → Lock-Release + `alice/mail/error`, aber `Respond to Webhook` wird nie erreicht → HTTP-Client hängt bis nginx-Timeout (300 s). Gleiche Einschränkung wie `alice-dms-reconcile` und die DMS-Backfills.
- **Empfehlung:** Nice-to-have, dokumentiert.

#### BUG-5: `Code: Query Weaviate` GraphQL-`errors` (kein Exception) bricht die Paginierung ab und verarbeitet eine Teilmenge — ⚖️ DOKUMENTIERT (identisch PROJ-97-Verhalten)
- **Severity:** Low
- **Detail:** Gibt Weaviate ein `errors`-Array aus einem anderen Grund als fehlendem `thumbnail_path`/`fileHash` zurück (z.B. transienter Fehler mitten in der Cursor-Paginierung), wird geloggt und `break`. Der Lauf arbeitet dann mit den bis dahin geladenen Objekten weiter. Folge: einige Objekte werden in diesem Lauf nicht geprüft — aber **nichts wird fälschlich gelöscht** (Fail-safe bleibt). Nächster Lauf holt sie nach.
- **Empfehlung:** So belassen, konsistent mit `alice-dms-reconcile`.

### Summary
- **Acceptance Criteria:** alle Kategorien erfüllt. 1 Semantik-Feinheit bei `mailboxes_checked` (BUG-3, Low).
- **Edge Cases:** 18/18 abgedeckt (inkl. Weaviate-unerreichbar-Abbruch, nicht in der Spec-Liste, aber implementiert).
- **Bugs Found:** 5 total (0 Critical, 1 High, 1 Medium, 3 Low). **BUG-2 (High) in-Iteration behoben und per Datenfluss-Trace + Node-Syntaxcheck re-verifiziert.** BUG-1 (Medium) vom Nutzer 2026-08-31 bewusst akzeptiert (kein Auth-Node, analog PROJ-97-BUG-2). BUG-3/4/5 (Low) dokumentiert.
- **Security:** Pass. Fehlende Webhook-Auth bewusst konsistent mit dem etablierten DMS-Reconcile-/Backfill-Muster.
- **Production Ready:** **JA** — kein Critical/High offen (BUG-2 behoben), BUG-1 akzeptiert. → Status **Approved**.

### Offene Deploy-Voraussetzungen (kein QA-Blocker, aber vor Live-Betrieb nötig)
1. `alice-mail-reader` Container-Rebuild + Deploy (`/list-uids` sonst 404 → jedes Postfach `unreachable` → nur Fall (a) wirkt).
2. `Deploy n8n-workflow alice-mail-reconcile`.
3. Empfohlen: 1 Dry-Run über den Webhook (`time_limit_seconds` optional) zur Sichtprüfung der Zähler vor dem ersten `confirm`-Lauf — analog PROJ-97-Vorgehen.

## Deployment
_To be added by /deploy_

## Deployment
_To be added by /deploy_
