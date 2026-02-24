# AI-first & Speech-first architecture – rough concept 

## Dokumentstatus

| Attribut | Wert |
|----------|------|
| **Dokumenttyp** | Grobkonzept |
| **Version** | 1.0 |
| **Status** | Entwurf |
| **Nächster Schritt** | Phasenweise Überführung in Feinkonzepte |

Dieses Grobkonzept definiert die Gesamtarchitektur, Designprinzipien und den Umsetzungsfahrplan. Für jede Umsetzungsphase wird ein separates Feinkonzept erstellt, das technische Details, Konfigurationen und Implementierungsschritte enthält.

---

## Übersicht

Dieses Dokument fasst das vollständige Konzept für eine KI-zentrierte Smart-Home- und Personal-Assistant-Architektur zusammen. Es vereint Hardware-Infrastruktur, Software-Architektur, Storage-Design und einen konkreten Umsetzungsfahrplan.

---

## 1. Zielbild und Ausgangslage

### 1.1 Vision

Ein **einziger intelligenter Assistent**, der:

- aus verschiedenen Räumen und Geräten per Sprache nutzbar ist
- selbst entscheidet, wo Inhalte angezeigt werden
- ohne manuelle Unterscheidung zwischen „Home Assistant" oder „WebUI" funktioniert
- alle Domänen vereint: Smart Home, DMS, Finanzen, Kalender, Mail, News
- auch bei Teilausfällen grundlegende Funktionen bereitstellt

### 1.2 Kernfunktionen

Der Assistent orchestriert:

- **Smart-Home-Steuerung**: Licht, Klima, Szenen, Geräte, Routinen
- **Persönliche Assistenz**: Fragen, Planungen, Zusammenfassungen
- **Dokumentenmanagement (DMS)**: Kontoauszüge, Verträge, Schriftverkehr
- **Finanzen**: Konten, Anlagen, Auswertungen
- **Kommunikation**: Kalender & Mail
- **Information**: Tagesaktuelle Nachrichten (Politik, Wissenschaft)

### 1.3 Rahmenbedingungen

- **Lokal-First**: Nur via VPN von außen erreichbar
- **Lokale KI bevorzugt**, Cloud-Modelle nur gezielt
- **Sprechererkennung** für abgestufte Berechtigungen
- **Energiebewusst**: Idle-Strategien für GPU-Ressourcen
- **Multi-User-fähig**: Gleichzeitige Nutzung durch mehrere Personen

### 1.4 Vorhandene Infrastruktur

| System | Komponenten |
|--------|-------------|
| **Headless-Server** | Ryzen 9 + RTX 3090 + TITAN X Pascal |
| **Proxmox-Server** | Home Assistant, Pi-hole, InfluxDB, Grafana |
| **Synology NAS** | Daten/Backups |
| **Docker-Stack** | Ollama, OpenWebUI, Whisper, Piper, Weaviate, Postgres, Redis, Mosquitto, n8n |

---

## 2. Zentrale Architekturprinzipien

### 2.1 Ein Assistent, viele Ein- und Ausgänge

Statt separater Assistenten in verschiedenen Systemen gibt es **einen zentralen Assistant Core**, der:

- alle Texteingaben (inkl. aus Sprache) verarbeitet
- n8n + LLM als Orchestrierungs- und Denk-Schicht nutzt
- selbst bestimmt, welche Geräte/Ausgaben genutzt werden

**Konsequenz:** HA Voice, WebUI und zukünftige Clients sind nur Eingabe-/Ausgabe-Endpoints. Die KI-Logik sitzt zentral.

### 2.2 KI-First: KI entscheidet, Systeme sind Tools

Der Assistant Core nutzt andere Systeme als **Tools**:

| Tool | Funktion |
|------|----------|
| Home Assistant | Steuern von Lichtern, Szenen, Geräten, Sensoren |
| Weaviate/Postgres | Wissens-/Dokumenten- und Finanzdatenbank |
| Mail-/Kalender | Kommunikation, Termine |
| Externe APIs | Aktuelle Informationen (News, Wissenschaft) |

Die KI entscheidet kontextbasiert:
- Welche Tools werden aufgerufen?
- Welche Daten werden kombiniert?
- Welche Ausgabeformen sind sinnvoll?

### 2.3 Sprache-First: Sprache als primärer Interaktionskanal

**Sprache ist der zentrale Kanal:**

- Wakeword-aktivierte Geräte (Home Assistant Voice & Satelliten)
- Sprach-Taste in Browser/WebUI (Button-Start)

**Beispiele natürlicher Befehle:**

- „Dimme das Licht im Wohnzimmer auf 30 Prozent und zeig mir dazu die letzten Stromverbrauchsdaten auf dem Fernseher."
- „Was habe ich im letzten Jahr für Versicherungen ausgegeben? Zeig mir das auf dem Wallpanel."
- „Fass mir die wichtigsten politischen Nachrichten von heute zusammen und lies sie mir am Computer vor."

### 2.4 Display-Targets statt System-Auswahl

Statt manueller System-Auswahl werden **logische Gerätenamen** verwendet:

| logical_name | type | room | backend | target_id |
|--------------|------|------|---------|-----------|
| wallpanel | display | kitchen | home_assistant | browser_mod.kueche_tablet |
| wohnzimmer_tv | display | living | home_assistant | media_player.wohnzimmer_tv |
| pc_andreas | browser | office | webapp | client_id:andreas_pc |

