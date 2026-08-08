# AgriSense AI — Device Connectivity & Account Architecture

**Version 1.0**

This document explains how physical ESP32 hardware, farmer accounts, the
website, and the future mobile app all fit together — specifically how a
device gets identified, how it gets bound to a farmer's account, how one
account can manage multiple devices, and how different customers' data
stays completely separate.

---

## 1. Core Concept: Two Separate Identities

There are **two independent identity systems** in AgriSense AI, and the
entire architecture exists to connect them safely.

| Identity | Belongs to | Used for | Set by |
|---|---|---|---|
| **Device ID + Device Password** | The physical ESP32 unit | Authenticating hardware → backend telemetry | Manufactured/flashed once, printed on the unit |
| **Email + Account Password** | The human farmer | Logging into the website / app | Chosen by the farmer at signup |

These two never merge into one credential. The device authenticates
itself to the backend independently of any human login. A farmer's login
never touches the device directly — it only ever talks to the backend,
which decides what data to show based on which devices are bound to that
account.

---

## 2. Device Provisioning (Before It Reaches a Farmer)

1. During manufacturing/firmware flashing, each ESP32 unit is assigned a
   **unique Device ID** (e.g. `AGS-7F3K21`) and a **unique Device
   Password**, both stored in the unit's firmware and printed on a
   label/box.
2. The backend records this device in the `devices` table as
   **unbound** — it exists in the system, but has no owning account yet.
3. No two units ever share the same Device ID + Password. This
   uniqueness is what keeps every customer's hardware distinguishable
   from every other customer's.

---

## 3. What Happens When a Farmer Gets a Device

### Step 1 — Power on
The farmer powers on the ESP32 and connects it to Wi-Fi. It immediately
starts sending telemetry (sensor readings, heartbeat) to the backend
using its own Device ID + Password for authentication. At this point the
backend receives data but has no account to associate it with — it sits
as "unclaimed."

### Step 2 — Create an account
The farmer signs up on the website or app with a normal **email +
password** (Supabase Auth). This step has nothing to do with the
hardware yet.

### Step 3 — Bind the device
On the "Connect Hardware" screen, the farmer enters:
- **Device ID**
- **Device Password**

(both from the sticker/box on the physical unit)

The backend validates:
- Does this Device ID exist?
- Does the password match?
- Is it currently unbound (or bound to *this* account already)?

If valid, the backend writes a single record linking that
`device_id → account_id`. This is the **binding**, and it is a
**one-time action**.

### Step 4 — Everything after that is automatic
From this point forward:
- The ESP32 keeps authenticating with its own Device ID + Password —
  nothing changes on the hardware side.
- The backend now knows which account owns that device, so every
  telemetry reading, camera frame, and pump-state change is routed and
  stored under that account.
- Whenever the farmer logs into the **website or the app** with their
  email, the backend looks up "which devices does this account own?" and
  returns live data for all of them.
- **The farmer never re-enters the Device ID/Password again**, and
  logging in from a new device (their phone, a new browser) shows the
  exact same data, because both clients are reading from the same
  backend/account — not from the hardware directly.

---

## 4. Multiple Devices, One Account

- A single account (one email) can bind **between 1 and 4 devices**.
  This limit is enforced **server-side**, not just in the UI — the
  backend rejects a 5th bind attempt.
- This supports larger farms: a farmer might place separate ESP32 nodes
  across different fields or zones. All of them bind to the same email.
- The dashboard (web and app) shows a **device switcher** — e.g. tabs or
  a dropdown for "Field Node 1," "Field Node 2," etc. — each with its
  own live camera feed, sensor readings, and pump control, all under one
  login.

---

## 5. Multiple Different Customers, Fully Isolated Data

- Every unit shipped has a **different, unique** Device ID + Password —
  guaranteed unique across all customers.
- When Customer A binds their unit to their account, and Customer B
  binds a different unit to their account, the backend enforces strict
  account-scoped queries: Customer A's account can only ever fetch
  devices where `account_id = A`.
- Customer B's device, camera feed, sensor history, pump state, and
  recommendations are **completely invisible** to Customer A — even
  though both are using the identical website and app.
- This is standard multi-tenant isolation: the Device ID is the link
  between hardware and account; the `account_id` field is the wall that
  keeps tenants separate.

---

## 6. Data Model (Simplified)

