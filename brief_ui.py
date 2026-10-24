"""HTML for the brief page: a photo hero with live weather effects, then one card per section.

brief.py builds the sections; each has a `kind` and structured `data`. To give a new
kind its own look, add a function to RENDER below (and a slot in ORDER).
"""
import math
from datetime import datetime, timedelta
from html import escape


def e(x):
    return escape(str(x), quote=True)


def link(u):
    return e(u) if str(u).startswith(("https://", "http://")) else "#"


def icon(code):
    return ("☀️" if code <= 1 else "⛅" if code == 2 else "☁️" if code <= 48 else "🌦" if code <= 57
            else "🌧" if code <= 67 or 80 <= code <= 82 else "🌨" if code <= 86 else "⛈")


def fx_kind(code):
    return ("rain" if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99) else
            "snow" if code in (71, 73, 75, 77, 85, 86) else "fog" if code in (45, 48) else "sun" if code <= 1 else "cloud")


def hm(iso):
    return iso[11:16]


def smooth(pts):
    d = f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        mx = (x0 + x1) / 2
        d += f" C{mx:.1f},{y0:.1f} {mx:.1f},{y1:.1f} {x1:.1f},{y1:.1f}"
    return d


# --- graphics ---------------------------------------------------------------

def weather_chart(slots):
    # temperature curve with rain-chance bars underneath and a weather icon every three hours
    if len(slots) < 2:
        return ""
    W, H, L, R, top, B = 560, 214, 22, 22, 56, 32
    base, n = H - B, len(slots)
    xs = [L + (W - L - R) * i / (n - 1) for i in range(n)]
    temps = [s[1] for s in slots]
    lo, hi = min(temps), max(temps)
    span, floor = max(hi - lo, 6.0), base - 56
    ys = [top + (floor - top) * (1 - (t - lo) / span) for t in temps]
    line = smooth(list(zip(xs, ys)))
    area = f"{line} L{xs[-1]:.1f},{base} L{xs[0]:.1f},{base} Z"
    imax, imin = temps.index(hi), temps.index(lo)
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="Temperature and rain chance by hour">',
           '<defs><linearGradient id="ag" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--sun);stop-opacity:.38"/>'
           '<stop offset="1" style="stop-color:var(--sun);stop-opacity:0"/></linearGradient></defs>',
           f'<line x1="{L}" x2="{W - R}" y1="{base}" y2="{base}" class="axis"/>']
    for i, (iso, t, p, code) in enumerate(slots):
        h = p / 100 * 46
        if p >= 5:
            out.append(f'<rect class="bar rainbar" style="--k:{i}" x="{xs[i] - 7:.1f}" y="{base - h:.1f}" width="14" height="{h:.1f}" rx="4"/>')
        if p >= 30:
            out.append(f'<text class="pct" x="{xs[i]:.1f}" y="{base - h - 5:.1f}" text-anchor="middle">{p}%</text>')
    out.append(f'<path class="fade area" d="{area}"/><path class="draw tline" pathLength="1" d="{line}"/>')
    for i, (iso, t, p, code) in enumerate(slots):
        labelled = i % 3 == 0 or i in (imax, imin)
        if labelled:
            out.append(f'<circle class="fade dot" cx="{xs[i]:.1f}" cy="{ys[i]:.1f}" r="4.5"/>'
                       f'<text class="fade tlabel" x="{xs[i]:.1f}" y="{ys[i] - 11:.1f}" text-anchor="middle">{round(t)}°</text>')
        if i % 3 == 0:
            out.append(f'<text class="fade emo" x="{xs[i]:.1f}" y="26" text-anchor="middle">{icon(code)}</text>')
        if i % 2 == 0:
            out.append(f'<text class="hlabel" x="{xs[i]:.1f}" y="{H - 8}" text-anchor="middle">{hm(iso)[:2]}</text>')
    return "".join(out) + "</svg>"


def sun_arc(rise, sett, now):
    # half-circle from sunrise to sunset with the sun at its current position (or midday when there is no "now")
    cx, cy, r = 150, 122, 112
    t = 0.5 if now is None else min(max((now - rise).total_seconds() / (sett - rise).total_seconds(), 0), 1)
    x, y = cx - r * math.cos(math.pi * t), cy - r * math.sin(math.pi * t)
    arc = f"M{cx - r},{cy} A{r},{r} 0 0 1 {cx + r},{cy}"
    prog = f"M{cx - r},{cy} A{r},{r} 0 0 1 {x:.1f},{y:.1f}"
    night = now is not None and (now < rise or now > sett)
    return (f'<svg class="sunarc" viewBox="0 0 300 150" role="img" aria-label="Sunrise {rise:%H:%M}, sunset {sett:%H:%M}">'
            '<defs><linearGradient id="sg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--sun);stop-opacity:.22"/>'
            '<stop offset="1" style="stop-color:var(--sun);stop-opacity:0"/></linearGradient></defs>'
            f'<path d="{arc} Z" fill="url(#sg)"/><path d="{arc}" class="track"/>'
            + (f'<path d="{prog}" class="draw prog" pathLength="1"/>' if now is not None and 0 < t else "")
            + f'<line x1="14" x2="286" y1="{cy}" y2="{cy}" class="axis"/>'
            f'<g class="fade sunpos{" night" if night else ""}" style="--t:{t:.3f}"><circle class="halo" cx="{x:.1f}" cy="{y:.1f}" r="15"/>'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8.5" class="sun"/></g>'
            f'<text x="{cx - r}" y="{cy + 18}" text-anchor="middle" class="hlabel">{rise:%H:%M}</text>'
            f'<text x="{cx + r}" y="{cy + 18}" text-anchor="middle" class="hlabel">{sett:%H:%M}</text></svg>')


def moon_svg(f):
    # f: 0 = new, 0.5 = full. The lit part is a half-disc plus an elliptical terminator.
    r, cx, cy = 26, 32, 32
    k = math.cos(2 * math.pi * f)
    rx = abs(k) * r
    if f < 0.5:  # waxing: lit on the right
        d = f"M{cx},{cy - r} A{r},{r} 0 0 1 {cx},{cy + r} A{rx:.2f},{r} 0 0 {0 if k > 0 else 1} {cx},{cy - r} Z"
    else:  # waning: lit on the left
        d = f"M{cx},{cy - r} A{r},{r} 0 0 0 {cx},{cy + r} A{rx:.2f},{r} 0 0 {1 if k > 0 else 0} {cx},{cy - r} Z"
    return (f'<svg class="moon" viewBox="0 0 64 64" role="img"><circle cx="{cx}" cy="{cy}" r="{r}" class="dark"/>'
            f'<path d="{d}" class="lit"/><circle cx="{cx}" cy="{cy}" r="{r}" class="rim"/></svg>')


