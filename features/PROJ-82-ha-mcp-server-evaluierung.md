# PROJ-82: HA-MCP-Server-Evaluierung (Spike)

## Status: Approved
**Created:** 2026-09-03
**Last Updated:** 2026-09-03

## Dependencies
- None (Spike — bewertet, ersetzt/erweitert aber nichts produktiv)
- Vorgelagert zu: PROJ-83 (HA-Agent variable Intents), PROJ-84 (HA-Agent Area-Context) — beide starten erst nach Go/No-Go-Entscheidung aus diesem Spike

## Overview

Alice steuert Home Assistant aktuell über einen selbstgebauten Intent-Pfad: `alice-ha-sync` synchronisiert exponierte HA-Entitäten in eine Weaviate-Collection (`HAIntent`), `alice-chat-handler`/`alice-chat-stream` matcht Nutzer-Äußerungen per `nearText`-Suche gegen diese Collection und ruft HA-Services direkt per REST auf (PROJ-1, PROJ-3, PROJ-39). Das deckt einfache Sprachsteuerung ab, aber (a) keine variablen Werte (Prozent, Mengen, Listen-Einträge — geplant als PROJ-83), (b) keinen Raum-Kontext aus dem sprechenden Gerät (geplant als PROJ-84), und (c) keine Dashboard- oder Automations-Erstellung/-Bearbeitung.

Der externe `ha-mcp`-Server (github.com/homeassistant-ai/ha-mcp) bietet als MCP-Tool-Set einen breiteren Funktionsumfang: neben Assist-artiger Gerätesteuerung auch Dashboard-Erstellung/-Bearbeitung und Automations-Erstellung/-Bearbeitung.

Dieser Spike prüft **vor** dem Start von PROJ-83/84, ob ha-mcp (a) eine sinnvolle **Ergänzung** ist (neue Fähigkeiten wie Dashboard/Automation-Management, die der bisherige Ansatz nicht bietet) und/oder (b) eine **Verbesserung** des bisherigen Intent-Pfads selbst darstellt (z. B. bessere native Unterstützung für variable Werte oder Area-Context als PROJ-83/84 sonst selbst bauen müssten). Ergebnis ist ein Vergleichsdokument mit klarer Empfehlung, das Andreas' Go/No-Go-Entscheidung für die Architektur von PROJ-83/84 informiert.

**Kein Ziel dieses Spikes:** Produktiv-Integration von ha-mcp in Alice, Migration des bestehenden Intent-Pfads, Wegwerfen von PROJ-1/3/39-Infrastruktur. Der Spike liefert nur die Entscheidungsgrundlage.

## User Stories

- Als Andreas möchte ich wissen, ob ha-mcp den bestehenden Weaviate/n8n-Intent-Pfad ersetzen sollte, ergänzen sollte, oder ob sich der Aufwand nicht lohnt, damit ich PROJ-83/84 auf der richtigen Grundlage plane.
- Als Andreas möchte ich sehen, wie ha-mcp mit variablen Werten (z. B. Rolladen auf 50 %) und Raum-Kontext (z. B. "Licht im Büro") umgeht, damit ich einschätzen kann, ob es PROJ-83/84 einfacher macht oder überflüssig macht.
- Als Andreas möchte ich sehen, ob ha-mcp Dashboards und Automationen tatsächlich sinnvoll lesen/erstellen/bearbeiten kann, damit ich weiß, ob Alice damit zur besseren HA-Verwaltungs-Oberfläche werden kann.
- Als Andreas möchte ich das Sicherheitsmodell von ha-mcp verstehen (Token-Scope, Schreibrisiko), bevor ich es an produktive HA-Steuerung heranlasse.
- Als Andreas möchte ich am Ende eine klare, begründete Empfehlung lesen (nicht nur Rohdaten), damit ich die Go/No-Go-Entscheidung schnell treffen kann.

## Acceptance Criteria

