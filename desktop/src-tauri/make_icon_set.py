"""Generate the platform icon set Tauri needs from app-icon.png into ./icons/.

Produces the PNGs referenced by tauri.conf.json plus a multi-size .ico and .icns.
Run:  python make_icon_set.py
"""
from __future__ import annotations

import os

from PIL import Image

SRC = "app-icon.png"
OUT = "icons"


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    base = Image.open(SRC).convert("RGBA")

    def resized(n: int) -> Image.Image:
        return base.resize((n, n), Image.LANCZOS)

    # Standard Tauri PNGs.
    pngs = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
        # Windows Store / MSIX square logos (harmless to ship; used only by that target).
        "Square30x30Logo.png": 30,
        "Square44x44Logo.png": 44,
        "Square71x71Logo.png": 71,
        "Square89x89Logo.png": 89,
        "Square107x107Logo.png": 107,
        "Square142x142Logo.png": 142,
        "Square150x150Logo.png": 150,
        "Square284x284Logo.png": 284,
        "Square310x310Logo.png": 310,
        "StoreLogo.png": 50,
    }
    for name, n in pngs.items():
        resized(n).save(os.path.join(OUT, name))

    # Windows .ico (multi-resolution).
    resized(256).save(os.path.join(OUT, "icon.ico"),
                      sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])

    # macOS .icns (Pillow packs the standard sizes).
    resized(1024).save(os.path.join(OUT, "icon.icns"))

    print("generated", len(pngs) + 2, "icon files in", OUT)


if __name__ == "__main__":
    main()
