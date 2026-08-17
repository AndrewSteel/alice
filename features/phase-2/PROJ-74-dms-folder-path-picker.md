# PROJ-74: DMS Pfad-Auswahlbox — Verzeichnis-Browser für NAS-Ordner

## Status: Deployed

**Created:** 2026-08-03
**Last Updated:** 2026-08-04

## Dependencies

- Requires: PROJ-15 (DMS NAS-Ordner-Verwaltung) — ersetzt die manuelle Pfad-Texteingabe in `AddFolderDialog` und `EditFolderDialog`
- Requires: PROJ-65/66 (Effective-Permissions API / Granulares Rollen-Gating) — Zugriff weiterhin über `can_manage_dms_folders`

## Overview

PROJ-15 führte die Verwaltung überwachter NAS-Ordner ein, jedoch mussten Admins den absoluten Pfad manuell als Freitext eintippen — fehleranfällig und ohne Bezug zur tatsächlichen NAS-Struktur. Dieses Feature ersetzt die Texteingabe durch eine Auswahlbox (Verzeichnis-Browser), die den NAS-Baum ab `/mnt/nas` anzeigt und es dem Admin erlaubt, einen Ordner per Klick statt per Tippen auszuwählen — sowohl beim Anlegen als auch beim Ändern eines DMS-Ordners.

`/mnt/nas` ist der Mount-Punkt, unter dem mehrere unabhängige NAS-Freigaben als Geschwisterverzeichnisse eingehängt sind (z. B. `/mnt/nas/Projekte`, `/mnt/nas/Backup`). Der Mount-Punkt selbst ist keine sinnvolle Erfassungseinheit — er wird in der Auswahlbox nur als Navigationsebene angezeigt, ist aber nicht auswählbar. Auswählbar sind ausschließlich Pfade ab Tiefe 1, also `/mnt/nas/{Freigabe}` und tiefer.

Im Zuge der Konzeption wurde ein bestehendes funktionales Risiko identifiziert: Der DMS-Scanner (PROJ-16/72) verarbeitet Ordner rekursiv. Wird sowohl ein Ordner als auch einer seiner Unterordner separat als DMS-Ordner erfasst, verarbeitet der Scanner die Dateien im Unterordner doppelt.

**Refinement (2026-08-04):** Die ursprüngliche Lösung verhinderte deshalb jede Unter-/Überordner-Überlappung vollständig (409 Conflict). In der Praxis zeigte sich, dass das zu restriktiv ist: Reale NAS-Strukturen enthalten häufig einen breiten Sammelordner (z. B. `~/Finanzen/{Bank}`) mit vielen unterschiedlichen, nicht typisierbaren Dokumenten, während einzelne Unterordner darin bereits einem spezifischen Dokumenttyp zugeordnet sind (z. B. `~/Finanzen/{Bank}/Depot` → `SecuritySettlement`, `~/Finanzen/{Bank}/Girokonto` → `BankStatement`). Ohne den Sammelordner separat erfassen zu können, gehen dessen sonstige Dokumente nie ins DMS. Die Validierung wurde daher gelockert: **Nur exakt identische Pfade werden weiterhin blockiert.** Unter-/Überordner-Überlappungen sind ab jetzt erlaubt und werden in der Auswahlbox lediglich informativ markiert (nicht blockierend) — der Admin sieht bewusst, wo der Scanner Dateien doppelt verarbeiten wird, und akzeptiert das explizit als Trade-off. Der DMS-Scanner selbst bekommt dafür keine Deduplizierungslogik (siehe Non-Goals).

**Kein Anlegen neuer NAS-Verzeichnisse:** Die Auswahlbox erlaubt nur die Auswahl bereits existierender NAS-Ordner (kein `mkdir`). Die manuelle Freitext-Pfadeingabe entfällt vollständig — ein NAS-Ordner muss vor der Erfassung in Alice bereits auf dem NAS existieren.

## User Stories

- Als Admin möchte ich beim Hinzufügen eines DMS-Ordners den Pfad über eine Auswahlbox aus dem NAS-Verzeichnisbaum wählen, statt ihn manuell einzutippen, damit ich keine Tippfehler mache und die tatsächliche NAS-Struktur sehe.
- Als Admin möchte ich beim Bearbeiten eines bestehenden DMS-Ordners über dieselbe Auswahlbox zu einem Unter- oder übergeordneten Ordner wechseln können, damit ich den Scan-Scope anpassen kann, ohne den Pfad neu einzutippen.
- Als Admin möchte ich in der Auswahlbox erkennen, welche Ordner bereits exakt als DMS-Ordner erfasst sind oder mit einem erfassten Ordner überlappen, damit ich bewusst entscheiden kann, ob eine dadurch entstehende doppelte Scanner-Verarbeitung für mich akzeptabel ist.
- Als Admin möchte ich innerhalb der Auswahlbox navigieren können (in Unterordner hinein, per Breadcrumb wieder heraus), damit ich auch tief verschachtelte NAS-Ordner erreichen kann.
- Als Admin möchte ich einen breiten Sammelordner UND spezifisch typisierte Unterordner davon unabhängig voneinander als eigene DMS-Ordner erfassen können, damit auch die nicht typisierbaren Dokumente im Sammelordner ins DMS gelangen — auch wenn das bedeutet, dass die Unterordner-Dateien vom Scanner doppelt verarbeitet werden.

## Acceptance Criteria

