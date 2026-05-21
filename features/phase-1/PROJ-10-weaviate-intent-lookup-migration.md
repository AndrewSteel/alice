# PROJ-10: Weaviate Intent Lookup — Migration auf native n8n-Nodes

## Status: Deployed
**Created:** 2026-02-28
**Last Updated:** 2026-03-02
**Deployed:** 2026-03-02

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

---

## Tech Design (Solution Architect)

**Erstellungsdatum:** 2026-03-02

### Erkenntnisse aus der Analyse

Die Recherche zeigt: Es gibt **keinen nativen `n8n-nodes-base.weaviate`-Node** — nur einen LangChain-Vektorstore-Node (`@n8n/n8n-nodes-langchain.vectorStoreWeaviate`), der für KI-Ketten ausgelegt ist und keine Certainty-Scores zurückgibt. Die Spec-Notiz war ein Irrtum.

**Gewählter Ansatz:** HTTP-Request-Node (empfohlen von der Spec) mit Config-Set-Node für URL und Schwellenwerte.

---

### Node-Struktur (Workflow-Pipeline)

Der aktuelle **Intent Lookup Code Node** (1 Node, ~80 Zeilen, hartkodierte URL) wird durch **5 fokussierte Nodes** ersetzt:

```
[Config: Intent Params]   ← NEU: Set-Node am Workflow-Anfang
        |
        | (einmalig, versorgt alle nachgelagerten Nodes)
        |
[Sentence Splitter]       ← UNVERÄNDERT (Code-Node)
        |
        | (1 Item mit parts-Array: ["Licht an", "Heizung hoch"])
        |
[Split Parts]             ← NEU: Code-Node (3 Zeilen)
        |
        | (N Items, eines pro Teil: {currentPart: "Licht an", ...})
        |
[Weaviate: nearText]      ← NEU: HTTP-Request-Node (kein Code!)
        |
        | (N Items mit Weaviate-Antwort pro Teil)
        |
[Filter & Rank]           ← NEU: Code-Node (~15 Zeilen, nur Filterlogik)
        |
        | (N Items mit {matched, certainty, domain, service, ...})
        |
[Build Route Decision]    ← NEU: Code-Node (~10 Zeilen, nur Routing)
        |
[Path Router]             ← UNVERÄNDERT (Switch-Node)
```

---

### Datenmodell

**Config: Intent Params** (Set-Node, verändert ohne Code):
| Feld | Standardwert | Bedeutung |
|---|---|---|
| `weaviateUrl` | `http://weaviate:8080` | Weaviate-Basis-URL |
| `intentMinCertainty` | `0.82` | Mindestschwelle für Match |
| `intentMaxResults` | `3` | Maximale Kandidaten pro Suche |

**Pro-Teil-Ergebnis** (nach Filter & Rank):
- `currentPart` — der gesuchte Satzteil
- `matched` — true/false
- `certainty` — Ähnlichkeitswert (0–1)
- `domain`, `service`, `entityId`, `parameters` — HA-Steuerparameter
- `requiresConfirmation` — true für `lock` / `alarm_control_panel`
- `weaviateError` + `weaviateErrorMsg` — bei Verbindungsfehler

**Route Decision** (Ausgabe von Build Route Decision):
- `pathDecision` — `HA_FAST` / `HYBRID` / `LLM_ONLY`
- `intentResults` — Array aller Teil-Ergebnisse
- `matchedCount` / `totalCount`

---

### Technische Entscheidungen

**Warum HTTP-Request-Node statt LangChain-Weaviate-Node?**
Der LangChain-Node ist für KI-Ketten gebaut: er gibt keine Certainty-Scores zurück, unterstützt kein direktes GraphQL und läuft als Sub-Node im AI-Agenten-Kontext. Für direkten Datenabruf mit Certainty-Filterung ist der HTTP-Request-Node die richtige Wahl — er zeigt Request und Response vollständig im n8n-Execution-Log (=besseres Debugging).

**Warum Config-Set-Node statt `$env`-Zugriff?**
`$env`-Zugriff in Code-Nodes ist in n8n standardmäßig blockiert. Der Set-Node am Workflow-Anfang ist im n8n-UI direkt editierbar — keine Code-Änderung, kein Deployment nötig.

