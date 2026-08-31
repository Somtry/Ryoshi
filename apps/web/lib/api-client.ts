/// 后端 REST API 的轻量客户端。
///
/// 设计意图:
///   原项目组件通过 Server Actions(lib/actions/*)直接操作数据库;
///   前后端分离后,这些调用改为 HTTP 请求后端 API。本模块提供统一的
///   fetch 封装(同源、带 cookie、错误规整),供各 actions 文件复用。
///   后端对应端点在 apps/server 的阶段 4 逐步实现;未实现的会先返回 501,
///   前端按"功能未就绪"降级处理,不阻断聊天主流程。

/// 统一发起 JSON 请求。同源相对路径,经 Vite 代理转发到后端 :8000。
export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const resp = await fetch(path, {
    credentials: 'include', // 携带 cookie(模型选择 / searchMode / 会话)
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options
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
