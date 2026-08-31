/// 前端入口(React 单页应用)。
///
/// 设计意图:
///   原项目是 Next.js App Router,入口由框架接管;迁到 Vite + React Router 后,
///   这里手动挂载根组件并配置路由。路由与原 app/ 目录一一对应:
///     /            → 首页(新聊天),原 app/page.tsx
///     /search/:id  → 已有聊天,原 app/search/[id]/page.tsx
///   所有页面共用 AppLayout 提供的 Provider 树(对应原 app/layout.tsx)。
///   其余页面(认证、分享)在阶段 4 接入。

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import '../globals.css'

import AppLayout from './AppLayout'
import HomePage from './pages/HomePage'
import SearchPage from './pages/SearchPage'

const router = createBrowserRouter([
  {
    // 布局路由:所有子页面都被 AppLayout 的 Provider 树包裹
    element: <AppLayout />,
    children: [
      { path: '/', element: <HomePage /> },
      { path: '/search/:id', element: <SearchPage /> }
    ]
  }
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>
)
