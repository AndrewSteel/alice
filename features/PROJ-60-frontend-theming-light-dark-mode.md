# PROJ-60: Frontend Theming — Light/Dark Mode Switch

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
