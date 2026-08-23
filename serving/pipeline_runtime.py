"""ONNXRuntime mirror of ml/src/agrisense_pd/eval/pipeline.py.

Same two-stage routing logic (species model -> matching disease model,
single_condition species short-circuit, missing-model handling), but
self-contained (numpy + onnxruntime + Pillow only, no torch/ultralytics)
since this is what actually runs in the deployed API — a much lighter
dependency footprint than training (see
plant-disease-implementation-plan.md section "H").

Driven ENTIRELY by registry.json (written by ml/.../export/registry.py):
preprocessing parameters, per-species class lists, and confidence
thresholds all come from there, never re-derived here. This is what
makes a training/serving normalization mismatch impossible by
construction.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps


@dataclass
class Prediction:
    species: str
    species_confidence: float
    condition: Optional[str]
    condition_confidence: float
    joint_confidence: float
    low_confidence: bool
    inference_ms: float
    notes: str = ""
    species_topk: list[tuple[str, float]] = field(default_factory=list)


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()


def _looks_like_probabilities(x: np.ndarray) -> bool:
    return bool(np.all(x >= -1e-4) and abs(float(x.sum()) - 1.0) < 1e-2)


class TwoStagePipelineRuntime:
    def __init__(self, model_dir: Path | str):
        self.model_dir = Path(model_dir)
        registry_path = self.model_dir / "registry.json"
        if not registry_path.exists():
            raise FileNotFoundError(
                f"{registry_path} not found. Download exported/ from Drive into {self.model_dir} "
                "after running Phase G (export/registry.py)."
            )
        with open(registry_path, "r", encoding="utf-8") as f:
            self.registry = json.load(f)

        self.input_size = self.registry["input"]["size"]
        self.mean = np.array(self.registry["input"]["mean"], dtype=np.float32).reshape(3, 1, 1)
        self.std = np.array(self.registry["input"]["std"], dtype=np.float32).reshape(3, 1, 1)
        self.min_species_conf = self.registry["thresholds"]["min_species_confidence"]
        self.min_condition_conf = self.registry["thresholds"]["min_condition_confidence"]

        stage1_path = self.model_dir / self.registry["stage1"]["path"]
        self.stage1_session = ort.InferenceSession(str(stage1_path), providers=["CPUExecutionProvider"])
        self.stage1_input_name = self.stage1_session.get_inputs()[0].name
        self.stage1_classes = self.registry["stage1"]["classes"]

        self._stage2_sessions: dict[str, ort.InferenceSession] = {}

    def _preprocess(self, image: Image.Image) -> np.ndarray:
        image = ImageOps.exif_transpose(image).convert("RGB")
        image = image.resize((self.input_size, self.input_size), Image.BILINEAR)
        arr = np.asarray(image, dtype=np.float32) / 255.0  # HWC, [0,1]
        arr = arr.transpose(2, 0, 1)  # CHW
        arr = (arr - self.mean) / self.std
        return arr[np.newaxis, ...].astype(np.float32)

    def _run_session(self, session: ort.InferenceSession, input_name: str, tensor: np.ndarray) -> np.ndarray:
        outputs = session.run(None, {input_name: tensor})
        logits = np.asarray(outputs[0]).reshape(-1)
        if not _looks_like_probabilities(logits):
            logits = _softmax(logits)
        return logits

    def _get_stage2_session(self, species: str):
        entry = self.registry["stage2"].get(species)
        if entry is None or entry.get("type") in ("constant", "unavailable"):
            return None, entry
        if species in self._stage2_sessions:
            return self._stage2_sessions[species], entry
        path = self.model_dir / entry["path"]
        if not path.exists():
            return None, entry
        session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self._stage2_sessions[species] = session
        return session, entry

    def predict(self, image: Image.Image) -> Prediction:
        start = time.monotonic()
        tensor = self._preprocess(image)

        probs1 = self._run_session(self.stage1_session, self.stage1_input_name, tensor)
        species_idx = int(np.argmax(probs1))
        species = self.stage1_classes[species_idx]
        species_conf = float(probs1[species_idx])

        top5_idx = np.argsort(probs1)[::-1][:5]
        species_topk = [(self.stage1_classes[i], float(probs1[i])) for i in top5_idx]

        entry = self.registry["stage2"].get(species)
        if entry is not None and entry.get("type") == "constant":
            condition = entry["condition"]
            condition_conf = species_conf
            notes = "single_condition_species"
        elif entry is not None and entry.get("type") == "unavailable":
            condition, condition_conf, notes = None, 0.0, "no_stage2_model_found"
        else:
            session, _ = self._get_stage2_session(species)
            if session is None:
                condition, condition_conf, notes = None, 0.0, "no_stage2_model_found"
            else:
                input_name = session.get_inputs()[0].name
                probs2 = self._run_session(session, input_name, tensor)
                cond_idx = int(np.argmax(probs2))
                condition = entry["classes"][cond_idx]
                condition_conf = float(probs2[cond_idx])
                notes = ""

        joint = species_conf * condition_conf if condition is not None else 0.0
        low_confidence = (
            condition is None
            or species_conf < self.min_species_conf
            or condition_conf < self.min_condition_conf
        )
        inference_ms = (time.monotonic() - start) * 1000

        return Prediction(
            species=species, species_confidence=species_conf,
            condition=condition, condition_confidence=condition_conf,
            joint_confidence=joint, low_confidence=low_confidence,
            inference_ms=inference_ms, notes=notes, species_topk=species_topk,
        )
