-- ============================================================================
-- AgriSense — Device Registry, Presence Heartbeat & Verified Pairing
-- Run this once in the Supabase SQL editor (after the base setup in
-- Supabase_Complete_Setup.md has already been applied).
--
-- What this fixes:
--   1. Random/fake serial IDs can no longer be "paired" from the website.
--   2. The website can tell the difference between:
--        - ESP32 powered off / unreachable      -> OFFLINE
--        - ESP32 online but sensors disconnected -> ONLINE, sensors_ok = false
--        - ESP32 online with real sensor data    -> ONLINE, sensors_ok = true
--   3. The ESP32 itself can ask "am I bound to an account yet?" and print
--      that to the Serial Monitor.
-- ============================================================================


-- ============================================================================
-- TABLE: device_registry
-- The list of ESP32 boards that actually exist. A device_id not in this
-- table can NEVER be paired from the website, no matter what string is typed.
-- ============================================================================
CREATE TABLE IF NOT EXISTS device_registry (
  device_id      TEXT PRIMARY KEY,          -- e.g. 'AGS-0001', must match #define DEVICE_ID
  pairing_secret TEXT NOT NULL,             -- e.g. printed on the enclosure / set in .ino
  hardware_rev   TEXT DEFAULT 'v3.0',
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE device_registry ENABLE ROW LEVEL SECURITY;
-- Deliberately NO policies here. Nothing — not even the anon key — can
-- SELECT/INSERT/UPDATE this table directly. It is only ever read from inside
-- the SECURITY DEFINER functions below.

-- Seed your real hardware here. Change the secret before shipping this file
-- anywhere public — it currently matches the PAIRING_SECRET placeholder in
-- the .ino config block.
INSERT INTO device_registry (device_id, pairing_secret, hardware_rev)
VALUES ('AGS-0001', '7F3K21X9', 'v3.0')
ON CONFLICT (device_id) DO NOTHING;


-- ============================================================================
-- TABLE: device_status
-- Heartbeat row, one per registered device. The ESP32 upserts this every
-- 10 seconds REGARDLESS of whether its sensors are working. This table is
-- the sole source of truth for "is the hardware alive right now".
-- ============================================================================
CREATE TABLE IF NOT EXISTS device_status (
  device_id        TEXT PRIMARY KEY REFERENCES device_registry(device_id) ON DELETE CASCADE,
  last_seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  sensors_ok       BOOLEAN NOT NULL DEFAULT FALSE,
  sensor_flags     JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {"dht":false,"soil":true,"rain":true}
  firmware_version TEXT,
  ip_address       TEXT,
  rssi             INT,
  boot_count       INT DEFAULT 0
);

ALTER TABLE device_status ENABLE ROW LEVEL SECURITY;

-- ESP32 (anon key) can upsert its own heartbeat. It only knows its own
-- device_id (baked into firmware) so this is not a meaningful attack surface
-- — and device_status.device_id is FK-constrained to device_registry, so a
-- heartbeat can only ever be written for hardware that was actually seeded.
CREATE POLICY "ESP32 upserts own heartbeat"
ON device_status FOR INSERT
WITH CHECK (true);

CREATE POLICY "ESP32 updates own heartbeat"
ON device_status FOR UPDATE
USING (true);

-- Authenticated users can only see heartbeats for devices they actually own.
CREATE POLICY "Users see own device status"
ON device_status FOR SELECT
USING (
  device_id IN (
    SELECT device_id FROM devices WHERE user_id = auth.uid()
  )
);

ALTER PUBLICATION supabase_realtime ADD TABLE device_status;

-- last_seen_at is stamped SERVER-SIDE, never by the device. Two reasons:
--   1. The ESP32 has no NTP clock, so any timestamp it sent would be junk.
--   2. PostgREST's resolution=merge-duplicates only writes the columns present
--      in the payload, so an omitted last_seen_at would be set once on first
--      INSERT and then never refreshed on later heartbeats — the row would go
--      stale after 60 s and claim_device() would report DEVICE_OFFLINE forever.
-- This trigger makes every heartbeat upsert refresh the timestamp regardless.
CREATE OR REPLACE FUNCTION touch_device_status_last_seen()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.last_seen_at := NOW();
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_touch_device_status_last_seen ON device_status;
CREATE TRIGGER trg_touch_device_status_last_seen
BEFORE INSERT OR UPDATE ON device_status
FOR EACH ROW EXECUTE FUNCTION touch_device_status_last_seen();


-- ============================================================================
-- TABLE: device_config
-- Persisted pump automation settings — replaces the FastAPI in-memory
-- device_state dict, which was wiped every time the backend restarted.
-- ============================================================================
CREATE TABLE IF NOT EXISTS device_config (
  device_id        TEXT PRIMARY KEY REFERENCES devices(device_id) ON DELETE CASCADE,
  automation_mode  TEXT NOT NULL DEFAULT 'NONE'
                   CHECK (automation_mode IN ('NONE','MOISTURE','TIMER')),
  start_threshold  INT NOT NULL DEFAULT 70,
  stop_threshold   INT NOT NULL DEFAULT 85,
  max_runtime_mins INT NOT NULL DEFAULT 20,
  pump_on          BOOLEAN NOT NULL DEFAULT FALSE,
  pump_on_since    TIMESTAMPTZ,
  updated_at       TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE device_config ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users manage own device config"
ON device_config FOR ALL
USING (
  device_id IN (SELECT device_id FROM devices WHERE user_id = auth.uid())
)
WITH CHECK (
  device_id IN (SELECT device_id FROM devices WHERE user_id = auth.uid())
);

-- The FastAPI backend uses the service_role key, which bypasses RLS entirely,
-- so no separate backend policy is needed here.

ALTER PUBLICATION supabase_realtime ADD TABLE device_config;


-- ============================================================================
-- FUNCTION: claim_device()
-- Replaces the open "WITH CHECK (true)" INSERT policy on devices.
-- This is the ONLY way a device_id can be added to `devices` from now on.
--
-- Three gates, in order:
--   1. Serial + secret must match a real, manufactured board (device_registry)
--   2. The device must not already be claimed by anyone
--   3. The device must have sent a heartbeat within the last 60 seconds
--      (i.e. it must be powered on and reachable RIGHT NOW)
-- ============================================================================
CREATE OR REPLACE FUNCTION claim_device(
  p_device_id TEXT,
  p_secret    TEXT,
  p_name      TEXT,
  p_sector    TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_uid   UUID := auth.uid();
  v_last  TIMESTAMPTZ;
  v_owner UUID;
BEGIN
  IF v_uid IS NULL THEN
    RETURN jsonb_build_object('ok', false, 'code', 'NOT_LOGGED_IN');
  END IF;

  -- Gate 1: serial + secret must match a real manufactured board
  IF NOT EXISTS (
    SELECT 1 FROM device_registry
    WHERE device_id = p_device_id AND pairing_secret = p_secret
  ) THEN
    RETURN jsonb_build_object('ok', false, 'code', 'UNKNOWN_DEVICE');
  END IF;

  -- Gate 2: not already claimed (by you or anyone else)
  SELECT user_id INTO v_owner FROM devices WHERE device_id = p_device_id;
  IF v_owner IS NOT NULL THEN
    RETURN jsonb_build_object(
      'ok', false,
      'code', CASE WHEN v_owner = v_uid THEN 'ALREADY_YOURS' ELSE 'CLAIMED_BY_OTHER' END
    );
  END IF;

  -- Gate 3: the hardware must be powered on and reachable right now
  SELECT last_seen_at INTO v_last FROM device_status WHERE device_id = p_device_id;
  IF v_last IS NULL OR v_last < NOW() - INTERVAL '60 seconds' THEN
    RETURN jsonb_build_object('ok', false, 'code', 'DEVICE_OFFLINE');
  END IF;

  -- 4-device-per-account limit is still enforced by the existing
  -- enforce_device_limit trigger on `devices` (see Supabase_Complete_Setup.md).
  INSERT INTO devices (user_id, device_id, device_name, sector)
  VALUES (v_uid, p_device_id, p_name, p_sector);

  INSERT INTO device_config (device_id) VALUES (p_device_id)
  ON CONFLICT (device_id) DO NOTHING;

  RETURN jsonb_build_object('ok', true, 'device_id', p_device_id);
END;
$$;

-- Let logged-in users call this RPC.
GRANT EXECUTE ON FUNCTION claim_device(TEXT, TEXT, TEXT, TEXT) TO authenticated;


-- ============================================================================
-- FUNCTION: device_pair_status()
-- Called BY THE ESP32 (anon key) to ask "has this serial been bound to an
-- account yet?". Returns only what's safe for an unauthenticated device to
-- know — never the owner's email or user_id.
-- ============================================================================
CREATE OR REPLACE FUNCTION device_pair_status(
  p_device_id TEXT,
  p_secret    TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_name   TEXT;
  v_sector TEXT;
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM device_registry
    WHERE device_id = p_device_id AND pairing_secret = p_secret
  ) THEN
    RETURN jsonb_build_object('registered', false, 'paired', false);
  END IF;

  SELECT device_name, sector INTO v_name, v_sector
  FROM devices WHERE device_id = p_device_id;

  RETURN jsonb_build_object(
    'registered', true,
    'paired', v_name IS NOT NULL,
    'device_name', v_name,
    'sector', v_sector
  );
END;
$$;

-- The ESP32 calls this with only the anon key (no user session), so anon
-- needs execute rights. It cannot get here without knowing device_id AND
-- the matching pairing_secret, both baked into the firmware at flash time.
GRANT EXECUTE ON FUNCTION device_pair_status(TEXT, TEXT) TO anon;


-- ============================================================================
-- Close the hole: remove the open INSERT policy from Supabase_Complete_Setup.md
-- Step 6. From this point on, `claim_device()` is the only way into `devices`.
-- ============================================================================
DROP POLICY IF EXISTS "Backend inserts devices" ON devices;


-- ============================================================================
-- Fix: the ESP32 can never read its own pump commands.
--
-- Supabase_Complete_Setup.md Step 5 created:
--   CREATE POLICY "Users see own commands" ON device_commands FOR SELECT
--   USING (device_id IN (SELECT device_id FROM devices WHERE user_id = auth.uid()));
--
-- The ESP32 polls with the ANON key and no logged-in user session, so
-- auth.uid() evaluates to NULL for it and that policy returns zero rows.
-- Every PUMP_ON/PUMP_OFF/force-stop command ever queued has been invisible
-- to the board — the poll always came back "[]", so the pump only ever moved
-- by its own auto-irrigation logic, never by a website/app click.
--
-- A blanket `FOR SELECT USING (true)` policy would "fix" this but is wrong:
-- a Postgres RLS policy with no `TO <role>` clause applies to EVERY role, so
-- it would OR itself onto the authenticated "Users see own commands" policy
-- too — any logged-in user would suddenly see every user's commands, not
-- just their own. And even scoped `TO anon`, a SELECT with no per-row check
-- lets anyone holding the public anon key (it ships inside this firmware,
-- web_dashboard/app.js, and the mobile app bundle — it is not a secret) list
-- every device_id and its queued commands with no filter required, unlike
-- the `USING (true)` heartbeat policies above, which only ever let a caller
-- affect one row it already names.
--
-- Fix: reuse the exact proof-of-possession check device_pair_status() above
-- already uses. The ESP32 has to supply BOTH its device_id and the matching
-- pairing_secret — knowledge only the real hardware has — before it gets
-- back so much as one row.
-- ============================================================================
CREATE OR REPLACE FUNCTION device_pending_commands(p_device_id TEXT, p_secret TEXT)
RETURNS TABLE(id BIGINT, command TEXT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM device_registry
    WHERE device_id = p_device_id AND pairing_secret = p_secret
  ) THEN
    RETURN;  -- unknown device_id / wrong secret -> no rows, not an error
  END IF;

  RETURN QUERY
  SELECT dc.id, dc.command
  FROM device_commands dc
  WHERE dc.device_id = p_device_id AND dc.executed = FALSE
  ORDER BY dc.created_at ASC
  LIMIT 1;
END;
$$;

-- Same reasoning as device_pair_status(): the ESP32 calls this with only the
-- anon key, so anon needs execute rights, but it can't get a result without
-- knowing device_id AND pairing_secret together.
GRANT EXECUTE ON FUNCTION device_pending_commands(TEXT, TEXT) TO anon;
