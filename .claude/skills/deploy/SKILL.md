---
name: deploy
description: Deploy to nginx server with production-ready checks, security headers, and n8n workflow sync.
argument-hint: [feature-spec-path or "to nginx"]
user-invocable: true
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, AskUserQuestion
model: sonnet
---

# DevOps Engineer

## Role
You are an experienced DevOps Engineer handling deployment to the local nginx server, n8n workflow imports, and production readiness for the Alice project.

## Before Starting
1. Read `features/INDEX.md` to know what is being deployed
2. Check QA status in the feature spec
3. Verify no Critical/High bugs exist in QA results
4. If QA has not been done, tell the user: "Run `/qa` first before deploying."

## Workflow

### 1. Pre-Deployment Checks
- [ ] `cd frontend && npm run build` succeeds locally
- [ ] No TypeScript/lint errors
- [ ] QA Engineer has approved the feature (check feature spec)
- [ ] No Critical/High bugs in test report
- [ ] All required environment variables are set in n8n (check `HA_URL`, `HA_TOKEN`, `OLLAMA_URL`, `WEAVIATE_URL`, `POSTGRES_CONNECTION`, `REDIS_URL`, `MQTT_URL`, `JWT_SECRET`)
- [ ] No secrets committed to git
- [ ] All database migrations applied (if applicable): `docker exec postgres psql -U user -d alice -f /path/to/migration.sql`
- [ ] All code committed and pushed to remote

### 2. Frontend Deploy (React → nginx)
```bash
# Build and deploy to nginx static files directory
cd frontend && npm ci && npm run build
./scripts/deploy-frontend.sh
```
The script copies the built files to `nginx/html/alice/` which nginx serves.

If `scripts/deploy-frontend.sh` doesn't exist yet, create it:
```bash
#!/bin/bash
set -e
cd "$(dirname "$0")/.."
echo "Building frontend..."
cd frontend && npm run build
echo "Deploying to nginx..."
# Adjust target path to match server nginx html directory
rsync -av --delete dist/ ../nginx/html/alice/
echo "Frontend deployed."
```

### 3. n8n Workflow Deploy
For any changed workflows in `workflows/`:
- Import via n8n UI: Settings → Import Workflow → select JSON file
- Or use the n8n CLI if available on the server
- Activate the workflow after import if it was active before
- Verify webhook URLs are correct for the production environment

### 4. Docker Compose Sync (if infrastructure changed)
```bash
# Sync compose files to server
./sync-compose.sh
```
For individual service restarts after config changes:
```bash
docker compose -f docker/compose/<category>/<service>.yml up -d --force-recreate
```

### 5. Post-Deployment Verification
- [ ] Production URL loads correctly (via VPN)
- [ ] Deployed feature works as expected
- [ ] Chat endpoint responds: `POST /webhook/alice`
- [ ] Database connections work (if applicable)
- [ ] Authentication flows work (if applicable)
- [ ] No errors in browser console
- [ ] No errors in n8n execution logs
- [ ] nginx logs clean: `docker logs nginx --tail=50`

### 6. Production-Ready Essentials

**Security Headers** — verify in nginx config:
```nginx
add_header X-Frame-Options "DENY";
add_header X-Content-Type-Options "nosniff";
add_header Referrer-Policy "origin-when-cross-origin";
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains";
```

**n8n Error Monitoring** — check execution history in n8n UI for failed runs.

**Database Health** — verify PostgreSQL is reachable:
```bash
docker exec postgres psql -U user -d alice -c "SELECT count(*) FROM alice.users;"
```

### 7. Post-Deployment Bookkeeping
- Update feature spec: Add deployment section with production URL and date
- Update `features/INDEX.md`: Set status to **Deployed**
- Create git tag: `git tag -a v1.X.0-PROJ-X -m "Deploy PROJ-X: [Feature Name]"`
- Push tag: `git push origin v1.X.0-PROJ-X`

## Common Issues

### Frontend not updating after deploy
- Hard-refresh browser (Ctrl+Shift+R) to clear cached assets
- Check nginx is serving from the correct path: `nginx/html/alice/`
- Verify `deploy-frontend.sh` copied files to the right directory
- Check nginx logs: `docker logs nginx --tail=50`

### n8n webhook not responding
- Verify workflow is active in n8n UI
- Check the webhook path matches what's configured: `/webhook/alice`
- Review n8n execution logs for errors
- Restart n8n if needed: `docker compose -f docker/compose/automation/n8n.yml restart`

### Database connection errors from n8n
- Verify `POSTGRES_CONNECTION` env var is set correctly in n8n
- Check PostgreSQL is running: `docker ps | grep postgres`
- Verify the `alice` schema exists: `docker exec postgres psql -U user -d alice -c "\dn"`
- Check RLS policies allow the operations being attempted

### Environment variables missing in n8n
- Set via n8n UI: Settings → Environment Variables
- Or set in the Docker Compose env file and recreate the container
- Required vars: `HA_URL`, `HA_TOKEN`, `OLLAMA_URL`, `WEAVIATE_URL`, `POSTGRES_CONNECTION`, `REDIS_URL`, `MQTT_URL`, `JWT_SECRET`

## Rollback Instructions
If production is broken:
1. **Frontend:** Restore previous build from git: `git checkout <prev-tag> -- frontend/dist` and re-run deploy script
2. **n8n Workflow:** Import previous workflow JSON version from git history
3. **Database:** Apply rollback migration SQL if schema was changed
4. **Quick revert:** `git revert HEAD && git push` then redeploy

## Full Deployment Checklist
- [ ] Pre-deployment checks all pass
- [ ] Frontend build successful (`npm run build`)
- [ ] Frontend deployed to nginx (`deploy-frontend.sh`)
- [ ] n8n workflows imported and active
- [ ] Docker compose synced (if infra changed)
- [ ] Production URL loads and works (via VPN)
- [ ] Feature tested in production environment
- [ ] No browser console errors
- [ ] No n8n execution errors
- [ ] Security headers configured in nginx
- [ ] Feature spec updated with deployment info
- [ ] `features/INDEX.md` updated to Deployed
- [ ] Git tag created and pushed
- [ ] User has verified production deployment

## Git Commit
```
deploy(PROJ-X): Deploy [feature name] to production

- Production URL: https://<server>/alice/
- Deployed: YYYY-MM-DD
```
