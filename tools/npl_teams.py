"""Build the NPL app's team pages: squads, captains, coaches and photos.

    python tools/npl_teams.py
    -> sd/npl/<CODE>/team.json + captain.jpg, sd/npl/venue.jpg (+ teams.json, all in one)
       (deploy.ps1 copies the sd/ folder onto the Cardputer's SD card)

Source: the English Wikipedia article "2026 Nepal Premier League" (Teams and
Squads sections) and the captains' Wikipedia photos. Photos are letterboxed
to 240x135 baseline JPEGs, which the Cardputer can draw full screen.
Add your own photos (trophy, team group...) as JPGs in sd/npl/<CODE>/ or
sd/npl/photos/ - the app shows every JPG it finds there.
"""
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from PIL import Image

UA = {"User-Agent": "CardOS-npl/1.0 (personal device)"}
PAGE = "2026 Nepal Premier League"
OUT = os.path.join(os.path.dirname(__file__), "..", "sd", "npl")
CODES = {
    "Biratnagar Kings": "BIK", "Chitwan Rhinos": "CHR", "Janakpur Bolts": "JAB",
    "Kathmandu Gorkhas": "KAG", "Kathmandu Gurkhas": "KAG", "Karnali Yaks": "KAY",
    "Lumbini Lions": "LUL", "Pokhara Avengers": "POA", "Sudurpaschim Royals": "SPR",
}


def fetch(url):
    """GET with a polite pause, retrying when Wikipedia says "too many requests"."""
    for attempt in range(5):
        time.sleep(1.5)
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(10 * (attempt + 1))


def wiki(**kw):
    kw["format"] = "json"
    return json.loads(fetch("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(kw)))


def section_text(title):
    secs = wiki(action="parse", page=PAGE, prop="sections")["parse"]["sections"]
    idx = next(s["index"] for s in secs if s["line"] == title)
    return wiki(action="parse", page=PAGE, prop="wikitext", section=idx)["parse"]["wikitext"]["*"]


def plain(text):
    """Wikitext -> plain text: [[A|B]] -> B, [[A]] -> A, drop templates/refs."""
    text = re.sub(r"\{\{efn[^}]*\}\}", "", text)
    text = re.sub(r"<ref[^>]*/>|<ref.*?</ref>", "", text)
    text = re.sub(r"\[\[([^|\]]*)\|([^\]]*)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"\{\{[^}]*\}\}", "", text)
    return text.strip()


def link_target(cell):
    m = re.search(r"\[\[([^|\]]+)", cell)
    return m.group(1) if m else None


def parse_teams():
    """Teams table: team, last season, captain, coach (+ captain's article title)."""
    teams = {}
    rows = section_text("Teams").split("|-")[1:]
    for row in rows:
        cells = [c.strip() for c in row.strip().strip("|}").split("\n|") if c.strip()]
        cells = [c.lstrip("|").strip() for c in cells]
        if len(cells) < 4:
            continue
        name = plain(cells[0])
        code = CODES.get(name)
        if not code:
            continue
        teams[code] = {"name": name, "last": plain(cells[1]), "captain": plain(cells[2]),
                       "coach": plain(cells[3]), "captain_page": link_target(cells[2]), "squad": []}
    return teams


def parse_squads(teams):
    text = section_text("Squads")
    for table in text.split("{|")[1:]:
        heads = [CODES.get(plain(h)) for h in re.findall(r"^!\s*(.+)$", table, re.M)]
        cells = table.split('valign="top" |')[1:]
        for code, cell in zip(heads, cells):
            if code not in teams:
                continue
            seen = set()
            for line in re.findall(r"^\*\s*(.+)$", cell, re.M):
                flags = []
                if re.search(r"\|c\]\]\)", line):
                    flags.append("c")
                if re.search(r"\|wk\]\]\)", line):
                    flags.append("wk")
                name = plain(re.sub(r"\(\[\[[^\]]*\]\]\)", "", line))
                if name and name not in seen:
                    seen.add(name)
                    teams[code]["squad"].append([name, ",".join(flags)])


def letterbox(img, w=240, h=135):
    img = img.convert("RGB")
    img.thumbnail((w, h), Image.LANCZOS)
    out = Image.new("RGB", (w, h), (0, 0, 0))
    out.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return out


def save_photo(page_title, path):
    """The Wikipedia lead image of `page_title`, as a 240x135 baseline JPEG."""
    if not page_title:
        return False
    js = wiki(action="query", prop="pageimages", piprop="thumbnail", pithumbsize=480,
              titles=page_title, redirects=1)
    page = next(iter(js["query"]["pages"].values()))
    src = page.get("thumbnail", {}).get("source")
    if not src:
        return False
    raw = fetch(src)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    letterbox(Image.open(io.BytesIO(raw))).save(path, "JPEG", quality=85, progressive=False)
    return True


def main():
    teams = parse_teams()
    parse_squads(teams)
    os.makedirs(OUT, exist_ok=True)
    for code, t in sorted(teams.items()):
        t["photo"] = save_photo(t.pop("captain_page"), os.path.join(OUT, code, "captain.jpg"))
        print("%s %-20s captain %-22s coach %-22s squad %2d  photo %s" % (
            code, t["name"], t["captain"], t["coach"], len(t["squad"]), t["photo"]))
    venue = save_photo("Tribhuvan University International Cricket Ground", os.path.join(OUT, "venue.jpg"))
    # one small file per team, so the Cardputer only loads the team it shows
    for code, t in teams.items():
        os.makedirs(os.path.join(OUT, code), exist_ok=True)
        with open(os.path.join(OUT, code, "team.json"), "w", encoding="utf-8") as f:
            json.dump(t, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(OUT, "teams.json"), "w", encoding="utf-8") as f:
        json.dump({"source": "Wikipedia: " + PAGE, "venue_photo": venue, "teams": teams}, f,
                  ensure_ascii=False, separators=(",", ":"))
    print("venue photo:", venue, "| wrote", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
