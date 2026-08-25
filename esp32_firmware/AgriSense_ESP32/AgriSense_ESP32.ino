// ═══════════════════════════════════════════════════════════════════════════════
//  AgriSense AI — ESP32 Firmware v3.0.0
//  Hardware: ESP32 DevKit V1
//  Language: C++ (Arduino Framework)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  ARCHITECTURE (Hybrid — Direct to Supabase):
//
//    ┌─────────────────┐   HTTPS REST    ┌─────────────────────┐
//    │  ESP32 (C++)    │ ─────────────►  │  Supabase REST API  │
//    │  This file      │ ◄────────────── │  (hosted database)  │
//    └─────────────────┘   JSON rows     └─────────────────────┘
//                                                  │
//                                    Supabase Realtime
//                                                  ▼
//                                        ┌──────────────────┐
//                                        │   Website/App    │
//                                        │  (Browser JS)    │
//                                        └──────────────────┘
//
//  WHAT CHANGED FROM v2.x:
//    - ESP32 now talks directly to Supabase REST API (HTTPS) — no FastAPI needed.
//    - Telemetry:  POST https://<SUPABASE_URL>/rest/v1/telemetry_data
//    - Commands:   GET  https://<SUPABASE_URL>/rest/v1/device_commands?...
//    - FastAPI backend is no longer required for the data pipeline.
//      (It can still be used later for the pump automation decision engine.)
//
//  SENSORS WIRED:
//    DHT11   (Temp + Humidity)  → GPIO 4
//    Soil Moisture Sensor AOUT  → GPIO 34  (12-bit ADC, no pull-up needed)
//    Rain Sensor DO             → GPIO 33  (LOW = Rain Detected)
//    Relay Module IN            → GPIO 16  (Active-LOW: LOW = Relay/Pump ON)
//
//  FLOW:
//    1. Connects to Wi-Fi (HTTPS/TLS capable)
//    2. Every 10 s → reads all sensors → POST to Supabase telemetry_data table
//    3. Every  5 s → GET from Supabase device_commands table
//         → if PUMP_ON  received → turn relay ON  + mark command executed
//         → if PUMP_OFF received → turn relay OFF + mark command executed
//    4. Serial Monitor shows a live dashboard — open at 115200 baud.
//
//  EDIT THE CONFIGURATION SECTION BELOW BEFORE UPLOADING.
//
// ═══════════════════════════════════════════════════════════════════════════════

// ─── LIBRARIES ────────────────────────────────────────────────────────────────
#include <WiFi.h>
#include <WiFiClientSecure.h>   // For HTTPS to Supabase (TLS)
#include <HTTPClient.h>
#include <ArduinoJson.h>        // Install: ArduinoJson by Benoit Blanchon (v6.x)
#include <DHT.h>                // Install: DHT sensor library by Adafruit

// ═══════════════════════════════════════════════════════════════════════════════
//  ╔══════════════════════════════════════════════════════╗
//  ║          CONFIGURATION — EDIT BEFORE UPLOAD         ║
//  ╚══════════════════════════════════════════════════════╝
// ═══════════════════════════════════════════════════════════════════════════════

// ── Wi-Fi ─────────────────────────────────────────────────────────────────────
#define WIFI_SSID          "YOLO"
#define WIFI_PASSWORD      "12345678"

// ── Supabase Configuration ────────────────────────────────────────────────────
// These come from your Supabase project settings → API
// Project URL:  https://supabase.com/dashboard/project/iqmrpwvbmfkhychhditg/settings/api
#define SUPABASE_URL       "iqmrpwvbmfkhychhditg.supabase.co"
#define SUPABASE_ANON_KEY  "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlxbXJwd3ZibWZraHljaGhkaXRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYyNTY5OTEsImV4cCI6MjEwMTgzMjk5MX0.i8wCUSDmc6DI8ZLK6wQeaZDzQqZCEIzkZUrrg2RnefQ"

