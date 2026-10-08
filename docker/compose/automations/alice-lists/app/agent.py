"""
Lists agent logic (PROJ-106): what the chat tools do.

Tool results are dicts handed to alice-chat-stream, which phrases the reply
from a template:
  - real failures carry an "error" code plus a German "message" hint
  - questions back to the user carry a question "status" (see QUESTION_STATUSES)
  - successes carry a status and ONLY what was actually stored
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import db, tickets
from . import textutil as tx
from . import timeutil as tu

logger = logging.getLogger("alice-lists.agent")

VOICE_LIMIT = 5
CHAT_LIMIT = 50
MAX_CANDIDATES = 6
MAX_TITLE = 2000
MAX_NOTE = 4000
MAX_LIST_NAME = 100
DONE_RETENTION_DAYS = 30
PRIORITIES = ("high", "normal", "low")

QUESTION_STATUSES = {
    "confirm_delete", "confirm_delete_list", "ambiguous", "ambiguous_list", "needs_list_scope",
    "unknown_list", "confirm_past", "confirm_order", "confirm_duplicate",
}


@dataclass
class Ctx:
    user_id: str | None        # None = unknown speaker
    role: str | None
    tz: ZoneInfo
    now: datetime
    channel: str = "chat"       # "voice" | "chat"
    session_id: str | None = None
    turn: int | None = None
    # True only when the user answers an open question of the previous turn
    # (main.py checks the stored pending question) — a model setting
    # confirmed=true on its own is ignored.
    confirmed: bool = False

    @property
    def unknown(self) -> bool:
        return self.user_id is None

    @property
    def ticket_owner(self) -> str:
        return self.user_id or "unknown"


def _err(code: str, message: str, **extra) -> dict:
    return {"error": code, "message": message, **extra}


ERR_UNKNOWN_SPEAKER = ("unknown_speaker",
                       "Der Sprecher wurde nicht erkannt — erlaubt ist nur, etwas auf die Einkaufsliste zu setzen.")
ERR_FORBIDDEN = ("forbidden", "Die Rolle des Nutzers darf diese Aktion nicht ausführen.")
ERR_NO_SHOPPING = ("no_shopping_list", "Es ist keine Einkaufsliste festgelegt — das kann nur ein Admin.")


# ---------------------------------------------------------------------------
# Permissions (fixed in the service; the admin area only switches the role
# flag can_use_lists on/off — see Tech Design, open point 1)
# ---------------------------------------------------------------------------
def permission_error(ctx: Ctx, action: str, lst: dict | None) -> dict | None:
    """None if allowed, else an error result.

    actions: read, add, complete, update, remove, cleanup, rename, delete,
             create_shared, flag_shopping, set_default
    """
    if ctx.unknown:
        if action == "add" and lst is not None and lst.get("is_shopping"):
            return None
        return _err(*ERR_UNKNOWN_SPEAKER)
    if lst is not None and not lst.get("is_shared"):
        # Private: only the owner ever gets here (visibility filter).
        return None if lst.get("owner_id") == ctx.user_id else _err(*ERR_FORBIDDEN)
    role = ctx.role
    if action in ("read", "add", "complete", "set_default"):
        return None
    if action in ("update", "remove", "cleanup"):
        if role in ("admin", "user"):
            return None
        if action == "remove" and lst is not None and lst.get("is_shopping"):
            return _err("forbidden_child_remove",
                        "Kinder dürfen nichts von der Einkaufsliste entfernen, nur abhaken.")
        return _err(*ERR_FORBIDDEN)
    if action == "create_shared":
        return None if role in ("admin", "user") else _err(*ERR_FORBIDDEN)
    if action == "flag_shopping":
        return None if role == "admin" else _err("admin_only", "Nur ein Admin kann die Einkaufsliste festlegen.")
    if action in ("rename", "delete"):
        if role == "admin":
            return None
        if lst is not None and lst.get("is_shopping") and action == "delete":
            return _err("admin_only", "Die Einkaufsliste kann nur ein Admin löschen.")
        if role == "user" and lst is not None and lst.get("created_by") == ctx.user_id:
            return None
        return _err("not_list_owner", "Gemeinsame Listen dürfen nur ein Admin und der Ersteller umbenennen "
                                      "oder löschen.")
    return _err(*ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# Argument helpers
# ---------------------------------------------------------------------------
def _str_arg(args: dict, key: str, max_len: int) -> str | None:
    v = args.get(key)
    if v is None:
        return None
    v = str(v).strip()
    if len(v) > max_len:
        raise tu.InputError(f"{key} ist zu lang (max {max_len} Zeichen)")
    return v or None


def _flag(args: dict, key: str) -> bool:
    v = args.get(key)
    return v is True or str(v).strip().lower() in ("true", "1", "yes", "ja")


def _priority(value) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    v = str(value).strip().lower()
    v = {"hoch": "high", "wichtig": "high", "dringend": "high", "niedrig": "low", "unwichtig": "low",
         "mittel": "normal"}.get(v, v)
    if v not in PRIORITIES:
        raise tu.InputError("priority muss high, normal oder low sein")
    return v


def _list_info(lst: dict) -> dict:
    return {"name": lst["name"], "shared": lst["is_shared"], "shopping": lst["is_shopping"]}


# ---------------------------------------------------------------------------
# List resolution
# ---------------------------------------------------------------------------
@dataclass
class Visible:
    lists: list[dict]

    def by_id(self, list_id: str) -> dict | None:
        return next((l for l in self.lists if l["id"] == list_id), None)

    @property
    def shopping(self) -> dict | None:
        return next((l for l in self.lists if l["is_shopping"]), None)


async def _visible(ctx: Ctx) -> Visible:
    return Visible(await db.visible_lists(ctx.user_id))


def resolve_list(ctx: Ctx, vis: Visible, name: str | None, scope: str | None = None) -> dict:
    """Name → {"list": row} or a question / error result.

    "Einkaufsliste"/"Einkaufszettel" always mean the flagged list; exact
    names win over approximate ones; a private and a shared list with the
    same name need the user's choice (scope private|shared).
    """
    name = (name or "").strip()
    if tx.is_shopping_alias(name):
        lst = vis.shopping
        return {"list": lst} if lst else _err(*ERR_NO_SHOPPING)
    candidates = vis.lists
    if scope in ("private", "shared"):
        candidates = [l for l in candidates if l["is_shared"] == (scope == "shared")]
    idx = tx.match_names(name, [l["name"] for l in candidates])
    matches = [candidates[i] for i in idx]
    if len(matches) == 1:
        return {"list": matches[0]}
    if not matches:
        return {"status": "unknown_list", "name": name,
                "instruction": "Die Liste gibt es nicht. Frage, ob sie angelegt werden soll; bei Ja das Tool "
                               "erneut mit confirmed=true aufrufen."}
    exact = {tx.name_key(m["name"]) for m in matches}
    if len(matches) == 2 and len(exact) == 1 and {m["is_shared"] for m in matches} == {True, False}:
        return {"status": "needs_list_scope", "name": matches[0]["name"],
                "instruction": "Frage: deine private oder die gemeinsame Liste? Danach mit list_scope "
                               "(private|shared) erneut aufrufen."}
    return {"status": "ambiguous_list", "options": [m["name"] for m in matches[:MAX_CANDIDATES]],
            "instruction": "Frage, welche Liste gemeint ist, und rufe das Tool mit dem Namen erneut auf."}


async def _target_list(ctx: Ctx, vis: Visible, args: dict, key: str = "list") -> dict:
    """Named list, else the user's default list (unknown speaker: none)."""
    name = _str_arg(args, key, 200)
    if name:
        return resolve_list(ctx, vis, name, (args.get("list_scope") or None))
    if ctx.unknown:
        return _err(*ERR_UNKNOWN_SPEAKER)
    list_id = await db.ensure_default_list(ctx.user_id)
    lst = vis.by_id(list_id) or await db.get_list(list_id)
    return {"list": lst}


