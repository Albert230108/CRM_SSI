import { useLayoutEffect, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { useHeaderHeight } from '@react-navigation/elements'
import type { NativeStackScreenProps } from '@react-navigation/native-stack'

import type { TenantsStackParamList } from '../navigation/types'
import type { BrainEntry } from '../api/brain'
import {
  useCreateBrainEntry,
  useDeleteBrainEntry,
  useTenantBrain,
} from '../hooks/useTenantDetail'

type Props = NativeStackScreenProps<TenantsStackParamList, 'Brain'>

/**
 * Per-tenant "brain" (structured memory) editor, opened from the chat header dropdown. Lists the
 * entries newest-first with a persistent composer to add more; entries are removed with a confirm.
 */
export function BrainScreen({ navigation, route }: Props) {
  const { tenantId, tenantName } = route.params
  const brain = useTenantBrain(tenantId)
  const create = useCreateBrainEntry(tenantId)
  const remove = useDeleteBrainEntry(tenantId)

  const [draft, setDraft] = useState('')
  const headerHeight = useHeaderHeight()

  useLayoutEffect(() => {
    // The tenant name isn't on the brain payload, so the title uses the route param.
    navigation.setOptions({ title: tenantName ? `${tenantName} · Brain` : 'Brain' })
  }, [navigation, tenantName])

  const onAdd = () => {
    const content = draft.trim()
    if (!content) return
    create.mutate(content, {
      onSuccess: () => setDraft(''),
      onError: () => Alert.alert('Not added', 'Could not add the brain entry. Please try again.'),
    })
  }

  const onDelete = (entry: BrainEntry) => {
    Alert.alert('Delete entry', 'Remove this brain entry?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Delete',
        style: 'destructive',
        onPress: () =>
          remove.mutate(entry.id, {
            onError: () => Alert.alert('Not deleted', 'Please try again.'),
          }),
      },
    ])
  }

  const renderItem = ({ item }: { item: BrainEntry }) => (
    <View style={styles.row}>
      <Text style={styles.entryText}>{item.content}</Text>
      <TouchableOpacity onPress={() => onDelete(item)} hitSlop={8}>
        <Text style={styles.delete}>✕</Text>
      </TouchableOpacity>
    </View>
  )

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right', 'bottom']}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior="padding"
        keyboardVerticalOffset={headerHeight}
      >
        {brain.isLoading ? (
          <View style={styles.center}>
            <ActivityIndicator color="#2563eb" size="large" />
          </View>
        ) : brain.isError ? (
          <View style={styles.center}>
            <Text style={styles.errorText}>Couldn’t load brain entries.</Text>
            <TouchableOpacity onPress={() => void brain.refetch()}>
              <Text style={styles.retry}>Retry</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <FlatList
            data={brain.data ?? []}
            keyExtractor={(e) => String(e.id)}
            renderItem={renderItem}
            ItemSeparatorComponent={() => <View style={styles.separator} />}
            contentContainerStyle={styles.listContent}
            refreshControl={
              <RefreshControl refreshing={brain.isRefetching} onRefresh={() => void brain.refetch()} />
            }
            ListEmptyComponent={
              <View style={styles.center}>
                <Text style={styles.muted}>No brain entries yet.</Text>
              </View>
            }
          />
        )}

        <View style={styles.composer}>
          <TextInput
            style={styles.input}
            value={draft}
            onChangeText={setDraft}
            multiline
            placeholder="New brain entry…"
            editable={!create.isPending}
          />
          <TouchableOpacity
            style={[styles.addButton, (!draft.trim() || create.isPending) && styles.addButtonDisabled]}
            onPress={onAdd}
            disabled={!draft.trim() || create.isPending}
          >
            {create.isPending ? (
              <ActivityIndicator color="#fff" size="small" />
            ) : (
              <Text style={styles.addText}>Add</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f3f4f6' },
  flex: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  listContent: { padding: 12, flexGrow: 1 },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 8,
    backgroundColor: '#fff',
    borderRadius: 10,
    padding: 12,
  },
  entryText: { fontSize: 14, color: '#374151', flexShrink: 1, lineHeight: 20 },
  delete: { color: '#9ca3af', fontSize: 16, paddingHorizontal: 4 },
  separator: { height: 8 },
  muted: { color: '#9ca3af', fontSize: 14 },
  errorText: { color: '#dc2626', fontSize: 15 },
  retry: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
  composer: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    gap: 8,
    padding: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e5e7eb',
    backgroundColor: '#fff',
  },
  input: {
    flex: 1,
    maxHeight: 120,
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 18,
    paddingHorizontal: 14,
    paddingVertical: 8,
    fontSize: 16,
  },
  addButton: {
    backgroundColor: '#2563eb',
    borderRadius: 18,
    paddingHorizontal: 18,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addButtonDisabled: { opacity: 0.5 },
  addText: { color: '#fff', fontWeight: '600', fontSize: 15 },
})
