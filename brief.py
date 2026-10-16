"""Morning brief at 06:45 on weekdays, plus an evening heads-up for tomorrow.

Each section is a function f(d, evening) returning a Sec (or None to stay quiet).
To add one, write the function and put it in SECTIONS. A section that throws
shows as "unavailable" instead of sinking the whole brief.

Optional secrets: REMINDERS (see reminders()), GCAL_ICS (Google Calendar secret
iCal address), FES_ICS (FrankfurtPlus bin calendar iCal link), FX (e.g. "INR").
"""
import json, re, sys, time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from functools import cache
from html import escape
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from zoneinfo import ZoneInfo

import commute as c
from commute import E, PM, T, TZ, get, hapi, hm, lookup, mins, now, place, trips

SEND, LEAVE, LATEST, EVENING = E("BRIEF_AT", "06:45"), E("BRIEF_LEAVE", "07:30"), "09:00", E("EVENING_AT", "20:00")
RAINY, UA = 40, {"User-Agent": "commute-brief/1.0 (github.com/smarthipad-ai/commute)"}
DESC = {0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
        51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain", 67: "Freezing rain",
        71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
        80: "Showers", 81: "Showers", 82: "Heavy showers", 85: "Snow showers", 86: "Snow showers",
        95: "Thunderstorm", 96: "Thunderstorm, hail", 99: "Thunderstorm, hail"}
OCC = {11: "quiet", 12: "moderate", 13: "busy", 14: "packed"}
BINS = {"rest": ("Restmüll", "#4b4b4b"), "papier": ("Paper", "#2f6fd1"), "bio": ("Bio", "#8a5a2b"),
        "lvp": ("Packaging", "#e2b400"), "verpack": ("Packaging", "#e2b400"), "gelb": ("Packaging", "#e2b400"),
        "sperr": ("Bulky waste", "#7a6a9a"), "grün": ("Garden waste", "#3f8f3a"), "glas": ("Glass", "#2a9d8f")}
QUOTES = [
    ("Morgenstund hat Gold im Mund. — The morning hour has gold in its mouth.", "German proverb"),
    ("Waste no more time arguing about what a good man should be. Be one.", "Marcus Aurelius"),
    ("Very little is needed to make a happy life.", "Marcus Aurelius"),
    ("It is not that we have a short time to live, but that we waste a lot of it.", "Seneca"),
    ("While we are postponing, life speeds by.", "Seneca"),
    ("Begin at once to live, and count each separate day as a separate life.", "Seneca"),
    ("Difficulties strengthen the mind, as labour does the body.", "Seneca"),
    ("First say to yourself what you would be; and then do what you have to do.", "Epictetus"),
    ("No man is free who is not master of himself.", "Epictetus"),
    ("The journey of a thousand miles begins with a single step.", "Lao Tzu"),
    ("Well begun is half done.", "Aristotle"),
    ("Knowing is not enough; we must apply. Willing is not enough; we must do.", "Goethe"),
    ("Aller Anfang ist schwer. — Every beginning is hard.", "German proverb"),
    ("Übung macht den Meister. — Practice makes the master.", "German proverb"),
    ("Do what you can, with what you have, where you are.", "Theodore Roosevelt"),
    ("Energy and persistence conquer all things.", "Benjamin Franklin"),
    ("Lost time is never found again.", "Benjamin Franklin"),
    ("Well done is better than well said.", "Benjamin Franklin"),
    ("One today is worth two tomorrows.", "Benjamin Franklin"),
    ("Never leave that till tomorrow which you can do today.", "Benjamin Franklin"),
    ("Write it on your heart that every day is the best day in the year.", "Ralph Waldo Emerson"),
    ("Nothing great was ever achieved without enthusiasm.", "Ralph Waldo Emerson"),
    ("He who has a why to live can bear almost any how.", "Friedrich Nietzsche"),
    ("Opportunities multiply as they are seized.", "Sun Tzu"),
    ("The secret of success is constancy to purpose.", "Benjamin Disraeli"),
    ("Genius is one percent inspiration and ninety-nine percent perspiration.", "Thomas Edison"),
    ("Heaven never helps the man who will not act.", "Sophocles"),
    ("Fortune favours the bold.", "Terence"),
    ("Carpe diem. — Seize the day.", "Horace"),
    ("Per aspera ad astra. — Through hardships to the stars.", "Latin proverb"),
    ("Dum spiro, spero. — While I breathe, I hope.", "Latin proverb"),
    ("Fall seven times, stand up eight.", "Japanese proverb"),
    ("Little by little, one travels far.", "Spanish proverb"),
    ("Be not afraid of going slowly; be afraid only of standing still.", "Chinese proverb"),
    ("If you want to go fast, go alone. If you want to go far, go together.", "African proverb"),
    ("A smooth sea never made a skilled sailor.", "English proverb"),
    ("Rome wasn't built in a day.", "English proverb"),
    ("The early bird catches the worm.", "English proverb"),
]


