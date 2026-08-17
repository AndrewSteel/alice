# PROJ-64: Voice-Enrollment — Offene Sprachauswahl

## Status: Deployed
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Implementation Notes
- `alice-speech-gateway/app/config.py`: open `ask_sprache` prompt, third duplicated `LANGUAGES` config (de+en), `match_language()` case-insensitive substring matcher against all configured `displayName_de` values.
- `alice-speech-gateway/app/enrollment.py`: `ASKING_SPRACHE` state uses `match_language()`, stores ISO code in `self.sprache` (default `"de"`), always advances to `DONE` — no-match falls back to German with an info log, no hang.
- `stt.py`/`SPEECH_LANGUAGE` untouched (out of scope, confirmed by QA).
- QA: READY, 0 blocking bugs. 2 Low observations (first-match-wins on multi-language transcripts; substring match can trigger on superstrings like "Deutschland") — harmless, not fixed.

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

#### A) Data Flow

```
ESPHome-Enrollment-Dialog (alice-speech-gateway, enrollment.py)
State ASKING_SPRACHE
  → offene Frage ohne Aufzählung ("Welche Sprache möchtest du verwenden?")
  → Transkription wird gegen die displayName_de-Werte aller in der lokalen Config-Kopie
    (dritte Duplizierung, gleiches Muster wie PROJ-63) konfigurierten Sprachen geprüft
  → Treffer → ISO-639-1-Code in self.sprache gespeichert
  → kein Treffer / unverständlich → Fallback "de", Enrollment schließt normal ab (kein Hängenbleiben)
```

#### B) Data Model

Kein neues Schema — `self.sprache` speichert künftig den ISO-Code (z. B. `"fr"`) statt des deutschen Worts, konsistent mit der PROJ-63-Migration. Der Wert landet wie bisher in `alice.user_profiles.preferences.sprache`.

#### C) Tech Decisions

- **Keyword-Matching statt Spracherkennung:** Bewusste Design-Entscheidung (explizit als Non-Goal in den Technical Requirements benannt) — STT bleibt Deutsch-fixiert, kein NLU/Spracherkennungs-Modell. Passt zu einem seltenen, kurzen Enrollment-Dialog, bei dem Latenz und Robustheit wichtiger sind als freie Spracherkennung.
- **Dritte lokale Config-Kopie statt Netzwerkaufruf während des Dialogs:** Enrollment ist ein Echtzeit-Sprachgespräch — ein synchroner HTTP-Request mitten im Dialog würde vermeidbare Latenz/Fehlerfläche für einen Wert einführen, der sich nur beim Deploy ändert. Gleiches Muster wie die Config-Duplizierung in PROJ-63.
- **Kein Zusammenhang mit PROJ-62:** Dieser Flow ist rein ESPHome/HA-Voice-seitig, keine UI beteiligt — unabhängig von der Frontend-i18n-Spec umsetzbar.
- **Fallback auf Deutsch bei jedem Nicht-Treffer** (unbekannte Sprache, Config-Drift, missverstandene STT-Ausgabe) — verhindert ein Hängenbleiben im Enrollment-State; Nutzer kann seine Sprache später jederzeit über Mein Profil (PROJ-62/63) korrigieren.

#### D) Dependencies

Keine neuen Pakete — Änderung konzentriert sich auf bestehenden Code in `enrollment.py`/`config.py`.

## QA Test Results

**Tested:** 2026-07-19
**Scope:** `config.py` + `enrollment.py` in `alice-speech-gateway` (static/logical verification — no live STT/audio pipeline in this environment)
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### AC-1: `ask_sprache` becomes an open question without enumeration
- [x] `config.SPEECH_ENROLLMENT["ask_sprache"]` = `"Welche Sprache möchtest du verwenden?"` (config.py:166) — open question, no list of concrete languages. PASS

#### AC-2: `ASKING_SPRACHE` matches against `displayName_de` of ALL configured languages
- [x] `enrollment.py:172` calls `config.match_language(text)` instead of the old hardcoded `"englisch"/"english"` check. PASS
- [x] `match_language` (config.py:136-152) iterates `LANGUAGES` and tests `lang["displayName_de"].lower() in text` for every entry — genuinely dynamic against all configured languages, verified by reading the implementation (not just the name). PASS

#### AC-3: `self.sprache` stores the ISO-639-1 code, not the German word
- [x] Default changed to `sprache: str = "de"` (enrollment.py:91).
- [x] On match, `self.sprache = matched` where `matched` is `lang["code"]` (ISO code). On no-match, `self.sprache = config.DEFAULT_LANGUAGE_CODE` (`"de"`). Never stores the word form. PASS

#### AC-4: No match → fallback to `"de"`, no hang, enrollment completes
- [x] `match_language` returns `None` when no `displayName_de` appears; branch sets `self.sprache = DEFAULT_LANGUAGE_CODE` and logs an informational message (enrollment.py:173-180).
- [x] Both match and no-match paths unconditionally set `self._state = _State.DONE` (enrollment.py:183) → `is_done` becomes True → no hang. Verified by reading the full state machine: `ASKING_ANREDE` always advances to `ASKING_SPRACHE`, which always advances to `DONE`. There is no path that re-enters `ASKING_SPRACHE`. PASS

