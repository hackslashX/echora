from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import re
import threading
import time
import unicodedata
from zoneinfo import ZoneInfo

import httpx


@dataclass(frozen=True)
class Listen:
    artist: str
    title: str
    played_at: datetime


_cache: dict[tuple[str, str, int], tuple[float, list[Listen]]] = {}
_cache_lock = threading.Lock()


def _normalize(value: str | None) -> str:
    folded = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


def recent_listens(username: str, api_key: str, since: datetime) -> list[Listen]:
    since_unix = int(since.timestamp())
    cache_key = (username.casefold(), hashlib.sha256(api_key.encode()).hexdigest(), since_unix // 3600)
    with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < 300:
            return list(cached[1])
    listens: list[Listen] = []
    page = 1
    with httpx.Client(timeout=20) as client:
        while page <= 20:
            response = client.get("https://ws.audioscrobbler.com/2.0/", params={
                "method": "user.getrecenttracks", "user": username, "api_key": api_key,
                "format": "json", "from": since_unix, "limit": 200, "page": page,
            })
            response.raise_for_status()
            payload = response.json()
            if payload.get("error"):
                raise RuntimeError(str(payload.get("message") or "Last.fm rejected the history request"))
            recent = payload.get("recenttracks", {})
            tracks = recent.get("track", [])
            for track in tracks:
                timestamp = track.get("date", {}).get("uts")
                if not timestamp:
                    continue
                listens.append(Listen(
                    artist=str(track.get("artist", {}).get("#text") or ""),
                    title=str(track.get("name") or ""),
                    played_at=datetime.fromtimestamp(int(timestamp), tz=timezone.utc),
                ))
            pages = int(recent.get("@attr", {}).get("totalPages") or 1)
            if page >= pages:
                break
            page += 1
    with _cache_lock:
        _cache[cache_key] = (time.monotonic(), list(listens))
    return listens


def track_listen_counts(
    rows: list[dict[str, object]], listens: list[Listen], timezone_name: str,
    period_start: str | None = None, period_end: str | None = None,
) -> tuple[dict[str, int], dict[str, int]]:
    exact: dict[tuple[str, str], str] = {}
    title_ids: dict[str, list[str]] = {}
    for row in rows:
        identifier = str(row["id"])
        title = _normalize(str(row.get("title") or ""))
        exact[(_normalize(str(row.get("artist") or "")), title)] = identifier
        title_ids.setdefault(title, []).append(identifier)
    all_counts: Counter[str] = Counter()
    period_counts: Counter[str] = Counter()
    zone = ZoneInfo(timezone_name)
    start_minutes = _minutes(period_start) if period_start else None
    end_minutes = _minutes(period_end) if period_end else None
    for listen in listens:
        title = _normalize(listen.title)
        identifier = exact.get((_normalize(listen.artist), title))
        if identifier is None and len(title_ids.get(title, [])) == 1:
            identifier = title_ids[title][0]
        if identifier is None:
            continue
        all_counts[identifier] += 1
        if start_minutes is not None and end_minutes is not None:
            local = listen.played_at.astimezone(zone)
            minute = local.hour * 60 + local.minute
            in_period = start_minutes <= minute < end_minutes if start_minutes < end_minutes else minute >= start_minutes or minute < end_minutes
            if in_period:
                period_counts[identifier] += 1
    return dict(all_counts), dict(period_counts)


def _minutes(value: str) -> int:
    hour, minute = value.split(":", 1)
    return int(hour) * 60 + int(minute)
