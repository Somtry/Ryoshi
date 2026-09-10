/// 首页(新聊天)。对应原 app/page.tsx。
///
/// 设计意图:
///   原页面是 React Server Component,服务端注入 userId、模型选择数据等;
///   迁到 SPA 后改为客户端挂载时调 /api/models 拉模型选择器数据。
///   isGuest 由认证状态决定:未登录=匿名访客,已登录=正式用户。
///
///   BYOK 更新:监听 BYOK_KEYS_UPDATED_EVENT 事件,配置保存后自动刷新模型列表。

import { useEffect, useState } from 'react'

import { apiFetch } from '@/lib/api-client'
import { BYOK_KEYS_UPDATED_EVENT } from '@/lib/events'
import type { ModelSelectorData } from '@/lib/types/model-selector'

import { Chat } from '@/components/chat'
import { useAuthCheck } from '@/hooks/use-auth-check'

export default function HomePage() {
  const [modelSelectorData, setModelSelectorData] = useState<
    ModelSelectorData | undefined
  >()
  const { isGuest, libraryAvailable } = useAuthCheck()

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

  return (
    <Chat
      isGuest={isGuest}
      isCloudDeployment={false}
      libraryAvailable={libraryAvailable}
      modelSelectorData={modelSelectorData}
    />
  )
}
