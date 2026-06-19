# PROJ-43: Speaker Recognition (Speaker-ID)

## Status: Deployed
**Created:** 2026-06-18
**Last Updated:** 2026-06-19 (Production hotfixes applied. Known issues documented below.)

## Dependencies
- Requires: PROJ-40 (Speech Gateway Service) — Speaker-ID-Hook im Gateway, Wyoming-Pipeline
- Requires: PROJ-42 (HA Voice Integration) — ESPHome-Geräte mit Wake-Word, device-mapping.yaml
- Requires: PROJ-41 (WebApp Voice Interface) — Browser-Mikrofon für WebApp-Enrollment

## User Stories

- Als Nutzer möchte ich, dass Alice mich an meiner Stimme erkennt sobald ich nach "Hey Jarvis" spreche, damit ich ESPHome-Geräte ohne Login nutzen kann.

- Als Admin möchte ich einen neuen Nutzer per Sprachbefehl einrollen ("Hey Jarvis, lass uns einen neuen Nutzer aufnehmen"), damit die Person ihre Stimme direkt am Gerät einspricht und ich keine Fremdaufnahmen beschaffen muss.

- Als Admin möchte ich einen Gast einrollen ("Hey Jarvis, lass uns einen neuen Gast aufnehmen") mit eingeschränkten Rechten.

- Als unbekannter Sprecher möchte ich nach "Hey Jarvis" mit Alice als Gast interagieren können, ohne Enrollment.

- Als Admin möchte ich meine Stimme einmalig über die WebApp einsprechen (Bootstrap), damit ich danach ESPHome-Enrollments per Sprache starten kann.

- Als Admin möchte ich einem WebApp-Nutzer die Berechtigung erteilen, sich über die WebApp für ESPHome-Geräte einzurollen.

- Als Nutzer möchte ich meine Stimmproben über die WebApp erneuern können, wenn die Erkennung sich verschlechtert.

- Als Admin möchte ich Stimmprofile einsehen und löschen können.

- Als Admin möchte ich, dass jeder Turn in einer laufenden CC-Session neu erkannt wird, damit ein Sprecher ohne Berechtigung keine privilegierten Befehle in meiner Session ausführen kann.

## Acceptance Criteria

### Sprechererkennung
- [ ] Gateway identifiziert Sprecher aus dem Utterance-Audio **jedes Turns** bevor der LLM-Call erfolgt
- [ ] Erkannter Sprecher (Konfidenz ≥ Schwellenwert) → dieser Turn nutzt dessen `user_id` und Rolle
- [ ] Unbekannter Sprecher oder Konfidenz < Schwellenwert → dieser Turn nutzt Guest-Rolle
- [ ] Binäre Erkennung — keine Rückfrage bei unsicherer Erkennung, direkt Guest-Rolle
- [ ] Erster Turn einer Session: Alice begrüßt den Sprecher als Auftakt der Antwort; der bisherige Wake-Sound entfällt
  - `ha_only`: Begrüßung + Ergebnis in einem TTS-Output — *"Hallo {display_name}, das Licht ist jetzt an."* / *"Hallo Gast, das Licht ist jetzt an."*
  - `llm`: Begrüßung wird sofort nach Speaker-ID gesprochen (füllt LLM-Wartezeit) — *"Hallo {display_name}, einen Moment…"* / *"Hallo Gast, was kann ich für dich tun?"* — LLM-Antwort folgt nahtlos; ersetzt den "Warte bitte…"-Marker aus PROJ-50 für bekannte Sprecher
- [ ] Folge-Turns in einer CC-Session: Sprecher wird pro Turn neu identifiziert; Rolle kann sich zwischen Turns ändern
- [ ] Wechselt der Sprecher in einer CC-Session, gelten für den neuen Turn ausschließlich dessen Berechtigungen — keine Vererbung der Rolle aus dem vorigen Turn

### Enrollment — ESPHome Voice-Pfad
- [ ] "Hey Jarvis, lass uns einen neuen Nutzer aufnehmen" startet Enrollment mit Rolle `user` — nur wenn auslösender Sprecher als Admin erkannt
- [ ] "Hey Jarvis, lass uns einen neuen Gast aufnehmen" startet Enrollment mit Rolle `guest` — nur wenn auslösender Sprecher als Admin erkannt
- [ ] Nicht-Admin-Trigger → Alice antwortet: "Enrollment kann nur von einem Administrator gestartet werden."
- [ ] Alice führt durch: `display_name` (mit Bestätigung), `username` (mit Bestätigung), Anrede (Du | Sie), Sprache (Deutsch | Englisch)
- [ ] Bei Username-Kollision informiert Alice und fragt nach einem alternativen Username
- [ ] Stimmproben werden während der Enrollment-Konversation erfasst
- [ ] Neuer `alice.users`-Eintrag wird angelegt (ohne E-Mail/Passwort)
- [ ] Eingerollter Nutzer ist unmittelbar auf allen ESPHome-Geräten erkennbar

### Enrollment — WebApp-Pfad
- [ ] Profileinstellungen zeigen "Stimmregistrierung"-Button wenn Admin ihn für den Nutzer freigegeben hat
- [ ] Button ermöglicht Aufnahme von Stimmproben über das Browser-Mikrofon
- [ ] Admin kann den Button pro Nutzer in der Nutzerverwaltung aktivieren/deaktivieren
- [ ] Bootstrap: erster Admin kann sich über die WebApp einrollen ohne vorheriges ESPHome-Enrollment
- [ ] Bestehende Stimmproben können über denselben Pfad erneuert werden (Überschreiben)

### Admin-Verwaltung
- [ ] Admin kann Stimmprofile in der WebApp einsehen und löschen
- [ ] Admin kann einem via ESPHome eingerollten Nutzer nachträglich E-Mail + Passwort vergeben (WebApp-Zugang)

