"""Avatar thumbnails through ImageMagick."""

import subprocess
from pathlib import Path


def make_thumbnail(avatar: Path) -> Path:
    """Write a 128 pixel thumbnail next to an avatar that save_avatar stored, and return its path."""
    target = avatar.with_name(f"thumb-{avatar.name}")
    subprocess.run(["convert", str(avatar), "-resize", "128x128", str(target)], check=True)
    return target
