// Live ESP32-CAM view — mint a short-lived viewer token from the backend,
// then hand the caller a URL to the camera.html page (served by the same
// backend/main.py that serves web_dashboard/), which opens in the system
// browser. Routes through /api/camera/{device_id}/token, never straight to
// the stream — same reasoning as lib/plant.ts and lib/advisor.ts.
import { BACKEND_BASE } from './supabase';

function requireBackend() {
  if (!BACKEND_BASE) {
    throw new Error(
      'EXPO_PUBLIC_BACKEND_URL is not set — the live camera needs the FastAPI backend reachable from this phone.'
    );
  }
}

export async function getLiveCameraUrl(deviceId: string, token: string): Promise<string> {
  requireBackend();

  const resp = await fetch(`${BACKEND_BASE}/api/camera/${deviceId}/token`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!resp.ok) {
    let detail = `Could not start the camera (${resp.status})`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON — keep the generic message
    }
    throw new Error(detail);
  }

  const { token: camToken } = await resp.json();
  return `${BACKEND_BASE}/camera.html?t=${encodeURIComponent(camToken)}`;
}
