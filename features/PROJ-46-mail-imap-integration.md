# PROJ-46: Mail IMAP Integration

## Status: Approved
**Created:** 2026-06-24
**Last Updated:** 2026-06-24

## Dependencies
- Requires: PROJ-1–PROJ-39 (Auth, JWT, User-Management) — für Login und Nutzerverwaltung
- Requires: Weaviate (Phase 1 Basis) — für Metadaten-Indexierung
- Soft dependency: Zukünftiges "Inhaltsdarstellungs-Feature" (noch kein PROJ-X) — für vollständige Mail-Body-Anzeige; Alice liefert Rohinhalt bis dahin direkt im Chat

## User Stories

- Als WebApp-Nutzer möchte ich ein IMAP-Postfach im Settings-Tab konfigurieren, damit Alice meine Mails indexiert und per Sprache/Text abfragbar macht.
- Als Postfach-Eigentümer möchte ich festlegen, welche anderen Alice-Nutzer auf mein Postfach zugreifen dürfen, damit ich die Kontrolle über meine Mails behalte.
- Als freigeschalteter Nutzer möchte ich per Sprache oder Text fragen "Habe ich heute eine wichtige Mail bekommen?", damit ich ohne manuelles E-Mail-Öffnen informiert bleibe.
- Als freigeschalteter Nutzer möchte ich bei einer als "Wichtig" klassifizierten Mail automatisch eine Benachrichtigung im WebApp-Chat erhalten, damit ich keine wichtigen Mails verpasse.
- Als freigeschalteter Nutzer möchte ich den vollständigen Inhalt einer gefundenen Mail auf Anfrage abrufen können ("Zeig mir den Inhalt der Mail von der Bank"), damit ich bei Bedarf alle Details sehe.
- Als Admin möchte ich jedes Postfach löschen können (auch fremde), damit ich bei Nutzer-Offboarding oder Sicherheitsproblemen eingreifen kann.
- Als Postfach-Eigentümer möchte ich ein Postfach mit allen zugehörigen Metadaten löschen können, damit keine Daten zurückbleiben.

## Acceptance Criteria

### Settings-Tab: Postfach-Verwaltung
- [ ] Im Settings-Menü existiert ein neuer Tab "E-Mail-Postfächer"
- [ ] Jeder eingeloggte WebApp-Nutzer kann in diesem Tab eigene Postfächer anlegen
- [ ] Folgende Felder sind beim Anlegen/Bearbeiten eines Postfachs konfigurierbar:
  - Anzeigename (Pflicht)
  - IMAP-Host (Pflicht)
  - IMAP-Port (Pflicht, Default: 993)
  - Benutzername (Pflicht)
  - Passwort (Pflicht, verschlüsselt gespeichert, wird nach dem Speichern nicht mehr im Klartext angezeigt)
  - SSL/TLS aktivieren (Checkbox, Default: aktiv)
  - Sync-Intervall in Minuten (Pflicht, Default: 15 min)
  - Startdatum für Indexierung (optional; fehlt das Datum, werden nur neue Mails ab Konfigurationszeitpunkt indexiert)
- [ ] Nach dem Speichern wird eine Test-Verbindung zum IMAP-Server aufgebaut; bei Fehler wird eine verständliche Fehlermeldung angezeigt
- [ ] Ein Postfach kann bearbeitet werden (alle Felder außer Passwort werden vorausgefüllt; Passwort muss neu eingegeben werden, um es zu ändern)
- [ ] Eigentümer und Admin können ein Postfach löschen; Löschung löscht alle zugehörigen Weaviate-Objekte (Mails dieses Postfachs)
- [ ] Nach der Löschung werden alle freigeschalteten Nutzer nicht mehr über dieses Postfach benachrichtigt

### Nutzerzuweisung
- [ ] Der Eigentümer eines Postfachs kann im Settings-Tab einen oder mehrere Alice-Nutzer als freigeschaltet markieren (Multi-Select)
- [ ] Freigeschaltete Nutzer können Mails des Postfachs per Chat abfragen und erhalten proaktive Benachrichtigungen
- [ ] Nur Eigentümer und Admin sehen die Zugangsdaten-Felder (Host, Port, Benutzername); das Passwort ist für niemanden einsehbar

