# PROJ-63: Backend Sprachcode-Offenheit (alice-auth + alice-chat-stream)

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Implementation Notes
- Language config `{code, displayName_de, displayName_en, llm_instruction}` duplicated in `alice-auth/main.py` and `alice-chat-stream/app/memory.py`, seeded with exactly `de`+`en` (behavior-identical to pre-change).
- `alice-auth`: `PATCH /auth/profile` (line 778) and `POST /auth/admin/users` (line 1084) validate against the config, accept legacy `"deutsch"`/`"englisch"` as aliases, 422 on unknown codes. New public `GET /auth/languages` (`/api/auth/languages` externally via nginx rewrite).
- `alice-chat-stream`: binary `if sprache == "englisch"` branch replaced by config lookup, unknown/missing code falls back to `de`.
- Migration `sql/migrations/063-backend-language-codes.sql` written but NOT yet applied to the live DB — corrected from an earlier `docker exec`-based shell script to match this project's actual deploy pattern (raw `.sql` file, applied from the dev PC via `psql -h database.lan -p 5432 -U alice_user -d alice -f sql/migrations/063-backend-language-codes.sql`, see e.g. `014-chat-storage.sql`/`046-imap-mailboxes.sql`). Needs to be run manually before old word-form values can be considered migrated.
- QA: READY. 2 Low bugs, non-blocking: migration script's summary count line captures psql command-tag noise (cosmetic); spec's line-number references (744/1029) had drifted to actual 778/1084 (docs only).

## Dependencies
- Requires: existing `alice.user_profiles.preferences.sprache`-Feld (JSONB, keine bestehende CHECK-Constraint auf DB-Ebene — Einschränkung liegt aktuell nur im Anwendungscode).
- Required by: PROJ-62 (Frontend i18n) — das Sprache-Dropdown in Mein Profil/`CreateUserDialog` bezieht seine Optionsliste über den neuen Endpunkt aus dieser Spec.
- Required by: PROJ-64 (Voice-Enrollment-Spracherkennung) — `alice-speech-gateway/enrollment.py` muss auf dieselben Sprachcodes umgestellt werden.

## User Stories
- Als Betreiber möchte ich eine neue unterstützte Sprache (Code, Anzeigename, LLM-Instruktionstext) durch einen Config-Eintrag + Redeploy hinzufügen können, ohne Datenbankschema oder API-Verträge zu ändern.
- Als Frontend möchte ich die Liste unterstützter Sprachen über einen API-Endpunkt abrufen können, damit das Sprache-Dropdown nie von der Backend-Validierung abweicht.
- Als Nutzer, dessen Profil bereits `sprache: "deutsch"` oder `"englisch"` enthält, möchte ich, dass mein bestehender Wert nach dem Umstieg auf ISO-Codes ohne mein Zutun weiterhin korrekt funktioniert.
- Als System (alice-chat-stream) möchte ich für jede konfigurierte Sprache eine passende Instruktion an den LLM-Systemprompt anhängen können, statt einer binären Deutsch/Englisch-Fallunterscheidung.

