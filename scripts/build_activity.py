#!/usr/bin/env python3
"""
Builds the activity card the README embeds, in the same hand as the rest of
assets/.

    python3 scripts/build_activity.py [output.svg]

Why not a stats service or the metrics action
---------------------------------------------
The public stats services this README used to embed went away (503 and 402),
and the metrics action needs a personal access token: given only the
workflow's own token it renders "0 commits, 1 repository", which is worse
than nothing. Everything here is public data that needs no personal token:

  * the contribution calendar GitHub publishes at /users/<login>/contributions
  * the REST API's public repository and language endpoints

GITHUB_TOKEN is used when present, only to raise the rate limit.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import urllib.request
from html import unescape

from build_assets import (ACCENT, FAINT, INK, INK_DIM, LINE2, MUTED, OUT, STAGE4, W, Doc, measure, n, panel)

LOGIN = os.environ.get("GITHUB_LOGIN", "oyinlola-tech")
TOKEN = os.environ.get("GITHUB_TOKEN", "")

LEVELS = [STAGE4, "#4a2d14", "#87501f", "#c4742f", ACCENT]
LANG_COLORS = ["#ffb067", "#56d6c0", "#6e92ff", "#9b8cff", "#5ee2a0", "#d8e2ff", "#ff8f43"]
OTHER = "#3a4150"


def fetch(url: str, api: bool = False, page: bool = False) -> bytes:
    headers = {"User-Agent": f"{LOGIN}-profile-readme"}
    if page:
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)", "Accept": "text/html"}
    elif api:
        headers["Accept"] = "application/vnd.github+json"
        if TOKEN:
            headers["Authorization"] = f"Bearer {TOKEN}"
    else:
        headers["X-Requested-With"] = "XMLHttpRequest"
    last = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as r:
                return r.read()
        except Exception as e:  # flaky networks are the normal case, not the exception
            last = e
    raise SystemExit(f"could not fetch {url}: {last}")


def calendar() -> list[tuple[dt.date, int, int]]:
    """[(date, count, level)] for the last year, oldest first."""
    html = fetch(f"https://github.com/users/{LOGIN}/contributions").decode("utf-8", "replace")
    cells = {}
    for tag in re.findall(r"<td[^>]*ContributionCalendar-day[^>]*>", html):
        date = re.search(r'data-date="([\d-]+)"', tag)
        cid = re.search(r'id="([^"]+)"', tag)
        level = re.search(r'data-level="(\d)"', tag)
        if date and cid and level:
            cells[cid.group(1)] = [dt.date.fromisoformat(date.group(1)), 0, int(level.group(1))]
    for cid, text in re.findall(r'<tool-tip[^>]*for="([^"]+)"[^>]*>([^<]*)</tool-tip>', html):
        m = re.match(r"\s*([\d,]+) contribution", unescape(text))
        if cid in cells and m:
            cells[cid][1] = int(m.group(1).replace(",", ""))
    days = sorted((tuple(v) for v in cells.values()), key=lambda d: d[0])
    if len(days) < 300:
        raise SystemExit(f"contribution calendar looked wrong: only {len(days)} days parsed")
    return days


def activity_is_private() -> bool:
    """GitHub's "Make profile private and hide activity" setting zeroes the calendar for everyone."""
    return b"activity is private" in fetch(f"https://github.com/{LOGIN}", page=True)


def repositories():
    repos, page = [], 1
    while True:
        batch = json.loads(fetch(f"https://api.github.com/users/{LOGIN}/repos?per_page=100&type=owner&page={page}", api=True))
        repos += batch
        if len(batch) < 100:
            break
        page += 1
    return repos


def languages(repos) -> dict[str, int]:
    totals: dict[str, int] = {}
    for r in repos:
        if r["fork"] or r["archived"] or not r.get("language"):
            continue
        for lang, size in json.loads(fetch(r["languages_url"], api=True)).items():
            totals[lang] = totals.get(lang, 0) + size
    return totals