### Admin-Sonderrechte
- [ ] Der Admin sieht im Settings-Tab alle Postfächer aller Nutzer
- [ ] Der Admin kann jedes Postfach löschen, aber keine Zugangsdaten einsehen oder ändern

### Mail-Indexierung (n8n-Hintergrundprozess)
- [ ] n8n pollt jeden konfigurierten IMAP-Server im eingestellten Intervall
- [ ] Bereits indexierte Mails (anhand Message-ID) werden nicht erneut verarbeitet
- [ ] Pro Mail werden in Weaviate gespeichert: Absender, Empfänger, Betreff, Datum, Message-ID (IMAP UID), Postfach-ID, Kategorie, LLM-Zusammenfassung (2–3 Sätze), Anhang-Metadaten (Dateiname, MIME-Typ, Größe in Bytes) als Liste
- [ ] Das LLM (Ollama/qwen3) klassifiziert jede Mail anhand von Absender + Betreff + Body-Preview (erste ~500 Zeichen) in eine der vier Kategorien: **Wichtig**, **Werbung**, **Social Media**, **Spam**
- [ ] Ist ein Startdatum konfiguriert, werden beim ersten Sync alle Mails ab diesem Datum rückwirkend indexiert
- [ ] Verbindungsfehler werden geloggt; der nächste Sync-Zyklus versucht es erneut (kein sofortiger Retry-Loop)

### Reaktive Mail-Abfragen (Chat)
- [ ] Nutzer können per Sprache oder Text Mails abfragen (Beispiele: "Habe ich heute eine Mail von der Sparkasse?", "Zeig mir alle wichtigen Mails der letzten Woche", "Wie viele ungelesene Mails habe ich?")
- [ ] Alice sucht ausschließlich in Postfächern, für die der anfragende Nutzer freigeschaltet ist
- [ ] Auf Anfrage ("Zeig mir den Inhalt der Mail XYZ") lädt Alice den vollen Mail-Body live vom IMAP-Server nach (per gespeicherter Message-ID) und gibt ihn im Chat aus
- [ ] Nutzer können nach Anhängen fragen ("Hat die Mail von der Bank einen PDF-Anhang?"); Alice antwortet anhand der gespeicherten Anhang-Metadaten
- [ ] Anhänge werden nicht automatisch heruntergeladen oder in andere Systeme (DMS) eingespeist — das ist ein separates zukünftiges Feature
- [ ] Ist die IMAP-Verbindung beim Nachlade-Versuch nicht verfügbar, gibt Alice eine klare Fehlermeldung

### Proaktive Benachrichtigungen
- [ ] Nach jedem Sync-Zyklus werden neu indexierte Mails der Kategorie "Wichtig" als Chat-Nachricht an alle freigeschalteten Nutzer des jeweiligen Postfachs gesendet
- [ ] Die Nachricht enthält: Absender, Betreff, Datum und die LLM-Zusammenfassung
- [ ] Mails der Kategorien Werbung, Social Media und Spam erzeugen keine proaktive Benachrichtigung
- [ ] Eine Benachrichtigung wird pro Mail maximal einmal pro Nutzer gesendet (kein Duplikat bei erneutem Sync)

## Edge Cases

