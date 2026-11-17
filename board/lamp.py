# lamp.py - moon phase, LED drawing and settings for the Moon in My Room lamp.
#
# Hardware: ESP32 running MicroPython, SK6812 RGBW strip across the moon.
# Wiring:   strip red -> VIN, strip white -> GND, strip green -> D18.
#
# The moon has six light chambers. This lights whole chambers and evens out
# their brightness, so a chamber with one LED matches a chamber with several.
#
# The values below are the defaults. Anything changed on the web page and
# saved there is kept in settings.json on the board, and wins over these.

import asyncio
import json
import os
import time

import machine
import neopixel

import sky
import themes

# ---------------------------------------------------------------- Settings

WIFI_SSID = ""               # Normally set on the setup page. 2.4 GHz only.
WIFI_PASSWORD = ""           # Never commit a real one.
HOSTNAME = "moon"            # The web page is at http://moon.local

DATA_PIN = 18
NUM_LEDS = 27                # how many LEDs are on your cut piece of strip

# Which LEDs sit in each chamber, listed left to right as you face the moon.
# Use walk() or the web page's Calibrate section to find out. Leave out any
# LED that sits under a baffle wall: LEDs not listed here stay off.
# Set to None to split the strip into six equal groups.
# The map below is from one particular build (27 LEDs of a 144/m strip);
# yours will differ. LEDs 4, 19 and 21 sit under baffle walls.
CHAMBERS = [[0, 1, 2, 3], [5, 6], [7, 8, 9, 10, 11, 12],
            [13, 14, 15, 16, 17, 18], [20], [22, 23, 24, 25, 26]]

# Fine-tune each chamber by eye, left to right. Raise a dim one above 1.0,
# lower a bright one below 1.0. Check with show(0.5), a full moon.
GAIN = [0.67, 0.67, 0.87, 0.87, 1.0, 1.2]

BRIGHTNESS = 1.0             # 0.0 to 1.0, the whole moon: lit side and dark
                             # side glow together. Every chamber is matched to
                             # the chamber with the fewest LEDs, so even 1.0
                             # draws only a few LEDs' worth of power.
COLOR = [0, 0, 0, 255]       # (red, green, blue, white) for the lit part.
                             # White channel only gives the cleanest moonlight.

DARK_GLOW = True             # Light the unlit part with a faint glow?
DARK_COLOR = [255, 40, 0, 0] # (red, green, blue, white) colour of that glow.
DARK_BRIGHTNESS = 0.2        # Its strength compared with the lit part,
                             # 0.0 to 1.0. BRIGHTNESS dims both together.

SWEEP_STEP_S = 0.12          # Power-on sweep: seconds spent on each chamber as
                             # the light runs 1 -> 6 -> 1. 0 skips the sweep.

SMOOTH_EDGE = True           # True: the chamber at the shadow edge fades in
                             # and out over a couple of days. False: chambers
                             # switch fully on or off, like the original toy.
NORTHERN_HEMISPHERE = True   # False flips which side is lit, as seen down south.
LED0_ON_LEFT = True          # Only used while CHAMBERS is None: is the first
                             # LED (the end with the wires) on the left?

# Where and when. The web page fills in the time zone from your phone or
# computer; latitude and longitude are needed for sunrise and sunset.
LATITUDE = None              # e.g. 51.5 (north is positive)
LONGITUDE = None             # e.g. -0.13 (east is positive, west negative)
TZ_NAME = ""                 # e.g. "Europe/London", shown on the page
TZ_RULES = []                # [[Unix time, minutes ahead of UTC], ...]

GLOW_TWILIGHT = False        # True: show the dark side glow only around
TWILIGHT_MIN = 60            # sunrise and sunset, this many minutes either side,
                             # like earthshine on the real moon.

SCHEDULE = False             # Turn on and off by itself?
ON_AT = "sunset"             # "sunset", "sunrise" or a time like "19:30"
ON_OFFSET_MIN = 0            # minutes after sunset/sunrise (negative: before)
OFF_AT = "23:00"
OFF_OFFSET_MIN = 0
FADE_MIN = 10                # minutes to fade in and out (0 switches at once)

THEME = "moon"               # "moon" (uses COLOR), "blood", "jupiter",
                             # "nebula", "rainbow" or "aurora"
