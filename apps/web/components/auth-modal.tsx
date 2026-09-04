'use client'

import Link from 'next/link'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { IconLogo } from '@/components/ui/icons'

interface AuthModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function AuthModal({ open, onOpenChange }: AuthModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader className="items-center text-center">
          <div className="mx-auto mb-6 flex size-20 items-center justify-center rounded-full bg-muted">
            <IconLogo className="size-14" />
          </div>
          <DialogTitle className="text-xl font-semibold">
            继续使用 Ryoshi
          </DialogTitle>
          <DialogDescription className="text-muted-foreground">
            登录你的账号或注册新账号，即可使用 Ryoshi。
          </DialogDescription>
        </DialogHeader>
        <div className="mt-6 space-y-3">
          <Button asChild className="w-full" size="lg">
            <Link href="/auth/sign-up">注册</Link>
          </Button>
          <Button asChild variant="outline" className="w-full" size="lg">
            <Link href="/auth/login">登录</Link>
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
