from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping


def _event_date(event: Mapping) -> datetime.date | None:
    created = event.get("created_at")
    if not created:
        return None

    try:
        return datetime.fromisoformat(str(created).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def current_streak_from_events(events: Iterable[Mapping]) -> int:
    """Estimate streak days from recent public events."""
    activity_dates = set()
    for event in events:
        event_date = _event_date(event)
        if event_date:
            activity_dates.add(event_date)
    if not activity_dates:
        return 0

    today = datetime.now(timezone.utc).date()
    cursor = today if today in activity_dates else today - timedelta(days=1)

    streak = 0
    while cursor in activity_dates:
        streak += 1
        cursor -= timedelta(days=1)

    return streak


def most_active_project_from_events(events: Iterable[Mapping], fallback: str = "N/A") -> str:
    """Return most frequently touched repository in the current event window."""
    repo_counter = Counter()

    for event in events:
        repo = event.get("repo") or {}
        repo_name = repo.get("name")
        if repo_name:
            repo_counter[str(repo_name)] += 1

    if repo_counter:
        return repo_counter.most_common(1)[0][0]

    return fallback
