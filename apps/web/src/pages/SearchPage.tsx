/// 已有聊天页。对应原 app/search/[id]/page.tsx。
///
/// 设计意图:
///   原页面是 React Server Component,服务端 loadChat 后把消息作为
///   savedMessages 传给 Chat;迁到 SPA 后改为客户端挂载时调 /api/chats/:id
///   拉取历史,再渲染 Chat。加载期间显示加载态,404 时按"会话不存在"处理。

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { apiFetch } from '@/lib/api-client'
import { loadChat } from '@/lib/actions/chat'
import type { UIMessage } from '@/lib/types/ai'
import type { ModelSelectorData } from '@/lib/types/model-selector'

import { Chat } from '@/components/chat'

export default function SearchPage() {
  const { id } = useParams<{ id: string }>()
  const [state, setState] = useState<
    | { status: 'loading' }
    | { status: 'not-found' }
    | { status: 'ready'; messages: UIMessage[] }
  >({ status: 'loading' })
  // 模型选择器数据:与 HomePage 一致,否则刷新进入历史会话时输入框右下角的
  // 模型选择器会消失(chat-panel 要求 modelSelectorData 非空才渲染)。
  const [modelSelectorData, setModelSelectorData] = useState<ModelSelectorData | undefined>()

  useEffect(() => {
    apiFetch<ModelSelectorData>('/api/models')
      .then(setModelSelectorData)
      .catch(() => setModelSelectorData(undefined))
  }, [])

  useEffect(() => {
    if (!id) return
    let cancelled = false
    setState({ status: 'loading' })
    loadChat(id).then(chat => {
      if (cancelled) return
      if (!chat) {
        setState({ status: 'not-found' })
      } else {
        setState({ status: 'ready', messages: chat.messages })
      }
    })
    return () => {
      cancelled = true
    }
  }, [id])

  if (state.status === 'loading') {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        加载中…
      </div>
    )
  }

  if (state.status === 'not-found') {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        会话不存在或已被删除
      </div>
    )
  }

  return (
    <Chat
      id={id}
      savedMessages={state.messages}
      isGuest
      isCloudDeployment={false}
      libraryAvailable={false}
      modelSelectorData={modelSelectorData}
    />
  )
}
