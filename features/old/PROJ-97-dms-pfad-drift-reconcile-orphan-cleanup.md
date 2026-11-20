# PROJ-97: DMS Pfad-Drift-Reconcile + Cleanup verwaister Weaviate-Objekte

## Status: Deployed
**Created:** 2026-08-31
**Last Updated:** 2026-08-31 (Deployed + 2 Dry-Run-Läufe verifiziert; `confirm`-Lauf steht noch aus; Status → Deployed)

## Dependencies

- Betrifft: `alice-dms-thumbnailer-backfill` (n8n-Workflow, [[PROJ-95]]) — reparierte Objekte werden von diesem bzw. dem Live-Thumbnailer aufgegriffen.
- Betrifft: `alice-dms-lifecycle` (n8n-Workflow) — nutzt denselben `delete_file`-/`update_path`-Ansatz (Cascade-Delete BankTransaction-Kinder, `filePath`-PATCH), den PROJ-97 als Batch nachzieht.
- Nutzt die von `alice-dms-scanner` / `alice-dms-path-worker` gepflegten Redis-Keys `alice:dms:path_to_hash`, `alice:dms:hash_to_paths:<hash>`, `alice:dms:processed`.
- Folgt den in [[PROJ-92]] / [[PROJ-94]] / [[PROJ-95]] / [[PROJ-96]] etablierten Backfill-Mustern (Webhook-Trigger, Redis-Lock `alice:dms:processor:lock:run`, optionaler `time_limit_seconds`-Parameter, kein Auto-Continue).
- Zusätzlich ein monatlicher `Schedule Trigger` (erster Montag im Monat, 01:00 Uhr) — zu dieser Zeit läuft kein anderer zeitgesteuerter Workflow (`alice-dms-scanner` 07–22 Uhr, `alice-dms-processor` 02:00, `alice-dms-image-description-backfill` 23:30/06:00).
- **Email-Konsistenz ist NICHT Teil dieser Spec** — wird als [[PROJ-98]] separat behandelt (IMAP-basierte Waisen-Erkennung).

## Kontext

Beim ersten Produktivlauf des PROJ-95-Backfills (`alice-dms-thumbnailer-backfill`, Execution 164088, 2026-08-30) fielen zwei vorbestehende Datenqualitätsprobleme auf, die keiner der bestehenden Workflows behebt:

- **~700 datei-basierte Weaviate-Objekte ohne `filePath`.** Sie bekommen nie ein Thumbnail (keine Rendering-Quelle), tauchen aber in Trefferlisten der DMS-Bibliothek auf. Der Vergleich mit einem Lauf von vor PROJ-95 (Execution 161941) zeigt: dasselbe Problem, dort wurden 5965 von 6047 Objekten aus diesem Grund übersprungen. Ursache laut Nutzer: Alt-Importe, deren `filePath` (und teils `fileHash`) nie befüllt wurde.
- **~35 Objekte mit veraltetem `filePath`.** Die Datei wurde im NAS verschoben; Weaviate zeigt weiter den alten Ort. Der Thumbnailer-Service antwortet mit HTTP 422, weil die Datei am gespeicherten Pfad nicht existiert.

**Warum kein bestehender Workflow das löst:**

- `alice-dms-scanner` → `Code: Find Stale Paths`: bereinigt nur die Redis-Map `alice:dms:path_to_hash` (entfernt Einträge, deren Datei weg ist) und schickt eine `delete_file`-MQTT-Nachricht. Er prüft **nicht** Weaviate-Objekte, die in Redis gar nicht (mehr) referenziert sind.
- `alice-dms-lifecycle` → `update_path` / `Code: PATCH filePath`: PATCHt `filePath` nur, wenn `Code: Weaviate Find by Hash` das Objekt über `fileHash` findet. Objekte mit fehlendem/falschem `fileHash` werden nie gefunden → nie repariert. Und `update_path` wird nur ausgelöst, wenn die verschobene Datei am neuen Ort **erneut gescannt** wird und ihr Hash noch in `alice:dms:processed` steht.
- `alice-dms-classification-backfill`: korrigiert die Klassifikation (Collection-Zuordnung), fasst `filePath` nie an.

**Gewählter Lösungsansatz** (Nutzerentscheidungen in der Spec-Phase):

Ein neuer Batch-Workflow **`alice-dms-reconcile`** (manueller Webhook + monatlicher Schedule), der den Weaviate-Bestand gegen die von Scanner/Path-Worker gepflegte Redis-Wahrheit (`alice:dms:path_to_hash` / `alice:dms:hash_to_paths:<hash>`) abgleicht:

