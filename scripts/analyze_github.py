from __future__ import annotations

import json
import sys
from typing import Dict, List, Mapping
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from language_stats import summarize_languages
from repo_health import current_streak_from_events, most_active_project_from_events

GITHUB_API_BASE = "https://api.github.com"


def _api_get(path: str, token: str | None = None, params: Dict[str, str | int] | None = None):
    query = f"?{urlencode(params)}" if params else ""
    url = f"{GITHUB_API_BASE}{path}{query}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "developer-xray-generator",
    }
    if token:
        headers["Authorization"] = "Bearer " + token

    request = Request(url, headers=headers)
    try:
        with urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        print(f"GitHub API request failed ({error.code}) for {path}.", file=sys.stderr)
    except URLError as error:
        print(f"GitHub API request failed for {path}: {error.reason}", file=sys.stderr)

    return []


def fetch_repositories(username: str, token: str | None = None) -> List[Mapping]:
    repositories = []
    page = 1

    while True:
        batch = _api_get(
            f"/users/{username}/repos",
            token=token,
            params={"per_page": 100, "page": page, "sort": "updated"},
        )
        if not batch:
            break

        repositories.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    return repositories


def fetch_public_events(username: str, token: str | None = None, pages: int = 3) -> List[Mapping]:
    events: List[Mapping] = []

    for page in range(1, pages + 1):
        batch = _api_get(
            f"/users/{username}/events/public",
            token=token,
            params={"per_page": 100, "page": page},
        )
        if not batch:
            break
        events.extend(batch)

    return events


def analyze_profile(username: str, token: str | None = None) -> Dict[str, object]:
    repositories = fetch_repositories(username, token=token)
    events = fetch_public_events(username, token=token)

    public_projects = [repo for repo in repositories if not repo.get("fork")]
    stars_received = sum(int(repo.get("stargazers_count", 0)) for repo in repositories)

    pushes = [event for event in events if event.get("type") == "PushEvent"]
    total_commits = 0
    for event in pushes:
        payload = event.get("payload") or {}
        total_commits += int(payload.get("size") or 0)

    language_breakdown = summarize_languages(public_projects)
    language_count = len({repo.get("language") for repo in public_projects if repo.get("language")})

    return {
        "username": username,
        "repositories": len(repositories),
        "public_projects": len(public_projects),
        "languages": language_count,
        "total_commits": total_commits,
        "stars_received": stars_received,
        "language_breakdown": language_breakdown,
        "current_streak": current_streak_from_events(events),
        "most_active_project": most_active_project_from_events(events),
    }
