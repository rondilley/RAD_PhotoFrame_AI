"""Weather icons as small inline SVG (no emoji, no icon font, no external file)."""

from markupsafe import Markup

SUN = "#ffc94d"
MOON = "#cfd8e8"
CLOUD = "#c6cfdd"
CLOUD_DARK = "#8d98ab"
RAIN = "#4cc9f0"
SNOW = "#eef2f8"
BOLT = "#ffb547"


def _sun(cx=32, cy=32, r=11):
    rays = "".join(
        f'<line x1="{cx}" y1="{cy - r - 5}" x2="{cx}" y2="{cy - r - 11}" stroke="{SUN}" stroke-width="4" '
        f'stroke-linecap="round" transform="rotate({a} {cx} {cy})"/>'
        for a in range(0, 360, 45)
    )
    return f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{SUN}"/>{rays}'


def _moon(cx=30, cy=30):
    return (f'<circle cx="{cx}" cy="{cy}" r="15" fill="{MOON}"/>'
            f'<circle cx="{cx + 8}" cy="{cy - 6}" r="13" fill="var(--card)"/>')


def _cloud(dx=0, dy=0, color=CLOUD):
    return (f'<g transform="translate({dx} {dy})" fill="{color}">'
            f'<circle cx="24" cy="38" r="10"/><circle cx="36" cy="32" r="13"/><circle cx="47" cy="40" r="9"/>'
            f'<rect x="14" y="38" width="42" height="11" rx="5.5"/></g>')


def icon(kind: str, size: int = 64) -> Markup:
    body = {
        "sun": _sun(),
        "moon": _moon(),
        "partly": _sun(24, 24, 9) + _cloud(4, 6),
        "partly-night": _moon(24, 24) + _cloud(4, 6),
        "cloud": _cloud(0, 2),
        "fog": _cloud(0, -4) + "".join(
            f'<line x1="14" y1="{y}" x2="54" y2="{y}" stroke="{CLOUD_DARK}" stroke-width="4" stroke-linecap="round"/>'
            for y in (52, 59)),
        "rain": _cloud(0, -4) + "".join(
            f'<line x1="{x}" y1="50" x2="{x - 4}" y2="60" stroke="{RAIN}" stroke-width="4" stroke-linecap="round"/>'
            for x in (24, 34, 44)),
        "snow": _cloud(0, -4) + "".join(f'<circle cx="{x}" cy="{y}" r="3.2" fill="{SNOW}"/>'
                                        for x, y in ((24, 54), (34, 59), (44, 54))),
        "storm": _cloud(0, -4, CLOUD_DARK) + f'<polygon points="34,44 26,58 33,58 29,66 42,51 35,51 39,44" fill="{BOLT}"/>',
    }.get(kind, _cloud())
    return Markup(f'<svg width="{size}" height="{size}" viewBox="0 0 64 64">{body}</svg>')
