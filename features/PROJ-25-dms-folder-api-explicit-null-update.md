# PROJ-25: DMS Folder API — Explicit Null Update für nullable Felder

## Status: Deployed
**Created:** 2026-03-15
**Last Updated:** 2026-03-15

## Dependencies
- Requires: PROJ-15 (DMS Folder Management) — Workflow `alice-dms-folder-api` muss deployed sein
- Requires: PROJ-23 (DMS Security Hardening) — COALESCE-Pattern aus Fix 2 ist die Basis dieses Fixes

## Overview

Funktions-Regression aus PROJ-23 (BUG-1): Der PUT-Endpunkt des `alice-dms-folder-api`-Workflows kann die nullable Felder `suggested_type` und `description` nicht explizit auf `null` setzen (d.h. löschen). Die in PROJ-23 eingeführte COALESCE-Lösung behandelt `null` als "Feld nicht gesendet" (Wert beibehalten) — es ist nicht möglich, zwischen "nicht gesendet" und "explizit auf null gesetzt" zu unterscheiden.

## User Stories

- Als Admin möchte ich `suggested_type` eines Ordners auf "automatisch" (null) zurücksetzen können, damit der DMS Processor wieder das LLM zur Klassifikation nutzt statt eines festen Hints.
- Als Admin möchte ich die `description` eines Ordners löschen können, damit veraltete Beschreibungstexte entfernt werden können.
- Als Admin möchte ich, dass Felder, die ich nicht im PUT-Body mitschicke, unverändert bleiben, damit partial updates weiterhin korrekt funktionieren.

## Acceptance Criteria

- [ ] PUT `/webhook/dms/folders` mit `{ "id": 1, "suggested_type": null }` setzt `suggested_type` auf `NULL` in der Datenbank
- [ ] PUT `/webhook/dms/folders` mit `{ "id": 1, "description": null }` setzt `description` auf `NULL` in der Datenbank
- [ ] PUT `/webhook/dms/folders` ohne `suggested_type`-Key im Body lässt `suggested_type` unverändert (bisheriges Verhalten)
- [ ] PUT `/webhook/dms/folders` ohne `description`-Key im Body lässt `description` unverändert (bisheriges Verhalten)
- [ ] `path` und `enabled` bleiben vom Fix unberührt (`path` ist required und kann nicht null sein; `enabled` ist boolean und nicht nullable)
- [ ] Alle bestehenden AC aus PROJ-15 und PROJ-23 bleiben erfüllt (kein Regressionsrisiko)
- [ ] Keine dynamische SQL-Konstruktion (Prinzip aus PROJ-23 Fix 2 bleibt erhalten)
- [ ] Keine Änderungen am Frontend erforderlich — der `dms.ts`-Service sendet bereits `null` für explizite Löschungen

## Edge Cases

- **`suggested_type: null` gesendet**: Feld wird auf NULL gesetzt → Scanner nutzt LLM-Klassifikation
- **`description: null` gesendet**: Feld wird auf NULL gesetzt → leere Beschreibung
- **`suggested_type` nicht im Body**: Kein Key → bestehendem Wert bleibt (COALESCE-Verhalten)
- **`suggested_type: "Invoice"` gesendet**: Wert wird gesetzt wie bisher
- **Ungültiger `suggested_type`-Wert** (z.B. `"Foo"`): Validierung schlägt wie bisher fehl → 400
- **Nur `id` im Body, sonst nichts**: `hasUpdate = false` → 400 "No fields to update" (bestehend)
- **`enabled: null` gesendet**: `Boolean(null) = false` im Code-Node → wird auf `false` gesetzt (kein Problem, da `enabled` nicht nullable ist und `false` ein gültiger Wert ist)

## Technical Requirements

