# PROJ-59: Financial Research Workflow

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Dependencies
- None (steht eigenständig; nutzt bestehende Alice-Infra: Chat-Tool-Calling, n8n, Gotify, nginx-Static-Hosting, Permission-System)

## Context

Alice soll per Sprach-/Text-Auftrag eine mehrstufige Sektor-Analyse (Marktüberblick, Screening, Comps, Tiefenanalyse, DCF, Investment-Thesen) anstoßen können. Die eigentliche Analyse läuft über die Claude-Skills/Plugins `equity-research`, `financial-analysis` und `market-researcher` aus dem externen Repo `anthropics/financial-services`, orchestriert von einer selbst-gehosteten Claude Code CLI in einem neuen Docker-Container. Das Vorbild für den Analyse-Ablauf und das Ergebnisformat ist `docs/planning/financial-example-skill.md`.

**Bewusster Constraint-Bruch:** Diese Funktion benötigt zwingend Claude als Ausführungs-Engine (Claude Code CLI, ausgehender Internetzugriff) — eine Cloud-Abhängigkeit, die laut PRD-Non-Goals aber explizit für spezifische Use-Cases erlaubt ist ("Keine Cloud-LLM-Pflicht (optional für spezifische Use-Cases)"). Alice's Kern-Chat bleibt vollständig Ollama-basiert; nur dieses eine Feature nutzt Claude.

**Auth-Modell:** Läuft über einen bestehenden Claude Pro-Plan (Subscription mit rollierendem Token-Limit), nicht über nutzungsbasierte API-Abrechnung. Das genaue Headless-Auth-Verfahren für eine Subscription in einem Docker-Container ist bei Implementierung zu klären (→ /architecture).

## User Stories

- Als Admin möchte ich Alice per Chat/Sprache beauftragen, einen Wirtschaftssektor zu analysieren, indem ich nur den Sektornamen nenne, damit ich ohne manuelle Recherche eine strukturierte Investment-Übersicht bekomme.
- Als Admin möchte ich optional eine These/Angle mitgeben (z.B. "...mit Fokus auf europäische Anbieter"), damit die Analyse auf meine spezifische Fragestellung zugeschnitten ist.
- Als Admin möchte ich sofort eine Bestätigung samt grober Zeitschätzung bekommen, wenn der Auftrag gestartet wurde, damit ich weiß, dass Alice arbeitet und wie lange ich warten muss.
- Als Admin möchte ich benachrichtigt werden (Chat-Nachricht + Push), sobald das Dashboard fertig ist, damit ich es nicht aktiv abfragen muss.
- Als Admin möchte ich bei einem fehlgeschlagenen Lauf eine klare Fehlermeldung bekommen, damit ich nicht ergebnislos auf eine Antwort warte, die nie kommt.
- Als Nutzer ohne Admin-Rolle möchte ich beim Versuch, die Funktion zu nutzen, eine klare Ablehnung bekommen, damit klar ist, dass dies eine Admin-Funktion ist.

## Acceptance Criteria