Die KI entscheidet: „Zeig X auf wallpanel" – der Output-Router leitet je nach Backend weiter.

### 2.5 Graceful Degradation: Ausfallsicherheit durch Schichten

Das System muss auch bei Teilausfällen funktionsfähig bleiben. Dafür gilt das Prinzip der **gestuften Degradation**:

#### Degradationsstufen

| Stufe | Ausfall | Verfügbare Funktionen | Eingeschränkt |
|-------|---------|----------------------|---------------|
| **Vollbetrieb** | Keiner | Alle Funktionen | – |
| **Stufe 1** | Speech-Gateway | Text-Chat, HA-Automationen | Sprachsteuerung |
| **Stufe 2** | LLM/Ollama | HA-Automationen, einfache Intent-Erkennung via Regex | KI-Intelligenz, komplexe Anfragen |
| **Stufe 3** | n8n | HA-Automationen (lokal), manuelle Steuerung | Alle KI-Orchestrierung |
| **Stufe 4** | Weaviate/Postgres | Grundlegende Smart-Home-Steuerung | DMS, Finanzen, Kontext |
| **Notbetrieb** | Headless-Server komplett | Home Assistant standalone | Alles außer lokale HA-Funktionen |

#### Design-Prinzipien für Ausfallsicherheit

- **Home Assistant bleibt autonom**: Kritische Automationen (Heizung, Sicherheit) laufen lokal in HA, nicht in n8n
- **Timeout-basierte Fallbacks**: Reagiert eine Komponente nicht innerhalb definierter Zeit, wird die nächste Stufe aktiviert
- **Health-Checks**: Jede Komponente exponiert einen `/health`-Endpoint
- **Circuit-Breaker**: Nach wiederholten Fehlern wird eine Komponente temporär umgangen

---

## 3. Performance-Anforderungen

### 3.1 Latenz-Budgets

Für eine natürliche Sprach-Erfahrung sind strenge Latenz-Grenzen erforderlich:

| Phase | Ziel-Latenz | Maximum | Komponente |
|-------|-------------|---------|------------|
| Wakeword-Erkennung | < 200ms | 500ms | HA-Voice-Gerät |
| Audio-Übertragung | < 100ms | 200ms | Netzwerk |
| STT (Whisper) | < 500ms | 1.000ms | Speech-Gateway |
| Speaker-ID | < 200ms | 400ms | Speech-Gateway |
| LLM-Response (erste Token) | < 800ms | 1.500ms | Ollama |
| LLM-Response (komplett) | < 2.000ms | 4.000ms | Ollama |
| Tool-Ausführung (HA) | < 300ms | 500ms | n8n → HA |
| TTS (Piper) | < 300ms | 600ms | Speech-Gateway |
| Audio-Wiedergabe Start | < 100ms | 200ms | Client |
| **Gesamt: Wakeword → erste Audio-Antwort** | **< 2.000ms** | **< 3.500ms** | End-to-End |

### 3.2 Streaming-Strategie

Um die wahrgenommene Latenz zu reduzieren:

- **LLM-Streaming**: Tokens werden während der Generierung an TTS weitergeleitet
- **Chunk-basiertes TTS**: Piper generiert Audio satzweise, Wiedergabe startet vor Abschluss
- **Progressive UI-Updates**: WebApp zeigt Antwort während des Streamings

### 3.3 Monitoring der Latenz

- Prometheus-Metriken für jede Phase
- Grafana-Dashboard mit P50/P95/P99-Latenzen
- Alerting bei Überschreitung der Maximum-Werte

---

## 4. Hardware-Architektur

### 4.1 Ziel-Hardware

#### Mainboard: ASUS PRO WS X570-ACE

Workstation-Mainboard mit:
- 3× voll angebundene PCIe-Slots
- Optimale GPU-Aufteilung (3090 im x16, Titan X im x8)
- 2× M.2 Onboard + weitere über PCIe-Adapter

#### GPU-Slot-Belegung

| Slot | Modus | Karte |
|------|-------|-------|
| PCIEX16_1 (x16) | volle Bandbreite | **RTX 3090** (primäre KI-GPU) |
| PCIEX16_2 (x8) | ausreichend für ML | **Titan X (Pascal)** |
| PCIEX16_3 (x4) | Zusatz | **ICY BOX NVMe Adapter + 990 EVO** |

### 4.2 Storage-Design (Hot/Warm/Cold)

#### Speicherklassen

| Storage | Zweck | Anforderungen | Darf ausfallen? |
|---------|-------|---------------|-----------------|
| **Hot Storage** | Modelle, Vektoren, temporäre KI-Daten | Maximale Performance | JA |
| **Warm Storage** | Tägliche persistente Daten | NVMe-Mirror (ZFS RAID1) | NEIN |
| **Cold Storage** | Archiv, Backups (Synology) | Redundanzfokussiert | NEIN |

#### NVMe-Konfiguration

**Hot Storage (Samsung 980 Pro 1TB):**
- M.2 Slot 1 auf Mainboard, PCIe 4.0 x4
- KI-Modelle (Ollama, Whisper, Embeddings, Weaviate-Index)
- Container-Caches, Temp-Files, Pipelines

