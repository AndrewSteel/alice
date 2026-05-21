# PROJ-27: Nutzerprofil selbst bearbeiten

## Status: Deployed
**Created:** 2026-03-16
**Last Updated:** 2026-03-16

## Dependencies
- Requires: PROJ-7 (JWT Auth) — alice-auth Container, alice.users Tabelle
- Requires: PROJ-26 (Admin Nutzerverwaltung) — alice.user_profiles Tabelle, MX-Validierung, Settings-Layout mit vertikalen Tabs (Desktop) / horizontalen Tabs (Mobile)

---

## Übersicht

Als eingeloggter Nutzer (alle Rollen: admin, user, guest, child) kann ich unter **Einstellungen → Mein Profil** meine eigenen Nutzerdaten bearbeiten. Kein Admin-Eingriff nötig für alltägliche Profilpflege.

**Editierbare Felder:**
- Passwort (aktuelles PW bestätigen + neues PW 2x)
- E-Mail-Adresse (Format- + MX-Validierung wie in PROJ-26)
- `facts.name` (Klartextname)
- `facts.interessen` (Tags, frei wählbar — hinzufügen + löschen)
- `preferences.anrede` (Dropdown: du / sie)
- `preferences.sprache` (Dropdown: deutsch / englisch)

**Nur anzeigen (nicht editierbar):**
- `facts.rolle` (wird vom Admin beim Anlegen gesetzt)
- `preferences.detailgrad` (wird vom Admin beim Anlegen gesetzt)

**Scope:** Jeder eingeloggte Nutzer darf nur seine eigenen Daten ändern. Keine Cross-User-Zugriffe.

---

## User Stories

1. **Als Nutzer** möchte ich unter Einstellungen → Mein Profil meinen Anzeigenamen (`facts.name`) ändern können, damit Alice mich korrekt anspricht.
2. **Als Nutzer** möchte ich meine Interessen als Tags pflegen können (hinzufügen und einzeln löschen), damit Alice relevantere Vorschläge machen kann.
3. **Als Nutzer** möchte ich meine bevorzugte Anrede (du/sie) und Sprache (deutsch/englisch) anpassen können, damit Alice in meiner bevorzugten Kommunikationsform antwortet.
4. **Als Nutzer** möchte ich mein Passwort freiwillig ändern können (nicht nur beim ersten Login), indem ich mein aktuelles Passwort bestätige, damit mein Account sicher bleibt.
5. **Als Nutzer** möchte ich meine E-Mail-Adresse aktualisieren können, damit OTPs und Benachrichtigungen die richtige Adresse erreichen.
6. **Als Nutzer** möchte ich meine Systemrolle (`facts.rolle`) und meinen Detailgrad (`preferences.detailgrad`) sehen, auch wenn ich sie nicht ändern kann, um meine Kontoeinstellungen zu verstehen.

---

## Acceptance Criteria

### AC-1: Settings-Tab "Mein Profil"
- [ ] SettingsPage bekommt neuen Tab "Mein Profil" — sichtbar für alle authentifizierten Nutzer (alle Rollen)
- [ ] Tab erscheint als erstes (ganz links auf Desktop, ganz links/oben auf Mobile) — ist der Standard-Tab beim Öffnen der Einstellungen
- [ ] Das Layout folgt dem bestehenden Settings-Pattern aus PROJ-26 (vertikale Tabs Desktop, horizontale Tabs Mobile)

### AC-2: Profil-Übersicht (Lesen)
- [ ] Beim Öffnen des Tabs werden aktuelle Profildaten geladen: `username`, `email`, `facts.*`, `preferences.*`
- [ ] Anzeige von `facts.rolle` und `preferences.detailgrad` als read-only Felder (Label + Wert, kein Input)
- [ ] Hinweis bei read-only Feldern: "Wird vom Admin verwaltet"
- [ ] Wenn ein Feld noch nicht befüllt ist (z.B. `facts.name` = null), wird das Input-Feld leer angezeigt (kein Placeholder-Wert als echter Wert gespeichert)

