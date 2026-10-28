import json, os, re, subprocess, sys, tempfile, time
from datetime import date, datetime, timedelta
from functools import cache
from html import escape
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API = "https://www.rmv.de/hapi"
TZ = ZoneInfo("Europe/Berlin")
E = os.environ.get
LEAVE_FROM, LEAVE_TO, ARRIVE_BY = E("LEAVE_FROM", "07:30"), E("LEAVE_TO", "08:00"), E("ARRIVE_BY", "08:30")
AM, PM = (E("AM_FROM", "07:00"), E("AM_TO", "09:00")), (E("PM_FROM", "15:00"), E("PM_TO", "17:30"))
LATE, STEP, AHEAD = 5, 5, 60
GO_AM, GO_PM = E("BRIEF_LEAVE", "07:30"), E("WORK_LEAVE")  # when you usually head out; drives the "time to go" ping


def now():
    return datetime.now(TZ).replace(tzinfo=None)


def hm(d, x):
    return datetime.combine(d, datetime.strptime(x, "%H:%M").time())


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


def get(url, tries=3, timeout=30, **kw):
    # every outside call goes through here: retry dropped connections, timeouts and server errors, not client errors like 404
    for n in range(tries):
        try:
            with urlopen(Request(url, **kw), timeout=timeout) as r:
                return r.read()
        except HTTPError as e:
            if (e.code < 500 and e.code != 429) or n == tries - 1:
                raise
        except (OSError, HTTPException):  # URLError, timeouts, connection resets
            if n == tries - 1:
                raise
        time.sleep(3 * 3 ** n)


def hapi(ep, **p):
    return json.loads(get(f"{API}/{ep}?" + urlencode({"accessId": E("RMV_KEY"), "format": "json", **p})))


def lookup(q, n=1):
    out = []
    for x in hapi("location.name", input=q, type="ALL", maxNo=n).get("stopLocationOrCoordLocation", []):
        out += [x[k] for k in ("StopLocation", "CoordLocation") if k in x]
    return out


@cache
def place(v):
    m = re.fullmatch(r"\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*", v)
    if m:
        la, lo = (f"{float(x):.6f}" for x in (m[1], m[2]))
        return {"CoordLat": la, "CoordLong": lo}, f"pin {la}, {lo}"
    p = lookup(v)[0]
    return {"Id": p["id"]}, p["name"]


def at(ev, rt=True):
    t = ev.get("rtTime") if rt else None
    d = ev.get("rtDate") if t else None
    return datetime.strptime(f"{d or ev['date']} {t or ev['time']}", "%Y-%m-%d %H:%M:%S")


def mins(iso):
    m = re.fullmatch(r"P(?:\d+D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", iso or "")
    return int(m[1] or 0) * 60 + int(m[2] or 0) if m else 0


def kind(name):
    n = name.upper()
    for k, p in (("u", "U"), ("s", "S"), ("tram", "TRAM"), ("bus", "BUS"), ("rail", "R")):
        if re.match(p + r"\s?\d", n) or n.startswith(p + " "):
            return k
    return "bus" if "BUS" in n else "rail"


