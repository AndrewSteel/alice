# PROJ-66: Frontend — Granulares Rollen-Gating in Settings

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
