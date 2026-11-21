---
name: to-factory
description: Hand an approved feature spec to the Software Factory by creating a GitHub issue with the factory label that points to the spec. Use after /write-spec, once the spec is committed and pushed.
argument-hint: "PROJ-X"
user-invocable: true
disable-model-invocation: true
---

# An die Software Factory übergeben

Übergibt eine fertige, vom Menschen abgenommene Spec an die Software Factory.

## Schritte

1. **Spec finden:** `ls features/<PROJ-X>-*/spec.md 2>/dev/null` → `<spec-pfad>`. Gibt es keine, abbrechen: „Für <PROJ-X> gibt es noch keine Spec. Erst `/write-spec`." (Alte Specs unter `features/old/` werden nicht übergeben.)

2. **Prüfen, dass die Spec auf GitHub liegt.** Die Factory liest sie vom Standard-Branch, nicht von deinem Rechner.
   - Standard-Branch: `gh repo view --json defaultBranchRef --jq .defaultBranchRef.name`
   - `git fetch origin` und prüfen, dass die Spec auf `origin/<standard-branch>` identisch ist: `git diff --quiet origin/<standard-branch> -- <spec-pfad>`
   - Ist sie lokal geändert, nicht committet oder nicht gepusht: dem Nutzer sagen, was fehlt, und fragen, ob du committen und pushen sollst. Nicht ungefragt pushen.

3. **Doppelte Übergabe vermeiden:** `gh issue list --label factory --state open --search "<PROJ-X> in:title" --json number,title`. Gibt es schon ein offenes Issue, dessen Link zeigen und abbrechen.

4. **Issue anlegen:**
   - Titel: `<PROJ-X>: <Feature-Name aus der Spec>`
   - Label: `factory`
   - Text:
     ```
     Spec: <spec-pfad>

     <ein Satz, worum es geht, aus den User Stories>

     **Akzeptanzkriterien (Kurzfassung):**
     - AK-1: …
     - AK-2: …

     _Die Spec ist der Vertrag. Die Factory baut danach und meldet sich hier bei Fragen._
     ```
   - Befehl: `gh issue create --label factory --title "…" --body-file <datei>`
   - `features/INDEX.md` hier **nicht** ändern. Den Status pflegt ab jetzt die Factory in ihrem Branch.

5. **Rückmeldung an den Nutzer:** Issue-Link und der Hinweis, dass die Factory es innerhalb einer Minute übernimmt. Fortschritt über die Labels am Issue bzw. das Board.
