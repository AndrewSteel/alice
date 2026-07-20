# PROJ-62: Frontend Internationalisierung (i18n)

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-20

## Implementation Notes
- `i18next`/`react-i18next` with `frontend/src/i18n/` (`config.ts`, `format.ts`, `I18nProvider.tsx`, `locales/de.ts`+`en.ts`, 437 leaf keys each, exact parity). Pre-login: `navigator.language` detection (German fallback). Post-login: switches to saved `sprache` immediately, overriding the login screen's language.
- `FlipCard.tsx`'s `DOC_META_LABELS`/`EXTRA_META_LABELS`/`HIDDEN_META_KEYS` moved into the locale files (data-driven); date formatting centralized via `format.ts`'s `intlLocale()`.
- **Coordinator fix**: the original implementation stored/sent the `sprache` field as the legacy German word-form (`"deutsch"`/`"englisch"`) instead of the ISO-639-1 codes PROJ-63 already migrated the backend to. Fixed in `i18n/config.ts` (`Sprache` type now `"de"|"en"`, `localeToSprache()` only emits ISO codes, `spracheToLocale()` still reads both forms for pre-migration profiles), `ProfilForm.tsx`, `CreateUserDialog.tsx` (`SPRACHE_OPTIONS` + translated dropdown labels), and `profileApi.ts` (loosened literal-union types to `string`). QA verified this fix is correct and complete.
- QA: READY. 1 Medium bug (non-blocking, tracked as follow-up): client-authored error strings thrown from the service layer (`api.ts`, `profileApi.ts`, `dms.ts`, `adminApi.ts`, `voiceApi.ts`, `fetchWithAuth.ts`) are hardcoded German and surface untranslated in English mode — fix pattern already exists in the codebase (`auth.ts` uses stable error codes mapped through `t()`), not applied here yet. 1 Low bug: `CreateUserDialog` email placeholder + a few dropdowns not fully localized.

## Dependencies
- None technically, but should land after PROJ-60 (Theming) since both touch nearly every component file — sequencing avoids repeated merge conflicts.
- Absorbs the data-driven refactor of `DOC_META_LABELS`/`EXTRA_META_LABELS`/`HIDDEN_META_KEYS` in `FlipCard.tsx` (frontend-design.md Abschnitt 6.6), since those are exactly the hardcoded-German-string problem this spec solves.
- Reuses the existing `sprache`-Feld in `alice.user_profiles` (bereits vorhanden, aktuell nur für die Alice-Antwortsprache genutzt) — keine neue DB-Spalte nötig.
- **Verwandt, aber separat: PROJ-63** (Backend-Sprachcode-Offenheit in `alice-auth`/`alice-chat-stream`) öffnet die aktuell auf `("deutsch","englisch")` hart validierte `sprache`-Whitelist und die binäre LLM-Prompt-Logik zu einer konfigurierbaren Sprachliste. Diese Spec (PROJ-62) macht nur die Frontend-Übersetzungsschicht offen; das Sprache-Dropdown in Mein Profil/`CreateUserDialog` sollte seine Optionsliste aus derselben Quelle wie PROJ-63 beziehen, sobald diese existiert, statt einer eigenen hartcodierten Liste.

## User Stories
- Als Nutzer möchte ich die Oberfläche (Menüs, Buttons, Labels, Fehlermeldungen, Tooltips) auf Deutsch oder Englisch sehen, statt ausschließlich auf Deutsch.
- Als Nutzer möchte ich, dass meine bereits vorhandene "Sprache"-Einstellung in Mein Profil sowohl Alices Antworten als auch die UI-Sprache steuert — eine Einstellung, kein Widerspruch.
- Als Erstbesucher (noch nicht eingeloggt) möchte ich, dass der Login-Screen meiner Browser-Spracheinstellung folgt, damit ich nicht zwingend Deutsch lesen muss, um mich anzumelden.
- Als eingeloggter Nutzer möchte ich, dass nach dem Login sofort meine gespeicherte Sprachpräferenz greift, unabhängig davon, was der Login-Screen zuvor zeigte.
- Als zukünftiger Betreiber möchte ich, dass eine dritte Sprache ergänzt werden kann, ohne Komponenten-Code anzufassen (nur neue Übersetzungsressourcen).

