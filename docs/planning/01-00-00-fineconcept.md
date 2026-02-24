# Feinkonzept Phase 1: Alice – KI-First Grundsystem

## Dokumentstatus

| Attribut | Wert |
| :-------- | :---- |
| **Dokumenttyp** | Feinkonzept |
| **Phase** | 1 |
| **Version** | 1.0 |
| **Status** | Entwurf |
| **Basiert auf** | Grobkonzept v1.0 |
| **Repository** | <https://github.com/AndrewSteel/alice> |

---

## 1. Scope und Ziele

### 1.1 Phasenziel

Aufbau eines funktionsfähigen KI-Chat-Systems mit:

- Zentralem n8n-Workflow als KI-Endpunkt
- React-WebApp für Text-basierte Interaktion
- Home Assistant Integration (Licht & Schalter)
- DMS-Grundlage mit Weaviate für alle Dokumenttypen
- Multi-Tier Agent Memory von Anfang an
- Latenz-Baseline und Monitoring-Grundlage

### 1.2 Abgrenzung (nicht in Phase 1)

- Spracheingabe/-ausgabe (Phase 2)
- Sprechererkennung (Phase 2)
- Display-Routing / Output-Router (Phase 3)
- Multi-User-Handling (Phase 3)
- Bilder und Videos im DMS

### 1.3 Erfolgskriterien

| Kriterium | Messung |
| :-------- | :------ |
| Chat-Antwort funktioniert | Text-Eingabe → KI-Antwort in < 5s |
| HA-Steuerung funktioniert | "Schalte Licht X ein" → Licht geht an |
| DMS-Import funktioniert | PDF-Upload → Eintrag in Weaviate |
| Memory funktioniert | Kontext aus vorherigen Nachrichten wird genutzt |
| Dokument-Suche funktioniert | Semantische Suche findet relevante Dokumente |

---

## 2. Voraussetzungen

### 2.1 Abgeschlossene Phase 0

- [x] Hardware eingerichtet (Ryzen 9, RTX 3090, TITAN X)
- [x] Docker-Stack läuft stabil
- [x] Ollama mit Modellen (qwen, gpt-oss, gemma)
- [x] Weaviate mit text2vec-transformers auf TITAN X
- [x] PostgreSQL und Redis verfügbar
- [x] nginx Reverse-Proxy konfiguriert
- [x] Monitoring-Grundlage (Prometheus/Grafana)

### 2.2 Benötigte Zugänge

| System | Zugang | Zweck |
| :----- | :----- | :---- |
| Home Assistant | Long-Lived Access Token | REST API Calls |
| GitHub | SSH-Key oder Token | Repository-Zugriff |
| NAS | NFS/SMB Mount | Dokument-Zugriff |
| Pi-hole | Admin-Zugang | DNS-Eintrag alice.happy-mining.de |

### 2.3 Neue Container für Phase 1

| Container | Image | Zweck | GPU |
| :-------- | :---- | :---- | :-- |
| alice-frontend | Custom (React) | WebApp | - |
| alice-api | Custom (Python/FastAPI) | Optional: API-Layer | - |

---

## 3. Technische Spezifikation

### 3.1 Systemarchitektur Phase 1

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         ALICE PHASE 1                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐ │
│  │    React     │────▶│    nginx     │────▶│        n8n           │ │
│  │   Frontend   │     │    Proxy     │     │   /webhook/alice     │ │
│  │              │◀────│              │◀────│                      │ │
│  └──────────────┘     └──────────────┘     └──────────┬───────────┘ │
│        ▲                                              │             │
│        │                                              ▼             │
│        │                                   ┌──────────────────────┐ │
│        │                                   │    Tool Router       │ │
│        │                                   │  (Qwen2.5 + Tools)   │ │
│        │                                   └──────────┬───────────┘ │
│        │                                              │             │
│        │              ┌───────────────────────────────┼─────────┐   │
│        │              │                               │         │   │
│        │              ▼                               ▼         ▼   │
│        │   ┌──────────────────┐    ┌─────────────┐  ┌─────────────┐ │
│        │   │  Home Assistant  │    │  Weaviate   │  │ PostgreSQL  │ │
│        │   │    REST API      │    │  (Vektor)   │  │  (Memory)   │ │
│        │   │  Licht/Schalter  │    │    DMS      │  │  Sessions   │ │
│        │   └──────────────────┘    └─────────────┘  └─────────────┘ │
│        │                                                            │
│        │   ┌──────────────────┐    ┌─────────────┐                  │
│        │   │      MQTT        │    │   Ollama    │                  │
│        │   │  (DMS-Queue)     │    │  RTX 3090   │                  │
│        │   └──────────────────┘    └─────────────┘                  │
│        │                                                            │
└────────┼────────────────────────────────────────────────────────────┘
         │
    WebSocket für
    Streaming-Responses
```

### 3.2 LLM-Strategie: Tool-Use statt Router

**Bisheriger Ansatz (Router):**

```text
User Input → gemma:2b (Router) → Entscheidung → qwen:14b (Ausführung)
             ~500ms                              ~2000ms
             = 2 LLM-Calls, ~2500ms gesamt
```

**Neuer Ansatz (Tool-Use):**

```text
User Input → Qwen2.5:14b mit Tools → Direkte Ausführung
             ~2000ms (1 Call)
             = 1 LLM-Call, schneller & flexibler
```

**Vorteile:**

- Weniger Latenz (ein statt zwei LLM-Calls)
- Flexiblere Tool-Kombinationen möglich
- Modell entscheidet kontextbasiert
- Qwen2.5 hat natives Function-Calling

**Empfohlenes Modell:** `qwen2.5:14b-instruct-q5_K_M`

- 14B Parameter, quantisiert auf ~10GB VRAM
- Natives Tool/Function-Calling
- Gute deutsche Sprachunterstützung
- Lässt Raum für Whisper auf TITAN X

### 3.3 Tool-Definitionen für Alice

```json
{
  "tools": [
    {
      "name": "home_assistant",
      "description": "Steuert Smart-Home-Geräte wie Lichter und Schalter",
      "parameters": {
        "action": "turn_on | turn_off | toggle | set_brightness",
        "entity_id": "light.xxx oder switch.xxx",
        "brightness": "0-255 (optional, nur für Lichter)"
      }
    },
    {
      "name": "search_documents",
      "description": "Durchsucht das Dokumentenarchiv semantisch",
      "parameters": {
        "query": "Suchbegriff oder Frage",
        "doc_type": "Rechnung | Kontoauszug | Dokument | Email | alle",
        "date_from": "YYYY-MM-DD (optional)",
        "date_to": "YYYY-MM-DD (optional)",
        "limit": "Anzahl Ergebnisse (default: 5)"
      }
    },
    {
      "name": "get_document_details",
      "description": "Ruft Details zu einem spezifischen Dokument ab",
      "parameters": {
        "document_id": "Weaviate UUID des Dokuments"
      }
    },
    {
      "name": "remember",
      "description": "Speichert wichtige Informationen für später",
      "parameters": {
        "fact": "Die zu merkende Information",
        "category": "personal | preference | task | other"
      }
    },
    {
      "name": "recall",
      "description": "Ruft früher gespeicherte Informationen ab",
      "parameters": {
        "query": "Wonach soll gesucht werden?"
      }
    }
  ]
}
```

### 3.4 n8n Workflow-Architektur

#### Haupt-Workflow: Alice Chat Handler

```text
┌─────────────────────────────────────────────────────────────────────────┐
│ WORKFLOW: Alice Chat Handler                                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────────┐  │
│  │ Webhook │──▶│ Load Memory │──▶│ Build Prompt│──▶│ LLM + Tools     │  │
│  │  POST   │   │ (3 Tiers)   │   │             │   │ (Qwen2.5:14b)   │  │
│  └─────────┘   └─────────────┘   └─────────────┘   └─────────┬───────┘  │
│                                                              │          │
│                                        ┌─────────────────────┼────────┐ │
│                                        │    Tool Execution   │        │ │
│                                        │         Loop        ▼        │ │
│                                        │  ┌─────────────────────────┐ │ │
│                                        │  │ Tool: home_assistant    │ │ │
│                                        │  │ Tool: search_documents  │ │ │
│                                        │  │ Tool: remember/recall   │ │ │
│                                        │  └─────────────────────────┘ │ │
│                                        │              │               │ │
│                                        │              ▼               │ │
│                                        │  ┌─────────────────────────┐ │ │
│                                        │  │ LLM: Final Response     │ │ │
│                                        │  └─────────────────────────┘ │ │
│                                        └──────────────┬───────────────┘ │
│                                                       │                 │
│  ┌──────────────┐   ┌─────────────┐                   │                 │
│  │ Save Memory  │◀──│Format Output│◀──────────────────┘                 │
│  │ (PostgreSQL) │   │             │                                     │
│  └──────────────┘   └──────┬──────┘                                     │
│                            │                                            │
│                            ▼                                            │
│                    ┌──────────────┐                                     │
│                    │   Response   │                                     │
│                    │  to Webhook  │                                     │
│                    └──────────────┘                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Sub-Workflows

