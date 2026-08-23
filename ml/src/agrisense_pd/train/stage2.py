"""Phase D2 — train one disease classifier per species.

This is a resumable state machine, not a plain loop, because ~20-30
per-species trainings will not fit inside one free-tier Colab session
(see plant-disease-implementation-plan.md section 1.6). Re-running this
script's cell:
  - skips species already marked "done" in state/stage2_progress.json
  - resumes any species marked "in_progress" from its last.pt
  - retries "failed" species only if --retry-failed is passed
  - stops cleanly between species once --max-minutes elapses, leaving
    valid state for the next run

Usage:
    python -m agrisense_pd.train.stage2
    python -m agrisense_pd.train.stage2 --species tomato
    python -m agrisense_pd.train.stage2 --max-minutes 300
    python -m agrisense_pd.train.stage2 --retry-failed
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

from .. import drive_io
from ..config import CONFIGS_DIR, PATHS, set_seeds
from ..logging_utils import get_logger
from . import callbacks, resume_state

log = get_logger("train.stage2")


def _load_cfg() -> dict:
    with open(CONFIGS_DIR / "train_stage2.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _discover_species() -> list[str]:
    root = PATHS.stage2
    if not root.exists():
        raise FileNotFoundError(f"{root} not found — run materialize.py --stage 2 (Phase C1/C2) first.")
    return sorted(d.name for d in root.iterdir() if d.is_dir())


def _species_cfg(cfg: dict, species: str) -> dict:
    merged = dict(cfg)
    override = cfg.get("overrides", {}).get(species, {})
    merged.update(override)
    return merged


def train_one_species(species: str, cfg: dict, augment_profile: str = "default") -> dict:
    from ultralytics import YOLO

    sp_cfg = _species_cfg(cfg, species)
    set_seeds(sp_cfg.get("seed", 42))

    data_dir = PATHS.stage2 / species
    drive_dest = PATHS.stage2_models(species)
    local_last = PATHS.runs / "_resume" / f"stage2_{species}_last.pt"
    resumed = drive_io.pull_checkpoint(drive_dest / "last.pt", local_last)

    project = str(PATHS.runs / "stage2")
    run_name = f"{species}__aug" if augment_profile == "aggressive" else species

    if resumed is not None:
        log.info("[%s] Resuming from existing Drive checkpoint.", species)
        model = YOLO(str(resumed))
        callbacks.attach_checkpoint_sync(
            model, drive_dest, every_n_epochs=sp_cfg.get("checkpoint_sync_every_n_epochs", 2)
        )
        model.train(resume=True)
    else:
        log.info("[%s] Starting fresh training from %s.", species, sp_cfg["model"])
        model = YOLO(sp_cfg["model"])
        callbacks.attach_checkpoint_sync(
            model, drive_dest, every_n_epochs=sp_cfg.get("checkpoint_sync_every_n_epochs", 2)
        )
        model.train(
            data=str(data_dir),
            imgsz=sp_cfg["imgsz"],
            epochs=sp_cfg["epochs"],
            batch=sp_cfg["batch"],
            workers=sp_cfg["workers"],
            optimizer=sp_cfg["optimizer"],
            cos_lr=sp_cfg["cos_lr"],
            patience=sp_cfg["patience"],
            amp=sp_cfg["amp"],
            cache=sp_cfg["cache"],
            hsv_h=sp_cfg["hsv_h"], hsv_s=sp_cfg["hsv_s"], hsv_v=sp_cfg["hsv_v"],
            degrees=sp_cfg["degrees"], flipud=sp_cfg["flipud"], fliplr=sp_cfg["fliplr"],
            erasing=sp_cfg["erasing"],
            seed=sp_cfg.get("seed", 42),
            project=project,
            name=run_name,
            exist_ok=True,
        )

    run_dir = Path(model.trainer.save_dir)
    callbacks.sync_final(run_dir, drive_dest)

    val_metrics = model.val(data=str(data_dir), split="val")
    test_metrics = model.val(data=str(data_dir), split="test")
    val_top1 = float(getattr(val_metrics, "top1", float("nan")))
    test_top1 = float(getattr(test_metrics, "top1", float("nan")))

    class_names = [model.names[i] for i in sorted(model.names.keys())]
    with open(drive_dest / "classes.json", "w", encoding="utf-8") as f:
        json.dump(class_names, f, indent=2)

    return {
        "classes": len(class_names),
        "val_top1": val_top1,
        "test_top1": test_top1,
        "run_dir": str(run_dir),
    }


def write_summary_report(state: dict) -> None:
    rows = []
    for species, info in state.items():
        if info.get("status") != "done":
            continue
        rows.append((
            species, info.get("classes", 0),
            info.get("val_top1", float("nan")), info.get("test_top1", float("nan")),
        ))
    rows.sort(key=lambda r: (r[3] if r[3] == r[3] else -1))  # NaN-safe worst-first sort

    lines = [
        "# Stage 2 (per-species disease) training report",
        "",
        "| species | #classes | val top1 | test top1 | flagged (<0.85 test top1) |",
        "|---|---|---|---|---|",
    ]
    for species, n_classes, val_t1, test_t1 in rows:
        flagged = "YES" if test_t1 < 0.85 else ""
        lines.append(f"| {species} | {n_classes} | {val_t1:.4f} | {test_t1:.4f} | {flagged} |")

    failed = [sp for sp, info in state.items() if info.get("status") == "failed"]
    if failed:
        lines.append("")
        lines.append(f"## Failed species: {failed}")

    out_path = PATHS.artifacts / "stage2_report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", out_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase D2: train per-species disease classifiers.")
    parser.add_argument("--species", default=None, help="Train only this one species.")
    parser.add_argument("--max-minutes", type=float, default=None,
                         help="Stop cleanly between species once this many minutes elapse.")
    parser.add_argument("--retry-failed", action="store_true",
                         help="Also retry species previously marked 'failed'.")
    parser.add_argument("--augment-profile", choices=["default", "aggressive"], default="default",
                         help="Phase F: use the aggressive augmentation profile (writes to a "
                              "separate <species>__aug run, does not overwrite the baseline).")
    args = parser.parse_args()

    cfg = _load_cfg()
    all_species = _discover_species()
    targets = [args.species] if args.species else all_species

    state = resume_state.load()
    start_time = time.monotonic()

    for species in targets:
        status = resume_state.get_status(state, species)
        if status == "done":
            log.info("[%s] already done, skipping.", species)
            continue
        if status == "failed" and not args.retry_failed:
            log.info("[%s] previously failed, skipping (pass --retry-failed to retry).", species)
            continue

        if args.max_minutes is not None:
            elapsed_min = (time.monotonic() - start_time) / 60
            if elapsed_min >= args.max_minutes:
                log.info(
                    "Reached --max-minutes=%.1f budget, stopping cleanly. "
                    "Re-run this cell to continue with the remaining species.",
                    args.max_minutes,
                )
                break

        resume_state.mark_in_progress(state, species)
        resume_state.save(state)
        log.info("=== Training Stage 2 model for species: %s ===", species)
        try:
            result = train_one_species(species, cfg, augment_profile=args.augment_profile)
            resume_state.mark_done(
                state, species,
                classes=result["classes"], val_top1=result["val_top1"],
                test_top1=result["test_top1"], run_dir=result["run_dir"],
            )
        except Exception as e:  # noqa: BLE001 - one species failing must not abort the loop
            log.error("[%s] training failed: %s", species, e)
            resume_state.mark_failed(state, species, error=str(e))
        resume_state.save(state)

    write_summary_report(state)

    done = [sp for sp, i in state.items() if i.get("status") == "done"]
    pending = [sp for sp in all_species if resume_state.get_status(state, sp) not in ("done",)]
    print(f"\nDone: {len(done)}/{len(all_species)} species.")
    if pending:
        print(f"Remaining: {pending}")


if __name__ == "__main__":
    main()
