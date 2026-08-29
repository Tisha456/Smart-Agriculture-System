# AgriSense — Plant Species + Disease Recognition: Implementation Spec

**Status:** build spec. Nothing here has been generated yet.
**Scope:** this file is the single source of truth — both the "why" and the "what to build". (It absorbed an earlier stage-by-stage roadmap document, since removed.)
**Execution target:** Google Colab, free tier (single T4, ~16 GB VRAM, ~12 h session cap, disconnects expected).
**Deliverable:** two trained models — Stage 1 (species) and Stage 2 (one disease model per species) — exported to ONNX, plus a keyed FastAPI service that serves them into the AgriSense app + web dashboard.

---

## 0. How to use this file

Each phase below has a fixed shape:

| Field | Meaning |
|---|---|
| **Goal** | One sentence. |
| **Files to generate** | Exact paths Claude Code must create. Nothing outside this list. |
| **Contract** | CLI signature, inputs, outputs, and the invariants the code must hold. |
| **Colab cell** | The exact cell that runs it in the notebook. |
| **Accept when** | Objective pass condition. If it fails, the phase is not done. |

Work phase by phase. Do not generate a later phase's files early — later phases depend on real numbers (class counts, accuracy) that only exist after the earlier ones run.

---

## 1. Deviations from the original roadmap (read before generating)

These are deliberate. Each replaces a step from the earlier roadmap document that this
spec superseded.

### 1.1 Drive is cold storage; `/content` is the working disk
The roadmap (A1) puts `data/` in Drive. Mounted Drive is a FUSE layer with per-file latency in the tens of milliseconds — fine for a 4 GB archive, ruinous for 100,000 individual JPEGs read every epoch. Epoch time becomes I/O-bound and the GPU idles.

**Instead:**

```
Drive  (persists across sessions, survives disconnects)
  archives/       raw dataset archives, downloaded once, never re-downloaded
  manifests/      master.csv + taxonomy CSVs  (small, text, the real source of truth)
  models/         checkpoints synced mid-training + final weights
  exported/       ONNX + registry.json
  artifacts/      reports, confusion matrices, logs
  state/          resume state for the multi-session stage-2 loop

/content/agrisense_pd  (fast local SSD, wiped every session, fully rebuildable)
  data/raw/       extracted archives
  data/clean/     rejected/quarantined images
  data/stage1_species/   symlink tree: train|val|test / <species>/
  data/stage2_disease/   symlink tree: <species>/ train|val|test / <condition>/
  runs/           ultralytics working dir
```

**Rule:** every local path must be reconstructible from Drive by re-running the setup cells. Nothing irreplaceable ever lives only on `/content`.

### 1.2 A manifest replaces three copies of the dataset
Roadmap B3 copies cleaned images into `data/clean/merged/<species>/<condition>/`, then C1 copies them again into `stage1_species/`, then C2 a third time into `stage2_disease/`. That is ~3× disk and, on Drive, hours of file-by-file copying per session.

**Instead:** one file, `manifests/master.csv`, one row per surviving image:

```csv
image_id,src_dataset,src_relpath,src_label,species,condition,width,height,sha256,phash,dup_group,split,status,reject_reason
```

- `image_id` — stable: `sha256[:16]`.
- `split` — one of `train|val|test`. **One column, used by both stages** (see 1.3).
- `status` — `ok` | `rejected` | `unmapped`.
- Folder trees are built on demand by `materialize.py` using symlinks. Building both trees takes seconds and ~0 extra bytes.

### 1.3 A single split column, shared by both stages
The roadmap splits stage 1 (C1) and stage 2 (C2) independently with separate 80/10/10 draws. An image can then land in stage-1 `test` and stage-2 `train`. Phase E's end-to-end number would then be measured on images the stage-2 model memorized, inflating it.

**Instead:** split once, stratified on the `(species, condition)` pair, and reuse that assignment for both stages. The stage-1 test set and every stage-2 test set are then disjoint from all training data, so end-to-end accuracy is honest.

### 1.4 Duplicate-group-aware splitting
PlantVillage contains many near-identical frames of the same physical leaf. An exact-hash dedup (roadmap B2) does not catch these; a random split then puts frame *n* in train and frame *n+1* in test, and validation accuracy reads ~0.99 while real-world accuracy collapses.

**Instead:** cluster by perceptual hash (`dup_group`), and assign an entire cluster to one split. Exact duplicates are dropped; near-duplicates are kept but never straddle a split.

### 1.5 Species with one condition get no Stage 2 model
If a species has only `healthy` (or only one disease) after merging, training a 1-class classifier is meaningless. The registry marks it `constant` and the runtime returns that condition with confidence inherited from Stage 1. Saves training time and avoids a degenerate model.

### 1.6 Stage 2 must survive session death
~20–30 separate trainings cannot fit one free-tier session. The loop is a resumable state machine (`state/stage2_progress.json`), and every training resumes from `last.pt` if one exists. Reconnecting and re-running the same cell must continue, never restart.

