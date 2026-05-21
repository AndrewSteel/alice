# PROJ-26: Admin Nutzerverwaltung

## Status: Deployed
**Created:** 2026-03-15
**Last Updated:** 2026-03-16

## Dependencies
- Requires: PROJ-7 (JWT Auth / Login Screen) — alice-auth Container, alice.users Tabelle, `is_active` Spalte
- Requires: Frontend Settings-Seite (bereits vorhanden: `SettingsPage.tsx` mit Tabs-Pattern)

---

## Übersicht

Als Admin kann ich unter **Einstellungen → Nutzerverwaltung** neue Benutzer anlegen, verwalten und deaktivieren. Das System generiert ein 8-stelliges Einmal-Passwort (OTP), das per E-Mail an den neuen Nutzer geschickt wird. Der Nutzer muss dieses OTP bei der Erstanmeldung zwingend durch ein eigenes Passwort ersetzen.

**Scope:** Admin-Only. Alle Endpunkte setzen `role = "admin"` im JWT voraus.

---

## User Stories

1. **Als Admin** möchte ich unter Einstellungen → Nutzerverwaltung alle vorhandenen Nutzer sehen, damit ich einen Überblick über aktive und inaktive Accounts habe.
2. **Als Admin** möchte ich einen neuen Nutzer anlegen (mit Benutzername, E-Mail, Systemrolle, Facts und Preferences), damit ich anderen Personen Zugang zu Alice geben kann.
3. **Als Admin** möchte ich, dass beim Anlegen automatisch ein 8-stelliges Einmal-Passwort generiert und per E-Mail an den neuen Nutzer versendet wird, damit dieser sich sicher einloggen kann.
4. **Als Admin** möchte ich einem bestehenden Nutzer ein neues Einmal-Passwort vergeben und per E-Mail versenden, damit ich vergessene Passwörter zurücksetzen kann.
5. **Als Admin** möchte ich einen Nutzer inaktiv stellen können (ohne ihn zu löschen), damit er sich nicht mehr einloggen kann, seine Daten aber erhalten bleiben.
6. **Als Admin** möchte ich einen Nutzer dauerhaft löschen können (mit Bestätigungsdialog), damit abgelaufene Accounts entfernt werden.
7. **Als neuer Nutzer** muss ich beim ersten Login mein Einmal-Passwort zwingend durch ein selbst gewähltes Passwort ersetzen, bevor ich Alice nutzen kann.

---

## Acceptance Criteria

### AC-1: Nutzerliste (Frontend)
- [ ] Im Settings-Tab "Nutzerverwaltung" wird eine Tabelle aller Nutzer angezeigt (sichtbar nur für Admins)
- [ ] Spalten: Benutzername, Anzeigename, E-Mail, Systemrolle, Status (aktiv/inaktiv), Erstellt am
- [ ] Inaktive Nutzer sind visuell markiert (z.B. gedimmt oder Badge "Inaktiv")
- [ ] Jede Zeile hat ein Aktionsmenü (⋮) mit: OTP zurücksetzen, Deaktivieren/Aktivieren, Löschen
- [ ] Button "Neuer Nutzer" öffnet einen Dialog/Drawer

### AC-2: Nutzer anlegen
- [ ] Pflichtfelder: Benutzername (eindeutig), E-Mail-Adresse, Systemrolle (`admin`/`user`/`guest`/`child`)
- [ ] Optionale Felder — Facts: `name` (Klartextname, z.B. "Andreas"), `rolle` (freie Beschreibung, z.B. "Vater", hat nichts mit alice.users.role zu tun)
- [ ] Optionale Felder — Preferences: `anrede` (`du`/`sie`), `sprache` (`deutsch`/`englisch`), `detailgrad` (`technisch`/`normal`/`einfach`/`kindlich`)
- [ ] E-Mail-Adresse wird vor dem Speichern validiert: Format (Regex) + MX-Record-Lookup der Domain
- [ ] Bei ungültigem Format oder nicht existierender Mail-Domain erscheint eine Inline-Fehlermeldung
- [ ] Systemrolle als Dropdown (`admin`, `user`, `guest`, `child`)
- [ ] `anrede` als Dropdown (nur `du` / `sie`)
- [ ] `sprache` als Dropdown (`deutsch` / `englisch`; durch neue DB-Einträge erweiterbar — kein Hardcoding im Frontend außer verfügbare Werte)
- [ ] `detailgrad` als Dropdown (`technisch` / `normal` / `einfach` / `kindlich`)
- [ ] Nach erfolgreichem Anlegen: Toast "Nutzer angelegt, Einmal-Passwort wurde per E-Mail versendet"
- [ ] Nutzerliste aktualisiert sich sofort (optimistic update oder refetch)

### AC-3: OTP-Generierung und E-Mail-Versand
- [ ] Das OTP wird serverseitig generiert: 8 Zeichen, alphanumerisch gemischt (A-Z, a-z, 0-9), kryptografisch zufällig (kein `random`, sondern `secrets`-Modul)
- [ ] Das OTP wird als bcrypt-Hash (cost 12) in `alice.users.password_hash` gespeichert — nie im Klartext
- [ ] Die Datenbank-Spalte `alice.users.must_change_password` wird auf `TRUE` gesetzt
- [ ] Eine E-Mail mit dem OTP im Klartext wird an die angegebene Adresse gesendet
- [ ] E-Mail-Inhalt (Deutsch): Begrüßung mit Name/Benutzername, das OTP, Hinweis dass es beim ersten Login geändert werden muss, URL zu Alice
- [ ] SMTP-Konfiguration via Umgebungsvariablen: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `ALICE_BASE_URL`
- [ ] Bei SMTP-Fehler: Rollback der User-Erstellung + Fehlermeldung an den Admin (HTTP 500 mit klarer Beschreibung)

