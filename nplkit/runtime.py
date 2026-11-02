# NPL Cricket runtime: boots straight into the app on a stock UIFlow2
# Cardputer ADV. Gives the app the same `ctx` that CardOS does (keyboard,
# screen, key clicks, screen sleep) and keeps WiFi and the clock up in the
# background, since there is no home screen or status bar to do it.
import gc
import time
import machine
import network
import esp32
import M5
from M5 import Lcd
from nplkit import config as C
from nplkit import keys as K
from nplkit import settings

NTP_HOSTS = ("pool.ntp.org", "time.google.com", "time.cloudflare.com")
WIFI_RETRY_MS = 30000
NTP_RETRY_MS = 10000

SCREEN_ON, SCREEN_DIM, SCREEN_OFF = 0, 1, 2


def saved_wifi():
    """(ssid, password) saved in the UIFlow settings, or (None, None)."""
    try:
        nvs = esp32.NVS("uiflow")
        return nvs.get_str("ssid0"), nvs.get_str("pswd0")
    except OSError:
        return None, None


def clock_set():
    return time.localtime()[0] >= 2024


def sync_time():
    """Set the RTC to local time from NTP. Returns True on success."""
    import ntptime
    for host in NTP_HOSTS:
        try:
            ntptime.host = host
            ntptime.settime()  # sets RTC to UTC
            t = time.localtime(time.time() + settings.get("tz") * 60)
            machine.RTC().datetime((t[0], t[1], t[2], t[6], t[3], t[4], t[5], 0))
            return True
        except Exception as e:
            print("ntp sync failed:", host, e)
    return False


class Net:
    """Joins the saved WiFi, re-joins if it drops, and sets the clock once."""

    def __init__(self):
        self.wlan = network.WLAN(network.STA_IF)
        self.ssid, self._pswd = saved_wifi()
        self._next_join = 0
        self._next_ntp = 0
        try:
            network.country(C.WIFI_COUNTRY)
        except Exception as e:
            print("wifi country:", e)
        try:
            self.wlan.active(True)
            self.wlan.config(reconnects=2)
        except Exception as e:
            print("wifi:", e)

    def connected(self):
        return self.wlan.isconnected()

    def update(self):
        now = time.ticks_ms()
        if not self.wlan.isconnected():
            if self.ssid and time.ticks_diff(now, self._next_join) >= 0:
                self._next_join = time.ticks_add(now, WIFI_RETRY_MS)
                try:
                    if self.wlan.status() != network.STAT_CONNECTING:
                        self.wlan.disconnect()
                        self.wlan.connect(self.ssid, self._pswd)
                except Exception as e:
                    print("wifi connect:", e)
        elif not clock_set() and time.ticks_diff(now, self._next_ntp) >= 0:
            self._next_ntp = time.ticks_add(now, NTP_RETRY_MS)
            sync_time()


class Context:
    """What the app gets: the same names CardOS hands to its apps."""
    TOP = 0
    BOTTOM = C.H
    W = C.W
    ESC = K.ESC
    ENTER = K.ENTER
    LEFT = K.LEFT
    RIGHT = K.RIGHT
    UP = K.UP
    DOWN = K.DOWN
    BACKSPACE = K.BACKSPACE

    def __init__(self, kb, net):
        self.lcd = Lcd
        self.config = C
        self.net = net
        self._kb = kb
        self.click = settings.get("click")
        self.keep_awake = False
        self._last_input = time.ticks_ms()
        self._screen = SCREEN_ON

    def tick(self):
        """Call once per loop: keeps WiFi up, returns new key presses."""
        M5.update()
        pressed = self._kb.poll() if self._kb else []
        now = time.ticks_ms()
        if pressed:
            self._last_input = now
            if self._screen != SCREEN_ON:
                self.wake()
                pressed = []  # the key that wakes the screen does nothing else
        elif not self.keep_awake:
            self._check_sleep(now)
        if pressed and self.click:
            self._click(pressed[-1])
        self.net.update()
        return pressed

    def _check_sleep(self, now):
        timeout = settings.get("sleep") * 1000
        if timeout <= 0 or self._screen == SCREEN_OFF:
            return
        idle = time.ticks_diff(now, self._last_input)
        if idle >= timeout:
            Lcd.setBrightness(0)
            self._screen = SCREEN_OFF
        elif self._screen == SCREEN_ON and idle >= timeout - min(10000, timeout // 2):
            Lcd.setBrightness(max(8, settings.get("brightness") // 4))
            self._screen = SCREEN_DIM

    def wake(self):
        self._last_input = time.ticks_ms()
        if self._screen != SCREEN_ON:
            Lcd.setBrightness(settings.get("brightness"))
            self._screen = SCREEN_ON

    def _click(self, key):
        freq = (C.CLICK_FREQ_ENTER if key == K.ENTER else
                C.CLICK_FREQ_ESC if key == K.ESC else C.CLICK_FREQ)
        try:
            M5.Speaker.tone(freq, C.CLICK_MS)
        except Exception:
            pass

    def fullscreen(self, on=True):
        pass  # always full screen: there are no bars

    def clear(self, color=C.BG):
        Lcd.fillRect(0, self.TOP, self.W, self.BOTTOM - self.TOP, color)


def _splash(lines, color=C.FG):
    Lcd.fillScreen(C.BG)
    try:
        Lcd.drawBmp("/flash/res/npl/icon_56.bmp", (C.W - 56) // 2, 8)
    except Exception:
        pass
    Lcd.setFont(Lcd.FONTS.DejaVu12)
    y = 74
    for i, line in enumerate(lines):
        Lcd.setTextColor(color if i == 0 else C.DIM, C.BG)
        Lcd.drawCenterString(line, C.W // 2, y)
        y += 17


def _wait_online(ctx, seconds=20):
    """Show a splash until WiFi and the clock are ready (or a key / timeout)."""
    net = ctx.net
    if not net.ssid:
        _splash(("No WiFi saved", "On your computer run:", "python install.py --wifi"), C.YELLOW)
        time.sleep_ms(4000)
        return
    end = time.ticks_add(time.ticks_ms(), seconds * 1000)
    dots = 0
    while time.ticks_diff(end, time.ticks_ms()) > 0:
        if net.connected() and clock_set():
            return
        step = "Setting the clock" if net.connected() else "Connecting to " + net.ssid[:20]
        _splash((step + "." * (dots % 4), "any key: skip"))
        dots += 1
        if ctx.tick():
            return
        time.sleep_ms(400)


def start():
    M5.begin()
    K.silence_irq()  # M5.begin() may re-arm the firmware keyboard IRQ
    try:
        M5.Speaker.begin()
    except Exception as e:
        print("speaker init failed:", e)
    settings.apply()
    try:
        kb = K.Keyboard()
    except Exception as e:
        print("keyboard init failed:", e)
        kb = None
    ctx = Context(kb, Net())
    _wait_online(ctx)
    from nplkit import npl
    while True:  # Esc on the main screen just reopens the app
        gc.collect()
        npl.run(ctx)
