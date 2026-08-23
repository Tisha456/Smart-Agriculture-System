"""Image I/O helpers shared by cleaning, splitting, and evaluation:
safe decoding, content hashing, perceptual hashing, and basic quality
checks. Kept dependency-light (Pillow + imagehash) since B2 runs this
over the whole corpus and needs to be fast and parallelizable.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import imagehash
except ImportError:  # imagehash is a thin wrapper; fail loudly at call time instead
    imagehash = None  # type: ignore

MIN_SIDE_PX = 64
MAX_ASPECT_RATIO = 5.0
PHASH_HAMMING_THRESHOLD = 5


@dataclass
class ImageInfo:
    ok: bool
    reason: Optional[str]  # rejection reason if ok=False
    width: int = 0
    height: int = 0
    sha256: str = ""
    phash: str = ""


def safe_open(path: Path) -> Optional[Image.Image]:
    """Open + fully decode an image, correcting EXIF orientation. Returns
    None if the file is unreadable/truncated/not an image.
    """
    try:
        img = Image.open(path)
        img.load()  # force full decode now, not lazily later
        img = ImageOps.exif_transpose(img)
        return img.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return None


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def phash_of_image(img: Image.Image) -> str:
    if imagehash is None:
        raise ImportError("imagehash is required (pip install imagehash)")
    return str(imagehash.phash(img))


def hamming_distance_hex(a: str, b: str) -> int:
    """Hamming distance between two hex-encoded perceptual hashes of equal
    bit length (imagehash's default phash is 64 bits / 16 hex chars).
    """
    ia = int(a, 16)
    ib = int(b, 16)
    return bin(ia ^ ib).count("1")


def inspect_image(path: Path) -> ImageInfo:
    """Run the full quality pipeline on one image: decode, size/aspect
    checks, sha256, phash. Does NOT check for duplicates against other
    images — that's a corpus-wide step done by the caller (clean.py).
    """
    img = safe_open(path)
    if img is None:
        return ImageInfo(ok=False, reason="unreadable")

    w, h = img.size
    if min(w, h) < MIN_SIDE_PX:
        return ImageInfo(ok=False, reason="too_small", width=w, height=h)

    aspect = max(w, h) / max(1, min(w, h))
    if aspect > MAX_ASPECT_RATIO:
        return ImageInfo(ok=False, reason="bad_aspect", width=w, height=h)

    file_hash = sha256_of_file(path)
    try:
        p_hash = phash_of_image(img)
    except ImportError:
        p_hash = ""

    return ImageInfo(ok=True, reason=None, width=w, height=h, sha256=file_hash, phash=p_hash)
