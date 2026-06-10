# HA Voice PE — ESPHome-Konfiguration und wyoming_satellite-Komponente

Dieses Dokument erklärt die Arbeitsweise des Home Assistant Voice PE Geräts mit der Custom-Firmware aus PROJ-42. Es beschreibt sowohl den Aufbau der `espHome.yaml` als auch die genaue Funktionsweise der C++-Komponente `wyoming_satellite`.

---

## espHome.yaml

### Packages-Basis

```yaml
packages:
  nabu_casa.voice_pe: github://esphome/home-assistant-voice-pe/home-assistant-voice.yaml@26.4.0
```

Das Gerät fährt nicht mit einer komplett selbst geschriebenen Config, sondern erweitert Nabu Casas offizielle HA Voice PE Firmware als *Package*. Dieses Package bringt alles mit:

- Den I2S-Mikrofon-Treiber (`i2s_mics`)
- Den I2S-Lautsprecher (`i2s_audio_speaker`, `mixing_speaker`)
- Das `micro_wake_word`-Component (id: `mww`) mit vier vortrainierten Modellen: `okay_nabu`, `hey_jarvis`, `hey_mycroft`, `stop`
- Das `voice_assistant`-Component (verbindet mit HA Assist)
- LED-Ring, Mute-Switch, Lautstärkeregelung, Button-Events

Die eigene YAML-Datei **überschreibt und ergänzt** selektiv Teile davon. ESPHome mergt beide Configs beim Kompilieren.

### Substitutions

```yaml
substitutions:
  mic_id: "i2s_mics"
  speaker_id: "i2s_audio_speaker"
  alice_gateway_host: "192.168.178.88"
  alice_gateway_port: "10302"
```

`mic_id` und `speaker_id` sind die IDs aus dem Package — sie werden direkt wiederverwendet, kein zweites I2S-Setup. Der Lautsprecher ist bewusst `i2s_audio_speaker` (Hardware-I2S, 48 kHz direkt) und **nicht** `mixing_speaker`. Der `mixing_speaker` würde durch den `speaker_mixer`-Chain einen ca. 6 s Anlaufverzug erzeugen und die ersten TTS-Frames verlieren.

### Die externe Komponente

```yaml
external_components:
  - source: {type: local, path: components}
    components: [wyoming_satellite]

wyoming_satellite:
  id: alice_satellite
  host: ${alice_gateway_host}
  port: ${alice_gateway_port}
  microphone: ${mic_id}
  speaker: ${speaker_id}
  silence_ms: 900
  listen_timeout_ms: 6000
```

Das ist der Kern: eine eigengeschriebene ESPHome-Komponente, die einen Wyoming TCP *Client* implementiert. Stock ESPHome `voice_assistant` kann das nicht — er spricht nur die HA Native API. Die Instanz heißt `alice_satellite` und bekommt Zugriff auf Mikrofon und Lautsprecher aus dem Package.

### Dual-Wakeword-Logik

```yaml
micro_wake_word:
  on_wake_word_detected:
    - if:
        condition:
          and:
            - lambda: 'return wake_word == "Hey Jarvis";'
            - switch.is_off: master_mute_switch
        then:
          - wyoming_satellite.stop: alice_satellite
          - voice_assistant.stop:
          - wyoming_satellite.start: alice_satellite
```

ESPHome **mergt** Automation-Trigger — er ersetzt sie nicht. Wenn "Hey Jarvis" erkannt wird, laufen daher **beide Handler** nacheinander:

**Package-Handler (läuft zuerst):** Startet `voice_assistant.start` → HA Assist

**Eigener Handler (läuft sofort danach):**
1. `wyoming_satellite.stop` — sicherer No-Op falls keine aktive Session
2. `voice_assistant.stop` — **bricht die eben gestartete HA Assist Session sofort ab**
3. `wyoming_satellite.start` — startet stattdessen Alice

Für alle anderen Wake Words (`okay_nabu`, `hey_mycroft`, `stop`) schlägt die `lambda`-Bedingung fehl → der `if`-Block tut nichts → nur der Package-Handler läuft normal durch.

---

## wyoming_satellite.cpp

### Zustandsautomat

Die Komponente läuft als ESPHome `Component` — `loop()` wird jeden Tick (~10 ms) aufgerufen. Der Ablauf folgt vier Zuständen:

```
IDLE → CONNECTING → CAPTURE → AWAIT_RESPONSE → CAPTURE → ... → IDLE
```

| Zustand | Bedeutung |
|---|---|
| `IDLE` | Kein aktives Session; Mikrofon läuft für `micro_wake_word` |
| `CONNECTING` | TCP-Connect zum Gateway läuft |
| `CAPTURE` | Mikrofon-Audio wird aufgenommen und gestreamt |
| `AWAIT_RESPONSE` | TTS-Antwort vom Gateway wird empfangen und abgespielt |

