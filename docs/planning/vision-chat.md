# Vision-Chat

Der HA-Voice-Ansatz spielt für das Nachfolgende keine Rolle. Der HA-Voice-Ansatz für die visuelle Ausgabe wird im PROJ-45 tiefer beleuchtet. Das Nachfolgende trifft nur auf die WebApp zu.

Wir haben aktuell die ersten Entwicklungen für einen Speech-Ansatz und einen Chat-Bot-Ansatz für die WebApp durchgeführt. Was mir fehlt ist ein Ansatz, bei dem die Ergebnisse **visuell** dargestellt werden. Mit **Visuell** meine ich nicht den textbasierten Ansatz des Chat-Bots sondern einen grafischen Ansatz bei denen die Einzel-Ergebnisse in einer Flip-Card dargestellt werden. Die Anfragen sollen weiterhin über das Eingabefeld oder per Speech erfolgen, aber die Eregbnisse, die zumeist aus einzelnen Ergebnissen stammen, sollen nicht als Text ausgegeben werden, sondern einzeln in den Flip-Cards. Solche Anfragen unterscheiden sich dadurch, dass in der Anfrage ein Textbestandteil vorhanden ist, der auf eine grafische Ausgabe hindeutet "... zeige mir ...". Es kann aber auch vom LLM erfolgen, wenn eine Anfrage zu mehreren Ergebnissen führt und das LLM z.B. die Nachfrage stellt, "Soll ich Dir die Ergebnisse grafisch darstellen?". Beispiele für Anfragen sind:

* Zeige mir alle Rechnungen der Telekom?
* Welche Aktienkäufe gab es im November 2025?
* Welche Abbuchungen für Gas gab es im Jahr 2024?
* Welche Bilder wurden in Tokyo gemacht?
...

Im Ergebnis führen diese Anfragen meistens zu einer **Liste von Einzeltreffern**, die als Text aufbereitet nicht sehr übersichtlich sind.

# Flip-Cards

Für jeden Einzeltreffer soll daher eine einzelne **Flip-Card** verwendet werden.

## Vorderseite

Auf der Vorderseite der Card soll ein **Vorschaubild** dargestellt werden. Als Kopfzeile sollte der Dateiname des zugehörigen Dokuments angegeben werden. Unterhalb des Bildes sollte Platz für Zusatzinformationen eingeplant werden und als Fußzeile eine Icon-Leiste, mit der Aktionen ausgelöst werden können. Hier am Beipiel des Summenzeichens, dass auf die Summary-Seite der Flip-Card wechselt. Ein Anklicken der Card außerhalb des Vorschaubildes und außerhalb der Icon-Leiste selbst sollte zur Rückseite wechseln.

Ein Beispiel für die Vorderseite der Card:

``` Text
┌────────────────────────────────┐
│ Original-Dateiname             │
│┌──────────────────────────────┐│
││                              ││
││                              ││
││        Vorschaubild          ││
││                              ││
││                              ││
││                              ││
││                              ││
│└──────────────────────────────┘│
│ Platz für zusätzliche          │
│ Informationen                  │
├────────────────────────────────┤
│ ∑- Iconleiste für Aktionen     │
└────────────────────────────────┘
```

## Rückseite

Auf der Rückseite der Card sollen relevante **Informationen aus den Weaviate Schemas** angezeigt werden, die sich an der Art des Dokumentes orientieren. Ein Anklicken der Card sollte wieder zur Vorderseite wechseln.

``` Text
┌────────────────────────────────┐
│                                │
│       Ergebniss aus den        │
│       Weaviate-Schemas         │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
└────────────────────────────────┘
```

## Summary

Auf der Summary-Seite solle die **Zusammenfassung** angezeigt werden, die vom LLM für weaviate erstellt wurde. Ein Anklicken der Card sollte wieder zur Vorderseite wechseln.

