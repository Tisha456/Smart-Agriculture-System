import React, { useState } from 'react';
import {
  Alert,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fontMono, radius, spacing } from '../../theme/tokens';
import { Card } from '../../components/Card';
import { Field } from '../../components/Field';
import { Button } from '../../components/Button';
import { ComingSoon } from '../../components/ComingSoon';

const SUGGESTED_QUESTIONS = [
  'Why is my soil moisture dropping fast?',
  'Should I water before the forecasted rain?',
  'What does a high humidity + dry soil reading mean?',
];

// Swap this out for the real reasoning-assistant / LLM call when it ships —
// nothing else on this screen needs to change.
function askAssistant() {
  Alert.alert('AI model in training', 'The AgriSense reasoning assistant is not connected yet.');
}

export default function AdvisorScreen() {
  const [draft, setDraft] = useState('');

  return (
    <SafeAreaView style={styles.flex} edges={['top']}>
      <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <ScrollView contentContainerStyle={styles.scroll}>
          <Text style={styles.title}>Advisor</Text>
          <Text style={styles.subtitle}>Ask the AgriSense assistant about your farm.</Text>

          <Card style={styles.conversationCard}>
            <ComingSoon label="AI MODEL IN TRAINING" />
            <Text style={styles.emptyHint}>
              Once connected, this assistant will reason over your live telemetry and farm history to
              answer questions directly here.
            </Text>
          </Card>

          <Text style={styles.sectionTitle}>SUGGESTED QUESTIONS</Text>
          {SUGGESTED_QUESTIONS.map((q) => (
            <View key={q} style={styles.suggestion} onTouchEnd={askAssistant}>
              <Text style={styles.suggestionText}>{q}</Text>
            </View>
          ))}
        </ScrollView>

        <View style={styles.inputBar}>
          <Field
            label=""
            style={styles.input}
            placeholder="Ask about your farm..."
            value={draft}
            onChangeText={setDraft}
          />
          <Button label="SEND" onPress={askAssistant} style={styles.sendButton} />
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bgMain },
  scroll: { padding: spacing.lg, paddingBottom: spacing.lg },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: '800' },
  subtitle: { color: colors.textSecondary, fontSize: 12, marginTop: spacing.xs, marginBottom: spacing.lg },
  conversationCard: { alignItems: 'center', gap: spacing.md, marginBottom: spacing.lg, minHeight: 160, justifyContent: 'center' },
  emptyHint: { color: colors.textMuted, fontSize: 12, textAlign: 'center', lineHeight: 18 },
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
    padding: spacing.lg,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    alignItems: 'flex-end',
  },
  input: { flex: 1, marginBottom: 0 },
  sendButton: { flex: 0, paddingHorizontal: spacing.lg, minWidth: 80 },
});