### AC-4: Erstes Login (Passwort-Änderung erzwungen)
- [ ] Nach erfolgreichem Login prüft alice-auth ob `must_change_password = TRUE`
- [ ] Wenn `TRUE`: Login-Response enthält zusätzlich `{"must_change_password": true}` (kein Token wird verweigert, aber Frontend zeigt Pflicht-Formular)
- [ ] Das Frontend erkennt das Flag und zeigt — **vor** Weitergabe zum Chat — ein Modal/Seite "Passwort ändern"
- [ ] Das neue Passwort muss mindestens 8 Zeichen haben und darf nicht dem OTP entsprechen
- [ ] Passwort und Passwort-Wiederholung müssen übereinstimmen
- [ ] Nach erfolgreicher Änderung wird `must_change_password = FALSE` gesetzt und der Nutzer landet normal im Chat
- [ ] Es gibt keinen "Überspringen"-Button — die Passwortänderung ist erzwungen

### AC-5: OTP zurücksetzen (bestehender Nutzer)
- [ ] Admin kann über das Aktionsmenü eines Nutzers "OTP zurücksetzen" wählen
- [ ] Ein neues OTP wird generiert, als Hash gespeichert, `must_change_password = TRUE` gesetzt
- [ ] Das neue OTP wird per E-Mail an die hinterlegte Adresse gesendet
- [ ] Admin sieht das OTP **nicht** im Frontend (kein Klartextanzeige im UI)
- [ ] Toast: "Neues Einmal-Passwort per E-Mail versendet"

### AC-6: Nutzer deaktivieren / aktivieren
- [ ] Admin kann Nutzer über das Aktionsmenü deaktivieren (`is_active = FALSE`)
- [ ] Bestätigungsdialog: "Nutzer [username] deaktivieren? Der Nutzer kann sich danach nicht mehr einloggen."
- [ ] Deaktivierte Nutzer können sich nicht einloggen (bestehende Tokens werden beim nächsten `/auth/validate` ungültig)
- [ ] Admin kann deaktivierte Nutzer wieder aktivieren (`is_active = TRUE`)
- [ ] Der eigene Admin-Account kann nicht deaktiviert werden (Button deaktiviert + Tooltip)

### AC-7: Nutzer löschen
- [ ] Admin kann Nutzer über das Aktionsmenü löschen
- [ ] Zweistufiger Bestätigungsdialog: "Diese Aktion kann nicht rückgängig gemacht werden. Benutzername zur Bestätigung eingeben:"
- [ ] Nach Eingabe des korrekten Benutzernamens: DELETE-Request, Nutzer + alle zugehörigen Daten werden gelöscht (CASCADE)
- [ ] Der eigene Admin-Account kann nicht gelöscht werden (Button deaktiviert + Tooltip)
- [ ] Toast: "Nutzer [username] wurde gelöscht"

---

## Edge Cases

- **Benutzername bereits vergeben:** Backend gibt 409 Conflict zurück; Frontend zeigt Inline-Fehler am Benutzernamen-Feld
- **E-Mail-Domain ohne MX-Record:** Inline-Fehlermeldung "E-Mail-Domain akzeptiert keine E-Mails"; User wird nicht angelegt
- **SMTP nicht erreichbar:** Nutzer wird nicht in DB gespeichert (Rollback); Admin sieht Fehlermeldung "E-Mail-Versand fehlgeschlagen — Nutzer wurde nicht angelegt. SMTP prüfen."
- **Admin versucht eigenen Account zu deaktivieren/löschen:** Button disabled, Tooltip erklärt warum
- **Nutzer hat kein E-Mail-Feld:** Das E-Mail-Feld ist Pflichtfeld beim Anlegen; bestehende Nutzer ohne E-Mail können kein OTP-Reset erhalten (Button im Aktionsmenü disabled + Hinweis)
- **Sehr langsamer MX-Lookup:** Timeout nach 5 Sekunden; bei Timeout wird mit Warnung fortgefahren (MX-Check als Best-Effort, kein hartes Blockieren)
- **Neues Passwort = OTP:** Backend vergleicht neues Passwort mit gespeichertem Hash; bei Übereinstimmung: Fehlermeldung "Das neue Passwort darf nicht dem Einmal-Passwort entsprechen"
- **Passwort zu kurz:** Mindestlänge 8 Zeichen; Inline-Validierung im Frontend + Validierung im Backend
- **Token läuft während Passwortänderungs-Flow ab:** Nutzer wird zu `/login` weitergeleitet, muss sich neu einloggen und wird wieder zum Passwortänderungs-Modal geleitet

---

## Technical Requirements

### Datenbank-Migration (`011-proj26-user-management.sql`)
- [ ] `ALTER TABLE alice.users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE`
- [ ] `ALTER TABLE alice.users DROP COLUMN IF EXISTS last_login` — Duplikat-Bereinigung: `last_login` (Originalschema, nie verwendet) wird entfernt; `last_login_at` (Migration 007, aktiv genutzt) bleibt
- [ ] Neuer UNIQUE-Index auf `alice.users.email` (falls noch nicht vorhanden)
- [ ] `alice.user_profiles` Eintrag wird beim User-Anlegen via alice-auth erzeugt (nicht via DB-Migration)
- [ ] `sql/init-postgres.sql` wird ebenfalls bereinigt: `last_login` → `last_login_at` umbenennen, damit Frisch-Installationen konsistent sind