**Warm Storage (ZFS-Mirror):**
- Samsung MZVLW1T0HMLH (1TB) – Mainboard-Slot
- Samsung 990 EVO Plus (1TB) – PCIe-Adapter-Slot
- Ergibt ZFS RAID1 mit hoher Sicherheit + guter Performance

### 4.3 Energiemanagement

#### Stromverbrauch-Übersicht (geschätzt)

| Zustand | RTX 3090 | Titan X | Gesamt System |
|---------|----------|---------|---------------|
| Idle (Desktop) | ~15W | ~10W | ~80W |
| Idle (Modelle geladen) | ~30W | ~15W | ~100W |
| Aktive Inferenz | ~300W | ~200W | ~600W |
| Peak (beide GPUs voll) | ~350W | ~250W | ~750W |

#### Energiespar-Strategien

**Kurzfristig (Phase 1-2):**
- GPU-Monitoring in Grafana (Verbrauch, Temperatur, Auslastung)
- Bewusstsein für Baseline-Verbrauch schaffen

**Mittelfristig (Phase 3):**
- **Modell-Unloading**: Selten genutzte Modelle nach Timeout aus VRAM entladen
- **GPU-Affinity**: Whisper/Piper auf Titan X, LLM primär auf 3090
- **Batch-Verarbeitung**: DMS-Ingestion zu definierten Zeiten (nachts)

**Langfristig (nach Phase 3):**
- Evaluierung: Reicht eine GPU für den Normalbetrieb?
- Zweite GPU nur bei Bedarf aktivieren (nvidia-smi -i 1 -pm 0)

---

## 5. Software-Architektur

### 5.1 Schichtenmodell

```
┌─────────────────────────────────────────────────────────────┐
│  1. CLIENT-SCHICHT (Input/Output)                           │
│     • HA-Voice-Geräte (Wakeword, Mikro, Speaker)           │
│     • WebApp (PWA, Mobile-First)                            │
│     • Weitere Voice-/Display-Clients                        │
├─────────────────────────────────────────────────────────────┤
│  2. SPEECH-SCHICHT                                          │
│     • Zentraler Speech-Gateway-Service (Python)             │
│     • STT (Whisper), Speaker-ID, TTS (Piper)               │
├─────────────────────────────────────────────────────────────┤
│  3. KI-/ORCHESTRIERUNGS-SCHICHT                            │
│     • n8n mit LLM-Anbindung (Ollama lokal, optional Cloud) │
│     • Tool-Nodes für HA, DMS, Finanzen, Mail, Kalender     │
│     • Display-Router, Kontext-Manager                       │
├─────────────────────────────────────────────────────────────┤
│  4. SYSTEM-/DATEN-SCHICHT                                   │
│     • Home Assistant (Geräte, Automationen)                 │
│     • Weaviate (Vektorsuche), Postgres (strukturierte Daten)│
│     • Redis (Sessions, Cache, Kontext)                      │
│     • NAS (Rohdokumente, Backups)                          │
│     • InfluxDB/Grafana (Monitoring)                         │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Rolle der Hauptkomponenten

#### Headless Server – AI Core & Backend-Services

- LLMs (Ollama auf beiden GPUs)
- STT/TTS (Whisper, Piper)
- n8n als Orchestrator
- Weaviate, Postgres, Redis, Mosquitto
- nginx als Reverse Proxy und API-Gateway
- Python-Spezialdienste (Speech-Gateway, DMS-Ingestion)

#### Proxmox-Server – Smart-Home & Monitoring

- Home Assistant (Produktiv & Development)
- Pi-hole (DNS/Adblock)
- InfluxDB & Grafana

Home Assistant bleibt die **Geräte- und Automationsschicht**, ist aber nicht mehr der zentrale KI-Assistent. Kritische Automationen verbleiben lokal in HA für Ausfallsicherheit.

#### Synology NAS – Datenhub & Backup

- Dokumentenablage (Kontoauszüge, Verträge, Mails)
- Backups von Postgres, Weaviate, n8n, Konfigurationen
- Multimedia (ggf. später für Foto-/Video-KI)

### 5.3 Speech-Gateway als Dreh- und Angelpunkt

#### Problem mit klassischer Assist-Pipeline

Home Assistants Assist-Pipeline bietet zwar Wakeword, STT/TTS und Intent-Logik, aber:
- Sprechererkennung ist nicht integriert
- KI-/Orchestrierungs-Logik liegt innerhalb von HA und ist schwer erweiterbar
- WebUI-Clients würden eine andere Pipeline nutzen

#### Lösung: Eigener Speech-Gateway-Service

Ein Python-Service mit:

**Nach außen:**
- Wyoming-Interface für HA-Voice/Assist-Geräte
- HTTP/WebSocket Interface für WebUI & zukünftige Clients

**Intern:**
- Audio → Whisper (STT)
- Audio → Speaker-ID (Voice-Embeddings)
- Request → n8n/Assistant Core
- Text → Piper (TTS)

### 5.4 Sprechererkennung (Speaker-ID)

#### Technische Grundlage

| Aspekt | Entscheidung | Begründung |
|--------|--------------|------------|
| **Embedding-Modell** | ECAPA-TDNN (SpeechBrain) | State-of-the-art, gute Performance, Open Source |
| **Alternative** | Resemblyzer | Leichtgewichtiger, einfachere Integration |
| **Embedding-Dimension** | 192 (ECAPA) oder 256 (Resemblyzer) | Kompakt genug für schnellen Vergleich |
| **Ähnlichkeitsmetrik** | Cosine Similarity | Standard für Speaker Verification |

#### Enrollment-Prozess

1. **Initiierung**: User startet Enrollment in WebApp oder per Sprachbefehl
2. **Sample-Aufnahme**: 5-10 Sprachproben à 3-5 Sekunden
   - Unterschiedliche Sätze für Varianz
   - Hinweis auf ruhige Umgebung
3. **Embedding-Generierung**: Jede Probe wird zu Embedding verarbeitet
4. **Aggregation**: Durchschnitts-Embedding aus allen Proben
5. **Speicherung**: Embedding + Metadaten in Postgres
6. **Validierung**: Test-Erkennung mit neuer Probe

#### Erkennungs-Logik

```
Audio-Input
    ↓