@dataclass
class Sec:
    icon: str
    title: str
    lines: list = field(default_factory=list)  # plain text, used for the ping and the page
    head: str = None  # short piece for the notification title
    tone: str = "info"  # info / ok / warn / bad; warn and bad make the evening heads-up worth sending
    html: str = None  # custom card body; otherwise lines are rendered
    data: dict = None  # extra values the page hero uses


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


def fetch(url):
    return json.loads(retry(lambda: get(url, headers=UA)))


def dt(s):
    return datetime.fromisoformat(s).astimezone(TZ).replace(tzinfo=None) if "+" in s[10:] or s.endswith("Z") else datetime.fromisoformat(s)


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
    return fetch(f"https://api.open-meteo.com/v1/forecast?latitude={la}&longitude={lo}"
                 "&current=temperature_2m,apparent_temperature,weather_code"
                 "&hourly=temperature_2m,apparent_temperature,precipitation_probability,weather_code,wind_speed_10m"
                 "&daily=weather_code,temperature_2m_max,temperature_2m_min,uv_index_max,sunrise,sunset"
                 "&timezone=Europe%2FBerlin&forecast_days=4")


@cache
def air():
    la, lo = home_coords()
    return fetch(f"https://air-quality-api.open-meteo.com/v1/air-quality?latitude={la}&longitude={lo}"
                 "&hourly=european_aqi,alder_pollen,birch_pollen,grass_pollen,mugwort_pollen,ragweed_pollen"
                 "&timezone=Europe%2FBerlin&forecast_days=3")


def hourly(src, d, frm, to, *keys):
    # [(time, key1, key2, ...)] for the hourly slots of day d between frm and to
    h = src["hourly"]
    return [(datetime.fromisoformat(t), *(h[k][i] for k in keys)) for i, t in enumerate(h["time"])
            if hm(d, frm) <= datetime.fromisoformat(t) <= hm(d, to)]


def daily(d, key):
    f = forecast()["daily"]
    return f[key][f["time"].index(d.isoformat())]


def rain(d, frm, to):
    t, p, code = max(hourly(forecast(), d, frm, to, "precipitation_probability", "weather_code"), key=lambda s: s[1] or 0)
    p = p or 0
    return (f"{DESC.get(code, 'rain').lower()} likely, {p}% at {T(t)}" if p >= RAINY else f"dry (max {p}%)"), p >= RAINY


@cache
def morning_trips(d):
    (o, _), (w, _) = place(E("HOME_ADDR")), place(E("WORK_ADDR"))
    lf = hm(d, LEAVE)
    return trips(o, w, lf, lf + timedelta(minutes=30))


@cache
def ics(name, d):
    # events on day d from the iCal feed in secret `name`: [(start, end, summary, all_day)]
    url = E(name)
    if not url:
        return None
    import icalendar, recurring_ical_events
    cal = icalendar.Calendar.from_ical(retry(lambda: get(url, headers=UA)))
    out = []
    for ev in recurring_ical_events.of(cal).at(d):
        s, e = ev["DTSTART"].dt, ev.get("DTEND", ev["DTSTART"]).dt
        allday = not isinstance(s, datetime)
        s, e = ((datetime.combine(s, datetime.min.time()), datetime.combine(e, datetime.min.time())) if allday
                else tuple(x.astimezone(TZ).replace(tzinfo=None) if x.tzinfo else x for x in (s, e)))
        out.append((s, e, str(ev.get("SUMMARY", "")).strip(), allday))
    return sorted(out)


