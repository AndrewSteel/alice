# PROJ-57: On-Device VAD Noise Robustness — Adaptiver Noise-Floor

## Status: Deployed
**Created:** 2026-07-03
**Last Updated:** 2026-07-03

## Dependencies
- Requires: PROJ-42 (wyoming_satellite Component, HA Voice PE Hardware) — der zu ändernde Silence-Detector (`is_silent_()`, `silence_threshold_`) stammt aus BUG-14 in PROJ-42
- Related: PROJ-58 (Sprache-vs-TV/Radio-Trennung via Speaker-ID) — verwandtes, aber technisch andersartiges Problem (Quelltrennung statt Lautstärke-Schwelle); explizit **nicht** Teil dieses Specs

## Kontext

Das HA Voice PE (Büro + Küche, aus PROJ-49) hat Schwierigkeiten, eine Spracheingabe sauber abzuschließen, wenn im Raum ein Dauergeräusch vorhanden ist (z.B. Lüfter, Staubsauger). Ursache: der on-device Silence-Detector in `wyoming_satellite.cpp` (`is_silent_()`) nutzt einen **festen RMS-Schwellwert von 700** — jedes Mikrofon-Frame mit RMS ≥ 700 gilt als "Sprache läuft noch", unabhängig davon, ob es sich um die Stimme des Nutzers oder reines Umgebungsgeräusch handelt.

In einem leisen Raum funktioniert das gut: der Nutzer spricht, die Stille danach fällt unter 700 RMS, das Gerät beendet die Eingabe nach 900ms Stille. Liegt der Geräuschpegel im Raum aber dauerhaft über 700 RMS (laufender Lüfter, Dunstabzugshaube, Staubsauger), wird `is_silent_()` nie `true` — die 900ms-Stille-Erkennung greift nie, und das Gerät fällt stattdessen auf den 8-Sekunden-Hard-Timeout (`listen_timeout_ms_`) zurück. Das Ergebnis: lange Wartezeit nach jeder Äußerung, und im schlimmsten Fall wird Geräusch mit in die Aufnahme aufgenommen.

Dieses Feature ersetzt den festen Schwellwert durch einen **adaptiven Noise-Floor**, der sich automatisch an den tatsächlichen Umgebungspegel anpasst — ohne manuelle Konfiguration pro Raum/Gerät.

**Explizit außerhalb des Scopes:** Hintergrundquellen mit sprachähnlichem Charakter (TV, Radio) lassen sich durch eine Lautstärke-Schwelle grundsätzlich nicht von echter Nutzer-Sprache trennen — das erfordert Quellentrennung (z.B. Speaker-ID), nicht nur eine bessere Schwellwert-Berechnung. Das wird separat in **PROJ-58** behandelt.

## User Stories

- Als Nutzer möchte ich "Licht im Büro ausschalten" auch bei laufender Dunstabzugshaube oder Lüfter sagen können, ohne dass das Gerät die Eingabe erst nach 8 Sekunden abschließt.
- Als Nutzer möchte ich, dass sich das Zuhör-Verhalten des Geräts automatisch an den Geräuschpegel im Raum anpasst, ohne dass ich irgendetwas manuell einstellen muss.
- Als Nutzer möchte ich, dass sich in einem leisen Raum nichts am bisherigen, bereits funktionierenden Verhalten ändert.
- Als Admin möchte ich, dass diese Anpassung automatisch für jedes Gerät/jeden Raum funktioniert (Büro, Küche, künftige Geräte), ohne raumspezifische manuelle Kalibrierung in `espHome.yaml` oder `device-mapping.yaml`.

## Akzeptanzkriterien

### Kernverhalten
- [ ] Bei laufendem Lüfter im Raum beendet das Gerät die Eingabe innerhalb der üblichen Stille-Zeitspanne (~900ms) nachdem der Nutzer aufgehört hat zu sprechen — nicht erst nach dem 8s-Timeout
- [ ] Gleiches gilt für: Dunstabzugshaube und Kühlschrank-Brummen (typische Dauergeräusche)
- [ ] Gleiches gilt in der Tendenz für Staubsauger — als lautere/variablere obere Bandbreite, ohne Garantie bei Extremlautstärke direkt am Gerät (siehe Edge Cases)
- [ ] In einem leisen Raum (aktuelle Baseline) bleibt das Verhalten unverändert — keine Regression bei Stille-Erkennung oder Reaktionszeit
- [ ] Die Anpassung erfolgt automatisch pro Gerät/Raum, ohne manuellen Schwellwert in YAML

