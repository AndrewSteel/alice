---
paths:
  - "workflows/**"
---

## n8n Development Rules

### Core Behavior

1. **Silent execution** - No commentary between tools
2. **Parallel by default** - Execute independent operations simultaneously
3. **Templates first** - Always check before building (2,709 available)
4. **Multi-level validation** - Quick check → Full validation → Workflow validation
5. **Never trust defaults** - Explicitly configure ALL parameters

### Attribution & Credits

- **MANDATORY TEMPLATE ATTRIBUTION**: Share author name, username, and n8n.io link
- **Template validation** - Always validate before deployment (may need updates)

### Performance

- **Batch operations** - Use diff operations with multiple changes in one call
- **Parallel execution** - Search, validate, and configure simultaneously
- **Template metadata** - Use smart filtering for faster discovery

### Code Node Usage

- **Avoid when possible** - Prefer standard nodes
- **Only when necessary** - Use code node as last resort
- **AI tool capability** - ANY node can be an AI tool (not just marked ones)

### Loops: No Loop-in-Loop

n8n does not support nesting a Split In Batches / loop node inside another loop node within the same workflow.

- **Prefer no loop at all**: if the per-item work can happen in a single pass of standard/Code nodes over the full item list, skip the loop entirely (e.g. fetch all records in one query, transform in one Code node, write in one batch call) rather than looping just because a collection of items is involved.
- **One loop is fine**: iterating a flat list of items in a single loop node is the normal case.
- **Need a second, independent loop dimension?** (e.g. loop over collections, then loop over records per collection) — do not nest a second loop node in the same workflow. Instead call a sub-workflow (Execute Workflow node) from inside the outer loop, and put the inner loop inside that sub-workflow. This is the established pattern in this repo (see `alice-dms-processor`'s Phase B / BankTransaction extraction).
- **Workflows with a time limit** (`time_limit_seconds` pattern, see PROJ-92/94/96/95) require a real loop node — the time check runs once per iteration, after each individual item is processed. Don't try to replace this loop with a single bulk pass; the time check needs a per-item checkpoint to stop cleanly mid-run.

### Most Popular n8n Nodes (for get_node_essentials):

1. **n8n-nodes-base.code** - JavaScript/Python scripting
2. **n8n-nodes-base.httpRequest** - HTTP API calls
3. **n8n-nodes-base.webhook** - Event-driven triggers
4. **n8n-nodes-base.set** - Data transformation
5. **n8n-nodes-base.if** - Conditional routing
6. **n8n-nodes-base.manualTrigger** - Manual workflow execution
7. **n8n-nodes-base.respondToWebhook** - Webhook responses
8. **n8n-nodes-base.scheduleTrigger** - Time-based triggers
9. **@n8n/n8n-nodes-langchain.agent** - AI agents
10. **n8n-nodes-base.googleSheets** - Spreadsheet integration
11. **n8n-nodes-base.merge** - Data merging
12. **n8n-nodes-base.switch** - Multi-branch routing
13. **n8n-nodes-base.telegram** - Telegram bot integration
14. **@n8n/n8n-nodes-langchain.lmChatOpenAi** - OpenAI chat models
15. **n8n-nodes-base.splitInBatches** - Batch processing
16. **n8n-nodes-base.openAi** - OpenAI legacy node
17. **n8n-nodes-base.gmail** - Email automation
18. **n8n-nodes-base.function** - Custom functions
19. **n8n-nodes-base.stickyNote** - Workflow documentation
20. **n8n-nodes-base.executeWorkflowTrigger** - Sub-workflow calls

**Note:** LangChain nodes use the `@n8n/n8n-nodes-langchain.` prefix, core nodes use `n8n-nodes-base.`
