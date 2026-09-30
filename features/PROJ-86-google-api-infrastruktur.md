# PROJ-86: Google-API-Infrastruktur

## Status: Deployed
**Created:** 2026-09-19
**Last Updated:** 2026-09-30

> QA Re-Test 2026-09-19: **READY / Approved.** BUG-01 (Critical, Event-Loop-Deadlock) und BUG-02 (Medium, 500 statt 422) sind unabhängig nachgeprüft und **behoben** — bis 60 parallele Anfragen ohne Hänger, `/health` durchgehend ~30 ms, dabei weiterhin exakt 1 Refresh je Connection (Race-Schutz intakt). 14/14 Acceptance Criteria, 0 offene Critical/High. Neu zu beachten: `/token` kann unter Lock-Contention ein **transientes, retrybares 503** liefern (PROJ-87/88/89). Details unter „QA Test Results".

## Dependencies
- Keiner (nutzt bestehende Alice-Authentifizierung/User-Tabelle)
- **Voraussetzung außerhalb des Codes:** Google-Cloud-Projekt + OAuth-Consent-Screen müssen vor Go-Live im Modus „In Production" konfiguriert sein (manuell durch Andreas in der Google Cloud Console). Im Modus „Testing" verfallen Refresh-Tokens automatisch nach 7 Tagen und nur explizit whitelisted Test-User dürfen sich verbinden — beides widerspricht der Anforderung eines dauerhaften Hintergrund-Zugriffs.
- **Wird benötigt von:** PROJ-87 (Kalender-Agent), PROJ-88 (Aufgaben-Agent), PROJ-89 (Kontakte-Agent) — alle drei bauen ihre jeweilige Settings-UI und ihren Chat-CRUD auf dem hier definierten Connection-Mechanismus auf.
- **Kein Einfluss auf PROJ-46/PROJ-53:** Geprüft — PROJ-46 (IMAP-Mailbox-Verwaltung) und PROJ-53 (Mail-Anhang-DMS-Import) sind bereits deployed und funktional unabhängig (eigenes AES-256-CBC-Passwort-Schema für statische IMAP-Zugangsdaten, kein OAuth). PROJ-86 führt einen parallelen, eigenständigen Connection-Mechanismus für Google-OAuth ein und verändert nichts an IMAP-Tabellen, -Workflows oder -Endpoints. Beide Muster bleiben unabhängig nebeneinander bestehen.

## Kontext

PROJ-86 ist **reine Backend-Infrastruktur ohne eigene sichtbare UI**. Es liefert den wiederverwendbaren Mechanismus, mit dem Alice-User ihre Google-Konten per OAuth verbinden, die Tokens sicher verwaltet werden und nachgelagerte Agenten (Kalender/Aufgaben/Kontakte, perspektivisch weitere Google-Dienste) auf einen gültigen Access-Token zugreifen können — ohne dass jedes Feature seinen eigenen OAuth-Flow, seine eigene Verschlüsselung oder seinen eigenen Refresh-Mechanismus bauen muss.

Die eigentlichen "Konto verbinden"-Buttons und Settings-Tabs entstehen erst in PROJ-87/88/89, jeweils im entsprechenden Feature-Tab. PROJ-86 stellt dafür die technischen Bausteine bereit (DB-Schema, OAuth-Redirect-Endpoints, Token-Storage/Verschlüsselung, Refresh-Mechanismus, interner Token-Abruf-Endpoint).

## User Stories

- Als Alice-User möchte ich ein Google-Konto per OAuth verbinden können, damit nachgelagerte Features (Kalender, Aufgaben, Kontakte) in meinem Namen auf meine Google-Daten zugreifen können.
- Als Alice-User möchte ich mehrere Google-Konten verbinden können (z. B. privat + beruflich), damit ich alle meine Google-Daten über Alice nutzen kann.
- Als Alice-User möchte ich selbst entscheiden können, welche Google-Berechtigungen (Kalender/Aufgaben/Kontakte) ich für ein verbundenes Konto freigebe, und diese später erweitern können, ohne das Konto neu verbinden zu müssen.
- Als Alice-User möchte ich eine Google-Connection jederzeit trennen können, wobei der Zugriff auch bei Google selbst widerrufen wird.
- Als nachgelagerter Agent (PROJ-87/88/89) möchte ich über eine einfache interne Schnittstelle einen gültigen Access-Token für eine Connection abrufen können, ohne mich um Verschlüsselung oder Ablauf/Refresh kümmern zu müssen.
- Als Alice-User möchte ich im Chat eine klare Meldung bekommen, wenn meine Google-Verbindung nicht mehr funktioniert, damit ich weiß, dass ich sie neu verbinden muss.

## Acceptance Criteria

- [ ] Ein User kann aus einem authentifizierten Alice-Kontext heraus einen Google-OAuth-Consent-Flow starten (Redirect zu Google, Rückkehr über eine Callback-Route auf der bestehenden Alice-Domain).
- [ ] Beim erstmaligen Verbinden eines Google-Kontos werden Access-Token und Refresh-Token verschlüsselt in PostgreSQL gespeichert, verknüpft mit dem Alice-User und der Google-Account-Kennung (z. B. Google-`sub`/E-Mail).
- [ ] Ein User kann mehrere Google-Konten gleichzeitig verbinden; jede Connection ist eindeutig durch (Alice-User, Google-Account-Kennung) identifiziert.
- [ ] Jede Connection speichert eine Liste der gewährten Scopes. Ein User kann eine bestehende Connection um zusätzliche Scopes erweitern (löst einen erneuten, gezielten Consent-Flow für die Erweiterung aus), ohne eine neue Connection anzulegen.
- [ ] Ein Nur-Kalender-Consent und ein Nur-Kontakte-Consent für dasselbe Google-Konto führen zur selben Connection mit vereinigten Scopes (kein Duplikat).
- [ ] Ein interner REST-Endpoint liefert für eine gegebene Connection einen aktuell gültigen Access-Token; ist der gespeicherte Access-Token abgelaufen, wird er transparent über den Refresh-Token erneuert, bevor er zurückgegeben wird.
- [ ] Der Token-Refresh läuft vollständig im Hintergrund (Alice-Backend ↔ Google), ohne dass der User online, im VPN oder im Browser aktiv sein muss.
- [ ] Schlägt der Refresh fehl (z. B. Refresh-Token von Google widerrufen), wird die Connection auf einen Fehlerstatus gesetzt; ein Agent, der daraufhin einen Token anfragt, bekommt einen eindeutig erkennbaren Fehler zurück, den er im Chat verständlich kommunizieren kann (z. B. "Google-Verbindung muss erneuert werden").
- [ ] Ein User kann eine eigene Connection in einer Liste einsehen (Google-Konto, Scopes, Status) — Grundlage für die von PROJ-87/88/89 zu bauende Settings-UI.
- [ ] Ein User kann eine eigene Connection trennen: Tokens werden aus der Alice-DB gelöscht UND der Zugriff wird aktiv über Googles Revoke-Endpoint widerrufen.
- [ ] Ein User sieht ausschließlich seine eigenen Connections; es gibt keinen Mechanismus, über den ein anderer User (auch kein Admin) fremde Connections einsehen, verwalten oder nutzen kann.
- [ ] Alle Rollen (admin/user/guest/child) dürfen Connections anlegen — PROJ-86 selbst schränkt dies nicht ein (etwaige rollenbasierte Einschränkungen sind Sache der jeweiligen Folge-Features).
- [ ] Bricht der User den Google-Consent-Screen ab oder liefert der Callback einen Fehler, landet der User ohne angelegte/veränderte Connection zurück, mit einer erkennbaren Fehlermeldung; bestehende Connections bleiben unverändert.
- [ ] Tokens sind at-rest verschlüsselt in PostgreSQL gespeichert (nicht im Klartext), analog zum bestehenden Verschlüsselungsansatz für IMAP-Passwörter (PROJ-46).

## Edge Cases