# ---------------------------------------------------------------------------
# Item shaping + sorting
# ---------------------------------------------------------------------------
def _when(item: dict, prefix: str) -> tu.When | None:
    at = item.get(f"{prefix}_at")
    return tu.When(at, bool(item.get(f"{prefix}_has_time"))) if at else None


def is_overdue(item: dict, ctx: Ctx) -> bool:
    return any(w is not None and w.is_past(ctx.now, ctx.tz)
               for w in (_when(item, "due"), _when(item, "deadline")))


_PRIO_RANK = {"high": 0, "normal": 1, "low": 2}


def sort_key(item: dict, ctx: Ctx):
    whens = [w for w in (_when(item, "due"), _when(item, "deadline")) if w is not None]
    prio = _PRIO_RANK.get(item.get("priority") or "normal", 1)
    created = item.get("created_at") or ctx.now
    if not whens:
        return (2, datetime.max.date(), prio, datetime.max.replace(tzinfo=ctx.tz), created)
    earliest = min(whens, key=lambda w: w.at)
    group = 0 if is_overdue(item, ctx) else 1
    return (group, earliest.local_date(ctx.tz), prio, earliest.at, created)


def describe_item(item: dict, ctx: Ctx, list_name: str | None = None, note: bool = False,
                  ref: bool = False) -> dict:
    out: dict = {"title": item["title"]}
    if ref:
        out["item_ref"] = item["id"]
    if list_name:
        out["list"] = list_name
    due = tu.describe_when(item.get("due_at"), bool(item.get("due_has_time")), ctx.tz)
    deadline = tu.describe_when(item.get("deadline_at"), bool(item.get("deadline_has_time")), ctx.tz)
    if due:
        out["due"] = due
    if deadline:
        out["deadline"] = deadline
    if item.get("priority") and item["priority"] != "normal":
        out["priority"] = item["priority"]
    if not item.get("is_done") and is_overdue(item, ctx):
        out["overdue"] = True
    if item.get("is_done") and item.get("done_at"):
        out["done_at"] = item["done_at"].astimezone(ctx.tz).date().isoformat()
    if note and item.get("note"):
        out["note"] = item["note"]
    return out


