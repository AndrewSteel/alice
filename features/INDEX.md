# Feature Index

> Central tracking for all features. Updated by skills automatically.

## Status Legend

- **Planned** - Requirements written, ready for development
- **In Progress** - Currently being built
- **In Review** - QA testing in progress
- **Deployed** - Live in production

## Features

| ID      | Feature                                                                     | Status   | Spec                                                                                                               | Created    |
| ------- | --------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------ | ---------- |
| PROJ-1  | HA Intent Infrastructure (DB-Schema & Weaviate HAIntent Collection)         | Deployed | [PROJ-1-ha-intent-infrastructure.md](PROJ-1-ha-intent-infrastructure.md)                                           | 2026-02-23 |
| PROJ-2  | FastAPI Container + hassil-parser (hassil Intent Expansion)                 | Deployed | [PROJ-2-fastapi-intent-helper.md](PROJ-2-fastapi-intent-helper.md)                                                 | 2026-02-23 |
| PROJ-3  | HA-First Chat Handler with Intent Routing                                   | Deployed | [PROJ-3-ha-first-chat-handler.md](PROJ-3-ha-first-chat-handler.md)                                                 | 2026-02-23 |
| PROJ-4  | HA Auto-Sync (MQTT → n8n → Weaviate)                                        | Deployed | [PROJ-4-ha-auto-sync.md](PROJ-4-ha-auto-sync.md)                                                                   | 2026-02-23 |
| PROJ-5  | Hassil Native Library Integration (Expansion Engine Upgrade)                | Deployed | [PROJ-5-hassil-native-expansion.md](PROJ-5-hassil-native-expansion.md)                                             | 2026-02-26 |
| PROJ-6  | Hassil expansion_rules Compatibility Fix                                    | Deployed | [PROJ-6-hassil-expansion-rules-fix.md](PROJ-6-hassil-expansion-rules-fix.md)                                       | 2026-02-27 |
| PROJ-7  | JWT Auth / Login Screen                                                     | Deployed | [PROJ-7-jwt-auth-login.md](PROJ-7-jwt-auth-login.md)                                                               | 2026-02-27 |
| PROJ-8  | Services Sidebar & Landing Page Migration                                   | Deployed | [PROJ-8-services-sidebar-and-landing-page-migration.md](PROJ-8-services-sidebar-and-landing-page-migration.md)     | 2026-02-28 |
| PROJ-9  | Chat-Handler JWT-Schutz                                                     | Deployed | [PROJ-9-chat-handler-jwt-protection.md](PROJ-9-chat-handler-jwt-protection.md)                                     | 2026-02-28 |
| PROJ-10 | Weaviate Intent Lookup — Migration auf native n8n-Nodes                     | Deployed | [PROJ-10-weaviate-intent-lookup-migration.md](PROJ-10-weaviate-intent-lookup-migration.md)                         | 2026-02-28 |
| PROJ-11 | HA Sync Python Worker (Ersatz für n8n alice-ha-intent-sync)                 | Deployed | [PROJ-11-ha-sync-python-worker.md](PROJ-11-ha-sync-python-worker.md)                                               | 2026-03-02 |
| PROJ-12 | Phase 2 Security & UX Hardening (nginx Headers, Rate-Limiting, Chat-Rename) | Deployed | [PROJ-12-phase2-security-and-ux-hardening.md](PROJ-12-phase2-security-and-ux-hardening.md)                         | 2026-03-03 |
| PROJ-13 | Auth-Endpoint Rate-Limiting (Login Brute-Force Schutz)                      | Deployed | [PROJ-13-auth-rate-limiting.md](PROJ-13-auth-rate-limiting.md)                                                     | 2026-03-06 |
| PROJ-14 | Sidebar Context-Menu & Session-Persistenz                                   | Deployed | [PROJ-14-sidebar-context-menu-and-session-persistence.md](PROJ-14-sidebar-context-menu-and-session-persistence.md) | 2026-03-06 |
| PROJ-15 | DMS NAS-Ordner-Verwaltung (CRUD via REST API + Frontend)                    | Deployed | [PROJ-15-dms-folder-management.md](PROJ-15-dms-folder-management.md)                                               | 2026-03-09 |
| PROJ-16 | DMS Scanner & NAS Multi-Format-Scan                                         | Deployed | [PROJ-16-dms-scanner-nas-infrastructure.md](PROJ-16-dms-scanner-nas-infrastructure.md)                             | 2026-03-09 |
| PROJ-17 | DMS Scanner Multi-Queue-Routing (Erweiterung PROJ-16)                       | Deployed | [PROJ-17-dms-scanner-multi-queue-routing.md](PROJ-17-dms-scanner-multi-queue-routing.md)                           | 2026-03-11 |
| PROJ-18 | DMS Text-Extractor-Container (pdf/ocr/txt/office → plaintext)               | Deployed | [PROJ-18-dms-text-extractor-containers.md](PROJ-18-dms-text-extractor-containers.md)                               | 2026-03-11 |
| PROJ-19 | DMS Processor Workflow (LLM-Klassifikation + Weaviate)                      | Deployed | [PROJ-19-dms-processor-workflow.md](PROJ-19-dms-processor-workflow.md)                                             | 2026-03-09 |
| PROJ-20 | DMS Document Search Tool (alice-tool-search)                                | Deployed | [PROJ-20-dms-document-search-tool.md](PROJ-20-dms-document-search-tool.md)                                         | 2026-03-09 |
| PROJ-21 | DMS Lifecycle Management (Duplikate, Verschiebungen, Dateiänderungen)       | Deployed | [PROJ-21-dms-lifecycle-management.md](PROJ-21-dms-lifecycle-management.md)                                         | 2026-03-12 |
| PROJ-22 | DMS Lifecycle Workflow (alice-dms-lifecycle MQTT Consumer)                  | Deployed | [PROJ-22-dms-lifecycle-workflow.md](PROJ-22-dms-lifecycle-workflow.md)                                             | 2026-03-12 |
| PROJ-23 | DMS Security Hardening (Folder-API SQL-Injection & GraphQL-Injection)       | Deployed    | [PROJ-23-dms-security-hardening.md](PROJ-23-dms-security-hardening.md)                                             | 2026-03-15 |
| PROJ-24 | DMS Operational Improvements (Stats, LLM-Retry, MQTT-Reliability)           | Deployed  | [PROJ-24-dms-operational-improvements.md](PROJ-24-dms-operational-improvements.md)                                 | 2026-03-15 |
| PROJ-25 | DMS Folder API — Explicit Null Update für nullable Felder (BUG-1 aus PROJ-23) | Deployed  | [PROJ-25-dms-folder-api-explicit-null-update.md](PROJ-25-dms-folder-api-explicit-null-update.md)                   | 2026-03-15 |

<!-- Add features above this line -->

## Next Available ID: PROJ-26
