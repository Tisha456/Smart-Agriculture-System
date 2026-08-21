import React, { useState } from 'react';
import { Alert, Modal, Pressable, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import DateTimePicker from '@react-native-community/datetimepicker';
import { colors, fontMono, radius, spacing } from '../theme/tokens';
import { Card } from './Card';
import { Button } from './Button';
import { ALL_DAYS, type Timer } from '../lib/types';

const DAY_SHORT: Record<string, string> = { Mo: 'M', Tu: 'T', We: 'W', Th: 'T', Fr: 'F', Sa: 'S', Su: 'S' };
const DEFAULT_DAYS = ['Mo', 'Tu', 'We', 'Th', 'Fr'];

interface TimerControlProps {
  timers: Timer[];
  disabled: boolean;
  onCreate: (payload: { startTime: string; durationMins: number; activeDays: string[] }) => Promise<void>;
  onUpdate: (timer: Timer, changes: { startTime: string; durationMins: number; activeDays: string[] }) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onToggle: (id: number, isActive: boolean) => Promise<void>;
}

function to12h(time24: string): string {
  const [h, m] = time24.split(':').map(Number);
  const ampm = h >= 12 ? 'PM' : 'AM';
  const hour12 = h % 12 || 12;
  return `${String(hour12).padStart(2, '0')}:${String(m).padStart(2, '0')} ${ampm}`;
}

function addMinutes(time24: string, minutes: number): string {
  const [h, m] = time24.split(':').map(Number);
  const total = (h * 60 + m + minutes) % (24 * 60);
  const hh = Math.floor(total / 60);
  const mm = total % 60;
  return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

function dateToTime24(d: Date): string {
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function time24ToDate(time24: string): Date {
  const [h, m] = time24.split(':').map(Number);
  const d = new Date();
  d.setHours(h, m, 0, 0);
  return d;
}

export function TimerControl({ timers, disabled, onCreate, onUpdate, onDelete, onToggle }: TimerControlProps) {
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<Timer | null>(null);
  const [time, setTime] = useState<Date>(new Date());
  const [showPicker, setShowPicker] = useState(false);
  const [duration, setDuration] = useState('15');
  const [days, setDays] = useState<string[]>(DEFAULT_DAYS);
  const [saving, setSaving] = useState(false);

  const openCreate = () => {
    setEditing(null);
    setTime(new Date());
    setDuration('15');
    setDays(DEFAULT_DAYS);
    setFormOpen(true);
  };

  const openEdit = (timer: Timer) => {
    setEditing(timer);
    setTime(time24ToDate(timer.start_time));
    setDuration(String(timer.duration_mins));
    setDays(timer.active_days?.length ? timer.active_days : DEFAULT_DAYS);
    setFormOpen(true);
  };

  const toggleDay = (day: string) => {
    setDays((prev) => (prev.includes(day) ? prev.filter((d) => d !== day) : [...prev, day]));
  };

  const submit = async () => {
    const durationMins = parseInt(duration, 10);
    if (!durationMins || durationMins <= 0) {
      Alert.alert('Invalid duration', 'Enter a duration in minutes greater than 0.');
      return;
    }
    if (!days.length) {
      Alert.alert('No days selected', 'Pick at least one active day.');
      return;
    }
    setSaving(true);
    try {
      const payload = { startTime: dateToTime24(time), durationMins, activeDays: days };
      if (editing) {
        await onUpdate(editing, payload);
      } else {
        await onCreate(payload);
      }
      setFormOpen(false);
    } catch (err: any) {
      Alert.alert('Timer save failed', err.message ?? 'Unknown error');
    } finally {
      setSaving(false);
    }
  };

  const confirmDelete = (timer: Timer) => {
    Alert.alert('Delete timer', `Remove the ${to12h(timer.start_time)} timer?`, [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: () => onDelete(timer.id).catch((err) => Alert.alert('Delete failed', err.message)),
      },
    ]);
  };

  return (
    <Card style={styles.card}>
      <Text style={styles.title}>TIMERS</Text>

      {timers.length === 0 ? (
        <Text style={styles.empty}>No active scheduled timers configured.</Text>
      ) : (
        timers.map((timer) => (
          <View key={timer.id} style={styles.timerRow}>
            <View style={styles.timerInfo}>
              <Text style={styles.timerTime}>
                {to12h(timer.start_time)} → {to12h(addMinutes(timer.start_time, timer.duration_mins))}
              </Text>
              <View style={styles.dayRow}>
                {ALL_DAYS.map((d) => (
                  <View
                    key={d}
                    style={[styles.dayBadge, timer.active_days?.includes(d) && styles.dayBadgeActive]}
                  >
                    <Text
                      style={[styles.dayText, timer.active_days?.includes(d) && styles.dayTextActive]}
                    >
                      {DAY_SHORT[d]}
                    </Text>
                  </View>
                ))}
              </View>
              <Text style={[styles.status, { color: timer.is_active ? colors.green : colors.textMuted }]}>
                {timer.is_active ? 'ENABLED' : 'DISABLED'}
              </Text>
            </View>

            <View style={styles.timerActions}>
              <Switch
                value={timer.is_active}
                onValueChange={(v) => onToggle(timer.id, v).catch((err) => Alert.alert('Failed', err.message))}
                disabled={disabled}
                trackColor={{ false: colors.bgSubtle, true: 'rgba(62,207,142,0.5)' }}
                thumbColor={timer.is_active ? colors.green : colors.textMuted}
              />
              <Pressable onPress={() => openEdit(timer)} disabled={disabled}>
                <Text style={styles.actionLink}>EDIT</Text>
              </Pressable>
              <Pressable onPress={() => confirmDelete(timer)} disabled={disabled}>
                <Text style={[styles.actionLink, { color: colors.rose }]}>DELETE</Text>
              </Pressable>
            </View>
          </View>
        ))
      )}

      <Button label="+ ADD TIMER" variant="secondary" onPress={openCreate} disabled={disabled} />

      <Modal visible={formOpen} transparent animationType="slide" onRequestClose={() => setFormOpen(false)}>
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>{editing ? 'EDIT TIMER' : 'ADD TIMER'}</Text>

            <Text style={styles.fieldLabel}>Start Time</Text>
            <Pressable style={styles.timeButton} onPress={() => setShowPicker(true)}>
              <Text style={styles.timeButtonText}>{to12h(dateToTime24(time))}</Text>
            </Pressable>
            {showPicker && (
              <DateTimePicker
                value={time}
                mode="time"
                display="spinner"
                onChange={(_, selected) => {
                  setShowPicker(false);
                  if (selected) setTime(selected);
                }}
              />
            )}

            <Text style={styles.fieldLabel}>Duration (minutes)</Text>
            <TextInput
              style={styles.durationInput}
              keyboardType="number-pad"
              value={duration}
              onChangeText={setDuration}
              placeholderTextColor={colors.textMuted}
            />

            <Text style={styles.fieldLabel}>Active Days</Text>
            <View style={styles.dayPickerRow}>
              {ALL_DAYS.map((d) => (
                <Pressable
                  key={d}
                  onPress={() => toggleDay(d)}
                  style={[styles.dayPickerChip, days.includes(d) && styles.dayPickerChipActive]}
                >
                  <Text style={[styles.dayPickerText, days.includes(d) && styles.dayPickerTextActive]}>
                    {DAY_SHORT[d]}
                  </Text>
                </Pressable>
              ))}
            </View>

            <View style={styles.modalButtonRow}>
              <Button label="CANCEL" variant="secondary" onPress={() => setFormOpen(false)} disabled={saving} style={styles.modalButton} />
              <Button label={editing ? 'SAVE' : 'ADD'} variant="primary" onPress={submit} loading={saving} style={styles.modalButton} />
            </View>
          </View>
        </View>
      </Modal>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { marginBottom: spacing.md },
  title: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: '700',
    fontFamily: fontMono,
    letterSpacing: 0.5,
    marginBottom: spacing.md,
  },
  empty: { color: colors.textMuted, fontSize: 12, marginBottom: spacing.md },
  timerRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderTopWidth: 1,
    borderTopColor: colors.borderMuted,
    paddingVertical: spacing.md,
  },
  timerInfo: { flex: 1 },
  timerTime: { color: colors.textPrimary, fontSize: 14, fontFamily: fontMono, fontWeight: '700' },
  dayRow: { flexDirection: 'row', gap: 3, marginTop: spacing.xs },
  dayBadge: {
    width: 18,
    height: 18,
    borderRadius: 9,
    backgroundColor: colors.bgSubtle,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dayBadgeActive: { backgroundColor: 'rgba(62,207,142,0.25)' },
  dayText: { fontSize: 9, color: colors.textMuted, fontFamily: fontMono },
  dayTextActive: { color: colors.green },
  status: { fontSize: 10, fontFamily: fontMono, marginTop: spacing.xs, fontWeight: '700' },
  timerActions: { alignItems: 'flex-end', gap: spacing.xs },
  actionLink: { color: colors.blue, fontSize: 11, fontFamily: fontMono, fontWeight: '700' },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(1,4,9,0.75)',
    justifyContent: 'flex-end',
  },
  modalCard: {
    backgroundColor: colors.bgCard,
    borderTopLeftRadius: radius.lg,
    borderTopRightRadius: radius.lg,
    borderColor: colors.border,
    borderWidth: 1,
    padding: spacing.lg,
  },
  modalTitle: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '700',
    fontFamily: fontMono,
    marginBottom: spacing.lg,
  },
  fieldLabel: { color: colors.textSecondary, fontSize: 11, marginBottom: spacing.xs, marginTop: spacing.sm },
  timeButton: {
    backgroundColor: colors.bgInput,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  timeButtonText: { color: colors.textPrimary, fontFamily: fontMono, fontSize: 16, fontWeight: '700' },
  durationInput: {
    backgroundColor: colors.bgInput,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    color: colors.textPrimary,
    fontFamily: fontMono,
  },
  dayPickerRow: { flexDirection: 'row', gap: spacing.xs },
  dayPickerChip: {
    width: 34,
    height: 34,
    borderRadius: 17,
    backgroundColor: colors.bgSubtle,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dayPickerChipActive: { backgroundColor: 'rgba(62,207,142,0.2)', borderColor: colors.green },
  dayPickerText: { color: colors.textMuted, fontFamily: fontMono, fontSize: 12 },
  dayPickerTextActive: { color: colors.green, fontWeight: '700' },
  modalButtonRow: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.lg },
  modalButton: { flex: 1 },
});
