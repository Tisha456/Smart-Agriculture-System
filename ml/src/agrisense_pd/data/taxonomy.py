"""Phase B1 — unify every training dataset's (config.TRAINING_DATASETS)
class names, plus PlantDoc's for eval-time label matching in Phase E, into
one (species, condition) taxonomy.

Design (see plant-disease-implementation-plan.md section "B1"):
  - Normalize: strip accents -> lowercase -> collapse separators -> snake_case.
  - Translate known Portuguese agronomy terms to English before lookup.
  - Resolve against a canonical species/condition vocabulary + synonym table.
  - Anything NOT confidently resolved gets confidence="review" and blank
    species/condition — it is never guessed. You fill in
    ml/configs/taxonomy_overrides.yaml for those, and overrides always win.

Usage:
    python -m agrisense_pd.data.taxonomy --build
"""
from __future__ import annotations

import argparse
import csv
import re
import unicodedata
from pathlib import Path
from typing import Optional

import yaml

from ..config import CONFIGS_DIR, PATHS, TRAINING_DATASETS
from ..logging_utils import get_logger

log = get_logger("taxonomy")

# ---------------------------------------------------------------------------
# Canonical vocabularies. Extend these (or use taxonomy_overrides.yaml) as
# new source labels turn up in the "review" list — do not guess inline.
# ---------------------------------------------------------------------------

CANONICAL_SPECIES = {
    "apple", "blueberry", "cherry", "maize", "grape", "orange", "peach",
    "bell_pepper", "potato", "raspberry", "soybean", "squash", "strawberry",
    "tomato", "coffee", "bean", "cassava", "cotton", "wheat", "rice",
    "sugarcane", "citrus", "cucumber", "watermelon", "banana",
}

CANONICAL_CONDITIONS = {
    "healthy", "scab", "black_rot", "cedar_apple_rust", "powdery_mildew",
    "gray_leaf_spot", "common_rust", "northern_leaf_blight", "esca",
    "leaf_blight", "bacterial_spot", "early_blight", "late_blight",
    "leaf_mold", "septoria_leaf_spot", "spider_mites", "target_spot",
    "mosaic_virus", "yellow_leaf_curl_virus", "citrus_greening", "rust",
    "anthracnose", "leaf_rust", "brown_spot", "angular_leaf_spot",
    "bacterial_blight", "leaf_scorch", "phoma_leaf_spot", "downy_mildew",
    "red_rot", "wilt", "canker", "sooty_mold", "sigatoka",
    # cassava (Kaggle gauravduttakiit/cassava-leaf-disease-classification)
    "brown_streak_disease", "green_mottle", "mosaic_disease",
    # rice (Kaggle nirmalsankalana/rice-leaf-disease-image)
    "blast", "tungro", "leaf_scald", "hispa",
}

# species synonyms: normalized-token -> canonical
SPECIES_SYNONYMS = {
    "corn": "maize",
    "corn_maize": "maize",
    "milho": "maize",
    "pepper": "bell_pepper",
    "pepper_bell": "bell_pepper",
    "peppers_bell": "bell_pepper",
    "soja": "soybean",
    "feijao": "bean",
    "cafe": "coffee",
    "algodao": "cotton",
    "trigo": "wheat",
    "arroz": "rice",
    "cana": "sugarcane",
    "cana_de_acucar": "sugarcane",
    "mandioca": "cassava",
    "citros": "citrus",
    "laranja": "orange",
    "morango": "strawberry",
    "batata": "potato",
    "uva": "grape",
    "maca": "apple",
    "banana_": "banana",
}

