"""
PROJ-106 — deterministic replies for lists tool results (incl. the combined
day query with the calendar).

Same reasoning as calendar_replies (PROJ-87 live tests): outcomes are phrased
here from the structured alice-lists result instead of by the LLM — short,
always consistent with what was stored, in the user's language (de / en).

compose() returns None for results the LLM must handle itself.
"""
from __future__ import annotations

from datetime import date, datetime

from . import calendar_replies as cr

QUESTION_STATUSES = {
    "confirm_delete", "confirm_delete_list", "ambiguous", "ambiguous_list", "needs_list_scope",
    "unknown_list", "confirm_past", "confirm_order", "confirm_duplicate",
}

_ERRORS = {
    "de": {
        "unknown_speaker": "Ich weiß nicht, wer spricht – ohne dich zu erkennen kann ich nur etwas auf die Einkaufsliste setzen.",
        "forbidden": "Deine Rolle hat keinen Zugriff auf diese Aktion.",
        "forbidden_child_remove": "Von der Einkaufsliste entfernen darfst du nicht – abhaken geht aber.",
        "admin_only": "Das darf nur ein Admin.",
        "not_list_owner": "Gemeinsame Listen dürfen nur ein Admin und die Person, die sie angelegt hat, umbenennen oder löschen.",
        "no_shopping_list": "Es ist gerade keine Einkaufsliste festgelegt – das kann ein Admin erledigen.",
        "duplicate_list_name": "Eine Liste mit diesem Namen gibt es schon.",
        "reserved_name": "Dieser Name ist der Einkaufsliste vorbehalten – bitte nimm einen anderen.",
        "private_not_shopping": "Eine private Liste kann nicht die Einkaufsliste sein.",
        "item_gone": "Den Eintrag gibt es nicht mehr, ich habe nichts gelöscht.",
        "item_changed": "Der Eintrag wurde inzwischen geändert, deshalb habe ich ihn nicht gelöscht.",
        "list_gone": "Die Liste gibt es nicht mehr.",
        "ticket_expired": "Die Löschanfrage ist abgelaufen, ich habe nichts gelöscht.",
        "ticket_unknown": "Die Löschanfrage ist abgelaufen, ich habe nichts gelöscht.",
        "ticket_wrong_owner": "Ich habe nichts gelöscht.",
        "not_confirmed": "Okay, ich habe nichts gelöscht.",
        "no_session": "Das geht nur innerhalb eines Gesprächs.",
        "lists_disabled": "Listen sind für dich nicht verfügbar.",
        "lists_unavailable": "Die Listen sind gerade nicht erreichbar. Bitte versuch es später noch einmal.",
        "timeout": "Die Listen haben nicht rechtzeitig geantwortet. Bitte versuch es später noch einmal.",
        "internal_error": "Da ist etwas schiefgegangen, es wurde nichts geändert. Bitte versuch es später noch einmal.",
    },
    "en": {
        "unknown_speaker": "I don't know who is speaking – without recognising you I can only add things to the shopping list.",
        "forbidden": "Your role has no access to that action.",
        "forbidden_child_remove": "You may not remove things from the shopping list – but you can tick them off.",
        "admin_only": "Only an admin may do that.",
        "not_list_owner": "Shared lists can only be renamed or deleted by an admin or the person who created them.",
        "no_shopping_list": "There is no shopping list set right now – an admin can set one.",
        "duplicate_list_name": "A list with that name already exists.",
        "reserved_name": "That name is reserved for the shopping list – please pick another one.",
        "private_not_shopping": "A private list can't be the shopping list.",
        "item_gone": "That entry no longer exists, nothing was deleted.",
        "item_changed": "The entry has changed in the meantime, so I did not delete it.",
        "list_gone": "That list no longer exists.",
        "ticket_expired": "The delete request has expired, nothing was deleted.",
        "ticket_unknown": "The delete request has expired, nothing was deleted.",
        "ticket_wrong_owner": "Nothing was deleted.",
        "not_confirmed": "Okay, nothing was deleted.",
        "no_session": "That only works within a conversation.",
        "lists_disabled": "Lists are not available for you.",
        "lists_unavailable": "The lists are not reachable right now. Please try again later.",
        "timeout": "The lists did not answer in time. Please try again later.",
        "internal_error": "Something went wrong, nothing was changed. Please try again later.",
    },
}

