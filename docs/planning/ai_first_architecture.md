# KI-First & Sprache-First Architektur – Zusammenfassung und Projektfahrplan

## 1. Ausgangslage & Zielbild

Du möchtest deine gesamte Heim- und Automations-Architektur auf **KI-first** und **Sprache-first** umstellen. Die KI soll:

- zentraler Einstiegspunkt und Orchestrator für:
  - Smart-Home-Funktionen (Licht, Klima, Szenen, Geräte, Routinen)
  - persönliche Assistenten-Funktionalität (Fragen, Planungen, Zusammenfassungen)
  - Dokumentenmanagement (DMS)
  - Finanzthemen (Konten, Anlagen, Auswertungen)
  - Kalender & Mail
  - tagesaktuelle Informationen (Politik, Wissenschaft)
- primär über **Sprache** (In- und Output) angesprochen werden, ergänzt durch **Text-Chat**.
- unterschiedliche **Anzeigeziele** dynamisch ansteuern können:
  - Wallpanel (Tablet in der Küche)
  - TV-Gerät im Wohnzimmer
  - PC/Notebook
  - weitere Displays in Zukunft

Rahmenbedingungen:

- **Lokal-First**, von außen nur via **VPN** erreichbar.
- **Lokale KI bevorzugt**, Cloud-Modelle nur gezielt.
- Du nutzt bereits:
  - Headless-Server mit Ryzen 9 + RTX 3090 + TITAN X
  - Proxmox-Server mit Home Assistant, Pi-hole, InfluxDB, Grafana
  - Synology NAS für Daten/Backups
  - Docker-Stack mit Ollama, OpenWebUI, Whisper, Piper, Weaviate, Postgres, Redis, Mosquitto, n8n
- Du **liebst Bastelarbeit** und kannst sowohl Low-Code (n8n) als auch Code (Python, Docker) bedienen.
- Du planst **Sprechererkennung** für abgestufte Berechtigungen.

Ziel: **Ein einziger Assistent**, der aus verschiedenen Räumen und Geräten per Sprache nutzbar ist, und selbst entscheidet, _wo_ Inhalte angezeigt werden – ohne, dass du zwischen „Home Assistant“ oder „WebUI“ unterscheiden musst.


## 2. Zentrale Architekturprinzipien (KI-first & Sprache-first)

### 2.1 Ein Assistent, viele Ein- und Ausgänge

Statt separaten „Assistenten“ in Home Assistant und einer WebApp gibt es **einen zentralen Assistant Core**, der:

- alle Texteingaben (inkl. aus Sprache) verarbeitet,
- n8n + LLM als Orchestrierungs- und Denk-Schicht nutzt,
- selbst bestimmt, welche Geräte/Ausgaben genutzt werden (Audio + Displays).

**Konsequenz:**

- HA Voice, WebUI, zukünftige Clients sind nur **Eingabe-/Ausgabe-Endpoints**.
- Die KI-Logik sitzt **zentral**, nicht als Stückwerk in verschiedenen Systemen.


### 2.2 KI-First: KI entscheidet, Systeme sind Tools

Der Assistant Core nutzt andere Systeme als **Tools**:

- Home Assistant: Steuern von Lichtern, Szenen, Geräten, Sensoren.
- Weaviate/Postgres: Wissens-/Dokumenten- und Finanzdatenbank.
- Mail-/Kalender-Systeme: Kommunikation, Termine.
- Externe Feeds/APIs: aktuelle Informationen (News, Wissenschaft).

Die KI (LLM) entscheidet kontextbasiert:

- Welche Tools werden aufgerufen?
- Welche Daten werden kombiniert?
- Welche Ausgabeformen sind sinnvoll (gesprochene Antwort, Tabellen, Diagramme, Kurz-Zusammenfassung, Wissensartikel)?

Du musst also **nicht** mehr „in Systeme denken“ („Jetzt Home Assistant, dann WebUI“), sondern einfach in Aufgaben/Anweisungen.


### 2.3 Sprache-First: Sprache als primärer Interaktionskanal

Für dich ist **Sprache der zentrale Kanal**:

- Wakeword-aktivierte Geräte (Home Assistant Voice & zukünftige Satelliten)
- Sprach-Taste in Browser/WebUI (kein Wakeword nötig, Button-Start reicht)

Du sprichst in natürlichen Sätzen wie:

