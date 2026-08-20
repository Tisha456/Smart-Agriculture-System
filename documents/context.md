# AgriSense AI — Complete Project Context
> Last updated: 20 August 2026 (v4.0 — Verified Pairing & Real Device Presence)
> Status: Hybrid architecture — ESP32 → Supabase direct for telemetry/heartbeat/manual pump.
> FastAPI deployed ONLY for pump automation (Moisture Auto + Timer modes).

---

## What Is AgriSense?

AgriSense is a **Smart Agriculture IoT System** that lets a farmer:
- Monitor soil moisture, temperature, humidity, and rain from anywhere in the world
- Control a water pump (relay) remotely via a website — manual switch + emergency Force Stop
- Run automatic irrigation: **Soil Moisture Auto** (start/stop thresholds) or **Timer Schedule**
- Get rain protection (pump auto-stops when rain is detected, in both auto modes)
- Know for certain whether the hardware is actually connected — not just guess from a UI toast

---

## v4.0 — What changed and why

Three problems drove this revision, all reported directly against the running system:

1. **Any typed string paired successfully.** The old SQL policy
   `devices FOR INSERT WITH CHECK (true)` let the website insert literally any serial into
   `devices`, with no check that real hardware existed. Fixed by a `device_registry` table
   (real serials only) plus a `claim_device()` RPC with three gates: serial+secret must match a
   registered board, the board must not already be claimed, and — critically — **the board must
   have sent a heartbeat within the last 60 seconds**. You cannot pair hardware that isn't
   powered on.

2. **No way to tell "ESP32 off" from "ESP32 on but sensors unplugged."** The firmware used to
   `return` out of `sendTelemetry()` the instant a DHT11 read failed, so a sensor fault produced
   *zero packets* — indistinguishable from the device being switched off. Fixed with a new
   `device_status` heartbeat table the ESP32 upserts every 10s **regardless of sensor health**,
   plus per-sensor OK/fail flags. The dashboard now shows three real states:
   - **OFFLINE** — no heartbeat, or it's gone stale (>30s) — values show `00` in grey
   - **ONLINE, no sensor data** — heartbeat is fresh but sensors are failing — values show `00`
     in **green** (the connection is real and healthy; only the sensors are the problem)
   - **LIVE** — heartbeat fresh, sensors healthy — real readings

3. **No confirmation on the hardware side that pairing worked.** The ESP32 now asks Supabase
   "am I paired yet?" once at boot and every 30s after, and prints a big banner to the Serial
   Monitor the moment the answer changes — so pairing on the website and confirmation on the
   device happen live, on two screens, within 30 seconds of each other.

Also fixed while investigating (found, not requested, but blocking): `BACKEND_BASE` was used in
four places in `app.js` and defined nowhere, so Moisture Auto, Timer mode, Force Stop, and the
whole timer UI silently did nothing. And the pump automation engine read `last_soil_moisture`
from an in-memory dict that the ESP32's direct-to-Supabase telemetry never fed — it would have
latched the pump ON forever the moment it actually ran. Both are fixed below.

---

## Current Architecture (v4.0)

```
┌─────────────────────┐   HTTPS REST    ┌──────────────────────┐
│   ESP32 Hardware    │ ─────────────►  │   Supabase           │
│   (C++ / Arduino)  │ ◄────────────── │   (hosted cloud DB)  │
│  v4.0.0 firmware   │                 └──────────────────────┘
└─────────────────────┘                          │  ▲
        │ every 10s: telemetry (always sent,      │  │
        │   zeros if a sensor fails) + heartbeat   │  │ Supabase Realtime
        │ every 5s:  poll device_commands          │  │ (telemetry_data,
        │ every 30s: "am I paired?" check           │  │  device_status)
        ▼                                          ▼  │
                                    ┌──────────────────────┐
                                    │   Website (Browser)  │
                                    │   Supabase JS Client │
                                    └──────────────────────┘
                                          │  ▲
                                          │  │  HTTP (only for automation)
                                          ▼  │
                                    ┌──────────────────────┐
                                    │  FastAPI (main.py)   │
                                    │  Decision Engine ONLY │
                                    └──────────────────────┘
```

