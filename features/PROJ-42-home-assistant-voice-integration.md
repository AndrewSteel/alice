# PROJ-42: Home Assistant Voice Integration

## Status: Planned
**Created:** 2026-06-02
**Last Updated:** 2026-06-02

## Dependencies
- Requires: PROJ-40 (Speech Gateway Service) — Wyoming-Endpunkt, VoicePipeline, Device-Mapping-Mechanismus
- Requires: alice-chat-stream — AI-Pipeline mit HA-Tool-Calls und `conversation_end`-Event-Signaling
- Required by: PROJ-43 (Speaker Recognition) — Speaker-ID-Hook im Gateway wird in Wyoming-Sessions aktiv

## User Stories

- Als Nutzer möchte ich "Hey Jarvis" sagen und Alice eine beliebige Frage stellen können, damit ich Alice hands-free im Raum nutzen kann — ohne Smartphone oder Browser.

- Als Nutzer möchte ich nach Alices Antwort direkt weiterreden können, ohne erneut "Hey Jarvis" zu sagen, damit wir eine natürliche Konversation führen können.

- Als Nutzer möchte ich "Licht im Büro ausschalten" sagen und dass die Session danach sofort endet, damit ich keine unnötige Wartezeit nach einer Steuerungsanweisung habe.

- Als Nutzer möchte ich, dass "Okay Nabu" weiterhin HA Assist auslöst und unverändert funktioniert, damit ich HA-native Funktionen nicht verliere.

- Als Admin möchte ich ein neues Gerät durch einen einzelnen Eintrag in einer Konfigurationsdatei hinzufügen können, damit die Integration ohne Code-Änderungen skaliert.

- Als Admin möchte ich das Custom ESPHome YAML im Repository haben, damit ich es nach einem Firmware-Update des Geräts reproduzieren kann.

- Als Nutzer möchte ich bei Fehlern (Alice nicht erreichbar, STT-Fehler) immer eine gesprochene Rückmeldung erhalten, damit ich nie vor einem stillen Gerät stehe.

## Acceptance Criteria

### ESPHome-Konfiguration (HA Voice PE)
- [ ] Custom ESPHome YAML liegt unter `devices/ha-voice-pe/espHome.yaml` im Repository
- [ ] "Hey Jarvis" ist als Wakeword konfiguriert und löst die direkte Verbindung zum Alice Gateway Wyoming-Endpunkt aus (bypassing HA Assist pipeline)
- [ ] "Okay Nabu" bleibt als Wakeword für HA Assist konfiguriert und funktioniert unverändert parallel
- [ ] Das Device bleibt über die ESPHome-Integration in HA sichtbar (Entities, Lautstärke, LED, Events) — nur die Voice-Pipeline wird herausgelöst
- [ ] Das YAML enthält einen Kommentarblock zur Update-Prozedur: was bei einem HA Voice PE Firmware-Update zu tun ist

### Gateway — Wyoming Satellite Endpunkt
- [ ] Der Wyoming-Endpunkt (Port 10302) akzeptiert direkte Verbindungen von ESPHome-Geräten
- [ ] Alice identifiziert das verbindende Gerät anhand der Quell-IP; das Mapping ist in `device-mapping.yaml` konfiguriert
- [ ] Bei unbekannter Quell-IP erhält das Gerät eine gesprochene Fehlermeldung auf Deutsch und die Verbindung wird beendet
- [ ] Der Gateway führt die vollständige Pipeline aus: faster-whisper STT → alice-chat-stream → Piper TTS → Audio zurück ans Gerät
- [ ] TTS-Audio wird sentence-level gestreamt (Pipelining aus PROJ-40 bleibt aktiv)

### Device-Mapping (Konfiguration)
- [ ] `device-mapping.yaml` unterstützt beliebig viele Einträge mit den Feldern: `ip`, `user_id`, `name`, `room`
- [ ] Ein neues Gerät hinzufügen erfordert ausschließlich einen neuen YAML-Eintrag — kein Code-Change
- [ ] Änderungen an `device-mapping.yaml` werden beim Gateway-Neustart übernommen

