# Architektur: PROJ-118 Klassifizierung + Feldextraktion (#9)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-23

## A) Betroffene Bausteine
```
alice-document-classify (neuer Container, Python/FastAPI, Port 8015, nur Docker-Netz, keine nginx-Route)
+-- Arbeitsschleife: holt fällige Arbeit der Stufe `classify` aus dem Register,
|   nur kind = document und nur, wenn `extract` erledigt ist; höchstens N Quellen gleichzeitig (Standard 1)
+-- Lebenszeichen an das Register, solange eine Quelle in Arbeit ist (Warteschlange im Gateway kann dauern)
+-- Ablauf je Quelle: Typ bestimmen → Felder/Titel/Zusammenfassung → Sprachprüfung →
|   (Kontoauszug) Buchungen abschnittsweise → Prüfungen (Saldo, IBAN/ISIN, Werte) → ein Schreibaufruf
+-- LLM nur über alice-llm-gateway mit eigenem Schlüssel (Hintergrund-Stufe)
+-- liest und schreibt ausschließlich über die Schnittstelle von alice-source-registry
+-- GET /health (healthy / warning / unhealthy mit Grund), GET /status (laufende Arbeit, Zähler)

alice-source-registry (PROJ-115, Erweiterungen der Schnittstelle, alle optional)
+-- Übernahme (claim) optional nur, wenn bestimmte Vorstufen erledigt sind („requires“: extract)
+-- Zurücksetzen je Feld: eine Stufe kann bei Änderung bestimmter Felder bzw. des Inhaltsteils
|   wieder auf `pending` gehen (classify: Inhaltsteil und `type`)
+-- `manual` feldgenau auch innerhalb von Blöcken: `fields.iban` schützt nur dieses Feld
+-- Schreiben mit Übernahme-Token: Ergebnis wird verworfen, wenn die Stufe inzwischen
    zurückgesetzt oder die Quelle gelöscht wurde

alice-llm-gateway: nur `clients.example` um den neuen Hintergrund-Aufrufer ergänzt
PostgreSQL: eine neue Spalte in alice.pipeline_stages (Migration), sonst keine Änderung
Redis, Weaviate, MQTT, nginx, Frontend, n8n: keine Änderung (alte DMS-Workflows laufen weiter)
```

Ein neuer Dienst statt Erweiterung von `alice-text-extraction`: andere Last (LLM statt CPU/OCR), eigene Parallelität (1) und ein eigener Ausfallgrund (Gateway). Die Extraktion bleibt frei von LLM-Abhängigkeiten.

## B) Datenmodell
- **Keine neuen Tabellen.** Zustand, Versuche, Fehler und Backoff liegen im Register (PROJ-115).
- **Neue Spalte `alice.pipeline_stages.resets_on_fields`** (Liste von Feldnamen, `content` = Inhaltsteil): Ändert sich eines dieser Felder (durch eine andere Stufe oder von Hand), geht die Stufe wieder auf `pending`. Vorbelegt: `classify` → `content`, `type`. Bestehende Regel `resets_on_content_change` (database/rag/wiki) bleibt unverändert.
- **Quell-Markdown** (Frontmatter, über das Register geschrieben):
  - `type`: einer von `Invoice`, `BankStatement`, `Contract`, `SecuritySettlement`, `Document`
  - `classification`: `confidence` (0–1), `uncertain` (true/false)
  - `title`: `YYYY-MM-DD hh.mm.ss <deutscher Titel>` (Zeit aus `modified`, Ortszeit; ohne gültiges `modified` aus `captured`)
  - `summary`: deutsche Zusammenfassung; `summary_language_uncertain`: true/false
  - `fields`: gemeinsame Felder (`document_date`, `sender`, `recipient`, `tags`) und die Felder des Typs laut Spec, nicht gefundene/ungültige Werte `null`. Positionen einer Rechnung: `line_items` mit `description`, `quantity`, `amount`. Buchungen: `transactions` mit `booking_date`, `value_date`, `counterparty`, `purpose`, `amount` (mit Vorzeichen).
  - Saldenprüfung bei Kontoauszügen: nur bei Abweichung `fields.balance_mismatch: true` und `fields.balance_difference` (Endsaldo minus berechneter Endsaldo). So verschwinden die Kennzeichen automatisch, wenn ein späterer Lauf aufgeht.
  - `manual`: zusätzlich Einträge der Form `<block>.<feld>` (z. B. `fields.amount_gross`).