_LLM_HANDLED_ERRORS = {"invalid_input", "await_user_answer", "ticket_same_turn"}


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------
def _q(text: str, lang: str) -> str:
    return f"„{text}“" if lang == "de" else f"“{text}”"


def _list_name(lst: dict | None, lang: str, case: str = "dat") -> str:
    """'der Einkaufsliste' / 'die Einkaufsliste' / 'der Liste „Baumarkt“'."""
    lst = lst or {}
    name = lst.get("name") or ""
    if lang == "en":
        return "the shopping list" if lst.get("shopping") else f"the list {_q(name, lang)}"
    art = {"dat": "der", "acc": "die", "nom": "die"}[case]
    if lst.get("shopping"):
        return f"{art} Einkaufsliste"
    return f"{art} Liste {_q(name, lang)}"


def _when(w: dict | None, lang: str, voice: bool, today: date) -> str:
    if not w:
        return ""
    d = cr._parse_day(w.get("date"))
    day = cr._day(d, lang, today) if d else ""
    t = cr._time(w.get("time"), lang, voice)
    if lang == "de":
        return " ".join(x for x in (day, f"um {t}" if t else "") if x)
    return " ".join(x for x in (day, f"at {t}" if t else "") if x)


def _details(item: dict, lang: str, voice: bool, today: date) -> list[str]:
    out = []
    if item.get("due"):
        out.append(("fällig " if lang == "de" else "due ") + _when(item["due"], lang, voice, today))
    if item.get("deadline"):
        out.append(("Frist bis " if lang == "de" else "deadline ") +
                   _when(item["deadline"], lang, voice, today).removeprefix("am ").removeprefix("on "))
    if item.get("priority") == "high":
        out.append("wichtig" if lang == "de" else "important")
    elif item.get("priority") == "low":
        out.append("unwichtig" if lang == "de" else "low priority")
    return out


def _item_text(item: dict, lang: str, voice: bool, today: date, quote: bool = True,
               show_list: bool = True) -> str:
    text = _q(item.get("title") or "", lang) if quote else (item.get("title") or "")
    extra = _details(item, lang, voice, today)
    if item.get("overdue"):
        extra.insert(0, "überfällig" if lang == "de" else "overdue")
    if show_list and item.get("list"):
        extra.append((f"auf {item['list']}" if lang == "de" else f"on {item['list']}"))
    if extra:
        text += f" ({', '.join(extra)})" if not voice else ", " + ", ".join(extra)
    return text


def _titles(items: list, lang: str, quote: bool = True) -> list[str]:
    out = []
    for i in items:
        t = i.get("title") if isinstance(i, dict) else str(i)
        out.append(_q(t, lang) if quote else t)
    return out


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


# ---------------------------------------------------------------------------
# Per-status replies
# ---------------------------------------------------------------------------
def _added(r: dict, lang: str, voice: bool, today: date) -> str:
    lst = r.get("list") or {}
    shopping = lst.get("shopping")
    items, reopened = r.get("items") or [], r.get("reopened") or []
    parts = []
    if r.get("list_created"):
        parts.append(f"Ich habe {_list_name(lst, lang, 'acc')} angelegt." if lang == "de"
                     else f"I created {_list_name(lst, lang)}.")
    if items:
        names = cr._join(_titles(items, lang, quote=not shopping), lang)
        details = _details(items[0], lang, voice, today)
        tail = (", " + ", ".join(details)) if details else ""
        if lang == "de":
            parts.append(f"Ich habe {names} auf {_list_name(lst, lang, 'acc')} gesetzt{tail}.")
        else:
            parts.append(f"I added {names} to {_list_name(lst, lang)}{tail}.")
    if reopened:
        names = cr._join(_titles(reopened, lang, quote=not shopping), lang)
        parts.append(f"{_cap(names)} stand schon abgehakt drauf, ich habe es wieder geöffnet." if lang == "de"
                     else f"{_cap(names)} was already ticked off, I reopened it.")
    return " ".join(parts) or ("Es wurde nichts eingetragen." if lang == "de" else "Nothing was added.")


def _missing(names: list[str], lang: str) -> str:
    if not names:
        return ""
    joined = cr._join(_titles(names, lang), lang)
    return (f" {joined} habe ich nicht gefunden." if lang == "de" else f" I couldn't find {joined}.")


