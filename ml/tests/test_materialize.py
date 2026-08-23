"""Unit tests for agrisense_pd.data.materialize (Phase C1/C2).

Verifies the symlinked (or copied, on filesystems without symlink
support) folder trees exactly match the manifest's per-split, per-class
counts, and that materialization is idempotent.

Run with: python -m pytest ml/tests/test_materialize.py -v
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agrisense_pd.config as config_mod  # noqa: E402


def _write_master_csv(paths, rows: list[dict]) -> None:
    fieldnames = [
        "image_id", "src_dataset", "src_relpath", "src_label", "species", "condition",
        "width", "height", "sha256", "phash", "dup_group", "split", "status", "reject_reason",
    ]
    path = paths.master_csv()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _make_dummy_image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not a real image, just needs to exist for linking")


def _row(image_id, species, condition, split, dup_group=None):
    return {
        "image_id": image_id, "src_dataset": "plantvillage",
        "src_relpath": f"{species}___{condition}/{image_id}.jpg",
        "src_label": f"{species}___{condition}", "species": species, "condition": condition,
        "width": "256", "height": "256", "sha256": image_id * 4, "phash": "f" * 16,
        "dup_group": dup_group or f"g_{image_id}", "split": split, "status": "ok", "reject_reason": "",
    }


def _setup(tmp_path, monkeypatch):
    from agrisense_pd.data import materialize

    drive_root = tmp_path / "drive"
    local_root = tmp_path / "local"
    paths = config_mod.Paths(drive_root=drive_root, local_root=local_root)
    monkeypatch.setattr(materialize, "PATHS", paths)

    rows = [
        _row("aaaa1111", "tomato", "healthy", "train"),
        _row("aaaa2222", "tomato", "healthy", "val"),
        _row("aaaa3333", "tomato", "late_blight", "test"),
        _row("aaaa4444", "potato", "healthy", "train"),
        # single-condition species: potato only ever appears with "healthy" here
    ]
    for r in rows:
        img_path = paths.raw_dataset(r["src_dataset"]) / r["src_relpath"]
        _make_dummy_image(img_path)

    _write_master_csv(paths, rows)
    return materialize, paths, rows


def test_stage1_tree_matches_manifest_counts(tmp_path, monkeypatch):
    materialize, paths, rows = _setup(tmp_path, monkeypatch)
    ok_rows = materialize._read_master_rows()
    materialize.materialize_stage1(ok_rows)

    assert (paths.stage1 / "train" / "tomato").exists()
    assert (paths.stage1 / "val" / "tomato").exists()
    assert (paths.stage1 / "test" / "tomato").exists()
    assert (paths.stage1 / "train" / "potato").exists()

    train_tomato_files = list((paths.stage1 / "train" / "tomato").iterdir())
    assert len(train_tomato_files) == 1


def test_stage2_skips_single_condition_species(tmp_path, monkeypatch):
    materialize, paths, rows = _setup(tmp_path, monkeypatch)
    ok_rows = materialize._read_master_rows()
    materialize.materialize_stage2(ok_rows)

    # tomato has 2 conditions -> gets a stage2 tree
    assert (paths.stage2 / "tomato").exists()
    assert (paths.stage2 / "tomato" / "train" / "healthy").exists()
    assert (paths.stage2 / "tomato" / "test" / "late_blight").exists()

    # potato has only "healthy" -> no stage2 tree at all (spec section 1.5)
    assert not (paths.stage2 / "potato").exists()


def test_materialize_is_idempotent(tmp_path, monkeypatch):
    materialize, paths, rows = _setup(tmp_path, monkeypatch)
    ok_rows = materialize._read_master_rows()
    materialize.materialize_stage1(ok_rows)
    first_run_files = sorted(p.name for p in (paths.stage1 / "train" / "tomato").iterdir())

    materialize.materialize_stage1(ok_rows)  # re-run without --force
    second_run_files = sorted(p.name for p in (paths.stage1 / "train" / "tomato").iterdir())

    assert first_run_files == second_run_files
