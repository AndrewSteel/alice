"""
HTTP clients: alice-google-connect (PROJ-86) and the Google Calendar REST API.

Errors are mapped to a small exception hierarchy so the agent layer can turn
them into the spec's user-facing outcomes:
  ReauthRequired      → "Google-Verbindung erneuern" (409 from PROJ-86, or 401 from Google)
  Unavailable         → "Kalender gerade nicht erreichbar" (timeouts, 5xx, rate limits,
                        a second transient 503 from the token endpoint)
  NotFound            → calendar / event no longer exists (404 / 410)
  GoogleRejected      → Google refused the request (400/403 other than rate limit)
"""
from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import quote

import httpx

logger = logging.getLogger("alice-calendar.google")

GOOGLE_CONNECT_URL = os.environ.get("GOOGLE_CONNECT_URL", "http://alice-google-connect:8008").rstrip("/")
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
HTTP_TIMEOUT = float(os.environ.get("GOOGLE_HTTP_TIMEOUT", "10"))
TOKEN_RETRY_DELAY = 0.4

SCOPE_CALENDAR_LIST = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"
SCOPE_EVENTS = "https://www.googleapis.com/auth/calendar.events"
CALENDAR_SCOPES = [SCOPE_CALENDAR_LIST, SCOPE_EVENTS]


class GoogleError(Exception):
    pass


class ReauthRequired(GoogleError):
    pass


class Unavailable(GoogleError):
    pass


class NotFound(GoogleError):
    pass


class GoogleRejected(GoogleError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def has_calendar_scope(scopes: list[str]) -> bool:
    return all(s in (scopes or []) for s in CALENDAR_SCOPES)


# ---------------------------------------------------------------------------
# alice-google-connect
# ---------------------------------------------------------------------------
async def list_connections(client: httpx.AsyncClient, user_token: str) -> list[dict]:
    try:
        resp = await client.get(
            f"{GOOGLE_CONNECT_URL}/google/connections",
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.error("google-connect unreachable: %s", exc)
        raise Unavailable("google-connect unreachable")
    if resp.status_code != 200:
        logger.error("google-connect /connections returned %s", resp.status_code)
        raise Unavailable(f"google-connect returned {resp.status_code}")
    data = resp.json()
    return data if isinstance(data, list) else []


async def get_access_token(client: httpx.AsyncClient, user_token: str, connection_id: str) -> str:
    """Fetch a valid access token; one automatic retry on the transient 503."""
    for attempt in (1, 2):
        try:
            resp = await client.post(
                f"{GOOGLE_CONNECT_URL}/google/connections/{connection_id}/token",
                headers={"Authorization": f"Bearer {user_token}"},
                timeout=HTTP_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            logger.error("token request failed: %s", exc)
            raise Unavailable("google-connect unreachable")

        if resp.status_code == 200:
            token = (resp.json() or {}).get("access_token")
            if not token:
                raise Unavailable("token response without access_token")
            return token
        if resp.status_code == 409:
            raise ReauthRequired(connection_id)
        if resp.status_code == 404:
            raise NotFound(connection_id)
        if resp.status_code == 503 and attempt == 1:
            await asyncio.sleep(TOKEN_RETRY_DELAY)
            continue
        logger.warning("token endpoint returned %s for %s", resp.status_code, connection_id)
        raise Unavailable(f"token endpoint returned {resp.status_code}")
    raise Unavailable("token endpoint retry exhausted")


# ---------------------------------------------------------------------------
# Google Calendar REST
# ---------------------------------------------------------------------------
def _cal(calendar_id: str) -> str:
    return quote(calendar_id, safe="")


async def _request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    access_token: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> dict | None:
    try:
        resp = await client.request(
            method, url,
            params=params,
            json=json_body,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        logger.warning("Google %s %s failed: %s", method, url, exc)
        raise Unavailable(str(exc))

    if resp.status_code in (200, 201):
        return resp.json()
    if resp.status_code == 204:
        return None
    if resp.status_code in (404, 410):
        raise NotFound(url)
    if resp.status_code == 401:
        raise ReauthRequired(url)
    body = resp.text[:300]
    if resp.status_code == 429 or resp.status_code >= 500 or (
        resp.status_code == 403 and ("rateLimitExceeded" in body or "userRateLimitExceeded" in body)
    ):
        logger.warning("Google %s %s → %s %s", method, url, resp.status_code, body)
        raise Unavailable(f"Google returned {resp.status_code}")
    logger.warning("Google %s %s rejected → %s %s", method, url, resp.status_code, body)
    raise GoogleRejected(resp.status_code, body)


async def list_calendars(client: httpx.AsyncClient, access_token: str) -> list[dict]:
    items: list[dict] = []
    page_token = None
    for _ in range(5):  # hard cap: 5 pages × 250
        params = {"maxResults": 250}
        if page_token:
            params["pageToken"] = page_token
        data = await _request(client, "GET", f"{CALENDAR_API}/users/me/calendarList", access_token, params) or {}
        items.extend(data.get("items") or [])
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return items


async def list_events(
    client: httpx.AsyncClient,
    access_token: str,
    calendar_id: str,
    time_min: str,
    time_max: str,
    tz_name: str,
    max_results: int = 250,
) -> list[dict]:
    data = await _request(
        client, "GET", f"{CALENDAR_API}/calendars/{_cal(calendar_id)}/events", access_token,
        params={
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",   # series → individual occurrences
            "orderBy": "startTime",
            "maxResults": max_results,
            "timeZone": tz_name,
        },
    ) or {}
    return [e for e in (data.get("items") or []) if e.get("status") != "cancelled"]


async def get_event(client: httpx.AsyncClient, access_token: str, calendar_id: str, event_id: str) -> dict:
    data = await _request(
        client, "GET", f"{CALENDAR_API}/calendars/{_cal(calendar_id)}/events/{quote(event_id, safe='')}",
        access_token,
    )
    if not data or data.get("status") == "cancelled":
        raise NotFound(event_id)
    return data


async def insert_event(client: httpx.AsyncClient, access_token: str, calendar_id: str, body: dict) -> dict:
    data = await _request(
        client, "POST", f"{CALENDAR_API}/calendars/{_cal(calendar_id)}/events", access_token, json_body=body,
    )
    if not data or not data.get("id"):
        raise Unavailable("insert without event id")
    return data


async def patch_event(
    client: httpx.AsyncClient, access_token: str, calendar_id: str, event_id: str, body: dict,
) -> dict:
    data = await _request(
        client, "PATCH", f"{CALENDAR_API}/calendars/{_cal(calendar_id)}/events/{quote(event_id, safe='')}",
        access_token, json_body=body,
    )
    if not data or not data.get("id"):
        raise Unavailable("patch without event id")
    return data


async def move_event(
    client: httpx.AsyncClient, access_token: str, calendar_id: str, event_id: str, destination: str,
) -> dict:
    data = await _request(
        client, "POST",
        f"{CALENDAR_API}/calendars/{_cal(calendar_id)}/events/{quote(event_id, safe='')}/move",
        access_token, params={"destination": destination},
    )
    if not data or not data.get("id"):
        raise Unavailable("move without event id")
    return data


async def delete_event(client: httpx.AsyncClient, access_token: str, calendar_id: str, event_id: str) -> None:
    await _request(
        client, "DELETE", f"{CALENDAR_API}/calendars/{_cal(calendar_id)}/events/{quote(event_id, safe='')}",
        access_token,
    )