def _done_change(r: dict, lang: str, done: bool) -> str:
    items = r.get("items") or r.get("done_items") or []
    already = r.get("already") or []
    parts = []
    if items:
        names = cr._join(_titles(items, lang), lang)
        if lang == "de":
            parts.append(f"Ich habe {names} {'abgehakt' if done else 'wieder geöffnet'}.")
        else:
            parts.append(f"I {'ticked off' if done else 'reopened'} {names}.")
    if already:
        names = cr._join(_titles(already, lang), lang)
        if lang == "de":
            verb = "war" if len(already) == 1 else "waren"
            parts.append(f"{_cap(names)} {verb} {'schon erledigt' if done else 'noch offen'}.")
        else:
            parts.append(f"{_cap(names)} {'was' if len(already) == 1 else 'were'} "
                         f"{'already done' if done else 'still open'}.")
    text = " ".join(parts) + _missing(r.get("not_found") or [], lang)
    return text.strip() or ("Ich habe nichts gefunden." if lang == "de" else "I found nothing.")


def _removed(r: dict, lang: str) -> str:
    items = r.get("items") or r.get("removed") or []
    text = ""
    if items:
        names = cr._join(_titles(items, lang, quote=False), lang)
        text = f"Ich habe {names} entfernt." if lang == "de" else f"I removed {names}."
    return (text + _missing(r.get("not_found") or [], lang)).strip() or \
        ("Ich habe nichts gefunden." if lang == "de" else "I found nothing.")


def _ambiguous(r: dict, lang: str, voice: bool, today: date) -> str:
    prefix = ""
    if r.get("done_items") or r.get("already"):
        prefix = _done_change(r, lang, r.get("action") != "reopen") + " "
    elif r.get("removed"):
        prefix = _removed({"items": r["removed"]}, lang) + " "
    cands = r.get("candidates") or []
    if voice:
        cands = cands[:3]
    opts = [_item_text(c, lang, voice, today) for c in cands]
    if lang == "de":
        return prefix + f"Welchen Eintrag meinst du: {cr._join(opts, lang, 'oder')}?"
    return prefix + f"Which entry do you mean: {cr._join(opts, lang, 'or')}?"


def _updated(r: dict, lang: str, voice: bool, today: date) -> str:
    item = dict(r.get("item") or {})
    lst = r.get("list") or {}
    item.pop("list", None)
    details = _details(item, lang, voice, today)
    tail = (", " + ", ".join(details)) if details else ""
    if lang == "de":
        return f"Geändert: {_q(item.get('title') or '', lang)} auf {_list_name(lst, lang)}{tail}."
    return f"Changed: {_q(item.get('title') or '', lang)} on {_list_name(lst, lang)}{tail}."


def _confirm_delete(r: dict, lang: str) -> str:
    item = r.get("item") or {}
    prefix = (_removed({"items": r["removed"]}, lang) + " ") if r.get("removed") else ""
    deferred = r.get("deferred") or []
    if lang == "de":
        text = f"Soll ich {_q(item.get('title') or '', lang)} von {_list_name(r.get('list'), lang)} löschen?"
        if deferred:
            text += f" {_cap(cr._join(_titles(deferred, lang), lang))} lösche ich nur einzeln, sag mir danach Bescheid."
    else:
        text = f"Shall I delete {_q(item.get('title') or '', lang)} from {_list_name(r.get('list'), lang)}?"
        if deferred:
            text += f" I only delete {cr._join(_titles(deferred, lang), lang)} one at a time, tell me afterwards."
    return prefix + text


def _confirm_delete_list(r: dict, lang: str) -> str:
    lst = r.get("list") or {}
    n = int(r.get("count") or 0)
    if lang == "de":
        count = "ohne Einträge" if n == 0 else f"mit {n} Eintr{'ag' if n == 1 else 'ägen'}"
        if lst.get("shopping"):
            return (f"{_q(lst.get('name') or '', lang)} ist die Einkaufsliste. Soll ich sie {count} wirklich "
                    "löschen?")
        return f"Soll ich die Liste {_q(lst.get('name') or '', lang)} {count} löschen?"
    count = "with no entries" if n == 0 else f"with {n} entr{'y' if n == 1 else 'ies'}"
    if lst.get("shopping"):
        return f"{_q(lst.get('name') or '', lang)} is the shopping list. Really delete it {count}?"
    return f"Shall I delete the list {_q(lst.get('name') or '', lang)} {count}?"


