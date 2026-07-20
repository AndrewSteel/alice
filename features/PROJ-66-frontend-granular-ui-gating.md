# PROJ-66: Frontend — Granulares Rollen-Gating in Settings

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-20

## Implementation Notes
- New `services/permissions.ts` + `hooks/usePermissions.ts`: fetches `GET /api/auth/permissions` once per `SettingsPage` mount (not global app start, not per tab-switch), fail-open to `role === "admin"` on fetch failure.
- `SettingsPage.tsx`: tabs now controlled, gated via `can(flag)` — Nutzerverwaltung→`can_manage_users`, DMS→`can_manage_dms_folders`, Chatarchiv→`can_view_chat_archive`; resets to `mein-profil` if the active tab becomes unpermitted after a user switch.
- `MailboxSection.tsx`: takes a `canManageMailboxes` prop, all 4 prior role checks replaced; `isOwner` logic unchanged.
- `UserTable.tsx` VoiceCell and `MeinProfilSection.tsx` `canEnrollVoice` deliberately left on `role === "admin"` (documented bootstrap exception). Stimmprofile tab also stays on `isAdmin` — correct per spec, which names exactly 3 tabs to migrate and provisions no flag for voice-profile management.
- QA: READY, 0 blocking bugs. 1 Low cosmetic bug (skeleton always shows 4 placeholder rows regardless of eventual 3-7 tabs, minor residual shift); 1 Low unreachable edge case in the array-unwrap fallback (doesn't affect the real endpoint's bare-object response).

## Dependencies
- Requires: PROJ-65 (Backend Effective-Permissions API) — konsumiert `GET /api/auth/permissions`.
- Sollte nach PROJ-60 (Theming) und PROJ-62 (i18n) umgesetzt werden, da `SettingsPage.tsx`/`MailboxSection.tsx` in beiden vorherigen Specs ohnehin angefasst werden.

## User Stories
- Als Nutzer mit `can_manage_users=true` (z. B. ein künftig differenzierter Rollen-Typ) möchte ich den Nutzerverwaltung-Tab sehen, auch ohne vollen Admin-Status.
- Als Admin möchte ich weiterhin uneingeschränkten Zugriff auf DMS-, Nutzerverwaltung-, Chatarchiv-Tab und Mailbox-Admin-Funktionen haben — keine Verhaltensänderung gegenüber heute.
- Als Nutzer ohne die jeweilige Berechtigung möchte ich den entsprechenden Tab/die Aktion gar nicht erst sehen, statt einen Fehler nach dem Klick zu bekommen.
- Als Entwickler möchte ich, dass die "Admin darf sich immer für Voice-Enrollment freischalten"-Regel unverändert bestehen bleibt, da sie kein Permission-Gating-Problem ist, sondern eine bewusste Bootstrap-Ausnahme.

## Acceptance Criteria
- [ ] Neuer Hook `usePermissions()` lädt `GET /api/auth/permissions` beim Mount von `SettingsPage.tsx` (nicht global beim App-Start — kein unnötiger Request für Nutzer, die Settings nie öffnen).
- [ ] Während des Ladens zeigt die Tab-Leiste ein Skeleton statt eines Layout-Sprungs.
- [ ] `SettingsPage.tsx`: Tab-Sichtbarkeit ersetzt `isAdmin` durch die granularen Flags — Nutzerverwaltung → `can_manage_users`, DMS → `can_manage_dms_folders`, Chatarchiv → `can_view_chat_archive`. Mein Profil und E-Mail bleiben unverändert für alle Rollen sichtbar.
- [ ] `MailboxSection.tsx`: "Alle Postfächer"-Ansicht, Besitzer-Spalte und das Verwalten fremder Postfächer werden durch `can_manage_mailboxes` statt `role === "admin"` gesteuert; die bestehende `isOwner`-Logik für eigene Postfächer bleibt für alle Rollen unverändert.
- [ ] `UserTable.tsx` (VoiceCell, Zeile 101) und `MeinProfilSection.tsx` (`canEnrollVoice`, Zeile 83) bleiben **unverändert** bei `role === "admin"` — dokumentierte bewusste Ausnahme, keine Permission-Migration.
- [ ] Schlägt `GET /api/auth/permissions` fehl (Netzwerkfehler, 5xx), fällt die Tab-/Aktions-Sichtbarkeit auf das bisherige `role === "admin"`-Verhalten zurück.
- [ ] Ein Nutzer mit granularem Flag `true`, aber `role !== "admin"` (z. B. manuell in der DB gesetzt), sieht den entsprechenden Tab/die Aktion korrekt — Beweis, dass die Gates tatsächlich permission- und nicht mehr rollenbasiert sind.
- [ ] Permissions werden pro Settings-Sitzung einmal geladen, nicht bei jedem Tab-Wechsel erneut angefragt.

