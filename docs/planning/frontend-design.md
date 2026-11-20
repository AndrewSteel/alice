# Frontend-Design — Technische Anforderungen

> Grundlagendokument für die Neugestaltung des Alice-WebApp-Frontends. Fasst die technischen und funktionalen Anforderungen zusammen, die sich aus den Feature-Specs in `features/old/phase-1/` (PROJ-1–39) und `features/old/` (PROJ-40–58) ergeben, sowie bekannte Schwachstellen der aktuellen Umsetzung. Dient als Basis für `/architecture`, nicht als fertiges Design.

---

## 1. Zweck & Einordnung

Das aktuelle Frontend ist organisch über ca. 15 Feature-Specs gewachsen (PROJ-7, Phase 1.5, bis PROJ-56, Phase 2.3). Ziel dieses Dokuments ist es, die daraus entstandenen Anforderungen an einer Stelle zu bündeln, damit auf dieser Grundlage eine **modernere Version des aktuellen Ansatzes** entworfen werden kann — kein Rewrite der Backend-Logik, sondern eine Neugestaltung von UI-Struktur, Interaktion und Codequalität im Frontend.

**Scope:** Nur die WebApp (`frontend/`). Die Gerätefeedback-UI von ESPHome-Satelliten/HA-Voice-Geräten (PROJ-42, PROJ-49) ist nicht Teil dieses Dokuments.

**Quelle der Wahrheit für Feature-Status:** `features/old/INDEX.md` und `features/old/phase-1/INDEX.md`. Dieses Dokument fasst zusammen und zitiert Feature-IDs, ersetzt aber nicht die Specs selbst.

---

## 2. Aktueller Tech-Stack (Rahmenbedingung)

Der bestehende Stack ist **bindende Rahmenbedingung** für das Redesign — es geht um eine modernere Version des aktuellen Ansatzes, nicht um eine Stack-Migration:

| Bereich            | Technologie                                                                                                                                                                                       |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Framework          | Next.js 15 (App Router), **statischer Export** → Build wird nach `docker/compose/infra/nginx/html/` kopiert und dort als statische Dateien von nginx ausgeliefert (kein Node-Server zur Laufzeit) |
| UI-Runtime         | React 19, TypeScript 5.7                                                                                                                                                                          |
| Styling            | Tailwind CSS 3.4 + `tailwindcss-animate` + `@tailwindcss/typography`                                                                                                                              |
| Komponenten-Kit    | shadcn/ui (Radix-Primitives) — vollständiger Satz in `components/ui/` (~30 Dateien: Dialog, Sheet, Tabs, DropdownMenu, Toast/Sonner, Tooltip, Select, Accordion, AlertDialog, u.a.)               |
| Icons              | `lucide-react`                                                                                                                                                                                    |
| Markdown-Rendering | `react-markdown` + `remark-gfm` + `rehype-highlight` (Syntax-Highlighting: TS/JS/Python/YAML/JSON/Bash)                                                                                           |
| Formulare          | `react-hook-form` + `@hookform/resolvers`                                                                                                                                                         |
| Drag & Drop        | `@dnd-kit/{core,sortable,utilities,modifiers}`                                                                                                                                                    |
| Auth-Token         | `jose` (`decodeJwt`, rein clientseitig, keine Signaturprüfung im Browser)                                                                                                                         |
| State Management   | Kein Redux/Zustand — reine React Hooks + Context (`AuthContext`) + Custom Hooks                                                                                                                   |

Build & Deploy: `./scripts/deploy-frontend.sh` (Build + Kopie) gefolgt von `./scripts/sync-compose.sh` (Sync zum Produktionsserver) — beide Schritte sind zwingend erforderlich.

---

## 3. Architektur-Überblick

### Ordnerstruktur (`frontend/src/`)

```
app/                  # Next.js App Router: layout.tsx, page.tsx (Chat-Startseite), login/, settings/
components/
  Auth/               # AuthProvider, LoginForm, ProtectedRoute, ChangePasswordForm
  Chat/               # ChatWindow, MessageList, MessageRenderer (+ renderers/*), InputArea, VoiceOverlay
  Layout/             # AppShell.tsx — Sidebar + Main + Footer, Mobile/Desktop-Split, Vision/Text-Split-Screen
  Sidebar/            # Sidebar, ChatList, ChatSearch, NewChatButton, ServiceLinks, UserCard
  Settings/           # SettingsPage (Tabs) + Section-/Dialog-Komponenten je Tab
  Vision/             # VisionPanel, FlipCardGrid, FlipCard, ThumbnailImage
  ui/                 # shadcn-Primitives
hooks/                # useAuth, useChatSessions, useVisionPanel, useVoiceMode1/2, useDmsFolders, ...
services/             # api.ts, auth.ts, dms.ts, adminApi.ts, mailApi.ts, profileApi.ts, voiceApi.ts
lib/utils.ts          # cn()-Helper
```

