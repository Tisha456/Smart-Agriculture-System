"""Phase D1 — train the Stage 1 species classifier.

Resumable: if Drive/models/stage1/last.pt exists, it is pulled local and
training resumes from it. Re-running this script's cell after a Colab
disconnect continues training rather than restarting from scratch.

Usage:
    python -m agrisense_pd.train.stage1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .. import drive_io
from ..config import CONFIGS_DIR, PATHS, set_seeds
from ..logging_utils import get_logger
from . import callbacks

log = get_logger("train.stage1")


def _load_cfg() -> dict:
    with open(CONFIGS_DIR / "train_stage1.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _class_names_from_index(model) -> list[str]:
    return [model.names[i] for i in sorted(model.names.keys())]


def train(cfg: dict) -> tuple["object", Path]:
    from ultralytics import YOLO

    set_seeds(cfg.get("seed", 42))

    drive_dest = PATHS.stage1_models()
    local_last = PATHS.runs / "_resume" / "stage1_last.pt"
    resumed = drive_io.pull_checkpoint(drive_dest / "last.pt", local_last)

    project = str(PATHS.runs / cfg["project_name"])
    name = cfg["run_name"]

    if resumed is not None:
        log.info("Found existing checkpoint on Drive — resuming Stage 1 training.")
        model = YOLO(str(resumed))
        callbacks.attach_checkpoint_sync(
            model, drive_dest, every_n_epochs=cfg.get("checkpoint_sync_every_n_epochs", 2)
        )
        results = model.train(resume=True)
    else:
        log.info("No existing checkpoint — starting Stage 1 training from %s.", cfg["model"])
        model = YOLO(cfg["model"])
        callbacks.attach_checkpoint_sync(
            model, drive_dest, every_n_epochs=cfg.get("checkpoint_sync_every_n_epochs", 2)
        )
        results = model.train(
            data=str(PATHS.stage1),
            imgsz=cfg["imgsz"],
            epochs=cfg["epochs"],
            batch=cfg["batch"],
            workers=cfg["workers"],
            optimizer=cfg["optimizer"],
            cos_lr=cfg["cos_lr"],
            patience=cfg["patience"],
            amp=cfg["amp"],
            cache=cfg["cache"],
            hsv_h=cfg["hsv_h"], hsv_s=cfg["hsv_s"], hsv_v=cfg["hsv_v"],
            degrees=cfg["degrees"], flipud=cfg["flipud"], fliplr=cfg["fliplr"],
            erasing=cfg["erasing"],
            seed=cfg.get("seed", 42),
            project=project,
            name=name,
            exist_ok=True,
        )

    run_dir = Path(model.trainer.save_dir)
    callbacks.sync_final(run_dir, drive_dest)
    return model, run_dir


def evaluate_and_report(model, run_dir: Path) -> dict:
    metrics_out = {}
    for split_name in ("val", "test"):
        try:
            metrics = model.val(data=str(PATHS.stage1), split=split_name)
        except Exception as e:  # noqa: BLE001
            log.warning("Validation on split=%s failed: %s", split_name, e)
            continue
        top1 = float(getattr(metrics, "top1", float("nan")))
        top5 = float(getattr(metrics, "top5", float("nan")))
        metrics_out[split_name] = {"top1": top1, "top5": top5}
        log.info("Stage 1 [%s] top1=%.4f top5=%.4f", split_name, top1, top5)

    class_names = _class_names_from_index(model)
    lines = [
        "# Stage 1 (species) training report",
        "",
        f"Base model: `{model.ckpt_path if hasattr(model, 'ckpt_path') else 'n/a'}`",
        f"Run directory: `{run_dir}`",
        f"Classes ({len(class_names)}): {class_names}",
        "",
        "## Validation metrics",
        "",
        "| split | top1 | top5 |",
        "|---|---|---|",
    ]
    for split_name, m in metrics_out.items():
        lines.append(f"| {split_name} | {m['top1']:.4f} | {m['top5']:.4f} |")

    cm_src = run_dir / "confusion_matrix.png"
    if cm_src.exists():
        lines.append("")
        lines.append(f"Confusion matrix saved at: `{cm_src}`")

    out_path = PATHS.artifacts / "stage1_report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", out_path)

    metrics_json_path = PATHS.artifacts / "stage1_metrics.json"
    with open(metrics_json_path, "w", encoding="utf-8") as f:
        json.dump({"classes": class_names, "metrics": metrics_out, "run_dir": str(run_dir)}, f, indent=2)

    return metrics_out


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase D1: train Stage 1 species classifier.")
    parser.parse_args()
    cfg = _load_cfg()
    model, run_dir = train(cfg)
    metrics = evaluate_and_report(model, run_dir)

    test_top1 = metrics.get("test", {}).get("top1")
    if test_top1 is not None:
        flag = "OK" if test_top1 >= 0.95 else "BELOW TARGET (expected >= 0.95 on clean lab images)"
        print(f"\nStage 1 test top-1: {test_top1:.4f} [{flag}]")


if __name__ == "__main__":
    main()
