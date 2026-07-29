#!/usr/bin/env python3
"""Generate the HACS/Home Assistant brand assets.

HACS requires brand assets at custom_components/<domain>/brand/ unless the
integration is listed in the home-assistant/brands repository. Generating them
from a script keeps them reproducible and reviewable, rather than checking in
opaque binaries nobody can regenerate.

The mark is a deliberately generic rolled blind -- Somfy's own logo is a
trademark and is not used here.

    python scripts/make_brand_assets.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = REPO_ROOT / "custom_components" / "ha_somfy" / "brand"

BACKGROUND = (31, 41, 51, 255)  # deep slate
SLAT = (253, 186, 46, 255)  # amber, echoing the gateway's own UI accent
RAIL = (255, 214, 122, 255)  # lighter amber for the head and hem rails


def _rounded_background(size: int) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([(0, 0), (size - 1, size - 1)], radius=int(size * 0.22), fill=BACKGROUND)
    return image


def _draw_blind(image: Image.Image, size: int) -> None:
    """A partially lowered blind: head rail, three slats, hem rail.

    Deliberately chunky. HACS renders this at roughly 40px in its store list,
    where thin bars with small gaps blur into a single smudge. Three thick
    slats survive the downscale; four thin ones did not.
    """
    draw = ImageDraw.Draw(image)
    margin = size * 0.20
    width = size - 2 * margin
    left, right = margin, margin + width

    rail_height = size * 0.075
    slat_height = size * 0.075
    gap = size * 0.05
    hem_height = size * 0.09

    y = size * 0.20
    draw.rounded_rectangle([(left, y), (right, y + rail_height)], radius=rail_height / 2, fill=RAIL)
    y += rail_height + gap

    for _ in range(3):
        draw.rounded_rectangle(
            [(left, y), (right, y + slat_height)], radius=slat_height / 2, fill=SLAT
        )
        y += slat_height + gap

    # Hem rail, inset slightly so the blind reads as hanging free.
    inset = width * 0.08
    draw.rounded_rectangle(
        [(left + inset, y), (right - inset, y + hem_height)],
        radius=hem_height / 2,
        fill=RAIL,
    )


def make_icon(size: int) -> Image.Image:
    image = _rounded_background(size)
    _draw_blind(image, size)
    return image


# No logo.png is produced. home-assistant/brands treats logo as optional and
# falls back to the icon, and it rejects images with empty space at the edges.
# A "logo" that is just the square icon centred on a wide transparent canvas is
# all padding: it would be rejected, and it would add nothing over the fallback.


def check_trimmed(path: Path) -> str:
    """home-assistant/brands requires minimal empty space at the edges.

    An untrimmed image is rejected there, so verify rather than assume: the
    alpha bounding box must span the whole canvas.
    """
    with Image.open(path) as image:
        bbox = image.convert("RGBA").getbbox()
        if bbox == (0, 0, *image.size):
            return "trimmed"
        return f"NOT TRIMMED - content bbox {bbox} inside {image.size}"


def main() -> int:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for stale in ("logo.png", "logo@2x.png"):
        (BRAND_DIR / stale).unlink(missing_ok=True)

    for name, image in (
        ("icon.png", make_icon(256)),
        ("icon@2x.png", make_icon(512)),
    ):
        path = BRAND_DIR / name
        image.save(path, "PNG", optimize=True)
        written.append(path)

    for path in written:
        with Image.open(path) as check:
            size = f"{check.size[0]}x{check.size[1]}"
        print(f"  {path.relative_to(REPO_ROOT)}  {size}  {check_trimmed(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
