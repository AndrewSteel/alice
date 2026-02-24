# Alice Phase 1.2 - HA-First Workflow-Architektur

## Dokumentstatus

| Attribut | Wert |
|----------|------|
| **Dokumenttyp** | Feinkonzept |
| **Phase** | 1.2 |
| **Version** | 2.0 |
| **Status** | Entwurf |
| **Basiert auf** | Feinkonzept Phase 1 v1.0 |
| **Repository** | https://github.com/AndrewSteel/alice |

---

## 1. Scope und Ziele

### 1.1 Phasenziel

Aufbau eines **schnellen HA-Schnellpfads** für Home Assistant Steuerung mit:
- Weaviate-basierter Intent-Erkennung (statt LLM-Router)
- Multi-Intent-Unterstützung ("Licht an UND Musik lauter")
- Automatische Synchronisation mit HA-Entities
- Latenz < 200ms für einfache HA-Befehle
- Fallback zu LLM für komplexe Anfragen

### 1.2 Abgrenzung (nicht in Phase 1.2)

- Parameter-Extraktion aus Text ("auf 50 Prozent")
- Kontext-basierte Entity-Auflösung ("mach es heller")
- Bestätigungs-Dialoge für sicherheitskritische Aktionen
- Voice-spezifische Optimierungen

### 1.3 Erfolgskriterien

| Kriterium | Messung |
|-----------|---------|
| Einfacher HA-Befehl | < 200ms End-to-End |
| Multi-Intent (2-3 Befehle) | < 400ms End-to-End |
| Intent-Erkennung Accuracy | > 90% bei Standard-Befehlen |
| Auto-Sync funktioniert | Neue Entity → Intent in < 60s |
| Fallback funktioniert | Unbekannter Befehl → LLM-Antwort |

---

## 2. Designprinzipien

### 2.1 HA-First: Schnelle Haussteuerung hat Priorität

| Anfrage-Typ | Ziel-Latenz | Pfad |
|-------------|-------------|------|
| HA-Steuerung (einfach) | < 200ms | Weaviate → HA API |
| HA-Steuerung (multi) | < 400ms | Split → Weaviate → HA API (parallel) |
| Fragen / Chat | < 3000ms | LLM mit Tools |
| DMS-Suche | < 2000ms | Weaviate Semantic Search |

### 2.2 Multi-Intent-Unterstützung

Natürliche Sprache enthält oft mehrere Befehle:
- "Dimme das Licht im Wohnzimmer **und** schalte den Fernseher ein"
- "Rolladen runter, Licht aus, Gute-Nacht-Szene aktivieren"
- "Mach die Musik leiser **und dann** das Licht heller"

### 2.3 Automatische Synchronisation

Neue HA-Entities bekommen automatisch passende Intents in Weaviate:
- HA-Restart → Full Sync aller Entities
- Entity hinzugefügt → Incremental Sync
- Entity gelöscht → Intents entfernen

---

## 3. Architektur-Übersicht

### 3.1 Request-Flow mit Multi-Intent

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User Input                                   │
│    "Dimme das Licht im Wohnzimmer und schalte den Fernseher ein"   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 0: Sentence Splitter                               (~5ms)     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │  Trenne bei: "und", "dann", "außerdem", Komma, Punkt        │    │
│  │  → Teil 1: "Dimme das Licht im Wohnzimmer"                  │    │
│  │  → Teil 2: "schalte den Fernseher ein"                      │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 1: Intent-Erkennung (Weaviate) - PARALLEL          (~50ms)    │
│  ┌──────────────────────────┐    ┌──────────────────────────┐       │
│  │  nearText: Teil 1        │    │  nearText: Teil 2        │       │
│  │  → dim, light, 0.94      │    │  → turn_on, media, 0.92  │       │
│  │  → entity: light.wz      │    │  → entity: tv.wz         │       │
│  └──────────────────────────┘    └──────────────────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
                                │
                    ┌───────────┴───────────┐
                    │ Alle Teile HA-Intent? │
                    └───────────┬───────────┘
                       Ja │           │ Nein (mind. 1 Teil ohne Intent)
                          ▼           ▼