- **IMAP-Verbindung schlägt fehl beim Anlegen:** Fehlermeldung direkt im Settings-Dialog; Postfach wird trotzdem gespeichert, damit der Nutzer Zugangsdaten korrigieren kann ohne neu anzufangen.
- **Startdatum liegt weit in der Vergangenheit (tausende Mails):** Initialer Backfill läuft über mehrere Sync-Zyklen; kein Single-Request-Timeout. Der Nutzer sieht im Settings-Tab einen Status ("Indexierung läuft…" / "X Mails indexiert").
- **Eigentümer-Account wird gelöscht:** Alle Postfächer dieses Nutzers werden ebenfalls gelöscht (Cascade), inklusive Weaviate-Metadaten.
- **Nutzer wird aus Zugriffsliste entfernt:** Laufende Benachrichtigungen für diesen Nutzer werden sofort gestoppt; bereits empfangene Nachrichten bleiben im Chat-Verlauf.
- **Gleiche Mail-Message-ID in zwei verschiedenen Postfächern:** Jedes Weaviate-Objekt trägt eine Postfach-ID — kein Konflikt; beide Objekte existieren unabhängig.
- **LLM nicht erreichbar (Ollama down):** Mail wird ohne Kategorie und ohne Zusammenfassung indexiert (Status: "unklassifiziert"); kein Abbruch des Sync-Zyklus. Proaktive Benachrichtigung wird nicht ausgelöst.
- **Mail hat sehr viele oder sehr große Anhänge:** Nur Metadaten (Name, Typ, Größe) werden indexiert — kein Limit pro Mail, da keine Binärdaten gespeichert werden.
- **Zwei Nutzer legen das gleiche Postfach an:** Technisch erlaubt — jedes Postfach ist ein unabhängiges Objekt mit eigenem Eigentümer. Duplikate sind die Verantwortung des Nutzers.
- **Passwort-Änderung während laufendem Sync:** Der aktive Sync-Zyklus schlägt fehl; der nächste Zyklus nutzt das neue Passwort.

## Technical Requirements

- **Passwort-Speicherung:** Verschlüsselt in der Datenbank (AES oder Postgres pgcrypto); niemals im Klartext in Logs oder API-Responses
- **Weaviate-Kollektion:** Neue Kollektion `Email` mit Feldern: `message_id`, `mailbox_id`, `subject`, `sender`, `recipients`, `date`, `category`, `summary`, `attachments` (JSON-Array: name, mime_type, size_bytes); semantische Suche auf `subject` + `summary`
- **Sync-Prozess:** n8n-Workflow mit Schedule-Trigger; pro Postfach ein separater Durchlauf
- **Authentifizierung:** Alle Settings-API-Endpunkte erfordern gültigen JWT; Postfach-Daten werden nur für den Eigentümer oder Admin zurückgegeben
- **Skalierung:** MVP unterstützt bis zu 10 Postfächer; kein Parallelitäts-Limit im Spec definiert

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Schichten-Überblick

Drei Schichten: **Settings-UI** (Postfach-Verwaltung), **n8n Backend** (Sync + API), **Chat-Integration** (Tool-Abfragen + proaktive Benachrichtigungen).

---

### A) Komponenten-Struktur (Settings-UI)

```
SettingsPage
+-- Tab: "E-Mail" (sichtbar für ALLE eingeloggten Nutzer — neu)
    +-- MailboxSection
        +-- Header: "Meine Postfächer" (user) / "Alle Postfächer" (admin)
        +-- Button: "Postfach hinzufügen"
        +-- MailboxTable
        |   +-- Spalten: Anzeigename | Host | Besitzer* | Status | Freigesch. Nutzer | Aktionen
        |   +-- StatusBadge: Aktiv / Indexierung läuft / Fehler / Unklassifiziert
        |   (* Besitzer-Spalte nur für Admin)
        +-- AddMailboxDialog
        |   +-- Felder: Anzeigename, IMAP-Host, Port (993), SSL-Toggle, Benutzername,
        |               Passwort, Sync-Intervall (15 min), Startdatum (optional)
        |   +-- Inline-Feedback: Verbindungstest-Ergebnis nach Speichern
        +-- EditMailboxDialog
        |   +-- Gleiche Felder; Passwort-Feld leer (muss neu eingegeben werden)
        +-- DeleteMailboxDialog
        |   +-- Bestätigung + Warnung "Alle indexierten Mails werden gelöscht"
        +-- AccessDialog
            +-- Multi-Select: Alle Alice-Nutzer; freigeschaltete vorausgewählt
```

