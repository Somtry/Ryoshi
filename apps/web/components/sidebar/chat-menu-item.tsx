'use client'

import { useCallback, useState, useTransition } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'

import {
  IconDots as MoreHorizontal,
  IconDownload as Download,
  IconTrash as Trash2
} from '@tabler/icons-react'
import { toast } from 'sonner'

import { getAccessToken } from '@/lib/api-client'

import { deleteChat } from '@/lib/actions/chat'
import { Chat as DBChat } from '@/lib/db/schema'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from '@/components/ui/alert-dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu'
import {
  SidebarMenuAction,
  SidebarMenuButton,
  SidebarMenuItem
} from '@/components/ui/sidebar'

import { Spinner } from '../ui/spinner'

interface ChatMenuItemProps {
  chat: DBChat
}

const formatDateWithTime = (date: Date | string) => {
  const parsedDate = new Date(date)
  const now = new Date()
  const yesterday = new Date()
  yesterday.setDate(yesterday.getDate() - 1)

  const formatTime = (date: Date) => {
    return date.toLocaleString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    })
  }

  if (
    parsedDate.getDate() === now.getDate() &&
    parsedDate.getMonth() === now.getMonth() &&
    parsedDate.getFullYear() === now.getFullYear()
  ) {
    return `今天 ${formatTime(parsedDate)}`
  } else if (
    parsedDate.getDate() === yesterday.getDate() &&
    parsedDate.getMonth() === yesterday.getMonth() &&
    parsedDate.getFullYear() === yesterday.getFullYear()
  ) {
    return `昨天 ${formatTime(parsedDate)}`
  } else {
    return parsedDate.toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    })
  }
}

export function ChatMenuItem({ chat }: ChatMenuItemProps) {
  const pathname = usePathname()
  const path = `/search/${chat.id}`
  const isActive = pathname === path
  const router = useRouter()
  const [isPending, startTransition] = useTransition()
  const [isMenuOpen, setIsMenuOpen] = useState(false)
  const [isAlertOpen, setIsAlertOpen] = useState(false)

  const handleDeleteChat = useCallback(() => {
    // Close overlays first so focus and pointer locks are released
    // before the list updates and this item potentially unmounts.
    setIsAlertOpen(false)
    setIsMenuOpen(false)

    startTransition(() => {
      void (async () => {
        const result = await deleteChat(chat.id)

        if (result?.success) {
          toast.success('对话已删除')
          if (isActive) {
            router.push('/')
          }
          window.dispatchEvent(new CustomEvent('chat-history-updated'))
        } else if (result?.error) {
          toast.error(result.error)
        } else {
          toast.error('删除对话时出现意外错误。')
        }
      })()
    })
  }, [chat.id, isActive, router, startTransition])
  const handleMenuOpenChange = useCallback((open: boolean) => {
    setIsMenuOpen(open)
  }, [])

  /// 导出对话:调后端 /api/chats/{id}/export?format=md 触发下载。
  /// 用 fetch + blob 而非 window.open:需要带 Authorization 头(登录模式),
  /// 且能捕获失败给 toast(window.open 失败是静默的)。
  const handleExportChat = useCallback(async () => {
    setIsMenuOpen(false)
    try {
      const headers: Record<string, string> = {}
      const token = getAccessToken()
      if (token) headers['Authorization'] = `Bearer ${token}`
      const resp = await fetch(`/api/chats/${chat.id}/export?format=md`, {
        headers
      })
      if (!resp.ok) {
        throw new Error(`导出失败(${resp.status})`)
      }
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      // 后端 Content-Disposition 已带文件名(RFC 5987);前端兜底一份
      const cd = resp.headers.get('content-disposition') || ''
      const match = cd.match(/filename\*=UTF-8''([^;]+)/)
      a.download = match
        ? decodeURIComponent(match[1])
        : `${chat.title || 'chat'}.md`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast.success('对话已导出')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导出对话失败')
    }
  }, [chat.id, chat.title])

  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        asChild
        isActive={isActive}
        className="h-auto flex-col gap-0.5 items-start p-2 pr-8"
      >
        <Link href={path}>
          <div className="text-xs font-medium truncate select-none w-full">
            {chat.title}
          </div>
          <div className="text-xs text-muted-foreground w-full">
            {formatDateWithTime(chat.createdAt)}
          </div>
        </Link>
      </SidebarMenuButton>

      <DropdownMenu open={isMenuOpen} onOpenChange={handleMenuOpenChange}>
        <DropdownMenuTrigger asChild>
          <SidebarMenuAction className="size-7 p-1 mr-1">
            <MoreHorizontal size={16} />
            <span className="sr-only">Chat Actions</span>
          </SidebarMenuAction>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start">
          <DropdownMenuItem
            className="gap-2"
            onSelect={event => {
              event.preventDefault()
              void handleExportChat()
            }}
          >
            <Download size={14} />
            导出对话
          </DropdownMenuItem>
          <DropdownMenuItem
            className="gap-2 text-destructive focus:text-destructive"
            onSelect={event => {
              event.preventDefault()
              setIsMenuOpen(false)
              setIsAlertOpen(true)
            }}
          >
            <Trash2 size={14} />
            删除对话
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <AlertDialog open={isAlertOpen} onOpenChange={setIsAlertOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确定要删除吗？</AlertDialogTitle>
            <AlertDialogDescription>
              此操作无法撤销，该对话记录将被永久删除。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isPending}>取消</AlertDialogCancel>
            <AlertDialogAction
              disabled={isPending}
              onClick={event => {
                event.preventDefault()
                handleDeleteChat()
              }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {isPending ? (
                <div className="flex items-center justify-center">
                  <Spinner />
                </div>
              ) : (
                '删除'
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SidebarMenuItem>
  )
}
