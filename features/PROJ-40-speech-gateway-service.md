# PROJ-40: Speech Gateway Service

## Status: Planned
**Created:** 2026-05-21
**Last Updated:** 2026-05-21

## Dependencies
- Requires: PROJ-1 (User Authentication) — JWT-Validierung für WebApp-Clients
- Required by: PROJ-41 (WebApp Voice Interface) — konsumiert STT- und Full-Voice-Endpunkt
- Required by: PROJ-42 (HA Voice Integration) — konsumiert den Wyoming-Endpunkt
- Extended by: PROJ-43 (Speaker Recognition) — wird in diesen Service integriert
- Depends on: alice-chat-stream — interner AI-Pipeline-Endpunkt
- Depends on: wyoming-piper — TTS-Service (bestehender Container)

## User Stories

- Als Nutzer möchte ich ein Mikrofon-Icon in der WebApp drücken, sprechen und
  den transkribierten Text als Eingabeprompt sehen, damit ich Sprache statt
  Tastatur zur Texteingabe verwenden kann.

- Als Nutzer möchte ich ein Audio-Icon in der WebApp drücken und ein vollständiges
  Sprachgespräch mit Alice führen — ohne Texteingabe oder Textausgabe — damit
  ich Alice hands-free bedienen kann.

- Als Nutzer möchte ich, dass die Sprachausgabe beginnt, sobald Alice den ersten
  vollständigen Satz generiert hat, damit die gefühlte Latenz kürzer ist.

- Als Nutzer möchte ich Alice durch Sprechen unterbrechen können, damit wir eine
  natürliche Konversation führen können.

- Als Nutzer möchte ich, dass das Gespräch nach einer vollständigen Antwort offen
  bleibt und ich direkt weiterreden kann, ohne erneut ein Icon zu drücken.

- Als Nutzer möchte ich über ein HA Voice Device im Wohnzimmer mit Alice sprechen
  — nicht nur für HA-Steuerung, sondern für beliebige Fragen — mit denselben
  Gesprächsfähigkeiten wie über die WebApp.

- Als Nutzer möchte ich bei Fehlern immer eine gesprochene Rückmeldung erhalten,
  damit ich nie vor einem stillen Gerät stehe.

- Als Admin möchte ich HA Voice Devices über eine Konfigurationsdatei festen
  Nutzern zuordnen, damit Anfragen vom richtigen Nutzerprofil bearbeitet werden.

## Acceptance Criteria

### Modus 1 — STT-Endpunkt (WebApp, Mikrofon-Icon)
- [ ] Der Gateway exponiert einen WebSocket-Endpunkt (z.B. `/ws/stt`) für
      reine Transkription
- [ ] Client sendet fertig aufgezeichnete Audio-Datei (push-to-talk)
- [ ] Gateway liefert den transkribierten Text zurück; kein KI-Aufruf, kein TTS
- [ ] Authentifizierung via JWT (Header oder Query-Parameter)

### Modus 2 — Full-Voice-Pipeline (WebApp, Audio-Icon)
- [ ] Der Gateway exponiert einen WebSocket-Endpunkt (z.B. `/ws/voice`) für
      die vollständige Sprachkonversation
- [ ] Client sendet fertig aufgezeichnete Audio-Datei; Gateway übernimmt
      STT → alice-chat-stream → Piper TTS → Audio zurück
- [ ] Keine Textausgabe — ausschließlich Audio-Antwort
- [ ] Authentifizierung via JWT

### Modus 3 — Wyoming-Endpunkt (HA Voice Device)
- [ ] Der Gateway exponiert einen Wyoming-kompatiblen Endpunkt (Port 10300)
      und ersetzt damit den wyoming-whisper-Container vollständig
- [ ] HA Voice Devices können nach Wakeword-Erkennung Audio an den Gateway
      senden; der Gateway führt dieselbe Full-Voice-Pipeline wie Modus 2 aus
- [ ] Jede Device-ID wird über eine Konfigurationsdatei (YAML/JSON,
      in Docker-Volume gemountet) einem Nutzer (user_id) zugeordnet
- [ ] Unbekannte Device-IDs erhalten eine gesprochene Fehlerantwort

### Sentence-Level TTS Streaming (Modus 2 + 3)
- [ ] LLM-Token-Stream wird zu vollständigen Sätzen akkumuliert
      (Trennung bei `.`, `!`, `?`, Zeilenumbruch)
- [ ] Jeder vollständige Satz wird sofort an Piper TTS übergeben —
      ohne auf die vollständige KI-Antwort zu warten
- [ ] TTS-Audio-Chunks werden sofort an den Client gestreamt
- [ ] Satz 2 wird in Piper verarbeitet während Satz 1 noch abgespielt wird
      (Pipeline-Parallelismus)

