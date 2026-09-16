import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '../store/authStore'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

type Agent = {
  role: string
  label: string
  description: string
  active_profiles: number
  total_profiles: number
  has_default: boolean
  tenants_pinned: number
  reads: string[]
}
type External = { key: string; label: string; kind: 'channel' | 'external' | 'crm' }
type Edge = { from: string; to: string; label: string; kind: EdgeKind }
type EdgeKind = 'flow' | 'loop' | 'trigger' | 'integration' | 'send' | 'context'
type Graph = { agents: Agent[]; externals: External[]; edges: Edge[] }

type Box = { x: number; y: number; w: number; h: number }

// Fixed topology layout. The graph data (counts, which context edges exist) is live; the
// on-canvas position of each known node is curated here so the diagram always reads cleanly.
const POS: Record<string, Box> = {
  // External / CRM knowledge the agents read (top band)
  beds24: { x: 40, y: 20, w: 150, h: 44 },
  notes: { x: 210, y: 20, w: 150, h: 44 },
  payments: { x: 380, y: 20, w: 150, h: 44 },
  brain: { x: 550, y: 20, w: 150, h: 44 },
  templates: { x: 720, y: 20, w: 170, h: 44 },
  // Channels on the left boundary (inbound in / reply out)
  email: { x: 30, y: 250, w: 150, h: 52 },
  whatsapp: { x: 30, y: 330, w: 150, h: 52 },
  // The reply pipeline
  planner: { x: 250, y: 288, w: 160, h: 66 },
  sales_manager: { x: 470, y: 180, w: 170, h: 66 },
  executor: { x: 470, y: 80, w: 170, h: 66 },
  drafter: { x: 470, y: 330, w: 160, h: 66 },
  checker: { x: 700, y: 330, w: 160, h: 66 },
  formatter: { x: 920, y: 330, w: 160, h: 66 },
  quotation_manager: { x: 720, y: 170, w: 180, h: 66 },
  // Independent agents (bottom band)
  brain_writer: { x: 250, y: 470, w: 160, h: 60 },
  action_writer: { x: 250, y: 555, w: 160, h: 60 },
}

const EDGE_STYLE: Record<EdgeKind, { color: string; dash?: string; label: string }> = {
  flow: { color: '#0891b2', label: 'Reply pipeline' },
  loop: { color: '#d97706', dash: '5 4', label: 'Redraft loop' },
  trigger: { color: '#6b7280', dash: '2 4', label: 'Inbound trigger' },
  integration: { color: '#4f46e5', label: 'External integration' },
  send: { color: '#059669', label: 'Outgoing send' },
  context: { color: '#9ca3af', dash: '3 5', label: 'Reads context' },
}

const KIND_FILL: Record<string, string> = {
  channel: '#ecfdf5',
  external: '#eef2ff',
  crm: '#f9fafb',
}

function center(b: Box) {
  return { x: b.x + b.w / 2, y: b.y + b.h / 2 }
}

// Point on `from`'s border along the line toward `to`, so an arrow stops at the box edge.
function borderPoint(from: Box, to: Box) {
  const c = center(from)
  const t = center(to)
  const dx = t.x - c.x
  const dy = t.y - c.y
  if (dx === 0 && dy === 0) return c
  const hw = from.w / 2
  const hh = from.h / 2
  const scale = Math.min(
    dx !== 0 ? hw / Math.abs(dx) : Infinity,
    dy !== 0 ? hh / Math.abs(dy) : Infinity,
  )
  return { x: c.x + dx * scale, y: c.y + dy * scale }
}

