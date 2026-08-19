// ═══════════════════════════════════════════════════════════════════════════════
//  AgriSense AI — ESP32 Firmware v2.1.0
//  Hardware: ESP32 DevKit V1
//  Language: C++ (Arduino Framework)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  ARCHITECTURE (how the 3 layers talk):
//
//    ┌─────────────────┐   HTTP (C++)    ┌──────────────────┐   WebSocket   ┌──────────────┐
//    │  ESP32 (C++)    │ ──────────────► │  Python Backend  │ ◄──────────── │   Website    │
//    │  This file      │ ◄────────────── │  (FastAPI/PC)    │ ──────────── ►│   (Browser)  │
//    └─────────────────┘   JSON cmds     └──────────────────┘               └──────────────┘
//
//  ESP32 runs ONLY C++ — HTTPClient library makes the HTTP calls.
//  JavaScript runs ONLY in the browser. Python runs ONLY on your PC.
//
//  SENSORS WIRED:
//    DHT11   (Temp + Humidity)  → GPIO 4
//    Soil Moisture Sensor AOUT  → GPIO 34  (12-bit ADC, no pull-up needed)
//    Rain Sensor DO             → GPIO 33  (LOW = Rain Detected)
//    Relay Module IN            → GPIO 16  (Active-LOW: LOW = Relay/Pump ON)
//
//  FLOW:
//    1. Connects to Wi-Fi
//    2. Every 10 s → reads all sensors → POST /api/telemetry to Python backend
//    3. Every  5 s → GET /api/device/command/{device_id}
//         → if PUMP_ON  received → turn relay ON  + print to Serial
//         → if PUMP_OFF received → turn relay OFF + print to Serial
//    4. Serial Monitor shows a live dashboard — open at 115200 baud.
//
//  EDIT THE CONFIGURATION SECTION BELOW BEFORE UPLOADING.
//
// ═══════════════════════════════════════════════════════════════════════════════

// ─── LIBRARIES ────────────────────────────────────────────────────────────────
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>   // Install: ArduinoJson by Benoit Blanchon (v6.x)
#include <DHT.h>           // Install: DHT sensor library by Adafruit

// ═══════════════════════════════════════════════════════════════════════════════
//  ╔══════════════════════════════════════════════════════╗
//  ║          CONFIGURATION — EDIT BEFORE UPLOAD         ║
//  ╚══════════════════════════════════════════════════════╝
// ═══════════════════════════════════════════════════════════════════════════════

// ── Wi-Fi ─────────────────────────────────────────────────────────────────────
#define WIFI_SSID          "Your_Home_WiFi"
#define WIFI_PASSWORD      "Your_Password"

// ── Backend Server ────────────────────────────────────────────────────────────
// IP address of the PC running the Python FastAPI server.
// Find your PC's IP with: ipconfig (Windows) or ip addr (Linux)
// Example: "http://192.168.1.10:8000"
#define BACKEND_URL        "http://192.168.1.10:8000"

// ── Device Identity ───────────────────────────────────────────────────────────
// Must match what you entered when binding the device in the web dashboard.
#define DEVICE_ID          "AGS-0001"
#define DEVICE_PASSWORD    "changeme"

// ── Pin Assignments ───────────────────────────────────────────────────────────
#define DHT_PIN            4      // DHT11 DATA  → GPIO 4
#define DHT_TYPE           DHT11  // Sensor type (DHT11, not DHT22)
#define SOIL_MOISTURE_PIN  34     // Soil Moisture AOUT → GPIO 34 (ADC only, no pull-up)
#define RAIN_SENSOR_PIN    33     // Rain Sensor DO     → GPIO 33
#define RELAY_PUMP_PIN     16     // Relay IN           → GPIO 16

// ── Soil Moisture Calibration ─────────────────────────────────────────────────
// Step 1: Leave sensor in dry air → note ADC reading → set SOIL_DRY_VALUE
// Step 2: Submerge probe in water  → note ADC reading → set SOIL_WET_VALUE
#define SOIL_DRY_VALUE     4095   // Raw ADC when fully dry (12-bit max)
#define SOIL_WET_VALUE     1500   // Raw ADC when submerged in water