## Acceptance Criteria
- [ ] Alle statischen UI-Texte sind übersetzbar und liegen für Deutsch und Englisch vollständig vor: Login, Chat (Platzhalter, Tool-Status-Chips, Fehlerzustände, Buttons), Sidebar (Umbenennen/Löschen/Kontextmenü/Service-Links), alle Settings-Tabs (Mein Profil, DMS, Nutzerverwaltung, E-Mail, Chatarchiv), Vision/FlipCard (Metadaten-Labels, Zusammenfassung, leere/fehlende Zustände).
- [ ] Die Architektur ist so offen, dass eine weitere Sprache durch Hinzufügen einer neuen Übersetzungsressource ergänzt werden kann, ohne bestehenden Komponenten-Code zu ändern.
- [ ] Das bestehende `sprache`-Feld in Mein Profil (aktuell: Antwortsprache von Alice) steuert zusätzlich die UI-Sprache — ein Dropdown, ein gespeicherter Wert.
- [ ] Vor dem Login zeigt der Login-Screen die per `navigator.language` erkannte Browsersprache (Fallback Deutsch, falls weder de noch en erkannt wird).
- [ ] Nach erfolgreichem Login wechselt die UI unmittelbar auf den im Profil gespeicherten `sprache`-Wert, auch wenn dieser vom zuvor gezeigten Login-Screen abweicht.
- [ ] Die hartkodierten Metadaten-Label-Maps in `FlipCard.tsx` (`DOC_META_LABELS`, `EXTRA_META_LABELS`, `HIDDEN_META_KEYS`) sind auf eine datengetriebene, übersetzbare Struktur umgestellt statt fest verdrahteter deutscher Strings.
- [ ] Datumsformatierung (z. B. `formatMetaValue` in `FlipCard.tsx`, aktuell hart auf `de-DE` codiert) folgt der aktiven UI-Sprache (`de-DE` vs. `en-US`/`en-GB`).
- [ ] Admin-seitiges Anlegen neuer Nutzer (`CreateUserDialog`) setzt weiterhin den initialen `sprache`-Wert des neuen Nutzers — unverändertes Verhalten, jetzt konsistent mit der UI-Sprachsteuerung.
- [ ] Fehlt ein Übersetzungsschlüssel für die aktive Sprache, wird kein technischer Schlüsselname angezeigt, sondern ein sinnvoller Fallback (deutscher Text) verwendet — kein sichtbarer Absturz oder `undefined`.

## Edge Cases
- Übersetzungsschlüssel fehlt in einer Sprachressource (z. B. nach unvollständigem PR): Fallback auf Deutsch statt Rohschlüssel oder leerem Text.
- Browsersprache ist weder Deutsch noch Englisch (z. B. Französisch): Login-Screen fällt auf Deutsch zurück.
- Rollen Gast/Kind: gleiche Sprachsteuerung wie alle anderen Rollen, keine Einschränkung.
- Von Alice/LLM generierte Chat-Antworten und vom Nutzer eingegebener Text werden **nicht** übersetzt — nur die UI-Chrome (Buttons, Labels, System-/Fehlermeldungen) ist Teil dieser Spec.
- Backend-generierte Fehlermeldungen (z. B. von `alice-auth` bei ungültigen Login-Daten) sind aktuell teils hartkodiertes Deutsch und **nicht Teil dieser Spec** — nur clientseitige UI-Strings werden übersetzt; falls eine Backend-Fehlermeldung 1:1 durchgereicht wird, bleibt sie vorerst deutsch.
- Sprachwechsel während eines laufenden Chat-Streams (SSE aktiv): UI-Chrome darf sofort umschalten, ohne den laufenden Stream zu unterbrechen.
- Pluralisierung/Grammatik-Unterschiede zwischen Deutsch und Englisch (z. B. "1 Dokument gefunden" vs. "3 Dokumente gefunden") müssen pro Sprache korrekt behandelt werden, nicht nur wortwörtlich übersetzt.

