# PROJ-64: Voice-Enrollment — Offene Sprachauswahl

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Dependencies
- Requires: PROJ-63 (Backend Sprachcode-Offenheit) — nutzt dieselbe Sprachkonfiguration (Code, `displayName_de`, LLM-Instruktion), dupliziert nach demselben Muster in `alice-speech-gateway`.
- Requires: PROJ-43 (Speaker Recognition, Deployed) — Enrollment-Flow (`enrollment.py`) ist Teil dieses bestehenden Features.
- Kein Zusammenhang mit PROJ-62 (Frontend i18n) — dieser Flow ist rein sprachbasiert (ESPHome/HA-Voice), keine UI beteiligt.

## User Stories
- Als Nutzer, der sich per Sprache neu registriert (Enrollment), möchte ich meine bevorzugte Sprache frei nennen können (z. B. "Französisch"), statt nur zwischen Deutsch und Englisch wählen zu können.
- Als Betreiber möchte ich, dass eine neue Sprache aus PROJ-63 automatisch auch im Voice-Enrollment erkannt wird, ohne `enrollment.py` erneut anzufassen (nur die geteilte Config erweitern).
- Als Nutzer, der eine nicht konfigurierte oder unverständliche Antwort gebe, möchte ich, dass das Enrollment nicht hängen bleibt, sondern sinnvoll auf Deutsch zurückfällt.

## Acceptance Criteria
- [ ] `config.SPEECH_ENROLLMENT["ask_sprache"]` wird zu einer offenen Frage ohne Aufzählung konkreter Sprachen (z. B. "Welche Sprache möchtest du verwenden?").
- [ ] `EnrollmentSession.process_turn()` (State `ASKING_SPRACHE`, `enrollment.py:166-173`) prüft die Transkription gegen die `displayName_de`-Werte aller in der geteilten Sprachkonfiguration (PROJ-63) konfigurierten Sprachen, statt hartcodiert nur `"englisch"`/`"english"` zu matchen.
- [ ] `self.sprache` speichert den ISO-639-1-Code (z. B. `"fr"`) statt des deutschen Wortes — konsistent mit der PROJ-63-Migration.
- [ ] Kein Treffer in der Transkription (z. B. unverständliche Antwort, nicht konfigurierte Sprache genannt): Fallback auf `"de"`, kein Hängenbleiben im State, Enrollment schließt normal ab.
- [ ] Die Sprachkonfiguration ist in `alice-speech-gateway` dupliziert vorhanden (gleiches Muster wie `alice-auth`/`alice-chat-stream` aus PROJ-63) — keine Netzwerkabfrage während des laufenden Enrollment-Dialogs.
- [ ] Bestehendes Verhalten mit nur Deutsch+Englisch konfiguriert bleibt unverändert (Nutzer, der "Englisch" sagt, bekommt weiterhin `en` gesetzt).

## Edge Cases
- Nutzer nennt eine Sprache, die zwar ISO-Code-technisch existiert, aber nicht in der lokalen Config-Kopie von `alice-speech-gateway` eingetragen ist (Config-Drift zwischen Containern): kein Treffer, Fallback auf Deutsch — kein Fehlerzustand, aber im Log vermerkt.
- Deutsch-fixierte STT transkribiert einen fremdsprachigen Sprachnamen falsch (z. B. "Französisch" wird als ähnlich klingendes Wort erkannt): führt zu Fallback auf Deutsch statt Absturz; Nutzer kann seine Sprache später jederzeit über Mein Profil (PROJ-62/PROJ-63) ändern.
- Sehr kurze oder leise Antwort ohne erkennbares Sprachwort: wie oben, Fallback auf Deutsch.
- Enrollment für Rolle "Gast": identisches Verhalten wie für "Nutzer", keine rollenspezifische Einschränkung der Sprachauswahl.

## Technical Requirements (optional)
- Änderungen konzentrieren sich auf `enrollment.py` (Matching-Logik, State `ASKING_SPRACHE`) und `config.py` (Prompt-Text, Sprachkonfiguration).
- Keine Änderung an `stt.py` oder `SPEECH_LANGUAGE` — STT bleibt Deutsch-fixiert (siehe Entscheidung: Keyword-Matching statt dynamischer Spracherkennung).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
