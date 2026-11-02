NAME = "NPL Cricket"
ICON = "/flash/res/npl/icon"   # NPL logo tiles, made by tools/npl_logos.py
COLOR = 0xDC2626

# Nepal Premier League: today's matches, upcoming fixtures, results and the
# points table. Data: ESPN's public scoreboard feed (no key needed), fetched
# over plain HTTP (public scores; skips the ~30 KB TLS cost) and read as a
# stream so the ~17 KB replies never have to fit in RAM. Saved to flash, so
# the app opens instantly and works offline with the last data.
#   , /  switch tab     ; .  move     Enter  match details / team page / photos
#   r    refresh        R    reload the whole season      p    NPL photos   Esc  back
# Team pages (squads, captains, coaches, photos) come from sd/npl/ on the SD
# card, built by tools/npl_teams.py. Runs full screen (no CardOS bars).
import gc
import json
import os
import time
from nplkit import net, settings, sd
from nplkit.jsonstream import Parser

HOST = "site.api.espn.com"
FEED = "/apis/site/v2/sports/cricket/23081/scoreboard"
CACHE = "/flash/npl_cache.json"
LOGOS = "/flash/res/npl/"      # <CODE>_14.bmp / _26.bmp team logos, npl_bar.bmp
LIVE_REFRESH_MS = 45000

TABS = ("Today", "Next", "Results", "Teams")
TEAMS = {   # short code: (name, badge colour)
    "BIK": ("Biratnagar Kings", 0x7C3AED),
    "CHR": ("Chitwan Rhinos", 0x15803D),
    "JAB": ("Janakpur Bolts", 0xCA8A04),
    "KAG": ("Kathmandu Gorkhas", 0xB91C1C),
    "KAY": ("Karnali Yaks", 0x1D4ED8),
    "LUL": ("Lumbini Lions", 0xEA580C),
    "POA": ("Pokhara Avengers", 0x0E7490),
    "SPR": ("Sudur Paschim Royals", 0xBE185D),
}
DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
TOP = 15            # content starts below the tab row (full screen)
BOTTOM = 135        # screen height
SD_DIR = sd.ROOT + "/npl"
WHITE = 0xFFFFFF
SUB = 0xA3B1C6        # secondary text: light grey, readable from a distance
WIN = 0xFBBF24        # winner's team code / result line
LIVE_RED = 0xEF4444


# ------------------------------------------------------------ ESPN feed
EV = ("events", "#")
CAL = ("leagues", "#", "calendar", "#")
DATE = EV + ("date",)
SUMMARY = EV + ("status", "summary")
STATE = EV + ("status", "type", "state")
COMP = EV + ("competitions", "#")
NUMBER = COMP + ("description",)
VENUE = COMP + ("venue", "fullName")
SIDE = COMP + ("competitors", "#")
ABBR = SIDE + ("team", "abbreviation")
SCORE = SIDE + ("score",)
WINNER = SIDE + ("winner",)


class Collector:
    """Keeps only what the app shows from one scoreboard reply."""

    def __init__(self):
        self.events = []
        self.calendar = []
        self.ev = None
        self.side = None

    def open(self, path):
        if path == EV:
            self.ev = {"utc": "", "no": "", "st": "", "sum": "", "v": "", "t": []}
            self.events.append(self.ev)
        elif path == SIDE and self.ev is not None:
            self.side = ["TBA", "", False]
            self.ev["t"].append(self.side)

    def value(self, path, v):
        if path == CAL:
            self.calendar.append(v[:10].replace("-", ""))
            return
        ev = self.ev
        if ev is None or path[:2] != EV:
            return
        if path == DATE:
            ev["utc"] = v
        elif path == SUMMARY:
            ev["sum"] = v
        elif path == STATE:
            ev["st"] = v
        elif path == NUMBER:
            ev["no"] = v
        elif path == VENUE:
            ev["v"] = v
        elif self.side is not None:
            if path == ABBR:
                self.side[0] = v
            elif path == SCORE:
                self.side[1] = v
            elif path == WINNER:
                self.side[2] = v == "true"