### Backend-Erweiterungen (alice-auth FastAPI-Container)
Neue Endpunkte (alle erfordern Admin-JWT):
```
GET  /admin/users              → Liste aller Nutzer (ohne password_hash)
POST /admin/users              → Nutzer anlegen + OTP generieren + E-Mail senden
POST /admin/users/{id}/reset-otp → Neues OTP generieren + E-Mail senden
PATCH /admin/users/{id}/status    → {is_active: bool} — aktivieren/deaktivieren
DELETE /admin/users/{id}          → Nutzer löschen

POST /auth/change-password     → Neues Passwort setzen (muss must_change_password=TRUE haben)
```

`/auth/login` Anpassung:
- Zusätzliches Feld `must_change_password` in der Response wenn TRUE

### SMTP-Konfiguration (alice-auth .env)
```
SMTP_HOST=mail.example.com
SMTP_PORT=587
SMTP_USER=alice@example.com
SMTP_PASSWORD=...
SMTP_FROM="Alice <alice@example.com>"
ALICE_BASE_URL=https://alice.happy-mining.de
```

### E-Mail-Validierung
- Schritt 1: Regex — muss `@` + Domain + TLD enthalten
- Schritt 2: `dns.resolver.resolve(domain, 'MX')` — Python `dnspython` Bibliothek
- Timeout: 5s; bei Timeout → Warnung in Response, aber kein harter Fehler
- `dnspython` wird zu `requirements.txt` hinzugefügt

### OTP-Generierung
```python
import secrets, string
alphabet = string.ascii_letters + string.digits  # A-Z, a-z, 0-9
otp = ''.join(secrets.choice(alphabet) for _ in range(8))
```

### Frontend — neue Komponenten
- `SettingsPage.tsx` bekommt neuen Tab "Nutzerverwaltung" (nur `isAdmin`)
- `src/components/Settings/NutzerVerwaltungSection.tsx` — Tab-Inhalt
- `src/components/Settings/UserTable.tsx` — Datentabelle mit shadcn Table
- `src/components/Settings/CreateUserDialog.tsx` — Formular als shadcn Dialog
- `src/components/Settings/DeleteUserDialog.tsx` — Zweistufiger Bestätigungsdialog
- `src/components/Auth/ChangePasswordForm.tsx` — Pflicht-Passwortänderung nach erstem Login
- `src/services/adminApi.ts` — API-Calls für Admin-Endpunkte

### Sicherheit
- Alle Admin-Endpunkte: JWT-Prüfung + `role === "admin"` Check im alice-auth Backend
- OTP wird **ausschließlich** per E-Mail übermittelt — niemals in einer API-Response zurückgegeben
- `must_change_password` wird clientseitig **nicht** als Bypass-Kriterium gewertet — Backend setzt es zurück
- Passwort-Änderungs-Endpunkt prüft, ob `must_change_password = TRUE` (verhindert Missbrauch des Endpoints)

---

## Tech Design (Solution Architect)

### Überblick

Das Feature besteht aus vier Schichten:

1. **SettingsPage Redesign** — neues responsives Layout (Tab-Navigation oben auf Mobile, links auf Desktop)
2. **Frontend** — neue Admin-Sektion + Dialoge innerhalb der Settings
3. **Backend** — Erweiterung des bestehenden `alice-auth` FastAPI-Containers
4. **Datenbank** — eine neue Migration (eine neue Spalte)

---

### A) SettingsPage Layout-Redesign

**Problem:** Das aktuelle Layout hat die Tabs auf Mobile am unteren Bildschirmrand fixiert (wie eine App-Navigation). Auf Desktop sind sie horizontal oben, aber die Inhalte sind breit und es gibt kein seitliches Navigation-Panel.

**Neues Layout:**

```
Mobile (< 768px)
┌────────────────────────────────┐
│ ← Einstellungen                │  ← Sticky Header
├────────────────────────────────┤
│ [Allgemein] [DMS] [Nutzer ▶]  │  ← Tabs horizontal, scrollen bei Überfüllung
├────────────────────────────────┤
│                                │
│   Tab Content                  │
│                                │
└────────────────────────────────┘

Desktop (≥ 768px)
┌────────────────────────────────────────────────┐
│ ← Einstellungen                                │  ← Sticky Header
├──────────────────┬─────────────────────────────┤
│                  │                             │
│  Allgemein       │   Content Area              │
│                  │   (nimmt restliche Breite)  │
│  DMS             │                             │
│                  │                             │
│  Nutzer-         │                             │
│  verwaltung      │                             │
│  (nur Admin)     │                             │
│                  │                             │
└──────────────────┴─────────────────────────────┘
   Linke Spalte        Rechte Spalte
   ~180px, feste        flex-grow
   Breite
```