def _in_range(item: dict, rng: tu.QueryRange, ctx: Ctx, only_deadlines: bool) -> bool:
    if rng.keyword == "overdue":
        whens = [_when(item, "deadline")] if only_deadlines else [_when(item, "due"), _when(item, "deadline")]
        return any(w is not None and w.is_past(ctx.now, ctx.tz) for w in whens)
    if rng.first_day is None:
        return not only_deadlines or item.get("deadline_at") is not None
    whens = [_when(item, "deadline")] if only_deadlines else [_when(item, "due"), _when(item, "deadline")]
    return any(w is not None and rng.first_day <= w.local_date(ctx.tz) <= rng.last_day for w in whens)


# ---------------------------------------------------------------------------
# Dates for add / update
# ---------------------------------------------------------------------------
def _dates(args: dict, ctx: Ctx, prefix: str = "") -> dict:
    """Parse due_/deadline_ date+time args (with optional prefix "new_")."""
    out = {}
    for kind in ("due", "deadline"):
        d = tu.parse_date(args.get(f"{prefix}{kind}_date"), f"{prefix}{kind}_date")
        t = tu.parse_time(args.get(f"{prefix}{kind}_time"), f"{prefix}{kind}_time")
        w = tu.build_when(d, t, ctx.tz, ctx.now)
        if w is not None:
            out[kind] = w
    return out


def _date_questions(dates: dict, ctx: Ctx, preview: dict, all_dates: dict | None = None) -> dict | None:
    """A new date in the past, or a deadline before the due date (checked on
    `all_dates`, i.e. incl. unchanged values) → question instead of saving."""
    if ctx.confirmed:
        return None
    for kind in ("due", "deadline"):
        w = dates.get(kind)
        if w is not None and w.is_past(ctx.now, ctx.tz):
            return {"status": "confirm_past", "field": kind, "item": preview,
                    "instruction": "Das Datum liegt in der Vergangenheit. Frage nach; bei Bestätigung mit "
                                   "confirmed=true erneut aufrufen, sonst mit dem richtigen Datum."}
    combined = dates if all_dates is None else all_dates
    due, deadline = combined.get("due"), combined.get("deadline")
    if due and deadline and deadline.at < due.at and deadline.local_date(ctx.tz) <= due.local_date(ctx.tz):
        return {"status": "confirm_order", "item": preview,
                "instruction": "Die Frist liegt vor der Fälligkeit. Weise darauf hin und frage nach."}
    return None


def _preview(title: str, dates: dict, ctx: Ctx, priority: str | None = None) -> dict:
    out: dict = {"title": title}
    for kind in ("due", "deadline"):
        w = dates.get(kind)
        if w is not None:
            out[kind] = tu.describe_when(w.at, w.has_time, ctx.tz)
    if priority and priority != "normal":
        out["priority"] = priority
    return out


