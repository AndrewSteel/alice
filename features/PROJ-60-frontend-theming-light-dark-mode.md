# PROJ-60: Frontend Theming — Light/Dark Mode Switch

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Implementation Notes
- `next-themes` ThemeProvider wraps the app in `frontend/src/app/layout.tsx`; 3-way toggle (`ThemeToggle.tsx`) added to Settings → Mein Profil, visible to all roles.
- Nova palette (Zinc base, Cyan accent, Lime/Cyan charts) defined for `:root`/`.dark` in `globals.css`; ~55 component files migrated from literal `bg-gray-*`/`text-gray-*` to semantic tokens.
- Two highlight.js themes CSS-scoped (`highlight-themes.css`) under `:root`/`.dark`, switching without markdown re-render.
- QA: READY. 1 Medium bug (unreadable pink inline-code text + hardcoded `prose-invert` in `AssistantMessage.tsx`) fixed post-QA — now `text-pink-600 dark:text-pink-300` and `dark:prose-invert`; rebuild confirmed clean. 2 remaining Low/cosmetic bugs not fixed (FlipCard header/footer/card-face shade layering flattens in Light mode; a few intentionally-untouched literal link/icon colors sit below WCAG AA on white) — tracked here for future polish, non-blocking per Approved bar (no critical/high).

## Dependencies
- None (foundational for the frontend redesign; PROJ-61/62/63 build on the semantic token layer this spec introduces)

## User Stories
- Als Nutzer (admin/user/guest/child) möchte ich zwischen Hell, Dunkel und System wechseln können, damit die Oberfläche zu meiner Umgebung und Präferenz passt.
- Als Erstbesucher möchte ich, dass Alice beim ersten Laden automatisch meine Betriebssystem-Farbeinstellung übernimmt, ohne dass ich etwas konfigurieren muss.
- Als wiederkehrender Nutzer möchte ich, dass meine manuell gewählte Theme-Einstellung auf demselben Gerät/Browser erhalten bleibt.
- Als Nutzer möchte ich den Umschalter an einem vorhersehbaren Ort (Settings → Mein Profil) finden, zusammen mit meinen anderen Anzeige-Präferenzen (Anrede, Sprache).
- Als Nutzer möchte ich, dass Codeblöcke im Chat in beiden Modi gut lesbar bleiben.

## Acceptance Criteria
- [ ] Ein dreistufiger Theme-Regler (Hell / Dunkel / System) ist unter Settings → Mein Profil verfügbar, für alle Rollen sichtbar und bedienbar (admin/user/guest/child).
- [ ] Ohne gespeicherte Präferenz folgt der Startwert `prefers-color-scheme` des Browsers/OS.
- [ ] Eine manuelle Auswahl wird geräte-/browserspezifisch in `localStorage` gespeichert und überschreibt bei künftigen Besuchen die System-Präferenz.
- [ ] Wahl von "System" entfernt den manuellen Override; die App folgt danach live Änderungen der OS-Einstellung (z. B. automatischer OS-Wechsel abends) ohne Reload.
- [ ] Der Wechsel wirkt sofort, ohne Seiten-Reload.
- [ ] Alle Bereiche rendern korrekt in Hell und Dunkel über semantische Tokens (keine literalen `bg-gray-*`/`text-gray-*`-Klassen mehr auf themebaren Flächen): Login, Chat (alle Message-Rollen), Sidebar, alle Settings-Tabs (Mein Profil, DMS, Nutzerverwaltung, E-Mail, Chatarchiv), Vision/FlipCard.
- [ ] Farbtokens in `globals.css`/`tailwind.config.ts` sind für `:root` (Light) und `.dark` neu definiert: Style "Nova", Basisfarbe Zinc, Akzentfarbe Cyan, Chart-Farben als Lime/Cyan-Kombination.
- [ ] Codeblöcke (rehype-highlight) verwenden im Light Mode ein helles Highlight.js-Theme und im Dark Mode weiterhin `atom-one-dark`, automatisch synchron zum App-Theme.
- [ ] Kein Flash of Incorrect Theme (FOUC) beim initialen Laden.
- [ ] Fällt `localStorage` aus (z. B. privates Fenster, restriktive Browser-Policy), funktioniert die App fehlerfrei mit System-Präferenz als Fallback bei jedem Laden.

