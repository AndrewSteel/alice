# PROJ-99: Umstellung Ollama → llama.cpp (ollama-3090)

## Status: Deployed
**Created:** 2026-09-01
**Last Updated:** 2026-09-02

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
- [ ] Der Router entlädt ein geladenes Modell **nicht** im Leerlauf (Ersatz für
      Ollamas `OLLAMA_KEEP_ALIVE=-1`); ein Modell weicht nur, wenn das andere
      angefragt wird. Ein Schedule-Workflow (`alice-llm-model-warmup`, 07:00
      Europe/Berlin) lädt das Chat-Modell nach dem nächtlichen DMS-Lauf vor, so
      dass die erste Chat-Anfrage am Tag keine Kaltstart-Verzögerung hat.
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
- **VRAM reicht nicht für qwen (ctx 16384 + mmproj) neben Weaviate:** Die 3090
  ist mit `weaviate-transformers` + `multi2vec-clip` geteilt. qwen-Q4 (~18,6 GB)
  + mmproj (~1,1 GB) + KV bei ctx 16384 ≈ ~21 GB. → `weaviate-transformers` gibt
  VRAM zurück (`PYTORCH_CUDA_ALLOC_CONF`-Cap; Fallback CPU). Lädt qwen dann
  trotzdem nicht: `ctx-size` gestuft senken (16384→12288→8192) — 8192 ist die
  Untergrenze, darunter leidet der Agenten-Tool-Loop. Letzter Fallback:
  Rollback. `mistral` (~16 GB) ist unkritisch.
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
| Token-Generierungsrate Chat-Modell (Qwen3-VL-30B-A3B, ID `qwen3-vl-30b`), llama.cpp vs. Ollama | ≥ +20 % tok/s |
| Token-Generierungsrate DMS-Modell (Mistral-Small-3.2-24B, ID `mistral-small-3.2-24b`), Vorher/Nachher dokumentiert | gemessen, kein Rückschritt |
| Funktionale Regressionen bei Konsumenten (Chat, DMS, Vision, Open WebUI) | 0 |
| Reasoning-/Thinking-Stream (PROJ-37) funktionsgleich | ja |
| Agenten-Tool-Loop (mehrere Runden) funktionsgleich | ja |
| `ollama-titan` unverändert lauffähig | ja |
| nginx: `llama3090.happy-mining.de` aktiv, `ollama3090…` → 301-Redirect | ja |
| Rollback-Prozedur dokumentiert und erprobt (inkl. nginx-Ebene) | ja |

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

_Erstellt am 2026-09-01. Zielgruppe: Produkt-/Betriebssicht — kein Code, nur
Architektur-Entscheidungen._

### 1. Grundidee in einem Satz

`ollama-3090` (Ollama auf der RTX 3090) wird durch **einen einzigen
llama.cpp-Server** ersetzt, der auf ein **Modell-Verzeichnis** zeigt und die
zwei benötigten Modelle (Chat/Vision + DMS-Text) **bei Bedarf selbst lädt und
wieder entlädt**. Nach außen verhält sich alles gleich; intern ist die
Token-Generierung schneller.

### 2. Ziel-Topologie (Übersicht)

```text
                         RTX 3090 (GPU c15bd736…)
                    ┌──────────────────────────────────┐
                    │   llama-3090  (neuer Container)   │
                    │   llama.cpp-Server, Modell-Ordner │
                    │   /v1/chat/completions, /v1/models│
                    │   lädt/entlädt Modelle dynamisch  │
                    └──────────────────────────────────┘
                          ▲            ▲            ▲
          ┌───────────────┘            │            └───────────────┐
          │                            │                            │
   alice-chat-stream          9 n8n-DMS-Workflows          dms-extractor-image
   (Chat/Agent, Stream,        (Klassifizierung,           (Vision / Bild-
    Tool-Loop, Thinking)        Sprachprüfung, …)            beschreibung)
          │                            │                            │
          └──────────── openwebui ─────┴──── nginx-Vhost ───────────┘
                    (Direkt-Test-UI)      llama3090.happy-mining.de
                                          (extern, über VPN)

   ollama-titan  (TITAN X, Ollama)  ──►  UNVERÄNDERT, nur für Jupyter
```

**Was neu ist:** ein Container `llama-3090`.
**Was wegfällt:** der Container `ollama-3090` (Definition + Modell-Volume bleiben
für die Karenzzeit erhalten, wird nur gestoppt).
**Was unberührt bleibt:** `ollama-titan`.

### 3. Der neue Dienst: llama.cpp mit dynamischer Modell-Registry

| Eigenschaft | Entscheidung | Warum (PM-Sicht) |
| --- | --- | --- |
| **Ein Endpoint, mehrere Modelle** | llama.cpp-Server wird **ohne festes Modell** gestartet und bekommt stattdessen einen **Modell-Ordner** genannt. Jeder Request nennt im `model`-Feld den gewünschten Modellnamen; der Server lädt ihn in die GPU und entlädt nicht mehr gebrauchte Modelle nach einer Leerlaufzeit selbst. | Erfüllt die Spec-Vorgabe „ein Endpoint, dynamischer Router" **ohne** zusätzlichen Router-Container oder Eigenentwicklung. Weniger bewegliche Teile = weniger Betriebsrisiko. |
| **API-Format** | Der Server spricht das **OpenAI-kompatible Format** (`/v1/chat/completions`, `/v1/models`). Das ist der Pfad, den alle Konsumenten künftig nutzen. | Ein einheitliches, dokumentiertes Format statt Ollamas Eigen-API. Open WebUI und viele Tools sprechen es nativ. |
| **Modelle** | Zwei Modelle, gleiche Quant-Stufe wie heute. Chat/Vision: **Qwen3-VL-30B-A3B-Instruct** (MoE, ~30 B total / ~3 B aktiv, `arch qwen35`, Ollama meldete `27.8B`), Q4_K_M-Sprachgewichte (~18,6 GB) **+** F16-Vision-Projektor `mmproj` (~1,1 GB) — Repo `Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF`. DMS-Text: **Mistral-Small-3.2-24B-Instruct-2506** (dense 24 B), Q4_K_M (~14 GB), **kein** mmproj. Model-IDs (Preset-Sektionsnamen = `$env.OLLAMA_MODEL*`): **`qwen3-vl-30b`** und **`mistral-small-3.2-24b`** — **`:`-frei** (llama.cpp schreibt `:` im Sektionsnamen um). GGUF-Pfade in `presets.ini` **absolut** (`/models/…`). | Verhaltensparität: identischer Modellstand + Quant → gleiche Antwortqualität, nur schneller. Prompts/Modellwahl-Logik unverändert; nur die Modell-**Namen** in `.env` + 9 Workflow-Fallbacks von den alten Ollama-Tags auf die neuen `:`-freien IDs gezogen. |
| **VRAM-Strategie** | **Immer nur ein Modell** aktiv (`--models-max 1`). **Kein Idle-Unload** (ersetzt Ollamas `OLLAMA_KEEP_ALIVE=-1`). Nächtlicher DMS-Lauf (02:00 UTC) lädt mistral; `alice-llm-model-warmup` (05:00 UTC) schaltet vor Arbeitsbeginn zurück auf qwen. **`ctx-size = 16384`** (Agenten-Tool-Loop-Minimum), **`parallel = 1`** (1 KV-Slot statt 4), **`image-min-tokens = 1024`** (Qwen3-VL-Grounding). | **Gemessen 2026-09-02:** qwen (ctx 16384, mmproj, parallel 1) **~20,9 GB** + `weaviate-transformers` **~0,8 GB** (von ~3,3 GB via `PYTORCH_CUDA_ALLOC_CONF`-Cap) + `multi2vec-clip` **~1,4 GB** = **~23,1/24 GB, ~1,5 GB frei**. `parallel = 1` spart ~3–4 GB (Alice = 1 sequ. Chat-Stream/Nutzer). mistral statt qwen: ~16 GB, entspannt. **Beide LLMs zusammen passen nicht** → `--models-max 1`. Puffer dünn — bei OOM unter Last: `ctx-size` 16384→12288 oder `t2v-transformers` auf CPU. |
| **Warmup-Workflow** | `alice-llm-model-warmup` (n8n): Schedule `0 5 * * *` (UTC) → ein `POST /v1/chat/completions` an qwen mit `max_tokens: 1`. Lädt qwen (verdrängt mistral). `onError: continueRegularOutput` + Winston-Log; kein Retry, kein Blocker. `load-on-startup = true` in `presets.ini` wärmt qwen zusätzlich nach jedem Container-Neustart. | Erste Morgen-Chat-Antwort ohne Kaltstart-Verzögerung. Zeitpunkt liegt nach dem 02:00-DMS-Lauf und vor dem 06:00-Image-Description-Backfill — keine Cron-Kollision. |
| **Modell-Storage** | Modell-Ordner auf schnellem Storage, analog `/srv/hot/models` (eigener Unterordner für llama.cpp, getrennt von Ollamas Ordner). | Schnelles Nachladen beim Modell-Wechsel; keine Kollision mit den erhalten bleibenden Ollama-Modellen. |
| **Betrieb** | Eigener Container `llama-3090`, `restart: unless-stopped`, GPU fest auf die RTX 3090 gepinnt (dieselbe `device_ids`-Zuweisung wie `ollama-3090` heute), Healthcheck gegen die Modell-Liste (`/v1/models`). | Gleiche Betriebs-Garantien wie beim alten Dienst. |
| **Netzwerk & Sicherheit** | Container hängt in **denselben Docker-Netzen** wie `ollama-3090` heute (`frontend`, `app_int`) plus dem Netz von `dms-extractor-image` (`backend`), damit alle bisherigen Konsumenten ihn erreichen. Kein Port nach außen; extern nur über den nginx-Vhost hinter VPN. | Keine neue Angriffsfläche; „VPN-only" bleibt. |