### Continued Conversation
- [ ] Nach vollständiger TTS-Antwort bleibt die Session offen und wartet auf neue Spracheingabe (kein erneutes Wakeword nötig)
- [ ] Session endet automatisch nach 30 Sekunden Stille
- [ ] Session endet sofort wenn alice-chat-stream ein `conversation_end`-Event sendet — dies geschieht nach HA-Aktionen mit Schreibzugriff (Licht schalten, Thermostat setzen etc.)
- [ ] Reine HA-Abfragen (read-only, z.B. "Ist das Licht im Büro an?") lösen kein `conversation_end` aus — Session bleibt offen
- [ ] Bei Session-Ende kehrt das Gerät automatisch in den Wakeword-Lausch-Modus zurück

### Fehlerbehandlung
- [ ] Bei STT-Fehler, KI-Timeout oder TTS-Fehler erhält das Gerät eine gesprochene Fehlerantwort auf Deutsch
- [ ] Stille nach Wakeword (< 0.5s Audio oder leeres Transkript): gesprochene Rückmeldung "Ich habe nichts verstanden, bitte wiederholen."
- [ ] Fällt der Gateway-Prozess aus, antwortet das Gerät auf "Hey Jarvis" nicht — kein Hängen, kein Crash; ESPHome-Timeout greift; "Okay Nabu" bleibt unberührt

## Edge Cases

- **Firmware-Update HA Voice PE**: Custom ESPHome YAML muss manuell neu geflasht werden; Prozedur ist im YAML dokumentiert und im Repository nachvollziehbar
- **DHCP-Reservation fällt aus (IP ändert sich)**: Gateway antwortet "Gerät nicht konfiguriert"; Fix: DHCP-Reservation wiederherstellen, ggf. `device-mapping.yaml` aktualisieren
- **Beide Wakewords gleichzeitig aktiv**: "Hey Jarvis"- und "Okay Nabu"-Sessions sind vollständig unabhängig; kein Konflikt auf Gateway-Seite
- **Gateway nicht erreichbar beim Wakeword-Trigger**: ESPHome-Connection-Timeout; Gerät kehrt zu Wakeword-Modus zurück; keine gesprochene Fehlermeldung möglich (kein Gateway zum Sprechen)
- **Barge-In während TTS**: Das HA Voice PE sendet firmware-seitig kein Audio während TTS läuft; kein Interrupt, Session läuft normal zu Ende (keine Gateway-Änderung nötig)
- **Silence-Timeout feuert während Nutzer beginnt zu sprechen**: Eingehende Audio-Aktivität setzt den Timeout zurück
- **Neues Gerät hinzufügen (Satellite1 oder zweites HA Voice PE)**: Neuer Eintrag in `device-mapping.yaml` + neues ESPHome YAML unter `devices/<device-name>/espHome.yaml`; kein Code-Change
- **Unbekannte Device-IP**: Gesprochene Fehlerantwort "Gerät nicht konfiguriert", kein KI-Aufruf, Verbindung wird beendet

## Technical Requirements

- **Performance**: End-to-End (Wakeword-Ende → erste TTS-Silbe) < 4s
- **Port**: 10302 (Wyoming — bereits in PROJ-40 definiert und in compose.yml konfiguriert)
- **Repository-Struktur**:
  - `devices/ha-voice-pe/espHome.yaml` — Custom ESPHome YAML für HA Voice PE Pilotgerät
  - `device-mapping.yaml` (Docker-Volume) — IP → user_id Mapping, erweiterbar
- **Sprache**: Deutsch (Standard, konfigurierbar per Umgebungsvariable)
- **Barge-In**: Nicht implementiert für Wyoming-Geräte (firmware-seitige Einschränkung; Extension-Path via PROJ-43 Speaker-Verification Hook bleibt erhalten)
- **Sicherheit**: Wyoming-Endpunkt ist nur im internen Docker-Netz und VPN erreichbar; keine JWT-Authentifizierung (Device-IP als Identifikation reicht für VPN-only Deployment)

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Context: What PROJ-40 Already Built

The core Wyoming infrastructure is **fully implemented** in `alice-speech-gateway`. PROJ-42 does not rebuild it — it completes the last missing piece (ESPHome device config) and refines the device-mapping schema.

Already running (PROJ-40, status: Approved):
- Wyoming TCP server on port 10302 — accepts direct device connections
- Device identification by **source IP** (not a protocol field — the Wyoming protocol carries no device ID; this was discovered during PROJ-40 live testing)
- Continued conversation loop (open session after each TTS reply, 30-second silence timeout)
- `conversation_end` signal handling — AI signals session end after HA write actions (e.g. lights switched), session stays open after read-only queries
- Full pipeline: faster-whisper STT → alice-chat-stream → Piper TTS → audio back to device
- Spoken German error messages for all failure modes (unknown device, STT error, AI timeout, audio too short)