## Acceptance Criteria
- [ ] Eine zentrale, statische Sprachkonfiguration existiert in `alice-auth` und in `alice-chat-stream` (je Container dupliziert): pro Sprache `{code (ISO 639-1), displayName_de, displayName_en, llm_instruction}`.
- [ ] `alice-auth`: `PATCH`/Profil-Update-Endpunkte (`main.py:744`, `main.py:1029`) validieren `sprache` gegen die Codes der aktuellen Konfiguration statt gegen die feste Tupel `("deutsch", "englisch")`; ungültiger Code → weiterhin `422` mit Klartext-Fehlermeldung, die die aktuell gültigen Codes nennt.
- [ ] Neuer Endpunkt `GET /api/auth/languages` liefert die konfigurierte Sprachliste (Code + beide Anzeigenamen) für das Frontend-Dropdown.
- [ ] `alice-chat-stream/memory.py`: Die binäre `if sprache == "englisch"`-Verzweigung (Zeile 178) ist durch ein Lookup über die Sprachkonfiguration ersetzt; unbekannter/fehlender Code fällt auf Deutsch zurück (`de`, konsistent mit PRD-Constraint "Sprache: Primär Deutsch").
- [ ] Bestehende `preferences.sprache`-Werte in `alice.user_profiles` werden per einmaligem Migrationsskript von `"deutsch"`/`"englisch"` auf `"de"`/`"en"` umgestellt.
- [ ] `CreateUserDialog` (Admin legt neuen Nutzer an) und `ProfilForm` beziehen ihre Dropdown-Optionen über `GET /api/auth/languages` statt eines hartcodierten Union-Typs (Umsetzung erfolgt im Rahmen von PROJ-62/`/frontend`, hier nur der Endpunkt-Vertrag).
- [ ] Start des Frontends/Backends mit **nur** Deutsch+Englisch konfiguriert verhält sich exakt wie heute (keine Verhaltensänderung ohne Config-Erweiterung).

## Edge Cases
- Sprachcode wird in `alice-auth`, aber (versehentlich) nicht in `alice-chat-stream` konfiguriert (Container-Update nicht synchron ausgerollt): LLM-Prompt-Logik fällt für diesen Code auf Deutsch zurück statt zu fehlern.
- Migrationsskript läuft auf einer Datenbank, in der `sprache` bereits `null` oder ein unbekannter Wert ist (z. B. manuell gesetzt): Skript überschreibt nur exakte Treffer auf `"deutsch"`/`"englisch"`, lässt alles andere unverändert, loggt übersprungene Zeilen.
- Alter Client (gecachtes Frontend-Bundle vor PROJ-62-Deployment) sendet noch `"deutsch"`/`"englisch"` an die Profil-API nach der Migration: Validierung akzeptiert beide alten Wortwerte übergangsweise als Alias für `"de"`/`"en"`, bis der Frontend-Rollout abgeschlossen ist.
- `GET /api/auth/languages` wird von einem nicht eingeloggten Client aufgerufen (Login-Screen-Sprachwahl gibt es laut PROJ-62 nicht, dort zählt nur Browser-Sprache) — Endpunkt ist dennoch öffentlich erreichbar, da er keine Nutzerdaten enthält.
- Sprachkonfiguration enthält einen Code ohne vollständige Übersetzung in PROJ-62 (UI-Text fehlt): kein Blocker für diese Spec, greift der i18n-Fallback aus PROJ-62.

## Technical Requirements (optional)
- Kein neues DB-Schema/keine neue Tabelle — Sprachkonfiguration bleibt Anwendungscode (Python-Dict/JSON-Datei je Container), passend zum Solo-Hobby-Projekt-Rahmen.
- Migrationsskript nach bestehendem Muster (`scripts/proj55-add-thumbnail-path.sh`) als `scripts/proj63-migrate-sprache-codes.sh`.
- `GET /api/auth/languages` erfordert keine Authentifizierung (analog zu anderen öffentlichen Metadaten-Endpunkten), liefert aber keine nutzerbezogenen Daten.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Data Flow

```
alice-auth (Profil-Update / Nutzer-Anlage, main.py)
  → validiert `sprache` gegen die zentrale Sprachkonfiguration statt des festen Tupels ("deutsch","englisch")
  → neuer Endpunkt GET /api/auth/languages liefert die konfigurierte Liste (Code + beide Anzeigenamen) ans Frontend

alice-chat-stream (memory.py, Systemprompt-Aufbau)
  → schlägt den gespeicherten Sprachcode in seiner eigenen Kopie derselben Konfiguration nach
  → hängt die passende llm_instruction an den Systemprompt an, statt der heutigen binären if sprache == "englisch"-Verzweigung
  → unbekannter/fehlender Code → Fallback Deutsch (konsistent mit PRD-Vorgabe „Sprache: primär Deutsch")

Einmaliges Migrationsskript
  → schreibt bestehende preferences.sprache-Werte "deutsch"/"englisch" auf "de"/"en" um
  → überspringt alles andere unverändert, loggt übersprungene Zeilen
```