def spark(vals, w=84, h=28):
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = [(2 + (w - 4) * i / (len(vals) - 1), 3 + (h - 6) * (1 - (v - lo) / span)) for i, v in enumerate(vals)]
    up = vals[-1] >= vals[0]
    return (f'<svg class="spark {"up" if up else "down"}" viewBox="0 0 {w} {h}"><path class="draw" pathLength="1" d="{smooth(pts)}"/>'
            f'<circle class="fade" cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="2.6"/></svg>')


def bin_svg(color, k):
    return (f'<svg class="binsvg" viewBox="0 0 40 48" style="--c:{e(color)};--k:{k}"><rect x="6" y="14" width="28" height="30" rx="4" class="body"/>'
            '<g class="lid"><rect x="3" y="8" width="34" height="6" rx="3"/><rect x="15" y="3" width="10" height="5" rx="2"/></g>'
            '<path d="M13 20v18M20 20v18M27 20v18" class="ribs"/></svg>')


def occ_dots(n):
    filled = max(0, min(4, n - 10)) if n else 0
    return f'<span class="occ" title="{filled}/4 full">' + "".join(f'<i class="{"on" if i < filled else ""}"></i>' for i in range(4)) + "</span>"


# --- card bodies ------------------------------------------------------------

def r_text(s, ctx):
    return "".join(f"<p>{e(x)}</p>" for x in s.lines)


def r_alert(s, ctx):
    return "".join(f'<p class="alertline">{e(x)}</p>' for x in s.lines)


def r_weather(s, ctx):
    d = s.data
    now_line = f'<p class="muted">{e(s.lines[0])}</p>' if d["now"] else ""
    uv = f'<span class="pill">UV {round(d["uv"])}</span>' if d.get("uv") else ""
    return (f'<p class="lead">{e(d["sentence"])}</p>{now_line}{weather_chart(d["slots"])}'
            f'<p class="legend"><span><i class="lg line"></i>Temperature</span><span><i class="lg rain"></i>Rain chance</span>{uv}</p>')


def r_sky(s, ctx):
    d = s.data
    rise, sett = datetime.fromisoformat(d["rise"]), datetime.fromisoformat(d["set"])
    now = datetime.fromisoformat(d["now"]) if d.get("now") else None
    m = d["moon"]
    h, mi = divmod(d["minutes"], 60)
    delta = ""
    if d.get("delta"):
        delta = f'<p class="muted">{"Days are getting " + ("longer" if d["delta"] > 0 else "shorter")}: {d["delta"]:+d} min tomorrow</p>'
    full, new = (datetime.fromisoformat(m[k]).date() for k in ("full", "new"))
    nxt = f"Full moon {full:%a %d %b}" if (full - ctx["today"]).days <= (new - ctx["today"]).days else f"New moon {new:%a %d %b}"
    clock = "".join(f'<p class="pill warnpill">{e(x)}</p>' for x in d["clock"])
    return (f'<div class="skygrid"><div>{sun_arc(rise, sett, now)}<p class="center"><b>{h} h {mi:02d} min</b> of daylight</p>{delta}</div>'
            f'<div class="moonbox">{moon_svg(m["f"])}<b>{e(m["name"])}</b><span class="muted">{m["illum"]}% lit<br>{e(nxt)}</span></div></div>{clock}')


def r_train(s, ctx):
    d, rows = s.data, []
    for ti, t in enumerate(d["trips"]):
        total = sum(g["mins"] for g in t["segs"]) or 1
        segs = []
        for k, g in enumerate(t["segs"]):
            label = (g.get("name", "") if g["kind"] not in ("walk", "wait") and g["mins"] / total >= .14 else
                     "🚶" if g["kind"] == "walk" and g["mins"] / total >= .09 else "")
            segs.append(f'<i class="seg {g["kind"]}" style="flex:{g["mins"]};--k:{k}" title="{e(g.get("name") or g["kind"])} {g["mins"]} min"><em>{e(label)}</em></i>')
        rides = "".join(
            f'<li><span class="chip {r["kind"]}">{e(r["name"])}</span> <b>{r["dep"]}</b>'
            + (f' <span class="muted">pl. {e(r["track"])}</span>' if r["track"] else "")
            + (f' <span class="delay">+{r["delay"]} min</span>' if r["delay"] >= 1 else "")
            + (f' {occ_dots(r["occ"])}<span class="muted occl">{d["occ"].get(r["occ"], "")}</span>' if r["occ"] in d["occ"] else "") + "</li>" for r in t["rides"])
        status = f'<span class="st bad">{e(t["issue"])}</span>' if t["issue"] else '<span class="st ok">on time</span>'
        badge = f'<span class="badge">{e(t["tag"])}</span>' if t["tag"] else ('<span class="badge good">Best pick</span>' if t["rec"] else "")
        rows.append(f'<div class="trip{" rec" if t["rec"] else ""}"><div class="trow"><b>{hm(t["leave"])}</b><span class="dur">{t["minutes"]} min</span>'
                    f'<b>{hm(t["arr"])}</b></div><div class="bar">{"".join(segs)}</div>'
                    f'<div class="tmeta"><ul class="rides">{rides}</ul><div class="tright">{badge}{status}</div></div></div>')
    return "".join(rows)


def r_rainhome(s, ctx):
    d = s.data
    bars = "".join(f'<div class="rb" style="--k:{i}"><i class="bar" style="--h:{max(p, 3)}%;--k:{i}"></i><b>{p}%</b><span>{hm(iso)[:2]}h</span></div>'
                   for i, (iso, p, tp) in enumerate(d["slots"]))
    return f'<p class="lead">{e(s.lines[0])}</p><div class="rainbars">{bars}</div>'


def r_radar(s, ctx):
    d = s.data
    return (f'<div class="map" id="radar" data-lat="{d["lat"]}" data-lon="{d["lon"]}"><div class="shimmer"></div></div>'
            '<p class="legend"><span class="muted">Live rain radar, past two hours · tap to play or pause</span></p>')