| Workflow | Trigger | Funktion |
| :------- | :------ | :------- |
| `alice-chat-handler` | Webhook POST | Haupt-Chat-Logik |
| `alice-tool-ha` | Workflow Call | Home Assistant Steuerung |
| `alice-tool-search` | Workflow Call | Weaviate Dokumentensuche |
| `alice-memory-transfer` | Schedule (täglich) | PostgreSQL → Weaviate Transfer |
| `alice-dms-scanner` | Schedule (stündlich) | NAS-Ordner scannen → MQTT |
| `alice-dms-processor` | Schedule (nachts) | MQTT-Queue → Weaviate |

### 3.5 Multi-Tier Memory Implementierung

#### Tier 1: Working Memory (PostgreSQL)

```sql
-- Schema für Agent Memory
CREATE SCHEMA IF NOT EXISTS alice;

-- ============================================
-- USER MANAGEMENT (Vorbereitung für Phase 1.5/2)
-- ============================================

CREATE TABLE alice.users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    email VARCHAR(255),
    
    -- Phase 1.5: Passwort-Auth
    password_hash VARCHAR(255),
    
    -- Phase 2: WebAuthn/Passkeys
    webauthn_credentials JSONB DEFAULT '[]',
    
    -- Phase 2: Speaker Recognition
    speaker_embeddings JSONB DEFAULT '[]',
    speaker_enrollment_complete BOOLEAN DEFAULT FALSE,
    
    -- Berechtigungen
    role VARCHAR(20) DEFAULT 'user' CHECK (role IN ('admin', 'user', 'guest')),
    permissions JSONB DEFAULT '{
        "home_assistant": {
            "lights": true,
            "switches": true,
            "climate": false,
            "security": false
        },
        "dms": {
            "read": true,
            "write": true,
            "delete": false
        },
        "settings": {
            "manage_users": false,
            "manage_devices": false
        }
    }',
    
    -- Metadaten
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_login TIMESTAMPTZ,
    failed_login_attempts INT DEFAULT 0,
    locked_until TIMESTAMPTZ
);

-- Initiale User anlegen
INSERT INTO alice.users (username, display_name, role, permissions) VALUES
(
    'andreas', 
    'Andreas', 
    'admin',
    '{
        "home_assistant": {"lights": true, "switches": true, "climate": true, "security": true},
        "dms": {"read": true, "write": true, "delete": true},
        "settings": {"manage_users": true, "manage_devices": true}
    }'
),
(
    'partner', 
    'Partner', 
    'user',
    '{
        "home_assistant": {"lights": true, "switches": true, "climate": true, "security": false},
        "dms": {"read": true, "write": true, "delete": false},
        "settings": {"manage_users": false, "manage_devices": false}
    }'
),
(
    'gast',
    'Gast',
    'guest',
    '{
        "home_assistant": {"lights": true, "switches": false, "climate": false, "security": false},
        "dms": {"read": false, "write": false, "delete": false},
        "settings": {"manage_users": false, "manage_devices": false}
    }'
);

-- Sessions für Auth (Phase 1.5)
CREATE TABLE alice.auth_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES alice.users(id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    device_info JSONB,
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    last_activity TIMESTAMPTZ DEFAULT NOW(),
    is_valid BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_auth_sessions_token ON alice.auth_sessions(token_hash) WHERE is_valid = TRUE;
CREATE INDEX idx_auth_sessions_user ON alice.auth_sessions(user_id, expires_at);

-- WebAuthn Challenges (Phase 2)
CREATE TABLE alice.webauthn_challenges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES alice.users(id) ON DELETE CASCADE,
    challenge TEXT NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('registration', 'authentication')),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '5 minutes'),
    used BOOLEAN DEFAULT FALSE
);

-- ============================================
-- AGENT MEMORY
-- ============================================

-- Aktive Konversationen
CREATE TABLE alice.messages (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    user_id VARCHAR(255) NOT NULL DEFAULT 'andreas',
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    tool_calls JSONB,
    tool_results JSONB,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    token_count INT,
    transferred_to_weaviate BOOLEAN DEFAULT FALSE,
    transferred_at TIMESTAMPTZ,
    weaviate_id UUID
);

CREATE INDEX idx_messages_session ON alice.messages(session_id, timestamp);
CREATE INDEX idx_messages_user_recent ON alice.messages(user_id, timestamp DESC);
CREATE INDEX idx_messages_not_transferred ON alice.messages(user_id) 
    WHERE transferred_to_weaviate = FALSE;

-- Session-Metadaten
CREATE TABLE alice.sessions (
    session_id UUID PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    last_activity TIMESTAMPTZ DEFAULT NOW(),
    message_count INT DEFAULT 0,
    summary TEXT,
    key_topics TEXT[],
    is_active BOOLEAN DEFAULT TRUE
);

-- User-Profile (Tier 3: Summarized Facts)
CREATE TABLE alice.user_profiles (
    user_id VARCHAR(255) PRIMARY KEY,
    facts JSONB DEFAULT '{}',
    preferences JSONB DEFAULT '{}',
    last_updated TIMESTAMPTZ DEFAULT NOW(),
    
    -- Verknüpfung mit Users-Tabelle
    CONSTRAINT fk_user_profiles_user 
        FOREIGN KEY (user_id) 
        REFERENCES alice.users(username) 
        ON DELETE CASCADE
);

-- Initiale Profile für alle User
INSERT INTO alice.user_profiles (user_id, facts, preferences) VALUES
(
    'andreas',
    '{"name": "Andreas", "rolle": "Hausbesitzer", "interessen": ["Smart Home", "KI", "Garten", "Finanzen"]}',
    '{"sprache": "deutsch", "anrede": "du", "detailgrad": "technisch"}'
),
(
    'partner',
    '{"name": "Partner", "rolle": "Hausbesitzer"}',
    '{"sprache": "deutsch", "anrede": "du", "detailgrad": "normal"}'
),
(
    'gast',
    '{"name": "Gast", "rolle": "Besucher"}',
    '{"sprache": "deutsch", "anrede": "Sie", "detailgrad": "einfach"}'
);
```

#### Tier 2: Long-Term Memory (Weaviate)

```json
{
  "class": "AliceMemory",
  "description": "Langzeit-Erinnerungen des Alice-Assistenten",
  "vectorizer": "text2vec-transformers",
  "vectorIndexConfig": {
    "distance": "cosine"
  },
  "properties": [
    {
      "name": "session_id",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": {
        "text2vec-transformers": { "skip": true }
      }
    },
    {
      "name": "user_id",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": {
        "text2vec-transformers": { "skip": true }
      }
    },
    {
      "name": "timestamp",
      "dataType": ["date"],
      "indexFilterable": true
    },
    {
      "name": "conversation_context",
      "dataType": ["text"],
      "description": "User-Nachricht + Assistant-Antwort kombiniert für Vektorisierung",
      "moduleConfig": {
        "text2vec-transformers": { "skip": false }
      }
    },
    {
      "name": "user_message",
      "dataType": ["text"],
      "moduleConfig": {
        "text2vec-transformers": { "skip": true }
      }
    },
    {
      "name": "assistant_message",
      "dataType": ["text"],
      "moduleConfig": {
        "text2vec-transformers": { "skip": true }
      }
    },
    {
      "name": "extracted_facts",
      "dataType": ["text"],
      "description": "LLM-extrahierte Fakten aus der Konversation",
      "moduleConfig": {
        "text2vec-transformers": { "skip": false }
      }
    },
    {
      "name": "topics",
      "dataType": ["text[]"],
      "indexFilterable": true
    },
    {
      "name": "importance_score",
      "dataType": ["number"],
      "description": "0.0-1.0, LLM-bewertet",
      "indexFilterable": true
    },
    {
      "name": "postgres_message_id",
      "dataType": ["int"]
    }
  ]
}
```

#### Memory-Retrieval-Logik