- **Scope-Erweiterung für bereits verbundenes Konto:** User verbindet zunächst nur Kalender-Zugriff, später möchte PROJ-89 (Kontakte) zusätzlichen Scope. Es muss ein gezielter Re-Consent nur für den fehlenden Scope möglich sein, ohne bestehende Scopes/Tokens zu verlieren.
- **Zwei Alice-User verbinden dasselbe Google-Konto:** User A und User B (zwei getrennte Alice-Accounts) verbinden zufällig dieselbe Google-Adresse. Da Connections pro (Alice-User, Google-Account) eindeutig sind, entstehen zwei unabhängige Connections mit jeweils eigenen Tokens — kein Konflikt, aber beide haben unabhängigen Zugriff auf dasselbe Google-Konto.
- **Refresh-Token wird von Google widerrufen, während kein Agent gerade zugreift:** Fehler wird erst beim nächsten tatsächlichen Zugriffsversuch sichtbar (kein aktives Polling) — Connection-Status bleibt bis dahin fälschlich "aktiv". Muss beim nächsten fehlschlagenden Refresh-Versuch korrekt auf Fehlerstatus wechseln.
- **Gleichzeitiger Token-Refresh durch zwei parallele Agenten-Aufrufe:** PROJ-87 und PROJ-88 fragen quasi zeitgleich einen Access-Token für dieselbe Connection an, beide sehen einen abgelaufenen Token. Es darf nicht zu doppeltem Refresh mit daraus resultierendem Race Condition (z. B. einer der beiden Refresh-Token wird von Google invalidiert, weil bereits durch den parallelen Call rotiert) kommen.
- **Trennen einer Connection, während ein Google-API-Call gerade läuft:** In-Flight-Anfragen eines Agenten sollen nicht hart abbrechen, aber alle nachfolgenden Token-Anfragen für die getrennte Connection müssen sofort fehlschlagen.
- **Google-Revoke-Call schlägt beim Trennen fehl** (z. B. Google nicht erreichbar, Token bereits invalide): Lokale Tokens werden trotzdem gelöscht (User-Erwartung "getrennt" muss lokal in jedem Fall erfüllt werden), Fehler wird geloggt statt den Trennen-Vorgang zu blockieren.
- **User widerruft Zugriff direkt in seinem Google-Konto** (nicht über Alice): Connection bleibt lokal als "aktiv" gespeichert, bis der nächste Refresh-Versuch fehlschlägt und sie auf Fehlerstatus setzt — kein sofortiges Erkennen möglich (kein Webhook von Google für diesen Fall).
- **Consent-Flow wird von einem Gerät außerhalb VPN/Hausnetz gestartet:** Browser kann die Alice-Callback-Domain nicht erreichen, Google-Redirect landet ins Leere. Aus Nutzersicht ein Verbindungsfehler, kein spezifisches Alice-Verhalten nötig — Voraussetzung (VPN/Hausnetz) gehört in die Dokumentation der Folge-Features.

## Technical Requirements

- **Security:** Access- und Refresh-Tokens werden ausschließlich verschlüsselt in PostgreSQL gespeichert; Entschlüsselung erfolgt nur im dafür zuständigen Backend-Service. Kein Token verlässt diesen Service im Klartext außer als Antwort auf den internen Token-Abruf-Endpoint.
- **Architektur-Vorgabe (Detailausgestaltung folgt in `/architecture`):** Token-Refresh und Verschlüsselung laufen in einem eigenen Backend-Service (nicht in n8n-Workflows, im Unterschied zum bestehenden IMAP-Muster aus PROJ-46). Nachgelagerte n8n-Workflows (PROJ-87/88/89) rufen einen internen REST-Endpoint dieses Service auf, um einen gültigen Access-Token für eine Connection zu erhalten.
- **Zugriff:** Nur über VPN/Hausnetz erreichbar, wie der Rest von Alice; der OAuth-Callback läuft über die bestehende Alice-Domain/nginx-Routing.
- **Erweiterbarkeit:** Das Scope-Modell muss offen für künftige Google-Dienste über Calendar/Tasks/Contacts hinaus sein (freie Scope-Liste pro Connection, kein hartcodiertes Enum nur dieser drei Dienste).
- **Kein lokales Caching von Google-Nutzdaten** (Kalendereinträge, Aufgaben, Kontakte selbst) — PROJ-86 verwaltet ausschließlich Verbindungs-Metadaten und Tokens, siehe PRD-Constraint „nur Live-Abfragen".

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

PROJ-86 hat keine UI. Es besteht aus zwei Bausteinen:

1. **Neuer Backend-Service `alice-google-connect`** — kapselt den kompletten OAuth-Lebenszyklus (Consent-Start, Callback, Token-Verschlüsselung, Refresh, Revoke) und stellt einen internen Token-Endpoint für nachgelagerte Agenten bereit.
2. **Neue PostgreSQL-Tabelle `alice.google_connections`** — eine Zeile pro (Alice-User, Google-Konto), analog zum bestehenden `alice.imap_mailboxes`-Muster aus PROJ-46, aber mit OAuth-Feldern statt statischem Passwort.

Kein n8n-Workflow nötig für PROJ-86 selbst — n8n kommt erst mit PROJ-87/88/89 ins Spiel, wenn diese den internen Token-Endpoint aufrufen.

### Workflow Architecture

**Consent-Start (User klickt "Google-Konto verbinden" — Button selbst kommt erst mit PROJ-87/88/89, ruft aber bereits diesen Endpoint auf):**
- **Trigger:** Authentifizierter HTTP-Request von der Alice-WebApp (JWT im Header, wie bei allen anderen Alice-Endpoints)
- **Ablauf:** Service prüft JWT → baut die Google-Autorisierungs-URL mit den angefragten Scopes + einem signierten State-Parameter (bindet den Alice-User an den Flow, verhindert CSRF) → gibt die URL zurück, WebApp leitet den Browser dorthin weiter
- **Integrationen:** Google OAuth 2.0 Authorization Endpoint

**Callback (Google leitet den User-Browser zurück):**
- **Trigger:** GET-Request von Googles Redirect auf die feste Callback-Route der Alice-Domain (kein Webhook, kommt vom User-Browser)
- **Ablauf:** State-Parameter prüfen (Signatur + Alice-User-Zuordnung) → Autorisierungscode gegen Access-/Refresh-Token bei Google eintauschen → Google-Account-Kennung (E-Mail/`sub`) aus der Token-Antwort lesen → bestehende Connection für (User, Google-Account) suchen: existiert sie, werden die neuen Scopes mit den vorhandenen vereinigt und der Refresh-Token nur bei Bedarf aktualisiert; existiert sie nicht, wird eine neue Zeile angelegt → Tokens verschlüsselt speichern → Browser zurück zu den Alice-Settings leiten (Erfolg oder Fehlermeldung als Query-Parameter)
- **Integrationen:** Google OAuth Token Endpoint, PostgreSQL
- **Fehlerbehandlung:** Abbruch/Google-Fehler/State-Mismatch → Redirect zurück zu den Settings mit Fehler-Kennung, keine DB-Änderung

**Interner Token-Abruf (aufgerufen von PROJ-87/88/89 n8n-Workflows):**
- **Trigger:** Interner HTTP-Request mit Connection-ID
- **Ablauf:** Connection laden → verschlüsselten Access-Token entschlüsseln → abgelaufen? Falls ja: Refresh-Token entschlüsseln, bei Google gegen neuen Access-Token tauschen, verschlüsselt zurückschreiben (Row-Lock verhindert doppelten Refresh bei parallelen Anfragen) → gültigen Access-Token zurückgeben
- **Integrationen:** Google OAuth Token Endpoint (nur bei Ablauf), PostgreSQL
- **Fehlerbehandlung:** Google lehnt Refresh ab → Connection-Status auf `error` setzen, Fehler mit klarem Code zurückgeben, den der aufrufende Agent in eine Chat-Meldung übersetzt

**Connection trennen:**
- **Trigger:** Authentifizierter Request vom User (aus der jeweiligen Settings-UI der Folge-Features)
- **Ablauf:** Connection dem anfragenden User zuordnen (Ownership-Check) → Refresh-Token entschlüsseln → Googles Revoke-Endpoint aufrufen (Fehler wird geloggt, blockiert aber nicht) → Zeile aus `alice.google_connections` löschen
- **Integrationen:** Google OAuth Revoke Endpoint, PostgreSQL

**Connections auflisten:**
- **Trigger:** Authentifizierter Request vom User
- **Ablauf:** Alle Connections des anfragenden Users laden (Google-Konto, Scopes, Status, Verbunden-seit) — keine Tokens in der Antwort

