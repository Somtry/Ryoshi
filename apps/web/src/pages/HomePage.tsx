/// 首页(新聊天)。对应原 app/page.tsx。
///
/// 设计意图:
///   原页面是 React Server Component,服务端注入 userId、模型选择数据等;
///   迁到 SPA 后改为客户端挂载时调 /api/models 拉模型选择器数据。
///   匿名模式下 isGuest=true,模型选择器仍可用(选择结果存 cookie)。

import { useEffect, useState } from 'react'

import { apiFetch } from '@/lib/api-client'
import type { ModelSelectorData } from '@/lib/types/model-selector'

import { Chat } from '@/components/chat'

export default function HomePage() {
  const [modelSelectorData, setModelSelectorData] = useState<ModelSelectorData | undefined>()

  useEffect(() => {
    apiFetch('/api/models')
      .then(setModelSelectorData)
      .catch(() => setModelSelectorData(undefined))
  }, [])

  return (
    <Chat
      isGuest
      isCloudDeployment={false}
      libraryAvailable={false}
      modelSelectorData={modelSelectorData}
    />
  )
}
