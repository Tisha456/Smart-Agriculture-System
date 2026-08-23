# AgriSense Plant Disease serving API (Phase H).
# CPU-only ONNXRuntime image — no CUDA needed, this is inference-only.
FROM python:3.11-slim

WORKDIR /app

RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY app.py auth.py pipeline_runtime.py __init__.py ./serving/
RUN touch /app/__init__.py

# Exported models (registry.json + *.onnx) — downloaded from Drive/exported/
# after Phase G. Not baked into the image if you'd rather mount/fetch them
# at deploy time; see DEPLOY.md.
COPY models ./models

ENV MODEL_DIR=/app/models
ENV PYTHONUNBUFFERED=1

USER appuser
EXPOSE 8080

CMD ["uvicorn", "serving.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "2"]