// ── Soil Temperature Offset ───────────────────────────────────────────────────
// No DS18B20 probe — soil temp is estimated from air temperature.
#define SOIL_TEMP_OFFSET   -2.5f  // Soil temp = air temp + offset (°C)

// ── Timing ────────────────────────────────────────────────────────────────────
#define TELEMETRY_INTERVAL_MS    10000UL   // Send sensor data every 10 s
#define COMMAND_POLL_INTERVAL_MS  5000UL   // Poll backend for commands every 5 s

// ── Firmware Version ──────────────────────────────────────────────────────────
#define FIRMWARE_VERSION   "2.1.0"

// ═══════════════════════════════════════════════════════════════════════════════
//  GLOBALS
// ═══════════════════════════════════════════════════════════════════════════════

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastTelemetryMs   = 0;
unsigned long lastCommandPollMs = 0;

// Cached sensor values (updated every telemetry cycle, read by Serial print)
float g_temperature   = 0;
float g_humidity      = 0;
float g_soilMoisture  = 0;
bool  g_rainDetected  = false;
bool  g_pumpOn        = false;
int   g_rssi          = 0;
int   g_telemetryCount = 0;   // how many telemetry packets sent

// ═══════════════════════════════════════════════════════════════════════════════
//  SERIAL HELPER: Print a styled section header
// ═══════════════════════════════════════════════════════════════════════════════

void printDivider(char c = '-', int len = 55) {
  for (int i = 0; i < len; i++) Serial.print(c);
  Serial.println();
}

