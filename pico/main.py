"""Inky Frame 7.3" (Pico W): download the dashboard picture and show it.

WHAT THIS PROGRAM DOES, STEP BY STEP
    1. Connects to your Wi-Fi.
    2. Asks the internet for the exact time (the Pico has no clock of its own
       that survives a restart).
    3. Downloads dashboard.jpg from your GitHub repo (a GitHub Action keeps it
       up to date), plus dashboard.json, a small file saying where the tide
       curve is on the picture.
    4. Checks the download really is a JPEG picture.
    5. Draws it on the e-ink screen, then adds the red "you are here" marker
       on the tide chart using the exact time from step 2.
    6. Waits 30 minutes, then starts again.

WHY THE RED MARKER IS DRAWN HERE
    GitHub's schedule can run hours late. If the marker were part of the
    picture it could be hours out. Drawn here, it is right every time the
    screen refreshes, even when the picture itself is a little old.

IF SOMETHING GOES WRONG
    * No Wi-Fi, GitHub down, or a broken file: the screen is left exactly as it
      was, the orange warning light comes on, and it tries again in 10 minutes.
      A failed update can never blank the display.
    * Only the time or the marker file is missing: the picture is still shown,
      just without the red marker.
    * The program FREEZES (for example the Wi-Fi drops half way through a
      download and the Pico waits forever): a safety timer restarts the Pico
      after 5 minutes. Without it a frozen frame stays frozen, with the green
      "busy" light on, until you switch it off and on by hand.

SETUP
    Put this file (named main.py) and secrets.py on the Pico, with Pimoroni's
    MicroPython firmware for the Inky Frame installed. The Pico runs main.py
    automatically every time it starts.

HOW TO READ THIS FILE
    Lines starting with # are notes for humans; the Pico ignores them. A "def"
    line starts a function: a named bundle of steps that other parts of the
    program can use. The very last line, main(), is what actually starts things.
"""
# ------------------------------------------------------------------ tools we borrow
# "import" loads a ready-made toolbox. These all come with the Pimoroni firmware.
import machine        # control of the Pico itself (we use it to restart)
import os             # deleting and renaming files
import time           # clock, waiting

import inky_frame     # the frame's lights and its sleep timer
import jpegdec        # turns a JPEG file into dots on the screen
import network        # Wi-Fi
import urequests      # downloads things from the internet
from picographics import PicoGraphics, DISPLAY_INKY_FRAME_7 as DISPLAY   # drawing on the screen

# Your Wi-Fi name and password, and the picture's web address, live in secrets.py.
from secrets import WIFI_SSID, WIFI_PASSWORD, IMAGE_URL

# ------------------------------------------------------------------ settings you may change
UPDATE_MINUTES = 30   # how often to fetch a fresh picture (e-ink wears with very frequent redraws)
RETRY_MINUTES = 10    # how long to wait before trying again after a failure

# If one whole update (Wi-Fi, download, drawing the screen) takes longer than this,
# the program has frozen, so the Pico restarts itself. A normal update takes about
# a minute, so 5 is very generous.
UPDATE_TIME_LIMIT_MINUTES = 5

IMAGE_FILE = "/dashboard.jpg"        # where the current picture is stored on the Pico
TEMP_FILE = "/dashboard_new.jpg"     # a download is saved here first, so a half-finished
                                     # download never replaces a good picture

# The small file describing the tide curve sits next to the picture on GitHub.
# This takes the picture's address and swaps "dashboard.jpg" for "dashboard.json".
JSON_URL = IMAGE_URL.rsplit("/", 1)[0] + "/dashboard.json"

# Your local time. Ireland and the UK are on UTC+0 in winter and UTC+1 in summer
# ("European summer time": from 01:00 UTC on the last Sunday of March until
# 01:00 UTC on the last Sunday of October). Change these two if you move.
# They only affect where the red marker is drawn, not the picture itself.
UTC_OFFSET_HOURS = 0      # winter offset from UTC
EU_SUMMER_TIME = True     # add one hour in the European summer period

# Pen numbers for the Inky Frame's seven inks (only the two we draw with).
INK_BLACK = 0
INK_RED = 4


