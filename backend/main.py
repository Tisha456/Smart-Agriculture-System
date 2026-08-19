"""
AgriSense AI — FastAPI Backend Server
======================================
One server handles:
  - ESP32 sending sensor data (POST /api/telemetry)
  - ESP32 polling for commands (GET /api/device/command/{device_id})
  - Website/App sending pump commands (POST /api/command)
  - Website/App live data via WebSocket (/ws/{device_id})
  - Device binding/unbinding
  - Timer management
  - Pump Automation Engine (Manual / Moisture / Timer modes)
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client
from dotenv import load_dotenv
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
import os
import json
import asyncio

# ── Load Environment Variables ──────────────────────────────────────────────
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ═══════════════════════════════════════════════════════════════════════════════
# IN-MEMORY DEVICE STATE (per-device pump automation state)
# ═══════════════════════════════════════════════════════════════════════════════
# Tracks automation_mode, thresholds, and last pump state for each device.
# This avoids needing a new Supabase column for now.
#
# automation_mode:
#   "NONE"     → Manual only. Backend does nothing automatically.
#   "MOISTURE" → Auto-pump based on soil moisture thresholds.
#   "TIMER"    → Auto-pump based on scheduled timers.
#
device_state: dict[str, dict] = {}
# Example entry:
# "AGS-0001": {
#     "automation_mode": "NONE",
#     "start_threshold": 70,
#     "stop_threshold": 85,
#     "max_runtime_mins": 20,
#     "pump_on": False,
#     "pump_on_since": None,        # datetime when pump was turned ON
#     "last_soil_moisture": 0,
#     "last_rain_detected": False,
# }

def get_device_state(device_id: str) -> dict:
    """Get or create default state for a device."""
    if device_id not in device_state:
        device_state[device_id] = {
            "automation_mode": "NONE",
            "start_threshold": 70,
            "stop_threshold": 85,
            "max_runtime_mins": 20,
            "pump_on": False,
            "pump_on_since": None,
            "last_soil_moisture": 0,
            "last_rain_detected": False,
        }
    return device_state[device_id]


# ═══════════════════════════════════════════════════════════════════════════════
# PUMP DECISION ENGINE (Background Task)
# ═══════════════════════════════════════════════════════════════════════════════

async def pump_decision_engine():
    """
    Runs every 10 seconds in the background.
    Evaluates each device's automation_mode and issues pump commands.

    LOGIC:
      - NONE (Manual): Do nothing. User controls pump directly.
      - MOISTURE: If soil < start_threshold AND no rain → PUMP_ON.
                  If soil >= stop_threshold → PUMP_OFF.
                  If max runtime exceeded → PUMP_OFF.
      - TIMER: Check current time against scheduled timers.
               If inside a timer window → PUMP_ON.
               If outside all windows → PUMP_OFF.

    In ALL modes, the manual switch can always override (handled by
    the /api/command endpoint, which sets mode to NONE on manual use).
    """
    while True:
        try:
            await asyncio.sleep(10)

            for device_id, ds in list(device_state.items()):
                mode = ds.get("automation_mode", "NONE")

                if mode == "NONE":
                    # Manual mode — do nothing
                    continue

                elif mode == "MOISTURE":
                    await evaluate_moisture_mode(device_id, ds)

                elif mode == "TIMER":
                    await evaluate_timer_mode(device_id, ds)

        except Exception as e:
            print(f"[Decision Engine] Error: {e}")


async def evaluate_moisture_mode(device_id: str, ds: dict):
    """Auto-pump based on soil moisture thresholds."""
    soil = ds.get("last_soil_moisture", 0)
    rain = ds.get("last_rain_detected", False)
    pump_on = ds.get("pump_on", False)
    start = ds.get("start_threshold", 70)
    stop = ds.get("stop_threshold", 85)
    max_runtime = ds.get("max_runtime_mins", 20)

    # Safety: max runtime check
    if pump_on and ds.get("pump_on_since"):
        elapsed = (datetime.now() - ds["pump_on_since"]).total_seconds() / 60
        if elapsed >= max_runtime:
            await queue_pump_command(device_id, "PUMP_OFF", "Max Runtime Safety Cutoff")
            ds["pump_on"] = False
            ds["pump_on_since"] = None
            return

    # If soil is dry AND no rain → turn pump ON
    if soil < start and not rain and not pump_on:
        await queue_pump_command(device_id, "PUMP_ON", "Smart Moisture Auto")
        ds["pump_on"] = True
        ds["pump_on_since"] = datetime.now()

    # If soil has reached the stop threshold → turn pump OFF
    elif soil >= stop and pump_on:
        await queue_pump_command(device_id, "PUMP_OFF", "Smart Moisture Auto")
        ds["pump_on"] = False
        ds["pump_on_since"] = None


async def evaluate_timer_mode(device_id: str, ds: dict):
    """Auto-pump based on scheduled timers from the timers table."""
    pump_on = ds.get("pump_on", False)
    rain    = ds.get("last_rain_detected", False)

    # Safety: if currently raining and pump is ON → turn it off immediately
    if rain and pump_on:
        await queue_pump_command(device_id, "PUMP_OFF", "Rain Detected — Timer Paused")
        ds["pump_on"] = False
        ds["pump_on_since"] = None
        return

    # If raining, don't start a new timer cycle
    if rain:
        return

    try:
        timers_resp = supabase.table("timers") \
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
            # Handle both "06:00" and "06:00 PM" formats
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
        ds["pump_on"] = True
        ds["pump_on_since"] = datetime.now()
    elif not inside_window and pump_on:
        await queue_pump_command(device_id, "PUMP_OFF", "Timer Schedule")
        ds["pump_on"] = False
        ds["pump_on_since"] = None



async def queue_pump_command(device_id: str, command: str, trigger: str):
    """Insert a command into the device_commands table for the ESP32 to pick up."""
    print(f"[Decision Engine] {device_id}: {command} (trigger: {trigger})")
    try:
        supabase.table("device_commands").insert({
            "device_id": device_id,
            "command": command,
            "executed": False
        }).execute()

        # Broadcast pump state change to connected dashboards
        pump_running = command == "PUMP_ON"
        await manager.broadcast(device_id, {
            "type": "pump_update",
            "pump_state": "RUNNING" if pump_running else "OFF",
            "trigger": trigger,
            "automation_mode": device_state.get(device_id, {}).get("automation_mode", "NONE"),
        })
    except Exception as e:
        print(f"[Decision Engine] Error queuing command: {e}")


# ── App Lifespan (start background tasks) ───────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start the Decision Engine background task
    task = asyncio.create_task(pump_decision_engine())
    print("[Startup] Pump Decision Engine started.")
    yield
    task.cancel()
    print("[Shutdown] Pump Decision Engine stopped.")


# ── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(title="AgriSense AI Backend", version="2.0.0", lifespan=lifespan)

# Allow Website and App to connect (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # In production, replace * with your website URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── WebSocket Connection Manager ─────────────────────────────────────────────
# Tracks all connected website/app clients per device
class ConnectionManager:
    def __init__(self):
        # { "AGS-7F3K21": [websocket1, websocket2, ...] }
        self.active: dict[str, list[WebSocket]] = {}

    async def connect(self, device_id: str, ws: WebSocket):
        await ws.accept()
        if device_id not in self.active:
            self.active[device_id] = []
        self.active[device_id].append(ws)

    def disconnect(self, device_id: str, ws: WebSocket):
        if device_id in self.active:
            self.active[device_id].remove(ws)

    async def broadcast(self, device_id: str, data: dict):
        """Send live data to all clients watching this device."""
        if device_id in self.active:
            dead = []
            for ws in self.active[device_id]:
                try:
                    await ws.send_json(data)
                except:
                    dead.append(ws)
            for ws in dead:
                self.active[device_id].remove(ws)

manager = ConnectionManager()


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class TelemetryPayload(BaseModel):
    """What the ESP32 sends every 10 seconds"""
    device_id: str
    device_password: str   # Security: ESP32 must authenticate itself
    soil_moisture: float
    temperature: float
    humidity: float
    soil_temp: Optional[float] = 0.0
    solar_radiation: Optional[float] = 0.0
    rain_detected: bool
    battery_pct: Optional[float] = 100.0
    rssi: Optional[int] = -70

class CommandPayload(BaseModel):
    """What the website/app sends to control the pump"""
    device_id: str
    command: str   # "PUMP_ON", "PUMP_OFF"

class BindDevicePayload(BaseModel):
    """What the website sends when adding a new ESP32"""
    device_id: str
    device_password: str
    device_name: str
    sector: str
    user_token: str   # Supabase JWT token from logged-in user

class TimerPayload(BaseModel):
    device_id: str
    start_time: str
    duration_mins: int
    active_days: List[str]
    user_token: str

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

@app.get("/")
def root():
    return {"status": "AgriSense Backend is running", "version": "2.0.0"}


# ── ESP32: Send sensor data ──────────────────────────────────────────────────
@app.post("/api/telemetry")
async def receive_telemetry(payload: TelemetryPayload):
    """
    The ESP32 calls this every 10 seconds.
    1. We verify the device exists in Supabase.
    2. We save the reading to telemetry_data table.
    3. We update the in-memory device state (for Decision Engine).
    4. We instantly broadcast the reading to all connected website/app clients.
    """
    # Step 1: Verify device exists
    device_check = supabase.table("devices").select("device_id").eq("device_id", payload.device_id).execute()
    if not device_check.data:
        raise HTTPException(status_code=403, detail="Device not registered. Bind it in the app first.")

    # Step 2: Save to database
    reading = {
        "device_id": payload.device_id,
        "soil_moisture": payload.soil_moisture,
        "temperature": payload.temperature,
        "humidity": payload.humidity,
        "soil_temp": payload.soil_temp,
        "solar_radiation": payload.solar_radiation,
        "rain_detected": payload.rain_detected,
        "battery_pct": payload.battery_pct,
        "rssi": payload.rssi,
    }
    supabase.table("telemetry_data").insert(reading).execute()

    # Step 3: Update in-memory state for Decision Engine
    ds = get_device_state(payload.device_id)
    ds["last_soil_moisture"] = payload.soil_moisture
    ds["last_rain_detected"] = payload.rain_detected

    # Step 4: Broadcast live to website/app via WebSocket
    await manager.broadcast(payload.device_id, {
        "type": "telemetry",
        **reading
    })

    return {"status": "ok"}


# ── ESP32: Poll for commands (runs every 5 seconds on ESP32) ─────────────────
@app.get("/api/device/command/{device_id}")
def get_command(device_id: str):
    """
    The ESP32 asks: 'Do you have any commands for me?'
    Returns the oldest unexecuted command and marks it done.
    """
    result = supabase.table("device_commands") \
        .select("*") \
        .eq("device_id", device_id) \
        .eq("executed", False) \
        .order("created_at") \
        .limit(1) \
        .execute()

    if not result.data:
        return {"command": None}

    cmd = result.data[0]

    # Mark as executed so ESP32 doesn't repeat it
    supabase.table("device_commands") \
        .update({"executed": True}) \
        .eq("id", cmd["id"]) \
        .execute()

    return {"command": cmd["command"]}


# ── Website/App: Send a manual pump command ──────────────────────────────────
@app.post("/api/command")
async def send_command(payload: CommandPayload):
    """
    Website or App sends: 'Turn pump ON/OFF for device AGS-7F3K21'
    This is a MANUAL override — it immediately:
      1. Queues the command for the ESP32.
      2. Switches automation_mode to NONE so the Decision Engine
         doesn't fight the manual action.
    """
    # Queue command
    supabase.table("device_commands").insert({
        "device_id": payload.device_id,
        "command": payload.command,
        "executed": False
    }).execute()

    # Switch to manual mode (disable any running automation)
    ds = get_device_state(payload.device_id)
    ds["automation_mode"] = "NONE"
    ds["pump_on"] = (payload.command == "PUMP_ON")
    if payload.command == "PUMP_ON":
        ds["pump_on_since"] = datetime.now()
    else:
        ds["pump_on_since"] = None

    # Broadcast mode change to dashboard
    await manager.broadcast(payload.device_id, {
        "type": "pump_update",
        "pump_state": "RUNNING" if payload.command == "PUMP_ON" else "OFF",
        "trigger": "Manual Override",
        "automation_mode": "NONE",
    })

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

    ds = get_device_state(payload.device_id)
    ds["automation_mode"] = payload.mode
    ds["start_threshold"] = payload.start_threshold or 70
    ds["stop_threshold"] = payload.stop_threshold or 85
    ds["max_runtime_mins"] = payload.max_runtime_mins or 20

    print(f"[Automation] {payload.device_id}: mode set to {payload.mode}")

    # Broadcast mode change
    await manager.broadcast(payload.device_id, {
        "type": "mode_update",
        "automation_mode": payload.mode,
        "start_threshold": ds["start_threshold"],
        "stop_threshold": ds["stop_threshold"],
        "max_runtime_mins": ds["max_runtime_mins"],
    })

    return {
        "status": "mode updated",
        "device_id": payload.device_id,
        "automation_mode": payload.mode,
    }


# ── Website/App: Get current automation state for a device ───────────────────
@app.get("/api/automation/state/{device_id}")
def get_automation_state(device_id: str):
    """Return the current automation mode and pump state."""
    ds = get_device_state(device_id)
    return {
        "device_id": device_id,
        "automation_mode": ds["automation_mode"],
        "pump_on": ds["pump_on"],
        "start_threshold": ds["start_threshold"],
        "stop_threshold": ds["stop_threshold"],
        "max_runtime_mins": ds["max_runtime_mins"],
    }


# ── Website/App: Bind a new ESP32 device ─────────────────────────────────────
@app.post("/api/devices/bind")
def bind_device(payload: BindDevicePayload):
    """
    Called when a farmer adds a new ESP32 to their account.
    Uses the user's JWT token to get their user_id from Supabase Auth.
    """
    # Get user from token
    user_resp = supabase.auth.get_user(payload.user_token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Invalid session. Please log in again.")

    user_id = user_resp.user.id

    # Check 4-device limit (also enforced by DB trigger, but good to check here too)
    existing = supabase.table("devices").select("id").eq("user_id", user_id).execute()
    if len(existing.data) >= 4:
        raise HTTPException(status_code=400, detail="Maximum 4 devices allowed per account.")

    # Add device
    supabase.table("devices").insert({
        "user_id": user_id,
        "device_id": payload.device_id,
        "device_name": payload.device_name,
        "sector": payload.sector,
    }).execute()

    return {"status": "device bound", "device_id": payload.device_id}


# ── Website/App: Get devices for logged-in user ───────────────────────────────
@app.get("/api/devices")
def get_devices(authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    user_id = user_resp.user.id
    devices = supabase.table("devices").select("*").eq("user_id", user_id).execute()
    return {"devices": devices.data}


# ── Website/App: Unbind a device ──────────────────────────────────────────────
@app.delete("/api/devices/{device_id}")
def unbind_device(device_id: str, authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supabase.table("devices") \
        .delete() \
        .eq("device_id", device_id) \
        .eq("user_id", user_resp.user.id) \
        .execute()

    return {"status": "device unbound"}


# ── Website/App: Get last 50 sensor readings for a device ────────────────────
@app.get("/api/telemetry/{device_id}")
def get_telemetry(device_id: str, authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    data = supabase.table("telemetry_data") \
        .select("*") \
        .eq("device_id", device_id) \
        .order("created_at", desc=True) \
        .limit(50) \
        .execute()

    return {"readings": data.data}


# ── Website/App: Timer management ─────────────────────────────────────────────
@app.post("/api/timers")
def add_timer(payload: TimerPayload):
    user_resp = supabase.auth.get_user(payload.user_token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supabase.table("timers").insert({
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

    timers = supabase.table("timers").select("*").eq("device_id", device_id).execute()
    return {"timers": timers.data}


@app.delete("/api/timers/{timer_id}")
def delete_timer(timer_id: int, authorization: str = Header(...)):
    token = authorization.replace("Bearer ", "")
    user_resp = supabase.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=401, detail="Unauthorized")

    supabase.table("timers").delete().eq("id", timer_id).execute()
    return {"status": "timer deleted"}


# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET — Live Data Stream
# ═══════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/{device_id}")
async def websocket_endpoint(websocket: WebSocket, device_id: str):
    """
    Website/App connects here to receive live sensor data instantly.
    When the ESP32 sends a reading, it shows up here within milliseconds.
    Also receives pump_update and mode_update events from the Decision Engine.
    
    Usage: ws://your-server:8000/ws/AGS-7F3K21
    """
    await manager.connect(device_id, websocket)

    # Send current automation state on connect
    ds = get_device_state(device_id)
    try:
        await websocket.send_json({
            "type": "mode_update",
            "automation_mode": ds["automation_mode"],
            "start_threshold": ds["start_threshold"],
            "stop_threshold": ds["stop_threshold"],
            "max_runtime_mins": ds["max_runtime_mins"],
        })
    except:
        pass

    try:
        while True:
            # Keep connection alive
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        manager.disconnect(device_id, websocket)
