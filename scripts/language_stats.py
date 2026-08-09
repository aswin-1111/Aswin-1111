from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Mapping


def summarize_languages(repositories: Iterable[Mapping], top_n: int = 4) -> List[Dict[str, float]]:
    """Build weighted language percentages from repository metadata."""
    totals = defaultdict(float)

    for repo in repositories:
        language = repo.get("language")
        if not language:
            continue

        weight = float(repo.get("size") or 1)
        totals[str(language)] += max(weight, 1.0)

    total_weight = sum(totals.values())
    if total_weight <= 0:
        return []

    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)

    summary = []
    for language, weight in ranked[:top_n]:
        percent = (weight / total_weight) * 100
        summary.append({"language": language, "percent": round(percent, 1)})

    return summary
