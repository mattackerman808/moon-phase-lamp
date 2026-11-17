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
2. Copy every file in the `board` folder to the ESP32: in Thonny, open
   View → Files, select them all and choose "Upload to /". `main.py` runs at
   every power-on.
3. Restart the board.

## Joining your Wi-Fi

The first time it starts, the lamp has no Wi-Fi saved, so it opens its own
network called **MoonLamp-XXXX**, and the whole moon slowly pulses blue.

1. Join MoonLamp-XXXX from your phone. The setup page should pop up by
   itself; if not, open `http://192.168.4.1`.
2. Tap **Find networks**, pick your home network (2.4 GHz only), enter the
   password and tap **Connect**.
3. Once the lamp has joined, the page shows its new address, with a Copy
   button, and counts down 20 seconds, then the setup network closes and your device goes back
   to your home Wi-Fi. In a normal browser tab the page then moves to
   **http://moon.local** by itself. The small pop-up window that phones and
   Macs open for setup pages closes when the Wi-Fi changes instead, so open
   that address yourself (or the numbered address the page shows, which
   also works on phones that can't open `.local` names).

If the lamp can't reach your Wi-Fi for a minute (a new router, a changed
password), MoonLamp-XXXX opens again so you can fix it, while the lamp keeps
trying the saved network. The setup network has no password, and the lamp
never shows the saved Wi-Fi password on its page.

## The web page

The page opens on tonight's moon, drawn the way the lamp shows it.

- **See other nights** by dragging the moon, tapping the arrows beside it,
  or tapping the month strip underneath (one dot per night, as bright as
  that night's moon, with tonight circled). The lamp follows. Then choose **Keep this phase** to show that
  phase all the time, or **Back to tonight**. **Play a month** runs through
  a whole month in 30 seconds.
- **Power button**: turns the lamp on or off. With a schedule, this lasts
  until the next scheduled change; turning on while it's scheduled off
  lasts up to 4 hours.
- **Brightness** dims the whole moon, lit side and glow together.
- **Moonlight**: Cool, Moon, Warm and Harvest whites, the themes Blood moon,
  Jupiter, Nebula, Rainbow and Aurora (which can move gently), or Custom to
  set the warmth or mix the white and colour LEDs yourself.
- **Dark side**: no glow, or a glow in Ember, Red, Earthshine, Night blue,
  Violet or your own colour.

The rest is a tap away:

- **Schedule and location**: turn on and off by itself at sunset, sunrise or
  set times (with an offset such as 30 minutes before sunset), with a fade.
  Sunrise and sunset need the lamp's latitude and longitude, pasted in
  once; the time zone comes from the phone or computer you open the page on.
  The lamp works out sunrise and sunset itself, to within a minute or two.
- **Dark side glow**: its strength compared with the lit side, and whether
  to show it only around sunrise and sunset, like earthshine on the real
  moon.
- **Calibrate LEDs**, **Wi-Fi** and **Lamp** (network name, how phases are
  drawn, the switch-on sweep, defaults, restart).

Changes show on the moon straight away and save themselves a moment later.
Saved settings live in `settings.json` on the board and take priority over
the defaults at the top of `lamp.py`.

## Setting it up for your moon

Use **Calibrate LEDs** on the page:

- **LEDs on strip**: the number of LEDs on your piece of strip.
- **Light one LED**: step through them to see which chamber each one is in,
  then list each chamber's LEDs, left to right as you face the moon. Leave
  out any LED that sits under a baffle wall and lights two chambers at once.
- **Chamber brightness**: every chamber is given the same total light
  regardless of how many LEDs it has; these sliders correct what is left by
  eye, against a full moon.

### From Thonny

Connect over USB and press Ctrl-C in the Thonny Shell to stop the program.
These helpers still work:

| Command | What it does |
|---|---|
| `walk()` | Lights one LED at a time so you can see which chamber each is in |
| `chamber(0)` | Lights one whole chamber (0 = leftmost, 5 = rightmost) |
| `show(0.5)` | Shows a phase: 0 new, 0.25 first quarter, 0.5 full, 0.75 last |
| `demo()` | Sweeps through a whole month in 30 seconds |
| `startup_sweep()` | Replays the power-on sweep |
| `run()` | Goes back to showing the real phase, with the web page |

Settings can be tried in the Shell too, for example `lamp.BRIGHTNESS = 0.5`
then `show(0.5)`. They apply until the next restart. After changing
`lamp.NUM_LEDS`, `lamp.CHAMBERS` or `lamp.LED0_ON_LEFT`, run `lamp.rebuild()`.

## How it works

- The phase comes from the moon's average cycle length (29.53 days) counted
  from a known new moon. That is typically within about half a day of the
  true phase, which is less than one chamber's worth of difference.
- The shadow edge crosses one chamber per twelfth of the cycle, matching how
  the baffles are cut.
- The clock is set over Wi-Fi at start-up and re-synced twice a day. If Wi-Fi
  drops while it is running, the lamp carries on with its own clock.
- A single dim blue LED means it is waiting for Wi-Fi or internet time.
- The whole moon pulsing blue means the setup network is open and the lamp
  doesn't know the time yet: join MoonLamp-XXXX to set it up.

## Prior art

Earlier versions of this hack replaced the toy's controller with an Arduino
and a real-time clock module:

- [Arduino Controlled Model Moon (Instructables)](https://instructables.com/Arduino-Controlled-Model-Moon-synchronizes-phase-c)
- [Moon light displays realtime phases (Make)](https://makezine.com/?p=61803)
- [Moon phase light modification (Hackaday)](https://hackaday.com/2009/08/19/moon-phase-light-modification)
