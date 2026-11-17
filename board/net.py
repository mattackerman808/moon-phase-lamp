# net.py - Wi-Fi, the setup network and internet time for the moon lamp.
#
# With no Wi-Fi saved, or after a minute without it, the lamp opens its own
# open network called MoonLamp-XXXX. Joining it brings up the setup page
# (or open http://192.168.4.1). Once the lamp is on your Wi-Fi, the setup
# network closes a few seconds later and the page is at http://moon.local.

import asyncio
import socket
import time

import network
import ntptime

import lamp

SETUP_AFTER_S = 60           # open the setup network after this long offline
SETUP_CLOSE_S = 20           # after the setup page has seen the lamp join
SETUP_LINGER_S = 40          # close it this long after joining Wi-Fi, unless
                             # the setup page asks sooner (finish_setup)
RETRY_S = 60                 # try the saved Wi-Fi again this often
RESYNC_EVERY_S = 12 * 3600   # fetch internet time twice a day
SETUP_IP = "192.168.4.1"     # the ESP32's address on its own network

sta = network.WLAN(network.STA_IF)
ap = network.WLAN(network.AP_IF)

synced_at = None             # time.time() of the last internet time sync
_last_try = None             # ticks of the last Wi-Fi connect attempt
_user_until = None           # ticks: a join from the setup page is in progress
_dns_sock = None
_close_at = None             # ticks: close the setup network at this time

_STATUS = (("STAT_GOT_IP", "connected"), ("STAT_CONNECTING", "connecting"),
           ("STAT_WRONG_PASSWORD", "wrong password"),
           ("STAT_NO_AP_FOUND", "network not found"),
           ("STAT_HANDSHAKE_TIMEOUT", "wrong password or weak signal"),
           ("STAT_ASSOC_FAIL", "network refused the lamp"),
           ("STAT_BEACON_TIMEOUT", "lost the network"),
           ("STAT_IDLE", "not connected"))


def _ticks_since(t):
    return time.ticks_diff(time.ticks_ms(), t) if t is not None else None


def setup_name():
    mac = sta.config("mac")
    return "MoonLamp-%02X%02X" % (mac[-2], mac[-1])


def status_text():
    if sta.isconnected():
        return "connected"
    try:
        code = sta.status()
    except Exception:
        return "not connected"
    for name, text in _STATUS:
        if getattr(network, name, None) == code:
            return text
    return "not connected"


def _ap_clients():
    try:
        return len(ap.status("stations"))
    except Exception:
        return 0


def _joining():
    try:
        return sta.status() == getattr(network, "STAT_CONNECTING", None)
    except Exception:
        return False


def join():
    """Start connecting to the saved Wi-Fi (returns straight away)."""
    global _last_try
    _last_try = time.ticks_ms()
    if not lamp.WIFI_SSID:
        return
    sta.active(True)
    try:
        sta.disconnect()
    except OSError:
        pass
    try:
        sta.connect(lamp.WIFI_SSID, lamp.WIFI_PASSWORD)
    except OSError as err:
        print("Wi-Fi:", err)


def set_wifi(ssid, password):
    """Save new Wi-Fi details (from the setup page) and try them."""
    global _user_until
    lamp.apply({"WIFI_SSID": ssid, "WIFI_PASSWORD": password})
    lamp.save(only=["WIFI_SSID", "WIFI_PASSWORD"])
    _user_until = time.ticks_add(time.ticks_ms(), 30000)
    join()


def finish_setup():
    """The setup page has seen the lamp join: close the setup network soon.

    The wait gives people time to read the new address on the page
    (index.html counts down the same SETUP_CLOSE_S).
    """
    global _close_at
    if sta.isconnected() and ap.active():
        _close_at = time.ticks_add(time.ticks_ms(), SETUP_CLOSE_S * 1000)


def scan():
    """Nearby 2.4 GHz networks, strongest first: [(name, signal, locked)]."""
    sta.active(True)
    try:
        found = sta.scan()
    except OSError:
        if sta.isconnected():
            raise
        sta.disconnect()     # an ESP32 can't scan mid-connect
        found = sta.scan()
    best = {}
    for ssid, _, _, rssi, security, _ in found:
        try:
            name = ssid.decode()
        except Exception:
            continue
        if name and (name not in best or rssi > best[name][1]):
            best[name] = (name, rssi, security != 0)
    return sorted(best.values(), key=lambda n: -n[1])


