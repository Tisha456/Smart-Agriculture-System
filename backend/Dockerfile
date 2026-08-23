# AgriSense automation backend (pump decision engine + timers/automation API
# + web dashboard static hosting). Build from the REPO ROOT, not this
# directory — main.py serves web_dashboard/ via a relative "../web_dashboard"
# path (see main.py), so both directories must land in the image with the
# same relative layout they have in the repo.
#
#   docker build -f backend/Dockerfile -t agrisense-backend .
#
FROM python:3.11-slim

WORKDIR /app

RUN groupadd -r appuser && useradd -r -g appuser appuser

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/main.py backend/main.py
COPY web_dashboard/ web_dashboard/

ENV PYTHONUNBUFFERED=1
# uvicorn's console-script entry point does not add the current directory to
# sys.path the way `python -m uvicorn` does, so a dotted app path
# ("backend.main:app") only resolves reliably with this set explicitly —
# verified by testing the exact import with cwd stripped from sys.path.
ENV PYTHONPATH=/app

USER appuser
EXPOSE 8080

# --workers MUST stay 1: the pump decision engine is an in-process asyncio
# background task started in main.py's lifespan, not a shared/external
# scheduler. Every extra worker process would run its own independent copy
# of that loop, so N workers would queue every pump command N times.
#
# Shell-form CMD (not exec-form JSON array) is deliberate here: it's what
# makes ${PORT:-8080} actually expand. Render assigns its own PORT (commonly
# 10000) and expects the container to bind to it; Fly.io does not set PORT at
# all, so this falls back to 8080 there, matching fly.toml's internal_port.
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
