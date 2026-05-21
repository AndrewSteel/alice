# Feature Index

> Central tracking for all features. Updated by skills automatically.

## Status Legend

- **Roadmap** - Feature identified, no spec file yet (after `/init`)
- **Planned** - Spec written, ready for architecture (after `/write-spec`)
- **Architected** - Tech design done, ready for implementation (after `/architecture`)
- **In Progress** - Currently being built (after `/frontend` or `/backend` starts)
- **In Review** - QA testing in progress (after `/qa` starts)
- **Approved** - QA passed, no Critical/High bugs (after `/qa` passes)
- **Deployed** - Live in production (after `/deploy`)

## Features

| ID      | Phase     | Feature                                                                                                            | Status   | Spec                                                                                         | Created    |
| ------- | --------- | ------------------------------------------------------------------------------------------------------------------ | -------- | -------------------------------------------------------------------------------------------- | ---------- |
| PROJ-1  | Phase 1.2 | HA Intent Infrastructure (DB-Schema & Weaviate HAIntent Collection)                                                | Deployed | PROJ-1-ha-intent-infrastructure.md                                                           | 2026-02-23 |
| PROJ-2  | Phase 1.2 | FastAPI Container + hassil-parser (hassil Intent Expansion)                                                        | Deployed | PROJ-2-fastapi-intent-helper.md                                                              | 2026-02-23 |
| PROJ-3  | Phase 1.2 | HA-First Chat Handler with Intent Routing                                                                          | Deployed | PROJ-3-ha-first-chat-handler.md                                                              | 2026-02-23 |
| PROJ-4  | Phase 1.2 | HA Auto-Sync (MQTT → n8n → Weaviate)                                                                               | Deployed | PROJ-4-ha-auto-sync.md                                                                       | 2026-02-23 |
| PROJ-5  | Phase 1.2 | Hassil Native Library Integration (Expansion Engine Upgrade)                                                       | Deployed | PROJ-5-hassil-native-expansion.md                                                            | 2026-02-26 |
| PROJ-6  | Phase 1.2 | Hassil expansion_rules Compatibility Fix                                                                           | Deployed | PROJ-6-hassil-expansion-rules-fix.md                                                         | 2026-02-27 |
| PROJ-7  | Phase 1.5 | JWT Auth / Login Screen                                                                                            | Deployed | PROJ-7-jwt-auth-login.md                                                                     | 2026-02-27 |
| PROJ-8  | Phase 1.5 | Services Sidebar & Landing Page Migration                                                                          | Deployed | PROJ-8-services-sidebar-and-landing-page-migration.md                                        | 2026-02-28 |
| PROJ-9  | Phase 1.5 | Chat-Handler JWT-Schutz                                                                                            | Deployed | PROJ-9-chat-handler-jwt-protection.md                                                        | 2026-02-28 |
| PROJ-10 | Phase 1.5 | Weaviate Intent Lookup — Migration auf native n8n-Nodes                                                            | Deployed | PROJ-10-weaviate-intent-lookup-migration.md                                                  | 2026-02-28 |
| PROJ-11 | Phase 1.5 | HA Sync Python Worker (Ersatz für n8n alice-ha-intent-sync)                                                        | Deployed | PROJ-11-ha-sync-python-worker.md                                                             | 2026-03-02 |
| PROJ-12 | Phase 1.5 | Phase 2 Security & UX Hardening (nginx Headers, Rate-Limiting, Chat-Rename)                                        | Deployed | PROJ-12-phase2-security-and-ux-hardening.md                                                  | 2026-03-03 |
| PROJ-13 | Phase 1.5 | Auth-Endpoint Rate-Limiting (Login Brute-Force Schutz)                                                             | Deployed | PROJ-13-auth-rate-limiting.md                                                                | 2026-03-06 |
| PROJ-14 | Phase 1.5 | Sidebar Context-Menu & Session-Persistenz                                                                          | Deployed | PROJ-14-sidebar-context-menu-and-session-persistence.md                                      | 2026-03-06 |
| PROJ-15 | Phase 1.6 | DMS NAS-Ordner-Verwaltung (CRUD via REST API + Frontend)                                                           | Deployed | PROJ-15-dms-folder-management.md                                                             | 2026-03-09 |
| PROJ-16 | Phase 1.6 | DMS Scanner & NAS Multi-Format-Scan                                                                                | Deployed | PROJ-16-dms-scanner-nas-infrastructure.md                                                    | 2026-03-09 |
| PROJ-17 | Phase 1.6 | DMS Scanner Multi-Queue-Routing (Erweiterung PROJ-16)                                                              | Deployed | PROJ-17-dms-scanner-multi-queue-routing.md                                                   | 2026-03-11 |
| PROJ-18 | Phase 1.6 | DMS Text-Extractor-Container (pdf/ocr/txt/office → plaintext)                                                      | Deployed | PROJ-18-dms-text-extractor-containers.md                                                     | 2026-03-11 |
| PROJ-19 | Phase 1.6 | DMS Processor Workflow (LLM-Klassifikation + Weaviate)                                                             | Deployed | PROJ-19-dms-processor-workflow.md                                                            | 2026-03-09 |
| PROJ-20 | Phase 1.6 | DMS Document Search Tool (alice-tool-search)                                                                       | Deployed | PROJ-20-dms-document-search-tool.md                                                          | 2026-03-09 |
| PROJ-21 | Phase 1.6 | DMS Lifecycle Management (Duplikate, Verschiebungen, Dateiänderungen)                                              | Deployed | PROJ-21-dms-lifecycle-management.md                                                          | 2026-03-12 |
| PROJ-22 | Phase 1.6 | DMS Lifecycle Workflow (alice-dms-lifecycle MQTT Consumer)                                                         | Deployed | PROJ-22-dms-lifecycle-workflow.md                                                            | 2026-03-12 |
| PROJ-23 | Phase 1.6 | DMS Security Hardening (Folder-API SQL-Injection & GraphQL-Injection)                                              | Deployed | PROJ-23-dms-security-hardening.md                                                            | 2026-03-15 |
| PROJ-24 | Phase 1.6 | DMS Operational Improvements (Stats, LLM-Retry, MQTT-Reliability)                                                  | Deployed | PROJ-24-dms-operational-improvements.md                                                      | 2026-03-15 |
| PROJ-25 | Phase 1.6 | DMS Folder API — Explicit Null Update für nullable Felder (BUG-1 aus PROJ-23)                                      | Deployed | PROJ-25-dms-folder-api-explicit-null-update.md                                               | 2026-03-15 |
| PROJ-26 | Phase 1.6 | Admin Nutzerverwaltung (Create/Deactivate/Delete + OTP-Email + First-Login-Flow)                                   | Deployed | PROJ-26-admin-user-management.md                                                             | 2026-03-15 |
| PROJ-27 | Phase 1.6 | Nutzerprofil selbst bearbeiten (Passwort, E-Mail, Name, Interessen, Präferenzen)                                   | Deployed | PROJ-27-user-profile-self-edit.md                                                            | 2026-03-16 |
| PROJ-28 | Phase 1.6 | DMS Verzeichnis-Reihenfolge (sort_order + Drag-and-Drop + Scanner-Sortierung)                                      | Deployed | PROJ-28-dms-folder-sort-order.md                                                             | 2026-03-22 |
| PROJ-29 | Phase 1.6 | BankStatement Transaction Indexing (BankTransaction Collection)                                                    | Deployed | PROJ-29-bank-transaction-indexing.md                                                         | 2026-04-28 |
| PROJ-30 | Phase 1.6 | Streaming Chat Backend (alice-chat-stream Python/FastAPI, SSE-Endpunkt)                                            | Deployed | PROJ-30-streaming-chat-backend.md                                                            | 2026-05-08 |
| PROJ-31 | Phase 1.6 | Frontend Streaming-UI (Token-Rendering, Tool-Status, Stopp-Button)                                                 | Deployed | PROJ-31-frontend-streaming-ui.md                                                             | 2026-05-07 |
| PROJ-32 | Phase 1.6 | nginx Streaming-Konfiguration (SSE-Proxy, Buffering off, Rate-Limiting)                                            | Deployed | PROJ-32-nginx-streaming-config.md                                                            | 2026-05-07 |
| PROJ-33 | Phase 2   | Phase-2-Vorbereitung — Speech Streaming Interface (WebSocket, TTS-Segmentierung)                                   | Planned  | [PROJ-33-phase2-speech-streaming-interface.md](PROJ-33-phase2-speech-streaming-interface.md) | 2026-05-07 |
| PROJ-34 | Phase 1.6 | alice-auth RS256 Migration (HS256 → RS256, RSA Key Pair, Public Key Distribution)                                  | Deployed | PROJ-34-alice-auth-rs256.md                                                                  | 2026-05-09 |
| PROJ-35 | Phase 1.6 | Chat Frontend Redesign — Nachrichten- und Eingabebereich (Markdown, Syntax Highlighting, 760px, kein Segment-Hack) | Deployed | PROJ-35-chat-frontend-redesign.md                                                            | 2026-05-10 |
| PROJ-36 | Phase 1.6 | RS256 Migration — Vollständige Umstellung aller Komponenten (n8n Credential, Sidebar 403, DMS 403)                 | Deployed | PROJ-36-rs256-migration-completion.md                                                        | 2026-05-10 |
| PROJ-37 | Phase 1.6 | Streaming Verbosity — Thinking-Support und angereicherte Tool-Events                                               | Deployed | PROJ-37-streaming-verbosity.md                                                               | 2026-05-13 |
| PROJ-38 | Phase 1.6 | Sidebar Text-Truncation & Context-Menu Regression Fix (PROJ-35-Nachfolge)                                          | Deployed | PROJ-38-sidebar-text-truncation-and-context-menu-fix.md                                      | 2026-05-13 |
| PROJ-39 | Phase 1.6 | alice-ha-sync Overhaul — Conversation Filter, Area Registry, Value Placeholder Expansion                           | Deployed | PROJ-39-ha-sync-overhaul.md                                                                  | 2026-05-15 |

<!-- Add features above this line -->

## Next Available ID: PROJ-40

