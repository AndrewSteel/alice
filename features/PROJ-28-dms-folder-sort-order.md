# PROJ-28: DMS Verzeichnis-Reihenfolge

## Status: Deployed
**Created:** 2026-03-22
**Last Updated:** 2026-03-22
**Deployed:** 2026-03-22

## Dependencies
- Requires: PROJ-15 (DMS NAS-Ordner-Verwaltung) — Tabelle `alice.dms_watched_folders` und Frontend-Seite existieren
- Requires: PROJ-16 (DMS Scanner) — Workflow `alice-dms-scanner` liest aktive Ordner

## Overview

Manche NAS-Ordner haben einen expliziten `suggested_type` (z.B. "Rechnung"), andere lassen die Klassifikation offen (`null` = auto). Damit typisierte Unterordner vor generischen Hauptordnern verarbeitet werden, soll der Admin die Verarbeitungsreihenfolge der Ordner manuell festlegen können.

Die Reihenfolge wird per Drag-and-Drop im Frontend eingestellt und als `sort_order`-Spalte in PostgreSQL persistiert. Der `alice-dms-scanner`-Workflow liest die Ordner fortan sortiert nach diesem Wert.

## User Stories

- Als Admin möchte ich festlegen, in welcher Reihenfolge die DMS-Ordner beim Scan abgearbeitet werden, damit typisierte Unterordner (mit `suggested_type`) vor allgemeinen Ordnern verarbeitet werden.
- Als Admin möchte ich die Reihenfolge im Frontend durch Verschieben (Drag-and-Drop) der Einträge ändern, damit ich keine direkte Datenbankoperation ausführen muss.
- Als Admin möchte ich, dass die geänderte Reihenfolge sofort gespeichert wird, damit ich keine explizite Speicher-Aktion ausführen muss.
- Als Admin möchte ich, dass neue Ordner am Ende der Liste eingefügt werden, damit bestehende Reihenfolgen nicht gestört werden.
- Als System (`alice-dms-scanner`) möchte ich die Ordner in der konfigurierten `sort_order` verarbeiten, damit Ordner mit explizitem Typ vor Auto-Ordnern in die MQTT-Queue gelangen.

## Acceptance Criteria

### Datenbank
- [ ] Spalte `sort_order INTEGER NOT NULL DEFAULT 0` wird zu `alice.dms_watched_folders` hinzugefügt
- [ ] Index auf `sort_order` existiert (für performantes `ORDER BY`)
- [ ] Migration-Datei `sql/migrations/XXX-proj28-dms-folder-sort-order.sql` initialisiert `sort_order` für bestehende Einträge aufsteigend nach `id` (d.h. bisherige Einfügereihenfolge bleibt erhalten)
- [ ] `sort_order`-Werte sind nicht zwingend lückenlos (1, 2, 5 ist valide); nur die relative Reihenfolge zählt

### Backend API
- [ ] Neuer Endpunkt **PATCH** `/webhook/dms/folders/reorder` im Workflow `alice-dms-folder-api`
- [ ] Request-Body: `{ "order": [{ "id": 3, "sort_order": 1 }, { "id": 1, "sort_order": 2 }, ...] }`
- [ ] Endpunkt aktualisiert alle übergebenen Einträge in einer Transaktion (oder sequenziell) und gibt die aktualisierte Liste zurück
- [ ] JWT-Schutz analog zu bestehenden Endpunkten (Admin-Rolle erforderlich)
- [ ] **GET** `/webhook/dms/folders` gibt Ordner fortan sortiert nach `sort_order ASC, id ASC` zurück
- [ ] **POST** `/webhook/dms/folders` (neuer Ordner) setzt `sort_order` auf `MAX(sort_order) + 1` aller vorhandenen Ordner, sodass neue Einträge immer ans Ende kommen

### Frontend
- [ ] Die Tabelle auf der DMS-Ordner-Seite (`/settings` → DMS-Tab) zeigt das Drag-and-Drop-Handle-Icon (GripVertical) rechts neben den bestehenden Aktions-Icons (Bearbeiten, Löschen)
- [ ] Zeilen können per Drag-and-Drop verschoben werden (touch- und mausbasiert)
- [ ] Nach dem Loslassen wird sofort ein PATCH-Request an `/api/webhook/dms/folders/reorder` mit der neuen Reihenfolge gesendet
- [ ] Während des Speicherns zeigt die Tabelle einen Lade-Indikator (kein Full-Screen-Spinner, subtil in der Zeile oder am Tabellenrand)
- [ ] Bei Fehler wird ein Toast angezeigt und die Tabelle springt zur vorherigen Reihenfolge zurück (optimistic rollback)
- [ ] Die Reihenfolge der angezeigten Zeilen entspricht der `sort_order` aus der API-Antwort

