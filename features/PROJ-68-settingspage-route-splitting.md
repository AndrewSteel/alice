# PROJ-68: SettingsPage — Route-Splitting

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
