# PROJ-9: Chat-Fenster & JWT-Schutz

## Status: In Progress
**Created:** 2026-02-28
**Last Updated:** 2026-02-28

## Dependencies
- Requires: PROJ-7 (JWT Auth / Login Screen) — JWT-Signierung, `alice_token` in localStorage, `auth.ts`

---

## Übersicht

Dieses Feature schließt zwei zusammenhängende Lücken:

1. **Chat-Fenster (Frontend):** Das erste nutzbare Chat-UI — Nachrichten eingeben, Antworten von Alice empfangen, neue Chats starten. Nach dem Login startet automatisch ein neuer Chat. Der "Neuer Chat"-Button in der Sidebar wird funktional.

2. **JWT-Schutz (Backend + Frontend):** Der `alice-chat-handler`-Webhook prüft den `Authorization: Bearer`-Header. Kein gültiges JWT → sofortiger 401. `user_id` kommt aus dem JWT-Claim, nicht mehr aus dem Body. Das Frontend sendet den Token automatisch mit und behandelt 401-Antworten mit Auto-Logout.

---

## User Stories

### Chat-Fenster
1. **Als Nutzer** möchte ich nach dem Login sofort ein Chat-Fenster sehen, ohne einen Button drücken zu müssen, damit ich ohne Umwege mit Alice sprechen kann.
2. **Als Nutzer** möchte ich eine Nachricht eingeben und absenden (Enter oder Button), damit ich Alice Fragen stellen kann.
3. **Als Nutzer** möchte ich Alices Antwort im Chat-Fenster sehen, sobald sie verfügbar ist, damit ich eine Konversation führen kann.
4. **Als Nutzer** möchte ich sehen, wenn Alice gerade antwortet (Typing Indicator), damit ich weiß dass meine Nachricht angekommen ist.
5. **Als Nutzer** möchte ich mit "Neuer Chat" in der Sidebar einen frischen Chat starten, damit ich Themen voneinander trennen kann.
6. **Als Nutzer** möchte ich meine bisherigen Chats in der Sidebar sehen (nach Datum gruppiert), damit ich frühere Gespräche wieder aufrufen kann.

### JWT-Schutz
7. **Als Nutzer** möchte ich, dass meine Chat-Anfragen automatisch mit meiner Authentifizierung gesendet werden, ohne dass ich mich darum kümmern muss.
8. **Als Nutzer** möchte ich bei einer abgelaufenen Session automatisch zum Login-Screen weitergeleitet werden, damit meine Daten geschützt bleiben.
9. **Als Admin** möchte ich, dass der Chat-Endpoint ohne gültiges JWT nicht erreichbar ist, damit unautorisierter Zugriff verhindert wird.
10. **Als Entwickler** möchte ich, dass `user_id` aus dem JWT-Claim gelesen wird (nicht aus dem Body), damit Clients ihre eigene `user_id` nicht manipulieren können.

---

## Acceptance Criteria

### Frontend — Chat-Fenster

- [ ] Nach dem Login wird automatisch ein neuer Chat gestartet (leeres Chat-Fenster sichtbar, keine manuelle Aktion nötig)
- [ ] Das Chat-Fenster zeigt eine leere Nachrichtenliste mit einem Willkommenshinweis wenn noch keine Nachrichten vorhanden sind
- [ ] Der Nutzer kann eine Nachricht in ein Texteingabefeld eingeben
- [ ] Absenden via Enter-Taste (ohne Shift) oder Send-Button
- [ ] Die eigene Nachricht erscheint sofort im Chat (rechts, User-Bubble)
- [ ] Während Alice antwortet, ist ein Typing Indicator sichtbar (links, als Platzhalter)
- [ ] Alices Antwort ersetzt den Typing Indicator und wird links angezeigt
- [ ] Das Send-Button und Eingabefeld sind während des laufenden Requests deaktiviert (kein Doppel-Submit)
- [ ] Bei einem Fehler (Netzwerk, 500) erscheint eine Fehlermeldung im Chat statt dem Typing Indicator
- [ ] Die Nachrichtenliste scrollt automatisch nach unten wenn neue Nachrichten erscheinen
- [ ] Der "Neuer Chat"-Button in der Sidebar erstellt eine neue Session und leert das Chat-Fenster
- [ ] Jede Session bekommt als Titel die ersten 40 Zeichen der ersten User-Nachricht
- [ ] Sessions erscheinen in der Sidebar-Liste (nach Datum gruppiert)
- [ ] Ein Klick auf eine Session in der Sidebar lädt deren Nachrichten ins Chat-Fenster

