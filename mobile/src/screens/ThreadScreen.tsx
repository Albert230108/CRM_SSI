import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
  type NativeScrollEvent,
  type NativeSyntheticEvent,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { KeyboardAvoidingView } from 'react-native-keyboard-controller'
import { AxiosError } from 'axios'
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native'
import type { NativeStackNavigationProp } from '@react-navigation/native-stack'
import { useHeaderHeight } from '@react-navigation/elements'

import type { ThreadParams, TenantsStackParamList } from '../navigation/types'
import type {
  EmailThreadOption,
  ThreadBubble,
  TenantChannelEndpointRead,
} from '../api/communications'
import {
  useForwardEmail,
  useRunAiPlanner,
  useSendEmail,
  useSendWhatsapp,
  useThread,
  useThreadVersion,
  useWhatsappEndpoints,
} from '../hooks/useThread'
import { formatBubbleTime, oneLine } from '../lib/format'

// Reached from both the Tenants and Notifications stacks, so ThreadScreen reads its route/navigation
// via hooks rather than stack-specific props — keeping it usable from either navigator.
type ThreadRoute = RouteProp<Record<'Thread', ThreadParams>, 'Thread'>

type Channel = 'whatsapp' | 'email'
type InfoScreen = 'BookingDetail' | 'Notes' | 'Brain'

function isOutbound(direction: string): boolean {
  return direction.toLowerCase() === 'outbound'
}

function endpointLabel(e: TenantChannelEndpointRead): string {
  return e.chat_display_name || e.external_chat_namespace || e.external_account_id || `Chat ${e.id}`
}

function emailThreadLabel(t: EmailThreadOption): string {
  return oneLine(t.subject, 28) || t.accountEmail || `Thread ${t.threadId}`
}

const SKELETON_ROWS: { outbound: boolean; width: number }[] = [
  { outbound: false, width: 180 },
  { outbound: true, width: 140 },
  { outbound: false, width: 220 },
  { outbound: true, width: 120 },
  { outbound: false, width: 160 },
]

function ThreadSkeleton() {
  return (
    <View style={styles.listContent}>
      {SKELETON_ROWS.map((row, i) => (
        <View
          key={i}
          style={[styles.bubbleRow, row.outbound ? styles.bubbleRowRight : styles.bubbleRowLeft]}
        >
          <View style={[styles.skeletonBubble, { width: row.width }]} />
        </View>
      ))}
    </View>
  )
}

/** A single chat bubble. Memoized so composing/polling doesn't re-render the whole history. */
const BubbleRow = memo(function BubbleRow({
  item,
  onOpenEmail,
  onForwardEmail,
}: {
  item: ThreadBubble
  onOpenEmail: (item: ThreadBubble) => void
  onForwardEmail: (threadId: number | null) => void
}) {
  const outbound = isOutbound(item.direction)
  const isEmail = item.kind === 'email'
  return (
    <TouchableOpacity
      activeOpacity={isEmail ? 0.7 : 1}
      // Tap an email to read the full HTML body; long-press to forward the thread.
      onPress={isEmail ? () => onOpenEmail(item) : undefined}
      onLongPress={isEmail ? () => onForwardEmail(item.threadId) : undefined}
      style={[styles.bubbleRow, outbound ? styles.bubbleRowRight : styles.bubbleRowLeft]}
    >
      <View style={[styles.bubble, outbound ? styles.bubbleOut : styles.bubbleIn]}>
        <View style={styles.bubbleMeta}>
          <Text style={[styles.channelTag, outbound ? styles.metaOut : styles.metaIn]}>
            {item.kind === 'whatsapp' ? 'WhatsApp' : 'Email'}
          </Text>
          {item.aiGenerated ? (
            <Text style={[styles.aiTag, outbound ? styles.metaOut : styles.metaIn]}>· AI</Text>
          ) : null}
        </View>
        {item.kind === 'email' && item.subject ? (
          <Text style={[styles.subject, outbound ? styles.textOut : styles.textIn]}>
            {item.subject}
          </Text>
        ) : null}
        <Text style={[styles.bubbleText, outbound ? styles.textOut : styles.textIn]}>
          {item.text || '(no text)'}
        </Text>
        <Text style={[styles.bubbleTime, outbound ? styles.metaOut : styles.metaIn]}>
          {formatBubbleTime(item.at)}
        </Text>
      </View>
    </TouchableOpacity>
  )
})

