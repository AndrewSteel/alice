# PROJ-111: LLM-Gateway mit Priorisierung

## Status: Architected
**Created:** 2026-10-09
**Last Updated:** 2026-10-09

## Dependencies
- Requires: PROJ-99 (Umstellung Ollama → llama.cpp) — `llama-3090` ist der einzige Inference-Endpunkt, vor den das Gateway geschaltet wird

## Kontext

`llama-3090` hat genau einen Verarbeitungs-Slot (`parallel = 1`) und arbeitet Anfragen strikt in Eingangsreihenfolge ab — llama.cpp kennt keine Prioritäten. Tagsüber (07–22 Uhr) erzeugt die DMS-Pipeline über `alice-dms-path-worker` → `dms-extractor-image` sowie weitere n8n-Workflows viele Analyse-Anfragen. Eine Chat-Anfrage reiht sich dahinter ein und wartet, bis die gesamte Analyse-Warteschlange abgearbeitet ist. Aufgefallen beim Live-Test von PROJ-106 (Chat praktisch blockiert).

Architektur-Prüfung 2026-10-08: Eine vorgeschaltete Schicht, die den GPU-Slot nach Priorität vergibt, ist der richtige Ansatz. MQTT als Warteschlange wurde verworfen (Pub/Sub ohne „erst Prio-Queue prüfen“-Semantik, kein Request/Response-Streaming).

Modellwechsel sind **nicht** Teil dieses Features: Sie finden betrieblich ausschließlich nachts statt, tagsüber ist nur das Chat-Modell geladen.

## Prioritätsstufen

| Stufe | Aufrufer | Reihenfolge innerhalb der Stufe |
| --- | --- | --- |
| **Interaktiv** (Mensch wartet) | `alice-chat-stream` (WebApp-Chat + Voice PE), OpenWebUI, externer Zugang `llama3090.happy-mining.de` | nach Eingang (gleichberechtigt, auch zwischen mehreren Personen) |
| **Hintergrund** (Maschine) | `dms-extractor-image`, alle n8n-Workflows (DMS-Klassifizierung, Sprachprüfung, Mail-Sync, Backfills, Modell-Warmup, …) | nach Eingang |

Regel: **Mensch vor Maschine** — wird der Slot frei, kommt immer zuerst die älteste wartende interaktive Anfrage dran, erst wenn keine wartet, die älteste Hintergrund-Anfrage.

## User Stories
- Als Nutzer (WebApp, Voice PE oder OpenWebUI) möchte ich, dass meine Chat-Anfrage zügig beantwortet wird, auch wenn die DMS-Pipeline gerade viele Dokumente analysiert, damit Alice tagsüber als Assistent nutzbar bleibt.
- Als einer von mehreren gleichzeitigen Nutzern möchte ich in Eingangsreihenfolge bedient werden, damit niemand bevorzugt oder dauerhaft übergangen wird.
- Als Admin möchte ich, dass die DMS- und Mail-Analyse ohne Änderung ihrer Abläufe weiterläuft und nur hinter Chat-Anfragen zurücktritt, damit die Verarbeitung vollständig bleibt.
- Als Admin möchte ich in Logs und Prometheus sehen, wie lang die Warteschlangen sind und wie lange Anfragen je Stufe warten, damit ich beurteilen kann, ob weitere Maßnahmen (z.B. Abbruch laufender Hintergrund-Anfragen) nötig sind.
- Als Admin möchte ich, dass kein Aufrufer die Priorisierung umgehen oder sich selbst eine höhere Stufe geben kann, damit die Reihenfolge verlässlich ist.

## Acceptance Criteria