Embedding generieren
    ↓
Vergleich mit allen registrierten Sprechern (Cosine Similarity)
    ↓
┌─────────────────────────────────────────┐
│ Similarity ≥ 0.75 → Sprecher erkannt    │
│ Similarity 0.50-0.75 → Unsicher         │
│ Similarity < 0.50 → Unbekannt           │
└─────────────────────────────────────────┘
    ↓
Rolle zuweisen (Admin/User/Guest/Unknown)
```

#### Umgang mit unbekannten Sprechern

| Situation | Verhalten |
|-----------|-----------|
| **Unbekannt, Similarity < 0.50** | Gast-Rolle, nur unkritische Funktionen |
| **Unsicher, Similarity 0.50-0.75** | Rückfrage: „Bist du [Name]?" oder Gast-Rolle |
| **Neuer Sprecher möchte sich registrieren** | Erfordert Bestätigung durch Admin (Sprache oder App) |

#### Rollen und Berechtigungen (Grobkonzept)

| Rolle | Smart Home | DMS/Finanzen | System |
|-------|------------|--------------|--------|
| **Admin** | Alles | Alles | Konfiguration, Enrollment |
| **User** | Alles | Eigene Daten | Keine Systemänderungen |
| **Guest** | Licht, Musik | Keine | Keine |
| **Unknown** | Nur Statusabfragen | Keine | Keine |

### 5.5 Kontext-Management

#### Warum Kontext wichtig ist

Ohne Kontext versteht der Assistent keine Folgebefehle:
- „Mach das Licht an" → Welches Licht?
- „Zeig mir mehr davon" → Wovon?
- „Nochmal, aber lauter" → Was nochmal?

#### Kontext-Architektur

**Session-Konzept:**

| Attribut | Wert |
|----------|------|
| **Session-Start** | Erstes Wakeword / Erstes Audio |
| **Session-Ende** | 5 Minuten Inaktivität oder explizites „Danke" / „Tschüss" |
| **Session-ID** | UUID, verknüpft mit Device + Speaker |
| **Speicherort** | Redis (TTL: 30 Minuten) |

**Kontext-Datenstruktur:**

```json
{
  "session_id": "uuid",
  "speaker_id": "andreas",
  "device_id": "ha_voice_wohnzimmer",
  "room": "wohnzimmer",
  "started_at": "2025-01-15T14:30:00Z",
  "last_activity": "2025-01-15T14:32:15Z",
  "conversation": [
    {
      "role": "user",
      "content": "Wie ist das Wetter morgen?",
      "timestamp": "..."
    },
    {
      "role": "assistant", 
      "content": "Morgen wird es sonnig bei 12 Grad.",
      "timestamp": "..."
    }
  ],
  "entities": {
    "last_room_mentioned": "wohnzimmer",
    "last_device_mentioned": "deckenlampe",
    "last_topic": "wetter"
  },
  "display_target": "wallpanel"
}
```

#### Anaphern-Auflösung

Der Kontext-Manager löst Referenzen auf:

| Eingabe | Auflösung |
|---------|-----------|
| „Mach das Licht an" | → Licht im aktuellen Raum (aus device_id) |
| „Mach es heller" | → last_device_mentioned aus Kontext |
| „Zeig das auf dem TV" | → Referenz auf letzte generierte Anzeige |
| „Noch 5 Grad wärmer" | → Heizung im aktuellen Raum + relative Änderung |

#### Persistenter Kontext vs. Session-Kontext

| Typ | Speicherort | TTL | Inhalt |
|-----|-------------|-----|--------|
| **Session** | Redis | 30 min | Aktuelle Konversation, temporäre Referenzen |
| **User-Präferenzen** | Postgres | Permanent | Bevorzugte Temperatur, Lichtstärke, Routinen |
| **Langzeit-Gedächtnis** | Weaviate | Permanent | Wichtige Fakten, extrahiert aus Gesprächen |

### 5.6 Multi-User-Handling

#### Szenarien

| Szenario | Lösung |
|----------|--------|
| **Gleichzeitige Anfragen, verschiedene Räume** | Parallelverarbeitung, getrennte Sessions |
| **Gleichzeitige Anfragen, selber Raum** | Queue mit FIFO, Audio-Feedback „Einen Moment" |
| **Konflikt: User A sagt „Licht an", User B sagt „Licht aus"** | Priorität nach Rolle, dann First-Come |
| **Gemeinsamer Kontext (z.B. Film schauen)** | Shared-Session-Modus (explizit aktiviert) |

#### Request-Queue

```
┌─────────────────────────────────────────────┐
│  Eingehende Requests                        │
│  ┌─────┐ ┌─────┐ ┌─────┐                   │
│  │ R1  │ │ R2  │ │ R3  │                   │
│  └──┬──┘ └──┬──┘ └──┬──┘                   │
│     │       │       │                       │
│     ▼       ▼       ▼                       │
│  ┌─────────────────────────────────────┐   │
│  │  Request-Router                      │   │
│  │  • Raum ermitteln                   │   │
│  │  • Speaker-ID prüfen                │   │
│  │  • Queue zuweisen                   │   │
│  └─────────────────────────────────────┘   │
│     │           │           │               │
│     ▼           ▼           ▼               │
│  [Queue A]   [Queue B]   [Queue C]         │
│  Wohnzimmer  Küche       Büro              │
└─────────────────────────────────────────────┘
```

#### Konfliktauflösung

Prioritätsreihenfolge bei widersprüchlichen Befehlen:

1. **Sicherheitskritisch** (Alarm, Türen) → Immer Vorrang
2. **Admin-Rolle** → Vor User/Guest
3. **Zeitstempel** → First-Come-First-Served
4. **Explizite Bestätigung** → Bei echtem Konflikt nachfragen

---

## 6. Datenarchitektur

### 6.1 Weaviate-Schema (Entwurf)

#### Collection: Document

```json
{
  "class": "Document",
  "description": "Dokumente aus DMS (PDFs, Scans, etc.)",
  "vectorizer": "text2vec-transformers",
  "properties": [
    {"name": "title", "dataType": ["text"]},
    {"name": "content", "dataType": ["text"]},
    {"name": "summary", "dataType": ["text"]},
    {"name": "doc_type", "dataType": ["text"], "description": "invoice, contract, letter, bank_statement"},
    {"name": "source_path", "dataType": ["text"]},
    {"name": "doc_date", "dataType": ["date"]},
    {"name": "ingested_at", "dataType": ["date"]},
    {"name": "sender", "dataType": ["text"]},
    {"name": "tags", "dataType": ["text[]"]},
    {"name": "owner", "dataType": ["text"], "description": "User-ID"}
  ]
}
```

#### Collection: Transaction

```json
{
  "class": "Transaction",
  "description": "Finanztransaktionen",
  "vectorizer": "text2vec-transformers",
  "properties": [
    {"name": "description", "dataType": ["text"]},
    {"name": "amount", "dataType": ["number"]},
    {"name": "currency", "dataType": ["text"]},
    {"name": "tx_date", "dataType": ["date"]},
    {"name": "category", "dataType": ["text"]},
    {"name": "account", "dataType": ["text"]},
    {"name": "counterparty", "dataType": ["text"]},
    {"name": "tx_type", "dataType": ["text"], "description": "income, expense, transfer"},
    {"name": "source_document", "dataType": ["Document"]}
  ]
}
```

#### Collection: Mail

```json
{
  "class": "Mail",
  "description": "E-Mails",
  "vectorizer": "text2vec-transformers",
  "properties": [
    {"name": "subject", "dataType": ["text"]},
    {"name": "body", "dataType": ["text"]},
    {"name": "summary", "dataType": ["text"]},
    {"name": "sender", "dataType": ["text"]},
    {"name": "recipients", "dataType": ["text[]"]},
    {"name": "received_at", "dataType": ["date"]},
    {"name": "folder", "dataType": ["text"]},
    {"name": "is_important", "dataType": ["boolean"]},
    {"name": "action_required", "dataType": ["boolean"]},
    {"name": "tags", "dataType": ["text[]"]}
  ]
}
```

#### Collection: ConversationMemory

```json
{
  "class": "ConversationMemory",
  "description": "Langzeit-Erinnerungen aus Gesprächen",
  "vectorizer": "text2vec-transformers",
  "properties": [
    {"name": "fact", "dataType": ["text"]},
    {"name": "context", "dataType": ["text"]},
    {"name": "speaker_id", "dataType": ["text"]},
    {"name": "learned_at", "dataType": ["date"]},
    {"name": "confidence", "dataType": ["number"]},
    {"name": "source_session", "dataType": ["text"]}
  ]
}
```

### 6.2 Postgres-Schema (Entwurf)

#### Tabelle: speakers

```sql
CREATE TABLE speakers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user',
    embedding VECTOR(192),  -- pgvector für ECAPA-TDNN
    created_at TIMESTAMP DEFAULT NOW(),
    last_seen TIMESTAMP,
    preferences JSONB DEFAULT '{}'
);
```

#### Tabelle: sessions

```sql
CREATE TABLE sessions (
    id UUID PRIMARY KEY,
    speaker_id UUID REFERENCES speakers(id),
    device_id VARCHAR(100),
    room VARCHAR(50),
    started_at TIMESTAMP DEFAULT NOW(),
    ended_at TIMESTAMP,
    conversation JSONB DEFAULT '[]'
);
```

#### Tabelle: devices

```sql
CREATE TABLE devices (
    id VARCHAR(100) PRIMARY KEY,
    logical_name VARCHAR(50) UNIQUE,
    device_type VARCHAR(20),
    room VARCHAR(50),
    backend VARCHAR(20),
    target_id VARCHAR(200),
    capabilities JSONB DEFAULT '[]'
);
```

#### Tabelle: permissions

```sql
CREATE TABLE permissions (
    id SERIAL PRIMARY KEY,
    role VARCHAR(20) NOT NULL,
    resource VARCHAR(100) NOT NULL,
    action VARCHAR(50) NOT NULL,
    allowed BOOLEAN DEFAULT true,
    UNIQUE(role, resource, action)
);
```

---

## 7. Workflow-Versionierung und Deployment

### 7.1 n8n-Workflow-Management

#### Versionierung

| Aspekt | Lösung |
|--------|--------|
| **Repository** | Git-Repository für n8n-Workflows |
| **Export-Format** | JSON (n8n-native) |
| **Branching** | main (Produktion), develop (Test) |
| **Commit-Strategie** | Ein Commit pro Workflow-Änderung mit Beschreibung |

#### Workflow-Struktur im Repository

```
n8n-workflows/
├── core/
│   ├── chat-main.json
│   ├── intent-router.json
│   └── display-router.json
├── integrations/
│   ├── homeassistant/
│   │   ├── light-control.json
│   │   └── climate-control.json
│   ├── dms/
│   │   ├── document-ingestion.json
│   │   └── document-search.json
│   └── finance/
│       ├── transaction-import.json
│       └── expense-report.json
├── utils/
│   ├── error-handler.json
│   └── notification.json
└── README.md
```

### 7.2 Deployment-Strategie

#### Staging-Umgebung

- Zweite n8n-Instanz (n8n-staging) auf dem Headless-Server
- Eigene Datenbank (postgres_n8n_staging)
- Test-Webhook-URLs (/webhook-test/...)

#### Deployment-Prozess

1. Änderung in develop-Branch committen
2. In n8n-staging importieren und testen
3. Review (Funktionalität, Fehlerbehandlung)
4. Merge in main
5. Import in n8n-production
6. Smoke-Test mit definierten Test-Cases

#### Rollback

- Bei Fehler: Vorherige Version aus Git-History exportieren
- In n8n importieren (überschreibt aktuelle Version)
- Alternativ: Workflow deaktivieren, Fallback-Workflow aktivieren

---

## 8. Typische Flows

### 8.1 Sprach-Command über HA-Voice

1. Wakeword → Audioaufnahme (HA-Voice)
2. Audio → Speech-Gateway (Wyoming)
3. Gateway: Whisper → Text, Speaker-ID → User/Rolle, Session laden/erstellen
4. Request → n8n mit Text, Speaker, Rolle, Session-ID, Device-ID
5. n8n: Kontext anreichern, Intent erkennen, Tools & Anzeigen planen
6. Aktionen: HA-Befehle, DB-Abfragen, Anzeige-Targets setzen
7. Kontext aktualisieren (Redis)
8. Antworttext → Gateway → TTS → Audio zurück ans HA-Voice-Gerät

### 8.2 Sprach-Command über WebApp

1. Button → Audioaufnahme im Browser
2. Audio → Speech-Gateway (HTTP/WebSocket)
3. Gateway: Whisper + Speaker-ID → Session laden/erstellen
4. Request → n8n wie oben
5. Antwort: TTS-Audio → WebApp, UI-Daten für Tabellen/Diagramme
6. Progressive Updates während LLM-Streaming

### 8.3 Fallback bei Teilausfall

1. Request kommt an Speech-Gateway
2. Gateway: Health-Check auf n8n → Timeout
3. Fallback: Regex-basierte Intent-Erkennung im Gateway
4. Einfache Befehle (Licht an/aus) direkt an HA-API
5. Komplexe Befehle: „Entschuldigung, der Assistent ist gerade eingeschränkt verfügbar. Einfache Befehle funktionieren weiterhin."

---

## 9. Roadmap

### Übersicht

| Phase | Zeitraum | Schwerpunkt |
|-------|----------|-------------|
| **Phase 0** | Vorbereitung | Hardware-Umbau, Storage-Setup |
| **Phase 1** | Monat 1–2 | Fundament & MVP |
| **Phase 2** | Monat 3–4 | Sprache, Sprecher, Use-Cases |
| **Phase 3** | Monat 5–6 | Härtung, Multi-User, Monitoring |

Für jede Phase wird ein **separates Feinkonzept** erstellt, das folgende Elemente enthält:
- Detaillierte technische Spezifikationen
- Konkrete Konfigurationen und Code-Beispiele
- Testfälle und Akzeptanzkriterien
- Abhängigkeiten und Risiken

---

### Phase 0: Hardware-Umbau & Storage-Vorbereitung

**Ziel:** Basis modernisieren, Storage sauber trennen, GPUs optimal nutzen

#### Schritte

1. **OS-Migration vorbereiten**
   - /-Partition verkleinern oder Backup
   - Neue SSD für OS definieren (z. B. 250GB SATA oder NVMe)
   - Bootloader sichern

2. **OS auf dedizierte System-SSD verschieben**
   - Partitionen kopieren
   - fstab aktualisieren
   - Boot-Test durchführen

3. **Hardware-Umbau**
   - Altes Board ausbauen, neues ASUS X570-ACE einbauen
   - RTX 3090 in x16 Slot 1
   - Titan X in x8 Slot 2
   - ICY BOX Adapter installieren & 990 EVO einsetzen

4. **Storage einrichten**
   - Warm-Storage: `zpool create mirror warm nvmeX nvmeY`, Mount `/srv/warm`
   - Hot-Storage: 980 Pro formatieren, `/srv/hot` + Docker-Cache + Model-Speicher

5. **Basis-Energiemonitoring**
   - nvidia-smi Exporter oder DCGM-Exporter einrichten
   - Grafana-Dashboard für GPU-Watt, Temperatur

6. **Validierung**
   - Systemstart testen
   - Docker/LLMs/n8n validieren
   - Baseline-Stromverbrauch dokumentieren

#### Feinkonzept-Inhalte (zu erstellen)
- Partitionierungsschema
- ZFS-Pool-Konfiguration
- Mount-Punkte und fstab
- Docker-Volume-Mapping

---

### Phase 1 (Monat 1–2): Fundament & MVP

**Ziel:** Stabiler Kern mit n8n als Orchestrator und einfachem KI-Chat

#### Schritte

1. **AI-Core-Stack konsolidieren**
   - Docker-Network `ai-core` anlegen
   - Services: n8n, Ollama, Whisper, Piper, Weaviate, Postgres, Redis, Mosquitto, nginx
   - Basis-Monitoring (Prometheus/Grafana)

2. **n8n als zentraler KI-Endpunkt**
   - Webhook `/webhook/chat` einrichten
   - LLM-Node auf lokale Modelle legen
   - Fehlerbehandlung und Timeout-Logik

3. **Weaviate-Schema initialisieren**
   - Collections Document, Transaction, Mail anlegen
   - Test-Daten importieren

4. **Postgres-Schema initialisieren**
   - Tabellen speakers, sessions, devices, permissions anlegen
   - pgvector-Extension aktivieren

5. **WebApp-MVP (Text-Chat)**
   - Einfache PWA: Eingabefeld, Antwortanzeige, primitive Session
   - Zugriff nur über VPN

6. **Einfache HA→n8n-Integration**
   - Test-Flow: HA-Button/Intent → n8n → Licht/Szene steuern

7. **DMS-Grundlage**
   - NAS-Ordner regelmäßig in n8n scannen
   - Neue Dateien in Weaviate/Postgres eintragen

8. **Latenz-Baseline messen**
   - End-to-End-Latenz für Text-Chat dokumentieren
   - Prometheus-Metriken für n8n-Execution-Time

9. **Workflow-Versionierung einrichten**
   - Git-Repository für n8n-Workflows
   - Erste Workflows committen

#### Ergebnis
Funktionierender KI-Chat via WebApp, erste HA-n8n-Verbindung, Datenbank-Grundstruktur

#### Feinkonzept-Inhalte (zu erstellen)
- Docker-Compose für AI-Core-Stack
- n8n-Workflow-Blueprints
- API-Spezifikation für Chat-Webhook
- Weaviate/Postgres-Initialisierungsskripte

---

### Phase 2 (Monat 3–4): Sprache, Sprecher & Use-Case-Ausbau

**Ziel:** Sprache-First-Erfahrung und Sprechererkennung

#### Schritte

1. **Speech-Gateway (Python-Service)**
   - HTTP/WebSocket-API für WebApp-Audio
   - Whisper-Integration (STT), Piper-Integration (TTS)
   - Request an n8n mit Text, Device-ID
   - Health-Endpoint für Monitoring

2. **Latenz-Optimierung**
   - Streaming-Pipeline: LLM → TTS
   - Chunk-basierte Audio-Generierung
   - Latenz-Metriken pro Phase

3. **Sprach-Chat in WebApp**
   - Button für Aufnahme-Start/Stopp
   - Audio an Speech-Gateway, TTS-Audio als Antwort
   - Progressive UI-Updates während Streaming

4. **Sprechererkennung integrieren**
   - ECAPA-TDNN oder Resemblyzer als Container
   - Enrollment-Flow in WebApp (5-10 Samples)
   - Zuordnung Embedding ↔ User in Postgres
   - Confidence-Thresholds implementieren

5. **Kontext-Management implementieren**
   - Session-Handling in Redis
   - Kontext-Datenstruktur definieren
   - Anaphern-Auflösung in n8n-Workflow

6. **Home Assistant Voice anbinden**
   - Speech-Gateway als Wyoming-STT/TTS-Server konfigurieren
   - End-to-End-Tests: Wakeword → KI → Antwort → TTS

7. **Finanzen & Mail Use-Cases**
   - Banken-CSV/PDF-Import
   - Mail-IMAP-Connector in n8n
   - Erste Queries: „Größte Ausgaben?", „Wichtige Mails?"

8. **Fallback-Logik implementieren**
   - Health-Checks für alle Komponenten
   - Timeout-basierte Degradation
   - Einfache Regex-Intents als Fallback

#### Ergebnis
Sprachsteuerung über HA-Voice und WebApp, Sprechererkennung, Kontext-Awareness, erste Finanz-/Mail-Funktionen, Fallback bei Teilausfällen

#### Feinkonzept-Inhalte (zu erstellen)
- Speech-Gateway API-Spezifikation
- Speaker-ID Enrollment-Protokoll
- Kontext-Datenmodell
- Fallback-Entscheidungsbaum

---

### Phase 3 (Monat 5–6): Härtung, Multi-User & Feinschliff

**Ziel:** Stabiler Dauerbetrieb, Multi-User-Fähigkeit, Security

#### Schritte

1. **Display-Registry & Output-Router**
   - Tabelle/Config für Displays
   - Output-Router in n8n für verschiedene Backends
   - Tests: „zeig mir das auf dem Wallpanel/TV/Computer"

2. **Multi-User-Handling**
   - Request-Queue pro Raum
   - Konfliktauflösung implementieren
   - Shared-Session-Modus für gemeinsame Aktivitäten

3. **Security-Härtung**
   - TLS überall (nginx)
   - Auth für WebApp/n8n/Gateway (OAuth/JWT)
   - Rollen-/Rechte-Modell in Postgres aktivieren
   - Berechtigungsprüfung in n8n-Workflows

4. **Monitoring & Logging**
   - n8n-Executions in zentraler DB, Fehler-Alarme
   - Grafana-Dashboards für Latenz (P50/P95/P99), GPU-Auslastung, KI-Calls
   - Logging für kritische Aktionen
   - Alerting bei Latenz-Überschreitung

5. **Energieoptimierung**
   - Modell-Unloading nach Inaktivität
   - GPU-Affinity optimieren
   - Batch-Verarbeitung für DMS

6. **Automations-Refactoring**
   - Simple Regeln in Home Assistant belassen (Ausfallsicherheit)
   - Komplexe KI-Szenarien in n8n zentralisieren
   - Doppellogik abbauen

7. **Modellstrategie & Feintuning**
   - Evaluieren, welche Use-Cases mit lokalen Modellen funktionieren
   - Optional Cloud-Einsatz für komplexe Aufgaben
   - Prompt-/Tool-Optimierung

8. **Langzeit-Gedächtnis**
   - Extraktion wichtiger Fakten aus Gesprächen
   - ConversationMemory in Weaviate befüllen
   - Integration in Kontext-Anreicherung

9. **Dokumentation & Runbooks**
   - Betriebshandbuch erstellen
   - Troubleshooting-Guides
   - Backup/Restore-Prozeduren

#### Ergebnis
Stabil laufendes KI-first und Sprache-first System mit zentralem Assistenten, Multi-User-Fähigkeit, robustem Monitoring und dokumentierten Betriebsprozessen

#### Feinkonzept-Inhalte (zu erstellen)
- Security-Konzept (Auth, Rollen, Verschlüsselung)
- Multi-User-Konfliktmatrix
- Monitoring-Konzept mit Metriken und Alerts
- Betriebshandbuch

---

## 10. Übergang zum Feinkonzept

### Vorgehen

Für jede Phase wird vor Beginn der Umsetzung ein Feinkonzept erstellt:

1. **Scope festlegen**: Welche Elemente aus dem Grobkonzept werden detailliert?
2. **Technische Recherche**: Konkrete Versionen, Konfigurationen, Abhängigkeiten
3. **Spezifikation**: APIs, Datenstrukturen, Konfigurationsdateien
4. **Testfälle**: Akzeptanzkriterien für jeden Schritt
5. **Review**: Plausibilitätsprüfung vor Umsetzung

### Feinkonzept-Template

Jedes Feinkonzept folgt dieser Struktur:

```markdown
# Feinkonzept Phase X: [Titel]