def model(t):
    legs, raw = [], t["LegList"]["Leg"]
    for l in raw:
        o, d = l["Origin"], l["Destination"]
        if l.get("type") in ("TETA", "TAXI"):  # on-demand shuttle (e.g. KNUT): a ride, but one you have to book in the app
            name = " ".join((l.get("name") or "On-demand").split())
            legs.append(dict(ride=True, name=name, kind="demand", dir="", line=name, line_id=None, occ=0, frm=o["name"], to=d["name"],
                             dep=at(o), pdep=at(o, False), arr=at(d), parr=at(d, False), track=None, moved=False, cancelled=False,
                             risk=False, notes=["On-demand service: book it in the app"], demand=True))
        elif l.get("type") == "JNY":
            name = " ".join((l.get("name") or "").split())
            pr = l.get("Product") or {}
            pr = (pr[0] if pr else {}) if isinstance(pr, list) else pr
            msgs = [m.get("head", "").strip() for m in (l.get("Messages") or {}).get("Message", [])]
            occ = max((o.get("raw", 0) for o in l.get("Occupancy") or []), default=0)
            legs.append(dict(ride=True, name=name, kind=kind(name), dir=l.get("direction", ""), line=pr.get("line") or name, line_id=pr.get("lineId"), occ=occ,
                             frm=o["name"], to=d["name"], dep=at(o), pdep=at(o, False), arr=at(d), parr=at(d, False),
                             track=o.get("rtTrack") or o.get("track"), moved=bool(o.get("rtTrack") and o.get("track") and o["rtTrack"] != o["track"]),
                             cancelled=bool(l.get("cancelled") or o.get("cancelled") or d.get("cancelled")),
                             risk=l.get("reachable") is False, notes=[m for m in msgs if m]))
        else:
            w = mins(l.get("duration")) or round((at(d, False) - at(o, False)).total_seconds() / 60)
            if w:
                legs.append(dict(ride=False, mins=w, to=d["name"]))
    rides = [l for l in legs if l["ride"]]
    if not rides:
        return None
    i0 = next(i for i, l in enumerate(legs) if l["ride"])
    i1 = max(i for i, l in enumerate(legs) if l["ride"])
    w0 = sum(l["mins"] for l in legs[:i0])  # all the walking before the first ride, not just one leg
    w1 = sum(l["mins"] for l in legs[i1 + 1:])  # and after the last
    for r in rides:
        r["delay"] = round((r["dep"] - r["pdep"]).total_seconds() / 60)
    # RMV's own start and end times are the ground truth; the walk sums keep live delays of the last ride in the arrival
    leave = min(rides[0]["pdep"] - timedelta(minutes=w0), at(raw[0]["Origin"], False))
    arr = max(rides[-1]["arr"] + timedelta(minutes=w1), at(raw[-1]["Destination"]))
    issues = []
    for r in rides:
        if r["cancelled"]:
            issues.append((r["name"], r["pdep"], "cancelled"))
        elif r["risk"]:
            issues.append((r["name"], r["pdep"], "connection at risk"))
        elif r["delay"] >= LATE:
            issues.append((r["name"], r["pdep"], f"+{r['delay']} min"))
    return dict(legs=legs, rides=rides, leave=leave, arr=arr, issues=issues, demand=any(r.get("demand") for r in rides))


def day():
    n = now()
    d = n.date()
    if n.time() > datetime.strptime(LEAVE_TO, "%H:%M").time() or d.weekday() > 4:
        d += timedelta(days=1)
        while d.weekday() > 4:
            d += timedelta(days=1)
    return d


def trips(o, d, lf, lt, by=None):
    q = lf - timedelta(minutes=20)
    p = {**{"origin" + k: v for k, v in o.items()}, **{"dest" + k: v for k, v in d.items()},
         "date": f"{q:%Y-%m-%d}", "time": f"{q:%H:%M}", "numF": 6}
    out, seen, ctx = [], set(), None
    for _ in range(5):
        r = hapi("trip", **p, **({"context": ctx} if ctx else {}))
        ms = [m for m in map(model, r.get("Trip", [])) if m]
        for m in ms:
            key = (m["leave"], m["arr"], tuple(x["name"] for x in m["rides"]))
            if key not in seen and lf <= m["leave"] <= lt:
                seen.add(key); out.append(m)
        ctx = r.get("scrF")
        if not ms or not ctx or max(m["leave"] for m in ms) > lt:
            break
    for m in out:
        m["late"] = bool(by) and m["arr"] > by
        m["spare"] = round((by - m["arr"]).total_seconds() / 60) if by else None
        m["gone"] = m["leave"] < now()
        m["ok"] = not m["issues"] and not m["late"]
    out.sort(key=lambda m: (m["leave"], m["arr"]))
    live = [m for m in out if not m["gone"]]
    # prefer trips that don't need an on-demand booking; fall back to them when nothing else is clean
    good = [m for m in live if m["ok"] and not m["demand"]] or [m for m in live if m["ok"]]
    # with a deadline: the latest clean trip that makes it; live: the next clean trip
    rec = (good[-1] if by else good[0]) if good else None
    for m in out:
        m["rec"] = m is rec
    return out, rec


