# AgriSense AI — ESP32-CAM Flashing Guide

How to get `AgriSense_ESP32CAM/AgriSense_ESP32CAM.ino` onto an AI-Thinker
ESP32-CAM. The board has **no USB port and no auto-reset circuit**, so it needs
an external USB-to-serial adapter and a manual boot-mode sequence. That is the
whole reason flashing it is fiddly.

---

## FIRST — what you canNOT do

| Idea | Verdict |
|------|---------|
| Run the camera on an **ESP8266** (NodeMCU / Wemos D1) | **Impossible.** The ESP8266 has no DVP/I2S camera interface and ~40 KB of free RAM. A single VGA JPEG is bigger than that. This is a silicon limitation, not a wiring problem. |
| Move the camera to a plain **ESP32 DevKit V1** | **Not practical.** The OV2640 is soldered to the ESP32-CAM PCB — there is no ribbon to unplug. The camera needs 8 data + 5 control GPIOs; DevKit V1 has no PSRAM and its 34/35/36/39 pins are input-only. |
| Use an ESP32 / ESP8266 board as the **programmer** | **Yes — this works.** Hold its own MCU in reset and its USB-serial chip becomes a plain USB-to-TTL bridge. Covered below as Option C and D. |

So: the ESP32-CAM stays the camera board. The other board is only the cable.

---

## PICK A PROGRAMMER

| Option | Hardware | Notes |
|--------|----------|-------|
| **A** | ESP32-CAM-MB dock | Easiest. Board snaps in, has micro-USB and a BOOT button. Buy this if flashing keeps failing. |
| **B** | FTDI FT232RL / CP2102 adapter | The standard. What you have now. |
| **C** | Spare ESP32 DevKit V1 | Works, no extra purchase. |
| **D** | Spare NodeMCU ESP8266 | Works, same trick as C. |

---

## OPTION A — ESP32-CAM-MB dock

1. Seat the ESP32-CAM in the dock (camera side up, pins fully in).
2. Plug micro-USB into your PC.
3. Hold the dock's **BOOT** button, click Upload, keep holding until the
   `Connecting....` line turns into `Writing at 0x...`.
4. Release BOOT. Press **RST** when it finishes.

Driver: the dock uses a **CH340**. If no COM port appears, install the CH340
driver from WCH.

---

## OPTION B — FTDI / CP2102 adapter

Set the adapter's voltage jumper to **5V**. The 3.3V rail on most adapters
cannot source the ~300 mA the camera pulls, and the resulting brownouts look
exactly like a wiring fault.

```
FTDI adapter            ESP32-CAM
  5V   ---------------->  5V
  GND  ----------+----->  GND
  TX   ---------------->  U0R      (crossed: TX goes to RX)
  RX   <----------------  U0T      (crossed: RX comes from TX)
                 |
                 +----->  IO0      <- jumper wire, GND to IO0
```

**TX and RX are crossed here.** This is the normal case: a dedicated adapter
exposes the UART's own pins.

---

## OPTION C — ESP32 DevKit V1 as the programmer

Hold the DevKit's ESP32 in reset so it stops driving the UART, leaving its
onboard CP2102/CH340 as a bare USB-to-TTL bridge.

```
ESP32 DevKit V1         ESP32-CAM
  EN   --> GND          (jumper on the DevKit — do this FIRST)

  5V / VIN ----------->  5V
  GND  ----------+----->  GND
  TX0  ---------------->  U0T      <- NOT crossed
  RX0  ---------------->  U0R      <- NOT crossed
                 |
                 +----->  IO0
```

**Why TX-to-TX and RX-to-RX here:** you are not tapping the ESP32's UART, you
are tapping the *USB chip's* side of it. The header pin labelled `RX0` is driven
by the USB chip's transmitter, and `TX0` feeds the USB chip's receiver. Wiring
it "correctly" crossed gives you silence.

The `EN -> GND` jumper is mandatory. Without it the DevKit's own ESP32 fights
for the same TX line and you get garbage or nothing.

> Power warning: USB gives ~500 mA total and the DevKit's regulator eats some.
> If flashing starts then dies partway, power the ESP32-CAM from a separate 5V
> supply and connect only GND, TX, RX, IO0 between the two boards.

---

## OPTION D — NodeMCU ESP8266 as the programmer

Same idea, different reset pin.

