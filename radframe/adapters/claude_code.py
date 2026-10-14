"""Claude Code activity from the transcripts in ~/.claude/projects (read only).

Each assistant message has message.usage. The reader keeps a byte offset per file,
reads only new complete lines, and counts each message id once (a message can
appear on several lines). It keeps 8 days of events in memory.
"""

import datetime as dt
import json
import threading
import time
from collections import defaultdict
from pathlib import Path

KEEP_S = 8 * 86400
ACTIVE_S = 10 * 60
SCAN_S = 30


def _project(cwd: str | None, folder: str) -> str:
    if cwd:
        return Path(cwd).name or cwd
    return folder.rsplit("-", 1)[-1]


class ClaudeCodeReader:
    def __init__(self, root: Path, tz: dt.tzinfo):
        self.root = root
        self.tz = tz
        self.lock = threading.Lock()
        self.offsets: dict[Path, int] = {}
        self.seen: set[str] = set()
        self.events: list[tuple] = []  # (epoch, project, session, model, in, out, cache_read, cache_write)
        self.session_project: dict[str, str] = {}
        self.session_last: dict[str, float] = {}
        self.last_scan = 0.0
        threading.Thread(target=self._run, name="claude-reader", daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                self.scan()
            except Exception:
                pass
            time.sleep(SCAN_S)

    def scan(self) -> None:
        cutoff = time.time() - KEEP_S
        new = []
        for f in self.root.rglob("*.jsonl"):
            try:
                st = f.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            start = self.offsets.get(f, 0)
            if st.st_size <= start:
                continue
            with f.open("rb") as fh:
                fh.seek(start)
                data = fh.read()
            end = data.rfind(b"\n") + 1
            self.offsets[f] = start + end
            folder = f.relative_to(self.root).parts[0]
            for raw in data[:end].splitlines():
                try:
                    o = json.loads(raw)
                except ValueError:
                    continue
                ts = o.get("timestamp")
                sid = o.get("sessionId") or f.stem
                if not ts:
                    continue
                try:
                    epoch = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    continue
                proj = _project(o.get("cwd"), folder)
                with self.lock:
                    self.session_project.setdefault(sid, proj)
                    self.session_last[sid] = max(self.session_last.get(sid, 0), epoch)
                msg = o.get("message") or {}
                usage = msg.get("usage") if isinstance(msg, dict) else None
                mid = msg.get("id") if isinstance(msg, dict) else None
                if not usage or not mid or mid in self.seen:
                    continue
                self.seen.add(mid)
                new.append((epoch, proj, sid, msg.get("model") or "", usage.get("input_tokens") or 0,
                            usage.get("output_tokens") or 0, usage.get("cache_read_input_tokens") or 0,
                            usage.get("cache_creation_input_tokens") or 0))
        with self.lock:
            self.events = [e for e in self.events if e[0] >= cutoff] + new
            self.events.sort()
            self.last_scan = time.time()

    def snapshot(self) -> dict:
        now = time.time()
        today0 = dt.datetime.now(self.tz).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        with self.lock:
            events = list(self.events)
            last = dict(self.session_last)
            proj_of = dict(self.session_project)
            scanned = self.last_scan

        def total(evts):
            return {
                "out": sum(e[5] for e in evts),
                "fresh_in": sum(e[4] + e[7] for e in evts),
                "cached": sum(e[6] for e in evts),
                "calls": len(evts),
            }

        today = [e for e in events if e[0] >= today0]
        by_proj: dict[str, dict] = defaultdict(lambda: {"out": 0, "calls": 0, "last": 0.0})
        for e in today:
            p = by_proj[e[1]]
            p["out"] += e[5]
            p["calls"] += 1
            p["last"] = max(p["last"], e[0])
        projects = sorted(({"name": k, **v} for k, v in by_proj.items()), key=lambda p: -p["out"])

        # output tokens per hour, last 24 hours, oldest first
        hour0 = int(now // 3600) * 3600
        hours = [0] * 24
        for e in events:
            i = 23 - int((hour0 - int(e[0] // 3600) * 3600) // 3600)
            if 0 <= i < 24:
                hours[i] += e[5]

        # output tokens per day, last 7 days, oldest first
        days = []
        for d in range(6, -1, -1):
            start = today0 - d * 86400
            days.append({"label": dt.datetime.fromtimestamp(start, self.tz).strftime("%a"),
                         "out": sum(e[5] for e in events if start <= e[0] < start + 86400)})

        active = sorted(({"session": s, "project": proj_of.get(s, "?"), "age_s": now - t}
                         for s, t in last.items() if now - t < ACTIVE_S), key=lambda a: a["age_s"])
        models: dict[str, int] = defaultdict(int)
        for e in today:
            models[e[3].replace("claude-", "")] += e[5]
        return {
            "today": total(today),
            "week": total([e for e in events if e[0] >= today0 - 6 * 86400]),
            "projects": projects,
            "hours": hours,
            "hour0": hour0,
            "days": days,
            "active": active,
            "models": sorted(models.items(), key=lambda m: -m[1]),
            "scanned": scanned,
        }
