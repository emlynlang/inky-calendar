"""Weather + tide dashboard picture for a Pimoroni Inky Frame 7.3".

HOW IT FITS TOGETHER
    GitHub Actions runs this script every 30 minutes. It downloads the weather
    and tide forecast (both free, no account needed), draws an 800 x 480 picture,
    and saves it as dashboard.jpg in the repo. The Inky Frame then downloads that
    picture and shows it (see the Pico's main.py).

    The red "you are here" marker on the tide chart is NOT part of the picture.
    GitHub can be hours late, so a marker baked into the picture could be hours
    out. Instead this script also writes dashboard.json, which describes where the
    tide curve is on screen, and the Pico draws the marker itself using its own clock.

WHY THE PICTURE LOOKS THE WAY IT DOES
    The e-ink panel can only print seven pure inks: black, white, green, blue,
    red, yellow and orange. Anything else (greys, pastels, soft edges) turns into
    a speckle of dots. So the whole picture is drawn in those seven colours only:
      * text and shapes have hard, un-blurred edges (no anti-aliasing blends)
      * icons are cartoon-style with black outlines
      * the "light blue" tide fill is thin blue stripes on white
    Every pixel is snapped to the nearest ink at the very end as a safety net.

SETTINGS (environment variables, all optional; unset or empty uses the default)
    LATITUDE, LONGITUDE   where the weather is for        (default: Dromore West)
    TIMEZONE              e.g. Europe/Dublin              (default: Europe/Dublin)
    TIDE_LATITUDE, TIDE_LONGITUDE
                          a point in the SEA for the tide forecast. The tide model
                          has no data over land, so this is a spot just offshore.

FILE LAYOUT (top to bottom)
    1. Settings and colours      4. Weather and tide data
    2. Layout positions          5. Icons and the moon
    3. Fonts and text drawing    6. Drawing the dashboard, then main()
"""
import datetime
import json
import math
import os
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageChops, ImageDraw, ImageFont

# =============================================================================
# 1. SETTINGS AND COLOURS
# =============================================================================
LAT = (os.environ.get("LATITUDE") or "54.24").strip()
LON = (os.environ.get("LONGITUDE") or "-8.80").strip()
TZ_NAME = (os.environ.get("TIMEZONE") or "Europe/Dublin").strip()
TZ = ZoneInfo(TZ_NAME)

# Approximate offshore spot just north of Dromore West (override with the
# TIDE_LATITUDE / TIDE_LONGITUDE variables if the tide times look wrong).
TIDE_LAT = (os.environ.get("TIDE_LATITUDE") or "54.33").strip()
TIDE_LON = (os.environ.get("TIDE_LONGITUDE") or "-8.85").strip()

OUTPUT_PATH = "dashboard.jpg"
SIDECAR_PATH = "dashboard.json"   # tells the Pico where the tide curve is (see header)
W, H = 800, 480  # the Inky Frame 7.3" screen size in pixels

# The seven inks. The values are deliberately far apart from each other so the
# Pico always maps each one to the right ink.
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GREEN = (30, 140, 70)
BLUE = (30, 50, 190)
RED = (190, 30, 30)
YELLOW = (255, 235, 40)
ORANGE = (230, 120, 30)
INKS = [BLACK, WHITE, GREEN, BLUE, RED, YELLOW, ORANGE]

# Roughly what those inks really look like on the (muted) panel. Used only to
# make the optional preview picture, never for the real image.
PANEL_LOOK = [(38, 34, 46), (222, 224, 216), (66, 106, 82), (58, 68, 128),
              (168, 66, 76), (214, 192, 86), (196, 126, 88)]

# =============================================================================
# 2. LAYOUT POSITIONS (pixels from the top-left corner)
# =============================================================================
DIVIDER_X = 320    # vertical line: left column | tide chart and forecast
DIVIDER_Y = 300    # horizontal line: tide chart | forecast
LINE = 3           # thickness of the divider lines

TIDE_BOX = (334, 10, 786, 292)        # (left, top, right, bottom) of the tide chart
PANEL_BOX = (12, 312, 308, 470)       # bottom-left box: moon at night, next tides by day

FORECAST_X = 332       # left edge of the first forecast card
FORECAST_STEP = 94     # distance from one card to the next
FORECAST_CARD_W = 88
FORECAST_TOP, FORECAST_BOTTOM = 312, 470

TIDE_HATCH_GAP = 9     # pixels between the stripes under the tide curve (bigger = lighter)