def r_calendar(s, ctx):
    d = s.data
    warn = f'<p class="banner">⚠ {e(d["warn"])}</p>' if d["warn"] else ""
    allday = "".join(f'<span class="pill">{e(x)}</span> ' for x in d["allday"])
    evs = "".join(f'<li><b>{a}</b><span class="muted">{b}</span><p>{e(t)}</p></li>' for a, b, t in d["events"])
    return f'{warn}{allday}<ul class="timeline">{evs}</ul>'


def r_bins(s, ctx):
    d = s.data
    cells = "".join(f'<div class="bincell">{bin_svg(c, i)}<span>{e(n)}</span></div>' for i, (n, c) in enumerate(d["names"]))
    return f'<p class="lead">{"Put out tonight" if d["evening"] else "Collected today"}</p><div class="bins">{cells}</div>'


def r_notes(s, ctx):
    return '<ul class="notes">' + "".join(f'<li><span>{i}</span>{e(t)}</li>' for i, t in s.data["items"]) + "</ul>"


def ago(iso, now):
    m = round((now - datetime.fromisoformat(iso)).total_seconds() / 60)
    return f"{m} min ago" if m < 90 else f"{round(m / 60)} h ago"


def r_news(s, ctx):
    def group(title, items):
        if not items:
            return ""
        lis = "".join(f'<li><a href="{link(x["url"])}" target="_blank" rel="noopener"><span class="nt">{e(x["title"])}</span>'
                      f'<span class="muted">{e(x["topline"] + " · " if x["topline"] else "")}{ago(x["time"], ctx["now"]) if x["time"] else ""}</span></a></li>' for x in items)
        return f'<h3>{title}</h3><ul class="news">{lis}</ul>'
    d = s.data
    return group("Germany", d["national"]) + group("Hessen", d["hessen"]) + '<p class="src">tagesschau.de · hessenschau.de</p>'


def r_history(s, ctx):
    d = s.data
    more = f' <a href="{link(d["url"])}" target="_blank" rel="noopener">Read more →</a>' if d.get("url") else ""
    return f'<div class="year">{e(d["year"])}</div><p class="lead">{e(d["text"])}{more}</p>'


def r_article(s, ctx):
    d = s.data
    img = f'<img src="{link(d["thumb"])}" alt="" loading="lazy">' if d.get("thumb") else ""
    return (f'<div class="article">{img}<div><h3>{e(d["title"])}</h3><p>{e(d["extract"])}</p>'
            f'<a href="{link(d["url"])}" target="_blank" rel="noopener">Read the article →</a></div></div>')


def r_word(s, ctx):
    d = s.data
    art = f'<span class="gender {e(d["art"])}">{e(d["art"])}</span>' if d["art"] else ""
    return (f'<div class="wordhead">{art}<span class="word{" long" if len(d["word"]) > 13 else ""}">{e(d["word"])}</span></div><p class="muted">{e(d["pos"])} · {e(d["meaning"])}</p>'
            f'<p class="example">“{e(d["example"])}”<br><span class="muted">{e(d["example_en"])}</span></p>')


def r_river(s, ctx):
    d = s.data
    pct = max(4, min(100, (d["level"] - d["lo"]) / (d["hi"] - d["lo"]) * 100))
    mark = (d["mark"] - d["lo"]) / (d["hi"] - d["lo"]) * 100
    arrow = "▲" if d["change"] > 2 else "▼" if d["change"] < -2 else "▶"
    return (f'<div class="gauge{" high" if d["high"] else ""}"><div class="fill" style="--w:{pct:.0f}%"></div><i class="mark" style="left:{mark:.0f}%"></i></div>'
            f'<div class="gaugelab"><span>{round(d["level"])} cm <small class="muted">{arrow} {d["change"]:+.0f} in 24 h</small></span>'
            f'<span>🌡 {d["temp"]:.1f}°C water</span></div>'
            + (f'<p class="banner">High water — river paths may be closed</p>' if d["high"] else "") +
            '<p class="src">Main at Frankfurt Osthafen · mark = shipping restrictions (300 cm) · pegelonline.wsv.de</p>')


def r_ticker(s, ctx):
    rows = []
    for x in s.data["rows"]:
        up = x["change"] >= 0
        rows.append(f'<li><span class="lab">{e(x["label"])}</span>{spark(x["spark"])}<span class="val">{e(x["value"])}'
                    f'<em class="{"up" if up else "down"}">{"▲" if up else "▼"} {abs(x["change"]):.2f}%</em></span></li>')
    return '<ul class="ticker">' + "".join(rows) + '</ul><p class="src">Not financial advice · ECB rates via Frankfurter · prices via Yahoo Finance</p>'


RENDER = {"alert": r_alert, "weather": r_weather, "sky": r_sky, "train": r_train, "rainhome": r_rainhome, "radar": r_radar,
          "calendar": r_calendar, "bins": r_bins, "notes": r_notes, "news": r_news, "history": r_history, "article": r_article,
          "word": r_word, "river": r_river, "ticker": r_ticker}
ORDER = ["alert", "weather", "train", "rainhome", "radar", "sky", "text", "calendar", "bins", "notes", "news", "history", "article", "word", "river", "ticker"]
SLIM = {"text"}


def card(s, i, ctx):
    if s.private:  # this page is public: personal sections stay in the notification
        n = len(s.lines)
        body = f'<p class="muted">🔒 {n} item{"s" * (n != 1)} — shown in your notification only, kept off this public page</p>'
        return f'<section class="card r slim private" style="--d:{i % 3}"><span class="ic">{s.icon}</span><div><h2>{e(s.title)}</h2>{body}</div></section>'
    body = RENDER.get(s.kind, r_text)(s, ctx)
    cls = f"card r {s.tone} k-{s.kind}"
    if s.kind in SLIM:
        return f'<section class="{cls} slim" style="--d:{i % 3}"><span class="ic">{s.icon}</span><div><h2>{e(s.title)}</h2>{body}</div></section>'
    return f'<section class="{cls}" style="--d:{i % 3}"><h2><span class="ic">{s.icon}</span>{e(s.title)}</h2>{body}</section>'


# --- home-screen app ---------------------------------------------------------

