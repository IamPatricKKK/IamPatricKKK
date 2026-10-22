"""Render the profile activity card (light + dark SVG) from the GitHub contribution calendar.

Usage: GITHUB_TOKEN=... python3 .github/scripts/activity.py <login> <out_dir>
"""

import json
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone

QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

THEMES = {
    "light": dict(fg="#1f2328", muted="#59636e", grid="#d1d9e0", accent="#0969da", accent2="#8250df"),
    "dark": dict(fg="#f0f6fc", muted="#9198a1", grid="#3d444d", accent="#4493f8", accent2="#ab7df8"),
}

W, H = 1200, 340
CHART_L, CHART_R, CHART_TOP, CHART_BASE = 40, 1160, 176, 296


def fetch_days(login: str, token: str) -> tuple[int, list[tuple[date, int]]]:
    to = datetime.now(timezone.utc)
    frm = to - timedelta(days=365)
    body = json.dumps({
        "query": QUERY,
        "variables": {"login": login, "from": frm.isoformat(), "to": to.isoformat()},
    }).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if "errors" in payload:
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    cal = payload["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    days = [
        (date.fromisoformat(d["date"]), d["contributionCount"])
        for w in cal["weeks"]
        for d in w["contributionDays"]
    ]
    return cal["totalContributions"], days


def streaks(days: list[tuple[date, int]]) -> tuple[int, int]:
    longest = run = 0
    for _, n in days:
        run = run + 1 if n else 0
        longest = max(longest, run)
    current = 0
    tail = list(days)
    # Today may have no contributions yet; that does not break the streak.
    if tail and tail[-1][1] == 0:
        tail.pop()
    for _, n in reversed(tail):
        if not n:
            break
        current += 1
    return longest, current


def weekly(days: list[tuple[date, int]]) -> list[tuple[date, int]]:
    weeks: list[tuple[date, int]] = []
    for i in range(0, len(days), 7):
        chunk = days[i:i + 7]
        weeks.append((chunk[0][0], sum(n for _, n in chunk)))
    return weeks


def smooth_path(pts: list[tuple[float, float]]) -> str:
    """Catmull-Rom spline through the points, as cubic Bezier segments."""
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        # Keep the curve from dipping below the baseline between zero weeks.
        c1 = (c1[0], min(c1[1], CHART_BASE))
        c2 = (c2[0], min(c2[1], CHART_BASE))
        d += f" C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}"
    return d


def fmt(n: int) -> str:
    return f"{n:,}"


def render(theme: dict, total: int, days: list[tuple[date, int]]) -> str:
    weeks = weekly(days)
    peak = max((n for _, n in weeks), default=0) or 1
    step = (CHART_R - CHART_L) / max(len(weeks) - 1, 1)
    pts = [
        (CHART_L + i * step, CHART_BASE - (n / peak) * (CHART_BASE - CHART_TOP))
        for i, (_, n) in enumerate(weeks)
    ]
    line = smooth_path(pts)
    area = f"{line} L{pts[-1][0]:.1f},{CHART_BASE} L{pts[0][0]:.1f},{CHART_BASE} Z"
    end_x, end_y = pts[-1]

    longest, current = streaks(days)
    active = sum(1 for _, n in days if n)
    metrics = [
        (fmt(total), "CONTRIBUTIONS"),
        (fmt(active), "ACTIVE DAYS"),
        (f"{longest} d", "LONGEST STREAK"),
        (f"{current} d", "CURRENT STREAK"),
    ]
    metric_svg = "\n".join(
        f'  <g class="in" style="animation-delay:{0.1 + i * 0.12:.2f}s">'
        f'<text class="sans" x="{40 + i * 290}" y="92" font-size="40" font-weight="700" letter-spacing="-1" fill="{theme["fg"]}">{value}</text>'
        f'<text class="mono" x="{42 + i * 290}" y="120" font-size="12" letter-spacing="2" fill="{theme["muted"]}">{label}</text></g>'
        for i, (value, label) in enumerate(metrics)
    )

    months = []
    prev = None
    for i, (start, _) in enumerate(weeks):
        if start.month != prev and i > 0:
            x = CHART_L + i * step
            if x < CHART_R - 30:
                months.append(
                    f'<text class="mono" x="{x:.1f}" y="324" font-size="11" fill="{theme["muted"]}" text-anchor="middle">{start.strftime("%b")}</text>'
                )
        prev = start.month
    month_svg = "\n  ".join(months)

    grid = "\n  ".join(
        f'<line x1="{CHART_L}" x2="{CHART_R}" y1="{y:.1f}" y2="{y:.1f}" stroke="{theme["grid"]}" stroke-dasharray="2 6"/>'
        for y in (CHART_TOP, (CHART_TOP + CHART_BASE) / 2)
    )
    span = f"{days[0][0].strftime('%b %Y')} – {days[-1][0].strftime('%b %Y')}"

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{total} contributions in the last 12 months">
  <title>{total} contributions in the last 12 months</title>
  <defs>
    <linearGradient id="stroke" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="{theme["accent"]}"/>
      <stop offset="1" stop-color="{theme["accent2"]}"/>
    </linearGradient>
    <linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{theme["accent"]}" stop-opacity="0.28"/>
      <stop offset="1" stop-color="{theme["accent"]}" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <style>
    .sans {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace; }}
    .in {{ opacity: 0; animation: in 0.7s cubic-bezier(.2,.7,.2,1) forwards; }}
    @keyframes in {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}
    .line {{ stroke-dasharray: 1; stroke-dashoffset: 1; animation: draw 2.2s cubic-bezier(.45,0,.2,1) 0.5s forwards; }}
    @keyframes draw {{ to {{ stroke-dashoffset: 0; }} }}
    .area {{ opacity: 0; animation: fade 1.2s ease-out 1.6s forwards; }}
    .end {{ opacity: 0; animation: fade 0.4s ease-out 2.6s forwards; }}
    @keyframes fade {{ to {{ opacity: 1; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .in, .area, .end {{ animation: none; opacity: 1; }}
      .line {{ animation: none; stroke-dashoffset: 0; }}
    }}
  </style>

  <text class="mono" x="{CHART_R}" y="40" font-size="12" letter-spacing="1" fill="{theme["muted"]}" text-anchor="end">{span}</text>
{metric_svg}

  {grid}
  <line x1="{CHART_L}" x2="{CHART_R}" y1="{CHART_BASE}" y2="{CHART_BASE}" stroke="{theme["grid"]}"/>
  <path class="area" d="{area}" fill="url(#fill)"/>
  <path class="line" d="{line}" pathLength="1" fill="none" stroke="url(#stroke)" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <g class="end">
    <circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="4" fill="{theme["accent2"]}"/>
    <circle cx="{end_x:.1f}" cy="{end_y:.1f}" r="4" fill="none" stroke="{theme["accent2"]}" stroke-width="2">
      <animate attributeName="r" values="4;14" dur="1.8s" begin="2.6s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.8;0" dur="1.8s" begin="2.6s" repeatCount="indefinite"/>
    </circle>
  </g>
  {month_svg}
</svg>
"""


def main() -> None:
    login, out_dir = sys.argv[1], sys.argv[2]
    total, days = fetch_days(login, os.environ["GITHUB_TOKEN"])
    os.makedirs(out_dir, exist_ok=True)
    for name, theme in THEMES.items():
        with open(os.path.join(out_dir, f"activity-{name}.svg"), "w", encoding="utf-8") as f:
            f.write(render(theme, total, days))
    print(f"{login}: {total} contributions, {len(days)} days")


if __name__ == "__main__":
    main()
