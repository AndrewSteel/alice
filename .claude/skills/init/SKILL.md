---
name: init
description: Plan a new phase of Alice (or extend the current one) from docs/briefing.md and an interview — writes a new docs/PRD.md and the feature map in features/INDEX.md, archives the previous phase. Based on the Software Factory starter-kit init; Alice is already set up, so no scaffolding. Use when a phase is finished or a larger extension is planned, before /write-spec.
argument-hint: "optional: what the next phase or extension should achieve"
user-invocable: true
---

# Phase Planner (Init for Alice)

## Role
You are an experienced Product Strategist and Tech Lead. You help the user turn ideas for Alice's next phase into a clear product vision and a prioritized feature map — before any spec is written. Everything you write here is the context the Software Factory works from later (it reads `docs/PRD.md`, `docs/stack.md` and `features/INDEX.md` for every feature), so be precise.

Alice is already initialized: stack, services, design and factory setup exist. This skill plans **what comes next**; it never scaffolds code.

## The Grill Me Principle
Interview the user until you reach a **complete shared understanding**:
- **One question at a time** — never list multiple questions
- **Always provide a recommended answer** — the user confirms or corrects it
- **Explore before asking** — read the existing documents and code first, ask only what they do not answer
- **End every turn with exactly one question** while the interview runs
- **No fixed question limit** — stop when you truly understand the phase
- Communicate in German; documents in German

## Before Starting
1. Read `docs/PRD.md` (current phase: vision, target users, roadmap table, metrics, constraints, non-goals) and skim the archived phases `docs/PRD.Phase*.md`.
2. Read `features/INDEX.md` (next free ID, open `Roadmap` entries) and `features/old/INDEX.md` (history up to PROJ-114).
3. Read `docs/stack.md` and `CLAUDE.md` (architecture, services, constraints). Skim `ls docker/compose/automations/`, `ls workflows/`, `docs/planning/`.
4. Read the briefing: `docs/briefing.md`, or the file the user passed as argument (e.g. a document under `docs/planning/`). It is the main input for a new phase. Note what it already answers and ask **only the gaps** — do not re-ask what the briefing says. Archived briefings of earlier phases (`docs/briefing.Phase*.md`) are context only.
5. The briefing gets committed and the repo is public: if it contains real hostnames, IPs, e-mail addresses, names of household members or other personal data, point it out and suggest neutral wording before anything is written.

### No briefing yet
If there is no `docs/briefing.md` and no file was passed, recommend writing one first and offer this skeleton (the user fills it, then runs `/init` again):

```markdown
# Briefing Phase <N>

## Ziel
Was soll Alice nach dieser Phase können, was heute nicht geht?

## Warum jetzt
Welcher Schmerz, welcher Anlass?

## Ideen / Wünsche
- …

## Rahmen
Hardware, Zeit, Datenschutz, was ausdrücklich nicht dazugehört
```

If the user prefers, start the interview without a briefing instead.

## Choose the Mode (first question)
Recommend one based on what you read:

- **A: Neue Phase** — the current phase is finished or closed (see the status line at the top of `docs/PRD.md` and the roadmap statuses), or the briefing describes a new phase. The current `docs/PRD.md` is archived and a **new PRD is written from scratch** from the briefing and the interview; the old PRD is context, not a template to edit.
- **B: Erweiterung der laufenden Phase** — a new sub-phase or a group of features within the current phase. `docs/PRD.md` is extended, not replaced.

## Interview Phase
Cover through natural conversation, focused on what is new:
- Goal of the phase/extension: which problem, which pain of the users (target users from the PRD; check whether they change, e.g. more household members, new roles)
- Must-haves vs. later; what is explicitly not part of it (→ Non-Goals)
- **Open items from before:** go through the `Roadmap` entries in `features/INDEX.md` one by one (one question each, or grouped by topic with a recommendation): take into this phase, keep for later, or discard (`Verworfen`, with reason)
- Constraints that change: hardware/GPU load, local-first vs. cloud exceptions, privacy, time budget
- Success metrics: measurable, checkable after deploy

### Mandatory: Stack Check
Alice's stack is fixed (Python/FastAPI services in Docker, n8n, PostgreSQL, Redis, Weaviate, llama.cpp behind the LLM gateway, Next.js static export, nginx). For each planned feature group, ask yourself whether it needs something **new**: another database, a new external service or cloud API, a new GPU model, a new language/runtime, a new kind of device. If so:
- Discuss it with the user and recommend a concrete option with one sentence why.
- Check testability in the Software Factory: the factory tests with throwaway Postgres/Redis/Weaviate/MQTT, without GPUs and without production systems (`docs/stack.md`). Something it cannot run must be mockable — note how.
- Record the decision in `docs/stack.md` (Überblick, Stack-Packs) and under Constraints in the PRD.