# ---------------------------------------------------------------------------
# Tool: add items
# ---------------------------------------------------------------------------
async def add_items(ctx: Ctx, args: dict) -> dict:
    titles = tx.split_items(args.get("items") if args.get("items") is not None else args.get("title"))
    if not titles:
        raise tu.InputError("items ist erforderlich (Einträge wie gesagt, z. B. 'Milch, Butter und Eier')")
    if len(titles) > tx.MAX_ITEMS_PER_CALL:
        raise tu.InputError(f"Höchstens {tx.MAX_ITEMS_PER_CALL} Einträge auf einmal")
    if any(len(t) > MAX_TITLE for t in titles):
        raise tu.InputError(f"Ein Eintrag ist zu lang (max {MAX_TITLE} Zeichen)")
    note = _str_arg(args, "note", MAX_NOTE)
    priority = _priority(args.get("priority"))
    dates = _dates(args, ctx)

    vis = await _visible(ctx)
    target = await _target_list(ctx, vis, args)
    if target.get("status") == "unknown_list" and ctx.confirmed and not ctx.unknown:
        # "Soll ich sie anlegen?" — "Ja": create the private list now.
        try:
            lst = await db.create_list(ctx.user_id, target["name"], shared=False)
        except db.DuplicateName:
            return _err("duplicate_list_name", "Eine Liste mit diesem Namen gibt es schon.")
        target = {"list": {**lst, "open_count": 0}}
        created_list = True
    else:
        created_list = False
    if "list" not in target:
        return target
    lst = target["list"]
    denied = permission_error(ctx, "add", lst)
    if denied:
        return denied

    question = _date_questions(dates, ctx, _preview(titles[0], dates, ctx, priority))
    if question:
        question["list"] = _list_info(lst)
        return question

    existing = await db.fetch_items([lst["id"]], done=False)
    reopened: list[dict] = []
    to_add = list(titles)
    if lst["is_shopping"]:
        # Shopping list: open duplicates are fine; a done one is reopened.
        done_items = await db.fetch_items([lst["id"]], done=True)
        remaining = []
        for title in to_add:
            hit = next((d for d in done_items if tx.same_title(d["title"], title)), None)
            if hit is not None:
                done_items.remove(hit)
                row = await db.set_done(hit["id"], False, None)
                if row is not None:
                    reopened.append(row)
                    continue
            remaining.append(title)
        to_add = remaining
    elif not ctx.confirmed:
        dups = [t for t in to_add if any(tx.same_title(e["title"], t) for e in existing)]
        if dups:
            return {"status": "confirm_duplicate", "titles": dups, "list": _list_info(lst),
                    "instruction": "Diese Einträge stehen schon offen auf der Liste. Frage, ob trotzdem "
                                   "angelegt werden soll; bei Ja mit confirmed=true erneut aufrufen."}

    fields = {"note": note, "priority": priority or "normal"}
    for kind in ("due", "deadline"):
        w = dates.get(kind)
        if w is not None:
            fields[f"{kind}_at"] = w.at
            fields[f"{kind}_has_time"] = w.has_time
    rows = await db.insert_items(lst["id"], to_add, fields, ctx.user_id) if to_add else []
    return {
        "status": "added",
        "list": _list_info(lst),
        "list_created": created_list,
        "items": [describe_item(r, ctx) for r in rows],
        "reopened": [describe_item(r, ctx) for r in reopened],
    }


# ---------------------------------------------------------------------------
# Tool: query items
# ---------------------------------------------------------------------------
async def query_items(ctx: Ctx, args: dict) -> dict:
    done = _flag(args, "done")
    only_deadlines = _flag(args, "only_deadlines")
    count_only = _flag(args, "count_only")
    with_notes = _flag(args, "include_notes")
    search = _str_arg(args, "search", 300)
    rng = tu.resolve_range(args.get("range"), ctx.tz, ctx.now, args.get("date"), args.get("date_to"), done=done)

    vis = await _visible(ctx)
    name = _str_arg(args, "list", 200)
    single = None
    if name:
        target = resolve_list(ctx, vis, name, args.get("list_scope") or None)
        if "list" not in target:
            if target.get("status") == "unknown_list":
                # Nothing to create when only asking — say it does not exist.
                return {"status": "list_not_found", "name": target["name"]}
            return target
        single = target["list"]
    denied = permission_error(ctx, "read", single)
    if denied:
        return denied
    lists = [single] if single else vis.lists
    by_id = {l["id"]: l for l in lists}

    if done:
        since = ctx.now - timedelta(days=DONE_RETENTION_DAYS)
        items = await db.fetch_items(list(by_id), done=True, done_since=since)
        if single is None:
            # "Was habe ich erledigt?" — the caller's own; per list: everyone's.
            items = [i for i in items if i.get("done_by") == ctx.user_id]
        items = [i for i in items if rng.first_day <= i["done_at"].astimezone(ctx.tz).date() <= rng.last_day]
        items.sort(key=lambda i: i["done_at"], reverse=True)
    else:
        items = await db.fetch_items(list(by_id), done=False)
        items = [i for i in items if _in_range(i, rng, ctx, only_deadlines)]
        items.sort(key=lambda i: sort_key(i, ctx))

    if search:
        scored = [(tx.title_score(search, i["title"]), i) for i in items]
        best = max((s for s, _ in scored), default=0)
        items = [i for s, i in scored if s and s == best]

    result: dict = {
        "status": "ok",
        "mode": "done" if done else ("search" if search else ("count" if count_only else "items")),
        "range": {"keyword": rng.keyword,
                  "from": rng.first_day.isoformat() if rng.first_day else None,
                  "to": rng.last_day.isoformat() if rng.last_day else None},
        "only_deadlines": only_deadlines,
        "total": len(items),
    }
    if single:
        result["list"] = _list_info(single)
    if search:
        result["search"] = search
        result["found"] = bool(items)
    if count_only and not search:
        result["items"] = []
        result["remaining"] = 0
        return result

    limit = VOICE_LIMIT if ctx.channel == "voice" else CHAT_LIMIT
    shown = items[:limit]
    multi = len({i["list_id"] for i in items}) > 1
    result["items"] = [describe_item(i, ctx, by_id[i["list_id"]]["name"] if multi else None, with_notes)
                       for i in shown]
    result["remaining"] = len(items) - len(shown)
    result["truncated"] = ctx.channel != "voice" and len(items) > limit
    return result


