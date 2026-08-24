import { useState, type ReactNode } from 'react'
import NotesBox from './NotesBox'
import TenantBrainBox from './TenantBrainBox'
import TenantActionsBox from './TenantActionsBox'

type TenantNotesPanelProps = {
  tenantId?: number
  onReady?: (tenantId: number) => void
}

type Tab = 'notes' | 'brain' | 'actions'

export default function TenantNotesPanel({ tenantId, onReady }: TenantNotesPanelProps) {
  const [tab, setTab] = useState<Tab>('notes')
  const [tabActions, setTabActions] = useState<ReactNode>(null)

  return (
    <div className="flex h-full w-full min-w-0 flex-col gap-1.5">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-gray-100">
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => setTab('notes')}
            className={`px-2.5 py-1 text-xs font-semibold ${
              tab === 'notes' ? 'border-b-2 border-cyan-500 text-cyan-700' : 'text-gray-400 hover:text-gray-600'
            }`}
          >
            Notes
          </button>
          <button
            type="button"
            onClick={() => setTab('brain')}
            className={`px-2.5 py-1 text-xs font-semibold ${
              tab === 'brain' ? 'border-b-2 border-cyan-500 text-cyan-700' : 'text-gray-400 hover:text-gray-600'
            }`}
          >
            Tenant Brain
          </button>
          <button
            type="button"
            onClick={() => setTab('actions')}
            className={`px-2.5 py-1 text-xs font-semibold ${
              tab === 'actions' ? 'border-b-2 border-cyan-500 text-cyan-700' : 'text-gray-400 hover:text-gray-600'
            }`}
          >
            Actions
          </button>
        </div>
        <div className="flex min-w-0 items-center justify-end gap-2">{tabActions}</div>
      </div>

      <div className="min-h-0 flex-1">
        {/* All three mount so NotesBox's autosave/onReady wiring never gets remounted by a tab
            switch; only the inactive ones are hidden. */}
        <div className={tab === 'notes' ? 'h-full' : 'hidden'}>
          <NotesBox tenantId={tenantId} onReady={onReady} isActive={tab === 'notes'} onActionsChange={setTabActions} />
        </div>
        <div className={tab === 'brain' ? 'h-full' : 'hidden'}>
          <TenantBrainBox tenantId={tenantId} isActive={tab === 'brain'} onActionsChange={setTabActions} />
        </div>
        <div className={tab === 'actions' ? 'h-full' : 'hidden'}>
          <TenantActionsBox tenantId={tenantId} isActive={tab === 'actions'} onActionsChange={setTabActions} />
        </div>
      </div>
    </div>
  )
}
