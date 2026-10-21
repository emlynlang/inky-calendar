"""Renders an 800x480 weather + calendar dashboard (dashboard.jpg) for a
Pimoroni Inky Frame 7.3". Run by the GitHub Actions workflow every 30 minutes.

Environment variables (all optional; unset or empty falls back to a default):
  CALENDAR_URL  secret ICS feed URL (e.g. Google Calendar "secret address in iCal format")
  LATITUDE / LONGITUDE  location, default Dromore West
  TIMEZONE      IANA timezone, default Europe/Dublin
"""
import datetime
import math
import os
import re
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

# ------------------------------------------------------------------ config
CALENDAR_URL = (os.environ.get("CALENDAR_URL") or "").strip()
LAT = (os.environ.get("LATITUDE") or "54.24").strip()
LON = (os.environ.get("LONGITUDE") or "-8.80").strip()
TZ_NAME = (os.environ.get("TIMEZONE") or "Europe/Dublin").strip()
TZ = ZoneInfo(TZ_NAME)
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


# ------------------------------------------------------------------ calendar (ICS)
def _unescape(s):
    return s.replace("\\n", " ").replace("\\N", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _prop(line):
    head, _, value = line.partition(":")
    parts = head.split(";")
    params = {}
    for p in parts[1:]:
        k, _, v = p.partition("=")
        params[k.upper()] = v.strip('"')
    return parts[0].upper(), params, value


def _dt(value, params):
    """-> (aware datetime in TZ, is_all_day)"""
    value = value.strip()
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return datetime.datetime.strptime(value[:8], "%Y%m%d").replace(tzinfo=TZ), True
    if value.endswith("Z"):
        dt = datetime.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
        return dt.astimezone(TZ), False
    dt = datetime.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    zone = TZ
    if "TZID" in params:
        try:
            zone = ZoneInfo(params["TZID"])
        except Exception:
            pass  # unknown zone name (e.g. Outlook "GMT Standard Time"): assume local
    return dt.replace(tzinfo=zone).astimezone(TZ), False


_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _parse_events(text):
    text = re.sub(r"\r?\n[ \t]", "", text)  # unfold
    events, cur = [], None
    for line in text.splitlines():
        if line == "BEGIN:VEVENT":
            cur = {"EXDATE": []}
        elif line == "END:VEVENT":
            if cur is not None and "DTSTART" in cur:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            name, params, value = _prop(line)
            if name == "EXDATE":
                for v in value.split(","):
                    try:
                        cur["EXDATE"].append(_dt(v, params)[0].date())
                    except ValueError:
                        pass
            elif name in ("DTSTART", "DTEND", "RECURRENCE-ID"):
                try:
                    cur[name] = _dt(value, params)
                except ValueError:
                    pass
            elif name in ("SUMMARY", "RRULE", "UID", "STATUS"):
                cur[name] = _unescape(value)
    return events


def _rule_matches(day, start_date, rule):
    """Does a recurrence rule produce an occurrence on `day`? (DAILY/WEEKLY/MONTHLY/YEARLY)"""
    if day < start_date:
        return False
    interval = int(rule.get("INTERVAL", 1))
    freq = rule.get("FREQ")
    if freq == "DAILY":
        return (day - start_date).days % interval == 0
    if freq == "WEEKLY":
        wanted = [_DAYS.index(x[-2:]) for x in rule["BYDAY"].split(",")] if "BYDAY" in rule \
            else [start_date.weekday()]
        weeks = ((day - datetime.timedelta(days=day.weekday())) -
                 (start_date - datetime.timedelta(days=start_date.weekday()))).days // 7
        return day.weekday() in wanted and weeks % interval == 0
    if freq == "MONTHLY":
        if "BYDAY" in rule:      # e.g. "2nd Tuesday": not supported
            return False
        months = (day.year - start_date.year) * 12 + day.month - start_date.month
        return day.day == start_date.day and months % interval == 0
    if freq == "YEARLY":
        return (day.month, day.day) == (start_date.month, start_date.day) and \
            (day.year - start_date.year) % interval == 0
    return False


def events_for_day(text, day):
    """Return [(sort_key, 'HH:MM' or 'All day', title)] for the given date."""
    events = _parse_events(text)
    overridden = {(e.get("UID"), e["RECURRENCE-ID"][0].date()) for e in events if "RECURRENCE-ID" in e}
    day_start = datetime.datetime.combine(day, datetime.time(), tzinfo=TZ)
    day_end = day_start + datetime.timedelta(days=1)
    out = []
    for e in events:
        if e.get("STATUS", "").upper() == "CANCELLED":
            continue
        start, all_day = e["DTSTART"]
        title = e.get("SUMMARY", "(no title)")
        if "RRULE" in e and "RECURRENCE-ID" not in e:
            rule = dict(p.split("=", 1) for p in e["RRULE"].split(";") if "=" in p)
            if day in e["EXDATE"] or (e.get("UID"), day) in overridden:
                continue
            if "UNTIL" in rule:
                try:
                    if day > _dt(rule["UNTIL"], {})[0].date():
                        continue
                except ValueError:
                    pass
            if not _rule_matches(day, start.date(), rule):
                continue
            if "COUNT" in rule:
                n, d0 = 0, start.date()
                while d0 <= day:
                    n += _rule_matches(d0, start.date(), rule) and d0 not in e["EXDATE"]
                    d0 += datetime.timedelta(days=1)
                if n > int(rule["COUNT"]):
                    continue
            occ = datetime.datetime.combine(day, start.timetz().replace(tzinfo=None), tzinfo=TZ)
            out.append((occ if not all_day else day_start, "All day" if all_day else occ.strftime("%H:%M"), title, all_day))
            continue
        end = e["DTEND"][0] if "DTEND" in e else start
        if not (start < day_end and max(end, start + datetime.timedelta(seconds=1)) > day_start):
            continue
        out.append((start if not all_day else day_start, "All day" if all_day else
                    ("00:00" if start < day_start else start.strftime("%H:%M")), title, all_day))
    out.sort(key=lambda x: (not x[3], x[0]))
    return [(label, title) for _, label, title, _ in out]


def get_events(day):
    """Today's events from CALENDAR_URL. Returns (events, error_message_or_None)."""
    if not CALENDAR_URL:
        return [], "No calendar linked"
    try:
        r = requests.get(CALENDAR_URL, timeout=20)
        r.raise_for_status()
        return events_for_day(r.text, day), None
    except Exception as exc:  # keep the dashboard alive if the calendar is down
        print("Calendar error:", exc)
        return [], "Calendar unavailable"


# ------------------------------------------------------------------ drawing
def generate_image(weather, events, cal_error, now, out_path=OUTPUT_PATH):
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    cur, daily = weather["current"], weather["daily"]
    sunrise = datetime.datetime.fromisoformat(daily["sunrise"][0]).replace(tzinfo=TZ)
    sunset = datetime.datetime.fromisoformat(daily["sunset"][0]).replace(tzinfo=TZ)
    is_night = now >= sunset or now < sunrise

    # layout lines
    d.rectangle([320, 0, 321, H], fill=BLACK)
    d.rectangle([322, 300, W, 301], fill=BLACK)

    # clock and date
    d.text((24, 6), now.strftime("%H:%M"), font=font(86, True), fill=BLACK)
    d.text((26, 104), now.strftime("%A, %d %b"), font=font(24), fill=RED)

    # current weather
    code = cur["weather_code"]
    draw_icon(img, code, 72, 200, 54, night=is_night)
    d.text((140, 160), "%d°C" % round(cur["temperature_2m"]), font=font(52, True), fill=BLACK)
    d.text((142, 222), describe(code), font=font(18), fill=BLACK)
    d.text((26, 262), "Feels %d°  ·  Humidity %d%%  ·  %d km/h" % (
        round(cur["apparent_temperature"]), round(cur["relative_humidity_2m"]),
        round(cur["wind_speed_10m"])), font=font(14), fill=GREY)

    # bottom-left panel: moon after sunset, sun times by day
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
        draw_icon(img, 0, 76, 391, 46)
        d.text((140, 352), "Sunrise  " + sunrise.strftime("%H:%M"), font=font(18, True), fill=BLACK)
        d.text((140, 386), "Sunset   " + sunset.strftime("%H:%M"), font=font(18, True), fill=BLACK)

    # agenda
    d.text((344, 20), "TODAY'S SCHEDULE", font=font(20, True), fill=BLACK)
    d.rectangle([344, 54, 780, 56], fill=RED)
    if events:
        for i, (label, title) in enumerate(events[:6]):
            y = 72 + i * 36
            d.ellipse([344, y + 7, 354, y + 17], fill=RED)
            d.text((364, y), label, font=font(18, True), fill=BLACK)
            d.text((448, y), fit(d, title, font(18), 780 - 448), font=font(18), fill=BLACK)
        if len(events) > 6:
            d.text((344, 72 + 6 * 36 - 4), "+%d more" % (len(events) - 6), font=font(14), fill=GREY)
    else:
        d.text((344, 76), cal_error or "Nothing scheduled today", font=font(18), fill=GREY)

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
    events, cal_error = get_events(now.date())
    generate_image(get_weather(), events, cal_error, now)


if __name__ == "__main__":
    main()
