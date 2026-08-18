/*
 * ═══════════════════════════════════════════════════════════════════════════
 * AgriSense AI — ESP32 Firmware  v2.1.0
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * What this firmware does:
 *   1. Reads sensors every 10 seconds (soil moisture, air temp/humidity,
 *      soil temperature, rain state).
 *   2. POSTs the JSON reading to the Python backend (/api/telemetry).
 *   3. Polls the backend every 5 seconds for relay commands
 *      (/api/device/command/{device_id}) and actuates the relays.
 *
 * Required Libraries (install via Arduino Library Manager):
 *   - DHT sensor library   (by Adafruit)
 *   - OneWire              (by Paul Stoffregen)
 *   - DallasTemperature    (by Miles Burton)
 *   - ArduinoJson          (by Benoit Blanchon)
 *   - HTTPClient           (built-in with ESP32 Arduino core)
 *   - WiFi                 (built-in with ESP32 Arduino core)
 *
 * Board:  ESP32 Dev Module  (Arduino IDE → Tools → Board)
 * ═══════════════════════════════════════════════════════════════════════════
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>
#include <OneWire.h>
#include <DallasTemperature.h>

// ── Project configuration (edit config.h before uploading) ──────────────
#include "../config.h"

// ═══════════════════════════════════════════════════════════════════════════
// SENSOR OBJECTS
// ═══════════════════════════════════════════════════════════════════════════

// DHT22 — Air temperature & humidity
DHT dht(DHT_PIN, DHT_TYPE);

// DS18B20 — Soil temperature (OneWire bus)
OneWire oneWire(DS18B20_PIN);
DallasTemperature soilTempSensor(&oneWire);

// ═══════════════════════════════════════════════════════════════════════════
// TIMING
// ═══════════════════════════════════════════════════════════════════════════
unsigned long lastTelemetryMs  = 0;
unsigned long lastCommandPollMs = 0;

// ═══════════════════════════════════════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(115200);
  Serial.println();
  Serial.println("═══════════════════════════════════════");
  Serial.println("  AgriSense AI — ESP32 Firmware v" FIRMWARE_VERSION);
  Serial.println("═══════════════════════════════════════");

  // ── Sensor pins ────────────────────────────────────────────────────────
  dht.begin();
  soilTempSensor.begin();
  pinMode(SOIL_MOISTURE_PIN, INPUT);
  pinMode(RAIN_SENSOR_PIN, INPUT);

  // ── Relay pins (active-LOW — start with relays OFF = HIGH) ────────────
  pinMode(RELAY_PUMP_PIN,   OUTPUT);  digitalWrite(RELAY_PUMP_PIN,   HIGH);
  pinMode(RELAY_VALVE1_PIN, OUTPUT);  digitalWrite(RELAY_VALVE1_PIN, HIGH);
  pinMode(RELAY_FOGGER_PIN, OUTPUT);  digitalWrite(RELAY_FOGGER_PIN, HIGH);
  pinMode(RELAY_LIGHTS_PIN, OUTPUT);  digitalWrite(RELAY_LIGHTS_PIN, HIGH);

  // ── Wi-Fi ──────────────────────────────────────────────────────────────
  connectToWiFi();
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
  // ── 1. Read DHT22 (air temperature & humidity) ────────────────────────
  float humidity    = dht.readHumidity();
  float temperature = dht.readTemperature();   // Celsius

  if (isnan(humidity) || isnan(temperature)) {
    Serial.println("[Sensor] DHT22 read failed — skipping this cycle.");
    return;
  }

  // ── 2. Read soil moisture (analog → percentage) ───────────────────────
  int rawSoil = analogRead(SOIL_MOISTURE_PIN);
  float soilMoisture = map(rawSoil, SOIL_DRY_VALUE, SOIL_WET_VALUE, 0, 100);
  soilMoisture = constrain(soilMoisture, 0, 100);

  // ── 3. Read DS18B20 soil temperature ──────────────────────────────────
  soilTempSensor.requestTemperatures();
  float soilTemp = soilTempSensor.getTempCByIndex(0);
  if (soilTemp == DEVICE_DISCONNECTED_C) {
    soilTemp = temperature - 2.5;   // Fallback: estimate from air temp
    Serial.println("[Sensor] DS18B20 not found — using estimated soil temp.");
  }

  // ── 4. Read rain sensor (digital: LOW = rain detected) ────────────────
  bool rainDetected = (digitalRead(RAIN_SENSOR_PIN) == LOW);

  // ── 5. System info ────────────────────────────────────────────────────
  int rssi = WiFi.RSSI();

  // ── Print to Serial Monitor ───────────────────────────────────────────
  Serial.println("───────────── Telemetry ─────────────");
  Serial.printf("  Soil Moisture : %.1f %%\n", soilMoisture);
  Serial.printf("  Air Temp      : %.1f °C\n", temperature);
  Serial.printf("  Humidity      : %.1f %%\n", humidity);
  Serial.printf("  Soil Temp     : %.1f °C\n", soilTemp);
  Serial.printf("  Rain          : %s\n", rainDetected ? "YES" : "NO");
  Serial.printf("  RSSI          : %d dBm\n", rssi);
  Serial.println("─────────────────────────────────────");

  // ── 6. Build JSON payload ─────────────────────────────────────────────
  StaticJsonDocument<512> doc;
  doc["device_id"]        = DEVICE_ID;
  doc["device_password"]  = DEVICE_PASSWORD;
  doc["soil_moisture"]    = soilMoisture;
  doc["temperature"]      = temperature;
  doc["humidity"]         = humidity;
  doc["soil_temp"]        = soilTemp;
  doc["solar_radiation"]  = 0.0;          // No LDR/PAR sensor wired yet
  doc["rain_detected"]    = rainDetected;
  doc["battery_pct"]      = 100.0;        // USB-powered — always 100
  doc["rssi"]             = rssi;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  // ── 7. HTTP POST to backend ───────────────────────────────────────────
  HTTPClient http;
  String url = String(BACKEND_URL) + "/api/telemetry";
  http.begin(url);
  http.addHeader("Content-Type", "application/json");

  int httpCode = http.POST(jsonPayload);

  if (httpCode == 200) {
    Serial.println("[HTTP] Telemetry sent OK.");
  } else {
    Serial.printf("[HTTP] Telemetry POST failed — code: %d\n", httpCode);
    String resp = http.getString();
    Serial.println("[HTTP] Response: " + resp);
  }
  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════
// POLL BACKEND FOR RELAY COMMANDS
// ═══════════════════════════════════════════════════════════════════════════
void pollForCommands() {
  HTTPClient http;
  String url = String(BACKEND_URL) + "/api/device/command/" + DEVICE_ID;
  http.begin(url);

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
  } else {
    Serial.printf("[CMD] Poll failed — code: %d\n", httpCode);
  }
  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════
// EXECUTE A RELAY COMMAND
// ═══════════════════════════════════════════════════════════════════════════
void executeCommand(String command) {
  // Active-LOW relay: LOW = ON, HIGH = OFF
  if (command == "PUMP_ON") {
    digitalWrite(RELAY_PUMP_PIN, LOW);
    Serial.println("[Relay] Water Pump → ON");
  }
  else if (command == "PUMP_OFF") {
    digitalWrite(RELAY_PUMP_PIN, HIGH);
    Serial.println("[Relay] Water Pump → OFF");
  }
  else if (command == "VALVE1_ON") {
    digitalWrite(RELAY_VALVE1_PIN, LOW);
    Serial.println("[Relay] Zone 1 Valve → ON");
  }
  else if (command == "VALVE1_OFF") {
    digitalWrite(RELAY_VALVE1_PIN, HIGH);
    Serial.println("[Relay] Zone 1 Valve → OFF");
  }
  else if (command == "FOGGER_ON") {
    digitalWrite(RELAY_FOGGER_PIN, LOW);
    Serial.println("[Relay] Foggers → ON");
  }
  else if (command == "FOGGER_OFF") {
    digitalWrite(RELAY_FOGGER_PIN, HIGH);
    Serial.println("[Relay] Foggers → OFF");
  }
  else if (command == "LIGHTS_ON") {
    digitalWrite(RELAY_LIGHTS_PIN, LOW);
    Serial.println("[Relay] Field Lights → ON");
  }
  else if (command == "LIGHTS_OFF") {
    digitalWrite(RELAY_LIGHTS_PIN, HIGH);
    Serial.println("[Relay] Field Lights → OFF");
  }
  else {
    Serial.println("[CMD] Unknown command: " + command);
  }
}