- **Betroffener Workflow**: `alice-dms-folder-api` — nur der `JWT+Validate: PUT Folder` Code-Node und der `PG: Update Folder` PostgreSQL-Node
- **Lösungsansatz**: "Explicit-null flag" pro nullable Feld
  - Code-Node erkennt, ob der Key im Body vorhanden ist (`'suggested_type' in body`), unabhängig vom Wert
  - Für jeden nullable Field: separates Boolean-Flag `clearSuggestedType`, `clearDescription`
  - PostgreSQL-Node nutzt CASE-Ausdruck statt reinem COALESCE:
    ```sql
    suggested_type = CASE WHEN $6 THEN NULL ELSE COALESCE($2, suggested_type) END,
    description    = CASE WHEN $7 THEN NULL ELSE COALESCE($3, description) END
    ```
  - `$6` = `clearSuggestedType` (boolean), `$7` = `clearDescription` (boolean)
- **Keine DB-Migrationen** — nur Workflow-Änderung
- **Keine Frontend-Änderungen** — `dms.ts` sendet bereits `null` für Felder, die geleert werden sollen
- **Keine nginx-Änderungen**
- **Workflow-Datei**: `workflows/core/alice-dms-folder-api.json`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Scope

Rein operativer Bugfix in einem einzigen n8n-Workflow. Kein Frontend, keine Datenbank, kein nginx.

**Betroffen:** 2 Nodes in `alice-dms-folder-api`
- `JWT+Validate: PUT Folder` (Code Node)
- `PG: Update Folder` (PostgreSQL Node)

---

### Ursache

Das Problem liegt im Zusammenspiel zweier Nodes:

**Code Node (aktuell):** Erkennt bereits korrekt, ob ein Key im Body vorhanden war (`body.suggested_type !== undefined`). Gibt aber in beiden Fällen `null` zurück — egal ob der Key nicht gesendet wurde oder explizit auf `null` gesetzt wurde.

**PG Node (aktuell):** Nutzt `COALESCE($2, existing_value)`. PostgreSQL behandelt beide `null`-Fälle identisch: der bestehende Wert wird beibehalten. Es gibt keinen Mechanismus, um "explizit löschen" von "nicht gesendet" zu unterscheiden.

---

### Lösung: Explicit-Null-Flags

#### Node 1 — Code Node (`JWT+Validate: PUT Folder`)

Das Ausgabe-Objekt erhält zwei neue Boolean-Felder:

| Feld | Wert `true` wenn... | Wert `false` wenn... |
|---|---|---|
| `clearSuggestedType` | `suggested_type: null` explizit gesendet | Key nicht gesendet oder Wert gesetzt |
| `clearDescription` | `description: null` explizit gesendet | Key nicht gesendet oder Wert gesetzt |

Die vorhandene Logik (`if body.suggested_type !== undefined`) bleibt unverändert — es werden lediglich diese zwei Flags ergänzt.

#### Node 2 — PostgreSQL Node (`PG: Update Folder`)

Die `COALESCE`-Ausdrücke für die zwei nullable Felder werden durch `CASE`-Ausdrücke ersetzt:

| Feld | Bisherig | Nach Fix |
|---|---|---|
| `suggested_type` | `COALESCE($2, suggested_type)` | `CASE WHEN $6 THEN NULL ELSE COALESCE($2, suggested_type) END` |
| `description` | `COALESCE($3, description)` | `CASE WHEN $7 THEN NULL ELSE COALESCE($3, description) END` |
| `path`, `enabled` | unverändert | unverändert |
| `folderId` | `$5` | `$5` |

Zwei neue Parameter: `$6` = `clearSuggestedType`, `$7` = `clearDescription`.

**Entscheidungslogik pro Feld:**
- Clear-Flag `true` → Feld wird auf `NULL` gesetzt
- Clear-Flag `false` + Wert vorhanden → Wert wird gesetzt
- Clear-Flag `false` + Wert `null` (nicht gesendet) → `COALESCE` behält bestehenden Wert

---

### Warum dieser Ansatz?