**Rule of thumb:** if it's telemetry, manual pump control, or device pairing — it works with the
FastAPI backend switched off. If it's Moisture Auto or Timer Schedule mode — the backend must be
running, and the website now says so honestly (reverts to Manual + toasts a warning) if it can't
reach it, instead of pretending automation is active.

---

## The 3 Layers

### Layer 1 — ESP32 Firmware (C++) v4.0.0
**File:** `esp32_firmware/AgriSense_ESP32/AgriSense_ESP32.ino`

Every loop:
- **Every 10s** → reads all sensors, POSTs telemetry to `telemetry_data` — **always**, even if a
  sensor read failed (bad readings become `0`, tracked separately via `sensors_ok` /
  `sensor_flags`). This is what makes "online, sensors dead" distinguishable from "offline".
- **Every 10s** (just before telemetry) → upserts `device_status`: `last_seen_at`, `sensors_ok`,
  `sensor_flags` (`{dht, soil, rain}`), firmware version, IP, RSSI, boot count.
- **Every 5s** → polls `device_commands`, executes PUMP_ON/PUMP_OFF, marks executed.
- **Once at boot, then every 30s** → calls the `device_pair_status` RPC and prints a banner to
  Serial when the paired/unpaired state changes.

Per-sensor health:
- **DHT11** — `isnan()` check, same as before. On failure, temperature/humidity sent as `0`.
- **Soil moisture** — new `SOIL_DISCONNECT_ADC` threshold. A raw ADC below it means "probe not
  plugged in", sent as `0`. **This value needs calibration per-board** — see
  `esp32_firmware/WIRING_GUIDE.md` for the procedure (unplug, read raw ADC; plug in dry, read
  raw ADC; set the threshold between the two).
- **Rain sensor** — **cannot be health-checked.** A disconnected digital pin floating LOW reads
  identically to "no rain detected". It's excluded from `sensors_ok`; `sensor_flags.rain` always
  reports `true`. This is a real hardware limitation, not a bug — documented in `WIRING_GUIDE.md`.

Config additions (top of `.ino`):
```cpp
#define DEVICE_ID          "AGS-0001"
#define PAIRING_SECRET     "7F3K21X9"   // must match device_registry.pairing_secret in Supabase
#define SOIL_DISCONNECT_ADC  100        // calibrate on your board — see WIRING_GUIDE.md
```

### Layer 2 — Python Backend (FastAPI) — Automation ONLY
**File:** `backend/main.py` (v4.0.0)

**Not needed** for telemetry, manual pump control, or device pairing — all of those go directly
ESP32/website ↔ Supabase. **Required** only for Moisture Auto and Timer Schedule modes.

The decision engine runs every 10s and, for every device with `automation_mode != NONE`:
1. Reads `device_config` (mode + thresholds — persisted, not an in-memory dict anymore)
2. Reads the latest `device_status` heartbeat and `telemetry_data` row
3. **Safety gate**: if the heartbeat is stale (>30s), the telemetry is stale (>60s), or
   `sensors_ok` is false → force `PUMP_OFF` if running, and skip threshold evaluation entirely.
   This is mandatory now that sensor failures send `0` instead of no packet — without the gate,
   a disconnected soil probe would read `0 < start_threshold` forever and never stop watering.
4. Otherwise evaluates Moisture or Timer logic exactly as before (rain guard, max-runtime cutoff)
   and persists `pump_on`/`pump_on_since` back to `device_config`.

Because this server has no logged-in user, every endpoint validates the caller's Supabase JWT
with the anon client, then does the actual table read/write with `supabase_admin`
(`SUPABASE_SERVICE_KEY`, bypasses RLS) after manually re-checking device ownership.

**⚠️ `backend/.env` now requires `SUPABASE_SERVICE_KEY`** (Project Settings → API → service_role
in the Supabase dashboard). Without it, `supabase_admin` silently falls back to the anon key and
every automation read/write returns empty under RLS. A placeholder line was added to
`backend/.env` and `backend/.env.example` — replace it with the real key before starting the
server.

