"""Host configuration: defaults, overridden by config/radframe.toml (ignored by git)."""

import os
import secrets
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "RAD_PhotoFrame"


@dataclass
class Config:
    bind: str = "127.0.0.1"
    port: int = 8765
    timezone: str = "America/Los_Angeles"
    rotation: list[tuple[str, int]] = field(default_factory=lambda: [("now", 30), ("today", 40), ("reflex", 45), ("health", 35), ("ai", 35), ("vibe", 30)])
    poll_s: int = 10
    claude_projects: Path = Path.home() / ".claude" / "projects"
    disks: tuple[str, ...] = ("C:\\", "G:\\")
    token_file: Path = DATA_DIR / "frame.token"
    calendars_file: Path = PROJ / "calendars.key.txt"
    frame_serial: str | None = None
    reflex_root: Path = Path.home() / "Desktop" / "Reflex_Security"
    digest_every_s: int = 60 * 60
    digest_hours: tuple[int, int] = (7, 19)
    weather_lat: float | None = None
    weather_lon: float | None = None
    weather_place: str = ""
    cluster: list[tuple[str, str]] = field(default_factory=list)
    vitals: list[tuple[str, str]] = field(default_factory=list)  # (node name, ssh target)

    @classmethod
    def load(cls, path: Path = PROJ / "config" / "radframe.toml") -> "Config":
        cfg = cls()
        if path.exists():
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            cfg.frame_serial = data.get("frame", {}).get("adb_serial")
            cfg.bind = data.get("host", {}).get("bind", cfg.bind)
            w = data.get("weather", {})
            cfg.weather_lat = w.get("latitude")
            cfg.weather_lon = w.get("longitude")
            cfg.weather_place = w.get("place", "")
            cfg.cluster = [(c["name"], c["url"]) for c in data.get("cluster", [])]
            cfg.vitals = [(c["name"], c.get("ssh", f"inference@{c['name']}")) for c in data.get("cluster", [])]
            if "rotation" in data:
                cfg.rotation = [(r["dashboard"], int(r["seconds"])) for r in data["rotation"]]
        return cfg

    def token(self) -> str:
        """The frame token. Made on the first start; kept in the host data folder only."""
        if not self.token_file.exists():
            self.token_file.parent.mkdir(parents=True, exist_ok=True)
            self.token_file.write_text(secrets.token_urlsafe(32) + "\n")
        return self.token_file.read_text().strip()
