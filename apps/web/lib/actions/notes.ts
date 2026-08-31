/// 笔记操作(前端 HTTP 客户端)。原为 Server Actions,现调用后端 API。
/// 笔记的后端端点在阶段 4 实现;阶段 3 这些功能未就绪。

import { apiFetch } from '@/lib/api-client'
import type { Note } from '@/lib/db/schema'

export interface SaveNoteInput {
  title: string
  content: string
  chatId?: string | null
  sourceMessageId?: string | null
}

export async function saveNote(input: SaveNoteInput): Promise<Note> {
  return apiFetch('/api/notes', { method: 'POST', body: JSON.stringify(input) })
}

export async function listNotes(): Promise<Note[]> {
  return apiFetch('/api/notes')
}

export async function searchNotes(query: string): Promise<Note[]> {
  return apiFetch(`/api/notes?query=${encodeURIComponent(query)}`)
}

export async function getNote(noteId: string): Promise<Note | null> {
  try {
    return await apiFetch(`/api/notes/${noteId}`)
  } catch {
    return null
  }
}

export async function deleteNote(noteId: string): Promise<void> {
  return apiFetch(`/api/notes/${noteId}`, { method: 'DELETE' })
}