### Auth-Fluss

JWT wird nach Login in `localStorage` (`alice_token`) abgelegt und als `Authorization: Bearer` an jeden Request angehängt. `AuthProvider` prüft beim App-Start zunächst clientseitig den Token-Ablauf (`jose.decodeJwt`), validiert danach gegen `GET /api/auth/validate` (prüft `is_active` + `must_change_password`). Bei 429 (Rate-Limit) wird der lokal dekodierte User als Fallback verwendet statt auszuloggen. `ProtectedRoute` schützt alle Seiteninhalte: Lade-Skeleton → Redirect bei fehlendem User → erzwungener Passwortwechsel bei `must_change_password` → Kindkomponenten.

### Streaming-Datenfluss

`services/api.ts` (`streamChat()`) öffnet einen `fetch()` + `ReadableStream` (bewusst **kein** `EventSource`, da custom `Authorization`-Header benötigt werden). SSE-Events werden zeilenweise geparst und nach `type` dispatcht: `token`, `thinking`, `tool_start`, `tool_end`, `vision_results`, `error`, `done` (Terminator `[DONE]`). `hooks/useChatSessions.ts` verwaltet den gesamten Message-Array-State (Rollen: `user | assistant | tool_call | thinking | error | status`) auf Basis dieser Events. Ein Legacy-Fallback (`/api/webhook/v1/chat/completions`, n8n `alice-chat-handler`) greift, wenn `NEXT_PUBLIC_STREAM_API_URL` nicht gesetzt ist.

Zusätzlich existieren zwei unabhängige WebSocket-Verbindungen für Sprache (siehe Abschnitt 4.5), getrennt vom SSE-Chat-Stream.

---

## 4. Funktionale Anforderungen nach Bereich

### 4.1 Auth & Session

*Quellen: PROJ-7 (Deployed), PROJ-9 (Deployed), PROJ-13 (Deployed), PROJ-34/36 (Deployed, RS256-Migration)*

- Login-Screen: Username + Passwort, Passwort-Sichtbarkeits-Toggle, generische Fehlermeldung bei ungültigen Daten, Button während Submit deaktiviert. Vollbild auf Mobile, zentrierte Card ab ≥768px.
- JWT-Claims: `user_id/username/role/exp`, 24h Gültigkeit, kein Refresh-Token.
- Auto-Login-Check beim App-Start, Redirect zu `/login` bei fehlendem/ungültigem/abgelaufenem Token.
- Logout-Button in der Sidebar (Fire-and-Forget Backend-Call).
- `/api/auth/login` ist separat vom Chat-Endpoint rate-limitiert (nginx).
- Alle Services erwarten Bearer-Token gegen `alice-auth` (RS256, Public-Key-Verifikation serverseitig) — keine sichtbaren Frontend-Änderungen durch RS256-Migration, aber bindender Vertrag.

### 4.2 Sidebar & Session-Verwaltung

*Quellen: PROJ-8 (Deployed), PROJ-12 (Deployed), PROJ-14 (Deployed), PROJ-38 (Deployed)*

- **Services-Bereich** unterhalb der Chat-Liste: Icon+Label-Links (n8n, Open WebUI, Home Assistant, HA Dev, Kanboard, Jupyter, Finance Upload), öffnen in neuem Tab, `aria-label`, ausgeblendet bei eingeklappter Sidebar, sichtbar im Mobile-Sheet (Tap schließt Drawer).
- **Umbenennen:** Inline-Edit (Stift → `Input`, Autofocus+Select), Enter/Blur commitet, Escape bricht ab, leerer String behält alten Titel, `maxLength=60`.
- **Kontextmenü:** `⋯`-Button → shadcn `DropdownMenu` (Umbenennen/Löschen), Löschen erfordert `AlertDialog`-Bestätigung, schließt bei Outside-Click/Escape/Auswahl, `stopPropagation` gegen versehentliche Session-Auswahl.
- **Truncation:** Lange Titel müssen `truncate` mit `min-w-0` auf allen Flex-Vorfahren (inkl. Override des Radix-`ScrollArea`-internen `display:table`-Wrappers), damit der `⋯`-Button nie aus dem sichtbaren Bereich gedrängt wird. Tooltip zeigt vollen Titel.
- Sessions/Messages liegen backend-seitig (`GET/PATCH/DELETE /api/webhook/alice/sessions...`), nicht in `localStorage`. Skeleton beim Laden, Empty-State ohne Nachrichten.
- 429-Antworten werden als Chat-Fehler-Bubble angezeigt, kein automatischer Logout.

