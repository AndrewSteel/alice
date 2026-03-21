# Backend Implementation Checklist

## Core Checklist
- [ ] Checked existing workflows (`ls workflows/`) before creating new ones
- [ ] Checked existing tables via git before creating new ones
- [ ] Database tables created in `alice` PostgreSQL schema (if needed)
- [ ] Row Level Security enabled on ALL new tables
- [ ] RLS policies created for SELECT, INSERT, UPDATE, DELETE
- [ ] Indexes created on performance-critical columns
- [ ] Foreign keys set with appropriate ON DELETE behavior
- [ ] n8n workflow logic implements all acceptance criteria
- [ ] JWT authentication verified in workflow (no access without valid token)
- [ ] Input validation in workflow (IF-node checks or Code node with Zod-style validation)
- [ ] Meaningful error responses with correct HTTP status codes
- [ ] Error handling: `onError: "continueRegularOutput"` + IF node for edge cases
- [ ] Workflow JSON saved to `workflows/`
- [ ] No hardcoded secrets — all credentials via n8n credential store
- [ ] User has reviewed and approved
- [ ] User notified: "Deploy n8n-workflow `<name>`"

## Verification (run before marking complete)
- [ ] Workflow validated via n8n-mcp `validate_workflow`
- [ ] All acceptance criteria from feature spec addressed
- [ ] Triggers and endpoints return correct status codes (test with curl)
- [ ] `features/INDEX.md` status updated to "In Progress"
- [ ] Code committed to git

## Performance Checklist
- [ ] Frequently filtered PostgreSQL columns have indexes
- [ ] No N+1 queries — use PostgreSQL joins or `splitInBatches` node
- [ ] All list queries use LIMIT
- [ ] Retry logic on external API calls (optional for MVP)
- [ ] Rate limiting configured on public-facing webhooks (optional for MVP)