// ── Device Identity ───────────────────────────────────────────────────────────
// IMPORTANT: This DEVICE_ID must match the device_id you register
// in the website's "Initialize Node Pairing" form.
// The DEVICE_ID is what links this ESP32's data to your account.
#define DEVICE_ID          "AGS-0001"

// Must match the pairing_secret seeded for this device_id in the
// device_registry table (documents/supabase_presence_and_pairing.sql).
// This proves to the website that this board is genuine hardware, not a
// typed-in guess.
#define PAIRING_SECRET     "7F3K21X9"

// ── Pin Assignments ───────────────────────────────────────────────────────────
#define DHT_PIN            4      // DHT11 DATA  → GPIO 4
#define DHT_TYPE           DHT11  // Sensor type (DHT11, not DHT22)
#define SOIL_MOISTURE_PIN  34     // Soil Moisture AOUT → GPIO 34 (ADC only, no pull-up)
#define RAIN_SENSOR_PIN    33     // Rain Sensor DO     → GPIO 33
#define RELAY_PUMP_PIN     16     // Relay IN           → GPIO 16

// ── Soil Moisture Calibration ─────────────────────────────────────────────────
// Measured on this board: dry air ≈ 4095, probe fully submerged ≈ 30.
// Re-measure if you swap the probe — these are per-sensor, not universal.
// Step 1: Leave sensor in dry air → note ADC reading → set SOIL_DRY_VALUE
// Step 2: Submerge probe in water  → note ADC reading → set SOIL_WET_VALUE
#define SOIL_DRY_VALUE     4095   // Raw ADC when fully dry (12-bit max)
#define SOIL_WET_VALUE     30     // Raw ADC when submerged in water (measured)

// ── Soil Sensor Disconnect Detection ──────────────────────────────────────────
// If the probe is unplugged, GPIO34 floats and reads near 0 (input-only pin,
// no internal pull-up). Calibrate on your own board:
//   1. Flash this firmware, open Serial Monitor.
//   2. Unplug the soil probe. Note the raw ADC value printed each tick.
//   3. Plug it back in, place it in dry soil. Note the raw ADC value again.
//   4. Set SOIL_DISCONNECT_ADC between the two, closer to the unplugged one.
//
// ponytail: this threshold sits in a narrow gap — a submerged probe reads ~30
// here and a floating pin reads ~0, so "fully wet" and "unplugged" are only
// ~30 counts apart. 10 separates them on this board, but it is not a wide
// margin. If disconnect detection ever misfires, read DO (the module's
// digital output) as a second signal instead of widening this.
#define SOIL_DISCONNECT_ADC  10

// ── Soil Temperature Offset ───────────────────────────────────────────────────
// No DS18B20 probe — soil temp is estimated from air temperature.
#define SOIL_TEMP_OFFSET   -2.5f  // Soil temp = air temp + offset (°C)

// ── Timing ────────────────────────────────────────────────────────────────────
#define TELEMETRY_INTERVAL_MS    10000UL   // Send sensor data every 10 s
#define HEARTBEAT_INTERVAL_MS    10000UL   // Upsert device_status every 10 s
#define COMMAND_POLL_INTERVAL_MS  5000UL   // Poll Supabase for commands every 5 s
#define PAIR_CHECK_INTERVAL_MS   30000UL   // Ask "am I paired?" every 30 s

// ── Firmware Version ──────────────────────────────────────────────────────────
#define FIRMWARE_VERSION   "3.0.0"

// ═══════════════════════════════════════════════════════════════════════════════
//  GLOBALS
// ═══════════════════════════════════════════════════════════════════════════════

DHT dht(DHT_PIN, DHT_TYPE);

unsigned long lastTelemetryMs   = 0;
unsigned long lastHeartbeatMs   = 0;
unsigned long lastCommandPollMs = 0;
unsigned long lastPairCheckMs   = 0;