def reminders(d, evening=False):
    """Secret REMINDERS, one per line:
         Thu: gym bag                      every Thursday
         day 1: pay rent                   every 1st of the month
         2026-11-03: dentist 15:00         once
         birthday 03-14: Anna              yearly, also flagged the day before
         countdown 2026-12-19: holidays    "37 days until holidays" every day until then
    """
    out = []
    for raw in (E("REMINDERS") or "").splitlines():
        if raw.lstrip().startswith("#"):
            continue
        key, _, text = raw.partition(":")
        key, text = key.strip().lower(), text.strip()
        if not text:
            continue
        if key[:3] in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") and len(key) <= 9:
            if ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(key[:3]) == d.weekday():
                out.append(("📌", text))
        elif m := re.fullmatch(r"day (\d{1,2})", key):
            if int(m[1]) == d.day:
                out.append(("📌", text))
        elif m := re.fullmatch(r"birthday (\d{2})-(\d{2})", key):
            for k, when in ((0, "tomorrow"),) if evening else ((0, "today"), (1, "tomorrow")):
                if (d + timedelta(k)).strftime("%m-%d") == f"{m[1]}-{m[2]}":
                    out.append(("🎂", f"{text}'s birthday {when}"))
        elif m := re.fullmatch(r"countdown (\d{4}-\d{2}-\d{2})", key):
            n = (date.fromisoformat(m[1]) - d).days
            if n == 0:
                out.append(("🎉", f"{text} — today!"))
            elif n > 0:
                out.append(("⏳", f"{n} day{'s' * (n != 1)} until {text}"))
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", key) and date.fromisoformat(key) == d:
            out.append(("📌", text))
    return out


@cache
def picture(d):
    # Wikimedia Commons picture of the day (freely licensed; credit shown on the page)
    try:
        i = fetch(f"https://api.wikimedia.org/feed/v1/wikipedia/en/featured/{d:%Y/%m/%d}")["image"]
        url = re.sub(r"/\d+px-", "/1280px-", i["thumbnail"]["source"].split("?")[0]) if i["image"]["width"] > 1280 else i["image"]["source"]
        return dict(url=url, thumb=i["thumbnail"]["source"].split("?")[0], page=i["file_page"],
                    credit=re.sub(r"\s+", " ", (i.get("artist") or {}).get("text") or "Wikimedia Commons").strip(),
                    license=(i.get("license") or {}).get("type", ""), about=re.sub(r"\s+", " ", (i.get("description") or {}).get("text", "")).strip()[:140])
    except Exception:
        return None


def quote_of(d):
    return QUOTES[d.toordinal() % len(QUOTES)]


# --- sections ---------------------------------------------------------------

def weather(d, evening):
    lo, hi, uv = daily(d, "temperature_2m_min"), daily(d, "temperature_2m_max"), daily(d, "uv_index_max")
    slots = hourly(forecast(), d, "07:00", "19:00", "temperature_2m", "precipitation_probability", "weather_code")
    codes = [s[3] for s in slots]
    code = max(set(codes), key=codes.count)  # what most of the waking day looks like, not the overnight worst
    lines = []
    if d == now().date():
        cur = forecast()["current"]
        lines.append(f"Now {round(cur['temperature_2m'])}°, feels {round(cur['apparent_temperature'])}° · {DESC.get(cur['weather_code'], '')}")
    walk, _ = rain(d, LEAVE, "09:00")
    lines.append(f"{'Tomorrow' if evening else 'Today'} {round(lo)}°–{round(hi)}°, {DESC.get(code, '').lower()} · morning walk {walk}")
    strip = "".join(f'<div class="hr"><span>{t:%H}</span><b>{icon(w)}</b><span class="tp">{round(tp)}°</span>'
                    f'<i style="--p:{p or 0}%"></i><span class="rp">{p or 0}%</span></div>' for t, tp, p, w in slots[::2])
    s = Sec(icon(code), "Weather", lines, f"{icon(code)} {round(lo)}°→{round(hi)}°")
    s.html = f'<p class="big">{escape(lines[-1])}</p>{"".join(f"<p>{escape(x)}</p>" for x in lines[:-1])}<div class="strip">{strip}</div>'
    s.data = dict(code=code, lo=lo, hi=hi, uv=uv)
    return s


def dwd_warnings(d, evening):
    la, lo = home_coords()
    out, tone = [], "warn"
    for a in fetch(f"https://api.brightsky.dev/alerts?lat={la}&lon={lo}").get("alerts", []):
        on, off = dt(a["onset"]), dt(a["expires"]) if a.get("expires") else hm(d, "23:59")
        if on <= hm(d, "20:00") and off >= hm(d, "06:00"):
            out.append(f"{a.get('headline_en') or a.get('headline_de')} ({T(on)}–{T(off)})")
            tone = "bad" if a.get("severity") in ("severe", "extreme") else tone
    return Sec("🚨", "Weather warning", out, "🚨 warning", tone) if out else None


def frost(d, evening):
    cold = min(hourly(forecast(), d, "06:00", "09:00", "temperature_2m"), key=lambda s: s[1])
    if cold[1] > 1:
        return None
    return Sec("🧊", "Frost", [f"{round(cold[1])}° at {T(cold[0])} — icy pavements and platforms possible, allow extra time"], "🧊 frost", "warn")


