# CardOS keyboard: Cardputer ADV (TCA8418 over I2C, polled -- NOT the
# firmware IRQ, which storms and corrupts the SD SPI bus).
# Driver adapted from kamrrillo/Cardputer-ADV-Keyboard (MIT).
from machine import Pin, SoftI2C

# Key names returned by Keyboard.poll()
ESC = "KEY_ESC"      # top-left ` / Esc key
LEFT = "KEY_LEFT"    # ,
RIGHT = "KEY_RIGHT"  # /
UP = "KEY_UP"        # ;
DOWN = "KEY_DOWN"    # .
ENTER = "\n"
BACKSPACE = "\x08"
TAB = "KEY_TAB"

_TCA_ADDR = 0x34
_REG_CFG = 0x01
_REG_INT = 0x02
_REG_FIFO = 0x04
_REG_KP_GP1 = 0x1D
_REG_KP_GP2 = 0x1E
_REG_KP_GP3 = 0x1F
_REG_GPI_EM1 = 0x09
_PIN_SDA, _PIN_SCL, _PIN_IRQ = 8, 9, 11

# keycode -> (normal, fn-layer)
KEYMAP = {
    1: (ESC, ESC), 5: ("1", "!"), 11: ("2", "@"), 15: ("3", "#"),
    21: ("4", "$"), 25: ("5", "%"), 31: ("6", "^"), 35: ("7", "&"),
    41: ("8", "*"), 45: ("9", "("), 51: ("0", ")"), 55: ("-", "_"),
    61: ("=", "+"), 65: (BACKSPACE, BACKSPACE),
    2: (TAB, TAB), 6: ("q", "Q"), 12: ("w", "W"), 16: ("e", "E"),
    22: ("r", "R"), 26: ("t", "T"), 32: ("y", "Y"), 36: ("u", "U"),
    42: ("i", "I"), 46: ("o", "O"), 52: ("p", "P"), 56: ("[", "{"),
    62: ("]", "}"), 66: ("\\", "|"),
    3: ("KEY_FN", "KEY_FN"), 7: ("KEY_CAPS", "KEY_CAPS"), 13: ("a", "A"),
    17: ("s", "S"), 23: ("d", "D"), 27: ("f", "F"), 33: ("g", "G"),
    37: ("h", "H"), 43: ("j", "J"), 47: ("k", "K"), 53: ("l", "L"),
    57: (UP, ";"), 63: ("'", '"'), 67: (ENTER, ENTER),
    4: ("KEY_CTRL", "KEY_CTRL"), 8: ("KEY_OPT", "KEY_OPT"), 14: ("KEY_ALT", "KEY_ALT"),
    18: ("z", "Z"), 24: ("x", "X"), 28: ("c", "C"), 34: ("v", "V"),
    38: ("b", "B"), 44: ("n", "N"), 48: ("m", "M"),
    54: (LEFT, ","), 58: (DOWN, "."), 64: (RIGHT, "/"),
    68: (" ", " "),
}


class Keyboard:
    def __init__(self, sda=_PIN_SDA, scl=_PIN_SCL, irq=_PIN_IRQ, freq=400000):
        self._pins = (scl, sda, freq)
        self._i2c = SoftI2C(scl=Pin(scl), sda=Pin(sda), freq=freq)
        self._irq = Pin(irq, Pin.IN, Pin.PULL_UP)
        self._addr = _TCA_ADDR
        self.fn = False
        self.caps = False
        self._buf = []
        self._init_tca()

    def _wr(self, reg, val):
        self._i2c.writeto_mem(self._addr, reg, bytes([val]))

    def _rd(self, reg):
        return self._i2c.readfrom_mem(self._addr, reg, 1)[0]

    def _init_tca(self):
        self._wr(_REG_KP_GP1, 0xFF)
        self._wr(_REG_KP_GP2, 0xFF)
        self._wr(_REG_KP_GP3, 0x00)
        self._wr(_REG_GPI_EM1, 0x00)
        self._wr(_REG_CFG, 0x3E)

    def _drain_fifo(self):
        for _ in range(16):
            evt = self._rd(_REG_FIFO)
            if evt == 0:
                break
            self._process(evt & 0x7F, bool(evt & 0x80))
        self._wr(_REG_INT, 0xFF)

    def _process(self, keynum, pressed):
        entry = KEYMAP.get(keynum)
        if entry is None:
            return
        normal, with_fn = entry
        if normal == "KEY_FN":
            self.fn = pressed
            return
        if normal == "KEY_CAPS":
            if pressed:
                self.caps = not self.caps
            return
        if normal in ("KEY_CTRL", "KEY_OPT", "KEY_ALT"):
            return
        if not pressed:
            return
        if self.fn:
            char = with_fn
        elif self.caps and len(normal) == 1 and normal.isalpha():
            char = normal.upper()
        else:
            char = normal
        self._buf.append(char)

    def poll(self):
        """Return the list of keys pressed since the last poll."""
        try:
            if self._irq.value() == 0 or self._rd(_REG_INT) & 0x01:
                self._drain_fifo()
        except OSError:
            # The audio chip shares these I2C pins; starting/stopping the
            # speaker or mic hands them to the firmware's I2C. Take them back.
            try:
                scl, sda, freq = self._pins
                self._i2c = SoftI2C(scl=Pin(scl), sda=Pin(sda), freq=freq)
                if self._rd(_REG_INT) & 0x01:
                    self._drain_fifo()
            except Exception as e:
                print("kb poll err", e)
        result = self._buf[:]
        self._buf.clear()
        return result


def silence_irq():
    """Disable the firmware's GPIO11 keyboard IRQ so it can't storm the bus."""
    try:
        Pin(_PIN_IRQ, Pin.IN, Pin.PULL_UP).irq(handler=None)
    except Exception as e:
        print("silence kb irq:", e)
