import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useLocation } from 'react-router-dom'
import Button from './ui/Button'
import AiChatComposer from './AiChatComposer'
import { useAuthStore } from '../store/authStore'
import { useDraggablePosition } from '../hooks/useDraggablePosition'
import { getUserPreferenceKey } from '../lib/dashboardLayoutPreferences'
import { getScreenContext } from '../lib/screenContext'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''
const POSITION_STORAGE_PREFIX = 'crm_ssi.ai-assistant.fab-position.'

type ConversationRead = {
  id: number
  title: string
  created_at: string
  updated_at: string
}

type AssistantMessageRead = {
  id: number
  role: 'user' | 'assistant'
  content: string
  tool_trace: { knowledge_suggestion?: { title: string; body: string } | null } | null
  created_at: string
}

type KnowledgeEntry = {
  id: number
  title: string
  body: string
  category: string | null
  source: string
  created_at: string
  updated_at: string
}

function loadStoredPosition(userKey: string | null): { x: number; y: number } {
  if (!userKey) return { x: 0, y: 0 }
  try {
    const raw = window.localStorage.getItem(`${POSITION_STORAGE_PREFIX}${userKey}`)
    if (!raw) return { x: 0, y: 0 }
    const parsed = JSON.parse(raw)
    if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') return { x: parsed.x, y: parsed.y }
  } catch {
    // Ignore corrupt/unavailable storage - the widget just starts at its default spot.
  }
  return { x: 0, y: 0 }
}

function getWidgetHost(): HTMLElement {
  const existing = document.getElementById('crm-ai-assistant-host')
  if (existing) return existing
  const host = document.createElement('div')
  host.id = 'crm-ai-assistant-host'
  document.body.appendChild(host)
  return host
}

