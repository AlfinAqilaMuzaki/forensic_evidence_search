"""Cache thumbnail on-disk untuk grid hasil pencarian di GUI.

Thumbnail dibuat sekali (lazy, saat pertama kali ditampilkan) dan disimpan
di folder index (bukan folder dataset), supaya:
- file sumber tidak pernah tersentuh;
- GUI tidak perlu decode gambar full-res tiap kali menggambar ulang grid.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from . import config


class ThumbnailCache:
    def __init__(self, index_dir: str | Path):
        self.dir = Path(index_dir) / config.THUMB_DIRNAME
        self.dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, image_id: int) -> Path:
        return self.dir / f"{image_id}.jpg"

    def get_or_create(self, image_id: int, source_path: str) -> str | None:
        out = self.path_for(image_id)
        if out.exists():
            return str(out)
        from .utils import safe_open_image

        img = safe_open_image(source_path)
        if img is None:
            return None
        try:
            img.thumbnail(config.THUMB_SIZE)
            img.convert("RGB").save(out, "JPEG", quality=85)
        finally:
            img.close()
        return str(out)