### n8n Scanner
- [ ] Der PostgreSQL-Node "PG: Active Folders" im Workflow `alice-dms-scanner` liest mit `ORDER BY sort_order ASC, id ASC`
- [ ] Keine weiteren Änderungen am Workflow erforderlich — der restliche Ablauf ist reihenfolgeunabhängig

## Edge Cases

- **Neuer Ordner via POST**: `sort_order = MAX(sort_order) + 1`; bei leerer Tabelle → `sort_order = 1`.
- **PATCH mit unvollständiger Liste** (nicht alle IDs übergeben): API aktualisiert nur die übergebenen Einträge; nicht genannte Einträge behalten ihren bisherigen `sort_order`. Keine Fehlerreaktion.
- **PATCH mit doppelten `sort_order`-Werten in der Payload**: API führt das Update durch; Gleichstand wird durch `id ASC` als Tiebreaker aufgelöst (kein Fehler).
- **Alle Ordner haben denselben `sort_order = 0`** (Ausgangszustand nach Migration): Reihenfolge wird durch `id ASC` bestimmt — entspricht der bisherigen Einfügereihenfolge.
- **Drag-and-Drop auf Touch-Gerät**: Drag-Library muss Touch-Events unterstützen (z.B. `@dnd-kit/core`).
- **Gleichzeitige Reorder-Requests** von zwei Admin-Sessions: Letzte Anfrage gewinnt (Last Write Wins); kein Conflict-Handling notwendig (Einzelplatz-Setup).
- **Netzwerkfehler beim Speichern**: Optimistic Update wird rückgängig gemacht; Toast zeigt Fehler an.
- **Ordner wird während Drag gelöscht** (z.B. in anderer Session): Nächster GET nach dem Reorder liefert aktuelle Liste; UI wird aktualisiert.
- **Scanner läuft während Reorder**: Der laufende Scan-Job liest die Ordner einmal zu Beginn; eine Reihenfolgeänderung wirkt sich erst beim nächsten Scan-Lauf aus.

## Technical Requirements

- **DB-Migration**: `sql/migrations/XXX-proj28-dms-folder-sort-order.sql`
  ```sql
  ALTER TABLE alice.dms_watched_folders
    ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0;

  -- Bestehende Einträge: sort_order = id (relative Reihenfolge erhalten)
  UPDATE alice.dms_watched_folders SET sort_order = id;

  CREATE INDEX idx_dms_watched_folders_sort_order
    ON alice.dms_watched_folders (sort_order ASC);
  ```
- **n8n Workflow-Änderung**: `alice-dms-folder-api` — neuer Switch-Zweig für `PATCH /reorder`; GET-Query um `ORDER BY sort_order ASC, id ASC` ergänzt; POST-Handler um `sort_order`-Berechnung ergänzt
- **n8n Workflow-Änderung**: `alice-dms-scanner` — GET-Query um `ORDER BY sort_order ASC, id ASC` ergänzt
- **Frontend-Library**: `@dnd-kit/core` + `@dnd-kit/sortable` (bereits in vielen shadcn-Projekten genutzt, kein Overhead)
- **Authentifizierung**: JWT mit `role = admin` — analog zu allen bestehenden DMS-Admin-Endpunkten

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

PROJ-28 ist ein Full-Stack-Feature mit drei Schichten: Datenbankschema, zwei n8n-Workflow-Änderungen und Frontend-Erweiterung. Die Gesamtänderung ist chirurgisch — keine bestehende Komponente wird ersetzt, nur erweitert.

---

### Datenbankschicht

Die Tabelle `alice.dms_watched_folders` bekommt eine neue Spalte `sort_order` (Ganzzahl). Ein Index sorgt dafür, dass die `ORDER BY`-Abfrage im Scanner performant bleibt.

Beim Anlegen der Migration werden bestehende Einträge einmalig mit ihrer bisherigen ID als Startreihenfolge befüllt — der Admin sieht sofort eine sinnvolle Ausgangsreihenfolge statt lauter Nullen.

```
alice.dms_watched_folders
  + sort_order  INTEGER  NOT NULL  DEFAULT 0
  + INDEX (sort_order ASC)
```

Migrationsdatei: `sql/migrations/013-proj28-dms-folder-sort-order.sql`

---

### Backend: n8n Workflow `alice-dms-folder-api`

