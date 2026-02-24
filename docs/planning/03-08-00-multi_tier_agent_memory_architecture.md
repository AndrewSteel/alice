# Feinkonzept Phase 3.8 - Multi-Tier Agent Memory: PostgreSQL + Weaviate

## Dokumentstatus

| Attribut | Wert |
| :-------- | :---- |
| **Dokumenttyp** | Feinkonzept |
| **Phase** | 3.8 |
| **Version** | 1.0 |
| **Status** | Entwurf |
| **Basiert auf** | Feinkonzept v1.0 |
| **Repository** | <https://github.com/AndrewSteel/alice> |

---

# 

## Die optimale Architektur: 3-Tier Memory System

```
┌─────────────────────────────────────────────────────────┐
│ TIER 1: Working Memory (PostgreSQL)                    │
│ • Aktuelle Konversation (letzte 10-20 Nachrichten)     │
│ • Strukturierte Metadaten (User-ID, Timestamps)        │
│ • Session-State (aktuelle Aufgaben, Kontext)           │
│ Größe: Klein (immer im Context Window)                 │
│ Zweck: Sofortiger Zugriff, schnell, transaktional      │
└─────────────────────────────────────────────────────────┘
                         ↓ Transfer bei Context-Limit
┌─────────────────────────────────────────────────────────┐
│ TIER 2: Semantic Long-Term Memory (Weaviate)           │
│ • Gesamte Konversationshistorie (vektorisiert!)        │
│ • Semantische Suche über alle Erinnerungen             │
│ • Automatisches "Erinnern" relevanter Kontexte         │
│ Größe: Unbegrenzt (außerhalb Context Window)           │
│ Zweck: Intelligentes Retrieval bei Bedarf              │
└─────────────────────────────────────────────────────────┘
                         ↓ Periodische Konsolidierung
┌─────────────────────────────────────────────────────────┐
│ TIER 3: Summarized Memory (PostgreSQL/Weaviate)        │
│ • LLM-generierte Zusammenfassungen von Sessions        │
│ • Key Facts über den User                              │
│ • Wichtige Entscheidungen & Präferenzen                │
│ Größe: Sehr klein (strukturiert)                       │
│ Zweck: Kompakter Überblick, immer im Context           │
└─────────────────────────────────────────────────────────┘
```

---

## Warum diese Architektur besser ist als Löschen

### ❌ Alte Ansätze (problematisch):

**Ansatz 1: FIFO-Löschen**
```
Problem: "Vergessen" wichtiger früherer Informationen
Beispiel:
- Tag 1: User sagt "Ich habe zwei Kinder"
- Tag 30: GELÖSCHT wegen Overflow
- Tag 31: Agent fragt wieder "Haben Sie Kinder?"
→ Sehr frustrierend für User!
```

**Ansatz 2: Nur Zusammenfassung**
```
Problem: Verlust von Details und Nuancen
Beispiel:
- Original: "Mein Sohn Max studiert Informatik in München, 
             meine Tochter Lisa macht Ausbildung zur Krankenschwester"
- Summary: "User hat zwei Kinder"
→ Wichtige Details verloren!
```

### ✅ Multi-Tier Ansatz (optimal):

```
1. User sagt etwas Wichtiges
   ↓
2. Sofort in PostgreSQL (Working Memory)
   ↓
3. Nach X Tagen → Transfer zu Weaviate (vektorisiert)
   ↓
4. Agent braucht Info später:
   → Semantic Search in Weaviate findet es!
   → Nur relevante Memories in Context laden
   ↓
5. NICHTS geht verloren!
```

---

## Konkrete Implementierung

### Schema 1: PostgreSQL Working Memory

```sql
-- Aktuelle Konversation
CREATE TABLE agent_messages (
    id SERIAL PRIMARY KEY,
    session_id UUID NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL,  -- 'user' oder 'assistant'
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT NOW(),
    metadata JSONB,  -- Flexibel für zusätzliche Infos
    
    -- Für Lifecycle-Management
    transferred_to_weaviate BOOLEAN DEFAULT FALSE,
    transferred_at TIMESTAMP,
    weaviate_id UUID,
    
    -- Index für schnelle Queries
    INDEX idx_session (session_id, timestamp),
    INDEX idx_user_recent (user_id, timestamp DESC)
);

-- Session-Zusammenfassungen
CREATE TABLE agent_session_summaries (
    id SERIAL PRIMARY KEY,
    session_id UUID UNIQUE NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    message_count INT,
    summary TEXT,  -- LLM-generierte Zusammenfassung
    key_facts JSONB,  -- Strukturierte Fakten
    created_at TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_user_summaries (user_id, end_time DESC)
);

-- User-Profil (persistent facts)
CREATE TABLE agent_user_profiles (
    user_id VARCHAR(255) PRIMARY KEY,
    facts JSONB,  -- {"kinder": 2, "wohnort": "München", ...}
    preferences JSONB,  -- {"kommunikationsstil": "direkt", ...}
    last_updated TIMESTAMP DEFAULT NOW()
);
```

