import React from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { colors, fontMono, radius, spacing } from '../theme/tokens';
import { Card } from './Card';
import { Badge } from './Badge';
import type { AutomationMode } from '../lib/types';

interface AutomationControlProps {
  mode: AutomationMode;
  commandPending: boolean;
  disabled: boolean;
  onChange: (mode: AutomationMode) => void;
}

const MODE_LABELS: Record<AutomationMode, string> = {
  NONE: 'MANUAL',
  MOISTURE: 'MOISTURE AUTO',
  TIMER: 'TIMER SCHEDULE',
};

const OPTIONS: { value: AutomationMode; label: string }[] = [
  { value: 'NONE', label: 'MANUAL' },
  { value: 'MOISTURE', label: 'MOISTURE AUTO' },
  { value: 'TIMER', label: 'TIMER' },
];

export function AutomationControl({ mode, commandPending, disabled, onChange }: AutomationControlProps) {
  return (
    <Card style={styles.card}>
      <Text style={styles.title}>AUTOMATION</Text>

      <Text style={styles.subLabel}>Current Mode</Text>
      <View style={styles.stateRow}>
        <Badge label={MODE_LABELS[mode]} tone={mode === 'NONE' ? 'muted' : 'green'} />
      </View>

      <View style={styles.optionRow}>
        {OPTIONS.map((opt) => {
          const active = opt.value === mode;
          return (
            <Pressable
              key={opt.value}
              onPress={() => !active && onChange(opt.value)}
              disabled={disabled || commandPending}
              style={[
                styles.option,
                active && styles.optionActive,
                (disabled || commandPending) && styles.optionDisabled,
              ]}
            >
              <Text style={[styles.optionText, active && styles.optionTextActive]}>{opt.label}</Text>
            </Pressable>
          );
        })}
      </View>

      {mode === 'NONE' ? (
        <Text style={styles.hint}>Pump Control below is directly controlled by you.</Text>
      ) : (
        <Text style={styles.hint}>
          The existing automation engine controls the pump according to its configured rules.
        </Text>
      )}
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
  optionRow: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  option: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
    backgroundColor: colors.bgSubtle,
  },
  optionActive: {
    borderColor: colors.green,
    backgroundColor: 'rgba(62,207,142,0.12)',
  },
  optionDisabled: {
    opacity: 0.5,
  },
  optionText: {
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: fontMono,
    fontWeight: '700',
  },
  optionTextActive: {
    color: colors.green,
  },
  hint: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: spacing.xs,
  },
});
