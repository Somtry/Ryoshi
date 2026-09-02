'use client'

import { useEffect, useState } from 'react'

import { User } from '@supabase/supabase-js'

import { apiFetch } from '@/lib/api-client'
import { createClient } from '@/lib/supabase/client'
import type { ModelSelectorData } from '@/lib/types/model-selector'

/// 后端认证模式。'anonymous' = ENABLE_AUTH=false,单用户共享 anonymous-user;
/// 'authenticated' = 需要登录。从 /api/models 拉取(每个页面都会调,天然搭载)。
/// 拉取失败时按 'authenticated' 处理(保守:不展示登录态功能)。
type AuthMode = 'anonymous' | 'authenticated'

let cachedAuthMode: AuthMode | null = null

async function fetchAuthMode(): Promise<AuthMode> {
  if (cachedAuthMode) return cachedAuthMode
  try {
    const data = await apiFetch<ModelSelectorData>('/api/models')
    cachedAuthMode = data.authMode ?? 'authenticated'
  } catch {
    cachedAuthMode = 'authenticated'
  }
  return cachedAuthMode
}

export function useAuthCheck() {
  // user 只代表**真实登录用户**(Supabase session)。匿名模式下恒为 null——
  // 没登录就是没登录,Header 据此显示 GuestMenu(对齐原型 layout.tsx 行为)。
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [authMode, setAuthMode] = useState<AuthMode>('authenticated')

  useEffect(() => {
    let subscription: { unsubscribe: () => void } | null = null
    let cancelled = false

    const checkAuth = async () => {
      const mode = await fetchAuthMode()
      if (cancelled) return
      setAuthMode(mode)

      if (mode === 'anonymous') {
        // 匿名模式:不读 Supabase,直接视为"功能上的已登录"(isGuest=false),
        // 但 user 保持 null(没有真实账号)
        setUser(null)
        setLoading(false)
        return
      }

      // 认证模式:读 Supabase session
      try {
        const supabase = createClient()

        const {
          data: { session }
        } = await supabase.auth.getSession()
        if (!cancelled) setUser(session?.user ?? null)

        const {
          data: { subscription: authSubscription }
        } = supabase.auth.onAuthStateChange((event, session) => {
          if (!cancelled) setUser(session?.user ?? null)
        })
        subscription = authSubscription
      } catch {
        // Supabase not configured
        if (!cancelled) setUser(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    checkAuth()

    return () => {
      cancelled = true
      subscription?.unsubscribe()
    }
  }, [])

  // isGuest 是功能开关,与"有没有真实账号"解耦:
  //   - 匿名模式(ENABLE_AUTH=false): 原型 getCurrentUserId() 返回 anonymous-user
  //     (真值),isGuest=false,上传/拖拽/历史落库全部可用
  //   - 认证模式: 有 session → 非游客;无 session → 游客(功能受限,弹登录框)
  const isGuest = authMode === 'anonymous' ? false : !user

  return {
    user,
    loading,
    authMode,
    isGuest,
    /// libraryAvailable 对齐原型:ENABLE_AUTH 只影响匿名与否,不关掉 Library。
    libraryAvailable: true
  }
}