---

## 2. Global conventions

Every generated file obeys these. State them in `ml/README.md` too.

- **Python** 3.10+ (Colab default). Type hints on all public functions.
- **Idempotent**: re-running any script must be safe. Detect completed work and skip, unless `--force`.
- **Seed**: `SEED = 42`, set in `config.py` for `random`, `numpy`, `torch`. Splits are deterministic given the same manifest.
- **Naming**: canonical `species` and `condition` are lowercase `snake_case` ASCII — `tomato`, `late_blight`, `healthy`, `yellow_leaf_curl_virus`. No `___`, no spaces, no accents (Digipathos labels are Portuguese and accented; they get transliterated then mapped).
- **Logging**: one `logging_utils.get_logger(name)`; every script writes to stdout *and* appends to `artifacts/logs/<script>.log` on Drive. No bare `print` in library code.
- **Config**: all paths come from `configs/paths.yaml` via `config.py`. No hardcoded `/content/...` anywhere except `paths.yaml`.
- **CLI**: `argparse`, every script runnable as `python -m agrisense_pd.<module> --flags`. No logic in `if __name__` beyond arg parsing and a call.
- **No silent failures**: a script that cannot do its job exits non-zero with a message naming the missing input.

---

## 3. File manifest (everything Claude Code will generate)

```
ml/
  README.md                          # quickstart, conventions, phase order
  requirements-colab.txt
  configs/
    paths.yaml                       # Drive root, local root, all derived paths
    sources.yaml                     # dataset URLs/slugs + manual-fallback notes
    taxonomy_overrides.yaml          # human decisions from B1 (hand-edited)
    train_stage1.yaml                # hyperparameters
    train_stage2.yaml
  notebooks/
    AgriSense_PlantDisease_Colab.ipynb
  src/agrisense_pd/
    __init__.py
    config.py                        # loads paths.yaml, seeds, dataclasses
    logging_utils.py
    drive_io.py                      # mount, archive push/pull, checkpoint sync
    imaging.py                       # safe open, sha256, phash, size checks
    data/
      __init__.py
      download.py                    # A2
      inspect_structure.py           # A3
      taxonomy.py                    # B1
      clean.py                       # B2
      build_manifest.py              # B3
      split.py                       # C0
      materialize.py                 # C1 + C2
    train/
      __init__.py
      callbacks.py                   # periodic checkpoint -> Drive
      stage1.py                      # D1
      stage2.py                      # D2 (resumable loop)
      resume_state.py
    eval/
      __init__.py
      pipeline.py                    # shared two-stage inference (torch)
      evaluate_holdout.py            # end-to-end on our own test split
      plantdoc_eval.py               # E1
      report.py                      # markdown + confusion matrices
    detect/
      __init__.py
      plantdoc_to_yolo.py            # E2, only if triggered
      train_detector.py
    export/
      __init__.py
      to_onnx.py                     # G
      verify_onnx.py
      registry.py                    # writes exported/registry.json
  tests/
    test_taxonomy.py
    test_split.py
    test_manifest.py

serving/                             # Phase H+, runs in this repo, not Colab
  app.py
  pipeline_runtime.py                # ONNX runtime version of eval/pipeline.py
  auth.py
  requirements.txt
  Dockerfile
  .env.example
```

The existing `backend/` (Supabase automation engine) stays untouched. `serving/` is a **separate** service — it is GPU/CPU-heavy, has a different scaling profile, and must not be able to take the pump-automation backend down.

---

# PHASE A — Environment & Data

## A1. Environment setup

**Goal:** reproducible Colab session: GPU confirmed, Drive mounted, folder skeleton created, deps pinned.

**Files to generate:** `ml/configs/paths.yaml`, `ml/src/agrisense_pd/config.py`, `ml/src/agrisense_pd/logging_utils.py`, `ml/src/agrisense_pd/drive_io.py`, `ml/requirements-colab.txt`, notebook cells 1–3.

