import { StyleSheet, Text, View } from 'react-native'

/**
 * Shared placeholder for tabs whose real screens land in Phase 1 (tenant list / thread view)
 * and Phase 2 (notifications). Keeps the navigation shell demonstrable without pre-building UI.
 */
export function PlaceholderScreen({ title, note }: { title: string; note: string }) {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>{title}</Text>
      <Text style={styles.note}>{note}</Text>
    </View>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  title: { fontSize: 20, fontWeight: '700' },
  note: { fontSize: 14, color: '#6b7280', textAlign: 'center' },
})