### Robustheit / Fallback
- [ ] Bei Geräuschpegeln, die auch mit adaptivem Noise-Floor keine zuverlässige Sprach-vs-Geräusch-Trennung erlauben (z.B. Staubsauger direkt neben dem Gerät), greift weiterhin der bestehende 8s-Hard-Timeout als Fallback — kein Hängenbleiben, keine Regression gegenüber heute
- [ ] Ändert sich der Geräuschpegel während einer laufenden Konversation merklich (z.B. Dunstabzugshaube wird während des Gesprächs eingeschaltet), ist spätestens bei der nächsten "Hey Jarvis"-Aktivierung der neue Pegel berücksichtigt

### Kein Nutzer-seitiger Konfigurationsaufwand
- [ ] Kein manuelles Kalibrieren durch den Nutzer nötig (kein Setup-Schritt wie "bitte 5 Sekunden still sein")
- [ ] Kein raumspezifischer Fixwert in `espHome.yaml`/`device-mapping.yaml` nötig — funktioniert automatisch für Büro, Küche und künftige Geräte

## Edge Cases

- **Geräusch startet mitten in der Aufnahme** (z.B. Lüfter schaltet sich ein während der Nutzer spricht): laufende Erkennung darf nicht fälschlich vorzeitig abbrechen, nur weil der Pegel plötzlich steigt
- **Sehr leiser Nutzer bei moderatem Hintergrundgeräusch**: Wenn die Sprache kaum über dem Noise-Floor liegt, kann `speech_seen_` u.U. nicht zuverlässig gesetzt werden — Fallback bleibt der 8s-Timeout, kein Hängenbleiben, aber ggf. unsauberes Erkennungsende (bekannte Grenze, kein Blocker für dieses Feature)
- **Extreme Nahfeld-Geräusche** (Staubsauger direkt am Gerät): keine Garantie für korrekte Trennung; Verhalten degradiert kontrolliert auf den bestehenden 8s-Timeout, kein Absturz/Hängenbleiben
- **Sprachähnlicher Hintergrund (TV/Radio)**: explizit außerhalb des Scopes dieses Features — siehe PROJ-58
- **Gerätewechsel Büro ↔ Küche**: unterschiedliche Raumakustik/Grundgeräusch wird automatisch durch die Live-Anpassung berücksichtigt, keine manuelle Rekalibrierung bei Standortwechsel nötig
- **Reflash/Neustart des Geräts**: Kalibrierungszustand ist flüchtig (RAM); nach einem Neustart beginnt die Anpassung wieder von einem Startwert (bestehender Fixwert 700 als sinnvoller Ausgangspunkt, bis genug Daten für eine adaptive Schätzung vorliegen)

## Technical Requirements

- **Änderungsort**: `devices/ha-voice-pe/components/wyoming_satellite/wyoming_satellite.h` + `.cpp` — Silence-Detector (`is_silent_()`, `silence_threshold_`)
- **Kein Gateway-Change** nötig — reine Firmware-Änderung (wie PROJ-49)
- **Kein Reflash** für Gateway-/n8n-seitige Änderungen; nur OTA-Flash der Firmware nach Änderungen an diesem Feature
- **Ressourcen**: ESP32-S3 (begrenzte CPU/RAM) — Berechnung muss in Echtzeit im bestehenden `on_mic_data_()`-Callback laufen (16ms-Frames), darf die bestehende Audio-Pipeline nicht messbar verlangsamen
- **ESPHome-Version**: 2026.3.1 (wie in PROJ-42/PROJ-49 festgelegt)

## Offene Fragen (für /architecture zu klären)