# =============================================================================
# 3. FONTS AND TEXT DRAWING
# =============================================================================
_FONT_CACHE = {}


def font(size, bold=False):
    """Return a font of the given pixel size.

    Prefers Inter (downloaded by get_fonts.sh); if that isn't there, falls back
    to DejaVu Sans (already installed on GitHub's Ubuntu runners), then to
    Pillow's built-in font, so a missing download never breaks the build.
    """
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
                _make_bold(f)
            break
        except (OSError, ValueError):
            continue  # that font file isn't available; try the next one
    if f is None:
        f = ImageFont.load_default(size)
    _FONT_CACHE[key] = f
    return f


def _make_bold(f):
    """Inter is a "variable" font: push its Weight setting up for bold text."""
    try:
        axes = f.get_variation_axes()
        values = [a["default"] for a in axes]
        for i, a in enumerate(axes):
            if a["name"] in (b"Weight", "Weight"):
                values[i] = 800
        f.set_variation_by_axes(values)
    except Exception:
        pass  # not a variable font: it is used as it is


class PixelDraw:
    """Like Pillow's ImageDraw, but text is drawn WITHOUT anti-aliasing.

    Normal text has soft grey edges. On this panel those would turn into stray
    coloured dots, so each letter is drawn as a mask and every pixel is either
    fully inked or not inked at all. Everything else (lines, boxes, circles)
    is passed straight through to ImageDraw, which already has hard edges.
    """

    def __init__(self, img):
        self.img = img
        self.d = ImageDraw.Draw(img)

    def __getattr__(self, name):
        return getattr(self.d, name)  # rectangle(), line(), textlength(), ...

    def text(self, xy, s, font=None, fill=BLACK, anchor="la", **_):
        # Work out the box the text will occupy, with a little spare room.
        l, t, r, b = self.d.textbbox(xy, s, font=font, anchor=anchor)
        l, t, r, b = int(l) - 2, int(t) - 2, int(r) + 3, int(b) + 3
        # Draw the text (soft edges) into a grey mask, then make it hard-edged:
        # a pixel counts as "ink" if it is at least ~40% covered.
        mask = Image.new("L", (r - l, b - t), 0)
        ImageDraw.Draw(mask).text((xy[0] - l, xy[1] - t), s, font=font, fill=255, anchor=anchor)
        mask = mask.point(lambda v: 255 if v >= 100 else 0)
        self.img.paste(fill, (l, t, r, b), mask)


def _fit_size(d, s, bold, max_w, start):
    """Largest font size (<= start) at which the text s fits in max_w pixels."""
    size = start
    while size > 10 and d.textlength(s, font=font(size, bold)) > max_w:
        size -= 1
    return size


# =============================================================================
# 4. WEATHER AND TIDE DATA
# =============================================================================
def get_weather():
    """Current weather plus a 5-day forecast from Open-Meteo (free, no key)."""
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": LAT,
            "longitude": LON,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
                       "weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max,sunrise,sunset",
            "timezone": TZ_NAME,   # so sunrise/sunset come back in local time
            "forecast_days": 5,
            "wind_speed_unit": "kmh",
        },
        timeout=20,
    )
    r.raise_for_status()
    return r.json()


def describe(code):
    """Turn Open-Meteo's numeric weather code into words."""
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


def get_tides():
    """Hourly sea level (metres, tides included) for today and tomorrow.

    Returns a list of (datetime, metres). It comes from Open-Meteo's marine
    model, which is coarse (about 8 km) and less accurate close to the coast,
    so treat the times as approximate. Heights are measured from mean sea level,
    not from the "chart datum" used on printed tide tables, which is why the
    dashboard shows times but not heights.
    """
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


def _catmull_rom(p0, p1, p2, p3, t):
    """Smooth value between p1 and p2 (t runs 0 to 1), using the points either side."""
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)


def _smooth_curve(pts, step=0.1):
    """Turn hourly points [(hour, metres)] into a smooth curve with a point every 6 minutes."""
    out, n = [], len(pts)
    for i in range(n - 1):
        p0, p1 = pts[max(i - 1, 0)][1], pts[i][1]
        p2, p3 = pts[i + 1][1], pts[min(i + 2, n - 1)][1]
        h0, h1 = pts[i][0], pts[i + 1][0]
        k = max(1, int(round((h1 - h0) / step)))
        for j in range(k):
            out.append((h0 + (h1 - h0) * j / k, _catmull_rom(p0, p1, p2, p3, j / k)))
    out.append(pts[-1])
    return out


