"""Phase E0 — end-to-end evaluation on OUR OWN held-out test split.

Not in the original roadmap. This exists so that Phase E1's PlantDoc
number can be interpreted correctly: a drop from this baseline to
PlantDoc means "real-world photos are harder"; a mismatch between this
baseline and (species-acc x conditional-acc) would instead mean a
routing bug in eval/pipeline.py (see
plant-disease-implementation-plan.md section "E0").

Usage:
    python -m agrisense_pd.eval.evaluate_holdout
"""
from __future__ import annotations

import argparse
import csv
import json

from ..config import PATHS
from ..logging_utils import get_logger
from . import report
from .pipeline import TwoStagePipeline

log = get_logger("eval.evaluate_holdout")


def _load_test_rows() -> list[dict]:
    path = PATHS.master_csv()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run split.py (Phase C0) first.")
    with open(path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["status"] == "ok" and r["split"] == "test"]


def run(sample_limit: int | None = None) -> dict:
    rows = _load_test_rows()
    if sample_limit:
        rows = rows[:sample_limit]
    log.info("Evaluating on %d held-out test images.", len(rows))

    pipeline = TwoStagePipeline()

    y_true_species, y_pred_species = [], []
    cond_true_given_correct_species, cond_pred_given_correct_species = [], []
    strict_correct = 0
    n_no_stage2_model = 0

    for r in rows:
        image_path = PATHS.raw_dataset(r["src_dataset"]) / r["src_relpath"]
        pred = pipeline.predict(str(image_path))

        y_true_species.append(r["species"])
        y_pred_species.append(pred.species)

        species_correct = pred.species == r["species"]
        if species_correct:
            cond_true_given_correct_species.append(r["condition"])
            cond_pred_given_correct_species.append(pred.condition or "")

        if species_correct and pred.condition == r["condition"]:
            strict_correct += 1

        if pred.notes == "no_stage2_model_found":
            n_no_stage2_model += 1

    n = len(rows)
    species_labels = sorted(set(y_true_species) | set(y_pred_species))
    species_matrix = report.confusion_matrix(y_true_species, y_pred_species, species_labels)
    species_top1 = sum(1 for t, p in zip(y_true_species, y_pred_species) if t == p) / n if n else 0.0

    n_species_correct = len(cond_true_given_correct_species)
    condition_acc_given_species = (
        sum(1 for t, p in zip(cond_true_given_correct_species, cond_pred_given_correct_species) if t == p)
        / n_species_correct
    ) if n_species_correct else float("nan")

    strict_e2e = strict_correct / n if n else 0.0

    metrics = {
        "n_images": n,
        "species_top1": species_top1,
        "condition_acc_given_correct_species": condition_acc_given_species,
        "strict_e2e": strict_e2e,
        "n_no_stage2_model": n_no_stage2_model,
    }

    report.save_confusion_matrix_png(
        species_matrix, species_labels, PATHS.artifacts / "eval_holdout_species_confusion.png",
        title="Stage 1 species confusion (holdout test)",
    )
    confused_pairs = report.most_confused_pairs(species_matrix, species_labels)

    sections = [
        f"Images evaluated: {n}",
        f"Species top-1: {species_top1:.4f}",
        f"Condition accuracy (given correct species): {condition_acc_given_species:.4f}",
        f"Strict end-to-end (both correct): {strict_e2e:.4f}",
        f"Images with no Stage 2 model available: {n_no_stage2_model}",
        "## Sanity check\n"
        f"species_top1 x condition_acc_given_species = "
        f"{species_top1 * condition_acc_given_species:.4f} (compare to strict_e2e above — "
        "a large gap indicates a routing bug in eval/pipeline.py, not a model weakness).",
        "## Most confused species pairs\n\n" + report.metrics_table(
            [{"true": t, "pred": p, "count": c} for t, p, c in confused_pairs],
            ["true", "pred", "count"],
        ),
    ]
    report.write_markdown_report(
        PATHS.artifacts / "eval_holdout_report.md", "Phase E0 — held-out test evaluation", sections
    )

    with open(PATHS.artifacts / "eval_holdout_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    print(json.dumps(metrics, indent=2))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase E0: evaluate on our own held-out test split.")
    parser.add_argument("--sample-limit", type=int, default=None,
                         help="Evaluate on only the first N rows (for a quick smoke test).")
    args = parser.parse_args()
    run(sample_limit=args.sample_limit)


if __name__ == "__main__":
    main()
