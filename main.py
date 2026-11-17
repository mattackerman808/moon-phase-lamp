# main.py - show tonight's real moon phase on a Moon in My Room.
#
# Hardware: ESP32 running MicroPython, SK6812 RGBW strip across the moon.
# Wiring:   strip red -> VIN, strip white -> GND, strip green -> D18.
#
# The moon has six light chambers. This version lights whole chambers and
# evens out their brightness, so a chamber with one LED matches a chamber
# with several.
#
# The board runs this file automatically at power-on. To experiment, connect
# over USB, press Ctrl-C to stop it, then try the helpers at the bottom:
#   walk()       step through the LEDs one at a time (to fill in CHAMBERS)
#   chamber(0)   light one whole chamber, 0 = leftmost ... 5 = rightmost
#   show(0.5)    display a phase: 0 new, 0.25 first quarter, 0.5 full, 0.75 last
#   demo()       sweep through a whole month in 30 seconds
#   startup_sweep()  replay the power-on sweep
#   run()        go back to showing the real phase

import time

import machine
import neopixel
import network
import ntptime

# ---------------------------------------------------------------- Settings

WIFI_SSID = "your-network-name"   # must be a 2.4 GHz network
WIFI_PASSWORD = "your-password"

DATA_PIN = 18
NUM_LEDS = 27                # how many LEDs are on your cut piece of strip

# Which LEDs sit in each chamber, listed left to right as you face the moon.
# Use walk() to find out. Leave out any LED that sits under a baffle wall:
# LEDs not listed here stay off. Example for 27 LEDs:
#   CHAMBERS = [(0, 1), (3, 4, 5, 6), (8, 9, 10, 11, 12),
#               (14, 15, 16, 17, 18), (20, 21, 22, 23), (25, 26)]
# While this is None, the strip is simply split into six equal groups.
# The map below is from one particular build (27 LEDs of a 144/m strip);
# yours will differ, so run walk() and replace it.
CHAMBERS = [[0, 1, 2, 3], [5, 6], [7, 8, 9, 10, 11, 12],
            [13, 14, 15, 16, 17, 18], [20], [22, 23, 24, 25, 26]]
# LEDs 4, 19 and 21 sit under baffle walls, so they are left out.

# Fine-tune each chamber by eye, left to right. Raise a dim one above 1.0,
# lower a bright one below 1.0. Check with show(0.5), a full moon.
GAIN = (0.67, 0.67, 0.87, 0.87, 1.0, 1.2)

BRIGHTNESS = 1.0             # 0.0 to 1.0, overall. Every chamber is matched to
                             # chamber 5's single LED, so even 1.0 draws only
                             # about six LEDs' worth of power.
COLOR = (0, 0, 0, 255)       # (red, green, blue, white) for the lit part.
                             # White channel only gives the cleanest moonlight.

DARK_COLOR = (255, 40, 0, 0) # (red, green, blue, white) glow on the unlit part.
DARK_BRIGHTNESS = 0.2        # How strong that glow is. 0 turns it off.

SWEEP_STEP_S = 0.12          # Power-on sweep: seconds spent on each chamber as
                             # the light runs 1 -> 6 -> 1. 0 skips the sweep.

SMOOTH_EDGE = True           # True: the chamber at the shadow edge fades in
                             # and out over a couple of days. False: chambers
                             # switch fully on or off, like the original toy.
NORTHERN_HEMISPHERE = True   # False flips which side is lit, as seen down south.
LED0_ON_LEFT = True          # Only used while CHAMBERS is None: is the first
                             # LED (the end with the wires) on the left?

UPDATE_EVERY_S = 600         # Redraw every 10 minutes.
RESYNC_EVERY_S = 12 * 3600   # Fetch internet time twice a day.

# ------------------------------------------------------------- Moon phase

# Average length of a lunar cycle, in whole seconds (29.530588 days).
SYNODIC_S = 2551443
# A known new moon: 6 January 2000, 18:14 UTC.
NEW_MOON_REF = time.mktime((2000, 1, 6, 18, 14, 0, 0, 0))
# Before the first internet time sync the clock reads year 2000.
CLOCK_VALID_AFTER = time.mktime((2025, 1, 1, 0, 0, 0, 0, 0))


def moon_phase(now=None):
    """Return the phase as 0.0-1.0: 0 new, 0.25 first quarter, 0.5 full."""
    if now is None:
        now = time.time()
    return ((now - NEW_MOON_REF) % SYNODIC_S) / SYNODIC_S


def clock_is_set():
    return time.time() > CLOCK_VALID_AFTER