THEME_MOTION = True          # let animated themes move slowly
FIXED_PHASE = None           # None: tonight's real moon. 0.0-1.0: always show
                             # that phase (0.5 full, 0.25 first quarter)

# Settings the web page can change and settings.json can hold.
SETTINGS = ("WIFI_SSID", "WIFI_PASSWORD", "HOSTNAME", "NUM_LEDS", "CHAMBERS",
            "GAIN", "BRIGHTNESS", "COLOR", "DARK_GLOW", "DARK_COLOR",
            "DARK_BRIGHTNESS",
            "SWEEP_STEP_S", "SMOOTH_EDGE", "NORTHERN_HEMISPHERE",
            "LED0_ON_LEFT", "LATITUDE", "LONGITUDE", "TZ_NAME", "TZ_RULES",
            "GLOW_TWILIGHT", "TWILIGHT_MIN", "SCHEDULE", "ON_AT",
            "ON_OFFSET_MIN", "OFF_AT", "OFF_OFFSET_MIN", "FADE_MIN",
            "THEME", "THEME_MOTION", "FIXED_PHASE")
SETTINGS_FILE = "settings.json"

HOLD_S = 120                 # A preview from the web page lasts this long.
GLANCE_S = 5                 # Tapping a colour shows the whole moon this long.
DEMO_S = 30                  # A demo month takes this long.

# ------------------------------------------------------------- Moon phase

# Average length of a lunar cycle, in whole seconds (29.530588 days).
# Kept as whole numbers: ESP32 floats are too coarse for the raw clock value.
SYNODIC_S = 2551443
# A known new moon: 6 January 2000, 18:14 UTC.
NEW_MOON_REF = time.mktime((2000, 1, 6, 18, 14, 0, 0, 0))
# Before the first internet time sync the clock reads year 2000.
CLOCK_VALID_AFTER = time.mktime((2025, 1, 1, 0, 0, 0, 0, 0))


def moon_phase(now=None):
    """Return the phase as 0.0-1.0: 0 new, 0.25 first quarter, 0.5 full."""
    if now is None:
        now = time.time()
    return ((int(now) - NEW_MOON_REF) % SYNODIC_S) / SYNODIC_S


def clock_is_set():
    return time.time() > CLOCK_VALID_AFTER


# Some MicroPython builds count time from 2000 instead of 1970.
EPOCH_DELTA = 946684800 if time.gmtime(0)[0] == 2000 else 0


def unix_now():
    return int(time.time()) + EPOCH_DELTA


# ------------------------------------------------------------ Saving

_DEFAULTS = {k: globals()[k] for k in SETTINGS}
_saved = dict(_DEFAULTS)     # what settings.json holds, after load()/save()


def _num(v, lo, hi):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError("expected a number")
    return min(hi, max(lo, v))


def _color(v):
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        raise ValueError("expected [red, green, blue, white]")
    return [int(_num(c, 0, 255)) for c in v]


