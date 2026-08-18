#ifndef AGRISENSE_CONFIG_H
#define AGRISENSE_CONFIG_H

// ═══════════════════════════════════════════════════════════════════════
// AgriSense AI — ESP32 Configuration
// ═══════════════════════════════════════════════════════════════════════
// Edit this file ONCE before uploading to your ESP32.
// Everything the firmware needs to know lives here.
// ═══════════════════════════════════════════════════════════════════════

// ── Wi-Fi Credentials ──────────────────────────────────────────────────
#define WIFI_SSID          "Your_Home_WiFi"
#define WIFI_PASSWORD      "Your_Password"

// ── Backend Server ─────────────────────────────────────────────────────
// IP address (or hostname) of the PC running the Python FastAPI server.
// Example: "http://192.168.1.10:8000"
#define BACKEND_URL        "http://192.168.1.10:8000"

// ── Device Identity ────────────────────────────────────────────────────
// Unique per unit — printed on the label/box. Never reuse across units.
#define DEVICE_ID          "AGS-0001"
#define DEVICE_PASSWORD    "changeme"

// ── Sensor Pin Assignments (ESP32 DevKit) ──────────────────────────────
// Refer to AgriSense_Full_System_Tutorial.md for wiring diagram.
#define DHT_PIN            4      // DHT22 — Air Temperature & Humidity (GPIO 4)
#define DHT_TYPE           DHT22  // DHT sensor type (DHT11 or DHT22)
#define SOIL_MOISTURE_PIN  34     // Capacitive Soil Moisture — Analog (GPIO 34)
#define DS18B20_PIN        5      // DS18B20 — Soil Temperature (GPIO 5)
#define RAIN_SENSOR_PIN    33     // Rain Sensor — Digital (GPIO 33)

// ── Relay / Actuator Pin Assignments ───────────────────────────────────
// 4-channel relay module (active-LOW: LOW = relay ON)
#define RELAY_PUMP_PIN     16     // Relay CH1 — Main Water Pump (GPIO 16)
#define RELAY_VALVE1_PIN   17     // Relay CH2 — Zone 1 Solenoid Valve (GPIO 17)
#define RELAY_FOGGER_PIN   18     // Relay CH3 — Misting Foggers (GPIO 18)
#define RELAY_LIGHTS_PIN   19     // Relay CH4 — Field LED Lighting (GPIO 19)

// ── Soil Moisture Calibration ──────────────────────────────────────────
// Measure the raw ADC reading with the sensor in dry air → SOIL_DRY_VALUE
// Submerge the probe in water → SOIL_WET_VALUE
// The firmware maps these to 0–100%.
#define SOIL_DRY_VALUE     4095   // ESP32 12-bit ADC max (dry air)
#define SOIL_WET_VALUE     1500   // Typical reading when submerged

// ── Timing ─────────────────────────────────────────────────────────────
#define TELEMETRY_INTERVAL_MS    10000   // Send sensor readings every 10 seconds
#define COMMAND_POLL_INTERVAL_MS  5000   // Poll backend for commands every 5 seconds

// ── Firmware Version ───────────────────────────────────────────────────
#define FIRMWARE_VERSION   "2.1.0"

#endif // AGRISENSE_CONFIG_H
