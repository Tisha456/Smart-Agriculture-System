"""Unit tests for agrisense_pd.config's dataset roster (TRAINING_DATASETS /
EVAL_DATASETS / DATASETS).

Run with: python -m pytest ml/tests/test_config.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agrisense_pd import config  # noqa: E402


def test_eval_datasets_excluded_from_training():
    assert set(config.EVAL_DATASETS).isdisjoint(set(config.TRAINING_DATASETS)), (
        "An eval-only dataset (e.g. plantdoc) must never also appear in "
        "training_datasets — that would let test data leak into training."
    )


def test_datasets_is_union_of_training_and_eval():
    assert set(config.DATASETS) == set(config.TRAINING_DATASETS) | set(config.EVAL_DATASETS)


def test_plantdoc_is_eval_only():
    assert "plantdoc" in config.EVAL_DATASETS
    assert "plantdoc" not in config.TRAINING_DATASETS


def test_digipathos_not_in_active_roster():
    # Confirmed-dead source (Embrapa server refuses connections) — must
    # not be silently fetched by default. Its sources.yaml entry is kept
    # for the record but excluded from paths.yaml's lists.
    assert "digipathos" not in config.DATASETS


def test_get_paths_reads_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("AGRISENSE_PD_DRIVE_ROOT", str(tmp_path / "drive"))
    monkeypatch.setenv("AGRISENSE_PD_LOCAL_ROOT", str(tmp_path / "local"))
    paths = config.get_paths()
    assert paths.drive_root == tmp_path / "drive"
    assert paths.local_root == tmp_path / "local"
