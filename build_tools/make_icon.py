"""Bikin assets/noktah.ico untuk Noktah (panel gelap + 3 batang equalizer)."""
import os

from PIL import Image, ImageDraw

SIZES = [16, 24, 32, 48, 64, 128, 256]
BG = (17, 17, 20, 255)
EDGE = (58, 58, 66, 255)
BAR = (255, 255, 255, 255)
BAR_ACCENT = (232, 168, 118, 255)


def draw(size):
    s = size * 4  # supersampling
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # panel: sudut atas rata (menempel layar), bawah membulat
    pad_x = int(s * 0.08)
    top = int(s * 0.18)
    bottom = int(s * 0.86)
    r = int((bottom - top) * 0.34)
    d.rounded_rectangle(
        [pad_x, top, s - pad_x, bottom], radius=r, fill=BG, outline=EDGE, width=max(1, s // 64)
    )
    # ratakan sisi atas supaya terlihat "menempel"
    d.rectangle([pad_x, top, s - pad_x, top + r], fill=BG)

    # equalizer 3 batang
    heights = (0.34, 0.52, 0.24)
    bar_w = max(2, int(s * 0.075))
    gap = int(s * 0.055)
    total = len(heights) * bar_w + (len(heights) - 1) * gap
    x = (s - total) // 2
    cy = (top + bottom) // 2
    box_h = bottom - top
    for i, frac in enumerate(heights):
        h = int(box_h * frac)
        color = BAR_ACCENT if i == 1 else BAR
        d.rounded_rectangle(
            [x, cy - h // 2, x + bar_w, cy + h // 2], radius=bar_w // 2, fill=color
        )
        x += bar_w + gap

    return img.resize((size, size), Image.LANCZOS)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "assets")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, "noktah.ico")

    frames = [draw(s) for s in SIZES]
    frames[-1].save(out, format="ICO", sizes=[(s, s) for s in SIZES])
    png = os.path.join(out_dir, "noktah.png")
    frames[-1].save(png, format="PNG")
    print("icon:", out)
    print("png :", png)


if __name__ == "__main__":
    main()