- „Dimme das Licht im Wohnzimmer auf 30 Prozent und zeig mir dazu die letzten Stromverbrauchsdaten auf dem Fernseher.“
- „Was habe ich im letzten Jahr für Versicherungen ausgegeben? Zeig mir das auf dem Wallpanel.“
- „Fass mir die wichtigsten politischen Nachrichten von heute zusammen und lies sie mir am Computer vor.“

Die KI interpretiert diese Sätze, orchestriert die Aktionen und wählt passende Ausgabeformen.


### 2.4 Display-Targets statt System-Auswahl

Du willst **nicht** manuell zwischen „Home Assistant“ oder „WebUI“ wählen, sondern Displays/Endgeräte benennen:

- „Wallpanel“ (Küche)
- „Fernseher im Wohnzimmer“
- „Mein Computer“

Dafür gibt es eine **Display-Registry** – eine Zuordnung von logischen Namen zu technischen Zielen:

| logical_name   | type     | room       | backend        | target_id                        |
|----------------|----------|-----------|----------------|----------------------------------|
| wallpanel      | display  | kitchen   | home_assistant | browser_mod.kueche_tablet        |
| wohnzimmer_tv  | display  | living    | home_assistant | media_player.wohnzimmer_tv       |
| pc_andreas     | browser  | office    | webapp         | client_id:andreas_pc             |

Die KI entscheidet: „Zeig X auf `wallpanel`“ – der Output-Router leitet je nach Backend an Home Assistant (z. B. browser_mod) oder WebApp weiter. Du musst nur „Wallpanel“, „TV“, „Computer“ sagen.


## 3. Rolle der Hauptkomponenten

### 3.1 Headless Server – AI Core & Backend-Services

**Rolle:** AI- und Service-Zentrale.

- LLMs (Ollama/ggf. zusätzliche Server auf beiden GPUs)
- STT/TTS (Whisper, Piper)
- n8n als Orchestrator
- Weaviate & Postgres & Redis
- Mosquitto (MQTT)
- nginx als Reverse Proxy und API-Gateway
- Spezialservices in Python (Speech-Gateway, DMS/Finanz-Ingestion)

Hier sitzt de facto dein „Rechenzentrum“ – alles lokal, mit starker GPU-Power.


### 3.2 Proxmox-Server – Smart-Home & Monitoring

**Rolle:** Smart-Home-Infrastruktur.

- Home Assistant Produktiv & Development
- Pi-hole (DNS/Adblock)
- InfluxDB & Grafana (Metriken, Energie, Monitoring)

Home Assistant bleibt die **Geräte- und Automationsschicht**:

- klassisches Licht/Heizung/Automationsverhalten
- Dashboards für Entitäten
- Home Assistant Voice-Geräte als Audio-I/O

Home Assistant ist dabei **nicht mehr der zentrale KI-Assistent**, sondern eines von mehreren Tools, die der Assistant Core benutzt.


### 3.3 Synology NAS – Datenhub & Backup

**Rolle:** Speicher & Archiv.

- Dokumentenablage: Kontoauszüge, Verträge, Schriftverkehr, Mails als PDF/EML
- Backups von:
  - Postgres
  - Weaviate
  - n8n (Workflows)
  - Konfigurationen von Home Assistant / Infrastruktur
- Multimedia (ggf. später für Foto-/Video-KI)

Die NAS ist dein „Langzeitgedächtnis“.


## 4. Speech-Gateway als Dreh- und Angelpunkt (Assist-Alternative)

### 4.1 Problem mit der klassischen Assist-Pipeline

Home Assistant Assist bringt zwar:

- Wakeword
- STT/TTS (via Wyoming/Whisper/Piper)
- Intent-/Conversation-Logik

…aber:

- die **Sprechererkennung** ist nicht integriert,
- die KI-/Orchestrierungs-Logik liegt innerhalb von HA und schwer erweiterbar,
- WebUI-Clients würden eine andere Pipeline nutzen (kein Wyoming), was zu zwei parallelen Welten führt.

Das widerspricht der Idee: „Ein Assistent, eine Logik, viele Clients“.


### 4.2 Lösung: Eigener Speech-Gateway-Service

Statt Assist als Herz der Sprachlogik zu nutzen, baust du einen **eigenen Speech-Gateway-Service** (z. B. in Python, Container auf dem Headless-Server).

Dieser Dienst bietet:

- nach außen:
  - **Wyoming-Interface** für HA-Voice/Assist-Geräte
  - **HTTP/WebSocket Interface** für WebUI & zukünftige Clients
