import { useState } from 'react'
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import type { NativeStackScreenProps } from '@react-navigation/native-stack'

import type { TenantsStackParamList } from '../navigation/types'
import type { TenantRead } from '../api/tenants'
import { useTenants } from '../hooks/useTenants'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { formatListTime, initials } from '../lib/format'

type Props = NativeStackScreenProps<TenantsStackParamList, 'TenantList'>

export function TenantListScreen({ navigation }: Props) {
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search, 300)
  const { data: tenants, isLoading, isError, refetch, isRefetching } = useTenants(debouncedSearch)

  const renderItem = ({ item }: { item: TenantRead }) => {
    const subtitleParts = [item.booking_status, item.room_name ?? item.property_name].filter(
      Boolean,
    )
    return (
      <TouchableOpacity
        style={styles.row}
        onPress={() => navigation.navigate('Thread', { tenantId: item.id, tenantName: item.name })}
      >
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initials(item.name)}</Text>
        </View>
        <View style={styles.rowBody}>
          <View style={styles.rowTop}>
            <Text style={styles.name} numberOfLines={1}>
              {item.name}
            </Text>
            <Text style={styles.time}>{formatListTime(item.last_message_date)}</Text>
          </View>
          <View style={styles.rowBottom}>
            <Text style={styles.subtitle} numberOfLines={1}>
              {subtitleParts.join(' · ') || item.booking_id}
            </Text>
            {item.unread_count > 0 ? (
              <View style={styles.badge}>
                <Text style={styles.badgeText}>{item.unread_count}</Text>
              </View>
            ) : null}
          </View>
        </View>
      </TouchableOpacity>
    )
  }

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      <View style={styles.searchWrap}>
        <TextInput
          style={styles.search}
          placeholder="Search tenants"
          autoCapitalize="none"
          autoCorrect={false}
          value={search}
          onChangeText={setSearch}
          clearButtonMode="while-editing"
        />
      </View>

      {isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#2563eb" />
        </View>
      ) : isError ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>Couldn’t load tenants.</Text>
          <TouchableOpacity onPress={() => void refetch()}>
            <Text style={styles.retry}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={tenants}
          keyExtractor={(t) => String(t.id)}
          renderItem={renderItem}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          refreshControl={
            <RefreshControl refreshing={isRefetching} onRefresh={() => void refetch()} />
          }
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.subtitle}>No tenants found.</Text>
            </View>
          }
          contentContainerStyle={tenants && tenants.length === 0 ? styles.emptyContent : undefined}
        />
      )}
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  searchWrap: { padding: 12, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: '#e5e7eb' },
  search: {
    backgroundColor: '#f3f4f6',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 16,
  },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  emptyContent: { flexGrow: 1 },
  row: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 12, paddingVertical: 12, gap: 12 },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: '#dbeafe',
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: { color: '#1d4ed8', fontWeight: '700' },
  rowBody: { flex: 1, gap: 4 },
  rowTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  rowBottom: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  name: { fontSize: 16, fontWeight: '600', flexShrink: 1 },
  time: { fontSize: 12, color: '#9ca3af' },
  subtitle: { fontSize: 14, color: '#6b7280', flexShrink: 1 },
  badge: {
    minWidth: 22,
    height: 22,
    borderRadius: 11,
    backgroundColor: '#2563eb',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 6,
  },
  badgeText: { color: '#fff', fontSize: 12, fontWeight: '700' },
  separator: { height: StyleSheet.hairlineWidth, backgroundColor: '#e5e7eb', marginLeft: 68 },
  errorText: { color: '#dc2626', fontSize: 15 },
  retry: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
})