To run:
```powershell
cd backend
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Endpoints kept: `POST /api/command` (manual override / Force Stop), `POST /api/automation/mode`,
`GET /api/automation/state/{id}`, timer CRUD (`POST/GET/DELETE /api/timers`, plus new
`PATCH /api/timers/{id}` to persist the enable/disable toggle). `GET /api/health` replaces the
old duplicate root route.

**Removed** (the ESP32 and website both bypass these — they were dead code):
`POST /api/telemetry`, `GET /api/device/command/{id}`, `POST /api/devices/bind`,
`WS /ws/{device_id}` and its `ConnectionManager`.

### Layer 3 — Web Dashboard (HTML/CSS/JavaScript)
**Files:** `web_dashboard/index.html`, `app.js`, `styles.css`

Talks **directly to Supabase** for everything except automation mode and timers:
- **Auth:** `supabaseClient.auth.signIn/signUp`
- **Device pairing:** `supabaseClient.rpc('claim_device', {...})` — no longer a raw INSERT.
  Requires the Hardware Serial ID **and** the Pairing Secret; fails with a specific message if
  the serial is unknown, already claimed, or the board isn't currently sending heartbeats.
- **Presence:** subscribes to `device_status` Realtime for the active device, plus a one-shot
  fetch on device switch/login and a 5-second UI tick (needed because "going offline" produces
  no database event to react to — only elapsed time does).
- **Live telemetry:** `supabaseClient.channel().on('postgres_changes', INSERT, telemetry_data)`
- **Manual pump command:** `supabaseClient.from('device_commands').insert()`
- **Automation mode / timers:** `fetch(BACKEND_BASE + '/api/...')` — now actually defined
  (`web_dashboard/app.js` top of file). Degrades honestly: if the backend is unreachable, the UI
  reverts to Manual mode and shows a toast, instead of silently pretending automation is active.

Header status pill and dashboard values are driven by one function, `connectionState()`:
`NO_DEVICE` / `OFFLINE` / `ONLINE_NO_SENSORS` / `LIVE` — see the CSS classes `.val-offline`
(grey) and `.val-nosensor` (green) in `styles.css`.

**Removed:** the "Auxiliary Farm Actuator Relays" card (Zone 1 Solenoid / Misting Foggers /
Field LED Lighting) — it was pure UI mockup. Its toggles only called `showToast()`; no command
was ever sent, and the firmware never configured GPIO17/18/19. `WIRING_GUIDE.md` documents one
relay, on GPIO16. Deleted rather than left as a UI element that lies about hardware state.

---

## Device Pairing Flow (v4.0)

```
Step 0 (one-time, per physical board): seed it into device_registry
        INSERT INTO device_registry (device_id, pairing_secret) VALUES ('AGS-0001', '7F3K21X9');
        (see documents/supabase_presence_and_pairing.sql)

Step 1: Flash firmware with matching DEVICE_ID + PAIRING_SECRET, power it on
        → it starts sending heartbeats to device_status every 10s immediately,
          even before anyone has paired it

Step 2: Open website → Log in with email (Supabase Auth)

Step 3: Connect page → enter Serial ID + Pairing Secret + name → "Initialize Node Pairing"
        Website calls claim_device() RPC, which checks (in order):
          1. Serial + secret match a real registered board       -> else UNKNOWN_DEVICE
          2. Not already claimed by anyone                        -> else CLAIMED_BY_OTHER / ALREADY_YOURS
          3. device_status.last_seen_at within the last 60s       -> else DEVICE_OFFLINE
        Only if all three pass does a row get written to `devices`.

Step 4: Within 30s, the ESP32's own pairing check flips its Serial Monitor banner to
        "PAIRED — THIS ESP32 IS BOUND TO THE WEBSITE" — visible proof on both ends.

