# CardOS SD card service: mount the TF card at /sd (shared by all apps).
#
#   from nplkit import sd
#   if sd.mount():          # safe to call many times; mounts only once
#       os.listdir(sd.ROOT)
#
# Uses the firmware's machine.SDCard in SPI mode. Slot 3 shares the SPI
# host with the display (the firmware's own UIFlow setup does the same).
import os
import machine

ROOT = "/sd"

# --- SD card wiring (Cardputer / StampS3) ---
SD_SCK, SD_MISO, SD_MOSI, SD_CS = 40, 39, 14, 12

_card = None  # keep a reference so the driver isn't garbage-collected


def is_mounted():
    try:
        os.listdir(ROOT)
        return True
    except OSError:
        return False


def mount():
    """Mount the card at /sd. Returns True if it is (or already was) mounted."""
    global _card
    if is_mounted():
        return True
    try:
        os.umount(ROOT)  # clear a stale mount left by a removed card
    except OSError:
        pass
    last = None
    for slot in (3, 2):
        for freq in (20000000, 4000000):
            card = None
            try:
                card = machine.SDCard(slot=slot, sck=SD_SCK, miso=SD_MISO,
                                      mosi=SD_MOSI, cs=SD_CS, freq=freq)
                os.mount(card, ROOT)
                _card = card
                print("SD mounted (slot=%d freq=%d)" % (slot, freq))
                return True
            except Exception as e:
                last = e
                try:
                    if card:
                        card.deinit()
                except Exception:
                    pass
    print("SD mount failed:", last)
    return False


def unmount():
    """Unmount and release the SD driver (frees ~20 KB of system RAM, e.g. for TLS)."""
    global _card
    try:
        os.umount(ROOT)
    except OSError:
        pass
    if _card is not None:
        try:
            _card.deinit()
        except Exception:
            pass
        _card = None
