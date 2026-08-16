#!/usr/bin/env python3
"""
Developer X-Ray
----------------
Analyzes a GitHub profile (repos, languages, commits, contribution streaks)
and renders both a terminal box (stdout) and an SVG card (assets/xray-card.svg)
for embedding in a README.

Usage:
    GITHUB_TOKEN=ghp_xxx python3 scripts/xray.py [username]

If GITHUB_TOKEN is set, GraphQL is used for full stats (commits, streaks,
per-repo contribution counts). Without a token, the script falls back to
the unauthenticated REST API with a reduced feature set.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field

USERNAME = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("GH_USERNAME", "aswin-1111")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVG_PATH = os.path.join(REPO_ROOT, "assets", "xray-card.svg")

GRAPHQL_URL = "https://api.github.com/graphql"
REST_URL = "https://api.github.com"

BAR_WIDTH = 20  # characters, for the terminal bar chart
TOP_N_LANGUAGES = 5


@dataclass
class Stats:
    username: str
    repositories: int = 0
    public_projects: int = 0
    languages_count: int = 0
    total_commits: int | str = "n/a"
    total_stars: int = 0
    followers: int = 0
    member_since: str = "n/a"
    current_streak: int | str = "n/a"
    longest_streak: int | str = "n/a"
    most_active_project: str = "n/a"
    language_breakdown: list[tuple[str, float]] = field(default_factory=list)
    generated_at: str = field(default_factory=lambda: dt.date.today().isoformat())


def _http_json(url: str, payload: dict | None = None, headers: dict | None = None) -> dict:
    headers = headers or {}
    headers.setdefault("User-Agent", "developer-xray-script")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def graphql(query: str, variables: dict) -> dict:
    headers = {"Authorization": f"bearer {TOKEN}", "Content-Type": "application/json"}
    result = _http_json(GRAPHQL_URL, {"query": query, "variables": variables}, headers)
    if "errors" in result:
        raise RuntimeError(result["errors"])
    return result["data"]


REPOS_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    repositories(first: 50, after: $after, ownerAffiliations: OWNER, privacy: PUBLIC) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        isFork
        stargazerCount
        pushedAt
        languages(first: 10, orderBy: {field: SIZE, order: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""

CONTRIBUTIONS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      contributionCalendar {
        weeks { contributionDays { date contributionCount } }
      }
      commitContributionsByRepository(maxRepositories: 50) {
        repository { name }
        contributions { totalCount }
      }
    }
  }
}
"""


