import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';
import { colors, fontMono } from '../theme/tokens';

interface SoilGaugeProps {
  value: number; // 0-100, ignored (rendered as empty ring) when muted
  stateLabel: string;
  muted?: boolean; // true for OFFLINE/NO_DEVICE — grey ring, no reading
  size?: number;
}

export function SoilGauge({ value, stateLabel, muted, size = 180 }: SoilGaugeProps) {
  const strokeWidth = 14;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, value));
  const progress = muted ? 0 : (clamped / 100) * circumference;
  const ringColor = muted ? colors.textMuted : colors.green;

  return (
    <View style={[styles.wrap, { width: size, height: size }]}>
      <Svg width={size} height={size}>
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={colors.bgSubtle}
          strokeWidth={strokeWidth}
          fill="none"
        />
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={ringColor}
          strokeWidth={strokeWidth}
          fill="none"
          strokeDasharray={`${progress}, ${circumference}`}
          strokeLinecap="round"
          rotation="-90"
          origin={`${size / 2}, ${size / 2}`}
        />
      </Svg>
      <View style={styles.center} pointerEvents="none">
        <Text style={[styles.value, { color: muted ? colors.textMuted : colors.textPrimary }]}>
          {muted ? '00' : Math.round(clamped)}
          <Text style={styles.percent}>%</Text>
        </Text>
        <Text style={[styles.state, { color: ringColor }]}>{stateLabel}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  center: {
    position: 'absolute',
    alignItems: 'center',
  },
  value: {
    fontSize: 36,
    fontWeight: '700',
    fontFamily: fontMono,
  },
  percent: {
    fontSize: 18,
    fontWeight: '400',
  },
  state: {
    fontSize: 12,
    fontFamily: fontMono,
    marginTop: 4,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
});
