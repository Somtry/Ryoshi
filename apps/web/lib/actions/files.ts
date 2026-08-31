/// 文件库操作(前端 HTTP 客户端)。原为 Server Actions,现调用后端 API。
/// 文件上传/列表/删除的后端端点在阶段 4 实现;阶段 3 这些功能未就绪。

import { apiFetch } from '@/lib/api-client'
import type { LibraryFile } from '@/lib/db/schema'

export async function listFiles(): Promise<LibraryFile[]> {
  return apiFetch('/api/files')
}

export async function searchFiles(query: string): Promise<LibraryFile[]> {
  return apiFetch(`/api/files?query=${encodeURIComponent(query)}`)
}

export async function deleteFile(fileId: string): Promise<void> {
  return apiFetch(`/api/files/${fileId}`, { method: 'DELETE' })
}
