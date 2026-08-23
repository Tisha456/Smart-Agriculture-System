# AgriSense Plant Disease — Step-by-Step Execution Guide

Everything you need to do, in order, from right now to a working
"upload photo → get diagnosis" feature in your app.

**Reference docs:** `plant-disease-implementation-plan.md` (the spec —
explains *why* each thing is built this way) and
`plant-disease-full-roadmap-v2.md` (the original roadmap). `ml/README.md`
has the short version of this file.

**Total time:** roughly 2–3 Colab sessions of training (~8–12 GPU hours
spread across days), plus ~1–2 hours of your own hands-on work.

---

## Legend

| Symbol | Meaning |
|---|---|
| 🖥️ | You do this on your Windows PC |
| ☁️ | You do this in Google Colab |
| ⏱️ | Long-running — start it and walk away |
| ⚠️ | A decision or check that needs your eyes |
| ✅ | How you know the step worked |

---

# PART 0 — Before you open Colab (🖥️ your PC, ~10 min)

## Step 0.1 — Run the tests once locally

Confirms the pipeline logic works before you burn GPU hours on it.

```powershell
cd C:\Users\ankul\OneDrive\Desktop\MAJRO\AgriSense\ml
python -m pip install pytest pyyaml
python -m pytest tests -v
```

✅ **Expect:** `20 passed`. If anything fails, stop and fix it before Colab.

---

## Step 0.2 — Commit and push everything to GitHub

**This is mandatory.** The Colab notebook's first cell clones your repo —
if your code isn't pushed, Colab gets an old copy and nothing works.

```powershell
cd C:\Users\ankul\OneDrive\Desktop\MAJRO\AgriSense
git status
git add .
git commit -m "Add plant disease ML pipeline, serving API, and mobile scan feature"
git push origin main
```

⚠️ **Before pushing, check `git status` output** — make sure no `.env`
file is being committed. `.gitignore` already blocks them, but look anyway.

✅ **Expect:** push succeeds, and `ml/`, `serving/`, `STEPS.md`,
`plant-disease-implementation-plan.md` all appear on
https://github.com/Tisha456/Smart-Agriculture-System

⚠️ **If the repo is private:** Colab's `git clone` will fail at Cell 1.
Either make it public, or replace the clone line in Cell 1 with a token URL:
`https://<your-github-token>@github.com/Tisha456/Smart-Agriculture-System.git`

---

## Step 0.3 — Get your Kaggle API token

PlantVillage downloads through Kaggle's API.

1. Go to https://www.kaggle.com/settings/account
2. Scroll to the **API** section → click **Create New Token**
3. A file called `kaggle.json` downloads. **Keep it handy** — you upload
   it to Colab in Step 2.1.

✅ **Expect:** `kaggle.json` sitting in your Downloads folder.

---

## Step 0.4 — Check your Google Drive space

The pipeline stores ~5–8 GB on Drive (dataset archives + model checkpoints).

1. Go to https://drive.google.com/settings/storage
2. Make sure you have **at least 10 GB free**.

✅ **Expect:** ≥10 GB free. If not, clear space now — running out
mid-training corrupts checkpoint syncs.

---

# PART 1 — Colab setup (☁️, ~5 min)

## Step 1.1 — Open the notebook in Colab

**Easiest route:**
1. Go to https://colab.research.google.com
2. **File → Open notebook → GitHub** tab
3. Paste: `Tisha456/Smart-Agriculture-System`
4. Select `ml/notebooks/AgriSense_PlantDisease_Colab.ipynb`

**Alternative:** upload the `.ipynb` file directly from
`ml/notebooks/` via **File → Upload notebook**.

---

## Step 1.2 — Turn on the free GPU ⚠️

**This is the step people forget.** Without it, training silently runs on
CPU and takes days instead of hours (the code hard-fails to prevent this,
but do it up front).

1. Menu: **Runtime → Change runtime type**
2. **Hardware accelerator** → select **T4 GPU**
3. Click **Save**

✅ **Expect:** the notebook reconnects with a GPU attached.

---

## Step 1.3 — Run Cell 1 (clone + install)

Click into Cell 1 and press **Shift+Enter**.

✅ **Expect:** `Repo ready at /content/AgriSense`, and pip installs finish
without red errors. Takes ~2 minutes.

❌ **If clone fails:** see the private-repo note in Step 0.2.

---

## Step 1.4 — Run Cell 2 (mount Drive + GPU check)