def info():
    connected = sta.isconnected()
    return {
        "ssid": lamp.WIFI_SSID,
        "status": status_text(),
        "connected": connected,
        "ip": sta.ifconfig()[0] if connected else None,
        "hostname": lamp.HOSTNAME,
        "setup": ap.active(),
        "setup_name": setup_name(),
        "setup_ip": SETUP_IP,
        # True while a join from the setup page is still being tried.
        "joining": not connected and _user_until is not None
                   and time.ticks_diff(_user_until, time.ticks_ms()) > 0
                   and _joining(),
        "time_synced": lamp.clock_is_set(),
        "synced_s_ago": time.time() - synced_at if synced_at else None,
    }


# --------------------------------------------------------- Setup network

def start_setup():
    ap.active(True)
    ap.config(essid=setup_name(), authmode=network.AUTH_OPEN)
    lamp.setup_active = True
    asyncio.create_task(_dns_loop())
    print("Setup: join Wi-Fi '%s', then open http://%s"
          % (setup_name(), SETUP_IP))


def stop_setup():
    ap.active(False)
    lamp.setup_active = False
    close()
    print("Setup network closed")


def _dns_reply(req):
    """Answer every name lookup with the lamp's own address.

    That is what makes phones pop up the setup page on their own.
    """
    end = 12
    while end < len(req) and req[end]:
        end += req[end] + 1
    end += 5                 # zero byte, then query type and class
    if end > len(req):
        return None
    is_a = req[end - 4:end - 2] == b"\x00\x01"
    head = req[:2] + b"\x81\x80" + req[4:6] + (b"\x00\x01" if is_a else b"\x00\x00")
    out = head + b"\x00\x00\x00\x00" + req[12:end]
    if is_a:
        out += b"\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04"
        out += bytes([int(x) for x in SETUP_IP.split(".")])
    return out


async def _dns_loop():
    global _dns_sock
    close()
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", 53))
    except OSError as err:
        s.close()
        print("Setup: name server failed:", err)
        return
    s.setblocking(False)
    _dns_sock = s
    while ap.active() and _dns_sock is s:
        try:
            req, addr = s.recvfrom(512)
        except OSError:
            await asyncio.sleep_ms(50)
            continue
        try:
            reply = _dns_reply(req)
            if reply:
                s.sendto(reply, addr)
        except Exception:
            pass


def close():
    """Close the setup network's name server socket."""
    global _dns_sock
    if _dns_sock:
        try:
            _dns_sock.close()
        except OSError:
            pass
        _dns_sock = None


# -------------------------------------------------------------- Loops

async def wifi_loop():
    global _user_until, _close_at
    try:
        network.hostname(lamp.HOSTNAME)
    except Exception:
        pass
    sta.active(True)
    try:
        # Wi-Fi power saving makes the web page slow; the lamp is on mains.
        sta.config(pm=sta.PM_NONE)
    except Exception:
        pass
    if ap.active():          # left over from before a soft restart
        ap.active(False)
    join()
    offline_since = time.ticks_ms()
    linger_since = None
    while True:
        if _user_until is not None and time.ticks_diff(_user_until, time.ticks_ms()) <= 0:
            _user_until = None
        if sta.isconnected():
            if offline_since is not None:
                print("Wi-Fi: connected,", sta.ifconfig()[0])
            offline_since = None
            _user_until = None
            if ap.active():
                if linger_since is None:
                    linger_since = time.ticks_ms()
                elif (_ticks_since(linger_since) >= SETUP_LINGER_S * 1000 or
                      (_close_at is not None and
                       time.ticks_diff(_close_at, time.ticks_ms()) <= 0)):
                    stop_setup()
                    linger_since = None
                    _close_at = None
        else:
            linger_since = None
            _close_at = None
            if offline_since is None:
                offline_since = time.ticks_ms()
            if not ap.active() and (not lamp.WIFI_SSID or
                                    _ticks_since(offline_since) >= SETUP_AFTER_S * 1000):
                start_setup()
            if ap.active() and _ap_clients() and _user_until is None:
                # Someone is on the setup page. Searching for the saved
                # network would hop channels and drop their phone.
                if _joining():
                    sta.disconnect()
            elif (lamp.WIFI_SSID and not _joining()
                  and _ticks_since(_last_try) >= RETRY_S * 1000):
                join()
        await asyncio.sleep(1)


async def clock_loop():
    global synced_at
    while True:
        wait = 5
        if sta.isconnected():
            try:
                ntptime.settime()
                synced_at = time.time()
                print("Time synced (UTC):", time.gmtime()[:6])
                wait = RESYNC_EVERY_S
            except Exception as err:
                print("Time sync failed:", err)
                wait = 60
        await asyncio.sleep(wait)
