# PROJ-44: DMS BankTransaction Lifecycle Cleanup

## Status: Deployed
**Created:** 2026-06-24
**Last Updated:** 2026-08-17

## Dependencies
- Requires: PROJ-29 (BankTransaction Indexing) — `BankTransaction` collection und `parentStatementId`-Verknüpfung müssen existieren
- Requires: PROJ-22 (DMS Lifecycle) — `alice-dms-lifecycle` Workflow (MQTT-basierte Lifecycle-Events)
- Requires: PROJ-16 (DMS Scanner) — `alice-dms-scanner` publiziert Lifecycle-Events via MQTT

## Problem Statement

**BUG-13 aus PROJ-29:** Wenn ein Kontoauszug aus dem DMS-Ordner gelöscht wird oder sich sein Inhalt ändert (neue Hash), verbleiben die zugehörigen `BankTransaction`-Kinder als verwaiste Objekte in Weaviate. Der Lifecycle-Mechanismus ist nicht über die Child-Collection `BankTransaction` informiert — er kennt nur `BankStatement`-Objekte und löscht diese, ohne die zugehörigen Buchungszeilen zu bereinigen.

**Konkretes Schadenbild:**
- Verwaiste `BankTransaction`-Objekte tauchen weiterhin in Suchergebnissen auf, obwohl die zugrundeliegende Datei nicht mehr im DMS ist
- Bei Re-Processing einer geänderten Datei akkumulieren sich doppelte Buchungen
- Die `parentStatementId` verweist auf ein nicht mehr existierendes `BankStatement`-Objekt
- Speicherverbrauch wächst unbegrenzt (kein Ablaufdatum, keine automatische Bereinigung)

**Zwei Trigger-Szenarien:**

1. **Replace-Szenario**: Datei bleibt am selben Pfad, Inhalt ändert sich (neuer SHA-256-Hash). Der Scanner entfernt den alten Hash aus `alice:dms:processed`, der Processor erstellt ein neues `BankStatement`-Objekt mit neuer UUID. Die alten `BankTransaction`-Objekte (verknüpft mit der alten `parentStatementId`) bleiben in Weaviate.

2. **Delete-Szenario**: Datei wird physisch aus dem DMS-Ordner entfernt. Der Scanner durchläuft nur noch existierende Dateien — er hat keine Kenntnis, dass ein bekannter Pfad verschwunden ist. Weder `BankStatement` noch `BankTransaction`-Objekte werden jemals bereinigt.

## User Stories

- Als System möchte ich, dass beim Ersetzen einer geänderten Kontoauszugs-Datei (Replace-Fall) die alten `BankTransaction`-Kinder des alten `BankStatement`-Objekts automatisch gelöscht werden, bevor das neue Objekt erstellt wird, damit keine verwaisten Buchungen in Weaviate verbleiben.
- Als System möchte ich, dass beim physischen Löschen einer Kontoauszugs-Datei aus dem DMS-Ordner alle zugehörigen `BankTransaction`-Objekte in Weaviate gelöscht werden, zusammen mit dem übergeordneten `BankStatement`-Objekt.
- Als Nutzer möchte ich sicherstellen, dass Suchanfragen wie „letzter Zahlungsausgang Telekom" ausschließlich Buchungen aus aktiven, im DMS vorhandenen Kontoauszügen liefern — und keine Geister-Buchungen aus gelöschten Dateien.
- Als Administrator möchte ich nach einer Bereinigungsoperation via `curl` prüfen können, dass der `BankTransaction`-Count in Weaviate tatsächlich zurückgegangen ist, und zwar auf exakt die Anzahl der verbleibenden aktiven Buchungen.
- Als System möchte ich, dass die Bereinigung idempotent ist: ein zweimaliges Auslösen des Delete-Events für dasselbe `BankStatement` führt zum selben Ergebnis (kein Fehler, keine negativen Counts).

## Acceptance Criteria

### AC-1: Replace-Szenario — Cascade-Delete beim Re-Processing

