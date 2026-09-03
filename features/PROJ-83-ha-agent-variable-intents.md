# PROJ-83: HA-Agent variable Intents — Prozent-Werte, Temperatur, Listen-Eintrag

## Status: Architected
**Created:** 2026-09-03
**Last Updated:** 2026-09-03

## Dependencies
- Requires: PROJ-1 (HA Intent Infrastructure) — Weaviate `HAIntent`-Collection
- Requires: PROJ-3 (HA-First Chat Handler mit Intent-Routing) — HA_FAST/HYBRID/LLM_ONLY-Pfadlogik, Sentence Splitter
- Requires: PROJ-39 (alice-ha-sync Overhaul) — Value-Placeholder-Grundlage (`{value}`/`{temperature}`-Expansion, aktuell auf feste Diskretstufen begrenzt)
- Requires: PROJ-82 (HA-MCP-Server-Evaluierung) — Spike abgeschlossen, Ergebnis: No-Go. PROJ-83 baut auf dem bestehenden n8n/Weaviate-Ansatz auf, kein MCP-Server involviert
- Unabhängig von: PROJ-84 (HA-Agent Area-Context-Weitergabe) — beide hängen von PROJ-82 ab, aber nicht voneinander; Reihenfolge zwischen PROJ-83 und PROJ-84 ist beliebig

## Overview

Der bestehende HA_FAST-Intent-Pfad (PROJ-1/PROJ-3/PROJ-39) erkennt Sprachbefehle über eine Weaviate-`nearText`-Suche gegen **vorab generierte, feste Diskretwerte**: Licht-Helligkeit und Rolladen-Position werden nur in den Stufen 10/25/50/75/100 % indexiert, Heizungs-Temperatur nur in den Ganzzahlstufen 16–26 °C. Sagt Andreas "Rolladen auf 37 Prozent", gibt es dafür kein passendes Weaviate-Objekt — das System matcht auf die nächstliegende vorindexierte Stufe (z. B. 25 oder 50) und führt damit einen **falschen** Wert aus, nicht den tatsächlich gesprochenen.

Zusätzlich werden `{message}`-Pattern (freier Text, z. B. für Listen-Einträge wie "Milch zur Einkaufsliste hinzufügen") von PROJ-39 komplett übersprungen — dafür existiert aktuell kein Erkennungspfad.

PROJ-83 schließt diese Lücke: Licht-Helligkeit, Rolladen-Position und Heizungs-Temperatur akzeptieren beliebige ganzzahlige Werte innerhalb des jeweils gültigen Bereichs (nicht nur die bisherigen festen Stufen), und ein einfacher Einkaufslisten-Eintrag (freier Text, eine vorkonfigurierte Standardliste) wird unterstützt. Alles bleibt im schnellen HA_FAST-Pfad (< 200 ms, kein LLM-Aufruf) — die Werterkennung selbst ist reine Textverarbeitung.

**Zusätzlich entdeckte Sync-Lücke (gehört mit in diesen Scope):** Die drei bestehenden HA-Automationen unter `homeassistant/` (`alice_sync_on_start.yaml`, `alice_sync_on_entity_created.yaml`, `alice_sync_on_entity_removed.yaml`) lösen einen MQTT-Sync (`alice/ha/sync`) bei HA-Neustart sowie beim Erstellen/Löschen einer Entity aus — **nicht** aber, wenn eine bereits bestehende Entity nachträglich für die Assist-Konversation freigeschaltet (oder diese Freigabe entzogen) wird. Ohne einen entsprechenden Trigger bleibt eine neu freigeschaltete Entity bis zum nächsten HA-Neustart oder manuellen Full-Sync unsichtbar für den HA_FAST-Pfad — das würde auch die neuen Werte-Fähigkeiten aus PROJ-83 für frisch freigeschaltete Entities blockieren. PROJ-83 ergänzt daher eine neue HA-Automation (für automatisches Erkennen der Freischaltungs-Änderung) plus ein manuell auslösbares HA-Script (gleiche Wirkung, für den Fall dass der automatische Trigger einen Fall nicht abdeckt).

