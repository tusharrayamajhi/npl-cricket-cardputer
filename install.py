"""Install CardOS, or the NPL Cricket app on its own, on an M5Stack Cardputer ADV.

    python install.py              check the device, then install and reboot
    python install.py --check      only run the checks, change nothing
    python install.py --wifi       only change the WiFi name and password, then reboot
    python install.py --port COM5  use this serial port (default: auto-detect)
    python install.py --no-sd      install without the SD card files
    python install.py --no-reset   don't reboot when done
    python install.py --restore    put back the main.py that was there before

The same file ships in both repos: next to cardos/ + apps/ it installs CardOS,
next to nplkit/ it installs NPL Cricket on its own.

Needs Python 3.8+ on the computer and UIFlow2 firmware on the Cardputer ADV.
mpremote and mpy-cross are installed into tools/mpyx (not system-wide) if missing.
"""
import argparse
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
LIB = "cardos" if os.path.isdir(os.path.join(ROOT, "cardos")) else "nplkit"
PRODUCT = "CardOS" if LIB == "cardos" else "NPL Cricket"
HAS_APPS = os.path.isdir(os.path.join(ROOT, "apps"))
TOOLS = os.path.join(ROOT, "tools", "mpyx")
BUILD = os.path.join(ROOT, "build")
MPY_CROSS = "mpy-cross==1.27.0.post2"   # matches UIFlow2 2.5.x (MicroPython 1.27)
ESPRESSIF_VID = 0x303A                  # USB vendor id of the ESP32-S3
BACKUP = "/flash/main_before_%s.py" % LIB
BACKUP_BOOT = "/flash/main_before_%s.boot" % LIB   # UIFlow boot option from before
SECRETS = os.path.join(ROOT, "secrets.json")

# Runs on the Cardputer: reports what we need to know as one JSON line.
PROBE = r"""
import sys, os, gc, json
r = {'machine': os.uname().machine, 'version': os.uname().version,
     'mpy': getattr(sys.implementation, '_mpy', 0)}
try:
    import M5
    r['uiflow'] = True
except ImportError:
    r['uiflow'] = False
try:
    from machine import Pin, SoftI2C
    r['adv'] = 0x34 in SoftI2C(scl=Pin(9), sda=Pin(8), freq=100000).scan()
except Exception:
    r['adv'] = False
s = os.statvfs('/flash')
r['flash_free'] = s[0] * s[3]
try:
    r['main'] = open('/flash/main.py').read(300)
except OSError:
    r['main'] = None
try:
    r['wifi'] = __import__('esp32').NVS('uiflow').get_str('ssid0')
except Exception:
    r['wifi'] = None
try:
    os.stat('%s')
    r['backup'] = True
except OSError:
    r['backup'] = False
def sd_free():
    # the card object must outlive this function: if it is garbage-collected
    # the SD driver shuts down under the mounted card and the board crashes
    global _cardos_sd
    try:
        os.listdir('/sd')
    except OSError:
        import machine
        try:
            os.umount('/sd')
        except OSError:
            pass
        ok = False
        for slot in (3, 2):
            for freq in (20000000, 4000000):
                try:
                    c = machine.SDCard(slot=slot, sck=40, miso=39, mosi=14, cs=12, freq=freq)
                    os.mount(c, '/sd')
                    _cardos_sd = c
                    ok = True
                    break
                except Exception:
                    pass
            if ok:
                break
        if not ok:
            return None
    s = os.statvfs('/sd')
    return s[0] * s[3]
r['sd_free'] = sd_free()
gc.collect()
r['ram_free'] = gc.mem_free()
print('@@PROBE' + json.dumps(r))
""" % BACKUP


def say(msg, mark=" "):
    print("%s %s" % (mark, msg))


def ok(msg):
    say(msg, "[ OK ]")


_connected = None   # port we have talked to (talking to it pauses whatever it was running)


def fail(msg, hint=None):
    say(msg, "[FAIL]")
    if hint:
        for line in hint.strip().splitlines():
            print("        " + line)
    if _connected:
        restart(_connected)   # don't leave the Cardputer paused at the Python prompt
    sys.exit(1)


def warn(msg):
    say(msg, "[WARN]")


# ---------------------------------------------------------------- tools on the PC

def ensure_tools():
    """mpremote + mpy-cross, from the system or from tools/mpyx."""
    if TOOLS not in sys.path:
        sys.path.insert(0, TOOLS)
    missing = []
    for mod, pkg in (("mpremote", "mpremote"), ("mpy_cross", MPY_CROSS)):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        say("Installing %s into tools/mpyx ..." % ", ".join(missing))
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
                            "--target", TOOLS] + missing)
        if r.returncode:
            fail("Could not install " + ", ".join(missing),
                 "Install them yourself:  python -m pip install mpremote " + MPY_CROSS)
    ok("PC tools ready (mpremote, mpy-cross)")


