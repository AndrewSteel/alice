# wyoming_satellite — ESPHome external component

A Wyoming protocol **TCP client** for ESPHome. On a `wyoming_satellite.start`
action it connects to the Alice speech gateway, streams one microphone utterance
(gated by an on-device energy VAD), plays back the TTS audio the gateway streams
in return, and loops for continued conversation until the user stays silent.

It is consumed by `devices/ha-voice-pe/espHome.yaml`. See that file and the
device-level `README.md` for the build/flash procedure.

## Config

```yaml
wyoming_satellite:
  id: alice_satellite
  host: "192.168.1.10"     # gateway IP (prefer an IP; lwip resolves names too)
  port: 10300
  microphone: va_mic       # id of a `microphone:` component (from the package)
  speaker: va_speaker      # id of a `speaker:` component (from the package)
  silence_threshold: 700   # RMS amplitude (0-32767) below which a frame = silence
  silence_ms: 900          # trailing silence that ends one utterance
  listen_timeout_ms: 8000  # no-speech silence that ends the session
```

Actions: `wyoming_satellite.start` (begin a session — bind to the "Hey Jarvis"
wake-word handler) and `wyoming_satellite.stop` (abort).

## Wire protocol

Audio is 16 kHz mono signed-16-bit PCM (matches the gateway). Each Wyoming event
is a JSON header line terminated by `\n`, optionally followed by a JSON `data`
object and a binary payload:

```
{"type":"audio-start","data_length":42}\n{"rate":16000,"width":2,"channels":1}
{"type":"audio-chunk","data_length":42,"payload_length":1024}\n{...}<1024 PCM bytes>
{"type":"audio-stop"}\n
```

Outbound (device→gateway): `audio-start` → `audio-chunk`* → `audio-stop`.
Inbound (gateway→device): same three, carrying the TTS reply.

## Build status (last verified: 2026-06-03)

Compiled successfully against ESPHome 2026.3.1 / ESP-IDF 5.5.3 / ESP32-S3.
`esphome compile devices/ha-voice-pe/espHome.yaml` → **SUCCESS**.

## API notes — confirmed against `ff8ce89` (ESPHome used by the build)

**Microphone callback:** `add_data_callback` takes `std::function<void(const std::vector<uint8_t>&)>`.
Raw PCM arrives as `uint8_t` bytes; the component reinterprets as `int16_t` for the RMS VAD.

**Action override:** `Action<Ts...>::play` signature is `virtual void play(const Ts &...x) = 0;`.
Must use `const Ts &...x` (const reference pack) — `Ts... x` (by value) does not match and
leaves the class abstract.

**Socket factory / connect:** Uses `socket::socket(domain, type, proto)` +
`Socket::connect(sockaddr*, socklen_t)` + `setblocking(false)`. If this fails in a future
ESPHome version, check `esphome/components/socket/socket.h`.

**`speaker::is_running()`:** `rearm_when_drained_()` waits for `is_running()` to return `false`
before re-opening the mic. If the speaker never reports `false` on a given hardware revision,
replace that check with a fixed post-TTS delay (e.g. 300 ms).

## Notes

- Header JSON is parsed with minimal string scanning (`json_int_`/`json_str_`),
  which is safe because the gateway emits compact machine JSON. It is **not** a
  general JSON parser — don't reuse it for arbitrary input.
- DNS uses lwip `getaddrinfo`; an IP literal avoids the dependency.
- Single session at a time; `start()` is a no-op while a session is active.
