"""
alice-lists — local task & list management for Alice (PROJ-106).

nginx proxies /api/lists/* → alice-lists:8010 as /lists/* (admin role config
now, the PROJ-107 WebApp view later). The /internal/* routes are NOT routed
by nginx; only alice-chat-stream calls them over the Docker network,
forwarding the end user's JWT.

Endpoints:
  GET  /health
  GET  /lists/admin/roles          - Admin: lists permission per role
  PUT  /lists/admin/roles          - Admin: update lists permission per role
  POST /internal/turn              - Chat turn start: permission + open follow-up question
  POST /internal/tools/{tool}      - Chat tools

A background task purges done entries 30 days after they were ticked off.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from . import agent, db, tickets
from . import timeutil as tu
from .auth import Caller, load_public_key, verify

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("alice-lists")

PURGE_INTERVAL_SECONDS = 6 * 3600

try:
    load_public_key()
except Exception as _exc:  # fail fast like the other Alice services
    logger.critical("JWT public key load failed on startup: %s", _exc)
    sys.exit(1)


async def _purge_loop() -> None:
    while True:
        try:
            n = await db.purge_done(agent.DONE_RETENTION_DAYS)
            if n:
                logger.info("Purged %s done list entries older than %s days", n, agent.DONE_RETENTION_DAYS)
        except Exception as exc:
            logger.warning("purge failed: %s", exc)
        await asyncio.sleep(PURGE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    purge = asyncio.create_task(_purge_loop())
    try:
        yield
    finally:
        purge.cancel()
        await db.close_pool()


app = FastAPI(title="alice-lists", version="1.0.0", lifespan=lifespan)


async def _require_admin(caller: Caller = Depends(verify)) -> Caller:
    role = None if caller.is_unknown_speaker else (await db.caller_access(caller.user_id))[0]
    if role != "admin":
        raise HTTPException(status_code=403, detail="Admin-Zugriff erforderlich")
    return caller


@app.get("/health")
async def health():
    db_ok = await db.healthy()
    return {"status": "healthy" if db_ok else "degraded", "db": db_ok}


# ---------------------------------------------------------------------------
# Admin: role permission
# ---------------------------------------------------------------------------
class RoleFlag(BaseModel):
    role: str
    can_use_lists: bool

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in db.ROLES:
            raise ValueError("role muss admin, user, guest oder child sein")
        return v


class RoleUpdate(BaseModel):
    roles: list[RoleFlag] = Field(..., max_length=4)


@app.get("/lists/admin/roles")
async def get_roles(caller: Caller = Depends(_require_admin)):
    return {"roles": await db.get_role_config()}


@app.put("/lists/admin/roles")
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


async def _access(caller: Caller) -> tuple[str | None, str | None]:
    """(role, denial reason). The unknown speaker passes with role None —
    the agent allows him the shopping-list add only."""
    if caller.is_unknown_speaker:
        return None, None
    role, allowed = await db.caller_access(caller.user_id)
    if role is None or not allowed:
        return role, "forbidden"
    return role, None


def _owner(caller: Caller) -> str:
    return "unknown" if caller.is_unknown_speaker else caller.user_id


@app.post("/internal/turn")
async def turn_start(body: TurnStart, caller: Caller = Depends(verify)):
    """Called by alice-chat-stream before each LLM turn: whether lists are
    usable and the open follow-up question of the previous turn."""
    _, denied = await _access(caller)
    if denied:
        return {"enabled": False, "reason": denied, "pending": None}
    try:
        pending = await tickets.load_pending(_owner(caller), body.session_id, body.turn)
    except Exception as exc:  # Redis hiccup must not disable the lists
        logger.warning("pending lookup failed: %s", exc)
        pending = None
    return {"enabled": True, "reason": None, "unknown_speaker": caller.is_unknown_speaker,
            "pending": pending}


_TOOLS = {
    "add_items": agent.add_items,
    "query_items": agent.query_items,
    "complete_items": agent.complete_items,
    "reopen_items": agent.reopen_items,
    "update_item": agent.update_item,
    "remove_items": agent.remove_items,
    "confirm_delete": agent.confirm_delete,
    "cleanup_list": agent.cleanup_list,
    "manage_list": agent.manage_list,
}
_RESOLVED_STATUSES = {"added", "completed", "reopened", "updated", "removed", "deleted", "cleaned",
                      "list_created", "list_renamed", "default_set", "shopping_set"}


@app.post("/internal/tools/{tool}")
async def run_tool(tool: str, body: ToolCall, caller: Caller = Depends(verify)):
    """Always 200 with a result dict — alice-chat-stream phrases the reply."""
    handler = _TOOLS.get(tool)
    if handler is None:
        raise HTTPException(status_code=404, detail="Unknown tool")
    role, denied = await _access(caller)
    if denied:
        return agent._err(*agent.ERR_FORBIDDEN)

    owner = _owner(caller)
    pending = None
    if body.session_id and body.turn is not None:
        try:
            pending = await tickets.load_pending(owner, body.session_id, body.turn)
        except Exception as exc:
            logger.warning("pending lookup failed: %s", exc)
    user_id = None if caller.is_unknown_speaker else caller.user_id
    tz = tu.zone((await db.user_timezone(user_id)) if user_id else None)
    ctx = agent.Ctx(
        user_id=user_id, role=role, tz=tz, now=datetime.now(tz),
        channel="voice" if body.channel == "voice" else "chat",
        session_id=body.session_id, turn=body.turn,
        # A confirmation only counts as the answer to a question Alice asked.
        confirmed=bool(pending) and agent._flag(body.args or {}, "confirmed"),
    )
    try:
        result = await handler(ctx, body.args or {})
    except tu.InputError as exc:
        return agent._err("invalid_input", f"{exc} — korrigiere den Aufruf oder frage den Nutzer nach.")
    except Exception:
        logger.exception("Tool %s failed", tool)
        return agent._err("internal_error", "Interner Fehler im Listen-Dienst. Melde keinen Erfolg.")

    if body.session_id:
        try:
            if result.get("status") in agent.QUESTION_STATUSES and body.turn is not None:
                await tickets.save_pending(owner, body.session_id, body.turn, {
                    "tool": tool,
                    "args": body.args or {},
                    "result": {k: v for k, v in result.items() if k != "instruction"},
                })
            elif result.get("status") in _RESOLVED_STATUSES:
                # Errors (e.g. a premature same-turn confirm) must NOT clear
                # the question, or the user's "Ja" finds no ticket.
                await tickets.clear_pending(owner, body.session_id)
        except Exception as exc:
            logger.warning("pending store failed: %s", exc)
    return result
