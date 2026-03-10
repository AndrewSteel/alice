# PROJ-18: DMS Document Search Tool (alice-tool-search)

## Status: Planned
**Created:** 2026-03-09
**Last Updated:** 2026-03-09

## Dependencies
- Requires: PROJ-17 (DMS Processor) — Weaviate muss mit Dokumenten befüllt sein
- Requires: PROJ-3 (HA-First Chat Handler) — alice-chat-handler muss den Sub-Workflow aufrufen können

## Overview

Implementierung des `alice-tool-search` n8n Sub-Workflows sowie Integration als Tool im `alice-chat-handler`. Der Workflow nimmt eine semantische Suchanfrage (+ optionale Filter) entgegen, führt eine Weaviate nearText-Suche über alle DMS-Collections durch und gibt formatierte Ergebnisse zurück, die der Chat-Handler als Tool-Response an Qwen2.5 weitergibt.

## User Stories

- Als Alice (Chat-Handler) möchte ich Dokumente semantisch durchsuchen können, damit ich Nutzerfragen wie "Zeig mir Rechnungen von 2025" oder "Was habe ich für Versicherungen ausgegeben?" korrekt beantworten kann.
- Als Nutzer möchte ich nach Dokumenten filtern können (Typ, Zeitraum), damit ich bei vielen Dokumenten schnell die relevanten finde.
- Als Nutzer möchte ich bei Suchergebnissen eine kurze Zusammenfassung des Inhalts sehen, damit ich ohne das Original-Dokument zu öffnen erkennen kann, ob es relevant ist.
- Als Nutzer möchte ich Details zu einem spezifischen Dokument abrufen können (per Weaviate-UUID), damit ich vollständige Metadaten und den Volltext einsehen kann.
- Als Admin möchte ich, dass der Search-Workflow als n8n Execute-Workflow-Trigger implementiert ist, damit er direkt vom alice-chat-handler aufgerufen werden kann.

## Acceptance Criteria

- [ ] n8n Sub-Workflow `alice-tool-search` existiert mit Execute-Workflow-Trigger
- [ ] Workflow akzeptiert Input: `{ query: string, doc_type?: string, date_from?: string, date_to?: string, limit?: number }`
- [ ] Standard-Suchmodus: nearText-Suche über alle DMS-Collections (Rechnung, Kontoauszug, Dokument, Email, WertpapierAbrechnung, Vertrag)
- [ ] Wenn `doc_type` angegeben: Suche nur in der entsprechenden Collection
- [ ] Wenn `date_from` / `date_to` angegeben: Weaviate where-Filter auf Datumfeld der jeweiligen Collection
- [ ] `limit` Default: 5, Maximum: 20
- [ ] Rückgabe: Array von Ergebnis-Objekten mit `{ weaviate_id, collection, score, title_or_summary, date, amount?, key_fields }`
- [ ] Zweite Funktion: `get_document_details` — gibt alle Felder eines Dokuments per UUID zurück
- [ ] `alice-chat-handler` Workflow enthält beide Tools (`search_documents`, `get_document_details`) im Tool-Definitions-System-Prompt
- [ ] `alice-chat-handler` kann `alice-tool-search` per n8n Execute-Workflow aufrufen und das Ergebnis als Tool-Response an das LLM zurückgeben
- [ ] Bei leerer Suchanfrage oder 0 Ergebnissen: leeres Array zurückgeben (kein Fehler)
- [ ] Bei Weaviate-Fehler: leeres Array + Fehler-Flag zurückgeben (damit Chat-Handler graceful degradiert)

## Tool Definitions (für System-Prompt in alice-chat-handler)

```json
{
  "name": "search_documents",
  "description": "Durchsucht das Dokumentenarchiv semantisch. Nutze dieses Tool für Fragen zu Rechnungen, Kontoauszügen, Verträgen, E-Mails oder Wertpapierabrechnungen.",
  "parameters": {
    "query": "Suchbegriff oder Frage auf Deutsch",
    "doc_type": "Rechnung | Kontoauszug | Dokument | Email | WertpapierAbrechnung | Vertrag | alle (optional, default: alle)",
    "date_from": "YYYY-MM-DD (optional)",
    "date_to": "YYYY-MM-DD (optional)",
    "limit": "Anzahl Ergebnisse 1-20 (optional, default: 5)"
  }
}
```

```json
{
  "name": "get_document_details",
  "description": "Ruft alle Details zu einem spezifischen Dokument aus dem Archiv ab. Nutze die weaviate_id aus einem vorherigen search_documents Ergebnis.",
  "parameters": {
    "weaviate_id": "UUID des Dokuments aus vorherigem search_documents Aufruf",
    "collection": "Weaviate-Collection-Name (aus search_documents Ergebnis)"
  }
}
```

## Edge Cases

- **Suchanfrage auf Englisch**: Weaviate nearText funktioniert auch mit englischen Begriffen (multilingual model). Kein Problem.
- **`doc_type` ist nicht in der gültigen Liste**: Wird ignoriert, Suche über alle Collections.
- **`date_from` nach `date_to`**: Werden vertauscht (date_from = Min, date_to = Max).
- **`weaviate_id` existiert nicht**: HTTP 404 von Weaviate → leeres Objekt zurückgeben + Log.
- **Weaviate-Collection leer (noch keine Dokumente)**: nearText-Suche gibt leeres Array zurück — kein Fehler.
- **Sehr spezifische Suche ohne Treffer**: Leeres Array. Alice antwortet dem Nutzer, dass keine Dokumente gefunden wurden.
- **`limit` > 20**: Wird auf 20 gekappt.
- **Score-Schwelle**: Ergebnisse mit Weaviate-Distanz > 0.8 (cosine) werden herausgefiltert.
- **alice-chat-handler ruft Tool auf, Weaviate ist offline**: `{ results: [], error: "Weaviate nicht erreichbar" }`. Chat-Handler gibt Nutzer eine Fehlermeldung.

## Technical Requirements

- **Trigger**: n8n Execute Workflow Trigger (kein Webhook)
- **Weaviate-Suche**: nearText mit optionalem where-Filter, via HTTP-Request oder Weaviate-Node
- **Multi-Collection-Suche**: Parallele Suche in allen 6 Collections, Ergebnisse nach Score sortiert
- **Score-Filter**: Distance-Schwelle 0.8 (cosine)
- **Result-Format pro Treffer**:
  ```json
  {
    "weaviate_id": "uuid",
    "collection": "Rechnung",
    "score": 0.23,
    "title_or_summary": "Rechnung Stadtwerke München – 2025-01-15",
    "date": "2025-01-15",
    "amount": 89.50,
    "key_fields": { "absender": "Stadtwerke München", "gesamtbetrag": 89.50 }
  }
  ```
- **Chat-Handler Integration**: `alice-chat-handler` Workflow muss um Tool-Dispatch für `search_documents` und `get_document_details` erweitert werden
- **n8n Credentials**: Weaviate (HTTP-Request)
- **Workflow-Datei**: `workflows/core/alice-tool-search.json`

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
