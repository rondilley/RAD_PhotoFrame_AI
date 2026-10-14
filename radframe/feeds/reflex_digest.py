"""Reflex digest: a headless Claude run reads Ron's work calendar, Gmail, Slack and
Fireflies through the claude.ai connectors (read-only tools only) plus the newest
weekly reports, and gives one JSON object (digest_schema.json).

The run has no built-in tools (--tools ""), only the read tools below; every other
connector tool (send, delete, label, create) is denied. The result stays in memory
(DR-02).

    python -m radframe.feeds.reflex_digest      one run, prints a short summary
"""

import datetime as dt
import json
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from zoneinfo import ZoneInfo

from ..adapters.reflex.guard import ReflexGuard
from ..adapters.reflex.reports import newest_reports

HERE = Path(__file__).parent
READ_TOOLS = [
    "mcp__claude_ai_Google_Calendar__list_calendars",
    "mcp__claude_ai_Google_Calendar__list_events",
    "mcp__claude_ai_Google_Calendar__get_event",
    "mcp__claude_ai_Google_Calendar__search_events",
    "mcp__claude_ai_Gmail__search_threads",
    "mcp__claude_ai_Gmail__get_thread",
    "mcp__claude_ai_Gmail__get_message",
    "mcp__claude_ai_Gmail__list_labels",
    "mcp__claude_ai_Slack__slack_search_public_and_private",
    "mcp__claude_ai_Slack__slack_search_public",
    "mcp__claude_ai_Slack__slack_read_channel",
    "mcp__claude_ai_Slack__slack_read_thread",
    "mcp__claude_ai_Slack__slack_read_user_profile",
    "mcp__claude_ai_Slack__slack_search_users",
    "mcp__claude_ai_Slack__slack_search_channels",
    "mcp__claude_ai_Fireflies__fireflies_get_transcripts",
    "mcp__claude_ai_Fireflies__fireflies_get_summary",
    "mcp__claude_ai_Fireflies__fireflies_search",
    "mcp__claude_ai_Fireflies__fireflies_get_user",
    "mcp__claude_ai_Fireflies__fireflies_get_active_meetings",
]
TIMEOUT_S = 600


def run_once(reflex_root: Path, tz_name: str = "America/Los_Angeles", model: str = "sonnet") -> dict:
    tz = ZoneInfo(tz_name)
    reports = newest_reports(ReflexGuard(reflex_root))
    rtext = "\n\n".join(f"### {r['kind']} ({r['file']}, {r['age_days']} days old)\n{r['text']}" for r in reports)
    prompt = (HERE / "digest_prompt.md").read_text(encoding="utf-8").replace(
        "{now}", dt.datetime.now(tz).strftime("%A %Y-%m-%d %H:%M")).replace("{reports}", rtext or "(none)")
    schema = (HERE / "digest_schema.json").read_text(encoding="utf-8")
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("claude CLI not found")
    cmd = [exe, "-p", "--output-format", "json", "--model", model, "--no-session-persistence",
           "--tools", "", "--allowedTools", ",".join(READ_TOOLS), "--json-schema", schema]
    started = time.time()
    # an empty working folder, so no project CLAUDE.md or settings come into the run
    with tempfile.TemporaryDirectory(prefix="radframe-digest-") as cwd:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=TIMEOUT_S, cwd=cwd,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError(f"claude exit {r.returncode}: {(r.stderr or r.stdout)[-300:]}")
    out = json.loads(r.stdout)
    data = out.get("structured_output")
    if data is None:
        text = (out.get("result") or "").strip()
        text = text[text.find("{"): text.rfind("}") + 1]
        data = json.loads(text)
    for key in ("day_line", "calendar", "inbox", "slack", "meetings", "week", "notes"):
        if key not in data:
            raise RuntimeError(f"digest has no {key}")
    data["_meta"] = {"time": time.time(), "seconds": round(time.time() - started),
                     "cost_usd": out.get("total_cost_usd"), "reports": [(x["kind"], x["date"]) for x in reports]}
    return data


class DigestReader:
    """Runs the digest on a schedule in the host. Keeps the last good result in memory."""

    def __init__(self, reflex_root: Path, tz_name: str, every_s: int = 20 * 60, hours=(6, 20), weekdays_only=True):
        self.root, self.tz_name, self.every_s, self.hours, self.weekdays_only = reflex_root, tz_name, every_s, hours, weekdays_only
        self.lock = threading.Lock()
        self.data: dict | None = None
        self.error: str | None = None
        self.running = False
        threading.Thread(target=self._run, name="reflex-digest", daemon=True).start()

    def _due(self) -> bool:
        now = dt.datetime.now(ZoneInfo(self.tz_name))
        if self.data is None:
            return True
        if self.weekdays_only and now.weekday() >= 5:
            return time.time() - self.data["_meta"]["time"] > 3 * 3600
        if not (self.hours[0] <= now.hour < self.hours[1]):
            return False
        return time.time() - self.data["_meta"]["time"] >= self.every_s

    def _run(self) -> None:
        while True:
            if self._due():
                self.running = True
                try:
                    d = run_once(self.root, self.tz_name)
                    with self.lock:
                        self.data, self.error = d, None
                except Exception as e:
                    with self.lock:
                        self.error = str(e)[:200]
                finally:
                    self.running = False
            time.sleep(60)

    def snapshot(self) -> dict:
        with self.lock:
            d, err = self.data, self.error
        if d is None:
            return {"status": "pending" if err is None else "fault", "error": err, "running": self.running}
        age = time.time() - d["_meta"]["time"]
        return {**d, "status": "ok" if age < 2 * self.every_s else "out_of_date", "error": err, "age_s": age,
                "running": self.running}


if __name__ == "__main__":
    d = run_once(Path.home() / "Desktop" / "Reflex_Security")
    m = d["_meta"]
    print(f"digest in {m['seconds']} s, cost {m['cost_usd']}")
    print("calendar", len(d["calendar"]), "inbox", len(d["inbox"]), "slack", len(d["slack"]),
          "meetings", len(d["meetings"]), "priorities", len(d["week"]["priorities"]))
    print("notes:", d["notes"])
