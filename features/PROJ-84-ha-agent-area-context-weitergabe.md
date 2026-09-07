# PROJ-84: HA-Agent Area-Context-Weitergabe

## Status: Deployed
**Created:** 2026-09-07
**Last Updated:** 2026-09-07

## Dependencies
- Requires: PROJ-1 (HA Intent Infrastructure) — Weaviate `HAIntent`-Collection
- Requires: PROJ-3 (HA-First Chat Handler mit Intent-Routing) — HA_FAST/LLM_ONLY-Pfadlogik, Sentence Splitter
- Requires: PROJ-39 (alice-ha-sync Overhaul) — `alice.ha_entities.area_id`/`area_name` bereits synchronisiert
- Requires: PROJ-40/PROJ-42 (Speech-Gateway Wyoming/ESPHome) — `device-mapping.yaml` (Raum je Geräte-IP) + `source: esphome:<Raum>`-Weitergabe an `alice-chat-stream`
- Requires: PROJ-82 (HA-MCP-Server-Evaluierung) — Spike abgeschlossen, Ergebnis: No-Go. PROJ-84 baut auf dem bestehenden n8n/Weaviate-Ansatz auf, kein MCP-Server involviert
- Unabhängig von: PROJ-83 (HA-Agent variable Intents) — beide hängen von PROJ-82 ab, aber nicht voneinander; Reihenfolge war beliebig, PROJ-83 ist bereits deployed

## Overview

Der HA_FAST-Pfad (PROJ-1/PROJ-3/PROJ-39/PROJ-83) matcht eine Äußerung wie "Licht einschalten" per Weaviate-`nearText` gegen alle indexierten `HAIntent`-Utterances im Haus. Jede indexierte Utterance ist **immer** an eine konkrete Entity gebunden (Name oder Raum im Utterance-Text — es gibt keine wirklich generische Variante, siehe `alice-ha-sync/main.py generate_utterances()`). Sagt Andreas im Büro "Licht einschalten", ohne einen Raum zu nennen, matcht Weaviate rein semantisch auf die textlich nächstliegende Utterance im ganzen Haus — das kann zufällig die Küche treffen statt des Büros, in dem er tatsächlich steht.

**Die Grundlage existiert bereits:** Jedes HA Voice PE ist in `device-mapping.yaml` (alice-speech-gateway) fest einer IP und einem Raum zugeordnet (`room: "Büro"`) und sendet diesen Raum bereits heute als `source: "esphome:Büro"` an `alice-chat-stream` — er wird dort aber aktuell **nicht** an `ha_path.decide_path()`/`execute_ha_intents()` weitergereicht. `alice.ha_entities.area_name` ist durch PROJ-39 bereits für jede Entity befüllt.

PROJ-84 schließt diese Lücke: Enthält die gesprochene Äußerung selbst keinen erkennbaren Raum- oder Gerätenamen, wird der Raum des sprechenden Geräts (aus `source`) als Kontext herangezogen, und **alle** aktiven Entitäten der passenden Domain in diesem Raum werden angesprochen (nicht nur die eine von Weaviate zufällig gematchte). Nennt die Äußerung selbst einen Raum oder Gerätenamen, hat das explizit Gesagte Vorrang. Ist weder ein Raum genannt noch einer aus dem Gerätekontext bekannt (z. B. Webapp-Chat), fragt Alice aktiv nach dem Raum, statt zu raten.

**Bewusst außerhalb des Scopes:**
- Kein Session-/Slot-Filling-Zustand — Alice merkt sich die Rückfrage nicht; der Nutzer wiederholt den vollständigen Befehl inkl. Raum in der nächsten Nachricht (kein neuer Multi-Turn-Zustand im HA_FAST-Pfad).
- Kein Live-HA-Call zur Area-Auflösung — Lookup läuft wie der bestehende Friendly-Name-Lookup (PROJ-83) gegen `alice.ha_entities` in PostgreSQL.
- Keine Änderung an der Einkaufslisten-Logik (PROJ-83 Baustein 3) — die ist bereits area-unabhängig (eine feste Standardliste, kein Entity-/Domain-Konzept).
- Keine Änderung am Sync-Mechanismus selbst (`alice-ha-sync`) — `area_name`/`area_id` sind bereits vollständig synchronisiert (PROJ-39).

## User Stories

- Als Andreas möchte ich im Büro sagen "Rolladen schließen", ohne "im Büro" sagen zu müssen, und genau der/die Rolladen im Büro fahren zu — weil der HA Voice PE im Büro als Raum "Büro" hinterlegt hat.
- Als Andreas möchte ich in der Küche sagen "Licht einschalten", ohne "in der Küche" sagen zu müssen, und alle Lichter der Küche gehen an.
- Als Andreas möchte ich, dass wenn ich im Satz selbst einen anderen Raum nenne (z. B. "Licht im Wohnzimmer einschalten", während ich im Büro spreche), der genannte Raum gilt — nicht der Raum, in dem ich gerade stehe.
- Als Andreas möchte ich, dass bei mehreren gleichartigen Geräten in einem Raum (z. B. drei Lichtern in der Küche) alle gemeint sind, wenn ich kein einzelnes explizit nenne.
- Als Andreas möchte ich, dass Alice nachfragt, in welchem Raum sie etwas tun soll, wenn weder mein Satz noch der Gerätekontext einen Raum hergibt — statt dass sie irgendein zufälliges Gerät im Haus anspricht.
- Als Andreas möchte ich, dass Area-Context-Befehle genauso schnell reagieren wie bisherige Befehle (< 200 ms, kein LLM-Aufruf), damit sich die Steuerung nicht langsamer anfühlt.
- Als Andreas möchte ich bei einem Teilfehler (z. B. ein Licht von dreien offline) wissen, was geklappt hat und was nicht — nicht nur eine pauschale Erfolgs- oder Fehlermeldung.

