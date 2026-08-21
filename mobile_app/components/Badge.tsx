import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { colors, fontMono, radius } from '../theme/tokens';

export type BadgeTone = 'green' | 'amber' | 'rose' | 'blue' | 'muted';

const toneColors: Record<BadgeTone, { bg: string; fg: string; border: string }> = {
  green: { bg: 'rgba(62,207,142,0.12)', fg: colors.green, border: 'rgba(62,207,142,0.3)' },
  amber: { bg: 'rgba(210,153,34,0.12)', fg: colors.amber, border: 'rgba(210,153,34,0.3)' },
  rose: { bg: 'rgba(248,81,73,0.12)', fg: colors.rose, border: 'rgba(248,81,73,0.3)' },
  blue: { bg: 'rgba(88,166,255,0.12)', fg: colors.blue, border: 'rgba(88,166,255,0.3)' },
  muted: { bg: 'rgba(110,118,129,0.12)', fg: colors.textMuted, border: 'rgba(110,118,129,0.3)' },
};

interface BadgeProps {
  label: string;
  tone?: BadgeTone;
}

export function Badge({ label, tone = 'muted' }: BadgeProps) {
  const c = toneColors[tone];
  return (
    <View style={[styles.badge, { backgroundColor: c.bg, borderColor: c.border }]}>
      <Text style={[styles.text, { color: c.fg }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    borderWidth: 1,
    borderRadius: radius.full,
    paddingHorizontal: 10,
    paddingVertical: 4,
    alignSelf: 'flex-start',
  },
  text: {
    fontSize: 11,
    fontFamily: fontMono,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
});