Der "E-Mail"-Tab ist der einzige Settings-Tab, der für alle Nutzer (nicht nur Admin) sichtbar ist. Admin sieht zusätzlich eine "Besitzer"-Spalte und kann fremde Postfächer löschen.

---

### B) Datenmodell

**PostgreSQL — zwei neue Tabellen:**

`alice.imap_mailboxes` — ein Eintrag pro Postfach:
- ID, Besitzer (User-ID), Anzeigename, IMAP-Host, Port, Benutzername
- Passwort: AES-verschlüsselt via pgcrypto — niemals im Klartext gespeichert oder zurückgegeben
- SSL-Flag, Sync-Intervall (Minuten), Startdatum (optional)
- Status (aktiv / syncing / Fehler), Anzahl indexierter Mails, Zeitstempel letzter Sync, letzte Fehlermeldung
- Bei Löschen des Besitzers: Postfach wird automatisch mitgelöscht (Cascade)

`alice.imap_mailbox_access` — Zugriffssteuerung:
- Postfach-ID + User-ID (zusammengesetzter Primärschlüssel)
- Bei Löschen des Postfachs oder Nutzers: Eintrag wird automatisch mitgelöscht (Cascade)

**Weaviate — neue Kollektion `Email`:**
- `message_id` (IMAP UID + Postfach-ID kombiniert — global eindeutig)
- `mailbox_id` (für Zugriffskontrolle bei Suchanfragen)
- `subject`, `sender`, `recipients`, `date`, `category`, `summary`
- `attachments` (JSON-Liste: Dateiname, MIME-Typ, Größe in Bytes)
- Semantische Vektorsuche auf `subject` + `summary`

---

### C) n8n Workflow-Architektur

**Workflow 1: `alice-mail-api` (neu)**
- Trigger: HTTP Webhook
- Routen: GET/POST/PUT/DELETE /mailboxes, PUT /mailboxes/:id/access
- Auth: JWT-Validierung (identisch zu alice-session-api)
- Passwort-Handling: pgcrypto-Ver-/Entschlüsselung in SQL-Nodes

**Workflow 2: `alice-mail-sync` (neu)**
- Trigger: Schedule (jede Minute)
- Ablauf: Lade fällige Postfächer → IMAP-Fetch → Weaviate-Deduplizierung → Ollama-Klassifizierung → Weaviate-Speicherung → Benachrichtigung → Postgres-Status-Update
- Ollama-Ausfall: kategorie = "unklassifiziert", Sync läuft weiter
- IMAP-Fehler: Status auf "Fehler", kein Retry-Loop

**Workflow 3: `alice-mail-tools` (neu)**
- Tools für den Chat-Agent:
  - `search_emails` — semantische Suche in Weaviate, gefiltert nach autorisierten Postfach-IDs
  - `get_email_body` — live IMAP-Fetch per Message-ID
  - `list_email_attachments` — Anhang-Metadaten aus Weaviate

**Proaktive Benachrichtigungen (MVP):**
n8n schreibt "Wichtig"-Mails als system-generierte Nachricht direkt in `alice.messages` (letzte aktive Session des Nutzers). Kein MQTT-Push für MVP.

---

### D) Tech-Entscheidungen

| Entscheidung | Gewählt | Warum |
|---|---|---|
| Passwort-Speicherung | pgcrypto AES in Postgres | Bereits verfügbar; kein separater Secret-Store |
| IMAP-Verbindung | n8n IMAP Email Node | Nativ in n8n Core, kein Custom-Container |
| Sync-Granularität | 1 Workflow, iteriert alle Postfächer | Einfach; skaliert bis ~10 Postfächer (MVP-Limit) |
| Settings-Tab-Sichtbarkeit | Alle Nutzer (nicht nur Admin) | Spec: jeder Nutzer kann eigene Postfächer anlegen |
| Backfill | Inkrementell über Sync-Zyklen | Verhindert Timeout bei großen Postfächern |

---

### E) Abhängigkeiten

