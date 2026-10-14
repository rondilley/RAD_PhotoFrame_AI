"""Turn the digest calendar strings into the event shape that today.html uses."""

import datetime as dt


def _at(day0: dt.datetime, hhmm: str) -> dt.datetime | None:
    try:
        h, m = hhmm.strip().split(":")
        return day0.replace(hour=int(h), minute=int(m))
    except (ValueError, AttributeError):
        return None


def calendar_from_digest(dg: dict, tz: dt.tzinfo) -> dict:
    now = dt.datetime.now(tz)
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today, tomorrow = [], []
    for e in dg.get("calendar", []):
        base = day0 if e.get("day") == "today" else day0 + dt.timedelta(days=1)
        start = _at(base, e.get("start", ""))
        all_day = start is None
        if all_day:
            start = base
        end = _at(base, e.get("end", "")) or (start + dt.timedelta(minutes=30) if not all_day else base + dt.timedelta(days=1))
        ev = {"title": e.get("title", ""), "start": start, "end": end, "all_day": all_day,
              "where": e.get("with", ""), "video": bool(e.get("video")), "prep": e.get("prep", "")}
        (today if e.get("day") == "today" else tomorrow).append(ev)
    for lst in (today, tomorrow):
        lst.sort(key=lambda x: (not x["all_day"], x["start"]))
    for ev in today:
        ev["past"] = not ev["all_day"] and ev["end"] <= now
        ev["now"] = not ev["all_day"] and ev["start"] <= now < ev["end"]
    upcoming = [e for e in today + tomorrow if not e["all_day"] and e["end"] > now]
    nxt = upcoming[0] if upcoming else None
    return {"status": "ok", "today": today, "tomorrow": tomorrow, "next": nxt,
            "next_in_s": (nxt["start"] - now).total_seconds() if nxt else None,
            "fetched": dg.get("_meta", {}).get("time", 0), "source": "Reflex calendar"}
