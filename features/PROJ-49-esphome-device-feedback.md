# PROJ-49: ESPHome Device Feedback — LED-Zustandsmaschine + Wake Sound

## Status: Architected
**Created:** 2026-06-15
**Last Updated:** 2026-06-15

## Dependencies
- Requires: PROJ-42 (ESPHome wyoming_satellite component, HA Voice PE hardware)
- Optional backend touch: alice-chat-stream (falls "Warte bitte…" als Interstitial implementiert wird)

## Kontext

Audio I/O des HA Voice PE funktioniert vollständig (PROJ-42 Deployed). Dem Gerät fehlt jetzt audiovisuelle Zustandsrückmeldung: Der Lichtkreis bleibt statisch, der Wake Sound ist inkonsistent. Der Nutzer weiß nicht, ob das Gerät zuhört, denkt oder antwortet.

Das Gerät hat einen RGB LED-Ring sowie einen Lautsprecher (I2S) — beide sind im ESPHome-Package des HA Voice PE bereits vollständig verkabelt.

## User Stories

- Als Nutzer möchte ich durch den Lichtkreis sehen, in welchem Zustand Alice gerade ist (Zuhören / Denken / Antworten), damit ich ohne Blick aufs Smartphone verstehe, was das Gerät tut.

- Als Nutzer möchte ich bei "Hey Jarvis" immer denselben, konsistenten Ton hören, damit das Feedback zuverlässig und vorhersagbar ist — und nicht bei der ersten Aktivierung anders klingt als bei den folgenden.

- Als Nutzer möchte ich, dass der Lichtkreis nach dem Ende einer Session wieder in den Idle-Zustand zurückkehrt, damit ich immer erkennen kann, ob das Gerät im Wakeword-Modus ist.

## Akzeptanzkriterien

### Wake Sound (Konsistenz)

- [ ] Bei jeder "Hey Jarvis"-Erkennung wird **exakt derselbe Ton** abgespielt — unabhängig davon, ob es die erste oder eine Folge-Aktivierung ist
- [ ] Die Ursache der zwei verschiedenen Töne ist identifiziert (verschiedene Audio-Dateien im Package? I2S-Bus-Zustand? Media Player vs. Speaker-Pfad?)
- [ ] Falls nötig: Wake Sound wird im `on_wake_word_detected`-Handler für `hey_jarvis` explizit gesteuert, statt den Package-Switch `wake_sound` zu nutzen

### LED-Zustandsmaschine

| Zustand | Trigger | LED-Verhalten |
|---|---|---|
| STT (Zuhören) | Nach Wakeword-Ton, Mic ist aktiv | Lichtkreis dreht **im Uhrzeigersinn** |
| Denken | Audio-Upload abgeschlossen, warte auf LLM/HA | Lichtkreis **blinkt** |
| TTS (Antworten) | Erste TTS-Chunk trifft ein | Lichtkreis dreht **gegen den Uhrzeigersinn** |
| CC-Zuhören | TTS beendet, Mic re-armed für nächste Äußerung | Lichtkreis dreht **im Uhrzeigersinn** (wie STT) |
| Idle | Session beendet, zurück zu Wakeword-Modus | LED kehrt zum Package-Idle-Effekt zurück |

- [ ] STT-Phase: LED dreht im Uhrzeigersinn ab dem Moment des Wakeword-Tones bis zum Ende des Audio-Uploads
- [ ] Thinking-Phase: LED blinkt ab Audio-Upload-Ende bis zum ersten TTS-Chunk
- [ ] TTS-Phase: LED dreht gegen den Uhrzeigersinn während Audio gespielt wird
- [ ] CC-Zuhören: Nach Ende der TTS-Ausgabe dreht LED wieder im Uhrzeigersinn (Mic wartet auf nächste Äußerung)
- [ ] Session-Ende: LED kehrt in den Idle-Effekt des Packages zurück (kein "hängen bleiben" in einem Aktiv-Effekt)
- [ ] Fehlerfall (STT-Fehler, Timeout, unbekannte IP): LED kehrt zu Idle zurück nach der Fehlermeldung

### "Warte bitte…" Interstitial

Alice-chat-stream sendet bereits ein "Warte bitte…"-TTS wenn das LLM angesprochen wird. Das Device empfängt dieses Audio und spielt es ab. Die LED-Zustandsmaschine muss diese Sequenz korrekt abbilden:

- [ ] "Warte bitte…"-Audio kommt als TTS-Chunk an → LED dreht gegen den Uhrzeigersinn (wie normale TTS)
- [ ] Nach Ende der "Warte bitte…"-Ausgabe kehrt das Device in die Thinking-Phase zurück → LED blinkt wieder
- [ ] Sobald die eigentliche LLM-Antwort als TTS eintrifft → LED dreht wieder gegen den Uhrzeigersinn
- [ ] Beim HA-Part (kein LLM-Thinking) tritt kein "Warte bitte…" auf — LED wechselt direkt von Thinking zu TTS

## Edge Cases

