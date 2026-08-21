import { useCallback, useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';
import { claimDevice, unbindDevice } from '../lib/controls';
import { CLAIM_ERROR_MESSAGES, type Device } from '../lib/types';
import { useAuth } from './useAuth';

export const MAX_DEVICES = 4;

export function useDevices() {
  const { session } = useAuth();
  const [devices, setDevices] = useState<Device[]>([]);
  const [activeDeviceIndex, setActiveDeviceIndex] = useState(0);
  const [loading, setLoading] = useState(true);

  const fetchDevices = useCallback(async () => {
    if (!session?.user?.id) {
      setDevices([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    try {
      // RLS ensures this only ever returns devices owned by the logged-in user.
      const { data, error } = await supabase
        .from('devices')
        .select('*')
        .eq('user_id', session.user.id);
      if (error) throw error;

      const mapped: Device[] = (data ?? []).map((d: any) => ({
        id: d.device_id,
        name: d.device_name || d.device_id,
        sector: d.sector || 'Active Field Sector',
        boundAt: d.created_at ? String(d.created_at).split('T')[0] : 'Today',
      }));
      setDevices(mapped);
      setActiveDeviceIndex((prev) => (prev >= mapped.length ? 0 : prev));
    } finally {
      setLoading(false);
    }
  }, [session?.user?.id]);

  useEffect(() => {
    fetchDevices();
  }, [fetchDevices]);

  const pair = useCallback(
    async (deviceId: string, secret: string, name: string) => {
      if (devices.length >= MAX_DEVICES) {
        throw new Error(`Maximum limit of ${MAX_DEVICES} devices reached per account. Unbind a node first.`);
      }
      const data = await claimDevice({
        deviceId: deviceId.toUpperCase(),
        secret,
        name: name || `Node ${devices.length + 1}`,
        sector: name || `Node ${devices.length + 1}`,
      });
      if (!data?.ok) {
        const code = data?.code ?? 'UNKNOWN_DEVICE';
        throw new Error(CLAIM_ERROR_MESSAGES[code] || `Pairing failed (${code}).`);
      }
      await fetchDevices();
    },
    [devices.length, fetchDevices]
  );

  const unbind = useCallback(
    async (deviceId: string) => {
      if (!session?.user?.id) return;
      await unbindDevice(deviceId, session.user.id);
      await fetchDevices();
    },
    [session?.user?.id, fetchDevices]
  );

  return {
    devices,
    activeDevice: devices[activeDeviceIndex] ?? null,
    activeDeviceIndex,
    setActiveDeviceIndex,
    loading,
    fetchDevices,
    pair,
    unbind,
  };
}
