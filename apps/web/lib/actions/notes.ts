/// 笔记操作(前端 HTTP 客户端)。
///
/// 设计意图:
///   原为 Server Actions,现调用后端 REST API。**契约与原 Server Action 一致**:
///   返回 `{ success, error?, note?/notes?, nextCursor?, hasMore? }`,调用方
///   (answer-section、message-actions、library-panel)按此判定,无需改动。
///   后端端点在阶段 4/任务 20 实现;未就绪时走 catch 返回 `{ success: false }`。

import { apiFetch } from '@/lib/api-client'
import type { Note } from '@/lib/db/schema'

/// 与原项目 NotesListCursor 对齐:按 (updatedAt, id) 排序的分页游标
export type NotesListCursor = {
  updatedAt: string
  id: string
}

export interface SaveNoteInput {
  content: string
  title?: string
  chatId?: string | null
  sourceMessageId?: string | null
}

export async function saveNote(
  input: SaveNoteInput
): Promise<{ success: boolean; note?: Note; error?: string }> {
  try {
    const note = await apiFetch<Note>('/api/notes', {
      method: 'POST',
      body: JSON.stringify(input)
    })
    return { success: true, note }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to save note'
    }
  }
}

export async function listNotes({
  limit = 20,
  cursor
}: {
  limit?: number
  cursor?: NotesListCursor | null
} = {}): Promise<{
  success: boolean
  notes?: Note[]
  nextCursor?: NotesListCursor | null
  hasMore?: boolean
  error?: string
}> {
  try {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', JSON.stringify(cursor))
    return await apiFetch(`/api/notes?${params}`)
  } catch (error) {
    return {
      success: false,
      notes: [],
      error: error instanceof Error ? error.message : 'Failed to load notes'
    }
  }
}

export async function searchNotes({
  query,
  limit = 20
}: {
  query: string
  limit?: number
}): Promise<{
  success: boolean
  notes?: Note[]
  nextCursor?: NotesListCursor | null
  hasMore?: boolean
  error?: string
}> {
  try {
    const params = new URLSearchParams({
      query: encodeURIComponent(query),
      limit: String(limit)
    })
    return await apiFetch(`/api/notes?${params}`)
  } catch (error) {
    return {
      success: false,
      notes: [],
      error: error instanceof Error ? error.message : 'Failed to search notes'
    }
  }
}

export async function getNote(noteId: string): Promise<Note | null> {
  try {
    return await apiFetch(`/api/notes/${noteId}`)
  } catch {
    return null
  }
}

export async function deleteNote(
  noteId: string
): Promise<{ success: boolean; error?: string }> {
  try {
    await apiFetch(`/api/notes/${noteId}`, { method: 'DELETE' })
    return { success: true }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to delete note'
    }
  }
}
