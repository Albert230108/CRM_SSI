import { useLayoutEffect, useMemo } from 'react'
import {
  ActivityIndicator,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import type { NativeStackScreenProps } from '@react-navigation/native-stack'

import type { TenantsStackParamList } from '../navigation/types'
import type { FinanceLineItem } from '../api/finance'
import { useTenant } from '../hooks/useTenants'
import { useTenantFinance } from '../hooks/useTenantDetail'
import { formatDate, formatMoney } from '../lib/format'

type Props = NativeStackScreenProps<TenantsStackParamList, 'BookingDetail'>

/**
 * "Beds24 details & payments" — opened from the chat header dropdown. Shows the full booking:
 * a friendly summary of the well-known fields, every remaining primitive field from the raw
 * Beds24 payload (so nothing is hidden as the channel-specific shape varies), then charges and
 * payments. Each data source degrades independently so one failing query doesn't blank the screen.
 */
export function BookingDetailScreen({ navigation, route }: Props) {
  const { tenantId, tenantName } = route.params
  const tenant = useTenant(tenantId)
  const finance = useTenantFinance(tenantId)

  useLayoutEffect(() => {
    navigation.setOptions({ title: tenant.data?.name ?? tenantName ?? 'Beds24 details' })
  }, [navigation, tenant.data?.name, tenantName])

  const onRefresh = () => {
    void tenant.refetch()
    void finance.refetch()
  }

  const t = tenant.data
  const refreshing = tenant.isRefetching || finance.isRefetching

  // The well-known fields are surfaced explicitly in the summary; hide them from the generic raw
  // dump so we don't show the same thing twice.
  const KNOWN_RAW_KEYS = useMemo(
    () =>
      new Set([
        'id',
        'bookid',
        'bookingid',
        'status',
        'firstname',
        'lastname',
        'name',
        'guestname',
        'email',
        'phone',
        'mobile',
        'arrival',
        'departure',
        'checkin',
        'checkout',
        'roomname',
        'propertyname',
        'notes',
      ]),
    [],
  )

  const rawRows = useMemo(
    () => flattenBeds24Raw(finance.data?.tenant.beds24_raw ?? null, KNOWN_RAW_KEYS),
    [finance.data?.tenant.beds24_raw, KNOWN_RAW_KEYS],
  )

  const charges = finance.data?.charges ?? []
  const payments = finance.data?.payments ?? []

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right', 'bottom']}>
      <ScrollView
        contentContainerStyle={styles.content}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
      >
        {/* Booking summary */}
        {tenant.isLoading ? (
          <ActivityIndicator style={{ marginVertical: 24 }} color="#2563eb" />
        ) : t ? (
          <View style={styles.card}>
            <Text style={styles.title}>{t.name}</Text>
            <InfoRow label="Booking" value={[t.booking_status, t.booking_id].filter(Boolean).join(' · ')} />
            <InfoRow label="Room" value={[t.room_name, t.property_name].filter(Boolean).join(' · ')} />
            {t.check_in || t.check_out ? (
              <InfoRow label="Stay" value={`${formatDate(t.check_in)} → ${formatDate(t.check_out)}`} />
            ) : null}
            <InfoRow label="Email" value={t.email} />
            <InfoRow label="Phone" value={t.phone ?? t.mobile} />
            <InfoRow label="Responsible" value={t.responsible_comm} />
          </View>
        ) : (
          <SectionError label="booking" onRetry={() => void tenant.refetch()} />
        )}

        {/* Full Beds24 payload */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Beds24 booking data</Text>
          {finance.isLoading ? (
            <ActivityIndicator color="#2563eb" />
          ) : finance.isError ? (
            <SectionError label="Beds24 data" onRetry={() => void finance.refetch()} bare />
          ) : rawRows.length === 0 ? (
            <Text style={styles.muted}>No additional Beds24 fields.</Text>
          ) : (
            rawRows.map((row) => <InfoRow key={row.key} label={row.label} value={row.value} />)
          )}
        </View>

        {/* Charges & payments */}
        <View style={styles.card}>
          <Text style={styles.sectionTitle}>Charges & payments</Text>
          {finance.isLoading ? (
            <ActivityIndicator color="#2563eb" />
          ) : finance.isError ? (
            <SectionError label="finance" onRetry={() => void finance.refetch()} bare />
          ) : charges.length === 0 && payments.length === 0 ? (
            <Text style={styles.muted}>No charges or payments.</Text>
          ) : (
            <>
              {charges.length > 0 ? <FinanceGroup label="Charges" items={charges} /> : null}
              {payments.length > 0 ? <FinanceGroup label="Payments" items={payments} /> : null}
            </>
          )}
        </View>
      </ScrollView>
    </SafeAreaView>
  )
}

/** One primitive field from the raw Beds24 payload, ready to render. */
type RawRow = { key: string; label: string; value: string }

/**
 * Flatten the raw Beds24 booking object to a list of `{label, value}` rows. Only primitive fields
 * (string/number/boolean) are shown — nested objects/arrays and empty values are skipped — so the
 * screen never hides data yet stays readable across the channel-specific payload variants.
 */
function flattenBeds24Raw(
  raw: Record<string, unknown> | null,
  knownKeys: Set<string>,
): RawRow[] {
  if (!raw || typeof raw !== 'object') return []
  const rows: RawRow[] = []
  for (const [key, value] of Object.entries(raw)) {
    if (knownKeys.has(key.toLowerCase())) continue
    if (value === null || value === undefined || value === '') continue
    if (typeof value === 'object') continue // skip nested objects/arrays for legibility
    rows.push({ key, label: humanizeKey(key), value: String(value) })
  }
  return rows.sort((a, b) => a.label.localeCompare(b.label))
}

/** "numAdult" / "arrival_time" → "Num Adult" / "Arrival Time". */
function humanizeKey(key: string): string {
  const spaced = key
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function InfoRow({ label, value }: { label: string; value: string | null | undefined }) {
  if (!value) return null
  return (
    <View style={styles.infoRow}>
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{value}</Text>
    </View>
  )
}

function FinanceGroup({ label, items }: { label: string; items: FinanceLineItem[] }) {
  const currency = items[0]?.currency ?? null
  const total = items.reduce((sum, i) => sum + (Number(i.amount) || 0), 0)
  return (
    <View style={styles.financeGroup}>
      <Text style={styles.financeGroupLabel}>{label}</Text>
      {items.map((item) => (
        <View key={`${item.type}-${item.id}`} style={styles.financeRow}>
          <Text style={styles.financeDesc} numberOfLines={1}>
            {item.description || item.type}
          </Text>
          <Text style={styles.financeAmount}>{formatMoney(item.amount, item.currency)}</Text>
        </View>
      ))}
      <View style={styles.financeTotalRow}>
        <Text style={styles.financeTotalLabel}>Total {label.toLowerCase()}</Text>
        <Text style={styles.financeTotalValue}>{formatMoney(total, currency)}</Text>
      </View>
    </View>
  )
}

function SectionError({
  label,
  onRetry,
  bare,
}: {
  label: string
  onRetry: () => void
  bare?: boolean
}) {
  const body = (
    <>
      <Text style={styles.errorText}>Couldn’t load {label}.</Text>
      <TouchableOpacity onPress={onRetry}>
        <Text style={styles.retry}>Retry</Text>
      </TouchableOpacity>
    </>
  )
  return bare ? <View>{body}</View> : <View style={styles.card}>{body}</View>
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f3f4f6' },
  content: { padding: 12, gap: 12 },
  card: { backgroundColor: '#fff', borderRadius: 12, padding: 14, gap: 6 },
  title: { fontSize: 18, fontWeight: '700', color: '#111827', marginBottom: 2 },
  sectionTitle: { fontSize: 15, fontWeight: '700', color: '#111827', marginBottom: 4 },
  infoRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 12, paddingVertical: 3 },
  infoLabel: { fontSize: 13, color: '#6b7280', flexShrink: 0 },
  infoValue: { fontSize: 13, color: '#111827', fontWeight: '500', flexShrink: 1, textAlign: 'right' },
  muted: { color: '#9ca3af', fontSize: 14 },
  financeGroup: { gap: 2, marginTop: 4 },
  financeGroupLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: '#6b7280',
    textTransform: 'uppercase',
    marginBottom: 2,
  },
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
  errorText: { color: '#dc2626', fontSize: 14 },
  retry: { color: '#2563eb', fontSize: 14, fontWeight: '600', marginTop: 4 },
})
