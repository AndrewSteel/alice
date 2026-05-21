# PROJ-36: RS256 Migration — Vollständige Umstellung aller Komponenten

## Status: Deployed
**Created:** 2026-05-10
**Last Updated:** 2026-05-10

## Kontext & Motivation

PROJ-34 hat `alice-auth` von HS256 auf RS256 umgestellt. Dabei wurden `alice-auth` und `alice-chat-stream` korrekt migriert. Das n8n-JWT-Credential `4iUJhbFCSgQeHAGL` ("JWT Auth account") wurde jedoch nicht aktualisiert — es prüft Tokens weiterhin mit HS256 + Shared Secret. Da alice-auth nun RS256-Tokens ausstellt, schlägt die Validierung in n8n fehl.

**Sichtbare Fehler:**
1. **Sidebar (PROJ-14):** 403 auf `GET /api/webhook/alice/sessions` → keine alten Chats sichtbar
2. **DMS (PROJ-15/25/28):** 403 auf `GET /api/webhook/dms/folders` → Frontend zeigt "Zugriff verweigert - Admin-Rechte erforderlich"

## Dependencies

- Requires: PROJ-34 (RS256-Migration in alice-auth — abgeschlossen)
- Fixes: PROJ-14 (Sidebar Session API), PROJ-15/25/28 (DMS Folder API)

## Betroffene Komponenten (Audit-Ergebnis)

| Komponente                        | JWT-Prüfung                                       | Status nach PROJ-34                                           |
| --------------------------------- | ------------------------------------------------- | ------------------------------------------------------------- |
| `alice-auth`                      | Signiert (Private Key) + verifiziert (Public Key) | ✅ Korrekt RS256                                               |
| `alice-chat-stream`               | Verifiziert mit Public Key (Python PyJWT)         | ✅ Korrekt RS256                                               |
| n8n Credential `4iUJhbFCSgQeHAGL` | HS256 + Shared Secret                             | ❌ Noch HS256 → alle n8n-Webhooks mit jwtAuth fehlerhaft       |
| `alice-session-api` (n8n)         | Benutzt o.g. Credential                           | ❌ 403 auf allen Endpunkten                                    |
| `alice-dms-folder-api` (n8n)      | Benutzt o.g. Credential                           | ❌ 403 auf allen Endpunkten                                    |
| `alice-chat-handler` (n8n)        | Benutzt o.g. Credential                           | ⚠️ Betroffen, aber Chat läuft über alice-chat-stream (PROJ-30) |
| `n8n/.env`                        | `JWT_SECRET` noch gesetzt                         | 🧹 Aufräumen (Credential braucht kein Secret mehr)             |
| Frontend                          | Leitet JWT opak weiter                            | ✅ Nicht betroffen                                             |
| nginx                             | Prüft kein JWT                                    | ✅ Nicht betroffen                                             |

## User Stories

- Als Nutzer möchte ich die Sidebar mit meinen alten Chats sehen, damit ich den Gesprächsverlauf weiterführen kann.
- Als Admin möchte ich das DMS aufrufen können, damit ich Ordner verwalten kann.
- Als Entwickler möchte ich, dass alle n8n-Webhook-Endpunkte RS256-Tokens korrekt validieren, damit die Sicherheit der HS256→RS256-Migration vollständig ist.
- Als Operator möchte ich, dass `JWT_SECRET` aus der n8n-Umgebung entfernt wird, damit kein veraltetes Secret im System verbleibt.

## Acceptance Criteria

### AC-1: n8n JWT Credential auf RS256 aktualisiert
- [ ] n8n-Credential `4iUJhbFCSgQeHAGL` ("JWT Auth account") verwendet `RS256` als Algorithmus
- [ ] Das Credential enthält den Public Key (Inhalt von `/srv/warm/alice/keys/jwt_public.pem`)
- [ ] Das Credential enthält **kein** Shared Secret mehr

