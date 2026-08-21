// Ported 1:1 from web_dashboard/styles.css :root — keep both in sync.
export const colors = {
  bgMain: '#0d1117',
  bgCard: '#161b22',
  bgCardHover: '#1c2128',
  bgInput: '#010409',
  bgSubtle: '#21262d',

  border: '#30363d',
  borderMuted: '#21262d',

  green: '#3ecf8e',
  amber: '#d29922',
  rose: '#f85149',
  blue: '#58a6ff',
  purple: '#a371f7',

  textPrimary: '#f0f6fc',
  textSecondary: '#8b949e',
  textMuted: '#6e7681',
} as const;

export const radius = {
  sm: 4,
  md: 6,
  lg: 10,
  full: 9999,
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const fontMono =
  'ui-monospace, SFMono-Regular, "JetBrains Mono", "SF Mono", Menlo, monospace';
export const fontSans =
  'System, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

// Connection-state colors — matches .val-offline / .val-nosensor / default in styles.css
export const connectionColors = {
  NO_DEVICE: colors.textMuted,
  OFFLINE: colors.textMuted,
  ONLINE_NO_SENSORS: colors.green,
  LIVE: colors.green,
} as const;
