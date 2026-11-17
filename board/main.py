# main.py - starts the Moon in My Room lamp. The board runs it at power-on.
#
# Settings are on the lamp's web page (http://moon.local), with their
# defaults at the top of lamp.py.
#
# To experiment, connect over USB and press Ctrl-C to stop it, then try:
#   walk()           step through the LEDs one at a time (to fill in CHAMBERS)
#   chamber(0)       light one whole chamber, 0 = leftmost ... 5 = rightmost
#   show(0.5)        display a phase: 0 new, 0.25 first quarter, 0.5 full, 0.75 last
#   demo()           sweep through a whole month in 30 seconds
#   startup_sweep()  replay the power-on sweep
#   run()            go back to showing the real phase, with the web page
# Settings can be tried here too, e.g. lamp.BRIGHTNESS = 0.5, then show(0.5).

import asyncio

import lamp
import net
import web
from lamp import chamber, demo, off, show, startup_sweep, test, walk


async def _main():
    asyncio.create_task(net.wifi_loop())
    await web.serve()
    # If there is no Wi-Fi saved, there is nothing to wait for.
    await lamp.startup_sweep_async(lambda: not lamp.WIFI_SSID or net.sta.isconnected())
    asyncio.create_task(net.clock_loop())
    await lamp.display_loop()


def run():
    asyncio.new_event_loop()
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        # Close the web server so run() can open it again.
        net.close()
        asyncio.run(web.stop())
        asyncio.new_event_loop()
        print("Stopped. Try walk(), chamber(0), show(0.5), demo(), or run().")


lamp.load()
run()