**Bewusst außerhalb des Scopes** (im Rahmen der Interview-Phase identifiziert und als eigene Roadmap-Einträge vorgemerkt, siehe `features/INDEX.md`):
- **PROJ-100 (Todo-Listen-Agent)**: mehrere benannte Listen ansprechen, Einträge entfernen/abhaken, Liste vorlesen/im Chat anzeigen, Liste bei Bedarf anlegen
- **PROJ-101 (HA-Status-Abfragen)**: allgemeine Zustands-/Werte-Fragen zu beliebigen HA-Entities ("Wie ist der Status der Heizung im Wohnzimmer?") — vermutlich LLM/HYBRID-Pfad, nicht HA_FAST

**Ebenfalls außerhalb des Scopes:**
- Relative Befehle ("Licht etwas heller", "Rolladen ein Stück runter") — brauchen aktuellen Gerätezustand als Referenz + Schrittweiten-Definition, eigene Erweiterung
- Verbesserte Entity-Disambiguierung bei mehreren Kandidaten im selben Raum — das ist PROJ-84s Aufgabe (Area-Context)

## User Stories

- Als Andreas möchte ich sagen "Rolladen im Büro auf 50 Prozent stellen" und der Rolladen fährt exakt auf 50 %, damit ich nicht auf eine der bisherigen fünf Diskretstufen beschränkt bin.
- Als Andreas möchte ich sagen "Licht im Wohnzimmer auf 30 Prozent dimmen" und die Helligkeit wird exakt auf 30 % gesetzt.
- Als Andreas möchte ich sagen "Heizung im Büro auf 21 Grad stellen" und die Zieltemperatur wird exakt auf 21 °C gesetzt, sobald eine Climate-Entity für Assist freigegeben ist.
- Als Andreas möchte ich sagen "Milch zur Einkaufsliste hinzufügen" und der Eintrag erscheint als freier Text auf der Einkaufsliste, ohne dass ich vorher exakte Formulierungen einüben muss.
- Als Andreas möchte ich, dass ein Wert außerhalb des zulässigen Bereichs (z. B. "Heizung auf 45 Grad") **nicht** ausgeführt wird, sondern Alice mir den tatsächlich zulässigen Bereich nennt, damit ich weiß, was stattdessen möglich ist.
- Als Andreas möchte ich, dass wertbehaftete Befehle genauso schnell reagieren wie einfache Befehle (< 200 ms, kein LLM-Aufruf), damit sich die Steuerung nicht langsamer anfühlt als bisher.
- Als Andreas möchte ich, dass eine bestehende Entity automatisch synchronisiert wird, sobald ich sie in HA für Assist freischalte (oder ihr die Freigabe entziehe), damit ich nicht extra an einen HA-Neustart oder manuellen Full-Sync denken muss.
- Als Andreas möchte ich den Sync bei Bedarf auch manuell per HA-Script auslösen können, falls der automatische Trigger einen Fall nicht abdeckt.

## Acceptance Criteria

