#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pillow"]
# ///
"""Convert an image to a raw 2bpp frame for the GDEM0397F81 4-color panel.

Pixel codes (2 bits, MSB-first, 4 pixels per byte):
  black=0b00  white=0b01  yellow=0b10  red=0b11

The controller's frame RAM is 800x680 but the visible glass is 800x480,
so the image is rendered at 800x480 and the remaining 200 rows are padding.
Use --image-pos to move the image within the 680-row frame to discover
where the visible window actually sits.

Usage:
  uv run tools/img2epd.py photo.png                 # -> photo.bin (136,000 bytes)
  uv run tools/img2epd.py photo.png -o out.bin --image-pos bottom --no-dither
"""

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps

WIDTH = 800
VISIBLE_H = 480
FRAME_H = 680

# palette index == panel pixel code
PALETTE = [
    (0x00, 0x00, 0x00),  # 0b00 black
    (0xFF, 0xFF, 0xFF),  # 0b01 white
    (0xFF, 0xFF, 0x00),  # 0b10 yellow
    (0xFF, 0x00, 0x00),  # 0b11 red
]
COLOR_NAMES = ["black", "white", "yellow", "red"]


def edge_color(strip: Image.Image) -> tuple:
    """Average color of an edge strip, for filling the adjacent bar."""
    r, g, b = strip.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
    return (r, g, b)


# perceptual luminance weights: the eye is most sensitive to green, least to blue
W_R, W_G, W_B = 0.30, 0.59, 0.11


