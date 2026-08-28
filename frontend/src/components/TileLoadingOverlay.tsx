type TileLoadingOverlayProps = {
  active: boolean
}

export default function TileLoadingOverlay({ active }: TileLoadingOverlayProps) {
  if (!active) return null

  return (
    <div
      role="status"
      aria-label="Loading tenant data"
      className="absolute inset-0 z-20 flex items-center justify-center rounded-2xl bg-white/50 backdrop-blur-sm"
    >
      <InlineSpinner size="md" className="text-cyan-600" />
    </div>
  )
}
import InlineSpinner from './InlineSpinner'
