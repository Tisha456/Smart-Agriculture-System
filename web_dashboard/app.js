// ── Supabase Configuration ─────────────────────────────────────────────────
const SUPABASE_URL = "https://iqmrpwvbmfkhychhditg.supabase.co";
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlxbXJwd3ZibWZraHljaGhkaXRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYyNTY5OTEsImV4cCI6MjEwMTgzMjk5MX0.i8wCUSDmc6DI8ZLK6wQeaZDzQqZCEIzkZUrrg2RnefQ";
// Hybrid architecture: website talks directly to Supabase (no FastAPI for telemetry).
// FastAPI is kept only for future automation/decision engine.

let supabaseClient = null;
if (window.supabase) {
  supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
}

// FastAPI is used ONLY for pump automation (moisture + timer modes).
// Telemetry, manual pump control, and device pairing go direct to Supabase
// and work fully even when this backend is not running.
const BACKEND_BASE = (location.protocol === 'file:')
  ? 'http://10.87.216.17:8000'   // edit if the backend moves — matches backend/main.py
  : location.origin;             // served by FastAPI itself when hosted (main.py serve_dashboard)

let activeRealtimeChannel = null;       // Supabase Realtime channel for telemetry_data
let activeStatusChannel   = null;       // Supabase Realtime channel for device_status (heartbeat)
let presenceTickerHandle  = null;       // setInterval handle — detects offline devices
let currentSession = null;

// A missed heartbeat window: the ESP32 heartbeats every 10s, so 3 misses = offline.
const OFFLINE_AFTER_MS = 30000;

// Application State
const state = {
  activeView: 'view-connect',
  currentUser: { loggedIn: false, email: null, id: null, token: null },
  devices: [],
  activeDeviceIndex: 0,
  telemetry: {
    hasData: false,          // false until first real packet from ESP32
    lastDataMs: null,        // timestamp of last received telemetry
    lastRowAt: null,         // created_at of that row — dedupes the poll's re-reads
    soilMoisture: 0,
    temperature: 0,
    tempUnit: 'C',
    humidity: 0,
    rainDetected: false,
    soilTemp: 0,
    solarRadiation: 0,
    npk: { n: 0, p: 0, k: 0 },
    battery: 0,
    signal: 0,
    targetThreshold: 70,
    stopThreshold: 85,
    maxRuntime: 20
  },
  // Split Analytics State
  analytics: {
    selectedIndex: 3, // Defaults to '2h Ago' (index 3 chronologically)
    series: {
      soil: { active: true, color: '#3ecf8e', label: 'Soil Moisture', unit: '%', min: 0, max: 100 },
      temp: { active: true, color: '#d29922', label: 'Temperature', unit: '°C', min: 0, max: 50 },
      humid: { active: true, color: '#58a6ff', label: 'Humidity', unit: '% RH', min: 0, max: 100 },
      solar: { active: true, color: '#a371f7', label: 'Solar PAR', unit: 'W/m²', min: 0, max: 1000 }
    },
    buffer: {
      labels: ['8h Ago', '6h Ago', '4h Ago', '2h Ago'],
      soil: [0, 0, 0, 0],
      temp: [0, 0, 0, 0],
      humid: [0, 0, 0, 0],
      solar: [0, 0, 0, 0],
      rain: [0, 0, 0, 0],
      npk: ['0/0/0', '0/0/0', '0/0/0', '0/0/0']
    }
  },
  pump: {
    state: 'OFF',
    automationMode: 'NONE'   // 'NONE' | 'MOISTURE' | 'TIMER'
  },
  // Live connection state for the currently selected device, fed by
  // device_status heartbeats. This is what "connected" actually means —
  // separate from Supabase Realtime channel subscription state, which only
  // proves the BROWSER reached Supabase, not that the ESP32 is alive.
  presence: {
    lastSeenMs: null,
    sensorsOk: false,
    sensorFlags: {},
    firmwareVersion: null,
    ipAddress: null,
    rssi: null,
    bootCount: null
  },
  timers: [],
  auditLog: [],
  pendingModalAction: null
};

// Derived connection state for the active device:
//   'NO_DEVICE'           — nothing bound to this account yet
//   'OFFLINE'             — no heartbeat, or heartbeat older than OFFLINE_AFTER_MS
//   'ONLINE_NO_SENSORS'   — heartbeat is fresh, but sensors_ok = false
//   'LIVE'                — heartbeat is fresh and sensors_ok = true
function connectionState() {
  if (!state.devices.length) return 'NO_DEVICE';
  if (!state.presence.lastSeenMs) return 'OFFLINE';
  if (Date.now() - state.presence.lastSeenMs > OFFLINE_AFTER_MS) return 'OFFLINE';
  return state.presence.sensorsOk ? 'LIVE' : 'ONLINE_NO_SENSORS';
}

// Initialization
document.addEventListener('DOMContentLoaded', async () => {
  setupNavigation();
  initCanvasEvents();

  // Modal Backdrop click handler
  const backdrop = document.getElementById('modalBackdrop');
  if (backdrop) {
    backdrop.addEventListener('click', (e) => {
      if (e.target.id === 'modalBackdrop') closeModal();
    });
  }

  const cameraBackdrop = document.getElementById('cameraBackdrop');
  if (cameraBackdrop) {
    cameraBackdrop.addEventListener('click', (e) => {
      if (e.target.id === 'cameraBackdrop') closeLiveCamera();
    });
  }

  window.addEventListener('resize', () => renderCanvasChart());

  // Re-evaluate connection state every 5s. This is required because going
  // OFFLINE produces no database event to react to — only the passage of
  // time (no heartbeat for OFFLINE_AFTER_MS) tells us the ESP32 died.
  presenceTickerHandle = setInterval(() => {
    // Re-read from the database, not just re-render cached state — Realtime
    // can silently stop delivering (see refreshDeviceData).
    const dev = state.devices[state.activeDeviceIndex];
    if (dev) refreshDeviceData(dev.id);
    updateTelemetryUI();
    updateHeaderStatusPill();
  }, 5000);

  // Check active Supabase session
  if (supabaseClient) {
    const { data: { session } } = await supabaseClient.auth.getSession();
    if (session) {
      onUserAuthenticated(session);
    } else {
      showAuthScreen();
    }

    supabaseClient.auth.onAuthStateChange((_event, session) => {
      if (session) {
        onUserAuthenticated(session);
      } else {
        showAuthScreen();
      }
    });
  }
});

// ── Auth Handlers ────────────────────────────────────────────────────────
function switchAuthTab(tab) {
  const loginForm = document.getElementById('loginForm');
  const signupForm = document.getElementById('signupForm');
  const tabLogin = document.getElementById('tabLogin');
  const tabSignup = document.getElementById('tabSignup');

  if (tab === 'login') {
    loginForm.style.display = 'block';
    signupForm.style.display = 'none';
    tabLogin.classList.add('active');
    tabSignup.classList.remove('active');
  } else {
    loginForm.style.display = 'none';
    signupForm.style.display = 'block';
    tabLogin.classList.remove('active');
    tabSignup.classList.add('active');
  }
}

function showAuthScreen() {
  document.getElementById('authScreen').style.display = 'flex';
  document.getElementById('mainApp').style.display = 'none';
  if (activeRealtimeChannel) {
    supabaseClient.removeChannel(activeRealtimeChannel);
    activeRealtimeChannel = null;
  }
  if (activeStatusChannel) {
    supabaseClient.removeChannel(activeStatusChannel);
    activeStatusChannel = null;
  }
  state.devices = [];
  state.presence = {
    lastSeenMs: null, sensorsOk: false, sensorFlags: {},
    firmwareVersion: null, ipAddress: null, rssi: null, bootCount: null
  };
}

