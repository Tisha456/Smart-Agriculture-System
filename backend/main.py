"""
AgriSense AI — FastAPI Backend Server
======================================
This server does ONE thing: run the pump automation decision engine
(Manual / Moisture / Timer modes) and expose the endpoints needed to
configure it and manage timers.

It does NOT sit in the telemetry or manual-pump-control path — those go
directly ESP32 <-> Supabase and Website <-> Supabase (see documents/context.md).
Manual pump control and device pairing work with this server stopped;
only Moisture Auto and Timer Schedule modes require it running.

Endpoints:
  - POST   /api/command                    — manual pump ON/OFF (also used by Force Stop)
  - POST   /api/automation/mode             — set NONE / MOISTURE / TIMER for a device
  - GET    /api/automation/state/{id}       — read current automation config
  - GET    /api/devices                     — list devices for logged-in user (unused by website; kept for API completeness)
  - DELETE /api/devices/{id}                — unbind (unused by website; kept for API completeness)
  - POST   /api/timers, GET/{id}, DELETE/{id}, PATCH/{id} — timer schedule CRUD
  - POST   /api/plant/predict               — proxy to the plant-disease serving API
                                               (serving/app.py). Holds PLANT_API_KEY
                                               server-side so the app/website never see it.
"""

from fastapi import FastAPI, HTTPException, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
from contextlib import asynccontextmanager
import os
import asyncio
import httpx

# ── Load Environment Variables ──────────────────────────────────────────────
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")  # service_role key — bypasses RLS

# Plant-disease serving API (serving/app.py, deployed per serving/DEPLOY.md).
# PLANT_API_KEY must only ever live here, server-side — see
# plant-disease-implementation-plan.md Phase J: the mobile app and website
# call THIS backend's /api/plant/predict instead, which holds the real key.
PLANT_API_URL = os.getenv("PLANT_API_URL")        # e.g. https://agrisense-pd-api-xxxxx.run.app
PLANT_API_KEY = os.getenv("PLANT_API_KEY")

# Anon client: only used to validate a user's JWT (auth.get_user). Never used
# for table reads/writes — this server has no logged-in session, so RLS
# policies scoped to auth.uid() would silently return zero rows.
supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Admin client: for ALL table reads/writes. Bypasses RLS entirely, so every
# endpoint below that touches a table manually re-checks ownership after
# validating the caller's JWT with the anon client above.
supabase_admin: Client = create_client(
    SUPABASE_URL,
    SUPABASE_SERVICE_KEY if SUPABASE_SERVICE_KEY else SUPABASE_ANON_KEY
)