### AC-2: alice-session-api (Sidebar) funktioniert wieder
- [ ] `GET /api/webhook/alice/sessions` mit gültigem RS256-Token → 200 + Session-Liste
- [ ] Sidebar zeigt bestehende Chats nach Login
- [ ] `GET /api/webhook/alice/sessions/:id/messages` → 200 + Nachrichtenliste
- [ ] `PATCH /api/webhook/alice/sessions/:id` → 200
- [ ] `DELETE /api/webhook/alice/sessions/:id` → 204

### AC-3: alice-dms-folder-api (DMS) funktioniert wieder
- [ ] `GET /api/webhook/dms/folders` mit gültigem RS256-Token (Admin) → 200 + Ordnerliste
- [ ] Frontend DMS zeigt keine Fehlermeldung "Zugriff verweigert" mehr
- [ ] `POST`, `PUT`, `DELETE` auf `/api/webhook/dms/folders` funktionieren korrekt

### AC-4: alice-chat-handler (n8n) verifiziert RS256-Tokens
- [ ] Webhook-Endpunkte in `alice-chat-handler` akzeptieren RS256-Tokens
- [ ] Kein Regressionstest nötig (primäre Chat-Route ist alice-chat-stream), aber Credential-Update gilt automatisch

### AC-5: JWT_SECRET aus n8n-Umgebung entfernt
- [ ] `JWT_SECRET` ist aus `docker/compose/automations/n8n/.env` entfernt (oder als veraltet kommentiert)
- [ ] n8n-Container-Neustart nach `.env`-Änderung erfolgt

### AC-6: Vollständiger Audit dokumentiert
- [ ] Alle Komponenten mit JWT-Verarbeitung sind identifiziert und ihr Status ist dokumentiert
- [ ] Keine weitere Komponente verwendet noch HS256 mit dem alten `JWT_SECRET`

## Edge Cases

- **Gültige RS256-Tokens von anderen Benutzern**: Nach Credential-Update funktionieren alle bestehenden RS256-Tokens. Keine Re-Login-Pflicht.
- **Abgelaufene HS256-Tokens**: Da JWT-Expiry 24h ist und PROJ-34 bereits deployed ist, sind keine HS256-Tokens mehr im Umlauf. Kein Fallback nötig.
- **n8n-Neustart nach Credential-Update**: n8n lädt Credentials beim Start. Ein Neustart nach dem Credential-Update ist ausreichend (kein Workflow-Redeploy nötig).
- **Credential-Update nicht in Git**: n8n-Credentials werden in der n8n-Datenbank gespeichert, nicht in den Workflow-JSONs — kein Git-Commit für das Credential selbst nötig.
- **Public Key enthält Zeilenumbrüche**: n8n-Credential-Felder unterstützen mehrzeilige Eingaben. Der PEM-Schlüssel muss inkl. `-----BEGIN PUBLIC KEY-----` Header eingegeben werden.

## Technical Requirements

### Schritt 1: n8n Credential aktualisieren (manuell im n8n UI)

1. n8n öffnen → Credentials → `4iUJhbFCSgQeHAGL` ("JWT Auth account")
2. Algorithm: `RS256`
3. Key: Inhalt von `/srv/warm/alice/keys/jwt_public.pem` (auf dem Server: `ssh stan@ki.lan cat /srv/warm/alice/keys/jwt_public.pem`)
4. Credential speichern

### Schritt 2: n8n/.env bereinigen

Aus `docker/compose/automations/n8n/.env` entfernen:
```
JWT_SECRET=e1b2886f3...
```

### Schritt 3: n8n-Container neustarten

```bash
# Nach .env-Änderung via sync-compose.sh + SSH
ssh stan@ki.lan "cd /opt/alice && docker compose -f docker/compose/automations/n8n/compose.yml restart"
```

### Kein Workflow-JSON-Update nötig

Die Workflow-JSONs (`alice-session-api.json`, `alice-dms-folder-api.json`, `alice-chat-handler.json`) referenzieren das Credential nur per ID. Das Credential-Update im n8n UI wirkt sofort für alle Workflows ohne JSON-Änderung.

---

Die Änderungen wurden manuell durchgeführt. Das Dokuemnt verbleibt zur notwendigen Dokuemntation der Umstellung im Repository.
