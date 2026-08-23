"""Phase C1/C2 — materialize the ultralytics-ready folder trees from
master.csv, without ever copying the dataset (see
plant-disease-implementation-plan.md section 1.2). Entries are symlinks
into data/raw/; falls back to hardlinks, then plain copies, if the
filesystem doesn't support symlinks (rare on Colab's local ext4 disk, but
possible in odd environments — the script reports which mode it used).

--stage 1: data/stage1_species/{train,val,test}/<species>/
--stage 2: data/stage2_disease/<species>/{train,val,test}/<condition>/
           (only species with >= 2 distinct conditions get a stage-2 tree —
           see spec section 1.5, single-condition species have no Stage 2 model)

Usage:
    python -m agrisense_pd.data.materialize --stage 1
    python -m agrisense_pd.data.materialize --stage 2
    python -m agrisense_pd.data.materialize --stage 1 --stage 2 --force
"""
from __future__ import annotations

import argparse
import csv
import shutil
from collections import defaultdict
from pathlib import Path

from ..config import PATHS
from ..logging_utils import get_logger

log = get_logger("materialize")

_LINK_MODE: str | None = None  # decided once per run, cached


def _read_master_rows() -> list[dict]:
    path = PATHS.master_csv()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run split.py (Phase C0) first.")
    with open(path, "r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    ok_rows = [r for r in rows if r["status"] == "ok" and r["split"]]
    if not ok_rows:
        raise ValueError("No rows with status=ok and a split assigned — run split.py first.")
    return ok_rows


def _src_path(row: dict) -> Path:
    return PATHS.raw_dataset(row["src_dataset"]) / row["src_relpath"]


def _link_one(src: Path, dest: Path) -> None:
    global _LINK_MODE
    if dest.exists() or dest.is_symlink():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)

    modes_to_try = [_LINK_MODE] if _LINK_MODE else ["symlink", "hardlink", "copy"]
    for mode in modes_to_try:
        try:
            if mode == "symlink":
                dest.symlink_to(src)
            elif mode == "hardlink":
                import os
                os.link(src, dest)
            else:
                shutil.copy2(src, dest)
            _LINK_MODE = mode
            return
        except OSError:
            continue
    raise OSError(f"Could not link or copy {src} -> {dest} by any method (symlink/hardlink/copy).")


def materialize_stage1(rows: list[dict], force: bool = False) -> None:
    root = PATHS.stage1
    if force and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    counts: dict[tuple[str, str], int] = defaultdict(int)
    for r in rows:
        split, species = r["split"], r["species"]
        if not species:
            continue
        src = _src_path(r)
        dest = root / split / species / f"{r['image_id']}{src.suffix.lower()}"
        _link_one(src, dest)
        counts[(split, species)] += 1

    log.info("Stage 1 tree materialized at %s using link mode=%s", root, _LINK_MODE)
    _print_and_verify_counts("stage1", counts, rows, key_fn=lambda r: (r["split"], r["species"]))


def _species_condition_index(rows: list[dict]) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["species"] and r["condition"]:
            idx[r["species"]].add(r["condition"])
    return idx


def materialize_stage2(rows: list[dict], force: bool = False) -> None:
    root = PATHS.stage2
    if force and root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    species_conditions = _species_condition_index(rows)
    multi_condition_species = {sp for sp, conds in species_conditions.items() if len(conds) >= 2}
    log.info(
        "%d species have >=2 conditions and get a Stage 2 tree; %d species are single-condition "
        "and are skipped (constant prediction at serve time).",
        len(multi_condition_species),
        len(species_conditions) - len(multi_condition_species),
    )

    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in rows:
        species = r["species"]
        if species not in multi_condition_species:
            continue
        split, condition = r["split"], r["condition"]
        src = _src_path(r)
        dest = root / species / split / condition / f"{r['image_id']}{src.suffix.lower()}"
        _link_one(src, dest)
        counts[(species, split, condition)] += 1

    log.info("Stage 2 trees materialized at %s using link mode=%s", root, _LINK_MODE)
    per_species: dict[str, dict[tuple[str, str], int]] = defaultdict(dict)
    for (sp, split, cond), cnt in counts.items():
        per_species[sp][(split, cond)] = cnt

    for sp in sorted(multi_condition_species):
        sp_rows = [r for r in rows if r["species"] == sp]
        _print_and_verify_counts(
            f"stage2/{sp}", per_species.get(sp, {}), sp_rows,
            key_fn=lambda r: (r["split"], r["condition"]),
        )


def _print_and_verify_counts(label: str, materialized_counts: dict, rows: list[dict], key_fn) -> None:
    expected: dict = defaultdict(int)
    for r in rows:
        expected[key_fn(r)] += 1

    mismatches = []
    for key, exp_count in expected.items():
        got = materialized_counts.get(key, 0)
        if got != exp_count:
            mismatches.append((key, exp_count, got))

    total = sum(expected.values())
    print(f"[{label}] total images: {total}, groups: {len(expected)}")
    if mismatches:
        print(f"[{label}] WARNING: {len(mismatches)} count mismatches vs manifest:")
        for key, exp, got in mismatches[:20]:
            print(f"    {key}: expected {exp}, materialized {got}")
    else:
        print(f"[{label}] counts match manifest exactly.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase C1/C2: materialize training folder trees.")
    parser.add_argument("--stage", action="append", type=int, choices=[1, 2], required=True,
                         help="Repeatable: --stage 1 --stage 2")
    parser.add_argument("--force", action="store_true", help="Rebuild trees from scratch.")
    args = parser.parse_args()

    rows = _read_master_rows()
    stages = set(args.stage)
    if 1 in stages:
        materialize_stage1(rows, force=args.force)
    if 2 in stages:
        materialize_stage2(rows, force=args.force)


if __name__ == "__main__":
    main()