### 4.3 Chat & Streaming

*Quellen: PROJ-31 (Deployed), PROJ-35 (Deployed, strukturprägend), PROJ-37 (In Review), PROJ-51 (Deployed)*

- Zentrale Spalte `max-w-[760px]`, responsive getestet bei 375/768/1440px, keine horizontale Scrollbar.
- Nachrichtenmodell: `MessageRole = user | assistant | tool_call | thinking | error | status`, rollenbasiertes Rendering über `MessageRenderer` + `renderers/*.tsx` (Dispatch-Pattern, erweiterbar durch neue Renderer-Datei je Rolle).
- Token-für-Token In-Place-Update der aktiven Assistant-Bubble (kein Full-Re-Render).
- Tool-Status-Chips (🔍/📄/💡/🧠) erscheinen/verschwinden bei `tool_start`/`tool_end`; ab PROJ-37 mit dynamischem Kontexttext (z. B. „Suche nach 'Rechnung Nov'…", ≤80 Zeichen) und Ergebnis-Zusammenfassung (z. B. „3 Dokumente gefunden").
- `thinking`-Events werden als eigene, einklappbare Nachrichtenform gerendert (Ollama `think:true`).
- Stop-Button ersetzt Send während des Streamings (`AbortController`), abgebrochene Nachricht erhält `[Abgebrochen]`-Tag, Eingabe wird wieder freigegeben.
- Markdown: Tabellen, Codeblöcke mit horizontalem Scroll, Syntax-Highlighting, Links mit `target=_blank rel=noopener noreferrer`. Feste Typografie-Regeln je Rolle (Schriftgröße/Farbe).
- Auto-Grow-Textarea (~6 Zeilen), Enter sendet/Shift+Enter neue Zeile.
- Auto-Scroll nur wenn Nutzer ≤150px vom unteren Rand entfernt ist oder bei Rollenwechsel — darf den Nutzer nie mitten im Lesen nach unten reißen.
- Auto-generierte Session-Titel (LLM, nach erster vollständiger Antwort, async, ≤60 Zeichen, überschreibt nie einen manuell vergebenen Titel); Sidebar zeigt „Neuer Chat" statt „Unbenannter Chat" während der Titel noch aussteht.
- Beim Session-Reload müssen Backend-`msg_type`-Werte korrekt auf Frontend-Rollen gemappt werden (`user_text/user_stt→user`, `llm_thinking→thinking`, `llm_response→assistant`, `ha_result/tool_result→tool_call`), damit Thinking-/Tool-Verlauf nach Reload erhalten bleibt.

### 4.4 Settings-Bereich

Tab-basiertes Layout: vertikale Tabs links (Desktop), horizontal scrollbare Tabs oben (Mobile). Tab-Sichtbarkeit rollenabhängig (`user.role`).

*Quellen: PROJ-15 (Deployed), PROJ-28 (Deployed), PROJ-26 (Deployed), PROJ-27 (Deployed), PROJ-43 (Deployed), PROJ-46 (Deployed), PROJ-52 (Deployed)*

