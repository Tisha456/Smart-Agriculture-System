"""Shared two-stage inference pipeline (PyTorch/ultralytics version).

This is the SINGLE implementation of "species model -> matching disease
model" routing, used by evaluate_holdout.py (E0), plantdoc_eval.py (E1),
and mirrored 1:1 in ONNXRuntime by serving/pipeline_runtime.py for the
live API. Keeping one implementation here means E0/E1 numbers reflect
exactly the logic that ships (see
plant-disease-implementation-plan.md section "E0").

Species with a single known condition never get a Stage 2 model (see
section 1.5) — predict() returns that constant condition directly,
inheriting the species confidence, and this is a normal/expected code
path, not a fallback for an error.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..config import PATHS
from ..logging_utils import get_logger

log = get_logger("eval.pipeline")


@dataclass
class Prediction:
    species: str
    species_confidence: float
    condition: Optional[str]
    condition_confidence: float
    joint_confidence: float
    species_topk: list[tuple[str, float]] = field(default_factory=list)
    notes: str = ""


def _load_condition_index() -> dict[str, list[str]]:
    path = PATHS.condition_index_json()
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run build_manifest.py (Phase B3) first.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


class TwoStagePipeline:
    """Loads Stage 1 once; loads Stage 2 models lazily and caches them,
    since evaluation/serving only ever touches a subset of species per
    run and loading ~25 models eagerly wastes memory and startup time.
    """

    def __init__(
        self,
        stage1_weights: Optional[Path] = None,
        stage2_root: Optional[Path] = None,
        imgsz: int = 224,
    ) -> None:
        from ultralytics import YOLO

        self._YOLO = YOLO
        self.stage1_weights = Path(stage1_weights) if stage1_weights else PATHS.stage1_models() / "best.pt"
        self.stage2_root = Path(stage2_root) if stage2_root else PATHS.stage2_models()
        self.imgsz = imgsz
        self.condition_index = _load_condition_index()

        if not self.stage1_weights.exists():
            raise FileNotFoundError(
                f"Stage 1 weights not found at {self.stage1_weights}. Run train/stage1.py (Phase D1) first."
            )
        self.stage1_model = YOLO(str(self.stage1_weights))
        self._stage2_cache: dict[str, object] = {}

    def _is_single_condition(self, species: str) -> bool:
        conditions = self.condition_index.get(species, [])
        return len(conditions) < 2

    def _get_stage2_model(self, species: str):
        if species in self._stage2_cache:
            return self._stage2_cache[species]

        weights = self.stage2_root / species / "best.pt"
        if not weights.exists():
            self._stage2_cache[species] = None
            return None

        model = self._YOLO(str(weights))
        self._stage2_cache[species] = model
        return model

    def predict(self, image) -> Prediction:
        """`image` — anything ultralytics .predict() accepts: a path,
        PIL.Image, or numpy array.
        """
        stage1_results = self.stage1_model.predict(image, imgsz=self.imgsz, verbose=False)
        r1 = stage1_results[0]
        probs = r1.probs
        species_idx = int(probs.top1)
        species = self.stage1_model.names[species_idx]
        species_conf = float(probs.top1conf)

        top5_idx = [int(i) for i in probs.top5]
        top5_conf = [float(c) for c in probs.top5conf]
        species_topk = [(self.stage1_model.names[i], c) for i, c in zip(top5_idx, top5_conf)]

        if self._is_single_condition(species):
            conditions = self.condition_index.get(species, [])
            condition = conditions[0] if conditions else None
            condition_conf = species_conf  # inherited — see spec section 1.5
            notes = "single_condition_species" if condition else "species_has_no_known_conditions"
            joint = species_conf * condition_conf if condition else 0.0
            return Prediction(
                species=species, species_confidence=species_conf,
                condition=condition, condition_confidence=condition_conf,
                joint_confidence=joint, species_topk=species_topk, notes=notes,
            )

        stage2_model = self._get_stage2_model(species)
        if stage2_model is None:
            log.warning("No Stage 2 model found for species '%s'.", species)
            return Prediction(
                species=species, species_confidence=species_conf,
                condition=None, condition_confidence=0.0, joint_confidence=0.0,
                species_topk=species_topk, notes="no_stage2_model_found",
            )

        stage2_results = stage2_model.predict(image, imgsz=self.imgsz, verbose=False)
        r2 = stage2_results[0]
        cond_idx = int(r2.probs.top1)
        condition = stage2_model.names[cond_idx]
        condition_conf = float(r2.probs.top1conf)

        return Prediction(
            species=species, species_confidence=species_conf,
            condition=condition, condition_confidence=condition_conf,
            joint_confidence=species_conf * condition_conf,
            species_topk=species_topk, notes="",
        )
