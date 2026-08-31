/// 前端侧的数据库类型与 ID 生成(轻量替代)。
///
/// 设计意图:
///   原项目前后端同构,前端组件直接 import 服务端的 Drizzle schema
///   (lib/db/schema.ts)来取 generateId 与若干类型。迁到前后端分离后,
///   前端不再包含 ORM 与 cuid2 依赖,这里提供一个等价的轻量文件:
///   只导出前端真正用到的 generateId 和类型定义,不含任何服务端依赖。
///   真正的表结构在后端 apps/server/src/ryoshi/db/models.py。

/// 生成主键 ID。
/// 原项目用 cuid2;这里用 crypto.randomUUID 的十六进制串,同样满足
/// "唯一、不可枚举、字符串",且浏览器原生支持、零依赖。
export function generateId(): string {
  return crypto.randomUUID().replace(/-/g, '')
}

// ---- 前端用到的实体类型(与后端模型对应的字段子集) ----

export interface Chat {
  id: string
  createdAt: Date | string
  title: string
  userId: string
  visibility: 'public' | 'private'
}

export interface Message {
  id: string
  chatId: string
  role: string
  createdAt: Date | string
  updatedAt?: Date | string | null
  metadata?: Record<string, unknown> | null
}

export interface Part {
  id: string
  messageId: string
  order: number
  type: string
  [key: string]: unknown
}

export interface Note {
  id: string
  userId: string
  chatId?: string | null
  sourceMessageId?: string | null
  title: string
  content: string
  createdAt: Date | string
  updatedAt: Date | string
}

export interface LibraryFile {
  id: string
  userId: string
  chatId?: string | null
  filename: string
  objectKey: string
  mediaType: string
  size?: number | null
  createdAt: Date | string
  updatedAt: Date | string
}

export interface Feedback {
  id: string
  userId?: string | null
  sentiment: 'positive' | 'neutral' | 'negative'
  message: string
  pageUrl: string
  userAgent?: string | null
  createdAt: Date | string
}