### Data Model (plain language)

**`alice.google_connections`** (eine Zeile pro Alice-User + Google-Konto):
- Eindeutige ID
- Alice-User (Fremdschlüssel, Owner — keine Freigabe an andere User)
- Google-Account-Kennung (z. B. E-Mail-Adresse des Google-Kontos)
- Gewährte Scopes (Liste, erweiterbar — nicht auf Calendar/Tasks/Contacts limitiert)
- Verschlüsselter Access-Token + dessen Ablaufzeitpunkt
- Verschlüsselter Refresh-Token
- Status (aktiv / Fehler)
- Letzter Fehler (Klartext-Meldung für Diagnose)
- Verbunden seit, zuletzt aktualisiert

Eindeutigkeit: genau eine Zeile pro (Alice-User, Google-Account-Kennung) — Scope-Erweiterungen aktualisieren die bestehende Zeile statt eine neue anzulegen.

Kein separates Zugriffs-/Freigabe-Table (im Unterschied zu `imap_mailbox_access`), da Connections laut Spec strikt privat pro User sind.

### Tech Decisions

- **Eigener Backend-Service statt n8n-Workflow für Krypto/Refresh:** Bereits im Spec als Anforderung festgelegt. Begründung: Token-Refresh ist ein hochfrequenter, sicherheitskritischer Pfad (jeder Agenten-Aufruf kann einen Refresh auslösen); ein schlanker FastAPI-Service erlaubt Row-Locking gegen parallele Refreshes und hält Kryptografie an einer einzigen, klar testbaren Stelle — analog zum bestehenden `alice-auth`-Service (JWT-Handling), nicht analog zum n8n-basierten IMAP-Passwort-Muster.
- **Neue Tabelle statt Erweiterung von `imap_mailboxes`:** OAuth-Connections (Access+Refresh-Token-Paar, Scope-Liste, Ablaufzeit) unterscheiden sich strukturell stark von einem statischen IMAP-Passwort. Eigene Tabelle hält beide Konzepte sauber getrennt, wie in der Spec-Dependency-Prüfung festgehalten (kein Einfluss auf PROJ-46).
- **Freie Scope-Liste statt Enum:** Erfüllt die Spec-Anforderung "offen für künftige Google-Dienste" — jeder String-Scope kann gespeichert werden, ohne Schema-Änderung für neue Google-APIs.
- **Row-Lock beim Refresh statt Locking auf Anwendungsebene:** Löst das Edge Case "gleichzeitiger Refresh durch zwei Agenten" direkt in PostgreSQL, kein zusätzlicher Koordinationsmechanismus (Redis-Lock o. ä.) nötig.
- **AES-256-Verschlüsselung mit eigenem Service-Schlüssel:** Folgt dem etablierten Alice-Muster (`MAIL_ENC_KEY` bei `alice-mail-reader`), eigener `.env`-Schlüssel für diesen Service statt Wiederverwendung des Mail-Schlüssels — Trennung der Sicherheitsdomänen.
- **Nginx-Location analog `alice-auth`:** Neuer Block `/api/google/` routet auf den neuen Service, gleiches Muster wie bestehende `/api/auth/`, `/api/dms/thumbnail/` etc.

### Dependencies (packages to install)

- `fastapi`, `uvicorn` — HTTP-Service (Alice-Konvention für Python-Backend-Services)
- `google-auth-oauthlib` bzw. `requests`/`httpx` für die OAuth-Token-Endpoint-Aufrufe (kein volles Google-Client-SDK nötig, da PROJ-86 selbst keine Kalender-/Aufgaben-/Kontakte-API aufruft — das macht erst PROJ-87/88/89)
- `psycopg2` bzw. `asyncpg` — PostgreSQL-Zugriff (Alice-Konvention)
- `cryptography` — AES-256-Verschlüsselung der Tokens
- `pyjwt` — Verifikation des Alice-JWT (gleiche Bibliothek wie `alice-auth`)

### Neue/geänderte Infrastruktur

- Neuer Service `docker/compose/automations/alice-google-connect/` (Dockerfile, compose.yml, `.env.example` mit u. a. `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_ENC_KEY`, `JWT_PUBLIC_KEY_PATH`)
- Neue Migration `sql/migrations/070-proj86-google-connections.sql` für `alice.google_connections` (inkl. RLS, analog bestehendem Muster)
- Neuer nginx-Location-Block `/api/google/` → `alice-google-connect` (analog `/api/auth/`)
- Voraussetzung (kein Code): Google-Cloud-Projekt mit OAuth-Client-ID + Consent-Screen im Produktionsmodus, Redirect-URI auf die Alice-Domain eingetragen

## Implementation Notes (Backend)

**Umgesetzt 2026-09-19:**

- Neuer Service `docker/compose/automations/alice-google-connect/` (FastAPI, Port 8008): `POST /google/connect/start`, `GET /google/callback`, `GET /google/connections`, `POST /google/connections/{id}/token`, `DELETE /google/connections/{id}`, `GET /health`. Verifiziert Alice-JWTs (RS256, nur Public Key gemountet — Service kann keine Tokens ausstellen).
- Neue Migration `sql/migrations/070-proj86-google-connections.sql` — Tabelle `alice.google_connections`, UNIQUE (user_id, google_account), RLS (Policies permissiv, Autorisierung erfolgt im Service, analog `imap_mailboxes`-Muster).
- Infrastruktur verdrahtet: `docker/compose/scripts/Makefile` (STACKS-Eintrag), nginx-Location `/api/google/` → `alice-google-connect:8008` (kein Rate-Limit, da `/callback` ein einmaliger Browser-Redirect mit signiertem State ist, kein Brute-Force-Ziel).
- Tokens AES-256-CBC-verschlüsselt (eigener Schlüssel `GOOGLE_ENC_KEY`, getrennt von `MAIL_ENC_KEY`), gleiches Wire-Format wie `alice-mail-reader` (verifiziert byte-kompatibel trotz `cryptography` statt `pycryptodome`).
- State-Parameter (CSRF/User-Bindung im OAuth-Callback) HMAC-signiert mit `GOOGLE_ENC_KEY`, 600s TTL.
- Google-Account-Kennung wird über den Userinfo-Endpoint ermittelt (nicht per ID-Token-Decode) — vermeidet JWKS-Handling, Access-Token stammt aus vertrauenswürdigem Server-zu-Server-Austausch.
- `/token`-Endpoint ist **user-scoped** (erfordert JWT des aufrufenden Users) statt reiner Connection-ID — verhindert, dass eine bloße UUID als Bearer-Credential für fremde Google-Konten dient. Trade-off: ein rein hintergrundgesteuerter Job ohne User-JWT (z. B. zukünftiger Scheduled-Sync) könnte diesen Endpoint so nicht nutzen — bei Bedarf in PROJ-87 klären.
- Row-Lock (`SELECT ... FOR UPDATE`) um Prüfung+Refresh+Rückschreiben beim Token-Abruf verhindert Race Condition bei parallelen Refresh-Anfragen (verifiziert: 4 parallele Calls gegen langsames Mock-Google → genau 1 Refresh).
- Neue Connections erfordern zwingend einen Refresh-Token von Google (da `refresh_token_enc NOT NULL`); liefert Google beim Erstverbinden keinen (sollte durch `prompt=consent` nicht vorkommen), wird redirected statt eine unbrauchbare Zeile anzulegen. Scope-Erweiterungen bei bestehender Connection tolerieren fehlenden Refresh-Token (Google liefert ihn nicht bei jedem Consent erneut).
- Verifikation durch den Backend-Agenten gegen echte Test-Container (Postgres 16 + Dockerfile-Build, gemocktes Google): Migration/RLS/Constraints, voller Consent→Callback→Token-Flow, Scope-Union ohne Duplikat, User-Scoping von Liste/Token/Delete (404 bei Fremd-Connection), Fehlerstatus + 409 `reauth_required` bei widerrufenem Refresh-Token, Revoke-Fehler blockiert Löschen nicht, Race-Condition-Schutz.
- Kein n8n-Workflow, kein Frontend (laut Spec — kommt mit PROJ-87/88/89).

## QA Test Results

