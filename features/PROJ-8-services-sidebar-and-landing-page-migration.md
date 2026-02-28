# PROJ-8: Services Sidebar & Landing Page Migration

## Status: Deployed
**Created:** 2026-02-28
**Last Updated:** 2026-02-28

## Dependencies
- Requires: PROJ-7 (JWT Auth / Login Screen) — Sidebar structure already exists; UserCard and AppShell are in place

## Context

The system currently has two separate entry points:

1. **Old landing page** — `docker/compose/infra/nginx/html/index.html`
   A plain HTML page with service cards linking to n8n, Open WebUI, Home Assistant, HA Dev, Kanboard, Jupyter, and Finance Upload.

2. **Alice React app** — deployed at `docker/compose/infra/nginx/html/` (root, no `basePath`)
   The new primary interface for Alice (chat, auth, sidebar).

The goal is to consolidate these by migrating the service links into the Alice sidebar and replacing the old landing page with the Alice app.

---

## User Stories

- As a user opening the landing page, I want to be taken directly to the Alice interface, so that Alice is the primary entry point into the system.
- As a user inside Alice, I want to open external services (n8n, Home Assistant, etc.) directly from the sidebar, so that I don't need a separate landing page to navigate to them.
- As a user, I want Finance Upload to remain accessible via a sidebar link, so that I can still reach it while it is waiting for its own React-based replacement.
- As a user clicking a service link, I want it to open in a new browser tab, so that I don't lose my current Alice session.

---

## Acceptance Criteria

### Sidebar — Service Links Section
- [ ] A "Services" section is visible in the Alice sidebar, below the chat list and above the UserCard
- [ ] The section contains one button/link per service: n8n, Open WebUI, Home Assistant, HA Development, Kanboard, Jupyter, Finance Upload
- [ ] Each button displays an appropriate icon (from `lucide-react`) and a short label
- [ ] Clicking any service link opens the target URL in a new browser tab (`target="_blank" rel="noopener noreferrer"`)
- [ ] Finance Upload link targets `/finance_upload/index.html` (relative path, not an external domain)
- [ ] All other service links use their respective `https://*.happy-mining.de` URLs
- [ ] The section heading "Services" is clearly visually separated from the chat list above it
- [ ] Styling is consistent with the existing dark sidebar theme (gray-900 background, gray-100 text, hover:bg-gray-700)
- [ ] The section is accessible: all links have `aria-label` attributes

### Landing Page Replacement
- [ ] `docker/compose/infra/nginx/html/index.html` is replaced by the Alice React app's built `index.html`
- [ ] The React app's static assets (`_next/`) are deployed to the nginx html root
- [ ] The `finance_upload/` directory and all its contents are untouched
- [ ] After the change, navigating to `alice.happy-mining.de` directly loads the Alice React login/chat screen

### Deployment
- [ ] All changed files are placed under `docker/compose/infra/nginx/html/` (local)
- [ ] Changes are synced to the server via `./sync-compose.sh`
- [ ] No nginx container restart is required or performed

---

## Services to Migrate

| Label | URL / Path | Icon (lucide-react) |
|---|---|---|
| n8n | `https://n8n.happy-mining.de` | `Workflow` |
| Open WebUI | `https://openwebui.happy-mining.de` | `MessageSquare` |
| Home Assistant | `https://homeassistant.happy-mining.de` | `Home` |
| HA Development | `https://hassdev.happy-mining.de` | `Hammer` |
| Kanboard | `https://kanboard.happy-mining.de` | `Trello` (or `KanbanSquare`) |
| Jupyter | `https://jupyter.happy-mining.de` | `NotebookPen` |
| Finance Upload | `/finance_upload/index.html` | `Upload` |

> Icon names are suggestions — use whatever is available and visually fitting in the installed lucide-react version.

---

## Edge Cases

- **Finance Upload link**: Must use a relative path (`/finance_upload/index.html`), not an external domain, because it is served from the same nginx root.
- **Old bookmarks**: Anyone who bookmarked the old `index.html` will be redirected to `/alice/` without any broken experience.
- **Collapsed sidebar**: Service links must not be visible when the desktop sidebar is collapsed; they reappear when the sidebar is expanded.
- **Mobile sidebar (Sheet)**: Service links are visible in the mobile drawer as well; tapping a link closes the drawer before opening the URL.
- **Accessibility**: Icons are decorative and hidden from screen readers (`aria-hidden`); the link's `aria-label` provides the accessible name.
- **Future Finance Upload replacement**: The sidebar link entry point (URL and label) must be trivially updatable in a later sprint without architectural changes.

---

## Technical Requirements

- No new npm packages required (lucide-react already available)
- No API changes, no backend changes, no workflow changes
- The new `index.html` redirect must work without JavaScript (meta-refresh fallback)
- The Finance Upload link must use a root-relative path so it works regardless of where Alice is hosted

---

## Out of Scope

- Replacing the `finance_upload` HTML app itself (planned for a later sprint)
- Adding role-based visibility to service links (all authenticated users see all services)
- Configurable service list (hardcoded is acceptable for this sprint)

---

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
- **Production URL:** https://alice.happy-mining.de
- **Deployed:** 2026-02-28
- Frontend built via `./scripts/deploy-frontend.sh` (rsync to `nginx/html/`, `finance_upload/` excluded)
- Synced to server via `./sync-compose.sh`
- No nginx container restart required
