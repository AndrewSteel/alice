# PROJ-34: alice-auth RS256 Migration

**Status:** 🔵 Planned
**Created:** 2026-05-09
**Last Updated:** 2026-05-09

## Kontext & Motivation

`alice-auth` signiert JWTs derzeit mit HS256 (symmetrischer Shared-Secret). Seit PROJ-30 wird
`alice-chat-stream` mit RS256-Verifikation gebaut — der Streaming-Service erwartet ein RSA-Public-Key-File
(`JWT_PUBLIC_KEY_PATH`). Solange alice-auth noch HS256 ausgibt, können `alice-chat-stream`-Tokens
nicht verifiziert werden.

**Warum RS256?**
- Private Key bleibt ausschließlich in alice-auth — andere Dienste brauchen nur den Public Key
- Kein Shared-Secret über Container-Grenzen hinweg nötig; geringeres Kompromittierungsrisiko
- Vorbereitung für weitere Dienste (Phase-2 Speech Service, PROJ-33), die Tokens ebenfalls verifizieren müssen

## Dependencies

- Requires: PROJ-7 (alice-auth — wird in-place migriert)
- Blocks: PROJ-30 (alice-chat-stream — wartet auf RS256-Tokens)
- Enables: PROJ-33 (Phase-2 Speech Service kann Tokens selbst verifizieren)

## User Stories

- Als Entwickler möchte ich, dass alice-auth RSA-signierte JWTs ausstellt, damit alice-chat-stream und
  zukünftige Dienste Tokens lokal verifizieren können ohne den Signing-Key zu kennen.
- Als Operator möchte ich das Schlüsselpaar einmalig generieren und dauerhaft auf `/srv/warm/alice/keys/`
  ablegen, damit es Container-Neustarts überlebt.
- Als Entwickler möchte ich, dass die Migration ohne Login-Unterbrechung für bestehende Sessions
  ausrollt (Grace-Period für alte Tokens).

## Acceptance Criteria

### Key Management
- [ ] RSA-Schlüsselpaar (4096 Bit) liegt unter `/srv/warm/alice/keys/jwt_private.pem` (Modus 600) und
  `/srv/warm/alice/keys/jwt_public.pem` (Modus 644) auf dem Host
- [ ] Private Key ist **nicht** im Git-Repository und **nicht** in Container-Images
- [ ] Public Key ist **nicht** geheim — er darf als Read-Only-Volume in alle verifizierenden Dienste gemountet werden
- [ ] Key-Generierung ist als einmaliger Admin-Befehl dokumentiert (kein Startup-Auto-Generate)

### alice-auth Code
- [ ] `JWT_ALGORITHM = "RS256"` (war `"HS256"`)
- [ ] `JWT_PRIVATE_KEY_PATH` (Env-Var) ersetzt `JWT_SECRET` für das Signieren
- [ ] `_create_jwt()` lädt den Private Key aus der Datei und signiert mit RS256
- [ ] `_decode_jwt()` lädt den Public Key aus einer Datei (`JWT_PUBLIC_KEY_PATH`) und verifiziert mit RS256
- [ ] Beide Key-Variablen werden beim Start geprüft; fehlen sie → Service startet nicht (kein Silent-Fail)
- [ ] `requirements.txt` von alice-auth enthält `cryptography>=42,<44`

### alice-auth compose.yml
- [ ] Private Key als Read-Only-Volume: `/srv/warm/alice/keys/jwt_private.pem:/run/secrets/jwt_private.pem:ro`
- [ ] Public Key als Read-Only-Volume: `/srv/warm/alice/keys/jwt_public.pem:/run/secrets/jwt_public.pem:ro`
- [ ] `JWT_SECRET` wird aus `.env` und compose.yml entfernt
- [ ] `.env` enthält stattdessen `JWT_PRIVATE_KEY_PATH=/run/secrets/jwt_private.pem` und
  `JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public.pem`

### alice-auth Health-Endpoint
- [ ] `GET /health` prüft `JWT_PRIVATE_KEY_PATH` statt `JWT_SECRET`
- [ ] Response-Field heißt `jwt_private_key` (nicht `jwt_secret`)

### alice-chat-stream (bereits implementiert in PROJ-30, muss nur live gehen)
- [ ] Public Key liegt unter `/srv/warm/alice/keys/jwt_public.pem` auf dem Host (gleicher Pfad)
- [ ] alice-chat-stream compose.yml mounted denselben Host-Pfad (bereits konfiguriert)
- [ ] `.env` von alice-chat-stream enthält `JWT_PUBLIC_KEY_PATH=/run/secrets/jwt_public.pem`

### Rollout ohne Unterbrechung
- [ ] Neues Key-Paar generieren, bevor alice-auth neugestartet wird
- [ ] alice-auth mit RS256 deployen → gibt ab sofort RS256-Tokens aus
- [ ] alice-chat-stream deployen → verifiziert RS256-Tokens
- [ ] Bestehende HS256-Sessions laufen maximal 24h weiter (JWT-Expiry); danach sind alle Tokens RS256
- [ ] Kein Token-Blacklisting oder Forced-Logout nötig (bestehende Tokens werden abgelehnt bei
  alice-chat-stream, nicht bei alice-auth/validate — akzeptabler Trade-off)

