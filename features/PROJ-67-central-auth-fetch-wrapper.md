# PROJ-67: Zentraler Auth-Fetch-Wrapper

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Dependencies
- None (reiner Frontend-Refactor, keine Backend-/API-Vertragsänderung).

## User Stories
- Als Entwickler möchte ich Auth-Header-Erzeugung und 401-Behandlung an einer einzigen Stelle pflegen, statt in sechs Service-Dateien (`api.ts`, `dms.ts`, `adminApi.ts`, `mailApi.ts`, `profileApi.ts`, `voiceApi.ts`) nahezu identischen Code zu duplizieren.
- Als Entwickler möchte ich, dass ein neuer Service (zukünftig) automatisch das korrekte Auth-/401-Verhalten bekommt, indem er den zentralen Wrapper nutzt, statt eine eigene Kopie zu schreiben.
- Als Nutzer soll sich am sichtbaren Verhalten (401 → Logout + Redirect zu `/login`, Ausnahme beim Passwort-ändern-Dialog) durch diesen Refactor nichts ändern.

## Acceptance Criteria
- [ ] Ein zentraler Fetch-Wrapper (z. B. `services/fetchWithAuth.ts`) ersetzt die duplizierten `authHeaders()`/`bearer()`- und `handleAuthError()`-Funktionspaare in `api.ts`, `dms.ts`, `adminApi.ts`, `mailApi.ts`, `profileApi.ts`, `voiceApi.ts`.
- [ ] Der Wrapper hängt automatisch `Authorization: Bearer <token>` (und `Content-Type: application/json`, sofern nicht überschrieben) an; fehlt der Token, wird sofort zu `/login` umgeleitet, bevor ein Request abgesetzt wird (bestehendes Verhalten).
- [ ] Bei `401`-Antwort: Token wird gelöscht (`clearToken()`) und zu `/login` umgeleitet — bestehendes Verhalten, jetzt zentral implementiert.
- [ ] Der Wrapper unterstützt eine Option, das Auto-Redirect-Verhalten bei 401 zu unterdrücken (genutzt vom Passwort-ändern-Aufruf in `profileApi.ts`, wo ein 401 auch "falsches aktuelles Passwort" bedeuten kann); der Aufrufer wertet den Fehler in diesem Fall selbst aus.
- [ ] Der SSE-Chat-Stream (`streamChat()`/`sendMessage()` in `api.ts`) nutzt den Wrapper für Header-Erzeugung und die initiale 401-Prüfung vor Stream-Start; die anschließende `ReadableStream`-Verarbeitung bleibt unverändert in `api.ts`.
- [ ] Alle bisherigen Sonderverhalten bleiben erhalten: `429`-Behandlung in `sendMessage()` (Fehlermeldung statt Logout), Netzwerkfehler-Meldungen, servertypische Fehlermeldungen je Status-Code.
- [ ] Keine funktionale Verhaltensänderung aus Nutzersicht — nur interne Konsolidierung; bestehende Tests/Requests gegen alle sechs Services verhalten sich identisch.
- [ ] `voiceApi.ts`s REST-Aufrufe (Enrollment-Upload/-Liste/-Löschen/-Toggle) nutzen den Wrapper; die WebSocket-Verbindungen (`?token=`-Query-Param in `useVoiceMode1`/`useVoiceMode2`, PROJ-68) sind **nicht** Teil dieser Spec, da sie einen strukturell anderen Auth-Mechanismus verwenden.

## Edge Cases
- Aufruf ohne Token (z. B. Race Condition beim App-Start): Wrapper wirft vor dem Request und leitet weiter — identisch zum heutigen Verhalten in jeder einzelnen Datei.
- Aufrufer, der den `suppressAuthRedirect`-Opt-out nutzt, aber die Antwort selbst nicht auswertet: Wrapper liefert weiterhin die rohe `Response`, kein stiller Fehler-Schluck.
- Gleichzeitige 401-Antworten von mehreren parallelen Requests (z. B. Sidebar lädt Sessions während Settings Mailboxen lädt): mehrfacher `clearToken()`+Redirect-Aufruf ist unschädlich (idempotent), kein Race-Condition-Schutz nötig.
- Bestehender Legacy-Fallback-Pfad (`/api/webhook/v1/chat/completions`, aktiv wenn `NEXT_PUBLIC_STREAM_API_URL` nicht gesetzt ist) muss weiterhin funktionieren.

## Technical Requirements (optional)
- Reines Frontend-Refactoring, kein Backend-Vertrag ändert sich.
- Migration schrittweise pro Service-Datei möglich (kein Big-Bang-Zwang), aber alle sechs Dateien müssen am Ende auf den Wrapper umgestellt sein.

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
