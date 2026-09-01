/// 后端 REST API 的轻量客户端。
///
/// 设计意图:
///   原项目组件通过 Server Actions(lib/actions/*)直接操作数据库;
///   前后端分离后,这些调用改为 HTTP 请求后端 API。本模块提供统一的
///   fetch 封装(同源、带 cookie、错误规整、自动附加 Supabase access_token),
///   供各 actions 文件复用。
///
///   认证令牌:Supabase 浏览器端把 session 存 localStorage
///   (key 格式 `sb-{project-ref}-auth-token`)。这里从 localStorage 读取
///   access_token 并放入 Authorization: Bearer header,后端用 python-jose
///   本地校验(对应原项目服务端的 supabase.auth.getUser())。
///   未登录 / 未配置 Supabase 时不带 header,后端按匿名模式处理。

import { hasSupabasePublicConfig } from './supabase/keys'

/// 从 localStorage 读 Supabase session 的 access_token。
/// 不依赖 @supabase/supabase-js 的 client 实例,避免在每次请求都初始化 client。
/// 导出供 chat.tsx 的 DefaultChatTransport 复用(SSE 流式请求不走 apiFetch)。
export function getAccessToken(): string | null {
  if (!hasSupabasePublicConfig()) return null
  try {
    const url = import.meta.env.VITE_SUPABASE_URL as string
    // storageKey 格式: sb-{hostname 第一段}-auth-token
    const projectRef = new URL(url).hostname.split('.')[0]
    const raw = localStorage.getItem(`sb-${projectRef}-auth-token`)
    if (!raw) return null
    const session = JSON.parse(raw)
    return session?.access_token ?? null
  } catch {
    return null
  }
}

/// 统一发起 JSON 请求。同源相对路径,经 Vite 代理转发到后端 :8000。
export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined)
  }

  // 已登录用户的请求携带 JWT,后端据此识别用户身份
  const token = getAccessToken()
  if (token) {
    headers['Authorization'] = `Bearer ${token}`
  }

  const resp = await fetch(path, {
    credentials: 'include', // 携带 cookie(模型选择 / searchMode / 会话)
    ...options,
    headers
  })

  if (!resp.ok) {
    const text = await resp.text().catch(() => '')
    throw new ApiError(resp.status, text || resp.statusText)
  }
  // 204 无内容或空响应体时返回 null
  if (resp.status === 204) return null as T
  const text = await resp.text()
  return (text ? JSON.parse(text) : null) as T
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string
  ) {
    super(message)
    this.name = 'ApiError'
  }
}
