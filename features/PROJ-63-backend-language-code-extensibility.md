# PROJ-63: Backend Sprachcode-Offenheit (alice-auth + alice-chat-stream)

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Dependencies
- Requires: existing `alice.user_profiles.preferences.sprache`-Feld (JSONB, keine bestehende CHECK-Constraint auf DB-Ebene — Einschränkung liegt aktuell nur im Anwendungscode).
- Required by: PROJ-62 (Frontend i18n) — das Sprache-Dropdown in Mein Profil/`CreateUserDialog` bezieht seine Optionsliste über den neuen Endpunkt aus dieser Spec.
- Required by: PROJ-64 (Voice-Enrollment-Spracherkennung) — `alice-speech-gateway/enrollment.py` muss auf dieselben Sprachcodes umgestellt werden.

## User Stories
- Als Betreiber möchte ich eine neue unterstützte Sprache (Code, Anzeigename, LLM-Instruktionstext) durch einen Config-Eintrag + Redeploy hinzufügen können, ohne Datenbankschema oder API-Verträge zu ändern.
- Als Frontend möchte ich die Liste unterstützter Sprachen über einen API-Endpunkt abrufen können, damit das Sprache-Dropdown nie von der Backend-Validierung abweicht.
- Als Nutzer, dessen Profil bereits `sprache: "deutsch"` oder `"englisch"` enthält, möchte ich, dass mein bestehender Wert nach dem Umstieg auf ISO-Codes ohne mein Zutun weiterhin korrekt funktioniert.
- Als System (alice-chat-stream) möchte ich für jede konfigurierte Sprache eine passende Instruktion an den LLM-Systemprompt anhängen können, statt einer binären Deutsch/Englisch-Fallunterscheidung.

## Acceptance Criteria
- [ ] Eine zentrale, statische Sprachkonfiguration existiert in `alice-auth` und in `alice-chat-stream` (je Container dupliziert): pro Sprache `{code (ISO 639-1), displayName_de, displayName_en, llm_instruction}`.
- [ ] `alice-auth`: `PATCH`/Profil-Update-Endpunkte (`main.py:744`, `main.py:1029`) validieren `sprache` gegen die Codes der aktuellen Konfiguration statt gegen die feste Tupel `("deutsch", "englisch")`; ungültiger Code → weiterhin `422` mit Klartext-Fehlermeldung, die die aktuell gültigen Codes nennt.
- [ ] Neuer Endpunkt `GET /api/auth/languages` liefert die konfigurierte Sprachliste (Code + beide Anzeigenamen) für das Frontend-Dropdown.
- [ ] `alice-chat-stream/memory.py`: Die binäre `if sprache == "englisch"`-Verzweigung (Zeile 178) ist durch ein Lookup über die Sprachkonfiguration ersetzt; unbekannter/fehlender Code fällt auf Deutsch zurück (`de`, konsistent mit PRD-Constraint "Sprache: Primär Deutsch").
- [ ] Bestehende `preferences.sprache`-Werte in `alice.user_profiles` werden per einmaligem Migrationsskript von `"deutsch"`/`"englisch"` auf `"de"`/`"en"` umgestellt.
- [ ] `CreateUserDialog` (Admin legt neuen Nutzer an) und `ProfilForm` beziehen ihre Dropdown-Optionen über `GET /api/auth/languages` statt eines hartcodierten Union-Typs (Umsetzung erfolgt im Rahmen von PROJ-62/`/frontend`, hier nur der Endpunkt-Vertrag).
- [ ] Start des Frontends/Backends mit **nur** Deutsch+Englisch konfiguriert verhält sich exakt wie heute (keine Verhaltensänderung ohne Config-Erweiterung).

## Edge Cases
- Sprachcode wird in `alice-auth`, aber (versehentlich) nicht in `alice-chat-stream` konfiguriert (Container-Update nicht synchron ausgerollt): LLM-Prompt-Logik fällt für diesen Code auf Deutsch zurück statt zu fehlern.
- Migrationsskript läuft auf einer Datenbank, in der `sprache` bereits `null` oder ein unbekannter Wert ist (z. B. manuell gesetzt): Skript überschreibt nur exakte Treffer auf `"deutsch"`/`"englisch"`, lässt alles andere unverändert, loggt übersprungene Zeilen.
- Alter Client (gecachtes Frontend-Bundle vor PROJ-62-Deployment) sendet noch `"deutsch"`/`"englisch"` an die Profil-API nach der Migration: Validierung akzeptiert beide alten Wortwerte übergangsweise als Alias für `"de"`/`"en"`, bis der Frontend-Rollout abgeschlossen ist.
- `GET /api/auth/languages` wird von einem nicht eingeloggten Client aufgerufen (Login-Screen-Sprachwahl gibt es laut PROJ-62 nicht, dort zählt nur Browser-Sprache) — Endpunkt ist dennoch öffentlich erreichbar, da er keine Nutzerdaten enthält.
- Sprachkonfiguration enthält einen Code ohne vollständige Übersetzung in PROJ-62 (UI-Text fehlt): kein Blocker für diese Spec, greift der i18n-Fallback aus PROJ-62.

## Technical Requirements (optional)
- Kein neues DB-Schema/keine neue Tabelle — Sprachkonfiguration bleibt Anwendungscode (Python-Dict/JSON-Datei je Container), passend zum Solo-Hobby-Projekt-Rahmen.
- Migrationsskript nach bestehendem Muster (`scripts/proj55-add-thumbnail-path.sh`) als `scripts/proj63-migrate-sprache-codes.sh`.
- `GET /api/auth/languages` erfordert keine Authentifizierung (analog zu anderen öffentlichen Metadaten-Endpunkten), liefert aber keine nutzerbezogenen Daten.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