def fetch_day(day=None):
    """One scoreboard: a day "YYYYMMDD", or None for ESPN's current day."""
    path = FEED + ("?dates=" + day if day else "")
    r = net.request("GET", HOST, path, {"User-Agent": "CardOS"}, timeout=20, tls=False)
    try:
        if r.status != 200:
            raise OSError("HTTP %d" % r.status)
        col = Collector()
        parser = Parser(col.value, col.open)
        buf = bytearray(1024)
        while True:
            n = r.readinto(buf)
            if not n:
                break
            parser.feed(memoryview(buf)[:n])
        return col
    finally:
        r.close()


# ------------------------------------------------------------ time helpers
def local(utc):
    """ESPN UTC "2026-10-31T06:45Z" -> local time tuple (Nepal time by default)."""
    try:
        t = time.mktime((int(utc[0:4]), int(utc[5:7]), int(utc[8:10]),
                         int(utc[11:13]), int(utc[14:16]), 0, 0, 0))
    except (ValueError, IndexError):
        return None
    return time.localtime(t + settings.get("tz") * 60)


def day_key(t):
    return "%04d%02d%02d" % (t[0], t[1], t[2])


def day_text(t):
    return "%s %d %s" % (DAYS[t[6]], t[2], MONTHS[t[1] - 1])


def clock_text(t):
    return "%02d:%02d" % (t[3], t[4])


def split_score(score):
    """"149 (19.3/20 ov, target 158)" -> ("149", "19.3/20 ov, target 158")."""
    i = score.find(" (")
    return (score, "") if i < 0 else (score[:i], score[i + 2:].rstrip(")"))


def card_score(score):
    """Short form for cards: "149 (19.3/20 ov, target 158)" -> "149 (19.3)"."""
    main, extra = split_score(score)
    if not extra:
        return main
    overs = extra.split(",")[0].replace(" ov", "").split("/")[0]
    return "%s (%s)" % (main, overs)


def jpeg_size(path):
    """(width, height) from a JPEG header, or (0, 0)."""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return 0, 0
            while True:
                b = f.read(1)
                if not b:
                    return 0, 0
                if b != b"\xff":
                    continue
                m = f.read(1)
                while m == b"\xff":
                    m = f.read(1)
                if not m:
                    return 0, 0
                if m[0] in (0xC0, 0xC1, 0xC2):
                    f.read(3)
                    h = int.from_bytes(f.read(2), "big")
                    return int.from_bytes(f.read(2), "big"), h
                if m[0] in (0xD8, 0xD9) or 0xD0 <= m[0] <= 0xD7:
                    continue
                f.seek(int.from_bytes(f.read(2), "big") - 2, 1)
    except OSError:
        return 0, 0


def short_no(no):
    return no.replace(" Match", "").replace("Qualifier", "Q").replace("Eliminator", "Elim")


