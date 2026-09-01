# PROJ-99: Umstellung Ollama → llama.cpp (ollama-3090)

## Status: In Progress
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
| **Modelle** | Zwei GGUF-Dateien im Modell-Ordner: das Chat-/Vision-Modell (`qwen3.5:27b`-Äquivalent, q4_K_M, **mit** zugehörigem Vision-Projektor/mmproj) und das DMS-Text-Modell (`mistral-small3.2:24b`-Äquivalent, q4_K_M). Gleiche Quantisierung wie heute. | Verhaltensparität: identischer Modellstand, identische Quant-Stufe → gleiche Antwortqualität, nur schneller. |
| **VRAM-Strategie** | Es ist **immer nur ein Modell** aktiv geladen. Wechselt die Last vom Chat aufs DMS-Modell (oder umgekehrt), entlädt/lädt der Server (Sekunden bis ~1 min). | 27b-q4 + 24b-q4 + Kontext passen **nicht sicher gleichzeitig** in 24 GB. „Ein Modell aktiv" ist die robuste Lösung; die Ladezeiten werden dokumentiert, nicht wegoptimiert (siehe Edge Case „Modell-Wechsel unter Last"). |
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

1. **Vorbereiten (ohne Live-Wirkung):** GGUF-Modelle in den neuen Modell-Ordner
   legen; Compose-Datei für `llama-3090` anlegen; neue nginx-Config
   `llama-3090.conf` schreiben; alte `ollama-3090.conf` auf Redirect umbauen;
   Konsumenten-`.env` mit neuen Werten vorbereiten.
2. **Baseline messen:** Token/s für Chat-Modell und DMS-Modell **unter Ollama**
   festhalten (Vorher-Wert für den Benchmark).
3. **Schnitt:** `ollama-3090` stoppen → `llama-3090` starten → warten bis
   `/v1/models` beide Modelle listet → alle Konsumenten mit neuer Config neu
   starten → n8n-Workflows deployen → nginx-Configs syncen (`sync-compose.sh`)
   und nginx neu laden.
4. **Paritäts-Checks:** die Prüfliste aus den Acceptance Criteria abarbeiten
   (Chat inkl. Thinking + mehrstufigem Tool-Loop; je ein DMS-Workflow live + ein
   Backfill im Dry-Run; Vision-Testbild; Open WebUI Test-Chat; externer
   Redirect).
5. **Nachher messen:** Token/s erneut, Vorher/Nachher dokumentieren
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
| 27b-Modell + Kontext sprengt die 24 GB | Fällt beim Cutover-Check auf (Modell lädt nicht) → Rollback. Ggf. Kontextgröße begrenzen. |
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
  `--models-preset /models/presets.ini --models-max 1 --sleep-idle-seconds 900
  --api-key-file /run/secrets/llama_api_key`. Healthcheck gegen `/health`.
- **`presets.ini.example`** — zwei Sektionen, Sektionsname = Modell-ID im
  Request: `qwen3.5:27b-q4_K_M` (mit `mmproj`, `reasoning-format = deepseek`)
  und `mistral-small3.2:24b`. Real-Datei liegt auf dem Volume
  `/srv/hot/models/llama-cpp/presets.ini` (nicht gesynct).
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

Modellwahl (`$env.OLLAMA_MODEL_DMS`, `$env.OLLAMA_VISION_MODEL`), Prompts,
Retry-/Lock-/Zeitlimit-Logik: **unverändert**. Alle 9 Dateien: `node --check`
grün, JSON valide, Diff minimal (nur die betroffenen `jsCode`-Strings +
HTTP-Node-Parameter).

### Environment (`.env.example`, keine Secrets)

- `alice-chat-stream`: `OLLAMA_URL=http://llama-3090:11434`,
  `OLLAMA_MODEL=qwen3.5:27b-q4_K_M`, neu `OLLAMA_API_KEY`,
  `OLLAMA_TIMEOUT_SECONDS=120`.
- `dms-extractor-image`: `OLLAMA_URL=http://llama-3090:11434`, neu `OLLAMA_API_KEY`.
- `n8n`: `OLLAMA_URL=http://llama-3090:11434`, neu `OLLAMA_API_KEY`,
  `OLLAMA_MODEL`/`OLLAMA_MODEL_DMS`/`OLLAMA_VISION_MODEL` auf die Preset-Namen.
- `openwebui`: neues `.env.example` + `env_file`, compose auf
  `ENABLE_OPENAI_API=true` / `OPENAI_API_BASE_URL=http://llama-3090:11434/v1` /
  `OPENAI_API_KEY=${OLLAMA_API_KEY}` / `ENABLE_OLLAMA_API=false`.
- Server-seitig zusätzlich: `/srv/warm/llama-3090/llama_api_key` (1 Zeile),
  `/srv/hot/models/llama-cpp/` (GGUF + `presets.ini` + `cache/`).

### Offen für /deploy (kein Code)

- GGUF-Dateien beschaffen (q4_K_M, gleiche Quants) + `presets.ini` schreiben.
- `llama_api_key` erzeugen + in alle Konsumenten-`.env` eintragen.
- Cutover-Reihenfolge + Vorher/Nachher-Benchmark (§7 Tech Design).
- n8n-Workflows via `Deploy n8n-workflow {name}` (9×).

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