- [ ] "Rolladen im [Raum] auf X Prozent stellen" mit beliebigem ganzzahligem X zwischen 0–100 setzt die Cover-Position exakt auf X — nicht auf die nächstliegende der bisherigen 5 Diskretstufen
- [ ] "Licht im [Raum] auf X Prozent dimmen/stellen" mit beliebigem ganzzahligem X zwischen 0–100 setzt die Licht-Helligkeit exakt auf X
- [ ] "Heizung im [Raum] auf X Grad stellen" mit beliebigem ganzzahligem X innerhalb des von der jeweiligen Climate-Entity gemeldeten `min_temp`/`max_temp`-Bereichs setzt die Zieltemperatur exakt auf X
- [ ] Werte außerhalb des zulässigen Bereichs (Licht/Rolladen > 100 % oder < 0 %, Heizung außerhalb `min_temp`/`max_temp`) werden **nicht** ausgeführt; Alice antwortet auf Deutsch mit dem tatsächlich zulässigen Bereich der jeweiligen Entity (z. B. "Die Heizung im Büro lässt sich nur zwischen 5 und 30 Grad einstellen.")
- [ ] Grenzwerte selbst (0 %, 100 %, exakt `min_temp`, exakt `max_temp`) gelten als gültig und werden ausgeführt
- [ ] Wertbehaftete Befehle (Licht/Rolladen/Heizung) bleiben im HA_FAST-Pfad — < 200 ms End-to-End, kein LLM-Aufruf (Performance-Ziel aus PROJ-3 AC-9 gilt unverändert auch für Werte-Befehle)
- [ ] "[Artikel] zur Einkaufsliste hinzufügen" (und gleichwertige Formulierungen) fügt den gesprochenen Artikeltext als neuen Eintrag zu einer vorkonfigurierten Standard-Einkaufsliste hinzu — beliebiger Freitext, inkl. optionaler Mengenangabe als Teil des Texts (z. B. "2 Packungen Milch" wird als ein Eintrag übernommen, keine separate Mengen-Extraktion)
- [ ] Fehlt die Standard-Einkaufsliste in HA, antwortet Alice mit einer verständlichen deutschen Fehlermeldung statt stillem Fehlschlag
- [ ] Zahlen werden aus dem transkribierten Text als Ziffern erkannt (z. B. "50", "21")
- [ ] Nachkommawerte (z. B. "21,5 Grad") werden auf die nächste Ganzzahl gerundet, nicht abgelehnt
- [ ] Multi-Befehl-Eingaben mit Werten (z. B. "Rolladen auf 50 und Licht auf 30 Prozent") funktionieren weiterhin über den bestehenden Sentence-Splitter-Mechanismus (PROJ-3) — jeder Teilbefehl wird unabhängig mit seinem eigenen Wert korrekt ausgeführt
- [ ] Bestehende feste Formulierungen ohne Wert (z. B. "Licht einschalten", "Rolladen hoch") funktionieren unverändert weiter — keine Regression
- [ ] Wird eine bereits registrierte HA-Entity nachträglich für die Assist-Konversation freigeschaltet, löst das automatisch einen Sync aus, der die Entity ohne HA-Neustart oder manuellen Full-Sync in Weaviate/`alice.ha_entities` verfügbar macht
- [ ] Wird einer bereits exponierten Entity die Assist-Freigabe entzogen, löst das automatisch einen Sync aus, der die Entity aus Weaviate entfernt und in `alice.ha_entities` als inaktiv markiert — analog zum bestehenden `entity_removed`-Verhalten (PROJ-39)
- [ ] Zusätzlich zur automatischen Erkennung existiert ein manuell ausführbares HA-Script mit derselben Wirkung (Sync-Trigger für Freischaltungs-Änderungen), auslösbar über die HA-UI oder eine Service-Aktion
- [ ] Die drei bestehenden Automationen (`alice_sync_on_start`, `alice_sync_on_entity_created`, `alice_sync_on_entity_removed`) bleiben unverändert funktionsfähig — keine Regression an der bestehenden Sync-Infrastruktur

## Edge Cases

- **Wert im gültigen Bereich, aber Entity aktuell nicht erreichbar** (z. B. Rolladen-Motor offline): wie bei bestehenden HA-API-Fehlern (PROJ-3) — nutzerfreundliche deutsche Fehlermeldung, kein Absturz.
- **Keine Climate-Entity aktuell für Assist freigegeben** (Stand PROJ-39-QA: 0 Climate-Entities exponiert): Heizungs-Temperatur-Befehle können erst live funktionieren/getestet werden, sobald Andreas eine Climate-Entity in HA für Assist freigibt. Bekanntes, dokumentiertes Limit — kein Blocker für PROJ-83 selbst, die Fähigkeit muss aber vorhanden sein, sobald eine Entity exponiert wird.
- **Ausgeschriebene Zahlwörter** ("fünfzig Prozent" statt "50 Prozent"): werden nicht zuverlässig erkannt — dokumentierte, akzeptierte Lücke (Whisper transkribiert Zahlen im Deutschen überwiegend als Ziffern).
- **Einkaufslisten-Artikel bereits auf der Liste** (Duplikat): wird trotzdem als neuer Eintrag hinzugefügt — kein Dedup, folgt dem HA-Standardverhalten.
- **Mehrdeutige Entity** (mehrere Lichter im selben Raum, z. B. Bürolicht + LED-Box + LED-Ring): Verhalten bleibt exakt wie heute (unverändert durch PROJ-83) — Verbesserung der Auflösung ist explizit PROJ-84s Aufgabe.
- **Sehr langer Einkaufslisten-Artikeltext** (z. B. ganzer Satz statt kurzem Artikel): wird als vollständiger Text übernommen, keine künstliche Kürzung.
- **Wert mit führenden Nullen oder ungewöhnlicher Schreibweise** ("auf 050 Prozent"): wird als Zahl 50 interpretiert (führende Nullen ignoriert).
- **Kein Wert im Satz erkennbar, obwohl Value-Pattern erwartet wird** (z. B. "Rolladen auf stellen" — STT-Transkriptionsfehler hat die Zahl verschluckt): Befehl wird nicht als vollständiger Match erkannt, fällt auf den bestehenden Fallback-Mechanismus zurück (HYBRID/LLM_ONLY, analog zu einem generellen Nicht-Match).
- **Mehrere Entities gleichzeitig freigeschaltet** (z. B. Bulk-Freigabe mehrerer Entities in einem Schritt über die HA-UI): Jede Freischaltung löst einzeln einen Sync-Trigger aus — analog zum bestehenden `mode: queued`/`max: 10`-Verhalten der `entity_created`/`entity_removed`-Automationen, keine verlorenen Events bei mehreren Änderungen kurz hintereinander.
- **Freischaltungs-Änderung während eines laufenden Full-Syncs** (z. B. HA-Neustart-Sync noch aktiv, während zeitgleich eine Entity freigeschaltet wird): wie beim bestehenden Concurrent-Sync-Schutz aus PROJ-39 — der neue Trigger reiht sich ein bzw. wird nach Abschluss des laufenden Syncs verarbeitet, keine parallelen Schreibkonflikte.
- **Entity wird freigeschaltet, aber Freischaltung wieder rückgängig gemacht bevor der Sync verarbeitet wurde** (sehr kurz hintereinander): Endzustand nach Verarbeitung beider Events entspricht dem tatsächlichen letzten Freigabe-Status der Entity — kein dauerhaft falscher Zwischenstand in Weaviate.

