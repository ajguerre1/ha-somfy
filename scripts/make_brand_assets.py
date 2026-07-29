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
    """A partially lowered blind: head rail, four slats, hem rail."""
    draw = ImageDraw.Draw(image)
    margin = size * 0.22
    width = size - 2 * margin
    left, right = margin, margin + width

    head_top = size * 0.20
    head_height = size * 0.055
    draw.rounded_rectangle(
        [(left, head_top), (right, head_top + head_height)],
        radius=head_height / 2,
        fill=RAIL,
    )

    slat_height = size * 0.045
    gap = size * 0.035
    y = head_top + head_height + gap
    for _ in range(4):
        draw.rounded_rectangle(
            [(left, y), (right, y + slat_height)], radius=slat_height / 2, fill=SLAT
        )
        y += slat_height + gap

    # Hem rail, inset slightly so the blind reads as hanging free.
    hem_height = size * 0.06
    inset = width * 0.06
    draw.rounded_rectangle(
        [(left + inset, y + gap * 0.4), (right - inset, y + gap * 0.4 + hem_height)],
        radius=hem_height / 2,
        fill=RAIL,
    )


def make_icon(size: int) -> Image.Image:
    image = _rounded_background(size)
    _draw_blind(image, size)
    return image


def make_logo(width: int, height: int) -> Image.Image:
    """Wordmark-free logo: the icon centred on a transparent wide canvas."""
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    icon = make_icon(height)
    image.paste(icon, ((width - height) // 2, 0), icon)
    return image


def main() -> int:
    BRAND_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for name, image in (
        ("icon.png", make_icon(256)),
        ("icon@2x.png", make_icon(512)),
        ("logo.png", make_logo(512, 256)),
        ("logo@2x.png", make_logo(1024, 512)),
    ):
        path = BRAND_DIR / name
        image.save(path, "PNG", optimize=True)
        written.append(path)

    for path in written:
        with Image.open(path) as check:
            print(f"  {path.relative_to(REPO_ROOT)}  {check.size[0]}x{check.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
