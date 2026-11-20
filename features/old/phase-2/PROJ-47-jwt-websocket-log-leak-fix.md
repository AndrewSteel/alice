# PROJ-47: JWT WebSocket Log Leak Fix

## Status: Deployed
**Created:** 2026-06-02
**Last Updated:** 2026-06-15

## Background

BUG-LIVE-2 from the PROJ-41 live QA. The `--no-access-log` flag added to the uvicorn CMD only silences the HTTP access logger (`uvicorn.access`). The WebSocket protocol logger (`uvicorn.protocols.websockets.websockets_impl`) is a separate handler and still emits connection-lifecycle lines that include the full request URI — containing the full JWT passed as the `?token=` query param.

Sample line from `docker logs alice-speech-gateway` after the fix attempt:
```
INFO:     172.18.0.14:53124 - "WebSocket /ws/voice?token=eyJhbGciOiJSUzI1NiI…[full RS256 JWT]… [accepted]
INFO:     connection open
```

A 10-minute JWT is durably written to Docker's log store and any downstream log shipping on every WebSocket connection. Anyone with log access can replay the token until it expires.

## Dependencies

- Requires: PROJ-40 (Speech Gateway Service) — `alice-speech-gateway` is the container where the fix is applied

## User Stories

- Als Systembetreiber möchte ich, dass JWTs nicht in Container-Logs erscheinen, damit Angreifer mit Log-Zugriff die Token nicht bis zu deren Ablauf wiederverwenden können.

- Als Nutzer möchte ich, dass meine Authentifizierungs-Token vertraulich behandelt werden, damit meine Identität nicht durch gespeicherte Logs kompromittiert werden kann.

## Acceptance Criteria

- [x] Nach einem WebSocket-Connect auf `/api/speech/ws/stt` oder `/api/speech/ws/voice` erscheint **kein** JWT in `docker logs alice-speech-gateway`
- [x] Die bestehenden strukturierten Session-Logs des Gateways (`Voice session started`, `Voice session ended`, `Auth` rejection lines) bleiben vollständig erhalten
- [x] `curl -ks https://ki.lan/api/speech/health` liefert weiterhin `{"status":"ok",...}` (kein Startup-Fehler durch Log-Konfiguration)
- [x] `import webrtcvad` in der laufenden Umgebung: kein `ModuleNotFoundError` (keine Regression durch Dockerfile-Änderung)
- [x] Auth-Rejections (4401-Close) sind nach wie vor in den Logs sichtbar (strukturierte JSON-Logs des Gateways)

## Edge Cases

- **Log-Konfiguration schlägt beim Start fehl**: Gateway muss weiterhin starten; Log-Fehler darf keinen Service-Absturz verursachen.
- **Anderer Logger schreibt ebenfalls URLs**: Nach der Änderung prüfen, ob andere uvicorn- oder FastAPI-Logger (`uvicorn.error`, `fastapi`) URLs mit `?token=` loggen.
- **Downstream log shipping bereits aktiv**: Tokens, die vor dem Fix in Logs geschrieben wurden, können nicht zurückgenommen werden — nur neue Verbindungen werden geschützt.

## Technical Requirements

- **Scope**: Nur `alice-speech-gateway` — kein anderer Service ist betroffen.
- **Fix approach** (Backend-Entscheidung, eine der folgenden Optionen):
  1. `logging.Filter` auf dem `uvicorn.protocols.websockets.websockets_impl`-Logger, der `?token=...` aus der Nachricht entfernt, bevor sie emittiert wird. Kleinste Auswirkung.
  2. Log-Level des WebSocket-Protocol-Loggers via uvicorn `log_config` auf `WARNING` setzen. Verliert Connection-lifecycle-Zeilen — akzeptabel, da das Gateway bereits strukturierte JSON-Session-Logs emittiert.
- **Keine nginx-Änderung** nötig für diese Lösung (Option 3 aus dem QA-Bericht — Token in Header umschreiben — ist Out-of-Scope).
- **Verify**: Nach Rebuild: `docker logs alice-speech-gateway` nach 3 WS-Connects → keine Zeile mit `?token=` oder `eyJ`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Root Cause (Corrected after implementation)

The spec assumed the `[accepted]` message came from `uvicorn.protocols.websockets.websockets_impl`. In **uvicorn 0.49**, `WebSocketProtocol.__init__` passes `logger=logging.getLogger("uvicorn.error")` to the websockets library's `WebSocketServerProtocol` parent. All lifecycle logs — including `"WebSocket /ws/voice?token=..." [accepted]` — are emitted via `uvicorn.error`, which has `propagate=False` and its own StreamHandler using the default uvicorn format. `--no-access-log` does not touch this logger.

### Fix

**File:** `app/logging_config.py`

**Approach:** Add a `_TokenRedactFilter` to the `uvicorn.error` logger in `setup_logging()`. The filter intercepts every log record before formatting and replaces `?token=<value>` (and `&token=<value>`) with `?token=<redacted>` in both the format string and the args tuple. Because it returns `True`, all records still pass through — only the credential is stripped. The filter attaches to the logger itself (not a specific handler), so it covers all handlers regardless of propagation.

**Why a filter over level suppression:** `uvicorn.error` also carries genuine error messages (ASGI exceptions, startup failures). Raising its level to WARNING would hide errors. The filter approach is surgical: it touches only the query-string content, not the log structure.

### Affected Components

```
alice-speech-gateway/
+-- app/
    +-- logging_config.py   ← _TokenRedactFilter class + 1 line in setup_logging()
    +-- main.py             ← no change
+-- Dockerfile              ← no change
```

### Before / After

| Logger | Before | After |
|--------|--------|-------|
| `uvicorn.access` | Silenced by `--no-access-log` | Unchanged |
| `uvicorn.error` | Leaks `?token=<JWT>` at INFO | `?token=<redacted>` — token stripped |
| Gateway JSON logger | Structured session/auth logs | Unchanged |

## QA Test Results

**Tested:** 2026-06-15 on ki.lan (uvicorn 0.49.0, alice-speech-gateway)

**Test procedure:** 3 WebSocket upgrade requests to `http://<gateway-ip>:10301/ws/voice?token=eyJFAKETOKEN123` directly against the gateway container.

**Results:**

| Criterion | Result |
|-----------|--------|
| No JWT in `docker logs` after 3 WS connects | **PASS** — `grep 'eyJ'` returns nothing |
| `?token=<redacted>` present instead | **PASS** — `INFO: ... "WebSocket /ws/voice?token=<redacted>" [accepted]` |
| Gateway structured JSON logs intact | **PASS** — auth rejections visible as `{"logger":"alice-speech-gateway.ws","msg":"WS auth rejected: Token ungültig"}` |
| Health endpoint returns `{"status":"ok",...}` | **PASS** — `curl -sk https://ki.lan/api/speech/health` → `{"status":"ok","jwt_public_key":true,"wyoming_enabled":true,"whisper_model":"large-v3"}` |
| No Dockerfile change → no webrtcvad regression | **PASS** — Dockerfile unchanged, container running |

**No bugs found. All acceptance criteria met.**

## Deployment

**Deployed:** 2026-06-15
**Tag:** `v2.1.2-PROJ-47`

- Only changed file: `app/logging_config.py` in `alice-speech-gateway`
- No Dockerfile change, no nginx change, no n8n workflow, no DB migration
- Synced via `./scripts/sync-compose.sh` → rebuilt on ki.lan → container recreated
- Production health verified: `{"status":"ok","jwt_public_key":true,"wyoming_enabled":true}`
