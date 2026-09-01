import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  ActivityIndicator,
  Alert,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native'
import { SafeAreaView } from 'react-native-safe-area-context'
import { KeyboardAvoidingView } from 'react-native-keyboard-controller'
import { useHeaderHeight } from '@react-navigation/elements'
import type { NativeStackScreenProps } from '@react-navigation/native-stack'

import type { TenantsStackParamList } from '../navigation/types'
import { useTenant } from '../hooks/useTenants'
import {
  useDiscardDraftNotes,
  useSaveDraftNotes,
  useSaveNotes,
} from '../hooks/useTenantDetail'
import { useDebouncedValue } from '../hooks/useDebouncedValue'

type Props = NativeStackScreenProps<TenantsStackParamList, 'Notes'>

/**
 * Tenant notes editor, opened from the chat header dropdown. Mirrors the web app's
 * autosave-while-typing: edits persist to `draft_notes` (no Beds24 sync) so an unsaved change
 * survives navigating away, and "Save" commits to `notes` (which also syncs Beds24 and clears the
 * draft). The editor seeds from the draft if one exists, otherwise the committed note.
 */
export function NotesScreen({ navigation, route }: Props) {
  const { tenantId, tenantName } = route.params
  const tenant = useTenant(tenantId)
  const save = useSaveNotes(tenantId)
  const saveDraft = useSaveDraftNotes(tenantId)
  const discardDraft = useDiscardDraftNotes(tenantId)

  useLayoutEffect(() => {
    navigation.setOptions({ title: tenant.data?.name ? `${tenant.data.name} · Notes` : tenantName ? `${tenantName} · Notes` : 'Notes' })
  }, [navigation, tenant.data?.name, tenantName])

  const headerHeight = useHeaderHeight()
  const committed = tenant.data?.notes ?? ''
  const draft = tenant.data?.draft_notes ?? null

  const [value, setValue] = useState('')
  const seededRef = useRef(false)
  const editedRef = useRef(false)
  const lastSavedDraftRef = useRef<string | null>(null)

  const onChangeText = (next: string) => {
    editedRef.current = true
    setValue(next)
  }

  // Seed the editor once when the tenant loads: prefer an in-progress draft, else the committed note.
  useEffect(() => {
    if (seededRef.current || !tenant.data) return
    const initial = draft ?? committed
    setValue(initial)
    lastSavedDraftRef.current = draft // only a real draft counts as "already saved"
    seededRef.current = true
  }, [tenant.data, draft, committed])

  // Debounced autosave of the draft as the user types.
  const debounced = useDebouncedValue(value, 800)
  useEffect(() => {
    // Only autosave a real user edit — never during the initial seed transition.
    if (!seededRef.current || !editedRef.current) return
    if (debounced === lastSavedDraftRef.current) return
    if (debounced === committed && (lastSavedDraftRef.current === null || lastSavedDraftRef.current === '')) {
      // Back to the committed value with no prior draft — nothing to persist.
      return
    }
    lastSavedDraftRef.current = debounced
    saveDraft.mutate(debounced.trim() ? debounced : null)
  }, [debounced, committed, saveDraft])

  const dirty = value !== committed

  const onSave = () => {
    save.mutate(value.trim() ? value : null, {
      onSuccess: () => {
        lastSavedDraftRef.current = null
        navigation.goBack()
      },
      onError: () => Alert.alert('Notes not saved', 'Something went wrong. Please try again.'),
    })
  }

  const onDiscardDraft = () => {
    Alert.alert('Discard changes', 'Revert to the saved note?', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Discard',
        style: 'destructive',
        onPress: () => {
          setValue(committed)
          lastSavedDraftRef.current = null
          discardDraft.mutate()
        },
      },
    ])
  }

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right', 'bottom']}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior="padding"
        keyboardVerticalOffset={headerHeight}
      >
        {tenant.isLoading && !seededRef.current ? (
          <View style={styles.center}>
            <ActivityIndicator color="#2563eb" size="large" />
          </View>
        ) : (
          <View style={styles.flex}>
            <TextInput
              style={styles.input}
              value={value}
              onChangeText={onChangeText}
              multiline
              autoFocus
              placeholder="Add notes…"
              textAlignVertical="top"
            />
            <View style={styles.footer}>
              <View style={styles.statusWrap}>
                {saveDraft.isPending ? (
                  <Text style={styles.status}>Saving draft…</Text>
                ) : draft !== null && dirty ? (
                  <TouchableOpacity onPress={onDiscardDraft}>
                    <Text style={styles.discard}>Discard changes</Text>
                  </TouchableOpacity>
                ) : (
                  <Text style={styles.statusMuted}>Autosaves as you type</Text>
                )}
              </View>
              <TouchableOpacity
                style={[styles.saveButton, (!dirty || save.isPending) && styles.saveButtonDisabled]}
                onPress={onSave}
                disabled={!dirty || save.isPending}
              >
                {save.isPending ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <Text style={styles.saveText}>Save</Text>
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
  container: { flex: 1, backgroundColor: '#fff' },
  flex: { flex: 1 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  input: {
    flex: 1,
    fontSize: 16,
    lineHeight: 22,
    color: '#111827',
    padding: 16,
  },
  footer: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    padding: 12,
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: '#e5e7eb',
  },
  statusWrap: { flex: 1 },
  status: { fontSize: 13, color: '#6b7280' },
  statusMuted: { fontSize: 13, color: '#9ca3af' },
  discard: { fontSize: 14, color: '#dc2626', fontWeight: '600' },
  saveButton: {
    backgroundColor: '#2563eb',
    borderRadius: 10,
    paddingHorizontal: 22,
    height: 40,
    alignItems: 'center',
    justifyContent: 'center',
  },
  saveButtonDisabled: { opacity: 0.5 },
  saveText: { color: '#fff', fontWeight: '600', fontSize: 15 },
})
