import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { colors, fontMono, radius } from '../theme/tokens';
import type { ConnectionState } from '../lib/types';

const labelFor: Record<ConnectionState, string> = {
  NO_DEVICE: 'NO DEVICE',
  OFFLINE: 'OFFLINE',
  ONLINE_NO_SENSORS: 'ONLINE — NO SENSORS',
  LIVE: 'LIVE',
};

const colorFor: Record<ConnectionState, string> = {
  NO_DEVICE: colors.textMuted,
  OFFLINE: colors.textMuted,
  ONLINE_NO_SENSORS: colors.green,
  LIVE: colors.green,
};

export function ConnectionPill({ state }: { state: ConnectionState }) {
  const c = colorFor[state];
  return (
    <View style={[styles.pill, { borderColor: c === colors.textMuted ? colors.border : 'rgba(62,207,142,0.35)' }]}>
      <View style={[styles.dot, { backgroundColor: c }]} />
      <Text style={[styles.text, { color: c }]}>{labelFor[state]}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    borderWidth: 1,
    borderRadius: radius.full,
    paddingHorizontal: 10,
    paddingVertical: 5,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: 4,
  },
  text: {
    fontSize: 11,
    fontFamily: fontMono,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
});