## Acceptance Criteria

- [ ] "[Aktion]" ohne genannten Raum/Gerätenamen (z. B. "Rolladen schließen", "Licht einschalten"), gesprochen über ein HA Voice PE mit konfiguriertem Raum, wird auf den Raum des sprechenden Geräts angewendet (aus `source: esphome:<Raum>`)
- [ ] Enthält die Äußerung selbst einen erkennbaren Raumnamen (Abgleich gegen `alice.ha_entities.area_name`, case-insensitive), hat dieser genannte Raum Vorrang vor dem Geräte-Raum — auch wenn beide unterschiedlich sind
- [ ] Enthält die Äußerung selbst einen erkennbaren Entity-Namen oder Alias (Abgleich gegen `alice.ha_entities.friendly_name`/`aliases`), wird wie bisher (PROJ-1/PROJ-3) direkt diese eine Entity angesprochen — kein Area-Context nötig, keine Verhaltensänderung
- [ ] Hat der ermittelte Raum (genannt oder aus Gerätekontext) mehrere aktive Entitäten derselben Domain (z. B. drei Lichter), werden **alle** angesprochen — gilt einheitlich für alle Domains (light, cover, switch, climate, lock, media_player, …), keine domain-spezifischen Ausnahmen
- [ ] Wertbehaftete Befehle (PROJ-83, z. B. "Licht auf 30 Prozent dimmen") wenden bei mehreren betroffenen Entitäten denselben Wert auf alle an
- [ ] Erfolgsmeldung bei mehreren betroffenen Entitäten ist raumbezogen und einmalig formuliert (z. B. "Licht im Büro eingeschaltet."), nicht eine Zeile pro Entity
- [ ] Schlägt bei mehreren betroffenen Entitäten eine einzelne fehl (z. B. Gerät offline), meldet Alice den Erfolg der übrigen UND nennt das fehlgeschlagene Gerät separat (z. B. "Licht im Büro eingeschaltet, außer LED-Ring (nicht erreichbar).")
- [ ] Kein Raum in der Äußerung genannt UND kein Raum aus dem Gerätekontext bekannt (z. B. Webapp-Chat `webapp_cc`/`webapp_mic`, oder HA Voice PE ohne `room` in `device-mapping.yaml`) → Alice antwortet mit einer Rückfrage auf Deutsch nach dem Raum (z. B. "In welchem Raum möchtest du das Licht einschalten?"), führt nichts aus, kein LLM-Aufruf
- [ ] Diese Rückfrage merkt sich den ursprünglichen Befehl nicht als offenen Zustand — der nächste Request wird unabhängig behandelt; der Nutzer wiederholt den vollständigen Befehl inkl. Raum
- [ ] Ist der Geräte-Raum bekannt, aber es existiert keine aktive Entität der passenden Domain in diesem Raum (z. B. "Licht einschalten" im Büro, aber kein Licht dem Büro zugeordnet), fällt der Request auf den bestehenden LLM_ONLY-Pfad zurück (analog zu einem generellen Nicht-Match, PROJ-83-Muster)
- [ ] Area-Context-Befehle bleiben im HA_FAST-Pfad — < 200 ms End-to-End, kein LLM-Aufruf (Performance-Ziel aus PROJ-3 AC-9 / PROJ-83 gilt unverändert)
- [ ] Multi-Befehl-Eingaben mit Area-Context (z. B. "Rolladen schließen und Licht ausschalten" im Büro) funktionieren weiterhin über den bestehenden Sentence-Splitter-Mechanismus — jeder Teilbefehl bekommt unabhängig seinen Area-Context angewendet
- [ ] Bestehende Befehle mit explizit genanntem Einzelgerät oder Raum funktionieren unverändert weiter — keine Regression
- [ ] Der Raum-Abgleich (Äußerung ↔ `area_name`) ist case-insensitive (z. B. "büro" matcht "Büro")

## Edge Cases

- **Mehrere Entitäten derselben Domain im Raum, eine ist bereits im Zielzustand** (z. B. eines von drei Lichtern ist schon an): wird trotzdem angesprochen (idempotenter HA-Call), zählt als Erfolg — kein Sonderfall.
- **Genannter Raum existiert nicht in `alice.ha_entities.area_name`** (z. B. Tippfehler/Fantasiename in der Transkription, "Licht im Bürro einschalten"): kein Area-Treffer im Text → Verhalten wie "kein Raum genannt", Geräte-Raum-Kontext greift falls vorhanden, sonst Rückfrage.
- **Geräte-Raum bekannt, aber im Satz wird eine konkrete Einzel-Entity genannt, die NICHT in diesem Raum liegt** (z. B. "Wohnzimmerlicht einschalten" im Büro gesprochen): Entity-Name-Treffer hat Vorrang (wie in den AC festgelegt) — Weaviate-Match wird direkt verwendet, kein Area-Context, keine Einschränkung auf den Geräte-Raum.
- **Raumname ist Teil eines Gerätenamens** (z. B. Entity heißt "Büro Deckenlampe", Raum heißt auch "Büro"): Kein Konflikt — beide Treffer (Area-Name UND Entity-Name) führen zum selben Ergebnis (Büro-Kontext).
- **Sehr kurzer oder mehrdeutiger Raumname, der zufällig Teil eines anderen Wortes ist** (z. B. Raum "Bad" als Substring in einem längeren Wort): dokumentierte, akzeptierte Grenze des Substring-Abgleichs — kein Wortgrenzen-Escape vorgesehen, da deutsche Raumnamen im Haushalt aktuell eindeutig sind.
- **Genau eine Entity der passenden Domain im Raum** (z. B. nur ein Licht im Büro): Verhalten bleibt wie bei mehreren — funktional identisch zum bisherigen Einzel-Entity-Fall, nur über den Area-Lookup statt Weaviate-Einzeltreffer aufgelöst.
- **Multi-Befehl mit Area-Context + wertlosem Einzelgerät-Befehl gemischt** (z. B. "Licht einschalten und Bürolicht auf 50 Prozent" im Büro): jeder Teil wird unabhängig aufgelöst — der erste über Area-Context (alle Büro-Lichter an), der zweite über den expliziten Entity-Namen (nur Bürolicht auf 50 %).
- **Area-Context-Teil + Einkaufslisten-Teil im selben Multi-Befehl**: unverändert wie PROJ-83 — der Einkaufslisten-Teil wird vorab erkannt und läuft area-unabhängig weiter.
- **Alle Entitäten der Domain im Raum sind offline/nicht erreichbar**: keine Erfolgsmeldung, alle werden als Fehler einzeln benannt (Grenzfall des Teilfehler-Verhaltens — 0 von N erfolgreich statt "N-1 von N").
- **Rückfrage-Fall, Nutzer antwortet mit reinem Raumnamen ohne neuen Befehl** (z. B. auf "In welchem Raum?" antwortet er nur "Büro"): da kein Session-Zustand gehalten wird, ist das eine eigenständige neue Nachricht ohne erkennbaren HA-Intent — fällt auf den bestehenden Nicht-Match-Fallback (LLM_ONLY) zurück; das LLM hat keinen Kontext über die vorherige Rückfrage.
- **Wert außerhalb des zulässigen Bereichs bei Multi-Entity** (z. B. "Heizung auf 45 Grad" trifft mehrere Climate-Entities im Raum mit unterschiedlichen `min_temp`/`max_temp`): jede Entity wird einzeln gegen ihren eigenen Bereich geprüft (analog PROJ-83) — Entities außerhalb ihres Bereichs werden nicht angesprochen und einzeln mit ihrem tatsächlichen Bereich benannt, Entities innerhalb werden ausgeführt (folgt demselben Teilerfolgs-Muster wie ein Offline-Gerät).

