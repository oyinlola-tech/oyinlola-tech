#!/usr/bin/env python3
"""
Builds every SVG in assets/ for the profile README.

    python3 scripts/build_assets.py        # needs fonttools, brotli, uharfbuzz

Why generated, and why text is outlines
---------------------------------------
GitHub serves README images behind a strict CSP, so an SVG cannot load a web
font, and a system-font fallback changes the width of every line on every
machine. Here all text is shaped with HarfBuzz (so kerning is real) and
emitted as glyph outlines from the same three families the portfolio uses:
Inter Tight, Inter and JetBrains Mono, all under the SIL Open Font License.
Each glyph is defined once per file and placed with <use>, which keeps the
files small. The result renders identically everywhere and depends on no
third-party service at view time.

Rule carried over from the portfolio: if a number appears, it is countable in
a repository. Edit the data at the bottom of each section, then rebuild.
"""

from __future__ import annotations

import io
import math
import re
from html import escape
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "scripts" / "fonts"
ICONS = ROOT / "scripts" / "icons"
OUT = ROOT / "assets"

# --------------------------------------------------------------------------
# Tokens, taken from the portfolio's app/globals.css
# --------------------------------------------------------------------------
STAGE, STAGE2, STAGE3, STAGE4 = "#07080b", "#0b0d12", "#10131a", "#171b24"
INK, INK_DIM, MUTED, FAINT = "#f4f5f7", "#a7adb8", "#8f96a1", "#808795"
ACCENT, ACCENT2, SIGNAL = "#ffb067", "#ff8f43", "#5ee2a0"
LINE, LINE2 = "rgba(255,255,255,0.08)", "rgba(255,255,255,0.14)"

W = 880  # every full-width asset shares this, close to GitHub's README column


def n(v: float) -> str:
    """Compact number formatting for SVG attributes."""
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


# --------------------------------------------------------------------------
# Type: variable fonts pinned to a weight, shaped with HarfBuzz
# --------------------------------------------------------------------------
class Face:
    def __init__(self, key: str, file: str, weight: int, features: dict | None = None):
        self.key = key
        font = TTFont(FONTS / file)
        font = instancer.instantiateVariableFont(font, {"wght": weight}, inplace=False)
        font.flavor = None
        buf = io.BytesIO()
        font.save(buf)
        self.tt = font
        self.upm = font["head"].unitsPerEm
        self.glyphs = font.getGlyphSet()
        self.cmap = font.getBestCmap()
        self.hb = hb.Font(hb.Face(buf.getvalue()))
        self.features = features or {}
        self._paths: dict[int, str] = {}

    def shape(self, text: str):
        missing = [c for c in text if ord(c) not in self.cmap]
        if missing:
            raise ValueError(f"{self.key}: no glyph for {missing!r} in {text!r}")
        b = hb.Buffer()
        b.add_str(text)
        b.guess_segment_properties()
        hb.shape(self.hb, b, self.features)
        return [(i.codepoint, p.x_advance, p.x_offset) for i, p in zip(b.glyph_infos, b.glyph_positions)]

    def path(self, gid: int) -> str:
        if gid not in self._paths:
            pen = SVGPathPen(self.glyphs, ntos=lambda v: str(int(round(v))))
            self.glyphs[self.tt.getGlyphName(gid)].draw(pen)
            self._paths[gid] = pen.getCommands()
        return self._paths[gid]


MONO_FEATURES = {"calt": False, "liga": False}
FACES = {
    "display": Face("d", "InterTight-latin.woff2", 640),
    "displayb": Face("D", "InterTight-latin.woff2", 720),
    "body": Face("b", "Inter-latin.woff2", 400),
    "bodym": Face("B", "Inter-latin.woff2", 560),
    "mono": Face("m", "JetBrainsMono-latin.woff2", 400, MONO_FEATURES),
    "monob": Face("M", "JetBrainsMono-latin.woff2", 640, MONO_FEATURES),
}


def measure(text: str, face: str, size: float, track: float = 0) -> float:
    f = FACES[face]
    run = f.shape(text)
    return sum(a for _, a, _ in run) * size / f.upm + track * size * max(len(run) - 1, 0)


def wrap(text: str, face: str, size: float, width: float) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and measure(trial, face, size) > width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