## Technical Requirements

- Performance: wertbehaftete HA-Befehle bleiben im HA_FAST-Pfad, < 200 ms End-to-End, kein LLM-Aufruf (analog PROJ-3 AC-9/AC-10)
- Kein Breaking Change an bestehenden festen (wertlosen) Formulierungen und an der Sentence-Splitter-Logik aus PROJ-3
- Wertebereich-Grenzen (min/max) werden dynamisch aus der jeweiligen HA-Entity gelesen (z. B. `min_temp`/`max_temp` bei Climate-Entities), nicht hartkodiert — verschiedene Thermostate können unterschiedliche Bereiche haben
- Sprache: Fehlermeldungen und Bereichsangaben auf Deutsch
- Offene Architektur-Frage: Der exakte HA-Event-Mechanismus, der beim Ändern des Assist-Freigabestatus einer bestehenden Entity feuert (vermutlich nicht `entity_registry_updated`, da dieser Status separat von der Entity Registry verwaltet wird), ist noch zu ermitteln/verifizieren — Aufgabe von `/architecture`. Empfehlung: Falls machbar, die neue Automation die bestehenden Event-Namen `entity_created`/`entity_removed` auf `alice/ha/sync` wiederverwenden lassen, da die n8n-Sync-Logik (PROJ-39) bei `entity_created` bereits einen Expose-Check durchführt — das würde eine Änderung an `alice-ha-intent-sync` selbst vermeiden

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

PROJ-83 wird **komplett im bestehenden `alice-chat-stream`-Container** (Python, HA_FAST-Pfad in `app/ha_path.py`) plus **einer kleinen Erweiterung im `alice-ha-sync`-Worker** und **einer neuen HA-Automation + einem HA-Script** umgesetzt.

- **Kein neuer Docker-Container.**
- **Kein neues Weaviate-Collection, kein neues DB-Schema, keine DB-Migration.**
- **Kein LLM-Aufruf** — die Werterkennung ist reine Textverarbeitung (Regex) und bleibt im < 200 ms-Budget.
- **Die vorindexierten Diskretstufen in Weaviate bleiben unverändert** — sie dienen weiterhin als semantische Anker für die `nearText`-Suche. Neu ist nur, dass der *tatsächlich gesprochene* Wert nach dem Match aus dem Originaltext gezogen wird und den Anker-Wert überschreibt.

Die Architektur folgt vier unabhängigen Bausteinen:

1. **Werterkennung** (Prozent / Temperatur) — Regex-Extraktion nach dem Weaviate-Match, Range-Prüfung, Ausführung mit exaktem Wert.
2. **Rolladen-Positionierung** — neues Intent-Template `cover.set_cover_position` (existiert bisher nicht) + Werterkennung wie Baustein 1.
3. **Einkaufslisten-Eintrag** — Freitext-Erkennung im Code (kein Weaviate-Match), Ziel-Liste = die erste für Assist freigegebene `todo`-Entity.
4. **Sync bei Freischaltungs-Änderung** — neue HA-Automation + manuelles HA-Script, die den bestehenden `entity_created`/`entity_removed`-Eventweg wiederverwenden.