Step 5: Dashboard shows LIVE the moment the next telemetry packet with sensors_ok=true arrives.
```

Key rules (unchanged): 1 email = max 4 ESP32 nodes (DB trigger); each ESP32 has a unique
`DEVICE_ID`; data lives in Supabase, accessible from anywhere.

---

## Sensors & Hardware

| Sensor | GPIO | What it measures | Health-checkable? |
|--------|------|-----------------|---|
| DHT11 | GPIO 4 | Air temperature + humidity | Yes — `isnan()` on read |
| Capacitive Soil Moisture | GPIO 34 (ADC) | Soil water content (0–100%) | Yes — `SOIL_DISCONNECT_ADC`, needs per-board calibration |
| Rain Sensor (digital) | GPIO 33 | Rain detected yes/no | **No** — floating pin reads as "no rain"; excluded from `sensors_ok` |
| Relay Module | GPIO 16 | Controls water pump (active-LOW) | n/a (actuator, not a sensor) |

**Relay is active-LOW:** `GPIO 16 = LOW` → relay ON → pump runs. `GPIO 16 = HIGH` → relay OFF.

There is currently **only one relay/actuator** on this hardware. The dashboard no longer shows
placeholder controls for equipment that isn't wired (see "Removed" under Layer 3).

---

## Pump Control (Current State)

### Manual (works with FastAPI stopped):
```
Website → supabaseClient.from('device_commands').insert({ device_id, command: 'PUMP_ON' })
                    ↓
        ESP32 polls every 5s → picks it up → relay fires → marks executed=true
```

### Force Stop (requires FastAPI running):
Unlike the manual toggle, Force Stop calls `POST /api/command` on the FastAPI backend. If the
backend is unreachable it now reports failure honestly ("Force Stop FAILED — automation server
unreachable. Use the Manual Override switch instead.") rather than claiming success while doing
nothing, which is what it silently did before `BACKEND_BASE` was fixed.

### Automation Modes (require FastAPI running):
- **MOISTURE mode:** `soil < start_threshold AND no rain → PUMP_ON`; `soil >= stop_threshold →
  PUMP_OFF`; max-runtime safety cutoff. Blocked entirely if the device is offline, its telemetry
  is stale, or `sensors_ok` is false (the safety gate — see Layer 2).
- **TIMER mode:** checks current time/day against the `timers` table. Rain immediately stops the
  pump and pauses the schedule. Same safety gate applies.
- Selecting either mode while the backend is down reverts the UI to Manual and shows a toast —
  it does not pretend to be active.

---

## Supabase Database Tables

| Table | Purpose | New in v4.0? |
|-------|---------|---|
| `devices` | Which ESP32 belongs to which user | — |
| `telemetry_data` | Every sensor reading (ESP32 inserts directly, 10s, always sent) | — |
| `device_commands` | Queue of PUMP_ON/PUMP_OFF | — |
| `timers` | Irrigation schedules | — |
| `device_registry` | **Real, seeded serials + pairing secrets.** Not readable by anon/authenticated — only via SECURITY DEFINER RPCs. | ✅ |
| `device_status` | Heartbeat: `last_seen_at`, `sensors_ok`, `sensor_flags`, firmware/IP/RSSI/boot_count. Sole source of truth for "is the hardware alive". | ✅ |
| `device_config` | Persisted automation mode + thresholds + pump state, replaces the old in-memory dict in `main.py`. | ✅ |

**Key RLS / RPCs (see `documents/supabase_presence_and_pairing.sql`):**
- `claim_device(device_id, secret, name, sector)` — the *only* path into `devices` now. The old
  `"Backend inserts devices" WITH CHECK (true)` policy has been dropped.
- `device_pair_status(device_id, secret)` — what the ESP32 calls (anon key) to check if it's
  bound; never exposes owner email/user_id.
- `device_status`: anon can INSERT/UPDATE (the ESP32's own heartbeat); authenticated users can
  only SELECT devices they own.
- `device_config`: authenticated users can manage rows for devices they own; the backend uses
  the service_role key and bypasses this entirely.

---

## File Structure

```
AgriSense/
├── esp32_firmware/
│   ├── AgriSense_ESP32/
│   │   └── AgriSense_ESP32.ino    ← v4.0.0 — heartbeat, sensor health flags, pairing check
│   └── WIRING_GUIDE.md            ← now includes soil-disconnect calibration steps
│
├── backend/
│   ├── main.py                    ← v4.0.0 — automation engine ONLY, device_config-backed
│   ├── requirements.txt
│   ├── .env                       ← now also needs SUPABASE_SERVICE_KEY (placeholder added)
│   └── .env.example
│
├── web_dashboard/
│   ├── index.html                 ← pairing-secret field, offline banner, aux card removed
│   ├── app.js                     ← BACKEND_BASE defined, connectionState(), claim_device RPC
│   └── styles.css                 ← .val-offline / .val-nosensor / .status-pill.offline
│
└── documents/
    ├── context.md                            ← this file
    ├── Supabase_Complete_Setup.md             ← base schema (run first)
    ├── supabase_presence_and_pairing.sql      ← v4.0 additions (run second) — registry, status,
    │                                             config, claim_device(), device_pair_status()
    └── AgriSense_AI_Device_Connectivity_Architecture.md