### device-mapping.yaml
- [ ] `user_id`-Feld wird aus dem Speaker-Recognition-Routing entfernt — user_id wird ausschließlich aus der Sprechererkennung bestimmt
- [ ] `name` und `room` bleiben erhalten (Logging, Kontext)

## Edge Cases

- **Bootstrap (Henne-Ei)**: Kein Admin eingerollt → kein ESPHome-Enrollment möglich. Lösung: erster Admin rollt sich einmalig über die WebApp ein.
- **Admin unter Konfidenz-Schwellenwert**: Admin wird als Gast erkannt → Enrollment-Trigger abgelehnt. Admin muss Stimmproben via WebApp erneuern.
- **Username-Kollision**: Alice informiert und fragt nach einem alternativen Username.
- **Enrollment-Abbruch / Verbindungsunterbrechung**: Kein Nutzer wird angelegt, Gateway kehrt in normalen Modus zurück.
- **Stimme verändert** (Krankheit, Stimmbruch): Erkennung schlägt fehl → Guest-Rolle; Neueinrollung via WebApp oder erneutes ESPHome-Enrollment.
- **Erst-Deployment ohne eingerollte Nutzer**: Alle Sprecher werden als Gast erkannt bis Bootstrap abgeschlossen.
- **Mehrere Sprecher gleichzeitig**: Dominanter Sprecher wird erkannt; bei unklarer Dominanz → Guest-Rolle.
- **Sprecher-Wechsel in CC (Rechteeinschränkung)**: Admin startet CC; ein Gast oder unbekannter Sprecher übernimmt den nächsten Turn → Turn wird mit Guest-Rechten ausgeführt, auch wenn die Session ursprünglich von einem Admin gestartet wurde.
- **Sprecher-Wechsel zu höherer Berechtigung in CC**: Unbekannter Sprecher startet Session (Guest-Rolle); Admin spricht im Folge-Turn → Admin-Rechte gelten ab genau diesem Turn.

## Technical Requirements

- **Performance**: Speaker-ID läuft parallel zum STT-Beginn in jedem Turn; Ziel: < 500 ms Mehrlatenz pro Turn gegenüber reiner STT-Verarbeitung
- **Hardware**: TITAN X (Embeddings/Speaker-ID, lokal — gemäß PRD-Constraints)
- **Lokal-First**: Kein Cloud-Dienst für Speaker-ID; lokales Embedding-Modell
- **Sprache**: Enrollment-Dialog auf Deutsch (Standard), Antworten nach eingestellter Nutzerpräferenz

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### System Overview

This feature touches three layers: `alice-speech-gateway` (Speaker-ID engine + enrollment logic), PostgreSQL (voice profiles), and the WebApp Settings (enrollment UI + admin management).

### Component Structure

```
alice-speech-gateway
+-- speaker_id.py (NEW)         — ECAPA-TDNN model wrapper: identify(), enroll()
+-- speaker_db.py (NEW)         — async PostgreSQL read/write for speaker_profiles
+-- enrollment.py (NEW)         — ESPHome enrollment state machine (multi-turn dialog)
+-- pipeline.py (MODIFIED)      — parallel Speaker-ID + STT; per-turn identity; first-turn greeting
+-- config.py (MODIFIED)        — SPEAKER_MODEL_PATH, SPEAKER_THRESHOLD, POSTGRES_DSN
+-- wyoming_transport.py (MOD.) — remove user_id lookup from device-mapping
|
+-- New HTTP endpoints (gateway)
    POST   /enroll              — WebApp audio upload → embedding → store to DB (JWT auth)
    DELETE /enroll/{user_id}    — admin: delete a voice profile
    GET    /enroll/profiles     — admin: list all enrolled voice profiles

WebApp (frontend/src/components/Settings/)
+-- MeinProfilSection.tsx (MODIFIED) — new "Stimmregistrierung" card (conditional on permission)
|   +-- VoiceEnrollmentDialog.tsx (NEW) — record 5 samples, progress bar, upload
+-- NutzerVerwaltungSection.tsx (MODIFIED) — voice enrollment toggle per user
+-- UserTable.tsx (MODIFIED)    — add "Stimme" column with Switch per user
+-- VoiceProfilesSection.tsx (NEW) — admin tab: enrolled users list + delete action
+-- SettingsPage.tsx (MODIFIED) — add "Stimmprofile" tab

Database
+-- alice.speaker_profiles (NEW TABLE)
+-- alice.users (MODIFIED)      — add allow_voice_enrollment column
+-- device-mapping.yaml (MOD.)  — remove user_id field (user identity comes from Speaker-ID)
```

### Data Model

**New table: `alice.speaker_profiles`**

| Field          | Type       | Notes                                            |
| -------------- | ---------- | ------------------------------------------------ |
| `user_id`      | UUID PK/FK | References alice.users; one profile per user     |
| `embeddings`   | FLOAT[][]  | Array of embedding vectors, one per audio sample |
| `sample_count` | INT        | Number of recorded samples (target: 5)           |
| `created_at`   | TIMESTAMP  |                                                  |
| `updated_at`   | TIMESTAMP  |                                                  |

Cosine similarity is computed in Python (no pgvector extension needed — user count will never exceed ~20).

**Modified: `alice.users`**

Add column: `allow_voice_enrollment BOOLEAN DEFAULT false`

Controls whether the "Stimmregistrierung" button appears in a user's profile settings.

**Modified: `device-mapping.yaml`**

Remove `user_id` field. User identity is now determined exclusively by Speaker-ID. `name` and `room` fields are kept (used for logging and room context).

### Speaker Recognition Engine

