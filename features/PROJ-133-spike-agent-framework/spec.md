# PROJ-133: Spike Agent-Framework

**Erstellt:** 2026-11-24
**Phase:** 4.4

<!-- Der Status steht nur in features/INDEX.md. Diese Datei schreibt nur der Mensch (/write-spec, /refine). -->

> **Entwurf — noch nicht bereit für die Factory.** Interview am 2026-11-24 begonnen und bewusst unterbrochen: Der Spike startet erst, wenn PROJ-128 und PROJ-132 (die produktiven Tools) gebaut sind. Diese Spec hält die bisherigen Entscheidungen als Grundlage fest. Vor der Übergabe mit `/refine PROJ-133` die offenen Fragen klären und die Akzeptanzkriterien vervollständigen.

## Abhängigkeiten
- Benötigt: PROJ-128 (Such-Tools als Service) — Dokument-, Mail- und Bildsuche, mit denen die Prototypen arbeiten
- Benötigt: PROJ-132 (Wiki-Tool für den Agenten) — Wiki lesen, suchen, Links folgen
- Liefert für: PROJ-134 (Agent-Kern auf neuem Framework) — mit der Entscheidung aus diesem Spike erfolgt der Übergang von Alt zu Neu dort sofort

## Ziel
Entscheiden, auf welchem Agent-Framework der neue Agent-Kern (PROJ-134) gebaut wird — so nah an der späteren Produktivbasis wie möglich: mit den produktiven Tools und gegen das produktive LLM.

## User Stories
- Als Admin möchte ich die Agent-Framework-Kandidaten anhand fester Kriterien verglichen sehen, damit die Wahl nachvollziehbar ist und nicht auf Bauchgefühl beruht.
- Als Admin möchte ich die zwei aussichtsreichsten Kandidaten als Prototypen mit den echten Tools gegen das produktive LLM messen, damit die Entscheidung auf dem Verhalten unter Produktivbedingungen beruht.
- Als Admin möchte ich einen wiederverwendbaren DMS-Testkatalog mit Mess-Skript, damit ich die Antwortqualität jetzt und später (PROJ-134 ff.) gleich messen kann.

## Bisher entschiedener Umfang

### Stufe 1 — Papier-Bewertung
- Kandidaten: DeepSeek Harness (Favorit), Pydantic AI, LangGraph, OpenAI Agents SDK, smolagents. Lösungen auf Basis von n8n sind ausgeschlossen.
- Bewertungsmatrix gegen die Kriterien aus dem PRD: mehrschrittige Planung, Sub-Agents, Tools über MCP oder Python, SSE-Streaming zur WebApp, Sessions/Gedächtnis, Modellwahl je Aufgabe/Sub-Agent, lokaler llama.cpp über OpenAI-kompatible API hinter `alice-llm-gateway`, i18n der Ausgaben; zusätzlich Lizenz, Reifegrad und Wartungsaktivität.
- Ergebnis: Empfehlung, welche zwei Kandidaten einen Prototyp bekommen — DeepSeek Harness und die beste Alternative aus der Matrix.

### Stufe 2 — Zwei Prototypen
- Beide Prototypen setzen dasselbe Szenario um und laufen durch dasselbe Mess-Skript.
- Die Prototypen nutzen die **neuen, produktiven Tools** (PROJ-128, PROJ-132), nicht die alten Tools (`search_documents`/`get_document_details` über n8n).
- Gemessen wird gegen das **produktive LLM**, nicht gegen ein gemocktes.
- Die Factory baut Prototypen und Mess-Skript und testet deren Mechanik mit Mocks (sie darf das produktive LLM nicht ansprechen). Den eigentlichen Messlauf gegen das produktive LLM führt der Mensch nach dem Deploy aus.

### DMS-Testkatalog und Mess-Skript
- **Im Repo:** Katalogformat, Mess-Skript und ein kleiner synthetischer Beispiel-Korpus (ca. 5–8 erfundene Dokumente mit Beispielfragen), damit das Mess-Skript Ende-zu-Ende testbar ist.
- **Nur lokal, nicht im Repo:** der echte Katalog mit ~30 Fragen, Soll-Antworten und Quellen in einer gitignorierten Datei im selben Format; schreibt der Mensch.
- **Bewertung je Frage:** erwartete Kernaussage plus mindestens eine erwartete Quelle. Korrekt = Antwort enthält die Kernaussage und nennt die Quelle. Prüfung regelbasiert (Schlüsselwörter/Zahlen), kein LLM-as-Judge.
- Zielwert laut PRD (Metrik DMS-Antwortqualität): ≥ 80 % korrekt mit Quellenangabe.