def streaks(days):
    today = dt.date.today()
    past = [d for d in days if d[0] <= today]
    longest = run = 0
    for _, count, _ in past:
        run = run + 1 if count else 0
        longest = max(longest, run)
    current = 0
    tail = past[:-1] if past and past[-1][1] == 0 else past  # today may simply not have happened yet
    for _, count, _ in reversed(tail):
        if not count:
            break
        current += 1
    return current, longest


def build(path):
    days = calendar()
    repos = repositories()
    langs = languages(repos)
    own = [r for r in repos if not r["fork"]]
    total = sum(c for _, c, _ in days)
    active = sum(1 for _, c, _ in days if c)
    busiest = max(days, key=lambda d: d[1])
    current, longest = streaks(days)
    stars = sum(r["stargazers_count"] for r in own)

    # With activity hidden in the account settings the calendar is all zeros.
    # Drawing "0 contributions" would be a lie, so the card falls back to what
    # is genuinely public, and grows the calendar back the day it is unhidden.
    hidden = total == 0 and activity_is_private()
    month_ago = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    recent = sum(1 for r in own if (r.get("pushed_at") or "") >= month_ago)

    h = 388
    if hidden:
        doc = Doc(W, h, f"{len(own)} public repositories", f"{stars} stars, {len(langs)} languages, {recent} repositories pushed in the last 30 days.")
    else:
        doc = Doc(W, h, f"{total:,} public contributions in the last year",
                  f"{active} active days, longest streak {longest} days, {len(own)} public repositories.")
    panel(doc)
    x0 = 30

    # headline
    doc.text(x0, 42, "IN PUBLIC, ON GITHUB" if hidden else "THE LAST TWELVE MONTHS, IN PUBLIC", "mono", 10.5, ACCENT, track=0.12)
    wt = doc.text(x0, 92, f"{len(own)}" if hidden else f"{total:,}", "displayb", 44, INK, track=-0.025)
    doc.text(x0 + wt + 12, 92, "public repositories" if hidden else "contributions", "body", 16, INK_DIM)

    if hidden:
        facts = [(f"{recent}", "pushed in the last 30 days"), (f"{len(langs)}", "languages"),
                 (f"{stars}", "stars"), (f"{sum(1 for r in own if r.get('homepage'))}", "with a live deployment")]
    else:
        facts = [(f"{current}", "day streak now"), (f"{longest}", "longest streak, days"),
                 (f"{active}", "active days"), (f"{busiest[1]}", f"most in a day · {busiest[0].strftime('%-d %b')}")]
    fx = 380
    fw = (W - 30 - fx) / len(facts)
    for i, (value, label) in enumerate(facts):
        cx = fx + i * fw
        doc.add(f'<path d="M{n(cx)} 56V98" stroke="{LINE2}"/>')
        doc.text(cx + 14, 76, value, "display", 22, INK, track=-0.01)
        words, line, ly = label.split(), "", 93
        lines = []
        for w_ in words:
            trial = f"{line} {w_}".strip()
            if line and measure(trial, "mono", 9.8, 0.02) > fw - 22:
                lines.append(line)
                line = w_
            else:
                line = trial
        lines.append(line)
        for ln in lines[:2]:
            doc.text(cx + 14, ly, ln, "mono", 9.8, MUTED, track=0.02)
            ly += 12.5

    gy, gh_ = 86, 0.0
    if not hidden:
        # calendar
        first = days[0][0]
        start = first - dt.timedelta(days=(first.weekday() + 1) % 7)  # back to Sunday
        weeks = ((days[-1][0] - start).days // 7) + 1
        gy = 150
        pitch = (W - 60) / weeks
        cell = pitch - 3
        last_month = None
        for date, count, level in days:
            col, row = divmod((date - start).days, 7)
            cx = x0 + col * pitch
            if date.day <= 7 and row == 0 and date.month != last_month or (last_month is None and col == 0):
                if last_month is None or date.month != last_month:
                    doc.text(cx, gy - 10, date.strftime("%b").upper(), "mono", 9.4, FAINT, track=0.08)
                    last_month = date.month
            doc.add(f'<rect x="{n(cx)}" y="{n(gy + row * pitch)}" width="{n(cell)}" height="{n(cell)}" rx="2.6" fill="{LEVELS[level]}"/>')
        gh_ = 7 * pitch
        lx = W - 30
        doc.text(lx, gy + gh_ + 14, "more", "mono", 9.4, FAINT, anchor="end", track=0.04)
        lx -= measure("more", "mono", 9.4, 0.04) + 8
        for lvl in reversed(LEVELS):
            lx -= 11
            doc.add(f'<rect x="{n(lx)}" y="{n(gy + gh_ + 5)}" width="10" height="10" rx="2.4" fill="{lvl}"/>')
            lx -= 3
        doc.text(lx - 3, gy + gh_ + 14, "less", "mono", 9.4, FAINT, anchor="end", track=0.04)

    # languages
    ly0 = gy + gh_ + 52
    ranked = sorted(langs.items(), key=lambda kv: -kv[1])
    whole = sum(langs.values()) or 1
    top = [kv for kv in ranked if kv[1] / whole >= 0.005][:7]   # a 0.0% legend entry is noise
    rest = whole - sum(v for _, v in top)
    rest = rest if rest / whole >= 0.001 else 0
    doc.text(x0, ly0, f"LANGUAGES ACROSS {len(own)} PUBLIC REPOSITORIES, BY BYTES", "mono", 10.5, MUTED, track=0.1)
    if not hidden:
        doc.text(W - 30, ly0, f"{stars} stars", "mono", 10.5, FAINT, anchor="end", track=0.04)
    by, bw = ly0 + 14, W - 60
    doc.defs.append(f'<clipPath id="bar"><rect x="{x0}" y="{by}" width="{bw}" height="10" rx="5"/></clipPath>')
    segs, cx = [], float(x0)
    parts = [(name, size, LANG_COLORS[i]) for i, (name, size) in enumerate(top)] + ([("Other", rest, OTHER)] if rest else [])
    for name, size, color in parts:
        wseg = bw * size / whole
        segs.append(f'<rect x="{n(cx)}" y="{by}" width="{n(max(wseg - 1.5, 0.5))}" height="10" fill="{color}"/>')
        cx += wseg
    doc.add(f'<g clip-path="url(#bar)">{"".join(segs)}</g>')
    lx, ly = float(x0), by + 36
    for name, size, color in parts:
        pct = f"{size / whole * 100:.1f}%"
        wname = measure(name, "bodym", 12)
        wpct = measure(pct, "mono", 10.5)
        need = 14 + wname + 7 + wpct + 22
        if lx + need > W - 30:
            lx, ly = float(x0), ly + 22
        doc.add(f'<circle cx="{n(lx + 4)}" cy="{n(ly - 4)}" r="4" fill="{color}"/>')
        doc.text(lx + 14, ly, name, "bodym", 12, INK)
        doc.text(lx + 14 + wname + 7, ly, pct, "mono", 10.5, MUTED)
        lx += need

    doc.h = ly + 48
    doc.body[0] = f'<rect x="0.5" y="0.5" width="{n(W - 1)}" height="{n(doc.h - 1)}" rx="16" fill="#07080b" stroke="rgba(255,255,255,0.08)"/>'
    doc.text(x0, doc.h - 18, f"Public repositories only. Private work such as ZudoMart and Telente CBT is not counted. Updated {dt.date.today().isoformat()}.",
             "mono", 9.6, FAINT, track=0.02)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc.render(), encoding="utf-8")
    print("activity is hidden in the account settings: calendar omitted" if hidden else "calendar drawn")
    print(f"{path}: {total:,} contributions, {active} active days, longest streak {longest}, "
          f"{len(own)} repositories, {len(langs)} languages")


if __name__ == "__main__":
    from pathlib import Path
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "activity.svg")