1. **Kalibrierungsmechanismus**: kontinuierliche Hintergrund-Schätzung während der Wakeword-Lauschphase (IDLE-State, Mic läuft bereits für `micro_wake_word`) vs. kurzes Kalibrierungsfenster direkt nach dem Wakeword-Trigger — Trade-off Genauigkeit vs. Implementierungsaufwand und Latenz
2. **Margin/Multiplikator**: welcher Abstand über dem gemessenen Noise-Floor gilt als "Sprache" (heute: fixer RMS-Wert 700 ohne Bezug zum Umgebungspegel)?
3. **Adaption während CAPTURE**: wird der Noise-Floor während einer laufenden Aufnahme weiter aktualisiert, oder beim Start der Utterance eingefroren (Risiko: echte Sprache wird fälschlich in die Schätzung eingerechnet)?
4. **Startwert-Strategie**: welcher Ausgangswert gilt direkt nach Neustart/Reflash, bevor genug Daten für eine Schätzung vorliegen? (Vorschlag: bestehender Fixwert 700 als Fallback-Startpunkt)

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

**Änderungsort:** `devices/ha-voice-pe/components/wyoming_satellite/` (`.h` + `.cpp`) — reine Firmware-Logik, kein Gateway-/n8n-Change, keine neuen Abhängigkeiten.

### A) Verhaltensablauf

```
IDLE (Wake-Word-Lauschphase, Mic läuft bereits für "Hey Jarvis")
+-- Noise-Floor-Schätzung läuft kontinuierlich im Hintergrund mit,
|   solange das Gerät im IDLE-Zustand ist (kein zusätzlicher Mic-Start,
|   keine zusätzliche Latenz — nutzt Audio, das ohnehin schon fließt)
+-- Direkt nach Boot/Reflash, bevor genug Hintergrund-Audio vorliegt:
    Startwert = heutiger Fixwert 700 (keine Regression am ersten Tag)

"Hey Jarvis" erkannt → CAPTURE beginnt
+-- Schwellwert für diese Utterance wird EINGEFROREN:
|   = letzter IDLE-Noise-Floor-Wert, umgerechnet in einen Sprache-Schwellwert
+-- Während der laufenden Aufnahme wird der Schwellwert NICHT mehr verändert
|   (verhindert, dass die eigene Stimme des Nutzers die Schätzung verfälscht)
+-- Stille-Erkennung (900ms) arbeitet exakt wie heute, nur mit diesem
|   eingefrorenen, an den Raum angepassten Schwellwert statt Fixwert 700

Utterance endet → zurück in IDLE
+-- Noise-Floor-Schätzung läuft weiter (Live-Anpassung), nächste Utterance
    nutzt automatisch den aktuellen Wert — erfüllt AC "spätestens bei
    nächster Hey-Jarvis-Aktivierung berücksichtigt"

Sicherheitsnetz (neu, siehe "Wichtiger Befund" unten):
+-- Eine Aufnahme wird IMMER spätestens nach dem bestehenden
    8-Sekunden-Hard-Timeout beendet — unabhängig davon, ob in der Zwischenzeit
    (fälschlich oder korrekt) Sprache erkannt wurde. Das ist heute nicht
    garantiert (siehe unten) und wird mit diesem Feature nachgerüstet.
```

### B) Daten-Modell (fachlich)

Zwei neue, rein flüchtige (RAM-only, wie im Spec gefordert) Laufzeitwerte kommen hinzu, keine neuen Config-Felder in YAML:

- **Noise-Floor-Schätzwert**: ein sich langsam anpassender "wie laut ist es hier gerade im Ruhezustand"-Wert, der bei jedem Mikrofon-Frame während IDLE leicht nachjustiert wird (stärkeres Gewicht auf neuere Frames, ältere Messungen verblassen graduell) — keine feste Fensterlänge, die konfiguriert werden müsste.
- **Aktiver Sprache-Schwellwert**: wird beim Start jeder Utterance einmalig aus dem Noise-Floor-Schätzwert berechnet und für die Dauer der Aufnahme eingefroren (siehe Margin-Formel unten).

Beide Werte verhalten sich exakt wie der heutige `silence_threshold_`: flüchtig, pro Gerät, kein Persistieren, kein Reflash nötig.

### C) Tech-Entscheidungen (Begründung)

