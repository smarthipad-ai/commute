import json, os, re, subprocess, sys, tempfile, time
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API = "https://www.rmv.de/hapi"
TZ = ZoneInfo("Europe/Berlin")
E = os.environ.get
LEAVE_FROM, LEAVE_TO, ARRIVE_BY = E("LEAVE_FROM", "07:30"), E("LEAVE_TO", "08:00"), E("ARRIVE_BY", "08:30")
LATE, EVERY = 5, 420


def now():
    return datetime.now(TZ).replace(tzinfo=None)


def get(url, **kw):
    with urlopen(Request(url, **kw), timeout=30) as r:
        return r.read()


def hapi(ep, **p):
    return json.loads(get(f"{API}/{ep}?" + urlencode({"accessId": E("RMV_KEY"), "format": "json", **p})))


def lookup(q, n=1):
    out = []
    for x in hapi("location.name", input=q, type="ALL", maxNo=n).get("stopLocationOrCoordLocation", []):
        out += [x[k] for k in ("StopLocation", "CoordLocation") if k in x]
    return out


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
    legs = []
    for l in t["LegList"]["Leg"]:
        o, d = l["Origin"], l["Destination"]
        if l.get("type") == "JNY":
            name = " ".join((l.get("name") or "").split())
            msgs = [m.get("head", "").strip() for m in (l.get("Messages") or {}).get("Message", [])]
            legs.append(dict(ride=True, name=name, kind=kind(name), dir=l.get("direction", ""),
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
    w0 = legs[0]["mins"] if not legs[0]["ride"] else 0
    w1 = legs[-1]["mins"] if not legs[-1]["ride"] else 0
    for r in rides:
        r["delay"] = round((r["dep"] - r["pdep"]).total_seconds() / 60)
    leave = rides[0]["pdep"] - timedelta(minutes=w0)
    arr = rides[-1]["arr"] + timedelta(minutes=w1)
    issues = []
    for r in rides:
        if r["cancelled"]:
            issues.append((r["name"], r["pdep"], "cancelled"))
        elif r["risk"]:
            issues.append((r["name"], r["pdep"], "connection at risk"))
        elif r["delay"] >= LATE:
            issues.append((r["name"], r["pdep"], f"+{r['delay']} min"))
    return dict(legs=legs, rides=rides, leave=leave, arr=arr, issues=issues)


def day():
    n = now()
    d = n.date()
    if n.time() > datetime.strptime(LEAVE_TO, "%H:%M").time() or d.weekday() > 4:
        d += timedelta(days=1)
        while d.weekday() > 4:
            d += timedelta(days=1)
    return d


def trips(o, d, dt):
    lf, lt = (datetime.combine(dt, datetime.strptime(x, "%H:%M").time()) for x in (LEAVE_FROM, LEAVE_TO))
    p = {**{"origin" + k: v for k, v in o.items()}, **{"dest" + k: v for k, v in d.items()},
         "date": f"{dt:%Y-%m-%d}", "time": (lf - timedelta(minutes=20)).strftime("%H:%M"), "numF": 6}
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
    by = datetime.combine(dt, datetime.strptime(ARRIVE_BY, "%H:%M").time())
    for m in out:
        m["late"] = m["arr"] > by
        m["spare"] = round((by - m["arr"]).total_seconds() / 60)
        m["gone"] = m["leave"] < now()
        m["ok"] = not m["issues"] and not m["late"]
    out.sort(key=lambda m: (m["leave"], m["arr"]))
    live = [m for m in out if not m["gone"]]
    good = [m for m in live if m["ok"]]
    rec = good[-1] if good else None
    for m in out:
        m["rec"] = m is rec
    return out, rec


def snapshot():
    (o, on), (d, dn) = place(E("HOME_ADDR")), place(E("WORK_ADDR"))
    dt = day()
    opts, rec = trips(o, d, dt)
    return dict(date=dt, opts=opts, rec=rec, at=now(), home=on, work=dn)


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
        rows.append(
            f'<li class="ride {l["kind"]}"><span class="t">{dep}</span><span class="dot"></span>'
            f'<div>{chip(l)} <span class="dir">→ {escape(short(l["dir"]))}</span><div class="stop">{escape(short(l["frm"]))}</div>'
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
    return f'<span class="st ok">{m["spare"]} min spare</span>'


def card(m):
    dur = round((m["arr"] - m["leave"]).total_seconds() / 60)
    cls = "card" + (" rec" if m["rec"] else "") + (" gone" if m["gone"] else "") + ("" if m["ok"] else " issue")
    badge = '<div class="pick">Leave by this one</div>' if m["rec"] else ""
    return (f'<details class="{cls}"{" open" if m["rec"] else ""}><summary>{badge}<div class="row">'
            f'<div class="times"><b>{T(m["leave"])}</b><span class="arrow">→</span><b>{T(m["arr"])}</b></div>{status(m)}</div>'
            f'<div class="row sub"><span class="chips">{"".join(chip(r) for r in m["rides"])}</span><span>{dur} min</span></div></summary>'
            f'{timeline(m)}</details>')


def render(s):
    rec, by = s["rec"], ARRIVE_BY
    if rec:
        hero = (f'<p class="eyebrow">Leave home by</p><h1>{T(rec["leave"])}</h1>'
                f'<p class="lead">Arrive {T(rec["arr"])} · {rec["spare"]} min before {by}</p>')
    else:
        hero = f'<p class="eyebrow">Heads up</p><h1 class="bad">No clean option</h1><p class="lead">Nothing between {LEAVE_FROM} and {LEAVE_TO} gets you there by {by} without a problem. Check the list.</p>'
    cards = "".join(map(card, s["opts"])) or '<p class="empty">RMV returned no connections.</p>'
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="120">
<title>Commute</title><style>
:root{{--bg:#f4f2ee;--card:#fff;--ink:#1c1b19;--mute:#77736b;--line:#e4e0d8;--ok:#1f7a4d;--okb:#e3f3ea;--warn:#a15c00;--warnb:#fdf0dc;--bad:#b42318;--badb:#fde8e6;--acc:#1c1b19;
--u:#1b64b0;--s:#2f8f3a;--bus:#8b3a8f;--tram:#c4322a;--rail:#5b5b5b}}
@media (prefers-color-scheme:dark){{:root{{--bg:#141413;--card:#1f1e1c;--ink:#f0ede6;--mute:#9a958b;--line:#33312d;--okb:#163626;--ok:#5fd39a;--warnb:#3a2a10;--warn:#f0b54d;--badb:#3d1714;--bad:#ff8a7e;--acc:#f0ede6}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,"Segoe UI",Roboto,sans-serif}}
main{{max-width:560px;margin:0 auto;padding:28px 16px 40px}}
.eyebrow{{margin:0;color:var(--mute);font-size:13px;letter-spacing:.06em;text-transform:uppercase}}
h1{{margin:2px 0 4px;font-size:64px;line-height:1;font-weight:700;letter-spacing:-.03em;font-variant-numeric:tabular-nums}}
.lead{{margin:0 0 6px;font-size:17px}}.meta{{margin:0 0 22px;color:var(--mute);font-size:13px}}
h2{{font-size:13px;color:var(--mute);text-transform:uppercase;letter-spacing:.06em;margin:0 0 10px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:0 0 10px;overflow:hidden}}
.card.rec{{border:2px solid var(--acc)}}.card.gone{{opacity:.45}}
summary{{list-style:none;cursor:pointer;padding:14px 16px}}summary::-webkit-details-marker{{display:none}}
.pick{{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}}
.row{{display:flex;align-items:center;justify-content:space-between;gap:10px}}.sub{{margin-top:8px;color:var(--mute);font-size:13px}}
.times{{font-size:24px;font-variant-numeric:tabular-nums;display:flex;align-items:baseline;gap:8px}}.arrow{{color:var(--mute);font-size:18px}}
.chips{{display:flex;flex-wrap:wrap;gap:4px}}
.chip{{display:inline-block;color:#fff;font-weight:700;font-size:12px;padding:2px 7px;border-radius:5px;background:var(--rail)}}
.chip.u{{background:var(--u)}}.chip.s{{background:var(--s);border-radius:10px}}.chip.bus{{background:var(--bus)}}.chip.tram{{background:var(--tram)}}
.st{{font-size:13px;font-weight:600;padding:3px 9px;border-radius:99px;white-space:nowrap}}
.st.ok{{color:var(--ok);background:var(--okb)}}.st.warn{{color:var(--warn);background:var(--warnb)}}.st.bad{{color:var(--bad);background:var(--badb)}}.st.mute{{color:var(--mute)}}
.tl{{list-style:none;margin:0;padding:4px 16px 16px;border-top:1px solid var(--line)}}
.tl li{{display:grid;grid-template-columns:62px 14px 1fr;gap:10px;position:relative;padding:8px 0 0}}
.tl .t{{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}}.tl s{{color:var(--mute);font-weight:400;font-size:12px}}
.tl .dot{{position:relative}}.tl .dot:before{{content:"";position:absolute;left:3px;top:6px;width:8px;height:8px;border-radius:50%;background:var(--ink)}}
.tl .ride:not(.end) .dot:after{{content:"";position:absolute;left:6px;top:14px;bottom:-14px;width:3px;background:var(--rail)}}
.tl .u .dot:after{{background:var(--u)!important}}.tl .s .dot:after{{background:var(--s)!important}}.tl .bus .dot:after{{background:var(--bus)!important}}.tl .tram .dot:after{{background:var(--tram)!important}}
.tl .walk .dot:before{{background:none;border-left:2px dotted var(--mute);border-radius:0;width:0;height:20px;left:6px;top:0}}
.tl .walk .w{{color:var(--mute);font-size:13px}}
.stop{{font-weight:600;margin-top:2px}}.dir{{color:var(--mute);font-size:13px}}
.tags{{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}}.tag{{font-style:normal;font-size:12px;padding:1px 7px;border-radius:5px;background:var(--bg);color:var(--mute)}}
.tag.warn{{background:var(--warnb);color:var(--warn)}}.tag.bad{{background:var(--badb);color:var(--bad)}}b.bad,.bad{{color:var(--bad)}}
.note{{margin:6px 0 0;font-size:13px;color:var(--warn)}}.empty,footer{{color:var(--mute);font-size:13px}}footer{{margin-top:22px}}
</style></head><body><main>
{hero}<p class="meta">{s["date"]:%a %d %b} · Home → Haus 21 · live RMV data as of {T(s["at"])}</p>
<h2>Leaving {LEAVE_FROM}–{LEAVE_TO}</h2>{cards}
<footer>Tap a trip for every train, platform and walk. Times include walking from your door. Refreshes every 2 min.</footer>
</main></body></html>"""


def publish(html):
    remote = E("GH_REMOTE")
    if not remote:
        open("commute.html", "w").write(html); print("wrote commute.html"); return
    with tempfile.TemporaryDirectory() as d:
        open(f"{d}/index.html", "w").write(html); open(f"{d}/.nojekyll", "w").close()
        git = lambda *a: subprocess.run(["git", *a], cwd=d, check=True, capture_output=True)
        git("init", "-q", "-b", "gh-pages"); git("add", "."); git("commit", "-qm", "update"); git("push", "-qf", remote, "gh-pages")


def notify(s, loud):
    rec = s["rec"]
    title = f"Leave {T(rec['leave'])} → arrive {T(rec['arr'])}" if rec else f"No clean option for {ARRIVE_BY}"
    lines = []
    for m in [m for m in s["opts"] if not m["gone"]][:4]:
        flag = "✓" if m["ok"] else "⚠ " + (m["issues"][0][0] + " " + m["issues"][0][2] if m["issues"] else "late")
        lines.append(f"{T(m['leave'])} → {T(m['arr'])} · {' '.join(r['name'] for r in m['rides'])} {flag}")
    msg = {"topic": E("NTFY_TOPIC"), "title": title, "message": "\n".join(lines) or "No connections.",
           "priority": 4 if loud else 3, "tags": ["warning" if loud else "train"]}
    if E("PAGE_URL"):
        msg |= {"click": E("PAGE_URL"), "actions": [{"action": "view", "label": "Details", "url": E("PAGE_URL")}]}
    print(title, *lines, sep="\n")
    if E("NTFY_TOPIC"):
        get("https://ntfy.sh", data=json.dumps(msg).encode(), method="POST", headers={"Content-Type": "application/json"})


def sig(s):
    return (s["rec"] and s["rec"]["leave"], frozenset(i[:2] + (i[2].startswith("+"),) for m in s["opts"] if not m["gone"] for i in m["issues"]))


def watch():
    force = E("FORCE") == "true"
    t = now().strftime("%H:%M")
    if not force and not ("06:30" <= t <= "07:35"):
        print("outside start window", t); return
    end = datetime.combine(now().date(), datetime.strptime(LEAVE_TO, "%H:%M").time())
    last_sig, last_html = None, None
    while True:
        s = snapshot()
        html = render(s)
        if html.split("live RMV data")[0] != (last_html or "").split("live RMV data")[0]:
            publish(html); last_html = html
        k = sig(s)
        if k != last_sig:
            notify(s, loud=last_sig is not None and (not s["rec"] or k[1] - (last_sig[1] if last_sig else frozenset())))
            last_sig = k
        if force or now() + timedelta(seconds=EVERY) > end:
            break
        time.sleep(EVERY)


if __name__ == "__main__":
    a = sys.argv[1:]
    if "--check" in a:
        for k in ("HOME_ADDR", "WORK_ADDR"):
            print(k, "=", E(k))
            print("   ", place(E(k))[1]) if "," in E(k) and re.search(r"\d\.\d", E(k).split(",")[0]) else [print("   ", p["name"]) for p in lookup(E(k), 3)]
        s = snapshot()
        publish(render(s)); notify(s, False) if "--send" in a else None
    elif "--watch" in a:
        watch()
    else:
        s = snapshot(); publish(render(s))
        for m in s["opts"]:
            print(T(m["leave"]), "→", T(m["arr"]), " ".join(r["name"] for r in m["rides"]), m["issues"] or "")