def way_home(d, evening):
    text, wet = rain(d, PM[0], "18:00")
    return Sec("☂️" if wet else "🌤", "Way home", [f"Way home ({PM[0]}–18:00): {text}" + (" — take an umbrella" if wet else "")],
               "☂️ umbrella" if wet else None, "warn" if wet else "ok")


def train(d, evening):
    opts, rec = morning_trips(d)
    if not opts:
        return Sec("🚆", f"Leaving at {LEAVE}", [f"RMV returned no connections leaving {LEAVE}."], f"⚠️ no trains from {LEAVE}", "bad")
    show = opts[:2] + ([rec] if rec and rec not in opts[:2] else [])  # backup: the first clean trip if the first two have problems
    lines, rows = [], []
    for m in show:
        rides = ", ".join(f"{r['name']} {T(r['dep'])}" + (f" pl. {r['track']}" if r["track"] else "")
                          + (f" ({OCC[r['occ']]})" if r.get("occ") in OCC else "") for r in m["rides"])
        flag = "⚠ " + " ".join(m["issues"][0][::2]) if m["issues"] else "✓"
        tag = "Backup: " if m is rec and m not in opts[:2] else ""
        lines.append(f"{tag}{T(m['leave'])} → {T(m['arr'])} · {rides} {flag}")
        chips = "".join(f'<span class="chip {r["kind"]}">{escape(r["name"])}</span>' for r in m["rides"])
        detail = " · ".join(f"{escape(r['name'])} {T(r['dep'])}" + (f" pl. {escape(r['track'])}" if r["track"] else "")
                            + (f' <em class="occ o{r["occ"]}">{OCC[r["occ"]]}</em>' if r.get("occ") in OCC else "") for r in m["rides"])
        st = f'<span class="st bad">{escape(m["issues"][0][2])}</span>' if m["issues"] else '<span class="st ok">on time</span>'
        rows.append(f'<div class="trip{" rec" if m is rec else ""}">{f"<small>{tag[:-2]}</small>" if tag else ""}'
                    f'<div class="tr"><b>{T(m["leave"])} → {T(m["arr"])}</b>{st}</div><div class="tr sub">{chips}<span>{detail}</span></div></div>')
    head = f"Leave {T(rec['leave'])} → arrive {T(rec['arr'])}" if rec else f"⚠️ no clean trip from {LEAVE}"
    s = Sec("🚆", f"If you leave at {LEAVE}", lines, head, "ok" if rec is opts[0] else "warn" if rec else "bad", "".join(rows))
    s.data = dict(rec=rec)
    return s


def disruptions(d, evening):
    # RMV alerts on your morning lines during commute hours, plus any strike in the RMV area that day
    opts, _ = morning_trips(d)
    lines = {r["line_id"]: r["line"] for m in opts for r in m["rides"] if r.get("line_id")}
    windows = [(hm(d, LEAVE), hm(d, "09:00")), (hm(d, PM[0]), hm(d, PM[1]))]
    seen, out = set(), []
    for name in set(lines.values()):
        for m in hapi("himsearch", lines=name).get("Message", []):
            if m["id"] in seen or not any(p.get("lineId") in lines for p in m.get("affectedProduct", [])):
                continue
            if not any(n in f"{m.get('head', '')} {m.get('lead', '')}" for n in lines.values()):  # only mentions the line in passing
                continue
            if active(m, windows):
                seen.add(m["id"]); out.append(m["head"].strip())
    for m in hapi("himsearch").get("Message", []):
        if m["id"] not in seen and "streik" in f"{m.get('head', '')} {m.get('text', '')}".lower() and active(m, [(hm(d, "05:00"), hm(d, "23:00"))]):
            seen.add(m["id"]); out.append("Strike: " + m["head"].strip())
    return Sec("⚠️", "Disruptions", out, "⚠️ disruption", "bad") if out else None


def active(m, windows):
    s = datetime.strptime(f"{m['sDate']} {m['sTime']}", "%Y-%m-%d %H:%M:%S")
    e = datetime.strptime(f"{m['eDate']} {m['eTime']}", "%Y-%m-%d %H:%M:%S")
    spans = [(s, e)]
    if m.get("dailyStartingAt") and m.get("dailyDuration"):
        dur, spans = timedelta(minutes=mins(m["dailyDuration"])), []
        for k in (-1, 0):  # yesterday's window can run into this morning
            start = hm(windows[0][0].date() + timedelta(days=k), m["dailyStartingAt"][:5])
            spans.append((start, start + dur))
    return any(max(a, s, x) < min(b, e, y) for a, b in windows for x, y in spans)