**Model:** SpeechBrain ECAPA-TDNN, running on TITAN X via CUDA. Shares the GPU context already used by Whisper.

**Flow per turn:**
```
Utterance audio received
  ├── STT (Whisper, existing)
  └── Speaker-ID (ECAPA-TDNN, new) ← runs concurrently as asyncio Task

Both finish → Speaker-ID result: (user_id, confidence)
  • confidence ≥ threshold → turn uses that user's role
  • confidence < threshold → turn uses Guest role (no renegotiation)
```

**First-turn greeting (replaces wake sound):**

- `ha_only` session: gateway passes `speaker_display_name` and `is_first_turn=true` to alice-chat-stream → alice-chat-stream prefixes the HA response: *"Hallo {name}, das Licht ist jetzt an."*
- `llm` session: gateway speaks *"Hallo {name}, einen Moment…"* immediately via TTS after Speaker-ID (occupies the LLM wait slot, same mechanism as the existing "Warte bitte" from PROJ-48) → LLM response follows seamlessly

**Continued Conversation (CC) sessions:**

Each turn re-runs Speaker-ID independently. The identified role applies to that turn only — no carry-over.

### ESPHome Enrollment State Machine

Triggered when STT transcript matches an enrollment intent ("lass uns einen neuen Nutzer/Gast aufnehmen"):

```
State 0: Identity check — is requesting speaker Admin? If not → spoken rejection, return to normal
State 1: Ask display_name   → STT confirmation
State 2: Ask username       → check collision in DB → STT confirmation
State 3: Ask Anrede         → Du | Sie
State 4: Ask Sprache        → Deutsch | Englisch
State 5: Collect 5 samples  → reuses STT audio from the 5 dialog turns above
State 6: Write alice.users + alice.speaker_profiles → spoken confirmation
→ Return to normal pipeline
```

Voice samples are captured from the STT audio already recorded during the dialog turns — no separate "say this phrase" step. This matches the 5-sample target of the WebApp flow.

On abort (silence timeout, disconnect): no partial user is created.

### WebApp Enrollment Flow

```
MeinProfilSection (existing)
  └── "Stimmregistrierung" card (shown only if allow_voice_enrollment = true)
        └── VoiceEnrollmentDialog
              Step 1: Record 5 audio samples (browser mic, ~3 sec each)
              Step 2: Progress bar (1/5, 2/5, …)
              Step 3: Upload batch to gateway POST /enroll (JWT auth)
              Step 4: Success / error state

NutzerVerwaltung → UserTable
  └── "Stimme" column: Switch per user (toggles allow_voice_enrollment)

Settings → "Stimmprofile" tab (admin only)
  └── VoiceProfilesSection: table of enrolled users, delete button per row
```

### Tech Decisions

| Decision                                    | Rationale                                                                                     |
| ------------------------------------------- | --------------------------------------------------------------------------------------------- |
| SpeechBrain ECAPA-TDNN                      | Runs locally on CUDA; no cloud; well-maintained; best accuracy/weight ratio for < 20 speakers |
| Embeddings in PostgreSQL (float array)      | User count stays small — no vector DB needed; keeps data in one place                         |
| Speaker-ID as module inside gateway         | Shares GPU context with Whisper; avoids network hop; < 500 ms target is achievable            |
| WebApp enrollment via gateway HTTP endpoint | Gateway already holds the model; avoids routing raw audio through Next.js                     |
| Enrollment state machine inside gateway     | Enrollment is a voice dialog, not an LLM conversation; gateway owns the audio loop            |
| 5 samples for both enrollment paths         | Consistent quality target; sufficient for ECAPA-TDNN baseline accuracy                        |

### New Dependencies (gateway)

| Package       | Purpose                                                          |
| ------------- | ---------------------------------------------------------------- |
| `speechbrain` | ECAPA-TDNN speaker embedding model                               |
| `asyncpg`     | Async PostgreSQL client (gateway has no DB connection currently) |

### Files Changed / Created

| File                                                                                 | Action                                                           |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| `docker/compose/automations/alice-speech-gateway/app/speaker_id.py`                  | NEW                                                              |
| `docker/compose/automations/alice-speech-gateway/app/speaker_db.py`                  | NEW                                                              |
| `docker/compose/automations/alice-speech-gateway/app/enrollment.py`                  | NEW                                                              |
| `docker/compose/automations/alice-speech-gateway/app/pipeline.py`                    | MODIFIED                                                         |
| `docker/compose/automations/alice-speech-gateway/app/config.py`                      | MODIFIED                                                         |
| `docker/compose/automations/alice-speech-gateway/app/wyoming_transport.py`           | MODIFIED                                                         |
| `docker/compose/automations/alice-speech-gateway/config/device-mapping.example.yaml` | MODIFIED                                                         |
| `sql/init-schema.sql`                                                                | MODIFIED — speaker_profiles table, allow_voice_enrollment column |
| `frontend/src/components/Settings/MeinProfilSection.tsx`                             | MODIFIED                                                         |
| `frontend/src/components/Settings/VoiceEnrollmentDialog.tsx`                         | NEW                                                              |
| `frontend/src/components/Settings/NutzerVerwaltungSection.tsx`                       | MODIFIED                                                         |
| `frontend/src/components/Settings/UserTable.tsx`                                     | MODIFIED                                                         |
| `frontend/src/components/Settings/VoiceProfilesSection.tsx`                          | NEW                                                              |
| `frontend/src/components/Settings/SettingsPage.tsx`                                  | MODIFIED                                                         |

## QA Test Results

**Tested:** 2026-06-18
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### Sprechererkennung (Speaker Recognition)