def env():
    e = dict(os.environ)
    e["PYTHONPATH"] = TOOLS + os.pathsep + e.get("PYTHONPATH", "")
    e["PYTHONIOENCODING"] = "utf-8"
    return e


def mpremote(port, *args, check=True):
    """Run mpremote on the device; returns its output text."""
    cmd = [sys.executable, "-m", "mpremote", "connect", port, "resume"] + list(args)
    r = subprocess.run(cmd, env=env(), capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = r.stdout + r.stderr
    global _connected
    if r.returncode == 0:
        _connected = port
    if check and r.returncode:
        fail("mpremote failed:\n" + out.strip()[-800:],
             "Unplug and replug the Cardputer, close anything else using the port\n"
             "(Thonny, Arduino IDE, another terminal), then run the installer again.")
    return out


# ---------------------------------------------------------------- device checks

def find_port(wanted):
    if wanted:
        return wanted
    from serial.tools import list_ports
    ports = [p for p in list_ports.comports() if p.vid == ESPRESSIF_VID]
    if not ports:
        fail("No Cardputer found on USB.",
             "- Plug it in with a USB-C data cable (some cables only charge).\n"
             "- Turn it on. If it still doesn't show up, hold the G0 button while\n"
             "  plugging in, or restart it while connected.\n"
             "- Or pass the port yourself:  python install.py --port COM5")
    if len(ports) > 1:
        fail("More than one ESP32 device is connected: " + ", ".join(p.device for p in ports),
             "Pick one:  python install.py --port " + ports[0].device)
    ok("Cardputer found on " + ports[0].device)
    return ports[0].device


def probe(port):
    out = mpremote(port, "exec", PROBE)
    for line in out.splitlines():
        if line.startswith("@@PROBE"):
            return json.loads(line[7:])
    fail("The Cardputer didn't answer the check:\n" + out.strip()[-800:],
         "Is UIFlow2 (MicroPython) firmware installed? See the README.")


def compiled_header(paths):
    """mpy version our files need, as sys.implementation._mpy encodes it.

    Byte 2 (sub-version + CPU) is only set in files with native/viper code,
    so take it from one of those (e.g. jsonstream.mpy)."""
    best = 0
    for p in paths:
        with open(p, "rb") as f:
            h = f.read(3)
        best = max(best, h[1] | (h[2] << 8))
    return best


def check_device(info, mpy_files, need_flash, need_sd, use_sd):
    if "Cardputer" not in info["machine"]:
        fail("This board is '%s', not a Cardputer." % info["machine"])
    if not info["uiflow"]:
        fail("UIFlow2 firmware not found (no M5 module).",
             "Flash 'UIFlow2.0 Cardputer' with M5Burner first - see the README.")
    ok("Firmware: %s (UIFlow2)" % info["version"])
    if not info["adv"]:
        fail("Cardputer ADV keyboard not found.",
             "%s supports the Cardputer ADV only. The original Cardputer has a\n"
             "different keyboard and won't work yet." % PRODUCT)
    ok("Board: Cardputer ADV")
    want = compiled_header(mpy_files)
    if info["mpy"] & 0xFF != want & 0xFF or (want >> 8 and info["mpy"] >> 8 != want >> 8):
        fail("MicroPython version mismatch (device mpy 0x%x, %s built for 0x%x)." % (info["mpy"], PRODUCT, want),
             "Update the Cardputer to the latest UIFlow2 for Cardputer (MicroPython 1.27)\n"
             "with M5Burner, then run the installer again.")
    ok("MicroPython version matches")
    if info["flash_free"] < need_flash:
        fail("Not enough flash space: %d KB free, %d KB needed."
             % (info["flash_free"] // 1024, need_flash // 1024),
             "Delete old programs from the Cardputer (e.g. with Thonny) and try again.")
    ok("Flash space: %d KB free, %d KB needed" % (info["flash_free"] // 1024, need_flash // 1024))
    if use_sd:
        if info["sd_free"] is None:
            fail("No SD card found.",
                 "Insert a FAT32 microSD card (any size up to 32 GB works) and try again.\n"
                 "The NPL app keeps team pages and photos on it.\n"
                 "To install without it:  python install.py --no-sd")
        if info["sd_free"] < need_sd:
            fail("SD card is full: %d KB free, %d KB needed." % (info["sd_free"] // 1024, need_sd // 1024))
        ok("SD card: %d MB free" % (info["sd_free"] // (1024 * 1024)))


# ---------------------------------------------------------------- build + upload

def rel(path):
    return os.path.relpath(path, ROOT).replace("\\", "/")


def compile_all():
    """Compile <lib>/*.py -> build/<lib> and apps/*.py -> build/mpy.
    Returns (lib .mpy files, app .mpy files)."""
    out = []
    for src, dst in ((LIB, LIB), ("apps", "mpy")):
        if not os.path.isdir(os.path.join(ROOT, src)):
            out.append([])
            continue
        d = os.path.join(BUILD, dst)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            if f.endswith(".mpy"):
                os.remove(os.path.join(d, f))
        files = []
        for f in sorted(os.listdir(os.path.join(ROOT, src))):
            if not f.endswith(".py"):
                continue
            o = os.path.join(d, f[:-3] + ".mpy")
            r = subprocess.run([sys.executable, "-m", "mpy_cross", "-march=xtensawin", "-o", o,
                                os.path.join(ROOT, src, f)], env=env(), capture_output=True, text=True)
            if r.returncode:
                fail("Compile failed: %s/%s\n%s" % (src, f, r.stderr))
            files.append(o)
        out.append(files)
    return out


def tree(folder):
    """All files under ROOT/folder, as (local path, path relative to folder)."""
    base = os.path.join(ROOT, folder)
    for dirpath, _, names in os.walk(base):
        for n in sorted(names):
            p = os.path.join(dirpath, n)
            yield p, os.path.relpath(p, base).replace("\\", "/")


def plan_files(lib_mpys, app_mpys, use_sd):
    """[(local, remote)] for flash, and for the SD card."""
    flash = [(p, "/flash/libs/%s/%s" % (LIB, os.path.basename(p))) for p in lib_mpys]
    if HAS_APPS:
        # apps keep their .py (the launcher reads NAME/ICON from it) and load the .mpy
        flash += [(os.path.join(ROOT, "apps", f), "/flash/apps/" + f)
                  for f in sorted(os.listdir(os.path.join(ROOT, "apps"))) if f.endswith(".py")]
        flash += [(p, "/flash/apps/mpy/" + os.path.basename(p)) for p in app_mpys]
    flash += [(p, "/flash/res/" + r) for p, r in tree("res")]
    flash.append((os.path.join(ROOT, "main.py"), "/flash/main.py"))
    if os.path.exists(SECRETS):
        flash.append((SECRETS, "/flash/cardos_secrets.json"))
    sd = [(p, "/sd/" + r) for p, r in tree("sd")] if use_sd else []
    return flash, sd


def size(files):
    return sum(os.path.getsize(p) for p, _ in files)


def upload(port, flash, sd, info):
    dirs = sorted({r.rsplit("/", 1)[0] for _, r in flash + sd})
    # the SD card must be mounted before folders are made on it
    sd_mount = PROBE.split("def sd_free():")[1].split("r['sd_free']")[0]
    mount = "import os\ndef sd_free():" + sd_mount + "sd_free()\n" if sd else ""
    prep = mount + ("import os\n"
            "def md(p):\n"
            " q = ''\n"
            " for part in p.strip('/').split('/'):\n"
            "  q += '/' + part\n"
            "  try: os.mkdir(q)\n"
            "  except OSError: pass\n"
            "for d in %r: md(d)\n"
            # a .py next to a .mpy would win, so the library folder keeps only .mpy files
            "for f in os.listdir(%r):\n"
            " if f.endswith('.py'): os.remove(%r + f)\n"
            % (dirs, "/flash/libs/" + LIB, "/flash/libs/%s/" % LIB))
    if info["main"] is not None and LIB not in info["main"] and not info["backup"]:
        # keep the old boot setting next to the backup, so --restore can put it back
        prep += ("import os, esp32\nos.rename('/flash/main.py', %r)\n"
                 "try: b = esp32.NVS('uiflow').get_u8('boot_option')\nexcept OSError: b = 1\n"
                 "open(%r, 'w').write(str(b))\n" % (BACKUP, BACKUP_BOOT))
        say("Your old main.py is saved as " + BACKUP)
    # UIFlow2 boot option 0 = run main.py straight away (no UIFlow start menu)
    prep += "import esp32\nn = esp32.NVS('uiflow')\nn.set_u8('boot_option', 0)\nn.commit()\n"
    args = ["exec", prep]
    for local, remote in flash + sd:
        args += ["+", "cp", local, ":" + remote]
    say("Uploading %d files (%d KB) ..." % (len(flash) + len(sd), (size(flash) + size(sd)) // 1024))
    mpremote(port, *args)
    # verify: every file is there with the right size
    want = {r: os.path.getsize(p) for p, r in flash + sd}
    check = ("import os, json\nr = {}\nfor p in %r:\n try: r[p] = os.stat(p)[6]\n except OSError: r[p] = -1\n"
             "print('@@SIZES' + json.dumps(r))\n" % sorted(want))
    out = mpremote(port, "exec", mount + check)
    got = {}
    for line in out.splitlines():
        if line.startswith("@@SIZES"):
            got = json.loads(line[7:])
    bad = [r for r, n in want.items() if got.get(r) != n]
    if bad:
        fail("%d files didn't upload correctly, e.g. %s" % (len(bad), bad[0]),
             "Run the installer again.")
    ok("All %d files uploaded and verified" % len(want))


def restore(port):
    out = mpremote(port, "exec",
                   "import os, esp32\n"
                   "try:\n os.stat(%r)\nexcept OSError:\n print('@@NOBACKUP')\nelse:\n"
                   " os.rename(%r, '/flash/main.py')\n"
                   " try:\n  b = int(open(%r).read())\n  os.remove(%r)\n"
                   " except (OSError, ValueError):\n  b = 1\n"
                   " n = esp32.NVS('uiflow'); n.set_u8('boot_option', b); n.commit()\n"
                   " print('@@RESTORED', b)\n" % (BACKUP, BACKUP, BACKUP_BOOT, BACKUP_BOOT))
    if "@@NOBACKUP" in out:
        fail("No backup found (%s). Nothing to restore." % BACKUP)
    if "@@RESTORED 0" in out:
        ok("Old main.py restored (it starts on power-up, as before)")
    else:
        ok("Old main.py restored and UIFlow start menu turned back on")


def ask_wifi(port):
    """Ask for the WiFi name and password and save them where UIFlow2 keeps them."""
    import getpass
    print()
    say("The Cardputer joins this WiFi on start-up (2.4 GHz networks only).")
    ssid = input("        WiFi name: ").strip()
    if not ssid:
        fail("No WiFi name entered.")
    pswd = getpass.getpass("        WiFi password (hidden, Enter for none): ")
    mpremote(port, "exec", "import esp32\nn = esp32.NVS('uiflow')\n"
                           "n.set_str('ssid0', %r)\nn.set_str('pswd0', %r)\nn.commit()\n" % (ssid, pswd))
    ok("WiFi saved: " + ssid)


def restart(port):
    # the USB link drops as the board resets, so an error here is expected
    subprocess.run([sys.executable, "-m", "mpremote", "connect", port, "resume", "exec",
                    "import machine; machine.reset()"], env=env(), capture_output=True)


def reboot(port):
    restart(port)
    ok("Rebooting the Cardputer")


def main():
    ap = argparse.ArgumentParser(description="Install %s on an M5Stack Cardputer ADV." % PRODUCT)
    ap.add_argument("--port", help="serial port, e.g. COM5 or /dev/ttyACM0 (default: auto)")
    ap.add_argument("--check", action="store_true", help="only check the device, change nothing")
    ap.add_argument("--wifi", action="store_true", help="only change the WiFi name and password")
    ap.add_argument("--no-sd", action="store_true", help="skip the SD card files")
    ap.add_argument("--no-reset", action="store_true", help="don't reboot when done")
    ap.add_argument("--restore", action="store_true", help="put back the main.py from before %s" % PRODUCT)
    a = ap.parse_args()

    print("\n%s installer\n" % PRODUCT)
    ensure_tools()
    port = find_port(a.port)
    if a.restore:
        restore(port)
        reboot(port)
        return
    if a.wifi:
        ask_wifi(port)
        reboot(port)
        return
    lib_mpys, app_mpys = compile_all()
    if HAS_APPS:
        ok("Compiled %d %s modules and %d apps" % (len(lib_mpys), PRODUCT, len(app_mpys)))
    else:
        ok("Compiled %d %s modules" % (len(lib_mpys), PRODUCT))
    flash, sd = plan_files(lib_mpys, app_mpys, not a.no_sd)
    say("Checking the Cardputer ...")
    info = probe(port)
    # +64 KB headroom for settings, caches and the backup
    check_device(info, lib_mpys + app_mpys, size(flash) + 64 * 1024, size(sd), not a.no_sd)
    if a.check:
        restart(port)
        print("\nAll checks passed. Run without --check to install.\n")
        return
    if info["wifi"]:
        ok("WiFi saved on the Cardputer: " + info["wifi"])
    # CardOS has a Settings app for WiFi; NPL Cricket on its own needs it set here
    if not info["wifi"] and not HAS_APPS:
        ask_wifi(port)
    if HAS_APPS and not os.path.exists(SECRETS):
        say("No secrets.json: fine, only the Voice Agent app needs a Gemini key")
    upload(port, flash, sd, info)
    if a.no_reset:
        print("\nDone. Restart the Cardputer to start %s.\n" % PRODUCT)
    else:
        reboot(port)
        if HAS_APPS:
            print("\nDone! CardOS starts in a few seconds.\n"
                  "Open Settings to connect WiFi, then open NPL Cricket.\n")
        else:
            print("\nDone! NPL Cricket starts in a few seconds.\n"
                  "The first start downloads the season, which takes about a minute.\n")


if __name__ == "__main__":
    main()
