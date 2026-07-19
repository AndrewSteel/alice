# PROJ-70: Browser-Sprachmodi — Adaptiver Noise-Floor

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Dependencies
- Requires: PROJ-69 (Voice-Hooks Silence-Detection-Extraktion) — diese Spec erweitert den dort extrahierten gemeinsamen Hook um adaptive Kalibrierung, statt erneut in zwei Dateien zu duplizieren.
- Verwandt: PROJ-57 (On-Device VAD Noise Robustness, Deployed) — gleiches Grundproblem (fester RMS-Schwellwert reagiert schlecht auf Umgebungsgeräusch) für das ESPHome-Gerät bereits gelöst; diese Spec überträgt das Prinzip auf den Browser, mit angepasster Kalibrierungsstrategie (siehe Kontext).
- Explizit **nicht** Teil dieser Spec: Trennung von Nutzer-Stimme und sprachähnlichem Hintergrund (TV/Radio) — das ist PROJ-58, ein separates Quelltrennungsproblem.

## Kontext

Anders als das ESPHome-Gerät (PROJ-57) hat der Browser keine dauerhafte Idle-Hörphase, in der das Mikrofon bereits läuft, bevor eine Aufnahme beginnt — das Mikrofon wird erst beim Start einer Aufnahme (Mode 1) bzw. beim Öffnen des Voice-Overlays (Mode 2) aktiviert. Die Kalibrierung kann daher nicht wie bei PROJ-57 kontinuierlich im Hintergrund vor dem Trigger laufen, sondern nutzt ein kurzes Kalibrierungsfenster zu Beginn jeder Aufnahme.

## User Stories
- Als Nutzer möchte ich Alice per Sprache auch bei laufendem Lüfter, offenem Fenster mit Straßenlärm oder ähnlichem Dauergeräusch nutzen können, ohne dass die Aufnahme unnötig lange auf die feste 900ms-Stille wartet.
- Als Nutzer möchte ich, dass sich in einem leisen Raum nichts am bisherigen, bereits funktionierenden Verhalten ändert.
- Als Nutzer möchte ich keinerlei manuellen Kalibrierschritt durchführen ("bitte kurz still sein") — die Anpassung soll transparent im Hintergrund jeder Aufnahme passieren.

## Acceptance Criteria
- [ ] Der gemeinsame Silence-Detection-Hook (PROJ-69) misst zu Beginn jeder Aufnahme ein kurzes Kalibrierungsfenster (Richtwert 300–500ms, final in `/architecture`) als Ambient-Noise-Baseline, bevor die eigentliche Sprach-/Stille-Erkennung aktiv wird.
- [ ] Der aktive Sprache-Schwellwert wird aus `noise_floor × Margin-Faktor` berechnet und nach unten auf den heutigen Fixwert (`SILENCE_THRESHOLD = 0.01`) begrenzt — in einem leisen Raum bleibt das Verhalten exakt identisch zu heute (keine Regression).
- [ ] Der Schwellwert wird nach dem Kalibrierungsfenster für den Rest der laufenden Aufnahme eingefroren (verhindert, dass die eigene Stimme des Nutzers die Schätzung verfälscht) — analog zu PROJ-57.
- [ ] Beide Modi (Push-to-Talk und Vollduplex) nutzen dieselbe Kalibrierungsstrategie (kurzes Fenster pro Aufnahme/Turn, kein Unterschied zwischen den Modi).
- [ ] Bei einem Dauergeräusch, das über dem heutigen Fixwert liegt (z. B. Lüfter, Straßenlärm), endet die Aufnahme innerhalb der üblichen Stille-Zeitspanne (~900ms) nachdem der Nutzer aufgehört hat zu sprechen — nicht erst durch den Server-seitigen Gateway-Timeout (30s).
- [ ] Kein manueller Kalibrierschritt, keine neue UI — Verhalten ist für den Nutzer transparent.

## Edge Cases
- Nutzer beginnt sofort zu sprechen, ohne Pause vor dem Sprechbeginn (Kalibrierungsfenster erfasst bereits die eigene Stimme statt reinem Umgebungsgeräusch): bekannte Grenze, führt im schlimmsten Fall zu einem zu hohen Schwellwert für diese eine Aufnahme — kein Blocker, analog zur entsprechenden Grenze in PROJ-57.
- Umgebungsgeräusch ändert sich merklich während einer laufenden Aufnahme (z. B. Tür wird geöffnet), nachdem der Schwellwert bereits eingefroren wurde: keine Anpassung innerhalb derselben Aufnahme, wird erst bei der nächsten Aufnahme/dem nächsten Turn berücksichtigt (identisch zu PROJ-57s Design-Entscheidung).
- Sehr kurze Aufnahme (Nutzer tippt Mikrofon-Button an und lässt sofort wieder los, kürzer als das Kalibrierungsfenster): Kalibrierung darf nicht blockieren oder abstürzen — Fallback auf den festen Schwellwert (0.01) bei unzureichenden Samples.
- Extrem lautes/variables Umgebungsgeräusch (z. B. direkt neben einem Staubsauger), bei dem auch der adaptive Schwellwert keine zuverlässige Trennung erlaubt: bestehender Gateway-seitiger 30s-Timeout bleibt das ultimative Sicherheitsnetz — kein Hängenbleiben, keine neue Absicherung nötig, da diese bereits serverseitig existiert.
- Mode 2 (Vollduplex, mehrere Turns pro Sitzung): jeder Turn kalibriert unabhängig neu, kein Zustand wird zwischen Turns übernommen (bewusst einfacher als eine kontinuierliche Zwischen-Turn-Schätzung, siehe Kontext).

## Technical Requirements (optional)
- Änderung erfolgt ausschließlich im gemeinsamen Hook aus PROJ-69 — kein Protokoll-/Gateway-Change, keine neuen WebSocket-Nachrichtentypen.
- Margin-Faktor und Länge des Kalibrierungsfensters sind Heuristik-Werte (analog zu PROJ-57s `NOISE_MARGIN_FACTOR`), final in `/architecture` festgelegt und ohne neuen Spec-Zyklus nachjustierbar.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