async function onUserAuthenticated(session) {
  currentSession = session;
  state.currentUser = {
    loggedIn: true,
    email: session.user.email,
    id: session.user.id,
    token: session.access_token
  };

  document.getElementById('authScreen').style.display = 'none';
  document.getElementById('mainApp').style.display = 'block';

  // Show real email in the Session Active card on the Connect page
  const emailDisplay = document.getElementById('sessionEmailDisplay');
  if (emailDisplay) emailDisplay.textContent = session.user.email;

  showToast(`Welcome back, ${session.user.email}`, 'success');

  // Load user's bound devices from backend
  await fetchUserDevices();

  selectTimeInterval(3);
  renderCanvasChart();
  updateTelemetryUI();
}

async function handleLogin() {
  const email = document.getElementById('loginEmail').value.trim();
  const password = document.getElementById('loginPassword').value.trim();
  const errBox = document.getElementById('loginError');
  const btn = document.getElementById('loginBtn');

  errBox.style.display = 'none';
  btn.disabled = true;
  btn.innerText = 'Authenticating...';

  try {
    const { data, error } = await supabaseClient.auth.signInWithPassword({ email, password });
    if (error) throw error;
    // Session listener will trigger onUserAuthenticated
  } catch (err) {
    errBox.textContent = err.message || 'Login failed';
    errBox.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="material-symbols-outlined">login</span> Sign In to Dashboard';
  }
}

async function handleSignup() {
  const email = document.getElementById('signupEmail').value.trim();
  const password = document.getElementById('signupPassword').value.trim();
  const confirm = document.getElementById('signupConfirm').value.trim();
  const errBox = document.getElementById('signupError');
  const btn = document.getElementById('signupBtn');

  if (password !== confirm) {
    errBox.textContent = 'Passwords do not match';
    errBox.style.display = 'block';
    return;
  }

  errBox.style.display = 'none';
  btn.disabled = true;
  btn.innerText = 'Creating Account...';

  try {
    const { data, error } = await supabaseClient.auth.signUp({ email, password });
    if (error) throw error;
    showToast('Account created! Check your email to confirm it, then sign in.', 'success');
    switchAuthTab('login');
  } catch (err) {
    errBox.textContent = err.message || 'Signup failed';
    errBox.style.display = 'block';
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<span class="material-symbols-outlined">person_add</span> Create Account';
  }
}

async function handleLogout() {
  // Unsubscribe realtime channel before logging out
  if (activeRealtimeChannel) {
    supabaseClient.removeChannel(activeRealtimeChannel);
    activeRealtimeChannel = null;
  }
  if (supabaseClient) {
    await supabaseClient.auth.signOut();
  }
  showAuthScreen();
  showToast('Logged out successfully', 'info');
}

// SPA Navigation Router
function setupNavigation() {
  const tabs = document.querySelectorAll('.nav-tab-btn');
  const navTabsContainer = document.querySelector('.nav-tabs');
  const mobileMenuBtn = document.getElementById('mobileMenuBtn');

  // Mobile Menu Toggle
  if (mobileMenuBtn && navTabsContainer) {
    mobileMenuBtn.addEventListener('click', () => {
      navTabsContainer.classList.toggle('mobile-open');
    });
  }

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      // Close mobile menu on select
      if (navTabsContainer) {
        navTabsContainer.classList.remove('mobile-open');
      }

      const targetId = tab.getAttribute('data-target');
      document.querySelectorAll('.view-section').forEach(view => {
        view.classList.remove('active');
      });

      const targetView = document.getElementById(targetId);
      if (targetView) {
        targetView.classList.add('active');
        state.activeView = targetId;
      }

      if (targetId === 'view-dashboard') {
        setTimeout(() => renderCanvasChart(), 100);
      }
    });
  });
}

// ── Supabase Direct Integration ────────────────────────────────────────────
async function fetchUserDevices() {
  if (!supabaseClient || !state.currentUser.id) return;

  try {
    // Query devices table directly — RLS ensures users only see their own devices
    const { data, error } = await supabaseClient
      .from('devices')
      .select('*')
      .eq('user_id', state.currentUser.id);

    if (error) throw error;

    state.devices = (data || []).map(d => ({
      id: d.device_id,
      name: d.device_name || d.device_id,
      sector: d.sector || 'Active Field Sector',
      battery: 100,
      signal: 'Strong',
      boundAt: d.created_at ? d.created_at.split('T')[0] : 'Today'
    }));

    // Clamp in case the previously active index no longer exists (e.g. that
    // device was just unbound).
    if (state.activeDeviceIndex >= state.devices.length) {
      state.activeDeviceIndex = 0;
    }

    renderBoundDevices();
    updateHeaderDeviceSelector();
    updateHeaderStatusPill();

    if (state.devices.length > 0) {
      subscribeToDeviceRealtime(state.devices[state.activeDeviceIndex].id);
      loadTimers();
    }
  } catch (err) {
    console.error('Error fetching devices:', err);
    renderBoundDevices();
    updateHeaderDeviceSelector();
    updateHeaderStatusPill();
  }
}

// Apply one telemetry row to state + UI. Shared by the Realtime INSERT
// handler and the polling fallback so the two can never drift apart.
// `created_at` is tracked because the poll re-reads the same latest row
// repeatedly — without that guard it would push duplicates into the chart.
function applyTelemetryRow(data) {
  if (!data) return;
  const rowAt = data.created_at || null;
  const isNewRow = rowAt !== state.telemetry.lastRowAt;

  state.telemetry.hasData = true;
  state.telemetry.lastDataMs = Date.now();
  state.telemetry.lastRowAt = rowAt;

  state.telemetry.soilMoisture   = data.soil_moisture   || 0;
  state.telemetry.temperature    = data.temperature     || 0;
  state.telemetry.humidity       = data.humidity        || 0;
  state.telemetry.soilTemp       = data.soil_temp       || 0;
  state.telemetry.solarRadiation = data.solar_radiation || 0;
  state.telemetry.rainDetected   = !!data.rain_detected;
  state.telemetry.battery        = data.battery_pct     || 100;
  state.telemetry.signal         = data.rssi            || -70;

  if (isNewRow) {
    const buf = state.analytics.buffer;
    buf.soil.shift();  buf.soil.push(Math.round(data.soil_moisture || 0));
    buf.temp.shift();  buf.temp.push(Number((data.temperature || 0).toFixed(1)));
    buf.humid.shift(); buf.humid.push(Math.round(data.humidity || 0));
    buf.solar.shift(); buf.solar.push(Math.round(data.solar_radiation || 0));
    renderCanvasChart();
  }

  updateTelemetryUI();
}

// Re-read the latest heartbeat and the latest telemetry row.
// Realtime is the fast path, but it can silently deliver nothing (channel
// subscribed before the auth token applied, socket dropped on sleep/tab
// switch). Polling this means the page is never more than one ESP32 tick
// stale, instead of needing a manual refresh.
function refreshDeviceData(deviceId) {
  if (!supabaseClient || !deviceId) return;

  supabaseClient
    .from('device_status')
    .select('last_seen_at, sensors_ok, sensor_flags, firmware_version, ip_address, rssi, boot_count')
    .eq('device_id', deviceId)
    .maybeSingle()
    .then(({ data }) => { if (data) applyPresenceRow(data); });

  supabaseClient
    .from('telemetry_data')
    .select('*')
    .eq('device_id', deviceId)
    .order('created_at', { ascending: false })
    .limit(1)
    .maybeSingle()
    .then(({ data }) => { if (data) applyTelemetryRow(data); });
}

