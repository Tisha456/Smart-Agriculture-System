"""Phase E2 (conditional) — convert PlantDoc's Pascal VOC XML annotations
into a single-class YOLO detection dataset ("leaf"). All 28 PlantDoc
object classes collapse to one class here: this detector only needs to
answer "where are the leaves", not "which disease" — the Stage 1/2
classifiers answer that on each crop (see
plant-disease-implementation-plan.md section "E2").

Only run this if Phase E1 showed a material accuracy drop on multi-object
images (see plantdoc_eval.py's multi_object vs single_object metrics).

Uses PlantDoc's own "train" split for detector training so the images
evaluated in Phase E1 (which scans the whole raw/plantdoc tree) are not
also used to train the detector.

Usage:
    python -m agrisense_pd.detect.plantdoc_to_yolo
"""
from __future__ import annotations

import argparse
import random
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

from ..config import PATHS, SEED
from ..logging_utils import get_logger

log = get_logger("detect.plantdoc_to_yolo")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
LEAF_CLASS_ID = 0
VAL_FRACTION = 0.1


def _find_train_subdir(root: Path) -> Path | None:
    for d in root.rglob("*"):
        if d.is_dir() and d.name.lower() == "train":
            return d
    return None


def _voc_to_yolo_line(obj: ET.Element, img_w: int, img_h: int) -> str | None:
    bbox = obj.find("bndbox")
    if bbox is None:
        return None
    try:
        xmin = float(bbox.find("xmin").text)
        ymin = float(bbox.find("ymin").text)
        xmax = float(bbox.find("xmax").text)
        ymax = float(bbox.find("ymax").text)
    except (AttributeError, TypeError, ValueError):
        return None

    cx = ((xmin + xmax) / 2) / img_w
    cy = ((ymin + ymax) / 2) / img_h
    w = (xmax - xmin) / img_w
    h = (ymax - ymin) / img_h
    if w <= 0 or h <= 0:
        return None
    return f"{LEAF_CLASS_ID} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}"


def convert(out_dir: Path | None = None, seed: int = SEED) -> Path:
    from PIL import Image

    root = PATHS.raw_dataset("plantdoc")
    if not root.exists():
        raise FileNotFoundError(f"{root} not found — run download.py (Phase A2) first.")

    source_dir = _find_train_subdir(root)
    if source_dir is None:
        log.warning(
            "No 'train' subdirectory found under %s — falling back to a deterministic "
            "90/10 split of the whole PlantDoc set. NOTE: this means some images used "
            "to train the detector may overlap with Phase E1's evaluation set.",
            root,
        )
        source_dir = root

    xml_files = list(source_dir.rglob("*.xml"))
    log.info("Found %d annotation files under %s for detector training.", len(xml_files), source_dir)

    out_dir = out_dir or (PATHS.local_root / "data" / "detector_yolo")
    for split in ("train", "val"):
        (out_dir / "images" / split).mkdir(parents=True, exist_ok=True)
        (out_dir / "labels" / split).mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    n_written = 0
    n_skipped = 0

    for xf in xml_files:
        try:
            tree = ET.parse(xf)
        except ET.ParseError:
            n_skipped += 1
            continue

        filename_el = tree.find(".//filename")
        image_name = filename_el.text.strip() if filename_el is not None and filename_el.text else xf.stem
        image_path = None
        for ext in IMAGE_EXTS:
            candidate = xf.with_suffix(ext)
            if candidate.exists():
                image_path = candidate
                break
        if image_path is None:
            candidate = xf.parent / image_name
            if candidate.exists():
                image_path = candidate
        if image_path is None:
            n_skipped += 1
            continue

        try:
            with Image.open(image_path) as img:
                img_w, img_h = img.size
        except Exception:
            n_skipped += 1
            continue

        lines = []
        for obj in tree.findall(".//object"):
            line = _voc_to_yolo_line(obj, img_w, img_h)
            if line:
                lines.append(line)
        if not lines:
            n_skipped += 1
            continue

        split = "val" if rng.random() < VAL_FRACTION else "train"
        dest_img = out_dir / "images" / split / image_path.name
        dest_label = out_dir / "labels" / split / (image_path.stem + ".txt")
        shutil.copy2(image_path, dest_img)
        dest_label.write_text("\n".join(lines), encoding="utf-8")
        n_written += 1

    data_yaml = {
        "path": str(out_dir),
        "train": "images/train",
        "val": "images/val",
        "names": {LEAF_CLASS_ID: "leaf"},
    }
    yaml_path = out_dir / "data.yaml"
    with open(yaml_path, "w", encoding="utf-8") as f:
        yaml.dump(data_yaml, f)

    log.info("Converted %d images (%d skipped) -> %s", n_written, n_skipped, out_dir)
    print(f"Detector dataset ready: {n_written} images, {n_skipped} skipped, config at {yaml_path}")
    return yaml_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase E2: convert PlantDoc XML to YOLO detection format.")
    parser.parse_args()
    convert()


if __name__ == "__main__":
    main()