## Edge Cases
- Nutzer loggt sich aus und als anderer Nutzer wieder ein, ohne die Seite neu zu laden (SPA-Navigation): `usePermissions()` muss für den neuen Nutzer neu laden, keine stale gecachten Werte des vorherigen Nutzers verwenden.
- Nutzer hat keine Berechtigung für den aktuell aktiven Tab (z. B. Tab-State aus vorheriger Admin-Sitzung im Speicher, Nutzerwechsel): Settings-Seite fällt auf den Default-Tab ("Mein Profil") zurück statt eines leeren/kaputten Panels.
- `GET /api/auth/permissions` liefert 401 (Token währenddessen abgelaufen): folgt dem bestehenden App-weiten 401-Verhalten (Redirect zu `/login`), kein Sonderfall hier.
- Gleichzeitiges Update der Permissions durch einen Admin (z. B. Rollenwechsel) während der betroffene Nutzer die Settings-Seite offen hat: keine Live-Aktualisierung erforderlich — Änderung greift beim nächsten Laden der Settings-Seite.

## Technical Requirements (optional)
- `usePermissions()` folgt dem bestehenden Hook-Muster (`hooks/`), kein globaler State-Layer nötig für diesen begrenzten Scope.
- Kein Eingriff in serverseitige Durchsetzung — Backend-Endpunkte prüfen weiterhin unabhängig ihre eigenen Berechtigungen; dieses Frontend-Gating ist reine UX (kein Sicherheitsgrenze).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
SettingsPage.tsx
+-- usePermissions() (neuer Hook, lädt GET /api/auth/permissions beim Mount)
    +-- Skeleton in der Tab-Leiste während des Ladens
    +-- Tab-Sichtbarkeit: Nutzerverwaltung → can_manage_users, DMS → can_manage_dms_folders, Chatarchiv → can_view_chat_archive
    +-- Mein Profil / E-Mail bleiben für alle Rollen sichtbar (unverändert)

MailboxSection.tsx
+-- "Alle Postfächer"-Ansicht, Besitzer-Spalte, Fremdverwaltung → can_manage_mailboxes (statt role === "admin")
+-- isOwner-Logik (eigene Postfächer) bleibt unverändert für alle Rollen