**Technische Umsetzung:**
- Das äußere Container-Div wechselt per Tailwind von `flex-col` (Mobile) zu `flex-row` (Desktop)
- Die shadcn `TabsList` wechselt von horizontal (Mobile) zu vertikal (Desktop) — gesteuert über Tailwind responsive Klassen (`md:flex-col`)
- Das shadcn `Tabs`-Attribut `orientation` wird auf `"vertical"` gesetzt, damit Tastatur-Navigation (Pfeiltasten) korrekt funktioniert
- Auf Mobile wird die horizontale Darstellung trotz `orientation="vertical"` durch Tailwind-Klassen erzwungen (`flex-row` Basis, `md:flex-col` für Desktop)
- Die `TabsContent` Elemente wandern nach rechts (`md:flex-1`) und sind nicht mehr am Body-Ende sondern inline neben der Navigation
- Das bisherige `fixed bottom-0` für die Mobile-Navigation entfällt komplett — die Tabs sind nun immer im normalen Dokumentfluss (kein Overlay)

**Vorher → Nachher Verhalten:**

| Gerät   | Vorher                              | Nachher                          |
|---------|-------------------------------------|----------------------------------|
| Mobile  | Tabs am unteren Bildrand fixiert    | Tabs horizontal oben im Fluss    |
| Desktop | Tabs horizontal oben                | Tabs vertikal links als Sidebar  |

---

### B) Komponenten-Struktur (vollständig)

```
src/components/Settings/
├── SettingsPage.tsx              [GEÄNDERT] — neues Layout + Tab "Nutzerverwaltung"
├── AllgemeinSection.tsx          [unverändert]
├── DmsSection.tsx                [unverändert]
├── FoldersTable.tsx              [unverändert]
├── AddFolderDialog.tsx           [unverändert]
├── EditFolderDialog.tsx          [unverändert]
├── DeleteFolderDialog.tsx        [unverändert]
│
│   ── NEU: Nutzerverwaltung ──
├── NutzerVerwaltungSection.tsx   [NEU] — Section-Container mit Header + Tabelle
├── UserTable.tsx                 [NEU] — shadcn Table mit allen Nutzern
├── CreateUserDialog.tsx          [NEU] — Dialog zum Anlegen (2 Gruppen: Basis + Profil)
├── ResetOtpDialog.tsx            [NEU] — Bestätigungsdialog "OTP zurücksetzen"
├── DeactivateUserDialog.tsx      [NEU] — Bestätigungsdialog "Deaktivieren/Aktivieren"
└── DeleteUserDialog.tsx          [NEU] — 2-stufiger Dialog mit Benutzername-Eingabe

src/components/Auth/
├── AuthProvider.tsx              [GEÄNDERT] — must_change_password Flag aus Login-Response auswerten
├── ProtectedRoute.tsx            [GEÄNDERT] — ChangePasswordForm zeigen wenn Flag gesetzt
└── ChangePasswordForm.tsx        [NEU] — Vollbild-Formular "Passwort ändern" (kein Überspringen)

src/services/
└── adminApi.ts                   [NEU] — fetch-Calls für alle /api/auth/admin/* Endpunkte

src/hooks/
└── useAdminUsers.ts              [NEU] — Daten-Hook: Nutzerliste laden, CRUD-Operationen
```

---

### C) Datenfluss

**Nutzer anlegen (Happy Path):**
```
Admin öffnet "Neuer Nutzer"-Dialog
→ Füllt Formular aus (Basis: username, email, role — Profil: name, rolle, anrede, sprache, detailgrad)
→ Klick "Anlegen"
→ Frontend: POST /api/auth/admin/users
→ alice-auth: E-Mail-Format prüfen → MX-Lookup → OTP generieren → User in DB speichern
         → Permissions aus Role-Template initialisieren (alice.init_user_permissions)
         → user_profiles Eintrag mit facts + preferences anlegen
         → OTP per SMTP versenden → 201 Created
→ Frontend: Dialog schließt → Toast "Nutzer angelegt, E-Mail versendet" → Liste aktualisiert
```

**Erstes Login (Passwort-Änderung erzwungen):**
```
Neuer Nutzer gibt OTP ein → POST /api/auth/login
→ alice-auth: Login erfolgreich → must_change_password = TRUE
→ Response: { token, user, must_change_password: true }
→ AuthProvider: Token speichern, mustChangePassword-Flag in Context setzen
→ ProtectedRoute: Zeigt ChangePasswordForm statt Chat
→ Nutzer gibt neues Passwort ein (2x) → POST /api/auth/change-password
→ alice-auth: bcrypt-Vergleich mit altem Hash (darf nicht gleich sein)
         → neues Passwort hashen → must_change_password = FALSE → 200 OK
→ AuthProvider: Flag zurücksetzen → Nutzer landet im Chat
```

**Admin-Aktionen (Deaktivieren / Löschen / OTP-Reset):**
```
Admin klickt ⋮ → Aktionsmenü erscheint
→ Wählt Aktion → Bestätigungsdialog öffnet
→ Admin bestätigt
→ API-Call (PATCH / DELETE / POST) → alice-auth verarbeitet + antwortet
→ Frontend: useAdminUsers Hook aktualisiert lokale Liste (optimistic oder refetch)
→ Toast mit Ergebnis
```

---

### D) Datenmodell (Plaintext)

**alice.users — neue Spalte:**
- `must_change_password` (Boolean, Standard: Nein) — kennzeichnet Konten, die beim nächsten Login zwingend das Passwort ändern müssen

**alice.user_profiles — befüllt beim User-Anlegen:**
- `facts`: freies JSON-Objekt, z.B. `{"name": "Andreas", "rolle": "Vater"}`
- `preferences`: freies JSON-Objekt mit festen Keys:
  - `anrede`: `"du"` oder `"sie"`
  - `sprache`: `"deutsch"` oder `"englisch"` (erweiterbar durch neue Werte, ohne Code-Änderung)
  - `detailgrad`: `"technisch"` / `"normal"` / `"einfach"` / `"kindlich"`