### AC-3: Profilfelder bearbeiten (Name, Interessen, Anrede, Sprache)
- [ ] `facts.name`: Freitextfeld, max. 100 Zeichen
- [ ] `facts.interessen`: Tag-Input-Komponente — bestehende Tags werden als Chips mit ×-Button angezeigt; neuen Tag per Eingabe + Enter hinzufügen; max. 20 Tags; max. 30 Zeichen pro Tag; Duplikate werden abgelehnt (client-seitig)
- [ ] `preferences.anrede`: Dropdown mit Optionen `du` / `sie`
- [ ] `preferences.sprache`: Dropdown mit Optionen `deutsch` / `englisch`
- [ ] Alle Felder in einem gemeinsamen Formular mit einem "Speichern"-Button für Profildaten
- [ ] Bei erfolgreichem Speichern: Toast "Profil gespeichert"
- [ ] Validierungsfehler werden als Inline-Fehlermeldungen unter dem jeweiligen Feld angezeigt

### AC-4: E-Mail-Adresse ändern
- [ ] E-Mail-Adresse als eigenes Formular mit separatem "Speichern"-Button (getrennt vom Profil-Formular)
- [ ] Vor dem Speichern: Format-Validierung (Regex) + MX-Record-Lookup (gleicher Mechanismus wie PROJ-26)
- [ ] Bei ungültigem Format: Inline-Fehlermeldung "Ungültige E-Mail-Adresse"
- [ ] Bei Domain ohne MX-Record: Inline-Fehlermeldung "E-Mail-Domain akzeptiert keine E-Mails" (HTTP 422)
- [ ] Bei bereits verwendeter E-Mail: Fehlermeldung "E-Mail-Adresse wird bereits verwendet" (HTTP 409)
- [ ] Bei Erfolg: Toast "E-Mail-Adresse geändert"
- [ ] MX-Lookup-Timeout (5s) → Warnung im Log, kein harter Fehler für den Nutzer (Best-Effort wie PROJ-26)

### AC-5: Passwort freiwillig ändern
- [ ] Eigene Sektion "Passwort ändern" mit separatem Formular und eigenem Absenden-Button
- [ ] Drei Felder: Aktuelles Passwort, Neues Passwort, Neues Passwort wiederholen
- [ ] Alle drei Felder als `type="password"` mit Sichtbarkeits-Toggle (Auge-Icon)
- [ ] Client-seitige Validierung: Neues Passwort min. 8 Zeichen; Wiederholung muss übereinstimmen
- [ ] Backend-Validierung: Aktuelles Passwort gegen gespeicherten Hash prüfen (bcrypt.checkpw); neues Passwort muss sich vom aktuellen unterscheiden; min. 8 Zeichen
- [ ] Fehlerfälle:
  - Aktuelles Passwort falsch → HTTP 401 → Inline-Fehler "Aktuelles Passwort ist falsch"
  - Neues PW = aktuelles PW → HTTP 400 → Inline-Fehler "Neues Passwort muss sich vom aktuellen unterscheiden"
  - Zu kurz → HTTP 400 → Inline-Fehler "Passwort muss mindestens 8 Zeichen haben"
- [ ] Bei Erfolg: alle drei Felder leeren + Toast "Passwort geändert"
- [ ] `must_change_password` wird bei dieser Aktion **nicht** geprüft oder verändert (dieser Endpunkt ist für freiwillige Änderungen)

---

## Edge Cases

