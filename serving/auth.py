"""API key auth + a simple in-memory rate limiter for the /predict
endpoint (Phase H). Constant-time comparison via secrets.compare_digest
— a plain `==` on the header value leaks the key byte-by-byte through
response timing, which is a real attack against a single static key like
this one (see plant-disease-implementation-plan.md section "H").
"""
from __future__ import annotations

import os
import secrets
import time
from collections import defaultdict, deque

from fastapi import Header, HTTPException, status

API_KEY = os.environ.get("API_KEY", "")
RATE_LIMIT_REQUESTS = int(os.environ.get("RATE_LIMIT_REQUESTS", "60"))
RATE_LIMIT_WINDOW_SECONDS = float(os.environ.get("RATE_LIMIT_WINDOW_SECONDS", "60"))

if not API_KEY:
    raise RuntimeError(
        "API_KEY environment variable is not set. Never hardcode it in code or commit it — "
        "set it via your platform's secret manager (see serving/DEPLOY.md)."
    )

_request_log: dict[str, deque] = defaultdict(deque)


def _check_rate_limit(key: str) -> None:
    now = time.monotonic()
    window = _request_log[key]
    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {RATE_LIMIT_REQUESTS} requests per {RATE_LIMIT_WINDOW_SECONDS:.0f}s.",
        )
    window.append(now)


def require_api_key(x_api_key: str | None = Header(default=None)) -> str:
    if x_api_key is None or not secrets.compare_digest(x_api_key, API_KEY):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key.")
    _check_rate_limit(x_api_key)
    return x_api_key
