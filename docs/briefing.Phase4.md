# Briefing Phase 4 — Umbau: Quelle der Wahrheit, Microservices, Agent-Framework

## Ziel
Nach Phase 4 hat Alice ein belastbares Fundament statt gewachsener Workflows:
1. **Markdown als Quelle der Wahrheit:** Jedes Dokument mit Textinhalt (PDF, Office, TXT, OCR-Scan), jede Mail und
   jedes Bild (als Bildbeschreibung) wird in eine Markdown-Datei überführt. Alles Weitere wird daraus abgeleitet und
   ist jederzeit neu erzeugbar.
2. **LLM-Wiki:** Aus den Quell-Markdowns pflegt ein lokales LLM ein verlinktes Wiki (Personen, Organisationen,
   Verträge, Konten, Themen, Zeiträume/Ereignisse, Orte). Der Agent nutzt es als Wissensbasis; in der WebApp ist es
   lesbar.
3. **RAG aus der Quelle der Wahrheit:** Weaviate wird weiter bedient, aber aus den Markdown-Dateien statt aus Plaintext.
4. **Mail im ETL:** Mails werden als `*.eml` gespeichert — ohne Anhänge, stattdessen mit Link auf die separat
   gespeicherten Anhangsdateien. Mailtext und Anhänge laufen durch dieselbe Pipeline wie alle anderen Dokumente.
5. **Kein n8n mehr:** Alle n8n-Workflows sind durch Docker-Microservices ersetzt; der n8n-Container entfällt.
6. **Neues Agent-Framework mit Multi-Model:** lokales LLM für ETL und DMS-Analysen, Cloud-Modell für tiefe,
   internetgestützte Recherchen. DMS-Anfragen im Chat werden zuverlässig und mehrschrittig beantwortet.

## Warum jetzt
- **Der ETL erfüllt die Anforderungen nicht.** Wahrheit ist über Redis-Maps, Weaviate-Objekte und NAS verstreut und
  driftet (PROJ-113: Bilder nie in Redis, Pfadkorrektur nie gefeuert; PROJ-76/93: fehlende Übergaben, keine Thumbnails).
  Inhalte liegen nur in Weaviate; ein Property lässt sich nach Anlage nicht ändern (PROJ-55). Nichts ist für Menschen
  lesbar oder nachvollziehbar.
- **n8n fällt immer wieder aus.** Task-Runner-OOM, 3600-s-Timeout, axios-Crash bei LLM-Timeouts (PROJ-72, PROJ-53),
  „Expression exceeded memory limit“/HTTP 413 bei großen Bildern (PROJ-112), tausende parallele Executions bei
  MQTT-Fan-out (PROJ-113 BUG-3). Das Loop-in-Loop-Verbot zwang zu Aufteilungen wie `alice-dms-scanner` +
  `alice-dms-path-worker` und zu selbstaufrufenden Backfill-Ketten (PROJ-96).
- **Mail ist ein Sonderweg.** Anhänge gelangen nachts über das Dateisystem (`/mnt/nas/ai/<Typ>/`) in den DMS und warten
  bis zu einem Tag; Mails selbst existieren nur als Weaviate-Objekt.
- **Der Agent ist zu rudimentär.** `alice-chat-stream` ist eine reaktive Tool-Schleife (max. 4 Runden, keine Planung,
  keine Zerlegung, Tool-Ergebnisse gehen zwischen Turns verloren, enger Kontext). Viele DMS-Fragen werden nicht sauber
  beantwortet; Multi-Intent scheitert (PROJ-102); Websuche fehlt.

## Ideen / Wünsche

### ETL-Neubau (radikaler Umbau ausdrücklich erlaubt)
- Eine Pipeline für alle Quellen: NAS-Ordner (`alice.dms_watched_folders`) und IMAP-Postfächer.
- Stufen: Erkennen (Scan/Hash/Dedup) → Extrahieren (bestehende Extraktor-Container pdf/ocr/office/txt/image
  weiterverwenden, wo sinnvoll) → **Markdown erzeugen** (Inhalt + YAML-Frontmatter mit Quelle, Hash, Typ,
  Klassifikation, extrahierten Feldern) → Datenbankeinträge → Wiki-Pflege → RAG-Index → Thumbnails.
- Strukturierte Daten (Rechnungen, Kontoauszüge/Buchungen, Wertpapierabrechnungen, Verträge …) als Datenbankeinträge
  in PostgreSQL statt nur in Weaviate; Redis nur noch Queue/Lock, nicht mehr Wahrheit.
- Verarbeitungszustand je Quelldatei nachvollziehbar (welche Stufe, welcher Fehler, Retry).
- Löschen/Verschieben/Umbenennen von Quelldateien wird sauber durch alle abgeleiteten Daten propagiert.
- Kompletter Neuaufbau aller Daten (MD, DB, Wiki, Weaviate) aus den Originalen muss möglich sein — ist auch der Weg
  für den Start der Phase.

### Quelle der Wahrheit
- Ablage: eigener NAS-Ordner, **Git-versioniert**, damit LLM-Änderungen nachvollziehbar und rücksetzbar sind.
- Eine Markdown-Datei je Quelldokument / Mail / Bild; Originale bleiben unverändert an ihrem Ort.
- Mails: `*.eml` (ohne Anhänge, mit Links auf die separat gespeicherten Anhänge) + Markdown mit dem Mailtext.
  Anhänge werden eigene Quelldokumente mit Verweis auf die Mail.
- Bilder: Markdown mit Vision-Beschreibung, EXIF, Ort (Reverse-Geocoding) und Link aufs Original.

