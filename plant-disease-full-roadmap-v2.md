# Plant Species + Disease Recognition — Full Build Roadmap (Multi-Dataset)

**Tools:** Google Colab (training, free GPU) + Claude Code (writing/running all scripts)
**Datasets:** PlantVillage (main training) + Digipathos (main training, broader species/disease coverage) + PlantDoc (real-world test only — NOT used for training)
**Skip:** "New Plant Diseases Dataset" — it's PlantVillage with augmentation applied, not new data. Using it alongside PlantVillage causes data leakage (same underlying photos in train and test), making accuracy numbers meaningless.
**End goal:** A deployed API with an API key, feeding a "upload photo → get diagnosis" feature in your personal app + website.

Run each stage's prompt in Claude Code (inside Colab or connected to your Colab/Drive), check the result against the "Check" note, then move to the next.

---

## PHASE A — Setup & Data Collection

### A1. Environment setup (Colab)
```
Write a Colab notebook cell that mounts Google Drive, installs
ultralytics, torch, scikit-learn, and pandas, and creates this folder
structure inside Drive: data/raw/plantvillage, data/raw/digipathos,
data/raw/plantdoc, data/clean, data/stage1_species, data/stage2_disease,
models, scripts. Confirm GPU is available.
```
**Check:** GPU detected, folders exist in Drive (so they persist across sessions).

### A2. Download and place datasets
```
Write a script/instructions to download PlantVillage from Kaggle
(mohitsingh1804/plantvillage), Digipathos from its official DOI page,
and PlantDoc from its GitHub repo, and extract each into their
respective data/raw/<name> folder. If Kaggle API credentials are needed,
tell me exactly what file to upload and where.
```
**Check:** All three datasets extracted into their raw folders, no leftover zip/archive files.

### A3. Inspect each dataset's structure
```
Write a script that scans data/raw/plantvillage, data/raw/digipathos,
and data/raw/plantdoc separately, and prints: folder/label structure,
number of classes, naming convention used for each (e.g.
"Species___Condition" vs numeric IDs vs XML annotations), and image
counts per class. I need to see how each dataset differs before merging
them.
```
**Check:** You should now clearly see PlantVillage's `Species___Condition` folders, Digipathos's own naming, and PlantDoc's image+XML/annotation structure (since it has bounding boxes).

---

## PHASE B — Cleaning & Label Harmonization

### B1. Build one consistent taxonomy
```
Based on the label structures you found in A3, write a mapping table
(as a CSV or Python dict) that maps every class name from PlantVillage
and Digipathos into one consistent taxonomy: a "species" field and a
"condition" field (condition = disease name or "healthy"). Flag any
labels that don't clearly map to an existing species/condition so I can
review them manually.
```
**Check:** Review the flagged/ambiguous labels yourself — some naming mismatches need a human judgment call (e.g. is "Tomato_Yellow_Leaf_Curl_Virus" the same as "Tomato___Yellow_Leaf_Curl_Virus"?).

### B2. Clean and deduplicate
```
Write a script that checks data/raw/plantvillage and data/raw/digipathos
for corrupted images (unreadable files), exact duplicate images (hash-based
check), and extremely small/low-resolution images below a usable
threshold. Remove or quarantine these into a data/clean/rejected folder
with a log explaining why each was flagged.
```
**Check:** Review the rejected folder count — if it's a large chunk of the dataset, investigate before proceeding.

### B3. Apply the taxonomy and merge
```
Using the mapping table from B1, copy all cleaned images from
PlantVillage and Digipathos into data/clean/merged/<species>/<condition>/,
renaming/relabeling according to the unified taxonomy. Print final class
counts (species and species+condition combinations) after merging.
```
**Check:** This merged folder is now your real, deduplicated, unified dataset — this is what training will use.

---

## PHASE C — Reorganize for Two-Stage Training

### C1. Stage 1 folders (species only)
```
From data/clean/merged, build data/stage1_species/ by grouping all
images of the same species together regardless of condition. Split
80/10/10 into train/val/test with a fixed random seed. Print counts per
split per species.
```

### C2. Stage 2 folders (disease per species)
```
From data/clean/merged, build data/stage2_disease/<species>/ folders,
each containing subfolders per condition (disease or healthy) for that
species only. Split each species' data 80/10/10 into train/val/test.
Print per-species class counts.
```
**Check:** Flag any species/condition combo with fewer than ~150–200 images — these are augmentation candidates later.

---

## PHASE D — Train

### D1. Train Stage 1 (species model)
```
Train a YOLO11 classification model (yolo11n-cls.pt base) on
data/stage1_species using ultralytics, 30 epochs, image size 224. Save
to models/stage1_species. After training, print validation accuracy,
precision, and confusion matrix summary. Save checkpoints to Drive
periodically in case the Colab session disconnects.
```