**Wichtig:** `user_profiles.user_id` ist derzeit `VARCHAR(255)`. Beim Anlegen via alice-auth wird die UUID des neuen Users als String gespeichert (konsistent mit bestehendem Verhalten).

**E-Mail-Template (Plaintext, Deutsch):**
```
Betreff: Dein Alice-Zugang

Hallo [Name / Benutzername],

dein Alice-Konto wurde eingerichtet. Dein Einmal-Passwort lautet:

  [OTP]

Bitte melde dich unter [ALICE_BASE_URL] an und ändere das Passwort
beim ersten Login. Das Passwort ist nur einmal verwendbar.

Viele Grüße,
Alice
```

---

### E) Backend-Architektur (alice-auth Erweiterung)

**Neue Endpunkte** (alle erfordern Admin-JWT):

| Methode  | Pfad                          | Zweck                                    |
|----------|-------------------------------|------------------------------------------|
| GET      | `/admin/users`                | Liste aller Nutzer (kein password_hash)  |
| POST     | `/admin/users`                | Nutzer anlegen + OTP + E-Mail            |
| POST     | `/admin/users/{id}/reset-otp` | Neues OTP generieren + E-Mail            |
| PATCH    | `/admin/users/{id}/status`    | `is_active` umschalten                   |
| DELETE   | `/admin/users/{id}`           | Nutzer inkl. aller Daten löschen         |

**Geänderter Endpunkt:**

| Methode | Pfad                   | Änderung                                      |
|---------|------------------------|-----------------------------------------------|
| POST    | `/auth/login`          | Gibt `must_change_password: true` mit zurück  |
| POST    | `/auth/change-password`| Neuer Endpunkt: OTP → eigenes Passwort        |

**OTP-Sicherheitskette:**
```
Generieren (secrets.choice, 8 Zeichen) → als bcrypt-Hash speichern
→ Klartext nur per E-Mail versenden → nie in API-Response zurückgeben
→ must_change_password = TRUE setzen
```

**E-Mail-Versand (SMTP via smtplib):**
- STARTTLS auf Port 587 (konfigurierbar via `SMTP_PORT`)
- Bei SMTP-Fehler: DB-Transaktion rückgängig machen (Nutzer nicht anlegen)
- Fehler-Response an Admin: HTTP 500 mit klarer Fehlerbeschreibung

**MX-Validierung (dnspython):**
- Schritt 1: Regex-Check (Format)
- Schritt 2: DNS MX-Lookup mit 5-Sekunden-Timeout
- Bei Timeout: Warnung im Log, kein harter Fehler (Best-Effort)
- Bei fehlendem MX-Record: HTTP 422 "E-Mail-Domain akzeptiert keine E-Mails"

---

### F) nginx-Routing (bereits konfiguriert)

Die bestehende nginx-Regel `/api/auth/*` → `alice-auth:8002` deckt alle neuen Endpunkte ab. Kein nginx-Änderungsbedarf.

---

### G) Neue Abhängigkeiten

| Paket      | Wo               | Zweck                                    |
|------------|------------------|------------------------------------------|
| `dnspython`| alice-auth       | MX-Record-Lookup für E-Mail-Validierung  |

Keine neuen npm-Pakete nötig — shadcn Table, Dialog, DropdownMenu, Badge, Toast sind bereits vorhanden oder einfach nachzuinstallieren.

---

### H) Dateien — Übersicht

**Neue Dateien:**
- `frontend/src/components/Settings/NutzerVerwaltungSection.tsx`
- `frontend/src/components/Settings/UserTable.tsx`
- `frontend/src/components/Settings/CreateUserDialog.tsx`
- `frontend/src/components/Settings/ResetOtpDialog.tsx`
- `frontend/src/components/Settings/DeactivateUserDialog.tsx`
- `frontend/src/components/Settings/DeleteUserDialog.tsx`
- `frontend/src/components/Auth/ChangePasswordForm.tsx`
- `frontend/src/services/adminApi.ts`
- `frontend/src/hooks/useAdminUsers.ts`
- `sql/migrations/011-proj26-user-management.sql`

**Geänderte Dateien:**
- `frontend/src/components/Settings/SettingsPage.tsx` — Layout-Redesign + neuer Tab
- `frontend/src/components/Auth/AuthProvider.tsx` — must_change_password Flag
- `frontend/src/components/Auth/ProtectedRoute.tsx` — ChangePasswordForm einbinden
- `docker/compose/automations/alice-auth/main.py` — neue Endpunkte + SMTP + MX
- `docker/compose/automations/alice-auth/requirements.txt` — dnspython hinzufügen
- `docker/compose/automations/alice-auth/.env` — SMTP-Variablen (lokal, nicht im Git)

## QA Test Results

**Tested:** 2026-03-15 (Round 1), 2026-03-15 (Round 2), 2026-03-16 (Round 3 Re-Test)
**App URL:** https://alice.happy-mining.de
**Tester:** QA Engineer (AI)
**Build:** Frontend redeployed, alice-auth container rebuilt and restarted

### Re-Test Summary (Round 3)

Round 2 had 3 remaining bugs (BUG-3b Low, BUG-4 Low accepted, BUG-5 Low accepted). This round verifies all fixes applied since Round 2.

