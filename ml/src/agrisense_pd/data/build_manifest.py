"""Phase B3 — build the master manifest: the single source of truth for
every downstream step (see plant-disease-implementation-plan.md section 1.2).

Joins fingerprints.csv (from clean.py) into manifests/master.csv with a
stable image_id (sha256 prefix), and freezes the canonical class ordering
for both stages into species_index.json / condition_index.json — every
downstream step (training, export, the API) reads class order from there,
never from folder listing order.

Usage:
    python -m agrisense_pd.data.build_manifest
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict

from ..config import PATHS
from ..logging_utils import get_logger

log = get_logger("build_manifest")

LOW_DATA_THRESHOLD = 200
MASTER_FIELDS = [
    "image_id", "src_dataset", "src_relpath", "src_label", "species", "condition",
    "width", "height", "sha256", "phash", "dup_group", "split", "status", "reject_reason",
]


def _read_fingerprints() -> list[dict]:
    path = PATHS.fingerprints_csv()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run clean.py (Phase B2) first.")
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build() -> None:
    rows = _read_fingerprints()
    raw_root_by_dataset = {ds: str(PATHS.raw_dataset(ds)) for ds in ("plantvillage", "digipathos")}

    seen_ids: set[str] = set()
    out_rows = []
    for r in rows:
        image_id = r["sha256"][:16]
        if image_id in seen_ids:
            # Extremely unlikely sha256-prefix collision; keep first occurrence.
            continue
        seen_ids.add(image_id)

        root = raw_root_by_dataset.get(r["src_dataset"], "")
        src_relpath = r["path"]
        if root and src_relpath.startswith(root):
            src_relpath = src_relpath[len(root):].lstrip("/\\")

        out_rows.append({
            "image_id": image_id,
            "src_dataset": r["src_dataset"],
            "src_relpath": src_relpath,
            "src_label": r["src_label"],
            "species": r["species"],
            "condition": r["condition"],
            "width": r["width"],
            "height": r["height"],
            "sha256": r["sha256"],
            "phash": r["phash"],
            "dup_group": r["dup_group"],
            "split": "",       # filled in by split.py (Phase C0)
            "status": "ok",
            "reject_reason": "",
        })

    out_path = PATHS.master_csv()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MASTER_FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    log.info("Wrote %s (%d rows)", out_path, len(out_rows))

    _write_class_report(out_rows)
    _write_class_indices(out_rows)


def _write_class_indices(rows: list[dict]) -> None:
    species_index = sorted({r["species"] for r in rows if r["species"]})
    conditions_by_species: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r["species"] and r["condition"]:
            conditions_by_species[r["species"]].add(r["condition"])

    condition_index = {
        species: sorted(conds) for species, conds in conditions_by_species.items()
    }

    with open(PATHS.species_index_json(), "w", encoding="utf-8") as f:
        json.dump(species_index, f, indent=2)
    with open(PATHS.condition_index_json(), "w", encoding="utf-8") as f:
        json.dump(condition_index, f, indent=2)
    log.info(
        "Wrote species_index.json (%d species) and condition_index.json",
        len(species_index),
    )


def _write_class_report(rows: list[dict]) -> None:
    per_species: Counter = Counter()
    per_species_condition: Counter = Counter()
    per_source: Counter = Counter()
    conditions_by_species: dict[str, set[str]] = defaultdict(set)

    for r in rows:
        per_species[r["species"]] += 1
        per_species_condition[(r["species"], r["condition"])] += 1
        per_source[r["src_dataset"]] += 1
        conditions_by_species[r["species"]].add(r["condition"])

    low_data = [
        (sp, cond, cnt) for (sp, cond), cnt in per_species_condition.items()
        if cnt < LOW_DATA_THRESHOLD
    ]
    single_condition = [sp for sp, conds in conditions_by_species.items() if len(conds) < 2]

    lines = ["# Master manifest class report (Phase B3)", ""]
    lines.append(f"Total clean images: {len(rows)}")
    lines.append("")
    lines.append("## Images per source dataset")
    lines.append("")
    lines.append("| dataset | count |")
    lines.append("|---|---|")
    for ds, cnt in per_source.most_common():
        lines.append(f"| {ds} | {cnt} |")

    lines.append("")
    lines.append("## Images per species")
    lines.append("")
    lines.append("| species | count |")
    lines.append("|---|---|")
    for sp, cnt in per_species.most_common():
        lines.append(f"| {sp} | {cnt} |")

    lines.append("")
    lines.append("## Images per (species, condition)")
    lines.append("")
    lines.append("| species | condition | count |")
    lines.append("|---|---|---|")
    for (sp, cond), cnt in sorted(per_species_condition.items(), key=lambda kv: -kv[1]):
        lines.append(f"| {sp} | {cond} | {cnt} |")

    lines.append("")
    lines.append(f"## Low-data (species, condition) combos — under {LOW_DATA_THRESHOLD} images")
    lines.append("(These are Phase F augmentation candidates.)")
    lines.append("")
    lines.append("| species | condition | count |")
    lines.append("|---|---|---|")
    for sp, cond, cnt in sorted(low_data, key=lambda t: t[2]):
        lines.append(f"| {sp} | {cond} | {cnt} |")

    lines.append("")
    lines.append("## Species with a single condition (no Stage 2 model — see spec section 1.5)")
    lines.append("")
    for sp in sorted(single_condition):
        lines.append(f"- {sp}: only {conditions_by_species[sp]}")

    out_path = PATHS.artifacts / "class_report.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote %s", out_path)
    print(f"\nTotal clean images: {len(rows)}")
    print(f"Species: {len(per_species)}")
    print(f"(species, condition) combos: {len(per_species_condition)}")
    print(f"Low-data combos (<{LOW_DATA_THRESHOLD} imgs): {len(low_data)}")
    print(f"Single-condition species (no Stage 2 model): {single_condition}")


def main() -> None:
    build()


if __name__ == "__main__":
    main()
