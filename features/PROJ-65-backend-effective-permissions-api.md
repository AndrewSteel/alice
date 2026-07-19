# PROJ-65: Backend — Effective-Permissions API & fehlende System-Flags

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Dependencies
- Requires: bestehendes Permission-Schema (`alice.permissions_system`, `alice.role_templates`, `alice.init_user_permissions`) aus Phase 1.
- Required by: PROJ-66 (Frontend Granular UI Gating) — konsumiert den hier spezifizierten Endpunkt.

## User Stories
- Als Frontend möchte ich für den eingeloggten Nutzer die effektiven System-Berechtigungen über einen einzigen Endpunkt abrufen können, statt clientseitig nur auf `user.role === "admin"` zu prüfen.
- Als Admin möchte ich, dass Nutzerverwaltung-, DMS- und Chatarchiv-Tab-Sichtbarkeit sowie Mailbox-Admin-Rechte jeweils über ein eigenes, spezifisches Permission-Flag gesteuert werden, statt implizit an ein unpassendes bestehendes Flag gebunden zu sein.
- Als bestehender Admin-Nutzer möchte ich nach dem Rollout weiterhin uneingeschränkten Zugriff auf DMS-Tab, Chatarchiv und Mailbox-Verwaltung haben, ohne manuell etwas umstellen zu müssen.

## Acceptance Criteria
- [ ] `alice.permissions_system` erhält drei neue Spalten: `can_manage_dms_folders`, `can_view_chat_archive`, `can_manage_mailboxes` (alle `BOOLEAN DEFAULT FALSE`).
- [ ] `alice.role_templates` wird für alle vier Rollen aktualisiert: `admin` → alle drei neuen Flags `true`; `user`/`guest`/`child` → alle drei `false` (identisch zum heutigen faktischen Verhalten, keine Verhaltensänderung).
- [ ] `alice.init_user_permissions()` schreibt die drei neuen Flags beim Anlegen/Aktualisieren eines Nutzers aus dem Rollen-Template (wie die bestehenden Flags).
- [ ] Migrationsskript setzt für **bestehende** Nutzer mit `role = 'admin'` alle drei neuen Flags rückwirkend auf `true`; alle anderen bestehenden Nutzer erhalten `false` (Default) — Bestandsverhalten bleibt unverändert.
- [ ] Neuer Endpunkt `GET /api/auth/permissions` (in `alice-auth`) liefert die effektiven `permissions_system`-Werte des per JWT authentifizierten Nutzers als JSON (alle 10 Flags: die 7 bestehenden + die 3 neuen).
- [ ] Endpunkt erfordert gültigen JWT (wie alle anderen `/api/auth/*`-Routen außer `/login`), liefert 401 ohne gültiges Token.
- [ ] Kein Permission-Eintrag für den Nutzer vorhanden (sollte durch `init_user_permissions` beim Login/Anlegen nicht vorkommen, aber als Fallback): Endpunkt liefert alle Flags als `false` statt eines Fehlers.

## Edge Cases
- Nutzer, dessen Rolle sich ändert (z. B. `user` → `admin`): bestehendes `init_user_permissions`-Verhalten (ON CONFLICT DO UPDATE) greift automatisch auch für die drei neuen Flags — keine Sonderbehandlung nötig.
- Migrationsskript läuft mehrfach (z. B. bei wiederholtem Deploy-Versuch): idempotent, überschreibt admin-Zeilen erneut mit `true`, keine Duplikate.
- Individuelle Abweichung vom Rollen-Template (z. B. ein `user`-Account bekommt manuell `can_manage_dms_folders=true` gesetzt): Es gibt aktuell **keine** UI zum Editieren einzelner `permissions_system`-Flags pro Nutzer — nur über direkten DB-Zugriff oder Rollenwechsel möglich. Diese Spec liefert keine neue Editor-UI, nur den Lese-Endpunkt.
- Endpunkt wird während eines laufenden Rollenwechsels (Race Condition zwischen Rollen-Update und Permission-Read) aufgerufen: liefert den zu diesem Zeitpunkt in der DB stehenden Wert, kein Locking nötig (seltener, nicht-kritischer Fall).

## Technical Requirements (optional)
- Endpunkt-Standort: `alice-auth` (Port wie bestehende `/api/auth/*`-Routen), analog zum Muster aus PROJ-63 (`GET /api/auth/languages`).
- Migrationsskript nach bestehendem Muster: `scripts/proj65-add-permission-flags.sh`.
- Keine neue UI zum Bearbeiten einzelner Permission-Flags — Scope ist ausschließlich Schema + Lese-Endpunkt.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