def bike(d, evening):
    am = hourly(forecast(), d, "07:00", "09:00", "temperature_2m", "precipitation_probability", "wind_speed_10m")
    pm = hourly(forecast(), d, PM[0], "18:00", "temperature_2m", "precipitation_probability", "wind_speed_10m")
    ok = all(8 <= t <= 26 and (p or 0) < 20 and w < 25 for _, t, p, w in am + pm)
    return Sec("🚲", "Bike day", [f"Dry, {round(min(x[1] for x in am))}°–{round(max(x[1] for x in pm))}° and light wind both ways — good day to cycle"], tone="ok") if ok else None


def air_quality(d, evening):
    out = []
    aqi = max((x[1] or 0 for x in hourly(air(), d, "07:00", "20:00", "european_aqi")), default=0)
    if aqi >= 60:
        out.append(f"Air quality {'very poor' if aqi >= 80 else 'poor'} (EAQI {round(aqi)}) — maybe skip the run outside")
    for k in ("alder", "birch", "grass", "mugwort", "ragweed"):
        v = max((x[1] or 0 for x in hourly(air(), d, "06:00", "20:00", f"{k}_pollen")), default=0)
        if v >= 20:
            out.append(f"{k.title()} pollen {'very high' if v >= 100 else 'high' if v >= 50 else 'moderate'} ({round(v)} grains/m³)")
    uv = daily(d, "uv_index_max")
    if uv and uv >= 6:
        out.append(f"UV index {round(uv)} — sunscreen")
    return Sec("🌿", "Air, pollen & sun", out, tone="warn") if out else None


def calendar(d, evening):
    evs = ics("GCAL_ICS", d)
    if evs is None:
        return None
    timed = [e for e in evs if not e[3]]
    lines = [f"All day: {e[2]}" for e in evs if e[3]] + [f"{T(s)}–{T(e)} {t}" for s, e, t, _ in timed[:4]]
    if not lines:
        return Sec("📅", "Calendar", ["Nothing in your calendar"], tone="ok")
    _, rec = morning_trips(d)
    if timed and rec and timed[0][0] < rec["arr"] + timedelta(minutes=10):
        lines.insert(0, f"⚠ First meeting {T(timed[0][0])} — leaving at {LEAVE} you'd arrive {T(rec['arr'])}")
    return Sec("📅", "Calendar", lines, f"📅 {T(timed[0][0])}" if timed else None, "warn" if lines[0].startswith("⚠") else "info")


def bins(d, evening):
    # evening: what to put out tonight for tomorrow; morning: what's collected today
    evs = ics("FES_ICS", d)
    if not evs:
        return None
    names = []
    for _, _, t, _ in evs:
        label, color = next((v for k, v in BINS.items() if k in t.lower()), (t, "#777"))
        names.append((label, color))
    text = ", ".join(n for n, _ in names)
    s = Sec("🗑", "Bins", [f"Put out tonight: {text}" if evening else f"Collected today: {text}"], f"🗑 {text}", "warn" if evening else "info")
    s.html = "<p>" + ("Put out tonight" if evening else "Collected today") + ": " + " ".join(
        f'<span class="bin" style="--c:{c}">{escape(n)}</span>' for n, c in names) + "</p>"
    return s


def notes(d, evening):
    r = reminders(d, evening)
    if evening:  # countdowns are for the morning; everything else is worth knowing the night before
        r = [x for x in r if x[0] != "⏳"]
    return Sec("📌", "Today" if not evening else "Tomorrow", [f"{i} {t}" for i, t in r], tone="warn" if evening else "info") if r else None


def sun(d, evening):
    rise, set_ = (datetime.fromisoformat(daily(d, k)) for k in ("sunrise", "sunset"))
    day_len = set_ - rise
    lines = [f"Sunrise {T(rise)} · sunset {T(set_)} · {day_len.seconds // 3600}h {day_len.seconds % 3600 // 60:02d}m of daylight"]
    for k in range(1, 5):  # clocks change at 2–3am on a Sunday; warn from the Thursday before
        a, b = datetime.combine(d + timedelta(k - 1), datetime.min.time(), TZ), datetime.combine(d + timedelta(k), datetime.min.time(), TZ)
        if a.utcoffset() != b.utcoffset():
            back = b.utcoffset() < a.utcoffset()
            lines.append(f"⏰ Clocks go {'back' if back else 'forward'} 1 hour early on {(d + timedelta(k - 1)):%a %d %b} — "
                         + ("an extra hour of sleep" if back else "one hour less sleep"))
    return Sec("🌅", "Daylight", lines)


