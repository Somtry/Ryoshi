/// 聊天相关操作(前端 HTTP 客户端)。
///
/// 设计意图:
///   原为 Next Server Actions('use server'),直接操作数据库;
///   现改为调用后端 REST API。函数签名与组件调用处保持一致,组件无需改动。
///   阶段 3 仅聊天主流程可用,历史/分享等端点在阶段 4 由后端实现,
///   未就绪的调用会抛 ApiError,组件按既有降级逻辑处理。

import { apiFetch } from '@/lib/api-client'
import type { UIMessage } from '@/lib/types/ai'

export interface ChatSummary {
  id: string
  title: string
  createdAt: string
  visibility: 'public' | 'private'
}

/// 拉取当前用户的聊天列表
export async function getChats(): Promise<ChatSummary[]> {
  return apiFetch('/api/chats')
}

export async function getChatsPage(limit = 20, offset = 0) {
  return apiFetch(`/api/chats?limit=${limit}&offset=${offset}`)
}

/// 按 id 加载一场聊天(含消息历史)
export async function loadChat(
  chatId: string,
  _userId?: string | null
): Promise<{ messages: UIMessage[]; title: string; visibility: string } | null> {
  try {
    return await apiFetch(`/api/chats/${chatId}`)
  } catch {
    return null
  }
}

export async function deleteChat(chatId: string): Promise<void> {
  return apiFetch(`/api/chats/${chatId}`, { method: 'DELETE' })
}

export async function clearChats(): Promise<void> {
  return apiFetch('/api/chats', { method: 'DELETE' })
}

export async function deleteMessagesAfter(
  chatId: string,
  messageId: string
): Promise<void> {
  return apiFetch(`/api/chats/${chatId}/messages/after/${messageId}`, {
    method: 'DELETE'
  })
}

/// 分享聊天:把可见性设为 public 并返回可分享的 id
export async function shareChat(chatId: string): Promise<string> {
  const result = await apiFetch<{ shareId: string }>(
    `/api/chats/${chatId}/share`,
    { method: 'POST' }
  )
  return result.shareId
}
