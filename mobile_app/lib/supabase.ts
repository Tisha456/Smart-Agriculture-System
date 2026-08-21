import 'react-native-url-polyfill/auto';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { createClient } from '@supabase/supabase-js';
import { AppState } from 'react-native';

const SUPABASE_URL = process.env.EXPO_PUBLIC_SUPABASE_URL;
const SUPABASE_ANON_KEY = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY;

if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
  throw new Error(
    'Missing EXPO_PUBLIC_SUPABASE_URL / EXPO_PUBLIC_SUPABASE_ANON_KEY — copy .env.example to .env and fill them in.'
  );
}

// Same Supabase project, same anon key, same auth.users, same RLS policies
// as web_dashboard/app.js — there is no separate mobile backend.
export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY, {
  auth: {
    storage: AsyncStorage,
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: false,
  },
});

// Only refresh the auth token while the app is actually in the foreground.
AppState.addEventListener('change', (nextState) => {
  if (nextState === 'active') {
    supabase.auth.startAutoRefresh();
  } else {
    supabase.auth.stopAutoRefresh();
  }
});

// Realtime subscriptions (telemetry_data, device_status, device_config) are
// RLS-scoped, so they need the current access token, not just the anon key.
supabase.auth.onAuthStateChange((_event, session) => {
  supabase.realtime.setAuth(session?.access_token ?? SUPABASE_ANON_KEY);
});

// FastAPI backend — automation mode, timers, pump/force-stop commands only.
// Telemetry, presence, pairing and monitoring never touch this.
export const BACKEND_BASE = (process.env.EXPO_PUBLIC_BACKEND_URL ?? '').replace(/\/+$/, '');
