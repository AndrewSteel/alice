# PROJ-32: nginx Streaming-Konfiguration

**Status:** 🟢 Deployed
**Created:** 2026-05-07
**Last Updated:** 2026-05-09

## Kontext & Motivation

nginx puffert standardmäßig Proxy-Antworten vollständig, bevor es sie an den Client weitergibt. Das bricht Server-Sent Events (SSE): Der Client wartet auf den vollständigen Stream, der nie endet, bis die Verbindung getrennt wird.

Außerdem muss ein neuer Proxy-Block für den `alice-chat-stream`-Service (PROJ-30, Port 8003) angelegt und korrekt konfiguriert werden.

## Dependencies

- Requires: PROJ-30 (alice-chat-stream läuft auf Port 8003)
- Modifies: `nginx/` Konfigurationsdateien (bestehende Struktur)
- Parallel zu: PROJ-31 (Frontend Streaming-UI)

## User Stories

- Als Entwickler möchte ich, dass SSE-Verbindungen zum `alice-chat-stream` ohne Pufferung durchgeleitet werden, damit Tokens den Browser sofort erreichen.
- Als Entwickler möchte ich, dass bestehende Proxies (n8n, alice-auth) unverändert bleiben, damit kein Rückschritt entsteht.
- Als Entwickler möchte ich, dass abgebrochene Client-Verbindungen sofort an den Upstream weitergegeben werden, damit der Python-Service den Ollama-Stream stoppen kann.

## Acceptance Criteria

### SSE-Proxy-Konfiguration
- [x] Neuer Location-Block `/api/stream/` leitet zu `http://alice-chat-stream:8003` weiter
- [x] `proxy_buffering off` ist im Stream-Location-Block gesetzt
- [x] `proxy_cache off` ist im Stream-Location-Block gesetzt
- [x] Response-Header `X-Accel-Buffering: no` wird vom Upstream gesetzt oder von nginx hinzugefügt
- [x] `proxy_read_timeout` ist auf mindestens `120s` gesetzt (Streaming-Verbindungen leben länger)
- [x] `proxy_send_timeout` ist auf mindestens `120s` gesetzt
- [x] `chunked_transfer_encoding on` ist aktiv (Standard, explizit dokumentiert)

### Verbindungs-Management
- [x] `proxy_http_version 1.1` ist gesetzt (HTTP/1.1 für Keep-Alive)
- [x] `proxy_set_header Connection ""` entfernt den `Connection: close`-Header (Keep-Alive)
- [x] `proxy_set_header X-Real-IP $remote_addr` wird weitergeleitet
- [x] `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for` wird weitergeleitet

### Bestehende Konfiguration unverändert
- [x] `/api/webhook/` → n8n (Port 5678): unverändert (300s Timeout, Buffering nach wie vor aus)
- [x] `/api/auth/` → alice-auth (Port 8002): unverändert
- [x] Statische Dateien (`/`): unverändert
- [x] Rate-Limiting auf `/api/webhook/` (20 Req/min): unverändert
- [x] Security-Headers-Snippet: unverändert

### Rate-Limiting für Streaming
- [x] Neuer `limit_req_zone` für `/api/stream/`: 10 Req/min pro IP (SSE-Verbindungen sind langlebig)
- [x] HTTP 429-Antwort ist plaintext (kein SSE) mit `Retry-After`-Header

## Edge Cases

- Client bricht SSE-Verbindung ab → nginx meldet `EPIPE` an Upstream, Python-Service stoppt Stream
- Ollama braucht >120s für eine Antwort → nginx sendet HTTP 504; Frontend zeigt Timeout-Meldung
- `alice-chat-stream` Container nicht erreichbar → nginx antwortet mit HTTP 502; kein SSE-Stream
- Gleichzeitig > 100 SSE-Verbindungen → nginx-Worker-Connections müssen ausreichen (prüfen)

## Tech Design (Solution Architect)

### Änderungsumfang

Zwei Dateien werden modifiziert — kein neuer Service, kein Datenbankschema, keine Frontend-Änderung:

