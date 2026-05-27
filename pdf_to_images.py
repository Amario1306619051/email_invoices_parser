"""Convert input (PDF / PNG / JPEG / TIFF) into a list of PNG images.

Pipeline ini selalu image-first: PDF native pun dirender ke PNG dulu sebelum
dikirim ke OCR engine (LightOn OCR atau GPT-4o vision)."""
from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

import config

log = logging.getLogger(__name__)

DEFAULT_DPI = 200
MAX_LONG_SIDE = 2200  # cap supaya payload ke API tidak meledak
PAGE_IMAGE_FORMAT = "PNG"


def _save_image(img: Image.Image, target_dir: Path, stem: str, page_idx: int) -> Path:
    out_path = target_dir / f"{stem}_p{page_idx + 1:02d}.png"
    img.save(out_path, format=PAGE_IMAGE_FORMAT, optimize=True)
    return out_path


def _resize_if_needed(img: Image.Image) -> Image.Image:
    w, h = img.size
    long_side = max(w, h)
    if long_side <= MAX_LONG_SIDE:
        return img
    scale = MAX_LONG_SIDE / long_side
    new_size = (int(w * scale), int(h * scale))
    return img.resize(new_size, Image.LANCZOS)


def _render_pdf(path: Path, target_dir: Path, dpi: int) -> list[Path]:
    out_paths: list[Path] = []
    doc = fitz.open(path)
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=dpi)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        img = _resize_if_needed(img)
        out_paths.append(_save_image(img, target_dir, path.stem, i))
    doc.close()
    return out_paths


def _normalize_image(path: Path, target_dir: Path) -> list[Path]:
    with Image.open(path) as im:
        img = im.convert("RGB")
        img = _resize_if_needed(img)
        out = _save_image(img, target_dir, path.stem, 0)
    return [out]


def to_images(path: Path, dpi: int = DEFAULT_DPI) -> list[Path]:
    """Return list of PNG paths (one per page). PDF → render; image → normalize."""
    suffix = path.suffix.lower()
    target_dir = config.DOWNLOADS_DIR / "pages"
    target_dir.mkdir(parents=True, exist_ok=True)

    if suffix == ".pdf":
        paths = _render_pdf(path, target_dir, dpi)
    elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        paths = _normalize_image(path, target_dir)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")

    log.info("Rendered %s → %d page image(s)", path.name, len(paths))
    return paths
