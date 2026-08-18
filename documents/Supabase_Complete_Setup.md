# 🗄️ Complete Supabase Setup Guide — Step by Step

Follow every step in order. Don't skip anything.

---

## STEP 1: Open Your Supabase Project

1. Open your browser
2. Go to this exact link: **https://supabase.com/dashboard/project/iqmrpwvbmfkhychhditg**
3. You will see your AgriSense project dashboard

---

## STEP 2: Enable Email Authentication

1. On the left sidebar, click **"Authentication"**
2. Then click **"Providers"**
3. Find **"Email"** in the list
4. Make sure the toggle is **ON** (green)
5. Click **Save** if needed

✅ Done. Now farmers can sign up and log in with their email and password.

---

## STEP 3: Open the SQL Editor

1. On the left sidebar, click **"SQL Editor"** (it looks like a database icon)
2. Click the **"New Query"** button (top right)
3. A blank text area will appear where you paste SQL code

---

## STEP 4: Create All Database Tables

Copy everything below (all of it), paste it into the SQL Editor, then click **"Run"**:

```sql
-- ============================================================
-- TABLE 1: devices
-- Stores which ESP32 devices belong to which farmer account
-- One Gmail account can have maximum 4 devices
-- ============================================================
CREATE TABLE devices (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  device_id TEXT UNIQUE NOT NULL,
  device_name TEXT,
  sector TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- This rule automatically BLOCKS a 5th device from being added
CREATE OR REPLACE FUNCTION check_device_limit()
RETURNS TRIGGER AS $$
BEGIN
  IF (SELECT COUNT(*) FROM devices WHERE user_id = NEW.user_id) >= 4 THEN
    RAISE EXCEPTION 'Maximum 4 devices allowed per account';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER enforce_device_limit
BEFORE INSERT ON devices
FOR EACH ROW EXECUTE FUNCTION check_device_limit();


-- ============================================================
-- TABLE 2: telemetry_data
-- Every 10 seconds, the ESP32 sends sensor readings here
-- ============================================================
CREATE TABLE telemetry_data (
  id BIGSERIAL PRIMARY KEY,
  device_id TEXT NOT NULL,
  soil_moisture FLOAT,
  temperature FLOAT,
  humidity FLOAT,
  soil_temp FLOAT,
  solar_radiation FLOAT,
  rain_detected BOOLEAN,
  battery_pct FLOAT,
  rssi INT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
-- TABLE 3: device_commands
-- When you click "Turn Pump ON" on the website,
-- the command is saved here. The ESP32 picks it up every 5 sec.
-- ============================================================
CREATE TABLE device_commands (
  id BIGSERIAL PRIMARY KEY,
  device_id TEXT NOT NULL,
  command TEXT NOT NULL,
  executed BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
-- TABLE 4: timers
-- Stores irrigation schedules (e.g. water at 6AM for 15 mins)
-- ============================================================
CREATE TABLE timers (
  id BIGSERIAL PRIMARY KEY,
  device_id TEXT NOT NULL,
  start_time TEXT NOT NULL,
  duration_mins INT NOT NULL,
  active_days TEXT[],
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
-- REALTIME: Makes the website update instantly when new data arrives
-- ============================================================
ALTER PUBLICATION supabase_realtime ADD TABLE telemetry_data;
ALTER PUBLICATION supabase_realtime ADD TABLE device_commands;
```

After clicking **Run**, you should see:
> **✅ Success. No rows returned.**

If you see an error, copy the error message and tell me.

---

## STEP 5: Add Security Rules (So Farmers Only See Their Own Data)

1. Click **"New Query"** again (to open a fresh blank area)
2. Copy everything below, paste it, and click **"Run"**:

```sql
-- ============================================================
-- ROW LEVEL SECURITY
-- This ensures farmer@gmail.com CANNOT see another farmer's data
-- ============================================================

-- Lock all tables
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry_data ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE timers ENABLE ROW LEVEL SECURITY;


-- devices: You can only see and edit YOUR OWN devices
CREATE POLICY "Users manage own devices"
ON devices FOR ALL
USING (auth.uid() = user_id)
WITH CHECK (auth.uid() = user_id);


-- telemetry_data: You can only see data from YOUR OWN devices
CREATE POLICY "Users see own telemetry"
ON telemetry_data FOR SELECT
USING (
  device_id IN (
    SELECT device_id FROM devices WHERE user_id = auth.uid()
  )
);

-- The Python backend (server) needs to INSERT telemetry without a user login
CREATE POLICY "Backend inserts telemetry"
ON telemetry_data FOR INSERT
WITH CHECK (true);


-- device_commands: You can only see commands for YOUR OWN devices
CREATE POLICY "Users see own commands"
ON device_commands FOR SELECT
USING (
  device_id IN (
    SELECT device_id FROM devices WHERE user_id = auth.uid()
  )
);

-- The website can INSERT new commands
CREATE POLICY "Users insert commands"
ON device_commands FOR INSERT
WITH CHECK (true);

-- The Python backend can UPDATE commands (to mark them as executed)
CREATE POLICY "Backend updates commands"
ON device_commands FOR UPDATE
USING (true);


-- timers: You can only see and edit YOUR OWN timers
CREATE POLICY "Users manage own timers"
ON timers FOR ALL
USING (
  device_id IN (
    SELECT device_id FROM devices WHERE user_id = auth.uid()
  )
)
WITH CHECK (
  device_id IN (
    SELECT device_id FROM devices WHERE user_id = auth.uid()
  )
);
```

After clicking **Run**, you should see:
> **✅ Success. No rows returned.**

---

## STEP 6: Verify Everything Was Created

1. On the left sidebar, click **"Table Editor"**
2. You should see 4 tables listed:
   - ✅ devices
   - ✅ telemetry_data
   - ✅ device_commands
   - ✅ timers

---

## ✅ Supabase is now fully configured!

Tell me when you see all 4 tables in the Table Editor.
After that, I will write the Python Backend server code.