// Cached sensor values (updated every telemetry cycle, read by Serial print)
float g_temperature   = 0;
float g_humidity      = 0;
float g_soilMoisture  = 0;
bool  g_rainDetected  = false;
bool  g_pumpOn        = false;
int   g_rssi          = 0;
int   g_telemetryCount = 0;   // how many telemetry packets sent
int   g_bootCount      = 1;   // increments once per boot; sent in heartbeat

// Sensor health flags — updated every telemetry tick, always sent in heartbeat
// (even when the sensor read failed, so the website can show "online, no data")
bool  g_dhtOk       = false;
bool  g_soilOk      = false;
bool  g_sensorsOk   = false;
long  g_lastSoilRaw = 0;      // raw ADC, useful for calibrating SOIL_DISCONNECT_ADC

// Pairing state — only re-printed to Serial when it changes
bool  g_isPaired        = false;
bool  g_pairStatusKnown = false;   // false until the first successful check
String g_pairedDeviceName = "";

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
  Serial.printf("    Temperature  : %.1f °C  [%s]\n", g_temperature, g_dhtOk ? "OK" : "NOT DETECTED");
  Serial.printf("    Humidity     : %.1f %%  [%s]\n", g_humidity,    g_dhtOk ? "OK" : "NOT DETECTED");
  Serial.printf("    Soil Moisture: %.1f %%  (raw ADC %ld)  [%s]  ",
                g_soilMoisture, g_lastSoilRaw, g_soilOk ? "OK" : "NOT DETECTED");

  // Inline soil state annotation
  if (!g_soilOk)                  Serial.println("[ DISCONNECTED ]");
  else if (g_soilMoisture < 30)   Serial.println("[ DRY  - watering needed ]");
  else if (g_soilMoisture < 70)   Serial.println("[ MODERATE              ]");
  else                             Serial.println("[ WET  - well irrigated  ]");

  Serial.printf("    Rain Sensor  : %s  [wiring cannot be verified — floating pin reads as 'no rain']\n",
                g_rainDetected ? "RAIN DETECTED  <<< pump blocked in auto modes" : "Dry / Clear");

  Serial.printf("    Sensors OK   : %s\n", g_sensorsOk ? "YES — live data" : "NO — sending 0s, check wiring");

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
  Serial.printf("    Supabase     : %s\n", SUPABASE_URL);
  Serial.printf("    Device ID    : %s\n", DEVICE_ID);

  // ── Pairing ────────────────────────────────────────────────────────────────
  Serial.println("  PAIRING:");
  if (!g_pairStatusKnown) {
    Serial.println("    Status       : Checking...");
  } else if (g_isPaired) {
    Serial.printf("    Status       : BOUND to website  (Node: %s)\n", g_pairedDeviceName.c_str());
  } else {
    Serial.println("    Status       : NOT BOUND — pair this device on the website Connect page");
  }

  printDivider('-');
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SETUP
// ═══════════════════════════════════════════════════════════════════════════════