| Table | Key Fields | Purpose |
|---|---|---|
| `accounts` | `id`, `email`, `password_hash`, `created_at` | Farmer login identity (Supabase Auth) |
| `devices` | `id`, `device_id`, `device_password_hash`, `account_id` (nullable until bound), `device_type` (sensor node / ESP32-CAM), `name`, `last_seen`, `status` | Physical hardware identity + binding state |
| `sensor_readings` | `id`, `device_id`, `timestamp`, `soil_moisture`, `temperature`, `humidity`, `rain_state` | Telemetry history |
| `irrigation_events` | `id`, `device_id`, `timestamp`, `action` (ON/OFF), `trigger` (manual / scheduled / smart-auto), `conditions` | Pump decision log |
| `predictions` | `id`, `account_id`, `image_url`, `plant`, `disease`, `confidence`, `severity` | AI disease-scan results |
| `recommendations` | `id`, `account_id`, `prediction_id`, `text`, `created_at` | LLM-generated guidance |

`device_id` is what the ESP32 sends on every request; `account_id` is
resolved server-side by looking up the binding — the device itself never
needs to know or store which account it belongs to.

---

## 7. Authentication Summary

| Actor | Authenticates with | Validated by |
|---|---|---|
| ESP32 hardware | Device ID + Device Password (or a token derived from them at bind time) | Backend checks against `devices` table |
| Farmer (web/app) | Email + Account Password → JWT session | Supabase Auth issues/validates the JWT |

Every client-facing API endpoint requires a valid JWT for the logged-in
account. Every hardware-facing ingestion endpoint requires a valid
Device ID + Password (or derived token) — the two auth paths never
cross.

---

## 8. Real-Time Data Flow

```
ESP32 Sensor Node ──┐
                     ├─→ FastAPI Backend ──→ PostgreSQL (Supabase)
ESP32-CAM ───────────┘         │
                                ├─→ WebSocket broadcast ──→ Web Dashboard
                                │                      └──→ Mobile App
                                └─→ Decision Engine (sensors + weather + 
                                    vision) → LLM → Recommendation
```

Because both the website and the app subscribe to the same backend for
the same account's bound devices, they always show identical, real-time
data — there is no separate "sync" step between them.

---

## 9. Website Scope vs. Mobile App Scope

| Section | Website | Mobile App |
|---|---|---|
| **Connect Hardware** | Login/signup, bind a device (Device ID + Password), view bound devices & status | Same, plus can bind on the go |
| **Live Monitor** | Live camera feed + sensor grid (weather, soil moisture, rain), device switcher | Same |
| **Pump Control** | Basic ON/OFF override, status view | Full control |
| **Irrigation Timers/Scheduling** | View only, "manage in app" | Full scheduling (e.g. daily 6:00 PM, 10 min) |
| **AI Disease Scan** | — (or basic teaser) | Full image capture/upload → prediction → recommendation |
| **AI Assistant Chat** | — (or basic teaser) | Full conversational assistant with farm context |

---

## 10. Pump Automation Logic (Runs in the Backend, Regardless of Client)

Two modes, both logged with their triggering conditions:

**Scheduled mode** — farmer sets a fixed time + duration (e.g. daily
6:00 PM for 10 minutes). The backend triggers the pump ON command at
that local time and OFF after the configured duration.

**Smart/automatic mode** — independent of or layered with scheduling:
1. If soil moisture drops below the configured threshold →
2. Check the rain sensor and the weather forecast for the next 24h
   (configurable) →
3. If rain is detected or forecast → keep the pump OFF (conserve water) →
4. If no rain → turn the pump ON →
5. Turn OFF automatically once soil moisture rises above the upper
   bound, or the max run time is reached — whichever happens first.

A manual override from web or app always takes precedence and is
clearly flagged and logged as such.

---

## 11. Edge Cases Worth Handling

- **Device goes offline**: flip `status` to "offline" if no telemetry is
  received within a configurable timeout; alert the farmer.
- **Wrong Device ID/Password entered**: reject the bind attempt with a
  clear error; do not reveal whether the ID exists (avoid leaking valid
  IDs to someone guessing).
- **Device already bound to another account**: reject the bind attempt
  — a device can only belong to one account at a time (until explicitly
  unbound/transferred).
- **Farmer sells/replaces a unit**: provide an "unbind device" action so
  the old owner's account releases it, allowing a new owner to bind it
  cleanly.
- **5th device bind attempt**: rejected server-side with a clear message
  ("Maximum of 4 devices per account").
- **LLM/weather provider outage**: fall back to rule-based guidance
  rather than failing the request.

---

## 12. One-Sentence Summary

Every ESP32 ships with its own fixed, unique Device ID + Password; a
farmer binds a device to their email account exactly once; from then on,
the website and the app both simply read that account's live data from
the shared backend — with a hard cap of 4 devices per account and
complete data isolation between different customers' accounts.
