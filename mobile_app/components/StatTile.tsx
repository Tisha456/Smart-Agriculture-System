import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { colors, fontMono, spacing } from '../theme/tokens';
import { Card } from './Card';

interface StatTileProps {
  label: string;
  value: string;
  unit?: string;
  color?: string;
  subtitle?: string;
}

export function StatTile({ label, value, unit, color = colors.textPrimary, subtitle }: StatTileProps) {
  return (
    <Card style={styles.tile}>
      <Text style={styles.label}>{label}</Text>
      <View style={styles.valueRow}>
        <Text style={[styles.value, { color }]}>{value}</Text>
        {unit ? <Text style={styles.unit}>{unit}</Text> : null}
      </View>
      {subtitle ? <Text style={styles.subtitle}>{subtitle}</Text> : null}
    </Card>
  );
}

const styles = StyleSheet.create({
  tile: {
    flex: 1,
    alignItems: 'flex-start',
  },
  label: {
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: fontMono,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.xs,
  },
  valueRow: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 4,
  },
  value: {
    fontSize: 28,
    fontWeight: '700',
    fontFamily: fontMono,
  },
  unit: {
    color: colors.textSecondary,
    fontSize: 14,
    marginBottom: 4,
  },
  subtitle: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: spacing.xs,
  },
});