- [ ] Wenn der DMS-Processor ein `BankStatement` neu erstellt (Replace-Fall: neuer Hash, gleicher Pfad), werden zuerst alle `BankTransaction`-Objekte mit der `parentStatementId` des **alten** `BankStatement`-Objekts aus Weaviate gelöscht, bevor neue `BankTransaction`-Objekte eingefügt werden
- [ ] Das alte `BankStatement`-Objekt selbst wird aus Weaviate gelöscht (es wird durch das neue ersetzt)
- [ ] Der neue Processor-Durchlauf legt ein neues `BankStatement` + neue `BankTransaction`-Objekte mit der neuen UUID als `parentStatementId` an
- [ ] Nach dem Re-Processing: `Aggregate { BankTransaction { meta { count } } }` entspricht exakt der Anzahl der Buchungen aus dem neuen Dokument (keine Duplikate des Altbestands)
- [ ] Wenn das alte `BankStatement`-Objekt nicht in Weaviate gefunden wird (bereits manuell gelöscht), läuft der Processor ohne Fehler weiter

### AC-2: Delete-Szenario — Scanner erkennt gelöschte Dateien

- [ ] Der `alice-dms-scanner` prüft am Ende jedes Scan-Durchlaufs alle Pfade in `alice:dms:path_to_hash` (Redis Hash) darauf, ob die jeweilige Datei noch physisch existiert
- [ ] Für jeden Pfad, der nicht mehr existiert, publiziert der Scanner ein MQTT-Event auf `alice/dms/lifecycle` mit `action: "delete_file"`, `file_hash`, `file_path`
- [ ] Redis-Einträge für den gelöschten Pfad werden bereinigt: `HDEL alice:dms:path_to_hash <file_path>`, `SREM alice:dms:hash_to_paths:<hash> <file_path>`, `SREM alice:dms:processed <hash>` (nur wenn keine weiteren Pfade auf denselben Hash verweisen)
- [ ] Der Stats-Counter `alice:dms:scanner:stats:deleted_files` wird pro erkanntem gelöschtem Pfad inkrementiert
- [ ] Der Scan-Durchlauf bricht nicht ab, wenn ein oder mehrere Dateien als gelöscht erkannt werden

### AC-3: Lifecycle-Workflow verarbeitet `delete_file`-Events

- [ ] Der `alice-dms-lifecycle`-Workflow akzeptiert `action: "delete_file"` als gültige Aktion (aktuell schlägt er mit `Unknown action` fehl)
- [ ] Bei `delete_file`: Weaviate wird nach dem `BankStatement`-Objekt mit passendem `fileHash` durchsucht (analog zur bestehenden `Code: Weaviate Find by Hash`-Logik)
- [ ] Wenn ein `BankStatement` gefunden wird: alle `BankTransaction`-Objekte mit `parentStatementId = <weaviate_id>` werden via `DELETE /v1/batch/objects` (where-Filter) aus Weaviate gelöscht
- [ ] Danach wird das `BankStatement`-Objekt selbst via `DELETE /v1/objects/<class>/<uuid>` aus Weaviate gelöscht
- [ ] Wenn kein `BankStatement` gefunden wird (Hash unbekannt, bereits bereinigt): no-op, kein Fehler, MQTT `Done` wird trotzdem gesendet
- [ ] Wenn das `BankStatement` einer anderen Collection angehört (z.B. `Invoice`, `Document`): `BankTransaction`-Cascade-Schritt wird übersprungen; nur das Parent-Objekt wird gelöscht
- [ ] MQTT `alice/dms/done` wird nach erfolgreicher Bereinigung publiziert mit `{ action: "delete_file", deleted_statement: true/false, deleted_transactions: N }`
- [ ] Bei Fehlern (Weaviate nicht erreichbar, Batch-Delete schlägt fehl): MQTT `alice/dms/error` publizieren (analog zum bestehenden Error-Handler)

### AC-4: Keine verwaisten BankTransaction-Objekte nach Lifecycle-Operationen

- [ ] Testfall Replace: Kontoauszug wird durch geänderte Version ersetzt → nach Re-Processing sind exakt 0 BankTransaction-Objekte mit der alten `parentStatementId` in Weaviate vorhanden
- [ ] Testfall Delete: Kontoauszug wird aus DMS-Ordner entfernt → nach nächstem Scanner-Durchlauf und Lifecycle-Verarbeitung sind exakt 0 BankTransaction-Objekte mit der zugehörigen `parentStatementId` in Weaviate vorhanden
- [ ] PRD-Metrik: `DMS BankTransaction: verwaiste Objekte → 0 nach Parent-Löschung` (aus `docs/PRD.md`) ist erfüllt