---

### `start()` — Session-Initialisierung

Wird aufgerufen wenn "Hey Jarvis" erkannt wird.

1. **Guard:** Wenn nicht `IDLE`, ignorieren (kein Doppelstart)
2. **State → CONNECTING**
3. **`connect_()`:** DNS-Auflösung via `lwip getaddrinfo`, TCP-Connect zum Gateway (synchron)
4. **`rx_buffer_.reserve(16384)`** — Heap-Vorreservierung bevor Mic-Callbacks fragmentieren können
5. Zustandsvariablen initialisieren: `speech_seen_ = false`, `capturing_utterance_ = false`
6. **`mic_->start()`** — I2S-Mikrofonaufnahme beginnt
7. **State → CAPTURE**
8. **`begin_utterance_()`** — sendet sofort `audio-start` ans Gateway

---

### `begin_utterance_()` — Wyoming AudioStart

Sendet ein Wyoming-Event ans Gateway:

```
{"type": "audio-start", "data_length": 42}\n
{"rate": 16000, "width": 2, "channels": 1}
```

Das Header-JSON teilt dem Gateway mit: "Ich schicke jetzt 16 kHz mono 16-bit PCM." Die Rate 16000 ist hier kritisch — würde 48000 stehen, würde Whisper das Audio 3× gestaucht interpretieren und Garbage-Transkripte liefern (war BUG-8 beim Hardware-Bringup).

---

### `on_mic_data_()` — I2S-Datenkonvertierung

Der I2S-DMA-Buffer liefert Frames im Format **32-bit Stereo, 16 kHz:**

```
[L3][L2][L1][L0][R3][R2][R1][R0][L3][L2]...  (8 Bytes pro Sample-Paar)
```

Die Konvertierung zu mono 16-bit:

```cpp
const int32_t s32 = data[i] | (data[i+1] << 8) | (data[i+2] << 16) | (data[i+3] << 24);
const uint16_t s16 = static_cast<int16_t>(s32 >> 16);
```

Den linken Kanal nehmen, Bits 31–16 als signed 16-bit extrahieren. Ein DMA-Buffer mit 2048 raw bytes ergibt 256 Samples = 512 Bytes PCM16 (16 ms Audio).

**VAD (Energy Detection):** Nach der Konvertierung prüft `is_silent_()` den RMS-Wert:

```
RMS = sqrt(Summe(sample²) / Anzahl)
```

Rauschen hat typischerweise RMS < 300, Sprache > 700. Wenn Sprache erkannt: `speech_seen_ = true`, `last_voice_ms_ = millis()`.

**Senden:** Jedes konvertierte PCM16-Frame wird sofort als `audio-chunk` ans Gateway gesendet:

```
{"type": "audio-chunk", "data_length": 42, "payload_length": 512}\n
{"rate": 16000, "width": 2, "channels": 1}
[512 bytes PCM16]
```

---

### `loop()` im CAPTURE-Zustand — Schweige-Erkennung

Jeden Tick prüft `loop()` zwei Bedingungen:

```
speech_seen_ UND (millis() - last_voice_ms_) > silence_ms_ (900 ms)?
  → end_utterance_()

ODER: (millis() - utterance_start_ms_) > listen_timeout_ms_ (6000 ms)?
  → end_utterance_()    ← Fallback: kein Sprechen erkannt
```

Die erste Bedingung reagiert dynamisch auf das Ende der Sprache. Die zweite ist ein harter Timeout als Absicherung für den Fall, dass gar kein Sprechen erkannt wurde.

---

### `end_utterance_()` — Utterance abschließen

1. Sendet `audio-stop` ans Gateway (kein Payload)
2. `mic_->stop()` — gibt den I2S-Bus frei (Mikrofon und Lautsprecher teilen sich den Bus)
3. `capturing_utterance_ = false`
4. **State → AWAIT_RESPONSE**

---

### `loop()` im AWAIT_RESPONSE-Zustand — TTS empfangen

`read_socket_()` wird jeden Tick aufgerufen. Das liest non-blocking vom Socket (bis `EWOULDBLOCK`), befüllt `rx_buffer_`, und ruft nach jedem Read `try_dispatch_()` auf.

---

### `try_dispatch_()` — Wyoming-Frame-Parsing

Wyoming-Events sind zeilenbasiert:

```
{JSON-Header}\n
[data_length Bytes: Data-JSON]
[payload_length Bytes: Binär-Payload]
```

Der Parser sucht `\n` im Buffer, extrahiert den Header, prüft ob die erwarteten Bytes vollständig im Buffer sind, dispatcht dann `handle_inbound_event_()` und löscht den verarbeiteten Teil aus dem Buffer.