- **Nutzer hat noch kein Profil-Eintrag** (`user_profiles` Zeile fehlt): Profil-PATCH erstellt den Eintrag (UPSERT), Fehler wird nicht an den Nutzer weitergegeben
- **Tag bereits vorhanden:** Client-seitige Duplikatprüfung (case-insensitive) — neuer Tag wird nicht hinzugefügt, kein Fehler-Toast (silently ignored oder kurze Inline-Meldung)
- **Tag über 30 Zeichen:** Eingabefeld blockiert Eingabe nach 30 Zeichen (maxLength) + Backend-Validierung (HTTP 422)
- **Mehr als 20 Tags:** "+" Button / Enter-Taste ist deaktiviert wenn 20 Tags erreicht; Inline-Hinweis "Maximum erreicht (20 Tags)"
- **Netzwerkfehler beim Speichern:** Toast "Fehler beim Speichern. Bitte erneut versuchen." — Formularinhalte bleiben erhalten
- **Nutzer wechselt Tab ohne zu speichern:** Keine Warnung — ungespeicherte Änderungen gehen verloren (kein Dirty-Check nötig für MVP)
- **Leeres `facts.name`-Feld abspeichern:** Erlaubt — `null` wird gespeichert (Feld bleibt optional)
- **Leere Interessen-Liste:** Erlaubt — `[]` wird gespeichert
- **Gleichzeitige Änderungen (zwei Browser-Tabs):** Letzter Write gewinnt (keine Konfliktbehandlung in MVP)
- **Nutzer mit `must_change_password = TRUE`:** Wird nach dem Passwort-Änderungs-Flow (PROJ-26) zum Chat weitergeleitet; der neue Profil-Tab ist erst danach erreichbar

---

## Technical Requirements

### Neue Backend-Endpunkte (alice-auth)

Alle Endpunkte erfordern einen gültigen JWT (beliebige Rolle). Jeder Nutzer kann nur seine eigenen Daten ändern — die User-ID wird aus dem JWT-Payload entnommen, **nicht** aus dem Request-Body.

```
GET  /auth/profile                → Profildaten des eingeloggten Nutzers lesen
PATCH /auth/profile               → facts.name, facts.interessen, preferences.anrede, preferences.sprache
PATCH /auth/email                 → E-Mail-Adresse ändern (mit Format + MX-Validierung)
POST  /auth/change-password-voluntary → Freiwillige Passwortänderung (altes PW bestätigen)
```

`GET /auth/profile` Response:
```json
{
  "username": "andreas",
  "email": "andreas@example.com",
  "facts": {
    "name": "Andreas",
    "rolle": "Vater",
    "interessen": ["Kochen", "Musik"]
  },
  "preferences": {
    "anrede": "du",
    "sprache": "deutsch",
    "detailgrad": "normal"
  }
}
```

### Datenbank

- Kein neues Schema nötig — `alice.user_profiles.facts` und `alice.user_profiles.preferences` sind bereits JSONB
- `facts.interessen` ist ein neues Schlüssel im bestehenden JSON-Objekt (Array von Strings)
- UPSERT-Strategie für `user_profiles`: `INSERT ... ON CONFLICT (user_id) DO UPDATE`
- E-Mail-Update: `UPDATE alice.users SET email = $1 WHERE id = $2`

### Input-Validierung (Backend)

- `facts.name`: String, max. 100 Zeichen, nullable
- `facts.interessen`: Array of strings, max. 20 Einträge, jeder Eintrag max. 30 Zeichen, keine Duplikate (case-insensitive)
- `preferences.anrede`: enum `["du", "sie"]`
- `preferences.sprache`: enum `["deutsch", "englisch"]`
- E-Mail: Regex + MX-Lookup (dnspython, Timeout 5s) — wiederverwendet aus PROJ-26
- Neues Passwort: min. 8 Zeichen; darf nicht mit aktuellem PW übereinstimmen (bcrypt.checkpw)

### Frontend — neue/geänderte Dateien

