"""Render the source app icon (1024x1024 PNG) for VersoWork.

Crafted editorial mark: warm charcoal squircle (#1E1C19) carrying two facing folio
pages forming a geometric "V" (left page in warm parchment #F0EEE6 = Chat, right page
in terracotta #D4A27F = Code & Artifacts).
"""
from __future__ import annotations

from PIL import Image, ImageDraw

S = 1024
PAD = 88
RADIUS = 220


def render_versowork_icon() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Squircle tile in deep warm ink (#1E1C19) with subtle inner border (#332F29)
    d.rounded_rectangle([PAD, PAD, S - PAD, S - PAD], radius=RADIUS,
                        fill=(30, 28, 25, 255), outline=(56, 51, 44, 255), width=8)

    # Left folio wing ("Recto" - Chat) in warm parchment (#F0EEE6)
    left_wing = [
        (272, 290),
        (430, 290),
        (512, 650),
        (476, 742),
        (392, 742),
    ]
    d.polygon(left_wing, fill=(240, 238, 230, 255))

    # Right folio wing ("Verso" - Artifacts & Code) in warm terracotta (#D4A27F)
    right_wing = [
        (594, 290),
        (752, 290),
        (632, 742),
        (548, 742),
        (512, 650),
    ]
    d.polygon(right_wing, fill=(212, 162, 127, 255))

    # Subtle spine highlight dot at top center
    d.ellipse([492, 254, 532, 294], fill=(212, 162, 127, 230))
    return img


def main() -> None:
    img = render_versowork_icon()
    img.save("app-icon.png")
    print("wrote app-icon.png", img.size)


if __name__ == "__main__":
    main()
