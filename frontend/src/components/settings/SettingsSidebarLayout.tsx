import { ReactNode } from 'react'

export type SettingsTab = {
  id: string
  label: string
}

export default function SettingsSidebarLayout({
  title,
  subtitle,
  crossLink,
  tabs,
  activeTab,
  onTabChange,
  children,
  maxWidthClassName = 'max-w-6xl',
}: {
  title: string
  subtitle?: ReactNode
  crossLink?: ReactNode
  tabs: SettingsTab[]
  activeTab: string
  onTabChange: (id: string) => void
  children: ReactNode
  maxWidthClassName?: string
}) {
  return (
    <main className={`mx-auto ${maxWidthClassName} px-6 py-4`}>
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">{title}</h1>
          {subtitle ? <p className="mt-1 text-sm text-gray-500">{subtitle}</p> : null}
        </div>
        {crossLink ? <div className="shrink-0">{crossLink}</div> : null}
      </div>

      <div className="mt-4 flex flex-col gap-4 md:flex-row">
        <nav className="flex shrink-0 gap-1.5 overflow-x-auto md:w-48 md:flex-col md:overflow-visible">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={`whitespace-nowrap rounded-xl px-3.5 py-2.5 text-left text-sm font-medium transition ${
                activeTab === tab.id
                  ? 'bg-cyan-600 text-white'
                  : 'text-gray-700 hover:bg-gray-100'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>

        <div className="min-w-0 flex-1 space-y-4">{children}</div>
      </div>
    </main>
  )
}
