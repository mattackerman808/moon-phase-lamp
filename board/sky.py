# sky.py - local time, sunrise and sunset, and the on/off schedule.
#
# Pure maths with no hardware, so it can be checked on a computer. Times are
# whole Unix seconds (since 1970, UTC). Keep them as integers: ESP32 floats
# only hold about 7 digits.

import math

DAY = 86400


# ------------------------------------------------------------- Calendar

def days_from_civil(y, m, d):
    """Days since 1 January 1970 for a calendar date."""
    y -= 1 if m <= 2 else 0
    era = y // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def civil_from_days(z):
    """Calendar date (year, month, day) for days since 1 January 1970."""
    z += 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return yoe + era * 400 + (1 if m <= 2 else 0), m, d


# ------------------------------------------------------------- Time zone

def utc_offset(t, rules):
    """Minutes ahead of UTC at Unix time t.

    rules is [[unix time, minutes], ...] in time order, as worked out by the
    web page from the browser's time zone. Empty means UTC.
    """
    off = rules[0][1] if rules else 0
    for start, minutes in rules:
        if start > t:
            break
        off = minutes
    return off


def hhmm(t, rules):
    """Local clock time "HH:MM" for Unix time t."""
    s = (t + utc_offset(t, rules) * 60) % DAY
    return "%02d:%02d" % (s // 3600, s % 3600 // 60)


def parse_hhmm(text):
    """Minutes after midnight for "HH:MM", or None if it isn't one."""
    try:
        h, m = text.split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    if 0 <= h < 24 and 0 <= m < 60:
        return h * 60 + m
    return None


# ---------------------------------------------------------- Sun

def sun_times(days, lat, lon):
    """Sunrise and sunset for a date, in minutes after that date's UTC midnight.

    days is the date as days since 1970. lon is positive east. Uses NOAA's
    short formulas, good to a minute or two. Returns None when the sun
    doesn't rise or set that day (near the poles).
    """
    y, _, _ = civil_from_days(days)
    doy = days - days_from_civil(y, 1, 1)
    n = 366 if days_from_civil(y + 1, 1, 1) - days_from_civil(y, 1, 1) == 366 else 365
    g = 2 * math.pi / n * (doy + 0.5)
    eqt = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                    - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    la = math.radians(lat)
    cos_h = (math.cos(math.radians(90.833)) / (math.cos(la) * math.cos(decl))
             - math.tan(la) * math.tan(decl))
    if cos_h > 1 or cos_h < -1:
        return None
    h = math.degrees(math.acos(cos_h))
    return 720 - 4 * (lon + h) - eqt, 720 - 4 * (lon - h) - eqt


def sun_events(now, lat, lon, rules, around=1):
    """[(unix time, "sunrise" | "sunset")] for local days around now."""
    out = []
    if lat is None or lon is None:
        return out
    today = (now + utc_offset(now, rules) * 60) // DAY
    for dd in range(-around, around + 1):
        st = sun_times(today + dd, lat, lon)
        if st:
            base = (today + dd) * DAY
            out.append((base + int(st[0] * 60), "sunrise"))
            out.append((base + int(st[1] * 60), "sunset"))
    out.sort()
    return out


# -------------------------------------------------------------- Schedule

def event_time(days, spec, offset_min, lat, lon, rules):
    """Unix time of "sunset", "sunrise" or "HH:MM" on a local date, or None."""
    if spec in ("sunrise", "sunset"):
        if lat is None or lon is None:
            return None
        st = sun_times(days, lat, lon)
        if not st:
            return None
        mins = st[0] if spec == "sunrise" else st[1]
        return days * DAY + int(mins * 60) + offset_min * 60
    mins = parse_hhmm(spec)
    if mins is None:
        return None
    wall = days * DAY + mins * 60          # that clock time, as if it were UTC
    return wall - utc_offset(wall - utc_offset(wall, rules) * 60, rules) * 60


def schedule(now, on_at, on_offset, off_at, off_offset, lat, lon, rules):
    """The schedule around now: (last event, next event), each (time, "on"|"off")."""
    today = (now + utc_offset(now, rules) * 60) // DAY
    events = []
    for dd in (-1, 0, 1, 2):
        for kind, spec, off in (("on", on_at, on_offset), ("off", off_at, off_offset)):
            t = event_time(today + dd, spec, off, lat, lon, rules)
            if t is not None:
                events.append((t, kind))
    events.sort()
    last = nxt = None
    for e in events:
        if e[0] <= now:
            last = e
        elif nxt is None:
            nxt = e
    return last, nxt


def power_level(now, last, fade_min):
    """0.0 (off) to 1.0 (on), fading for fade_min after each change."""
    if last is None:
        return 1.0
    t, kind = last
    f = 1.0 if fade_min <= 0 else min(1.0, (now - t) / (fade_min * 60))
    return f if kind == "on" else 1.0 - f


def twilight_level(now, events, minutes):
    """1.0 within `minutes` of a sunrise or sunset, fading to 0.0 beyond it."""
    if not events:
        return 1.0                         # no location: glow all the time
    near = min(abs(now - t) for t, _ in events)
    span = minutes * 60
    edge = min(span // 2, 15 * 60)         # fade over the last 15 minutes
    if near >= span:
        return 0.0
    if near <= span - edge:
        return 1.0
    return (span - near) / edge
