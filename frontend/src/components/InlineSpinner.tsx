type InlineSpinnerProps = {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const SIZE_CLASSES = {
  sm: 'h-3 w-3 border-2',
  md: 'h-8 w-8 border-2',
  lg: 'h-12 w-12 border-4',
}

export default function InlineSpinner({ size = 'sm', className = '' }: InlineSpinnerProps) {
  return <span aria-hidden="true" className={`inline-block shrink-0 animate-spin rounded-full border-current border-t-transparent ${SIZE_CLASSES[size]} ${className}`} />
}
