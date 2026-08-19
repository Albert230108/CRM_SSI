export default function ConfirmDialog({
  title,
  description,
  confirmLabel,
  confirmingLabel,
  danger = true,
  loading,
  error,
  onConfirm,
  onCancel,
}: {
  title: string
  description: string
  confirmLabel: string
  confirmingLabel?: string
  danger?: boolean
  loading: boolean
  error?: string
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-gray-900/40 px-4 backdrop-blur-sm">
      <div className="w-full max-w-md rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
        <p className="mt-2 text-sm text-gray-600">{description}</p>
        {error ? <p className="mt-2 text-sm text-rose-600">{error}</p> : null}
        <div className="mt-4 flex justify-end gap-3">
          <button type="button" onClick={onCancel} className="rounded-xl px-4 py-2 text-sm text-gray-500 hover:text-gray-900">
            Cancel
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={onConfirm}
            className={`rounded-xl px-4 py-2 text-sm font-semibold text-white disabled:bg-gray-300 ${
              danger ? 'bg-rose-600 hover:bg-rose-700' : 'bg-cyan-600 hover:bg-cyan-700'
            }`}
          >
            {loading ? confirmingLabel ?? 'Working...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
