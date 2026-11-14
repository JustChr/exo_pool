"""Render the Zodiac Exo brand images (original design: water droplet with waves).

Writes icon.png / icon@2x.png / logo.png / logo@2x.png / dark_logo*.png into
custom_components/zodiac_exo/brand/ and a light/dark preview sheet.

Usage:
    pip install pillow
    python scripts/make_brand.py [output_brand_dir] [preview_png]

The wordmark font is Segoe UI Bold (what the committed logos use). Set
EXO_BRAND_FONT=/path/to/font.ttf to use another font; on Linux/macOS a
DejaVu Sans Bold / Helvetica fallback is tried automatically.
"""
import math
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

_REPO = Path(__file__).resolve().parent.parent
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else _REPO / "custom_components" / "zodiac_exo" / "brand"
PREVIEW = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("brand_preview.png")

_FONT_CANDIDATES = [
    os.environ.get("EXO_BRAND_FONT", ""),
    "C:/Windows/Fonts/segoeuib.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_CANDIDATES:
        if path and Path(path).exists():
            return ImageFont.truetype(path, size)
    raise SystemExit("No bold font found; set EXO_BRAND_FONT=/path/to/font.ttf")
OUT.mkdir(parents=True, exist_ok=True)

SS = 2048  # supersampled canvas for the icon

TOP = (34, 211, 238)      # cyan-400
BOTTOM = (3, 105, 161)    # sky-700
TEXT_LIGHT_BG = (12, 74, 110)    # sky-900
TEXT_DARK_BG = (224, 242, 254)   # sky-100


def droplet_mask(size: int) -> Image.Image:
    """Teardrop: circle at the bottom joined tangentially to a pointed top."""
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    r = size * 0.36
    cx, cy = size / 2, size - r - size * 0.015
    tip = (cx, size * 0.015)
    # Tangent points: CP is perpendicular to TP, so the angle between the
    # upward direction and CP is acos(r / |CT|).
    theta = math.acos(r / (cy - tip[1]))
    left = (cx - r * math.sin(theta), cy - r * math.cos(theta))
    right = (cx + r * math.sin(theta), cy - r * math.cos(theta))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    d.polygon([tip, left, (cx, cy), right], fill=255)
    return m


def gradient(size: int) -> Image.Image:
    g = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        g.putpixel((0, y), tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)))
    return g.resize((size, size))


def wave(draw: ImageDraw.ImageDraw, size: int, y: float, amp: float, width: float, phase: float):
    """Filled wavy band (no polyline seams)."""
    xs = [size * 0.02 + size * 0.96 * i / 600 for i in range(601)]
    top = [(x, y - width / 2 + amp * math.sin(2 * math.pi * (x / size) * 2.0 + phase)) for x in xs]
    bottom = [(x, yy + width) for x, yy in reversed(top)]
    draw.polygon(top + bottom, fill=255)


def make_icon() -> Image.Image:
    size = SS
    mask = droplet_mask(size)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(gradient(size), (0, 0), mask)

    # white waves, clipped to the droplet
    waves = Image.new("L", (size, size), 0)
    wd = ImageDraw.Draw(waves)
    wave(wd, size, size * 0.60, size * 0.035, size * 0.065, 0.0)
    wave(wd, size, size * 0.76, size * 0.035, size * 0.065, 0.9)
    # inset so waves don't touch the droplet edge
    # fast erosion: blur then keep only fully-inside pixels
    inner = mask.filter(ImageFilter.GaussianBlur(size * 0.03)).point(
        lambda v: 255 if v >= 250 else 0
    )
    waves = ImageChops.multiply(waves, inner)
    white = Image.new("RGBA", (size, size), (255, 255, 255, 255))
    img.paste(white, (0, 0), waves)

    # glossy highlight in the upper-left of the droplet
    hl = Image.new("L", (size, size), 0)
    hd = ImageDraw.Draw(hl)
    r = size * 0.36
    cx, cy = size / 2, size - r - size * 0.015
    box = [cx - r * 0.72, cy - r * 0.72, cx + r * 0.72, cy + r * 0.72]
    hd.arc(box, start=208, end=250, fill=255, width=int(size * 0.045))
    hl = ImageChops.multiply(hl, inner).point(lambda v: v * 190 // 255)
    overlay = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    overlay.putalpha(hl)
    return Image.alpha_composite(img, overlay)


def trim(img: Image.Image) -> Image.Image:
    return img.crop(img.getchannel("A").getbbox())


def square(img: Image.Image) -> Image.Image:
    w, h = img.size
    s = max(w, h)
    out = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    out.paste(img, ((s - w) // 2, (s - h) // 2))
    return out


def make_logo(icon: Image.Image, height: int, text_color) -> Image.Image:
    font = _font(int(height * 0.62))
    text = "Zodiac Exo"
    tb = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    tw, th = tb[2] - tb[0], tb[3] - tb[1]
    ic = icon.resize((int(icon.width * height / icon.height), height), Image.LANCZOS)
    gap = int(height * 0.22)
    canvas = Image.new("RGBA", (ic.width + gap + tw + 4, height), (0, 0, 0, 0))
    canvas.paste(ic, (0, 0), ic)
    d = ImageDraw.Draw(canvas)
    d.text((ic.width + gap - tb[0], (height - th) // 2 - tb[1]), text, font=font, fill=text_color)
    return trim(canvas)


icon_big = square(trim(make_icon()))
icon_big.resize((512, 512), Image.LANCZOS).save(OUT / "icon@2x.png", optimize=True)
icon_big.resize((256, 256), Image.LANCZOS).save(OUT / "icon.png", optimize=True)

trimmed_icon = trim(make_icon())
for prefix, color in (("", TEXT_LIGHT_BG), ("dark_", TEXT_DARK_BG)):
    big = make_logo(trimmed_icon, 1024, color)
    for name, h in ((f"{prefix}logo@2x.png", 256), (f"{prefix}logo.png", 128)):
        w = round(big.width * h / big.height)
        big.resize((w, h), Image.LANCZOS).save(OUT / name, optimize=True)

# preview sheet on light and dark backgrounds
logo = Image.open(OUT / "logo@2x.png")
dlogo = Image.open(OUT / "dark_logo@2x.png")
icon = Image.open(OUT / "icon@2x.png").resize((256, 256), Image.LANCZOS)
W = max(logo.width, dlogo.width) + 256 + 120
sheet = Image.new("RGB", (W, 2 * 336), (255, 255, 255))
dark = Image.new("RGB", (W, 336), (28, 28, 30))
sheet.paste(dark, (0, 336))
for row, lg in ((0, logo), (1, dlogo)):
    y = row * 336 + 40
    sheet.paste(icon, (40, y), icon)
    sheet.paste(lg, (40 + 256 + 40, y), lg)
sheet.save(PREVIEW)
for p in sorted(OUT.iterdir()):
    print(p.name, Image.open(p).size)