def _clean(name, v, new):
    """Check one setting and return it in the form the lamp uses."""
    if name in ("WIFI_SSID", "WIFI_PASSWORD"):
        if not isinstance(v, str) or len(v) > 64:
            raise ValueError("expected text up to 64 characters")
        return v
    if name == "HOSTNAME":
        v = str(v).lower()
        ok = 0 < len(v) <= 32 and v[0] != "-" and v[-1] != "-"
        for ch in v:
            ok = ok and (ch.isalpha() or ch.isdigit() or ch == "-")
        if not ok:
            raise ValueError("use letters, numbers and dashes")
        return v
    if name == "NUM_LEDS":
        return int(_num(v, 1, 300))
    if name == "CHAMBERS":
        if v is None:
            return None
        if not isinstance(v, list) or len(v) != 6:
            raise ValueError("expected six lists of LED numbers")
        n = new.get("NUM_LEDS", NUM_LEDS)
        out = []
        for c in v:
            if not isinstance(c, list):
                raise ValueError("expected six lists of LED numbers")
            leds = [int(_num(i, 0, 1000)) for i in c]
            for i in leds:
                if i >= n:
                    raise ValueError("LED %d is past the end of the strip" % i)
            out.append(leds)
        return out
    if name == "GAIN":
        if not isinstance(v, list) or len(v) != 6:
            raise ValueError("expected six numbers")
        return [_num(g, 0.0, 3.0) for g in v]
    if name in ("BRIGHTNESS", "DARK_BRIGHTNESS"):
        return _num(v, 0.0, 1.0)
    if name in ("COLOR", "DARK_COLOR"):
        return _color(v)
    if name == "SWEEP_STEP_S":
        return _num(v, 0.0, 2.0)
    if name in ("DARK_GLOW", "SMOOTH_EDGE", "NORTHERN_HEMISPHERE",
                "LED0_ON_LEFT", "GLOW_TWILIGHT", "SCHEDULE", "THEME_MOTION"):
        if not isinstance(v, bool):
            raise ValueError("expected true or false")
        return v
    if name in ("LATITUDE", "LONGITUDE"):
        if v is None:
            return None
        lim = 90 if name == "LATITUDE" else 180
        v = _num(v, -lim - 1, lim + 1)
        if not -lim <= v <= lim:
            raise ValueError("expected -%d to %d" % (lim, lim))
        return float(v)
    if name == "TZ_NAME":
        if not isinstance(v, str) or len(v) > 64:
            raise ValueError("expected text up to 64 characters")
        return v
    if name == "TZ_RULES":
        if not isinstance(v, list) or len(v) > 64:
            raise ValueError("expected up to 64 [time, minutes] pairs")
        out = []
        for r in v:
            if not isinstance(r, list) or len(r) != 2:
                raise ValueError("expected [time, minutes] pairs")
            t, m = int(_num(r[0], 0, 4e9)), int(_num(r[1], -900, 900))
            if out and t <= out[-1][0]:
                raise ValueError("times must go up")
            out.append([t, m])
        return out
    if name in ("ON_AT", "OFF_AT"):
        if v in ("sunset", "sunrise"):
            return v
        mins = sky.parse_hhmm(v)
        if mins is None:
            raise ValueError('expected "sunset", "sunrise" or a time like "19:30"')
        return "%02d:%02d" % (mins // 60, mins % 60)
    if name in ("ON_OFFSET_MIN", "OFF_OFFSET_MIN"):
        return int(_num(v, -240, 240))
    if name == "FADE_MIN":
        return int(_num(v, 0, 120))
    if name == "THEME":
        if v not in themes.THEMES:
            raise ValueError("expected one of " + ", ".join(themes.THEMES))
        return v
    if name == "FIXED_PHASE":
        return None if v is None else _num(v, 0.0, 1.0)
    if name == "TWILIGHT_MIN":
        return int(_num(v, 10, 240))
    raise ValueError("unknown setting")


def apply(changes):
    """Check and use new settings straight away (not saved).

    Raises ValueError naming the bad setting; nothing changes in that case.
    """
    for k in changes:
        if k not in SETTINGS:
            raise ValueError("%s: unknown setting" % k)
    new = {}
    for k in SETTINGS:           # in order, so NUM_LEDS is known before CHAMBERS
        if k in changes:
            try:
                new[k] = _clean(k, changes[k], new)
            except ValueError as err:
                raise ValueError("%s: %s" % (k, err))
    if "NUM_LEDS" in new and "CHAMBERS" not in new and CHAMBERS:
        for c in CHAMBERS:
            for i in c:
                if i >= new["NUM_LEDS"]:
                    raise ValueError("NUM_LEDS: CHAMBERS uses LED %d" % i)
    globals().update(new)
    if "NUM_LEDS" in new or "CHAMBERS" in new or "LED0_ON_LEFT" in new:
        rebuild()
    _forget_plan()
    draw()


def unsaved():
    return any(globals()[k] != _saved[k] for k in SETTINGS)


def save(only=None):
    """Write settings to settings.json. only: a list of names to save."""
    global _saved
    keep = dict(_saved)
    for k in (only or SETTINGS):
        keep[k] = globals()[k]
    changed = {k: keep[k] for k in SETTINGS if keep[k] != _DEFAULTS[k]}
    with open(SETTINGS_FILE + ".tmp", "w") as f:
        json.dump(changed, f)
    os.rename(SETTINGS_FILE + ".tmp", SETTINGS_FILE)
    _saved = keep


def load():
    """Read settings.json, if there is one, over the defaults above."""
    global _saved
    try:
        with open(SETTINGS_FILE) as f:
            stored = json.load(f)
    except (OSError, ValueError):
        stored = {}
    try:
        apply(stored)
    except ValueError:
        # Use whatever is still valid, one setting at a time.
        for k in SETTINGS:
            if k in stored:
                try:
                    apply({k: stored[k]})
                except ValueError as err:
                    print("settings.json:", err)
    _saved = {k: globals()[k] for k in SETTINGS}


def revert():
    """Go back to the last saved settings."""
    apply(_saved)


def defaults():
    """Go back to the values in this file, keeping Wi-Fi (not saved)."""
    apply({k: v for k, v in _DEFAULTS.items()
           if k not in ("WIFI_SSID", "WIFI_PASSWORD", "HOSTNAME")})


# ----------------------------------------------------------------- LEDs

OFF = (0, 0, 0, 0)
strip = None
chambers = []
FEWEST = 1                   # LED count of the smallest chamber
setup_active = False         # net.py sets this while the setup network is up


def _equal_split():
    order = list(range(NUM_LEDS))
    if not LED0_ON_LEFT:
        order.reverse()
    return [tuple(order[NUM_LEDS * j // 6:NUM_LEDS * (j + 1) // 6])
            for j in range(6)]


def rebuild():
    """Set up the strip and chamber map from the settings.

    Call this after changing NUM_LEDS, CHAMBERS or LED0_ON_LEFT in the Shell.
    """
    global strip, chambers, FEWEST
    if strip is not None:
        off()                # clear LEDs a shorter strip would no longer reach
    strip = neopixel.NeoPixel(machine.Pin(DATA_PIN), NUM_LEDS, bpp=4)
    chambers = [tuple(c) for c in CHAMBERS] if CHAMBERS else _equal_split()
    # Every chamber is held to the light output of the one with the fewest LEDs.
    FEWEST = min([len(c) for c in chambers if c] or [1])


def lit_fractions(phase):
    """How much of each chamber is lit, left to right, each 0.0-1.0.

    The shadow edge on the real moon sweeps across at a steady rate, and
    each chamber is an equal slice, so each one covers 1/12 of the cycle.
    """
    n = len(chambers)
    p = phase % 1.0
    waxing = p < 0.5
    swept = (p if waxing else p - 0.5) * 2 * n   # chambers the edge has crossed
    out = []
    for j in range(n):
        # The edge starts from the right-hand limb in the northern hemisphere.
        from_start = (n - 1 - j) if NORTHERN_HEMISPHERE else j
        f = min(1.0, max(0.0, swept - from_start))
        if not SMOOTH_EDGE:
            f = 1.0 if f >= 0.5 else 0.0
        out.append(f if waxing else 1.0 - f)
    return out


def set_chamber(j, lit, power=1.0, glow=1.0, color=None):
    """Set one chamber to 0.0-1.0 lit (does not send to the strip).

    The lit share gets color (COLOR unless a theme gives one), the unlit
    share gets the dim DARK_COLOR glow.
    power (0.0-1.0) dims the whole moon for the schedule, glow (0.0-1.0)
    dims only the dark side glow for twilight.
    """
    leds = chambers[j]
    if not leds:
        return
    if color is None:
        color = COLOR
    n = len(leds)
    # Light for the whole chamber, then shared out among its LEDs.
    share = GAIN[j] * FEWEST
    level = BRIGHTNESS * power
    bright = lit * level * share
    dark = (1.0 - lit) * (DARK_BRIGHTNESS * level * glow if DARK_GLOW else 0.0) * share
    for k, i in enumerate(leds):
        px = []
        for c in range(4):
            units = int(color[c] * bright + DARK_COLOR[c] * dark + 0.5)
            base, extra = divmod(units, n)
            px.append(min(255, base + (1 if k < extra else 0)))
        strip[i] = tuple(px)


def theme_colors():
    """Each chamber's colour from the theme right now, or None for COLOR."""
    return themes.colors(THEME, len(chambers), time.ticks_ms(), THEME_MOTION)


def render(phase, power=1.0, glow=1.0):
    """Light the moon for a phase between 0.0 and 1.0."""
    strip.fill(OFF)
    if power > 0:
        tc = theme_colors()
        for j, f in enumerate(lit_fractions(phase)):
            set_chamber(j, f, power, glow, tc[j] if tc else None)
    strip.write()


def show_only(j):
    """One chamber fully lit, the rest showing the dark glow."""
    strip.fill(OFF)
    tc = theme_colors()
    for k in range(len(chambers)):
        set_chamber(k, 1.0 if k == j else 0.0, color=tc[k] if tc else None)
    strip.write()


def show_waiting():
    """One dim blue LED: no internet time yet, so the phase is unknown."""
    strip.fill(OFF)
    strip[0] = (0, 0, 8, 0)
    strip.write()


SETUP_PULSE_MS = 2400        # one slow blue breath while setup is needed


def show_setup():
    """The whole moon breathes blue: join the lamp's setup network."""
    t = time.ticks_ms() % SETUP_PULSE_MS / SETUP_PULSE_MS
    level = 0.08 + 0.92 * (1 - abs(2 * t - 1)) ** 2   # 0.08 -> 1 -> 0.08
    strip.fill(OFF)
    for j, leds in enumerate(chambers):
        if not leds:
            continue
        # Same evening-out as set_chamber, so every chamber matches.
        units = int(255 * level * GAIN[j] * FEWEST + 0.5)
        base, extra = divmod(units, len(leds))
        for k, i in enumerate(leds):
            strip[i] = (0, 0, min(255, base + (1 if k < extra else 0)), 0)
    strip.write()


def _animating():
    if showing() == "demo":
        return True
    if _hold is None and setup_active and not clock_is_set():
        return True                          # the blue setup pulse
    return (THEME_MOTION and THEME in themes.ANIMATED
            and showing() in ("tonight", "phase", "glance"))


# ---------------------------------------------------------- Schedule

_override = None             # (on, until Unix time or None) from the web page
HAND_ON_MAX_S = 4 * 3600     # turning on by hand while scheduled off lasts this
_plan = None                 # cached (worked out at, last, next, sun events)


def _forget_plan():
    global _plan
    _plan = None


def plan(now=None):
    """The schedule and today's sun around now, worked out once a minute."""
    global _plan
    if now is None:
        now = unix_now()
    if _plan is None or not 0 <= now - _plan[0] < 60:
        last = nxt = None
        if SCHEDULE:
            last, nxt = sky.schedule(now, ON_AT, ON_OFFSET_MIN, OFF_AT,
                                     OFF_OFFSET_MIN, LATITUDE, LONGITUDE, TZ_RULES)
        sun = sky.sun_events(now, LATITUDE, LONGITUDE, TZ_RULES)
        _plan = (now, last, nxt, sun)
    return _plan


def levels(now=None):
    """(power, glow) now: how much of the moon, and of its dark side glow."""
    global _override
    if now is None:
        now = unix_now()
    _, last, nxt, sun = plan(now)
    power = sky.power_level(now, last, FADE_MIN) if SCHEDULE else 1.0
    if _override:
        on, until = _override
        if until is not None and now >= until:
            _override = None
        else:
            power = 1.0 if on else 0.0
    glow = sky.twilight_level(now, sun, TWILIGHT_MIN) if GLOW_TWILIGHT else 1.0
    return power, glow


def set_power(on):
    """Turn on (True) or off (False) until the schedule's next change.

    Turning on while the schedule has the lamp off lasts at most
    HAND_ON_MAX_S, so it doesn't stay on all night and the next day.
    None goes back to the schedule. Without a schedule it lasts until restart.
    """
    global _override
    _override = None
    if on is not None:
        now = unix_now()
        nxt = plan(now)[2] if SCHEDULE else None
        until = nxt[0] if nxt else None
        if on and SCHEDULE and levels(now)[0] <= 0:
            until = min(until, now + HAND_ON_MAX_S) if until else now + HAND_ON_MAX_S
        _override = (on, until)
    draw()


def schedule_info():
    """What the web page shows about time, sun and schedule."""
    if not clock_is_set():
        return None
    now = unix_now()
    _, last, nxt, sun = plan(now)
    power, glow = levels(now)
    today = [(k, sky.hhmm(t, TZ_RULES)) for t, k in
             sky.sun_events(now, LATITUDE, LONGITUDE, TZ_RULES, around=0)]
    return {
        "time": sky.hhmm(now, TZ_RULES),
        "sun": dict(today),
        "power": power,
        "glow": glow,
        "override": _override[0] if _override else None,
        "until": sky.hhmm(_override[1], TZ_RULES) if _override and _override[1] else None,
        "next": [nxt[1], sky.hhmm(nxt[0], TZ_RULES)] if SCHEDULE and nxt else None,
    }


# ------------------------------------------------- What the moon is showing

# A preview from the web page: (kind, value, until_ticks, started_ticks).
_hold = None
_last_logged = None


def hold(kind, value=None, seconds=HOLD_S):
    """Show something other than tonight for a while.

    kind is "phase" (value 0.0-1.0), "glance" (a phase shown for a moment,
    to see a new colour), "demo", "led" (value = LED number) or
    "chamber" (value = 0-5).
    """
    global _hold
    now = time.ticks_ms()
    _hold = (kind, value, time.ticks_add(now, int(seconds * 1000)), now)
    draw()


def release():
    """Go back to tonight's phase."""
    global _hold
    _hold = None
    draw()


def showing():
    return _hold[0] if _hold else "tonight"


def shown_phase():
    """The phase on the moon right now, or None if it isn't showing one."""
    if _hold:
        kind, value, _, start = _hold
        if kind in ("phase", "glance"):
            return value
        if kind == "demo":
            return min(1.0, time.ticks_diff(time.ticks_ms(), start) / (DEMO_S * 1000))
        return None
    if FIXED_PHASE is not None:
        return FIXED_PHASE
    return moon_phase() if clock_is_set() else None


def draw():
    """Draw whatever the moon should be showing now."""
    global _hold, _last_logged
    now = time.ticks_ms()
    if _hold and time.ticks_diff(_hold[2], now) <= 0:
        _hold = None
    if _hold:
        kind, value, _, start = _hold
        if kind in ("phase", "glance"):
            return render(value)
        if kind == "led":
            return test(value)
        if kind == "chamber":
            return chamber(value)
        t = time.ticks_diff(now, start) / (DEMO_S * 1000)
        if t < 1:
            return render(t)
        _hold = None
    if clock_is_set():
        phase = moon_phase() if FIXED_PHASE is None else FIXED_PHASE
        render(phase, *levels())
        if _last_logged != int(phase * 1000):
            _last_logged = int(phase * 1000)
            print("Phase: %.3f" % phase)
    elif setup_active:
        show_setup()
    elif FIXED_PHASE is not None:
        render(FIXED_PHASE)                  # needs no clock, so no schedule
    else:
        show_waiting()


async def display_loop():
    while True:
        draw()
        await asyncio.sleep_ms(40 if _animating() else 500)


async def startup_sweep_async(done):
    """The power-on sweep, 1 -> 6 -> 1.

    It repeats until done() is true (Wi-Fi is up) or 30 seconds have gone
    by, so the moon goes straight from the sweep to tonight's phase.
    """
    if SWEEP_STEP_S <= 0:
        return
    step = int(SWEEP_STEP_S * 1000)
    deadline = time.ticks_add(time.ticks_ms(), 30000)
    show_only(0)
    await asyncio.sleep_ms(step)
    while True:
        for j in _bounce():
            show_only(j)
            await asyncio.sleep_ms(step)
        if done() or time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            break


def _bounce():
    n = len(chambers)
    return list(range(1, n)) + list(range(n - 2, -1, -1))   # 2..6, 5..1


# ---------------------------------------------- Helpers for the Shell

def show(phase):
    render(phase)


def test(i):
    """Light a single LED."""
    strip.fill(OFF)
    if 0 <= i < NUM_LEDS:
        strip[i] = (0, 0, 0, 40)
    strip.write()


def walk():
    """Step through every LED, to see which chamber each one sits in."""
    for i in range(NUM_LEDS):
        test(i)
        input("LED %d is lit - press Enter for the next one" % i)
    off()


def chamber(j):
    """Light one whole chamber at its evened-out full level."""
    strip.fill(OFF)
    set_chamber(j, 1.0)
    strip.write()


def off():
    strip.fill(OFF)
    strip.write()


def demo(seconds=30):
    """Sweep through one full lunar month."""
    steps = 300
    for s in range(steps + 1):
        render(s / steps)
        time.sleep(seconds / steps)


def startup_sweep():
    """Replay the power-on sweep once."""
    show_only(0)
    time.sleep(SWEEP_STEP_S)
    for j in _bounce():
        show_only(j)
        time.sleep(SWEEP_STEP_S)


rebuild()
