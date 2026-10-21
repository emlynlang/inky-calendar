"""Renders an 800x480 weather + tide dashboard (dashboard.jpg) for a
Pimoroni Inky Frame 7.3". Run by the GitHub Actions workflow every 30 minutes.

Environment variables (all optional; unset or empty falls back to a default):
  LATITUDE / LONGITUDE  location, default Dromore West
  TIMEZONE      IANA timezone, default Europe/Dublin
  TIDE_LATITUDE / TIDE_LONGITUDE  optional sea point for tides
"""
import datetime
import math
import os
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------ config
LAT = (os.environ.get("LATITUDE") or "54.24").strip()
LON = (os.environ.get("LONGITUDE") or "-8.80").strip()
TZ_NAME = (os.environ.get("TIMEZONE") or "Europe/Dublin").strip()
TZ = ZoneInfo(TZ_NAME)
# Offshore point used for tides (the marine model has no data over land). Approximate:
# a spot in the sea just north of Dromore West. Override with TIDE_LATITUDE / TIDE_LONGITUDE.
TIDE_LAT = (os.environ.get("TIDE_LATITUDE") or "54.33").strip()
TIDE_LON = (os.environ.get("TIDE_LONGITUDE") or "-8.85").strip()
OUTPUT_PATH = "dashboard.jpg"
W, H = 800, 480

# Colours. The Inky Frame's JPEG decoder dithers to its 7 inks, so pastel
# shades come out as soft stippling on the panel.
BLACK = (20, 20, 20)
WHITE = (255, 255, 255)
RED = (200, 40, 40)
BLUE = (40, 60, 170)
GREY = (110, 110, 110)
SUN = (246, 174, 72)
ORANGE_DARK = (226, 130, 40)
TIDE_FILL = (176, 204, 242)
CLOUD_FRONT = (192, 202, 222)
CLOUD_BACK = (122, 142, 182)
RAIN = (70, 110, 190)
BOLT = (245, 200, 50)
MOON_BG = (22, 26, 44)
MOON_DARK = (62, 68, 96)
MOON_LIT = (246, 232, 180)

# ------------------------------------------------------------------ fonts
_FONT_CACHE = {}