export function ThreadScreen() {
  const route = useRoute<ThreadRoute>()
  // Both stacks that host ThreadScreen expose identical Thread + info-screen params, so typing the
  // navigator against the Tenants stack is sound and gives us typed navigate() calls.
  const navigation = useNavigation<NativeStackNavigationProp<TenantsStackParamList>>()
  const { tenantId, tenantName } = route.params
  const listRef = useRef<FlatList<ThreadBubble>>(null)

  const { data, isLoading, isError, refetch } = useThread(tenantId)
  const { data: endpoints } = useWhatsappEndpoints(tenantId)
  const version = useThreadVersion(tenantId)
  const sendWhatsapp = useSendWhatsapp(tenantId)
  const sendEmail = useSendEmail(tenantId)
  const forwardEmail = useForwardEmail(tenantId)
  const runPlanner = useRunAiPlanner(tenantId)

  const [channel, setChannel] = useState<Channel>('whatsapp')
  const [text, setText] = useState('')
  const [selectedEndpointId, setSelectedEndpointId] = useState<number | null>(null)
  const [selectedEmailThreadId, setSelectedEmailThreadId] = useState<number | null>(null)
  const [forwardThreadId, setForwardThreadId] = useState<number | null>(null)
  const [forwardBody, setForwardBody] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)

  const headerTitle = data?.tenantName ?? tenantName
  const emailThreads = data?.emailThreads ?? []
  const hasEndpoints = (endpoints?.length ?? 0) > 0
  const hasEmailThreads = emailThreads.length > 0

  // Header: title + a ⋯ dropdown that opens the per-tenant info screens (Beds24 details, notes, brain).
  useLayoutEffect(() => {
    navigation.setOptions({
      title: headerTitle ?? 'Thread',
      headerRight: () => (
        <TouchableOpacity onPress={() => setMenuOpen(true)} hitSlop={10}>
          <Text style={styles.headerMenuButton}>⋯</Text>
        </TouchableOpacity>
      ),
    })
  }, [navigation, headerTitle])

  const openInfoScreen = useCallback(
    (screen: InfoScreen) => {
      setMenuOpen(false)
      navigation.navigate(screen, { tenantId, tenantName: headerTitle })
    },
    [navigation, tenantId, headerTitle],
  )

  // Cheap version poll drives full-thread refreshes: only refetch when the change-marker actually
  // moves. Skipping the first observed value avoids a redundant refetch right after the initial load.
  const latestAt = version.data?.latest_at ?? null
  const prevLatestAtRef = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    const prev = prevLatestAtRef.current
    prevLatestAtRef.current = latestAt
    if (prev === undefined) return // first value seen — the initial fetch already has it
    if (latestAt && latestAt !== prev) void refetch()
  }, [latestAt, refetch])

  // Default the WhatsApp send target to the most-recent inbound chat (or the only/first one).
  useEffect(() => {
    if (selectedEndpointId !== null || !endpoints || endpoints.length === 0) return
    const preferred = endpoints.find((e) => e.is_most_recent_inbound) ?? endpoints[0]
    setSelectedEndpointId(preferred.id)
  }, [endpoints, selectedEndpointId])

  // Default the email reply target to the first available thread.
  useEffect(() => {
    if (selectedEmailThreadId !== null || emailThreads.length === 0) return
    setSelectedEmailThreadId(emailThreads[0].threadId)
  }, [emailThreads, selectedEmailThreadId])

  // If a tenant has only email (no WhatsApp link), start the composer on the email channel.
  useEffect(() => {
    if (endpoints && !hasEndpoints && hasEmailThreads) setChannel('email')
  }, [endpoints, hasEndpoints, hasEmailThreads])

  const bubbles = data?.bubbles ?? []
  // The list renders inverted (newest pinned to the bottom, scroll up for history), so feed it the
  // bubbles newest-first. `bubbles` arrives oldest→newest, so reverse a memoized copy.
  const invertedBubbles = useMemo(() => bubbles.slice().reverse(), [bubbles])

  // "New messages" pill: when a message arrives while the user has scrolled up into history, we
  // don't yank them down — we offer a tap to jump to the newest instead.
  const [atBottom, setAtBottom] = useState(true)
  const [showNewPill, setShowNewPill] = useState(false)
  const newestKey = invertedBubbles[0]?.key ?? null
  const prevNewestKeyRef = useRef<string | null>(null)
  useEffect(() => {
    const prev = prevNewestKeyRef.current
    prevNewestKeyRef.current = newestKey
    if (prev === null || newestKey === null || newestKey === prev) return
    if (!atBottom) setShowNewPill(true)
  }, [newestKey, atBottom])

  const onScroll = useCallback((e: NativeSyntheticEvent<NativeScrollEvent>) => {
    // Inverted list: the newest message sits at offset ~0.
    const nearBottom = e.nativeEvent.contentOffset.y < 48
    setAtBottom(nearBottom)
    if (nearBottom) setShowNewPill(false)
  }, [])

  const jumpToNewest = useCallback(() => {
    listRef.current?.scrollToOffset({ offset: 0, animated: true })
    setShowNewPill(false)
  }, [])

  const sending = sendWhatsapp.isPending || sendEmail.isPending

  const canSend =
    text.trim().length > 0 &&
    !sending &&
    (channel === 'whatsapp' ? selectedEndpointId !== null : selectedEmailThreadId !== null)

  const onSend = () => {
    const message = text.trim()
    if (!message) return
    const onError = (err: unknown) => {
      const detail =
        err instanceof AxiosError
          ? (err.response?.data as { detail?: string } | undefined)?.detail
          : undefined
      Alert.alert('Message not sent', detail ?? 'Something went wrong. Please try again.')
    }
    if (channel === 'whatsapp') {
      if (selectedEndpointId === null) return
      sendWhatsapp.mutate(
        { message, whatsappEndpointId: selectedEndpointId },
        { onSuccess: () => setText(''), onError },
      )
    } else {
      if (selectedEmailThreadId === null) return
      sendEmail.mutate(
        { emailThreadId: selectedEmailThreadId, message },
        { onSuccess: () => setText(''), onError },
      )
    }
  }

  // Run the full planner instead of a one-shot draft: the result lands in the AI Drafts queue
  // asynchronously rather than in this composer, so we confirm and point the user there.
  const onRunPlanner = () => {
    runPlanner.mutate(
      {
        channel,
        whatsappEndpointId: channel === 'whatsapp' ? selectedEndpointId : undefined,
        emailThreadId: channel === 'email' ? selectedEmailThreadId : undefined,
        roughDraft: text.trim() || undefined,
      },
      {
        onSuccess: () =>
          Alert.alert('Planner running', 'Generating a draft — it will appear in AI Drafts shortly.'),
        onError: (err) => {
          const detail =
            err instanceof AxiosError
              ? (err.response?.data as { detail?: string } | undefined)?.detail
              : undefined
          Alert.alert('Planner failed', detail ?? 'Could not run the planner. Please try again.')
        },
      },
    )
  }

  const openForward = useCallback((threadId: number | null) => {
    if (threadId === null) return
    setForwardThreadId(threadId)
    setForwardBody('')
  }, [])

  const openEmail = useCallback(
    (item: ThreadBubble) => {
      if (item.kind !== 'email') return
      navigation.navigate('EmailViewer', { subject: item.subject, html: item.html, text: item.text })
    },
    [navigation],
  )

  const submitForward = () => {
    if (forwardThreadId === null) return
    forwardEmail.mutate(
      { emailThreadId: forwardThreadId, body: forwardBody.trim() || '(forwarded)' },
      {
        onSuccess: () => setForwardThreadId(null),
        onError: (err) => {
          const detail =
            err instanceof AxiosError
              ? (err.response?.data as { detail?: string } | undefined)?.detail
              : undefined
          Alert.alert('Forward failed', detail ?? 'Could not forward this thread.')
        },
      },
    )
  }

  const renderBubble = useCallback(
    ({ item }: { item: ThreadBubble }) => (
      <BubbleRow item={item} onOpenEmail={openEmail} onForwardEmail={openForward} />
    ),
    [openEmail, openForward],
  )

  const headerHeight = useHeaderHeight()

  // Which composer targets are available drives whether we can send at all on each channel.
  const channelReady = channel === 'whatsapp' ? hasEndpoints : hasEmailThreads
  const noTargetsAtAll = endpoints && !hasEndpoints && !hasEmailThreads

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right', 'bottom']}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior="padding"
        keyboardVerticalOffset={headerHeight}
      >
        <View style={styles.listWrap}>
          {isLoading ? (
            <ThreadSkeleton />
          ) : isError ? (
            <View style={styles.center}>
              <Text style={styles.errorText}>Couldn’t load this thread.</Text>
              <TouchableOpacity onPress={() => void refetch()}>
                <Text style={styles.retry}>Retry</Text>
              </TouchableOpacity>
            </View>
          ) : invertedBubbles.length === 0 ? (
            <View style={styles.center}>
              <Text style={styles.subtitle}>No messages yet.</Text>
            </View>
          ) : (
            <FlatList
              ref={listRef}
              data={invertedBubbles}
              inverted
              style={styles.list}
              keyExtractor={(b) => b.key}
              renderItem={renderBubble}
              contentContainerStyle={styles.listContent}
              onScroll={onScroll}
              scrollEventThrottle={16}
              initialNumToRender={15}
              windowSize={11}
              removeClippedSubviews
              keyboardDismissMode="interactive"
            />
          )}

          {showNewPill ? (
            <TouchableOpacity style={styles.newPill} onPress={jumpToNewest} activeOpacity={0.85}>
              <Text style={styles.newPillText}>↓ New messages</Text>
            </TouchableOpacity>
          ) : null}
        </View>

        {noTargetsAtAll ? (
          <View style={styles.composerHint}>
            <Text style={styles.subtitle}>
              No linked WhatsApp chat or email thread for this tenant — link one in the web app to
              send from here.
            </Text>
          </View>
        ) : (
          <View style={styles.composerWrap}>
            {/* Channel toggle */}
            <View style={styles.channelRow}>
              <ChannelTab
                label="WhatsApp"
                active={channel === 'whatsapp'}
                disabled={!hasEndpoints}
                onPress={() => setChannel('whatsapp')}
              />
              <ChannelTab
                label="Email"
                active={channel === 'email'}
                disabled={!hasEmailThreads}
                onPress={() => setChannel('email')}
              />
              <View style={styles.channelSpacer} />
              <TouchableOpacity
                style={styles.aiButton}
                onPress={onRunPlanner}
                disabled={runPlanner.isPending || !channelReady}
              >
                {runPlanner.isPending ? (
                  <ActivityIndicator size="small" color="#7c3aed" />
                ) : (
                  <Text style={styles.aiButtonText}>✨ Run planner</Text>
                )}
              </TouchableOpacity>
            </View>

            {/* Target selector (whatsapp chats or email threads) */}
            {channel === 'whatsapp' && endpoints && endpoints.length > 1 ? (
              <View style={styles.chipRow}>
                {endpoints.map((e) => (
                  <Chip
                    key={e.id}
                    label={endpointLabel(e)}
                    selected={e.id === selectedEndpointId}
                    onPress={() => setSelectedEndpointId(e.id)}
                  />
                ))}
              </View>
            ) : null}
            {channel === 'email' && emailThreads.length > 1 ? (
              <View style={styles.chipRow}>
                {emailThreads.map((t) => (
                  <Chip
                    key={t.threadId}
                    label={emailThreadLabel(t)}
                    selected={t.threadId === selectedEmailThreadId}
                    onPress={() => setSelectedEmailThreadId(t.threadId)}
                  />
                ))}
              </View>
            ) : null}

            {!channelReady ? (
              <View style={styles.composerHint}>
                <Text style={styles.subtitle}>
                  {channel === 'whatsapp'
                    ? 'No linked WhatsApp chat for this tenant.'
                    : 'No email thread to reply to for this tenant.'}
                </Text>
              </View>
            ) : (
              <View style={styles.composer}>
                <TextInput
                  style={styles.input}
                  placeholder={channel === 'whatsapp' ? 'Message' : 'Email reply'}
                  value={text}
                  onChangeText={setText}
                  multiline
                  editable={!sending}
                />
                <TouchableOpacity
                  style={[styles.sendButton, !canSend && styles.sendButtonDisabled]}
                  onPress={onSend}
                  disabled={!canSend}
                >
                  {sending ? (
                    <ActivityIndicator color="#fff" size="small" />
                  ) : (
                    <Text style={styles.sendText}>Send</Text>
                  )}
                </TouchableOpacity>
              </View>
            )}
          </View>
        )}
      </KeyboardAvoidingView>

      {/* Header ⋯ dropdown */}
      <Modal
        visible={menuOpen}
        transparent
        animationType="fade"
        onRequestClose={() => setMenuOpen(false)}
      >
        <Pressable style={styles.menuBackdrop} onPress={() => setMenuOpen(false)}>
          <View style={[styles.menuCard, { top: headerHeight }]}>
            <MenuItem label="Beds24 details & payments" onPress={() => openInfoScreen('BookingDetail')} />
            <View style={styles.menuDivider} />
            <MenuItem label="Notes" onPress={() => openInfoScreen('Notes')} />
            <View style={styles.menuDivider} />
            <MenuItem label="Brain" onPress={() => openInfoScreen('Brain')} />
          </View>
        </Pressable>
      </Modal>

      {/* Forward modal */}
      <Modal
        visible={forwardThreadId !== null}
        transparent
        animationType="fade"
        onRequestClose={() => setForwardThreadId(null)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <Text style={styles.modalTitle}>Forward email thread</Text>
            <Text style={styles.subtitle}>
              Forwards to the address configured in Admin Settings.
            </Text>
            <TextInput
              style={styles.modalInput}
              placeholder="Add a note (optional)"
              value={forwardBody}
              onChangeText={setForwardBody}
              multiline
              editable={!forwardEmail.isPending}
            />
            <View style={styles.modalButtons}>
              <TouchableOpacity
                onPress={() => setForwardThreadId(null)}
                disabled={forwardEmail.isPending}
              >
                <Text style={styles.actionMuted}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={submitForward} disabled={forwardEmail.isPending}>
                {forwardEmail.isPending ? (
                  <ActivityIndicator color="#2563eb" size="small" />
                ) : (
                  <Text style={styles.action}>Forward</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </SafeAreaView>
  )
}

function MenuItem({ label, onPress }: { label: string; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.menuItem} onPress={onPress}>
      <Text style={styles.menuItemText}>{label}</Text>
    </TouchableOpacity>
  )
}