- [x] Gateway identifiziert Sprecher aus dem Utterance-Audio jedes Turns vor dem LLM-Call (`wyoming_transport.py:148-154`, `pipeline.py:170-199`)
- [x] Erkannter Sprecher (Konfidenz ≥ Schwellenwert) → Turn nutzt dessen `user_id` und Rolle (`pipeline.py:201-204`, `jwt_factory` callback)
- [x] Unbekannter Sprecher / Konfidenz < Schwellenwert → Guest-Rolle (`speaker_id.py:115-117`, binary — keine Rückfrage)
- [x] Erster Turn `ha_only`: Begrüßung als Prefix der HA-Antwort — `pipeline.py:316-319`
- [x] Erster Turn `llm`: Begrüßung sofort nach Speaker-ID als Thinking-Message (`pipeline.py:326-335`)
- [x] Folge-Turns CC: Speaker-ID per Turn neu ausgeführt (Konversationsschleife in `wyoming_transport.py`)
- [x] Sprecher-Wechsel in CC: Nur Berechtigungen des aktuellen Turns gelten (`VoicePipeline.user_id` wird via `jwt_factory` pro Turn ersetzt)

#### Enrollment — ESPHome Voice-Pfad

- [x] "lass uns einen neuen Nutzer aufnehmen" → Enrollment mit Rolle `user` (nur Admin) — `wyoming_transport.py:190-207`
- [x] "lass uns einen neuen Gast aufnehmen" → Enrollment mit Rolle `guest` (nur Admin)
- [x] Nicht-Admin-Trigger → `"Enrollment kann nur von einem Administrator gestartet werden."` (`config.py:103`)
- [x] Alice führt durch: `display_name` (mit Bestätigung), `username` (mit Bestätigung), Anrede, Sprache — `enrollment.py` state machine
- [x] Username-Kollision → Alice informiert und fragt nach Alternative (`enrollment.py:149-153`)
- [x] Stimmproben aus Dialog-Turns erfasst (`enrollment.py:119-120`, `get_sample_audio()`)
- [x] **BUG-1 (HIGH) — FIXED:** Neuer `alice.users`-Eintrag wird angelegt; `anrede`/`sprache` werden jetzt in `alice.user_profiles.preferences` geschrieben (`speaker_db.create_enrolled_user()` UPSERT, kanonische Werte `du`/`sie` + `deutsch`/`englisch`)
- [x] Eingerollter Nutzer sofort erkennbar — Profile in-place neu geladen (`wyoming_transport.py:335-339`)

#### Enrollment — WebApp-Pfad

- [ ] **BUG-3 (HIGH):** "Stimmregistrierung"-Button im Profil — **FEHLT** (kein Frontend implementiert)
- [ ] **BUG-3 (HIGH):** Aufnahme von Stimmproben via Browser-Mikrofon — **FEHLT**
- [ ] **BUG-3 (HIGH):** Admin-Toggle `allow_voice_enrollment` pro Nutzer in Nutzerverwaltung — **FEHLT**
- [ ] **BUG-3 (HIGH):** Bootstrap — Backend-Endpoint `POST /enroll` existiert, aber **kein UI-Zugang**
- [ ] **BUG-3 (HIGH):** Stimmproben erneuern — Backend unterstützt Überschreiben, aber **kein UI**

#### Admin-Verwaltung

- [ ] **BUG-3 (HIGH):** Stimmprofile einsehen und löschen in WebApp — **FEHLT** (`VoiceProfilesSection.tsx` nicht erstellt)
- [ ] **BUG-3 (HIGH):** E-Mail + Passwort für ESPHome-Nutzer nachträglich vergeben — **FEHLT** (kein UI)

#### device-mapping.yaml

- [x] `user_id`-Feld entfernt — `config.py` `Device`-Dataclass und `device-mapping.example.yaml` aktualisiert
- [x] `name` und `room` erhalten

---

### Edge Cases Status

- [x] Bootstrap (Henne-Ei): Backend-Endpoint `POST /enroll` offen für Admin ohne Prior-Enrollment — kein Frontend-Zugang (→ BUG-3)
- [x] Admin unter Schwellenwert → Enrollment-Trigger abgelehnt (wird als Guest erkannt, kein Admin-Recht)
- [x] Username-Kollision → Alice fragt nach Alternative (enrollment.py state machine)
- [x] Enrollment-Abbruch / leerer Transcript → kein User angelegt (DB-Schreibung nur bei `session.succeeded`)
- [x] Erst-Deployment ohne eingerollte Nutzer → alle als Gast erkannt (`load_all_profiles()` liefert leere Liste)
- [x] **BUG-2 (HIGH) — FIXED:** Success-TTS wird zurückgehalten bis `create_enrolled_user()` erfolgreich war; bei DB-Fehler spricht Alice stattdessen `save_failed` (`wyoming_transport.py` `_run_enrollment_turn`)

---

### Security Audit Results

- [x] JWT required on all `/enroll/*` endpoints — `_require_auth` Dependency
- [x] `user_id` kommt ausschließlich aus JWT-Payload, nie aus Request-Body (`enroll_router.py:71`)
- [x] Admin-only Endpoints (GET /profiles, DELETE, PATCH /allow) prüfen `role == "admin"` aus JWT
- [x] SQL-Injection: alle DB-Queries parametrisiert (asyncpg `$1, $2` Syntax)
- [x] Wyoming-Port nur im Docker-internen Netzwerk erreichbar — kein externer Angriff auf Enrollment
- [x] Enrollment-Trigger verlangt erkannten Admin-Sprecher — unbekannte Sprecher können kein Enrollment starten
- [x] Nginx: `/api/speech/enroll` separater Block mit expliziten Methoden (GET, POST, DELETE, PATCH, OPTIONS)

---

### Bugs Found

