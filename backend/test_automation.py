"""Self-check for the automation safety gate (main.automation_blocked_reason).
Run: python backend/test_automation.py
Needs backend/.env present (main.py builds a Supabase client at import) but
makes no network calls."""
from main import automation_blocked_reason as blocked

OK = {"dht": True, "soil": True, "rain": True}
DHT_DEAD = {"dht": False, "soil": True, "rain": True}
SOIL_DEAD = {"dht": True, "soil": False, "rain": True}

# Healthy device: both modes run.
assert blocked("MOISTURE", False, False, OK) is None
assert blocked("TIMER", False, False, OK) is None

# A dead DHT11 must NOT stop irrigation — neither mode reads temp/humidity.
# This is the regression that motivated splitting the gate per mode.
assert blocked("MOISTURE", False, False, DHT_DEAD) is None
assert blocked("TIMER", False, False, DHT_DEAD) is None

# A dead soil probe blocks MOISTURE (it reports 0, which would pin the pump
# on forever) but not TIMER, which never reads it.
assert blocked("MOISTURE", False, False, SOIL_DEAD) == "soil probe not reporting"
assert blocked("TIMER", False, False, SOIL_DEAD) is None

# Stale telemetry blocks MOISTURE only — TIMER treats missing rain data as dry.
assert blocked("MOISTURE", False, True, OK) == "telemetry stale"
assert blocked("TIMER", False, True, OK) is None

# Offline blocks everything, whatever the mode.
assert blocked("MOISTURE", True, False, OK) == "device offline"
assert blocked("TIMER", True, False, OK) == "device offline"
assert blocked("TIMER", True, True, SOIL_DEAD) == "device offline"

# Older firmware that never sent sensor_flags is treated as healthy, so
# upgrading the backend cannot silently disable a working device.
assert blocked("MOISTURE", False, False, {}) is None
assert blocked("TIMER", False, False, {}) is None

print("test_automation: all assertions passed")