# condition synonyms: normalized-token (or substring key handled specially) -> canonical
CONDITION_SYNONYMS = {
    "grey_leaf_spot": "gray_leaf_spot",
    "cercospora_leaf_spot_gray_leaf_spot": "gray_leaf_spot",
    "cercospora_leaf_spot": "gray_leaf_spot",
    "black_measles": "esca",
    "haunglongbing_citrus_greening": "citrus_greening",
    "haunglongbing": "citrus_greening",
    "greening": "citrus_greening",
    "two_spotted_spider_mite": "spider_mites",
    "spider_mites_two_spotted_spider_mite": "spider_mites",
    "tomato_mosaic_virus": "mosaic_virus",
    "tomato_yellow_leaf_curl_virus": "yellow_leaf_curl_virus",
    "yellow_leaf_curl": "yellow_leaf_curl_virus",
    "saudavel": "healthy",
    "sadia": "healthy",
    "ferrugem": "rust",
    "ferrugem_asiatica": "rust",
    "mancha": "leaf_blight",
    "mancha_foliar": "leaf_blight",
    "mancha_de_cercospora": "gray_leaf_spot",
    "mancha_angular": "angular_leaf_spot",
    "oidio": "powdery_mildew",
    "mildio": "downy_mildew",
    "requeima": "late_blight",
    "pinta_preta": "black_rot",
    "cancro": "canker",
    "podridao": "wilt",
    "murcha": "wilt",
    "antracnose": "anthracnose",
    "queima_das_folhas": "leaf_blight",
}

# Portuguese -> English word-level translation, applied before synonym lookup
# (handles Digipathos labels that combine crop + disease in Portuguese).
PT_EN_WORDS = {
    "folha": "leaf",
    "folhas": "leaves",
    "planta": "plant",
    "doenca": "disease",
    "doente": "diseased",
    "sadia": "healthy",
    "saudavel": "healthy",
    "ferrugem": "rust",
    "mancha": "spot",
    "manchas": "spots",
    "oidio": "powdery_mildew",
    "mildio": "downy_mildew",
    "podridao": "rot",
    "murcha": "wilt",
    "cancro": "canker",
    "antracnose": "anthracnose",
    "cinzenta": "gray",
    "angular": "angular",
    "bacteriana": "bacterial",
    "viral": "viral",
    "asiatica": "asian",
}


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_token(raw: str) -> str:
    """unicode-strip accents -> lowercase -> collapse separators -> snake_case"""
    text = strip_accents(raw)
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text


def translate_pt(token: str) -> str:
    parts = token.split("_")
    translated = [PT_EN_WORDS.get(p, p) for p in parts]
    return "_".join(translated)


def _resolve_species(token: str) -> tuple[Optional[str], str]:
    token = normalize_token(token)
    if token in CANONICAL_SPECIES:
        return token, "auto:canonical"
    if token in SPECIES_SYNONYMS:
        return SPECIES_SYNONYMS[token], "auto:synonym"
    translated = translate_pt(token)
    if translated in CANONICAL_SPECIES:
        return translated, "auto:pt_translation"
    if translated in SPECIES_SYNONYMS:
        return SPECIES_SYNONYMS[translated], "auto:pt_translation+synonym"
    return None, "unresolved"


def _resolve_condition(token: str) -> tuple[Optional[str], str]:
    token = normalize_token(token)
    if token in ("healthy", "saudavel", "sadia"):
        return "healthy", "auto:healthy"
    if token in CANONICAL_CONDITIONS:
        return token, "auto:canonical"
    if token in CONDITION_SYNONYMS:
        return CONDITION_SYNONYMS[token], "auto:synonym"
    translated = translate_pt(token)
    if translated in CANONICAL_CONDITIONS:
        return translated, "auto:pt_translation"
    if translated in CONDITION_SYNONYMS:
        return CONDITION_SYNONYMS[translated], "auto:pt_translation+synonym"
    return None, "unresolved"


def split_species_condition(raw_label: str) -> tuple[str, str]:
    """Split a raw folder/label name into a (species_part, condition_part)
    guess, before per-part normalization/resolution.
    """
    if "___" in raw_label:
        species_part, _, condition_part = raw_label.partition("___")
        return species_part, condition_part

    # Fall back: normalize the whole thing, then look for the first token
    # (or first two tokens) that resolve as a species; everything after is
    # treated as the condition. This handles single-underscore or
    # differently-punctuated schemes (e.g. some Digipathos folder names).
    norm = normalize_token(raw_label)
    tokens = norm.split("_")
    for split_at in (1, 2):
        candidate_species = "_".join(tokens[:split_at])
        resolved, _ = _resolve_species(candidate_species)
        if resolved is not None:
            return candidate_species, "_".join(tokens[split_at:])
    # No species prefix recognized at all — return whole string as species
    # part so it still shows up (unresolved) in the review list rather than
    # silently vanishing.
    return norm, ""