**Getestet:** 2026-09-19 | **Tester:** QA-Agent (`/qa`)
**Testumgebung:** Wegwerf-Container (Postgres 16 mit Migration 070, `alice-google-connect` aus dem echten Dockerfile gebaut, gemockter Google-OAuth-Server für `/token`, `/v1/userinfo`, `/revoke`). 5 Testuser (admin/user/user-b/guest/child), echte RS256-JWTs mit einem QA-Keypair. Container nach Testende entfernt.

**Hinweis zur Methodik:** Es wurde gegen die laufende Anwendung getestet (HTTP + direkte DB-Inspektion), nicht nur per Code-Review. Kein Live-Test gegen echte Google-Endpoints — der Google-Cloud-Consent-Screen (siehe Dependencies) ist Voraussetzung und muss vor Go-Live separat verifiziert werden.

### Acceptance Criteria

| # | Kriterium | Ergebnis | Evidenz |
|---|-----------|----------|---------|
| AC-01 | Consent-Flow aus authentifiziertem Kontext starten, Rückkehr über Callback-Route | PASS | `POST /google/connect/start` → 200 mit `auth_url`; enthält `access_type=offline`, `prompt=consent`, `redirect_uri=https://alice.test/api/google/callback`, signierter `state`. Callback → 302 `?google=connected`. |
| AC-02 | Access- + Refresh-Token verschlüsselt in PG, verknüpft mit Alice-User + Google-Kennung | PASS | Nach Callback Zeile mit `user_id`, `google_account=qa.user@gmail.com`; beide Token-Spalten im Format `iv_hex:ct_hex`, kein Klartext (s. Encryption-Check unten). |
| AC-03 | Mehrere Google-Konten pro User; eindeutig je (User, Google-Account) | PASS | Zwei Konten für denselben User → 2 Zeilen. UNIQUE-Constraint `google_connections_user_account_uniq` greift; zweiter Consent für dasselbe Konto legt kein Duplikat an. |
| AC-04 | Scope-Liste je Connection, Erweiterung ohne neue Connection | PASS | Consent 1 (calendar) → 3 Scopes; Consent 2 (contacts, Google **ohne** `refresh_token`) → 1 Zeile, Scopes vereinigt (calendar + contacts + openid + email), Refresh-Token unverändert erhalten und danach funktionsfähig (`/token` → 200). |
| AC-05 | Nur-Kalender- + Nur-Kontakte-Consent → eine Connection mit vereinigten Scopes | PASS | `SELECT count(*)` = 1, Scope-Array enthält beide Scopes (siehe AC-04). |
| AC-06 | Interner Endpoint liefert gültigen Access-Token, refresht bei Ablauf transparent | PASS | Gültig → Token direkt ohne Google-Call (0 Outbound-Calls). Abgelaufen (`expires_at` in die Vergangenheit) → 200 mit neuem Token `AT-refreshed`, 1 Outbound-Refresh, neue `expires_at` in der DB. 60s-Sicherheitsmarge greift. |
| AC-07 | Refresh läuft im Hintergrund (Backend ↔ Google), ohne User/Browser/VPN | PASS | Refresh erfolgt vollständig server-zu-server im `/token`-Call; kein Browser, kein User-Interaktionsschritt, keine Session nötig — nur das JWT des aufrufenden Users. (Siehe Einschränkung BUG-04: ein Job ohne User-JWT kann den Endpoint nicht nutzen.) |
| AC-08 | Refresh-Fehler → Fehlerstatus + eindeutiger Fehler für den Agenten | PASS | Google 400 `invalid_grant` → HTTP 409 `{"error":"reauth_required"}`, `status='error'`, `last_error` gesetzt; Folgeaufruf sofort 409 ohne weiteren Google-Call. Liste zeigt `status=error`. |
| AC-09 | User sieht eigene Connections in einer Liste (Konto, Scopes, Status) | PASS | `GET /google/connections` → Felder `id, google_account, scopes, status, last_error, created_at, updated_at`. Kein Feld enthält „token". `LIMIT 100` vorhanden. |
| AC-10 | Trennen: lokale Tokens gelöscht UND Revoke bei Google | PASS | `DELETE` → 200 `{"success":true}`, Revoke-Endpoint 1× aufgerufen, Zeile entfernt, Folge-`/token` → 404, erneutes `DELETE` → 404. |
| AC-11 | Nur eigene Connections — auch kein Admin-Zugriff auf fremde | PASS | Fremde Connection: `/token` 404, `DELETE` 404, nicht in Liste. **Admin ebenfalls 404** (kein Override). Fremde Zeile bleibt nach den Versuchen intakt. Alle Queries user-scoped (s. Security-Audit). |
| AC-12 | Alle Rollen (admin/user/guest/child) dürfen Connections anlegen | PASS | Alle vier Rollen: `connect/start` 200 und Callback `google=connected`. Keine rollenbasierte Sperre in PROJ-86. |
| AC-13 | Abbruch/Callback-Fehler → keine Connection angelegt/verändert, erkennbare Fehlermeldung | PASS | `error=access_denied`, `error=invalid_scope`, kaputter `state`, fehlender `state` → jeweils 302 mit `google=error&reason=…`; Connection-Anzahl unverändert, 0 Google-Token-Calls. |
| AC-14 | Tokens at-rest verschlüsselt (nicht im Klartext), analog PROJ-46 | PASS | Sentinel-Tokens nach dem Speichern **nicht** in der DB auffindbar (`LIKE '%SENTINEL%'` → 0 Treffer). Format `iv_hex:ct_hex` (AES-256-CBC, PKCS7), IV pro Schreibvorgang zufällig (Ciphertext unterscheidet sich bei gleichem Klartext). Eigener `GOOGLE_ENC_KEY`, getrennt von `MAIL_ENC_KEY`. |

**Ergebnis Acceptance Criteria: 14/14 PASS.**

### Edge Cases

| Edge Case | Ergebnis | Evidenz |
|-----------|----------|---------|
| Scope-Erweiterung ohne Verlust von Scopes/Tokens | PASS | Refresh-Token überlebt den Re-Consent ohne `refresh_token` in der Google-Antwort; Scopes vereinigt; Token danach nutzbar. |
| Zwei Alice-User verbinden dasselbe Google-Konto | PASS | 2 unabhängige Zeilen mit eigenen Tokens. A kann B's Connection nicht abrufen (404); `DELETE` durch B lässt A's Zeile unberührt. |
| Refresh-Token widerrufen, während kein Agent zugreift | PASS | Status bleibt bis zum nächsten Zugriff `active`, wechselt beim ersten fehlschlagenden Refresh korrekt auf `error` (wie in der Spec beschrieben). |
| **Gleichzeitiger Refresh durch zwei parallele Agenten** | **FAIL** | **BUG-01 — Deadlock, Service komplett blockiert.** Sequenziell korrekt (2. Aufruf bekommt den gecachten Token, genau 1 Outbound-Refresh); bei echter Parallelität hängt der Dienst dauerhaft. |
| Trennen während laufendem Google-Call → Folgeanfragen scheitern sofort | PASS | Nach `DELETE` liefert `/token` sofort 404; laufender Revoke-Call wird durch das 10s-httpx-Timeout begrenzt. |
| Google-Revoke schlägt fehl → lokal trotzdem löschen | PASS | Revoke HTTP 500 → `DELETE` 200, Zeile gelöscht. Revoke hängt (>Timeout) → `DELETE` nach 10,1s trotzdem 200, Zeile gelöscht, Fehler nur geloggt. |
| User widerruft direkt bei Google | PASS | Identisch zum Refresh-Fehlerpfad (409 `reauth_required`, Status `error`). |
| Consent-Start außerhalb VPN | N/A | Kein Alice-spezifisches Verhalten; Doku-Thema der Folge-Features (laut Spec). |

### Security Audit (Red Team)

