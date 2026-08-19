import type { ToastState } from '../lib/useToast'

export default function ToastHost({ toast, onDismiss }: { toast: ToastState; onDismiss: () => void }) {
  if (!toast) return null

  const tone =
    toast.kind === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
      : 'border-rose-200 bg-rose-50 text-rose-800'

  return (
    <div className={`fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-3 rounded-xl border px-4 py-3 text-sm shadow-lg ${tone}`} role="status">
      <p className="flex-1">{toast.message}</p>
      <button type="button" onClick={onDismiss} className="shrink-0 text-xs font-semibold opacity-70 hover:opacity-100" aria-label="Dismiss">
        &times;
      </button>
    </div>
  )
}
