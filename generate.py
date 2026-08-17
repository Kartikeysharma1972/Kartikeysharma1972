#!/usr/bin/env python3
"""
Regenerates every graphic on this profile from live GitHub data.

Nothing here is embedded from a third-party server: the portrait, the stat
graphics, the language bars and the year heatmap are all drawn locally as SVG,
with the typeface subset and inlined as base64 so the page renders identically
everywhere and can never rate-limit or go dark.

Run by .github/workflows/profile.yml once a day (and on push). Commits only what
changed. Locally:  GITHUB_TOKEN=$(gh auth token) python generate.py
"""

import base64
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

# --------------------------------------------------------------------------- #
# config
# --------------------------------------------------------------------------- #
USER = "Kartikeysharma1972"
NAME = "Kartikey Sharma"

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
FONT_PATH = ASSETS / "fonts" / "jbmono-subset.woff2"
PORTRAIT_SRC = ASSETS / "portrait.png"

# character ramp, quiet -> loud (matches the "the year" ramp in the design)
RAMP = " .:x#█"

# palette — deliberately monochrome; colours adapt to the viewer's theme
FG_DARK, FG_LIGHT = "#adbac7", "#3d444d"      # body text
DIM_DARK, DIM_LIGHT = "#636e7b", "#8b949e"    # labels / captions
HI_DARK, HI_LIGHT = "#f0f6fc", "#1f2328"      # bright: the big number
ACC_DARK, ACC_LIGHT = "#6cb6ff", "#0969da"    # links

# JetBrains Mono metrics
CW = 0.600   # advance width in em (the design assumes exactly this)

# tidy display names for languages
LANG_NAMES = {
    "Jupyter Notebook": "jupyter",
    "Dockerfile": "docker",
    "Shell": "shell",
    "C++": "c++",
    "C#": "c#",
}


def lang_label(name: str) -> str:
    return LANG_NAMES.get(name, name.lower())


# --------------------------------------------------------------------------- #
# data
# --------------------------------------------------------------------------- #
def gh_graphql(query: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        try:
            token = subprocess.check_output(["gh", "auth", "token"], text=True).strip()
        except Exception:
            pass
    if not token:
        sys.exit("no GITHUB_TOKEN available")
    import urllib.request

    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as r:
        out = json.loads(r.read())
    if "errors" in out:
        sys.exit(json.dumps(out["errors"], indent=2))
    return out["data"]


def fetch():
    data = gh_graphql(
        """
    query {
      user(login: "%s") {
        contributionsCollection {
          contributionCalendar {
            totalContributions
            weeks { contributionDays { contributionCount weekday date } }
          }
        }
        repositories(first: 100, isFork: false, ownerAffiliations: OWNER,
                     orderBy: {field: PUSHED_AT, direction: DESC}) {
          nodes {
            name
            languages(first: 12, orderBy: {field: SIZE, direction: DESC}) {
              edges { size node { name } }
            }
          }
        }
      }
    }
    """
        % USER
    )
    user = data["user"]
    cal = user["contributionsCollection"]["contributionCalendar"]

    weeks = [[d["contributionCount"] for d in w["contributionDays"]] for w in cal["weeks"]]
    days = [c for w in weeks for c in w]

    # languages by bytes across public non-fork repos, and repo counts by primary lang
    by_bytes, by_repos = {}, {}
    for repo in user["repositories"]["nodes"]:
        edges = repo["languages"]["edges"]
        for e in edges:
            by_bytes[e["node"]["name"]] = by_bytes.get(e["node"]["name"], 0) + e["size"]
        if edges:
            primary = edges[0]["node"]["name"]
            by_repos[primary] = by_repos.get(primary, 0) + 1

    return {
        "total": cal["totalContributions"],
        "weeks": weeks,
        "days": days,
        "active_days": sum(1 for c in days if c > 0),
        "best_week": max((sum(w) for w in weeks), default=0),
        "by_bytes": sorted(by_bytes.items(), key=lambda kv: -kv[1]),
        "by_repos": sorted(by_repos.items(), key=lambda kv: -kv[1]),
    }


# --------------------------------------------------------------------------- #
# svg helpers
# --------------------------------------------------------------------------- #
def font_face() -> str:
    b64 = base64.b64encode(FONT_PATH.read_bytes()).decode()
    return (
        "@font-face{font-family:'JBM';font-style:normal;font-weight:400;"
        f"src:url(data:font/woff2;base64,{b64}) format('woff2');}}"
    )


def theme_css() -> str:
    return (
        f".fg{{fill:{FG_DARK}}}.dim{{fill:{DIM_DARK}}}.hi{{fill:{HI_DARK}}}"
        f".acc{{fill:{ACC_DARK}}}"
        "@media(prefers-color-scheme:light){"
        f".fg{{fill:{FG_LIGHT}}}.dim{{fill:{DIM_LIGHT}}}"
        f".hi{{fill:{HI_LIGHT}}}.acc{{fill:{ACC_LIGHT}}}}}"
    )


def svg_open(w: int, h: int, extra_css: str = "") -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
        f'font-family="JBM,ui-monospace,monospace" '
        f'role="img">'
        f"<style>{font_face()}{theme_css()}"
        f"text{{white-space:pre;dominant-baseline:hanging}}{extra_css}</style>"
    )


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write(path: Path, content: str):
    path.write_text(content, encoding="utf-8", newline="\n")
    print(f"  wrote {path.relative_to(ROOT)}  ({len(content):,} b)")


