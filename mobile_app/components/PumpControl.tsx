import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { colors, fontMono, spacing } from '../theme/tokens';
import { Card } from './Card';
import { Badge } from './Badge';
import { Button } from './Button';

interface PumpControlProps {
  pumpState: 'RUNNING' | 'OFF';
  commandPending: boolean;
  disabled: boolean;
  onTurnOn: () => void;
  onTurnOff: () => void;
}

export function PumpControl({ pumpState, commandPending, disabled, onTurnOn, onTurnOff }: PumpControlProps) {
  const running = pumpState === 'RUNNING';
  return (
    <Card style={styles.card}>
      <Text style={styles.title}>PUMP CONTROL</Text>

      <Text style={styles.subLabel}>Current State</Text>
      <View style={styles.stateRow}>
        <Badge label={running ? 'RUNNING' : 'OFF'} tone={running ? 'green' : 'muted'} />
      </View>

      <View style={styles.buttonRow}>
        <Button
          label="TURN ON"
          variant="primary"
          onPress={onTurnOn}
          disabled={disabled || running}
          loading={commandPending && !running}
        />
        <Button
          label="TURN OFF"
          variant="secondary"
          onPress={onTurnOff}
          disabled={disabled || !running}
          loading={commandPending && running}
        />
      </View>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: {
    marginBottom: spacing.md,
  },
  title: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: '700',
    fontFamily: fontMono,
    letterSpacing: 0.5,
    marginBottom: spacing.md,
  },
  subLabel: {
    color: colors.textSecondary,
    fontSize: 11,
    marginBottom: spacing.xs,
  },
  stateRow: {
    marginBottom: spacing.lg,
  },
  buttonRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
});
