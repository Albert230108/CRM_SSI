import { useLayoutEffect } from 'react'
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import type { NativeStackScreenProps } from '@react-navigation/native-stack'

import type { NotificationsStackParamList } from '../navigation/types'
import type { NotificationRead } from '../api/notifications'
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotifications,
} from '../hooks/useNotifications'
import { formatListTime, oneLine } from '../lib/format'

type Props = NativeStackScreenProps<NotificationsStackParamList, 'NotificationsList'>

export function NotificationsScreen({ navigation }: Props) {
  const { data: notifications, isLoading, isError, refetch, isRefetching } = useNotifications()
  const markRead = useMarkNotificationRead()
  const markAll = useMarkAllNotificationsRead()

  useLayoutEffect(() => {
    navigation.setOptions({
      headerRight: () => (
        <TouchableOpacity onPress={() => markAll.mutate()} disabled={markAll.isPending}>
          <Text style={[styles.markAll, markAll.isPending && styles.dim]}>Mark all read</Text>
        </TouchableOpacity>
      ),
    })
  }, [navigation, markAll])

  const onPressNotification = (item: NotificationRead) => {
    if (!item.is_read) markRead.mutate(item.id)
    if (item.tenant_id != null) {
      navigation.navigate('Thread', {
        tenantId: item.tenant_id,
        tenantName: item.tenant_name ?? undefined,
      })
    }
  }

  const renderItem = ({ item }: { item: NotificationRead }) => (
    <TouchableOpacity style={styles.row} onPress={() => onPressNotification(item)}>
      <View style={[styles.dot, item.is_read ? styles.dotRead : styles.dotUnread]} />
      <View style={styles.rowBody}>
        <View style={styles.rowTop}>
          <Text style={[styles.title, !item.is_read && styles.titleUnread]} numberOfLines={1}>
            {item.tenant_name ?? 'Notification'}
          </Text>
          <Text style={styles.time}>{formatListTime(item.event_at)}</Text>
        </View>
        <Text style={styles.preview} numberOfLines={2}>
          <Text style={styles.channel}>
            {item.channel} · {item.direction}
          </Text>
          {item.preview ? `  ${oneLine(item.preview, 140)}` : ''}
        </Text>
      </View>
    </TouchableOpacity>
  )

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right']}>
      {isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#2563eb" />
        </View>
      ) : isError ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>Couldn’t load notifications.</Text>
          <TouchableOpacity onPress={() => void refetch()}>
            <Text style={styles.retry}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={notifications}
          keyExtractor={(n) => String(n.id)}
          renderItem={renderItem}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          refreshControl={
            <RefreshControl refreshing={isRefetching} onRefresh={() => void refetch()} />
          }
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.preview}>You’re all caught up.</Text>
            </View>
          }
          contentContainerStyle={
            notifications && notifications.length === 0 ? styles.emptyContent : undefined
          }
        />
      )}
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  emptyContent: { flexGrow: 1 },
  row: { flexDirection: 'row', paddingHorizontal: 12, paddingVertical: 12, gap: 10 },
  dot: { width: 10, height: 10, borderRadius: 5, marginTop: 5 },
  dotUnread: { backgroundColor: '#2563eb' },
  dotRead: { backgroundColor: 'transparent' },
  rowBody: { flex: 1, gap: 3 },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  title: { fontSize: 15, fontWeight: '500', color: '#374151', flexShrink: 1 },
  titleUnread: { fontWeight: '700', color: '#111827' },
  time: { fontSize: 12, color: '#9ca3af' },
  preview: { fontSize: 13, color: '#6b7280' },
  channel: { fontSize: 12, color: '#9ca3af', textTransform: 'capitalize' },
  separator: { height: StyleSheet.hairlineWidth, backgroundColor: '#e5e7eb', marginLeft: 32 },
  errorText: { color: '#dc2626', fontSize: 15 },
  retry: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
  markAll: { color: '#2563eb', fontSize: 14, fontWeight: '600' },
  dim: { opacity: 0.5 },
})
