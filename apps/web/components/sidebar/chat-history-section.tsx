import { ChatHistoryClient } from './chat-history-client'

// 非 async:原为 Next Server Component 形态,迁 SPA 后同步渲染即可
export function ChatHistorySection() {
  return <ChatHistoryClient />
}
