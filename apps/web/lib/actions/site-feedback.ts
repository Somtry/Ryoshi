/// 站点反馈操作(前端 HTTP 客户端)。原为 Server Actions,现调用后端 API。

import { apiFetch } from '@/lib/api-client'

export interface FeedbackInput {
  sentiment: 'positive' | 'neutral' | 'negative'
  message: string
  pageUrl: string
}

export async function submitFeedback(input: FeedbackInput): Promise<void> {
  return apiFetch('/api/feedback', {
    method: 'POST',
    body: JSON.stringify(input)
  })
}
