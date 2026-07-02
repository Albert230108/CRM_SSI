import { useEffect, useMemo, useState } from 'react'
import { useParams } from 'react-router-dom'
import FinanceBox from '../components/FinanceBox'
import ImportModal from '../components/ImportModal'
import OneDriveBox from '../components/OneDriveBox'
import TenantList from '../components/TenantList'
import ThreadView from '../components/ThreadView'

export default function Dashboard() {
  const { tenantId } = useParams()
  const selectedTenantId = useMemo(() => {
    const parsed = Number(tenantId)
    return Number.isFinite(parsed) ? parsed : undefined
  }, [tenantId])
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [tenantsCollapsed, setTenantsCollapsed] = useState(false)
  const [tenantReloadSignal, setTenantReloadSignal] = useState(0)

  useEffect(() => {
    const mediaQuery = window.matchMedia('(max-width: 767px)')
    const updateCollapsedState = () => setTenantsCollapsed(mediaQuery.matches)

    updateCollapsedState()
    mediaQuery.addEventListener('change', updateCollapsedState)
    return () => mediaQuery.removeEventListener('change', updateCollapsedState)
  }, [])

  return (
    <main className="flex h-screen w-full flex-col overflow-hidden px-6 py-6">
      <div className="mb-5 flex w-full items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold text-gray-900">Dashboard</h1>
        </div>
        <button
          type="button"
          onClick={() => setImportModalOpen(true)}
          className="rounded-xl border border-cyan-500/40 bg-cyan-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-cyan-700"
        >
          Import Beds24 bookings
        </button>
      </div>

      <div className="flex flex-row gap-4 flex-1 min-h-0 overflow-hidden">
        
        {/* LEFT COLUMN: Tenant List */}
        <section
          className={[
            'relative flex h-full shrink-0 overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm transition-all duration-300',
            tenantsCollapsed ? 'w-10' : 'w-[260px]',
          ].join(' ')}
        >
          <button
            type="button"
            onClick={() => setTenantsCollapsed((current) => !current)}
            aria-label={tenantsCollapsed ? 'Expand tenants panel' : 'Collapse tenants panel'}
            className="absolute right-0 top-4 z-10 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-l-xl border border-gray-200 border-r-0 bg-white text-sm font-semibold text-gray-600 shadow-sm transition hover:bg-gray-50"
          >
            {tenantsCollapsed ? '▶' : '◀'}
          </button>
          <div
            className={[
              'h-full min-w-[260px] overflow-hidden p-5 transition-all duration-300',
              tenantsCollapsed ? 'pointer-events-none opacity-0' : 'opacity-100',
            ].join(' ')}
          >
            <TenantList selectedTenantId={selectedTenantId} reloadSignal={tenantReloadSignal} />
          </div>
        </section>

        {/* MIDDLE COLUMN: Finance & OneDrive (UPDATED) */}
        <div className="flex min-w-0 flex-1 flex-col gap-4 h-full">
          <section className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex h-full min-h-0 flex-1 overflow-auto">
              <FinanceBox tenantId={selectedTenantId} />
            </div>
          </section>

          <section className="flex min-h-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
            <div className="flex h-full min-h-0 flex-1 overflow-auto">
              <OneDriveBox tenantId={selectedTenantId} />
            </div>
          </section>
        </div>

        {/* RIGHT COLUMN: Thread View */}
        <section className="flex min-w-0 flex-1 overflow-hidden rounded-2xl border border-gray-200 bg-white p-5 shadow-sm">
          <div className="h-full w-full min-h-0 overflow-hidden">
            <ThreadView tenantId={selectedTenantId} />
          </div>
        </section>
      </div>

      <ImportModal
        open={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        onImported={() => setTenantReloadSignal((current) => current + 1)}
      />
    </main>
  )
}
