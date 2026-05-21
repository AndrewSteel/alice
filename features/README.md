# Feature Specifications

Dieser Ordner enthält detaillierte Feature Specs vom Requirements Engineer.

## Path-Structure
`features/**` aktueller Entwicklungs-Pfad
`features/phase-X/**` abgeschlossene Features der Phase-X

## Naming Convention
`PROJ-X-feature-name.md`

Beispiele:
- `PROJ-1-user-authentication.md`
- `PROJ-2-kanban-board.md`
- `PROJ-3-file-attachments.md`

## Was gehört in eine Feature Spec?

### 1. User Stories
Beschreibe, was der User tun möchte:
```markdown
Als [User-Typ] möchte ich [Aktion] um [Ziel zu erreichen]
```

### 2. Acceptance Criteria
Konkrete, testbare Kriterien:
```markdown
- [ ] User kann Email + Passwort eingeben
- [ ] Passwort muss mindestens 8 Zeichen lang sein
- [ ] Nach Registration wird User automatisch eingeloggt
```

### 3. Edge Cases
Was passiert bei unerwarteten Situationen:
```markdown
- Was passiert bei doppelter Email?
- Was passiert bei Netzwerkfehler?
- Was passiert bei gleichzeitigen Edits?
```

### 4. Tech Design (vom Solution Architect)
```markdown
## Database Schema
CREATE TABLE tasks (...);

## Component Architecture
ProjectDashboard
├── ProjectList
│   └── ProjectCard
```

### 5. QA Test Results (vom QA Engineer)
Am Ende des Feature-Dokuments fügt QA die Test-Ergebnisse hinzu:
```markdown
---

## QA Test Results

**Tested:** 2026-01-12
**App URL:** https://alice.happy-mining.de

### Acceptance Criteria Status
- [x] AC-1: User kann Email + Passwort eingeben
- [x] AC-2: Passwort mindestens 8 Zeichen
- [ ] ❌ BUG: Doppelte Email wird nicht abgelehnt

### Bugs Found
**BUG-1: Doppelte Email-Registrierung**
- **Severity:** High
- **Steps to Reproduce:** 1. Register with email, 2. Try again with same email
- **Expected:** Error message
- **Actual:** Silent failure
```

### 6. Deployment Status (vom DevOps Engineer)
```markdown
---

## Deployment

**Status:** ✅ Deployed
**Deployed:** 2026-01-13
**Production URL:** https://alice.happy-mining.de
**Git Tag:** v1.0.0-PROJ-1
```

## Workflow

1. **Requirements Engineer** erstellt Feature Spec
2. **User** reviewed Spec und gibt Feedback
3. **Solution Architect** fügt Tech-Design hinzu
4. **User** approved finales Design
5. **Frontend/Backend Devs** implementieren (dokumentiert via Git Commits)
6. **QA Engineer** testet und fügt Test-Ergebnisse zum Feature-Dokument hinzu
7. **DevOps** deployed und fügt Deployment-Status zum Feature-Dokument hinzu

## Status-Tracking

Feature-Status wird direkt im Feature-Dokument getrackt:
```markdown
# PROJ-1: Feature Name

**Status:** 🔵 Planned | 🟡 In Progress | ✅ Deployed | ❌ Deleted
**Created:** 2026-01-12
**Last Updated:** 2026-01-12
```

**Status-Bedeutung:**
- 🔵 Planned – Requirements sind geschrieben, ready for development
- 🟡 In Progress – Wird gerade gebaut
- ✅ Deployed – Live in Production
- ❌ Deleted - Feature wurde entfernt

**Git als Single Source of Truth:**
- Alle Implementierungs-Details sind in Git Commits
- `git log --grep="PROJ-1"` zeigt alle Änderungen für dieses Feature
- Keine separate FEATURE_CHANGELOG.md nötig!
