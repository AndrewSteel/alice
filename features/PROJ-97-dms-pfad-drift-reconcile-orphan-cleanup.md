# PROJ-97: DMS Pfad-Drift-Reconcile + Cleanup verwaister Weaviate-Objekte

## Status: Planned
**Created:** 2026-08-31
**Last Updated:** 2026-08-31 (Schedule-Trigger ergänzt: erster Montag im Monat 01:00, `confirm` implizit, `max_runtime_seconds=3600`)

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