def png_icon(size):
    # a sunrise: night-to-dawn gradient with a sun on the horizon, drawn pixel by pixel (no image library needed)
    import struct, zlib
    rows = []
    for y in range(size):
        t = y / (size - 1)
        sky = [round(a + (b - a) * t) for a, b in zip((22, 34, 66), (245, 158, 96))]
        row = bytearray([0])
        for x in range(size):
            dx, dy = (x - size / 2) / size, (y - size * .72) / size
            r = (dx * dx + dy * dy) ** .5
            px = (255, 214, 120) if r < .19 and y < size * .78 else (250, 190, 100) if r < .25 and y < size * .78 else tuple(sky)
            if y >= size * .78:  # the ground
                px = (27, 36, 51)
            row += bytes(px)
        rows.append(bytes(row))
    chunk = lambda k, d: struct.pack(">I", len(d)) + k + d + struct.pack(">I", zlib.crc32(k + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def app_files():
    # lets you add the brief to your phone's home screen; it then opens full screen like an app
    import json
    manifest = dict(name="Morning brief", short_name="Brief", start_url="./", scope="./", display="standalone",
                    background_color="#1b2433", theme_color="#1b2433",
                    icons=[dict(src=f"icon-{n}.png", sizes=f"{n}x{n}", type="image/png", purpose="any maskable") for n in (192, 512)])
    return {"brief/manifest.webmanifest": json.dumps(manifest), "brief/icon-192.png": png_icon(192), "brief/icon-512.png": png_icon(512)}


# --- page -------------------------------------------------------------------

def page(secs, d, evening, ctx):
    pic, (q, who) = ctx["pic"], ctx["quote"]
    w = next((s for s in secs if s.kind == "weather"), None)
    tr = next((s for s in secs if s.kind == "train"), None)
    wh = next((s for s in secs if s.kind == "rainhome"), None)
    hour = ctx["now"].hour
    greet = (f"Tomorrow, {d:%A}" if evening else
             f"Good morning, {e(ctx['name'])}" if hour < 12 else f"Good afternoon, {e(ctx['name'])}" if hour < 18 else f"Good evening, {e(ctx['name'])}")
    chips = []
    if w:
        wd = w.data
        chips.append(f'<div class="gl temp fu" style="--d:3"><span class="em">{icon(wd["code"])}</span><div><b><i data-count="{round(wd["lo"])}">{round(wd["lo"])}</i>°'
                     f'<u>→</u><i data-count="{round(wd["hi"])}">{round(wd["hi"])}</i>°</b><small>{e(wd["desc"])}</small></div></div>')
    rec = tr.data["rec"] if tr and tr.data else None
    if rec:
        live = f' data-leave="{e(rec["leave"])}"' if tr.data["today"] and not evening else ""
        chips.append(f'<div class="gl leave fu" style="--d:4"{live}><small>Leave by</small><b>{hm(rec["leave"])}</b>'
                     f'<small>arrive {hm(rec["arr"])}<span class="cd"></span></small></div>')
    if wh:
        chips.append(f'<div class="gl fu" style="--d:5"><span class="em">{"☂️" if wh.data["wet"] else "🌤"}</span>'
                     f'<div><b class="small">{"Umbrella" if wh.data["wet"] else "Dry"}</b><small>on the way home</small></div></div>')
    kind = fx_kind(w.data["code"]) if w else "none"
    bg = f"background-image:url('{link(pic['url'])}')" if pic else "background-image:linear-gradient(160deg,#36506b,#c98b5e)"
    ordered = sorted(secs, key=lambda s: (0 if s.tone == "bad" else 1, ORDER.index(s.kind) if s.kind in ORDER else 99))
    cards = "".join(card(s, i, ctx) for i, s in enumerate(ordered))
    credit = (f'<p>Photo: <a href="{link(pic["page"])}">{e(pic["about"] or "Wikimedia Commons picture of the day")}</a> · '
              f'{e(pic["credit"])} · {e(pic["license"])}</p>') if pic else ""
    quote = f'<blockquote class="fu" style="--d:6">{e(q)}<cite>— {e(who)}</cite></blockquote>' if not evening else ""
    html = TEMPLATE
    for k, v in {"__TITLE__": "Tomorrow" if evening else "Morning brief", "__CSS__": CSS, "__JS__": JS, "__BG__": bg, "__FX__": kind,
                 "__DATE__": f"{d:%A, %d %B}", "__GREET__": greet, "__CHIPS__": "".join(chips), "__QUOTE__": quote, "__CARDS__": cards,
                 "__LIVE__": e(ctx["page_url"]), "__CREDIT__": credit, "__MADE__": ctx["made"]}.items():
        html = html.replace(k, v)
    return html


TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#1b2433"><title>__TITLE__</title>
<link rel="manifest" href="manifest.webmanifest"><link rel="icon" type="image/png" href="icon-192.png"><link rel="apple-touch-icon" href="icon-192.png">
<meta name="apple-mobile-web-app-capable" content="yes"><meta name="mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-title" content="Brief">
<script>document.documentElement.classList.add('js')</script>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>__CSS__</style></head><body>
<header class="hero" data-fx="__FX__"><div class="bg" style="__BG__"></div><canvas aria-hidden="true"></canvas>
<div class="top"><span class="gl pillsm">📍 Frankfurt</span><span class="gl pillsm">__DATE__</span></div>
<div class="hi"><h1 class="fu" style="--d:1">__GREET__</h1><div class="chips">__CHIPS__</div>__QUOTE__</div>
<svg class="cue" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></header>
<main>__CARDS__
<footer><p><a href="__LIVE__">Live commute page →</a></p>__CREDIT__<p>Made __MADE__ · RMV, Open-Meteo, DWD via Bright Sky, tagesschau, Wikimedia, pegelonline, ECB</p></footer>
</main><script>__JS__</script></body></html>"""

CSS = """
:root{--bg:#f2eee6;--card:#fffdf9;--ink:#1b1a17;--mute:#7a746a;--line:#ebe5d8;--soft:#f5f1e8;--sun:#f59e0b;--rain:#3b82f6;--ok:#15803d;--okb:#e3f5e8;
--warn:#b45309;--warnb:#fdf0dc;--bad:#c62828;--badb:#fde9e7;--u:#1b64b0;--s:#2f8f3a;--bus:#8b3a8f;--tram:#c4322a;--rail:#6b6b6b;--r:22px;
--shadow:0 1px 1px rgba(60,40,10,.04),0 12px 30px -16px rgba(60,40,10,.28)}
@media (prefers-color-scheme:dark){:root{--bg:#0d0e10;--card:#17181b;--ink:#f3f1ec;--mute:#9d988d;--line:#2a2b2f;--soft:#1f2024;--ok:#4ade80;--okb:#10301c;
--warn:#fbbf24;--warnb:#33260c;--bad:#ff8a80;--badb:#3a1512;--shadow:0 1px 0 rgba(255,255,255,.04),0 14px 34px -16px rgba(0,0,0,.7)}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif;-webkit-font-smoothing:antialiased}
a{color:inherit}
/* hero */
.hero{position:relative;min-height:min(88svh,640px);color:#fff;display:flex;flex-direction:column;justify-content:flex-end;overflow:hidden;isolation:isolate;background:#1b2433}
.hero .bg{position:absolute;inset:-5%;z-index:-3;background-size:cover;background-position:center;animation:kb 34s ease-in-out infinite alternate;will-change:transform}
@keyframes kb{from{transform:scale(1) translate3d(0,0,0)}to{transform:scale(1.1) translate3d(-1.6%,-1.2%,0)}}
.hero:before{content:"";position:absolute;inset:0;z-index:-2;background:linear-gradient(180deg,rgba(8,12,22,.6) 0%,rgba(8,12,22,.08) 30%,rgba(8,12,22,.32) 58%,rgba(8,12,22,.9) 100%)}
.hero canvas{position:absolute;inset:0;width:100%;height:100%;z-index:-1;pointer-events:none}
.top{position:absolute;top:0;left:0;right:0;max-width:640px;margin:0 auto;padding:calc(env(safe-area-inset-top) + 16px) 18px 0;display:flex;justify-content:space-between;gap:8px}
.gl{background:rgba(255,255,255,.14);backdrop-filter:blur(14px) saturate(1.3);-webkit-backdrop-filter:blur(14px) saturate(1.3);border:1px solid rgba(255,255,255,.26);border-radius:18px;box-shadow:0 8px 24px -10px rgba(0,0,0,.45)}
.pillsm{padding:6px 12px;font-size:12px;font-weight:600;letter-spacing:.02em;border-radius:99px}
.hi{width:100%;max-width:640px;margin:0 auto;padding:110px 18px 56px}
h1{font:700 clamp(34px,9vw,50px)/1.04 Fraunces,Georgia,serif;margin:0 0 20px;letter-spacing:-.01em;text-shadow:0 2px 24px rgba(0,0,0,.4)}
.chips{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:22px}
.chips .gl{display:flex;align-items:center;gap:10px;padding:10px 16px}
.chips b{display:block;font:600 28px/1.1 Fraunces,Georgia,serif;font-variant-numeric:tabular-nums}.chips b.small{font-size:20px}
.chips u{text-decoration:none;opacity:.6;margin:0 5px;font-size:20px}.chips small{display:block;font-size:12px;opacity:.88}
.chips .em{font-size:30px;line-height:1}.leave{flex-direction:column;align-items:flex-start!important;gap:0!important}
.cd{margin-left:6px;font-weight:600}.cd:before{content:"· "}.cd:empty:before{content:""}
blockquote{margin:0;max-width:520px;font:500 clamp(17px,4.6vw,21px)/1.4 Fraunces,Georgia,serif;text-shadow:0 1px 14px rgba(0,0,0,.5);position:relative;padding-left:14px;border-left:3px solid rgba(255,255,255,.55)}
cite{display:block;font:400 13px Inter,sans-serif;opacity:.85;margin-top:8px;font-style:normal}
.cue{position:absolute;left:50%;bottom:30px;width:26px;height:26px;margin-left:-13px;fill:none;stroke:#fff;stroke-width:2.4;stroke-linecap:round;stroke-linejoin:round;opacity:.8;animation:bob 2.2s ease-in-out infinite}
@keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(7px)}}
.fu{opacity:0;transform:translateY(16px);animation:fu .9s cubic-bezier(.2,.8,.2,1) forwards;animation-delay:calc(var(--d,0)*120ms + 150ms)}
@keyframes fu{to{opacity:1;transform:none}}
/* cards */
main{max-width:640px;margin:-34px auto 0;padding:0 14px 44px;position:relative}
.card{position:relative;background:var(--card);border-radius:var(--r);padding:18px;margin:0 0 14px;box-shadow:var(--shadow);border:1px solid var(--line);overflow:hidden}
.card h2{display:flex;align-items:center;gap:10px;margin:0 0 12px;font:600 11.5px/1 Inter,sans-serif;letter-spacing:.09em;text-transform:uppercase;color:var(--mute)}
.ic{display:grid;place-items:center;width:30px;height:30px;border-radius:10px;background:var(--soft);font-size:16px;letter-spacing:0;flex:none}
.card p{margin:6px 0}.card h3{margin:14px 0 6px;font:600 12px/1 Inter;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}
.lead{font-size:16px;font-weight:600;line-height:1.4}.muted,.src{color:var(--mute);font-size:13px}.src{margin:12px 0 0;font-size:11.5px}.center{text-align:center}
.card.warn{box-shadow:inset 4px 0 0 var(--warn),var(--shadow)}.card.warn .ic{background:var(--warnb)}
.card.bad{box-shadow:inset 4px 0 0 var(--bad),var(--shadow);background:linear-gradient(100deg,var(--badb),var(--card) 55%)}
.card.bad .ic{background:var(--badb);animation:pulse 2.2s ease-out infinite}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(198,40,40,.45)}70%,100%{box-shadow:0 0 0 12px rgba(198,40,40,0)}}
.slim{display:flex;gap:14px;align-items:flex-start;padding:14px 18px}.slim h2{margin-bottom:4px}.slim p{margin:0;font-size:14.5px}.slim .ic{width:38px;height:38px;font-size:20px;border-radius:12px}
.alertline{font-weight:600;color:var(--bad)}.card.warn .alertline{color:var(--warn)}
.pill{display:inline-block;padding:3px 10px;border-radius:99px;background:var(--soft);font-size:12px;font-weight:600}.warnpill{background:var(--warnb);color:var(--warn)}
.banner{background:var(--warnb);color:var(--warn);padding:9px 12px;border-radius:12px;font-weight:600;font-size:13.5px}
/* reveal + draw animations (only with JS, so the page is complete without it) */
.js .r{opacity:0;transform:translateY(22px) scale(.985);transition:opacity .7s cubic-bezier(.2,.8,.2,1),transform .7s cubic-bezier(.2,.8,.2,1);transition-delay:calc(var(--d,0)*70ms)}
.js .r.in{opacity:1;transform:none}
.js .draw{stroke-dasharray:1;stroke-dashoffset:1}.js .in .draw{animation:draw 1.6s .25s cubic-bezier(.4,0,.2,1) forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.js .fade{opacity:0}.js .in .fade{animation:fade .8s .9s ease forwards}@keyframes fade{to{opacity:1}}
.js .bar{transform:scaleY(0)}.js .in .bar{animation:growy .8s cubic-bezier(.2,.8,.2,1) forwards;animation-delay:calc(var(--k,0)*45ms + .25s)}
@keyframes growy{to{transform:scaleY(1)}}
.js .seg{transform:scaleX(0)}.js .in .seg{animation:growx .7s cubic-bezier(.2,.8,.2,1) forwards;animation-delay:calc(var(--k,0)*110ms + .2s)}
@keyframes growx{to{transform:scaleX(1)}}
/* weather chart + sky */
.chart{width:100%;height:auto;display:block;margin-top:8px;overflow:visible}.chart .bar,.rb .bar{transform-box:fill-box;transform-origin:bottom}
.axis{stroke:var(--line);stroke-width:1.5}.rainbar{fill:var(--rain);opacity:.32}.pct{font:600 10px Inter;fill:var(--rain)}
.area{fill:url(#ag)}.tline{fill:none;stroke:var(--sun);stroke-width:3.2;stroke-linecap:round;stroke-linejoin:round;filter:drop-shadow(0 4px 6px rgba(245,158,11,.35))}
.dot{fill:var(--card);stroke:var(--sun);stroke-width:2.6}.tlabel{font:700 12.5px Inter;fill:var(--ink)}.emo{font-size:17px}.hlabel{font:500 11px Inter;fill:var(--mute)}
.legend{display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--mute);margin:10px 0 0}.legend span{display:flex;align-items:center;gap:6px}
.lg{display:inline-block;width:14px;height:4px;border-radius:3px;background:var(--sun)}.lg.rain{background:var(--rain);opacity:.5;height:10px;width:8px;border-radius:2px}
.skygrid{display:grid;grid-template-columns:1.7fr 1fr;gap:14px;align-items:center}.sunarc{width:100%;height:auto;display:block}
.sunarc .track{fill:none;stroke:var(--line);stroke-width:3;stroke-dasharray:2 6;stroke-linecap:round}.sunarc .prog{fill:none;stroke:var(--sun);stroke-width:4;stroke-linecap:round}
.sun{fill:var(--sun)}.halo{fill:var(--sun);opacity:.25;animation:halo 3s ease-in-out infinite;transform-box:fill-box;transform-origin:center}.sunpos.night{opacity:.45!important}
@keyframes halo{0%,100%{transform:scale(1);opacity:.28}50%{transform:scale(1.5);opacity:.08}}
.moonbox{display:flex;flex-direction:column;align-items:center;text-align:center;gap:4px}.moon{width:76px;height:76px;filter:drop-shadow(0 0 14px rgba(250,240,200,.35));animation:float 6s ease-in-out infinite}
@keyframes float{0%,100%{transform:translateY(0)}50%{transform:translateY(-5px)}}
.moon .dark{fill:#2a2f3d}.moon .lit{fill:#f6efd2}.moon .rim{fill:none;stroke:rgba(0,0,0,.15);stroke-width:1}
/* trains */
.trip{padding:12px 0;border-top:1px solid var(--line)}.trip:first-of-type{border-top:0;padding-top:2px}
.trow{display:flex;align-items:baseline;justify-content:space-between;gap:10px;margin-bottom:8px}.trow b{font:600 24px/1 Fraunces,Georgia,serif;font-variant-numeric:tabular-nums}
.trip.rec .trow b{color:var(--ok)}.dur{flex:1;text-align:center;color:var(--mute);font-size:12px;position:relative}
.dur:before,.dur:after{content:"";position:absolute;top:50%;width:calc(50% - 30px);border-top:1.5px dashed var(--line)}.dur:before{left:0}.dur:after{right:0}
.bar{display:flex;gap:3px;height:34px}.seg{display:grid;place-items:center;border-radius:11px;color:#fff;font:700 12px Inter;min-width:5px;background:var(--rail);transform-origin:left;overflow:hidden;white-space:nowrap}
.seg em{font-style:normal}.seg.demand{background:#0f766e}.chip.demand{background:#0f766e}.seg.s{background:var(--s)}.seg.u{background:var(--u)}.seg.bus{background:var(--bus)}.seg.tram{background:var(--tram)}
.seg.walk{background:repeating-linear-gradient(90deg,var(--line) 0 5px,transparent 5px 10px);color:var(--mute)}.seg.wait{background:var(--soft)}
.tmeta{display:flex;justify-content:space-between;gap:10px;margin-top:9px;align-items:flex-start}.rides{list-style:none;margin:0;padding:0;display:grid;gap:5px;font-size:13.5px}
.rides li{display:flex;align-items:center;gap:7px;flex-wrap:wrap}.chip{display:inline-block;color:#fff;font-weight:700;font-size:12px;padding:2px 8px;border-radius:6px;background:var(--rail)}
.chip.u{background:var(--u)}.chip.s{background:var(--s);border-radius:10px}.chip.bus{background:var(--bus)}.chip.tram{background:var(--tram)}
.delay{color:var(--bad);font-weight:700;font-size:12px}.occ{display:inline-flex;gap:2px}.occ i{width:5px;height:11px;border-radius:2px;background:var(--line)}.occ i.on{background:var(--warn)}.occl{font-size:12px}
.tright{display:flex;flex-direction:column;align-items:flex-end;gap:5px}.st{font-size:12px;font-weight:700;padding:3px 10px;border-radius:99px}.st.ok{color:var(--ok);background:var(--okb)}.st.bad{color:var(--bad);background:var(--badb)}
.badge{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;font-weight:700;color:var(--warn)}.badge.good{color:var(--ok)}
/* rain on the way home, radar */
.rainbars{display:flex;gap:8px;align-items:flex-end;height:96px;margin-top:10px}.rb{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:3px;font-size:11px;color:var(--mute)}
.rb .bar{display:block;width:100%;max-width:34px;height:var(--h);min-height:3px;border-radius:7px;background:linear-gradient(to top,var(--rain),#93c5fd)}.rb b{font-size:11.5px;color:var(--ink)}
.map{position:relative;height:250px;border-radius:16px;overflow:hidden;background:var(--soft)}.map .shimmer{position:absolute;inset:0;background:linear-gradient(100deg,transparent 30%,rgba(255,255,255,.25) 50%,transparent 70%);animation:sh 1.6s infinite}
@keyframes sh{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
.basemap{filter:saturate(.55) brightness(1.04) contrast(.92)}
@media (prefers-color-scheme:dark){.basemap{filter:invert(1) hue-rotate(180deg) saturate(.5) brightness(.82) contrast(.9)}}
.mapbar{position:absolute;left:10px;right:10px;bottom:30px;z-index:500;display:flex;align-items:center;gap:10px;padding:7px 10px;border-radius:12px;background:rgba(255,255,255,.88);color:#111;font:600 12px Inter;backdrop-filter:blur(8px)}
@media (prefers-color-scheme:dark){.mapbar{background:rgba(23,24,27,.88);color:#eee}}
.mapbar button{all:unset;cursor:pointer;width:26px;height:26px;border-radius:50%;background:var(--rain);color:#fff;display:grid;place-items:center;font-size:11px}
.prog2{flex:1;height:4px;border-radius:3px;background:rgba(120,120,120,.3);overflow:hidden}.prog2 i{display:block;height:100%;width:0;background:var(--rain);transition:width .3s linear}
/* calendar, bins, notes */
.timeline{list-style:none;margin:10px 0 0;padding:0}.timeline li{display:grid;grid-template-columns:52px 1fr;gap:2px 12px;padding:8px 0 8px 14px;border-left:3px solid var(--line);position:relative}
.timeline li:before{content:"";position:absolute;left:-7px;top:13px;width:11px;height:11px;border-radius:50%;background:var(--card);border:3px solid var(--rain)}
.timeline b{font-variant-numeric:tabular-nums}.timeline .muted{grid-row:2;font-size:12px}.timeline p{grid-column:2;grid-row:1/3;margin:0;align-self:center;font-weight:500}
.bins{display:flex;gap:18px;flex-wrap:wrap;margin-top:6px}.bincell{display:flex;flex-direction:column;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--mute)}
.binsvg{width:46px;height:54px}.binsvg .body{fill:var(--c)}.binsvg .lid rect{fill:var(--c);filter:brightness(1.18)}.binsvg .ribs{stroke:rgba(255,255,255,.4);stroke-width:2.5;stroke-linecap:round;fill:none}
.binsvg .lid{transform-box:fill-box;transform-origin:left bottom}.js .in .binsvg .lid{animation:lid 1s calc(var(--k)*160ms + .5s) ease}@keyframes lid{0%,100%{transform:rotate(0)}35%{transform:rotate(-18deg)}}
.notes{list-style:none;margin:0;padding:0;display:grid;gap:9px}.notes li{display:flex;gap:12px;align-items:center;padding:10px 12px;border-radius:14px;background:var(--soft);font-weight:500}.notes span{font-size:20px}
/* news, learning */
.news{list-style:none;margin:0;padding:0}.news li+li{border-top:1px solid var(--line)}.news a{display:block;text-decoration:none;padding:10px 0}
.news .nt{display:block;font-weight:600;line-height:1.35}.news a:hover .nt{text-decoration:underline}.news .muted{font-size:12px}
.year{font:700 64px/1 Fraunces,Georgia,serif;color:transparent;-webkit-text-stroke:1.5px var(--line);margin-bottom:-6px;letter-spacing:-.02em}
.article{display:flex;gap:14px;align-items:flex-start}.article img{width:96px;height:96px;object-fit:cover;border-radius:14px;flex:none;box-shadow:var(--shadow)}.article h3{margin:0 0 6px;font:600 17px/1.3 Fraunces,Georgia,serif;text-transform:none;letter-spacing:0;color:var(--ink)}
.article p{margin:0 0 8px;font-size:14px;color:var(--mute)}.article a{font-weight:600;font-size:13px}
.wordhead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap}.word{font:700 clamp(32px,9vw,42px)/1.1 Fraunces,Georgia,serif;letter-spacing:-.01em}
.word{overflow-wrap:anywhere;hyphens:auto}.word.long{font-size:clamp(24px,7.4vw,34px)}
.gender{font:700 12px Inter;text-transform:uppercase;letter-spacing:.06em;padding:3px 9px;border-radius:99px;color:#fff;background:var(--rail)}.gender.der{background:#2563eb}.gender.die{background:#db2777}.gender.das{background:#16a34a}
.example{margin-top:12px;padding:12px 14px;border-radius:14px;background:var(--soft);font-style:italic}.example .muted{font-style:normal}
/* river, markets */
.gauge{position:relative;height:16px;border-radius:99px;background:var(--soft);overflow:hidden;margin-top:6px}.gauge .fill{height:100%;width:var(--w);border-radius:99px;background:linear-gradient(90deg,#38bdf8,#2563eb,#38bdf8);background-size:200% 100%;animation:wave 4s linear infinite}
.gauge.high .fill{background:linear-gradient(90deg,#f59e0b,#dc2626,#f59e0b);background-size:200% 100%}@keyframes wave{to{background-position:-200% 0}}
.js .gauge .fill{width:0;transition:width 1.4s cubic-bezier(.2,.8,.2,1) .3s}.js .in .gauge .fill{width:var(--w)}.mark{position:absolute;top:0;bottom:0;width:2px;background:var(--bad)}
.gaugelab{display:flex;justify-content:space-between;margin-top:8px;font-weight:600}.gaugelab small{font-weight:400}
.ticker{list-style:none;margin:0;padding:0}.ticker li{display:grid;grid-template-columns:1fr 84px auto;gap:12px;align-items:center;padding:9px 0}.ticker li+li{border-top:1px solid var(--line)}
.lab{font-weight:600}.val{text-align:right;font-weight:700;font-variant-numeric:tabular-nums}.val em{display:block;font-style:normal;font-size:12px;font-weight:600}.up{color:var(--ok)}.down{color:var(--bad)}
.spark{width:84px;height:28px;overflow:visible}.spark path{fill:none;stroke-width:2.2;stroke-linecap:round}.spark.up path,.spark.up circle{stroke:var(--ok);fill:var(--ok)}.spark.down path,.spark.down circle{stroke:var(--bad);fill:var(--bad)}.spark path{fill:none!important}
footer{color:var(--mute);font-size:12px;text-align:center;padding:10px 12px 0}footer p{margin:5px 0}
@media (min-width:700px){.hero{min-height:560px}.card{padding:22px}}
@media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}
.js .r,.js .fade,.js .seg,.js .bar,.fu{opacity:1!important;transform:none!important}.js .draw{stroke-dashoffset:0!important}.js .gauge .fill{width:var(--w)!important}}
"""

JS = """
(()=>{
const rm=matchMedia('(prefers-reduced-motion: reduce)').matches, $=(s,r=document)=>[...r.querySelectorAll(s)];
// reveal cards as they scroll in
const io=new IntersectionObserver(es=>es.forEach(x=>{if(x.isIntersecting){x.target.classList.add('in');io.unobserve(x.target)}}),{threshold:.12});
$('.r').forEach(el=>io.observe(el));
// count the temperatures up
if(!rm)$('[data-count]').forEach(el=>{const to=+el.dataset.count,t0=performance.now();(function f(t){const p=Math.min(1,(t-t0)/1100),v=Math.round(to*(1-Math.pow(1-p,3)));el.textContent=v;if(p<1)requestAnimationFrame(f)})(t0)});
// countdown to the recommended departure
$('[data-leave]').forEach(el=>{const at=new Date(el.dataset.leave),out=$('.cd',el)[0];
 const u=()=>{const m=Math.round((at-Date.now())/6e4);out.textContent=m>90?`in ${Math.floor(m/60)} h ${m%60} min`:m>0?`in ${m} min`:m>-6?'leave now':''};u();setInterval(u,15000)});
// weather in the hero: rain, snow, sun glow, drifting cloud or fog
const hero=$('.hero')[0],cv=$('canvas',hero)[0],kind=hero.dataset.fx;
if(!rm&&cv&&kind!=='none'){const c=cv.getContext('2d');let W,H;const dpr=Math.min(devicePixelRatio||1,2);
 const size=()=>{W=cv.clientWidth;H=cv.clientHeight;cv.width=W*dpr;cv.height=H*dpr;c.setTransform(dpr,0,0,dpr,0,0)};size();addEventListener('resize',size);
 const n={rain:120,snow:80,fog:5,cloud:6,sun:0}[kind]||0,R=Math.random;
 const P=[...Array(n)].map(()=>({x:R()*W,y:R()*H,v:kind==='rain'?520+R()*380:20+R()*40,l:10+R()*16,r:1+R()*2.6,s:R()*6.28,a:.05+R()*.08}));
 let last=0;(function tick(t){const dt=Math.min(.05,(t-last)/1000||.016);last=t;c.clearRect(0,0,W,H);
  if(kind==='rain'){c.strokeStyle='rgba(205,225,255,.42)';c.lineWidth=1.2;c.beginPath();P.forEach(p=>{c.moveTo(p.x,p.y);c.lineTo(p.x-p.l*.12,p.y+p.l);p.y+=p.v*dt;p.x-=p.v*dt*.12;if(p.y>H){p.y=-30;p.x=R()*(W+60)}});c.stroke()}
  else if(kind==='snow'){c.fillStyle='rgba(255,255,255,.8)';P.forEach(p=>{p.y+=p.v*dt;p.s+=dt;p.x+=Math.sin(p.s)*.4;if(p.y>H){p.y=-6;p.x=R()*W}c.beginPath();c.arc(p.x,p.y,p.r,0,6.28);c.fill()})}
  else if(kind==='sun'){const g=c.createRadialGradient(W*.82,H*.12,0,W*.82,H*.12,H*.75),k=.85+.15*Math.sin(t/1800);g.addColorStop(0,`rgba(255,220,130,${.6*k})`);g.addColorStop(.35,`rgba(255,190,90,${.22*k})`);g.addColorStop(1,'rgba(255,190,90,0)');c.fillStyle=g;c.fillRect(0,0,W,H)}
  else{P.forEach(p=>{p.x+=p.v*dt*(kind==='fog'?.6:1);if(p.x>W+260)p.x=-260;const w=kind==='fog'?420:240,g=c.createRadialGradient(p.x,p.y%(H*.8)+H*.1,0,p.x,p.y%(H*.8)+H*.1,w);g.addColorStop(0,`rgba(255,255,255,${p.a*(kind==='fog'?1.8:1)})`);g.addColorStop(1,'rgba(255,255,255,0)');c.fillStyle=g;c.fillRect(p.x-w,0,w*2,H)})}
  requestAnimationFrame(tick)})(0)}
// rain radar (RainViewer frames on a Leaflet map), built when the card scrolls into view
const rd=$('#radar')[0];
if(rd){const lo=new IntersectionObserver(es=>{if(es[0].isIntersecting){lo.disconnect();radar(rd)}},{rootMargin:'200px'});lo.observe(rd)}
function radar(el){
 const css=document.createElement('link');css.rel='stylesheet';css.href='https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css';document.head.appendChild(css);
 const js=document.createElement('script');js.src='https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js';
 js.onload=async()=>{try{
  const meta=await (await fetch('https://api.rainviewer.com/public/weather-maps.json')).json(),fr=[...meta.radar.past,...(meta.radar.nowcast||[])],lat=+el.dataset.lat,lon=+el.dataset.lon;
  el.innerHTML='';const map=L.map(el,{zoomControl:false,scrollWheelZoom:false,attributionControl:true}).setView([lat,lon],8);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:10,className:'basemap',attribution:'© OpenStreetMap · radar RainViewer'}).addTo(map);
  const layers=fr.map(f=>L.tileLayer(meta.host+f.path+'/256/{z}/{x}/{y}/2/1_1.png',{opacity:0,maxNativeZoom:7,maxZoom:10,zIndex:5}).addTo(map));
  const bar=document.createElement('div');bar.className='mapbar';bar.innerHTML='<button aria-label="Play or pause">❚❚</button><span class="tm"></span><div class="prog2"><i></i></div>';el.appendChild(bar);
  L.DomEvent.disableClickPropagation(bar);const btn=bar.firstChild,tm=$('.tm',bar)[0],pr=$('i',bar)[0];let i=fr.length-1,play=!rm,timer;
  const show=k=>{layers.forEach((l,j)=>l.setOpacity(j===k?.72:0));const t=new Date(fr[k].time*1e3);tm.textContent=t.toLocaleTimeString('de-DE',{hour:'2-digit',minute:'2-digit'})+(fr[k].time*1e3>Date.now()+3e5?' · forecast':'');pr.style.width=((k+1)/fr.length*100)+'%'};
  const step=()=>{i=(i+1)%fr.length;show(i);timer=setTimeout(step,i===fr.length-1?1800:550)};
  const set=p=>{play=p;btn.textContent=p?'❚❚':'▶';clearTimeout(timer);if(p)timer=setTimeout(step,300)};
  btn.onclick=()=>set(!play);el.addEventListener('click',e=>{if(!bar.contains(e.target))set(!play)});show(i);set(play);
 }catch(e){el.innerHTML='<p class="muted" style="padding:16px">Radar unavailable right now.</p>'}};
 document.head.appendChild(js)}
})();
"""
