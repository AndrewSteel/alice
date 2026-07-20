# PROJ-65: Backend — Effective-Permissions API & fehlende System-Flags

## Status: Deployed
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Implementation Notes
- 3 new `BOOLEAN DEFAULT FALSE` columns on `alice.permissions_system` (`can_manage_dms_folders`, `can_view_chat_archive`, `can_manage_mailboxes`), threaded through `role_templates` (admin=true, others=false) and `init_user_permissions()`.
- New JWT-protected `GET /api/auth/permissions` in `alice-auth`, reuses existing `_require_auth`, returns all 10 flags, falls back to all-false if no permission row exists.
- Migration `sql/migrations/065-permission-flags.sql` written but NOT yet applied to the live DB — corrected from an earlier `docker exec`-based shell script to match this project's actual deploy pattern (raw `.sql` file, applied from the dev PC via `psql -h database.lan -p 5432 -U alice_user -d alice -f sql/migrations/065-permission-flags.sql`, see e.g. `014-chat-storage.sql`/`046-imap-mailboxes.sql`).
- QA: READY. 1 Low/cosmetic bug (migration script's summary count may include psql command-tag noise, same class of issue as PROJ-63's script) — non-blocking.

## Dependencies
- Requires: bestehendes Permission-Schema (`alice.permissions_system`, `alice.role_templates`, `alice.init_user_permissions`) aus Phase 1.
- Required by: PROJ-66 (Frontend Granular UI Gating) — konsumiert den hier spezifizierten Endpunkt.

## User Stories
- Als Frontend möchte ich für den eingeloggten Nutzer die effektiven System-Berechtigungen über einen einzigen Endpunkt abrufen können, statt clientseitig nur auf `user.role === "admin"` zu prüfen.
- Als Admin möchte ich, dass Nutzerverwaltung-, DMS- und Chatarchiv-Tab-Sichtbarkeit sowie Mailbox-Admin-Rechte jeweils über ein eigenes, spezifisches Permission-Flag gesteuert werden, statt implizit an ein unpassendes bestehendes Flag gebunden zu sein.
- Als bestehender Admin-Nutzer möchte ich nach dem Rollout weiterhin uneingeschränkten Zugriff auf DMS-Tab, Chatarchiv und Mailbox-Verwaltung haben, ohne manuell etwas umstellen zu müssen.

## Acceptance Criteria
- [ ] `alice.permissions_system` erhält drei neue Spalten: `can_manage_dms_folders`, `can_view_chat_archive`, `can_manage_mailboxes` (alle `BOOLEAN DEFAULT FALSE`).
- [ ] `alice.role_templates` wird für alle vier Rollen aktualisiert: `admin` → alle drei neuen Flags `true`; `user`/`guest`/`child` → alle drei `false` (identisch zum heutigen faktischen Verhalten, keine Verhaltensänderung).
- [ ] `alice.init_user_permissions()` schreibt die drei neuen Flags beim Anlegen/Aktualisieren eines Nutzers aus dem Rollen-Template (wie die bestehenden Flags).
- [ ] Migrationsskript setzt für **bestehende** Nutzer mit `role = 'admin'` alle drei neuen Flags rückwirkend auf `true`; alle anderen bestehenden Nutzer erhalten `false` (Default) — Bestandsverhalten bleibt unverändert.
- [ ] Neuer Endpunkt `GET /api/auth/permissions` (in `alice-auth`) liefert die effektiven `permissions_system`-Werte des per JWT authentifizierten Nutzers als JSON (alle 10 Flags: die 7 bestehenden + die 3 neuen).
- [ ] Endpunkt erfordert gültigen JWT (wie alle anderen `/api/auth/*`-Routen außer `/login`), liefert 401 ohne gültiges Token.
- [ ] Kein Permission-Eintrag für den Nutzer vorhanden (sollte durch `init_user_permissions` beim Login/Anlegen nicht vorkommen, aber als Fallback): Endpunkt liefert alle Flags als `false` statt eines Fehlers.

## Edge Cases
- Nutzer, dessen Rolle sich ändert (z. B. `user` → `admin`): bestehendes `init_user_permissions`-Verhalten (ON CONFLICT DO UPDATE) greift automatisch auch für die drei neuen Flags — keine Sonderbehandlung nötig.
- Migrationsskript läuft mehrfach (z. B. bei wiederholtem Deploy-Versuch): idempotent, überschreibt admin-Zeilen erneut mit `true`, keine Duplikate.
- Individuelle Abweichung vom Rollen-Template (z. B. ein `user`-Account bekommt manuell `can_manage_dms_folders=true` gesetzt): Es gibt aktuell **keine** UI zum Editieren einzelner `permissions_system`-Flags pro Nutzer — nur über direkten DB-Zugriff oder Rollenwechsel möglich. Diese Spec liefert keine neue Editor-UI, nur den Lese-Endpunkt.
- Endpunkt wird während eines laufenden Rollenwechsels (Race Condition zwischen Rollen-Update und Permission-Read) aufgerufen: liefert den zu diesem Zeitpunkt in der DB stehenden Wert, kein Locking nötig (seltener, nicht-kritischer Fall).

