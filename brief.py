"""Morning brief: one ntfy ping at 06:45 on weekdays.

Each section is a function taking the day and returning (title, lines) or None.
To add one, write the function and append it to SECTIONS.
"""
import json, sys, time
from datetime import date, datetime, timedelta
from functools import cache
from urllib.error import HTTPError, URLError

from commute import E, PM, T, TZ, day, get, hapi, hm, lookup, mins, now, place, trips

SEND, LEAVE, LATEST = E("BRIEF_AT", "06:45"), E("BRIEF_LEAVE", "07:30"), "09:00"
RAINY = 40  # % chance of rain that counts as "take an umbrella"
DESC = {0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
        80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
        95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail"}


def icon(code):
    return ("☀️" if code <= 1 else "⛅" if code == 2 else "☁️" if code <= 48 else "🌦" if code <= 57
            else "🌧" if code <= 67 or 80 <= code <= 82 else "🌨" if code <= 86 else "⛈")


def retry(f, tries=4):
    for n in range(tries):
        try:
            return f()
        except (HTTPError, URLError, TimeoutError):
            if n == tries - 1:
                raise
            time.sleep(5 * 2 ** n)


# --- data -------------------------------------------------------------------

@cache
def home_coords():
    v = E("HOME_ADDR")
    try:
        la, lo = (float(x) for x in v.split(","))
    except ValueError:
        x = lookup(v)[0]
        la, lo = x["lat"], x["lon"]
    return round(la, 3), round(lo, 3)


@cache
def forecast():
    la, lo = home_coords()
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={la}&longitude={lo}"
           "&current=temperature_2m,apparent_temperature,weather_code"
           "&hourly=temperature_2m,precipitation_probability,weather_code"
           "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
           "&timezone=Europe%2FBerlin&forecast_days=4")
    return json.loads(retry(lambda: get(url)))


def hours(d, frm, to):
    # [(datetime, rain %, code)] for the hourly slots of day d between frm and to
    h = forecast()["hourly"]
    out = []
    for t, p, c in zip(h["time"], h["precipitation_probability"], h["weather_code"]):
        t = datetime.fromisoformat(t)
        if hm(d, frm) <= t <= hm(d, to):
            out.append((t, p or 0, c))
    return out


def rain(slots):
    # "dry" or "rain likely, 70% at 17:00"
    t, p, c = max(slots, key=lambda s: s[1])
    return (f"{DESC.get(c, 'rain').lower()} likely, {p}% at {T(t)}" if p >= RAINY else f"dry (max {p}%)"), p >= RAINY


@cache
def morning_trips(d):
    (o, _), (w, _) = place(E("HOME_ADDR")), place(E("WORK_ADDR"))
    lf = hm(d, LEAVE)
    opts, rec = trips(o, w, lf, lf + timedelta(minutes=30))
    return opts, rec


# --- sections ---------------------------------------------------------------

def weather(d):
    f = forecast()
    i = f["daily"]["time"].index(d.isoformat())
    lo, hi = f["daily"]["temperature_2m_min"][i], f["daily"]["temperature_2m_max"][i]
    codes = [c for _, _, c in hours(d, "07:00", "19:00")]
    code = max(set(codes), key=codes.count)  # what most of your waking day looks like, not the overnight worst
    lines = []
    if d == now().date():
        c = f["current"]
        lines.append(f"Now {round(c['temperature_2m'])}°, feels {round(c['apparent_temperature'])}° · {DESC.get(c['weather_code'], '')}")
    walk, _ = rain(hours(d, LEAVE, "09:00"))
    lines.append(f"Today {round(lo)}°–{round(hi)}°, {DESC.get(code, '').lower()} · morning walk {walk}")
    return f"{icon(code)} {round(lo)}°→{round(hi)}°", lines


def way_home(d):
    text, wet = rain(hours(d, PM[0], "18:00"))
    return ("☂️ umbrella" if wet else None), [f"{'☂️ Take an umbrella — way home' if wet else 'Way home'}: {text}"]


def commute_at_leave(d):
    opts, rec = morning_trips(d)
    if not opts:
        return f"No trains from {LEAVE}", [f"RMV returned no connections leaving {LEAVE}."]
    lines = []
    for m in opts[:2]:
        rides = ", ".join(f"{r['name']} {T(r['dep'])}" + (f" pl. {r['track']}" if r["track"] else "") for r in m["rides"])
        flag = "⚠ " + " ".join(m["issues"][0][::2]) if m["issues"] else "✓"
        lines.append(f"{T(m['leave'])} → {T(m['arr'])} · {rides} {flag}")
    title = f"Leave {T(rec['leave'])} → arrive {T(rec['arr'])}" if rec else f"⚠ no clean trip from {LEAVE}"
    return title, [f"Leaving at {LEAVE}:"] + lines


