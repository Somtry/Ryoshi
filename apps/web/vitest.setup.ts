import { vi } from 'vitest'

// 测试环境的兜底变量(部分被测模块读取环境)
process.env.DATABASE_URL =
  process.env.DATABASE_URL ?? 'postgres://user:pass@localhost:5432/testdb'
