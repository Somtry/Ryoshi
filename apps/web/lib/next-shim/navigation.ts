/// next/navigation 的兼容实现(基于 React Router)。
///
/// 设计意图:
///   原项目组件用 next/navigation 的 useRouter / usePathname 做客户端导航。
///   迁到 React Router 后,这些 API 有对应物但接口略不同。为让 46 个组件
///   的 import 一行不改,这里提供同名导出,内部转发到 React Router。
///   通过 vite.config 的 alias 把 'next/navigation' 指向本文件。

import { useLocation, useNavigate } from 'react-router-dom'

/// next 的 useRouter 返回 { push, replace, back, refresh, prefetch }。
/// React Router 的 useNavigate 只提供 navigate(to) 与 navigate(-1),
/// 这里适配成 next 的形状;refresh / prefetch 在 SPA 里无对应,给空操作。
export function useRouter() {
  const navigate = useNavigate()
  return {
    push: (href: string) => navigate(href),
    replace: (href: string) => navigate(href, { replace: true }),
    back: () => navigate(-1),
    forward: () => navigate(1),
    // SPA 无服务端刷新与预取概念,保留 API 形状以避免调用处报错
    refresh: () => {},
    prefetch: (_href: string) => {}
  }
}

/// 直接复用 React Router 的 useLocation,取 pathname 字段,与 next 一致。
export function usePathname(): string {
  return useLocation().pathname
}

/// next 的 useServerInsertedHTML 是 RSC 专用(注入服务端渲染的 HTML),
/// SPA 中无此概念。原项目仅在某些 provider 里用到,给空实现即可。
export function useServerInsertedHTML(_callback: () => unknown): void {
  // 无操作:单页应用没有服务端插入 HTML 的阶段
}
