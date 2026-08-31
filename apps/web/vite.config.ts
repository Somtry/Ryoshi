/// Vite 配置:React 单页应用 + 开发代理到 Python 后端。
///
/// 设计意图:
///   原项目靠 Next.js 同域转发 API;Ryoshi 前后端分离,开发时前端在 :3000、
///   后端在 :8000。这里用 Vite 的 dev proxy 把 /api 与 /relay(PostHog 反代)
///   转发到 :8000,使前端代码里的相对路径请求原样可达后端,无需改动组件。
///   路径别名 @ 指向项目根,与原 tsconfig 的 "@/*" 保持一致,保证既有
///   import 语句(@/components、@/lib 等)不需要改。

import path from 'path'
import { fileURLToPath } from 'url'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': __dirname,
      // next/* 兼容层:让组件里的 next/link、next/navigation、next/image
      // import 原样生效,内部转发到 React Router / 原生元素。见 lib/next-shim/
      'next/navigation': path.resolve(__dirname, 'lib/next-shim/navigation.ts'),
      'next/link': path.resolve(__dirname, 'lib/next-shim/link.tsx'),
      'next/image': path.resolve(__dirname, 'lib/next-shim/image.tsx')
    }
  },
  server: {
    port: 3000,
    proxy: {
      // API 转发到 Python 后端
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      // PostHog 反代(原 next.config 的 rewrites),后端 server 也实现了这套
      '/relay': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  }
})
