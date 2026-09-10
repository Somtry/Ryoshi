'use client'

/// 侧边栏"New"按钮。
///
/// 行为:
///   - 当前对话有消息 → 触发全局事件,Chat 组件清空消息、生成新 chatId
///   - 当前对话无消息 → 不变(已经是新对话了)

import { useEffect, useState } from 'react'
import { usePathname, useRouter } from 'next/navigation'

import { IconPlus as Plus } from '@tabler/icons-react'

import { NEW_CHAT_EVENT } from '@/lib/events'

import { SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'

export function NewChatMenuItem() {
  const router = useRouter()
  const pathname = usePathname()
  // 判断当前是否在聊天页且有无消息(通过检查 Chat 组件是否存在消息)
  // 简化方案:监听 messages-changed 事件来跟踪消息状态
  const [hasMessages, setHasMessages] = useState(false)

  useEffect(() => {
    const handleMessagesChanged = (e: CustomEvent) => {
      setHasMessages(e.detail?.hasMessages ?? false)
    }
    window.addEventListener(
      'messages-changed',
      handleMessagesChanged as EventListener
    )
    return () => {
      window.removeEventListener(
        'messages-changed',
        handleMessagesChanged as EventListener
      )
    }
  }, [])

  const handleClick = () => {
    // 如果不在首页或聊天页,先跳回首页
    if (pathname !== '/' && !pathname.startsWith('/search')) {
      router.push('/')
      return
    }

    // 如果有消息,触发开新对话事件;无消息则不变
    if (hasMessages) {
      window.dispatchEvent(new CustomEvent(NEW_CHAT_EVENT))
    }
    // 无消息时什么都不做(已经在空白新对话状态)
  }

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        onClick={handleClick}
        className="flex items-center gap-2"
      >
        <Plus className="size-4" />
        <span>新对话</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  )
}