| Tab              | Sichtbar für           | Kernanforderungen                                                                                                                                                                                                                                                                                                                                          |
| ---------------- | ---------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Mein Profil      | alle Rollen            | Erster/Standard-Tab. Name, Interessen (Tag-Input mit Chips, max. 20×30 Zeichen, Deduplizierung), Anrede/Sprache-Dropdowns; Rolle/Detailgrad read-only. Getrennte Formulare für Profil/E-Mail (MX-validiert)/Passwort. Bedingte „Stimmregistrierung"-Karte (`VoiceEnrollmentDialog`, 5 WAV-Samples über Browser-Mikrofon, Fortschritts-/Slot-Anzeige)       |
| DMS              | admin-only             | Tabelle (Pfad/Typ-Badge/Beschreibung/Enabled-Switch/Aktionen), Add/Edit-Dialoge, Löschen-Bestätigung, `suggested_type`-Dropdown. Drag-and-Drop-Sortierung via `@dnd-kit` (touch- und tastaturzugänglich), optimistisches Update mit Rollback-Toast bei Fehler                                                                                              |
| Nutzerverwaltung | admin-only             | User-Tabelle (Username/E-Mail/Rolle/Status/Erstellt), Row-Actions (OTP-Reset/Deaktivieren/Löschen), Create-User-Dialog, erzwungener Passwortwechsel beim First-Login (kein Skip). Eigenschutz: eigener Admin-Account kann nicht deaktiviert/gelöscht werden. Voice-Profile-Verwaltung (Liste/Löschen, Enrollment-Toggle je Nutzer, `SetCredentialsDialog`) |
| E-Mail           | alle Rollen            | Mailbox-Tabelle (Name/Host/Owner*-admin-only/Status-Badge/Shared-Users/Aktionen), Add/Edit-Dialog (Host, Port, User, Passwort write-only, SSL-Toggle, Sync-Intervall, Backfill-Startdatum), Inline-Verbindungstest, Multi-Select für User-Sharing. Passwort wird nie angezeigt                                                                             |
| Chatarchiv       | admin-only (403 sonst) | Paginierte Liste (20/Seite) aller Sessions aller Nutzer (30 Tage): Username, Startzeit, Typ-Badge (LLM/HA-only), Titel, Nachrichtenanzahl, Quelle. Zeilenklick → Detailansicht mit denselben Chat-Renderern wie im Hauptchat. Löschen aus Liste und Detail                                                                                                 |

### 4.5 Voice/Speech-Interface

*Quelle: PROJ-41 (Deployed), Backend-Vertrag PROJ-40*

Zwei sich gegenseitig ausschließende Modi in `InputArea`:

- **Modus 1 (Mikrofon-Button, STT→Text):** Toggle-Recording (roter Pulsring), streamt 250ms-MediaRecorder-Chunks sofort über WebSocket (`/ws/stt`), clientseitige Silence-Detection (AnalyserNode RMS, ~900ms), Zwischentranskript ersetzt Textarea-Inhalt live (eingefroren sobald Nutzer manuell tippt), sendet nie automatisch ab.
- **Modus 2 (Audio-Icon, volles Sprachgespräch):** Öffnet `VoiceOverlay` (shadcn Dialog) mit Zustandsanzeige („Höre zu…"/„Alice denkt…"/„Alice spricht…"), kontinuierliches Streaming über `/ws/voice`, Web-Audio-API-Playback-Queue für TTS-Chunks, Barge-in unterbricht laufende Wiedergabe, Session bleibt über mehrere Turns bestehen.
- JWT wird als `?token=`-Query-Parameter übergeben (Browser können bei WebSockets keine Header setzen).
- `getUserMedia`-Ablehnung → Toast + Deaktivierung bis Reload.
- Browser-Support: Chrome/Firefox Desktop, Chrome/Safari Mobile.

### 4.6 Vision/Flip-Card-Ergebnisse

*Quellen: PROJ-54 (Deployed), PROJ-55 (Deployed, primär Backend), PROJ-56 (Deployed, kein UI-Effekt außer neuer Dokumenttyp)*

- Split-Screen-Hauptbereich: `VisionPanel` (links, standardmäßig ausgeblendet) + Chat-Textbereich (rechts, standardmäßig volle Breite).
- Drei Anzeigemodi (`text`/`vision`/`split`), gesteuert über `useVisionPanel` und das SSE-Event `vision_results`. Automatischer Wechsel zu Vision-Only bei visueller Anfrage, automatisches Wiedereinblenden des Textbereichs bei reiner Text-Antwort während Vision-Modus aktiv ist.
- Desktop: Split 2/3 Vision : 1/3 Text. Mobile: Einzelansicht mit Wischgeste oder Toggle-Icon; 2 Spalten Hochformat, 4 Spalten Querformat.
- `FlipCard` mit drei Seiten: Vorderseite (Thumbnail + Metadaten + Icon-Leiste), Rückseite (Weaviate-Schema-Felder je Dokumenttyp), Zusammenfassung (KI-generierter Text) — CSS-3D-Transform, keine JS-Animationsbibliothek.
- Thumbnails werden per `fetch()` + Bearer-Header als Blob geladen (`createObjectURL`), da ein einfaches `<img src>` keine Auth-Header mitgeben kann. Quelle: `GET /api/dms/thumbnail/{uuid}` (immer ein Bild, Platzhalter bei Fehlen).
- Randfälle spezifiziert: 0 Treffer, 50+ Treffer, fehlendes Thumbnail.

---

## 5. Cross-cutting Anforderungen

### API-Oberfläche

| Route                             | Service (Port)                                       | Auth                                 |
| --------------------------------- | ---------------------------------------------------- | ------------------------------------ |
| `/api/auth/*`                     | alice-auth (8002/intern)                             | JWT-Ausstellung, `/login` öffentlich |
| `/api/stream/chat`                | alice-chat-stream (8003), SSE, `proxy_buffering off` | Bearer JWT                           |
| `/api/webhook/alice/*`            | n8n Session-API                                      | Bearer JWT                           |
| `/api/webhook/dms/*`              | n8n DMS-Folder-API                                   | Bearer JWT, admin                    |
| `/api/dms/thumbnail/{uuid}`       | alice-dms-thumbnailer (8004)                         | Bearer JWT                           |
| `/api/speech/ws/stt`, `/ws/voice` | alice-speech-gateway                                 | JWT via `?token=` Query              |

### Rollenmodell

`admin` / `user` / `guest` / `child` (DB: `alice.users.role`, granulares Permission-Schema in `alice.permissions_*` und `alice.role_templates`). Aktuell gate't das Frontend nur binär auf `role === "admin"` — siehe Abschnitt 6.

### Responsive Baseline

Getestete Breakpoints durchgängig: 375px / 768px / 1440px. Mobile: Sidebar als Sheet/Drawer, horizontal scrollbare oder kompakte Tab-Leisten. Desktop: feste 260px-Sidebar, vertikale Settings-Tabs.

### Darstellung & Sprache

Dark Mode ist aktuell Standard (Open-WebUI-inspirierte Palette: gray-900/800/700, blue-600/500 Akzent) — siehe Abschnitt 6 zur fehlenden Umschaltbarkeit. Alle UI-Texte sind hartkodiertes Deutsch, keine i18n-Schicht (konsistent mit Projektkonvention).

### Latenz-Zielwerte (README, relevant für gefühlte UI-Reaktionsfähigkeit)

| Szenario                     | Ziel       | Maximum  |
| ---------------------------- | ---------- | -------- |
| LLM erster Token (Streaming) | < 800 ms   | 1.500 ms |
| LLM vollständige Antwort     | < 2.000 ms | 4.000 ms |
| End-to-End (Text)            | < 3.000 ms | 5.000 ms |
| End-to-End (Sprache)         | < 2.000 ms | 3.500 ms |
| TTS erster Audio-Chunk       | < 3.000 ms | 5.000 ms |

---

## 6. Bekannte technische Schwachstellen (zu adressieren im Redesign)

1. **Dark Mode fest verdrahtet.** `app/layout.tsx` setzt `className="dark"` hart; `next-themes` ist installiert, aber ungenutzt. shadcn-Theme-Variablen existieren in `globals.css`/`tailwind.config.ts`, werden aber von den meisten Feature-Komponenten umgangen (literale Klassen wie `bg-gray-900`, `text-gray-400` statt `bg-background`, `text-muted-foreground`). → Ein Light-Mode/Theme-Switch im Redesign erfordert eine komponentenweite Umstellung auf die semantischen Tokens.
2. **Duplizierte Auth-Fetch-Logik.** Jede Service-Datei (`api.ts`, `dms.ts`, `adminApi.ts`, `mailApi.ts`, `profileApi.ts`, `voiceApi.ts`) implementiert ihr eigenes `authHeaders()`/401-Redirect-Paar. → Sollte in einen zentralen Fetch-Wrapper/Interceptor konsolidiert werden.
3. **Grobes Rollen-Gating.** Aktuell nur ein binärer `user.role === "admin"`-Check pro Komponente (`SettingsPage.tsx`, `MailboxSection.tsx`, `UserTable.tsx`, `MeinProfilSection.tsx`), obwohl das Backend ein granulares Rechtemodell mit `guest`/`child`-Templates und per-Domain/Dokumenttyp-Filtern bereithält (`alice.permissions_home_assistant`, `alice.permissions_dms`, `alice.role_templates`). Das Frontend konsumiert diese Granularität aktuell nicht. → Rollenbewusstes UI (z. B. eingeschränkte Ansichten für Gast/Kind) benötigt eine neue API-Oberfläche für effektive Permissions plus einen zugehörigen Hook — nicht nur Komponenten-Anpassungen.
4. **`SettingsPage.tsx` als Monolith.** ~5.000 Zeilen über ~20 Section-/Dialog-Dateien, alles Client-Components ohne Route-Splitting (keine `/settings/dms`, `/settings/users` Subrouten). → Kandidat für Aufteilung in eigene Routen/Code-Splitting.
5. **Zwei nahezu identische WebSocket-Voice-Implementierungen.** `useVoiceMode1.ts` (Push-to-Talk) und `useVoiceMode2.ts` (Vollduplex) enthalten fast identischen RMS-Silence-Detection-Code. → Gemeinsame Basis extrahierbar.
6. **Manuelle Flip-Card-Logik mit hartkodierten Metadaten-Maps.** `FlipCard.tsx` nutzt manuelle 3D-CSS-Transforms und dokumenttyp-spezifische deutsche Label-Maps (`DOC_META_LABELS`, `EXTRA_META_LABELS`, `HIDDEN_META_KEYS`) direkt in der Komponente. → Im Redesign bewusst erhalten oder sauber in eine datengetriebene Struktur überführen, insbesondere im Hinblick auf den neuen Dokumenttyp „Image" (PROJ-56).
7. **Kein zentraler State-Management-Layer.** `useChatSessions.ts` (~680 Zeilen) verwaltet den gesamten Message-State einer Session manuell über verschachtelte `setMessagesBySession`-Aufrufe mit Last-Item-Lookups. Funktional, aber fragil bei Erweiterung um neue SSE-Event-Typen.

---

## 7. Nicht-Ziele / Out of Scope

- Keine ESPHome-/HA-Voice-Satelliten-UI (siehe PROJ-42, PROJ-49) — reine Gerätefunktion, kein WebApp-Bestandteil.
- Keine Änderungen an Backend-APIs oder Datenmodellen — dieses Dokument beschreibt bestehende Verträge, schlägt aber keine neuen vor (Ausnahme: Abschnitt 6 benennt Stellen, an denen neue API-Oberflächen für ein rollenbewusstes Redesign nötig würden — das ist eine Beobachtung, keine Spezifikation).
- Keine Stack-Migration — Next.js/React/Tailwind/shadcn bleiben im Focus, es sei denn, die Anforderungen lassen sich mit einem anderen Ansatz einfacher und produktiver umsetzen.
- Keine Bewertung von PROJ-45, PROJ-50, PROJ-53, PROJ-58 (Roadmap-Einträge ohne Spec-Datei) — diese fließen erst nach `/write-spec` in ein Redesign-Grundlagendokument ein.

---

## 8. Offene Architektur-Fragen für dieses Redesign

Aus der `/write-spec`-Runde 2026-07-19 (PROJ-60–71) ergeben sich zwei Fragen, die technische Entscheidungen sind und daher bewusst **nicht** in einer Feature-Spec, sondern hier als Anforderung/offene Frage für `/architecture` festgehalten werden:

1. **Statischer Export vs. Node-Server.** Aktuell liefert nginx einen statischen Next.js-Export aus (Abschnitt 2, keine Laufzeit-Node-Instanz). Zukünftig soll Seiteninhalt bei Bedarf auch von Alice (LLM) generiert werden — mit einem rein statischen Export nur schwer umsetzbar. **Anforderung an die Architektur:** prüfen, ob ein Umstieg auf einen Node-Server (z. B. Next.js Standalone-Server-Modus) sinnvoll ist, und falls ja, die Migration inkl. Auswirkung auf `./scripts/deploy-frontend.sh`/nginx-Routing planen. Keine der Specs PROJ-60–71 setzt diese Entscheidung voraus (alle sind mit statischem Export umsetzbar); sie sollte aber vor oder parallel zu PROJ-68 (Route-Splitting) getroffen werden, da Route-Struktur und Rendering-Modus zusammenhängen.
2. **Stack-Migration.** Sollte sich im Rahmen der Architektur-Planung zu Punkt 1 oder zu einer der Specs zeigen, dass ein anderer Ansatz als Next.js/React/Tailwind/shadcn die Anforderungen deutlich einfacher oder produktiver umsetzen lässt, ist das laut ursprünglicher Anfrage explizit in Betracht zu ziehen (siehe Abschnitt 7 — Ausnahme vom „Keine Stack-Migration"-Grundsatz).

### Ergebnis (`/architecture`-Betrachtung, 2026-07-19, im Rahmen der PROJ-60–71-Architektur)

1. **Statischer Export vs. Node-Server → Kein Umstieg, Entscheidung vertagt.** Alle 12 Specs (PROJ-60–71) sind vollständig mit dem bestehenden statischen Export umsetzbar — das wurde in jeder einzelnen Architektur explizit geprüft und bestätigt (u. a. PROJ-60, PROJ-62, PROJ-68). Es gibt aktuell **keine konkrete, spezifizierte Anforderung**, die einen Node-Server braucht: „Alice generiert bei Bedarf Seiteninhalt" ist eine Zukunftsidee ohne Feature-Spec, keine Anforderung mit Akzeptanzkriterien. Ein Umstieg auf Node-Server-Betrieb (Standalone-Modus) hätte realen Preis — dauerhafter Node-Prozess statt reiner Datei-Auslieferung, Anpassung von `./scripts/deploy-frontend.sh` und dem nginx-Routing, zusätzliche Laufzeit-Angriffsfläche/Betriebslast — und würde damit der Projektprämisse „lokal, einfach, ein Node-Server mehr zum Betreiben" zuwiderlaufen, ohne dass aktuell ein Feature davon profitiert (Simplicity-First-Grundsatz aus CLAUDE.md: keine Architektur für hypothetische künftige Anforderungen). **Empfehlung:** Beim statischen Export bleiben. Die Frage wird erst dann neu aufgerollt, wenn „Alice generiert Seiteninhalt" über `/write-spec` zu einer konkreten Feature-Spec mit Akzeptanzkriterien wird — erst dann lässt sich seriös beurteilen, ob und welche Form von Server-Rendering sie tatsächlich braucht.
2. **Stack-Migration → Kein Wechsel.** Bei keiner der 12 Architekturen ergab sich ein Anwendungsfall, den Next.js/React/Tailwind/shadcn nicht sauber abbildet — im Gegenteil, mehrere Specs (PROJ-66/67/68/69/71) nutzen bewusst bereits vorhandene Stack-Bausteine (React-Hooks, `useReducer`, Next.js App-Router, dynamische Imports) statt neuer Abhängigkeiten. Kein Hinweis auf einen Stack-Wechsel-Bedarf, damit entfällt die Ausnahme aus Abschnitt 7 für diesen Feature-Umfang; „keine Stack-Migration" bleibt bindend.

Beide Ergebnisse sind **Momentaufnahmen für den PROJ-60–71-Umfang**, keine dauerhafte Festlegung für alle künftigen Redesign-Phasen — bei neuen, grundlegend anderen Anforderungen (z. B. der Alice-Seitengenerierung-Idee) sind sie erneut zu prüfen.

---

## 9. Phase 4 — neue und geänderte Oberflächen (Planung 2026-11-20)

Vereinbart in der Phasenplanung (`docs/PRD.md`). Details präzisiert die jeweilige Spec.

- **Wiki-Ansicht (PROJ-131):** nur lesen, kein Editor. Navigation über die Links zwischen Seiten, Suche, von jeder Aussage Sprung zur Quell-Markdown bzw. zum Original. Sichtbar für `haushalt` und `admin`, nicht für `guest`.
- **ETL-Status (PROJ-122):** nur `admin`. Verarbeitungsstand je Quelle und Stufe, Fehler mit Ursache, „erneut versuchen“, Fortschritt des Neuaufbaus.
- **Agent-Schritte im Chat (PROJ-135):** Plan und Tool-Aufrufe sind während und nach der Antwort nachvollziehbar (einklappbar). Antworten, für die die Cloud genutzt wurde, sind sichtbar gekennzeichnet; eine Freigabe für die Weitergabe lokaler Inhalte an die Cloud fragt der Chat pro Anfrage ab.
- **Sprache:** unverändert. Lange Recherchen liefern per Sprache eine Kurzantwort mit Hinweis, dass das vollständige Ergebnis in der WebApp steht.
- Alle neuen Texte laufen über die i18n-Schicht.