### Testaufbau
- [x] `ha-mcp`-Server läuft testweise als eigener Docker-Container gegen die produktive HA-Instanz (`HA_URL`, ein dedizierter Long-Lived Token — nicht der produktive `HA_TOKEN` aus n8n/alice-ha-sync)
- [x] Server wird ausschließlich über einen MCP-Client (Claude Code direkt) angesprochen — **keine** Änderung an `alice-chat-stream`, `alice-chat-handler` oder n8n-Workflows
- [x] Testcontainer wird nach Abschluss des Spikes wieder gestoppt und entfernt (kein Dauerbetrieb, kein Compose-File in `docker/compose/`)

### Testfälle (alle 5 durchgeführt — erfolgreich oder mit dokumentiertem Fehlschlag)
- [x] Test 1 — Einfacher Intent: "Licht im Büro einschalten" über ha-mcp ausgeführt, Antwortzeit gemessen und mit dem bestehenden HA_FAST-Pfad (< 200 ms laut PROJ-3) verglichen
- [x] Test 2 — Variabler Intent (PROJ-83-Bezug): "Rolladen auf 50 % stellen" über ha-mcp ausgeführt, geprüft ob der Prozentwert korrekt und ohne Vorab-Expansion (vgl. PROJ-39 Value-Placeholder-Expansion) verarbeitet wird
- [x] Test 3 — Area-Context (PROJ-84-Bezug): "Licht im Büro" (ohne explizite Entity-Nennung) über ha-mcp ausgeführt, geprüft ob Raumzuordnung nativ funktioniert oder ob eigene Area-Sync-Logik (wie in PROJ-39) weiterhin nötig wäre
- [x] Test 4 — Dashboard lesen: ein bestehendes Lovelace-Dashboard über ha-mcp ausgelesen, Ergebnis auf Vollständigkeit/Korrektheit geprüft
- [x] Test 5 — Automation erstellen/ändern: eine Test-Automation (klar als Test gekennzeichnet, keine produktive Automation verändert) über ha-mcp angelegt oder bearbeitet, Ergebnis in HA UI verifiziert

### Vergleichsdokument
- [x] Neues Dokument `features/PROJ-82-ha-mcp-vergleich.md` (oder gleichnamiger Abschnitt in diesem Spec) enthält eine Vergleichstabelle mit mindestens folgenden Dimensionen: Latenz, variable Intents, Area-Context, Dashboard-Fähigkeit, Automations-Fähigkeit, Betriebsaufwand (neuer Container, Auth-Setup), Sicherheitsmodell
- [x] Sicherheitsmodell wird als eigene Dimension bewertet: benötigter HA_TOKEN-Scope, Risiko durch Schreibzugriff auf Automationen/Dashboards, Bezug zum offenen SEC-5-Punkt aus PROJ-3 (`permissions_home_assistant` ist noch nicht in den Chat-Handler verdrahtet)
- [x] Dokument enthält eine klare Empfehlung (Ergänzung / Ersatz / beides nicht sinnvoll) mit Begründung, keine reine Datensammlung ohne Fazit
- [x] Dokument beschreibt konkret, wie sich die Empfehlung auf PROJ-83 (variable Intents) und PROJ-84 (Area-Context) auswirkt — z. B. "PROJ-83 kann nativ über ha-mcp gelöst werden, eigene Value-Expansion entfällt" oder "PROJ-83 bleibt wie geplant, ha-mcp nur für Dashboard/Automation als separates neues Feature"
- [x] Andreas hat das Dokument gelesen und eine Go/No-Go-Entscheidung getroffen (dokumentiert als Ergänzung am Ende des Dokuments: Entscheidung + Datum)

## Edge Cases

