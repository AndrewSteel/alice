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

### Übersicht

Zwei unabhängige Änderungen, die zusammen die Sicherheitslücke schließen:

1. **n8n `alice-chat-handler`** — ein neuer Code-Node direkt nach dem Webhook-Trigger prüft das JWT. Kein gültiges Token → sofortige 401-Antwort, der Rest des Workflows läuft nicht an.
2. **Frontend `services/api.ts`** — neue Datei, die alle Chat-Requests mit dem gespeicherten JWT ausstattet und 401-Antworten behandelt.

---

### A) n8n Workflow — Geänderter Ablauf

**Aktueller Ablauf:**
```
Webhook (POST /webhook/v1/chat/completions)
  ↓
Input Validator  ← liest user_id aus Body (unsicher)
  ↓
Empty Input Check
  ↓
[... Haupt-Logik ...]
```

**Neuer Ablauf nach PROJ-9:**
```
Webhook (POST /webhook/v1/chat/completions)
  ↓
[NEU] JWT Auth Guard (Code Node)
  ├── Kein / ungültiger / abgelaufener Token
  │     → Respond To Webhook: HTTP 401 {"detail": "Unauthorized"}
  │         [Workflow endet hier]
  └── Gültiger Token
        → Übergibt user_id, username, role aus JWT-Claims
  ↓
Input Validator  ← liest user_id jetzt aus JWT-Claims (sicher)
  ↓
Empty Input Check
  ↓
[... Haupt-Logik unverändert ...]
```

**Zwei neue Nodes:**
| Node | Typ | Zweck |
|---|---|---|
| JWT Auth Guard | Code Node | Bearer-Token aus Header lesen, Signatur + Ablaufzeit prüfen, Claims extrahieren |
| Unauthorized Response | Respond To Webhook | Sofort HTTP 401 zurückgeben wenn Token fehlt/ungültig |

**Geänderte Node:**
| Node | Änderung |
|---|---|
| Input Validator | `userId` nicht mehr aus `body.user_id` lesen, sondern aus den JWT-Claims des vorherigen Nodes |

---

### B) JWT-Verifikation im Code-Node (Technischer Ansatz)

n8n erlaubt in Code-Nodes Node.js built-in Module. JWT HS256 kann ohne externe Bibliotheken verifiziert werden:

- Das Token wird in drei Teile zerlegt: Header, Payload, Signatur (Base64url-kodiert)
- Die Signatur wird mit `crypto.createHmac('sha256', JWT_SECRET)` nachberechnet und verglichen
- Der Payload wird dekodiert und das `exp`-Feld gegen die aktuelle Uhrzeit geprüft

`JWT_SECRET` ist bereits als n8n-Umgebungsvariable gesetzt (seit PROJ-7) und via `$env.JWT_SECRET` im Code-Node abrufbar.

**Kein neues npm-Paket nötig.** Der compose.yml erlaubt nur `axios` als externe Bibliothek — built-in `crypto` ist immer verfügbar.

---

### C) Frontend — `services/api.ts`

**Neue Datei** (neben dem bestehenden `services/auth.ts`):

```
frontend/src/services/
├── auth.ts     (bestehend — Login, Logout, Validate, Token-Management)
└── api.ts      (NEU — Chat-Requests mit JWT)
```

**Verantwortlichkeiten von `api.ts`:**

```
sendMessage(messages, sessionId)
  ├── Kein Token in localStorage?
  │     → window.location.href = '/login'  [kein Request]
  ├── POST /api/webhook/v1/chat/completions
  │     Header: Authorization: Bearer <token>
  │     Body: { messages, session_id }
  ├── HTTP 401?
  │     → clearToken() + window.location.href = '/login'
  ├── Netzwerk-/Serverfehler?
  │     → throw Error mit beschreibender Meldung
  └── HTTP 200?
        → Response-JSON zurückgeben
```

**Warum kein `user_id` mehr im Body?**
Nach PROJ-9 liest der Chat-Handler `user_id` ausschließlich aus dem JWT-Claim. `api.ts` sendet `user_id` daher nicht mehr — der Wert käme ohnehin aus dem Token.

**Nginx-Routing (unverändert):**
```
POST /api/webhook/v1/chat/completions
  → nginx: rewrite /api → /webhook
  → n8n: POST /webhook/v1/chat/completions
```

---

### D) Request-Format (vorher/nachher)

| Feld | Vorher | Nachher |
|---|---|---|
| Header `Authorization` | — | `Bearer <jwt>` (neu, required) |
| Body `messages` | ✅ bleibt | ✅ bleibt |
| Body `session_id` | ✅ bleibt | ✅ bleibt |
| Body `user_id` | gesendet (unsicher) | nicht mehr gesendet |

---

### E) Tech-Entscheidungen

| Entscheidung | Begründung |
|---|---|
| JWT-Prüfung via built-in `crypto` (kein jose) | n8n-Sandbox erlaubt nur `axios` als externe Bibliothek; `crypto` ist immer verfügbar |
| Guard als erster Node (vor Input Validator) | Schnelles Fail-Fast: unautorisierte Requests werden sofort abgebrochen, keine DB-Queries |
| `user_id` aus JWT, nicht aus Body | Verhindert Manipulation: ein Client kann nicht die `user_id` eines anderen Nutzers angeben |
| 401 ohne Fehlerdetails (`{"detail": "Unauthorized"}`) | Kein Leak von Informationen (abgelaufen vs. ungültig vs. fehlt — alles gleich) |
| `window.location.href` für Logout-Redirect | Vollständiger Page-Reload löscht App-State; konsistent mit Login-Redirect aus PROJ-7 |

---

### F) Betroffene Dateien

| Datei | Änderung |
|---|---|
| `workflows/core/alice-chat-handler.json` | 2 neue Nodes (JWT Auth Guard + Unauthorized Response), Input Validator angepasst |
| `frontend/src/services/api.ts` | Neue Datei |

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
