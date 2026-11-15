"""Builds the banner / avatar / preview files from the Blender renders. python3 compose.py RENDER_DIR OUT_DIR"""
import sys, os, math
from PIL import Image, ImageDraw, ImageFont, ImageFilter
R, OUT = sys.argv[1], sys.argv[2]
FB = "/usr/share/fonts/opentype/inter/Inter-BlackItalic.otf"
FE = "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"
W, H = 2560, 1440
SAFE = (507, 508, 2053, 931)          # shown on every device
DESK = (0, 508, 2560, 931)            # widest desktop strip

def fit(text, path, maxw, maxh=10**6):
    s = 400
    while s > 10:
        f = ImageFont.truetype(path, s); b = f.getbbox(text)
        if b[2] - b[0] <= maxw and b[3] - b[1] <= maxh: return f
        s -= 2
def label(im, text, path, box, fill=(255, 255, 255), stroke=(24, 26, 30), sw=0.09, align="l", maxh=10**6):
    """draw text fitted into box=(x0,y0,x1) width; returns bottom y"""
    x0, y0, x1 = box
    f = fit(text, path, x1 - x0, maxh); b = f.getbbox(text); tw, th = b[2] - b[0], b[3] - b[1]
    x = x0 if align == "l" else x0 + (x1 - x0 - tw) // 2
    s = max(2, int(f.size * sw))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x - b[0] + s * 0.5, y0 - b[1] + s * 0.9), text, font=f, fill=(0, 0, 0, 150), stroke_width=s, stroke_fill=(0, 0, 0, 150))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(s * 0.5)))
    ImageDraw.Draw(im).text((x - b[0], y0 - b[1]), text, font=f, fill=fill, stroke_width=s, stroke_fill=stroke)
    return y0 + th
def trim(p):
    a = Image.open(p).convert("RGBA"); return a.crop(a.getbbox())
def paste_fit(im, cut, box, shadow=True, anchor="c"):
    x0, y0, x1, y1 = box
    k = min((x1 - x0) / cut.width, (y1 - y0) / cut.height)
    c = cut.resize((int(cut.width * k), int(cut.height * k)), Image.LANCZOS)
    x = x0 + (x1 - x0 - c.width) // 2; y = y1 - c.height if anchor == "b" else y0 + (y1 - y0 - c.height) // 2
    if shadow:
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        e = (x + c.width * 0.08, y + c.height * 0.90, x + c.width * 0.92, y + c.height * 1.04)
        ImageDraw.Draw(sh).ellipse(e, fill=(0, 0, 0, 90)); im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(c.height * 0.035)))
    im.alpha_composite(c, (x, y))
def gradient(size, top, bot, rays=None):
    w, h = size; im = Image.new("RGBA", size)
    px = Image.linear_gradient("L").resize(size)
    im = Image.composite(Image.new("RGBA", size, bot + (255,)), Image.new("RGBA", size, top + (255,)), px)
    if rays:
        ov = Image.new("RGBA", size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov); cx, cy = w / 2, h / 2; rr = math.hypot(w, h)
        n = 28
        for i in range(0, n, 2):
            a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
            d.polygon([(cx, cy), (cx + rr * math.cos(a0), cy + rr * math.sin(a0)), (cx + rr * math.cos(a1), cy + rr * math.sin(a1))], fill=rays)
        im.alpha_composite(ov)
    return im

def scene_banner(src, name, tagline, small, tx0, tx1):
    im = Image.open(os.path.join(R, src)).convert("RGBA")
    y = label(im, "GRINDER", FB, (tx0, SAFE[1] + 58, tx1), fill=(255, 214, 64))
    y = label(im, tagline, FE, (tx0, y + 44, tx1), sw=0.11)
    if small: label(im, small, FE, (tx0, y + 30, tx0 + int((tx1 - tx0) * 0.78)), sw=0.11, fill=(255, 255, 255))
    im.convert("RGB").save(os.path.join(OUT, name), quality=93); return im

def avatar(cut, name, top, bot, rays, boxk=0.80, dy=0.0, crop=None):
    im = gradient((800, 800), top, bot, rays)
    if crop:      # full-bleed close-up: square crop of the raw render
        c = Image.open(os.path.join(R, cut)).convert("RGBA").crop(crop).resize((800, 800), Image.LANCZOS); im.alpha_composite(c)
    else:
        c = trim(os.path.join(R, cut)); m = int(800 * (1 - boxk) / 2)
        paste_fit(im, c, (m, m + int(800 * dy), 800 - m, 800 - m + int(800 * dy)), shadow=False)
    im.convert("RGB").save(os.path.join(OUT, name), quality=95); return im