## Edge Cases
- Erste Sitzung ohne gespeicherte Präferenz: App folgt `prefers-color-scheme`.
- `localStorage` deaktiviert/blockiert: kein Fehler, Fallback auf System-Default bei jedem Laden, keine Persistenz.
- Nutzer wählt Theme manuell, ändert danach seine OS-Einstellung: manuelle Wahl bleibt bestehen, kein automatisches Zurückspringen, bis explizit "System" gewählt wird.
- Mehrere Tabs/Fenster desselben Browsers gleichzeitig offen: Wechsel in einem Tab synchronisiert sich in die anderen (Standardverhalten von `next-themes` über das `storage`-Event).
- Gerätewechsel (neues Gerät, anderes Browser-Profil, Inkognito): keine serverseitige Synchronisierung — Präferenz ist rein lokal und muss dort neu gesetzt werden.
- Bereits gestreamte/gerenderte Chat-Nachrichten (Markdown, Codeblöcke, Tabellen) müssen beim Theme-Wechsel ohne erneuten Fetch korrekt umfärben.

## Technical Requirements (optional)
- `next-themes` (bereits als Dependency vorhanden, aktuell ungenutzt) als Theme-Provider für Hydration-sicheres Rendering und Cross-Tab-Sync.
- Migration aller betroffenen Komponenten von literalen Tailwind-Farbklassen auf semantische Tokens (`bg-background`, `text-muted-foreground`, etc.) — u. a. Chat-, Sidebar-, Settings- und Vision-Komponenten (siehe `frontend-design.md`, Abschnitt 6.1).
- Zwei `highlight.js`-Stylesheets (dark/light), an das aktive Theme gekoppelt geladen bzw. per CSS-Scoping aktiviert.
- Rein clientseitiger Theme-Zustand (localStorage) — kompatibel mit dem aktuell noch bestehenden statischen Export (siehe PROJ-59-Notiz zur Rendering-Architektur, separat an `/architecture` adressiert).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
Settings → Mein Profil (ProfilForm)
+-- Theme-Regler (3-stufig: Hell / Dunkel / System)