### Schema 2: Weaviate Long-Term Memory

```json
{
  "class": "AgentMemory",
  "description": "Langzeit-Erinnerungen des KI-Agenten",
  "vectorizer": "text2vec-transformers",
  "properties": [
    {
      "name": "session_id",
      "dataType": ["text"],
      "description": "UUID der Konversation",
      "indexFilterable": true
    },
    {
      "name": "user_id",
      "dataType": ["text"],
      "description": "Identifikation des Users",
      "indexFilterable": true
    },
    {
      "name": "timestamp",
      "dataType": ["date"],
      "description": "Wann die Interaktion stattfand",
      "indexFilterable": true
    },
    {
      "name": "message_pair",
      "dataType": ["text"],
      "description": "User-Nachricht + Agent-Antwort kombiniert",
      "moduleConfig": {
        "text2vec-transformers": {
          "skip": false,
          "vectorizePropertyName": false
        }
      }
    },
    {
      "name": "user_message",
      "dataType": ["text"],
      "description": "Originaltext vom User"
    },
    {
      "name": "assistant_message",
      "dataType": ["text"],
      "description": "Originaltext vom Agenten"
    },
    {
      "name": "context_summary",
      "dataType": ["text"],
      "description": "Zusammenfassung des Konversationskontexts",
      "moduleConfig": {
        "text2vec-transformers": {
          "skip": false
        }
      }
    },
    {
      "name": "extracted_facts",
      "dataType": ["text"],
      "description": "Wichtige Fakten aus der Konversation",
      "moduleConfig": {
        "text2vec-transformers": {
          "skip": false
        }
      }
    },
    {
      "name": "topics",
      "dataType": ["text[]"],
      "description": "Themen-Tags",
      "indexFilterable": true
    },
    {
      "name": "importance_score",
      "dataType": ["number"],
      "description": "Wie wichtig ist diese Erinnerung? (0-1)",
      "indexFilterable": true
    },
    {
      "name": "postgres_message_id",
      "dataType": ["int"],
      "description": "Verknüpfung zur PostgreSQL Tabelle"
    },
    {
      "name": "embedding_model",
      "dataType": ["text"],
      "description": "Welches Modell wurde verwendet"
    }
  ]
}
```

---

## Workflow 1: Message Processing

### n8n Workflow bei neuer User-Nachricht

```javascript
// Node 1: User-Nachricht empfangen (Webhook)
const userMessage = $json.message;
const userId = $json.user_id;
const sessionId = $json.session_id || generateUUID();

// Node 2: In PostgreSQL speichern (Working Memory)
await postgres.query(`
  INSERT INTO agent_messages (session_id, user_id, role, content)
  VALUES ($1, $2, 'user', $3)
  RETURNING id
`, [sessionId, userId, userMessage]);

// Node 3: Aktuelle Working Memory laden (letzte 20 Nachrichten)
const workingMemory = await postgres.query(`
  SELECT role, content, timestamp
  FROM agent_messages
  WHERE session_id = $1
  ORDER BY timestamp DESC
  LIMIT 20
`, [sessionId]);

// Node 4: Prüfe ob Working Memory zu groß wird
const tokenCount = estimateTokens(workingMemory);

if (tokenCount > 6000) {  // Threshold
  // → Transfer zu Weaviate (siehe Workflow 2)
  triggerTransferWorkflow(sessionId);
}

// Node 5: Semantic Retrieval aus Weaviate (nur relevante Memories!)
const relevantMemories = await weaviate.search({
  class: "AgentMemory",
  nearText: {
    concepts: [userMessage]
  },
  where: {
    path: ["user_id"],
    operator: "Equal",
    valueText: userId
  },
  limit: 5  // Nur top-5 relevante Erinnerungen
});

// Node 6: User-Profil laden
const userProfile = await postgres.query(`
  SELECT facts, preferences
  FROM agent_user_profiles
  WHERE user_id = $1