### 4. Betroffene Konsumenten — was sich je Konsument ändert

Alle Änderungen sind **Konfiguration**, keine Logik. Modell-Auswahl, Prompts und
Agenten-Verhalten bleiben unverändert.

| Konsument | Heute | Nach der Umstellung |
| --- | --- | --- |
| **`alice-chat-stream`** (Chat/Agent) | Streaming über Ollamas `/api/chat` (NDJSON), Tool-Loop, Reasoning-Stream über `message.thinking`, Abschluss über `done` + `eval_count` | Streaming über `/v1/chat/completions` (SSE/`data:`-Format). Der Streaming-Parser, die Tool-Call-Auswertung, die Denk-Token-Extraktion und die Token-Zählung werden auf das OpenAI-Format umgestellt (Details: Edge-Case-Liste der Spec). **Verhalten nach außen — SSE-Event-Typen, Thinking vor Antwort, Tool-Runden — bleibt identisch.** |
| **`alice-chat-stream` / `memory.py`** | Ein Nicht-Streaming-Call über `/api/generate` (Titel-/Profil-Logik) | Nicht-Streaming-Call über `/v1/chat/completions` |
| **9 n8n-DMS-Workflows** | Code-Nodes rufen **hardcodiert** `http://ollama-3090:11434/api/generate`; Modellname aus `$env.OLLAMA_MODEL_DMS` | Code-Nodes rufen den neuen Endpoint über `/v1/chat/completions`; Hostname wird auf eine **Environment-Variable** gezogen (kein Hardcode mehr). Response-Auswertung wechselt vom Ollama-Feld `response` auf das OpenAI-Feld `choices[0].message.content`. Umsetzung im `/backend`-Schritt, Deploy über `Deploy n8n-workflow {name}`. |
| **`dms-extractor-image`** (Vision) | `/api/generate` mit `images: [base64]` | `/v1/chat/completions` mit Bild als Content-Part (OpenAI-Vision-Format); Endpoint/Modell aus den bestehenden `OLLAMA_*`-Variablen (Werte angepasst) |
| **`openwebui`** | `OLLAMA_BASE_URL=http://ollama-3090:11434` | Auf den OpenAI-kompatiblen Modus des neuen Endpoints umgestellt (`OPENAI_API_BASE_URL` auf `http://llama-3090:.../v1`, Ollama-Anbindung deaktiviert). Nach dem Wechsel einmal neu laden/neu starten, damit die Modell-Liste frisch gezogen wird. |
| **nginx-Vhost** | `ollama-3090.conf`: Proxy `ollama3090.happy-mining.de` → `ollama-3090:11434` | **Neu** `llama-3090.conf`: `llama3090.happy-mining.de` → `llama-3090:<port>` (WebSocket-Header, `proxy_read_timeout 3600s`, `client_max_body_size 50m` — 1:1 wie die alte Config). **Alt** `ollama-3090.conf` bleibt als Server-Block, liefert aber nur noch **301-Redirect** auf den neuen Hostnamen (HTTP + HTTPS). |

### 5. Namens- und Endpoint-Konvention

| | Alt | Neu |
| --- | --- | --- |
| Container / interner Hostname | `ollama-3090` | `llama-3090` |
| Interner Endpoint | `http://ollama-3090:11434` | `http://llama-3090:<port>` (OpenAI-Pfade unter `/v1`) |
| Externer Hostname (nginx) | `ollama3090.happy-mining.de` | `llama3090.happy-mining.de` (alt → 301) |
| Modell-Ordner | `/srv/hot/models/ollama` | eigener Unterordner unter `/srv/hot/models` für llama.cpp |

Neuer Name = sauberer Cutover und eindeutiger Rollback: „alte URL zeigt auf alten
Dienst, neue URL auf neuen Dienst".

### 6. Konfiguration / Environment (keine Secrets)

Neue bzw. geänderte Variablen (Werte in den jeweiligen `.env`, Beispiele in
`.env.example`):

- **`alice-chat-stream`**: `OLLAMA_URL` → neuer Endpoint; `OLLAMA_MODEL` →
  GGUF-Modellname des Chat-Modells. `OLLAMA_THINK`, `OLLAMA_TIMEOUT_SECONDS`
  bleiben.
- **n8n**: neue Variable für den DMS-Inferenz-Endpoint (ersetzt den Hardcode);
  `OLLAMA_MODEL_DMS` → GGUF-Modellname des DMS-Modells; `OLLAMA_TIMEOUT_MS`
  bleibt (muss ≥ Modell-Ladezeit sein).
- **`dms-extractor-image`**: `OLLAMA_URL` / `OLLAMA_VISION_MODEL` → neue Werte.
- **`openwebui`**: `OLLAMA_BASE_URL` entfällt, `OPENAI_API_BASE_URL` +
  `ENABLE_OPENAI_API=true` hinzu.
- **`README.md`**: `ollama-3090`-Zeile ersetzen, neuer Hostname + Modell-Ordner
  dokumentiert, Redirect-Hinweis für externe Skripte.

### 7. Cutover-Ablauf (harter Schnitt)

1. **Vorbereiten (ohne Live-Wirkung):** GGUF-Modelle in den Modell-Ordner legen;
   Compose-Datei für `llama-3090` anlegen; neue nginx-Config `llama-3090.conf`
   schreiben; alte `ollama-3090.conf` auf Redirect umbauen; Konsumenten-`.env`
   vorbereiten.
2. **VRAM für Weaviate zurückholen:** `t2v-transformers` mit dem
   `PYTORCH_CUDA_ALLOC_CONF`-Cap neu starten (`make recreate s=automations/weaviate
   svc=t2v-transformers` o.ä.), `nvidia-smi` prüfen — Ziel: `weaviate-transformers`
   von ~3,3 GB auf ~1–1,5 GB. Greift der Cap nicht ausreichend: `ENABLE_CUDA=0`
   plus `deploy.resources`-Block entfernen (CPU-Betrieb).
3. **Baseline messen:** Token/s Chat- und DMS-Modell **unter Ollama** festhalten;
   `nvidia-smi` notieren.
