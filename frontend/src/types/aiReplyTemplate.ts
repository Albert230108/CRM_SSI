export type AiTemplateSection = {
  label: string
  content: string
  // Canvas-only metadata: never sent to the AI. Absent on templates saved before the canvas
  // editor existed.
  id?: string | null
  x?: number | null
  y?: number | null
  order?: number | null
}

export type AiTemplateNote = {
  id: string
  text: string
  x: number
  y: number
  color?: string | null
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
