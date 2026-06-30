import { useMemo, useState } from 'react'
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

  return (
    <main className="mx-auto max-w-7xl px-6 py-6">
      <div className="mb-5 flex items-center justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.35em] text-cyan-400">CRM Dashboard</p>
          <h1 className="mt-1 text-3xl font-semibold text-white">Tenant workspace</h1>
        </div>
        <button
          type="button"
          onClick={() => setImportModalOpen(true)}
          className="rounded-xl border border-cyan-500/40 bg-cyan-500/10 px-4 py-2 text-sm font-semibold text-cyan-300 transition hover:bg-cyan-500/20"
        >
          Import Beds24 bookings
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-[24%_24%_52%]">
        <section className="min-h-[220px] rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <TenantList selectedTenantId={selectedTenantId} />
        </section>

        <section className="min-h-[220px] rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <FinanceBox tenantId={selectedTenantId} />
        </section>

        <section className="min-h-[220px] rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <ThreadView tenantId={selectedTenantId} />
        </section>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[24%_24%_52%]">
        <div />
        <div />
        <section className="min-h-[220px] rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <OneDriveBox tenantId={selectedTenantId} />
        </section>
      </div>

      <ImportModal open={importModalOpen} onClose={() => setImportModalOpen(false)} />
    </main>
  )
}