1. **Kontinuierliche Schätzung während IDLE statt Kalibrierungsfenster nach Wake-Word**
   Das Mikrofon läuft im IDLE-Zustand ohnehin permanent für die Wake-Word-Erkennung (`micro_wake_word`). Die Noise-Floor-Schätzung nutzt exakt diesen bereits fließenden Audio-Strom mit — kein zusätzlicher Rechenaufwand für ein separates Kalibrierungsfenster, keine zusätzliche Latenz zwischen "Hey Jarvis" und Aufnahmestart. Das Gerät ist bei jeder Aktivierung sofort mit einem aktuellen Wert bereit.

2. **Schwellwert = Noise-Floor × Faktor, nach unten begrenzt auf den heutigen Fixwert 700**
   Ein reiner Faktor (z.B. das ~1,8-fache des gemessenen Ruhepegels) skaliert automatisch mit der Lautstärke im Raum — ein Lüfter (niedriger Ruhepegel) bekommt einen niedrigen, ein Staubsauger (hoher Ruhepegel) einen entsprechend höheren Schwellwert. Die Untergrenze von 700 stellt sicher: in einem leisen Raum (Ruhepegel deutlich unter dem heutigen Fixwert) bleibt exakt das heutige Verhalten erhalten — das erfüllt die "keine Regression"-Anforderung ohne Sonderfall-Logik.

3. **Schwellwert wird bei Utterance-Start eingefroren, nicht live während der Aufnahme aktualisiert**
   Würde der Noise-Floor während der Aufnahme weiterlaufen, würde die Stimme des Nutzers selbst als "Umgebungsgeräusch" mit eingerechnet und den Schwellwert im Lauf eines längeren Satzes fälschlich anheben. Einfrieren beim Utterance-Start vermeidet das und deckt sich mit der Anforderung, dass ein während des Gesprächs neu hinzukommendes Geräusch erst ab der nächsten Aktivierung berücksichtigt werden muss.

4. **Startwert nach Boot/Reflash: heutiger Fixwert 700**
   Direkt nach dem Start liegt noch keine ausreichende IDLE-Hörzeit vor, um einen verlässlichen Noise-Floor zu haben. Der bestehende Fixwert 700 dient so lange als Startpunkt, bis genug Hintergrund-Audio vorliegt (im Bereich weniger Sekunden Wake-Word-Lauschzeit) — danach übernimmt die adaptive Schätzung. Kein Nutzer-seitiger Kalibrierungsschritt nötig.

5. **Wichtiger Befund aus dem bestehenden Code — Sicherheitsnetz muss nachgerüstet werden**
   Bei der Durchsicht von `wyoming_satellite.cpp` zeigt sich: der heutige 8-Sekunden-Hard-Timeout greift nur, wenn *während der gesamten Aufnahme nie* Sprache erkannt wurde (`!speech_seen_`). Sobald irgendein Frame als "Sprache" gilt — was bei einem dauerhaft dem Fixwert 700 überlegenen Geräuschpegel bei **jedem** Frame der Fall ist — bleibt dieser Fallback-Pfad blockiert, und die Aufnahme endet aktuell in so einem Fall **gar nicht** über einen Timeout (entgegen der im Spec beschriebenen Annahme "Gerät fällt auf 8s-Timeout zurück"). Dieses Feature ergänzt daher einen von der Sprache-Erkennung unabhängigen, absoluten Timeout: die Aufnahme wird so oder so nach spätestens 8 Sekunden beendet, egal was `speech_seen_` sagt. Das ist eine reine Absicherung (kein neues Nutzerverhalten) und war schon immer die im Spec beschriebene Erwartung — die adaptive Schwellwert-Berechnung macht diesen Fall in der Praxis zwar seltener, aber die Absicherung muss unabhängig davon existieren, um die Akzeptanzkriterien "kein Hängenbleiben" garantieren zu können.

### D) Abhängigkeiten

Keine neuen Bibliotheken/Pakete. Die Änderung nutzt ausschließlich bereits vorhandene Bausteine (Mikrofon-Callback, RMS-Berechnung, `millis()`-Zeitbasis), die bereits Teil von `wyoming_satellite.cpp` sind.

### Offene Fragen — Status