function subscribeToDeviceRealtime(deviceId) {
  // Remove old channels if switching devices
  if (activeRealtimeChannel) {
    supabaseClient.removeChannel(activeRealtimeChannel);
    activeRealtimeChannel = null;
  }
  if (activeStatusChannel) {
    supabaseClient.removeChannel(activeStatusChannel);
    activeStatusChannel = null;
  }

  // Reset presence — we don't know this device's live state until either
  // the one-shot fetch below returns, or a heartbeat event arrives.
  state.presence = {
    lastSeenMs: null, sensorsOk: false, sensorFlags: {},
    firmwareVersion: null, ipAddress: null, rssi: null, bootCount: null
  };
  updateTelemetryUI();
  updateHeaderStatusPill();

  // Initial load + polling fallback, both below.
  refreshDeviceData(deviceId);

  // Subscribe to new rows in telemetry_data for this device
  activeRealtimeChannel = supabaseClient
    .channel(`telemetry-${deviceId}`)
    .on(
      'postgres_changes',
      {
        event: 'INSERT',
        schema: 'public',
        table: 'telemetry_data',
        filter: `device_id=eq.${deviceId}`
      },
      (payload) => applyTelemetryRow(payload.new)
    )
    .subscribe();

  // Subscribe to device_status heartbeat updates — this, not the telemetry
  // channel, is what proves the ESP32 itself is alive and reachable.
  activeStatusChannel = supabaseClient
    .channel(`status-${deviceId}`)
    .on(
      'postgres_changes',
      { event: '*', schema: 'public', table: 'device_status', filter: `device_id=eq.${deviceId}` },
      (payload) => applyPresenceRow(payload.new)
    )
    .subscribe();
}

// Apply a device_status row (from the one-shot fetch or a Realtime event)
// to presence state, then re-render everything that depends on it.
function applyPresenceRow(row) {
  if (!row) return;
  state.presence.lastSeenMs  = row.last_seen_at ? new Date(row.last_seen_at).getTime() : Date.now();
  state.presence.sensorsOk   = !!row.sensors_ok;
  state.presence.sensorFlags = row.sensor_flags || {};
  // Board identity/diagnostics — only ever arrive on the heartbeat, never on
  // telemetry, so card 8 depends on device_status being reachable.
  if (row.firmware_version !== undefined) state.presence.firmwareVersion = row.firmware_version;
  if (row.ip_address !== undefined)       state.presence.ipAddress       = row.ip_address;
  if (row.rssi !== undefined)             state.presence.rssi            = row.rssi;
  if (row.boot_count !== undefined)       state.presence.bootCount       = row.boot_count;
  updateTelemetryUI();
  updateHeaderStatusPill();
}

// Card 8 ("ESP32 Telemetry Status"). Driven by the heartbeat, so it is updated
// in EVERY connection state — including OFFLINE, where the last known RSSI and
// firmware are still worth showing, greyed out.
function updateNodeStatusCard() {
  const statusEl = document.getElementById('nodeStatusText');
  const powerEl  = document.getElementById('nodePowerSignalText');
  const bootEl   = document.getElementById('nodeBootIpText');
  const fwEl     = document.getElementById('nodeFirmwareText');
  if (!statusEl) return;

  const cs = connectionState();
  const p  = state.presence;

  const LABELS = {
    NO_DEVICE:         ['Status: NO NODE',           'var(--text-muted)'],
    OFFLINE:           ['Status: OFFLINE',           'var(--text-muted)'],
    ONLINE_NO_SENSORS: ['Status: ONLINE — NO SENSORS', 'var(--green-primary)'],
    LIVE:              ['Status: LIVE',              'var(--green-primary)']
  };
  const [label, color] = LABELS[cs];
  statusEl.textContent = label;
  statusEl.style.color = color;

  const live = (cs === 'LIVE' || cs === 'ONLINE_NO_SENSORS');
  const dash = (v, suffix = '') => (v === null || v === undefined ? '--' : `${v}${suffix}`);

  // RSSI comes from the heartbeat; battery_pct rides on telemetry rows.
  const rssi = live ? dash(p.rssi, ' dBm') : '-- dBm';
  const batt = live && state.telemetry.hasData
    ? `${Math.round(state.telemetry.battery)}%`
    : '--';

  if (powerEl) powerEl.textContent = `Battery: ${batt} • RSSI: ${rssi}`;
  if (bootEl)  bootEl.textContent  = `Boot: ${dash(p.bootCount)} • IP: ${dash(p.ipAddress)}`;
  if (fwEl)    fwEl.textContent    = `Firmware ${p.firmwareVersion ? 'v' + p.firmwareVersion : '--'}`;
}

// Drives the header status-pill text/color from connectionState().
function updateHeaderStatusPill() {
  const pill = document.getElementById('headerStatusPill');
  const dot  = document.getElementById('headerPulseDot');
  const text = document.getElementById('wsStatusText');
  if (!pill || !dot || !text) return;

  const currentDev = state.devices[state.activeDeviceIndex];
  const cs = connectionState();

  pill.classList.remove('offline', 'nosensor');
  dot.classList.remove('offline');

  if (cs === 'NO_DEVICE') {
    text.textContent = 'No Node Connected';
    pill.classList.add('offline');
    dot.classList.add('offline');
    return;
  }

  const label = currentDev ? `${currentDev.name} (${currentDev.id})` : 'Node';

  if (cs === 'OFFLINE') {
    text.textContent = `${label} — OFFLINE`;
    pill.classList.add('offline');
    dot.classList.add('offline');
  } else if (cs === 'ONLINE_NO_SENSORS') {
    text.textContent = `${label} — ONLINE (no sensor data)`;
    pill.classList.add('nosensor');
  } else {
    text.textContent = `${label} — LIVE`;
  }
}

// Render Bound Devices List (Page 1)
function renderBoundDevices() {
  const container = document.getElementById('boundDevicesList');
  const slotsBadge = document.getElementById('slotsUsedBadge');
  const limitBox = document.getElementById('limitWarningBox');
  
  if (slotsBadge) slotsBadge.textContent = `${state.devices.length} / 4 Nodes Active`;

  if (limitBox) {
    limitBox.style.display = state.devices.length >= 4 ? 'flex' : 'none';
  }

  if (!container) return;

  if (state.devices.length === 0) {
    container.innerHTML = `<div style="text-align: center; padding: 1.5rem; color: var(--text-muted);">No active hardware nodes bound to account. Use the form on the left to add a device.</div>`;
    return;
  }

  container.innerHTML = state.devices.map((device, idx) => `
    <div class="device-item-row">
      <div class="device-info-meta">
        <div class="device-icon-sq">
          <span class="material-symbols-outlined" style="font-size: 20px;">developer_board</span>
        </div>
        <div>
          <h4 style="font-size: 13px; font-weight: 600; color: var(--text-primary); display: flex; align-items: center; gap: 0.4rem;">
            ${device.name} (${device.id})
            <span class="pulse-dot${idx === state.activeDeviceIndex && connectionState() === 'OFFLINE' ? ' offline' : ''}"
              style="${idx === state.activeDeviceIndex ? '' : 'background-color: var(--text-muted);'}"
              title="${idx === state.activeDeviceIndex ? connectionState() : 'Select to see live status'}"></span>
          </h4>
          <p style="font-size: 11px; color: var(--text-secondary); font-family: var(--font-mono); margin-top: 0.15rem;">${device.sector}</p>
        </div>
      </div>
      <div style="display: flex; align-items: center; gap: 0.85rem; flex-wrap: wrap;">
        <span style="font-size: 11px; font-family: var(--font-mono); color: var(--text-secondary); display: flex; align-items: center; gap: 2px;">
          <span class="material-symbols-outlined" style="font-size: 14px;">battery_full</span> ${device.battery}%
        </span>
        <span style="font-size: 11px; font-family: var(--font-mono); color: var(--green-primary); display: flex; align-items: center; gap: 2px;">
          <span class="material-symbols-outlined" style="font-size: 14px;">signal_cellular_alt</span> ${device.signal}
        </span>
        <button class="btn-secondary" style="color: var(--rose-danger); border-color: rgba(248,81,73,0.3);" onclick="promptUnbindDevice(${idx})">Unbind</button>
      </div>
    </div>
  `).join('');
}


