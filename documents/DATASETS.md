# AgriSense AI — Datasets

Every dataset the plant-disease pipeline is configured to use. Source of truth is
`ml/configs/sources.yaml` (acquisition) and `ml/configs/paths.yaml` (which ones are
actually wired into training vs evaluation).

> **Status note.** These are the datasets the pipeline is *configured* for. The
> two-stage model has not been trained to completion yet, so the deployed Plant Scan
> currently runs on Gemini vision instead — see "Current model status" at the bottom.
> Nothing in this file is a claimed result.

---

## Training datasets

Set in `paths.yaml → training_datasets`.

### 1. PlantVillage
| | |
|---|---|
| Source | Kaggle — `mohitsingh1804/plantvillage` |
| Size | ~800 MB |
| Conditions | Lab (controlled background, single detached leaf) |
| Layout | Folder-per-class, `Species___Condition` |

The standard academic benchmark for leaf disease classification. Clean and well
labelled, but every image is a detached leaf on a plain background — models trained on
it alone score in the high 90s on their own validation split and then fall over on real
field photos. That gap is the reason for the next three datasets.

### 2. PlantWild
| | |
|---|---|
| Source | Hugging Face — `uqtwei2/PlantWild` |
| Size | ~4.4 GB, **30,030 images**, 146 classes (v1: 18,542 / 89 · v2: 11,488 / 115) |
| Conditions | In the wild, crowdsourced |
| License | CC BY-NC-ND 4.0 (non-commercial, no derivatives) |

Chosen specifically to attack the PlantVillage generalisation gap with real-world
imagery rather than just more lab data.

**Contamination risk, and how it's handled:** PlantWild images were crowdsourced from
Google/Ecosia/Baidu image search — the same route PlantDoc's images came from. So
`clean.py` cross-checks every PlantWild image against PlantDoc's perceptual hashes and
rejects near-duplicates (`reason: plantdoc_overlap`). Without this the real-world
evaluation number would be contaminated by train/test overlap and therefore meaningless.

### 3. Cassava Leaf Disease
| | |
|---|---|
| Source | Kaggle — `nirmalsankalana/cassava-leaf-disease-classification` |
| Size | ~5.8 GB, **21,367 images** |
| Classes | Bacterial Blight, Brown Streak, Green Mottle, Mosaic Disease, healthy |
| Conditions | Real field photos |

Crowdsourced from Ugandan farmers, annotated by NaCRRI and the Makerere University AI
lab. Adds a staple crop under genuine field conditions.

*Mirror choice matters here:* `gauravduttakiit`'s mirror is the raw competition format
(flat `train_images/` + a CSV label file), which this pipeline's folder-per-class
scanner cannot read. `nirmalsankalana`'s mirror is pre-organised into class folders.

### 4. Rice Leaf Disease
| | |
|---|---|
| Source | Kaggle — `nirmalsankalana/rice-leaf-disease-image` |
| Size | ~500 MB, **5,932 images** |
| Classes | Bacterial Blight (1584), Blast (1440), Brown Spot (1600), Tungro (1308) |

Rice has **no PlantVillage coverage at all**, so this is the cheapest way to add a major
staple. Note: no `healthy` class, so rice has no healthy condition until one is sourced
elsewhere.

**Training total: roughly 57,000+ images before cleaning and deduplication.**

---

## Evaluation dataset (never trained on)

Set in `paths.yaml → eval_datasets`.

### PlantDoc
| | |
|---|---|
| Source | GitHub — `pratikkayal/PlantDoc-Object-Detection-Dataset` |
| Size | ~1.7 GB |
| Format | Images + Pascal VOC XML bounding boxes |

Held out entirely from training. This is the honest real-world number: models that score
in the high 90s on PlantVillage validation have historically scored 40–70% on PlantDoc.
The object-detection variant is used (not the classification-folder variant) because the
detection phase needs the boxes.

---

## Excluded: Digipathos

Listed in `sources.yaml` with `kind: unavailable`, deliberately not deleted.

Embrapa's host actively refuses connections (`ECONNREFUSED 200.0.70.2:443`), reproduced
both locally and from a Colab session with unrestricted internet. Every known downloader
hits the same dead endpoint, so no package swap fixes it. PlantWild replaced it. The
entry is kept so it can be re-enabled if the service ever returns.

---

## Pipeline stages

```
download  ─► inspect_structure ─► taxonomy ─► clean ─► build_manifest ─► split
   │              │                   │          │            │            │
 sources      real folder        unify class  dedupe +    train/val/    stratified,
 .yaml        convention         names        reject      test rows     seed 42
                                              overlaps
                          │
                          ▼
        Stage 1: species classifier  (yolo11s-cls, 224px, 30 epochs)
                          │
                          ▼
        Stage 2: per-species disease classifier, routed by registry.json
                 (species with one condition short-circuit to a constant)
                          │
                          ▼
              ONNX export ─► serving/app.py ─► /api/plant/predict
```

Adding a dataset means adding it to `sources.yaml` + `paths.yaml`; nothing else
hardcodes dataset names.

**Preprocessing** (`serving/pipeline_runtime.py`): EXIF transpose → RGB → resize to
224×224 bilinear → `/255.0` → HWC→CHW → normalise. Size, mean and std all come from
`registry.json` rather than being hardcoded, so the serving side can never drift from
what the model was trained with.

**Reproducibility:** `seed: 42` throughout (`paths.yaml`, `train_stage1.yaml`).

---

## Current model status

The two-stage classifier has **not** been trained to completion — there is no `.onnx`
artifact in the repo, and `serving/models/` is gitignored and empty.

The deployed Plant Scan therefore runs on **Gemini vision** with a strict JSON response
schema, which returns species, condition, severity, affected area %, symptoms, cause,
treatment and prevention. `backend/main.py` chooses its inference source from the
environment: set `PLANT_API_URL` + `PLANT_API_KEY` and it proxies to the trained model
service instead — no code change required.

Training this pipeline requires downloading ~13 GB across four datasets and a GPU
session; see `ml/notebooks/AgriSense_PlantDisease_Colab.ipynb`.
