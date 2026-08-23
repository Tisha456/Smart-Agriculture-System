"""Unit tests for agrisense_pd.data.split (Phase C0).

Run with: python -m pytest ml/tests/test_split.py -v
"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agrisense_pd.data import split as split_mod  # noqa: E402


def _make_rows(n_groups: int, per_group: int, species: str, condition: str) -> list[dict]:
    rows = []
    for g in range(n_groups):
        for _ in range(per_group):
            rows.append({
                "species": species,
                "condition": condition,
                "dup_group": f"{species}_{condition}_g{g}",
            })
    return rows


def test_no_dup_group_spans_two_splits():
    rows = _make_rows(50, 4, "tomato", "late_blight") + _make_rows(30, 3, "potato", "healthy")
    assignment = split_mod.assign_splits(rows, seed=42)

    group_splits = defaultdict(set)
    for r in rows:
        gid = r["dup_group"]
        group_splits[gid].add(assignment[gid])

    for gid, splits in group_splits.items():
        assert len(splits) == 1, f"dup_group {gid} spans multiple splits: {splits}"


def test_ratios_within_tolerance():
    rows = _make_rows(200, 5, "tomato", "late_blight")
    assignment = split_mod.assign_splits(rows, seed=42)

    counts = defaultdict(int)
    for r in rows:
        counts[assignment[r["dup_group"]]] += 1
    total = sum(counts.values())

    for split_name, target in split_mod.TARGET_RATIOS.items():
        actual = counts[split_name] / total
        assert abs(actual - target) <= split_mod.RATIO_TOLERANCE, (
            f"{split_name}: target {target}, actual {actual}"
        )


def test_deterministic_across_runs():
    rows = _make_rows(80, 4, "tomato", "late_blight") + _make_rows(60, 6, "corn", "rust")
    a1 = split_mod.assign_splits(rows, seed=42)
    a2 = split_mod.assign_splits(rows, seed=42)
    assert a1 == a2


def test_small_but_sufficient_stratum_gets_val_and_test_images():
    rows = _make_rows(15, 2, "raspberry", "healthy")  # 30 images, 15 singleton-ish groups
    assignment = split_mod.assign_splits(rows, seed=42)
    counts = defaultdict(int)
    for r in rows:
        counts[assignment[r["dup_group"]]] += 1
    assert counts["val"] > 0
    assert counts["test"] > 0
