# 🚀 AgriSense AI: Full System Integration & Setup Guide

This document is your **Master Step-by-Step Blueprint**. It explains exactly how to wire your hardware, set up your database and authentication, run the backend, and get real-time data flowing between your ESP32, Website, and Mobile App.

---

## 🛠️ PHASE 1: Hardware Wiring & Connection Validation

_Goal: Ensure all physical sensors and relays are correctly connected to the ESP32._

### 1. Power Connections

- **Sensors**: Connect the `3.3V` pin of the ESP32 to the VCC/Power pins of the DHT22, DS18B20, Rain Sensor, and Soil Moisture Sensor.
- **Relay Module**: Connect the `5V/VIN` pin of the ESP32 to the Relay Module VCC.
- **Ground**: Connect all `GND` pins from sensors and relays to the ESP32 `GND`.

### 2. Sensor Data Connections

- **Soil Moisture Sensor**: Connect the Analog Out (AOUT) to **GPIO 34**.
- **DHT22 (Air Temp/Humidity)**: Connect the Data pin to **GPIO 4**. _(Add a 10kΩ pull-up resistor between Data and 3.3V)._
- **DS18B20 (Soil Temp)**: Connect the Data pin to **GPIO 5**. _(Add a 4.7kΩ pull-up resistor between Data and 3.3V)._
- **Rain Sensor**: Connect the Digital Out (DO) to **GPIO 33**.

### 3. Actuator (Motor/Valve) Connections

- **Water Pump (Relay CH1)**: Connect **GPIO 16** to IN1 on the relay board.
- **Zone 1 Valve (Relay CH2)**: Connect **GPIO 17** to IN2.
- **Foggers (Relay CH3)**: Connect **GPIO 18** to IN3.
- **Field Lights (Relay CH4)**: Connect **GPIO 19** to IN4.
  > **Motor Wiring**: Cut the live wire of your 12V/220V water pump. Connect one end to the **COM** terminal of Relay CH1, and the other end to the **NO (Normally Open)** terminal.

---

## 💻 PHASE 2: Uploading the ESP32 Code

_Goal: Tell the hardware how to connect to your Wi-Fi and where to send data._

1. Open `esp32_firmware/config.h` in your code editor.
2. Update the **Wi-Fi Credentials**:
   ```cpp
   #define WIFI_SSID "Your_Home_WiFi"
   #define WIFI_PASSWORD "Your_Password"
   ```
3. Update the **Backend URL**. This is the IP address of the computer that will run your Python server.
   ```cpp
   #define BACKEND_URL "http://192.168.1.10:8000"
   ```
4. Connect the ESP32 to your PC via USB and upload the `AgriSense_ESP32.ino` code using the Arduino IDE.

---

## 🗄️ PHASE 3: Database & Authentication Setup (Supabase)

_Goal: Ensure the website and mobile app share the exact same data, and enforce the "4 ESP32s per Email" rule._

1. **Create a Supabase Project**: Go to Supabase.com, create a project, and get your API URL and Anon Key.
2. **Setup Authentication**:
   - Enable Email/Password authentication in Supabase.
   - When a farmer logs into the Website OR the Mobile App with `farmer@agrisense.ai`, Supabase provides a secure authentication token.
3. **Create the Database Tables**: You need three main tables in your PostgreSQL database:
   - `users_profile`: Stores the farmer's email and user ID.
   - `devices`: Links the `DEVICE_ID` (e.g., AGS-7F3K21) to the farmer's `user_id`. You will enforce a database limit (Trigger/Constraint) so a single `user_id` can only have a maximum of **4 devices** linked.
   - `telemetry_data`: Stores every sensor reading, tagged with the `DEVICE_ID` and a timestamp.

---

## 🌉 PHASE 4: The Python Backend (The Bridge)

_Goal: Move data securely between the ESP32, the Database, and the Website/App._

You will build a Python FastAPI server. It does three things:

1. **Receive Data (POST)**: Every 10 seconds, the ESP32 sends JSON data to `http://your-server:8000/api/telemetry`. The Python server saves this data into the Supabase `telemetry_data` table.
2. **Hold Commands**: When you click "Turn Pump On" on the website, it saves the command `PUMP_ON` in the database. When the ESP32 asks `/api/device/command` every 5 seconds, Python replies with `PUMP_ON`.
3. **Broadcast Live (WebSockets)**: As soon as Python receives sensor data from the ESP32, it instantly blasts that data out over a WebSocket.

---

## 🌐 PHASE 5: Connecting the Website & App for Real-Time Control

_Goal: See live data moving on the screen and click buttons to control motors._

Because your Website and Mobile App both connect to the **same Supabase database** and the **same Python Backend**, they are perfectly synchronized.

### Getting Live Data on the Website:

In your `web_dashboard/app.js`, you will remove the dummy simulation loop and add WebSocket code:

```javascript
const ws = new WebSocket("ws://192.168.1.10:8000/ws");

ws.onmessage = function (event) {
  const realData = JSON.parse(event.data);

  // Update the UI instantly!
  state.telemetry.soilMoisture = realData.soil;
  state.telemetry.temperature = realData.temp;
  updateTelemetryUI();
};
```

### Controlling Motors from the Website:

When you click the toggle switch on the website, `app.js` sends a command to the backend:

```javascript
function handleControlPumpToggle(checked) {
  const action = checked ? "PUMP_ON" : "PUMP_OFF";

  // Send command to Python Backend
  fetch("http://192.168.1.10:8000/api/website/command", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: "AGS-7F3K21", command: action }),
  });
}
```

_The Python backend receives this, and 5 seconds later, the ESP32 pulls the command and clicks the physical relay to turn on your water pump!_