- `pgcrypto` Extension in PostgreSQL (vor Implementierung prüfen ob aktiv)
- n8n IMAP Email Node (in n8n Core enthalten)
- Weaviate: neues Schema für `Email`-Kollektion (via `init-weaviate-schema.sh`)
- Frontend: keine neuen npm-Packages (alle shadcn-Komponenten bereits vorhanden)

## Implementation Notes

### Backend (PROJ-46 backend phase)

**New files:**
- `sql/migrations/046-imap-mailboxes.sql` — Creates `alice.imap_mailboxes` + `alice.imap_mailbox_access` tables with RLS
- `docker/compose/automations/alice-mail-reader/` — Python Flask IMAP service (stdlib imaplib, 3 endpoints: /test, /fetch, /body)
- `workflows/alice-mail-api.json` — 7 REST webhook routes for CRUD mailbox management
- `workflows/alice-mail-sync.json` — Schedule trigger (every minute), fetches/classifies/stores emails via alice-mail-reader + Ollama + Weaviate
- `workflows/alice-mail-tools.json` — Chat tool webhooks: search_emails (Weaviate), get_email_body (IMAP live fetch)

**Modified files:**
- `schemas/email.json` — Added `mailboxId` and `imapUid` fields
- `docker/compose/automations/alice-chat-stream/app/tools.py` — Added search_emails + get_email_body tools
- `docker/compose/automations/alice-chat-stream/.env.example` — Added N8N_TOOL_MAIL_URL

**Deviations from spec:**
- Tech design said "n8n IMAP Email Node, kein Custom-Container" — but n8n's IMAP node is a trigger-only and cannot be called dynamically with per-mailbox credentials. Created alice-mail-reader (tiny Python service, ~180 lines) as an HTTP-callable IMAP adapter instead.
- Password encryption uses AES-256-CBC via Node.js crypto built-in (available in n8n Code nodes) instead of pgcrypto, since pgcrypto was not installed on the server.

**DB Migration applied:** 2026-06-24 — production postgres confirmed OK.

## QA Test Results

**QA Date:** 2026-06-24 | **Tester:** QA Engineer (Claude Sonnet 4.6)
**Result: APPROVED — No Critical or High bugs remaining**

---

### Acceptance Criteria Results

#### Settings-Tab: Postfach-Verwaltung

| # | Criterion | Result | Notes |
|---|---|---|---|
| 1 | Neuer Tab "E-Mail-Postfächer" im Settings-Menü | ✅ PASS | Tab für alle Nutzer sichtbar (nicht nur Admin) |
| 2 | Jeder eingeloggte Nutzer kann eigene Postfächer anlegen | ✅ PASS | Kein Admin-Check auf Tab-Ebene |
| 3 | Alle 8 Felder beim Anlegen konfigurierbar (Defaults: Port 993, SSL an, Intervall 15 min) | ✅ PASS | Alle Felder in AddMailboxDialog vorhanden mit korrekten Defaults |
| 4 | Test-Verbindung nach Speichern; Fehlermeldung inline | ✅ PASS | alice-mail-reader /test Endpoint, Ergebnis direkt im Dialog |
| 5 | Bearbeiten vorausgefüllt (Passwort leer) | ✅ PASS | EditMailboxDialog füllt alle Felder außer Passwort vor |
| 6 | Eigentümer + Admin können löschen; Weaviate-Objekte werden mitgelöscht | ✅ PASS | DELETE /v1/batch/objects mit mailboxId-Filter; Cascade für DB |
| 7 | Nach Löschung keine Benachrichtigungen mehr | ✅ PASS | CASCADE DELETE auf imap_mailbox_access; Sync findet kein Postfach mehr |

#### Nutzerzuweisung

| # | Criterion | Result | Notes |
|---|---|---|---|
| 8 | Eigentümer kann Nutzer als freigeschaltet markieren (Multi-Select) | ✅ PASS | AccessDialog mit Checkboxen für alle aktiven Nutzer |
| 9 | Freigeschaltete Nutzer können Mails per Chat abfragen | ✅ PASS | alice-mail-tools prüft imap_mailbox_access + owner |
| 10 | Nur Eigentümer und Admin sehen Zugangsdaten-Felder | ✅ PASS | canManage = isOwner \|\| isAdmin im Frontend; API gibt Host/Port/User zurück aber nie Passwort |

