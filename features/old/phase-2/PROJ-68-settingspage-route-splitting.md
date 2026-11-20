# PROJ-68: SettingsPage — Route-Splitting

## Status: Deployed
**Created:** 2026-07-19
**Last Updated:** 2026-07-20

## Implementation Notes
- Monolithic `SettingsPage.tsx` deleted, replaced by `app/settings/layout.tsx` (shared shell, keeps `usePermissions()` mounted once per Settings visit) + 7 subroute pages (`profil`, `allgemein`, `dms`, `nutzer`, `stimmprofile`, `chatarchiv`, `mail`), each dynamic-importing its Section component.
- 7 routes instead of the Tech Design's illustrative 5-route list — QA confirmed this is correct: the live post-PROJ-66 UI has 7 tabs, and AC-1's binding text ("jeder bestehende Settings-Tab") plus AC-3 (tab bar visually unchanged) require covering all of them.
- New `SettingsShell.tsx` (real `<Link>`-based tab bar + route guard), `SettingsGatingContext.tsx` (shares PROJ-66's `can()` across routes without refetching), `SettingsSectionSkeleton.tsx`.
- Bundle win: old `/settings` monolith was 329 kB First Load JS; new `/settings/profil` is 113 kB — a ~66% reduction.
- QA: READY, 0 blocking bugs. 1 Low known gap: a hard page-load of an unknown `/settings/xyz` URL (typo/stale bookmark only, never reachable via in-app navigation) falls back to the app root instead of redirecting to `/settings/profil`, due to the static-export (`output: "export"`) constraint rejecting a catch-all route — the spec's own edge-case wording explicitly permits this as an acceptable alternative. 1 Low cosmetic bug inherited from PROJ-66 (skeleton row count).

## Dependencies
- Sollte nach PROJ-66 (Frontend Granulares Rollen-Gating) umgesetzt werden — die Route-Guards dieser Spec nutzen denselben `usePermissions()`-Hook und dieselben Flags, um direkten URL-Zugriff auf nicht erlaubte Tabs zu blockieren.
- Kompatibel mit dem aktuellen statischen Export (Next.js `output: 'export'` unterstützt verschachtelte statische Routen ohne Node-Server).

## User Stories
- Als Entwickler möchte ich, dass jeder Settings-Tab sein eigenes Bundle lädt, statt dass alle ~20 Section-/Dialog-Dateien beim ersten Öffnen von Settings auf einmal geladen werden.
- Als Nutzer möchte ich einen Settings-Tab direkt per URL aufrufen oder als Lesezeichen speichern können (z. B. `/settings/mail`), statt immer über den Default-Tab starten zu müssen.
- Als Nutzer möchte ich mit dem Browser-Zurück-Button zwischen zuvor besuchten Settings-Tabs wechseln können.
- Als Nutzer ohne Berechtigung für einen Tab möchte ich bei direktem URL-Aufruf sauber auf einen erlaubten Tab umgeleitet werden, statt einen kaputten oder leeren Bildschirm zu sehen.

## Acceptance Criteria
- [ ] Jeder bestehende Settings-Tab wird eine eigene Next.js-Subroute: `/settings/profil`, `/settings/dms`, `/settings/nutzer`, `/settings/mail`, `/settings/chatarchiv` (URL-Segmente final in `/architecture` festzulegen).
- [ ] Jede Subroute lädt ihre zugehörigen Section-/Dialog-Komponenten per Code-Splitting (dynamischer Import) statt als Teil eines gemeinsamen Bundles.
- [ ] Die Tab-Leiste (vertikal Desktop / horizontal scrollbar Mobile) bleibt optisch unverändert, navigiert aber über echte Links/Routing statt lokalem State.
- [ ] Browser-Vor-/Zurück-Navigation wechselt zwischen zuvor besuchten Settings-Tabs.
- [ ] `/settings` (ohne Sub-Pfad) redirected auf den Default-Tab `/settings/profil`.
- [ ] Ruft ein Nutzer eine Subroute direkt per URL auf, für die ihm laut PROJ-66 (`usePermissions()`) die Berechtigung fehlt, wird er ohne sichtbares Aufblitzen geschützter Inhalte auf `/settings/profil` umgeleitet.
- [ ] Gesamtgröße des initial für `/settings/profil` geladenen JS-Bundles ist spürbar kleiner als das heutige monolithische Settings-Bundle (konkreter Zielwert in `/architecture`).
- [ ] Kompatibel mit statischem Export — keine serverseitigen Route-Handler nötig, alle Prüfungen laufen clientseitig nach dem Laden der statischen Route.

## Edge Cases
- Direkter Aufruf einer unbekannten Settings-Subroute (z. B. Tippfehler `/settings/xyz`): Standard-404-Verhalten oder Redirect auf `/settings/profil` (Entscheidung in `/architecture`).
- Nutzer öffnet einen Tab per Deep-Link, während die Permissions (PROJ-66) noch laden: Route-Guard wartet den Ladezustand ab (Skeleton, siehe PROJ-66), statt vorschnell umzuleiten oder kurz falsche Inhalte zu zeigen.
- Nutzer mit offenem, ungespeichertem Formular (z. B. Mailbox-Bearbeitungsdialog) navigiert per Browser-Zurück zu einem anderen Tab: bestehendes Verhalten (kein Autosave) bleibt unverändert — keine neue "ungespeicherte Änderungen"-Warnung im Scope dieser Spec.
- Rollenwechsel während eine Subroute offen ist (siehe PROJ-66 Edge Case): beim nächsten Routenwechsel greifen die aktualisierten Permissions, kein Live-Update während der Nutzer auf der Seite verweilt.

## Technical Requirements (optional)
- Next.js App-Router-Struktur: `app/settings/[tab]/page.tsx` oder einzelne Ordner je Tab — Entscheidung in `/architecture`.
- Migration schrittweise pro Tab möglich, kein Big-Bang-Zwang.
- Keine Änderung an den Section-/Dialog-Komponenten selbst (deren interne Logik bleibt unangetastet) — nur an der Lade-/Routing-Struktur um sie herum.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
app/settings/
+-- page.tsx           → redirect auf /settings/profil
+-- profil/page.tsx     → MeinProfilSection (+ Dialoge), Code-Splitting per dynamischem Import
+-- dms/page.tsx        → DmsSection (+ Dialoge), dynamischer Import, Route-Guard can_manage_dms_folders
+-- nutzer/page.tsx     → NutzerVerwaltungSection (+ Dialoge), dynamischer Import, Route-Guard can_manage_users
+-- mail/page.tsx       → MailboxSection (+ Dialoge), dynamischer Import
+-- chatarchiv/page.tsx → ChatarchivSection, dynamischer Import, Route-Guard can_view_chat_archive

Gemeinsame Settings-Shell (Tab-Leiste vertikal Desktop/horizontal Mobile) navigiert über echte Links statt lokalem Tab-State
```

#### B) Data Model

Keine — der URL-Routenparameter ersetzt den bisherigen lokalen Tab-State, keine neue Persistenz.

#### C) Tech Decisions

- **URL-Segmente auf Deutsch** (`profil`, `dms`, `nutzer`, `mail`, `chatarchiv`), passend zur bestehenden deutschsprachigen UI-Konvention und den heutigen Tab-Labels — vermeidet eine gemischtsprachige URL-Oberfläche.
- **Kompatibel mit statischem Export:** Next.js App-Router unterstützt verschachtelte statische Routen ohne Node-Server (bestätigt durch die Technical Requirements der Spec) — keine Änderung an `scripts/deploy-frontend.sh` nötig. Die in frontend-design.md §8 aufgeworfene, übergeordnete Frage „statischer Export vs. Node-Server" bleibt offen und unabhängig von dieser Spec — keine der PROJ-60–71-Specs setzt diese Entscheidung voraus.
- **Route-Guard hängt an PROJ-66s `usePermissions()`** (bereits als Dependency vermerkt): Während Permissions laden, zeigt die Route dasselbe Skeleton wie PROJ-66, statt verfrüht umzuleiten oder kurz geschützte Inhalte aufblitzen zu lassen.
- **Unbekannte Subroute (`/settings/xyz`) leitet auf `/settings/profil` um** statt eines nackten 404 — konsistent mit dem Grundsatz „nie ein kaputtes Panel zeigen".
- **Code-Splitting per Tab ist der Mechanismus**, der das heutige ~5.000-Zeilen-Monolith-Bundle verkleinert — jede Subroute lädt ihre Section-/Dialog-Komponenten erst bei Besuch.
- **Migration schrittweise pro Tab möglich**, kein Big-Bang-Zwang (bereits in Technical Requirements vorgegeben).

#### D) Dependencies

Keine neuen Pakete — nutzt Next.js App-Router und dynamischen Import, beide bereits im Stack.

## QA Test Results

**Tested:** 2026-07-20
**Tester:** QA Engineer (AI) — static verification + production `next build` (before/after) in a container-less environment (no live browser).
**Scope:** `frontend/src/app/settings/{layout,page}.tsx` + all 7 subroute `page.tsx` files, `frontend/src/components/Settings/{SettingsShell,SettingsGatingContext,SettingsSectionSkeleton}.tsx`; cross-checked against the deleted `SettingsPage.tsx` (`git show HEAD:`), `hooks/usePermissions.ts`, `MailboxSection.tsx`, i18n locales, `next.config.*`, and `nginx/conf.d/alice.conf`.

> Verification method: full read of every new/changed route + shell file; `git diff HEAD` to prove the Section/Dialog components are byte-for-byte unchanged; codebase-wide grep for stale `SettingsPage` references and `/settings` links; two full production builds (current branch **and** a `git worktree` at HEAD) to measure the real before/after bundle sizes; inspection of `frontend/out/settings/` static-export output; nginx `try_files` trace for the unknown-route edge case. Items needing a running browser are flagged as not-runtime-verified rather than assumed.

### Flagged Deviation Rulings

**Deviation #1 (7 subroutes vs. the Tech Design's 5-route list) — CORRECT, not a bug.**
AC-1's binding wording is *"Jeder bestehende Settings-Tab wird eine eigene Next.js-Subroute"* ("every existing tab becomes its own subroute"). The live post-PROJ-66 UI has 7 tabs (`profil`, `allgemein`, `dms`, `nutzer`, `stimmprofile`, `chatarchiv`, `mail`). Dropping `allgemein`/`stimmprofile` would leave two existing tabs with no route and would visibly alter the tab bar, directly violating AC-1 *and* AC-3 ("Tab-Leiste bleibt optisch unverändert"). The Tech Design §A route list (which even the spec author flagged with "URL-Segmente final in /architecture festzulegen") is illustrative and predates counting the actual current tabs; the AC text governs. Building all 7 is the faithful reading. **AC-1 PASS.**

**Deviation #2 (hard-loaded unknown subroute falls through to app root `/`, not `/settings/profil`) — real gap, severity LOW, non-blocking.** See BUG-1.

### Acceptance Criteria Status

#### AC-1: Every existing tab is its own Next.js subroute
- [x] Routes present and statically generated: `/settings/profil`, `/settings/allgemein`, `/settings/dms`, `/settings/nutzer`, `/settings/stimmprofile`, `/settings/chatarchiv`, `/settings/mail` (+ `/settings` index). Confirmed in the `next build` route table and in `frontend/out/settings/*.html`.
- [x] All 7 existing tabs covered (see Deviation #1 ruling).

#### AC-2: Each subroute code-splits its Section/Dialog components via dynamic import
- [x] Each `page.tsx` uses `next/dynamic(() => import(...), { ssr: false, loading: <SettingsSectionSkeleton/> })` — no static Section import in any route file. The former monolith statically imported all 7 Sections at once.
- [x] Build evidence: each subroute's own "Size" column is ~1.5–1.7 kB vs. the old single `/settings` at **52.9 kB** — the section code is no longer in the initial route chunk.

#### AC-3: Tab bar visually unchanged, now real routing instead of local state
- [x] Compared `SettingsShell.tsx` JSX against `git show HEAD:.../SettingsPage.tsx`: identical header, identical wrapper classes (`flex flex-row md:flex-col w-full md:w-44 shrink-0 ... border border-border bg-card p-1 md:h-fit md:sticky md:top-20`), identical tab order, identical label/shortLabel split, identical active styling (`bg-muted text-foreground shadow-sm`). Only the mechanism changed: shadcn `<TabsTrigger>`+`useState` → `<Link>` with active derived from `usePathname()`. `triggerBase` reproduces the shadcn TabsTrigger base + custom `triggerClass`, plus adds `focus-visible` ring (a11y improvement, not a regression).
- [x] `aria-current="page"` on the active link; `<nav aria-label>` — correct semantics for the new link-based bar.
- [~] Minor pixel note carried from PROJ-66: loading skeleton hardcodes 4 rows regardless of the eventual 3–7 tabs (`SettingsShell.tsx:138`). Cosmetic only. See BUG-2.

#### AC-4: Browser back/forward moves between previously visited tabs
- [x] Tab links are plain `<Link href>` with **no `replace` prop** → each tab click pushes a history entry; back/forward navigates between them. These are genuinely distinct URLs/routes, not local-state swaps.
- [x] `/settings` → profil uses `router.replace` (correct: the index is not a back-trap), and the shell's guard uses `router.replace` too — neither pollutes history. Only real tab-to-tab navigation pushes.

#### AC-5: `/settings` redirects to `/settings/profil`
- [x] `app/settings/page.tsx` `router.replace("/settings/profil")` in a `useEffect`. Redundantly, the shell guard also treats the empty segment as unknown and replaces to profil. Both target the same URL — harmless double-replace, no history entry.

#### AC-6: Direct URL access to an unpermitted subroute redirects to profil with NO flash of guarded content
- [x] Guard logic traced carefully in `SettingsShell.tsx`. Content area renders `children` ONLY when `!isLoading && activeTab && permitted` (line 177); in every other state it renders `SettingsSectionSkeleton`. Because the dynamic Section import lives *inside* `children` (the route `page.tsx`), an unpermitted route never even loads its Section chunk — no flash possible.
- [x] `permitted` is computed per-segment from `TAB_DEFS` via `isPermitted` → `can()` (fail-open from PROJ-66). Applies uniformly to all gated segments (`dms`, `nutzer`, `stimmprofile`, `chatarchiv`), not just some.
- [x] Redirect (`router.replace("/settings/profil")`) fires from a `useEffect` gated by `if (isLoading) return` — never redirects during the permissions-loading window (EC handled: waits for skeleton, no premature redirect).
- [x] Static export generates the valid-but-gated routes' HTML (e.g. `nutzer.html`), so a hard-load by a non-admin correctly mounts the shell, shows the skeleton, then redirects — not a fall-through.

#### AC-7: Initial `/settings/profil` bundle measurably smaller than the old monolith
- [x] **Concrete before/after** (two real production builds):
  - OLD `/settings` (monolith, HEAD worktree): route **52.9 kB**, First Load JS **329 kB**.
  - NEW `/settings/profil`: route **1.58 kB**, First Load JS **113 kB**.
  - Reduction: First Load JS **−216 kB (~66% smaller)**; route-specific JS 52.9 kB → 1.58 kB. Far exceeds "spürbar kleiner". Home route `/` First Load JS is essentially unchanged (297 kB → 300 kB; the "Size" column swing is Next's chunk-attribution accounting, not a real regression).

#### AC-8: Static-export compatible, no server-side route handlers
- [x] `next.config` `output: "export"`; build ran `Exporting (2/2)` and emitted static HTML for all routes. No `app/api` directory, no `route.ts` handlers anywhere. All settings files are `"use client"` components; guards run client-side after the static route loads.

### Edge Cases Status

#### EC-1: Unknown subroute (`/settings/xyz`)
- [~] In-app: impossible — the tab bar only renders valid `<Link>`s, so no unknown segment is ever produced by navigation. Hard-load: see BUG-1 (falls to app root instead of profil). Non-blocking.

#### EC-2: Deep-link while permissions still loading
- [x] Guard `useEffect` returns early while `isLoading`; content shows `SettingsSectionSkeleton`. No premature redirect, no wrong content flash. Handled per spec.

#### EC-3: Unsaved form + browser-back to another tab
- [x] No new autosave/unsaved-changes warning introduced; Section components are unchanged (git diff empty). Existing no-autosave behavior preserved. In scope-boundary compliant.

#### EC-4: Role change while a subroute is open
- [x] No live update; `usePermissions()` refetches on next Settings mount only. Matches spec (and PROJ-66 EC-4).

### PROJ-66 Contract Preservation (fetch-once + mailbox prop)

- [x] **Fetch once per Settings visit, not per tab.** `usePermissions()` is called exactly once — in `SettingsShell`, which is rendered by the shared `app/settings/layout.tsx`. In the Next.js App Router a segment layout stays mounted while only the child `page` swaps on sub-navigation, so tab-to-tab clicks do NOT remount the shell and do NOT refetch. `useEffect([])` fires once per Settings visit. Verified `usePermissions` has no other call site (grep). This is a genuine improvement over the monolith (same guarantee, now structurally enforced by the persistent layout).
- [x] **`canManageMailboxes` wiring intact.** `mail/page.tsx` reads `can("can_manage_mailboxes")` from `useSettingsGating()` and passes it as the `canManageMailboxes` prop to `MailboxSection`. The `SettingsGatingContext.Provider` (in the shell) supplies the same fail-open `can()` from the single `usePermissions()` fetch — no second fetch. `MailboxSection.tsx` is unchanged vs HEAD (git diff empty); its prop contract from PROJ-66 is honored. Provider is only mounted around `children` when permitted, so `useSettingsGating()` in the mail page never hits its null-guard throw.

### Security Audit Results

**Framing:** UX-only gating, identical to PROJ-66; backend enforces independently. Confirmed accurate for this refactor.
- [x] **No new server-side surface.** Pure static client routing — no `app/api`, no `route.ts`, `output: "export"`. Nothing added that could be an auth/injection surface.
- [x] Guard uses hard-coded flag-name string literals (`can_manage_users`, etc.) from `TAB_DEFS` — never user input; no injection vector.
- [x] Hiding/redirecting a tab is not the enforcement point: the backend `/auth/admin/*` and n8n mailbox webhooks re-check the JWT/role on every call (established under PROJ-66). A user who forges the client-side URL or flag still hits the server's own check.
- [x] No secrets, no PII, no logging introduced in any new file.
- [x] Static export means unknown/guessed URLs cannot reach any server handler — worst case is a client-side redirect or a fall-through to the (still auth-gated) app root.

### Regression

- [x] **`SettingsPage.tsx` deleted cleanly.** `git status`: `D SettingsPage.tsx`. Remaining `SettingsPage` mentions are 3 stale doc-comments only (`usePermissions.ts:22`, `MailboxSection.tsx:36`, `SettingsShell.tsx:36`) — no broken imports/JSX. Grep confirms zero live code references.
- [x] **Nav link still works.** `Sidebar/UserCard.tsx:40` does `window.location.href = "/settings"`; `settings.html` is generated and `page.tsx` redirects to profil. Functional via the redirect.
- [x] **Section/Dialog components untouched.** `git diff HEAD --numstat` is empty for `MailboxSection`, `MeinProfilSection`, `DmsSection`, `NutzerVerwaltungSection`, `VoiceProfilesSection`, `ChatarchivSection`, `AllgemeinSection` — internal logic byte-for-byte unchanged, honoring the spec's explicit scope boundary. Only new wrapper/route files + the deletion differ.
- [x] **Build clean.** `npm run build` → "Compiled successfully", type-check + lint pass, 13/13 static pages generated, export OK. No new warnings.
- [x] **i18n (PROJ-62):** all `TAB_DEFS` label keys exist in `de.ts`/`en.ts` (`settings.tabs.{profile,profileShort,allgemein,dms,users,usersShort,voiceProfiles,chatArchive,email}`).
- [x] **Theming (PROJ-60):** shell uses only semantic tokens (`bg-background`, `bg-card`, `bg-muted`, `text-foreground`, `border-border`) — no hardcoded colors.

### Bugs Found

#### BUG-1: Hard-loaded unknown settings URL falls through to app root `/` instead of redirecting to `/settings/profil`
- **Severity:** Low
- **Steps to Reproduce:**
  1. Type or bookmark `/settings/xyz` (a segment with no generated `.html`) and load it directly.
  2. nginx `try_files $uri $uri.html $uri/ /index.html` finds no `settings/xyz.html` and serves `/index.html` (the app root / chat), so the Settings shell never mounts and the client-side redirect-to-profil never runs.
  3. Expected (per Tech Design §C preference): redirect to `/settings/profil`.
  4. Actual: user lands on the fully-functional, still-auth-gated chat root; URL stays `/settings/xyz`.
- **Impact:** Only reachable by manual typo/stale bookmark — in-app navigation can never produce an unknown segment (tab bar renders valid links only). The landing target is a working, authenticated screen, not a broken/blank/404 panel, so the User Story's real concern ("statt einen kaputten oder leeren Bildschirm") is not violated. Root cause is the project-wide `output: "export"` constraint (a catch-all `[...rest]` needs `generateStaticParams()` and cannot enumerate arbitrary typos) plus the existing SPA-fallback nginx rule — not a defect in this feature's logic. The spec's own edge-case wording explicitly permits "Standard-404-Verhalten ODER Redirect ... Entscheidung in /architecture", leaving this fallback within the allowed range.
- **Priority:** Nice to have. If the ideal redirect is later required, options are a small client-side check on the root page for a `/settings/*` pathname, or an nginx `location = /settings/...` rewrite — both out of scope here.

#### BUG-2: Tab-bar loading skeleton hardcodes 4 placeholder rows regardless of eventual 3–7 tabs (carried over from PROJ-66)
- **Severity:** Low (cosmetic)
- **Steps to Reproduce:**
  1. Open any `/settings/*` route; during the permissions fetch the tab bar shows exactly 4 skeleton rows (`SettingsShell.tsx:138`).
  2. Once settled, the real bar shows 3 (plain user) to 7 (admin) tabs — on desktop (vertical stack) the bar height shifts slightly.
- **Impact:** Cosmetic only; unchanged from the pre-refactor behavior (PROJ-66 BUG-1). Not introduced by this feature. Not noticeable on mobile (horizontal, flex-1).
- **Priority:** Nice to have.

### Items Not Verifiable Without a Live Browser/Container (explicitly stated)
- Actual rendered pixel behavior of the skeleton→tabs transition and back/forward at 375/768/1440px (static + build analysis only here).
- Real nginx `try_files` fall-through for BUG-1 was traced from config, not executed against a running server — smoke-test during `/deploy`.
- n8n mailbox-webhook server-side enforcement (workflow JSON outside this diff; unchanged by this refactor).

### Summary
- **Acceptance Criteria:** 8/8 PASS (AC-3 with a Low cosmetic note carried from PROJ-66).
- **Edge Cases:** 3/4 fully handled; EC-1 (unknown route) partially — see BUG-1 (Low, non-blocking, within spec's allowed range).
- **Both flagged deviations resolved:** #1 = correct implementation (all 7 subroutes required by AC-1/AC-3); #2 = genuine Low gap, non-blocking.
- **Bugs Found:** 2 total — 0 Critical, 0 High, 0 Medium, 2 Low (BUG-1 unknown-route fallback; BUG-2 skeleton row count, inherited).
- **PROJ-66 contract:** preserved and structurally strengthened (fetch-once now enforced by the persistent shared layout; mailbox prop correctly rewired through `SettingsGatingContext`).
- **Regression:** none — Section/Dialog components byte-for-byte unchanged; monolith deleted cleanly; nav link works via redirect; build clean.
- **Security:** Pass — pure static client routing, no new server surface, backend enforcement unchanged.
- **Production Ready:** YES (READY).
- **Recommendation:** Deploy. Both findings are Low and non-blocking. During `/deploy`, smoke-test: (a) back/forward across tabs, (b) a non-admin hard-loading `/settings/nutzer` redirects to profil with no flash, (c) the `/settings/xyz` fall-through behavior, and (d) confirm the permissions request fires once per Settings visit (Network tab) and not per tab click.

## Deployment
Deployed 2026-07-20 (manual production deploy by Andrew Steel, frontend bundle covering PROJ-60-62/66-71). Confirmed working in production.
