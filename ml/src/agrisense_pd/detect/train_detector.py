"""Phase E2 (conditional) — train the leaf-detector pre-step and measure
whether it actually improves end-to-end accuracy on PlantDoc's
multi-object images. Only keep it if it helps (see
plant-disease-implementation-plan.md section "E2") — it doubles latency
and adds a failure mode, so "no improvement" means leave it off, and
that decision gets recorded either way.

Usage:
    python -m agrisense_pd.detect.plantdoc_to_yolo   # build the dataset first
    python -m agrisense_pd.detect.train_detector
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import drive_io
from ..config import PATHS, set_seeds
from ..eval import report
from ..eval.pipeline import TwoStagePipeline
from ..eval.plantdoc_eval import collect_plantdoc_ground_truth, load_known_vocab
from ..logging_utils import get_logger
from ..train import callbacks

log = get_logger("detect.train_detector")

DEFAULT_EPOCHS = 50
DEFAULT_IMGSZ = 640


def train(data_yaml: Path, epochs: int = DEFAULT_EPOCHS, imgsz: int = DEFAULT_IMGSZ) -> Path:
    from ultralytics import YOLO

    set_seeds()
    drive_dest = PATHS.drive_models / "detector"
    local_last = PATHS.runs / "_resume" / "detector_last.pt"
    resumed = drive_io.pull_checkpoint(drive_dest / "last.pt", local_last)

    project = str(PATHS.runs / "detector")
    if resumed is not None:
        log.info("Resuming detector training from existing Drive checkpoint.")
        model = YOLO(str(resumed))
        callbacks.attach_checkpoint_sync(model, drive_dest, every_n_epochs=5)
        model.train(resume=True)
    else:
        model = YOLO("yolo11n.pt")
        callbacks.attach_checkpoint_sync(model, drive_dest, every_n_epochs=5)
        model.train(
            data=str(data_yaml), imgsz=imgsz, epochs=epochs, project=project,
            name="leaf_detector", exist_ok=True,
        )

    run_dir = Path(model.trainer.save_dir)
    callbacks.sync_final(run_dir, drive_dest)
    return run_dir / "weights" / "best.pt"


def _predict_with_detection(detector, pipeline: TwoStagePipeline, image_path: str, conf: float = 0.25):
    """Crop every detected leaf box, classify each crop, and return the
    highest-confidence crop's prediction (spec: 'report highest-confidence
    crop, plus all crops' — all-crops predictions are attached for
    inspection but the highest-confidence one is what's scored).
    """
    from PIL import Image

    results = detector.predict(image_path, conf=conf, verbose=False)
    r = results[0]
    boxes = r.boxes

    with Image.open(image_path) as img:
        img = img.convert("RGB")
        crops = []
        if boxes is None or len(boxes) == 0:
            crops.append(img)  # no detection — fall back to the whole image
        else:
            for box in boxes.xyxy.tolist():
                x1, y1, x2, y2 = [int(round(v)) for v in box]
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(img.width, x2), min(img.height, y2)
                if x2 > x1 and y2 > y1:
                    crops.append(img.crop((x1, y1, x2, y2)))

    predictions = [pipeline.predict(crop) for crop in crops]
    best = max(predictions, key=lambda p: p.joint_confidence)
    return best, predictions


def evaluate_with_and_without_detection(detector_weights: Path) -> dict:
    from ultralytics import YOLO

    known_species, known_conditions = load_known_vocab()
    all_rows = collect_plantdoc_ground_truth()
    in_vocab_rows = [
        r for r in all_rows
        if r["species"] in known_species and r["condition"] in known_conditions.get(r["species"], set())
    ]
    multi_object_rows = [r for r in in_vocab_rows if r["box_count"] > 1]
    log.info("Evaluating detection pre-step on %d multi-object PlantDoc images.", len(multi_object_rows))

    pipeline = TwoStagePipeline()
    detector = YOLO(str(detector_weights))

    def score(rows, use_detection: bool) -> dict:
        strict_correct = 0
        species_correct = 0
        for r in rows:
            if use_detection:
                pred, _ = _predict_with_detection(detector, pipeline, r["image_path"])
            else:
                pred = pipeline.predict(r["image_path"])
            if pred.species == r["species"]:
                species_correct += 1
                if pred.condition == r["condition"]:
                    strict_correct += 1
        n = len(rows) or 1
        return {"n_images": len(rows), "species_top1": species_correct / n, "strict_e2e": strict_correct / n}

    before = score(multi_object_rows, use_detection=False)
    after = score(multi_object_rows, use_detection=True)

    improved = after["strict_e2e"] > before["strict_e2e"]
    result = {"before_detection": before, "after_detection": after, "detection_improves_accuracy": improved}

    table = report.comparison_table({"before (no detector)": before, "after (with detector)": after})
    decision = (
        "Detection pre-step IMPROVES end-to-end accuracy on multi-object PlantDoc images — keep it enabled."
        if improved else
        "Detection pre-step does NOT improve end-to-end accuracy — keep it OFF. It only adds "
        "latency and a failure mode with no measured benefit."
    )
    report.write_markdown_report(
        PATHS.artifacts / "phase_e2_detector_report.md",
        "Phase E2 — leaf detector before/after comparison",
        [table, f"\n**Decision:** {decision}"],
    )
    with open(PATHS.artifacts / "phase_e2_detector_metrics.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))
    print(decision)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase E2: train leaf detector and compare before/after.")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--imgsz", type=int, default=DEFAULT_IMGSZ)
    parser.add_argument("--data-yaml", default=None,
                         help="Path to data.yaml from plantdoc_to_yolo.py (default: standard location).")
    args = parser.parse_args()

    data_yaml = Path(args.data_yaml) if args.data_yaml else (
        PATHS.local_root / "data" / "detector_yolo" / "data.yaml"
    )
    if not data_yaml.exists():
        raise FileNotFoundError(f"{data_yaml} not found — run plantdoc_to_yolo.py first.")

    weights = train(data_yaml, epochs=args.epochs, imgsz=args.imgsz)
    evaluate_with_and_without_detection(weights)


if __name__ == "__main__":
    main()
