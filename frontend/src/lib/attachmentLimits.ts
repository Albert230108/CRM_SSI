export const MAX_FILE_BYTES = 10 * 1024 * 1024
export const MAX_EMAIL_TOTAL_BYTES = 20 * 1024 * 1024
export const MAX_WHATSAPP_TOTAL_BYTES = 25 * 1024 * 1024

export type AttachmentChannel = 'email' | 'whatsapp'

export function maxTotalBytesFor(channel: AttachmentChannel): number {
  // Email is capped lower than WhatsApp: Gmail's raw send tops out near 35MB, and 25MB of
  // files base64-encodes to ~33.3MB before headers and any quoted thread body.
  return channel === 'email' ? MAX_EMAIL_TOTAL_BYTES : MAX_WHATSAPP_TOTAL_BYTES
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

export type AttachmentValidationError = { filename: string; reason: string }

/**
 * Client-side pre-flight against the same caps the server enforces. This is UX only - the
 * upload endpoint re-validates every file.
 */
export function validateAttachmentSelection(
  files: { name: string; size: number }[],
  channel: AttachmentChannel,
  alreadySelectedBytes = 0,
): AttachmentValidationError[] {
  const errors: AttachmentValidationError[] = []
  const totalLimit = maxTotalBytesFor(channel)
  let running = alreadySelectedBytes

  for (const file of files) {
    if (file.size > MAX_FILE_BYTES) {
      errors.push({
        filename: file.name,
        reason: `exceeds the ${formatBytes(MAX_FILE_BYTES)} per-file limit`,
      })
      continue
    }
    running += file.size
    if (running > totalLimit) {
      errors.push({
        filename: file.name,
        reason: `would exceed the ${formatBytes(totalLimit)} total limit for ${channel}`,
      })
    }
  }

  return errors
}