## Technical Requirements

- Performance: Area-Context-Befehle bleiben im HA_FAST-Pfad, < 200 ms End-to-End, kein LLM-Aufruf (analog PROJ-3 AC-9 / PROJ-83)
- Area-Auflösung läuft als PostgreSQL-Query gegen `alice.ha_entities` (`WHERE area_name = $1 AND domain = $2 AND is_active`), kein Live-HA-Call — gleiches Muster wie der bestehende Friendly-Name-Lookup (PROJ-83)
- Der Geräte-Raum kommt aus dem bereits vorhandenen `source`-Feld (`esphome:<Raum>`), das aktuell bis `main.py` durchgereicht, aber nicht an `ha_path.decide_path()`/`execute_ha_intents()` weitergegeben wird — muss ergänzt werden
- Raum-/Namens-Erkennung im Text: case-insensitive Substring-Abgleich des Text-Teils gegen `alice.ha_entities.area_name` (Raum-Erkennung) sowie `friendly_name`/`aliases` (Entity-Erkennung)
- Kein Breaking Change an bestehenden Befehlen mit explizit genanntem Einzelgerät/Raum und an der Sentence-Splitter-Logik (PROJ-3)
- Kein neuer Session-/Konversations-Zustand — die Rückfrage ist zustandslos, analog zum bestehenden `requires_confirmation`-Antwortmuster (PROJ-83), das ebenfalls keinen Folgezustand hält
- Sprache: Rückfragen, Erfolgs- und Fehlermeldungen auf Deutsch
- Webapp-Quellen (`webapp_cc`, `webapp_mic`) haben strukturell keinen Geräte-Raum — dort führt jeder raumlose Befehl konsistent zur Rückfrage, keine Sonderbehandlung für Ein-Entity-Haushalte

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

**Feature-Typ:** Reines Backend (Python HA_FAST-Pfad in `alice-chat-stream`). Kein UI, keine DB-Schema-Änderung, kein n8n-Workflow, keine neue Dependency.

### Big Picture — was sich ändert

Heute weiß der HA_FAST-Pfad nicht, in welchem Raum der Nutzer steht. Der Raum wird vom sprechenden Gerät zwar schon bis in `alice-chat-stream` mitgeliefert (`source: "esphome:Büro"`), aber an der Türschwelle zum HA_FAST-Pfad fallen gelassen. PROJ-84 reicht diesen Raum eine Ebene tiefer durch und nutzt ihn als Fallback-Kontext, wenn die Äußerung selbst keinen Raum und kein Gerät nennt.

Die Reihenfolge, in der ein Befehl aufgelöst wird, ist die zentrale Design-Entscheidung. Pro Teilbefehl gilt eine feste Rangfolge:

```
1. Nennt der Text ein konkretes Gerät (friendly_name / alias)?
   → ja: dieses eine Gerät ansteuern (heutiges Verhalten, unverändert)

2. Nennt der Text einen bekannten Raumnamen (area_name)?
   → ja: ALLE aktiven Geräte der passenden Domain in DIESEM Raum

3. Kennt Alice den Raum des sprechenden Geräts (aus source)?
   → ja: ALLE aktiven Geräte der passenden Domain in DIESEM Raum

4. Kein Raum, nirgendwo:
   → Rückfrage auf Deutsch ("In welchem Raum möchtest du …?"),
     nichts ausführen, kein LLM
```

Nur Stufe 1 existiert heute. Stufe 2–4 kommen neu dazu.

### Datenfluss (ein Teilbefehl)

