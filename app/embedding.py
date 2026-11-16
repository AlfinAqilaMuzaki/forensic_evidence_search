"""Ekstraksi visual embedding menggunakan CLIP (open_clip).

Kenapa CLIP?
- CLIP dilatih untuk memetakan isi VISUAL gambar (bukan metadata/nama file)
  ke sebuah vector di ruang embedding, sedemikian rupa sehingga gambar dengan
  isi/scene yang mirip punya vector yang berdekatan (cosine similarity tinggi).
- Cukup robust terhadap resize, kompresi ulang, perubahan brightness/kontras
  ringan, dan watermark kecil, karena encoder bekerja pada representasi
  visual level-tinggi, bukan piksel mentah.
- Tidak menggunakan face recognition maupun metadata sama sekali -- input
  satu-satunya adalah pixel gambar itu sendiri.

Model default: ViT-B-32 (pretrained "openai"), embedding 512 dimensi.
Vector di-normalisasi L2 sehingga cosine similarity == inner product, yang
cocok dipakai langsung dengan FAISS metric INNER_PRODUCT.

Setiap gambar hanya dibuka SEKALI dari disk per proses indexing: dalam
pembukaan itu langsung dihitung perceptual hash (pHash/dHash) sekaligus
tensor CLIP, supaya I/O tidak dobel untuk dataset besar (~200.000 file).
"""
from __future__ import annotations

import logging
from typing import Iterable

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset

from . import config
from .hashing import compute_hashes
from .utils import safe_open_image

logger = logging.getLogger(__name__)


class ImageRecord:
    __slots__ = ("idx", "valid", "tensor", "phash", "dhash", "width", "height", "error")

    def __init__(self, idx, valid, tensor=None, phash="", dhash="", width=0, height=0, error=""):
        self.idx = idx
        self.valid = valid
        self.tensor = tensor
        self.phash = phash
        self.dhash = dhash
        self.width = width
        self.height = height
        self.error = error


def _collate(batch: list[ImageRecord]) -> list[ImageRecord]:
    return batch


class _ImagePathDataset(Dataset):
    """Dataset tipis: satu gambar dibaca, di-hash, dan di-preprocess per item.

    Sengaja TIDAK meng-cache gambar full-res di memori -- gambar asli dibuang
    segera setelah tensor & hash-nya diambil. Ini yang membuat indexing
    200.000 gambar tetap punya jejak memori yang datar (bounded).
    """

    def __init__(self, paths: list[str], preprocess):
        self.paths = paths
        self.preprocess = preprocess

    def __len__(self) -> int:
        return len(self.paths)

    def __getitem__(self, idx: int) -> ImageRecord:
        path = self.paths[idx]
        img = safe_open_image(path)
        if img is None:
            return ImageRecord(idx, False, error="unreadable/corrupt file")
        try:
            width, height = img.size
            phash, dhash = compute_hashes(img)
            tensor = self.preprocess(img)
        except Exception as exc:  # noqa: BLE001 - harus tetap lanjut ke file berikutnya
            return ImageRecord(idx, False, error=str(exc))
        finally:
            img.close()
        return ImageRecord(idx, True, tensor=tensor, phash=phash, dhash=dhash, width=width, height=height)


class ClipEmbedder:
    """Wrapper model CLIP untuk ekstraksi embedding batch dari daftar path gambar."""

    def __init__(self, device: str | None = None):
        import open_clip

        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        model, _, preprocess = open_clip.create_model_and_transforms(
            config.CLIP_MODEL_NAME, pretrained=config.CLIP_PRETRAINED
        )
        model.eval()
        model.to(self.device)
        self.model = model
        self.preprocess = preprocess
        logger.info(
            "CLIP model %s (%s) loaded on %s", config.CLIP_MODEL_NAME, config.CLIP_PRETRAINED, self.device
        )

    @torch.no_grad()
    def embed_single(self, img: Image.Image) -> np.ndarray:
        tensor = self.preprocess(img).unsqueeze(0).to(self.device)
        feat = self.model.encode_image(tensor)
        feat = feat / feat.norm(dim=-1, keepdim=True)
        return feat.squeeze(0).cpu().numpy().astype("float32")

    @torch.no_grad()
    def process_paths_batched(self, paths: list[str]) -> Iterable[list[tuple[ImageRecord, np.ndarray | None]]]:
        """Generator per-batch: list of (ImageRecord, embedding_or_None).

        Untuk record yang tidak valid (corrupt), embedding-nya None.
        """
        ds = _ImagePathDataset(paths, self.preprocess)
        loader = DataLoader(
            ds,
            batch_size=config.EMBED_BATCH_SIZE,
            num_workers=config.EMBED_NUM_WORKERS,
            shuffle=False,
            collate_fn=_collate,
        )
        for batch in loader:
            valid_records = [r for r in batch if r.valid]
            result: list[tuple[ImageRecord, np.ndarray | None]] = []
            if valid_records:
                tensors = torch.stack([r.tensor for r in valid_records]).to(self.device)
                feats = self.model.encode_image(tensors)
                feats = feats / feats.norm(dim=-1, keepdim=True).clamp_min(1e-8)
                feats_np = feats.cpu().numpy().astype("float32")
                feat_iter = iter(feats_np)
            else:
                feat_iter = iter(())
            for r in batch:
                if r.valid:
                    result.append((r, next(feat_iter)))
                else:
                    result.append((r, None))
            yield result
