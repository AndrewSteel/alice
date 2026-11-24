# General Project Rules

## Development Workflow (Software Factory)
New features are built by the Software Factory on the server, not interactively:

0. **Phase planning (human, locally, once per phase or larger extension):** briefing in `docs/briefing.md` → `/init` → new `docs/PRD.md` + feature map in `features/INDEX.md` (status `Roadmap`)
1. **Spec (human, locally):** `/write-spec` → `features/PROJ-X-<name>/spec.md`, commit and push. Changes to a spec: `/refine PROJ-X`
2. **Hand-off:** `/to-factory PROJ-X` creates a GitHub issue with label `factory`
3. **Factory (server):** check, architecture (`design.md`), implementation, tests (`qa-report.md`), pull request, independent acceptance
4. **Human:** review the PR, merge, deploy with `/deploy PROJ-X` (steps from the PR's "Deploy-Schritte"). No staging (decided 2026-11-24): the live checks run in production right after the deploy

If the user requests a feature that is not in `features/INDEX.md` yet: guide them to `/write-spec` first, no implementation without a spec.

## Feature Tracking
- All features are tracked in `features/INDEX.md` - read it before starting any work
- Each feature has its own folder `features/PROJ-X-feature-name/` (Software Factory / Starter Kit layout):
  - `spec.md` — WHAT (user stories, acceptance criteria, edge cases). Written by the human; the Software Factory never edits it
  - `design.md` — HOW (architecture, implementation notes)
  - `qa-report.md` — test result
- `features/old/` is history: features up to PROJ-114 as flat files (`PROJ-X-name.md`, `phase-X/`). Read it for context, never add or change anything there
- Feature IDs are sequential: check INDEX.md for the next available number
- One feature per spec file (Single Responsibility)
- Never combine multiple independent functionalities in one spec

## Git Conventions
- Commit format: `type(PROJ-X): description`
- Types: feat, fix, refactor, test, docs, deploy, chore
- Check existing features before creating new ones: `features/INDEX.md` and `features/old/INDEX.md`
- Check existing components before building: `git ls-files src/components/`
- Check existing APIs before building: `git ls-files src/app/api/`

## Human-in-the-Loop
- Always ask for user approval before finalizing deliverables
- Present options using clear choices rather than open-ended questions
- Never proceed to the next workflow phase without user confirmation

## Status Updates
After completing work on any feature, you MUST update tracking files. Follow this exact sequence:

1. **Read** the feature folder (`features/PROJ-X-*/`) and `features/INDEX.md` BEFORE editing
2. **Write** your changes using the Edit tool — do NOT just describe what you would write
3. **Re-read** the file AFTER editing to verify the changes are actually present
4. **If changes are missing**, repeat step 2 — never claim updates were made without verifying

**What to update in the feature folder:**
- `design.md`: implementation notes (what was built, what changed, deviations from the spec), bug fixes or design changes discovered during implementation
- `qa-report.md`: test results
- `spec.md` only by the human (revisions go into its Decision Log). The status lives in `features/INDEX.md`, not in the spec

**What to update in `features/INDEX.md`:**
- The status column is the single source of the feature status
- Valid statuses: Roadmap → Planned → Architected → In Progress → In Review → Approved → Deployed
  - **Roadmap**: feature identified, no spec yet
  - **Planned**: after `/write-spec` (human)
  - **Architected**: Software Factory, `design.md` written
  - **In Progress**: Software Factory, implementation running
  - **In Review**: Software Factory, tests running
  - **Approved**: Software Factory, tests passed (no critical/high bugs), PR ready for review
  - **Deployed**: after `/deploy` (human only)
  - **Verworfen**: will not be built (note the replacement, e.g. "ersetzt durch PROJ-X")

**NEVER do this:**
- Do NOT say "I've updated the feature spec" without actually calling the Edit tool
- Do NOT summarize changes in chat as a substitute for writing them to the file
- Do NOT skip updates because "it's obvious" or "minor"

## File Handling
- ALWAYS read a file before modifying it - never assume contents from memory
- After context compaction, re-read files before continuing work
- When unsure about current project state, read `features/INDEX.md` first
- Run `git diff` to verify what has already been changed in this session
- Never guess at import paths, component names, or API routes - verify by reading

## Handoffs Between Skills
- After completing a skill, suggest the next step to the user (e.g. "Next step: `/to-factory PROJ-X`")
- Handoffs are always user-initiated, never automatic