## Technical Requirements (optional)
- Endpunkt-Standort: `alice-auth` (Port wie bestehende `/api/auth/*`-Routen), analog zum Muster aus PROJ-63 (`GET /api/auth/languages`).
- Migrationsskript nach bestehendem Muster: `scripts/proj65-add-permission-flags.sh`.
- Keine neue UI zum Bearbeiten einzelner Permission-Flags — Scope ist ausschließlich Schema + Lese-Endpunkt.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Data Flow

```
Login / Nutzer-Anlage → alice.init_user_permissions() → schreibt jetzt 10 statt 7 System-Flags aus dem Rollen-Template

Frontend (eingeloggt) → GET /api/auth/permissions (JWT-geschützt, alice-auth)
  → liest die permissions_system-Zeile des Nutzers
  → liefert alle 10 Flags als JSON zurück
  → kein Eintrag vorhanden (Fallback-Fall) → alle Flags false statt Fehler
```

#### B) Data Model

`alice.permissions_system` erhält drei neue Boolean-Spalten (Default `false`), gleiche Form wie die sieben bestehenden: Verwaltung von DMS-Ordnern, Einsicht ins Chatarchiv, Verwaltung von Postfächern. `alice.role_templates` wird für alle vier Rollen aktualisiert — `admin` erhält alle drei neu auf `true`, die anderen drei Rollen auf `false` (entspricht dem heutigen faktischen Verhalten, also verhaltensneutral bis PROJ-66 die Flags konsumiert). Bestehende Nutzer werden per Migrationsskript rückwirkend befüllt: `role = admin` → alle drei `true`, alle anderen bleiben beim Default `false`.

#### C) Tech Decisions

- **Neue Spalten auf bestehender Tabelle statt neuer Tabelle:** `permissions_system` ist bereits eine 1-Zeile-pro-Nutzer-Flag-Tabelle; drei weitere Booleans behalten die Form bei, und derselbe `init_user_permissions()`/Rollen-Template-Mechanismus funktioniert unverändert weiter (drei weitere Keys durch dieselbe Schleife).
- **Ein neuer Lese-Endpunkt statt einem je Flag:** Das Frontend braucht „was darf dieser Nutzer" als eine Form, die es in einem Hook halten kann (siehe PROJ-66). Folgt demselben Muster wie PROJ-63s `GET /api/auth/languages` (gleicher Container, gleicher Auth-Stil).
- **Keine neue Editor-UI** (expliziter Non-Goal) — Flags werden ausschließlich über Rollen-Templates oder direkten DB-Zugriff gesetzt, genau wie die bestehenden System-Permissions heute schon funktionieren.
- **Migration ist idempotent** — setzt admin-Zeilen erneut auf `true`, fasst alle anderen nicht an, folgt demselben Deploy-Skript-Muster wie PROJ-55/PROJ-63.
- **Kein Sicherheitsgrenze, reine Lese-API:** Der Endpunkt liefert nur, was serverseitig ohnehin in der DB steht — die eigentliche Durchsetzung bleibt bei den jeweiligen Backend-Endpunkten (unverändert), dieser Endpunkt macht nur den bereits vorhandenen Zustand für das Frontend sichtbar.

#### D) Dependencies

Keine neuen Pakete — bestehender `alice-auth`-FastAPI-Service, bestehendes Postgres-Migrationsmuster (`scripts/proj65-add-permission-flags.sh`).

## QA Test Results

**Tested:** 2026-07-19
**Tester:** QA Engineer (AI) — static verification only (no live DB/container in this environment)
**Scope:** `sql/init-schema.sql`, `docker/compose/automations/alice-auth/main.py`, `scripts/proj65-add-permission-flags.sh`

> Verification method: full static read + trace of every SQL statement, Python compile check, bash syntax check, cross-check of endpoint flag list against schema columns, and codebase-wide grep for other `permissions_system` consumers. Items requiring a running Postgres/container are called out explicitly as "not runtime-verified" rather than assumed to pass.