function updateHeaderDeviceSelector() {
  const select = document.getElementById('headerDeviceSelect');
  if (!select) return;

  if (state.devices.length === 0) {
    select.innerHTML = '<option value="">No Node Connected</option>';
    updateHeaderStatusPill();
    return;
  }

  select.innerHTML = state.devices.map((d, i) => `
    <option value="${i}">${d.name} (${d.id})</option>
  `).join('');
  select.value = state.activeDeviceIndex;

  select.onchange = (e) => {
    state.activeDeviceIndex = parseInt(e.target.value);
    const selectedDev = state.devices[state.activeDeviceIndex];
    if (selectedDev) {
      showToast(`Switched telemetry node to: ${selectedDev.name}`, 'info');
      subscribeToDeviceRealtime(selectedDev.id);
      loadTimers();
      renderBoundDevices();
    }
  };
}

async function handleBindDevice() {
  if (state.devices.length >= 4) {
    showToast('Maximum limit of 4 devices reached per account. Unbind a node first.', 'error');
    document.getElementById('limitWarningBox').style.display = 'flex';
    return;
  }

  const id     = document.getElementById('inputDeviceId').value.trim();
  const secret = document.getElementById('inputDevicePairingSecret').value.trim();
  const name   = document.getElementById('inputDeviceName').value.trim() || `Node ${state.devices.length + 1}`;

  if (!id) {
    showToast('Please enter the Hardware Serial ID (e.g. AGS-0001)', 'error');
    return;
  }
  if (!secret) {
    showToast('Please enter the Pairing Secret printed on your device', 'error');
    return;
  }

  const btn = document.getElementById('btnBindDevice');
  if (btn) { btn.disabled = true; btn.innerText = 'Pairing Node...'; }

  // Plain-language messages for each failure the claim_device() RPC can return.
  // See documents/supabase_presence_and_pairing.sql for the gate each code maps to.
  const CLAIM_ERROR_MESSAGES = {
    NOT_LOGGED_IN:     'Your session expired. Please log in again.',
    UNKNOWN_DEVICE:    'No AgriSense board with that serial and secret exists. Check the label on your ESP32.',
    DEVICE_OFFLINE:    'Board recognised, but it hasn\'t reported in. Power on the ESP32, wait 15 seconds, then retry.',
    CLAIMED_BY_OTHER:  'That board is already paired to another account.',
    ALREADY_YOURS:     'You\'ve already paired this board.'
  };

  try {
    // claim_device() is the ONLY way into the devices table — it verifies the
    // serial+secret against device_registry (real hardware) AND requires a
    // fresh heartbeat in device_status (the board must be powered on right now).
    const { data, error } = await supabaseClient.rpc('claim_device', {
      p_device_id: id.toUpperCase(),
      p_secret: secret,
      p_name: name,
      p_sector: name
    });

    if (error) throw new Error(error.message || 'Failed to bind device.');

    if (!data || !data.ok) {
      const code = data ? data.code : 'UNKNOWN_DEVICE';
      throw new Error(CLAIM_ERROR_MESSAGES[code] || `Pairing failed (${code}).`);
    }

    showToast(`Node ${id.toUpperCase()} successfully paired!`, 'success');
    document.getElementById('inputDeviceId').value = '';
    document.getElementById('inputDevicePairingSecret').value = '';
    document.getElementById('inputDeviceName').value = '';
    await fetchUserDevices();
  } catch (err) {
    showToast(err.message, 'error');
    console.error('Bind error:', err);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span class="material-symbols-outlined">sensors</span> Initialize Node Pairing';
    }
  }
}

function promptUnbindDevice(index) {
  const device = state.devices[index];
  document.getElementById('modalTitle').textContent = 'Unbind Hardware Node';
  document.getElementById('modalBody').textContent = `Are you sure you want to unbind ${device.name} (${device.id})?`;

  state.pendingModalAction = async () => {
    try {
      // Delete device directly from Supabase — RLS enforces user owns this device
      const { error } = await supabaseClient
        .from('devices')
        .delete()
        .eq('device_id', device.id)
        .eq('user_id', state.currentUser.id);

      if (error) throw new Error(error.message);
      showToast(`Node ${device.id} unbound`, 'info');
      await fetchUserDevices();
    } catch (err) {
      showToast(err.message, 'error');
    } finally {
      closeModal();
    }
  };

  document.getElementById('modalBackdrop').classList.add('active');
}

async function handleControlPumpToggle(checked) {
  state.pump.state = checked ? 'RUNNING' : 'OFF';
  evaluatePumpDecisionEngine();

  const currentDev = state.devices[state.activeDeviceIndex];
  const cmdStr = checked ? 'PUMP_ON' : 'PUMP_OFF';

  if (currentDev) {
    try {
      // Insert command directly into Supabase — ESP32 polls and picks it up
      const { error } = await supabaseClient
        .from('device_commands')
        .insert({
          device_id: currentDev.id,
          command: cmdStr,
          executed: false
        });
      if (error) throw new Error(error.message);
      showToast(`Manual command sent: ${cmdStr}`, 'success');
    } catch (err) {
      showToast('Failed to send command: ' + err.message, 'error');
    }
  }

  // Manual switch always clears automation mode locally
  state.pump.automationMode = 'NONE';
  updateAutomationModeUI('NONE');

  const newLog = {
    time: new Date().toLocaleString(),
    unit: currentDev ? currentDev.name : 'Relay Pump 1',
    trigger: 'Manual Override',
    action: checked ? 'OFF → RUNNING' : 'RUNNING → OFF',
    moisture: `${Math.round(state.telemetry.soilMoisture)}%`,
    duration: checked ? 'Active' : 'Manual Stop'
  };
  state.auditLog.unshift(newLog);
  renderAuditLog();
}

function closeModal() {
  document.getElementById('modalBackdrop').classList.remove('active');
  state.pendingModalAction = null;
}

function confirmModalAction() {
  if (state.pendingModalAction) state.pendingModalAction();
}