```
src/components/Settings/
├── SettingsPage.tsx              [GEÄNDERT] — neuer Tab "Mein Profil" als erster Tab
├── MeinProfilSection.tsx         [NEU] — Haupt-Container (3 Sektionen: Profil, E-Mail, Passwort)
├── ProfilForm.tsx                [NEU] — Formular für Name, Interessen, Anrede, Sprache
├── InteressenTagInput.tsx        [NEU] — Tag-Input-Komponente (Chips + Eingabefeld)
├── EmailForm.tsx                 [NEU] — E-Mail-Formular mit MX-Validierung
└── ChangePasswordForm.tsx        [GEÄNDERT*] — bestehende Komponente aus PROJ-26 um
                                               "Aktuelles Passwort" Feld erweitern;
                                               neuer Endpunkt /auth/change-password-voluntary

src/services/
└── profileApi.ts                 [NEU] — fetch-Calls für /auth/profile, /auth/email,
                                          /auth/change-password-voluntary

src/hooks/
└── useProfile.ts                 [NEU] — Profildaten laden + PATCH-Operationen
```

*`ChangePasswordForm.tsx` aus PROJ-26 ist für den First-Login-Flow gebaut (kein "Aktuelles Passwort"-Feld). Für PROJ-27 wird eine zweite Variante im Settings-Kontext benötigt, die das aktuelle Passwort abfragt und einen anderen Endpunkt nutzt.

### Sicherheit

- User-ID wird ausschließlich aus dem validierten JWT-Payload gelesen — kein User-ID-Parameter im Request akzeptiert
- Alle Endpunkte prüfen JWT-Gültigkeit (bestehender `_require_auth` Decorator)
- Passwort-Verifikation: `bcrypt.checkpw(current_password.encode(), stored_hash)` — Timing-sicherer Vergleich
- E-Mail-Eindeutigkeit: UNIQUE-Constraint auf `alice.users.email` (bereits aus PROJ-26 Migration 011)

---

## Tech Design (Solution Architect)

### Überblick

Das Feature besteht aus zwei Schichten:

1. **Frontend** — neuer Settings-Tab "Mein Profil" mit 3 isolierten Formularen
2. **Backend** — 4 neue Endpunkte im `alice-auth` FastAPI-Container (kein DB-Schema-Change)

---

### A) Komponenten-Struktur

```
SettingsPage.tsx  [GEÄNDERT]
└── Tab "Mein Profil" (defaultValue → neu als erster Tab, alle Rollen)
    └── MeinProfilSection.tsx  [NEU] — Haupt-Container, lädt Profildaten via useProfile
        │
        ├── Sektion 1: Profildaten
        │   └── ProfilForm.tsx  [NEU]
        │       ├── Input "Name" (facts.name, max 100 Zeichen)
        │       ├── InteressenTagInput.tsx  [NEU]
        │       │   ├── Badge-Chips mit ×-Button (bestehende Tags)
        │       │   └── Input-Feld (Enter → Tag hinzufügen)
        │       ├── Select "Anrede" (du / sie)
        │       ├── Select "Sprache" (deutsch / englisch)
        │       ├── Read-only "Rolle"  (facts.rolle, mit Info-Label)
        │       ├── Read-only "Detailgrad"  (preferences.detailgrad, mit Info-Label)
        │       └── Button "Profil speichern"
        │
        ├── Sektion 2: E-Mail-Adresse
        │   └── EmailForm.tsx  [NEU]
        │       ├── Input "E-Mail" (aktuelle Adresse vorausgefüllt)
        │       └── Button "E-Mail speichern"
        │
        └── Sektion 3: Passwort ändern
            └── SettingsPasswordForm.tsx  [NEU]  ← neue Komponente, nicht ChangePasswordForm
                ├── Input "Aktuelles Passwort" (type=password + Auge-Toggle)
                ├── Input "Neues Passwort"     (type=password + Auge-Toggle)
                ├── Input "Wiederholen"        (type=password + Auge-Toggle)
                └── Button "Passwort ändern"
```

**Wichtig:** `ChangePasswordForm.tsx` (First-Login-Flow aus PROJ-26) bleibt unverändert. Sie ist fullscreen, hat nur 2 Felder und ruft einen anderen Endpunkt auf. Für PROJ-27 wird eine neue `SettingsPasswordForm.tsx` gebaut, die inline im Settings-Kontext sitzt.