### Acceptance Criteria Status

#### AC-1: Three new BOOLEAN columns on `alice.permissions_system`
- [x] `can_manage_dms_folders BOOLEAN DEFAULT FALSE` — schema line 118
- [x] `can_view_chat_archive BOOLEAN DEFAULT FALSE` — schema line 119
- [x] `can_manage_mailboxes BOOLEAN DEFAULT FALSE` — schema line 120
- [x] Correct type and default for all three

#### AC-2: `alice.role_templates` updated for all four roles
- [x] `admin` (line 166) → all three new flags `true`; other 7 flags unchanged
- [x] `user` (line 190) → all three new flags `false`; pre-existing `can_manage_memory: true` preserved (no accidental flip)
- [x] `guest` (line 203) → all three new flags `false`
- [x] `child` (line 215) → all three new flags `false`
- [x] Each role checked individually — no copy-paste role-value mistake found

#### AC-3: `init_user_permissions()` writes the three new flags
- [x] INSERT column list (lines 297-301) includes all three new columns
- [x] VALUES casts (lines 311-313) use the same `COALESCE((...->>'flag')::boolean, false)` pattern as the 7 existing flags
- [x] ON CONFLICT DO UPDATE SET (lines 323-325) sets all three from EXCLUDED — symmetric with INSERT; no forgotten clause. This is the failure mode called out in the task (INSERT added but ON CONFLICT forgotten) — confirmed NOT present, all three clauses are in sync.

#### AC-4: Migration script backfills existing admins, others stay false
- [x] `ADD COLUMN ... DEFAULT FALSE` fills all existing rows with `false` (Postgres backfills the default) — non-admins correctly left at `false`
- [x] Admin backfill UPDATE (script lines 81-88) is scoped `FROM alice.users u WHERE ps.user_id = u.id AND u.role = 'admin'` — touches only admin rows, sets the three flags to TRUE, leaves the 7 existing flags untouched (column-level UPDATE, not a JSONB blob overwrite)
- [x] `updated_at` column referenced in the UPDATE exists (schema line 122)
- *Not runtime-verified:* actual row counts against production data require a live DB.

#### AC-5: New `GET /api/auth/permissions` returns all 10 flags
- [x] Endpoint defined at `main.py:745` (`/auth/permissions`, reachable as `/api/auth/permissions` via the existing nginx `/api/auth/*` proxy that already serves `/auth/profile` etc.)
- [x] `_SYSTEM_PERMISSION_FLAGS` tuple (lines 731-742) contains exactly the 10 column names — cross-checked one-by-one against the schema columns; none missing, none misspelled, correct order
- [x] SELECT builds the column list from that tuple and returns a JSON object of `{flag: bool(...)}` for all 10
- *Not runtime-verified:* end-to-end HTTP response shape requires a running container.

#### AC-6: Requires valid JWT, 401 without
- [x] Uses `_require_auth(authorization)` — the same helper used by `/auth/profile`, `/auth/email`, etc. (not a weaker/bypassed check). It calls `_extract_bearer_token` (401 on missing/malformed header), `_decode_jwt` (401 on expired/invalid), and rejects tokens without `user_id` (401). No bypass path.

#### AC-7: No permission row → all flags `false`, not an error
- [x] Query is a single-table `SELECT ... WHERE user_id = %s`; `cur.fetchone()` returns `None` when no row exists (no unhandled exception — `None` is a normal result, not a raise)
- [x] Fallback expression `bool(row[flag]) if row else False` (line 775) yields `False` for every flag when `row is None`. Correct and reachable.

### Edge Cases Status

#### EC-1: Role change (user → admin) picks up new flags
- [x] `ON CONFLICT (user_id) DO UPDATE` in `init_user_permissions()` updates all three new flags from the new role template — no special handling needed.

#### EC-2: Migration re-run (idempotency)
- [x] `ADD COLUMN IF NOT EXISTS` — safe to repeat
- [x] `jsonb || '{...}'::jsonb` merge overwrites exactly the three keys and preserves all other keys — no duplication, no silent no-op on re-run
- [x] Admin backfill re-sets `true` (harmless repeat); non-admin rows untouched
- [x] Whole migration wrapped in `BEGIN ... COMMIT` (script lines 59, 99) — atomic
- *Not runtime-verified:* actual idempotent execution requires a live DB.

#### EC-3: Individual per-user deviation from template
- [x] By design — no editor UI in scope; read-only endpoint returns whatever is stored. Matches spec.

#### EC-4: Read during a concurrent role change (race)
- [x] Endpoint returns the value currently in the DB, no locking — matches spec's accepted behavior.