## Edge Cases

- **Mehrere Pfade für denselben Hash** (Datei wurde kopiert): Der Scanner löscht einen Pfad aus `alice:dms:hash_to_paths`, aber da noch andere Pfade existieren, wird `alice:dms:processed` NICHT geleert — das Dokument bleibt indiziert, kein Delete-Event wird für das Weaviate-Objekt ausgelöst
- **Delete-Event für nicht-BankStatement-Objekt**: Der Lifecycle-Handler findet z.B. ein `Invoice`-Objekt — `BankTransaction`-Cascade wird übersprungen, nur das Invoice-Objekt wird gelöscht
- **Batch-Delete gibt Teilfehler zurück** (einige BankTransaction-Objekte konnten nicht gelöscht werden): Erfolgreiche Löschungen behalten, fehlgeschlagene loggen, Prozess nicht abbrechen — analog zu bestehender Fehlerbehandlung in PROJ-19
- **Race Condition Scanner ↔ Processor**: Scanner erkennt Datei als gelöscht und sendet Delete-Event, während Processor dieselbe Datei gerade noch verarbeitet → Delete-Event trifft auf noch nicht existierende BankTransaction-Objekte → no-op, kein Fehler
- **`delete_file`-Event doppelt ausgelöst** (idempotenz): Zweites Event findet nichts in Weaviate → no-op, kein Fehler, kein negativer Count
- **Sehr viele verwaiste Dateien** (z.B. DMS-Ordner wurde komplett geleert, 100+ Kontoauszüge): Scanner gibt 100+ Delete-Events aus — jedes wird als einzelnes MQTT-Event verarbeitet; kein Batch-Limit erforderlich
- **Weaviate Batch-Delete API-Version**: Die `DELETE /v1/batch/objects` mit where-Filter muss mit der eingesetzten Weaviate-Version kompatibel sein (siehe BUG-3 aus PROJ-29 — API-Format-Kompatibilität vor Deployment verifizieren)

## Technical Requirements

### Geänderte Workflows/Dateien
- `workflows/alice-dms-scanner.json` — Stale-Path-Detection nach dem Scan-Loop hinzufügen
- `workflows/alice-dms-lifecycle.json` — `delete_file`-Action-Handler hinzufügen
- `workflows/alice-dms-processor.json` — Replace-Scenario: altes BankStatement + BankTransaction-Kinder vor Re-Insert löschen

### Infrastruktur
- **Keine neuen Container** erforderlich
- **Keine Schema-Änderungen** erforderlich (bestehende `BankTransaction`-Collection mit `parentStatementId` ist ausreichend)
- Weaviate Batch-Delete API (`DELETE /v1/batch/objects` mit where-Filter auf `parentStatementId`) — Kompatibilität mit der eingesetzten Weaviate-Version vorab prüfen

### Performance
- Scanner-Zusatzschritt (Stale-Path-Check): liest alle Keys aus `alice:dms:path_to_hash` (Redis HGETALL), prüft fs.existsSync für jeden Pfad → O(n) mit n = Anzahl bekannter DMS-Pfade; akzeptabel für < 10.000 Dateien
- Lifecycle-Delete-Handler: 1 Weaviate-Query (Find by Hash) + 1 Weaviate-Batch-Delete (BankTransaction) + 1 Weaviate-Delete (BankStatement) → < 5s pro Event erwartet

---

## Tech Design (Solution Architect)

### Umfang

Dieses Feature berührt **zwei n8n-Workflows** (Scanner, Lifecycle) und **einen zur Verifikation** (Processor). Keine neuen Container, keine Schema-Änderungen, kein Frontend-Eingriff.

---

### Wichtige Vorab-Erkenntnis: AC-1 (Replace) ist bereits implementiert

Der `Code: BankTransaction Phase B`-Node in `alice-dms-processor.json` enthält bereits eine BUG-13-Korrektur, die beim Replace-Szenario greift:

- Wenn ein BankStatement neu prozessiert wird (Dateiinhalt geändert, neuer Hash), wird das alte `BankStatement`-Objekt bereits via `HTTP: Weaviate Delete` gelöscht
- Phase B erkennt, ob der neue `parentId` von der alten `_existing_weaviate_id` abweicht (`oldParentId` im Code)
- Falls ja: Phase B löscht alle `BankTransaction`-Kinder des alten Parents über GraphQL-Get → DELETE-by-UUID (zuverlässiger als delete-by-where, BUG-3-Fix)

**Konsequenz für PROJ-44:** Das Replace-Szenario muss nur verifiziert werden (kein neuer Code). Die eigentliche Implementierungsarbeit liegt im Delete-Szenario.

---

### Komponentenübersicht

```
workflows/
├── alice-dms-scanner.json      (GEÄNDERT) — Stale-Path-Check nach dem Scan-Loop
└── alice-dms-lifecycle.json    (GEÄNDERT) — delete_file-Action-Handler (neue Branch)

workflows/alice-dms-processor.json   (VERIFIZIEREN, kein neuer Code)
```

---

### Workflow 1: `alice-dms-scanner` — Stale-Path-Detection

**Wo im Workflow:** Neuer Abschnitt nach `Code: Summary Stats`, bevor `MQTT: Publish Stats` ausgelöst wird.

**Ablauf:**

```
[Nach Scan-Loop abgeschlossen]
        ↓
Code: Find Stale Paths
  • HGETALL alice:dms:path_to_hash  → alle bekannten Pfade aus Redis
  • fs.existsSync(path) für jeden Pfad
  • Sammelt alle Pfade, die nicht mehr existieren

        ↓
IF: Has Stale Paths
  nein → weiter zu MQTT: Publish Stats (kein Aufwand)
  ja  ↓

Loop: Stale Paths (SplitInBatches oder inline)
  Für jeden verwaisten Pfad:
  
  1. SMEMBERS alice:dms:hash_to_paths:<hash>
     → prüfen, ob noch andere Pfade auf denselben Hash zeigen
     
  2. Redis-Bereinigung:
     • HDEL alice:dms:path_to_hash <pfad>
     • SREM alice:dms:hash_to_paths:<hash> <pfad>
     
  3. Falls keine weiteren Pfade für diesen Hash übrig:
     • SREM alice:dms:processed <hash>
     • MQTT: Publish delete_file → alice/dms/lifecycle
       { action: "delete_file", file_hash: <hash>, file_path: <pfad> }
       
  4. Falls noch andere Pfade für denselben Hash existieren:
     → kein MQTT-Event, kein Weaviate-Eingriff
     (Dokument ist noch woanders vorhanden — kein Orphan)

        ↓
Stats: deleted_files += N  (in Summary Stats eingerechnet)
        ↓
MQTT: Publish Stats (mit deleted_files)
```

**Designentscheidung — Warum HGETALL statt separatem State?**
`alice:dms:path_to_hash` ist die einzige Redis-Quelle der Wahrheit für "bekannte DMS-Pfade". Sie wird vom Scanner selbst gepflegt (HSET bei add/update). Ein Sweep über diese Map ist O(n) über alle bekannten Pfade — akzeptabel für < 10.000 Dateien im Haushalt-DMS. Eine eigene "deleted-files"-Queue würde Doppelstate erzeugen.

**Designentscheidung — Warum kein Delete-Event, wenn noch andere Pfade existieren?**
Wenn `alice:dms:hash_to_paths:<hash>` noch weitere, existierende Pfade enthält, ist der Inhalt der Datei weiterhin im DMS verfügbar (z.B. Kopie in anderem Ordner). Das Weaviate-Objekt ist korrekt und soll nicht gelöscht werden. Nur wenn alle Pfade eines Hashes verschwunden sind, ist das Dokument tatsächlich aus dem DMS entfernt.

---

### Workflow 2: `alice-dms-lifecycle` — delete_file Handler

**Topologische Änderungen:**