- intern:
  - Audio→Whisper (STT)
  - Audio→Speaker-ID (Voice-Embeddings + Zuordnung zu User/Rollen)
  - Zusammenstellen eines Requests an n8n/Assistant Core
  - Texte→Piper (TTS)

**Ablauf HA Voice → Gateway → KI → HA Voice:**

1. Wakeword & Audio-Aufnahme auf HA-Voice-Gerät.
2. Audio als Wyoming-STT-Request an den Speech-Gateway.
3. Gateway: STT + Speaker-ID, Request an n8n (Text, Device-ID, Raum, Sprecher).
4. n8n + LLM planen Aktionen (Tools, Ziele, Anzeigen).
5. Antworttext zurück an Speech-Gateway.
6. Gateway: TTS via Piper und Audio zurück an HA-Voice-Gerät.
7. Optional: Anzeige an passende Displays (via HA/WebUI).

**Ablauf WebUI → Gateway → KI → WebUI:**

1. Button im Browser löst Audioaufnahme aus.
2. Audio per HTTP/WebSocket an Speech-Gateway.
3. Gateway: STT + Speaker-ID → Request an n8n.
4. n8n + LLM wie oben.
5. Antworttext & Display-Payload an WebUI.
6. Gateway/Backend: TTS-Audio an Browser, UI-Rendering in WebApp.

Damit haben **alle Clients denselben Pipeline-Kern** – und du kannst Sprechererkennung, Berechtigungen, Logging und Routing zentral handhaben.


## 5. n8n vs. Python – warum Hybrid statt „nur Python“?

### 5.1 Latenztreiber in deinem System

Die größten Latenzen entstehen bei:

- STT (Whisper)
- LLM-Berechnung
- TTS (Piper)
- ggf. aufwendigen DB/Weaviate-Abfragen

Der Overhead durch n8n (Workflow-Engine, JSON-Weitergabe, Logging) liegt meist im Bereich von **Millisekunden**, während STT/LLM/TTS oft **hundert bis mehrere hundert Millisekunden** benötigen.

Praktisch wirst du einen Unterschied von 50–200 ms zwischen „n8n-orchestriert“ und „komplett Python“ kaum spüren, wenn die **Gesamtzeit bei 2–5 s** liegt.


### 5.2 Stärken von n8n

- Extrem gut für **Orchestrierung**: HA, NAS, Weaviate, Postgres, Mail, Kalender, News, HTTP-APIs.
- **Low-/No-Code**: du kannst neue Flows schnell aufbauen, kombinieren, testen.
- **Visualisierung & Debugging**: Execution-History, Node-Level-Fehler-Analyse.
- Ideal für **wachsendes System** mit vielen Datenquellen & Use-Cases.

### 5.3 Stärken von Python

- Ideal für **Performance-kritische Spezialdienste**:
  - Speech-Gateway mit Audio-Streaming, Whisper-Anbindung, Speaker-ID.
  - DMS-/Finanz-Parsing (OCR, KI-gestützte Extraktion, Normalisierung).
- Volle Kontrolle für **kompliziertere Logik**,
- direkter Zugriff auf GPU-Libraries, ML-Frameworks, etc.

### 5.4 Empfehlung: n8n als Hirn, Python als Spezialwerkzeug

Statt „alles in Python“ oder „alles in n8n“:

- **n8n**:
  - KI-Orchestrierung, Toolauswahl, kombinierte Workflows.
  - High-Level-Prozesse (Hauslogik, DMS-Workflows, Finanzreports, News-Analysen).
- **Python-Services daneben**:
  - Speech-Gateway.
  - DMS-/Finanz-Ingestion (OCR, Parsing, Normalisierung).
  - ggf. spezielle HA-Integrationen mit höherem Durchsatz oder komplexer Logik.

So bekommst du die **Flexibilität von n8n** und die **Performance/Feinkontrolle von Python** – ohne die Komplexität eines komplett selbstgebauten Orchestrators.


## 6. Zielarchitektur in der Übersicht

### 6.1 Schichtenmodell

1. **Client-Schicht (Input/Output)**
   - HA-Voice-Geräte (Wakeword, Mikro, Speaker)
   - WebApp (PWA, Mobile-First) mit Mikro & Lautsprechern
   - weitere Voice-/Display-Clients in Zukunft

2. **Speech-Schicht**
   - zentraler **Speech-Gateway-Service** (Python)
   - STT (Whisper), Speaker-ID, TTS (Piper)

