# PROJ-61: Vision Flip-Card Grid — Responsive Enlargement

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
