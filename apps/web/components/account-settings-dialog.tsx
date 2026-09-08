'use client'

import { useState, useTransition } from 'react'
import { useRouter } from 'next/navigation'

import type { User } from '@supabase/supabase-js'
import {
  IconDeviceLaptop as Laptop,
  IconMoon as Moon,
  IconSun as Sun,
  IconTrash as Trash2
} from '@tabler/icons-react'
import { toast } from 'sonner'

import { deleteAccount } from '@/lib/actions/account'
import { createClient } from '@/lib/supabase/client'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Separator } from '@/components/ui/separator'
import { Spinner } from '@/components/ui/spinner'

import { useTheme } from '@/components/theme-provider'

interface AccountSettingsDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  user: User
}

const themeOptions = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
  { value: 'system', label: '跟随系统', icon: Laptop }
]

export function AccountSettingsDialog({
  open,
  onOpenChange,
  user
}: AccountSettingsDialogProps) {
  const router = useRouter()
  const { setTheme, theme } = useTheme()
  const [isDeleting, startDeleteTransition] = useTransition()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const activeTheme = theme ?? 'system'

  const userName =
    user.user_metadata?.full_name || user.user_metadata?.name || 'User'

  const handleDeleteAccount = () => {
    startDeleteTransition(() => { void (async () => {
      const result = await deleteAccount()

      if (result.success) {
        try {
          await createClient().auth.signOut()
        } catch (error) {
          console.error('Failed to clear client session:', error)
        }

        toast.success('账号已注销')
        setConfirmOpen(false)
        onOpenChange(false)
        router.push('/')
        router.refresh()
        return
      }

      toast.error(result.error ?? '注销账号失败')
    })() })
  }

  return (
    <Dialog
      open={open}
      onOpenChange={nextOpen => {
        if (!isDeleting) {
          if (!nextOpen) {
            setConfirmOpen(false)
          }
          onOpenChange(nextOpen)
        }
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>账户</DialogTitle>
          <DialogDescription>
            管理你的账号偏好和数据。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-6">
          <section className="grid gap-3">
            <div className="grid gap-1">
              <h3 className="text-sm font-medium">个人资料</h3>
              <div className="text-sm text-muted-foreground">
                <p className="truncate">{userName}</p>
                <p className="truncate">{user.email}</p>
              </div>
            </div>
          </section>

          <Separator />

          <section className="grid gap-3">
            <div className="grid gap-1">
              <h3 className="text-sm font-medium">主题外观</h3>
              <p className="text-sm text-muted-foreground">
                选择 Ryoshi 在这台设备上的外观。
              </p>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {themeOptions.map(option => {
                const Icon = option.icon
                const selected = activeTheme === option.value

                return (
                  <Button
                    key={option.value}
                    type="button"
                    variant={selected ? 'secondary' : 'outline'}
                    className="h-16 flex-col gap-1.5 px-2"
                    aria-pressed={selected}
                    onClick={() => setTheme(option.value)}
                  >
                    <Icon className="size-4" />
                    <span className="text-xs">{option.label}</span>
                  </Button>
                )
              })}
            </div>
          </section>

          <Separator />

          <section className="grid gap-3">
            <div className="grid gap-1">
              <h3 className="text-sm font-medium text-destructive">
                注销账号
              </h3>
              <p className="text-sm text-muted-foreground">
                永久删除你的账号、对话记录和已上传的文件，此操作无法撤销。
              </p>
            </div>

            <AlertDialog
              open={confirmOpen}
              onOpenChange={nextOpen => {
                if (!isDeleting) {
                  setConfirmOpen(nextOpen)
                }
              }}
            >
              <AlertDialogTrigger asChild>
                <Button
                  type="button"
                  variant="destructive"
                  className="w-fit gap-2"
                  disabled={isDeleting}
                >
                  <Trash2 className="size-4" />
                  注销账号
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>确定要注销账号吗？</AlertDialogTitle>
                  <AlertDialogDescription>
                    此操作无法撤销，你的账号、对话记录和已上传的文件都将被永久删除。
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel disabled={isDeleting}>
                    取消
                  </AlertDialogCancel>
                  <AlertDialogAction
                    disabled={isDeleting}
                    onClick={event => {
                      event.preventDefault()
                      handleDeleteAccount()
                    }}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    {isDeleting ? <Spinner /> : '确认注销'}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </section>
        </div>
      </DialogContent>
    </Dialog>
  )
}