void setup() {
  Serial.begin(115200);
  delay(500);  // Let Serial settle

  printHeader("AgriSense AI - ESP32 Firmware " FIRMWARE_VERSION);
  Serial.println("  Architecture: ESP32 → Supabase REST API (Direct, no FastAPI)");
  Serial.println("  Language    : C++ (Arduino Framework)");
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

  // ── Check pairing status once at boot ────────────────────────────────────────
  checkPairStatus();

  printDivider();
  Serial.println("  Boot complete. Starting sensor loop...");
  Serial.printf("  Telemetry every %lu s,  Heartbeat every %lu s,  Command poll every %lu s\n",
                TELEMETRY_INTERVAL_MS / 1000, HEARTBEAT_INTERVAL_MS / 1000, COMMAND_POLL_INTERVAL_MS / 1000);
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

  // ── Send Heartbeat every HEARTBEAT_INTERVAL_MS ──────────────────────────────
  // Sent BEFORE telemetry so the "online" signal lands even if the telemetry
  // POST fails for some reason.
  if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeatMs = now;
    sendHeartbeat();
  }

  // ── Send Telemetry every TELEMETRY_INTERVAL_MS ──────────────────────────────
  if (now - lastTelemetryMs >= TELEMETRY_INTERVAL_MS) {
    lastTelemetryMs = now;
    sendTelemetry();
  }

  // ── Re-check pairing status every PAIR_CHECK_INTERVAL_MS ────────────────────
  if (now - lastPairCheckMs >= PAIR_CHECK_INTERVAL_MS) {
    lastPairCheckMs = now;
    checkPairStatus();
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
  long raw = sum / 5;
  g_lastSoilRaw = raw;   // cached for health check + Serial dashboard

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
  // Every sensor is health-checked independently. A failed/disconnected
  // sensor reports 0 rather than skipping the tick entirely — this is what
  // lets the website tell "ESP32 online, sensors unplugged" (zeros, but
  // still receiving packets) apart from "ESP32 powered off" (no packets,
  // heartbeat goes stale).
  float humidity    = dht.readHumidity();
  float temperature = dht.readTemperature();  // Celsius
  g_dhtOk = !isnan(humidity) && !isnan(temperature);
  if (!g_dhtOk) {
    Serial.println("  [DHT11] Read FAILED — check wiring on GPIO 4. Sending 0s this tick.");
    humidity = 0;
    temperature = 0;
  }

  float soilMoisture = readSoilMoisturePct();   // also updates g_lastSoilRaw
  g_soilOk = (g_lastSoilRaw >= SOIL_DISCONNECT_ADC);
  if (!g_soilOk) {
    Serial.printf("  [Soil] Raw ADC %ld below disconnect threshold — probe not detected. Sending 0.\n", g_lastSoilRaw);
    soilMoisture = 0;
  }

  g_sensorsOk = g_dhtOk && g_soilOk;

  float soilTemp     = g_dhtOk ? (temperature + SOIL_TEMP_OFFSET) : 0;
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

  // ── Build JSON payload (matches telemetry_data table columns) ───────────────
  StaticJsonDocument<300> doc;
  doc["device_id"]       = DEVICE_ID;
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

  // ── HTTPS POST to Supabase REST API ─────────────────────────────────────────
  // Inserts a row directly into telemetry_data table.
  // The website receives it instantly via Supabase Realtime subscription.
  Serial.print("  [Supabase] POST /rest/v1/telemetry_data ... ");

  WiFiClientSecure client;
  client.setInsecure();  // Skip TLS cert verification (fine for IoT/dev)

  HTTPClient http;
  String url = String("https://") + SUPABASE_URL + "/rest/v1/telemetry_data";
  http.begin(client, url);

  // Supabase REST API requires these three headers
  http.addHeader("Content-Type", "application/json");
  http.addHeader("apikey", SUPABASE_ANON_KEY);
  http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON_KEY);
  http.addHeader("Prefer", "return=minimal");  // Don't return the inserted row

  int code = http.POST(body);

  if (code == 201) {
    // 201 Created = row inserted successfully into Supabase
    Serial.println("OK (201) → Row inserted. Website updates via Supabase Realtime.");
  } else if (code == 200) {
    Serial.println("OK (200)");
  } else if (code < 0) {
    Serial.printf("FAILED (connection error %d) — check Wi-Fi or Supabase URL\n", code);
  } else {
    String resp = http.getString();
    Serial.printf("FAILED (HTTP %d): %s\n", code, resp.c_str());
  }

  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  SEND HEARTBEAT  →  UPSERT device_status
//  This is what makes "connected" real. It is sent on every tick regardless
//  of whether the sensors are working — a stale/missing heartbeat is the
//  ONLY thing that means "this ESP32 is powered off or unreachable".
// ═══════════════════════════════════════════════════════════════════════════════