```javascript
// n8n Code-Node: Build Context with Memory
const userId = $json.user_id || 'andreas';
const sessionId = $json.session_id;
const userMessage = $json.message;

// Tier 3: User Profile (immer laden)
const userProfile = await $getWorkflowStaticData('global').db.query(`
  SELECT facts, preferences FROM alice.user_profiles WHERE user_id = $1
`, [userId]);

// Tier 1: Working Memory (letzte 20 Nachrichten dieser Session)
const workingMemory = await $getWorkflowStaticData('global').db.query(`
  SELECT role, content, tool_calls, tool_results, timestamp
  FROM alice.messages
  WHERE session_id = $1
  ORDER BY timestamp DESC
  LIMIT 20
`, [sessionId]);

// Tier 2: Relevante Long-Term Memories (semantische Suche)
const relevantMemories = await fetch('http://weaviate:8080/v1/graphql', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    query: `{
      Get {
        AliceMemory(
          nearText: { concepts: ["${userMessage.replace(/"/g, '\\"')}"] }
          where: {
            path: ["user_id"]
            operator: Equal
            valueText: "${userId}"
          }
          limit: 5
        ) {
          conversation_context
          extracted_facts
          timestamp
          importance_score
          _additional { distance }
        }
      }
    }`
  })
});

// Context zusammenbauen
return {
  userProfile: userProfile.rows[0],
  workingMemory: workingMemory.rows.reverse(), // chronologisch
  relevantMemories: relevantMemories.data?.Get?.AliceMemory || [],
  currentMessage: userMessage
};
```

### 3.6 Home Assistant Integration

#### REST API Konfiguration

```yaml
# In Home Assistant configuration.yaml (falls nicht schon aktiv)
api:

# Long-Lived Access Token erstellen:
# Profil → Sicherheit → Langlebige Zugangstoken → Token erstellen
```

#### n8n Sub-Workflow: alice-tool-ha

```javascript
// Eingabe vom Tool-Call
const action = $json.action;      // turn_on, turn_off, toggle, set_brightness
const entityId = $json.entity_id; // light.wohnzimmer, switch.buero
const brightness = $json.brightness; // optional

const HA_URL = 'http://homeassistant.local:8123';
const HA_TOKEN = $env.HA_TOKEN;

// Service bestimmen
let domain = entityId.split('.')[0]; // light oder switch
let service = action;

if (action === 'set_brightness' && domain === 'light') {
  service = 'turn_on';
}

// API-Call
const response = await fetch(`${HA_URL}/api/services/${domain}/${service}`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${HA_TOKEN}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    entity_id: entityId,
    ...(brightness && { brightness: parseInt(brightness) })
  })
});

if (response.ok) {
  // Entity-State abrufen für Bestätigung
  const stateResponse = await fetch(`${HA_URL}/api/states/${entityId}`, {
    headers: { 'Authorization': `Bearer ${HA_TOKEN}` }
  });
  const state = await stateResponse.json();
  
  return {
    success: true,
    entity_id: entityId,
    new_state: state.state,
    friendly_name: state.attributes.friendly_name
  };
} else {
  return {
    success: false,
    error: `HA API Error: ${response.status}`
  };
}
```

#### Verfügbare Entities ermitteln

```javascript
// n8n Workflow: HA Entity Discovery (einmalig/bei Bedarf)
const HA_URL = 'http://homeassistant.local:8123';
const HA_TOKEN = $env.HA_TOKEN;

const response = await fetch(`${HA_URL}/api/states`, {
  headers: { 'Authorization': `Bearer ${HA_TOKEN}` }
});
const allStates = await response.json();

// Nur Lichter und Schalter filtern
const relevantEntities = allStates
  .filter(e => e.entity_id.startsWith('light.') || e.entity_id.startsWith('switch.'))
  .map(e => ({
    entity_id: e.entity_id,
    friendly_name: e.attributes.friendly_name,
    state: e.state,
    domain: e.entity_id.split('.')[0]
  }));

// Als JSON speichern für System-Prompt
return { entities: relevantEntities };
```

### 3.7 DMS-Pipeline

#### Architektur

```text
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  NAS-Ordner │────▶│  Scanner    │────▶│    MQTT     │────▶│  Processor  │
│  (mehrere)  │     │ (stündlich) │     │   Queue     │     │  (nachts)   │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                                                                   │
                           ┌───────────────────────────────────────┘
                           │
                           ▼
              ┌─────────────────────────┐
              │      Verarbeitung       │
              │  ┌───────────────────┐  │
              │  │ 1. PDF → Text     │  │
              │  │ 2. LLM Extraction │  │
              │  │ 3. Klassifikation │  │
              │  │ 4. Weaviate Insert│  │
              │  └───────────────────┘  │
              └─────────────────────────┘
```

#### NAS-Ordner-Struktur (Vorschlag)

```text
/volume1/dokumente/
├── inbox/              # Neue, unverarbeitete Dokumente
│   ├── rechnungen/
│   ├── kontoauszuege/
│   ├── vertraege/
│   └── sonstiges/
├── archiv/             # Verarbeitete Dokumente (nach Jahr)
│   ├── 2024/
│   └── 2025/
└── fehler/             # Dokumente mit Verarbeitungsfehlern
```

#### MQTT Topic-Struktur

```text
alice/dms/new           # Neue Dokumente zur Verarbeitung
alice/dms/processing    # Aktuell in Verarbeitung
alice/dms/done          # Erfolgreich verarbeitet
alice/dms/error         # Fehler bei Verarbeitung
```

#### Message-Format

```json
{
  "file_path": "/volume1/dokumente/inbox/rechnungen/rechnung_2024_001.pdf",
  "detected_at": "2025-01-17T22:00:00Z",
  "file_size": 125000,
  "file_hash": "sha256:abc123...",
  "suggested_type": "Rechnung",
  "priority": "normal"
}
```

#### Workflow: alice-dms-scanner

```javascript
// Trigger: Schedule (alle 60 Minuten, tagsüber)
// Scannt konfigurierte Ordner auf neue Dateien

const SCAN_PATHS = [
  { path: '/mnt/nas/dokumente/inbox/rechnungen', type: 'Rechnung' },
  { path: '/mnt/nas/dokumente/inbox/kontoauszuege', type: 'Kontoauszug' },
  { path: '/mnt/nas/dokumente/inbox/vertraege', type: 'Dokument' },
  { path: '/mnt/nas/dokumente/inbox/sonstiges', type: 'auto' }
];

const processedFiles = await redis.smembers('alice:dms:processed_files');
const newFiles = [];

for (const scanPath of SCAN_PATHS) {
  const files = await fs.readdir(scanPath.path);
  
  for (const file of files) {
    if (!file.endsWith('.pdf')) continue;
    
    const fullPath = `${scanPath.path}/${file}`;
    const fileHash = await calculateHash(fullPath);
    
    if (!processedFiles.includes(fileHash)) {
      newFiles.push({
        file_path: fullPath,
        detected_at: new Date().toISOString(),
        file_hash: fileHash,
        suggested_type: scanPath.type,
        priority: 'normal'
      });
    }
  }
}

// Neue Dateien in MQTT-Queue
for (const file of newFiles) {
  await mqtt.publish('alice/dms/new', JSON.stringify(file));
  await redis.sadd('alice:dms:queued_files', file.file_hash);
}

return { scanned: SCAN_PATHS.length, new_files: newFiles.length };
```

#### Workflow: alice-dms-processor

```javascript
// Trigger: Schedule (nachts, 02:00-05:00)
// Verarbeitet Dokumente aus MQTT-Queue

const MAX_DOCS_PER_RUN = 50;
const messages = await mqtt.subscribe('alice/dms/new', { limit: MAX_DOCS_PER_RUN });

for (const msg of messages) {
  const doc = JSON.parse(msg.payload);
  
  try {
    // 1. PDF → Text
    const text = await extractTextFromPDF(doc.file_path);
    
    // 2. LLM-Klassifikation und Extraktion
    const extracted = await callOllama({
      model: 'qwen2.5:14b',
      prompt: buildExtractionPrompt(text, doc.suggested_type)
    });
    
    // 3. Weaviate-Collection bestimmen
    const collection = mapTypeToCollection(extracted.document_type);
    
    // 4. In Weaviate speichern
    const weaviateId = await insertToWeaviate(collection, {
      ...extracted.fields,
      volltext: text,
      pdf_pfad: doc.file_path
    });
    
    // 5. Datei ins Archiv verschieben
    await moveToArchive(doc.file_path, extracted.document_type);
    
    // 6. Als verarbeitet markieren
    await redis.sadd('alice:dms:processed_files', doc.file_hash);
    await mqtt.publish('alice/dms/done', JSON.stringify({
      file_hash: doc.file_hash,
      weaviate_id: weaviateId,
      collection: collection
    }));
    
  } catch (error) {
    await mqtt.publish('alice/dms/error', JSON.stringify({
      file_hash: doc.file_hash,
      error: error.message
    }));
    await moveToErrorFolder(doc.file_path);
  }
}
```

