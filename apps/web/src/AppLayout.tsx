/// 应用根布局(SPA 版)。复刻原 app/layout.tsx 的 Provider 嵌套。
///
/// 设计意图:
///   原项目在 Next 的服务端 layout 里用一层层 Provider 包裹页面
///   (主题 / PostHog / 用户态 / 侧栏 / 文件库 / Artifact),并注入服务端
///   取到的 user。迁到 SPA 后,这层嵌套仍必需——Chat 等组件依赖其中的
///   context(如 useArtifact)。这里用匿名(访客)默认值重建同样的树:
///   userId=null、hasUser=false、不渲染登录态侧栏。认证接入(阶段 4)后,
///   这些值改由客户端会话状态提供。

import { Outlet } from 'react-router-dom'

import ArtifactRoot from '@/components/artifact/artifact-root'
import Header from '@/components/header'
import { KeyboardShortcutHandler } from '@/components/keyboard-shortcut-handler'
import { LibraryProvider } from '@/components/library/library-context'
import { PostHogProvider } from '@/components/posthog-provider'
import { ThemeProvider } from '@/components/theme-provider'
import { SidebarProvider } from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { UserProvider } from '@/lib/contexts/user-context'

export default function AppLayout() {
  // 阶段 3:匿名模式,无登录用户
  const user = null
  const userId: string | null = null

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <PostHogProvider userId={userId}>
        <UserProvider hasUser={!!userId}>
          <SidebarProvider defaultOpen={false}>
            <LibraryProvider>
              <KeyboardShortcutHandler />
              <div className="flex min-h-screen w-full flex-col">
                <Header user={user} />
                <ArtifactRoot>
                  <Outlet />
                </ArtifactRoot>
              </div>
            </LibraryProvider>
          </SidebarProvider>
        </UserProvider>
      </PostHogProvider>
      <Toaster />
    </ThemeProvider>
  )
}