```
MQTT Trigger: alice/dms/lifecycle
        ↓
Code: Parse & Validate        ← GEÄNDERT: 'delete_file' zu valid_actions hinzufügen
        ↓
Code: Weaviate Find by Hash   (unverändert — liefert _weaviate_id und _weaviate_class)
        ↓
IF: Is add_path               (unverändert)
  true → PATCH additionalPaths → Redis Update → MQTT Done
  false ↓
IF: Is update_path            (unverändert)
  true → PATCH filePath → Redis Update → MQTT Done
  false ↓
IF: Is delete_file            ← NEU
  true ↓
  
  IF: Weaviate Object Found?
    nein → kein Fehler (bereits bereinigt) → MQTT Done (deleted_statement: false, deleted_transactions: 0)
    ja  ↓
    
    IF: Is BankStatement?
      ja  ↓
        Code: Find BankTransaction Children
          • GraphQL Get: BankTransaction(where parentStatementId = <uuid>), paginiert (limit 100, nach_cursor)
          • Sammelt alle BankTransaction-UUIDs des Parent-Objekts
              ↓
        Code: Delete BankTransaction Children
          • DELETE /v1/objects/BankTransaction/<uuid> für jede UUID
          • Fehler einzelner Deletes: loggen + weitermachen (nicht abbrechen)
          • Zählt: deleted_transactions_count
      nein → deleted_transactions_count = 0 (kein Cascade nötig)
    
    (beide Pfade führen zu:)
    HTTP: Delete Parent Object
      • DELETE /v1/objects/<_weaviate_class>/<_weaviate_id>
          ↓
    MQTT: Done
      { action: "delete_file", deleted_statement: true, deleted_transactions: N }
  
  false → unbekannte Action (Warn-Log, kein Fehler)
```

**Warum GraphQL-Get → DELETE-by-UUID statt DELETE-by-where?**
Identische Entscheidung wie in Phase B (BUG-3-Fix im Processor): Der `DELETE /v1/batch/objects`-Endpoint mit where-Filter verhält sich je nach Weaviate-Version unterschiedlich; der HTTP-Body wird von einigen Proxies/Clients bei DELETE-Requests verworfen. Der GET→DELETE-by-UUID-Pfad ist zuverlässiger und bereits im Processor bewährt.

**Paginierung der BankTransaction-Abfrage:**
Ein 15-seitiger Kontoauszug kann >100 Transaktionen haben. Die GraphQL-Abfrage verwendet `limit: 100` mit Cursor-Paginierung (`after`-Argument von Weaviate) bis die Ergebnisliste leer ist, um alle Kinder zu erfassen.

---

### Datenfluss-Übersicht

```
[Datei gelöscht aus DMS-Ordner]
        ↓
alice-dms-scanner (nächster stündlicher Lauf)
  Stale-Path-Check: Pfad nicht mehr auf Filesystem
  Redis bereinigen (path_to_hash, hash_to_paths, processed)
  MQTT → alice/dms/lifecycle: { action: "delete_file", file_hash, file_path }
        ↓
alice-dms-lifecycle
  Find BankStatement by fileHash in Weaviate
  Falls BankStatement:
    → alle BankTransaction-Kinder per GraphQL ermitteln
    → BankTransaction-Objekte via DELETE-by-UUID löschen
  → BankStatement via DELETE löschen
  MQTT → alice/dms/done: { deleted_statement: true, deleted_transactions: N }
```

---

### Keine neuen Abhängigkeiten

Alle benötigten Komponenten existieren bereits: MQTT, Redis (mit `redis`-Node-Modul), Weaviate HTTP (via axios), fs (Node.js built-in). Keine neuen npm-Pakete, keine neuen Container.

---

### Deploy-Reihenfolge

1. `alice-dms-scanner` deployen (Stale-Path-Check aktiv ab dem nächsten stündlichen Run)
2. `alice-dms-lifecycle` deployen (delete_file-Handler bereit)
3. AC-1 verifizieren: einen bestehenden Kontoauszug ersetzen → BankTransaction-Count prüfen
4. AC-2/AC-3 verifizieren: Testdatei aus DMS-Ordner entfernen → Scanner-Run abwarten → Weaviate-Count prüfen

## QA Test Results

**QA Date:** 2026-06-24
**Tested By:** QA Engineer (Red Team)
**Test Method:** Static code review of all PROJ-44 deliverables (`alice-dms-scanner.json`, `alice-dms-lifecycle.json`, and the existing BUG-13 fix in `alice-dms-processor.json`). Live execution against Weaviate / n8n was not performed (workflows run on ki.lan). One HIGH bug was found and fixed during QA before sign-off.

---

### Acceptance Criteria Results

#### AC-1: Replace-Szenario — Cascade-Delete beim Re-Processing