Drei gezielte Änderungen am bestehenden Workflow:

```
[Switch: Method + Path]
  │
  ├── GET  /folders        → PostgreSQL SELECT ... ORDER BY sort_order ASC, id ASC
  │                           (bisher kein ORDER BY — jetzt sortiert)
  │
  ├── POST /folders        → PostgreSQL INSERT ...
  │                           sort_order = SELECT MAX(sort_order) + 1 FROM ...
  │                           (neuer Ordner landet automatisch am Ende)
  │
  ├── PUT  /folders        → unverändert
  ├── DELETE /folders      → unverändert
  │
  └── PATCH /folders/reorder  ← NEU
        JWT-Validierung (Admin-Rolle)
        Body: { "order": [{ "id": 3, "sort_order": 1 }, ...] }
        PostgreSQL: UPDATE ... SET sort_order = $2 WHERE id = $1
          (sequenziell für jeden Eintrag im Array)
        Response: aktualisierte Ordnerliste (SELECT ... ORDER BY sort_order ASC, id ASC)
```

Der neue PATCH-Zweig im Switch-Node erkennt die Kombination `PATCH` + Pfad enthält `/reorder`.

---

### Backend: n8n Workflow `alice-dms-scanner`

Minimale Änderung: Der PostgreSQL-Node "PG: Active Folders" bekommt `ORDER BY sort_order ASC, id ASC` in seiner Query. Der Rest des Workflows ist völlig unberührt — die Reihenfolge, in der Dateien in die MQTT-Queue eingestellt werden, folgt nun der Admin-Konfiguration.

---

### Frontend-Komponentenbaum

```
DmsSection (bestehend, erweitert)
  ├── useDmsFolders (Hook, erweitert — neue Action: reorderFolders)
  │
  ├── [DnD context: DndContext + SortableContext]  ← NEU
  │     FoldersTable → SortableFoldersTable (bestehend, erweitert)
  │       ├── [für jede Zeile: SortableRow]  ← NEU
  │       │     Pfad | Typ | Beschreibung | Status-Switch | Aktionen [Pencil | Trash | GripVertical]
  │       │                                                                                 ↑ NEU, rechts außen
  │       │     [Lade-Indikator während PATCH läuft]  ← NEU
  │       └── ...
  │
  ├── AddFolderDialog (unverändert)
  ├── EditFolderDialog (unverändert)
  └── DeleteFolderDialog (unverändert)
```

**Änderungen je Datei:**

| Datei | Art der Änderung |
|---|---|
| `services/dms.ts` | `DmsFolder` um `sort_order: number` erweitern; neue Funktion `reorderFolders()` |
| `hooks/useDmsFolders.ts` | Neue Action `reorderFolders` (optimistic update + rollback) |
| `components/Settings/FoldersTable.tsx` | Drag-and-Drop via `@dnd-kit/sortable`; neue `onReorder`-Prop; Handle-Spalte links |
| `components/Settings/DmsSection.tsx` | `handleReorder`-Handler + `onReorder`-Prop an FoldersTable übergeben |

---

### Datenfluss: Drag-and-Drop

```
Admin zieht Zeile
    │
    ▼
onDragEnd (dnd-kit Event)
    │
    ▼
Neue Reihenfolge berechnen (arrayMove)
    │
    ▼
Optimistic Update: lokalen State sofort neu setzen
    │
    ▼
PATCH /api/webhook/dms/folders/reorder
    ├── Erfolg → State mit Server-Antwort aktualisieren (sync)
    └── Fehler → State auf vorherige Reihenfolge zurücksetzen + Toast
```

---

### Tech-Entscheidungen

**Warum `@dnd-kit` statt HTML5 Drag-and-Drop?**
HTML5 DnD hat bekannte Schwächen auf Touch-Geräten und erfordert viel Eigenimplementierung für Tabellen-Rows. `@dnd-kit/sortable` ist leichtgewichtig (~15 kB), touch-kompatibel, barrierefrei (Keyboard-DnD) und wird auch von shadcn-Beispielen für sortierbare Listen empfohlen.

**Warum Optimistic Update statt Warten auf API?**
Das Drag-and-Drop fühlt sich responsiv an — die Zeile "fliegt" sofort an ihre neue Position. Bei einem Netzwerkfehler (sehr selten im lokalen VPN-Setup) springt die Liste zurück und ein Toast erklärt den Fehler. Kein Dialog, keine Blockierung.