def sheet(banner, av, name, title):
    """how it looks on a phone and on desktop"""
    S = Image.new("RGB", (1600, 1300), (15, 15, 15)); d = ImageDraw.Draw(S)
    f = ImageFont.truetype(FE, 30); fs = ImageFont.truetype(FE, 22)
    d.text((40, 24), title, font=ImageFont.truetype(FE, 40), fill="white")
    d.text((40, 100), "Desktop", font=fs, fill=(170, 170, 170))
    S.paste(banner.crop(DESK).convert("RGB").resize((1520, int(1520 * 423 / 2560)), Image.LANCZOS), (40, 134))
    y = 134 + int(1520 * 423 / 2560) + 30
    def circ(a, s):
        a = a.convert("RGB").resize((s, s), Image.LANCZOS); m = Image.new("L", (s * 4, s * 4), 0)
        ImageDraw.Draw(m).ellipse((0, 0, s * 4, s * 4), fill=255); return a, m.resize((s, s), Image.LANCZOS)
    a, m = circ(av, 160); S.paste(a, (40, y), m)
    d.text((230, y + 30), "Grinder", font=ImageFont.truetype(FE, 52), fill="white")
    d.text((230, y + 100), "@grinder5 · War Thunder POV Shorts", font=fs, fill=(170, 170, 170))
    y += 210
    d.text((40, y), "Phone", font=fs, fill=(170, 170, 170)); d.text((560, y), "Next to a Short / comment", font=fs, fill=(170, 170, 170))
    y += 34
    mb = banner.crop(SAFE).convert("RGB").resize((440, int(440 * 423 / 1546)), Image.LANCZOS); S.paste(mb, (40, y))
    a, m = circ(av, 72); S.paste(a, (56, y + mb.height + 16), m)
    d.text((144, y + mb.height + 30), "Grinder", font=f, fill="white")
    for i, s in enumerate((96, 48, 32)):
        a, m = circ(av, s); S.paste(a, (560 + i * 130, y + 10), m)
    d.text((40, y + mb.height + 120), "TV (whole image)", font=fs, fill=(170, 170, 170))
    tv = banner.convert("RGB").resize((560, 315), Image.LANCZOS); S.paste(tv, (40, y + mb.height + 154))
    S = S.crop((0, 0, 1600, y + mb.height + 154 + 315 + 40)); S.save(os.path.join(OUT, name), quality=90)

# ---- A: road gang (characters right, text left)
bA = scene_banner("F_bannerA.png", "A - banner (road gang).jpg", "WAR THUNDER POV SHORTS", "the tanks have feelings", SAFE[0] + 36, SAFE[0] + 470)
aA = avatar("F_av_car.png", "A - profile picture (armoured car).jpg", (255, 196, 92), (240, 120, 50), (255, 255, 255, 34), crop=(195, 100, 955, 860))
sheet(bA, aA, "A - preview.jpg", "Option A: Road gang")
# ---- B: the helicopter
bB = scene_banner("F_bannerB.png", "B - banner (helicopter).jpg", "WAR THUNDER POV SHORTS", "new one every day", SAFE[0] + 40, SAFE[0] + 760)
aB = avatar("F_av_heli.png", "B - profile picture (helicopter).jpg", (120, 196, 255), (40, 120, 230), (255, 255, 255, 30), crop=(160, 200, 920, 960))
sheet(bB, aB, "B - preview.jpg", "Option B: The helicopter")
# ---- C: line-up on flat colour
bC = gradient((W, H), (255, 205, 70), (250, 140, 40), (255, 255, 255, 30))
cy0, cy1 = SAFE[1] + 20, SAFE[3] - 24
paste_fit(bC, trim(os.path.join(R, "F_maus.png")), (70, cy0 + 20, 480, cy1), anchor="b")
paste_fit(bC, trim(os.path.join(R, "F_car.png")), (SAFE[0] + 10, cy0 + 40, SAFE[0] + 400, cy1), anchor="b")
paste_fit(bC, trim(os.path.join(R, "F_heli.png")), (SAFE[2] - 470, cy0 - 10, SAFE[2] - 10, cy1 - 20), anchor="c")
paste_fit(bC, trim(os.path.join(R, "F_tank.png")), (2085, cy0 + 110, 2400, cy1), anchor="b")
if os.path.exists(os.path.join(R, "F_f15.png")):
    paste_fit(bC, trim(os.path.join(R, "F_f15.png")), (1500, 130, 2100, 430), shadow=False)
tx0, tx1 = SAFE[0] + 430, SAFE[2] - 500
y = label(bC, "GRINDER", FB, (tx0, SAFE[1] + 70, tx1), fill=(255, 255, 255), align="c")
y = label(bC, "WAR THUNDER POV SHORTS", FE, (tx0 + 10, y + 46, tx1 - 10), sw=0.11, align="c", fill=(255, 236, 150))
label(bC, "everything has eyes. nothing survives.", FE, (tx0 + 40, y + 30, tx1 - 40), sw=0.11, align="c")
bC.convert("RGB").save(os.path.join(OUT, "C - banner (line-up).jpg"), quality=93)
aC = avatar("F_tank.png", "C - profile picture (light tank).jpg", (150, 220, 110), (40, 150, 80), (255, 255, 255, 30), boxk=0.9)
sheet(bC, aC, "C - preview.jpg", "Option C: The line-up")
print("ok")