def quantize(img: Image.Image, dither: bool) -> Image.Image:
    """Floyd-Steinberg with serpentine scanning and perceptual color distance."""
    w, h = img.size
    buf = [list(p) for p in img.getdata()]
    idx = bytearray(w * h)
    for y in range(h):
        serp = y & 1
        xs = range(w - 1, -1, -1) if serp else range(w)
        for x in xs:
            i = y * w + x
            p = buf[i]
            r = min(255.0, max(0.0, p[0]))
            g = min(255.0, max(0.0, p[1]))
            b = min(255.0, max(0.0, p[2]))
            best, bd = 0, 1e18
            for k, (pr, pg, pb) in enumerate(PALETTE):
                dr, dg, db = r - pr, g - pg, b - pb
                d = W_R * dr * dr + W_G * dg * dg + W_B * db * db
                if d < bd:
                    bd, best = d, k
            idx[i] = best
            if dither:
                pr, pg, pb = PALETTE[best]
                er, eg, eb = r - pr, g - pg, b - pb
                fwd = -1 if serp else 1
                for dy, dx, wt in ((0, fwd, 7), (1, -fwd, 3), (1, 0, 5), (1, fwd, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= nx < w and ny < h:
                        q = buf[ny * w + nx]
                        f = wt / 16.0
                        q[0] += er * f
                        q[1] += eg * f
                        q[2] += eb * f
    out = Image.new("P", (w, h))
    out.putdata(list(idx))
    flat = [c for rgb in PALETTE for c in rgb]
    out.putpalette(flat + flat[:3] * (256 - len(PALETTE)))
    return out


def pack_rows(indexed: Image.Image) -> bytes:
    px = indexed.load()
    out = bytearray()
    for y in range(indexed.height):
        for x in range(0, WIDTH, 4):
            byte = 0
            for i in range(4):
                byte = (byte << 2) | (px[x + i, y] & 0b11)
            out.append(byte)
    return bytes(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="output .bin (default: <image>.bin)")
    ap.add_argument(
        "--image-pos",
        choices=["top", "middle", "bottom"],
        default="top",
        help="where the 480 visible rows sit inside the 680-row frame (default: top)",
    )
    ap.add_argument(
        "--pad-color",
        choices=COLOR_NAMES,
        default="white",
        help="color for the 200 off-screen padding rows (default: white)",
    )
    ap.add_argument("--no-dither", action="store_true", help="nearest color only, no dithering")
    ap.add_argument(
        "--rotate", type=int, choices=[0, 90, 180, 270], default=90,
        help="rotate the image N degrees clockwise before fitting (default: 90)",
    )
    ap.add_argument(
        "--saturation", type=float, default=1.0,
        help="saturation boost before quantizing, e.g. 1.4 (default: 1.0)",
    )
    ap.add_argument(
        "--contrast", type=float, default=1.0,
        help="contrast boost before quantizing, e.g. 1.2 (default: 1.0)",
    )
    ap.add_argument(
        "--preview", action="store_true",
        help="also save <out>.preview.png showing the quantized 4-color result",
    )
    args = ap.parse_args()

    out_path = args.out
    if out_path is None:
        # inside an input/ dir, default to the sibling output/ dir
        if args.image.parent.name == "input":
            out_dir = args.image.parent.parent / "output"
            out_dir.mkdir(exist_ok=True)
            out_path = out_dir / (args.image.stem + ".bin")
        else:
            out_path = args.image.with_suffix(".bin")

    img = ImageOps.exif_transpose(Image.open(args.image)).convert("RGB")
    if args.rotate:
        img = img.rotate(-args.rotate, expand=True)
    if img.size != (WIDTH, VISIBLE_H):
        scale = min(WIDTH / img.width, VISIBLE_H / img.height)
        w, h = round(img.width * scale), round(img.height * scale)
        print(f"fitting {img.width}x{img.height} -> {w}x{h} on white {WIDTH}x{VISIBLE_H}")
        scaled = img.resize((w, h), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (WIDTH, VISIBLE_H), (0xFF, 0xFF, 0xFF))
        x0, y0 = (WIDTH - w) // 2, (VISIBLE_H - h) // 2
        strip = 16  # edge strip whose average color fills the adjacent bar
        if w < WIDTH:  # pillarbox: bars left/right
            left = edge_color(scaled.crop((0, 0, strip, h)))
            right = edge_color(scaled.crop((w - strip, 0, w, h)))
            canvas.paste(left, (0, 0, x0, VISIBLE_H))
            canvas.paste(right, (x0 + w, 0, WIDTH, VISIBLE_H))
        if h < VISIBLE_H:  # letterbox: bars top/bottom
            top = edge_color(scaled.crop((0, 0, w, strip)))
            bottom = edge_color(scaled.crop((0, h - strip, w, h)))
            canvas.paste(top, (0, 0, WIDTH, y0))
            canvas.paste(bottom, (0, y0 + h, WIDTH, VISIBLE_H))
        canvas.paste(scaled, (x0, y0))
        img = canvas

    if args.saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(args.saturation)
    if args.contrast != 1.0:
        img = ImageEnhance.Contrast(img).enhance(args.contrast)

    indexed = quantize(img, dither=not args.no_dither)
    if args.preview:
        preview_path = out_path.with_suffix(".preview.png")
        indexed.convert("RGB").save(preview_path)
        print(f"wrote {preview_path}")
    image_rows = pack_rows(indexed)

    pad_code = COLOR_NAMES.index(args.pad_color)
    pad_byte = pad_code * 0b01_01_01_01
    pad_row = bytes([pad_byte]) * (WIDTH // 4)
    pad_total = FRAME_H - VISIBLE_H

    if args.image_pos == "top":
        before, after = 0, pad_total
    elif args.image_pos == "bottom":
        before, after = pad_total, 0
    else:
        before = pad_total // 2
        after = pad_total - before

    frame = pad_row * before + image_rows + pad_row * after
    expected = WIDTH * FRAME_H // 4
    assert len(frame) == expected, f"frame is {len(frame)} bytes, expected {expected}"

    out_path.write_bytes(frame)
    print(f"wrote {out_path} ({len(frame):,} bytes, image at {args.image_pos})")


if __name__ == "__main__":
    main()