| Criterion | Status | Notes |
|---|---|---|
| Processor cascade-deletes old BankTransaction children before inserting new ones | PASS | `Code: BankTransaction Phase B` calls `cascadeDeleteChildren(oldParentId)` when `_existing_weaviate_class === 'BankStatement'` and old UUID ≠ new UUID |
| `cascadeDeleteChildren` uses GraphQL Get → DELETE-by-UUID (BUG-3 fix) | PASS | Uses paged GraphQL GET + per-UUID DELETE, with 404-as-success handling |
| Old BankStatement itself deleted before new one inserted | PASS | `HTTP: Weaviate Delete` node runs via `If: Has Existing Entry` → true branch |
| `_existing_weaviate_id` propagated to Phase B | PASS | `Code: Redis State Update` reads from `$('Code: Check Existing Entry')` which carries `_existing_weaviate_id`/`_existing_weaviate_class` |
| oldParentId null-safe when no previous object exists | PASS | `oldParentId = null` → `if (oldParentId)` guard in Phase B → `cascadeDeleteChildren` returns `{deleted:0, failed:0}` immediately |
| Count verification after re-processing (0 old, N new) | NOT TESTED LIVE | Logic correct; requires live Weaviate run to confirm |
| **AC-1 verdict** | PASS (with live verification pending) | |

#### AC-2: Delete-Szenario — Scanner erkennt gelöschte Dateien

| Criterion | Status | Notes |
|---|---|---|
| Scanner checks all paths in `alice:dms:path_to_hash` after scan | PASS | `Code: Find Stale Paths` uses `HGETALL alice:dms:path_to_hash` after Summary Stats |
| `delete_file` MQTT event published only when no other copies exist for that hash | PASS | After HDEL + SREM, `sMembers hash_to_paths` checked; event only if `stillAlive.length === 0` |
| Redis cleanup: HDEL path_to_hash, SREM hash_to_paths, SREM processed | PASS | All three operations in `Code: Find Stale Paths` |
| `deleted_files` in scanner stats | PASS (partial) | Field added to stats item directly; not persisted as separate Redis counter (see BUG-4 LOW) |
| Scan-Durchlauf does not abort on stale path errors | PASS | Outer try/catch in `Code: Find Stale Paths` catches all errors, always appends stats item |
| Stale check runs even when DMS has no files (BUG-3, fixed) | PASS (fixed) | Initially bypassed via `End: No Files` path; fixed by routing `Set: No Files Stats → Code: Find Stale Paths` |
| **AC-2 verdict** | PASS (with live verification pending) | BUG-3 fixed during QA; BUG-4 LOW documented |

#### AC-3: Lifecycle-Workflow verarbeitet `delete_file`-Events

| Criterion | Status | Notes |
|---|---|---|
| `delete_file` accepted as valid action in Parse & Validate | PASS | `!['add_path', 'update_path', 'delete_file'].includes(msg.action)` updated |
| Weaviate Find by Hash reused for delete_file | PASS | Flow: MQTT Trigger → Parse → Weaviate Find by Hash → IF: Is add_path (false) → IF: Is update_path (false) → IF: Is delete_file (true) |
| IF: Is delete_file branch exists and routes correctly | PASS | New node with `action === 'delete_file'` condition |
| BankTransaction children found via paged GraphQL Get | PASS | `for (page; page<50; page++)` loop in `Code: Handle delete_file`, breaks when `hits.length < 100` |
| Each BankTransaction child deleted by UUID | PASS | `axios.delete /v1/objects/BankTransaction/<uuid>` per child, warnings on failure |
| BankStatement deleted after children | PASS | `axios.delete /v1/objects/<parentClass>/<parentId>`, throws on error |
| Non-BankStatement: cascade skipped, only parent deleted | PASS | `if (parentClass === 'BankStatement')` guard around child collection loop |
| Object not found → no-op, no error | PASS | `if (!parentId || !parentClass)` early return with `deleted_statement: false` |
| MQTT `alice/dms/done` published with deletion stats | PASS | `MQTT: Done (delete_file)` node with `deleted_statement` and `deleted_transactions` fields |
| MQTT `alice/dms/error` on failures | PASS | Existing Error Trigger → Code: Format Error → MQTT: Publish Error chain handles uncaught throws |
| **AC-3 verdict** | PASS (with live verification pending) | |