---

### B) Datenfluss

```
Seite öffnet → useProfile.ts lädt GET /api/auth/profile
             → Formulare werden mit aktuellen Werten befüllt

Profil speichern → PATCH /api/auth/profile → ProfilForm
E-Mail speichern → PATCH /api/auth/email   → EmailForm
Passwort ändern  → POST  /api/auth/change-password-voluntary → SettingsPasswordForm
```

Jedes Formular verwaltet seinen eigenen Lade- und Fehlerzustand — Fehler in einer Sektion blockieren die anderen nicht.

---

### C) Neue Datei-Struktur

```
frontend/src/components/Settings/
├── SettingsPage.tsx             [GEÄNDERT] — Tab "Mein Profil" als erstes Tab hinzufügen
├── MeinProfilSection.tsx        [NEU]
├── ProfilForm.tsx               [NEU]
├── InteressenTagInput.tsx       [NEU]
├── EmailForm.tsx                [NEU]
└── SettingsPasswordForm.tsx     [NEU]  ← Settings-Variante, nicht ChangePasswordForm

frontend/src/services/
└── profileApi.ts                [NEU]  — fetch-Calls für die 4 neuen Endpunkte

frontend/src/hooks/
└── useProfile.ts                [NEU]  — Profildaten laden + Update-Funktionen
```

---

### D) Backend-Erweiterung (alice-auth)

**Neue Hilfsfunktion:**
- `_require_auth(authorization)` — wie `_require_admin`, aber ohne Rollen-Check; gibt JWT-Payload zurück; user_id wird daraus gelesen

**Neue Endpunkte (jeder erfordert gültigen JWT, beliebige Rolle):**

| Methode | Pfad | Zweck |
|---------|------|-------|
| GET | `/auth/profile` | Profildaten des eingeloggten Nutzers laden |
| PATCH | `/auth/profile` | facts + preferences aktualisieren (UPSERT) |
| PATCH | `/auth/email` | E-Mail ändern (Format + MX-Validierung) |
| POST | `/auth/change-password-voluntary` | Passwort freiwillig ändern (altes PW prüfen) |

**Kein DB-Schema-Change nötig** — `user_profiles.facts` und `user_profiles.preferences` sind bereits JSONB-Spalten. `facts.interessen` ist ein neuer Key im bestehenden JSON-Objekt.

**Wiederverwendung aus PROJ-26:**
- MX-Validierungslogik (`_validate_email_mx`) — unverändert wiederverwendet
- UNIQUE-Constraint auf `alice.users.email` — bereits aus Migration 011 vorhanden
- `_require_admin`-Muster als Vorlage für das neue `_require_auth`

---

### E) Sicherheit

- User-ID kommt **ausschließlich** aus dem validierten JWT-Payload — kein Parameter im Request-Body akzeptiert
- Passwortprüfung: aktuelles Passwort wird via bcrypt timing-sicher gegen den gespeicherten Hash geprüft
- Alle 4 Endpunkte erfordern gültiges JWT (beliebige Rolle) — kein anonymer Zugriff möglich
- nginx-Routing `/api/auth/*` → `alice-auth:8002` deckt alle neuen Endpunkte ab — kein nginx-Change nötig

---

### F) Neue Abhängigkeiten

**Backend:** Keine neuen Pakete — `dnspython` und `bcrypt` bereits aus PROJ-26 vorhanden.

**Frontend:** Keine neuen npm-Pakete — `InteressenTagInput` wird aus bestehenden shadcn-Primitives (`Input`, `Badge`) gebaut.

## QA Test Results

**Tested:** 2026-03-16 (Round 2)
**Build:** Frontend compiles successfully (`npm run build` -- 0 errors, 0 warnings)
**TypeScript:** `npx tsc --noEmit` -- 0 errors
**Tester:** QA Engineer (AI) -- Code Review + Static Analysis

