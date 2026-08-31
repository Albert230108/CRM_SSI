import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { AxiosError } from 'axios'
import { useNavigation, useRoute, type RouteProp } from '@react-navigation/native'

import type { ThreadParams } from '../navigation/types'
import type { ThreadBubble, TenantChannelEndpointRead } from '../api/communications'
import { useSendWhatsapp, useThread, useWhatsappEndpoints } from '../hooks/useThread'
import { formatBubbleTime } from '../lib/format'

// Reached from both the Tenants and Notifications stacks, so ThreadScreen reads its route/navigation
// via hooks rather than stack-specific props — keeping it usable from either navigator.
type ThreadRoute = RouteProp<Record<'Thread', ThreadParams>, 'Thread'>

function isOutbound(direction: string): boolean {
  return direction.toLowerCase() === 'outbound'
}

function endpointLabel(e: TenantChannelEndpointRead): string {
  return e.chat_display_name || e.external_chat_namespace || e.external_account_id || `Chat ${e.id}`
}

export function ThreadScreen() {
  const route = useRoute<ThreadRoute>()
  const navigation = useNavigation()
  const { tenantId, tenantName } = route.params
  const listRef = useRef<FlatList<ThreadBubble>>(null)

  const { data, isLoading, isError, refetch } = useThread(tenantId)
  const { data: endpoints } = useWhatsappEndpoints(tenantId)
  const sendMutation = useSendWhatsapp(tenantId)

  const [text, setText] = useState('')
  const [selectedEndpointId, setSelectedEndpointId] = useState<number | null>(null)

  // Title: param first (instant), upgraded to the thread's own name once loaded.
  useLayoutEffect(() => {
    navigation.setOptions({ title: data?.tenantName ?? tenantName ?? 'Thread' })
  }, [navigation, data?.tenantName, tenantName])

  // Default the send target to the most-recent inbound chat (or the only/first one).
  useEffect(() => {
    if (selectedEndpointId !== null || !endpoints || endpoints.length === 0) return
    const preferred = endpoints.find((e) => e.is_most_recent_inbound) ?? endpoints[0]
    setSelectedEndpointId(preferred.id)
  }, [endpoints, selectedEndpointId])

  const bubbles = data?.bubbles ?? []
  const canSend =
    text.trim().length > 0 && selectedEndpointId !== null && !sendMutation.isPending

  const onSend = () => {
    if (selectedEndpointId === null || text.trim().length === 0) return
    const message = text.trim()
    sendMutation.mutate(
      { message, whatsappEndpointId: selectedEndpointId },
      {
        onSuccess: () => setText(''),
        onError: (err) => {
          const detail =
            err instanceof AxiosError
              ? (err.response?.data as { detail?: string } | undefined)?.detail
              : undefined
          Alert.alert('Message not sent', detail ?? 'Something went wrong. Please try again.')
        },
      },
    )
  }

  const renderBubble = ({ item }: { item: ThreadBubble }) => {
    const outbound = isOutbound(item.direction)
    return (
      <View style={[styles.bubbleRow, outbound ? styles.bubbleRowRight : styles.bubbleRowLeft]}>
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
      </View>
    )
  }

  const hasEndpoints = (endpoints?.length ?? 0) > 0

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right', 'bottom']}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={90}
      >
        {isLoading ? (
          <View style={styles.center}>
            <ActivityIndicator size="large" color="#2563eb" />
          </View>
        ) : isError ? (
          <View style={styles.center}>
            <Text style={styles.errorText}>Couldn’t load this thread.</Text>
            <TouchableOpacity onPress={() => void refetch()}>
              <Text style={styles.retry}>Retry</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <FlatList
            ref={listRef}
            data={bubbles}
            keyExtractor={(b) => b.key}
            renderItem={renderBubble}
            contentContainerStyle={styles.listContent}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
            ListEmptyComponent={
              <View style={styles.center}>
                <Text style={styles.subtitle}>No messages yet.</Text>
              </View>
            }
          />
        )}

        {/* Composer — WhatsApp plain text only for the MVP. */}
        {endpoints && !hasEndpoints ? (
          <View style={styles.composerHint}>
            <Text style={styles.subtitle}>
              No linked WhatsApp chat for this tenant — link one in the web app to send from here.
            </Text>
          </View>
        ) : (
          <View style={styles.composerWrap}>
            {endpoints && endpoints.length > 1 ? (
              <View style={styles.endpointRow}>
                {endpoints.map((e) => {
                  const selected = e.id === selectedEndpointId
                  return (
                    <TouchableOpacity
                      key={e.id}
                      style={[styles.endpointChip, selected && styles.endpointChipSelected]}
                      onPress={() => setSelectedEndpointId(e.id)}
                    >
                      <Text
                        style={[
                          styles.endpointChipText,
                          selected && styles.endpointChipTextSelected,
                        ]}
                        numberOfLines={1}
                      >
                        {endpointLabel(e)}
                      </Text>
                    </TouchableOpacity>
                  )
                })}
              </View>
            ) : null}
            <View style={styles.composer}>
              <TextInput
                style={styles.input}
                placeholder="Message"
                value={text}
                onChangeText={setText}
                multiline
                editable={!sendMutation.isPending}
              />
              <TouchableOpacity
                style={[styles.sendButton, !canSend && styles.sendButtonDisabled]}
                onPress={onSend}
                disabled={!canSend}
              >
                {sendMutation.isPending ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <Text style={styles.sendText}>Send</Text>
                )}
              </TouchableOpacity>
            </View>
          </View>
        )}
      </KeyboardAvoidingView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#f3f4f6' },
  flex: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  subtitle: { fontSize: 14, color: '#6b7280', textAlign: 'center' },
  errorText: { color: '#dc2626', fontSize: 15 },
  retry: { color: '#2563eb', fontSize: 15, fontWeight: '600' },
  listContent: { padding: 12, gap: 8 },
  bubbleRow: { flexDirection: 'row' },
  bubbleRowLeft: { justifyContent: 'flex-start' },
  bubbleRowRight: { justifyContent: 'flex-end' },
  bubble: { maxWidth: '82%', borderRadius: 14, paddingHorizontal: 12, paddingVertical: 8 },
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
  endpointRow: { flexDirection: 'row', flexWrap: 'wrap', gap: 6, paddingHorizontal: 12, paddingTop: 8 },
  endpointChip: {
    borderWidth: 1,
    borderColor: '#d1d5db',
    borderRadius: 14,
    paddingHorizontal: 10,
    paddingVertical: 4,
    maxWidth: 180,
  },
  endpointChipSelected: { backgroundColor: '#dbeafe', borderColor: '#2563eb' },
  endpointChipText: { fontSize: 12, color: '#6b7280' },
  endpointChipTextSelected: { color: '#1d4ed8', fontWeight: '600' },
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
})