3. **KI-/Orchestrierungs-Schicht**
   - **n8n** mit:
     - LLM-Anbindung (Ollama lokal, optional Cloud)
     - Tool-Nodes für HA, DMS, Finanzen, Mail, Kalender, News
     - Display-Router

4. **System-/Daten-Schicht**
   - Home Assistant (Geräte, Automationen, Dashboards)
   - Weaviate (Vektorsuche für Dokumente & Mails)
   - Postgres (strukturierte Daten: Finanzen, Metadaten, User/Rollen)
   - NAS (Rohdokumente, Backups)
   - InfluxDB/Grafana (Messwerte, Energie, Monitoring)

### 6.2 Typische Flows

#### Sprach-Command über HA-Voice

1. Wakeword → Audioaufnahme (HA-Voice).
2. Audio → Speech-Gateway (Wyoming).
3. Gateway:
   - Whisper → Text,
   - Speaker-ID → User/Rolle,
   - Request → n8n.
4. n8n/LLM:
   - Intent erkennen (SmartHome, DMS, Finanzen, News),
   - Tools & Anzeigen planen.
5. Aktionen:
   - HA-Befehle (HTTP/Websocket),
   - DB-/Weaviate-Abfragen,
   - Anzeige-Targets setzen (Wallpanel/TV/PC).
6. Antworttext → Gateway → TTS → Audio zurück ans HA-Voice-Gerät.

#### Sprach-Command über WebApp

1. Button → Audioaufnahme im Browser.
2. Audio → Speech-Gateway (HTTP/WebSocket).
3. Gateway: Whisper + Speaker-ID → Request → n8n.
4. n8n/LLM wie oben.
5. Antwort zurück:
   - TTS-Audio → WebApp,
   - UI-Daten → WebApp für Tabellen, Diagramme, Dokumentansichten.


## 7. Projektfahrplan (Roadmap)

Die Roadmap ist auf etwa 6 Monate ausgelegt und in drei Phasen gegliedert.

### Phase 1 (Monat 1–2): Fundament & MVP

**Ziel:** Stabiler Kern mit n8n als Orchestrator und einfachem KI-Chat.

1. **AI-Core-Stack auf dem Headless-Server konsolidieren**
   - Docker-Network `ai-core` anlegen.
   - Services: n8n, Ollama (3090/TITAN), Whisper, Piper, Weaviate, Postgres, Redis, Mosquitto, nginx.
   - Basis-Monitoring (Prometheus/Grafana) für CPU/GPU/Memory.

2. **n8n als zentraler KI-Endpunkt**
   - Webhook `/webhook/chat` einrichten:
     - Input: Text + (optional) User/Device-Infos.
     - Output: Antworttext.
   - LLM-Node auf lokale Modelle legen, Fallback-Option für Cloud vorbereiten.

3. **WebApp-MVP (Text-Chat)**
   - Einfache PWA (React/Svelte/…): Eingabefeld, Antwortanzeige, primitive Session.
   - Auth nur rudimentär (z. B. ein Token), Zugriff nur über VPN.

4. **Einfache HA→n8n-Integration**
   - Test-Flow: HA-Button oder Intent, der Text an n8n schickt.
   - n8n steuert per HA-Node z. B. ein Licht oder eine Szene.

5. **DMS-Grundlage**
   - Einen NAS-Ordner (z. B. „Kontoauszüge“) regelmäßig in n8n scannen.
   - Neue Dateien per Pipeline (ggf. einfacher Text-Extractor) in Weaviate/Postgres eintragen.

**Ergebnis:**  
Du hast einen funktionierenden, zentralen KI-Chat via WebApp und eine erste Verbindung zwischen n8n und Home Assistant.


### Phase 2 (Monat 3–4): Sprache, Sprecher & Use-Case-Ausbau

**Ziel:** Sprache-First-Erfahrung und Sprechererkennung einführen, wichtige Use-Cases abdecken.

1. **Speech-Gateway (Python-Service)**
   - HTTP/WebSocket-API für WebApp-Audio.
   - Integration mit Whisper-Container (STT).
   - Integration mit Piper-Container (TTS).
   - Einfacher Request an n8n mit Text, Device-ID.

2. **Sprach-Chat in WebApp**
   - Button zum Starten/Stoppen der Aufnahme.
   - Audio an Speech-Gateway, Streaming- oder Chunk-Verarbeitung.
   - TTS-Audio als Antwort abspielen.