| Alternative | Bewertung |
|---|---|
| **Explicit-Null-Flags (gewählt)** | Kein dynamisches SQL. Statische Query bleibt erhalten. Minimale Änderung. |
| Sentinel-Wert (z.B. `"__CLEAR__"`) | Fragil, API-seitig sichtbar, funktioniert nicht für typisierte Felder |
| Dynamische SQL-Konstruktion | Widerspricht dem Sicherheitsprinzip aus PROJ-23 Fix 2 — explizit ausgeschlossen |
| Separate "clear"-Endpunkte | Unnötige API-Komplexität für einen einfachen Bugfix |

---

### Sicherheitsbewertung

Kein neues Risiko. Die Flags sind boolesche Werte, die der Code Node aus dem Request Body ableitet — kein User Input fließt als SQL-Fragment in die Query. Das Parameterisierungs-Prinzip aus PROJ-23 bleibt vollständig erhalten.

---

### Betroffene Dateien

| Datei | Änderung |
|---|---|
| `workflows/core/alice-dms-folder-api.json` | 2 Nodes geändert (Code + PG für PUT) |

Keine weiteren Dateien betroffen.

## QA Test Results

**Tested:** 2026-03-15
**Tester:** QA Engineer (AI) -- Code Audit + Static Analysis
**Method:** Static code analysis of `workflows/core/alice-dms-folder-api.json`, frontend service `dms.ts`, and `EditFolderDialog.tsx`. This is a backend-only bugfix in an n8n workflow. Testing was performed by auditing the workflow JSON, tracing the data flow from frontend through the API, and simulating edge cases with Node.js scripts.

### Acceptance Criteria Status

#### AC-1: PUT with `{ "id": 1, "suggested_type": null }` sets `suggested_type` to NULL in the database
- [x] Code node computes `clearSuggestedType = ('suggested_type' in body) && body.suggested_type === null` -- correctly detects explicit null
- [x] When `clearSuggestedType` is true, the PG query `CASE WHEN $6 THEN NULL ELSE COALESCE($2, suggested_type) END` evaluates the WHEN branch and sets NULL
- [x] `$6` maps to `$json.clearSuggestedType` in the `queryReplacement` array (position index 5, 0-based)
- **PASS**

#### AC-2: PUT with `{ "id": 1, "description": null }` sets `description` to NULL in the database
- [x] Code node computes `clearDescription = ('description' in body) && body.description === null` -- correctly detects explicit null
- [x] When `clearDescription` is true, the PG query `CASE WHEN $7 THEN NULL ELSE COALESCE($3, description) END` evaluates the WHEN branch and sets NULL
- [x] `$7` maps to `$json.clearDescription` in the `queryReplacement` array (position index 6, 0-based)
- **PASS**

#### AC-3: PUT without `suggested_type` key in body leaves `suggested_type` unchanged
- [x] When `suggested_type` is not in the body: `clearSuggestedType = false` (because `'suggested_type' in body` is false)
- [x] `suggestedType` stays `null` (initialized value, never reassigned)
- [x] In PG: `$6 = false` -> ELSE branch -> `COALESCE(null, suggested_type)` -> keeps existing value
- **PASS**

#### AC-4: PUT without `description` key in body leaves `description` unchanged
- [x] When `description` is not in the body: `clearDescription = false` (because `'description' in body` is false)
- [x] `description` stays `null` (initialized value, never reassigned)
- [x] In PG: `$7 = false` -> ELSE branch -> `COALESCE(null, description)` -> keeps existing value
- **PASS**

#### AC-5: `path` and `enabled` remain unaffected by the fix
- [x] `path` still uses `COALESCE($1, path)` -- no CASE wrapper, unchanged from PROJ-23
- [x] `enabled` still uses `COALESCE($4, enabled)` -- no CASE wrapper, unchanged from PROJ-23
- [x] `path` validation (required, max 500 chars) unchanged
- [x] `enabled` is set via `Boolean(body.enabled)` when present -- not nullable
- **PASS**

