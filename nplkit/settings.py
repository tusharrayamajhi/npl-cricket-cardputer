# NPL Cricket settings, read from config.py.
#
#   from nplkit import settings
#   settings.get("tz")            # minutes from UTC
#
# WiFi name/password are NOT kept here: they live in the UIFlow settings
# (NVS "ssid0"/"pswd0"), set by `python install.py --wifi`.
from nplkit import config as C

_DATA = {
    "brightness": C.BRIGHTNESS,
    "volume": C.CLICK_VOLUME,
    "click": C.KEY_CLICK,
    "tz": C.TZ_OFFSET_MIN,
    "sleep": C.SLEEP_SEC,
}


def get(key):
    return _DATA[key]


def apply():
    """Push brightness and volume to the hardware (called at boot)."""
    import M5
    try:
        M5.Lcd.setBrightness(get("brightness"))
    except Exception as e:
        print("brightness:", e)
    try:
        M5.Speaker.setVolume(get("volume"))
    except Exception as e:
        print("volume:", e)