**Warum `sort_order` nicht gapless halten?**
Lückenlose Nummerierung (1,2,3,...) nach jedem Reorder wäre eine zusätzliche `UPDATE`-Komplexität ohne Mehrwert. Die relative Reihenfolge (`ORDER BY sort_order ASC`) ist das einzige was zählt. 1, 3, 7 sortiert genauso korrekt wie 1, 2, 3.

**Warum kein separater `sort_order`-Endpunkt im Scanner?**
Der Scanner liest einmal pro Stunden-Tick alle aktiven Ordner. Die Sortierung ist eine reine SQL-Änderung (`ORDER BY`), kein neuer Workflow-Zweig nötig.

---

### Neue Abhängigkeiten

| Paket | Zweck |
|---|---|
| `@dnd-kit/core` | Drag-and-Drop Basisframework |
| `@dnd-kit/sortable` | Sortierbare Listen (aufbauend auf core) |
| `@dnd-kit/utilities` | Hilfsfunktion `arrayMove` für Reihenfolge-Berechnung |

## QA Test Results

**Tested:** 2026-03-22 (re-test)
**Scope:** Backend only (Database Migration, n8n Workflows: alice-dms-folder-api, alice-dms-scanner)
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-DB: Datenbank

- [x] Spalte `sort_order INTEGER NOT NULL DEFAULT 0` wird zu `alice.dms_watched_folders` hinzugefuegt
  - File `sql/migrations/012-proj28-dms-folder-sort-order.sql` adds column with `ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0`
- [x] Index auf `sort_order` existiert (fuer performantes `ORDER BY`)
  - `CREATE INDEX IF NOT EXISTS idx_dms_watched_folders_sort_order ON alice.dms_watched_folders (sort_order ASC)` is present
- [x] Migration initialisiert `sort_order` fuer bestehende Eintraege aufsteigend nach `id`
  - `UPDATE alice.dms_watched_folders SET sort_order = id;` preserves insertion order
- [x] `sort_order`-Werte sind nicht zwingend lueckenlos -- relative Reihenfolge zaehlt
  - No UNIQUE constraint on sort_order; only ORDER BY sort_order ASC, id ASC is used throughout

**Note:** Spec references filename `013-proj28-dms-folder-sort-order.sql` but actual file is `012-proj28-dms-folder-sort-order.sql`. This is a spec-vs-implementation naming discrepancy, not a functional bug.

#### AC-API: Backend API

- [x] Neuer Endpunkt **PATCH** `/webhook/dms/folders/reorder` im Workflow `alice-dms-folder-api`
  - Webhook node with `httpMethod: "PATCH"` and `path: "dms/folders/reorder"` exists (typeVersion 2.1, webhookId: dms-f5-patch-reorder)
- [x] Request-Body `{ "order": [{ "id": 3, "sort_order": 1 }, ...] }` accepted
  - Validation code parses `body.order` array, extracts `id` and `sort_order` as integers via `parseInt(..., 10)`
- [x] Endpunkt aktualisiert alle uebergebenen Eintraege und gibt aktualisierte Liste zurueck
  - UPDATE uses `UNNEST($1::int[], $2::int[])` for batch update; followed by full SELECT with ORDER BY sort_order ASC, id ASC via "PG: List After Reorder" node
- [x] JWT-Schutz analog zu bestehenden Endpunkten (Admin-Rolle erforderlich)
  - Webhook node uses `authentication: "jwtAuth"` with credential `4iUJhbFCSgQeHAGL` (JWT Auth account); Code node checks `payload.role !== 'admin'` and returns `_forbidden: true` which routes via "IF: PATCH Admin" to 403
- [x] **GET** `/webhook/dms/folders` gibt Ordner sortiert nach `sort_order ASC, id ASC` zurueck
  - PG: List Folders query: `SELECT COALESCE(JSON_AGG(JSON_BUILD_OBJECT(...) ORDER BY sort_order ASC, id ASC), '[]'::json) AS folders`
- [x] GET response includes `sort_order` field in JSON output
  - `JSON_BUILD_OBJECT` includes `'sort_order', sort_order`
- [x] **POST** `/webhook/dms/folders` setzt `sort_order` auf `MAX(sort_order) + 1`
  - INSERT query: `sort_order = (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM alice.dms_watched_folders)` -- handles empty table (COALESCE to 0) and appends to end
- [x] POST RETURNING clause includes `sort_order` in response
  - Confirmed: `RETURNING id, path, suggested_type, description, enabled, sort_order, created_at::text, updated_at::text`

#### AC-Scanner: n8n Scanner

