"""Render the source app icon (1024x1024 PNG) for Open Claude Desktop.

An original, brand-neutral mark: a rounded-square tile with a soft indigo→violet
diagonal gradient and a white outlined speech bubble containing three dots — a
universal "chat" motif, deliberately unlike any third-party product's branding.
Run:  python make_icon.py   ->  writes app-icon.png
Then: tauri icon app-icon.png  (generates the full platform icon set)
"""
from __future__ import annotations

from PIL import Image, ImageDraw

S = 1024
# Rounded-square tile inset a little from the edges (macOS-style squircle padding).
PAD = 96
RADIUS = 224
A = PAD
B = S - PAD


def _lerp(c1, c2, t):
    return tuple(round(a + (b - a) * t) for a, b in zip(c1, c2, strict=True))


def gradient_tile() -> Image.Image:
    """Diagonal indigo→violet gradient, masked to a rounded square."""
    top_left = (79, 70, 229)     # indigo-600
    bottom_right = (139, 92, 246)  # violet-500
    grad = Image.new("RGB", (S, S))
    px = grad.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * (S - 1))
            px[x, y] = _lerp(top_left, bottom_right, t)

    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([A, A, B, B], radius=RADIUS, fill=255)

    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    tile.paste(grad, (0, 0), mask)
    return tile


def draw_bubble(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    # Speech bubble body (rounded rect) + a tail, drawn as a white outline.
    bx0, by0, bx1, by1 = 300, 320, 724, 620
    stroke = 34
    white = (255, 255, 255, 255)
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=96, outline=white, width=stroke)
    # Tail: a small triangle at the bottom-left, filled then re-outlined to blend.
    tail = [(388, by1 - 6), (388, by1 + 96), (486, by1 - 6)]
    d.polygon(tail, fill=white)
    # Knock the inner seam of the tail back so it reads as part of the outlined bubble.
    d.line([(388, by1 - 6), (486, by1 - 6)], fill=(0, 0, 0, 0), width=2)
    # Three dots.
    cy = (by0 + by1) // 2
    for cx in (420, 512, 604):
        d.ellipse([cx - 30, cy - 30, cx + 30, cy + 30], fill=white)


def main() -> None:
    img = gradient_tile()
    draw_bubble(img)
    img.save("app-icon.png")
    print("wrote app-icon.png", img.size)


if __name__ == "__main__":
    main()
