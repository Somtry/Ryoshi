/// 文件库操作(前端 HTTP 客户端)。
///
/// 设计意图:
///   原为 Server Actions,现调用后端 REST API。**契约与原 Server Action 一致**:
///   返回 `{ success, error?, files?, nextCursor?, hasMore? }`,调用方
///   (library-panel)按此判定,无需改动。
///   后端端点在阶段 4/任务 20 实现;未就绪时走 catch 返回 `{ success: false }`。

import { apiFetch } from '@/lib/api-client'
import type { LibraryFile } from '@/lib/db/schema'

/// 与原项目 FilesListCursor 对齐:按 (updatedAt, id) 排序的分页游标
export type FilesListCursor = {
  updatedAt: string
  id: string
}

/// 与原项目对齐:LibraryFile + 签名后的可访问 url
export type LibraryFileItem = LibraryFile & {
  key: string
  url: string
}

export async function listFiles({
  limit = 20,
  cursor
}: {
  limit?: number
  cursor?: FilesListCursor | null
} = {}): Promise<{
  success: boolean
  files?: LibraryFileItem[]
  nextCursor?: FilesListCursor | null
  hasMore?: boolean
  error?: string
}> {
  try {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', JSON.stringify(cursor))
    return await apiFetch(`/api/files?${params}`)
  } catch (error) {
    return {
      success: false,
      files: [],
      error: error instanceof Error ? error.message : 'Failed to load files'
    }
  }
}

export async function searchFiles({
  query,
  limit = 20
}: {
  query: string
  limit?: number
}): Promise<{
  success: boolean
  files?: LibraryFileItem[]
  nextCursor?: FilesListCursor | null
  hasMore?: boolean
  error?: string
}> {
  try {
    const params = new URLSearchParams({
      query: encodeURIComponent(query),
      limit: String(limit)
    })
    return await apiFetch(`/api/files?${params}`)
  } catch (error) {
    return {
      success: false,
      files: [],
      error: error instanceof Error ? error.message : 'Failed to search files'
    }
  }
}

export async function deleteFile(
  fileId: string
): Promise<{ success: boolean; error?: string }> {
  try {
    await apiFetch(`/api/files/${fileId}`, { method: 'DELETE' })
    return { success: true }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to delete file'
    }
  }
}