### LLM-Wiki
- Vom lokalen LLM aus den Quell-Markdowns gepflegt (anlegen, ergänzen, verlinken), Quellenangabe auf jeder Seite.
- Ebenfalls im Git-versionierten Bereich der Quelle der Wahrheit.
- Nutzung: Agent liest und navigiert das Wiki als Tool (zusätzlich zu RAG); WebApp bekommt eine Wiki-Ansicht.
- Berechtigungen (`alice.permissions_dms`, Postfach-Zugriff) müssen auch im Wiki gelten — offene Frage, wie
  (z. B. Seiten nur aus erlaubten Quellen).

### n8n → Microservices
- Jeder n8n-Workflow wird ein Python/FastAPI-Docker-Service (Stack bleibt), aufgeteilte Workflows werden wieder
  zusammengeführt (z. B. Scanner + Path-Worker, Processor + Classify + Language-Check).
- Betroffen (Stand heute): DMS (scanner, path-worker, processor, classify-document, language-check, lifecycle,
  reconcile, thumbnailer, Backfills, folder-api, folder-conflict-check), Mail (sync, attachment-processor,
  attachment-backfill, reconcile, api, tools), Session (session-api, session-cleanup), Tools (tool-search),
  Sonstiges (llm-model-warmup). Viele davon gehen im neuen ETL auf, statt 1:1 portiert zu werden.
- Robustheit: begrenzte Parallelität, Retries mit Backoff, Healthchecks, Metriken (Prometheus ist vorhanden).

### Agent-Framework & Multi-Model
- Anforderungen: mehrschrittige Planung, Sub-Agents, Tools über MCP oder Python, Streaming zur WebApp (SSE),
  Sessions/Gedächtnis, Modellwahl je Aufgabe/Sub-Agent, lokaler llama.cpp über OpenAI-kompatible API
  (hinter `alice-llm-gateway`), Cloud-Modell für Recherche, i18n der Ausgaben (Sprachsetting des Nutzers).
- **Kandidat 1: DeepSeek Harness (dsh)** — MIT, TypeScript/Node, Developer Preview (Breaking Changes, kein
  Security-Audit). Laut Doku: eigene OpenAI-kompatible Endpunkte, Anthropic u. a. als Provider, MCP-Client,
  Sub-Agents, Headless-/SDK-Server (JSON-RPC). Zu prüfen: Modellwahl je Sub-Agent, Einbindung in Auth/JWT und
  SSE-Stream, Betrieb im Docker-Netz, Stabilität.
- Weitere Open-Source-Alternativen prüfen (z. B. Pydantic AI, LangGraph, OpenAI Agents SDK, smolagents). Ausgeschlossen:
  Lösungen auf Basis von n8n.
- Vorgehen: **Evaluierungs-Spike mit Go/No-Go** als erstes Agent-Feature, danach Migration von `alice-chat-stream`.
- Multi-Model: lokal für alle ETL-Schritte und DMS-Analysen; Cloud nur für tiefergehende, internetgestützte
  Recherche/Analyse. „local-first“ heißt nicht „local-only“.

## Rahmen
- **Datenschutz Cloud:** Die Cloud sieht nur Recherche-Kontext (Frage, Web-Inhalte). DMS-, Mail- und Wiki-Inhalte
  bleiben lokal; Weitergabe nur mit expliziter Freigabe pro Anfrage. ETL läuft ausschließlich lokal.
- **Hardware:** RTX 3090 (llama.cpp, ein Slot, teilt VRAM mit Weaviate-Vektorisierern), TITAN X (Speech). Chat und ETL
  konkurrieren um den Slot → `alice-llm-gateway` mit Prioritäten bleibt; Wiki-Pflege und Neuaufbau laufen als
  Hintergrundlast.
- **Neustart erlaubt:** private Anwendung; vollständiger Neuaufbau der Daten ist akzeptabel, keine Datenmigration
  der alten Weaviate-/Redis-Bestände nötig.
- **Stack:** Python/FastAPI-Services, PostgreSQL, Redis, Weaviate, MQTT, Next.js, nginx bleiben. Neu ggf.: Git im
  Quelle-der-Wahrheit-Ordner, Agent-Framework (evtl. Node-Runtime), Cloud-LLM-API — Stack-Check in `/init`;
  in der Software Factory müssen Cloud-LLM und GPU-Modelle mockbar sein.
- **Zugang** weiterhin nur per VPN; Solo-Projekt, ca. 3–4 h/Tag.
- **Nicht Teil von Phase 4:** alle offenen Roadmap-Einträge aus Phase 3 (PROJ-81, 89, 90, 101–105, 107–110, 114)
  werden zurückgestellt; HA-Steuerung, Sprache, Kalender und Listen bleiben funktional wie sie sind (nur Anbindung an
  das neue Agent-Framework).

## Offene Fragen für /init
- Wiki-Struktur (Seitentypen, Granularität) und wie oft/auslösend gepflegt wird (pro neuem Dokument vs. nächtlich).
- Berechtigungen im Wiki (gemeinsames Wiki mit gefilterter Sicht vs. Wiki je Rolle).
- Welches Cloud-Modell/Provider; Kostenrahmen.
- Bauweise der Pipeline: ein Service mit Stufen-Workern oder ein Service je Stufe; Event-Bus MQTT vs. Redis-Queues.
- Reihenfolge: ETL zuerst oder Agent-Spike parallel.
- Was mit der bisherigen Bildsuche (`multi2vec-clip`) passiert.
