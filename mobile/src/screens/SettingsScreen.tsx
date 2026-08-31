import { StyleSheet, Text, TouchableOpacity, View } from 'react-native'

import { useAuthStore } from '../store/authStore'

/**
 * Minimal Settings tab: shows who is signed in and offers logout. Enough to close the auth
 * loop in Phase 0; broader settings are deferred (see docs/android-mobile-app-plan.md Phase 3).
 */
export function SettingsScreen() {
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)

  return (
    <View style={styles.container}>
      <View style={styles.info}>
        <Text style={styles.label}>Signed in as</Text>
        <Text style={styles.value}>{user?.full_name ?? user?.email ?? 'Unknown user'}</Text>
        {user?.email ? <Text style={styles.sub}>{user.email}</Text> : null}
      </View>

      <TouchableOpacity style={styles.logout} onPress={() => void logout()}>
        <Text style={styles.logoutText}>Log out</Text>
      </TouchableOpacity>
    </View>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, justifyContent: 'space-between' },
  info: { gap: 4, marginTop: 16 },
  label: { fontSize: 13, color: '#6b7280' },
  value: { fontSize: 18, fontWeight: '600' },
  sub: { fontSize: 14, color: '#6b7280' },
  logout: {
    borderWidth: 1,
    borderColor: '#dc2626',
    borderRadius: 8,
    paddingVertical: 14,
    alignItems: 'center',
  },
  logoutText: { color: '#dc2626', fontSize: 16, fontWeight: '600' },
})
