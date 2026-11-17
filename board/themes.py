# themes.py - colour themes for the lit part of the moon.
#
# Each theme gives one (red, green, blue, white) colour per chamber, left to
# right. Animated themes move slowly with the clock in milliseconds. Pure
# maths with no hardware, so it can be checked on a computer.

import math

THEMES = ("moon", "blood", "jupiter", "nebula", "rainbow", "aurora")
ANIMATED = ("jupiter", "nebula", "rainbow", "aurora")

_JUPITER = ([255, 214, 160, 40], [224, 150, 80, 10], [255, 226, 180, 60],
            [190, 110, 60, 0], [240, 180, 110, 20], [210, 130, 70, 0])
_SPOT = [230, 60, 20, 0]
_NEBULA = ([150, 0, 255, 0], [255, 0, 140, 0], [40, 0, 255, 0],
           [255, 60, 200, 0], [0, 90, 255, 0])
_VIOLET = [170, 0, 255, 0]


def _cycle(ms, period_s, offset=0.0):
    """Where we are, 0.0-1.0, in a cycle that repeats every period_s seconds.

    Uses whole milliseconds first: ESP32 floats can't hold big tick counts.
    """
    p = int(period_s * 1000)
    return ((ms % p) / p + offset) % 1.0


def _wave(ms, period_s, offset):
    """0.0-1.0, rising and falling smoothly."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * _cycle(ms, period_s, offset))


def _mix(a, b, f):
    return [int(x + (y - x) * f + 0.5) for x, y in zip(a, b)]


def hsv(h, s=1.0, v=1.0):
    """Hue 0.0-1.0 around the colour wheel, as [red, green, blue, 0]."""
    h = (h % 1.0) * 6
    i = int(h)
    f = h - i
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    r, g, b = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[i % 6]
    return [int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5), 0]


def colors(theme, n, ms, motion=True):
    """Colours for n chambers at clock time ms, or None for the plain moon."""
    if theme not in THEMES or theme == "moon":
        return None
    if not motion:
        ms = 0
    out = []
    for j in range(n):
        x = j / max(1, n - 1)                      # 0.0 left ... 1.0 right
        if theme == "blood":
            # Deep red in the middle, brighter copper towards the edges,
            # like the moon in a total lunar eclipse.
            out.append(_mix([170, 12, 0, 0], [255, 70, 10, 0], abs(x - 0.5) * 2))
        elif theme == "jupiter":
            band = _JUPITER[j % len(_JUPITER)]
            # The Great Red Spot drifts across every two minutes.
            spot = (_cycle(ms, 120) if motion else 0.4) * (n + 2) - 1
            out.append(_mix(band, _SPOT, 0.85 * max(0.0, 1 - abs(j - spot))))
        elif theme == "nebula":
            a = _NEBULA[j % len(_NEBULA)]
            b = _NEBULA[(j + 2) % len(_NEBULA)]
            out.append(_mix(a, b, _wave(ms, 47, j * 0.29)))
        elif theme == "rainbow":
            out.append(hsv(x * 0.85 + _cycle(ms, 60)))
        else:                                      # aurora
            hue = 0.36 + 0.07 * math.sin(2 * math.pi * _cycle(ms, 23, j * 0.21))
            c = hsv(hue, 1.0, 0.45 + 0.55 * _wave(ms, 17, j * 0.37))
            flash = max(0.0, math.sin(2 * math.pi * _cycle(ms, 37, j * 0.13))) ** 4
            out.append(_mix(c, _VIOLET, 0.7 * flash))
    return out
