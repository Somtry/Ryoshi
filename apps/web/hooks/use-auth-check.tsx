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

/// 匿名模式下的伪用户:最小可用的 User 形状。
/// 原型里匿名模式 getCurrentUserId() 返回 'anonymous-user'(真值),
/// 于是 isGuest=false、上传/拖拽/历史落库全部可用。SPA 前端没有服务端,
/// 用后端告知的 authMode 合成等价用户,让消费 isGuest/user 的组件无需改动。
function makeAnonymousUser(id: string): User {
  return {
    id,
    app_metadata: {},
    user_metadata: {},
    aud: 'authenticated',
    created_at: '',
    // 标记匿名,供需要区分的地方使用(原型用 is_anonymous 同理)
    is_anonymous: true
  } as unknown as User
}

export function useAuthCheck() {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [authMode, setAuthMode] = useState<AuthMode>('authenticated')

  useEffect(() => {
    let subscription: { unsubscribe: () => void } | null = null
    let cancelled = false

    const checkAuth = async () => {
      // 先问后端认证模式:匿名模式下无论 Supabase 是否配置,都视为已登录
      const mode = await fetchAuthMode()
      if (cancelled) return
      setAuthMode(mode)

      if (mode === 'anonymous') {
        setUser(makeAnonymousUser('anonymous-user'))
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

  return {
    user,
    loading,
    isAuthenticated: !!user,
    authMode,
    /// libraryAvailable 的语义对齐原型:ENABLE_AUTH !== 'false'。
    /// 匿名模式下 Library 面板对所有人开放(数据归 anonymous-user);
    /// 认证模式下也开放(游客可浏览,保存时弹登录框)。
    /// 原型恒为 true(ENABLE_AUTH 只影响匿名与否,不关掉 Library),
    /// 所以这里直接恒 true——保留字段只为不改动消费方。
    libraryAvailable: true
  }
}