// UI Telemetry Update Functions
// Display rules:
//   OFFLINE / NO_DEVICE -> everything 00, grey. No packets arriving at all.
//   otherwise           -> EACH sensor renders from its own sensor_flags
//                          entry, never from the global sensors_ok. A dead
//                          DHT does not blank the soil gauge or the rain
//                          badge, and vice versa. Only the warning banner
//                          and the status pill still use sensors_ok.
function updateTelemetryUI() {
  const offlineBanner = document.getElementById('offlineBanner');
  const noDataBanner   = document.getElementById('noSensorDataBanner');

  const soilValText         = document.getElementById('soilValText');
  const tempValText         = document.getElementById('tempValText');
  const humidityValText     = document.getElementById('humidityValText');
  const targetThresholdText = document.getElementById('targetThresholdText');
  const gaugeVal             = document.getElementById('soilGaugeVal');
  const soilStateText        = document.getElementById('soilStateText');
  const rainBadge             = document.getElementById('rainStateBadge');

  // Threshold displays reflect user-configured settings, not live sensor
  // data, so they stay populated regardless of connection state.
  document.getElementById('ctrlStartVal').textContent = `${state.telemetry.targetThreshold}%`;
  document.getElementById('ctrlStopVal').textContent = `${state.telemetry.stopThreshold}%`;
  document.getElementById('ctrlRuntimeVal').textContent = `${state.telemetry.maxRuntime} mins`;

  const cs = connectionState();

  // Card 8 is heartbeat-driven and must refresh in every state, so it is
  // updated here — before the early returns the sensor cards take below.
  updateNodeStatusCard();

  function showZeroed(colorClass, label) {
    [soilValText, tempValText].forEach(el => {
      if (!el) return;
      el.classList.remove('val-offline', 'val-nosensor');
      el.classList.add(colorClass);
      el.textContent = '00';
    });
    if (humidityValText) {
      humidityValText.classList.remove('val-offline', 'val-nosensor');
      humidityValText.classList.add(colorClass);
      humidityValText.textContent = '00%';
    }
    if (targetThresholdText) targetThresholdText.textContent = `${state.telemetry.targetThreshold}%`;
    if (gaugeVal) gaugeVal.setAttribute('stroke-dasharray', '0, 100');
    if (soilStateText) {
      soilStateText.textContent = label;
      soilStateText.style.color = colorClass === 'val-offline' ? 'var(--text-muted)' : 'var(--green-primary)';
    }
  }

  if (cs === 'NO_DEVICE' || cs === 'OFFLINE') {
    showZeroed('val-offline', cs === 'NO_DEVICE' ? 'No Device' : 'Offline');
    if (rainBadge) {
      rainBadge.textContent = 'SENSORS OFFLINE';
      rainBadge.style.background = 'rgba(110,118,129,0.15)';
      rainBadge.style.color = 'var(--text-muted)';
      rainBadge.style.border = '1px solid rgba(110,118,129,0.3)';
    }
    if (offlineBanner) offlineBanner.style.display = (cs === 'OFFLINE') ? 'flex' : 'none';
    if (noDataBanner) noDataBanner.style.display = 'none';
    return;
  }

  // ── ONLINE: render each sensor from ITS OWN health flag ────────────────────
  // Deliberately no global gate here. sensors_ok is only (dht && soil), so a
  // dead DHT used to blank the soil gauge and the rain badge as well. Each
  // sensor now stands alone: a working one always shows its real reading, a
  // failed one shows 00 next to a FAIL in the Node Health card.
  if (offlineBanner) offlineBanner.style.display = 'none';
  if (noDataBanner) noDataBanner.style.display = (cs === 'ONLINE_NO_SENSORS') ? 'flex' : 'none';

  const flags  = state.presence.sensorFlags || {};
  const dhtOk  = flags.dht  !== false;   // undefined = older firmware, assume OK
  const soilOk = flags.soil !== false;

  // Name the actual failing sensor rather than blaming both.
  const noSensorDetail = document.getElementById('noSensorDetail');
  if (noSensorDetail) {
    const failed = [
      !dhtOk && 'DHT11 (temperature/humidity, GPIO 4)',
      !soilOk && 'soil moisture probe (GPIO 34)',
    ].filter(Boolean).join(' and ');
    noSensorDetail.textContent =
      `— ${failed} not reporting. Check the wiring; every other sensor keeps updating normally.`;
  }

  [soilValText, tempValText, humidityValText].forEach(el => {
    if (el) el.classList.remove('val-offline', 'val-nosensor');
  });

  // Soil
  const moisture = soilOk ? Math.round(state.telemetry.soilMoisture) : 0;
  if (soilValText) {
    soilValText.textContent = soilOk ? moisture : '00';
    if (!soilOk) soilValText.classList.add('val-nosensor');
  }
  if (gaugeVal) gaugeVal.setAttribute('stroke-dasharray', `${moisture}, 100`);
  if (soilStateText) {
    if (!soilOk) {
      soilStateText.textContent = 'Probe Not Detected';
      soilStateText.style.color = 'var(--amber-warning)';
    } else if (moisture < state.telemetry.targetThreshold - 15) {
      soilStateText.textContent = 'Dry';
      soilStateText.style.color = 'var(--amber-warning)';
    } else {
      soilStateText.textContent = 'Optimal';
      soilStateText.style.color = 'var(--green-primary)';
    }
  }

  // Temperature + humidity (both come from the DHT, so they share a flag)
  let tempVal = state.telemetry.temperature;
  if (state.telemetry.tempUnit === 'F') {
    tempVal = (tempVal * 9/5) + 32;
  }
  if (tempValText) {
    tempValText.textContent = dhtOk ? tempVal.toFixed(1) : '00';
    if (!dhtOk) tempValText.classList.add('val-nosensor');
  }
  const tempUnitText = document.getElementById('tempUnitText');
  if (tempUnitText) tempUnitText.textContent = `°${state.telemetry.tempUnit}`;
  if (humidityValText) {
    humidityValText.textContent = dhtOk ? `${Math.round(state.telemetry.humidity)}%` : '00%';
    if (!dhtOk) humidityValText.classList.add('val-nosensor');
  }
  if (targetThresholdText) targetThresholdText.textContent = `${state.telemetry.targetThreshold}%`;

  // Rain — never gated, it has no health check to fail (see setRainBadge)
  setRainBadge(state.telemetry.rainDetected);
}

// The rain sensor is reported independently of sensors_ok: the firmware sets
// sensor_flags.rain = true unconditionally because a digital rain sensor
// cannot be health-checked (see AgriSense_ESP32.ino sendHeartbeat). So a DHT
// or soil failure must NOT mask a working rain reading — this is called from
// the ONLINE_NO_SENSORS path too, not just the fully-live one.
function setRainBadge(detected) {
  const rainBadge = document.getElementById('rainStateBadge');
  if (!rainBadge) return;
  if (detected) {
    rainBadge.textContent = 'RAIN DETECTED';
    rainBadge.style.background = 'rgba(88, 166, 255, 0.15)';
    rainBadge.style.color = 'var(--blue-accent)';
    rainBadge.style.border = '1px solid rgba(88,166,255,0.4)';
  } else {
    rainBadge.textContent = 'DRY / CLEAR';
    rainBadge.style.background = 'rgba(62, 207, 142, 0.12)';
    rainBadge.style.color = 'var(--green-primary)';
    rainBadge.style.border = '1px solid rgba(62,207,142,0.3)';
  }
}

function toggleTempUnit() {
  state.telemetry.tempUnit = state.telemetry.tempUnit === 'C' ? 'F' : 'C';
  document.getElementById('btnTempUnit').textContent = `Unit: °${state.telemetry.tempUnit}`;
  updateTelemetryUI();
}

