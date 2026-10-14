"""Garmin Connect (garminconnect, token login) and Strava (official API) for the health
dashboard. Read only. Tokens from radframe.accounts; nothing goes to the frame but the
numbers on the page."""

import datetime as dt
import json
import threading
import time

import httpx

from ..accounts import GARMIN_DIR, STRAVA_FILE, garmin_ok

GARMIN_EVERY_S = 15 * 60
STRAVA_EVERY_S = 30 * 60
MI = 1609.344
G_PER_LB = 453.59237
WEIGHT_DAYS = 5 * 365
FT = 3.28084


def _g(d, *path, default=None):
    for p in path:
        if isinstance(d, list):
            d = d[0] if d else None
        if not isinstance(d, dict):
            return default
        d = d.get(p)
    return default if d is None else d


def _short(d: dt.date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def _weight(rows: list, today: dt.date) -> dict | None:
    """Index scale weigh-ins (grams), oldest first, as pounds with a time axis 0..1."""
    pts = sorted((r["calendarDate"], r) for r in rows if r.get("weight") and r.get("calendarDate"))
    if not pts:
        return None
    d0 = dt.date.fromisoformat(pts[0][0])
    span = max(1, (today - d0).days)
    lb = [r["weight"] / G_PER_LB for _, r in pts]
    last = pts[-1][1]
    peak_i = max(range(len(lb)), key=lb.__getitem__)
    return {"lb": lb[-1], "date": pts[-1][0], "date_label": _short(dt.date.fromisoformat(pts[-1][0])), "age_d": (today - dt.date.fromisoformat(pts[-1][0])).days,
            "fat": last.get("bodyFat"), "muscle_lb": (last.get("muscleMass") or 0) / G_PER_LB or None,
            "bmi": last.get("bmi"), "peak_lb": lb[peak_i], "peak_date": pts[peak_i][0], "first_date": pts[0][0],
            "series": lb, "xs": [(dt.date.fromisoformat(d) - d0).days / span for d, _ in pts], "count": len(pts)}


class GarminReader:
    def __init__(self, tz: dt.tzinfo):
        self.tz = tz
        self.lock = threading.Lock()
        self.data: dict | None = None
        self.error: str | None = None
        self.fetched = 0.0
        self.night_cache: dict[str, dict] = {}
        threading.Thread(target=self._run, name="garmin", daemon=True).start()

    def configured(self) -> bool:
        return garmin_ok()

    def _collect(self) -> dict:
        from garminconnect import Garmin

        g = Garmin()
        g.login(tokenstore=str(GARMIN_DIR))
        today = dt.datetime.now(self.tz).date()

        def safe(fn, *a):
            try:
                return fn(*a)
            except Exception:
                return None

        days = safe(g.get_daily_steps, (today - dt.timedelta(days=13)).isoformat(), today.isoformat()) or []
        steps14 = [{"date": x.get("calendarDate"), "steps": x.get("totalSteps") or 0,
                    "goal": x.get("stepGoal")} for x in days][-14:]
        with_data = [x["date"] for x in steps14 if x["steps"]]
        data_date = with_data[-1] if with_data else today.isoformat()
        s = safe(g.get_user_summary, data_date) or {}

        nights = []  # last 7 nights, oldest first; past nights do not change, so keep them
        for k in range(6, -1, -1):
            d = (today - dt.timedelta(days=k)).isoformat()
            if d not in self.night_cache:
                dto = (safe(g.get_sleep_data, d) or {}).get("dailySleepDTO") or {}
                hv = (safe(g.get_hrv_data, d) or {}).get("hrvSummary") or {}
                n = {"date": d, "sleep_s": dto.get("sleepTimeSeconds"), "deep_s": dto.get("deepSleepSeconds"),
                     "light_s": dto.get("lightSleepSeconds"), "rem_s": dto.get("remSleepSeconds"),
                     "awake_s": dto.get("awakeSleepSeconds"), "score": _g(dto, "sleepScores", "overall", "value"),
                     "hrv": hv.get("lastNightAvg"), "hrv_week": hv.get("weeklyAvg"), "hrv_status": hv.get("status")}
                if k >= 2:
                    self.night_cache[d] = n
                nights.append(n)
            else:
                nights.append(self.night_cache[d])
        bc = safe(g.get_body_composition, (today - dt.timedelta(days=WEIGHT_DAYS)).isoformat(), today.isoformat()) or {}
        weight = _weight(bc.get("dateWeightList") or [], today)
        slept = [n for n in nights if n["sleep_s"]]
        last = slept[-1] if slept else {}
        hrvs = [n for n in nights if n["hrv"]]
        lh = hrvs[-1] if hrvs else {}
        return {
            "today": today.isoformat(), "data_date": data_date,
            "sync_age_d": (today - dt.date.fromisoformat(data_date)).days,
            "steps": s.get("totalSteps"), "step_goal": s.get("dailyStepGoal"),
            "rhr": s.get("restingHeartRate"), "rhr7": s.get("lastSevenDaysAvgRestingHeartRate"),
            "active_kcal": s.get("activeKilocalories"), "stress": s.get("averageStressLevel"),
            "intensity_min": (s.get("moderateIntensityMinutes") or 0) + 2 * (s.get("vigorousIntensityMinutes") or 0),
            "bb_now": s.get("bodyBatteryMostRecentValue"), "bb_high": s.get("bodyBatteryHighestValue"),
            "bb_low": s.get("bodyBatteryLowestValue"),
            "weight": weight, "night": last, "nights": nights, "hrv_last": lh, "steps14": steps14,
            "steps_avg": round(sum(x["steps"] for x in steps14 if x["steps"]) / max(1, len(with_data))),
        }

    def _run(self) -> None:
        while True:
            if self.configured():
                try:
                    data = self._collect()
                    with self.lock:
                        self.data, self.error, self.fetched = data, None, time.time()
                except Exception as e:
                    with self.lock:
                        self.error = f"{type(e).__name__}: {str(e)[:120]}"
            time.sleep(GARMIN_EVERY_S)

    def snapshot(self) -> dict:
        if not self.configured():
            return {"status": "unconfigured"}
        with self.lock:
            d, err, f = self.data, self.error, self.fetched
        if d is None:
            return {"status": "fault" if err else "pending", "error": err}
        return {**d, "status": "ok" if time.time() - f < 3 * GARMIN_EVERY_S else "out_of_date", "error": err, "fetched": f}


class StravaReader:
    def __init__(self, tz: dt.tzinfo):
        self.tz = tz
        self.lock = threading.Lock()
        self.data: dict | None = None
        self.error: str | None = None
        self.fetched = 0.0
        self.access: tuple[str, float] | None = None
        self.athlete_id: int | None = None
        threading.Thread(target=self._run, name="strava", daemon=True).start()

    def configured(self) -> bool:
        return STRAVA_FILE.exists()

    def _token(self) -> str:
        if self.access and self.access[1] > time.time() + 300:
            return self.access[0]
        cfg = json.loads(STRAVA_FILE.read_text())
        r = httpx.post("https://www.strava.com/oauth/token", timeout=30, data={
            "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
            "grant_type": "refresh_token", "refresh_token": cfg["refresh_token"]})
        r.raise_for_status()
        t = r.json()
        if t.get("refresh_token") and t["refresh_token"] != cfg["refresh_token"]:
            cfg["refresh_token"] = t["refresh_token"]
            STRAVA_FILE.write_text(json.dumps(cfg))
        self.access = (t["access_token"], float(t["expires_at"]))
        return t["access_token"]

    def _get(self, path: str, **params):
        r = httpx.get(f"https://www.strava.com/api/v3{path}", headers={"Authorization": f"Bearer {self._token()}"},
                      params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _collect(self) -> dict:
        if not self.athlete_id:
            self.athlete_id = self._get("/athlete")["id"]
        after = int(time.time() - 366 * 86400)
        acts = []
        for page in range(1, 6):
            batch = self._get("/athlete/activities", after=after, per_page=200, page=page)
            acts += batch
            if len(batch) < 200:
                break
        out = []
        for a in acts:
            start = dt.datetime.fromisoformat(a["start_date"].replace("Z", "+00:00")).astimezone(self.tz)
            out.append({"name": a.get("name", ""), "type": a.get("sport_type") or a.get("type", ""), "start": start,
                        "mi": (a.get("distance") or 0) / MI, "moving_s": a.get("moving_time") or 0,
                        "elev_ft": (a.get("total_elevation_gain") or 0) * FT, "hr": a.get("average_heartrate")})
        out.sort(key=lambda a: a["start"], reverse=True)
        today = dt.datetime.now(self.tz).date()
        months = []
        for k in range(11, -1, -1):  # 12 months, oldest first
            y, m = divmod(today.year * 12 + today.month - 1 - k, 12)
            w = [a for a in out if (a["start"].year, a["start"].month) == (y, m + 1)]
            months.append({"label": dt.date(y, m + 1, 1).strftime("%b")[0], "hours": sum(a["moving_s"] for a in w) / 3600,
                           "count": len(w)})
        monday = today - dt.timedelta(days=today.weekday())
        weeks = []
        for k in (1, 0):
            w0 = monday - dt.timedelta(weeks=k)
            w = [a for a in out if w0 <= a["start"].date() < w0 + dt.timedelta(days=7)]
            weeks.append({"hours": sum(a["moving_s"] for a in w) / 3600, "mi": sum(a["mi"] for a in w), "count": len(w)})
        st = self._get(f"/athletes/{self.athlete_id}/stats")

        def tot(key):
            t = st.get(key) or {}
            return {"count": t.get("count") or 0, "mi": (t.get("distance") or 0) / MI,
                    "hours": (t.get("moving_time") or 0) / 3600, "elev_ft": (t.get("elevation_gain") or 0) * FT}

        last = out[0] if out else None
        return {"recent": out[:4], "months": months, "this_week": weeks[1], "last_week": weeks[0],
                "last": last, "days_since": (today - last["start"].date()).days if last else None,
                "year": {"count": len([a for a in out if a["start"].year == today.year]),
                         "hours": sum(a["moving_s"] for a in out if a["start"].year == today.year) / 3600},
                "ytd": {k: tot(f"ytd_{k}_totals") for k in ("ride", "run", "swim")},
                "all": {k: tot(f"all_{k}_totals") for k in ("ride", "run", "swim")}}

    def _run(self) -> None:
        while True:
            if self.configured():
                try:
                    data = self._collect()
                    with self.lock:
                        self.data, self.error, self.fetched = data, None, time.time()
                except Exception as e:
                    with self.lock:
                        self.error = f"{type(e).__name__}: {str(e)[:120]}"
            time.sleep(STRAVA_EVERY_S)

    def snapshot(self) -> dict:
        if not self.configured():
            return {"status": "unconfigured"}
        with self.lock:
            d, err, f = self.data, self.error, self.fetched
        if d is None:
            return {"status": "fault" if err else "pending", "error": err}
        return {**d, "status": "ok" if time.time() - f < 3 * STRAVA_EVERY_S else "out_of_date", "error": err, "fetched": f}
