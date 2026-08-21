import React from 'react';
import { Alert, StyleSheet, Text } from 'react-native';
import { colors, fontMono, spacing } from '../theme/tokens';
import { Card } from './Card';
import { Button } from './Button';

interface ForceStopProps {
  commandPending: boolean;
  disabled: boolean;
  onForceStop: () => void;
}

export function ForceStop({ commandPending, disabled, onForceStop }: ForceStopProps) {
  const confirm = () => {
    Alert.alert(
      'Force Stop',
      'This will immediately stop the active pump or irrigation operation. Continue?',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Force Stop', style: 'destructive', onPress: onForceStop },
      ]
    );
  };

  return (
    <Card style={styles.card}>
      <Text style={styles.title}>⚠ FORCE STOP</Text>
      <Text style={styles.body}>
        Immediately stop the active pump or irrigation operation.
      </Text>
      <Button label="FORCE STOP" variant="danger" onPress={confirm} disabled={disabled} loading={commandPending} />
    </Card>
  );
}

const styles = StyleSheet.create({
  card: {
    borderColor: 'rgba(248,81,73,0.35)',
  },
  title: {
    color: colors.rose,
    fontSize: 13,
    fontWeight: '700',
    fontFamily: fontMono,
    letterSpacing: 0.5,
    marginBottom: spacing.sm,
  },
  body: {
    color: colors.textSecondary,
    fontSize: 12,
    marginBottom: spacing.lg,
    lineHeight: 18,
  },
});