### Auswahlbox — Allgemein

- [ ] `AddFolderDialog` und `EditFolderDialog` ersetzen das bisherige Text-`Input` für den Pfad durch einen Button/Feld, der eine Auswahlbox (Dialog/Sheet) öffnet
- [ ] Die Auswahlbox startet im Add-Dialog immer bei `/mnt/nas`
- [ ] Die Auswahlbox startet im Edit-Dialog beim aktuellen Pfad des zu bearbeitenden Ordners (Breadcrumb zeigt den Pfad, Liste zeigt dessen direkte Unterordner)
- [ ] Die Auswahlbox zeigt ausschließlich Verzeichnisse (keine Dateien) des aktuell geöffneten Pfads
- [ ] Klick auf einen Unterordner navigiert eine Ebene tiefer; die Breadcrumb-Leiste erlaubt den Sprung zurück zu jeder höheren Ebene bis `/mnt/nas`
- [ ] Ein Button "Diesen Ordner auswählen" übernimmt den aktuell geöffneten Pfad in das Formular und schließt die Auswahlbox
- [ ] **`/mnt/nas` selbst ist nicht auswählbar** — auf der Root-Ebene ist der Button "Diesen Ordner auswählen" deaktiviert; auswählbar sind ausschließlich Pfade ab `/mnt/nas/{Freigabe}` (Tiefe ≥ 1)
- [ ] Nach Auswahl zeigt das Formular den gewählten Pfad schreibgeschützt an (kein Freitext-Edit mehr möglich)
- [ ] Symlinks werden in der Ordnerliste nicht angezeigt (konsistent mit dem Scan-Verhalten des DMS-Scanners, der Symlinks überspringt)

### Konflikt-Markierung in der Auswahlbox

- [ ] Ordner, die exakt einem bereits aktiven (`enabled = true`) DMS-Ordner entsprechen, werden in der Liste als "Bereits erfasst" markiert und sind **nicht auswählbar** (einzige blockierende Markierung)
- [ ] Ordner, die Unterordner eines bereits aktiven DMS-Ordners sind, werden als "Liegt unterhalb eines bereits erfassten Ordners" markiert — **rein informativ, weiterhin auswählbar** (Refinement 2026-08-04: Sub-/Überordner-Überlappung ist erlaubt, siehe Overview)
- [ ] Ordner, die einen bereits aktiven DMS-Ordner als Unterordner enthalten (Ordner ist Überordner), werden als "Enthält bereits erfassten Ordner" markiert — **rein informativ, weiterhin auswählbar**
- [ ] `/mnt/nas` selbst wird nie als "Überordner-Konflikt" markiert, obwohl es rein pfadtechnisch Präfix jedes registrierten Ordners ist — da es ohnehin nicht auswählbar ist (siehe oben), ist die Konflikt-Prüfung auf Pfade ab Tiefe ≥ 1 beschränkt
- [ ] Im Edit-Dialog gilt die Konflikt-Markierung nicht für den gerade bearbeiteten Ordner selbst — sein aktueller Pfad sowie dessen Unter-/Überordner bleiben auswählbar, solange sie nicht exakt mit einem ANDEREN aktiven DMS-Ordner übereinstimmen
- [ ] Deaktivierte (`enabled = false`) DMS-Ordner lösen keine Konflikt-Markierung aus

### Backend-Validierung (Defense in Depth)

