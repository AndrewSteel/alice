# Architektur: PROJ-122 ETL-Status-Ansicht (Admin, WebApp) (#14)

**Spec:** [spec.md](spec.md) · **Stand:** 2026-11-25

## A) Betroffene Bausteine
```
alice-etl-status (Container, NEU, Python/FastAPI, Port 8018)
+-- einzige Schnittstelle der WebApp zum neuen ETL, nur für admin (JWT + Rolle aus der DB)
+-- liest Register-Tabellen direkt (Matrix, Quellenliste, Fehler, Detail, Vorschau, Kachel-Zahlen)
+-- "erneut versuchen" einzeln und sammelweise -> alice-source-registry (Retry + Ereignis)
+-- Neuaufbau und Abgleich -> alice-etl-rebuild (durchgereicht, "gestartet von" = Admin)
+-- GET /health
nginx: neue Route /api/etl/ -> alice-etl-status:8018 (eigenes Ratenlimit)
Frontend:
+-- neue Seite /etl (Zusammenfassung, Übersicht/Matrix + Quellenliste, Fehler, Neuaufbau, Abgleich,
|   Quellen-Detail als Seitenleiste), Auto-Refresh-Auswahl
+-- Dashboard: neue Kachel "ETL" (Kachel-Registry), alte Kacheln unverändert
+-- UserCard: Eintrag "ETL-Status" (nur admin)
+-- i18n de/en
docker/compose/scripts/Makefile: neuer Stack automations/alice-etl-status
PostgreSQL: keine Schemaänderung
alice-source-registry, alice-etl-rebuild: keine Änderung (deren interne Schnittstellen bleiben ohne nginx-Route)
```

## B) Datenmodell
- **Keine neuen Tabellen.** Alles, was die Seite zeigt, steht schon im Register (PROJ-115: Quellen, Fundorte, Stufen, Stufenzustände, Ereignisse) und in den Lauf-/Abgleich-Tabellen (PROJ-120).
- **Gelesen (nur lesend, direkt per SQL):** `sources`, `source_locations`, `source_stages`, `pipeline_stages`, `source_events`, `users` (Rolle und Name des Admins).
- **Geschrieben wird nichts direkt:** Retry und Ereignis gehen über die Register-Schnittstelle, Neuaufbau/Abgleich über die Schnittstelle von PROJ-120. Kein Zugriff auf Repo, NAS, Redis oder Weaviate.
- **Im Browser gemerkt:** nur die Auto-Refresh-Wahl (`localStorage`).
- **Wer darf was:** ausschließlich aktive Nutzer mit Rolle `admin`. Die Rolle wird bei **jeder** Anfrage in `alice.users` nachgeschlagen (nicht nur aus dem Token), damit eine Herabstufung sofort greift (EC-8).

## C) Abläufe

### Zugriff
1. Browser ruft `/api/etl/...` mit dem JWT auf. nginx leitet an `alice-etl-status` weiter.
2. Der Dienst prüft die Signatur (RS256, öffentlicher Schlüssel wie bei den anderen Diensten). Kein/ungültiges/abgelaufenes Token → 401 (die WebApp leitet zur Anmeldung, EC-7).
3. Nutzer laut DB nicht aktiv oder nicht `admin` → 403, nichts wird gelesen oder geändert. Die Seite leitet bei 403 zum Chat weiter (AK-3, EC-8).