``` Text
┌────────────────────────────────┐
│                                │
│   AI-generated Summary         │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
│                                │
└────────────────────────────────┘
```

# Frontend

Das Frontend besteht zur Zeit aus dem **Chat-Fenster** mit einer **Eingabezeile** und **Voice-Icons** im Footer sowie der ein- und ausblendbaren **Seitenleiste**. Das Chat-Fenster soll um das **Flip-Card-Fenster** erweitert werden. Das immer dann eingeblendet werden soll, wenn Daten visuell dargestellt werden sollen. Dabei soll das Flip-Card-Fenster dass Chat-Fenster nicht ersetzen, sondern in eine **rechte Seitenleiste** verdrängen. Dabei sollte ein ein- und ausblenden, der rechten Sidebar möglich sein, so wie bei der vorhandenen linken Sidebar. Im Flip-Card-Fenster sollen die Eregbnisse in den Flip-Cards dargestellt werden, wobei die Flip-Cards in **Reihen und Spalten** dargestellt werden sollten. Die Eingabezeile und Voice-Icons sollen im Footer bestehen bleiben, um die weitere Kommunikation mit dem LLM zu ermöglichen, z.B. um die Anzahl der auszugebenen Flip-Cards durch weitere Filter zu verkleinern oder die Ergebnisse zu sortieren. Dafür sollen keine zusätzlichen Icons für Filter oder Sortierreihenfolgen verwendet werden, sondern die Kommunikation soll weiterhin über die Eingabezeile mit Sprachsteuerung möglich sein. Daher sollte auch das Chat-fenster nicht ersetzt werden, da hier die Kommunikation wie bisher in Textform erfolget. Das LLM kann damit weiterhin auf die bisherige Kommunikation zurückgreifen und der Nutzer den Thinking-Prozess bei Bedarf verfolgen. Im PC-Browser könnte die rechte Sidebar etwa doppelt so breit sein wie die linke Sidebar und die Flip-Cards sollten die restliche Fensterbreite verwenden können (responsive design). Im Smartphone sollte zwischen Flip-Card-Fenster und Chat-Fenster durch wischen gewechselt werden können. keine Darstellung von beiden Fenstern gleichzeitig.

Bei der Größe der Flip-Cards sollten wir uns an der Größe von **Youtube-Shorts** orientieren. Danach sollten wir bei Smartphones im Portrait-Modus zwei Cards neben und untereinander auf den Bildschirm bekommen, im Landscape-Modus wären es vier Cards nebeneinander. Auch im Landscape-Modus sollte die linke Sidebar standardmäßig ausgeblendet sein und nicht wie bisher eingeblendet. Die Vorschaubilder sollten sich in ihrer Größe an diesem Aufbau orientieren. Bei künftigen Bildern und Videos wäre hier zwar hoch- und querformat möglich. Auf Grund der Dokumente, zumeist im A4 Hochformat, sollte jedoch das Hochformat die Größe des Vorschaubildes bestimmen. Theoretisch wäre auch ein quadratisches Format für die Vorschaubilder möglich, bei Dokumenten beginnend mit dem Kopf und bei Bildern und Videos aus dem Zentrum generiert. Ichj bin hier für Vorschläge offen.

# Backend

Da das Frontend Dokumente als Vorschaubild darstellen soll, muss im Backend ein Vorschaubild für die verschiedenen Dokument-Arten erzeugt und gespeichert werden. Die Görße sollte sich am Aufbau der Cards orientieren. Das die Anzahl der Cards fest ist, sollte auch nur ein Vorschaubild in passender Größe erstellt werden. Die Generierung sollte im Rahmen der DMS-Aufbereitung erfolgen und könnte im alice-dms-scanner angestoßen werden (siehe features/phase-1/PROJ-16-dms-scanner-nas-infrastructure.md). Die Vorschaubilder könnten im Warm-Storage abgelegt werden, da dieser bisher kaum verwendet wird und Speicherplatz zur Verfügung hat. 

