"""Phase B2 — clean & fingerprint all training datasets (config.TRAINING_DATASETS).

PlantDoc is untouched as training data — it is test-only (see roadmap) —
but IS read here to build a phash lookup used to reject any training image
that's a near-duplicate of a PlantDoc test image. This matters specifically
because PlantWild is crowdsourced from Google/Ecosia/Baidu image search,
the same route PlantDoc's images came from — without this check, a
duplicate landing in both sides would silently inflate Phase E1's
real-world accuracy number (see plant-disease-implementation-plan.md
section 1.4 and configs/sources.yaml's plantwild entry).

For every training image: decodability, size, sha256, phash. Rejects
unreadable / too-small / bad-aspect / exact-duplicate / unmapped-label /
plantdoc-overlap images (each with a logged reason). Near-duplicates
WITHIN training data are NOT rejected — they get a shared dup_group id so
Phase C0 can keep whole clusters on one side of the split.

Checkpoints partial hashing progress every N images to
manifests/fingerprints.partial.csv so a Colab disconnect mid-pass doesn't
cost the whole run.

Usage:
    python -m agrisense_pd.data.clean
    python -m agrisense_pd.data.clean --workers 8
"""
from __future__ import annotations

import argparse
import csv
import random
import shutil
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from tqdm import tqdm

from ..config import PATHS, SEED, TRAINING_DATASETS
from ..imaging import PHASH_HAMMING_THRESHOLD, hamming_distance_hex, inspect_image
from ..logging_utils import get_logger
from .taxonomy import resolve_label, load_overrides

log = get_logger("clean")

CHECKPOINT_EVERY = 5000
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
MAX_SAMPLES_PER_REASON = 50


def _collect_candidate_images() -> list[tuple[str, str, Path]]:
    """(src_dataset, src_label, path) for every image under each training
    dataset's raw folder (config.TRAINING_DATASETS)."""
    out = []
    for dataset in TRAINING_DATASETS:
        root = PATHS.raw_dataset(dataset)
        if not root.exists():
            continue
        class_dirs = [
            d for d in root.rglob("*")
            if d.is_dir() and any(f.is_file() for f in d.iterdir())
        ]
        for d in class_dirs:
            label = d.name
            for f in d.iterdir():
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                    out.append((dataset, label, f))
    return out


def fingerprint_plantdoc_phashes() -> list[str]:
    """Perceptual hashes of every PlantDoc image (read-only — PlantDoc is
    never written to fingerprints.csv or trained on). Returns an empty
    list if PlantDoc hasn't been downloaded yet rather than erroring, so
    clean.py still works if run before Phase A2's plantdoc fetch.
    """
    root = PATHS.raw_dataset("plantdoc")
    if not root.exists():
        return []
    image_files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    phashes = []
    for p in tqdm(image_files, desc="fingerprinting plantdoc (for overlap check)"):
        info = inspect_image(p)
        if info.ok and info.phash:
            phashes.append(info.phash)
    return phashes


def find_plantdoc_overlaps(rows: list[dict], plantdoc_phashes: list[str]) -> set[str]:
    """Given training rows (each with a 'path' and 'phash') and a list of
    PlantDoc phashes, return the set of training-row paths whose phash is
    within PHASH_HAMMING_THRESHOLD of any PlantDoc image. Bucketed by
    phash prefix so this stays fast even with ~100k training rows against
    ~5k PlantDoc images (see clean.py module docstring for why this check
    exists).
    """
    if not plantdoc_phashes:
        return set()

    buckets: dict[str, list[str]] = defaultdict(list)
    for ph in plantdoc_phashes:
        buckets[ph[:4]].append(ph)

    overlap_paths: set[str] = set()
    for r in rows:
        phash = r.get("phash")
        if not phash:
            continue
        for ph in buckets.get(phash[:4], ()):
            if hamming_distance_hex(phash, ph) <= PHASH_HAMMING_THRESHOLD:
                overlap_paths.add(r["path"])
                break
    return overlap_paths


def _worker(args: tuple[str, str, str]) -> dict:
    dataset, label, path_str = args
    path = Path(path_str)
    info = inspect_image(path)
    return {
        "src_dataset": dataset,
        "src_label": label,
        "path": path_str,
        "ok": info.ok,
        "reason": info.reason,
        "width": info.width,
        "height": info.height,
        "sha256": info.sha256,
        "phash": info.phash,
    }


