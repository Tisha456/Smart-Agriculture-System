# AgriSense AI — ESP32 DevKit Wiring & System Guide

## Board: ESP32 DevKit V1 (ESP-WROOM-32)

---

## SENSOR CONNECTIONS

### 1. DHT22 — Air Temperature & Humidity
| DHT22 Pin | ESP32 Board Pin | GPIO # | Notes |
|-----------|-----------------|--------|-------|
| VCC       | 3.3V            | 3.3V   | Power from ESP32 3.3V |
| DATA      | **D4**          | GPIO 4 | Add 10kΩ pull-up resistor between DATA and VCC |
| GND       | GND             | GND    | Common ground |

### 2. Capacitive Soil Moisture Sensor (Analog)
| Sensor Pin | ESP32 Board Pin | GPIO # | Notes |
|------------|-----------------|--------|-------|
| VCC        | 3.3V            | 3.3V   | Power from 3.3V |
| AOUT       | **D34**         | GPIO 34 | 12-bit ADC input (0–4095) |
| GND        | GND             | GND    | Common ground |

> **Calibration in `config.h`:**
> - Measure raw ADC in dry air → set `SOIL_DRY_VALUE` (Default: 4095)
> - Submerge probe in water → set `SOIL_WET_VALUE` (Default: ~1500)

### 3. DS18B20 — Soil Temperature (Waterproof Probe)
| Sensor Pin | ESP32 Board Pin | GPIO # | Notes |
|------------|-----------------|--------|-------|
| VCC (Red)  | 3.3V            | 3.3V   | Power from 3.3V |
| DATA (Yellow) | **D5**       | GPIO 5 | Add 4.7kΩ pull-up resistor between DATA and VCC |
| GND (Black)| GND             | GND    | Common ground |

> *If DS18B20 is not connected, firmware automatically estimates soil temperature from air temperature (−2.5°C offset).*

### 4. Rain Sensor Module (Digital Output)
| Sensor Pin | ESP32 Board Pin | GPIO # | Notes |
|------------|-----------------|--------|-------|
| VCC        | 3.3V            | 3.3V   | Power from 3.3V |
| DO         | **D33**         | GPIO 33 | Digital output: LOW = Rain detected |
| GND        | GND             | GND    | Common ground |

---

## ACTUATOR / RELAY CONNECTIONS

> Using a 4-channel 5V relay module (active-LOW: LOW = relay ON).
> Power the relay module VCC pin from the ESP32 **VIN (5V)** pin or external 5V adapter.

| Relay Channel | ESP32 Pin | GPIO # | Controls              | Dashboard Control Label |
|---------------|-----------|--------|-----------------------|-------------------------|
| Channel 1     | **D16**   | GPIO 16 | Main Water Pump       | Relay Water Pump Master |
| Channel 2     | **D17**   | GPIO 17 | Zone 1 Solenoid Valve | Zone 1 Valve            |
| Channel 3     | **D18**   | GPIO 18 | Misting Foggers       | High-Pressure Foggers   |
| Channel 4     | **D19**   | GPIO 19 | Field LED Lighting    | Perimeter LED Lights    |

> **Relay Load Wiring (Pump / Solenoid Valve):**
> - **COM** → Live wire from AC / DC power source
> - **NO (Normally Open)** → Wire to Pump / Solenoid Valve
> - **Relay GND** → ESP32 GND

---

## FULL PIN SUMMARY SCHEMATIC

```
ESP32 GPIO 4   ──→ DHT22 DATA         (+ 10kΩ pull-up to 3.3V)
ESP32 GPIO 34  ──→ Soil Moisture AOUT  (Analog input)
ESP32 GPIO 5   ──→ DS18B20 DATA       (+ 4.7kΩ pull-up to 3.3V)
ESP32 GPIO 33  ──→ Rain Sensor DO      (Digital input)

ESP32 GPIO 16  ──→ Relay CH1 IN (Main Water Pump)
ESP32 GPIO 17  ──→ Relay CH2 IN (Zone 1 Solenoid Valve)
ESP32 GPIO 18  ──→ Relay CH3 IN (Misting Foggers)
ESP32 GPIO 19  ──→ Relay CH4 IN (Field LED Lights)

ESP32 3.3V     ──→ VCC of DHT22, Soil Sensor, DS18B20, Rain Sensor
ESP32 VIN (5V) ──→ VCC of 4-Channel Relay Module
ESP32 GND      ──→ All Sensor GNDs + Relay Module GND
```

---

## REQUIRED ARDUINO LIBRARIES

Install these via **Arduino IDE → Sketch → Include Library → Manage Libraries**:

| Library | Author | Purpose |
|---------|--------|---------|
| DHT sensor library | Adafruit | Read DHT22 temperature & humidity |
| Adafruit Unified Sensor | Adafruit | Dependency for DHT library |
| OneWire | Paul Stoffregen | OneWire bus communication |
| DallasTemperature | Miles Burton | DS18B20 temperature sensor |
| ArduinoJson | Benoit Blanchon | Build/parse JSON payloads |

> **WiFi** and **HTTPClient** are built-in with the ESP32 Arduino core — no separate install needed.

---

## DATA & CONTROL FLOW

```
 [Sensors] ──→ Reads every 10s ──→ ESP32 ──→ HTTP POST /api/telemetry ──→ Python Backend
                                                                                │
   Web Dashboard ◄── Live WebSocket (/ws/device_id) ◄──────────────────────────┘
   & Mobile App  ─── HTTP POST /api/command ──────────→ Queued in Backend ──→ ESP32 polls GET /api/device/command
```

---

## SETUP CHECKLIST

1. [ ] Open `esp32_firmware/config.h` and set your Wi-Fi SSID & password
2. [ ] Set `BACKEND_URL` to the IP of the PC running the Python server
3. [ ] Set a unique `DEVICE_ID` and `DEVICE_PASSWORD` for this unit
4. [ ] (Optional) Calibrate `SOIL_DRY_VALUE` and `SOIL_WET_VALUE`
5. [ ] In Arduino IDE: Select board **ESP32 Dev Module**
6. [ ] Install the required libraries listed above
7. [ ] Upload `AgriSense_ESP32.ino` to the ESP32 via USB
8. [ ] Open Serial Monitor (115200 baud) to verify sensor readings
