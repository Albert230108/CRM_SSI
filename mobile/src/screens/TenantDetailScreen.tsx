import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import type { NativeStackScreenProps } from '@react-navigation/native-stack'

import type { TenantsStackParamList } from '../navigation/types'
import type { FinanceLineItem } from '../api/finance'
import type { BrainEntry } from '../api/brain'
import { useTenant } from '../hooks/useTenants'
import {
  useCreateBrainEntry,
  useDeleteBrainEntry,
  useSaveNotes,
  useTenantBrain,
  useTenantFinance,
} from '../hooks/useTenantDetail'
import { formatDate, formatMoney } from '../lib/format'

type Props = NativeStackScreenProps<TenantsStackParamList, 'TenantDetail'>

/**
 * Tenant overview — the landing screen when a tenant is tapped (list → detail → thread). Mirrors
 * the web dashboard's centre column: booking header, finance, notes, brain, plus a prominent
 * "Open conversation" action into the thread. Sections degrade independently so one failing query
 * (e.g. finance) doesn't blank the whole screen.
 */
export function TenantDetailScreen({ navigation, route }: Props) {
  const { tenantId, tenantName } = route.params
  const tenant = useTenant(tenantId)
  const finance = useTenantFinance(tenantId)
  const brain = useTenantBrain(tenantId)

  useLayoutEffect(() => {
    navigation.setOptions({ title: tenant.data?.name ?? tenantName ?? 'Tenant' })
  }, [navigation, tenant.data?.name, tenantName])

  const onRefresh = () => {
    void tenant.refetch()
    void finance.refetch()
    void brain.refetch()
  }

  const t = tenant.data
  const refreshing = tenant.isRefetching || finance.isRefetching || brain.isRefetching

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right', 'bottom']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        {/* Booking header */}
        {tenant.isLoading ? (
          <ActivityIndicator style={{ marginVertical: 24 }} color="#2563eb" />
        ) : t ? (
          <View style={styles.card}>
            <Text style={styles.title}>{t.name}</Text>
            <Text style={styles.metaLine}>
              {[t.booking_status, t.booking_id].filter(Boolean).join(' · ')}
            </Text>
            {t.room_name || t.property_name ? (
              <Text style={styles.metaLine}>
                {[t.room_name, t.property_name].filter(Boolean).join(' · ')}
              </Text>
            ) : null}
            {t.check_in || t.check_out ? (
              <Text style={styles.metaLine}>
                {formatDate(t.check_in)} → {formatDate(t.check_out)}
              </Text>
            ) : null}
            {t.responsible_comm ? (
              <Text style={styles.metaLine}>Responsible: {t.responsible_comm}</Text>
            ) : null}
          </View>
        ) : (
          <SectionError label="tenant" onRetry={() => void tenant.refetch()} />
        )}

        {/* Open conversation */}
        <TouchableOpacity
          style={styles.threadButton}
          onPress={() => navigation.navigate('Thread', { tenantId, tenantName: t?.name })}
        >
          <Text style={styles.threadButtonText}>💬  Open conversation</Text>
        </TouchableOpacity>

        {/* Finance */}
        <FinanceSection
          loading={finance.isLoading}
          error={finance.isError}
          charges={finance.data?.charges ?? []}
          payments={finance.data?.payments ?? []}
          onRetry={() => void finance.refetch()}
        />

        {/* Notes */}
        <NotesSection tenantId={tenantId} notes={t?.notes ?? null} loading={tenant.isLoading} />

        {/* Brain */}
        <BrainSection
          tenantId={tenantId}
          loading={brain.isLoading}
          error={brain.isError}
          entries={brain.data ?? []}
          onRetry={() => void brain.refetch()}
        />
      </ScrollView>
    </SafeAreaView>
  )
}

function SectionError({ label, onRetry }: { label: string; onRetry: () => void }) {
  return (
    <View style={styles.card}>
      <Text style={styles.errorText}>Couldn’t load {label}.</Text>
      <TouchableOpacity onPress={onRetry}>
        <Text style={styles.retry}>Retry</Text>
      </TouchableOpacity>
    </View>
  )
}

function SectionHeader({ title, right }: { title: string; right?: React.ReactNode }) {
  return (
    <View style={styles.sectionHeader}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {right}
    </View>
  )
}