def fetch_via_graphql(username: str) -> Stats:
    stats = Stats(username=username)

    # --- repositories + languages ---
    nodes = []
    after = None
    created_at = None
    while True:
        data = graphql(REPOS_QUERY, {"login": username, "after": after})
        user = data["user"]
        created_at = user["createdAt"]
        stats.followers = user["followers"]["totalCount"]
        repos = user["repositories"]
        nodes.extend(repos["nodes"])
        if repos["pageInfo"]["hasNextPage"]:
            after = repos["pageInfo"]["endCursor"]
        else:
            break

    stats.repositories = len(nodes)
    non_fork = [n for n in nodes if not n["isFork"]]
    stats.public_projects = len(non_fork)
    stats.total_stars = sum(n["stargazerCount"] for n in non_fork)
    stats.member_since = created_at[:4]

    lang_bytes: dict[str, int] = {}
    for repo in non_fork:
        for edge in repo["languages"]["edges"]:
            lang_bytes[edge["node"]["name"]] = lang_bytes.get(edge["node"]["name"], 0) + edge["size"]
    stats.languages_count = len(lang_bytes)
    total_bytes = sum(lang_bytes.values()) or 1
    ranked = sorted(lang_bytes.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N_LANGUAGES]
    stats.language_breakdown = [(name, size / total_bytes * 100) for name, size in ranked]

    # --- contributions, year by year, from account creation to today ---
    start_year = int(created_at[:4])
    this_year = dt.date.today().year
    total_commits = 0
    repo_contribs: dict[str, int] = {}
    all_days: list[tuple[dt.date, int]] = []

    for year in range(start_year, this_year + 1):
        frm = f"{year}-01-01T00:00:00Z"
        to = f"{year}-12-31T23:59:59Z"
        try:
            data = graphql(CONTRIBUTIONS_QUERY, {"login": username, "from": frm, "to": to})
        except Exception:
            continue
        cc = data["user"]["contributionsCollection"]
        total_commits += cc["totalCommitContributions"]
        for repo in cc["commitContributionsByRepository"]:
            name = repo["repository"]["name"]
            repo_contribs[name] = repo_contribs.get(name, 0) + repo["contributions"]["totalCount"]
        for week in cc["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                d = dt.date.fromisoformat(day["date"])
                if d <= dt.date.today():
                    all_days.append((d, day["contributionCount"]))

    stats.total_commits = total_commits
    if repo_contribs:
        stats.most_active_project = max(repo_contribs.items(), key=lambda kv: kv[1])[0]
    elif non_fork:
        stats.most_active_project = max(non_fork, key=lambda n: n["pushedAt"])["name"]

    all_days.sort(key=lambda t: t[0])
    stats.current_streak, stats.longest_streak = _compute_streaks(all_days)

    return stats


def _compute_streaks(days: list[tuple[dt.date, int]]) -> tuple[int, int]:
    if not days:
        return "n/a", "n/a"
    longest = current = 0
    running = 0
    prev_date = None
    for d, count in days:
        if prev_date is not None and (d - prev_date).days != 1:
            running = 0
        running = running + 1 if count > 0 else 0
        longest = max(longest, running)
        prev_date = d
    # current streak: walk backwards from today (or yesterday) while count > 0
    by_date = {d: c for d, c in days}
    cursor = dt.date.today()
    if by_date.get(cursor, 0) == 0:
        cursor -= dt.timedelta(days=1)  # today may not have contributions yet
    streak = 0
    while by_date.get(cursor, 0) > 0:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak, longest


def fetch_via_rest(username: str) -> Stats:
    """Reduced-feature fallback when no token is available."""
    stats = Stats(username=username)
    headers = {"Accept": "application/vnd.github+json"}
    user = _http_json(f"{REST_URL}/users/{username}", headers=headers)
    stats.followers = user.get("followers", 0)
    stats.member_since = (user.get("created_at") or "")[:4] or "n/a"

    repos = []
    page = 1
    while True:
        batch = _http_json(f"{REST_URL}/users/{username}/repos?per_page=100&page={page}", headers=headers)
        if not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    stats.repositories = len(repos)
    non_fork = [r for r in repos if not r.get("fork")]
    stats.public_projects = len(non_fork)
    stats.total_stars = sum(r.get("stargazers_count", 0) for r in non_fork)

    lang_count: dict[str, int] = {}
    for r in non_fork:
        lang = r.get("language")
        if lang:
            lang_count[lang] = lang_count.get(lang, 0) + 1
    stats.languages_count = len(lang_count)
    total = sum(lang_count.values()) or 1
    ranked = sorted(lang_count.items(), key=lambda kv: kv[1], reverse=True)[:TOP_N_LANGUAGES]
    stats.language_breakdown = [(name, n / total * 100) for name, n in ranked]

    if non_fork:
        stats.most_active_project = max(non_fork, key=lambda r: r.get("pushed_at", ""))["name"]

    return stats


def fetch_stats(username: str) -> Stats:
    if TOKEN:
        try:
            return fetch_via_graphql(username)
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
            print(f"warning: GraphQL fetch failed ({exc}); falling back to REST", file=sys.stderr)
    return fetch_via_rest(username)


def render_terminal(stats: Stats) -> str:
    lines = []
    width = 48
    lines.append("╭" + "─" * width + "╮")
    title = "DEVELOPER X-RAY"
    lines.append("│" + title.center(width) + "│")
    lines.append("├" + "─" * width + "┤")
    lines.append("│" + " " * width + "│")

    def row(label: str, value: str) -> str:
        return "│  " + label.ljust(width - len(str(value)) - 5) + str(value) + "  │"

    lines.append(row("Repositories", stats.repositories))
    lines.append(row("Public projects", stats.public_projects))
    lines.append(row("Languages", stats.languages_count))
    lines.append(row("Total commits", stats.total_commits))
    lines.append(row("Total stars", stats.total_stars))
    lines.append(row("Followers", stats.followers))
    lines.append("│" + " " * width + "│")
    lines.append("│  Most used" + " " * (width - 11) + "│")

    max_pct = stats.language_breakdown[0][1] if stats.language_breakdown else 1
    for name, pct in stats.language_breakdown:
        blocks = max(1, round(pct / max_pct * BAR_WIDTH))
        bar = "█" * blocks
        text = f"  {bar} {name:<12} {pct:4.0f}%"
        lines.append("│" + text.ljust(width) + "│")

    lines.append("│" + " " * width + "│")
    lines.append(row("\U0001f525 Current streak", f"{stats.current_streak} days"))
    lines.append(row("\U0001f9e9 Longest streak", f"{stats.longest_streak} days"))
    lines.append(row("\U0001f4c8 Most active project", stats.most_active_project))
    lines.append(row("\U0001f393 Member since", stats.member_since))
    lines.append("│" + " " * width + "│")
    lines.append("╰" + "─" * width + "╯")
    return "\n".join(lines)


PALETTE = {
    "bg": "#0d1117",
    "border": "#30363d",
    "text": "#c9d1d9",
    "dim": "#8b949e",
    "blue": "#58a6ff",
    "green": "#3fb950",
    "purple": "#a371f7",  # used sparingly, single accent only
}


def render_svg(stats: Stats) -> str:
    p = PALETTE
    lang_rows = len(stats.language_breakdown)
    height = 430 + lang_rows * 24
    y = 40
    parts: list[str] = []
    parts.append(
        f'<svg width="480" height="{height}" viewBox="0 0 480 {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Developer X-Ray stats card">'
    )
    parts.append(f'<rect x="0.5" y="0.5" width="479" height="{height-1}" rx="10" fill="{p["bg"]}" stroke="{p["border"]}"/>')
    parts.append(
        f'<text x="240" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
        f'font-size="15" font-weight="700" fill="{p["blue"]}" text-anchor="middle">DEVELOPER X-RAY</text>'
    )
    y += 14
    parts.append(f'<line x1="0" y1="{y}" x2="480" y2="{y}" stroke="{p["border"]}"/>')

    def stat_row(label: str, value, y: int, color: str = p["text"]) -> str:
        return (
            f'<text x="24" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
            f'font-size="13" fill="{p["dim"]}" text-anchor="start">{label}</text>'
            f'<text x="456" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
            f'font-size="13" font-weight="700" fill="{color}" text-anchor="end">{value}</text>'
        )

    y += 32
    for label, value in [
        ("Repositories", stats.repositories),
        ("Public projects", stats.public_projects),
        ("Languages", stats.languages_count),
        ("Total commits", stats.total_commits),
        ("Total stars", stats.total_stars),
        ("Followers", stats.followers),
    ]:
        parts.append(stat_row(label, value, y))
        y += 26

    y += 8
    parts.append(
        f'<text x="24" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
        f'font-size="11" font-weight="700" fill="{p["dim"]}" text-anchor="start">MOST USED</text>'
    )
    y += 26
    max_pct = stats.language_breakdown[0][1] if stats.language_breakdown else 1
    bar_colors = [p["blue"], p["green"], p["blue"], p["green"], p["blue"]]
    for i, (name, pct) in enumerate(stats.language_breakdown):
        bar_w = round(pct / max_pct * 260, 1)
        color = bar_colors[i % len(bar_colors)]
        parts.append(
            f'<text x="24" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
            f'font-size="12" fill="{p["text"]}" text-anchor="start">{name}</text>'
        )
        parts.append(f'<rect x="156" y="{y-12}" width="260" height="8" rx="4" fill="#21262d"/>')
        parts.append(f'<rect x="156" y="{y-12}" width="{bar_w}" height="8" rx="4" fill="{color}"/>')
        parts.append(
            f'<text x="456" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
            f'font-size="12" fill="{p["dim"]}" text-anchor="end">{pct:.0f}%</text>'
        )
        y += 24

    y += 12
    parts.append(f'<line x1="0" y1="{y}" x2="480" y2="{y}" stroke="{p["border"]}"/>')
    y += 24

    def dot_row(color: str, label: str, value, y: int) -> str:
        return (
            f'<circle cx="28" cy="{y-5}" r="4" fill="{color}"/>'
            f'<text x="40" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
            f'font-size="13" fill="{p["dim"]}" text-anchor="start">{label}</text>'
            f'<text x="456" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
            f'font-size="13" font-weight="700" fill="{p["text"]}" text-anchor="end">{value}</text>'
        )

    parts.append(dot_row(p["green"], "Current streak", f"{stats.current_streak} days", y))
    y += 26
    parts.append(dot_row(p["blue"], "Longest streak", f"{stats.longest_streak} days", y))
    y += 26
    parts.append(dot_row(p["purple"], "Most active project", stats.most_active_project, y))
    y += 26
    parts.append(dot_row(p["blue"], "Member since", stats.member_since, y))
    y += 30

    parts.append(
        f'<text x="240" y="{y}" font-family="\'Cascadia Code\',\'Courier New\',monospace" '
        f'font-size="10" fill="{p["dim"]}" text-anchor="middle">@{stats.username} &#183; generated {stats.generated_at}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts)


def _placeholder_stats(username: str) -> Stats:
    """Used when the API is unreachable (e.g. no token + rate-limited).
    The next scheduled Actions run (authenticated) will overwrite this
    with real numbers, so we surface 'pending' rather than fabricate data.
    """
    s = Stats(username=username)
    s.repositories = "pending"
    s.public_projects = "pending"
    s.languages_count = "pending"
    s.total_commits = "pending"
    s.total_stars = "pending"
    s.followers = "pending"
    s.member_since = "pending"
    s.current_streak = "pending"
    s.longest_streak = "pending"
    s.most_active_project = "pending first sync"
    s.language_breakdown = [("awaiting first sync", 100.0)]
    return s


def main() -> None:
    try:
        stats = fetch_stats(USERNAME)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        print(f"warning: could not reach GitHub API ({exc}); writing placeholder card", file=sys.stderr)
        stats = _placeholder_stats(USERNAME)
    print(render_terminal(stats))

    svg = render_svg(stats)
    os.makedirs(os.path.dirname(SVG_PATH), exist_ok=True)
    with open(SVG_PATH, "w") as f:
        f.write(svg + "\n")
    print(f"\nWrote {SVG_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