void sendHeartbeat() {
  StaticJsonDocument<300> doc;
  doc["device_id"]        = DEVICE_ID;
  // last_seen_at is deliberately NOT sent: the board has no NTP clock, and the
  // string "now()" is not valid timestamptz input (Postgres accepts 'now', not
  // 'now()'), which made this whole upsert fail with HTTP 400. The
  // touch_device_status_last_seen trigger stamps it server-side instead.
  doc["sensors_ok"]       = g_sensorsOk;
  doc["firmware_version"] = FIRMWARE_VERSION;
  doc["ip_address"]       = WiFi.localIP().toString();
  doc["rssi"]             = g_rssi;
  doc["boot_count"]       = g_bootCount;

  JsonObject flags = doc.createNestedObject("sensor_flags");
  flags["dht"]  = g_dhtOk;
  flags["soil"] = g_soilOk;
  flags["rain"] = true;  // cannot be health-checked — see WIRING_GUIDE.md

  String body;
  serializeJson(doc, body);

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  String url = String("https://") + SUPABASE_URL + "/rest/v1/device_status";
  http.begin(client, url);

  http.addHeader("Content-Type", "application/json");
  http.addHeader("apikey", SUPABASE_ANON_KEY);
  http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON_KEY);
  // resolution=merge-duplicates makes this an UPSERT on device_id (primary key)
  http.addHeader("Prefer", "resolution=merge-duplicates,return=minimal");

  int code = http.POST(body);

  if (code == 201 || code == 200 || code == 204) {
    Serial.printf("  [Heartbeat] OK (%d) → device_status updated. Sensors: %s\n",
                  code, g_sensorsOk ? "OK" : "NOT DETECTED");
  } else if (code < 0) {
    Serial.printf("  [Heartbeat] FAILED (connection error %d)\n", code);
  } else {
    String resp = http.getString();
    Serial.printf("  [Heartbeat] FAILED (HTTP %d): %s\n", code, resp.c_str());
  }

  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  CHECK PAIRING STATUS  →  POST /rest/v1/rpc/device_pair_status
//  Asks Supabase "has this device_id been claimed by a website account yet?"
//  Only prints a banner when the state CHANGES, so the log isn't spammed.
// ═══════════════════════════════════════════════════════════════════════════════

void checkPairStatus() {
  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  String url = String("https://") + SUPABASE_URL + "/rest/v1/rpc/device_pair_status";
  http.begin(client, url);

  http.addHeader("Content-Type", "application/json");
  http.addHeader("apikey", SUPABASE_ANON_KEY);
  http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON_KEY);

  StaticJsonDocument<128> reqDoc;
  reqDoc["p_device_id"] = DEVICE_ID;
  reqDoc["p_secret"]    = PAIRING_SECRET;
  String reqBody;
  serializeJson(reqDoc, reqBody);

  int code = http.POST(reqBody);

  if (code == 200) {
    String response = http.getString();
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, response);

    if (!err) {
      bool registered = doc["registered"] | false;
      bool paired     = doc["paired"] | false;
      String name     = doc["device_name"].isNull() ? "" : String((const char*)doc["device_name"]);

      if (!registered) {
        Serial.println("\n  [Pairing] WARNING: This device_id/secret is not in device_registry.");
        Serial.println("  [Pairing] Check DEVICE_ID and PAIRING_SECRET match what was seeded in Supabase.");
      }

      bool changed = (!g_pairStatusKnown) || (paired != g_isPaired) || (name != g_pairedDeviceName);
      g_isPaired          = paired;
      g_pairedDeviceName  = name;
      g_pairStatusKnown   = true;

      if (changed) {
        Serial.println();
        printDivider('*');
        if (g_isPaired) {
          Serial.println("  PAIRED — THIS ESP32 IS BOUND TO THE WEBSITE");
          Serial.printf("  Device ID : %s\n", DEVICE_ID);
          Serial.printf("  Node Name : %s\n", g_pairedDeviceName.c_str());
          Serial.println("  Status    : Telemetry is reaching the dashboard live");
        } else {
          Serial.println("  NOT PAIRED — this board is not linked to any account");
          Serial.printf("  Device ID : %s\n", DEVICE_ID);
          Serial.println("  Fix: open the website -> Connect page -> enter serial");
          Serial.printf("       %s and its pairing secret, with this board\n", DEVICE_ID);
          Serial.println("       powered on. This banner flips within 30 seconds.");
        }
        printDivider('*');
      }
    } else {
      Serial.printf("  [Pairing] JSON parse error: %s\n", err.c_str());
    }
  } else if (code < 0) {
    Serial.printf("  [Pairing] Check FAILED (connection error %d)\n", code);
  } else {
    Serial.printf("  [Pairing] Check FAILED (HTTP %d)\n", code);
  }

  http.end();
}