App-weite Querschnitts-Änderung (kein neuer Komponenten-Baum):
+-- app/layout.tsx — ThemeProvider (next-themes) umschließt die App, ersetzt das heute hart gesetzte className="dark"
+-- globals.css / tailwind.config.ts — Token-Neudefinition für :root (Light) und .dark (Style "Nova": Basis Zinc, Akzent Cyan, Charts Lime/Cyan)
+-- Alle bestehenden Bereiche (Chat, Sidebar, Settings, Vision) — Migration literaler Farbklassen (bg-gray-900 etc.) auf semantische Tokens (bg-background, text-muted-foreground etc.)
+-- Codeblöcke (rehype-highlight) — zwei highlight.js-Stylesheets (hell/dunkel), aktives per Theme gekoppelt
```

#### B) Data Model

```
Theme-Präferenz:
- Wert: "light" | "dark" | "system"
- Ablageort: localStorage (verwaltet automatisch durch next-themes)
- Kein neues DB-Feld, kein Server-Roundtrip — rein clientseitig
```

#### C) Tech Decisions

- **next-themes statt Eigenbau:** Bereits als Dependency vorhanden, aber ungenutzt (siehe frontend-design.md §6.1). Löst FOUC-Vermeidung (blockierendes Inline-Script vor Hydration), Cross-Tab-Sync (`storage`-Event) und Hydration-sichere Theme-Auflösung — alles Dinge, die eine Eigenimplementierung erneut lösen müsste.
- **Token-Migration ist der eigentliche Aufwand dieser Spec**, nicht der Umschalter selbst: Der 3-Wege-Regler ist ein dünner Wrapper; der Großteil der Arbeit ist das komponentenweite Ersetzen literaler Tailwind-Klassen durch semantische Tokens. Deshalb ist diese Spec bewusst als Grundlage für PROJ-61/62/66/68/71 markiert — diese Folge-Specs berühren dieselben Dateien und sollten die bereits migrierten Tokens vorfinden statt sie selbst nachzuziehen.
- **Farbpalette einmalig als CSS-Variablen** für `:root` und `.dark` definiert, überall per Tailwinds semantischen Farbnamen konsumiert (in `tailwind.config.ts` bereits als Grundgerüst vorhanden, aber aktuell ungenutzt).
- **Codeblock-Highlighting:** zwei Stylesheets parallel geladen, Auswahl über CSS-Scoping an die `.dark`-Klasse gekoppelt — vermeidet ein erneutes Rendern bereits gestreamter Markdown-Nachrichten beim Theme-Wechsel.
- **Rendering-Kompatibilität:** Lösung ist rein clientseitig (localStorage + CSS-Variablen) und unabhängig von der in frontend-design.md §8 offenen Frage „Statischer Export vs. Node-Server" — funktioniert unverändert in beiden Fällen, diese Spec trifft diese Entscheidung nicht.
- **Rollout-Empfehlung:** Token-Migration in Schritten je Bereich (Chat + Settings zuerst, da auch von PROJ-62/66/71 berührt), nicht als ein einzelner Großumbau — reduziert Review-Umfang pro PR.

#### D) Dependencies

- `next-themes` (bereits installiert, wird erstmals genutzt) — keine neue Abhängigkeit.

## QA Test Results

**Tested:** 2026-07-19
**App:** Next.js 15 App Router, static export (`output: "export"`) — verified via clean production build
**Tester:** QA Engineer (AI, autonomous session)
**Method:** Static/code audit of all new files, full `git diff HEAD` review of 56 changed frontend files, `next build`, CSS cascade tracing, `next-themes@0.4.6` behavior verification. No live browser session available in this environment; runtime-visual claims are reasoned from code + CSS specificity, flagged where they need a human spot-check.

### Acceptance Criteria Status

#### AC-1: 3-way toggle in Settings → Mein Profil, visible/operable for all roles
- [x] `ThemeToggle` (Hell/Dunkel/System) rendered unconditionally in a new "Darstellung" `Card` in `MeinProfilSection.tsx` (lines 100-112) — NOT behind any role check or the `canEnrollVoice` gate.
- [x] Correct a11y: `role="radiogroup"` + three `role="radio"` with `aria-checked`, keyboard-focusable buttons, `focus-visible:ring-ring`.
- [x] All roles (admin/user/guest/child) reach Mein Profil, so all can operate it.

#### AC-2: No saved preference → follows `prefers-color-scheme`
- [x] `ThemeProvider` uses `defaultTheme="system"` + `enableSystem`. next-themes resolves to `prefers-color-scheme` when no `localStorage.theme` key exists.

#### AC-3: Manual choice persists in localStorage and overrides on future visits
- [x] `setTheme("light"|"dark")` writes `localStorage.theme`; next-themes reads it on next load and applies before paint via its injected blocking script.

#### AC-4: "System" clears override and live-follows OS changes without reload
- [x] `setTheme("system")` removes the manual override; `enableSystem` wires a `matchMedia("(prefers-color-scheme)")` change listener that re-resolves live. Supported in `next-themes@0.4.6` (verified in package.json).

#### AC-5: Switch is instant, no reload
- [x] Pure client state + CSS-variable swap on the `.dark` class; no navigation/fetch. `disableTransitionOnChange` only suppresses transition flicker during the swap — does not cause a reload and does not conflict with this criterion.

#### AC-6: All areas render in Light and Dark via semantic tokens (no literal `bg-gray-*`/`text-gray-*`)
- [x] `grep -rn "bg-gray-\|text-gray-" frontend/src/components/ frontend/src/app/` → NO MATCHES. Broader sweep (`border-gray/from-gray/ring-gray/placeholder-gray/...`) across `frontend/src` → NO MATCHES.
- [x] Migration is semantically sound across the sampled areas (Auth: LoginForm/ChangePasswordForm/ProtectedRoute; Sidebar: ChatList/ChatListItem/ChatSearch/NewChatButton; Chat: MessageList/UserMessage/AssistantMessage/InputArea; Settings: tabs + MeinProfil; Vision: FlipCard/VisionPanel). Selected/active states preserve distinction (e.g. `ChatListItem` active `bg-muted text-foreground` vs inactive `text-muted-foreground hover:bg-accent/60`; settings tabs `data-[state=active]:bg-muted data-[state=active]:text-foreground`; user bubble `bg-muted` vs transparent assistant message — all remain distinguishable in both modes).
- [~] MINOR: see BUG-3 (FlipCard `bg-card` vs `bg-background` collapse to identical white in light mode) — legibility preserved via borders, but intended shade layering flattens.

#### AC-7: Tokens redefined for `:root` (Light) and `.dark` — Nova / Zinc base / Cyan accent / Lime+Cyan charts
- [x] `globals.css` defines full token set for both `:root` and `.dark`. Zinc hue 240 base; `--primary`/`--ring` = Cyan (192/187); `--chart-*` mix Lime (84-85) and Cyan (186-192).
- [x] `tailwind.config.ts` maps every semantic name to `hsl(var(--…))` (background/foreground/card/popover/primary/secondary/muted/accent/destructive/border/input/ring/chart/sidebar). Spec allowed globals.css OR tailwind.config.ts; tokens live in globals.css and are consumed via the config — resolves correctly (build passes, classes generated).

#### AC-8: Code blocks — light hljs theme in Light, `atom-one-dark` in Dark, auto-synced
- [x] `highlight-themes.css` scopes atom-one-light under `:root …` and atom-one-dark under `.dark …`, imported at top of `globals.css`. Cascade traced: `:root .hljs` = specificity (0,2,0) and `.dark .hljs` = (0,2,0) are EQUAL, so source order decides. Dark rules come later → win when `.dark` is present; in Light mode `.dark …` selectors don't match at all → light wins. Correct, no specificity fight.
- [x] No other/stale hljs stylesheet import exists (only the code element applying the `hljs` class in `AssistantMessage.tsx`). Theme swap recolors already-streamed markdown via CSS only, no re-render.

#### AC-9: No FOUC on initial load
- [x] next-themes renders its blocking theme script into the prerendered HTML (static export includes it); `layout.tsx` sets `suppressHydrationWarning` on `<html>` and dropped the hardcoded `className="dark"`. Class is applied before first paint.
- Note: recommend a human spot-check of the exported `index.html` in production to confirm the inline script is present in the static output (reasoned correct; not observable in this headless session).

#### AC-10: localStorage blocked → clean fallback to system every load, no crash
- [x] next-themes@0.4.6 wraps all `localStorage` access in try/catch internally; on failure it degrades to the system preference and simply does not persist. No custom storage code was added that could throw. No crash path introduced.

### Edge Cases Status
- [x] EC-1 First session, no pref → follows `prefers-color-scheme` (AC-2).
- [x] EC-2 localStorage disabled → system fallback, no persistence, no error (AC-10).
- [x] EC-3 Manual choice sticky across OS changes until "System" chosen (next-themes only follows OS when theme==="system").
- [x] EC-4 Multi-tab sync via `storage` event (next-themes default).
- [x] EC-5 Device/profile switch → purely local, no server sync (no DB field added; correct by design).
- [x] EC-6 Already-streamed markdown/code recolors on switch without refetch — CSS-scoped hljs + semantic tokens, no re-render (AC-8).

### Security Audit Results (red-team)

Pure client-side CSS/theme feature; no API, auth, or server surface touched.
- [x] No new network calls, endpoints, or auth changes.
- [x] localStorage usage is entirely inside `next-themes`; only a fixed enum ("light"/"dark"/"system") is ever written, and the value is applied as a CSS class name, never injected as HTML/JS — no XSS vector.
- [x] The injected anti-FOUC script is library-authored and reads only its own storage key; no user-controlled data flows into it.
- [x] No secrets, env vars, or `NEXT_PUBLIC_` additions.
- **Security verdict: PASS.**

### Bugs Found

#### BUG-1: Inline code is near-illegible in Light mode — FIXED
- **Severity:** Medium
- **Resolution:** Changed to `text-pink-600 dark:text-pink-300`; rebuild confirmed clean.
- **Location:** `frontend/src/components/Chat/renderers/AssistantMessage.tsx:27`
- **Steps to Reproduce:**
  1. Switch theme to Hell (light).
  2. Open a chat message containing inline `` `code` ``.
  3. Expected: readable inline code in both modes.
  4. Actual: inline code uses `bg-card text-pink-300`. The migration made the background theme-aware (`bg-card` = white in light) but left the text a fixed light pink (`pink-300`, #f9a8d4). Contrast on white ≈ 1.3:1 — effectively unreadable. Dark mode is fine.
- **Priority:** Fix before deployment (regression introduced by the migration; touches the "code readable in both modes" story). Suggest a token/`dark:` split, e.g. a darker pink or `text-primary` in light.

#### BUG-2: `prose prose-invert` is hardcoded instead of `dark:prose-invert` — FIXED
- **Severity:** Low
- **Resolution:** Changed to `dark:prose-invert`; rebuild confirmed clean.
- **Location:** `frontend/src/components/Chat/renderers/AssistantMessage.tsx:53`
- **Detail:** `prose-invert` (Typography dark palette) is applied unconditionally. Most text is explicitly overridden to `text-foreground`, so body/headings/strong stay correct in Light mode. But un-overridden prose sub-elements (list bullets/counters, captions) keep dark-tuned colors in Light mode — legible but semantically wrong and slightly washed out. Should be `dark:prose-invert`.
- **Priority:** Fix in next sprint.

#### BUG-3: FlipCard surface layering flattens in Light mode
- **Severity:** Low
- **Location:** `frontend/src/components/Vision/FlipCard.tsx`
- **Detail:** Header/footer bars mapped to `bg-background` while the card face is `bg-card`. In Dark these differ (background darker than card → inset look). In Light both `--background` and `--card` are `0 0% 100%` (pure white), so the shade separation disappears; only the `border-border` dividers remain. Not broken, but loses intended depth. Consider `bg-muted` for the bars.
- **Priority:** Nice to have.

#### BUG-4: Left-untouched literal accent colors are borderline in Light mode
- **Severity:** Low
- **Location:** e.g. `AssistantMessage.tsx` link `prose-a:text-blue-400`; amber lock icon in `ChangePasswordForm.tsx`; various `focus:border-blue-500`.
- **Detail:** These non-gray literals were intentionally out of the gray-only migration scope. On the new white Light background several sit below WCAG AA for normal text (`blue-400` on white ≈ 2.6:1). Cosmetic in Dark, sub-optimal in Light.
- **Priority:** Nice to have (follow-up polish pass / covered by later PROJ-6x specs).

### Regression Check (broad ~56-file touch)
- [x] Diff audited for accidental non-color class edits: the ONLY non-`gray→token` changes are the intended `layout.tsx` restructure (dropped `className="dark"` + hardcoded body colors, now driven by `body { @apply bg-background text-foreground }`), the `antialiased` class preserved, and the new Darstellung card. No layout/spacing/flex/grid/size classes were altered by the migration — sed-style collateral damage did NOT occur.
- [x] Shared components used by PROJ-51/52 (chat storage: ChatList/ChatListItem/MessageList) and PROJ-54/55/56 (Vision/DMS: FlipCard/VisionPanel/ThumbnailImage) changed color tokens only; structure/handlers untouched.
- [x] `next build` passes cleanly (exit 0, 6/6 static pages, export OK, no type/lint errors).

### Summary
- **Acceptance Criteria:** 10/10 functionally passed (AC-6 passes with a minor light-mode flattening noted in BUG-3).
- **Bugs Found:** 4 total (0 critical, 0 high, 1 medium, 3 low).
- **Security:** PASS — no attack surface introduced.
- **Production Ready:** YES (no critical/high). Recommend fixing BUG-1 (medium light-mode readability regression) before or immediately after deploy; BUG-2/3/4 are low-priority polish.
- **Recommendation:** Approve. Address BUG-1 as a fast follow.

## Deployment
_To be added by /deploy_