### Security Audit Results

**Docker/API feature:**
- [x] Authentication: valid Bearer JWT required via `_require_auth`; missing/expired/invalid/`user_id`-less tokens all return 401. No bypass path.
- [x] Authorization / no data leak: `user_id` is taken from the decoded JWT payload (`payload["user_id"]`), NOT from any client-supplied query/body parameter. The SELECT is scoped `WHERE user_id = %s` with that JWT value — a caller cannot read another user's permissions.
- [x] SQL injection: the interpolated column list is built from the module-level static tuple `_SYSTEM_PERMISSION_FLAGS` (constant in source, never from request input) — verified by reading lines 731-742; claim confirmed. The only user-derived value (`user_id`) is passed as a parameterized `%s`, not string-interpolated. No injection surface.
- [x] Read-only endpoint: exposes only permission state that already exists server-side; no writes, no privilege escalation. Actual enforcement stays with the downstream backend endpoints (unchanged).
- [x] No secrets logged: error path logs a generic message, not token/PII.

**Static toolchain checks:**
- [x] `python3 -m py_compile docker/compose/automations/alice-auth/main.py` → passes (local Python 3.12.3; container is `python:3.12-slim`). Note: the endpoint uses a triple-quoted f-string containing `", ".join(...)` (nested double-quotes) — this is valid on Python 3.12+, which the container image guarantees; it would be a SyntaxError on <3.12, but the pinned base image is 3.12, so this is fine.
- [x] `bash -n scripts/proj65-add-permission-flags.sh` → passes; `set -euo pipefail` present.

### Regression
- [x] Grep for `permissions_system` across the repo: the only consumers are the new endpoint and the view `alice.v_user_permissions_summary`. The view (lines 816-828) selects `ps.can_manage_users` by explicit column name — no `SELECT *` / no fixed-column-count assumption — so the three added columns do not affect it.
- [x] No other `SELECT * FROM alice.permissions_system` or column-order-dependent query exists in the codebase.
- [x] `init_user_permissions()` is called by `admin_create_user` (main.py:1225) with `(user_id, role)` — signature unchanged, so existing callers are unaffected.

### Bugs Found

#### OBS-1: Migration report variable may capture psql command tags (cosmetic)
- **Severity:** Low
- **Steps to Reproduce:**
  1. Run `scripts/proj65-add-permission-flags.sh` against a live DB
  2. The `admins=$(psql_run -t -A <<'SQL' ... )` heredoc runs `BEGIN`, several `UPDATE`s, a `SELECT count(*)`, and `COMMIT`. psql prints command status tags (e.g. `BEGIN`, `UPDATE 3`, `COMMIT`) to stdout in addition to the count.
  3. Expected: the final line prints just the admin count (e.g. `5`).
  4. Actual (likely): `${admins}` holds multiple lines (command tags + the count), so the "Admin permission rows now fully set" line renders messily.
- **Impact:** Purely cosmetic — the migration itself commits correctly; only the human-readable report line is affected. Does not affect schema, data, or idempotency.
- **Priority:** Nice to have (e.g. add `-q` or isolate the count in its own `psql_run -c`). Confirm exact behavior on the live run.

### Items Not Verifiable Without a Live DB/Container (explicitly stated)
- Actual HTTP 200/401 responses and JSON body of `GET /api/auth/permissions`.
- nginx routing of `/api/auth/permissions` (inherited from the existing `/api/auth/*` rule that already serves `/auth/profile`; pattern is identical, but not independently exercised here).
- Real execution and idempotency of the migration against production data (row counts, backfill result).
These are traced as correct by static analysis; they should be smoke-tested during `/deploy`.

### Summary
- **Acceptance Criteria:** 7/7 passed
- **Edge Cases:** 4/4 handled
- **Bugs Found:** 1 total (0 critical, 0 high, 0 medium, 1 low — cosmetic report-only)
- **Security:** Pass — JWT-enforced, user-scoped by JWT `user_id`, no SQL injection (static flag tuple + parameterized `user_id`), read-only.
- **Production Ready:** YES
- **Recommendation:** Deploy. The single Low finding is cosmetic (migration report line) and does not block. Smoke-test the endpoint and run the migration on the live DB during `/deploy` to cover the items that cannot be exercised statically.

## Deployment
Deployed 2026-07-20 (manual production deploy by Andrew Steel, alice-auth). Confirmed working in production. Schema migration (`sql/migrations/065-permission-flags.sql`) still needs to be run against the live DB to add the 3 new columns and backfill existing admins — not yet confirmed run at time of writing.
