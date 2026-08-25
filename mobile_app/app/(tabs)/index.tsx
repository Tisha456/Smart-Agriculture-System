import React, { useCallback, useState } from 'react';
import { Alert, Linking, RefreshControl, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fontMono, spacing } from '../../theme/tokens';
import { useAuth } from '../../hooks/useAuth';
import { useDevices } from '../../hooks/useDevices';
import { useDeviceLive } from '../../hooks/useDeviceLive';
import { useDeviceControls } from '../../hooks/useDeviceControls';
import { DevicePicker } from '../../components/DevicePicker';
import { ConnectionPill } from '../../components/ConnectionPill';
import { SoilGauge } from '../../components/SoilGauge';
import { StatTile } from '../../components/StatTile';
import { Badge } from '../../components/Badge';
import { Sparkline } from '../../components/Sparkline';
import { Card } from '../../components/Card';
import { Button } from '../../components/Button';
import { ControlsPanel } from '../../components/ControlsPanel';
import { getLiveCameraUrl } from '../../lib/camera';

function timeAgo(ms: number | null): string {
  if (!ms) return '--';
  const diff = Math.max(0, Date.now() - ms);
  if (diff < 5000) return 'Just now';
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  return `${Math.floor(diff / 3600000)}h ago`;
}

function HealthRow({ label, value, tone }: { label: string; value: string; tone?: 'green' | 'rose' | 'muted' }) {
  const color = tone === 'green' ? colors.green : tone === 'rose' ? colors.rose : colors.textPrimary;
  return (
    <View style={styles.healthRow}>
      <Text style={styles.healthLabel}>{label}</Text>
      <Text style={[styles.healthValue, { color }]}>{value}</Text>
    </View>
  );
}