4. **Schnitt:** `ollama-3090` stoppen → `llama-3090` starten → warten bis
   `/v1/models` beide Modelle listet → **`nvidia-smi`: lädt qwen
   (`load-on-startup`, ctx 16384 + mmproj) neben den beiden Weaviate-Containern
   in die 24 GB?** Falls OOM: `ctx-size` gestuft senken (16384 → 12288 → 8192)
   **oder** `t2v-transformers` doch auf CPU. → alle Konsumenten mit neuer Config
   neu starten → n8n-Workflows deployen (10×) → nginx-Configs syncen
   (`sync-compose.sh`) und nginx neu laden.
5. **Paritäts-Checks:** die Prüfliste aus den Acceptance Criteria abarbeiten
   (Chat inkl. Thinking + mehrstufigem Tool-Loop mit einer Dokumentensuche, die
   viele Treffer liefert → prüft, dass ctx 16384 im Loop reicht; je ein
   DMS-Workflow live + ein Backfill im Dry-Run; Vision-Testbild; Open WebUI
   Test-Chat; externer Redirect). **Modell-Wechsel-Test:** einen DMS-Request
   (mistral) auslösen, danach einen Chat (qwen) — beide müssen laden, `nvidia-smi`
   darf in keinem der beiden Zustände über 24 GB gehen.
6. **Nachher messen:** Token/s erneut, Vorher/Nachher dokumentieren
   (Ziel Chat-Modell ≥ +20 %).

### 8. Rollback (Ziel: wenige Minuten)

1. Konsumenten-`.env` auf die alten Werte zurück (`ollama-3090:11434`,
   Ollama-Modellnamen).
2. `llama-3090` stoppen, `ollama-3090` starten.
3. Konsumenten + n8n-Workflows (alte Versionen) neu starten/deployen.
4. **nginx:** `ollama-3090.conf` wieder als Proxy herstellen,
   `llama-3090.conf` deaktivieren, syncen, neu laden.
5. Ollama-Modell-Volume ist unangetastet → keine Datenwiederherstellung nötig.

Die `ollama-3090`-Container-Definition und das Modell-Volume bleiben eine
**dokumentierte Karenzzeit** (Vorschlag: bis zum nächsten stabilen
Wochen-Review) erhalten und werden erst danach abgeräumt.

### 9. Wesentliche Risiken (aus der Edge-Case-Liste, PM-Kurzfassung)

| Risiko | Umgang |
| --- | --- |
| **qwen (ctx 16384 + mmproj) passt nicht neben Weaviate in die 24 GB** | `weaviate-transformers` gibt VRAM zurück: `PYTORCH_CUDA_ALLOC_CONF`-Cap (committed) bzw. CPU-Fallback (`ENABLE_CUDA=0`). `nvidia-smi`-Check + gestuftes `ctx-size` (16384→12288→8192) beim Cutover. Kein Datenverlust. |
| Kleineres `ctx-size` (8192) würde den Agenten-Tool-Loop begrenzen | Deshalb **nicht** akzeptiert — 16384 ist das Minimum; die VRAM-Zeile oben löst das Platzproblem stattdessen. |
| Modell-Wechsel-Latenz bei geteilter Nutzung Chat ↔ DMS | Wird dokumentiert, kein Akzeptanzkriterium. Batch-Timeouts (`OLLAMA_TIMEOUT_MS`) müssen eine Ladephase überdauern. |
| Tool-Call-/Thinking-Feld heißt im OpenAI-Format anders | `/backend` passt Parser an; robustes Parsen beider Argument-Formen bleibt erhalten; kein Denk-Text im Antworttext. |
| Vision ohne geladenen Projektor → sinnlose Beschreibung | `dms-extractor-image` muss einen **klaren Fehler** bekommen, keinen stillen Text-only-Fallback. |
| Externe Notebooks rufen Ollama-native Pfade (`/api/generate`, `/api/tags`) | Redirect fängt den Hostname; die Pfade selbst müssen auf `/v1/...` umgestellt werden. In der Spec dokumentiert, **keine** Kompat-Shim-Pflicht. |
| `ollama-titan` versehentlich mit angefasst | Umstellung berührt nur den `ollama-3090`-Block; `ollama-titan` bleibt in seiner Compose-Datei unverändert und muss nach dem Cutover weiter erreichbar sein. |

### 10. Was dieses Design NICHT festlegt (bleibt `/backend` / `/deploy`)

- Exakte llama.cpp-Startparameter (Kontextgröße, GPU-Layer, Leerlauf-Unload-TTL,
  Port).
- Die konkreten GGUF-Bezugsquellen/Dateinamen der beiden Modelle.
- Das genaue Bild-Content-Format für den Vision-Request.
- Die exakten Code-Anpassungen in `streaming.py` und den n8n-Code-Nodes.

### 11. Abhängigkeiten / Reihenfolge

`/backend` baut: llama-3090-Compose + Healthcheck, `streaming.py`- und
`memory.py`-Anpassung, 9 n8n-Workflow-Anpassungen, `dms-extractor-image`-Anpassung,
zwei nginx-Configs, alle `.env.example`. Danach `/qa` gegen die Paritäts- und
Performance-Kriterien, dann `/deploy` als Cutover mit dokumentiertem Rollback.

## Implementation Notes (Backend)

_Implementiert am 2026-09-01. Router-Ansatz: **llama.cpp nativer Router-Modus**
(kein separater Router-Container) — vom Nutzer bestätigt._

### Neuer Dienst

- **`docker/compose/ai/llama-3090/compose.yml`** — `ghcr.io/ggml-org/llama.cpp:server-cuda`,
  Container `llama-3090`, Port `11434`, GPU auf die RTX 3090 gepinnt (gleiche
  `device_ids` wie `ollama-3090`). Networks: `frontend, backend, automation`
  (Superset der Netze aller Konsumenten). Command:
  `--models-preset /models/presets.ini --models-max 1
  --api-key-file /run/secrets/llama_api_key` (kein `--sleep-idle-seconds`).
  Healthcheck gegen `/health`.
- **`presets.ini.example`** — zwei Sektionen, Sektionsname = Model-ID im Request
  (**`:`-frei**, sonst schreibt llama.cpp sie um — im Log verifiziert):
  `[qwen3-vl-30b]` → `/models/Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf` +
  `/models/mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf`, `reasoning-format = deepseek`,
  `load-on-startup = true`; `[mistral-small-3.2-24b]` →
  `/models/mistralai_Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf`
  (bartowski-Requant, kein HF-Login). Pfade **absolut** (Router-Subprozess-CWD
  ≠ `/models`). **Kein** `stop-timeout` / Idle-Unload. Real-Datei liegt auf dem
  Volume `/srv/hot/models/llama-cpp/presets.ini` (nicht gesynct).
- **`compose.yml`** — `--sleep-idle-seconds` **nicht** gesetzt: der Router
  entlädt nie von selbst, ein Modell weicht nur, wenn das andere angefragt wird.
- **`README.md`** (Service-Ordner) — Endpoint, Modelle, Server-Dateien, Secret,
  Rollback.
- **`docker/compose/scripts/Makefile`** — `ai/llama-3090` in `STACKS` ergänzt.
  `ai/ollama` bleibt (läuft in der Karenzzeit nur noch `ollama-titan`;
  `ollama-3090`-Service wird gestoppt, nicht entfernt).

### nginx

- **`conf.d/llama-3090.conf`** (neu) — `llama3090.happy-mining.de` →
  `http://llama-3090:11434`, Header/Timeouts 1:1 aus `ollama-3090.conf`.
- **`conf.d/ollama-3090.conf`** (umgebaut) — beide Server-Blöcke (80 + 443)
  liefern nur noch `301` auf `https://llama3090.happy-mining.de$request_uri`.

### API-Format-Umstellung (Ollama → OpenAI)