### Frontend — `services/api.ts`

- [ ] `services/api.ts` wird neu erstellt mit einer `sendMessage()`-Funktion
- [ ] Jeder Chat-Request enthält den Header `Authorization: Bearer <token>`
- [ ] Antwortet der Server mit HTTP 401 → Token löschen + `window.location.href = '/login'`
- [ ] Ist kein Token vorhanden → sofortiger Redirect zu `/login`, kein Request
- [ ] Bei Netzwerk-/Serverfehlern wird ein beschreibender Error geworfen

### Backend — n8n `alice-chat-handler`

- [ ] Der Webhook liest den `Authorization: Bearer <token>`-Header
- [ ] Fehlt der Header oder ist das Format ungültig → sofort HTTP 401, keine weitere Verarbeitung
- [ ] Das JWT wird mit `JWT_SECRET` verifiziert (Signatur + Ablaufzeit)
- [ ] Ungültiges oder abgelaufenes Token → HTTP 401
- [ ] `user_id` kommt aus dem JWT-Claim — der Body-Parameter `user_id` wird ignoriert
- [ ] `username` und `role` aus dem JWT stehen für Logging zur Verfügung
- [ ] Alle nachfolgenden Nodes verwenden `user_id` aus dem JWT

---

## Edge Cases

- **Seite wird neu geladen:** Session-Metadaten (id, title, updatedAt) bleiben via localStorage erhalten; Nachrichten innerhalb der Session gehen verloren (in-memory) — akzeptiert für Phase 1.5
- **Token läuft während Chat ab:** Nächste Anfrage erhält 401 → Auto-Logout + Redirect
- **Token fehlt beim Senden:** Kein Request, sofortiger Redirect
- **Manipulation von `user_id` im Body:** Serverseitig ignoriert — nur JWT-Claim zählt
- **Leere Nachricht absenden:** Send-Button bleibt deaktiviert solange Eingabe leer/nur Whitespace
- **Sehr lange Antwort von Alice:** Chat scrollt fortlaufend nach unten, kein Layout-Bruch
- **Netzwerkfehler während Typing:** Fehlermeldung als Chat-Nachricht (links), Eingabe wird wieder aktiviert
- **Session löschen:** Session wird aus Sidebar und localStorage entfernt; wenn aktiv → automatisch neuer Chat

---

## Technical Requirements

- **Nachrichten-Persistenz:** Session-Metadaten in `localStorage`; Nachrichten pro Session in React State (in-memory) — Vollpersistenz via DB ist PROJ-10+
- **JWT_SECRET:** Bereits als n8n-Umgebungsvariable gesetzt (PROJ-7)
- **Keine neuen npm-Pakete:** JWT-Verifikation in n8n via built-in `crypto`; `uuid` via `crypto.randomUUID()` (built-in)
- **Kein Token-Blacklisting:** Token läuft nach 24h ab (Phase 1.5)
- **Request-Format:** OpenAI-kompatibel — `{ messages: [...], session_id: "..." }` — `user_id` wird nicht mehr gesendet

---

## Neue und geänderte Dateien

| Datei | Änderung |
|---|---|
| `frontend/src/components/Chat/ChatWindow.tsx` | Neu — Container: MessageList + ChatInputArea |
| `frontend/src/components/Chat/MessageList.tsx` | Neu — scrollbare Nachrichtenliste mit Auto-Scroll |
| `frontend/src/components/Chat/MessageBubble.tsx` | Neu — User- (rechts) und Alice-Nachrichten (links) |
| `frontend/src/components/Chat/TypingIndicator.tsx` | Neu — Pulsierender "Alice antwortet..."-Indikator |
| `frontend/src/components/Chat/ChatInputArea.tsx` | Neu — Textarea + Send-Button |
| `frontend/src/hooks/useChatSessions.ts` | Neu — Session-State + localStorage-Sync |
| `frontend/src/services/api.ts` | Neu — sendMessage + Bearer-Header + 401-Handler |
| `frontend/src/components/Layout/AppShell.tsx` | Geändert — handleNewChat und Session-Management verdrahten |
| `frontend/src/app/page.tsx` | Geändert — Placeholder durch ChatWindow ersetzen |
| `workflows/core/alice-chat-handler.json` | Geändert — JWT Auth Guard + Unauthorized Response Node |