def find_extrema(series):
    """Find the high and low tides: a list of (datetime, 'H' or 'L').

    A tide peak is an hourly point that is higher than the one before it and not
    lower than the one after (a low is the reverse). The exact time is then
    refined to between the hourly points by fitting a parabola through three
    neighbouring points.
    """
    out = []
    for i in range(1, len(series) - 1):
        a, b, c = series[i - 1][1], series[i][1], series[i + 1][1]
        if (b > a and b >= c) or (b < a and b <= c):
            den = a - 2 * b + c
            off = max(-1.0, min(1.0, 0.5 * (a - c) / den)) if den else 0.0
            out.append((series[i][0] + datetime.timedelta(hours=off), "H" if b > a else "L"))
    return out


def moon_phase(now):
    """Where the moon is in its cycle: 0 = new, 0.25 = first quarter, 0.5 = full, 0.75 = last quarter.

    Counts days since a known new moon (6 Jan 2000, 18:14 UTC) and divides by
    the average length of a lunar cycle (29.53 days).
    """
    utc = now.astimezone(datetime.timezone.utc)
    known_new_moon = datetime.datetime(2000, 1, 6, 18, 14, tzinfo=datetime.timezone.utc)
    days = (utc - known_new_moon).total_seconds() / 86400.0
    return (days / 29.530588853) % 1.0


def moon_name(p):
    """Name of the phase for a moon_phase() value."""
    for limit, name in ((0.03, "New Moon"), (0.22, "Waxing Crescent"), (0.28, "First Quarter"),
                        (0.47, "Waxing Gibbous"), (0.53, "Full Moon"), (0.72, "Waning Gibbous"),
                        (0.78, "Last Quarter"), (0.97, "Waning Crescent")):
        if p < limit:
            return name
    return "New Moon"


# =============================================================================
# 5. ICONS AND THE MOON
# =============================================================================
# Icons are cartoon-style: flat ink colours with a black outline. To get smooth
# curves without blurred edges, each icon is drawn 4x larger on a see-through
# layer and then shrunk, keeping the MOST COMMON colour in each 4x4 block
# (a normal resize would blend colours, which the panel can't show).
SS = 4  # how many times larger the icons are drawn before shrinking


def _shrink(layer, ss):
    """Shrink an RGBA layer by ss, picking the most common colour in each block."""
    w, h = layer.size[0] // ss, layer.size[1] // ss
    src = layer.load()
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dst = out.load()
    for y in range(h):
        for x in range(w):
            counts = {}
            for j in range(ss):
                for i in range(ss):
                    p = src[x * ss + i, y * ss + j]
                    counts[p] = counts.get(p, 0) + 1
            best = max(counts, key=counts.get)
            if best[3]:  # leave fully see-through blocks empty
                dst[x, y] = best
    return out


def _outline_width(s):
    """Thickness of an icon's black outline for an icon of size s."""
    return max(1.6 * SS, .05 * s)


def _circle(d, x, y, r, fill):
    d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _outlined_disc(d, x, y, r, fill, ow):
    _circle(d, x, y, r + ow, BLACK)
    _circle(d, x, y, r, fill)


def _cloud(d, cx, cy, s, fill, grow=0):
    """A cloud shape: three round puffs on a flat base. `grow` fattens it (for outlines)."""
    _circle(d, cx - .30 * s, cy + .06 * s, .27 * s + grow, fill)
    _circle(d, cx + .02 * s, cy - .14 * s, .36 * s + grow, fill)
    _circle(d, cx + .36 * s, cy + .08 * s, .25 * s + grow, fill)
    d.rectangle([cx - .30 * s, cy - .02 * s, cx + .36 * s, cy + .33 * s + grow], fill=fill)


def _outlined_cloud(d, cx, cy, s, fill):
    _cloud(d, cx, cy, s, BLACK, grow=_outline_width(s))   # black outline first...
    _cloud(d, cx, cy, s, fill)                            # ...then the coloured cloud on top


def _cloud_pair(d, cx, cy, s):
    """A blue cloud peeking out from behind a white one (used for rain, snow, overcast...)."""
    _outlined_cloud(d, cx - .32 * s, cy - .30 * s, .82 * s, BLUE)   # darker cloud behind
    _outlined_cloud(d, cx + .04 * s, cy + .04 * s, s, WHITE)         # white cloud in front