```
docker/compose/infra/nginx/
├── conf.d/
│   ├── alice.conf        ← MODIFIZIERT: neuer /api/stream/ Location-Block
│   └── rate-limit.conf   ← MODIFIZIERT: neuer stream_limit Zone
└── snippets/
    └── security-headers.conf   ← unverändert
```

### Konfigurationsstruktur

```
rate-limit.conf
  +-- stream_limit Zone  (10 req/min, SSE-spezifisch)
  +-- chat_limit Zone    (20 req/min, unverändert)
  +-- auth_limit Zone    (5 req/min, unverändert)

alice.conf → server { 443 }
  +-- /api/auth/          → alice-auth:8002      (unverändert)
  +-- /api/webhook/alice/ → n8n:5678             (unverändert)
  +-- /api/webhook/dms/   → n8n:5678             (unverändert)
  +-- /api/stream/        → alice-chat-stream:8003  ← NEU
  |     +-- proxy_buffering off
  |     +-- proxy_cache off
  |     +-- proxy_http_version 1.1
  |     +-- Connection "" (Keep-Alive override)
  |     +-- read/send timeout 120s
  |     +-- rate limit: stream_limit
  +-- /api/webhook/       → n8n:5678             (unverändert, catch-all)
  +-- /                   → static files          (unverändert)
```

### Tech-Entscheidungen

**Warum `/api/stream/` vor `/api/webhook/` in alice.conf?**
nginx wählt den längsten übereinstimmenden `^~`-Prefix. `/api/stream/` beginnt nicht mit `/api/webhook/`, es gibt keine Kollision — die Reihenfolge ist aber trotzdem sinnvoll der Lesbarkeit halber: spezifische Blöcke vor dem Catch-all.

**Warum `proxy_set_header Connection ""`?**
Der Server-Block setzt global `Connection: $connection_upgrade` (für WebSocket-Upgrade-Header). Im Stream-Block muss das auf Keep-Alive zurückgesetzt werden, damit SSE-Verbindungen offen bleiben, ohne ein Upgrade zu erwarten.

**Warum `X-Accel-Buffering: no` via `add_header` statt Upstream-Header?**
Sicherer: falls `alice-chat-stream` den Header einmal nicht setzt (z. B. nach einem Refactor), setzt nginx ihn trotzdem. Doppelt gesetzt schadet nicht.

**Warum 10 req/min für Stream-Rate-Limit?**
SSE-Verbindungen sind langlebig (eine Verbindung pro Chat-Antwort). 10 req/min reichen für normalen Chat, verhindern aber, dass ein Client Hunderte von Verbindungen öffnet.

**Warum `proxy_http_version 1.1`?**
HTTP/2 hat eigene Streaming-Mechanismen; nginx öffnet Upstream-Verbindungen in HTTP/1.1. Für SSE (unidirektionaler Stream) ist HTTP/1.1 Keep-Alive die bewährte Lösung.

### Deployment

Nach der Änderung an `alice.conf` und `rate-limit.conf`:
1. `nginx -t` validiert die Syntax
2. `./sync-compose.sh` überträgt die Konfiguration auf den Server
3. nginx reload im Container (`docker exec nginx nginx -s reload`)

---

## QA-Ergebnis

**Getestet:** 2026-05-08 — Code Review gegen Acceptance Criteria

### SSE-Proxy-Konfiguration
- [x] Neuer Location-Block `/api/stream/` leitet zu `http://alice-chat-stream:8003` weiter
- [x] `proxy_buffering off` im Stream-Location-Block gesetzt
- [x] `proxy_cache off` im Stream-Location-Block gesetzt
- [x] `add_header X-Accel-Buffering no always` — nginx setzt Header selbst (defensiv, auch falls Upstream ihn weglässt)
- [x] `proxy_read_timeout 120s` gesetzt
- [x] `proxy_send_timeout 120s` gesetzt
- [x] `chunked_transfer_encoding on` explizit gesetzt

### Verbindungs-Management
- [x] `proxy_http_version 1.1` gesetzt
- [x] `proxy_set_header Connection ""` — überschreibt den server-block-globalen `$connection_upgrade`
- [x] `proxy_set_header X-Real-IP $remote_addr`
- [x] `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for`