## Edge Cases

- Private Key nicht lesbar beim Start → alice-auth-Prozess bricht mit Fehlermeldung ab (kein 500 im Betrieb)
- Public Key nicht lesbar beim Start → alice-chat-stream-Prozess bricht ab
- Schlüssel rotieren: neues Paar generieren → alice-auth neustarten → 24h warten → alice-chat-stream neustarten (keine JWKS-Rotation nötig in Phase 1)
- Versehentlich `chmod 644` auf Private Key → Warnung in Logs, aber kein Startup-Stopp (Dateisystem-Sicherheit ist Admin-Aufgabe)

## Technical Design

### Key-Generierung (einmaliger Admin-Befehl auf dem Server)

```bash
mkdir -p /srv/warm/alice/keys
openssl genrsa -out /srv/warm/alice/keys/jwt_private.pem 4096
openssl rsa -in /srv/warm/alice/keys/jwt_private.pem \
            -pubout -out /srv/warm/alice/keys/jwt_public.pem
chmod 600 /srv/warm/alice/keys/jwt_private.pem
chmod 644 /srv/warm/alice/keys/jwt_public.pem
```

### Änderungen in alice-auth/main.py

**Konfiguration** (ersetzt `JWT_SECRET`):
```python
JWT_PRIVATE_KEY_PATH = os.environ.get("JWT_PRIVATE_KEY_PATH", "")
JWT_PUBLIC_KEY_PATH  = os.environ.get("JWT_PUBLIC_KEY_PATH", "")
JWT_ALGORITHM        = "RS256"

def _load_private_key() -> str:
    if not JWT_PRIVATE_KEY_PATH:
        raise RuntimeError("JWT_PRIVATE_KEY_PATH is not set")
    with open(JWT_PRIVATE_KEY_PATH) as f:
        return f.read()

def _load_public_key() -> str:
    if not JWT_PUBLIC_KEY_PATH:
        raise RuntimeError("JWT_PUBLIC_KEY_PATH is not set")
    with open(JWT_PUBLIC_KEY_PATH) as f:
        return f.read()
```

**`_create_jwt()`** (signiert mit Private Key):
```python
def _create_jwt(user_id: str, username: str, role: str) -> str:
    private_key = _load_private_key()
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=JWT_EXPIRY_HOURS)).timestamp()),
    }
    return jwt.encode(payload, private_key, algorithm=JWT_ALGORITHM)
```

**`_decode_jwt()`** (verifiziert mit Public Key):
```python
def _decode_jwt(token: str) -> dict:
    public_key = _load_public_key()
    return jwt.decode(token, public_key, algorithms=[JWT_ALGORITHM])
```

**Startup-Prüfung** (Fail-Fast):
```python
# In app startup / lifespan:
try:
    _load_private_key()
    _load_public_key()
except Exception as exc:
    logger.critical("JWT key load failed on startup: %s", exc)
    raise SystemExit(1)
```

### Änderungen in alice-auth/compose.yml

```yaml
volumes:
  - /srv/warm/alice/keys/jwt_private.pem:/run/secrets/jwt_private.pem:ro
  - /srv/warm/alice/keys/jwt_public.pem:/run/secrets/jwt_public.pem:ro
```

### Keine Datenbankänderungen

Kein neues Schema. `alice.auth_sessions` ist bereits vorhanden und wird nicht berührt.

## Tech Design (Solution Architect)

### Architecture Overview

Pure backend/infrastructure migration — no UI changes, no database schema changes, no n8n workflow changes.

**Key Distribution Model:**
```
[HOST: /srv/warm/alice/keys/]
  jwt_private.pem (mode 600)  ──→  alice-auth only (signing)
  jwt_public.pem  (mode 644)  ──→  alice-auth + alice-chat-stream + future services (verification)
```

**Services Changed:**

| Service | Change |
|---|---|
| `alice-auth` main.py | HS256 → RS256; `JWT_SECRET` → key file reads; fail-fast startup check |
| `alice-auth` compose.yml | Add private + public key volumes; remove `JWT_SECRET` env |
| `alice-chat-stream` compose.yml | Mount same public key path (service is already coded for RS256) |

**Rollout sequence (zero forced-logout):**
```
1. Generate RSA key pair on server (one-time admin command)
2. Deploy alice-auth → issues RS256 tokens from now on
3. Existing HS256 tokens expire within 24h naturally
4. Deploy alice-chat-stream → RS256 verification active
```

**Not changed:** PostgreSQL schema, n8n workflows, nginx, frontend. Frontend stores and forwards JWTs opaquely — algorithm change is invisible to it.

**Dependencies added:** `cryptography>=42,<44` to alice-auth requirements (alice-chat-stream already has it).

### Deliverables

- [ ] `docker/compose/automations/alice-auth/main.py` — RS256-Implementierung
- [ ] `docker/compose/automations/alice-auth/requirements.txt` — `cryptography` ergänzen
- [ ] `docker/compose/automations/alice-auth/compose.yml` — Key-Volumes eintragen
- [ ] Deployment-Anleitung (Key-Generierung + Rollout-Reihenfolge) als Kommentar in compose.yml
  oder separates `DEPLOY.md` im Container-Verzeichnis
