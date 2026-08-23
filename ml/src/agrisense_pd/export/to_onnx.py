"""Phase G — export trained models to ONNX for serving.

Exports Stage 1, every Stage 2 species model found under
Drive/models/stage2/<species>/best.pt, and the leaf detector if Phase E2
built and kept one. Output mirrors the training model tree under
Drive/exported/.

If Phase F promoted an augmented retrain for a species (see
plant-disease-implementation-plan.md section F's promotion rule), copy
that model over models/stage2/<species>/best.pt BEFORE running this —
this script always exports from the canonical stage2/<species>/best.pt
path, never from a *__aug run directly, since promotion is a recorded
human decision, not something this script guesses.

Usage:
    python -m agrisense_pd.export.to_onnx
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ..config import PATHS
from ..logging_utils import get_logger

log = get_logger("export.to_onnx")

OPSET = 12
IMGSZ = 224


def _export_one(weights_path: Path, out_dir: Path, out_name: str, imgsz: int = IMGSZ) -> Path:
    from ultralytics import YOLO

    if not weights_path.exists():
        raise FileNotFoundError(f"Weights not found: {weights_path}")

    model = YOLO(str(weights_path))
    exported_path = model.export(format="onnx", opset=OPSET, dynamic=True, simplify=True, imgsz=imgsz)
    exported_path = Path(exported_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / out_name
    if exported_path.resolve() != dest.resolve():
        dest.write_bytes(exported_path.read_bytes())
    log.info("Exported %s -> %s", weights_path, dest)
    return dest


def export_stage1() -> Path:
    weights = PATHS.stage1_models() / "best.pt"
    out_dir = PATHS.exported / "stage1"
    return _export_one(weights, out_dir, "species.onnx")


def export_stage2_all() -> dict[str, Path]:
    root = PATHS.stage2_models()
    if not root.exists():
        log.warning("%s does not exist — no Stage 2 models to export.", root)
        return {}

    results = {}
    for species_dir in sorted(root.iterdir()):
        if not species_dir.is_dir():
            continue
        weights = species_dir / "best.pt"
        if not weights.exists():
            log.warning("Skipping %s — no best.pt found.", species_dir)
            continue
        out_dir = PATHS.exported / "stage2"
        results[species_dir.name] = _export_one(weights, out_dir, f"{species_dir.name}.onnx")
    return results


def export_detector_if_present() -> Path | None:
    weights = PATHS.drive_models / "detector" / "best.pt"
    if not weights.exists():
        log.info("No detector weights found at %s — skipping (E2 was not built/kept).", weights)
        return None
    out_dir = PATHS.exported / "detector"
    return _export_one(weights, out_dir, "leaf_detector.onnx", imgsz=640)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase G: export trained models to ONNX.")
    parser.parse_args()

    stage1_path = export_stage1()
    stage2_paths = export_stage2_all()
    detector_path = export_detector_if_present()

    print(f"Stage 1 exported: {stage1_path}")
    print(f"Stage 2 exported: {len(stage2_paths)} species -> {list(stage2_paths.keys())}")
    print(f"Detector exported: {detector_path}")


if __name__ == "__main__":
    main()
