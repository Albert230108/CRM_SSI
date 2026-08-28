import type { ReactNode } from 'react'
import InlineSpinner from './InlineSpinner'

type AiTemplateOption = {
  id: number
  name: string
}

type AiDraftControlsProps = {
  tenantId?: number
  channel: 'email' | 'whatsapp'
  message: string
  selectedTemplateId: string
  onSelectedTemplateIdChange: (value: string) => void
  templates: AiTemplateOption[]
  templateLoading?: boolean
  aiDraftGenerating: boolean
  plannerEnabled: boolean
  plannerRunning: boolean
  onGenerateAiDraft: () => void
  onRunPlanner: () => void
  onPreviewAiPayload?: () => void
  plannerRedoButton?: ReactNode
}

export default function AiDraftControls({
  tenantId,
  channel,
  message,
  selectedTemplateId,
  onSelectedTemplateIdChange,
  templates,
  templateLoading = false,
  aiDraftGenerating,
  plannerEnabled,
  plannerRunning,
  onGenerateAiDraft,
  onRunPlanner,
  onPreviewAiPayload,
  plannerRedoButton,
}: AiDraftControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-channel={channel} data-tenant-id={tenantId} data-message-length={message.trim().length}>
      <select
        value={selectedTemplateId}
        onChange={(event) => onSelectedTemplateIdChange(event.target.value)}
        disabled={templateLoading || aiDraftGenerating}
        className="min-w-[10rem] flex-1 rounded-lg border border-gray-300 bg-white px-2.5 py-1.5 text-sm text-gray-900 outline-none focus:border-indigo-500 disabled:cursor-not-allowed disabled:bg-gray-50"
      >
        <option value="">No AI template</option>
        {templates.map((template) => (
          <option key={template.id} value={template.id}>{template.name}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={onGenerateAiDraft}
        disabled={aiDraftGenerating || !selectedTemplateId}
        className="rounded-lg border border-indigo-300 bg-indigo-50 px-2.5 py-1 text-xs font-semibold text-indigo-700 hover:bg-indigo-100 disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className="inline-flex items-center gap-1.5">
          {aiDraftGenerating ? <InlineSpinner className="h-3 w-3" /> : null}
          {aiDraftGenerating ? 'Generating...' : 'Draft with AI'}
        </span>
      </button>
      {plannerEnabled ? (
        <button
          type="button"
          onClick={onRunPlanner}
          disabled={plannerRunning}
          title="Let the AI pick the template and draft the reply, then have it reviewed"
          className="rounded-lg border border-indigo-500 bg-indigo-600 px-2.5 py-1 text-xs font-semibold text-white hover:bg-indigo-700 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="inline-flex items-center gap-1.5">
            {plannerRunning ? <InlineSpinner className="h-3 w-3" /> : null}
            {plannerRunning ? 'Planning...' : 'Run planner'}
          </span>
        </button>
      ) : null}
      {plannerRedoButton}
      {onPreviewAiPayload ? (
        <button
          type="button"
          onClick={onPreviewAiPayload}
          disabled={!selectedTemplateId}
          title="Preview exact AI payload in a new tab"
          className="rounded-lg border border-gray-300 bg-white p-1.5 text-gray-600 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 6H18a1 1 0 0 1 1 1v4.5M18 6l-7 7M12 6H7a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-5" />
          </svg>
        </button>
      ) : null}
    </div>
  )
}