- [ ] Nur Nutzer mit Rolle `admin` können den Workflow auslösen; andere Rollen erhalten eine ablehnende Antwort ohne dass ein Job gestartet wird
- [ ] Nutzer kann den Auftrag per natürlichsprachigem Freitext auslösen (z.B. "Analysiere den Sektor KI-Infrastruktur"); Alice erkennt die Absicht selbstständig per Function-Calling
- [ ] Pflichtangabe ist der Sektor-Name; eine optionale These/Angle kann im selben Satz mitgegeben werden
- [ ] Nennt der Nutzer keinen erkennbaren Sektor, startet Alice keinen Job, sondern fragt aktiv nach ("Welchen Sektor soll ich analysieren?")
- [ ] Nach Auftragsstart antwortet Alice sofort mit einer Bestätigung inkl. grober Zeitschätzung (z.B. "gestartet, dauert ca. 10–20 Minuten"), ohne auf den Abschluss zu warten
- [ ] Der Nutzer kann mehrere Analysen parallel laufen lassen (z.B. zwei Sektoren gleichzeitig), ohne dass Alice das ablehnt
- [ ] Nach erfolgreichem Abschluss erscheint eine neue Assistant-Nachricht in der ursprünglichen Chat-Session mit einem funktionierenden Link zum Dashboard, UND eine Gotify-Push-Benachrichtigung wird verschickt
- [ ] Das Dashboard enthält für den analysierten Sektor: Marktüberblick (TAM/CAGR), 5 verglichene Firmen mit Comps, Radar-Charts (Wachstum/Effizienz/Marge/Bewertung/Burggraben), Bull/Base/Bear-DCF-Szenarien, Moat-Details und ein Verdict-Label pro Firma — analog zum Format aus `docs/planning/financial-example-skill.md`
- [ ] Schlägt der Job fehl (API-Fehler, Timeout, Absturz), erscheint stattdessen eine Fehler-Nachricht in der Session mit Kurzgrund, plus Gotify-Push
- [ ] Stoppt ein Lauf, weil das Token-Limit des Claude Pro-Plans erreicht wurde, pausiert der Job statt zu scheitern: Nutzer bekommt eine Info-Nachricht ("pausiert wegen Token-Limit, wird automatisch fortgesetzt"), und der Job wird automatisch fortgesetzt, sobald das Limit sich zurückgesetzt hat — ohne manuellen Neustart durch den Nutzer
- [ ] Das Dashboard ist über eine stabile, direkt aufrufbare URL erreichbar (kein Login-Zwang für den Abruf der generierten Datei innerhalb des VPNs)

## Edge Cases

- Was passiert, wenn der Nutzer denselben Sektor zweimal kurz hintereinander anfragt? → Beide Läufe starten unabhängig voneinander (kein Dedupe in V1); Kosten/Ressourcen-Verantwortung liegt beim Nutzer.
- Was passiert, wenn während eines laufenden Jobs der Nutzer nach dem Status fragt ("wie weit bist du?")? → V1 kann das nicht beantworten (kein Job-Status-Tracking); bekannte Einschränkung, kein Blocker für den Launch.
- Was passiert, wenn die Claude-Authentifizierung fehlt oder ungültig ist? → Job schlägt sofort fehl, Nutzer bekommt die reguläre Fehler-Nachricht (kein stiller Absturz).
- Was passiert, wenn das Token-Limit des Pro-Plans mehrfach hintereinander während desselben Jobs erreicht wird? → Job pausiert und setzt jedes Mal automatisch fort, bis er abgeschlossen ist; keine Obergrenze an Pausen-Zyklen in V1.
- Was passiert, wenn der Nutzer die App/den Chat schließt, bevor der Job fertig ist? → Kein Problem, da Fertigstellung asynchron per Chat-Nachricht + Gotify-Push kommuniziert wird, unabhängig von einer offenen Session.
- Was passiert mit alten Dashboard-Dateien über die Zeit? → Kein automatisches Cleanup in V1 (Non-Goal); Dateien sammeln sich im Shared Volume/nginx-Verzeichnis.
- Was passiert, wenn ein Nicht-Admin versucht, die Funktion per Chat anzufragen? → Alice lehnt ab, ohne dass ein Job gestartet oder API-Kosten verursacht werden.

## Non-Goals (V1)

- Keine Live-Kursdaten/kostenpflichtigen Datenkonnektoren (FactSet, Morningstar, S&P Global, ...) — Analyse basiert auf Claude-Wissen (+ optional Web-Suche)
- Kein Job-Status-Tracking/Fortschrittsanzeige während der Laufzeit
- Keine Zwischen-Checkpoints/Nutzer-Bestätigung während des Laufs (läuft vollautomatisch headless durch)
- Kein automatisches Aufräumen alter Dashboard-Dateien
- Keine Job-Historie/Übersicht vergangener Analysen im Frontend

## Technical Requirements (optional)

- Security: Zugriff ausschließlich für Rolle `admin` (Permission-Gate analog bestehender admin-only Chat-Features)
- Verfügbarkeit: Läuft nur innerhalb des VPNs, wie der Rest von Alice
- Keine Echtzeit-Anforderung: Job darf mehrere Minuten dauern; Antwortzeit der Auftragsbestätigung dagegen wie bei anderen Chat-Tools üblich (\< 3s)

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