#### BUG-1: `anrede` und `sprache` werden in ESPHome-Enrollment still verworfen
- **Severity:** High
- **Steps to Reproduce:**
  1. Admin triggert ESPHome-Enrollment
  2. Benutzer gibt `anrede=Sie` und `sprache=Englisch` an
  3. Enrollment abgeschlossen
  4. Erwartet: `alice.user_profiles.preferences` enthält `{"anrede": "sie", "sprache": "en"}`
  5. Tatsächlich: `alice.user_profiles` Eintrag fehlt völlig; `alice.users` hat keine Felder für diese Werte
- **Root Cause:** `speaker_db.create_enrolled_user()` nimmt `anrede`/`sprache` als Parameter an, ignoriert sie aber; schreibt nicht in `alice.user_profiles`
- **File:** `docker/compose/automations/alice-speech-gateway/app/speaker_db.py:164-181`
- **Priority:** Fix before deployment

#### BUG-2: Vorzeitige Erfolgs-TTS vor tatsächlicher DB-Schreibung im ESPHome-Enrollment
- **Severity:** High
- **Steps to Reproduce:**
  1. Admin triggert ESPHome-Enrollment, füllt alle Felder aus
  2. Enrollment State Machine erreicht `ASKING_SPRACHE` → gibt sofort "Einrollung abgeschlossen" zurück → wird gesprochen
  3. Danach schlägt `create_enrolled_user()` fehl (z.B. DB-Verbindungsproblem)
  4. Erwartet: Alice spricht Erfolg erst nach erfolgreichem DB-Write
  5. Tatsächlich: Erfolg bereits gesprochen; kein Nutzer angelegt; kein Fehler-Feedback
- **Root Cause:** `enrollment.py:172-173` — success message returned in `process_turn()` state machine; DB write happens externally in `wyoming_transport.py:320-340` after TTS has already played
- **Files:** `enrollment.py:162-173`, `wyoming_transport.py:307-342`
- **Priority:** Fix before deployment

#### BUG-3: Frontend-Implementierung komplett fehlend
- **Severity:** High
- **Steps to Reproduce:**
  1. Nutzer öffnet WebApp → Settings → Mein Profil
  2. Erwartet: "Stimmregistrierung"-Karte (wenn admin-enabled)
  3. Tatsächlich: Kein Enrollment-UI vorhanden
- **Root Cause:** Backend-Commit (edb2722) implementierte nur Gateway/DB-Schicht; Frontend-Dateien wurden nie erstellt
- **Missing Files:**
  - `frontend/src/components/Settings/VoiceEnrollmentDialog.tsx` (NEW — fehlt)
  - `frontend/src/components/Settings/VoiceProfilesSection.tsx` (NEW — fehlt)
  - `frontend/src/components/Settings/MeinProfilSection.tsx` (MODIFIED — nicht angepasst)
  - `frontend/src/components/Settings/NutzerVerwaltungSection.tsx` (MODIFIED — nicht angepasst)
  - `frontend/src/components/Settings/UserTable.tsx` (MODIFIED — nicht angepasst)
  - `frontend/src/components/Settings/SettingsPage.tsx` (MODIFIED — nicht angepasst)
- **Priority:** Fix before deployment

#### BUG-4: Enrollment API akzeptiert weniger als 5 Stimmproben
- **Severity:** Medium
- **Steps to Reproduce:**
  1. `POST /enroll` mit 1 WAV-Datei aufrufen
  2. Erwartet: 400 Bad Request ("Mindestens 5 Audioaufnahmen erforderlich")
  3. Tatsächlich: 200 OK — Enrollment mit nur 1 Sample gespeichert
- **Root Cause:** `enroll_router.py:85` prüft `< 1` statt `< 5`
- **Priority:** Fix before deployment

---

### Summary

- **Acceptance Criteria:** 15/25 passed (10 failed)
- **Bugs Found:** 4 total (0 Critical, 3 High, 1 Medium)
- **Security:** Pass — JWT-Auth, user_id aus Token, parametrisierte Queries
- **Production Ready:** NO
- **Recommendation:** Fix BUG-1 (Datenverlust anrede/sprache), BUG-2 (Premature TTS), BUG-3 (Frontend), BUG-4 (Minimum Samples) — dann erneut `/qa` ausführen

## Frontend Implementation Notes

**Implemented:** 2026-06-18 (by /frontend — resolves BUG-3)

The WebApp enrollment + admin management UI (previously missing entirely) is now built. All new/changed files compile cleanly (`npm run build` passes type-check + lint).

### New files
- `frontend/src/services/voiceApi.ts` — gateway REST client: `enrollVoice()`, `getVoiceProfiles()`, `deleteVoiceProfile()`, `setVoiceEnrollmentAllowed()`. Targets `/api/speech/enroll*`. JWT sent as `Authorization: Bearer`; `user_id` never sent in body (gateway derives it from the token).
- `frontend/src/hooks/useWavRecorder.ts` — captures mic audio via Web Audio API and encodes a **16 kHz mono 16-bit WAV** Blob client-side. MediaRecorder's WebM/Opus is avoided because the gateway's `torchaudio.load()` cannot reliably decode it; WAV matches the ECAPA-TDNN pipeline.
- `frontend/src/hooks/useVoiceProfiles.ts` — admin list/delete state for enrolled profiles.
- `frontend/src/components/Settings/VoiceEnrollmentDialog.tsx` — records 5 samples, progress bar + slot indicators, "Neu beginnen" reset, upload, success state.
- `frontend/src/components/Settings/VoiceProfilesSection.tsx` — admin "Stimmprofile" tab: enrolled-users table (desktop + mobile), delete with AlertDialog confirm.

