"""Phase G — write exported/registry.json: the contract between training
and serving. serving/pipeline_runtime.py reads ONLY this file to know
which ONNX files to load, what preprocessing to apply, and what class
each output index maps to — it never re-derives any of this, so a
mismatch between training and serving normalization becomes impossible
by construction (see plant-disease-implementation-plan.md section "G").

Usage:
    python -m agrisense_pd.export.registry
"""
from __future__ import annotations

import argparse
import datetime
import json

from ..config import PATHS
from ..logging_utils import get_logger

log = get_logger("export.registry")

REGISTRY_VERSION = "1.0.0"
INPUT_SIZE = 224
# Ultralytics classification models normalize to [0, 1] with no additional
# per-channel mean/std subtraction by default (unlike ImageNet-pretrained
# torchvision models) — keep this in sync with train_stage1.yaml /
# train_stage2.yaml if that ever changes.
INPUT_NORMALIZE = "0-1"
INPUT_MEAN = [0.0, 0.0, 0.0]
INPUT_STD = [1.0, 1.0, 1.0]

DEFAULT_MIN_SPECIES_CONFIDENCE = 0.5
DEFAULT_MIN_CONDITION_CONFIDENCE = 0.5


def _model_classes(onnx_path) -> list[str]:
    from ultralytics import YOLO

    model = YOLO(str(onnx_path))
    return [model.names[i] for i in sorted(model.names.keys())]


def _load_json_if_exists(path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build() -> dict:
    with open(PATHS.condition_index_json(), "r", encoding="utf-8") as f:
        condition_index: dict[str, list[str]] = json.load(f)

    stage1_onnx = PATHS.exported / "stage1" / "species.onnx"
    if not stage1_onnx.exists():
        raise FileNotFoundError(f"{stage1_onnx} not found — run to_onnx.py (Phase G) first.")
    stage1_entry = {
        "path": "stage1/species.onnx",
        "classes": _model_classes(stage1_onnx),
    }

    stage2_entries: dict[str, dict] = {}
    stage2_dir = PATHS.exported / "stage2"
    for species, conditions in sorted(condition_index.items()):
        if len(conditions) < 2:
            stage2_entries[species] = {"type": "constant", "condition": conditions[0] if conditions else "healthy"}
            continue
        onnx_path = stage2_dir / f"{species}.onnx"
        if onnx_path.exists():
            stage2_entries[species] = {
                "path": f"stage2/{species}.onnx",
                "classes": _model_classes(onnx_path),
            }
        else:
            log.warning("Species '%s' has %d conditions but no exported Stage 2 model — marking unavailable.",
                        species, len(conditions))
            stage2_entries[species] = {"type": "unavailable", "reason": "no_exported_model"}

    detector_metrics = _load_json_if_exists(PATHS.artifacts / "phase_e2_detector_metrics.json")
    detector_onnx = PATHS.exported / "detector" / "leaf_detector.onnx"
    detector_entry = {
        "enabled": bool(detector_metrics.get("detection_improves_accuracy", False)) and detector_onnx.exists(),
        "path": "detector/leaf_detector.onnx" if detector_onnx.exists() else None,
    }

    holdout_metrics = _load_json_if_exists(PATHS.artifacts / "eval_holdout_metrics.json")
    plantdoc_metrics = _load_json_if_exists(PATHS.artifacts / "plantdoc_metrics.json")
    metrics_entry = {
        "clean_test_e2e": holdout_metrics.get("strict_e2e"),
        "plantdoc_e2e": plantdoc_metrics.get("overall", {}).get("strict_e2e"),
    }

    registry = {
        "version": REGISTRY_VERSION,
        "created_at": datetime.datetime.utcnow().isoformat() + "Z",
        "input": {
            "size": INPUT_SIZE,
            "layout": "NCHW",
            "normalize": INPUT_NORMALIZE,
            "mean": INPUT_MEAN,
            "std": INPUT_STD,
        },
        "stage1": stage1_entry,
        "stage2": stage2_entries,
        "detector": detector_entry,
        "metrics": metrics_entry,
        "thresholds": {
            "min_species_confidence": DEFAULT_MIN_SPECIES_CONFIDENCE,
            "min_condition_confidence": DEFAULT_MIN_CONDITION_CONFIDENCE,
        },
    }
    return registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase G: write exported/registry.json.")
    parser.parse_args()

    registry = build()
    out_path = PATHS.exported / "registry.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2)
    log.info("Wrote %s", out_path)

    print(json.dumps(registry, indent=2))
    print(
        "\nNOTE: thresholds.min_species_confidence / min_condition_confidence are placeholder "
        "defaults (0.5). Tune them after reading artifacts/plantdoc_metrics.json's "
        "mean_confidence_correct vs mean_confidence_incorrect (Phase E1's calibration numbers), "
        "then re-run this script."
    )


if __name__ == "__main__":
    main()
