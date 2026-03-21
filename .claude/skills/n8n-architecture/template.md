## PRD Result Template

```markdown
# PRD: [Workflow Name]

**Status:** Draft
**Created:** [Date]
**Author:** [Name]

---

## 1. Goal & Context

**What should be automated?**
[1-3 sentences describing the goal]

**Why is this automation needed?**
[Business context, time savings, current manual process]

**Who uses the result?**
[Target audience / recipients of the output]

---

## 2. Trigger & Schedule

| Property | Value |
|---|---|
| Trigger Type | [Webhook / Schedule / Manual / Event] |
| Schedule | [e.g. Every Monday 9:00 / Real-time / On demand] |
| Timezone | [e.g. Europe/Berlin] |
| Expected Volume | [e.g. 10-50 executions per day] |

---

## 3. Data Flow

### Input
- **Source:** [Service/API/Webhook]
- **Format:** [JSON / Form Data / CSV / etc.]
- **Example Payload:**
```json
{
  "example": "data"
}
```

### Processing
1. [Step 1: What happens to the data]
2. [Step 2: Transformation/enrichment]
3. [Step n: ...]

### Output
- **Destination:** [Service/API/Email/Sheet]
- **Format:** [Description of output]
- **Recipients:** [Who receives the result]

---

## 4. Services & Credentials

| Service | Purpose | Credential Type | Status |
|---|---|---|---|
| [e.g. PostgreSQL] | [Query data] | [postgres] | [Available / Missing] |
| [e.g. Ollama] | [LLM processing] | [ollamaApi] | [Available / Missing] |
| [e.g. MQTT] | [Event queue] | [mqtt] | [Available / Missing] |

---

## 5. Workflow Architecture

### Node Overview (recommended)

| # | Node Name | Node Type | Function |
|---|---|---|---|
| 1 | [Name] | [n8n-nodes-base.xyz] | [What the node does] |
| 2 | [Name] | [n8n-nodes-base.xyz] | [What the node does] |
| ... | ... | ... | ... |

### Data Flow Diagram

```
[Trigger] -> [Node 2] -> [Node 3] -> ... -> [Output]
                              |
                              v
                        [Error Branch]
```

### Aggregation & Batching
- [Does data need to be aggregated before processing?]
- [Is batch processing needed?]
- [How many items are expected per run?]

---

## 6. Error Handling & Edge Cases

### Error Handling

| Error Type | Response |
|---|---|
| API unreachable | [e.g. Retry 3x, then notify] |
| Empty data | [e.g. Send info notification, end workflow] |
| Rate limit reached | [e.g. Wait and retry] |
| Invalid input | [e.g. Validate, return error message] |

### Known Edge Cases
- [Edge Case 1: Description + desired behavior]
- [Edge Case 2: Description + desired behavior]

### Error Notifications
- **Channel:** [Email / Slack / etc.]
- **Recipients:** [Who gets notified]
- **Content:** [What the error message should include]

---

## 7. n8n-Specific Notes

### Data Structure Warnings
- [e.g. YouTube getAll returns id as object: $json.id.videoId not $json.id]
- [e.g. Webhook data is under $json.body, not $json]

### Expression Constraints
- No optional chaining (?.) in n8n Expressions — only in Code Nodes
- Expressions must start with = prefix when dynamic
- Wrap all `$env` reads in try/catch with fallback values

### Aggregation
- [Do items need to be aggregated before AI/email nodes?]
- [Use Code Node with "Run Once for All Items" for aggregation]

### Error Handling Pattern
- `onError: "continueRegularOutput"` instead of deprecated `continueOnFail: true`
- IF node for edge cases (e.g. no data present)

---

## 8. Acceptance Criteria

- [ ] [Criterion 1: What must work]
- [ ] [Criterion 2: What must work]
- [ ] [Criterion 3: What must work]
- [ ] Error handling tested (empty data, API failures)
- [ ] Workflow validation passes without errors (warnings acceptable)
- [ ] End-to-end test with real data successful

---

## 9. Open Questions

- [Question 1: What still needs clarification]
- [Question 2: What still needs clarification]
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
- Assume services or credentials — always ask
- Generate vague requirements ("handle errors somehow")
- Include implementation details like exact expressions or code
- Create the workflow — this PRD is INPUT for the build phase

### Quality Checklist (verify before delivering):
- [ ] Every service has a credential status (Available/Missing)
- [ ] Error handling is specified for each external API call
- [ ] Aggregation needs are explicitly stated
- [ ] Data flow is clear: what comes in, what goes out
- [ ] At least 3 acceptance criteria are defined
- [ ] Known n8n pitfalls are documented in Section 7

---

## Integration with Other Skills

### Build Phase (after PRD is approved):
Once the user approves the PRD, use n8n-mcp tools to build:
1. `search_nodes` — Find the right nodes
2. `get_node_essentials` — Check node configuration
3. `n8n_create_workflow` — Build the workflow
4. `n8n_validate_workflow` — Validate
5. `n8n_autofix_workflow` — Auto-fix issues
6. `n8n_list_executions` — Debug runs

### Related Skills:
- `/backend` — Build the workflow after this PRD is approved
- `/qa` — Test the workflow against acceptance criteria
- `/deploy` — Deploy to production