Alle vier offenen Fragen aus dem Spec sind durch die obigen Entscheidungen beantwortet (Kalibrierungsmechanismus → C.1, Margin/Multiplikator → C.2, Adaption während CAPTURE → C.3, Startwert-Strategie → C.4). Zusätzlich: der Sicherheitsnetz-Befund (C.5) war im Spec nicht als offene Frage aufgeführt, ist aber eine notwendige Ergänzung, um die bestehende Akzeptanzkriterie "kein Hängenbleiben" verlässlich zu erfüllen.

## Implementation Notes (Backend/Firmware)

**Geändert:** `devices/ha-voice-pe/components/wyoming_satellite/wyoming_satellite.h` + `.cpp`. Reine Firmware-Änderung, wie im Tech Design beschrieben — keine Gateway-/n8n-Änderung, kein neues YAML-Feld.

- **Kontinuierliche Noise-Floor-Schätzung während IDLE**: `on_mic_data_()` verarbeitet Mikrofon-Frames jetzt auch im `IDLE`-Zustand (vorher: sofortiger Return außerhalb `CAPTURE`). Im IDLE-Fall wird nur `update_noise_floor_()` aufgerufen (RMS des Frames → langsamer EWMA mit `ALPHA = 0.02`), kein Senden an das Gateway.
- **Eingefrorener Schwellwert pro Utterance**: `begin_utterance_()` berechnet `silence_threshold_` neu aus `noise_floor_estimate_ * NOISE_MARGIN_FACTOR` (Faktor 1.8), nach unten begrenzt auf `configured_min_threshold_` (= der YAML-Wert `silence_threshold: 700`, einmalig in `setup()` gesichert). Der Wert bleibt für die gesamte Aufnahme unverändert — `is_silent_()` selbst wurde nicht verändert, sie liest weiterhin `silence_threshold_`.
- **Startwert nach Boot**: `noise_floor_estimate_` wird in `setup()` mit dem YAML-Wert (700) vorbelegt — exakt die im Spec geforderte Fallback-Startwert-Strategie.
- **Sicherheitsnetz-Nachrüstung (Tech Design C.5)**: `loop()` im `CAPTURE`-State hat jetzt einen dritten, von `speech_seen_` unabhängigen Check — ein absoluter `listen_timeout_ms_`-Deckel ab `utterance_start_ms_`, der die Aufnahme per `end_utterance_()` (nicht `finish_session_()`, da ja Sprache erkannt wurde) beendet. Das behebt den im Tech Design dokumentierten Befund, dass der bestehende Timeout-Pfad nie griff, sobald `speech_seen_` einmal `true` war.
- **Kein neuer State, kein neues YAML-Feld** — `silence_threshold` in den espHome-*.yaml-Dateien bleibt unverändert (700) und wirkt jetzt als Startwert/Untergrenze statt als Fixwert.

**Build-Verifikation:** `esphome compile` für beide Geräte-Configs (`espHome-buero.yaml`, `espHome-kueche.yaml`) lief erfolgreich durch (installierte ESPHome-Version im lokalen venv: 2026.4.5 — Spec nennt 2026.3.1 aus PROJ-42/49; keine mit dieser Änderung zusammenhängenden Kompatibilitätsprobleme aufgetreten). Kein Hardware-Flash/On-Device-Test durchgeführt (kein Zugriff auf physische Geräte in dieser Session) — Verifikation der akustischen Akzeptanzkriterien (Lüfter/Dunstabzugshaube/Staubsauger-Szenarien) steht aus und muss auf echter Hardware erfolgen.

## QA Test Results

