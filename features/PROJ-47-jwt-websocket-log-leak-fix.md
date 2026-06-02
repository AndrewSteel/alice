# PROJ-47: JWT WebSocket Log Leak Fix

## Status: Planned
**Created:** 2026-06-02
**Last Updated:** 2026-06-02

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

- [ ] Nach einem WebSocket-Connect auf `/api/speech/ws/stt` oder `/api/speech/ws/voice` erscheint **kein** JWT in `docker logs alice-speech-gateway`
- [ ] Die bestehenden strukturierten Session-Logs des Gateways (`Voice session started`, `Voice session ended`, `Auth` rejection lines) bleiben vollständig erhalten
- [ ] `curl -ks https://ki.lan/api/speech/health` liefert weiterhin `{"status":"ok",...}` (kein Startup-Fehler durch Log-Konfiguration)
- [ ] `import webrtcvad` in der laufenden Umgebung: kein `ModuleNotFoundError` (keine Regression durch Dockerfile-Änderung)
- [ ] Auth-Rejections (4401-Close) sind nach wie vor in den Logs sichtbar (strukturierte JSON-Logs des Gateways)

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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
