import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Polyline } from 'react-native-svg';
import { colors, fontMono, spacing } from '../theme/tokens';

interface SparklineProps {
  label: string;
  values: number[];
  color: string;
  unit?: string;
  min?: number;
  max?: number;
  height?: number;
}

export function Sparkline({ label, values, color, unit = '', min = 0, max = 100, height = 60 }: SparklineProps) {
  const width = 300;
  const padding = 6;

  const points = values.map((v, i) => {
    const x = values.length > 1 ? padding + (i / (values.length - 1)) * (width - padding * 2) : width / 2;
    const norm = max === min ? 0.5 : (v - min) / (max - min);
    const y = height - padding - Math.max(0, Math.min(1, norm)) * (height - padding * 2);
    return `${x},${y}`;
  });

  const latest = values.length ? values[values.length - 1] : null;

  return (
    <View style={styles.wrap}>
      <View style={styles.headerRow}>
        <Text style={styles.label}>{label}</Text>
        <Text style={[styles.latest, { color }]}>{latest !== null ? `${latest}${unit}` : '--'}</Text>
      </View>
      {values.length > 1 ? (
        <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
          <Polyline points={points.join(' ')} fill="none" stroke={color} strokeWidth={2} />
          <Circle
            cx={points[points.length - 1].split(',')[0]}
            cy={points[points.length - 1].split(',')[1]}
            r={3.5}
            fill={color}
          />
        </Svg>
      ) : (
        <View style={[styles.empty, { height }]}>
          <Text style={styles.emptyText}>No history yet</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginBottom: spacing.md,
  },
  headerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: spacing.xs,
  },
  label: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fontMono,
  },
  latest: {
    fontSize: 12,
    fontFamily: fontMono,
    fontWeight: '700',
  },
  empty: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  emptyText: {
    color: colors.textMuted,
    fontSize: 11,
  },
});
