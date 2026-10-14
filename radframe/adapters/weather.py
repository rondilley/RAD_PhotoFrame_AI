"""Weather from Open-Meteo (no key). Keeps the last good forecast for up to 6 hours (IR-06)."""

import threading
import time

import httpx

URL = "https://api.open-meteo.com/v1/forecast"
EVERY_S = 10 * 60
KEEP_S = 6 * 3600

# WMO weather code -> (text, icon)
CODES = {
    0: ("Clear", "sun"), 1: ("Mostly clear", "sun"), 2: ("Partly cloudy", "partly"), 3: ("Cloudy", "cloud"),
    45: ("Fog", "fog"), 48: ("Fog", "fog"),
    51: ("Light drizzle", "rain"), 53: ("Drizzle", "rain"), 55: ("Heavy drizzle", "rain"),
    56: ("Freezing drizzle", "rain"), 57: ("Freezing drizzle", "rain"),
    61: ("Light rain", "rain"), 63: ("Rain", "rain"), 65: ("Heavy rain", "rain"),
    66: ("Freezing rain", "rain"), 67: ("Freezing rain", "rain"),
    71: ("Light snow", "snow"), 73: ("Snow", "snow"), 75: ("Heavy snow", "snow"), 77: ("Snow grains", "snow"),
    80: ("Showers", "rain"), 81: ("Showers", "rain"), 82: ("Heavy showers", "rain"),
    85: ("Snow showers", "snow"), 86: ("Snow showers", "snow"),
    95: ("Thunderstorm", "storm"), 96: ("Thunderstorm", "storm"), 99: ("Thunderstorm", "storm"),
}


def describe(code) -> tuple[str, str]:
    return CODES.get(int(code or 0), ("Unknown", "cloud"))


class WeatherReader:
    def __init__(self, lat: float | None, lon: float | None, place: str, tz: str):
        self.lat, self.lon, self.place, self.tz = lat, lon, place, tz
        self.lock = threading.Lock()
        self.data: dict | None = None
        self.fetched = 0.0
        self.error: str | None = None
        if lat is not None and lon is not None:
            threading.Thread(target=self._run, name="weather", daemon=True).start()

    def _run(self) -> None:
        while True:
            try:
                r = httpx.get(URL, timeout=20, params={
                    "latitude": self.lat, "longitude": self.lon, "timezone": self.tz,
                    "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
                    "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,is_day",
                    "hourly": "temperature_2m,precipitation_probability,weather_code",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                    "forecast_days": 6,
                })
                r.raise_for_status()
                with self.lock:
                    self.data = r.json()
                    self.fetched = time.time()
                    self.error = None
            except Exception as e:
                with self.lock:
                    self.error = type(e).__name__
            time.sleep(EVERY_S)

    def snapshot(self) -> dict:
        with self.lock:
            d, fetched, err = self.data, self.fetched, self.error
        if self.lat is None:
            return {"status": "unconfigured"}
        if d is None or time.time() - fetched > KEEP_S:
            return {"status": "fault", "error": err or "no data yet", "place": self.place}
        cur = d["current"]
        text, icon = describe(cur["weather_code"])
        if icon in ("sun", "partly") and not cur.get("is_day", 1):
            icon = "moon" if icon == "sun" else "partly-night"
        # next 8 hours from the current hour
        hourly = d["hourly"]
        now_key = cur["time"][:13]
        start = next((i for i, t in enumerate(hourly["time"]) if t[:13] >= now_key), 0)
        hours = []
        for i in range(start, min(start + 8, len(hourly["time"]))):
            hours.append({"hour": int(hourly["time"][i][11:13]), "temp": hourly["temperature_2m"][i],
                          "rain": hourly["precipitation_probability"][i], "icon": describe(hourly["weather_code"][i])[1]})
        daily = d["daily"]
        days = []
        for i in range(len(daily["time"])):
            days.append({"date": daily["time"][i], "hi": daily["temperature_2m_max"][i], "lo": daily["temperature_2m_min"][i],
                         "rain": daily["precipitation_probability_max"][i], "text": describe(daily["weather_code"][i])[0],
                         "icon": describe(daily["weather_code"][i])[1]})
        return {
            "status": "ok" if time.time() - fetched < 3 * EVERY_S else "out_of_date",
            "place": self.place,
            "temp": cur["temperature_2m"], "feels": cur["apparent_temperature"], "humidity": cur["relative_humidity_2m"],
            "wind": cur["wind_speed_10m"], "text": text, "icon": icon,
            "hi": days[0]["hi"] if days else None, "lo": days[0]["lo"] if days else None,
            "sunrise": daily["sunrise"][0][11:16] if daily.get("sunrise") else None,
            "sunset": daily["sunset"][0][11:16] if daily.get("sunset") else None,
            "hours": hours, "days": days, "fetched": fetched,
        }