# ---------------------------------------------------------------------------
# Finding existing items (complete / reopen / update / remove)
# ---------------------------------------------------------------------------
@dataclass
class Found:
    items: list[dict]         # one entry, or several identical titles in one list


async def _find(ctx: Ctx, lists: list[dict], query: str, prefer_done: bool = False) -> Found | dict:
    """Best title matches among the given lists' items — entries in the
    preferred state (open, or done for "wieder öffnen") first, the others
    only when nothing matches (so "schon erledigt" can be reported)."""
    ids = [l["id"] for l in lists]
    cands: list[dict] = []
    for state in (prefer_done, not prefer_done):
        scored = [(tx.title_score(query, i["title"]), i) for i in await db.fetch_items(ids, done=state)]
        best = max((sc for sc, _ in scored), default=0)
        cands = [i for sc, i in scored if sc and sc == best]
        if cands:
            break
    if not cands:
        return {"status": "not_found", "query": query}
    first = cands[0]
    if all(c["list_id"] == first["list_id"] and tx.same_title(c["title"], first["title"]) for c in cands):
        return Found(cands)
    cands.sort(key=lambda i: sort_key(i, ctx))
    names = {l["id"]: l["name"] for l in lists}
    return {
        "status": "ambiguous", "query": query,
        "candidates": [describe_item(c, ctx, names.get(c["list_id"]), ref=True) for c in cands[:MAX_CANDIDATES]],
        "instruction": "Mehrere Einträge passen. Nenne sie knapp und frage, welcher gemeint ist; danach das Tool "
                       "mit item_ref erneut aufrufen.",
    }


async def _scope_lists(ctx: Ctx, vis: Visible, args: dict) -> list[dict] | dict:
    name = _str_arg(args, "list", 200)
    if not name:
        return vis.lists
    target = resolve_list(ctx, vis, name, args.get("list_scope") or None)
    if "list" not in target:
        if target.get("status") == "unknown_list":
            return {"status": "list_not_found", "name": target["name"]}
        return target
    return [target["list"]]


async def _by_ref(ctx: Ctx, vis: Visible, ref) -> dict | None:
    try:
        item = await db.get_item(str(ref))
    except Exception:
        raise tu.InputError("item_ref ist ungültig")
    if item is None or vis.by_id(item["list_id"]) is None:
        return None
    return item


async def _targets(ctx: Ctx, args: dict, prefer_done: bool = False):
    """(vis, lists, [(query, Found|result)]) for multi-entry actions."""
    vis = await _visible(ctx)
    lists = await _scope_lists(ctx, vis, args)
    if isinstance(lists, dict):
        return vis, lists, []
    if args.get("item_ref"):
        item = await _by_ref(ctx, vis, args["item_ref"])
        return vis, lists, [(str(args.get("items") or ""), Found([item]) if item else
                             {"status": "not_found", "query": str(args.get("items") or "")})]
    queries = tx.split_items(args.get("items") if args.get("items") is not None else args.get("title"))
    if not queries:
        raise tu.InputError("items ist erforderlich")
    if len(queries) > tx.MAX_ITEMS_PER_CALL:
        raise tu.InputError(f"Höchstens {tx.MAX_ITEMS_PER_CALL} Einträge auf einmal")
    out = []
    for q in queries:
        out.append((q, await _find(ctx, lists, q, prefer_done)))
    return vis, lists, out


# ---------------------------------------------------------------------------
# Tools: complete / reopen
# ---------------------------------------------------------------------------
async def complete_items(ctx: Ctx, args: dict) -> dict:
    return await _set_done(ctx, args, True)


async def reopen_items(ctx: Ctx, args: dict) -> dict:
    return await _set_done(ctx, args, False)


