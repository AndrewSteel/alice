# PROJ-23: DMS Security Hardening (Folder-API & Processor)

## Status: Deployed
**Created:** 2026-03-15
**Last Updated:** 2026-03-15

## Dependencies
- Requires: PROJ-15 (DMS Folder Management) — Workflow `alice-dms-folder-api` muss deployed sein
- Requires: PROJ-19 (DMS Processor) — Workflow `alice-dms-processor` muss deployed sein

## Overview

Behebung von vier Security-Findings aus den QA-Runden von PROJ-15 und PROJ-19. Alle Fixes betreffen n8n-Workflow-Code-Nodes; kein Frontend-Eingriff notwendig. Die Änderungen sind rein defensiver Natur — die betroffenen Endpunkte funktionieren korrekt, haben aber verwundbare oder fragile Sicherheitsmuster.

| Bug | Workflow | Schweregrad | Beschreibung |
|-----|----------|-------------|--------------|
| PROJ-15 BUG-8 | `alice-dms-folder-api` | **High** | DELETE-Query nutzt `{{ $json.folderId }}` String-Interpolation statt `$1`-Parameter |
| PROJ-15 BUG-4 | `alice-dms-folder-api` | Medium | PUT-Query dynamisch als String aufgebaut, via `$json.sql` durch die Pipeline weitergeleitet |
| PROJ-15 BUG-2 | `alice-dms-folder-api` | Medium | JWT-Rolle per manuellem Base64-Decode ohne Signatur-Verifikation gelesen |
| PROJ-19 BUG-9 | `alice-dms-processor` | Medium | `file_path` in GraphQL-Query ohne vollständiges Escaping (Newlines, Control-Chars) |

## User Stories

- Als Admin möchte ich sicher sein, dass der DELETE-Endpunkt keine SQL-Injection-Angriffsfläche bietet, auch wenn der `parseInt()`-Guard in Zukunft entfernt oder umgangen wird.
- Als Admin möchte ich sicher sein, dass der PUT-Endpunkt kein dynamisch aufgebautes SQL durch die n8n-Pipeline leitet, damit keine Injection-Möglichkeit durch modifizierte Intermediate-Nodes entstehen kann.
- Als Admin möchte ich, dass die Rollen-Prüfung auf dem n8n-eigenen JWT-Validierungs-Mechanismus basiert und nicht auf einem eigenen Base64-Decode, der keine Signatur prüft.
- Als System möchte ich, dass Dateipfade im Weaviate-GraphQL-Query vollständig escapet werden, damit Pfade mit Newlines oder Control-Characters keine Query-Fehler oder Injection erzeugen.

## Acceptance Criteria

### Fix 1: DELETE SQL-Injection (PROJ-15 BUG-8)

- [x] `PG: Delete Folder` Node nutzt `$1`-Platzhalter mit `queryReplacement`-Option — bereits vor diesem Sprint korrekt implementiert
- [x] Kein `{{ ... }}`-Ausdruck im SQL-String
- [x] `folderId` via `queryReplacement` als Integer übergeben
- [x] Verhalten: 204 bei Erfolg, 404 wenn Ordner nicht gefunden

### Fix 2: PUT Dynamic SQL (PROJ-15 BUG-4)

- [x] PUT-Validierungs-Code-Node baut keine SQL-String-Variable mehr auf (`$json.sql` entfernt)
- [x] Code-Node gibt `{ path, suggestedType, description, enabled, folderId }` aus — null für nicht gesendete Felder
- [x] `PG: Update Folder` nutzt statische COALESCE-Query: `UPDATE ... SET path = COALESCE($1, path), ...`
- [x] `queryReplacement` mit Array aller Felder
- [x] Partial Updates weiterhin möglich (COALESCE behält bestehenden Wert wenn null)

### Fix 3: JWT Manual Decode (PROJ-15 BUG-2)

- [x] Alle vier Code-Nodes (GET, POST, PUT, DELETE) haben klarstellenden Kommentar: Webhook-Level JWT-Validierung ist die Sicherheitsgrenze
- [x] Base64-Decode dient nur der Claim-Extraktion (Rolle) — kein Sicherheitsmechanismus
- [x] Ausgewählter Ansatz: Option B (Kommentar) — für admin-only API ausreichend

