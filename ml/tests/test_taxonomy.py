"""Unit tests for agrisense_pd.data.taxonomy (Phase B1).

Run with: python -m pytest ml/tests/test_taxonomy.py -v
(from the ml/ directory, or with ml/src on PYTHONPATH)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agrisense_pd.data import taxonomy  # noqa: E402


def test_strip_accents():
    assert taxonomy.strip_accents("saudável") == "saudavel"
    assert taxonomy.strip_accents("Mancha_Angular") == "Mancha_Angular"


def test_normalize_token_collapses_separators():
    assert taxonomy.normalize_token("Tomato___Yellow_Leaf_Curl_Virus") == "tomato_yellow_leaf_curl_virus"
    assert taxonomy.normalize_token("Pepper,_bell") == "pepper_bell"


def test_both_tomato_yellow_leaf_curl_forms_resolve_the_same():
    a = taxonomy.resolve_label("plantvillage", "Tomato_Yellow_Leaf_Curl_Virus")
    b = taxonomy.resolve_label("plantvillage", "Tomato___Yellow_Leaf_Curl_Virus")
    assert a["species"] == "tomato"
    assert a["condition"] == "yellow_leaf_curl_virus"
    assert a["species"] == b["species"]
    assert a["condition"] == b["condition"]
    assert a["confidence"] == "auto"
    assert b["confidence"] == "auto"


def test_pepper_bell_synonym():
    r = taxonomy.resolve_label("plantvillage", "Pepper,_bell___Bacterial_spot")
    assert r["species"] == "bell_pepper"
    assert r["condition"] == "bacterial_spot"
    assert r["confidence"] == "auto"


def test_portuguese_label_translates():
    r = taxonomy.resolve_label("digipathos", "Milho___Ferrugem")
    assert r["species"] == "maize"
    assert r["condition"] == "rust"
    assert r["confidence"] == "auto"


def test_portuguese_healthy_label():
    r = taxonomy.resolve_label("digipathos", "Soja___Saudavel")
    assert r["species"] == "soybean"
    assert r["condition"] == "healthy"


def test_unresolvable_label_is_flagged_for_review_not_guessed():
    r = taxonomy.resolve_label("digipathos", "Xyzzy___Whatsit123")
    assert r["confidence"] == "review"
    assert r["species"] == ""
    assert r["condition"] == ""


def test_override_wins_over_automatic_resolution(tmp_path, monkeypatch):
    import yaml

    overrides_content = {
        "overrides": [
            {
                "src_dataset": "digipathos",
                "src_label": "Xyzzy___Whatsit123",
                "species": "coffee",
                "condition": "leaf_rust",
            }
        ]
    }
    overrides_file = tmp_path / "taxonomy_overrides.yaml"
    overrides_file.write_text(yaml.dump(overrides_content), encoding="utf-8")
    monkeypatch.setattr(taxonomy, "CONFIGS_DIR", tmp_path)

    overrides = taxonomy.load_overrides()
    key = ("digipathos", "Xyzzy___Whatsit123")
    assert key in overrides
    assert overrides[key]["species"] == "coffee"
    assert overrides[key]["condition"] == "leaf_rust"
    assert overrides[key]["confidence"] == "override"
