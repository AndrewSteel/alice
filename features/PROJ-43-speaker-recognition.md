# PROJ-43: Speaker Recognition (Speaker-ID)

## Status: Planned
**Created:** 2026-06-18
**Last Updated:** 2026-06-18

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

## Acceptance Criteria

### Sprechererkennung
- [ ] Gateway identifiziert Sprecher aus dem Utterance-Audio bevor der LLM-Call erfolgt
- [ ] Erkannter Sprecher (Konfidenz ≥ Schwellenwert) → Session nutzt dessen `user_id` und Rolle
- [ ] Unbekannter Sprecher oder Konfidenz < Schwellenwert → Session nutzt Guest-Rolle
- [ ] Wake-Sound wird ersetzt durch personalisierte Begrüßung: "Hallo {display_name}" (bekannt) bzw. "Hallo Gast, was kann ich für dich tun?" (unbekannt)
- [ ] Binäre Erkennung — keine Rückfrage bei unsicherer Erkennung, direkt Guest-Rolle

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

## Technical Requirements

- **Performance**: Speaker-ID läuft parallel zum STT-Beginn; Ziel: < 500 ms Mehrlatenz gegenüber aktuellem Wake-Sound
- **Hardware**: TITAN X (Embeddings/Speaker-ID, lokal — gemäß PRD-Constraints)
- **Lokal-First**: Kein Cloud-Dienst für Speaker-ID; lokales Embedding-Modell
- **Sprache**: Enrollment-Dialog auf Deutsch (Standard), Antworten nach eingestellter Nutzerpräferenz

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