def fx(d, evening):
    sym = E("FX", "INR")
    if not sym or evening:
        return None
    r = fetch(f"https://api.frankfurter.dev/v1/{(d - timedelta(10)).isoformat()}..?base=EUR&symbols={quote(sym)}")["rates"]
    days = sorted(r)
    now_, prev = r[days[-1]], r[days[-2]] if len(days) > 1 else r[days[-1]]
    lines = []
    for s in sym.split(","):
        ch = (now_[s] - prev[s]) / prev[s] * 100
        lines.append(f"€1 = {now_[s]:.2f} {s} ({'▲' if ch > 0 else '▼' if ch < 0 else '='}{abs(ch):.2f}% vs previous day)")
    return Sec("💶", "Exchange rate", lines)


SECTIONS = [weather, dwd_warnings, frost, train, disruptions, way_home, bike, air_quality, calendar, bins, notes, sun, fx]
TONE_ORDER = {"bad": 0, "warn": 1, "info": 2, "ok": 2}


# --- assembly ---------------------------------------------------------------

def easter(y):
    a, b, cc = y % 19, y // 100, y % 100
    dd, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - dd - g + 15) % 30
    i, k = cc // 4, cc % 4
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


def next_workday(d):
    d += timedelta(1)
    while d.weekday() > 4 or holiday(d):
        d += timedelta(1)
    return d


def build(d, evening=False):
    secs = []
    for f in SECTIONS:
        try:
            s = f(d, evening)
        except Exception as e:  # one broken source shouldn't sink the whole brief
            s = Sec("❔", f.__name__.replace("_", " ").title(), [f"unavailable ({type(e).__name__}: {str(e)[:80]})"])
        if s and (s.lines or s.html):
            secs.append(s)
    return secs


def message(secs, d, evening):
    heads = [s.head for s in secs if s.head]
    title = ("Tomorrow: " if evening else "") + (" · ".join(heads) or "Morning brief")
    body = []
    if d != now().date() + timedelta(1 if evening else 0):
        body.append(f"(for {d:%a %d %b})")
    for s in sorted(secs, key=lambda s: TONE_ORDER[s.tone]):
        if s.icon == "🚆":
            body += [f"🚆 {s.title}:"] + s.lines
        else:  # lines that bring their own emoji keep it
            body += [x if x[:1] in "⚠⏰🎂📌⏳🎉" else f"{s.icon} {x}" for x in s.lines]
    if not evening:
        q, who = quote_of(d)
        body.append(f"\n“{q}” — {who}")
    return title, "\n".join(body)


def page(secs, d, evening):
    w = next((s for s in secs if s.title == "Weather"), None)
    tr = next((s for s in secs if s.icon == "🚆"), None)
    pic, (q, who) = picture(now().date()), quote_of(d)
    greet = (f"Tomorrow, {d:%A}" if evening else
             "Good morning" if now().hour < 12 else "Good afternoon" if now().hour < 18 else "Good evening")
    temp = f'{round(w.data["lo"])}°<span>→</span>{round(w.data["hi"])}°' if w and w.data else ""
    rec = tr.data["rec"] if tr and tr.data else None
    leave = (f'<div class="leave"><small>Leave {LEAVE[:5]} →</small><b>{T(rec["arr"])}</b><small>at Haus 21</small></div>' if rec else "")
    bg = f"background-image:linear-gradient(180deg,rgba(0,0,0,.15),rgba(0,0,0,.65)),url('{escape(pic['url'])}')" if pic else ""
    hero = (f'<header class="hero" style="{bg}"><div class="hi"><p class="date">{d:%A, %d %B}</p><h1>{greet}</h1>'
            f'<div class="now"><div class="temp">{w.icon if w else ""} {temp}</div>{leave}</div>'
            f'<blockquote>“{escape(q)}”<cite>— {escape(who)}</cite></blockquote></div></header>')
    cards = []
    for s in sorted(secs, key=lambda s: TONE_ORDER[s.tone]):  # problems first, otherwise section order
        body = s.html or "".join(f"<p>{escape(x)}</p>" for x in s.lines)
        cards.append(f'<section class="card {s.tone}"><h2><span>{s.icon}</span>{escape(s.title)}</h2>{body}</section>')
    credit = (f'<p>Photo: <a href="{escape(pic["page"])}">{escape(pic["about"] or "Wikimedia Commons picture of the day")}</a> · '
              f'{escape(pic["credit"])} · {escape(pic["license"])}</p>') if pic else ""
    page_url = E("PAGE_URL") or "../"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{'Tomorrow' if evening else 'Morning brief'}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Inter:wght@400;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f5f2ec;--card:#fff;--ink:#1d1b18;--mute:#76716a;--line:#e7e2d9;--ok:#1f7a4d;--okb:#e4f3ea;--warn:#a35d00;--warnb:#fdf1de;--bad:#b42318;--badb:#fde8e6;