```
Gesprochen: "Licht einschalten"      Gerät: HA Voice PE Büro
        │
        ▼
alice-speech-gateway  ──►  source = "esphome:Büro"
        │
        ▼
alice-chat-stream / main.py   (bekommt source schon heute)
        │  NEU: source wird an decide_path() + execute_ha_intents() übergeben
        ▼
ha_path.py
        │
        ├─ Weaviate nearText: welche Domain/welcher Service ist gemeint? → "light / turn_on"
        │
        ├─ Text nach Gerätename absuchen  → kein Treffer
        ├─ Text nach Raumname absuchen    → kein Treffer
        ├─ Geräte-Raum aus source         → "Büro"
        │
        ├─ PostgreSQL:  SELECT entity_id FROM alice.ha_entities
        │               WHERE area_name = 'Büro' (case-insensitive)
        │                 AND domain = 'light' AND is_active
        │               → [licht.buero_decke, licht.buero_stehlampe]
        │
        └─ HA REST: turn_on für beide Entities
                │
                ▼
        "Licht im Büro eingeschaltet."   (eine raumbezogene Meldung)
```

### Wie der Text nach Raum-/Gerätenamen durchsucht wird

Gleiches Muster wie der bestehende Friendly-Name-Lookup aus PROJ-83: ein einfacher, case-insensitiver Textvergleich (Substring) des Teilbefehls gegen die in `alice.ha_entities` gespeicherten Namen.

- **Gerätenamen:** Abgleich gegen `friendly_name` und die Einträge in `aliases`.
- **Raumnamen:** Abgleich gegen die Menge der bekannten `area_name`-Werte.

Beides läuft gegen PostgreSQL, kein Live-Aufruf bei Home Assistant, kein LLM. Bewusst akzeptierte Grenze (aus der Spec): ein sehr kurzer Raumname, der zufällig in einem längeren Wort steckt, kann fälschlich matchen — im aktuellen Haushalt sind die deutschen Raumnamen eindeutig genug, ein Wortgrenzen-Schutz wird nicht gebaut.

### Was die Datenbank liefert

Keine neue Tabelle, keine neue Spalte. PROJ-84 liest nur zusätzlich Felder, die durch PROJ-39 bereits befüllt sind:

```
alice.ha_entities  (bestehend)
  entity_id       z. B. "light.buero_decke"
  domain          z. B. "light"
  friendly_name   z. B. "Büro Deckenlicht"
  aliases         z. B. ["Deckenlicht Büro"]
  area_name       z. B. "Büro"          ← durch PROJ-39 gepflegt
  is_active       nur aktive Entities zählen
```

Die neue Abfrage: „Gib mir alle aktiven `entity_id` einer Domain in einem Raum." Der bestehende Index auf `domain` deckt das ab; der Query läuft im Millisekunden-Bereich und gefährdet das < 200 ms-Ziel nicht.

### Mehrere Geräte, eine Meldung

