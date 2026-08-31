/// 已有聊天页。对应原 app/search/[id]/page.tsx。
///
/// 设计意图:
///   原页面在服务端按 id 加载聊天历史再渲染;SPA 中历史加载走 API
///   (阶段 4 接入 /api/chats/:id)。阶段 3 先按"访客 + 无预载历史"渲染,
///   useChat 的 messages 由前端会话内状态维护,刷新后历史的持久化在阶段 4 补。

import { useParams } from 'react-router-dom'

import { Chat } from '@/components/chat'

export default function SearchPage() {
  const { id } = useParams<{ id: string }>()

  return (
    <Chat
      id={id}
      isGuest
      isCloudDeployment={false}
      libraryAvailable={false}
    />
  )
}