```

---

## Session Log

### ✅ Session 1 — Original bugs fixed (19 Aug 2026):
1. Timer system was frontend-only → rewired to Supabase-backed API
2. Force Stop button was UI-only → now sends PUMP_OFF to backend
3. Rain badge never updated → now reads live telemetry state
4. Timer mode had no rain guard → added: rain stops pump immediately
5. Duplicate day codes `["M","T","W","T"]` → fixed to `["Mo","Tu","We","Th","Fr","Sa","Su"]`
6. Wrong firmware in repo (ultrasonic sensor) → replaced with real AgriSense firmware
7. Fake "Operator Authentication" card → replaced with real logged-in email display
8. Node pairing silently failed → Supabase RLS policy added for anon INSERT on `devices`
9. Sector hardcoded → now uses what user types
10. Pairing Secret field was blocking form with `required` → removed

### ✅ Session 2 — Architecture migration to Hybrid (20 Aug 2026):
11-15. Migrated ESP32 → Supabase direct for telemetry; website → Supabase Realtime; removed
`BACKEND_URL`/`DEVICE_PASSWORD` from firmware — but left `BACKEND_BASE` referenced in `app.js`
without ever defining it, and left the FastAPI decision engine fed by an endpoint the ESP32 no
longer called. Both were found and fixed in Session 3.

### ✅ Session 3 — Verified Pairing & Real Device Presence (20 Aug 2026):
16. **Root-caused the fake-pairing complaint** to `devices FOR INSERT WITH CHECK (true)`. Added
    `device_registry` (real serials only) + `claim_device()` RPC with a 3-gate check, the last
    gate requiring a live heartbeat — you cannot pair hardware that isn't powered on.
17. **Added `device_status` heartbeat table** + firmware `sendHeartbeat()`, sent every 10s
    regardless of sensor health. This is the actual source of truth for "connected".
18. **Removed the early-return in `sendTelemetry()`** that made a sensor fault look identical to
    the device being off — failed sensors now send `0` with a health flag instead of nothing.
19. **Added per-sensor health tracking** (`g_dhtOk`, `g_soilOk`, `g_sensorsOk`,
    `SOIL_DISCONNECT_ADC`) and documented that the rain sensor cannot be health-checked.
20. **Added `checkPairStatus()`** — ESP32 asks Supabase if it's paired at boot + every 30s,
    prints a banner on Serial Monitor when the state changes.
21. **Rewrote the dashboard's connection logic** around one `connectionState()` function driving
    three real states (OFFLINE/ONLINE_NO_SENSORS/LIVE) instead of the old binary
    hasData/no-hasData check, which could never distinguish "off" from "on, no sensors".
22. **Fixed the undefined `BACKEND_BASE`** — Moisture Auto, Timer mode, Force Stop, and the timer
    UI were all silently failing (caught exceptions swallowed by empty catch blocks).
23. **Fixed `updateHeaderDeviceSelector()` calling a non-existent `connectDeviceWebSocket()`** —
    switching devices in the header dropdown threw an uncaught error.
24. **Deleted a dead duplicate `updateTelemetryUI()`** — two functions with the same name existed;
    JS silently kept only the second, so the first was 100% dead code.
25. **Rewrote the FastAPI decision engine** to read `device_config`/`device_status`/
    `telemetry_data` from Supabase instead of an in-memory dict wiped on every restart, and added
    a mandatory safety gate (offline / stale telemetry / sensors not OK → force PUMP_OFF, skip
    evaluation) — required because zeroed sensor readings would otherwise latch the pump on.
26. **Removed dead FastAPI endpoints** (`/api/telemetry`, `/api/device/command/{id}`,
    `/api/devices/bind`, the `/ws/{device_id}` WebSocket) that neither the ESP32 nor the website
    called anymore, plus the `ConnectionManager` class that only served the WebSocket.
27. **Added `PATCH /api/timers/{id}`** so the enable/disable toggle actually persists (it used to
    only mutate local JS state).
28. **Removed the "Auxiliary Farm Actuator Relays" card** — it was UI mockup with no backing
    firmware or command wiring; deleted rather than left misleading.
29. **`backend/.env` now requires `SUPABASE_SERVICE_KEY`** — flagged with a placeholder, since
    the rewritten engine depends on it for every RLS-protected table it touches.

---

## Quick Start — Current System (v4.0)

**Step 1 — Apply the database changes (once):**
Run `documents/Supabase_Complete_Setup.md` (if not already applied), then
`documents/supabase_presence_and_pairing.sql` in the Supabase SQL editor. Seed your real board's
serial + secret into `device_registry` (a starter row for `AGS-0001` is included — change the
secret before using it for anything real).

**Step 2 — Flash the ESP32:**
- Open `esp32_firmware/AgriSense_ESP32/AgriSense_ESP32.ino`
- Set `WIFI_SSID`, `WIFI_PASSWORD`, `DEVICE_ID`, `PAIRING_SECRET` (must match what you seeded)
- **Calibrate `SOIL_DISCONNECT_ADC`** — see `WIRING_GUIDE.md`
- Upload, open Serial Monitor at 115200 baud — you should see `NOT PAIRED` until Step 4

**Step 3 — (Only if you want automation) start the backend:**
```powershell
cd backend
# Set SUPABASE_SERVICE_KEY in .env first — see backend/.env.example
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```
Skip this step entirely if you only need telemetry + manual pump control.

**Step 4 — Open the website, log in, pair the device:**
Connect page → enter the Serial ID **and** Pairing Secret → Initialize Node Pairing. The ESP32
must be powered on right now — pairing checks for a live heartbeat. Within 30s the Serial Monitor
should flip to `PAIRED`.

**Step 5 — Dashboard:**
Shows `OFFLINE` (grey `00`) until the ESP32 sends a heartbeat, `ONLINE (no sensor data)` (green
`00`) if it's alive but a sensor is failing, or `LIVE` with real numbers once everything works.

---

## Pending / Future Work

- [ ] Deploy FastAPI to cloud (Render / Railway / VPS) so automation modes work without a PC
      staying on — currently must run locally
- [ ] `GET /api/devices` and `DELETE /api/devices/{id}` in `main.py` are unused by the website
      (which talks to Supabase directly) and still use the anon client — not exercised, not fixed
- [ ] ESP32-CAM integration — not yet wired or coded
- [ ] Mobile app — currently website-only
- [ ] Auxiliary actuators (valves/foggers/lighting) — removed as UI mockup; would need a
      4-channel relay board, new firmware pins, and an extended command vocabulary to build for real
- [ ] Rotate `PAIRING_SECRET` per device periodically for better security hygiene

---

## Important Config Values (Quick Reference)

| Setting | Value | Where |
|---------|-------|-------|
| Device ID | `AGS-0001` | `.ino` — `#define DEVICE_ID` |
| Pairing Secret | must match `device_registry.pairing_secret` | `.ino` — `#define PAIRING_SECRET` |
| Soil disconnect threshold | needs per-board calibration | `.ino` — `#define SOIL_DISCONNECT_ADC` |
| WiFi SSID / Password | your network | `.ino` |
| Supabase Host | `iqmrpwvbmfkhychhditg.supabase.co` | `.ino` — `#define SUPABASE_URL` |
| Supabase Project | `iqmrpwvbmfkhychhditg` | `app.js` + `backend/.env` |
| Supabase Service Key | **required**, was missing | `backend/.env` — `SUPABASE_SERVICE_KEY` |
| Backend base URL (automation only) | `app.js` — `BACKEND_BASE` (now defined) | edit if backend moves |
| DHT11 Pin | GPIO 4 | `.ino` + wiring |
| Soil Moisture Pin | GPIO 34 | `.ino` + wiring |
| Rain Sensor Pin | GPIO 33 | `.ino` + wiring |
| Relay/Pump Pin | GPIO 16 (active-LOW) | `.ino` + wiring |
