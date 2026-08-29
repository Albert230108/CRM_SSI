type SkeletonProps = {
  className?: string
}

/**
 * Lightweight shimmer placeholder for loading states, replacing bare "Loading..."
 * text. Motion (animate-pulse) is disabled automatically under prefers-reduced-motion
 * via the global CSS guard in index.css.
 */
export default function Skeleton({ className = '' }: SkeletonProps) {
  return <div aria-hidden="true" className={`animate-pulse rounded-md bg-gray-200/70 ${className}`} />
}

/**
 * A stack of skeleton lines for text-block placeholders.
 */
export function SkeletonText({ lines = 3, className = '' }: { lines?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading" className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, index) => (
        <Skeleton key={index} className={`h-3 ${index === lines - 1 ? 'w-2/3' : 'w-full'}`} />
      ))}
    </div>
  )
}
