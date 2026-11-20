# Product Requirements Document — Phase 4

> Phase 1 (PROJ-1–PROJ-39), Phase 2 (PROJ-40–PROJ-77) und Phase 3 (PROJ-78–PROJ-114) sind abgeschlossen.
> Phase-1-Roadmap → `docs/PRD.Phase1.md`
> Phase-2-Roadmap → `docs/PRD.Phase2.md`
> Phase-3-Roadmap → `docs/PRD.Phase3.md`
> Briefing dieser Phase → `docs/briefing.Phase4.md`
>
> **Status Phase 4:** Geplant am 2026-11-20 — Umbau: Quelle der Wahrheit, Microservices, Agent-Framework.

## Vision

Phase 4 ersetzt das gewachsene Fundament von Alice durch ein belastbares: Jedes Dokument, jede Mail und jedes Bild wird in eine **Markdown-Datei als Quelle der Wahrheit** überführt (Git-versioniert, für Menschen lesbar, von Hand korrigierbar). Alles Weitere — strukturierte Daten in PostgreSQL, der Weaviate-RAG-Index und ein vom lokalen LLM gepflegtes, verlinktes **LLM-Wiki** — wird daraus abgeleitet und ist jederzeit neu erzeugbar. Alle n8n-Workflows werden durch **Docker-Microservices** ersetzt, n8n entfällt. Ein neues **Agent-Framework** beantwortet DMS-Fragen mehrschrittig und zuverlässig und nutzt für tiefe, internetgestützte Recherchen ein **Cloud-Modell** — local-first, nicht local-only.

Ein vollständiger Neuaufbau aller Daten aus den Originalen ist ausdrücklich akzeptiert; das alte System läuft weiter, bis der Neuaufbau steht.

## Target Users

**Haushalt (Rolle `haushalt`, zwei Haushaltsmitglieder)**
- Beide haben identische Rechte: alle DMS-Dokumente, alle Postfächer, das gesamte Wiki — keine Unterscheidung untereinander
- Nutzen Chat und Sprache für Fragen an DMS, Mails, Wiki und für Recherchen

**Admin (Rolle `admin`)**
- Ein Haushaltsmitglied mit zusätzlichen Verwaltungsrechten (Nutzer, Ordner, Postfächer, Logs, ETL-Status, Neuaufbau)

**Gäste (Rolle `guest`)**
- Stark eingeschränkt wie bisher: kein Zugriff auf DMS, Mail und Wiki; nur freigegebene HA-Funktionen

**Schmerz Phase 4:** Der ETL erfüllt die Anforderungen nicht — die Wahrheit ist über Redis, Weaviate und NAS verstreut und driftet, Inhalte sind nicht lesbar oder korrigierbar. n8n-Workflows fallen immer wieder aus (Speicher, Timeouts, Loop-in-Loop-Aufteilungen, Fan-out). Mails sind ein Sonderweg, Anhänge kommen erst nach bis zu einem Tag im DMS an. Der Chat-Agent ist eine reaktive Tool-Schleife ohne Planung und beantwortet viele DMS-Fragen nicht sauber; Web-Recherche fehlt.

## Core Features (Roadmap Phase 4)