### Modified files
- `MeinProfilSection.tsx` — conditional "Stimmregistrierung" card. Shown when `user.role === "admin"` (bootstrap) **or** `profile.allow_voice_enrollment`.
- `UserTable.tsx` — new "Stimme" column: per-user `Switch` toggling `allow_voice_enrollment`; admins show an "Immer" badge (always allowed); a green mic icon marks users whose voice is already enrolled.
- `NutzerVerwaltungSection.tsx` — wires the toggle handler with success/error toasts.
- `useAdminUsers.ts` — `toggleVoiceEnrollment()`.
- `SettingsPage.tsx` — new admin "Stimmprofile" tab.
- `services/adminApi.ts` / `services/profileApi.ts` — added `allow_voice_enrollment` (+ `speaker_enrollment_complete` on AdminUser) to the types.

### Required backend addition (alice-auth)
The `allow_voice_enrollment` flag lives in `alice.users` but the **alice-auth** service did not expose it. To make the profile card and admin toggle reflect real state, `docker/compose/automations/alice-auth/main.py` was extended:
- `GET /auth/profile` now returns `allow_voice_enrollment`.
- `GET /auth/admin/users` now returns `allow_voice_enrollment` and `speaker_enrollment_complete`.

→ **alice-auth must be redeployed** alongside the frontend for the toggle/card state to load correctly.

### Still open (backend — out of scope for /frontend)
BUG-1 (anrede/sprache dropped), BUG-2 (premature success TTS), and BUG-4 (min-samples check `< 1` vs `< 5`) from the QA results remain and require a `/backend` pass before re-QA.

## Backend Bug Fixes

**Implemented:** 2026-06-18 (by /backend — resolves the three open backend bugs from QA)

- **BUG-1 — `anrede`/`sprache` persisted.** `speaker_db.create_enrolled_user()` now writes an `alice.user_profiles` row inside the same transaction as the `alice.users` insert, storing `preferences = {"anrede", "sprache"}`. Uses `ON CONFLICT (user_id) DO UPDATE` merging via `||` so an existing profile is not clobbered. To stay consistent with the alice-auth `PATCH /auth/profile` format, the enrollment state machine now stores canonical values: `anrede` ∈ {`du`,`sie`} and `sprache` ∈ {`deutsch`,`englisch`} (previously `de`/`en`). Files: `speaker_db.py`, `enrollment.py`.
- **BUG-2 — success TTS deferred until DB write confirms.** `_run_enrollment_turn()` in `wyoming_transport.py` no longer speaks the prompt up-front on the terminal turn. For questions/retries/abort it speaks immediately as before; on the final (succeeded) turn it extracts embeddings, calls `create_enrolled_user()`, and only then speaks the success prompt — or the new `SPEECH_ENROLLMENT["save_failed"]` message if the write fails. Files: `wyoming_transport.py`, `config.py`.
- **BUG-4 — minimum sample count enforced.** `POST /enroll` now rejects fewer than 5 files with `400 "Mindestens 5 Audioaufnahmen erforderlich"` (was `< 1`). File: `enroll_router.py`.

No DB migration needed — `alice.user_profiles` already exists; the gateway pool has write access. No n8n workflow changes. The gateway container (`alice-speech-gateway`) must be rebuilt/redeployed for these changes to take effect.

---

## QA Re-Test Results (Retest)

**Tested:** 2026-06-18 (retest after BUG-1/2/3/4 fixes)
**Tester:** QA Engineer (AI)
**Scope:** Verify the four prior bugs are resolved; re-evaluate all acceptance criteria.

### Prior Bugs — Verification

| Bug                                | Severity | Status    | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ---------------------------------- | -------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BUG-1 — `anrede`/`sprache` dropped | High     | **FIXED** | `speaker_db.create_enrolled_user()` writes `alice.user_profiles` row in the same transaction (`ON CONFLICT … DO UPDATE` merge via `\|\|`); canonical values `du`/`sie` + `deutsch`/`englisch` set in `enrollment.py:162-170`.                                                                                                                                                                                                   |
| BUG-2 — premature success TTS      | High     | **FIXED** | `wyoming_transport.py:_run_enrollment_turn` (313-350) holds the terminal prompt; speaks success only after `create_enrolled_user()` succeeds, else `SPEECH_ENROLLMENT["save_failed"]` (`config.py:120`).                                                                                                                                                                                                                        |
| BUG-3 — frontend missing           | High     | **FIXED** | All 5 new files present; `MeinProfilSection`/`UserTable`/`NutzerVerwaltungSection`/`SettingsPage`/`useAdminUsers`/`adminApi`/`profileApi` wired. `npm run build` passes type-check + lint clean. nginx `^~ /api/speech/enroll` block routes POST/GET/DELETE/PATCH → gateway:10301; `enroll_router` mounted + DB pool init in `main.py:115,76-79`. alice-auth exposes `allow_voice_enrollment` (+`speaker_enrollment_complete`). |
| BUG-4 — min samples `< 1`          | Medium   | **FIXED** | `enroll_router.py:85` now rejects `len(files) < 5` with 400.                                                                                                                                                                                                                                                                                                                                                                    |

### New Bug

#### BUG-5: Admin cannot assign E-Mail + Passwort to an ESPHome-enrolled user (WebApp access) — **FIXED**
- **Fixed:** 2026-06-18
- **Backend:** New `PATCH /auth/admin/users/{user_id}/set-credentials` endpoint in `alice-auth/main.py`. Sets email + hashed OTP, sends OTP email, rolls back on SMTP failure. Rejects if user already has email (409) or email format invalid (422).
- **Frontend:** New `SetCredentialsDialog.tsx` + `setCredentials()` in `adminApi.ts` + `setUserCredentials()` in `useAdminUsers.ts`. `UserTable.tsx` now shows "Zugang einrichten" (active) instead of disabled "OTP zurücksetzen" for users without an email address.