// Pump & Controls Engine
function evaluatePumpDecisionEngine() {
  const badge = document.getElementById('pumpStatusBadge');
  const ctrlBadge = document.getElementById('controlPumpStatusBadge');
  const switchElem = document.getElementById('controlPumpSwitch');
  
  if (state.pump.state === 'RUNNING') {
    if (badge) { badge.textContent = 'RUNNING'; badge.className = 'status-badge-flat running'; }
    if (ctrlBadge) { ctrlBadge.textContent = 'PUMP RUNNING'; ctrlBadge.className = 'status-badge-flat running'; }
    if (switchElem) switchElem.checked = true;
  } else {
    if (badge) { badge.textContent = 'OFF'; badge.className = 'status-badge-flat off'; }
    if (ctrlBadge) { ctrlBadge.textContent = 'PUMP OFF'; ctrlBadge.className = 'status-badge-flat off'; }
    if (switchElem) switchElem.checked = false;
  }
}

// ── Automation Mode Functions ─────────────────────────────────────────────
async function setAutomationMode(mode) {
  const currentDev = state.devices[state.activeDeviceIndex];
  if (!currentDev) {
    showToast('No device connected. Bind a node first.', 'error');
    return;
  }

  // Optimistically show the selected mode, but revert below if the backend
  // (FastAPI, which runs the actual decision engine) can't be reached —
  // showing "MOISTURE AUTO" while nothing is evaluating it would be the same
  // silent-failure problem as the fake device pairing.
  state.pump.automationMode = mode;
  updateAutomationModeUI(mode);

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/automation/mode`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${state.currentUser.token}`
      },
      body: JSON.stringify({
        device_id: currentDev.id,
        mode: mode,
        start_threshold: state.telemetry.targetThreshold,
        stop_threshold: state.telemetry.stopThreshold,
        max_runtime_mins: state.telemetry.maxRuntime
      })
    });

    if (!resp.ok) throw new Error(`Backend responded ${resp.status}`);

    const modeLabels = { NONE: 'Manual Only', MOISTURE: 'Soil Moisture Auto', TIMER: 'Timer Schedule' };
    showToast(`Automation mode set: ${modeLabels[mode] || mode}`, 'success');

    // Add to audit log
    const newLog = {
      time: new Date().toLocaleString(),
      unit: currentDev.name,
      trigger: 'Mode Change',
      action: `Mode → ${modeLabels[mode] || mode}`,
      moisture: `${Math.round(state.telemetry.soilMoisture)}%`,
      duration: '--'
    };
    state.auditLog.unshift(newLog);
    renderAuditLog();
  } catch (err) {
    console.error('Automation mode update failed:', err);
    state.pump.automationMode = 'NONE';
    updateAutomationModeUI('NONE');
    if (mode !== 'NONE') {
      showToast('Automation server offline — manual control still works.', 'error');
    }
  }
}

function updateAutomationModeUI(mode) {
  // Update radio button selections
  document.querySelectorAll('input[name="automationMode"]').forEach(radio => {
    radio.checked = (radio.value === mode);
  });

  // Update card highlight
  const optionMap = { NONE: 'modeOptionNone', MOISTURE: 'modeOptionMoisture', TIMER: 'modeOptionTimer' };
  Object.values(optionMap).forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('active');
  });
  const activeId = optionMap[mode];
  if (activeId) {
    const activeEl = document.getElementById(activeId);
    if (activeEl) activeEl.classList.add('active');
  }

  // Update status badge
  const badge = document.getElementById('automationModeBadge');
  if (badge) {
    const badgeMap = {
      NONE:     { text: 'MANUAL ONLY',    cls: 'off' },
      MOISTURE: { text: 'MOISTURE AUTO',  cls: 'running' },
      TIMER:    { text: 'TIMER ACTIVE',   cls: 'running' }
    };
    const b = badgeMap[mode] || badgeMap.NONE;
    badge.textContent = b.text;
    badge.className = `status-badge-flat ${b.cls}`;
  }
}

async function handleForceStop() {
  const currentDev = state.devices[state.activeDeviceIndex];
  if (!currentDev) {
    showToast('No device connected. Bind a node first.', 'error');
    return;
  }

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/command`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${state.currentUser.token}`
      },
      body: JSON.stringify({ device_id: currentDev.id, command: 'PUMP_OFF' })
    });
    if (!resp.ok) throw new Error(`Backend responded ${resp.status}`);

    state.pump.state = 'OFF';
    state.pump.automationMode = 'NONE';
    evaluatePumpDecisionEngine();
    updateAutomationModeUI('NONE');
    showToast('Force Stop Executed: Emergency shutdown sent to device', 'error');
  } catch (err) {
    console.error('Force Stop failed to reach backend:', err);
    showToast('Force Stop FAILED — automation server unreachable. Use the Manual Override switch instead.', 'error');
  }
}

function updateStartThreshold(val) {
  state.telemetry.targetThreshold = parseInt(val);
  updateTelemetryUI();
}

function updateStopThreshold(val) {
  state.telemetry.stopThreshold = parseInt(val);
  updateTelemetryUI();
}

function updateMaxRuntime(val) {
  state.telemetry.maxRuntime = parseInt(val);
  updateTelemetryUI();
}

// ── Live Camera (ESP32-CAM relay via backend/main.py) ─────────────────────────
async function openLiveCamera() {
  const currentDev = state.devices[state.activeDeviceIndex];
  if (!currentDev) {
    showToast('No device connected. Bind a node first.', 'error');
    return;
  }

  const backdrop = document.getElementById('cameraBackdrop');
  const viewport = document.getElementById('cameraViewport');
  viewport.innerHTML = '<p id="cameraStatus" style="font-size: 13px; color: var(--text-secondary);">Connecting…</p>';
  backdrop.classList.add('active');

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/camera/${currentDev.id}/token`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${state.currentUser.token}` }
    });
    if (!resp.ok) throw new Error(`Backend responded ${resp.status}`);
    const { token } = await resp.json();

    const img = document.createElement('img');
    img.style.cssText = 'max-width: 100%; max-height: 60vh; border-radius: 6px;';
    img.src = `${BACKEND_BASE}/api/camera/stream?t=${encodeURIComponent(token)}`;
    img.alt = 'Live farm camera feed';
    img.onerror = () => {
      viewport.innerHTML = '<p style="font-size: 13px; color: var(--text-secondary);">No camera feed available. Is the ESP32-CAM powered on?</p>';
    };
    viewport.innerHTML = '';
    viewport.appendChild(img);
  } catch (err) {
    viewport.innerHTML = `<p style="font-size: 13px; color: var(--rose-danger);">Could not start the camera feed: ${err.message}</p>`;
  }
}

function closeLiveCamera() {
  const viewport = document.getElementById('cameraViewport');
  const img = viewport.querySelector('img');
  if (img) img.src = '';   // actually tears down the stream connection, not just hides it
  document.getElementById('cameraBackdrop').classList.remove('active');
}

function triggerSimulatedDrySpell() {
  state.telemetry.soilMoisture = 14.5;
  updateTelemetryUI();
  evaluatePumpDecisionEngine();
  showToast('Simulated Dry Spell Event Triggered! Soil moisture dropped to 14.5%', 'warning');
}

// ── Timer Schedule Manager (Backend-Connected) ────────────────────────────────
// Day abbreviations match backend: Mo Tu We Th Fr Sa Su
const ALL_DAYS = ['Mo','Tu','We','Th','Fr','Sa','Su'];
const DAY_LABELS = { Mo:'M', Tu:'T', We:'W', Th:'T', Fr:'F', Sa:'S', Su:'S' };

