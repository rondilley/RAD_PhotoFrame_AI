"""Jinja2 renderer, content version and small SVG helpers for the templates."""

import datetime as dt
import hashlib
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .icons import icon

TEMPLATES = Path(__file__).parent / "templates"


def human(n: float, unit: str = "") -> str:
    """1234 -> 1.2K, 3400000 -> 3.4M."""
    n = float(n or 0)
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            v = n / div
            return f"{v:.1f}{suffix}{unit}" if v < 100 else f"{v:.0f}{suffix}{unit}"
    return f"{n:.0f}{unit}"


def gib(n: float) -> str:
    return f"{(n or 0) / 2**30:.0f}"


def duration(s: float) -> str:
    s = int(s or 0)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def spark(values: list[float], w: int = 300, h: int = 64, top: float = 100.0, color: str = "#4cc9f0",
          bottom: float = 0.0, xs: list[float] | None = None, dots: bool = False) -> Markup:
    """An area line of the history, bottom..top, as inline SVG. xs: optional x positions 0..1."""
    if len(values) < 2:
        return Markup(f'<svg width="{w}" height="{h}"></svg>')
    top = max(top, max(values), bottom + 1)
    n = len(values)
    xs = xs or [i / (n - 1) for i in range(n)]
    pts = [(x * w, h - 2 - ((v - bottom) / (top - bottom)) * (h - 4)) for x, v in zip(xs, values)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"{pts[0][0]:.1f},{h} {line} {pts[-1][0]:.1f},{h}"
    return Markup(
        f'<svg class="fill" width="100%" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
        f'<polygon points="{area}" fill="{color}" fill-opacity="0.18"/>'
        f'<polyline points="{line}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>'
        + (f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="5" fill="{color}"/>' if dots else "")
        + "</svg>"
    )


def bars(values: list[float], w: int = 560, h: int = 150, color: str = "#b388ff", gap: int = 4,
         highlight_last: bool = True) -> Markup:
    """Vertical bars as inline SVG."""
    n = max(len(values), 1)
    top = max(max(values or [0]), 1)
    bw = (w - gap * (n - 1)) / n
    out = [f'<svg width="100%" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none">']
    for i, v in enumerate(values):
        bh = max(2.0, (v / top) * (h - 2)) if v else 2.0
        op = "1" if (highlight_last and i == n - 1) else ("0.75" if v else "0.18")
        out.append(f'<rect x="{i * (bw + gap):.1f}" y="{h - bh:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="3" '
                   f'fill="{color}" fill-opacity="{op}"/>')
    out.append("</svg>")
    return Markup("".join(out))


def ring(pct: float, size: int = 150, stroke: int = 14, color: str = "#4cc9f0") -> Markup:
    """A percent ring as inline SVG."""
    r = (size - stroke) / 2
    c = 2 * 3.14159265 * r
    pct = max(0.0, min(100.0, float(pct or 0)))
    return Markup(
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">'
        f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="#232a38" stroke-width="{stroke}"/>'
        f'<circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}" '
        f'stroke-linecap="round" stroke-dasharray="{c * pct / 100:.1f} {c:.1f}" '
        f'transform="rotate(-90 {size/2} {size/2})"/></svg>'
    )


def level(pct: float) -> str:
    """CSS class for a load level."""
    pct = float(pct or 0)
    return "hot" if pct >= 90 else ("warm" if pct >= 70 else "")


env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]), trim_blocks=True,
                  lstrip_blocks=True)
def hm(d) -> str:
    return f"{d.hour:02d}:{d.minute:02d}"


def until(s) -> str:
    s = int(s or 0)
    if s <= 60:
        return "now"
    m = (s + 59) // 60
    if m < 60:
        return f"in {m} min"
    h, m = divmod(m, 60)
    return f"in {h} h {m} min" if m else f"in {h} h"


def dayname(iso: str) -> str:
    return dt.date.fromisoformat(iso).strftime("%a")


env.filters.update(human=human, gib=gib, duration=duration, level=level, hm=hm, until=until, dayname=dayname)
env.globals.update(spark=spark, bars=bars, ring=ring, icon=icon)


def render(template: str, **ctx) -> tuple[str, str]:
    """The HTML fragment and its content version (first 16 hex digits of the SHA-256)."""
    html = env.get_template(template).render(**ctx)
    return html, hashlib.sha256(html.encode()).hexdigest()[:16]


def page(template: str, **ctx) -> str:
    return env.get_template(template).render(**ctx)


def local(epoch: float, tz: dt.tzinfo, fmt: str) -> str:
    return dt.datetime.fromtimestamp(epoch, tz).strftime(fmt)
