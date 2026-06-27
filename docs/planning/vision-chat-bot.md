# Vision-Chat-Bot

Wir haben aktuell die ersten Entwicklungen für einen Speech-Ansatz und einen Chat-Bot-Ansatz durchgeführt. Was mir fehlt ist ein Ansatz, bei dem die Ergebnisse **visuell** dargestellt werden. Mit **Visuell** meine ich nicht den textbasierten Ansatz des Chat-Bots sondern einen grafischen Ansatz bei denen die Einzel-Ergebnisse in einer Flip-Card dargestellt werden. Die Anfragen sollen weiterhin über das Eingabefeld oder per Speech erfolgen, aber die Eregbnisse, die zumeist aus einzelnen Ergebnissen stammen, sollen nicht als Text ausgegeben werden, sondern einzeln in den Flip-Cards. Solche Anfragen unterscheiden sich dadurch, dass in der Anfrage ein Textbestandteil vorhanden ist, der auf eine grafische Ausgabe hindeutet "... zeige mir ...". Es kann aber auch vom LLM erfolgen, wenn eine Anfrage zu mehreren Ergebnissen führt und das LLM z.B. die Nachfrage stellt, "Soll ich Dir die Ergebnisse grafisch darstellen?". Beispiele für Anfragen sind:

* Zeige mir alle Rechnungen der Telekom?
* Welche Aktienkäufe gab es im November 2025?
* Welche Abbuchungen für Gas gab es im Jahr 2024?
* Welche Bilder wurden in Tokyo gemacht?
...

Im Ergebnis führen diese Anfragen meistens zu einer Liste von Einzeltreffern, die als Text aufbereitet nicht sehr übersichtlich sind.

# Flip-Cards

Für jeden Einzeltreffer soll daher eine einzelne Flip-Card verwendet werden.

## Vorderseite

┌
┐
└
┘
├
┤
┼
│
─
▶
◀
▲
▼

## Rückseite