UserTable.tsx (VoiceCell, Zeile 101) / MeinProfilSection.tsx (canEnrollVoice, Zeile 83)
+-- bewusst UNVERÄNDERT bei role === "admin" — dokumentierte Bootstrap-Ausnahme, keine Permission-Migration
```

#### B) Data Model

Keine neue Persistenz im Frontend — Permissions werden einmal pro Settings-Sitzung abgerufen und im lokalen State des Hooks gehalten (kein globaler State, kein `localStorage`). Bewusst kein Caching über einen Nutzerwechsel hinweg, um veraltete Flags nach SPA-internem Login-Wechsel auszuschließen.

#### C) Tech Decisions

- **Laden erst beim Mount von SettingsPage, nicht global beim App-Start:** Erfüllt die Anforderung, dass Nutzer, die Settings nie öffnen, keinen zusätzlichen Request zahlen; vermeidet außerdem einen globalen State-Layer, den das Projekt bewusst nicht nutzt (frontend-design.md §2: „kein Redux/Zustand").
- **Fail-open auf heutiges `role === "admin"`-Verhalten bei Ladefehler:** Ein Netzwerkfehler soll einem echten Admin nicht versehentlich Tabs verstecken. Dies ist eine UX-Absicherung, keine Sicherheitsgrenze — Backend-Endpunkte prüfen weiterhin unabhängig ihre eigenen Berechtigungen (siehe Technical Requirements der Spec).
- **Die zwei explizit ausgenommenen Prüfungen (VoiceCell, canEnrollVoice) bleiben bei `role === "admin"`** — dokumentierte bewusste Ausnahme, dieser Hook fasst sie nicht an.
- **Neu-Laden bei Nutzerwechsel:** `usePermissions()` darf keine gecachten Werte des vorherigen Nutzers zeigen — erzwingt einen frischen Fetch bei jedem Settings-Mount statt eines persistenten Caches.

#### D) Dependencies

Keine neuen Pakete — `usePermissions()` folgt dem bestehenden Hook-Muster (`hooks/`), konsumiert PROJ-65s Endpunkt über den bestehenden Fetch-Ansatz (kompatibel mit PROJ-67s Wrapper, unabhängig von dessen Rollout-Reihenfolge).

## QA Test Results

**Tested:** 2026-07-20
**Tester:** QA Engineer (AI) — static verification + production build (no live containers/browser in this environment)
**Scope:** `frontend/src/services/permissions.ts`, `frontend/src/hooks/usePermissions.ts`, `frontend/src/components/Settings/SettingsPage.tsx`, `frontend/src/components/Settings/MailboxSection.tsx`; cross-checked against `frontend/src/services/fetchWithAuth.ts`, `UserTable.tsx`, `MeinProfilSection.tsx`, `AuthProvider.tsx`, i18n locales, and backend `docker/compose/automations/alice-auth/main.py`.

> Verification method: full read of all 4 changed files + traced consumers, codebase-wide grep for every call site of `usePermissions`/`getPermissions`, `git diff`/`git status` to prove the two bootstrap-exception files are untouched by this feature, `npm run build`, i18n key existence check, and a backend grep to confirm independent server-side enforcement. Items needing a running browser/container are called out as "not runtime-verified" rather than assumed.

### Acceptance Criteria Status

#### AC-1: `usePermissions()` loads on `SettingsPage` mount only (not global)
- [x] Only call site of the hook is `SettingsPage.tsx:25`; grep found no app-root/layout/provider invocation.
- [x] `getPermissions()` is called exclusively from inside `usePermissions`' `useEffect` — no other consumer.
- [x] `useEffect` dependency array is `[]` → fires once per mount; users who never open Settings issue no request.

#### AC-2: Skeleton in the tab bar during loading, no layout jump
- [x] While `isLoading`, a `<Skeleton>` block replaces the `<TabsList>` (SettingsPage.tsx:96-104) with the same container layout classes (`flex flex-row md:flex-col w-full md:w-44 shrink-0 ... border border-border bg-card p-1`) — the empty→populated jump is avoided.
- [x] `aria-hidden="true"` on the skeleton — correct a11y.
- [~] Minor: the skeleton always renders a fixed 4 placeholder rows, but the resolved tab bar shows a variable count (3 for a plain user up to 7 for an admin). On desktop (vertical stack) this can still produce a small residual vertical shift when the real bar replaces the skeleton. See BUG-1 (Low, cosmetic). AC intent (no blank→tabs jump) is met.

#### AC-3: Tab visibility driven by the 3 granular flags, not `role`
- [x] `canDms = can("can_manage_dms_folders")`, `canUsers = can("can_manage_users")`, `canChatArchive = can("can_view_chat_archive")` — TabsTrigger and TabsContent for DMS/Nutzerverwaltung/Chatarchiv are gated on these, not on `isAdmin`.
- [x] `mein-profil`, `allgemein`, `email` render unconditionally for all roles.
- [x] Voice-profiles tab deliberately stays on `isAdmin` — CONFIRMED CORRECT, not a gap: the spec (AC list + Tech Design component structure) exhaustively names exactly 3 tabs to migrate; PROJ-65 provisioned no voice-management flag, so no granular flag exists to migrate it to. Leaving it on `isAdmin` is faithful to the spec and preserves prior behavior.

#### AC-4: `MailboxSection` gated by `can_manage_mailboxes` prop, `isOwner` unchanged
- [x] Prop `canManageMailboxes: boolean` added; all 4 former role uses replaced: title (adminTitle/userTitle, line 119), owner column header (line 149), owner cell (line 166), and `canManage` (line 159).
- [x] Grep confirms NO residual `role === "admin"` / `isAdmin` anywhere in `MailboxSection.tsx`.
- [x] `isOwner = mb.owner_id === user?.id` and the owner-only Edit/Access buttons are unchanged (lines 158, 187-198).
- [x] `SettingsPage` passes `canManageMailboxes={can("can_manage_mailboxes")}` (line 170).

#### AC-5: `UserTable` VoiceCell & `MeinProfilSection` `canEnrollVoice` untouched
- [x] `UserTable.tsx:93` still `if (user.role === "admin")` in VoiceCell.
- [x] `MeinProfilSection.tsx:88` still `user?.role === "admin" || profile.allow_voice_enrollment`.
- [x] `git status --porcelain` shows ZERO uncommitted changes to both files — PROJ-66's working-tree changes touch only the 4 target files. (Both files do differ vs `main`, but that delta is entirely from the sibling PROJ-60/62 theming/i18n work, which is why the spec's line refs ~101/~83 drifted to 93/88.)

#### AC-6: Fetch failure → fail-open to `role === "admin"`
- [x] End-to-end chain verified: `getPermissions()` throws on non-OK → `usePermissions` `catch` sets `permissions=null, failed=true` → `can()` returns `isAdmin` when `failed || !permissions`. A network/5xx hiccup never hides a real admin's tabs.

#### AC-7: Non-admin with granular flag `true` sees the tab
- [x] Once the fetch succeeds (`!failed && permissions`), `can(flag)` returns `permissions[flag] === true` with NO role check first — a non-admin user whose flag is `true` sees the corresponding tab; an admin whose flag is (unexpectedly) not set would not. Gates are genuinely permission-driven, not role-driven, in the success path.

#### AC-8: Permissions loaded once per Settings session, not per tab-switch
- [x] Hook `useEffect([])` fires once per mount. Tab switches only update `activeTab` local state; they do not remount the hook nor call `getPermissions` again.
- [x] The tab-reset effect (deps `[isLoading, activeTab, permissions, failed]`) only calls `setActiveTab` — it never refetches.

### Edge Cases Status

#### EC-1: In-SPA user switch must refetch, no stale cached flags
- [x] No cross-mount cache exists (state lives in the hook; no module/localStorage cache) — every fresh mount refetches.
- [x] Traced the switch cycle: logout (`AuthProvider.logout` → `router.replace("/login")`) unmounts `SettingsPage`; login (`LoginForm` → `window.location.href = "/"`) is a full page reload that clears all React state. Either path guarantees a fresh `usePermissions` fetch for the new user. No stale-flag path found.

#### EC-2: No permission for active tab → fall back to default tab
- [x] Effect at SettingsPage.tsx:64-68 resets to `mein-profil` when the settled active tab isn't permitted; guarded by `if (isLoading) return` so it can't fire during the skeleton window. No unwanted reset flash for a legitimately-permitted tab (isTabPermitted returns true → no reset).

#### EC-3: 401 (token expired mid-session) → global redirect, not a special case
- [x] `getPermissions` uses `fetchWithAuth` without `suppressAuthRedirect`; a 401 triggers `clearToken()` + `window.location.href = "/login"` inside the wrapper BEFORE it throws. The local `usePermissions` catch does set `failed=true`, but the browser is already navigating away, so the fail-open (admin) tabs are not meaningfully shown, and even if a sub-second re-render occurred the backend enforces every downstream call. No 401-swallowing / no auth-bypass. Handled per spec.

#### EC-4: Concurrent permission update while Settings open
- [x] No live update by design; a role/flag change is picked up on the next Settings mount (fresh fetch). Matches spec.

### Security Audit Results

**Framing:** spec explicitly documents this as UX-only gating, not a security boundary. Confirmed accurate:
- [x] Admin user routes enforce role server-side independently: every `/auth/admin/*` handler in `alice-auth/main.py` (users list :1100, create :1157, reset-otp :1307, set-credentials :1379, status :1471, delete :1519) calls `_require_admin(authorization)`, which returns 401/403 unless the JWT payload `role == "admin"` (main.py:300-311). Hiding a frontend tab is not the enforcement point.
- [x] `GET /api/auth/permissions` itself is JWT-scoped and user-scoped by the JWT `user_id` (verified under PROJ-65) — a caller cannot read another user's permissions; no client-supplied user id.
- [x] Mailbox CRUD is proxied to n8n (`/api/webhook/alice/mailboxes` in `mailApi.ts`) behind `fetchWithAuth`; enforcement lives in the n8n workflow (JWT-verified webhook), architecturally separate from this frontend change. *Not statically verifiable in this repo scope* (workflow JSON not part of this diff), but the frontend change adds no new privileged path — a user who forges `canManageMailboxes` client-side still hits the server's own check.
- [x] No secrets introduced; `permissions.ts` logs nothing; no PII/token in any new code path.
- [x] No new injection surface: the flag name passed to `can()`/`permissions[flag]` is a hard-coded string literal, never user input.

### Regression
- [x] Build passes: `npm run build` → "Compiled successfully", type-check + lint clean, `/settings` route emitted. No new warnings introduced by making Tabs controlled.
- [x] i18n (PROJ-62): all referenced keys exist in both `de.ts` and `en.ts` — `settings.tabs.{dms,users,usersShort,voiceProfiles,chatArchive,profile,profileShort,allgemein,email}` and `settings.mail.{adminTitle,userTitle}`. Making `<Tabs>` controlled (`value`/`onValueChange`) did not disturb the translated trigger labels.
- [x] Theming (PROJ-60): tab triggers and skeleton use the semantic token classes (`bg-card`, `bg-muted`, `text-foreground`, `border-border`) unchanged — no hardcoded colors reintroduced.
- [x] `MailboxSection` prop-drilling: only one new prop added; all existing props/behavior (`useMailboxes`, add/edit/delete/access dialogs, loading/error/empty states, `isOwner` actions) unchanged. Owner-only Edit/Access buttons and the masked host for non-managers still behave as before.

### Bugs Found

#### BUG-1: Skeleton uses a fixed 4-row placeholder regardless of eventual tab count
- **Severity:** Low
- **Steps to Reproduce:**
  1. Open `/settings` as a plain user (3 tabs resolve: Profile, Allgemein, E-Mail) or as an admin (7 tabs).
  2. Observe the loading skeleton renders exactly 4 placeholder rows (SettingsPage.tsx:101).
  3. Expected: skeleton row count approximates the resolved tab count so the bar height is stable.
  4. Actual: on desktop (vertical stack) the bar height changes when the real `TabsList` (3–7 rows) replaces the 4-row skeleton — a small residual vertical shift.
- **Impact:** Cosmetic only; on mobile (horizontal, flex-1) it is not noticeable. The empty→populated jump that AC-2 targets is still prevented.
- **Priority:** Nice to have.

#### OBS-1: `getPermissions` array-unwrap returns `undefined` for an empty array (defensive-only path)
- **Severity:** Low (not reachable against the real backend)
- **Detail:** If the endpoint ever returned `[]`, `body[0]` yields `undefined`, which `usePermissions` would store; `can()` then treats `!permissions` as truthy and fails open to `isAdmin`. The coordinator confirmed the live endpoint returns a bare flat object, so this branch is never executed. Fail-open is also the intended safe direction. No action required; noted for completeness.

### Items Not Verifiable Without a Live Browser/Container (explicitly stated)
- Actual rendered skeleton-to-tabs transition and the exact pixel shift in BUG-1 (needs a browser at 375/768/1440px).
- Real 401 redirect timing race in EC-3 (needs a live expired token).
- n8n mailbox-webhook server-side enforcement (workflow JSON outside this diff).
These are traced as correct/benign by static analysis and should be smoke-tested during `/deploy`.

### Summary
- **Acceptance Criteria:** 8/8 passed (AC-2 passed with a Low cosmetic note).
- **Edge Cases:** 4/4 handled.
- **Bugs Found:** 1 Low (BUG-1, cosmetic) + 1 Low observation (OBS-1, unreachable) — 0 critical, 0 high, 0 medium.
- **Security:** Pass — UX-only gating framing confirmed accurate; backend `/auth/admin/*` routes independently `_require_admin`-gated; permissions endpoint JWT/user-scoped; no new privileged path or injection surface.
- **Production Ready:** YES (READY).
- **Recommendation:** Deploy. The single Low finding is cosmetic (skeleton row count) and non-blocking. Smoke-test the responsive skeleton transition and confirm a non-admin-with-flag test account sees the gated tab during `/deploy`.

## Deployment
_To be added by /deploy_
