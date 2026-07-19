# PROJ-67: Zentraler Auth-Fetch-Wrapper

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Implementation Notes
- `frontend/src/services/fetchWithAuth.ts` (new) consolidates `authHeaders()`/`bearer()`/`handleAuthError()` from all six service files (`api.ts`, `dms.ts`, `adminApi.ts`, `mailApi.ts`, `profileApi.ts`, `voiceApi.ts`); old helpers deleted, no orphaned references remain.
- `suppressAuthRedirect` option used by `streamChat()` (SSE) and `profileApi.changePasswordVoluntary()`, both of which re-implement their own explicit 401 handling.
- `voiceApi.ts` WebSocket `?token=` auth intentionally left untouched (only REST calls migrated), per spec.
- Known non-blocking cosmetic issue (BUG-1, Low): on a 401, try/catch-wrapped REST callers may briefly surface a generic "Netzwerkfehler…" message instead of "Session abgelaufen…" before the redirect fires; the redirect + logout themselves are unaffected. See QA Test Results for detail.

## Dependencies
- None (reiner Frontend-Refactor, keine Backend-/API-Vertragsänderung).

## User Stories
- Als Entwickler möchte ich Auth-Header-Erzeugung und 401-Behandlung an einer einzigen Stelle pflegen, statt in sechs Service-Dateien (`api.ts`, `dms.ts`, `adminApi.ts`, `mailApi.ts`, `profileApi.ts`, `voiceApi.ts`) nahezu identischen Code zu duplizieren.
- Als Entwickler möchte ich, dass ein neuer Service (zukünftig) automatisch das korrekte Auth-/401-Verhalten bekommt, indem er den zentralen Wrapper nutzt, statt eine eigene Kopie zu schreiben.
- Als Nutzer soll sich am sichtbaren Verhalten (401 → Logout + Redirect zu `/login`, Ausnahme beim Passwort-ändern-Dialog) durch diesen Refactor nichts ändern.

## Acceptance Criteria
- [ ] Ein zentraler Fetch-Wrapper (z. B. `services/fetchWithAuth.ts`) ersetzt die duplizierten `authHeaders()`/`bearer()`- und `handleAuthError()`-Funktionspaare in `api.ts`, `dms.ts`, `adminApi.ts`, `mailApi.ts`, `profileApi.ts`, `voiceApi.ts`.
- [ ] Der Wrapper hängt automatisch `Authorization: Bearer <token>` (und `Content-Type: application/json`, sofern nicht überschrieben) an; fehlt der Token, wird sofort zu `/login` umgeleitet, bevor ein Request abgesetzt wird (bestehendes Verhalten).
- [ ] Bei `401`-Antwort: Token wird gelöscht (`clearToken()`) und zu `/login` umgeleitet — bestehendes Verhalten, jetzt zentral implementiert.
- [ ] Der Wrapper unterstützt eine Option, das Auto-Redirect-Verhalten bei 401 zu unterdrücken (genutzt vom Passwort-ändern-Aufruf in `profileApi.ts`, wo ein 401 auch "falsches aktuelles Passwort" bedeuten kann); der Aufrufer wertet den Fehler in diesem Fall selbst aus.
- [ ] Der SSE-Chat-Stream (`streamChat()`/`sendMessage()` in `api.ts`) nutzt den Wrapper für Header-Erzeugung und die initiale 401-Prüfung vor Stream-Start; die anschließende `ReadableStream`-Verarbeitung bleibt unverändert in `api.ts`.
- [ ] Alle bisherigen Sonderverhalten bleiben erhalten: `429`-Behandlung in `sendMessage()` (Fehlermeldung statt Logout), Netzwerkfehler-Meldungen, servertypische Fehlermeldungen je Status-Code.
- [ ] Keine funktionale Verhaltensänderung aus Nutzersicht — nur interne Konsolidierung; bestehende Tests/Requests gegen alle sechs Services verhalten sich identisch.
- [ ] `voiceApi.ts`s REST-Aufrufe (Enrollment-Upload/-Liste/-Löschen/-Toggle) nutzen den Wrapper; die WebSocket-Verbindungen (`?token=`-Query-Param in `useVoiceMode1`/`useVoiceMode2`, PROJ-68) sind **nicht** Teil dieser Spec, da sie einen strukturell anderen Auth-Mechanismus verwenden.

