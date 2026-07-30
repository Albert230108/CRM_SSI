import { useState } from 'react'
import { useNotesDraftStore } from '../store/notesDraftStore'

export default function UnsavedNotesModal() {
  const pending = useNotesDraftStore((state) => state.pending)
  const resolvePending = useNotesDraftStore((state) => state.resolvePending)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  if (!pending) return null

  const handleChoice = async (choice: 'save' | 'discard' | 'cancel') => {
    setError('')
    if (choice === 'save') {
      setSaving(true)
      const ok = await resolvePending('save')
      setSaving(false)
      if (!ok) setError('Failed to save notes. Please try again.')
      return
    }
    await resolvePending(choice)
  }

  return (
    <div
      role="alertdialog"
      aria-live="assertive"
      aria-label="Unsaved notes"
      className="fixed inset-0 z-[100] flex flex-col items-center justify-center gap-4 bg-white/60 backdrop-blur-md"
    >
      <div className="flex w-full max-w-sm flex-col items-center gap-3 rounded-xl bg-white p-5 text-center shadow-xl">
        <p className="text-lg font-semibold text-gray-800">Unsaved notes</p>
        <p className="text-sm text-gray-500">
          You have unsaved changes in this tenant&apos;s notes. What would you like to do?
        </p>
        {error ? <p className="text-sm text-rose-500">{error}</p> : null}
        <div className="flex w-full flex-col gap-2">
          <button
            type="button"
            disabled={saving}
            onClick={() => handleChoice('save')}
            className="w-full rounded-xl bg-cyan-600 px-4 py-2.5 font-semibold text-white transition hover:bg-cyan-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? 'Saving...' : 'Save & Continue'}
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => handleChoice('discard')}
            className="w-full rounded-xl border border-rose-200 bg-white px-4 py-2.5 font-semibold text-rose-600 transition hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Discard & Continue
          </button>
          <button
            type="button"
            disabled={saving}
            onClick={() => handleChoice('cancel')}
            className="w-full rounded-xl border border-gray-300 px-4 py-2.5 font-semibold text-gray-700 transition hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
