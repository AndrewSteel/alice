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
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