- [x] PostgreSQL-Node "PG: Active Folders" im Workflow `alice-dms-scanner` liest mit `ORDER BY sort_order ASC, id ASC`
  - Query: `SELECT id, path, suggested_type FROM alice.dms_watched_folders WHERE enabled = true ORDER BY sort_order ASC, id ASC`
- [x] Keine weiteren Aenderungen am Workflow erforderlich
  - Only the ORDER BY clause was added to the existing query; rest of scanner is unchanged

### Edge Cases Status

#### EC-1: Neuer Ordner via POST (sort_order = MAX + 1; leere Tabelle = 1)
- [x] Handled correctly -- `COALESCE(MAX(sort_order), 0) + 1` returns 1 for empty table

#### EC-2: PATCH mit unvollstaendiger Liste
- [x] Handled correctly -- UPDATE uses `WHERE t.id = v.id`, so only submitted IDs are updated; others keep their current sort_order

#### EC-3: PATCH mit doppelten sort_order-Werten
- [x] Handled correctly -- No UNIQUE constraint on sort_order; tiebreaker is `id ASC` in all ORDER BY clauses

#### EC-4: Alle Ordner haben sort_order = 0 (Ausgangszustand nach Migration)
- [x] Spec describes theoretical edge case; migration backfills sort_order = id so this state never occurs in practice. Functionally correct regardless: ORDER BY sort_order ASC, id ASC handles ties via id

#### EC-5: Gleichzeitige Reorder-Requests (Last Write Wins)
- [x] Acceptable -- no conflict handling needed per spec; last UPDATE wins naturally in PostgreSQL

#### EC-6: Scanner laeuft waehrend Reorder
- [x] Acceptable -- scanner reads folders once at start; reorder takes effect on next run

### Security Audit Results (Red Team)

#### Authentication
- [x] PATCH /reorder webhook uses n8n JWT Auth credential (id: `4iUJhbFCSgQeHAGL`) -- invalid/missing JWT rejected at webhook level before code execution
- [x] JWT payload decoded from base64url only after n8n has validated signature -- no signature bypass possible

#### Authorization
- [x] Admin role check: `payload.role !== 'admin'` returns `_forbidden: true`, routed via IF node to 403 Forbidden with clear error message "Forbidden: admin role required"
- [x] Non-admin users cannot reorder folders

#### Input Validation
- [x] Empty or non-array `order` body returns 400 with descriptive error
- [x] Entries with non-integer `id` or `sort_order` return 400
- [x] `parseInt` used with radix 10 -- no octal/hex parsing issues
- [x] SQL injection prevented: parameterized queries with `$1::int[]` and `$2::int[]` -- user input never concatenated into SQL
- [x] Array size capped at 100 entries -- `order.length > 100` returns 400 with descriptive error (fixes previous BUG-2)
- [x] Negative sort_order values rejected -- `so < 0` returns 400 with descriptive error (fixes previous BUG-3)

#### Denial of Service / Resource Exhaustion
- [x] Array size limit of 100 entries prevents memory pressure from oversized payloads (fixed since initial QA)

#### Data Integrity
- [x] UPDATE only affects rows WHERE t.id = v.id -- non-existent IDs are silently ignored (no error, no side effect)
- [x] No risk of updating other tables -- query is scoped to `alice.dms_watched_folders`

#### Information Disclosure
- [x] Error responses do not leak internal details (only generic "Validation failed" or "admin role required")
- [x] PATCH 200 response returns full folder list -- same data as GET endpoint, appropriate for admin

### Previous Bug Fix Verification

#### BUG-1 (from initial QA): PUT endpoint RETURNING clause missing `sort_order` field
- **Status:** FIXED
- **Verification:** PUT query now includes `sort_order` in RETURNING clause: `RETURNING id, path, suggested_type, description, enabled, sort_order, created_at::text, updated_at::text`

#### BUG-2 (from initial QA): No array size limit on PATCH /reorder payload
- **Status:** FIXED
- **Verification:** Validation code checks `order.length > 100` and returns `_validationError` with descriptive message, routed to 400 response

#### BUG-3 (from initial QA): Negative sort_order values accepted
- **Status:** FIXED
- **Verification:** Validation code checks `so < 0` and returns `_validationError: 'sort_order must be a non-negative integer'`, routed to 400 response

### Bugs Found (Re-test)

No new bugs found.

### Regression Check