### 3.8 React Frontend

#### Projektstruktur

```text
alice-frontend/
├── public/
│   └── index.html
├── src/
│   ├── components/
│   │   ├── Auth/                    # NEU: Auth-Komponenten
│   │   │   ├── AuthProvider.jsx     # Context Provider
│   │   │   ├── LoginScreen.jsx      # Phase 1.5: Login-UI
│   │   │   ├── ProtectedRoute.jsx   # Route-Guard
│   │   │   └── UserMenu.jsx         # User-Anzeige/Logout
│   │   ├── Chat/
│   │   │   ├── ChatContainer.jsx
│   │   │   ├── MessageList.jsx
│   │   │   ├── MessageBubble.jsx
│   │   │   └── InputArea.jsx
│   │   ├── Sidebar/
│   │   │   ├── Sidebar.jsx
│   │   │   └── SessionList.jsx
│   │   └── common/
│   │       ├── LoadingIndicator.jsx
│   │       └── ErrorBoundary.jsx
│   ├── hooks/
│   │   ├── useAuth.js               # NEU: Auth-Hook
│   │   ├── useChat.js
│   │   ├── useWebSocket.js
│   │   └── useSession.js
│   ├── services/
│   │   ├── api.js
│   │   └── auth.js                  # NEU: Auth-Service
│   ├── App.jsx
│   └── index.jsx
├── package.json
├── Dockerfile
└── nginx.conf
```

#### Auth-Context (Phase 1: Auto-Login, vorbereitet für Phase 1.5)

```jsx
// src/components/Auth/AuthProvider.jsx
import React, { createContext, useContext, useState, useEffect } from 'react';
import { authService } from '../../services/auth';

const AuthContext = createContext(null);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(false);

  useEffect(() => {
    initializeAuth();
  }, []);

  const initializeAuth = async () => {
    try {
      // Phase 1: Auto-Login als 'andreas'
      // Phase 1.5: Token aus localStorage prüfen
      const savedToken = localStorage.getItem('alice_token');
      
      if (savedToken) {
        // Phase 1.5: Token validieren
        const userData = await authService.validateToken(savedToken);
        setUser(userData);
        setIsAuthenticated(true);
      } else {
        // Phase 1: Automatischer Default-User
        const defaultUser = {
          id: 'andreas',
          username: 'andreas',
          displayName: 'Andreas',
          role: 'admin',
          permissions: {
            home_assistant: { lights: true, switches: true, climate: true, security: true },
            dms: { read: true, write: true, delete: true },
            settings: { manage_users: true, manage_devices: true }
          }
        };
        setUser(defaultUser);
        setIsAuthenticated(true);
      }
    } catch (error) {
      console.error('Auth initialization failed:', error);
      // Phase 1: Fallback zu Default-User
      setUser({ id: 'andreas', username: 'andreas', displayName: 'Andreas', role: 'admin' });
      setIsAuthenticated(true);
    } finally {
      setIsLoading(false);
    }
  };

  // Phase 1.5: Login-Funktion (aktuell Placeholder)
  const login = async (username, password) => {
    setIsLoading(true);
    try {
      const { user: userData, token } = await authService.login(username, password);
      localStorage.setItem('alice_token', token);
      setUser(userData);
      setIsAuthenticated(true);
      return { success: true };
    } catch (error) {
      return { success: false, error: error.message };
    } finally {
      setIsLoading(false);
    }
  };

  // Phase 2: WebAuthn Login (Placeholder)
  const loginWithWebAuthn = async () => {
    throw new Error('WebAuthn not implemented yet - coming in Phase 2');
  };

  const logout = () => {
    localStorage.removeItem('alice_token');
    setUser(null);
    setIsAuthenticated(false);
    // Phase 1: Sofort wieder als Default einloggen
    initializeAuth();
  };

  // Berechtigungsprüfung
  const hasPermission = (category, action) => {
    if (!user?.permissions) return false;
    return user.permissions[category]?.[action] === true;
  };

  const value = {
    user,
    isLoading,
    isAuthenticated,
    login,
    loginWithWebAuthn,
    logout,
    hasPermission
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};
```

#### Auth-Service (Vorbereitung)