#### B) Data Model

Sprachkonfigurations-Eintrag (pro Sprache): Code (ISO 639-1), Anzeigename Deutsch, Anzeigename Englisch, LLM-Instruktionstext. Liegt als statische Anwendungskonfiguration (Python-Dict/JSON-Datei) **dupliziert je Container** — kein neues DB-Schema, keine neue Tabelle (explizite Vorgabe der Spec). Einzige DB-Auswirkung: bestehende Werte in `alice.user_profiles.preferences.sprache` werden per Migrationsskript von Wortform auf ISO-Code umgestellt.

#### C) Tech Decisions

- **Konfiguration dupliziert statt zentraler Config-Service:** Jeder Container (alice-auth, alice-chat-stream, später alice-speech-gateway in PROJ-64) hält seine eigene Kopie derselben statischen Konfiguration, statt sie zur Laufzeit von einem gemeinsamen Dienst abzurufen. Passt zum bestehenden Solo-Hobby-Projekt-Rahmen (kein Service-Mesh/Config-Server) und vermeidet eine neue Laufzeit-Abhängigkeit zwischen `alice-chat-stream` und `alice-auth` für einen Wert, der sich nur beim Deploy ändert. Bewusst akzeptierter Trade-off (siehe Edge Cases der Spec): Config-Drift bei nicht synchronem Container-Update — abgefedert durch Fallback auf Deutsch statt eines Fehlers.
- **`GET /api/auth/languages` ist öffentlich/unauthentifiziert:** gleiche Kategorie wie andere reine Metadaten-Endpunkte, vermeidet das Henne-Ei-Problem „Sprachliste laden, bevor der Nutzer eingeloggt ist" (relevant für PROJ-62s Login-Screen-Erkennung und `CreateUserDialog`).
- **Alias-Schicht für alte Wortwerte** (`"deutsch"`/`"englisch"` übergangsweise weiterhin akzeptiert) ist eine Rollout-Absicherung für gecachte Frontend-Bundles, keine Dauerlösung — sollte nach vollständigem PROJ-62-Rollout in einem späteren Cleanup entfernt werden.
- **Validierung bleibt Anwendungscode**, keine DB-Constraint (heute schon so) — konsistent mit der bestehenden Architektur, in der `sprache` ein JSONB-Feld ohne CHECK-Constraint ist.

#### D) Dependencies

Keine neuen Pakete — nutzt den bestehenden Python/FastAPI-Stack in `alice-auth` und `alice-chat-stream`. Migrationsskript nach bestehendem Muster (`scripts/proj63-migrate-sprache-codes.sh`, analog zu `scripts/proj55-add-thumbnail-path.sh`).

## QA Test Results

**Tested:** 2026-07-19
**Scope:** Backend code audit (static). Runtime deps (bcrypt, jwt, psycopg2, asyncpg, httpx) are not installed in this environment, so no live server was started. Pure language logic was extracted and unit-tested in isolation; parse-checks (`py_compile`, `bash -n`) run against the real files; nginx routing verified against config.
**Tester:** QA Engineer (AI, autonomous background session)