def _deleted(r: dict, lang: str) -> str:
    if r.get("kind") == "list":
        name = _q((r.get("list") or {}).get("name") or "", lang)
        return f"Ich habe die Liste {name} gelöscht." if lang == "de" else f"I deleted the list {name}."
    title = _q((r.get("item") or {}).get("title") or "", lang)
    return f"Ich habe {title} gelöscht." if lang == "de" else f"I deleted {title}."


def _confirm_past(r: dict, lang: str, voice: bool, today: date) -> str:
    item = r.get("item") or {}
    w = item.get(r.get("field") or "due") or item.get("due") or item.get("deadline")
    when = _when(w, lang, voice, today)
    if lang == "de":
        return f"Das Datum ({when}) liegt in der Vergangenheit. Soll ich {_q(item.get('title') or '', lang)} trotzdem so eintragen?"
    return f"That date ({when}) is in the past. Shall I save {_q(item.get('title') or '', lang)} like that anyway?"


def _confirm_order(r: dict, lang: str, voice: bool, today: date) -> str:
    item = r.get("item") or {}
    due, deadline = _when(item.get("due"), lang, voice, today), _when(item.get("deadline"), lang, voice, today)
    if lang == "de":
        return (f"Die Frist ({deadline}) liegt vor der Fälligkeit ({due}). Soll ich das trotzdem so eintragen "
                "oder meinst du ein anderes Datum?")
    return (f"The deadline ({deadline}) is before the due date ({due}). Save it like that anyway, "
            "or did you mean another date?")


def _confirm_duplicate(r: dict, lang: str) -> str:
    names = cr._join(_titles(r.get("titles") or [], lang), lang)
    one = len(r.get("titles") or []) == 1
    if lang == "de":
        return (f"{_cap(names)} {'steht' if one else 'stehen'} schon offen auf {_list_name(r.get('list'), lang, 'dat')}. "
                f"Soll ich {'es' if one else 'sie'} trotzdem noch einmal eintragen?")
    return f"{_cap(names)} {'is' if one else 'are'} already open on {_list_name(r.get('list'), lang)}. Add again anyway?"


def _overview(r: dict, lang: str, voice: bool) -> str:
    lists = r.get("lists") or []
    if not lists:
        return "Du hast keine Listen." if lang == "de" else "You have no lists."

    def one(l: dict) -> str:
        tags = []
        if l.get("default"):
            tags.append("Standard" if lang == "de" else "default")
        if l.get("shopping"):
            tags.append("Einkaufsliste" if lang == "de" else "shopping list")
        elif l.get("shared"):
            tags.append("gemeinsam" if lang == "de" else "shared")
        n = int(l.get("open") or 0)
        tags.append(f"{n} offen" if lang == "de" else f"{n} open")
        return f"{l.get('name')} ({', '.join(tags)})"

    lead = "Deine Listen" if lang == "de" else "Your lists"
    if voice or len(lists) <= 3:
        return f"{lead}: {cr._join([one(l) for l in lists], lang)}."
    return "\n".join([f"{lead}:"] + [f"- {one(l)}" for l in lists])


_RANGE_LEAD = {
    "de": {"today": "heute", "tomorrow": "morgen", "day_after_tomorrow": "übermorgen",
           "this_week": "diese Woche", "next_week": "nächste Woche"},
    "en": {"today": "today", "tomorrow": "tomorrow", "day_after_tomorrow": "the day after tomorrow",
           "this_week": "this week", "next_week": "next week"},
}


def _range_text(rng: dict, lang: str, today: date) -> str:
    kw = rng.get("keyword")
    if kw in _RANGE_LEAD[lang]:
        return _RANGE_LEAD[lang][kw]
    if kw == "date":
        return cr._range_phrase(rng, lang, today)
    return ""