function FinanceSection({
  loading,
  error,
  charges,
  payments,
  onRetry,
}: {
  loading: boolean
  error: boolean
  charges: FinanceLineItem[]
  payments: FinanceLineItem[]
  onRetry: () => void
}) {
  if (error) return <SectionError label="finance" onRetry={onRetry} />
  const total = (items: FinanceLineItem[]) =>
    items.reduce((sum, i) => sum + (Number(i.amount) || 0), 0)
  const currency = charges[0]?.currency ?? payments[0]?.currency ?? null

  const renderRow = (item: FinanceLineItem) => (
    <View key={`${item.type}-${item.id}`} style={styles.financeRow}>
      <Text style={styles.financeDesc} numberOfLines={1}>
        {item.description || item.type}
      </Text>
      <Text style={styles.financeAmount}>{formatMoney(item.amount, item.currency)}</Text>
    </View>
  )

  return (
    <View style={styles.card}>
      <SectionHeader title="Finance" />
      {loading ? (
        <ActivityIndicator color="#2563eb" />
      ) : charges.length === 0 && payments.length === 0 ? (
        <Text style={styles.muted}>No charges or payments.</Text>
      ) : (
        <>
          {charges.length > 0 ? (
            <>
              <Text style={styles.financeGroupLabel}>Charges</Text>
              {charges.map(renderRow)}
              <View style={styles.financeTotalRow}>
                <Text style={styles.financeTotalLabel}>Total charges</Text>
                <Text style={styles.financeTotalValue}>{formatMoney(total(charges), currency)}</Text>
              </View>
            </>
          ) : null}
          {payments.length > 0 ? (
            <>
              <Text style={[styles.financeGroupLabel, { marginTop: 12 }]}>Payments</Text>
              {payments.map(renderRow)}
              <View style={styles.financeTotalRow}>
                <Text style={styles.financeTotalLabel}>Total payments</Text>
                <Text style={styles.financeTotalValue}>{formatMoney(total(payments), currency)}</Text>
              </View>
            </>
          ) : null}
        </>
      )}
    </View>
  )
}

function NotesSection({
  tenantId,
  notes,
  loading,
}: {
  tenantId: number
  notes: string | null
  loading: boolean
}) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(notes ?? '')
  const save = useSaveNotes(tenantId)

  // Keep the local editor in sync when the tenant (and thus its notes) loads/refreshes, but never
  // clobber an in-progress edit.
  useEffect(() => {
    if (!editing) setValue(notes ?? '')
  }, [notes, editing])

  const onSave = () => {
    save.mutate(value.trim() ? value : null, {
      onSuccess: () => setEditing(false),
      onError: () => Alert.alert('Notes not saved', 'Something went wrong. Please try again.'),
    })
  }

  return (
    <View style={styles.card}>
      <SectionHeader
        title="Notes"
        right={
          !editing ? (
            <TouchableOpacity onPress={() => setEditing(true)}>
              <Text style={styles.action}>Edit</Text>
            </TouchableOpacity>
          ) : null
        }
      />
      {loading ? (
        <ActivityIndicator color="#2563eb" />
      ) : editing ? (
        <>
          <TextInput
            style={styles.notesInput}
            value={value}
            onChangeText={setValue}
            multiline
            placeholder="Add notes…"
            editable={!save.isPending}
          />
          <View style={styles.notesButtons}>
            <TouchableOpacity
              onPress={() => {
                setValue(notes ?? '')
                setEditing(false)
              }}
              disabled={save.isPending}
            >
              <Text style={styles.actionMuted}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onSave} disabled={save.isPending}>
              {save.isPending ? (
                <ActivityIndicator color="#2563eb" size="small" />
              ) : (
                <Text style={styles.action}>Save</Text>
              )}
            </TouchableOpacity>
          </View>
        </>
      ) : notes?.trim() ? (
        <Text style={styles.notesText}>{notes}</Text>
      ) : (
        <Text style={styles.muted}>No notes yet.</Text>
      )}
    </View>
  )
}