async def _set_done(ctx: Ctx, args: dict, done: bool) -> dict:
    if ctx.unknown:
        return _err(*ERR_UNKNOWN_SPEAKER)
    vis, lists, targets = await _targets(ctx, args, prefer_done=not done)
    if isinstance(lists, dict):
        return lists
    changed, already, not_found, ambiguous = [], [], [], None
    for query, found in targets:
        if isinstance(found, dict):
            if found["status"] == "ambiguous" and ambiguous is None:
                ambiguous = found
            elif found["status"] == "not_found":
                not_found.append(query)
            continue
        lst = vis.by_id(found.items[0]["list_id"])
        denied = permission_error(ctx, "complete", lst)
        if denied:
            return denied
        hit = False
        for item in found.items:
            if item["is_done"] == done:
                continue
            row = await db.set_done(item["id"], done, ctx.user_id)
            if row is not None:
                changed.append(describe_item(row, ctx, lst["name"]))
                hit = True
                break  # identical duplicates: one per mention
        if not hit:
            already.append(found.items[0]["title"])
    result = {"status": "completed" if done else "reopened", "items": changed,
              "already": already, "not_found": not_found}
    if ambiguous:
        result = {**ambiguous, "done_items": changed, "already": already, "not_found": not_found,
                  "action": "complete" if done else "reopen"}
    return result


# ---------------------------------------------------------------------------
# Tool: update item
# ---------------------------------------------------------------------------
_CHANGE_KEYS = ("new_title", "new_note", "new_due_date", "new_due_time", "new_deadline_date",
                "new_deadline_time", "new_priority", "new_list", "clear_due", "clear_deadline", "clear_note")


async def update_item(ctx: Ctx, args: dict) -> dict:
    if ctx.unknown:
        return _err(*ERR_UNKNOWN_SPEAKER)
    if not any(args.get(k) not in (None, "", False) for k in _CHANGE_KEYS):
        raise tu.InputError("Es wurde keine Änderung angegeben (new_*/clear_* Felder)")
    vis = await _visible(ctx)
    lists = await _scope_lists(ctx, vis, args)
    if isinstance(lists, dict):
        return lists
    if args.get("item_ref"):
        item = await _by_ref(ctx, vis, args["item_ref"])
        found = Found([item]) if item else {"status": "not_found", "query": ""}
    else:
        query = _str_arg(args, "item", 300) or _str_arg(args, "items", 300)
        if not query:
            raise tu.InputError("item (Titel des Eintrags) ist erforderlich")
        found = await _find(ctx, lists, query)
    if isinstance(found, dict):
        return found
    item = found.items[0]
    lst = vis.by_id(item["list_id"])
    denied = permission_error(ctx, "update", lst)
    if denied:
        return denied

    changes: dict = {}
    title = _str_arg(args, "new_title", MAX_TITLE)
    if title:
        changes["title"] = title
    if _flag(args, "clear_note"):
        changes["note"] = None
    elif args.get("new_note") not in (None, ""):
        changes["note"] = _str_arg(args, "new_note", MAX_NOTE)
    prio = _priority(args.get("new_priority"))
    if prio:
        changes["priority"] = prio

    new_dates = {}
    for kind in ("due", "deadline"):
        if _flag(args, f"clear_{kind}"):
            changes[f"{kind}_at"] = None
            changes[f"{kind}_has_time"] = False
            continue
        d = tu.parse_date(args.get(f"new_{kind}_date"), f"new_{kind}_date")
        t = tu.parse_time(args.get(f"new_{kind}_time"), f"new_{kind}_time")
        if d is None and t is not None and item.get(f"{kind}_at") is not None:
            d = item[f"{kind}_at"].astimezone(ctx.tz).date()   # "auf 15 Uhr" keeps the day
        w = tu.build_when(d, t, ctx.tz, ctx.now)
        if w is not None:
            new_dates[kind] = w
            changes[f"{kind}_at"] = w.at
            changes[f"{kind}_has_time"] = w.has_time
    if new_dates:
        merged = {k: v for k, v in (("due", _when(item, "due")), ("deadline", _when(item, "deadline")))
                  if v and changes.get(f"{k}_at", 0) is not None}
        merged.update(new_dates)
        question = _date_questions(new_dates, ctx, _preview(item["title"], merged, ctx), merged)
        if question:
            return question

    if args.get("new_list"):
        dest = resolve_list(ctx, vis, str(args["new_list"]))
        if "list" not in dest:
            if dest.get("status") == "unknown_list":
                return {"status": "list_not_found", "name": dest["name"]}
            return dest
        denied = permission_error(ctx, "add", dest["list"])
        if denied:
            return denied
        changes["list_id"] = dest["list"]["id"]
        lst = dest["list"]

    row = await db.update_item(item["id"], changes)
    if row is None:
        return {"status": "not_found", "query": item["title"]}
    return {"status": "updated", "item": describe_item(row, ctx, lst["name"], note=True),
            "list": _list_info(lst)}