✅ **Expect:**
- A popup asking you to authorize Google Drive → click through and allow it.
- Then printed output showing:
  - `CUDA available: True`
  - `GPU: Tesla T4` (or L4/A100 if you're lucky)
  - `VRAM: ~15-16 GB`
  - `Environment check passed.`

❌ **If it says "No GPU detected":** go back to Step 1.2. Do not continue
without a GPU.

---

## Step 1.5 — Run Cell 3 (create folders)

✅ **Expect:** prints your Drive root
(`/content/drive/MyDrive/AgriSense_PlantDisease`) and local root. A new
`AgriSense_PlantDisease` folder now exists in your Google Drive.

---

# PART 2 — Get the datasets (☁️, ~30–60 min ⏱️)

## Step 2.1 — Run Cell 4 (upload Kaggle token) ⚠️ manual

✅ **Expect:** a **"Choose Files"** button appears. Click it, select the
`kaggle.json` from Step 0.3, and wait for `Saved to /root/.kaggle/kaggle.json`.

(If it prints "already present, skipping upload" — you're fine, move on.)

---

## Step 2.2 — Run Cell 5 (download all three datasets) ⏱️

This downloads PlantVillage (~800 MB), Digipathos (~2 GB), and PlantDoc
(~1.7 GB). Takes 30–60 minutes.

✅ **Expect:** a final summary showing `OK` for all three datasets.

⚠️ **Digipathos is not a single zip file** — Embrapa serves it as ~90+
separate zip archives, one per (crop, disorder) class, through its own
API. Cell 5 first tries the community `digipathos` Python package to walk
that API automatically and extract each class into its own folder.

**If that automated path succeeds:** you'll see log lines like
`Digipathos: N classes downloaded OK` — nothing more to do, move on.

**If it fails** (the package wraps a specific, unofficial API from ~2019 —
it may be stale if Embrapa changed their repository since):

1. Read the printed message for the exact destination path.
2. Open https://www.digipathos-rep.cnptia.embrapa.br in a normal browser tab
   and browse/download whichever crop/disorder zip archives you want.
3. Extract each one into your Google Drive at:
   `MyDrive/AgriSense_PlantDisease/` → actually, extract locally in Colab
   at `/content/agrisense_pd/data/raw/digipathos/<crop>___<disorder>/`
   (use the same `Species___Condition`-style naming as PlantVillage — e.g.
   `Coffee___Leaf_Rust`), one folder per class, images directly inside.
4. No need to re-run Cell 5 — move straight to Cell 6.

💡 **Recommended shortcut if this gets fiddly:** proceed with PlantVillage
+ PlantDoc alone. You'll get fewer species and narrower coverage, but the
whole pipeline works unchanged. Given the automated path may be hit-or-miss
on a 2019-era API, don't sink more than ~15-20 minutes into manual
Digipathos wrangling before falling back to this.

---

## Step 2.3 — Run Cell 6 (inspect structure) ⚠️ read the output

✅ **Expect:** a printed summary for each dataset showing class counts and
naming convention.

⚠️ **Actually read this.** You should be able to say in one sentence how
each dataset names its classes (e.g. PlantVillage uses
`Species___Condition`). Detailed reports are saved to
`MyDrive/AgriSense_PlantDisease/artifacts/inspect_*.md` — open them in
Drive if you want the full per-class tables.

---

# PART 3 — Clean and organize the data (☁️, ~45–70 min ⏱️)

## Step 3.1 — Run Cell 7 (build taxonomy)

Maps every dataset's class names into one consistent
`(species, condition)` vocabulary.

✅ **Expect:** printed counts, ending with `NEEDS REVIEW: <number>`.

- **If `NEEDS REVIEW: 0`** → skip Step 3.2, go straight to Step 3.3. 🎉
- **If it's more than 0** → do Step 3.2 now.

---

## Step 3.2 — Fix unresolved labels ⚠️ manual, may need 2–3 rounds

Cell 7 prints every label it couldn't confidently resolve. It **never
guesses** — that's deliberate, since a wrong mapping silently poisons
training data.

1. In Colab's left sidebar, click the **📁 folder icon**
2. Navigate to `AgriSense/ml/configs/taxonomy_overrides.yaml`
3. Double-click to open it in the editor
4. For each reviewed label, add an entry. Change `overrides: []` to a real list:

```yaml
overrides:
  - src_dataset: digipathos
    src_label: "Milho_Mancha_Foliar_Cercospora"
    species: maize
    condition: gray_leaf_spot
  - src_dataset: digipathos
    src_label: "Cafe_Ferrugem"
    species: coffee
    condition: leaf_rust
```

**Rules:**
- `src_dataset` = `plantvillage` or `digipathos`
- `src_label` = copy the label **exactly** as Cell 7 printed it
- `species` / `condition` = lowercase `snake_case`, no spaces, no accents
- Use `healthy` as the condition for healthy-plant classes

5. **Ctrl+S** to save
6. **Re-run Cell 7**
7. Repeat until `NEEDS REVIEW: 0`

⚠️ **Also check the printed species/condition lists at the bottom.** If you
see near-duplicates like both `gray_spot` and `grey_spot`, two labels that
mean the same thing didn't merge — add an override to unify them.

---

## Step 3.3 — Run Cell 9 (clean & fingerprint) ⏱️ ~30–50 min

Checks every image for corruption, removes exact duplicates, and clusters
near-duplicates so they can't leak across your train/test split.

✅ **Expect:** a rejection summary. **Rejection rate should be under 5%.**

⚠️ **If it's over 5%,** it prints a warning. Stop and open
`MyDrive/AgriSense_PlantDisease/manifests/rejected.csv` — a high rate
almost always means a systematic problem (an unmapped label family, a
wrong folder level), not genuinely bad data.

💡 This checkpoints every 5000 images. If Colab disconnects here, just
re-run Cells 1–3 then Cell 9 — it resumes where it stopped.

---

## Step 3.4 — Run Cell 10 (build master manifest) ⚠️ read the output

✅ **Expect:** total clean image count, species count, and two lists:
- **Low-data combos** (<200 images) — note these, they're your Phase F candidates later
- **Single-condition species** — these correctly get no Stage 2 model

⚠️ **Sanity-check the numbers.** Total images should be roughly your raw
count minus rejects. Species names should look botanically sensible.

---

## Step 3.5 — Run Cell 11 (split train/val/test)

✅ **Expect:** `train: ~80%`, `val: ~10%`, `test: ~10%`.

This is the step that decides whether your final accuracy numbers mean
anything — it keeps near-duplicate image clusters entirely on one side of
the split.

---

## Step 3.6 — Run Cell 12 (materialize training folders)

✅ **Expect:** completes in **seconds**, prints `counts match manifest
exactly` for stage1 and each species.

⚠️ **If this takes minutes instead of seconds,** it fell back to copying
files instead of symlinking. Check the printed link mode — it still works,
just slower and uses more disk.

---

# PART 4 — TRAINING (☁️ — this is the GPU part) ⏱️⏱️

## 🔴 Read this before starting: the disconnect protocol

Colab free tier **will** disconnect you — idle timeout, the ~12 hour cap,
or random flakiness. **This is handled.** Checkpoints sync to your Drive
every 2 epochs.

**When you get disconnected, do exactly this:**

1. Reconnect the runtime (**Runtime → Reconnect**, or just reopen the notebook)
2. Re-run **Cell 1** (clone/pull + install)
3. Re-run **Cell 2** (mount Drive + GPU check)
4. Re-run **Cell 3** (folders)
5. Re-run **Cell 5** (download — instant, it sees the archives already on Drive)
6. Re-run **Cell 12** (materialize — seconds, rebuilds folders from the manifest)
7. Re-run whichever training cell you were on (**13** or **14**)

It **resumes from the last checkpoint**. It does not start over.

💡 **Tip to reduce disconnects:** keep the browser tab open and visible.
Don't let your PC sleep. Check back every 30–60 min.

---

## Step 4.1 — Run Cell 13: train Stage 1 (species model) ⏱️ 1.5–3 hours

This trains the model that identifies *which plant* is in the photo.

✅ **Expect:** ultralytics training output (a progress bar per epoch), then
a final `Stage 1 test top-1: 0.9xxx [OK]`.

⚠️ **Target: test top-1 ≥ 0.95.** Species identification on clean lab
images is an easy task — if you're materially below 0.95, something is
wrong with the data upstream, not the model. Check
`artifacts/stage1_report.md` on Drive and look at the most-confused pairs
(tomato/potato confusion is normal; tomato/corn means a labeling bug).

---

## Step 4.2 — Run Cell 14: train Stage 2 (disease models) ⏱️ 3–6 hours, likely 2+ sessions

This trains a **separate disease classifier for each species** — roughly
20–30 models. It will not finish in one free-tier session, and that's fine.

The cell is set to `--max-minutes 300` (5 hours): it stops **cleanly
between species** before your session dies, leaving valid resume state.

✅ **Expect:** per-species training output, then
`Done: N/M species.` and a list of remaining species.

**Just re-run Cell 14 (after Cells 1–3, 5, 12) in a new session** until it
says `Done: M/M` with nothing remaining. Already-trained species are
skipped instantly.

⚠️ **When it finishes,** open
`MyDrive/AgriSense_PlantDisease/artifacts/stage2_report.md`. It's sorted
worst-first. Note any species flagged with test top-1 < 0.85 — those are
your Phase F candidates in Part 6.

---

# PART 5 — Evaluation: the honest numbers (☁️, ~30–60 min)

## Step 5.1 — Run Cell 15 (clean held-out test)

Your baseline: how the two stages perform end-to-end on clean lab images
they've never seen.

✅ **Expect:** JSON with `species_top1`, `condition_acc_given_correct_species`,
and `strict_e2e`.

⚠️ **Sanity check:** `species_top1 × condition_acc` should ≈ `strict_e2e`.
A large gap means a routing bug, not a model weakness.

---

## Step 5.2 — Run Cell 16 (PlantDoc real-world test) ⚠️ the important one

This is the number that tells you what your app's users will actually
experience — real photos, real backgrounds, multiple leaves.

✅ **Expect:** overall / single-object / multi-object metric blocks.

🔴 **EXPECT A BIG DROP.** Clean validation in the high 90s and PlantDoc
end-to-end in the **40–70% range is the normal, documented outcome** for
PlantVillage-trained models. This is not a bug and not a failure — your
training data is lab-style single leaves on plain backgrounds, and
PlantDoc is messy real photos.

**This lower number is the one you should design your app around** — it's
why the API returns a `low_confidence` flag and the app shows "unclear
photo, try again" instead of confidently stating a wrong diagnosis.

📄 Read `artifacts/comparison.md` on Drive for the side-by-side table.

---

## Step 5.3 — Decide about the leaf detector ⚠️ decision point

Look at Cell 16's output and compare `multi_object` vs `single_object`
`strict_e2e`:

| Difference | Action |
|---|---|
| Less than ~10 points | **Skip Cell 17.** Go to Part 6. A detector you don't need only adds latency and a failure mode. |
| More than ~10 points | **Run Cell 17** (Phase E2). It trains a leaf detector that crops individual leaves before classifying. |

If you run Cell 17 (⏱️ ~1–2 hours), it prints an explicit
**keep it / turn it off** decision at the end based on measured
before/after accuracy. Trust that decision.

---

# PART 6 — Fix weak species (☁️, optional, ⏱️ varies)

**Skip this entirely if** every species in `stage2_report.md` is above
0.85 test top-1 and you're happy with the PlantDoc number.

## Step 6.1 — Add an override for the weak species

1. Open `AgriSense/ml/configs/train_stage2.yaml` in Colab's file editor
2. Under `overrides:`, add a block for the species (replace the `{}`):

```yaml
overrides:
  corn:
    degrees: 30.0
    hsv_v: 0.6
    erasing: 0.35
    epochs: 40
```

3. Save (Ctrl+S)

## Step 6.2 — Retrain it

1. In **Cell 18**, change `SPECIES_TO_FIX = "REPLACE_ME"` to your species
   (e.g. `"corn"`)
2. Run Cell 18

This trains into a **separate** `<species>__aug` run — your baseline is
not overwritten.

## Step 6.3 — Decide whether to promote it ⚠️

🔴 **Promotion rule: only keep the retrained model if it improves the
PlantDoc / real-world number — not just validation.** Validation-only
improvement is how you fool yourself.

If it genuinely improved: in Google Drive, copy
`models/stage2/<species>__aug/best.pt` over
`models/stage2/<species>/best.pt`.

If it didn't: leave the baseline alone.

Then **re-run Cell 16** to confirm the real-world number actually moved.

---

# PART 7 — Export the models (☁️, ~15 min)

## Step 7.1 — Run Cell 19 (export + verify + registry)

Converts everything to ONNX (the format the API uses), verifies each
exported model produces identical predictions to the original, and writes
`registry.json` — the contract between training and serving.

✅ **Expect:** `PASSED=True` for every model, and `All models passed: True`.

❌ **If any model fails verification,** stop. A mismatch here means the
deployed API would produce different results than your tested model. Don't
deploy until this is green.

⚠️ **Note the printed threshold warning.** The confidence thresholds
default to 0.5. Tune them after reading Cell 16's calibration numbers
(`mean_confidence_correct` vs `mean_confidence_incorrect`) — if your model
is confidently wrong on real photos, raise the thresholds — then re-run
just the registry step.

---

## Step 7.2 — Run Cell 20 (download the models)

✅ **Expect:** a zip file downloads to your PC
(`agrisense_exported.zip`, likely 50–300 MB).

---

## Step 7.3 — 🖥️ Put the models in place

```powershell
cd C:\Users\ankul\OneDrive\Desktop\MAJRO\AgriSense
mkdir serving\models
```

Extract `agrisense_exported.zip` into `serving\models\` so you end up with:

```
serving/models/registry.json
serving/models/stage1/species.onnx
serving/models/stage2/tomato.onnx
serving/models/stage2/potato.onnx
...
```

✅ **Verify:** `registry.json` sits directly inside `serving\models\`, not
inside a nested `exported\` subfolder.

💡 These are gitignored on purpose — model weights don't belong in git.

---

# PART 8 — Deploy the API (🖥️, ~30–45 min)

Full detail lives in `serving/DEPLOY.md`. Summary:

## Step 8.1 — Test it locally first

```powershell
cd C:\Users\ankul\OneDrive\Desktop\MAJRO\AgriSense\serving
python -m pip install -r requirements.txt

# Generate a key and set it for this shell session
python -c "import secrets; print(secrets.token_urlsafe(32))"
# copy the output, then:
$env:API_KEY = "PASTE_THE_KEY_HERE"
$env:MODEL_DIR = "./models"

cd ..
python -m uvicorn serving.app:app --port 8080
```

In a **second** terminal, test all four cases:

```powershell
# 1. No key -> should be 401
curl.exe -i -X POST http://localhost:8080/predict -F "file=@test_leaf.jpg"

# 2. Wrong key -> should be 401
curl.exe -i -X POST http://localhost:8080/predict -H "X-API-Key: wrong" -F "file=@test_leaf.jpg"

# 3. Correct key -> should return a diagnosis
curl.exe -i -X POST http://localhost:8080/predict -H "X-API-Key: YOUR_KEY" -F "file=@test_leaf.jpg"

# 4. Health check -> should be 200, no key needed
curl.exe -i http://localhost:8080/health
```

✅ **All four must behave as described** before you deploy.

---

## Step 8.2 — Deploy to Google Cloud Run

Follow `serving/DEPLOY.md` steps 0–5 exactly. In short:

```powershell
gcloud auth login
gcloud config set project <your-gcp-project-id>
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com

# Store the key as a secret (NEVER as a plain env var — it leaks into deploy logs)
python -c "import secrets; print(secrets.token_urlsafe(32))"
echo -n "PASTE_KEY" | gcloud secrets create agrisense-pd-api-key --data-file=-

gcloud auth configure-docker
docker build -t gcr.io/<project-id>/agrisense-pd-api:latest ./serving
docker push gcr.io/<project-id>/agrisense-pd-api:latest

gcloud run deploy agrisense-pd-api `
  --image gcr.io/<project-id>/agrisense-pd-api:latest `
  --region us-central1 --platform managed --allow-unauthenticated `
  --memory 2Gi --cpu 2 --min-instances 0 --max-instances 3 `
  --set-secrets API_KEY=agrisense-pd-api-key:latest
```

## Step 8.3 — Get your live URL

```powershell
gcloud run services describe agrisense-pd-api --region us-central1 --format='value(status.url)'
```

✅ **Save this URL.** Test it with the same four curl cases from Step 8.1,
swapping `localhost:8080` for your live URL.

---

# PART 9 — Wire it into your app (🖥️, ~15 min)

The mobile app code is already written. It just needs the backend
configured.

## Step 9.1 — Configure your backend's `.env`

Open `backend\.env` (create it from `.env.example` if it doesn't exist)
and add the two new lines:

```
PLANT_API_URL=https://your-cloud-run-url.run.app
PLANT_API_KEY=the_same_key_from_step_8.2
```

🔴 **Why the proxy exists:** the app never talks to the plant API
directly. Anything shipped in a React Native bundle is extractable — an
API key in the app is a public API key. Your backend holds it instead.

## Step 9.2 — Restart your backend

```powershell
cd C:\Users\ankul\OneDrive\Desktop\MAJRO\AgriSense\backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

## Step 9.3 — Make sure the phone can reach it

Your `mobile_app\.env` must have `EXPO_PUBLIC_BACKEND_URL` set to your
PC's **LAN IP**, not `localhost`:

```
EXPO_PUBLIC_BACKEND_URL=http://10.87.216.17:8000
```

Find your current IP with `ipconfig` and update it if it changed.

## Step 9.4 — Run the app and test

```powershell
cd C:\Users\ankul\OneDrive\Desktop\MAJRO\AgriSense\mobile_app
npx expo start
```

1. Open the app on your phone
2. Go to the **Plant Scan** tab
3. Tap **TAKE PHOTO** or **CHOOSE FROM LIBRARY**
4. Grant camera/photo permission when asked

✅ **Expect:** the photo appears, then species + condition + confidence
percentages fill in.

⚠️ **Test with ~5 real photos**, including a deliberately bad one (blurry,
or a non-plant object). The bad one should show the amber **"UNCLEAR
PHOTO"** state rather than a confident wrong answer.

---

# Quick reference: what runs where

| Phase | Cell | Where | Time |
|---|---|---|---|
| Setup | 1–3 | Colab | 5 min |
| Kaggle token | 4 | Colab ⚠️ manual | 2 min |
| Download data | 5 | Colab ⏱️ | 30–60 min |
| Inspect | 6 | Colab ⚠️ read | 5 min |
| Taxonomy | 7 (+ edit yaml) | Colab ⚠️ manual | 10–30 min |
| Clean | 9 | Colab ⏱️ | 30–50 min |
| Manifest | 10 | Colab ⚠️ read | 2 min |
| Split | 11 | Colab | 1 min |
| Materialize | 12 | Colab | seconds |
| **Train Stage 1** | **13** | **Colab GPU ⏱️** | **1.5–3 h** |
| **Train Stage 2** | **14** | **Colab GPU ⏱️** | **3–6 h, 2+ sessions** |
| Eval clean | 15 | Colab | 15 min |
| Eval PlantDoc | 16 | Colab ⚠️ key result | 30 min |
| Detector | 17 | Colab, *conditional* | 1–2 h |
| Fix weak species | 18 | Colab, *conditional* | varies |
| Export | 19 | Colab | 10 min |
| Download models | 20 | Colab | 5 min |
| Deploy API | — | Your PC | 30–45 min |
| Wire app | — | Your PC | 15 min |

---

# Troubleshooting

**"No GPU detected" / env check fails**
→ Runtime → Change runtime type → T4 GPU → Save. Re-run Cell 2.

**"CUDA out of memory" during Cell 13**
→ Open `ml/configs/train_stage1.yaml`, change `batch: 128` to `batch: 64`.
Re-run Cell 13.

**Colab disconnected mid-training**
→ Re-run Cells 1, 2, 3, 5, 12, then your training cell. It resumes. Nothing lost.

**"You have exceeded your GPU usage limit"**
→ Free-tier daily cap. Wait ~12–24 hours, or use a different Google
account. Your progress is safe on Drive — resume with the protocol above.

**Kaggle download says credentials not found**
→ Re-run Cell 4 and upload `kaggle.json` again (Colab runtimes lose
`/root/` between sessions).

**Digipathos download fails**
→ Expected. See Step 2.2 for the manual route.

**Cell 7 keeps showing labels to review**
→ Each round only fixes labels you added overrides for. Keep adding
entries and re-running until it hits 0. Check for typos in `src_label` —
it must match exactly.

**`materialize.py` says counts don't match**
→ Re-run Cell 12 with `--force`:
`!python -m agrisense_pd.data.materialize --stage 1 --stage 2 --force`

**API returns 500 on `/predict`**
→ Check `serving/models/registry.json` exists and paths inside it resolve.
Re-run Step 7.3.

**App says "EXPO_PUBLIC_BACKEND_URL is not set"**
→ Set it in `mobile_app/.env` to your PC's LAN IP, then restart
`npx expo start` (env vars only load at startup).

---

# The two decisions still open

1. **Deployment platform** — everything is written for **Google Cloud Run**
   (scales to zero, proper secret management). Say so if you'd rather use
   Render or Railway and `serving/DEPLOY.md` gets rewritten; the app and
   Dockerfile don't change.

2. **Stage 1 model size** — currently `yolo11s-cls` (better accuracy).
   Switch to `yolo11n-cls` in `ml/configs/train_stage1.yaml` if you want
   faster training at roughly 1 point less accuracy. **Decide before
   Step 4.1** — changing it later means retraining Stage 1 from scratch.
