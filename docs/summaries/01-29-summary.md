# Alice — Entwicklungsstand PROJ-1 bis PROJ-29

> **Stand:** 7. Mai 2026 · Alle 29 Features im Status **Deployed**
>
> Dieses Dokument richtet sich an externe Stakeholder mit technischem Hintergrund, die sich einen vollständigen Überblick über den aktuellen Entwicklungsstand verschaffen möchten.

---

## 1. Systemarchitektur (Überblick)

Alice ist ein **local-first, AI-first Personal Assistant** mit Smart-Home-Integration. Der gesamte Stack läuft on-premise auf einem Heimserver und ist ausschließlich per VPN erreichbar.

```
CLIENT (React PWA · Home Assistant Voice Devices)
        ↓
nginx (Reverse Proxy · JWT-Auth · Rate-Limiting)
        ↓
n8n (AI-Orchestrator)  +  alice-auth (FastAPI)
        ↓
Ollama qwen3:14b  ←→  Weaviate (Vektor-DB)  ←→  PostgreSQL (alice-Schema)
        ↓
Home Assistant (Smart Home)  +  NAS (Dokumente)  +  MQTT  +  Redis
```

**Kernprinzip:** Ein einziger LLM-Aufruf mit native Tool-Use — kein zweistufiger Router. Der Sprachmodell entscheidet selbst, welches Tool es aufruft (`home_assistant`, `search_documents`, `get_document_details`, `remember`, `recall`).

---

## 2. Entwicklungsphasen

| Phase     | Inhalt                                                | Status          |
| --------- | ----------------------------------------------------- | --------------- |
| Phase 0   | Hardware-Setup                                        | ✅ Abgeschlossen |
| Phase 1   | Chat MVP (n8n + React + Home Assistant + DMS)         | ✅ Abgeschlossen |
| Phase 1.5 | JWT-Authentifizierung + Login-Screen                  | ✅ Abgeschlossen |
| Phase 2   | Speech Gateway (Whisper STT + Piper TTS + Speaker-ID) | Geplant         |
| Phase 3   | Multi-User, Display-Routing, Security Hardening       | Geplant         |

---

## 3. Feature-Cluster

### 3.1 Home Assistant Intent Infrastructure (PROJ-1 bis PROJ-6, PROJ-11)

Dies ist die Grundlage der Smart-Home-Steuerung. Die Features bauen streng aufeinander auf.

#### PROJ-1 — HA Intent Infrastructure (Datenmodell)
Die **Datengrundlage** für alles, was mit Sprachbefehlen und Smart-Home zusammenhängt.