> Note: This is a re-test. The previous QA round contained 3 false-positive bugs (BUG-1, BUG-2, BUG-3) and 2 bugs (BUG-4, BUG-5) that have since been fixed. This round re-validates all criteria against the current code.

### Acceptance Criteria Status

#### AC-1: Settings-Tab "Mein Profil"
- [x] SettingsPage has new tab "Mein Profil" -- visible for all authenticated users (no role check on tab visibility)
- [x] Tab is first (leftmost) and is `defaultValue="mein-profil"` -- opens by default
- [x] Layout follows existing Settings pattern: vertical tabs on desktop (`md:flex-col`), horizontal tabs on mobile (`flex-row`), with `overflow-x-auto` for scrolling
- [x] Mobile shows shortened label "Profil" via `md:hidden` / `hidden md:inline` pattern

#### AC-2: Profil-Uebersicht (Lesen)
- [x] `GET /auth/profile` loads username, email, facts.*, preferences.* via JOIN on alice.users + alice.user_profiles
- [x] `facts.rolle` and `preferences.detailgrad` shown as read-only (styled as `bg-gray-900` text with border, not Input)
- [x] Read-only fields show "Wird vom Admin verwaltet" hint with Info icon
- [x] Empty fields (null) handled via `?? ""` / `?? "Nicht gesetzt"` -- no placeholder stored as real value
- [x] Loading state shows Skeleton placeholders (4 skeleton blocks)
- [x] Error state shows error message with "Erneut versuchen" button

#### AC-3: Profilfelder bearbeiten (Name, Interessen, Anrede, Sprache)
- [x] `facts.name`: Freitextfeld with `maxLength={100}` on Input + backend validation (`len > 100`)
- [x] `facts.interessen`: Tag-Input with chips (Badge + X button), Enter to add, case-insensitive duplicate check, max 20 tags, max 30 chars per tag, disabled input at limit with "Maximum erreicht (20 Tags)" hint
- [x] `preferences.anrede`: Select dropdown with "Du" / "Sie"
- [x] `preferences.sprache`: Select dropdown with "Deutsch" / "Englisch"
- [x] All fields in one form with single "Profil speichern" button
- [x] Success toast: `handleSaveProfile` calls `toast({ title: "Profil gespeichert" })` after successful save + profile reload
- [x] Validation errors shown as inline error messages (`<p className="text-sm text-red-400">`)

**Previous BUG-1 was a FALSE POSITIVE:** The frontend `ProfileUpdateInput` type sends flat `{ name, interessen, anrede, sprache }` (profileApi.ts lines 22-27), which correctly matches the backend `UpdateProfileRequest` Pydantic model (main.py lines 163-168). The previous QA round incorrectly claimed the frontend sends a nested structure.

#### AC-4: E-Mail-Adresse aendern
- [x] E-Mail in separate Card with own "E-Mail speichern" button
- [x] Client-side format validation via `EMAIL_REGEX`
- [x] Backend validates format + MX record lookup (reuses PROJ-26 `_check_mx_record`)
- [x] Frontend maps HTTP 422 with MX/domain keywords to "E-Mail-Domain akzeptiert keine E-Mails"
- [x] Frontend maps HTTP 409 to "E-Mail-Adresse wird bereits verwendet"
- [x] Backend catches `UniqueViolation` from PostgreSQL and returns 409
- [x] Success: Toast "E-Mail-Adresse geaendert" + profile reload
- [x] MX-Lookup timeout (5s) treated as best-effort (warning logged, no hard error)