Trifft ein Raum-Lookup mehrere Geräte (drei Küchenlichter), werden alle nacheinander per HA-REST angesprochen — mit demselben Wert, falls der Befehl wertbehaftet ist (PROJ-83: „auf 30 Prozent"). Die Rückmeldung wird **einmal raumbezogen** formuliert:

- Alles ok: „Licht im Büro eingeschaltet."
- Teilweise: „Licht im Büro eingeschaltet, außer LED-Ring (nicht erreichbar)."
- Nichts ok: jedes Gerät wird einzeln als Fehler benannt.

Das ist eine neue Formatierungs-Schicht über den bereits vorhandenen Pro-Gerät-Ergebnissen — die Einzelergebnisse (Erfolg/Fehler je `entity_id`) entstehen wie heute.

### Die Rückfrage (Stufe 4)

Wenn weder Text noch Gerätekontext einen Raum hergeben — typisch bei Webapp-Chat (`webapp_cc`, `webapp_mic`) oder einem HA Voice PE ohne `room`-Eintrag — antwortet Alice mit einer deutschen Rückfrage und führt nichts aus. **Kein Zustand wird gespeichert.** Der Nutzer muss den vollständigen Befehl inklusive Raum erneut sagen. Antwortet er nur mit „Büro", ist das für Alice eine neue, für sich stehende Nachricht ohne erkennbaren Befehl — sie landet im normalen LLM-Pfad. Das ist die in der Spec bewusst gewählte Vereinfachung (kein Slot-Filling), analog zum bestehenden `requires_confirmation`-Muster aus PROJ-83, das ebenfalls keinen Folgezustand hält.

### Rückfall auf den LLM-Pfad

Kennt Alice den Raum (genannt oder aus dem Gerät), findet dort aber **kein** Gerät der passenden Domain (z. B. „Licht einschalten" im Büro, aber dem Büro ist kein Licht zugeordnet), behandelt sie den Teilbefehl wie einen generellen Nicht-Treffer: der ganze Request geht auf den bestehenden LLM_ONLY-Pfad — gleiches Verhalten wie heute, wenn Weaviate nichts Passendes findet.

### Multi-Befehl

Der bestehende Sentence-Splitter aus PROJ-3 bleibt unverändert. Jeder Teilbefehl durchläuft die Rangfolge oben unabhängig — „Rolladen schließen und Licht ausschalten" im Büro wendet den Büro-Kontext getrennt auf beide Teile an. Ein Einkaufslisten-Teil im selben Satz wird wie in PROJ-83 vorab erkannt und läuft raum-unabhängig weiter.

### Tech-Entscheidungen (Begründung)

| Entscheidung | Warum |
| --- | --- |
| Raum aus `source` durchreichen statt neuem Feld | Der Wert existiert schon im Request, es fehlt nur die Weitergabe an zwei Funktionen. Minimaler Eingriff. |
| PostgreSQL-Lookup statt Live-HA-Abfrage | Gleiches Muster wie PROJ-83, hält den Pfad unter 200 ms, kein Netz-Roundtrip zu HA. |
| Explizit genanntes Gerät/Raum schlägt Gerätekontext | Der Nutzer, der einen Raum ausspricht, meint diesen — auch wenn er woanders steht. Entspricht der Alltagserwartung. |
| Rückfrage statt Raten | Ein zufällig gewähltes Gerät im ganzen Haus ist für den Nutzer schlechter als eine kurze Nachfrage. |
| Kein Slot-Filling / kein Session-Zustand | Der HA_FAST-Pfad ist bewusst zustandslos. Zustand würde ihn in einen Multi-Turn-Dialog verwandeln — eigenes, größeres Thema. |
| Alle Geräte einer Domain im Raum, nicht nur das nächstliegende | „Licht an" in einem Raum meint umgangssprachlich das ganze Zimmer, nicht eine Lampe. |

### Betroffene Komponenten

- `alice-chat-stream/app/main.py` — `source` an die zwei Fast-Path-Funktionen übergeben (wenige Zeilen).
- `alice-chat-stream/app/ha_path.py` — Kern der Arbeit: Raum aus `source` parsen, Text-Abgleich gegen `area_name`/`friendly_name`/`aliases`, Raum-Lookup-Query, Multi-Entity-Ausführung, raumbezogene Meldungs-Formatierung, Rückfrage-Zweig.
- Tests unter `alice-chat-stream/tests/` — neue Fälle für die Rangfolge, Multi-Entity, Rückfrage, Case-Insensitivität, Multi-Befehl.
- Keine Änderung an `alice-speech-gateway`, `alice-ha-sync`, DB-Schema, n8n.

### Offene Punkte / Annahmen

- **Annahme:** `alice.ha_entities.area_name` ist für die relevanten Entities tatsächlich flächendeckend befüllt (laut Spec durch PROJ-39 erledigt). Falls einzelne Entities keinen `area_name` haben, sind sie über den Raum-Lookup nicht erreichbar — sie bleiben aber über ihren Gerätenamen ansprechbar.
- **Annahme:** Der `room`-Wert in `device-mapping.yaml` ist textgleich mit `area_name` in Home Assistant (beide „Büro"). Weicht die Schreibweise ab, greift der Geräte-Raum-Kontext nicht. Der Abgleich ist case-insensitive, aber nicht fuzzy.

## Implementation Notes (Backend)

**Umgesetzt 2026-09-07** — reines Backend in `alice-chat-stream`, kein DB-/n8n-/Frontend-Anteil.

### Geänderte Dateien
- `app/ha_path.py` — Kern:
  - `parse_device_room(source)` — `"esphome:Büro"` → `"Büro"`. Der Speech-Gateway
    ersetzt Leerzeichen im Raumnamen durch Unterstriche (`wyoming_transport.py`
    Zeile 222–224: `device.room.replace(" ", "_")`), daher werden sie hier wieder
    zurückgewandelt. `"esphome"`, `"webapp_cc"`, `"webapp_mic"`, `None` → kein Raum.
  - Neue DB-Lookups gegen `alice.ha_entities` (alle mit `is_active = TRUE`):
    `_load_area_names()` (distinct `area_name`), `_load_entity_name_index()`
    (`friendly_name` + `aliases`, lowercase), `_load_area_entities(area, domain)`
    (`LOWER(area_name) = LOWER($1) AND domain = $2`).
  - `AreaResolution`-Dataclass mit `mode ∈ {"entity","area","ask"}`, pro Teilbefehl.
  - Rangfolge in `decide_path()` (jetzt mit `source`-Parameter): (1) Text nennt
    Gerät → `entity` (Weaviate-Einzeltreffer bleibt), (2) Text nennt bekannten
    Raum → `area` mit allen Domain-Entities dieses Raums, (3) Geräte-Raum aus
    `source` → `area`, (4) kein Raum → `ask`. Raum bekannt aber 0 Entities der
    Domain → ganzer Request auf LLM_ONLY.
  - `execute_ha_intents()` (neuer Parameter `area_targets`): `ask` → deutsche
    Rückfrage, nichts ausgeführt, kein LLM. `area` → ein HA-Call je Entity mit
    demselben (wertbehafteten) Parameter, eine raumbezogene Sammelmeldung via
    `_area_message()` (Teilfehler: „…, außer X (nicht erreichbar).“; 0 Erfolge:
    „Im Büro hat nichts geklappt: …“). Einzel-HTTP-Call in `_do_service_call()`
    extrahiert (vorher inline dupliziert).
  - Per-Entity-Temperaturgrenzen im `area`-Zweig (Edge Case Zeile 68): jede
    Climate-Entity wird gegen ihre eigene `min_temp`/`max_temp` geprüft.
- `app/main.py` — `source` an `decide_path()`, `decision.area_targets` an
  `execute_ha_intents()` durchgereicht (2 Zeilen).
- `tests/test_ha_path_area.py` — neu, 20 Tests (Rangfolge 1–4, Multi-Entity,
  Teilfehler, alle offline, Wert auf alle, Multi-Befehl, Case-Insensitivität,
  Tippfehler-Raum, Area+Einkaufsliste, `parse_device_room`).

### Testlauf
`pytest tests/ --ignore=tests/test_admin_dashboard.py` (redis-Dependency fehlt
lokal, unabhängig): **95 passed**, davon 25 für PROJ-84
(`tests/test_ha_path_area.py`), 0 Regressionen in den PROJ-83-Suiten.

### QA-Nachlauf 2026-09-07 — BUG-1/2/3 behoben
Erste QA-Runde fand 4 Bugs (0 Critical/High, 2 Medium, 2 Low). BUG-1/2/3
gemeinsame Wurzel: die PROJ-83-`_resolve_value`-Wertauflösung in Pass 1 ist nicht
area-aware und nutzte die zufällige Weaviate-Entity für Bereichsprüfung + Label.
Fix:
- Pass 1 überspringt für `area`-Teile die Entity-spezifische Prüfung; nur die
  „Zahl vorhanden?"-Prüfung bleibt (fehlt sie → LLM-Fallback wie gehabt).
- Prozent-Grenzen (universell 0–100) werden im Area-Zweig einmal raumbezogen
  geprüft und abgelehnt (kein HA-Call, kein interner Bezeichner in der Meldung).
- Temperatur-Grenzen werden pro Raum-Entity live geprüft (Spec Edge Case Z. 68).
- `_area_message` nutzt jetzt Domain-Nomen + korrekte Präposition
  (`_room_dat`: „im Büro" / „in der Küche", kleine `_FEMININE_ROOMS`-Liste) →
  „Licht im Büro eingeschaltet.", „Heizung in der Küche auf 21 Grad gestellt".
BUG-4 (generisches Rückfrage-Nomen für nicht in `_DOMAIN_NOUNS` gelistete Domains)
bewusst offen gelassen — Low, Kern-Domains korrekt.

### Abweichungen / Annahmen
- Rückfrage-Text ist domain-abhängig („In welchem Raum möchtest du das Licht
  steuern?“) über eine kleine `_DOMAIN_NOUNS`-Map; unbekannte/gemischte Domains →
  „…möchtest du das steuern?“.
- Die Spec-Annahme „`source`-Raum textgleich mit `area_name`“ stimmt nur bis auf
  die Unterstrich-Ersetzung des Gateways — die wird jetzt kompensiert, bleibt
  aber nicht fuzzy.

## QA Test Results

**Tested:** 2026-09-07
**Tester:** QA Engineer (AI)
**Method:** Code review + targeted async probes + pytest (unit/integration). Reines
Backend-Feature (kein UI, kein n8n) — kein Browser-/E2E-Test anwendbar.
**Test suite:** `pytest tests/ --ignore=tests/test_admin_dashboard.py` →
**Runde 1: 90 passed, 3 xfailed** (Bugs). **Runde 2 (nach BUG-1/2/3-Fix):
95 passed, 0 xfailed.** (`test_admin_dashboard.py` ignoriert — fehlende
`redis`-Dependency lokal, PROJ-84-unabhängig.) Neu: `tests/test_ha_path_area.py`
(25 Tests).

### Acceptance Criteria Status

#### AC-1: Raumloser Befehl über HA Voice PE → Raum des Geräts (`source: esphome:<Raum>`)
- [x] `parse_device_room("esphome:Büro")` → `"Büro"`; alle aktiven Entities der
  Domain im Raum werden Ziel (`test_device_room_applies_to_all_domain_entities`)
- [x] Unterstrich-Rückwandlung (`esphome:Wohn_zimmer` → `Wohn zimmer`) — Gateway
  ersetzt Leerzeichen durch `_`, wird kompensiert

#### AC-2: Genannter Raum hat Vorrang vor Geräte-Raum (case-insensitive)
- [x] `test_named_room_beats_device_room` — „Licht in der Küche" bei
  `source=esphome:Büro` steuert Küche
- [x] `test_room_match_case_insensitive` — „büro" matcht „Büro"

#### AC-3: Genannter Entity-/Alias-Name → wie bisher direkt diese eine Entity
- [x] `test_named_device_wins` — `mode="entity"`, ein HA-Call auf die
  Weaviate-Entity, kein Area-Lookup
- [x] Alias-Abgleich (`aliases`-Array) mitgeführt in `_load_entity_name_index()`

#### AC-4: Mehrere aktive Entities derselben Domain im Raum → alle angesprochen
- [x] `test_device_room_applies_to_all_domain_entities` (2 Lichter), gilt
  domain-übergreifend (Query nur nach `domain` gefiltert, keine Ausnahmen)

#### AC-5: Wertbehaftete Befehle → selber Wert auf alle betroffenen Entities
- [x] `test_value_applied_to_all_area_entities` — `brightness_pct: 30` an beide
- [x] Prozent-Bereichsprüfung (0–100) raumbezogen (`test_area_percent_out_of_range_message_is_room_scoped`)
- [x] Temperatur pro Raum-Entity gegen deren eigene `min_temp`/`max_temp`
  (`test_area_temperature_uses_per_entity_bounds`,
  `test_area_temperature_out_of_range_per_entity`) — **BUG-1 behoben**

#### AC-6: Erfolgsmeldung raumbezogen + einmalig
- [x] Eine Zeile statt einer pro Entity (`_area_message`)
- [x] Wortlaut spec-konform: „Licht im Büro eingeschaltet." /
  „Heizung in der Küche auf 21 Grad gestellt." — Domain-Nomen + korrekte
  Präposition je Raumgenus (`_room_dat`) — **BUG-3 behoben**
  (`test_area_message_grammar_feminine_room`, `..._masculine_room`)

#### AC-7: Teilfehler → Erfolg der übrigen + fehlgeschlagenes Gerät separat
- [x] `test_partial_failure_named_separately` → „Im Büro eingeschaltet, außer
  Büro Stehlampe (nicht erreichbar)."
- [x] `test_all_offline` → „Im Büro hat nichts geklappt: …" (0-von-N-Grenzfall)

#### AC-8: Kein Raum genannt UND keiner aus Gerätekontext → deutsche Rückfrage, nichts ausführen, kein LLM
- [x] `test_no_room_asks_back` (`webapp_cc`) + `qa_probe3` (`webapp_mic`) →
  „In welchem Raum möchtest du das Licht steuern?", `posts == []`, `results == []`
- [x] Bleibt im HA_FAST-Pfad (kein `streaming.stream_chat`-Aufruf)

#### AC-9: Rückfrage hält keinen Zustand
- [x] Kein Session-/Slot-State angelegt; `execute_ha_intents` gibt nur Text
  zurück, `main.py` persistiert wie ein normales HA_FAST-Ergebnis. Folge-Request
  „Büro" allein matcht keinen Intent → LLM_ONLY (bestehendes Verhalten)

#### AC-10: Raum bekannt, aber keine Entity der Domain → LLM_ONLY-Fallback
- [x] `test_room_without_matching_domain_falls_back_to_llm` — `area_lookup_failed`
  → `path = "LLM_ONLY"`

#### AC-11: Performance < 200 ms, kein LLM
- [x] Strukturell: HA_FAST-Zweig in `main.py` unverändert vor dem LLM-Return;
  PROJ-84 fügt 2–3 parametrisierte, indizierte PG-Queries in `decide_path` hinzu
  (`area_name`-Distinct, Name-Index, Raum-Entity-Lookup) — lokal, Sub-ms.
  Live-Messung wie bei PROJ-83 AC-6 steht aus (Deploy-Nachlauf).

#### AC-12: Multi-Befehl mit Area-Context über den Sentence-Splitter
- [x] `test_multi_command_independent_area_context` — jeder Teil bekommt sein
  eigenes `AreaResolution`
- [x] `test_area_plus_shopping` — Einkaufslisten-Teil läuft area-unabhängig weiter

#### AC-13: Bestehende Einzelgerät-/Raum-Befehle unverändert — keine Regression
- [x] Alle 68 PROJ-83-Tests grün; Einzel-Entity-Zweig unverändert (nur der
  HTTP-Call in `_do_service_call` extrahiert)
- [~] Kleiner Wortlaut-Shift: Einzel-Entity-Fehlermeldung nennt jetzt den
  Friendly Name statt `entity_id`/`domain` (konsistent mit PROJ-83 BUG-3, keine
  Testregression)

#### AC-14: Raum-Abgleich case-insensitive
- [x] `_load_area_entities` nutzt `LOWER(area_name) = LOWER($1)`,
  `_text_names_area` vergleicht lowercase (`test_room_match_case_insensitive`)

### Edge Cases Status

- [x] **EC — eine von mehreren Entities schon im Zielzustand**: idempotenter
  HA-Call, zählt als Erfolg (kein Sonderfall im Code)
- [x] **EC — genannter Raum existiert nicht** (`Bürro`): kein Area-Treffer →
  Geräte-Raum greift, sonst Rückfrage (`test_typo_room_name_falls_through_to_ask`)
- [x] **EC — Einzel-Entity genannt, die nicht im Geräte-Raum liegt**:
  `mode="entity"` hat Vorrang, Weaviate-Match wird direkt verwendet
- [x] **EC — Raumname = Teil eines Gerätenamens** („Büro Deckenlampe" / „Büro"):
  `_text_names_entity` prüft zuerst; führt bei echtem Gerätenamen zu `entity`,
  sonst zu `area` — beide landen im Büro-Kontext (kein Konflikt)
- [x] **EC — kurzer Raumname als Substring** („Bad"): dokumentierte akzeptierte
  Grenze, kein Wortgrenzen-Escape (Spec)
- [x] **EC — genau eine Entity der Domain im Raum**: `entity_ids == [einer]`,
  gleicher Codepfad wie bei mehreren
- [x] **EC — Multi-Befehl: Area-Teil + expliziter Einzelgerät-Wert-Teil**: je
  Teil unabhängig aufgelöst
- [x] **EC — Area-Teil + Einkaufslisten-Teil**: `test_area_plus_shopping`
- [x] **EC — alle Entities offline**: `test_all_offline` → keine Erfolgsmeldung,
  jede einzeln als Fehler
- [x] **EC — Rückfrage, Nutzer antwortet nur mit Raumnamen**: kein State → neue
  Nachricht ohne Intent → LLM_ONLY
- [x] **EC — Wert außerhalb des Bereichs bei Multi-Climate mit unterschiedlichen
  `min_temp`/`max_temp`**: jede Climate-Entity wird gegen ihre eigenen Grenzen
  geprüft, innerhalb → ausgeführt, außerhalb → einzeln mit tatsächlichem Bereich
  benannt (`test_area_temperature_out_of_range_per_entity`) — BUG-1 behoben

### Security Audit Results

**Docker/Backend feature:**
- [x] Authentifizierung: `/stream/chat` unverändert hinter `verify_jwt`
- [x] SQL-Injection: alle neuen Queries parametrisiert (`$1`, `$2`,
  `ANY($1::text[])`); `source` zusätzlich durch `ChatRequest._check_source`
  validiert (`esphome:<x>` Whitelist). Ein bösartiger `source`-Wert landet nur
  als harmloser, ergebnisloser Parameter im Area-Lookup
- [x] Keine Secrets in Logs (`logger.warning` loggt nur Exception-Text +
  Raum-/Domain-Namen, keine Tokens)
- [x] Keine sensiblen Daten in der Antwort
- [~] **Beobachtung (kein neuer Bug):** Der HA_FAST-Pfad prüft weiterhin keine
  per-User-HA-Berechtigung (`alice.permissions_home_assistant`) — vorbestehend
  seit PROJ-1/PROJ-83. PROJ-84 vergrößert den Wirkradius leicht (ein Befehl
  adressiert jetzt *alle* Geräte einer Domain im Raum statt einem). Sollte als
  eigenes Feature/Bug gegen den HA-Pfad insgesamt adressiert werden.

### Bugs Found

#### BUG-1: Temperatur im Area-Modus wurde gegen die falschen Grenzen geprüft — BEHOBEN
- **Severity:** Medium
- **Status:** ✅ behoben 2026-09-07 (QA-Nachlauf)
- **Root cause:** `execute_ha_intents` Pass 1 rief für jeden wertbehafteten
  Intent `_resolve_value(intent, …)` auf, das `_fetch_temp_range(intent.entity_id)`
  auf die von Weaviate zufällig gematchte Entity anwendet. Lag der gesprochene
  Wert außerhalb *deren* `min_temp`/`max_temp`, brach die Schleife bei
  `if not resolved["ok"]` ab und der Area-Zweig mit der korrekten Pro-Entity-
  Prüfung wurde nie erreicht. Zusätzlich leakte der Weaviate-Slug in die Antwort.
- **Fix:** Pass 1 überspringt für `area`-Teile die Entity-spezifische Prüfung
  (nur „Zahl vorhanden?"); Temperaturgrenzen pro Raum-Entity live im Area-Zweig.
- **Test:** `test_area_temperature_uses_per_entity_bounds`,
  `test_area_temperature_out_of_range_per_entity`

#### BUG-2: Bereichsfehler-Meldung im Area-Modus nannte den Weaviate-Slug — BEHOBEN
- **Severity:** Medium
- **Status:** ✅ behoben 2026-09-07 (QA-Nachlauf, selbe Ursache wie BUG-1)
- **Root cause:** Auch für Prozent-Werte (universelle 0–100-Grenzen) lief die
  Ablehnung über den Einzel-Entity-Zweig von Pass 1 → `_entity_label` der
  Weaviate-Entity → Slug-Fallback in der deutschen Meldung.
- **Fix:** Prozent-Grenzen werden im Area-Zweig einmal raumbezogen geprüft:
  „Licht im Büro lässt sich nur zwischen 0 und 100 Prozent einstellen.", kein
  HA-Call, kein interner Bezeichner.
- **Test:** `test_area_percent_out_of_range_message_is_room_scoped`

#### BUG-3: Area-Erfolgsmeldung — Wortlaut & Grammatik — BEHOBEN
- **Severity:** Low
- **Status:** ✅ behoben 2026-09-07 (QA-Nachlauf)
- **Root cause:** `_area_message` baute „Im {area} …" mit fester Präposition und
  ohne Domain-Nomen (außer bei Temperatur).
- **Fix:** `_DOMAIN_SUBJECT` (Nominativ-Nomen) + `_room_dat()` (Präposition je
  Raumgenus, kleine `_FEMININE_ROOMS`-Liste) → „Licht im Büro eingeschaltet.",
  „Rolladen im Büro geschlossen.", „Licht in der Küche auf 30 Prozent gestellt."
- **Test:** `test_area_message_grammar_feminine_room`, `..._masculine_room`

#### BUG-4: Rückfrage-Nomen für nicht abgedeckte Domains generisch
- **Severity:** Low
- **Root cause:** `_DOMAIN_NOUNS` deckt 8 Domains ab; alles andere und gemischte
  Domains → „In welchem Raum möchtest du **das** steuern?"
- **Impact:** Grammatisch tragbar, aber unspezifisch. Für die Kern-Domains
  (light/cover/climate/…) korrekt.
- **Priority:** Nice to have

### Summary
- **Acceptance Criteria:** 13/14 vollständig bestanden (AC-1…AC-10, AC-12…AC-14).
  AC-11 (Live-Performance-Messung < 200 ms) strukturell erfüllt, Live-Messung
  offen bis Deploy-Nachlauf (analog PROJ-83 AC-6).
- **Edge Cases:** 12/12 bestanden.
- **Bugs Found:** 4 total (0 Critical, 0 High, 2 Medium, 2 Low).
  BUG-1, BUG-2, BUG-3 im QA-Nachlauf 2026-09-07 behoben + Tests. BUG-4 (Low)
  bewusst offen — generisches Rückfrage-Nomen nur für Domains außerhalb der
  8 Kern-Domains.
- **Security:** Pass — keine neuen Schwachstellen (alle Queries parametrisiert,
  `source` validiert). Vorbestehende Beobachtung: der HA_FAST-Pfad prüft keine
  per-User-HA-Berechtigung (seit PROJ-1/83); PROJ-84 vergrößert den Wirkradius
  leicht. Sollte als eigenes Feature gegen den HA-Pfad adressiert werden.
- **Regression:** Keine — 95 Tests grün, alle PROJ-83-Suiten unberührt.
- **Production Ready:** YES — 0 Critical/High, alle Medium-Bugs behoben, nur
  1 Low offen (BUG-4, kosmetisch, Kern-Domains korrekt).
- **Recommendation:** Deploy. BUG-4 bei Gelegenheit nachziehen.

## Deployment

**Deployed:** 2026-09-07 — Docker-Container `alice-chat-stream` neu gebaut und
ausgerollt (nur `app/ha_path.py` + `app/main.py` geändert; keine Schema-Migration,
kein n8n-Deploy, kein Frontend-Build).

### Live-Verifikation 2026-09-07

| Szenario | Ergebnis |
| --- | --- |
| Licht einschalten / ausschalten (raumlos, über HA Voice PE) | ✅ korrekter Raum, alle Lichter |
| Rolladen auf 50 % (wertbehaftet, Area-Context) | ✅ Wert auf alle Rolladen im Raum |
| Rolladen öffnen (wertlos, Area-Context) | ✅ |
| Entität, die nur einmal im Haus vorkommt | ✅ funktional identisch zum bisherigen Einzel-Entity-Fall |
| Ein Device + Area-Zuordnung | ✅ Geräte-Raum greift |
| Rückfrage bei fehlendem Raum | ✅ „In welchem Raum …?", nichts ausgeführt |

### Performance (AC-11)

Live gemessen über 5 Area-Context-Anfragen: **0,965 s gesamt ≈ Ø 193 ms/Anfrage**
— innerhalb des < 200-ms-Ziels (analog PROJ-3 AC-9 / PROJ-83 AC-6), kein
LLM-Aufruf. Damit ist AC-11 live bestätigt.

### Offen (nicht blockierend)

- **BUG-4** (Low, kosmetisch): generisches Rückfrage-Nomen für Domains außerhalb
  der 8 in `_DOMAIN_NOUNS` gelisteten Kern-Domains.
- Vorbestehende Beobachtung aus dem QA-Audit: der HA_FAST-Pfad prüft keine
  per-User-HA-Berechtigung (`alice.permissions_home_assistant`) — seit
  PROJ-1/PROJ-83. PROJ-84 vergrößert den Wirkradius leicht (ein Befehl adressiert
  jetzt alle Geräte einer Domain im Raum). Kandidat für ein eigenes Feature
  gegen den HA-Pfad insgesamt.
