// ── Supabase & Backend Configuration ─────────────────────────────────────
const SUPABASE_URL = "https://iqmrpwvbmfkhychhditg.supabase.co";
const SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImlxbXJwd3ZibWZraHljaGhkaXRnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODYyNTY5OTEsImV4cCI6MjEwMTgzMjk5MX0.i8wCUSDmc6DI8ZLK6wQeaZDzQqZCEIzkZUrrg2RnefQ";
const BACKEND_BASE = "http://localhost:8000";
const WS_BASE = "ws://localhost:8000";

let supabaseClient = null;
if (window.supabase) {
  supabaseClient = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
}

let activeWebSocket = null;
let currentSession = null;

// Application State
const state = {
  activeView: 'view-connect',
  currentUser: { loggedIn: false, email: null, id: null, token: null },
  devices: [],
  activeDeviceIndex: 0,
  telemetry: {
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
  timers: [],
  auditLog: [],
  pendingModalAction: null
};

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

  window.addEventListener('resize', () => renderCanvasChart());

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
  if (activeWebSocket) {
    activeWebSocket.close();
    activeWebSocket = null;
  }
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

  showToast(`Welcome back, ${session.user.email}`, 'success');

  // Load user's bound devices from backend
  await fetchUserDevices();

  selectTimeInterval(3);
  renderCanvasChart();
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
    showToast('Account created! Please sign in.', 'success');
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

// ── Backend API & WebSocket Integration ──────────────────────────────────
async function fetchUserDevices() {
  if (!state.currentUser.token) return;

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/devices`, {
      headers: { 'Authorization': `Bearer ${state.currentUser.token}` }
    });
    if (!resp.ok) throw new Error('Failed to fetch devices');
    const data = await resp.json();

    state.devices = data.devices.map(d => ({
      id: d.device_id,
      name: d.device_name || d.device_id,
      sector: d.sector || 'Active Field Sector',
      battery: 100,
      signal: 'Strong',
      boundAt: d.created_at ? d.created_at.split('T')[0] : 'Today'
    }));

    renderBoundDevices();
    updateHeaderDeviceSelector();

    if (state.devices.length > 0) {
      connectDeviceWebSocket(state.devices[state.activeDeviceIndex].id);
    }
  } catch (err) {
    console.error('Error fetching devices:', err);
    renderBoundDevices();
    updateHeaderDeviceSelector();
  }
}

function connectDeviceWebSocket(deviceId) {
  if (activeWebSocket) {
    activeWebSocket.close();
    activeWebSocket = null;
  }

  const wsUrl = `${WS_BASE}/ws/${deviceId}`;
  activeWebSocket = new WebSocket(wsUrl);

  activeWebSocket.onopen = () => {
    const statusText = document.getElementById('wsStatusText');
    if (statusText) statusText.textContent = `${deviceId} (Live)`;
  };

  activeWebSocket.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      if (data.type === 'telemetry') {
        state.telemetry.soilMoisture = data.soil_moisture || 0;
        state.telemetry.temperature = data.temperature || 0;
        state.telemetry.humidity = data.humidity || 0;
        state.telemetry.soilTemp = data.soil_temp || 0;
        state.telemetry.solarRadiation = data.solar_radiation || 0;
        state.telemetry.rainDetected = !!data.rain_detected;
        state.telemetry.battery = data.battery_pct || 100;
        state.telemetry.signal = data.rssi || -70;

        // Push to rolling buffer
        const buf = state.analytics.buffer;
        buf.soil.shift(); buf.soil.push(Math.round(data.soil_moisture));
        buf.temp.shift(); buf.temp.push(Number(data.temperature.toFixed(1)));
        buf.humid.shift(); buf.humid.push(Math.round(data.humidity));
        buf.solar.shift(); buf.solar.push(Math.round(data.solar_radiation));

        updateTelemetryUI();
        renderCanvasChart();

      } else if (data.type === 'pump_update') {
        // Backend Decision Engine changed the pump state
        state.pump.state = data.pump_state || 'OFF';
        if (data.automation_mode) {
          state.pump.automationMode = data.automation_mode;
          updateAutomationModeUI(data.automation_mode);
        }
        evaluatePumpDecisionEngine();
        const trigger = data.trigger || 'Auto';
        showToast(`Pump ${state.pump.state === 'RUNNING' ? 'ON' : 'OFF'} — ${trigger}`, state.pump.state === 'RUNNING' ? 'success' : 'info');

      } else if (data.type === 'mode_update') {
        // Backend confirmed an automation mode change
        if (data.automation_mode) {
          state.pump.automationMode = data.automation_mode;
          updateAutomationModeUI(data.automation_mode);
        }
        if (data.start_threshold) {
          state.telemetry.targetThreshold = data.start_threshold;
          state.telemetry.stopThreshold = data.stop_threshold || 85;
          state.telemetry.maxRuntime = data.max_runtime_mins || 20;
          updateTelemetryUI();
        }
      }
    } catch (e) {
      console.error("WS message error", e);
    }
  };

  activeWebSocket.onclose = () => {
    const statusText = document.getElementById('wsStatusText');
    if (statusText) statusText.textContent = `${deviceId} (Offline)`;
  };
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
            <span class="pulse-dot"></span>
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

function updateTelemetryUI() {
  const hasDevice = state.devices.length > 0;
  const moisture = state.telemetry.soilMoisture;

  const soilValText = document.getElementById('soilValText');
  if (soilValText) soilValText.textContent = hasDevice && moisture > 0 ? Math.round(moisture) : '--';

  const gaugeVal = document.getElementById('soilGaugeVal');
  if (gaugeVal) gaugeVal.setAttribute('stroke-dasharray', `${hasDevice && moisture > 0 ? Math.round(moisture) : 0}, 100`);

  const soilStateText = document.getElementById('soilStateText');
  if (soilStateText) {
    if (!hasDevice || moisture === 0) {
      soilStateText.textContent = 'No Connection';
      soilStateText.style.color = 'var(--text-muted)';
    } else if (moisture < state.telemetry.targetThreshold - 15) {
      soilStateText.textContent = 'Dry';
      soilStateText.style.color = 'var(--amber-warning)';
    } else {
      soilStateText.textContent = 'Optimal';
      soilStateText.style.color = 'var(--green-primary)';
    }
  }

  let tempVal = state.telemetry.temperature;
  if (state.telemetry.tempUnit === 'F' && tempVal > 0) {
    tempVal = (tempVal * 9/5) + 32;
  }
  const tempValText = document.getElementById('tempValText');
  if (tempValText) tempValText.textContent = hasDevice && tempVal > 0 ? tempVal.toFixed(1) : '--';

  const tempUnitText = document.getElementById('tempUnitText');
  if (tempUnitText) tempUnitText.textContent = `°${state.telemetry.tempUnit}`;

  const humidityValText = document.getElementById('humidityValText');
  if (humidityValText) humidityValText.textContent = hasDevice && state.telemetry.humidity > 0 ? Math.round(state.telemetry.humidity) : '--';
}

function updateHeaderDeviceSelector() {
  const select = document.getElementById('headerDeviceSelect');
  if (!select) return;

  if (state.devices.length === 0) {
    select.innerHTML = '<option value="">No Node Connected</option>';
    const statusText = document.getElementById('wsStatusText');
    if (statusText) statusText.textContent = 'No Node Connected';
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
      connectDeviceWebSocket(selectedDev.id);
    }
  };
}

async function handleBindDevice() {
  if (state.devices.length >= 4) {
    showToast('Maximum limit of 4 devices reached per account. Unbind a node first.', 'error');
    document.getElementById('limitWarningBox').style.display = 'flex';
    return;
  }

  const id = document.getElementById('inputDeviceId').value.trim();
  const pass = document.getElementById('inputDevicePass').value.trim();
  const name = document.getElementById('inputDeviceName').value.trim() || `Node ${state.devices.length + 1}`;

  if (!id) {
    showToast('Please enter a valid Hardware ID', 'error');
    return;
  }

  const btn = document.getElementById('btnBindDevice');
  if (btn) { btn.disabled = true; btn.innerText = 'Pairing Node...'; }

  try {
    const resp = await fetch(`${BACKEND_BASE}/api/devices/bind`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_id: id.toUpperCase(),
        device_password: pass || 'secret123',
        device_name: name,
        sector: 'Sector 4 - Field Plot',
        user_token: state.currentUser.token
      })
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Failed to bind device');
    }

    showToast(`Node ${id} successfully paired!`, 'success');
    await fetchUserDevices();
  } catch (err) {
    showToast(err.message, 'error');
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
      const resp = await fetch(`${BACKEND_BASE}/api/devices/${device.id}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${state.currentUser.token}` }
      });
      if (!resp.ok) throw new Error('Unbind failed');
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
      // POST /api/command — backend will also set automation_mode to NONE
      await fetch(`${BACKEND_BASE}/api/command`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: currentDev.id, command: cmdStr })
      });
      showToast(`Manual command sent: ${cmdStr}`, 'success');
    } catch (err) {
      showToast('Failed to send command to backend', 'error');
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
function updateTelemetryUI() {
  const moisture = Math.round(state.telemetry.soilMoisture);
  document.getElementById('soilValText').textContent = moisture;

  const gaugeVal = document.getElementById('soilGaugeVal');
  gaugeVal.setAttribute('stroke-dasharray', `${moisture}, 100`);

  if (moisture < state.telemetry.targetThreshold - 15) {
    document.getElementById('soilStateText').textContent = 'Dry';
    document.getElementById('soilStateText').style.color = 'var(--amber-warning)';
  } else {
    document.getElementById('soilStateText').textContent = 'Optimal';
    document.getElementById('soilStateText').style.color = 'var(--green-primary)';
  }

  let tempVal = state.telemetry.temperature;
  if (state.telemetry.tempUnit === 'F') {
    tempVal = (tempVal * 9/5) + 32;
  }
  document.getElementById('tempValText').textContent = tempVal.toFixed(1);
  document.getElementById('tempUnitText').textContent = `°${state.telemetry.tempUnit}`;
  document.getElementById('humidityValText').textContent = `${state.telemetry.humidity}%`;
  document.getElementById('targetThresholdText').textContent = `${state.telemetry.targetThreshold}%`;

  document.getElementById('ctrlStartVal').textContent = `${state.telemetry.targetThreshold}%`;
  document.getElementById('ctrlStopVal').textContent = `${state.telemetry.stopThreshold}%`;
  document.getElementById('ctrlRuntimeVal').textContent = `${state.telemetry.maxRuntime} mins`;
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

  state.pump.automationMode = mode;
  updateAutomationModeUI(mode);

  try {
    await fetch(`${BACKEND_BASE}/api/automation/mode`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        device_id: currentDev.id,
        mode: mode,
        start_threshold: state.telemetry.targetThreshold,
        stop_threshold: state.telemetry.stopThreshold,
        max_runtime_mins: state.telemetry.maxRuntime
      })
    });

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
    showToast('Failed to update automation mode', 'error');
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

function handleForceStop() {
  state.pump.state = 'OFF';
  evaluatePumpDecisionEngine();
  showToast('Force Stop Executed: Emergency shutdown', 'error');
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

function triggerSimulatedDrySpell() {
  state.telemetry.soilMoisture = 14.5;
  updateTelemetryUI();
  evaluatePumpDecisionEngine();
  showToast('Simulated Dry Spell Event Triggered! Soil moisture dropped to 14.5%', 'warning');
}

// Timer Schedule Manager
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
          ${['M','T','W','T','F','S','S'].map(d => `
            <span class="day-badge ${timer.days.includes(d) ? 'active' : ''}">${d}</span>
          `).join('')}
        </div>
      </div>

      <div style="display: flex; align-items: center; gap: 0.75rem;">
        <label class="toggle-switch">
          <input type="checkbox" ${timer.active ? 'checked' : ''} onchange="toggleTimerActive(${timer.id})">
          <span class="toggle-slider"></span>
        </label>
        <button class="btn-secondary" style="color: var(--rose-danger); padding: 0.2rem 0.5rem;" onclick="deleteTimer(${timer.id})">
          <span class="material-symbols-outlined" style="font-size: 16px;">delete</span>
        </button>
      </div>
    </div>
  `).join('');
}

function handleAddTimer() {
  const timeInput = document.getElementById('timerTimeInput').value;
  const durationInput = parseInt(document.getElementById('timerDurationInput').value) || 15;

  const [h, m] = timeInput.split(':');
  const hour = parseInt(h);
  const ampm = hour >= 12 ? 'PM' : 'AM';
  const hour12 = hour % 12 || 12;
  const formattedTime = `${hour12 < 10 ? '0' + hour12 : hour12}:${m} ${ampm}`;

  const newTimer = {
    id: Date.now(),
    time: formattedTime,
    duration: durationInput,
    days: ['M', 'T', 'W', 'T', 'F'],
    active: true
  };

  state.timers.push(newTimer);
  renderTimers();
  showToast(`Added scheduled timer: Daily ${formattedTime} (${durationInput} mins)`, 'success');
}

function toggleTimerActive(id) {
  const timer = state.timers.find(t => t.id === id);
  if (timer) {
    timer.active = !timer.active;
    showToast(`Timer ${timer.time} ${timer.active ? 'Enabled' : 'Disabled'}`, 'info');
  }
}

function deleteTimer(id) {
  state.timers = state.timers.filter(t => t.id !== id);
  renderTimers();
  showToast('Scheduled timer deleted', 'info');
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