# ---------------------------------------------------------------------------
# Tool: remove items (shopping list directly; elsewhere stage 1 of 2)
# ---------------------------------------------------------------------------
async def remove_items(ctx: Ctx, args: dict) -> dict:
    if ctx.unknown:
        return _err(*ERR_UNKNOWN_SPEAKER)
    vis, lists, targets = await _targets(ctx, args)
    if isinstance(lists, dict):
        return lists
    removed, not_found, confirm, deferred, ambiguous = [], [], None, [], None
    for query, found in targets:
        if isinstance(found, dict):
            if found["status"] == "ambiguous" and ambiguous is None:
                ambiguous = found
            elif found["status"] == "not_found":
                not_found.append(query)
            continue
        item = found.items[0]
        lst = vis.by_id(item["list_id"])
        denied = permission_error(ctx, "remove", lst)
        if denied:
            return denied
        if lst["is_shopping"]:
            # One mention removes one entry (identical duplicates stay).
            gone = await db.delete_items([item["id"]])
            if gone:
                removed.append(describe_item(item, ctx, lst["name"]))
            else:
                not_found.append(query)
            continue
        if confirm is None:
            confirm = (item, lst)
        else:
            deferred.append(item["title"])

    if confirm is not None:
        if not ctx.session_id or ctx.turn is None:
            return _err("no_session", "Löschen ist nur innerhalb eines Gesprächs möglich.")
        item, lst = confirm
        described = describe_item(item, ctx, lst["name"])
        ticket = await tickets.issue(ctx.ticket_owner, ctx.session_id, ctx.turn, {
            "kind": "item", "item_id": item["id"], "updated_at": item["updated_at"].isoformat(),
            "item": described, "list": _list_info(lst),
        })
        return {"status": "confirm_delete", "ticket": ticket, "item": described, "list": _list_info(lst),
                "removed": removed, "not_found": not_found, "deferred": deferred,
                "instruction": "NOCH NICHTS GELÖSCHT. Frage, ob der Eintrag gelöscht werden soll; lists_confirm_delete "
                               "erst nach dem Ja des Nutzers in seiner nächsten Nachricht."}
    if ambiguous:
        return {**ambiguous, "removed": removed, "not_found": not_found, "action": "remove"}
    return {"status": "removed", "items": removed, "not_found": not_found}


_TICKET_MESSAGES = {
    "same_turn": "Die Löschung braucht die Zustimmung des Nutzers in seiner nächsten Nachricht. Es wurde NICHTS "
                 "gelöscht.",
    "expired": "Die Löschanfrage ist verfallen. Es wurde NICHTS gelöscht.",
    "unknown": "Unbekanntes oder abgelaufenes Lösch-Ticket. Es wurde NICHTS gelöscht.",
    "wrong_owner": "Ungültiges Lösch-Ticket. Es wurde NICHTS gelöscht.",
}


async def confirm_delete(ctx: Ctx, args: dict) -> dict:
    if ctx.unknown:
        return _err(*ERR_UNKNOWN_SPEAKER)
    if not ctx.session_id or ctx.turn is None:
        return _err("no_session", "Löschen ist nur innerhalb eines Gesprächs möglich.")
    try:
        target = await tickets.redeem(str(args.get("ticket") or ""), ctx.ticket_owner, ctx.session_id, ctx.turn)
    except tickets.TicketError as exc:
        return _err(f"ticket_{exc.reason}", _TICKET_MESSAGES.get(exc.reason, _TICKET_MESSAGES["unknown"]))

    vis = await _visible(ctx)
    if target.get("kind") == "list":
        lst = vis.by_id(target["list_id"])
        if lst is None:
            return _err("list_gone", "Die Liste gibt es nicht mehr.")
        denied = permission_error(ctx, "delete", lst)
        if denied:
            return denied
        await db.delete_list(lst["id"])
        return {"status": "deleted", "kind": "list", "list": _list_info(lst),
                "count": int(lst.get("open_count") or 0) + int(lst.get("done_count") or 0)}

    item = await db.get_item(target["item_id"])
    lst = vis.by_id(item["list_id"]) if item else None
    if item is None or lst is None:
        return _err("item_gone", "Der Eintrag ist nicht mehr vorhanden. Es wurde nichts gelöscht.")
    denied = permission_error(ctx, "remove", lst)
    if denied:
        return denied
    outcome = await db.delete_item_if_unchanged(item["id"], datetime.fromisoformat(target["updated_at"]))
    if outcome == "gone":
        return _err("item_gone", "Der Eintrag ist nicht mehr vorhanden. Es wurde nichts gelöscht.")
    if outcome == "changed":
        return _err("item_changed", "Der Eintrag wurde zwischenzeitlich geändert. Es wurde NICHTS gelöscht.")
    return {"status": "deleted", "kind": "item", "item": target.get("item"), "list": _list_info(lst)}


