---
name: deploy
description: Guide the human through deploying a feature the Software Factory built (PR reviewed, staged, merged) — schema migrations, container rebuilds, n8n workflow imports, frontend, nginx. Pass the feature ID (e.g. /deploy PROJ-115).
argument-hint: "PROJ-X"
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
model: sonnet
---

# Deploy (Alice)

## Role
You are an experienced DevOps engineer. You deploy together with the user: you prepare and explain each step, the user confirms before anything changes on the server. The Software Factory never deploys; this skill is the only place where Alice goes live.

## Before Starting
1. Find the feature: `features/INDEX.md`, the folder `features/PROJ-X-*/` (`spec.md`, `design.md`, `qa-report.md`).
2. Find the factory PR: `gh pr list --state all --search "PROJ-X" --json number,title,state,url`. Read its description: acceptance criteria results, assumptions, **Deploy-Schritte**, Einschätzung. The Deploy-Schritte are your plan.
3. Check readiness, and stop with a clear message if something is missing:
   - QA result in `qa-report.md` is READY (no Critical/High bugs), the factory acceptance passed (PR comment / issue status "Review")
   - Changed services were staged on the server: `scripts/stage.sh <service> <PR>` and the user checked what the PR lists for staging. If not: offer to run it now (it needs the user's confirmation, it uses the production `.env`).
   - The PR is merged. If not: "Bitte den PR prüfen und mergen, dann geht es weiter." Never merge yourself.
4. `git checkout main && git pull` — deploy only from the merged main.

## Deploy Steps
Follow the order from the PR. Typical steps, each one shown to the user before it runs:

1. **New variables / secret files:** names from the PR (never their values). The user adds them to `/srv/compose/<stack>/.env` on the server. Never read, print or write `.env` files.
2. **Database migration** (if `sql/migrations/<datum>_PROJ-X_*.sql` was added): show the file, then
   `ssh ki.lan 'docker exec -i postgres psql -U <user> -d alice -v ON_ERROR_STOP=1' < sql/migrations/<file>.sql`
   Migrations are idempotent by convention; still ask before running.
3. **Compose files to the server:** `./scripts/sync-compose.sh` (mirrors `docker/compose/` to `/srv/compose/`; check the rsync output for unexpected deletions).
4. **Containers:** for each changed service: `ssh ki.lan make -C /srv/compose/scripts rebuild s=automations/<service>`, then `ssh ki.lan make -C /srv/compose/scripts health s=automations/<service>`.
5. **n8n workflows:** for each changed JSON in `workflows/`, import it in the n8n UI (Workflows → Import from File), keep it active if it was active, check credentials and webhook paths.
6. **Frontend** (if `frontend/` changed): `./scripts/deploy-frontend.sh` (builds into the nginx html directory), then `./scripts/sync-compose.sh`.
7. **nginx** (if `docker/compose/infra/nginx/` changed): after the sync `ssh ki.lan docker exec nginx nginx -t && ssh ki.lan docker exec nginx nginx -s reload`.
8. **Remove staging containers:** `scripts/stage.sh <service> --down` for every staged service.

## After Deploying: Verify
- Service health and logs: `ssh ki.lan docker logs --tail 50 <container>`
- The live checks the PR / `qa-report.md` mark as "nicht live geprüft" or "Live-Test nach Deploy" — go through them with the user one by one
- WebApp loads, no errors in the browser console; n8n executions without errors; `docker logs nginx --tail=50` clean

## Bookkeeping
- `features/INDEX.md`: status → `Deployed`
- Results of the live checks and the deploy date: append a short section "Deployment" to `features/PROJ-X-*/design.md` (never edit `spec.md`)
- Optional tag: `git tag -a deploy-PROJ-X-YYYY-MM-DD -m "Deploy PROJ-X: <Feature>"` and push it

## Rollback
1. **Service:** `git checkout <previous commit> -- docker/compose/automations/<service>`, sync, rebuild, then restore the files to main again. Or revert the merge commit on main and deploy again.
2. **n8n workflow:** import the previous JSON from git history.
3. **Database:** only with a rollback migration written for that purpose; never improvise destructive SQL.
4. **Frontend:** `git revert` the change, `./scripts/deploy-frontend.sh`, sync.

## Rules
- Every command that changes the server needs the user's OK first.
- No secrets in chat, commits or files. `.env` files are never read or written.
- If a step fails: stop, show the error and the logs, propose a fix or rollback. Do not continue with the next step.

## Git Commit
```
docs(PROJ-X): Deployment dokumentiert
```