### Priorisierung
- [ ] Alle Aufrufer aus der Tabelle „Prioritätsstufen“ sprechen das LLM nur noch über das Gateway an; keiner ruft `llama-3090` direkt auf (auch nicht der externe Zugang über nginx).
- [ ] Warten interaktive und Hintergrund-Anfragen gleichzeitig, wird beim Freiwerden des Slots immer zuerst eine interaktive Anfrage weitergeleitet.
- [ ] Innerhalb einer Stufe werden Anfragen in Eingangsreihenfolge weitergeleitet (zwei gleichzeitige Chat-Anfragen verschiedener Personen: die zuerst eingegangene wird zuerst bedient).
- [ ] Es wird zu jedem Zeitpunkt höchstens eine Anfrage an `llama-3090` weitergeleitet (entspricht dem einen Slot).
- [ ] Eine laufende Hintergrund-Anfrage wird nicht abgebrochen; eine neu eintreffende interaktive Anfrage wartet höchstens, bis diese eine Anfrage fertig ist, und überholt alle wartenden Hintergrund-Anfragen.
- [ ] Testfall: 20 Hintergrund-Anfragen stehen in der Schlange, dann trifft eine Chat-Anfrage ein → die Chat-Anfrage ist die nächste, die an `llama-3090` geht.
- [ ] Die Stufe wird vom Gateway anhand der Identität des Aufrufers festgelegt; ein Aufrufer kann seine Stufe nicht selbst wählen oder erhöhen. Unbekannte/nicht zugeordnete Aufrufer laufen als Hintergrund.

### Transparenz gegenüber den Aufrufern
- [ ] Antworten (inkl. Token-Streaming, Thinking-Tokens und Tool-Calls im Chat-Agenten-Loop) kommen beim Aufrufer unverändert an — gleiches Verhalten wie bei direktem Aufruf von `llama-3090`.
- [ ] Die Aufrufer brauchen außer der Endpunkt-Adresse (und ggf. Zugangsschlüssel) keine Änderung an ihrer Logik; n8n-Workflows und `dms-extractor-image` laufen fachlich unverändert weiter.
- [ ] Ein Aufrufer, der die Verbindung abbricht, während seine Anfrage noch wartet, belegt keinen Slot mehr; seine Anfrage wird nicht mehr weitergeleitet.

### Sicherheit
- [ ] Das Gateway nimmt nur Anfragen mit gültigem Zugangsschlüssel (Bearer-Token) an; ohne bzw. mit falschem Schlüssel → Ablehnung, keine Weiterleitung.
- [ ] Das Gateway ist nur intern bzw. über VPN (nginx) erreichbar — gleiche Erreichbarkeit wie `llama-3090` heute.

### Betrieb & Sichtbarkeit
- [ ] Pro Anfrage ein strukturierter Log-Eintrag mit: Aufrufer, Stufe, Wartezeit in der Schlange, Laufzeit am LLM, Ergebnis (ok / Fehler / Timeout / Abbruch durch Aufrufer).
- [ ] Prometheus-Kennzahlen: aktuelle Schlangenlänge je Stufe, Wartezeit je Stufe, Anzahl Anfragen je Stufe und Ergebnis; im vorhandenen Prometheus eingebunden.
- [ ] Das Gateway startet automatisch neu und besitzt einen Healthcheck.
- [ ] Rollback ist dokumentiert: Aufrufer per Konfiguration wieder direkt auf `llama-3090` stellen.

