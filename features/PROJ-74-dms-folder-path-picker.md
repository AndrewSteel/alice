# PROJ-74: DMS Pfad-Auswahlbox — Verzeichnis-Browser für NAS-Ordner

## Status: Planned

**Created:** 2026-08-03
**Last Updated:** 2026-08-03

## Dependencies

- Requires: PROJ-15 (DMS NAS-Ordner-Verwaltung) — ersetzt die manuelle Pfad-Texteingabe in `AddFolderDialog` und `EditFolderDialog`
- Requires: PROJ-65/66 (Effective-Permissions API / Granulares Rollen-Gating) — Zugriff weiterhin über `can_manage_dms_folders`

## Overview

PROJ-15 führte die Verwaltung überwachter NAS-Ordner ein, jedoch mussten Admins den absoluten Pfad manuell als Freitext eintippen — fehleranfällig und ohne Bezug zur tatsächlichen NAS-Struktur. Dieses Feature ersetzt die Texteingabe durch eine Auswahlbox (Verzeichnis-Browser), die den NAS-Baum ab `/mnt/nas` anzeigt und es dem Admin erlaubt, einen Ordner per Klick statt per Tippen auszuwählen — sowohl beim Anlegen als auch beim Ändern eines DMS-Ordners.

`/mnt/nas` ist der Mount-Punkt, unter dem mehrere unabhängige NAS-Freigaben als Geschwisterverzeichnisse eingehängt sind (z. B. `/mnt/nas/Projekte`, `/mnt/nas/Backup`). Der Mount-Punkt selbst ist keine sinnvolle Erfassungseinheit — er wird in der Auswahlbox nur als Navigationsebene angezeigt, ist aber nicht auswählbar. Auswählbar sind ausschließlich Pfade ab Tiefe 1, also `/mnt/nas/{Freigabe}` und tiefer.

Im Zuge der Konzeption wurde ein bestehendes funktionales Risiko identifiziert: Der DMS-Scanner (PROJ-16/72) verarbeitet Ordner rekursiv. Wird sowohl ein Ordner als auch einer seiner Unterordner separat als DMS-Ordner erfasst, verarbeitet der Scanner die Dateien im Unterordner doppelt. Dieses Feature führt daher zusätzlich eine Validierung ein, die das Erfassen von Ordnern verhindert, die Unter- oder Überpfad eines bereits aktiven DMS-Ordners sind.

**Kein Anlegen neuer NAS-Verzeichnisse:** Die Auswahlbox erlaubt nur die Auswahl bereits existierender NAS-Ordner (kein `mkdir`). Die manuelle Freitext-Pfadeingabe entfällt vollständig — ein NAS-Ordner muss vor der Erfassung in Alice bereits auf dem NAS existieren.

## User Stories

- Als Admin möchte ich beim Hinzufügen eines DMS-Ordners den Pfad über eine Auswahlbox aus dem NAS-Verzeichnisbaum wählen, statt ihn manuell einzutippen, damit ich keine Tippfehler mache und die tatsächliche NAS-Struktur sehe.
- Als Admin möchte ich beim Bearbeiten eines bestehenden DMS-Ordners über dieselbe Auswahlbox zu einem Unter- oder übergeordneten Ordner wechseln können, damit ich den Scan-Scope anpassen kann, ohne den Pfad neu einzutippen.
- Als Admin möchte ich in der Auswahlbox erkennen, welche Ordner bereits als DMS-Ordner erfasst sind (oder mit einem erfassten Ordner in Konflikt stehen), damit ich keine doppelte oder überlappende Erfassung vornehme.
- Als Admin möchte ich innerhalb der Auswahlbox navigieren können (in Unterordner hinein, per Breadcrumb wieder heraus), damit ich auch tief verschachtelte NAS-Ordner erreichen kann.
- Als System (DMS Scanner) möchte ich weiterhin nur eindeutige, nicht überlappende Ordnerpfade aus der Datenbank lesen, damit keine Datei doppelt verarbeitet wird.

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

- [ ] Ordner, die exakt einem bereits aktiven (`enabled = true`) DMS-Ordner entsprechen, werden in der Liste als "Bereits erfasst" markiert und sind nicht auswählbar
- [ ] Ordner, die Unterordner eines bereits aktiven DMS-Ordners sind, werden als "Liegt unterhalb eines bereits erfassten Ordners" markiert und sind nicht auswählbar
- [ ] Ordner, die einen bereits aktiven DMS-Ordner als Unterordner enthalten (Ordner ist Überordner), werden als "Enthält bereits erfassten Ordner" markiert und sind nicht auswählbar
- [ ] `/mnt/nas` selbst wird nie als "Überordner-Konflikt" markiert, obwohl es rein pfadtechnisch Präfix jedes registrierten Ordners ist — da es ohnehin nicht auswählbar ist (siehe oben), ist die Konflikt-Prüfung auf Pfade ab Tiefe ≥ 1 beschränkt
- [ ] Im Edit-Dialog gilt die Konflikt-Markierung nicht für den gerade bearbeiteten Ordner selbst — sein aktueller Pfad sowie dessen Unter-/Überordner bleiben auswählbar, solange sie nicht mit einem ANDEREN aktiven DMS-Ordner in Konflikt stehen
- [ ] Deaktivierte (`enabled = false`) DMS-Ordner lösen keine Konflikt-Markierung aus

### Backend-Validierung (Defense in Depth)

