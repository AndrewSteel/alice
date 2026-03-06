# PROJ-13: Auth-Endpoint Rate-Limiting

## Status: Planned
**Created:** 2026-03-06
**Last Updated:** 2026-03-06

## Dependencies
- Requires: PROJ-7 (JWT Auth / Login Screen) — `/api/auth/`-Endpoints müssen existieren
- Requires: PROJ-12 (Phase 2 Security & UX Hardening) — `rate-limit.conf` und `limit_req_status 429` sind bereits gesetzt

---

## Übersicht

BUG-2 aus dem PROJ-12-QA-Audit: Der Login-Endpoint (`POST /api/auth/login`) hat kein Rate-Limiting. Ein Angreifer kann beliebig viele Passwörter ausprobieren. Das `security.md`-Regelwerk fordert explizit: "Implement rate limiting on authentication endpoints."

**Scope:** Ausschließlich nginx-Konfiguration. Kein Frontend-Umbau, kein Backend-Code, keine DB-Änderung.

**Abgrenzung:** Nur `POST`-Requests auf `/api/auth/` werden begrenzt. `GET /api/auth/validate` wird vom Frontend bei jedem Seitenaufruf und regelmäßig im Hintergrund aufgerufen — dieser Endpoint bleibt ungedrosselt.

---

## User Stories

1. **Als Admin** möchte ich, dass ein Angreifer nicht unbegrenzt Login-Versuche ausführen kann, damit Brute-Force-Angriffe auf Nutzerpasswörter verhindert werden.
2. **Als Nutzer** möchte ich eine verständliche Fehlermeldung erhalten, wenn mein Login wegen zu vieler Versuche geblockt wird, damit ich weiß, dass ich kurz warten muss.
3. **Als Nutzer** möchte ich, dass das Rate-Limit großzügig genug ist, damit eine normale Anmeldung (1–3 Versuche/Minute) nie blockiert wird.
4. **Als Frontend** (`auth.js`) möchte ich `/api/auth/validate` unbegrenzt aufrufen können, damit Session-Validierungen und automatische Token-Checks nicht geblockt werden.
5. **Als Admin** möchte ich, dass das Auth-Rate-Limit strenger ist als das Chat-Rate-Limit (20r/m), da Login-Brute-Force sicherheitskritischer ist als Chat-Spam.

---

## Acceptance Criteria

### A) nginx Rate-Limit Zone für Auth

Betroffene Datei: `docker/compose/infra/nginx/conf.d/rate-limit.conf`

- [ ] Eine neue `limit_req_zone`-Direktive definiert eine Zone `auth_limit`
- [ ] Die Zone verwendet **`$auth_limit_key`** als Schlüssel (nicht `$binary_remote_addr` direkt) — damit nur `POST`-Requests gezählt werden
- [ ] Eine `map`-Direktive in `rate-limit.conf` definiert `$auth_limit_key`:
  - `POST` → `$binary_remote_addr` (wird gezählt)
  - alle anderen Methoden → `""` (leerer String = nicht gezählt)
- [ ] Rate: **5r/m** (5 Requests pro Minute, ~1 alle 12 Sekunden)
- [ ] Zone-Größe: `10m` Shared Memory
- [ ] Die Direktive steht im `http`-Kontext (via `conf.d/rate-limit.conf`, das nginx in den http-Kontext lädt)

### B) nginx Rate-Limit Anwendung

Betroffene Datei: `docker/compose/infra/nginx/conf.d/alice.conf`

- [ ] `limit_req zone=auth_limit burst=3 nodelay;` ist im `/api/auth/`-Location-Block gesetzt
- [ ] Die `limit_req`-Direktive steht **vor** dem `if ($request_method = OPTIONS)` Block (OPTIONS läuft in der Rewrite-Phase vor Access-Phase — daher werden OPTIONS-Requests ohnehin nicht gezählt, aber die Reihenfolge ist konventionell korrekt)
- [ ] `GET /api/auth/validate`-Requests werden nicht geblockt (durch die `map`-Direktive: GET → leerer Schlüssel → kein Counting)
- [ ] `POST /api/auth/login` mit ≤ 5 Requests/Minute wird durchgelassen
- [ ] `POST /api/auth/login` mit > 5 Requests/Minute (nach burst=3) erhält HTTP 429
- [ ] `limit_req_status 429` ist bereits gesetzt (via PROJ-12) — keine erneute Änderung nötig

### C) Frontend — Login-Screen Fehlerbehandlung

Betroffene Datei: `frontend/src/components/Auth/LoginScreen.tsx` (oder `services/auth.ts`)

- [ ] Bei HTTP 429 vom Login-Endpoint zeigt der LoginScreen die Meldung: `"Zu viele Anmeldeversuche — bitte eine Minute warten."`
- [ ] Kein Auto-Redirect auf 429 (429 ist kein Auth-Fehler)
- [ ] Die Fehlermeldung erscheint inline im Login-Formular (nicht als Toast oder Alert-Box)
- [ ] Der Login-Button wird nach 429 nicht deaktiviert — der Nutzer kann erneut versuchen (nginx entscheidet, wann er wieder erlaubt wird)
- [ ] Der bestehende 401-Handler (falsches Passwort) bleibt unverändert

---

## Edge Cases

- **`GET /api/auth/validate` bei vielen Seitenaufrufen:** Durch die `map`-Lösung (GET → leerer Schlüssel) wird dieser Endpoint nie gezählt und nie geblockt.
- **`POST /api/auth/logout`:** Wird ebenfalls gezählt (ist ein POST). Mit burst=3 und 5r/m ist das unkritisch — niemand loggt sich 5x/Minute aus.
- **`POST /api/auth/hash-password`:** Admin-Utility-Endpoint. Wird ebenfalls begrenzt. Akzeptabler Trade-off — hash-password ist kein Live-Endpoint.
- **Mehrere Nutzer hinter VPN:** Gleiche Einschränkung wie beim Chat-Rate-Limit (BUG-3 PROJ-12): geteilte IP, gemeinsames Limit. Da Alice ein Familienprojekt mit wenigen Nutzern ist, reicht burst=3 für Simultananmeldungen aus.
- **Falsches Passwort + sofortiger Retry:** 5r/m + burst=3 = 8 schnelle Versuche, danach 429. Danach 1 Versuch alle 12 Sekunden. Das ist ausreichend restriktiv gegen Brute-Force.

---

## Technical Requirements

- **nginx:** `ngx_http_limit_req_module` bereits aktiv (via PROJ-12). `map`-Direktive erfordert `ngx_http_map_module` — im nginx-Default-Image standardmäßig enthalten, kein Modul-Nachladen nötig.
- **Dateiänderungen:** Nur `conf.d/rate-limit.conf` (Zone + Map) und `conf.d/alice.conf` (limit_req in /api/auth/) und LoginScreen-Komponente
- **Keine neuen npm-Pakete**
- **Kein Backend-Code, keine DB-Änderung**
- **Deployment:** `nginx -s reload` nach `sync-compose.sh` — kein Container-Neustart nötig

---

## Tech Design
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
