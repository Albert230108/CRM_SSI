type InlineSpinnerProps = {
  className?: string
}

export default function InlineSpinner({ className = '' }: InlineSpinnerProps) {
  return <span aria-hidden="true" className={`inline-block shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent ${className}`} />
}