- Der Inhaltsteil wird von PROJ-118 nie geschrieben.

## C) Abläufe
1. **Arbeit holen:** Ist ein Platz frei, fragt der Dienst das Register nach fälliger `classify`-Arbeit für `document`, deren `extract` auf `done` steht (AK-2, AK-3). Nichts zu tun → Pause (Standard 10 s, AK-6).
2. **Lesen:** Frontmatter und Inhaltsteil über das Register. Gesperrt/fehlend → Arbeit ohne Fehlversuch zurückgeben.
3. **Leeres Dokument** (`extraction.empty`, Inhaltsteil nicht von Hand gesetzt): kein LLM; `type: Document`, leere Zusammenfassung, gemeinsame Felder `null`, Titel unverändert (AK-32).
4. **Typ:**
   - `type` in `manual` → kein Klassifizierungsaufruf, Hand-Typ gilt (AK-33/34). Ist er kein bekannter Typ, endet die Stufe endgültig mit verständlichem Fehler (nach Korrektur von `type` läuft sie von selbst neu).
   - Sonst Aufruf 1 mit Temperatur 0 auf den ersten 20.000 Zeichen; Prompt nennt alle fünf Typen mit Merkmalen (AK-10). Konfidenz unter dem Schwellwert (Standard 0,7) → Aufruf 2 mit erhöhter Temperatur (Standard 0,7); übernommen wird die höhere Konfidenz, bei Gleichstand der zweite; bleibt sie darunter, `uncertain: true` (AK-7–9).
5. **Felder, Titel, Zusammenfassung:** ein Aufruf mit dem Feldsatz des Typs auf dem Dokumentanfang (bei Kontoauszügen nur Kopfdaten). Vorgabe: Titel und Zusammenfassung auf Deutsch, auch bei englischer Quelle (AK-21).
6. **Sprachprüfung ohne LLM:** Anteil englischer gegenüber deutschen Funktionswörtern in Zusammenfassung und Titel. Weniger als 6 Wörter (Eigennamen, Zahlen) gelten nie als Verdacht, einzelne englische Fachbegriffe ebenfalls nicht (AK-24). Verdacht → Schritt 5 einmal mit verschärfter Deutsch-Vorgabe; dessen Ergebnis wird übernommen; bleibt der Verdacht, `summary_language_uncertain: true` (AK-22/23).
7. **Buchungen (nur `BankStatement`):** Inhaltsteil entlang `## Seite <n>` in Abschnitte bis zur konfigurierten Größe (Standard 8.000 Zeichen) gruppiert; ohne Seitenmarken nach Größe an Zeilengrenzen geteilt. Ein Aufruf je Abschnitt, Ergebnisse in Dokumentreihenfolge. Ist die letzte Buchung eines Abschnitts gleich der ersten des nächsten (Datum, Betrag, Verwendungszweck), wird sie einmal übernommen (AK-26/27).
8. **Prüfen ohne LLM:** Werte normalisieren (Datum → `YYYY-MM-DD`, deutsche Beträge inkl. `S`/`H` → Zahl, Währung → ISO-Code), Ungültiges → `null` (AK-14, EC-5); IBAN (Modulo 97) und ISIN (Luhn) prüfen (AK-16); Saldo prüfen (AK-28–30).
9. **Titel bilden:** LLM-Titel ohne eventuell mitgelieferten Datums-Präfix (EC-8), höchstens 80 Zeichen an einer Wortgrenze (AK-18), davor die Änderungszeit des Originals (AK-17/19/20).
10. **Schreiben:** Erst wenn alle Aufrufe gelungen sind, ein Schreibaufruf mit Übernahme-Token (AK-45). Das Register schützt `manual` (auch `fields.iban`), committet vorher Hand-Änderungen (EC-9), benennt bei neuem Titel per Git um, erzeugt `classify: <id> <title>` bzw. Sammel-Commit (AK-4), setzt `database`/`rag`/`wiki` zurück. Wurde die Stufe inzwischen zurückgesetzt oder die Quelle gelöscht, verwirft das Register das Ergebnis; der Dienst gibt die Arbeit dann ohne Fehlversuch zurück (EC-15). Danach `done`.
11. **Fehler:**
    - Gateway nicht erreichbar, Zeitüberschreitung, 5xx, 429, Schlüssel abgelehnt → Arbeit ohne Fehlversuch zurück, Warnung im Log, neue Arbeit pausiert (Standard 60 s), danach weiter (AK-42). Abgelehnter Schlüssel macht `/health` „unhealthy“.
    - Ungültige Antwort (kein JSON, Typ fehlt/unbekannt, Buchungsliste fehlt) → sofort ein zweiter Versuch; scheitert er, `fail` mit Backoff (AK-43/44); bei Kontoauszügen scheitert so die ganze Quelle (AK-31). Ausnahme: der Konfidenz-Zweitversuch: ist er zweimal ungültig, gilt das gültige Ergebnis des ersten.
    - Register nicht erreichbar/Repo weg (503) oder Markdown gesperrt (409) → Arbeit ohne Fehlversuch zurück.