---

### A) Ablauf im HA_FAST-Pfad (Visual Tree)

```
alice-chat-stream — event_generator (app/main.py)
│
├── ha_path.decide_path(message)
│     ├── split_message()  → Teilbefehle (Sentence Splitter, PROJ-3, unverändert)
│     └── für jeden Teil:  lookup_intent()  → Weaviate nearText gegen HAIntent
│           └── bester Treffer ≥ INTENT_MIN_CERTAINTY (0.82)?
│
├── ALLE Teile matchen  →  HA_FAST
│     │
│     └── execute_ha_intents(intents, parts)          ← NEU: parts wird mitgegeben
│           │
│           ├── [pro Intent] Werte-Nachbearbeitung  (NEU)
│           │     ├── Ist der Intent-Service wertbehaftet?
│           │     │     light.turn_on + brightness   → Prozent 0–100
│           │     │     cover.set_cover_position      → Prozent 0–100
│           │     │     climate.set_temperature       → Temperatur (dyn. Bereich)
│           │     │
│           │     ├── ja → Regex zieht die Zahl aus dem zugehörigen Textteil
│           │     │        "auf 37 Prozent"  → 37
│           │     │        "21,5 Grad"       → 22   (kaufm. Rundung)
│           │     │        "050 Prozent"     → 50   (führende Nullen)
│           │     │        keine Zahl gefunden → Intent gilt als NICHT gematcht
│           │     │                              → Gesamt-Fallback auf LLM_ONLY
│           │     │
│           │     ├── Range-Check
│           │     │     Prozent: fixe Grenzen 0–100
│           │     │     Temperatur: Live-GET /api/states/<entity>
│           │     │                 → attributes.min_temp / max_temp
│           │     │     ausserhalb → NICHT ausführen, deutsche Bereichs-Antwort
│           │     │
│           │     └── innerhalb → parameters[key] = exakter Wert
│           │
│           ├── [pro Intent] HA REST-Call (parallel, unverändert)
│           │     POST /api/services/<domain>/<service>  { entity_id, <wert> }
│           │
│           └── Template-Antwort  ("Rolladen Büro auf 37 % gestellt.")
│
├── Einkaufslisten-Sonderfall  (NEU, vor der normalen Intent-Schleife)
│     └── Teiltext matcht Einkaufslisten-Regex?
│           ("… zur/auf die Einkaufsliste …" o. ä.)
│           ├── ja → todo.add_item  { entity_id: <default-todo>, item: <Freitext> }
│           │        default-todo = erste aktive todo-Entity aus alice.ha_entities
│           │        keine todo-Entity freigegeben → deutsche Fehlermeldung
│           └── nein → normaler Weaviate-Pfad
│
└── KEIN Teil / nicht alle Teile matchen  →  LLM_ONLY  (unverändert)
```

---

### B) Baustein 1 & 2 — Werterkennung Prozent / Temperatur / Rolladen-Position

**Problem heute:** `execute_ha_intents()` nimmt die `parameters` direkt aus dem Weaviate-Treffer. Der Treffer ist aber eine der 5 bzw. 11 vorindexierten Diskretstufen — bei „Rolladen auf 37 Prozent" matcht Weaviate semantisch auf „… auf 50 Prozent" und führt **50** aus.

**Lösung:**