export default function AiAssistantWidget() {
  const token = useAuthStore((state) => state.token)
  const user = useAuthStore((state) => state.user)
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated)
  const location = useLocation()
  const authHeaders = token ? { Authorization: `Bearer ${token}` } : undefined
  const userKey = getUserPreferenceKey(user)
  const { position, handlePointerDown, style } = useDraggablePosition(loadStoredPosition(userKey))
  const draggedRef = useRef(false)
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'chat' | 'knowledge'>('chat')

  const [conversations, setConversations] = useState<ConversationRead[]>([])
  const [conversationMenuOpen, setConversationMenuOpen] = useState(false)
  const [currentConversationId, setCurrentConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<AssistantMessageRead[]>([])
  const [question, setQuestion] = useState('')
  const [sending, setSending] = useState(false)
  const [useCrm, setUseCrm] = useState(false)
  const [error, setError] = useState('')

  const [knowledge, setKnowledge] = useState<KnowledgeEntry[]>([])
  const [knowledgeLoaded, setKnowledgeLoaded] = useState(false)
  const [newKnowledgeTitle, setNewKnowledgeTitle] = useState('')
  const [newKnowledgeBody, setNewKnowledgeBody] = useState('')

  // Persist the FAB position per user as it's dragged. It's read back via loadStoredPosition()
  // as the drag hook's initial state above - this only takes effect on the next full mount
  // (e.g. after a reload), since useDraggablePosition doesn't expose a way to reset mid-session.
  useEffect(() => {
    if (!userKey) return
    try {
      window.localStorage.setItem(`${POSITION_STORAGE_PREFIX}${userKey}`, JSON.stringify({ x: position.x, y: position.y }))
    } catch {
      // Best-effort only.
    }
  }, [position.x, position.y, userKey])

  const loadConversations = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/ai-assistant/conversations`, { headers: authHeaders })
      if (!response.ok) return
      const data = (await response.json()) as ConversationRead[]
      setConversations(Array.isArray(data) ? data : [])
    } catch {
      // The widget still works for the current session even if the history list fails to load.
    }
  }

  const loadMessages = async (conversationId: number) => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/ai-assistant/conversations/${conversationId}`, { headers: authHeaders })
      if (!response.ok) return
      const data = (await response.json()) as AssistantMessageRead[]
      setMessages(Array.isArray(data) ? data : [])
    } catch {
      setError('Failed to load this conversation')
    }
  }

  useEffect(() => {
    if (open && isAuthenticated) void loadConversations()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, isAuthenticated])

  useEffect(() => {
    if (currentConversationId != null) void loadMessages(currentConversationId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentConversationId])

  const startNewChat = () => {
    setCurrentConversationId(null)
    setMessages([])
    setError('')
    setConversationMenuOpen(false)
  }

  const openConversation = (conversationId: number) => {
    setCurrentConversationId(conversationId)
    setError('')
    setConversationMenuOpen(false)
  }

  const deleteConversation = async (conversationId: number) => {
    try {
      await fetch(`${API_BASE_URL}/api/ai-assistant/conversations/${conversationId}`, {
        method: 'DELETE',
        headers: authHeaders,
      })
      if (currentConversationId === conversationId) startNewChat()
      await loadConversations()
    } catch {
      setError('Failed to delete conversation')
    }
  }

  const askQuestion = async () => {
    const prompt = question.trim()
    if (!prompt || sending) return
    try {
      setSending(true)
      setError('')
      setQuestion('')

      let conversationId = currentConversationId
      if (conversationId == null) {
        const createResponse = await fetch(`${API_BASE_URL}/api/ai-assistant/conversations`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
          body: JSON.stringify({}),
        })
        if (!createResponse.ok) throw new Error('Failed to start a conversation')
        const created = (await createResponse.json()) as ConversationRead
        conversationId = created.id
        setCurrentConversationId(created.id)
      }

      setMessages((current) => [
        ...current,
        { id: -Date.now(), role: 'user', content: prompt, tool_trace: null, created_at: new Date().toISOString() },
      ])

      const screenContext = getScreenContext(location.pathname)
      const response = await fetch(`${API_BASE_URL}/api/ai-assistant/conversations/${conversationId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ question: prompt, screen_context: screenContext, use_crm: useCrm }),
      })
      if (!response.ok) throw new Error('Failed to get an answer')
      const assistantMessage = (await response.json()) as AssistantMessageRead
      setMessages((current) => [...current, assistantMessage])
      await loadConversations()
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to get an answer'
      setError(message)
    } finally {
      setSending(false)
    }
  }

  const saveKnowledgeSuggestion = async (suggestion: { title: string; body: string }) => {
    try {
      await fetch(`${API_BASE_URL}/api/ai-assistant/knowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ title: suggestion.title, body: suggestion.body, source: 'ai' }),
      })
      if (knowledgeLoaded) await loadKnowledge()
    } catch {
      setError('Failed to save that to the knowledge base')
    }
  }

  const loadKnowledge = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/api/ai-assistant/knowledge`, { headers: authHeaders })
      if (!response.ok) return
      const data = (await response.json()) as KnowledgeEntry[]
      setKnowledge(Array.isArray(data) ? data : [])
      setKnowledgeLoaded(true)
    } catch {
      setError('Failed to load the knowledge base')
    }
  }

  useEffect(() => {
    if (open && tab === 'knowledge' && !knowledgeLoaded) void loadKnowledge()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, tab, knowledgeLoaded])

  const addKnowledgeEntry = async () => {
    const title = newKnowledgeTitle.trim()
    const body = newKnowledgeBody.trim()
    if (!title || !body) return
    try {
      await fetch(`${API_BASE_URL}/api/ai-assistant/knowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...(authHeaders ?? {}) },
        body: JSON.stringify({ title, body }),
      })
      setNewKnowledgeTitle('')
      setNewKnowledgeBody('')
      await loadKnowledge()
    } catch {
      setError('Failed to save the knowledge base entry')
    }
  }

  const deleteKnowledgeEntry = async (entryId: number) => {
    try {
      await fetch(`${API_BASE_URL}/api/ai-assistant/knowledge/${entryId}`, { method: 'DELETE', headers: authHeaders })
      await loadKnowledge()
    } catch {
      setError('Failed to delete the knowledge base entry')
    }
  }

  if (!isAuthenticated) return null

  return createPortal(
    <>
      <button
        type="button"
        onPointerDown={(event) => {
          draggedRef.current = false
          const onMove = () => {
            draggedRef.current = true
          }
          window.addEventListener('pointermove', onMove, { once: true })
          handlePointerDown(event)
        }}
        onClick={() => {
          if (!draggedRef.current) setOpen((current) => !current)
        }}
        style={{ ...style, position: 'fixed', bottom: '1.5rem', right: '1.5rem', zIndex: 100 }}
        className="flex h-12 w-12 items-center justify-center rounded-full bg-indigo-600 text-white shadow-lg transition hover:bg-indigo-700 active:scale-95"
        aria-label={open ? 'Close CRM assistant' : 'Open CRM assistant'}
        title="CRM Assistant"
      >
        <span className="text-lg" aria-hidden="true">
          {open ? '×' : '✦'}
        </span>
      </button>

      {open ? (
        <div
          style={{ position: 'fixed', bottom: '5.5rem', right: '1.5rem', zIndex: 100 }}
          className="flex h-[32rem] w-[23rem] max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-2xl border border-indigo-200 bg-white shadow-2xl"
        >
          <div className="flex items-center justify-between gap-2 border-b border-gray-100 bg-indigo-50/60 px-3 py-2">
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-indigo-700">CRM Assistant</p>
            </div>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => setTab(tab === 'chat' ? 'knowledge' : 'chat')}
                className="rounded-full border border-indigo-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-indigo-700 hover:bg-indigo-50"
              >
                {tab === 'chat' ? 'Knowledge' : 'Back to chat'}
              </button>
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="rounded-full border border-gray-200 bg-white px-2 py-1 text-[11px] font-semibold text-gray-600 hover:bg-gray-50"
                aria-label="Close"
              >
                ×
              </button>
            </div>
          </div>

          {tab === 'chat' ? (
            <>
              <div className="flex items-center justify-between gap-2 border-b border-gray-100 px-3 py-1.5">
                <div className="relative min-w-0 flex-1">
                  <button
                    type="button"
                    onClick={() => setConversationMenuOpen((v) => !v)}
                    className="max-w-full truncate rounded-lg px-1.5 py-1 text-left text-xs font-medium text-gray-600 hover:bg-gray-50"
                  >
                    {currentConversationId
                      ? conversations.find((c) => c.id === currentConversationId)?.title ?? 'Chat'
                      : 'New chat'}{' '}
                    ▾
                  </button>
                  {conversationMenuOpen ? (
                    <div className="absolute left-0 top-full z-10 mt-1 max-h-56 w-64 overflow-auto rounded-xl border border-gray-200 bg-white p-1 shadow-lg">
                      <button
                        type="button"
                        onClick={startNewChat}
                        className="block w-full rounded-lg px-2 py-1.5 text-left text-xs font-semibold text-indigo-700 hover:bg-indigo-50"
                      >
                        + New chat
                      </button>
                      {conversations.map((conversation) => (
                        <div key={conversation.id} className="group flex items-center gap-1">
                          <button
                            type="button"
                            onClick={() => openConversation(conversation.id)}
                            className={`min-w-0 flex-1 truncate rounded-lg px-2 py-1.5 text-left text-xs ${
                              conversation.id === currentConversationId ? 'bg-indigo-50 text-indigo-700' : 'text-gray-700 hover:bg-gray-50'
                            }`}
                          >
                            {conversation.title}
                          </button>
                          <button
                            type="button"
                            onClick={() => void deleteConversation(conversation.id)}
                            className="shrink-0 rounded px-1 text-[11px] text-gray-400 opacity-0 hover:text-rose-500 group-hover:opacity-100"
                            aria-label="Delete conversation"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                      {conversations.length === 0 ? <p className="px-2 py-1.5 text-xs text-gray-400">No saved chats yet</p> : null}
                    </div>
                  ) : null}
                </div>
                <label className="flex shrink-0 items-center gap-1 text-[11px] text-gray-500">
                  <input type="checkbox" checked={useCrm} onChange={(event) => setUseCrm(event.target.checked)} className="accent-indigo-600" />
                  Search CRM
                </label>
              </div>

              <div className="min-h-0 flex-1 space-y-2 overflow-auto bg-gray-50/40 p-3">
                {messages.length === 0 ? (
                  <p className="text-xs text-gray-400">
                    Ask where something is, how a workflow works, or (with "Search CRM" on) about a tenant or booking.
                  </p>
                ) : (
                  messages.map((message) => (
                    <div key={message.id} className="space-y-1">
                      <div
                        className={`max-w-[90%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${
                          message.role === 'user' ? 'ml-auto bg-indigo-600 text-white' : 'mr-auto bg-white text-gray-700 shadow-sm'
                        }`}
                      >
                        {message.content}
                      </div>
                      {message.role === 'assistant' && message.tool_trace?.knowledge_suggestion ? (
                        <div className="mr-auto max-w-[90%] rounded-xl border border-dashed border-indigo-200 bg-indigo-50/60 px-3 py-2 text-xs text-indigo-800">
                          <p className="mb-1 font-semibold">Add "{message.tool_trace.knowledge_suggestion.title}" to the knowledge base?</p>
                          <button
                            type="button"
                            onClick={() => void saveKnowledgeSuggestion(message.tool_trace!.knowledge_suggestion!)}
                            className="rounded-full border border-indigo-300 bg-white px-2.5 py-1 font-semibold text-indigo-700 hover:bg-indigo-100"
                          >
                            Save to knowledge base
                          </button>
                        </div>
                      ) : null}
                    </div>
                  ))
                )}
              </div>

              {error ? <p className="px-3 py-1 text-xs font-medium text-rose-500">{error}</p> : null}

              <div className="border-t border-gray-100 p-2">
                <AiChatComposer
                  value={question}
                  onChange={setQuestion}
                  onSubmit={() => void askQuestion()}
                  placeholder="Ask the CRM assistant..."
                  disabled={sending}
                  busy={sending}
                  className="border-0 p-0 shadow-none"
                />
              </div>
            </>
          ) : (
            <div className="min-h-0 flex-1 overflow-auto p-3">
              <p className="mb-2 text-xs text-gray-500">
                Entries here are what the assistant searches to answer "how does this work" questions - add one yourself, or save a suggestion from a chat.
              </p>
              <div className="mb-3 space-y-1.5 rounded-xl border border-gray-200 bg-gray-50/60 p-2">
                <input
                  value={newKnowledgeTitle}
                  onChange={(event) => setNewKnowledgeTitle(event.target.value)}
                  placeholder="Title"
                  className="w-full rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs outline-none focus:border-indigo-300"
                />
                <textarea
                  value={newKnowledgeBody}
                  onChange={(event) => setNewKnowledgeBody(event.target.value)}
                  placeholder="What should staff know?"
                  rows={2}
                  className="w-full resize-none rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-xs outline-none focus:border-indigo-300"
                />
                <Button variant="ai" size="sm" onClick={() => void addKnowledgeEntry()} disabled={!newKnowledgeTitle.trim() || !newKnowledgeBody.trim()}>
                  Add entry
                </Button>
              </div>

              <div className="space-y-2">
                {knowledge.map((entry) => (
                  <div key={entry.id} className="rounded-xl border border-gray-200 bg-white p-2 text-xs">
                    <div className="mb-1 flex items-start justify-between gap-2">
                      <p className="font-semibold text-gray-800">{entry.title}</p>
                      <div className="flex shrink-0 items-center gap-1">
                        {entry.source === 'ai' ? (
                          <span className="rounded-full bg-indigo-100 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-700">AI</span>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => void deleteKnowledgeEntry(entry.id)}
                          className="rounded px-1 text-gray-400 hover:text-rose-500"
                          aria-label="Delete entry"
                        >
                          ×
                        </button>
                      </div>
                    </div>
                    <p className="whitespace-pre-wrap text-gray-600">{entry.body}</p>
                  </div>
                ))}
                {knowledge.length === 0 ? <p className="text-xs text-gray-400">No entries yet.</p> : null}
              </div>
            </div>
          )}
        </div>
      ) : null}
    </>,
    getWidgetHost(),
  )
}