### What could / could not be executed
- **Executed:** `python3 -m py_compile` on both changed Python files (both parse OK); `bash -n` on the migration script (syntax OK); isolated unit test of `_normalize_language` / `_invalid_language_detail` / `_llm_instruction_for` copied verbatim from the source (all 26 assertions pass); nginx config inspection; git history diff of the pre-PROJ-63 `build_system_prompt` branch.
- **Could NOT execute:** live HTTP calls (FastAPI app can't boot without bcrypt/jwt/psycopg2), the migration against a real DB (explicitly out of scope), and the full `main.py`/`memory.py` import path (external deps missing) — mitigated by extracting and testing the pure functions standalone.

### Acceptance Criteria Status

#### AC-1: Central static language config in both services `{code, displayName_de, displayName_en, llm_instruction}` — PASS
- [x] `alice-auth/main.py:141-154` defines `LANGUAGES` with all four keys per entry (de, en).
- [x] `alice-chat-stream/app/memory.py:40-53` defines an identical `LANGUAGES` list (duplicated per container, as designed).
- [x] Both carry `LANGUAGE_ALIASES = {"deutsch":"de","englisch":"en"}`.

#### AC-2: `PATCH /auth/profile` + create-user validate `sprache` against configured codes, 422 naming valid codes — PASS
- [x] `PATCH /auth/profile` (handler at `main.py:778`; validation at 818-822) calls `_normalize_language`, raises `422` with `_invalid_language_detail()` → `"Ungültige Sprache. Erlaubt: de, en"`, and stores the normalized code.
- [x] `POST /auth/admin/users` create-user (handler at `main.py:1084`; validation at 1106-1110) does the same.
- [x] Hardcoded `("deutsch","englisch")` tuple is gone from both handlers.
- Note: spec header cited `main.py:744` / `main.py:1029`; actual current lines are `778` / `1084` (code grew since the spec was written). Validation sits in the correct handlers, is present in BOTH, and is not applied to any wrong endpoint. Documentation nit only — see BUG-2.

#### AC-3: `GET /api/auth/languages` public, returns code + both display names, no user data — PASS
- [x] `main.py:443-460` — no `_require_auth`/`_require_admin`, no DB access, returns only static config (`code`, `displayName_de`, `displayName_en`). `llm_instruction` is intentionally NOT exposed.
- [x] nginx `location ^~ /api/auth/` with `rewrite ^/api(.*)$ $1 break;` → forwards `/auth/languages` to `alice-auth:8002`; CORS `Allow-Methods` includes GET. Reachable externally as `GET /api/auth/languages`.

#### AC-4: `memory.py` binary branch replaced by lookup; unknown/missing → `de` — PASS
- [x] Old `if sprache == "englisch": ... else: ...` (git HEAD:memory.py) is fully removed; replaced by `_llm_instruction_for(sprache)` at line 218.
- [x] Isolated unit test: `de`/`deutsch`→German, `en`/`englisch`→English, `None`/`""`/`fr`/`xx`→German fallback. All pass.

#### AC-5: One-time migration script `"deutsch"/"englisch"` → `"de"/"en"` — PASS (one low cosmetic reporting bug — BUG-1)
- [x] `UPDATE ... WHERE preferences->>'sprache' = 'deutsch'` → `"de"`, and `'englisch'` → `"en"`; wrapped in a single `BEGIN`/`COMMIT` with `ON_ERROR_STOP=1`.
- [x] Only exact word-form matches are touched; `null`, already-migrated codes, and unknown/manual values are left untouched and pre-listed as skipped (lines 46-53).

#### AC-6: Frontend dropdown wiring via the endpoint — N/A (out of scope)
- [x] Spec explicitly defers `CreateUserDialog`/`ProfilForm` to PROJ-62/`/frontend`; only the endpoint contract is in scope here, and it is delivered.

#### AC-7: With only de+en configured, behavior identical to pre-PROJ-63 — PASS
- [x] git diff confirms the new `llm_instruction` strings are byte-identical to the old binary branch (`"Reply in English."` / `"Antworte immer auf Deutsch. Sei präzise und hilfreich."`).
- [x] Validation still accepts exactly the same effective inputs (plus legacy aliases). No new required fields, no signature changes.

### Edge Cases Status
- [x] **EC-1** Code in auth but not chat-stream (config drift): unknown code → German fallback, not an error. Verified in unit test.
- [x] **EC-2** Migration on `null`/unknown `sprache`: only exact `deutsch`/`englisch` matches updated; everything else untouched and logged as skipped.
- [x] **EC-3** Stale client sends `deutsch`/`englisch` post-migration: accepted via alias, normalized to `de`/`en`. Verified.
- [x] **EC-4** Unauthenticated `GET /api/auth/languages`: public, no PII. Verified.
- [x] **EC-5** Configured code lacking a PROJ-62 UI translation: out of scope (handled by i18n fallback in PROJ-62). N/A.

### Security Audit Results
- [x] **New endpoint auth:** `GET /auth/languages` requires no auth by design (spec-approved); exposes only static metadata, no user/PII data, and withholds `llm_instruction`.
- [x] **Error-message leakage:** 422 detail reveals only the valid codes (`de, en`) — nothing sensitive.
- [x] **No auth weakening in touched handlers:** `PATCH /auth/profile` still calls `_check_profile_rate_limit` + `_require_auth` (lines 789-790); create-user still calls `_check_admin_rate_limit` + `_require_admin` (1095-1096). The PROJ-63 diff only added sprache normalization inside existing validation blocks.
- [x] **`user_id` sourcing:** unchanged — always from the JWT payload, never from request body.
- [x] **Migration SQL-injection surface:** none — all SQL uses static string literals; `CONTAINER`/`DB_USER`/`DB_NAME` are shell args passed to `docker exec`/`psql -U -d`, never interpolated into SQL text.
- [x] **Migration destructiveness/transaction:** non-destructive (`jsonb_set` on the single `{sprache}` key), single `BEGIN`/`COMMIT`, `ON_ERROR_STOP=1`. Does NOT run automatically — only on explicit manual invocation. Not run during this QA.
- [x] **nginx:** the public `/languages` endpoint inherits the pre-existing `auth_limit` rate limit (burst 3) — acceptable for a metadata endpoint.

### Bugs Found

#### BUG-1: Migration success-count line captures psql command tags, not just the number
- **Severity:** Low (cosmetic — reporting only; migration itself is correct)
- **Location:** `scripts/proj63-migrate-sprache-codes.sh:57-82`
- **Steps to Reproduce:**
  1. Run the migration heredoc (`psql_run -t -A <<'SQL' ... SQL`), which executes `BEGIN; UPDATE; UPDATE; SELECT count(*); COMMIT;`.
  2. Expected: `migrated` holds just the count, so the final line reads e.g. `Profiles now on ISO codes (de/en): 5`.
  3. Actual: psql (no `-q`) also emits command tags (`BEGIN`, `UPDATE 2`, `UPDATE 1`, `COMMIT`) to stdout, so `migrated` becomes a multi-line blob and the summary line is noisy (`... : BEGIN\nUPDATE 2\n...\n5\nCOMMIT`).
- **Priority:** Nice to have (add `-q`, or `SELECT` the count in a separate `psql_run` call after `COMMIT`). Does not affect correctness of the migration.

#### BUG-2: Spec line-number references are stale (`main.py:744`/`1029` vs actual `778`/`1084`)
- **Severity:** Low (documentation only)
- **Location:** spec AC-2 / Tech Design vs `main.py`
- **Impact:** None on behavior — validation is present and correct in both intended handlers. Flagged so future readers don't chase the wrong lines.
- **Priority:** Nice to have.

**Observation (not a bug):** `memory.py:191` still defaults to the word-form `prefs.get("sprache") or "deutsch"` rather than `"de"`. Harmless — `_llm_instruction_for` resolves `"deutsch"` via the alias to `de`. Could be tidied to `"de"` in a later cleanup alongside alias removal.

### Summary
- **Acceptance Criteria:** 7/7 passed (AC-6 N/A by scope).
- **Edge Cases:** 5/5 handled (EC-5 N/A by scope).
- **Bugs Found:** 2 total (0 critical, 0 high, 0 medium, 2 low — both cosmetic/documentation).
- **Security:** Pass — public endpoint is metadata-only, no auth weakened, migration has no injection/destructive risk and does not auto-run.
- **Production Ready:** YES
- **Recommendation:** READY — deploy. Optionally address BUG-1 (cosmetic migration output) before running the migration, and BUG-2 (spec line refs) at leisure. Neither blocks deployment.

## Deployment
_To be added by /deploy_