- [x] GET /webhook/dms/folders -- returns folder list with sort_order field, sorted by sort_order ASC, id ASC
- [x] POST /webhook/dms/folders -- creates folders with auto-assigned sort_order (MAX + 1), RETURNING includes sort_order
- [x] PUT /webhook/dms/folders -- updates folders, RETURNING now includes sort_order (BUG-1 fixed)
- [x] DELETE /webhook/dms/folders -- unmodified, still works (no sort_order impact)
- [x] alice-dms-scanner -- query updated with ORDER BY sort_order ASC, id ASC; no other changes to workflow logic
- [x] Workflow connection graph verified: Webhook -> JWT+Validate -> IF: Admin -> IF: Valid -> PG: Reorder -> PG: List After Reorder -> Aggregate -> Respond 200 (with 403 and 400 error branches properly wired)

### Summary
- **Acceptance Criteria:** 12/12 passed (all backend ACs met)
- **Edge Cases:** 6/6 functionally correct
- **Previous Bugs Fixed:** 3/3 verified fixed (BUG-1 Medium, BUG-2 Low, BUG-3 Low)
- **New Bugs Found:** 0
- **Security:** Pass (JWT auth, admin role check, parameterized SQL, array size limit, negative value rejection)
- **Production Ready:** YES -- all previously identified bugs have been fixed; no new issues found

## QA Test Results -- Frontend

**Tested:** 2026-03-22
**Scope:** Frontend (React components, hooks, service layer, DnD integration)
**Tester:** QA Engineer (AI)
**Build Status:** PASS (no compilation errors)

### Acceptance Criteria Status

#### AC-FE-1: Drag-and-Drop Handle-Icon (GripVertical) rechts neben Aktions-Icons

- [x] Desktop table (md+): Action column order is Pencil (edit) -> Trash2 (delete) -> GripVertical (drag handle), rightmost position
  - `FoldersTable.tsx` lines 114-159: `flex items-center justify-end gap-1` with handle as last child
- [x] Mobile card layout (<md): Drag handle is positioned left of path text, appropriate for touch UX
  - `FoldersTable.tsx` lines 204-217: handle is `shrink-0` before the path `<p>` element

**Status: PASS**

#### AC-FE-2: Zeilen koennen per Drag-and-Drop verschoben werden (touch- und mausbasiert)

- [x] PointerSensor configured with `activationConstraint: { distance: 8 }` -- prevents accidental drags on click
- [x] TouchSensor configured with `activationConstraint: { delay: 200, tolerance: 5 }` -- touch-friendly with delay to distinguish from scroll
- [x] KeyboardSensor with `sortableKeyboardCoordinates` -- accessibility: keyboard DnD supported
- [x] `restrictToVerticalAxis` modifier prevents horizontal movement during drag
- [x] `verticalListSortingStrategy` used for correct vertical list sorting behavior
- [x] `closestCenter` collision detection for accurate drop targeting
- [x] `useSortable` hook applied to both desktop (`SortableDesktopRow`) and mobile (`SortableMobileRow`) rows
- [x] Dragging visual feedback: `isDragging` applies `bg-gray-800 opacity-80 shadow-lg z-50 relative`
- [x] Cursor feedback: `cursor-grab` default, `active:cursor-grabbing` while dragging

**Status: PASS**

#### AC-FE-3: Nach dem Loslassen wird sofort ein PATCH-Request gesendet

- [x] `handleDragEnd` in `FoldersTable.tsx` calls `onReorder(reordered)` with `arrayMove` result
- [x] Guard clause: returns early if `!over || active.id === over.id` (no-op on same position)
- [x] `DmsSection.handleReorder` calls `reorderFolders(reorderedFolders)` (no confirmation dialog)
- [x] `useDmsFolders.reorderFolders` builds `order` array with `index + 1` as `sort_order` values
- [x] `dms.ts.reorderFolders` sends `PATCH` to `/api/webhook/dms/folders/reorder` with `{ order: [...] }` body
- [x] Request includes JWT `Authorization: Bearer <token>` header via `authHeaders()`

**Status: PASS**

#### AC-FE-4: Lade-Indikator waehrend des Speicherns (subtil, nicht Full-Screen)

- [x] `isReordering` state managed in `useDmsFolders` hook (set true before PATCH, false in finally block)
- [x] Desktop: GripVertical icon replaced with `Loader2 animate-spin` per-row when `isReordering === true`
- [x] Mobile: Same Loader2 replacement on mobile drag handle
- [x] No full-screen spinner or blocking overlay -- indicator is scoped to the drag handle icon

**Status: PASS**

#### AC-FE-5: Bei Fehler: Toast + optimistic rollback

