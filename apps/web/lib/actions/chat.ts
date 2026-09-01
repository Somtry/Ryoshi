/// 聊天相关操作(前端 HTTP 客户端)。
///
/// 设计意图:
///   原为 Next Server Actions('use server'),直接操作数据库;
///   现改为调用后端 REST API。**契约与原 Server Action 一致**:返回
///   `{ success, error?, ... }` 形状,调用方(chat-menu-item、clear-history、
///   chat-share 等)按此判定,无需改动。
///   后端对应端点在阶段 4/任务 19-20 逐步实现;未就绪的会在 catch 分支
///   返回 `{ success: false, error }`,组件按既有降级逻辑处理。

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

export async function deleteChat(
  chatId: string
): Promise<{ success: boolean; error?: string }> {
  try {
    await apiFetch(`/api/chats/${chatId}`, { method: 'DELETE' })
    return { success: true }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to delete chat'
    }
  }
}

export async function clearChats(): Promise<{
  success: boolean
  error?: string
}> {
  try {
    await apiFetch('/api/chats', { method: 'DELETE' })
    return { success: true }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to clear history'
    }
  }
}

export async function deleteMessagesAfter(
  chatId: string,
  messageId: string
): Promise<{ success: boolean; error?: string }> {
  try {
    await apiFetch(`/api/chats/${chatId}/messages/after/${messageId}`, {
      method: 'DELETE'
    })
    return { success: true }
  } catch (error) {
    return {
      success: false,
      error:
        error instanceof Error ? error.message : 'Failed to delete messages'
    }
  }
}

/// 分享聊天:把可见性设为 public 并返回可分享的 id。
/// 原项目返回更新后的 Chat 对象;这里对齐调用方实际需要——shareId。
export async function shareChat(
  chatId: string
): Promise<{ success: boolean; shareId?: string; error?: string }> {
  try {
    const result = await apiFetch<{ shareId: string }>(
      `/api/chats/${chatId}/share`,
      { method: 'POST' }
    )
    return { success: true, shareId: result.shareId }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to share chat'
    }
  }
}