### Barge-In / Interrupt (Modus 2 + 3)
- [ ] Client kann jederzeit während eines laufenden TTS-Streams Audio senden
      (WebApp: explizites `interrupt`-Event; HA Voice: eingehende Audio-Aktivität)
- [ ] Gateway bricht sofort ab: laufender Ollama-Stream wird gestoppt,
      ausstehende TTS-Chunks werden verworfen
- [ ] Gateway startet unmittelbar den STT-Prozess für die neue Eingabe
- [ ] Die Konversations-Session bleibt erhalten (gleiche session_id)

### Continued Conversation (Modus 2 + 3)
- [ ] Nach vollständiger TTS-Ausgabe bleibt die Session offen und wartet
      auf neue Spracheingabe
- [ ] Session endet automatisch nach konfiguriertem Silence-Timeout
      ohne neue Eingabe (Standard: 30s)
- [ ] Session endet sofort wenn alice-chat-stream ein `conversation_end`-Event
      sendet (z.B. bei Abschluss-Phrasen wie "Danke")
- [ ] Client kann die Session aktiv beenden (WebSocket-Close oder
      explizites Stop-Event)
- [ ] Der WebApp-Client wird über Zwischenstatus informiert:
      `stt_complete`, `ai_processing`, `tts_generating`, `session_ended`

### Fehlerbehandlung
- [ ] Bei jedem Fehler (STT-Fehler, KI-Timeout, TTS-Fehler) liefert der
      Gateway eine gesprochene Fehlerantwort auf Deutsch
- [ ] KI-Timeout ist konfigurierbar (Standard: 15s)
- [ ] Einzige Ausnahme: Fällt Piper TTS selbst aus, wird der Fehler geloggt
      und die Verbindung geschlossen (TTS ist Voraussetzung für gesprochene Fehler)
- [ ] Ungültige oder abgelaufene JWTs werden mit einer WS-Fehlermeldung
      abgelehnt — kein STT, kein KI-Aufruf

### Allgemein
- [ ] Mehrere Clients können gleichzeitig Anfragen stellen; kein globaler Lock
- [ ] Der Gateway verwendet die TITAN X GPU
      (ID: `GPU-ed6554a1-fe67-5286-11c3-a19c2f3554a6`)
- [ ] STT: faster-whisper large-v3, Deutsch als Standardsprache

## Edge Cases

- **Stille / kein Sprachinhalt**: Whisper liefert leeres Transkript →
  Gateway antwortet mit "Ich habe nichts verstanden, bitte wiederholen."
- **Audio zu kurz (< 0.5s)**: Gateway verwirft ohne Whisper-Aufruf,
  gesprochene Rückmeldung
- **Unbekannte Device-ID (Wyoming)**: Gesprochene Fehlerantwort, kein KI-Aufruf
- **alice-chat-stream nicht erreichbar**: Gesprochene Fehlerantwort nach Timeout;
  andere laufende Sessions bleiben unberührt
- **Barge-In bei letztem TTS-Satz**: Bereits gesendete Audio-Chunks werden
  im Client zu Ende abgespielt; keine weiteren Chunks werden gesendet
- **conversation_end während Barge-In**: Laufende neue Eingabe hat Vorrang;
  conversation_end wird ignoriert
- **Silence-Timeout feuert während Nutzer gerade beginnt zu sprechen**:
  Eingehende Audio-Aktivität setzt den Timeout zurück
- **Client trennt Verbindung mid-stream**: Laufende STT/KI/TTS-Prozesse
  werden abgebrochen, Ressourcen freigegeben
- **HA Voice Device unterstützt kein Barge-In**: Gerät sendet kein Audio
  während TTS läuft → kein Interrupt; Conversation läuft normal zu Ende
  (firmware-seitige Einschränkung, nicht Gateway-Fehler)

## Technical Requirements

- **Performance**: End-to-End < 3s (WebApp), < 4s (HA Voice Device)
- **Concurrency**: Mehrere gleichzeitige Sessions; graceful degradation
  bei Ressourcenengpass
- **GPU**: TITAN X — gleiche Zuweisung wie bisheriger wyoming-whisper
- **Ports**: 10300 (Wyoming), 10301 (WebSocket, WebApp)
- **Sprache**: Deutsch (Standard); konfigurierbar per Umgebungsvariable
- **Container**: Ersetzt wyoming-whisper vollständig
- **Konfiguration**: Device→User-Mapping als YAML/JSON in Docker-Volume;
  Timeouts als Umgebungsvariablen
- **Sicherheit**: Nur im VPN erreichbar; JWT für WebApp;
  Wyoming-Endpunkt vertraut internem Docker-Netz

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