export default function DashboardScreen() {
  const { session } = useAuth();
  const { devices, activeDevice, activeDeviceIndex, setActiveDeviceIndex, loading: devicesLoading, fetchDevices } =
    useDevices();
  const deviceId = activeDevice?.id ?? null;
  const live = useDeviceLive(deviceId);
  const controls = useDeviceControls(deviceId);

  const [cameraLoading, setCameraLoading] = useState(false);
  async function openLiveCamera() {
    if (!deviceId || !session) return;
    setCameraLoading(true);
    try {
      const url = await getLiveCameraUrl(deviceId, session.access_token);
      await Linking.openURL(url);
    } catch (err: any) {
      Alert.alert('Live camera failed', err?.message ?? 'Could not reach the camera relay.');
    } finally {
      setCameraLoading(false);
    }
  }

  const [refreshing, setRefreshing] = useState(false);
  const onRefresh = useCallback(async () => {
    setRefreshing(true);
    await Promise.all([fetchDevices(), live.refresh(), controls.refreshControls()]);
    setRefreshing(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetchDevices, live.refresh, controls.refreshControls]);

  const cs = live.connectionState;
  const muted = cs === 'OFFLINE' || cs === 'NO_DEVICE';
  const hasDevice = !!activeDevice;

  // Each sensor renders from its OWN health flag, never from the global
  // sensors_ok — that is only (dht && soil), so a dead DHT used to blank the
  // soil gauge and rain badge too. A working sensor always shows its real
  // reading; a failed one shows 00 and is called out in NODE HEALTH below.
  // `undefined` means older firmware that didn't send flags: assume OK.
  const dhtOk = !muted && live.presence.sensorFlags.dht !== false;
  const soilOk = !muted && live.presence.sensorFlags.soil !== false;

  return (
    <SafeAreaView style={styles.flex} edges={['top']}>
      <ScrollView
        contentContainerStyle={styles.scroll}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.green} />}
      >
        <View style={styles.header}>
          <DevicePicker devices={devices} activeIndex={activeDeviceIndex} onSelect={setActiveDeviceIndex} />
          <ConnectionPill state={cs} />
        </View>

        {cs === 'NO_DEVICE' && !devicesLoading ? (
          <Card style={styles.emptyCard}>
            <Text style={styles.emptyTitle}>No Node Connected</Text>
            <Text style={styles.emptyBody}>
              Pair an AgriSense board from the Account tab to see live telemetry and controls here.
            </Text>
          </Card>
        ) : null}

        {cs === 'OFFLINE' ? (
          <Card style={styles.offlineBanner}>
            <Text style={styles.offlineText}>
              {activeDevice?.name} is OFFLINE — no heartbeat received. Check power and Wi-Fi.
            </Text>
          </Card>
        ) : null}

        {cs === 'ONLINE_NO_SENSORS' ? (
          <Card style={styles.noSensorBanner}>
            <Text style={styles.noSensorText}>
              {`${[!dhtOk && 'DHT11 (temp/humidity, GPIO 4)', !soilOk && 'soil probe (GPIO 34)']
                .filter(Boolean)
                .join(' and ')} not reporting — check wiring. Other sensors keep working.`}
            </Text>
          </Card>
        ) : null}

        <View style={styles.gaugeWrap}>
          <SoilGauge
            value={soilOk ? live.telemetry.soilMoisture : 0}
            stateLabel={
              muted
                ? 'NO DATA'
                : !soilOk
                ? 'NO PROBE'
                : live.telemetry.soilMoisture < 40
                ? 'DRY'
                : 'OPTIMAL'
            }
            muted={!soilOk}
          />
        </View>

        <View style={styles.statRow}>
          <StatTile
            label="Temperature"
            value={dhtOk ? live.telemetry.temperature.toFixed(1) : '00'}
            unit="°C"
            color={dhtOk ? colors.amber : colors.textMuted}
          />
          <StatTile
            label="Humidity"
            value={dhtOk ? `${Math.round(live.telemetry.humidity)}` : '00'}
            unit="%"
            color={dhtOk ? colors.blue : colors.textMuted}
          />
        </View>

        <Card style={styles.rainCard}>
          <Text style={styles.rainLabel}>RAIN STATUS</Text>
          {/* Rain is reported independently of sensors_ok — the firmware sets
              sensor_flags.rain = true unconditionally because a digital rain
              sensor can't be health-checked (AgriSense_ESP32.ino
              sendHeartbeat), and sensors_ok is only dht && soil. So a DHT or
              soil failure must not mask a working rain reading; only a fully
              offline device does. */}
          <Badge
            label={
              muted
                ? 'SENSORS OFFLINE'
                : live.telemetry.rainDetected
                ? 'RAIN DETECTED'
                : 'DRY / CLEAR'
            }
            tone={muted ? 'muted' : live.telemetry.rainDetected ? 'blue' : 'green'}
          />
        </Card>

        <Text style={styles.sectionTitle}>LIVE HISTORY</Text>
        <Card style={styles.historyCard}>
          <Sparkline label="Soil Moisture" values={live.history.soil} color={colors.green} unit="%" min={0} max={100} />
          <Sparkline label="Temperature" values={live.history.temp} color={colors.amber} unit="°C" min={0} max={50} />
          <Sparkline label="Humidity" values={live.history.humid} color={colors.blue} unit="%" min={0} max={100} />
        </Card>

        <Text style={styles.sectionTitle}>NODE HEALTH</Text>
        <Card>
          <HealthRow label="Connection" value={cs.replace(/_/g, ' ')} tone={muted ? 'muted' : 'green'} />
          <HealthRow label="Last Seen" value={timeAgo(live.presence.lastSeenMs)} />
          <HealthRow
            label="DHT"
            value={live.presence.sensorFlags.dht === false ? 'FAIL' : hasDevice ? 'OK' : '--'}
            tone={live.presence.sensorFlags.dht === false ? 'rose' : 'green'}
          />
          <HealthRow
            label="Soil Sensor"
            value={live.presence.sensorFlags.soil === false ? 'FAIL' : hasDevice ? 'OK' : '--'}
            tone={live.presence.sensorFlags.soil === false ? 'rose' : 'green'}
          />
          <HealthRow
            label="Rain Sensor"
            value={live.presence.sensorFlags.rain === false ? 'FAIL' : hasDevice ? 'OK' : '--'}
            tone={live.presence.sensorFlags.rain === false ? 'rose' : 'green'}
          />
          <HealthRow label="RSSI" value={live.presence.rssi != null ? `${live.presence.rssi} dBm` : '--'} />
          <HealthRow label="Firmware" value={live.presence.firmwareVersion ?? '--'} />
          <HealthRow label="IP" value={live.presence.ipAddress ?? '--'} />
        </Card>

        <Text style={styles.sectionTitle}>FIELD CAMERA</Text>
        <Card style={styles.cameraCard}>
          <Button
            label="LIVE CAMERA"
            variant="secondary"
            onPress={openLiveCamera}
            loading={cameraLoading}
            disabled={!hasDevice}
          />
        </Card>

        <ControlsPanel controls={controls} hasDevice={hasDevice} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bgMain },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xxl * 2 },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.lg,
  },
  emptyCard: { alignItems: 'center', marginBottom: spacing.lg },
  emptyTitle: { color: colors.textPrimary, fontWeight: '700', fontSize: 15, marginBottom: spacing.xs },
  emptyBody: { color: colors.textSecondary, fontSize: 12, textAlign: 'center' },
  offlineBanner: { borderColor: colors.border, backgroundColor: colors.bgSubtle, marginBottom: spacing.lg },
  offlineText: { color: colors.textMuted, fontSize: 12, textAlign: 'center' },
  noSensorBanner: { borderColor: 'rgba(62,207,142,0.3)', backgroundColor: 'rgba(62,207,142,0.08)', marginBottom: spacing.lg },
  noSensorText: { color: colors.green, fontSize: 12, textAlign: 'center' },
  gaugeWrap: { alignItems: 'center', marginBottom: spacing.lg },
  statRow: { flexDirection: 'row', gap: spacing.md, marginBottom: spacing.md },
  rainCard: { alignItems: 'center', marginBottom: spacing.lg },
  rainLabel: { color: colors.textSecondary, fontSize: 11, fontFamily: fontMono, marginBottom: spacing.sm },
  sectionTitle: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fontMono,
    letterSpacing: 1,
    marginBottom: spacing.sm,
    marginTop: spacing.sm,
  },
  historyCard: { marginBottom: spacing.lg },
  cameraCard: { marginBottom: spacing.lg },
  healthRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderMuted,
  },
  healthLabel: { color: colors.textSecondary, fontSize: 12 },
  healthValue: { fontSize: 12, fontFamily: fontMono, fontWeight: '700' },
});