- **ha-mcp-Container startet nicht / kann sich nicht mit HA verbinden**: Fehler dokumentieren, betroffene Testfälle als "nicht durchführbar" markieren, Spike trotzdem mit den übrigen Testfällen abschließen — kein Blocker für das Vergleichsdokument.
- **Ein Testfall schlägt fehl (z. B. Automation-Erstellung produziert eine ungültige Automation)**: Fehlschlag wird dokumentiert (nicht verschwiegen) und fließt als Minuspunkt in die jeweilige Vergleichsdimension ein — der Spike gilt trotzdem als abgeschlossen.
- **ha-mcp benötigt einen HA_TOKEN mit weiterreichenden Rechten als der bestehende (z. B. Automations-Schreibzugriff)**: Für den Test wird ein separater, dedizierter Long-Lived Token mit dem für die Tests nötigen Scope erstellt — niemals der produktive `HA_TOKEN` aus `alice-ha-sync`/n8n wiederverwendet.
- **Test-Automation (Testfall 5) verändert versehentlich reale Geräte**: Test-Automation muss vor Ausführung als harmlos verifiziert werden (z. B. nur Logging/Notification, kein Geräte-Trigger auf echte Aktoren) oder auf eine Test-Entity beschränkt werden.
- **Beide Ansätze schneiden in etwa gleich ab (kein klares Go/No-Go)**: Dokument empfiehlt in diesem Fall explizit den risikoärmeren Pfad — PROJ-83/84 starten mit dem bestehenden n8n/Weaviate-Ansatz (kein Blocker), eine mögliche ha-mcp-Ergänzung für Dashboard/Automation würde dann als eigenständiges neues Feature nachgelagert bewertet.
- **HA-Instanz während der Tests nicht erreichbar (Netzwerk/VPN-Problem)**: Testlauf wird verschoben, kein Workaround mit Mock-Daten — der Spike bewertet reales Verhalten gegen die echte Instanz.
- **Docker-Testergebnis überträgt sich nicht 1:1 auf HACS-Betrieb**: Der Docker-Modus deckt alle 5 Testfälle mit voller Funktionsparität ab, aber 5 privilegierte Datei-/YAML-Tools sind exklusiv dem HACS/Custom-Component-Modus vorbehalten. Falls eine spätere Go-Entscheidung (PROJ-83/84) diese Tools benötigt, muss der Betriebsmodus (Docker vs. HACS) separat neu bewertet werden — das Vergleichsdokument macht diese Einschränkung explizit, damit sie nicht übersehen wird.

## Technical Requirements

- Kein Zugriff auf/keine Änderung an produktiven n8n-Workflows, `alice-chat-stream` oder `alice-ha-sync` während des Spikes
- Dedizierter HA Long-Lived Access Token für den Testcontainer, getrennt vom produktiven `HA_TOKEN`
- Testcontainer läuft nur temporär (manueller Start/Stop während des Spikes), kein Docker-Compose-Eintrag im Projekt
- Vergleichsdokument auf Deutsch (Feature-Doku-Konvention)

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Überblick

Dieser Spike ist reine **Ablauf- und Vergleichsarbeit**, kein produktives Feature — es entsteht kein Docker-Compose-Stack im Projekt, kein DB-Schema, kein n8n-Workflow, keine Frontend-Komponente. Das einzige Artefakt, das im Repo bleibt, ist das Vergleichsdokument. Der Testcontainer und die MCP-Client-Anbindung sind temporäre, manuell durchgeführte Schritte während des Spikes.

### A) Testaufbau (Ablauf, kein Dauerbetrieb)

```
Schritt 1: Dedizierter HA-Token
  └── In Home Assistant UI ein neues Long-Lived Access Token erstellen,
      nur für diesen Spike — getrennt vom produktiven Token, den
      alice-ha-sync/n8n verwenden

Schritt 2: ha-mcp-Container starten
  └── Docker-Image ghcr.io/homeassistant-ai/ha-mcp im HTTP-Modus,
      manuell per docker run gestartet (kein compose.yml im Repo)
  └── Konfiguration: HA-Instanz-Adresse + das dedizierte Token aus Schritt 1
  └── Läuft nur lokal/temporär, kein Eintrag in docker/compose/

Schritt 3: Als MCP-Server in Claude Code einbinden
  └── Temporäre MCP-Server-Verbindung zum laufenden Container
      (HTTP-Transport, wie vom ha-mcp-Server vorgesehen)

Schritt 4: 5 Testfälle als Tool-Calls ausführen
  └── Ergebnisse (Antwortzeit, Korrektheit, Fehler) direkt in dieser
      Session beobachtet und protokolliert

Schritt 5: Aufräumen
  └── MCP-Server-Verbindung in Claude Code wieder entfernen
  └── Container stoppen und entfernen
  └── Test-Token in Home Assistant widerrufen
```

