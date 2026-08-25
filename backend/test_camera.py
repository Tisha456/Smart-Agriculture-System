"""Self-check for the ESP32-CAM relay routes in main.py. Run:
python backend/test_camera.py
Needs backend/.env present (CAM_UPLOAD_KEY + Supabase creds for import) but
makes no real network/Supabase calls — auth for the viewer-token route is
bypassed by seeding main._camera_tokens directly, since minting a real one
needs a live logged-in user."""
import time

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
DEVICE_ID = "AGS-TEST-CAM"
FAKE_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"   # SOI...EOI, contents don't matter

# Wrong upload key -> 401, not a silent pass-through.
resp = client.post(f"/api/camera/{DEVICE_ID}/frame", headers={"x-cam-key": "wrong"}, content=FAKE_JPEG)
assert resp.status_code == 401, resp.text

# Oversized frame -> 413.
resp = client.post(
    f"/api/camera/{DEVICE_ID}/frame",
    headers={"x-cam-key": main.CAM_UPLOAD_KEY},
    content=b"x" * (main.MAX_FRAME_BYTES + 1),
)
assert resp.status_code == 413, resp.text

# Real upload, nobody watching yet -> 200, wanted false.
resp = client.post(f"/api/camera/{DEVICE_ID}/frame", headers={"x-cam-key": main.CAM_UPLOAD_KEY}, content=FAKE_JPEG)
assert resp.status_code == 200, resp.text
assert resp.json() == {"wanted": False}

# /wanted mirrors the same flag for an idle camera.
resp = client.get(f"/api/camera/{DEVICE_ID}/wanted", headers={"x-cam-key": main.CAM_UPLOAD_KEY})
assert resp.json() == {"wanted": False}

# Stream with an unknown token -> 401.
resp = client.get("/api/camera/stream", params={"t": "not-a-real-token"})
assert resp.status_code == 401, resp.text

# Stream with an expired token -> 401.
main._camera_tokens["expired-token"] = (DEVICE_ID, time.time() - 1)
resp = client.get("/api/camera/stream", params={"t": "expired-token"})
assert resp.status_code == 401, resp.text

# Valid token -> streaming a frame, and the camera should now see "wanted": true.
main._camera_tokens["good-token"] = (DEVICE_ID, time.time() + 60)
with client.stream("GET", "/api/camera/stream", params={"t": "good-token"}) as resp:
    assert resp.status_code == 200
    assert "multipart/x-mixed-replace" in resp.headers["content-type"]
    chunk = next(resp.iter_bytes())
    assert b"--frame" in chunk
    assert b"\xff\xd8" in chunk    # the JPEG we uploaded came through

resp = client.get(f"/api/camera/{DEVICE_ID}/wanted", headers={"x-cam-key": main.CAM_UPLOAD_KEY})
assert resp.json() == {"wanted": True}

print("test_camera: all assertions passed")