**Erneute Klassifizierung** (Register, PROJ-115 geändert):
- Original geändert → wie bisher (PROJ-116) alle Stufen nach `detect` auf `pending`, also auch `classify` (Entscheidung A im Issue; der zweite Halbsatz von AK-37 entfällt).
- Eine Stufe (z. B. `extract` bei „erneut versuchen“) schreibt einen geänderten Inhaltsteil → `classify` auf `pending`; derselbe Inhalt → bleibt `done`.
- Hand-Korrektur am Inhaltsteil oder an `type` → `classify` auf `pending` (AK-34/35); an anderen Feldern (z. B. `fields.amount_gross`, `summary`, `title`) nicht (AK-36).
- „Erneut versuchen“ → bestehende Funktion des Registers (AK-39).

## D) Technische Entscheidungen
- **Mehrere kleine Aufrufe statt eines großen:** Typ, dann Felder des Typs, dann Buchungen je Abschnitt. Der Feld-Prompt enthält nur den Feldsatz des erkannten Typs (keine Felder anderer Typen, AK-12) und Konfidenz-Wiederholung kostet nur den kurzen Aufruf.
- **OpenAI-kompatible Schnittstelle des Gateways** (`/v1/chat/completions`, JSON-Antwortformat), wie die übrigen Aufrufer seit PROJ-99. Denkblöcke (`<think>`) und Codezäune werden vor dem Lesen entfernt.
- **Dokumenttext als Daten:** Der Text steht abgegrenzt in der Nutzer-Nachricht mit der Vorgabe, darin enthaltene Anweisungen zu ignorieren; entspricht die Antwort nicht dem Format, ist sie ungültig (EC-11).
- **Sprachheuristik mit Funktionswörtern** wie im alten `alice-dms-language-check` (PROJ-79), aber gegen deutsche Funktionswörter abgewogen, damit Fachbegriffe keinen Fehlalarm auslösen.
- **Titel-Zeit in Ortszeit** (Standard `Europe/Berlin`, einstellbar): `modified` steht im Register in UTC; Menschen sortieren nach der Uhrzeit, die der Dateimanager zeigt.
- **Saldenkennzeichen unter `fields`:** Der Block wird bei jedem Lauf vollständig neu geschrieben, alte Kennzeichen verschwinden damit von selbst (das Register kann Felder der obersten Ebene nicht löschen).
- **Register-Erweiterungen statt Umgehungen:** Übernahme nur nach erledigter Vorstufe (sonst müsste der Dienst Arbeit übernehmen und sofort zurückgeben), Zurücksetzen je Feld als Spalte (neue Regeln ohne Codeänderung), `manual` mit Punkt-Schreibweise (Spec verlangt Schutz einzelner Felder in `fields`), Schreiben mit Token (keine veralteten Ergebnisse nach Hand-Korrektur oder Löschung). Alles optional, bestehende Aufrufer unverändert.
- **Kein Postgres, kein Redis, kein Weaviate, kein MQTT im Dienst** (AK-48).

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `httpx`; Image mit `tini`.
- Neue Umgebungsvariablen (Platzhalter in `.env.example` von `alice-document-classify`): `REGISTRY_URL`, `LLM_GATEWAY_URL`, `LLM_GATEWAY_KEY`, `CLASSIFY_MODEL`, `CLASSIFY_CONCURRENCY` (1), `CLASSIFY_POLL_SECONDS` (10), `CLASSIFY_HEARTBEAT_SECONDS` (60), `CLASSIFY_LLM_TIMEOUT_SECONDS` (900), `CLASSIFY_LLM_RETRY_SECONDS` (60), `CLASSIFY_MAX_TOKENS` (8192), `CLASSIFY_CONFIDENCE_THRESHOLD` (0.7), `CLASSIFY_RETRY_TEMPERATURE` (0.7), `CLASSIFY_HEAD_CHARS` (20000), `CLASSIFY_CHUNK_CHARS` (8000), `CLASSIFY_LANGUAGE_THRESHOLD` (0.15), `CLASSIFY_TIMEZONE` (Europe/Berlin), `CLASSIFY_REGISTRY_GRACE_SECONDS` (60), `CLASSIFY_BATCH` (false).
- Gateway: neuer Eintrag `document-classify background <key>` in der Schlüsseldatei auf dem Server.

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1, AK-4, AK-17, AK-19, AK-46 | Ende-zu-Ende mit echtem Register (Wegwerf-Postgres, Temp-Git-Repo) und LLM-Attrappe: Frontmatter, Umbenennung, Commit-Nachricht, Sammel-Commit | E2E |
| AK-2, AK-3, AK-5 | Register: Übernahme mit `requires`; Bilder/Mails unberührt; Ordnertyp wird nicht gelesen, Attrappe zählt Aufruf | E2E |
| AK-6, AK-41 | Abfragefrist konfiguriert; 5 Quellen, Parallelität 1 → nie mehr als eine `running` | Unit (Register-Attrappe) |
| AK-7–10, AK-43, AK-44 | Attrappe mit gesteuerten Antworten: Temperatur, Konfidenz, Zweitversuch, ungültiges JSON, Backoff bis `failed_permanent` | Unit + E2E |
| AK-11–16, EC-5 | Feldsätze je Typ, `null`, ungültige Werte, Typwechsel, IBAN/ISIN | Unit + E2E |
| AK-18, AK-20, EC-6–8 | Titelbildung, neues `modified` | Unit + E2E |
| AK-21–24, EC-12 | Prompt-Inhalt, Sprachheuristik, Zweitversuch | Unit |
| AK-25–31, EC-3, EC-4 | 100.000-Zeichen-Dokument, 12-Seiten-Auszug, Dubletten, Salden, kaputter Abschnitt | Unit + E2E |
| AK-32 | `extraction.empty` → kein Aufruf | Unit + E2E |
| AK-33–39 | `manual`-Typ, Hand-Korrekturen (Typ, Inhalt, Einzelfelder), Inhaltsänderung über `extract`, `fields.iban` in `manual`, erneut versuchen | E2E + Register-Tests |
| AK-40, AK-42 | Attrappe prüft Schlüssel; Gateway weg/Zeitüberschreitung → Versuchszähler unverändert, Warnung, danach weiter | Unit + E2E |
| AK-45, EC-15 | Abbruch vor dem Schreiben; gelöschte Quelle → verworfen | Unit + E2E |
| AK-47, AK-48 | keine nginx-Route, keine Redis/Weaviate/MQTT-Abhängigkeit, alte Workflows unverändert (git diff) | Prüfung |
| AK-49, AK-50 | echte Dokumente, echtes LLM, Chat parallel | nur nach Deploy durch den Menschen |