// ═══════════════════════════════════════════════════════════════════════════════
//  POLL FOR COMMANDS  →  GET /api/device/command/{device_id}
// ═══════════════════════════════════════════════════════════════════════════════

void pollCommand() {
  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;

  // Supabase REST filter: device_id=eq.AGS-0001 AND executed=eq.false
  // order=created_at.asc (oldest first), limit=1 (one at a time)
  String url = String("https://") + SUPABASE_URL
             + "/rest/v1/device_commands"
             + "?device_id=eq." + DEVICE_ID
             + "&executed=eq.false"
             + "&order=created_at.asc"
             + "&limit=1";

  http.begin(client, url);
  http.addHeader("apikey", SUPABASE_ANON_KEY);
  http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON_KEY);
  http.addHeader("Accept", "application/json");

  int code = http.GET();

  if (code == 200) {
    String response = http.getString();

    // Supabase returns an array: [{"id":1, "command":"PUMP_ON", ...}]
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, response);

    if (!err && doc.is<JsonArray>() && doc.as<JsonArray>().size() > 0) {
      JsonObject cmd    = doc[0];
      const char* command = cmd["command"];
      long        cmdId   = cmd["id"].as<long>();

      if (command != nullptr && strlen(command) > 0) {
        // ── A command arrived — print it prominently ──────────────────────────
        Serial.println();
        printDivider('*');
        Serial.printf("  COMMAND RECEIVED FROM WEBSITE: %s\n", command);

        String cmdStr = String(command);

        if (cmdStr == "PUMP_ON") {
          setPump(true);
          Serial.println("  >>> ACTION: Relay energised — Water Pump is now ON");
          Serial.println("  >>> This was triggered from the website dashboard.");
        } else if (cmdStr == "PUMP_OFF") {
          setPump(false);
          Serial.println("  >>> ACTION: Relay released — Water Pump is now OFF");
          Serial.println("  >>> This was triggered from the website dashboard.");
        } else {
          Serial.printf("  >>> Unknown command: '%s' — ignored\n", command);
        }

        // Mark command as executed so it doesn't repeat
        http.end();
        markCommandExecuted(cmdId);

        printSensorDashboard("Post-Command State");
        printDivider('*');
        return;  // http.end() already called above

      } else {
        Serial.print(".");  // No pending command
      }
    } else if (!err) {
      Serial.print(".");    // Empty array = no pending commands
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
//  MARK COMMAND AS EXECUTED  →  PATCH Supabase device_commands by id
//  Sets executed=true so ESP32 doesn't pick up the same command again.
// ═══════════════════════════════════════════════════════════════════════════════

void markCommandExecuted(long cmdId) {
  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  String url = String("https://") + SUPABASE_URL
             + "/rest/v1/device_commands"
             + "?id=eq." + String(cmdId);

  http.begin(client, url);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("apikey", SUPABASE_ANON_KEY);
  http.addHeader("Authorization", String("Bearer ") + SUPABASE_ANON_KEY);
  http.addHeader("Prefer", "return=minimal");

  int code = http.PATCH("{\"executed\": true}");

  if (code == 204 || code == 200) {
    Serial.printf("\n  [Command] Marked command #%ld as executed.\n", cmdId);
  } else {
    Serial.printf("\n  [Command] Failed to mark executed (HTTP %d)\n", code);
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