export default function AiAgentOverview() {
  useDocumentTitle('CRM - Agent Overview')
  const token = useAuthStore((state) => state.token)
  const [graph, setGraph] = useState<Graph | null>(null)
  const [error, setError] = useState('')
  const [showContext, setShowContext] = useState(true)

  const authHeaders = useMemo(() => (token ? { Authorization: `Bearer ${token}` } : undefined), [token])

  const load = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/ai-agent-profiles/graph`, { headers: authHeaders })
      if (!response.ok) {
        setError('Could not load the agent map.')
        return
      }
      setGraph(await response.json())
    } catch {
      setError('Could not load the agent map.')
    }
  }, [authHeaders])

  useEffect(() => {
    load()
  }, [load])

  const agentByRole = useMemo(() => {
    const map = new Map<string, Agent>()
    graph?.agents.forEach((agent) => map.set(agent.role, agent))
    return map
  }, [graph])

  const externalByKey = useMemo(() => {
    const map = new Map<string, External>()
    graph?.externals.forEach((ext) => map.set(ext.key, ext))
    return map
  }, [graph])

  const visibleEdges = useMemo(
    () => (graph?.edges ?? []).filter((e) => POS[e.from] && POS[e.to] && (showContext || e.kind !== 'context')),
    [graph, showContext],
  )

  return (
    <main className="mx-auto max-w-6xl animate-slide-up px-6 py-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Agent Overview</h1>
          <p className="mt-1 text-sm text-gray-600">
            How the AI agents connect and loop, and where they touch the rest of the CRM and external
            services. Counts reflect the live configuration.{' '}
            <Link to="/settings/ai-agents" className="text-brand-700 hover:underline">
              Back to profiles
            </Link>
          </p>
        </div>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={showContext} onChange={(e) => setShowContext(e.target.checked)} />
          Show context links
        </label>
      </div>

      {error ? <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p> : null}

      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-600">
        {Object.entries(EDGE_STYLE).map(([kind, style]) => (
          <span key={kind} className="inline-flex items-center gap-1.5">
            <svg width="22" height="8" aria-hidden>
              <line x1="1" y1="4" x2="21" y2="4" stroke={style.color} strokeWidth="2" strokeDasharray={style.dash} />
            </svg>
            {style.label}
          </span>
        ))}
      </div>

      <div className="overflow-x-auto rounded-2xl border border-gray-200 bg-white p-2 shadow-sm">
        <svg viewBox="0 0 1120 640" className="w-full" style={{ minWidth: 900 }} role="img" aria-label="Agent connection map">
          <defs>
            {Object.entries(EDGE_STYLE).map(([kind, style]) => (
              <marker key={kind} id={`arrow-${kind}`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill={style.color} />
              </marker>
            ))}
          </defs>

          {visibleEdges.map((edge, i) => {
            const a = POS[edge.from]
            const b = POS[edge.to]
            const p1 = borderPoint(a, b)
            const p2 = borderPoint(b, a)
            const style = EDGE_STYLE[edge.kind]
            return (
              <line
                key={i}
                x1={p1.x}
                y1={p1.y}
                x2={p2.x}
                y2={p2.y}
                stroke={style.color}
                strokeWidth={edge.kind === 'context' ? 1 : 2}
                strokeDasharray={style.dash}
                markerEnd={`url(#arrow-${edge.kind})`}
                opacity={edge.kind === 'context' ? 0.55 : 0.9}
              />
            )
          })}

          {Object.entries(POS).map(([key, box]) => {
            const agent = agentByRole.get(key)
            const ext = externalByKey.get(key)
            if (!agent && !ext) return null
            const isAgent = Boolean(agent)
            const fill = isAgent ? '#ffffff' : KIND_FILL[ext!.kind] ?? '#f9fafb'
            const stroke = isAgent ? '#0891b2' : '#c7cdd6'
            const label = agent?.label ?? ext?.label ?? key
            const node = (
              <g>
                <rect
                  x={box.x}
                  y={box.y}
                  width={box.w}
                  height={box.h}
                  rx={10}
                  fill={fill}
                  stroke={stroke}
                  strokeWidth={isAgent ? 1.5 : 1}
                />
                <text x={box.x + box.w / 2} y={box.y + (isAgent ? 22 : box.h / 2 + 4)} textAnchor="middle" fontSize="13" fontWeight={600} fill="#111827">
                  {label}
                </text>
                {isAgent ? (
                  <>
                    <text x={box.x + box.w / 2} y={box.y + 40} textAnchor="middle" fontSize="10.5" fill="#4b5563">
                      {agent!.active_profiles} active{agent!.has_default ? '' : ' · no default'}
                    </text>
                    <text x={box.x + box.w / 2} y={box.y + 54} textAnchor="middle" fontSize="10.5" fill="#4b5563">
                      {agent!.tenants_pinned} tenant{agent!.tenants_pinned === 1 ? '' : 's'} pinned
                    </text>
                  </>
                ) : null}
              </g>
            )
            return isAgent ? (
              <Link key={key} to={`/settings/ai-agents`} aria-label={`${label} profiles`} style={{ cursor: 'pointer' }}>
                {node}
              </Link>
            ) : (
              <g key={key}>{node}</g>
            )
          })}
        </svg>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {graph?.agents.map((agent) => (
          <div key={agent.role} className="rounded-2xl border border-gray-200 bg-white p-3">
            <p className="text-sm font-semibold text-gray-900">{agent.label}</p>
            <p className="mt-1 text-xs text-gray-600">{agent.description}</p>
            {agent.active_profiles === 0 ? (
              <p className="mt-1.5 text-xs font-medium text-amber-700">No active profile — this agent cannot run yet.</p>
            ) : null}
          </div>
        ))}
      </div>
    </main>
  )
}
