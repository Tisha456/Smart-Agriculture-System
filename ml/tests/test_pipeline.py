"""Unit tests for agrisense_pd.eval.pipeline's routing logic (Phase E0/E1/H).

These test the routing decisions (single_condition inheritance, missing
Stage 2 model handling) WITHOUT loading a real ultralytics model — the
pipeline is constructed via object.__new__ and only the fields the
routing logic actually touches (condition_index, stage2_root, cache) are
set directly.

Run with: python -m pytest ml/tests/test_pipeline.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agrisense_pd.eval.pipeline import TwoStagePipeline  # noqa: E402


def _bare_pipeline(condition_index: dict, stage2_root: Path) -> TwoStagePipeline:
    p = object.__new__(TwoStagePipeline)
    p.condition_index = condition_index
    p.stage2_root = stage2_root
    p._stage2_cache = {}
    p._YOLO = None  # not needed unless a real weights file is found
    return p


def test_single_condition_species_is_detected():
    p = _bare_pipeline({"raspberry": ["healthy"], "tomato": ["healthy", "late_blight"]}, Path("/nonexistent"))
    assert p._is_single_condition("raspberry") is True
    assert p._is_single_condition("tomato") is False


def test_species_with_no_condition_entry_is_treated_as_single_condition():
    p = _bare_pipeline({"tomato": ["healthy", "late_blight"]}, Path("/nonexistent"))
    assert p._is_single_condition("unknown_species") is True


def test_missing_stage2_model_returns_none_without_raising(tmp_path):
    p = _bare_pipeline({"tomato": ["healthy", "late_blight"]}, tmp_path)
    result = p._get_stage2_model("tomato")
    assert result is None
    # cached as None so a second call doesn't re-check the filesystem
    assert p._stage2_cache["tomato"] is None