# ----------------------------------------------------------------- LEDs

strip = neopixel.NeoPixel(machine.Pin(DATA_PIN), NUM_LEDS, bpp=4)
OFF = (0, 0, 0, 0)


def _equal_split():
    order = list(range(NUM_LEDS))
    if not LED0_ON_LEFT:
        order.reverse()
    return [tuple(order[NUM_LEDS * j // 6:NUM_LEDS * (j + 1) // 6])
            for j in range(6)]


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


def set_chamber(j, lit):
    """Set one chamber to 0.0-1.0 lit (does not send to the strip).

    The lit share gets COLOR, the unlit share gets the dim DARK_COLOR glow.
    """
    leds = chambers[j]
    if not leds:
        return
    n = len(leds)
    # Light for the whole chamber, then shared out among its LEDs.
    share = GAIN[j] * FEWEST
    bright = lit * BRIGHTNESS * share
    dark = (1.0 - lit) * DARK_BRIGHTNESS * share
    for k, i in enumerate(leds):
        px = []
        for c in range(4):
            units = int(COLOR[c] * bright + DARK_COLOR[c] * dark + 0.5)
            base, extra = divmod(units, n)
            px.append(min(255, base + (1 if k < extra else 0)))
        strip[i] = tuple(px)


def render(phase):
    """Light the moon for a phase between 0.0 and 1.0."""
    strip.fill(OFF)
    for j, f in enumerate(lit_fractions(phase)):
        set_chamber(j, f)
    strip.write()


def show_only(j):
    """One chamber fully lit, the rest showing the dark glow."""
    strip.fill(OFF)
    for k in range(len(chambers)):
        set_chamber(k, 1.0 if k == j else 0.0)
    strip.write()


def startup_sweep():
    """Run the light across the chambers, 1 -> 6 -> 1.

    Wi-Fi starts connecting at the same time. If it is not up after one
    pass, the sweep repeats until it is (or 30 seconds have gone by), so
    the moon goes straight from the sweep to tonight's phase.
    """
    if SWEEP_STEP_S <= 0:
        return
    wlan.active(True)
    if not wlan.isconnected():
        try:
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        except OSError:
            pass  # already trying to connect
    n = len(chambers)
    bounce = list(range(1, n)) + list(range(n - 2, -1, -1))   # 2..6, 5..1
    deadline = time.ticks_add(time.ticks_ms(), 30000)
    show_only(0)
    time.sleep(SWEEP_STEP_S)
    while True:
        for j in bounce:
            show_only(j)
            time.sleep(SWEEP_STEP_S)
        if wlan.isconnected() or time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            break
    if not wlan.isconnected():
        show_waiting()


def show_waiting():
    """One dim blue LED: no internet time yet, so the phase is unknown."""
    strip.fill(OFF)
    strip[0] = (0, 0, 8, 0)
    strip.write()


# ------------------------------------------------------- Wi-Fi and clock

wlan = network.WLAN(network.STA_IF)


def connect_wifi(timeout_s=30):
    wlan.active(True)
    if wlan.isconnected():
        return True
    try:
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    except OSError:
        pass  # already trying to connect
    deadline = time.ticks_add(time.ticks_ms(), timeout_s * 1000)
    while not wlan.isconnected():
        if time.ticks_diff(deadline, time.ticks_ms()) <= 0:
            return False
        time.sleep_ms(250)
    return True


def sync_clock():
    """Set the board's clock from the internet. Returns True on success."""
    if not connect_wifi():
        print("Wi-Fi: could not connect")
        return False
    try:
        ntptime.settime()
    except Exception as err:
        print("Time sync failed:", err)
        return False
    print("Time synced (UTC):", time.gmtime()[:6])
    return True


# ------------------------------------------------------------ Main loop

def run():
    last_sync = None
    while True:
        due = last_sync is None or time.time() - last_sync >= RESYNC_EVERY_S
        if due and sync_clock():
            last_sync = time.time()

        if clock_is_set():
            phase = moon_phase()
            render(phase)
            print("Phase: %.3f" % phase)
            # Until the first sync works, try again every minute.
            time.sleep(UPDATE_EVERY_S if last_sync is not None else 60)
        else:
            show_waiting()
            time.sleep(10)


# ---------------------------------------------- Helpers for the prompt

def show(phase):
    render(phase)


def test(i):
    """Light a single LED."""
    strip.fill(OFF)
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


try:
    startup_sweep()
    run()
except KeyboardInterrupt:
    print("Stopped. Try walk(), chamber(0), show(0.5), demo(), or run().")