### Acceptance Criteria — Updated Status

#### Sprechererkennung — 7/7 PASS (unchanged from first QA)
#### Enrollment — ESPHome Voice-Pfad — 8/8 PASS (BUG-1, BUG-2 now fixed)
#### Enrollment — WebApp-Pfad — 5/5 PASS (BUG-3 fixed: card, recorder, admin toggle, bootstrap, re-enroll all present and build clean)
#### Admin-Verwaltung — 2/2 PASS
- [x] Stimmprofile einsehen und löschen — `VoiceProfilesSection.tsx` + `GET/DELETE /enroll`
- [x] E-Mail + Passwort nachträglich vergeben — `SetCredentialsDialog.tsx` + `PATCH /auth/admin/users/{id}/set-credentials`
#### device-mapping.yaml — 2/2 PASS (unchanged)

### Security Audit — PASS (re-confirmed)
JWT enforced on all `/enroll/*`; `user_id` from token only; admin-only guards on profiles/delete/allow; parametrised asyncpg queries; nginx enroll block scoped to explicit methods + CORS.

### Summary

- **Acceptance Criteria:** 25/25 passed
- **Bugs:** All resolved (BUG-1/2/3/4/5). 0 Critical, 0 High, 0 Medium open.
- **Security:** Pass
- **Production Ready:** YES — all ACs met, no open bugs.
- **Deploy reminder:** rebuild `alice-speech-gateway` (backend fixes) + redeploy `alice-auth` (new profile fields + set-credentials endpoint); frontend via `deploy-frontend.sh` + `sync-compose.sh`.

---

## QA Re-Test Results (Independent Re-Verification)

**Tested:** 2026-06-18 (independent re-test of the current working tree, incl. uncommitted BUG-5 + alice-auth/frontend changes)
**Tester:** QA Engineer (AI)
**Method:** Code-level verification of every AC against the actual source + frontend production build. The live voice pipeline (Wyoming/ECAPA-TDNN/Whisper/Piper) could **not** be exercised end-to-end locally — it requires CUDA, the SpeechBrain model, Postgres and physical ESPHome devices, all of which run on `ki.lan`. Speaker-recognition ACs are therefore verified by code inspection, not runtime.

### Prior Bugs — Re-Verified

| Bug                            | Sev  | Status    | Evidence (current tree)                                                                                                                                                                                                                                                                                                                |
| ------------------------------ | ---- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| BUG-1 — anrede/sprache dropped | High | **FIXED** | `speaker_db.create_enrolled_user()` writes `alice.user_profiles` in the same `conn.transaction()` as the `users` insert, merging via `preferences \|\| EXCLUDED.preferences` (`speaker_db.py:183-191`); canonical `du`/`sie` + `deutsch`/`englisch` (`enrollment.py:162-170`), matching alice-auth's `PATCH /auth/profile` validation. |
| BUG-2 — premature success TTS  | High | **FIXED** | `_run_enrollment_turn` speaks question/retry/abort prompts immediately but holds the terminal prompt; success spoken only after `create_enrolled_user()` returns, else `SPEECH_ENROLLMENT["save_failed"]` (`wyoming_transport.py:307-351`, `config.py:120`).                                                                           |
| BUG-3 — frontend missing       | High | **FIXED** | All 6 files present and wired (voiceApi, useWavRecorder, useVoiceProfiles, VoiceEnrollmentDialog, VoiceProfilesSection + Mein­Profil/UserTable/Nutzer­Verwaltung/SettingsPage/useAdminUsers/adminApi/profileApi). `npm run build` passes type-check + lint, exit 0.                                                                    |
| BUG-4 — min samples `< 1`      | Med  | **FIXED** | `enroll_router.py:85` rejects `len(files) < 5` with 400.                                                                                                                                                                                                                                                                               |
| BUG-5 — set WebApp credentials | High | **FIXED** | `PATCH /auth/admin/users/{id}/set-credentials` (`main.py:1226`) + `SetCredentialsDialog.tsx` + `adminApi.setCredentials()` + `useAdminUsers.setUserCredentials()`; UserTable shows "Zugang einrichten" for users without an email.                                                                                                     |

### Acceptance Criteria — 25/25 PASS

- **Sprechererkennung (7/7):** per-turn STT+Speaker-ID run concurrently (`wyoming_transport.py:148-154`); confidence ≥ threshold → user role, else Guest (binary, no re-ask); first-turn greeting (ha_only prefix / llm thinking-message); per-turn re-identification with no role carry-over in CC.
- **Enrollment ESPHome (8/8):** admin-gated user/guest triggers; non-admin rejection (`config.py:103`); guided display_name/username/anrede/sprache with confirmations; username-collision re-prompt; samples from dialog turns; new `alice.users` + `user_profiles` row; immediate recognisability via in-place profile reload.
- **Enrollment WebApp (5/5):** conditional "Stimmregistrierung" card; 5-sample recorder (16 kHz mono WAV); admin per-user toggle; admin bootstrap self-enroll; re-enroll overwrites.
- **Admin-Verwaltung (2/2):** view/delete profiles; assign email+OTP to ESPHome-enrolled users.
- **device-mapping.yaml (2/2):** `user_id` removed from `Device`; `name`/`room` retained.

### Security Audit — PASS
JWT enforced on all `/enroll/*` (`_require_auth`); `user_id` strictly from verified token payload (`auth.py` contract, never request body); admin-only guards on profiles/delete/allow/set-credentials; parametrised asyncpg + psycopg2 queries; nginx `^~ /api/speech/enroll` block ordered before the GET-only WS block with explicit method allow-list + scoped CORS; Wyoming port internal-only.