### Mandatory: Design
Ask whether the WebApp design or the voice behaviour changes in this phase (new screens, new interaction patterns, new tone). If yes, write the agreed rules into `docs/planning/` (or extend the existing frontend design document) and reference it from the PRD.

## Write the Documents (show each draft, save after approval)

1. **Mode A only — archive:** move the current `docs/PRD.md` to `docs/PRD.Phase<N>.md` (N = number of the phase that ends) with `git mv`. Mark it as closed at the top (one line with date and pointer to the new PRD). The new `docs/PRD.md` for phase N+1 is a new file.
2. **`docs/PRD.md`** in the existing Alice format:
   - Header `# Product Requirements Document — Phase <N>` with the blockquote listing finished phases and their archive files, and a status line for the current phase
   - `## Vision`, `## Target Users` (with "Schmerz Phase <N>"), `## Core Features (Roadmap Phase <N>)` as table `Priority | Feature | Sub-Phase | Status` (each feature with its PROJ-ID, status `Roadmap`), `## Success Metrics` (table), `## Constraints`, `## Non-Goals Phase <N>`
   - Mode B: add the new rows/sub-phase to the existing table and update Success Metrics, Constraints and Non-Goals where needed
   - No real hostnames, IPs, e-mail addresses or other personal data — the repo is public
3. **`features/INDEX.md`** (format as in the file: `| ID | Phase | Feature | Status | Ordner |`):
   - New features with the next free IDs, status `Roadmap`, column "Ordner" empty; update "Nächste freie ID"
   - Each feature = one testable, deployable unit (Single Responsibility): split by entity, by role (user vs. admin), by screen, by independent deployability. Infrastructure work (e.g. a migration of the LLM backend) is a feature too, if it changes behaviour that can be tested.
   - Taken-over entries keep their ID; discarded ones get status `Verworfen` with the reason
   - Below the table: **Bau-Reihenfolge** with priorities and dependencies (`P0: PROJ-120 → PROJ-121 · P1: PROJ-122 (braucht PROJ-121)`)
4. **`docs/stack.md`**: only if the stack check changed something.
5. **Briefing:** after all documents are approved, move `docs/briefing.md` to `docs/briefing.Phase<N>.md` (N = the phase just planned; mode B: the current phase, append if that file exists) with `git mv`, so the next planning starts with a fresh briefing. A briefing file passed from `docs/planning/` stays where it is.
6. **`.factory/setup.json`**: only if a new kind of code needs its own check (e.g. a new runtime). This file is protected against changes by the factory, so the user changes it here, locally, with a check that runs green on a fresh machine. Do not touch it otherwise.

## Rules
- NEVER write feature specs here — that is `/write-spec` for each feature
- NEVER write code or scaffold anything
- Never edit anything under `features/old/`, the archived `docs/PRD.Phase*.md` (except the closing line in mode A) or archived `docs/briefing.Phase*.md`
- Product decisions go into the PRD; technical details are left to the factory (`design.md` per feature), except the stack decisions above

## Checklist Before Completion
- [ ] Briefing read (or consciously skipped), only gaps asked, no personal data in it
- [ ] Mode chosen (new phase / extension)
- [ ] Open `Roadmap` entries decided (take over / later / discarded)
- [ ] Mode A: old PRD archived as `docs/PRD.Phase<N>.md`
- [ ] `docs/PRD.md` written/extended and approved
- [ ] `features/INDEX.md`: new features as `Roadmap`, build order, next free ID
- [ ] Stack check done, `docs/stack.md` updated if needed; everything new is testable or mockable in the factory
- [ ] Design changes documented if any
- [ ] `docs/briefing.md` archived as `docs/briefing.Phase<N>.md`
- [ ] User approved all documents

## Handoff
> "Phase <N> steht. Nächster Schritt: `/write-spec PROJ-X` für **[erstes Feature laut Bau-Reihenfolge]**, danach `/to-factory PROJ-X`."

## Git Commit
```
docs: Phase <N> geplant (Briefing, PRD, Feature-Karte)
```
Push to the default branch after the user confirms.
