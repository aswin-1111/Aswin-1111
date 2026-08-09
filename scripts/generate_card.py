from __future__ import annotations

import argparse
import html
import os
from pathlib import Path

from analyze_github import analyze_profile

CARD_WIDTH = 760
CARD_HEIGHT = 540


def _format_number(value: int) -> str:
    return f"{value:,}"


def _metric_line(label: str, value: str) -> str:
    return f"  {label:<28}{value:>12}"


def _language_line(language: str, percent: float, scale: int = 24) -> str:
    bar_width = max(1, round((percent / 100) * scale))
    bar = "█" * bar_width
    return f"  {bar:<24} {language:<12} {percent:>5.1f}%"


def _build_lines(snapshot: dict) -> list[str]:
    lines = [
        "               DEVELOPER X-RAY",
        "",
        _metric_line("Repositories", _format_number(snapshot["repositories"])),
        _metric_line("Public projects", _format_number(snapshot["public_projects"])),
        _metric_line("Languages", _format_number(snapshot["languages"])),
        _metric_line("Total commits", _format_number(snapshot["total_commits"])),
        _metric_line("Stars received", _format_number(snapshot["stars_received"])),
        "",
        "  Most used",
    ]

    breakdown = snapshot.get("language_breakdown") or []
    if breakdown:
        for language_data in breakdown:
            lines.append(
                _language_line(str(language_data["language"]), float(language_data["percent"]))
            )
    else:
        lines.append("  No language data available")

    lines.extend(
        [
            "",
            _metric_line("🔥 Current streak", f"{snapshot['current_streak']} days"),
            _metric_line("🧩 Most active project", str(snapshot["most_active_project"])),
        ]
    )

    return lines


def _build_svg(snapshot: dict) -> str:
    lines = _build_lines(snapshot)

    line_height = 28
    content_start_y = 90

    text_elements = []
    for i, line in enumerate(lines):
        y = content_start_y + (i * line_height)
        escaped = html.escape(line)
        text_elements.append(f'<text x="60" y="{y}">{escaped}</text>')

    text_block = "\n    ".join(text_elements)

    return f"""<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"{CARD_WIDTH}\" height=\"{CARD_HEIGHT}\" viewBox=\"0 0 {CARD_WIDTH} {CARD_HEIGHT}\" role=\"img\" aria-label=\"Developer X-Ray for {html.escape(str(snapshot['username']))}\">
  <defs>
    <linearGradient id=\"bg\" x1=\"0%\" y1=\"0%\" x2=\"100%\" y2=\"100%\">
      <stop offset=\"0%\" stop-color=\"#0f2027\"/>
      <stop offset=\"50%\" stop-color=\"#203a43\"/>
      <stop offset=\"100%\" stop-color=\"#2c5364\"/>
    </linearGradient>
  </defs>
  <rect x=\"8\" y=\"8\" width=\"{CARD_WIDTH - 16}\" height=\"{CARD_HEIGHT - 16}\" rx=\"14\" fill=\"url(#bg)\" stroke=\"#b7c5d3\" stroke-width=\"2\"/>
  <line x1=\"25\" y1=\"60\" x2=\"{CARD_WIDTH - 25}\" y2=\"60\" stroke=\"#b7c5d3\" opacity=\"0.7\"/>
  <g font-family=\"JetBrains Mono, Consolas, Menlo, monospace\" font-size=\"22\" fill=\"#ecf2f8\" white-space=\"pre\">
    {text_block}
  </g>
</svg>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Developer X-Ray SVG card from GitHub profile data.")
    parser.add_argument("--username", default=os.getenv("GITHUB_USERNAME", "aswin-1111"), help="GitHub username")
    parser.add_argument(
        "--output",
        default="assets/developer-xray.svg",
        help="Output SVG path (relative to repo root)",
    )
    args = parser.parse_args()

    token = os.getenv("GITHUB_TOKEN")
    snapshot = analyze_profile(args.username, token=token)
    svg = _build_svg(snapshot)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")

    print(f"Generated {output_path} for @{args.username}")


if __name__ == "__main__":
    main()
