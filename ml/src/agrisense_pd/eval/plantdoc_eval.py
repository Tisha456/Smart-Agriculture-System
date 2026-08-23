"""Phase E1 — real-world generalization test on PlantDoc (never used in
training). This is the number that tells you how the model will actually
behave on photos your app's users upload — expect it to be meaningfully
lower than the clean-dataset numbers from D1/D2/E0. See
plant-disease-implementation-plan.md section "E1": a clean-lab top-1 in
the high 90s and a PlantDoc end-to-end result in the 40-70% range is the
normal, documented outcome for PlantVillage-trained models, not a bug.

PlantDoc labels are resolved through the SAME taxonomy normalizer as
PlantVillage/Digipathos. Its class vocabulary only partially overlaps
ours — we evaluate only on the intersection and report exclusions
explicitly, since scoring a model on a species it never saw in training
is noise, not a generalization result.

Usage:
    python -m agrisense_pd.eval.plantdoc_eval
"""
from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

from ..config import PATHS
from ..data.taxonomy import resolve_label
from ..logging_utils import get_logger
from . import report
from .pipeline import TwoStagePipeline

log = get_logger("eval.plantdoc_eval")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def load_known_vocab() -> tuple[set[str], dict[str, set[str]]]:
    with open(PATHS.species_index_json(), "r", encoding="utf-8") as f:
        known_species = set(json.load(f))
    with open(PATHS.condition_index_json(), "r", encoding="utf-8") as f:
        raw = json.load(f)
    known_conditions = {sp: set(conds) for sp, conds in raw.items()}
    return known_species, known_conditions


def collect_plantdoc_ground_truth() -> list[dict]:
    """One row per image with an XML annotation: resolved (species,
    condition) via majority vote across its boxes, plus box_count for the
    single- vs multi-object split.
    """
    root = PATHS.raw_dataset("plantdoc")
    xml_files = list(root.rglob("*.xml"))
    rows = []
    excluded_labels: Counter = Counter()

    for xf in xml_files:
        try:
            tree = ET.parse(xf)
        except ET.ParseError:
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
            image_path = candidate if candidate.exists() else None
        if image_path is None:
            continue

        objs = tree.findall(".//object")
        box_count = len(objs)
        if box_count == 0:
            continue

        resolved_labels = []
        for obj in objs:
            name_el = obj.find("name")
            if name_el is None or not name_el.text:
                continue
            tax = resolve_label("plantdoc", name_el.text.strip())
            if tax["species"] and tax["condition"]:
                resolved_labels.append((tax["species"], tax["condition"]))
            else:
                excluded_labels[name_el.text.strip()] += 1

        if not resolved_labels:
            continue

        majority = Counter(resolved_labels).most_common(1)[0][0]
        rows.append({
            "image_path": str(image_path),
            "species": majority[0],
            "condition": majority[1],
            "box_count": box_count,
        })

    if excluded_labels:
        log.warning(
            "%d distinct PlantDoc object labels could not be resolved by the taxonomy "
            "normalizer and were excluded from ground truth: %s",
            len(excluded_labels), dict(excluded_labels),
        )
    return rows


def _evaluate_subset(rows: list[dict], pipeline: TwoStagePipeline) -> dict:
    if not rows:
        return {"n_images": 0}

    y_true_species, y_pred_species = [], []
    cond_true_given_species, cond_pred_given_species = [], []
    strict_correct = 0
    confidences_correct, confidences_incorrect = [], []

    for r in rows:
        pred = pipeline.predict(r["image_path"])
        y_true_species.append(r["species"])
        y_pred_species.append(pred.species)

        species_correct = pred.species == r["species"]
        if species_correct:
            cond_true_given_species.append(r["condition"])
            cond_pred_given_species.append(pred.condition or "")

        overall_correct = species_correct and pred.condition == r["condition"]
        if overall_correct:
            strict_correct += 1
            confidences_correct.append(pred.joint_confidence)
        else:
            confidences_incorrect.append(pred.joint_confidence)

    n = len(rows)
    species_top1 = sum(1 for t, p in zip(y_true_species, y_pred_species) if t == p) / n
    n_species_correct = len(cond_true_given_species)
    condition_acc = (
        sum(1 for t, p in zip(cond_true_given_species, cond_pred_given_species) if t == p) / n_species_correct
    ) if n_species_correct else float("nan")
    strict_e2e = strict_correct / n

    mean_conf_correct = sum(confidences_correct) / len(confidences_correct) if confidences_correct else float("nan")
    mean_conf_incorrect = sum(confidences_incorrect) / len(confidences_incorrect) if confidences_incorrect else float("nan")

    return {
        "n_images": n,
        "species_top1": species_top1,
        "condition_acc_given_correct_species": condition_acc,
        "strict_e2e": strict_e2e,
        "mean_confidence_correct": mean_conf_correct,
        "mean_confidence_incorrect": mean_conf_incorrect,
    }


