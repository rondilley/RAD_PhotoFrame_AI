"""HTTP routes of ARCHITECTURE section 5.2 (the v0.1 subset)."""

import collections
import datetime as dt
import hashlib
import secrets
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from .adapters.calendar_ics import CalendarReader
from .adapters.claude_code import ClaudeCodeReader
from .adapters.health import GarminReader, StravaReader
from .adapters.llm_cluster import ClusterReader
from .adapters.system import SystemSampler
from .adapters.weather import WeatherReader
from .config import Config
from .feeds.digest_view import calendar_from_digest
from .feeds.reflex_digest import DigestReader
from .frame_link import FrameLink
from .render_html import local, page, render

STATIC = Path(__file__).parent / "static"
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"  # inline style attributes for bar widths; scripts stay self only
OPEN = {"/healthz"}


def create_app(cfg: Config) -> FastAPI:
    tz = ZoneInfo(cfg.timezone)
    token = cfg.token()
    system = SystemSampler(cfg.disks)
    claude = ClaudeCodeReader(cfg.claude_projects, tz)
    weather = WeatherReader(cfg.weather_lat, cfg.weather_lon, cfg.weather_place, cfg.timezone)
    calendar = CalendarReader(cfg.calendars_file, tz)
    link = FrameLink(cfg.frame_serial, cfg.port)
    cluster = ClusterReader(cfg.cluster)
    garmin = GarminReader(tz)
    strava = StravaReader(tz)
    digest = DigestReader(cfg.reflex_root, cfg.timezone, every_s=cfg.digest_every_s, hours=cfg.digest_hours)
    fragments: collections.OrderedDict[str, str] = collections.OrderedDict()
    heartbeat = {"time": 0.0, "shown": None, "ua": None}
    start = time.time()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def guard(request: Request, call_next):
        path = request.url.path
        if path in OPEN or path.startswith("/admin/"):
            if request.client is None or request.client.host != "127.0.0.1":
                return PlainTextResponse("forbidden", status_code=403)
        elif not secrets.compare_digest(request.cookies.get("rf_token", ""), token):
            return PlainTextResponse("not authorized", status_code=403)
        resp: Response = await call_next(request)
        resp.headers["Content-Security-Policy"] = CSP
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    def shell_version() -> str:
        """Hash of the shell files. When it changes, the shell reloads itself."""
        h = hashlib.sha256()
        for f in sorted(STATIC.rglob("*")) + [Path(__file__).parent / "templates" / "shell.html"]:
            if f.is_file():
                h.update(f.name.encode())
                h.update(f.read_bytes())
        return h.hexdigest()[:16]

    hold = {"name": None, "until": 0.0}

    def current() -> tuple[str, int]:
        """The dashboard for this moment and the seconds left in its slot."""
        if hold["name"] and time.time() < hold["until"]:
            return hold["name"], int(hold["until"] - time.time()) + 1
        cycle = sum(s for _, s in cfg.rotation)
        t = int(time.time()) % cycle
        for name, secs in cfg.rotation:
            if t < secs:
                return name, secs - t
            t -= secs
        return cfg.rotation[0][0], cfg.rotation[0][1]

    def build(name: str) -> tuple[str, str]:
        now = time.time()
        d = dt.datetime.now(tz)
        ctx = {
            "now": now,
            "today": f"{d:%A, %B} {d.day}",
            "now_dt": d,
            "tz": tz,
            "local": lambda e, f: local(e, tz, f),
        }
        dg = digest.snapshot()
        ctx["dg"] = dg

        def cal() -> dict:
            # the digest calendar first; the iCal reader when there is no digest yet
            if dg.get("calendar") is not None:
                return calendar_from_digest(dg, tz)
            c = calendar.snapshot()
            if c["status"] == "unconfigured" and dg.get("status") == "pending":
                c["status"] = "loading"
            return c

        if name == "now":
            ctx["sys"] = system.snapshot()
            ctx["cc"] = claude.snapshot()
            ctx["cal"] = cal()
        elif name == "today":
            ctx["cal"] = cal()
            ctx["wx"] = weather.snapshot()
        elif name == "reflex":
            pass
        elif name == "health":
            ctx["garmin"] = garmin.snapshot()
            ctx["strava"] = strava.snapshot()
        elif name == "ai":
            ctx["cl"] = cluster.snapshot()
            ctx["sys"] = system.snapshot()
            ctx["cc"] = claude.snapshot()
        else:
            ctx["cc"] = claude.snapshot()
        try:
            html, version = render(f"{name}.html", **ctx)
        except Exception as e:  # one broken dashboard must not stop the poll
            html, version = render("fault.html", name=name, error=f"{type(e).__name__}: {e}"[:200], **ctx)
        fragments[version] = html
        fragments.move_to_end(version)
        while len(fragments) > 20:
            fragments.popitem(last=False)
        return html, version

    @app.get("/frame", response_class=HTMLResponse)
    def frame():
        return HTMLResponse(page("shell.html", poll_s=cfg.poll_s), headers={"Cache-Control": "no-cache"})

    @app.get("/v1/now")
    def now(request: Request, shown: str | None = None):
        name, left = current()
        _, version = build(name)
        heartbeat.update(time=time.time(), shown=shown, ua=request.headers.get("user-agent"))
        minute = int(time.time() // 60)
        shift = {"x": (minute * 7) % 13 - 6, "y": (minute * 5) % 13 - 6}
        return JSONResponse({
            "dashboard": name,
            "version": version,
            "kind": "html",
            "shell": shell_version(),
            "status": "ok",
            "shift": shift,
            "poll_s": min(cfg.poll_s, left),
            "host_ms": int(time.time() * 1000),
            "tz_offset_min": int(dt.datetime.now(tz).utcoffset().total_seconds() // 60),
        }, headers={"Cache-Control": "no-store"})

    @app.get("/v1/fragment/{version}", response_class=HTMLResponse)
    def fragment(version: str):
        html = fragments.get(version)
        if html is None:
            return PlainTextResponse("unknown version", status_code=404)
        return HTMLResponse(html, headers={"Cache-Control": "max-age=86400, immutable"})

    @app.get("/v1/display")
    def display():
        return JSONResponse({"display": "on"}, headers={"Cache-Control": "no-store"})

    @app.post("/admin/hold")
    def admin_hold(dash: str, minutes: float = 5):
        """Workstation only: keep one dashboard on the screen (for design work)."""
        if dash not in {n for n, _ in cfg.rotation}:
            return PlainTextResponse("unknown dashboard", status_code=404)
        hold.update(name=dash, until=time.time() + minutes * 60)
        return JSONResponse({"hold": dash, "minutes": minutes})

    @app.get("/healthz")
    def healthz():
        return JSONResponse({
            "uptime_s": round(time.time() - start),
            "heartbeat_age_s": round(time.time() - heartbeat["time"]) if heartbeat["time"] else None,
            "shown": heartbeat["shown"],
            "frame_link": link.state,
            "digest": digest.snapshot().get("status"),
            "claude_scan_age_s": round(time.time() - claude.last_scan) if claude.last_scan else None,
        }, headers={"Cache-Control": "no-store"})

    return app