---

### `handle_inbound_event_()` — TTS-Playback

**`audio-start`:** Konfiguriert den Speaker auf 48 kHz und startet ihn:

```cpp
speaker_->set_audio_stream_info(AudioStreamInfo(16, 1, 48000));
speaker_->start();
```

**`audio-chunk`:** Schreibt das PCM-Payload direkt in den Speaker-Ringbuffer:

```cpp
speaker_->play(payload.data(), payload.size());
```

**`audio-stop`:** Das Gateway ist fertig mit Sprechen.
- `tts_stop_ms_ = millis()`
- `pending_rearm_ = true`
- Kein sofortiger Mic-Start — der Speaker-Ringbuffer spielt noch nach.

---

### `rearm_when_drained_()` — Continued Conversation

400 ms nach `audio-stop` (fixer Delay, weil `speaker_->is_running()` über ESPHome-Versionen unzuverlässig ist):

1. `speaker_->stop()`
2. Zustandsvariablen zurücksetzen
3. `mic_->start()` — I2S-Bus wieder für Mikrofon freigegeben
4. **State → CAPTURE**
5. `begin_utterance_()` — sofort neues `audio-start` ans Gateway

Das ist die **Continued Conversation**: Das Gateway wartet bereits auf die nächste Äußerung, ohne dass der User erneut "Hey Jarvis" sagen muss. Der Zyklus CAPTURE → AWAIT_RESPONSE → CAPTURE läuft so lange, bis das Gateway die TCP-Verbindung schließt.

---

### `finish_session_()` — Session-Ende

Wird aufgerufen wenn: Gateway die Verbindung schließt (EOF), ein Fehler auftritt, oder `stop()` von außen aufgerufen wird.

1. `mic_->stop()`, `speaker_->stop()`
2. TCP-Socket schließen, `rx_buffer_` freigeben
3. State → **IDLE**
4. **`mic_->start()` — kritisch:** `micro_wake_word` empfängt nur Audio wenn das Mikrofon läuft. Ohne diesen Aufruf würde das Gerät nie wieder ein Wake Word erkennen (war BUG-10 beim Hardware-Bringup).

---

## Vollständiger Flow: "Hey Jarvis, Licht an"

```
Gerät im IDLE-Zustand
mic_ läuft für micro_wake_word
        │
        │  "Hey Jarvis" erkannt
        ▼
Package-Handler:  voice_assistant.start  (HA Assist)
Eigener Handler:  voice_assistant.stop
                  wyoming_satellite.start()
        │
        ▼
connect_() — TCP zu 192.168.178.88:10302
mic_->start(), State=CAPTURE
begin_utterance_() → audio-start gesendet
        │
        │  on_mic_data_() Callbacks:
        │  32-bit Stereo → 16-bit Mono
        │  audio-chunk gesendet (laufend)
        │  speech_seen_=true, last_voice_ms_ aktuell
        │
        │  Stille 900 ms nach letztem Sprachframe
        ▼
end_utterance_() → audio-stop, mic_->stop()
State=AWAIT_RESPONSE
        │
        │  Gateway: STT (Whisper) → "Licht im Büro an"
        │           AI → HA-Aktion → TTS (Piper, 48 kHz)
        ▼
audio-start empfangen → speaker 48 kHz start
audio-chunk(s) empfangen → speaker_->play()
audio-stop empfangen → pending_rearm_=true
        │
        │  400 ms warten (Speaker-Drain + XMOS AEC-Settle)
        ▼
rearm_when_drained_():
  speaker_->stop(), mic_->start()
  State=CAPTURE, begin_utterance_() → audio-start
        │
        │  [Gateway sendet conversation_end → schließt TCP]
        │  read_socket_() sieht EOF (n==0)
        ▼
finish_session_() → mic_->start(), State=IDLE

Gerät hört wieder auf Wake Words
```

Das Gateway steuert den Session-Lebenszyklus — das Gerät folgt der TCP-Verbindung. Schließt das Gateway die Verbindung (nach `conversation_end` oder 30 s Stille), endet die Session auf dem Gerät automatisch.

---

## I2S-Raten im Überblick

| Konstante | Wert | Verwendet für |
|---|---|---|
| `MIC_SAMPLE_RATE` | 16000 Hz | AudioStart/AudioChunk-Events ans Gateway; WAV-Header für Whisper |
| `SAMPLE_RATE` | 48000 Hz | Speaker-Konfiguration; AudioStreamInfo für TTS-Playback |

Diese beiden Raten dürfen **nicht** verwechselt werden. `SAMPLE_RATE` in `audio_format_json()` zu verwenden war BUG-8 und führte zu Garbage-Transkripten.