def run() -> dict:
    known_species, known_conditions = load_known_vocab()
    all_rows = collect_plantdoc_ground_truth()

    in_vocab_rows = [
        r for r in all_rows
        if r["species"] in known_species and r["condition"] in known_conditions.get(r["species"], set())
    ]
    excluded_species = sorted({r["species"] for r in all_rows} - known_species)
    log.info(
        "PlantDoc: %d/%d ground-truth images fall within our trained species+condition "
        "vocabulary (excluded species not in training set: %s).",
        len(in_vocab_rows), len(all_rows), excluded_species,
    )

    single_object_rows = [r for r in in_vocab_rows if r["box_count"] <= 1]
    multi_object_rows = [r for r in in_vocab_rows if r["box_count"] > 1]

    pipeline = TwoStagePipeline()
    overall = _evaluate_subset(in_vocab_rows, pipeline)
    single_obj_metrics = _evaluate_subset(single_object_rows, pipeline)
    multi_obj_metrics = _evaluate_subset(multi_object_rows, pipeline)

    result = {
        "overall": overall,
        "single_object": single_obj_metrics,
        "multi_object": multi_obj_metrics,
        "n_total_plantdoc_images": len(all_rows),
        "n_excluded_out_of_vocab": len(all_rows) - len(in_vocab_rows),
        "excluded_species": excluded_species,
    }

    sections = [
        f"Total PlantDoc images with resolvable labels: {len(all_rows)}",
        f"In our training vocabulary: {len(in_vocab_rows)} "
        f"(excluded species not in training set: {excluded_species})",
        "## Overall\n" + report.metrics_table([overall], list(overall.keys())),
        "## Single-object images\n" + report.metrics_table([single_obj_metrics], list(single_obj_metrics.keys())),
        "## Multi-object images\n" + report.metrics_table([multi_obj_metrics], list(multi_obj_metrics.keys())),
        "## Interpreting this\n"
        "Expect overall accuracy here to be well below the clean-dataset validation/test "
        "numbers from D1/D2/E0 — that is the normal, expected outcome for a model trained on "
        "lab-style single-leaf photos, and it is the honest estimate of what your app's users "
        "will actually experience. If multi-object accuracy is materially below single-object "
        "accuracy (roughly >10 points), Phase E2 (leaf detector pre-step) is worth building; "
        "otherwise skip it.",
    ]
    report.write_markdown_report(PATHS.artifacts / "plantdoc_report.md", "Phase E1 — PlantDoc evaluation", sections)

    with open(PATHS.artifacts / "plantdoc_metrics.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    _write_comparison(overall)
    print(json.dumps(result, indent=2))
    return result


def _write_comparison(plantdoc_overall: dict) -> None:
    holdout_path = PATHS.artifacts / "eval_holdout_metrics.json"
    metric_sets = {}
    if holdout_path.exists():
        with open(holdout_path, "r", encoding="utf-8") as f:
            holdout = json.load(f)
        metric_sets["clean_test (E0)"] = {
            "species_top1": holdout.get("species_top1"),
            "condition_acc_given_correct_species": holdout.get("condition_acc_given_correct_species"),
            "strict_e2e": holdout.get("strict_e2e"),
        }
    metric_sets["plantdoc (E1)"] = {
        "species_top1": plantdoc_overall.get("species_top1"),
        "condition_acc_given_correct_species": plantdoc_overall.get("condition_acc_given_correct_species"),
        "strict_e2e": plantdoc_overall.get("strict_e2e"),
    }
    table = report.comparison_table(metric_sets)
    report.write_markdown_report(
        PATHS.artifacts / "comparison.md",
        "Clean test vs PlantDoc comparison",
        [table, "\nRun evaluate_holdout.py (E0) first if the clean_test column is missing."],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase E1: evaluate on PlantDoc.")
    parser.parse_args()
    run()


if __name__ == "__main__":
    main()