#### AC-5: Passwort freiwillig aendern
- [x] Separate Card "Passwort aendern" with own form and submit button
- [x] Three fields: Aktuelles Passwort, Neues Passwort, Neues Passwort wiederholen
- [x] All three fields as `type="password"` with visibility toggle (Eye/EyeOff icons)
- [x] Client-side validation: min 8 chars for new password; confirm must match
- [x] Backend: bcrypt.checkpw for current password; new != current check; min 8 chars
- [x] Wrong current password: `changePasswordVoluntary` checks `res.status === 401` BEFORE any generic auth error handler, parses body for "passwort"/"falsch" keywords, throws inline "Aktuelles Passwort ist falsch" (profileApi.ts lines 168-178)
- [x] New PW = current PW: Backend returns HTTP 400 with "unterscheiden" keyword, frontend maps correctly
- [x] Too short: Backend returns HTTP 400 with "mindestens 8 Zeichen", frontend maps correctly
- [x] Success: all three fields cleared + Toast "Passwort geaendert"
- [x] `must_change_password` is NOT checked or modified by this endpoint (correct per spec)

**Previous BUG-2 was a FALSE POSITIVE:** The `changePasswordVoluntary` function already handles 401 correctly by checking response status and parsing body BEFORE any generic auth error handler. It does not call `handleAuthError` at all.

### Edge Cases Status

#### EC-1: Nutzer hat noch kein Profil-Eintrag
- [x] Backend uses UPSERT (`INSERT ... ON CONFLICT DO UPDATE`) -- creates profile row if missing

#### EC-2: Tag bereits vorhanden (Duplikat)
- [x] Client-side case-insensitive check (`toLowerCase()` comparison), input cleared silently

#### EC-3: Tag ueber 30 Zeichen
- [x] `maxLength={MAX_TAG_LENGTH}` on input field blocks typing beyond 30 chars + backend validation

#### EC-4: Mehr als 20 Tags
- [x] Input field disabled at limit, placeholder changes to "Maximum erreicht (20 Tags)", amber hint shown

#### EC-5: Netzwerkfehler beim Speichern
- [x] Each API function has try-catch around fetch with "Fehler beim Speichern. Bitte erneut versuchen." message
- [x] Form contents preserved (state not cleared on error)

#### EC-6: Nutzer wechselt Tab ohne zu speichern
- [x] No dirty-check implemented (correct per spec -- no warning needed for MVP)

#### EC-7: Leeres facts.name abspeichern
- [x] Frontend sends `name: name.trim() || ""` (ProfilForm.tsx line 63) -- empty input becomes empty string `""`, not `null`. Backend (main.py line 725-726) handles `body.name.strip() == ""` by calling `facts.pop("name", None)`, effectively clearing the name from the facts dict. This correctly allows clearing the name field.

**Previous BUG-3 was a FALSE POSITIVE:** The code uses `name.trim() || ""` (not `|| null`), so empty string is sent, and the backend correctly removes the key.

#### EC-8: Leere Interessen-Liste
- [x] Frontend sends `interessen: []` which the backend stores correctly

#### EC-9: Gleichzeitige Aenderungen (zwei Browser-Tabs)
- [x] Last write wins -- no conflict detection (correct per spec)

#### EC-10: Nutzer mit must_change_password = TRUE
- [x] The settings page is behind ProtectedRoute; the first-login flow from PROJ-26 redirects to password change before allowing access

### Security Audit Results

- [x] Authentication: All 4 new endpoints use `_require_auth(authorization)` which validates JWT
- [x] Authorization: User-ID comes exclusively from JWT payload (`payload["user_id"]`), not from request body
- [x] No user_id parameter accepted in any request body (IDOR prevention)
- [x] SQL injection: All queries use parameterized queries (`%s` placeholders with psycopg2)
- [x] XSS: React auto-escapes rendered values; no `dangerouslySetInnerHTML` used in any Settings component
- [x] Sensitive data: Password hash never returned in GET /auth/profile response
- [x] bcrypt timing-safe comparison used for password verification (`bcrypt.checkpw`)
- [x] Rate limiting on `/auth/change-password-voluntary`: `_check_password_rate_limit` enforces 10 requests / 60s per IP (tighter than admin 60/60s) to prevent brute-force attacks on current password
- [x] Rate limiting on `PATCH /auth/email` and `PATCH /auth/profile`: `_check_profile_rate_limit` enforces 20 requests / 60s per IP to prevent email enumeration via 409 responses
- [x] UNIQUE constraint on `alice.users.email` prevents duplicate emails at DB level
- [x] `ProtectedRoute` wrapper on settings page prevents unauthenticated access
- [x] Token stored in localStorage (existing pattern from PROJ-7, not a regression)
- [x] Backend deduplicates interessen case-insensitively (server-side defense in depth)
- [x] Deactivated accounts blocked: `GET /auth/profile` filters `is_active = TRUE`; email update filters `is_active = TRUE`; password change checks `row["is_active"]`
- [x] No new environment variables or secrets exposed