## Edge Cases
- Aufruf ohne Token (z. B. Race Condition beim App-Start): Wrapper wirft vor dem Request und leitet weiter — identisch zum heutigen Verhalten in jeder einzelnen Datei.
- Aufrufer, der den `suppressAuthRedirect`-Opt-out nutzt, aber die Antwort selbst nicht auswertet: Wrapper liefert weiterhin die rohe `Response`, kein stiller Fehler-Schluck.
- Gleichzeitige 401-Antworten von mehreren parallelen Requests (z. B. Sidebar lädt Sessions während Settings Mailboxen lädt): mehrfacher `clearToken()`+Redirect-Aufruf ist unschädlich (idempotent), kein Race-Condition-Schutz nötig.
- Bestehender Legacy-Fallback-Pfad (`/api/webhook/v1/chat/completions`, aktiv wenn `NEXT_PUBLIC_STREAM_API_URL` nicht gesetzt ist) muss weiterhin funktionieren.

## Technical Requirements (optional)
- Reines Frontend-Refactoring, kein Backend-Vertrag ändert sich.
- Migration schrittweise pro Service-Datei möglich (kein Big-Bang-Zwang), aber alle sechs Dateien müssen am Ende auf den Wrapper umgestellt sein.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
services/fetchWithAuth.ts (neu)
+-- hängt Authorization: Bearer <token> (+ Content-Type, sofern nicht überschrieben) an
+-- kein Token → sofortiger Redirect zu /login, kein Request wird abgesetzt
+-- 401 → clearToken() + Redirect zu /login (Standardverhalten)
+-- Option suppressAuthRedirect → Aufrufer wertet die Response selbst aus (Passwort-ändern-Fall)

Konsumenten (alle sechs auf den Wrapper umgestellt):
  api.ts (Header-Erzeugung + initiale 401-Prüfung vor SSE-Stream-Start; ReadableStream-Verarbeitung bleibt unverändert dort)
  dms.ts, adminApi.ts, mailApi.ts, profileApi.ts, voiceApi.ts (nur REST-Aufrufe)
