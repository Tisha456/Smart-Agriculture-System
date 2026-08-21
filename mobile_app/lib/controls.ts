// Centralized control communication layer. UI components and hooks never
// call fetch()/supabase commands directly for controls — everything routes
// through here, and every function maps 1:1 onto an endpoint/RPC that
// already exists in backend/main.py or the Supabase schema. Nothing here
// invents a new command vocabulary.
import { supabase, BACKEND_BASE } from './supabase';
import type { AutomationMode, PumpCommand, Timer } from './types';

function requireBackend() {
  if (!BACKEND_BASE) {
    throw new Error(
      'EXPO_PUBLIC_BACKEND_URL is not set — automation, timers and pump/force-stop commands need the FastAPI backend reachable from this phone.'
    );
  }
}

async function backendFetch(path: string, init?: RequestInit) {
  requireBackend();
  const resp = await fetch(`${BACKEND_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    let detail = `Backend responded ${resp.status}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON — keep the generic message
    }
    throw new Error(detail);
  }
  return resp.json();
}

// ── Pump / Force Stop ────────────────────────────────────────────────────
// POST /api/command — per backend/main.py this single endpoint is already
// "manual pump ON/OFF (also used by Force Stop)". It upserts device_config
// (pump_on, automation_mode -> NONE) synchronously, so device_config is
// always the real resulting state, which is Realtime-subscribed elsewhere.
export async function sendPumpCommand(deviceId: string, command: PumpCommand) {
  return backendFetch('/api/command', {
    method: 'POST',
    body: JSON.stringify({ device_id: deviceId, command }),
  });
}

export async function forceStop(deviceId: string) {
  return sendPumpCommand(deviceId, 'PUMP_OFF');
}

// ── Automation ───────────────────────────────────────────────────────────
export async function setAutomationMode(
  deviceId: string,
  mode: AutomationMode,
  thresholds: { startThreshold: number; stopThreshold: number; maxRuntimeMins: number }
) {
  return backendFetch('/api/automation/mode', {
    method: 'POST',
    body: JSON.stringify({
      device_id: deviceId,
      mode,
      start_threshold: thresholds.startThreshold,
      stop_threshold: thresholds.stopThreshold,
      max_runtime_mins: thresholds.maxRuntimeMins,
    }),
  });
}

export async function getAutomationState(deviceId: string) {
  return backendFetch(`/api/automation/state/${encodeURIComponent(deviceId)}`) as Promise<{
    device_id: string;
    automation_mode: AutomationMode;
    pump_on: boolean;
    start_threshold: number;
    stop_threshold: number;
    max_runtime_mins: number;
  }>;
}

// ── Timers ───────────────────────────────────────────────────────────────
export async function loadTimers(deviceId: string, accessToken: string): Promise<Timer[]> {
  const data = await backendFetch(`/api/timers/${encodeURIComponent(deviceId)}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  });
  return data.timers ?? [];
}

export async function saveTimer(
  payload: {
    deviceId: string;
    startTime: string;
    durationMins: number;
    activeDays: string[];
  },
  accessToken: string
) {
  return backendFetch('/api/timers', {
    method: 'POST',
    body: JSON.stringify({
      device_id: payload.deviceId,
      start_time: payload.startTime,
      duration_mins: payload.durationMins,
      active_days: payload.activeDays,
      user_token: accessToken,
    }),
  });
}

export async function toggleTimer(id: number, isActive: boolean, accessToken: string) {
  return backendFetch(`/api/timers/${id}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ is_active: isActive }),
  });
}

export async function deleteTimer(id: number, accessToken: string) {
  return backendFetch(`/api/timers/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${accessToken}` },
  });
}

// The backend has no "edit a timer" endpoint — only add / delete / toggle
// is_active. Editing reuses those two existing operations rather than
// inventing a new one.
export async function updateTimer(
  existing: Timer,
  changes: { startTime: string; durationMins: number; activeDays: string[] },
  accessToken: string
) {
  await deleteTimer(existing.id, accessToken);
  await saveTimer(
    {
      deviceId: existing.device_id,
      startTime: changes.startTime,
      durationMins: changes.durationMins,
      activeDays: changes.activeDays,
    },
    accessToken
  );
}

// ── Pairing ──────────────────────────────────────────────────────────────
export async function claimDevice(args: {
  deviceId: string;
  secret: string;
  name: string;
  sector: string;
}) {
  const { data, error } = await supabase.rpc('claim_device', {
    p_device_id: args.deviceId,
    p_secret: args.secret,
    p_name: args.name,
    p_sector: args.sector,
  });
  if (error) throw new Error(error.message || 'Failed to bind device.');
  return data as { ok: boolean; code?: string; device_id?: string };
}

export async function unbindDevice(deviceId: string, userId: string) {
  const { error } = await supabase
    .from('devices')
    .delete()
    .eq('device_id', deviceId)
    .eq('user_id', userId);
  if (error) throw new Error(error.message);
}
