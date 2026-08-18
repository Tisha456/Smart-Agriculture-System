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
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from supabase import create_client, Client
from dotenv import load_dotenv
import os
import json
import asyncio

# ── Load Environment Variables ──────────────────────────────────────────────
load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# ── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(title="AgriSense AI Backend", version="1.0.0")

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
    command: str   # "PUMP_ON", "PUMP_OFF", "VALVE1_ON", "VALVE1_OFF", etc.

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


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return {"status": "AgriSense Backend is running", "version": "1.0.0"}


# ── ESP32: Send sensor data ──────────────────────────────────────────────────
@app.post("/api/telemetry")
async def receive_telemetry(payload: TelemetryPayload):
    """
    The ESP32 calls this every 10 seconds.
    1. We verify the device exists in Supabase.
    2. We save the reading to telemetry_data table.
    3. We instantly broadcast the reading to all connected website/app clients.
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

    # Step 3: Broadcast live to website/app via WebSocket
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


# ── Website/App: Send a pump command ─────────────────────────────────────────
@app.post("/api/command")
def send_command(payload: CommandPayload):
    """
    Website or App sends: 'Turn pump ON for device AGS-7F3K21'
    We save it to the database. ESP32 will pick it up in ≤5 seconds.
    """
    supabase.table("device_commands").insert({
        "device_id": payload.device_id,
        "command": payload.command,
        "executed": False
    }).execute()

    return {"status": "command queued", "command": payload.command}


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
    
    Usage: ws://your-server:8000/ws/AGS-7F3K21
    """
    await manager.connect(device_id, websocket)
    try:
        while True:
            # Keep connection alive
            await asyncio.sleep(30)
            await websocket.send_json({"type": "ping"})
    except WebSocketDisconnect:
        manager.disconnect(device_id, websocket)