#### AC-5: Language config duplicated locally — no network call during the live dialog
- [x] `LANGUAGES` + `DEFAULT_LANGUAGE_CODE` defined locally in config.py:115-133, same shape (`code`, `displayName_de`, `displayName_en`, `llm_instruction`) as the sibling copies in `alice-auth/main.py:144` and `alice-chat-stream/app/memory.py:42`. This is the third duplication as specified.
- [x] Grep for `httpx`/`requests`/`aiohttp`/`urllib`/`http.client` in both `enrollment.py` and `config.py`: none found. The `ASKING_SPRACHE` path performs pure local string matching. PASS

#### AC-6: Existing de+en behaviour unchanged (saying "Englisch" still yields `en`)
- [x] Empirically traced: `match_language("Ich möchte Englisch")` → `"en"`; `match_language("Ich spreche Deutsch")` → `"de"`. PASS

### Edge Cases Status

#### EC-1: Named language not in local config copy (config drift) → fallback + log
- [x] `match_language("Französisch bitte")` → `None` → `sprache="de"`, informational log emitted (enrollment.py:174-179). No error state. PASS

#### EC-2: STT mis-transcribes foreign language name → fallback, no crash
- [x] Any unrecognised transcript yields `None` → `"de"`. No exception path. PASS

#### EC-3: Very short / quiet answer with no language word → fallback to German
- [x] `match_language("äh was?")` → `"de"`; `match_language("")` → `"de"` (empty string: `"deutsch" in ""` is False, safe). PASS

#### EC-4: Enrollment for role "Gast" → identical behaviour
- [x] The `ASKING_SPRACHE` logic is role-independent; only the final `done_*` prompt key branches on role (enrollment.py:184). PASS

### Regression Check

- [x] `session.sprache` flows into `create_enrolled_user(sprache=session.sprache, ...)` (wyoming_transport.py:328-334) → persisted to `alice.user_profiles.preferences.sprache` as JSON (speaker_db.py:183-191). Since `self.sprache` is now always an ISO code, the downstream value matches what PROJ-63 expects (ISO code, not word form). PASS
- [x] Sibling configs (`alice-auth`, `alice-chat-stream`) confirmed consistent (de+en, same field shape) — no drift introduced. PASS
- [x] `stt.py` / `SPEECH_LANGUAGE` NOT touched: `git diff HEAD` shows zero changes to `stt.py`; `SPEECH_LANGUAGE` (config.py:49) unchanged, STT remains German-fixed as required by the spec's Non-Goal. PASS
- [x] `python3 -m py_compile` on both changed files: PASS.

### Security Audit Results

**Docker feature (unauthenticated ESPHome voice-enrollment dialog):**
- [x] No new attack surface: the language selection is local, case-insensitive substring matching of a fixed transcript against a hardcoded list. No injection vector (the transcript is not used in any SQL/shell/HTTP context here; the resolved value is a constant ISO code from the config list, not the raw transcript).
- [x] The persisted `sprache` value can only ever be one of the configured `code` constants or the `"de"` fallback — the user's raw spoken text never reaches the DB, so no stored-injection risk via this path.
- [x] No secrets, no network calls, no new env vars introduced.
- Note: enrollment itself remains gated upstream (admin-only trigger, `enrollment_not_admin` guard) — unchanged by this feature.

**Security verdict: PASS.**

### Bugs Found

None blocking. Two low-severity observations (do not fail any AC):

#### OBS-1: First-match-wins ordering on multi-language transcripts
- **Severity:** Low
- **Detail:** `match_language` returns the first `LANGUAGES` entry whose `displayName_de` is a substring. A transcript mentioning several language names (e.g. "Weder Deutsch noch Englisch") resolves to the first one in list order (`de`), not the intended one. Given the enrollment prompt asks for a single language and any ambiguity falls back sensibly, and the user can change language later via Mein Profil, this is acceptable. No fix required for deployment.

#### OBS-2: Substring match can trigger on a superstring word
- **Severity:** Low
- **Detail:** Substring matching means e.g. "Deutschland" matches `de`. In practice a language answer is a language name, and the fallback/self-correction path makes this harmless. No fix required.

### Could Not Be Verified Without Live Hardware
- Actual Whisper STT transcription quality for spoken language names (German-fixed STT rendering of e.g. "Französisch") — logic-only verification performed; runtime behaviour depends on the STT model output feeding `process_turn`.
- End-to-end Wyoming audio turn handling and embedding extraction (`extract_embedding`) — out of scope of the changed code and not exercisable here.

### Summary
- **Acceptance Criteria:** 6/6 passed
- **Edge Cases:** 4/4 passed
- **Bugs Found:** 0 blocking (2 low-severity observations)
- **Security:** PASS (no new attack surface; local string matching, no injection vector)
- **Production Ready:** YES
- **Recommendation:** READY — deploy. Observations OBS-1/OBS-2 are optional nice-to-haves, not blockers.

## Deployment
Deployed 2026-07-20 (manual production deploy by Andrew Steel, frontend bundle covering PROJ-60-62/66-71). Confirmed working in production.