#### AC-6: All existing AC from PROJ-15 and PROJ-23 remain fulfilled (no regression)
- [x] GET endpoint unchanged -- no new nodes or modified code
- [x] POST endpoint unchanged -- no new nodes or modified code
- [x] DELETE endpoint unchanged -- no new nodes or modified code
- [x] PUT endpoint: only the Code node and PG node were modified, all other PUT-related nodes (IF checks, error responses) unchanged
- [x] JWT authentication (`jwtAuth` on all webhooks) unchanged
- [x] Admin role check in all four Code nodes unchanged
- [x] PROJ-23 Fix 1 (DELETE parameterized): Still uses `$1` with `queryReplacement` -- CONFIRMED
- [x] PROJ-23 Fix 2 (PUT static COALESCE): Still uses static query, no dynamic SQL -- CONFIRMED (CASE added but still static)
- [x] PROJ-23 Fix 3 (JWT comments): All four security comments still present -- CONFIRMED
- **PASS**

#### AC-7: No dynamic SQL construction (PROJ-23 Fix 2 principle preserved)
- [x] The UPDATE query is still a static string literal in the PG node configuration
- [x] No string concatenation or template literals used to build SQL
- [x] All values are passed via `queryReplacement` parameter array
- [x] The CASE/WHEN/ELSE extension is part of the static query text, not dynamically generated
- **PASS**

#### AC-8: No frontend changes required -- `dms.ts` already sends null for explicit deletions
- [x] `dms.ts` `UpdateFolderInput` interface already has `suggested_type?: string | null` and `description?: string | null`
- [x] `updateFolder()` sends `{ id, ...data }` via `JSON.stringify()` -- null values are preserved in JSON serialization (`{"suggested_type":null}`)
- [x] `EditFolderDialog.tsx` line 65-66: When user selects "Automatisch (LLM)", `newType = null`, and if it differs from current value, `updates.suggested_type = null` is added to the update object
- [x] `EditFolderDialog.tsx` line 68-69: When user clears description, `newDesc = null`, and if it differs from current value, `updates.description = null` is added
- [x] JSON `null` is correctly parsed by n8n as JavaScript `null`, and `'suggested_type' in body` returns `true` for `{"suggested_type": null}`
- [x] No changes were made to any frontend files -- CONFIRMED via `git log --name-only`
- **PASS**

### Edge Cases Status

#### EC-1: `suggested_type: null` sent -- field set to NULL, Scanner uses LLM classification
- [x] `clearSuggestedType = true`, PG CASE returns NULL -- CONFIRMED via code trace
- **PASS**

#### EC-2: `description: null` sent -- field set to NULL
- [x] `clearDescription = true`, PG CASE returns NULL -- CONFIRMED via code trace
- **PASS**

#### EC-3: `suggested_type` not in body -- existing value preserved (COALESCE behavior)
- [x] `clearSuggestedType = false`, `suggestedType = null`, `COALESCE(null, suggested_type)` returns existing -- CONFIRMED
- **PASS**

#### EC-4: `suggested_type: "Invoice"` sent -- value set as before
- [x] `clearSuggestedType = false` (value is not null), `suggestedType = "Invoice"`, `COALESCE("Invoice", suggested_type)` returns "Invoice" -- CONFIRMED
- **PASS**

#### EC-5: Invalid `suggested_type` value (e.g., `"Foo"`) -- validation fails with 400
- [x] Code node validates against `validTypes` array before PG node is reached -- unchanged from PROJ-23
- [x] Returns `_validationError: 'suggested_type must be one of: ...'`
- **PASS**

#### EC-6: Only `id` in body, nothing else -- 400 "No fields to update"
- [x] `hasUpdate` stays `false` when no field keys are present -> returns `_validationError: 'No fields to update'`
- **PASS**

