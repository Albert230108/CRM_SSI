import { useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { AxiosError } from 'axios'

import type { AiAutoDraft } from '../api/aiDrafts'
import {
  useAiDrafts,
  useCancelDraftAutoSend,
  useDismissDraft,
  useMarkDraftUsed,
  useRedoDraft,
  useSendDraftNow,
} from '../hooks/useAiDrafts'
import { navigateToThread } from '../navigation/navigationRef'
import { formatBubbleTime } from '../lib/format'

function errorDetail(err: unknown, fallback: string): string {
  const detail =
    err instanceof AxiosError
      ? (err.response?.data as { detail?: string } | undefined)?.detail
      : undefined
  return detail ?? fallback
}

/** Queue of AI-generated reply drafts awaiting a human decision (send / dismiss / redo / seed). */
export function AiDraftsScreen() {
  const { data, isLoading, isError, refetch, isRefetching } = useAiDrafts()
  const sendNow = useSendDraftNow()
  const dismiss = useDismissDraft()
  const cancelAutoSend = useCancelDraftAutoSend()
  const markUsed = useMarkDraftUsed()
  const redo = useRedoDraft()

  const [redoId, setRedoId] = useState<number | null>(null)
  const [redoWhat, setRedoWhat] = useState('')

  const busy =
    sendNow.isPending ||
    dismiss.isPending ||
    cancelAutoSend.isPending ||
    markUsed.isPending ||
    redo.isPending

  const run = (p: Promise<unknown>, failMsg: string) => {
    p.catch((err) => Alert.alert('Action failed', errorDetail(err, failMsg)))
  }

  const submitRedo = () => {
    if (redoId === null) return
    const what = redoWhat.trim()
    if (!what) return
    redo.mutate(
      { id: redoId, what },
      {
        onSuccess: () => {
          setRedoId(null)
          setRedoWhat('')
        },
        onError: (err) => Alert.alert('Redo failed', errorDetail(err, 'Could not regenerate.')),
      },
    )
  }

  const renderItem = ({ item }: { item: AiAutoDraft }) => {
    const canCancelAutoSend =
      item.status === 'pending_auto_send' || item.scheduled_send_at !== null
    return (
      <View style={styles.card}>
        <TouchableOpacity
          disabled={busy}
          onPress={() => navigateToThread(item.tenant_id, item.tenant_name ?? undefined)}
        >
          <View style={styles.cardTop}>
            <Text style={styles.tenant} numberOfLines={1}>
              {item.tenant_name ?? `Tenant ${item.tenant_id}`}
            </Text>
            <Text style={styles.channel}>{item.channel}</Text>
          </View>
          <View style={styles.statusRow}>
            <Text style={styles.status}>{item.status.replace(/_/g, ' ')}</Text>
            <Text style={styles.time}>{formatBubbleTime(item.created_at)}</Text>
          </View>
          <Text style={styles.body} numberOfLines={6}>
            {item.formatted_text || item.generated_text}
          </Text>
        </TouchableOpacity>
        <View style={styles.actions}>
          <ActionLink label="Send now" onPress={() => run(sendNow.mutateAsync(item.id), 'Could not send.')} disabled={busy} />
          <ActionLink label="Redo" onPress={() => { setRedoId(item.id); setRedoWhat('') }} disabled={busy} />
          <ActionLink label="Seed" onPress={() => run(markUsed.mutateAsync(item.id), 'Could not mark used.')} disabled={busy} />
          {canCancelAutoSend ? (
            <ActionLink
              label="Stop auto-send"
              onPress={() => run(cancelAutoSend.mutateAsync(item.id), 'Could not cancel.')}
              disabled={busy}
            />
          ) : null}
          <ActionLink
            label="Dismiss"
            destructive
            onPress={() => run(dismiss.mutateAsync(item.id), 'Could not dismiss.')}
            disabled={busy}
          />
        </View>
      </View>
    )
  }

  return (
    <SafeAreaView style={styles.container} edges={['top', 'left', 'right']}>
      <View style={styles.header}>
        <Text style={styles.headerTitle}>AI Drafts</Text>
      </View>
      {isLoading ? (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#2563eb" />
        </View>
      ) : isError ? (
        <View style={styles.center}>
          <Text style={styles.errorText}>Couldn’t load AI drafts.</Text>
          <TouchableOpacity onPress={() => void refetch()}>
            <Text style={styles.retry}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={data}
          keyExtractor={(d) => String(d.id)}
          renderItem={renderItem}
          contentContainerStyle={styles.listContent}
          onRefresh={() => void refetch()}
          refreshing={isRefetching}
          ListEmptyComponent={
            <View style={styles.center}>
              <Text style={styles.muted}>No pending AI drafts.</Text>
            </View>
          }
        />
      )}

      <Modal
        visible={redoId !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setRedoId(null)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Redo draft</Text>
            <Text style={styles.muted}>Describe what to change.</Text>
            <TextInput
              style={styles.modalInput}
              placeholder="e.g. shorter, and confirm the check-in time"
              value={redoWhat}
              onChangeText={setRedoWhat}
              multiline
              editable={!redo.isPending}
            />
            <View style={styles.modalButtons}>
              <TouchableOpacity onPress={() => setRedoId(null)} disabled={redo.isPending}>
                <Text style={styles.actionMuted}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={submitRedo} disabled={redo.isPending || !redoWhat.trim()}>
                {redo.isPending ? (
                  <ActivityIndicator size="small" color="#2563eb" />
                ) : (
                  <Text style={styles.action}>Redo</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  )
}

function ActionLink({
  label,
  onPress,
  disabled,
  destructive,
}: {
  label: string
  onPress: () => void
  disabled?: boolean
  destructive?: boolean
}) {
  return (
    <TouchableOpacity onPress={onPress} disabled={disabled} hitSlop={6}>
      <Text style={[styles.actionLink, destructive && styles.actionLinkDestructive, disabled && styles.actionLinkDisabled]}>
        {label}
      </Text>
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f3f4f6' },
  header: {
    padding: 12,
    backgroundColor: '#fff',
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: '#e5e7eb',
  },
  headerTitle: { fontSize: 18, fontWeight: '700', textAlign: 'center', color: '#111827' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  listContent: { padding: 12, gap: 10 },
  card: { backgroundColor: '#fff', borderRadius: 12, padding: 14, gap: 6 },
  cardTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 8 },
  tenant: { fontSize: 15, fontWeight: '700', color: '#111827', flexShrink: 1 },
  channel: { fontSize: 11, fontWeight: '700', textTransform: 'uppercase', color: '#6b7280' },
  statusRow: { flexDirection: 'row', justifyContent: 'space-between' },
  status: { fontSize: 12, color: '#7c3aed', fontWeight: '600', textTransform: 'capitalize' },
  time: { fontSize: 11, color: '#9ca3af' },
  body: { fontSize: 14, color: '#374151', lineHeight: 20, marginTop: 2 },
  actions: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 16,
    marginTop: 6,
    paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#f3f4f6',
  },
  actionLink: { color: '#2563eb', fontWeight: '600', fontSize: 13 },
  actionLinkDestructive: { color: '#dc2626' },
  actionLinkDisabled: { opacity: 0.4 },
  muted: { color: '#9ca3af', fontSize: 14 },
  errorText: { color: '#dc2626', fontSize: 15 },
  retry: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
  action: { color: '#2563eb', fontWeight: '600', fontSize: 15 },
  actionMuted: { color: '#6b7280', fontWeight: '600', fontSize: 15 },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'center', padding: 24 },
  modalCard: { backgroundColor: '#fff', borderRadius: 14, padding: 16, gap: 8 },
  modalTitle: { fontSize: 16, fontWeight: '700', color: '#111827' },
  modalInput: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 10,
    padding: 10,
    fontSize: 15,
    minHeight: 70,
    textAlignVertical: 'top',
    marginTop: 4,
  },
  modalButtons: { flexDirection: 'row', justifyContent: 'flex-end', gap: 24, marginTop: 4 },
})
