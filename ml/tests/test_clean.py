"""Unit tests for agrisense_pd.data.clean's PlantDoc train/test contamination
guard (find_plantdoc_overlaps). This is what stops a PlantWild training
image that happens to duplicate a PlantDoc test image from silently
inflating Phase E1's real-world accuracy number (see
plant-disease-implementation-plan.md section 1.4).

Pure-function tests only — no real images needed, since the matching
logic operates purely on phash strings.

Run with: python -m pytest ml/tests/test_clean.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agrisense_pd.data import clean  # noqa: E402


def test_identical_phash_is_flagged_as_overlap():
    training_rows = [{"path": "train/img1.jpg", "phash": "aaaaaaaaaaaaaaaa"}]
    plantdoc_phashes = ["aaaaaaaaaaaaaaaa"]
    overlaps = clean.find_plantdoc_overlaps(training_rows, plantdoc_phashes)
    assert overlaps == {"train/img1.jpg"}


def test_near_duplicate_within_threshold_is_flagged():
    # Differ by a few bits (Hamming distance <= PHASH_HAMMING_THRESHOLD)
    training_rows = [{"path": "train/img1.jpg", "phash": "0000000000000000"}]
    # 0x0000... vs 0x0000000000000003 -> hamming distance 2
    plantdoc_phashes = ["0000000000000003"]
    overlaps = clean.find_plantdoc_overlaps(training_rows, plantdoc_phashes)
    assert overlaps == {"train/img1.jpg"}


def test_dissimilar_phash_is_not_flagged():
    training_rows = [{"path": "train/img1.jpg", "phash": "0000000000000000"}]
    plantdoc_phashes = ["ffffffffffffffff"]  # maximally different
    overlaps = clean.find_plantdoc_overlaps(training_rows, plantdoc_phashes)
    assert overlaps == set()


def test_empty_plantdoc_list_flags_nothing():
    training_rows = [{"path": "train/img1.jpg", "phash": "aaaaaaaaaaaaaaaa"}]
    overlaps = clean.find_plantdoc_overlaps(training_rows, [])
    assert overlaps == set()


def test_rows_without_phash_are_skipped_not_crashed():
    training_rows = [{"path": "train/img1.jpg", "phash": ""}]
    overlaps = clean.find_plantdoc_overlaps(training_rows, ["aaaaaaaaaaaaaaaa"])
    assert overlaps == set()


def test_only_matching_rows_are_flagged_among_many():
    training_rows = [
        {"path": "train/match.jpg", "phash": "aaaaaaaaaaaaaaaa"},
        {"path": "train/nomatch.jpg", "phash": "ffffffffffffffff"},
    ]
    overlaps = clean.find_plantdoc_overlaps(training_rows, ["aaaaaaaaaaaaaaaa"])
    assert overlaps == {"train/match.jpg"}
