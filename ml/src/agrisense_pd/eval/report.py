"""Shared markdown + confusion-matrix reporting helpers for Phase E
(evaluate_holdout.py / plantdoc_eval.py). Kept generic so both scripts —
and Phase F's before/after comparisons — write reports in one consistent
format.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Optional, Sequence

from ..logging_utils import get_logger

log = get_logger("eval.report")


def confusion_matrix(y_true: Sequence[str], y_pred: Sequence[str], labels: list[str]) -> list[list[int]]:
    idx = {lbl: i for i, lbl in enumerate(labels)}
    n = len(labels)
    matrix = [[0] * n for _ in range(n)]
    for t, p in zip(y_true, y_pred):
        if t in idx and p in idx:
            matrix[idx[t]][idx[p]] += 1
    return matrix


def save_confusion_matrix_png(matrix: list[list[int]], labels: list[str], out_path: Path,
                               title: str = "Confusion matrix") -> None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        log.warning("matplotlib/numpy not available — skipping confusion matrix PNG.")
        return

    arr = np.array(matrix, dtype=float)
    row_sums = arr.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1
    normalized = arr / row_sums

    fig_size = max(6, len(labels) * 0.4)
    fig, ax = plt.subplots(figsize=(fig_size, fig_size))
    im = ax.imshow(normalized, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)))
    ax.set_yticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=90, fontsize=6)
    ax.set_yticklabels(labels, fontsize=6)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    log.info("Saved confusion matrix to %s", out_path)


def most_confused_pairs(matrix: list[list[int]], labels: list[str], top_n: int = 10) -> list[tuple[str, str, int]]:
    pairs = []
    for i, true_label in enumerate(labels):
        for j, pred_label in enumerate(labels):
            if i != j and matrix[i][j] > 0:
                pairs.append((true_label, pred_label, matrix[i][j]))
    pairs.sort(key=lambda p: -p[2])
    return pairs[:top_n]


def per_class_accuracy(matrix: list[list[int]], labels: list[str]) -> dict[str, float]:
    out = {}
    for i, label in enumerate(labels):
        total = sum(matrix[i])
        out[label] = (matrix[i][i] / total) if total else float("nan")
    return out


def precision_recall_f1_macro(matrix: list[list[int]], labels: list[str]) -> dict[str, float]:
    n = len(labels)
    precisions, recalls, f1s = [], [], []
    for i in range(n):
        tp = matrix[i][i]
        fp = sum(matrix[r][i] for r in range(n)) - tp
        fn = sum(matrix[i]) - tp
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(f1)
    return {
        "macro_precision": sum(precisions) / n if n else 0.0,
        "macro_recall": sum(recalls) / n if n else 0.0,
        "macro_f1": sum(f1s) / n if n else 0.0,
    }


def write_markdown_report(out_path: Path, title: str, sections: list[str]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = f"# {title}\n\n" + "\n\n".join(sections)
    out_path.write_text(content, encoding="utf-8")
    log.info("Wrote %s", out_path)


def metrics_table(rows: list[dict], columns: list[str]) -> str:
    header = "| " + " | ".join(columns) + " |"
    sep = "|" + "|".join(["---"] * len(columns)) + "|"
    lines = [header, sep]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in columns) + " |")
    return "\n".join(lines)


def comparison_table(metric_sets: dict[str, dict[str, float]]) -> str:
    """metric_sets: {"clean_val": {"species_top1": .., "condition_acc": .., "e2e": ..}, ...}
    Produces one row per metric, one column per metric set — the
    clean-val / clean-test / plantdoc side-by-side table from Phase E1.
    """
    set_names = list(metric_sets.keys())
    metric_names = sorted({m for s in metric_sets.values() for m in s})

    header = "| metric | " + " | ".join(set_names) + " |"
    sep = "|" + "|".join(["---"] * (len(set_names) + 1)) + "|"
    lines = [header, sep]
    for metric in metric_names:
        row = [metric]
        for set_name in set_names:
            val = metric_sets[set_name].get(metric)
            row.append(f"{val:.4f}" if isinstance(val, float) else str(val))
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)