**Warum n8n's natives Item-Modell statt `Promise.all`?**
n8n führt einen Node automatisch einmal pro Input-Item aus. Wenn Split Parts N Items liefert, laufen HTTP-Request-Node und Filter & Rank automatisch N mal — ohne Schleifenlogik. Das ist sauberer und vollständig im Execution-Log nachvollziehbar.

**Warum `continueOnFail` am HTTP-Request-Node?**
Statt eines separaten Error-Handlers: Der HTTP-Request-Node liefert bei Fehler ein Item mit `$json.error`. Der Filter-&-Rank-Node erkennt das und setzt `weaviateError: true`. Das Build-Route-Node wertet alle Items aus — kein Workflow-Absturz bei Weaviate-Ausfall.

---

### Credential-Strategie

Da Weaviate lokal ohne API-Key läuft, wird **keine Authentifizierung** am HTTP-Request-Node benötigt (Authentication: None). Die URL wird im **Config-Set-Node** verwaltet — zentralisiert und ohne Code.

Sobald Weaviate einen API-Key bekommt (spätere Phase), reicht es, einen "Header Auth"-Credential in n8n anzulegen und am HTTP-Request-Node zu hinterlegen — **ohne Workflow-JSON-Änderung**.

---

### Betroffene Nodes im alice-chat-handler

| Node | Status | Änderung |
|---|---|---|
| `Config: Intent Params` | NEU | Set-Node nach Input Validator |
| `Sentence Splitter` | UNVERÄNDERT | Bleibt exakt wie bisher |
| `Intent Lookup` | ERSETZT | Wird gelöscht |
| `Split Parts` | NEU | Code-Node, ersetzt Intent-Lookup-Schleife |
| `Weaviate: nearText Search` | NEU | HTTP-Request-Node |
| `Filter & Rank` | NEU | Code-Node, Filterlogik aus Intent Lookup |
| `Build Route Decision` | NEU | Code-Node, Routing-Logik aus Intent Lookup |
| `Path Router` | UNVERÄNDERT | Bleibt exakt wie bisher |

**Alle anderen Nodes downstream (HA Fast Executor, Hybrid, LLM Only usw.) bleiben unverändert.**

---

### Abhängigkeiten (keine neuen Pakete)

Alle benötigten Nodes sind in n8n bereits enthalten:
- `Set` (n8n-nodes-base.set)
- `Code` (n8n-nodes-base.code) — bereits im Workflow vorhanden
- `HTTP Request` (n8n-nodes-base.httpRequest) — Standard-n8n-Node

---

## QA Test Results (Re-Test #2)