```

#### B) Data Model

Keine — reiner Service-Layer-Refactor ohne Datenänderung.

#### C) Tech Decisions

- **Eine Wrapper-Funktion statt Klasse/Context:** Auth-Header-Erzeugung und 401-Behandlung sind zustandsloses Request-Plumbing (Token lesen, Header setzen, Status prüfen) — keine React-Lifecycle-Bindung nötig, gleichermaßen aus Komponenten wie aus reinen Service-Funktionen nutzbar.
- **`suppressAuthRedirect` als expliziter Opt-out-Parameter statt eigener Funktion:** hält einen einzigen Code-Pfad statt einer Beinahe-Duplikat-Variante, während `profileApi.ts`s Passwort-ändern-Aufruf weiterhin selbst entscheidet, ob ein 401 „falsches Passwort" oder „abgelaufene Sitzung" bedeutet.
- **SSE-Sonderfall:** `streamChat()`/`sendMessage()` nutzen den Wrapper nur für Header-Erzeugung und die 401-Prüfung vor Stream-Start — die anschließende `ReadableStream`-Verarbeitung bleibt strukturell in `api.ts`, da sie ein grundsätzlich anderer Code-Pfad ist (langlebiger Stream vs. Request/Response).
- **WebSocket-Auth (`voiceApi.ts`s `?token=`-Query-Param) explizit ausgenommen:** strukturell anderer Auth-Mechanismus (Browser können bei WebSockets keine Custom-Header setzen) — bleibt außerhalb des Wrappers, wie in der Spec vorgegeben.
- **Migration datei-für-Datei möglich, kein Big-Bang:** sechs unabhängige Aufrufstellen, geringes Risiko eines gebrochenen Zwischenzustands.
- **Bestehende Sonderverhalten bleiben erhalten:** 429-Sonderbehandlung in `sendMessage()`, Netzwerkfehler-Meldungen, Legacy-Fallback-Pfad (`/api/webhook/v1/chat/completions`) — der Wrapper ändert nur, wo der Code liegt, nicht was er tut.

#### D) Dependencies

Keine neuen Pakete.

## QA Test Results

**Tested:** 2026-07-19
**Scope:** Static/code-level QA of a pure internal service-layer refactor (no new UI surface). Verified against actual code + production build; behavior compared line-by-line against the pre-refactor versions (`git show HEAD:...`).
**Tester:** QA Engineer (AI)

### Method
- Read `fetchWithAuth.ts` + all six migrated services in full.
- Diffed each service against its pre-refactor `HEAD` version to characterise the exact behavioral delta.
- `npm run build` (Next.js 15.5.12): compiled + type-checked + exported cleanly, no errors/warnings.
- Grepped `frontend/src/` for orphaned references to the deleted `authHeaders()`/`bearer()`/`handleAuthError()`/`handleAuth()` helpers — none remain.
- No unit/e2e test suite exists for this layer: `package.json` has no `test` script and there are zero `*.test.*`/`*.spec.*` files in `frontend/`. Nothing to run and nothing that imports the deleted helpers.

### Acceptance Criteria Status

| # | Criterion | Result |
|---|-----------|--------|
| AC-1 | Central wrapper replaces duplicated `authHeaders()`/`bearer()`/`handleAuthError()` pairs in all six services | PASS — all six import `fetchWithAuth`; grep confirms zero remaining copies of the old helpers |
| AC-2 | Auto-attach `Authorization: Bearer <token>` (+ `Content-Type: application/json` unless overridden / body is FormData); missing token → redirect before request | PASS — FormData skip (`!(init.body instanceof FormData)`) verified against `voiceApi.enrollVoice`; existing `Content-Type` respected (`!headers.has(...)`); no-token path redirects + throws before `fetch()` |
| AC-3 | `401` → `clearToken()` + redirect, centrally | PASS |
| AC-4 | `suppressAuthRedirect` opt-out, used by the voluntary password-change call | PASS — `profileApi.changePasswordVoluntary` passes the flag and does its own 401 body-parse to distinguish "wrong current password" from "expired session"; identical to pre-refactor logic |
| AC-5 | SSE `streamChat()`/`sendMessage()` use wrapper for headers + initial 401 check; `ReadableStream` processing untouched | PASS — `streamChat` uses the wrapper with `suppressAuthRedirect` then handles 401/429 via callbacks; the reader/decoder/SSE-parsing loop is byte-for-byte unchanged |
| AC-6 | All prior special behaviors preserved (429, network-error messages, per-status messages) | PARTIAL — see BUG-1: on a `401`, try/catch-wrapped REST callers no longer surface the specific "Session abgelaufen" text (swallowed into their generic "Netzwerkfehler…" message). 429 handling, per-status messages, and the redirect itself are all preserved |
| AC-7 | No functional behavior change from a user's perspective | PARTIAL — see BUG-1 (LOW, cosmetic). Every other path is behaviorally identical |
| AC-8 | `voiceApi` REST calls use wrapper; WebSocket `?token=` auth untouched | PASS — only the four REST calls were migrated; no WebSocket code touched |

### Edge Cases Status

- No token / app-start race: PASS — identical to old behavior. Note (not a regression): in the try/catch-wrapped callers the no-token throw was already swallowed into "Netzwerkfehler…" in the OLD code too (`authHeaders()` threw *inside* the try), so this is unchanged.
- `suppressAuthRedirect` caller not evaluating the response: PASS — wrapper always returns the raw `Response`, no silent error-swallow.
- Concurrent 401s from parallel requests: PASS — `clearToken()` + `location.href` are idempotent; no shared mutable state in the wrapper.
- Legacy fallback path (`/api/webhook/v1/chat/completions`, active when `NEXT_PUBLIC_STREAM_API_URL` unset): PASS — `sendMessage` still targets it; `Authorization` was always attached to this endpoint pre-refactor, so no header behavior changed.

### Security Audit Results

- No silent 401 pass-through: PASS. `suppressAuthRedirect` is used in exactly two places, and **both** re-implement explicit 401 handling: `streamChat` (`clearToken()` + redirect on `res.status === 401`) and `changePasswordVoluntary` (parses body, then either surfaces "wrong password" or does `clearToken()` + redirect). There is no code path where a 401 escapes without either a redirect or explicit caller handling.
- Authorization-header leakage: PASS. The wrapper attaches `Authorization` to every migrated call — same set of endpoints as before. The legacy fallback already carried the header. No unauthenticated endpoint (`login`/`validate`/`logout` in `auth.ts`) was migrated, so no token is newly attached anywhere.
- Token not weakened: PASS. `getToken()`/`clearToken()` unchanged; token still read from `localStorage` on each call, redirect-before-request preserved.
- No secrets logged, no new env vars, no auth-flow contract change (frontend-only header/redirect plumbing).

**Security verdict: PASS — no regression.**

### Bugs Found

#### BUG-1: On a 401, try/catch-wrapped REST callers surface a generic "Netzwerkfehler…" message instead of "Session abgelaufen…"
- **Severity:** Low
- **Priority:** Fix in next sprint / acceptable to deploy as-is
- **Affected callers:** `api.ts` (`sendMessage`, `fetchSessions`, `fetchSessionMessages`, `renameSessionApi`, `deleteSessionApi`, `fetchAdmin*`), `dms.ts`, `adminApi.ts`, `profileApi.ts` (`getProfile`/`updateProfile`/`updateEmail`). NOT affected: `mailApi.ts` (no try/catch → "Session abgelaufen" still propagates) and `changePasswordVoluntary` (explicit 401 handling).
- **Root cause (verified against `HEAD`):** OLD code called `handleAuthError(res)` *outside* the try/catch, so a 401 threw "Session abgelaufen — bitte erneut anmelden." cleanly. NEW code performs the 401 check *inside* `fetchWithAuth`, which is called *inside* the caller's try/catch — so the "Session abgelaufen" throw is caught and re-thrown as the caller's generic "Netzwerkfehler …" text.
- **Mitigation / why Low:** `fetchWithAuth` runs `clearToken()` + `window.location.href = "/login"` *before* throwing, so the functionally important behavior (logout + full-page redirect) is fully preserved and identical to before. Only the transient error-text differs.
- **Observability (per the implementer's flagged nuance):** Not strictly guaranteed unobservable. `window.location.href` schedules navigation as a *task*; the thrown rejection reaches the caller's `.catch` as a *microtask*, which can `setState` and let React commit a render before the navigation task fires. So a brief "Netzwerkfehler…" flash is possible on session expiry, though typically imperceptible. No caller pattern-matches on the "Session abgelaufen" string (grep confirmed), so nothing downstream breaks logically — this is purely cosmetic.
- **Note:** The primary chat path (`streamChat`, active when `NEXT_PUBLIC_STREAM_API_URL` is set) is unaffected — it handles 401 explicitly with no wrong message.

### Regression Check
- All service files consumed by Chat / Settings / Sidebar / Vision still export the same function signatures; only internals changed. Build (which type-checks all consumers) passed. No import paths broken; `grep -r "authHeaders\|handleAuthError\|bearer" frontend/src/` returns nothing.

### Summary
- **Acceptance Criteria:** 6/8 full PASS, 2 PARTIAL (AC-6, AC-7 — both solely due to the LOW cosmetic BUG-1).
- **Bugs Found:** 1 total (0 critical, 0 high, 0 medium, 1 low).
- **Security:** PASS — no regression.
- **Build:** PASS (clean compile + type-check + export).
- **Tests:** No test suite exists for this layer (stated, not fabricated).
- **Production Ready:** YES (READY).
- **Recommendation:** Deploy. Optionally address BUG-1 later by moving the 401 throw's message concern out of the caller's catch (e.g. have the wrapper still redirect but let callers not wrap the wrapper's own 401 throw), but it is not blocking — the redirect, the load-bearing behavior, is preserved.

## Deployment
_To be added by /deploy_