function renderTimers() {
  const container = document.getElementById('timersList');
  if (!container) return;

  if (state.timers.length === 0) {
    container.innerHTML = `<div style="font-size: 12px; color: var(--text-muted); padding: 0.5rem 0;">No active scheduled timers configured.</div>`;
    return;
  }

  container.innerHTML = state.timers.map(timer => `
    <div class="timer-schedule-item">
      <div>
        <div style="font-size: 14px; font-weight: 700; font-family: var(--font-mono); color: var(--text-primary); display: flex; align-items: center; gap: 0.4rem;">
          <span class="material-symbols-outlined" style="font-size: 16px; color: var(--green-primary);">schedule</span>
          ${timer.time} <span style="font-size: 11px; color: var(--text-secondary); font-weight: 400;">(${timer.duration} Mins)</span>
        </div>
        <div style="display: flex; gap: 0.2rem; margin-top: 0.35rem;">
          ${ALL_DAYS.map(d => `
            <span class="day-badge ${(timer.days || []).includes(d) ? 'active' : ''}" title="${d}">${DAY_LABELS[d]}</span>
          `).join('')}
        </div>
      </div>

      <div style="display: flex; align-items: center; gap: 0.75rem;">
        <label class="toggle-switch">
          <input type="checkbox" ${timer.active ? 'checked' : ''} onchange="toggleTimerActive(${timer.id}, this.checked)">
          <span class="toggle-slider"></span>
        </label>
        <button class="btn-secondary" style="color: var(--rose-danger); padding: 0.2rem 0.5rem;" onclick="deleteTimer(${timer.id})">
          <span class="material-symbols-outlined" style="font-size: 16px;">delete</span>
        </button>
      </div>
    </div>
  `).join('');
}