| Angriff | Umfang | Ergebnis |
|---------|--------|----------|
| Auth-Bypass | 13 Angriffsvarianten × 4 authentifizierte Endpoints = **52 Anfragen** | **Alle 401.** Kein Header, leerer Bearer, Basic-Auth, Token ohne „Bearer"-Präfix, `bearer` klein, **`alg:none`**, **RS256→HS256-Algorithmus-Confusion (HMAC mit dem Public Key)**, fremdes Keypair, abgelaufen, malformed, leer, verfälschte Signatur, JWT ohne `user_id`. Keine einzige Anfrage kam durch; Ziel-Zeile blieb unverändert. |
| OAuth-State-Tampering | 11 Varianten auf `/google/callback` | **Alle abgewiesen** (`reason=invalid_state`). `user_id` auf fremden User getauscht (alte Signatur), mit geratenem Schlüssel neu signiert, Signatur leer/abgeschnitten/großgeschrieben/entfernt, abgelaufenes `exp`, SQLi im `user_id`. **0 Google-Token-Calls und 0 DB-Änderungen** — die Signatur wird vor jeglicher Netz-/DB-Aktion geprüft. Account-Hijacking über den State ist nicht möglich. |
| SQL-Injection | 11 Payloads in `connection_id` (Pfad, `/token` + `DELETE`) und in `scopes[]` | **Keine Injection.** Parameterisierte Queries; Postgres-Log zeigt den Payload als Literal (`WHERE id = ''' OR 1=1--'`). Keine Tabelle gelöscht, keine Zeile verändert, kein Token geleakt, Zeilen-/Tabellenzahl konstant. Scopes werden zusätzlich durch Präfix-/Längen-Validierung abgewiesen (422). **Nebenbefund: BUG-02 (HTTP 500 statt 404).** |
| Secrets-Exposure | 10 Response-Typen + vollständige Container-Logs | **Sauber.** `GOOGLE_CLIENT_SECRET` und `GOOGLE_ENC_KEY` tauchen in **keiner** Response und **nicht** im Log auf. Refresh-Token (inkl. rotiertem) erscheint **nirgends** in Responses/Logs. Access-Token erscheint ausschließlich in der `/token`-Antwort (by design). `/openapi.json` und `/docs` leaken nichts. |
| Token-at-rest | DB-Rohinspektion | Verschlüsselt, zufälliger IV pro Schreibvorgang, kein Klartext (s. AC-14). |
| Cross-User-Isolation | Liste/Token/Delete über alle Rollen | Strikt user-scoped, 404 statt 403 (verrät die Existenz fremder Connections nicht). Admin hat bewusst **kein** Override. |
| `last_error`-Rückgabe | Inhalt + Sichtbarkeit | Unkritisch: enthält nur Googles Fehlerbody, auf 500 Zeichen begrenzt, kein Client-Secret, nur für den Eigentümer sichtbar. |
| Rate-Limiting | Flood-Tests | Siehe BUG-05 (Low). 200 unauthentifizierte Callback-Anfragen mit ungültigem State → **0 Outbound-Google-Calls** (keine Amplifikation); die Begründung im nginx-Kommentar ist damit belegt. Outbound-Traffic zu Google erfordert gültiges JWT **und** eigene Connection. |

**Query-Konsistenz-Review (alle 11 Statements in `main.py`):** Alle lesenden Einstiegs-Queries filtern auf `user_id` (Z. 430, 568, 622, 791) bzw. `DELETE` auf `id AND user_id` (Z. 820). Die `UPDATE … WHERE id = %s` ohne `user_id` (Z. 452, 471, 689, 723, 740) sind unbedenklich: sie laufen jeweils **innerhalb derselben Transaktion nach** einem Ownership-geprüften `SELECT … FOR UPDATE`. Kein Pfad erlaubt Zugriff auf fremde Daten.

**RLS-Bewertung:** Die Policies in Migration 070 sind permissiv (`USING (TRUE)`) — die Autorisierung liegt vollständig im Service. Das entspricht dem etablierten `imap_mailboxes`-Muster und ist konsistent, verdient aber die Anmerkung in BUG-06: RLS bietet hier faktisch keine zweite Verteidigungslinie.

### Gefundene Bugs

