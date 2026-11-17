# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

MicroPython firmware for an ESP32 that turns an Uncle Milton "Moon in My Room" toy into a lamp showing the real current moon phase. The whole program is `main.py`, which the board runs at every power-on. `README.md` is the user-facing build and setup guide (parts, wiring, calibration). Keep it in sync when settings or helpers change.

## Running / testing

There is no build, lint, or test tooling. The code only runs on the device: it imports MicroPython-only modules (`machine`, `neopixel`, `network`, `ntptime`) and uses MicroPython APIs (`time.ticks_ms`, `time.sleep_ms`, 8-tuple `time.mktime`). It won't run under CPython without stubs.

The documented workflow (README) is Thonny: flash MicroPython, save `main.py` to the board, then press Ctrl-C in the Shell to stop the main loop and call helpers interactively: `walk()`, `chamber(j)`, `show(phase)`, `demo()`, `startup_sweep()`, `run()`, `off()`, `test(i)`.

## Architecture notes

- **Module-level side effects.** Importing `main.py` builds the `NeoPixel` strip, computes `chambers`/`FEWEST`, then calls `startup_sweep()` and `run()` (an infinite loop). `KeyboardInterrupt` drops to the REPL with every global still live. That's why settings typed in the Shell take effect until restart. Derived globals (`chambers`, `FEWEST`) are computed once at import, so changing `CHAMBERS` or `NUM_LEDS` at the prompt won't rebuild them.
- **Phase math.** `moon_phase()` is the mean synodic month (`SYNODIC_S`, whole seconds) counted from a reference new moon (`NEW_MOON_REF`). Both references go through `time.mktime`, so the code doesn't depend on the port's epoch. The modulo is done on integers before dividing, which matters because ESP32 MicroPython floats are single-precision. Keep it that way.
- **Rendering pipeline.** `lit_fractions(phase)` gives each of the six chambers a 0.0–1.0 lit fraction. The shadow edge crosses one chamber per 1/12 of the cycle, and `NORTHERN_HEMISPHERE` and `SMOOTH_EDGE` are applied here. `set_chamber(j, lit)` turns that fraction into pixel values: lit share gets `COLOR`, unlit share gets the `DARK_COLOR` glow. `render()` and `show_only()` fill the strip and call `strip.write()`. `set_chamber` itself never writes.
- **Brightness equalization.** Every chamber gets the same *total* light no matter how many LEDs it has. Total light is `GAIN[j] * FEWEST` (FEWEST = LED count of the smallest chamber), split across the chamber's LEDs with `divmod` so the remainder is spread one unit at a time. Pixels are RGBW 4-tuples (`bpp=4`, SK6812).
- **Chamber map.** `CHAMBERS` lists LED indices per chamber, left to right as you face the moon. LEDs under baffle walls are left out and stay off. If `CHAMBERS` is `None`, `_equal_split()` divides the strip into six groups, using `LED0_ON_LEFT` for orientation. The committed map belongs to one particular build.
- **Clock / Wi-Fi.** `run()` calls `sync_clock()` (Wi-Fi then NTP, UTC) at start-up and every `RESYNC_EVERY_S`. It redraws every `UPDATE_EVERY_S`, or every 60 s until the first sync succeeds. `clock_is_set()` treats any time before 2025 as unset and shows `show_waiting()` (one dim blue LED). `startup_sweep()` starts the Wi-Fi connection itself and keeps sweeping until Wi-Fi is up (30 s max), so the sweep hides the connect delay.

## Constraints

- `WIFI_SSID` / `WIFI_PASSWORD` must stay as placeholders in committed code. Never commit real credentials.
- Settings live as constants at the top of `main.py` and are documented for end users there and in the README. Keep their inline comments plain-language.