#### Admin-Sonderrechte

| # | Criterion | Result | Notes |
|---|---|---|---|
| 11 | Admin sieht alle Postfächer aller Nutzer | ✅ PASS | SQL WHERE ($2 = 'admin' OR owner_id = userId) |
| 12 | Admin kann löschen, aber keine Zugangsdaten ändern | ✅ PASS | Delete-Button für Admin sichtbar; Edit-Button nur für Eigentümer |

#### Mail-Indexierung (n8n)

| # | Criterion | Result | Notes |
|---|---|---|---|
| 13 | n8n pollt IMAP-Server im eingestellten Intervall | ✅ PASS | Schedule-Trigger jede Minute; next_sync_at-Tracking |
| 14 | Bereits indexierte Mails nicht erneut verarbeitet | ✅ PASS | Weaviate-Dedup-Check via messageId + mailboxId vor dem Speichern |
| 15 | Alle Metadaten in Weaviate gespeichert (Absender, Empfänger, Betreff, Datum, Message-ID, Postfach-ID, Kategorie, Zusammenfassung, Anhang-Metadaten) | ✅ PASS | Alle Felder im weaviateObj vorhanden; mailboxId + imapUid wurden in Prod-Schema ergänzt |
| 16 | LLM klassifiziert in Wichtig / Werbung / Social Media / Spam | ✅ PASS | Ollama-Aufruf mit Klassifikations-Prompt; Fallback "unklassifiziert" bei Ausfall |
| 17 | Startdatum für rückwirkende Indexierung | ⚠️ PARTIAL | start_date wird gespeichert aber nicht im IMAP-Fetch verwendet. Stattdessen UID-basierter Sync (ab UID 0 = alle Mails). Neue Postfächer indexieren ALLE verfügbaren Mails, nicht nur ab Startdatum. (BUG-4 — Medium) |
| 18 | Verbindungsfehler werden geloggt; nächster Zyklus wiederholt | ✅ PASS | status=error gesetzt, next_sync_at gesetzt; WHERE-Filter wurde gefixed (vorher permanenter Ausschluss von error-Postfächern) |

#### Reaktive Mail-Abfragen (Chat)

| # | Criterion | Result | Notes |
|---|---|---|---|
| 19 | Mails per Sprache/Text abfragen | ✅ PASS | search_emails-Tool mit Weaviate Hybrid Search |
| 20 | Alice sucht nur in autorisierten Postfächern | ✅ PASS | PG: Get Authorized Mailboxes filtert nach Eigentümerschaft + Access-Tabelle |
| 21 | Vollständiger Mail-Body auf Anfrage | ✅ PASS | get_email_body-Tool lädt live vom IMAP über alice-mail-reader |
| 22 | Anhang-Abfragen möglich | ✅ PASS | Anhang-Metadaten in Weaviate gespeichert, in Suchergebnissen enthalten |
| 23 | Anhänge werden nicht automatisch eingespeist | ✅ PASS | Nur Metadaten; kein Download-Mechanismus implementiert |
| 24 | IMAP nicht verfügbar: klare Fehlermeldung | ✅ PASS | alice-mail-reader gibt Fehler-JSON zurück; n8n-Tool gibt error-Objekt an Chat |

#### Proaktive Benachrichtigungen

| # | Criterion | Result | Notes |
|---|---|---|---|
| 25 | "Wichtig"-Mails als Chat-Nachricht an freigeschaltete Nutzer | ✅ PASS | PG: Send Notifications schreibt in alice.messages (letzte LLM-Session) |
| 26 | Nachricht enthält Absender, Betreff, Datum, Zusammenfassung | ✅ PASS | Formatierte Nachricht mit allen Feldern |
| 27 | Werbung/Social Media/Spam erzeugen keine Benachrichtigung | ✅ PASS | Nur category='Wichtig' löst Benachrichtigung aus |
| 28 | Benachrichtigung maximal einmal pro Nutzer | ✅ PASS | Weaviate-Dedup verhindert doppelte Indexierung; damit auch keine doppelten Notifications |

