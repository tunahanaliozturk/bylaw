"""Avatar thumbnails through ImageMagick."""

import subprocess

from app.files import UPLOAD_DIR


def make_thumbnail(client_name: str) -> str:
    """Write a 128 pixel thumbnail of the upload the client named and return the thumbnail's name."""
    target = f"thumb-{client_name}"
    subprocess.run(f"convert {UPLOAD_DIR / client_name} -resize 128x128 {UPLOAD_DIR / target}", shell=True, check=True)
    return target