function ChannelTab({
  label,
  active,
  disabled,
  onPress,
}: {
  label: string
  active: boolean
  disabled?: boolean
  onPress: () => void
}) {
  return (
    <TouchableOpacity
      style={[styles.channelTab, active && styles.channelTabActive, disabled && styles.channelTabDisabled]}
      onPress={onPress}
      disabled={disabled}
    >
      <Text style={[styles.channelTabText, active && styles.channelTabTextActive]}>{label}</Text>
    </TouchableOpacity>
  )
}

function Chip({
  label,
  selected,
  onPress,
}: {
  label: string
  selected: boolean
  onPress: () => void
}) {
  return (
    <TouchableOpacity
      style={[styles.chip, selected && styles.chipSelected]}
      onPress={onPress}
    >
      <Text style={[styles.chipText, selected && styles.chipTextSelected]} numberOfLines={1}>
        {label}
      </Text>
    </TouchableOpacity>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f3f4f6' },
  flex: { flex: 1 },
  listWrap: { flex: 1 },
  list: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  subtitle: { fontSize: 14, color: '#6b7280', textAlign: 'center' },
  errorText: { color: '#dc2626', fontSize: 15 },
  retry: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
  action: { color: '#2563eb', fontWeight: '600', fontSize: 15 },
  actionMuted: { color: '#6b7280', fontWeight: '600', fontSize: 15 },
  headerMenuButton: { fontSize: 26, color: '#2563eb', paddingHorizontal: 4, marginTop: -4 },
  listContent: { padding: 12, gap: 8 },
  bubbleRow: { flexDirection: 'row' },
  bubbleRowLeft: { justifyContent: 'flex-start' },
  bubbleRowRight: { justifyContent: 'flex-end' },
  bubble: { maxWidth: '82%', borderRadius: 14, paddingHorizontal: 12, paddingVertical: 8 },
  skeletonBubble: { height: 44, borderRadius: 14, backgroundColor: '#e5e7eb' },
  bubbleIn: { backgroundColor: '#fff', borderTopLeftRadius: 4 },
  bubbleOut: { backgroundColor: '#2563eb', borderTopRightRadius: 4 },
  bubbleMeta: { flexDirection: 'row', alignItems: 'center', gap: 4, marginBottom: 2 },
  channelTag: { fontSize: 10, fontWeight: '700', textTransform: 'uppercase', letterSpacing: 0.5 },
  aiTag: { fontSize: 10, fontWeight: '600' },
  subject: { fontSize: 13, fontWeight: '700', marginBottom: 2 },
  bubbleText: { fontSize: 15, lineHeight: 20 },
  bubbleTime: { fontSize: 10, marginTop: 4, alignSelf: 'flex-end' },
  textIn: { color: '#111827' },
  textOut: { color: '#fff' },
  metaIn: { color: '#9ca3af' },
  metaOut: { color: '#c7dbfd' },
  newPill: {
    position: 'absolute',
    alignSelf: 'center',
    bottom: 12,
    backgroundColor: '#2563eb',
    borderRadius: 16,
    paddingHorizontal: 14,
    paddingVertical: 7,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 3,
  },
  newPillText: { color: '#fff', fontSize: 13, fontWeight: '600' },
  composerHint: {
    padding: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e5e7eb',
    backgroundColor: '#fff',
  },
  composerWrap: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e5e7eb',
    backgroundColor: '#fff',
  },
  channelRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingTop: 8 },
  channelSpacer: { flex: 1 },
  channelTab: {
    paddingHorizontal: 12,
    paddingVertical: 5,
    borderRadius: 14,
    backgroundColor: '#f3f4f6',
  },
  channelTabActive: { backgroundColor: '#dbeafe' },
  channelTabDisabled: { opacity: 0.4 },
  channelTabText: { fontSize: 13, color: '#6b7280', fontWeight: '600' },
  channelTabTextActive: { color: '#1d4ed8' },
  aiButton: {
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: '#ddd6fe',
    backgroundColor: '#f5f3ff',
  },
  aiButtonText: { color: '#7c3aed', fontSize: 13, fontWeight: '600' },
  chipRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, paddingHorizontal: 12, paddingTop: 8 },
  chip: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 4,
    maxWidth: 180,
  },
  chipSelected: { backgroundColor: '#dbeafe', borderColor: '#2563eb' },
  chipText: { fontSize: 12, color: '#6b7280' },
  chipTextSelected: { color: '#1d4ed8', fontWeight: '600' },
  composer: { flexDirection: 'row', alignItems: 'flex-end', gap: 8, padding: 8 },
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
  sendButton: {
    backgroundColor: '#2563eb',
    borderRadius: 18,
    paddingHorizontal: 18,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  sendButtonDisabled: { opacity: 0.5 },
  sendText: { color: '#fff', fontWeight: '600', fontSize: 15 },
  menuBackdrop: { flex: 1 },
  menuCard: {
    position: 'absolute',
    right: 8,
    backgroundColor: '#fff',
    borderRadius: 12,
    paddingVertical: 4,
    minWidth: 220,
    shadowColor: '#000',
    shadowOpacity: 0.15,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 6,
  },
  menuItem: { paddingHorizontal: 16, paddingVertical: 12 },
  menuItemText: { fontSize: 15, color: '#111827' },
  menuDivider: { height: StyleSheet.hairlineWidth, backgroundColor: '#e5e7eb', marginLeft: 16 },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'center',
    padding: 24,
  },
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