void printHeader(const char* title) {
  Serial.println();
  printDivider('=');
  Serial.printf("  %s\n", title);
  printDivider('=');
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SERIAL DASHBOARD — prints current sensor state in a readable block
// ═══════════════════════════════════════════════════════════════════════════════

void printSensorDashboard(const char* trigger) {
  Serial.println();
  printDivider('-');
  Serial.printf("  AgriSense Dashboard  [Packet #%d]  Trigger: %s\n",
                g_telemetryCount, trigger);
  printDivider('-');

  // ── Sensors ────────────────────────────────────────────────────────────────
  Serial.println("  SENSORS:");
  Serial.printf("    Temperature  : %.1f °C\n",          g_temperature);
  Serial.printf("    Humidity     : %.1f %%\n",          g_humidity);
  Serial.printf("    Soil Moisture: %.1f %%  ",          g_soilMoisture);

  // Inline soil state annotation
  if      (g_soilMoisture < 30)  Serial.println("[ DRY  - watering needed ]");
  else if (g_soilMoisture < 70)  Serial.println("[ MODERATE              ]");
  else                            Serial.println("[ WET  - well irrigated  ]");

  Serial.printf("    Rain Sensor  : %s\n",
                g_rainDetected ? "RAIN DETECTED  <<< pump blocked in auto modes" : "Dry / Clear");

  // ── Relay / Pump ───────────────────────────────────────────────────────────
  Serial.println("  ACTUATOR:");
  if (g_pumpOn) {
    Serial.println("    Water Pump   : *** ON  (RUNNING) ***");
  } else {
    Serial.println("    Water Pump   : OFF");
  }

  // ── Network ────────────────────────────────────────────────────────────────
  Serial.println("  NETWORK:");
  Serial.printf("    Wi-Fi Signal : %d dBm (%s)\n", g_rssi,
                g_rssi > -60 ? "Strong" : g_rssi > -75 ? "Medium" : "Weak");
  Serial.printf("    Backend URL  : %s\n", BACKEND_URL);
  Serial.printf("    Device ID    : %s\n", DEVICE_ID);

  printDivider('-');
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SETUP
// ═══════════════════════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(500);  // Let Serial settle

  printHeader("AgriSense AI - ESP32 Firmware " FIRMWARE_VERSION);
  Serial.println("  Language : C++ (Arduino Framework)");
  Serial.println("  Note     : JS runs in browser, Python on PC.");
  Serial.println("             This ESP32 ONLY runs C++ code.");
  printDivider();

  // ── Configure Pins ──────────────────────────────────────────────────────────
  pinMode(RAIN_SENSOR_PIN, INPUT);
  pinMode(RELAY_PUMP_PIN,  OUTPUT);

  // Relay is active-LOW → start with pump OFF (HIGH = relay OFF)
  digitalWrite(RELAY_PUMP_PIN, HIGH);
  Serial.println("  [INIT] Relay → GPIO 16 → Pump OFF (HIGH = relay OFF)");

  // ── Start DHT ───────────────────────────────────────────────────────────────
  dht.begin();
  Serial.println("  [INIT] DHT11  → GPIO 4  → Initialised");
  Serial.println("  [INIT] Soil   → GPIO 34 → ADC ready");
  Serial.println("  [INIT] Rain   → GPIO 33 → Digital input ready");

  // ── Connect Wi-Fi ───────────────────────────────────────────────────────────
  connectWiFi();

  printDivider();
  Serial.println("  Boot complete. Starting sensor loop...");
  Serial.printf("  Telemetry every %lu s,  Command poll every %lu s\n",
                TELEMETRY_INTERVAL_MS / 1000, COMMAND_POLL_INTERVAL_MS / 1000);
  printDivider();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MAIN LOOP
// ═══════════════════════════════════════════════════════════════════════════════

void loop() {
  // Reconnect Wi-Fi if dropped
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("\n  [WiFi] Connection lost — reconnecting...");
    connectWiFi();
  }

  unsigned long now = millis();

  // ── Poll for Commands every COMMAND_POLL_INTERVAL_MS ────────────────────────
  // Poll FIRST so commands are snappy (no waiting for telemetry)
  if (now - lastCommandPollMs >= COMMAND_POLL_INTERVAL_MS) {
    lastCommandPollMs = now;
    pollCommand();
  }

  // ── Send Telemetry every TELEMETRY_INTERVAL_MS ──────────────────────────────
  if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryMs = now;
    sendTelemetry();
  }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  WI-FI CONNECT (blocking until connected)
// ═══════════════════════════════════════════════════════════════════════════════

void connectWiFi() {
  Serial.printf("\n  [WiFi] Connecting to: %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    if (++attempts > 40) {
      Serial.println("\n  [WiFi] Timed out. Retrying in 10 s...");
      delay(10000);
      attempts = 0;
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    }
  }

  g_rssi = WiFi.RSSI();
  Serial.println();
  Serial.printf("  [WiFi] Connected!  IP: %s   RSSI: %d dBm\n",
                WiFi.localIP().toString().c_str(), g_rssi);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  READ SENSORS
// ═══════════════════════════════════════════════════════════════════════════════

float readSoilMoisturePct() {
  // Average 5 ADC samples to reduce noise
  long sum = 0;
  for (int i = 0; i < 5; i++) {
    sum += analogRead(SOIL_MOISTURE_PIN);
    delay(10);
  }
  float raw = (float)(sum / 5);

  // Map: high ADC = dry (0%), low ADC = wet (100%) — sensor is inverted
  float pct = ((float)(SOIL_DRY_VALUE - raw) / (float)(SOIL_DRY_VALUE - SOIL_WET_VALUE)) * 100.0f;
  return constrain(pct, 0.0f, 100.0f);
}

bool readRainDetected() {
  // Rain sensor DO: LOW = rain detected (active-LOW module)
  return (digitalRead(RAIN_SENSOR_PIN) == LOW);
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SEND TELEMETRY  →  POST /api/telemetry
// ═══════════════════════════════════════════════════════════════════════════════

void sendTelemetry() {
  // ── Read all sensors ────────────────────────────────────────────────────────
  float humidity    = dht.readHumidity();
  float temperature = dht.readTemperature();  // Celsius

  if (isnan(humidity) || isnan(temperature)) {
    Serial.println("  [DHT11] Read FAILED — check wiring on GPIO 4. Skipping tick.");
    return;
  }

  float soilMoisture = readSoilMoisturePct();
  float soilTemp     = temperature + SOIL_TEMP_OFFSET;
  bool  rainDetected = readRainDetected();
  g_rssi             = WiFi.RSSI();

  // ── Cache into globals for dashboard ────────────────────────────────────────
  g_temperature  = temperature;
  g_humidity     = humidity;
  g_soilMoisture = soilMoisture;
  g_rainDetected = rainDetected;
  g_telemetryCount++;

  // ── Print dashboard to Serial ────────────────────────────────────────────────
  printSensorDashboard("10s Telemetry Tick");

  // ── Build JSON payload ───────────────────────────────────────────────────────
  StaticJsonDocument<300> doc;
  doc["device_id"]       = DEVICE_ID;
  doc["device_password"] = DEVICE_PASSWORD;
  doc["soil_moisture"]   = soilMoisture;
  doc["temperature"]     = temperature;
  doc["humidity"]        = humidity;
  doc["soil_temp"]       = soilTemp;
  doc["solar_radiation"] = 0.0;     // No solar sensor wired
  doc["rain_detected"]   = rainDetected;
  doc["battery_pct"]     = 100.0;   // No battery sensor wired
  doc["rssi"]            = g_rssi;

  String body;
  serializeJson(doc, body);

  // ── HTTP POST to Python backend ──────────────────────────────────────────────
  Serial.printf("  [HTTP] POST %s/api/telemetry ... ", BACKEND_URL);

  HTTPClient http;
  http.begin(String(BACKEND_URL) + "/api/telemetry");
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);

  if (code == 200) {
    Serial.println("OK (200) → Backend received, website updated via WebSocket");
  } else if (code < 0) {
    Serial.printf("FAILED (connection error %d) — is backend running?\n", code);
  } else {
    Serial.printf("FAILED (HTTP %d)\n", code);
  }

  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  POLL FOR COMMANDS  →  GET /api/device/command/{device_id}
// ═══════════════════════════════════════════════════════════════════════════════

void pollCommand() {
  HTTPClient http;
  String url = String(BACKEND_URL) + "/api/device/command/" + String(DEVICE_ID);
  http.begin(url);

  int code = http.GET();

  if (code == 200) {
    String response = http.getString();

    StaticJsonDocument<128> doc;
    DeserializationError err = deserializeJson(doc, response);

    if (!err) {
      const char* command = doc["command"];

      if (command != nullptr && strlen(command) > 0) {
        // ── A command arrived — print it prominently ──────────────────────────
        Serial.println();
        printDivider('*');
        Serial.printf("  COMMAND RECEIVED FROM WEBSITE: %s\n", command);

        String cmd = String(command);

        if (cmd == "PUMP_ON") {
          setPump(true);
          Serial.println("  >>> ACTION: Relay energised — Water Pump is now ON");
          Serial.println("  >>> This was triggered from the website dashboard.");
          Serial.println("  >>> Cross-check: pump switch on website should show RUNNING.");
        } else if (cmd == "PUMP_OFF") {
          setPump(false);
          Serial.println("  >>> ACTION: Relay released — Water Pump is now OFF");
          Serial.println("  >>> This was triggered from the website dashboard.");
          Serial.println("  >>> Cross-check: pump switch on website should show OFF.");
        } else {
          Serial.printf("  >>> Unknown command: '%s' — ignored\n", command);
        }

        // Print current sensor state after acting on command
        printSensorDashboard("Post-Command State");
        printDivider('*');

      } else {
        // No command — print a minimal heartbeat dot so you know it's polling
        Serial.print(".");
      }
    } else {
      Serial.printf("\n  [Command] JSON parse error: %s\n", err.c_str());
    }

  } else if (code < 0) {
    Serial.printf("\n  [Command] Poll FAILED (connection error %d)\n", code);
  } else {
    Serial.printf("\n  [Command] Poll FAILED (HTTP %d)\n", code);
  }

  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  RELAY (PUMP) CONTROL
// ═══════════════════════════════════════════════════════════════════════════════

void setPump(bool on) {
  if (g_pumpOn == on) {
    Serial.printf("  [Relay] Pump already %s — no change.\n", on ? "ON" : "OFF");
    return;
  }

  g_pumpOn = on;

  // Active-LOW relay: LOW = ON (pump running), HIGH = OFF (pump idle)
  digitalWrite(RELAY_PUMP_PIN, on ? LOW : HIGH);

  Serial.println();
  Serial.printf("  [Relay] GPIO 16 → %s → Pump %s\n",
                on ? "LOW  (relay energised)" : "HIGH (relay released)",
                on ? "** ON **" : "OFF");
}