def _render_items(lead: str, items: list[dict], r: dict, lang: str, voice: bool, today: date,
                  quote: bool) -> str:
    remaining = int(r.get("remaining") or 0)
    texts = [_item_text(i, lang, voice, today, quote=quote) for i in items]
    if voice or len(items) <= 3:
        text = f"{lead}: {cr._join(texts, lang)}"
        if remaining:
            text += f" und {remaining} weitere" if lang == "de" else f" and {remaining} more"
        return text + "."
    lines = [f"{lead}:"] + [f"- {t}" for t in texts]
    if remaining:
        lines.append(f"… und {remaining} weitere." if lang == "de" else f"… and {remaining} more.")
    if r.get("truncated"):
        lines.append("(Liste gekürzt)" if lang == "de" else "(list shortened)")
    return "\n".join(lines)


def _query(r: dict, lang: str, voice: bool, today: date) -> str:
    lst = r.get("list")
    items = r.get("items") or []
    total = int(r.get("total") or 0)
    mode = r.get("mode")
    rng = r.get("range") or {}
    kw = rng.get("keyword")
    shopping = bool(lst and lst.get("shopping"))

    if mode == "search":
        what = _q(r.get("search") or "", lang)
        where = _list_name(lst, lang) if lst else ("deinen Listen" if lang == "de" else "your lists")
        if lang == "de":
            return f"Ja, {what} steht auf {where}." if r.get("found") else f"Nein, {what} steht nicht auf {where}."
        return f"Yes, {what} is on {where}." if r.get("found") else f"No, {what} is not on {where}."

    if mode == "count":
        where = _list_name(lst, lang) if lst else ("deinen Listen" if lang == "de" else "your lists")
        if lang == "de":
            if total == 0:
                return f"Auf {where} stehen keine offenen Einträge."
            return f"Auf {where} {'steht' if total == 1 else 'stehen'} {total} offene{'r' if total == 1 else ''} Eintr{'ag' if total == 1 else 'äge'}."
        return f"{_cap(where)} has {total} open entr{'y' if total == 1 else 'ies'}."

    if mode == "done":
        when = "diese Woche" if kw == "this_week" else ("heute" if kw == "today" else "in den letzten 30 Tagen")
        if lang == "en":
            when = {"this_week": "this week", "today": "today"}.get(kw, "in the last 30 days")
        if not items:
            if lst:
                return (f"Von {_list_name(lst, lang)} wurde {when} nichts abgehakt." if lang == "de"
                        else f"Nothing was ticked off {_list_name(lst, lang)} {when}.")
            return f"Du hast {when} nichts erledigt." if lang == "de" else f"You completed nothing {when}."
        lead = (f"Von {_list_name(lst, lang)} {when} abgehakt" if lst else f"{_cap(when)} erledigt") \
            if lang == "de" else (f"Ticked off {_list_name(lst, lang)} {when}" if lst else f"Completed {when}")
        return _render_items(lead, items, r, lang, voice, today, quote=not shopping)

    span = _range_text(rng, lang, today)
    deadlines = r.get("only_deadlines")
    if not items:
        if kw == "overdue":
            return "Es ist nichts überfällig." if lang == "de" else "Nothing is overdue."
        if deadlines:
            if lang == "de":
                return f"{_cap(span)} hast du keine Fristen." if span else "Du hast keine Fristen."
            return f"You have no deadlines{' ' + span if span else ''}."
        if span:
            return f"{_cap(span)} steht nichts an." if lang == "de" else f"Nothing is due {span}."
        if lst:
            return (f"{_cap(_list_name(lst, lang, 'nom'))} ist leer." if lang == "de"
                    else f"{_cap(_list_name(lst, lang))} is empty.")
        return "Du hast keine offenen Einträge." if lang == "de" else "You have no open entries."

    if lang == "de":
        if kw == "overdue":
            lead = "Überfällig"
        elif deadlines:
            lead = f"Fristen {span}".strip()
        elif span:
            lead = f"{_cap(span)} fällig"
        elif lst:
            lead = f"Auf {_list_name(lst, lang)} {'steht' if total == 1 else 'stehen'}"
        else:
            lead = "Deine offenen Einträge"
    else:
        if kw == "overdue":
            lead = "Overdue"
        elif deadlines:
            lead = f"Deadlines {span}".strip()
        elif span:
            lead = f"Due {span}"
        elif lst:
            lead = f"On {_list_name(lst, lang)}"
        else:
            lead = "Your open entries"
    return _render_items(lead, items, r, lang, voice, today, quote=not shopping)


