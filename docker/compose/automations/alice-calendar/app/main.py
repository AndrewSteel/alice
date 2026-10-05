"""
alice-calendar — Google Calendar agent for Alice (PROJ-87).

nginx proxies /api/calendar/* → alice-calendar:8009 as /calendar/*. The
/internal/* routes are NOT routed by nginx; only alice-chat-stream calls them
over the Docker network, forwarding the end user's JWT.

Endpoints:
  GET  /health
  GET  /calendar/accounts          - Settings tab: accounts + live calendar lists
  PUT  /calendar/selection         - Settings tab: toggle active / default
  GET  /calendar/admin/roles       - Admin: calendar permission per role
  PUT  /calendar/admin/roles       - Admin: update calendar permission per role
  POST /internal/turn              - Chat turn start: permission + open follow-up question
  POST /internal/tools/{tool}      - Chat tools (list/create/update/delete/confirm_delete)

No event data is stored — every request reads Google live.
"""
from __future__ import annotations

import logging
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import agent, db, tickets
from . import timeutil as tu
from .auth import Caller, load_public_key, verify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alice-calendar")

try:
    load_public_key()
except Exception as _exc:  # fail fast like the other Alice services
    logger.critical("JWT public key load failed on startup: %s", _exc)
    sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    try:
        yield
    finally:
        await db.close_pool()


app = FastAPI(title="alice-calendar", version="1.0.0", lifespan=lifespan)


async def _ctx(caller: Caller, client: httpx.AsyncClient, **kw) -> agent.Ctx:
    tz_name = await db.user_timezone(caller.user_id) or tu.DEFAULT_TZ
    tz = tu.zone(tz_name)
    return agent.Ctx(caller=caller, client=client, tz_name=tz.key, tz=tz, now=datetime.now(tz), **kw)


async def _require_calendar_user(caller: Caller = Depends(verify)) -> Caller:
    """Tab endpoints: identified user with calendar permission, else 403."""
    if caller.is_unknown_speaker or not await db.can_use_calendar(caller.user_id):
        raise HTTPException(status_code=403, detail="Keine Kalender-Berechtigung")
    return caller


async def _require_admin(caller: Caller = Depends(verify)) -> Caller:
    role = await db.pool().fetchval(
        "SELECT role FROM alice.users WHERE id = $1::uuid AND is_active", caller.user_id
    ) if not caller.is_unknown_speaker else None
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin-Zugriff erforderlich")
    return caller


@app.get("/health")
async def health():
    db_ok = await db.healthy()
    return {"status": "healthy" if db_ok else "degraded", "db": db_ok}


# ---------------------------------------------------------------------------
# Settings tab
# ---------------------------------------------------------------------------
@app.get("/calendar/accounts")
async def get_accounts(caller: Caller = Depends(_require_calendar_user)):
    async with httpx.AsyncClient() as client:
        ctx = await _ctx(caller, client)
        try:
            return await agent.accounts_overview(ctx)
        except agent.google.Unavailable:
            raise HTTPException(status_code=502, detail="Google-Verbindungen nicht abrufbar")


class SelectionUpdate(BaseModel):
    connection_id: str = Field(..., max_length=64)
    calendar_id: str = Field(..., min_length=1, max_length=512)
    is_active: bool | None = None
    is_default: bool | None = None

    @field_validator("connection_id")
    @classmethod
    def _uuid(cls, v: str) -> str:
        try:
            return str(uuid.UUID(v))
        except ValueError as exc:
            raise ValueError("connection_id muss eine UUID sein") from exc


@app.put("/calendar/selection")
async def put_selection(body: SelectionUpdate, caller: Caller = Depends(_require_calendar_user)):
    if body.is_active is None and body.is_default is None:
        raise HTTPException(status_code=422, detail="is_active oder is_default angeben")
    async with httpx.AsyncClient() as client:
        ctx = await _ctx(caller, client)
        try:
            selections = await agent.update_selection(
                ctx, body.connection_id, body.calendar_id, body.is_active, body.is_default,
            )
        except agent.SelectionError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.detail)
        except agent.google.Unavailable:
            raise HTTPException(status_code=502, detail="Google-Verbindungen nicht abrufbar")
    return {"selections": selections}


# ---------------------------------------------------------------------------
# Admin: role permission
# ---------------------------------------------------------------------------
class RoleFlag(BaseModel):
    role: str
    can_use_calendar: bool

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in db.ROLES:
            raise ValueError("role muss admin, user, guest oder child sein")
        return v


class RoleUpdate(BaseModel):
    roles: list[RoleFlag] = Field(..., max_length=4)


@app.get("/calendar/admin/roles")
async def get_roles(caller: Caller = Depends(_require_admin)):
    return {"roles": await db.get_role_config()}


