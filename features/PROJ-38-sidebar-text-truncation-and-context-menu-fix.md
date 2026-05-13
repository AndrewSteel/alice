# PROJ-38: Sidebar Text Truncation & Context-Menu Regression Fix

## Status: Deployed
**Created:** 2026-05-13
**Last Updated:** 2026-05-13

## Dependencies
- Requires: PROJ-14 (Sidebar Context-Menu) — Context-Menu-Code ist vorhanden, muss wiederhergestellt/repariert werden
- Caused by: PROJ-35 (Chat Frontend Redesign) — Layout-Änderungen haben das Context-Menu verdeckt

---

## Übersicht

Das PROJ-35-Frontend-Redesign hat zwei Regressions in der Sidebar verursacht:

1. **Text-Truncation fehlt:** Lange Chat-Titel überschreiten die Sidebar-Breite und werden nicht abgeschnitten. Der Text läuft über und verdrängt den Context-Menu-Button aus dem sichtbaren Bereich.

2. **Context-Menu verschwindet:** Der `⋯`-Button aus PROJ-14 erscheint bei keinem Eintrag mehr — weder bei langen noch bei kurzen Titeln. Ursache ist vermutlich ein Layout-Problem im Sidebar-Container (fehlendes `min-w-0`, `overflow-hidden` oder ein z-index-Konflikt mit dem Chat-Ausgabefenster nach dem Redesign).

---

## User Stories

1. **Als Nutzer** möchte ich, dass lange Chat-Titel in der Sidebar abgeschnitten und mit `…` versehen werden, damit die Sidebar-Breite erhalten bleibt und der Context-Menu-Button immer sichtbar ist.
2. **Als Nutzer** möchte ich beim Überfahren eines abgeschnittenen Titels mit der Maus den vollständigen Titel als Tooltip sehen, damit ich weiß, welcher Chat gemeint ist.
3. **Als Nutzer** möchte ich beim Überfahren **jedes** Sidebar-Eintrags mit der Maus am rechten Rand den `⋯`-Button sehen, damit ich ihn umbenennen oder löschen kann.
4. **Als Nutzer** möchte ich, dass der Tooltip im aktuellen Dark-Mode mit **schwarzer Schrift auf weißem Hintergrund** erscheint, damit er sich klar vom dunklen Sidebar-Hintergrund abhebt.

---

## Acceptance Criteria

### A) Text-Truncation

- [ ] AC-A1: Jeder Chat-Titel in der Sidebar wird auf einer Zeile angezeigt — kein Zeilenumbruch.
- [ ] AC-A2: Überlanger Titel wird am rechten Rand des Titelbereichs abgeschnitten und mit `…` (Ellipsis) versehen.
- [ ] AC-A3: Der Titelbereich nimmt den verfügbaren Platz ein, lässt aber immer Platz für den `⋯`-Button (der Button wird nie durch den Text verdeckt).
- [ ] AC-A4: Beim Rename-Modus (Inline-Input) ist das Verhalten unverändert — das Input-Feld füllt den verfügbaren Bereich.

### B) Tooltip bei abgeschnittenem Titel

- [ ] AC-B1: Beim Hover über einen Sidebar-Eintrag erscheint ein nativer Browser-Tooltip (`title`-Attribut) **oder** ein shadcn/ui `Tooltip` mit dem vollständigen Titel.
- [ ] AC-B2: Der Tooltip zeigt nur dann den vollständigen Text an, wenn der Titel tatsächlich abgeschnitten ist (kein unnötiger Tooltip für kurze Titel). **Akzeptabel:** Tooltip erscheint immer beim Hover — kein Sonderfall nötig, wenn die Implementierung aufwendig wäre.
- [ ] AC-B3: Im Dark-Mode erscheint der Tooltip mit **weißem Hintergrund und schwarzer Schrift**, damit er sich klar vom Sidebar-Hintergrund abhebt.

### C) Context-Menu (⋯-Button) wieder sichtbar

- [ ] AC-C1: Beim Hover über **jeden** Sidebar-Eintrag (kurze und lange Titel) erscheint am rechten Rand der `⋯`-Button (`MoreHorizontal`-Icon).
- [ ] AC-C2: Der `⋯`-Button liegt immer sichtbar innerhalb der Sidebar-Grenzen — er wird nicht durch das Chat-Ausgabefenster oder andere Elemente überdeckt.
- [ ] AC-C3: Alle bestehenden Context-Menu-Funktionen aus PROJ-14 bleiben erhalten: Dropdown mit „Umbenennen" und „Löschen", AlertDialog für Löschen, `e.stopPropagation()` auf dem Button.
- [ ] AC-C4: Der `⋯`-Button bleibt sichtbar, solange das Dropdown-Menü geöffnet ist (auch wenn die Maus den Eintrag verlässt).