def _sun(d, cx, cy, s):
    """Orange disc with eight black rays."""
    r = .42 * s
    for k in range(8):
        a = k * math.pi / 4
        d.line([(cx + math.cos(a) * (r + .2 * s), cy + math.sin(a) * (r + .2 * s)),
                (cx + math.cos(a) * (r + .45 * s), cy + math.sin(a) * (r + .45 * s))],
               fill=BLACK, width=int(max(2 * SS, .07 * s)))
    _outlined_disc(d, cx, cy, r, ORANGE, _outline_width(s))


def _drop(d, x, y, r):
    """A raindrop: a round bottom with a pointed top."""
    d.polygon([(x, y - 2.1 * r), (x - .92 * r, y - .45 * r), (x + .92 * r, y - .45 * r)], fill=BLUE)
    _circle(d, x, y, r, BLUE)


def _icon_fn(code, night=False):
    """Pick the drawing function for a weather code.

    Every drawing function takes (layer, d, cx, cy, s): the see-through layer,
    a drawing tool for it, the icon's centre and its size.
    """
    def clear(layer, d, cx, cy, s):
        if not night:
            _sun(d, cx, cy, s)
            return
        # Night: a yellow crescent moon, outlined all the way round. It is a big
        # disc with a smaller disc cut out of it; the outline is the same shape grown.
        w, h = layer.size
        r, rc, ow = .5 * s, .42 * s, _outline_width(s)
        cut_x, cut_y = cx + .26 * s, cy - .14 * s

        def disc(x, y, rad):
            m = Image.new("L", (w, h), 0)
            ImageDraw.Draw(m).ellipse([x - rad, y - rad, x + rad, y + rad], fill=255)
            return m
        black = ImageChops.subtract(disc(cx, cy, r + ow), disc(cut_x, cut_y, rc))
        yellow = ImageChops.subtract(disc(cx, cy, r), disc(cut_x, cut_y, rc + ow))
        layer.paste(BLACK + (255,), (0, 0, w, h), black)
        layer.paste(YELLOW + (255,), (0, 0, w, h), yellow)

    def partly_cloudy(layer, d, cx, cy, s):
        _sun(d, cx + .24 * s, cy - .26 * s, .8 * s)
        _outlined_cloud(d, cx - .06 * s, cy + .14 * s, .92 * s, WHITE)

    def overcast(layer, d, cx, cy, s):
        _cloud_pair(d, cx, cy + .12 * s, s)

    def fog(layer, d, cx, cy, s):
        h = .14 * s
        for i in range(4):  # four staggered blue bars
            y = cy - .36 * s + i * .26 * s
            x = cx - .5 * s + (i % 2) * .12 * s
            d.rounded_rectangle([x, y, x + .8 * s, y + h], radius=h / 2, fill=BLUE)

    def rain(heavy):
        def draw(layer, d, cx, cy, s):
            _cloud_pair(d, cx, cy - .14 * s, s)
            r = max(.085 * s, 2.2 * SS)
            for row in range(3 if heavy else 2):
                n = 4 if row % 2 == 0 else 3
                for i in range(n):
                    x = cx - .34 * s + i * (.68 * s / 3) + (row % 2) * .11 * s
                    _drop(d, x, cy + .52 * s + row * .24 * s, r)
        return draw

    def snow(layer, d, cx, cy, s):
        _cloud_pair(d, cx, cy - .14 * s, s)
        for row in range(2):
            for i in range(4 - row):
                x = cx - .34 * s + i * (.68 * s / 3) + row * .11 * s
                _circle(d, x, cy + .54 * s + row * .24 * s, max(.08 * s, 2.2 * SS), BLUE)

    def thunder(layer, d, cx, cy, s):
        _cloud_pair(d, cx, cy - .14 * s, s)
        bolt = [(cx + a * s, cy + b * s) for a, b in
                [(.05, .26), (-.17, .60), (-.02, .58), (-.10, .92), (.20, .50), (.04, .52)]]
        d.polygon(bolt, fill=YELLOW)
        d.line(bolt + [bolt[0]], fill=BLACK, width=int(max(1.5 * SS, .04 * s)), joint="curve")

    # Open-Meteo "WMO" weather codes grouped by how they should look.
    if code in (0, 1):
        return clear
    if code == 2:
        return partly_cloudy
    if code in (45, 48):
        return fog
    if code in (51, 53, 55, 56, 57, 61, 63, 80, 81):
        return rain(heavy=False)
    if code in (65, 66, 67, 82):
        return rain(heavy=True)
    if code in (71, 73, 75, 77, 85, 86):
        return snow
    if code in (95, 96, 99):
        return thunder
    return overcast  # code 3, and anything unknown