@app.put("/calendar/admin/roles")
async def put_roles(body: RoleUpdate, caller: Caller = Depends(_require_admin)):
    await db.set_role_config([r.model_dump() for r in body.roles])
    return {"roles": await db.get_role_config()}


# ---------------------------------------------------------------------------
# Internal: chat tools
# ---------------------------------------------------------------------------
class ToolCall(BaseModel):
    args: dict = Field(default_factory=dict)
    session_id: str | None = Field(None, max_length=64)
    turn: int | None = Field(None, ge=0)
    channel: str = "chat"


class TurnStart(BaseModel):
    session_id: str = Field(..., max_length=64)
    turn: int = Field(..., ge=0)


@app.post("/internal/turn")
async def turn_start(body: TurnStart, caller: Caller = Depends(verify)):
    """Called by alice-chat-stream before each LLM turn.

    enabled=false + reason tells the chat service not to offer the calendar
    tools and to explain why. pending carries the open follow-up question of
    the previous turn (tool results are not part of the chat history).
    """
    if caller.is_unknown_speaker:
        return {"enabled": False, "reason": "unknown_speaker", "pending": None}
    if not await db.can_use_calendar(caller.user_id):
        return {"enabled": False, "reason": "forbidden", "pending": None}
    try:
        pending = await tickets.load_pending(caller.user_id, body.session_id, body.turn)
    except Exception as exc:  # Redis hiccup must not disable the calendar
        logger.warning("pending lookup failed: %s", exc)
        pending = None
    return {"enabled": True, "reason": None, "pending": pending}


# Results that ask the user something — remembered for the next turn.
_PENDING_STATUSES = {"confirm_delete", "ambiguous", "needs_scope", "needs_calendar", "confirm_past"}

_TOOLS = {
    "list_events": agent.list_events,
    "create_event": agent.create_event,
    "update_event": agent.update_event,
    "delete_event": agent.prepare_delete,
    "confirm_delete": agent.confirm_delete,
}


@app.post("/internal/tools/{tool}")
async def run_tool(tool: str, body: ToolCall, caller: Caller = Depends(verify)):
    """Always 200 with a result dict — the LLM explains errors to the user."""
    handler = _TOOLS.get(tool)
    if handler is None:
        raise HTTPException(status_code=404, detail="Unknown tool")
    if caller.is_unknown_speaker:
        return agent._err(
            "unknown_speaker",
            "Der Sprecher wurde nicht erkannt. Führe keine Kalenderaktion aus und erkläre, dass du "
            "nicht weißt, wessen Kalender gemeint ist.",
        )
    if not await db.can_use_calendar(caller.user_id):
        return agent._err(
            "forbidden",
            "Die Rolle des Nutzers hat keinen Kalenderzugriff. Lehne höflich ab und erkläre das.",
        )
    async with httpx.AsyncClient() as client:
        ctx = await _ctx(
            caller, client,
            channel="voice" if body.channel == "voice" else "chat",
            session_id=body.session_id,
            turn=body.turn,
        )
        try:
            result = await handler(ctx, body.args or {})
        except tu.UnsupportedRecurrence as exc:
            return agent._err(
                "unsupported_recurrence",
                f"{exc}. Lege den Termin NICHT an. Sage dem Nutzer, dass Alice nur einfache "
                "Wiederholungen kann und er komplexere Regeln direkt in Google Kalender einrichten "
                "soll (oder biete eine einfache Variante an).",
            )
        except tu.InputError as exc:
            return agent._err("invalid_input", f"{exc} — korrigiere den Aufruf oder frage den Nutzer nach.")
        except agent.google.ReauthRequired:
            return agent._err(*agent.ERR_REAUTH)
        except agent.google.GoogleError:
            return agent._err(*agent.ERR_UNAVAILABLE)
        except Exception:
            logger.exception("Tool %s failed", tool)
            return agent._err("internal_error", "Interner Fehler im Kalender-Dienst. Melde keinen Erfolg; "
                                                "sage dem Nutzer, er soll es später nochmal versuchen.")

    if body.session_id:
        try:
            if result.get("status") in _PENDING_STATUSES and body.turn is not None:
                await tickets.save_pending(caller.user_id, body.session_id, body.turn, {
                    "tool": tool,
                    "args": body.args or {},
                    "result": {k: v for k, v in result.items() if k != "instruction"},
                })
            elif result.get("status") in ("created", "updated", "deleted"):
                # The question was resolved. Errors (e.g. a premature same-turn
                # confirm) must NOT clear it, or the user's "Ja" finds no ticket.
                await tickets.clear_pending(caller.user_id, body.session_id)
        except Exception as exc:
            logger.warning("pending store failed: %s", exc)
    return result