┌──────────────────────────────┐  ┌──────────────────────────────────┐
│  STEP 2a: HA-Schnellpfad     │  │  STEP 2b: Hybrid/LLM-Pfad        │
│          (~100ms)            │  │          (~1-3s)                  │
│                              │  │                                   │
│  • Berechtigungen prüfen     │  │  • HA-Intents zuerst ausführen   │
│  • Parallele HA API Calls    │  │  • Rest an LLM übergeben         │
│  • Template-Antwort          │  │  • Tool-Calling für Komplexes    │
└──────────────────────────────┘  └──────────────────────────────────┘
                    │                         │
                    └───────────┬─────────────┘
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│  STEP 3: Response & Logging                                         │
│  • Kurze Bestätigung: "Licht gedimmt, Fernseher eingeschaltet"     │
│  • Message in PostgreSQL speichern                                  │
│  • Gesamtlatenz: ~200ms (HA-only) / ~2s (mit LLM)                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Sync-Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Home Assistant │────▶│     MQTT        │────▶│      n8n        │
│  Event:         │     │  alice/ha/sync  │     │  Workflow       │
│  - ha_start     │     └─────────────────┘     │  alice-ha-sync  │
│  - entity_new   │                             └─────────────────┘
│  - entity_del   │                                     │
└─────────────────┘                                     ▼
                                               ┌─────────────────┐
                                               │  1. HA API      │
                                               │  2. Diff mit DB │
                                               │  3. Generate    │
                                               │  4. Weaviate    │
                                               └─────────────────┘
```

---

## 4. Komponenten im Detail

### 4.1 Sentence Splitter

```javascript
/**
 * Teilt einen Multi-Intent-Satz in einzelne Befehle
 * @param {string} text - Eingabe-Text
 * @returns {string[]} - Array von Teil-Sätzen
 */
function splitMultiIntent(text) {
  // Trennwörter und Patterns (Reihenfolge wichtig!)
  const separatorPatterns = [
    /\s+und\s+dann\s+/gi,      // "und dann" zuerst
    /\s+und\s+danach\s+/gi,
    /\s+und\s+außerdem\s+/gi,
    /\s+und\s+/gi,             // "und" allein
    /\s+dann\s+/gi,
    /\s+danach\s+/gi,
    /\s+außerdem\s+/gi,
    /\s+sowie\s+/gi,
    /\s+zusätzlich\s+/gi,
    /\s+auch\s+noch\s+/gi,
    /,\s+/g,                   // Komma
    /\.\s+/g                   // Punkt (neuer Satz)
  ];
  
  let parts = [text];
  
  for (const pattern of separatorPatterns) {
    const newParts = [];
    for (const part of parts) {
      const split = part.split(pattern);
      newParts.push(...split);
    }
    parts = newParts;
  }
  
  // Cleanup
  return parts
    .map(p => p.trim())
    .map(p => p.replace(/^(bitte|mal|noch|auch)\s+/gi, ''))  // Füllwörter entfernen
    .filter(p => p.length >= 4);  // Mindestlänge
}

// Beispiele:
// "Dimme das Licht und schalte den TV ein"
// → ["Dimme das Licht", "schalte den TV ein"]

// "Rolladen runter, Licht aus, Gute Nacht"
// → ["Rolladen runter", "Licht aus", "Gute Nacht"]
```

### 4.2 Parallele Intent-Erkennung

```javascript
/**
 * Erkennt Intents für mehrere Teile parallel via Weaviate
 * @param {string[]} parts - Aufgeteilte Satz-Teile
 * @returns {Promise<IntentResult[]>} - Intent pro Teil
 */
async function detectIntentsParallel(parts) {
  const weaviateUrl = $env.WEAVIATE_URL;
  const minCertainty = parseFloat($env.INTENT_MIN_CERTAINTY || '0.82');
  
  // Parallele Suchen starten
  const searchPromises = parts.map(async (part, index) => {
    const query = {
      query: `{
        Get {
          HAIntent(
            nearText: {
              concepts: ["${part.replace(/"/g, '\\"')}"]
              certainty: 0.78
            }
            limit: 3
          ) {
            utterance
            intent
            domain
            service
            entityId
            areaId
            areaName
            parameters
            requiresConfirmation
            priority
            _additional { certainty }
          }
        }
      }`
    };
    
    try {
      const response = await fetch(`${weaviateUrl}/v1/graphql`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(query)
      });
      
      const result = await response.json();
      const intents = result.data?.Get?.HAIntent || [];
      
      // Besten Treffer auswählen (höchste Certainty über Threshold)
      const bestIntent = intents
        .filter(i => i._additional.certainty >= minCertainty)
        .sort((a, b) => {
          // Erst nach Certainty, dann nach Priority
          const certDiff = b._additional.certainty - a._additional.certainty;
          if (Math.abs(certDiff) > 0.03) return certDiff;
          return (b.priority || 5) - (a.priority || 5);
        })[0];
      
      return {
        partIndex: index,
        originalText: part,
        intent: bestIntent || null,
        isHAIntent: bestIntent !== null,
        certainty: bestIntent?._additional.certainty || 0
      };
    } catch (error) {
      return {
        partIndex: index,
        originalText: part,
        intent: null,
        isHAIntent: false,
        certainty: 0,
        error: error.message
      };
    }
  });
  
  return Promise.all(searchPromises);
}
```

### 4.3 Request-Klassifizierung

```javascript
/**
 * Entscheidet über den Verarbeitungspfad basierend auf Intent-Ergebnissen
 * @param {IntentResult[]} results - Intent-Ergebnisse pro Teil
 * @returns {ProcessingDecision}
 */
