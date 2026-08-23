import React, { useState } from 'react';
import { Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import Feather from '@expo/vector-icons/Feather';
import { colors, fontMono, radius, spacing } from '../theme/tokens';
import type { Device } from '../lib/types';

interface DevicePickerProps {
  devices: Device[];
  activeIndex: number;
  onSelect: (index: number) => void;
}

export function DevicePicker({ devices, activeIndex, onSelect }: DevicePickerProps) {
  const [open, setOpen] = useState(false);
  const active = devices[activeIndex];

  if (!devices.length) {
    return (
      <View style={styles.trigger}>
        <Text style={styles.name}>No Node Connected</Text>
      </View>
    );
  }

  return (
    <>
      <Pressable style={styles.trigger} onPress={() => setOpen(true)} disabled={devices.length <= 1}>
        <Text style={styles.name}>{active.name}</Text>
        <Text style={styles.id}>{active.id}</Text>
        {devices.length > 1 ? (
          <Feather name="chevron-down" size={14} color={colors.textMuted} style={styles.chevron} />
        ) : null}
      </Pressable>

      <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
        <Pressable style={styles.backdrop} onPress={() => setOpen(false)}>
          <View style={styles.menu}>
            {devices.map((d, i) => (
              <Pressable
                key={d.id}
                style={[styles.menuItem, i === activeIndex && styles.menuItemActive]}
                onPress={() => {
                  onSelect(i);
                  setOpen(false);
                }}
              >
                <Text style={styles.menuItemName}>{d.name}</Text>
                <Text style={styles.menuItemId}>{d.id}</Text>
              </Pressable>
            ))}
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  trigger: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: 6,
  },
  name: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: '700',
  },
  id: {
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: fontMono,
  },
  chevron: {
    marginLeft: 2,
  },
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(1,4,9,0.7)',
    justifyContent: 'flex-start',
    paddingTop: 100,
    paddingHorizontal: spacing.lg,
  },
  menu: {
    backgroundColor: colors.bgCard,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.lg,
    overflow: 'hidden',
  },
  menuItem: {
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderBottomColor: colors.borderMuted,
    borderBottomWidth: 1,
  },
  menuItemActive: {
    backgroundColor: colors.bgCardHover,
  },
  menuItemName: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
  },
  menuItemId: {
    color: colors.textSecondary,
    fontSize: 11,
    fontFamily: fontMono,
    marginTop: 2,
  },
});
