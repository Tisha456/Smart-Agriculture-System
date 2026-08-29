// ═══════════════════════════════════════════════════════════════════════════════
//  AgriSense AI — ESP32-CAM Firmware v1.0.0
//  Hardware: AI-Thinker ESP32-CAM (on a USB programming dock / "ESP32-CAM-MB")
//  Language: C++ (Arduino Framework)
// ═══════════════════════════════════════════════════════════════════════════════
//
//  ARCHITECTURE:
//
//    ┌──────────────┐   HTTPS POST JPEG   ┌───────────────────┐   MJPEG   ┌──────────┐
//    │ ESP32-CAM    │ ──────────────────► │  FastAPI backend  │ ────────► │ Browser/ │
//    │ This file    │ ◄────────────────── │  (backend/main.py)│           │   App    │
//    └──────────────┘   {"wanted": bool}  └───────────────────┘           └──────────┘
//
//  This is a SEPARATE board from AgriSense_ESP32.ino (the soil/rain/pump node).
//  It cannot be combined onto one board: the AI-Thinker camera interface uses
//  GPIO 34 (your soil ADC pin), GPIO 4 (the on-board flash LED, DHT11 lives
//  there on the sensor node) and GPIO 16 (PSRAM CS). See WIRING_GUIDE.md.
//
//  This board reuses the SENSOR NODE's DEVICE_ID below — it isn't a separate
//  paired device, it's "the camera on that field node". No new Supabase
//  pairing is needed; the backend authenticates it with CAM_UPLOAD_KEY
//  instead (see backend/.env's CAM_UPLOAD_KEY, which must match the one set
//  below), the same way PLANT_API_KEY authenticates the plant-disease API.
//
//  FLOW:
//    1. Connect to Wi-Fi.
//    2. Init the OV2640 camera (esp_camera.h).
//    3. Loop:
//       - If nobody is watching: poll GET /api/camera/{id}/wanted every
//         IDLE_POLL_MS and do nothing else (saves power/bandwidth).
//       - If someone is watching: capture a JPEG and POST it to
//         /api/camera/{id}/frame, rate-limited by STREAM_FPS_CAP. Each POST
//         response says whether to keep streaming or drop back to idle.
//    4. Serial Monitor shows connection + streaming status at 115200 baud.
//
//  EDIT THE CONFIGURATION SECTION BELOW BEFORE UPLOADING.
//
// ═══════════════════════════════════════════════════════════════════════════════

// ─── LIBRARIES ────────────────────────────────────────────────────────────────
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>   // Install: ArduinoJson by Benoit Blanchon (v6.x)
#include "esp_camera.h"

// ═══════════════════════════════════════════════════════════════════════════════
//  ╔══════════════════════════════════════════════════════╗
//  ║          CONFIGURATION — EDIT BEFORE UPLOAD         ║
//  ╚══════════════════════════════════════════════════════╝
// ═══════════════════════════════════════════════════════════════════════════════

// ── Wi-Fi — same network as AgriSense_ESP32.ino, or any network with internet ──
#define WIFI_SSID          "YOLO"
#define WIFI_PASSWORD      "12345678"

// ── Backend (relay through the internet, not the local network) ─────────────
// This is the SAME FastAPI backend used by the app/website
// (see mobile_app/.env's EXPO_PUBLIC_BACKEND_URL). Update if it moves.
#define BACKEND_HOST       "agrisense-ai-cqzv.onrender.com"
#define BACKEND_USE_TLS    true

// ── Device Identity — reuses the sensor node's DEVICE_ID on purpose ─────────
#define DEVICE_ID          "AGS-0001"

// Must match CAM_UPLOAD_KEY in backend/.env exactly. Generate one with:
//   python -c "import secrets; print(secrets.token_urlsafe(24))"
#define CAM_UPLOAD_KEY     "td--M_yeveIQ5aZ-PjNUT1SkrtrXNmdL"

// ── Calibration knobs — real hardware never matches the datasheet ───────────
// ponytail: fixed values below, no auto-tuning. Adjust by hand if the board
// browns out (weak 5V supply) or a PSRAM-less clone rejects VGA/fb_count 2.
#define IDLE_POLL_MS       3000    // how often to check "is anyone watching?" while idle
#define STREAM_FPS_CAP     4       // max frames/sec while streaming (TLS handshake + upload cost)
#define JPEG_QUALITY_PSRAM 12      // lower = better quality, bigger file (0-63)
#define JPEG_QUALITY_NO_PSRAM 15

