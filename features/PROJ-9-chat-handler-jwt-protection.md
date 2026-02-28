# PROJ-9: Chat-Handler JWT-Schutz

## Status: Planned
**Created:** 2026-02-28
**Last Updated:** 2026-02-28

## Dependencies
- Requires: PROJ-7 (JWT Auth / Login Screen) — JWT-Signierung, `alice_token` in localStorage, `auth.ts`

---

## Übersicht

Der `alice-chat-handler`-Webhook ist aktuell ohne Authentifizierung erreichbar. Jeder der die URL kennt, kann Anfragen stellen. Dieses Feature schließt diese Sicherheitslücke:

1. **Backend (n8n):** Der Chat-Webhook prüft den `Authorization: Bearer`-Header und liest `user_id` aus dem JWT-Claim — nicht mehr aus dem Request-Body.
2. **Frontend:** `services/api.ts` wird erstellt und sendet den gespeicherten JWT bei jedem Chat-Request automatisch mit. 401-Antworten lösen automatischen Logout + Redirect zu `/login` aus.

---

## User Stories

1. **Als Nutzer** möchte ich, dass meine Chat-Anfragen automatisch mit meiner Authentifizierung gesendet werden, ohne dass ich mich darum kümmern muss.
2. **Als Nutzer** möchte ich bei einer abgelaufenen Session automatisch zum Login-Screen weitergeleitet werden, damit meine Daten geschützt bleiben.
3. **Als Admin** möchte ich, dass der Chat-Endpoint ohne gültiges JWT nicht erreichbar ist, damit unautorisierter Zugriff verhindert wird.
4. **Als Entwickler** möchte ich, dass `user_id` aus dem JWT-Claim gelesen wird (nicht aus dem Body), damit Clients ihre eigene `user_id` nicht manipulieren können.

---

## Acceptance Criteria

### Backend — n8n `alice-chat-handler`

- [ ] Der Webhook liest den `Authorization: Bearer <token>`-Header aus dem Request
- [ ] Fehlt der Header oder ist das Format ungültig → sofort HTTP 401 zurückgeben, keine weitere Verarbeitung
- [ ] Das JWT wird mit `JWT_SECRET` verifiziert (Signatur + Ablaufzeit)
- [ ] Ist das Token ungültig oder abgelaufen → HTTP 401
- [ ] `user_id` wird aus dem JWT-Claim `user_id` gelesen — der `user_id`-Parameter im Request-Body wird ignoriert
- [ ] `username` und `role` aus dem JWT werden für Logging verfügbar gemacht
- [ ] Alle nachfolgenden Nodes verwenden `user_id` aus dem JWT (nicht aus dem Body)

### Frontend — `services/api.ts`

- [ ] `services/api.ts` wird neu erstellt mit einer `sendMessage()`-Funktion (oder gleichwertig)
- [ ] Jeder Chat-Request enthält den Header `Authorization: Bearer <token>` (Token aus `localStorage` via `getToken()` aus `auth.ts`)
- [ ] Antwortet der Server mit HTTP 401 → Token aus localStorage löschen + `window.location.href = '/login'`
- [ ] Ist kein Token in localStorage → kein Request wird gesendet, direkter Redirect zu `/login`
- [ ] Die Funktion wirft bei anderen Fehlern (500, Netzwerk) einen beschreibenden Error

---

## Edge Cases

- **Token läuft während aktiver Chat-Session ab:** Nächste Chat-Anfrage erhält 401 → automatischer Logout + Redirect, kein stiller Fehler
- **Token fehlt beim Senden:** Kein Request, sofortiger Redirect zu `/login`
- **Manipulation von `user_id` im Body:** Wird serverseitig ignoriert — `user_id` kommt ausschließlich aus dem JWT
- **Gleichzeitige Requests bei 401:** Beide lösen Redirect aus; da `window.location.href` zugewiesen wird, ist das unproblematisch
- **n8n JWT-Verifikation schlägt fehl (falscher `JWT_SECRET`):** 401 zurück — kein Leak von Fehlerdetails

---

## Technical Requirements

- **JWT_SECRET:** Muss in n8n als Umgebungsvariable verfügbar sein (bereits vorhanden seit PROJ-7)
- **Kein neues npm-Paket nötig:** JWT-Verifikation in n8n via Code-Node (jose oder crypto built-in); `jose` ist bereits im Frontend als Dependency vorhanden
- **Kein Caching:** JWT wird bei jeder Anfrage live verifiziert
- **Kein Token-Blacklisting:** Token läuft nach 24h natürlich ab (Phase 1.5 Scope — wie PROJ-7)
- **Rückwärtskompatibilität:** Der `session_id`-Parameter bleibt im Body; nur `user_id` wird aus dem JWT gelesen

---

## Geänderte Dateien

| Datei | Änderung |
|---|---|
| `workflows/core/alice-chat-handler.json` | JWT-Validierung als erster Node nach dem Webhook |
| `frontend/src/services/api.ts` | Neu erstellen: sendMessage + Authorization-Header + 401-Handler |

---

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