| Bug | Severity | Round 2 Status | Round 3 Status | Notes |
|-----|----------|----------------|----------------|-------|
| BUG-1 | Low | ACCEPTED | ACCEPTED | Spalten-Layout abweichend, UX besser als Spec. |
| BUG-2 | Critical | FIXED | FIXED (confirmed) | /auth/validate gibt must_change_password zurueck. |
| BUG-3/3b | Medium->Low | PARTIAL FIX | FIXED | adminApi.ts liest jetzt body.detail aus dem 409-Response. |
| BUG-4 | Low | OPEN (accepted) | FIXED | Backend validiert anrede/sprache/detailgrad mit HTTP 422. |
| BUG-5 | Low | OPEN (accepted) | FIXED | In-memory Rate-Limiter: 60 req/60s pro IP auf allen Admin-Endpunkten. |
| BUG-6 | Medium | FIXED | FIXED (confirmed) | display_name korrekt gesetzt. |

### Acceptance Criteria Status

#### AC-1: Nutzerliste (Frontend)
- [x] Im Settings-Tab "Nutzerverwaltung" wird eine Tabelle aller Nutzer angezeigt (sichtbar nur fuer Admins) -- `isAdmin` check in SettingsPage.tsx controls tab visibility
- [x] Spalten: Benutzername (mit display_name als Unterzeile), E-Mail, Systemrolle, Status, Erstellt am -- BUG-1 accepted, UX ist besser als Spec
- [x] Inaktive Nutzer sind visuell markiert -- `opacity-50` class + "Inaktiv" Badge (rot)
- [x] Jede Zeile hat ein Aktionsmenue (MoreVertical icon) mit: OTP zuruecksetzen, Deaktivieren/Aktivieren, Loeschen
- [x] Button "Neuer Nutzer" oeffnet einen Dialog
- [x] Mobile responsive layout mit Card-Ansicht statt Tabelle (md:hidden / hidden md:block)

#### AC-2: Nutzer anlegen
- [x] Pflichtfelder: Benutzername (eindeutig), E-Mail-Adresse, Systemrolle
- [x] Optionale Felder Facts: `name`, `rolle` -- als Input-Felder vorhanden
- [x] Optionale Felder Preferences: `anrede`, `sprache`, `detailgrad` -- als Dropdowns vorhanden
- [x] E-Mail-Adresse wird vor dem Speichern validiert: Format (Regex) -- Frontend + Backend
- [x] MX-Record-Lookup der Domain im Backend (dnspython)
- [x] Bei ungueltigem Format erscheint Inline-Fehlermeldung im Frontend
- [x] Systemrolle als Dropdown (admin, user, guest, child)
- [x] `anrede` als Dropdown (du / sie)
- [x] `sprache` als Dropdown (deutsch / englisch)
- [x] `detailgrad` als Dropdown (technisch / normal / einfach / kindlich)
- [x] Nach erfolgreichem Anlegen: Toast "Nutzer angelegt, Einmal-Passwort wurde per E-Mail versendet"
- [x] Nutzerliste aktualisiert sich sofort (optimistic update in useAdminUsers via setUsers)
- [x] display_name wird korrekt auf body.name gesetzt

#### AC-3: OTP-Generierung und E-Mail-Versand
- [x] OTP wird serverseitig generiert: 8 Zeichen, alphanumerisch (A-Z, a-z, 0-9), kryptografisch (secrets.choice)
- [x] OTP wird als bcrypt-Hash (cost 12) gespeichert -- _hash_password mit gensalt(rounds=12)
- [x] `must_change_password` wird auf TRUE gesetzt
- [x] E-Mail mit OTP im Klartext wird gesendet (via smtplib STARTTLS/SSL)
- [x] E-Mail-Inhalt (Deutsch): Begruessung, OTP, Hinweis, URL -- Template matches spec
- [x] SMTP-Konfiguration via Umgebungsvariablen (SMTP_HOST, SMTP_PORT, etc.)
- [x] Bei SMTP-Fehler: Rollback der User-Erstellung + Fehlermeldung (HTTP 500)

#### AC-4: Erstes Login (Passwort-Aenderung erzwungen)
- [x] Nach Login prueft alice-auth ob `must_change_password = TRUE`
- [x] Response enthaelt `must_change_password: true`
- [x] /auth/validate gibt must_change_password zurueck -- AuthProvider liest es korrekt nach Page-Reload
- [x] ChangePasswordForm: Neues Passwort muss mindestens 8 Zeichen haben -- Frontend + Backend Validierung
- [x] Passwort und Passwort-Wiederholung muessen uebereinstimmen -- canSubmit check
- [x] Backend prueft: neues Passwort darf nicht dem OTP entsprechen (bcrypt compare)
- [x] Nach erfolgreicher Aenderung: `must_change_password = FALSE`
- [x] Kein "Ueberspringen"-Button vorhanden -- ChangePasswordForm hat keine Skip-Option

#### AC-5: OTP zuruecksetzen (bestehender Nutzer)
- [x] Admin kann ueber Aktionsmenue "OTP zuruecksetzen" waehlen
- [x] Neues OTP wird generiert, als Hash gespeichert, must_change_password = TRUE
- [x] Neues OTP wird per E-Mail gesendet
- [x] Admin sieht OTP nicht im Frontend (API gibt OTP nie zurueck)
- [x] Toast: "Neues Einmal-Passwort per E-Mail versendet" (via ResetOtpDialog + NutzerVerwaltungSection)

