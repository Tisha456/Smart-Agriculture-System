import React from 'react';
import { StyleSheet, Text, View } from 'react-native';
import { colors, fontMono, spacing } from '../theme/tokens';
import { PumpControl } from './PumpControl';
import { AutomationControl } from './AutomationControl';
import { TimerControl } from './TimerControl';
import { ForceStop } from './ForceStop';
import type { useDeviceControls } from '../hooks/useDeviceControls';

interface ControlsPanelProps {
  controls: ReturnType<typeof useDeviceControls>;
  hasDevice: boolean;
}

export function ControlsPanel({ controls, hasDevice }: ControlsPanelProps) {
  const disabled = !hasDevice || controls.commandPending;

  return (
    <View style={styles.wrap}>
      <Text style={styles.heading}>CONTROLS</Text>

      <PumpControl
        pumpState={controls.pumpState}
        commandPending={controls.commandPending}
        disabled={disabled}
        onTurnOn={controls.turnPumpOn}
        onTurnOff={controls.turnPumpOff}
      />

      <AutomationControl
        mode={controls.automationMode}
        commandPending={controls.commandPending}
        disabled={disabled}
        onChange={controls.setAutomationMode}
      />

      <TimerControl
        timers={controls.timers}
        disabled={!hasDevice}
        onCreate={controls.createTimer}
        onUpdate={controls.updateTimer}
        onDelete={controls.deleteTimer}
        onToggle={controls.toggleTimer}
      />

      <ForceStop
        commandPending={controls.commandPending}
        disabled={!hasDevice}
        onForceStop={controls.forceStop}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginTop: spacing.lg,
  },
  heading: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: '700',
    fontFamily: fontMono,
    letterSpacing: 1,
    marginBottom: spacing.lg,
    textAlign: 'center',
  },
});
