/// 首页(新聊天)。对应原 app/page.tsx。
///
/// 设计意图:
///   原页面是 React Server Component,服务端注入 userId、模型选择数据等;
///   迁到 SPA 后改为客户端挂载时调 /api/models 拉模型选择器数据。
///   isGuest 由认证状态决定:未登录=匿名访客,已登录=正式用户。

import { useEffect, useState } from 'react'

import { apiFetch } from '@/lib/api-client'
import type { ModelSelectorData } from '@/lib/types/model-selector'

import { Chat } from '@/components/chat'
import { useAuthCheck } from '@/hooks/use-auth-check'

export default function HomePage() {
  const [modelSelectorData, setModelSelectorData] = useState<ModelSelectorData | undefined>()
  const { isGuest, libraryAvailable } = useAuthCheck()

  useEffect(() => {
    apiFetch<ModelSelectorData>('/api/models')
      .then(setModelSelectorData)
      .catch(() => setModelSelectorData(undefined))
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