### New Observations (Low — non-blocking, no fix required to ship)

- **OBS-1 (Low):** `admin_set_credentials` sends the OTP email *before* the DB `UPDATE`. If the supplied address is already used by another user, the email is delivered (naming the enrolled user) and the write then fails 409 — a spurious OTP that was never persisted. The pre-check (`main.py:1265`) only verifies the *target* user has no email, not global uniqueness. Mirror the `update_email` pattern (check/handle uniqueness before sending) if hardening later.
- **OBS-2 (Low):** In `_run_enrollment_turn`, `saved=True` is set only after the post-create `load_all_profiles()` reload. If that reload throws, the user *was* created but Alice speaks `save_failed`. Moving the reload outside the saved-determining block would avoid the misleading message. Extremely unlikely (same pool).
- **OBS-3 (design note):** Enrollment embeddings reuse short dialog utterances incl. ~0.5 s confirmations ("Ja"). This is the documented design (no separate "say this phrase" step); recognition quality from sub-second clips may be weaker than the WebApp's ~3 s samples. Accepted tradeoff, flagged for field tuning of `SPEAKER_THRESHOLD`.

### Summary

- **Acceptance Criteria:** 25/25 passed
- **Bugs:** 0 Critical, 0 High, 0 Medium open (BUG-1…5 all resolved). 3 new Low observations, none blocking.
- **Security:** Pass
- **Production Ready:** **YES** — all ACs met, no open Critical/High/Medium bugs.
- **Caveat:** Voice-pipeline ACs verified by code inspection only; a runtime smoke test on `ki.lan` (enroll via WebApp → speak at an ESPHome device → confirm recognition + greeting) is recommended during `/deploy`.
- **Deploy reminder:** rebuild `alice-speech-gateway`; redeploy `alice-auth` (profile fields + set-credentials); frontend via `deploy-frontend.sh` + `sync-compose.sh`.

## Deployment

**Deployed:** 2026-06-19
**Environment:** Production (ki.lan)
**Containers rebuilt:** `alice-speech-gateway` (PyTorch 2.3.1+cu121 pinned for TITAN X / Maxwell CC 5.2; SpeechBrain ECAPA-TDNN), `alice-auth` (new `/auth/profile` allow_voice_enrollment + PATCH set-credentials endpoint)
**Frontend:** deployed via `deploy-frontend.sh` + `sync-compose.sh`
**Smoke test:** WebApp voice enrollment completed successfully; speaker recognition confirmed active.

## Post-Deployment Findings (2026-06-19)

### Hotfixes Applied

**BUG-5: Guest service user missing from DB (Wyoming 503)**
- **Symptom:** All Wyoming voice turns returned 503 from `alice-chat-stream`. WebApp keyboard input worked fine.
- **Root Cause:** `wyoming_transport._token_for()` mints JWTs with `user_id = "00000000-0000-0000-0000-000000000000"` for unidentified speakers. `alice-chat-stream` tries to `INSERT INTO alice.sessions` (FK → `alice.users.id`) — no user with that UUID existed → FK violation → 503.
- **Fix:** `sql/migrations/017-guest-service-user.sql` — inserts a `voice-guest` user with role `guest` and the fixed null UUID. Applied to production.

**BUG-6: WebApp audio VAD too aggressive after PROJ-43 rebuild**
- **Symptom:** WebApp microphone input ("weder PC noch Smartphone") produced no transcript. STT log: 720 ms clip, VAD removed all audio.
- **Root Cause:** Container rebuild likely installed a newer `faster-whisper` 1.x version with stricter default VAD parameters (`min_silence_duration_ms = 2000` causes short clips to be fully filtered).
- **Fix:** Explicit `vad_parameters` in `stt.py`: `threshold=0.3`, `min_silence_duration_ms=500`. Applied and redeployed.

### Known Production Issues (not yet fixed)

**ISSUE-1: ESPHome admin bootstrap (chicken-and-egg)**
- **Description:** The first admin cannot enroll themselves via ESPHome. The enrollment trigger in `wyoming_transport.py` requires the requesting speaker to be recognized as admin via Speaker-ID — but Speaker-ID requires prior enrollment. Catch-22.
- **Current workaround:** Admin must enroll via WebApp first (browser mic), then ESPHome recognition works.
- **Design note:** The WebApp path has a special case: `role === "admin"` always shows the enrollment card, bypassing the `allow_voice_enrollment` flag. This is the intended bootstrap path.
- **Limitation:** First-time deployment requires WebApp access for the admin.

**ISSUE-2: Same-device enrollment creates cross-device quality mismatch**
- **Description:** Embeddings captured on one device (e.g., ESPHome Büro mic) may not match well when speaking on a different device (ESPHome Küche, WebApp mic). Different microphone characteristics (frequency response, noise floor, gain) affect the embedding space.
- **Observed scores:** Short commands ~0.59, longer sentences ~0.64 (enrolled via WebApp, recognized on ESPHome).
- **Current workaround:** Threshold lowered from 0.75 → 0.55 in production `.env` to compensate.
- **Risk:** Lower threshold increases false positive rate. Monitor in production.
- **Future fix options:** (a) Per-device enrollment (enroll on each device separately, store embeddings tagged by device); (b) Audio normalization before embedding extraction (equalization, noise suppression); (c) Separate threshold per device in `device-mapping.yaml`.

### Production Configuration Delta

| Setting                                           | Default | Production |
| ------------------------------------------------- | ------- | ---------- |
| `SPEAKER_THRESHOLD`                               | 0.75    | 0.55       |
| `stt.py` `vad_parameters.threshold`               | 0.5     | 0.3        |
| `stt.py` `vad_parameters.min_silence_duration_ms` | 2000    | 500        |
