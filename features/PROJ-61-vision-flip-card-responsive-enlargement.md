# PROJ-61: Vision Flip-Card Grid — Responsive Enlargement

## Status: Approved
**Created:** 2026-07-19
**Last Updated:** 2026-07-20

## Implementation Notes
- `FlipCardGrid.tsx`: `grid-cols-1 sm:grid-cols-2 lg:grid-cols-[repeat(auto-fill,minmax(min(420px,100%),1fr))]` — the `min(420px,100%)` clamp (instead of a plain `minmax(420px,1fr)`) prevents overflow when the container (e.g. PROJ-54's narrow split-screen text pane) is narrower than 420px.
- `FlipCard.tsx`: font sizes scaled per breakpoint/context (was uniform `text-xs`); summary icon button touch target raised from 24px to 44px (`h-11 w-11`, no responsive prefix).
- Deliberately frontend-only per the spec's own decoupling decision — existing 400×400 thumbnails render slightly upscaled until a future PROJ-55 backend follow-up regenerates them at 800×800; not a blocker.
- QA: READY, 0 blocking bugs. 1 Low/cosmetic bug (summary glyph renders ~16px instead of intended 20px due to a Button base-class CSS specificity override — touch target itself unaffected, icon size unchanged from before this PR). Recommend real-browser spot-check at 375/768/1440px + Safari `min()`-in-`minmax()` + live split-screen drag test before/after deploy.

## Dependencies
- Builds on PROJ-54 (Vision-Chat: Flip-Card Ergebnisansicht) — this spec changes the grid/sizing behavior of the existing `FlipCardGrid`/`FlipCard` components, not the underlying data or flip mechanic.
- Should land after PROJ-60 (Theming) so sizing changes are made directly against the new semantic tokens rather than being re-touched twice.
- **Blocked by a backend change to PROJ-55 (DMS Thumbnail-Generierung, Deployed):** Thumbnails are currently generated at a fixed 400×400px, sized for the old 2-column mobile layout. With this spec's larger cards (up to ~480px on desktop), source thumbnails need to be regenerated at a higher resolution (target: 800×800px) to stay crisp — this requires reopening PROJ-55 via `/refine PROJ-55` (thumbnailer container target size + re-running the backfill workflow for existing documents). Out of scope for this frontend spec; tracked here only as a hard dependency.

## User Stories
- Als Nutzer auf dem Smartphone (Portrait) möchte ich, dass jede Ergebnis-Karte die volle Bildschirmbreite nutzt, damit ich Thumbnail und Metadaten tatsächlich erkennen kann, statt sie nur zu erahnen.
- Als Nutzer auf dem Smartphone (Querformat) oder Tablet möchte ich zwei deutlich lesbare Karten pro Zeile statt vieler kleiner Karten.
- Als Desktop-Nutzer möchte ich spürbar größere Karten (min. 420–480px) als heute (min. 200px), damit ich Vorschau und Metadaten ohne Flip erfassen kann.
- Als Nutzer möchte ich, dass Schrift in den Karten (Dateiname, Metadaten, Zusammenfassung) proportional zur neuen Kartengröße mitwächst, statt weiterhin winzig zu bleiben.

## Acceptance Criteria
- [ ] Mobile Portrait (< 640px): Grid zeigt 1 Spalte, Karte nutzt die volle verfügbare Breite abzüglich Grid-Padding.
- [ ] Mobile Querformat und Tablet (≥ 640px, < 1024px oder äquivalenter Breakpoint): Grid zeigt 2 Spalten.
- [ ] Desktop (≥ 1024px): Grid nutzt `auto-fill` mit Mindestbreite 420–480px pro Karte (`minmax(420px, 1fr)` oder gleichwertig), Spaltenzahl ergibt sich automatisch aus der verfügbaren Breite (inkl. innerhalb des schmaleren 1/3-Split-Screen-Bereichs aus PROJ-54).
- [ ] Kartenhöhe ergibt sich weiterhin automatisch aus der Breite (Thumbnail bleibt 1:1-Quadrat via `aspect-square`, Header/Metadaten-/Icon-Leisten behalten ihr proportionales Verhältnis).
- [ ] Schriftgrößen in der Karte (Dateiname-Header, Metadaten-Zeilen, Zusammenfassungstext, Icon-Leiste) skalieren responsiv je Breakpoint (z. B. `text-sm`/`text-base` statt durchgängig `text-xs`), lesbar sowohl bei 1-spaltiger Mobile-Darstellung als auch bei den größeren Desktop-Karten.
- [ ] Touch-Ziele in der Icon-Leiste (z. B. "Zusammenfassung"-Button) sind auf allen Breakpoints mindestens 44×44px groß.
- [ ] Bestehende Randfälle aus PROJ-54 (0 Treffer, 50+ Treffer, fehlendes Thumbnail) bleiben mit dem neuen Layout funktional unverändert.
- [ ] Keine horizontale Scrollbar auf keinem der drei Baseline-Breakpoints (375/768/1440px).

## Edge Cases
- 50+ Treffer bei größeren Desktop-Karten (weniger Spalten als heute) → mehr vertikales Scrollen; keine Pagination/Virtualisierung in dieser Spec vorgesehen, nur Layout-Vergrößerung.
- Split-Screen-Modus (Vision 2/3 : Text 1/3) auf kleineren Desktop-Fenstern kann das Grid auf 1 Spalte reduzieren, sobald die verfügbare Breite unter 420px fällt — Grid muss dies ohne Overflow automatisch handhaben.
- Sehr lange Dateinamen oder Metadatenwerte bei größerer Schrift dürfen den Kartenrahmen nicht sprengen (weiterhin `truncate` mit Tooltip).
- Rotationswechsel auf Mobile (Portrait ↔ Querformat) während eine Karte geflippt ist: Flip-Zustand bleibt erhalten, Layout passt sich ohne Fehler an die neue Spaltenzahl an.
- Fehlendes Thumbnail (Platzhalterbild) muss bei größerem Format weiterhin proportional und ohne Verzerrung skalieren.
- Übergangsphase nach dem PROJ-55-Backfill (siehe Dependencies): Dokumente mit noch nicht neu generiertem Thumbnail zeigen vorübergehend das alte 400×400px-Bild im neuen, größeren Kartenformat — leichter Upscale, kein Fehlerzustand, kein Blocker für diese Spec.

## Technical Requirements (optional)
- Änderungen konzentrieren sich auf `FlipCardGrid.tsx` (Grid-Spalten/Breakpoints) und `FlipCard.tsx` (Schriftgrößen-Klassen, Touch-Ziel-Größen); keine Änderung an der 3D-Flip-Logik oder den Datenquellen.
- Grid-Spalten-Logik sollte auf Tailwind-Breakpoints (`sm:`/`lg:`) statt der aktuellen `sm:`/`md:`-Mischung aufgebaut werden, um mit den drei Baseline-Breakpoints (375/768/1440px) übereinzustimmen.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
VisionPanel
+-- FlipCardGrid (Grid-Container — hier ändern sich Spalten/Breakpoints)
    +-- FlipCard (×N — 3D-Flip-Mechanik unverändert)
        +-- Vorderseite: Thumbnail (aspect-square) + Metadaten + Icon-Leiste (Touch-Ziele ≥44×44px)
        +-- Rückseite: Weaviate-Schema-Felder je Dokumenttyp
        +-- Zusammenfassungs-Seite
```

#### B) Data Model

Keine Änderung — dieselben Suchergebnis-Objekte, derselbe Thumbnail-Endpunkt (`GET /api/dms/thumbnail/{uuid}`). Reine Layout-/Typografie-Änderung, keine neuen Felder.

#### C) Tech Decisions

- **Breakpoints auf die drei Baseline-Werte (375/768/1440px) ausgerichtet:** `FlipCardGrid.tsx` nutzt heute eine `sm:`/`md:`-Mischung (`grid-cols-2` → `sm:grid-cols-4` → `md:grid-cols-[...]`), die nicht exakt mit den getesteten Breakpoints übereinstimmt. Umstellung auf `sm:`/`lg:` behebt das strukturell, statt nur die Werte zu justieren.
- **Desktop-Spaltenzahl wird zum Browser-Nebeneffekt statt Festwert:** `minmax(200px,1fr)` → `minmax(420px,1fr)` mit `auto-fill` — die Spaltenzahl ergibt sich automatisch aus der verfügbaren Breite, inklusive innerhalb des schmaleren 1/3-Split-Screen-Textbereichs (PROJ-54), ohne dass eine feste Spaltenzahl je Fenstergröße gepflegt werden muss.
- **Schriftgrößen-Skalierung je Breakpoint** (`text-xs` → `text-sm`/`text-base`) statt eines durchgängigen Fixwerts, damit die größeren Karten nicht mit unverändert winziger Schrift wirken.
- **Abhängigkeit zu PROJ-55 (Thumbnail-Auflösung) ist entkoppelt:** Diese Spec liefert unabhängig aus; bis der 800×800px-Backfill (separat via `/refine PROJ-55`) läuft, wird das bestehende 400×400px-Bild leicht hochskaliert dargestellt — kein Fehlerzustand, kein Blocker für diesen Rollout.
- **Sequenzierung nach PROJ-60 (Theming):** Sizing-Änderungen sollten direkt gegen die neuen semantischen Tokens erfolgen, um `FlipCard.tsx`/`FlipCardGrid.tsx` nicht zweimal anzufassen (bereits als Dependency in der Spec vermerkt).

#### D) Dependencies

Keine neuen Pakete — reine Tailwind-Klassen-/Breakpoint-Änderung an bestehenden Komponenten.

## QA Test Results

**Tested:** 2026-07-20
**Tester:** QA Engineer (AI)
**Method:** Static / CSS-math verification + clean production build. No live browser available — real-browser spot-checks recommended below.
**Scope of change (verified via `git diff`):** Only `FlipCardGrid.tsx` (6 lines, grid classes) and `FlipCard.tsx` (18 lines, font-size + touch-target classes). Zero logic changes, zero backend/thumbnailer files touched.

### Acceptance Criteria Status

#### AC-1: Mobile Portrait (< 640px) → 1 column, full available width minus grid padding — PASS
- `grid-cols-1` applies below the `sm:` (640px) breakpoint. Single column = `1fr` = 100% of the content box.
- Container has `p-3` (12px) padding; card fills the remaining width. At a 375px container: content = 375 − 24 = 351px, card = 351px. No overflow.

#### AC-2: Mobile Landscape / Tablet (≥ 640px, < 1024px) → 2 columns — PASS
- `sm:grid-cols-2` applies from 640px and is overridden by `lg:` only at 1024px, so the 2-column band is exactly [640, 1024). Baseline 768px falls cleanly inside it.
- Tailwind `grid-cols-2` = `repeat(2, minmax(0,1fr))`; the `minmax(0,...)` floor guarantees columns shrink rather than overflow. At 768px: content 744px, minus one 12px gap = 732 / 2 = 366px per card. No overflow.

#### AC-3: Desktop (≥ 1024px) → auto-fill, min card width 420–480px, automatic column count (incl. narrow split-screen) — PASS
- `lg:grid-cols-[repeat(auto-fill,minmax(min(420px,100%),1fr))]`.
- At 1440px: content = 1440 − 24 = 1416px. `min(420px,100%)` → 420px floor. auto-fill = floor((1416+12)/(420+12)) = floor(1428/432) = 3 columns; each stretches to (1416 − 24)/3 = 464px — inside the 420–480 target. No overflow.
- Narrow split-screen (container content < 420px) handled by the `min(420px,100%)` clamp — see EC-2. Column count is a pure browser side-effect of available width; no fixed per-window count. Matches spec's Tech Decision.

#### AC-4: Card height automatic from width; thumbnail stays 1:1 `aspect-square` — PASS
- Thumbnail wrapper `aspect-square w-full` unchanged (FlipCard L92). Card is a `flex flex-col` in normal flow whose height derives from its contents; back face overlays via `absolute inset-0`. Flip/perspective styles untouched.

#### AC-5: Font sizes scale per breakpoint, legible at both extremes — PASS
- Filename header `text-sm lg:text-base`; front metadata bar `text-xs sm:text-sm`; back-face `MetadataRow` `text-sm`; details/summary headers `text-sm`; summary body `text-sm lg:text-base`. All migrated off the uniform `text-xs`. Diff confirms these are the only text-class changes.

#### AC-6: Icon-bar touch targets ≥ 44×44px on ALL breakpoints — PASS
- Summary button: `size="icon"` default `h-10 w-10` (40px) is overridden by `className="h-11 w-11"` (44px). Override is correct: `cn(buttonVariants({ variant, size, className }))` appends `className` AFTER the size default in the generated string, and tailwind-merge keeps the last class per property group → `h-11`/`w-11` win. Verified against `button.tsx`.
- `h-11 w-11` carries NO responsive prefix → 44×44px unconditionally on 375/768/1440 and everything between. Correct.

#### AC-7: Existing PROJ-54 edge cases still functional — PASS
- `VisionPanel.tsx` (0-result branch → `VisionEmptyState`; else `FlipCardGrid`) untouched. `ThumbnailImage.tsx` (skeleton/error-placeholder) untouched. `VisionEmptyState.tsx` untouched. Only the grid classes and card typography changed; the surrounding state machine is intact.

#### AC-8: No horizontal scrollbar at 375 / 768 / 1440px — PASS
- 375px: 1 column, card = content width (351px). No overflow.
- 768px: 2 columns via `minmax(0,1fr)` (floor 0) — cannot overflow.
- 1440px: 3 columns, total 3×420 + 2×12 = 1284 ≤ 1416 available; `1fr` distributes the remainder inside the box. No overflow.
- CSS math done manually rather than trusting the implementer's assertion; holds at all three.

### Edge Cases Status

#### EC-1: 50+ results → more vertical scroll, no pagination expected — PASS
- Grid renders all results; scroll container is `VisionPanel`'s `flex-1 overflow-y-auto`. No pagination/virtualization was added (none required by spec). Larger cards simply mean fewer columns / more vertical scroll, as intended.

#### EC-2: Split-screen narrower than 420px → single column, no overflow — PASS (key claim verified with gap+padding accounted for)
- With container content < 420px, `min(420px,100%)` resolves `100%` to the grid content-box width, so the track floor becomes the container width, not 420px. auto-fill then yields exactly 1 column sized to `1fr`.
- Worked example, container 400px: content = 400 − 24 (`p-3`) = 376px → `min(420,376)` = 376 → floor((376+12)/(376+12)) = 1 column = 376px. No overflow. A plain `minmax(420px,1fr)` would have forced a 420px track into a 376px box → horizontal overflow. The `min()` clamp is the fix and it holds even after `p-3` padding and `gap-3` are subtracted.

#### EC-3: Long filenames / metadata at larger font don't blow out the card — PASS
- Filename header keeps `truncate` + `title={result.filename}` tooltip (L86). Front metadata bar keeps `truncate` (L101). Back-face `MetadataRow` value keeps `truncate` (L24). Font-size bumps did not remove any truncation.

#### EC-4: Device rotation mid-flip preserves flip state — PASS
- Flip state lives in `FlipCardGrid` `faces` (keyed by uuid) and is passed as a controlled prop; rotation is a viewport resize, not a remount, so state survives. Flip-state logic untouched by the diff.

#### EC-5: Missing-thumbnail placeholder scales proportionally — PASS
- On fetch error, `ThumbnailImage` returns a `bg-muted` div with the same `w-full h-full className` inside FlipCard's `aspect-square w-full` wrapper, so the placeholder occupies the identical square box as a real thumbnail and scales identically. Centered `FileText` glyph, no distortion.

#### EC-6: PROJ-55 thumbnail-resolution transition (400×400 upscaled) — OUT OF SCOPE (per spec)
- Documented in spec Tech Design as acceptable/decoupled. Not evaluated as a defect.

### Security Audit Results

Pure CSS/Tailwind class-name change — no data flow, auth, input handling, or new network calls introduced. Existing `ThumbnailImage` fetch (Bearer token from `getToken()`, `encodeURIComponent(uuid)`) is unchanged. No injection / auth-bypass / data-leak surface added.
- **Security verdict: PASS (no new surface).**

### Bugs Found

#### BUG-1: Summary icon glyph likely renders at 16px, not the intended 20px (cosmetic, non-blocking)
- **Severity:** Low
- **Steps to Reproduce:**
  1. Open a Vision result card and inspect the summary (Sigma) icon inside the icon bar.
  2. Expected (implementer intent): 20px glyph (`h-5 w-5`).
  3. Actual (predicted): ~16px glyph. The Button base class `[&_svg]:size-4` compiles to a descendant selector `.[&_svg]:size-4 svg { width/height: 1rem }` with specificity (0,1,1), which outranks the utility `.h-5`/`.w-5` (0,1,0) applied directly on the SVG. Same cascade layer, so higher specificity wins → 16px.
- **Impact:** None on any acceptance criterion. The 44×44px touch target (AC-6) is fully satisfied because that lives on the button element, not the glyph. This is purely the icon-enlargement intent being partially neutralized. Note: the pre-existing `h-3.5 w-3.5` was subject to the same override, so the observable icon size is effectively unchanged by this PR.
- **Priority:** Nice to have (confirm visually in browser; if a larger glyph is desired, use `[&_svg]:h-5` `[&_svg]:w-5` on the Button or bump via the size variant).

### Recommended real-browser spot-checks before deploy
Implementer's implied checks are covered; the full pre/post-deploy list a human should run:
1. Chrome / Firefox / Safari at 375, 768, 1440px — confirm 1 / 2 / auto-fill columns and zero horizontal scrollbar (Safari in particular for `min()` in a grid `minmax()` track — well supported since Safari 14, but verify).
2. PROJ-54 split-screen: drag the Vision/Text divider until the Vision pane content width drops below ~420px and confirm the grid collapses to 1 column with no overflow (EC-2).
3. Flip a card, then rotate a real phone Portrait↔Landscape and confirm the flip state and layout survive (EC-4).
4. A result with a missing thumbnail (force a 404) — confirm the placeholder fills the full square (EC-5).
5. A very long filename and long metadata values — confirm truncation + hover tooltip at the larger font (EC-3).
6. Visually confirm BUG-1 (icon glyph size) and decide if it needs a follow-up.
7. Light and dark theme (PROJ-60) — confirm semantic tokens still read correctly at the new font sizes.

### Summary
- **Acceptance Criteria:** 8/8 passed.
- **Edge Cases:** 5/5 in-scope passed (1 explicitly out of scope).
- **Bugs Found:** 1 total (0 critical, 0 high, 0 medium, 1 low — cosmetic icon glyph size).
- **Security:** PASS (no new surface).
- **Build:** `npm run build` passes cleanly (Next.js 15.5.12, compiled + type-checked, no errors/warnings).
- **Regression:** 3D-flip mechanic, perspective/transform styles, and data-fetching logic confirmed untouched (`git diff` = class-name changes only). No backend/thumbnailer files touched.
- **Production Ready:** YES.
- **Recommendation:** Deploy. The single Low bug is cosmetic and does not violate any acceptance criterion; address it as an optional follow-up. Complete the browser spot-checks above post-deploy.

## Deployment
_To be added by /deploy_