// ═══════════════════════════════════════════════════════════════════════════════
//  AI-THINKER ESP32-CAM PIN MAP — swap this whole block for a different board
// ═══════════════════════════════════════════════════════════════════════════════
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

// ── Globals ───────────────────────────────────────────────────────────────────
WiFiClientSecure g_client;
HTTPClient g_http;
bool g_streaming = false;
unsigned long g_lastFrameMs = 0;
unsigned long g_lastIdlePollMs = 0;

// ─────────────────────────────────────────────────────────────────────────────
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
  Serial.printf("  [WiFi] Connected!  IP: %s\n", WiFi.localIP().toString().c_str());
}

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_LATEST;

  if (psramFound()) {
    config.frame_size = FRAMESIZE_VGA;
    config.jpeg_quality = JPEG_QUALITY_PSRAM;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    config.frame_size = FRAMESIZE_QVGA;
    config.jpeg_quality = JPEG_QUALITY_NO_PSRAM;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("  [Camera] Init failed: 0x%x\n", err);
    return false;
  }
  Serial.println("  [Camera] Ready.");
  return true;
}

// Reads the {"wanted": bool} field out of a small JSON response body.
// Anything malformed/unexpected is treated as "not wanted" — fail closed,
// so a bad response doesn't spin the camera into pointless streaming.
bool parseWanted(const String &body) {
  StaticJsonDocument<128> doc;
  if (deserializeJson(doc, body) != DeserializationError::Ok) return false;
  return doc["wanted"] | false;
}

bool pollWanted() {
  String url = String(BACKEND_USE_TLS ? "https://" : "http://") + BACKEND_HOST
             + "/api/camera/" + DEVICE_ID + "/wanted";
  g_http.begin(g_client, url);
  g_http.addHeader("X-Cam-Key", CAM_UPLOAD_KEY);
  int code = g_http.GET();
  bool wanted = false;
  if (code == 200) wanted = parseWanted(g_http.getString());
  else Serial.printf("  [Camera] /wanted -> HTTP %d\n", code);
  g_http.end();
  return wanted;
}

bool pushFrame() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("  [Camera] Frame capture failed.");
    return false;
  }

  String url = String(BACKEND_USE_TLS ? "https://" : "http://") + BACKEND_HOST
             + "/api/camera/" + DEVICE_ID + "/frame";
  g_http.begin(g_client, url);
  g_http.addHeader("Content-Type", "image/jpeg");
  g_http.addHeader("X-Cam-Key", CAM_UPLOAD_KEY);
  int code = g_http.POST(fb->buf, fb->len);

  bool wanted = false;
  if (code == 200) wanted = parseWanted(g_http.getString());
  else Serial.printf("  [Camera] /frame -> HTTP %d\n", code);

  g_http.end();
  esp_camera_fb_return(fb);
  return wanted;
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n\n=== AgriSense ESP32-CAM v1.0.0 ===");

  if (!initCamera()) {
    Serial.println("  [Camera] Halting — check wiring/board selection.");
    while (true) delay(1000);
  }

  connectWiFi();
  g_client.setInsecure();       // Skip TLS cert verification (fine for IoT/dev)
  g_http.setReuse(true);        // Critical for framerate — a fresh TLS handshake
                                 // per frame costs 1-2s and caps you near 0.5 fps.
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  unsigned long now = millis();
  const unsigned long minFrameIntervalMs = 1000UL / STREAM_FPS_CAP;

  if (g_streaming) {
    if (now - g_lastFrameMs >= minFrameIntervalMs) {
      g_lastFrameMs = now;
      g_streaming = pushFrame();
      if (!g_streaming) Serial.println("  [Camera] No viewers — going idle.");
    }
  } else {
    if (now - g_lastIdlePollMs >= IDLE_POLL_MS) {
      g_lastIdlePollMs = now;
      if (pollWanted()) {
        Serial.println("  [Camera] Viewer connected — streaming.");
        g_streaming = true;
        g_lastFrameMs = 0;
      }
    }
  }
}