#### AC-4: Keine verwaisten BankTransaction-Objekte

| Criterion | Status | Notes |
|---|---|---|
| Replace testfall: 0 BankTransaction with old parentStatementId after re-processing | NOT TESTED LIVE | Logic in Phase B is correct; live test requires Weaviate |
| Delete testfall: 0 BankTransaction after scanner run + lifecycle processing | NOT TESTED LIVE | Logic in scanner + lifecycle correct; live test required |
| PRD metric: verwaiste Objekte → 0 nach Parent-Löschung | NOT TESTED LIVE | |
| **AC-4 verdict** | NOT TESTED LIVE | Architecture correct; blocked by remote-only deployment |

---

### Bugs Found

#### BUG-1 (MEDIUM, FIXED during QA): Stale path check bypassed on empty DMS
- **Severity:** HIGH → fixed → no longer blocking
- **Location:** `alice-dms-scanner.json` — connection `Set: No Files Stats → End: No Files`
- **Issue:** When all DMS folders are empty or no supported files exist, `IF: Has Files` routes to `Set: No Files Stats → End: No Files`, bypassing `Code: Find Stale Paths` entirely. Spec edge case "DMS-Ordner komplett geleert" requires cleanup to run in this case.
- **Fix applied:** Changed `Set: No Files Stats → End: No Files` to `Set: No Files Stats → Code: Find Stale Paths`. `End: No Files` node is now an orphan (harmless in n8n).

#### BUG-2 (LOW): Internal `_stale_for_deletion` field in scanner stats MQTT
- **Severity:** Low
- **Location:** `alice-dms-scanner.json` → `MQTT: Publish Stats`, `Code: Find Stale Paths`
- **Issue:** Stats items output by `Code: Find Stale Paths` carry `_stale_for_deletion: false`. `MQTT: Publish Stats` uses `JSON.stringify($json)` which includes this internal field in the published stats message.
- **Impact:** Minor — stats consumers see an unexpected `_stale_for_deletion: false` field. Not harmful.
- **Recommendation:** Update `MQTT: Publish Stats` message to explicitly list only intended stats fields.

#### BUG-3 (LOW): `deleted_files` counter counts only Weaviate-triggering deletions
- **Severity:** Low
- **Location:** `Code: Find Stale Paths` — `deletedFiles` counter
- **Issue:** `deletedFiles` is only incremented when a stale path has no surviving copies (triggering Weaviate cleanup). Paths removed from Redis because a copy exists elsewhere are not counted. Spec says "pro erkanntem gelöschtem Pfad inkrementiert" — implies all stale paths, not just cleanup-triggering ones.
- **Impact:** Minor stats undercount.
- **Recommendation:** Increment a separate counter for total-stale-paths-removed vs. Weaviate-cleanups-triggered.

#### BUG-4 (LOW): No UUID sanitization in `Code: Handle delete_file` GraphQL query
- **Severity:** Low (security)
- **Location:** `alice-dms-lifecycle.json` → `Code: Handle delete_file`
- **Issue:** `parentId` (from `_weaviate_id`, a Weaviate-generated UUID) is used directly in the GraphQL query string without sanitization. Phase B's `cascadeDeleteChildren` sanitizes its input with `String(pid).replace(/[^a-zA-Z0-9-]/g, '')`. The lifecycle handler omits this step.
- **Impact:** Very low risk — `_weaviate_id` is Weaviate-generated and UUID-formatted, so injection is extremely unlikely. But it's inconsistent with the existing defensive security pattern.
- **Recommendation:** Add UUID sanitization for defensive consistency.

---

### Security Audit (Red Team)

#### S-1 (PASS): No new external input surface
PROJ-44 adds no new webhooks, API endpoints, or user-controllable inputs. The `delete_file` lifecycle event is published internally by `alice-dms-scanner` — it never accepts user-supplied data. Attacks require compromising the MQTT broker or the scanner itself.

#### S-2 (PASS): fileHash GraphQL injection prevention maintained
`Code: Weaviate Find by Hash` still sanitizes `fileHash` with `replace(/[^a-zA-Z0-9:]/g, '')` before using it in GraphQL queries. No change to this path.