```javascript
// src/services/auth.js
const API_BASE = process.env.REACT_APP_API_URL || 'https://alice.happy-mining.de/api';

export const authService = {
  // Phase 1.5: Passwort-Login
  async login(username, password) {
    const response = await fetch(`${API_BASE}/webhook/alice/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.message || 'Login fehlgeschlagen');
    }
    
    return response.json();
  },

  // Phase 1.5: Token validieren
  async validateToken(token) {
    const response = await fetch(`${API_BASE}/webhook/alice/auth/validate`, {
      headers: { 
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      }
    });
    
    if (!response.ok) {
      throw new Error('Token ungültig');
    }
    
    return response.json();
  },

  // Phase 2: WebAuthn Registration
  async startWebAuthnRegistration(userId) {
    const response = await fetch(`${API_BASE}/webhook/alice/auth/webauthn/register/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId })
    });
    return response.json();
  },

  async completeWebAuthnRegistration(userId, credential) {
    const response = await fetch(`${API_BASE}/webhook/alice/auth/webauthn/register/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, credential })
    });
    return response.json();
  },

  // Phase 2: WebAuthn Authentication
  async startWebAuthnAuth(username) {
    const response = await fetch(`${API_BASE}/webhook/alice/auth/webauthn/auth/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username })
    });
    return response.json();
  },

  async completeWebAuthnAuth(username, credential) {
    const response = await fetch(`${API_BASE}/webhook/alice/auth/webauthn/auth/complete`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, credential })
    });
    return response.json();
  }
};
```

#### App.jsx mit AuthProvider

```jsx
// src/App.jsx
import React from 'react';
import { AuthProvider } from './components/Auth/AuthProvider';
import { useAuth } from './components/Auth/AuthProvider';
import ChatContainer from './components/Chat/ChatContainer';
import Sidebar from './components/Sidebar/Sidebar';
import LoadingIndicator from './components/common/LoadingIndicator';

const AppContent = () => {
  const { isLoading, isAuthenticated, user } = useAuth();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen bg-gray-900">
        <LoadingIndicator text="Alice wird geladen..." />
      </div>
    );
  }

  // Phase 1.5: Hier würde LoginScreen gerendert wenn !isAuthenticated
  // if (!isAuthenticated) {
  //   return <LoginScreen />;
  // }

  return (
    <div className="flex h-screen bg-gray-900">
      <Sidebar user={user} />
      <main className="flex-1">
        <ChatContainer />
      </main>
    </div>
  );
};

const App = () => {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
};

export default App;
```

#### Kern-Komponente: ChatContainer (mit Auth)

```jsx
// src/components/Chat/ChatContainer.jsx
import React, { useState, useEffect, useRef } from 'react';
import { useChat } from '../../hooks/useChat';
import MessageList from './MessageList';
import InputArea from './InputArea';

const ChatContainer = () => {
  const { 
    messages, 
    isLoading, 
    sendMessage, 
    sessionId 
  } = useChat();
  
  const messagesEndRef = useRef(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async (text) => {
    if (!text.trim()) return;
    await sendMessage(text);
  };

  return (
    <div className="flex flex-col h-full bg-gray-900">
      <header className="bg-gray-800 p-4 border-b border-gray-700">
        <h1 className="text-xl font-semibold text-white">Alice</h1>
        <span className="text-sm text-gray-400">Session: {sessionId?.slice(0, 8)}...</span>
      </header>
      
      <MessageList messages={messages} isLoading={isLoading} />
      <div ref={messagesEndRef} />
      
      <InputArea onSend={handleSend} disabled={isLoading} />
    </div>
  );
};

export default ChatContainer;
```

#### API Service (mit Auth-Vorbereitung)

```javascript
// src/services/api.js
const API_BASE = process.env.REACT_APP_API_URL || 'https://alice.happy-mining.de/api';

// Helper für Auth-Header
const getAuthHeaders = () => {
  const token = localStorage.getItem('alice_token');
  const headers = {
    'Content-Type': 'application/json',
  };
  
  // Phase 1.5: Token im Header mitschicken
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  
  return headers;
};

export const chatApi = {
  // User-ID wird jetzt von außen übergeben (aus AuthContext)
  async sendMessage(sessionId, message, userId = 'andreas') {
    const response = await fetch(`${API_BASE}/webhook/alice`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        session_id: sessionId,
        user_id: userId,
        message: message,
        timestamp: new Date().toISOString()
      })
    });
    
    if (!response.ok) {
      if (response.status === 401) {
        // Phase 1.5: Token abgelaufen → Logout triggern
        localStorage.removeItem('alice_token');
        window.location.reload();
      }
      throw new Error(`API Error: ${response.status}`);
    }
    
    return response.json();
  },
  
  async getSessionHistory(sessionId) {
    const response = await fetch(`${API_BASE}/webhook/alice/history/${sessionId}`, {
      headers: getAuthHeaders()
    });
    return response.json();
  },
  
  async getSessions(userId = 'andreas') {
    const response = await fetch(`${API_BASE}/webhook/alice/sessions?user_id=${userId}`, {
      headers: getAuthHeaders()
    });
    return response.json();
  }
};
```

#### useChat Hook (mit Auth-Integration)

```javascript
// src/hooks/useChat.js
import { useState, useCallback, useEffect } from 'react';
import { useAuth } from '../components/Auth/AuthProvider';
import { chatApi } from '../services/api';
import { v4 as uuidv4 } from 'uuid';

export const useChat = () => {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => {
    // Session aus localStorage oder neue erstellen
    const saved = localStorage.getItem('alice_session_id');
    return saved || uuidv4();
  });

  useEffect(() => {
    localStorage.setItem('alice_session_id', sessionId);
  }, [sessionId]);

  const sendMessage = useCallback(async (text) => {
    if (!text.trim() || !user) return;

    const userMessage = {
      id: uuidv4(),
      role: 'user',
      content: text,
      timestamp: new Date().toISOString()
    };

    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      // User-ID aus Auth-Context verwenden
      const response = await chatApi.sendMessage(sessionId, text, user.username);
      
      const assistantMessage = {
        id: uuidv4(),
        role: 'assistant',
        content: response.message,
        timestamp: new Date().toISOString(),
        toolCalls: response.tool_calls || []
      };

      setMessages(prev => [...prev, assistantMessage]);
    } catch (error) {
      console.error('Chat error:', error);
      setMessages(prev => [...prev, {
        id: uuidv4(),
        role: 'assistant',
        content: 'Entschuldigung, es gab einen Fehler. Bitte versuche es erneut.',
        timestamp: new Date().toISOString(),
        isError: true
      }]);
    } finally {
      setIsLoading(false);
    }
  }, [sessionId, user]);

  const startNewSession = useCallback(() => {
    const newSessionId = uuidv4();
    setSessionId(newSessionId);
    setMessages([]);
  }, []);

  return {
    messages,
    isLoading,
    sendMessage,
    sessionId,
    startNewSession,
    user
  };
};
```

#### Docker-Konfiguration (Optional – nur bei Container-Variante)

> **Hinweis:** Diese Konfiguration wird nur benötigt, wenn du das Frontend als
> separaten Docker-Container betreiben möchtest. Die empfohlene Variante ist,
> das Frontend als statische Dateien direkt vom bestehenden nginx auszuliefern
> (siehe Kapitel 4).

```dockerfile
# alice-frontend/Dockerfile (Optional)
FROM node:20-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

```nginx
# alice-frontend/nginx.conf (Optional – nur bei Container-Variante)
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # API-Proxy wird vom Haupt-nginx übernommen
}
```

---

## 4. Konfigurationen

### 4.1 Architektur-Entscheidung: Kein separater Frontend-Container

Da du bereits einen funktionierenden nginx-Reverse-Proxy (`nginx.happy-mining.de`) betreibst, nutzen wir diesen direkt für Alice. Das React-Frontend wird als statische Dateien gebaut und vom bestehenden nginx ausgeliefert.

**Vorteile:**

- Kein zusätzlicher Container
- Einfacheres Deployment
- Weniger Ressourcenverbrauch
- Einheitliche TLS-Terminierung

**Struktur:**

```text
nginx Container (bestehend)
├── /etc/nginx/conf.d/
│   ├── happy-mining.conf     # Bestehendes Setup
│   └── alice.conf            # NEU: Alice-Konfiguration
└── /usr/share/nginx/html/
    └── alice/                # NEU: React Build-Dateien
        ├── index.html
        ├── static/
        │   ├── js/
        │   └── css/
        └── ...
```

### 4.2 nginx-Konfiguration für Alice

Neue Datei: `./nginx/conf.d/alice.conf`

```nginx
# ============================================================
# Alice - KI-First Smart Home Assistant
# ============================================================

# HTTP -> HTTPS Redirect
server {
    listen 80;
    server_name alice.happy-mining.de;
    return 301 https://$host$request_uri;
}

# HTTPS Server Block
server {
    listen 443 ssl;
    http2 on;
    server_name alice.happy-mining.de;

    # TLS - gleiche Zertifikate wie happy-mining.de
    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/private-key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_cache shared:SSL:10m;
    add_header Strict-Transport-Security "max-age=31536000" always;

    resolver 127.0.0.11 ipv6=off valid=30s;

    # Frontend: React Build als statische Dateien
    root /usr/share/nginx/html/alice;
    index index.html;

    # SPA-Routing: Alle Pfade -> index.html
    location / {
        try_files $uri $uri/ /index.html;
        
        # Cache für Assets
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2)$ {
            expires 1y;
            add_header Cache-Control "public, immutable";
        }
    }

    # API: /api/webhook/* -> n8n
    set $n8n_upstream http://n8n:5678;

    location ^~ /api/webhook/ {
        # CORS
        add_header Access-Control-Allow-Origin "https://alice.happy-mining.de" always;
        add_header Vary Origin always;
        add_header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type, Authorization" always;
        add_header Access-Control-Allow-Credentials "true" always;

        if ($request_method = OPTIONS) {
            return 204;
        }

        # Rewrite: /api/webhook/alice -> /webhook/alice
        rewrite ^/api/(.*)$ /$1 break;
        proxy_pass $n8n_upstream;
        
        # Proxy-Header
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        
        # Längere Timeouts für LLM-Responses
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        
        # Kein Buffering für Streaming
        proxy_buffering off;
    }

    # Health-Check
    location /health {
        access_log off;
        return 200 "OK\n";
        add_header Content-Type text/plain;
    }

    # Logging
    access_log /var/log/nginx/alice_access.log;
    error_log /var/log/nginx/alice_error.log;
}
```

### 4.3 nginx docker-compose.yml Erweiterung

Deine bestehende nginx-Konfiguration muss nur um ein Volume erweitert werden:

```yaml
# infra/docker-compose.yml (Auszug)
nginx:
    image: nginx:1.27-alpine
    container_name: nginx
    networks: [frontend, backend]
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/conf.d:/etc/nginx/conf.d:ro
      - ./nginx/snippets:/etc/nginx/snippets:ro
      - ./certs:/etc/nginx/certs:ro
      - ./nginx/html:/usr/share/nginx/html:ro          # Enthält jetzt auch /alice
      - /srv/warm/logs/nginx:/var/log/nginx
    # ... rest bleibt gleich
```

### 4.4 Frontend Build & Deployment

Da das Frontend nicht als Container läuft, brauchst du ein Build-Script:

```bash
#!/bin/bash
# scripts/deploy-frontend.sh

set -e
FRONTEND_DIR="$(dirname "$0")/../frontend"
NGINX_HTML_DIR="/srv/docker/infra/nginx/html/alice"  # Anpassen!

echo "🔨 Building Alice Frontend..."
cd "$FRONTEND_DIR"

# Dependencies & Build
npm ci
npm run build

