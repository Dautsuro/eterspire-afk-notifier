"""Generates the app icon (eterspire_notifier/assets/icon.png and icon.ico).

Run once: python tools/make_icon.py  (needs Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "eterspire_notifier" / "assets"
SIZE = 1024  # drawn big, then scaled down for smooth edges

PANEL = (135, 64, 46)  # the game's pop-up colour
GOLD = (232, 176, 48)
FISH = (236, 242, 248)

img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle((24, 24, SIZE - 24, SIZE - 24), radius=200, fill=GOLD)
d.rounded_rectangle((84, 84, SIZE - 84, SIZE - 84), radius=150, fill=PANEL)
# fish: body, tail, eye
d.ellipse((190, 330, 720, 690), fill=FISH)
d.polygon([(660, 510), (860, 340), (860, 680)], fill=FISH)
d.ellipse((300, 450, 370, 520), fill=PANEL)
# alert badge
d.ellipse((640, 120, 900, 380), fill=GOLD, outline=PANEL, width=28)
d.rounded_rectangle((752, 165, 790, 290), radius=18, fill=PANEL)
d.ellipse((749, 305, 793, 349), fill=PANEL)

OUT.mkdir(parents=True, exist_ok=True)
small = img.resize((256, 256), Image.LANCZOS)
small.save(OUT / "icon.png")
small.save(OUT / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
