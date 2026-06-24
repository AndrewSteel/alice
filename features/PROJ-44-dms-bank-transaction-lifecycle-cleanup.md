# PROJ-44: DMS BankTransaction Lifecycle Cleanup

## Status: In Progress
**Created:** 2026-06-24
**Last Updated:** 2026-06-24

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
_To be added by /qa_

## Deployment
_To be added by /deploy_
