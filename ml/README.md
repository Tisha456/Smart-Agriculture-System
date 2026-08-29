# AgriSense — Plant Species + Disease Recognition ML Pipeline

Trains two models — a species classifier (Stage 1) and one disease
classifier per species (Stage 2) — on Google Colab's free GPU, evaluates
them honestly (including a real-world PlantDoc test), and exports them
for the FastAPI serving layer in `../serving/`.

Full design rationale lives in `../plant-disease-implementation-plan.md`
(the spec this code implements). Read it first if something here looks
unexplained — every non-obvious decision is justified there, not repeated
in code comments.

## Quickstart (Google Colab)

1. Open `notebooks/AgriSense_PlantDisease_Colab.ipynb` in Colab.
2. **Runtime -> Change runtime type -> T4 GPU** (or better, if you have Colab Pro).
3. Run cells top to bottom, in order. Each cell maps to one phase (A1
   through G) and is safe to re-run — every script here is idempotent.
4. A few cells need a human in the loop (clearly marked in the notebook):
   - Cell 4: upload your `kaggle.json` (PlantVillage download).
   - Cell 8: read the taxonomy "review" list, fill in
     `configs/taxonomy_overrides.yaml`, re-run cell 7.
   - Cells 17-18: conditional — only run if Phase E1's report says to.
5. If Colab disconnects mid-training: reconnect, re-run cells 1-3 and 5
   and 12 (cheap — they just rebuild the local disk from Drive), then
   re-run whichever training cell you were on (13 or 14). It resumes;
   it does not restart.

## Layout

```
configs/       All tunable parameters. Nothing is hardcoded in scripts.
notebooks/     The Colab notebook — this is what you actually open and run.
src/agrisense_pd/
  config.py, logging_utils.py, drive_io.py, imaging.py   — shared infra
  data/     Phases A2-C2: download, inspect, taxonomy, clean, manifest, split, materialize
  train/    Phases D1-D2: Stage 1 + Stage 2 training, checkpoint sync, resume state
  eval/     Phases E0-E1: two-stage inference pipeline, held-out + PlantDoc evaluation
  detect/   Phase E2 (conditional): leaf detector pre-step
  export/   Phase G: ONNX export, verification, serving registry
tests/       Plain-Python unit tests, no GPU/Colab needed:
             python -m pytest ml/tests -v
```

## Conventions

- **Seed 42 everywhere** (`config.SEED`) — splits and training are
  deterministic given the same manifest.
- **snake_case taxonomy**: `species` and `condition` values are lowercase
  ASCII snake_case (`bell_pepper`, `late_blight`, `healthy`). No `___`, no
  accents. See `data/taxonomy.py`.
- **Idempotent scripts**: re-running any script is safe and either no-ops
  or completes remaining work. Pass `--force` where a script supports it
  to force a rebuild.
- **One manifest, not copied folders**: `manifests/master.csv` on Drive is
  the source of truth. Training folder trees under `data/stage1_species/`
  and `data/stage2_disease/` are symlinked from it on demand by
  `materialize.py` — they are disposable and rebuilt from the manifest
  every session, never hand-edited.
- **Drive vs local**: `Drive/AgriSense_PlantDisease/` holds everything
  that must survive a session (archives, manifests, model checkpoints,
  exported models, artifacts/reports). `/content/agrisense_pd/` holds
  everything disposable (extracted images, the materialized folder
  trees, ultralytics run directories) — see `configs/paths.yaml`.
- **Config-driven paths**: every path comes from `config.PATHS`
  (`configs/paths.yaml`). No script hardcodes `/content/...` or a Drive
  path directly.
- **CLI everywhere**: every script is runnable as
  `python -m agrisense_pd.<module> --flags` and takes no interactive input.

## Running tests locally (no GPU needed)

```bash
cd ml
pip install pytest pyyaml
python -m pytest tests -v
```

These cover the pure-Python logic (taxonomy resolution, split assignment,
manifest building, folder materialization, pipeline routing) — they do
not need ultralytics/torch/PIL and run in well under a second.

## After training: getting models into the serving API

Phase G (`export/to_onnx.py`, `verify_onnx.py`, `registry.py`) writes
everything the API needs to `Drive/AgriSense_PlantDisease/exported/`.
Download that folder and place its contents at `../serving/models/` —
see `../serving/DEPLOY.md` for the full path from there to a live,
API-key-protected HTTPS endpoint.
