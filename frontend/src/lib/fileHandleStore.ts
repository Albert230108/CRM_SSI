const DB_NAME = 'crm-ssi-fs'
const STORE_NAME = 'directory-handles'

type HandleRecord = {
  userKey: string
  handle: FileSystemDirectoryHandle
}

let dbPromise: Promise<IDBDatabase | null> | null = null

function openDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise

  dbPromise = new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') {
      resolve(null)
      return
    }

    const request = indexedDB.open(DB_NAME, 1)

    request.onupgradeneeded = () => {
      const db = request.result
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'userKey' })
      }
    }

    request.onsuccess = () => resolve(request.result)
    request.onerror = () => resolve(null)
    request.onblocked = () => resolve(null)
  })

  return dbPromise
}

export async function getDirectoryHandleForUser(userKey: string): Promise<FileSystemDirectoryHandle | null> {
  try {
    const db = await openDb()
    if (!db) return null

    return await new Promise<FileSystemDirectoryHandle | null>((resolve) => {
      const transaction = db.transaction(STORE_NAME, 'readonly')
      const store = transaction.objectStore(STORE_NAME)
      const request = store.get(userKey)

      request.onsuccess = () => {
        const record = request.result as HandleRecord | undefined
        resolve(record?.handle ?? null)
      }
      request.onerror = () => resolve(null)
    })
  } catch {
    return null
  }
}

export async function setDirectoryHandleForUser(userKey: string, handle: FileSystemDirectoryHandle): Promise<void> {
  try {
    const db = await openDb()
    if (!db) return

    await new Promise<void>((resolve) => {
      const transaction = db.transaction(STORE_NAME, 'readwrite')
      const store = transaction.objectStore(STORE_NAME)
      store.put({ userKey, handle })
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => resolve()
      transaction.onabort = () => resolve()
    })
  } catch {
    return
  }
}

export async function clearDirectoryHandleForUser(userKey: string): Promise<void> {
  try {
    const db = await openDb()
    if (!db) return

    await new Promise<void>((resolve) => {
      const transaction = db.transaction(STORE_NAME, 'readwrite')
      const store = transaction.objectStore(STORE_NAME)
      store.delete(userKey)
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => resolve()
      transaction.onabort = () => resolve()
    })
  } catch {
    return
  }
}
