# PROJ-62: Frontend Internationalisierung (i18n)

## Status: Planned
**Created:** 2026-07-19
**Last Updated:** 2026-07-19

## Dependencies
- None technically, but should land after PROJ-60 (Theming) since both touch nearly every component file — sequencing avoids repeated merge conflicts.
- Absorbs the data-driven refactor of `DOC_META_LABELS`/`EXTRA_META_LABELS`/`HIDDEN_META_KEYS` in `FlipCard.tsx` (frontend-design.md Abschnitt 6.6), since those are exactly the hardcoded-German-string problem this spec solves.
- Reuses the existing `sprache`-Feld in `alice.user_profiles` (bereits vorhanden, aktuell nur für die Alice-Antwortsprache genutzt) — keine neue DB-Spalte nötig.
- **Verwandt, aber separat: PROJ-63** (Backend-Sprachcode-Offenheit in `alice-auth`/`alice-chat-stream`) öffnet die aktuell auf `("deutsch","englisch")` hart validierte `sprache`-Whitelist und die binäre LLM-Prompt-Logik zu einer konfigurierbaren Sprachliste. Diese Spec (PROJ-62) macht nur die Frontend-Übersetzungsschicht offen; das Sprache-Dropdown in Mein Profil/`CreateUserDialog` sollte seine Optionsliste aus derselben Quelle wie PROJ-63 beziehen, sobald diese existiert, statt einer eigenen hartcodierten Liste.

## User Stories
- Als Nutzer möchte ich die Oberfläche (Menüs, Buttons, Labels, Fehlermeldungen, Tooltips) auf Deutsch oder Englisch sehen, statt ausschließlich auf Deutsch.
- Als Nutzer möchte ich, dass meine bereits vorhandene "Sprache"-Einstellung in Mein Profil sowohl Alices Antworten als auch die UI-Sprache steuert — eine Einstellung, kein Widerspruch.
- Als Erstbesucher (noch nicht eingeloggt) möchte ich, dass der Login-Screen meiner Browser-Spracheinstellung folgt, damit ich nicht zwingend Deutsch lesen muss, um mich anzumelden.
- Als eingeloggter Nutzer möchte ich, dass nach dem Login sofort meine gespeicherte Sprachpräferenz greift, unabhängig davon, was der Login-Screen zuvor zeigte.
- Als zukünftiger Betreiber möchte ich, dass eine dritte Sprache ergänzt werden kann, ohne Komponenten-Code anzufassen (nur neue Übersetzungsressourcen).

## Acceptance Criteria
- [ ] Alle statischen UI-Texte sind übersetzbar und liegen für Deutsch und Englisch vollständig vor: Login, Chat (Platzhalter, Tool-Status-Chips, Fehlerzustände, Buttons), Sidebar (Umbenennen/Löschen/Kontextmenü/Service-Links), alle Settings-Tabs (Mein Profil, DMS, Nutzerverwaltung, E-Mail, Chatarchiv), Vision/FlipCard (Metadaten-Labels, Zusammenfassung, leere/fehlende Zustände).
- [ ] Die Architektur ist so offen, dass eine weitere Sprache durch Hinzufügen einer neuen Übersetzungsressource ergänzt werden kann, ohne bestehenden Komponenten-Code zu ändern.
- [ ] Das bestehende `sprache`-Feld in Mein Profil (aktuell: Antwortsprache von Alice) steuert zusätzlich die UI-Sprache — ein Dropdown, ein gespeicherter Wert.
- [ ] Vor dem Login zeigt der Login-Screen die per `navigator.language` erkannte Browsersprache (Fallback Deutsch, falls weder de noch en erkannt wird).
- [ ] Nach erfolgreichem Login wechselt die UI unmittelbar auf den im Profil gespeicherten `sprache`-Wert, auch wenn dieser vom zuvor gezeigten Login-Screen abweicht.
- [ ] Die hartkodierten Metadaten-Label-Maps in `FlipCard.tsx` (`DOC_META_LABELS`, `EXTRA_META_LABELS`, `HIDDEN_META_KEYS`) sind auf eine datengetriebene, übersetzbare Struktur umgestellt statt fest verdrahteter deutscher Strings.
- [ ] Datumsformatierung (z. B. `formatMetaValue` in `FlipCard.tsx`, aktuell hart auf `de-DE` codiert) folgt der aktiven UI-Sprache (`de-DE` vs. `en-US`/`en-GB`).
- [ ] Admin-seitiges Anlegen neuer Nutzer (`CreateUserDialog`) setzt weiterhin den initialen `sprache`-Wert des neuen Nutzers — unverändertes Verhalten, jetzt konsistent mit der UI-Sprachsteuerung.
- [ ] Fehlt ein Übersetzungsschlüssel für die aktive Sprache, wird kein technischer Schlüsselname angezeigt, sondern ein sinnvoller Fallback (deutscher Text) verwendet — kein sichtbarer Absturz oder `undefined`.

## Edge Cases
- Übersetzungsschlüssel fehlt in einer Sprachressource (z. B. nach unvollständigem PR): Fallback auf Deutsch statt Rohschlüssel oder leerem Text.
- Browsersprache ist weder Deutsch noch Englisch (z. B. Französisch): Login-Screen fällt auf Deutsch zurück.
- Rollen Gast/Kind: gleiche Sprachsteuerung wie alle anderen Rollen, keine Einschränkung.
- Von Alice/LLM generierte Chat-Antworten und vom Nutzer eingegebener Text werden **nicht** übersetzt — nur die UI-Chrome (Buttons, Labels, System-/Fehlermeldungen) ist Teil dieser Spec.
- Backend-generierte Fehlermeldungen (z. B. von `alice-auth` bei ungültigen Login-Daten) sind aktuell teils hartkodiertes Deutsch und **nicht Teil dieser Spec** — nur clientseitige UI-Strings werden übersetzt; falls eine Backend-Fehlermeldung 1:1 durchgereicht wird, bleibt sie vorerst deutsch.
- Sprachwechsel während eines laufenden Chat-Streams (SSE aktiv): UI-Chrome darf sofort umschalten, ohne den laufenden Stream zu unterbrechen.
- Pluralisierung/Grammatik-Unterschiede zwischen Deutsch und Englisch (z. B. "1 Dokument gefunden" vs. "3 Dokumente gefunden") müssen pro Sprache korrekt behandelt werden, nicht nur wortwörtlich übersetzt.

## Technical Requirements (optional)
- Wahl der konkreten i18n-Bibliothek/-Architektur (z. B. Übersetzungsdateien pro Locale, Routing-Strategie) erfolgt in `/architecture` — hier nur die funktionale Anforderung: clientseitig umschaltbar, kompatibel mit dem aktuellen statischen Export, keine Server-Roundtrips für den reinen UI-Sprachwechsel.
- Erwartete Struktur: pro Sprache eine zentrale Übersetzungsressource (kein Text hartkodiert in `.tsx`-Dateien), damit eine dritte Sprache ohne Komponenten-Änderung ergänzt werden kann.
- Locale-abhängige Datums-/Zahlenformatierung zentral kapseln (nicht pro Komponente einzeln `toLocaleDateString` mit hartem Locale-String).

---
<!-- Sections below are added by subsequent skills -->

## Tech Design (Solution Architect)
_To be added by /architecture_

## QA Test Results
_To be added by /qa_

## Deployment
_To be added by /deploy_