**Contract**
- `config.py` exposes `PATHS` (dataclass of every path), `SEED`, `set_seeds()`, and `ensure_dirs()` which creates the full Drive + local skeleton from §1.1.
- `drive_io.mount()` — idempotent, no-op if already mounted, hard error if not on Colab.
- `drive_io.pull_archive(name)` / `push_archive(name)` — move archives between Drive and `/content` with size verification.
- `drive_io.sync_checkpoint(src, dest_subdir)` — atomic (write `.tmp`, then rename) so a disconnect mid-copy never leaves a corrupt `best.pt` on Drive.
- Env check prints: GPU name, VRAM, torch/CUDA version, ultralytics version, free disk on `/content`, free Drive quota. **Hard-fails if no GPU** — silently training on CPU wastes hours.
- `requirements-colab.txt` pins `ultralytics`, `torch`/`torchvision` (leave Colab's preinstalled CUDA build alone — install ultralytics with `--no-deps`-style care so it does not downgrade torch), `onnx`, `onnxruntime`, `imagehash`, `pillow`, `pandas`, `scikit-learn`, `pyyaml`, `tqdm`, `kaggle`.

**Colab cell**
```python
!pip -q install -r /content/AgriSense/ml/requirements-colab.txt
from agrisense_pd import config, drive_io
drive_io.mount(); config.ensure_dirs(); config.env_report()
```

**Accept when:** GPU line prints a T4/L4/A100, all Drive folders exist, `env_report()` exits 0, and torch was **not** downgraded by the install.

---

## A2. Acquire datasets

**Goal:** every dataset in `config.DATASETS` (the union of `paths.yaml`'s `training_datasets` and `eval_datasets`) sitting in Drive `archives/`, extracted to local `data/raw/`, with download happening **once ever**.

**Files:** `ml/configs/sources.yaml`, `ml/configs/paths.yaml`, `ml/src/agrisense_pd/data/download.py`.

**Contract**
- Which datasets get fetched is controlled entirely by `paths.yaml`'s `training_datasets` / `eval_datasets` lists, not by what happens to be listed in `sources.yaml` — an entry can exist there (kept for the record) without being active. Adding a new dataset is a config edit in these two files, not a code change to `download.py`.
- `sources.yaml` holds, per dataset: `kind` (`kaggle` | `http` | `git` | `huggingface` | `digipathos_pip` | `unavailable` | `manual`), locator, expected archive filename, and expected approximate size.
  - **PlantVillage** — Kaggle `mohitsingh1804/plantvillage`. Requires `kaggle.json`. Folder-per-class, `Species___Condition`.
  - **PlantWild** — HuggingFace dataset `uqtwei2/PlantWild` (two zips: v1 + v2, 30,030 images, 146 classes combined). Fetched via `huggingface_hub.hf_hub_download`, no Kaggle/Embrapa dependency. **Replaces Digipathos** — chosen specifically because it is *in-the-wild crowdsourced* imagery, directly targeting the documented PlantDoc real-world accuracy gap rather than adding more lab-condition data. License CC BY-NC-ND 4.0 (accepted for this personal-project model). Its internal label format is **not publicly documented**; Phase A3's report is what actually reveals it — do not assume a convention before reading `artifacts/inspect_plantwild.md`.
  - **Cassava** — Kaggle `nirmalsankalana/cassava-leaf-disease-classification` (folder-per-class re-packaging; deliberately not the raw competition mirror, which is a flat `train_images/` + `train.csv` format this pipeline's folder scanner can't read without a CSV-restructuring step this build does not have). Real field photos, 5 classes.
  - **Rice** — Kaggle `nirmalsankalana/rice-leaf-disease-image`. Confirmed folder-per-class, 4 disease classes, no healthy class.
  - **Digipathos** — `kind: unavailable`. **Confirmed dead**: the host actively refuses connections (`ECONNREFUSED`), reproduced from both a local machine and a live Colab session with unrestricted internet. Every known downloader package (`digipathos`, `georg-un/...`, `mtxslv/digipathos_downloader`) hits the identical Embrapa endpoint, so no package swap fixes an unreachable host. `download.py` skips this entry with an informational message rather than retrying — this is expected steady-state behavior, not a failure to handle.
  - **PlantDoc** — public GitHub repo. Two variants exist: the object-detection version (images + Pascal VOC XML) and a folder-per-class classification version. **Fetch the detection version** — Phase E2 needs the boxes, and the classification split is derivable from it.
- Order of operations per dataset: archive already in Drive → skip download → copy to `/content` → extract → verify → delete the local archive copy (not the Drive one).
- `--only <name>` to fetch one dataset; `--force` to re-download.
- Kaggle credentials: if `~/.kaggle/kaggle.json` is absent, print exactly what to upload and where, then exit non-zero.

**Accept when:** every dataset in `config.DATASETS` is non-empty except `digipathos` (which reports `SKIPPED`, not `MISSING`), no stray archives under `/content`, and re-running the script downloads nothing.

---

## A3. Inspect structure

**Goal:** know exactly how the three label schemes differ before writing any mapping.

**Files:** `ml/src/agrisense_pd/data/inspect_structure.py`.

**Contract**
- Scans each raw dataset **independently** — no merging logic here.
- Per dataset, writes `artifacts/inspect_<dataset>.md` and prints: directory depth and shape, detected label convention (`Species___Condition` / free-form / Portuguese / XML-annotated), class count, per-class image counts, image count total, extension histogram, and a resolution percentile table (p1/p50/p99).
- For PlantDoc: additionally parses the XML annotations and reports box-count-per-image distribution and the set of object class names.
- Writes a combined `artifacts/inspect_summary.md` with the three side by side.

**Accept when:** you can read the three reports and state, in one sentence each, how that dataset names its classes. This is a human checkpoint — do not proceed until you have actually read them.

---

# PHASE B — Taxonomy, Cleaning, Manifest

## B1. Unified taxonomy

**Goal:** every PlantVillage and Digipathos class name resolved to `(species, condition)` — with the ambiguous ones surfaced for a human, not guessed.

**Files:** `ml/src/agrisense_pd/data/taxonomy.py`, `ml/configs/taxonomy_overrides.yaml`, `ml/tests/test_taxonomy.py`.

**Contract**
- Normalization pipeline: unicode-strip accents → lowercase → collapse separators (`___`, `__`, `-`, spaces) → snake_case → apply a synonym table.
- Synonym table handles at minimum: `bell_pepper` = `pepper_bell` = `pepper`, `corn` = `maize`, `grey`/`gray`, `spot`/`spots`, `virus` suffixes, and the Portuguese→English crop and disease terms from Digipathos (`milho`→`maize`, `feijao`→`bean`, `mancha`→`spot`, `ferrugem`→`rust`, `saudavel`→`healthy`, etc.).
- Output `manifests/taxonomy_map.csv`:
  ```csv
  src_dataset,src_label,species,condition,confidence,decision_source
  ```
  where `confidence` ∈ `auto` | `review` | `override`, and `decision_source` names the rule that fired.
- **Anything not confidently resolved is written with `confidence=review` and `species`/`condition` blank** — never guessed. The script prints the review list and its count.
- `taxonomy_overrides.yaml` is hand-edited by you; re-running merges overrides in as `confidence=override`. Overrides always win.
- Answer the roadmap's own example explicitly in tests: `Tomato_Yellow_Leaf_Curl_Virus` and `Tomato___Yellow_Leaf_Curl_Virus` must both resolve to `(tomato, yellow_leaf_curl_virus)`.
- Unit tests cover: accent stripping, the two tomato forms, a Portuguese label, and an override taking precedence.

**Accept when:** the `review` list is empty *after* you have filled in `taxonomy_overrides.yaml`. Every source label maps to a `(species, condition)` pair, and the distinct species/condition vocabularies print cleanly with no near-duplicate entries (`gray_spot` and `grey_spot` both present = your synonym table is incomplete).

---

## B2. Clean & fingerprint

**Goal:** drop what is unusable, fingerprint everything else so duplicates and near-duplicates are known.

**Files:** `ml/src/agrisense_pd/imaging.py`, `ml/src/agrisense_pd/data/clean.py`.

**Contract**
- For every image in every `config.TRAINING_DATASETS` entry (**PlantDoc is untouched as training data** — it is test-only), compute: decodability, `(width,height)`, `sha256`, `phash` (64-bit).
- Reject rules, each recorded with a reason: `unreadable`, `truncated`, `too_small` (min side < 64 px), `bad_aspect` (ratio > 5:1), `exact_duplicate` (sha256 already seen — keep first, PlantVillage wins ties for stability), `unmapped` (label has no taxonomy entry), `plantdoc_overlap` (see below).
- Near-duplicates are **not** rejected. Cluster by Hamming distance ≤ 5 on `phash` and assign a shared `dup_group` id; singletons get their own group. Use a BK-tree or bucketed LSH — a naive O(n²) comparison over ~100k images will not finish in a session.
- **Cross-dataset contamination guard:** PlantDoc images are fingerprinted too (read-only — never written to `fingerprints.csv`, never trained on), and any training image within Hamming distance ≤ 5 of a PlantDoc image is rejected as `plantdoc_overlap`. This exists specifically because PlantWild is crowdsourced from Google/Ecosia/Baidu image search — the same route PlantDoc's images came from — so a duplicate landing on both sides is a real risk, not a theoretical one, and would silently inflate Phase E1's real-world accuracy number if left unguarded.
- Rejected files are **quarantined by reference**, not moved: write `manifests/rejected.csv` and copy at most 50 samples per reason into `data/clean/rejected/<reason>/` for eyeballing. Moving 10k files on Drive is pointless I/O.
- Parallelize hashing across CPU workers with a `tqdm` progress bar; checkpoint partial results every 5000 images to `manifests/fingerprints.partial.csv` so a disconnect does not cost the whole pass.

**Accept when:** rejection rate is under ~5% of the corpus. If it is higher, stop and read `rejected.csv` — a systematic misread (wrong extension filter, a nested folder level missed in A3) is far more likely than 20% of a curated dataset being broken. A `plantdoc_overlap` count on its own is not necessarily a problem (PlantWild/PlantDoc sharing a data source makes some overlap plausible) but is worth reading if it's large relative to PlantWild's size.

---

## B3. Build the master manifest

**Goal:** one CSV that is the dataset from here on.

**Files:** `ml/src/agrisense_pd/data/build_manifest.py`, `ml/tests/test_manifest.py`.

**Contract**
- Joins fingerprints (B2) + taxonomy map (B1) into `manifests/master.csv` with the schema in §1.2. `split` is left blank at this stage.
- Prints and writes `artifacts/class_report.md`: image count per species, per `(species, condition)`, per source dataset, and a cross-tab of species × condition.
- **Flags** every `(species, condition)` with < 200 images as `low_data`, and every species with < 2 distinct conditions as `single_condition` (these skip Stage 2 per §1.5). Both lists go into `artifacts/class_report.md`.
- Also emits `manifests/species_index.json` and `manifests/condition_index.json` — the canonical class-order for both stages. **Class ordering is frozen here** and every downstream step (training, ONNX export, the API) reads it. Never let ultralytics' alphabetical folder ordering be the implicit source of truth.

**Accept when:** `master.csv` row count ≈ (raw count − rejects), the cross-tab looks botanically sane, and you have reviewed the `low_data` list — it is the input to Phase F.

---

# PHASE C — Split & Materialize

## C0. Split once, for both stages

**Files:** `ml/src/agrisense_pd/data/split.py`, `ml/tests/test_split.py`.

**Contract**
- 80/10/10 train/val/test, seed 42, stratified on `(species, condition)`.
- **Constraint:** all rows sharing a `dup_group` receive the same split. Implement as: group by `dup_group` → assign groups to splits greedily to hit per-stratum targets → write `split` back to `master.csv`.
- Guarantee every `(species, condition)` with ≥ 10 images has at least one val and one test image; classes below that are flagged, not silently dropped.
- Writes `artifacts/split_report.md` with per-split counts and the realized ratios per stratum.
- Tests assert: no `dup_group` spans two splits; ratios within ±2%; identical output across two runs with the same seed.

**Accept when:** the dup-group test passes and realized ratios are within tolerance. This is the phase that decides whether your Phase E number means anything.

---

## C1/C2. Materialize the training trees

**Files:** `ml/src/agrisense_pd/data/materialize.py`.

**Contract**
- `--stage 1` builds `data/stage1_species/{train,val,test}/<species>/` — every image of a species together regardless of condition.
- `--stage 2` builds `data/stage2_disease/<species>/{train,val,test}/<condition>/` for each species with ≥ 2 conditions.
- Entries are **symlinks** into `data/raw/`. Falls back to hardlinks, then copy, if symlinks are unavailable — and says which mode it used.
- Idempotent: an existing correct tree is left alone; `--force` rebuilds.
- Prints per-split, per-class counts on completion and asserts they match `master.csv`.
- Must run in well under a minute for the full corpus. If it does not, it is copying when it should be linking.

**Accept when:** both trees exist, counts match the manifest exactly, and `data/stage2_disease/` contains exactly the non-`single_condition` species.

---

# PHASE D — Train (the two models)

## D1. Stage 1 — species classifier

**Files:** `ml/configs/train_stage1.yaml`, `ml/src/agrisense_pd/train/callbacks.py`, `ml/src/agrisense_pd/train/stage1.py`.

**Contract**
- Ultralytics YOLO11 classification. **Base: `yolo11s-cls.pt`**, not `n` — Stage 1 sees the most data, carries the whole pipeline, and `s` still trains comfortably in a free-tier session. Overridable in the YAML.
- Starting hyperparameters (tune only if a run tells you to):
  ```yaml
  model: yolo11s-cls.pt
  imgsz: 224
  epochs: 30
  batch: 128          # drop to 64 if CUDA OOM on T4
  workers: 8
  optimizer: auto
  cos_lr: true
  patience: 10
  amp: true
  cache: false        # symlink tree + local SSD is fast enough; caching 100k imgs will OOM RAM
  augment: default ultralytics cls aug + hsv/flip; no vertical flip
  project: <local>/runs/stage1
  name: species
  ```
- `callbacks.py` registers an `on_fit_epoch_end` hook that copies `last.pt` + `best.pt` to `Drive/models/stage1/` every N epochs (default 2) via `drive_io.sync_checkpoint`. This is what makes a disconnect survivable.
- **Resume:** on start, if `Drive/models/stage1/last.pt` exists, pull it local and pass `resume=True`. Re-running the cell after a disconnect must continue, not restart.
- After training: run validation on **both** `val` and the held-out `test` split; write `artifacts/stage1_report.md` with top-1, top-5, macro-precision/recall/F1, per-class accuracy, and the 10 most-confused species pairs. Save the confusion matrix PNG to `artifacts/`.
- Copy final `best.pt` to `Drive/models/stage1/best.pt`.

**Accept when:** test-split top-1 ≥ 0.95 (species on clean lab images is an easy task — anything materially lower means a data or label problem upstream, not a model problem). Checkpoints are on Drive. Confusion pairs are botanically plausible (tomato/potato confusion is normal; tomato/corn is a bug).

---

## D2. Stage 2 — per-species disease classifiers

**Files:** `ml/configs/train_stage2.yaml`, `ml/src/agrisense_pd/train/resume_state.py`, `ml/src/agrisense_pd/train/stage2.py`.

**Contract**
- Loops species in `data/stage2_disease/`, training one model each into `Drive/models/stage2/<species>/`.
- Base `yolo11n-cls.pt`, imgsz 224, epochs 30, batch 64, patience 8 — per-species datasets are small; `n` is the right size and keeps the total loop inside a couple of sessions.
- **State machine** — `state/stage2_progress.json`:
  ```json
  {"tomato": {"status": "done", "classes": 10, "val_top1": 0.981, "test_top1": 0.974,
              "run_dir": "...", "finished_at": "..."},
   "corn":   {"status": "in_progress", "epochs_done": 12}}
  ```
  Statuses: `pending` | `in_progress` | `done` | `failed`. On start the loop skips `done`, resumes `in_progress` from `last.pt`, and retries `failed` only with `--retry-failed`.
- `--species <name>` trains exactly one; `--max-minutes <n>` stops cleanly between species before the session dies, leaving valid state.
- Per-species checkpoint sync to Drive, same callback as D1.
- On completion, writes `artifacts/stage2_report.md`: a table of species | #classes | train size | val top-1 | test top-1 | flagged, sorted worst-first. Species under 0.85 test top-1 are flagged as Phase F candidates.
- Each species run also writes its `condition` class order to `Drive/models/stage2/<species>/classes.json`, read from `condition_index.json` — not inferred from folder order.

**Accept when:** every non-`single_condition` species is `done`, the summary table is written, and re-running the cell is a no-op. Expect a spread — low-data species from B3 will be at the bottom, and that is the point of the table.

---

# PHASE E — Real-world evaluation

## E0. End-to-end on our own held-out test split

**Files:** `ml/src/agrisense_pd/eval/pipeline.py`, `ml/src/agrisense_pd/eval/evaluate_holdout.py`.

Not in the original roadmap, added because you need a *clean* end-to-end baseline before interpreting the PlantDoc number — otherwise you can't tell whether a drop is "real-world hardness" or "the two stages don't compose".

**Contract**
- `pipeline.py` — the single shared implementation of two-stage inference, used by E0, E1 and (mirrored in ONNX) by the API. Signature:
  ```python
  predict(image) -> {"species", "species_confidence",
                     "condition", "condition_confidence",
                     "joint_confidence",            # product of the two
                     "species_topk", "notes"}
  ```
  Loads Stage 1, routes to the matching Stage 2 model, handles `single_condition` species by returning the constant condition, and handles "no Stage 2 model found" explicitly rather than crashing.
- `evaluate_holdout.py` runs it over `split == "test"` and reports: species top-1, condition accuracy **given correct species**, and strict end-to-end (both correct).

**Accept when:** end-to-end ≈ species-acc × conditional-acc. A large gap means a routing bug in `pipeline.py`, not a model weakness.

---

## E1. PlantDoc generalization test

**Files:** `ml/src/agrisense_pd/eval/plantdoc_eval.py`, `ml/src/agrisense_pd/eval/report.py`.

**Contract**
- PlantDoc labels go through the **same** `taxonomy.py` normalizer. Its class vocabulary only partially overlaps ours: evaluate **only** on the intersection, and report the excluded classes explicitly. Scoring a model on a species it was never trained on is not a generalization result, it's noise.
- Report, side by side with E0's numbers: species top-1, conditional condition accuracy, strict end-to-end — and additionally split the results by **single-object vs multi-object images** (using the XML box counts). That split is the actual decision input for E2.
- Also report a calibration line: mean confidence on correct vs incorrect predictions. If the model is confidently wrong on real photos, the API needs a confidence floor before it shows a diagnosis to a user.
- Writes `artifacts/plantdoc_report.md` plus a `artifacts/comparison.md` table: clean-val / clean-test / plantdoc, one row per metric.

**Accept when:** the report exists and the drop is quantified. **Expect a large drop** — clean-lab top-1 in the high 90s and PlantDoc in the 40–70% range is the normal, documented outcome for PlantVillage-trained models. That number is the honest answer to "will this work in my app", and it is the number to put in front of users, not the validation figure.

---

## E2. Leaf detector pre-step — conditional

**Trigger:** only build this if E1 shows multi-object accuracy materially below single-object accuracy (guide: > 10 points). Otherwise skip and record why in `artifacts/comparison.md`.

**Files:** `ml/src/agrisense_pd/detect/plantdoc_to_yolo.py`, `ml/src/agrisense_pd/detect/train_detector.py`.

**Contract**
- Converts PlantDoc Pascal VOC XML → YOLO detection format, collapsing all 28 classes into a **single `leaf` class** — you need "where are the leaves", not "which disease" at this stage; the classifiers answer that.
- Splits PlantDoc's own data for the detector (its train split only), keeping the E1 evaluation images out of detector training.
- Trains `yolo11n.pt`, imgsz 640, epochs ~50, with the same Drive checkpointing.
- Re-runs E1 with detection enabled: crop each box, classify each crop, aggregate per image (report highest-confidence crop, plus all crops). Writes a before/after table.

**Accept when:** the before/after table shows the change. **If detection does not improve end-to-end accuracy, keep it off** — it doubles latency and adds a failure mode. Record the decision either way.

---

# PHASE F — Fix weak spots

**Files:** extend `ml/configs/train_stage2.yaml` with a per-species `overrides:` block; add `--augment-profile` to `stage2.py`. No new modules.

**Contract**
- Targets are the flagged species from D2 (< 0.85) and the `low_data` combos from B3.
- Aggressive profile: rotation ±30°, horizontal flip, brightness/contrast/saturation jitter, random resized crop (scale 0.6–1.0), slight blur, random erasing. Optionally class-weighted loss for imbalanced conditions.
- Retrained models go to `models/stage2/<species>__aug/` — **do not overwrite the baseline** until the comparison says the new one is better.
- Writes `artifacts/phase_f_<species>.md`: baseline vs augmented on val, our test split, and PlantDoc.
- **Promotion rule:** a retrained model replaces the baseline only if it improves on the *PlantDoc* number (or, where PlantDoc lacks that species, on our test split) — not on val. Val improvement alone is how you fool yourself.

**Accept when:** each targeted species has a comparison file and an explicit promote/reject decision recorded.

---

# PHASE G — Export

**Files:** `ml/src/agrisense_pd/export/to_onnx.py`, `verify_onnx.py`, `registry.py`.

**Contract**
- Exports Stage 1, every promoted Stage 2 model, and the detector if E2 kept it. Opset 12+, dynamic batch axis, `simplify=True`. Output to `Drive/exported/` mirroring the model tree.
- `verify_onnx.py` — for each model, run ≥ 20 test-split images through both PyTorch and ONNXRuntime: **argmax must match on 100%**, and max logit delta < 1e-3. Any mismatch fails the phase loudly.
- `registry.py` writes `exported/registry.json` — the contract between training and serving:
  ```json
  {
    "version": "1.0.0",
    "created_at": "...",
    "input": {"size": 224, "layout": "NCHW", "normalize": "0-1", "mean": [...], "std": [...]},
    "stage1": {"path": "stage1/species.onnx", "classes": ["apple", "corn", ...]},
    "stage2": {
      "tomato": {"path": "stage2/tomato.onnx", "classes": ["healthy", "late_blight", ...]},
      "raspberry": {"type": "constant", "condition": "healthy"}
    },
    "detector": {"enabled": false},
    "metrics": {"clean_test_e2e": 0.0, "plantdoc_e2e": 0.0},
    "thresholds": {"min_species_confidence": 0.0, "min_condition_confidence": 0.0}
  }
  ```
  The preprocessing block is not optional — a mismatch between training normalization and API normalization is the single most common cause of "works in Colab, garbage in production".
- Then **download `exported/` out of Drive into this repo's `serving/models/`** (gitignored — ship via release artifact or object storage, not git).

**Accept when:** every ONNX file verifies, `registry.json` validates against the schema, and its metrics fields carry the real Phase E numbers.

---

# PHASE H — Serving API

**Files:** `serving/app.py`, `pipeline_runtime.py`, `auth.py`, `requirements.txt`, `Dockerfile`, `.env.example`.

**Contract**
- FastAPI, `POST /predict`, multipart image upload. Returns:
  ```json
  {"species": "tomato", "species_confidence": 0.97,
   "condition": "late_blight", "condition_confidence": 0.88,
   "joint_confidence": 0.85, "low_confidence": false,
   "model_version": "1.0.0", "inference_ms": 142}
  ```
- `low_confidence: true` when either confidence is below the registry thresholds — the app should then show "unclear photo, try again" rather than a wrong diagnosis stated with certainty. Given the E1 numbers, this matters.
- Auth: `X-API-Key` header checked against `API_KEY` env var using `secrets.compare_digest` (constant-time — a plain `==` leaks the key by timing). Missing/wrong → 401. No key in the code, no key in git.
- `GET /health` (unauthenticated, for the platform's probe) and `GET /version` (returns registry version + metrics).
- Guards: max upload size (~10 MB), content-type allowlist, EXIF-orientation correction, simple per-key rate limit.
- `pipeline_runtime.py` mirrors `eval/pipeline.py` exactly but on ONNXRuntime, driven entirely by `registry.json`. Models load once at startup, not per request.
- Dockerfile: `python:3.11-slim`, CPU `onnxruntime`, non-root user, `uvicorn` with 2 workers.
- **Separate service from `backend/`** — do not merge it into the Supabase automation server.

**Accept when:** local curl tests pass for (a) no key → 401, (b) wrong key → 401, (c) correct key + real leaf photo → sensible JSON, (d) correct key + a non-plant photo → `low_confidence: true`.

---

# PHASE I — Deploy

**Files:** `serving/DEPLOY.md`, plus the platform config file once you pick a platform.

Pick one — I'd default to **Google Cloud Run** here: scales to zero (free-tier friendly for a personal app), takes the Dockerfile as-is, has proper secret management, and won't cold-start-kill a ~200 MB model set the way the smallest Render/Railway tiers can.

**Contract:** exact commands (build, push, deploy), secret handling via Secret Manager (never `--set-env-vars` for the key — it lands in deploy logs), memory/CPU sizing for ONNX CPU inference, where to read the HTTPS URL, and a smoke-test curl. Includes generating a strong key (`python -c "import secrets;print(secrets.token_urlsafe(32))"`) and a rotation note.

**Accept when:** the live URL answers `/health`, rejects a bad key, and returns a prediction with the good one.

---

# PHASE J — Client integration

Both clients already exist in this repo.

- **J1 — `mobile_app/`** (Expo/React Native). Add a "Diagnose plant" screen: `expo-image-picker` for camera/gallery, upload to `/predict`, render species + condition + confidence, and a distinct UI state for `low_confidence`. **The API key must not ship in the app bundle** — anything in the RN bundle is extractable. Proxy through Supabase Edge Functions or the existing backend, which holds the key server-side.
- **J2 — `web_dashboard/`** (vanilla HTML/CSS/JS). Add an upload card with drag-drop, preview, loading state, and result display. Same rule: the browser must never see the API key — call it through a server-side proxy route.

**Accept when:** both clients return correct results end-to-end on ~5 real phone photos, and the key is not present in the shipped bundle or in any browser network request.

---

## Notebook layout — `AgriSense_PlantDisease_Colab.ipynb`

One cell per step, each independently re-runnable after a reconnect:

| # | Cell | Phase |
|---|---|---|
| 1 | Mount Drive, clone/pull repo, `pip install -r requirements-colab.txt` | A1 |
| 2 | `sys.path` setup, `env_report()` — GPU/VRAM/disk assertions | A1 |
| 3 | `ensure_dirs()` | A1 |
| 4 | Kaggle credential setup | A2 |
| 5 | `download.py` (all three) | A2 |
| 6 | `inspect_structure.py` → display reports | A3 |
| 7 | `taxonomy.py --build` → print review list | B1 |
| 8 | **(manual)** edit `taxonomy_overrides.yaml`, re-run cell 7 | B1 |
| 9 | `clean.py` | B2 |
| 10 | `build_manifest.py` → display class report | B3 |
| 11 | `split.py` → display split report | C0 |
| 12 | `materialize.py --stage 1 --stage 2` | C1/C2 |
| 13 | `train/stage1.py` (re-run to resume) | D1 |
| 14 | `train/stage2.py --max-minutes 300` (re-run to continue) | D2 |
| 15 | `eval/evaluate_holdout.py` | E0 |
| 16 | `eval/plantdoc_eval.py` → comparison table | E1 |
| 17 | **(conditional)** detector build + re-eval | E2 |
| 18 | **(conditional)** Phase F retrains | F |
| 19 | `export/to_onnx.py` + `verify_onnx.py` + `registry.py` | G |
| 20 | Zip `exported/` for download | G |

**Session-death protocol** (put this in a markdown cell at the top): reconnect → run cells 1–3 → run cells 5 and 12 (cheap, rebuild local disk from Drive) → re-run whichever training cell you were on. It resumes.

---

## Rough time budget (free T4)

| Phase | Wall clock |
|---|---|
| A (download + extract) | 30–60 min, once |
| B (hash ~100k images, CPU-bound) | 30–50 min |
| C | < 2 min |
| D1 Stage 1 | 1.5–3 h |
| D2 Stage 2 (~20–30 species) | 3–6 h — plan on 2 sessions |
| E | 30–60 min |
| F | variable |
| G | 15 min |

Total ≈ 2–3 free-tier sessions if nothing goes wrong. The resume machinery in D1/D2 is what makes that survivable.

---

## Open decisions for you (answer before Phase D)

1. **Stage 1 base model** — spec says `yolo11s-cls`. Say so if you want `n` (faster, ~1 pt less accurate).
2. **Deploy target** — spec assumes Cloud Run. Confirm or change.
3. **Digipathos** — RESOLVED: confirmed dead (server refuses connections). Replaced by PlantWild in `training_datasets`. If Embrapa's service ever comes back, flip `digipathos`'s `kind` in `sources.yaml` back to `digipathos_pip` and add it to `training_datasets`.
4. **Low-confidence threshold** — set after E1, since it depends on the real calibration numbers.
5. **PlantWild license (CC BY-NC-ND 4.0)** — accepted for this personal-project model. Revisit before any commercial use of the trained weights.
