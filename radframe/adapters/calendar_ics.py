"""Calendars from secret iCal (ICS) addresses. Read only.

The addresses are secrets. They are in <project>/calendars.key.txt, one per line:
    <label> <https://calendar.google.com/calendar/ical/.../basic.ics>
The reader never logs or shows an address. Event text stays in memory.
"""

import datetime as dt
import threading
import time
from pathlib import Path

import httpx
import icalendar
import recurring_ical_events

EVERY_S = 5 * 60
KEEP_S = 6 * 3600


def read_sources(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        label, _, url = line.partition(" ")
        if url.strip().startswith("https://"):
            out.append((label, url.strip()))
    return out


def _as_local(v, tz: dt.tzinfo) -> tuple[dt.datetime, bool]:
    """(local datetime, all_day) for a DTSTART or DTEND value."""
    if isinstance(v, dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=tz)
        return v.astimezone(tz), False
    return dt.datetime(v.year, v.month, v.day, tzinfo=tz), True


class CalendarReader:
    def __init__(self, key_file: Path, tz: dt.tzinfo):
        self.key_file = key_file
        self.tz = tz
        self.lock = threading.Lock()
        self.cals: dict[str, icalendar.Calendar] = {}
        self.fetched: dict[str, float] = {}
        self.errors: dict[str, str] = {}
        threading.Thread(target=self._run, name="calendar", daemon=True).start()

    def configured(self) -> bool:
        return bool(read_sources(self.key_file))

    def _run(self) -> None:
        while True:
            for label, url in read_sources(self.key_file):
                try:
                    r = httpx.get(url, timeout=30, follow_redirects=True)
                    r.raise_for_status()
                    cal = icalendar.Calendar.from_ical(r.content)
                    with self.lock:
                        self.cals[label] = cal
                        self.fetched[label] = time.time()
                        self.errors.pop(label, None)
                except Exception as e:  # never put the URL in the message
                    with self.lock:
                        self.errors[label] = f"{type(e).__name__}" + (f" {e.response.status_code}" if isinstance(e, httpx.HTTPStatusError) else "")
            time.sleep(EVERY_S)

    def snapshot(self) -> dict:
        if not self.configured():
            return {"status": "unconfigured", "today": [], "tomorrow": [], "next": None, "next_in_s": None, "fetched": 0, "errors": {}}
        now = dt.datetime.now(self.tz)
        day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = day0 + dt.timedelta(days=2)
        events = []
        with self.lock:
            cals = dict(self.cals)
            fetched = dict(self.fetched)
            errors = dict(self.errors)
        for label, cal in cals.items():
            if time.time() - fetched.get(label, 0) > KEEP_S:
                continue
            for ev in recurring_ical_events.of(cal).between(day0, end):
                if str(ev.get("STATUS", "")).upper() == "CANCELLED":
                    continue
                if str(ev.get("TRANSP", "")).upper() == "TRANSPARENT" and "DTEND" not in ev:
                    continue
                start, all_day = _as_local(ev.decoded("DTSTART"), self.tz)
                if "DTEND" in ev:
                    stop, _ = _as_local(ev.decoded("DTEND"), self.tz)
                else:
                    stop = start + (dt.timedelta(days=1) if all_day else ev.decoded("DURATION", dt.timedelta(0)))
                where = str(ev.get("LOCATION", "") or "")
                desc = str(ev.get("DESCRIPTION", "") or "")
                video = "zoom.us" in (where + desc) or "meet.google.com" in (where + desc) or "teams.microsoft" in (where + desc)
                events.append({
                    "cal": label, "title": str(ev.get("SUMMARY", "(no title)")), "start": start, "end": stop,
                    "all_day": all_day, "where": "" if video and where.startswith("http") else where[:60], "video": video,
                })
        events.sort(key=lambda e: (not e["all_day"], e["start"]))
        tomorrow0 = day0 + dt.timedelta(days=1)
        today = [e for e in events if e["start"] < tomorrow0 and e["end"] > day0]
        tomorrow = [e for e in events if e["start"] >= tomorrow0 or (e["all_day"] and e["start"] == tomorrow0)]
        for e in today:
            e["past"] = not e["all_day"] and e["end"] <= now
            e["now"] = not e["all_day"] and e["start"] <= now < e["end"]
        upcoming = [e for e in events if not e["all_day"] and e["end"] > now]
        nxt = upcoming[0] if upcoming else None
        status = "ok" if cals and not errors else ("fault" if not cals else "partial")
        return {
            "status": status, "errors": errors, "today": today, "tomorrow": tomorrow, "next": nxt,
            "next_in_s": (nxt["start"] - now).total_seconds() if nxt else None,
            "fetched": min(fetched.values()) if fetched else 0,
        }