def draw_icon(img, code, cx, cy, s, night=False):
    """Draw the weather icon for `code`, centred on (cx, cy), at size s."""
    box = int(s * 2.4)  # the see-through square the icon is drawn on
    layer = Image.new("RGBA", (box * SS, box * SS), (0, 0, 0, 0))
    _icon_fn(code, night)(layer, ImageDraw.Draw(layer), box * SS / 2, box * SS / 2, s * SS)
    small = _shrink(layer, SS)
    img.paste(small, (int(cx - box / 2), int(cy - box / 2)), small)


def draw_moon(img, cx, cy, r, p):
    """Draw the moon as seen from the northern hemisphere (waxing = right side lit).

    Designed for a black background: white rim, black unlit side, yellow lit side.
    The lit part is filled one row at a time. On each row, the terminator (the
    edge between light and dark) sits at width * cos(2*pi*phase) from the centre.
    """
    n = int(r * 2 + 8)
    layer = Image.new("RGBA", (n * SS, n * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c, R = n * SS / 2, r * SS
    R2 = R - 3 * SS                    # the lit/unlit disc sits inside the white rim
    _circle(d, c, c, R, WHITE)
    _circle(d, c, c, R2, BLACK)
    k = math.cos(2 * math.pi * p)
    for dy in range(-int(R2), int(R2) + 1):
        w = math.sqrt(max(0.0, R2 * R2 - dy * dy))   # half-width of the disc on this row
        t = w * k                                    # where the terminator crosses this row
        x0, x1 = (t, w) if p < 0.5 else (-w, -t)     # waxing: right side lit; waning: left
        if x1 > x0:
            d.line([(c + x0, c + dy), (c + x1, c + dy)], fill=YELLOW)
    small = _shrink(layer, SS)
    img.paste(small, (int(cx - n / 2), int(cy - n / 2)), small)


def _draw_sun_glyph(d, cx, cy, rising):
    """Small half-sun on a horizon line, with a red arrow up (sunrise) or down (sunset)."""
    d.pieslice([cx - 15, cy - 15, cx + 15, cy + 15], 180, 360, fill=ORANGE, outline=BLACK, width=2)
    d.line([(cx - 22, cy + 1), (cx + 22, cy + 1)], fill=BLACK, width=3)
    if rising:
        arrow = [(cx, cy - 31), (cx - 8, cy - 19), (cx + 8, cy - 19)]
    else:
        arrow = [(cx, cy - 19), (cx - 8, cy - 31), (cx + 8, cy - 31)]
    d.polygon(arrow, fill=RED, outline=BLACK)


# =============================================================================
# 6. DRAWING THE DASHBOARD
# =============================================================================
# Screen map:
#     +----------------+--------------------------------+
#     | date           |                                |
#     | weather (big)  |        tide chart              |
#     | sunrise/sunset |                                |
#     +----------------+                                |
#     | moon (night)   +--------------------------------+
#     | next tides     |  5-day forecast (5 cards)      |
#     +----------------+--------------------------------+

def _draw_header(d, now):
    """Today's date, top left, in red."""
    text = now.strftime("%A, %d %b")
    size = _fit_size(d, text, True, 284, 28)
    d.text((24, 10), text, font=font(size, True), fill=RED)


def _draw_current_weather(img, d, weather, is_night):
    """Big icon and temperature, then the description and the feels-like/wind/humidity lines."""
    cur = weather["current"]
    code = cur["weather_code"]
    draw_icon(img, code, 82, 124, 68, night=is_night)

    temp = "%d°C" % round(cur["temperature_2m"])
    d.text((152, 56), temp, font=font(_fit_size(d, temp, True, 160, 78), True), fill=BLACK)

    desc = describe(code)
    d.text((154, 148), desc, font=font(_fit_size(d, desc, True, 158, 24), True), fill=BLACK)

    d.text((26, 184), "Feels like %d°   Wind %d km/h" % (
        round(cur["apparent_temperature"]), round(cur["wind_speed_10m"])),
        font=font(16, True), fill=BLACK)
    d.text((26, 206), "Humidity %d%%" % round(cur["relative_humidity_2m"]),
           font=font(16, True), fill=BLACK)


def _draw_sun_times(d, sunrise, sunset):
    """Sunrise and sunset times with their little half-sun symbols."""
    _draw_sun_glyph(d, 38, 268, rising=True)
    d.text((72, 240), "Sunrise", font=font(15, True), fill=BLACK)
    d.text((72, 258), sunrise.strftime("%H:%M"), font=font(24, True), fill=BLACK)
    _draw_sun_glyph(d, 182, 268, rising=False)
    d.text((216, 240), "Sunset", font=font(15, True), fill=BLACK)
    d.text((216, 258), sunset.strftime("%H:%M"), font=font(24, True), fill=BLACK)


def _draw_moon_panel(img, d, now):
    """Night: the moon phase on a black panel."""
    x0, y0, x1, y1 = PANEL_BOX
    d.rounded_rectangle(PANEL_BOX, radius=14, fill=BLACK, outline=BLACK, width=3)
    p = moon_phase(now)
    draw_moon(img, 82, 391, 54, p)
    words = moon_name(p).split(" ")      # e.g. "Waxing" / "Gibbous" on two lines
    for i, word in enumerate(words):
        d.text((158, 346 + i * 28), word, font=font(22, True), fill=WHITE)
    lit = (1 - math.cos(2 * math.pi * p)) / 2 * 100   # percentage of the disc that is lit
    d.text((158, 346 + len(words) * 28 + 6), "%d%% lit" % round(lit),
           font=font(17, True), fill=YELLOW)


def _draw_next_tides_panel(d, tides, now):
    """Daytime: the next high tide and next low tide, soonest first."""
    d.rounded_rectangle(PANEL_BOX, radius=14, fill=WHITE, outline=BLACK, width=3)
    d.text((28, 324), "NEXT TIDES", font=font(16, True), fill=BLACK)

    upcoming = {}                          # {'H': next high time, 'L': next low time}
    for t, kind in find_extrema(tides or []):
        if t > now and kind not in upcoming:
            upcoming[kind] = t
    if not upcoming:
        d.text((28, 370), "Tide data unavailable", font=font(18, True), fill=BLACK)
        return
    for i, (kind, t) in enumerate(sorted(upcoming.items(), key=lambda kv: kv[1])):
        y = 358 + i * 50
        if kind == "H":    # blue triangle pointing up for high tide, down for low
            tri = [(44, y + 4), (33, y + 24), (55, y + 24)]
        else:
            tri = [(44, y + 24), (33, y + 4), (55, y + 4)]
        d.polygon(tri, fill=BLUE)
        name = "High" if kind == "H" else "Low"
        day = "" if t.date() == now.date() else " " + t.strftime("%a")   # e.g. " Sat" if tomorrow
        d.text((72, y), "%s %s%s" % (name, t.strftime("%H:%M"), day), font=font(22, True), fill=BLACK)


def _draw_tide_chart(img, d, series, now):
    """Today's tide as a smooth curve from midnight to midnight.

    Marked on it: high/low tide times (black dots with labels) and hour labels
    along the bottom. The red "now" marker is left for the Pico to draw.

    Returns a small dict describing where the curve is on screen (for the Pico),
    or None if there is no tide data.
    """
    x0, y0, x1, y1 = TIDE_BOX
    d.rounded_rectangle(TIDE_BOX, radius=10, outline=BLACK, width=3)
    d.text((x0 + 16, y0 + 9), "TIDES TODAY", font=font(16, True), fill=BLACK)

    # Express every data point as "hours since midnight today" (a little either side too).
    midnight = datetime.datetime.combine(now.date(), datetime.time(), tzinfo=TZ)

    def hours(t):
        return (t - midnight).total_seconds() / 3600.0

    pts = [(hours(t), v) for t, v in series or [] if -1.5 <= hours(t) <= 25.5]
    if len(pts) < 6:
        d.text((x0 + 16, y0 + 70), "Tide data unavailable", font=font(20, True), fill=BLACK)
        return None

    curve = [(h, v) for h, v in _smooth_curve(pts) if 0 <= h <= 24]

    # The drawing area inside the box, and how heights map onto it.
    px0, px1, py0, py1 = x0 + 20, x1 - 20, y0 + 58, y1 - 62
    low, high = min(v for _, v in curve), max(v for _, v in curve)
    span = max(high - low, 0.5)          # never squash a very small tide into a flat line

    def X(h):                            # hour -> x pixel
        return px0 + h / 24.0 * (px1 - px0)

    def Y(v):                            # metres -> y pixel (higher water = higher on screen)
        return py1 - (v - low) / span * (py1 - py0)

    def height_at(h):                    # curve height at hour h
        return min(curve, key=lambda p: abs(p[0] - h))[1]

    extrema = [(t, k) for t, k in find_extrema(series) if 0 <= hours(t) <= 24]

    # --- The curve, its striped fill and the high/low dots -------------------
    # Drawn 4x larger on a see-through layer, then shrunk by colour vote (see _shrink).
    pad = 10
    size = (((px1 - px0) + 2 * pad) * SS, ((py1 - py0) + 2 * pad) * SS)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)

    def L(x, y):                         # screen position -> position on the big layer
        return ((x - px0 + pad) * SS, (y - py0 + pad) * SS)

    line = [L(X(h), Y(v)) for h, v in curve]
    # Stripes: a mask of the area under the curve, intersected with a mask of vertical bars.
    under_curve = Image.new("L", size, 0)
    ImageDraw.Draw(under_curve).polygon(line + [L(X(24), py1), L(X(0), py1)], fill=255)
    bars = Image.new("L", size, 0)
    bd = ImageDraw.Draw(bars)
    for sx in range(0, size[0], TIDE_HATCH_GAP * SS):
        bd.rectangle([sx, 0, sx + 2 * SS - 1, size[1]], fill=255)
    layer.paste(BLUE + (255,), (0, 0) + size, ImageChops.darker(under_curve, bars))
    ld.line(line, fill=BLUE, width=5 * SS, joint="curve")
    for t, _ in extrema:
        cx, cy = L(X(hours(t)), Y(height_at(hours(t))))
        _circle(ld, cx, cy, 6 * SS, BLACK)
    small = _shrink(layer, SS)
    img.paste(small, (px0 - pad, py0 - pad), small)

    # --- Axis line, tick marks and hour labels --------------------------------
    d.line([(px0, py1 + 3), (px1, py1 + 3)], fill=BLACK, width=2)
    for hr in (0, 6, 12, 18, 24):
        d.line([(X(hr), py1 + 3), (X(hr), py1 + 9)], fill=BLACK, width=2)
        d.text((X(hr), y1 - 27), "%02d" % (hr % 24), font=font(15, True), fill=BLACK, anchor="ma")

    # --- Time labels for each high (above the dot) and low (below it) --------
    for t, kind in extrema:
        cx = min(max(X(hours(t)), px0 + 22), px1 - 22)     # keep the label inside the box
        y = Y(height_at(hours(t))) - 26 if kind == "H" else Y(height_at(hours(t))) + 9
        label, f = t.strftime("%H:%M"), font(16, True)
        l, top, r, bottom = d.textbbox((cx, y), label, font=f, anchor="ma")
        d.rectangle([l - 4, top - 2, r + 4, bottom + 3], fill=WHITE)   # white patch so stripes don't cross the text
        d.text((cx, y), label, font=f, fill=BLACK, anchor="ma")

    # --- Describe the chart so the Pico can draw the "now" marker -----------------
    # x runs linearly from x0 (midnight) to x1 (next midnight); ys holds the y pixel
    # of the curve for every 10 minutes of the day (145 values: 00:00, 00:10 ... 24:00).
    return {
        "x0": px0, "x1": px1,
        "top": py0 - 8, "bottom": py1 + 3,          # extent of the dashed line
        "ys": [int(round(Y(height_at(i / 6.0)))) for i in range(145)],
    }


def _draw_now_marker(d, marker, now_h):
    """Red dashed line and dot for the current time. The Pico draws the real one on
    the frame; this copy is only used for the preview picture."""
    x = marker["x0"] + now_h / 24.0 * (marker["x1"] - marker["x0"])
    for yy in range(marker["top"], marker["bottom"], 9):
        d.line([(x, yy), (x, yy + 5)], fill=RED, width=3)
    y = marker["ys"][int(round(now_h * 6))]
    d.ellipse([x - 9, y - 9, x + 9, y + 9], fill=BLACK)
    d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=RED)