# ------------------------------------------------------------------ Wi-Fi and the clock
def connect():
    """Join the Wi-Fi. Returns True if connected (gives up after about 30 seconds)."""
    wlan = network.WLAN(network.STA_IF)    # the Pico's Wi-Fi hardware, in "join a network" mode
    wlan.active(True)                      # switch it on
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(30):               # check once a second, up to 30 times
            if wlan.isconnected():
                break
            time.sleep(1)
    return wlan.isconnected()


def set_clock():
    """Set the Pico's clock from the internet. Returns True if it worked.

    The time is stored in UTC (the same everywhere in the world); local_time()
    below turns it into your local time.
    """
    try:
        import ntptime                    # "NTP" = the internet's time service
    except ImportError:
        return False
    for _ in range(3):                    # network time can occasionally fail; try a few times
        try:
            ntptime.settime()
            return True
        except Exception:
            time.sleep(1)
    return False


def _weekday(y, m, d):
    """Day of the week for a date: 0 = Monday ... 6 = Sunday.

    (Standard calendar maths, so we do not need a calendar library.)
    """
    t = (0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4)
    if m < 3:
        y -= 1
    sunday_first = (y + y // 4 - y // 100 + y // 400 + t[m - 1] + d) % 7   # 0 = Sunday
    return (sunday_first + 6) % 7


def _last_sunday(y, m):
    """Date (day of the month) of the last Sunday in a 31-day month (March or October)."""
    return 31 - ((_weekday(y, m, 31) + 1) % 7)


def is_summer_time(y, m, d, h):
    """True if the given UTC date and hour fall in European summer time."""
    if m < 3 or m > 10:
        return False                      # November to February: winter
    if 3 < m < 10:
        return True                       # April to September: summer
    switch = (_last_sunday(y, m), 1)      # both clock changes happen at 01:00 UTC
    if m == 3:
        return (d, h) >= switch           # clocks went forward
    return (d, h) < switch                # October: clocks go back


def local_time():
    """Your local date and time as ("2026-10-24", 12.5), where 12.5 means 12:30.

    Returns None if the clock couldn't be set (so no wrong marker is ever drawn).
    """
    secs = time.time()                    # seconds since 2000 (in UTC)
    y, m, d, h = time.gmtime(secs)[:4]
    offset = UTC_OFFSET_HOURS + (1 if EU_SUMMER_TIME and is_summer_time(y, m, d, h) else 0)
    t = time.gmtime(secs + offset * 3600)  # shift to local time
    return "%04d-%02d-%02d" % (t[0], t[1], t[2]), t[3] + t[4] / 60 + t[5] / 3600


# ------------------------------------------------------------------ downloading
def download():
    """Download the picture, check it, and only then replace the stored one."""
    r = urequests.get(IMAGE_URL)                      # ask GitHub for the picture
    try:
        if r.status_code != 200:                      # 200 means "OK"
            raise RuntimeError("HTTP %d" % r.status_code)
        size = 0
        with open(TEMP_FILE, "wb") as f:
            while True:                               # read in small pieces: the Pico has little memory
                chunk = r.raw.read(2048)
                if not chunk:
                    break
                f.write(chunk)
                size += len(chunk)
    finally:
        r.close()                                     # always hang up, even after an error

    # A real JPEG starts with the two bytes FF D8. Reject anything tiny or wrong,
    # such as an error page, rather than trying to draw it.
    with open(TEMP_FILE, "rb") as f:
        magic = f.read(2)
    if size < 2000 or magic != b"\xff\xd8":
        os.remove(TEMP_FILE)
        raise RuntimeError("bad image (%d bytes)" % size)

    # The download is good: swap it in for the old picture.
    try:
        os.remove(IMAGE_FILE)
    except OSError:
        pass                                          # there was no old picture yet
    os.rename(TEMP_FILE, IMAGE_FILE)


def download_tide_info():
    """Fetch dashboard.json (where the tide curve is). Returns a dict, or None if unavailable."""
    try:
        r = urequests.get(JSON_URL)
        try:
            if r.status_code != 200:
                return None
            return r.json()                           # turn the text file into a Python dictionary
        finally:
            r.close()
    except Exception as e:
        print("No tide info:", e)                     # not fatal: we just skip the red marker
        return None


# ------------------------------------------------------------------ drawing
def draw_now_marker(graphics, info, hours):
    """Draw the red dashed line and dot on the tide chart for the time `hours` (0 to 24).

    info comes from dashboard.json: the chart runs from x0 (midnight) to x1
    (next midnight), and ys[i] is the height of the curve at every 10 minutes.
    """
    m = info["marker"]
    x = int(m["x0"] + hours / 24 * (m["x1"] - m["x0"]) + 0.5)   # how far across the chart "now" is
    y = m["ys"][int(hours * 6 + 0.5)]                           # how high the curve is at that moment
    graphics.set_pen(INK_RED)
    for top in range(m["top"], m["bottom"], 9):       # dashed line: a short bar every 9 pixels
        graphics.rectangle(x - 1, top, 3, 6)
    graphics.set_pen(INK_BLACK)                       # dot: red centre with a black ring
    graphics.circle(x, y, 9)
    graphics.set_pen(INK_RED)
    graphics.circle(x, y, 6)


def show(info=None, hours=None):
    """Draw the stored picture on the e-ink screen (takes about 30 seconds).

    If info and hours are given, the red "now" marker is added on top first.
    """
    graphics = PicoGraphics(display=DISPLAY)
    jpeg = jpegdec.JPEG(graphics)
    jpeg.open_file(IMAGE_FILE)
    # The picture already uses only the panel's seven inks, so no dithering is needed.
    jpeg.decode(0, 0, jpegdec.JPEG_SCALE_FULL, dither=False)
    if info is not None and hours is not None:
        draw_now_marker(graphics, info, hours)
    graphics.update()                                 # the slow part: the screen flickers and redraws


# ------------------------------------------------------------------ the safety timer
def restart_now(timer):
    """Called by the safety timer if an update takes too long: restart the Pico.

    After the restart, main.py runs again from the top and tries a fresh update.
    """
    print("Update took too long; restarting")
    machine.reset()


# ------------------------------------------------------------------ the main program
def main():
    inky_frame.led_busy.on()           # the green "busy" light is on while we work

    # Start the safety timer. It is a stopwatch that counts down in the background,
    # even if the rest of the program is stuck. If it ever reaches zero it calls
    # restart_now(). Normally we switch it off (see deinit below) long before that.
    safety_timer = machine.Timer(-1)
    safety_timer.init(mode=machine.Timer.ONE_SHOT,
                      period=UPDATE_TIME_LIMIT_MINUTES * 60 * 1000,   # in milliseconds
                      callback=restart_now)

    wait = RETRY_MINUTES               # assume failure until it works
    try:
        if not connect():
            raise RuntimeError("Wi-Fi failed")
        clock_ok = set_clock()
        download()
        info = download_tide_info()

        # Only draw the marker if we know the time, the tide file arrived, it has
        # tide data, and it is for TODAY (a picture from yesterday would put the
        # marker in the wrong place).
        info_ok = None
        hours = None
        if clock_ok and info and info.get("marker"):
            date, hours = local_time()
            if info.get("date") == date:
                info_ok = info
        show(info_ok, hours)
        wait = UPDATE_MINUTES          # success: next check in 30 minutes
    except Exception as e:
        # Leave whatever is on the screen alone and try again soon.
        print("Update failed:", e)
        inky_frame.led_warn.on()       # the orange warning light
    safety_timer.deinit()              # the update finished (well or badly): stop the stopwatch
    inky_frame.led_busy.off()

    # Now wait for the next update.
    # On battery, sleep_for() switches the board off and its clock wakes it up later.
    # On USB power it can't switch off, so it returns and the program would just end,
    # leaving the picture stale until you cut the power. To avoid that we wait out the
    # rest of the time ourselves and then restart, which runs this program again.
    started = time.ticks_ms()
    inky_frame.sleep_for(wait)
    left = wait * 60 * 1000 - time.ticks_diff(time.ticks_ms(), started)
    if left > 0:
        time.sleep_ms(left)
    machine.reset()


main()                                 # this line starts everything