Einheitlicher Ziel-Endpoint: `POST {OLLAMA_URL}/v1/chat/completions`, Header
`Authorization: Bearer {OLLAMA_API_KEY}` (wenn gesetzt). `OLLAMA_URL` ist überall
die Basis-URL **ohne** `/v1`.

| Alt (Ollama) | Neu (OpenAI / llama.cpp) |
| --- | --- |
| `POST /api/generate` `{model, prompt, stream:false, format:'json', options:{temperature, num_predict}}` | `POST /v1/chat/completions` `{model, messages:[{role:'user',content:prompt}], stream:false, temperature, max_tokens:num_predict, response_format:{type:'json_object'}}` |
| Antwort: `resp.data.response` | Antwort: `resp.data.choices[0].message.content` |
| `POST /api/chat` NDJSON-Stream, `message.thinking`, `message.tool_calls`, `done`+`eval_count` | `POST /v1/chat/completions` SSE `data:`-Frames, `choices[0].delta.reasoning_content`, `choices[0].delta.tool_calls` (fragmentiert nach `index`), `[DONE]`, `usage` via `stream_options.include_usage` |
| `/api/tags` (Health) | `/v1/models` (gleiche 2xx-Semantik) |
| Vision: `images:[b64]` | `content:[{type:'text',…},{type:'image_url',image_url:{url:'data:image/jpeg;base64,…'}}]` |
| Think aus: top-level `think:false` | `chat_template_kwargs:{enable_thinking:false}` |

### `alice-chat-stream` (Python)

- **`app/streaming.py`** — `stream_chat` komplett auf SSE-`data:`-Parsing
  umgestellt. Neu: `_merge_tool_call_delta()` akkumuliert fragmentierte
  OpenAI-Tool-Calls nach `index`, synthetisiert fehlende IDs (`call_<n>`).
  Reasoning aus `delta.reasoning_content`/`reasoning`, nie in `accumulated_text`
  oder Token-Zähler. `usage` aus dem Trailing-Chunk. Fehler-Events unverändert
  (deutschsprachig). `OLLAMA_TIMEOUT_SECONDS` Default 60 → 120 (Cold-Load).
- **`app/memory.py`** — `generate_title_async` von `/api/generate` auf
  `/v1/chat/completions` (non-streaming) + `_llm_headers()`.
- **`tests/test_streaming_openai.py`** (neu) — 3 Tests für `_merge_tool_call_delta`.
  Bestehender `test_extract_vision_results.py` unverändert grün.
- `_extract_vision_results`, alle `_build_*`-Helfer und `tools.tool_schema()`
  (schon OpenAI-Function-Format) **unverändert**.

### `dms-extractor-image` (Python)

- **`main.py`** — `get_ai_description` auf `/v1/chat/completions` mit
  `image_url`-Content-Part. Leere Beschreibung → `RuntimeError` (kein stiller
  Text-only-Fallback, Spec-Edge-Case).

### n8n-Workflows (9)

Skript **`scripts/migrate-workflows-llamacpp.py`** (idempotent, `--check`):
Code-Nodes bekommen einen vorangestellten Shim `llamaGenerate(body, cfg)`, der
den **alten** Ollama-Body annimmt und ein `{ data: { response } }`-förmiges
Ergebnis zurückgibt — jede Call-Site ändert sich nur zu
`await llamaGenerate(BODY, CFG)`. Hardcodierter Host `http://ollama-3090:11434`
→ `$env.OLLAMA_URL`. `/api/tags` → `/v1/models`.

Die 2 HTTP-Request-Nodes von Hand umgestellt (OpenAI-Body + Auth-Header) +
jeweils die eine Downstream-Parse-Zeile:

| Workflow | Geänderte Nodes |
| --- | --- |
| `alice-dms-classify-document` | `Code: Two-Attempt Classification` (Shim) |
| `alice-dms-classification-backfill` | `Code: Ollama Health Check` (→ `/v1/models`), `Code: Compare & Handle` (Shim, 2 Call-Sites) |
| `alice-dms-language-check` | `Code: Language Heuristic + Retry` (Shim) |
| `alice-dms-language-backfill` | `Code: Ollama Health Check` (→ `/v1/models`) |
| `alice-dms-processor` | `HTTP: Ollama Extract` (OpenAI-Body+Auth), `Code: Parse Extract Result` (Parse + Shim für Retry), `Code: BankTransaction Phase B` (Shim) |
| `alice-mail-attachment-processor` | `Code: Process Queue Item` (Shim, `callOllama`) |
| `alice-mail-attachment-backfill` | `Code: Import Mail Attachments` (Shim, `callOllama`) |
| `alice-mail-sync` | `Process + Classify + Store Emails` (Shim) |
| `alice-dms-image-description-backfill` | `HTTP: Ollama Vision` (OpenAI-Vision-Body+Auth), `Code: Extract Description` (Parse) |

**Neuer Workflow `alice-llm-model-warmup.json`** (4 Nodes): Schedule
`0 5 * * *` (UTC = 07:00 Europe/Berlin MESZ / 06:00 MEZ) → `HTTP: Warm qwen`
(`POST /v1/chat/completions`, `model=$env.OLLAMA_MODEL`, `max_tokens:1`,
`onError: continueRegularOutput`) → `Code: Log Result` (Winston). Lädt qwen
vor Arbeitsbeginn (verdrängt das nachts geladene mistral), damit der erste
Chat des Tages keine Kaltstart-Verzögerung hat. n8n-mcp-Validierung: 0 Fehler.
Zu deployen via `Deploy n8n-workflow alice-llm-model-warmup`.

Prompts, Retry-/Lock-/Zeitlimit-Logik: **unverändert**. Die Modell-**Namen** in
den Code-Node-Fallbacks wurden auf die neuen `:`-freien IDs gezogen —
`'qwen3.5:27b-q4_K_M'` / `'qwen3:14b'` → `'mistral-small-3.2-24b'` an allen
DMS-Call-Sites (behebt nebenbei den vorbestehenden `qwen3:14b`-Fallback,
BUG-2), `alice-mail-sync`s hartkodiertes Klassifizierungs-Modell → env-getrieben
(`$env.OLLAMA_MODEL_DMS`). Alle Dateien: `node --check` grün, JSON valide,
`migrate-workflows-llamacpp.py --check` sauber.

### Environment (`.env.example`, keine Secrets)

- `alice-chat-stream`: `OLLAMA_URL=http://llama-3090:11434`,
  `OLLAMA_MODEL=qwen3-vl-30b`, neu `OLLAMA_API_KEY`, `OLLAMA_TIMEOUT_SECONDS=120`.
- `dms-extractor-image`: `OLLAMA_URL=http://llama-3090:11434`,
  `OLLAMA_VISION_MODEL=qwen3-vl-30b`, neu `OLLAMA_API_KEY`.
- `n8n`: `OLLAMA_URL=http://llama-3090:11434`, neu `OLLAMA_API_KEY`,
  `OLLAMA_MODEL`/`OLLAMA_VISION_MODEL` = `qwen3-vl-30b`,
  `OLLAMA_MODEL_DMS` = `mistral-small-3.2-24b`. **n8n hat kein `env_file`** —
  `OLLAMA_API_KEY` musste zusätzlich als `environment:`-Zeile in
  `n8n/compose.yml` ergänzt werden (BUG-3, s. u.).
- `openwebui`: neues `.env.example` + `env_file`, compose auf
  `ENABLE_OPENAI_API=true` / `OPENAI_API_BASE_URL=http://llama-3090:11434/v1` /
  `OPENAI_API_KEY=${OLLAMA_API_KEY}` / `ENABLE_OLLAMA_API=false`.
- Server-seitig zusätzlich: `/srv/warm/llama-3090/llama_api_key` (1 Zeile),
  `/srv/hot/models/llama-cpp/` (GGUF + `presets.ini` + `cache/`).

### Weaviate-VRAM (geteilte 3090)