def disruptions(d):
    # RMV alerts on the lines of your morning trips that apply during the commute hours
    opts, _ = morning_trips(d)
    lines = {r["line_id"]: r["line"] for m in opts for r in m["rides"] if r.get("line_id")}
    windows = [(hm(d, LEAVE), hm(d, "09:00")), (hm(d, PM[0]), hm(d, PM[1]))]
    seen, out = set(), []
    for name in set(lines.values()):
        for m in hapi("himsearch", lines=name).get("Message", []):
            if m["id"] in seen or not any(p.get("lineId") in lines for p in m.get("affectedProduct", [])):
                continue
            text = f"{m.get('head', '')} {m.get('lead', '')}"
            if not any(n in text for n in lines.values()):  # skip alerts that only list the line in passing
                continue
            if active(m, windows):
                seen.add(m["id"]); out.append(f"⚠️ {m['head'].strip()}")
    return ("⚠️ disruption" if out else None), out


def active(m, windows):
    s = datetime.strptime(f"{m['sDate']} {m['sTime']}", "%Y-%m-%d %H:%M:%S")
    e = datetime.strptime(f"{m['eDate']} {m['eTime']}", "%Y-%m-%d %H:%M:%S")
    daily = []
    if m.get("dailyStartingAt") and m.get("dailyDuration"):
        dur = timedelta(minutes=mins(m["dailyDuration"]))
        for k in (-1, 0):  # yesterday's window can run into this morning
            start = hm(windows[0][0].date() + timedelta(days=k), m["dailyStartingAt"][:5])
            daily.append((start, start + dur))
    else:
        daily = [(s, e)]
    return any(max(a, s, x) < min(b, e, y) for a, b in windows for x, y in daily)


SECTIONS = [weather, way_home, commute_at_leave, disruptions]


# --- assembly ---------------------------------------------------------------

def easter(y):
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    n = (h + l - 7 * m + 90) // 25
    return date(y, n, (h + l - 7 * m + 33 * n + 19) % 32)


def holiday(d):
    # public holidays in Hesse
    e = easter(d.year)
    days = {date(d.year, 1, 1): "New Year", e - timedelta(2): "Good Friday", e + timedelta(1): "Easter Monday",
            date(d.year, 5, 1): "Labour Day", e + timedelta(39): "Ascension", e + timedelta(50): "Whit Monday",
            e + timedelta(60): "Corpus Christi", date(d.year, 10, 3): "German Unity Day",
            date(d.year, 12, 25): "Christmas", date(d.year, 12, 26): "Boxing Day"}
    return days.get(d)


def due():
    # both DST variants of the cron fire; only the one landing in the hour before SEND counts
    sched = E("SCHEDULE")
    if not sched:
        return True
    from zoneinfo import ZoneInfo
    mi, h = map(int, sched.split()[:2])
    t = datetime.now(ZoneInfo("UTC")).replace(hour=h, minute=mi, second=0, microsecond=0).astimezone(TZ).replace(tzinfo=None)
    return hm(t.date(), SEND) - timedelta(hours=1) <= t <= hm(t.date(), SEND)


def build(d):
    titles, body = [], []
    for f in SECTIONS:
        try:
            r = f(d)
        except Exception as e:  # one broken source shouldn't sink the whole brief
            r = None, [f"({f.__name__} unavailable: {e})"]
        if r:
            if r[0]:
                titles.append(r[0])
            body += r[1]
    if d != now().date():
        body.insert(0, f"(for {d:%a %d %b})")
    return " · ".join(titles) or "Morning brief", body


def send(title, body):
    print(title, *body, sep="\n")
    if not E("NTFY_TOPIC"):
        return
    msg = {"topic": E("NTFY_TOPIC"), "title": title, "message": "\n".join(body), "tags": ["sunrise"]}
    if E("PAGE_URL"):
        msg |= {"click": E("PAGE_URL")}
    retry(lambda: get("https://ntfy.sh", data=json.dumps(msg).encode(), method="POST", headers={"Content-Type": "application/json"}))


def main():
    force = E("FORCE") == "true" or "--now" in sys.argv
    if not force:
        if not due():
            print("not this run", now()); return
        today = now().date()
        if holiday(today):
            print("holiday:", holiday(today)); return
        if now() > hm(today, LATEST):
            print("too late to send", now()); return
        time.sleep(max(0, (hm(today, SEND) - now()).total_seconds() - 60))  # fetch a minute early
    d = now().date() if now() < hm(now().date(), LEAVE) and now().weekday() < 5 else day()
    title, body = build(d)
    if not force:
        time.sleep(max(0, (hm(d, SEND) - now()).total_seconds()))
    send(title, body)


if __name__ == "__main__":
    main()