function BrainSection({
  tenantId,
  loading,
  error,
  entries,
  onRetry,
}: {
  tenantId: number
  loading: boolean
  error: boolean
  entries: BrainEntry[]
  onRetry: () => void
}) {
  const [adding, setAdding] = useState(false)
  const [draft, setDraft] = useState('')
  const create = useCreateBrainEntry(tenantId)
  const remove = useDeleteBrainEntry(tenantId)
  const addRef = useRef<TextInput>(null)

  if (error) return <SectionError label="brain" onRetry={onRetry} />

  const onAdd = () => {
    const content = draft.trim()
    if (!content) return
    create.mutate(content, {
      onSuccess: () => {
        setDraft('')
        setAdding(false)
      },
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

  return (
    <View style={styles.card}>
      <SectionHeader
        title="Brain"
        right={
          !adding ? (
            <TouchableOpacity
              onPress={() => {
                setAdding(true)
                setTimeout(() => addRef.current?.focus(), 50)
              }}
            >
              <Text style={styles.action}>Add</Text>
            </TouchableOpacity>
          ) : null
        }
      />
      {adding ? (
        <>
          <TextInput
            ref={addRef}
            style={styles.notesInput}
            value={draft}
            onChangeText={setDraft}
            multiline
            placeholder="New brain entry…"
            editable={!create.isPending}
          />
          <View style={styles.notesButtons}>
            <TouchableOpacity
              onPress={() => {
                setDraft('')
                setAdding(false)
              }}
              disabled={create.isPending}
            >
              <Text style={styles.actionMuted}>Cancel</Text>
            </TouchableOpacity>
            <TouchableOpacity onPress={onAdd} disabled={create.isPending}>
              {create.isPending ? (
                <ActivityIndicator color="#2563eb" size="small" />
              ) : (
                <Text style={styles.action}>Add</Text>
              )}
            </TouchableOpacity>
          </View>
        </>
      ) : null}
      {loading ? (
        <ActivityIndicator color="#2563eb" />
      ) : entries.length === 0 && !adding ? (
        <Text style={styles.muted}>No brain entries yet.</Text>
      ) : (
        entries.map((entry) => (
          <View key={entry.id} style={styles.brainRow}>
            <Text style={styles.brainText}>{entry.content}</Text>
            <TouchableOpacity onPress={() => onDelete(entry)} hitSlop={8}>
              <Text style={styles.brainDelete}>✕</Text>
            </TouchableOpacity>
          </View>
        ))
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f3f4f6' },
  content: { padding: 12, gap: 12 },
  card: {
    backgroundColor: '#fff',
    borderRadius: 12,
    padding: 14,
    gap: 6,
  },
  title: { fontSize: 18, fontWeight: '700', color: '#111827' },
  metaLine: { fontSize: 13, color: '#6b7280' },
  threadButton: {
    backgroundColor: '#2563eb',
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
  },
  threadButtonText: { color: '#fff', fontWeight: '700', fontSize: 15 },
  sectionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 4,
  },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: '#111827' },
  action: { color: '#2563eb', fontWeight: '600', fontSize: 14 },
  actionMuted: { color: '#6b7280', fontWeight: '600', fontSize: 14 },
  muted: { color: '#9ca3af', fontSize: 14 },
  errorText: { color: '#dc2626', fontSize: 14 },
  retry: { color: '#2563eb', fontSize: 14, fontWeight: '600', marginTop: 4 },
  financeGroupLabel: { fontSize: 12, fontWeight: '700', color: '#6b7280', textTransform: 'uppercase', marginBottom: 2 },
  financeRow: { flexDirection: 'row', justifyContent: 'space-between', paddingVertical: 3, gap: 8 },
  financeDesc: { fontSize: 14, color: '#374151', flexShrink: 1 },
  financeAmount: { fontSize: 14, color: '#111827', fontWeight: '600' },
  financeTotalRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e5e7eb',
    marginTop: 4,
    paddingTop: 4,
  },
  financeTotalLabel: { fontSize: 13, fontWeight: '700', color: '#374151' },
  financeTotalValue: { fontSize: 13, fontWeight: '700', color: '#111827' },
  notesText: { fontSize: 14, color: '#374151', lineHeight: 20 },
  notesInput: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 10,
    padding: 10,
    fontSize: 15,
    minHeight: 80,
    textAlignVertical: 'top',
  },
  notesButtons: { flexDirection: 'row', justifyContent: 'flex-end', gap: 20, marginTop: 8 },
  brainRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 8,
    paddingVertical: 6,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#f3f4f6',
  },
  brainText: { fontSize: 14, color: '#374151', flexShrink: 1, lineHeight: 20 },
  brainDelete: { color: '#9ca3af', fontSize: 16, paddingHorizontal: 4 },
})