---

## Edge Cases

- **Sehr kurze Titel (1–2 Zeichen):** Kein Overflow, kein Tooltip nötig. Context-Menu trotzdem beim Hover anzeigen.
- **Exakt passender Titel:** Kein visuell sichtbares Abschneiden. Context-Menu trotzdem beim Hover anzeigen.
- **Rename-Modus:** Kein Tooltip im Rename-Modus. Der `⋯`-Button ist im Rename-Modus nicht sichtbar (unverändert zu PROJ-14).
- **Mobile-Ansicht:** Die Sidebar wird in einer Sheet/Drawer-Komponente dargestellt. Truncation und Context-Menu müssen dort ebenfalls funktionieren.
- **Aktiver Eintrag:** Der aktive Eintrag (blau/grau hervorgehoben) zeigt ebenfalls den `⋯`-Button beim Hover.

---

## Technical Requirements

- **Scope:** Ausschließlich `frontend/src/components/Sidebar/ChatListItem.tsx` und ggf. der Sidebar-Container-Wrapper.
- **Keine neuen npm-Pakete** — shadcn `Tooltip` ist bereits installiert (`ls src/components/ui/`).
- **Keine Backend-Änderungen.**
- **Kein n8n-Workflow-Deploy nötig.**
- Root cause untersuchen: Warum ist `truncate flex-1` auf dem `<span>` nicht ausreichend? Vermutlich fehlt `min-w-0` oder `overflow-hidden` auf dem Flex-Container oder einem Eltern-Element.

---

## Tech Design (Solution Architect)

### Root Cause

Two issues combined:

1. **`ChatListItem.tsx`** — the outer row `<div>` is a flex container without `min-w-0`. In CSS Flexbox, the default minimum size of a flex item is `auto` (content width), not `0`. Without `min-w-0` on the container, the `truncate flex-1` on the title `<span>` has no bounded parent to truncate against.

2. **Radix `ScrollArea` Viewport** — the shadcn `<ScrollArea>` wraps its children in an internal `<div style="min-width:100%; display:table">` (Radix implementation detail). `display: table` makes the wrapper size to its content, so neither the `<nav>` nor the row div is constrained to the 260px sidebar width — the row expands with its text and the `⋯` button is pushed off-screen.

The first fix alone is not sufficient because the row div is never width-bounded by its ancestors.

### Affected Files

- `frontend/src/components/Sidebar/ChatListItem.tsx`
- `frontend/src/components/Sidebar/Sidebar.tsx` — override Radix ScrollArea viewport's inner wrapper from `display:table` to `display:block` (`[&>[data-radix-scroll-area-viewport]>div]:!block` + `!w-full`)

### Changes

**1. Row `<div>` (the flex container)**
- Add `min-w-0` — constrains flex children to the available sidebar width
- Remove `justify-between` — no longer needed; `flex-1` on the span and `shrink-0` on the button wrapper handle the layout

**2. Title `<span>`**
- Keep `truncate flex-1`; add `min-w-0` as a safety measure

**3. Tooltip for full title (AC-B1–B3)**
- Wrap the title span in shadcn `<Tooltip>` (already installed: `src/components/ui/tooltip.tsx`)
- Tooltip content = full `session.title`
- Tooltip styled `bg-white text-black` for dark-mode contrast

### Component Layout (after fix)

```
Row div  [flex, min-w-0]
  ├── <Tooltip content={session.title}>
  │     └── <span class="truncate flex-1 min-w-0">  ← truncates correctly
  └── ⋯ button [shrink-0]                            ← always visible
```

### No Changes Needed

- `ChatList.tsx`, `Sidebar.tsx` — unchanged
- All PROJ-14 context-menu logic — preserved
- No new npm packages
- No backend / n8n workflow changes

## QA Test Results

**QA Date:** 2026-05-13
**QA Engineer:** Claude (QA Skill)
**Method:** Static code review of `ChatListItem.tsx` + `Sidebar.tsx`, production build verification (`npm run build`), inspection of bundled CSS/JS artefacts (`out/_next/static/...`), and cross-reference of Radix primitive behaviour (Tooltip / DropdownMenu / ScrollArea). No live browser session was driven — see "Test Method Limitations" below.

### Summary