1. **Verwaiste Objekte löschen.** Ein datei-basiertes Objekt, dessen `filePath` (a) fehlt oder (b) auf eine nicht existierende Datei zeigt, **und** das über seinen `fileHash` keiner lebenden Datei in Redis zugeordnet werden kann, gilt als verwaist und wird endgültig aus Weaviate gelöscht — inkl. Cascade-Delete der BankTransaction-Kinder (falls BankStatement) und Löschen der zugehörigen `thumbnails/<uuid>.jpg`-Datei. Objekte ohne verwertbaren `fileHash` sind damit immer nicht-reparierbar → sie werden gelöscht; existiert die Quelldatei noch, indexiert der nächste `alice-dms-scanner`-Lauf sie als „new" neu.
2. **Pfad-Drift reparieren.** Kann ein Objekt mit fehlendem/veraltetem `filePath` über seinen `fileHash` einer real existierenden Datei (`alice:dms:hash_to_paths:<hash>` + `fs.existsSync`) zugeordnet werden, wird `filePath` (und `fileName`/`fileType`, falls abweichend) per PATCH auf den lebenden Pfad gesetzt. Das Objekt bleibt erhalten.
3. **Match auch über Pfad, nicht nur Hash.** Der Reconcile gleicht primär über `fileHash` gegen Redis ab; wo das kein Ergebnis liefert, wird zusätzlich der gespeicherte `filePath` selbst gegen `alice:dms:path_to_hash` und `fs.existsSync` geprüft (deckt Objekte mit kaputtem `fileHash` ab, deren Pfad noch stimmt).
4. **BankTransaction: Parent-Existenz.** Ein BankTransaction-Objekt, dessen `parentStatementId` auf kein existierendes BankStatement-Objekt (mehr) zeigt, ist eine Cascade-Delete-Waise und wird gelöscht.
5. **Nach erfolgreicher `filePath`-Reparatur** published der Reconcile pro Objekt eine `alice/dms/done`-MQTT-Nachricht → der Live-`alice-dms-thumbnailer` erzeugt das fehlende Thumbnail sofort.
6. **`confirm`-Gate (nur Webhook).** Ein Webhook-Aufruf ohne `confirm=true` ist ein reiner Dry-Run: identifiziert + zählt + loggt alle Waisen und reparierbaren Objekte, schreibt nichts. Mit `confirm=true` werden Reparatur-PATCH und Löschungen ausgeführt.
7. **Monatlicher Schedule-Lauf: `confirm` implizit.** Der `Schedule Trigger` (erster Montag im Monat, 01:00 Uhr) fährt immer im Ausführungsmodus (Reparatur + Löschung), mit fest hinterlegtem `max_runtime_seconds = 3600`. Ein Dry-Run als monatliche Automatik brächte keinen Nutzen (niemand macht nachts einen zweiten confirm-Aufruf). Die Fail-safe-Regel (bei jeder Unsicherheit „behalten") schützt vor Fehllöschungen.
8. **Redis-Lock + optionales Zeitlimit.** `alice:dms:processor:lock:run` (fail-closed, sauberer Skip bei belegtem Lock). Webhook: optionaler `time_limit_seconds`-Parameter; Schedule: fest 3600 s. Per-Objekt-Zeitcheck, sauberer Stopp mit vollständigem Response bzw. Log, kein Auto-Continue. Der Lock stellt sicher, dass Schedule- und Webhook-Lauf nie gleichzeitig schreiben — startet der eine, während der andere läuft, beendet sich der zweite sauber mit `stopped_reason: 'locked'`. Der Webhook-Trigger bleibt dabei jederzeit unabhängig vom Schedule aufrufbar.

Kein neuer Redis-Key, keine Schema-Änderung an Weaviate. `alice-dms-scanner`, `alice-dms-lifecycle` und `alice-dms-classification-backfill` bleiben unverändert.

## User Stories

- Als Admin möchte ich einen Reconcile-Lauf anstoßen können, der Weaviate-Objekte ohne auffindbare Quelldatei erkennt und entfernt, damit die DMS-Bibliothek keine „Geister-Dokumente" ohne Inhalt und ohne Thumbnail mehr anzeigt.
- Als Admin möchte ich, dass Dokumente, die im NAS verschoben wurden, in Weaviate automatisch auf den neuen Pfad korrigiert werden, damit Thumbnail-Generierung und Datei-Zugriff wieder funktionieren, ohne die Datei manuell neu importieren zu müssen.
- Als Admin möchte ich den Reconcile zuerst als Dry-Run fahren können, damit ich sehe, wie viele und welche Objekte gelöscht bzw. repariert würden, bevor ich die irreversible Löschung freigebe.
- Als Admin möchte ich den Reconcile mit einer festen Laufzeit starten können (z.B. per Postman `time_limit_seconds=3500`), damit ich einen großen Bestand kontrolliert in Teilmengen abarbeiten kann.
- Als Admin möchte ich, dass der Reconcile nicht zeitgleich mit der stündlichen DMS-Verarbeitung um Ressourcen konkurriert, damit beide Läufe verlässlich durchlaufen.
- Als Nutzer möchte ich, dass ein repariertes Dokument möglichst sofort sein fehlendes Thumbnail bekommt, damit ich nach dem Reconcile nicht noch einen zweiten Backfill anstoßen muss.
- Als Admin möchte ich, dass die Qualitätsprüfung einmal im Monat automatisch läuft, damit sich Pfad-Drift und verwaiste Objekte nicht über Monate ansammeln, ohne dass ich daran denken muss.

## Acceptance Criteria

**Trigger & Betriebsmodus:**
- [ ] `alice-dms-reconcile` wird per `POST /webhook/alice-dms-reconcile` **oder** per `Schedule Trigger` (Cron `0 1 1-7 * 1` → erster Montag im Monat, 01:00 Uhr) ausgelöst.
- [ ] **Webhook ohne `confirm=true`:** Dry-Run — der Lauf identifiziert alle Kandidaten, zählt sie nach Kategorie, loggt jeden einzelnen per winston (UUID, Collection, letzter bekannter `filePath`, geplante Aktion), führt **keine** Weaviate-Schreib-/Löschoperation und **kein** MQTT-Publish aus.
- [ ] **Webhook mit `confirm=true`:** Reparatur-PATCH, Löschungen und `alice/dms/done`-Publishes werden ausgeführt.
- [ ] **Schedule Trigger:** läuft immer im Ausführungsmodus (implizites `confirm`), mit fest hinterlegtem `max_runtime_seconds = 3600`. Es gibt keinen Schedule-Dry-Run.
- [ ] Der Ausführungsmodus (`dry-run` / `confirm`) wird per Node-Namen-Zugriff bestimmt: fired der `Schedule Trigger` → `confirm`; fired der Webhook → `confirm` nur bei `body.confirm === true`.
- [ ] `alice-dms-reconcile` nimmt vor Verarbeitungsbeginn den Redis-Lock `alice:dms:processor:lock:run` (NX, TTL als Fallback). Ist der Lock belegt (nächtlicher Processor, ein anderer Backfill, oder ein parallel gestarteter Reconcile), beendet sich der Workflow sauber mit `{ status: 'skipped', stopped_reason: 'locked', message: 'Lauf bereits aktiv' }`, HTTP 200 bzw. still im Schedule-Fall, ohne zu warten. Der Lock wird nach Abschluss (Erfolg, Zeitlimit-Stopp, Fehler) zuverlässig freigegeben.
- [ ] Der Webhook-Trigger ist jederzeit unabhängig vom Schedule aufrufbar. Ein manuell gestarteter Webhook-Lauf und der Monatslauf können nicht gleichzeitig schreiben — der zweite skippt per Lock.
- [ ] Optionaler `time_limit_seconds`-Parameter im Webhook-Body: gesetzt → nach jedem verarbeiteten Objekt Zeitcheck, bei Ablauf sauberer Stopp mit vollständigem Response; nicht gesetzt (und Webhook) → alle Objekte über alle geprüften Collections werden verarbeitet. Kein Selbstaufruf/Auto-Continue.

**Verwaiste datei-basierte Objekte (Invoice, BankStatement, Document, SecuritySettlement, Contract, Image):**
- [ ] Ein Objekt gilt als verwaist, wenn: (`filePath` fehlt ODER `fs.existsSync(filePath) === false`) UND kein Eintrag in `alice:dms:hash_to_paths:<fileHash>` auf eine per `fs.existsSync` verifizierbare Datei zeigt UND der gespeicherte `filePath` (falls vorhanden) nicht als Key in `alice:dms:path_to_hash` mit existierender Datei auftaucht.
- [ ] Objekte ohne verwertbaren `fileHash` (leer, kein SHA-256-Format) und ohne gültigen `filePath` werden als verwaist behandelt.
- [ ] Bei `confirm=true` wird ein verwaistes Objekt per `DELETE /v1/objects/<Class>/<uuid>` aus Weaviate entfernt.
- [ ] Ist das verwaiste Objekt ein BankStatement, werden zuvor alle BankTransaction-Kinder (`parentStatementId == <uuid>`) per GraphQL-Get + DELETE-by-ID entfernt (gepagt, Muster aus `alice-dms-lifecycle` `Code: Handle delete_file`).
- [ ] Existiert `thumbnails/<uuid>.jpg` (bzw. der in `thumbnail_path` hinterlegte Pfad), wird die Thumbnail-Datei mitgelöscht.
- [ ] Zugehörige Redis-Reste werden bereinigt: `fileHash` aus `alice:dms:processed` entfernen, `alice:dms:hash_to_paths:<fileHash>` und alle zeigenden `alice:dms:path_to_hash`-Einträge löschen (nur sofern kein anderes lebendes Objekt denselben Hash nutzt).

**Pfad-Drift-Reparatur:**
- [ ] Zeigt der `fileHash` eines Objekts mit fehlendem/veraltetem `filePath` über `alice:dms:hash_to_paths:<fileHash>` auf genau eine per `fs.existsSync` verifizierte Datei, wird bei `confirm=true` `filePath` per PATCH auf diesen Pfad gesetzt.
- [ ] `fileName` und `fileType` werden mit-gepatcht, wenn sie vom neuen Pfad abweichen (Basename / Extension).
- [ ] Steht der lebende Pfad bereits in `additionalPaths` des Objekts, wird `filePath` auf diesen Wert gehoben und `additionalPaths` entsprechend bereinigt (kein doppelter Eintrag).
- [ ] Zeigen mehrere lebende Pfade auf denselben `fileHash`, wird der lexikografisch erste als `filePath` gesetzt, die übrigen in `additionalPaths` aufgenommen (Muster aus `alice-dms-lifecycle` `add_path`).
- [ ] Nach erfolgreichem `filePath`-PATCH published der Workflow eine `alice/dms/done`-MQTT-Nachricht mit `{ document_type, weaviate_uuid, file_path, file_type, inserted: true }` (Format kompatibel zu `alice-dms-thumbnailer`s `Code: Parse & Filter`).

**BankTransaction-Konsistenz:**
- [ ] Für jedes BankTransaction-Objekt wird geprüft, ob `parentStatementId` auf ein existierendes BankStatement-Objekt zeigt (GraphQL-Get by ID).
- [ ] Zeigt `parentStatementId` auf kein (mehr) existierendes BankStatement, wird das BankTransaction-Objekt bei `confirm=true` gelöscht (Cascade-Delete-Waise).
- [ ] BankTransaction-Objekte werden nicht auf `filePath` geprüft (haben systembedingt keinen).

**Email:**
- [ ] Email-Objekte werden von diesem Workflow **nicht** angefasst — weder geprüft, repariert noch gelöscht (siehe [[PROJ-98]]).

**Response & Logging:**
- [ ] Der Webhook-Response enthält ausschließlich aggregierte Zähler: `{ status, mode: 'dry-run' | 'confirm', trigger: 'webhook' | 'schedule', stopped_reason: 'completed' | 'time_limit' | 'locked', checked, path_repaired, deleted_orphan, deleted_cascade_banktx, deleted_orphan_banktx, thumbnail_files_removed, done_events_published, skipped_ok, remaining }`.
- [ ] Der Schedule-Lauf hat keinen HTTP-Response — dieselbe Zusammenfassung wird per winston geloggt und nach `alice/dms/reconcile-stats` (MQTT) published (Muster analog `alice-dms-scanner` `MQTT: Publish Stats`).
- [ ] Jede einzelne Aktion (Reparatur, Löschung, Cascade) wird per winston geloggt mit UUID, Collection, letztem bekannten Pfad und Aktion — unabhängig vom Trigger.
- [ ] `remaining` = Anzahl noch nicht geprüfter Objekte der flachen Arbeitsliste bei Zeitlimit-Stopp; 0 bei vollständigem Lauf.

**Nicht-Ziele:**
- [ ] Der Workflow ändert die Klassifikation (Collection) eines Objekts nicht — das bleibt `alice-dms-classification-backfill`.
- [ ] Der Workflow scannt die NAS-Verzeichnisse nicht selbst — er verlässt sich auf die von Scanner/Path-Worker gepflegte Redis-Map plus `fs.existsSync`-Verifikation.

## Edge Cases

- **Objekt hat `filePath`, Datei existiert dort, aber kein `thumbnail_path`:** kein Reconcile-Fall — das Objekt ist gesund, `alice-dms-thumbnailer-backfill` (PROJ-95) kümmert sich um das Thumbnail. `skipped_ok` erhöhen.
- **Objekt ohne `filePath`, aber `fileHash` zeigt auf lebende Datei:** Reparatur-Fall (Punkt 2), nicht Löschung.
- **Objekt mit veraltetem `filePath`, Datei per `fileHash` an neuem Pfad gefunden:** `filePath` auf neuen Pfad patchen, Objekt behalten (deckt die 35 gescheiterten 422-Fälle ab, sofern die Datei noch in einem Watched-Folder liegt).
- **Objekt ohne `filePath` UND ohne verwertbaren `fileHash`:** verwaist → löschen. Existiert die Datei noch irgendwo, wird sie beim nächsten `alice-dms-scanner`-Lauf als „new" neu indexiert (inkl. LLM-Klassifizierung).
- **`alice:dms:hash_to_paths:<fileHash>` enthält mehrere Pfade, aber alle Dateien existieren nicht:** kein lebender Pfad → Objekt verwaist → löschen; alle toten Redis-Einträge mit bereinigen.
- **Redis nicht erreichbar zu Lauf-Beginn:** Lock-Acquire schlägt fail-closed fehl → Workflow beendet sich mit `stopped_reason: 'locked'` / entsprechender Meldung, keine Weaviate-Operationen.
- **Redis fällt mitten im Lauf aus:** der laufende Zeit-/Verarbeitungs-Check behandelt den Redis-Fehler wie „kein Match gefunden" — im Zweifel wird ein Objekt **nicht** gelöscht (fail-safe: lieber eine Waise stehen lassen als ein gültiges Objekt löschen). Loggen und im Zähler `skipped_ok` führen.
- **BankStatement wird als verwaist gelöscht, während parallel ein `alice-dms-processor`-Lauf dessen BankTransaction-Kinder neu schreibt:** durch den geteilten Redis-Lock `alice:dms:processor:lock:run` ausgeschlossen — Reconcile und nächtlicher Processor laufen nie gleichzeitig.
- **Zeitlimit läuft genau während der Cascade-Löschung eines BankStatements mit vielen Kindern ab:** die laufende Cascade wird zu Ende geführt (das Statement-Objekt darf nicht ohne seine Kinder oder umgekehrt zurückbleiben), danach greift der Zeit-Check und stoppt.
- **Dry-Run meldet 700 Löschungen, `confirm`-Lauf findet nur 690:** in der Zwischenzeit hat der Scanner 10 Dateien neu indexiert oder ein `update_path` ist durchgelaufen — kein Fehler, der `confirm`-Lauf arbeitet mit dem dann aktuellen Stand.
- **`thumbnail_path` auf dem Objekt zeigt auf eine Datei, die nicht mehr existiert:** Löschversuch der Thumbnail-Datei schlägt fehl → loggen, nicht abbrechen; Objekt-Löschung trotzdem durchführen.
- **Ein reparierter `filePath` published `alice/dms/done`, aber der Thumbnailer ist gerade down:** kein Reconcile-Fehler — die Nachricht geht verloren, das Objekt hat aber jetzt einen gültigen `filePath` und wird beim nächsten `alice-dms-thumbnailer-backfill`-Lauf aufgegriffen.
- **Objekt-`filePath` liegt außerhalb aller aktuell in `alice.dms_watched_folders` konfigurierten Ordner** (Ordner wurde aus der Watch-Liste entfernt): `alice:dms:path_to_hash` enthält den Pfad dann nicht mehr, die Datei ist per `fs.existsSync` evtl. trotzdem noch da. Verhalten: wenn `fs.existsSync(filePath) === true`, gilt das Objekt als gesund (`skipped_ok`), auch wenn der Ordner nicht mehr gewatcht wird — Reconcile löscht nichts, dessen Datei real existiert.
- **Der Monatslauf trifft auf `alice-dms-processor` (02:00) oder einen manuell gestarteten Backfill:** der Schedule-Lauf startet um 01:00 und ist mit `max_runtime_seconds = 3600` spätestens 02:00 fertig — knapp vor dem Processor. Läuft er wegen eines großen Bestands länger, nimmt der Processor um 02:00 den Lock nicht (Schedule-Lauf hält ihn) und skippt seinerseits sauber; der Reconcile-Lauf läuft zu Ende, der Processor läuft in der nächsten Nacht. Umgekehrt: hält der Processor den Lock noch um 01:00, skippt der Monatslauf und wird im nächsten Monat (oder manuell) nachgeholt.
- **Der erste Montag im Monat fällt auf den 1.:** Cron `0 1 1-7 * 1` matcht (Tag 1 UND Montag) — genau ein Lauf. Kein Doppel-Lauf, weil `1-7 * 1` „Tag im Bereich 1–7 UND Wochentag Montag" bedeutet und das im Monat nur einmal zutrifft.
- **Schedule-Lauf bricht mit Fehler ab (z.B. Weaviate mitten im Lauf weg):** der Lock wird über `Code: Release Lock` bzw. die TTL freigegeben; bereits gelöschte/reparierte Objekte bleiben so (idempotent), der Rest wird im nächsten Monatslauf erledigt. Kein Auto-Retry.

## Technical Requirements (optional)

- Kein neuer Redis-Key — Wiederverwendung von `alice:dms:processor:lock:run` und der bestehenden `alice:dms:*`-Map-Keys.
- Kein Selbstaufruf-Mechanismus (bewusste Abweichung von [[PROJ-96]]) — konsistent mit den Backfills mit explizitem `time_limit_seconds` ([[PROJ-92]], [[PROJ-94]], [[PROJ-95]]).
- Weaviate-Abfrage bleibt eine flache Liste über die geprüften Collections (kein Loop-in-Loop) — Collection-Zugehörigkeit steuert nur den Query-Aufbau, die Iteration ist ein einzelner Loop.
- `time_limit_seconds` und `confirm` per Node-Namen-Zugriff auf den Webhook-Node lesen (nicht `$input.first().json.body`) — der vorgeschaltete Lock-Node liefert ein Item ohne `body` (PROJ-92-Bug). Der `Schedule Trigger` wird ebenfalls per Node-Namen erkannt (`$('Schedule Trigger: Monthly').first()`), um `confirm=true` + `max_runtime_seconds=3600` zu setzen.
- Schedule-Cron: `0 1 1-7 * 1` (Minute 0, Stunde 1, Tag 1–7, jeder Monat, Wochentag Montag) — trifft pro Monat genau den ersten Montag.
- Fail-safe bei Unsicherheit: ein Objekt wird nur gelöscht, wenn eindeutig keine lebende Quelldatei zugeordnet werden kann. Jeder Redis-/Weaviate-Fehler während der Zuordnung führt zu „behalten", nicht „löschen".
- GraphQL-Feldnamen: datei-basierte Collections `filePath`/`fileHash`/`fileName`/`fileType`/`additionalPaths`/`thumbnail_path`; Image nutzt `file_path`/`file_hash`; `thumbnail_path` ggf. separat abfragen und bei `Cannot query field`-Fehler weglassen (Muster aus [[PROJ-95]]).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### E) Workflow-Architektur

PROJ-97 hat keine UI-Komponente. Es ist ein **neuer n8n-Workflow** `alice-dms-reconcile` (neue Datei `workflows/alice-dms-reconcile.json`). Die drei benachbarten Workflows (`alice-dms-scanner`, `alice-dms-lifecycle`, `alice-dms-classification-backfill`) bleiben unangetastet. Keine Weaviate-Schema-Änderung, kein neuer Redis-Key.

Der Workflow gleicht den Weaviate-Bestand der datei-basierten DMS-Collections gegen die „Redis-Wahrheit" ab, die `alice-dms-scanner`/`alice-dms-path-worker` pflegen: `alice:dms:path_to_hash` (Pfad → Hash), `alice:dms:hash_to_paths:<hash>` (Hash → Pfadliste), `alice:dms:processed` (Menge bekannter Hashes). Für jedes Objekt wird eine von vier Entscheidungen getroffen: **gesund** (nichts tun), **Pfad-Drift** (filePath reparieren), **verwaist** (löschen), oder **BankTransaction-Waise** (löschen).

#### Trigger

Zwei Trigger speisen denselben Verarbeitungsgraphen:

- **`Webhook: POST /webhook/alice-dms-reconcile`** — manueller Lauf. Ohne `confirm=true` im Body ist es ein reiner **Dry-Run** (identifizieren, zählen, loggen, nichts schreiben). Mit `confirm=true` werden Reparaturen und Löschungen ausgeführt. Optionaler `time_limit_seconds`-Parameter im Body begrenzt die Laufzeit.
- **`Schedule Trigger: Monthly`** — Cron `0 1 1-7 * 1` (erster Montag im Monat, 01:00 Uhr). Läuft **immer** im Ausführungsmodus (implizites `confirm`), festes Zeitlimit 3600 s. Zu dieser Uhrzeit läuft kein anderer zeitgesteuerter DMS-Workflow.

Ein `Code: Init Run`-Node direkt hinter beiden Triggern bestimmt per **Node-Namen-Zugriff** (nicht `$input.first().json.body` — das ist der PROJ-92-Bug), welcher Trigger gefeuert hat: Schedule → `mode = confirm`, `trigger = schedule`, `max_runtime_seconds = 3600`. Webhook → `trigger = webhook`, `mode = confirm` nur wenn `body.confirm === true`, `max_runtime_seconds` aus `body.time_limit_seconds` (sonst unbegrenzt).

#### Überlappungsschutz (Lock)

Direkt nach `Code: Init Run` nimmt der Lauf den **bestehenden** Redis-Lock `alice:dms:processor:lock:run` (SET NX mit TTL als Fallback). Diesen Lock teilen sich schon `alice-dms-processor` und die anderen Backfills — dadurch laufen Reconcile und nächtlicher Processor garantiert nie gleichzeitig, und zwei Reconcile-Läufe (z.B. manueller Webhook während des Monatslaufs) können nie gleichzeitig schreiben.

Ist der Lock belegt: sauberer Abbruch mit `{ status: 'skipped', stopped_reason: 'locked' }`, HTTP 200 (Webhook) bzw. stiller Stopp (Schedule), **ohne zu warten**. Ist Redis beim Lock-Erwerb nicht erreichbar: **fail-closed** — Abbruch, keine Weaviate-Operationen (fail-safe-Grundregel: im Zweifel nichts löschen). Der Lock wird bei jedem Ausgang (Erfolg, Zeitlimit-Stopp, Fehler via Error-Trigger) über einen `Code: Release Lock`-Node zuverlässig freigegeben; die TTL ist die Rückfallebene.

#### Verarbeitungsschritte (Nodes, High-Level)

```
Trigger (Webhook | Schedule Monthly)
  |
  +-- Code: Init Run ............... Modus + Zeitlimit + Trigger-Quelle bestimmen
  +-- Code: Acquire Lock .......... alice:dms:processor:lock:run (NX)
  +-- IF: Lock Acquired
  |     |-- (nein) --> Code: Respond Locked --> Ende
  |     |-- (ja)
  +-- Code: Load Redis Maps ....... path_to_hash + processed einmalig in den Lauf-Speicher laden
  +-- Code: Query Weaviate ........ flache Arbeitsliste über alle gepruften Collections
  |                                  (Invoice, BankStatement, Document, SecuritySettlement,
  |                                   Contract, Image, BankTransaction) - ein Query-Aufbau
  |                                   je Collection, danach EINE flache Liste
  +-- IF: Nothing To Do --> Code: Build Summary --> Ende
  +-- Loop: Per Object ............ ein einzelner Loop, kein Loop-in-Loop
  |     |
  |     +-- Code: Classify Object . entscheidet: healthy | path_drift | orphan | banktx_orphan
  |     |     - datei-basiert: filePath fehlt/tot? -> hash_to_paths + fs.existsSync pruefen
  |     |                       -> sonst filePath selbst gegen path_to_hash + fs.existsSync
  |     |     - BankTransaction: parentStatementId zeigt auf lebendes BankStatement?
  |     |
  |     +-- IF: Mode == confirm
  |     |     |-- (dry-run) --> Code: Log Planned Action (winston) --> zurueck in Loop
  |     |     |-- (confirm)
  |     |           |
  |     |           +-- [path_drift]  Code: PATCH filePath (+ fileName/fileType/additionalPaths)
  |     |           |                 --> MQTT: Publish alice/dms/done
  |     |           +-- [orphan]      Code: Delete Orphan
  |     |           |                   - BankStatement? -> Cascade: BankTransaction-Kinder
  |     |           |                     gepagt per GraphQL-Get + DELETE-by-ID
  |     |           |                   - Thumbnail-Datei loeschen (thumbnails/<uuid>.jpg)
  |     |           |                   - DELETE /v1/objects/<Class>/<uuid>
  |     |           |                   - Redis-Reste bereinigen (nur wenn kein anderes
  |     |           |                     lebendes Objekt denselben Hash nutzt)
  |     |           +-- [banktx_orphan] Code: Delete BankTx Orphan --> DELETE-by-ID
  |     |           +-- [healthy]     skipped_ok++ (nichts tun)
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
  |     |-- (nein) --> MQTT: Publish alice/dms/reconcile-stats --> End (NoOp)
```

Ein `Error Trigger` → `Code: Release Lock` → `MQTT: Publish Error`-Zweig (Muster aus `alice-dms-lifecycle`) stellt sicher, dass ein Absturz mitten im Lauf den Lock nicht hängen lässt.

#### Datenfluss

**Rein:** Trigger-Kontext (Webhook-Body mit `confirm`/`time_limit_seconds`, oder Schedule-Signal). **Verarbeitung:** Redis-Maps + Weaviate-Objektliste werden geladen → jedes Objekt wird gegen die Redis-Wahrheit und `fs.existsSync` klassifiziert → im Confirm-Modus wird pro Objekt genau eine Aktion (PATCH / DELETE / Cascade-DELETE / nichts) ausgeführt → nach jeder erfolgreichen Pfad-Reparatur geht eine `alice/dms/done`-MQTT-Nachricht raus. **Raus:** Webhook-JSON mit aggregierten Zählern, bzw. (Schedule) winston-Log + `alice/dms/reconcile-stats`-MQTT.

Jede einzelne Aktion wird **immer** per winston geloggt (UUID, Collection, letzter bekannter Pfad, geplante/ausgeführte Aktion) — auch im Dry-Run.

#### Integrationen

| System | Wofür |
| --- | --- |
| **Redis** | Lesen der `alice:dms:*`-Maps (Wahrheit über lebende Dateien), Lock `alice:dms:processor:lock:run`, Bereinigen toter Map-Einträge nach Löschung |
| **Weaviate** | GraphQL-Get (Objektliste, BankStatement-Existenzprüfung, BankTransaction-Kinder), REST-PATCH (filePath-Reparatur), REST-DELETE (verwaiste Objekte) |
| **Dateisystem (NAS-Mount)** | `fs.existsSync` zur Verifikation, ob ein in Redis/Weaviate genannter Pfad real existiert; Löschen der Thumbnail-Datei |
| **MQTT** | `alice/dms/done` (nach Pfad-Reparatur → Live-Thumbnailer), `alice/dms/reconcile-stats` (Monatslauf-Statistik), `alice/dms/error` (Fehlerzweig) |

Keine neuen externen Systeme — alle vier sind in DMS-Workflows bereits im Einsatz.

#### Fehlerverhalten

- **Redis nicht erreichbar zu Lauf-Beginn:** fail-closed, Abbruch mit `stopped_reason: 'locked'`, keine Weaviate-Operation.
- **Redis fällt mitten im Lauf aus:** Redis-Fehler bei der Zuordnung wird wie „kein Match gefunden" behandelt — Objekt wird **nicht** gelöscht (fail-safe), `skipped_ok`++, geloggt.
- **Weaviate-DELETE/PATCH schlägt für ein Objekt fehl:** loggen, nicht abbrechen, mit dem nächsten Objekt weiter; das Objekt wird im nächsten Lauf erneut geprüft (idempotent).
- **Thumbnail-Datei existiert nicht mehr:** Löschversuch scheitert → loggen, Objekt-Löschung trotzdem durchführen.
- **Zeitlimit während einer Cascade-Löschung:** die laufende Cascade wird zu Ende geführt (Statement + Kinder dürfen nicht halb gelöscht zurückbleiben), **dann** greift der Zeit-Check.
- **`alice/dms/done` published, aber Thumbnailer down:** kein Reconcile-Fehler — das Objekt hat jetzt einen gültigen `filePath` und wird beim nächsten `alice-dms-thumbnailer-backfill` aufgegriffen.
- **Absturz mitten im Lauf:** `Error Trigger`-Zweig gibt den Lock frei; bereits durchgeführte Aktionen bleiben (idempotent), der Rest folgt im nächsten Lauf. Kein Auto-Retry.

### B) Datenmodell (fachlich)

**Kein neues Weaviate-Feld, kein neuer Redis-Key.** Der Workflow liest ausschließlich bestehende Strukturen:

Pro geprüftem Weaviate-Objekt relevant:
- **UUID** — Objekt-Identität, steuert DELETE-by-ID und Thumbnail-Dateinamen (`thumbnails/<uuid>.jpg`)
- **Collection** — bestimmt nur den Query-Aufbau und die GraphQL-Feldnamen (datei-basiert: `filePath`/`fileHash`/`fileName`/`fileType`/`additionalPaths`/`thumbnail_path`; `Image`: `file_path`/`file_hash`)
- **filePath** — gespeicherter Dateiort; fehlend oder auf tote Datei zeigend ist der Auslöser der Prüfung
- **fileHash** (SHA-256) — Schlüssel für den Abgleich gegen `alice:dms:hash_to_paths:<hash>`; leer/kein-SHA-256-Format = nicht reparierbar
- **additionalPaths** — Liste weiterer bekannter Pfade desselben Inhalts (Muster aus `alice-dms-lifecycle` `add_path`)
- **thumbnail_path** — optional; Ort der zu löschenden Thumbnail-Datei (bei `Cannot query field`-Fehler weglassen, Muster aus PROJ-95)
- **parentStatementId** (nur BankTransaction) — muss auf ein existierendes BankStatement zeigen, sonst Cascade-Waise

Redis-Wahrheit (nur gelesen, tote Einträge nach Löschung entfernt):
- `alice:dms:path_to_hash` — Hash `{ Pfad: Hash }`; ein Pfad hier + real existierende Datei = lebender Pfad
- `alice:dms:hash_to_paths:<hash>` — Pfadliste je Hash; mind. ein per `fs.existsSync` verifizierter Pfad = Objekt reparierbar
- `alice:dms:processed` — Menge bekannter Hashes; Eintrag wird bei Löschung bereinigt (sofern kein anderes lebendes Objekt den Hash teilt)

**Klassifikations-Logik pro Objekt (fachlich):**

```
BankTransaction?
  -> parentStatementId zeigt auf lebendes BankStatement?  ja -> healthy
                                                          nein -> banktx_orphan (loeschen)

datei-basiert:
  filePath gesetzt UND Datei existiert dort?  ja -> healthy (Thumbnail ist Sache von PROJ-95)
  sonst:
    fileHash gueltig UND hash_to_paths:<hash> hat >=1 real existierende Datei?
        ja -> path_drift (filePath auf lebenden Pfad patchen; bei mehreren:
              lexikografisch erster = filePath, Rest -> additionalPaths)
    sonst: gespeicherter filePath steht als Key in path_to_hash UND Datei existiert?
        ja -> healthy (Hash kaputt, Pfad ok - nichts zu tun)
    sonst -> orphan (loeschen)
```

Jeder Redis- oder Weaviate-Fehler während dieser Klassifikation → Ergebnis `healthy`/`skipped_ok` (fail-safe: lieber Waise behalten als gültiges Objekt löschen).

**Response-/Statistik-Objekt** (Webhook-JSON bzw. MQTT-Payload):

```
status ............... 'ok' | 'skipped'
mode ................. 'dry-run' | 'confirm'
trigger ............. 'webhook' | 'schedule'
stopped_reason ...... 'completed' | 'time_limit' | 'locked'
checked ............. Objekte insgesamt geprueft
path_repaired ....... filePath-PATCHes ausgefuehrt (bzw. geplant im Dry-Run)
deleted_orphan ...... verwaiste datei-basierte Objekte geloescht
deleted_cascade_banktx  BankTransaction-Kinder via BankStatement-Cascade geloescht
deleted_orphan_banktx   BankTransaction ohne gueltigen Parent geloescht
thumbnail_files_removed  Thumbnail-Dateien geloescht
done_events_published   alice/dms/done-MQTT-Nachrichten gesendet
skipped_ok .......... gesunde + fail-safe-behaltene Objekte
remaining ........... bei Zeitlimit-Stopp: noch nicht geprueft; sonst 0
```

### C) Tech-Entscheidungen (Begründung)

- **Neuer Workflow statt Erweiterung eines bestehenden:** `alice-dms-scanner` prüft nur Redis-Map-Konsistenz (nicht Weaviate), `alice-dms-lifecycle` repariert nur, was per `fileHash` auffindbar ist, `alice-dms-classification-backfill` fasst `filePath` nie an. Keiner deckt „Weaviate-Objekt ohne auffindbare Quelldatei" ab. Ein eigener, klar abgegrenzter Reconcile-Workflow ist sauberer als drei bestehende Workflows aufzubohren.
- **Geteilter Lock `alice:dms:processor:lock:run` statt neuem Key:** Der Reconcile darf nie gleichzeitig mit dem nächtlichen `alice-dms-processor` schreiben (BankStatement löschen, während der Processor dessen Kinder neu schreibt). Ein eigener Lock würde diesen Konflikt nicht verhindern; der geteilte Lock löst ihn ohne neuen State.
- **Kein Selbstaufruf/Auto-Continue (bewusste Abweichung von PROJ-96):** PROJ-96 muss ~24000 Bilder über Wochen sequenziell abarbeiten und braucht dafür getaktete Fenster. Hier geht es um einen einmaligen Altbestand (~700 + ~35 Objekte) plus monatliche Nachprüfung — mit `time_limit_seconds` als Sicherung reicht ein Lauf, der Rest wird beim nächsten manuellen oder Monatslauf erledigt. Konsistent mit PROJ-92/94/95.
- **Fail-safe-Asymmetrie (Redis-Fehler → „behalten"):** Eine stehen gelassene Waise ist ein kosmetisches Problem (ein Geister-Eintrag in der Bibliothek), eine Fehllöschung ist irreversibel (Weaviate-Objekt inkl. LLM-Klassifizierung und Vektor weg). Deshalb: nur löschen, wenn eindeutig keine lebende Quelldatei zugeordnet werden kann; jeder Zweifel → behalten.
- **Dry-Run nur für den Webhook, nicht für den Schedule:** Ein Monats-Dry-Run brächte keinen Nutzen — niemand fährt nachts um 01:00 einen manuellen Bestätigungslauf hinterher. Die Fail-safe-Regel plus die monatliche Wiederholung machen den automatischen Ausführungsmodus vertretbar.
- **`fs.existsSync`-Verifikation zusätzlich zur Redis-Map:** Die Redis-Map kann veraltet sein (Ordner aus der Watch-Liste entfernt, Scanner noch nicht durchgelaufen). Ein Objekt, dessen Datei real existiert, wird nie gelöscht — auch wenn Redis den Pfad nicht (mehr) kennt.
- **Flache Arbeitsliste über alle Collections, ein Loop (kein Loop-in-Loop):** Die Collection steuert nur den Query-Aufbau und die Feldnamen; die Iteration selbst ist ein einzelner `SplitInBatches`-Loop mit Per-Objekt-Zeitcheck — dasselbe Muster wie `alice-dms-thumbnailer-backfill`.
- **`alice/dms/done` nach Pfad-Reparatur statt eigener Thumbnail-Logik:** Der Live-`alice-dms-thumbnailer` hört ohnehin auf dieses Event. Ein repariertes Objekt bekommt sein Thumbnail sofort, ohne dass der Reconcile den Thumbnailer-Service selbst aufrufen muss — und ohne dass der Admin danach einen zweiten Backfill starten muss.
- **Node-Namen-Zugriff für `confirm`/`time_limit_seconds`/Trigger-Erkennung:** Der vorgeschaltete Lock-Node gibt ein Item ohne `body` zurück (dokumentierter PROJ-92-Bug). `$('Webhook: ...').first()` bzw. `$('Schedule Trigger: Monthly').first()` umgeht das.
- **Cron `0 1 1-7 * 1` für „erster Montag im Monat":** n8n/Standard-Cron verknüpft Tag-des-Monats und Wochentag mit UND, wenn beide eingeschränkt sind — Tag 1–7 UND Montag trifft pro Monat genau einmal zu. Fällt der 1. auf einen Montag, matcht genau dieser eine Tag (kein Doppel-Lauf).

### D) Dependencies (Pakete)

Keine neuen Pakete. `redis`, `fs`, GraphQL/REST über `httpRequest` und MQTT sind in n8n Code-Nodes bereits erlaubt und in den DMS-Workflows durchgängig im Einsatz. winston-Logging ist über die bestehende n8n-Compose-Konfiguration verfügbar.

### Referenz-Muster aus bestehenden Workflows

| Baustein | Vorlage |
| --- | --- |
| Redis-Lock (NX + TTL, sauberer Skip, Release bei jedem Ausgang) | `alice-dms-thumbnailer-backfill` (`Code: Acquire Backfill Lock` / `IF: Lock Acquired` / `Code: Respond Locked`) |
| Per-Objekt-Zeitcheck + sauberer Stopp | `alice-dms-thumbnailer-backfill` (`Code: Time Check` / `IF: Time Limit Reached`) |
| BankTransaction-Cascade-Delete (gepagt: GraphQL-Get + DELETE-by-ID) | `alice-dms-lifecycle` (`Code: Handle delete_file`) |
| `filePath`-PATCH inkl. `additionalPaths`-Handhabung, mehrere lebende Pfade | `alice-dms-lifecycle` (`Code: PATCH filePath`, `add_path`) |
| Redis-Map-Bereinigung toter Pfade | `alice-dms-scanner` (`Code: Find Stale Paths`) |
| `alice/dms/done`-Payload-Format | `alice-dms-thumbnailer` (`Code: Parse & Filter` — Konsument des Events) |
| Statistik-MQTT-Publish (`alice/dms/reconcile-stats`) | `alice-dms-scanner` (`MQTT: Publish Stats`) |
| Error-Trigger → Lock-Release → Error-MQTT | `alice-dms-lifecycle` (`Error Trigger` / `Code: Format Error` / `MQTT: Publish Error`) |
| `thumbnail_path` bei `Cannot query field` weglassen | PROJ-95 (`alice-dms-thumbnailer-backfill` `Code: Query Weaviate`) |

---
_Review 2026-08-31: Tech Design gegen die realen Workflows geprüft (`alice-dms-lifecycle` `Code: Handle delete_file` / `Code: PATCH filePath` / `Code: Weaviate Find by Hash`, `alice-dms-thumbnailer-backfill` `Code: Acquire Backfill Lock` / `Code: Init Run` / `Code: Query Weaviate` / `Code: Time Check` / `Code: Respond Locked`, `alice-dms-scanner` `Code: Find Stale Paths` / Schedule-Trigger-Syntax, `alice-dms-thumbnailer` `Code: Parse & Filter`). Alle Referenzmuster bestätigt: geteilter Lock-Key `alice:dms:processor:lock:run` (NX + PX-TTL 30 min, fail-closed), Node-Namen-Zugriff für Body-Parameter (PROJ-92-Bug), Per-Objekt-Zeitcheck gegen `window_start`, gepagte Cascade-Delete (limit 100, `after`-Cursor), `thumbnail_path`-Retry bei `Cannot query field`, `alice/dms/done`-Payload (`inserted: true`, `weaviate_uuid`, `document_type`, `file_path`, `file_type`). Schedule-Trigger: n8n nutzt Standard-5-Feld-Cron (`cronExpression`), `0 1 1-7 * 1` = erster Montag im Monat 01:00 (DOM+DOW mit UND bei beidseitiger Einschränkung — deckt sich mit Edge Case). **Architektur freigegeben.**_

## Implementation Notes (Backend — 2026-08-31)

**Neuer Workflow:** `workflows/alice-dms-reconcile.json` (24 Nodes, inaktiv erstellt — muss vom Nutzer deployed werden). Fehler-Workflow: `alice-dms-lifecycle` (`po2OuxzG5htVHK6E`), MQTT-Credential `Kqy6cn7hyDDXrBA0` (`mqtt-alice`), Redis über `$env.REDIS_PASSWORD`.

**Node-Kette:**
`Webhook | Schedule Trigger: Monthly` → `Code: Init Run` → `Code: Acquire Lock` → `IF: Lock Acquired` → (nein) `Code: Respond Locked` → `IF: From Webhook`; (ja) `Code: Load Redis Maps` → `Code: Query Weaviate` → `IF: Nothing To Do` → (nein) `Loop Over Objects` → `Code: Process Object` → `IF: Publish Done?` → (`MQTT: Publish alice/dms/done` →) `Code: Time Check` → `IF: Time Limit Reached` → (nein) zurück in Loop / (ja) `Code: Build Summary` → `IF: From Webhook` → `Respond to Webhook` (Webhook) bzw. `MQTT: Publish reconcile-stats` → `End (Schedule)`.
`Error Trigger` → `Code: Release Lock (error)` → `MQTT: Publish Error`.

**Abweichungen / Präzisierungen gegenüber der Spec:**

1. **Schedule-Cron `0 0 1-7 * 1` statt `0 1 1-7 * 1`.** n8n-Cron-Trigger laufen in der Container-System-TZ = **UTC** (nicht `GENERIC_TIMEZONE=Europe/Berlin` — das gilt nur für Interval-Trigger). `0 1 * * *` UTC = 02:00/03:00 Berlin und kollidiert mit `alice-dms-processor` (`0 2 * * *`, ebenfalls UTC). `0 0 1-7 * 1` = 00:00 UTC = 01:00 (Winter) / 02:00 (Sommer) Berlin; mit dem 3600-s-Limit ist der Lauf spätestens 01:00 UTC fertig, also vor dem Processor um 02:00 UTC. „Erster Montag im Monat" bleibt erhalten (DOM 1–7 UND Wochentag Montag).

2. **Thumbnail-Datei-Löschung über neuen Service-Endpoint.** Der n8n-Container mountet `/srv/warm/documents/thumbnails` **nicht** — nur `alice-dms-thumbnailer` hat Zugriff. Statt `fs.unlink` in n8n: neuer `DELETE /thumbnail/{uuid}` in `docker/compose/automations/alice-dms-thumbnailer/app/main.py` (kein JWT, interner Endpoint, idempotent, `missing_ok=True`). `Code: Process Object` ruft ihn per HTTP auf; ein Fehlschlag blockiert die Objekt-Löschung nie (Edge Case „thumbnail_path zeigt auf nicht mehr existierende Datei"). **Erfordert Container-Rebuild + Deploy von `alice-dms-thumbnailer` zusammen mit dem Workflow.**

3. **Redis-Maps zentral, nicht pro Item.** `Code: Load Redis Maps` lädt `alice:dms:path_to_hash` einmal und baut den `hash → [paths]`-Reverse-Index. `Code: Process Object` liest beides per Node-Namen-Zugriff (`$('Code: Load Redis Maps').first().json`) — die Map wird **nicht** auf jedes Arbeits-Item kopiert (Speicher). Die `alice:dms:hash_to_paths:<hash>`-Sets werden pro Objekt nur als Fallback direkt aus Redis nachgeladen.

4. **BankStatement-Existenzprüfung per REST-GET** (`GET /v1/objects/BankStatement/<uuid>`, 200 = lebt / 404 = weg) statt GraphQL-ID-Filter — eindeutig, keine `path:["id"]`-Quirks. Jeder andere HTTP-Status → fail-safe „behalten".

5. **Lock-TTL 65 min** (`LOCK_TTL_MS = 3900000`) statt 30 min — muss ≥ dem 3600-s-Schedule-Fenster sein, sonst könnte die TTL den Lock freigeben, während der Schedule-Lauf noch schreibt.

6. **`Code: Release Lock (error)`** kann den Owner-Token nach einem Crash nicht kennen (Run-Item weg); löscht den Lock daher nur, wenn `JSON.parse(lock).workflow === 'alice-dms-reconcile'` — sonst bleibt er für die TTL stehen (nie fremden Lock löschen). Der Normalpfad (`Code: Build Summary`) macht Owner-checked Release per Lua-`eval` (Muster aus `alice-dms-thumbnailer-backfill`).

7. **Fail-safe-Klassifikation:** `Code: Process Object` ist ein einziger try/catch-Block. Reihenfolge: `healthy` (Datei am `filePath` da) → `path_drift` (Hash → lebende Datei) → `healthy` (Pfad ist lebender Key in `path_to_hash`) → bei `_redis_ok === false` immer `healthy`/`skipped_ok` → sonst `orphan`. Jeder unerwartete Fehler → `catch` → `skipped_ok`, Objekt bleibt.

8. **Zähler „planned-or-done".** `path_repaired` / `deleted_orphan` / `deleted_orphan_banktx` werden bei der Klassifikationsentscheidung hochgezählt — im Dry-Run bleibt es dabei (= „würde tun"), im Confirm-Modus wird die Schreiboperation ausgeführt und bei Fehlschlag der Zähler wieder dekrementiert + `skipped_ok++`. Damit zeigt der Dry-Run-Response echte Kategorie-Zahlen (AC „zählt sie nach Kategorie"). `deleted_cascade_banktx` / `thumbnail_files_removed` / `done_events_published` zählen nur echte Aktionen (nur Confirm-Pfad).

9. **`Image`-Collection: snake_case.** Query und PATCH nutzen `file_path`/`file_hash`/`file_name`/`file_type` für `Image`, camelCase für alle anderen. `additionalPaths` ist bei allen camelCase; `thumbnail_path` wird separat abgefragt und bei `Cannot query field` weggelassen.

**Validierung:** Alle 9 Code-Node-Skripte mit `node --check` fehlerfrei. Struktur (24 Nodes inkl. Sticky Note, keine verwaisten Connection-Referenzen, keine doppelten IDs) geprüft. `mcp__n8n-mcp__validate_workflow` meldet nur die bekannten False Positives (Brace-Matcher auf `[{ json: ... }]`, IF-`main[1]` als „error output" fehlinterpretiert, SplitInBatches-„done"→Summary — alle identisch zum produktiven `alice-dms-thumbnailer-backfill`).

**QA-Iteration (2026-08-31):** 3 Low-Bugs in-Iteration behoben — BUG-1 (Image-PATCH kein `additionalPaths` mehr), BUG-3 (`confirm`/`time_limit_seconds` jetzt auch aus Query-String), BUG-4 (Cascade-gelöschte BankTransaction-Kinder per `staticData._cascaded_banktx_uuids` gegen Doppel-DELETE geschützt). Details siehe QA Test Results.

**Offen für Live-Verifikation (nach Deploy):** Dry-Run-Lauf gegen den echten Bestand (`POST /webhook/alice-dms-reconcile` ohne `confirm`), Zähler gegen die ~700+~35-Erwartung aus PROJ-95 prüfen. **BUG-2 (Webhook ohne Auth für destruktiven Endpoint) — Nutzerentscheidung offen.**

## QA Test Results

**Tested:** 2026-08-31
**Tester:** QA Engineer (AI) — statische Prüfung
**Prüfumfang:** Workflow-JSON `workflows/alice-dms-reconcile.json` (24 Nodes) + Service-Change `alice-dms-thumbnailer/app/main.py` (`DELETE /thumbnail/{uuid}`). Kein Live-Lauf möglich (Workflow noch nicht deployed) — Verifikation gegen AC per Code-Lesung, Datenfluss-Trace und Vergleich mit den produktiven Referenz-Workflows.

### Acceptance Criteria Status

#### Trigger & Betriebsmodus
- [x] Webhook `POST /webhook/alice-dms-reconcile` **und** `Schedule Trigger` vorhanden; beide speisen `Code: Init Run`.
- [x] Cron: `0 0 1-7 * 1` (**Abweichung von der Spec `0 1 …`** — begründet: n8n-Cron läuft UTC, `0 1` UTC = 02:00/03:00 Berlin und kollidiert mit `alice-dms-processor`; `0 0` UTC = 01:00/02:00 Berlin, mit 3600 s-Limit vor dem Processor fertig). „Erster Montag im Monat" bleibt (DOM 1–7 UND Montag).
- [x] Webhook ohne `confirm=true` → `mode='dry-run'`: `Code: Process Object` führt keine PATCH/DELETE/MQTT-Operation aus (alle in `if (confirm) { … }` gekapselt), zählt aber per „planned-or-done"-Logik + loggt jede Entscheidung per winston (UUID, Collection, letzter Pfad, geplante Aktion).
- [x] Webhook mit `confirm=true` → `mode='confirm'`: Reparatur-PATCH, Löschungen, `alice/dms/done`-Publishes aktiv.
- [x] Schedule → immer `mode='confirm'`, `max_runtime_seconds=3600` fest. Kein Schedule-Dry-Run.
- [x] Modus per Node-Namen-Zugriff (`$('Schedule Trigger: Monthly').first()` / `$('Webhook: …').first()`), nicht `$input.first().json.body` — PROJ-92-Muster.
- [x] Redis-Lock `alice:dms:processor:lock:run` per `SET NX PX` vor Verarbeitung; belegt → `Code: Respond Locked` → `{ status:'skipped', stopped_reason:'locked', … }`, HTTP 200 (Webhook) bzw. Stats-MQTT + NoOp (Schedule), ohne Warten. Release im Normal-, Zeitlimit- und Fehlerpfad (`Code: Build Summary` owner-checked Lua-`eval`; `Code: Release Lock (error)` workflow-tag-checked; TTL 65 min als Backstop).
- [x] Webhook jederzeit unabhängig vom Schedule aufrufbar; zweiter Läufer skippt per Lock.
- [x] Optionaler `time_limit_seconds` im Webhook-Body → `Code: Time Check` nach jedem Objekt; Ablauf → sauberer Stopp via `IF: Time Limit Reached` → `Code: Build Summary` mit vollständigem Response. Kein Auto-Continue. — ⚠️ siehe BUG-3 (nur Body, nicht Query).

#### Verwaiste datei-basierte Objekte
- [x] Verwaisungs-Definition umgesetzt: (`filePath` fehlt ODER `!fs.existsSync`) UND kein per `fs.existsSync` verifizierter Pfad in `hash_to_paths:<hash>` UND gespeicherter `filePath` kein lebender Key in `path_to_hash`.
- [x] Objekt ohne SHA-256-`fileHash` und ohne gültigen `filePath` → `orphan` (`hashValid` = false → path_drift übersprungen, path_to_hash-Check schlägt fehl → orphan).
- [x] `confirm` → `DELETE /v1/objects/<Class>/<uuid>`.
- [x] BankStatement → gepagte Cascade (`parentStatementId`-GraphQL-Get limit 100 + `after`, DELETE-by-ID) **vor** Parent-Delete — Muster aus `alice-dms-lifecycle`.
- [x] Thumbnail-Datei-Löschung: **Abweichung** — n8n mountet `THUMB_DIR` nicht, daher `DELETE http://alice-dms-thumbnailer:8004/thumbnail/<uuid>` statt `fs.unlink`. Neuer Endpoint idempotent (`unlink(missing_ok=True)`), UUID-Regex-validiert, kein JWT (intern). Fehlschlag blockiert Objekt-Delete nicht.
- [x] Redis-Reste-Bereinigung: nach Objekt-Delete, nur wenn kein Member von `hash_to_paths:<hash>` mehr per `fs.existsSync` existiert → `hDel path_to_hash`, `del hash_to_paths:<hash>`, `sRem processed`.

#### Pfad-Drift-Reparatur
- [x] `fileHash` → genau/mehrere lebende Datei(en) → `filePath`-PATCH auf lexikografisch ersten (`livePaths.sort()[0]`).
- [x] `fileName`/`fileType` mit-gepatcht bei Abweichung (Basename / Extension lowercase).
- [x] Mehrere lebende Pfade → Rest in `additionalPaths` gemerged, `filePath` daraus entfernt, dedupe (`Set`).
- [~] „Lebender Pfad steht bereits in `additionalPaths`" → wird durch das `Set`-Merge + `merged.delete(newFilePath)` mit abgedeckt (kein Doppeleintrag). Kein separater „aus additionalPaths herausheben"-Zweig, aber Ergebnis identisch.
- [x] Nach PATCH → `alice/dms/done` mit `{ document_type, weaviate_uuid, file_path, file_type, inserted:true }` — Format kompatibel zu `alice-dms-thumbnailer` `Code: Parse & Filter`.

#### BankTransaction-Konsistenz
- [x] Pro BankTransaction: `parentStatementId` → REST-GET `/v1/objects/BankStatement/<id>` (200/404). Kein `filePath`-Check (kind `banktx`).
- [x] Parent 404 → `banktx_orphan` → `confirm` → DELETE.
- [x] Jeder andere HTTP-Status / Netzwerkfehler → fail-safe „behalten".

#### Email
- [x] `Code: Query Weaviate` fragt `Email` nicht ab; keine Email-Verarbeitung irgendwo im Graphen.

#### Response & Logging
- [x] Webhook-Response = exakt die geforderten aggregierten Zähler (`status, mode, trigger, stopped_reason, checked, path_repaired, deleted_orphan, deleted_cascade_banktx, deleted_orphan_banktx, thumbnail_files_removed, done_events_published, skipped_ok, remaining`).
- [x] Schedule: kein HTTP-Response; dieselbe Summary per winston + `alice/dms/reconcile-stats` (MQTT qos 1).
- [x] Jede Aktion (Reparatur/Löschung/Cascade) per winston geloggt mit UUID, Collection, letztem Pfad, Aktion — auch im Dry-Run.
- [x] `remaining` = `totalObjects − checked` bei `stopped_reason='time_limit'`, sonst 0.

#### Nicht-Ziele
- [x] Keine Klassifikations-/Collection-Änderung.
- [x] Kein NAS-Verzeichnis-Scan — nur Redis-Map + `fs.existsSync`.

### Edge Cases Status

- [x] Objekt gesund ohne `thumbnail_path` → `skipped_ok` (Schritt 1 „file exists" greift, Thumbnail ist PROJ-95).
- [x] Kein `filePath`, `fileHash` → lebende Datei → `path_drift` statt Löschung.
- [x] Veralteter `filePath`, Datei per Hash am neuen Ort → PATCH auf neuen Pfad (deckt die 35 422-Fälle).
- [x] Kein `filePath` UND kein verwertbarer `fileHash` → `orphan` → Löschung.
- [x] `hash_to_paths:<hash>` mehrere Pfade, alle tot → `orphan`, alle toten Redis-Einträge mit bereinigt.
- [x] Redis nicht erreichbar zu Lauf-Beginn → `Code: Acquire Lock` fail-closed → `Respond Locked`.
- [x] Redis fällt mitten im Lauf aus → `_redis_ok` false ODER per-Objekt-Redis-`catch` → Objekt-Klassifikation endet in `skipped_ok` (fail-safe), geloggt.
- [x] BankStatement-Delete vs. paralleler Processor → geteilter Lock schließt Gleichzeitigkeit aus.
- [x] Zeitlimit während Cascade → Cascade läuft im selben `Code: Process Object`-Aufruf zu Ende, `Code: Time Check` erst danach.
- [x] Dry-Run meldet 700, Confirm findet 690 → kein Fehler, Confirm arbeitet mit aktuellem Stand (getrennte Läufe, jeweils frische Query).
- [x] `thumbnail_path` zeigt auf nicht mehr existierende Datei → Service-`DELETE` gibt `{deleted:false}`, kein Zählerinkrement, kein Abbruch.
- [x] `alice/dms/done` published, Thumbnailer down → MQTT-Node `onError: continueRegularOutput`, kein Reconcile-Fehler.
- [x] `filePath` außerhalb aller Watched-Folder, Datei existiert real → Schritt 1 `fs.existsSync` true → `skipped_ok`, nichts gelöscht.
- [x] Monatslauf trifft Processor → Lock-Skip beidseitig sauber; 3600 s-Limit hält den Reconcile vor 02:00 UTC.
- [x] Erster Montag = der 1. → Cron `1-7 * 1` matcht genau einmal.
- [x] Schedule-Lauf-Fehler → `Error Trigger` → Lock-Release (workflow-tag) bzw. TTL; bereits erledigte Aktionen bleiben (idempotent), kein Auto-Retry.

### Security Audit Results

**n8n workflow:**
- [x] Kein User-Input in Weaviate/Redis-Keys außer `time_limit_seconds`/`confirm` (beide typgeprüft: `parseInt` bzw. `=== true`).
- [x] `fileHash` vor GraphQL-Nutzung per `SHA256_RE` validiert (`/^[a-f0-9]{64}$/i`) → keine GraphQL-Injektion über Hash. `weaviate_uuid` / `parentStatementId` stammen aus Weaviate selbst (kein User-Input), werden in GraphQL-`valueText` interpoliert — akzeptables Risiko wie im produktiven `alice-dms-lifecycle`.
- [x] Neuer Service-Endpoint `DELETE /thumbnail/{uuid}`: UUID per `re.fullmatch(r"[0-9a-f-]{36}")` → kein Path-Traversal. Kein JWT — konsistent mit `POST /generate` (interner Endpoint, nicht über nginx exponiert; `docker-compose` bindet nur ins interne `automation`/`backend`-Netz).
- [x] Redis-Passwort aus `$env.REDIS_PASSWORD`, nicht hardcoded. Keine Secrets in winston-Logs (nur UUIDs/Pfade/Zähler).
- [~] Webhook hat **keine** JWT-Prüfung (wie die anderen DMS-Backfills `alice-dms-thumbnailer-backfill` etc.). Der Endpoint löst destruktive Löschungen aus — Schutz derzeit nur durch VPN-only-Zugang + `confirm`-Gate + nginx. **Konsistent mit dem bestehenden Backfill-Muster, aber siehe BUG-2.**

**Regression:** `alice-dms-thumbnailer` — neuer Endpoint additiv, `POST /generate` / `GET /thumbnail/{uuid}` / `/health` unverändert. `alice-dms-scanner` / `alice-dms-lifecycle` / `alice-dms-classification-backfill` nicht angefasst. Geteilter Lock-Key erweitert die bestehende Skip-Logik um einen weiteren Teilnehmer, ändert sie nicht.

### Bugs Found

#### BUG-1: `Image`-PATCH schreibt `additionalPaths` auch ohne Schema-Property — ✅ BEHOBEN
- **Severity:** Low
- **Detail:** `Code: Process Object` fügte bei `path_drift` für `collection === 'Image'` `props.additionalPaths` hinzu → Weaviate-Auto-Schema hätte die Property angelegt.
- **Fix (2026-08-31):** Image-PATCH setzt nur noch `file_path` (+ `file_name`/`file_type` nur wenn die Property auf dem abgefragten Objekt existiert). Kein `additionalPaths` mehr für Image.

#### BUG-2: Reconcile-Webhook ohne Authentifizierung löst destruktive Löschungen aus — ⚖️ AKZEPTIERT (Nutzerentscheidung 2026-08-31)
- **Severity:** Medium
- **Detail:** `POST /webhook/alice-dms-reconcile` hat keine JWT-/Token-Prüfung. Mit `confirm=true` löscht der Aufruf endgültig Weaviate-Objekte (inkl. Vektoren + LLM-Klassifizierung). Schutz: VPN-only, `confirm`-Gate (Default = Dry-Run), nginx-Pfad. Gleiches Muster wie die bestehenden DMS-Backfills.
- **Entscheidung:** Bewusst **so belassen** — konsistent mit `alice-dms-thumbnailer-backfill` / `alice-dms-classification-backfill` / `alice-dms-language-backfill`. Der VPN-only-Zugang plus das `confirm`-Gate gelten als ausreichend. Kein Auth-Node.

#### BUG-3: `time_limit_seconds` nur aus Body, nicht aus Query-String — ✅ BEHOBEN
- **Severity:** Low
- **Detail:** `Code: Init Run` las nur `body.time_limit_seconds` / `body.confirm`.
- **Fix (2026-08-31):** liest jetzt `body` **und** `query` für beide Parameter (`?time_limit_seconds=3500`, `?confirm=true` wirken jetzt) — Angleichung an `alice-dms-thumbnailer-backfill` `Code: Init Run`.

#### BUG-4: Doppelverarbeitung von BankTransaction-Kindern eines verwaisten BankStatements — ✅ BEHOBEN
- **Severity:** Low
- **Detail:** Per-Cascade gelöschte Kinder tauchten danach als eigene `banktx`-Items auf → zweiter (404-)DELETE.
- **Fix (2026-08-31):** Cascade-gelöschte Child-UUIDs werden in `staticData._cascaded_banktx_uuids` vorgemerkt (in `Code: Init Run` + `Code: Build Summary` genullt); der `banktx`-Zweig überspringt sie ohne zweiten Call und ohne Doppel-Zählung. `Code: Query Weaviate` queued datei-basierte Collections (inkl. BankStatement) **vor** BankTransaction — Parent immer vor Kind verarbeitet, Fix greift zuverlässig.

#### BUG-5: Kein Webhook-Response bei Absturz nach Lock-Acquire
- **Severity:** Low
- **Detail:** Stürzt der Lauf nach erfolgreichem Lock ab, greift `Error Trigger` → Lock-Release + `alice/dms/error`, aber `Respond to Webhook` wird nie erreicht → HTTP-Client hängt bis nginx-Timeout (300 s). Identische Einschränkung wie `alice-dms-thumbnailer-backfill`.
- **Priorität:** Nice to have / dokumentiert.

### Summary
- **Acceptance Criteria:** alle Kategorien erfüllt (1 bewusste, begründete Abweichung bei der Cron-Zeit; 1 gleichwertige Umsetzung bei „Pfad in additionalPaths").
- **Edge Cases:** 17/17 abgedeckt.
- **Bugs Found:** 5 total (0 Critical, 0 High, 1 Medium, 4 Low). **BUG-1, BUG-3, BUG-4 in-Iteration behoben und re-verifiziert.** BUG-2 (Medium) vom Nutzer als bewusste Konsistenzentscheidung akzeptiert (kein Auth-Node). BUG-5 (Low) dokumentiert.
- **Security:** Pass. BUG-2 (fehlende Webhook-Auth) bewusst akzeptiert — VPN-only + `confirm`-Gate, konsistent mit allen anderen DMS-Backfills.
- **Production Ready:** **JA.** Kein Critical/High offen.
- **Deploy erfolgt (2026-08-31):** `alice-dms-thumbnailer` (neuer `DELETE`-Endpoint) + `alice-dms-reconcile` (Workflow-ID `pKeTwgkgshNwVZ7L`, aktiv).

### Live-Verifikation (2026-08-31)

**Dry-Run 1 (Execution 165064, `time_limit_seconds=180`):**
```
checked=1439  remaining=823  stopped_reason=time_limit
deleted_orphan=710  deleted_orphan_banktx=34  skipped_ok=695
path_repaired=0  deleted_cascade_banktx=0  thumbnail_files_removed=0  done_events_published=0
```
- `deleted_orphan=710` deckt sich mit der PROJ-95-Erwartung (~700 pfadlose Objekte). Stichprobe der `Code: Query Weaviate`-Ausgabe: Großteil der betroffenen `Invoice`-Objekte hat `file_path=null` **und** `file_hash=null` (Alt-Importe ohne verwertbare Quelle → korrekt `orphan`).
- `deleted_orphan_banktx=34`: Cascade-Waisen (BankTransaction ohne lebendes Parent-BankStatement) — Bonus-Fund, in PROJ-95 nicht separat beziffert.
- `path_repaired=0`: noch nicht aussagekräftig — der Lauf stoppte bei 1439/2262. **Voller Dry-Run ausstehend.**

**Dry-Run 2 (Execution 165078, voll, ~11 min, `stopped_reason=completed`):**
```
checked=2262  remaining=0
deleted_orphan=710  deleted_orphan_banktx=229  skipped_ok=1323
path_repaired=0  deleted_cascade_banktx=0  thumbnail_files_removed=0  done_events_published=0
```

**Log-Analyse (winston, `/srv/warm/n8n/data/logs/n8n.log`):**
- **`path_repaired=0` ist korrekt, kein Bug.** ALLE geloggten `orphan`-Entscheidungen haben `lastPath=(none)` UND `hash=(none)` (`grep -vc 'lastPath=(none)'` → 0; `grep -v 'hash=(none)'` → 0). Die 710 Waisen sind ausschließlich pfad- **und** hash-lose Alt-Importe — reine Geister-Objekte ohne Rekonstruktionsmöglichkeit. **Kein einziger Fall, in dem `confirm` ein Objekt mit lebender Quelldatei löschen würde** — die Fail-safe-Logik greift.
- Die ~35 Pfad-Drift-Fälle aus PROJ-95 haben sich zwischen dem 30.08. und dem 31.08. **selbst geheilt**: `alice-dms-scanner` hat die verschobenen Dateien am neuen Ort neu indexiert, ihr `filePath` zeigt wieder auf eine existierende Datei → jetzt in `skipped_ok`. Es gibt keine Drift mehr zu reparieren.
- **`deleted_orphan_banktx=229` ist korrekt — Cascade-Artefakt des Dry-Runs.** Die geloggten `parentStatementId` wiederholen sich stark (wenige verwaiste BankStatements × je viele Transaktions-Kinder). Diese Parent-BankStatements sind selbst Teil der 710 `orphan`. Im Dry-Run zählt der Cascade-Zweig nicht (`if (confirm)`), daher landen alle Kinder im `banktx_orphan`-Zähler; im `confirm`-Lauf werden dieselben Kinder über den BankStatement-Cascade-Pfad gelöscht und zählen dann als `deleted_cascade_banktx`. Netto identisch. Keine Doppel-Löschung dank BUG-4-Fix.
- **Ergebnis: grünes Licht für den `confirm`-Lauf.** Erwartung: `deleted_orphan≈710`, `deleted_cascade_banktx + deleted_orphan_banktx ≈ 229` (Split je nachdem, in welcher Reihenfolge Parent/Kind verarbeitet werden — Parent zuerst, daher überwiegend `deleted_cascade_banktx`), `path_repaired=0`, `skipped_ok≈1323`.

_(Hinweis: die Logdatei enthält beide vollen Läufe — 710 + 710 ≈ 1420 `orphan`-Zeilen.)_

## Deployment

**2026-08-31 — deployed:**
- `alice-dms-thumbnailer` (Container-Rebuild): neuer Endpoint `DELETE /thumbnail/{uuid}`.
- `alice-dms-reconcile` (n8n-Workflow-ID `pKeTwgkgshNwVZ7L`, aktiv): Webhook + Schedule Trigger (`0 0 1-7 * 1`).

**Verifikation:** 2 Dry-Run-Läufe (Execution 165064 partiell, 165078 voll) — Klassifikation bestätigt, keine Fehllöschungen möglich (alle `orphan` sind pfad-/hash-lose Alt-Importe). Siehe „Live-Verifikation" oben.

**Ausstehend:** erster `confirm=true`-Lauf (räumt die 710 verwaisten Objekte + ~229 Cascade-Waisen-Transaktionen auf). Danach optional Verifikations-Dry-Run (`deleted_orphan` sollte dann ~0 sein). Der monatliche Schedule läuft ab dem ersten Montag im September automatisch.