**Getestet:** 2026-07-03
**Methode:** Code-Review gegen jedes Akzeptanzkriterium (Logik-Trace durch `wyoming_satellite.cpp`/`.h`) + Build-Verifikation (`esphome compile`) für beide Geräte-Configs. **Kein Hardware-Flash / akustischer Test** — kein Zugriff auf physische Geräte (Büro/Küche) in dieser Session. Akustische Feinabstimmung (z.B. der Margin-Faktor 1.8) ist ein Heuristik-Wert aus dem Tech Design und kann nur auf echter Hardware endgültig validiert werden — als Nacharbeit für die erste Praxiswoche nach Deploy vorgemerkt, kein Blocker für Approved.
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### Kernverhalten
- [x] Lüfter/Dunstabzugshaube/Kühlschrank enden binnen ~900ms Stille statt 8s-Timeout — durch Logik-Trace bestätigt: `noise_floor_estimate_` konvergiert binnen weniger Sekunden IDLE-Zeit auf den Ruhepegel; `begin_utterance_()` setzt den Schwellwert auf `max(700, noise_floor × 1.8)`, wodurch reines Dauergeräusch unter dem Schwellwert bleibt und `is_silent_()` nach Sprachende wieder `true` liefert. (Exakter Faktor 1.8 ist eine Heuristik — Feinjustierung ggf. nach Praxiserfahrung nötig, siehe oben.)
- [x] Staubsauger als lautere Bandbreite — Schwellwert skaliert proportional mit dem gemessenen Ruhepegel, keine feste Obergrenze im Code.
- [x] Leiser Raum: keine Regression — verifiziert per Klemmwert-Logik: liegt `noise_floor × 1.8` unter 700, greift die `configured_min_threshold_`-Untergrenze und der Schwellwert bleibt exakt 700, identisch zum bisherigen Fixwert.
- [x] Automatische Anpassung pro Gerät/Raum ohne YAML-Wert — bestätigt: `silence_threshold: 700` in beiden espHome-*.yaml-Dateien unverändert, dient nur noch als Startwert/Untergrenze.

#### Robustheit / Fallback
- [x] Absoluter 8s-Fallback auch wenn `speech_seen_` bereits `true` ist — **war vor diesem Feature nicht gegeben** (dokumentierter Befund im Tech Design C.5), jetzt in `loop()` nachgerüstet: dritter, von `speech_seen_` unabhängiger Timeout-Check beendet die Utterance per `end_utterance_()` spätestens nach `listen_timeout_ms_`.
- [x] Pegeländerung während laufender Konversation ab nächster "Hey Jarvis"-Aktivierung berücksichtigt — bestätigt: `noise_floor_estimate_` läuft in jedem IDLE-Zustand weiter, `begin_utterance_()` liest den aktuellen Wert bei jedem `start()`.

#### Kein Nutzer-seitiger Konfigurationsaufwand
- [x] Kein manueller Kalibrierschritt — Noise-Floor-Schätzung läuft transparent im Hintergrund, kein neuer Setup-Flow.
- [x] Kein raumspezifischer Fixwert nötig — bestätigt (siehe oben).

### Edge Cases Status

- [x] Geräusch startet mitten in der Aufnahme — Schwellwert ist für die Utterance eingefroren (niedriger, vor-Geräusch-Wert); ein neu einsetzendes Geräusch wird eher als "Sprache geht weiter" gewertet als fälschlich zum vorzeitigen Abbruch zu führen (sichere Richtung).
- [x] Sehr leiser Nutzer bei moderatem Hintergrund — bekannte Grenze laut Spec, kein Regressionsrisiko durch dieses Feature; Fallback bleibt der (jetzt garantierte) 8s-Timeout.
- [x] Extreme Nahfeld-Geräusche (Staubsauger am Gerät) — durch das neue absolute Sicherheitsnetz (siehe oben) jetzt tatsächlich garantiert kontrolliert, nicht nur wie in der ursprünglichen (fehlerhaften) Annahme des Specs.
- [x] Gerätewechsel Büro ↔ Küche — beide Geräte führen unabhängige `WyomingSatellite`-Instanzen mit eigenem `noise_floor_estimate_`, keine geteilte Zustandsvariable zwischen Geräten.
- [x] Reflash/Neustart — `setup()` initialisiert `noise_floor_estimate_` und `configured_min_threshold_` frisch aus dem YAML-Wert (700) bei jedem Boot.

### Security Audit Results

**Firmware-Feature, keine neue Netzwerk-/Auth-Oberfläche:**
- [x] Keine neuen TCP/Socket-Eingänge, keine Änderung an der bestehenden Wyoming-Framing-/Parsing-Logik.
- [x] Keine neuen Config-/Persistenz-Felder, kein neuer Angriffsvektor über YAML oder OTA.
- [x] Alle neuen Werte sind RAM-only, geräteintern; keine Übertragung an Gateway/n8n.
- [x] Kein Integer-Overflow-Risiko bei der Schwellwert-Berechnung geprüft: RMS-Maximum für int16-Samples (32767) × Faktor 1.8 ≈ 58981, liegt innerhalb `uint16_t`-Bereich (max 65535).