## Außerhalb des Umfangs
- Prototypen für alle fünf Kandidaten (nur Papier-Bewertung)
- Messung der Prototypen mit den alten Tools oder mit gemocktem LLM als Entscheidungsgrundlage
- Migration von `alice-chat-stream` (PROJ-134)
- Cloud-Recherche (PROJ-136)
- Echte Katalogfragen oder personenbezogene Daten im Repo

## Akzeptanzkriterien
_Werden bei `/refine PROJ-133` vervollständigt. Bereits absehbar:_
- [ ] AK-1: Angenommen die fünf Kandidaten, wenn die Papier-Bewertung abgeschlossen ist, dann liegt eine Bewertungsmatrix mit allen Kriterien je Kandidat und eine begründete Auswahl von zwei Prototyp-Kandidaten vor.
- [ ] AK-2: Angenommen der synthetische Beispiel-Korpus und ein gemockter Chat-Endpunkt, wenn das Mess-Skript läuft, dann gibt es je Frage korrekt/falsch (Kernaussage und Quelle) und eine Gesamtquote aus.
- [ ] AK-3: Angenommen eine Katalogdatei außerhalb des Repos, wenn das Mess-Skript mit ihrem Pfad aufgerufen wird, dann misst es mit diesem Katalog; die Datei ist per `.gitignore` ausgeschlossen.
- [ ] AK-4: Angenommen beide Prototypen, wenn sie mit gemocktem LLM und gemockten Tools die Beispielfragen beantworten, dann rufen sie die Tools aus PROJ-128/PROJ-132 auf und liefern Antworten mit Quellenangabe, die das Mess-Skript auswerten kann.
- [ ] AK-5 (Live-Test nach Deploy, Mensch): Angenommen der echte Katalog, wenn beide Prototypen gegen das produktive LLM gemessen werden, dann liegt je Prototyp eine Quote vor, und die Go/No-Go-Entscheidung ist dokumentiert.

## Edge Cases
- EC-1: Kein Prototyp erreicht den Zielwert — siehe offene Fragen (No-Go-Folge).
- EC-2: Ein Kandidat (z. B. DeepSeek Harness, Developer Preview) bricht durch Breaking Changes zwischen Papier-Bewertung und Prototyp — Rückfall auf den nächstbesten Kandidaten der Matrix.

## Technische Anforderungen
- Lokales LLM über OpenAI-kompatible API hinter `alice-llm-gateway`
- Ggf. Node/TypeScript-Runtime, falls DeepSeek Harness einen Prototyp bekommt (`.factory/setup.json` braucht dann einen Node-Check, setzt der Mensch)

## Offene Fragen
- [ ] Ausgangswert: Wird zusätzlich das heutige System (`alice-chat-stream`, alte Tools) mit dem Katalog gemessen, als Basis der PRD-Metrik?
- [ ] Katalog-Umfang: Nur DMS-Fragen, oder auch Mail- und Wiki-Fragen, da die neuen Tools diese abdecken?
- [ ] Prototyp-Szenario: Welche PRD-Kriterien (Sub-Agents, SSE, Sessions, Modellwahl, i18n) müssen die Prototypen praktisch zeigen, welche reichen auf Papier?
- [ ] Go/No-Go-Kriterien: Schwelle (Zielwert 80 %? Abstand zwischen den Kandidaten?), weitere Kriterien wie Antwortzeit; was folgt bei No-Go für beide?
- [ ] Betrieb der Prototypen für den Messlauf: als eigener Container im Docker-Netz neben dem alten System?
- [ ] Wer entscheidet: der Mensch anhand eines Berichts der Factory?

## Product Decisions
- Testkatalog-Format, Mess-Skript und synthetischer Beispiel-Korpus im Repo; echter Katalog nur lokal (gitignoriert); regelbasierte Bewertung (Kernaussage + Quelle), kein LLM-as-Judge: Repo ist öffentlich, Factory muss das Skript testen können, Bewertung soll reproduzierbar sein (2026-11-24)
- Zweistufig: Papier-Bewertung aller Kandidaten, Prototypen für die zwei besten (DeepSeek Harness + beste Alternative): fairer Vergleich unter gleichen Bedingungen mit geprüfter Rückfalloption, ohne fünf Prototypen (2026-11-24)
- Prototypen nur mit den neuen, produktiven Tools (PROJ-128, PROJ-132): Wer mit den alten Tools am besten abschneidet, muss mit den neuen nicht am besten umgehen (2026-11-24)
- Messung gegen das produktive LLM statt gegen einen Mock: Was mit dem Mock gut ist, muss mit dem produktiven LLM nicht gut sein — so nah an der Basis wie möglich (2026-11-24)
- Spike wird nicht aufgeteilt und startet erst nach PROJ-132; dadurch entfällt die Parallelität zur ETL-Kette. Mit der Entscheidung erfolgt der Übergang Alt → Neu in PROJ-134 sofort (2026-11-24)