- **"Parent I2S bus not free"-Fehler**: Tritt auf wenn Media Player (Wake Sound) und `i2s_audio_speaker` (wyoming_satellite) gleichzeitig den I2S-Bus beanspruchen. LED-Übergänge müssen robust gegen diesen 1-Sekunden-Retry sein.
- **Kurze Äußerung ohne Sprache** (empty transcript / `audio_too_short`): LED geht von STT → Thinking → direkt zu Idle (kein TTS-Spin, da die Fehlermeldung via anderem Pfad kommt oder ausfällt je nach `speak_on_empty`-Logik)
- **Session endet durch `conversation_end`** (HA-Befehl): TTS spielt Bestätigung → gegen Uhrzeigersinn → Idle. Kein CC-Zuhören danach.
- **Gateway nicht erreichbar**: Kein TCP-Connect möglich → LED bleibt in Idle (kein aktiver Zustand erreicht)
- **OTA-Flash nach Änderung**: Wake Words in HA nach jedem Reflash neu aktivieren (bekannte Ops-Anforderung aus PROJ-42)

## Technical Requirements

- **Änderungsort**: `devices/ha-voice-pe/components/wyoming_satellite/wyoming_satellite.h` + `.cpp` — LED-Pointer und Zustandsübergänge im bestehenden Zustandsautomaten
- **LED-Steuerung**: `light::LightState*`-Pointer in der Komponente, gesetzt via `set_light()` in `__init__.py`. Effektnamen aus dem HA Voice PE Package müssen vor der Implementierung verifiziert werden (via `esphome config` Output analysieren)
- **Kein Gateway-Change** für LED-Basis-States: Die Firmware kennt ihre eigenen Zustandsübergänge (CAPTURE → AWAIT_RESPONSE → PLAYING) — LED-Steuerung kann rein device-seitig erfolgen
- **"Warte bitte…"-Interstitial**: Bereits in `alice-chat-stream/streaming.py` implementiert und auf dem Device aktiv — kein Backend-Change nötig, nur LED-Zustandssteuerung in der Firmware
- **ESPHome-Version**: ESPHome 2026.3.1 (wie in PROJ-42 festgelegt; LED-API-Calls müssen zu dieser Version passen)
- **Kein Reflash für Gateway-Changes**: Nur firmware-seitige Änderungen erfordern ein Reflash des HA Voice PE

## Offene Fragen (für /architecture zu klären)

1. **LED-Effektnamen**: Welche Effekte (clockwise spin, counter-clockwise spin, blink) stellt das HA Voice PE Package bereit, und wie heißen sie im ESPHome YAML/C++ API?
2. **Wake Sound Root Cause**: Warum klingen zwei aufeinanderfolgende Aktivierungen unterschiedlich — verschiedene Audio-Dateien oder I2S-Zustandsunterschied?
3. **"Warte bitte…"-Erkennung**: Wie unterscheidet die Firmware die "Warte bitte…"-TTS von der eigentlichen Antwort? (Pause zwischen zwei TTS-Sequenzen? Wyoming `RunPipeline`-Event?) Muss analysiert werden um den Rücksprung in den Blink-Zustand korrekt zu triggern.

---

## Tech Design (Solution Architect)

**Scope**: Pure firmware change. Kein Backend, kein n8n, kein Gateway-Change.

---

### Was gebaut wird (Überblick)

Drei unabhängige Änderungen in vier Dateien:

1. **LED-Hook in der C++-Komponente** — `wyoming_satellite.h` und `.cpp` bekommen einen `light::LightState*`-Pointer. Bei jedem Zustandswechsel ruft die Komponente direkt die ESPHome Light-API auf, um den richtigen Effekt zu starten.
2. **Schema-Erweiterung in `__init__.py`** — Das Python-Codegen registriert das neue `light:`-Feld und verdrahtet den Pointer beim Build.
3. **YAML-Anpassung in `espHome.yaml`** — Zwei Änderungen: (a) das `wyoming_satellite`-Block bekommt `light: voice_assistant_leds`; (b) der "Hey Jarvis"-Wake-Word-Handler wird umgebaut, um den Wake Sound konsistent zu machen.

---

### A) LED-Zustandsmaschine

#### Effektnamen (aus dem HA Voice PE Package verifiziert)

Die Effekte existieren bereits im Package — kein neues YAML nötig:

| Zustand | ESPHome Effektname | Aussehen |
|---|---|---|
| STT / CC-Zuhören | `"Listening For Command"` | Schnelle CW-Rotation (50 ms) |
| Denken | `"Thinking"` | Zwei gegenüberliegende LEDs pulsieren |
| TTS / Antworten | `"Replying"` | CCW-Rotation (50 ms) |
| Fehler | `"Error"` | Rotes Pulsieren |
| Idle | LED aus | Package-Idle (LED-Ring bleibt auf User-Farbe) |

#### Zustandsübergänge → LED-Aufruf (Mapping auf C++-Übergänge)

