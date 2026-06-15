# HA Voice PE — Alice "Hey Jarvis" firmware (PROJ-42)

This directory holds the **custom ESPHome firmware** for the Home Assistant
Voice PE so that:

- **"Hey Jarvis"** → streams straight to the Alice speech gateway
  (`wyoming_satellite` component, raw Wyoming TCP, **bypasses HA**).
- **"Okay Nabu"** → stock HA Assist, unchanged.

```
espHome.yaml                       # device config (dual wakeword)
components/wyoming_satellite/       # custom Wyoming TCP-client component (C++)
  ├─ __init__.py                    # ESPHome config schema + codegen
  ├─ wyoming_satellite.h / .cpp     # the component
  └─ README.md                      # version-sensitive build notes
```

> ⚠️ **This firmware is authored but has not been compiled or flashed** — that
> requires the physical HA Voice PE. Treat the first flash as a bring-up:
> expect to adjust the three `[VERSION]` spots noted in
> `components/wyoming_satellite/README.md` and to tune the VAD thresholds.

---

## What you need to do (precise procedure)

### 0. Prerequisites (once)

- A machine with the **ESPHome CLI** (`pip install esphome`, or the ESPHome
  Builder add-on in HA). Version should match the one the device currently runs
  — check **Settings → Add-ons → ESPHome** or `esphome version`.
- A `secrets.yaml` next to `espHome.yaml` (or your global ESPHome secrets) with:
  ```yaml
  wifi_ssid: "<your SSID>"
  wifi_password: "<your wifi password>"
  ```
- The HA Voice PE reachable on Wi-Fi, and a **USB-C cable** for the first flash
  (the very first flash of custom firmware must be over USB; afterwards OTA
  works).

### 1. Pin the upstream package

The `nabu_casa.voice_pe` package in `espHome.yaml` is pinned to `@main`. Change
it to the **release tag that matches the firmware currently on your device** so
an upstream change can't silently break the build:

```yaml
packages:
  nabu_casa.voice_pe: github://esphome/home-assistant-voice-pe/home-assistant-voice.yaml@2025.x.y
```

Find the tag at https://github.com/esphome/home-assistant-voice-pe/releases .

### 2. Set the gateway IP and verify the mic/speaker IDs

In `espHome.yaml` `substitutions:`

- `alice_gateway_host` → the **gateway's fixed IP** (the `ki.lan` host). Use an
  IP, not a hostname — the device may not resolve `.lan`/`.local` names.
- `alice_gateway_port` → `10300` (standard Wyoming port; wyoming-whisper container was removed).
- `mic_id` / `speaker_id` → must match the IDs the pinned package declares.
  Confirm them:
  ```bash
  esphome config devices/ha-voice-pe/espHome.yaml | grep -E 'id:.*(mic|speaker|media)'
  ```
  If they differ from `va_mic` / `va_speaker`, set the two substitutions
  accordingly. **No C++ change is needed** — only these two values.

### 3. Validate the config (no hardware needed)

```bash
esphome config devices/ha-voice-pe/espHome.yaml
```

This resolves the package + substitutions and surfaces schema errors early.
Fix any `wyoming_satellite` schema or ID errors here before compiling.

### 4. Compile

```bash
esphome compile devices/ha-voice-pe/espHome.yaml
```

If the C++ fails, jump to the `[VERSION]` notes in
`components/wyoming_satellite/README.md` — the likely culprits are the
microphone callback element type, the socket factory, or `speaker::is_running()`.

### 5. First flash (USB), then confirm both wakewords

```bash
esphome run devices/ha-voice-pe/espHome.yaml          # pick the USB port
```

Then, watch the **gateway logs** and the **device logs** in parallel:

```bash
# device logs
esphome logs devices/ha-voice-pe/espHome.yaml
# gateway logs (on the server)
ssh stan@ki.lan 'docker logs -f alice-speech-gateway'
```

Confirm:

| Say          | Expect on device logs                         | Expect on gateway logs            |
|--------------|-----------------------------------------------|-----------------------------------|
| "Okay Nabu"  | HA Assist starts (`voice_assistant`)          | *(nothing — HA path)*             |
| "Hey Jarvis" | `connecting to Alice gateway …`, `Utterance start` | `Wyoming session start` for this device's IP |

If "Hey Jarvis" connects but Alice says *"Dieses Gerät ist nicht bei Alice
registriert"*, the device IP isn't mapped — see step 7.

### 6. Tune the on-device VAD

Defaults are conservative. In `espHome.yaml` under `wyoming_satellite:`:

- `silence_threshold` (RMS, 0–32767): raise if a noisy room keeps the mic open;
  lower if quiet speech is cut off.
- `silence_ms`: trailing silence that ends one utterance (lower = snappier, but
  may clip slow speakers).
- `listen_timeout_ms`: how long the device keeps listening for a follow-up after
  Alice replies before returning to wake-word mode (continued conversation).

Re-flash over OTA after the first USB flash:
```bash
esphome run devices/ha-voice-pe/espHome.yaml --device <device-ip>
```

### 7. Map the device IP on the gateway

The gateway identifies the device by its **source IP**. Give the Voice PE a
**DHCP reservation** in your router, then add it to
`docker/compose/automations/alice-speech-gateway/config/device-mapping.yaml`:

```yaml
devices:
  "192.168.1.42":            # the Voice PE's reserved IP
    user_id: "<alice user uuid>"
    name: "Büro HA Voice PE"
    room: "Büro"
```

Restart the gateway to pick it up (`docker restart alice-speech-gateway`).

---

## Firmware-update procedure (recap)

A Voice PE OTA update **from Home Assistant** replaces the firmware and undoes
this custom config. To restore it: repeat steps 1–5 (re-pin the package tag,
re-validate, re-compile, re-flash). The inline procedure block at the top of
`espHome.yaml` has the short version.

## Known limitations (device side)

- **No barge-in:** the device only re-opens the mic *after* Alice finishes
  speaking (firmware can't echo-cancel its own TTS). Matches the spec.
- **Continued-conversation end is timeout-driven:** the gateway's internal
  `conversation_end` is not signalled back over Wyoming, so after a control
  command ("Licht aus") the device listens for `listen_timeout_ms` of silence,
  then returns to wake-word mode. A future enhancement could add a Wyoming event
  from the gateway to end the session immediately (gateway-side change).