- **`docker/compose/automations/weaviate/compose.yml`** — `t2v-transformers`
  bekommt `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:64,garbage_collection_threshold:0.6`,
  um den CUDA-Allocator zu deckeln (~3,3 GB → erwartet ~1–1,5 GB), damit qwen
  mit `ctx-size 16384` + mmproj neben Weaviate in die 24 GB passt. Kommentar im
  compose beschreibt den CPU-Fallback (`ENABLE_CUDA=0`). `multi2vec-clip`
  unverändert (GPU).

### Offen für /deploy (kein Code)

- GGUF-Dateien beschaffen + `presets.ini` schreiben. llama.cpp hat **keine
  Registry / kein `ollama pull`** und das Image bringt **keine HF-CLI** mit —
  Download auf dem **Host** ins Volume `/srv/hot/models/llama-cpp/` mit dem
  `hf`-Kommando (`pipx install "huggingface_hub[cli]"`; **nicht** das veraltete
  `huggingface-cli`). Konkrete Kommandos + `hf:`-Alternative:
  `docker/compose/ai/llama-3090/README.md` → „Getting the GGUF files".
  - **Chat/Vision:** `Qwen/Qwen3-VL-30B-A3B-Instruct-GGUF` →
    `Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf` (~18,6 GB) **+**
    `mmproj-Qwen3VL-30B-A3B-Instruct-F16.gguf` (~1,1 GB, Vision-Projektor für
    `dms-extractor-image` / `image-description-backfill`).
  - **DMS-Text:** `Mistral-Small-3.2-24B-Instruct-2506` Q4_K_M (~14 GB), nur
    Sprachgewichte, kein mmproj. Offizielles `mistralai/…-GGUF` ist **gated**
    (`hf auth login`); offene Alternative:
    `bartowski/mistralai_Mistral-Small-3.2-24B-Instruct-2506-GGUF`.
- Rechte auf dem Server: `/srv/hot/models/llama-cpp/` `750 root:docker`
  (analog `…/ollama`), GGUF + `presets.ini` `640 root:docker` (kein Secret);
  `/srv/warm/llama-3090/` `700 root:root`, `llama_api_key` `600 root:root`
  (**Secret**, Container liest als root).
- `llama_api_key` erzeugen + in alle Konsumenten-`.env` eintragen.
- **Prod-`.env` Modell-Namen** auf die `:`-freien IDs setzen:
  `OLLAMA_MODEL` / `OLLAMA_VISION_MODEL` = `qwen3-vl-30b`,
  `OLLAMA_MODEL_DMS` = `mistral-small-3.2-24b` (alice-chat-stream,
  dms-extractor-image, n8n). Müssen exakt den `presets.ini`-Sektionsnamen
  entsprechen. `presets.ini`: absolute `/models/…`-Pfade.
- **`weaviate-transformers` VRAM-Cap verifizieren** (§7 Schritt 2): mit
  `PYTORCH_CUDA_ALLOC_CONF` (bereits im `weaviate/compose.yml`, committed) sollte
  der Container von ~3,3 GB auf ~1–1,5 GB fallen. Greift der Cap nicht: auf CPU
  umstellen (`ENABLE_CUDA=0` + `deploy.resources` raus). Ziel: ~2–3 GB frei für
  qwen mit `ctx-size 16384`.
- **VRAM-Check beim Schnitt** (§7 Schritt 4): `nvidia-smi` bestätigen, dass qwen
  (ctx 16384 + mmproj) neben Weaviate in die 24 GB lädt. Preset `ctx-size 16384`
  ist das Agenten-Loop-Minimum; bei OOM gestuft 16384→12288→8192 **oder**
  `t2v-transformers` auf CPU. mistral unkritisch.
- Cutover-Reihenfolge + Vorher/Nachher-Benchmark (§7 Tech Design).
- n8n-Workflows via `Deploy n8n-workflow {name}` (9× migriert + 1× neu:
  `alice-llm-model-warmup`).
- Warmup-Zeitpunkt `0 5 * * *` UTC ggf. an eine geänderte DMS-Startzeit
  anpassen (muss nach dem 02:00-DMS-Lauf und vor Arbeitsbeginn liegen).

## QA Test Results

_Statische Code-/Config-Review am 2026-09-01 (kein `llama-3090` live —
Server-Bereitstellung ist `/deploy`-Scope, analog zum QA-Vorgehen bei PROJ-97/98).
Geprüft: alle geänderten/neuen Dateien aus dem Backend-Commit `fe74d42`,
Python-Syntax (`py_compile`), JS-Syntax aller 9 Workflow-Code-Nodes
(`node --check`), Unit-Tests (`pytest`), Migrationsskript `--check`,
nginx-Klammerbilanz, Secret-Scan der `.env.example`._

### Acceptance Criteria

#### Backend-Bereitstellung

| # | Kriterium | Status | Anmerkung |
| - | --- | --- | --- |
| 1 | llama.cpp läuft auf RTX 3090, ersetzt ollama-3090 | **Code bereit** | `docker/compose/ai/llama-3090/compose.yml`, GPU-Pin identisch zu `ollama-3090`. Live-Start = `/deploy`. |
| 2 | Ein Endpoint, dynamischer Router, beide Modelle | **Code bereit** | `--models-preset` + `--models-max 1` + `--sleep-idle-seconds 900`, kein separater Router-Container (Nutzerentscheidung). |
| 3 | Gleiche Quants wie Ollama | **Nicht prüfbar (statisch)** | Abhängig von den tatsächlich beschafften GGUF-Dateien — `/deploy`-Aufgabe. |
| 4 | `ollama-titan` unangetastet | **PASS** | `docker/compose/ai/ollama/compose.yml` nicht verändert (git diff leer); `llama-3090` ist eine neue, eigenständige Compose-Datei. |
| 4b | Kein Idle-Unload + Morgen-Warmup | **PASS (Code)** | `compose.yml` ohne `--sleep-idle-seconds`; `presets.ini.example` ohne `stop-timeout`, mit `load-on-startup=true` für qwen. Neuer Workflow `alice-llm-model-warmup` (Schedule `0 5 * * *` UTC): n8n-mcp-Validierung 0 Fehler, JS `node --check` grün. Live-Verifikation (qwen nach 07:00 resident) = `/deploy`. |
| 5 | `conf.d/llama-3090.conf` analog alter Config | **PASS** | Header/Timeouts/Body-Size 1:1 aus `ollama-3090.conf` übernommen, Klammern ausbalanciert. |
| 6 | Alter Vhost → dauerhafter 301 (HTTP+HTTPS) | **PASS** | Beide Server-Blöcke in `ollama-3090.conf` liefern `301` auf `https://llama3090.happy-mining.de$request_uri`. |
| 7 | Externe Clients funktionieren übergangsweise per Redirect | **Code bereit** | Redirect-Logik korrekt; Live-Verifikation = `/deploy`. |

#### Verhaltensparität `alice-chat-stream`

| # | Kriterium | Status | Anmerkung |
| - | --- | --- | --- |
| 8 | SSE-Event-Typen unverändert | **PASS (Code)** | `token`, `thinking_start`, `thinking`, `tool_start`, `tool_end`, `vision_results`, `conversation_end`, `done`, `[DONE]` — alle Emit-Stellen unverändert, nur die Quelle (SSE-`data:`-Parsing statt NDJSON) geändert. |
| 9 | Thinking-Stream: Denk-Tokens separat, nicht im Antworttext/Zähler | **PASS (Code)** | `delta.reasoning_content`/`reasoning` wird vor `content` verarbeitet, landet nur in `thinking_accumulator`, nie in `accumulated_text`/`CHAT_TOKENS_TOTAL`. Think aus → `chat_template_kwargs.enable_thinking=false`. |
| 10 | Tool-Loop: Aufruf → Ergebnis anhängen → erneuter Call → finale Antwort | **PASS (Code)** | `_merge_tool_call_delta` akkumuliert fragmentierte Tool-Calls korrekt nach `index` (3 neue Unit-Tests, siehe unten), Loop-Struktur unverändert. |
| 11 | Mehrere Tool-Runden end-to-end ohne doppelte/verlorene Ergebnisse | **PASS (Code)** | `tool_call_id` wird für jeden Call garantiert gesetzt (synthetisiert falls fehlend), verhindert verlorene Zuordnung. |
| 12 | Token-Zählung weiter erfasst | **PASS (Code)** | `usage` aus dem Trailing-Chunk (`stream_options.include_usage:true`) statt `eval_count`/`prompt_eval_count`; gleiche Zielstruktur `{prompt_tokens, completion_tokens}`. |
| 13 | `memory.py` Nicht-Streaming-Aufruf liefert Ergebnis | **PASS (Code)** | `generate_title_async` auf `/v1/chat/completions`, liest `choices[0].message.content`. |
| 14 | Fehlerfälle → gleiche dt. Fehler-Events, kein Hängen | **PASS (Code)** | `httpx.TimeoutException`/`HTTPError`-Handler unverändert, gleiche deutschen Meldungen. |