### Fix 4: GraphQL Injection (PROJ-19 BUG-9)

- [x] `Code: Build Weaviate Query` in `alice-dms-processor`: `className`-Allowlist gegen GraphQL-Injection
- [x] `file_path` vollständiges Escaping: `\`, `"`, `\n`, `\r`, `\t`, `\x00`–`\x1f`
- [x] Leerer `filePath` nach Escaping → `_skip: true` mit Log-Eintrag
- [x] Ungültiger `className` → `_skip: true` mit Log-Eintrag
- [x] Keine Verhaltensänderung für normale Dateipfade

## Edge Cases

- **Fix 1 – `folderId` ist kein Integer**: `parseInt()` im vorangehenden Code-Node liefert `NaN` → Query schlägt fehl mit DB-Fehler → 500 zurückgeben (kein Injection-Risiko)
- **Fix 2 – Alle Felder null (kein Update-Inhalt)**: COALESCE-Variante gibt bestehende Werte zurück unverändert; Response: `{ updated: false }` oder bestehende Werte
- **Fix 2 – Ungültiger `suggested_type`**: Validierung bleibt im Code-Node, bevor der PostgreSQL-Node aufgerufen wird — unverändert
- **Fix 3 – JWT ohne `role`-Claim**: Fallback wie bisher: 403 zurückgeben
- **Fix 4 – Pfad mit `"` oder `\`**: Werden escaped; Query bleibt valide
- **Fix 4 – Pfad leer**: Leerer String nach Escaping → Query-Fehler → Dokument überspringen mit Log-Eintrag

## Technical Requirements

- **Betroffene Workflows**: `alice-dms-folder-api` (PROJ-15), `alice-dms-processor` (PROJ-19)
- **Workflow-Dateien**: `workflows/core/alice-dms-folder-api.json`, `workflows/core/alice-dms-processor.json`
- **Keine DB-Migrationen** erforderlich — nur Workflow-Änderungen
- **Keine nginx-Änderungen** erforderlich
- **n8n Credentials**: unverändert
- **Fix 2 Alternative (DB-basierter Role-Check)**: Erfordert einen zusätzlichen PostgreSQL-Node nach dem Webhook in allen vier Branches — mehr Nodes, aber robuster

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Scope Summary

Four security fixes in two n8n workflows. No frontend changes, no database migrations, no new services. All changes are surgical edits to existing Code nodes and PostgreSQL nodes.

---

### Fix 1: DELETE SQL-Injection (BUG-8) — `alice-dms-folder-api`

**Current state:** The DELETE node (`PG: Delete Folder`) already uses `$1` as a placeholder in the SQL string, with `folderId` bound via the `queryReplacement` option. During architecture review, this node appears to already be parameterized correctly.

**Action:** Verify the current DELETE node against the spec. If `{{ $json.folderId }}` appears anywhere in the SQL string, replace it with `$1`. If the node is already safe, confirm and document — no change needed.

**Affected node:** `PG: Delete Folder` in `alice-dms-folder-api`

---

### Fix 2: PUT Dynamic SQL (BUG-4) — `alice-dms-folder-api`

**Problem:** The PUT validation Code node builds a SQL string dynamically (`'UPDATE ... SET ' + setClauses.join(', ')`) and passes it through the pipeline via `$json.sql`. The downstream PostgreSQL node executes whatever SQL arrives in that field. If any intermediate node were tampered with, it could inject arbitrary SQL.

**Fix design — Static COALESCE query:**

The Code node changes from a "SQL builder" to a "value extractor". It validates input and outputs four field values. The PostgreSQL node uses a hardcoded, static `UPDATE` query with `COALESCE($1, path)` for each column — if a value is `null`, PostgreSQL keeps the existing value unchanged. Partial updates still work exactly as before.

```
Code Node (after fix):
  Role: Validate input, output { role, path, suggested_type, description, enabled, folderId }
  No SQL construction, no $json.sql field

PG Node (after fix):
  Static query: UPDATE ... SET path = COALESCE($1, path), ... WHERE id = $5
  queryReplacement: [path, suggested_type, description, enabled, folderId]