--u:#1b64b0;--s:#2f8f3a;--bus:#8b3a8f;--tram:#c4322a;--rail:#5b5b5b}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121211;--card:#1d1c1a;--ink:#f1eee7;--mute:#9b968c;--line:#302e2a;--ok:#5fd39a;--okb:#14321f;--warn:#f0b54d;--warnb:#36270f;--bad:#ff8a7e;--badb:#3a1613}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}}
.hero{{min-height:440px;background:#2b3a4a linear-gradient(160deg,#36506b,#c98b5e) center/cover;color:#fff;display:flex;align-items:flex-end}}
.hi{{width:100%;max-width:600px;margin:0 auto;padding:28px 18px 26px}}
.date{{margin:0;font-size:13px;letter-spacing:.08em;text-transform:uppercase;opacity:.85}}
h1{{font-family:Fraunces,Georgia,serif;font-weight:700;font-size:44px;line-height:1.05;margin:4px 0 18px;text-shadow:0 2px 18px rgba(0,0,0,.35)}}
.now{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:18px}}
.temp,.leave{{background:rgba(255,255,255,.16);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.25);border-radius:16px;padding:10px 16px}}
.temp{{font:600 30px/1.2 Fraunces,Georgia,serif}}.temp span{{opacity:.6;margin:0 4px;font-size:22px}}
.leave{{display:flex;flex-direction:column;justify-content:center}}.leave b{{font:700 26px/1.1 Fraunces,Georgia,serif}}.leave small{{font-size:12px;opacity:.85}}
blockquote{{margin:0;font:500 19px/1.4 Fraunces,Georgia,serif;text-shadow:0 1px 12px rgba(0,0,0,.4);max-width:520px}}
cite{{display:block;font:400 13px Inter,sans-serif;opacity:.85;margin-top:6px;font-style:normal}}
main{{max-width:600px;margin:-14px auto 0;padding:0 14px 30px;position:relative}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:14px 16px;margin:0 0 12px;box-shadow:0 1px 2px rgba(0,0,0,.04)}}
.card.warn{{border-left:5px solid var(--warn)}}.card.bad{{border-left:5px solid var(--bad);background:linear-gradient(90deg,var(--badb),var(--card) 40%)}}
.card h2{{font-size:12px;letter-spacing:.07em;text-transform:uppercase;color:var(--mute);margin:0 0 8px;display:flex;gap:8px;align-items:center}}
.card h2 span{{font-size:17px;letter-spacing:0}}.card p{{margin:4px 0}}.big{{font-size:16px;font-weight:600}}
.strip{{display:flex;gap:4px;overflow-x:auto;margin-top:10px;padding-bottom:2px}}
.hr{{flex:1;min-width:36px;display:flex;flex-direction:column;align-items:center;gap:2px;font-size:12px;color:var(--mute)}}
.hr b{{font-size:18px}}.hr .tp{{color:var(--ink);font-weight:600;font-size:14px}}
.hr i{{display:block;width:8px;height:34px;border-radius:4px;background:linear-gradient(to top,#378add var(--p),var(--line) var(--p))}}.hr .rp{{font-size:11px}}
.trip{{border-top:1px solid var(--line);padding:9px 0}}.trip:first-of-type{{border-top:0;padding-top:2px}}.trip.rec b{{color:var(--ok)}}
.trip small{{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--warn);font-weight:600}}
.tr{{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}}.tr b{{font-size:20px;font-variant-numeric:tabular-nums}}
.tr.sub{{justify-content:flex-start;color:var(--mute);font-size:13px;margin-top:4px}}
.chip{{display:inline-block;color:#fff;font-weight:700;font-size:12px;padding:2px 7px;border-radius:5px;background:var(--rail)}}
.chip.u{{background:var(--u)}}.chip.s{{background:var(--s);border-radius:10px}}.chip.bus{{background:var(--bus)}}.chip.tram{{background:var(--tram)}}
.st{{font-size:12px;font-weight:600;padding:3px 9px;border-radius:99px}}.st.ok{{color:var(--ok);background:var(--okb)}}.st.bad{{color:var(--bad);background:var(--badb)}}
.occ{{font-style:normal;font-size:11px;padding:1px 6px;border-radius:5px;background:var(--bg)}}.occ.o13,.occ.o14{{color:var(--warn);background:var(--warnb)}}
.bin{{display:inline-block;padding:2px 10px;border-radius:99px;color:#fff;background:var(--c);font-weight:600;font-size:13px;margin:2px 2px 0 0}}
footer{{color:var(--mute);font-size:12px;text-align:center;padding:4px 10px 0}}footer a{{color:inherit}}
</style></head><body>{hero}<main>{"".join(cards)}
<footer><p><a href="{escape(page_url)}">Live commute page →</a></p>{credit}<p>Made {T(now())} · RMV, Open-Meteo, DWD via Bright Sky, ECB</p></footer>
</main></body></html>"""


def send(title, body, tag="sunrise", pic=None, priority=3):
    print(title, body, sep="\n")
    if not E("NTFY_TOPIC"):
        return
    url = (E("PAGE_URL") or "") + "brief/"
    msg = {"topic": E("NTFY_TOPIC"), "title": title, "message": body, "tags": [tag], "priority": priority, "click": url,
           "actions": [{"action": "view", "label": "Open brief", "url": url}]}
    if pic:
        msg["attach"] = pic["thumb"]
    retry(lambda: get("https://ntfy.sh", data=json.dumps(msg).encode(), method="POST", headers={"Content-Type": "application/json"}))


def mode():
    # which scheduled run this is: "morning", "evening" or None. Both DST variants of each cron fire; only one lands right.
    sched = E("SCHEDULE")
    if not sched:
        return None
    mi, h = map(int, sched.split()[:2])
    t = datetime.now(ZoneInfo("UTC")).replace(hour=h, minute=mi, second=0, microsecond=0).astimezone(TZ).replace(tzinfo=None)
    for name, at in (("morning", SEND), ("evening", EVENING)):
        if hm(t.date(), at) - timedelta(hours=1) <= t <= hm(t.date(), at):
            return name


def follow_up(d, secs):
    # keep an eye on the 07:30 trips until the live notifier takes over at 07:00; ping only on a new problem
    seen = c.sig(dict(opts=morning_trips(d)[0]))
    while now() + timedelta(minutes=5) < hm(d, c.AM[0]):
        time.sleep(300)
        morning_trips.cache_clear()
        try:
            opts, rec = morning_trips(d)
        except Exception as e:
            print("follow-up check failed:", e); continue
        new = c.sig(dict(opts=opts)) - seen
        seen |= new
        if new:
            s = train(d, False)
            send("⚠️ " + ", ".join(f"{n} {T(t)} {w}" for n, t, w in sorted(new, key=lambda i: i[1])), "\n".join(s.lines), "warning", priority=4)


def run(d, evening, wait_until=None):
    secs = build(d, evening)
    title, body = message(secs, d, evening)
    try:
        c.publish(page(secs, d, evening), "brief/index.html")
    except Exception as e:  # the ping matters more than the page
        print("page publish failed:", e)
    if wait_until:
        time.sleep(max(0, (wait_until - now()).total_seconds()))
    return secs, title, body


def main():
    a = sys.argv[1:]
    force = E("FORCE") == "true" or "--now" in a or "--evening" in a
    m = "evening" if "--evening" in a else mode() if not force else "morning"
    today = now().date()
    if not force and m is None and E("SCHEDULE"):
        print("not this run", now()); return
    if m == "evening":
        d = next_workday(today)
        if not force and d != today + timedelta(1):  # weekend or holiday tomorrow
            print("no workday tomorrow"); return
        secs, title, body = run(d, True, None if force else hm(today, EVENING))
        # stay quiet unless something needs doing tonight or tomorrow early; Sunday always gets a preview of the week
        if force or today.weekday() == 6 or any(s.tone in ("warn", "bad") and s.title != "Way home" for s in secs):
            send(title, body, "crescent_moon")
        else:
            print("nothing worth a ping tonight")
        return
    if not force:
        if today.weekday() > 4 or holiday(today):
            print("no brief today:", holiday(today) or "weekend"); return
        if now() > hm(today, LATEST):
            print("too late to send", now()); return
        time.sleep(max(0, (hm(today, SEND) - now()).total_seconds() - 90))  # fetch shortly before 06:45
    d = today if (now() < hm(today, LEAVE) and today.weekday() < 5 and not holiday(today)) else next_workday(today)
    secs, title, body = run(d, False, None if force else hm(today, SEND))
    send(title, body, pic=picture(today))
    if not force and d == today:
        follow_up(d, secs)


if __name__ == "__main__":
    main()