- [x] Previous folders saved to `previousFoldersRef.current` before optimistic update (`useDmsFolders.ts` line 86)
- [x] Optimistic update: `setFolders(reorderedFolders)` applied immediately (`useDmsFolders.ts` line 89)
- [x] On API success: state synced with server response `setFolders(updatedFolders)` (line 98)
- [x] On API error: rollback to `previousFoldersRef.current` (line 101), then throws error
- [x] `DmsSection.handleReorder` catches thrown error and displays destructive toast with error message (lines 81-85)
- [x] Auth errors (401): `handleAuthError` in `dms.ts` clears token and redirects to login
- [x] Network errors: caught in try/catch, throws descriptive German error message

**Status: PASS**

#### AC-FE-6: Angezeigte Reihenfolge entspricht sort_order aus der API-Antwort

- [x] `getFolders` returns folder array in API order (sorted by `sort_order ASC, id ASC` server-side)
- [x] `reorderFolders` response unwrapped with same logic as `getFolders`
- [x] After successful PATCH, folders state replaced with server response (not just local reorder)
- [x] `DmsFolder` type includes `sort_order: number` field

**Status: PASS**

### Edge Cases Status (Frontend-specific)

#### EC-FE-1: Drag-and-Drop auf Touch-Geraet

- [x] `@dnd-kit/core` TouchSensor configured with appropriate delay (200ms) and tolerance (5px)
- [x] Mobile layout provides dedicated drag handle with `touch-none` CSS to prevent browser scroll interference
- [ ] BUG-FE-1: Desktop drag handle missing `touch-none` CSS class (see Bugs section)

#### EC-FE-2: Netzwerkfehler beim Speichern

- [x] Optimistic update is rolled back via `previousFoldersRef.current`
- [x] Toast displayed with descriptive error message
- [x] `isReordering` flag reset in `finally` block -- prevents stuck loading state

#### EC-FE-3: Schnelles doppeltes Drag-and-Drop (Race Condition)

- [ ] BUG-FE-2: Rapid sequential drags can cause incorrect rollback state (see Bugs section)

#### EC-FE-4: Empty folder list

- [x] Empty state displays "Noch keine Ordner konfiguriert" message instead of table
- [x] No DnD context errors when folder list is empty (DndContext/SortableContext handle empty arrays)

#### EC-FE-5: Ordner wird waehrend Drag geloescht (andere Session)

- [x] After PATCH response, folders state is synced with server response -- deleted folder would disappear
- [x] If PATCH fails (e.g., because folder was deleted), rollback shows previous state; user sees stale data until next page load

### Responsive Layout Testing (Static Code Review)

#### Mobile (375px)

- [x] Card layout visible via `md:hidden` -- stacked vertical layout with drag handle, path, type badge, actions
- [x] Path text has `break-all` class to handle long NAS paths without overflow
- [x] Action buttons are compact (`size="sm"`, `h-7`) with text labels for clarity
- [x] Drag handle positioned left of content for natural thumb reach

#### Tablet (768px)

- [x] Table layout visible via `hidden md:block` -- standard table with columns
- [x] Path column has `max-w-[300px] truncate` to prevent table overflow
- [x] Description column has `max-w-[200px]` with truncation at 60 characters

#### Desktop (1440px)

- [x] Same table layout as tablet, benefits from extra width
- [x] `max-w-5xl` container in SettingsPage (line 35) caps content width at 1280px -- appropriate for readability
- [x] Table fits comfortably with all 5 columns visible

**Note:** Cross-browser testing (Chrome, Firefox, Safari) requires a running application instance and could not be performed via static code review. The implementation uses standard CSS (flexbox, Tailwind utilities) and well-tested library (@dnd-kit) which have excellent cross-browser compatibility.

### Security Audit Results (Frontend Red Team)

#### Authentication

- [x] All DMS API calls include JWT via `authHeaders()` function
- [x] Missing token triggers redirect to `/login` and throws error (prevents unauthenticated requests)
- [x] 401 responses handled: token cleared, redirect to login via `handleAuthError`
- [x] Token stored in localStorage (consistent with existing auth pattern in project)

#### Authorization

- [x] DMS tab only visible to admin users: `{isAdmin && <TabsTrigger value="dms">}` in `SettingsPage.tsx`
- [x] DMS content only rendered for admin: `{isAdmin && <TabsContent value="dms">}`
- [x] 403 responses from API result in "Zugriff verweigert -- Admin-Rechte erforderlich" error message
- [x] Non-admin users cannot see or interact with the DMS folder management UI

#### Input Validation (Frontend)

- [x] `reorderFolders` builds order array from actual folder objects -- no user-controlled text input involved
- [x] `sort_order` values are computed as `index + 1` (sequential integers) -- no injection vector
- [x] Folder IDs come from server-provided data, not user input