function classifyRequest(results) {
  const haIntents = results.filter(r => r.isHAIntent);
  const nonHAIntents = results.filter(r => !r.isHAIntent);
  
  // Fall 1: Alle Teile sind HA-Intents → Schnellpfad
  if (nonHAIntents.length === 0 && haIntents.length > 0) {
    return {
      path: 'HA_FAST',
      haIntents: haIntents,
      llmParts: [],
      requiresConfirmation: haIntents.some(i => i.intent?.requiresConfirmation)
    };
  }
  
  // Fall 2: Keine HA-Intents → LLM-Pfad
  if (haIntents.length === 0) {
    return {
      path: 'LLM_ONLY',
      haIntents: [],
      llmParts: nonHAIntents.map(r => r.originalText),
      originalMessage: results.map(r => r.originalText).join(' ')
    };
  }
  
  // Fall 3: Gemischt → Hybrid (HA zuerst, dann LLM)
  return {
    path: 'HYBRID',
    haIntents: haIntents,
    llmParts: nonHAIntents.map(r => r.originalText),
    executeOrder: ['HA', 'LLM']
  };
}
```

### 4.4 Parallele HA-Ausführung

```javascript
/**
 * Führt mehrere HA-Befehle parallel aus
 * @param {IntentResult[]} haIntents - Zu ausführende Intents
 * @param {string} userId - User für Berechtigungsprüfung
 * @returns {Promise<HAResult[]>}
 */