## Edge Cases
- **Gateway fällt aus / startet neu:** Kein automatischer Umweg direkt zu `llama-3090`. Aufrufer erhalten einen Fehler und nutzen ihre bestehenden Fehlerpfade (Chat: übliche „LLM nicht erreichbar“-Meldung; n8n/Extractor wie bei einem llama-Ausfall heute). Wartende Anfragen gehen verloren und werden nicht nachgeholt.
- **`llama-3090` nicht erreichbar oder antwortet mit Fehler:** Fehler wird an den jeweiligen Aufrufer durchgereicht, der Slot wird freigegeben, die nächste Anfrage kommt dran (keine hängende Schlange).
- **Laufende Hintergrund-Anfrage dauert sehr lange (bis zum Timeout des Aufrufers):** Interaktive Anfragen warten so lange (bewusst akzeptiert, Option A). Die Kennzahlen machen das sichtbar; ein Abbruch laufender Hintergrund-Anfragen ist ein mögliches Folge-Feature.
- **Mehrere Personen chatten gleichzeitig:** Gleichberechtigt in Eingangsreihenfolge; die zweite Anfrage wartet, bis die erste fertig ist (inkl. aller Tool-Loop-Runden, die jeweils als einzelne Anfragen eingereiht werden).
- **Dauerhafte Chat-Last:** Hintergrund-Anfragen kommen erst dran, wenn keine interaktive Anfrage wartet. Bei zwei Nutzern ist dauerhaftes Verhungern der Hintergrund-Arbeit praktisch ausgeschlossen; kein eigener Schutzmechanismus im MVP, Wartezeiten sind über die Kennzahlen sichtbar.
- **Hintergrund-Anfrage wartet in der Schlange länger als ihr eigenes Timeout:** Der Aufrufer bricht ab (bestehendes Fehlerverhalten, z.B. Extractor-Timeout 300 s); die Anfrage wird danach nicht mehr weitergeleitet.
- **Aufrufer ohne bekannte Zuordnung (neuer Dienst, falscher Schlüssel-Typ):** läuft als Hintergrund, nicht interaktiv.

## Nicht im Scope
- Modellwechsel-Steuerung (finden nur nachts statt).
- Abbruch laufender Hintergrund-Anfragen zugunsten interaktiver (mögliches Folge-Feature nach Auswertung der Kennzahlen).
- Mehr als zwei Stufen (z.B. Voice vor WebApp).
- UI-Anzeige der Warteschlange (Dashboard/Settings) — ggf. eigenes Folge-Feature.
- Persistente Warteschlange / „abschicken und vergessen“.

## Technical Requirements (optional)
- Performance: Zusätzliche Latenz durch das Gateway bei leerer Schlange vernachlässigbar (Ziel < 50 ms bis zum Weiterleiten).
- Security: Bearer-Token wie bei `llama-3090`; nur interne Netze + VPN.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

### Ausgangslage (Ist-Zustand)
`llama-3090` hängt heute in drei Docker-Netzen (frontend, backend, automation) und wird von allen Aufrufern direkt angesprochen – Chat-Dienst, n8n, Bild-Extraktor, OpenWebUI und (über nginx) der externe Zugang `llama3090.happy-mining.de`. Alle benutzen denselben Zugangsschlüssel. llama.cpp arbeitet streng in Eingangsreihenfolge ab.

### Art des Features
Reines Backend/Infrastruktur: **ein neuer Container, keine UI, keine Datenbank, keine n8n-Workflows.** Die Aufrufer ändern nur ihre Endpunkt-Adresse (und bekommen einen eigenen Schlüssel).

### A) Aufbau (Komponenten)

```
Aufrufer                                   Gateway (neu)                         GPU
+-- alice-chat-stream  (Schlüssel A) -+
+-- OpenWebUI          (Schlüssel B) -+--> alice-llm-gateway ------------------> llama-3090
+-- externer Zugang via nginx (Schl. C)+    +-- Schlüssel prüfen + Stufe ermitteln   (nur noch vom
+-- n8n (alle Workflows) (Schlüssel D) -+   +-- Warteschlange „Interaktiv"            Gateway erreichbar,
+-- dms-extractor-image  (Schlüssel E) -+   +-- Warteschlange „Hintergrund"          genau 1 Anfrage
                                            +-- Slot-Wächter (max. 1 aktive Anfrage)  gleichzeitig)
                                            +-- Durchreichen der Antwort (Streaming)
                                            +-- Logs + Prometheus-Kennzahlen
```