`, [userId]);

// Node 7: Context zusammenbauen
const context = {
  // Tier 3: Kompakte Facts (immer dabei)
  userFacts: userProfile.facts,
  
  // Tier 1: Aktuelle Konversation (immer dabei)
  recentMessages: workingMemory,
  
  // Tier 2: Relevante Historie (nur bei Bedarf)
  relevantPastContext: relevantMemories
};

// Node 8: LLM-Call
const response = await llm.chat({
  messages: [
    {role: "system", content: buildSystemPrompt(context)},
    ...workingMemory,
    {role: "user", content: userMessage}
  ]
});

// Node 9: Assistant-Antwort speichern
await postgres.query(`
  INSERT INTO agent_messages (session_id, user_id, role, content)
  VALUES ($1, $2, 'assistant', $3)
`, [sessionId, userId, response]);

return response;
```

---

## Workflow 2: Transfer zu Weaviate

### Automatischer Transfer bei Context-Overflow

```javascript
// Trigger: Working Memory zu groß

// Node 1: Alte Nachrichten aus PostgreSQL holen
const oldMessages = await postgres.query(`
  SELECT id, session_id, user_id, role, content, timestamp
  FROM agent_messages
  WHERE session_id = $1
    AND transferred_to_weaviate = FALSE
    AND timestamp < NOW() - INTERVAL '7 days'
  ORDER BY timestamp ASC
`, [sessionId]);

// Node 2: Nachrichten paarweise kombinieren (User + Assistant)
const messagePairs = [];
for (let i = 0; i < oldMessages.length - 1; i += 2) {
  if (oldMessages[i].role === 'user' && oldMessages[i+1].role === 'assistant') {
    messagePairs.push({
      user: oldMessages[i],
      assistant: oldMessages[i+1]
    });
  }
}

// Node 3: Für jedes Paar: Kontext extrahieren mit LLM
for (const pair of messagePairs) {
  // LLM extrahiert Fakten
  const extraction = await llm.chat({
    messages: [{
      role: "user",
      content: `
Analysiere diese Konversation und extrahiere:
1. Wichtige Fakten über den User
2. Themen der Diskussion
3. Wichtigkeit (0-1)

User: ${pair.user.content}
Assistant: ${pair.assistant.content}

Gib JSON zurück:
{
  "facts": ["Fakt 1", "Fakt 2"],
  "topics": ["Topic 1", "Topic 2"],
  "importance": 0.8,
  "summary": "Kurze Zusammenfassung"
}
      `
    }],
    response_format: {type: "json_object"}
  });
  
  const extracted = JSON.parse(extraction);
  
  // Node 4: In Weaviate speichern
  const weaviateId = await weaviate.insert({
    class: "AgentMemory",
    properties: {
      session_id: pair.user.session_id,
      user_id: pair.user.user_id,
      timestamp: pair.user.timestamp,
      
      // Kombinierter Text (wird vektorisiert!)
      message_pair: `User: ${pair.user.content}\nAssistant: ${pair.assistant.content}`,
      
      // Original-Texte
      user_message: pair.user.content,
      assistant_message: pair.assistant.content,
      
      // Extrahierte Informationen (werden auch vektorisiert!)
      context_summary: extracted.summary,
      extracted_facts: extracted.facts.join("; "),
      
      // Metadaten
      topics: extracted.topics,
      importance_score: extracted.importance,
      postgres_message_id: pair.user.id,
      embedding_model: "paraphrase-multilingual-MiniLM-L12-v2"
    }
  });
  
  // Node 5: PostgreSQL aktualisieren (markieren als transferiert)
  await postgres.query(`
    UPDATE agent_messages
    SET transferred_to_weaviate = TRUE,
        transferred_at = NOW(),
        weaviate_id = $1
    WHERE id IN ($2, $3)
  `, [weaviateId, pair.user.id, pair.assistant.id]);
  
  // Node 6: User-Profil aktualisieren (Facts hinzufügen)
  if (extracted.facts.length > 0) {
    await postgres.query(`
      INSERT INTO agent_user_profiles (user_id, facts)
      VALUES ($1, $2)
      ON CONFLICT (user_id) DO UPDATE
      SET facts = agent_user_profiles.facts || $2,
          last_updated = NOW()
    `, [pair.user.user_id, JSON.stringify(extracted.facts)]);
  }
}

// Node 7: Optional - Alte Nachrichten aus PostgreSQL löschen
// (nur wenn sicher in Weaviate gespeichert)
await postgres.query(`
  DELETE FROM agent_messages
  WHERE session_id = $1
    AND transferred_to_weaviate = TRUE
    AND timestamp < NOW() - INTERVAL '30 days'