def font(size, bold=False):
    key = (size, bold)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    candidates = [
        "fonts/Inter.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    f = None
    for path in candidates:
        try:
            f = ImageFont.truetype(path, size)
            if path.endswith("Inter.ttf") and bold:
                try:  # Inter is a variable font: raise the Weight axis for bold text
                    axes = f.get_variation_axes()
                    vals = [a["default"] for a in axes]
                    for i, a in enumerate(axes):
                        if a["name"] in (b"Weight", "Weight"):
                            vals[i] = 700
                    f.set_variation_by_axes(vals)
                except Exception:
                    pass
            break
        except (OSError, ValueError):
            continue
    if f is None:
        f = ImageFont.load_default(size)
    _FONT_CACHE[key] = f
    return f


def fit(d, s, f, max_w):
    """Truncate s with an ellipsis so it fits in max_w pixels."""
    if d.textlength(s, font=f) <= max_w:
        return s
    while s and d.textlength(s + "…", font=f) > max_w:
        s = s[:-1]
    return s.rstrip() + "…"


# ------------------------------------------------------------------ weather
def get_weather():
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": LAT,
            "longitude": LON,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                       "weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max,sunrise,sunset",
            "timezone": TZ_NAME,
            "forecast_days": 5,
            "wind_speed_unit": "kmh",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def describe(code):
    return {
        0: "Clear sky", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Fog", 48: "Rime fog", 51: "Light drizzle", 53: "Drizzle",
        55: "Heavy drizzle", 56: "Freezing drizzle", 57: "Freezing drizzle",
        61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain",
        67: "Freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
        77: "Snow grains", 80: "Light showers", 81: "Showers", 82: "Heavy showers",
        85: "Snow showers", 86: "Snow showers", 95: "Thunderstorm",
        96: "Thunder + hail", 99: "Thunder + hail",
    }.get(code, "Unknown")


# ------------------------------------------------------------------ icons
# Flat, soft, filled shapes. Each icon is drawn 4x larger on a transparent
# layer, then shrunk, which gives smooth (anti-aliased) edges.
SS = 4


def _circle(d, x, y, r, fill):
    d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _cloud(d, cx, cy, s, fill, grow=0):
    _circle(d, cx - .30 * s, cy + .06 * s, .27 * s + grow, fill)
    _circle(d, cx + .02 * s, cy - .14 * s, .36 * s + grow, fill)
    _circle(d, cx + .36 * s, cy + .08 * s, .25 * s + grow, fill)
    d.rectangle([cx - .30 * s, cy - .02 * s, cx + .36 * s, cy + .33 * s + grow], fill=fill)


def _cloud_pair(d, cx, cy, s):
    # darker cloud peeking out behind a lighter one, each with a white gap
    for (x, y, sz, col) in ((cx - .32 * s, cy - .30 * s, .82 * s, CLOUD_BACK),
                            (cx + .04 * s, cy + .04 * s, s, CLOUD_FRONT)):
        _cloud(d, x, y, sz, WHITE, grow=.05 * s)
        _cloud(d, x, y, sz, col)


def _sun(d, cx, cy, s):
    _circle(d, cx, cy, .5 * s, SUN)


def _drop(d, x, y, r):
    d.polygon([(x, y - 2.1 * r), (x - .92 * r, y - .45 * r), (x + .92 * r, y - .45 * r)], fill=RAIN)
    _circle(d, x, y, r, RAIN)


def _icon_fn(code, night=False):
    def clear(d, cx, cy, s):
        if night:
            _circle(d, cx, cy, .5 * s, SUN)
            _circle(d, cx + .26 * s, cy - .14 * s, .42 * s, WHITE)
        else:
            _sun(d, cx, cy, s)

    def part(d, cx, cy, s):
        _sun(d, cx + .24 * s, cy - .26 * s, .8 * s)
        _cloud(d, cx - .06 * s, cy + .14 * s, .92 * s, WHITE, grow=.05 * s)
        _cloud(d, cx - .06 * s, cy + .14 * s, .92 * s, CLOUD_FRONT)

    def overcast(d, cx, cy, s):
        _cloud_pair(d, cx, cy + .12 * s, s)

    def fog(d, cx, cy, s):
        h = .12 * s
        for i in range(4):
            y = cy - .36 * s + i * .26 * s
            x = cx - .5 * s + (i % 2) * .12 * s
            d.rounded_rectangle([x, y, x + .8 * s, y + h], radius=h / 2, fill=CLOUD_BACK)

    def rain(heavy):
        def f(d, cx, cy, s):
            _cloud_pair(d, cx, cy - .14 * s, s)
            r = .065 * s
            for row in range(3 if heavy else 2):
                n = 4 if row % 2 == 0 else 3
                for i in range(n):
                    x = cx - .34 * s + i * (.68 * s / 3) + (row % 2) * .11 * s
                    _drop(d, x, cy + .50 * s + row * .22 * s, r)
        return f

    def snow(d, cx, cy, s):
        _cloud_pair(d, cx, cy - .14 * s, s)
        for row in range(2):
            for i in range(4 - row):
                x = cx - .34 * s + i * (.68 * s / 3) + row * .11 * s
                _circle(d, x, cy + .52 * s + row * .22 * s, .06 * s, RAIN)

    def thunder(d, cx, cy, s):
        _cloud_pair(d, cx, cy - .14 * s, s)
        pts = [(.05, .26), (-.17, .60), (-.02, .58), (-.10, .92), (.20, .50), (.04, .52)]
        d.polygon([(cx + a * s, cy + b * s) for a, b in pts], fill=BOLT)

    if code in (0, 1):
        return clear
    if code == 2:
        return part
    if code in (45, 48):
        return fog
    if code in (51, 53, 55, 56, 57, 61, 63, 80, 81):
        return rain(False)
    if code in (65, 66, 67, 82):
        return rain(True)
    if code in (71, 73, 75, 77, 85, 86):
        return snow
    if code in (95, 96, 99):
        return thunder
    return overcast  # 3 and anything unknown


def draw_icon(img, code, cx, cy, s, night=False):
    box = int(s * 2.4)
    layer = Image.new("RGBA", (box * SS, box * SS), (0, 0, 0, 0))
    _icon_fn(code, night)(ImageDraw.Draw(layer), box * SS / 2, box * SS / 2, s * SS)
    layer = layer.resize((box, box), Image.LANCZOS)
    img.paste(layer, (int(cx - box / 2), int(cy - box / 2)), layer)


# ------------------------------------------------------------------ moon
def moon_phase(now):
    """0 = new, 0.25 = first quarter, 0.5 = full, 0.75 = last quarter."""
    utc = now.astimezone(datetime.timezone.utc)
    ref = datetime.datetime(2000, 1, 6, 18, 14, tzinfo=datetime.timezone.utc)  # a new moon
    days = (utc - ref).total_seconds() / 86400.0
    return (days / 29.530588853) % 1.0


def moon_name(p):
    for limit, name in ((0.03, "New Moon"), (0.22, "Waxing Crescent"), (0.28, "First Quarter"),
                        (0.47, "Waxing Gibbous"), (0.53, "Full Moon"), (0.72, "Waning Gibbous"),
                        (0.78, "Last Quarter"), (0.97, "Waning Crescent")):
        if p < limit:
            return name
    return "New Moon"


def draw_moon(img, cx, cy, r, p):
    """Phase as seen from the northern hemisphere: waxing = right side lit."""
    n = int(r * 2 + 8)
    layer = Image.new("RGBA", (n * SS, n * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c, R = n * SS / 2, r * SS
    _circle(d, c, c, R, MOON_DARK)
    k = math.cos(2 * math.pi * p)
    for dy in range(-int(R), int(R) + 1):
        w = math.sqrt(max(0.0, R * R - dy * dy))
        t = w * k
        x0, x1 = (t, w) if p < 0.5 else (-w, -t)
        if x1 > x0:
            d.line([(c + x0, c + dy), (c + x1, c + dy)], fill=MOON_LIT)
    layer = layer.resize((n, n), Image.LANCZOS)
    img.paste(layer, (int(cx - n / 2), int(cy - n / 2)), layer)


# ------------------------------------------------------------------ tides
def get_tides():
    """Hourly sea level (m, incl. tides) for today and tomorrow, as [(datetime, metres)]."""
    r = requests.get(
        "https://marine-api.open-meteo.com/v1/marine",
        params={
            "latitude": TIDE_LAT,
            "longitude": TIDE_LON,
            "hourly": "sea_level_height_msl",
            "timezone": TZ_NAME,
            "forecast_days": 2,
        },
        timeout=20,
    )
    r.raise_for_status()
    h = r.json()["hourly"]
    series = [(datetime.datetime.fromisoformat(t).replace(tzinfo=TZ), v)
              for t, v in zip(h["time"], h["sea_level_height_msl"]) if v is not None]
    if len(series) < 24:
        raise ValueError("no tide data for this point")
    return series


def _cr(p0, p1, p2, p3, t):
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


def _curve(pts, step=0.1):
    """Smooth [(hour, value)] samples through the hourly points (Catmull-Rom spline)."""
    out, n = [], len(pts)
    for i in range(n - 1):
        p0, p1 = pts[max(i - 1, 0)][1], pts[i][1]
        p2, p3 = pts[i + 1][1], pts[min(i + 2, n - 1)][1]
        h0, h1 = pts[i][0], pts[i + 1][0]
        k = max(1, int(round((h1 - h0) / step)))
        for j in range(k):
            out.append((h0 + (h1 - h0) * j / k, _cr(p0, p1, p2, p3, j / k)))
    out.append(pts[-1])
    return out


def find_extrema(series):
    """High and low tide times: [(datetime, 'H' or 'L')], refined between the hourly points."""
    out = []
    for i in range(1, len(series) - 1):
        a, b, c = series[i - 1][1], series[i][1], series[i + 1][1]
        if (b > a and b >= c) or (b < a and b <= c):
            den = a - 2 * b + c
            off = max(-1.0, min(1.0, 0.5 * (a - c) / den)) if den else 0.0
            out.append((series[i][0] + datetime.timedelta(hours=off), "H" if b > a else "L"))
    return out


def _fit_size(d, s, bold, max_w, start):
    size = start
    while size > 10 and d.textlength(s, font=font(size, bold)) > max_w:
        size -= 1
    return size


def draw_tides(img, d, box, series, now):
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=10, outline=BLACK, width=2)
    d.text((x0 + 14, y0 + 6), "TIDES TODAY", font=font(13, True), fill=GREY)
    midnight = datetime.datetime.combine(now.date(), datetime.time(), tzinfo=TZ)
    pts = []
    for t, v in series or []:
        hrs = (t - midnight).total_seconds() / 3600.0
        if -1.5 <= hrs <= 25.5:
            pts.append((hrs, v))
    if len(pts) < 6:
        d.text((x0 + 14, y0 + 56), "Tide data unavailable", font=font(18), fill=GREY)
        return

    curve = [(h, v) for h, v in _curve(pts) if 0 <= h <= 24]
    px0, px1, py0, py1 = x0 + 18, x1 - 18, y0 + 52, y1 - 50
    vmin, vmax = min(v for _, v in curve), max(v for _, v in curve)
    span = max(vmax - vmin, 0.5)

    def X(h):
        return px0 + h / 24.0 * (px1 - px0)

    def Y(v):
        return py1 - (v - vmin) / span * (py1 - py0)

    def at(h):  # curve value at hour h
        return min(curve, key=lambda p: abs(p[0] - h))[1]

    # smooth filled curve, drawn 4x larger then shrunk for clean edges
    pad = 8
    lw, lh = (px1 - px0) + 2 * pad, (py1 - py0) + 2 * pad
    layer = Image.new("RGBA", (lw * SS, lh * SS), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    def L(x, y):
        return ((x - px0 + pad) * SS, (y - py0 + pad) * SS)

    line = [L(X(h), Y(v)) for h, v in curve]
    ld.polygon(line + [L(X(24), py1), L(X(0), py1)], fill=TIDE_FILL)
    ld.line(line, fill=BLUE, width=3 * SS, joint="curve")
    extrema = [(t, k) for t, k in find_extrema(series)
               if 0 <= (t - midnight).total_seconds() / 3600.0 <= 24]
    for t, k in extrema:
        h = (t - midnight).total_seconds() / 3600.0
        cx, cy = L(X(h), Y(at(h)))
        ld.ellipse([cx - 4 * SS, cy - 4 * SS, cx + 4 * SS, cy + 4 * SS], fill=BLUE)
    layer = layer.resize((lw, lh), Image.LANCZOS)
    img.paste(layer, (px0 - pad, py0 - pad), layer)

    # axis, ticks and hour labels
    d.line([(px0, py1 + 1), (px1, py1 + 1)], fill=GREY, width=1)
    for hr in (0, 6, 12, 18, 24):
        d.line([(X(hr), py1 + 1), (X(hr), py1 + 5)], fill=GREY, width=1)
        d.text((X(hr), y1 - 22), "%02d" % (hr % 24), font=font(12), fill=GREY, anchor="ma")

    # high / low tide times
    for t, k in extrema:
        h = (t - midnight).total_seconds() / 3600.0
        cx = min(max(X(h), px0 + 16), px1 - 16)
        y = Y(at(h)) - 20 if k == "H" else Y(at(h)) + 6
        d.text((cx, y), t.strftime("%H:%M"), font=font(12, True), fill=BLACK, anchor="ma")

    # "now" marker
    hn = (now - midnight).total_seconds() / 3600.0
    if 0 <= hn <= 24:
        for yy in range(py0 - 4, py1 + 2, 6):
            d.line([(X(hn), yy), (X(hn), yy + 3)], fill=RED, width=2)
        cx, cy = X(hn), Y(at(hn))
        d.ellipse([cx - 6, cy - 6, cx + 6, cy + 6], fill=WHITE)
        d.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=RED)


def _sun_glyph(d, cx, cy, rising):
    """Small half-sun on a horizon line with an up/down arrow."""
    d.pieslice([cx - 13, cy - 13, cx + 13, cy + 13], 180, 360, fill=SUN)
    d.line([(cx - 20, cy + 1), (cx + 20, cy + 1)], fill=BLACK, width=2)
    if rising:
        d.polygon([(cx, cy - 25), (cx - 6, cy - 16), (cx + 6, cy - 16)], fill=ORANGE_DARK)
    else:
        d.polygon([(cx, cy - 16), (cx - 6, cy - 25), (cx + 6, cy - 25)], fill=ORANGE_DARK)


# ------------------------------------------------------------------ drawing
def generate_image(weather, tides, now, out_path=OUTPUT_PATH):
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    cur, daily = weather["current"], weather["daily"]
    sunrise = datetime.datetime.fromisoformat(daily["sunrise"][0]).replace(tzinfo=TZ)
    sunset = datetime.datetime.fromisoformat(daily["sunset"][0]).replace(tzinfo=TZ)
    is_night = now >= sunset or now < sunrise

    # layout lines
    d.rectangle([320, 0, 321, H], fill=BLACK)
    d.rectangle([322, 300, W, 301], fill=BLACK)

    # date
    date_s = now.strftime("%A, %d %b")
    d.text((24, 10), date_s, font=font(_fit_size(d, date_s, True, 284, 28), True), fill=RED)

    # current weather (large)
    code = cur["weather_code"]
    draw_icon(img, code, 80, 122, 68, night=is_night)
    temp_s = "%d°C" % round(cur["temperature_2m"])
    d.text((152, 56), temp_s, font=font(_fit_size(d, temp_s, True, 160, 78), True), fill=BLACK)
    d.text((154, 150), fit(d, describe(code), font(22), 160), font=font(22), fill=BLACK)
    d.text((26, 192), "Feels %d°  ·  Humidity %d%%  ·  %d km/h" % (
        round(cur["apparent_temperature"]), round(cur["relative_humidity_2m"]),
        round(cur["wind_speed_10m"])), font=font(14), fill=GREY)

    # sunrise / sunset
    _sun_glyph(d, 44, 256, True)
    d.text((82, 228), "Sunrise", font=font(12), fill=GREY)
    d.text((82, 244), sunrise.strftime("%H:%M"), font=font(24, True), fill=BLACK)
    _sun_glyph(d, 188, 256, False)
    d.text((226, 228), "Sunset", font=font(12), fill=GREY)
    d.text((226, 244), sunset.strftime("%H:%M"), font=font(24, True), fill=BLACK)

    # bottom-left panel: moon after sunset, next tides by day
    d.rounded_rectangle([12, 312, 308, 470], radius=14,
                        fill=MOON_BG if is_night else WHITE, outline=BLACK, width=2)
    if is_night:
        p = moon_phase(now)
        draw_moon(img, 82, 391, 54, p)
        words = moon_name(p).split(" ")
        for i, wtxt in enumerate(words):
            d.text((158, 346 + i * 28), wtxt, font=font(22, True), fill=WHITE)
        illum = (1 - math.cos(2 * math.pi * p)) / 2 * 100
        d.text((158, 346 + len(words) * 28 + 6), "%d%% lit" % round(illum), font=font(16), fill=MOON_LIT)
    else:
        d.text((28, 324), "NEXT TIDES", font=font(13, True), fill=GREY)
        nxt = {}
        for t, k in find_extrema(tides or []):
            if t > now and k not in nxt:
                nxt[k] = t
        if nxt:
            for i, (k, t) in enumerate(sorted(nxt.items(), key=lambda kv: kv[1])):
                name = "High" if k == "H" else "Low"
                y = 358 + i * 50
                tri = [(44, y + 4), (34, y + 22), (54, y + 22)] if k == "H" else \
                      [(44, y + 22), (34, y + 4), (54, y + 4)]
                d.polygon(tri, fill=BLUE)
                day = "" if t.date() == now.date() else " " + t.strftime("%a")
                d.text((72, y), "%s %s%s" % (name, t.strftime("%H:%M"), day), font=font(22, True), fill=BLACK)
        else:
            d.text((28, 370), "Tide data unavailable", font=font(18), fill=GREY)

    # tide chart (top right)
    draw_tides(img, d, (334, 10, 786, 292), tides, now)

    # 5-day forecast
    for i in range(5):
        x0 = 332 + i * 94
        cx = x0 + 44
        d.rounded_rectangle([x0, 310, x0 + 88, 470], radius=10, outline=BLACK, width=2)
        day = datetime.date.fromisoformat(daily["time"][i])
        label = "Today" if i == 0 else day.strftime("%a")
        d.text((cx, 318), label, font=font(16, True), fill=BLUE, anchor="ma")
        draw_icon(img, daily["weather_code"][i], cx + 2, 372, 28)
        hi, lo = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        d.text((cx, 414), "%d°/%d°" % (round(hi), round(lo)), font=font(17, True),
               fill=RED if hi >= 25 else BLACK, anchor="ma")
        pp = daily["precipitation_probability_max"][i]
        if pp is not None:
            d.text((cx, 440), "%d%%" % pp, font=font(14), fill=RAIN, anchor="ma")

    # baseline (not progressive) JPEG: what the Inky Frame's decoder expects
    img.save(out_path, "JPEG", quality=90, subsampling=0, optimize=False, progressive=False)


def main():
    now = datetime.datetime.now(TZ)
    try:
        tides = get_tides()
    except Exception as exc:  # the dashboard still renders without tides
        print("Tide error:", exc)
        tides = None
    generate_image(get_weather(), tides, now)


if __name__ == "__main__":
    main()