async function loadTimers() {
  const currentDev = state.devices[state.activeDeviceIndex];
  if (!currentDev || !state.currentUser.token) return;

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/timers/${currentDev.id}`, {
      headers: { 'Authorization': `Bearer ${state.currentUser.token}` }
    });
    if (!resp.ok) return;
    const data = await resp.json();

    state.timers = (data.timers || []).map(t => ({
      id: t.id,
      time: t.start_time,
      duration: t.duration_mins,
      days: t.active_days || [],
      active: t.is_active
    }));
    renderTimers();
  } catch (err) {
    console.error('Failed to load timers:', err);
  }
}

async function handleAddTimer() {
  const currentDev = state.devices[state.activeDeviceIndex];
  if (!currentDev) {
    showToast('No device connected. Bind a node first.', 'error');
    return;
  }

  const timeInput = document.getElementById('timerTimeInput').value;
  if (!timeInput) {
    showToast('Please select a time for the timer.', 'error');
    return;
  }
  const durationInput = parseInt(document.getElementById('timerDurationInput').value) || 15;

  // Build 24h time string for backend
  const start_time_24h = timeInput; // input[type="time"] already gives HH:MM

  // Format for display (12h)
  const [h, m] = timeInput.split(':');
  const hour = parseInt(h);
  const ampm = hour >= 12 ? 'PM' : 'AM';
  const hour12 = hour % 12 || 12;
  const formattedTime = `${hour12 < 10 ? '0' + hour12 : hour12}:${m} ${ampm}`;

  // Default: weekdays Mo-Fr
  const activeDays = ['Mo','Tu','We','Th','Fr'];

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/timers`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_id: currentDev.id,
        start_time: start_time_24h,
        duration_mins: durationInput,
        active_days: activeDays,
        user_token: state.currentUser.token
      })
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Failed to add timer');
    }

    showToast(`Timer added: Daily ${formattedTime} (${durationInput} mins)`, 'success');
    await loadTimers();  // Reload from backend to get server-assigned ID
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function toggleTimerActive(id, isChecked) {
  const timer = state.timers.find(t => t.id === id);
  if (!timer) return;

  const previous = timer.active;
  timer.active = isChecked;  // optimistic

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/timers/${id}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${state.currentUser.token}`
      },
      body: JSON.stringify({ is_active: isChecked })
    });
    if (!resp.ok) throw new Error(`Backend responded ${resp.status}`);
    showToast(`Timer ${timer.time} ${timer.active ? 'Enabled' : 'Disabled'}`, 'info');
  } catch (err) {
    console.error('Failed to toggle timer:', err);
    timer.active = previous;  // revert — the change did not actually persist
    renderTimers();
    showToast('Automation server unreachable — timer state not saved.', 'error');
  }
}

async function deleteTimer(id) {
  try {
    const resp = await fetch(`${BACKEND_BASE}/api/timers/${id}`, {
      method: 'DELETE',
      headers: { 'Authorization': `Bearer ${state.currentUser.token}` }
    });
    if (!resp.ok) throw new Error(`Backend responded ${resp.status}`);

    state.timers = state.timers.filter(t => t.id !== id);
    renderTimers();
    showToast('Scheduled timer deleted', 'info');
  } catch (err) {
    console.error('Failed to delete timer:', err);
    showToast('Automation server unreachable — timer not deleted.', 'error');
  }
}

function renderAuditLog() {
  const body = document.getElementById('auditLogTableBody');
  if (!body) return;

  body.innerHTML = state.auditLog.map(log => `
    <tr>
      <td>${log.time}</td>
      <td>${log.unit}</td>
      <td><span style="color: var(--green-primary); font-weight: 500;">${log.trigger}</span></td>
      <td>${log.action}</td>
      <td>${log.moisture}</td>
      <td>${log.duration}</td>
    </tr>
  `).join('');
}

// -------------------------------------------------------------
// Interactive Split Analytics Engine (Rolling 4-Point Buffer)
// -------------------------------------------------------------

function toggleSensorSeries(key) {
  if (!state.analytics.series[key]) return;
  state.analytics.series[key].active = !state.analytics.series[key].active;

  const btnId = `toggle${key.charAt(0).toUpperCase() + key.slice(1)}Btn`;
  const btn = document.getElementById(btnId);
  if (btn) btn.classList.toggle('active', state.analytics.series[key].active);

  renderCanvasChart();
}

// 0: 2h ago (index 3 in buffer)
// 1: 4h ago (index 2 in buffer)
// 2: 6h ago (index 1 in buffer)
// 3: 8h ago (index 0 in buffer)
function selectTimeInterval(offsetIndex) {
  // Update Buttons
  [0, 1, 2, 3].forEach(idx => {
    const btn = document.getElementById(`btnInt${idx}`);
    if(btn) btn.classList.toggle('active', idx === offsetIndex);
  });

  const chronologicalIndex = 3 - offsetIndex;
  state.analytics.selectedIndex = chronologicalIndex;

  const buf = state.analytics.buffer;
  
  const html = `
    <div class="numerical-sensor-row">
      <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
        <span class="sensor-dot" style="background: var(--green-primary);"></span> Soil Moisture
      </div>
      <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.soil[chronologicalIndex]}%</span>
    </div>
    
    <div class="numerical-sensor-row">
      <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
        <span class="sensor-dot" style="background: var(--amber-warning);"></span> Temperature
      </div>
      <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.temp[chronologicalIndex]}°C</span>
    </div>

    <div class="numerical-sensor-row">
      <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
        <span class="sensor-dot" style="background: var(--blue-accent);"></span> Humidity
      </div>
      <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.humid[chronologicalIndex]}% RH</span>
    </div>

    <div class="numerical-sensor-row">
      <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
        <span class="sensor-dot" style="background: rgba(210,153,34,0.6);"></span> Rain Accumulation
      </div>
      <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.rain[chronologicalIndex]} mm</span>
    </div>

    <div class="numerical-sensor-row">
      <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
        <span class="sensor-dot" style="background: var(--purple-accent);"></span> Solar PAR
      </div>
      <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.solar[chronologicalIndex]} W/m²</span>
    </div>

    <div class="numerical-sensor-row">
      <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
        <span class="sensor-dot" style="background: #fff;"></span> NPK Nutrients
      </div>
      <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.npk[chronologicalIndex]}</span>
    </div>
  `;

  const container = document.getElementById('numericalSensorsContainer');
  if (container) container.innerHTML = html;

  renderCanvasChart();
}

function initCanvasEvents() {
  const canvas = document.getElementById('trendCanvas');
  const tooltip = document.getElementById('chartTooltip');
  if (!canvas || !tooltip) return;

  canvas.addEventListener('mousemove', (e) => {
    const rect = canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const paddingLeft = 45;
    const paddingRight = 20;
    const usableWidth = rect.width - paddingLeft - paddingRight;

    const data = state.analytics.buffer;
    const count = data.labels.length;
    const stepX = usableWidth / (count - 1);

    let closestIdx = Math.round((x - paddingLeft) / stepX);
    closestIdx = Math.max(0, Math.min(count - 1, closestIdx));

    state.analytics.selectedIndex = closestIdx;
    
    // Sync the right panel
    const offsetIndex = 3 - closestIdx;
    [0, 1, 2, 3].forEach(idx => {
      const btn = document.getElementById(`btnInt${idx}`);
      if(btn) btn.classList.toggle('active', idx === offsetIndex);
    });
    
    // We can call selectTimeInterval but we don't want to re-render chart from within mousemove repeatedly
    // To be efficient, we manually update the HTML for numerical breakdown:
    const buf = state.analytics.buffer;
    const container = document.getElementById('numericalSensorsContainer');
    if(container) {
      container.innerHTML = `
        <div class="numerical-sensor-row">
          <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
            <span class="sensor-dot" style="background: var(--green-primary);"></span> Soil Moisture
          </div>
          <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.soil[closestIdx]}%</span>
        </div>
        <div class="numerical-sensor-row">
          <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
            <span class="sensor-dot" style="background: var(--amber-warning);"></span> Temperature
          </div>
          <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.temp[closestIdx]}°C</span>
        </div>
        <div class="numerical-sensor-row">
          <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
            <span class="sensor-dot" style="background: var(--blue-accent);"></span> Humidity
          </div>
          <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.humid[closestIdx]}% RH</span>
        </div>
        <div class="numerical-sensor-row">
          <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
            <span class="sensor-dot" style="background: rgba(210,153,34,0.6);"></span> Rain Accumulation
          </div>
          <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.rain[closestIdx]} mm</span>
        </div>
        <div class="numerical-sensor-row">
          <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
            <span class="sensor-dot" style="background: var(--purple-accent);"></span> Solar PAR
          </div>
          <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.solar[closestIdx]} W/m²</span>
        </div>
        <div class="numerical-sensor-row">
          <div style="display: flex; align-items: center; gap: 0.5rem; color: var(--text-secondary);">
            <span class="sensor-dot" style="background: #fff;"></span> NPK Nutrients
          </div>
          <span style="font-weight: 700; color: var(--text-primary); font-family: var(--font-mono);">${buf.npk[closestIdx]}</span>
        </div>
      `;
    }

    renderCanvasChart();
  });
}

function renderCanvasChart() {
  const canvas = document.getElementById('trendCanvas');
  if (!canvas) return;

  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();

  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;

  const paddingTop = 25;
  const paddingBottom = 35;
  const paddingLeft = 45;
  const paddingRight = 20;

  const plotW = w - paddingLeft - paddingRight;
  const plotH = h - paddingTop - paddingBottom;

  ctx.clearRect(0, 0, w, h);

  const data = state.analytics.buffer;
  const count = data.labels.length;
  const stepX = plotW / (count - 1);

  // Grid Lines & Y-Axis Scale
  ctx.strokeStyle = '#21262d';
  ctx.lineWidth = 1;
  ctx.fillStyle = '#6e7681';
  ctx.font = '10px ui-monospace, SFMono-Regular, "JetBrains Mono"';
  ctx.textAlign = 'right';

  const yTicks = [0, 25, 50, 75, 100];
  yTicks.forEach(tick => {
    const y = paddingTop + plotH - (tick / 100) * plotH;
    ctx.beginPath();
    ctx.moveTo(paddingLeft, y);
    ctx.lineTo(w - paddingRight, y);
    ctx.stroke();
    ctx.fillText(`${tick}%`, paddingLeft - 8, y + 3);
  });

  // X-Axis Timestamps (8h Ago, 6h Ago, etc.)
  ctx.textAlign = 'center';
  data.labels.forEach((label, i) => {
    const x = paddingLeft + i * stepX;
    
    // Highlight active label
    ctx.fillStyle = i === state.analytics.selectedIndex ? '#f0f6fc' : '#6e7681';
    ctx.font = i === state.analytics.selectedIndex 
      ? 'bold 11px ui-monospace, SFMono-Regular, "JetBrains Mono"' 
      : '10px ui-monospace, SFMono-Regular, "JetBrains Mono"';
      
    ctx.fillText(label, x, h - 10);
  });

  // Draw Vertical Guide Line for selected/hovered index
  if (state.analytics.selectedIndex >= 0 && state.analytics.selectedIndex < count) {
    const hoverX = paddingLeft + state.analytics.selectedIndex * stepX;
    ctx.strokeStyle = 'rgba(240, 246, 252, 0.15)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(hoverX, paddingTop);
    ctx.lineTo(hoverX, paddingTop + plotH);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Draw Each Active Series (Smooth Curves)
  Object.keys(state.analytics.series).forEach(key => {
    const s = state.analytics.series[key];
    if (!s.active || !data[key]) return;

    const values = data[key];
    const points = values.map((val, i) => {
      let normalizedVal = val;
      if (key === 'temp') normalizedVal = (val / 50) * 100;      // 0-50 C mapped to 0-100%
      if (key === 'solar') normalizedVal = (val / 1000) * 100;  // 0-1000 W/m2 mapped to 0-100%

      return {
        x: paddingLeft + i * stepX,
        y: paddingTop + plotH - (normalizedVal / 100) * plotH
      };
    });

    // Draw Smooth Stroke Line
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    ctx.moveTo(points[0].x, points[0].y);

    for (let i = 0; i < points.length - 1; i++) {
      const p1 = points[i];
      const p2 = points[i + 1];
      const cpX = (p1.x + p2.x) / 2;
      ctx.bezierCurveTo(cpX, p1.y, cpX, p2.y, p2.x, p2.y);
    }
    ctx.stroke();

    // Draw Data Point Dots
    points.forEach((pt, idx) => {
      const isSelected = (idx === state.analytics.selectedIndex);
      ctx.fillStyle = isSelected ? '#ffffff' : s.color;
      ctx.strokeStyle = '#161b22';
      ctx.lineWidth = 2;

      ctx.beginPath();
      ctx.arc(pt.x, pt.y, isSelected ? 6 : 4, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });
  });
}

// Toast Manager
function showToast(message, type = 'info') {
  const container = document.getElementById('toastContainer');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  let iconName = 'info';
  if (type === 'success') iconName = 'check_circle';
  if (type === 'error') iconName = 'warning';
  if (type === 'warning') iconName = 'report_problem';

  toast.innerHTML = `<span class="material-symbols-outlined" style="font-size: 18px;">${iconName}</span> <span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}