class Doc:
    def __init__(self, w: float, h: float, title: str, desc: str = ""):
        self.w, self.h, self.title, self.desc = w, h, title, desc
        self.defs: list[str] = []
        self.glyph_defs: dict[str, str] = {}
        self.body: list[str] = []
        self.css: list[str] = []

    def add(self, s: str):
        self.body.append(s)

    def text(self, x, y, s, face="body", size=14.0, fill=INK, anchor="start", track=0.0, opacity=None):
        """Place a line of outlined text. `track` is in em. Returns its width."""
        if not s:
            return 0.0
        f = FACES[face]
        run = f.shape(s)
        track_u = track * f.upm
        total = sum(a for _, a, _ in run) + track_u * max(len(run) - 1, 0)
        k = size / f.upm
        if anchor == "middle":
            x -= total * k / 2
        elif anchor == "end":
            x -= total * k
        uses, pen = [], 0.0
        for gid, adv, xoff in run:
            d = f.path(gid)
            if d:
                gid_ref = f"{f.key}{gid}"
                self.glyph_defs.setdefault(gid_ref, d)
                px = pen + xoff
                uses.append(f'<use href="#{gid_ref}"' + (f' x="{n(px)}"' if px else "") + "/>")
            pen += adv + track_u
        op = f' opacity="{n(opacity)}"' if opacity is not None else ""
        self.add(f'<g transform="translate({n(x)} {n(y)}) scale({k:.5f} {-k:.5f})" fill="{fill}"{op}>{"".join(uses)}</g>')
        return total * k

    def para(self, x, y, s, face, size, fill, width, leading=1.5, **kw):
        """Wrapped paragraph. Returns the y of the line after the last."""
        for line in wrap(s, face, size, width):
            self.text(x, y, line, face, size, fill, **kw)
            y += size * leading
        return y

    def render(self) -> str:
        glyphs = "".join(f'<path id="{k}" d="{d}"/>' for k, d in self.glyph_defs.items())
        css = f"<style>{''.join(self.css)}</style>" if self.css else ""
        title = escape(self.title, quote=True)
        desc = f"<desc>{escape(self.desc)}</desc>" if self.desc else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n(self.w)} {n(self.h)}" '
            f'width="{n(self.w)}" height="{n(self.h)}" role="img" aria-label="{title}">'
            f"<title>{title}</title>{desc}{css}<defs>{''.join(self.defs)}{glyphs}</defs>"
            f"{''.join(self.body)}</svg>\n"
        )

    def save(self, name: str):
        OUT.mkdir(exist_ok=True)
        (OUT / name).write_text(self.render(), encoding="utf-8")
        print(f"  {name:<28} {len(self.render()) / 1024:6.1f} KB")


def panel(doc: Doc, r=16, fill=STAGE, stroke=LINE):
    doc.add(f'<rect x="0.5" y="0.5" width="{n(doc.w - 1)}" height="{n(doc.h - 1)}" rx="{r}" fill="{fill}" stroke="{stroke}"/>')


def rng(seed: int):
    """xorshift32, the same generator the portfolio uses, so output is stable."""
    s = seed & 0xFFFFFFFF or 1

    def nxt():
        nonlocal s
        s ^= (s << 13) & 0xFFFFFFFF
        s ^= s >> 17
        s ^= (s << 5) & 0xFFFFFFFF
        return (s % 100000) / 100000

    return nxt


def fnv(text: str) -> int:
    h = 2166136261
    for ch in text:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def wave_mark(x, y, size, color=ACCENT):
    """The portfolio's mark: two offset waves."""
    k = size / 32
    return (
        f'<g transform="translate({n(x)} {n(y)}) scale({n(k)})" fill="none" stroke="{color}" '
        f'stroke-width="2.2" stroke-linecap="round">'
        f'<path d="M6 20c4-8 7.5-8 11 0s7 8 9 0"/><path d="M6 13c4-8 7.5-8 11 0s7 8 9 0" opacity=".42"/></g>'
    )


def zudo_mark(x, y, size, light="#FAFAF9"):
    """The Zudojs mark: a Z assembled from modules, the red diagonal the path through the layers."""
    k = size / 80
    cells = [(cx, 6, light) for cx in (6, 20, 34, 48, 62)]
    cells += [(48, 20, "#C0392B"), (34, 34, "#C0392B"), (20, 48, "#C0392B")]
    cells += [(cx, 62, light) for cx in (6, 20, 34, 48, 62)]
    rects = "".join(f'<rect x="{cx}" y="{cy}" width="12" height="12" fill="{c}"/>' for cx, cy, c in cells)
    return f'<g transform="translate({n(x)} {n(y)}) scale({n(k)})">{rects}</g>'


def arrow(x1, y1, x2, y2, color, width=1.4, head=5.5, dash=None, opacity=1.0):
    ang = math.atan2(y2 - y1, x2 - x1)
    hx, hy = x2 - head * math.cos(ang), y2 - head * math.sin(ang)
    lx, ly = hx + head * 0.55 * math.sin(ang), hy - head * 0.55 * math.cos(ang)
    rx, ry = hx - head * 0.55 * math.sin(ang), hy + head * 0.55 * math.cos(ang)
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<g opacity="{n(opacity)}"><path d="M{n(x1)} {n(y1)}L{n(hx)} {n(hy)}" stroke="{color}" stroke-width="{width}" fill="none"{d}/>'
        f'<path d="M{n(x2)} {n(y2)}L{n(lx)} {n(ly)}L{n(rx)} {n(ry)}Z" fill="{color}"/></g>'
    )


REDUCED_MOTION = "@media (prefers-reduced-motion:reduce){.mo{display:none}.tw{animation:none!important}}"


# --------------------------------------------------------------------------
# Hero: ZudoMart's real module graph as the centrepiece
# --------------------------------------------------------------------------
# Counts are from the case study: 26 + 20 + 14 + 14 + 5 = 79 Go modules.
DOMAINS = [
    ("commerce", 26, "#ffb067", (-118, -78)),
    ("platform", 20, "#56d6c0", (124, -66)),
    ("social", 14, "#6e92ff", (-104, 92)),
    ("creator", 5, "#9b8cff", (128, 96)),
    ("core", 14, "#d8e2ff", (6, 8)),
]


