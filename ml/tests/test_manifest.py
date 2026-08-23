"""Unit tests for agrisense_pd.data.build_manifest (Phase B3).

Run with: python -m pytest ml/tests/test_manifest.py -v
"""
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agrisense_pd.config as config_mod  # noqa: E402


def test_master_fields_schema_matches_spec():
    from agrisense_pd.data.build_manifest import MASTER_FIELDS

    expected = {
        "image_id", "src_dataset", "src_relpath", "src_label", "species", "condition",
        "width", "height", "sha256", "phash", "dup_group", "split", "status", "reject_reason",
    }
    assert set(MASTER_FIELDS) == expected


def test_build_manifest_end_to_end(tmp_path, monkeypatch):
    from agrisense_pd.data import build_manifest

    drive_root = tmp_path / "drive"
    local_root = tmp_path / "local"
    paths = config_mod.Paths(drive_root=drive_root, local_root=local_root)
    monkeypatch.setattr(build_manifest, "PATHS", paths)

    raw_pv = local_root / "data" / "raw" / "plantvillage"
    raw_pv.mkdir(parents=True)
    fingerprints_path = drive_root / "manifests" / "fingerprints.csv"
    fingerprints_path.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        {
            "src_dataset": "plantvillage",
            "src_label": "Tomato___healthy",
            "path": str(raw_pv / "Tomato___healthy" / "img1.jpg"),
            "species": "tomato",
            "condition": "healthy",
            "width": "256",
            "height": "256",
            "sha256": "a" * 64,
            "phash": "f" * 16,
            "dup_group": "g0",
        },
        {
            "src_dataset": "plantvillage",
            "src_label": "Tomato___late_blight",
            "path": str(raw_pv / "Tomato___late_blight" / "img2.jpg"),
            "species": "tomato",
            "condition": "late_blight",
            "width": "256",
            "height": "256",
            "sha256": "b" * 64,
            "phash": "e" * 16,
            "dup_group": "g1",
        },
    ]
    with open(fingerprints_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    build_manifest.build()

    master_path = paths.master_csv()
    assert master_path.exists()
    with open(master_path, "r", newline="", encoding="utf-8") as f:
        out_rows = list(csv.DictReader(f))
    assert len(out_rows) == 2
    assert {r["image_id"] for r in out_rows} == {"a" * 16, "b" * 16}
    assert all(r["status"] == "ok" for r in out_rows)
    assert all(r["split"] == "" for r in out_rows)  # split.py fills this in later

    assert paths.species_index_json().exists()
    assert paths.condition_index_json().exists()