`, [sessionId]);
```

---

## Workflow 3: Intelligentes Retrieval

### Semantic Memory Recall

```javascript
// Wenn User etwas fragt, das alte Informationen benötigt

// Node 1: User-Frage analysieren
const userQuestion = "Wie hieß nochmal mein Sohn?";

// Node 2: Semantic Search in Weaviate
const memories = await weaviate.query({
  class: "AgentMemory",
  nearText: {
    concepts: [userQuestion]  // Findet "Sohn Max studiert..." auch wenn "Max" nicht in Frage vorkommt!
  },
  where: {
    operator: "And",
    operands: [
      {
        path: ["user_id"],
        operator: "Equal",
        valueText: userId
      },
      {
        path: ["importance_score"],
        operator: "GreaterThan",
        valueNumber: 0.5  // Nur wichtige Memories
      }
    ]
  },
  limit: 10
});

// Node 3: Re-Ranking nach Relevanz & Zeit
const reranked = memories.map(m => ({
  ...m,
  // Kombiniere Semantic Similarity + Recency + Importance
  finalScore: (
    m._additional.distance * 0.5 +  // Semantic Match
    timeDecay(m.timestamp) * 0.3 +  // Neuere = wichtiger
    m.importance_score * 0.2         // Explizite Wichtigkeit
  )
})).sort((a, b) => b.finalScore - a.finalScore);

// Node 4: Top-Ergebnisse in Context laden
const relevantContext = reranked.slice(0, 3).map(m => 
  `[Frühere Konversation vom ${m.timestamp}]\n${m.message_pair}`
).join("\n\n");

// Node 5: LLM-Call mit geladenem Context
const response = await llm.chat({
  messages: [
    {
      role: "system",
      content: `Du bist ein hilfsbereiter Assistent.
      
Hier sind relevante frühere Konversationen:
${relevantContext}

Nutze diese Informationen, um die aktuelle Frage zu beantworten.`
    },
    {role: "user", content: userQuestion}
  ]
});

// Response: "Ihr Sohn heißt Max und studiert Informatik in München."
```

---

## Best Practices

### 1. Wann transferieren?

**Option A: Zeit-basiert (empfohlen)**
```javascript
// Transfer nach 7 Tagen
WHERE timestamp < NOW() - INTERVAL '7 days'
  AND transferred_to_weaviate = FALSE
```

**Option B: Token-basiert**
```javascript
// Transfer wenn Working Memory > 6000 Tokens
if (estimateTokens(workingMemory) > 6000) {
  transferOldestMessages();
}
```

**Option C: Session-basiert**
```javascript
// Transfer wenn Session beendet
ON SESSION_END → transfer entire session
```

**Meine Empfehlung:** Kombination!
- Working Memory: Letzte 7 Tage ODER 6000 Tokens (was zuerst)
- Rest → Weaviate

### 2. Was vektorisieren?

**Gute Praxis:**
```json
{
  // Vektorisieren (für Semantic Search):
  "message_pair": "User: ... Assistant: ...",  // Voller Dialog
  "context_summary": "...",  // LLM-Zusammenfassung
  "extracted_facts": "...",  // Wichtige Fakten
  
  // NICHT vektorisieren:
  "user_id": "12345",  // Metadaten
  "timestamp": "...",  // Metadaten
  "session_id": "..."  // Metadaten
}
```

### 3. Retrieval-Strategie

**Multi-Query Approach:**
```javascript
// Statt nur aktueller User-Nachricht:
const queries = [
  userMessage,  // Original
  await llm.rewrite(userMessage),  // Umformuliert
  await llm.extractKeywords(userMessage)  // Keywords
];

// Suche mit allen Queries, kombiniere Ergebnisse
const allMemories = [];
for (const query of queries) {
  const results = await weaviate.search(query);
  allMemories.push(...results);
}

// Deduplizieren & Re-ranken
const unique = deduplicateByWeaviateId(allMemories);
const ranked = rerankByRelevance(unique);
```

### 4. Wichtigkeit automatisch bestimmen

```javascript
// LLM bewertet Wichtigkeit
const importance = await llm.chat({
  messages: [{
    role: "user",
    content: `