Neu erstellt:
- PostgreSQL-Tabellen `alice.ha_intent_templates` (Sprachbefehls-Vorlagen), `alice.ha_entities` (HA-Geräteregister), `alice.ha_sync_log` (Audit-Trail)
- Weaviate-Collection `HAIntent` — vektorisiert nur das `utterance`-Feld (z. B. „Küche hell machen"), alle anderen Felder als Filter-Metadaten

Designentscheidung: Nur der natürlichsprachliche Satz wird eingebettet. Das hält die Vektoren sauber und ermöglicht Schwellenwert-Filterung (Cosine-Similarität ≥ 0,82).

#### PROJ-2 — hassil-parser FastAPI Container
Ein dedizierter Python-Container, der die offiziellen Home Assistant Intent-Sätze von GitHub herunterlädt, die Hassil-Template-Syntax (z. B. `[bitte] {name} einschalten`) zu konkreten deutschen Äußerungen expandiert und sie in `alice.ha_intent_templates` schreibt.

- Endpoint `POST /intents/sync` → 55 Templates aus den offiziellen HA-Intent-Dateien importiert
- Max. 50 Muster pro Intent (konfigurierbar), um kombinatorische Explosion zu vermeiden
- Publiziert nach erfolgreichem Sync ein MQTT-Event `alice/ha/sync`, das den Entity-Sync auslöst

#### PROJ-3 — HA-First Chat Handler
Der n8n-Hauptworkflow `alice-chat-handler`. Er entscheidet pro Nutzeranfrage, welchen Pfad er einschlägt:

1. **HA_FAST**: Weaviate-nearText-Suche findet einen Intent mit Certainty ≥ 0,82 → direkt zur HA REST API, ohne LLM
2. **HYBRID**: Weaviate findet Kandidaten, LLM wählt den besten aus
3. **LLM_ONLY**: Kein HA-Intent erkannt → LLM mit Tool-Use (später ausgebaut zu DMS-Suche etc.)

Abhängigkeit: benötigt PROJ-1 (Weaviate HAIntent) und PROJ-2 (Templates).

#### PROJ-4 — HA Auto-Sync (MQTT → n8n → Weaviate)
Sobald ein neues HA-Gerät hinzukommt, sendet Home Assistant ein `ha_start`- oder `entity_created`-Event auf `alice/ha/sync`. Der Sync-Workflow verknüpft jede Entität mit den passenden Intent-Templates und schreibt die expandierten Äußerungen in die `HAIntent`-Weaviate-Collection.

Beispiel: Gerät `light.wohnzimmer_decke` + Template `{name} einschalten` → Weaviate-Eintrag „Wohnzimmerlicht einschalten".

#### PROJ-5 + PROJ-6 — Hassil Library & Kompatibilitätsfix
PROJ-5 ersetzt den eigenen Regex-Parser durch die offizielle `hassil`-Bibliothek (v3.5+). PROJ-6 behebt eine Inkompatibilität zwischen HA-YAML-Expansion-Rules und der Library-API, die im Produktionseinsatz aufgedeckt wurde.

#### PROJ-11 — HA Sync Python Worker (Ablösung des n8n-Workflows)
Das zentrale Problem von PROJ-4: n8n-Code-Nodes können in der Community-Version keine Umgebungsvariablen lesen — Credentials mussten im Workflow-Code hardcodiert werden.

Lösung: Der Sync-Workflow wurde als eigenständigen **Python-Docker-Container** (`alice-ha-sync`) reimplementiert. Der Container:
- abonniert `alice/ha/sync` dauerhaft (persistente MQTT-Verbindung, exponential backoff)
- führt Full-Sync und inkrementellen Sync durch
- publiziert strukturiertes JSON auf `alice/system/ha-sync/info|warning|error`
- schreibt weiterhin in `alice.ha_sync_log` (PostgreSQL)

Der n8n-Workflow `alice-ha-intent-sync` wurde nach Deployment deaktiviert (nicht gelöscht).

---

### 3.2 Authentication & Security (PROJ-7, PROJ-9, PROJ-12, PROJ-13)

#### PROJ-7 — JWT Auth / Login Screen
Ersetzt den Auto-Login-Modus (Phase 1: fester Nutzer `andreas`) durch echte Authentifizierung:

- Login-Screen mit Passwort-Formular (React)
- `alice-auth` FastAPI-Container (separat von n8n) für alle Auth-Operationen
- JWT-Token (RS256), gespeichert in `localStorage`
- PostgreSQL-Tabellen: `alice.auth_sessions`, `alice.webauthn_challenges` (für Phase 2 vorbereitet)
- nginx leitet `/api/auth/*` an `alice-auth:8002`

#### PROJ-9 — Chat-Handler JWT-Schutz
Absicherung des Webhook-Endpunkts `/api/webhook/alice`. n8n validiert das JWT-Token im Authorization-Header bevor der Chat-Handler-Workflow ausgeführt wird.

#### PROJ-12 — Phase 2 Security & UX Hardening
Drei unabhängige Verbesserungen in einem Sprint:

1. **nginx Security Headers** — `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: origin-when-cross-origin` als wiederverwendbares nginx-Snippet in allen 7 CORS-Location-Blocks
2. **Rate-Limiting Chat** — `limit_req_zone` 20 Requests/Minute auf `/api/webhook/`; HTTP 429 mit nutzerfreundlicher Meldung im Chat
3. **Chat umbenennen** — Inline-Edit im Sidebar (Enter zum Speichern, Escape zum Abbrechen, Persistenz via `localStorage`)

#### PROJ-13 — Auth-Endpoint Rate-Limiting
Brute-Force-Schutz für den Login: 5 Requests/Minute via `map`-Direktive (nur POST-Requests werden gezählt, `GET /api/auth/validate` bleibt ungedrosselt). Frontend zeigt bei HTTP 429 „Zu viele Anmeldeversuche — bitte eine Minute warten".

---

### 3.3 Chat UI & Session Management (PROJ-8, PROJ-14)

#### PROJ-8 — Services Sidebar & Landing Page Migration
- Die alte statische `index.html`-Landingpage (7 Service-Links) wurde durch die React-App ersetzt
- Service-Links (n8n, Open WebUI, Home Assistant, HA Dev, Kanboard, Jupyter, Finance Upload) wanderten in eine neue `ServiceLinks`-Komponente in der Sidebar
- `finance_upload/` bleibt erhalten und ist per `/finance_upload/index.html` erreichbar

#### PROJ-14 — Sidebar Context-Menu & Session-Persistenz
- Rechtsklick / Drei-Punkte-Menü in der Sidebar: Session umbenennen, löschen
- Sessions überleben Browser-Neustarts (Persistenz in `localStorage`)
- Neue Sessions bekommen automatisch einen Titel aus dem ersten Satz der Anfrage

---

### 3.4 Document Management System (DMS) — PROJ-15 bis PROJ-25

Das DMS ist die umfangreichste Komponente und besteht aus einer vollständigen Datenpipeline: NAS-Scan → Textextraktion → LLM-Klassifikation → Weaviate-Indizierung → semantische Suche im Chat.

#### Überblick DMS-Pipeline

```
NAS (Inbox-Ordner)
    ↓  [alice-dms-scanner, stündlich 07-22 Uhr]
    ↓  SHA-256-Dedup via Redis
    ↓  Stabilitätsprüfung (5s Größenvergleich)
MQTT alice/dms/[pdf|ocr|txt|office]
    ↓  [4 Extractor-Container, dauerhaft]
    ├── dms-extractor-pdf   → pdf-parse (Node.js)
    ├── dms-extractor-ocr   → Tesseract (Python, deu+eng)
    ├── dms-extractor-txt   → direktes Lesen
    └── dms-extractor-office → LibreOffice headless
Redis List alice:dms:plaintext
    ↓  [alice-dms-processor, nächtlicher Batch]
    ↓  Ollama qwen3:14b: Klassifikation + Feldextraktion
Weaviate Collections (Invoice, BankStatement, Document,
                      Email, SecuritySettlement, Contract)
    ↓  [alice-tool-search, im Chat-Handler als Tool]
Nutzer-Antwort im Chat
```

#### PROJ-15 — DMS NAS-Ordner-Verwaltung (CRUD)
Admin-Interface zur Konfiguration, welche NAS-Ordner gescannt werden sollen.

- REST-API (`alice-dms-folder-api` n8n-Workflow): `GET/POST/PUT/DELETE /api/webhook/v1/dms/folders`
- Frontend: Settings-Tab „DMS" mit Tabelle + Formular (shadcn/ui)
- PostgreSQL: `alice.dms_watched_folders` mit Feldern `path`, `suggested_type`, `description`, `enabled`
- JWT-Authentifizierung: nur Admins können Ordner anlegen/löschen

#### PROJ-16 — DMS Scanner & NAS Multi-Format-Scan
n8n-Workflow `alice-dms-scanner` (Schedule: `0 7-22 * * *`):

- Liest aktive Ordner aus PostgreSQL
- Rekursiver Scan (max. Tiefe 10), Dateitypen: PDF, TXT, MD, DOCX, DOC, XLSX, XLS, ODT, ODS
- SHA-256-Dedup gegen Redis-Sets `alice:dms:processed` und `alice:dms:queued_files`
- Größenstabilitätsprüfung (5s Wartezeit → kein halbfertiger Upload)
- OCR-Detection für PDFs (BT-Marker-Suche in raw bytes)

#### PROJ-17 — DMS Scanner Multi-Queue-Routing
Erweiterung von PROJ-16: statt einer einzigen Queue `alice/dms/new` werden Dateien typenspezifisch geroutet:

| Datei                          | Queue              |
| ------------------------------ | ------------------ |
| PDF mit Textebene              | `alice/dms/pdf`    |
| PDF ohne Textebene             | `alice/dms/ocr`    |
| TXT, MD                        | `alice/dms/txt`    |
| DOCX, DOC, ODT, XLSX, XLS, ODS | `alice/dms/office` |

Zusätzlich: Redis-basierte Stats-Counter (scanned_files, new_files, skipped_files), publiziert als JSON auf `alice/dms/scanner/stats` nach jedem Scan-Lauf. Bugfix für ELOOP-Fehler bei CIFS-Symlinks (NAS-seitige zirkuläre Links) durch direkte Mount-Point-Bindung statt Parent-Verzeichnis.

#### PROJ-18 — DMS Text-Extractor-Container (4 Container)
Vier spezialisierte Docker-Container abonnieren je ihre MQTT-Queue und schreiben extrahierten Plaintext in die Redis List `alice:dms:plaintext`:

- **dms-extractor-pdf** (Node.js/Alpine): `pdf-parse`, leichtgewichtig
- **dms-extractor-ocr** (Python/Debian): `pytesseract`, `pdf2image`, Tesseract-Sprachdaten Deutsch + Englisch (~200 MB)
- **dms-extractor-txt** (Node.js/Alpine): `fs`-Modul + `chardet` für Encoding-Erkennung (UTF-8 / ISO-8859-1)
- **dms-extractor-office** (Python/Debian): LibreOffice headless (~500 MB), konvertiert zu TXT/CSV

Warum Redis statt MQTT für den Output? MQTT persistent sessions erfordern einen dauerhaft verbundenen Subscriber. Redis Lists sind AOF-persistent und überleben Container-Neustarts — ideal für den nächtlichen Batch-Processor.

NAS-Mounts werden zentral in `nas-volumes.yml` definiert und per Docker Compose `extends` in alle 5 Container eingebunden (Einzel-Source-of-Truth).

#### PROJ-19 — DMS Processor Workflow (LLM-Klassifikation + Weaviate)
Nächtlicher n8n-Batch-Workflow:

1. Liest Einträge aus Redis List `alice:dms:plaintext` (LRANGE + DEL)
2. Deduplizierung via `file_hash` (idempotent bei Mehrfachzustellung)
3. **Klassifikation**: Ollama qwen3:14b klassifiziert den Dokumenttyp (Invoice, BankStatement, etc.)
4. **Feldextraktion**: zweiter LLM-Aufruf extrahiert strukturierte Felder je nach Dokumenttyp (z. B. `absender`, `gesamtbetrag`, `rechnungsdatum` für Rechnungen)
5. Weaviate-Insert in die passende Collection
6. Redis-Mappings aktualisieren: `alice:dms:path_to_hash` und `alice:dms:hash_to_paths:<hash>` (Grundlage für PROJ-21)

Ab PROJ-24: 1× LLM-Retry bei ungültigem JSON-Response, bevor auf Fallback-Dokumenttyp „Document" zurückgefallen wird.

#### PROJ-20 — DMS Document Search Tool (alice-tool-search)
Integration des DMS in den Chat als LLM-Tool. Zwei Tools stehen dem Sprachmodell zur Verfügung:

- **`search_documents`**: nearText-Suche über alle 6 Weaviate-Collections parallel, optionale Filter nach Dokumenttyp und Zeitraum, Score-Schwelle 0,8, max. 20 Ergebnisse
- **`get_document_details`**: Vollständige Felder eines Dokuments per Weaviate-UUID

Beide Tools sind als `toolWorkflow`-Nodes an den AI-Agent-Node im `alice-chat-handler` angebunden — native LangChain-Integration, kein manuelles Dispatch.

Sicherheit: Der Sub-Workflow prüft `alice.permissions_dms` per parameterisierter SQL-Query und filtert Weaviate-Collections entsprechend der Nutzerberechtigungen. GraphQL-Injection via Suchanfrage wird durch Control-Character-Stripping verhindert.

#### PROJ-21 + PROJ-22 — DMS Lifecycle Management
Erkennung und Behandlung von drei Datei-Lifecycle-Ereignissen ohne erneuten LLM-Aufruf:

| Fall                                                                | Erkennung                                               | Behandlung                                                              |
| ------------------------------------------------------------------- | ------------------------------------------------------- | ----------------------------------------------------------------------- |
| **Duplikat** (gleicher Inhalt, neuer Pfad, Original noch vorhanden) | Scanner: Hash bekannt, alle alten Pfade existieren noch | Weaviate: `additional_paths` erweitern                                  |
| **Verschiebung** (gleicher Inhalt, neuer Pfad, Original weg)        | Scanner: Hash bekannt, keine alten Pfade mehr vorhanden | Weaviate: `original_path` aktualisieren                                 |
| **Dateiänderung** (gleicher Pfad, anderer Hash)                     | Scanner: `path_to_hash`-Lookup zeigt anderen Hash       | Alter Eintrag löschen, neues Dokument vollständig verarbeiten (mit LLM) |

Der Scanner publiziert Lifecycle-Events auf `alice/dms/lifecycle`. Der neue MQTT-getriebene Workflow `alice-dms-lifecycle` (PROJ-22) konsumiert diese Events und führt Weaviate-PATCH-Operationen + Redis-Updates durch — komplett ohne LLM, in Echtzeit nach dem nächsten Scanner-Lauf.

#### PROJ-23 — DMS Security Hardening
Vier Security-Findings aus den QA-Runden von PROJ-15 und PROJ-19:

- **SQL-Injection DELETE**: bereits korrekt mit `$1`-Platzhalter, verifiziert und dokumentiert
- **Dynamisches SQL PUT**: ersetzt durch statische COALESCE-Query (`UPDATE ... SET path = COALESCE($1, path), ...`)
- **JWT-Rollen-Check**: klarstellender Kommentar, dass n8n die Signatur validiert und der Base64-Decode nur der Claim-Extraktion dient
- **GraphQL-Injection file_path**: `className`-Allowlist + vollständiges Escaping (`\`, `"`, Newlines, Control-Chars)

#### PROJ-24 — DMS Operational Improvements
Fünf Zuverlässigkeits-Fixes:

1. **Scanner-Stats**: Redis-Counter-Pattern akkumuliert Metriken über Loop-Iterationen hinweg → Stats-JSON auf `alice/dms/scanner/stats` nach jedem Lauf
2. **LLM-Retry**: 1× Retry bei ungültigem JSON-Response, Counter `llm_retries`/`llm_retry_failures`
3. **errorWorkflow-Konfiguration**: `alice-dms-lifecycle` zeigt auf sich selbst als Error-Workflow → Error-Trigger-Node wird aktiv
4. **MQTT Persistent Sessions**: alle 4 Extractor-Container nutzen `clean: false` + stabile `clientId` → kein Nachrichtenverlust bei Container-Restart
5. **shutil.copy statt copy2**: Office-Extractor kopiert NAS-Dateien ohne Metadaten-Übertragung → robuster bei restriktiven NAS-Berechtigungen

#### PROJ-25 — DMS Folder API Explicit Null Update (BUG-1 aus PROJ-23)
Das COALESCE-Pattern aus PROJ-23 verhindert das explizite Löschen von `suggested_type` oder `description`. Lösung: der Frontend-Request unterscheidet `undefined` (Feld nicht gesendet → COALESCE) von `null` (explizit leeren → direkter `NULL`-Write), die API verarbeitet beide Fälle korrekt.

#### PROJ-28 — DMS Verzeichnis-Reihenfolge (sort_order + Drag-and-Drop)
Konfigurierbare Verarbeitungsreihenfolge für NAS-Ordner, damit typisierte Unterordner (mit `suggested_type`) vor generischen Hauptordnern verarbeitet werden.

- **Datenbank**: neue Spalte `sort_order INTEGER NOT NULL DEFAULT 0` in `alice.dms_watched_folders` mit Index; Migration befüllt Startreihenfolge aufsteigend nach bestehender `id`
- **Backend** (`alice-dms-folder-api`): neuer Endpunkt `PATCH /webhook/dms/folders/reorder` (Admin-only); GET gibt Ordner jetzt sortiert nach `sort_order ASC, id ASC` zurück; POST setzt `sort_order = MAX(sort_order) + 1` für neue Einträge automatisch ans Ende
- **Scanner** (`alice-dms-scanner`): PostgreSQL-Query um `ORDER BY sort_order ASC, id ASC` erweitert — keine weiteren Workflow-Änderungen notwendig
- **Frontend**: Drag-and-Drop via `@dnd-kit/sortable`; GripVertical-Handle rechts neben den Aktions-Icons; Optimistic Update mit Rollback bei Netzwerkfehler; subtiler Lade-Indikator (Loader2-Spinner im Handle) während PATCH läuft; Touch- und Keyboard-DnD unterstützt

Eingabe/Ausgabe-Validierung: Array-Größe auf 100 Einträge begrenzt, negative `sort_order`-Werte werden abgelehnt.

#### PROJ-29 — BankStatement Transaction Indexing (BankTransaction Collection)
Granulare Transaktionssuche für Kontoauszüge — ermöglicht Anfragen wie „Wann gab es den letzten Zahlungsausgang an die Telekom?" oder „Wie viel habe ich im letzten Jahr an Miete gezahlt?".

**Problem**: Ein `BankStatement`-Objekt enthielt bisher 30–100 Buchungen in einem einzigen Weaviate-Objekt. Der gemeinsame Vektor ist semantisch zu generisch für Einzelbuchungssuchen. Zusätzlich: `fullText`-Truncation bei 10.000 Zeichen schneidet hintere Seiten ab, und Ollama liefert bei 20.000-Zeichen-Prompts unvollständige Transaktionsextraktion.

**Lösung**: Neue Weaviate-Collection `BankTransaction` (1 Objekt pro Buchung). Vektorisiert werden die Felder `counterparty` (Gegenpartei) und `purpose` (Verwendungszweck). Gefiltert werden kann zusätzlich nach `transactionDate`, `amount`, `direction` (credit/debit), `bankName`, `accountIban`.

Der `alice-dms-processor` wurde um eine zweiphasige BankStatement-Verarbeitung erweitert:

- **Phase A (Header-Extraktion)**: Ollama analysiert nur die ersten 3.000 Zeichen → extrahiert Bankname, IBAN, Zeitraum, Salden → schreibt `BankStatement`-Objekt → merkt `parentStatementId`
- **Phase B (Transaktions-Chunk-Extraktion)**: Gesamttext in Chunks à max. 8.000 Zeichen (Trennung an Zeilenenden) → je Chunk ein Ollama-Aufruf → Deduplizierung nach `(transactionDate, amount, counterparty)` → Weaviate Batch-Insert aller Transaktionen

`alice-tool-search` unterstützt `BankTransaction` jetzt als eigene Collection — die Erweiterung beschränkt sich auf vier Konstanten-Maps (keine Änderung der Query-Logik). DMS-Berechtigungen werden per SQL-Migration automatisch befüllt: Nutzer mit `BankStatement`-Berechtigung erhalten automatisch dieselben Flags für `BankTransaction`.

`BankStatement` bleibt als Container für Zeitraum und Salden erhalten; `parentStatementId` verknüpft Buchungen mit ihrem Auszug.

**Bekannte Einschränkungen (nach Deploy dokumentiert)**: Beim Löschen eines Kontoauszugs über den Lifecycle-Workflow bleiben `BankTransaction`-Kinder in Weaviate als verwaiste Objekte zurück (BUG-13, geplant für Follow-up).

---

### 3.5 User Management (PROJ-26, PROJ-27)

#### PROJ-26 — Admin Nutzerverwaltung
Vollständiger Nutzerverwaltungs-Flow für Admins im Settings-Bereich:

- **Nutzer anlegen**: Formular mit Username, E-Mail (Format + MX-Record-Validierung), Rolle, Profilfelder → OTP per E-Mail → First-Login-Flow (Passwort setzen)
- **Nutzer deaktivieren / löschen**: Deaktivierung (soft-delete, `is_active = false`) oder Löschung nach DSGVO-konformer Confirmation
- PostgreSQL-Tabellen: `alice.users`, `alice.user_profiles`, `alice.role_templates`, Permission-Tabellen für HA und DMS
- Backend: `alice-auth` FastAPI-Container, neue Admin-Endpoints
- Frontend: Settings-Tab „Nutzerverwaltung" mit vertikalen Tabs (Desktop) / horizontalen Tabs (Mobile)

#### PROJ-27 — Nutzerprofil selbst bearbeiten
Jeder eingeloggte Nutzer kann unter **Einstellungen → Mein Profil** seine eigenen Daten pflegen:

- **Profilformular**: Anzeigename, Interessen (Tag-Input mit Chips), Anrede (du/sie), Sprache (deutsch/englisch)
- **E-Mail ändern**: eigenes Formular mit Format- und MX-Validierung
- **Passwort freiwillig ändern**: aktuelles Passwort bestätigen + neues Passwort (2×), bcrypt timing-sicherer Vergleich
- Read-only: Systemrolle und Detailgrad (nur vom Admin verwaltbar)
- Sicherheit: User-ID kommt ausschließlich aus dem JWT-Payload, kein IDOR-Risiko

---

## 4. Abhängigkeitskette

```
PROJ-1 (DB + Weaviate Schema)
  └── PROJ-2 (hassil-parser Container)
        └── PROJ-3 (Chat Handler)
              └── PROJ-9 (JWT-Schutz Chat)
                    └── PROJ-20 (DMS Search Tool im Chat)
        └── PROJ-4 (HA Auto-Sync)
              └── PROJ-11 (Python Sync Worker, ersetzt PROJ-4)
  └── PROJ-5 (hassil Library)
        └── PROJ-6 (hassil Fix)

PROJ-7 (JWT Auth)
  └── PROJ-8 (Services Sidebar)
  └── PROJ-9 (Chat JWT-Schutz)
  └── PROJ-12 (Security Hardening)
        └── PROJ-13 (Auth Rate-Limiting)
  └── PROJ-26 (Admin User Management)
        └── PROJ-27 (Profil selbst bearbeiten)

PROJ-15 (DMS Folder Management)
  └── PROJ-16 (DMS Scanner)
        └── PROJ-17 (Multi-Queue Routing)
              └── PROJ-18 (4 Extractor Container)
                    └── PROJ-19 (DMS Processor)
                          └── PROJ-20 (DMS Search Tool)
                          └── PROJ-21 (Lifecycle Management)
                                └── PROJ-22 (Lifecycle Workflow)
                          └── PROJ-23 (Security Hardening)
                          └── PROJ-24 (Operational Improvements)
              └── PROJ-21 (Lifecycle im Scanner)
  └── PROJ-23 (Folder API Security)
  └── PROJ-25 (Explicit Null Update)
  └── PROJ-28 (Sort Order + Drag-and-Drop)
        └── PROJ-16 (Scanner-Sortierung nach sort_order)

PROJ-19 (DMS Processor)
  └── PROJ-29 (BankTransaction Indexing)
        └── PROJ-20 (BankTransaction in alice-tool-search)
```

---

## 5. Technologie-Stack (deployed)

| Kategorie            | Komponenten                                                                                     |
| -------------------- | ----------------------------------------------------------------------------------------------- |
| **AI / LLM**         | Ollama qwen3:14b (RTX 3090), text2vec-transformers (Weaviate-Embedding)                         |
| **Orchestrierung**   | n8n (9 aktive Workflows), LangChain-Tool-Use                                                    |
| **Datenbank**        | PostgreSQL 15+ (`alice`-Schema, 14+ Tabellen), Weaviate (8 Collections), Redis (AOF-Persistenz) |
| **Messaging**        | Mosquitto MQTT (QoS 1, persistente Sessions)                                                    |
| **Backend-Services** | alice-auth (FastAPI), alice-ha-sync (Python), hassil-parser (FastAPI), 4× DMS Extractor         |
| **Frontend**         | React + TypeScript + Vite + Tailwind CSS + shadcn/ui + @dnd-kit (Drag-and-Drop)                 |
| **Infrastruktur**    | nginx (Reverse Proxy, Rate-Limiting, Security Headers), Docker Compose (15+ Container)          |
| **GPU**              | NVIDIA RTX 3090 (LLM-Inferenz + Weaviate-Embedding), TITAN X (multi2vec-clip)                   |

---

## 6. n8n Workflows (Übersicht)

| Workflow                | Trigger                       | Zweck                                     |
| ----------------------- | ----------------------------- | ----------------------------------------- |
| `alice-chat-handler`    | Webhook POST `/webhook/alice` | Haupt-Chat-Logik, Memory, Tool-Use        |
| `alice-tool-search`     | Execute Workflow              | Semantische Dokumentensuche in Weaviate   |
| `alice-tool-ha`         | Execute Workflow              | Home Assistant REST API                   |
| `alice-memory-transfer` | Schedule (täglich)            | PostgreSQL → Weaviate Langzeit-Gedächtnis |
| `alice-dms-scanner`     | Schedule (stündl. 07-22)      | NAS-Scan → MQTT-Queues                    |
| `alice-dms-processor`   | Schedule (nächtlich)          | Redis → LLM → Weaviate                    |
| `alice-dms-lifecycle`   | MQTT Trigger                  | Duplikate + Verschiebungen ohne LLM       |
| `alice-dms-folder-api`  | Webhook                       | Ordner-CRUD + Reorder für Admins          |
| Auth-Workflows (4×)     | Webhook                       | Login / Validate / Refresh / Logout       |

---

## 7. Drei-Schichten-Gedächtnis

Alice pflegt ein dreistufiges Gedächtnis-Modell:

| Tier                 | Speicher                         | Inhalt                                                   | Retention     |
| -------------------- | -------------------------------- | -------------------------------------------------------- | ------------- |
| **Working Memory**   | PostgreSQL `alice.messages`      | Letzte 20 Nachrichten der aktiven Session                | Session-Dauer |
| **Long-term Memory** | Weaviate `AliceMemory`           | Semantisch durchsuchbare Gesprächshistorie               | Dauerhaft     |
| **User Profile**     | PostgreSQL `alice.user_profiles` | Fakten + Präferenzen (Name, Interessen, Anrede, Sprache) | Dauerhaft     |

---

## 8. Sicherheitsarchitektur

- **Transport**: HTTPS (nginx, Let's Encrypt), ausschließlich VPN-Zugang
- **Authentifizierung**: JWT (RS256), validiert am nginx-/n8n-Webhook-Level bevor Code ausgeführt wird
- **Rate-Limiting**: 5 Req/min Login, 20 Req/min Chat (nginx `limit_req_zone`, HTTP 429)
- **Security Headers**: X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, HSTS
- **SQL-Injection**: Durchgängig parametrisierte Queries (psycopg2 `%s`, n8n `queryReplacement`)
- **GraphQL-Injection**: Allowlists für Collection-Namen, vollständiges Escaping von Nutzereingaben
- **Secrets**: alle Credentials in `.env`-Dateien (gitignored), nie im Quellcode
- **Berechtigungen**: `alice.permissions_dms` pro Nutzer + Collection — DMS-Suche filtert Weaviate-Collections entsprechend

---

## 9. Aktueller Gesamtstand

**29 von 29 Features** im Status **Deployed**. Nächste freie Feature-ID: **PROJ-30**.

### Offene technische Schulden (niedrige Priorität)
- RLS-Policies auf HA-Infrastruktur-Tabellen sind noch permissiv (`USING TRUE`) — geplant für Phase 3
- DMS-Extractor-Container: kein DB-Connection-Pooling (akzeptabel bei niedriger Frequenz)
- Stats-Nodes in Early-Exit-Pfaden zeigen `runtime_seconds: 0` statt echter Laufzeit
- `shutil.copy` statt Streaming für sehr große NAS-Dateien im Office-Extractor
- PROJ-28: Desktop-Drag-Handle fehlt `touch-none`-CSS (BUG-FE-1, Low) und Race Condition bei schnellem Doppel-Drag (BUG-FE-2, Low)
- PROJ-29: `BankTransaction`-Kinder werden beim Löschen des Parent-`BankStatement` via Lifecycle-Workflow nicht mitgelöscht (BUG-13, Medium-High — verwaiste Objekte in Weaviate)
- PROJ-29: Phase B hat kein Retry pro Chunk bei Ollama-Fehler → stille Teilverluste möglich

### Nächste Entwicklungsschritte (Phase 2)
- Speech Gateway: Whisper STT + Piper TTS + Speaker-ID (Python-Container)
- WebAuthn-Authentifizierung (Datenstruktur bereits vorbereitet)
- DMS Lifecycle: BankTransaction-Kinder beim Löschen des Parent-Auszugs mitlöschen (Follow-up zu PROJ-29 BUG-13)
- Multi-User-Display-Routing (Gespräche an den richtigen Bildschirm leiten)
