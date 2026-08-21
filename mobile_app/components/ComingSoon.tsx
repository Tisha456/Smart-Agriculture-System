import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { colors, fontMono, radius, spacing } from '../theme/tokens';

interface ComingSoonProps {
  label: string; // e.g. "MODEL IN TRAINING"
}

export function ComingSoon({ label }: ComingSoonProps) {
  return (
    <View style={styles.badge}>
      <View style={styles.dot} />
      <Text style={styles.text}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  badge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    alignSelf: 'center',
    backgroundColor: 'rgba(210,153,34,0.1)',
    borderColor: 'rgba(210,153,34,0.35)',
    borderWidth: 1,
    borderRadius: radius.full,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
    backgroundColor: colors.amber,
  },
  text: {
    color: colors.amber,
    fontFamily: fontMono,
    fontSize: 12,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
});
