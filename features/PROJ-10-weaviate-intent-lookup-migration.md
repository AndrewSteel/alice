# PROJ-10: Weaviate Intent Lookup — Migration auf native n8n-Nodes

## Status: Planned
**Created:** 2026-02-28
**Last Updated:** 2026-02-28

## Dependencies
- Requires: PROJ-1 (HA Intent Infrastructure) — HAIntent-Collection in Weaviate muss existieren
- Requires: PROJ-9 (Chat-Handler JWT-Schutz) — stabiler Chat-Handler als Basis

---

## Übersicht

Die „Intent Lookup"-Node im `alice-chat-handler`-Workflow verwendet aktuell eine Code-Node mit `axios`, die direkt gegen Weaviates GraphQL-API (`/v1/graphql`) schlägt. Diese Lösung ist funktionsfähig, aber technisch suboptimal:

- Die Verbindungs-URL (`http://weaviate:8080`) ist hart einkodiert
- HTTP-Fehler und Verbindungsprobleme sind schwer zu debuggen (nur `weaviateError: true`)
- n8n's native Weaviate-Nodes bieten Credential-Verwaltung, automatisches Retrying und laufen im Haupt-Prozess (kein Runner-Sandbox-Problem)
- Der Code mischt Netzwerk-Logik, Filterung und Routing-Entscheidung in einem einzigen, schwer lesbaren Node

Dieses Feature ersetzt den Code-Node durch native n8n Weaviate-Nodes und trennt die Verantwortlichkeiten klar auf.

---

## Hintergrund: Warum Code-Node aktuell nötig war

Der ursprüngliche Code-Node wurde gewählt, weil:
1. Die nearText-Suche mit Certainty-Filter und Priority-Sortierung komplex ist
2. Die Routing-Entscheidung (HA_FAST / HYBRID / LLM_ONLY) direkt im selben Node erfolgte
3. `$env`-Zugriff für die URL angenommen wurde (funktioniert nicht in n8n)

Nach der Migration zu nativen Nodes lassen sich diese Concerns sauber trennen.

---

## User Stories

1. **Als Entwickler** möchte ich, dass die Weaviate-Verbindung über ein n8n-Credential konfiguriert ist, damit ich die URL und Auth zentral verwalten kann ohne Workflow-JSON zu ändern.

2. **Als Entwickler** möchte ich, dass die Intent-Lookup-Logik in klar benannten n8n-Nodes aufgeteilt ist (Suche / Filter / Routing), damit ich einzelne Schritte im n8n-Executor-Log nachvollziehen und debuggen kann.

3. **Als Operator** möchte ich, dass ein Weaviate-Ausfall sauber als `pathDecision = 'LLM_ONLY'` erkannt wird — mit einem aussagekräftigen Fehlerlog in n8n statt einem stummen `weaviateError: true`.

4. **Als Operator** möchte ich die Certainty-Schwelle (`INTENT_MIN_CERTAINTY`) und die maximale Ergebniszahl (`INTENT_MAX_RESULTS`) ohne Code-Änderung konfigurieren können — z. B. über ein n8n-Workflow-Setting oder einen Set-Node am Workflow-Anfang.

---

## Acceptance Criteria

### Weaviate Credential
- [ ] Ein Weaviate-Credential ist in n8n angelegt (Type: `weaviate`, URL: `http://weaviate:8080`)
- [ ] Die Intent Lookup-Nodes verwenden dieses Credential — keine hart kodierte URL im Code

### Funktionale Gleichwertigkeit
- [ ] nearText-Suche auf der `HAIntent`-Collection liefert dieselben Ergebnisse wie bisher
- [ ] Certainty-Filterung funktioniert (Standard: ≥ 0.82)
- [ ] Sortierung nach Certainty (absteigend), dann Priority (absteigend) ist erhalten
- [ ] `requiresConfirmation` wird für Domains `lock` und `alarm_control_panel` korrekt gesetzt
- [ ] Routing-Entscheidung `HA_FAST` / `HYBRID` / `LLM_ONLY` ist identisch zum aktuellen Verhalten
- [ ] Bei Weaviate-Ausfall: `pathDecision = 'LLM_ONLY'`, Workflow läuft weiter (kein Absturz)

### Mehrere Satzteile (`parts`)
- [ ] Wenn `$json.parts` mehrere Einträge hat, wird für jeden Teil eine separate Suche durchgeführt
- [ ] Die Routing-Entscheidung berücksichtigt alle Teile (alle matched → HA_FAST, teilweise → HYBRID, keine → LLM_ONLY)

### Konfigurierbarkeit
- [ ] `INTENT_MIN_CERTAINTY` (Standard 0.82) ist ohne Code-Änderung anpassbar
- [ ] `INTENT_MAX_RESULTS` (Standard 3) ist ohne Code-Änderung anpassbar

### Observability
- [ ] Im n8n-Execution-Log ist pro Suche sichtbar: Suchbegriff, Anzahl Kandidaten, bestes Ergebnis mit Certainty
- [ ] Weaviate-Fehler erzeugen einen aussagekräftigen Log-Eintrag (nicht nur `weaviateError: true`)

---

## Edge Cases

- **Weaviate nicht erreichbar:** Graceful fallback auf `LLM_ONLY`, kein Workflow-Absturz
- **HAIntent-Collection leer:** Kein Match → `LLM_ONLY` (korrekt)
- **Certainty-Schwelle nie erreicht:** Alle Kandidaten unterhalb → `LLM_ONLY`
- **Sehr langer Eingabetext:** Suchstring auf 500 Zeichen begrenzt (wie bisher)
- **Sonderzeichen in der Eingabe:** Werden sicher für die Weaviate-Suche escapet
- **Timeout:** Weaviate antwortet nicht innerhalb von 5 Sekunden → Fehler, Fallback auf `LLM_ONLY`

---

## Abgrenzung (Out of Scope)

- Kein Änderung am Weaviate-Schema oder der HAIntent-Collection (PROJ-1)
- Keine neue Intent-Logik oder neue Domains
- Kein Umbau des HA-Fast-Executor oder anderer Downstream-Nodes
- Rename-Button in ChatListItem (BUG-7) gehört nicht zu diesem Feature

---

## Technische Hinweise (für Architecture/Backend)

- n8n Weaviate-Node: `n8n-nodes-base.weaviate` — unterstützt nearText über „Additional Fields"
- Certainty-Filter und Priority-Sortierung benötigen wahrscheinlich einen nachgelagerten Code-Node (da native Node keine Post-Filter-Logik hat)
- Alternative: HTTP-Request-Node mit dem Weaviate-Credential statt Code-Node (mehr Kontrolle als native Node, besser als axios in Code)
- Für Mehrteile-Handling (`parts`-Array) ggf. Split-in-Batches-Node + Merge nötig
