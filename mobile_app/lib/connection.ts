import type { ConnectionState } from './types';

// The ESP32 heartbeats every 10s, so 3 misses = offline. Matches
// web_dashboard/app.js exactly — both clients must agree on this threshold.
export const OFFLINE_AFTER_MS = 30000;

export function computeConnectionState(args: {
  hasDevice: boolean;
  lastSeenMs: number | null;
  sensorsOk: boolean;
}): ConnectionState {
  if (!args.hasDevice) return 'NO_DEVICE';
  if (!args.lastSeenMs) return 'OFFLINE';
  if (Date.now() - args.lastSeenMs > OFFLINE_AFTER_MS) return 'OFFLINE';
  return args.sensorsOk ? 'LIVE' : 'ONLINE_NO_SENSORS';
}
