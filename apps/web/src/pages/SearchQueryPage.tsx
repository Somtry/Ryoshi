/// 带查询词的新聊天页(/search?q=...)。对应原 app/search/page.tsx。
///
/// 设计意图:
///   外部入口(浏览器搜索插件、书签、第三方跳转)可以带 ?q= 直接开聊。
///   与 /search/:id 的区别:这里是**新聊天**(客户端生成新 chatId),
///   q 作为首条用户消息自动提交;无 q 时重定向回首页(对齐原型)。

import { useEffect, useState } from 'react'
import { Navigate, useSearchParams } from 'react-router-dom'

import { apiFetch } from '@/lib/api-client'
import { BYOK_KEYS_UPDATED_EVENT } from '@/lib/events'
import type { ModelSelectorData } from '@/lib/types/model-selector'
import { generateUUID } from '@/lib/utils'

import { Chat } from '@/components/chat'
import { useAuthCheck } from '@/hooks/use-auth-check'

export default function SearchQueryPage() {
  const [searchParams] = useSearchParams()
  const q = searchParams.get('q')
  const { isGuest, libraryAvailable } = useAuthCheck()
  const [modelSelectorData, setModelSelectorData] = useState<
    ModelSelectorData | undefined
  >()
  // chatId 只在首次渲染生成一次(原型是每次 SSR 生成;SPA 复用组件时不能变)
  const [chatId] = useState(() => generateUUID())

  useEffect(() => {
    const fetchModels = () => {
      apiFetch<ModelSelectorData>('/api/models')
        .then(setModelSelectorData)
        .catch(() => setModelSelectorData(undefined))
    }

    fetchModels()

    // BYOK 配置保存后刷新模型列表
    const handleByokUpdate = () => fetchModels()
    window.addEventListener(BYOK_KEYS_UPDATED_EVENT, handleByokUpdate)
    return () =>
      window.removeEventListener(BYOK_KEYS_UPDATED_EVENT, handleByokUpdate)
  }, [])

  if (!q) {
    return <Navigate to="/" replace />
  }

  return (
    <Chat
      id={chatId}
      query={q}
      isGuest={isGuest}
      isCloudDeployment={false}
      libraryAvailable={libraryAvailable}
      modelSelectorData={modelSelectorData}
    />
  )
}