---

## Tech Design (Solution Architect)

### Übersicht

PROJ-9 besteht aus drei zusammenhängenden Teilen:

1. **Chat-Fenster (Frontend)** — neue Komponenten-Familie `Chat/` + Hook `useChatSessions`
2. **API-Service (Frontend)** — neue `services/api.ts` mit JWT-Header und 401-Handler
3. **JWT-Schutz (n8n)** — neuer Guard-Node im `alice-chat-handler`

---

### A) Frontend — Komponentenstruktur

```
AppShell (bestehend — erweitert)
├── Sidebar (bestehend — NewChatButton jetzt funktional)
│   ├── NewChatButton  → löst handleNewChat() aus
│   └── ChatList       → zeigt echte Sessions aus useChatSessions
└── Hauptbereich
    ├── [leer, kein aktiver Chat] → Empty State: "Starte einen neuen Chat"
    └── ChatWindow (NEU)
        ├── MessageList (NEU)
        │   ├── [leer] → Welcome Message: "Wie kann ich helfen?"
        │   ├── MessageBubble × n (NEU)
        │   │   ├── User-Nachricht  (rechts, grau)
        │   │   └── Alice-Antwort   (links, kein Bubble)
        │   └── TypingIndicator (NEU) — sichtbar während API-Call
        └── ChatInputArea (NEU)
            ├── Textarea (shadcn, auto-resize)
            └── Send-Button (shadcn, deaktiviert während Loading)
```

---

### B) Auto-Start nach Login

Nach einem erfolgreichen Login landet der Nutzer auf `/`. Die `AppShell` prüft beim Mounten:

```
AppShell mountet
  └── Keine aktive Session?
        → handleNewChat() automatisch aufrufen
        → Neues ChatWindow mit leerer Nachrichtenliste öffnen
```

Das heißt: der Nutzer sieht nach dem Login sofort ein leeres Chat-Fenster mit Eingabefeld — kein Klick nötig.

---

### C) Session-Datenmodell

**Wo gespeichert:** Session-Metadaten in `localStorage`; Nachrichten in React State (in-memory).

```
Session (localStorage):
  id        — UUID (crypto.randomUUID())
  title     — erste 40 Zeichen der ersten User-Nachricht
  updatedAt — Zeitstempel der letzten Aktivität

Nachrichten (React State, pro Session):
  role      — "user" oder "assistant"
  content   — Nachrichtentext
  timestamp — Zeitstempel
```

**Warum localStorage für Metadaten, State für Nachrichten?**
Sessions bleiben nach Page-Reload in der Sidebar sichtbar. Nachrichten-Persistenz (DB-Anbindung) ist PROJ-10+. Für Phase 1.5 ist der Verlust von Nachrichten nach Reload akzeptiert.

---

### D) Hook `useChatSessions`

Neuer Hook der die gesamte Session-Logik kapselt und von `AppShell` genutzt wird:

```
useChatSessions gibt zurück:
  sessions          — Liste aller Sessions (aus localStorage)
  activeSessionId   — aktive Session-ID
  messages          — Nachrichten der aktiven Session (aus State)
  isLoading         — true während API-Call läuft
  createNewSession()  → neue Session anlegen + aktivieren
  selectSession(id)   → andere Session aktivieren
  deleteSession(id)   → Session entfernen
  sendMessage(text)   → Nachricht senden (ruft api.ts auf)
```

---

### E) Nachrichtenfluss (sendMessage)

