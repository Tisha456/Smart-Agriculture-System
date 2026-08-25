export type ConnectionState = 'NO_DEVICE' | 'OFFLINE' | 'ONLINE_NO_SENSORS' | 'LIVE';

export type AutomationMode = 'NONE' | 'MOISTURE' | 'TIMER';

export type PumpCommand = 'PUMP_ON' | 'PUMP_OFF';

export interface Device {
  id: string; // device_id, e.g. "AGS-0001"
  name: string;
  sector: string;
  boundAt: string;
}

export interface TelemetryRow {
  device_id: string;
  soil_moisture: number | null;
  temperature: number | null;
  humidity: number | null;
  soil_temp: number | null;
  solar_radiation: number | null;
  rain_detected: boolean | null;
  battery_pct: number | null;
  rssi: number | null;
  created_at: string;
}

export interface SensorFlags {
  dht?: boolean;
  soil?: boolean;
  rain?: boolean;
}

export interface DeviceStatusRow {
  device_id: string;
  last_seen_at: string;
  sensors_ok: boolean;
  sensor_flags: SensorFlags;
  firmware_version: string | null;
  ip_address: string | null;
  rssi: number | null;
  boot_count: number | null;
}

export interface DeviceConfigRow {
  device_id: string;
  automation_mode: AutomationMode;
  start_threshold: number;
  stop_threshold: number;
  max_runtime_mins: number;
  pump_on: boolean;
  pump_on_since: string | null;
}

export interface Timer {
  id: number;
  device_id: string;
  start_time: string; // "HH:MM" 24h, matches timers.start_time
  duration_mins: number;
  active_days: string[]; // subset of ['Mo','Tu','We','Th','Fr','Sa','Su']
  is_active: boolean;
}

export interface Presence {
  lastSeenMs: number | null;
  sensorsOk: boolean;
  sensorFlags: SensorFlags;
  firmwareVersion: string | null;
  ipAddress: string | null;
  rssi: number | null;
}

export interface TelemetrySnapshot {
  hasData: boolean;
  lastDataMs: number | null;
  soilMoisture: number;
  temperature: number;
  humidity: number;
  soilTemp: number;
  rainDetected: boolean;
}

export interface History {
  soil: number[];
  temp: number[];
  humid: number[];
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
}

export type PlantSeverity = 'none' | 'mild' | 'moderate' | 'severe';

export interface PlantDiagnosis {
  species: string;
  species_confidence: number;
  condition: string | null;
  condition_confidence: number;
  joint_confidence: number;
  low_confidence: boolean;
  model_version: string;
  inference_ms: number;
  // Present only from the Gemini fallback path (see backend/main.py
  // /api/plant/predict) — the trained serving API doesn't return these yet.
  is_plant?: boolean;
  healthy?: boolean;
  severity?: PlantSeverity;
  affected_area_pct?: number;
  symptoms?: string[];
  cause?: string;
  treatment?: string[];
  prevention?: string[];
  notes?: string;
}

export const ALL_DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su'] as const;

export const CLAIM_ERROR_MESSAGES: Record<string, string> = {
  NOT_LOGGED_IN: 'Your session expired. Please log in again.',
  UNKNOWN_DEVICE:
    "No AgriSense board with that serial and secret exists. Check the label on your ESP32.",
  DEVICE_OFFLINE:
    "Board recognised, but it hasn't reported in. Power on the ESP32, wait 15 seconds, then retry.",
  CLAIMED_BY_OTHER: 'That board is already paired to another account.',
  ALREADY_YOURS: "You've already paired this board.",
};