#### S-3 (LOW): UUID in GraphQL query (BUG-4 above)
`parentId` in `Code: Handle delete_file` is not explicitly sanitized. Risk is very low given UUID format constraints but inconsistent with project patterns. See BUG-4.

#### S-4 (PASS): No permission escalation or data leakage
The delete_file handler deletes Weaviate objects but does not expose data to users. The scanner only processes DMS folder paths from `alice.dms_watched_folders` (Postgres, requires DB access to modify). No new permission surface.

#### S-5 (PASS): Redis cleanup is minimal and targeted
`Code: Find Stale Paths` only removes paths from `alice:dms:path_to_hash`, `alice:dms:hash_to_paths:*`, and `alice:dms:processed`. It does not touch any user data or credentials.

---

### Regression Risk Assessment

#### R-1: `alice-dms-scanner` existing scan loop — PASS
The main scan loop (Hash + Size → Lifecycle Check → Route → queue MQTT) is completely unchanged. Only the post-loop path (Summary Stats → Find Stale Paths) is modified. The first N items in the loop still flow identically.

#### R-2: `alice-dms-lifecycle` add_path / update_path — PASS
`IF: Is add_path` and `IF: Is update_path` handlers are unchanged. The new `delete_file` branch is added as a third branch after the existing two, with no impact on the existing routing.

#### R-3: `alice-dms-processor` BankStatement processing — PASS
No changes to `alice-dms-processor.json` in PROJ-44 (the BUG-13 fix was already in PROJ-29). The processor remains unchanged.

#### R-4: PROJ-29 BankTransaction indexing — PASS
`BankTransaction` collection schema unchanged. Phase B logic unchanged. The lifecycle handler correctly targets `BankTransaction` by class name.

#### R-5: Stats MQTT publishing — PARTIAL CONCERN
`alice/dms/scanner/stats` messages now include `_stale_for_deletion: false` and `deleted_files: N`. Any consumer of this topic (Grafana, other workflows) will receive extra fields. Both are additive and non-breaking (JSON consumers typically ignore unknown fields).

---

### Summary

| Metric | Value |
|---|---|
| Total ACs tested | 4 |
| ACs PASS | 3 (AC-1, AC-2, AC-3) |
| ACs NOT TESTED LIVE | 1 (AC-4 — requires live Weaviate) |
| Bugs HIGH (blocking) | 1 (BUG-1, FIXED during QA) |
| Bugs LOW | 3 (BUG-2, BUG-3, BUG-4) |
| Security findings (scoped) | 0 critical/high, 1 LOW (BUG-4) |
| Regression Risk | Low for all dependent workflows |

### Production-Ready Decision: READY

**All blocking issues resolved:**
- BUG-3 (HIGH) — empty DMS stale path bypass — **fixed during QA session**

**Remaining non-blocking items:**
- BUG-2 / BUG-3 / BUG-4 (LOW) — cosmetic, stats accuracy, defensive security — can be addressed in a follow-up
- AC-4 live verification — to be confirmed during first production deployment by checking Weaviate `Aggregate { BankTransaction { meta { count } } }` before and after deleting a test bank statement

## Deployment

**Deployed:** 2026-06-24
**Deployed By:** Andrew Steel

### Deployed Artifacts

- `workflows/alice-dms-scanner.json` — Stale-Path-Detection deployed to n8n
- `workflows/alice-dms-lifecycle.json` — delete_file-Handler deployed to n8n

### Post-Deployment Verification

- AC-4 live verification: check `Aggregate { BankTransaction { meta { count } } }` in Weaviate before and after deleting a test bank statement to confirm no orphans remain
- Low-priority follow-up items (BUG-2, BUG-3, BUG-4) can be addressed in a maintenance pass

## Nachträgliche Änderung (2026-08-17)

**Logging auf winston umgestellt**: Die Code-Nodes in `workflows/alice-dms-lifecycle.json` verwendeten `console.log`/`console.warn`, deren Ausgabe nur im Browser-Log landet und für Post-Incident-Analysen nicht verfügbar ist. Umgestellt auf einen `winston`-Logger pro Node (File-Transport nach `/home/node/.n8n/logs/n8n.log`, `defaultMeta` mit Workflow-/Node-Namen), analog zur PROJ-72-Migration von scanner/path-worker/processor. Reine Logging-Änderung, keine funktionale Änderung. Deployed: 2026-08-17.