#### XSS Prevention

- [x] React JSX auto-escapes all rendered text (folder paths, descriptions, types)
- [x] No `dangerouslySetInnerHTML` usage anywhere in the component tree
- [x] Truncation function returns plain strings, no HTML

#### Sensitive Data Exposure

- [x] JWT token only sent in Authorization header, not logged to console
- [x] Error messages shown to user are generic German text, no internal details
- [x] `dms.ts` error handlers do not expose raw server response bodies in user-facing errors

### Bugs Found (Frontend)

#### BUG-FE-1: Desktop drag handle missing `touch-none` CSS class

- **Severity:** Low
- **Steps to Reproduce:**
  1. Open DMS folder settings on a touchscreen laptop/desktop at >= 768px width
  2. Try to drag a folder row using the GripVertical handle via touch
  3. Expected: Touch drag works smoothly without browser scroll interference
  4. Actual: Browser may intercept touch events for scrolling because the desktop handle button (line 147) lacks `touch-none` CSS, unlike the mobile handle (line 209) which has it
- **Impact:** Only affects touchscreen desktop/laptop users. PointerSensor and TouchSensor delay constraints partially mitigate this, but scroll interference is possible.
- **Priority:** Nice to have -- fix in next sprint

#### BUG-FE-2: Rapid sequential drags can cause incorrect rollback state

- **Severity:** Low
- **Steps to Reproduce:**
  1. Open DMS folder settings with 3+ folders
  2. Drag folder A to a new position (PATCH request starts)
  3. Before the first PATCH completes, immediately drag folder B to a different position
  4. If the first PATCH fails, rollback uses `previousFoldersRef.current` which was overwritten by the second drag
  5. Expected: Rollback returns to the original pre-drag state
  6. Actual: Rollback returns to the intermediate state (after first drag but before second)
- **Impact:** Very low in practice -- single-admin VPN setup, local network latency is minimal, and successful PATCH is the normal case. The `isReordering` flag shows a spinner but does NOT disable further drags.
- **Priority:** Nice to have -- fix in next sprint (could be mitigated by disabling drag when `isReordering === true`)

### Dependencies Check

- [x] `@dnd-kit/core@6.3.1` installed and compatible
- [x] `@dnd-kit/sortable@10.0.0` installed, peer dependency `@dnd-kit/core ^6.3.0` satisfied
- [x] `@dnd-kit/utilities@3.2.2` installed (provides `CSS.Transform`)
- [x] `@dnd-kit/modifiers@9.0.0` installed, peer dependency `@dnd-kit/core ^6.3.0` satisfied
- [x] No version conflicts or missing peer dependencies

### Regression Check (Frontend)

- [x] `DmsFolder` type extended with `sort_order: number` -- backward compatible (additive field)
- [x] `getFolders` response unwrapping handles multiple formats (n8n array wrapper, plain array, object wrapper) -- robust
- [x] `createFolder` appends new folder to end of local state -- consistent with API sort_order assignment
- [x] `updateFolder` replaces folder in-place (same position in array) -- does not affect sort order display
- [x] `deleteFolder` filters folder from local state -- remaining order preserved
- [x] `toggleFolder` uses `updateFolder` internally -- no sort order side effects
- [x] Existing dialogs (Add, Edit, Delete) are unmodified and receive same props as before
- [x] `SettingsPage.tsx` DMS tab rendering unchanged -- admin-only gate still intact

### Summary (Frontend)

- **Acceptance Criteria:** 6/6 passed (all frontend ACs met)
- **Edge Cases:** 3/5 passed, 2 with low-severity bugs
- **Responsive:** Mobile card layout and desktop table layout both correctly implemented
- **Cross-Browser:** Static analysis only (standard CSS + well-tested library -- low risk)
- **Security:** PASS (auth gates, XSS prevention, no data leaks)
- **Bugs Found:** 2 total (0 critical, 0 high, 0 medium, 2 low)
- **Production Ready:** YES -- both bugs are low severity with minimal real-world impact

### Combined Summary (Backend + Frontend)

- **Total Acceptance Criteria:** 18/18 passed
- **Total Bugs:** 2 low-severity frontend bugs (BUG-FE-1, BUG-FE-2)
- **Security:** PASS across all layers
- **Production Ready:** YES

> Found 2 bugs (2 low). Both are edge-case UX issues that do not affect core functionality. The feature can be deployed as-is. After deployment, the developer can address these in the next sprint. After fixes, run `/qa` again.

## Deployment
_To be added by /deploy_