### B) Was verglichen wird (Datenmodell des Vergleichsdokuments)

Kein Datenbankschema — das Vergleichsdokument ist eine strukturierte Markdown-Tabelle. Pro Dimension wird der bestehende Ansatz (n8n + Weaviate `HAIntent`, siehe PROJ-1/PROJ-3/PROJ-39) dem ha-mcp-Ansatz gegenübergestellt:

```
Dimension            | Bestehender Ansatz        | ha-mcp (Testergebnis)
----------------------|----------------------------|------------------------
Latenz                | < 200ms (HA_FAST, kein LLM)| gemessen in Test 1
Variable Intents      | nicht vorhanden (→ PROJ-83)| Test 2
Area-Context           | vorhanden (PROJ-39)        | Test 3
Dashboard-Fähigkeit    | nicht vorhanden            | Test 4
Automations-Fähigkeit  | nicht vorhanden            | Test 5
Betriebsaufwand        | läuft bereits produktiv    | neuer Container + Auth
Sicherheitsmodell      | HA_TOKEN nur für Service-Calls, keine granularen
                         Permission-Checks (offener SEC-5 aus PROJ-3)
                       | Scope + Schreibrisiko aus dem Testaufbau bewertet
```

Am Ende der Tabelle steht die Empfehlung (Ergänzung / Verbesserung / keins von beidem) in Fließtext, plus die Auswirkung auf PROJ-83 und PROJ-84.

### C) Tech-Entscheidungen (Begründung)

