# PROJ-99: Umstellung Ollama → llama.cpp (ollama-3090)

## Status: Planned
**Created:** 2026-09-01
**Last Updated:** 2026-09-01

## Kontext & Motivation

Der Chat-/Agenten-Pfad und die DMS-Pipeline laufen heute gegen die Ollama-Instanz
`ollama-3090` (RTX 3090). Für den Agenten-Bereich (mehrstufige Tool-Loops mit
`alice-chat-stream`) ist die Token-Generierungsrate der begrenzende Faktor für die
gefühlte Antwortgeschwindigkeit: jede Tool-Runde erzeugt eine komplette
LLM-Antwort, und mehrere Runden summieren sich.

`llama.cpp` (`llama-server`) erreicht auf identischer Hardware und bei gleicher
Quantisierung eine höhere Token-Generierungsrate als Ollama. Diese Umstellung
tauscht das Inferenz-Backend hinter `ollama-3090` gegen `llama.cpp` aus, bei
voller Verhaltensparität nach außen.

### Scope-Abgrenzung

**In Scope — alle Konsumenten von `ollama-3090`:**
- `alice-chat-stream` — Chat/Agent, Modell `qwen3.5:27b-q4_K_M` (`OLLAMA_MODEL`),
  Streaming über `/api/chat`, Reasoning-Stream (PROJ-37), Tool-Calling-Loop;
  außerdem ein Nicht-Streaming-Call in `memory.py` über `/api/generate`
- n8n-DMS-Workflows — `OLLAMA_MODEL_DMS` = `mistral-small3.2:24b`, über
  `/api/generate` und `/api/tags`:
  `alice-dms-classify-document`, `alice-dms-classification-backfill`,
  `alice-dms-language-check`, `alice-dms-language-backfill`,
  `alice-dms-processor`, `alice-mail-attachment-processor`,
  `alice-mail-attachment-backfill`, `alice-mail-sync`,
  `alice-dms-image-description-backfill`
- `dms-extractor-image` — Vision/Bildbeschreibung, `OLLAMA_VISION_MODEL` =
  `qwen3.5:27b-q4_K_M`, Bild-Input über `/api/generate`
- `openwebui` — `OLLAMA_BASE_URL`
- **nginx-Vhost** `conf.d/ollama-3090.conf` — externer Zugriff
  `https://ollama3090.happy-mining.de` → `http://ollama-3090:11434` (genutzt von
  externen Skripten / Jupyter-Notebooks außerhalb des Docker-Netzes; interne
  Konsumenten gehen direkt über das Docker-Netz, nicht über diesen Vhost)

**Explizit NICHT in Scope:**
- `ollama-titan` (TITAN X) — bleibt **unverändert** als Ollama-Instanz für
  Jupyter-Testprogramme und GPU-Experimente. Kein Konsument im Alice-Stack,
  keine Migration.
- `wyoming-whisper` / `alice-speech-gateway` (faster-whisper, CTranslate2) —
  vom LLM-Backend unabhängig, kein Bezug zu dieser Umstellung.
- Weaviate-Embedding-Container (`t2v-transformers`, `multi2vec-clip`) — eigene
  Runtime, kein Ollama.
- Keine Änderung an Modell-Auswahl/Prompts/Agenten-Logik — nur Backend-Tausch.

## Dependencies

- Requires: PROJ-30 (Streaming Chat Backend) — der `alice-chat-stream`-Streaming-Pfad
- Requires: PROJ-37 (Streaming Verbosity / Thinking-Stream) — muss erhalten bleiben
- Betrifft (ohne Blockade): die gesamte DMS-Pipeline (PROJ-19, PROJ-56, PROJ-78,
  PROJ-79 u.a.) sowie `alice-mail-sync` (PROJ-46) — alle laufen als Konsumenten
  weiter und müssen nach der Umstellung unverändert funktionieren

## User Stories

- Als **Andreas** möchte ich, dass Alice im Chat spürbar schneller antwortet —
  besonders bei Anfragen, die mehrere Tool-Aufrufe auslösen —, damit sich der
  Assistent flüssiger anfühlt.
