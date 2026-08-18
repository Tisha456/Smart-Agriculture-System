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
//
//  YOUR HARDWARE:
//    • DHT11           → Air Temperature & Humidity
//    • Soil Moisture   → Capacitive analog sensor
//    • Rain Sensor     → Digital output module
//    • Relay (1-ch)    → Water Pump control
//    • ESP32-CAM       → Separate module (not wired to this ESP32)
//
#define DHT_PIN            4      // DHT11 DATA pin → GPIO 4
#define DHT_TYPE           DHT11  // DHT11 sensor (not DHT22)
#define SOIL_MOISTURE_PIN  34     // Soil Moisture Sensor AOUT → GPIO 34 (ADC)
#define RAIN_SENSOR_PIN    33     // Rain Sensor DO → GPIO 33 (Digital)

// ── Relay / Actuator Pin Assignment ────────────────────────────────────
// Single-channel relay module (active-LOW: LOW = relay ON)
#define RELAY_PUMP_PIN     16     // Relay IN → GPIO 16 (Water Pump)

// ── Soil Moisture Calibration ──────────────────────────────────────────
// Measure the raw ADC reading with the sensor in dry air → SOIL_DRY_VALUE
// Submerge the probe in water → SOIL_WET_VALUE
// The firmware maps these to 0–100%.
#define SOIL_DRY_VALUE     4095   // ESP32 12-bit ADC max (dry air)
#define SOIL_WET_VALUE     1500   // Typical reading when submerged in water

// ── Soil Temperature Offset ────────────────────────────────────────────
// No DS18B20 probe wired — soil temp is estimated from air temperature.
// Soil is typically a few degrees cooler than ambient air.
#define SOIL_TEMP_OFFSET   -2.5   // Estimated soil temp = air temp + offset

// ── Timing ─────────────────────────────────────────────────────────────
#define TELEMETRY_INTERVAL_MS    10000   // Send sensor readings every 10 seconds
#define COMMAND_POLL_INTERVAL_MS  5000   // Poll backend for commands every 5 seconds

// ── Firmware Version ───────────────────────────────────────────────────
#define FIRMWARE_VERSION   "2.1.0"

#endif // AGRISENSE_CONFIG_H