- [ ] **POST** `/webhook/dms/folders` lehnt einen Pfad ab, der identisch mit, Unterpfad von, oder Überpfad eines bereits aktiven DMS-Ordners ist → 409 Conflict mit eindeutiger Fehlermeldung je Konflikttyp
- [ ] **POST**/**PUT** lehnen `/mnt/nas` selbst (exakt, ohne Unterpfad) als Pfad ab → 400 Bad Request ("Der NAS-Mount-Punkt selbst kann nicht als Ordner erfasst werden")
- [ ] **PUT** `/webhook/dms/folders/:id` wendet dieselbe Konflikt-Prüfung an, wobei der zu aktualisierende Ordner selbst von der Prüfung ausgenommen ist
- [ ] Die Ancestor/Descendant-Prüfung berücksichtigt ausschließlich aktive (`enabled = true`) Ordner und ausschließlich Pfade ab Tiefe ≥ 1 unterhalb von `/mnt/nas`
- [ ] Neuer Browse-Endpunkt liefert für einen gegebenen Pfad die Liste der direkten Unterverzeichnisse inkl. Markierungs-Information (bereits erfasst / Unterordner-Konflikt / Überordner-Konflikt), JWT-geschützt und auf `can_manage_dms_folders` beschränkt (analog zu den bestehenden CRUD-Endpunkten)
- [ ] Der Browse-Endpunkt verweigert Pfade außerhalb von `/mnt/nas` (Path-Traversal-Schutz, z. B. `../../etc`)

### Fehler- und Leerzustände

- [ ] Ist ein Verzeichnis nicht lesbar (Berechtigungsfehler auf dem NAS), zeigt die Auswahlbox eine Fehlermeldung statt einer leeren Liste
- [ ] Ein Verzeichnis ohne Unterordner zeigt einen Leerzustand ("Keine Unterordner") — "Diesen Ordner auswählen" bleibt trotzdem nutzbar (außer auf Root-Ebene, siehe oben)
- [ ] Ist `/mnt/nas` selbst nicht erreichbar, zeigt die Auswahlbox einen Fehlerzustand mit Hinweis, dass der NAS-Mount nicht verfügbar ist

## Edge Cases

- **Pfad wird nach Auswahl auf dem NAS gelöscht, bevor gespeichert wird**: POST/PUT läuft regulär durch bestehende PROJ-15-Logik (Pfad muss laut EC-1 aus PROJ-15 nicht zwingend existieren) — kein Sonderfall nötig.
- **Zwei Admins bearbeiten gleichzeitig verschachtelte Ordner**: Race Condition zwischen Konflikt-Prüfung und Speichern ist möglich (TOCTOU). Die Backend-Validierung bei POST/PUT ist die verbindliche Prüfung; die UI-Markierung ist nur ein proaktiver Hinweis. Bei einem nach dem Öffnen der Auswahlbox neu angelegten, überlappenden Ordner greift serverseitig weiterhin der 409.
- **Bestehende, bereits überlappende Ordner in der Datenbank** (vor diesem Feature angelegt): Werden NICHT rückwirkend validiert oder bereinigt — außerhalb des Scopes dieses Features.
- **Sehr viele Unterordner (Performance)**: Auswahlbox zeigt alle direkten Unterordner der aktuellen Ebene ohne Paginierung (i. d. R. keine sehr breiten Verzeichnisse auf dem NAS zu erwarten); keine Sonderbehandlung in diesem Feature.
- **Admin will einen Ordner erfassen, der noch nicht auf dem NAS existiert**: Nicht mehr möglich — der Ordner muss zuerst auf dem NAS angelegt werden (siehe Overview). Das ist eine bewusste Verhaltensänderung gegenüber PROJ-15 EC-1.
- **Reaktivierung eines deaktivierten, überlappenden Ordners**: Der `enabled`-Switch (inline PATCH) prüft in diesem Feature NICHT auf Konflikte mit anderen aktiven Ordnern — das Aktivieren eines zuvor deaktivierten, überlappenden Ordners kann somit wieder zu doppelter Scanner-Verarbeitung führen. Explizit als Non-Goal (siehe unten) markiert, nicht Teil dieses Features.
- **Admin öffnet die Auswahlbox direkt auf `/mnt/nas`, ohne zu navigieren**: "Diesen Ordner auswählen" ist deaktiviert; der Admin muss mindestens eine Ebene tiefer navigieren, bevor eine Auswahl möglich ist.

## Non-Goals

- Keine Möglichkeit, neue NAS-Verzeichnisse aus der Auswahlbox heraus anzulegen (kein `mkdir`)
- Keine manuelle Freitext-Pfadeingabe als Fallback
- Keine rückwirkende Bereinigung/Validierung bereits bestehender, überlappender DMS-Ordner in der Datenbank
- Keine Konflikt-Prüfung beim Reaktivieren (`enabled`-Switch) eines zuvor deaktivierten Ordners

## Technical Requirements (optional)

- Browse-Endpunkt beschränkt auf den Unterbaum von `/mnt/nas`; Pfad-Normalisierung erforderlich, um Path-Traversal zu verhindern
- Ancestor/Descendant-Prüfung basiert auf String-Präfixvergleich normalisierter absoluter Pfade, beginnend erst ab Tiefe 1 unterhalb `/mnt/nas` (z. B. ist `/mnt/nas/Projekte` Präfix von `/mnt/nas/Projekte/Rechnungen`, aber `/mnt/nas` selbst wird als gemeinsamer Mount-Punkt von der Prüfung ausgenommen)

---

<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)

_To be added by /architecture_

## QA Test Results

_To be added by /qa_

## Deployment

_To be added by /deploy_