# Deploy
rm -rf "$NGINX_HTML_DIR"/*
cp -r build/* "$NGINX_HTML_DIR/"
chown -R root:root "$NGINX_HTML_DIR"

# nginx reload
docker exec nginx nginx -s reload

echo "✅ Deployed to https://alice.happy-mining.de"
```

**Nutzung:**

```bash
cd /path/to/alice
./scripts/deploy-frontend.sh
```

### 4.5 Alternative: Frontend als separater Container

Falls du doch einen separaten Container bevorzugst (z.B. für CI/CD):

```yaml
# alice/docker-compose.yml (nur wenn Container gewünscht)
version: '3.8'

services:
  alice-frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: alice-frontend
    restart: unless-stopped
    networks:
      - frontend
    expose:
      - "80"  # Nur intern, nginx routet hierher
    environment:
      - REACT_APP_API_URL=https://alice.happy-mining.de/api

networks:
  frontend:
    external: true
```

In diesem Fall muss die nginx-Konfiguration angepasst werden:

```nginx
# Statt root /usr/share/nginx/html/alice:
location / {
    proxy_pass http://alice-frontend:80;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
}
```

### 4.6 Pi-hole DNS-Eintrag

```text
# Local DNS Records
alice.happy-mining.de -> 192.168.x.x (IP des nginx-Servers)
```

### 4.7 n8n Environment Variables

```env
# In n8n .env oder Docker-Compose
HA_URL=http://homeassistant.local:8123
HA_TOKEN=eyJ0eXAiOiJKV1QiLCJhbGc...
OLLAMA_URL=http://ollama-3090:11434
WEAVIATE_URL=http://weaviate:8080
POSTGRES_CONNECTION=postgresql://user:pass@postgres:5432/alice
REDIS_URL=redis://redis:6379
MQTT_URL=mqtt://mqtt:1883
JWT_SECRET=<generiert mit: openssl rand -base64 32>
```

### 4.8 Ollama Modell-Download

```bash
# Auf dem Server ausführen
docker exec -it ollama-3090 ollama pull qwen2.5:14b-instruct-q5_K_M
```

---

## 5. Implementierungsschritte

### Phase 1.1: Basis-Infrastruktur (Woche 1)

| # | Aufgabe | Dauer | Abhängigkeit |
| - | :------ | :---- | :----------- |
| 1.1.1 | Pi-hole DNS-Eintrag für alice.happy-mining.de | 15 min | - |
| 1.1.2 | nginx-Konfiguration für Alice | 30 min | 1.1.1 |
| 1.1.3 | PostgreSQL Schema erstellen (alice.*) inkl. **Users-Tabelle** | 45 min | - |
| 1.1.4 | **Initiale User anlegen (andreas, partner, gast)** | 15 min | 1.1.3 |
| 1.1.5 | Weaviate Collections erstellen (AliceMemory + DMS) | 1 h | - |
| 1.1.6 | Qwen2.5:14b Modell herunterladen | 30 min | - |
| 1.1.7 | HA Long-Lived Token erstellen | 15 min | - |
| 1.1.8 | n8n Environment Variables konfigurieren | 30 min | 1.1.7 |

### Phase 1.2: n8n Workflows (Woche 2)

| # | Aufgabe | Dauer | Abhängigkeit |
| - | :------ | :---- | :----------- |
| 1.2.1 | Workflow: alice-chat-handler (Grundgerüst) | 2 h | 1.1.* |
| 1.2.2 | Memory-Loading-Logik implementieren | 2 h | 1.2.1 |
| 1.2.3 | Tool-Definitionen im System-Prompt | 1 h | 1.2.2 |
| 1.2.4 | Sub-Workflow: alice-tool-ha | 2 h | 1.2.1 |
| 1.2.5 | Sub-Workflow: alice-tool-search | 2 h | 1.2.1 |
| 1.2.6 | Memory-Speicherung nach Response | 1 h | 1.2.2 |
| 1.2.7 | Error-Handling und Fallbacks | 2 h | 1.2.* |
| 1.2.8 | Workflow-Tests via Postman/curl | 2 h | 1.2.* |

### Phase 1.3: React Frontend (Woche 3)

| # | Aufgabe | Dauer | Abhängigkeit |
| - | :------ | :---- | :----------- |
| 1.3.1 | React-Projekt initialisieren (Vite + TypeScript) | 30 min | - |
| 1.3.2 | **Auth-Provider und Auth-Context erstellen** | 1.5 h | 1.3.1 |
| 1.3.3 | **Auth-Service (Placeholder für Phase 1.5)** | 1 h | 1.3.1 |
| 1.3.4 | Chat-Komponenten erstellen | 4 h | 1.3.2 |
| 1.3.5 | API-Service mit Auth-Header implementieren | 1.5 h | 1.3.2, 1.3.3 |
| 1.3.6 | useChat Hook mit User-Integration | 1 h | 1.3.4, 1.3.5 |
| 1.3.7 | Session-Management (localStorage) | 1 h | 1.3.4 |
| 1.3.8 | Styling (Tailwind CSS) | 2 h | 1.3.4 |
| 1.3.9 | **Deploy-Script erstellen** | 30 min | 1.3.* |
| 1.3.10 | **nginx html/alice Ordner anlegen** | 15 min | 1.1.2 |
| 1.3.11 | **Erster Build & Deploy nach nginx** | 30 min | 1.3.9, 1.3.10 |
| 1.3.12 | Integration-Tests | 2 h | 1.3.* |

### Phase 1.4: DMS-Pipeline (Woche 4)

| # | Aufgabe | Dauer | Abhängigkeit |
| - | :------ | :---- | :----------- |
| 1.4.1 | NAS-Ordnerstruktur anlegen | 30 min | - |
| 1.4.2 | NAS-Mount in Docker konfigurieren | 1 h | 1.4.1 |
| 1.4.3 | MQTT Topics definieren | 15 min | - |
| 1.4.4 | Workflow: alice-dms-scanner | 2 h | 1.4.2, 1.4.3 |
| 1.4.5 | Workflow: alice-dms-processor | 4 h | 1.4.4 |
| 1.4.6 | LLM Extraction-Prompts optimieren | 2 h | 1.4.5 |
| 1.4.7 | Test mit 10 Beispiel-Dokumenten | 2 h | 1.4.* |
| 1.4.8 | Fehlerbehandlung und Logging | 1 h | 1.4.5 |

### Phase 1.5: Memory-Transfer & Optimierung (Woche 5)

| # | Aufgabe | Dauer | Abhängigkeit |
| - | :------ | :---- | :----------- |
| 1.5.1 | Workflow: alice-memory-transfer | 3 h | 1.2.2 |
| 1.5.2 | Importance-Scoring implementieren | 2 h | 1.5.1 |
| 1.5.3 | Session-Summary-Generierung | 2 h | 1.5.1 |
| 1.5.4 | Latenz-Metriken in Prometheus | 2 h | 1.2.* |
| 1.5.5 | Grafana-Dashboard für Alice | 2 h | 1.5.4 |
| 1.5.6 | End-to-End-Tests | 2 h | alle |
| 1.5.7 | Dokumentation im Repository | 2 h | alle |
| 1.5.8 | Git-Commit aller Workflows | 1 h | alle |

---

## 6. Testfälle und Akzeptanzkriterien

### 6.1 Chat-Grundfunktion

| Test | Eingabe | Erwartetes Ergebnis | Akzeptanzkriterium |
| :--- | :------ | :------------------ | :----------------- |
| T1.1 | "Hallo Alice" | Freundliche Begrüßung | Antwort in < 3s |
| T1.2 | "Wie spät ist es?" | Aktuelle Uhrzeit | Korrekte Zeit ± 1 min |
| T1.3 | "Was ist die Hauptstadt von Frankreich?" | "Paris" | Faktisch korrekt |

### 6.2 Home Assistant Integration

| Test | Eingabe | Erwartetes Ergebnis | Akzeptanzkriterium |
| :--- | :------ | :------------------ | :----------------- |
| T2.1 | "Schalte das Licht im Wohnzimmer ein" | Licht geht an, Bestätigung | HA-State = "on" |
| T2.2 | "Mach das Bürolicht aus" | Licht geht aus, Bestätigung | HA-State = "off" |
| T2.3 | "Dimme das Schlafzimmerlicht auf 50%" | Helligkeit angepasst | brightness ≈ 127 |
| T2.4 | "Welche Lichter sind an?" | Liste der aktiven Lichter | Korrekte Auflistung |

### 6.3 Memory-Funktion

| Test | Eingabe | Erwartetes Ergebnis | Akzeptanzkriterium |
| :--- | :------ | :------------------ | :----------------- |
| T3.1 | "Merk dir: Mein Lieblingsessen ist Pizza" | Bestätigung | In user_profiles gespeichert |
| T3.2 | [Neue Session] "Was ist mein Lieblingsessen?" | "Pizza" | Aus Memory abgerufen |
| T3.3 | "Worüber haben wir letzte Woche gesprochen?" | Zusammenfassung | Semantic Search funktioniert |

### 6.4 DMS-Suche

| Test | Eingabe | Erwartetes Ergebnis | Akzeptanzkriterium |
| :--- | :------ | :------------------ | :----------------- |
| T4.1 | "Zeig mir Stromrechnungen von 2024" | Liste mit Rechnungen | Korrekte Filterung |
| T4.2 | "Was habe ich letztes Jahr für Versicherungen ausgegeben?" | Summe mit Details | Beträge korrekt addiert |
| T4.3 | "Finde Dokumente über Solaranlage" | Semantisch passende Treffer | Relevante Ergebnisse |

### 6.5 Performance

| Metrik | Zielwert | Maximum | Messmethode |
| :----- | :------- | :------ | :---------- |
| Einfache Antwort | < 2s | 4s | Prometheus histogram |
| HA-Steuerung | < 3s | 5s | Prometheus histogram |
| Dokumentensuche | < 4s | 8s | Prometheus histogram |
| DMS-Verarbeitung pro Dokument | < 30s | 60s | Log-Analyse |

---

## 7. Risiken und Mitigationen

| Risiko | Wahrscheinlichkeit | Auswirkung | Mitigation |
| :----- | :----------------- | :--------- | :--------- |
| Qwen2.5 Tool-Calling unzuverlässig | Mittel | Hoch | Fallback auf strukturierten Output mit JSON-Parsing |
| Latenz überschreitet Zielwerte | Mittel | Mittel | Modell-Quantisierung anpassen, Caching einführen |
| VRAM-Konflikt Ollama/Weaviate | Niedrig | Hoch | GPU-Zuweisung strikt trennen (3090 vs. TITAN X) |
| NAS-Mount instabil | Niedrig | Mittel | Lokaler Puffer, Retry-Logik |
| Weaviate-Vektorisierung langsam | Mittel | Niedrig | Batch-Verarbeitung, nächtliche Ausführung |
| LLM halluziniert HA-Entities | Mittel | Mittel | Entity-Validierung vor API-Call, Whitelist |

---

## 8. Rollback-Plan

### 8.1 Komponenten-Rollback

| Komponente | Rollback-Aktion | Dauer |
| :--------- | :-------------- | :---- |
| Frontend | Container stoppen, alter Zustand via Git | 5 min |
| n8n Workflows | Workflow-Version zurücksetzen (Git) | 10 min |
| PostgreSQL Schema | Schema droppen, kein Datenverlust anderer Systeme | 5 min |
| Weaviate Collections | Collection löschen (AliceMemory, DMS) | 5 min |
| nginx Config | Alte Config wiederherstellen | 5 min |

### 8.2 Vollständiger Rollback

```bash
# 1. Alice-Container stoppen
docker compose -f alice/docker-compose.yml down

# 2. nginx-Config entfernen
rm /etc/nginx/conf.d/alice.conf
docker exec nginx nginx -s reload

# 3. DNS-Eintrag entfernen (Pi-hole)

# 4. PostgreSQL Schema droppen
docker exec postgres psql -U user -c "DROP SCHEMA alice CASCADE;"

# 5. Weaviate Collections löschen
curl -X DELETE http://weaviate:8080/v1/schema/AliceMemory
curl -X DELETE http://weaviate:8080/v1/schema/Rechnung
# ... weitere Collections

# 6. Git-Änderungen reverten
cd alice && git reset --hard HEAD~X
```

---

## 9. Anhang

### A. System-Prompt für Alice

```text
Du bist Alice, ein intelligenter Assistent für Andreas' Smart Home und persönliche Dokumentenverwaltung.

## Deine Persönlichkeit
- Freundlich, hilfsbereit und effizient
- Du sprichst Deutsch und duzt Andreas
- Du antwortest präzise und vermeidest unnötige Füllwörter
- Bei technischen Themen kannst du ins Detail gehen

## Deine Fähigkeiten (Tools)

### home_assistant
Steuere Lichter und Schalter im Smart Home.
- Verfügbare Entities: {ENTITY_LIST}
- Aktionen: turn_on, turn_off, toggle, set_brightness

### search_documents
Durchsuche das Dokumentenarchiv (Rechnungen, Kontoauszüge, Verträge, E-Mails).
- Nutze semantische Suche für relevante Ergebnisse
- Filter nach Typ und Zeitraum möglich

### remember
Speichere wichtige Informationen für später.

### recall
Rufe früher gespeicherte Informationen ab.

## Kontext aus früheren Gesprächen
{RELEVANT_MEMORIES}

## Bekannte Fakten über Andreas
{USER_PROFILE}

## Aktuelle Konversation
{WORKING_MEMORY}

## Regeln
1. Nutze Tools nur wenn nötig
2. Bestätige Aktionen immer
3. Bei Unklarheiten: nachfragen
4. Keine Aktionen ohne explizite Anfrage
```

### B. Weaviate Schema-Initialisierung

```bash
#!/bin/bash
# init-weaviate-schema.sh

WEAVIATE_URL="http://weaviate:8080"

# AliceMemory Collection
curl -X POST "${WEAVIATE_URL}/v1/schema" \
  -H "Content-Type: application/json" \
  -d @schemas/alice-memory.json

# DMS Collections
curl -X POST "${WEAVIATE_URL}/v1/schema" \
  -H "Content-Type: application/json" \
  -d @schemas/rechnung.json

curl -X POST "${WEAVIATE_URL}/v1/schema" \
  -H "Content-Type: application/json" \
  -d @schemas/kontoauszug.json

curl -X POST "${WEAVIATE_URL}/v1/schema" \
  -H "Content-Type: application/json" \
  -d @schemas/dokument.json

curl -X POST "${WEAVIATE_URL}/v1/schema" \
  -H "Content-Type: application/json" \
  -d @schemas/email.json

curl -X POST "${WEAVIATE_URL}/v1/schema" \
  -H "Content-Type: application/json" \
  -d @schemas/wertpapier-abrechnung.json

echo "Schema-Initialisierung abgeschlossen!"
```

### C. Projekt-Repository-Struktur

```text
alice/
├── README.md
├── docker-compose.yml
├── .env.example
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Auth/                    # Auth-Komponenten
│   │   │   │   ├── AuthProvider.jsx
│   │   │   │   ├── LoginScreen.jsx      # Phase 1.5
│   │   │   │   ├── ProtectedRoute.jsx   # Phase 1.5
│   │   │   │   └── UserMenu.jsx
│   │   │   ├── Chat/
│   │   │   ├── Sidebar/
│   │   │   └── common/
│   │   ├── hooks/
│   │   │   ├── useAuth.js
│   │   │   ├── useChat.js
│   │   │   └── useSession.js
│   │   ├── services/
│   │   │   ├── api.js
│   │   │   └── auth.js
│   │   ├── App.jsx
│   │   └── index.jsx
│   ├── public/
│   ├── package.json
│   └── Dockerfile                       # Optional: nur für Container-Variante
├── workflows/
│   ├── alice-chat-handler.json
│   ├── alice-tool-ha.json
│   ├── alice-tool-search.json
│   ├── alice-memory-transfer.json
│   ├── alice-dms-scanner.json
│   ├── alice-dms-processor.json
│   └── auth/                            # Phase 1.5 Auth-Workflows
│       ├── alice-auth-login.json
│       ├── alice-auth-validate.json
│       ├── alice-auth-refresh.json
│       └── alice-auth-logout.json
├── schemas/
│   ├── alice-memory.json
│   ├── rechnung.json
│   ├── kontoauszug.json
│   ├── dokument.json
│   ├── email.json
│   └── wertpapier-abrechnung.json
├── sql/
│   ├── init-postgres.sql                # Inkl. Users-Tabelle
│   └── seed-users.sql                   # Initiale User
├── scripts/
│   ├── deploy-frontend.sh               # Build & Deploy nach nginx
│   ├── init-weaviate-schema.sh
│   ├── backup-workflows.sh
│   └── set-user-password.sh             # Phase 1.5
├── nginx/
│   └── alice.conf                       # Wird nach infra/nginx/conf.d/ kopiert
└── docs/
    ├── API.md
    └── TROUBLESHOOTING.md
```

---

## 10. Phase 1.5: Authentifizierung (Optionale Zwischenphase)

> **Hinweis:** Phase 1.5 ist eine optionale Zwischenphase, die nach Abschluss von Phase 1
> und vor Phase 2 durchgeführt werden kann. Sie kann auch parallel zu Beginn von Phase 2
> umgesetzt werden, sollte aber vor der Speaker-ID-Integration abgeschlossen sein.

### 10.1 Ziel

Vollständige Benutzer-Authentifizierung für die WebApp mit:

- Passwort-basiertem Login
- JWT-Token-Management
- Session-Verwaltung
- Vorbereitung für WebAuthn (Phase 2)

### 10.2 Scope

| Komponente | Phase 1.5 | Phase 2 |
| :--------- | :-------- | :------ |
| User/Passwort Login | ✅ | - |
| JWT-Tokens | ✅ | - |
| Login-Screen UI | ✅ | - |
| Password Reset | ✅ | - |
| WebAuthn/Passkeys | ❌ | ✅ |
| Speaker-ID-Verknüpfung | ❌ | ✅ |
| Biometrische Auth | ❌ | ✅ |

### 10.3 Technische Komponenten

#### n8n Auth-Workflows

```text
alice-auth-login          POST /webhook/alice/auth/login
alice-auth-validate       GET  /webhook/alice/auth/validate
alice-auth-refresh        POST /webhook/alice/auth/refresh
alice-auth-logout         POST /webhook/alice/auth/logout
alice-auth-password-reset POST /webhook/alice/auth/password-reset
```

#### Login-Workflow Logik

```javascript
// alice-auth-login (n8n Workflow)
const { username, password } = $json;

// 1. User aus DB laden
const user = await postgres.query(`
  SELECT id, username, display_name, password_hash, role, permissions,
         failed_login_attempts, locked_until, is_active
  FROM alice.users 
  WHERE username = $1
`, [username]);

if (!user.rows[0]) {
  return { error: 'Ungültige Anmeldedaten', status: 401 };
}

const userData = user.rows[0];

// 2. Account-Status prüfen
if (!userData.is_active) {
  return { error: 'Account deaktiviert', status: 403 };
}

if (userData.locked_until && new Date(userData.locked_until) > new Date()) {
  return { error: 'Account temporär gesperrt', status: 423 };
}

// 3. Passwort prüfen (bcrypt)
const bcrypt = require('bcrypt');
const passwordValid = await bcrypt.compare(password, userData.password_hash);

if (!passwordValid) {
  // Failed attempts erhöhen
  await postgres.query(`
    UPDATE alice.users 
    SET failed_login_attempts = failed_login_attempts + 1,
        locked_until = CASE 
          WHEN failed_login_attempts >= 4 THEN NOW() + INTERVAL '15 minutes'
          ELSE locked_until
        END
    WHERE id = $1
  `, [userData.id]);
  
  return { error: 'Ungültige Anmeldedaten', status: 401 };
}

// 4. JWT generieren
const jwt = require('jsonwebtoken');
const token = jwt.sign(
  { 
    userId: userData.id, 
    username: userData.username,
    role: userData.role 
  },
  process.env.JWT_SECRET,
  { expiresIn: '7d' }
);

// 5. Session in DB speichern
const tokenHash = await bcrypt.hash(token, 10);
await postgres.query(`
  INSERT INTO alice.auth_sessions (user_id, token_hash, device_info, ip_address, expires_at)
  VALUES ($1, $2, $3, $4, NOW() + INTERVAL '7 days')
`, [userData.id, tokenHash, $json.device_info || {}, $json.ip_address]);

// 6. Login-Counter zurücksetzen, last_login aktualisieren
await postgres.query(`
  UPDATE alice.users 
  SET failed_login_attempts = 0, locked_until = NULL, last_login = NOW()
  WHERE id = $1
`, [userData.id]);

// 7. Response
return {
  token,
  user: {
    id: userData.id,
    username: userData.username,
    displayName: userData.display_name,
    role: userData.role,
    permissions: userData.permissions
  }
};
```

#### Frontend: LoginScreen Komponente

```jsx
// src/components/Auth/LoginScreen.jsx
import React, { useState } from 'react';
import { useAuth } from './AuthProvider';

const LoginScreen = () => {
  const { login, isLoading } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    
    const result = await login(username, password);
    
    if (!result.success) {
      setError(result.error);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-900 px-4">
      <div className="max-w-md w-full space-y-8">
        {/* Logo/Header */}
        <div className="text-center">
          <h1 className="text-4xl font-bold text-white">Alice</h1>
          <p className="mt-2 text-gray-400">Dein Smart Home Assistent</p>
        </div>

        {/* Login Form */}
        <form onSubmit={handleSubmit} className="mt-8 space-y-6">
          {error && (
            <div className="bg-red-900/50 border border-red-500 text-red-200 px-4 py-3 rounded">
              {error}
            </div>
          )}

          <div className="space-y-4">
            <div>
              <label htmlFor="username" className="text-gray-300 text-sm">
                Benutzername
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                autoComplete="username"
                className="mt-1 w-full px-4 py-3 bg-gray-800 border border-gray-700 
                         rounded-lg text-white focus:ring-2 focus:ring-blue-500 
                         focus:border-transparent"
                placeholder="andreas"
              />
            </div>

            <div>
              <label htmlFor="password" className="text-gray-300 text-sm">
                Passwort
              </label>
              <div className="relative">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  className="mt-1 w-full px-4 py-3 bg-gray-800 border border-gray-700 
                           rounded-lg text-white focus:ring-2 focus:ring-blue-500 
                           focus:border-transparent"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400"
                >
                  {showPassword ? '🙈' : '👁️'}
                </button>
              </div>
            </div>
          </div>

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 
                     disabled:bg-gray-600 text-white font-medium rounded-lg 
                     transition-colors"
          >
            {isLoading ? 'Anmelden...' : 'Anmelden'}
          </button>

          {/* Phase 2: WebAuthn Button (Placeholder) */}
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <div className="w-full border-t border-gray-700" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="px-2 bg-gray-900 text-gray-500">
                Demnächst verfügbar
              </span>
            </div>
          </div>

          <button
            type="button"
            disabled
            className="w-full py-3 px-4 bg-gray-800 text-gray-500 
                     font-medium rounded-lg cursor-not-allowed 
                     flex items-center justify-center gap-2"
          >
            <span>🔐</span>
            Mit Fingerabdruck anmelden
          </button>
        </form>
      </div>
    </div>
  );
};