def _load_partial_checkpoint() -> tuple[list[dict], set[str]]:
    path = PATHS.fingerprints_partial_csv()
    if not path.exists():
        return [], set()
    rows = []
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    done_paths = {r["path"] for r in rows}
    log.info("Resuming from partial checkpoint: %d images already processed.", len(done_paths))
    return rows, done_paths


def _save_partial_checkpoint(rows: list[dict]) -> None:
    path = PATHS.fingerprints_partial_csv()
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["src_dataset", "src_label", "path", "ok", "reason", "width", "height", "sha256", "phash"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _cluster_duplicates(rows: list[dict]) -> dict[str, str]:
    """Assign dup_group ids. Exact sha256 matches collapse to one kept
    image (PlantVillage wins ties). Remaining images get bucketed by phash
    prefix, then clustered by Hamming distance within each bucket — this
    avoids an O(n^2) full comparison over the whole corpus.
    Returns path -> dup_group_id, and mutates nothing else.
    """
    ok_rows = [r for r in rows if r["ok"] and r["sha256"]]

    # Exact duplicate resolution via sha256.
    by_sha: dict[str, list[dict]] = defaultdict(list)
    for r in ok_rows:
        by_sha[r["sha256"]].append(r)

    kept_rows = []
    exact_dup_paths: set[str] = set()
    for sha, group in by_sha.items():
        if len(group) == 1:
            kept_rows.append(group[0])
            continue
        group.sort(key=lambda r: (r["src_dataset"] != "plantvillage", r["path"]))
        kept_rows.append(group[0])
        for dup in group[1:]:
            exact_dup_paths.add(dup["path"])

    # Bucket remaining (deduplicated-by-hash) images by first 4 hex chars
    # of phash to limit near-duplicate comparison cost.
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in kept_rows:
        if not r["phash"]:
            continue
        buckets[r["phash"][:4]].append(r)

    dup_group_of: dict[str, str] = {}
    group_counter = 0
    for bucket_rows in buckets.values():
        assigned = [False] * len(bucket_rows)
        for i in range(len(bucket_rows)):
            if assigned[i]:
                continue
            group_id = f"g{group_counter}"
            group_counter += 1
            dup_group_of[bucket_rows[i]["path"]] = group_id
            assigned[i] = True
            for j in range(i + 1, len(bucket_rows)):
                if assigned[j]:
                    continue
                if hamming_distance_hex(bucket_rows[i]["phash"], bucket_rows[j]["phash"]) <= PHASH_HAMMING_THRESHOLD:
                    dup_group_of[bucket_rows[j]["path"]] = group_id
                    assigned[j] = True

    # Images with no phash (imagehash missing) each get their own singleton group.
    for r in kept_rows:
        if r["path"] not in dup_group_of:
            dup_group_of[r["path"]] = f"g{group_counter}"
            group_counter += 1

    return dup_group_of, exact_dup_paths


def run(workers: int = 8, force: bool = False) -> None:
    random.seed(SEED)
    candidates = _collect_candidate_images()
    log.info("Found %d candidate images across plantvillage + digipathos.", len(candidates))

    if force:
        PATHS.fingerprints_partial_csv().unlink(missing_ok=True)

    prior_rows, done_paths = _load_partial_checkpoint()
    todo = [c for c in candidates if str(c[2]) not in done_paths]
    log.info("%d images already fingerprinted, %d remaining.", len(prior_rows), len(todo))

    all_rows = list(prior_rows)
    if todo:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futures = {
                ex.submit(_worker, (d, lbl, str(p))): (d, lbl, p)
                for d, lbl, p in todo
            }
            since_checkpoint = 0
            for fut in tqdm(as_completed(futures), total=len(futures), desc="fingerprinting"):
                row = fut.result()
                all_rows.append(row)
                since_checkpoint += 1
                if since_checkpoint >= CHECKPOINT_EVERY:
                    _save_partial_checkpoint(all_rows)
                    since_checkpoint = 0
        _save_partial_checkpoint(all_rows)

    # Resolve taxonomy for each unique (dataset, label) so we can flag "unmapped".
    overrides = load_overrides()
    label_cache: dict[tuple[str, str], dict] = {}

    def resolve_cached(dataset: str, label: str) -> dict:
        key = (dataset, label)
        if key not in label_cache:
            label_cache[key] = overrides.get(key) or resolve_label(dataset, label)
        return label_cache[key]

    rejected: list[dict] = []
    ok_rows = []
    for r in all_rows:
        if not r["ok"] if isinstance(r["ok"], bool) else r["ok"] != "True":
            reason = r["reason"] or "unreadable"
            rejected.append({**r, "reason": reason})
            continue
        tax = resolve_cached(r["src_dataset"], r["src_label"])
        if tax["confidence"] == "review":
            rejected.append({**r, "reason": "unmapped"})
            continue
        ok_rows.append(r)

    dup_group_of, exact_dup_paths = _cluster_duplicates(all_rows)
    for path in exact_dup_paths:
        rejected.append({"path": path, "reason": "exact_duplicate"})

    final_ok = [r for r in ok_rows if r["path"] not in exact_dup_paths]

    # Cross-dataset contamination guard: reject any training image that is
    # a near-duplicate of a PlantDoc TEST image (see module docstring —
    # matters most for PlantWild, which is crowdsourced the same way
    # PlantDoc is). PlantDoc itself is never modified or trained on.
    plantdoc_phashes = fingerprint_plantdoc_phashes()
    if plantdoc_phashes:
        log.info(
            "Checking %d clean training images against %d PlantDoc phashes for overlap...",
            len(final_ok), len(plantdoc_phashes),
        )
        overlap_paths = find_plantdoc_overlaps(final_ok, plantdoc_phashes)
        for path in overlap_paths:
            rejected.append({"path": path, "reason": "plantdoc_overlap"})
        if overlap_paths:
            log.warning(
                "%d training images are near-duplicates of PlantDoc test images — rejected "
                "to keep Phase E1's real-world accuracy number honest.",
                len(overlap_paths),
            )
        final_ok = [r for r in final_ok if r["path"] not in overlap_paths]
    else:
        log.info(
            "PlantDoc not downloaded yet — skipping train/test overlap check "
            "(safe: re-run clean.py after Phase A2 fetches it)."
        )

    # Write rejected.csv (full log) + sample up to 50 per reason into
    # data/clean/rejected/<reason>/ for eyeballing.
    rejected_path = PATHS.rejected_csv()
    with open(rejected_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["path", "reason"])
        writer.writeheader()
        for r in rejected:
            writer.writerow({"path": r["path"], "reason": r["reason"]})
    log.info("Wrote %s (%d rejected)", rejected_path, len(rejected))

    by_reason: dict[str, list[str]] = defaultdict(list)
    for r in rejected:
        by_reason[r["reason"]].append(r["path"])

    rejected_root = PATHS.clean / "rejected"
    for reason, paths in by_reason.items():
        dest_dir = rejected_root / reason
        dest_dir.mkdir(parents=True, exist_ok=True)
        for p in paths[:MAX_SAMPLES_PER_REASON]:
            src = Path(p)
            if src.exists():
                try:
                    shutil.copy2(src, dest_dir / src.name)
                except OSError:
                    pass

    # Attach dup_group + resolved taxonomy and write final fingerprints.csv
    # (this is the direct input to build_manifest.py in B3).
    out_path = PATHS.fingerprints_csv()
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        fieldnames = ["src_dataset", "src_label", "path", "species", "condition",
                      "width", "height", "sha256", "phash", "dup_group"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in final_ok:
            tax = resolve_cached(r["src_dataset"], r["src_label"])
            writer.writerow({
                "src_dataset": r["src_dataset"],
                "src_label": r["src_label"],
                "path": r["path"],
                "species": tax["species"],
                "condition": tax["condition"],
                "width": r["width"],
                "height": r["height"],
                "sha256": r["sha256"],
                "phash": r["phash"],
                "dup_group": dup_group_of.get(r["path"], ""),
            })
    log.info("Wrote %s (%d clean images)", out_path, len(final_ok))

    total = len(all_rows)
    reject_rate = len(rejected) / total if total else 0.0
    print(f"\nTotal scanned: {total}")
    print(f"Rejected: {len(rejected)} ({reject_rate:.1%})")
    for reason, paths in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"  {reason}: {len(paths)}")
    print(f"Clean, deduplicated, mapped images: {len(final_ok)}")
    if reject_rate > 0.05:
        print(
            "\nWARNING: rejection rate is above 5%. Read manifests/rejected.csv and "
            "data/clean/rejected/<reason>/ before proceeding — this usually means a "
            "systematic issue (wrong extension filter, an unmapped label family) "
            "rather than genuinely bad source data."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase B2: clean & fingerprint images.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--force", action="store_true", help="Ignore partial checkpoint, start fresh.")
    args = parser.parse_args()
    run(workers=args.workers, force=args.force)


if __name__ == "__main__":
    main()