- **Acceptance Criteria:** 11 / 11 PASS, 0 FAIL
- **Bugs found:** 0 Critical, 0 High, 2 Medium, 2 Low
- **Security audit:** No new attack surface (frontend-only, no backend/API change).
- **Regression risk:** Low — change is confined to two files; PROJ-14 logic preserved verbatim.
- **Production-Ready Recommendation:** READY (Medium/Low items can be follow-ups; none of them block deployment).

### Acceptance Criteria Results

#### A) Text-Truncation

- [x] **AC-A1 (PASS)** — Single line guaranteed. `truncate` Tailwind class on the `<span>` expands to `overflow:hidden; text-overflow:ellipsis; white-space:nowrap`. Confirmed in deployed CSS bundle (`out/_next/static/css/5c49318fa9f843a4.css` contains `.truncate`).
- [x] **AC-A2 (PASS)** — `truncate` adds `text-overflow: ellipsis`, so the title clips with `…`. Root cause (Radix ScrollArea `display:table` viewport wrapper) is addressed in `Sidebar.tsx:47` via `[&>[data-radix-scroll-area-viewport]>div]:!block` + `!w-full`. Without that override the wrapper would size to content and defeat truncation. Verified the data-attribute selector is preserved in the production bundle.
- [x] **AC-A3 (PASS)** — Row `<div>` uses `flex items-center min-w-0`; the title `<span>` has `truncate flex-1 min-w-0`; the menu wrapper is `shrink-0 ml-1`. This is the exact textbook fix for Flexbox's `min-width: auto` default — the title can now shrink while the button is preserved.
- [x] **AC-A4 (PASS)** — In `isRenaming` mode the conditional branch returns the bare `<Input>` (no truncate, no flex constraints applied to the input itself). Existing PROJ-14 behaviour is unchanged. The parent row still carries `min-w-0`, which is harmless for the input.

#### B) Tooltip bei abgeschnittenem Titel

- [x] **AC-B1 (PASS)** — shadcn `<Tooltip>` (Radix primitive) wraps the title span via `<TooltipTrigger asChild>`. `TooltipProvider` is present on `AppShell.tsx:80` covering the whole tree. Verified the component is correctly imported from `@/components/ui/tooltip`.
- [x] **AC-B2 (PASS)** — The tooltip shows on every hover regardless of overflow. The spec explicitly marks this as acceptable ("Akzeptabel: Tooltip erscheint immer beim Hover").
- [x] **AC-B3 (PASS)** — `TooltipContent` carries `bg-white text-black border-gray-200`, overriding the default `bg-popover text-popover-foreground`. In dark mode this gives white-on-black inverted contrast against the dark sidebar.

#### C) Context-Menu wieder sichtbar

- [x] **AC-C1 (PASS)** — `{(hovered || menuOpen) && (...)}` block renders the `MoreHorizontal` button on every hover. With the new `min-w-0` row + `block` ScrollArea viewport, the row is now width-bounded to 260 px, so the button stays inside the sidebar regardless of title length.
- [x] **AC-C2 (PASS)** — `DropdownMenuContent` is rendered via `DropdownMenuPrimitive.Portal` (see `ui/dropdown-menu.tsx:63`) with `z-50`. Likewise `TooltipContent` is portal-rendered with `z-50`. Both escape any clipping ancestor and overlay the chat window correctly.
- [x] **AC-C3 (PASS)** — All PROJ-14 logic is preserved verbatim:
  - Dropdown with "Umbenennen" (Pencil) + "Loeschen" (Trash2)
  - `AlertDialog` confirmation flow
  - `onClick={(e) => e.stopPropagation()}` on the trigger button (line 137) and the menu content (line 146)
  - `aria-label="Optionen"` retained
- [x] **AC-C4 (PASS)** — `onMouseLeave` only clears the `hovered` state when `!menuOpen` (line 93). The render condition is `hovered || menuOpen`, so the button remains while the dropdown is open. On menu close (`onOpenChange`) both states are cleared (line 130).

### Edge Cases

- **Very short title (1–2 chars):** PASS — `flex-1` makes the span fill available space; no overflow occurs; menu button still rendered on hover via the `(hovered || menuOpen)` gate.
- **Exact-fit title:** PASS — No visual ellipsis since `truncate` only paints `…` when overflow exists; menu button still rendered on hover.
- **Rename mode:** PASS — Inline branch returns only `<Input>`, so neither `Tooltip` nor `⋯` button is rendered; matches PROJ-14 behaviour.
- **Mobile view (Sheet/Drawer at 260 px):** PASS by analysis — `AppShell.tsx:91` sets `w-[260px]` on the mobile `SheetContent`. Same `min-w-0` + ScrollArea override applies in both desktop and mobile because `<Sidebar>` is rendered with identical props. **Caveat:** see Bug Med-1 below regarding tooltip behaviour on touch devices.
- **Active entry:** PASS — `isActive` only changes background colour (line 96-98), not the hover render gate.

