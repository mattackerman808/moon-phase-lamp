# web.py - the lamp's web page and the small JSON API behind it.
#
#   GET  /              the page (index.html)
#   GET  /api/state     settings, what the moon is showing, Wi-Fi status
#   GET  /api/scan      nearby Wi-Fi networks
#   POST /api/settings  {"BRIGHTNESS": 0.5, ...}  use now, not saved yet
#                       (add "glance": 0.5 to show the result on that phase
#                       for a moment, in the same step)
#   POST /api/save      write the current settings to settings.json
#                       ({"only": ["TZ_NAME", ...]} saves just those)
#   POST /api/revert    go back to the saved settings
#   POST /api/defaults  go back to the values in lamp.py (keeps Wi-Fi)
#   POST /api/show      {"phase": 0.5} | {"glance": 0.5} | {"demo": true} | {"led": 3} |
#                       {"chamber": 2} | {} for tonight
#   POST /api/power     {"on": true | false | null}  null = follow the schedule
#   POST /api/wifi      {"ssid": "...", "password": "..."}
#   POST /api/setup-done  close the setup network now the lamp has joined
#   POST /api/restart

import asyncio
import gc
import json
import os

import machine

import lamp
import net

PORT = 80
PAGE = "index.html"
_server = None


async def serve():
    global _server
    _server = await asyncio.start_server(_client, "0.0.0.0", PORT)
    print("Web page on port", PORT)


async def stop():
    """Close the web server (used when the program is stopped)."""
    global _server
    if _server:
        _server.close()
        await _server.wait_closed()
        _server = None


async def _client(reader, writer):
    try:
        await asyncio.wait_for(_handle(reader, writer), 15)
    except asyncio.TimeoutError:
        pass
    except Exception as err:
        print("Web:", repr(err))
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass
    gc.collect()


async def _send(writer, status, body=b"", ctype="application/json", extra=""):
    if isinstance(body, str):
        body = body.encode()
    writer.write(("HTTP/1.0 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n"
                  "Cache-Control: no-store\r\nConnection: close\r\n%s\r\n"
                  % (status, ctype, len(body), extra)).encode())
    if body:
        writer.write(body)
    await writer.drain()


async def _send_json(writer, data, status="200 OK"):
    await _send(writer, status, json.dumps(data))


async def _send_page(writer):
    size = os.stat(PAGE)[6]
    writer.write(("HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                  "Content-Length: %d\r\nCache-Control: no-store\r\n"
                  "Connection: close\r\n\r\n" % size).encode())
    with open(PAGE, "rb") as f:
        while True:
            chunk = f.read(4096)
            if not chunk:
                break
            writer.write(chunk)
            await writer.drain()


def state():
    settings = {k: getattr(lamp, k) for k in lamp.SETTINGS if k != "WIFI_PASSWORD"}
    return {
        "settings": settings,
        "unsaved": lamp.unsaved(),
        "showing": lamp.showing(),
        "phase": lamp.shown_phase(),
        "tonight": lamp.moon_phase() if lamp.clock_is_set() else None,
        "schedule": lamp.schedule_info(),
        "theme": lamp.theme_colors(),
        "wifi": net.info(),
    }


async def _handle(reader, writer):
    line = await reader.readline()
    try:
        method, path, _ = line.decode().split(" ", 2)
    except ValueError:
        return
    path = path.split("?", 1)[0]
    length = 0
    while True:
        h = await reader.readline()
        if h in (b"\r\n", b"\n", b""):
            break
        h = h.decode().lower()
        if h.startswith("content-length:"):
            length = int(h[15:])
    if length > 2048:
        return await _send_json(writer, {"error": "too big"}, "413 Too Large")
    body = await reader.readexactly(length) if length else b""

    if method == "GET" and path in ("/", "/index.html"):
        return await _send_page(writer)
    if not path.startswith("/api/"):
        if lamp.setup_active:
            # Phones check a known address to see if they are online. Send
            # those checks to the setup page so it pops up by itself.
            return await _send(writer, "302 Found", ctype="text/plain",
                               extra="Location: http://%s/\r\n" % net.SETUP_IP)
        return await _send(writer, "404 Not Found", "Not found", "text/plain")

    try:
        data = json.loads(body) if body else {}
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        result = _api(method, path, data)
    except ValueError as err:
        return await _send_json(writer, {"error": str(err)}, "400 Bad Request")
    except KeyError:
        return await _send_json(writer, {"error": "not found"}, "404 Not Found")
    except OSError as err:
        return await _send_json(writer, {"error": "lamp error %s" % err},
                                "500 Server Error")
    await _send_json(writer, result)
    if path == "/api/restart":
        await asyncio.sleep_ms(500)
        machine.reset()


def _api(method, path, data):
    if method == "GET" and path == "/api/state":
        return state()
    if method == "GET" and path == "/api/scan":
        return [{"ssid": s, "rssi": r, "locked": l} for s, r, l in net.scan()]
    if method != "POST":
        raise KeyError(path)
    if path == "/api/settings":
        for k in ("WIFI_SSID", "WIFI_PASSWORD"):
            if k in data:
                raise ValueError("%s: use the Wi-Fi section" % k)
        glance = data.pop("glance", None)
        if glance is not None:
            # Set the glance first so the new look is drawn straight onto it.
            lamp.hold("glance", lamp._num(glance, 0.0, 1.0), lamp.GLANCE_S)
        lamp.apply(data)
    elif path == "/api/save":
        only = data.get("only")
        if only is not None:
            if not isinstance(only, list) or any(k not in lamp.SETTINGS for k in only):
                raise ValueError("only: expected a list of setting names")
        lamp.save(only)
    elif path == "/api/revert":
        lamp.revert()
    elif path == "/api/defaults":
        lamp.defaults()
    elif path == "/api/show":
        _show(data)
    elif path == "/api/power":
        on = data.get("on")
        if on not in (True, False, None):
            raise ValueError("on: expected true, false or null")
        lamp.set_power(on)
    elif path == "/api/wifi":
        ssid = data.get("ssid")
        password = data.get("password", "")
        if not isinstance(ssid, str) or not ssid:
            raise ValueError("ssid: pick a network")
        net.set_wifi(ssid, password)
    elif path == "/api/setup-done":
        net.finish_setup()
    elif path == "/api/restart":
        return {"ok": True}
    else:
        raise KeyError(path)
    return state()


def _show(data):
    if "glance" in data:
        lamp.hold("glance", lamp._num(data["glance"], 0.0, 1.0), lamp.GLANCE_S)
    elif "phase" in data:
        lamp.hold("phase", lamp._num(data["phase"], 0.0, 1.0))
    elif data.get("demo"):
        lamp.hold("demo", seconds=lamp.DEMO_S + 1)
    elif "led" in data:
        lamp.hold("led", int(lamp._num(data["led"], 0, lamp.NUM_LEDS - 1)))
    elif "chamber" in data:
        lamp.hold("chamber", int(lamp._num(data["chamber"], 0, 5)))
    else:
        lamp.release()