def snapshot(back=False, live=False):
    a, b = ("WORK_ADDR", "HOME_ADDR") if back else ("HOME_ADDR", "WORK_ADDR")
    (o, _), (d, _) = place(E(a)), place(E(b))
    if live:
        n = now()
        dt, lf, lt, by = n.date(), n, n + timedelta(minutes=AHEAD), None
    else:
        dt = day()
        lf, lt, by = (hm(dt, x) for x in (LEAVE_FROM, LEAVE_TO, ARRIVE_BY))
    opts, rec = trips(o, d, lf, lt, by)
    return dict(date=dt, opts=opts, rec=rec, at=now(), lf=lf, lt=lt, by=by,
                route="Haus 21 → Home" if back else "Home → Haus 21")


T = lambda x: x.strftime("%H:%M")
short = lambda n: re.sub(r"^Frankfurt \(Main\)\s*-?\s*", "", n)


def chip(r):
    return f'<span class="chip {r["kind"]}">{escape(r["name"])}</span>'


def timeline(m):
    rows = []
    for l in m["legs"]:
        if not l["ride"]:
            rows.append(f'<li class="walk"><span class="t"></span><span class="dot"></span><span class="w">Walk {l["mins"]} min</span></li>')
            continue
        dep = f'<s>{T(l["pdep"])}</s> <b class="bad">{T(l["dep"])}</b>' if l["delay"] > 0 else T(l["dep"])
        arr = f'<s>{T(l["parr"])}</s> <b class="bad">{T(l["arr"])}</b>' if l["arr"] != l["parr"] else T(l["arr"])
        tags = []
        if l["cancelled"]:
            tags.append('<em class="tag bad">Cancelled</em>')
        elif l["delay"] > 0:
            tags.append(f'<em class="tag {"bad" if l["delay"] >= LATE else "warn"}">+{l["delay"]} min</em>')
        if l["risk"]:
            tags.append('<em class="tag bad">Connection at risk</em>')
        if l["track"]:
            tags.append(f'<em class="tag {"warn" if l["moved"] else ""}">Platform {escape(l["track"])}{" (changed)" if l["moved"] else ""}</em>')
        notes = "".join(f'<p class="note">{escape(n)}</p>' for n in l["notes"][:2])
        dirn = f' <span class="dir">→ {escape(short(l["dir"]))}</span>' if l["dir"] else ""
        rows.append(
            f'<li class="ride {l["kind"]}"><span class="t">{dep}</span><span class="dot"></span>'
            f'<div>{chip(l)}{dirn}<div class="stop">{escape(short(l["frm"]))}</div>'
            f'<div class="tags">{"".join(tags)}</div>{notes}</div></li>'
            f'<li class="ride {l["kind"]} end"><span class="t">{arr}</span><span class="dot"></span><div class="stop">{escape(short(l["to"]))}</div></li>')
    return "<ol class=\"tl\">" + "".join(rows) + "</ol>"


def status(m):
    if m["gone"]:
        return '<span class="st mute">Gone</span>'
    if any(i[2] == "cancelled" for i in m["issues"]):
        return '<span class="st bad">Cancelled</span>'
    if m["issues"]:
        return f'<span class="st bad">{escape(m["issues"][0][2])}</span>'
    if m["late"]:
        return f'<span class="st warn">{-m["spare"]} min late</span>'
    return f'<span class="st ok">{"On time" if m["spare"] is None else str(m["spare"]) + " min spare"}</span>'


def card(m):
    dur = round((m["arr"] - m["leave"]).total_seconds() / 60)
    cls = "card" + (" rec" if m["rec"] else "") + (" gone" if m["gone"] else "") + ("" if m["ok"] else " issue")
    badge = '<div class="pick">Leave by this one</div>' if m["rec"] else ""
    return (f'<details class="{cls}"{" open" if m["rec"] else ""}><summary>{badge}<div class="row">'
            f'<div class="times"><b>{T(m["leave"])}</b><span class="arrow">→</span><b>{T(m["arr"])}</b></div>{status(m)}</div>'
            f'<div class="row sub"><span class="chips">{"".join(chip(r) for r in m["rides"])}</span><span>{dur} min</span></div></summary>'
            f'{timeline(m)}</details>')