| Schritt | Was passiert |
|---|---|
| 1. Match | Weaviate-`nearText` bleibt wie er ist. Die Diskretstufen sind nur noch semantische Anker, ihr Zahlenwert wird verworfen. |
| 2. Service-Klassifikation | Anhand von `service` + `parameters`-Schlüssel wird bestimmt, ob der Intent wertbehaftet ist und welcher Werttyp gilt (Prozent oder Temperatur). |
| 3. Zahl-Extraktion | Regex auf den **Original-Textteil** (nicht auf die gematchte Utterance): erste Ganzzahl, optional gefolgt von „Prozent"/„%"/„Grad"/„°". Nachkommastellen (`21,5` / `21.5`) werden erkannt und kaufmännisch auf die nächste Ganzzahl gerundet. Führende Nullen werden ignoriert. |
| 4. Kein Wert gefunden | Der Intent wird als *nicht vollständig erkannt* behandelt → der komplette Request fällt auf LLM_ONLY zurück (analog „genereller Nicht-Match", Edge Case in der Spec). |
| 5. Range-Check | **Prozent** (Licht, Rolladen): feste Grenzen 0–100, inklusive. **Temperatur**: ein einmaliger `GET /api/states/<entity_id>` liest `attributes.min_temp` / `attributes.max_temp` der konkreten Climate-Entity. Grenzwerte selbst gelten als gültig. |
| 6. Ausserhalb Bereich | Kein HA-Call. Alice antwortet auf Deutsch mit dem tatsächlichen Bereich, z. B. „Die Heizung im Büro lässt sich nur zwischen 5 und 30 Grad einstellen." bzw. „… nur zwischen 0 und 100 Prozent." |
| 7. Innerhalb Bereich | Der exakte Wert wird in `parameters` geschrieben und der HA-REST-Call wie bisher (parallel) ausgeführt. |

**Warum Regex und kein Intent-Helper-Service:** Der Extraktionsschritt ist ein Einzeiler pro Werttyp und läuft in-Prozess. Ein separater FastAPI-Endpoint würde pro Teilbefehl einen zusätzlichen Netz-Hop ins < 200 ms-Budget legen, ohne erkennbaren Genauigkeitsgewinn (Whisper liefert im Deutschen Ziffern, keine Zahlwörter).

**Rolladen-Position (Baustein 2):** Es gibt heute **kein** Intent-Template für `cover.set_cover_position` — nur `open_cover` / `close_cover`. PROJ-83 fügt in `alice.ha_intent_templates` eine neue Zeile hinzu:

- Domain `cover`, Service `cover.set_cover_position`
- Patterns mit `{value}`-Platzhalter, z. B. „Rolladen in der {area} auf {value} Prozent stellen", „{name} auf {value} Prozent"
- `parameters`-Schlüssel `position`

Der `alice-ha-sync`-Worker expandiert `{value}`-Patterns für Nicht-`light`/`media_player`-Domains bereits mit den Prozentwerten (10/25/50/75/100) — für `cover` greift der Fallback-Zweig in `_value_expansion_for()` ohne Codeänderung. Nach dem Hinzufügen der Template-Zeile genügt ein `templates_updated`-Full-Sync, damit die Rolladen-Positions-Utterances in Weaviate landen.

**Multi-Befehl:** Der Sentence Splitter (PROJ-3) trennt „Rolladen auf 50 und Licht auf 30 Prozent" bereits in zwei Teile. Jeder Teil bekommt seinen eigenen Regex-Durchlauf → jeder Wert wird unabhängig extrahiert. `execute_ha_intents()` bekommt dafür zusätzlich die `parts`-Liste übergeben, damit Intent *i* mit Textteil *i* gepaart werden kann.

---

### C) Baustein 3 — Einfacher Einkaufslisten-Eintrag

| Aspekt | Entscheidung |
|---|---|
| Intent-Erkennung | **Nicht** über Weaviate (Freitext lässt sich nicht als Utterance-Set indexieren — der `alice-ha-sync`-Worker überspringt `{message}`-Patterns bewusst weiterhin). Stattdessen ein Regex/Keyword-Check direkt in `ha_path.py`, der vor der normalen Intent-Schleife läuft: erkennt Formulierungen wie „<Artikel> zur Einkaufsliste hinzufügen", „<Artikel> auf die Einkaufsliste", „schreib <Artikel> auf die Einkaufsliste". |
| Artikeltext | Alles vor dem Auslöser-Ausdruck („… zur Einkaufsliste") ist der Artikeltext — vollständiger Freitext, inklusive optionaler Mengenangabe („2 Packungen Milch"). Keine separate Mengen-Extraktion, keine Kürzung, kein Dedup (folgt HA-Standardverhalten). |
| Ziel-Liste | Die **erste aktive `todo`-Entity** aus `alice.ha_entities` (`is_active = true`, `domain = 'todo'`, nach `entity_id` sortiert für Determinismus). Aktuell existiert genau eine: `todo.einkaufsliste`. Kein neues ENV, keine neue Spalte. |
| Ausführung | `POST /api/services/todo/add_item` mit `{ entity_id: <todo-entity>, item: <Artikeltext> }`. |
| Keine Liste vorhanden | Wenn keine aktive `todo`-Entity existiert: Alice antwortet mit einer verständlichen deutschen Fehlermeldung („Es ist keine Einkaufsliste für Alice freigegeben."), kein stiller Fehlschlag, kein LLM. |
| Mehrere `todo`-Listen | Bewusst ausgeklammert → PROJ-100. „Erste Liste" ist für den aktuellen Ein-Listen-Zustand korrekt und für später klar erweiterbar. |

---

### D) Baustein 4 — Sync bei Assist-Freischaltungs-Änderung

**Problem:** Die drei bestehenden HA-Automationen feuern bei HA-Neustart und beim Erstellen/Löschen einer Entity. Wird eine **bestehende** Entity nachträglich für Assist freigeschaltet (oder die Freigabe entzogen), passiert nichts — die Entity bleibt bis zum nächsten HA-Neustart oder manuellen Full-Sync unsichtbar für den HA_FAST-Pfad.

**Lösung — zwei Teile, kein Worker-Code-Change:**

| Teil | Mechanismus |
|---|---|
| **Automatische Erkennung** | Neue HA-Automation `alice_sync_on_expose_changed.yaml`. Trigger: `entity_registry_updated` mit `action: update`. Bei Feuern published sie auf `alice/ha/sync` ein `entity_created`-Event für die betroffene Entity (gleicher Payload wie die bestehende `entity_created`-Automation, inkl. 5 s Delay, `mode: queued`, `max: 10`). |
| **Warum `entity_created` wiederverwenden** | Der `alice-ha-sync`-Worker macht bei `entity_created` **bereits** einen Expose-Check (`incremental_sync()` → `if entity_id not in expose_set: skip`). Ist die Entity jetzt freigeschaltet → sie wird indexiert. Ist die Freigabe entzogen → der Worker überspringt sie beim `entity_created` und der bestehende „no longer exposed"-Pfad des nächsten Full-Syncs räumt sie ab. Für sofortiges Entfernen bei Entzug published die Automation zusätzlich ein `entity_removed`, wenn der neue Zustand „nicht mehr exponiert" ist — dieser Pfad markiert die Entity in `alice.ha_entities` inaktiv und löscht die Weaviate-Objekte (analog PROJ-39). **Der Worker selbst wird nicht angefasst.** |
| **Offene Verifikation** | Ob HA beim Assist-Toggle tatsächlich `entity_registry_updated / action: update` feuert (der Expose-Status wird teils separat von der Entity Registry verwaltet), muss beim Bau verifiziert werden. Falls das Event nicht zuverlässig feuert: Fallback auf einen State-/Template-Trigger, der die `homeassistant/expose_entity/list` periodisch bzw. bei Konfig-Reload prüft. Die manuelle Fallback-Ebene (unten) deckt jeden nicht abgedeckten Fall ab. |
| **Manueller Trigger** | Neues HA-Script `alice_resync.yaml`, auslösbar über die HA-UI oder als Service-Aktion. Es published ein `ha_start`-Event (`sync_type: full`) auf `alice/ha/sync` → voller Re-Sync mit frischen Expose-Daten. Deckt jeden Fall ab, den der automatische Trigger verpasst. |
| **Regression** | Die drei bestehenden Automationen (`alice_sync_on_start`, `alice_sync_on_entity_created`, `alice_sync_on_entity_removed`) werden **nicht verändert**. Die neue Automation und das neue Script sind additive Dateien unter `homeassistant/`. |

---

### E) Datenmodell (Klartext)

**Keine Schema-Änderung.** Nur eine zusätzliche Zeile in einer bestehenden Tabelle:

```
alice.ha_intent_templates  — 1 neue Zeile:
    domain                = "cover"
    intent                = "set_position"
    service               = "cover.set_cover_position"
    patterns              = [ "Rolladen in der {area} auf {value} Prozent stellen",
                              "{name} auf {value} Prozent", … ]
    default_parameters    = {}
    requires_confirmation  = false
    priority              = (Standard)
```

Werte, die zur Laufzeit gelesen aber **nicht gespeichert** werden:

```
Aus HA /api/states/<climate-entity>.attributes:
    min_temp   — untere Temperaturgrenze der konkreten Climate-Entity
    max_temp   — obere Temperaturgrenze

Fest im Code:
    Prozent-Bereich Licht/Rolladen = 0 … 100 (HA-Standard)
```

Ziel-Einkaufsliste: Lookup zur Laufzeit gegen `alice.ha_entities` (`domain='todo' AND is_active`), kein neues Feld.

---

### F) Tech-Entscheidungen (für PM)

| Entscheidung | Wahl | Warum |
|---|---|---|
| Wo wird der exakte Wert erkannt? | Regex im `alice-chat-stream`-Code, nach dem Weaviate-Match | In-Prozess, kein Netz-Hop, hält das < 200 ms-Ziel. Whisper liefert im Deutschen Ziffern → Regex reicht. |
| Weaviate-Index anfassen? | Nein (bis auf das eine neue `cover`-Template) | Die Diskretstufen funktionieren als semantische Anker weiterhin. Weniger Risiko, kein großer Re-Index. |
| Temperatur-Grenzen | Live aus HA beim Befehl | Immer aktuell, kein Schema-Change, verschiedene Thermostate haben verschiedene Bereiche. Ein zusätzlicher GET pro Heizungs-Befehl ist im Budget. |
| Einkaufslisten-Erkennung | Keyword/Regex im Code, nicht Weaviate | Freitext ist nicht als Utterance-Set indexierbar. |
| Ziel-Einkaufsliste | Erste aktive `todo`-Entity | Kein ENV nötig, aktuell eindeutig (1 Liste), sauber nach PROJ-100 erweiterbar. |
| Expose-Change-Sync | Neue HA-Automation, die `entity_created`/`entity_removed` wiederverwendet | Der Worker macht bei `entity_created` schon einen Expose-Check → **null** Worker-Code-Änderung. |
| Manueller Re-Sync | HA-Script published `ha_start` | Nutzt exakt den bestehenden Full-Sync-Pfad, Fallback für jeden nicht abgedeckten Auto-Fall. |
| Wertloser Befehl („Licht an") | Unverändert | Regex-Nachbearbeitung greift nur bei wertbehafteten Services; alles andere läuft wie bisher. |

---

### G) Abzuliefernde Artefakte

```
alice-chat-stream  (bestehender Container — Code-Änderung)
├── app/ha_path.py
│     ├── NEU: Werttyp-Klassifikation je Intent (Prozent / Temperatur / keiner)
│     ├── NEU: Regex-Zahl-Extraktion aus dem Original-Textteil (+ Rundung, führende Nullen)
│     ├── NEU: Range-Check (fix 0–100 bzw. Live-GET min_temp/max_temp)
│     ├── NEU: deutsche Bereichs-Fehlermeldung bei Wert ausserhalb
│     ├── NEU: Einkaufslisten-Freitext-Erkennung + todo.add_item + „keine Liste"-Fehlermeldung
│     └── GEÄNDERT: execute_ha_intents() bekommt die parts-Liste mit übergeben
├── app/main.py
│     └── GEÄNDERT: parts an execute_ha_intents() weiterreichen
└── tests/
      └── NEU: Unit-Tests für Extraktion, Rundung, Range-Check, Multi-Befehl, Einkaufsliste

alice.ha_intent_templates  (bestehende Tabelle — 1 neue Zeile)
└── cover.set_cover_position-Template  → danach templates_updated-Full-Sync

homeassistant/  (neue Dateien — additiv)
├── alice_sync_on_expose_changed.yaml   (neue Automation)
└── alice_resync.yaml                   (neues manuelles Script)

alice-ha-sync  (bestehender Worker)
└── KEINE Änderung
```

**Keine** neuen npm-/pip-Pakete, **kein** neuer Container, **keine** DB-Migration, **keine** Frontend-Änderung, **kein** neues Weaviate-Collection.

---

### H) Performance

| Ziel | Mechanismus |
|---|---|
| Wertbehaftete Befehle < 200 ms, kein LLM | Regex-Extraktion ist in-Prozess (µs). Der einzige Zusatz-Call ist **ein** `GET /api/states/<entity>` und **nur** bei Heizungs-Befehlen — Licht/Rolladen brauchen ihn nicht (feste 0–100). Alle HA-Calls laufen weiterhin parallel. |
| Multi-Befehl | Sentence Splitter + parallele Ausführung unverändert; die Regex-Schleife fügt vernachlässigbare Zeit hinzu. |
| Kein Regressionsrisiko für wertlose Befehle | Die Nachbearbeitung ist an wertbehaftete Services gebunden; „Licht einschalten", „Rolladen hoch" nehmen den unveränderten Pfad. |

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
