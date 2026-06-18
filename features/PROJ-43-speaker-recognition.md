# PROJ-43: Speaker Recognition (Speaker-ID)

## Status: Architected
**Created:** 2026-06-18
**Last Updated:** 2026-06-18 (Tech design added by /architecture)

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

| Field | Type | Notes |
|---|---|---|
| `user_id` | UUID PK/FK | References alice.users; one profile per user |
| `embeddings` | FLOAT[][] | Array of embedding vectors, one per audio sample |
| `sample_count` | INT | Number of recorded samples (target: 5) |
| `created_at` | TIMESTAMP | |
| `updated_at` | TIMESTAMP | |

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

| Decision | Rationale |
|---|---|
| SpeechBrain ECAPA-TDNN | Runs locally on CUDA; no cloud; well-maintained; best accuracy/weight ratio for < 20 speakers |
| Embeddings in PostgreSQL (float array) | User count stays small — no vector DB needed; keeps data in one place |
| Speaker-ID as module inside gateway | Shares GPU context with Whisper; avoids network hop; < 500 ms target is achievable |
| WebApp enrollment via gateway HTTP endpoint | Gateway already holds the model; avoids routing raw audio through Next.js |
| Enrollment state machine inside gateway | Enrollment is a voice dialog, not an LLM conversation; gateway owns the audio loop |
| 5 samples for both enrollment paths | Consistent quality target; sufficient for ECAPA-TDNN baseline accuracy |

### New Dependencies (gateway)

| Package | Purpose |
|---|---|
| `speechbrain` | ECAPA-TDNN speaker embedding model |
| `asyncpg` | Async PostgreSQL client (gateway has no DB connection currently) |

### Files Changed / Created

| File | Action |
|---|---|
| `docker/compose/automations/alice-speech-gateway/app/speaker_id.py` | NEW |
| `docker/compose/automations/alice-speech-gateway/app/speaker_db.py` | NEW |
| `docker/compose/automations/alice-speech-gateway/app/enrollment.py` | NEW |
| `docker/compose/automations/alice-speech-gateway/app/pipeline.py` | MODIFIED |
| `docker/compose/automations/alice-speech-gateway/app/config.py` | MODIFIED |
| `docker/compose/automations/alice-speech-gateway/app/wyoming_transport.py` | MODIFIED |
| `docker/compose/automations/alice-speech-gateway/config/device-mapping.example.yaml` | MODIFIED |
| `sql/init-schema.sql` | MODIFIED — speaker_profiles table, allow_voice_enrollment column |
| `frontend/src/components/Settings/MeinProfilSection.tsx` | MODIFIED |
| `frontend/src/components/Settings/VoiceEnrollmentDialog.tsx` | NEW |
| `frontend/src/components/Settings/NutzerVerwaltungSection.tsx` | MODIFIED |
| `frontend/src/components/Settings/UserTable.tsx` | MODIFIED |
| `frontend/src/components/Settings/VoiceProfilesSection.tsx` | NEW |
| `frontend/src/components/Settings/SettingsPage.tsx` | MODIFIED |

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
