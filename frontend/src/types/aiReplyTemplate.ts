export type AiTemplateSection = {
  label: string
  content: string
  // Canvas-only metadata: never sent to the AI. Absent on templates saved before the canvas
  // editor existed, so every consumer must tolerate null/undefined.
  id?: string | null
  x?: number | null
  y?: number | null
  order?: number | null
  w?: number | null
  h?: number | null
  // Stacking order, shared with notes so a note can sit behind a card.
  z?: number | null
}

export type AiTemplateNote = {
  id: string
  text: string
  x: number
  y: number
  color?: string | null
  w?: number | null
  h?: number | null
  z?: number | null
}

export type AiReplyTemplate = {
  id: number
  name: string
  description: string | null
  guidelines: string | null
  sections: AiTemplateSection[]
  canvas_notes: AiTemplateNote[]
  brain_section_ids: number[]
  include_history: boolean
  history_message_limit: number | null
  include_beds24: boolean
  include_payments: boolean
  include_notes: boolean
}

export type BrainSectionOption = {
  id: number
  path: string
  title: string
  is_active: boolean
}

// Shared by the editor's help text and the popup editor's insert-token menu.
export const EMAIL_TEMPLATE_PLACEHOLDERS = [
  'tenant_name', 'first_name', 'last_name', 'email', 'phone', 'check_in', 'check_out',
  'num_nights', 'num_adults', 'num_children', 'room_name', 'property_name', 'booking_id',
  'booking_status', 'language', 'arrival_time', 'departure_time', 'city', 'country',
]
