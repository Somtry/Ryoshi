/// 账户操作(前端 HTTP 客户端)。原为 Server Actions,现调用后端 API。
/// 账户删除的后端端点在阶段 4(认证接入后)实现。

import { apiFetch } from '@/lib/api-client'

export async function deleteAccount(): Promise<void> {
  return apiFetch('/api/account', { method: 'DELETE' })
}
