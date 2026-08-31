import { useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  FlatList,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { AxiosError } from 'axios'

import type { ActionItem } from '../api/actions'
import {
  useActionItems,
  useCompleteAction,
  useDismissAction,
  useQuickAddAction,
  useReopenAction,
} from '../hooks/useActionItems'
import { navigateToThread } from '../navigation/navigationRef'
import { formatDate } from '../lib/format'

function errorDetail(err: unknown, fallback: string): string {
  const detail =
    err instanceof AxiosError
      ? (err.response?.data as { detail?: string } | undefined)?.detail
      : undefined
  return detail ?? fallback
}

function isDone(status: string): boolean {
  return status === 'done' || status === 'dismissed'
}

/** Global action-items board: quick-add (NL parse), complete/reopen/dismiss, open the tenant. */
export function ActionsScreen() {
  const { data, isLoading, isError, refetch, isRefetching } = useActionItems('')
  const quickAdd = useQuickAddAction()
  const complete = useCompleteAction()
  const dismiss = useDismissAction()
  const reopen = useReopenAction()

  const [text, setText] = useState('')

  const busy = complete.isPending || dismiss.isPending || reopen.isPending

  const onQuickAdd = () => {
    const value = text.trim()
    if (!value) return
    quickAdd.mutate(value, {
      onSuccess: () => setText(''),
      onError: (err) => Alert.alert('Not added', errorDetail(err, 'Could not add the task.')),
    })
  }

  const run = (p: Promise<unknown>, failMsg: string) => {
    p.catch((err) => Alert.alert('Action failed', errorDetail(err, failMsg)))
  }

  const renderItem = ({ item }: { item: ActionItem }) => {
    const done = isDone(item.status)
    return (
      <View style={styles.row}>
        <TouchableOpacity
          style={styles.checkbox}
          disabled={busy}
          onPress={() =>
            done
              ? run(reopen.mutateAsync(item.id), 'Could not reopen.')
              : run(complete.mutateAsync(item.id), 'Could not complete.')
          }
          hitSlop={8}
        >
          <Text style={styles.checkboxMark}>{done ? '☑' : '☐'}</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={styles.rowBody}
          disabled={item.tenant_id === null}
          onPress={() =>
            item.tenant_id !== null &&
            navigateToThread(item.tenant_id, item.tenant_name ?? undefined)
          }
        >
          <Text style={[styles.title, done && styles.titleDone]} numberOfLines={2}>
            {item.title}
          </Text>
          <View style={styles.metaRow}>
            {item.tenant_name ? <Text style={styles.metaTenant}>{item.tenant_name}</Text> : null}
            {item.due_date ? <Text style={styles.metaDue}>{formatDate(item.due_date)}</Text> : null}
            {item.priority ? (
              <Text style={[styles.metaTag, styles.priority]}>{item.priority}</Text>
            ) : null}
            {item.tags.map((tag) => (
              <Text key={tag.id} style={styles.metaTag}>
                {tag.name}
              </Text>
            ))}
          </View>
        </TouchableOpacity>
        {!done ? (
          <TouchableOpacity onPress={() => run(dismiss.mutateAsync(item.id), 'Could not dismiss.')} disabled={busy} hitSlop={8}>
            <Text style={styles.dismiss}>✕</Text>
          </TouchableOpacity>
        ) : null}
      </View>
    )
  }

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Actions</Text>
      </View>
      <View style={styles.addRow}>
        <TextInput
          style={styles.addInput}
          placeholder="Add a task… (e.g. call John tomorrow)"
          value={text}
          onChangeText={setText}
          editable={!quickAdd.isPending}
          onSubmitEditing={onQuickAdd}
          returnKeyType="done"
        />
        <TouchableOpacity
          style={[styles.addButton, (!text.trim() || quickAdd.isPending) && styles.addButtonDisabled]}
          onPress={onQuickAdd}
          disabled={!text.trim() || quickAdd.isPending}
        >
          {quickAdd.isPending ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Text style={styles.addButtonText}>Add</Text>
          )}
        </TouchableOpacity>
      </View>

      {isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#2563eb" />
        </View>
      ) : isError ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>Couldn’t load tasks.</Text>
          <TouchableOpacity onPress={() => void refetch()}>
            <Text style={styles.retry}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={data}
          keyExtractor={(i) => String(i.id)}
          renderItem={renderItem}
          ItemSeparatorComponent={() => <View style={styles.separator} />}
          onRefresh={() => void refetch()}
          refreshing={isRefetching}
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.muted}>No tasks yet.</Text>
            </View>
          }
        />
      )}
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#fff' },
  header: {
    padding: 12,
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#e5e7eb',
  },
  headerTitle: { fontSize: 18, fontWeight: '700', textAlign: 'center', color: '#111827' },
  addRow: { flexDirection: 'row', gap: 8, padding: 12, alignItems: 'center' },
  addInput: {
    flex: 1,
    backgroundColor: '#f3f4f6',
    borderRadius: 10,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 15,
  },
  addButton: {
    backgroundColor: '#2563eb',
    borderRadius: 10,
    paddingHorizontal: 16,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  addButtonDisabled: { opacity: 0.5 },
  addButtonText: { color: '#fff', fontWeight: '600' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  row: { flexDirection: 'row', alignItems: 'flex-start', gap: 10, paddingHorizontal: 12, paddingVertical: 12 },
  checkbox: { paddingTop: 1 },
  checkboxMark: { fontSize: 20, color: '#2563eb' },
  rowBody: { flex: 1, gap: 4 },
  title: { fontSize: 15, color: '#111827', fontWeight: '500' },
  titleDone: { color: '#9ca3af', textDecorationLine: 'line-through' },
  metaRow: { flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 6 },
  metaTenant: { fontSize: 12, color: '#2563eb', fontWeight: '600' },
  metaDue: { fontSize: 12, color: '#6b7280' },
  metaTag: {
    fontSize: 11,
    color: '#4b5563',
    backgroundColor: '#f3f4f6',
    paddingHorizontal: 6,
    paddingVertical: 1,
    borderRadius: 6,
    overflow: 'hidden',
  },
  priority: { color: '#b45309', backgroundColor: '#fef3c7' },
  dismiss: { fontSize: 16, color: '#9ca3af', paddingHorizontal: 4 },
  separator: { height: StyleSheet.hairlineWidth, backgroundColor: '#e5e7eb', marginLeft: 44 },
  muted: { color: '#9ca3af', fontSize: 14 },
  errorText: { color: '#dc2626', fontSize: 15 },
  retry: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
})