```
Nutzer sendet Nachricht
  ↓
useChatSessions.sendMessage(text)
  ├── User-Nachricht sofort in State hinzufügen (optimistic)
  ├── isLoading = true → TypingIndicator sichtbar
  ├── api.ts.sendMessage(allMessages, sessionId)
  │     → POST /api/webhook/v1/chat/completions
  │         Header: Authorization: Bearer <token>
  │         Body: { messages: [...], session_id }
  ├── Bei 401 → clearToken() + window.location.href = '/login'
  ├── Bei Fehler → Fehler-Nachricht in State einfügen
  └── Bei Erfolg → Alice-Antwort in State einfügen
        isLoading = false → TypingIndicator verschwindet
```

---

### F) n8n Workflow — Geänderter Ablauf

**Aktuell:**
```
Webhook → Input Validator (user_id aus Body) → Empty Check → [...]
```

**Nach PROJ-9:**
```
Webhook (JWT-Auth nativ aktiviert)
  ├── Kein / ungültiger / abgelaufener Token
  │     → n8n gibt automatisch HTTP 401 zurück
  │         [Workflow endet hier — kein extra Node nötig]
  └── Gültiger Token → Workflow läuft weiter
  ↓
[NEU] JWT Claims Extractor (Code Node — nur dekodieren, nicht verifizieren)
  → liest user_id, username, role aus dem bereits verifizierten Payload
  ↓
Input Validator (geändert: user_id aus JWT-Claims, nicht Body)
  ↓
Empty Input Check
  ↓
[... Rest unverändert ...]
```

**JWT-Verifikation:** Nativ im Webhook-Node über n8n's eingebaute JWT-Credential. n8n unterstützt HS256 und weitere Algorithmen direkt — kein Code-Node, kein `crypto`, kein externes npm-Paket.

**JWT-Credential in n8n:** Wird einmalig in n8n unter *Credentials → JWT* mit dem `JWT_SECRET` aus der n8n `.env` angelegt. Der Webhook-Node referenziert diese Credential.

**JWT Claims Extractor:** Ein einfacher Code-Node der den mittleren Teil des Tokens (Payload) base64url-dekodiert und die Claims als Felder weitergibt. Keine Kryptographie — die Verifikation hat der Webhook-Node bereits erledigt.

---

### G) Request-Format (vorher/nachher)

| Feld | Vorher | Nachher |
|---|---|---|
| Header `Authorization` | — | `Bearer <jwt>` (required) |
| Body `messages` | ✅ bleibt | ✅ bleibt |
| Body `session_id` | ✅ bleibt | ✅ bleibt |
| Body `user_id` | gesendet (unsicher) | entfernt |

---

### H) Tech-Entscheidungen

| Entscheidung | Begründung |
|---|---|
| Chat-Komponenten unter `components/Chat/` | Klare Trennung vom bestehenden Sidebar/Auth-Code; eigener Namespace |
| Session-Metadaten in localStorage | Sidebar bleibt nach Page-Reload nutzbar; volle DB-Persistenz ist PROJ-10 |
| Nachrichten in React State (in-memory) | Einfachste Lösung für Phase 1.5; verhindert Over-Engineering |
| `useChatSessions`-Hook statt Context | Single-Responsibility; AppShell ist der einzige Consumer |
| Auto-Start nach Login im AppShell-Mount | Nutzer wartet nach Login nicht auf manuellen Klick — direkter Einstieg |
| n8n nativer JWT-Auth auf Webhook (kein Code-Node) | n8n hat eingebaute JWT-Verifikation inkl. HS256 — kein Custom-Code, kein `crypto`, automatisches 401 |
| `window.location.href` bei 401 | Vollständiger Page-Reload löscht State sauber; konsistent mit PROJ-7 |

---

### I) Keine neuen npm-Pakete

Alle benötigten Abhängigkeiten sind bereits installiert:

| Was | Woher |
|---|---|
| `uuid` für Session-IDs | `crypto.randomUUID()` — Browser built-in |
| JWT-Payload lesen | `jose` — bereits installiert (PROJ-7) |
| UI-Komponenten | `shadcn/ui` — Textarea, Button, ScrollArea bereits vorhanden |
| Icons | `lucide-react` — bereits installiert |

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
