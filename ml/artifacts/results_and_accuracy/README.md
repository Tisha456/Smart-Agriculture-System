# Stage 1 (minimal baseline) — training artifacts

Produced by running `ml/notebooks/AgriSense_Minimal_Train_Colab.ipynb` end to
end and unzipping its output here.

```
ml/artifacts/results_and_accuracy/
├── results.csv                      per-epoch training log
├── results.png                      loss / accuracy curves
├── confusion_matrix.png             per-class confusion
├── confusion_matrix_normalized.png
├── args.yaml                        exact hyperparameters used
├── metrics.json                     final val top-1 / top-5, class list
└── weights/
    ├── best.pt                      trained PyTorch weights
    ├── last.pt                      final-epoch checkpoint
    └── species.onnx                 exported ONNX (opset 12, 224px)
```

## Result

| | |
|---|---|
| Model | `yolo11n-cls`, 224px, seed 42 |
| Epochs | 5 |
| Classes | 38 (PlantVillage `Species___Condition`) |
| Train / val images | 43,444 / 10,861 |
| **Val top-1** | **99.32%** |
| **Val top-5** | **100%** |

These are committed to the repo on purpose — they are small (a few MB) and they
are the evidence that this model was actually trained here. Only
`serving/models/` is gitignored, because that holds the full production export.

## What this model is, and is not

**Is:** a single-stage classifier over PlantVillage's `Species___Condition`
folders, trained with `yolo11n-cls` for a handful of epochs at 224 px, seed 42.
A working baseline that proves the training and export path end to end.

**Is not:**

- **Not the production two-stage pipeline.** `serving/pipeline_runtime.py` expects
  `registry.json` plus separate `stage1/species.onnx` and `stage2/<species>.onnx`
  models, written by `ml/src/agrisense_pd/export/registry.py`. This single combined
  classifier does not have that structure, so it will **not** drop into `serving/`
  as-is.
- **Not what the app currently runs.** `/api/plant/predict` in `backend/main.py`
  falls back to Gemini vision unless `PLANT_API_URL` + `PLANT_API_KEY` are set.
  Those are unset, so the Plant Scan results you see in the app and dashboard come
  from Gemini, not from this file.
- **Not a real-world accuracy number.** PlantVillage is lab imagery — single
  detached leaves on plain backgrounds. Accuracy here runs high and does not
  transfer to field photos. That gap is exactly why `ml/configs/paths.yaml` holds
  PlantDoc out as an evaluation-only set. See `documents/DATASETS.md`.

## Getting from here to production

The full pipeline in `ml/` trains the real thing: four datasets, `yolo11s-cls`
for 30 epochs, two-stage species → disease routing, ONNX export with a registry.
Run `ml/notebooks/AgriSense_PlantDisease_Colab.ipynb`, put the exported tree in
`serving/models/`, deploy `serving/`, then set `PLANT_API_URL` + `PLANT_API_KEY`
on the backend. No application code changes — the switch is environment only.