async function executeHAIntentsParallel(haIntents, userId) {
  const haUrl = $env.HA_URL;
  const haToken = $env.HA_TOKEN;
  
  const executePromises = haIntents.map(async (intentResult) => {
    const intent = intentResult.intent;
    
    // 1. Berechtigung prüfen (optional, wenn User-System aktiv)
    // const hasPermission = await checkHAPermission(userId, intent.domain, intent.entityId);
    // if (!hasPermission) return { success: false, error: 'permission_denied', ... };
    
    // 2. Bestätigung erforderlich?
    if (intent.requiresConfirmation) {
      return {
        success: false,
        requiresConfirmation: true,
        intent: intent.intent,
        entity: intent.entityId,
        message: `Soll ich wirklich ${intent.intent} für ${intent.entityId} ausführen?`
      };
    }
    
    // 3. Service-Call vorbereiten
    const [domain, serviceName] = intent.service.split('.');
    let serviceData = {};
    
    if (intent.entityId) {
      serviceData.entity_id = intent.entityId;
    }
    
    // Parameter aus Intent übernehmen
    if (intent.parameters) {
      try {
        const params = typeof intent.parameters === 'string' 
          ? JSON.parse(intent.parameters) 
          : intent.parameters;
        serviceData = { ...serviceData, ...params };
      } catch (e) {
        console.warn('Failed to parse intent parameters:', e);
      }
    }
    
    // 4. HA API Call
    try {
      const response = await fetch(
        `${haUrl}/api/services/${domain}/${serviceName}`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${haToken}`,
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(serviceData)
        }
      );
      
      return {
        success: response.ok,
        intent: intent.intent,
        domain: intent.domain,
        entity: intent.entityId,
        area: intent.areaName,
        service: intent.service,
        status: response.status
      };
    } catch (error) {
      return {
        success: false,
        error: error.message,
        intent: intent.intent,
        entity: intent.entityId
      };
    }
  });
  
  return Promise.all(executePromises);
}
```

### 4.5 Schnelle Antwort-Generierung

```javascript
/**
 * Generiert eine schnelle Template-basierte Antwort
 * @param {HAResult[]} results - Ausführungsergebnisse
 * @returns {string}
 */
function generateQuickResponse(results) {
  const successful = results.filter(r => r.success);
  const failed = results.filter(r => !r.success && !r.requiresConfirmation);
  const needsConfirm = results.filter(r => r.requiresConfirmation);
  
  // Antwort-Templates (deutsche Verben)
  const actionNames = {
    turn_on: 'eingeschaltet',
    turn_off: 'ausgeschaltet',
    toggle: 'umgeschaltet',
    dim: 'gedimmt',
    brightness_up: 'heller gemacht',
    brightness_down: 'dunkler gemacht',
    volume_up: 'lauter gemacht',
    volume_down: 'leiser gemacht',
    mute: 'stumm geschaltet',
    play: 'gestartet',
    pause: 'pausiert',
    stop: 'gestoppt',
    next: 'nächster Titel',
    previous: 'vorheriger Titel',
    open: 'geöffnet',
    close: 'geschlossen',
    activate: 'aktiviert',
    start: 'gestartet',
    temperature_up: 'wärmer gestellt',
    temperature_down: 'kühler gestellt'
  };
  
  const parts = [];
  
  // Erfolgreiche Aktionen zusammenfassen
  if (successful.length === 1) {
    const r = successful[0];
    const action = actionNames[r.intent] || r.intent;
    const target = r.area || r.entity?.split('.')[1]?.replace(/_/g, ' ') || 'Gerät';
    parts.push(`${target} ${action}`);
  } else if (successful.length > 1) {
    const actions = successful.map(r => {
      const action = actionNames[r.intent] || r.intent;
      const target = r.area || r.entity?.split('.')[1]?.replace(/_/g, ' ') || '';
      return `${target} ${action}`.trim();
    });
    parts.push(actions.join(', '));
  }
  
  // Fehlgeschlagene melden
  if (failed.length > 0) {
    const failedNames = failed.map(r => r.entity?.split('.')[1] || 'Gerät').join(', ');
    parts.push(`Fehler bei: ${failedNames}`);
  }
  
  // Bestätigung erforderlich
  if (needsConfirm.length > 0) {
    return needsConfirm[0].message;
  }
  
  if (parts.length === 0) {
    return "Erledigt.";
  }
  
  // Erste Buchstabe groß
  let response = parts.join('. ');
  return response.charAt(0).toUpperCase() + response.slice(1) + '.';
}
```

---

## 5. Datenmodell

### 5.1 PostgreSQL Schema

```sql
-- ============================================================
-- ALICE Phase 1.2 - HA Intent Sync Schema
-- ============================================================

-- Intent-Templates: Basis-Patterns pro Domain
CREATE TABLE IF NOT EXISTS alice.ha_intent_templates (
    id SERIAL PRIMARY KEY,
    domain VARCHAR(50) NOT NULL,           -- "light", "switch", "climate", etc.
    intent VARCHAR(50) NOT NULL,           -- "turn_on", "turn_off", "dim", etc.
    service VARCHAR(100) NOT NULL,         -- "light.turn_on", "switch.turn_off"
    
    -- Sentence-Patterns mit Platzhaltern:
    -- {name}  = friendly_name oder alias des Entity
    -- {area}  = Area-Name (Wohnzimmer, Küche, etc.)
    -- {where} = "im {area}" oder "{name}" - flexibel
    patterns JSONB NOT NULL,               -- ["Licht an {where}", "{name} einschalten"]
    
    -- Optionale Default-Parameter für den Service-Call
    default_parameters JSONB,              -- {"brightness_pct": 50}
    
    -- Sicherheit
    requires_confirmation BOOLEAN DEFAULT FALSE,
    
    -- Metadaten
    language VARCHAR(5) DEFAULT 'de',
    priority INT DEFAULT 5,                -- Höher = wichtiger bei Konflikten
    is_active BOOLEAN DEFAULT TRUE,
    source VARCHAR(50) DEFAULT 'manual',   -- "manual", "github", "custom"
    notes TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    UNIQUE(domain, intent, language)
);

-- Entity-Tracking: Aktueller Stand der HA-Entities
CREATE TABLE IF NOT EXISTS alice.ha_entities (
    id SERIAL PRIMARY KEY,
    entity_id VARCHAR(255) NOT NULL UNIQUE,
    domain VARCHAR(50) NOT NULL,
    friendly_name VARCHAR(255),
    
    -- Area-Zuordnung
    area_id VARCHAR(100),
    area_name VARCHAR(100),
    
    -- Zusätzliche Namen/Aliase für das Entity
    aliases JSONB DEFAULT '[]',
    
    -- HA-spezifische Attribute
    device_class VARCHAR(50),
    supported_features INT DEFAULT 0,
    unit_of_measurement VARCHAR(20),
    
    -- Sync-Status
    last_seen_at TIMESTAMPTZ DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    weaviate_synced BOOLEAN DEFAULT FALSE,
    intents_count INT DEFAULT 0,
    
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sync-Log: Protokollierung aller Sync-Vorgänge
CREATE TABLE IF NOT EXISTS alice.ha_sync_log (
    id SERIAL PRIMARY KEY,
    sync_type VARCHAR(20) NOT NULL,        -- "full", "incremental"
    trigger_source VARCHAR(50),            -- "mqtt", "manual", "scheduled"
    
    entities_found INT DEFAULT 0,
    entities_added INT DEFAULT 0,
    entities_removed INT DEFAULT 0,
    entities_updated INT DEFAULT 0,
    intents_generated INT DEFAULT 0,
    intents_removed INT DEFAULT 0,
    
    duration_ms INT,
    status VARCHAR(20) DEFAULT 'running',
    error_message TEXT,
    details JSONB,
    
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- Indizes
CREATE INDEX IF NOT EXISTS idx_intent_templates_domain 
    ON alice.ha_intent_templates(domain, is_active);
CREATE INDEX IF NOT EXISTS idx_ha_entities_domain 
    ON alice.ha_entities(domain);
CREATE INDEX IF NOT EXISTS idx_ha_entities_sync 
    ON alice.ha_entities(is_active, weaviate_synced);
```

### 5.2 Weaviate HAIntent Schema

```json
{
  "class": "HAIntent",
  "description": "Home Assistant Steuerungsbefehle für schnelle Intent-Erkennung",
  "vectorizer": "text2vec-transformers",
  "vectorIndexConfig": { "distance": "cosine" },
  "moduleConfig": {
    "text2vec-transformers": { "vectorizeClassName": false }
  },
  "properties": [
    {
      "name": "utterance",
      "description": "Beispiel-Äußerung (wird vektorisiert)",
      "dataType": ["text"],
      "indexSearchable": true
    },
    {
      "name": "intent",
      "description": "Intent-Name (turn_on, turn_off, dim, etc.)",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "domain",
      "description": "HA-Domain (light, switch, climate, etc.)",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "service",
      "description": "HA-Service (light.turn_on, etc.)",
      "dataType": ["text"],
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "entityId",
      "description": "Zugeordnete HA Entity ID",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "areaId",
      "description": "HA Area ID",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "areaName",
      "description": "Lesbarer Area-Name",
      "dataType": ["text"],
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "parameters",
      "description": "Service-Parameter als JSON",
      "dataType": ["text"],
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "language",
      "description": "Sprache (de, en)",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "priority",
      "description": "Priorität (1-10)",
      "dataType": ["int"],
      "indexFilterable": true
    },
    {
      "name": "requiresConfirmation",
      "description": "Bestätigung erforderlich?",
      "dataType": ["boolean"],
      "indexFilterable": true
    },
    {
      "name": "source",
      "description": "Quelle: manual, auto_generated",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    },
    {
      "name": "sourceEntity",
      "description": "Quell-Entity für auto-generierte Intents",
      "dataType": ["text"],
      "indexFilterable": true,
      "moduleConfig": { "text2vec-transformers": { "skip": true } }
    }
  ]
}
```

---

## 6. Automatischer Intent-Sync

### 6.1 Intent-Generator Algorithmus

```
Für jede Entity in (neue + geänderte):
    Templates = get_templates(entity.domain)
    
    Für jedes Template:
        Für jedes Pattern in Template.patterns:
            
            Falls "{name}" in Pattern:
                Namen = [entity.friendly_name] + entity.aliases
                Für jeden Namen:
                    utterance = Pattern.replace("{name}", Name)
                    → Weaviate.insert(utterance, entity_id, ...)
            
            Falls "{area}" in Pattern UND entity.area_name:
                utterance = Pattern.replace("{area}", entity.area_name)
                → Weaviate.insert(utterance, entity_id, ...)
            
            Falls "{where}" in Pattern:
                Varianten = []
                Falls entity.area_name:
                    Varianten.add("im " + entity.area_name)
                    Varianten.add("in der " + entity.area_name)
                Varianten.add(entity.friendly_name)
                Varianten.addAll(entity.aliases)
                
                Für jede Variante:
                    utterance = Pattern.replace("{where}", Variante)
                    → Weaviate.insert(utterance, entity_id, ...)
```

### 6.2 Home Assistant Automations

```yaml
# Sync bei HA-Start
- id: alice_sync_on_start
  alias: "Alice: Sync bei HA-Start"
  trigger:
    - platform: homeassistant
      event: start
  action:
    - delay: "00:00:30"
    - service: mqtt.publish
      data:
        topic: "alice/ha/sync"
        payload: '{"event": "ha_start", "sync_type": "full"}'

# Sync bei neuer Entity
- id: alice_sync_on_entity_created
  alias: "Alice: Sync bei neuer Entity"
  trigger:
    - platform: event
      event_type: entity_registry_updated
  condition:
    - condition: template
      value_template: "{{ trigger.event.data.action == 'create' }}"
  action:
    - delay: "00:00:05"
    - service: mqtt.publish
      data:
        topic: "alice/ha/sync"
        payload: >-
          {"event": "entity_created", "entity_id": "{{ trigger.event.data.entity_id }}"}

# Sync bei gelöschter Entity
- id: alice_sync_on_entity_removed
  alias: "Alice: Sync bei gelöschter Entity"
  trigger:
    - platform: event
      event_type: entity_registry_updated
  condition:
    - condition: template
      value_template: "{{ trigger.event.data.action == 'remove' }}"
  action:
    - service: mqtt.publish
      data:
        topic: "alice/ha/sync"
        payload: >-
          {"event": "entity_removed", "entity_id": "{{ trigger.event.data.entity_id }}"}
```

---

## 7. n8n Workflow-Struktur

### 7.1 Haupt-Workflow: alice-chat-handler (erweitert)

```
┌─────────────┐
│  Webhook    │
│  POST /chat │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│  Validate   │────▶│  Load User  │
│  Request    │     │  & Session  │
└─────────────┘     └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Sentence   │
                    │  Splitter   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Weaviate   │  (parallel für alle Teile)
                    │  Intent     │
                    │  Detection  │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Classify   │
                    │  Request    │
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
   │  HA_FAST    │  │   HYBRID    │  │  LLM_ONLY   │
   │  Path       │  │   Path      │  │  Path       │
   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
          │                │                │
          └────────────────┼────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Response   │
                    │  & Logging  │
                    └─────────────┘
```

### 7.2 Sub-Workflow: alice-ha-intent-sync

```
┌─────────────┐
│  MQTT       │
│  Trigger    │
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│  Log Start  │────▶│  Fetch HA   │
│  Sync       │     │  Entities   │
└─────────────┘     └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Compare    │
                    │  with DB    │
                    └──────┬──────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
       ▼                   ▼                   ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Process    │     │  Process    │     │  Process    │
│  Added      │     │  Updated    │     │  Removed    │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Generate   │
                    │  Intents    │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Update     │
                    │  Weaviate   │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Update     │
                    │  PostgreSQL │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │  Log        │
                    │  Complete   │
                    └─────────────┘
```

---

## 8. Implementierungsschritte

### 8.1 Phase 1.2.1 - Infrastruktur & Schema (4h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.1.1 | PostgreSQL Schema erstellen (ha_intent_templates, ha_entities, ha_sync_log) | 30 min | - |
| 1.2.1.2 | PostgreSQL Indizes und Trigger anlegen | 15 min | 1.2.1.1 |
| 1.2.1.3 | Weaviate HAIntent Collection erstellen (mit Schema v2) | 30 min | - |
| 1.2.1.4 | Weaviate Collection testen (Insert + nearText Query) | 30 min | 1.2.1.3 |
| 1.2.1.5 | n8n Environment Variables ergänzen (INTENT_MIN_CERTAINTY, etc.) | 15 min | - |
| 1.2.1.6 | n8n Credentials für MQTT einrichten | 30 min | - |
| 1.2.1.7 | MQTT Topic alice/ha/sync in Mosquitto testen | 15 min | 1.2.1.6 |
| 1.2.1.8 | Qwen3:14b herunterladen (ollama pull qwen3:14b) | 30 min | - |

### 8.2 Phase 1.2.2 - Intent-Templates (3h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.2.1 | Intent-Templates für Domain "light" erstellen (turn_on, turn_off, dim, brightness) | 30 min | 1.2.1.1 |
| 1.2.2.2 | Intent-Templates für Domain "switch" erstellen | 15 min | 1.2.1.1 |
| 1.2.2.3 | Intent-Templates für Domain "cover" erstellen (open, close, stop) | 15 min | 1.2.1.1 |
| 1.2.2.4 | Intent-Templates für Domain "media_player" erstellen (volume, play, pause, next) | 30 min | 1.2.1.1 |
| 1.2.2.5 | Intent-Templates für Domain "climate" erstellen | 15 min | 1.2.1.1 |
| 1.2.2.6 | Intent-Templates für Domain "scene" erstellen | 15 min | 1.2.1.1 |
| 1.2.2.7 | Intent-Templates für sicherheitskritische Domains (lock, alarm) mit requires_confirmation | 15 min | 1.2.1.1 |
| 1.2.2.8 | Templates in PostgreSQL importieren und verifizieren | 30 min | 1.2.2.1-7 |

### 8.3 Phase 1.2.3 - Sentence Splitter (2h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.3.1 | Sentence Splitter Funktion implementieren (n8n Code Node) | 45 min | - |
| 1.2.3.2 | Testfälle für Splitter definieren (10+ verschiedene Patterns) | 30 min | - |
| 1.2.3.3 | Splitter mit Testfällen verifizieren | 30 min | 1.2.3.1, 1.2.3.2 |
| 1.2.3.4 | Edge Cases behandeln (Füllwörter, Satzzeichen, Mindestlänge) | 15 min | 1.2.3.1 |

### 8.4 Phase 1.2.4 - Intent-Erkennung (4h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.4.1 | Weaviate nearText Query Builder implementieren | 30 min | 1.2.1.3 |
| 1.2.4.2 | Parallele Intent-Detection implementieren (Promise.all) | 45 min | 1.2.4.1 |
| 1.2.4.3 | Request-Klassifizierung implementieren (HA_FAST, HYBRID, LLM_ONLY) | 30 min | 1.2.4.2 |
| 1.2.4.4 | Certainty-Threshold konfigurierbar machen | 15 min | 1.2.4.2 |
| 1.2.4.5 | Test-Intents in Weaviate laden (manuell, 20-30 Beispiele) | 30 min | 1.2.1.3 |
| 1.2.4.6 | Intent-Erkennung mit Test-Intents verifizieren | 45 min | 1.2.4.2, 1.2.4.5 |
| 1.2.4.7 | Logging für Intent-Detection implementieren | 30 min | 1.2.4.2 |

### 8.5 Phase 1.2.5 - HA-Schnellpfad (4h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.5.1 | HA Service-Call Funktion implementieren | 45 min | - |
| 1.2.5.2 | Parallele HA-Ausführung implementieren (Promise.all) | 30 min | 1.2.5.1 |
| 1.2.5.3 | Berechtigungsprüfung einbauen (alice.user_ha_permissions) | 30 min | 1.2.5.1 |
| 1.2.5.4 | Bestätigungs-Handling für requiresConfirmation | 30 min | 1.2.5.1 |
| 1.2.5.5 | Quick-Response-Generator implementieren | 30 min | - |
| 1.2.5.6 | HA-Schnellpfad im Hauptworkflow integrieren | 30 min | 1.2.5.2, 1.2.5.5, 1.2.4.3 |
| 1.2.5.7 | End-to-End Test: Single HA-Befehl | 30 min | 1.2.5.6 |
| 1.2.5.8 | End-to-End Test: Multi HA-Befehl | 30 min | 1.2.5.6 |

### 8.6 Phase 1.2.6 - LLM-Integration (4h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.6.1 | LLM_ONLY Pfad implementieren (bestehenden Chat-Handler nutzen) | 45 min | 1.2.4.3 |
| 1.2.6.2 | HYBRID Pfad implementieren (HA zuerst, dann LLM) | 45 min | 1.2.5.6, 1.2.6.1 |
| 1.2.6.3 | HA-Ergebnisse in LLM-Kontext einbauen | 30 min | 1.2.6.2 |
| 1.2.6.4 | Fallback bei Weaviate-Fehler zu LLM | 30 min | 1.2.6.1 |
| 1.2.6.5 | Test: "Was ist das Wetter und mach das Licht an" (Hybrid) | 30 min | 1.2.6.2 |
| 1.2.6.6 | Test: "Erzähl mir einen Witz" (LLM_ONLY) | 15 min | 1.2.6.1 |
| 1.2.6.7 | Test: Weaviate nicht erreichbar → Fallback | 15 min | 1.2.6.4 |

### 8.7 Phase 1.2.7 - Auto-Sync (6h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.7.1 | HA Automations erstellen (MQTT Trigger bei Start/Entity-Änderung) | 30 min | 1.2.1.7 |
| 1.2.7.2 | n8n Workflow alice-ha-intent-sync erstellen (Grundgerüst) | 30 min | 1.2.1.6 |
| 1.2.7.3 | HA REST API Integration (fetch /api/states, /api/config/area_registry) | 45 min | 1.2.7.2 |
| 1.2.7.4 | Entity-Vergleich mit PostgreSQL implementieren (Diff) | 45 min | 1.2.7.3 |
| 1.2.7.5 | Intent-Generator Funktion implementieren (Templates × Entities) | 60 min | 1.2.7.4, 1.2.2.8 |
| 1.2.7.6 | Weaviate Batch-Import implementieren | 45 min | 1.2.7.5 |
| 1.2.7.7 | Weaviate Cleanup für gelöschte/geänderte Entities | 30 min | 1.2.7.5 |
| 1.2.7.8 | PostgreSQL Update (ha_entities, sync_log) | 30 min | 1.2.7.4 |
| 1.2.7.9 | Test: Manueller Full-Sync via MQTT | 30 min | 1.2.7.1-8 |
| 1.2.7.10 | Test: HA Restart → automatischer Sync | 30 min | 1.2.7.9 |
| 1.2.7.11 | Test: Neue Entity in HA → Intent erscheint | 30 min | 1.2.7.9 |

### 8.8 Phase 1.2.8 - Response & Logging (3h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.8.1 | Response-Zusammenführung für alle Pfade | 30 min | 1.2.5.6, 1.2.6.2 |
| 1.2.8.2 | Message-Logging in PostgreSQL (alice.messages) | 30 min | 1.2.8.1 |
| 1.2.8.3 | Latenz-Metriken erfassen (Prometheus Format) | 45 min | 1.2.8.1 |
| 1.2.8.4 | Error-Handling und sinnvolle Fehlermeldungen | 30 min | 1.2.8.1 |
| 1.2.8.5 | Statistik-View in PostgreSQL (v_ha_sync_stats) | 15 min | 1.2.7.8 |
| 1.2.8.6 | Grafana Dashboard erweitern (Intent-Detection Latenz) | 30 min | 1.2.8.3 |

### 8.9 Phase 1.2.9 - Tests & Optimierung (4h)

| # | Aufgabe | Dauer | Abhängigkeit |
|---|---------|-------|--------------|
| 1.2.9.1 | Testmatrix erstellen (20+ Testfälle für alle Pfade) | 30 min | - |
| 1.2.9.2 | Alle Testfälle durchführen und dokumentieren | 60 min | 1.2.9.1, alle |
| 1.2.9.3 | Latenz-Messungen (P50, P95, P99) | 30 min | 1.2.9.2 |
| 1.2.9.4 | Certainty-Threshold optimieren basierend auf Tests | 30 min | 1.2.9.2 |
| 1.2.9.5 | Fehlende Intent-Patterns ergänzen | 30 min | 1.2.9.2 |
| 1.2.9.6 | Dokumentation aktualisieren (README, TROUBLESHOOTING) | 30 min | alle |
| 1.2.9.7 | n8n Workflows exportieren und in Git committen | 30 min | alle |

---

## 9. Aufwandsschätzung Gesamt

| Phase | Beschreibung | Aufwand |
|-------|--------------|---------|
| 1.2.1 | Infrastruktur & Schema | 4h |
| 1.2.2 | Intent-Templates | 3h |
| 1.2.3 | Sentence Splitter | 2h |
| 1.2.4 | Intent-Erkennung | 4h |
| 1.2.5 | HA-Schnellpfad | 4h |
| 1.2.6 | LLM-Integration | 4h |
| 1.2.7 | Auto-Sync | 6h |
| 1.2.8 | Response & Logging | 3h |
| 1.2.9 | Tests & Optimierung | 4h |
| **Gesamt** | | **34h** |

**Geschätzte Dauer:** 1-2 Wochen (bei 3-4h/Tag)

---

## 10. Konfiguration

### 10.1 Environment Variables (n8n)

```env
# Home Assistant
HA_URL=http://homeassistant.local:8123
HA_TOKEN=eyJ0eXAiOiJKV1Q...

# Weaviate
WEAVIATE_URL=http://weaviate:8080

# Ollama
OLLAMA_URL=http://ollama-3090:11434
OLLAMA_MODEL=qwen3:14b

# Intent-Erkennung
INTENT_MIN_CERTAINTY=0.82
INTENT_MAX_RESULTS=3

# MQTT
MQTT_URL=mqtt://mosquitto:1883
```

### 10.2 Performance-Ziele

| Metrik | Ziel | Messung |
|--------|------|---------|
| HA-Befehl (single) | < 200ms | Webhook → Response |
| HA-Befehl (multi, 2-3) | < 400ms | Webhook → Response |
| Intent Detection | < 50ms | Weaviate nearText |
| LLM-Antwort | < 3s | Ollama Response |
| Intent-Sync (full) | < 30s | MQTT → Log Complete |

---

## 11. Fehlerbehandlung

| Fehler | Handling |
|--------|----------|
| Weaviate nicht erreichbar | Fallback zu LLM (kein Schnellpfad) |
| Kein Intent gefunden (alle Teile) | Weiterleitung an LLM |
| HA API Timeout | Retry 1x, dann Fehlermeldung |
| HA API 401 | Token abgelaufen → Fehlermeldung + Log |
| Entity nicht gefunden | "Ich konnte {entity} nicht finden" |
| Sync fehlgeschlagen | Log in ha_sync_log, Benachrichtigung |

---

## 12. Offene Erweiterungen (Phase 2+)

- [ ] Parameter-Extraktion aus Text ("auf 50 Prozent" → 50)
- [ ] Kontext-basierte Entity-Auflösung ("mach es heller" → letztes Licht)
- [ ] Bestätigungs-Dialog für sicherheitskritische Aktionen
- [ ] Voice-spezifische Optimierungen (kürzere Antworten)
- [ ] Lernende Intents (User-Feedback → neue Patterns)
- [ ] GitHub-Sync für offizielle HA Intent-Sentences

---

*Erstellt: Februar 2026*
*Autor: Claude (Anthropic) in Zusammenarbeit mit Andreas*
