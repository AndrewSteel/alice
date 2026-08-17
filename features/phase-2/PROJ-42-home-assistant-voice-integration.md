# PROJ-42: Home Assistant Voice Integration

## Status: In Review
**Created:** 2026-06-02
**Last Updated:** 2026-06-10

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

## Implementation Notes (Backend)

Implemented the three components from the Tech Design. No new containers, no DB
changes, no n8n workflows — as the architecture specified.

### 1. ESPHome device config (NEW)
- `devices/ha-voice-pe/espHome.yaml` — extends Nabu Casa's official HA Voice PE
  firmware as a remote `package`, then adds the dual-wakeword split:
  - "Okay Nabu" → stock HA Assist (`voice_assistant.start`), unchanged.
  - "Hey Jarvis" → direct TCP Wyoming to the gateway at `ki.lan:10302`
    (`wyoming_satellite.start`), bypassing HA.
  - Native API / OTA stay enabled so the device remains a normal ESPHome device
    in HA (entities, LED ring, volume, button events).
  - Inline firmware-update procedure block included.
- **Open item for QA/ops:** the "Hey Jarvis → raw TCP" path relies on a custom
  ESPHome `external_components/wyoming_satellite` (a Wyoming TCP *client*).
  Stock ESPHome `voice_assistant` cannot open a raw socket, so this component is
  referenced from `devices/ha-voice-pe/components/wyoming_satellite/` but is not
  yet authored/compiled — it needs the real HA Voice PE hardware to build and
  flash. Confirmed with user as the chosen mechanism ("Direct TCP from
  firmware"). The gateway side (Wyoming server on 10302) is fully built (PROJ-40).
- The `packages:` ref is pinned to `@main`; pin to a release tag before flashing.

### 2. device-mapping.yaml format extension (CHANGE)
- New nested format: each source-IP entry now has `user_id` (required) plus
  `name` and `room` (optional). Old flat `IP: "uuid"` format is no longer
  accepted (entries that aren't a mapping are skipped with a logged error).
- `config.py`: added a frozen `Device` dataclass; `load_device_mapping()` now
  returns `dict[str, Device]`, defaults `name` to the IP and `room` to `""`,
  and skips entries missing `user_id`.
- Updated both `device-mapping.yaml` and `device-mapping.example.yaml`.

### 3. Gateway logging enhancement (MINOR CHANGE)
- `wyoming_transport.py`: resolves the `Device` once per connection; logs now
  carry `device` (name) and `room` instead of only the raw IP.

### Fixes made along the way (tests were red on `main`)
- `test_config.py` and `test_wyoming_transport.py` were already failing before
  this work — they predated PROJ-40's switch from a Wyoming-metadata device id
  to source-IP identification (`_TestableHandler` set `_device_id`; production
  uses `_client_ip`). Brought both test files in line with the IP-based code
  and the new `Device` shape.
- Fixed a latent bug in `wyoming_transport._conversation_loop`: the
  silence-timeout log referenced `self._device_id`, which is never set in
  production and would raise `AttributeError` on session timeout. Now logs the
  resolved device label.

Full gateway suite green: **50 passed**
(`alice-speech-gateway/.venv/bin/pytest -q`).

### QA-round bug fixes — BUG-1 + BUG-2 (2026-06-02)

**BUG-2 (service token expiry) — code fix, verified.**
- `pipeline.py`: added `VoicePipeline.set_jwt()` to swap the service token
  between turns (Wyoming-only; the WS client-token path is untouched).
- `wyoming_transport.py`: the continued-conversation loop now re-mints the
  service token at the start of every turn instead of once per session, so a
  long read-only conversation never sends an expired token. A single turn
  always completes inside `SERVICE_JWT_TTL_SECONDS`, so per-turn minting is safe.
- `tests/test_wyoming_transport.py`: added `test_service_token_reminted_each_turn`
  (asserts the token is minted once per turn with distinct values; turn 1 via
  the constructor, later turns via `set_jwt`). Suite now **51 passed**.

**BUG-1 (missing `wyoming_satellite` component) — authored, hardware-verification pending.**
- Decision (confirmed with user): keep the committed "bypass HA" design and
  author the custom ESPHome component, rather than re-routing via an HA Assist
  pipeline. Stock ESPHome `voice_assistant` cannot open a raw socket, so a
  custom Wyoming TCP *client* is genuinely required.
- New: `devices/ha-voice-pe/components/wyoming_satellite/` —
  `__init__.py` (config schema + codegen, `wyoming_satellite.start/.stop`
  actions), `wyoming_satellite.h/.cpp` (the component), and a component README.
  The component connects to the gateway (lwip `getaddrinfo`), runs an on-device
  energy VAD to frame utterances (`audio-start`/`audio-chunk`/`audio-stop`),
  plays back the TTS reply, and loops for continued conversation until a
  no-speech `listen_timeout_ms` ends the session.
- `espHome.yaml`: fixed the `microphone:`/`speaker:` config (the `!extend`
  misuse → plain id references via new `mic_id`/`speaker_id` substitutions),
  switched `alice_gateway_host` guidance to a fixed IP, and exposed the VAD
  tunables (`silence_threshold`, `silence_ms`, `listen_timeout_ms`).
- New: `devices/ha-voice-pe/README.md` — precise build/flash procedure
  (pin package tag → set IP + verify mic/speaker IDs → `esphome config` →
  `compile` → OTA flash → confirm both wakewords → tune VAD → map device IP).
- **Cannot be compiled/flashed without the physical device.** Three ESPHome-version-sensitive
  spots are marked `[VERSION]` in the `.cpp` and documented in the component README
  (mic callback element type, socket factory/connect, `speaker::is_running()` drain
  semantics). Expect to adjust these and tune the VAD during first bring-up.
- Known device-side limitation carried into docs: the gateway's internal
  `conversation_end` is not signalled back over Wyoming, so after a control
  command the device ends the turn via `listen_timeout_ms` silence rather than
  immediately. A future gateway-side Wyoming "stop" event could close that gap.

### ESPHome bring-up learnings (2026-06-03)

Verified `esphome config` passes cleanly against the physical device environment.
Key findings recorded here for future reference and for the next firmware update.

**Package tag format**
- The `home-assistant-voice-pe` repo uses the short year format: `26.x.x` (e.g. `26.4.0`),
  **not** `2026.x.x`. The installed ESPHome CLI uses the long year format (`2026.x.x`).
  These are different namespaces and must not be confused when updating either.
- `26.4.0` is the current latest release tag (as of 2026-06-03).

**ESPHome CLI version must match the package's `esphome-version:`**
- The package file `home-assistant-voice.yaml@26.4.0` declares `esphome-version: 2026.3.1`.
  The CLI version must match this. Running a newer CLI (e.g. `2026.5.2`) causes a Python
  import error: the package pulls ESPHome core at commit `ff8ce89` (= `2026.3.1`) into the
  `.esphome/external_components/` cache, and the newer CLI's modules try to import symbols
  that don't exist in that older cached version (`CONF_B_CONSTANT` etc.).
- **Rule:** when upgrading ESPHome CLI, first check `esphome-version:` in the pinned package.
  Only upgrade the CLI to a version that has a matching `26.x.x` package release.
- When changing the package tag or substitutions, always clear the cache first:
  `rm -rf devices/ha-voice-pe/.esphome/`

**Confirmed mic/speaker IDs (package `@dev` / `26.4.0`)**

Note: `compile` always updates the package cache to `@dev` (via transitive sub-package
references inside `home-assistant-voice.yaml@26.4.0`). `config` uses the last fetched cache,
which may differ. IDs below are confirmed against `@dev` (the version that compiles):

- Microphone: `i2s_mics` ✓ (`@dev`; `va_mic` only existed in the `@26.4.0` cached state)
- Speaker: `i2s_audio_speaker` ✓
- `mixing_speaker` exists but is `mixer_speaker::MixerSpeaker` — does **not** inherit from
  `speaker::Speaker`. Our component's `set_speaker()` requires the base type; `mixing_speaker`
  is rejected at config-validation time with a clear type mismatch error. Use `i2s_audio_speaker`
  (the raw I2S hardware speaker which IS a `speaker::Speaker`).
- To re-verify IDs after a package update: `esphome config … 2>&1 | grep -E '^\s+id:' | sort -u`
  (do NOT use `2>/dev/null` — errors about IDs appear on stdout AND stderr)

**ESPHome Action API — confirmed correct signatures**

From `external_components/46ce801d/esphome/core/automation.h` (ESPHome `ff8ce89`, used by the build):
- `Action<Ts...>::play` is pure virtual with signature: `virtual void play(const Ts &...x) = 0;`
- Override must use **`const Ts &...x`** (const reference pack), not `Ts... x` (by value) — the
  signatures look similar but are distinct; the wrong one compiles as a new method, not an
  override, leaving the class abstract.
- `play_complex(const Ts &...x)` is the non-pure-virtual default (calls `play` then `play_next_`) — no need to override it for simple synchronous actions.

**Successful compile — `[SUCCESS]` (2026-06-03)**

`esphome compile devices/ha-voice-pe/espHome.yaml` completes cleanly.
All warnings are from `espressif__esp-tflite-micro` (TFLite, third-party) — not our component.
Build environment: ESPHome 2026.3.1, ESP-IDF 5.5.3, xtensa-esp-elf 14.2.0, ESP32-S3.

**First flash — OTA, aber `--device <IP>` erforderlich (2026-06-03)**
- Das HA Voice PE hat keinen USB-Port; alles läuft per WiFi OTA.
- **Erster Flash braucht `--device <IP>`**, weil der mDNS-Name sich durch den Flash ändert:
  - Vor dem Flash: `home-assistant-voice-09e9cd.local` (MAC-basierter OEM-Standardname)
  - Nach dem Flash: `ha-voice-pe-buero.local` (aus `name:` in `substitutions:`)
  - ESPHome versucht beim `run` automatisch `ha-voice-pe-buero.local` — das scheitert, weil das
    Gerät noch unter dem alten Namen läuft.
  - Fix: `esphome run devices/ha-voice-pe/espHome.yaml --device <aktuelle-IP>`
  - IP aus Fritz-Box: Heimnetz → Netzwerk → Gerät `home-assistant-voice-09e9cd`.
  - Büro-Gerät: **192.168.178.146**. DHCP-Reservation anlegen damit die IP stabil bleibt.
- Folge-Flashes: `esphome run … --device 192.168.178.146` (oder `--device ha-voice-pe-buero.local`)
- ESPHome API-Log zeigt `RequiresEncryptionAPIError` → dann `Successfully connected`:
  Erste Verbindung schlägt verschlüsselt fehl, ESPHome fällt auf Fallback zurück — nicht blockierend.
  Die Encryption kommt aus dem Package-Merge (das Package setzt `api: encryption:`), nicht aus
  unserem YAML. Für `esphome logs` Key aus HA holen: Einstellungen → Geräte & Dienste →
  ESPHome → `ha-voice-pe-buero` → Neu konfigurieren. Alternativ neuen Key generieren:
  `python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"`,
  in `secrets.yaml` als `api_encryption_key:` eintragen und HA Neu konfigurieren.

**micro_wake_word: Konflikt mit Package-Models (2026-06-03)**
- Das Package `@dev` deklariert `micro_wake_word` (id: `mww`) bereits mit vier Modellen:
  `okay_nabu`, `hey_jarvis`, `hey_mycroft`, `stop`.
- Wenn das eigene YAML zusätzlich `models:` deklariert, merged ESPHome beide Listen → doppelte
  Einträge → `micro_wake_word` initialisiert zur Laufzeit nicht → keine Wake-Word-Events,
  keine Logs, HA zeigt "Kein Aktivierungswort".
- **Regel:** Niemals `models:` in `micro_wake_word:` deklarieren — nur `on_wake_word_detected:`
  überschreiben. Das Package bringt alle benötigten Modelle mit.

**on_wake_word_detected: vollständiger Override (2026-06-03)**
- Wir überschreiben den Handler vollständig (User-Config hat Vorrang vor Package-Config).
- `hey_jarvis` → direkt `wyoming_satellite.start` (bypasses HA).
- Alle anderen Wake Words → Package-Logik exakt kopiert:
  Mute-Check (`master_mute_switch`) → Timer-Check (`timer_ringing`) →
  Voice-Assistant-laufend-Check → Media-Player-Announcement-Check →
  Wake-Sound (`play_sound` + 300 ms Delay) → `voice_assistant.start`.
- Quelle des kopierten Handlers: `.esphome/packages/0ec35b30/home-assistant-voice.yaml`
  (Package `@dev`, gecacht am 2026-06-03).

**HA steuert micro_wake_word — Wake Words müssen in HA aktiviert sein (2026-06-03)**
- ESPHome's Voice-Satellite-Pattern: HA schickt beim Verbinden den Befehl ob `micro_wake_word`
  läuft oder pausiert. Wenn HA "Kein Aktivierungswort" konfiguriert hat, hört das Gerät auf
  keine Wakewords — unabhängig vom Firmware-Code.
- Nach einem Reflash setzt HA die Wake-Word-Konfiguration für das Gerät zurück.
- **Fix nach jedem Reflash:** HA → Einstellungen → Sprachassistenten (oder Geräte & Dienste →
  ESPHome → Gerät) → Wake Words für `ha-voice-pe-buero` aktivieren.
- Dies gilt für ALLE Wakewords — auch `hey_jarvis` ist erst aktiv wenn HA es freigibt.

**Aktueller Stand Büro-Gerät (2026-06-03)**
- Gerät: `ha-voice-pe-buero`, IP: `192.168.178.146`
- Custom Firmware compiliert (ESPHome 2026.3.1) und geflasht ✓
- DHCP-Reservation für 192.168.178.146 in Fritz-Box noch ausstehend
- Wake Words in HA nach Reflash deaktiviert → **müssen neu aktiviert werden** (Blocker)
- `wyoming_satellite`-Routing nach Wake-Word-Aktivierung noch nicht getestet
- device-mapping.yaml auf dem Gateway für 192.168.178.146 noch nicht eingetragen

**Nächste Schritte (in dieser Reihenfolge)**
1. Wake Words in HA aktivieren (HA → Sprachassistenten → `ha-voice-pe-buero`)
2. DHCP-Reservation für 192.168.178.146 in Fritz-Box setzen
3. `device-mapping.yaml` auf dem Gateway eintragen + Gateway neu starten:
   ```yaml
   devices:
     "192.168.178.146":
       user_id: "<alice user_id>"
       name: "Büro HA Voice PE"
       room: "Büro"
   ```
   `ssh stan@ki.lan 'docker restart alice-speech-gateway'`
4. "Hey Jarvis" sprechen → Gateway-Log prüfen: `Wyoming session start` für 192.168.178.146
5. "Okay Nabu" sprechen → HA Assist antwortet normal
6. Logs richtig verbinden (api_encryption_key in secrets.yaml)

## QA Test Results

**QA Date:** 2026-06-02
**Tester:** QA Engineer (red-team)
**Build under test:** branch `feature/PROJ-42-home-assistant-voice-integration` (working tree)
**Automated suite:** `alice-speech-gateway/.venv/bin/pytest -q` → **50 passed**

### Test Method & Constraints

This is a Docker/Python + firmware-config feature. The **gateway side** was tested via
the existing pytest suite and code review. The **device side** (ESPHome firmware) could
**not** be built or flashed — it requires the real HA Voice PE hardware, the upstream
Nabu Casa package, and a custom `wyoming_satellite` component that is **not present in the
repo**. Full end-to-end (mic → STT → chat-stream → Piper → speaker) was not run: no GPU /
no live `alice-chat-stream` / no device in this environment. ACs depending on those are
marked **UNVERIFIED (hardware/stack required)** rather than PASS.

### Acceptance Criteria

#### ESPHome-Konfiguration (HA Voice PE)
| # | Criterion | Result |
|---|---|---|
| 1 | YAML exists at `devices/ha-voice-pe/espHome.yaml` | **PASS** — file present |
| 2 | "Hey Jarvis" → direct Wyoming to gateway, bypassing HA | **FAIL** — see BUG-1: references missing `external_components/wyoming_satellite`; YAML cannot compile/flash as committed |
| 3 | "Okay Nabu" → HA Assist, unchanged, parallel | **UNVERIFIED** — see BUG-6: full `micro_wake_word:` re-declaration may conflict with upstream package; needs hardware build to confirm |
| 4 | Device stays visible in HA (entities, LED, volume, events) | **UNVERIFIED** — `api:`/`ota:` retained; needs hardware |
| 5 | Inline firmware-update procedure block | **PASS** — detailed block present (lines 34-56) |

#### Gateway — Wyoming Satellite Endpunkt
| # | Criterion | Result |
|---|---|---|
| 6 | Endpoint (10302) accepts direct device connections | **PASS** — binds `0.0.0.0:10302`, PROJ-40 |
| 7 | Device identified by source IP via `device-mapping.yaml` | **PASS** — `_client_ip` lookup; covered by tests |
| 8 | Unknown source IP → spoken German error + connection ends | **PARTIAL** — spoken error PASS (tested); connection not actively closed, ends only via 30 s silence timeout (BUG-4) |
| 9 | Full pipeline STT→chat-stream→Piper→audio | **UNVERIFIED (stack)** — correct by design/unit tests; no live e2e |
| 10 | TTS sentence-level streaming preserved | **PASS** (by design) — pipeline parallelism unchanged from PROJ-40 |

#### Device-Mapping (Konfiguration)
| # | Criterion | Result |
|---|---|---|
| 11 | Arbitrary entries with `ip`, `user_id`, `name`, `room` | **PASS** — covered by `test_load_device_mapping_*` |
| 12 | New device = YAML entry only, no code change | **PASS** — loader is generic |
| 13 | Changes picked up on gateway restart | **PASS** — loaded at startup (`main.py` lifespan); documented |

#### Continued Conversation
| # | Criterion | Result |
|---|---|---|
| 14 | Session stays open after TTS, no re-wakeword | **PASS** — `test_continued_conversation_two_turns` |
| 15 | Session ends after 30 s silence | **PASS** — `test_silence_timeout_between_turns_ends_session` |
| 16 | Session ends immediately on `conversation_end` | **PASS** — `test_conversation_ended_signal_stops_after_one_turn` |
| 17 | Read-only queries do NOT trigger `conversation_end` | **PASS (design)** — gateway honours the signal; emission is alice-chat-stream's job |
| 18 | On session end, device returns to wakeword mode | **UNVERIFIED** — device-side firmware behaviour (also blocked by BUG-1) |

#### Fehlerbehandlung
| # | Criterion | Result |
|---|---|---|
| 19 | STT / AI-timeout / TTS error → spoken German error | **PASS** — `pipeline.run_turn` maps each to a `SPEECH_ERRORS` message |
| 20 | <0.5 s audio OR empty transcript → "Ich habe nichts verstanden, bitte wiederhole das." | **PARTIAL** — empty transcript PASS; <0.5 s audio speaks `audio_too_short` ("Die Aufnahme war zu kurz…"), not the AC text (BUG-3) |
| 21 | Gateway down → device silent on "Hey Jarvis", no crash, "Okay Nabu" intact | **UNVERIFIED** — device-side firmware behaviour (also blocked by BUG-1) |

**Summary:** 12 PASS · 1 FAIL · 3 PARTIAL · 5 UNVERIFIED (hardware/stack)

### Bugs

**BUG-1 — ESPHome config references a custom component that doesn't exist (High)** — **IN PROGRESS (authored + compiled; Wake-Word-Test ausstehend)**
`espHome.yaml` declares `external_components: [wyoming_satellite]` from local `path: components`,
but `devices/ha-voice-pe/components/` did not exist in the repo. The "Hey Jarvis → Alice"
path — the primary deliverable of this feature — could not compile or flash as committed.
*Repro:* `esphome compile devices/ha-voice-pe/espHome.yaml` → unresolved `wyoming_satellite`.
*Fix:* authored the `wyoming_satellite` ESPHome external component (`__init__.py` codegen +
`wyoming_satellite.h/.cpp`): a Wyoming protocol TCP client that streams mic audio to the gateway
on port 10302, plays back TTS, and loops for continued conversation with an on-device energy VAD.
Fixed the YAML `microphone:`/`speaker:` blocks (the `!extend` misuse → plain id references via
`mic_id`/`speaker_id` substitutions) and added VAD tunables. Build/flash procedure documented in
`devices/ha-voice-pe/README.md`; version-sensitive spots in the component's `README.md`.
**Still requires the physical HA Voice PE to compile + flash** — the component is authored but
not hardware-verified (no device/ESPHome toolchain in this environment). AC #2/#18/#21 remain
hardware-blocked until that bring-up runs.

**BUG-2 — Service token expires mid-conversation on long sessions (Medium)** — **FIXED**
`wyoming_transport._conversation_loop` minted the RS256 service token **once** at session start
(`_service_token_for(device.user_id)` inside the `pipeline is None` block) and reused it for
every turn. `SERVICE_JWT_TTL_SECONDS` defaults to **120 s** (`service_token.py:29`). A read-only
continued conversation that stays open (up to 30 s silence per turn) easily exceeds 120 s; the
next turn then sent an expired token to alice-chat-stream → 401 → `ChatError` → the user heard
"Bei der Verarbeitung ist ein Fehler aufgetreten." mid-conversation.
*Fix:* the Wyoming loop now re-mints the service token at the **start of every turn**
(`VoicePipeline.set_jwt()`), so each turn — which always completes well within the TTL — uses a
fresh token. The WebApp WS path keeps its client-supplied token unchanged. Regression test:
`test_service_token_reminted_each_turn` (suite: 51 passed).

**BUG-3 — Wrong error phrase for <0.5 s audio (Low)**
AC #20 requires "Ich habe nichts verstanden, bitte wiederhole das." for both the empty-transcript
and the <0.5 s audio case. The code speaks `SPEECH_ERRORS["audio_too_short"]` ("Die Aufnahme war
zu kurz, bitte sprich etwas länger.") for <0.5 s (`wyoming_transport.py:112-114`). Functionally
reasonable (arguably clearer), but does not match the spec text.

**BUG-4 — Unknown-IP connection is not actively closed (Low)**
On unknown source IP the loop speaks the error and `continue`s, re-speaking it on every audio
block until the 30 s silence timeout. AC #8 says "die Verbindung wird beendet". The connection
ends only passively via timeout, not by an explicit close after the error.

**BUG-5 — Stale module docstring (Low, doc-only)**
`wyoming_transport.py:2` says the endpoint is "on port 10300 (Mode 3)" and "Replaces the
wyoming-whisper container", contradicting the actual port **10302** and the parallel-operation
design (`main.py:5`, compose, and spec — wyoming-whisper stays on 10300 for HA). Pre-existing
from PROJ-40, in a file this feature edited.

**BUG-6 — ESPHome `micro_wake_word:` may conflict with upstream package (Low / Risk)**
The YAML re-declares the entire `micro_wake_word:` block (full `models:` list +
`on_wake_word_detected:`) on top of the official Nabu Casa package, which already configures it.
ESPHome package list-merge could duplicate the `okay_nabu` model or fail to override the
package's existing handler. Also assumes `va_mic`/`va_speaker` are the real package IDs.
Unverifiable without compiling against the pinned package on hardware.

### Security Audit (Red Team)

- **No JWT on the Wyoming endpoint — by design.** Identity is the TCP source IP, which the
  gateway maps to a `user_id` and then **mints a full `role: user` RS256 token** for. Anyone able
  to reach port 10302 *from a mapped IP* gets full chat access as that user, with no second
  factor. Accepted tradeoff for a VPN-only deployment (documented in the spec), but it means
  source-IP spoofing inside the trusted network = account takeover.
- **Port exposure wider than documented (Medium).** `compose.yml:19` publishes `10302:10302`,
  which binds on all host interfaces (`0.0.0.0`), yet `wyoming_transport.py` claims the port is
  "only reachable inside the Docker network." If the host has any non-VPN interface (e.g. LAN),
  10302 is reachable from the LAN, weakening the VPN-only assumption that justifies skipping auth.
  *Recommendation:* bind to the VPN/loopback interface (`<vpn-ip>:10302:10302`) or enforce a host
  firewall rule; verify before deploy.
- **Private key mount.** `jwt_private.pem` is mounted read-only and used only for service-token
  minting; the Wyoming path self-disables if the key is absent (`service_token.wyoming_enabled()`).
  Reasonable containment. No secrets found in logs (logs carry device name/room/IP, not tokens).
- **Service-token TTL** is short (120 s) — good for limiting replay; the flip side is BUG-2.

**Verdict:** No new critical injection/authz vulnerabilities in the gateway code. The IP-as-auth
model is an accepted, documented design risk; the port-binding discrepancy (Medium) should be
closed before production exposure.

### Regression

- Full gateway suite green (50 passed) — WebApp WS transports (PROJ-40/41), config loaders,
  continued-conversation loop all unaffected by the `Device` dataclass change.
- `load_device_mapping` return-type change (`dict[str,str]` → `dict[str,Device]`) has only two
  consumers (`main.py`, `wyoming_transport.py`), both updated. No other callers.
- Old flat `IP: "uuid"` mapping format is now rejected (logged + skipped, not a crash) —
  intentional per implementation notes; covered by `test_load_device_mapping_skips_non_mapping_entry`.

### Production-Ready Decision: **NOT READY**

The gateway-side changes (device-mapping format, IP identification, logging) are solid and fully
tested. However the feature's core deliverable — the "Hey Jarvis → Alice" firmware path — is
**not functional as committed** (BUG-1: missing `wyoming_satellite` component), so the primary
user story cannot be exercised. BUG-2 (token expiry) breaks the continued-conversation AC on
longer sessions. The port-binding security gap should also be resolved.

**Blocking:** BUG-1 (High). **Should-fix before deploy:** BUG-2 (Medium), port-binding (Medium).
**Nice-to-have:** BUG-3/4/5/6 (Low).

## Hardware Bring-Up Findings (2026-06-08 to 2026-06-10)

Full end-to-end testing on the physical HA Voice PE (192.168.178.146, Büro) uncovered a series
of bugs in both the ESPHome component and the gateway. All are fixed. Notes below are ordered
chronologically and serve as reference for future hardware iterations.

### Hardware Specifics (Confirmed)

**I2S microphone format**
- The XMOS mic array delivers **32-bit stereo** PCM at 16 kHz: 8 bytes per sample pair
  (4 bytes left + 4 bytes right, little-endian, MSB-justified).
- `raw_bytes/frame = 2048`, `pcm16_bytes/frame = 512` (after conversion to mono 16-bit).
- Conversion: `s32 >> 16` extracts bits 31–16 as a signed 16-bit sample. RMS threshold `is_silent_()`
  works correctly on this representation — room noise typically < 300, speech > 700 RMS.
- One DMA buffer = 16 ms of audio at 16 kHz. The diagnostic log prints every 100 frames (~1.6 s).

**Rate constants — critical distinction**
- `MIC_SAMPLE_RATE = 16000` — declared in AudioStart/AudioChunk events sent to the gateway.
  Whisper uses this to build the WAV header.
- `SAMPLE_RATE = 48000` — speaker-only. The `i2s_audio_speaker` is configured at 48 kHz
  so TTS audio plays without the mixer-chain startup delay (~6 s overhead avoided).
  Must NOT be used in mic format declarations.

**Speaker at 48 kHz**
- Using `i2s_audio_speaker` directly bypasses `mixing_speaker`, which requires a separate
  mixer task and introduces a ~6 s first-play latency due to the `speaker_mixer` chain setup.
- Gateway resamples Piper output (22 050 Hz) to 48 kHz before sending.

**XMOS AEC**
- The XMOS chip's Acoustic Echo Cancellation suppresses the speaker signal from the mic.
  Rate-limiting TTS delivery (pacing at real-time 48 kHz) further reduces self-conversation
  risk by ensuring the speaker fully drains before the mic re-arms for the next turn.

---

### Bug Fixes (BUG-7 to BUG-15)

**BUG-7 — Audio playback too fast and choppy (High) — FIXED**
`_SAMPLE_RATE = 16000` in `wyoming_transport.py` while TTS audio from Piper was 48 kHz.
`_BYTES_PER_SEC = 32000` → rate limiter slept 128 ms per 42 ms of audio → 3× underrun gaps
between chunks → audio played back in broken bursts.
*Fix:* `_SAMPLE_RATE = 48000`, `_BYTES_PER_SEC = 96000 B/s`. The sleep between 4 KB chunks
now matches actual I2S playback speed at 48 kHz.

**BUG-8 — STT transcribes garbage (High) — FIXED**
`audio_format_json()` returned `rate: 48000` (using `SAMPLE_RATE`, the speaker constant)
instead of the actual mic capture rate of 16 kHz. The gateway's `_pcm_to_wav()` wrapped the
audio in a WAV header claiming 48 kHz. Whisper saw 192 000 bytes ÷ 96 000 B/s = 2 s of audio
(real duration: 6 s) → audio was compressed 3× → garbage transcripts (e.g. "Bis zum nächsten
Mal." for "Licht im Büro ausschalten").
*Fix:* Added `MIC_SAMPLE_RATE = 16000` constant in `wyoming_satellite.h`. `audio_format_json()`
now uses `MIC_SAMPLE_RATE`. Comment in the `.cpp` explains why `SAMPLE_RATE` must not be used
here. STT is now correct.

**BUG-9 — Device stuck in AWAIT_RESPONSE forever (High) — FIXED**
After the conversation loop finished, `_conversation_loop` exited without closing the TCP
writer. The device remained in `AWAIT_RESPONSE` calling `read_socket_()` each loop tick,
never getting EOF, never returning to IDLE. Subsequent "Hey Jarvis" triggers were silently
ignored (device not in IDLE, `start()` returned immediately).
*Fix:* `_conversation_loop` calls `self.writer.close()` / `await self.writer.wait_closed()`
after the while loop exits. `handle_event()` returns `False` (signals Wyoming server to close
the connection) if `_loop_task.done()`.

**BUG-10 — Wake word detection dead after session (High) — FIXED**
`end_utterance_()` calls `mic_->stop()` to free the shared I2S bus for the speaker.
`finish_session_()` left the mic stopped. `micro_wake_word` receives audio only when the
mic is running; with the mic stopped it never detects the next "Hey Jarvis". Device had to
be rebooted to recover.
*Fix:* `finish_session_()` calls `mic_->start()` as its last action after `set_state_(IDLE)`.
The mic restarts in RX mode (speaker has already stopped), `micro_wake_word` resumes.

**BUG-11 — Infinite silence loop (Medium) — FIXED**
When Whisper's VAD removed all audio (genuine room silence sent during a continued-conversation
turn), the gateway spoke "Ich habe nichts verstanden" and re-entered `_collect_audio()` for
another turn. The device rearmed → sent more silence → loop. Session never ended.
*Fix:* `pipeline.run_turn()` returns `PipelineResult(no_speech=True)` on empty transcript
(and speaks the error on turn 1 only — see BUG-15). `_conversation_loop` breaks the loop on
`result.no_speech`.

**BUG-12 — HA commands don't end session immediately (Medium) — FIXED**
User story: "Licht im Büro ausschalten → session endet sofort." `streaming.py` never emitted
`conversation_end` after HA tool execution. The gateway saw `conversation_ended=False`,
re-armed the mic, waited 6 s of silence, spoke "Ich habe nichts verstanden", only then ended.
*Fix:* At end of `stream_chat()` in `streaming.py`, if any `home_assistant` tool appeared in
`tool_call_log`, emit `{"type":"conversation_end"}` before `done` and `[DONE]`. The gateway
sets `result.conversation_ended=True` → breaks after the TTS confirmation plays.
TCP close propagates to the device within ~20 ms — well before the 400 ms re-arm delay — so
the device never enters the second turn.

**BUG-13 — `WHISPER_COMPUTE_TYPE=float16` fails on TITAN X GPU (Medium) — FIXED**
CTranslate2 `float16` and `int8_float16` both fail on Maxwell architecture (TITAN X).
`int8` lowers accuracy. `default` auto-selects the best compute type: loads `large-v3` at
~7 600 MiB, correct transcription.
*Fix:* `config.py` default changed from `"float16"` to `"default"`. Comment explains the
Maxwell constraint. Set `WHISPER_COMPUTE_TYPE=int8` in `.env` to trade accuracy for ~2 GB
VRAM if needed.

**BUG-14 — Silence detection bypassed — always waits full 6 s (Medium) — FIXED (2026-06-10)**
The CAPTURE loop checked only `listen_timeout_ms` (6 000 ms). On-device VAD (`is_silent_()`)
was intentionally bypassed in an earlier version because the raw 32-bit I2S input fooled the
16-bit RMS calculation. After the correct stereo→mono conversion (BUG-8 fix), the PCM16
data is valid for RMS threshold evaluation.
*Fix:* `on_mic_data_()` now calls `is_silent_()` on each converted PCM chunk and updates
`last_voice_ms_` / `speech_seen_`. `loop()` CAPTURE case: if `speech_seen_` AND
`millis() - last_voice_ms_ > silence_ms_` (900 ms default), ends the utterance immediately.
`listen_timeout_ms` (6 s) is kept as a fallback for the no-speech-at-all case.
`start()` now initialises `speech_seen_=false` (was `true`, which would have triggered
silence detection before the user spoke).
Practical result: "Licht im Büro ausschalten" ends ~900 ms after the last syllable rather
than after the full 6 s timeout.

**BUG-15 — "Ich habe nichts verstanden" spoken at end of every session (Low) — FIXED (2026-06-10)**
After BUG-12 was fixed (HA commands close session via `conversation_end`), a continued-
conversation silence on non-HA queries still triggered "Ich habe nichts verstanden" before
ending. This message is appropriate after an accidental wake word with no speech (turn 1),
but not when the user simply stays quiet after an exchange.
*Fix:* `run_turn()` gains `speak_on_empty: bool = True`. `_conversation_loop` tracks
`turn_count`; passes `speak_on_empty=(turn_count == 1)`. Turn 1 (after wake word): error
spoken. Turn 2+ (continued conversation, silence): session ends silently. 53 gateway
tests pass.

---

### Infrastructure Issue — DMS queries return `ai_failed`

**Root cause:** `ollama-3090` Docker container was not running → nginx at
`ollama3090.happy-mining.de` returned 502 Bad Gateway for `/api/chat` (backend unreachable).
HA commands still worked because `ha_path.decide_path()` takes the fast-path (Weaviate →
HA REST), bypassing Ollama entirely. DMS/document queries always require the LLM.
**Fix:** `docker start ollama-3090` (or `docker compose up -d` in the ollama service dir).
No code changes needed.

**Relevant config:**
- `ollama-3090.conf`: `location / → http://ollama-3090:11434/` ✓
- `alice-chat-stream/.env`: `OLLAMA_URL=https://ollama3090.happy-mining.de` ✓ (goes through this nginx)

---

### Acceptance Criteria — Updated Status (2026-06-10)

All previously-blocked ACs are now verified or unblocked:

| # | Criterion | Result |
|---|---|---|
| 1 | YAML at `devices/ha-voice-pe/espHome.yaml` | **PASS** |
| 2 | "Hey Jarvis" → direct Wyoming to gateway | **PASS** — component authored, compiled, flashed, hardware-verified |
| 3 | "Okay Nabu" → HA Assist, parallel | **PASS** — micro_wake_word models come from package; handler override correct |
| 4 | Device stays visible in HA | **PASS** — API/ESPHome integration intact |
| 14 | Session stays open after TTS, no re-wakeword | **PASS** |
| 15 | Session ends after 30 s silence | **PASS** |
| 16 | Session ends immediately on `conversation_end` | **PASS** — BUG-12 fixed; HA commands verified |
| 18 | Device returns to wakeword mode on session end | **PASS** — BUG-9/BUG-10 fixed |

---

### Current State (2026-06-10)

| Component | State |
|---|---|
| `wyoming_satellite` component | Hardware-verified. Silence detection (BUG-14) fix requires reflash. |
| `alice-speech-gateway` | All fixes (BUG-7 to BUG-15) in code; needs `docker compose up --build -d`. |
| `alice-chat-stream` | `conversation_end` for HA commands in code; needs `docker compose up --build -d`. |
| `ollama-3090` container | Must be running for LLM queries (DMS, general). |
| `device-mapping.yaml` | Büro device (192.168.178.146) must be entered. |
| DHCP reservation | 192.168.178.146 must be reserved in Fritz-Box. |

**Pending deploy commands:**
```bash
esphome run devices/ha-voice-pe/espHome.yaml --device 192.168.178.146   # BUG-14 VAD fix
docker compose up --build -d alice-speech-gateway alice-chat-stream      # BUG-12/15
ssh stan@ki.lan 'docker start ollama-3090'                               # DMS queries
```

**Remaining known issues (all Low/cosmetic):**
- BUG-3: `audio_too_short` message text doesn't match spec ("Die Aufnahme war zu kurz" vs
  "Ich habe nichts verstanden") — functionally clearer, not worth changing.
- BUG-4: Unknown-IP connection ends via 30 s timeout, not immediately after spoken error —
  minor UX gap.
- BUG-5: Stale docstring in `wyoming_transport.py` line 5 (port 10300 → 10302).
- Emoji in LLM response: Piper speaks "Lächelndes Gesicht mit lachenden Augen" for 😊 —
  cosmetic; LLM prompt tuning would prevent this.
- "Parent I2S bus not free" at TTS start: 1-second retry, resolves itself. Occurs only
  if mic and speaker transitions overlap. Rare after session cleanup fixes (BUG-9/10).

## QA Re-Test (2026-06-15)

**Tester:** QA Engineer (red-team) · **Build:** branch `feature/PROJ-41-webapp-voice-interface` (contains PROJ-42 commit `c41d830` + hardware-bring-up fixes)
**Automated suite:** `alice-speech-gateway/.venv/bin/pytest -q` → **67 passed** (was 50/53 in prior rounds — net new regression tests).

### Scope
Re-test verifies that the BUG-1…BUG-15 fixes documented in the 2026-06-10 hardware bring-up are present in the current working tree and that the suite is green. Live hardware (HA Voice PE) and the GPU/STT/chat-stream stack were **not** re-exercised in this environment; ACs that were hardware-verified on 2026-06-10 are carried forward as PASS.

### Fix Verification (code-level)
| Bug | Sev | Claimed fix | Verified in code |
|---|---|---|---|
| BUG-1 | High | `wyoming_satellite` component authored/compiled/flashed | **PASS** — `devices/ha-voice-pe/components/wyoming_satellite/` present |
| BUG-2 | Med | Service token re-minted per turn | **PASS** — `set_jwt()` per turn; `test_service_token_reminted_each_turn` |
| BUG-7 | High | Speaker rate 48 kHz | **PASS** — `_SAMPLE_RATE=48000`, `_BYTES_PER_SEC=96000` (`wyoming_transport.py:38,45`) |
| BUG-8 | High | Mic declares 16 kHz | **PASS** — `MIC_SAMPLE_RATE` used in `audio_format_json()` (firmware) |
| BUG-9 | High | Writer closed after loop | **PASS** — `writer.close()/wait_closed()` (`wyoming_transport.py:183-184`) |
| BUG-10 | High | Mic restarted in `finish_session_` | **PASS** — `mic_->start()` (`wyoming_satellite.cpp:465`) |
| BUG-11 | Med | Break on empty transcript | **PASS** — `PipelineResult(no_speech=True)` (`pipeline.py:157`) |
| BUG-12 | Med | `conversation_end` after HA tool | **PASS** — gated on `tc.tool=="home_assistant"` (`streaming.py:363-364`) |
| BUG-13 | Med | `WHISPER_COMPUTE_TYPE=default` | **PASS** — `config.py:44` |
| BUG-14 | Med | On-device VAD silence cut | **PASS** — `is_silent_`/`speech_seen_`/`silence_ms_` (`wyoming_satellite.cpp:69-71,164-166`) |
| BUG-15 | Low | Suppress "nichts verstanden" turn 2+ | **PASS** — `speak_on_empty=(turn_count==1)` (`wyoming_transport.py:154`) |

**All Critical/High and all Medium gateway bugs are resolved and present in code.**

### Still Open (carried forward)
| Bug | Sev | Status |
|---|---|---|
| Port binding `10300:10300` on `0.0.0.0` | **Medium (security)** | **OPEN** — `compose.yml` binds all host interfaces. If the host has any non-VPN/LAN interface, the no-auth Wyoming endpoint is LAN-reachable. Accepted for VPN-only deployment; harden with host firewall if exposure changes. |
| BUG-3 | Low | **WONTFIX (accepted)** — `audio_too_short` speaks "Die Aufnahme war zu kurz…" not the AC text; judged functionally clearer on 2026-06-10. |
| BUG-4 | Low | **OPEN** — unknown IP: `_speak_error` + `continue` (`wyoming_transport.py:108-109`); connection ends via timeout, not active close. |
| BUG-5 | Low (doc) | **FIXED** — `wyoming_transport.py` docstring rewritten (2026-06-15): now correctly states port 10300 and the actual role of the transport. |

### Regression
Full gateway suite green (67 passed). No regressions in WebApp WS path, config loaders, or continued-conversation loop.

### Production-Ready Decision: **READY**
No Critical or High bugs remain. BUG-4 (Low) and BUG-3 (accepted) are non-blocking. BUG-5 fixed. Port binding (Medium) accepted for VPN-only deployment.

## Deployment

**Deployed:** 2026-06-15

### Port migration 10302 → 10300 (2026-06-15)

The Wyoming endpoint was moved from port 10302 to port 10300 — reclaiming the standard Wyoming port after the `wyoming-whisper` container was removed in PROJ-40.

**Files changed:**
- `compose.yml` — port mapping updated
- `app/config.py` + `.env.example` — `WYOMING_PORT` default updated
- `app/main.py` + `app/wyoming_transport.py` — docstrings corrected (closes BUG-5)
- `devices/ha-voice-pe/espHome.yaml` — `alice_gateway_port` substitution updated
- `devices/ha-voice-pe/components/wyoming_satellite/wyoming_satellite.h` — default port updated
- Component READMEs and comments updated

**Deployed via:**
1. `./scripts/sync-compose.sh` — synced compose + `.env.example` to server
2. Server `.env` updated: `WYOMING_PORT=10302` → `10300`
3. `docker compose up -d` on server (container recreated; `restart` does not re-read `env_file`)
4. ESPHome firmware reflashed: `esphome run devices/ha-voice-pe/espHome.yaml --device 192.168.178.146`

**Verified:** `docker exec alice-speech-gateway cat /proc/net/tcp` shows port 10300 bound. Device connects successfully.