def render(s):
    rec, by, win = s["rec"], s["by"], f'{T(s["lf"])}–{T(s["lt"])}'
    if rec:
        dur = round((rec["arr"] - rec["leave"]).total_seconds() / 60)
        sub = f"{rec['spare']} min before {T(by)}" if by else f"{dur} min door to door"
        hero = (f'<p class="eyebrow">{"Leave by" if by else "Next clean trip · leave"}</p><h1>{T(rec["leave"])}</h1>'
                f'<p class="lead">Arrive {T(rec["arr"])} · {sub}</p>')
    else:
        hero = (f'<p class="eyebrow">Heads up</p><h1 class="bad">No clean option</h1><p class="lead">Nothing leaving {win} '
                f'gets you there{f" by {T(by)}" if by else ""} without a problem. Check the list.</p>')
    cards = "".join(map(card, s["opts"])) or '<p class="empty">RMV returned no connections.</p>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light dark"><meta name="theme-color" content="#1b2433">
<noscript><meta http-equiv="refresh" content="120"></noscript><title>Commute</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,600;9..144,700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--bg:#f2eee6;--card:#fffdf9;--ink:#1b1a17;--mute:#7a746a;--line:#ebe5d8;--soft:#f5f1e8;--ok:#15803d;--okb:#e3f5e8;--warn:#b45309;--warnb:#fdf0dc;--bad:#c62828;--badb:#fde9e7;--acc:#15803d;
--u:#1b64b0;--s:#2f8f3a;--bus:#8b3a8f;--tram:#c4322a;--rail:#6b6b6b;--shadow:0 1px 1px rgba(60,40,10,.04),0 12px 30px -16px rgba(60,40,10,.28)}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d0e10;--card:#17181b;--ink:#f3f1ec;--mute:#9d988d;--line:#2a2b2f;--soft:#1f2024;--okb:#10301c;--ok:#4ade80;--warnb:#33260c;--warn:#fbbf24;--badb:#3a1512;--bad:#ff8a80;--acc:#4ade80;
--shadow:0 1px 0 rgba(255,255,255,.04),0 14px 34px -16px rgba(0,0,0,.7)}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}}
.top{{background:linear-gradient(160deg,#1b2433,#36506b 60%,#7c5a48);color:#fff;padding:26px 16px 46px}}
.top>div{{max-width:560px;margin:0 auto}}
main{{max-width:560px;margin:-28px auto 0;padding:0 14px 40px;position:relative}}
.eyebrow{{margin:0;font-size:12px;letter-spacing:.09em;text-transform:uppercase;opacity:.8}}
h1{{margin:4px 0 6px;font:700 64px/1 Fraunces,Georgia,serif;letter-spacing:-.02em;font-variant-numeric:tabular-nums;animation:up .7s cubic-bezier(.2,.8,.2,1) both}}
h1.bad{{color:#ffb4a8}}@keyframes up{{from{{opacity:0;transform:translateY(10px)}}}}
.lead{{margin:0 0 4px;font-size:17px}}.meta{{margin:6px 0 0;font-size:13px;opacity:.8}}
h2{{font-size:11.5px;color:var(--mute);text-transform:uppercase;letter-spacing:.09em;margin:18px 4px 10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:20px;margin:0 0 12px;overflow:hidden;box-shadow:var(--shadow);animation:up .6s cubic-bezier(.2,.8,.2,1) both}}
.card:nth-child(2){{animation-delay:.06s}}.card:nth-child(3){{animation-delay:.12s}}.card:nth-child(4){{animation-delay:.18s}}
.card.rec{{box-shadow:inset 4px 0 0 var(--acc),var(--shadow)}}.card.gone{{opacity:.45}}.card.issue{{box-shadow:inset 4px 0 0 var(--bad),var(--shadow)}}
summary{{list-style:none;cursor:pointer;padding:15px 18px}}summary::-webkit-details-marker{{display:none}}
.pick{{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px;color:var(--ok)}}
.row{{display:flex;align-items:center;justify-content:space-between;gap:10px}}.sub{{margin-top:8px;color:var(--mute);font-size:13px}}
.times{{font:600 26px/1 Fraunces,Georgia,serif;font-variant-numeric:tabular-nums;display:flex;align-items:baseline;gap:8px}}.arrow{{color:var(--mute);font-size:18px}}
.chips{{display:flex;flex-wrap:wrap;gap:4px}}
.chip{{display:inline-block;color:#fff;font-weight:700;font-size:12px;padding:2px 8px;border-radius:6px;background:var(--rail)}}
.chip.u{{background:var(--u)}}.chip.s{{background:var(--s);border-radius:10px}}.chip.bus{{background:var(--bus)}}.chip.tram{{background:var(--tram)}}.chip.demand{{background:#0f766e}}
.tl .demand .dot:after{{background:#0f766e!important}}
.st{{font-size:12px;font-weight:700;padding:3px 10px;border-radius:99px;white-space:nowrap}}
.st.ok{{color:var(--ok);background:var(--okb)}}.st.warn{{color:var(--warn);background:var(--warnb)}}.st.bad{{color:var(--bad);background:var(--badb)}}.st.mute{{color:var(--mute)}}
.tl{{list-style:none;margin:0;padding:4px 18px 16px;border-top:1px solid var(--line)}}
.tl li{{display:grid;grid-template-columns:62px 14px 1fr;gap:10px;position:relative;padding:8px 0 0}}
.tl .t{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}.tl s{{color:var(--mute);font-weight:400;font-size:12px}}
.tl .dot{{position:relative}}.tl .dot:before{{content:"";position:absolute;left:3px;top:6px;width:8px;height:8px;border-radius:50%;background:var(--ink)}}
.tl .ride:not(.end) .dot:after{{content:"";position:absolute;left:6px;top:14px;bottom:-14px;width:3px;background:var(--rail)}}
.tl .u .dot:after{{background:var(--u)!important}}.tl .s .dot:after{{background:var(--s)!important}}.tl .bus .dot:after{{background:var(--bus)!important}}.tl .tram .dot:after{{background:var(--tram)!important}}
.tl .walk .dot:before{{background:none;border-left:2px dotted var(--mute);border-radius:0;width:0;height:20px;left:6px;top:0}}
.tl .walk .w{{color:var(--mute);font-size:13px}}
.stop{{font-weight:600;margin-top:2px}}.dir{{color:var(--mute);font-size:13px}}
.tags{{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}}.tag{{font-style:normal;font-size:12px;padding:1px 7px;border-radius:6px;background:var(--soft);color:var(--mute)}}
.tag.warn{{background:var(--warnb);color:var(--warn)}}.tag.bad{{background:var(--badb);color:var(--bad)}}b.bad{{color:var(--bad)}}
.note{{margin:6px 0 0;font-size:13px;color:var(--warn)}}.empty,footer{{color:var(--mute);font-size:12.5px}}footer{{margin:22px 4px 0;text-align:center}}footer a{{color:inherit}}
.rf{{display:inline-block;margin-top:10px;padding:4px 10px;border-radius:99px;background:rgba(255,255,255,.14);font-size:12px}}
@media (prefers-reduced-motion:reduce){{*{{animation:none!important}}}}
</style></head><body>
<header class="top"><div>{hero}<p class="meta">{s["date"]:%a %d %b} · {s["route"]} · trips leaving {win} · live RMV data as of {T(s["at"])}</p><span class="rf" id="rf">updates every 2 min</span></div></header>
<main>{cards}
<footer>Tap a trip for every train, platform and walk. Times include walking from your door.<br><a href="brief/">Morning brief →</a></footer>
</main><script>
// reload with a fresh URL so neither the browser nor GitHub's cache hands back an old copy
let n=120;const rf=document.getElementById('rf');setInterval(()=>{{n--;rf.textContent=n>0?`refreshing in ${{n}} s`:'refreshing…';if(n<=0)location.replace(location.pathname+'?v='+Date.now())}},1000);
</script></body></html>"""


def publish(html, path="index.html", extra=None):
    # gh-pages holds the live page and the morning brief: update one file, keep the rest, and keep a single commit
    # (so nothing old lingers in a public history). --force-with-lease makes a push that raced another workflow fail and retry.
    remote = E("GH_REMOTE")
    if not remote:
        out = "commute.html" if path == "index.html" else path.replace("/", "_")
        open(out, "w").write(html); print("wrote", out); return  # local runs: just the page
    for attempt in range(3):
        with tempfile.TemporaryDirectory() as d:
            git = lambda *a: subprocess.run(["git", *a], cwd=d, check=True, capture_output=True, text=True)
            have = subprocess.run(["git", "clone", "-q", "--depth", "1", "-b", "gh-pages", remote, d], capture_output=True).returncode == 0
            if have:
                head = git("rev-parse", "HEAD").stdout.strip()
            else:
                git("init", "-q", "-b", "gh-pages")
            for name, body in {path: html, **(extra or {})}.items():
                os.makedirs(os.path.dirname(f"{d}/{name}"), exist_ok=True)
                open(f"{d}/{name}", "wb" if isinstance(body, bytes) else "w").write(body)
            open(f"{d}/.nojekyll", "w").close()
            if have and not git("status", "--porcelain").stdout.strip():
                return
            git("checkout", "-q", "--orphan", "fresh"); git("add", "-A"); git("commit", "-qm", f"update {path}")
            try:
                git("push", "-q", *(["--force-with-lease=gh-pages:" + head] if have else ["-f"]), remote, "fresh:gh-pages"); return
            except subprocess.CalledProcessError:  # the other workflow pushed first; start over from its version
                if attempt == 2:
                    raise


def notify(s, new=()):
    rec, loud = s["rec"], bool(new)
    if new:
        title = "⚠ " + ", ".join(f"{n} {T(t)} {w}" for n, t, w in sorted(new, key=lambda i: i[1]))
    elif s["by"]:
        title = f"Leave {T(rec['leave'])} → arrive {T(rec['arr'])}" if rec else f"No clean option for {T(s['by'])}"
    else:
        title = f"{s['route']}: leave {T(rec['leave'])} → arrive {T(rec['arr'])}" if rec else f"{s['route']}: no clean trip in the next hour"
    lines = []
    for m in [m for m in s["opts"] if not m["gone"]][:4]:
        flag = "✓" if m["ok"] else "⚠ " + (m["issues"][0][0] + " " + m["issues"][0][2] if m["issues"] else "late")
        lines.append(f"{T(m['leave'])} → {T(m['arr'])} · {' '.join(r['name'] for r in m['rides'])} {flag}")
    msg = {"topic": E("NTFY_TOPIC"), "title": title, "message": "\n".join(lines) or "No connections.",
           "priority": 4 if loud else 3, "tags": ["warning" if loud else "train"]}
    if E("PAGE_URL"):  # a fresh URL each time so the phone can't show a cached copy of the page
        url = f"{E('PAGE_URL')}?v={now():%Y%m%d%H%M}"
        msg |= {"click": url, "actions": [{"action": "view", "label": "Details", "url": url}]}
    print(title, *lines, sep="\n")
    if E("NTFY_TOPIC"):
        get("https://ntfy.sh", tries=5, data=json.dumps(msg).encode(), method="POST", headers={"Content-Type": "application/json"})


def go_ping(s, go):
    # "time to go": the first clean trip from your usual departure, about ten minutes before you need to leave
    skipped = [m for m in s["opts"] if not m["gone"] and m["leave"] < go["leave"] and m["issues"]]
    lines = [" · ".join(f"{r['name']} {T(r['dep'])}" + (f" pl. {r['track']}" if r["track"] else "") for r in go["rides"])]
    lines += [f"Skipping {T(m['leave'])}: {m['issues'][0][0]} {m['issues'][0][2]}" for m in skipped[:2]]
    msg = {"topic": E("NTFY_TOPIC"), "title": f"🚶 Time to go: leave {T(go['leave'])} → arrive {T(go['arr'])}",
           "message": "\n".join(lines), "priority": 4, "tags": ["walking"]}
    if E("PAGE_URL"):
        msg["click"] = f"{E('PAGE_URL')}?v={now():%Y%m%d%H%M}"
    print(msg["title"], *lines, sep="\n")
    if E("NTFY_TOPIC"):
        get("https://ntfy.sh", tries=5, data=json.dumps(msg).encode(), method="POST", headers={"Content-Type": "application/json"})


def sig(s):
    # problems on trips still ahead; a delay counts once, not per extra minute
    return frozenset(i[:2] + ("delayed" if i[2].startswith("+") else i[2],) for m in s["opts"] if not m["gone"] for i in m["issues"])


def session():
    # (back, from, to) for the session that is under way or about to start, or None. Decided from the actual time because
    # GitHub's scheduler can be hours late and fires both DST variants of a cron; extra runs just find no session and exit.
    n = now()
    if n.weekday() > 4:
        return None
    for back, (f, t) in ((False, AM), (True, PM)):
        if hm(n.date(), f) - timedelta(minutes=60) <= n <= hm(n.date(), t):
            return back, f, t


def watch():
    if E("FORCE") == "true":
        s = snapshot(now().hour >= 12, live=True)
        publish(render(s)); notify(s); return
    w = session()
    if not w:
        print("not a session start", now()); return
    if holiday(now().date()):
        print("public holiday:", holiday(now().date())); return
    back, f, t = w
    slot, end = max(hm(now().date(), f), now()), hm(now().date(), t)
    hour, seen, last_html, pub, pinged = None, None, None, datetime.min, datetime.min
    go_at, gone_off = (GO_PM if back else GO_AM), False
    while slot <= end:
        time.sleep(max(0, (slot - now()).total_seconds()))
        try:
            s = snapshot(back, live=True)
            k = sig(s)
            new = k - seen if seen is not None else frozenset()
            # hourly status, but not within 30 min of the last ping (a late start just before the hour)
            hourly = slot.hour != hour and slot - pinged >= timedelta(minutes=30)
            if go_at and not gone_off:
                t0 = hm(slot.date(), go_at)
                go = next((m for m in s["opts"] if m["ok"] and not m["gone"] and m["leave"] >= t0), None)
                if go and now() >= t0 - timedelta(minutes=30) and go["leave"] - now() <= timedelta(minutes=12):
                    go_ping(s, go); gone_off, hourly = True, False  # not a status ping on top of it in the same check
            if new or hourly:  # or straight away when a new problem shows up
                notify(s, new); pinged = slot
            hour, seen = slot.hour, k
            html = render(s)
            # Pages allows ~10 builds an hour, so only republish every 10 min unless a problem appeared
            if re.sub(r"as of \d\d:\d\d", "", html) != re.sub(r"as of \d\d:\d\d", "", last_html or "") and (new or now() - pub >= timedelta(minutes=10)):
                publish(html); last_html, pub = html, now()
        except Exception as e:  # a hiccup at RMV, ntfy or GitHub shouldn't end the whole session
            print(f"{now():%H:%M} check failed: {type(e).__name__}: {e}")
        n = (now() + timedelta(minutes=STEP)).replace(second=0, microsecond=0)
        slot = n - timedelta(minutes=n.minute % STEP)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--check" in a:
        for k in ("HOME_ADDR", "WORK_ADDR"):
            print(k, "=", E(k))
            print("   ", place(E(k))[1]) if "," in E(k) and re.search(r"\d\.\d", E(k).split(",")[0]) else [print("   ", p["name"]) for p in lookup(E(k), 3)]
        s = snapshot()
        publish(render(s)); notify(s) if "--send" in a else None
    elif "--watch" in a:
        watch()
    else:
        s = snapshot("--back" in a, "--live" in a); publish(render(s))
        for m in s["opts"]:
            print(T(m["leave"]), "→", T(m["arr"]), " ".join(r["name"] for r in m["rides"]), m["issues"] or "")