#### Verhaltensparität DMS-Pipeline (n8n)

| # | Kriterium | Status | Anmerkung |
| - | --- | --- | --- |
| 15 | `classify-document`: gleiches Ergebnis (Modell/Prompt) | **PASS (Code), Live-Test aussteht** | Prompt-Text unverändert, nur Transport (`llamaGenerate`-Shim). Ergebnisgleichheit hängt vom GGUF-Modell ab (`/deploy`). |
| 16 | `language-check` unverändert | **PASS (Code)** | Heuristik unverändert (lokal, kein LLM); nur der 2nd-Attempt-Call transportiert um. |
| 17 | `dms-processor` end-to-end, `OLLAMA_TIMEOUT_MS` wirksam | **PASS (Code)** | `OLLAMA_TIMEOUT_MS` unverändert als `cfg.timeout` durchgereicht (Phase B). HTTP-Node-Timeout (300000ms) unverändert. |
| 18 | `mail-sync`/`mail-attachment-processor` unverändert | **PASS (Code)** | Beide Shim-transportiert, Klassifizierungs-/Fallback-Logik (`ollamaReachable`) unverändert. |
| 19 | 4 Backfills laufen im Dry-Run | **Code bereit, Live-Test aussteht** | Kein Strukturbruch erkennbar; Dry-Run-Verifikation ist `/deploy`-Scope. |
| 20 | Health-Check-Äquivalent zu `/api/tags` | **PASS (Code)** | `/api/tags` → `/v1/models`, gleiche 2xx-Prüfung, in beiden betroffenen Workflows (`classification-backfill`, `language-backfill`). |

#### Verhaltensparität Vision & Open WebUI

| # | Kriterium | Status | Anmerkung |
| - | --- | --- | --- |
| 21 | `dms-extractor-image` liefert dt. Bildbeschreibung | **PASS (Code), Live-Test aussteht** | OpenAI-Vision-Content-Format korrekt (`image_url` + `data:image/jpeg;base64,…`), Prompt unverändert. |
| 22 | `image-description-backfill` Dry-Run ohne Fehler | **Code bereit** | HTTP-Node + Parse-Node konsistent umgestellt, `fullResponse` beibehalten (IF-Node-Kompatibilität). |
| 23 | Open WebUI verbindet, listet Modelle, Test-Chat | **Code bereit, Live-Test aussteht** | `ENABLE_OPENAI_API=true` + `OPENAI_API_BASE_URL` gesetzt; neues `.env.example` mit `OLLAMA_API_KEY`. |

#### Performance

| # | Kriterium | Status | Anmerkung |
| - | --- | --- | --- |
| 24 | Vorher/Nachher-Benchmark dokumentiert | **Offen** | Explizit `/deploy`-Scope (Spec §7). |
| 25 | ≥ +20 % tok/s Chat-Modell | **Offen** | Nur live messbar. |
| 26 | Keine funktionale Regression | **PASS (Code), Live-Bestätigung aussteht** | Kein Paritäts-Kriterium zeigt einen Codepfad-Bruch. |

#### Cutover & Rollback

| # | Kriterium | Status | Anmerkung |
| - | --- | --- | --- |
| 27 | Harter Cutover dokumentiert | **PASS** | Tech-Design §7. |
| 28 | `ollama-3090` bleibt (Karenzzeit) | **PASS** | Compose-Datei nicht gelöscht, nur außer Betrieb genommen (Doku in Tech Design + Service-README). |
| 29 | Rollback-Prozedur dokumentiert, Minuten-Wiederherstellung | **PASS** | Tech-Design §8 + Service-README. |
| 30 | README + `.env.example` aktualisiert, keine Secrets | **PASS** | Alle 4 Konsumenten-`.env.example` + neues `openwebui/.env.example`; nur Platzhalter (`your-llama-api-key` etc.), Secret-Scan negativ. |
| 31 | nginx-Configs über `sync-compose.sh`, beide aktiv | **Code bereit** | Sync/Reload ist `/deploy`-Ausführung. |
| 32 | Rollback schließt nginx-Ebene ein | **PASS** | Dokumentiert in Tech Design §8 + Service-README. |
| 33 | n8n-Workflows über Standard-Deploy-Weg | **PASS** | Kein direkter Live-Edit vorgenommen; JSONs liegen in `workflows/` zum Deploy über `Deploy n8n-workflow {name}`. |

**Zusammenfassung AC:** 34 Kriterien geprüft (inkl. AC 4b Idle-Unload/Warmup) —
25× PASS (Code), 1× PASS mit Live-Test ausstehend explizit vermerkt, 8× als
reine Cutover-/Messwert-Aufgaben korrekt an `/deploy` delegiert (kein Bug, kein
offener Punkt im Code).

**Nachtrag 2026-09-01:** Idle-Unload aus dem `llama-3090`-compose entfernt
(`--sleep-idle-seconds` gestrichen) + `presets.ini` ohne `stop-timeout` +
neuer Workflow `alice-llm-model-warmup` (Schedule `0 5 * * *` UTC = 07:00
Europe/Berlin) — verhindert, dass qwen im Tagesverlauf bei jedem Chat neu lädt
(Ersatz für Ollamas `OLLAMA_KEEP_ALIVE=-1`). n8n-mcp-Validierung: 0 Fehler.
Kein neuer Bug.

**Nachtrag 2026-09-01 (Modell-Identifikation):** Der Ollama-Tag
`qwen3.5:27b-q4_K_M` wurde per `ollama show` aufgelöst → **Qwen3-VL-30B-A3B-
Instruct** (MoE, `arch qwen35`, `27.8B`, vision+tools+thinking), **nicht** ein
Dense-27B. `mistral-small3.2:24b` → Standard **Mistral-Small-3.2-24B-Instruct-
2506**. Der Tag-String bleibt als `model`-Feld (kein Konsument ändert sich);
Doku/Preset auf die echten GGUF-Repos + Dateinamen präzisiert.

**Nachtrag 2026-09-01 (VRAM-Bilanz, echte `nvidia-smi`-Zahlen):** Die RTX 3090
(24 GB) ist geteilt — `weaviate-transformers` **3290 MiB** + `multi2vec-clip`
**1418 MiB** = **~4,7 GB dauerhaft**. Ollama fuhr qwen bereits **auf der 3090**
(nicht TITAN X) mit **18968 MiB** → zusammen ~23,7/24 GB, ~0,9 GB frei.

