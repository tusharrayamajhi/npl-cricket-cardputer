"""Turn the NPL + team logo PNGs into small BMPs for the Cardputer.

    python tools/npl_logos.py <folder with BIK.png CHR.png ... NPL.png>
    -> res/npl/   (deploy.ps1 uploads it to /flash/res/npl/)

BMP (24-bit) because the Cardputer draws it straight from flash with no
decoding RAM; logos are flattened onto the app background colour.
Team logos: <CODE>_14.bmp (lists), _26.bmp (cards), _36.bmp (details).
App icon: icon_56/36/24/16.bmp - a white tile with the NPL logo, one per
carousel size. npl_bar.bmp - small NPL wordmark for the app's tab bar.
"""
import os
import sys
from PIL import Image, ImageDraw

BG = (0x0F, 0x17, 0x2A)            # CardOS background (config.BG)
TEAMS = ("BIK", "CHR", "JAB", "KAG", "KAY", "LUL", "POA", "SPR")
TEAM_SIZES = (14, 26, 36)
ICON_SIZES = (56, 36, 24, 16)
OUT = os.path.join(os.path.dirname(__file__), "..", "res", "npl")


def trim(im):
    """Crop transparent borders so the logo fills its box."""
    box = im.getchannel("A").getbbox()
    return im.crop(box) if box else im


def fit(im, w, h):
    """Scale to fit inside w x h, keeping the aspect ratio, centred on transparent."""
    im = im.copy()
    im.thumbnail((w, h), Image.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    canvas.alpha_composite(im, ((w - im.width) // 2, (h - im.height) // 2))
    return canvas


def flatten(im, bg=BG):
    out = Image.new("RGB", im.size, bg)
    out.paste(im, mask=im.getchannel("A"))
    return out


def main(src):
    os.makedirs(OUT, exist_ok=True)
    for code in TEAMS:
        logo = trim(Image.open(os.path.join(src, code + ".png")).convert("RGBA"))
        for s in TEAM_SIZES:
            flatten(fit(logo, s, s)).save(os.path.join(OUT, "%s_%d.bmp" % (code, s)))
    npl = trim(Image.open(os.path.join(src, "NPL.png")).convert("RGBA"))
    for s in ICON_SIZES:
        # rounded white tile on the background, NPL logo inside (rendered 4x, then shrunk)
        big = s * 4
        tile = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        ImageDraw.Draw(tile).rounded_rectangle((0, 0, big - 1, big - 1), radius=big * 10 // 56, fill=(255, 255, 255, 255))
        pad = big // 9
        tile.alpha_composite(fit(npl, big - 2 * pad, big - 2 * pad), (pad, pad))
        flatten(tile.resize((s, s), Image.LANCZOS)).save(os.path.join(OUT, "icon_%d.bmp" % s))
    # small NPL wordmark for the app's tab bar (white pill, 32 x 13)
    w, h = 32, 13
    pill = Image.new("RGBA", (w * 4, h * 4), (0, 0, 0, 0))
    ImageDraw.Draw(pill).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), radius=12, fill=(255, 255, 255, 255))
    pill.alpha_composite(fit(npl, w * 4 - 12, h * 4 - 8), (6, 4))
    flatten(pill.resize((w, h), Image.LANCZOS), (0x1E, 0x29, 0x3B)).save(os.path.join(OUT, "npl_bar.bmp"))
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    print("wrote %d files, %d bytes, to %s" % (len(os.listdir(OUT)), total, os.path.abspath(OUT)))


if __name__ == "__main__":
    main(sys.argv[1])