def build_hero():
    h = 430
    doc = Doc(W, h, "Oluwayemi Oyinlola Michael, software engineer",
              "Backend systems in Go, Python and TypeScript. The graph is ZudoMart: 79 Go modules in five domains, joined by an event spine.")
    doc.css.append(
        "@keyframes tw{0%,100%{opacity:.35}50%{opacity:1}}.tw{animation:tw 3.6s ease-in-out infinite}"
        "@keyframes live{0%,100%{opacity:.35;r:3.2px}50%{opacity:1;r:4.4px}}.live{animation:live 2.4s ease-in-out infinite}"
        + REDUCED_MOTION
    )
    doc.defs.append(
        '<radialGradient id="wash" cx="74%" cy="52%" r="62%"><stop offset="0" stop-color="#ffb067" stop-opacity=".13"/>'
        '<stop offset=".55" stop-color="#ff8f43" stop-opacity=".035"/><stop offset="1" stop-color="#07080b" stop-opacity="0"/></radialGradient>'
        '<clipPath id="clip"><rect x="0.5" y="0.5" width="879" height="429" rx="18"/></clipPath>'
    )
    panel(doc, r=18)
    doc.add('<g clip-path="url(#clip)"><rect width="880" height="430" fill="url(#wash)"/>')

    # -- constellation ----------------------------------------------------
    cx0, cy0 = 652, 222
    rnd = rng(7919)
    centres, parts_lines, parts_nodes, parts_glow, hot = {}, [], [], [], []
    for name, count, color, (dx, dy) in DOMAINS:
        cx, cy = cx0 + dx, cy0 + dy
        centres[name] = (cx, cy, color)
        spread = 13 + math.sqrt(count) * 8.2
        gid = f"g-{name}"
        doc.defs.append(
            f'<radialGradient id="{gid}"><stop offset="0" stop-color="{color}" stop-opacity=".2"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></radialGradient>'
        )
        parts_glow.append(f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{n(spread * 1.75)}" fill="url(#{gid})"/>')
        pts = []
        for i in range(count):
            # golden-angle placement with jitter: even cover, no lattice look
            rad = spread * math.sqrt((i + 0.6) / count) * (0.86 + rnd() * 0.28)
            ang = i * 2.39996 + rnd() * 0.5
            pts.append((cx + rad * math.cos(ang) * 1.12, cy + rad * math.sin(ang) * 0.92))
        for i, (x, y) in enumerate(pts):
            near = sorted(range(count), key=lambda j: (pts[j][0] - x) ** 2 + (pts[j][1] - y) ** 2)[1:3]
            for j in near:
                if j > i or i not in sorted(range(count), key=lambda q: (pts[q][0] - pts[j][0]) ** 2 + (pts[q][1] - pts[j][1]) ** 2)[1:3]:
                    parts_lines.append(f'<path d="M{n(x)} {n(y)}L{n(pts[j][0])} {n(pts[j][1])}" stroke="{color}" stroke-opacity=".26"/>')
            big = rnd() > 0.78
            r = 2.5 if big else 1.2 + rnd() * 0.9
            if big:
                hot.append((x, y, color, rnd() * 3.6))
            parts_nodes.append(f'<circle cx="{n(x)}" cy="{n(y)}" r="{n(r)}" fill="{color}" opacity="{n(0.55 + rnd() * 0.45)}"/>')

    # the event spine: every outer domain talks to core, never to each other
    core = centres["core"]
    spine, pulses = [], []
    for idx, (name, _, color, _) in enumerate(DOMAINS[:-1]):
        x, y, _ = centres[name]
        mx, my = (x + core[0]) / 2, (y + core[1]) / 2
        bend = 26 if idx % 2 == 0 else -26
        qx, qy = mx - (core[1] - y) / 7 + 0, my + bend * 0.4
        d = f"M{n(x)} {n(y)}Q{n(qx)} {n(qy)} {n(core[0])} {n(core[1])}"
        spine.append(f'<path id="sp{idx}" d="{d}" stroke="{color}" stroke-opacity=".34" stroke-dasharray="1.5 5" stroke-linecap="round" fill="none"/>')
        for k in range(2):
            begin = idx * 0.85 + k * 2.1
            back = ' keyPoints="1;0" keyTimes="0;1" calcMode="linear"' if k else ""
            pulses.append(
                f'<circle class="mo" r="2.6" opacity="0" fill="{color if not k else core[2]}"><animateMotion dur="4.2s" begin="{n(begin)}s" '
                f'repeatCount="indefinite"{back}><mpath href="#sp{idx}"/></animateMotion>'
                f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.12;.85;1" dur="4.2s" begin="{n(begin)}s" repeatCount="indefinite"/></circle>'
            )
    doc.add("".join(parts_glow))
    doc.add(f'<g stroke-width=".8" fill="none">{"".join(parts_lines)}</g>')
    doc.add(f'<g stroke-width="1.2">{"".join(spine)}</g>')
    doc.add("".join(parts_nodes))
    doc.add("".join(
        f'<circle class="tw" style="animation-delay:-{n(delay)}s" cx="{n(x)}" cy="{n(y)}" r="4.6" fill="none" stroke="{c}" stroke-opacity=".55"/>'
        for x, y, c, delay in hot
    ))
    doc.add("".join(pulses))
    doc.add("</g>")

    label_at = {"commerce": (-1, -1), "platform": (1, -1), "social": (-1, 1), "creator": (1, 1), "core": (0, 1)}
    for name, count, color, _ in DOMAINS:
        x, y, _ = centres[name]
        spread = 13 + math.sqrt(count) * 8.2
        sx, sy = label_at[name]
        ly = y + sy * (spread + 17) + (4 if sy > 0 else 0)
        if name == "core":
            ly = y + spread + 16
        lx = x + sx * spread * 0.35
        wname = measure(name, "mono", 10.5, 0.04)
        wcount = measure(f"{count}", "monob", 10.5)
        start = lx - (wname + 8 + wcount) / 2
        doc.text(start, ly, name, "mono", 10.5, color, track=0.04, opacity=0.95)
        doc.text(start + wname + 8, ly, f"{count}", "monob", 10.5, INK)

    doc.text(W - 36, h - 30, "ZudoMart · 79 Go modules · five domains · one deployable", "mono", 10.5, FAINT, anchor="end", track=0.02)

    # -- masthead -----------------------------------------------------------
    doc.add(wave_mark(30, 22, 34))
    doc.text(70, 44, "oyinlola", "monob", 13, INK)
    avail = "Open to backend and platform roles"
    wa = measure(avail, "mono", 11.5, 0.02)
    doc.add(f'<circle class="live tw" cx="{n(W - 36 - wa - 14)}" cy="40" r="3.6" fill="{SIGNAL}"/>')
    doc.text(W - 36, 44, avail, "mono", 11.5, INK_DIM, anchor="end", track=0.02)

    # -- statement ----------------------------------------------------------
    x = 36
    doc.text(x, 116, "SOFTWARE ENGINEER  ·  ONDO STATE, NIGERIA  ·  UTC+1", "mono", 10.5, ACCENT, track=0.12)
    size = 50
    while measure("Oyinlola Michael", "displayb", size, -0.022) > 398:
        size -= 1
    doc.text(x, 116 + size + 12, "Oluwayemi", "displayb", size, INK, track=-0.022)
    doc.text(x, 116 + size * 2 + 16, "Oyinlola Michael", "displayb", size, INK, track=-0.022)
    y = doc.para(x, 116 + size * 2 + 58, "I build the systems behind useful products: backend APIs, data pipelines, "
                 "developer tools, and the architecture that holds them together.", "body", 15.5, INK_DIM, 392, leading=1.52)

    # -- telemetry, the portfolio's own four figures -----------------------------
    ty = h - 66
    doc.add(f'<path d="M{x} {ty - 22}H{x + 392}" stroke="{LINE2}"/>')
    for i, (value, label) in enumerate([("79", "Go modules"), ("39", "TS packages"), ("26", "Case studies"), ("3", "Core languages")]):
        cx = x + i * 102
        doc.text(cx, ty + 8, value, "display", 23, INK, track=-0.01)
        doc.text(cx, ty + 27, label, "mono", 9.8, MUTED, track=0.03)
    doc.save("hero.svg")


# --------------------------------------------------------------------------
# Project banners: the portfolio's lattice sigil, one hue per project
# --------------------------------------------------------------------------
def sigil(slug: str, hue: int, x0: float, y0: float, w: float, h: float, cols=46, rows=13) -> str:
    nxt = rng(fnv(slug))
    ax, ay = nxt() * 6.28, nxt() * 6.28
    fx, fy = 0.35 + nxt() * 0.5, 0.3 + nxt() * 0.45
    tilt = nxt() * 0.6 - 0.3
    base, hot = f"hsl({hue} 62% 62%)", f"hsl({hue} 90% 86%)"
    out = []
    for r in range(rows):
        for c in range(cols):
            u, v = c / (cols - 1), r / (rows - 1)
            field = (math.sin(u * cols * fx * 0.62 + ax + v * tilt * 6) * 0.5
                     + math.sin(v * rows * fy + ay) * 0.35 + math.sin((u + v) * 4.2 + ax * 0.5) * 0.2)
            lift = (field + 1) / 2
            depth = 0.45 + v * 0.55          # near rows sit forward
            fade = min(1.0, u * 2.4)          # dissolve toward the text
            o = (0.12 + lift * 0.8) * depth * fade
            if o < 0.05:
                continue
            px = x0 + u * w
            py = y0 + v * h + (0.5 - lift) * h * 0.13
            rad = (0.7 + lift * 1.5) * depth
            out.append(f'<circle cx="{n(px)}" cy="{n(py)}" r="{n(rad)}" fill="{hot if lift > 0.84 else base}" opacity="{n(o)}"/>')
    return "".join(out)


PROJECTS = [
    # slug, file, name, kind, status, hue, metrics
    ("zudomart", "ZudoMart", "Social commerce super-app", "Private", 26,
     [("79", "Go modules"), ("5", "Bounded domains"), ("13k+", "Go source files"), ("2", "Runtimes")]),
    ("zudojs", "Zudojs", "TypeScript application framework", "Open source", 210,
     [("39", "Packages"), ("198k", "Lines of TypeScript"), ("5", "Enforced tiers"), ("11", "Frontend adapters")]),
    ("sentinelx", "SentinelX", "Network intrusion detection & prevention", "Open source", 152,
     [("0–100", "Risk, with reasons"), ("75", "Test files"), ("2", "Capture modes"), ("Dry run", "Default response")]),
    ("commitguard", "CommitGuard", "Commit provenance & policy engine", "Open source", 38,
     [("4", "Detectors"), ("3", "Git hooks"), ("3", "Enforcement points"), ("63", "Test files")]),
    ("kolo", "Kolo", "Cooperative savings & payments infrastructure", "Open source", 158,
     [("32", "Prisma repositories"), ("18", "Controllers"), ("14", "Background queues"), ("3", "Role dashboards")]),
    ("utils-tool", "Utils-tool", "Local-first media utility suite", "Live", 44,
     [("28", "Tools"), ("2", "Runtime environments"), ("0", "Databases"), ("0", "Accounts required")]),
    ("agentlab", "AgentLab", "Agent execution & evaluation runtime", "Case study", 150,
     [("3", "Execution environments"), ("5", "Scoring dimensions"), ("2", "Model providers, routed"), ("1", "Command to demo")]),
    ("scriptune", "Scriptune", "Bible & hymn recognition platform", "Open source", 268,
     [("27", "Prisma models"), ("6", "Bible translations"), ("1,200", "Hymns"), ("3", "Apps · API, web, mobile")]),
]

STATUS_COLOR = {"Open source": SIGNAL, "Live": ACCENT, "Private": MUTED, "Case study": "#9bb4ff"}


def build_projects():
    h = 148
    for slug, name, kind, status, hue, metrics in PROJECTS:
        doc = Doc(W, h, f"{name}: {kind}", " · ".join(f"{v} {l}" for v, l in metrics))
        tint = f"hsl({hue} 70% 72%)"
        doc.defs.append(
            f'<radialGradient id="glow" cx="78%" cy="110%" r="70%"><stop offset="0" stop-color="hsl({hue} 62% 62%)" stop-opacity=".3"/>'
            f'<stop offset=".6" stop-color="hsl({hue} 62% 62%)" stop-opacity=".06"/><stop offset="1" stop-color="hsl({hue} 62% 62%)" stop-opacity="0"/></radialGradient>'
            f'<linearGradient id="shade" x1="0" x2="1"><stop offset="0" stop-color="{STAGE2}"/><stop offset=".5" stop-color="{STAGE2}" stop-opacity=".9"/>'
            f'<stop offset="1" stop-color="{STAGE2}" stop-opacity="0"/></linearGradient>'
            f'<clipPath id="clip"><rect x="0.5" y="0.5" width="879" height="{h - 1}" rx="14"/></clipPath>'
        )
        panel(doc, r=14, fill=STAGE2)
        doc.add(f'<g clip-path="url(#clip)"><rect width="880" height="{h}" fill="url(#glow)"/>')
        doc.add(sigil(slug, hue, 330, 10, 560, 70))
        doc.add(f'<rect x="0" y="0" width="520" height="{h}" fill="url(#shade)"/>')
        doc.add(f'<rect x="0" y="0" width="3" height="{h}" fill="{tint}"/></g>')

        x = 30
        doc.text(x, 36, kind.upper(), "mono", 10.8, tint, track=0.1)
        nx = x
        if slug == "zudojs":
            doc.add(zudo_mark(x, 47, 30))
            nx = x + 40
        wn = doc.text(nx, 73, name, "displayb", 30, INK, track=-0.02)
        # status pill
        sc = STATUS_COLOR[status]
        ws = measure(status, "mono", 10, 0.04)
        px = nx + wn + 14
        doc.add(f'<rect x="{n(px)}" y="55" width="{n(ws + 27)}" height="21" rx="10.5" fill="{STAGE}" fill-opacity=".7" stroke="{sc}" stroke-opacity=".45"/>')
        doc.add(f'<circle cx="{n(px + 11)}" cy="65.5" r="2.6" fill="{sc}"/>')
        doc.text(px + 19, 69, status, "mono", 10, sc, track=0.04)

        # metrics row
        doc.add(f'<path d="M{x} 94H{W - 30}" stroke="{LINE2}"/>')
        col = (W - 60) / 4
        for i, (value, label) in enumerate(metrics):
            cx = x + i * col
            wv = doc.text(cx, 125, value, "display", 21, INK, track=-0.01)
            lines = wrap(label, "mono", 10.8, col - wv - 20)
            ly = 121 if len(lines) == 1 else 114
            for line in lines[:2]:
                doc.text(cx + wv + 10, ly, line, "mono", 10.8, INK_DIM, track=0.01)
                ly += 13
        doc.save(f"project-{slug}.svg")


# --------------------------------------------------------------------------
# Stack: brand marks in one quiet grid
# --------------------------------------------------------------------------
def icon_path(slug: str) -> str:
    svg = (ICONS / f"{slug}.svg").read_text()
    return re.search(r'<path d="([^"]+)"', svg).group(1)


def readable(hex_color: str) -> str:
    """Brand colours are chosen for white paper. Lift the ones that vanish on the stage."""
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if lum < 0.1:
        return INK
    mix = max(0.0, min(0.65, 0.64 - lum))
    r, g, b = (c + (1 - c) * mix for c in (r, g, b))
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in (r, g, b))


STACK = [
    ("Languages", [("go", "Go", "00ADD8"), ("python", "Python", "3776AB"), ("typescript", "TypeScript", "3178C6"),
                   ("javascript", "JavaScript", "F7DF1E"), ("gnubash", "Bash", "4EAA25")]),
    ("Backend", [("zudojs", "Zudojs", ""), ("nodedotjs", "Node.js", "5FA04E"), ("fastify", "Fastify", "000000"),
                 ("express", "Express", "000000"), ("fastapi", "FastAPI", "009688"), ("gin", "Gin", "008ECF"),
                 ("apachekafka", "Kafka", "231F20"), ("rabbitmq", "RabbitMQ", "FF6600")]),
    ("Data", [("postgresql", "PostgreSQL", "4169E1"), ("mysql", "MySQL", "4479A1"), ("mariadb", "MariaDB", "003545"),
              ("redis", "Redis", "FF4438"), ("sqlite", "SQLite", "003B57"), ("prisma", "Prisma", "2D3748"),
              ("sequelize", "Sequelize", "52B0E7"), ("zod", "Zod", "3E67B1")]),
    ("Infrastructure", [("linux", "Linux", "FCC624"), ("kalilinux", "Kali", "557C94"), ("docker", "Docker", "2496ED"),
                        ("kubernetes", "Kubernetes", "326CE5"), ("terraform", "Terraform", "844FBA"), ("nginx", "Nginx", "009639"),
                        ("traefikproxy", "Traefik", "24A1C1"), ("githubactions", "Actions", "2088FF"), ("git", "Git", "F05032")]),
    ("Frontend & tooling", [("react", "React", "61DAFB"), ("nextdotjs", "Next.js", "000000"), ("tailwindcss", "Tailwind", "06B6D4"),
                            ("threedotjs", "Three.js", "000000"), ("expo", "Expo", "000020"), ("vite", "Vite", "646CFF"),
                            ("vitest", "Vitest", "6E9F18"), ("postman", "Postman", "FF6C37"), ("swagger", "Swagger", "85EA2D")]),
]


def build_stack():
    tile_w, tile_h, gap, left, top, row_gap = 72, 74, 8, 138, 26, 14
    h = top * 2 + len(STACK) * tile_h + (len(STACK) - 1) * row_gap
    doc = Doc(W, h, "Engineering stack",
              "; ".join(f"{g}: {', '.join(lbl for _, lbl, _ in items)}" for g, items in STACK))
    panel(doc)
    for r, (group, items) in enumerate(STACK):
        y = top + r * (tile_h + row_gap)
        if r:
            doc.add(f'<path d="M30 {n(y - row_gap / 2)}H{W - 30}" stroke="{LINE}"/>')
        lines = wrap(group.upper(), "mono", 10, 100)
        ly = y + tile_h / 2 + 4 - (len(lines) - 1) * 7
        for line in lines:
            doc.text(30, ly, line, "mono", 10, MUTED, track=0.1)
            ly += 14
        for i, (slug, label, color) in enumerate(items):
            x = left + i * (tile_w + gap)
            own = slug == "zudojs"
            doc.add(f'<rect x="{n(x)}" y="{n(y)}" width="{tile_w}" height="{tile_h}" rx="12" fill="{STAGE3}" '
                    f'stroke="{ACCENT if own else LINE}" stroke-opacity="{0.55 if own else 1}"/>')
            if own:
                doc.add(zudo_mark(x + tile_w / 2 - 14, y + 13, 28))
            else:
                k = 26 / 24
                doc.add(f'<path transform="translate({n(x + tile_w / 2 - 13)} {n(y + 14)}) scale({n(k)})" fill="{readable(color)}" d="{icon_path(slug)}"/>')
            doc.text(x + tile_w / 2, y + 60, label, "mono", 9.6, ACCENT if own else INK_DIM, anchor="middle", track=0.01)
    doc.save("stack.svg")


# --------------------------------------------------------------------------
# Architecture: how a backend is laid out, drawn from ZudoMart
# --------------------------------------------------------------------------
def box(doc, x, y, w, h, title, sub=None, color=LINE2, fill=STAGE3, title_color=INK, r=10, center=True):
    doc.add(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{r}" fill="{fill}" stroke="{color}"/>')
    ax, anchor = (x + w / 2, "middle") if center else (x + 14, "start")
    ty = y + h / 2 + (-3 if sub else 4.5)
    doc.text(ax, ty, title, "bodym", 13, title_color, anchor=anchor)
    if sub:
        doc.text(ax, ty + 16, sub, "mono", 9.6, MUTED, anchor=anchor, track=0.02)


def build_architecture():
    h = 500
    doc = Doc(W, h, "How I structure a backend, drawn from ZudoMart",
              "Clients reach a Go modular monolith through a Traefik edge. Four domains depend on core, never on each other. "
              "State lives in PostgreSQL and Redis. Domain events travel a Kafka spine to a Python service that returns scores.")
    doc.css.append(REDUCED_MOTION)
    panel(doc)

    # clients and edge
    doc.text(30, 40, "CLIENTS", "mono", 10, MUTED, track=0.1)
    box(doc, 30, 54, 100, 44, "Web app")
    box(doc, 30, 108, 100, 44, "Mobile app")
    box(doc, 30, 196, 100, 52, "Traefik", "edge · TLS", color=LINE2)
    doc.add(arrow(80, 152, 80, 194, FAINT))
    doc.add(arrow(130, 222, 172, 222, FAINT))

    # the monolith
    mx, my, mw, mh = 174, 54, 476, 286
    doc.add(f'<rect x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="14" fill="{STAGE2}" stroke="{ACCENT}" stroke-opacity=".5"/>')
    doc.text(mx, 40, "GO MODULAR MONOLITH", "mono", 10, ACCENT, track=0.1)
    doc.text(mx + mw, 40, "79 modules · one deployable", "mono", 10, MUTED, anchor="end", track=0.02)
    box(doc, mx + 16, my + 16, mw - 32, 38, "HTTP layer · chi", None, fill=STAGE4)
    doms = [("Commerce", "26 modules", "#ffb067"), ("Social", "14 modules", "#6e92ff"),
            ("Creator", "5 modules", "#9b8cff"), ("Platform", "20 modules", "#56d6c0")]
    dw = (mw - 32 - 3 * 10) / 4
    for i, (title, sub, color) in enumerate(doms):
        dx = mx + 16 + i * (dw + 10)
        box(doc, dx, my + 76, dw, 62, title, sub, color=color, title_color=INK)
        doc.add(f'<rect x="{n(dx)}" y="{my + 76}" width="{n(dw)}" height="3" rx="1.5" fill="{color}"/>')
        doc.add(arrow(dx + dw / 2, my + 54, dx + dw / 2, my + 75, FAINT, head=4.5))
        doc.add(arrow(dx + dw / 2, my + 138, dx + dw / 2, my + 151, FAINT, head=4.5))
        doc.add(arrow(dx + dw / 2, my + 186, dx + dw / 2, my + 201, FAINT, head=4.5))
    # the trust engine cuts across domains: escrow in commerce, KYC and fraud in platform, verification in core
    doc.add(f'<rect x="{n(mx + 16)}" y="{my + 152}" width="{n(mw - 32)}" height="34" rx="8" fill="#ffb067" fill-opacity=".07" stroke="#ffb067" stroke-opacity=".55"/>')
    wt = doc.text(mx + 30, my + 173.5, "Trust engine", "bodym", 12.5, INK)
    doc.text(mx + 30 + wt + 12, my + 173, "escrow · three-tier verification · risk scoring", "mono", 9.4, INK_DIM, track=0.01)
    box(doc, mx + 16, my + 202, mw - 32, 44, "Core", "14 modules · users · auth · search · ranking · analytics", color="#d8e2ff", fill=STAGE4)
    doc.text(mx + mw / 2, my + 270, "Modules talk by command, query and event. Never by reaching into each other's data.",
             "body", 11.5, INK_DIM, anchor="middle")

    # python service
    px, py, pw, ph = 690, 54, 160, 286
    doc.add(f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="14" fill="{STAGE2}" stroke="#56d6c0" stroke-opacity=".5"/>')
    doc.text(px, 40, "PYTHON SERVICE", "mono", 10, "#56d6c0", track=0.1)
    doc.text(px + pw / 2, py + 34, "FastAPI", "bodym", 14, INK, anchor="middle")
    for i, item in enumerate(["ranking", "recommendation", "moderation", "fraud detection", "forecasting"]):
        iy = py + 56 + i * 34
        doc.add(f'<rect x="{px + 14}" y="{iy}" width="{pw - 28}" height="26" rx="7" fill="{STAGE3}" stroke="{LINE}"/>')
        doc.text(px + pw / 2, iy + 17, item, "mono", 10.2, INK_DIM, anchor="middle")
    for j, line in enumerate(["Retrain a model without", "redeploying payments."]):
        doc.text(px + pw / 2, py + 244 + j * 15, line, "body", 11, MUTED, anchor="middle")

    # data row
    dy = 392
    doc.text(30, dy - 14, "STATE", "mono", 10, MUTED, track=0.1)
    box(doc, 174, dy, 180, 52, "PostgreSQL", "ent + Atlas migrations")
    box(doc, 366, dy, 120, 52, "Redis", "cache · sessions")
    doc.add(arrow(264, 340, 264, dy - 2, FAINT))
    doc.add(arrow(426, 340, 426, dy - 2, FAINT))

    # kafka spine
    kx1, kx2, ky = 510, 850, dy + 26
    doc.add(f'<rect x="{kx1}" y="{dy}" width="{kx2 - kx1}" height="52" rx="26" fill="{STAGE3}" stroke="{ACCENT}" stroke-opacity=".45"/>')
    doc.text(kx1 + 24, ky - 1, "Kafka event spine", "bodym", 13, INK)
    doc.text(kx1 + 24, ky + 14, "events out · scores back", "mono", 9.6, MUTED, track=0.02)
    doc.add(f'<path id="bus" d="M{kx1 + 196} {ky}H{kx2 - 24}" stroke="{ACCENT}" stroke-opacity=".65" stroke-dasharray="1.5 6" stroke-linecap="round" stroke-width="1.6"/>')
    for k in range(3):
        doc.add(f'<circle class="mo" r="3" opacity="0" fill="{ACCENT}"><animateMotion dur="2.8s" begin="{n(k * 0.93)}s" repeatCount="indefinite"><mpath href="#bus"/></animateMotion>'
                f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.15;.8;1" dur="2.8s" begin="{n(k * 0.93)}s" repeatCount="indefinite"/></circle>')
    doc.add(arrow(580, 340, 580, dy - 2, ACCENT, dash="4 4", opacity=0.85))
    doc.text(588, 368, "events", "mono", 9.6, ACCENT, track=0.04)
    doc.add(arrow(726, dy - 2, 726, 342, "#56d6c0", dash="4 4", opacity=0.85))
    doc.text(718, 368, "consume", "mono", 9.6, "#56d6c0", anchor="end", track=0.04)
    doc.add(arrow(822, 342, 822, dy - 2, "#56d6c0", dash="4 4", opacity=0.85))
    doc.text(814, 368, "scores", "mono", 9.6, "#56d6c0", anchor="end", track=0.04)

    doc.text(30, h - 22, "Deployed with Docker, Kubernetes, Terraform and Traefik, versioned alongside the code.", "mono", 10, FAINT, track=0.02)
    doc.save("architecture.svg")


# --------------------------------------------------------------------------
# Journey: a real sequence, so it is drawn as one
# --------------------------------------------------------------------------
JOURNEY = [
    ("2023", "Founded ZudoMart", "Started the backend that became a 79-module Go monolith."),
    ("2025", "Newdich Technology", "Backend Engineer on Eko Xpedite Exchange: merchant, agent and end-user flows."),
    ("Jan 2026", "EquityPilot", "ZudoMart joined FasterCapital's EquityPilot programme."),
    ("2026", "Shipped in the open", "Zudojs, Kolo, Telente CBT, Telente Store, Utils-tool, PowerWatch, LearnBridge, Zudo POS."),
    ("Now", "Security and data", "SentinelX, CommitGuard and Scriptune, alongside a BSc in Computer Science."),
]


def build_journey():
    h = 214
    doc = Doc(W, h, "Journey, 2023 to now", " ".join(f"{w}: {t}. {b}" for w, t, b in JOURNEY))
    doc.css.append("@keyframes tw{0%,100%{opacity:.3}50%{opacity:1}}.tw{animation:tw 2.6s ease-in-out infinite}" + REDUCED_MOTION)
    doc.defs.append(f'<linearGradient id="rail" gradientUnits="userSpaceOnUse" x1="30" x2="850"><stop offset="0" stop-color="{ACCENT}" stop-opacity=".15"/>'
                    f'<stop offset="1" stop-color="{ACCENT}"/></linearGradient>')
    panel(doc)
    col = (W - 60) / len(JOURNEY)
    ry = 62
    doc.add(f'<path d="M30 {ry}H{W - 30}" stroke="url(#rail)" stroke-width="1.5"/>')
    for i, (when, title, body) in enumerate(JOURNEY):
        x = 30 + i * col
        last = i == len(JOURNEY) - 1
        doc.text(x, ry - 22, when.upper(), "monob", 11, ACCENT if last else INK_DIM, track=0.08)
        if last:
            doc.add(f'<circle class="tw" cx="{n(x + 5)}" cy="{ry}" r="9" fill="{ACCENT}" fill-opacity=".25"/>')
        doc.add(f'<circle cx="{n(x + 5)}" cy="{ry}" r="4.5" fill="{ACCENT if last else STAGE}" stroke="{ACCENT}" stroke-width="1.5"/>')
        doc.text(x, ry + 36, title, "display", 15, INK, track=-0.005)
        doc.para(x, ry + 58, body, "body", 11.8, INK_DIM, col - 22, leading=1.5)
    doc.save("journey.svg")


# --------------------------------------------------------------------------
# Buttons and footer
# --------------------------------------------------------------------------
BUTTONS = [
    ("portfolio", "Portfolio", True), ("cv", "Read the CV", False), ("email", "Email", False),
    ("linkedin", "LinkedIn", False), ("x", "X", False), ("github", "GitHub", False), ("contact", "Contact form", False),
]


def build_buttons():
    for slug, label, primary in BUTTONS:
        tw = measure(label, "monob", 12.5, 0.03)
        w, h = tw + 58, 40
        doc = Doc(w, h, label)
        fg = STAGE if primary else INK
        doc.add(f'<rect x="0.5" y="0.5" width="{n(w - 1)}" height="{h - 1}" rx="19.5" fill="{ACCENT if primary else STAGE3}" stroke="{ACCENT if primary else LINE2}"/>')
        doc.text(20, 25, label, "monob", 12.5, fg, track=0.03)
        ax = 20 + tw + 10
        doc.add(f'<path d="M{n(ax)} 25.5L{n(ax + 8)} 17.5M{n(ax + 2)} 17.5H{n(ax + 8)}V23.5" stroke="{STAGE if primary else ACCENT}" stroke-width="1.7" fill="none" stroke-linecap="round" stroke-linejoin="round"/>')
        doc.save(f"btn-{slug}.svg")


def build_footer():
    h = 96
    doc = Doc(W, h, "oyinlola1.vercel.app")
    doc.defs.append(f'<linearGradient id="fade" x1="0" x2="1"><stop offset="0" stop-color="{ACCENT}" stop-opacity="0"/>'
                    f'<stop offset=".5" stop-color="{ACCENT}"/><stop offset="1" stop-color="{ACCENT}" stop-opacity="0"/></linearGradient>')
    panel(doc)
    for k, (dy, op) in enumerate([(0, 0.9), (9, 0.35)]):
        d = "M30 " + n(40 - dy)
        x = 30
        while x < W - 30:
            d += f"c14-26 27-26 41 0s27 26 41 0"
            x += 82
        doc.add(f'<path d="{d}" stroke="url(#fade)" stroke-width="1.6" fill="none" opacity="{op}" stroke-linecap="round"/>')
    doc.text(W / 2, 80, "oyinlola1.vercel.app  ·  built from one Python script, no third-party image services", "mono", 10.2, FAINT, anchor="middle", track=0.03)
    doc.save("footer.svg")


if __name__ == "__main__":
    print("Building assets/")
    build_hero()
    build_projects()
    build_stack()
    build_architecture()
    build_journey()
    build_buttons()
    build_footer()
