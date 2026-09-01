/// 账户操作(前端 HTTP 客户端)。
///
/// 设计意图:
///   原为 Server Actions,现调用后端 REST API。**契约与原 Server Action 一致**:
///   返回 `{ success, error? }`,调用方(account-settings-dialog)按此判定。
///   后端端点在阶段 4(认证接入后)实现;未就绪时走 catch 返回 `{ success: false }`。

import { apiFetch } from '@/lib/api-client'

export async function deleteAccount(): Promise<{
  success: boolean
  error?: string
}> {
  try {
    await apiFetch('/api/account', { method: 'DELETE' })
    return { success: true }
  } catch (error) {
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to delete account'
    }
  }
}