#### EC-7: `enabled: null` sent -- `Boolean(null) = false`, set to false
- [x] `Boolean(null)` evaluates to `false` in the Code node -- correct since `enabled` is not nullable
- [x] `COALESCE(false, enabled)` returns `false` -- updates the field
- **PASS**

### Security Audit Results (Red Team)

#### SQL Injection
- [x] PUT query remains fully parameterized with `$1` through `$7` placeholders
- [x] No string interpolation (`{{ }}`) in the SQL query string
- [x] The CASE/WHEN extension uses parameter references (`$6`, `$7`), not interpolated values
- [x] `clearSuggestedType` and `clearDescription` are boolean values computed in the Code node, not taken from user input. An attacker cannot inject these flags via the request body -- the Code node derives them from the `in` operator check and `=== null` comparison
- **PASS -- no new injection vectors**

#### Flag Manipulation Attack
- [x] Tested: attacker sends `{ "id": 1, "clearSuggestedType": true }` directly in the body. The Code node ignores this -- it computes `clearSuggestedType` from `('suggested_type' in body) && body.suggested_type === null`, which evaluates to `false` because `suggested_type` is not in the body. The attacker-supplied `clearSuggestedType` field is overwritten by the Code node's computed value.
- **PASS -- not exploitable**

#### Authorization
- [x] All four webhook endpoints still require `jwtAuth` authentication
- [x] All four Code nodes still check `payload.role !== 'admin'` and return 403
- [x] No changes to auth flow
- **PASS**

#### Data Integrity
- [x] The `queryReplacement` array has 7 elements matching `$1` through `$7` in the query -- parameter count is consistent
- [x] Parameter order: `[path, suggestedType, description, enabled, folderId, clearSuggestedType, clearDescription]` matches the SQL parameter positions
- **PASS**

### Regression Testing

#### PROJ-15 (DMS Folder Management)
- [x] GET endpoint: No changes -- still returns all folders
- [x] POST endpoint: No changes -- still creates folders
- [x] DELETE endpoint: No changes -- still deletes folders with parameterized query
- [x] PUT endpoint: Enhanced with CASE/WHEN -- backward compatible (existing partial updates with non-null values work identically through the COALESCE path)
- [x] Frontend: No changes to any component or service file
- **No regression**

#### PROJ-23 (DMS Security Hardening)
- [x] Fix 1 (DELETE SQL parameterization): Unchanged -- still uses `$1`
- [x] Fix 2 (PUT static COALESCE): Extended with CASE/WHEN wrapper but query is still static (no dynamic SQL construction)
- [x] Fix 3 (JWT comments): All four security comments still present
- [x] Fix 4 (GraphQL injection in processor): Different workflow, not affected
- **No regression**

#### PROJ-24 (DMS Operational Improvements)
- [x] Different workflows (scanner, processor, lifecycle) -- not affected by folder API changes
- **No regression**

### Bugs Found

No bugs found. The implementation correctly addresses the original regression (PROJ-23 BUG-1) with a clean, minimal approach.

### Summary
- **Acceptance Criteria:** 8/8 passed
- **Edge Cases:** 7/7 passed
- **Bugs Found:** 0 total
- **Security Audit:** PASS -- no new attack vectors introduced; explicit-null flags are derived server-side and cannot be manipulated by an attacker
- **Regression:** PASS -- no impact on PROJ-15, PROJ-23, or PROJ-24
- **Production Ready:** YES
- **Recommendation:** Deploy. The fix is minimal, surgical, and correct. The CASE/WHEN pattern cleanly resolves the COALESCE ambiguity without introducing dynamic SQL or new security risks. The frontend already sends `null` values correctly -- no client-side changes needed.

## Deployment

**Deployed:** 2026-03-15

**Workflows deployed:**
- `alice-dms-folder-api` — Fix für BUG-1: `JWT+Validate: PUT Folder` (Explicit-Null-Flags) + `PG: Update Folder` (CASE/WHEN statt reinem COALESCE)

**No frontend changes, no DB migrations, no nginx changes required.**