| Entscheidung | Wahl | Warum |
| --- | --- | --- |
| Betriebsmodus für den Test | Docker-Image im HTTP-Modus (offizieller Modus des ha-mcp-Projekts) | Kein Eingriff in die Home-Assistant-Installation selbst (Custom-Component/Add-on-Modus würde HA direkt verändern) — sauber isolierbar und rückstandsfrei entfernbar |
| MCP-Client | Claude Code (diese Session) | Kein zusätzliches Tool nötig, Testergebnisse direkt nachvollziehbar und dokumentierbar, keine Medienbrüche |
| Kein Compose-File im Repo | Manueller `docker run`, kein `docker/compose/`-Eintrag | Der Spike soll keine produktions-ähnliche Infrastruktur hinterlassen — verhindert versehentlichen Dauerbetrieb oder Verwechslung mit produktiven Stacks |
| Dedizierter HA-Token | Neues Long-Lived Token, nach dem Spike widerrufen | Home Assistant kennt kein granulares Token-Scoping — ein Token hat vollen API-Zugriff; ein separates Token begrenzt den Blast Radius und macht das Sicherheits-Testergebnis (Dimension „Sicherheitsmodell") aussagekräftig, ohne den produktiven Token-Scope zu vermischen |
| Vergleichsdokument als Markdown im Feature-Ordner | Erweiterung des bestehenden PROJ-82-Spec-Dokuments (kein separates Repo-Artefakt) | Konsistent mit Projektkonvention: Feature-Dokumentation lebt in `features/`, ein Spike braucht keine eigene Dokument-Hierarchie |
| Docker-Modus statt HACS/Custom-Component | Externer Docker-Container (siehe Abschnitt A) | Laut ha-mcp-Doku volle Funktionsparität zu HACS für Gerätesteuerung, Dashboard-Management und Automation-Erstellung — genau die 5 Testfälle. Einzige Einschränkung: 5 privilegierte Datei-/YAML-Tools (`ha_config_set_yaml`, `ha_read_file`, `ha_write_file`, `ha_delete_file`, `ha_list_files`) sind exklusiv dem HACS/Custom-Component-Modus vorbehalten (benötigen Zugriff auf das HA-Host-Dateisystem) — für keinen der 5 Testfälle relevant |

### D) Keine neuen Abhängigkeiten im Projekt

Kein neues npm-/Python-Paket, kein neuer dauerhafter Docker-Container, keine neue Datenbanktabelle, keine neue Weaviate-Collection, keine Änderung an bestehenden n8n-Workflows. Die einzige "Abhängigkeit" ist das extern gehostete Docker-Image `ghcr.io/homeassistant-ai/ha-mcp`, das nur temporär während des Spikes gezogen wird.

### E) Abgrenzung zu PROJ-83/84

Dieser Spike trifft keine Implementierungsentscheidung für PROJ-83/84 — er liefert nur die Grundlage. Fällt die Entscheidung für "Ergänzung" oder "Verbesserung", braucht die eigentliche Integration (z. B. ha-mcp dauerhaft betreiben, in `alice-chat-stream`/n8n einbinden, Permission-Checks aus PROJ-3 SEC-5 auf den neuen Pfad anwenden) eine eigene Architektur-Runde innerhalb von PROJ-83/84 — nicht Teil dieses Spikes.

## Vergleichsdokument (Spike-Ergebnis)

**Durchgeführt:** 2026-09-03
**Testaufbau:** `ha-mcp` (Docker-Image `ghcr.io/homeassistant-ai/ha-mcp:latest`, HTTP-Transport via `fastmcp-http.json`) gegen die produktive HA-Instanz (`http://homeassistant.lan:8123`), dediziertes Long-Lived Token, angesprochen über einen temporären MCP-Server in Claude Code (78 Tools geladen). Kein Alice/n8n-Wiring. Container und Test-Automation wurden nach Abschluss vollständig entfernt, alle während der Tests veränderten Live-Zustände (Licht, Rollladen) zurückgesetzt.

### Vergleichstabelle

| Dimension | Bestehender Ansatz (n8n + Weaviate `HAIntent`) | ha-mcp (Testergebnis) |
| --- | --- | --- |
| **Latenz** | Architektonisches Ziel < 200 ms (HA_FAST, kein LLM-Call) — laut PROJ-3-QA nie live verifiziert (AC-9/AC-10 "CANNOT VERIFY") | Test 1: Erster `light.turn_on`-Aufruf schlug mit einem **HA-seitigen 500er** fehl ("Server got itself in trouble"), zweiter Versuch erfolgreich in ~5,1 s End-to-End. Diese Zeit schließt den kompletten MCP-Tool-Call-Overhead dieser Session (mehrere Hops: Claude Code → Container → HA) ein und ist **nicht 1:1 mit einem reinen HTTP-Benchmark vergleichbar** — aber selbst mit großzügigem Abzug für Overhead liegt sie klar über der 200-ms-Zielmarke des bestehenden Pfads |
| **Variable Intents** (→ PROJ-83) | Nicht vorhanden — PROJ-39 überspringt `{value}`/`{temperature}` nicht mehr, expandiert aber nur auf **feste Diskretwerte** (10/25/50/75/100 % bzw. 16–26 °C) | Test 2: **Nativ erfolgreich.** `cover.set_cover_position` mit `position: 50` wurde direkt und korrekt verarbeitet (`current_position` danach `50`) — kein Diskretisierungs-Pattern nötig, jeder beliebige Wert (auch z. B. 37 %) wäre genauso möglich |
| **Area-Context** (→ PROJ-84) | Vorhanden über eigenen Sync-Worker (PROJ-39: WebSocket-Abruf Entity-/Device-/Area-Registry, Duplizierung nach PostgreSQL + Weaviate) | Test 3: Volle Area-/Floor-Registry (**32 Areas, 6 Floors**) live und direkt aus HA abrufbar, kein eigener Sync-Worker nötig, um die Struktur zu kennen. **Aber:** Freitext-Fuzzy-Suche ("Licht Büro" als ein String) fand `light.buro_burolicht` **nicht** unter den Top-Treffern — erst die strukturierte Suche mit getrennten `domain_filter`+`area_filter`-Parametern lieferte das korrekte Ergebnis. ha-mcp bietet also die rohen Registry-Daten nativ, aber **keine eingebaute Semantiksuche** für ganze Äußerungen wie die bestehende Weaviate-`nearText`-Suche |
| **Dashboard-Fähigkeit** | Nicht vorhanden | Test 4: **Erfolgreich.** Vollständiges 18-View-Dashboard ("Wandpanel") korrekt gelesen — gemischtes Layout (17 Views im neuen `sections`-Format, 1 View im klassischen `cards`-Format), ~300+ Karten, 403 Entity-Referenzen, kein erkennbarer Datenverlust |
| **Automations-Fähigkeit** | Nicht vorhanden | Test 5: **Erfolgreich.** Test-Automation erstellt (native Trigger/Actions, kein Template-Bypass — durch den mitgelieferten Best-Practice-Skill-Gate erzwungen), per `automation.trigger` sicher ausgelöst, Wirkung über eine `persistent_notification` verifiziert, danach vollständig wieder gelöscht |
| **Betriebsaufwand** | Läuft bereits produktiv (n8n + `alice-ha-sync` + Weaviate) | Neuer Container nötig. **Stolperstein:** Das Docker-Image startet per Default im **stdio-Modus** (nicht HTTP) — der HTTP-Modus erfordert einen expliziten Zusatzparameter (`fastmcp run fastmcp-http.json`), was aus der Doku nicht sofort ersichtlich war. Automation-Erstellung erzwingt zusätzlich einen Skill-Guide-Lesevorgang samt Attestations-Key (`BestPracticeKey`) — funktioniert zuverlässig, ist aber ein zusätzlicher Schritt gegenüber dem bestehenden Pfad |
| **Sicherheitsmodell** | `HA_TOKEN` wird nur für vordefinierte Service-Calls verwendet; granulare Permission-Checks (`alice.permissions_home_assistant`) sind noch **nicht** in den Chat-Handler verdrahtet (offener SEC-5-Punkt aus PROJ-3) | Ein einzelnes Long-Lived Token gibt **vollen HA-API-Zugriff** (HA kennt kein natives granulares Token-Scoping). ha-mcp kann per Design Dashboards **und** Automationen **schreibend** ändern — der Blast Radius ist damit strukturell größer als beim bestehenden reinen Service-Call-Pfad. Ein produktiver Einsatz bräuchte mindestens ein eng gefasstes Token plus eine eigene Absicherung kritischer Schreibpfade (Automations-/Dashboard-Änderungen), sonst würde das offene SEC-5-Risiko eher vergrößert als adressiert |

### Empfehlung

**Ergänzung, nicht Ersatz.** ha-mcp sollte den bestehenden n8n/Weaviate-Intent-Pfad **nicht ablösen** — dafür sprechen drei Befunde aus den Tests:

1. **Latenz**: Selbst mit Vorbehalt zur Messmethodik liegt ha-mcp klar über der 200-ms-Zielmarke des HA_FAST-Pfads (Test 1).
2. **Keine eingebaute NLU**: ha-mcp löst rohe Äußerungen wie "Licht im Büro" nicht selbst semantisch auf (Test 3) — eine aufrufende Instanz (LLM-Agent) müsste Domain/Area/Wert selbst strukturiert extrahieren, was im Kern dasselbe Problem ist, das die bestehende Weaviate-`nearText`-Suche bereits löst.
3. **Sicherheitsrisiko**: Voller, ungescopeter Schreibzugriff auf Automationen und Dashboards über ein einzelnes Token würde den bereits offenen SEC-5-Punkt aus PROJ-3 eher verschärfen als lösen (siehe Sicherheits-Dimension oben).

Gleichzeitig zeigen die Tests 4 und 5 klar: ha-mcp deckt **echte neue Fähigkeiten** ab, die der bestehende Ansatz überhaupt nicht bietet (Dashboard lesen, Automation erstellen/bearbeiten) — und tut das zuverlässig und mit eingebauten Schutzmechanismen (Best-Practice-Gate für Automationen). Das ist die Stärke von ha-mcp: **Ergänzung** um Fähigkeiten außerhalb der reinen Sprachsteuerung, nicht Verbesserung der Sprachsteuerung selbst.

### Auswirkung auf PROJ-83 (variable Intents)

**PROJ-83 bleibt architektonisch wie geplant** — Erweiterung der eigenen Utterance-zu-Value-Erkennung (Weaviate/n8n-Pipeline), kein Ersatz durch ha-mcp. Der native Umgang mit kontinuierlichen Werten bei ha-mcp (Test 2) ist ein guter Designhinweis (Zielsysteme akzeptieren beliebige Werte, nicht nur diskrete Stufen — PROJ-83 muss die Wert-**Erkennung** aus der Äußerung lösen, nicht nur die Wert-**Übergabe**), aber ha-mcp übernimmt nicht den eigentlichen Kern von PROJ-83: die Übersetzung einer gesprochenen Zahl/eines Prozentworts in einen strukturierten Wert. Das bleibt Aufgabe der eigenen Pipeline.

### Auswirkung auf PROJ-84 (Area-Context)

**PROJ-84 bleibt beim bestehenden Sync-Ansatz** (Erweiterung von PROJ-39). Die Area-/Floor-Registry ist über ha-mcp zwar bequem live abrufbar (Test 3), aber ein Live-Abruf bei jeder Chat-Anfrage würde die < 200-ms-Zielmarke des HA_FAST-Pfads gefährden — die Daten müssen weiterhin vorab in die Weaviate-`HAIntent`-Struktur synchronisiert werden, damit die schnelle Suche funktioniert. ha-mcp ersetzt hier nicht die Sync-Logik, sondern wäre bestenfalls eine alternative Datenquelle für den Sync-Worker selbst — kein Scope-Bestandteil dieses Spikes.

### Separater Ergänzungs-Kandidat

Sollte Andreas dashboard-/automations-bezogene Fähigkeiten für Alice wünschen, wäre das ein **eigenständiges neues Feature** (nachgelagert zu PROJ-83/84, nicht Teil davon) — mit eigener Architektur-Runde für: dauerhafter Betrieb (Compose-Stack), Integration in `alice-chat-stream`, ein eng gescoptes Token, und eine Absicherung der Schreibpfade (z. B. explizite Nutzerbestätigung vor Automations-/Dashboard-Änderungen), damit das bestehende SEC-5-Risiko aus PROJ-3 nicht vergrößert wird.

### Go/No-Go-Entscheidung

**No-Go (zurückgestellt) — 2026-09-03.** Andreas: "Die Implementierung eines ha-mcp-Servers wird zurückgestellt, bis eine konkrete Anforderung eine Umsetzung zwingend erfordert." PROJ-83 und PROJ-84 starten mit dem bestehenden n8n/Weaviate-Ansatz. Eine ha-mcp-Ergänzung (Dashboard-/Automations-Management) bleibt als möglicher separater Feature-Kandidat für später vorgemerkt, ohne aktuellen Auftrag.

## QA Test Results
_Kein `/qa`-Lauf nötig: Ergebnis dieses Spikes ist ein dokumentiertes No-Go, keine Implementierung. Andreas hat die Testergebnisse und die Empfehlung im Vergleichsdokument geprüft und direkt entschieden (2026-09-03)._

## Deployment
_To be added by /deploy_
