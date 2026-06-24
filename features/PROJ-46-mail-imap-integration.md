# PROJ-46: Mail IMAP Integration

## Status: Planned
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

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