### D2. Train Stage 2 (disease models, one per species)
```
Loop through each species folder in data/stage2_disease and train a
separate YOLO11-cls model for disease classification, saving each to
models/stage2_disease/<species>/. Use 30 epochs per species. Print a
summary table: species, number of classes, validation accuracy. Save
checkpoints to Drive periodically.
```
**Check:** Note any species with weak accuracy — likely low-data species from Phase C.

---

## PHASE E — Test for Real-World Accuracy (PlantDoc)

### E1. Real-world generalization test
```
Using data/raw/plantdoc (never used in training), write a test script
that runs each PlantDoc image through the Stage 1 + Stage 2 pipeline
and compares predictions against PlantDoc's ground-truth labels. Report
accuracy separately from the clean-dataset validation accuracy in D1/D2,
since PlantDoc has real backgrounds and multiple leaves per photo.
```
**Check:** Expect this number to be meaningfully lower than your clean validation accuracy — that's normal and expected; it tells you how much your model struggles with real-world photos like the ones your app's users will actually upload.

### E2. Decide if a detection pre-step is needed
```
Based on E1's results, if accuracy on PlantDoc images with multiple
leaves/cluttered backgrounds is poor, write a script that uses PlantDoc's
bounding box annotations to train a lightweight YOLO11 detection model
that crops individual leaves out of a photo BEFORE passing them to the
Stage 1/2 classifiers. Test whether this improves end-to-end accuracy
on PlantDoc.
```
**Check:** Only do this if E1 shows real degradation on multi-leaf/cluttered photos — since your dataset was framed around single cropped leaf inputs, this may not be necessary, but it's the fix if it is.

---

## PHASE F — Fix Weak Spots

```
For [species/condition] which had low accuracy in D2 or E1, add data
augmentation (rotation, flip, brightness/contrast jitter, zoom, slight
background variation) to its training set and retrain. Compare new
accuracy against the original on both validation and PlantDoc test sets.
```
**Check:** Re-run E1 after any fix to confirm real-world accuracy actually improved, not just validation accuracy.

---

## PHASE G — Export for Deployment

```
Export the final Stage 1 species model and all Stage 2 disease models
(and the detection pre-step model if built in E2) to ONNX format. Save
to models/exported, organized the same way as before. Verify each
exported model loads correctly and produces the same prediction as the
original on a test image.
```
**Check:** Confirm ONNX files exist and match original model predictions.

---

## PHASE H — Build the Serving API

```
Build a FastAPI app with:
1. A POST /predict endpoint that accepts an image upload, runs it
   through the (optional) detection model to crop leaves, then Stage 1
   species model, then the matching Stage 2 disease model, and returns
   JSON: {"species": ..., "condition": ..., "species_confidence": ...,
   "condition_confidence": ...}.
2. API key authentication — require a header like "X-API-Key" on every
   request, checked against a key stored in an environment variable, and
   reject requests without a valid key with a 401 error.
Include a Dockerfile.
```
**Check:** Test locally with curl, including a request with a missing/wrong API key (should get rejected) and one with the correct key (should get a prediction).

---

## PHASE I — Deploy & Get Your API Key

```
Write deployment instructions and config files to deploy this FastAPI
app to [Render / Railway / Google Cloud Run — tell me which you want],
including how to securely set the API_KEY environment variable on that
platform (not hardcoded in the repo). Give me the exact commands and
steps, and tell me where to find my live HTTPS endpoint URL once
deployed.
```
**Check:** Once deployed, generate a strong random API key yourself (or ask Claude Code to generate one), set it as the platform's environment variable, and test the live endpoint with that key before moving on. Treat this key like a password — don't commit it to a public GitHub repo.

---

## PHASE J — Connect to Your App and Website

### J1. Mobile/app client
```
Write client code for my [Android / iOS / Flutter — specify] app that
lets a user upload/take a photo, sends it to my deployed /predict
endpoint with the API key in the header, and displays the returned
species + condition + confidence in the UI.
```

### J2. Website upload feature
```
Build a simple web page (HTML/CSS/JS or React, tell me which) with a
photo upload button that sends the image to my deployed /predict
endpoint with the API key, shows a loading state while waiting, and
displays the species + condition result once returned.
```
**Check:** Test end-to-end from both the app and the website with a handful of real photos before considering this live/finished.

---

## Quick reference: full order of operations
A. Setup + collect 3 datasets → B. Clean + unify labels → C. Reorganize into stage1/stage2 folders → D. Train both stages → E. Test on real-world PlantDoc photos (add detection step if needed) → F. Fix weak spots → G. Export → H. Build API with key auth → I. Deploy + secure your API key → J. Wire into app and website

Go stage by stage — don't skip Phase E, since it's the one that tells you whether your model will actually work on the messy photos real users upload, not just clean lab images.