## 1. Scope und Ziele
## 2. Voraussetzungen
## 3. Technische Spezifikation
   3.1 Komponente A
   3.2 Komponente B
   ...
## 4. Konfigurationen
## 5. Implementierungsschritte
## 6. Testfälle und Akzeptanzkriterien
## 7. Risiken und Mitigationen
## 8. Rollback-Plan
```

---

## 11. Zusammenfassung

Mit dieser Architektur entsteht eine:

- **Extrem performante** Infrastruktur (optimale GPU-Nutzung, definierte Latenz-Budgets)
- **Ausfallsichere** Basis (Graceful Degradation, HA-Autonomie)
- **Sauber getrennte** Storage-Hierarchie (Hot/Warm/Cold)
- **Hochskalierbare** Software-Architektur (Schichtenmodell)
- **Multi-User-fähige** Lösung (Sprechererkennung, Konfliktauflösung)
- **Kontextbewusste** Interaktion (Session-Management, Anaphern-Auflösung)
- **Sicher redundante** Datenhaltung (ZFS-Mirror, Backups)
- **Energiebewusste** Betriebsführung (Monitoring, Optimierungsstrategien)
- **Versionierte** Workflows (Git, Staging, Rollback)
- **Zukunftssichere** Basis für Voice-first KI-Interaktionen

Der zentrale Assistent vereint alle Domänen unter einer einheitlichen Sprach- und Text-Schnittstelle, ohne dass zwischen verschiedenen Systemen unterschieden werden muss.

---

## 12. Nächste Schritte

1. **Review dieses Grobkonzepts** – Feedback und Anpassungen
2. **Feinkonzept Phase 0 erstellen** – Hardware-Umbau und Storage-Setup detaillieren
3. **Hardware-Umbau durchführen** – Nach Feinkonzept
4. **Feinkonzept Phase 1 erstellen** – Parallel zum Hardware-Umbau
