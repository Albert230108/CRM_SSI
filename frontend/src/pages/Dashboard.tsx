export default function Dashboard() {
  return (
    <main className="mx-auto max-w-7xl px-6 py-6">
      <div className="grid gap-4 lg:grid-cols-[25%_25%_50%]">
        <section className="min-h-[220px] rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-lg font-semibold text-white">Leads</h2>
          <p className="mt-2 text-sm text-slate-400">Left panel content.</p>
        </section>

        <section className="min-h-[220px] rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-lg font-semibold text-white">Tasks</h2>
          <p className="mt-2 text-sm text-slate-400">Center panel content.</p>
        </section>

        <section className="min-h-[220px] rounded-2xl border border-slate-800 bg-slate-900 p-5">
          <h2 className="text-lg font-semibold text-white">Workspace</h2>
          <p className="mt-2 text-sm text-slate-400">Right panel content.</p>
        </section>
      </div>
    </main>
  )
}