| Priority | Feature | Sub-Phase | Status |
| -------- | ------- | --------- | ------ |
| P0 | Rollenmodell Haushalt — `admin`/`haushalt`/`guest`, Rechte je Dokumenttyp und Postfach entfallen, `child` gestrichen (PROJ-121) | 4.1 | Planned |
| P0 | Quelle-der-Wahrheit-Repo + Quellen-Register — Git-versionierter NAS-Ordner, Markdown-/Frontmatter-Format, Register aller Quellen mit Verarbeitungszustand (PROJ-115) | 4.1 | Planned |
| P0 | Datei-Erkennung — Scan, Hash/Dedup, Verschieben/Umbenennen/Löschen; ersetzt Scanner, Path-Worker, Lifecycle, Reconcile (PROJ-116) | 4.1 | Roadmap |
| P0 | Text-Extraktion → Quell-Markdown (PROJ-117) | 4.1 | Roadmap |
| P0 | Klassifizierung + Feldextraktion ins Frontmatter, deutsche Zusammenfassung (PROJ-118) | 4.1 | Roadmap |
| P0 | Strukturierte Dokumentdaten in PostgreSQL, abgeleitet aus der Quell-Markdown (PROJ-119) | 4.1 | Roadmap |
| P0 | Neuaufbau + Vollständigkeitsabgleich (PROJ-120) | 4.1 | Roadmap |
| P0 | Spike Agent-Framework — DeepSeek Harness und Alternativen, Go/No-Go, DMS-Testkatalog (PROJ-133) | 4.4 | Roadmap |
| P1 | ETL-Status-Ansicht (Admin, WebApp) (PROJ-122) | 4.1 | Roadmap |
| P1 | Mail-Import in den ETL — `.eml` ohne Anhänge + Links, Mail-Markdown, Kategorie (PROJ-123) | 4.2 | Roadmap |
| P1 | Mail-Anhänge als Quelldokumente (PROJ-124) | 4.2 | Roadmap |
| P1 | Bilder in der Quelle der Wahrheit — Übernahme bestehender Beschreibungen (PROJ-125) | 4.2 | Roadmap |
| P1 | Vorschaubilder aus dem neuen ETL (PROJ-126) | 4.2 | Roadmap |
| P1 | RAG-Index aus der Quell-Markdown (PROJ-127) | 4.3 | Roadmap |
| P1 | Such-Tools als Service — Dokumente, Mails, Bilder (PROJ-128) | 4.3 | Roadmap |
| P1 | Wiki-Ingest — LLM-Pflege je neuer Quell-Markdown (PROJ-129) | 4.3 | Roadmap |
| P1 | Wiki-Lint nächtlich (PROJ-130) | 4.3 | Roadmap |
| P1 | Wiki-Ansicht in der WebApp (PROJ-131) | 4.3 | Roadmap |
| P1 | Wiki-Tool für den Agenten (PROJ-132) | 4.3 | Roadmap |
| P1 | Agent-Kern auf neuem Framework — ersetzt die Tool-Schleife in `alice-chat-stream` (PROJ-134) | 4.4 | Roadmap |
| P1 | Agent-Schritte im Chat sichtbar (PROJ-135) | 4.4 | Roadmap |
| P1 | Cloud-Recherche — Recherche-Sub-Agent, austauschbarer Provider, Start mit `claude -p` (PROJ-136) | 4.4 | Roadmap |
| P2 | Cloud-Provider per API mit Budget-Stopp, Freigabe für `haushalt` (PROJ-137) | 4.4 | Roadmap |
| P2 | Session-API + Session-Cleanup als Service (PROJ-138) | 4.5 | Roadmap |
| P2 | DMS-Ordner-API als Service (PROJ-139) | 4.5 | Roadmap |
| P2 | Postfach-API als Service (PROJ-140) | 4.5 | Roadmap |
| P2 | Modell-Warmup im LLM-Gateway (PROJ-141) | 4.5 | Roadmap |
| P2 | n8n-Abschaltung + Altbestand aufräumen (PROJ-142) | 4.5 | Roadmap |

Unterphasen: **4.1** ETL-Kern · **4.2** Mail und Bilder · **4.3** RAG und Wiki · **4.4** Agent-Framework · **4.5** n8n-Ablösung. Bau-Reihenfolge und Abhängigkeiten: `features/INDEX.md`.

### Produktentscheidungen