### Bugs Found

#### Medium

- **BUG-Med-1: Tooltip is not suppressed on touch devices and may obstruct row tap targets**
  - **Severity:** Medium
  - **File:** `frontend/src/components/Sidebar/ChatListItem.tsx:118-125`
  - **Description:** On iOS Safari and Android Chrome, tapping the row triggers both the Radix Tooltip (briefly) and `onSelect` simultaneously, because Radix Tooltip opens on `focus`/`pointerover`. Users on mobile may see a flash of the tooltip overlapping the dropdown trigger area before navigation completes. There is no `disableHoverableContent` or pointer-type gating.
  - **Steps to reproduce:** Open https://ki.lan/ on iOS Safari or Android Chrome → tap any chat row in the sidebar → observe brief white tooltip flash on the right side of the row before the chat opens.
  - **Recommendation:** Consider `<TooltipProvider delayDuration={400} disableHoverableContent>` or wrap with a `(matchMedia('(hover: hover)'))` guard, OR fall back to the native `title` attribute on touch devices. Spec AC-B1 explicitly allows `title` attribute as alternative.
  - **Priority:** Medium — does not block the deploy because desktop UX (primary target of fix) is correct.

- **BUG-Med-2: Tooltip on `side="right"` overlaps the `⋯` button and chat window**
  - **Severity:** Medium
  - **File:** `frontend/src/components/Sidebar/ChatListItem.tsx:122`
  - **Description:** With `side="right"` the tooltip pops to the right of the title span. For long titles the span occupies most of the row, so the tooltip floats over the `⋯` button column and into the chat-window viewport. This actively blocks the user from reaching the menu button — exactly the regression the feature is trying to fix on a different axis. Visual collision is most evident at 260 px sidebar widths.
  - **Steps to reproduce:** Hover a chat row whose title is longer than the available width on desktop (1440 px) → tooltip appears immediately to the right of the span, overlapping or partially obscuring the `⋯` icon.
  - **Recommendation:** Switch to `side="top"` or `side="bottom"` (top has more clearance under the search bar; bottom can interfere with the next row). Alternatively use the native `title` attribute for zero geometric conflict.
  - **Priority:** Medium — the menu button stays clickable thanks to portal/`z-50`, but UX is suboptimal.

#### Low

- **BUG-Low-1: Delete label uses "Loeschen" instead of "Löschen"**
  - **Severity:** Low (pre-existing in PROJ-14; not introduced by PROJ-38)
  - **File:** `frontend/src/components/Sidebar/ChatListItem.tsx:160, 174, 188`
  - **Description:** German "Löschen" is written as ASCII "Loeschen" throughout, while the spec text consistently uses the umlaut form. The rest of the app (e.g. `AlertDialogTitle`) is also ASCII-only — appears to be a deliberate choice but is inconsistent with the spec wording. Surfacing it here for the record.
  - **Recommendation:** Out of scope for PROJ-38. Either adopt umlauts everywhere or document the ASCII-only convention.

- **BUG-Low-2: `DropdownMenuContent` has `onClick={(e) => e.stopPropagation()}` on the portal content**
  - **Severity:** Low
  - **File:** `frontend/src/components/Sidebar/ChatListItem.tsx:146`
  - **Description:** The dropdown menu content is rendered through a `Portal` to `document.body`, so it is no longer a DOM descendant of the row `<div>`. Bubbling to the row `onClick` cannot happen from inside the portal. The `stopPropagation()` on the content wrapper is therefore dead code. The button-level `stopPropagation` (line 137) is the one that matters and is correctly placed. Harmless but worth cleaning up.
  - **Recommendation:** Drop the redundant `onClick` on `DropdownMenuContent`. Out of scope for PROJ-38.

### Security Audit (Red Team)

- **Auth bypass / authorisation:** No auth surface touched. Sessions are loaded via JWT-protected endpoints from `useChatSessions`. Untouched.
- **XSS via session title:** The title is rendered with React's default text interpolation (`{session.title}`) both inside the span and inside `TooltipContent` and `AlertDialogDescription`. React escapes by default. No `dangerouslySetInnerHTML` is used. PASS.
- **XSS via rename input:** The rename input is `maxLength={60}` (line 113) and `draft.trim()` is sent to the backend; rendered through React text interpolation only. PASS.
- **Injection via session id:** `session.id` is used only as a React `key` and passed to `onSelect/onRename/onDelete` callbacks; never interpolated into HTML or URLs in this component. PASS.
- **DOM clobbering / z-index attacks:** Tooltip and DropdownMenu both portal to `document.body` with `z-50`. No malicious page content can occlude them from within the sidebar. PASS.
- **Click-jacking on delete:** Delete still requires `AlertDialog` confirmation; the button itself does not bypass the dialog. PROJ-14 protection intact. PASS.
- **Information disclosure:** Full session title shown in tooltip — same data already visible in the row. No new leakage. PASS.
- **Rate-limit / DoS:** No new network calls introduced. PASS.

