import type { ReasoningUIPart, TextUIPart, UIMessage as AIMessage } from 'ai'

import type { SearchMode } from '@/lib/types/search'
import type { SearchResults } from '@/lib/types'

// Define metadata type for messages
export interface UIMessageMetadata {
  traceId?: string
  feedbackScore?: number | null
  searchMode?: SearchMode
  modelId?: string
  [key: string]: any
}

export type UIMessage<
  TMetadata = UIMessageMetadata,
  TDataTypes = UIDataTypes,
  TTools = UITools
> = AIMessage

export type UIDataTypes = {
  sources?: any[]
  // User-authored attachments (composer): a pasted text blob and a pasted URL.
  // `nonce` is the delimiter assigned server-side by `assignDataPartNonces`;
  // the composer never sets it.
  pastedContent?: { text: string; nonce?: string }
  quotedContext?: { text: string; nonce?: string }
  noteContext?: { title?: string; text: string; nonce?: string }
  sourceUrl?: { url: string }
}

// ---- 工具的输入/输出类型 ----
// 原项目用 InferUITool<typeof 工具实现例> 从前端工具定义推导;迁到
// Python 后端后前端不再有工具实现,这里手写与后端一致的契约:
//   search  → apps/server/src/ryoshi/tools/search.py (SearchResults.to_dict)
//   fetch   → apps/server/src/ryoshi/tools/fetch.py (FetchResult.to_dict)
//   askQuestion / todoWrite → agents/researcher.py 的工具返回

export interface TodoItem {
  id: string
  content: string
  status: 'pending' | 'in_progress' | 'completed'
  priority?: 'high' | 'medium' | 'low'
}

// 后端 search 工具的输出 = SearchResults + state 字段(to_dict 里固定带
// state="complete",前端据此判定"搜索完成"并渲染结果列表)。
// include_domains 等可选参数历史上出现过(前端展示 [域名] 标注),保留在输入里。
export type SearchToolInput = {
  query: string
  max_results?: number
  include_domains?: string[]
}

export type SearchToolOutput = SearchResults & { state: string }

export type FetchToolInput = { url: string }

// fetch 输出在后端是 {url,title,text};前端 fetch-section 在流式期间会把
// output 当成含 state 的结构判定(fetching/complete),成功后又按
// SearchResults 形状读 results[0] —— 与 search 共用同一消费模式。
export type FetchToolOutput = {
  url: string
  title: string
  text: string
  state?: string
  results?: Array<{ title: string; url: string; content: string }>
}

export type AskQuestionToolInput = {
  question: string
  options?: string[]
}

export type AskQuestionToolOutput = {
  question: string
  options: string[]
  requiresUserInput: boolean
}

export type TodoWriteToolInput = {
  todos: TodoItem[]
}

export type TodoWriteToolOutput = {
  success: boolean
  message: string
  completedCount: number
  totalCount: number
  todos: TodoItem[]
}

export type UITools = {
  search: { input: SearchToolInput; output: SearchToolOutput }
  fetch: { input: FetchToolInput; output: FetchToolOutput }
  askQuestion: { input: AskQuestionToolInput; output: AskQuestionToolOutput }
  todoWrite: { input: TodoWriteToolInput; output: TodoWriteToolOutput }
  // Dynamic tools will be added at runtime
  [key: string]: any
}

export type ToolPart<T extends keyof UITools = keyof UITools> = {
  type: `tool-${T}`
  toolCallId: string
  input: UITools[T]['input']
  output?: UITools[T]['output']
  state:
    | 'input-streaming'
    | 'input-available'
    | 'output-available'
    | 'output-error'
  errorText?: string
}

export type Part = TextUIPart | ReasoningUIPart | ToolPart