def _draw_forecast(img, d, daily):
    """Five cards: day name, icon, high/low temperature and chance of rain."""
    for i in range(5):
        left = FORECAST_X + i * FORECAST_STEP
        cx = left + FORECAST_CARD_W // 2
        d.rounded_rectangle([left, FORECAST_TOP, left + FORECAST_CARD_W, FORECAST_BOTTOM],
                            radius=10, outline=BLACK, width=3)

        day = datetime.date.fromisoformat(daily["time"][i])
        label = "Today" if i == 0 else day.strftime("%a")
        d.text((cx, 319), label, font=font(17, True), fill=BLUE, anchor="ma")

        draw_icon(img, daily["weather_code"][i], cx + 2, 374, 31)

        hi, lo = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        d.text((cx, 413), "%d°/%d°" % (round(hi), round(lo)), font=font(18, True),
               fill=RED if hi >= 25 else BLACK, anchor="ma")     # red when it's warm (25 C or more)

        rain_chance = daily["precipitation_probability_max"][i]
        if rain_chance is not None:
            d.text((cx, 439), "%d%%" % rain_chance, font=font(16, True), fill=BLUE, anchor="ma")


def _palette_image(colours):
    """A 256-entry palette image holding just our colours (extra slots repeat the first)."""
    flat = [c for rgb in colours for c in rgb]
    p = Image.new("P", (1, 1))
    p.putpalette(flat + list(colours[0]) * (256 - len(colours)))
    return p