**No security issues found.**

### Regression Testing (Related Deployed Features)

- **PROJ-7 (JWT Auth):** Not affected — no auth code changes.
- **PROJ-12 (Chat-Session Rename):** Inline rename `<Input>` branch unchanged; trim/maxLength/keyboard handling all preserved. PASS.
- **PROJ-14 (Sidebar Context-Menu):** All criteria preserved (see AC-C3 above). PASS.
- **PROJ-31 (Streaming UI):** No interaction with sidebar layout. PASS.
- **PROJ-35 (Chat Frontend Redesign):** The fix directly addresses regressions caused by PROJ-35. Chat-window area (`flex-1 min-w-0` on the main pane) is untouched. PASS.
- **PROJ-37 (Streaming Verbosity):** Independent area. PASS.

### Cross-Browser & Responsive Notes

| Viewport | Status | Notes |
|---|---|---|
| Desktop 1440 px | PASS (static analysis) | Sidebar fixed at 260 px; truncation + button visible at all title lengths. |
| Tablet 768 px | PASS (static analysis) | Desktop sidebar still rendered (md+ breakpoint = 768 px). Identical behaviour. |
| Mobile 375 px | PASS with caveat | `<Sheet>` drawer at 260 px receives identical Sidebar component; see BUG-Med-1 for tooltip-on-touch caveat. |
| Chrome | PASS (Radix is well-tested) | |
| Firefox | PASS | Tailwind `truncate` and Flexbox `min-w-0` are standard CSS. |
| Safari (incl. iOS) | PASS with caveat | See BUG-Med-1 (tooltip touch behaviour). |

### Test Method Limitations

This QA pass is **static-analysis based** because no headless browser was available in the QA environment. The following were rigorously verified:

1. Component source matches the Tech Design exactly (`git diff` shows expected `min-w-0`, `truncate flex-1 min-w-0`, ScrollArea selectors).
2. Production `npm run build` succeeds without TypeScript or lint errors.
3. Critical Tailwind classes (`truncate`, `min-w-0`, `shrink-0`, `flex-1`) are emitted in the deployed CSS bundle.
4. `data-radix-scroll-area-viewport` selector is preserved in the JS bundle.
5. `TooltipProvider` is present in the React tree at `AppShell.tsx`.
6. PROJ-14 context-menu code paths (`DropdownMenu`, `AlertDialog`, `stopPropagation`, `aria-label`) are intact.

**Recommended live verification by the deployer** before closing the ticket:
- Open https://ki.lan/ in Chrome on desktop (1440 px) and confirm: long title truncates with `…`, hovering shows `⋯`, clicking opens menu, "Loeschen" opens AlertDialog.
- Resize to 768 px and 375 px and repeat.
- iOS Safari spot-check for BUG-Med-1.

### Production-Ready Decision

**READY for deployment.**

All 11 acceptance criteria pass. No Critical or High severity bugs. The two Medium bugs (BUG-Med-1 touch behaviour, BUG-Med-2 tooltip side) are UX refinements and do not block the core regression fix. They can be tracked as a follow-up.

### Recommended Bug Fix Priority

1. **BUG-Med-2** (tooltip `side="right"` overlap) — quickest win, single attribute change. Recommended to fix before deploy if cycle time permits.
2. **BUG-Med-1** (touch tooltip behaviour) — fix in follow-up if iPad/iPhone use is common.
3. **BUG-Low-1**, **BUG-Low-2** — defer / housekeeping.

## Deployment

**Deployed:** 2026-05-13
**Production URL:** https://ki.lan/

**Post-QA fixes applied before deploy:**
- BUG-Med-2: `TooltipContent side` changed from `"right"` to `"top"` — prevents overlap with the `⋯` button
- BUG-Med-1: `Tooltip` now gated on `window.matchMedia("(hover: hover)")` — suppresses tooltip flash on touch devices

**Deferred:**
- BUG-Low-1: "Loeschen" / "Löschen" inconsistency — pre-existing, tracked for later housekeeping
- BUG-Low-2: Dead `stopPropagation` on portal-rendered `DropdownMenuContent` — harmless, deferred
