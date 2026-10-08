"""
One-time delete confirmation tickets (PROJ-106, same mechanism as PROJ-87), stored briefly in Redis.

Why server-side: a prompt alone does not guarantee that the LLM asks before
deleting. A ticket is bound to user, chat session and the turn it was issued
in, and can only be redeemed in the *immediately following* turn of the same
session. So the model can never "ask and delete" within one request, and an
unanswered question expires as soon as the user says something else.
"""
from __future__ import annotations

import json
import logging
import os
import secrets

logger = logging.getLogger("alice-lists.tickets")

REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD") or None
TICKET_TTL_SECONDS = int(os.environ.get("DELETE_TICKET_TTL_SECONDS", "300"))
KEY_PREFIX = "alice:lists:delete-ticket:"

_client = None


class TicketError(Exception):
    """reason: unknown | same_turn | expired | wrong_owner"""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _redis():
    global _client
    if _client is None:
        import redis.asyncio as redis  # imported lazily so unit tests need no redis

        _client = redis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, password=REDIS_PASSWORD,
            decode_responses=True, socket_timeout=3,
        )
    return _client


def set_client(client) -> None:
    """Test hook: inject a fake async redis client."""
    global _client
    _client = client


async def issue(user_id: str, session_id: str, turn: int, target: dict) -> str:
    ticket = secrets.token_urlsafe(16)
    payload = {"user_id": user_id, "session_id": session_id, "turn": int(turn), "target": target}
    await _redis().set(KEY_PREFIX + ticket, json.dumps(payload), ex=TICKET_TTL_SECONDS)
    return ticket


async def redeem(ticket: str, user_id: str, session_id: str, turn: int) -> dict:
    """Validate and consume a ticket. Returns the stored target.

    A same-turn attempt is rejected WITHOUT consuming the ticket, so the user's
    "Ja" in the next turn still works after a premature model call.
    """
    if not ticket or len(ticket) > 64:
        raise TicketError("unknown")
    key = KEY_PREFIX + ticket
    raw = await _redis().get(key)
    if not raw:
        raise TicketError("unknown")
    data = json.loads(raw)

    if data.get("user_id") != user_id or data.get("session_id") != session_id:
        # Never consume someone else's ticket.
        raise TicketError("wrong_owner")
    issued_turn = int(data.get("turn", -1))
    if turn <= issued_turn:
        raise TicketError("same_turn")
    # Consume in every remaining case: either it is redeemed now or it is stale.
    # DEL is atomic: of two parallel redeems only one sees deleted == 1.
    if not await _redis().delete(key):
        raise TicketError("unknown")
    if turn != issued_turn + 1:
        raise TicketError("expired")
    return data["target"]


# ---------------------------------------------------------------------------
# Pending follow-up questions
# ---------------------------------------------------------------------------
# alice-chat-stream does not replay tool results into the next request's
# history, so a question Alice asked ("welcher Termin?", "nur diesen oder die
# Serie?", "wirklich löschen?") would lose its event refs / ticket. The last
# open question per (user, session) is kept here and handed back to
# alice-chat-stream for the immediately following turn only.
PENDING_PREFIX = "alice:lists:pending:"


def _pending_key(user_id: str, session_id: str) -> str:
    return f"{PENDING_PREFIX}{user_id}:{session_id}"


async def save_pending(user_id: str, session_id: str, turn: int, data: dict) -> None:
    await _redis().set(_pending_key(user_id, session_id),
                       json.dumps({"turn": int(turn), "data": data}), ex=TICKET_TTL_SECONDS)


async def clear_pending(user_id: str, session_id: str) -> None:
    await _redis().delete(_pending_key(user_id, session_id))


async def load_pending(user_id: str, session_id: str, turn: int) -> dict | None:
    """The open question from turn-1, or None (older ones have expired)."""
    raw = await _redis().get(_pending_key(user_id, session_id))
    if not raw:
        return None
    stored = json.loads(raw)
    if int(stored.get("turn", -1)) != int(turn) - 1:
        return None
    return stored.get("data")
