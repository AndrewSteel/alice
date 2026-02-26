## PRD Result Template

```markdown
# PRD: [Workflow Name]

**Status:** Draft
**Erstellt:** [Datum]
**Autor:** [Name]

---

## 1. Ziel & Kontext

**Was soll automatisiert werden?**
[1-3 Saetze die das Ziel beschreiben]

**Warum wird diese Automatisierung gebraucht?**
[Business-Kontext, Zeitersparnis, aktueller manueller Prozess]

**Wer nutzt das Ergebnis?**
[Zielgruppe/Empfaenger des Outputs]

---

## 2. Trigger & Zeitplan

| Eigenschaft | Wert |
|---|---|
| Trigger-Typ | [Webhook / Schedule / Manual / Event] |
| Zeitplan | [z.B. Jeden Montag 9:00 / Echtzeit / Bei Bedarf] |
| Zeitzone | [z.B. Europe/Berlin] |
| Erwartetes Volumen | [z.B. 10-50 Ausfuehrungen pro Tag] |

---

## 3. Datenfluss

### Input
- **Quelle:** [Service/API/Webhook]
- **Format:** [JSON / Form Data / CSV / etc.]
- **Beispiel-Payload:**
```json
{
  "beispiel": "daten"
}
```

### Verarbeitung
1. [Schritt 1: Was passiert mit den Daten]
2. [Schritt 2: Transformation/Anreicherung]
3. [Schritt n: ...]

### Output
- **Ziel:** [Service/API/E-Mail/Sheet]
- **Format:** [Beschreibung des Outputs]
- **Empfaenger:** [Wer bekommt das Ergebnis]

---

## 4. Beteiligte Services & Credentials

| Service | Zweck | Credential-Typ | Status |
|---|---|---|---|
| [z.B. YouTube] | [Videos abrufen] | [OAuth2] | [Vorhanden / Fehlt] |
| [z.B. Anthropic] | [AI-Verarbeitung] | [API Key] | [Vorhanden / Fehlt] |
| [z.B. Gmail] | [E-Mail senden] | [OAuth2] | [Vorhanden / Fehlt] |

---

## 5. Workflow-Architektur

### Node-Uebersicht (empfohlen)

| # | Node-Name | Node-Typ | Funktion |
|---|---|---|---|
| 1 | [Name] | [n8n-nodes-base.xyz] | [Was macht der Node] |
| 2 | [Name] | [n8n-nodes-base.xyz] | [Was macht der Node] |
| ... | ... | ... | ... |

### Datenfluss-Diagramm

```
[Trigger] -> [Node 2] -> [Node 3] -> ... -> [Output]
                              |
                              v
                        [Error Branch]
```

### Aggregation & Batching
- [Muessen Daten aggregiert werden bevor sie verarbeitet werden?]
- [Gibt es Batch-Verarbeitung?]
- [Wie viele Items werden erwartet pro Durchlauf?]

---

## 6. Error Handling & Edge Cases

### Fehlerbehandlung

| Fehlertyp | Reaktion |
|---|---|
| API nicht erreichbar | [z.B. Retry 3x, dann Benachrichtigung] |
| Leere Daten | [z.B. Info-Mail senden, Workflow beenden] |
| Rate Limit erreicht | [z.B. Warten und erneut versuchen] |
| Ungueltige Eingabe | [z.B. Validierung, Fehlermeldung] |

### Bekannte Edge Cases
- [Edge Case 1: Beschreibung + gewuenschtes Verhalten]
- [Edge Case 2: Beschreibung + gewuenschtes Verhalten]

### Benachrichtigung bei Fehler
- **Kanal:** [E-Mail / Slack / etc.]
- **Empfaenger:** [Wer wird benachrichtigt]
- **Inhalt:** [Was soll in der Fehlermeldung stehen]

---

## 7. n8n-spezifische Hinweise

### Datenstruktur-Warnungen
- [z.B. YouTube getAll gibt id als Objekt zurueck: $json.id.videoId statt $json.id]
- [z.B. Webhook-Daten liegen unter $json.body, nicht $json]

### Expression-Einschraenkungen
- Kein Optional Chaining (?.) in n8n Expressions - nur in Code Nodes
- Expressions muessen mit = Prefix beginnen wenn sie dynamisch sind

### Aggregation
- [Muessen Items vor AI/E-Mail-Nodes aggregiert werden?]
- [Code Node mit "Run Once for All Items" fuer Aggregation nutzen]

### Error Handling Pattern
- `onError: "continueRegularOutput"` statt deprecated `continueOnFail: true`
- IF-Node fuer Edge Cases (z.B. keine Daten vorhanden)

---

## 8. Akzeptanzkriterien

- [ ] [Kriterium 1: Was muss funktionieren]
- [ ] [Kriterium 2: Was muss funktionieren]
- [ ] [Kriterium 3: Was muss funktionieren]
- [ ] Error Handling getestet (leere Daten, API-Fehler)
- [ ] Workflow-Validierung ohne Errors (Warnings akzeptabel)
- [ ] E2E-Test mit echten Daten erfolgreich

---

## 9. Offene Fragen

- [Frage 1: Was noch geklaert werden muss]
- [Frage 2: Was noch geklaert werden muss]
```

---

## Guidelines for the Agent

### DO:
- Ask ALL clarifying questions before generating the PRD
- Use the n8n-mcp `search_nodes` tool to validate node suggestions
- Include specific n8n node types in the architecture section
- Flag known n8n pitfalls (data structure, expressions, aggregation)
- Save the PRD as a file in the project directory
- Number the workflow steps clearly

### DON'T:
- Skip the clarifying questions phase
- Assume services or credentials - always ask
- Generate vague requirements ("handle errors somehow")
- Include implementation details like exact expressions or code
- Create the workflow - this PRD is INPUT for the build phase

### Quality Checklist (verify before delivering):
- [ ] Every service has a credential status (Vorhanden/Fehlt)
- [ ] Error handling is specified for each external API call
- [ ] Aggregation needs are explicitly stated
- [ ] Data flow is clear: what comes in, what goes out
- [ ] At least 3 acceptance criteria are defined
- [ ] Known n8n pitfalls are documented in Section 7

---

## Integration with Other Skills

### Build Phase (after PRD is approved):
Once the user approves the PRD, they can use the n8n-mcp tools to build:
1. `search_nodes` - Find the right nodes
2. `get_node` - Check node configuration
3. `n8n_create_workflow` - Build the workflow
4. `n8n_validate_workflow` - Validate
5. `n8n_autofix_workflow` - Auto-fix issues
6. `n8n_executions` - Debug runs

### Related Skills:
- **n8n-workflow-patterns** - Architectural patterns for the workflow design
- **n8n-node-configuration** - Detailed node setup guidance
- **n8n-expression-syntax** - Expression rules for n8n
- **n8n-validation-expert** - Validation and debugging