def resolve_label(src_dataset: str, raw_label: str) -> dict:
    species_part, condition_part = split_species_condition(raw_label)
    species, species_src = _resolve_species(species_part)

    if not condition_part:
        # No condition segment at all (e.g. a bare species folder) — most
        # likely this whole folder IS a condition-less species dump, which
        # we can't safely assume means "healthy". Flag for review.
        condition, condition_src = None, "unresolved"
    else:
        condition, condition_src = _resolve_condition(condition_part)

    if species is None or condition is None:
        return {
            "src_dataset": src_dataset,
            "src_label": raw_label,
            "species": species or "",
            "condition": condition or "",
            "confidence": "review",
            "decision_source": f"species={species_src},condition={condition_src}",
        }
    return {
        "src_dataset": src_dataset,
        "src_label": raw_label,
        "species": species,
        "condition": condition,
        "confidence": "auto",
        "decision_source": f"species={species_src},condition={condition_src}",
    }


def collect_raw_labels() -> list[tuple[str, str]]:
    """(src_dataset, raw_label) pairs from every class folder under each
    dataset in config.TRAINING_DATASETS. PlantDoc is excluded from
    training-taxonomy building (it's test-only) but its object class
    names still go through resolve_label() at eval time in Phase E via the
    same functions imported directly.
    """
    pairs = []
    for dataset in TRAINING_DATASETS:
        root = PATHS.raw_dataset(dataset)
        if not root.exists():
            continue
        class_dirs = {
            d for d in root.rglob("*")
            if d.is_dir() and any(f.is_file() for f in d.iterdir())
        }
        for d in class_dirs:
            pairs.append((dataset, d.name))
    return sorted(set(pairs))


def load_overrides() -> dict[tuple[str, str], dict]:
    path = CONFIGS_DIR / "taxonomy_overrides.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    overrides = {}
    for entry in data.get("overrides", []) or []:
        key = (entry["src_dataset"], entry["src_label"])
        overrides[key] = {
            "src_dataset": entry["src_dataset"],
            "src_label": entry["src_label"],
            "species": entry["species"],
            "condition": entry["condition"],
            "confidence": "override",
            "decision_source": "manual_override",
        }
    return overrides


def build() -> list[dict]:
    raw_labels = collect_raw_labels()
    overrides = load_overrides()

    rows = []
    for dataset, raw_label in raw_labels:
        key = (dataset, raw_label)
        if key in overrides:
            rows.append(overrides[key])
        else:
            rows.append(resolve_label(dataset, raw_label))

    out_path = PATHS.taxonomy_map_csv()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f, fieldnames=["src_dataset", "src_label", "species", "condition",
                           "confidence", "decision_source"]
        )
        writer.writeheader()
        writer.writerows(rows)
    log.info("Wrote %s (%d labels)", out_path, len(rows))

    review = [r for r in rows if r["confidence"] == "review"]
    print(f"\nTotal labels: {len(rows)}")
    print(f"Auto-resolved: {sum(1 for r in rows if r['confidence'] == 'auto')}")
    print(f"Overridden: {sum(1 for r in rows if r['confidence'] == 'override')}")
    print(f"NEEDS REVIEW: {len(review)}")
    if review:
        print(
            "\nAdd entries for these to ml/configs/taxonomy_overrides.yaml, "
            "then re-run this script:\n"
        )
        for r in review:
            print(f"  [{r['src_dataset']}] {r['src_label']!r}  ({r['decision_source']})")

    species_set = sorted({r["species"] for r in rows if r["species"]})
    condition_set = sorted({r["condition"] for r in rows if r["condition"]})
    print(f"\nDistinct species resolved: {len(species_set)} -> {species_set}")
    print(f"Distinct conditions resolved: {len(condition_set)} -> {condition_set}")

    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase B1: build unified taxonomy.")
    parser.add_argument("--build", action="store_true", help="Build/rebuild taxonomy_map.csv")
    args = parser.parse_args()
    if args.build or True:  # building is the only mode; flag kept for notebook clarity
        build()


if __name__ == "__main__":
    main()