# ---------------------------------------------------------------------------
# Tool: clean up done entries of a list
# ---------------------------------------------------------------------------
async def cleanup_list(ctx: Ctx, args: dict) -> dict:
    if ctx.unknown:
        return _err(*ERR_UNKNOWN_SPEAKER)
    vis = await _visible(ctx)
    target = await _target_list(ctx, vis, args)
    if "list" not in target:
        if target.get("status") == "unknown_list":
            return {"status": "list_not_found", "name": target["name"]}
        return target
    lst = target["list"]
    denied = permission_error(ctx, "cleanup", lst)
    if denied:
        return denied
    count = await db.delete_done(lst["id"])
    return {"status": "cleaned", "list": _list_info(lst), "count": int(count or 0)}


# ---------------------------------------------------------------------------
# Tool: list management
# ---------------------------------------------------------------------------
_MANAGE_ACTIONS = ("create", "rename", "delete", "set_default", "set_shopping", "overview")


async def manage_list(ctx: Ctx, args: dict) -> dict:
    action = str(args.get("action") or "").strip().lower()
    if action not in _MANAGE_ACTIONS:
        raise tu.InputError(f"action muss eines von {', '.join(_MANAGE_ACTIONS)} sein")
    if ctx.unknown:
        return _err(*ERR_UNKNOWN_SPEAKER)
    vis = await _visible(ctx)

    if action == "overview":
        default_id = await db.ensure_default_list(ctx.user_id)
        vis = await _visible(ctx)
        return {"status": "lists", "lists": [
            {**_list_info(l), "default": l["id"] == default_id, "open": int(l.get("open_count") or 0)}
            for l in vis.lists
        ]}

    if action == "create":
        name = _str_arg(args, "name", MAX_LIST_NAME)
        if not name:
            raise tu.InputError("name ist erforderlich")
        if tx.is_shopping_alias(name) and vis.shopping is not None:
            return _err("duplicate_list_name", "Die Einkaufsliste gibt es schon.", name=vis.shopping["name"])
        shared = _flag(args, "shared")
        if shared:
            denied = permission_error(ctx, "create_shared", None)
            if denied:
                return denied
        try:
            lst = await db.create_list(ctx.user_id, name, shared)
        except db.DuplicateName:
            return _err("duplicate_list_name", "Eine Liste mit diesem Namen gibt es schon.", name=name)
        return {"status": "list_created", "list": _list_info(lst)}

    target = resolve_list(ctx, vis, _str_arg(args, "name", 200) or "", args.get("list_scope") or None)
    if "list" not in target:
        if target.get("status") == "unknown_list":
            return {"status": "list_not_found", "name": target["name"]}
        return target
    lst = target["list"]

    if action == "rename":
        new_name = _str_arg(args, "new_name", MAX_LIST_NAME)
        if not new_name:
            raise tu.InputError("new_name ist erforderlich")
        denied = permission_error(ctx, "rename", lst)
        if denied:
            return denied
        try:
            row = await db.rename_list(ctx.user_id, lst["id"], new_name)
        except db.DuplicateName:
            return _err("duplicate_list_name", "Eine Liste mit diesem Namen gibt es schon.", name=new_name)
        if row is None:
            return {"status": "list_not_found", "name": lst["name"]}
        return {"status": "list_renamed", "old": lst["name"], "list": _list_info(row)}

    if action == "set_default":
        denied = permission_error(ctx, "set_default", lst)
        if denied:
            return denied
        await db.set_default(ctx.user_id, lst["id"])
        return {"status": "default_set", "list": _list_info(lst)}

    if action == "set_shopping":
        denied = permission_error(ctx, "flag_shopping", lst)
        if denied:
            return denied
        if not lst["is_shared"]:
            return _err("private_not_shopping", "Private Listen können nicht die Einkaufsliste sein.")
        if lst["is_shopping"]:
            return {"status": "shopping_set", "list": _list_info(lst), "previous": None, "unchanged": True}
        previous = await db.flag_shopping(lst["id"])
        return {"status": "shopping_set", "list": {**_list_info(lst), "shopping": True}, "previous": previous}

    # delete — stage 1: question with the number of entries
    denied = permission_error(ctx, "delete", lst)
    if denied:
        return denied
    if not ctx.session_id or ctx.turn is None:
        return _err("no_session", "Löschen ist nur innerhalb eines Gesprächs möglich.")
    count = int(lst.get("open_count") or 0) + int(lst.get("done_count") or 0)
    ticket = await tickets.issue(ctx.ticket_owner, ctx.session_id, ctx.turn,
                                 {"kind": "list", "list_id": lst["id"], "list": _list_info(lst)})
    return {"status": "confirm_delete_list", "ticket": ticket, "list": _list_info(lst), "count": count,
            "instruction": "NOCH NICHTS GELÖSCHT. Frage mit Anzahl der Einträge, ob die Liste gelöscht werden soll; "
                           "lists_confirm_delete erst nach dem Ja des Nutzers."}
