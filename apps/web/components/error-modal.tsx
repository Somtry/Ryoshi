'use client'

import Link from 'next/link'

import {
  IconAlertCircle as AlertCircle,
  IconClock as Clock,
  IconRefresh as RefreshCw
} from '@tabler/icons-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'

interface ErrorModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  error: {
    type: 'rate-limit' | 'auth' | 'forbidden' | 'general'
    message: string
    details?: string
  }
  onRetry?: () => void
  onAuthClose?: () => void
}

export function ErrorModal({
  open,
  onOpenChange,
  error,
  onRetry,
  onAuthClose
}: ErrorModalProps) {
  const handleAuthClose = () => {
    onOpenChange(false)
    onAuthClose?.()
  }

  const getErrorIcon = () => {
    switch (error.type) {
      case 'rate-limit':
        return <Clock className="size-6 text-yellow-500" />
      case 'auth':
      case 'forbidden':
        return <AlertCircle className="size-6 text-red-500" />
      default:
        return <AlertCircle className="size-6 text-orange-500" />
    }
  }

  const getErrorTitle = () => {
    switch (error.type) {
      case 'rate-limit':
        return '请求次数超限'
      case 'auth':
        return '继续使用 Ryoshi'
      case 'forbidden':
        return '无权访问'
      default:
        return '出错了'
    }
  }

  const getErrorDescription = () => {
    switch (error.type) {
      case 'rate-limit':
        return (
          error.message ||
          '请求太频繁了，请稍等片刻再试。'
        )
      case 'auth':
        return (
          error.message ||
          '登录你的账号或注册新账号，即可使用 Ryoshi。'
        )
      case 'forbidden':
        return '你没有权限访问该资源。'
      default:
        return (
          error.message || '发生了意外错误，请重试。'
        )
    }
  }

  const getErrorDetails = () => {
    if (error.type === 'rate-limit') {
      return error.details || '额度将在 UTC 零点重置。'
    }
    return error.details
  }

  return (
    <Dialog
      open={open}
      onOpenChange={open => {
        if (!open && error.type === 'auth') {
          handleAuthClose()
        } else {
          onOpenChange(open)
        }
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <div className="mx-auto mb-4 flex size-12 items-center justify-center rounded-full bg-muted">
            {getErrorIcon()}
          </div>
          <DialogTitle className="text-center text-xl font-semibold">
            {getErrorTitle()}
          </DialogTitle>
          <DialogDescription className="text-center text-muted-foreground">
            {getErrorDescription()}
          </DialogDescription>
          {getErrorDetails() && (
            <div className="mt-4 rounded-lg bg-muted p-3 text-sm text-muted-foreground">
              {getErrorDetails()}
            </div>
          )}
        </DialogHeader>
        <DialogFooter className="flex-col gap-2">
          {error.type === 'auth' ? (
            <>
              <Button asChild className="w-full">
                <Link href="/auth/sign-up">注册</Link>
              </Button>
              <Button asChild variant="outline" className="w-full">
                <Link href="/auth/login">登录</Link>
              </Button>
            </>
          ) : (
            <>
              {onRetry && error.type !== 'rate-limit' && (
                <Button
                  onClick={() => {
                    onRetry()
                    onOpenChange(false)
                  }}
                  className="w-full"
                >
                  <RefreshCw className="mr-2 size-4" />
                  重试
                </Button>
              )}
              <Button
                variant={
                  onRetry && error.type !== 'rate-limit' ? 'outline' : 'default'
                }
                onClick={() => onOpenChange(false)}
                className="w-full"
              >
                {error.type === 'rate-limit' ? '知道了' : '关闭'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
