/// OAuth 回调页。对应原 app/auth/oauth/route.ts。
///
/// 设计意图:
///   原型是 Next 服务端路由:在服务端用 code 换 session(cookie 方案)。
///   SPA 没有服务端,但 @supabase/supabase-js 的 createClient 默认开启
///   detectSessionInUrl——Supabase 重定向回 /auth/oauth?code=... 时,
///   getSession() 会自动用 URL 里的 code 完成交换并把 session 写进
///   localStorage。所以这里只需等待 session 建立,然后:
///     成功 → 跳回 next(默认首页),useAuthCheck 的 onAuthStateChange
///            会自动感知登录态,Header/侧栏即时刷新
///     失败/超时 → 跳 /auth/error(对齐原型的兜底行为)

import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { createClient } from '@/lib/supabase/client'

/// session 建立的最长等待时间。正常交换在 1s 内完成;超时视为失败,
/// 避免无效 code 让页面永远停在加载态。
const SESSION_TIMEOUT_MS = 10_000

export default function OAuthCallbackPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  // 防止 effect 内异步回调与超时回调竞争导致二次跳转
  const settled = useRef(false)

  useEffect(() => {
    const next = searchParams.get('next') ?? '/'

    const finish = (ok: boolean) => {
      if (settled.current) return
      settled.current = true
      navigate(ok ? next : '/auth/error', { replace: true })
    }

    let subscription: { unsubscribe: () => void } | null = null

    const run = async () => {
      try {
        const supabase = createClient()

        // code 交换是异步的:先订阅,交换完成时 SIGNED_IN 事件会送达
        const {
          data: { subscription: sub }
        } = supabase.auth.onAuthStateChange((event, session) => {
          if (event === 'SIGNED_IN' && session) finish(true)
        })
        subscription = sub

        // detectSessionInUrl 开启时,getSession 触发 URL code 的交换;
        // 若 session 已存在(如页面被重访),直接成功
        const {
          data: { session }
        } = await supabase.auth.getSession()
        if (session) finish(true)
      } catch {
        // Supabase 未配置:无 OAuth 可言,按失败处理
        finish(false)
      }
    }

    run()
    const timer = setTimeout(() => finish(false), SESSION_TIMEOUT_MS)

    return () => {
      clearTimeout(timer)
      subscription?.unsubscribe()
    }
  }, [navigate, searchParams])

  return (
    <div className="flex min-h-svh w-full items-center justify-center p-6">
      <p className="text-muted-foreground text-sm">正在完成登录…</p>
    </div>
  )
}
