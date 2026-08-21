import { useState } from 'react'
import NotesBox from './NotesBox'
import TenantBrainBox from './TenantBrainBox'

type TenantNotesPanelProps = {
  tenantId?: number
  onReady?: (tenantId: number) => void
}

type Tab = 'notes' | 'brain'

export default function TenantNotesPanel({ tenantId, onReady }: TenantNotesPanelProps) {
  const [tab, setTab] = useState<Tab>('notes')

  return (
    <div className="flex h-full w-full min-w-0 flex-col gap-1.5">
      <div className="flex shrink-0 gap-1 border-b border-gray-100">
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
      </div>

      <div className="min-h-0 flex-1">
        {/* Both mount so NotesBox's autosave/onReady wiring never gets remounted by a tab
            switch; only the inactive one is hidden. */}
        <div className={tab === 'notes' ? 'h-full' : 'hidden'}>
          <NotesBox tenantId={tenantId} onReady={onReady} />
        </div>
        <div className={tab === 'brain' ? 'h-full' : 'hidden'}>
          <TenantBrainBox tenantId={tenantId} />
        </div>
      </div>
    </div>
  )
}
