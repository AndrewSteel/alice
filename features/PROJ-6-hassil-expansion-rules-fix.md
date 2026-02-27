# PROJ-6: Hassil expansion_rules Compatibility Fix

## Status: Planned

**Created:** 2026-02-27
**Last Updated:** 2026-02-27

## Dependencies

- Requires: PROJ-5 (Hassil Native Library Integration) — `_expand_with_hassil()` must exist in `expand_ha_intents.py`

## Overview

PROJ-5 deployed the hassil-based expansion engine, but in production `Intents.from_dict()` fails for **all** domains with `'list' object has no attribute 'strip'`. The fallback routes every domain to the custom regex path, so PROJ-5 is functionally equivalent to the PROJ-2 baseline — the hassil code path never runs.

**Root cause:** The official HA intents YAML files (downloaded from GitHub) store some `expansion_rules` values as **lists of strings** (e.g., `color: ["rot", "grün", "blau"]`), while hassil's `Intents.from_dict()` expects all `expansion_rules` values to be **template strings** (e.g., `"(rot|grün|blau)"`). The API mismatch is not caught at import time but causes a crash inside `sample_sentence()`.

PROJ-6 fixes `_expand_with_hassil()` to pre-process `expansion_rules` before calling `Intents.from_dict()`: list-type values are converted to hassil-compatible alternative strings. After the fix, the hassil code path runs in production for all domains.

## User Stories

- Als Entwickler möchte ich, dass die hassil-Bibliothek in der Produktion tatsächlich für die Template-Expansion verwendet wird, damit PROJ-5 seinen ursprünglichen Zweck erfüllt.
- Als Entwickler möchte ich, dass `expansion_rules`-Einträge mit Listen-Werten (z.B. `["rot", "grün", "blau"]`) automatisch in hassil-kompatible Alternativ-Strings (`"(rot|grün|blau)"`) umgewandelt werden, damit `Intents.from_dict()` keine `AttributeError`-Exception wirft.
- Als Entwickler möchte ich, dass `expansion_rules`-Einträge mit String-Werten weiterhin unverändert bleiben, damit bestehende hassil-kompatible Einträge nicht korrumpiert werden.
- Als Entwickler möchte ich im Container-Log sehen, dass der `[hassil]`-Pfad für Intents aktiv ist (nicht `[custom]`), damit ich den Systemzustand auf einen Blick erkennen kann.
- Als Entwickler möchte ich, dass der gesamte Sync nach dem Fix in unter 15s abgeschlossen ist, damit die Performance-Anforderung aus PROJ-5 eingehalten bleibt.

## Acceptance Criteria

- [ ] Nach dem Fix erscheint `[hassil]` (nicht `[custom]`) in den Intent-Logs für Domains, deren YAML von `Intents.from_dict()` korrekt verarbeitet wird
- [ ] Keine `AttributeError: 'list' object has no attribute 'strip'`-Warnungen im Container-Log nach `POST /intents/sync`
- [ ] `expansion_rules` mit String-Werten werden unverändert an `Intents.from_dict()` übergeben (kein unnötiges Re-Processing)
- [ ] `expansion_rules` mit Listen-Werten (`list[str]`) werden zu hassil-kompatiblen Alternativ-Strings umgewandelt: `["a", "b", "c"]` → `"(a|b|c)"`
- [ ] Die Signatur und der Return-Typ von `parse_intent_yaml()` bleiben identisch: `(yaml_data: dict, domain: str, max_patterns: int) -> list[dict]`
- [ ] Die Signatur und der Return-Typ von `expand_intent_sentences()` bleiben identisch: `(sentences: list[str], expansion_rules: dict, max_patterns: int) -> list[str]`
- [ ] `{name}`- und `{area}`-Slot-Platzhalter bleiben als Literal-Strings in den expandierten Patterns erhalten
- [ ] `POST /intents/sync` liefert `inserted + updated >= 55` (keine Regression)
- [ ] `GET /health` gibt weiterhin `{"status": "healthy"}` zurück
- [ ] Kein Rebuild des Docker-Images nötig (nur `expand_ha_intents.py` wird geändert; keine neuen Abhängigkeiten)

## Edge Cases

- **String-Wert in expansion_rules** (Normalfall): `"(rot|grün|blau)"` → unverändert übergeben; kein Re-Processing.
- **Einelementige Liste** in expansion_rules: `["rot"]` → `"rot"` (kein Klammern-Overhead für Einzelwert).
- **Leere Liste** in expansion_rules: `[]` → Eintrag überspringen + Log-Warnung; kein Absturz.
- **Liste mit Dict-Einträgen** (z.B. `[{in: "name", out: "name"}]`): String-Wert aus dem `in`-Feld extrahieren; falls nicht möglich, Eintrag überspringen + Log-Warnung.
- **Verschachtelte expansion_rules** (Liste in Liste): nur die erste Ebene normalisieren; innere Strukturen unverändert lassen.
- **Fallback nach wie vor aktiv**: Wenn `Intents.from_dict()` nach dem Fix dennoch wirft (unbekannte zukünftige Änderungen in HA-YAML), greift der bestehende domain-level Fallback auf Custom-Expansion weiter.
- **`_common.yaml`-Regeln ohne passende Domain-Einträge**: Graceful skip, kein Absturz (identisch zu PROJ-5).

## Technical Requirements

- **Einzige Änderungsdatei:** `docker/compose/automations/hassil-parser/expand_ha_intents.py`
- **Keine Änderungen an:** `main.py`, `Dockerfile`, `compose.yml`, `requirements.txt`, Makefile, PostgreSQL-Schema
- **Kein Image-Rebuild erforderlich:** Die Datei wird per Volume-Mount oder direktem `docker cp` aktualisiert — alternativ reicht ein Sync via `sync-compose.sh` + `docker compose up -d --build hassil-parser` (ohne `--no-cache`; Layer-Cache nutzbar)
- **Pre-Processing-Funktion:** Eine neue Hilfsfunktion `_normalize_expansion_rules(rules: dict) -> dict` normalisiert alle Werte im Rules-Dict vor der Übergabe an `Intents.from_dict()`
- **Positionierung:** Die Normalisierung erfolgt **vor** `Intents.from_dict()` innerhalb von `_expand_with_hassil()`; keine Änderung außerhalb dieser Funktion
- **Performance:** `POST /intents/sync` darf nach dem Fix nicht langsamer als 15s sein (Baseline: 11,5s mit custom-path)

---

## Tech Design (Solution Architect)

_To be added by /architecture_

## QA Test Results

_To be added by /qa_

## Deployment

_To be added by /deploy_