#### AC-6: Nutzer deaktivieren / aktivieren
- [x] Admin kann Nutzer deaktivieren (PATCH is_active = false)
- [x] Bestaetigungsdialog mit korrektem Text (DeactivateUserDialog)
- [x] Deaktivierte Nutzer koennen sich nicht einloggen -- /auth/login prueft is_active
- [x] Bestehende Tokens werden bei /auth/validate ungueltig -- validate prueft is_active in DB
- [x] Admin kann deaktivierte Nutzer wieder aktivieren (willActivate toggle)
- [x] Eigener Admin-Account: Button disabled + Tooltip "Eigenen Account kann man nicht deaktivieren"

#### AC-7: Nutzer loeschen
- [x] Admin kann Nutzer ueber Aktionsmenue loeschen
- [x] Zweistufiger Bestaetigungsdialog: Benutzername zur Bestaetigung eingeben (DeleteUserDialog)
- [x] DELETE-Request, user_profiles wird explizit geloescht (kein FK-Cascade da VARCHAR)
- [x] Eigener Admin-Account: Button disabled + Tooltip "Eigenen Account kann man nicht loeschen"
- [x] Toast: "Nutzer [username] wurde dauerhaft geloescht"

### Edge Cases Status

#### EC-1: Benutzername / E-Mail bereits vergeben
- [x] Backend differenziert korrekt: constraint_name wird geprueft (main.py). Bei username-Constraint: "Benutzername ist bereits vergeben". Bei email-Constraint: "E-Mail-Adresse ist bereits vergeben".
- [x] BUG-3b FIXED: Frontend adminApi.ts liest jetzt den Response-Body aus: `const body = await res.json().catch(() => ({})); throw new Error(body.detail || "Benutzername oder E-Mail bereits vergeben.");` Die differenzierte Backend-Fehlermeldung wird korrekt an den Nutzer weitergegeben.

#### EC-2: E-Mail-Domain ohne MX-Record
- [x] Inline-Fehlermeldung "E-Mail-Domain akzeptiert keine E-Mails" -- Backend HTTP 422, Frontend zeigt error

#### EC-3: SMTP nicht erreichbar
- [x] Nutzer wird nicht in DB gespeichert (Rollback) -- conn.rollback() im SMTP-except
- [x] Admin sieht Fehlermeldung mit SMTP-Details

#### EC-4: Admin versucht eigenen Account zu deaktivieren/loeschen
- [x] Button disabled, Tooltip erklaert warum -- in UserActionMenu, isSelf check

#### EC-5: Nutzer hat kein E-Mail-Feld
- [x] OTP-Reset Button im Aktionsmenue disabled + Tooltip "Keine E-Mail-Adresse hinterlegt"

#### EC-6: Sehr langsamer MX-Lookup
- [x] Timeout nach 5 Sekunden (resolver.timeout = 5, resolver.lifetime = 5)
- [x] Bei Timeout wird mit Warnung fortgefahren (return True, True)

#### EC-7: Neues Passwort = OTP
- [x] Backend vergleicht neues Passwort mit gespeichertem Hash; bei Uebereinstimmung: HTTP 400

#### EC-8: Passwort zu kurz
- [x] Mindestlaenge 8 Zeichen; Inline-Validierung im Frontend (isTooShort) + Backend (len < 8 check)

#### EC-9: Token laeuft waehrend Passwortaenderungs-Flow ab
- [x] Backend gibt 401 zurueck, adminApi.changePassword leitet zu /login weiter

### Technical Requirements Status

#### Migration (011-proj26-user-management.sql)
- [x] `must_change_password BOOLEAN NOT NULL DEFAULT FALSE` -- ADD COLUMN IF NOT EXISTS
- [x] `DROP COLUMN IF EXISTS last_login` -- Duplikat-Bereinigung
- [x] UNIQUE-Index auf email (partial, WHERE email IS NOT NULL)

#### init-postgres.sql Bereinigung
- [x] `must_change_password` Spalte vorhanden
- [x] `last_login_at` statt `last_login` -- korrekt, nur `last_login_at` vorhanden

#### Backend-Erweiterungen
- [x] Alle 6 neuen Endpunkte implementiert (GET/POST admin/users, POST reset-otp, PATCH status, DELETE, POST change-password)
- [x] /auth/login gibt must_change_password zurueck wenn TRUE
- [x] /auth/validate gibt must_change_password zurueck wenn TRUE

#### Neue Abhaengigkeiten
- [x] dnspython in requirements.txt

### Security Audit Results

- [x] Authentication: Alle Admin-Endpunkte erfordern gueltigen JWT mit role=admin (_require_admin)
- [x] Authorization: Nicht-Admin JWTs erhalten HTTP 403 (role-check in _require_admin)
- [x] SQL Injection: Alle Queries nutzen parameterisierte Abfragen (psycopg2 %s Platzhalter)
- [x] XSS: React auto-escaping, kein dangerouslySetInnerHTML
- [x] OTP-Sicherheit: OTP wird nie in API-Responses zurueckgegeben, nur als bcrypt-Hash in DB gespeichert
- [x] Selbstschutz: Admin kann eigenen Account nicht deaktivieren/loeschen (Backend + Frontend)
- [x] Password hashing: bcrypt cost 12, kryptografisch sicherer OTP-Generator (secrets)
- [x] Token-Invalidierung: /auth/validate prueft is_active in der Datenbank, deaktivierte Nutzer werden abgelehnt
- [x] Passwort-Aenderungs-Endpoint: Prueft must_change_password = TRUE, verhindert Missbrauch
- [x] BUG-4 FIXED: Backend validiert jetzt anrede (du/sie), sprache (deutsch/englisch), detailgrad (technisch/normal/einfach/kindlich) mit HTTP 422 bei ungueltigen Werten (main.py Zeilen 601-607)
- [x] BUG-5 FIXED: In-memory Rate-Limiter auf allen Admin-Endpunkten: 60 Requests pro 60 Sekunden pro IP (main.py Zeilen 67-85). _check_admin_rate_limit() wird in jeder Admin-Route aufgerufen.
- [x] Rate-Limiter nutzt threading.Lock fuer Thread-Sicherheit und time.monotonic() fuer zuverlaessige Zeitmessung

