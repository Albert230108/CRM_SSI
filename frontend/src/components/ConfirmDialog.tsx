import Modal from './ui/Modal'
import Button from './ui/Button'

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
    <Modal open onClose={onCancel} dismissable={!loading} className="w-full max-w-md" ariaLabel={title}>
      <div className="rounded-3xl border border-gray-200 bg-white p-4 shadow-sm">
        <h2 className="text-xl font-semibold text-gray-900">{title}</h2>
        <p className="mt-2 text-sm text-gray-600">{description}</p>
        {error ? <p className="mt-2 text-sm text-rose-600">{error}</p> : null}
        <div className="mt-4 flex justify-end gap-3">
          <Button variant="ghost" onClick={onCancel} disabled={loading}>
            Cancel
          </Button>
          <Button variant={danger ? 'danger' : 'primary'} loading={loading} onClick={onConfirm}>
            {loading ? confirmingLabel ?? 'Working...' : confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
