# AgriSense AI — ESP32 DevKit V1 Wiring Guide

---

## ❓ QUESTION 1: How does the website connect to the ESP32?

**Short answer: Through Wi-Fi — but NOT directly. The website never talks to the ESP32 directly.**

### What "Initialize Node Pairing" actually does:
Clicking that button does **NOT** send anything to the ESP32. It just **registers the device ID in the Supabase cloud database** so the backend knows the device belongs to your account.

### The real connection flow:

```
                        YOUR HOME Wi-Fi NETWORK
                                │
               ┌────────────────┴────────────────┐
               │                                 │
         ESP32 board                        Your PC
               │                                 │
               │   Every 10s:                    │  Python backend running
               │   POST /api/telemetry ─────────►│  (python -m uvicorn ...)
               │                                 │
               │   Every 5s:                     │
               │   GET /api/device/command ◄─────│
               │                                 │
                                            ↕  WebSocket
                                       Your Browser
                                    (website / dashboard)
```

- **ESP32 ↔ Backend**: HTTP over your Wi-Fi (same network required)
- **Website ↔ Backend**: HTTP/WebSocket over network
- **No Bluetooth used anywhere**
- **No direct ESP32 ↔ Website connection** — they never talk to each other directly

### Summary table:

| What you do | What actually happens |
|-------------|----------------------|
| Power on ESP32 | ESP32 joins Wi-Fi → starts sending data to backend every 10s |
| Click "Initialize Node Pairing" | Your browser tells the backend: "add AGS-0001 to my account" → backend saves in Supabase cloud database |
| Open website on phone (different city) | Browser fetches your device list from Supabase → opens WebSocket to backend → sees live data |
| Click Pump ON | Browser → `POST /api/command` → backend → `device_commands` table → ESP32 polls every 5s → relay fires |

---

## ❓ QUESTION 2: D-pins vs GPIO pins — ESP32 DevKit V1

**Short answer: The number after "D" IS the GPIO number. D4 = GPIO4. They are the same thing.**

The physical label printed on your board (e.g. **D4**, **D33**, **D34**, **D16**) directly maps to the GPIO number used in code. There is no conversion needed — just use the number.

### Physical Board Layout — ESP32 DevKit V1 (30-pin / Type-C)

```
                    ┌─────────────────┐
                    │   [ USB-C ]     │
               3.3V │ ○             ○ │ GND
                EN  │ ○             ○ │ D23
               VP   │ ○  (GPIO36)  ○ │ D22
               VN   │ ○  (GPIO39)  ○ │ TX0  (GPIO1)
             ► D34  │ ○  [SOIL]   ○  │ RX0  (GPIO3)
             D35    │ ○             ○ │ D21
             D32    │ ○             ○ │ D19
           ► D33    │ ○  [RAIN]   ○  │ D18
             D25    │ ○             ○ │ D5
             D26    │ ○             ○ │ TX2  (GPIO17)
             D27    │ ○             ○ │ RX2  ← This is GPIO16 ★ [RELAY]
             D14    │ ○             ○ │ D4   ← [DHT11] ★
             D12    │ ○             ○ │ D2
             D13    │ ○             ○ │ D15
               GND  │ ○             ○ │ GND
               VIN  │ ○             ○ │ 3.3V
                    └─────────────────┘
                         ★ = pins used in this project
```

> **Note:** On some ESP32 DevKit V1 boards, GPIO16 is labeled **RX2** instead of **D16** — they are the exact same pin. Look for "RX2" or "IO16" on the right side of the board.

### Pin mapping for this project:

| What to connect | Board Label | Silkscreen says | GPIO in code | Side of board |
|----------------|-------------|-----------------|-------------|--------------|
| DHT11 DATA wire | **D4** | `D4` | GPIO 4 | Right side |
| Soil Moisture AOUT | **D34** | `D34` | GPIO 34 | Left side |
| Rain Sensor DO | **D33** | `D33` | GPIO 33 | Left side |
| Relay Module IN | **RX2 / D16** | `RX2` or `IO16` | GPIO 16 | Right side |
| All sensors VCC | **3.3V** | `3V3` | — | Either side |
| Relay VCC | **VIN** | `VIN` | 5V | Either side |
| All GND wires | **GND** | `GND` | — | Either side |

---

## SENSOR CONNECTIONS (step by step)

### 1. DHT11 — Air Temperature & Humidity

```
DHT11 module:              ESP32 board:
  VCC  ─────────────────►  3.3V  (3V3 pin)
  DATA ─────────────────►  D4    (right side, labeled D4)
  GND  ─────────────────►  GND

⚠️  Add a 10kΩ resistor between DATA and VCC (pull-up).
    Without it, readings will be wrong or NaN.
```

### 2. Capacitive Soil Moisture Sensor (Analog)

```
Soil Sensor:               ESP32 board:
  VCC  ─────────────────►  3.3V  (3V3 pin)
  AOUT ─────────────────►  D34   (left side, labeled D34)
  GND  ─────────────────►  GND

ℹ️  GPIO34 is INPUT ONLY — no pull-up inside chip. That's fine, AOUT is an analog output.
ℹ️  Calibrate in .ino: dry air reading → SOIL_DRY_VALUE, submerged → SOIL_WET_VALUE
```

#### Disconnect calibration (required for the "online, no sensor data" feature)

The firmware also needs to tell a genuinely dry probe apart from **no probe plugged in at
all** — an unplugged GPIO34 floats, and what it reads when floating depends on your specific
wiring/board, so you must measure it once:

1. Flash the firmware and open the Serial Monitor at 115200 baud.
2. **Unplug the soil sensor.** Watch the `raw ADC` value printed each tick in the dashboard
   (`Soil Moisture: ... (raw ADC ####)`). Note it — this is the "disconnected" reading.
3. **Plug the probe back in**, leave it in dry air (not in soil). Note the raw ADC value again —
   this is the lowest reading you'll ever see with a real probe attached.
4. Open the `.ino` and set `SOIL_DISCONNECT_ADC` to a value between the two, closer to the
   disconnected reading, e.g. if unplugged reads ~20 and dry-air reads ~3600, `50` is a safe cutoff.
5. Re-flash. Unplug the probe again to confirm the dashboard now prints `[ DISCONNECTED ]` and the
   website shows `00` in green (online, no sensor) instead of a fake moisture percentage.

The default in the firmware (`SOIL_DISCONNECT_ADC 100`) is only a placeholder — it assumes a
floating pin reads near zero, which is common but not guaranteed on every board.

### 3. Rain Sensor Module (Digital Output)

```
Rain Sensor module:        ESP32 board:
  VCC  ─────────────────►  3.3V  (3V3 pin)
  DO   ─────────────────►  D33   (left side, labeled D33)
  GND  ─────────────────►  GND

ℹ️  DO = Digital Output. LOW = Rain detected. HIGH = Dry.
ℹ️  The AO (analog out) pin is unused — ignore it.
⚠️  This sensor CANNOT be health-checked. A disconnected/floating DO pin reads
    the same as "no rain" — there is no way to tell the two apart in software.
    It is intentionally left out of the sensors_ok / "online, no data" check.
```

### 4. Relay Module — Water Pump Control

```
Relay Module:              ESP32 board:
  VCC  ─────────────────►  VIN   (5V pin — NOT 3.3V, relay needs 5V)
  IN   ─────────────────►  RX2   (right side, labeled RX2 or IO16 = GPIO16)
  GND  ─────────────────►  GND

Relay screw terminals:
  COM  ─────────────────►  Live wire (+) from pump power supply
  NO   ─────────────────►  Wire going to pump positive terminal
  (Normally Open = pump OFF when no signal. Turns ON when relay fires.)

⚠️  Active-LOW relay: GPIO16 LOW → relay ON → pump runs
                      GPIO16 HIGH → relay OFF → pump stops
⚠️  NEVER connect mains (230V AC) yourself without proper knowledge.
    Use a DC pump with a 12V adapter for safety during testing.
```

---

## QUICK SCHEMATIC (text diagram)

```
ESP32 DevKit V1
├── 3.3V ────┬──── DHT11 VCC
│            ├──── Soil Sensor VCC
│            └──── Rain Sensor VCC
│
├── D4  ─────────── DHT11 DATA  (+ 10kΩ to 3.3V)
├── D34 ─────────── Soil Sensor AOUT
├── D33 ─────────── Rain Sensor DO
├── RX2 ─────────── Relay Module IN   (= GPIO 16)
│
├── VIN ─────────── Relay Module VCC  (5V)
│
└── GND ────┬──── DHT11 GND
            ├──── Soil Sensor GND
            ├──── Rain Sensor GND
            └──── Relay Module GND
```

---

## REQUIRED ARDUINO LIBRARIES

Install via **Arduino IDE → Sketch → Include Library → Manage Libraries**:

| Library | Author | Install name |
|---------|--------|-------------|
| DHT sensor library | Adafruit | `DHT sensor library` |
| Adafruit Unified Sensor | Adafruit | `Adafruit Unified Sensor` |
| ArduinoJson | Benoit Blanchon | `ArduinoJson` (install v6.x) |

> **WiFi** and **HTTPClient** come built-in with the ESP32 Arduino core — no extra install needed.

---

## ARDUINO IDE BOARD SETTINGS

Go to **Tools** menu:

| Setting | Value |
|---------|-------|
| Board | `ESP32 Dev Module` |
| Upload Speed | `921600` |
| CPU Frequency | `240MHz` |
| Port | COM port your ESP32 is on |

---

## SETUP CHECKLIST

- [ ] Wire all sensors as shown above
- [ ] Open `AgriSense_ESP32.ino` in Arduino IDE
- [ ] Edit **CONFIGURATION section** at the top of the `.ino`:
  - [ ] `WIFI_SSID` → your Wi-Fi network name
  - [ ] `WIFI_PASSWORD` → your Wi-Fi password
  - [ ] `BACKEND_URL` → `http://10.87.216.17:8000` (your PC IP)
  - [ ] `DEVICE_ID` → unique ID like `AGS-0001`
  - [ ] `DEVICE_PASSWORD` → `changeme`
- [ ] Install 3 libraries listed above
- [ ] Select Board: **ESP32 Dev Module**
- [ ] Click Upload
- [ ] Open Serial Monitor at **115200 baud** — you should see Wi-Fi connecting, then sensor readings
- [ ] Start Python backend: `python -m uvicorn main:app --host 0.0.0.0 --port 8000`
- [ ] Open website → Log in → Go to Connect page → Enter device ID → Click **Initialize Node Pairing**
- [ ] Dashboard should start showing live telemetry within 10 seconds

---

> Flashing the ESP32-CAM (separate board, no USB port, manual boot mode) is
> covered in [ESP32CAM_UPLOAD_GUIDE.md](ESP32CAM_UPLOAD_GUIDE.md).