def _cleaned(r: dict, lang: str) -> str:
    n = int(r.get("count") or 0)
    where = _list_name(r.get("list"), lang)
    if lang == "de":
        if n == 0:
            return f"Auf {where} gab es keine erledigten Einträge."
        return f"Ich habe {n} erledigte{'n' if n == 1 else ''} Eintr{'ag' if n == 1 else 'äge'} von {where} entfernt."
    if n == 0:
        return f"There were no completed entries on {where}."
    return f"I removed {n} completed entr{'y' if n == 1 else 'ies'} from {where}."


def _manage(r: dict, lang: str) -> str:
    status = r.get("status")
    lst = r.get("list") or {}
    name = _q(lst.get("name") or "", lang)
    de = lang == "de"
    if status == "list_created":
        kind = ("gemeinsame Liste" if de else "shared list") if lst.get("shared") else ("Liste" if de else "list")
        return f"Ich habe die {kind} {name} angelegt." if de else f"I created the {kind} {name}."
    if status == "list_renamed":
        old = _q(r.get("old") or "", lang)
        return f"Ich habe die Liste {old} in {name} umbenannt." if de else f"I renamed the list {old} to {name}."
    if status == "default_set":
        return f"{name} ist jetzt deine Standardliste." if de else f"{name} is now your default list."
    if r.get("unchanged"):
        return f"{name} ist bereits die Einkaufsliste." if de else f"{name} already is the shopping list."
    prev = r.get("previous")
    if de:
        return f"{name} ist jetzt die Einkaufsliste" + (f" statt {_q(prev, lang)}." if prev else ".")
    return f"{name} is now the shopping list" + (f" instead of {_q(prev, lang)}." if prev else ".")


# ---------------------------------------------------------------------------
# Combined day query (calendar + lists)
# ---------------------------------------------------------------------------
_CAL_SILENT = {"no_active_calendar", "forbidden", "unknown_speaker", "calendar_disabled"}
_LISTS_SILENT = {"forbidden", "unknown_speaker", "lists_disabled"}