def snap_to_inks(img):
    """Force every pixel to the nearest of the seven inks (no dithering)."""
    return img.quantize(palette=_palette_image(INKS), dither=Image.Dither.NONE)


def generate_image(weather, tides, now, out_path=OUTPUT_PATH, preview_path=None,
                   sidecar_path=SIDECAR_PATH):
    """Draw the whole dashboard and save it.

    weather -- the dict from get_weather()
    tides   -- the list from get_tides(), or None if tides are unavailable
    now     -- the current time (timezone-aware)
    out_path -- where the real picture for the frame is saved (JPEG)
    preview_path -- optional: also save a PNG showing roughly how it will look
                    in the panel's muted colours (handy for checking on a computer),
                    including the "now" marker the Pico would add
    sidecar_path -- where to save dashboard.json (the tide-curve description)
    """
    img = Image.new("RGB", (W, H), WHITE)
    d = PixelDraw(img)

    daily = weather["daily"]
    sunrise = datetime.datetime.fromisoformat(daily["sunrise"][0]).replace(tzinfo=TZ)
    sunset = datetime.datetime.fromisoformat(daily["sunset"][0]).replace(tzinfo=TZ)
    is_night = now >= sunset or now < sunrise

    # Divider lines between the three areas.
    d.rectangle([DIVIDER_X, 0, DIVIDER_X + LINE - 1, H], fill=BLACK)
    d.rectangle([DIVIDER_X + LINE, DIVIDER_Y, W, DIVIDER_Y + LINE - 1], fill=BLACK)

    _draw_header(d, now)
    _draw_current_weather(img, d, weather, is_night)
    _draw_sun_times(d, sunrise, sunset)
    if is_night:
        _draw_moon_panel(img, d, now)          # after sunset: the moon phase
    else:
        _draw_next_tides_panel(d, tides, now)  # by day: the next high and low tide
    marker = _draw_tide_chart(img, d, tides, now)
    _draw_forecast(img, d, daily)

    # Snap every pixel to an ink and save as a baseline (non-progressive) JPEG,
    # which is what the Inky Frame's JPEG decoder expects.
    snapped = snap_to_inks(img)
    snapped.convert("RGB").save(out_path, "JPEG", quality=95, subsampling=0,
                                optimize=False, progressive=False)
    # The sidecar file: which day the tide curve is for, and where it is on screen.
    with open(sidecar_path, "w") as f:
        json.dump({"date": now.date().isoformat(),
                   "rendered": now.isoformat(timespec="minutes"),
                   "marker": marker}, f, separators=(",", ":"))

    if preview_path:
        shown = snapped.convert("RGB")
        if marker:
            midnight = datetime.datetime.combine(now.date(), datetime.time(), tzinfo=TZ)
            _draw_now_marker(PixelDraw(shown), marker, (now - midnight).total_seconds() / 3600.0)
        look = snap_to_inks(shown)
        look.putpalette([c for rgb in PANEL_LOOK for c in rgb] + list(PANEL_LOOK[0]) * (256 - 7))
        look.convert("RGB").save(preview_path)


def main():
    """Fetch the data, draw the picture, save it. This is what GitHub Actions runs."""
    now = datetime.datetime.now(TZ)
    try:
        tides = get_tides()
    except Exception as exc:   # the dashboard still draws without tides
        print("Tide error:", exc)
        tides = None
    generate_image(get_weather(), tides, now)


if __name__ == "__main__":
    main()
