# Deploying the plant-disease API — Google Cloud Run

Default target per `plant-disease-implementation-plan.md` Phase I: Cloud
Run scales to zero (good for a personal-app budget), takes the Dockerfile
as-is, and has proper secret management — unlike setting `API_KEY` as a
plain env var on some smaller-tier PaaS platforms, which can leak it into
deploy logs. If you'd rather use Render/Railway instead, say so and this
file gets rewritten for that platform; the app/Dockerfile don't change.

## 0. One-time setup

```bash
gcloud auth login
gcloud config set project <your-gcp-project-id>
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
```

## 1. Get the exported models onto this machine

After Phase G finishes in Colab, download `Drive/AgriSense_PlantDisease/exported/`
and place its contents at `serving/models/` so you have:

```
serving/models/registry.json
serving/models/stage1/species.onnx
serving/models/stage2/<species>.onnx   (one per species)
serving/models/detector/leaf_detector.onnx   (only if Phase E2 kept it)
```

## 2. Generate and store the API key

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# copy the output, then:
echo -n "PASTE_THE_KEY_HERE" | gcloud secrets create agrisense-pd-api-key --data-file=-
```

Treat this key like a password: never commit it, never put it in
`--set-env-vars` (that lands in deploy logs/history) — it must only ever
enter the platform via Secret Manager.

## 3. Build and push the image

```bash
gcloud auth configure-docker

docker build -t gcr.io/<your-gcp-project-id>/agrisense-pd-api:latest ./serving
docker push gcr.io/<your-gcp-project-id>/agrisense-pd-api:latest
```

## 4. Deploy

```bash
gcloud run deploy agrisense-pd-api \
  --image gcr.io/<your-gcp-project-id>/agrisense-pd-api:latest \
  --region us-central1 \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --min-instances 0 \
  --max-instances 3 \
  --set-secrets API_KEY=agrisense-pd-api-key:latest
```

- `--allow-unauthenticated` here means "the Cloud Run *ingress* doesn't
  require Google IAM auth" — your own `X-API-Key` check in `auth.py` is
  still the real gate on every request.
- 2Gi/2 CPU is a reasonable starting point for CPU ONNXRuntime inference
  across Stage 1 + one Stage 2 model per request; adjust after checking
  Cloud Run's memory graphs under real traffic.
- `--min-instances 0` is what makes this free-tier-friendly (scales to
  zero when idle); expect a cold-start delay of a few seconds on the
  first request after idle.

## 5. Find your live URL and test it

```bash
gcloud run services describe agrisense-pd-api --region us-central1 --format='value(status.url)'
```

```bash
# missing key -> 401
curl -i https://<your-url>/predict -F "file=@test_leaf.jpg"

# wrong key -> 401
curl -i https://<your-url>/predict -H "X-API-Key: wrong" -F "file=@test_leaf.jpg"

# correct key -> prediction
curl -i https://<your-url>/predict -H "X-API-Key: <the real key>" -F "file=@test_leaf.jpg"

# health probe (no key needed)
curl -i https://<your-url>/health
```

## Rotating the key later

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
echo -n "NEW_KEY_HERE" | gcloud secrets versions add agrisense-pd-api-key --data-file=-
gcloud run services update agrisense-pd-api --region us-central1 --set-secrets API_KEY=agrisense-pd-api-key:latest
```

Update the key everywhere it's used server-side (backend proxy routes in
Phase J) at the same time — the app/website should never hold this key
directly (see Phase J notes in `plant-disease-implementation-plan.md`).
