"""Phase A3 — inspect each raw dataset's structure independently, before any
merging logic exists. Produces one markdown report per dataset plus a
combined summary, so you can read them and understand each dataset's
label convention before B1 writes the taxonomy mapping.

Usage:
    python -m agrisense_pd.data.inspect_structure
    python -m agrisense_pd.data.inspect_structure --only plantvillage
"""
from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Optional

from PIL import Image

from ..config import DATASETS, EVAL_DATASETS, PATHS
from ..logging_utils import get_logger

log = get_logger("inspect_structure")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _percentile(sorted_vals: list[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, int(round(pct / 100 * (len(sorted_vals) - 1))))
    return sorted_vals[idx]


def _sample_resolutions(image_paths: list[Path], sample_size: int = 500) -> dict:
    step = max(1, len(image_paths) // sample_size)
    sampled = image_paths[::step][:sample_size]
    widths, heights = [], []
    for p in sampled:
        try:
            with Image.open(p) as img:
                w, h = img.size
            widths.append(w)
            heights.append(h)
        except Exception:
            continue
    widths.sort()
    heights.sort()
    return {
        "n_sampled": len(widths),
        "width_p1": _percentile(widths, 1),
        "width_p50": _percentile(widths, 50),
        "width_p99": _percentile(widths, 99),
        "height_p1": _percentile(heights, 1),
        "height_p50": _percentile(heights, 50),
        "height_p99": _percentile(heights, 99),
    }


def _detect_convention(label_names: list[str]) -> str:
    if any("___" in n for n in label_names):
        return "Species___Condition (double underscore)"
    if any(n.isdigit() for n in label_names):
        return "numeric IDs"
    accented = any(any(ord(c) > 127 for c in n) for n in label_names)
    if accented:
        return "free-form, non-ASCII (likely Portuguese)"
    return "free-form folder names"


def inspect_folder_dataset(name: str) -> dict:
    """Inspect a dataset laid out as folder-per-class (PlantVillage,
    Digipathos). Returns a dict of findings and writes a markdown report.
    """
    root = PATHS.raw_dataset(name)
    if not root.exists() or not any(root.iterdir()):
        log.warning("%s: raw folder empty or missing at %s", name, root)
        return {"name": name, "error": "empty_or_missing"}

    # Class folders may be nested one level deep (e.g. an extra top zip folder).
    all_dirs = [p for p in root.rglob("*") if p.is_dir()]
    leaf_class_dirs = [
        d for d in all_dirs
        if any(f.suffix.lower() in IMAGE_EXTS for f in d.iterdir() if f.is_file())
    ]
    if not leaf_class_dirs:
        # Images directly at top level with no class folders at all.
        leaf_class_dirs = [root] if any(
            f.suffix.lower() in IMAGE_EXTS for f in root.iterdir() if f.is_file()
        ) else []

    label_names = [d.name for d in leaf_class_dirs]
    per_class_counts = {}
    ext_counter: Counter = Counter()
    all_images: list[Path] = []
    for d in leaf_class_dirs:
        imgs = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
        per_class_counts[d.name] = len(imgs)
        all_images.extend(imgs)
        for f in imgs:
            ext_counter[f.suffix.lower()] += 1

    depths = {len(p.relative_to(root).parts) for p in leaf_class_dirs} or {0}
    convention = _detect_convention(label_names)
    res_stats = _sample_resolutions(all_images)

    findings = {
        "name": name,
        "n_classes": len(leaf_class_dirs),
        "n_images": len(all_images),
        "depth_levels": sorted(depths),
        "convention": convention,
        "per_class_counts": per_class_counts,
        "ext_histogram": dict(ext_counter),
        "resolution": res_stats,
        "sample_labels": label_names[:15],
    }
    _write_folder_report(findings)
    return findings


def _write_folder_report(f: dict) -> None:
    out_path = PATHS.artifacts / f"inspect_{f['name']}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    counts = f["per_class_counts"]
    sorted_classes = sorted(counts.items(), key=lambda kv: -kv[1])

    lines = [
        f"# Inspection report — {f['name']}",
        "",
        f"- Classes found: **{f['n_classes']}**",
        f"- Total images: **{f['n_images']}**",
        f"- Directory depth levels (relative to raw root): {f['depth_levels']}",
        f"- Detected label convention: **{f['convention']}**",
        f"- Sample label names: {f['sample_labels']}",
        "",
        "## Extension histogram",
        "",
        "| extension | count |",
        "|---|---|",
    ]
    for ext, cnt in sorted(f["ext_histogram"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {ext} | {cnt} |")

    lines += [
        "",
        "## Resolution (sampled)",
        "",
        f"- width: p1={f['resolution'].get('width_p1', 0):.0f} "
        f"p50={f['resolution'].get('width_p50', 0):.0f} "
        f"p99={f['resolution'].get('width_p99', 0):.0f}",
        f"- height: p1={f['resolution'].get('height_p1', 0):.0f} "
        f"p50={f['resolution'].get('height_p50', 0):.0f} "
        f"p99={f['resolution'].get('height_p99', 0):.0f}",
        "",
        "## Per-class image counts",
        "",
        "| class | count |",
        "|---|---|",
    ]
    for cls, cnt in sorted_classes:
        lines.append(f"| {cls} | {cnt} |")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", out_path)


def inspect_detection_dataset(name: str) -> dict:
    """For eval datasets (config.EVAL_DATASETS — currently just PlantDoc):
    images + Pascal VOC XML. Reports object class names and
    box-count-per-image distribution in addition to the standard
    structure summary.
    """
    root = PATHS.raw_dataset(name)
    if not root.exists() or not any(root.iterdir()):
        log.warning("%s: raw folder empty or missing at %s", name, root)
        return {"name": name, "error": "empty_or_missing"}

    xml_files = list(root.rglob("*.xml"))
    image_files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS]

    box_counts_per_image = []
    object_classes: Counter = Counter()
    parse_errors = 0
    for xf in xml_files:
        try:
            tree = ET.parse(xf)
            objs = tree.findall(".//object")
            box_counts_per_image.append(len(objs))
            for obj in objs:
                name_el = obj.find("name")
                if name_el is not None and name_el.text:
                    object_classes[name_el.text.strip()] += 1
        except ET.ParseError:
            parse_errors += 1

    box_counts_per_image.sort()
    ext_counter = Counter(p.suffix.lower() for p in image_files)
    res_stats = _sample_resolutions(image_files)

    findings = {
        "name": name,
        "n_images": len(image_files),
        "n_xml": len(xml_files),
        "xml_parse_errors": parse_errors,
        "object_classes": dict(object_classes),
        "n_object_classes": len(object_classes),
        "box_count_p1": _percentile(box_counts_per_image, 1),
        "box_count_p50": _percentile(box_counts_per_image, 50),
        "box_count_p99": _percentile(box_counts_per_image, 99),
        "ext_histogram": dict(ext_counter),
        "resolution": res_stats,
    }
    _write_detection_report(findings)
    return findings


def _write_detection_report(f: dict) -> None:
    out_path = PATHS.artifacts / f"inspect_{f['name']}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Inspection report — {f['name']} (object detection variant)",
        "",
        f"- Images: **{f['n_images']}**",
        f"- XML annotation files: **{f['n_xml']}** (parse errors: {f['xml_parse_errors']})",
        f"- Distinct object class names: **{f['n_object_classes']}**",
        f"- Boxes per image: p1={f['box_count_p1']:.0f} p50={f['box_count_p50']:.0f} "
        f"p99={f['box_count_p99']:.0f}",
        "",
        "## Object class names (with box counts)",
        "",
        "| class | box count |",
        "|---|---|",
    ]
    for cls, cnt in sorted(f["object_classes"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {cls} | {cnt} |")
    lines += [
        "",
        "## Resolution (sampled)",
        "",
        f"- width: p1={f['resolution'].get('width_p1', 0):.0f} "
        f"p50={f['resolution'].get('width_p50', 0):.0f} "
        f"p99={f['resolution'].get('width_p99', 0):.0f}",
        f"- height: p1={f['resolution'].get('height_p1', 0):.0f} "
        f"p50={f['resolution'].get('height_p50', 0):.0f} "
        f"p99={f['resolution'].get('height_p99', 0):.0f}",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", out_path)


def write_combined_summary(results: list[dict]) -> None:
    lines = ["# Combined dataset inspection summary", ""]
    for r in results:
        if r.get("error"):
            lines.append(f"## {r['name']}: {r['error']}")
            continue
        if r["name"] in EVAL_DATASETS:
            lines.append(
                f"## {r['name']}: {r['n_images']} images, "
                f"{r['n_object_classes']} object classes (detection dataset, test-only)"
            )
        else:
            lines.append(
                f"## {r['name']}: {r['n_classes']} classes, {r['n_images']} images, "
                f"convention: {r['convention']}"
            )
    out_path = PATHS.artifacts / "inspect_summary.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", out_path)
    print("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase A3: inspect raw dataset structure.")
    parser.add_argument("--only", choices=DATASETS, default=None)
    args = parser.parse_args()

    targets = [args.only] if args.only else DATASETS
    results = []
    for name in targets:
        if name in EVAL_DATASETS:
            results.append(inspect_detection_dataset(name))
        else:
            results.append(inspect_folder_dataset(name))

    write_combined_summary(results)


if __name__ == "__main__":
    main()
