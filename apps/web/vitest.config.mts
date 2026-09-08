import react from '@vitejs/plugin-react'
import path from 'path'
import { defineConfig } from 'vitest/config'

// Provide dummy env vars at configuration time to avoid import errors during bundling
process.env.DATABASE_URL =
  process.env.DATABASE_URL ?? 'postgres://user:pass@localhost:5432/testdb'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './'),
      'zod/v4': 'zod',
      // 与 vite.config / tsconfig 的 next/* 兼容层保持一致(三处须同步)
      'next/navigation': path.resolve(__dirname, './lib/next-shim/navigation.ts'),
      'next/link': path.resolve(__dirname, './lib/next-shim/link.tsx'),
      'next/image': path.resolve(__dirname, './lib/next-shim/image.tsx')
    }
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './vitest.setup.ts'
  }
})