export default LoginScreen;
```

### 10.4 Implementierungsschritte Phase 1.5

| # | Aufgabe | Dauer | Abhängigkeit |
| - | :------ | :---- | :----------- |
| 1.5.1 | bcrypt und jsonwebtoken in n8n installieren | 30 min | - |
| 1.5.2 | JWT_SECRET in Environment Variables | 15 min | - |
| 1.5.3 | Workflow: alice-auth-login | 2 h | 1.5.1, 1.5.2 |
| 1.5.4 | Workflow: alice-auth-validate | 1 h | 1.5.3 |
| 1.5.5 | Workflow: alice-auth-refresh | 1 h | 1.5.3 |
| 1.5.6 | Workflow: alice-auth-logout | 30 min | 1.5.3 |
| 1.5.7 | Initiale Passwörter für User setzen | 30 min | 1.5.3 |
| 1.5.8 | LoginScreen Komponente | 2 h | - |
| 1.5.9 | AuthProvider um echtes Login erweitern | 1 h | 1.5.4 |
| 1.5.10 | ProtectedRoute Komponente | 1 h | 1.5.9 |
| 1.5.11 | Logout-Funktionalität | 30 min | 1.5.6 |
| 1.5.12 | Password-Reset (optional) | 2 h | 1.5.3 |
| 1.5.13 | Integration-Tests | 2 h | alle |

**Geschätzte Gesamtdauer: 1 Woche**

### 10.5 Sicherheitshinweise

- **JWT_SECRET**: Mindestens 256-bit, sicher generiert (`openssl rand -base64 32`)
- **Passwort-Hashing**: bcrypt mit cost factor 12
- **Token-Expiration**: 7 Tage für Web, kürzer für Mobile
- **Rate-Limiting**: Max 5 Login-Versuche pro 15 Minuten
- **HTTPS**: Zwingend erforderlich (bereits via nginx konfiguriert)

---

## 11. Nächste Schritte nach Phase 1

Nach erfolgreichem Abschluss von Phase 1:

1. **Review durchführen** – Lessons Learned dokumentieren
2. **Latenz-Baseline** als Referenz für Phase 2 sichern
3. **Entscheidung Phase 1.5** – Auth jetzt oder parallel zu Phase 2?
4. **Feinkonzept Phase 2 erstellen** – Fokus: Sprache, TTS/STT, Speaker-ID, WebAuthn
5. **User-Feedback sammeln** – Was funktioniert gut, was nicht?

---

*Erstellt: Januar 2025*
*Autor: Claude (Anthropic) in Zusammenarbeit mit Andreas*
