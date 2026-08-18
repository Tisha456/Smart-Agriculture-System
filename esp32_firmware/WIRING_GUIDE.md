# AgriSense AI — ESP8266MOD / NodeMCU Wiring & System Guide

## Board: NodeMCU 1.0 (ESP-12E Module) / ESP8266MOD

---

## SENSOR CONNECTIONS

### 1. DHT11 — Temperature & Humidity
| DHT11 Pin | NodeMCU Board Pin | ESP8266 GPIO # | Notes |
|-----------|-------------------|----------------|-------|
| VCC       | 3.3V              | 3.3V           | Power from NodeMCU 3.3V |
| DATA      | **D2**            | GPIO 4         | Add 10kΩ pull-up resistor between DATA and VCC |
| GND       | GND               | GND            | Common ground |

### 2. Capacitive Soil Moisture Sensor (Analog)
| Sensor Pin | NodeMCU Board Pin | ESP8266 GPIO # | Notes |
|------------|-------------------|----------------|-------|
| VCC        | 3.3V              | 3.3V           | Power from 3.3V |
| AOUT       | **A0**            | ADC0           | Single 10-bit analog input on ESP8266 (0–1023) |
| GND        | GND               | GND            | Common ground |

> **Calibration in `config.h`:**
> - Measure raw ADC in dry air → set `SOIL_DRY_VALUE` (Default: ~880)
> - Submerge probe in water → set `SOIL_WET_VALUE` (Default: ~400)

### 3. Rain Sensor Module (Digital Output)
| Sensor Pin | NodeMCU Board Pin | ESP8266 GPIO # | Notes |
|------------|-------------------|----------------|-------|
| VCC        | 3.3V              | 3.3V           | Power from 3.3V |
| DO         | **D6**            | GPIO 12        | Digital output: LOW = Rain detected |
| GND        | GND               | GND            | Common ground |

> *Note: Soil temperature is calculated automatically in firmware from ambient temperature (-2.5°C offset). No DS18B20 sensor required.*

---

## ACTUATOR / RELAY CONNECTIONS

> Using a 4-channel 5V relay module (active-low: LOW = relay ON).
> Power the relay module VCC pin from the NodeMCU **VIN (5V)** pin or external 5V adapter.

| Relay Channel | NodeMCU Pin | ESP8266 GPIO # | Controls              | Dashboard Control Label |
|---------------|-------------|----------------|-----------------------|-------------------------|
| Channel 1     | **D1**      | GPIO 5         | Main Water Pump       | Relay Water Pump Master |
| Channel 2     | **D5**      | GPIO 14        | Zone 1 Solenoid Valve | Zone 1 Valve            |
| Channel 3     | **D7**      | GPIO 13        | Misting Foggers       | High-Pressure Foggers   |
| Channel 4     | **D8**      | GPIO 15        | Field LED Lighting    | Perimeter LED Lights    |

> **Relay Load Wiring (Pump / Solenoid Valve):**
> - **COM** → Live wire from AC / DC power source
> - **NO (Normally Open)** → Wire to Pump / Solenoid Valve
> - **Relay GND** → NodeMCU GND

---

## FULL PIN SUMMARY SCHEMATIC

```
NodeMCU D2  (GPIO 4)  ──→ DHT22 DATA (+ 10kΩ pull-up to 3.3V)
NodeMCU A0  (ADC0)    ──→ Soil Moisture Sensor AOUT
NodeMCU D6  (GPIO 12) ──→ Rain Sensor DO

NodeMCU D1  (GPIO 5)  ──→ Relay CH1 IN (Main Water Pump)
NodeMCU D5  (GPIO 14) ──→ Relay CH2 IN (Zone 1 Solenoid Valve)
NodeMCU D7  (GPIO 13) ──→ Relay CH3 IN (Misting Foggers)
NodeMCU D8  (GPIO 15) ──→ Relay CH4 IN (Field Lights)

NodeMCU 3.3V          ──→ VCC of DHT22, Soil Sensor, Rain Sensor
NodeMCU VIN (5V)      ──→ VCC of 4-Channel Relay Module
NodeMCU GND           ──→ All Sensor GNDs + Relay Module GND
```

---

## DATA & CONTROL FLOW

```
 [Sensors] ──→ Reads every 10s ──→ NodeMCU ESP8266 ──→ HTTP POST /api/telemetry ──→ Python Backend
                                                                                         │
   Web Dashboard ◄── Live WebSocket (/ws/device_id) ◄────────────────────────────────────┘
   & Mobile App  ─── HTTP POST /api/command ──────────→ Queued in Backend ──→ NodeMCU polls GET /api/device/command
```