Bewerte die Wichtigkeit dieser Konversation auf einer Skala von 0-1:
- 0: Triviale Smalltalk
- 0.3: Normale Konversation
- 0.7: Wichtige Informationen/Präferenzen
- 1.0: Kritische Fakten (Namen, Adressen, Entscheidungen)

User: ${userMsg}
Assistant: ${assistantMsg}

Gib nur die Zahl zurück.
    `
  }]
});

const score = parseFloat(importance);
```

### 5. Periodische Konsolidierung

**Wöchentlicher Cleanup-Job:**
```javascript
// 1. Session-Zusammenfassungen generieren
const sessions = await postgres.query(`
  SELECT session_id, array_agg(content ORDER BY timestamp) as messages
  FROM agent_messages
  WHERE timestamp BETWEEN NOW() - INTERVAL '7 days' AND NOW()
  GROUP BY session_id
`);

for (const session of sessions) {
  // LLM erstellt Zusammenfassung
  const summary = await llm.summarize(session.messages);
  
  // Speichern
  await postgres.query(`
    INSERT INTO agent_session_summaries (session_id, summary, ...)
    VALUES (...)
  `);
}

// 2. User-Profil aktualisieren
// Fakten aus allen Sessions des Users zusammenführen

// 3. Alte PostgreSQL-Daten archivieren
// (bereits in Weaviate gespeichert)
```

---

## Performance & Skalierung

### Geschätzte Größen

```
User mit 1 Jahr Nutzung:
├── Nachrichten gesamt: ~10.000
├── PostgreSQL (7 Tage): ~200 Nachrichten (~50 KB)
├── Weaviate (10.000): ~10.000 Vektoren (~40 MB)
└── Summaries: ~50 Sessions (~100 KB)

GESAMT RAM: ~50 MB pro User
→ 1000 aktive User = ~50 GB
```

### Optimierungen

**Für Weaviate:**
```yaml
# docker-compose.yml
weaviate:
  environment:
    # Mehr Shards für bessere Performance
    PERSISTENCE_LSM_ACCESS_STRATEGY: "mmap"
    # Cache-Größe erhöhen
    LIMIT_RESOURCES: "false"
```

**Für PostgreSQL:**
```sql
-- Partitionierung nach User oder Zeit
CREATE TABLE agent_messages (...)
PARTITION BY RANGE (timestamp);

-- Indices optimieren
CREATE INDEX CONCURRENTLY idx_working_memory 
ON agent_messages (user_id, timestamp DESC)
WHERE transferred_to_weaviate = FALSE;
```

---

## Monitoring & Debugging

### Dashboard-Metriken

```javascript
// KPIs zu tracken:
const metrics = {
  // Memory-Größen
  workingMemorySize: await countPostgreSQLMessages(),
  longTermMemorySize: await countWeaviateMemories(),
  
  // Retrieval-Performance
  avgRetrievalTime: measureSearchTime(),
  retrievalAccuracy: measureUserSatisfaction(),
  
  // Transfer-Rate
  messagesTransferredToday: countTransfers(),
  
  // Context Window Usage
  avgTokensPerRequest: calculateAvgTokens()
};
```

### Debug-Tools

```javascript
// Memory-Inspector Endpoint
app.get('/debug/memory/:userId', async (req, res) => {
  const userId = req.params.userId;
  
  const debug = {
    workingMemory: await getPostgreSQLMessages(userId),
    longTermMemory: await getWeaviateMemoryCount(userId),
    userProfile: await getUserProfile(userId),
    recentSummaries: await getSessionSummaries(userId, 5)
  };
  
  res.json(debug);
});
```

---

## Zusammenfassung

### ✅ JA, transferieren Sie zu Weaviate!

**Vorteile gegenüber Löschen:**
- Keine Informationsverluste
- Semantisches "Erinnern" bei Bedarf
- Unbegrenzte Historie
- Intelligentere Antworten

**Vorteile gegenüber nur Summarizen:**
- Details bleiben erhalten
- Kontext-spezifisches Retrieval
- Fakten gehen nicht verloren

**Best Practice:**
```
PostgreSQL (Working Memory):
├── Letzte 7 Tage
└── Oder max 6000 Tokens

Weaviate (Long-Term Memory):
├── Gesamte Historie (vektorisiert)
└── Semantic Retrieval bei Bedarf

PostgreSQL (Summaries):
├── Session-Zusammenfassungen
└── User-Profil (Facts)
```

**Das ist die State-of-the-Art Architektur für Production AI Agents!** 🚀