## Technical Requirements (optional)
- Wahl der konkreten i18n-Bibliothek/-Architektur (z. B. Übersetzungsdateien pro Locale, Routing-Strategie) erfolgt in `/architecture` — hier nur die funktionale Anforderung: clientseitig umschaltbar, kompatibel mit dem aktuellen statischen Export, keine Server-Roundtrips für den reinen UI-Sprachwechsel.
- Erwartete Struktur: pro Sprache eine zentrale Übersetzungsressource (kein Text hartkodiert in `.tsx`-Dateien), damit eine dritte Sprache ohne Komponenten-Änderung ergänzt werden kann.
- Locale-abhängige Datums-/Zahlenformatierung zentral kapseln (nicht pro Komponente einzeln `toLocaleDateString` mit hartem Locale-String).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
App-weite Querschnitts-Änderung (kein neuer sichtbarer Komponenten-Baum):
+-- I18nProvider (neu, in app/layout.tsx neben ThemeProvider aus PROJ-60)
    +-- vor Login: navigator.language (Fallback Deutsch)
    +-- nach Login: user_profiles.preferences.sprache (bestehendes Feld)
+-- Übersetzungsressourcen: eine Datei je Sprache (de/en), nach Bereich strukturiert (auth, chat, sidebar, settings, vision)
+-- FlipCard.tsx: DOC_META_LABELS/EXTRA_META_LABELS/HIDDEN_META_KEYS wandern aus dem Komponenten-Code in die Übersetzungsressource (datengetrieben statt hartcodierter deutscher Maps)
```

#### B) Data Model

Kein neues DB-Feld — nutzt das bestehende `sprache`-Feld in `alice.user_profiles.preferences` (heute nur für Alices Antwortsprache verwendet, steuert künftig zusätzlich die UI-Sprache). Die Login-Screen-Spracherkennung (`navigator.language`) ist rein flüchtig — kein Persistieren vor dem Login.

#### C) Tech Decisions

- **Bibliothekswahl bewusst offen für `/frontend`:** Anforderung ist clientseitig umschaltbar, statischer-Export-kompatibel (kein Server-Roundtrip fürs UI-Sprachumschalten), eine zentrale Ressource je Sprache, automatischer Fallback auf Deutsch bei fehlendem Schlüssel (in der Lookup-Funktion selbst verankert, nicht pro Aufrufstelle). Konkrete Bibliothek (z. B. eine schlanke Key-Lookup-Lösung für React/Next mit statischem Export) wird beim Bauen entschieden — das ist Implementierungsdetail, keine Architekturentscheidung.
- **Locale-Formatierung zentral kapseln:** `formatMetaValue` in `FlipCard.tsx` nutzt heute hart `de-DE`. Datums-/Zahlenformatierung wandert in einen zentralen Helper, den alle Komponenten nutzen — vermeidet verstreute `toLocaleDateString`-Aufrufe mit hartem Locale-String.
- **Pluralisierung muss Teil der Bibliothekswahl sein:** Deutsch/Englisch unterscheiden sich grammatikalisch (z. B. „1 Dokument" vs. „3 Dokumente"), ein reiner Key-Ersetz-Ansatz ohne Plural-Regeln reicht nicht.
- **Sequenzierung nach PROJ-60:** Beide Specs berühren nahezu jede Komponentendatei (bereits als Dependency vermerkt) — Token-Migration und Text-Extraktion sollten als getrennte Diffs laufen, nicht als eine kombinierte Änderung pro Datei.
- **Abgrenzung zu PROJ-63:** Diese Spec öffnet nur die Frontend-Übersetzungsschicht. Das Sprache-Dropdown sollte seine Optionsliste, sobald verfügbar, aus PROJ-63s `GET /api/auth/languages` beziehen statt einer eigenen hartcodierten Liste — technisch unabhängig voneinander umsetzbar, aber bewusst kompatibel gehalten.

#### D) Dependencies

- Ein client-seitiges i18n-Paket (Auswahl bei `/frontend`, aus der Next.js-/React-Kategorie mit Unterstützung für statischen Export, z. B. `next-intl` oder `i18next` + `react-i18next`).

## QA Test Results

**Tested:** 2026-07-20
**Scope:** Static frontend code audit + production build. No live browser session (autonomous background run); behavior verified by reading source, tracing data flow, key-parity scripting, and `npm run build`. Cross-browser/responsive rendering not exercised at runtime — the change is a pure translation/formatting layer with no new layout, so visual regression risk is low, but this was not visually confirmed on Chrome/Firefox/Safari or at 375/768/1440px.
**Tester:** QA Engineer (AI, autonomous background session)

### What could / could not be executed
- **Executed:** `npm run build` (exit 0, clean); programmatic leaf-key parity diff of `de.ts` vs `en.ts` (437 keys each, zero asymmetry); repo-wide greps for legacy word-form literals, hardcoded German JSX text/attributes, locale-branching anti-patterns, role-gating, and `dangerouslySetInnerHTML`; full read of `config.ts`, `format.ts`, `I18nProvider.tsx`, both locale files, `ProfilForm.tsx`, `CreateUserDialog.tsx`, `FlipCard.tsx`, `LoginForm.tsx`, chat renderers, `useChatSessions.ts`, and the service layer.
- **Could NOT execute:** interactive browser testing (language toggle live, hydration flash, post-login switch visually), cross-browser and responsive checks — no runtime environment in this session.

### Acceptance Criteria Status

#### AC-1: All static UI texts translatable, de+en complete (Login, Chat, Sidebar, all Settings tabs+dialogs, Vision/FlipCard) — PARTIAL (see BUG-1)
- [x] `de.ts` and `en.ts` are structurally identical: 437 leaf keys each, 0 keys missing in either direction (scripted diff).
- [x] Login (`LoginForm`, `ChangePasswordForm`), Chat (input placeholders, tool-status fallback chip, typing, voice overlay, empty/loading states), Sidebar (rename/delete/context-menu/services/groups), all Settings tabs (Profile, DMS, Users, Voice Profiles, Mail, Chat Archive) and every dialog, Vision/FlipCard — all render via `t(...)`. Broad umlaut/ß grep across `components/` + `app/` JSX text nodes and `placeholder=`/`title=`/`aria-label=` literals returns zero hardcoded German UI strings.
- [ ] BUG: Client-constructed error strings thrown from the **service layer** (`services/api.ts` incl. `streamChat` SSE `onError`, `profileApi.ts`, `dms.ts`, `adminApi.ts`, `voiceApi.ts`, `fetchWithAuth.ts`) are hardcoded German and surface untranslated in English UI, because ~20 components render `err instanceof Error ? err.message : t(...)`. AC-1 explicitly lists "Fehlermeldungen" and Chat "Fehlerzustände" as in scope, and these are client-side strings (not backend pass-through, which the spec does allow to stay German). See BUG-1.

#### AC-2: Architecture open for a 3rd language without touching component code — PASS
- [x] Components call generic `t("key")`; no `if (locale === "de")` UI branching. The only `s === "de"` (CreateUserDialog:293) merely selects which translation *key* to pass to `t()`, not hardcoded text. Adding a locale = add a resource file + register it in `config.ts` `resources`; no component edits.

#### AC-3: `sprache` field drives both Alice's response language AND UI language (one field, one value) — PASS
- [x] `ProfilForm` saves the ISO code (`de`/`en`) via `updateProfile` → `PATCH /auth/profile` (consumed by PROJ-63 for Alice's reply language) and, on the same save, calls `i18n.changeLanguage(locale)` + persists the UI-locale hint. `I18nProvider` post-login reads `profile.preferences.sprache` and applies it. Single dropdown, single stored value.

#### AC-4: Pre-login follows `navigator.language`, German fallback for non-de/en — PASS
- [x] `detectBrowserLocale()` iterates `navigator.languages`, matches the 2-letter prefix for `de`/`en`, and returns `DEFAULT_LOCALE` ("de") for anything else (e.g. `fr`). Applied in `I18nProvider` when no token is present.

#### AC-5: Post-login immediately switches to saved preference even if it differs from login screen — PASS
- [x] `I18nProvider` effect: after cached/browser hint, if a token exists it calls `getProfile()` then `apply(spracheToLocale(profile.preferences.sprache))`; `apply` always `changeLanguage`s when the target differs. Override is unconditional.

#### AC-6: FlipCard label maps data-driven, not hardcoded — PASS
- [x] `DOC_META_LABELS`/`EXTRA_META_LABELS`/`HIDDEN_META_KEYS` now live in the locale files under `vision.docMeta`/`vision.extraMeta`/`vision.hiddenMetaKeys` and are read via `t(..., { returnObjects: true })`. No hardcoded German maps remain in `FlipCard.tsx`.

#### AC-7: Date formatting follows active locale — PASS
- [x] `FlipCard` imports `formatMetaValue` from the central `i18n/format.ts`, which formats via `intlLocale(i18n.language)` → `de-DE` vs `en-US`. No hardcoded `de-DE` remains in the component. `format.ts` also centralizes `formatDate`/`formatDateTimeShort`/`formatDateTimeFull`.

#### AC-8: `CreateUserDialog` still sets new user's initial `sprache` — PASS
- [x] `SPRACHE_OPTIONS = ["de","en"]`, state defaults to `"de"`, and `input.sprache` is included in the create payload. Dropdown labels render through `t("settings.profilForm.langDe"/"langEn")`, no raw code shown.

#### AC-9: Missing key → German fallback, never a raw key or `undefined` — PASS
- [x] `fallbackLng: "de"` resolves any key present in `de` but missing in `en` to the German value. `returnNull: false`. `parseMissingKeyHandler: () => ""` fires only when a key is absent in **all** locales (incl. the German source) and returns an empty string — never the technical key name, never `undefined`. In practice parity is 100%, so this path is only a safety net.

### Edge Cases Status
- [x] **EC missing key:** German fallback via `fallbackLng`; empty-string-not-raw-key on total miss. Handled.
- [x] **EC non-de/en browser (e.g. fr):** falls back to German. Handled.
- [x] **EC guest/child role parity:** no role-gating anywhere near the language control (grep clean). Same dropdown for all roles. Handled.
- [x] **EC LLM/user content NOT translated:** `UserMessage` renders `message.content` raw; `AssistantMessage` renders markdown children raw; FlipCard renders `result.summary`/`result.filename` raw; tool/status chips render backend `content` with only a generic translated *fallback*. No `t()` wraps message content. Handled.
- [~] **EC backend error 1:1 stays German:** allowed by spec — but note the separate BUG-1 concerns *client-side* hardcoded German, which the spec does treat as in scope.
- [x] **EC language switch mid-SSE stream:** `i18n.changeLanguage` touches only the i18next singleton; the stream is driven by refs (`abortRef`/`streamingSessionRef`) in `useChatSessions`, fully independent. No interruption. Handled (reasoned, not runtime-observed).
- [x] **EC pluralization:** `samplesCount_one`/`samplesCount_other` use the correct i18next plural-suffix convention and are called as `t("settings.voiceProfiles.samplesCount", { count })`. Not literal concatenation. Handled.

### Security Audit Results
- [x] **XSS via `interpolation.escapeValue: false`:** SAFE. No `dangerouslySetInnerHTML` exists anywhere in `src/`. All `t()` output (including interpolated `{{name}}`/`{{count}}`/`{{path}}`/`{{host}}`/`{{recipient}}`, some admin/user-controlled) is rendered as React text nodes, which React escapes at render regardless of the i18next escape setting. Disabling i18next escaping only avoids double-escaping; it does not open an injection vector here.
- [x] **No auth/authz changes:** this layer touches no auth flow, no RLS, no API route handlers. `getProfile()` in `I18nProvider` reuses the existing authenticated fetch and fails closed (keeps cached/browser language) on error.
- [x] **No secrets / env exposure:** no new env vars, no `NEXT_PUBLIC_` additions.
- **Verdict:** Pass — no security issues introduced.

### Regression Check (touched ~80 files, string-extraction pass)
- [x] Spot-checked `ProfilForm`, `CreateUserDialog`, `LoginForm`, `FlipCard`, chat renderers, `useChatSessions`: event handlers, props, conditional rendering, validation, and state logic are intact — only text moved to `t()` and date formatting moved to the central helper.
- [x] **Cross-feature consistency fix (coordinator) verified complete:** grep for `"deutsch"`/`"englisch"` string literals across `src/` (excluding locale display text) returns only `config.ts`, and only in `spracheToLocale`'s *read* path (accepting legacy pre-migration values) + doc comments. `localeToSprache` emits ISO only; `ProfilForm` state/Select use `de`/`en`; `CreateUserDialog` `SPRACHE_OPTIONS` are `de`/`en` with `t()` labels; `profileApi` types loosened to `string`. No file still emits the legacy word-form. `npm run build` passes after the fix.

### Bugs Found

#### BUG-1: Client-side service-layer error strings are hardcoded German (surface untranslated in English UI)
- **Severity:** Medium
- **Location:** `services/api.ts` (incl. `streamChat` `onError`: "Verbindung unterbrochen. Bitte erneut versuchen.", "Zu viele Anfragen -- bitte kurz warten.", "Unbekannter Fehler vom Server."), `services/profileApi.ts`, `services/dms.ts`, `services/adminApi.ts`, `services/voiceApi.ts`, `services/fetchWithAuth.ts`. Consumed by ~20 components via `err instanceof Error ? err.message : t(...)` and by `useChatSessions` chat `error` messages.
- **Steps to Reproduce:**
  1. Set profile language to English; UI switches to English.
  2. Trigger any client-side error path — e.g. lose connectivity and send a chat message, or fail a Settings save (network drop, 5xx).
  3. Expected: the error text appears in English (AC-1 lists "Fehlermeldungen"/Chat "Fehlerzustände" as translatable, and these are client-constructed, not backend pass-through).
  4. Actual: the raw German service string is shown (e.g. "Verbindung unterbrochen. Bitte erneut versuchen."), while the surrounding UI is English.
- **Impact:** Cosmetic/UX inconsistency on error paths only. No crash, no raw key, no `undefined` — degrades gracefully to readable German. Backend-passed-through detail strings (`body.detail`) are explicitly allowed to remain German by the spec; this bug is specifically about the *frontend-authored* fallback strings.
- **Priority:** Fix in next sprint. Move these strings into the locale files (e.g. `common.networkError`, `chat.streamInterrupted`, `chat.rateLimited`) and have services throw stable error *codes* (as `auth.ts`/`LoginForm` already do with `NETWORK_ERROR`/`RATE_LIMITED`) that components map to `t()`. Non-blocking.

#### BUG-2: `CreateUserDialog` email placeholder hardcoded, ANREDE/DETAILGRAD/ROLE option labels show raw values
- **Severity:** Low
- **Location:** `components/Settings/CreateUserDialog.tsx` — email `placeholder="nutzer@example.com"` (line 154); `ANREDE_OPTIONS`, `ROLES`, `DETAILGRAD_OPTIONS` render the raw code (`du`/`sie`, `admin`/`user`/…, `technisch`/`normal`/…) instead of `t()` labels, unlike the language dropdown which was localized.
- **Impact:** Minor — an admin-only dialog; the values are recognizable, and role/detailgrad codes are arguably data identifiers. The email placeholder is a German-domain example. Inconsistent with the localized language dropdown in the same dialog.
- **Priority:** Nice to have. Non-blocking.

### Summary
- **Acceptance Criteria:** 8/9 fully passed; AC-1 partial (error-state sub-clause) — logged as BUG-1.
- **Edge Cases:** 7/7 handled (1 noted with cross-reference to BUG-1).
- **Bugs Found:** 2 total (0 critical, 0 high, 1 medium, 1 low).
- **Security:** Pass — no XSS (React escapes all `t()` output; no `dangerouslySetInnerHTML`), no auth/RLS/env changes.
- **Build:** `npm run build` passes cleanly (exit 0).
- **Production Ready:** YES (with follow-up) — no critical/high bugs. BUG-1 (Medium) is an error-path i18n completeness gap that degrades gracefully to German; recommend fixing in a fast-follow but it does not block deployment.
- **Recommendation:** READY. Ship; schedule BUG-1 for the next sprint and BUG-2 at leisure.

## Deployment
_To be added by /deploy_
