# NPL Cricket for Cardputer ADV

**Live Nepal Premier League scores on an M5Stack Cardputer ADV.**

A pocket scoreboard for the Nepal Premier League. Turn on the Cardputer ADV and it shows today's matches, live scores, fixtures, results and the points table, with real team logos. It runs on the Cardputer's standard UIFlow2 firmware and installs with one command.

<!-- Demo: drag your screen recording into this README on GitHub to embed it here -->

> Want a home screen with more apps (settings, image viewer, clock)? This app is also part of **[CardOS](https://github.com/tusharrayamajhi/CardOS)**.

---

## Features

- **Today:** today's matches, with live scores that refresh every 45 seconds during a game.
- **Next:** upcoming fixtures in Nepal time.
- **Results:** every finished match, with the winner highlighted.
- **Teams:** points table with team logos. Press Enter on a team to open its page:
  - captain, coach, record and position
  - last result and next match
  - full squad, with captain (c) and wicket-keeper (wk) marked
  - captain photo
- **Readable from a distance:** large white scores on a dark background, using the full 240×135 screen.
- **Works offline:** the season is saved on the Cardputer, so the app opens instantly and still shows the last data without WiFi.
- **Starts on power-up:** connects to WiFi and sets the clock by itself.

---

## What you need

| | |
|---|---|
| **Device** | [M5Stack Cardputer **ADV**](https://docs.m5stack.com/en/core/Cardputer-Adv). The original Cardputer has a different keyboard and isn't supported yet. |
| **Firmware** | **UIFlow2** for Cardputer (MicroPython 1.27), flashed with M5Burner |
| **SD card** | microSD card, FAT32. Holds team pages and photos (about 100 KB). |
| **WiFi** | 2.4 GHz network for live scores and the clock (5 GHz isn't supported by the Cardputer) |
| **Computer** | Windows, macOS or Linux with [Python 3.8+](https://www.python.org/downloads/), only for installing |
| **Cable** | USB-C **data** cable. Some cables only charge. |

---

## Install

### 1. Flash UIFlow2 (skip this if your Cardputer already runs UIFlow2)

1. Download and open **[M5Burner](https://docs.m5stack.com/en/download)**.
2. Choose **Cardputer** in the device list, then find the **UIFlow2.0** firmware for Cardputer / Cardputer ADV.
3. Download the latest version, connect the Cardputer and click **Burn**.

> If the computer doesn't see the Cardputer, hold the **G0** button while you plug it in. That puts it in download mode.

### 2. Download this app

```bash
git clone https://github.com/tusharrayamajhi/npl-cricket-cardputer.git
```

```bash
cd npl-cricket-cardputer
```

No git? Click **Code → Download ZIP** on GitHub and unzip it instead.

### 3. Insert the SD card and run the installer

Put the microSD card in the Cardputer, connect it with USB, turn it on and run:

```bash
python install.py
```

On macOS and Linux, use `python3` if `python` isn't found.

If the Cardputer has no WiFi saved yet, the installer asks for your WiFi name and password. The password is typed hidden and is only stored on the Cardputer.

```
NPL Cricket installer

[ OK ] PC tools ready (mpremote, mpy-cross)
[ OK ] Cardputer found on COM5
[ OK ] Compiled 9 NPL Cricket modules
  Checking the Cardputer ...
[ OK ] Firmware: v1.27.0 ... (UIFlow2)
[ OK ] Board: Cardputer ADV
[ OK ] MicroPython version matches
[ OK ] Flash space: 1953 KB free, 191 KB needed
[ OK ] SD card: 28 MB free

  The Cardputer joins this WiFi on start-up (2.4 GHz networks only).
        WiFi name: MyWiFi
        WiFi password (hidden, Enter for none):
[ OK ] WiFi saved: MyWiFi
  Uploading 49 files (186 KB) ...
[ OK ] All 49 files uploaded and verified
[ OK ] Rebooting the Cardputer

Done! NPL Cricket starts in a few seconds.
```

The Cardputer restarts, connects to WiFi, sets its clock and opens NPL Cricket. **The first start downloads the whole season, which takes about a minute.** After that it opens instantly.

**What the installer does:**

1. Installs `mpremote` and `mpy-cross` into `tools/mpyx/`. It doesn't touch your system Python.
2. Finds the Cardputer on USB automatically.
3. Compiles the app to `.mpy` bytecode, which loads with far less RAM.
4. Checks the device:
   - it's a Cardputer **ADV**, running **UIFlow2**
   - the MicroPython version matches
   - there's enough flash space
   - an **SD card** is inserted and has room

   If any check fails, it stops with a clear message, and the Cardputer is left exactly as it was.
5. Backs up your existing `main.py`, then uploads the app, logos, team data and photos.
6. Reads every file back to make sure its size matches.
7. Sets the Cardputer to open NPL Cricket on power-up, and reboots it.

**Installer options**

| Command | What it does |
|---|---|
| `python install.py --check` | Only run the checks. Changes nothing. |
| `python install.py --wifi` | Change the WiFi name and password, then reboot |
| `python install.py --port COM5` | Use a specific port (`/dev/ttyACM0` on Linux, `/dev/cu.usbmodem…` on macOS) |
| `python install.py --no-sd` | Install without an SD card. Team pages and photos won't be available. |
| `python install.py --no-reset` | Don't reboot at the end |
| `python install.py --restore` | Uninstall: put back your old `main.py` and how the Cardputer started before |

---

## Keys

The Cardputer ADV has no separate arrow keys. The app uses the keys with arrows printed on them:

| Key | Action |
|---|---|
| `,` `/` | Switch tab: Today, Next, Results, Teams |
| `;` `.` | Move up and down |
| `Enter` | Match details, team page or team photos |
| `r` | Refresh now |
| `R` | Reload the whole season |
| `p` | NPL photos |
| `Esc` (top-left `` ` `` key) | Back |
| Any key | Wake the screen when it's off |

The screen turns off after 5 minutes without a key press, to save battery.

---

## Settings

Edit [`nplkit/config.py`](nplkit/config.py), then run `python install.py` again:

```python
TZ_OFFSET_MIN = 345      # your time zone in minutes from UTC (Nepal = +5:45)
WIFI_COUNTRY = "NP"      # WiFi country code
BRIGHTNESS = 160         # screen brightness 0-255
SLEEP_SEC = 300          # seconds before the screen turns off (0 = never)
KEY_CLICK = True         # key click sound
```

**Add your own photos.** Copy JPG files into `sd/npl/<TEAM>/` (for example `sd/npl/KAG/`) or `sd/npl/photos/` and re-run the installer. The team page shows every JPG in its folder. Use **baseline** (not progressive) JPEGs, about 240×135 pixels.

---

## How it fits in 50 KB of RAM

The ESP32-S3 in the Cardputer ADV has no PSRAM. After WiFi and the screen take their share, the app gets about 50 KB. One day of match data is about 17 KB of JSON, and parsing it the normal way needs several times that.

| Problem | Fix |
|---|---|
| Big JSON replies don't fit in RAM | [`nplkit/jsonstream.py`](nplkit/jsonstream.py) parses the feed as it streams in and keeps only the fields the screen shows. |
| HTTPS needs ~30 KB of contiguous memory | Public scores are fetched over plain HTTP. |
| Decoding PNG logos needs extra memory | Logos are pre-shrunk on the PC to exact sizes (14, 26, 36 px) and stored as uncompressed BMP (Bitmap) files, which draw straight to the screen. |
| Compiling big `.py` files on the device runs out of RAM | Everything is pre-compiled to `.mpy` bytecode on the PC. Speed-critical parts use `@micropython.native`. |
| One big team file is too much to load | Each team has its own small JSON file on the SD card. Only the team you open is loaded. |

---

## Project layout

```
npl-cricket-cardputer/
├── install.py            one-command installer (checks + upload)
├── main.py               boot file: starts the app
├── nplkit/
│   ├── npl.py            the app: tabs, scores, team pages
│   ├── runtime.py        WiFi, clock, keys and screen sleep
│   ├── config.py         settings you can change
│   ├── jsonstream.py     streaming JSON parser
│   ├── net.py            small streaming HTTP client
│   ├── keys.py           Cardputer ADV keyboard driver
│   └── sd.py             SD card mounting
├── res/npl/              logos as BMP (go to the Cardputer's flash)
├── sd/npl/               team data and photos (go to the SD card)
└── tools/
    ├── npl_logos.py      PNG logos → res/npl/*.bmp at every size
    └── npl_teams.py      Wikipedia → sd/npl/<TEAM>/team.json + captain.jpg
```

**Rebuild the team data** (for example, for a new season):

```bash
pip install pillow
```

```bash
python tools/npl_teams.py
```

```bash
python tools/npl_logos.py path/to/folder-with-logo-pngs
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| **"No Cardputer found on USB"** | Use a data cable, not a charge-only one. Restart the Cardputer while it's plugged in. Close Thonny, Arduino IDE or any other serial monitor. |
| **"UIFlow2 firmware not found"** | Flash UIFlow2 with M5Burner (Install step 1). |
| **"Cardputer ADV keyboard not found"** | This is an original Cardputer. The app only supports the ADV for now. |
| **"MicroPython version mismatch"** | Update to the latest UIFlow2 for Cardputer in M5Burner. |
| **"No SD card found"** | Re-insert the card. It must be FAT32 (cards over 32 GB usually come as exFAT, so reformat them). Or use `--no-sd`. |
| **Stuck on "Connecting to…"** | Wrong WiFi name or password, or a 5 GHz network. Run `python install.py --wifi`. Press any key to skip and use saved data. |
| **"No WiFi saved" on start-up** | Run `python install.py --wifi`. |
| **"OFF" in the top-right corner** | The last update failed (no internet). Press `r` to try again. |
| **No matches shown** | Check WiFi, then press `R` to reload the season. Outside the season there are no live games. |
| **I want the original UIFlow back** | `python install.py --restore` |

---

## Credits and disclaimer

This is an **unofficial fan project**. It is not affiliated with the Nepal Premier League, its teams, ESPN or M5Stack.

- **Scores** come from ESPN's public cricket scoreboard feed. It is unofficial and may change without notice.
- **Squads and captains** come from [Wikipedia](https://en.wikipedia.org/wiki/2026_Nepal_Premier_League) (CC BY-SA).
- **Logos** are trademarks of their owners and are used only to identify the league and teams.
- **Captain and venue photos** come from Wikimedia Commons, under their own licences.

See [CREDITS.md](CREDITS.md) for each photo's author and licence.

## Licence

Code: [MIT](LICENSE) © 2026 Tushar Rayamajhi. Logos and photos are not covered by the MIT licence; see [CREDITS.md](CREDITS.md).