# ------------------------------------------------------------ app
class NplApp:
    def __init__(self, ctx):
        self.ctx = ctx
        self.lcd = ctx.lcd
        self.C = ctx.config
        self.tab = 0
        self.sel = 0
        self.offset = 0
        self.detail = None            # match shown full-screen, or None
        self.team = None              # team page open (team code), or None
        self.team_info = {}
        self.team_lines = []
        self.team_photos = []
        self.scroll = 0
        self.note = ""                # shown in the tab bar while updating
        self.offline = False
        self.last_live = time.ticks_ms()
        self.cache = {"cal": [], "days": {}}
        try:
            with open(CACHE) as f:
                self.cache = json.load(f)
        except (OSError, ValueError):
            pass

    # ---- data
    def save(self):
        try:
            with open(CACHE, "w") as f:
                json.dump(self.cache, f)
        except OSError as e:
            print("npl cache:", e)

    def matches(self):
        out = []
        for d in self.cache["cal"]:
            out.extend(self.cache["days"].get(d, []))
        return out

    def today(self):
        t = time.localtime()
        return day_key(t) if t[0] >= 2024 else None

    def days_to_update(self, everything=False):
        today = self.today()
        days = []
        for d in self.cache["cal"]:
            if everything:
                days.append(d)
                continue
            if today is not None and d > today:
                continue                   # future fixtures rarely change
            ms = self.cache["days"].get(d)
            if ms is None or any(m["st"] != "post" for m in ms):
                days.append(d)
        return days

    def update(self, everything=False):
        """Fetch new data. Returns True if anything was downloaded."""
        try:
            if everything or not self.cache["cal"]:
                self.status("Loading NPL schedule...")
                col = fetch_day()
                if col.calendar:
                    self.cache["cal"] = col.calendar
                everything = True
            days = self.days_to_update(everything)
            for i, d in enumerate(days):
                self.status("Updating %d/%d ..." % (i + 1, len(days)))
                self.cache["days"][d] = fetch_day(d).events
            self.save()
            self.offline = False
            print("npl: updated %d day(s)" % len(days))
            return True
        except (OSError, MemoryError) as e:
            print("npl update:", repr(e))
            self.offline = True
            return False
        finally:
            self.note = ""

    def refresh_detail(self):
        if self.detail is not None:
            for m in self.matches():
                if m["utc"] == self.detail["utc"] and m["no"] == self.detail["no"]:
                    self.detail = m

    def live_now(self):
        return any(m["st"] == "in" for m in self.matches())

    # ---- lists for each tab
    def today_matches(self):
        today = self.today()
        ms = self.matches()
        if today:
            todays = [m for m in ms if local(m["utc"]) and day_key(local(m["utc"])) == today]
            if todays:
                return "Today", todays
        upcoming = [m for m in ms if m["st"] != "post"]
        if upcoming:
            first = local(upcoming[0]["utc"])
            key = day_key(first) if first else None
            return "Next: " + (day_text(first) if first else "?"), [
                m for m in upcoming if local(m["utc"]) and day_key(local(m["utc"])) == key]
        return "Latest", ms[-2:]

    def upcoming(self):
        return [m for m in self.matches() if m["st"] == "pre"]

    def results(self):
        return [m for m in reversed(self.matches()) if m["st"] == "post"]

    def table(self):
        rows = {k: [k, 0, 0, 0, 0, 0] for k in TEAMS}     # team, P, W, L, NR, Pts
        for m in self.matches():
            if m["st"] != "post" or len(m["t"]) != 2:
                continue
            a, b = m["t"]
            if a[0] not in rows or b[0] not in rows:
                continue
            for side, other in ((a, b), (b, a)):
                r = rows[side[0]]
                r[1] += 1
                if side[2]:
                    r[2] += 1
                    r[5] += 2
                elif other[2]:
                    r[3] += 1
                else:
                    r[4] += 1
                    r[5] += 1
        return sorted(rows.values(), key=lambda r: (-r[5], -r[2], r[0]))

    # ---- drawing helpers
    def badge(self, code, x, y, w=30, h=15, font=None):
        lcd = self.lcd
        color = TEAMS.get(code, ("", 0x475569))[1]
        lcd.fillRoundRect(x, y, w, h, 3, color)
        lcd.setFont(font or lcd.FONTS.DejaVu9)
        lcd.setTextColor(WHITE, color)
        lcd.drawCenterString(code, x + w // 2, y + (h - 10) // 2)

    def logo(self, code, size, x, y):
        """Team logo from flash; falls back to a colour badge (e.g. for TBA)."""
        if code in TEAMS:
            try:
                self.lcd.drawBmp("%s%s_%d.bmp" % (LOGOS, code, size), x, y)
                return
            except Exception:
                pass
        self.badge(code, x, y + (size - 13) // 2 if size > 13 else y, size if size > 20 else 24, 13)

    def npl_logo(self, x, y):
        lcd = self.lcd
        try:
            lcd.drawBmp(LOGOS + "npl_bar.bmp", x, y)
            return
        except Exception:
            pass
        lcd.fillRoundRect(x, y, 30, 13, 3, 0xDC2626)
        lcd.fillRect(x + 2, y + 10, 26, 2, 0x1D4ED8)
        lcd.setFont(lcd.FONTS.DejaVu9)
        lcd.setTextColor(WHITE, 0xDC2626)
        lcd.drawCenterString("NPL", x + 15, y + 1)

    def status(self, text):
        self.note = text
        self.draw_tabs()

    def draw_tabs(self):
        lcd, C, ctx = self.lcd, self.C, self.ctx
        y = 0
        lcd.fillRect(0, y, ctx.W, TOP - y, 0x1E293B)
        self.npl_logo(2, y + 1)
        lcd.setFont(lcd.FONTS.DejaVu9)
        if self.note:                      # e.g. "Updating 2/3 ..." replaces the tabs
            lcd.setTextColor(C.ACCENT, 0x1E293B)
            lcd.drawString(self.note, 38, y + 3)
            return
        x = 36
        for i, name in enumerate(TABS):
            w = lcd.textWidth(name) + 8
            if i == self.tab and self.detail is None:
                lcd.fillRoundRect(x, y + 1, w, 13, 3, C.ACCENT)
                lcd.setTextColor(0x0F172A, C.ACCENT)
            else:
                lcd.setTextColor(SUB, 0x1E293B)
            lcd.drawString(name, x + 4, y + 3)
            x += w + 2
        if self.offline:
            lcd.setTextColor(C.YELLOW, 0x1E293B)
            lcd.drawRightString("OFF", ctx.W - 3, y + 3)
        elif self.live_now():
            lcd.fillCircle(ctx.W - 6, y + 7, 3, LIVE_RED)

    def state_tag(self, m):
        if m["st"] == "in":
            return "LIVE", LIVE_RED
        if m["st"] == "post":
            return "FINAL", SUB
        t = local(m["utc"])
        return (clock_text(t) if t else "--:--"), self.C.ACCENT

    def card(self, m, y, selected):
        """One match: logos and scores left/right, status in the middle (43 px)."""
        lcd, C, ctx = self.lcd, self.C, self.ctx
        bg = C.BG                          # logos are flattened on this colour
        lcd.fillRect(0, y, ctx.W, 43, bg)
        lcd.drawRoundRect(1, y, ctx.W - 2, 43, 4, C.ACCENT if selected else 0x1E293B)
        sides = m["t"] if len(m["t"]) == 2 else [["TBA", "", False], ["TBA", "", False]]
        done = m["st"] == "post"
        for i, (code, score, won) in enumerate(sides):
            right = i == 1
            lx = ctx.W - 31 if right else 5
            self.logo(code, 26, lx, y + 3)
            tx = ctx.W - 35 if right else 35
            lcd.setFont(lcd.FONTS.DejaVu9)
            lcd.setTextColor(WIN if won else WHITE, bg)
            label = (code + " WON" if not right else "WON " + code) if won else code
            (lcd.drawRightString if right else lcd.drawString)(label, tx, y + 3)
            text = card_score(score) if score else "-"
            lcd.setFont(lcd.FONTS.DejaVu12)
            if lcd.textWidth(text) > 62:
                lcd.setFont(lcd.FONTS.DejaVu9)
            lcd.setTextColor(WHITE, bg)
            (lcd.drawRightString if right else lcd.drawString)(text, tx, y + 15)
        tag, tag_color = self.state_tag(m)
        lcd.setFont(lcd.FONTS.DejaVu9)
        lcd.setTextColor(tag_color, bg)
        lcd.drawCenterString(tag, ctx.W // 2, y + 4)
        lcd.setTextColor(SUB, bg)
        lcd.drawCenterString(short_no(m["no"]), ctx.W // 2, y + 16)
        line = m["sum"] or (day_text(local(m["utc"])) if local(m["utc"]) else "")
        lcd.setTextColor(0xFBBF24 if done else C.FG, bg)
        lcd.drawCenterString(line[:44], ctx.W // 2, y + 31)

    def draw(self):
        ctx = self.ctx
        self.lcd.fillRect(0, TOP, ctx.W, BOTTOM - TOP, self.C.BG)
        self.draw_tabs()
        if self.team is not None:
            self.draw_team()
        elif self.detail is not None:
            self.draw_detail(self.detail)
        elif self.tab == 0:
            self.draw_today()
        elif self.tab == 1:
            self.draw_list(self.upcoming(), self.fixture_row, 15, "No upcoming matches")
        elif self.tab == 2:
            self.draw_list(self.results(), self.result_row, 28, "No results yet")
        else:
            self.draw_table()

    def current_list(self):
        if self.tab == 0:
            return self.today_matches()[1][:2]
        if self.tab == 1:
            return self.upcoming()
        if self.tab == 2:
            return self.results()
        return []

    def draw_today(self):
        lcd, C, ctx = self.lcd, self.C, self.ctx
        title, ms = self.today_matches()
        if not ms:
            self.empty("No matches - press r to refresh")
            return
        ms = ms[:2]
        self.sel = min(self.sel, len(ms) - 1)
        for i, m in enumerate(ms):
            self.card(m, TOP + 8 + i * 56, i == self.sel)

    def empty(self, text):
        lcd, C, ctx = self.lcd, self.C, self.ctx
        lcd.setFont(lcd.FONTS.DejaVu12)
        lcd.setTextColor(SUB, C.BG)
        lcd.drawCenterString(text, ctx.W // 2, TOP + 30)

    def draw_list(self, items, row_fn, row_h, empty_text):
        ctx = self.ctx
        if not items:
            self.empty(empty_text)
            return
        rows = (BOTTOM - TOP) // row_h
        self.sel = max(0, min(self.sel, len(items) - 1))
        if self.sel < self.offset:
            self.offset = self.sel
        elif self.sel >= self.offset + rows:
            self.offset = self.sel - rows + 1
        for r in range(rows):
            i = self.offset + r
            if i >= len(items):
                break
            row_fn(items[i], TOP + 1 + r * row_h, i == self.sel)

    def fixture_row(self, m, y, selected):
        lcd, C, ctx = self.lcd, self.C, self.ctx
        bg = C.BG
        lcd.fillRect(0, y, ctx.W, 15, bg)
        if selected:
            lcd.fillRect(0, y + 1, 3, 13, C.ACCENT)
        t = local(m["utc"])
        lcd.setFont(lcd.FONTS.DejaVu9)
        lcd.setTextColor(WHITE if selected else C.FG, bg)
        lcd.drawString(("%s %s" % (day_text(t), clock_text(t))) if t else "?", 6, y + 3)
        sides = m["t"] if len(m["t"]) == 2 else [["TBA"], ["TBA"]]
        for i, x in ((0, 108), (1, 160)):
            code = sides[i][0]
            self.logo(code, 14, x, y)
            lcd.setFont(lcd.FONTS.DejaVu9)
            lcd.setTextColor(WHITE if selected else C.FG, bg)
            lcd.drawString(code, x + 16, y + 3)
        lcd.setTextColor(SUB, bg)
        lcd.drawString("v", 148, y + 3)
        lcd.drawRightString(short_no(m["no"]), ctx.W - 4, y + 3)

    def result_row(self, m, y, selected):
        lcd, C, ctx = self.lcd, self.C, self.ctx
        bg = C.BG
        lcd.fillRect(0, y, ctx.W, 27, bg)
        if selected:
            lcd.fillRect(0, y + 1, 3, 25, C.ACCENT)
        sides = m["t"] if len(m["t"]) == 2 else [["TBA", "", False], ["TBA", "", False]]
        for i, (code, score, won) in enumerate(sides):
            x = 6 + i * 118
            self.logo(code, 14, x, y)
            lcd.setFont(lcd.FONTS.DejaVu9)
            lcd.setTextColor(WIN if won else WHITE, bg)
            lcd.drawString(code, x + 16, y + 3)
            lcd.setTextColor(WHITE, bg)
            lcd.drawString(card_score(score) if score else "-", x + 16 + lcd.textWidth(code + " "), y + 3)
        t = local(m["utc"])
        lcd.setTextColor(0xFBBF24, bg)
        line = ("%d %s  " % (t[2], MONTHS[t[1] - 1]) if t else "") + (m["sum"] or "No result")
        lcd.drawString(line[:44], 6, y + 16)

    def draw_table(self):
        """Points table; pick a team and press Enter for its page."""
        lcd, C, ctx = self.lcd, self.C, self.ctx
        rows = self.table()
        self.sel = max(0, min(self.sel, len(rows) - 1))
        lcd.setFont(lcd.FONTS.DejaVu9)
        lcd.setTextColor(SUB, C.BG)
        lcd.drawString("Enter: team page", 4, TOP + 2)
        cols = ((158, "P"), (177, "W"), (196, "L"), (215, "NR"), (233, "Pts"))
        for x, h in cols:
            lcd.drawCenterString(h, x, TOP + 2)
        for i, (code, p, w, l, nr, pts) in enumerate(rows):
            y = TOP + 14 + i * 13
            selected = i == self.sel
            if selected:
                lcd.fillRect(0, y, 3, 13, C.ACCENT)
            lcd.setTextColor(WHITE if selected else C.FG, C.BG)
            lcd.drawString("%d" % (i + 1), 5, y + 2)
            self.logo(code, 14, 13, y - 1)
            lcd.drawString(TEAMS[code][0], 30, y + 2)
            for (x, _), v in zip(cols, (p, w, l, nr, pts)):
                lcd.setTextColor(WHITE if (x == 233 or selected) else C.FG, C.BG)
                lcd.drawCenterString(str(v), x, y + 2)

    # ---- team pages
    def load_team(self, code):
        """sd/npl/<CODE>/team.json: captain, coach, last season, squad."""
        try:
            if sd.mount():
                with open("%s/%s/team.json" % (SD_DIR, code)) as f:
                    return json.load(f)
        except (OSError, ValueError) as e:
            print("npl team:", e)
        return {}

    def photos(self, folder):
        try:
            files = sorted(f for f in os.listdir(folder) if f.lower().endswith(".jpg"))
        except OSError:
            return []
        if "captain.jpg" in files:              # captain first
            files.remove("captain.jpg")
            files.insert(0, "captain.jpg")
        return [folder + "/" + f for f in files]

    def open_team(self, code):
        self.team_info = self.team_lines = None
        gc.collect()
        info = self.load_team(code)
        lines = []
        for i, r in enumerate(self.table()):
            if r[0] == code:
                lines.append(("#%d  P %d  W %d  L %d  NR %d  -  %d pts" % (i + 1, r[1], r[2], r[3], r[4], r[5]), WHITE))
        last = next((m for m in self.results() if any(t[0] == code for t in m["t"])), None)
        if last:
            lines.append(("Last: " + (last["sum"] or "no result"), WIN))
        nxt = next((m for m in self.upcoming() if any(t[0] == code for t in m["t"])), None)
        if nxt:
            t = local(nxt["utc"])
            other = [x[0] for x in nxt["t"] if x[0] != code]
            when = "%s %s" % (day_text(t), clock_text(t)) if t else "?"
            lines.append(("Next: %s v %s" % (when, other[0] if other else "?"), self.C.ACCENT))
        if info:
            if info.get("last"):
                lines.append(("2025 season: " + info["last"], SUB))
            lines.append(("Squad (%d):" % len(info.get("squad", [])), SUB))
            for player, flags in info.get("squad", []):
                mark = "  (%s)" % flags.replace(",", ", ") if flags else ""
                lines.append((player + mark, WIN if "c" in flags.split(",") else self.C.FG))
        else:
            lines.append(("No squad data: copy sd/npl to the SD card", SUB))
        self.team = code
        self.team_info = info
        self.team_lines = lines
        self.team_photos = self.photos(SD_DIR + "/" + code)
        self.scroll = 0

    def draw_team(self):
        lcd, C, ctx = self.lcd, self.C, self.ctx
        code, info = self.team, self.team_info
        self.logo(code, 36, 4, TOP + 4)
        lcd.setFont(lcd.FONTS.DejaVu12)
        lcd.setTextColor(WHITE, C.BG)
        lcd.drawString(TEAMS[code][0], 46, TOP + 3)
        lcd.setFont(lcd.FONTS.DejaVu9)
        lcd.setTextColor(WIN, C.BG)
        lcd.drawString("Captain: " + info.get("captain", "?"), 46, TOP + 19)
        lcd.setTextColor(SUB, C.BG)
        lcd.drawString("Coach: " + info.get("coach", "?"), 46, TOP + 30)
        if self.team_photos:
            n = len(self.team_photos)
            lcd.setTextColor(C.ACCENT, C.BG)
            lcd.drawRightString("Enter: %d photo%s" % (n, "s" if n > 1 else ""), ctx.W - 3, TOP + 30)
        rows = (BOTTOM - TOP - 46) // 11
        self.scroll = max(0, min(self.scroll, len(self.team_lines) - rows))
        y = TOP + 46
        for text, color in self.team_lines[self.scroll:self.scroll + rows]:
            lcd.setTextColor(color, C.BG)
            lcd.drawString(text[:44], 4, y)
            y += 11
        if self.scroll + rows < len(self.team_lines):
            lcd.fillTriangle(ctx.W - 8, BOTTOM - 7, ctx.W - 2, BOTTOM - 7, ctx.W - 5, BOTTOM - 3, SUB)

    # ---- photo viewer (full screen JPGs from the SD card)
    def caption(self, path):
        name = path.rsplit("/", 1)[-1][:-4]
        if name == "captain" and self.team:
            return "Captain: " + self.team_info.get("captain", "")
        if name == "venue":
            return "TU Cricket Ground, Kirtipur"
        return name.replace("_", " ").replace("-", " ")

    def view_photos(self, paths):
        ctx, lcd = self.ctx, self.lcd
        i = 0
        while True:
            lcd.fillScreen(0x000000)
            path = paths[i]
            w, h = jpeg_size(path)
            s = min(240 / w, 135 / h, 1.0) if w and h else 1.0
            x = (240 - int(w * s)) // 2 if w else 0
            y = (135 - int(h * s)) // 2 if h else 0
            try:
                lcd.drawJpg(path, x, y, 0, 0, 0, 0, s, s)
            except Exception as e:
                print("npl photo:", e)
            text = "%s   %d/%d" % (self.caption(path), i + 1, len(paths))
            lcd.setFont(lcd.FONTS.DejaVu9)
            tw = lcd.textWidth(text) + 10
            lcd.fillRoundRect((240 - tw) // 2, 121, tw, 13, 6, 0x000000)
            lcd.setTextColor(WHITE, 0x000000)
            lcd.drawCenterString(text, 120, 123)
            while True:
                keys = ctx.tick()
                if any(k in (ctx.ESC, ctx.ENTER, ctx.BACKSPACE) for k in keys):
                    return
                if any(k in (ctx.RIGHT, "/", ctx.DOWN, ".") for k in keys):
                    i = (i + 1) % len(paths)
                    break
                if any(k in (ctx.LEFT, ",", ctx.UP, ";") for k in keys):
                    i = (i - 1) % len(paths)
                    break
                time.sleep_ms(20)

    def draw_detail(self, m):
        lcd, C, ctx = self.lcd, self.C, self.ctx
        t = local(m["utc"])
        lcd.setFont(lcd.FONTS.DejaVu9)
        lcd.setTextColor(C.ACCENT, C.BG)
        head = m["no"] + ("  -  %s %s" % (day_text(t), clock_text(t)) if t else "")
        lcd.drawString(head[:44], 4, TOP + 1)
        lcd.setTextColor(SUB, C.BG)
        lcd.drawString(m["v"][:44], 4, TOP + 12)
        sides = m["t"] if len(m["t"]) == 2 else [["TBA", "", False], ["TBA", "", False]]
        for i, (code, score, won) in enumerate(sides):
            y = TOP + 24 + i * 28
            self.logo(code, 26, 4, y)
            lcd.setFont(lcd.FONTS.DejaVu9)
            lcd.setTextColor(C.FG, C.BG)
            lcd.drawString(TEAMS.get(code, (code,))[0][:24], 36, y)
            main, extra = split_score(score)
            lcd.setFont(lcd.FONTS.DejaVu12)
            lcd.setTextColor(WHITE, C.BG)
            lcd.drawString(main or ("yet to bat" if m["st"] == "in" else "-"), 36, y + 11)
            if extra:
                x = 40 + lcd.textWidth(main)
                lcd.setFont(lcd.FONTS.DejaVu9)
                lcd.setTextColor(SUB, C.BG)
                lcd.drawString(extra[:24], x, y + 13)
            if won:
                lcd.setTextColor(0xFBBF24, C.BG)
                lcd.drawRightString("WON", ctx.W - 6, y + 4)
        tag, color = self.state_tag(m)
        lcd.setFont(lcd.FONTS.DejaVu9)
        lcd.setTextColor(0xFBBF24 if m["st"] == "post" else color, C.BG)
        lcd.drawString((m["sum"] or tag)[:44], 4, TOP + 79)

    # ---- main loop
    def general_photos(self):
        """NPL photos not tied to a team: sd/npl/photos/*.jpg plus the venue."""
        if not sd.mount():
            return []
        paths = self.photos(SD_DIR + "/photos")
        try:
            os.stat(SD_DIR + "/venue.jpg")
            paths.append(SD_DIR + "/venue.jpg")
        except OSError:
            pass
        return paths

    def run(self):
        ctx = self.ctx
        ctx.fullscreen(True)               # the app uses the whole screen
        self.lcd.fillScreen(self.C.BG)
        self.draw()
        if self.update():
            self.draw()
        while True:
            redraw = False
            for k in ctx.tick():
                if self.team is not None:              # ---- team page
                    if k in (ctx.ESC, ctx.BACKSPACE):
                        self.team = None
                    elif k in (ctx.UP, ";"):
                        self.scroll = max(0, self.scroll - 3)
                    elif k in (ctx.DOWN, "."):
                        self.scroll += 3
                    elif k == ctx.ENTER and self.team_photos:
                        self.view_photos(self.team_photos)
                    else:
                        continue
                    redraw = True
                    continue
                if k == ctx.ESC:
                    if self.detail is not None:
                        self.detail = None
                        redraw = True
                        continue
                    return
                if k in ("r", "R"):
                    self.update(everything=(k == "R"))
                    self.refresh_detail()
                    redraw = True
                elif k in ("p", "P"):
                    paths = self.general_photos()
                    if paths:
                        self.view_photos(paths)
                        redraw = True
                elif self.detail is not None:
                    if k in (ctx.ENTER, ctx.BACKSPACE):
                        self.detail = None
                        redraw = True
                elif k in (ctx.LEFT, ","):
                    self.tab = (self.tab - 1) % len(TABS)
                    self.sel = self.offset = 0
                    redraw = True
                elif k in (ctx.RIGHT, "/", "KEY_TAB"):
                    self.tab = (self.tab + 1) % len(TABS)
                    self.sel = self.offset = 0
                    redraw = True
                elif k in (ctx.UP, ";"):
                    self.sel = max(0, self.sel - 1)
                    redraw = True
                elif k in (ctx.DOWN, "."):
                    self.sel += 1
                    redraw = True
                elif k == ctx.ENTER:
                    if self.tab == 3:
                        rows = self.table()
                        self.open_team(rows[min(self.sel, len(rows) - 1)][0])
                    else:
                        items = self.current_list()
                        if items:
                            self.detail = items[min(self.sel, len(items) - 1)]
                    redraw = True
            # keep live matches fresh while the app is open
            if self.live_now() and time.ticks_diff(time.ticks_ms(), self.last_live) > LIVE_REFRESH_MS:
                self.last_live = time.ticks_ms()
                self.update()
                self.refresh_detail()
                redraw = True
            if redraw:
                self.draw()
            time.sleep_ms(20)



def run(ctx):
    try:
        NplApp(ctx).run()
    finally:
        sd.unmount()        # give the SD driver's RAM back to CardOS