**Iteration 2 (ctx-size vs. Agenten-Loop):** Ein erster Ansatz `ctx-size 8192`
zur VRAM-Schonung wurde **verworfen** — Alice sendet im Tool-Loop System-Prompt
+ 7-Tool-Schema + letzte 20 Turns + bis 4 Runden Tool-Ergebnis-JSON (Suchtreffer
können groß sein); 8192 läuft über, sobald eine Suche viele Treffer liefert, und
der Agenten-Loop ist das Kern-Ziel der Umstellung. **`ctx-size 16384`** ist das
Arbeits-Minimum (Preset-Default). Damit qwen (~21 GB mit mmproj + 16k-KV) neben
Weaviate passt, gibt **`weaviate-transformers` VRAM zurück**:
`PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:64,…` im `weaviate/compose.yml`
(committed; MiniLM ist ~470 MB, die 3,3 GB sind Allocator-Reserve → erwartet
~1–1,5 GB) — Fallback: `t2v-transformers` auf CPU (`ENABLE_CUDA=0`,
+50–150 ms/Text-Embedding, Chat-Pfad ist LLM-Zeit-dominiert). `multi2vec-clip`
bleibt GPU. `--models-max 1` bleibt korrekt (beide LLMs zusammen ~34 GB).

**Risiko (Medium, Deploy-verifizierbar):** Reicht der Allocator-Cap nicht und
lädt qwen mit ctx 16384 trotzdem nicht neben Weaviate, ist der Fix (a)
`t2v-transformers` auf CPU oder (b) `ctx-size` gestuft 16384→12288→8192. Fällt
beim Cutover sofort auf (Modell lädt nicht), kein Datenverlust, kein Code-Bug.
`nvidia-smi`-Checks in §7 Schritt 2 + 4.

**Nachtrag 2026-09-02 (erster `llama-3090`-Start, zwei Blocker aus dem Log
behoben):**

1. **`:` im Preset-Sektionsnamen wird umgeschrieben.** `[qwen3.5:27b-q4_K_M]`
   wurde als Model-ID `qwen3.5:Q4_K_M` exponiert, `[mistral-small3.2:24b]` als
   `mistral-small3.2:24B` — llama.cpp behandelt alles nach dem ersten `:` als
   `tag` inkl. Case-Normalisierung. → Model-IDs auf **`qwen3-vl-30b`** /
   **`mistral-small-3.2-24b`** (`:`-frei) umgestellt: `presets.ini.example`,
   3× `.env.example`, 9 Workflow-Code-Fallbacks, `alice-llm-model-warmup`,
   README, Tech Design. Prod-`.env` müssen entsprechend angepasst werden
   (`OLLAMA_MODEL`/`OLLAMA_VISION_MODEL`=`qwen3-vl-30b`,
   `OLLAMA_MODEL_DMS`=`mistral-small-3.2-24b`).
2. **Relative GGUF-Pfade greifen nicht.** `failed to open GGUF file
   'Qwen3VL-…gguf' (No such file or directory)` — der Router-Subprozess hat ein
   anderes CWD als `/models`. → `presets.ini` nutzt **absolute** Pfade
   (`/models/…`).

Harmlose Log-Meldungen (kein Handlungsbedarf): `LLAMA_ARG_HOST … overwritten
by --host` (Image-Default), `control-looking token 128247 '</s>' was not
control-type` (Tokenizer-Metadaten, llama.cpp korrigiert selbst), zwei
`listening on`-Zeilen (Router `0.0.0.0:11434` + interner Modell-Subserver auf
`127.0.0.1:<random>` — nur der Router-Port ist der Endpoint).

**BUG-3 (beim Deploy gefunden, behoben) — `OLLAMA_API_KEY` fehlte in
`n8n/compose.yml`.** Anders als die anderen Konsumenten nutzt `n8n` **kein**
`env_file` — jede Variable wird einzeln unter `environment:` durchgereicht. Der
Backend-Commit hatte `OLLAMA_API_KEY` in `.env.example` ergänzt, aber die
`environment:`-Zeile `- OLLAMA_API_KEY=${OLLAMA_API_KEY}` vergessen → die 9
migrierten Workflows hätten `$env.OLLAMA_API_KEY` als `undefined` gesehen und
401 vom Router bekommen. Fix: die eine Zeile ergänzt. (`OLLAMA_URL`/
`OLLAMA_MODEL`/`OLLAMA_MODEL_DMS`/`OLLAMA_VISION_MODEL` waren schon vorher
durchgereicht.)

**Nachtrag 2026-09-02 (VRAM-Tuning nach echtem `nvidia-smi`):** qwen mit
`ctx 16384` + mmproj lud zunächst mit **20864 MiB** (Default `n_slots = 4`) →
zusammen mit Weaviate ~23,1/24 GB. Zwei Preset-Settings ergänzt:
`parallel = 1` (1 KV-Slot statt 4, spart ~3–4 GB; Alice = 1 sequ.
Chat-Stream/Nutzer) und `image-min-tokens = 1024` (Qwen3-VL braucht ≥1024
Bild-Tokens für zuverlässiges Grounding — sonst werden die ≤1024-px-DMS-Bilder
zu stark heruntergerechnet, Beschreibungen unscharf). Der
`PYTORCH_CUDA_ALLOC_CONF`-Cap auf `t2v-transformers` hat gewirkt: **3290 → 792
MiB**. Endstand: qwen ~20,9 GB + weaviate ~2,2 GB = **~23,1/24 GB, ~1,5 GB
frei** — läuft, aber dünner Puffer. Fallback dokumentiert (`ctx-size 12288`
bzw. `t2v-transformers` auf CPU). Kein Code-Bug.

### Edge Cases (9, aus der Spec)

| Edge Case | Status |
| --- | --- |
| Dynamischer Modell-Wechsel unter Last | Dokumentiert wie gefordert, kein AC — Router-Config (`--models-max 1`) entspricht der Spec-Vorgabe. |
| Abweichendes Tool-Call-Format | **PASS** — `_merge_tool_call_delta` verarbeitet fragmentierte OpenAI-Calls; bestehendes JSON-String/Objekt-Parsing für `arguments` unverändert (Try/Except → leere Args). |
| Reasoning-Feld heißt anders | **PASS** — `reasoning_content`/`reasoning` behandelt, kein Leck in `accumulated_text`. |
| Streaming-Zeilenformat (SSE statt NDJSON) | **PASS** — Parser komplett auf `data:`-Frames umgestellt, nicht-`data:`-Zeilen übersprungen (kein Fehler). |
| `done`/Usage-Signal | **PASS** — `finish_reason` + `stream_options.include_usage`; bei fehlendem Usage bleiben Zähler bei ihrem letzten Stand (min. 0), kein Absturz. |
| VRAM reicht nicht | Nur beim Cutover feststellbar — Rollback-Pfad vorhanden. |
| Vision ohne mmproj | **PASS** — `dms-extractor-image`: leere Beschreibung wirft jetzt `RuntimeError` statt stillem Fallback; `process_message` fängt das als `extraction_failed=True` ab. |
| `ollama-titan` versehentlich mitgetroffen | **PASS** — kein Diff an `docker/compose/ai/ollama/compose.yml`. |
| Open WebUI Modell-Cache | Dokumentiert (Reload nach Cutover) — Betriebsschritt, kein Code. |
| Externer Client folgt keinem Redirect | Akzeptiert wie in der Spec, Hostname im README dokumentiert. |
| Ollama-native API nicht verfügbar | Dokumentiert, keine Kompat-Shim gebaut — wie spezifiziert. |

### Bugs gefunden

Keine Critical/High. Zwei Findings dokumentiert, keines blockiert den Merge:

**BUG-1 (Medium) — Bearer-Token in n8n-HTTP-Node-Parametern statt Credential-Store.**
Die zwei umgestellten HTTP-Request-Nodes (`alice-dms-processor` „HTTP: Ollama
Extract", `alice-dms-image-description-backfill` „HTTP: Ollama Vision") tragen
den neuen `Authorization: Bearer …`-Header als rohen `{{ $env.OLLAMA_API_KEY }}`-
Ausdruck im Node-Parameter statt über einen n8n-Credential (wie z. B. die
bestehende `Ollama 3090`/`pg-alice`-Credential). n8n maskiert Header-Werte aus
Credentials in Execution-Logs/-UI, rohe Ausdrücke dagegen nicht — der Key
erscheint im Klartext in der Execution-Historie für jeden mit n8n-UI-Zugriff.
Kein Internet-Exposure (VPN-only, kein neues Secret nach außen), aber ein
Downgrade gegenüber dem etablierten Muster dieses Repos.
*Empfehlung:* vor Produktivbetrieb eine n8n-Credential vom Typ „Header Auth"
für den llama.cpp-Key anlegen und in beiden Nodes referenzieren (analog zur
Postgres-/Ollama-Credential), statt der rohen Env-Expression.