### What PROJ-42 Delivers

PROJ-42 has **three components** — no new containers, no database changes, no n8n workflows.

```
PROJ-42 Delivery
│
├── 1. ESPHome Device Configuration (NEW FILE)
│   └── devices/ha-voice-pe/espHome.yaml
│       Dual wakeword on the HA Voice PE hardware:
│         "Hey Jarvis" → direct TCP Wyoming to Gateway port 10302 (bypasses HA)
│         "Okay Nabu"  → HA Assist (existing, unchanged)
│       Firmware update procedure documented inline
│
├── 2. device-mapping.yaml Format Extension (CHANGE)
│   ├── device-mapping.yaml — new format with name + room per entry
│   ├── device-mapping.example.yaml — updated to show new format
│   └── config.py — parser updated to load name + room alongside user_id
│
└── 3. Gateway — Logging Enhancement (MINOR CHANGE)
    └── wyoming_transport.py — log messages use device name instead of raw IP
        (no logic changes — purely observability improvement)
```

### Data Flow

```
HA Voice PE
  │
  │ "Hey Jarvis" detected (on-device wakeword)
  │
  ↓  direct TCP Wyoming (port 10302) — HA is NOT in this path
alice-speech-gateway
  │  look up source IP in device-mapping.yaml → user_id + name + room
  │  faster-whisper STT
  │  alice-chat-stream (AI pipeline, conversation history)
  │  Piper TTS (sentence-level streaming)
  │  audio back to device
  │  loop: wait for next utterance OR end session
  │    → conversation_end signal (after HA write action) → session ends
  │    → 30 s silence → session ends
  │    → in either case: device returns to wakeword listening mode
  ↓
HA Voice PE (wakeword mode)

HA Voice PE
  │
  │ "Okay Nabu" detected
  │
  ↓  existing HA Assist pipeline — UNCHANGED
Home Assistant Assist
```

### Device-Mapping Data Model (extended)

Each device entry will have four fields:

| Field | Type | Purpose |
|---|---|---|
| `ip` | string | Source IP of TCP connection — primary lookup key |
| `user_id` | UUID | Maps to `alice.users.id` — determines whose session context is used |
| `name` | string | Human-readable device name (used in logs, future UI) |
| `room` | string | Room label (ready for PROJ-43 speaker recognition context) |

Stored in: `device-mapping.yaml` (Docker volume, mounted read-only into the gateway container). Loaded at startup. A gateway restart is required to pick up changes.

No new PostgreSQL tables. No Weaviate changes.

### Key Architectural Decision: Dual Wakeword

The HA Voice PE hardware supports configuring **multiple wakewords with independent pipeline targets**. This is the design that makes PROJ-42 possible without any trade-off:

- "Hey Jarvis" → ESPHome opens a direct TCP connection to the Gateway on port 10302. HA Assist is bypassed for this wakeword entirely.
- "Okay Nabu" → HA's built-in voice assistant pipeline, unchanged.
- Both wakewords are active in parallel on the same device. They are independent — no conflicts.
- The ESPHome integration in HA **remains connected** for entity visibility (entities, LED, volume control, events). Only the voice pipeline for "Hey Jarvis" is rerouted.

### Operational Requirement: DHCP Reservation

Device identity is based on source TCP IP. The HA Voice PE must have a **fixed IP address** via DHCP reservation in the router. If the IP changes, the device receives a spoken error ("Gerät nicht konfiguriert") until `device-mapping.yaml` is updated. This is an ops requirement, not a code change.

### What Does NOT Change

- All gateway Python logic (STT, AI pipeline, TTS, barge-in, continued conversation) — PROJ-40
- HA Assist pipeline and "Okay Nabu" path — untouched
- alice-chat-stream and `conversation_end` event semantics — already implemented
- nginx, PostgreSQL, n8n — no changes needed
- The wyoming-whisper container (port 10300) stays running for HA

### Dependencies Confirmed

| Dependency | Status |
|---|---|
| alice-speech-gateway Wyoming endpoint (port 10302) | Built in PROJ-40 |
| `conversation_end` event from alice-chat-stream after HA write actions | PROJ-40 dependency, implemented |
| ESPHome direct Wyoming satellite support | ESPHome firmware feature, confirmed supported |
| DHCP reservation for device IP | Ops requirement, outside codebase |

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