- [ ] **POST** `/webhook/dms/folders` lehnt ausschließlich einen Pfad ab, der **exakt identisch** mit einem bereits aktiven DMS-Ordner ist → 409 Conflict ("Dieser Ordner ist bereits als DMS-Ordner erfasst."). Unter- oder Überpfade eines aktiven Ordners werden **akzeptiert** (201) — Mehrfachverarbeitung durch den Scanner ist dabei ein bekannter, akzeptierter Trade-off (siehe Overview/Non-Goals)
- [ ] **POST**/**PUT** lehnen `/mnt/nas` selbst (exakt, ohne Unterpfad) als Pfad ab → 400 Bad Request ("Der NAS-Mount-Punkt selbst kann nicht als Ordner erfasst werden")
- [ ] **PUT** `/webhook/dms/folders/:id` wendet dieselbe Exakt-Match-Prüfung an, wobei der zu aktualisierende Ordner selbst von der Prüfung ausgenommen ist
- [ ] Die Ancestor/Descendant-Klassifizierung wird weiterhin berechnet (ausschließlich für aktive (`enabled = true`) Ordner und Pfade ab Tiefe ≥ 1 unterhalb von `/mnt/nas`), dient aber nur noch der informativen Markierung im Browse-Endpunkt — sie blockiert POST/PUT nicht mehr
- [ ] Neuer Browse-Endpunkt liefert für einen gegebenen Pfad die Liste der direkten Unterverzeichnisse inkl. Markierungs-Information (bereits erfasst / Unterordner-Konflikt / Überordner-Konflikt), JWT-geschützt und auf `can_manage_dms_folders` beschränkt (analog zu den bestehenden CRUD-Endpunkten)
- [ ] Der Browse-Endpunkt verweigert Pfade außerhalb von `/mnt/nas` (Path-Traversal-Schutz, z. B. `../../etc`)

### Fehler- und Leerzustände

- [ ] Ist ein Verzeichnis nicht lesbar (Berechtigungsfehler auf dem NAS), zeigt die Auswahlbox eine Fehlermeldung statt einer leeren Liste
- [ ] Ein Verzeichnis ohne Unterordner zeigt einen Leerzustand ("Keine Unterordner") — "Diesen Ordner auswählen" bleibt trotzdem nutzbar (außer auf Root-Ebene, siehe oben)
- [ ] Ist `/mnt/nas` selbst nicht erreichbar, zeigt die Auswahlbox einen Fehlerzustand mit Hinweis, dass der NAS-Mount nicht verfügbar ist

## Edge Cases

- **Pfad wird nach Auswahl auf dem NAS gelöscht, bevor gespeichert wird**: POST/PUT läuft regulär durch bestehende PROJ-15-Logik (Pfad muss laut EC-1 aus PROJ-15 nicht zwingend existieren) — kein Sonderfall nötig.
- **Zwei Admins legen gleichzeitig exakt denselben Pfad an**: Race Condition zwischen der Exakt-Match-Prüfung und dem Speichern ist theoretisch möglich (TOCTOU), wird aber durch den bestehenden `UNIQUE`-Constraint auf `path` in der Datenbank ohnehin abgefangen (der zweite Insert schlägt fehl, unabhängig vom Timing der Anwendungslogik). Für Unter-/Überordner-Überlappungen entfällt dieses Race-Problem, da solche Pfade jetzt ohnehin erlaubt sind.
- **Bewusst überlappende Ordner** (z. B. Sammelordner + spezifisch typisierte Unterordner, siehe Overview): Dokumente im überlappenden Bereich werden vom DMS-Scanner (PROJ-16/72) pro erfassten Ordner einmal verarbeitet — bei zwei überlappenden Ordnern also doppelt. Dies ist eine bewusst in Kauf genommene Nebenwirkung dieser Funktion, keine Deduplizierung im Scanner vorgesehen (siehe Non-Goals).
- **Bestehende, bereits überlappende Ordner in der Datenbank** (vor diesem Feature angelegt): Werden NICHT rückwirkend validiert oder bereinigt — ohnehin nicht mehr nötig, da Überlappung jetzt zulässig ist.
- **Sehr viele Unterordner (Performance)**: Auswahlbox zeigt alle direkten Unterordner der aktuellen Ebene ohne Paginierung (i. d. R. keine sehr breiten Verzeichnisse auf dem NAS zu erwarten); keine Sonderbehandlung in diesem Feature.
- **Admin will einen Ordner erfassen, der noch nicht auf dem NAS existiert**: Nicht mehr möglich — der Ordner muss zuerst auf dem NAS angelegt werden (siehe Overview). Das ist eine bewusste Verhaltensänderung gegenüber PROJ-15 EC-1.
- **Admin öffnet die Auswahlbox direkt auf `/mnt/nas`, ohne zu navigieren**: "Diesen Ordner auswählen" ist deaktiviert; der Admin muss mindestens eine Ebene tiefer navigieren, bevor eine Auswahl möglich ist.

## Non-Goals

- Keine Möglichkeit, neue NAS-Verzeichnisse aus der Auswahlbox heraus anzulegen (kein `mkdir`)
- Keine manuelle Freitext-Pfadeingabe als Fallback
- Keine rückwirkende Bereinigung/Validierung bereits bestehender, überlappender DMS-Ordner in der Datenbank
- **Keine Deduplizierung/Priorisierung im DMS-Scanner bei bewusst überlappenden Ordnern** — Mehrfachverarbeitung von Dateien in überlappenden Pfadbereichen wird explizit in Kauf genommen (Refinement 2026-08-04); der Scanner selbst wird durch dieses Feature nicht verändert

## Technical Requirements (optional)

- Browse-Endpunkt beschränkt auf den Unterbaum von `/mnt/nas`; Pfad-Normalisierung erforderlich, um Path-Traversal zu verhindern
- Ancestor/Descendant-Klassifizierung (für die informative Badge-Anzeige) basiert auf String-Präfixvergleich normalisierter absoluter Pfade, beginnend erst ab Tiefe 1 unterhalb `/mnt/nas` (z. B. ist `/mnt/nas/Projekte` Präfix von `/mnt/nas/Projekte/Rechnungen`, aber `/mnt/nas` selbst wird als gemeinsamer Mount-Punkt von der Prüfung ausgenommen) — sie ist seit dem Refinement vom 2026-08-04 nicht mehr blockierend, nur noch die Exakt-Match-Prüfung ist es

---

<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

#### A) Component Structure

```
Settings > DMS-Ordner
+-- AddFolderDialog (bestehend)
|   +-- Pfad-Feld: jetzt schreibgeschützte Anzeige statt Text-Input
|   +-- Button "Ordner wählen" öffnet FolderPathPicker
+-- EditFolderDialog (bestehend)
    +-- Pfad-Feld: jetzt schreibgeschützte Anzeige statt Text-Input
    +-- Button "Ordner wählen" öffnet FolderPathPicker (startet beim aktuellen Pfad)

FolderPathPicker (NEU, gemeinsame Komponente für Add + Edit, als Sheet von rechts)
+-- Breadcrumb-Leiste ( /mnt/nas > Freigabe > Unterordner ... )
+-- Ordnerliste der aktuell geöffneten Ebene
|   +-- Ordner-Zeile: Name, optionales Konflikt-Badge
|   |     ("Bereits erfasst" / "Liegt unterhalb eines erfassten Ordners" /
|   |      "Enthält bereits erfassten Ordner")
|   +-- Klick auf Zeile navigiert eine Ebene tiefer (auch bei Konflikt-Badge,
|         damit man in einen "enthält bereits erfassten Ordner"-Ordner hineinsehen kann)
+-- Fehlerzustand (Ordner nicht lesbar / NAS-Mount nicht erreichbar)
+-- Leerzustand ("Keine Unterordner")
+-- Footer: Button "Diesen Ordner auswählen"
      (deaktiviert auf /mnt/nas-Ebene selbst und nur bei EXAKTEM Konflikt
       "Bereits erfasst"; Unterordner-/Überordner-Konflikte bleiben auswählbar,
       Refinement 2026-08-04)
```

#### B) Data Model

Keine neue Tabelle. Die Auswahlbox liest direkt vom NAS-Dateisystem und reichert die Liste live mit dem Konfliktstatus aus der bestehenden `alice.dms_watched_folders`-Tabelle an (nur `path`, `enabled` werden gelesen) — nichts davon wird zwischengespeichert. Jeder Eintrag in der Ordnerliste besteht aus: Name, vollständiger Pfad, Konfliktstatus (keiner / exakt erfasst / liegt unterhalb / enthält). Persistiert wird weiterhin nur der final gewählte Pfad, genau wie heute in `path` der `dms_watched_folders`-Zeile.

#### C) Tech Decisions

- **Sheet statt verschachteltem Dialog** (Nutzerentscheidung): Add/Edit ist bereits ein Dialog — ein zweiter Dialog darüber würde auf Mobile (375px) eng und wirkt wie Modal-Stapeln. Ein von rechts einfahrendes Sheet bietet mehr Platz für Breadcrumb + Ordnerliste und fühlt sich wie ein eigener Navigationsschritt an.
- **Eine gemeinsame `FolderPathPicker`-Komponente** für Add und Edit statt zweier Implementierungen — identische Navigations-/Auswahl-/Konfliktlogik, es unterscheidet sich nur der Startpfad (`/mnt/nas` vs. aktueller Ordnerpfad) und dass Edit den gerade bearbeiteten Ordner selbst von der Konfliktprüfung ausnimmt.
- **Browse-Endpunkt als neue Route im bestehenden `alice-dms-folder-api`-Workflow**, keine neue Workflow-Datei — hält die gesamte DMS-Ordner-API (List/Create/Update/Delete/Reorder/Browse) an einem Ort, gleiches JWT + `can_manage_dms_folders`-Gate wie die fünf bestehenden Routen.
- **Dateisystemzugriff direkt in n8n**, kein neuer Container: Der n8n-Container mountet `/mnt/nas` bereits read-only über `nas-volumes.yml`, und `fs`/`path` sind bereits über `NODE_FUNCTION_ALLOW_BUILTIN` freigegeben.
- **Konfliktprüfung (exakt / Ancestor / Descendant) wird einmal implementiert und dreifach wiederverwendet** (Browse zur informativen Markierung, Create und Update zur verbindlichen Prüfung) über einen n8n-Sub-Workflow statt dreier Kopien desselben Codes. Seit dem Refinement vom 2026-08-04 ist nur noch der Exakt-Match-Fall für Create/Update tatsächlich blockierend (`hasConflict = conflictType === 'exact'`); Ancestor/Descendant werden weiterhin klassifiziert und im Browse-Endpunkt angezeigt, verhindern aber kein Speichern mehr.
- **Path-Traversal-Schutz:** jeder eingehende Pfad wird normalisiert (aufgelöster Absolutpfad) und nur akzeptiert, wenn er `/mnt/nas` selbst ist oder mit `/mnt/nas/` beginnt — alles andere (z. B. `../../etc`) wird mit 400 abgelehnt.
- **Symlinks werden beim Auflisten übersprungen**, konsistent mit dem bestehenden Scan-Verhalten des DMS-Scanners.

#### D) Dependencies

Keine neuen Pakete. Nutzt n8n's eingebautes `fs`/`path` (bereits freigegeben) sowie die bereits im Projekt vorhandenen shadcn-Komponenten `Sheet` und `Breadcrumb` (`frontend/src/components/ui/`).

#### E) Workflow Architecture — Browse-Endpunkt & Konflikt-Prüfung

- **Trigger:** neue Route `GET /webhook/dms/folders/browse?path=...` im bestehenden `alice-dms-folder-api`-Workflow
- **Nodes (High-Level):**
  1. Webhook: GET Browse
  2. JWT + Validate (gleiches Muster wie bestehende Routen) → 401 ohne gültiges Token, 403 ohne `can_manage_dms_folders`
  3. Pfad-Normalisierung + Traversal-Check → 400 bei Pfad außerhalb `/mnt/nas`
  4. Verzeichnis lesen (Symlinks werden übersprungen) → definierter Fehlerzustand statt leerer Liste bei Lesefehler (z. B. Berechtigungsproblem) oder falls `/mnt/nas` selbst nicht erreichbar ist
  5. Aktive (`enabled = true`) Ordner aus Postgres lesen
  6. Konflikt-Markierung über wiederverwendbaren Sub-Workflow "Check Folder Conflict" (auch von Create/Update genutzt) → markiert jeden Unterordner als exakt erfasst / liegt unterhalb / enthält erfassten Ordner
  7. Antwort: Liste der Unterordner mit Name, Pfad, Konfliktstatus
- **Data flow:** Frontend übergibt aktuellen Pfad → n8n liest das entsprechende Verzeichnis vom gemounteten NAS → reichert die Liste mit Konfliktstatus aus Postgres an → JSON zurück ans Frontend
- **Integrations:** Postgres (`alice.dms_watched_folders`, nur lesend), lokales Dateisystem `/mnt/nas` (read-only Mount)
- **Error handling:** Lesefehler (Berechtigung, nicht erreichbar) → Fehlerantwort mit Meldung statt leerer Liste oder 500 ohne Body; Pfad außerhalb `/mnt/nas` → 400; fehlendes/ungültiges Token bzw. fehlende Berechtigung → 401/403

Zusätzlich rufen **Create (POST)** und **Update (PUT)** denselben "Check Folder Conflict"-Sub-Workflow vor dem jeweiligen Postgres-Insert/Update auf — das ist die verbindliche "Defense in Depth"-Prüfung aus der Spec. Seit dem Refinement vom 2026-08-04 löst dabei **nur noch ein exakter Pfad-Match** einen 409 aus ("Dieser Ordner ist bereits als DMS-Ordner erfasst."); Ancestor-/Descendant-Konflikte mit einem anderen aktiven Ordner werden weiterhin klassifiziert (für die Fehlermeldung, falls doch mal relevant, und für Konsistenz mit dem Browse-Endpunkt), blockieren den Insert/Update aber nicht mehr. 400 bleibt weiterhin bestehen, wenn der Pfad exakt `/mnt/nas` ist. Update schließt dabei den gerade bearbeiteten Ordner selbst von der Prüfung aus.

## Backend Implementation Notes

- New sub-workflow `workflows/alice-dms-folder-conflict-check.json` implements the ancestor/descendant/exact conflict check once (queries `alice.dms_watched_folders` for active folders, string-prefix comparison of normalized paths), returning `{ path, conflictType, message, hasConflict }` per candidate path.
- `workflows/alice-dms-folder-api.json` gained a 6th route, `GET /webhook/dms/folders/browse?path=&excludeFolderId=`, gated with the same JWT `role==='admin'` check the other 5 routes already use (see Permission Gating Decision below). It lists direct subdirectories via `fs.readdirSync`, skips symlinks (matching `alice-dms-path-worker.json`'s scan behavior), rejects paths outside `/mnt/nas` with 400, and annotates each subfolder with conflict status via the new sub-workflow.
- POST and PUT now reject the literal `/mnt/nas` path (400) and call the conflict-check sub-workflow before writing (409 with a conflict-type-specific message on overlap); PUT excludes its own folder id from the check and skips the check entirely when `path` isn't part of the update.
- **Permission gating decision:** the browse route and the new POST/PUT conflict checks use `role === 'admin'` from the JWT, matching the actual behavior of the 5 pre-existing routes — none of which currently check the `can_manage_dms_folders` flag from `alice.permissions_system` despite it existing since PROJ-65. Fixing that gap for all 6 routes was judged out of scope for PROJ-74 (confirmed with user); it stays a pre-existing inconsistency, not something this feature introduced.
- **Deploy step required:** `alice-dms-folder-conflict-check` must be imported into n8n first so it gets a real workflow ID; the three `Execute Workflow` nodes in `alice-dms-folder-api.json` currently reference a placeholder id (`PENDING_IMPORT_alice-dms-folder-conflict-check`) that must be updated to the real id after import, before `alice-dms-folder-api` is deployed/re-deployed.

## Frontend Implementation Notes

- New shared component `frontend/src/components/Settings/FolderPathPicker.tsx`: a right-side `Sheet` (widened via `sm:max-w-lg`) with a `Breadcrumb` trail and a folder list, backed by a navigation stack of `{ path, conflictType }` so both breadcrumb jumps and drill-downs always know the current folder's own conflict status (needed to disable the select button on conflicting folders, not just show badges on rows).
- `frontend/src/services/dms.ts` gained `browseFolders(path?, excludeFolderId?)` and the `BrowseEntry` type, calling `GET /api/webhook/dms/folders/browse`, following the same `fetchWithAuth` / error-mapping / n8n array-unwrapping conventions as the existing folder CRUD functions.
- `AddFolderDialog.tsx` and `EditFolderDialog.tsx`: the free-text path `Input` is replaced with a read-only path display plus an "Ordner wählen" button that opens `FolderPathPicker` (`startPath="/mnt/nas"` for Add; `startPath={folder.path}` + `excludeFolderId={folder.id}` for Edit). Existing `pathRequired`/`pathTooLong` client-side guards were kept as harmless defensive checks even though the picker can no longer produce an invalid path in practice.
- New i18n keys under `settings.dms.dialog.choosePath` and `settings.dms.picker.*` added to both `de.ts` and `en.ts`.
- **Verification status:** `npm run build` (Next.js build + TypeScript type-check) passes cleanly. Live in-browser verification against a real backend was **not** performed — this sandbox has no running Alice Docker stack (Postgres/n8n/nginx) to authenticate against or to serve real NAS data, and the new `browse` route isn't deployed yet (see Backend Implementation Notes). This needs to be exercised in a real environment before sign-off.

## QA Test Results

**Tested:** 2026-08-03
**Environment:** No live Alice Docker stack (Postgres/n8n/nginx) or real NAS mount was available in this session, and the new `browse` route / conflict-check sub-workflow are not yet deployed (see Deploy step in Backend Implementation Notes) — so this pass could not exercise the feature end-to-end through a browser against a live backend. Instead: (1) rigorous code review of every changed file against each acceptance criterion, (2) the exact conflict-detection, path-normalization/traversal-guard, and directory-read/symlink-skip logic from the n8n Code nodes was copy-extracted into standalone Node scripts and run with `node` — including against a real fixture directory tree with symlinks (one pointing inside `/mnt/nas`, one escaping outside it) — to get genuine execution-verified confidence rather than only visual inspection, and (3) `npm run build` (Next.js build + TypeScript strict type-check) for the frontend. **Full live E2E verification (real browser, real JWT auth, real NAS data, deployed n8n workflows) is still required before this goes to production** and is called out below wherever a criterion could only be verified this way.
**Tester:** QA Engineer (AI)

### Acceptance Criteria Status

#### Auswahlbox — Allgemein
- [x] `AddFolderDialog`/`EditFolderDialog` replace the path `Input` with a read-only display + "Ordner wählen" button opening the picker — verified by code review of both files.
- [x] Add picker always starts at `/mnt/nas` — `AddFolderDialog` passes `startPath="/mnt/nas"`.
- [x] Edit picker starts at the folder's current path, breadcrumb + listing reflect it — `EditFolderDialog` passes `startPath={folder.path}`; `FolderPathPicker` derives the breadcrumb directly from `current.path`.
- [x] Only directories shown, never files — confirmed by running `Code: Read Directory`'s exact logic against a fixture tree containing a plain file; the file was correctly excluded.
- [x] Click navigates one level deeper; breadcrumb allows jumping back to any higher level up to `/mnt/nas` — `navigateInto`/`navigateToIndex` verified by code review; breadcrumb is built from a navigation stack.
- [x] "Diesen Ordner auswählen" submits the current path and closes the picker.
- [x] `/mnt/nas` itself not selectable (button disabled at root); selectable only at depth ≥ 1 — `disabled={isRoot || hasConflict}`.
- [x] After selection the form shows the path read-only, no free-text edit possible — the `Input` for path was removed entirely from both dialogs.
- [x] Symlinks never shown — verified against a fixture tree with two symlinks (one internal, one escaping `/mnt/nas`); both correctly excluded, matching the existing DMS scanner's symlink-skip behavior.

#### Konflikt-Markierung
- [x] Exact match → "Bereits erfasst", not selectable — verified via standalone execution of the conflict-detection logic (8 scenarios, all correct).
- [x] Subfolder of an active folder → "Liegt unterhalb..." badge, not selectable.
- [x] Folder containing an active folder → "Enthält..." badge, not selectable.
- [x] Siblings with a string-prefix-like name (e.g. active `/mnt/nas/A` vs. candidate `/mnt/nas/AB`) do **not** false-positive — explicitly tested (trailing-slash boundary check confirmed correct).
- [x] `/mnt/nas` itself never flagged as an "Überordner-Konflikt" — the sub-workflow explicitly excludes it, and it can never appear as a stored folder anyway (rejected at 400).
- [x] Edit dialog excludes the folder being edited from conflict marking, for every folder reached via browsing (row clicks and breadcrumb jumps all correctly retain accurate per-node conflict state since browsing always passes `excludeFolderId`) — **see BUG-1 (Low)** for one narrow gap.
- [x] Disabled (`enabled=false`) folders never trigger conflict marking — the sub-workflow's query filters `WHERE enabled = true`.

#### Backend-Validierung
- [x] POST rejects identical/sub/superpath of an active folder → 409 with a distinct message per conflict type — logic-verified; **see BUG-2 (High, fixed during this pass)**.
- [x] POST/PUT reject the literal `/mnt/nas` → 400 with the specified message.
- [x] PUT applies the same check, excluding the folder being updated (`excludeFolderId`).
- [x] Ancestor/descendant check only considers active, depth-≥1 folders.
- [~] New browse endpoint, JWT-protected + same admin gate as the 5 existing routes, with conflict annotations — **implemented and structurally validated** (`n8n-mcp validate_workflow`: 0 new-category errors; all reported issues are pre-existing patterns shared with the 5 untouched routes), but **not yet deployed** — cannot be hit over HTTP in this session.
- [x] Path-traversal protection on the browse endpoint — verified via standalone execution against `../../etc`, `/mnt/nas/../etc`, and a prefix-confusable `/mnt/nasty`; all correctly rejected.

#### Fehler- und Leerzustände
- [x] Unreadable directory → error message, not an empty list — verified: a missing directory correctly produced a distinct `readError` ("not found") with `entries: []`, not silently empty.
- [x] Empty directory → "Keine Unterordner" empty state, select button still usable (except at root) — code-verified (same enable/disable logic path as any other folder).
- [~] `/mnt/nas` itself unreachable → error state with a mount-unavailable hint — same code path as the unreadable-directory case (verified), but an actually-offline NAS mount could not be simulated in this session.

### Edge Cases Status
- [x] Path deleted from NAS after selection, before save — untouched PROJ-15 logic, no regression.
- [x] Concurrent admins / TOCTOU — server-side conflict check is authoritative regardless of what the picker displayed; UI is correctly only a proactive hint.
- [x] Pre-existing overlapping folders — no retroactive validation/cleanup added, matches the spec's explicit Non-Goal.
- [x] Very many subfolders — listing is unpaginated as specified, rendered in a scrollable container.
- [x] Selecting a not-yet-existing NAS folder — no longer possible; the picker only ever lists real `fs.readdirSync` entries.
- [x] Reactivating a disabled overlapping folder — untouched, matches the spec's explicit Non-Goal.
- [x] Opening the picker directly at `/mnt/nas` — select button correctly disabled until navigating deeper.

### Security Audit Results

**n8n workflow features:**
- [x] Authentication: browse route uses the same `jwtAuth` webhook credential as the 5 existing routes; missing/invalid signature rejected at the webhook level before any node runs.
- [x] Authorization: `role === 'admin'` gate on the new route and on the new POST/PUT conflict-check branches, consistent with (not weaker than) the 5 existing routes. (Note: none of the 6 routes currently check the finer-grained `can_manage_dms_folders` flag — a pre-existing gap outside PROJ-74's scope, confirmed with the user; not a regression.)
- [x] Path traversal: normalized-path + `startsWith('/mnt/nas/')` check blocks `..`-based and prefix-confusable escape attempts — execution-verified.
- [x] SQL injection: all new/modified Postgres queries use parameterized `queryReplacement` arrays ($1/$2/...), never string concatenation.
- [x] XSS: folder names and paths are rendered via plain JSX text interpolation (`{entry.name}`, `{segment}`) in `FolderPathPicker.tsx`; no `dangerouslySetInnerHTML` anywhere in the new code.
- [x] Symlink escape: entries pointing outside `/mnt/nas` are skipped before being listed — execution-verified against a symlink that pointed outside the mount.
- [x] No secrets in responses: browse response contains only `name`/`path`/`conflictType`/`message`.
- **Informational (not a new issue):** malformed input that makes `path.normalize()` throw (e.g. an embedded null byte) would surface as an n8n unhandled-node error rather than a clean 400, in the `JWT+Validate: GET Browse` node. This matches the pre-existing error-handling posture of every other Code node in this workflow (e.g. the shared JWT-decode block also isn't defensively wrapped) — not a regression introduced by PROJ-74, and worst case is a 500, no data exposure.

### Bugs Found

#### BUG-1: Edit picker's starting folder never re-checks its own conflict status against other active folders
- **Severity:** Low
- **Steps to Reproduce:**
  1. (Requires pre-existing overlapping DMS folders in the DB — an already-acknowledged out-of-scope legacy-data scenario per this spec's own Edge Cases.) Edit a folder A whose path already conflicts with a different active folder B (from before this feature existed).
  2. Open the path picker for A without navigating anywhere.
  3. Expected (per AC): the picker should reflect that A's own path conflicts with B and disable "Diesen Ordner auswählen".
  4. Actual: `FolderPathPicker`'s initial navigation-stack entry hardcodes `conflictType: null` for the starting path rather than querying it, so the button shows enabled for that specific starting node only. Every other node reached by actually browsing gets accurate, freshly-queried conflict data.
- **Consequence:** None functionally — if the user clicks Select without changing anything, `EditFolderDialog` diffs against `folder.path` and omits `path` from the PUT body entirely (no-op), so the backend's authoritative conflict check is never bypassed and no bad data can be written.
- **Priority:** Nice to have (not blocking).

#### BUG-2: 409 responses showed a generic message instead of the backend's conflict-type-specific message — FIXED
- **Severity:** High
- **Steps to Reproduce:**
  1. Trigger a POST or PUT that returns 409 (e.g. an ancestor/descendant path conflict).
  2. Expected (explicit AC): a distinct error message per conflict type, as produced by the new conflict-check sub-workflow.
  3. Actual (before fix): `createFolder()`/`updateFolder()` in `frontend/src/services/dms.ts` had a hardcoded `throw new Error("Dieser Pfad existiert bereits.")` on any 409, discarding the response body entirely — silently defeating the backend work.
- **Fix applied:** both functions now `await res.json()` on 409 and throw `body.error` (falling back to the old generic string only if the body can't be parsed), matching the pattern already used for 400 responses in the same file.
- **Verification:** re-ran `npm run build` after the fix — clean.
- **Priority:** Fixed before this QA pass concluded.

### Summary
- **Acceptance Criteria:** 24/24 passed on implementation review (2 of those — the browse endpoint's live reachability and a truly-offline-mount scenario — are implementation-verified but still need a live deployed environment to fully confirm end-to-end).
- **Bugs Found:** 2 total (0 critical, 1 high — fixed during this pass, 0 medium, 1 low — not blocking).
- **Security:** Pass, one informational note (pre-existing pattern, not a regression).
- **Production Ready (code-level):** YES — no unresolved Critical/High bugs.
- **Recommendation:** Approve at the code/spec level. Before `/deploy`: (1) import `alice-dms-folder-conflict-check` into n8n, (2) update the placeholder `PENDING_IMPORT_alice-dms-folder-conflict-check` workflow ID in the three `Execute Workflow` nodes inside `alice-dms-folder-api.json` to the real assigned id, (3) deploy `alice-dms-folder-api`, then (4) do one real browser smoke test of the Add/Edit picker flows against the live backend before considering this fully done — this session had no live environment to do that itself.

### Post-Deployment Smoke Test Findings (2026-08-03)

User performed exactly the live smoke test recommended above and found 3 issues, all fixed in this same session:

#### BUG-3: Breadcrumb navigation to a parent/ancestor folder did not work
- **Severity:** High
- **Root cause:** `FolderPathPicker` tracked navigation via a click-history stack (`{path, conflictType}[]`). When the Edit picker opens directly several levels deep (the normal case — e.g. `/mnt/nas/andreas/Documents/Finanzen/Ing DiBa/Depot/Order`), the stack starts with only 1 entry, but the breadcrumb displayed one segment per path component. Clicking an ancestor segment tried to truncate a stack that never had entries for those levels, so nothing happened.
- **Fix:** rewrote `FolderPathPicker` to derive breadcrumb navigation directly from the current path string (`pathAtDepth()`), not click history. The now-unrelated need to know "does the current folder itself conflict" is solved by extending the backend `browse` route (`alice-dms-folder-api.json`, `Code: Build Browse Conflict Input` / `Code: Build Browse Response`) to also report the *browsed path's own* conflict status alongside its children's — one extra candidate path per browse call. This also fixes BUG-1 from the original QA pass as a side effect (the starting folder's conflict status is now always freshly server-verified, never assumed).
- **Verification:** functional simulation (`browse_response_sim.js`, run via `node`) of the full conflict-input → sub-workflow → response-building chain against 3 scenarios (own-path genuinely conflicting with another active folder, own-path correctly excluded when it's the folder being edited, and a folder several levels deep showing an inherited ancestor conflict) — all correct. `npm run build` clean.
- **Requires re-deploy:** `alice-dms-folder-api` (browse route logic changed; `alice-dms-folder-conflict-check` sub-workflow itself is unchanged).

#### BUG-4: Path field and "Ordner wählen" button were two separate elements
- **Severity:** Low (UX)
- **Fix:** merged into a single clickable element in `AddFolderDialog.tsx`/`EditFolderDialog.tsx` — the path display itself now opens the picker (native `title` attribute shows the full path on hover), with a folder icon replacing the separate button.

#### BUG-5: Long paths overflowed the dialog to the right, dragging all other fields with them
- **Severity:** Medium (visual, affects every folder deep enough to need it — which in the user's own reported case was the everyday path length)
- **Root cause:** `DialogContent` is `display: grid`; a CSS grid item's default `min-width` is its content's min-content size, not 0. The path text had `truncate` (`white-space: nowrap`), so its unbreakable intrinsic width became the `<form>`'s minimum width, stretching the whole form (and therefore every other field and the button row, all normal-flow block children of that same now-oversized form) past the dialog's `max-w-md` bound.
- **Fix:** added `min-w-0` to the `<form>` and its inner path wrapper in both dialogs, overriding the grid item's auto min-width so `truncate` can actually take effect within the dialog's real width.
- **Verification:** `npm run build` clean; this is a standard, well-documented Tailwind/CSS-grid interaction (not guesswork) — the same `min-w-0` pattern is required anywhere unbreakable text sits inside a flex/grid ancestor.
- **Requires re-deploy:** frontend rebuild + `./scripts/deploy-frontend.sh` (same as BUG-3/4's frontend changes).

### Refinement Follow-up (2026-08-04): Exact-match-only blocking

Per the spec Refinement documented in Overview/Acceptance Criteria/Non-Goals, ancestor/descendant overlap is no longer blocked — only an exact path duplicate is. Implemented as a 2-line change plus documentation:

- `workflows/alice-dms-folder-conflict-check.json`, `Code: Compute Conflicts`: `hasConflict` changed from `conflictType !== null` to `conflictType === 'exact'`. `conflictType` itself (exact/ancestor/descendant/null) is unchanged and still returned — it now only drives the Browse endpoint's informational badges, not the POST/PUT blocking decision.
- `frontend/src/components/Settings/FolderPathPicker.tsx`: the select-button's `hasConflict` changed from `currentConflict != null` to `currentConflict === "exact"`.
- **Verification:** ran a standalone functional test (`exact_only_blocking.test.js`, via `node`) directly against the user's own reported real-world scenario — a collector folder (`.../ING-DiBa`) containing two already-active, specifically-typed subfolders (`Depot` → SecuritySettlement, `Girokonto` → BankStatement). Confirmed: registering the collector folder now succeeds (previously blocked), a new subfolder under an active folder now succeeds, both are still correctly badged (`descendant`/`ancestor`) for transparency, and an exact duplicate of an active folder is still blocked. `npm run build` clean.
- **Requires re-deploy:** both `alice-dms-folder-conflict-check` (sub-workflow logic changed) and `alice-dms-folder-api`'s dependent behavior via that sub-workflow, plus a frontend rebuild/redeploy for the picker.

## Deployment

**Deployed:** 2026-08-04
**Production URL:** https://alice.happy-mining.de
**Deployed by:** User (manual n8n workflow import + `./scripts/deploy-frontend.sh`)

Deployed artifacts:
- n8n workflow `alice-dms-folder-conflict-check` (new sub-workflow)
- n8n workflow `alice-dms-folder-api` (browse route + POST/PUT conflict validation, updated to the exact-match-only blocking rule)
- Frontend build containing `FolderPathPicker` and the updated `AddFolderDialog`/`EditFolderDialog`

User confirmed the feature works as expected in production, including the exact-match-only conflict policy from the 2026-08-04 refinement (collector folder + specifically-typed subfolders can now coexist as separate DMS folders).