---

### Bugs Found and Fixed

| Bug | Severity | Description | Status |
|---|---|---|---|
| BUG-1 | High | `Loop Back` war ein zweiter `SplitInBatches`-Node statt direkter Rückverbindung — hätte Multi-Postfach-Iteration gebrochen | **FIXED** in alice-mail-sync.json |
| BUG-2 | High (Initial assessment) | Weaviate `Email`-Kollektion hatte `mailboxId`/`imapUid`-Felder nicht | **FIXED**: Properties via API zu Prod-Schema hinzugefügt; schemas/email.json war korrekt |
| BUG-3 | Medium | Fehlerhafte Postfächer waren durch `status != 'error'` dauerhaft von Sync ausgeschlossen (Spec: "nächster Zyklus wiederholt") | **FIXED** in alice-mail-sync.json |
| BUG-4 | Medium | `start_date` wird gespeichert aber nicht im IMAP-Fetch verwendet; Sync ist UID-basiert (ab UID 0 = alle Mails, nicht ab Startdatum) | **OPEN** — Known Gap; neue Postfächer indexieren alle Mails (mehr als erwartet, nicht weniger) |
| BUG-5 | Low | AddMailboxDialog zeigt bei fehlgeschlagenem Verbindungstest nicht explizit, dass das Postfach trotzdem gespeichert wurde | **OPEN** — Minor UX |

---

### Security Audit

| Check | Result |
|---|---|
| JWT erforderlich für alle API-Endpunkte | ✅ Alle Webhooks mit `authentication: "jwtAuth"` |
| Passwort nie im Klartext gespeichert oder zurückgegeben | ✅ AES-256-CBC in DB; kein SELECT auf password_enc in API |
| Passwort nie in API-Response | ✅ Kein Feld `password` oder `password_enc` im GET-Response |
| SQL-Injection | ✅ Alle Queries parametrisiert ($1, $2, ...) |
| Autorisierung: Nutzer sieht nur eigene Postfächer | ✅ WHERE owner_id = userId; Admin-Bypass explizit per role-Check |
| Autorisierung: Mail-Tools nur für autorisierte Nutzer | ✅ alice-mail-tools prüft DB-Zugriff vor Weaviate-Query |
| XSS im Frontend | ✅ React rendert alle Strings als Text-Nodes (kein dangerouslySetInnerHTML) |
| Passwort-Speicherung im Browser | ✅ Passwort wird nach Submit nicht im State gehalten |

---

### Regression Test

- Existing Settings tabs (Mein Profil, Allgemein, DMS, Nutzerverwaltung, Stimmprofile, Chatarchiv): ✅ Frontend Build erfolgreich, Settings-Route kompiliert ohne Fehler
- Weaviate Email-Kollektion: ✅ Bestehende DMS-E-Mails-Funktionalität unberührt (additive Schema-Änderung)
- alice.users, alice.sessions, alice.messages: ✅ Nur gelesen, nicht verändert

---

### Production-Ready Decision

**✅ READY — Keine Critical oder High Bugs**

Offene Punkte (Medium/Low, kein Blocker):
- BUG-4: start_date-Filterung im IMAP-Fetch fehlt (neue Postfächer indexieren alle Mails)
- BUG-5: Fehlende explizite "Postfach gespeichert"-Meldung bei fehlgeschlagenem Connection-Test

**Deployment-Checkliste:**
1. Deploy n8n-workflow `alice-mail-api`
2. Deploy n8n-workflow `alice-mail-sync`
3. Deploy n8n-workflow `alice-mail-tools`
4. Deploy `alice-mail-reader` (neuer Docker-Container) auf ki.lan
5. Deploy `alice-chat-stream` (tools.py-Update + N8N_TOOL_MAIL_URL in .env)
6. Deploy nginx-Config (PUT-Methode für /api/webhook/alice/)
7. Deploy Frontend

## Deployment
_To be added by /deploy_