```
NodeMCU ESP8266         ESP32-CAM
  RST  --> GND          (jumper on the NodeMCU — do this FIRST)

  VIN / 5V ----------->  5V        <- the 5V pin, NOT 3V3
  GND  ----------+----->  GND
  TX   ---------------->  U0T      <- NOT crossed (same reason as Option C)
  RX   ---------------->  U0R      <- NOT crossed
                 |
                 +----->  IO0
```

Do **not** power the camera from NodeMCU's `3V3` pin — its AMS1117 regulator
browns out under the camera's current draw.

---

## THE FLASH SEQUENCE (all options)

Order matters. IO0 is only sampled at boot.

1. Wire everything as above, **including the IO0 to GND jumper**.
2. Plug in USB / power on. (If already powered: press **RST** on the
   ESP32-CAM with IO0 still grounded.)
3. Click Upload. Wait for `Writing at 0x00001000...`.
4. When it says `Hard resetting via RTS pin...`, **remove the IO0 jumper**.
5. Press **RST** once. The sketch now runs.

If you skip step 4, the board just reboots back into the bootloader and does
nothing — that is not a failed flash.

---

## ARDUINO IDE BOARD SETTINGS

Use the **desktop Arduino IDE**, not the web editor. The Arduino Cloud agent
hardcodes `--baud 460800`, which many adapters cannot sustain, and gives you no
way to lower it.

| Setting | Value |
|---------|-------|
| Board | `AI Thinker ESP32-CAM` |
| Partition Scheme | `Huge APP (3MB No OTA/1MB SPIFFS)` |
| PSRAM | `Enabled` |
| Upload Speed | `115200` — start here, raise only once it works |
| Port | the adapter's COM port |

Required library: **ArduinoJson** v6.x (Benoit Blanchon). `esp_camera.h`, `WiFi`
and `HTTPClient` ship with the ESP32 core.

Before uploading, edit the CONFIGURATION block at the top of the `.ino`:
`WIFI_SSID`, `WIFI_PASSWORD`, `DEVICE_ID`, and `CAM_UPLOAD_KEY` (must match
`CAM_UPLOAD_KEY` in `backend/.env`).

---

## TROUBLESHOOTING

### `Could not open COMx, the port doesn't exist`

Two devices are assigned the same COM number — usually a stale Bluetooth serial
port squatting on a low number. Check for duplicates:

```powershell
Get-PnpDevice -Class Ports -PresentOnly | Select-Object Status,FriendlyName
reg query "HKLM\HARDWARE\DEVICEMAP\SERIALCOMM"
```

If two rows show the same `(COMx)`, reassign the USB adapter: Device Manager →
Ports → the adapter → Properties → Port Settings → Advanced → COM Port Number →
pick an unused number. **Then unplug and replug the adapter** — the driver only
reads the new number at enumeration.

### `Failed to connect to ESP32: No serial data received`

The chip is not in download mode. In order of likelihood:

1. IO0 not grounded, or grounded only *after* power-on. Redo the sequence above.
2. TX/RX orientation wrong — crossed for Option B, straight for C and D.
3. Adapter jumper on 3.3V instead of 5V, or the camera is browning out.
   Use a separate 5V supply.
4. Baud too high. Drop to 115200.
5. GND not shared between adapter and camera board.

Fastest isolation test — this only touches the serial link, no sketch involved:

```
C:/Users/ankul/.arduino-create/esp32/esptool_py/4.5.1/esptool.exe --chip esp32 --port COM12 --baud 115200 chip_id
```

If `chip_id` fails, stop debugging the sketch — it is wiring, power, or boot
mode.

### `Brownout detector was triggered` in Serial Monitor

Flash succeeded, power supply is too weak. Use a 5V/1A+ supply on the `5V` pin.

### `Camera init failed with error 0x20004`

Camera ribbon not seated. Unlatch the connector, reseat, latch. Also confirm
Board = `AI Thinker ESP32-CAM` — a wrong board selection loads the wrong pin map.

### `Camera probe failed` / restarts on boot

PSRAM disabled in Tools, or a clone board without PSRAM. The firmware already
falls back to QVGA when `psramFound()` is false; if it still fails, enable PSRAM
in Tools and re-flash.

---

## AFTER FLASHING

Serial Monitor at **115200 baud**. Expect Wi-Fi to connect, the camera to init,
then the idle poll loop. If it connects to Wi-Fi but every upload returns 401,
`CAM_UPLOAD_KEY` in the sketch does not match `backend/.env`.

Sensor node wiring (soil / rain / DHT11 / relay) is a different board — see
[WIRING_GUIDE.md](WIRING_GUIDE.md).
