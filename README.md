# Moon phase lamp

Firmware that turns an Uncle Milton **Moon in My Room** into a lamp that
shows tonight's real moon phase, with no remote needed.

An ESP32 replaces the toy's original controller. It gets the date from the
internet, works out the phase, and lights the moon's six chambers with an
addressable LED strip. The unlit side gets a faint red glow, and at power-on
the light sweeps across the moon before settling on the current phase.

## Parts

- Uncle Milton Moon in My Room
- ESP32 development board (a classic ESP-WROOM-32 DevKit works well)
- SK6812 **RGBW** addressable LED strip, 5 V, 144 LEDs/m, IP30
  (about 20 cm is used; natural white on a white PCB suits the housing)
- Three jumper wires
- USB cable and a 5 V USB power adapter

## How the toy is built

The moon has six wedge-shaped light chambers separated by baffles. The stock
circuit board is a single strip across the middle with one LED per chamber.
That board is unplugged and left in place as a carrier, and the LED strip is
stuck along the same line.

## Wiring

| Strip wire | ESP32 pin |
|---|---|
| Red (+5 V) | VIN |
| White (ground) | GND |
| Green (data) | D18 |

Connect to the strip's **Din** end. Powering the strip from VIN means the
strip and the board always power up together.

## Installing

1. Install [Thonny](https://thonny.org) and use it to put MicroPython on the
   ESP32 (Run → Configure interpreter → MicroPython (ESP32) → Install).
2. Open `main.py`, set `WIFI_SSID` and `WIFI_PASSWORD` (2.4 GHz only), and
   set `NUM_LEDS` to the number of LEDs on your piece of strip.
3. Save it to the board as `main.py`. It runs at every power-on.

Do not commit your real Wi-Fi name or password.

## Setting it up for your moon

Connect over USB, press Ctrl-C in the Thonny Shell to stop the program, and
use these helpers:

| Command | What it does |
|---|---|
| `walk()` | Lights one LED at a time so you can see which chamber each is in |
| `chamber(0)` | Lights one whole chamber (0 = leftmost, 5 = rightmost) |
| `show(0.5)` | Shows a phase: 0 new, 0.25 first quarter, 0.5 full, 0.75 last |
| `demo()` | Sweeps through a whole month in 30 seconds |
| `startup_sweep()` | Replays the power-on sweep |
| `run()` | Goes back to showing the real phase |

Then edit the settings at the top of `main.py`:

- **`CHAMBERS`** lists the LEDs in each chamber, left to right as you face
  the moon. Leave out any LED that sits under a baffle wall and lights two
  chambers at once.
- **`GAIN`** trims each chamber's brightness. Every chamber is given the same
  total light regardless of how many LEDs it has; `GAIN` corrects what is
  left by eye. Check with `show(0.5)`.
- **`BRIGHTNESS`** sets the overall level.
- **`DARK_COLOR`** and **`DARK_BRIGHTNESS`** control the glow on the unlit
  side. Set the brightness to 0 to turn it off.
- **`SWEEP_STEP_S`** sets the speed of the power-on sweep. 0 skips it.
- **`SMOOTH_EDGE`** fades the chamber at the shadow edge; set it to `False`
  for hard steps like the original toy.
- **`NORTHERN_HEMISPHERE`** flips which side is lit.

Values typed in the Shell apply until the next restart, which makes it easy
to experiment before saving them in the file.

## How it works

- The phase comes from the moon's average cycle length (29.53 days) counted
  from a known new moon. That is typically within about half a day of the
  true phase, which is less than one chamber's worth of difference.
- The shadow edge crosses one chamber per twelfth of the cycle, matching how
  the baffles are cut.
- The clock is set over Wi-Fi at start-up and re-synced twice a day. If Wi-Fi
  drops while it is running, the lamp carries on with its own clock.
- A single dim blue LED means it is waiting for Wi-Fi or internet time.

## Prior art

Earlier versions of this hack replaced the toy's controller with an Arduino
and a real-time clock module:

- [Arduino Controlled Model Moon (Instructables)](https://instructables.com/Arduino-Controlled-Model-Moon-synchronizes-phase-c)
- [Moon light displays realtime phases (Make)](https://makezine.com/?p=61803)
- [Moon phase light modification (Hackaday)](https://hackaday.com/2009/08/19/moon-phase-light-modification)