# --------------------------------------------------------------------------- #
# 1. portrait  ->  ascii.svg
# --------------------------------------------------------------------------- #
def make_portrait(cols=64):
    fs = 11                      # font size px
    cw = CW * fs                 # cell width
    ch = fs * 1.06               # cell height (tight, matches mono line box)
    rows = round(cols * (cw / ch) * 1.0)  # keep image square-ish

    im = Image.open(PORTRAIT_SRC).convert("L")
    # square-crop toward the upper-centre where a face usually sits
    w, h = im.size
    side = min(w, h)
    im = im.crop(((w - side) // 2, 0, (w - side) // 2 + side, side))
    im = ImageOps.autocontrast(im, cutoff=3)
    im = im.resize((cols, rows), Image.LANCZOS)

    px = im.load()
    pramp = RAMP[:-1]   # skip the solid block so highlights don't glare
    # radial vignette so a busy background falls away into the page
    cx, cy = cols / 2, rows / 2
    maxd = (cx**2 + cy**2) ** 0.5
    grid = []
    for y in range(rows):
        line = []
        for x in range(cols):
            v = px[x, y] / 255.0
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / maxd
            v *= max(0.0, 1.0 - d * 1.25)          # darken toward edges
            v = min(1.0, (v ** 0.9) * 1.08)        # a touch more contrast
            line.append(pramp[min(len(pramp) - 1, int(v * len(pramp)))])
        grid.append("".join(line).rstrip())

    W = round(cols * cw) + 2
    H = round(rows * ch) + 2
    out = [svg_open(W, H)]
    out.append(f'<text class="fg" font-size="{fs}" x="1" y="1" '
               f'letter-spacing="0" xml:space="preserve">')
    for i, row in enumerate(grid):
        out.append(f'<tspan x="1" dy="{0 if i == 0 else ch:.2f}">{esc(row)}</tspan>')
    out.append("</text></svg>")
    write(ASSETS / "ascii.svg", "".join(out))


# --------------------------------------------------------------------------- #
# 2. stats.svg  — big number + line chart + active days / best week
# --------------------------------------------------------------------------- #
def make_stats(d):
    W, H = 720, 150
    fs = 13
    out = [svg_open(W, H)]

    # big contribution count
    out.append(f'<text class="hi" x="0" y="6" font-size="46" '
               f'font-weight="700">{d["total"]:,}</text>')
    out.append(f'<text class="dim" x="2" y="58" font-size="{fs}">'
               f'contributions in the last year</text>')

    # right-aligned secondary stats
    def stat(x, top, num, label):
        out.append(f'<text class="hi" x="{x}" y="{top}" font-size="22" '
                   f'font-weight="700" text-anchor="end">{num}</text>')
        out.append(f'<text class="dim" x="{x}" y="{top+26}" font-size="{fs}" '
                   f'text-anchor="end">{label}</text>')
    stat(W, 4, d["active_days"], "active days")
    stat(W, 40, d["best_week"], "best week")

    # daily line chart across the year (3-day moving average)
    days = d["days"]
    n = len(days)
    sm = []
    for i in range(n):
        a = days[max(0, i - 1): i + 2]
        sm.append(sum(a) / len(a))
    peak = max(sm) or 1
    x0, x1, ybase, height = 0, W, 138, 46
    pts = []
    for i, v in enumerate(sm):
        x = x0 + (x1 - x0) * i / (n - 1)
        y = ybase - (v / peak) * height
        pts.append(f"{x:.1f},{y:.1f}")
    out.append(f'<polyline class="fg" fill="none" stroke="currentColor" '
               f'stroke-width="1.25" opacity="0.9" points="{" ".join(pts)}" '
               f'stroke-linejoin="round"/>')
    # baseline is the chart line's own colour; use a faint rule under it
    out.append(f'<line x1="0" y1="{ybase+0.5}" x2="{W}" y2="{ybase+0.5}" '
               f'class="dim" stroke="currentColor" stroke-width="0.5" opacity="0.35"/>')
    out.append("</svg>")
    write(ASSETS / "stats.svg", "".join(out))


# --------------------------------------------------------------------------- #
# 3. langs.svg  — by bytes / by repos
# --------------------------------------------------------------------------- #
def make_langs(d):
    fs = 13
    lh = 20
    top_n = 5
    colw, barw = 360, 150
    rows = max(len(d["by_bytes"][:top_n]), len(d["by_repos"][:top_n]))
    W, H = colw * 2, 30 + rows * lh + 6
    out = [svg_open(W, H)]

    def column(x, title, items, denom_mode):
        out.append(f'<text class="dim" x="{x}" y="0" font-size="12" '
                   f'letter-spacing="1">{title}</text>')
        top = items[:top_n]
        if denom_mode == "bytes":
            total = sum(v for _, v in top) or 1
        else:
            total = sum(v for _, v in top) or 1
        namew = 96
        for i, (lang, val) in enumerate(top):
            y = 24 + i * lh
            pct = val / total
            out.append(f'<text class="fg" x="{x}" y="{y}" font-size="{fs}">'
                       f'{esc(lang_label(lang))}</text>')
            bx = x + namew
            fullw = barw
            fill = max(2, round(fullw * pct))
            out.append(f'<rect x="{bx}" y="{y+1}" width="{fullw}" height="8" '
                       f'rx="1" class="dim" opacity="0.18"/>')
            out.append(f'<rect x="{bx}" y="{y+1}" width="{fill}" height="8" '
                       f'rx="1" class="fg" opacity="0.85"/>')
            label = f"{pct*100:.0f}%" if denom_mode == "bytes" else f"{val}"
            out.append(f'<text class="dim" x="{bx+fullw+8}" y="{y}" '
                       f'font-size="12">{label}</text>')

    column(0, "BY BYTES", d["by_bytes"], "bytes")
    column(colw, "BY REPOS", d["by_repos"], "repos")
    out.append("</svg>")
    write(ASSETS / "langs.svg", "".join(out))


# --------------------------------------------------------------------------- #
# 4. year.svg  — contribution heatmap in the character ramp
# --------------------------------------------------------------------------- #
def make_year(d):
    weeks = d["weeks"]
    allc = [c for w in weeks for c in w]
    nz = sorted(c for c in allc if c > 0)
    # quantile thresholds so the ramp uses its full range
    def q(p):
        if not nz:
            return 1
        return nz[min(len(nz) - 1, int(p * len(nz)))]
    t1, t2, t3, t4 = 1, q(0.35), q(0.65), q(0.88)

    def ch(c):
        if c <= 0:
            return RAMP[0]
        if c < t2:
            return RAMP[1]
        if c < t3:
            return RAMP[2]
        if c < t4:
            return RAMP[3]
        if c < max(t4 + 1, q(0.97)):
            return RAMP[4]
        return RAMP[5]

    fs = 12
    cw = CW * fs
    lh = fs * 1.42   # generous line box so full-block cells stay separate
    grid = [["".join(ch(weeks[x][y]) if y < len(weeks[x]) else " "
                     for x in range(len(weeks)))] for y in range(7)]
    W = round(len(weeks) * cw) + 2
    H = round(7 * lh) + 40
    out = [svg_open(W, H)]
    out.append(f'<text class="dim" x="0" y="0" font-size="12" '
               f'letter-spacing="1">THE YEAR</text>')
    out.append(f'<text class="dim" x="0" y="16" font-size="11">'
               f'{d["active_days"]} of {len(allc)} days had a contribution</text>')
    out.append(f'<text class="fg" x="1" y="40" font-size="{fs}" '
               f'xml:space="preserve">')
    for i, row in enumerate(grid):
        out.append(f'<tspan x="1" dy="{0 if i == 0 else lh:.2f}">'
                   f'{esc(row[0])}</tspan>')
    out.append("</text>")
    out.append(f'<text class="dim" x="{W-1}" y="{7*lh+44:.0f}" font-size="10" '
               f'text-anchor="end" xml:space="preserve">less  {esc(RAMP.strip())}  more</text>')
    out.append("</svg>")
    write(ASSETS / "year.svg", "".join(out))


# --------------------------------------------------------------------------- #
# 5. README.md
# --------------------------------------------------------------------------- #
ABOUT = """\
about
─────
AI/ML engineer, India. I build production AI agents and RAG systems, and
ship full-stack products around them. Small, sharp tools over big vague
ideas: I build fast, test on real users, and cut what doesn't earn its keep.
Right now that's EdTech AI tutors and multi-agent LangGraph systems."""

STACK = """\
stack
─────
python   typescript   javascript   react   node   express   mongodb
langgraph   openai   groq   rag   docker   git   linux"""

PROJECTS = """\
projects
────────
Ai-Tutor · react, express, mongodb, groq
  AI EdTech tutor for CBSE classes 1-12. Grade-adaptive concept explainer,
  document summariser, mock tests and focus-area analysis.

Classroom-Ai-Package · node, python, openai
  K-12 platform: teacher lesson/worksheet/assessment generation plus a
  960-topic grade-adaptive student tutor.

FinanceIQ · javascript, langgraph
  Personal finance analyst. Reads bank statements, categorises spend and
  builds a personalised financial roadmap with LangGraph agents.

Multi-Agent-Customer-support · python, langgraph
  Four specialised agents (billing / technical / returns / general) with
  automatic routing and human escalation."""

ABOUT_PAGE = """\
about this page
───────────────
Every graphic here is generated, not embedded from anyone else's server.
ascii.svg is my avatar pushed through a character ramp; stats.svg, langs.svg
and year.svg are drawn straight from the GitHub GraphQL API by a scheduled
action, once a day, committing only what changed. The typeface is JetBrains
Mono, subset to the characters each graphic draws and inlined as base64, so
the page renders identically everywhere and never rate-limits or goes dark.
year.svg uses the portrait's ramp:  . : x # █ , quiet to loud."""


def make_readme(d):
    md = f"""<div align="center">

<img src="./assets/ascii.svg" alt="{NAME}" width="440"/>

<img src="./assets/stats.svg" alt="contribution stats" width="720"/>

[iamjustk.site](https://iamjustk.site) &nbsp;·&nbsp; [email](mailto:kartikey.sharma@codevidhya.com) &nbsp;·&nbsp; [github](https://github.com/{USER})

</div>

```text
{ABOUT}
```

```text
{STACK}
```

```text
{PROJECTS}
```

<div align="center">

<img src="./assets/langs.svg" alt="languages" width="720"/>

<img src="./assets/year.svg" alt="the year" width="720"/>

</div>

```text
{ABOUT_PAGE}
```
"""
    write(ROOT / "README.md", md)


# --------------------------------------------------------------------------- #
def main():
    ASSETS.mkdir(exist_ok=True)
    print("fetching live data from the GitHub GraphQL API ...")
    d = fetch()
    print(f"  {d['total']:,} contributions, {d['active_days']} active days, "
          f"best week {d['best_week']}")
    make_portrait()
    make_stats(d)
    make_langs(d)
    make_year(d)
    make_readme(d)
    print("done.")


if __name__ == "__main__":
    main()