### B) Funktionsweise in Alltagssprache
1. Eine Anfrage trifft ein. Das Gateway prüft den Schlüssel; falsch/fehlend → sofort abgelehnt.
2. Aus dem Schlüssel ergibt sich die Stufe (Interaktiv oder Hintergrund). Der Aufrufer kann sie nicht beeinflussen – es gibt kein „Priorität"-Feld in der Anfrage, das ausgewertet würde.
3. Die Anfrage stellt sich in die Warteschlange ihrer Stufe (Eingangsreihenfolge).
4. Der Slot-Wächter gibt den GPU-Slot immer an die **älteste interaktive** Anfrage, nur wenn keine wartet an die **älteste Hintergrund**-Anfrage.
5. Die Anfrage wird an `llama-3090` weitergeleitet; die Antwort (inkl. Token-Stream, Thinking, Tool-Calls) wird 1:1 an den Aufrufer durchgereicht.
6. Ist die Antwort komplett (oder fehlgeschlagen/abgebrochen), wird der Slot freigegeben und die nächste Anfrage kommt dran.

Jede Tool-Loop-Runde des Chat-Agenten ist eine eigene Anfrage und reiht sich neu ein (wie in der Spec festgelegt).

### C) Datenmodell (nur im Arbeitsspeicher, nichts persistent)
- **Schlüsselzuordnung** (Konfiguration): je Aufrufer ein eigener Schlüssel mit Name und Stufe. Alle Schlüssel, die nicht ausdrücklich als „Interaktiv" eingetragen sind, laufen als Hintergrund.
- **Wartende Anfrage** (flüchtig): Aufrufername, Stufe, Eingangszeitpunkt. Geht bei Neustart verloren (bewusst, siehe Edge Cases).
- **Kennzahlen/Logs**: Zähler und Wartezeiten in Prometheus; pro Anfrage eine strukturierte Log-Zeile (Aufrufer, Stufe, Wartezeit, Laufzeit, Ergebnis).