### Anzeige (eine Abfrage je Bereich und Refresh)
- **Zustand** (`GET /etl/state`, mit Art- und Gelöscht-Filter): Stufen in Register-Reihenfolge, Matrix Stufe × Zustand, Fehlerzahlen (Quellen mit `failed_permanent` oder gesperrt; Quellen mit `failed`), Anzahl Quellen, aktiver bzw. letzter Neuaufbau (von PROJ-120), letztes beendetes Abgleich-Ergebnis und laufender Abgleich (von PROJ-120), Erreichbarkeit von Register und PROJ-120-Dienst, Retry-Grenze. Fällt nur PROJ-120 aus, kommen Matrix und Fehler trotzdem; die Bereiche Neuaufbau/Abgleich zeigen dann das Banner (EC-9). Fällt die Datenbank aus, antwortet der Dienst 503 → Banner, alte Daten bleiben als „veraltet“ stehen.
- **Quellenliste** (`GET /etl/sources`): Zeilen = Quelle × gewählte Stufe, Filter Zustand, Art, gelöscht, gesperrt, Suche nach Titel-Teil oder `id`, seitenweise (50 je Seite). Fehlermeldung gekürzt (300 Zeichen). Liefert zusätzlich die Anzahl der Quellen, die ein Sammel-Retry für diese Auswahl träfe.
- **Fehler** (`GET /etl/errors`): je fehlgeschlagener Stufe (`failed`/`failed_permanent`) eine Zeile, je gesperrter Quelle eine Zeile „gesperrt“; ohne gelöschte Quellen; sortiert nach jüngstem Fehler (letzter Versuch bzw. Zeitpunkt der Sperre); Filter Stufe, Zustand (inkl. „gesperrt“), Art; seitenweise.
- **Quellen-Detail** (`GET /etl/sources/{id}`): Stammdaten, Sperre mit Ursache, alle Stufen (vollständige Meldung), alle Fundorte, Ereignisse neueste zuerst (höchstens 200), Pfad der Quell-Markdown; je Stufe, ob „erneut versuchen“ erlaubt ist.
- **Neuaufbau/Abgleich:** Fortschritt, Läufe, Fehlerliste eines Laufs, Ergebnisse, Ergebnis-Detail und Lücken werden von PROJ-120 durchgereicht. Die **Vorschau** vor dem Start (Anzahl betroffener Quellen, Stufen ab Startstufe) rechnet der Dienst selbst per SQL (ungefähr: nicht gelöschte, nicht gesperrte Quellen der Art; Stufen ab der Startstufe, die für die Art nicht `skipped` sind).

### Erneut versuchen
1. **Einzeln:** Dienst liest den aktuellen Zustand. Nur `failed`/`failed_permanent` einer nicht gelöschten, nicht gesperrten Quelle → Register-Retry (→ `pending`, Versuche 0), danach Ereignis `manual_retry` an der Quelle mit dem Namen des Admins. Sonst 409 mit Grund (AK-15, AK-19, EC-1, EC-3); die Seite zeigt den Grund als Toast und lädt neu.
2. **Sammelweise:** gleiche Filter wie Liste bzw. Fehlerbereich. Zuerst eine Probe (`dry_run`) für die Zahl im Bestätigungsdialog, dann die Ausführung. Bei der Ausführung wird die Auswahl **neu** bestimmt (nur Stufen, die dann noch `failed`/`failed_permanent` sind, EC-2) und mit der Grenze (Standard 1.000 Quellen) verglichen; darüber → 409 `limit_exceeded`, nichts geändert (AK-18, auch bei direktem Aufruf). Die Antwort nennt die tatsächliche Anzahl. Ein Abbruch im Dialog schickt nichts (AK-17).
3. Pro Quelle ein Ereignis mit dem Admin-Namen (AK-13). Die Register-Aufrufe laufen mit begrenzter Parallelität (10).

### Neuaufbau und Abgleich steuern
- Start: Startstufe + optionale Art aus dem Dialog; „gestartet von“ setzt der Dienst aus dem Admin-Namen (nie aus dem Request). Pausieren/Fortsetzen/Abbrechen/„Abgleich jetzt“/„Vollständig neu hashen“ werden durchgereicht. Ablehnungen von PROJ-120 (409/422/404) gehen mit Grund an die Seite (AK-42, EC-6); PROJ-120 nicht erreichbar → 503.
- Start deaktiviert, solange ein Lauf `läuft`/`pausiert`/`wartet` (AK-22); Abgleich-Buttons deaktiviert, solange `/health` von PROJ-120 einen laufenden Abgleich meldet (AK-34). Rückfragen vor Abbrechen und Neu-Hashen.

