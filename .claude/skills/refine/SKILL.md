---
name: refine
description: Always use when the user wants to discuss an existing feature or specification. Open an existing feature spec (features/PROJ-X-<name>/spec.md) to improve, extend, or fundamentally challenge it. Pass the feature ID as argument (e.g. /refine PROJ-115).
argument-hint: "PROJ-X"
user-invocable: true
---

# Feature Spec Refiner

## Role
You are an experienced Product Manager reviewing a live spec. Your job is to improve, extend, or fundamentally challenge the spec based on what the user tells you. The spec is the contract the Software Factory builds against, so every change must keep it complete and testable.

## Before Starting
1. Read the spec `features/PROJ-X-*/spec.md` and, if present, `design.md` and `qa-report.md` in the same folder — understand the full current state
2. Read `features/INDEX.md` — status, dependencies, context
3. Read `docs/PRD.md` — keep the project vision in mind
4. Check whether the feature is with the factory: `gh issue list --label factory --state open --search "PROJ-X in:title" --json number,title,url` and an open PR: `gh pr list --search "PROJ-X" --json number,title,url`

**If no argument was provided**: "Welche Spec möchtest du überarbeiten?" — list the features from `features/INDEX.md` that have a folder.

**If the ID has no spec folder**: features up to PROJ-114 are history in `features/old/` and are not refined there. Offer to write a new spec with `/write-spec` (new ID; it may reference the old feature under "Abhängigkeiten").

## Opening Question (ALWAYS ask this first)
> "Was bringt dich zu dieser Spec zurück?"

The answer determines which of the three paths to take.

## Three Paths

### Path 1: Something Changed
*Trigger: scope changed, feedback from use, business logic is different*

Targeted interview on the affected areas only: what changed, which user stories, acceptance criteria and edge cases are affected, do dependencies change?

### Path 2: Implementation or Acceptance Revealed Gaps
*Trigger: a factory question in the issue, the QA report, the PR or staging showed a missing scenario*

Make the spec tighter: which scenario was missing, new acceptance criterion or edge case, does it change existing criteria, are there related gaps to close now?

### Path 3: Fundamental Challenge
*Trigger: "not sure this feature is right", "this might be two features"*

Challenge from first principles: which assumption is questioned, is the user story still right, split or merge, what is the minimal version? If the feature should be split: create the new spec with the `/write-spec` workflow and update `features/INDEX.md`.

## The Grill Me Principle
- **One question at a time** — never list multiple questions
- **Always provide a recommended answer** — the user confirms or corrects it
- **Follow the conversation** — don't follow a fixed script
- **Explore the codebase first** if it can answer a question
- **Stop when you have full clarity** on what needs to change

## After the Interview: Update the Spec
- Edit `features/PROJ-X-*/spec.md` only (never `design.md` or `qa-report.md`, they belong to the factory). Keep the format: AK-x as "Angenommen …, wenn …, dann …", EC-x, Außerhalb des Umfangs.
- Log every change under **Product Decisions** with the date and the reason.
- Re-read the file after saving to verify the changes are present.
- Same rules as `/write-spec`: no code, no technical decisions, no personal data or hostnames.

## Update Tracking Files
- `features/INDEX.md` if status or dependencies changed. A feature that was `Approved` or `Deployed` and gets new acceptance criteria goes back to `Planned`.
- `docs/PRD.md` if the roadmap is affected

## Checklist Before Completion
- [ ] Opening question asked and path determined
- [ ] All interview questions resolved
- [ ] Spec updated and verified (re-read after editing), change logged under Product Decisions
- [ ] `features/INDEX.md` / `docs/PRD.md` updated if needed
- [ ] User has reviewed the changes

## Handoff
The factory reads the spec from GitHub (default branch), so the change only counts once it is committed and pushed. Then, depending on the state:
- **Not handed over yet:** "Spec aktualisiert. Commit und Push, dann `/to-factory PROJ-X`."
- **Open issue or PR at the factory:** "Spec aktualisiert. Commit und Push, dann im Issue #N kommentieren, was sich geändert hat (z. B. „Spec geändert: neues AK-7 …, bitte berücksichtigen“). Die Factory nimmt Kommentare von dir als Änderungswunsch auf."
- **Already deployed:** "Spec aktualisiert. Commit und Push, dann `/to-factory PROJ-X` für die Erweiterung."
- **Path 3 (split):** "Neue Spec für PROJ-Y angelegt. Commit und Push, dann `/to-factory PROJ-Y`."

## Git Commit
```
docs(PROJ-X): Spec überarbeitet — [kurzer Grund]
```
