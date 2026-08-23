"""Phase C0 — split the master manifest ONCE, shared by both stages
(see plant-disease-implementation-plan.md sections 1.3 and 1.4).

Why a single split column: splitting stage 1 and stage 2 independently
(as roadmap C1/C2 originally suggested) can put an image in stage-1 test
and stage-2 train, which would let Phase E's end-to-end number reflect
memorized data instead of genuine generalization.

Why dup_group-aware: an exact-hash dedup does not catch near-duplicate
frames of the same leaf. If those straddle train/test, validation
accuracy overstates real generalization. Every dup_group is therefore
assigned to exactly one split as a whole.

Usage:
    python -m agrisense_pd.data.split
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
from collections import Counter, defaultdict

from ..config import PATHS, SEED
from ..logging_utils import get_logger

log = get_logger("split")

TARGET_RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}
MIN_IMAGES_FOR_GUARANTEE = 10
RATIO_TOLERANCE = 0.02


def _seed_for_stratum(stratum_key: str, base_seed: int) -> int:
    digest = hashlib.sha256(stratum_key.encode("utf-8")).hexdigest()[:8]
    return base_seed + int(digest, 16)


def _majority_stratum(rows: list[dict]) -> tuple[str, str]:
    counts = Counter((r["species"], r["condition"]) for r in rows)
    return counts.most_common(1)[0][0]


def assign_splits(rows: list[dict], seed: int = SEED) -> dict[str, str]:
    """rows: ok rows from master.csv (each a dict with species, condition,
    dup_group). Returns dup_group -> split assignment.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r["dup_group"]].append(r)

    stratum_of_group: dict[str, tuple[str, str]] = {}
    for gid, group_rows in groups.items():
        stratum_of_group[gid] = _majority_stratum(group_rows)

    groups_by_stratum: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for gid, group_rows in groups.items():
        groups_by_stratum[stratum_of_group[gid]].append((gid, len(group_rows)))

    assignment: dict[str, str] = {}
    for stratum_key in sorted(groups_by_stratum.keys()):
        group_list = groups_by_stratum[stratum_key]
        total = sum(size for _, size in group_list)
        targets = {k: v * total for k, v in TARGET_RATIOS.items()}
        current = {"train": 0, "val": 0, "test": 0}

        rng = random.Random(_seed_for_stratum(f"{stratum_key[0]}|{stratum_key[1]}", seed))
        shuffled = list(group_list)
        rng.shuffle(shuffled)

        group_size = dict(group_list)
        for gid, size in shuffled:
            deficits = {s: targets[s] - current[s] for s in ("train", "val", "test")}
            chosen = max(deficits, key=deficits.get)
            assignment[gid] = chosen
            current[chosen] += size

        if total >= MIN_IMAGES_FOR_GUARANTEE:
            for split_name in ("val", "test"):
                if current[split_name] == 0:
                    candidates = [gid for gid, _ in shuffled if assignment[gid] == "train"]
                    if candidates:
                        smallest = min(candidates, key=lambda g: group_size[g])
                        assignment[smallest] = split_name
                        current["train"] -= group_size[smallest]
                        current[split_name] += group_size[smallest]
                    else:
                        log.warning(
                            "Stratum %s has %d images but only one dup_group — "
                            "cannot guarantee a %s image without violating the "
                            "dup_group-single-split constraint.",
                            stratum_key, total, split_name,
                        )

    return assignment


def run(seed: int = SEED) -> None:
    master_path = PATHS.master_csv()
    if not master_path.exists():
        raise FileNotFoundError(f"{master_path} not found — run build_manifest.py (Phase B3) first.")

    with open(master_path, "r", newline="", encoding="utf-8") as f:
        fieldnames = list(csv.DictReader(f).fieldnames or [])
    with open(master_path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    ok_rows = [r for r in rows if r["status"] == "ok"]
    assignment = assign_splits(ok_rows, seed=seed)

    for r in rows:
        if r["status"] == "ok":
            r["split"] = assignment.get(r["dup_group"], "")

    with open(master_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote split assignments back to %s", master_path)

    _write_report(rows)


def _write_report(rows: list[dict]) -> None:
    ok_rows = [r for r in rows if r["status"] == "ok" and r["split"]]
    per_stratum: dict[tuple[str, str], Counter] = defaultdict(Counter)
    overall = Counter()
    for r in ok_rows:
        per_stratum[(r["species"], r["condition"])][r["split"]] += 1
        overall[r["split"]] += 1

    lines = ["# Split report (Phase C0)", ""]
    total = sum(overall.values())
    lines.append(f"Total images split: {total}")
    for split_name in ("train", "val", "test"):
        cnt = overall[split_name]
        pct = cnt / total if total else 0
        lines.append(f"- {split_name}: {cnt} ({pct:.1%})")

    lines.append("")
    lines.append("## Per (species, condition) split counts")
    lines.append("")
    lines.append("| species | condition | train | val | test | total |")
    lines.append("|---|---|---|---|---|---|")
    for (sp, cond), counter in sorted(per_stratum.items()):
        t, v, te = counter["train"], counter["val"], counter["test"]
        lines.append(f"| {sp} | {cond} | {t} | {v} | {te} | {t+v+te} |")

    out_path = PATHS.artifacts / "split_report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", out_path)

    print(f"\nTotal images split: {total}")
    for split_name in ("train", "val", "test"):
        cnt = overall[split_name]
        pct = cnt / total if total else 0
        print(f"  {split_name}: {cnt} ({pct:.1%})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase C0: split manifest into train/val/test.")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()
    run(seed=args.seed)


if __name__ == "__main__":
    main()