Nicht ohne Produktivsysteme testbar: Qualität der echten LLM-Antworten und die Last neben Chat/Sprache (AK-49/50) → LLM-Attrappe (OpenAI-kompatibel) im Test.

Deploy-Schritte für den Menschen:
1. Migration `sql/migrations/2026-11-23_PROJ-118_classify_resets.sql` anwenden.
2. `alice-source-registry` neu bauen (Schnittstellen-Erweiterungen, abwärtskompatibel).
3. Gateway-Schlüssel für `document-classify` (Tier `background`) in `/srv/warm/llm-gateway/clients` eintragen, Gateway neu starten; `.env` für `alice-document-classify` aus `.env.example` anlegen (Modell wie das bisherige DMS-Modell).
4. Staging mit `scripts/stage.sh alice-document-classify <PR>` (arbeitet echte Quellen ab), nach dem Merge `sync-compose.sh` und `make rebuild s=automations/alice-document-classify`.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Neuer Dienst `alice-document-classify` | Stufe in `alice-text-extraction` | Eigene Parallelität und Ausfallgründe; Extraktion bleibt LLM-frei |
| Getrennte Aufrufe (Typ / Felder / Buchungen je Abschnitt) | ein Aufruf für alles | Feldsatz passt zum Typ, kurze Wiederholungen, lange Auszüge vollständig |
| Zurücksetzen je Feld als Spalte im Register | Sonderfall „classify“ im Code | Gilt für künftige Stufen ohne Codeänderung |
| `manual` mit `fields.<name>` | ganzer Block `fields` geschützt | Spec verlangt feldgenauen Schutz (AK-36, AK-38) |
| Schreiben mit Übernahme-Token | Prüfung nur beim Abschluss | Kein veraltetes Ergebnis landet im Repo (EC-9, EC-15) |
| Saldenkennzeichen in `fields` | oberste Ebene | Verschwinden von selbst, wenn der Auszug später aufgeht |
| Präfix in Ortszeit | UTC | Entspricht der Anzeige im Dateimanager |