**BUG-2 (Low, vorbestehend) — inkonsistenter Modell-Fallback — BEHOBEN.** Die
Code-Nodes hatten `$env.OLLAMA_MODEL_DMS || 'qwen3:14b'` (Fallback ≠
dokumentiertes DMS-Modell, vorbestehend seit vor diesem Feature). Da der
Model-ID-Wechsel auf `:`-freie Namen (`ollama show`-Fund, s. u.) ohnehin **alle**
`.env` + Workflow-Fallbacks anfassen musste, wurden die Fallbacks bei der
Gelegenheit auf `'mistral-small-3.2-24b'` konsolidiert und `alice-mail-sync`s
hartkodiertes Modell env-getrieben gemacht. Kein offener Punkt mehr.

### Security-Audit (Kurzfassung)

- Kein Secret im Klartext in `.env.example`/README/Compose (nur Platzhalter).
- `llama-3090` bleibt intern (Docker-Netz) + VPN-only extern, wie die Vorgänger-Instanz.
- Neues Secret (`OLLAMA_API_KEY`) korrekt aus `.env` bezogen, nicht hartkodiert.
- BUG-1 (oben) ist der einzige sicherheitsrelevante Fund — Medium, kein Blocker,
  da weiterhin VPN-only und kein Zugriff ohne n8n-UI-Login möglich.
- Keine neuen Webhook-/Auth-Oberflächen durch dieses Feature (reiner Backend-Tausch).

### Automatisierte Tests

- `pytest` (`alice-chat-stream/tests/`): 18/18 grün, davon 3 neu
  (`test_streaming_openai.py`: `_merge_tool_call_delta` — Fragment-Merge,
  ID-Synthese, zwei parallele Tool-Calls).
- `python3 -m py_compile` auf allen geänderten `.py`-Dateien: grün.
- `node --check` auf allen 9 Workflow-Code-Nodes (nach Transformation): grün.
- `scripts/migrate-workflows-llamacpp.py --check`: „Code nodes clean" (keine
  Alt-Host-Reste in Code-Nodes).
- nginx-Config-Klammerbilanz: ausgeglichen (kein `nginx -t`, da kein lokaler
  nginx verfügbar — echte Syntaxprüfung ist `/deploy`-Schritt).

### Production-Ready-Entscheidung

**DEPLOYED 2026-09-02.** Der Cutover verlief ohne Zwischenfall. Die statische
QA (34 AC) hielt beim Live-Test stand; die drei Deploy-Bugs (BUG-3 n8n-Env,
Preset-`:`-Namen, relative Pfade) wurden während des Cutovers behoben. Kein
Critical/High-Bug offen.

- **Performance:** Chat-Modell ~31,9 → **~178 tok/s** (~5,6×, Ziel war ≥ +20 %).
- **VRAM-Vorbehalt aufgelöst:** `parallel = 1` + Allocator-Cap → qwen + Weaviate
  bei ~23,1/24 GB, läuft stabil. `t2v-transformers` blieb auf der GPU (CPU-
  Fallback nicht nötig).
- **BUG-1 (Bearer-Token als rohe n8n-Env-Expression statt Credential):** weiter
  offen als Low/Medium-Nachlauf — funktional korrekt, nur nicht in Execution-
  Logs maskiert. Eigenes Ticket, falls gewünscht; kein Blocker.
- **Nachlauf:** Andreas prüft die restlichen DMS-/Mail-Workflows im Laufe der
  Tage live.

## Deployment

**Deployed 2026-09-02 — harter Cutover, voller Erfolg.**

### Ablauf (wie durchgeführt)

1. Vorbereitung: GGUF-Modelle nach `/srv/hot/models/llama-cpp/`
   (`Qwen3VL-30B-A3B-Instruct-Q4_K_M.gguf` + `mmproj-…-F16.gguf`,
   `mistralai_Mistral-Small-3.2-24B-Instruct-2506-Q4_K_M.gguf`), `presets.ini`
   mit **absoluten** Pfaden + `:`-freien Sektionsnamen, `llama_api_key` erzeugt
   + in alle Konsumenten-`.env`, Container auf den Server gesynct.
2. `weaviate-transformers` mit `PYTORCH_CUDA_ALLOC_CONF`-Cap neu erzeugt →
   3290 → 792 MiB VRAM.
3. `ollama-3090` gestoppt, `llama-3090` gestartet. Zwei Preset-Fixes aus dem
   ersten Start-Log (`:`-Sektionsnamen, relative Pfade — s. QA-Nachträge),
   dann `parallel = 1` + `image-min-tokens = 1024` ergänzt.
4. `alice-chat-stream`, `dms-extractor-image`, `n8n` (+ `OLLAMA_API_KEY`-Zeile,
   BUG-3), `openwebui` neu erzeugt.
5. Alle 10 n8n-Workflows deployed + published (9 migriert +
   `alice-llm-model-warmup`).
6. nginx-Configs gesynct + reloaded (`llama-3090.conf` aktiv,
   `ollama-3090.conf` = 301-Redirect).

### Performance (Kern-Ziel — massiv übertroffen)

| Metrik | Ollama (qwen3.5:27b, dense) | llama.cpp (qwen3-vl-30b, MoE ~3B aktiv) | Faktor |
| --- | --- | --- | --- |
| **Token-Generierung Chat-Modell** | **~31,9 tok/s** | **~178 tok/s** | **~5,6×** (Ziel war ≥ +20 %) |
| Prompt-Eval Chat-Modell | ~1150 tok/s | ~3450 tok/s | ~3,0× |

Beispiel: eine 1874-Token-Antwort in **10,7 s** statt ~59 s. Der Agenten-Tool-Loop
(mehrere LLM-Runden pro Anfrage) profitiert am stärksten — genau das Spec-Ziel.
Grund für den Faktor: dense-27B → 30B-A3B-**MoE**.
`truncated = 0` bei 7888-Token-Kontext bestätigt: `ctx-size 16384` reicht für den
Tool-Loop.

### VRAM (RTX 3090, geteilt mit Weaviate)

qwen (ctx 16384, mmproj, `parallel 1`) ~20,9 GB + `weaviate-transformers`
~0,8 GB + `multi2vec-clip` ~1,4 GB ≈ **~23,1 / 24 GB**. `--models-max 1`,
kein Idle-Unload. Modell-Wechsel qwen ↔ mistral automatisch über das
`model`-Feld; `alice-llm-model-warmup` lädt qwen täglich 05:00 UTC vor.

### Betrieb

- `llama-3090`: `restart: unless-stopped`, kein
  `watchtower.enable=false` — Watchtower **benachrichtigt** hier nur (gotify),
  Updates werden manuell eingespielt. Nach jedem llama.cpp-Update `presets.ini`
  gegentesten (Router-Modus bewegt sich schnell).
- `ollama-3090`: Container-Definition + Modell-Volume bleiben während der
  Karenzzeit erhalten (gestoppt, nicht gelöscht). Rollback-Prozedur: Tech Design
  §8.
- Nachlauf: Andreas prüft im Laufe der Tage die restlichen DMS-/Mail-Workflows
  live (Klassifizierung, Sprachprüfung, Bildbeschreibung, Backfills).

### Bugs beim Deploy (alle behoben)

- **BUG-3** — `OLLAMA_API_KEY` fehlte in `n8n/compose.yml` (n8n hat kein
  `env_file`). Fix: `environment:`-Zeile ergänzt.
- Preset-`:`-Sektionsnamen + relative Pfade (s. QA-Nachträge 2026-09-02).
- `parallel = 4` (Default) → `parallel = 1` fürs VRAM-Budget.
