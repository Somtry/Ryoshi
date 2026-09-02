/// 应用根布局(SPA 版)。复刻原 app/layout.tsx 的 Provider 嵌套。
///
/// 设计意图:
///   原项目在 Next 的服务端 layout 里用一层层 Provider 包裹页面
///   (主题 / PostHog / 用户态 / 侧栏 / 文件库 / Artifact),并注入服务端
///   取到的 user。迁到 SPA 后,这层嵌套仍必需——Chat 等组件依赖其中的
///   context(如 useArtifact)。用户态由 useAuthCheck 从 Supabase session
///   实时获取,登录/登出时自动刷新。

import { Outlet } from 'react-router-dom'

import ArtifactRoot from '@/components/artifact/artifact-root'
import AppSidebar from '@/components/app-sidebar'
import Header from '@/components/header'
import { KeyboardShortcutHandler } from '@/components/keyboard-shortcut-handler'
import { LibraryProvider } from '@/components/library/library-context'
import { PostHogProvider } from '@/components/posthog-provider'
import { ThemeProvider } from '@/components/theme-provider'
import { SidebarProvider } from '@/components/ui/sidebar'
import { Toaster } from '@/components/ui/sonner'
import { useAuthCheck } from '@/hooks/use-auth-check'
import { UserProvider } from '@/lib/contexts/user-context'

export default function AppLayout() {
  // user 是真实登录用户(Supabase session),匿名模式下为 null——
  // 没登录就是没登录,Header 据此显示 GuestMenu(对齐原型 layout.tsx)。
  // isGuest 是功能开关:匿名模式下为 false(上传/历史等功能可用)。
  const { user, loading, isGuest } = useAuthCheck()
  const userId = user?.id ?? null

  // 认证状态加载期间不渲染,避免闪烁(访客→已登录的跳变)
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-muted-foreground">加载中…</div>
      </div>
    )
  }

  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <PostHogProvider userId={userId}>
        {/* hasUser 语义对齐原型:匿名模式下 getCurrentUserId() 返回真值,
            有"匿名账号"数据(历史/文件),视为 hasUser=true */}
        <UserProvider hasUser={!isGuest}>
          <SidebarProvider defaultOpen={false}>
            <LibraryProvider>
              {/* 匿名模式也渲染侧栏:历史记录按匿名用户存储,需要可见 */}
              <AppSidebar />
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
