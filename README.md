# 🌱 AgriSense AI 

**An AI-Powered Smart Agriculture Decision Support System**

AgriSense AI is a full-stack smart agriculture platform that unifies IoT sensor telemetry, computer-vision-based crop disease detection, and Large Language Model (LLM) reasoning into a single cohesive system. It helps farmers monitor field conditions in real-time, automates irrigation, and provides context-aware, personalized agronomic recommendations.

---

## 🎯 Executive Summary

Smallholder and mid-scale farmers frequently lack affordable, real-time visibility into their field conditions. Generic advice often fails to account for a specific farm's live sensor readings, weather forecast, or crop history.

**AgriSense AI solves this through a closed-loop system:**
1. **IoT Field Nodes (ESP32)** continuously report environmental data.
2. **Automated Irrigation** triggers water pumps based on soil moisture and weather forecasts.
3. **Computer Vision (EfficientNet)** identifies crop diseases from farmer-uploaded leaf images.
4. **Decision Engine (LLM)** combines vision output, live sensor data, and weather forecasts into a structured context to generate highly specific, farm-relevant guidance.

> **The Core AI Philosophy**: We train one high-quality computer vision model for the narrow task of plant/disease identification, and delegate broader reasoning (fertilizer choice, pesticide advice, irrigation timing) to a general-purpose LLM fed with real-time farm context.

---

## ✨ Key Features

### 📡 Real-Time Environmental Monitoring
* Continuously captures **temperature, humidity, soil moisture, and rainfall** from the field.
* Displays live telemetry via WebSocket to the Next.js web dashboard and React Native mobile app.
* Buffers data locally on the ESP32 during connectivity drops to ensure no data loss.

### 💧 Smart Automated Irrigation
* Triggers water pumps automatically when soil moisture falls below user-configured thresholds.
* **Weather & Rain Aware**: The system checks live rain sensors and short-term weather forecasts. If rain is falling or expected within 24 hours, irrigation is paused to conserve water.
* Supports manual overrides from the dashboard or mobile app.

### 🍃 AI Crop Disease Detection
* Farmers can snap a photo of a leaf to receive an automated **Plant + Disease + Confidence** classification.
* Powered by a custom-trained **EfficientNet (B3/B4)** model.

### 🧠 Context-Aware LLM Recommendations
* The **Decision Engine** merges the disease prediction with live sensor readings, weather forecasts, and farm history.
* This structured context is sent to an LLM (Gemini/Claude/GPT) to produce specific fertilizer, pesticide, and irrigation guidance tailored *exactly* to what is happening on the farm right now.
* Features a **conversational AI assistant** that farmers can chat with for follow-up questions.

### 🔐 Secure Device & Account Architecture
* Strict separation between **Device Identity** (Hardware ID + Password) and **Farmer Identity** (Email + Password via Supabase Auth).
* Supports up to 4 devices per farmer account with absolute data isolation between different farmers.

---

## 🏗️ System Architecture

AgriSense AI is composed of five cooperating layers:

1. **Field / IoT**: ESP32, DHT22, soil moisture probe, rain sensor, relay, OLED.
2. **Backend / API**: FastAPI (Python) exposing REST endpoints and WebSocket channels.
3. **Data**: PostgreSQL (hosted on Supabase) and Supabase Storage for images.
4. **AI / Reasoning**: EfficientNet (PyTorch) for Vision + Gemini/Claude/GPT for the Decision Engine.
5. **Client**: Next.js (Web) and React Native/Expo (Mobile).

```text
ESP32 (Sensors + Relay) 
       │
       ▼
FastAPI Backend ──▶ PostgreSQL (Supabase)
       │
       ├─▶ WebSocket Broadcast ──▶ Web Dashboard & Mobile App
       │
       └─▶ Decision Engine (Sensors + Weather + Vision) ──▶ LLM ──▶ Recommendation
```

---

## 🛠️ Technology Stack

| Category | Technology |
|---|---|
| **IoT / Firmware** | ESP32, C++/Arduino, PlatformIO |
| **Backend API** | Python 3.11+, FastAPI, Uvicorn |
| **Database & Auth** | PostgreSQL, Supabase Auth, Supabase Storage |
| **Machine Learning** | PyTorch, EfficientNet (Trained on Colab/Kaggle) |
| **Reasoning Engine** | Gemini / Claude / OpenAI API |
| **Web Client** | React, Next.js, CSS3 Grid |
| **Mobile Client** | React Native, Expo |

---

## 📚 Documentation Directory

For deep technical details, refer to the original specification documents located in the `documents/` folder:

1. **[Product Requirements Document (PRD)](documents/AgriSense_AI_PRD.docx)**: The authoritative source of truth for the scope, features, non-functional requirements, and personas.
2. **[System Workflow & Functioning](documents/AgriSense_AI_Workflow_and_Functioning.docx)**: An operational walkthrough of how data flows from sensors to the LLM and back to the farmer.
3. **[AI Model Development Guide](documents/AgriSense_AI_Model_Development_Guide.docx)**: The AI strategy, explaining the split between the PyTorch EfficientNet CV model and the LLM reasoning layer, including training methodology.
4. **[Implementation Plan](documents/AgriSense_AI_Implementation_Plan.docx)**: The phased engineering roadmap, deployment steps, and testing matrix.
5. **[Device Connectivity Architecture](documents/AgriSense_AI_Device_Connectivity_Architecture.md)**: Details the dual-identity system ensuring secure device binding and multi-tenant data isolation.

---

## 🚀 Getting Started (Local Development)

1. **Environment Setup**: 
   - Provision a Supabase project (Auth, Database, Storage).
   - Obtain API keys for OpenWeather and your chosen LLM provider.
2. **Backend Config**:
   - Clone the repo and populate your `.env` file based on `.env.example`.
   - Run the FastAPI server using `uvicorn`.
3. **Client Config**:
   - Navigate to the web/mobile directories and run `npm install` followed by `npm run dev` to start the frontend.
4. **Hardware**:
   - Flash the ESP32 firmware using PlatformIO/Arduino IDE after updating the Wi-Fi and backend URL constants.

*(Refer to the Implementation Plan for detailed phase-by-phase build instructions.)*

---
*AgriSense AI — Cultivating intelligence for the modern smallholder farm.*