- **Quelle der Wahrheit:** eine Markdown-Datei je Quelldokument, Mail und Bild in einem eigenen, Git-versionierten NAS-Ordner; Originale bleiben unverändert an ihrem Ort. Der Mensch darf Quell-Markdowns von Hand korrigieren; die Pipeline übernimmt die Korrektur in DB, RAG und Wiki und überschreibt sie bei einem Neuaufbau nicht.
- **Mails:** gespeichert als `*.eml` ohne Anhänge, stattdessen mit Links auf die separat gespeicherten Anhangsdateien; Mailtext als Markdown; Anhänge sind eigene Quelldokumente mit Verweis auf die Mail.
- **Bilder:** Bild-Markdown mit Beschreibung, EXIF, Ort und Link aufs Original. Beim Neuaufbau werden die vorhandenen Beschreibungen übernommen; nur neue Bilder werden mit dem aktuellen Vision-Modell beschrieben (Neubeschreibung des Bestands = PROJ-114, zurückgestellt).
- **LLM-Wiki:** Seitentypen Personen, Organisationen, Verträge, Konten/Depots, Orte, Themen plus Index-Seiten. Jede neue Quell-Markdown löst einen Ingest im Hintergrund aus; ein nächtlicher Lint prüft Widersprüche, verwaiste Seiten und Links. Jede Aussage verlinkt auf ihre Quelle. Das Wiki ist reines LLM-Erzeugnis, in der WebApp nur lesbar; ein gemeinsames Wiki ohne gefilterte Sichten (Rollenmodell).
- **Agent-Framework:** Entscheidung per Spike (PROJ-133) mit Go/No-Go. Favorit DeepSeek Harness (MIT, TypeScript/Node, Developer Preview); Alternativen u. a. Pydantic AI, LangGraph, OpenAI Agents SDK, smolagents. Ausgeschlossen: Lösungen auf Basis von n8n. Kriterien: mehrschrittige Planung, Sub-Agents, Tools über MCP oder Python, SSE-Streaming zur WebApp, Sessions/Gedächtnis, Modellwahl je Aufgabe, lokaler llama.cpp über OpenAI-kompatible API hinter `alice-llm-gateway`, i18n der Ausgaben.
- **Multi-Model:** lokales LLM für alle ETL-Schritte und DMS-Analysen; Cloud-Modell nur für tiefergehende, internetgestützte Recherche. Cloud-Zugang austauschbar: Start mit dem unveränderten Claude Code CLI (`claude -p`) und dem Abo des Admins — nur für Anfragen des Admins; für weitere Haushaltsnutzer oder bei erreichten Limits per API mit Budget-Stopp (PROJ-137).
- **Sprache (Voice):** unverändert; lange Recherchen liefern per Sprache eine Kurzantwort mit Hinweis auf die WebApp.
- **WebApp:** neue bzw. geänderte Oberflächen — Wiki-Ansicht, ETL-Status (Admin), Agent-Schritte im Chat. Regeln: `docs/planning/frontend-design.md`, Abschnitt 9.

## Success Metrics

| Metrik | Zielwert |
| ------ | -------- |
| Vollständigkeit des Neuaufbaus | 100 % der Quelldateien, Mails und Bilder haben eine Quell-Markdown oder einen sichtbaren Fehlerstatus; Abgleich NAS/IMAP ↔ Quelle der Wahrheit findet 0 stille Lücken |
| Aktualität | neue Datei/Mail inkl. Anhänge in Quelle der Wahrheit, DB und RAG ≤ 15 min; im Wiki ≤ 24 h |
| Stabilität | 14 Tage ETL-Betrieb ohne manuellen Eingriff und ohne verlorene Elemente |
| DMS-Antwortqualität | ≥ 80 % korrekt mit Quellenangabe auf dem DMS-Testkatalog (~30 Fragen, Ausgangswert in PROJ-133 gemessen) |
| Wiki-Qualität | jede Wiki-Seite hat Quellenlinks; nächtlicher Lint findet 0 kaputte Links |
| n8n abgelöst | 0 aktive Workflows, n8n-Container entfernt |
| Datenschutz Cloud | 0 Cloud-Anfragen mit DMS-, Mail- oder Wiki-Inhalt ohne Freigabe (Protokoll der Cloud-Aufrufe) |
| Keine Regression | HA-Schnellpfad, Kalender, Listen, Timer funktionieren unverändert mit gleicher Antwortzeit |