### Bugs Found

#### BUG-1: Kontinuierliche Heap-Allokation im IDLE-Pfad (behoben während QA)
- **Severity:** Medium
- **Steps to Reproduce:**
  1. Code-Review von `on_mic_data_()` in der ersten Implementierung
  2. Für jeden Mikrofon-Frame im `IDLE`-Zustand (d.h. praktisch permanent, solange das Gerät nicht gerade eine Utterance aufnimmt) wurde ein `std::vector<uint8_t>` für die 32→16-Bit-Konvertierung heap-alloziert, nur um daraus die RMS für die Noise-Floor-Schätzung zu berechnen.
  3. Erwartet: laut Technical Requirements darf die Berechnung "die bestehende Audio-Pipeline nicht messbar verlangsamen" — eine dauerhafte Heap-Allokation alle 16ms, für die gesamte Betriebszeit des Geräts, ist auf einem ressourcenbeschränkten ESP32-S3 ein Fragmentierungsrisiko und widerspricht dieser nicht-funktionalen Anforderung.
  4. Actual (vor Fix): `pcm16`-Vektor wurde auch im IDLE-Pfad aufgebaut, obwohl nur die Summe der Quadrate benötigt wird.
- **Fix:** IDLE-Pfad berechnet die Summe der Quadrate jetzt direkt aus den Rohbytes in einer Schleife ohne Zwischenpuffer; `update_noise_floor_()` nimmt `sum_sq`/`num_samples` statt eines Sample-Zeigers entgegen. CAPTURE-Pfad (der `pcm16` tatsächlich braucht, um es ans Gateway zu senden) unverändert.
- **Verifiziert:** `esphome compile` für beide Geräte-Configs erneut erfolgreich, RAM/Flash-Nutzung unverändert (~19.4% RAM / ~35.1% Flash).
- **Priority:** Fixed before deployment

#### BUG-2: Veraltete Doku-Kommentare zu `silence_threshold` (behoben während QA)
- **Severity:** Low
- **Steps to Reproduce:**
  1. `components/wyoming_satellite/README.md` und `espHome.example.yaml` beschrieben `silence_threshold` noch als festen RMS-Schwellwert ("below which a frame = silence", "speech > 700 RMS") — nach diesem Feature ist es nur noch Startwert + Untergrenze für die adaptive Schätzung.
- **Fix:** Beide Kommentare aktualisiert, verweisen auf PROJ-57.
- **Priority:** Fixed before deployment

### Summary
- **Acceptance Criteria:** 8/8 passed (Logik-Verifikation; akustische Feinabstimmung auf Hardware steht als Nacharbeit aus, siehe oben)
- **Edge Cases:** 5/5 passed
- **Bugs Found:** 2 total (0 critical, 0 high, 1 medium — fixed, 1 low — fixed)
- **Security:** Pass — keine neue Angriffsfläche
- **Production Ready:** YES
- **Recommendation:** Deploy. Nach dem ersten Flash auf Büro/Küche empfiehlt sich eine kurze Praxisbeobachtung (Lüfter/Dunstabzugshaube laufen lassen, Utterance testen), um den Margin-Faktor 1.8 bei Bedarf nachzujustieren — das ist eine Tuning-Nacharbeit, kein Blocker.

## Deployment

**Deployed:** 2026-07-03
**Geräte:** HA Voice PE Büro + Küche — beide via OTA vom Nutzer geflasht (kein Gateway-/n8n-Deploy nötig, reine Firmware-Änderung).
**Verifikation:** Vom Nutzer nach dem Flash bestätigt — Anwendung funktioniert gemäß Spezifikation (adaptiver Noise-Floor bei Hintergrundgeräuschen, kein Hängenbleiben, keine Regression im leisen Raum).
**Bekannte Nacharbeit:** Der Margin-Faktor 1.8 (`NOISE_MARGIN_FACTOR` in `wyoming_satellite.h`) ist eine Heuristik aus dem Tech Design; sollte sich in der Praxis eine zu aggressive/zu lasche Trennung zeigen, ist er der erste Tuning-Punkt (kein neuer Deploy-Zyklus nötig, nur Reflash mit angepasstem Wert).
