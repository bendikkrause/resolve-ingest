"""Generate the platform icon files from packaging/icon.png.

    .venv/bin/python packaging/make_icons.py

Writes icon.icns (macOS) and icon.ico (Windows) beside the master. Both are
committed, so neither Pillow nor a Mac is needed to build the app — this only
needs running when the artwork changes.

The master is a 1024x1024 RGBA rounded square with transparent corners, cropped
from the source artwork. Requires Pillow, and iconutil for the .icns (macOS only).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
MASTER = HERE / "icon.png"

# Apple's required iconset members: (points, scale).
ICNS_SIZES = [(16, 1), (16, 2), (32, 1), (32, 2), (128, 1), (128, 2), (256, 1), (256, 2), (512, 1), (512, 2)]
# Windows packs every size into the one .ico; 256 is what modern shells display.
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]


def load_master() -> Image.Image:
    image = Image.open(MASTER).convert("RGBA")
    if image.size != (1024, 1024):
        sys.exit(f"expected a 1024x1024 master, got {image.size}")
    return image


def build_ico(master: Image.Image) -> Path:
    target = HERE / "icon.ico"
    master.save(target, format="ICO", sizes=[(s, s) for s in ICO_SIZES])
    return target


def build_icns(master: Image.Image) -> Path | None:
    """Requires iconutil, so macOS only. Returns None elsewhere."""
    if not shutil.which("iconutil"):
        return None

    target = HERE / "icon.icns"
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for points, scale in ICNS_SIZES:
            pixels = points * scale
            suffix = "@2x" if scale == 2 else ""
            resized = master.resize((pixels, pixels), Image.LANCZOS)
            resized.save(iconset / f"icon_{points}x{points}{suffix}.png")
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True
        )
    return target


def main() -> int:
    master = load_master()
    ico = build_ico(master)
    print(f"wrote {ico.name}  ({ico.stat().st_size // 1024} KB, sizes {ICO_SIZES})")

    icns = build_icns(master)
    if icns:
        print(f"wrote {icns.name} ({icns.stat().st_size // 1024} KB)")
    else:
        print("skipped icon.icns — iconutil not available (macOS only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