## Constraints

- **Local-first, nicht local-only.** ETL, Wiki-Pflege und DMS-Analysen laufen ausschließlich lokal. Die Cloud sieht nur Recherche-Kontext (Frage, Web-Inhalte); DMS-, Mail- und Wiki-Inhalte gehen nur mit expliziter Freigabe pro Anfrage hinaus. Jeder Cloud-Aufruf wird protokolliert. Google-Agenten bleiben wie bisher (nur Live-Abfragen).
- **Cloud-Zugang:** `claude -p` (unverändertes Claude Code CLI) mit dem Abo des Admins nur für dessen eigene Anfragen — Anfragen anderer Nutzer laufen nicht über dieses Abo (Anthropic-Nutzungsbedingungen). Das Abo teilt sich sein Kontingent mit der Software Factory.
- **Hardware:** Ryzen 9 + RTX 3090 (`llama-3090`, ein Slot, teilt VRAM mit den Weaviate-Vektorisierern) + TITAN X (Speech). Chat und ETL konkurrieren um den Slot → `alice-llm-gateway` mit Prioritäten bleibt; Neuaufbau und Wiki-Pflege laufen als Hintergrundlast.
- **Neustart:** keine Migration der alten Weaviate-/Redis-Bestände nötig (Ausnahme: Übernahme der Bildbeschreibungen). Das alte System läuft parallel, bis der Neuaufbau steht; Abschaltung in PROJ-142.
- **Stack:** Python/FastAPI-Services, PostgreSQL, Redis, Weaviate, MQTT, Next.js (statischer Export), nginx bleiben. Neu: Git im Ordner der Quelle der Wahrheit; Claude Code CLI als Cloud-Zugang; ggf. Node/TypeScript-Runtime, falls der Spike das DeepSeek Harness wählt. n8n entfällt am Ende von 4.5. Keine neue Queue-/Event-Infrastruktur. Details: `docs/stack.md`.
- **Software Factory:** testet ohne GPU und ohne Produktivsysteme — lokales LLM, Cloud-LLM (`claude`-CLI und API) und Vision-Modell werden gemockt. Messungen gegen das produktive LLM (Ausgangswert und Vergleich im Spike PROJ-133, DMS-Testkatalog) führt der Mensch aus. Factory-Parallelität: höchstens zwei Läufe; nur PROJ-133 läuft parallel zur ETL-Kette.
- **Zugang:** nur über VPN.
- **Sprache:** primär Deutsch; LLM-Ausgaben in der Nutzersprache; Docs Deutsch, Code/Commits Englisch.
- **Team:** Solo-Projekt, Hobbyzeit (3–4 h/Tag).

## Non-Goals Phase 4

- Alle offenen Roadmap-Einträge aus Phase 3 bleiben zurückgestellt: PROJ-81, 89, 101, 102, 103, 104, 105, 107, 108, 109, 110, 114. PROJ-90 (Websearch-Agent) ist verworfen, ersetzt durch PROJ-136
- Keine Neubeschreibung des Bild-Bestands (PROJ-114)
- Keine Bearbeitung des Wikis in der WebApp; keine nach Rolle gefilterten Wiki-Sichten
- Keine Rechte je Dokumenttyp oder Postfach mehr; keine Rolle `child`
- Keine Migration der alten Weaviate-/Redis-Daten (außer Bildbeschreibungen)
- Keine neuen Funktionen für HA-Steuerung, Sprache, Kalender, Listen, Timer — nur Anbindung an das neue Agent-Framework
- Kein PROJ-45 Display Registry, kein PROJ-59 Finanzanalyse, kein PROJ-58 Sprache-vs-TV-Trennung

---

Use `/write-spec` to create detailed feature specifications for each item in the roadmap above.
