"""AgriSense Plant Disease — serving API (Phase H).

A separate service from backend/main.py (the Supabase pump-automation
server) — different scaling profile (CPU-bound ONNX inference vs I/O-bound
Supabase calls), and a failure here must never be able to take pump
automation down (see plant-disease-implementation-plan.md section "H").

Endpoints:
  POST /predict  — image upload -> {species, condition, confidences, ...}
  GET  /health   — unauthenticated, for the platform's health probe
  GET  /version  — registry version + metrics
"""
from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, status
from PIL import Image, UnidentifiedImageError

from .auth import require_api_key
from .pipeline_runtime import TwoStagePipelineRuntime

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "./models"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp"}

_pipeline: TwoStagePipelineRuntime | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pipeline
    _pipeline = TwoStagePipelineRuntime(MODEL_DIR)  # load once at startup, not per request
    yield
    _pipeline = None


app = FastAPI(title="AgriSense Plant Disease API", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/version")
def version(_: str = Depends(require_api_key)):
    assert _pipeline is not None
    return {
        "registry_version": _pipeline.registry["version"],
        "created_at": _pipeline.registry["created_at"],
        "metrics": _pipeline.registry["metrics"],
    }


@app.post("/predict")
async def predict(file: UploadFile = File(...), _: str = Depends(require_api_key)):
    assert _pipeline is not None

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported content type '{file.content_type}'. Allowed: {sorted(ALLOWED_CONTENT_TYPES)}",
        )

    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Upload exceeds {MAX_UPLOAD_BYTES} bytes.",
        )

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Could not decode image.")

    pred = _pipeline.predict(image)

    return {
        "species": pred.species,
        "species_confidence": round(pred.species_confidence, 4),
        "condition": pred.condition,
        "condition_confidence": round(pred.condition_confidence, 4),
        "joint_confidence": round(pred.joint_confidence, 4),
        "low_confidence": pred.low_confidence,
        "model_version": _pipeline.registry["version"],
        "inference_ms": round(pred.inference_ms, 1),
    }
