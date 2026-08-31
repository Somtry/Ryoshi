/// 浏览器端 Supabase 客户端。
///
/// 设计意图:
///   原项目用 @supabase/ssr 的 createBrowserClient(为 Next SSR 设计);
///   SPA 中改用 @supabase/supabase-js 的 createClient 即可(纯浏览器环境,
///   无需处理服务端 cookie)。环境变量约定也从 Next 的 NEXT_PUBLIC_*
///   换成 Vite 的 VITE_*(经 import.meta.env 读取)。
///   阶段 3 为匿名模式,未配置时 createClient 会 throw,调用处已用
///   try/catch 降级为"未登录",不影响聊天主流程。认证在阶段 4 接入。

import { createClient as createSupabaseClient } from '@supabase/supabase-js'

import { getSupabasePublishableKey } from './keys'

let warnedOnce = false

export function createClient() {
  const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
  const key = getSupabasePublishableKey()

  if (!url || !key) {
    if (!warnedOnce) {
      warnedOnce = true
      console.warn(
        'Supabase 未配置,认证功能不可用。' +
          '如需启用认证,请在构建时设置 VITE_SUPABASE_URL 与 VITE_SUPABASE_PUBLISHABLE_KEY。'
      )
    }
    throw new Error('Supabase not configured')
  }

  return createSupabaseClient(url, key)
}