### Seite und Kachel
- Route `/etl` im bestehenden Haupt-Layout (Anmeldung, Toasts). Kopfzeile mit Zurück zu Dashboard/Chat, Refresh-Auswahl (aus/5/15/60 s, Standard 5 s, `localStorage`), Zeitpunkt des Stands.
- Oben Zusammenfassung (Abgleich mit Hervorhebung bei `unvollständig` oder > 36 h, Kurzstand Neuaufbau, Fehlerzahl). Darunter Tabs: Übersicht (Matrix, Klick auf Zelle → Quellenliste), Fehler, Neuaufbau, Abgleich. Quellen-Detail und Abgleich-Detail als Seitenleiste (Sheet).
- Auto-Refresh lädt Zustand und den gerade sichtbaren Bereich neu. Fehlschlag → Banner „Status-Dienst nicht erreichbar“, letzte Daten mit Zeitstempel „veraltet“, Aktionen deaktiviert, **kein** Toast je Refresh; Erfolg → Banner verschwindet (AK-41).
- Kachel „ETL“: lädt `GET /etl/state` beim Öffnen des Dashboards und über den Refresh-Knopf (wie die übrigen Kacheln). Drei Zeilen + Ampel:
  - rot: kein Abgleich, letzter `unvollständig` oder älter als 36 h;
  - sonst gelb: Quellen mit `failed_permanent` oder gesperrt, oder das letzte Ergebnis hat gemeldete (nicht reparierte) Lücken;
  - sonst grün.
  Neuaufbau-Prozent = durchgelaufene Quellen / Quellen im Lauf.
- Mobil: Matrix und Tabellen in eigenem horizontalen Scroll-Container, die Seite selbst scrollt nicht seitlich.

## D) Technische Entscheidungen
- **Neuer kleiner Dienst statt Erweiterung von `alice-etl-rebuild` oder `alice-chat-stream`**, weil die Spec verlangt, dass die internen Schnittstellen von PROJ-115/120 ohne nginx-Route bleiben, und EC-9 verlangt, dass die Register-Ansichten auch bei Ausfall des PROJ-120-Dienstes funktionieren. Der Chat-Dienst soll keine ETL-Logik tragen.
- **Lesen per SQL, Schreiben über die Dienste**: Matrix und Listen über 60.000 Quellen brauchen eine gebündelte Abfrage (< 1 s, AK-46); alle Änderungen laufen über die Schnittstellen, die die Regeln kennen (Queue, Kennzeichen, Commits).
- **Rolle aus der Datenbank je Anfrage**: Tokens leben länger als eine Rollenänderung; nur so greift EC-8 „spätestens die nächste Anfrage“.
- **Retry-Prüfung im neuen Dienst**: Die Register-Route erlaubt auch `pending`/`done`; die Spec erlaubt nur `failed`/`failed_permanent` nicht gesperrter, nicht gelöschter Quellen. Zwischen Prüfung und Register-Aufruf liegen Millisekunden; ein dadurch theoretisch möglicher Doppel-Retry setzt höchstens eine gerade wartende Stufe erneut auf `pending` (harmlos).
- **Grenze zählt Quellen**, nicht Stufen (Spec: „Auswahl mit mehr als … Quellen“). Im Fehlerbereich ohne Stufenfilter werden alle fehlgeschlagenen Stufen der gewählten Quellen wiederholt.
- **Fehlerbereich ohne gelöschte Quellen**: Für gelöschte Quellen gibt es keinen Retry und keine Verarbeitung mehr; sie würden den Bereich nur füllen. In der Quellenliste lassen sie sich über den Filter einblenden.
- **Vorschau als Näherung**: nicht gelöschte, nicht gesperrte Quellen der Art; die genaue Aufteilung (ausgenommen je Grund) zeigt danach der Lauf.
- **Ein Zustands-Abruf je Refresh** statt vieler kleiner: weniger Last bei 5-s-Takt, alle Zahlen eines Stands passen zusammen.
- **Detail als Seitenleiste statt eigener Route**: der statische Export braucht keine dynamischen Routen; Sprünge aus Fehlerliste, Lauf-Fehlern und Lücken öffnen dieselbe Seitenleiste.

## E) Abhängigkeiten
- Pakete: `fastapi`, `uvicorn`, `httpx`, `asyncpg`, `PyJWT`, `cryptography` (wie die übrigen Dienste). Frontend: keine neuen.
- Neue Umgebungsvariablen `alice-etl-status` (Platzhalter in `.env.example`): `POSTGRES_DSN`, `JWT_PUBLIC_KEY_PATH`, `REGISTRY_URL` (Standard `http://alice-source-registry:8012`), `REBUILD_URL` (Standard `http://alice-etl-rebuild:8017`), `ETL_RETRY_LIMIT` (Standard 1000).
- Secret: öffentlicher JWT-Schlüssel wie bei `alice-chat-stream` (Bind-Mount nach `/run/secrets/jwt_public.pem`).

