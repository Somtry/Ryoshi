/// 前端入口(React 单页应用)。
///
/// 设计意图:
///   原项目是 Next.js App Router,入口由框架接管;迁到 Vite + React Router 后,
///   这里手动挂载根组件并配置路由。路由与原 app/ 目录一一对应:
///     /            → 首页(新聊天),原 app/page.tsx
///     /search/:id  → 已有聊天,原 app/search/[id]/page.tsx
///     /auth/*      → 认证页面(登录/注册/忘记密码/更新密码)
///   所有页面共用 AppLayout 提供的 Provider 树(对应原 app/layout.tsx)。

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import '../globals.css'

import AppLayout from './AppLayout'
import HomePage from './pages/HomePage'
import SearchPage from './pages/SearchPage'
import AuthErrorPage from './pages/auth/AuthErrorPage'
import ForgotPasswordPage from './pages/auth/ForgotPasswordPage'
import LoginPage from './pages/auth/LoginPage'
import SignUpPage from './pages/auth/SignUpPage'
import SignUpSuccessPage from './pages/auth/SignUpSuccessPage'
import UpdatePasswordPage from './pages/auth/UpdatePasswordPage'

const router = createBrowserRouter([
  {
    // 布局路由:所有子页面都被 AppLayout 的 Provider 树包裹
    element: <AppLayout />,
    children: [
      { path: '/', element: <HomePage /> },
      { path: '/search/:id', element: <SearchPage /> }
    ]
  },
  {
    // 认证页面不带 AppLayout(不需要侧栏/聊天历史),独立居中布局
    path: '/auth/login',
    element: <LoginPage />
  },
  {
    path: '/auth/sign-up',
    element: <SignUpPage />
  },
  {
    path: '/auth/sign-up-success',
    element: <SignUpSuccessPage />
  },
  {
    path: '/auth/forgot-password',
    element: <ForgotPasswordPage />
  },
  {
    path: '/auth/update-password',
    element: <UpdatePasswordPage />
  },
  {
    path: '/auth/error',
    element: <AuthErrorPage />
  }
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>
)
