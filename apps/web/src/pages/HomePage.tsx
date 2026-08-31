/// 首页(新聊天)。对应原 app/page.tsx。
///
/// 设计意图:
///   原页面是 React Server Component,服务端注入 userId、模型选择数据等;
///   迁到 SPA 后改为客户端渲染。阶段 3 先用匿名(访客)模式与缺省配置跑通
///   核心聊天;userId / 模型选择器数据 / 图书馆可用性 在阶段 4 接入认证与
///   模型选择 API 后填充。

import { Chat } from '@/components/chat'

export default function HomePage() {
  return (
    <Chat
      // 阶段 3:匿名访客模式(未接认证)
      isGuest
      isCloudDeployment={false}
      libraryAvailable={false}
    />
  )
}