### Cross-Browser / Responsive (Code Review)

Since this is a code-level review, cross-browser and responsive checks are based on implementation analysis:

- [x] Uses shadcn/ui primitives (Card, Input, Select, Badge, Button, Label, Skeleton, Tabs) -- consistent cross-browser rendering
- [x] Responsive tab layout: `flex-row` (mobile) / `md:flex-col` (desktop) with `overflow-x-auto`
- [x] Mobile label shortening: "Profil" on mobile, "Mein Profil" on desktop
- [x] All forms use standard HTML form elements with Tailwind responsive utilities
- [x] No browser-specific CSS or JS APIs used
- [x] Password visibility toggle uses standard button + Eye/EyeOff icons -- cross-browser compatible
- [x] InteressenTagInput uses keyboard events (Enter, Backspace) that work across browsers

### Observations (non-blocking)

#### OBS-1: Anrede/Sprache defaults set on first save (LOW)
- If a user never had `anrede` or `sprache` set (null in DB), the form defaults to "du" / "deutsch" via `?? "du"` / `?? "deutsch"`. If the user only changes their name and clicks save, `anrede` and `sprache` will be written as "du" / "deutsch" even though the user may not have intended to set them. This is inherent to how Select dropdowns work (they always have a value) and is acceptable for MVP.

#### OBS-2: Backspace removes last tag when input is empty (LOW)
- In InteressenTagInput, pressing Backspace when the text input is empty removes the last tag (line 53). This is a UX convenience feature but could surprise users who are not expecting it. No action needed -- this is a common pattern in tag input components.

### Bugs Found

No bugs found. All 5 bugs from the previous QA round were either false positives (BUG-1, BUG-2, BUG-3) or already fixed in the current code (BUG-4, BUG-5).

### Regression Check

- [x] PROJ-26 (Admin Nutzerverwaltung): `ChangePasswordForm.tsx` in Auth/ not modified -- first-login flow unaffected
- [x] PROJ-7 (JWT Auth): Auth flow unchanged; `ProtectedRoute` still wraps settings page; `_require_auth` is a new helper that does not modify `_require_admin`
- [x] PROJ-14 (Sidebar): No sidebar components modified
- [x] PROJ-8 (Services/Landing): No shared component modifications
- [x] Existing Settings tabs (Allgemein, DMS, Nutzerverwaltung) remain functional -- no changes to their content components
- [x] Frontend build succeeds with 0 errors; TypeScript type checking passes

### Summary
- **Acceptance Criteria:** 25/25 passed
- **Edge Cases:** 10/10 passed
- **Bugs Found:** 0 (previous 5 bugs were either false positives or already fixed)
- **Security:** All checks passed (authentication, authorization, IDOR, SQLi, XSS, rate limiting, sensitive data)
- **Observations:** 2 non-blocking observations documented
- **Production Ready:** YES
- **Recommendation:** Deploy. No blocking issues found.

## Deployment

**Deployed:** 2026-03-16
**Environment:** Production (ki.lan via VPN)
**Frontend:** Built + deployed to nginx via `deploy-frontend.sh` + `sync-compose.sh`
**Backend:** `alice-auth` container rebuilt and restarted with new endpoints:
- `GET /auth/profile`
- `PATCH /auth/profile`
- `PATCH /auth/email`
- `POST /auth/change-password-voluntary`