```

**Workflow structure change:** The `$json.sql` → `$json.params` pipeline pattern is removed. The PG node gets a hardcoded query string (no expression interpolation for the query itself).

**Affected nodes:** `JWT+Validate: PUT Folder` (Code node) + `PG: Update Folder` (PostgreSQL node)

---

### Fix 3: JWT Role Extraction Without Signature Verification (BUG-2) — `alice-dms-folder-api`

**Problem:** All four Webhook branches (GET, POST, PUT, DELETE) manually decode the JWT payload via base64 without verifying the HMAC signature. An attacker who knows the token format could craft a fake JWT with `"role": "admin"` and pass the role check.

**Important context:** n8n's Webhook node itself validates JWT signatures at the HTTP layer using the configured `JWT Auth account` credential. A request with an invalid signature never reaches the Code node — it is rejected at the Webhook level.

**Chosen fix — DB-based role lookup (most robust option):**

After the Webhook validates the JWT, a PostgreSQL node reads the user's role directly from `alice.users` using the `sub` claim (user ID) from the token. This makes the role authoritative (comes from the database, not the token) and removes any dependency on the token's payload being trusted.

```
Webhook (JWT validated by n8n)
  ↓
PG: Get User Role  ← new node per branch (or shared via sub-workflow)
  SELECT role FROM alice.users WHERE id = $jwt_sub
  ↓
Code Node (simplified)
  Reads role from DB result, removes manual base64 decode
```

**Workflow structure change:** One new PostgreSQL node added to each of the four branches. The Code nodes are simplified — the base64 decode block is removed.

**Alternative (acceptable if DB node is too many changes):** Add a comment block in each Code node explicitly stating: "n8n's Webhook-level JWT validation is the security boundary. This base64 decode is only for claim extraction, not authentication." This documents intent and makes future audits clear, but does not add defense-in-depth.

The DB-lookup approach is recommended and is what the spec prefers.

**Affected nodes:** `JWT: GET Folders`, `JWT+Validate: POST Folder`, `JWT+Validate: PUT Folder`, `JWT+Validate: DELETE Folder`

---

### Fix 4: GraphQL Injection via `file_path` and `className` (BUG-9) — `alice-dms-processor`

**Problem:** The `Code: Build Weaviate Query` node builds a GraphQL query string by interpolating two unvalidated values:

1. `className` (e.g., "Invoice") — inserted directly into the query structure. No allowlist check. A malformed or manipulated `className` could break out of the `Get { ... }` block and inject arbitrary GraphQL.
2. `filePath` — only `\` and `"` are escaped. Newlines (`\n`), carriage returns (`\r`), tabs (`\t`), and other control characters (ASCII 0x00–0x1F) are not escaped. These can break the string literal in the query or trigger parser errors.

**Fix design:**

```
Step 1 — className allowlist:
  Valid values: ['Invoice', 'BankStatement', 'Document', 'Email', 'SecuritySettlement', 'Contract']
  If className not in list → set _skip: true, log warning, stop processing this document

Step 2 — filePath full escape function:
  Escape: \ → \\, " → \", newline → \n, carriage return → \r, tab → \t,
          all remaining control chars (0x00–0x1f) → \uXXXX
  If result is empty after escaping → set _skip: true, log warning, skip document

Step 3 — Query construction:
  Same as today, but using sanitized className and filePath
```

**No new nodes needed.** The existing `Code: Build Weaviate Query` node is extended in place. The `_skip: true` flag is already used in the processor pipeline for other skip conditions.

**Affected node:** `Code: Build Weaviate Query` in `alice-dms-processor`

---

### Workflow Impact Summary

| Workflow | Nodes Changed | New Nodes | Behavior Change |
|---|---|---|---|
| `alice-dms-folder-api` | DELETE (verify/fix), PUT Code + PG, all 4 JWT Code nodes | 0–4 PG nodes (Fix 3) | None — identical responses |
| `alice-dms-processor` | `Code: Build Weaviate Query` | 0 | Documents with bad paths now skipped instead of error |

### No Changes Needed
- nginx configuration
- PostgreSQL schema / migrations
- Frontend code
- n8n credentials
- Other workflows

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
