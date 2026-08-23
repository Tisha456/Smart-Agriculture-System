// Farm advisor chat — ask a question, optionally grounded in a device's live
// telemetry. Routes through backend/main.py's /api/advisor/ask proxy, never
// directly to Gemini — the API key must stay server-side (same reasoning as
// lib/plant.ts's /api/plant/predict).
import { BACKEND_BASE } from './supabase';
import type { ChatMessage } from './types';

function requireBackend() {
  if (!BACKEND_BASE) {
    throw new Error(
      'EXPO_PUBLIC_BACKEND_URL is not set — the advisor needs the FastAPI backend reachable from this phone.'
    );
  }
}

export async function askAdvisor(
  question: string,
  deviceId: string | null,
  history: ChatMessage[],
  token: string
): Promise<string> {
  requireBackend();

  const resp = await fetch(`${BACKEND_BASE}/api/advisor/ask`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      question,
      device_id: deviceId,
      history: history.map((m) => ({ role: m.role === 'assistant' ? 'model' : 'user', text: m.text })),
    }),
  });

  if (!resp.ok) {
    let detail = `Advisor request failed (${resp.status})`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = body.detail;
    } catch {
      // response body wasn't JSON — keep the generic message
    }
    throw new Error(detail);
  }

  const data = await resp.json();
  return data.answer;
}