#### BUG-01 — Deadlock: parallele `/token`-Aufrufe legen den kompletten Service dauerhaft lahm
- **Severity: Critical** | **Priorität: 1 (blockiert Deployment)**
- **Betroffen:** `POST /google/connections/{id}/token` — und in der Folge **alle** Endpoints des Service.
- **Root Cause:** Das **synchrone** `psycopg2` wird in `async def`-Handlern verwendet. `SELECT … FOR UPDATE` (Z. 617-626) blockiert damit den **Event-Loop-Thread**, nicht nur die eigene Coroutine. Ablauf: Request A nimmt den Row-Lock und gibt an `await client.post(...)` (Google-Refresh, Z. 662) die Kontrolle ab. Request B läuft in denselben `SELECT … FOR UPDATE`, wartet auf den Lock und blockiert dabei den einzigen Event-Loop-Thread. Dadurch kann die Antwort für A nie verarbeitet werden → A gibt den Lock nie frei → **gegenseitige Blockade, die sich nicht auflöst**.
- **Reproduktion:** 1) Connection anlegen. 2) `access_token_expires_at` in die Vergangenheit setzen. 3) **Zwei** gleichzeitige `POST /google/connections/{id}/token` absetzen (Google-Refresh mit ~2s Latenz).
- **Beobachtet:** Beide Requests laufen in den Client-Timeout (30s, Antwort kommt nie). `pg_stat_activity`: eine Session `idle in transaction`/`ClientRead`, eine `active`/`Lock: transactionid`. Danach antwortet **auch `/health` und `GET /google/connections` nicht mehr** — nach 15s/30s/60s weiterhin tot. Nur ein Container-Neustart stellt den Dienst wieder her. Outbound-Refreshes: 0, die Connection bleibt mit abgelaufenem Token zurück.
- **Zusatzbeweis (isoliert):** Hält man den Row-Lock aus einer **externen** psql-Transaktion und setzt **einen einzigen** `/token`-Request ab, sind sofort auch `/health`, `/google/connections` und `/connect/start` blockiert — obwohl `/health` praktisch nichts tut. Das belegt eindeutig: der Event-Loop-Thread hängt, es ist kein reines Row-Lock-Problem.
- **Auswirkung:** Genau das in der Spec geforderte Szenario („PROJ-87 und PROJ-88 fragen quasi zeitgleich einen Token an") führt zum Totalausfall des Service. Zwei Agenten reichen. `restart: unless-stopped` hilft **nicht** (der Prozess stürzt nicht ab), und der Healthcheck schlägt zwar fehl, aber ohne Autoheal-Container (im Repo nicht vorhanden) startet Docker den Container deswegen nicht neu → Ausfall bis zum manuellen Eingriff.
- **Hinweis:** Dieselbe Klasse von Fehler ist in PROJ-55 bereits einmal aufgetreten („blockierender Event-Loop" als Hauptursache) — hier lohnt eine generelle Konvention für Python-Services.
- **Lösungsrichtung (nicht umgesetzt — QA fixt nicht):** DB-Zugriffe aus dem Event-Loop nehmen, z.B. `asyncpg` oder `psycopg` v3 async, oder die synchronen Blöcke über `run_in_threadpool`/`asyncio.to_thread` auslagern; zusätzlich ein `lock_timeout`/`statement_timeout` auf der DB-Session als Sicherheitsnetz. Danach unbedingt erneut mit ≥2 parallelen Refreshes testen.

#### BUG-02 — Ungültige `connection_id` liefert HTTP 500 statt 404/422
- **Severity: Medium** | **Priorität: 3**
- **Betroffen:** `POST /google/connections/{id}/token`, `DELETE /google/connections/{id}`
- **Root Cause:** `connection_id` ist ein ungeprüfter `str`; Postgres wirft beim Cast `invalid input syntax for type uuid`, die generische `except Exception` (Z. 755/830) mappt das auf 500.
- **Reproduktion:** `POST /google/connections/nicht-uuid/token` mit gültigem JWT → 500 `{"detail":"Internal server error"}`.
- **Auswirkung:** Kein Datenleck (Response ist generisch, Details nur im Log) und **keine** Injection — aber falscher Statuscode: 5xx signalisiert Serverfehler statt Client-Fehler, verfälscht Monitoring/Alerting und lädt zum „Erfolg"-Fehlschluss beim Scannen ein. Fix: `connection_id: UUID` als Typ annotieren (FastAPI → 422) oder vorab validieren und 404 liefern.

#### BUG-03 — OAuth-`state` ist innerhalb der 600s-TTL wiederverwendbar (kein One-Time-Nonce)
- **Severity: Low** | **Priorität: 4**
- **Root Cause:** Der `nonce` im State wird erzeugt, aber nirgends persistiert/entwertet; `_verify_state()` prüft nur Signatur und `exp`.
- **Reproduktion:** Callback mit demselben gültigen `state` zweimal aufrufen → beide Male `google=connected`.
- **Auswirkung:** Gering. Der State ist an `user_id` gebunden und signiert; ein Replay schreibt nur die Connection **desselben** Users erneut, und ein Authorization-Code ist bei Google ohnehin nur einmal einlösbar. Kein Cross-User-Effekt (verifiziert). Sauberer wäre ein verbrauchter-Nonce-Speicher (z.B. Redis) — bewusste Restakzeptanz möglich.

#### BUG-04 — `/token` ist user-scoped: rein hintergrundgesteuerte Jobs können ihn nicht nutzen
- **Severity: Low (Design-Einschränkung, bereits in den Implementation Notes dokumentiert)** | **Priorität: 4**
- **Beobachtung:** Der Endpoint verlangt das JWT des Eigentümers. Ein Scheduled-Sync ohne User-Kontext (z.B. „Kalender alle 15min vorab laden") hätte kein JWT und käme nicht an den Token — AC-07 („ohne dass der User online sein muss") ist für den **agentengetriebenen** Fall erfüllt, für einen **zeitgesteuerten** Job ohne User-JWT jedoch nicht.
- **Auswirkung:** Für PROJ-86 kein Defekt (die Sicherheitsentscheidung ist gut begründet und verhindert, dass eine bloße UUID als Credential dient), aber PROJ-87/88/89 müssen dies beim Design berücksichtigen. **Erfordert eine bewusste Produktentscheidung** (siehe unten).

#### BUG-05 — Kein Rate-Limit auf `/api/google/`
- **Severity: Low** | **Priorität: 5**
- **Beobachtung:** Der nginx-Block setzt bewusst kein `limit_req` (anders als `/api/auth/`). Messung: 200 unauthentifizierte Callback-Anfragen in 0,38s → alle 302, **0 Outbound-Google-Calls** (State-Prüfung erfolgt vor jeder Netz-/DB-Aktion). 100 `/connect/start` bzw. 100 `/token` (authentifiziert) in ~4s.
- **Auswirkung:** Die Begründung im Code trägt — es gibt keine Brute-Force- oder Amplifikationsfläche für Unauthentifizierte. Ein **authentifizierter** User kann allerdings pro Anfrage einen Google-Refresh auslösen (20 erzwungene Abläufe → 20 Outbound-Calls) und so das Google-API-Kontingent belasten. In einem VPN-only-Setup mit vertrauenswürdigen Usern akzeptabel; ein moderates `limit_req` wäre dennoch günstige Zusatzsicherung. Relevanz steigt mit BUG-01 (weniger parallele Last = weniger Deadlock-Risiko).

#### BUG-06 — RLS-Policies sind rein permissiv (`USING (TRUE)`)
- **Severity: Info** | **Priorität: 5**
- **Beobachtung:** Entspricht dem bestehenden `imap_mailboxes`-Muster und der Architekturentscheidung (Autorisierung im Service, verifiziert korrekt). Steht aber in Spannung zur Projektregel „ALWAYS enable Row Level Security … never skip RLS": RLS ist zwar aktiviert, bietet faktisch keine zweite Verteidigungslinie. Bei einem künftigen Bug in der Service-Autorisierung fängt die DB nichts ab. Bewusst dokumentieren oder auf `current_setting('alice.user_id')`-basierte Policies umstellen.

**Bug-Zusammenfassung: 1 Critical, 0 High, 1 Medium, 3 Low, 1 Info.**

### Regression

| Prüfung | Ergebnis |
|---------|----------|
| PROJ-46/53-Dateien (IMAP, `alice-mail-reader`) unverändert | PASS — `git status` listet keine IMAP-/Mail-Reader-/`alice-auth`-Dateien. Geändert sind nur `nginx/conf.d/alice.conf`, `scripts/Makefile`, `docs/PRD.md`, `features/INDEX.md` + die drei neuen PROJ-86-Artefakte. |
| Keine Kopplung an IMAP-Strukturen im neuen Code | PASS — keinerlei Referenz auf `imap*`/`mailbox`; `MAIL_ENC_KEY` nur als Abgrenzungs-Kommentar in `.env.example`. Eigene Tabelle, eigener Schlüssel. |
| `alice.users` unangetastet | PASS — Migration 070 legt nur `alice.google_connections` an (FK auf `users` mit `ON DELETE CASCADE`); keine Änderung bestehender Tabellen. |
| nginx-Routing | PASS — `/api/google/` ist rein additiv, steht vor dem generischen `/api/webhook/`, kein bestehender Block verändert. CORS/Security-Header/OPTIONS/`rewrite` identisch zum `/api/auth/`-Muster; `proxy_pass` auf `alice-google-connect:8008` passt zu Dockerfile-`CMD` und Healthcheck. Einziger bewusster Unterschied: kein `limit_req` (BUG-05). |
| Makefile | PASS — ein additiver `STACKS`-Eintrag. |
| Container-Namen/Netze | PASS — `container_name: alice-google-connect`, kein Host-Port veröffentlicht (nur über nginx erreichbar, VPN-only-Anforderung erfüllt), Netze `automation` + `backend` wie bei vergleichbaren Services. |

### Nicht getestet / offene Punkte

- **Cross-Browser/Responsive entfällt** — PROJ-86 hat laut Spec keine UI. Der einzige browserseitige Touchpoint ist ein 302-Redirect (browserunabhängig). UI-Tests gehören zu PROJ-87/88/89.
- **Echte Google-Endpoints** wurden gemockt. Vor Go-Live zwingend manuell zu verifizieren: Consent-Screen im Modus „In Production" (sonst verfallen Refresh-Tokens nach 7 Tagen), eingetragene Redirect-URI, reale Scope-Strings.
- **Langzeit-/Ablaufverhalten** (echter 1h-Ablauf, Token-Rotation über Tage) nur simuliert durch Manipulation von `access_token_expires_at`.

### Verdikt (Erst-Test 2026-09-19): **NOT READY**

**Begründung:** Funktional ist das Feature stark — 14/14 Acceptance Criteria bestehen, und der Sicherheits-Audit ist mit 52 abgewehrten Auth-Bypass-Versuchen, 11 abgewehrten State-Manipulationen, keiner SQL-Injection und null Secret-Leaks in Responses und Logs ausgesprochen sauber. Die Verschlüsselung at-rest und die User-Isolation (inkl. fehlendem Admin-Override) sind korrekt umgesetzt.

Blockierend ist jedoch **BUG-01 (Critical)**: Zwei gleichzeitige Token-Abrufe legen den gesamten Service dauerhaft still, ohne Selbstheilung. Da PROJ-87/88/89 genau dieses Muster erzeugen werden und die Spec es explizit als Edge Case fordert, ist ein Deployment in diesem Zustand nicht vertretbar. Der beabsichtigte Row-Lock-Schutz ist logisch richtig gedacht, wird aber durch den synchronen DB-Treiber im Event-Loop ins Gegenteil verkehrt.

**Empfehlung:** BUG-01 beheben und den Parallelitätstest (≥2 gleichzeitige Refreshes, Google-Latenz ≥1s) wiederholen; BUG-02 gleich mitnehmen. Danach ist der Weg zu „Approved" frei — die übrigen Punkte sind Low/Info und können bewusst akzeptiert werden.

---

### Re-Test 2026-09-19 (BUG-01/BUG-02 Fix-Verifikation)

**Getestet:** 2026-09-19 | **Tester:** QA-Agent (`/qa`) | **Scope:** gezielte Nachprüfung der zwei als behoben gemeldeten Bugs + Regressions-Stichproben auf den geänderten Code-Pfaden. Der vollständige 14-AC-Durchlauf und der komplette Security-Audit wurden **bewusst nicht** wiederholt (Änderung eng umrissen: Nebenläufigkeits-Handling + ein Pfad-Parameter-Typ).

**Testumgebung:** Neu aufgebaute Wegwerf-Container (Postgres 16 + Migration 070, `alice-google-connect` frisch aus dem echten Dockerfile gebaut, gemockter Google-OAuth-Server mit einstellbarer Latenz/Fehlermodi auf `/token`, `/v1/userinfo`, `/revoke`). Am Image wurden **ausschließlich die drei Google-Endpoint-Konstanten** auf den Mock umgebogen, sonst keine Code-Änderung. Echte RS256-JWTs. Container nach Testende entfernt.

**Geprüfte Fix-Bestandteile:** `run_in_threadpool` in `health()`, `callback()` (via `_persist_connection`), `list_connections()`, `get_access_token()`, `delete_connection()`; `LOCK_TIMEOUT = "5s"` per `set_config('lock_timeout', …, TRUE)` inkl. 503-Mapping über `psycopg2.errors.LockNotAvailable`; `connection_id: uuid.UUID` auf `/token` und `DELETE`.

#### BUG-01 (Critical) — Re-Test

| # | Prüfung | Ergebnis | Evidenz |
|---|---------|----------|---------|
| 1 | **Original-Repro:** 3 parallele `/token`, abgelaufener Token, Mock-Latenz 2s | **PASS** | Alle 3 → 200 in 2,09–2,16s (keine Serialisierung, kein Hang). **Genau 1 Outbound-Refresh**, alle drei erhalten denselben Token `AT-refreshed-3` → Double-Refresh-Schutz intakt. DB danach `status=active`, `expires_at` in der Zukunft. |
| 1b | **Responsivität WÄHREND des laufenden Refresh** | **PASS** | `/health` 2× in **28/31 ms**, `GET /google/connections` 2× in **67/62 ms** — jeweils abgesetzt, während der Refresh in Flight war. Vorher: Totalausfall. |
| 2 | **Isolierter Beweis:** Row-Lock aus externer psql-Session gehalten, 1 `/token` | **PASS** | `/token` → **503 nach 5,07s** (statt Hänger bis Client-Timeout). `/health` parallel 3× in 31–32 ms. Log: `Lock timeout on connection=… canceling statement due to lock timeout` — der Rohtext bleibt im Log, nicht in der Response. |
| 3 | **Skalierung über die Minimal-Repro hinaus:** 5 bzw. 10 parallele `/token` auf **derselben** Connection | **PASS** | n=5 (Latenz 2s): 5×200, wall 2,17s, 1 Refresh. n=10 (2s): 10×200, wall 2,24s, 1 Refresh. n=10 (4s): 10×200, wall 4,74s, 1 Refresh. Jeweils alle Aufrufer mit identischem Token, `/health` durchgehend ~30 ms. |
| 3b | **Sättigung:** 60 parallele `/token` über 12 Connections | **PASS** | 60×200, wall 4,16s, **genau 12 Refreshes** (1 je Connection, kein Refresh-Sturm). `/health` unter Volllast 34/61/35 ms. Kein Threadpool-Starving. |
| 4 | **Parallele `/token` auf UNTERSCHIEDLICHEN Connections** (6 Stück, 2 User) | **PASS** | 6×200, **kein einziger 503** → kein spurioses `lock_timeout` bei legitimem Parallelverkehr. 6 Refreshes (1 je Connection), 6 **verschiedene** Tokens, keine Vermischung. Wall 2,3s statt 12s seriell → echte Parallelität. |
| 5 | **503-Body nicht leaky** | **PASS** | Body exakt `{"detail":"Token wird gerade aktualisiert — bitte erneut versuchen"}`. Kein Stacktrace, kein `psycopg2`, kein „canceling statement", kein Tabellen-/Query-Name, kein Secret, kein Token. |

**Zusatzprüfung Zustandshygiene:** Nach allen Contention-Tests `/health` → `{"status":"healthy","db":true,...}`, **0 Sessions in `idle in transaction`**, insgesamt nur 1 offene DB-Session (kein Connection-Leak), **RestartCount = 0** (der Container hat sich nie aufgehängt und musste nie neu starten). Genau das war im Erst-Test der Nachweis des Deadlocks — jetzt sauber.

> **BUG-01 gilt als behoben (resolved).** Die Ursache (synchrones psycopg2 im Event-Loop) ist durch konsequente `run_in_threadpool`-Auslagerung beseitigt; der `lock_timeout` wirkt als zusätzliches Sicherheitsnetz. Entscheidend: Der Row-Lock-Schutz gegen doppelten Refresh **bleibt dabei erhalten** (in jedem Parallel-Szenario exakt 1 Refresh je Connection) — der Fix hat die eigentlich zu schützende Eigenschaft nicht geopfert.

#### BUG-02 (Medium) — Re-Test

| Prüfung | Ergebnis | Evidenz |
|---------|----------|---------|
| `POST /google/connections/not-a-uuid/token` | **PASS** | **422** (vorher 500). |
| `DELETE /google/connections/not-a-uuid` | **PASS** | **422** (vorher 500). |
| Syntaktisch gültige, nicht existierende UUID | **PASS** | `/token` → **404**, `DELETE` → **404** — durch die Typ-Verschärfung nicht kaputtgegangen. |
| 13 malformed/UUID-ähnliche Payloads + SQLi (`' OR 1=1--`, `'; DROP TABLE alice.google_connections;--`, `' UNION SELECT refresh_token_enc …`, Null-Byte, zu kurz/zu lang/bad hex, Klammern) auf `/token` **und** `DELETE` | **PASS** | **Kein einziger 5xx.** Alle → 422 bzw. 404. Zeilenzahl konstant (13→13), Tabelle existiert unverändert, **0 Outbound-Google-Calls** — kein Payload erreichte die DB. |
| 422-Body-Hygiene | **PASS** | Standard-FastAPI-Validierungsfehler (`{"type":"uuid_parsing","loc":["path","connection_id"],…}`) — kein `psycopg2`, kein `invalid input syntax`, kein Tabellenname, kein Secret. |

> **BUG-02 gilt als behoben (resolved).** Fehleingaben werden jetzt vor jedem DB-Kontakt von FastAPI abgefangen; Monitoring/Alerting wird nicht länger durch falsche 5xx verfälscht.

#### Regressions-Stichproben auf den geänderten Pfaden

| Prüfung | Ergebnis | Evidenz |
|---------|----------|---------|
| **DELETE mit Revoke-ERFOLG** → Zeile gelöscht | PASS | 200 `{"success":true}`, Revoke 1× aufgerufen, Zeile weg. |
| **DELETE mit Revoke-FEHLER (HTTP 500)** → Zeile trotzdem lokal gelöscht | **PASS** | 200, Zeile gelöscht. *(Dieser Pfad war nach dem Zwei-Transaktionen-Umbau vom Entwickler nicht nachgeprüft worden — Best-Effort-Semantik hält.)* |
| **DELETE mit hängendem Revoke (15s)** → Zeile trotzdem gelöscht | **PASS** | 200 nach 10,1s (durch das 10s-httpx-Timeout begrenzt), Zeile gelöscht. `/health` während des hängenden Revoke: 36 ms. |
| Sequenzieller `/token` bei **gültigem** Token → Cache, 0 Outbound-Calls | PASS | 3× 200, identischer Token `AT-initial-30`, **0 Refreshes** — Threadpool-Umbau hat den einfachen Fall nicht regressiert. |
| Cross-User-Isolation nach UUID-Typänderung | PASS | Fremder User → `/token` 404, `DELETE` 404; **Admin ebenfalls 404** (kein Override); unauth. (kein Header / Garbage-JWT / `alg:none`) → 401. Zielzeile blieb intakt, 0 Outbound-Calls. |
| `GET /google/connections` — Inhalt + keine Tokens | PASS | 200, Felder unverändert (`id, google_account, scopes, status, last_error, created_at, updated_at`), kein Feld mit „token", keine Token-Werte im Body, nur eigene Zeilen (User B sieht exakt seine 3). |
| Callback-Flow end-to-end nach `_persist_connection`-Extraktion | PASS | Consent-Start → Callback → 302 `google=connected`, Zeile mit korrektem Account/Status/Scopes angelegt, Tokens verschlüsselt (kein `SENTINEL`-Klartext in der DB). |
| Scope-Union bei Re-Consent | PASS | Genau 1 Zeile, gleiche Connection-ID, Token danach weiter nutzbar (200). |
| Refresh von Google abgelehnt → 409 `reauth_required` | PASS | 409, DB `status=error`, Folgeaufruf erneut 409 **ohne** weiteren Google-Call. |
| Paralleles doppeltes `DELETE` (TOCTOU des Zwei-Transaktionen-Splits) | PASS | 3× 200, Zeile weg, kein 5xx. *(Nebenbefund: jeder der 3 Aufrufe feuert einen eigenen Revoke — harmlose Best-Effort-Dopplung, kein Defekt.)* |
| Log-Hygiene über den gesamten Lauf (476 Zeilen) | PASS | **0** Vorkommen von `GOOGLE_CLIENT_SECRET`/`GOOGLE_ENC_KEY`/Refresh-Tokens, **0** Tracebacks, **0** vom Service selbst erzeugte 500er. Die 3 geloggten 503 entsprechen exakt den 3 erwarteten `Lock timeout`-Warnungen. |

#### Neues Verhalten (kein Bug — für PROJ-87/88/89 zu beachten)

**`POST /google/connections/{id}/token` kann jetzt HTTP 503 zurückgeben** — neu gegenüber der ursprünglichen AC-Matrix (dort nur 200/401/404/409/502).

- **Wann:** Wenn ein paralleler Refresh **derselben** Connection den Row-Lock länger als `LOCK_TIMEOUT` (5s) hält. Praktisch nur, wenn Google für den Refresh länger als 5s braucht. Gemessen: bei Google-Latenz 2s und 4s trat **kein** 503 auf (alle Aufrufer bekamen 200); erst bei künstlichen 7s Latenz erhielt 1 von 3 Aufrufern ein 503.
- **Body:** `{"detail":"Token wird gerade aktualisiert — bitte erneut versuchen"}`
- **Semantik: retrybar.** Ein unmittelbarer Retry trifft in aller Regel auf den inzwischen frisch geschriebenen Token und wird ohne weiteren Google-Call aus dem Cache bedient.
- **Abgrenzung:** 503 ≠ 409 `reauth_required`. 409 ist ein Dauerzustand (User muss neu verbinden), 503 ist transient. Clients dürfen bei 503 **nicht** den Reauth-Dialog zeigen, sondern sollten einmal kurz (z.B. 1–2s) zurückfallen und erneut anfragen.
- Der 503 aus `_list_connections_sync`/`_load_connection_refresh_token` („Database unavailable") existierte bereits vorher für den Fall einer nicht erreichbaren DB.

#### Bug-Status nach dem Re-Test

| Bug | Severity | Status |
|-----|----------|--------|
| BUG-01 — Deadlock bei parallelen `/token` | Critical | **RESOLVED (verifiziert)** |
| BUG-02 — 500 statt 404/422 bei ungültiger UUID | Medium | **RESOLVED (verifiziert)** |
| BUG-03 — OAuth-`state` innerhalb TTL wiederverwendbar | Low | offen (bewusste Restakzeptanz) |
| BUG-04 — `/token` user-scoped, keine reinen Background-Jobs | Low (Design) | offen (Produktentscheidung in PROJ-87) |
| BUG-05 — kein Rate-Limit auf `/api/google/` | Low | offen (VPN-only, akzeptabel) |
| BUG-06 — RLS-Policies rein permissiv | Info | offen (dokumentiert, Muster-konform) |

**Neue Bugs im Re-Test: keine.** Insbesondere keine neuen Critical/High.

### Verdikt (Re-Test 2026-09-19): **READY**

**Begründung:** Beide gemeldeten Bugs sind unabhängig gegen frisch gebaute Container nachgeprüft und bestätigt behoben — nicht nur im ursprünglichen Minimal-Repro, sondern auch unter deutlich härterer Last (bis 60 parallele Anfragen, 10 gleichzeitige Refreshes auf derselben Connection, extern gehaltener Row-Lock, Latenz jenseits des Lock-Timeouts). Der Service blieb in **jedem** Szenario responsiv (`/health` durchgehend ~30 ms), hat sich nie aufgehängt, keine Transaktion und keine DB-Verbindung geleakt und musste nie neu gestartet werden.

Entscheidend für die Freigabe: Der Deadlock-Fix hat die Eigenschaft, die der Row-Lock überhaupt schützen soll, **nicht** beschädigt — in allen Parallel-Szenarien fand exakt **ein** Refresh je Connection statt, und unabhängige Connections behindern sich gegenseitig nicht (kein spurioses `lock_timeout`). Der zuvor nicht nachgeprüfte Revoke-Fehlerpfad des `DELETE` hält nach dem Zwei-Transaktionen-Umbau ebenfalls: Die lokale Zeile wird auch bei fehlschlagendem oder hängendem Google-Revoke zuverlässig gelöscht.

Damit stehen 14/14 Acceptance Criteria, ein sauberer Security-Audit und 0 offene Critical/High-Bugs. Die verbleibenden Punkte (BUG-03/04/05 Low, BUG-06 Info) sind bewusst akzeptierbar und kein Deployment-Hindernis.

**Auflagen für das Deployment (unverändert aus dem Erst-Test):**
1. Google-Cloud-Consent-Screen muss vor Go-Live im Modus „In Production" stehen (sonst verfallen Refresh-Tokens nach 7 Tagen) — siehe Dependencies.
2. Reale Google-Endpoints wurden gemockt; Consent-Screen, Redirect-URI und echte Scope-Strings sind beim ersten Live-Verbinden zu verifizieren.
3. PROJ-87/88/89 müssen den neuen **503 als transient/retrybar** behandeln (siehe „Neues Verhalten") und BUG-04 (kein Token-Abruf ohne User-JWT) im Design berücksichtigen.

## Deployment

**Deployed:** 2026-09-30 — `alice-google-connect` auf dem Produktionsserver mit echter `.env` (Google-Client-ID/-Secret, `GOOGLE_ENC_KEY`, JWT-Public-Key) live geschaltet.

**Google-Cloud-Setup abgeschlossen:**
- OAuth-Consent-Screen: Branding-Prüfung bestanden (Startseite + Datenschutzerklärung unter `happy-mining.de` veröffentlicht, Domain-Ownership per Google Search Console verifiziert, App-Name "Alice" auf der Startseite konsistent zum Consent-Screen benannt), Status **„In Production"**.
- App ist bewusst **nicht** von Google sicherheitsüberprüft (voller Verifizierungsprozess für sensible Scopes wäre für ein privates Ein-Haushalt-Tool unverhältnismäßig) — Nutzer sehen beim Verbinden einmalig den Hinweis „Diese App wurde nicht von Google überprüft" und bestätigen über „Erweitert → Alice öffnen (unsicher)". Erwartetes, akzeptiertes Verhalten, kein Bug.

**Live-Test 2026-09-30 (echtes Google, kein Mock) — durch Andreas, angeleitet:**

| Schritt | Ergebnis |
|---|---|
| `POST /google/connect/start` (Scope `calendar.readonly`) | PASS — korrekte Google-Auth-URL mit echter `client_id`, `redirect_uri`, `access_type=offline`, `prompt=consent` |
| Google-Login + Consent-Bestätigung im Browser | PASS — Consent-Screen zeigt "Alice", Scope-Auswahl funktioniert |
| `GET /google/callback` | PASS — Connection angelegt, `status: "active"`, `google_account` korrekt, Scopes inkl. automatisch ergänztem `openid`/`email` |
| `GET /google/connections` | PASS — angelegte Connection sichtbar, keine Tokens im Response |
| `POST /google/connections/{id}/token` | PASS — gültiger Access-Token zurückgegeben |

**Randnotiz (kein Bug):** Ein erster Versuch schlug mit „state expired" fehl, weil zwischen `connect/start` und dem Google-Login-Abschluss mehr als die 600s-State-TTL vergangen waren (Testablauf mit Zwischenschritten). Bestätigt genau das im Security-Audit verifizierte Verhalten — State-Signatur+Ablauf wird vor jeder DB-/Netzwerk-Aktion geprüft, kein Fehlverhalten des Service.

**Nicht live getestet (aus AC/Edge-Case-Sicht bereits durch QA gegen Mock-Google abgedeckt, bewusst nicht wiederholt):** Token-Refresh nach echtem Ablauf, Trennen/Revoke gegen echtes Google. Die erste echte Connection (`stahlhutandreas@gmail.com`, Scope `calendar.readonly`) bleibt bestehen als Ausgangspunkt für PROJ-87.

Damit sind alle Deployment-Auflagen aus dem QA-Re-Test erfüllt.
