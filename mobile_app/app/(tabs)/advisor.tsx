import React, { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLocalSearchParams, useRouter } from 'expo-router';
import Feather from '@expo/vector-icons/Feather';
import { colors, fontMono, radius, spacing } from '../../theme/tokens';
import { useAuth } from '../../hooks/useAuth';
import { useDevices } from '../../hooks/useDevices';
import { askAdvisor } from '../../lib/advisor';
import type { ChatMessage } from '../../lib/types';

const SUGGESTED_QUESTIONS = [
  'Why is my soil moisture dropping fast?',
  'Should I water before the forecasted rain?',
  'What does a high humidity + dry soil reading mean?',
];

export default function AdvisorScreen() {
  const { session } = useAuth();
  const { activeDevice } = useDevices();
  const router = useRouter();
  const { prefill } = useLocalSearchParams<{ prefill?: string }>();
  const scrollRef = useRef<ScrollView>(null);

  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sending, setSending] = useState(false);

  // Scan screen hands off a diagnosis via a route param — prefill it into the
  // input so the user can edit before sending, then clear it so navigating
  // back to this tab later doesn't re-inject the same stale diagnosis.
  useEffect(() => {
    if (prefill) {
      setDraft(prefill);
      router.setParams({ prefill: undefined });
    }
  }, [prefill]);

  async function send(question: string) {
    const trimmed = question.trim();
    if (!trimmed || sending) return;
    if (!session) {
      Alert.alert('Not signed in', 'Please sign in again to use the advisor.');
      return;
    }

    const userMsg: ChatMessage = { id: `${Date.now()}-u`, role: 'user', text: trimmed };
    setMessages((prev) => [...prev, userMsg]);
    setDraft('');
    setSending(true);
    try {
      const answer = await askAdvisor(
        trimmed,
        activeDevice?.id ?? null,
        messages,
        session.access_token
      );
      setMessages((prev) => [...prev, { id: `${Date.now()}-a`, role: 'assistant', text: answer }]);
    } catch (err: any) {
      Alert.alert('Advisor failed', err?.message || 'Something went wrong.');
      setMessages((prev) => prev.filter((m) => m.id !== userMsg.id));
      setDraft(trimmed);
    } finally {
      setSending(false);
    }
  }

  const canSend = draft.trim().length > 0 && !sending;

  return (
    <SafeAreaView style={styles.flex} edges={['top']}>
      <View style={styles.header}>
        <Text style={styles.title}>Advisor</Text>
        <Text style={styles.subtitle}>Ask the AgriSense assistant about your farm.</Text>
      </View>

      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 8 : 0}
      >
        <ScrollView
          ref={scrollRef}
          style={styles.messages}
          contentContainerStyle={styles.messagesContent}
          onContentSizeChange={() => scrollRef.current?.scrollToEnd({ animated: true })}
        >
          {messages.length === 0 ? (
            <>
              <Text style={styles.emptyHint}>
                Ask a question below — the assistant reasons over your live telemetry when a device
                is selected.
              </Text>
              <Text style={styles.sectionTitle}>SUGGESTED QUESTIONS</Text>
              {SUGGESTED_QUESTIONS.map((q) => (
                <Pressable key={q} style={styles.suggestion} onPress={() => send(q)}>
                  <Text style={styles.suggestionText}>{q}</Text>
                </Pressable>
              ))}
            </>
          ) : (
            messages.map((m) => (
              <View
                key={m.id}
                style={[styles.bubble, m.role === 'user' ? styles.bubbleUser : styles.bubbleAssistant]}
              >
                <Text style={m.role === 'user' ? styles.bubbleTextUser : styles.bubbleTextAssistant}>
                  {m.text}
                </Text>
              </View>
            ))
          )}
          {sending ? <Text style={styles.emptyHint}>Thinking…</Text> : null}
        </ScrollView>

        <View style={styles.inputBar}>
          <View style={styles.inputWrap}>
            <TextInput
              style={styles.input}
              placeholder="Ask about your farm..."
              placeholderTextColor={colors.textMuted}
              value={draft}
              onChangeText={setDraft}
              multiline
            />
          </View>
          <Pressable
            onPress={() => send(draft)}
            disabled={!canSend}
            style={[styles.sendBtn, !canSend && styles.sendBtnDisabled]}
          >
            {sending ? (
              <ActivityIndicator size="small" color="#04120b" />
            ) : (
              <Feather name="send" size={18} color={canSend ? '#04120b' : colors.textMuted} />
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bgMain },
  header: { paddingHorizontal: spacing.lg, paddingTop: spacing.sm, paddingBottom: spacing.sm },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: '800' },
  subtitle: { color: colors.textSecondary, fontSize: 12, marginTop: spacing.xs },
  messages: { flex: 1 },
  messagesContent: { padding: spacing.lg, paddingTop: spacing.sm, gap: spacing.sm, flexGrow: 1 },
  emptyHint: { color: colors.textMuted, fontSize: 12, textAlign: 'center', lineHeight: 18, marginBottom: spacing.md },
  bubble: { borderRadius: radius.md, padding: spacing.md, maxWidth: '85%' },
  bubbleUser: { backgroundColor: colors.green, alignSelf: 'flex-end' },
  bubbleAssistant: { backgroundColor: colors.bgSubtle, alignSelf: 'flex-start' },
  bubbleTextUser: { color: '#04120b', fontSize: 13, lineHeight: 18 },
  bubbleTextAssistant: { color: colors.textPrimary, fontSize: 13, lineHeight: 18 },
  sectionTitle: { color: colors.textSecondary, fontSize: 12, fontFamily: fontMono, letterSpacing: 1, marginBottom: spacing.sm },
  suggestion: {
    backgroundColor: colors.bgCard,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: radius.md,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  suggestionText: { color: colors.textPrimary, fontSize: 13 },
  inputBar: {
    flexDirection: 'row',
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    alignItems: 'flex-end',
  },
  inputWrap: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    justifyContent: 'center',
    backgroundColor: colors.bgInput,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 22,
    paddingHorizontal: spacing.md,
  },
  input: {
    color: colors.textPrimary,
    fontFamily: fontMono,
    fontSize: 14,
    paddingVertical: spacing.sm,
    maxHeight: 96,
  },
  sendBtn: {
    width: 44,
    height: 44,
    borderRadius: radius.full,
    backgroundColor: colors.green,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendBtnDisabled: { backgroundColor: colors.bgSubtle },
});