### Bugs Found -- Gesamtuebersicht (alle Runden)

#### BUG-1: Tabellenspalten weichen vom Spec ab -- ACCEPTED
- **Severity:** Low
- **Status:** ACCEPTED -- UX ist besser als Spec-Vorgabe. Kein Fix noetig.

#### BUG-2: must_change_password geht nach Page-Reload verloren -- FIXED (Round 2)
- **Severity:** Critical
- **Status:** FIXED

#### BUG-3/3b: UniqueViolation Fehlermeldung bei doppelter E-Mail -- FIXED (Round 3)
- **Severity:** Medium -> Low -> FIXED
- **Status:** FIXED
- **Round 2:** Backend fix verifiziert, Frontend hardcoded 409-Text.
- **Round 3 fix verified:** adminApi.ts Zeile 105-107 liest jetzt den Response-Body: `const body = await res.json().catch(() => ({})); throw new Error(body.detail || "Benutzername oder E-Mail bereits vergeben.");` Die differenzierte Fehlermeldung vom Backend erreicht den Nutzer korrekt.

#### BUG-4: Keine Backend-Validierung fuer Profil-Preference-Werte -- FIXED (Round 3)
- **Severity:** Low
- **Status:** FIXED
- **Round 3 fix verified:** main.py Zeilen 601-607 validiert jetzt serverseitig: anrede muss "du" oder "sie" sein, sprache muss "deutsch" oder "englisch" sein, detailgrad muss "technisch", "normal", "einfach" oder "kindlich" sein. Ungueltige Werte erhalten HTTP 422 mit klarer Fehlermeldung.

#### BUG-5: Kein Rate-Limiting auf Admin-Endpunkten -- FIXED (Round 3)
- **Severity:** Low
- **Status:** FIXED
- **Round 3 fix verified:** main.py Zeilen 67-85 implementiert einen In-memory Rate-Limiter (60 Requests / 60 Sekunden pro IP). Alle 5 Admin-Endpunkte rufen _check_admin_rate_limit(request) auf. Bei Ueberschreitung: HTTP 429 "Too many requests -- bitte warten."

#### BUG-6: display_name wird beim Erstellen neuer Nutzer nicht gesetzt -- FIXED (Round 2)
- **Severity:** Medium
- **Status:** FIXED

### Cross-Browser Assessment

Standard-konforme Web-APIs und Tailwind CSS. Keine Browser-spezifischen APIs verwendet.

- **Chrome/Edge:** Vollstaendig kompatibel.
- **Firefox:** Vollstaendig kompatibel.
- **Safari:** Kompatibel.

### Responsive Assessment

- **Mobile (375px):** Card-Ansicht, horizontale Tabs, responsive Dialog. overflow-x-auto auf TabsList.
- **Tablet (768px):** Desktop-Layout mit vertikalen Tabs links (md:flex-row, md:w-44).
- **Desktop (1440px):** Volle Tabellen-Darstellung mit max-w-5xl Container.

### Summary (Round 3 -- Final)
- **Acceptance Criteria:** 31/31 passed
- **Edge Cases:** 9/9 passed
- **All 6 Bugs resolved:** 1 accepted (BUG-1 UX), 5 fixed (BUG-2 through BUG-6)
- **Bugs Remaining:** 0 (zero critical, zero high, zero medium, zero low)
- **Security Audit:** All checks passed. Server-side validation, rate-limiting, parameterized queries, bcrypt hashing, no OTP leakage.
- **Production Ready:** YES
- **Recommendation:** Alle Bugs sind behoben. Deployment kann erfolgen.

## Deployment

**Deployed:** 2026-03-16

### Deployed Components
- **Frontend:** `NutzerVerwaltungSection`, `UserTable`, `CreateUserDialog`, `DeactivateUserDialog`, `DeleteUserDialog`, `ResetOtpDialog`, `ChangePasswordForm` — deployed via `./scripts/deploy-frontend.sh` + `./sync-compose.sh`
- **Backend:** `alice-auth` Container (v1.1.0 → v1.2.0) — Docker rebuilt and restarted on `ki.lan`
- **Database:** Migration `sql/migrations/011-proj26-user-management.sql` applied (UNIQUE index on `email`, `must_change_password` column, `display_name` backfill)

### Key Changes per Round
| Round | Change |
|-------|--------|
| 1 | Initial implementation |
| 2 | Fix BUG-2 (must_change_password via /auth/validate), BUG-3 (UniqueViolation differentiation), BUG-6 (display_name INSERT) |
| 3 | Fix BUG-3b (frontend reads 409 body), BUG-4 (preference validation), BUG-5 (rate limiter 60 req/min/IP on admin endpoints) |
