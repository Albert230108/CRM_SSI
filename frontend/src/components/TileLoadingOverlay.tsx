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
      <span className="h-8 w-8 animate-spin rounded-full border-2 border-cyan-600 border-t-transparent" />
    </div>
  )
}
