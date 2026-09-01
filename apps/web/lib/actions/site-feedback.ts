/// 站点反馈操作(前端 HTTP 客户端)。
///
/// 设计意图:
///   原为 Server Actions,现调用后端 REST API。**契约与原 Server Action 一致**:
///   返回 `{ success, error? }`,调用方(feedback-modal)按此判定,无需改动。
///   后端端点在阶段 4/任务 20 实现;未就绪时走 catch 返回 `{ success: false }`。

import { apiFetch } from '@/lib/api-client'

export interface FeedbackInput {
  sentiment: 'positive' | 'neutral' | 'negative'
  message: string
  pageUrl: string
}

export async function submitFeedback(
  input: FeedbackInput
): Promise<{ success: boolean; error?: string }> {
  try {
    await apiFetch('/api/feedback', {
      method: 'POST',
      body: JSON.stringify(input)
    })
    return { success: true }
  } catch (error) {
    return {
      success: false,
      error:
        error instanceof Error ? error.message : 'Failed to submit feedback'
    }
  }
}
