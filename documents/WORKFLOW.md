# AgriSense AI — System Workflow

How the whole system fits together, end to end. Four independent pieces that
each work on their own; nothing here is a monorepo build step.

| Piece | Directory | Stack |
|---|---|---|
| Mobile app | `mobile_app/` | Expo 54, expo-router, React Native, TypeScript |
| Web dashboard | `web_dashboard/` | Vanilla HTML/CSS/JS, served by the backend |
| Backend API | `backend/` | FastAPI (single `main.py`), deployed on Render |
| Sensor firmware | `esp32_firmware/AgriSense_ESP32/` | ESP32 DevKit V1, Arduino C++ |
| Camera firmware | `esp32_firmware/AgriSense_ESP32CAM/` | AI-Thinker ESP32-CAM, Arduino C++ |
| ML pipeline | `ml/` | Ultralytics YOLO-cls, ONNX export (training only) |

---

## 1. Telemetry — sensors to screen

The key architectural decision: **the ESP32 talks directly to Supabase, not to the
backend.** Manual pump control and live telemetry keep working even with the backend
stopped.

```
ESP32 DevKit V1                Supabase (Postgres)            App / Dashboard
──────────────────             ───────────────────            ───────────────
DHT11      GPIO 4  ─┐
Soil AOUT  GPIO 34 ─┼─ read ─► POST /rest/v1/telemetry_data ─► Realtime push ─► UI
Rain DO    GPIO 33 ─┘          (every 10s)
Relay IN   GPIO 16 ◄── set ◄── GET /rest/v1/device_commands ◄── INSERT command
                               (polled every 5s)
```

- **Telemetry** — every 10 s the board reads all sensors and inserts a row into
  `telemetry_data`. Failed sensors report `0` rather than skipping the tick, which is
  how "online but sensors dead" is distinguished from "powered off".
- **Heartbeat** — every 10 s it upserts `device_status`. A DB trigger stamps
  `last_seen_at` server-side (the board has no clock). No heartbeat for 30 s = OFFLINE.
- **Commands** — the board polls `device_commands` every 5 s for unexecuted rows,
  applies `PUMP_ON`/`PUMP_OFF` to the relay, then PATCHes the row `executed = true`.
- Clients subscribe to Supabase **Realtime** on `telemetry_data`, `device_status` and
  `device_config`, so the UI updates without polling.

## 2. Pairing — binding a board to an account

Serial + secret, gated on the board actually being alive.

1. `device_registry` is the factory list: `device_id` + `pairing_secret`. RLS is on with
   **zero policies**, so nobody can read it — only `SECURITY DEFINER` functions touch it.
2. User enters the serial + secret. The app calls `claim_device(...)`, which checks, in
   order: logged in → serial/secret matches registry → not already claimed →
   **`device_status.last_seen_at` is within 60 s**. That last gate means the board must
   be powered on at pairing time.
3. On success it inserts into `devices` (linked to `auth.uid()`) and seeds
   `device_config`. A trigger caps each account at 4 devices.

RLS on every user-facing table scopes rows to the owning account via a subquery on
`devices`.

## 3. Pump automation — the decision engine

This is the one thing that **does** need the backend running. A background task in
`backend/main.py` ticks every 10 s over all devices with automation enabled.

```
                     ┌─ safety gate ─┐
every 10s ─► read device_config, device_status, latest telemetry
                     │
                     ├─ offline / stale data / sensors_ok false ─► force PUMP_OFF, stop
                     │
                     ├─ MOISTURE mode ─► soil < start_threshold AND no rain ─► PUMP_ON
                     │                   soil ≥ stop_threshold              ─► PUMP_OFF
                     │                   elapsed ≥ max_runtime_mins         ─► PUMP_OFF
                     │
                     └─ TIMER mode ────► active timer window for today      ─► PUMP_ON/OFF
```

The safety gate exists because failed sensors report `0`. Without it a disconnected soil
probe reading `0` would satisfy `0 < start_threshold` forever and run the pump
continuously. Manual control from the UI switches `automation_mode` to `NONE` so the
engine doesn't fight the user.

## 4. Plant Scan — leaf disease detection

```
Phone camera ─► multipart upload ─► POST /api/plant/predict ─► Gemini vision (JSON schema)
                                    (backend holds the key)          │
                                                                      ▼
                        species, condition, severity, affected area %, symptoms,
                        cause, treatment, prevention, confidences
```

The backend picks its inference source at request time:

- If `PLANT_API_URL` + `PLANT_API_KEY` are set → proxies to the trained ONNX model
  service (`serving/app.py`).
- Otherwise → falls back to **Gemini vision** with a strict `responseSchema`, so the
  reply is structured JSON rather than prose.

Swapping between them is an environment variable, not a code change. See
`documents/DATASETS.md` for the training-side status.

## 5. Live camera — ESP32-CAM relay

The camera is a **second, separate board**. It cannot share the sensor node's hardware:
the OV2640 interface occupies GPIO 34 (the soil ADC), GPIO 4 (flash LED) and GPIO 16
(PSRAM CS). It reuses the sensor node's `device_id` — it is "the camera on that field
node", not a separately paired device.

```
ESP32-CAM ──► POST /api/camera/{id}/frame ──► backend holds latest JPEG in memory
     ▲             (auth: X-Cam-Key)                      │
     └── {"wanted": bool} ◄─────────────────────┐         ▼
                                                 │  GET /api/camera/stream?t=…
   idle: GET /api/camera/{id}/wanted every 3s    │  (MJPEG, multipart/x-mixed-replace)
                                                 │         │
                                          viewer present ◄─┘
```

Why relay through the backend instead of serving MJPEG on the LAN: it works from **any**
network with no router/port-forward config.

The `wanted` flag piggybacks on the upload response, so there's no separate control
channel to the device. While idle the camera polls every 3 s and streams nothing; the
moment someone opens the feed it flips to streaming (~2–4 fps at VGA). Viewers
authenticate with a short-lived token in the URL, because an `<img src>` cannot send an
`Authorization` header.

## 6. Farm advisor chat

`POST /api/advisor/ask` proxies to Gemini, injecting the device's latest telemetry into
the system instruction so answers are grounded in live readings. The Plant Scan screen
hands a diagnosis to this tab via a route param.

---

## Security model

- **Every API key stays server-side.** `GEMINI_API_KEY`, `PLANT_API_KEY` and
  `CAM_UPLOAD_KEY` live only in the backend environment; the app and dashboard call the
  backend, never the upstream service.
- **Every user-facing route validates the caller's JWT** with the Supabase anon client,
  then re-checks device ownership manually — the backend uses the service-role key for
  table access, which bypasses RLS, so ownership cannot be left to the database.
- **Devices authenticate with a shared secret** (`X-Cam-Key`) rather than a user token,
  since hardware has no login.
- Camera frames are held **in memory only** — never written to Supabase or disk.

## Running it

```bash
# Backend (serves the dashboard at http://localhost:8000/)
cd backend && pip install -r requirements.txt && uvicorn main:app --reload

# Mobile app
cd mobile_app && npm install && npx expo start
```

Environment: copy `backend/.env.example` → `backend/.env` and
`mobile_app/.env.example` → `mobile_app/.env`, then fill in the values.
Firmware: open the `.ino` in Arduino IDE, edit the CONFIGURATION block at the top, upload.
