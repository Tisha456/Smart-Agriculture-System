import React, { useState } from 'react';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fontMono, spacing } from '../../theme/tokens';
import { Card } from '../../components/Card';
import { Field } from '../../components/Field';
import { Button } from '../../components/Button';
import { Badge } from '../../components/Badge';
import { useAuth } from '../../hooks/useAuth';
import { useDevices, MAX_DEVICES } from '../../hooks/useDevices';

export default function AccountScreen() {
  const { session, signOut } = useAuth();
  const { devices, loading, pair, unbind } = useDevices();

  const [deviceId, setDeviceId] = useState('');
  const [secret, setSecret] = useState('');
  const [name, setName] = useState('');
  const [pairError, setPairError] = useState<string | null>(null);
  const [pairing, setPairing] = useState(false);

  const handlePair = async () => {
    setPairError(null);
    if (!deviceId.trim()) {
      setPairError('Please enter the Hardware Serial ID (e.g. AGS-0001)');
      return;
    }
    if (!secret.trim()) {
      setPairError('Please enter the Pairing Secret printed on your device');
      return;
    }
    setPairing(true);
    try {
      await pair(deviceId.trim(), secret.trim(), name.trim());
      setDeviceId('');
      setSecret('');
      setName('');
      Alert.alert('Node paired', `${deviceId.toUpperCase()} was successfully paired to your account.`);
    } catch (err: any) {
      setPairError(err.message ?? 'Pairing failed');
    } finally {
      setPairing(false);
    }
  };

  const confirmUnbind = (id: string, label: string) => {
    Alert.alert('Unbind Hardware Node', `Are you sure you want to unbind ${label} (${id})?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Unbind',
        style: 'destructive',
        onPress: () => unbind(id).catch((err) => Alert.alert('Unbind failed', err.message)),
      },
    ]);
  };

  return (
    <SafeAreaView style={styles.flex} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>Account</Text>

        <Card style={styles.sessionCard}>
          <Text style={styles.sessionLabel}>Signed in as</Text>
          <Text style={styles.sessionEmail}>{session?.user?.email}</Text>
          <Button label="SIGN OUT" variant="secondary" onPress={signOut} style={styles.signOutButton} />
        </Card>

        <View style={styles.sectionHeaderRow}>
          <Text style={styles.sectionTitle}>BOUND DEVICES</Text>
          <Badge label={`${devices.length} / ${MAX_DEVICES} NODES ACTIVE`} tone={devices.length >= MAX_DEVICES ? 'amber' : 'green'} />
        </View>

        {loading ? (
          <Text style={styles.loadingText}>Loading devices…</Text>
        ) : devices.length === 0 ? (
          <Card style={styles.emptyDevices}>
            <Text style={styles.emptyText}>No active hardware nodes bound to this account.</Text>
          </Card>
        ) : (
          devices.map((d) => (
            <Card key={d.id} style={styles.deviceCard}>
              <View style={styles.deviceInfo}>
                <Text style={styles.deviceName}>
                  {d.name} <Text style={styles.deviceId}>({d.id})</Text>
                </Text>
                <Text style={styles.deviceSector}>{d.sector}</Text>
                <Text style={styles.deviceBound}>Bound {d.boundAt}</Text>
              </View>
              <Button
                label="UNBIND"
                variant="danger"
                onPress={() => confirmUnbind(d.id, d.name)}
                style={styles.unbindButton}
              />
            </Card>
          ))
        )}

        {devices.length >= MAX_DEVICES ? (
          <Card style={styles.limitWarning}>
            <Text style={styles.limitWarningText}>
              Maximum limit of {MAX_DEVICES} devices reached per account. Unbind a node to pair another.
            </Text>
          </Card>
        ) : (
          <Card style={styles.pairCard}>
            <Text style={styles.sectionTitle}>PAIR A NEW NODE</Text>
            {pairError ? <Text style={styles.pairError}>{pairError}</Text> : null}
            <Field
              label="Hardware Serial ID"
              value={deviceId}
              onChangeText={setDeviceId}
              autoCapitalize="characters"
              placeholder="AGS-0001"
            />
            <Field
              label="Pairing Secret"
              value={secret}
              onChangeText={setSecret}
              placeholder="Printed on the device label"
            />
            <Field label="Node Name (optional)" value={name} onChangeText={setName} placeholder="Field Node 1" />
            <Button label="INITIALIZE NODE PAIRING" onPress={handlePair} loading={pairing} />
          </Card>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bgMain },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xxl },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: '800', marginBottom: spacing.lg },
  sessionCard: { marginBottom: spacing.xl },
  sessionLabel: { color: colors.textSecondary, fontSize: 11, marginBottom: spacing.xs },
  sessionEmail: { color: colors.textPrimary, fontSize: 15, fontWeight: '700', marginBottom: spacing.md },
  signOutButton: { alignSelf: 'flex-start', paddingHorizontal: spacing.lg },
  sectionHeaderRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.sm,
  },
  sectionTitle: { color: colors.textSecondary, fontSize: 12, fontFamily: fontMono, letterSpacing: 1 },
  loadingText: { color: colors.textMuted, fontSize: 12 },
  emptyDevices: { marginBottom: spacing.lg },
  emptyText: { color: colors.textMuted, fontSize: 12, textAlign: 'center' },
  deviceCard: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  deviceInfo: { flex: 1, marginRight: spacing.md },
  deviceName: { color: colors.textPrimary, fontSize: 14, fontWeight: '700' },
  deviceId: { color: colors.textSecondary, fontFamily: fontMono, fontWeight: '400', fontSize: 12 },
  deviceSector: { color: colors.textSecondary, fontSize: 11, marginTop: 2 },
  deviceBound: { color: colors.textMuted, fontSize: 10, marginTop: 2 },
  unbindButton: { flex: 0, paddingHorizontal: spacing.md },
  limitWarning: { borderColor: 'rgba(210,153,34,0.4)', backgroundColor: 'rgba(210,153,34,0.08)', marginTop: spacing.md },
  limitWarningText: { color: colors.amber, fontSize: 12, textAlign: 'center' },
  pairCard: { marginTop: spacing.lg },
  pairError: { color: colors.rose, fontSize: 12, marginBottom: spacing.md },
});
