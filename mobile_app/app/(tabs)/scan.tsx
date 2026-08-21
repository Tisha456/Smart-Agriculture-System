import React from 'react';
import { Alert, ScrollView, StyleSheet, Text, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { colors, fontMono, radius, spacing } from '../../theme/tokens';
import { Card } from '../../components/Card';
import { Button } from '../../components/Button';
import { ComingSoon } from '../../components/ComingSoon';

// Swap this out for the real Plant Recognition / Disease Detection model
// call when it ships — nothing else on this screen needs to change.
function runInference() {
  Alert.alert('Model in training', 'Plant Scan inference is not connected yet.');
}

export default function ScanScreen() {
  return (
    <SafeAreaView style={styles.flex} edges={['top']}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>Plant Scan</Text>
        <Text style={styles.subtitle}>Identify plants and detect disease from a photo.</Text>

        <Card style={styles.previewCard}>
          <View style={styles.previewPlaceholder}>
            <Text style={styles.previewIcon}>🌿</Text>
            <Text style={styles.previewHint}>No image selected</Text>
          </View>
        </Card>

        <View style={styles.buttonRow}>
          <Button label="TAKE PHOTO" variant="secondary" onPress={runInference} style={styles.rowButton} />
          <Button label="CHOOSE FROM LIBRARY" variant="secondary" onPress={runInference} style={styles.rowButton} />
        </View>

        <Card style={styles.resultCard}>
          <Text style={styles.resultHeading}>Plant Identification</Text>
          <ComingSoon label="MODEL IN TRAINING" />
        </Card>

        <Card style={styles.resultCard}>
          <Text style={styles.resultHeading}>Disease Analysis</Text>
          <ComingSoon label="MODEL IN TRAINING" />
        </Card>
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: colors.bgMain },
  scroll: { padding: spacing.lg, paddingBottom: spacing.xxl },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: '800' },
  subtitle: { color: colors.textSecondary, fontSize: 12, marginTop: spacing.xs, marginBottom: spacing.lg },
  previewCard: { marginBottom: spacing.md, padding: 0, overflow: 'hidden' },
  previewPlaceholder: {
    height: 220,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.bgSubtle,
    borderRadius: radius.lg,
  },
  previewIcon: { fontSize: 40, marginBottom: spacing.sm },
  previewHint: { color: colors.textMuted, fontSize: 12, fontFamily: fontMono },
  buttonRow: { flexDirection: 'row', gap: spacing.sm, marginBottom: spacing.lg },
  rowButton: { flex: 1 },
  resultCard: { alignItems: 'center', marginBottom: spacing.md, gap: spacing.md },
  resultHeading: {
    color: colors.textPrimary,
    fontSize: 13,
    fontWeight: '700',
    fontFamily: fontMono,
    alignSelf: 'flex-start',
    marginBottom: spacing.sm,
  },
});