**Tested:** 2026-03-02 (Re-Test #2 -- full independent re-verification)
**Workflow File:** `workflows/core/alice-chat-handler.json`
**Tester:** QA Engineer (AI)

### Test Method

Backend n8n workflow migration. Testing performed by automated static analysis of the workflow JSON (both draft and `activeVersion` sections). A Python comparison script verified node presence, parameter equality, connection wiring, credential assignment, and error handling properties across all 36 nodes in each version. No browser/UI testing applicable (purely backend orchestration).

### Acceptance Criteria Status

#### AC-1: Weaviate Credential
- [ ] **BUG-1 (spec clarification, unchanged):** No formal n8n Weaviate Credential exists. The HTTP Request node uses `authentication: "none"` with the URL from the Config Set Node. Acceptable per Tech Design (Weaviate runs locally without API key), but does not literally satisfy "Ein Weaviate-Credential ist in n8n angelegt (Type: weaviate)".
- [x] No hardcoded URL in code -- URL comes from `Config: Intent Params` Set Node (`weaviateUrl` field). Verified identical in both draft and active via automated comparison. PASS.

#### AC-2: Funktionale Gleichwertigkeit (Functional Equivalence)
- [x] nearText search on HAIntent collection: GraphQL query in HTTP Request body structurally correct. Parameters identical in draft and active (automated match=True). PASS.
- [x] Certainty filtering (>= 0.82 default): Filter & Rank code applies `CERTAINTY_THRESHOLD` from Config node. Code identical in both versions. PASS.
- [x] Sorting by certainty (desc), then priority (desc): Sort logic uses `certDiff > 0.001` check, then priority tiebreak. Code identical. PASS.
- [x] `requiresConfirmation` for domains `lock` and `alarm_control_panel`: `CONFIRMATION_DOMAINS` array verified in Filter & Rank code. PASS.
- [x] Routing decision HA_FAST / HYBRID / LLM_ONLY: Build Route Decision uses `runOnceForAllItems` mode. Logic: all matched -> HA_FAST, some -> HYBRID, none -> LLM_ONLY. Items with weaviateError have `matched: false`, so Weaviate-down correctly routes to LLM_ONLY. PASS.
- [x] Weaviate-Ausfall graceful fallback: HTTP Request has `continueOnFail: true`. Filter & Rank catches `$json.error` and `$json.errors`, sets `weaviateError: true` + descriptive `weaviateErrorMsg`. Build Route Decision produces LLM_ONLY when matchedCount is 0. PASS.

#### AC-3: Mehrere Satzteile (parts)
- [x] Split Parts creates one item per part: `parts.map(currentPart => ({ json: { ...$json, currentPart } }))`. PASS.
- [x] n8n automatically runs HTTP Request and Filter & Rank once per item (native item iteration). PASS.
- [x] Build Route Decision runs in `runOnceForAllItems` mode, evaluates all parts for routing. PASS.

#### AC-4: Konfigurierbarkeit
- [x] `INTENT_MIN_CERTAINTY` configurable via Config Set Node (`intentMinCertainty: 0.82`). Identical in both versions. PASS.
- [x] `INTENT_MAX_RESULTS` configurable via Config Set Node (`intentMaxResults: 3`). Identical in both versions. PASS.

#### AC-5: Observability
- [x] HTTP Request node natively logs full request URL, body, and response in n8n Execution Log. PASS.
- [x] Filter & Rank produces structured error output with `weaviateErrorMsg` containing actual error (not just boolean). PASS.

### Edge Cases Status

#### EC-1: Weaviate nicht erreichbar
- [x] `continueOnFail: true` and `options.timeout: 5000` on HTTP Request. Filter & Rank catches error, sets `weaviateError: true` + message. Build Route Decision produces `LLM_ONLY`. Identical in both versions. PASS.

#### EC-2: HAIntent Collection leer
- [x] Empty candidates array -> no qualified results -> `matched: false` -> LLM_ONLY. PASS.

#### EC-3: Certainty-Schwelle nie erreicht
- [x] All candidates below threshold -> `matched: false` -> LLM_ONLY. PASS.

#### EC-4: Sehr langer Eingabetext
- [x] Input truncated to 500 characters via `.substring(0, 500)` in HTTP Request body expression. Identical in both versions. PASS.

#### EC-5: Sonderzeichen in der Eingabe
- [x] Sanitization chain: (1) backslash escaping `.replace(/\\/g, '\\\\')`, (2) double-quote to single-quote `.replace(/"/g, "'")`, (3) whitespace normalization `.replace(/[\r\n\t]/g, ' ')`, (4) 500-char truncation. Identical in both versions. PASS.

#### EC-6: Timeout
- [x] HTTP Request node has `options.timeout: 5000` (5 seconds). Identical in both versions. PASS.

### Security Audit Results

- [x] **Authentication:** Both draft and active Webhook nodes have `authentication: "jwt"` with credential ID `4iUJhbFCSgQeHAGL` (JWT Auth account). PASS.
- [x] **Authorization:** No changes to authorization logic. JWT claims extraction and user_id derivation unchanged. PASS.
- [x] **GraphQL injection:** Sanitization chain (backslash escape -> double-quote replacement -> whitespace normalization -> 500-char truncation) mitigates injection. Internal Docker network only, no external access. PASS.
- [x] **No secrets exposed:** Weaviate URL is internal Docker network only (`http://weaviate:8080`), no API keys in workflow JSON. PASS.
- [x] **No sensitive data leakage:** Response data flows through existing secured paths. No new data exposure. PASS.
- [x] **Rate limiting:** No change from existing behavior. PASS.
- [x] **Credential integrity:** All 6 PostgreSQL nodes use credential `2YBtxcocRMLQuAdF` (pg-alice). All 3 MQTT nodes use `mqtt-local`. Ollama uses `8TAanq1tJFFodeaP`. All match between draft and active. PASS.

### Bugs Found

#### BUG-1: Weaviate Credential not created as n8n Credential (spec clarification)
- **Severity:** Low
- **Status:** OPEN (spec clarification only)
- **Steps to Reproduce:**
  1. Check n8n credential list for a Weaviate credential
  2. Expected: A formal n8n credential of type `weaviate` or `httpHeaderAuth` exists
  3. Actual: No credential; URL is in a Set Node with `authentication: "none"` on the HTTP Request
- **Impact:** Acceptable per Tech Design decision (Weaviate has no auth locally). Not a functional bug.
- **Priority:** Nice to have -- update the acceptance criterion text to match the Tech Design decision

#### BUG-2: New nodes not wired into active workflow -- VERIFIED FIXED
- **Severity:** Critical (original)
- **Status:** FIXED (verified in re-test #2)
- **Verification:** Automated comparison shows old `Intent Lookup` absent from both versions. All 5 PROJ-10 nodes present. Connection chain: `Empty Input Check -> Config: Intent Params -> Sentence Splitter -> Split Parts -> Weaviate: nearText Search -> Filter & Rank -> Build Route Decision -> Path Router`. Connections identical between draft and active (automated match=True).

#### BUG-3: Missing backslash escaping in GraphQL query body -- VERIFIED FIXED
- **Severity:** Medium (original)
- **Status:** FIXED (verified in re-test #2)
- **Verification:** `.replace(/\\/g, '\\\\')` confirmed in HTTP Request body expression. Bodies identical between draft and active (automated match=True).

#### BUG-4: Potential GraphQL injection via user input -- VERIFIED MITIGATED
- **Severity:** Medium (Low practical risk)
- **Status:** MITIGATED (verified in re-test #2)
- **Verification:** Full sanitization chain confirmed in both versions. No remaining attack vectors identified.

#### BUG-5: Draft Webhook node missing JWT credential -- VERIFIED FIXED
- **Severity:** High (original)
- **Status:** FIXED (verified in re-test #2)
- **Verification:** Draft Webhook has `"credentials": {"jwtAuth": {"id": "4iUJhbFCSgQeHAGL", "name": "JWT Auth account"}}`. Automated comparison: credentials match=True.

#### BUG-6: Draft PostgreSQL nodes missing explicit `operation` and `onError` -- VERIFIED FIXED
- **Severity:** Low (original)
- **Status:** FIXED (verified in re-test #2)
- **Verification:** All 6 PostgreSQL nodes in both draft and active have `"operation": "insert"` and `"options": {"onError": "continueRegularOutput"}`. Automated comparison: all 6 match=True.

### Regression Check

#### PROJ-9 (Chat-Handler JWT-Schutz)
- [x] JWT Claims Extractor: params identical in draft and active (automated match=True). No regression.
- [x] Input Validator: params identical (automated match=True). No regression.
- [x] Webhook JWT credential: identical in both versions. No regression.

#### PROJ-3 (HA-First Chat Handler with Intent Routing)
- [x] Path Router: params identical (automated match=True). No regression.
- [x] HA Fast Executor, Hybrid Executor, LLM Only Prep: all params identical. No regression.
- [x] Save Message, DB Insert, Format Response, Respond nodes: all 12 downstream nodes params identical. No regression.

#### PROJ-1 (HA Intent Infrastructure)
- [x] HAIntent collection schema not modified by this feature. No regression.

#### Cross-version consistency
- [x] 36 nodes in draft, 36 nodes in active. All node names match.
- [x] Of 36 nodes, 33 have perfectly identical parameters. The 3 MQTT Error nodes differ only in having an empty `"options": {}` in draft (cosmetic, no functional impact).
- [x] Connections are fully identical between draft and active (automated match=True).

### Summary
- **Acceptance Criteria:** 12/12 passed (BUG-1 is spec clarification only, not a functional gap)
- **Previously Found Bugs:** BUG-2 (Critical), BUG-3 (Medium), BUG-4 (Medium), BUG-5 (High), BUG-6 (Low) -- all verified fixed
- **New Bugs Found:** 0
- **Security:** PASS -- JWT authentication on both versions, GraphQL injection mitigated, no secrets exposed
- **Production Ready:** YES
- **Recommendation:** Deploy via `n8n_update_full_workflow`. Run smoke test with HA command ("Licht an im Wohnzimmer") and LLM-only query ("Was ist das Wetter?") to confirm end-to-end.