3. **Sprechererkennung integrieren**
   - Voice-Embedding-Modell als eigenen Container.
   - Enrollment-Flow: WebApp-Dialog, in dem du deine Stimme „einsprichst“.
   - Zuordnung Embedding ↔ User in Postgres-Tabelle.
   - Gateway bestimmt `speaker_id`, n8n leitet daraus `role` & Berechtigungen ab.

4. **Home Assistant Voice anbinden**
   - HA-Voice-Geräte so konfigurieren, dass sie den Speech-Gateway als Wyoming-STT/TTS-Server nutzen.
   - Erste End-to-End-Tests: „Wakeword → KI → Antwort & Aktion → TTS auf HA-Voice-Gerät“. 

5. **Finanzen & Mail Use-Cases**
   - Banken-CSV/PDF-Import: Python-Service oder n8n-Flow, der Daten in Postgres speichert.
   - Mail-IMAP-Connector in n8n:
     - wichtige Mails extrahieren, Metadaten in DB/Weaviate.
   - Erste Queries über WebApp/Sprachkommandos:
     - „Was waren meine größten Ausgaben im letzten Monat?“
     - „Gibt es wichtige ungelesene Mails?“

**Ergebnis:**  
Du kannst per Sprache über HA-Voice und WebApp mit deinem Assistenten sprechen, Sprecher werden erkannt, erste Finanz- und Mail-Funktionen stehen zur Verfügung.


### Phase 3 (Monat 5–6): Härtung, Anzeigen & Feinschliff

**Ziel:** Stabiler Dauerbetrieb, vielseitige Anzeigewege, Security & Monitoring.

1. **Display-Registry & Output-Router**
   - Tabelle/Config für Displays (Wallpanel, Wohnzimmer-TV, PC).
   - Output-Router in n8n, der je nach `display_target`:
     - Home Assistant (browser_mod/media_player/Entitäten) anspricht,
     - oder WebApp/WebSocket benachrichtigt.
   - Sprachkommandos testen: „… zeig mir das auf dem Wallpanel/TV/Computer“. 

2. **Security-Härtung**
   - TLS überall, wo sinnvoll (nginx fronten).
   - Auth für WebApp/n8n/Gateway (z. B. OAuth/JWT).
   - Rollen-/Rechte-Modell in Postgres: wer darf was?

3. **Monitoring & Logging**
   - n8n-Executions in zentraler DB, Fehler-Alarme.
   - Grafana-Dashboards für Latenz, Durchsatz, GPU-Auslastung, Anzahl KI-Calls.
   - Logging für kritische Aktionen (z. B. Heizungsänderungen, Türöffnungen).

4. **Automations-Refactoring**
   - Simple, deterministische Regeln weiter in Home Assistant belassen.
   - Komplexe, KI-gestützte Szenarien in n8n zentralisieren.
   - Doppellogik (z. B. gleiche Regel in HA & n8n) abbauen.

5. **Modellstrategie & Feintuning**
   - Evaluieren, welche Use-Cases mit kleinen lokalen Modellen gut funktionieren.
   - Optional gezielter Cloud-Einsatz für komplexe Aufgaben (nach eigenem Schalter).
   - ggf. Prompt-/Tool-Optimierung, um LLM-Entscheidungen robuster zu machen.

**Ergebnis:**  
Du hast ein stabil laufendes, KI-first und Sprache-first SmartHome-, DMS- und Finanzsystem, das lokal betrieben wird, Wakeword-Geräte, WebApp und mehrere Displays intelligent zusammenführt – mit einem zentralen Assistenten als Gehirn.


---

## 8. Nächste sinnvolle Detail-Schritte

Als nächste konkrete Vertiefungen bieten sich an:

1. **Design des Speech-Gateway-APIs**
   - konkrete Endpunkte, Payload-Formate, Fehlercodes.
2. **n8n-Blueprint für den zentralen Chat-Flow**
   - Nodes & Datenstrukturen, inkl. Rollenprüfung und Display-Routing.
3. **DMS/Finanz-Ingestion-Pipeline im Detail**
   - konkrete Tabellenstrukturen in Postgres,
   - Weaviate-Schema,
   - Beispiel-Flows für Dokumentenklassifizierung und -suche.

Diese Bausteine kannst du dann Schritt für Schritt mit deiner bestehenden Infrastruktur verheiraten.