- Als **Andreas** möchte ich, dass der Reasoning-/Denk-Stream (die
  eingeblendeten „thinking"-Abschnitte) nach der Umstellung genauso funktioniert
  wie vorher, damit ich nachvollziehen kann, was Alice tut.
- Als **Andreas** möchte ich, dass die DMS-Pipeline (Dokumentenklassifizierung,
  deutsche Zusammenfassungen, Sprachprüfung, Bildbeschreibung) nach der
  Umstellung unverändert korrekt arbeitet, damit meine Wissensbasis nicht
  beschädigt wird.
- Als **Andreas** möchte ich, dass Open WebUI weiterhin gegen dasselbe Backend
  läuft, damit ich dort weiter direkt mit den Modellen testen kann.
- Als **Andreas** möchte ich einen dokumentierten Rückweg zu `ollama-3090`,
  damit ich bei Problemen innerhalb von Minuten zurückschalten kann, ohne Daten
  zu verlieren.
- Als **Andreas** möchte ich einen Vorher/Nachher-Vergleich der
  Token-Generierungsrate, damit ich belegen kann, dass sich die Umstellung
  gelohnt hat.
- Als **Andreas** möchte ich, dass meine externen Testskripte / Jupyter-Notebooks,
  die bisher `ollama3090.happy-mining.de` ansprechen, nicht abrupt brechen,
  sondern übergangsweise per Redirect auf das neue Backend geleitet werden.

## Acceptance Criteria

### Backend-Bereitstellung

- [ ] `llama.cpp` läuft als Dienst auf der RTX 3090 (GPU `c15bd736…`) und ersetzt
      `ollama-3090` als Inferenz-Endpoint für alle oben gelisteten Konsumenten.
- [ ] Der Dienst bedient **alle drei bisherigen Modelle** dynamisch über **einen**
      Endpoint: das Chat-/Vision-Modell (`qwen3.5:27b-q4_K_M`-Äquivalent als GGUF)
      und das DMS-Text-Modell (`mistral-small3.2:24b`-Äquivalent als GGUF). Ein
      Request wählt das Modell per Namensfeld; der Dienst lädt es bei Bedarf und
      entlädt nicht mehr benötigte Modelle selbstständig (Modell-Registry /
      -Router-Betrieb, kein fest vorgegebenes Einzelmodell).
- [ ] Die eingesetzten GGUF-Modelle entsprechen in Quantisierung und Modellstand
      den heutigen Ollama-Modellen (gleiche Quants).
- [ ] `ollama-titan` bleibt unverändert lauffähig und von dieser Umstellung
      unberührt.
- [ ] Neue nginx-Config `conf.d/llama-3090.conf` mit
      `server_name llama3090.happy-mining.de` proxyt auf den llama.cpp-Container
      (WebSocket-Header, großzügige `proxy_read_timeout`, ausreichende
      `client_max_body_size` — analog zur bisherigen `ollama-3090.conf`).
- [ ] Der alte Vhost `ollama3090.happy-mining.de` bleibt als Server-Block
      bestehen und liefert einen dauerhaften **301-Redirect** auf
      `llama3090.happy-mining.de` (HTTP und HTTPS).
- [ ] Externe Skripte / Jupyter-Notebooks, die bisher
      `ollama3090.happy-mining.de` nutzen, funktionieren über den Redirect
      übergangsweise weiter; der Ziel-Hostname wird dokumentiert, damit sie
      nachgezogen werden können.

### Verhaltensparität `alice-chat-stream` (Chat/Agent)

- [ ] Eine einfache Chat-Anfrage liefert eine gestreamte Antwort; die
      SSE-Event-Typen (`token`, `thinking_start`, `thinking`, Tool-Status-Events,
      Abschluss) entsprechen dem heutigen Verhalten.
- [ ] Der Reasoning-/Thinking-Stream (PROJ-37) funktioniert: bei aktiviertem
      Think-Modus werden Denk-Tokens als separate `thinking`-Events vor dem
      eigentlichen Antworttext ausgeliefert und **nicht** in den Antworttext oder
      die Token-Zählung übernommen; bei deaktiviertem Think-Modus erscheinen
      keine `thinking`-Events.
- [ ] Der Agenten-Tool-Loop funktioniert: das Modell kann Tool-Aufrufe auslösen,
      die Ergebnisse werden angehängt, das Modell wird erneut aufgerufen, und der
      Loop endet mit einer finalen Antwort — bis zur bestehenden Runden-Obergrenze.
- [ ] Mehrere aufeinanderfolgende Tool-Runden in einer Anfrage funktionieren
      end-to-end (kein Abbruch, keine doppelten/verlorenen Tool-Ergebnisse).
- [ ] Prompt- und Completion-Token-Zählung wird weiterhin erfasst und in den
      bestehenden Metriken/Speicherpfaden abgelegt.
- [ ] Der Nicht-Streaming-Aufruf in `memory.py` (Profil-/Zusammenfassungs-Logik)
      liefert weiterhin ein verwertbares Ergebnis.
- [ ] Fehlerfälle (Backend nicht erreichbar, Timeout, HTTP-Fehler) führen zu den
      gleichen nutzersichtbaren Fehler-Events wie heute (deutschsprachige
      Fehlermeldung, kein Hängen).

### Verhaltensparität DMS-Pipeline (n8n)

- [ ] `alice-dms-classify-document` klassifiziert ein Testdokument mit demselben
      Ergebnis wie unter Ollama (gleiches Modell, gleicher Prompt).
- [ ] `alice-dms-language-check` erkennt nicht-deutsche Zusammenfassungen
      unverändert.
- [ ] `alice-dms-processor` verarbeitet ein Dokument end-to-end ohne Fehler; das
      bestehende Timeout-Verhalten (`OLLAMA_TIMEOUT_MS`) bleibt wirksam.
- [ ] `alice-mail-sync` und `alice-mail-attachment-processor` verarbeiten eine
      Testmail bzw. einen Testanhang unverändert.
- [ ] Die Backfill-Workflows (`…-classification-backfill`, `…-language-backfill`,
      `…-image-description-backfill`, `…-mail-attachment-backfill`) laufen im
      Dry-Run ohne Fehler durch.
- [ ] Ein etwaiger Health-/Verfügbarkeits-Check der Workflows (heute `/api/tags`)
      hat ein funktionierendes Äquivalent gegen das neue Backend.

### Verhaltensparität Vision & Open WebUI

- [ ] `dms-extractor-image` erzeugt für ein Testbild eine deutschsprachige
      Bildbeschreibung vergleichbarer Qualität wie unter Ollama (multimodaler
      Pfad / mmproj funktioniert).
- [ ] `alice-dms-image-description-backfill` läuft im Dry-Run ohne Fehler durch.
- [ ] Open WebUI kann sich mit dem neuen Backend verbinden, listet die
      verfügbaren Modelle und führt einen Test-Chat erfolgreich durch.

### Performance (Kern-Ziel)

- [ ] Es gibt einen dokumentierten Vorher/Nachher-Benchmark der
      Token-Generierungsrate (tok/s) für mindestens das Chat-Modell
      (`qwen3.5:27b`) und das DMS-Modell (`mistral-small3.2:24b`), gemessen auf
      der RTX 3090 bei gleicher Quantisierung und vergleichbarem Kontext.
- [ ] Die Token-Generierungsrate des Chat-Modells liegt nach der Umstellung
      **mindestens 20 % über** dem Ollama-Ausgangswert.
- [ ] Kein Konsument zeigt eine funktionale Regression (siehe Paritäts-Kriterien
      oben).

### Cutover & Rollback

- [ ] Cutover als harter Schnitt: `ollama-3090` stoppen, `llama.cpp` starten,
      alle Konsumenten-Endpoints umstellen, Paritäts-Checks durchführen.
- [ ] `ollama-3090`-Container-Definition und Modell-Volumes bleiben während einer
      dokumentierten Karenzzeit erhalten (nicht gelöscht).
- [ ] Es gibt eine dokumentierte Rollback-Prozedur (Konsumenten-Endpoints
      zurückstellen, `ollama-3090` wieder starten), die den Ausgangszustand in
      wenigen Minuten wiederherstellt.
- [ ] `README.md` und die betroffenen `.env.example`-Dateien sind aktualisiert
      (Endpoint, Modellnamen, ggf. neue Variablen); keine hartkodierten Secrets.
- [ ] Die nginx-Configs werden über den Standard-Weg auf den Server synchronisiert
      (`scripts/sync-compose.sh`) und nginx neu geladen; der alte
      `ollama-3090.conf`-Server-Block (jetzt Redirect) und die neue
      `llama-3090.conf` sind beide aktiv.
- [ ] Rollback-Prozedur schließt die nginx-Ebene ein: `ollama-3090.conf` wieder
      als Proxy (statt Redirect) herstellen, `llama-3090.conf` deaktivieren.
- [ ] n8n-Workflows werden über den Standard-Deploy-Weg synchronisiert
      (`Deploy n8n-workflow {name}`), nicht direkt bearbeitet.

## Edge Cases

- **Dynamischer Modell-Wechsel unter Last:** Fordert die DMS-Pipeline ein anderes
  Modell an, während der Chat läuft, entlädt/lädt `llama.cpp` Modelle, was
  Sekunden bis ~1 min dauern kann. → Wird **nur dokumentiert** (bekannte
  Ladezeiten, gelegentliche Kontention auf der geteilten 3090); **kein**
  Akzeptanzkriterium, keine Priorisierungsgarantie. Die bestehenden
  Batch-Timeouts müssen lang genug sein, um eine Modell-Ladephase zu überstehen.
- **Abweichendes Tool-Call-Format:** llama.cpp liefert Tool-Aufrufe u. U. in
  anderer Struktur als Ollamas `message.tool_calls`. → Der Loop muss beide
  Argument-Formen (JSON-String und Objekt) weiterhin robust parsen; ein nicht
  parsebares Argument führt wie heute zu leeren Argumenten, nicht zum Absturz.
- **Reasoning-Feld heißt anders:** Ollamas `message.thinking` hat unter
  llama.cpp/OpenAI-Format ggf. einen anderen Namen (`reasoning_content` o. ä.).
  → Die Extraktion der Denk-Tokens muss angepasst werden, ohne dass Denk-Text in
  den Antworttext leckt.
- **Streaming-Zeilenformat:** llama.cpp streamt im SSE-/`data:`-Format, Ollama in
  NDJSON. → Der Parser im Streaming-Pfad muss auf das neue Format umgestellt
  werden; nicht-interpretierbare Zeilen werden wie heute geloggt und übersprungen,
  nicht als Fehler behandelt.
- **`done`-/Usage-Signal:** Ollama markiert das Ende per `done` + `eval_count` /
  `prompt_eval_count`. → Es braucht ein Äquivalent für Abschluss-Erkennung und
  Token-Zählung; fehlt es, dürfen die Zähler höchstens 0 sein, nicht abstürzen.
- **VRAM reicht nicht für ein 27b-Modell + Kontext:** Wenn ein großer Quant plus
  Kontext die 24 GB der 3090 sprengt. → Muss beim Cutover auffallen (Modell lädt
  nicht); Fallback ist die dokumentierte Rollback-Prozedur.
- **Vision-Request ohne mmproj geladen:** Bild-Anfrage an ein Modell, dessen
  Projektor nicht mitgeladen wurde. → `dms-extractor-image` muss einen klaren
  Fehler bekommen (kein stiller Text-only-Fallback, der eine sinnlose
  Beschreibung erzeugt).
- **`ollama-titan` versehentlich mit umgestellt:** Da beide Instanzen im selben
  Compose-File stehen. → Die Umstellung darf `ollama-titan` nicht anfassen; nach
  dem Cutover muss `ollama-titan` weiterhin über seinen unveränderten Endpoint
  erreichbar sein.
- **Open WebUI cached alte Modell-Liste:** Nach dem Backend-Tausch. → Ein
  Reload / Neustart von Open WebUI muss die aktuelle Modell-Liste zeigen.
- **Externer Client folgt keinem Redirect:** Ein Skript, das
  `ollama3090.happy-mining.de` mit deaktiviertem Redirect-Following aufruft,
  erhält nach dem Cutover einen 301 statt einer API-Antwort. → Ist akzeptiert
  (dokumentierter Übergang); der neue Hostname `llama3090.happy-mining.de` ist im
  README vermerkt, damit solche Clients umgestellt werden können.
- **llama.cpp spricht die native Ollama-API nicht:** Externe Notebooks, die
  gezielt Ollama-Endpunkte (`/api/generate`, `/api/tags`) gegen den Vhost
  aufrufen, statt des OpenAI-Formats. → llama.cpp bietet einen
  Ollama-kompatiblen Pfad nur eingeschränkt; solche Clients müssen auf
  `/v1/...` umgestellt werden. In der Spec dokumentiert, keine
  Kompatibilitäts-Shim-Pflicht.

## Technical Requirements

- **Performance:** Token-Generierungsrate Chat-Modell ≥ +20 % ggü. Ollama-Baseline
  (RTX 3090, gleiche Quantisierung).
- **Kompatibilität:** Ein einziger Inferenz-Endpoint bedient Chat-, DMS-Text- und
  Vision-Modell mit dynamischem Laden/Entladen.
- **Isolation:** `ollama-titan` (TITAN X) bleibt unangetastet.
- **Sicherheit:** Nur über VPN erreichbar (wie bisher); keine hartkodierten
  Secrets; Endpoint bleibt im internen Docker-Netz.
- **Betrieb:** Health-Check für den neuen Dienst; Container `restart: unless-stopped`;
  Modell-Verzeichnis auf schnellem Storage (analog `/srv/hot/models`).
- **Reversibilität:** `ollama-3090` bleibt für eine Karenzzeit rückholbar
  (Container-Definition + Modell-Volumes erhalten).
- **Logging:** n8n-Workflows nutzen weiterhin `winston`, kein `console.log`.

## Success Metrics

| Metrik | Zielwert |
| --- | --- |
| Token-Generierungsrate Chat-Modell (`qwen3.5:27b`), llama.cpp vs. Ollama | ≥ +20 % tok/s |
| Token-Generierungsrate DMS-Modell (`mistral-small3.2:24b`), Vorher/Nachher dokumentiert | gemessen, kein Rückschritt |
| Funktionale Regressionen bei Konsumenten (Chat, DMS, Vision, Open WebUI) | 0 |
| Reasoning-/Thinking-Stream (PROJ-37) funktionsgleich | ja |
| Agenten-Tool-Loop (mehrere Runden) funktionsgleich | ja |
| `ollama-titan` unverändert lauffähig | ja |
| nginx: `llama3090.happy-mining.de` aktiv, `ollama3090…` → 301-Redirect | ja |
| Rollback-Prozedur dokumentiert und erprobt (inkl. nginx-Ebene) | ja |

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
