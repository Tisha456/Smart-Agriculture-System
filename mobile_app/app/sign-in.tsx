import React, { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { colors, fontMono, radius, spacing } from '../theme/tokens';
import { Field } from '../components/Field';
import { Button } from '../components/Button';
import { useAuth } from '../hooks/useAuth';

export default function SignInScreen() {
  const { signIn, signUp } = useAuth();
  const [tab, setTab] = useState<'login' | 'signup'>('login');

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleLogin = async () => {
    setError(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
    } catch (err: any) {
      setError(err.message ?? 'Login failed');
    } finally {
      setBusy(false);
    }
  };

  const handleSignup = async () => {
    setError(null);
    setInfo(null);
    if (password !== confirm) {
      setError('Passwords do not match');
      return;
    }
    setBusy(true);
    try {
      await signUp(email.trim(), password);
      setInfo('Account created! Please sign in.');
      setTab('login');
    } catch (err: any) {
      setError(err.message ?? 'Signup failed');
    } finally {
      setBusy(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.flex}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Text style={styles.brand}>AgriSense</Text>
        <Text style={styles.tagline}>Smart Agriculture IoT</Text>

        <View style={styles.tabRow}>
          <Text
            style={[styles.tab, tab === 'login' && styles.tabActive]}
            onPress={() => setTab('login')}
          >
            Sign In
          </Text>
          <Text
            style={[styles.tab, tab === 'signup' && styles.tabActive]}
            onPress={() => setTab('signup')}
          >
            Create Account
          </Text>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}
        {info ? <Text style={styles.info}>{info}</Text> : null}

        <Field
          label="Email"
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
          placeholder="you@example.com"
        />
        <Field
          label="Password"
          value={password}
          onChangeText={setPassword}
          secureTextEntry
          placeholder="••••••••"
        />

        {tab === 'signup' ? (
          <Field
            label="Confirm Password"
            value={confirm}
            onChangeText={setConfirm}
            secureTextEntry
            placeholder="••••••••"
          />
        ) : null}

        <Button
          label={tab === 'login' ? 'SIGN IN' : 'CREATE ACCOUNT'}
          onPress={tab === 'login' ? handleLogin : handleSignup}
          loading={busy}
        />

        <Text style={styles.note}>
          Same email/password as the AgriSense web dashboard — your bound devices carry over automatically.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bgMain },
  scroll: { flexGrow: 1, justifyContent: 'center', padding: spacing.xl },
  brand: {
    color: colors.green,
    fontSize: 32,
    fontWeight: '800',
    textAlign: 'center',
  },
  tagline: {
    color: colors.textSecondary,
    fontSize: 13,
    textAlign: 'center',
    marginTop: spacing.xs,
    marginBottom: spacing.xxl,
  },
  tabRow: {
    flexDirection: 'row',
    backgroundColor: colors.bgSubtle,
    borderRadius: radius.md,
    padding: 4,
    marginBottom: spacing.lg,
  },
  tab: {
    flex: 1,
    textAlign: 'center',
    paddingVertical: spacing.sm,
    color: colors.textSecondary,
    fontFamily: fontMono,
    fontSize: 12,
    fontWeight: '700',
    borderRadius: radius.sm,
    overflow: 'hidden',
  },
  tabActive: {
    backgroundColor: colors.bgCard,
    color: colors.green,
  },
  error: {
    color: colors.rose,
    fontSize: 12,
    marginBottom: spacing.md,
    textAlign: 'center',
  },
  info: {
    color: colors.green,
    fontSize: 12,
    marginBottom: spacing.md,
    textAlign: 'center',
  },
  note: {
    color: colors.textMuted,
    fontSize: 11,
    textAlign: 'center',
    marginTop: spacing.xl,
    lineHeight: 16,
  },
});
