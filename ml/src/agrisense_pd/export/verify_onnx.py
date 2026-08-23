"""Phase G — verify every exported ONNX model matches its PyTorch source.

For each model, runs >=20 test-split images through both backends via
ultralytics' own AutoBackend abstraction (loading the same YOLO class
with .pt vs .onnx weights applies IDENTICAL preprocessing regardless of
backend, so any difference found is a real export problem, not a
preprocessing mismatch). Requires argmax to match on 100% of images and
the max class-probability delta to stay under 1e-3 — any mismatch fails
loudly, since a preprocessing/normalization mismatch between training and
serving is the single most common cause of "works in Colab, garbage in
production" (see plant-disease-implementation-plan.md section "G").

Usage:
    python -m agrisense_pd.export.verify_onnx
"""
from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from ..config import PATHS, SEED
from ..logging_utils import get_logger

log = get_logger("export.verify_onnx")

MAX_DELTA = 1e-3
MIN_SAMPLES = 20


def _sample_test_images(species: str | None = None, n: int = MIN_SAMPLES) -> list[Path]:
    """species=None -> Stage 1 species-level test images; species=<name>
    -> that species' Stage 2 condition-level test images."""
    with open(PATHS.master_csv(), "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows = [r for r in rows if r["status"] == "ok" and r["split"] == "test"]
    if species is not None:
        rows = [r for r in rows if r["species"] == species]

    rng = random.Random(SEED)
    rng.shuffle(rows)
    rows = rows[:n]
    return [PATHS.raw_dataset(r["src_dataset"]) / r["src_relpath"] for r in rows]


def verify_pair(pt_weights: Path, onnx_weights: Path, images: list[Path], imgsz: int) -> dict:
    from ultralytics import YOLO

    if len(images) < MIN_SAMPLES:
        log.warning("Only %d test images available (wanted >= %d) for %s", len(images), MIN_SAMPLES, pt_weights)

    pt_model = YOLO(str(pt_weights))
    onnx_model = YOLO(str(onnx_weights))

    n_checked = 0
    n_argmax_matches = 0
    max_delta_seen = 0.0

    for img_path in images:
        if not img_path.exists():
            continue
        r_pt = pt_model.predict(str(img_path), imgsz=imgsz, verbose=False)[0]
        r_onnx = onnx_model.predict(str(img_path), imgsz=imgsz, verbose=False)[0]

        n_checked += 1
        if int(r_pt.probs.top1) == int(r_onnx.probs.top1):
            n_argmax_matches += 1

        pt_vec = r_pt.probs.data.cpu().numpy()
        onnx_vec = r_onnx.probs.data.cpu().numpy()
        delta = float(abs(pt_vec - onnx_vec).max())
        max_delta_seen = max(max_delta_seen, delta)

    argmax_match_rate = n_argmax_matches / n_checked if n_checked else 0.0
    passed = n_checked >= 1 and argmax_match_rate == 1.0 and max_delta_seen < MAX_DELTA

    return {
        "n_checked": n_checked,
        "argmax_match_rate": argmax_match_rate,
        "max_delta": max_delta_seen,
        "passed": passed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase G: verify exported ONNX models match PyTorch.")
    parser.parse_args()

    all_passed = True
    results = {}

    stage1_pt = PATHS.stage1_models() / "best.pt"
    stage1_onnx = PATHS.exported / "stage1" / "species.onnx"
    if stage1_pt.exists() and stage1_onnx.exists():
        images = _sample_test_images(species=None)
        result = verify_pair(stage1_pt, stage1_onnx, images, imgsz=224)
        results["stage1"] = result
        all_passed &= result["passed"]
        print(f"[stage1] checked={result['n_checked']} argmax_match={result['argmax_match_rate']:.1%} "
              f"max_delta={result['max_delta']:.2e} PASSED={result['passed']}")
    else:
        log.warning("Stage 1 pt/onnx pair not found — skipping.")

    stage2_root = PATHS.stage2_models()
    exported_stage2 = PATHS.exported / "stage2"
    if stage2_root.exists() and exported_stage2.exists():
        for species_dir in sorted(stage2_root.iterdir()):
            if not species_dir.is_dir():
                continue
            pt_path = species_dir / "best.pt"
            onnx_path = exported_stage2 / f"{species_dir.name}.onnx"
            if not (pt_path.exists() and onnx_path.exists()):
                continue
            images = _sample_test_images(species=species_dir.name)
            result = verify_pair(pt_path, onnx_path, images, imgsz=224)
            results[f"stage2/{species_dir.name}"] = result
            all_passed &= result["passed"]
            print(f"[stage2/{species_dir.name}] checked={result['n_checked']} "
                  f"argmax_match={result['argmax_match_rate']:.1%} "
                  f"max_delta={result['max_delta']:.2e} PASSED={result['passed']}")

    if not results:
        print("No exported models found to verify. Run to_onnx.py (Phase G) first.")
        sys.exit(1)

    print(f"\nAll models passed: {all_passed}")
    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