### D) Tech-Entscheidungen (mit Begründung)
| Entscheidung | Warum |
| --- | --- |
| **Eigener kleiner Python-Dienst** (wie `alice-lists`, `alice-speech-gateway`) | Gleicher Stack, gleiche Betriebsweise (Compose, Healthcheck, Tests). Eine Prioritäts-Warteschlange mit „höchstens 1 aktiv" ist mit nginx/Standard-Proxys nicht abbildbar – nginx kann nur Eingangsreihenfolge. |
| **Eigener Schlüssel je Aufrufer** statt Kopf-Feld „Priorität" | Erfüllt „Aufrufer kann Stufe nicht selbst wählen": Identität = Schlüssel, vom Gateway geprüft. Keine Code-Änderung bei den Aufrufern nötig; ein neuer Dienst ohne Eintrag läuft automatisch als Hintergrund. |
| **Nur wenige Pfade durchgelassen** (Chat-, Modell-, Health-Endpunkte der OpenAI-API) | Verkleinert die Angriffsfläche; das Gateway ist kein offener Proxy auf alles, was llama.cpp anbietet. Genauen Pfad-Umfang legt `/backend` anhand der tatsächlichen Aufrufer fest. |
| **Durchreichen als Stream ohne Zwischenpuffer** | Token-Streaming, Thinking-Tokens und Tool-Calls bleiben unverändert und ohne spürbare Zusatzlatenz (Ziel < 50 ms). |
| **Slot bleibt belegt bis Antwort-Ende; Abbruch des Aufrufers gibt ihn sofort frei** | Garantiert „höchstens 1 aktive Anfrage"; wartende Anfragen abgebrochener Aufrufer werden verworfen und nie mehr weitergeleitet. Der Abbruch wird auch an `llama-3090` weitergegeben, damit die GPU nicht umsonst weiterrechnet. |
| **`llama-3090` wird in ein eigenes, abgeschottetes Docker-Netz verlegt**, in dem nur das Gateway hängt | Technische Durchsetzung von „niemand umgeht das Gateway" – nicht nur Absprache. Heute hängt es in drei Netzen. |
| **Den echten `llama-3090`-Schlüssel kennt nur das Gateway** | Die Aufrufer bekommen eigene Gateway-Schlüssel; der Schlüssel zur GPU liegt nicht mehr verteilt in fünf `.env`-Dateien. |
| **Prometheus-Anbindung wie beim `chatstream`-Job** | Vorhandenes Muster, ein zusätzlicher Scrape-Job; keine neue Infrastruktur. |
| **Keine Persistenz / kein Redis** | Warteschlange ist bewusst flüchtig (Nicht-Scope: „abschicken und vergessen"). Hält das Gateway einfach und ohne Abhängigkeiten. |
| **Genau eine Gateway-Instanz** | Mehrere Instanzen würden den „1 Slot"-Wächter aushebeln. |

### E) Workflow Architecture
- **Trigger:** HTTP-Anfrage eines Aufrufers (OpenAI-kompatible API, identisch zu `llama-3090`).
- **Verarbeitung:** Schlüssel prüfen → Stufe bestimmen → einreihen → auf Slot warten → weiterleiten → Antwort durchreichen → Slot freigeben → loggen/zählen.
- **Ein-/Ausgang:** unverändert durchgereichter Anfrage-/Antwort-Inhalt; zusätzlich nur Log und Metriken.
- **Integrationen:** `llama-3090` (Ziel), Prometheus (Scrape), nginx (externer Zugang + VPN).
- **Fehlerbehandlung:**
  - Falscher/fehlender Schlüssel → Ablehnung (kein Weiterleiten).
  - `llama-3090` nicht erreichbar / Fehler → Fehler an Aufrufer, Slot frei, nächste Anfrage kommt dran.
  - Aufrufer bricht ab (wartend oder laufend) → Anfrage entfällt bzw. wird abgebrochen, Slot frei.
  - Gateway-Neustart → Aufrufer sehen Fehler und nutzen ihre bestehenden Fehlerpfade; kein Direktumweg zur GPU.

### F) Betroffene bestehende Teile
| Teil | Änderung |
| --- | --- |
| `docker/compose/ai/llama-3090` | Netze: nur noch das neue abgeschottete Netz |
| `alice-chat-stream`, `dms-extractor-image`, `n8n`, `openwebui` | Nur `.env`/Compose: Endpunkt-Adresse + eigener Schlüssel |
| nginx-Vhost `llama-3090.conf` | Ziel von `llama-3090` auf Gateway umstellen |
| `infra/prometheus/prometheus.yml` | Neuer Scrape-Job `llm-gateway` |
| `docker/compose/scripts/Makefile` | Neuen Stack ergänzen |
| README / Betriebsdoku | Rollback-Anleitung (Aufrufer wieder direkt auf `llama-3090`, Netz zurück) |

### G) Dependencies (Pakete)
- Python-Web-Framework + ASGI-Server und HTTP-Client mit Streaming (wie in den vorhandenen Python-Diensten)
- Prometheus-Client-Bibliothek (Kennzahlen)

### H) Hinweise für die Umsetzung / Risiken
- **Reihenfolge beim Ausrollen:** zuerst Gateway starten und testen, dann Aufrufer nacheinander umstellen, zuletzt `llama-3090` aus den alten Netzen nehmen (erst dann ist die Umgehung technisch ausgeschlossen).
- **Zeitüberschreitungen:** Das Gateway darf Wartezeit in der Schlange nicht eigenmächtig begrenzen; die Timeouts der Aufrufer (z.B. Extractor 300 s, Chat 120 s) bleiben maßgeblich. Chat-Timeout 120 s ist ggf. bei langer laufender Hintergrund-Anfrage knapp – über die Kennzahlen beobachten.
- **Modellwechsel-Anfragen** (z.B. `alice-llm-model-warmup`) laufen als normale Hintergrund-Anfrage durch; keine Sonderbehandlung.
- **Offener Punkt für `/backend`:** Genaue Liste der Pfade, die tatsächlich genutzt werden (n8n-Shim, Extractor, OpenWebUI), vor Implementierung per Code-Check bestätigen.

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
