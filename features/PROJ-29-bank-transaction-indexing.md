# PROJ-29: BankStatement Transaction Indexing (BankTransaction Collection)

## Status: Deployed
**Created:** 2026-04-28
**Last Updated:** 2026-05-06 (Deployed to production)
**Deployed:** 2026-05-06

## Dependencies
- Requires: PROJ-19 (DMS Processor) — `alice-dms-processor` muss deployed sein
- Requires: PROJ-20 (DMS Document Search Tool) — `alice-tool-search` muss deployed sein
- Requires: PROJ-16 (DMS Scanner) — `alice-dms-scanner` muss deployed sein

## Problem Statement

Suchen nach einzelnen Transaktionen aus Kontoauszügen (z.B. „Wann gab es den letzten Zahlungsausgang an die Telekom?") schlagen fehl, obwohl die gesuchten Buchungen im System vorhanden sind. Ursache: Die aktuelle DMS-Pipeline indexiert einen Kontoauszug als **ein einziges Weaviate-Objekt** (`BankStatement`). Damit gibt es drei kombinierte Probleme:

1. **Vektor-Verwässerung**: Ein `BankStatement`-Objekt enthält 30–100 verschiedene Buchungen. Der Vektor dieses Gesamttexts ist semantisch zu generisch — die spezifische Phrase eines Kontoinhabers geht im Rauschen unter.
2. **Plaintext-Truncation**: `fullText` wird bei 10.000 Zeichen abgeschnitten (`alice-dms-processor.json`). Bei mehrseitigen ING-DiBa-Auszügen fallen hintere Seiten aus der Suche heraus.
3. **LLM-Extraktionsverlust**: Der Klassifikations-Prompt wird bei 20.000 Zeichen gekappt; qwen3:14b neigt bei langen Transaktionslisten zu unvollständiger oder leerer `transactions`-Extraktion.

## Overview

Einführung einer neuen Weaviate-Collection `BankTransaction` (1 Objekt pro Buchung). Der `alice-dms-processor` wird so erweitert, dass Transaktionen chunkweise extrahiert und einzeln indexiert werden. `alice-tool-search` und DMS-Permissions werden entsprechend erweitert.

`BankStatement` bleibt als Container für Periode, Saldo und Datei-Referenz erhalten.

## User Stories

- Als Nutzer möchte ich fragen „Wann gab es den letzten Zahlungsausgang an die Telekom?", und Alice soll die exakten Buchungsdaten (Datum, Betrag, Verwendungszweck) aus meinen Kontoauszügen nennen können, ohne falsche oder generische Ergebnisse zu liefern.
- Als Nutzer möchte ich fragen „Wie viel habe ich im letzten Jahr an Miete gezahlt?", und Alice soll alle passenden Transaktionen aggregieren können.
- Als Nutzer möchte ich Transaktionen nach Empfänger, Datum und Betrag filtern können, damit ich schnell bestimmte Zahlungen wiederfinde.
- Als System möchte ich beim Re-Processing eines Kontoauszugs bestehende `BankTransaction`-Objekte des alten Auszugs löschen und neu einfügen, damit keine Duplikate entstehen.

## Acceptance Criteria

### AC-1: Neues Weaviate-Schema `BankTransaction`

- [ ] Datei `schemas/bank-transaction.json` existiert mit Collection `BankTransaction`
- [ ] Pflichtfelder: `parentStatementId` (text, filterable), `transactionDate` (date, filterable), `amount` (number, filterable), `currency` (text, filterable), `direction` (text: `"credit"` | `"debit"`, filterable), `counterparty` (text, vectorized), `purpose` (text, vectorized)
- [ ] Optionale Felder: `valueDate` (date, filterable), `counterpartyIban` (text, filterable, tokenization: field), `balanceAfter` (number), `bankName` (text, filterable), `accountIban` (text, filterable, tokenization: field), `rawText` (text, nicht vektorisiert)
- [ ] Vectorizer: `text2vec-transformers` auf `counterparty` und `purpose`
- [ ] `init-weaviate-schema.sh` erstellt die Collection analog zu den bestehenden Collections
- [ ] Collection lässt sich per `curl` gegen Weaviate verifizieren

### AC-2: DMS-Processor extrahiert Transaktionen chunkweise

- [ ] Workflow `alice-dms-processor.json`: Bei `doc_type = "BankStatement"` wird ein neuer Extraktionspfad ausgeführt
- [ ] Extraktion erfolgt in **Chunks von maximal 8.000 Zeichen** (statt einem einzigen 20.000-Zeichen-Prompt), um Truncation bei langen Auszügen zu vermeiden
- [ ] Pro Chunk: ein separater Ollama-HTTP-Call mit strukturiertem Extraktionsprompt für Transaktionslisten (JSON-Array)
- [ ] Jede extrahierte Transaktion wird als eigenes `BankTransaction`-Objekt via Weaviate Batch-Insert (`POST /v1/batch/objects`) indexiert
- [ ] Das Feld `parentStatementId` enthält die `weaviate_id` des zugehörigen `BankStatement`-Objekts
- [ ] Bei Re-Processing (Hash-Kollision oder manueller Auslösung): alle `BankTransaction`-Objekte mit demselben `parentStatementId` werden gelöscht, bevor neue eingefügt werden
- [ ] `BankStatement`-Objekt selbst bleibt unverändert erhalten (Header-Daten, Periode, Saldo)
- [ ] Stats-Zähler `transactions_indexed` wird in `alice:dms:run:stats` hinzugefügt
- [ ] Bei leerer Transaktionsliste aus LLM: Warnung geloggt, `BankStatement` trotzdem korrekt indexiert

### AC-3: `alice-tool-search` unterstützt `BankTransaction`

- [ ] `BankTransaction` ist in `ALL_COLLECTIONS` aufgenommen
- [ ] `DATE_FIELDS['BankTransaction'] = 'transactionDate'`
- [ ] `AMOUNT_FIELDS['BankTransaction'] = 'amount'`
- [ ] `KEY_FIELDS_MAP['BankTransaction']` enthält: `['counterparty', 'purpose', 'direction', 'bankName', 'accountIban']`
- [ ] `DOC_TYPE_MAP` enthält Einträge für `'BankTransaction'`, `'Buchung'`, `'Transaktion'`
- [ ] Suche nach „Zahlungsausgang Telekom" liefert `BankTransaction`-Objekte als Top-Treffer (Score > 0.6)
- [ ] Where-Filter auf `direction: "credit"` funktioniert in der Such-Logik
- [ ] Score-Threshold und Limit gelten analog zu anderen Collections

### AC-4: DMS-Permissions für `BankTransaction`

- [ ] Tabelle `alice.permissions_dms` unterstützt `doc_type = 'BankTransaction'`
- [ ] Migration: Nutzer mit `BankStatement`-Permission erhalten automatisch auch `BankTransaction`-Permission (gleiche `doc_type`-Gruppe)
- [ ] `alice.check_dms_permission()` prüft `BankTransaction` korrekt
- [ ] SQL-Migration-Script liegt unter `sql/migrations/` vor

### AC-5: Re-Indexierung bestehender Kontoauszüge

- [x] Anleitung im Deployment-Abschnitt: Redis-Set-Einträge der bestehenden BankStatement-Hashes löschen, Scanner neu auslösen (siehe Tech Design → "Konkrete Re-Index-Runbook")
- [x] Alternativ: manueller n8n-Execution-Trigger des `alice-dms-processor` reicht — dokumentiert im Runbook
- [ ] Nach Re-Indexierung: mindestens eine Testanfrage „Zahlungsausgang Telekom" liefert korrekte `BankTransaction`-Treffer (LIVE-Verifikation, nach Deploy)

## Edge Cases

- **Chunk-Grenze schneidet Transaktion**: Prompt-Boundary so wählen, dass Zeilenumbrüche als Trennzeichen dienen; LLM-Prompt weist explizit darauf hin, unvollständige Transaktionen zu ignorieren
- **LLM extrahiert doppelte Transaktionen** (Chunk-Überlapp): De-Duplikation anhand von (`transactionDate`, `amount`, `counterparty`) vor dem Batch-Insert
- **Kontoauszug ohne erkennbare Transaktionen** (Sammeldokument, reines Deckblatt): `transactions_indexed = 0`, Warning-Log, kein Fehler
- **Re-Processing mit neuer Chunk-Anzahl**: Löschen aller `parentStatementId`-Objekte vor Insert schützt vor verwaisten Einträgen
- **Weaviate Batch-Insert schlägt teilweise fehl**: Fehlerhafte Objekte loggen, erfolgreiche behalten; Processor soll nicht abbrechen (analog zu bestehender Fehlerbehandlung in PROJ-19)
- **Sehr langer Auszug (> 100 Transaktionen, > 15 Seiten)**: Chunking-Logik muss mehr als 2 HTTP-Calls verarbeiten — kein Hard-Limit auf Chunk-Anzahl
- **ING-DiBa vs. andere Banken**: Extraktion muss bankunabhängig sein (Prompt-basiert, kein hardcodiertes Parsing)
- **Transaktion ohne Verwendungszweck**: `purpose = ""` oder `null` — Objekt trotzdem indexieren, Suche funktioniert weiterhin über `counterparty`

## Tech Design (Solution Architect)

### Umfang

Dieses Feature berührt **zwei n8n-Workflows**, **eine neue Weaviate-Schema-Datei**, **ein Shell-Script** und **eine SQL-Migration**. Keine neuen Container, keine nginx-Änderungen, kein Frontend-Eingriff. Alle Änderungen betreffen ausschließlich die Backend-Datenpipeline.

---

### Komponentenübersicht

```
schemas/
└── bank-transaction.json                    (NEU) Ein Objekt pro Buchung

scripts/
└── init-weaviate-schema.sh                  (GEÄNDERT) Neue Collection registrieren

sql/migrations/
└── 013-proj29-bank-transaction-permissions.sql  (NEU) BankTransaction-Berechtigung auto-vergeben
   (Sequenznummer 013 folgt dem bestehenden Schema 0XX-projXX-… — vorheriges 012 = PROJ-28)

workflows/core/
├── alice-dms-processor.json                 (GEÄNDERT) Zweiphasige BankStatement-Extraktion
└── alice-tool-search.json                   (GEÄNDERT) BankTransaction in Suche aufnehmen
```

---

### Datenmodell: `BankTransaction`

Ein Weaviate-Objekt pro einzelner Bankbuchung. Die beiden Suchfelder — `counterparty` und `purpose` — erhalten jeweils einen eigenen Embedding-Vektor. Dadurch kann eine Suchanfrage wie „Telekom" oder „Vokal Ensemble Isernhagen" die exakt passende Buchung mit hoher Treffsicherheit finden.

```
BankTransaction
├── parentStatementId  → UUID des übergeordneten BankStatement (Verknüpfung; für Löschen bei Re-Processing)
├── transactionDate    → Buchungsdatum (filterbar)
├── valueDate          → Wertstellungsdatum (filterbar, optional)
├── amount             → Betrag in Euro, immer positiv (filterbar)
├── currency           → „EUR" o.ä. (filterbar)
├── direction          → „credit" oder „debit" (filterbar; beantwortet „Eingang oder Ausgang?")
├── counterparty       → Name des Senders oder Empfängers (VEKTORISIERT — primäres Suchfeld)
├── purpose            → Verwendungszweck / Buchungstext (VEKTORISIERT — primäres Suchfeld)
├── counterpartyIban   → IBAN der Gegenseite, falls vorhanden (Exact-Match-Filter)
├── balanceAfter       → Kontostand nach dieser Buchung (optional)
├── bankName           → Bankname (filterbar, vom Parent übernommen)
├── accountIban        → Konto-IBAN (filterbar, vom Parent übernommen)
└── rawText            → Originaler Buchungstext unverändert (nicht vektorisiert; für Debugging)
```

`BankStatement` bleibt unverändert — es enthält weiterhin die Kopfdaten (Zeitraum, Salden, Bank, IBAN) und dient als „Container" für seine Buchungen.

---

### Workflow-Architektur: `alice-dms-processor` (geändert)

**Trigger:** Zeitplan (täglich 02:00 Uhr), liest aus Redis-Queue `alice:dms:plaintext`

**Aktueller BankStatement-Pfad (eine Phase):**
```
Klassifizierung → Extraktions-Prompt (BankStatement) → Ollama (20k Zeichen) → Parse Extract Result → Weaviate Payload → BankStatement einfügen
```

**Neuer BankStatement-Pfad (zwei Phasen):**

```
Klassifizierung → IF: BankStatement? ──ja──┐
                                           ▼
                              Phase A: Header-Extraktion
                              ├── Ollama-Call, nur erste 3.000 Zeichen
                              ├── Extrahiert: bankName, IBAN, accountHolder, periodFrom/To, Salden
                              └── BankStatement in Weaviate einfügen → parentStatementId merken
                                           ▼
                              Phase B: Transaktions-Chunk-Extraktion
                              ├── Plaintext in Chunks (~8.000 Zeichen, Trennung an Zeilenenden)
                              ├── Code-Node: Chunk-Loop (inline)
                              │     ├── Je Chunk → Ollama-Call (JSON-Array der Transaktionen)
                              │     └── Ergebnisse sammeln + deduplizieren nach (Datum + Betrag + Gegenseite)
                              └── BankTransaction-Objekte → Weaviate Batch-Insert
                                           ▼
                              Stats: transactions_indexed += N

           ──nein──→ bestehender Pfad für Invoice / Document / Email / etc. (unverändert)
```

**Wesentliche Designentscheidungen:**

1. **Phase A verwendet nur die ersten 3.000 Zeichen** für die Header-Extraktion. Bankname, IBAN und Zeitraum stehen immer am Anfang des Auszugs. Das ist schneller und zuverlässiger als das gesamte Dokument zu parsen.

2. **Phase B verwendet einen inline-Chunk-Loop in einem einzelnen Code-Node** (nicht `SplitInBatches`). Begründung: Der Loop muss alle Chunk-Ergebnisse gesammelt haben, bevor dedupliziert werden kann. `SplitInBatches` würde die Ergebnisse auf mehrere Workflow-Items verteilen und einen zusätzlichen Merge-Node erfordern. Der Inline-Ansatz entspricht dem bestehenden Retry-Muster, das in diesem Workflow bereits verwendet wird.

3. **Chunk-Größe: ~8.000 Zeichen, Trennung an Zeilenenden.** Eine typische ING-DiBa-Seite umfasst ~2.500 Zeichen, ein 10-seitiger Auszug ergibt also ~3–4 Chunks. Jeder Chunk passt komfortabel in Ollamas Kontextfenster, mit ausreichend Puffer für Prompt und JSON-Antwort.

4. **Kein Chunk-Überlapp.** Buchungen sind zeilenweise strukturiert, daher schneidet ein sauberer Zeilenumbruch keine einzelne Buchung durch. Deduplicaton behandelt den seltenen Grenzfall einer mehrzeiligen Buchung an der Chunk-Grenze.

5. **Deduplizierung vor dem Insert:** De-Dup anhand des Tupels `(transactionDate, amount, counterparty)`. Das schützt vor doppelten Einträgen, falls Re-Processing ausgelöst wird, bevor alte Objekte gelöscht sind.

6. **Löschen vor Wiedereinspielung bei Re-Processing:** Vor dem Phase-B-Insert werden alle `BankTransaction`-Objekte mit passendem `parentStatementId` in Weaviate abgefragt und gelöscht. Das macht Re-Processing idempotent.

7. **BankStatement wird auch bei fehlgeschlagener Transaktionsextraktion korrekt indexiert.** Die Header- und Zusammenfassungsdaten sind immer wertvoll; Fehler bei der Transaktionsindexierung werden geloggt, brechen aber die Verarbeitung des übergeordneten Dokuments nicht ab.

---

### Workflow-Architektur: `alice-tool-search` (geändert)

**Was sich ändert:** Vier Konstanten-Maps erhalten je einen neuen Eintrag für `BankTransaction`.

| Map               | Neuer Eintrag                                                                           |
| ----------------- | --------------------------------------------------------------------------------------- |
| `ALL_COLLECTIONS` | `'BankTransaction'` hinzugefügt                                                         |
| `DATE_FIELDS`     | `BankTransaction → 'transactionDate'`                                                   |
| `AMOUNT_FIELDS`   | `BankTransaction → 'amount'`                                                            |
| `KEY_FIELDS_MAP`  | `BankTransaction → ['counterparty', 'purpose', 'direction', 'bankName', 'accountIban']` |
| `DOC_TYPE_MAP`    | `'BankTransaction'`, `'Buchung'`, `'Transaktion'` hinzugefügt                           |

Die nearText-Suchlogik, der Permission-Filter und die Ergebnis-Formatierungsknoten bleiben **unverändert** — sie arbeiten bereits generisch über alle Collections hinweg.

---

### Workflow-Architektur: Re-Indexierung bestehender Kontoauszüge

Die Re-Indexierung ist ein einmaliger Betriebsschritt, kein neuer Workflow-Knoten.

**Vorgehen:** Redis-Processed-Hash-Einträge aller vorhandenen Kontoauszugs-Dateien löschen, danach einen manuellen Processor-Run auslösen. Der Processor findet die Dateien als „nicht prozessiert", extrahiert sie erneut und erstellt jetzt zusätzlich `BankTransaction`-Objekte.

Der `alice-dms-processor` unterstützt diesen Mechanismus bereits — für den Re-Index-Schritt selbst ist keine Code-Änderung erforderlich.

#### Konkrete Re-Index-Runbook (BUG-11)

Die folgenden Schritte werden auf dem Headless-Server ausgeführt (`ssh stan@ki.lan`).

**Schritt 1 — Alle BankStatement-fileHashes aus Weaviate auflesen:**

```bash
# Auf dem Server (Weaviate-Container ist intern unter weaviate:8080 erreichbar)
docker exec n8n curl -sX POST http://weaviate:8080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ Get { BankStatement(limit: 1000) { fileHash filePath } } }"}' \
  | jq -r '.data.Get.BankStatement[].fileHash' \
  | sort -u > /tmp/bankstatement-hashes.txt

wc -l /tmp/bankstatement-hashes.txt   # Plausibilitätscheck
```

**Schritt 2 — Diese Hashes aus Redis-Set `alice:dms:processed` entfernen:**

```bash
# Redis-Passwort aus n8n-Container .env beziehen
REDIS_PW=$(docker exec n8n printenv REDIS_PASSWORD)

# Hashes batchweise löschen (SREM akzeptiert mehrere Werte pro Aufruf)
while IFS= read -r h; do
  docker exec redis redis-cli -a "$REDIS_PW" --no-auth-warning \
    SREM alice:dms:processed "$h"
done < /tmp/bankstatement-hashes.txt
```

**Schritt 3 — Processor-Run manuell auslösen:**

In der n8n-UI: Workflow `alice-dms-processor` öffnen → „Execute Workflow" klicken.
Alternativ via Scanner-Trigger (`alice-dms-scanner`) — der Scanner publiziert die Dateien
erneut auf die MQTT-Queues, die Extractoren schreiben sie nach Redis, der Processor läuft
in der nächsten Schedule-Iteration (oder manuell ausgelöst).

**Schritt 4 — Verifikation:**

```bash
# BankTransaction-Count prüfen (sollte > 0 sein nach Re-Index)
docker exec n8n curl -sX POST http://weaviate:8080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ Aggregate { BankTransaction { meta { count } } } }"}'

# Testanfrage gegen alice-tool-search
docker exec n8n curl -sX POST http://weaviate:8080/v1/graphql \
  -H 'Content-Type: application/json' \
  -d '{"query":"{ Get { BankTransaction(hybrid: {query: \"Telekom Zahlungsausgang\", alpha: 0.5}, limit: 5) { counterparty purpose direction amount transactionDate _additional { score } } } }"}'
```

Der Top-Treffer sollte `direction: \"debit\"` und `counterparty` mit „Telekom" enthalten,
mit Score > 0.6 (siehe AC-3).

**Hinweis:** Das Redis-Set `alice:dms:processed` enthält **alle** Doc-Type-Hashes (nicht nach
Typ segmentiert). Daher der Umweg über GraphQL-Get: nur die BankStatement-Hashes werden
gezielt entfernt, andere Dokumente bleiben unangetastet.

---

### Berechtigungskonzept

`BankTransaction`-Objekte enthalten sensible Finanzdaten — dieselbe Vertraulichkeitsstufe wie ihr übergeordnetes `BankStatement`. Die SQL-Migration fügt automatisch eine `BankTransaction`-Berechtigungszeile für jeden Nutzer ein, der bereits eine `BankStatement`-Berechtigung mit den gleichen `can_read`/`can_write`-Flags besitzt. Eine neue Permission-Check-Funktion ist nicht erforderlich; `alice.check_dms_permission()` schlägt `doc_type` bereits generisch nach.

---

### Performance-Erwartung

| Schritt                                                     | Schätzung                                        |
| ----------------------------------------------------------- | ------------------------------------------------ |
| Phase A Header-Extraktion (1 Ollama-Call, 3.000 Zeichen)    | ~3–5s                                            |
| Phase B Chunk-Extraktion (3–5 Ollama-Calls × 8.000 Zeichen) | ~15–25s gesamt                                   |
| BankTransaction Batch-Insert (50 Objekte)                   | < 2s                                             |
| Gesamtverarbeitungszeit pro 10-seitigem Auszug              | ~20–30s                                          |
| Suchlatenz für `BankTransaction`-Anfragen                   | Unverändert (identischer Weaviate-nearText-Pfad) |

Die gestiegene Verarbeitungszeit ist akzeptabel, da der Processor nachts läuft und ein 2-Stunden-Budget hat.

---

### Keine neuen Abhängigkeiten

Alle benötigten Komponenten existieren bereits: Ollama, Weaviate Batch API, Redis, axios (in Code-Nodes über `NODE_FUNCTION_ALLOW_EXTERNAL` verfügbar).

---

## Technical Requirements

### Neue Dateien
- `schemas/bank-transaction.json` — Weaviate-Collection-Definition
- `sql/migrations/013-proj29-bank-transaction-permissions.sql` — DMS-Permissions-Migration (Sequenznummer 013 nach Konvention 0XX-projXX-…)

### Geänderte Dateien
- `scripts/init-weaviate-schema.sh` — `BankTransaction` hinzufügen
- `workflows/core/alice-dms-processor.json` — Chunk-Extraktion + BankTransaction Batch-Insert
- `workflows/core/alice-tool-search.json` — BankTransaction in Collections + Field-Maps

### Infrastruktur
- **Keine neuen Container** erforderlich
- **Keine nginx-Änderungen** erforderlich
- **Kein Frontend-Eingriff** erforderlich
- Weaviate Batch-API (`POST /v1/batch/objects`) — bereits genutzt in `alice-dms-processor`
- Chunk-Verarbeitung in n8n via `SplitInBatches`-Node oder Code-Node mit Loop

### Deploy-Reihenfolge
1. Weaviate-Schema initialisieren: `./scripts/init-weaviate-schema.sh`
2. DB-Migration ausführen: `013-proj29-bank-transaction-permissions.sql`
3. n8n Workflow `alice-dms-processor` deployen
4. n8n Workflow `alice-tool-search` deployen
5. Re-Indexierung bestehender Kontoauszüge auslösen (Redis-Hashes löschen + Scanner-Run)
6. Testanfrage validieren

### Performance-Erwartung
- Pro 10-seitigem Kontoauszug: ca. 3–5 Chunk-Calls an Ollama (je 8.000 Zeichen), ~15–25s Extraktion
- Batch-Insert von 50 Transaktionen: < 2s gegen Weaviate
- Such-Latenz für `BankTransaction`: keine Änderung (identische Weaviate-Query-Logik)

---

## QA Test Results

**QA Date:** 2026-05-07
**Tested By:** QA Engineer (Red Team)
**Test Method:** Static code review of all PROJ-29 deliverables (workflows, schema, SQL migration, scripts). Live execution against Weaviate / n8n was not performed — workflow is currently `active: false` in `alice-dms-processor.json` and has not been deployed yet, so all findings are derived from code/config inspection.

### Acceptance Criteria Results

#### AC-1: Neues Weaviate-Schema `BankTransaction`

| Criterion                                                                                                            | Status          | Notes                                                                                         |
| -------------------------------------------------------------------------------------------------------------------- | --------------- | --------------------------------------------------------------------------------------------- |
| `schemas/bank-transaction.json` exists with class `BankTransaction`                                                  | PASS            | File present, class set correctly                                                             |
| Required fields `parentStatementId`, `transactionDate`, `amount`, `currency`, `direction`, `counterparty`, `purpose` | PASS            | All present with correct dataType / filterable flags                                          |
| Optional fields `valueDate`, `counterpartyIban`, `balanceAfter`, `bankName`, `accountIban`, `rawText`                | PASS            | All present; `counterpartyIban` and `accountIban` use `tokenization: "field"` for exact-match |
| Vectorizer `text2vec-transformers` on `counterparty` + `purpose`                                                     | PASS            | Other fields explicitly skipped via `moduleConfig.text2vec-transformers.skip = true`          |
| `init-weaviate-schema.sh` registers the collection                                                                   | PASS            | Entry `"bank-transaction.json"` added to `SCHEMAS` array (and to `init-weaviate-schema.py`)   |
| Collection verifiable via `curl`                                                                                     | NOT TESTED LIVE | Schema syntactically valid; cannot confirm Weaviate accepts it without deployment. Risk: low  |
| **AC-1 verdict**                                                                                                     | PARTIAL PASS    | See BUG-1, BUG-2 below                                                                        |

#### AC-2: DMS-Processor extrahiert Transaktionen chunkweise

| Criterion                                             | Status              | Notes                                                                                                                       |
| ----------------------------------------------------- | ------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| BankStatement triggers new extraction path            | PASS                | New `Code: BankTransaction Phase B` node runs only when `_document_type === 'BankStatement'` and parent insert succeeded    |
| Chunks of max 8.000 chars                             | PASS                | `CHUNK_SIZE = 8000`, `splitChunks` snaps to last newline within window                                                      |
| Per-chunk Ollama call with structured JSON prompt     | PASS                | Loop over chunks, `format: 'json'`, returns `{transactions: [...]}`                                                         |
| BankTransaction objects via `/v1/batch/objects`       | PASS                | Single batch insert per parent statement                                                                                    |
| `parentStatementId` set to `weaviate_id` of parent    | PASS                | `parentId = item._new_weaviate_id` propagated through `Code: Redis State Update`                                            |
| Re-processing deletes existing children before insert | PASS (with caveats) | `axios.delete /v1/batch/objects` invoked before insert. See BUG-3 — actual idempotency depends on Weaviate version behavior |
| BankStatement object preserved                        | PASS                | Header path unchanged (Phase A)                                                                                             |
| `transactions_indexed` stat counter                   | PASS                | Initialized to `'0'` in `Code: Init`, incremented in Phase B, included in both Final Log nodes                              |
| Empty-list warning + no failure                       | PASS                | `console.warn`, returns passthrough item with `_transactions_indexed: 0`                                                    |
| **AC-2 verdict**                                      | PARTIAL PASS        | See BUG-3, BUG-4, BUG-5, BUG-6, BUG-7, BUG-8                                                                                |

#### AC-3: `alice-tool-search` unterstützt `BankTransaction`

| Criterion                                                                                                 | Status          | Notes                                                                                                                                                                                       |
| --------------------------------------------------------------------------------------------------------- | --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `BankTransaction` in `ALL_COLLECTIONS`                                                                    | PASS            | Added in both `Input Normalizer` and `Apply DMS Filter`                                                                                                                                     |
| `DATE_FIELDS['BankTransaction'] = 'transactionDate'`                                                      | PASS            | Confirmed in `Weaviate Search` node                                                                                                                                                         |
| `AMOUNT_FIELDS['BankTransaction'] = 'amount'`                                                             | PASS            | Confirmed                                                                                                                                                                                   |
| `KEY_FIELDS_MAP['BankTransaction'] = ['counterparty', 'purpose', 'direction', 'bankName', 'accountIban']` | PASS            | Confirmed                                                                                                                                                                                   |
| `DOC_TYPE_MAP` contains `BankTransaction`, `Buchung`, `Transaktion`                                       | PASS            | Confirmed in `Input Normalizer`                                                                                                                                                             |
| Search "Zahlungsausgang Telekom" returns `BankTransaction` top hit                                        | NOT TESTED LIVE | Cannot test without indexed data                                                                                                                                                            |
| Where-filter on `direction: "credit"`                                                                     | NOT IMPLEMENTED | See BUG-9 — the AC explicitly requires direction filter support, but no UI / parameter / GraphQL where-clause was added for it. Only `dateFrom`/`dateTo` filters exist in `Weaviate Search` |
| Score threshold and limit consistent                                                                      | PASS            | Same `score < 0.01` cutoff, same `limit` slicing applied                                                                                                                                    |
| **AC-3 verdict**                                                                                          | PARTIAL PASS    | See BUG-9                                                                                                                                                                                   |

#### AC-4: DMS-Permissions für `BankTransaction`

| Criterion                                               | Status | Notes                                                                     |
| ------------------------------------------------------- | ------ | ------------------------------------------------------------------------- |
| `permissions_dms.doc_type` accepts `'BankTransaction'`  | PASS   | CHECK constraint replaced in migration                                    |
| BankStatement permission auto-clones to BankTransaction | PASS   | INSERT...SELECT with idempotent NOT EXISTS guard                          |
| `check_dms_permission()` works for BankTransaction      | PASS   | Function is generic (`WHERE doc_type = p_doc_type`); no change required   |
| SQL migration in `sql/migrations/`                      | PASS   | File `013-proj29-bank-transaction-permissions.sql` present and idempotent |
| **AC-4 verdict**                                        | PASS   | See BUG-10 (file naming inconsistency, low severity)                      |

#### AC-5: Re-Indexierung bestehender Kontoauszüge

| Criterion                                                         | Status                 | Notes                                                                                                                                                                      |
| ----------------------------------------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Documented procedure for redis-hash deletion + scanner re-trigger | NOT DOCUMENTED IN SPEC | The Tech-Design section mentions the approach in prose, but the spec has no concrete commands / steps a human can execute. No script, no runbook block in the feature spec |
| Alternative: one-shot script / n8n execution                      | NOT IMPLEMENTED        | No script provided                                                                                                                                                         |
| Test query "Zahlungsausgang Telekom" validation after re-index    | NOT TESTED             | Cannot confirm without live deployment                                                                                                                                     |
| **AC-5 verdict**                                                  | FAIL                   | See BUG-11                                                                                                                                                                 |

---

### Bugs Found

#### BUG-1 (HIGH): SQL migration file numbering does not match feature spec
- **Severity:** Low (operational), but explicitly violates the spec
- **Location:** `sql/migrations/013-proj29-bank-transaction-permissions.sql`
- **Spec demands:** Filename `029-bank-transaction-permissions.sql` (Tech Design line 109 + Technical Requirements line 248)
- **Actual:** `013-proj29-bank-transaction-permissions.sql`
- **Impact:** Spec/code drift — anyone following the spec will not find the file. Migration registry consistency at risk if other devs assume the spec is the source of truth.
- **Repro:** `ls sql/migrations/ | grep proj29`
- **Recommendation:** Either update the spec to use the sequential numbering (`013-…`) consistent with the rest of `sql/migrations/`, or rename the file to match the spec. Either way, align the spec and the file.

#### BUG-2 (MEDIUM): Schema field `purpose` is not filterable
- **Severity:** Medium
- **Location:** `schemas/bank-transaction.json` line 105–108
- **AC reference:** AC-1 states `purpose` should be vectorized. The spec does not mandate filterable, but the data model (line 132–137) describes both `counterparty` and `purpose` as primary search fields; for any future "filter by purpose containing X" use-case (e.g. exact-match Telekom-Festnetz vs. Telekom-Mobil) `indexFilterable=false` blocks it.
- **Impact:** Cannot use `where: { path: ["purpose"], operator: Like, … }` filters; only hybrid/nearText vector search works on this field. Acceptable for the announced use-cases, but inconsistent with `counterparty` which IS filterable.
- **Recommendation:** Set `indexFilterable: true` on `purpose` for consistency with `counterparty`, unless intentional storage-saving decision (then document in spec).

#### BUG-3 (HIGH): Phase B `delete-by-where` API call format may be incorrect for Weaviate v1
- **Severity:** High (silent idempotency failure → duplicate transactions on re-processing)
- **Location:** `alice-dms-processor.json` → `Code: BankTransaction Phase B`, lines 49–66 of the JS code
- **Issue:** The code calls `DELETE /v1/batch/objects` with body
  ```json
  { "match": { "class": "BankTransaction", "where": {…} }, "output": "minimal", "dryRun": false }
  ```
  The Weaviate REST batch-delete actually expects either `valueText` or, for newer versions, `valueString`. The schema declares `parentStatementId` as `text` with `tokenization: "field"`. Using `valueText` is correct for `text` types but the response shape expected (`delResp.data?.results?.matches`) only matches the `verbose` output mode — code uses `output: "minimal"`. Also, `axios.delete` with a body sometimes gets stripped by HTTP libraries / proxies / Weaviate proxies — the request body is not sent on `DELETE` per RFC and many clients drop it.
- **Impact:** If the body is dropped, the call effectively becomes `DELETE /v1/batch/objects` with no filter → error. If the call silently fails (caught in `try/catch` with `console.warn`), Phase B continues with the insert → DUPLICATE transactions every re-index, despite the dedup-by-(date, amount, counterparty) being intra-run only.
- **Repro (after deploy):**
  1. Deploy processor, run once with one bank statement that produces 30 transactions.
  2. Verify 30 BankTransaction objects in Weaviate.
  3. Manually re-trigger by `SREM alice:dms:processed <hash>` and re-running.
  4. Verify count: should still be 30 (idempotent). Likely will be 60 if the delete-by-where silently fails.
- **Recommendation:**
  - Verify with the actual Weaviate version (v1.24+ uses `valueText`, `output: "verbose"` to get `matches` count).
  - Add explicit log of the delete response status code to confirm in production logs.
  - Consider falling back to a GraphQL-Get-then-DELETE-by-ID loop as a more reliable alternative.

#### BUG-4 (MEDIUM): No retry on Phase B per-chunk Ollama failure
- **Severity:** Medium
- **Location:** `Code: BankTransaction Phase B`, the per-chunk loop
- **Issue:** Phase A (BankStatement classification + extraction) has explicit retry logic (`Code: Parse Classify Result`, `Code: Parse Extract Result`) — one retry on failed JSON parse. Phase B has NO retry: a single Ollama timeout / parse failure on chunk N silently drops all transactions in that chunk and continues. The console.warn is the only signal.
- **Impact:** A 10-page bank statement that has a single chunk fail loses ~25% of its transactions silently. The `transactions_indexed` stat is correct, but the user has no signal of the partial loss.
- **Recommendation:** Add at least one retry per chunk (mirroring Phase A pattern). Optionally publish an MQTT warning topic on partial-chunk failure.

#### BUG-5 (MEDIUM): `transactionDate` may be missing → object still indexed
- **Severity:** Medium
- **Location:** `Code: BankTransaction Phase B`, build-objects step
- **Issue:** The acceptance criteria mark `transactionDate` as required (AC-1, mandatory date field). However, the build step uses `Object.fromEntries(...).filter(([_, v]) => v !== null && v !== undefined)` to drop null fields — so if `toISODate(tx.transactionDate)` returns `null` (which the prompt explicitly allows when only DD.MM. without year context), the field is OMITTED from the insert, and the object is still inserted into the BankTransaction collection with no `transactionDate` at all.
- **Impact:** Transactions without a valid date pollute the collection and break `dateFrom`/`dateTo` filters in `alice-tool-search`. They will appear in semantic search results with `date: null`.
- **Recommendation:** Skip the entire transaction (do not insert) when `transactionDate` resolves to `null`. Alternatively, log a warning and use `parentStatementId`'s parent statement period as a fallback.

#### BUG-6 (LOW): Phase B does not handle `purpose === null` per spec edge case
- **Severity:** Low
- **Location:** `Code: BankTransaction Phase B`, build-objects step, line `purpose: (tx.purpose || '').toString()`
- **Issue:** Spec edge-case: "Transaktion ohne Verwendungszweck: `purpose = ""` oder `null` — Objekt trotzdem indexieren". The code coerces null to empty string `""`, which is then NOT filtered out by the null-drop filter — so `purpose: ""` IS sent to Weaviate. This may or may not be desired: an empty string vector embedding has no semantic content and may slightly bias vector results. Consistent behavior (drop the field if empty) is arguably better.
- **Impact:** Minor — vector index quality. Not a blocker.
- **Recommendation:** Either drop the field when empty, or document that empty-string purpose is intended.

#### BUG-7 (HIGH): `alice-dms-processor.json` workflow is `active: false`
- **Severity:** High (operational blocker)
- **Location:** `workflows/core/alice-dms-processor.json` line 1154: `"active": false`
- **Issue:** The workflow JSON shipped in the PROJ-29 changeset has `active: false`. After the user deploys this workflow, Phase B will not run on the schedule unless explicitly re-activated.
- **Impact:** No new BankStatement gets BankTransaction children until someone re-enables the workflow.
- **Recommendation:** Either set `active: true` in the JSON, or document explicitly in the deploy instructions that the user must re-activate the workflow after import.

#### BUG-8 (MEDIUM): `MQTT: Publish Error (Weaviate)` skips Phase B on parent-insert failure (correct), but on insert-success-then-Phase-B-failure there is no error topic
- **Severity:** Medium
- **Location:** Workflow connections from `Code: BankTransaction Phase B` → `MQTT: Publish Done` (no error branch)
- **Issue:** Phase B catches all errors internally (delete-by-where, per-chunk Ollama, batch insert) and returns successfully. So `MQTT: Publish Done` is fired even when 0 transactions were indexed for a bank statement that has 50 booking lines. The downstream operator has no MQTT-level signal of partial / total Phase B failure.
- **Impact:** Operations team cannot discover Phase B silent failures via `alice/dms/error` subscription. Only via inspection of `transactions_indexed` stat or n8n console logs.
- **Recommendation:** When `_transactions_indexed === 0` AND `dedup.length > 0` (i.e. extraction parsed transactions but insert failed), publish to `alice/dms/error` topic. Or always publish a Phase B completion summary with success/fail counts.

#### BUG-9 (HIGH): Direction filter (`direction: "credit"`) not implemented in `alice-tool-search`
- **Severity:** High (acceptance criterion failure)
- **Location:** `alice-tool-search.json` → `Weaviate Search` node, `buildGraphQL()` function
- **AC reference:** AC-3 explicitly states: "Where-Filter auf `direction: \"credit\"` funktioniert in der Such-Logik"
- **Issue:** The `buildGraphQL` function only constructs `where` clauses for `dateField` (date range). There is NO parameter passed from `Input Normalizer` for `direction`, no schema entry in `Apply DMS Filter`, and no GraphQL `where` operand for direction.
- **Impact:** A user asking "Wann gab es den letzten Zahlungsausgang an die Telekom?" is meant to be answerable with `direction: "debit"` filter. Currently the LLM tool description in `alice-chat-handler` does not even expose a `direction` parameter, and the underlying tool ignores it. The AC is not met.
- **Repro:** Inspect the `workflowInputs.value` in `alice-chat-handler.json` line 615–625 — no `direction` field. Inspect `Input Normalizer` line 19 of `alice-tool-search.json` — no `direction` extraction.
- **Recommendation:** Either (a) explicitly mark this AC as out-of-scope for the initial release and rely on hybrid search to surface direction-relevant results; or (b) add the parameter end-to-end: chat-handler tool → Input Normalizer → Weaviate Search GraphQL where clause.

#### BUG-10 (LOW): SQL migration filename inconsistent with spec naming convention
- **Severity:** Low
- **Location:** `sql/migrations/013-proj29-bank-transaction-permissions.sql`
- **Note:** Other PROJ-XX migrations follow the pattern `0XX-projXX-…` (e.g. `010-proj19-…`, `011-proj26-…`, `012-proj28-…`). This one follows the same pattern as `013-proj29-`, so it IS consistent with neighbours, but the spec under "Tech Design" says `029-bank-transaction-permissions.sql`. See BUG-1 — they're the same root issue.
- **Recommendation:** Update the spec to reflect the actual sequential migration numbering pattern (013).

#### BUG-11 (HIGH): AC-5 — Re-indexing procedure not documented in the spec
- **Severity:** High (acceptance criterion failure)
- **Location:** Feature spec
- **AC reference:** AC-5: "Anleitung im Deployment-Abschnitt: Redis-Set-Einträge der bestehenden BankStatement-Hashes löschen, Scanner neu auslösen"
- **Issue:** The Tech Design narrates the approach but does not provide:
  - Concrete `redis-cli` commands
  - Concrete way to identify "all BankStatement hashes" (since the hashes are stored in `alice:dms:processed` which is a global Set — not segmented per doc type)
  - Concrete trigger for the scanner re-run (manual workflow trigger? cron override?)
- **Impact:** Operator cannot self-serve the re-indexing without re-deriving the procedure from the n8n workflow internals.
- **Recommendation:** Add a "Re-Index Existing Bank Statements" runbook section to the spec with explicit commands, e.g.
  
  ```bash
  # Dry-run: list all BankStatement file_hashes
  docker exec weaviate curl -sX POST http://localhost:8080/v1/graphql \
    -H 'Content-Type: application/json' \
    -d '{"query":"{ Get { BankStatement { fileHash } } }"}' \
    | jq -r '.data.Get.BankStatement[].fileHash'
  # Remove these from alice:dms:processed
  # Trigger alice-dms-scanner workflow (or its rebuild path)
  ```

#### BUG-12 (MEDIUM): No live deployment verification possible
- **Severity:** Medium (process)
- **Location:** Feature spec
- **Issue:** The acceptance criteria require live verification of:
  - Weaviate `BankTransaction` collection creation
  - Search returning Top-Hit with score > 0.6
  - Re-Index test query
  None of these have been validated against live infrastructure — the feature spec contains no test execution log, no example curl + response, no n8n execution screenshot.
- **Recommendation:** Once the workflow is deployed (with BUG-7 fixed) and a test bank statement has been processed, attach example commands + responses to the spec under a "Live Deployment Validation" section.

---

### Security Audit (Red Team)

#### S-1 (PASS): GraphQL injection in Weaviate Search
- The `buildGraphQL` function in `alice-tool-search` properly escapes the `query` string (`replace(/\\/g, '\\\\').replace(/"/g, '\\"')` etc.). `BankTransaction` collection name is never user-supplied — it comes from the hardcoded `ALL_COLLECTIONS` allowlist. **No injection vector.**

#### S-2 (PASS): `parentStatementId` as filter target — no injection
- `parentStatementId` is generated by Weaviate (a UUID), never user-supplied. The `delete-by-where` clause uses `valueText: parentId` where `parentId = item._new_weaviate_id` set in `Code: Redis State Update`. **Not user-controllable.**

#### S-3 (PASS): Permission enforcement on BankTransaction
- The migration auto-grants BankTransaction permission ONLY to users who already have a BankStatement permission row, with the SAME flags. This correctly mirrors the data sensitivity. The wildcard `'*'` permission also covers BankTransaction via the unchanged `check_dms_permission()` function.
- **Risk:** A user without BankStatement permission has NO BankTransaction permission. Wildcard users have it transitively. The role_template UPDATE is idempotent. **Permission boundary is correctly enforced.**

#### S-4 (PASS): Tool-search filter applies before Weaviate query
- `Apply DMS Filter` strips `BankTransaction` from `collections[]` if the user is not allowed → `Weaviate Search` never queries BankTransaction → no data leaks. Verified in code path.

#### S-5 (CRITICAL): Hardcoded Redis password in untracked script
- **Location:** `scripts/del_alice_dms_plaintext.py` lines 5, 38, 41
- **Issue:** Hardcoded Redis password `'yk9TtUNE5ajBJuSruf3eAw=='` in plaintext.
- **Mitigations in place:**
  - File is NOT tracked by git (`git ls-files` shows it is not in the index → currently shown as untracked in `git status`)
  - File lives only on the developer's local filesystem
- **Risk:**
  - HIGH if this file is ever staged / committed → password leaks into git history
  - HIGH if this is a SHARED workstation
- **Recommendation:**
  - Add to `.gitignore` explicitly (`scripts/del_alice_dms_plaintext.py`) or move it to a secrets-managed location
  - Refactor to read `REDIS_PASSWORD` from env var, mirroring the pattern in the n8n workflow nodes
  - **DO NOT commit this file to the repo**
- **Note:** This is unrelated to PROJ-29 itself but was discovered during this audit and should be flagged.

#### S-6 (PASS): User-supplied `query` does not reach delete-by-where
- The Phase B delete uses only the internally-generated UUID, not any user-controlled string. **No issue.**

#### S-7 (LOW): Phase B logs may leak sensitive data
- `console.log` and `console.warn` in `Code: BankTransaction Phase B` can log:
  - `parentId` (UUID, low sensitivity)
  - `item.file_path` (could contain account holder name if folder structure encodes it)
  - Per-chunk transaction counts (no PII)
- Logs are visible in n8n UI to users with workflow access (admin-only).
- **Risk:** Acceptable for admin-only UI access, but if execution log retention is shared via Grafana/Loki, evaluate redaction.
- **Recommendation:** None blocking.

#### S-8 (PASS): No new authentication surface introduced
- PROJ-29 does not add new webhooks, API endpoints, or external triggers. All paths reuse the existing `alice-dms-processor` (schedule-only, no HTTP) and `alice-tool-search` (executeWorkflowTrigger, called only from `alice-chat-handler` which already enforces JWT). **No new attack surface.**

---

### Regression Risk Assessment

#### R-1: Existing BankStatement search still works — PASS
- BankStatement search is unaffected: same fields, same vectorizer, same `KEY_FIELDS_MAP` entry. Only the parent-doc-type extraction prompt was preserved.

#### R-2: PROJ-19 (DMS Processor classification) — PASS
- Phase A is unchanged. The new Phase B node is appended after `IF: Insert Success` for the "true" branch, fully passthrough for non-BankStatement docs. Invoice / Document / Email / Contract / SecuritySettlement paths are untouched.

#### R-3: PROJ-20 (alice-tool-search) — PASS
- All five const maps gained one entry; nothing was renamed or removed. Other collections continue to behave identically.

#### R-4: PROJ-24 (DMS Stats / Run-Stats reliability) — PASS
- New stat counter `transactions_indexed` added to `Code: Init` and both Final Log nodes. Format and serialization unchanged.

#### R-5: Frontend DMS settings — PARTIAL CONCERN
- `frontend/src/components/Settings/dms-constants.ts` `SUGGESTED_TYPES` does NOT include `BankTransaction`. This is consistent: BankTransaction is auto-derived, never a folder's `suggested_type`. But if an admin opens the DMS folder settings, `BankTransaction` will not appear in dropdowns — this is correct by design (folders contain bank statements, not transactions).
- **Verdict:** No change required, but worth a comment in the spec to clarify this is intentional.

#### R-6: PROJ-21/22 (DMS Lifecycle) — UNCLEAR
- Phase B does not register BankTransaction objects in any of the lifecycle Redis sets (`alice:dms:path_to_hash`, `alice:dms:processed`). Only the parent BankStatement is registered. If a bank statement file is moved or deleted, the lifecycle handler will delete the BankStatement object but leave the orphaned BankTransaction children in Weaviate forever (`parentStatementId` becomes a dangling reference).
- **This is a real bug, severity Medium-High.** Tracking under: BUG-13.

#### BUG-13 (HIGH): BankTransaction children orphaned on parent BankStatement deletion via lifecycle
- **Severity:** High
- **Location:** Interaction between `alice-dms-lifecycle` (PROJ-22) and the new BankTransaction objects.
- **Issue:** The lifecycle workflow is not aware of BankTransaction. When a bank statement file is moved out of the DMS or its hash changes (file edited), lifecycle deletes the BankStatement Weaviate object but leaves all BankTransaction children behind.
- **Impact:**
  - Storage: orphans accumulate indefinitely
  - Search: orphan transactions still appear in `BankTransaction` searches with a now-invalid `parentStatementId`
  - Permissions: orphaned objects are still readable to users with BankTransaction permission, even if the source statement is gone
- **Repro (after deploy):**
  1. Process a bank statement → BankStatement + N BankTransaction children
  2. Delete the source PDF from the watched folder
  3. Wait for lifecycle to fire
  4. Query `Aggregate { BankTransaction { meta { count } } }` — count remains N, not 0
- **Recommendation:** Either
  - Add a Phase-C cleanup step to `alice-dms-lifecycle` that, on BankStatement deletion, performs `DELETE /v1/batch/objects` with `where parentStatementId Equal <deletedId>`
  - Or: explicitly document the limitation in PROJ-29 and create a follow-up feature

---

### Summary

| Metric                            | Value                                                      |
| --------------------------------- | ---------------------------------------------------------- |
| Total ACs tested                  | 5                                                          |
| ACs PASS                          | 1 (AC-4)                                                   |
| ACs PARTIAL PASS                  | 3 (AC-1, AC-2, AC-3)                                       |
| ACs FAIL                          | 1 (AC-5)                                                   |
| Bugs Critical                     | 0                                                          |
| Bugs High                         | 4 (BUG-3, BUG-7, BUG-9, BUG-11, BUG-13)                    |
| Bugs Medium                       | 4 (BUG-2, BUG-4, BUG-5, BUG-8, BUG-12)                     |
| Bugs Low                          | 3 (BUG-1, BUG-6, BUG-10)                                   |
| Security Critical                 | 1 (S-5 — pre-existing, unrelated to PROJ-29)               |
| Security findings (PROJ-29 scope) | 0                                                          |
| Regression Risk                   | Low for PROJ-19/20/24, MEDIUM-HIGH for PROJ-21/22 (BUG-13) |

### Production-Ready Decision: NOT READY

**Blocking issues that MUST be fixed before deployment:**

1. **BUG-7** — Workflow `active: false` (deploy will not run the scheduled processor)
2. **BUG-9** — AC-3 direction filter not implemented (decide: drop AC or implement)
3. **BUG-11** — AC-5 re-index procedure not documented (deployment runbook gap)
4. **BUG-13** — Lifecycle orphans BankTransaction children (data integrity issue under normal operation)
5. **BUG-3** — Phase B delete-by-where API call needs live verification (idempotency)

**Should-fix before deployment (medium severity):**
6. **BUG-5** — Transactions with null `transactionDate` still inserted (pollutes search)
7. **BUG-4** — Phase B per-chunk failure has no retry (silent partial loss)
8. **BUG-8** — Phase B silent failures no MQTT signal (observability)
9. **BUG-1 / BUG-10** — Spec/file name alignment (documentation)

**Out-of-scope but flagged:**
- **S-5** — Hardcoded Redis password in untracked script `scripts/del_alice_dms_plaintext.py` (pre-existing, not part of PROJ-29 changes, but discovered)
