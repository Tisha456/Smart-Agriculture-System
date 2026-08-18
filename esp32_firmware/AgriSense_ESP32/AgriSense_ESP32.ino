/*
 * ═══════════════════════════════════════════════════════════════════════════
 * AgriSense AI — ESP32 Sensor Node Firmware  v2.1.0
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * HARDWARE CONNECTED TO THIS ESP32:
 *   • DHT11            — Air Temperature & Humidity       (GPIO 4)
 *   • Soil Moisture    — Capacitive analog sensor         (GPIO 34)
 *   • Rain Sensor      — Digital output module            (GPIO 33)
 *   • 1-Channel Relay  — Water Pump control               (GPIO 16)
 *
 * NOT CONNECTED (sent as 0 / estimated):
 *   • DS18B20 (soil temp)  → Estimated from air temp (−2.5°C offset)
 *   • Solar / PAR sensor   → Sent as 0
 *   • NPK sensor           → Not used (dashboard shows "--")
 *   • ESP32-CAM             → Separate module, not part of this node
 *
 * WHAT THIS FIRMWARE DOES:
 *   1. Reads all sensors every 10 seconds.
 *   2. Builds a JSON payload matching the backend TelemetryPayload model:
 *        { device_id, device_password, soil_moisture, temperature,
 *          humidity, soil_temp, solar_radiation, rain_detected,
 *          battery_pct, rssi }
 *   3. POSTs the JSON to the Python backend → POST /api/telemetry
 *   4. Polls for relay commands every 5 seconds → GET /api/device/command/{id}
 *   5. Actuates the pump relay based on commands (PUMP_ON / PUMP_OFF).
 *
 * REQUIRED ARDUINO LIBRARIES (install via Library Manager):
 *   • DHT sensor library   (by Adafruit)
 *   • Adafruit Unified Sensor (by Adafruit) — dependency for DHT
 *   • ArduinoJson          (by Benoit Blanchon)
 *   • WiFi                 (built-in with ESP32 core)
 *   • HTTPClient           (built-in with ESP32 core)
 *
 * BOARD SETTING:  ESP32 Dev Module  (Arduino IDE → Tools → Board)
 * ═══════════════════════════════════════════════════════════════════════════
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ── Project configuration (edit config.h before uploading) ──────────────
#include "../config.h"

// ═══════════════════════════════════════════════════════════════════════════
// SENSOR OBJECTS
// ═══════════════════════════════════════════════════════════════════════════

// DHT11 — Air temperature & humidity
DHT dht(DHT_PIN, DHT_TYPE);

// ═══════════════════════════════════════════════════════════════════════════
// TIMING
// ═══════════════════════════════════════════════════════════════════════════
unsigned long lastTelemetryMs   = 0;
unsigned long lastCommandPollMs = 0;
unsigned long bootTimeMs        = 0;

// ═══════════════════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  Serial.println();
  Serial.println("═══════════════════════════════════════");
  Serial.println("  AgriSense AI — ESP32 Firmware v" FIRMWARE_VERSION);
  Serial.println("  Hardware: DHT11 | Soil Moisture | Rain | Pump Relay");
  Serial.println("═══════════════════════════════════════");

  // ── Sensor pins ────────────────────────────────────────────────────────
  dht.begin();
  pinMode(SOIL_MOISTURE_PIN, INPUT);
  pinMode(RAIN_SENSOR_PIN, INPUT);

  // ── Relay pin (active-LOW — start with relay OFF = HIGH) ──────────────
  pinMode(RELAY_PUMP_PIN, OUTPUT);
  digitalWrite(RELAY_PUMP_PIN, HIGH);   // Pump OFF at boot

  // ── Wi-Fi ──────────────────────────────────────────────────────────────
  connectToWiFi();

  bootTimeMs = millis();
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN LOOP
// ═══════════════════════════════════════════════════════════════════════════
void loop() {
  // Reconnect Wi-Fi if it drops
  if (WiFi.status() != WL_CONNECTED) {
    connectToWiFi();
  }

  unsigned long now = millis();

  // ── Send telemetry every TELEMETRY_INTERVAL_MS (10 s) ─────────────────
  if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryMs = now;
    sendTelemetry();
  }

  // ── Poll for commands every COMMAND_POLL_INTERVAL_MS (5 s) ────────────
  if (now - lastCommandPollMs >= COMMAND_POLL_INTERVAL_MS) {
    lastCommandPollMs = now;
    pollForCommands();
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// WI-FI CONNECTION
// ═══════════════════════════════════════════════════════════════════════════
void connectToWiFi() {
  Serial.print("[WiFi] Connecting to ");
  Serial.print(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 40) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(" Connected!");
    Serial.print("[WiFi] IP Address: ");
    Serial.println(WiFi.localIP());
    Serial.print("[WiFi] RSSI: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    Serial.println(" FAILED — will retry in loop.");
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// READ ALL SENSORS & POST TO BACKEND
// ═══════════════════════════════════════════════════════════════════════════
void sendTelemetry() {

  // ── 1. Read DHT11 (air temperature & humidity) ────────────────────────
  float humidity    = dht.readHumidity();
  float temperature = dht.readTemperature();   // Celsius

  if (isnan(humidity) || isnan(temperature)) {
    Serial.println("[Sensor] DHT11 read failed — skipping this cycle.");
    return;   // Don't send corrupt data
  }

  // ── 2. Read soil moisture (analog → percentage) ───────────────────────
  //    ESP32 ADC is 12-bit (0–4095). We map dry/wet calibration values
  //    from config.h to a 0–100% range.
  int rawSoil = analogRead(SOIL_MOISTURE_PIN);
  float soilMoisture = map(rawSoil, SOIL_DRY_VALUE, SOIL_WET_VALUE, 0, 100);
  soilMoisture = constrain(soilMoisture, 0.0, 100.0);

  // ── 3. Estimate soil temperature from air temperature ─────────────────
  //    No DS18B20 wired — use the offset defined in config.h
  float soilTemp = temperature + SOIL_TEMP_OFFSET;

  // ── 4. Read rain sensor (digital: LOW = rain detected) ────────────────
  bool rainDetected = (digitalRead(RAIN_SENSOR_PIN) == LOW);

  // ── 5. System info ────────────────────────────────────────────────────
  int rssi = WiFi.RSSI();

  // ── Print to Serial Monitor ───────────────────────────────────────────
  Serial.println("───────────── Telemetry ─────────────");
  Serial.printf("  Soil Moisture : %.1f %%\n", soilMoisture);
  Serial.printf("  Air Temp      : %.1f °C  (DHT11)\n", temperature);
  Serial.printf("  Humidity      : %.1f %%  (DHT11)\n", humidity);
  Serial.printf("  Soil Temp     : %.1f °C  (estimated)\n", soilTemp);
  Serial.printf("  Rain          : %s\n", rainDetected ? "YES" : "NO");
  Serial.printf("  RSSI          : %d dBm\n", rssi);
  Serial.printf("  Raw Soil ADC  : %d\n", rawSoil);
  Serial.println("─────────────────────────────────────");

  // ── 6. Build JSON payload ─────────────────────────────────────────────
  //    This MUST match the backend TelemetryPayload model exactly:
  //      device_id, device_password, soil_moisture, temperature,
  //      humidity, soil_temp, solar_radiation, rain_detected,
  //      battery_pct, rssi
  StaticJsonDocument<512> doc;
  doc["device_id"]        = DEVICE_ID;
  doc["device_password"]  = DEVICE_PASSWORD;
  doc["soil_moisture"]    = soilMoisture;
  doc["temperature"]      = temperature;
  doc["humidity"]         = humidity;
  doc["soil_temp"]        = soilTemp;
  doc["solar_radiation"]  = 0.0;          // No solar/PAR sensor wired
  doc["rain_detected"]    = rainDetected;
  doc["battery_pct"]      = 100.0;        // USB-powered — always 100%
  doc["rssi"]             = rssi;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  // ── 7. HTTP POST to backend ───────────────────────────────────────────
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[HTTP] WiFi not connected — skipping POST.");
    return;
  }

  HTTPClient http;
  String url = String(BACKEND_URL) + "/api/telemetry";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);   // 5-second timeout

  int httpCode = http.POST(jsonPayload);

  if (httpCode == 200) {
    Serial.println("[HTTP] Telemetry sent OK ✓");
  } else if (httpCode < 0) {
    Serial.printf("[HTTP] Connection failed: %s\n", http.errorToString(httpCode).c_str());
  } else {
    Serial.printf("[HTTP] Telemetry POST error — HTTP %d\n", httpCode);
    String resp = http.getString();
    Serial.println("[HTTP] Response: " + resp);
  }
  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════
// POLL BACKEND FOR PUMP COMMANDS
// ═══════════════════════════════════════════════════════════════════════════
void pollForCommands() {
  if (WiFi.status() != WL_CONNECTED) return;

  HTTPClient http;
  String url = String(BACKEND_URL) + "/api/device/command/" + DEVICE_ID;
  http.begin(url);
  http.setTimeout(5000);

  int httpCode = http.GET();

  if (httpCode == 200) {
    String response = http.getString();

    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, response);

    if (!err && !doc["command"].isNull()) {
      String command = doc["command"].as<String>();
      Serial.printf("[CMD] Received command: %s\n", command.c_str());
      executeCommand(command);
    }
  } else if (httpCode < 0) {
    Serial.printf("[CMD] Connection failed: %s\n", http.errorToString(httpCode).c_str());
  } else {
    Serial.printf("[CMD] Poll error — HTTP %d\n", httpCode);
  }
  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════
// EXECUTE A RELAY COMMAND
// ═══════════════════════════════════════════════════════════════════════════
void executeCommand(String command) {
  // Active-LOW relay: LOW = relay ON, HIGH = relay OFF

  if (command == "PUMP_ON") {
    digitalWrite(RELAY_PUMP_PIN, LOW);
    Serial.println("[Relay] Water Pump → ON");
  }
  else if (command == "PUMP_OFF") {
    digitalWrite(RELAY_PUMP_PIN, HIGH);
    Serial.println("[Relay] Water Pump → OFF");
  }
  else {
    Serial.println("[CMD] Unknown command: " + command);
  }
}