### Bestehende Konfiguration unverändert
- [x] `/api/webhook/` → n8n: unverändert
- [x] `/api/auth/` → alice-auth: unverändert
- [x] Statische Dateien (`/`): unverändert
- [x] `chat_limit` (20 req/min) und `auth_limit` (5 req/min): unverändert
- [x] `security-headers.conf`-Snippet: unverändert

### Rate-Limiting für Streaming
- [x] `stream_limit` Zone: 10 req/min/IP in `rate-limit.conf`
- [x] `limit_req zone=stream_limit burst=5 nodelay` im Location-Block
- [x] HTTP 429 bei Überschreitung (via globalem `limit_req_status 429`) — plaintext, kein SSE
- [x] `Retry-After: 60` Header bei 429 — via `error_page 429 = @stream_rate_limited` + named location

### Pfad-Rewrite-Hinweis
Der Block verwendet `rewrite ^/api(.*)$ $1 break` — d. h. `/api/stream/chat` kommt beim Python-Service als `/stream/chat` an. Muss mit PROJ-30 abgestimmt sein (erwartet der Service `/stream/chat` oder `/chat`?).

### Deployment-Voraussetzung
`nginx -t` wurde gegen `nginx:1.27-alpine` validiert — Syntax OK. Konfiguration liegt lokal vor und muss noch deployed werden:
1. `./scripts/sync-compose.sh`
2. `ssh stan@ki.lan "docker exec nginx nginx -s reload"`

---

## Technical Design

### nginx Location-Block (Beispiel)

```nginx
# alice-chat-stream SSE Proxy
location /api/stream/ {
    limit_req zone=stream_limit burst=5 nodelay;

    proxy_pass         http://alice-chat-stream:8003/;
    proxy_http_version 1.1;
    proxy_set_header   Connection         "";
    proxy_set_header   Host               $host;
    proxy_set_header   X-Real-IP          $remote_addr;
    proxy_set_header   X-Forwarded-For    $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto  $scheme;

    # SSE erfordert: kein Buffering
    proxy_buffering    off;
    proxy_cache        off;
    add_header         X-Accel-Buffering  no;

    # Timeouts für langlebige Verbindungen
    proxy_read_timeout  120s;
    proxy_send_timeout  120s;

    # Security Headers (wiederverwendbares Snippet, wie bestehende Location-Blocks)
    include /etc/nginx/snippets/security-headers.conf;
}

# Rate-Limit-Zone (in http{}-Block)
limit_req_zone $binary_remote_addr zone=stream_limit:10m rate=10r/m;
```

### Datei-Struktur

Bestehende nginx-Konfigurationsstruktur (in `docker/compose/infra/` oder `nginx/`):
```
nginx/
├── conf.d/
│   ├── alice.conf          ← MODIFIZIERT: neuer /api/stream/ Block + limit_req_zone
│   └── ...
└── snippets/
    └── security-headers.conf   ← unverändert
```

### Deliverables

- [x] nginx `alice.conf` um `/api/stream/`-Location-Block erweitert
- [x] `limit_req_zone` für Stream-Rate-Limiting hinzugefügt
- [x] Konfiguration via `nginx -t` validiert
- [x] `scripts/sync-compose.sh` stellt sicher, dass nginx-Config deployed wird

### Live-QA (2026-05-09)

**Methode:** Direkttests auf ki.lan gegen laufenden nginx-Container

| Test | Ergebnis |
|---|---|
| `nginx -t` Syntax-Check | PASS — `syntax is ok / test is successful` |
| `proxy_buffering off` im `/api/stream/`-Block | PASS — verifiziert in `/etc/nginx/conf.d/alice.conf` |
| `proxy_cache off`, `chunked_transfer_encoding on` | PASS |
| `proxy_http_version 1.1`, `Connection ""` | PASS |
| `X-Accel-Buffering: no` am Client | PASS — Header in OPTIONS-Preflight sichtbar |
| Rate-Limit `stream_limit` 10r/m mit `Retry-After: 60` | PASS — verifiziert in `rate-limit.conf` |
| Security Headers auf `/api/stream/` | PASS — `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy` |
| HTTPS-Edge → nginx → Backend 401 (kein Token) | PASS |
| Bestehende Routen (`/api/auth/`, `/api/webhook/`) unverändert | PASS |

