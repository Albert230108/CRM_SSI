import { useEffect, useState } from 'react'
import { useAuthStore } from '../store/authStore'
import { clearDirectoryHandleForUser, getDirectoryHandleForUser, setDirectoryHandleForUser } from '../lib/fileHandleStore'

export default function Settings() {
  const userEmail = useAuthStore((state) => state.userEmail)
  const userKey = userEmail ?? 'anonymous'
  const [savedHandle, setSavedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [stagedHandle, setStagedHandle] = useState<FileSystemDirectoryHandle | null>(null)
  const [permissionState, setPermissionState] = useState<'granted' | 'prompt' | 'denied' | null>(null)
  const [unsupported, setUnsupported] = useState(false)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    setUnsupported(typeof window === 'undefined' || typeof window.showDirectoryPicker !== 'function')
  }, [])

  useEffect(() => {
    let cancelled = false

    const loadHandle = async () => {
      try {
        const handle = await getDirectoryHandleForUser(userKey)
        if (cancelled || !handle) return

        try {
          const perm = await handle.queryPermission({ mode: 'read' })
          if (cancelled) return

          if (perm === 'granted') {
            setSavedHandle(handle)
            setPermissionState('granted')
          } else if (perm === 'prompt') {
            setSavedHandle(handle)
            setPermissionState('prompt')
          } else {
            setPermissionState('denied')
          }
        } catch {
          if (cancelled) return
          setPermissionState('denied')
        }
      } catch {
        return
      }
    }

    setSavedHandle(null)
    setStagedHandle(null)
    setPermissionState(null)
    loadHandle()

    return () => {
      cancelled = true
    }
  }, [userKey])

  const handleStage = async () => {
    if (unsupported) return
    try {
      const dir = await window.showDirectoryPicker({ mode: 'read' })
      setStagedHandle(dir)
    } catch {
      return
    }
  }

  const handleSave = async () => {
    if (!stagedHandle) return
    try {
      setSaving(true)
      await setDirectoryHandleForUser(userKey, stagedHandle)
      setSavedHandle(stagedHandle)
      setPermissionState('granted')
      setStagedHandle(null)
    } catch {
      return
    } finally {
      setSaving(false)
    }
  }

  const handleClear = async () => {
    try {
      setSaving(true)
      await clearDirectoryHandleForUser(userKey)
      setSavedHandle(null)
      setStagedHandle(null)
      setPermissionState(null)
    } catch {
      return
    } finally {
      setSaving(false)
    }
  }

  const handleReconnect = async () => {
    if (!savedHandle) return
    try {
      const perm = await savedHandle.requestPermission({ mode: 'read' })
      setPermissionState(perm)
    } catch {
      setPermissionState('denied')
    }
  }

  const statusDot = (tone: 'green' | 'yellow' | 'red' | 'gray') => {
    const classes = {
      green: 'bg-green-500',
      yellow: 'bg-amber-400',
      red: 'bg-red-400',
      gray: 'bg-gray-300',
    }

    return <span className={`h-2.5 w-2.5 rounded-full ${classes[tone]}`} aria-hidden="true" />
  }

  return (
    <main className="mx-auto max-w-2xl px-6 py-6">
      <h1 className="text-2xl font-semibold text-gray-900">Settings</h1>
      <p className="text-sm text-gray-500">{userEmail ?? 'Signed in'}</p>

      <section className="mt-8 rounded-2xl border border-gray-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-gray-900">Local Folder</h2>
        <p className="mt-2 text-sm text-gray-500">
          Select the root folder on your computer where tenant files are stored. This setting is saved per user and restored on each visit.
        </p>

        {unsupported ? (
          <p className="mt-4 text-sm text-gray-600">Local folder access is not supported in this browser.</p>
        ) : (
          <div className="mt-4 space-y-4">
            <div className="flex items-center gap-2 text-sm text-gray-700">
              {savedHandle && permissionState === 'granted' ? statusDot('green') : null}
              {savedHandle && permissionState === 'prompt' ? statusDot('yellow') : null}
              {savedHandle && permissionState === 'denied' ? statusDot('red') : null}
              {!savedHandle ? statusDot('gray') : null}
              {savedHandle && permissionState === 'granted' ? `Connected - ${savedHandle.name}` : null}
              {savedHandle && permissionState === 'prompt' ? `Permission needed - ${savedHandle.name}` : null}
              {savedHandle && permissionState === 'denied' ? 'Access denied - choose a new folder' : null}
              {!savedHandle ? 'No folder selected' : null}
            </div>

            {stagedHandle ? (
              <p className="text-sm text-gray-600">Staged: {stagedHandle.name}</p>
            ) : null}

            <div className="flex flex-wrap gap-3">
              {savedHandle && permissionState === 'granted' ? (
                <button
                  type="button"
                  onClick={handleStage}
                  disabled={saving}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Change folder
                </button>
              ) : null}
              {savedHandle && permissionState === 'prompt' ? (
                <button
                  type="button"
                  onClick={handleReconnect}
                  disabled={saving}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Reconnect
                </button>
              ) : null}
              {savedHandle && permissionState === 'denied' ? (
                <button
                  type="button"
                  onClick={handleStage}
                  disabled={saving}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Choose new folder
                </button>
              ) : null}
              {!savedHandle ? (
                <button
                  type="button"
                  onClick={handleStage}
                  disabled={saving}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Choose folder
                </button>
              ) : null}
              {stagedHandle ? (
                <>
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={saving}
                    className="rounded-lg bg-gray-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-gray-800 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Save
                  </button>
                  <button
                    type="button"
                    onClick={() => setStagedHandle(null)}
                    disabled={saving}
                    className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                  >
                    Cancel
                  </button>
                </>
              ) : null}
              {savedHandle ? (
                <button
                  type="button"
                  onClick={handleClear}
                  disabled={saving}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-900 transition hover:border-gray-400 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Disconnect
                </button>
              ) : null}
            </div>
          </div>
        )}
      </section>
    </main>
  )
}