def _agenda(r: dict, lang: str, voice: bool, today: date) -> str:
    cal, lists = r.get("calendar"), r.get("lists") or {}
    events = (cal or {}).get("events") or [] if cal and not cal.get("error") else []
    cal_total = int((cal or {}).get("total") or len(events)) if events else 0
    items = lists.get("items") or [] if not lists.get("error") else []
    items_total = int(lists.get("total") or len(items)) if items else 0

    if lists.get("error") and (cal is None or cal.get("error")):
        # Neither part usable: the lists reason says why (e.g. unknown speaker).
        return _ERRORS[lang].get(lists["error"], _ERRORS[lang]["lists_unavailable"])

    rng = (cal or {}).get("range") or lists.get("range") or {}
    span = _range_text({**rng, "keyword": (lists.get("range") or {}).get("keyword") or rng.get("keyword")},
                       lang, today) or cr._range_phrase(rng, lang, today)
    hint = ""
    if cal and cal.get("error") and cal["error"] not in _CAL_SILENT:
        hint = (" Der Kalender war nicht erreichbar." if lang == "de" else " The calendar could not be read.")
    elif cal and cal.get("warnings"):
        hint = cr._warnings(cal, lang)
    if lists.get("error") and lists["error"] not in _LISTS_SILENT:
        # QA BUG-4: never present a day as complete when the entries are missing.
        hint += (" Die Aufgaben waren nicht abrufbar." if lang == "de" else " The entries could not be read.")

    if not events and not items:
        return (f"{_cap(span)} steht nichts an." if lang == "de" else f"Nothing is planned {span}.") + hint

    limit = 5 if voice else 50
    shown_events = events[:limit]
    shown_items = items[:max(0, limit - len(shown_events))]
    remaining = (cal_total - len(shown_events)) + (items_total - len(shown_items))
    multi_day = rng.get("from") != rng.get("to")

    parts = []
    if shown_events:
        evs = []
        for e in shown_events:
            when = cr._when(e, lang, voice, today, with_day=multi_day)
            evs.append(f"{when} {e.get('title') or ''}".strip() if lang == "de" else f"{e.get('title') or ''} {when}".strip())
        n = cal_total
        if lang == "de":
            parts.append(f"{_cap(span)} hast du {n} Termin{'e' if n != 1 else ''}: {cr._join(evs, lang)}.")
        else:
            parts.append(f"{_cap(span)} you have {n} event{'s' if n != 1 else ''}: {cr._join(evs, lang)}.")
    if shown_items:
        texts = [_item_text(i, lang, voice, today) for i in shown_items]
        lead = ("Fällig" if lang == "de" else "Due") if shown_events else \
            (f"{_cap(span)} fällig" if lang == "de" else f"Due {span}")
        parts.append(f"{lead}: {cr._join(texts, lang)}.")
    elif shown_events and not items and not lists.get("error"):
        parts.append("Fällige Aufgaben gibt es keine." if lang == "de" else "No entries are due.")
    if remaining > 0:
        parts.append(f"Und {remaining} weitere." if lang == "de" else f"And {remaining} more.")
    return " ".join(parts) + hint


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def compose(result: dict, lang: str, channel: str, now: datetime | None = None) -> str | None:
    """Reply text for a lists tool result, or None if the LLM must handle it."""
    if not isinstance(result, dict):
        return None
    lang = cr.language(lang)
    voice = channel == "voice"
    today = (now or datetime.now(cr.LOCAL_TZ)).astimezone(cr.LOCAL_TZ).date()

    err = result.get("error")
    if err:
        if err in _LLM_HANDLED_ERRORS:
            return None
        return _ERRORS[lang].get(err, _ERRORS[lang]["internal_error"])

    status = result.get("status")
    if status == "added":
        return _added(result, lang, voice, today)
    if status in ("completed", "reopened"):
        return _done_change(result, lang, status == "completed")
    if status == "removed":
        return _removed(result, lang)
    if status == "updated":
        return _updated(result, lang, voice, today)
    if status == "ambiguous":
        return _ambiguous(result, lang, voice, today)
    if status == "not_found":
        q = _q(result.get("query") or "", lang)
        return (f"Ich habe keinen Eintrag {q} gefunden." if lang == "de" else f"I couldn't find an entry {q}.") \
            if result.get("query") else ("Den Eintrag habe ich nicht gefunden." if lang == "de"
                                         else "I couldn't find that entry.")
    if status == "confirm_delete":
        return _confirm_delete(result, lang)
    if status == "confirm_delete_list":
        return _confirm_delete_list(result, lang)
    if status == "deleted":
        return _deleted(result, lang)
    if status == "confirm_past":
        return _confirm_past(result, lang, voice, today)
    if status == "confirm_order":
        return _confirm_order(result, lang, voice, today)
    if status == "confirm_duplicate":
        return _confirm_duplicate(result, lang)
    if status == "unknown_list":
        name = _q(result.get("name") or "", lang)
        return (f"Die Liste {name} gibt es nicht. Soll ich sie anlegen?" if lang == "de"
                else f"There is no list {name}. Shall I create it?")
    if status == "list_not_found":
        name = _q(result.get("name") or "", lang)
        return f"Die Liste {name} gibt es nicht." if lang == "de" else f"There is no list {name}."
    if status == "ambiguous_list":
        opts = [_q(o, lang) for o in result.get("options") or []]
        return (f"Welche Liste meinst du: {cr._join(opts, lang, 'oder')}?" if lang == "de"
                else f"Which list do you mean: {cr._join(opts, lang, 'or')}?")
    if status == "needs_list_scope":
        name = _q(result.get("name") or "", lang)
        return (f"Meinst du deine private oder die gemeinsame Liste {name}?" if lang == "de"
                else f"Do you mean your private or the shared list {name}?")
    if status == "ok":
        return _query(result, lang, voice, today)
    if status == "cleaned":
        return _cleaned(result, lang)
    if status in ("list_created", "list_renamed", "default_set", "shopping_set"):
        return _manage(result, lang)
    if status == "lists":
        return _overview(result, lang, voice)
    if status == "agenda":
        return _agenda(result, lang, voice, today)
    return None


def is_terminal(result: dict) -> bool:
    """Finished outcome (no question pending) — the voice session may end."""
    if result.get("error"):
        return result["error"] not in _LLM_HANDLED_ERRORS
    return result.get("status") not in QUESTION_STATUSES