## Umsetzung (Bau, 2026-11-23)
- Gebaut wie oben beschrieben: Dienst `docker/compose/automations/alice-document-classify/` (Port 8015, keine nginx-Route, Eintrag im `Makefile`, nur im Netz `backend`, kein NAS-Mount), Register-Erweiterungen in `alice-source-registry`, Spalte `resets_on_fields` in `sql/init-schema.sql` und Migration `sql/migrations/2026-11-23_PROJ-118_classify_resets.sql`, Eintrag `document-classify background <key>` in `alice-llm-gateway/clients.example`.
- Register-Schnittstelle (alles optional, bisherige Aufrufer unverändert):
  - `POST /stages/{stage}/claim` mit `requires` (Liste von Stufen, die `done` oder `skipped` sein müssen); solche Übernahmen laufen wie bei `kinds` direkt über das Register.
  - `PUT /sources/{id}/document` mit `token`: Antwort `discarded: true`, wenn die Stufe nicht mehr mit diesem Token läuft oder die Quelle gelöscht ist. Wird beim Schreiben zuerst eine Hand-Änderung committet und setzt diese die Stufe zurück, wird das Ergebnis ebenfalls verworfen (die Hand-Korrektur bleibt committet).
  - `GET/POST /stages` kennt `resets_on_fields`.
  - Zurücksetzen: Stufen mit `resets_on_content_change` wie bisher bei jeder Änderung außer `locations`/`manual`/`deleted`; zusätzlich Stufen, deren `resets_on_fields` ein geändertes Feld der obersten Ebene oder `content` nennen. Gilt beim Schreiben einer anderen Stufe und bei Hand-Korrekturen.
  - `manual`: Ändert ein Mensch ein Feld innerhalb eines Objekts (z. B. `fields.amount_gross`, `classification.uncertain`), steht genau dieser Pfad in `manual`; beim Schreiben bleibt dieser innere Wert erhalten, die übrigen inneren Felder werden ersetzt. Der Eintrag des ganzen Blocks (`fields`) schützt weiterhin den ganzen Block. README im Repo (nur bei neuen Repos) ergänzt.
- LLM-Aufrufe: System-Prompt beginnt mit `TASK: classify|extract|transactions`; Antwortformat JSON (`response_format: json_object`), Denkblöcke und Codezäune werden entfernt. Der Feld-Prompt enthält nur die Felder des Typs.
- Frontmatter-Felder der Stufe: `type`, `classification` (`confidence` auf 3 Stellen gerundet, `uncertain`), `title`, `summary`, `summary_language_uncertain` (immer gesetzt, true/false), `fields`. Bei Hand-Typ werden `type` und `classification` nicht geschrieben. Leeres Dokument: `classification.confidence` = `null`.
- Saldenkennzeichen `balance_mismatch`/`balance_difference` stehen nur bei Abweichung in `fields` (Entscheidung oben).
- Buchungsabschnitte: Seiten werden bis `CLASSIFY_CHUNK_CHARS` zusammengefasst; eine größere Seite wird an Zeilengrenzen geteilt („Seite 3, Teil 2“). Dubletten werden nur zwischen letzter Buchung eines Abschnitts und erster des nächsten zusammengeführt.
- Hinweis zur Git-Umbenennung: Git erkennt Umbenennungen über die Ähnlichkeit des Inhalts. Bei sehr kurzen Dokumenten wächst das Frontmatter durch die Klassifizierung so stark, dass `git log --follow` die Datei vor der Umbenennung nicht mehr findet; bei üblichen Dokumentlängen bleibt die Historie verbunden (im E2E-Test geprüft).
- Abweichungen von der Spec: AK-37 zweiter Halbsatz entfällt (Entscheidung A im Issue: geändertes Original setzt `classify` immer zurück). Sonst keine.