## F) Test- und Deploy-Plan
| AK | Nachweis | Art |
|---|---|---|
| AK-1, AK-2 | Kachel und UserCard-Eintrag sichtbar, Klick öffnet `/etl` | Browser (Playwright, API-Attrappen) |
| AK-3 | `haushalt`/`guest` auf `/etl` → weitergeleitet, keine ETL-Anfrage; kein Menüeintrag/keine Kachel | Browser |
| AK-4 | alle Routen ohne Token 401, mit `haushalt`/`guest` 403, nichts geändert; herabgestufter Admin 403 | Integration (Test-DB) |
| AK-5–7, EC-10 | Matrix-Zahlen gegen Testdaten, Art-/Gelöscht-Filter, neue Stufe erscheint | Integration |
| AK-8–10 | Liste je Zelle, 120 Quellen seitenweise, Suche Titel/`id` | Integration + Browser |
| AK-11 | Fehlerbereich mit failed/failed_permanent/gesperrt, Sortierung, Filter | Integration |
| AK-12, EC-4, EC-5 | Detail mit Fundorten, Ereignissen, langer Meldung, Sonderzeichen-Titel | Integration + Browser |
| AK-13–19, EC-2, EC-3 | Retry einzeln/sammelweise gegen das echte Register in-process (Test-DB, Temp-Repo), Grenze, Ereignis mit Admin-Namen, abgelehnte Zustände | Integration |
| AK-20–29, AK-33, AK-34, EC-6, EC-11 | PROJ-120 als Attrappe (feste Fortschrittsdaten); durchgereichte Steuerung, `started_by`, Fehlerweitergabe; Anzeige im Browser | Integration + Browser |
| AK-30–32, AK-35 | Ergebnis-Daten aus der Attrappe; Hervorhebung, Detail je Ebene, Links, keine Lücken-Aktion | Browser |
| AK-36, AK-37 | Kachel-Zahlen und Ampel (Unit-Test der Ampel-Regel im Dienst + Browser) | Unit + Browser |
| AK-38 | Kachel-Registry: alte Einträge unverändert | Durchsicht + Browser |
| AK-39–42 | Refresh-Takt, Merken, Ausfall/Rückkehr, Toast bei Ablehnung | Browser |
| AK-43–45 | Leerzustände, en/de, 375 px | Browser + Screenshots |
| AK-46 | 60.000 Quellen × 7 Stufen per SQL, Zeit für Zustand, Listen-/Fehlerseite < 1 s; Dienst hat weder Repo- noch NAS-Mount | Integration + Durchsicht |
| AK-47 | Dienst hat keine Redis-/Weaviate-Anbindung, keine n8n-Änderung | Durchsicht |
| AK-48–50 | Live nach Deploy | Mensch |

Nicht ohne Produktivsysteme testbar: echter Bestand, echte Stufen-Dienste, echter PROJ-120-Dienst mit laufenden Läufen → Attrappen: Register in-process gegen Test-DB, PROJ-120-Attrappe mit festen Daten, API-Attrappen im Browser-Test.

Deploy-Schritte für den Menschen:
1. `.env` für `alice-etl-status` aus `.env.example` (`POSTGRES_DSN` wie bei `alice-etl-rebuild`).
2. `./scripts/sync-compose.sh`, `make up s=automations/alice-etl-status` (bzw. `rebuild`).
3. nginx neu laden (neue Route `/api/etl/`, neue Ratenlimit-Zone).
4. `./scripts/deploy-frontend.sh`.
5. Live-Tests AK-48–50.

## Decision Log
| Entscheidung | Alternative | Abwägung |
|---|---|---|
| Neuer Dienst `alice-etl-status` | Admin-Routen in `alice-etl-rebuild` bzw. `alice-chat-stream` | Interne Schnittstellen bleiben ohne Route; Register-Ansichten unabhängig vom PROJ-120-Dienst (EC-9); ein Container mehr |
| Lesen per SQL | alles über Register/PROJ-120 | Register hat keine Listen-/Matrix-Routen; < 1 s bei 60.000 Quellen |
| Rolle je Anfrage aus der DB | nur Token-Claim | EC-8 verlangt sofortige Wirkung |
| Retry-Prüfung im neuen Dienst | Register-Route ändern | Register bleibt unverändert; Restrisiko eines Doppel-Retrys harmlos |
| Grenze zählt Quellen | Stufen zählen | Wortlaut der Spec |
| Detail als Seitenleiste | eigene Route `/etl/source?id=` | statischer Export, ein Baustein für alle Sprünge |