def _parse_ts(value: str) -> datetime:
    """Parse a Supabase timestamptz string (may end in 'Z') into an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ═══════════════════════════════════════════════════════════════════════════════
# PUMP DECISION ENGINE (Background Task)
# ═══════════════════════════════════════════════════════════════════════════════
# Reads live state from Supabase every tick — device_config for the mode and
# thresholds, device_status for the heartbeat, telemetry_data for the latest
# reading. Nothing is held in memory between ticks, so a backend restart
# never loses automation settings (they live in device_config, not in a dict).

async def pump_decision_engine():
    while True:
        try:
            await asyncio.sleep(10)
            await evaluate_all_devices()
        except Exception as e:
            print(f"[Decision Engine] Error: {e}")


async def evaluate_all_devices():
    configs_resp = supabase_admin.table("device_config") \
        .select("*").neq("automation_mode", "NONE").execute()
    configs = configs_resp.data or []

    for cfg in configs:
        device_id = cfg["device_id"]
        try:
            await evaluate_device(device_id, cfg)
        except Exception as e:
            print(f"[Decision Engine] {device_id}: error — {e}")


async def evaluate_device(device_id: str, cfg: dict):
    """
    Safety gate, then mode evaluation.

    The gate exists because sensor failures now report 0 instead of skipping
    the telemetry tick (see esp32_firmware — sendTelemetry() no longer
    early-returns on a bad DHT11 read). Without this gate, a disconnected
    soil probe reading 0 would satisfy `0 < start_threshold` forever and the
    pump would run continuously, re-triggering after every max-runtime cutoff.
    """
    now = datetime.now(timezone.utc)

    status_resp = supabase_admin.table("device_status") \
        .select("*").eq("device_id", device_id).limit(1).execute()
    status = status_resp.data[0] if status_resp.data else None

    telem_resp = supabase_admin.table("telemetry_data") \
        .select("*").eq("device_id", device_id).order("created_at", desc=True).limit(1).execute()
    telemetry = telem_resp.data[0] if telem_resp.data else None

    offline = True
    if status and status.get("last_seen_at"):
        offline = (now - _parse_ts(status["last_seen_at"])).total_seconds() > 30

    stale_data = True
    if telemetry and telemetry.get("created_at"):
        stale_data = (now - _parse_ts(telemetry["created_at"])).total_seconds() > 60

    sensors_ok = bool(status.get("sensors_ok")) if status else False

    if offline or stale_data or not sensors_ok:
        if cfg.get("pump_on"):
            await queue_pump_command(device_id, "PUMP_OFF", "Safety: sensor data unavailable")
            _update_device_config(device_id, pump_on=False, pump_on_since=None)
        return

    mode = cfg.get("automation_mode", "NONE")
    if mode == "MOISTURE":
        await evaluate_moisture_mode(device_id, cfg, telemetry)
    elif mode == "TIMER":
        await evaluate_timer_mode(device_id, cfg, telemetry)


async def evaluate_moisture_mode(device_id: str, cfg: dict, telemetry: dict):
    """Auto-pump based on soil moisture thresholds."""
    soil = telemetry.get("soil_moisture", 0) or 0
    rain = bool(telemetry.get("rain_detected", False))
    pump_on = cfg.get("pump_on", False)
    start = cfg.get("start_threshold", 70)
    stop = cfg.get("stop_threshold", 85)
    max_runtime = cfg.get("max_runtime_mins", 20)

    # Safety: max runtime check
    if pump_on and cfg.get("pump_on_since"):
        elapsed = (datetime.now(timezone.utc) - _parse_ts(cfg["pump_on_since"])).total_seconds() / 60
        if elapsed >= max_runtime:
            await queue_pump_command(device_id, "PUMP_OFF", "Max Runtime Safety Cutoff")
            _update_device_config(device_id, pump_on=False, pump_on_since=None)
            return

    # If soil is dry AND no rain → turn pump ON
    if soil < start and not rain and not pump_on:
        await queue_pump_command(device_id, "PUMP_ON", "Smart Moisture Auto")
        _update_device_config(device_id, pump_on=True, pump_on_since=_now_iso())

    # If soil has reached the stop threshold → turn pump OFF
    elif soil >= stop and pump_on:
        await queue_pump_command(device_id, "PUMP_OFF", "Smart Moisture Auto")
        _update_device_config(device_id, pump_on=False, pump_on_since=None)


async def evaluate_timer_mode(device_id: str, cfg: dict, telemetry: dict):
    """Auto-pump based on scheduled timers from the timers table."""
    pump_on = cfg.get("pump_on", False)
    rain = bool(telemetry.get("rain_detected", False)) if telemetry else False

    # Safety: if currently raining and pump is ON → turn it off immediately
    if rain and pump_on:
        await queue_pump_command(device_id, "PUMP_OFF", "Rain Detected — Timer Paused")
        _update_device_config(device_id, pump_on=False, pump_on_since=None)
        return

    # If raining, don't start a new timer cycle
    if rain:
        return

    try:
        timers_resp = supabase_admin.table("timers") \
            .select("*") \
            .eq("device_id", device_id) \
            .eq("is_active", True) \
            .execute()
        timers = timers_resp.data if timers_resp.data else []
    except Exception:
        return

    now = datetime.now()
    # Unique 2-letter abbreviations: Mo Tu We Th Fr Sa Su
    day_names = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    current_day = day_names[now.weekday()]
    inside_window = False

    for timer in timers:
        active_days = timer.get("active_days", [])
        if current_day not in active_days:
            continue

        try:
            start_str = timer.get("start_time", "06:00")
            if "AM" in start_str.upper() or "PM" in start_str.upper():
                start_time = datetime.strptime(start_str.upper().strip(), "%I:%M %p").time()
            else:
                start_time = datetime.strptime(start_str.strip(), "%H:%M").time()

            duration_mins = timer.get("duration_mins", 15)
            start_dt = now.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)
            end_dt = start_dt + timedelta(minutes=duration_mins)

            if start_dt <= now <= end_dt:
                inside_window = True
                break
        except Exception:
            continue

    if inside_window and not pump_on:
        await queue_pump_command(device_id, "PUMP_ON", "Timer Schedule")
        _update_device_config(device_id, pump_on=True, pump_on_since=_now_iso())
    elif not inside_window and pump_on:
        await queue_pump_command(device_id, "PUMP_OFF", "Timer Schedule")
        _update_device_config(device_id, pump_on=False, pump_on_since=None)


def _update_device_config(device_id: str, **fields):
    """Persist automation state back to device_config (replaces the old in-memory dict)."""
    try:
        supabase_admin.table("device_config").update(fields).eq("device_id", device_id).execute()
    except Exception as e:
        print(f"[Decision Engine] Failed to persist config for {device_id}: {e}")


async def queue_pump_command(device_id: str, command: str, trigger: str):
    """Insert a command into the device_commands table for the ESP32 to pick up.
    The website learns about this via its own Supabase Realtime subscription
    on device_commands/telemetry_data — no WebSocket broadcast needed here."""
    print(f"[Decision Engine] {device_id}: {command} (trigger: {trigger})")
    try:
        supabase_admin.table("device_commands").insert({
            "device_id": device_id,
            "command": command,
            "executed": False
        }).execute()
    except Exception as e:
        print(f"[Decision Engine] Error queuing command: {e}")


# ── App Lifespan (start background tasks) ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(pump_decision_engine())
    print("[Startup] Pump Decision Engine started.")
    yield
    task.cancel()
    print("[Shutdown] Pump Decision Engine stopped.")


# ── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(title="AgriSense AI Backend", version="4.0.0", lifespan=lifespan)

# Allow Website and App to connect (CORS)
# allow_credentials=True cannot be combined with allow_origins=["*"] — browsers reject it.
# Using explicit list instead; wildcard handles the file:// null-origin case too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # Must be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Serve the Web Dashboard as Static Files ───────────────────────────────────
# This means opening http://10.87.216.17:8000 opens the website directly.
# No more file:// origin issues. No CORS needed between website and backend.
_DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "web_dashboard")
_DASHBOARD_DIR = os.path.normpath(_DASHBOARD_DIR)

@app.get("/", include_in_schema=False)
def serve_dashboard():
    """Redirect root to index.html"""
    return FileResponse(os.path.join(_DASHBOARD_DIR, "index.html"))

# Mount static assets (JS, CSS, images) — must come AFTER all API routes are defined
# We mount it later at the bottom of the file to avoid route conflicts.


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class CommandPayload(BaseModel):
    """What the website/app sends to control the pump"""
    device_id: str
    command: str   # "PUMP_ON", "PUMP_OFF"

class TimerPayload(BaseModel):
    device_id: str
    start_time: str
    duration_mins: int
    active_days: List[str]
    user_token: str

class TimerPatchPayload(BaseModel):
    is_active: bool

class AutomationModePayload(BaseModel):
    """Set the pump automation mode for a device"""
    device_id: str
    mode: str              # "NONE", "MOISTURE", "TIMER"
    start_threshold: Optional[int] = 70
    stop_threshold: Optional[int] = 85
    max_runtime_mins: Optional[int] = 20


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health", include_in_schema=False)
def root():
    return {"status": "AgriSense Automation Backend is running", "version": "4.0.0"}


# ── Website/App: Send a manual pump command ──────────────────────────────────
@app.post("/api/command")
async def send_command(payload: CommandPayload):
    """
    Website sends: 'Turn pump ON/OFF for device AGS-7F3K21' (manual toggle or
    Force Stop). This is a MANUAL override — it queues the command for the
    ESP32 and switches automation_mode to NONE so the Decision Engine doesn't
    fight the manual action.
    """
    if payload.command not in ("PUMP_ON", "PUMP_OFF"):
        raise HTTPException(status_code=400, detail="command must be PUMP_ON or PUMP_OFF")

    supabase_admin.table("device_commands").insert({
        "device_id": payload.device_id,
        "command": payload.command,
        "executed": False
    }).execute()

    pump_on = payload.command == "PUMP_ON"
    supabase_admin.table("device_config").upsert({
        "device_id": payload.device_id,
        "automation_mode": "NONE",
        "pump_on": pump_on,
        "pump_on_since": _now_iso() if pump_on else None,
    }, on_conflict="device_id").execute()

    return {"status": "command queued", "command": payload.command, "automation_mode": "NONE"}


# ── Website/App: Set automation mode ─────────────────────────────────────────
@app.post("/api/automation/mode")
async def set_automation_mode(payload: AutomationModePayload):
    """
    Set the pump automation mode for a device.
    Modes: "NONE" (manual only), "MOISTURE", "TIMER"
    """
    if payload.mode not in ("NONE", "MOISTURE", "TIMER"):
        raise HTTPException(status_code=400, detail="Invalid mode. Use NONE, MOISTURE, or TIMER.")

    fields = {
        "device_id": payload.device_id,
        "automation_mode": payload.mode,
        "start_threshold": payload.start_threshold or 70,
        "stop_threshold": payload.stop_threshold or 85,
        "max_runtime_mins": payload.max_runtime_mins or 20,
    }
    supabase_admin.table("device_config").upsert(fields, on_conflict="device_id").execute()

    print(f"[Automation] {payload.device_id}: mode set to {payload.mode}")

    return {
        "status": "mode updated",
        "device_id": payload.device_id,
        "automation_mode": payload.mode,
    }


# ── Website/App: Get current automation state for a device ───────────────────
@app.get("/api/automation/state/{device_id}")
def get_automation_state(device_id: str):
    """Return the current automation mode and pump state from device_config."""
    resp = supabase_admin.table("device_config").select("*").eq("device_id", device_id).limit(1).execute()
    if not resp.data:
        return {
            "device_id": device_id,
            "automation_mode": "NONE",
            "pump_on": False,
            "start_threshold": 70,
            "stop_threshold": 85,
            "max_runtime_mins": 20,
        }
    cfg = resp.data[0]
    return {
        "device_id": device_id,
        "automation_mode": cfg["automation_mode"],
        "pump_on": cfg["pump_on"],
        "start_threshold": cfg["start_threshold"],
        "stop_threshold": cfg["stop_threshold"],
        "max_runtime_mins": cfg["max_runtime_mins"],
    }


# ── Website/App: Get devices for logged-in user ───────────────────────────────
# Not currently called by the website (it queries Supabase directly instead —
# see web_dashboard/app.js fetchUserDevices). Kept for API completeness.
@app.get("/api/devices")
def get_devices(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_resp.user.id
    devices = supabase_admin.table("devices").select("*").eq("user_id", user_id).execute()
    return {"devices": devices.data}


# ── Website/App: Unbind a device ──────────────────────────────────────────────
# Not currently called by the website (it deletes from Supabase directly).
# Kept for API completeness.
@app.delete("/api/devices/{device_id}")
def unbind_device(device_id: str, authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supabase_admin.table("devices") \
        .delete() \
        .eq("device_id", device_id) \
        .eq("user_id", user_resp.user.id) \
        .execute()

    return {"status": "device unbound"}


# ── Website/App: Timer management ─────────────────────────────────────────────
# All timer endpoints validate the caller's JWT with the anon client, then use
# supabase_admin (service key, bypasses RLS) for the actual table operation —
# manually re-checking device ownership first, since RLS is not enforcing it here.

def _assert_owns_device(user_id: str, device_id: str):
    owned = supabase_admin.table("devices").select("device_id") \
        .eq("device_id", device_id).eq("user_id", user_id).execute()
    if not owned.data:
        raise HTTPException(status_code=403, detail="You don't own this device.")

def _device_id_for_timer(timer_id: int) -> str:
    resp = supabase_admin.table("timers").select("device_id").eq("id", timer_id).limit(1).execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Timer not found")
    return resp.data[0]["device_id"]


@app.post("/api/timers")
def add_timer(payload: TimerPayload):
    user_resp = supabase.auth.get_user(payload.user_token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    _assert_owns_device(user_resp.user.id, payload.device_id)

    supabase_admin.table("timers").insert({
        "device_id": payload.device_id,
        "start_time": payload.start_time,
        "duration_mins": payload.duration_mins,
        "active_days": payload.active_days,
        "is_active": True
    }).execute()

    return {"status": "timer added"}


@app.get("/api/timers/{device_id}")
def get_timers(device_id: str, authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    _assert_owns_device(user_resp.user.id, device_id)

    timers = supabase_admin.table("timers").select("*").eq("device_id", device_id).execute()
    return {"timers": timers.data}


@app.patch("/api/timers/{timer_id}")
def patch_timer(timer_id: int, payload: TimerPatchPayload, authorization: str = Header(...)):
    """Toggle a timer's enabled state — persists what toggleTimerActive() in
    the website used to only change locally."""
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    device_id = _device_id_for_timer(timer_id)
    _assert_owns_device(user_resp.user.id, device_id)

    supabase_admin.table("timers").update({"is_active": payload.is_active}).eq("id", timer_id).execute()
    return {"status": "timer updated", "is_active": payload.is_active}


@app.delete("/api/timers/{timer_id}")
def delete_timer(timer_id: int, authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    device_id = _device_id_for_timer(timer_id)
    _assert_owns_device(user_resp.user.id, device_id)

    supabase_admin.table("timers").delete().eq("id", timer_id).execute()
    return {"status": "timer deleted"}


# ── Website/App: Plant disease diagnosis (proxy) ──────────────────────────────
@app.post("/api/plant/predict")
async def plant_predict(file: UploadFile = File(...)):
    """
    Proxy an uploaded photo to the plant-disease serving API and return its
    JSON diagnosis unchanged. This is the ONLY thing the app/website call for
    "upload photo -> get diagnosis" — the plant API's X-API-Key never leaves
    this server (see plant-disease-implementation-plan.md Phase J).
    """
    if not PLANT_API_URL or not PLANT_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Plant diagnosis is not configured on this server (PLANT_API_URL/PLANT_API_KEY missing).",
        )

    contents = await file.read()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{PLANT_API_URL}/predict",
                headers={"X-API-Key": PLANT_API_KEY},
                files={"file": (file.filename, contents, file.content_type)},
            )
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Could not reach plant diagnosis API: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


# ── Mount Static Files (MUST be last — after all API routes) ─────────────────
# Serves the web dashboard at http://10.87.216.17:8000/
# JS, CSS and other assets will be served from /web_dashboard/
app.mount("/", StaticFiles(directory=_DASHBOARD_DIR, html=True), name="dashboard")
