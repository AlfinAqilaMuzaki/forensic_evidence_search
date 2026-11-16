"""Buat dataset sintetis kecil untuk validasi bahwa sistem mencari berdasarkan
KONTEN VISUAL, bukan nama file/metadata.

Menghasilkan:
- N gambar "distractor" (scene acak, beda-beda) sebagai noise.
- 1 gambar "scene_similar" yang komposisinya mirip tapi BUKAN gambar yang sama
  (dipakai untuk memastikan skor similarity-nya lebih rendah daripada
  near-duplicate asli).
- 1 gambar referensi asli ("reference_original.png") beserta beberapa varian
  turunannya yang HARUS ditemukan sebagai hasil teratas:
    - reference_renamed_copy.jpg   (file identik, nama beda)
    - reference_resized.jpg        (di-resize lebih kecil)
    - reference_recompressed.jpg   (disimpan ulang JPEG kualitas rendah)
    - reference_cropped.jpg        (crop ~25% dari tepi)
    - reference_screenshot.png     (disimpan di dalam "frame" mirip screenshot)
    - reference_watermarked.jpg    (ditambah watermark teks)
    - reference_brightness.jpg     (brightness/kontras diubah)
    - reference_webp.webp          (format berbeda)

Semua file ditulis ke folder output; TIDAK ada file yang dimodifikasi di
tempat lain.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFont


def draw_scene(seed: int, size=(512, 512)) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", size, color=(rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
    draw = ImageDraw.Draw(img)
    for _ in range(rng.randint(5, 12)):
        shape = rng.choice(["ellipse", "rectangle", "line"])
        x0, y0 = rng.randint(0, size[0]), rng.randint(0, size[1])
        x1, y1 = rng.randint(0, size[0]), rng.randint(0, size[1])
        color = (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255))
        xmin, xmax = sorted([x0, x1])
        ymin, ymax = sorted([y0, y1])
        if xmin == xmax:
            xmax += 1
        if ymin == ymax:
            ymax += 1
        if shape == "ellipse":
            draw.ellipse([xmin, ymin, xmax, ymax], fill=color)
        elif shape == "rectangle":
            draw.rectangle([xmin, ymin, xmax, ymax], fill=color)
        else:
            draw.line([x0, y0, x1, y1], fill=color, width=rng.randint(2, 10))
    return img


def make_screenshot_frame(img: Image.Image) -> Image.Image:
    """Simulasikan hasil screenshot: gambar ditempel di kanvas lebih besar + border UI palsu."""
    pad_top, pad_side, pad_bottom = 60, 20, 20
    canvas = Image.new("RGB", (img.width + pad_side * 2, img.height + pad_top + pad_bottom), (40, 40, 40))
    canvas.paste(img, (pad_side, pad_top))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle([0, 0, canvas.width, pad_top - 5], fill=(230, 230, 230))
    draw.ellipse([15, 20, 30, 35], fill=(255, 95, 86))
    draw.ellipse([40, 20, 55, 35], fill=(255, 189, 46))
    return canvas


def add_watermark(img: Image.Image) -> Image.Image:
    img = img.copy()
    draw = ImageDraw.Draw(img)
    text = "SAMPLE WATERMARK"
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    draw.text((img.width - 220, img.height - 30), text, fill=(255, 255, 255), font=font)
    return img


def build(output_dir: str, n_distractors: int = 40, seed: int = 42) -> None:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)

    # 1. distractors
    distractor_dir = out / "distractors"
    distractor_dir.mkdir(exist_ok=True)
    for i in range(n_distractors):
        img = draw_scene(seed=1000 + i)
        img.save(distractor_dir / f"distractor_{i:04d}.jpg", quality=90)

    # 2. scene mirip tapi bukan gambar yang sama (skor harus < near-duplicate asli)
    similar_scene = draw_scene(seed=777)
    similar_scene.save(out / "scene_similar_but_different.jpg", quality=90)

    # 3. gambar referensi asli + varian
    ref = draw_scene(seed=9999)
    ref.save(out / "reference_original.png")

    ref.save(out / "reference_renamed_copy.jpg", quality=95)

    resized = ref.resize((ref.width // 2, ref.height // 2))
    resized.save(out / "reference_resized.jpg", quality=95)

    ref.save(out / "reference_recompressed.jpg", quality=15)

    w, h = ref.size
    cropped = ref.crop((int(w * 0.15), int(h * 0.15), w, h))  # crop ~15% dari sisi kiri/atas
    cropped.save(out / "reference_cropped.jpg", quality=90)

    screenshot = make_screenshot_frame(ref)
    screenshot.save(out / "reference_screenshot.png")

    watermarked = add_watermark(ref)
    watermarked.save(out / "reference_watermarked.jpg", quality=90)

    bright = ImageEnhance.Brightness(ref).enhance(1.4)
    bright = ImageEnhance.Contrast(bright).enhance(0.8)
    bright.save(out / "reference_brightness.jpg", quality=90)

    try:
        ref.save(out / "reference_webp.webp", format="WEBP", quality=90)
    except Exception as exc:  # pragma: no cover
        print(f"Lewati format WEBP (tidak didukung Pillow di sistem ini): {exc}")

    # 4. satu file corrupt untuk memastikan robustness (tidak menghentikan indexing)
    (out / "corrupt_file.jpg").write_bytes(b"not a real image")

    print(f"Dataset uji dibuat di: {out.resolve()}")
    print(f"Total distractor: {n_distractors}")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "test_dataset"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 40
    build(target, n)