```
start()                               → "Listening For Command"
end_utterance_()    (Audio-Stop gesendet)   → "Thinking"
audio-start empfangen (TTS beginnt)   → "Replying"
audio-stop empfangen (TTS-Chunk endet)→ "Thinking"  (kurz, bis nächstes audio-start ODER rearm)
rearm_when_drained_() (CC Mic bewaffnet) → "Listening For Command"
finish_session_()   (Session-Ende)    → LED aus
connect_() scheitert                  → LED aus
```

#### "Warte bitte…"-Interstitial — keine Extra-Logik nötig

Die bestehende Zustandsmaschine handhabt das bereits korrekt:

```
audio-start ("Warte bitte…")  → Replying (CCW)
audio-stop  ("Warte bitte…")  → Thinking (blinken)
[400 ms rearm-Verzögerung]
audio-start (LLM-Antwort)     → Replying (CCW)
audio-stop  (LLM done)        → Thinking → dann Idle oder CC-Zuhören
```

Die Firmware muss die TTS-Phasen **nicht unterscheiden** — das visuelle Verhalten ergibt sich automatisch aus dem Wechsel zwischen `audio-start` und `audio-stop`.

---

### B) Wake Sound Konsistenz

#### Root Cause (identifiziert)

Das I2S-Bus-Konfliktproblem bei zweiter+ Aktivierung:

- Das HA Voice PE Package läuft **zuerst**: queued Wake Sound ins Announcement-Pipeline → Mixer → `i2s_audio_speaker`
- Unser Handler läuft **danach**: `wyoming_satellite.stop` → `finish_session_()` → direkt `speaker_->stop()` auf demselben `i2s_audio_speaker`
- Der raw `stop()`-Aufruf unterbricht den Mixer-Ausgang → erste Audio-Bytes fallen weg → unterschiedlicher Klang als beim ersten Mal

#### Fix-Strategie: Unser Handler übernimmt den Wake Sound

Wir stornieren den vom Package gequeueten Sound und spielen ihn selbst nach der sauberen Session-Beendigung:

```
Unser "Hey Jarvis"-Handler (in espHome.yaml):
  1. wyoming_satellite.stop   ← räumt raw speaker auf
  2. voice_assistant.stop     ← räumt HA pipeline auf
  3. media_player.stop (announcement)  ← storniert den Package-gequeueten Sound
  4. play_sound "wake_word_triggered_sound" (priority: true)  ← sauber abspielen
  5. delay 300 ms
  6. wyoming_satellite.start
```

Damit spielt der Sound **immer** über denselben Pfad, unabhängig davon, ob es die erste oder zehnte Aktivierung ist.

---

### C) Welche Dateien werden geändert

| Datei | Art der Änderung |
|---|---|
| `components/wyoming_satellite/wyoming_satellite.h` | `light::LightState* light_` Pointer + `set_light()` Setter hinzufügen |
| `components/wyoming_satellite/wyoming_satellite.cpp` | LED-Aufrufe an den 6 Zustandsübergängen einbauen |
| `components/wyoming_satellite/__init__.py` | `CONF_LIGHT`-Schema + Codegen-Zeile für `set_light()` |
| `espHome.yaml` | `light: voice_assistant_leds` im wyoming_satellite-Block; Wake-Sound-Handler umbauen |

**Kein Reflash** wird für Gateway- oder n8n-seitige Änderungen nötig. Nur OTA-Flash der Firmware nach den C++-Änderungen.

---

### D) Edge Cases — bereits abgedeckt

| Edge Case | Verhalten |
|---|---|
| STT-Fehler / Timeout | `finish_session_()` → LED aus (Idle) |
| `audio_too_short` / leeres Transcript | Session endet normal → LED aus (kein TTS-Spin) |
| Session endet durch `conversation_end` | TTS → Replying → `finish_session_()` → LED aus. Kein CC-Zuhören. |
| Gateway nicht erreichbar | `connect_()` schlägt fehl → kein LED-Aufruf → LED bleibt aus |
| I2S "Parent not free" Retry | `finish_session_()` kümmert sich nicht um den Retry; LED bleibt in Idle bis zur nächsten Aktivierung |

---

### E) Tech-Entscheidungen (für PM)

**Warum C++-Pointer statt YAML-Trigger?**
Der wyoming_satellite ist eine C++-Komponente — er "weiß" am besten, wann genau ein Zustand wechselt. Ein YAML-Trigger würde eine Umweg über ESPHome's Automation-Engine erfordern und die Latenz zwischen Zustandswechsel und LED-Änderung erhöhen. Der direkte C++-Pointer-Aufruf ist der einfachste und schnellste Weg.

**Warum keine neuen LED-Effekte?**
Das HA Voice PE Package bringt bereits alle benötigten Effekte mit. Wir nutzen sie unverändert — kein Risiko, bestehende Animationen zu brechen.

**Warum Wake Sound im eigenen Handler statt Package-Handler?**
Das Package hat keine "Hey Jarvis"-spezifische Logik — es spielt den Sound generisch für alle Wake Words. Für Alice brauchen wir Kontrolle über die Reihenfolge (erst Session stoppen, dann Sound spielen). Statt den Package-Handler zu modifizieren (was Updates erschwert), überschreiben wir nur diesen einen Aspekt in unserem eigenen Automation-Block.
