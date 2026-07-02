export {}

declare global {
  type FileSystemPermissionMode = 'read' | 'readwrite'
  type PermissionState = 'granted' | 'denied' | 'prompt'

  interface FileSystemHandlePermissionDescriptor {
    mode?: FileSystemPermissionMode
  }

  interface FileSystemHandle {
    readonly kind: 'file' | 'directory'
    readonly name: string
    isSameEntry(other: FileSystemHandle): Promise<boolean>
    queryPermission(
      descriptor?: FileSystemHandlePermissionDescriptor
    ): Promise<PermissionState>
    requestPermission(
      descriptor?: FileSystemHandlePermissionDescriptor
    ): Promise<PermissionState>
  }

  interface FileSystemFileHandle extends FileSystemHandle {
    readonly kind: 'file'
    getFile(): Promise<File>
    createWritable(): Promise<FileSystemWritableFileStream>
  }

  interface FileSystemDirectoryHandle extends FileSystemHandle {
    readonly kind: 'directory'
    entries(): AsyncIterableIterator<[string, FileSystemHandle]>
    values(): AsyncIterableIterator<FileSystemHandle>
    keys(): AsyncIterableIterator<string>
    getFileHandle(
      name: string,
      options?: { create?: boolean }
    ): Promise<FileSystemFileHandle>
    getDirectoryHandle(
      name: string,
      options?: { create?: boolean }
    ): Promise<FileSystemDirectoryHandle>
  }

  interface Window {
    showDirectoryPicker(options?: {
      id?: string
      mode?: FileSystemPermissionMode
      startIn?: string | FileSystemHandle
    }): Promise<FileSystemDirectoryHandle>
  }
}