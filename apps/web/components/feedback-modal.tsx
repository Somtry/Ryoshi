'use client'

import { useState, useTransition } from 'react'

import {
  IconMoodNeutral as Meh,
  IconMoodSad as Frown,
  IconMoodSmile as Smile
} from '@tabler/icons-react'
import { toast } from 'sonner'

import { submitFeedback } from '@/lib/actions/site-feedback'
import { cn } from '@/lib/utils'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

type Sentiment = 'positive' | 'neutral' | 'negative'

interface FeedbackModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function FeedbackModal({ open, onOpenChange }: FeedbackModalProps) {
  const [sentiment, setSentiment] = useState<Sentiment | null>(null)
  const [message, setMessage] = useState('')
  const [isPending, startTransition] = useTransition()

  const handleSubmit = () => {
    if (!sentiment || !message.trim()) {
      toast.error('请先选择感受并填写反馈内容')
      return
    }

    startTransition(async () => {
      const result = await submitFeedback({
        sentiment,
        message: message.trim(),
        pageUrl: window.location.href
      })

      if (result.success) {
        toast.success('感谢你的反馈！')
        // Reset form and close modal
        setSentiment(null)
        setMessage('')
        onOpenChange(false)
      } else {
        toast.error('反馈提交失败，请稍后再试。')
      }
    })
  }

  const handleCancel = () => {
    setSentiment(null)
    setMessage('')
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[550px]">
        <DialogHeader>
          <DialogTitle>提交反馈</DialogTitle>
          <DialogDescription>
            你的反馈能帮助我们改进 Ryoshi，欢迎告诉我们你的想法！
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 mt-4">
          <div className="flex gap-2">
            <Button
              type="button"
              variant={sentiment === 'positive' ? 'default' : 'outline'}
              size="icon"
              onClick={() => setSentiment('positive')}
              className={cn(
                'size-12',
                sentiment === 'positive' && 'bg-green-500 hover:bg-green-600'
              )}
            >
              <Smile className="size-6" />
            </Button>
            <Button
              type="button"
              variant={sentiment === 'neutral' ? 'default' : 'outline'}
              size="icon"
              onClick={() => setSentiment('neutral')}
              className={cn(
                'size-12',
                sentiment === 'neutral' && 'bg-yellow-500 hover:bg-yellow-600'
              )}
            >
              <Meh className="size-6" />
            </Button>
            <Button
              type="button"
              variant={sentiment === 'negative' ? 'default' : 'outline'}
              size="icon"
              onClick={() => setSentiment('negative')}
              className={cn(
                'size-12',
                sentiment === 'negative' && 'bg-red-500 hover:bg-red-600'
              )}
            >
              <Frown className="size-6" />
            </Button>
          </div>

          <Textarea
            placeholder="写下你的反馈…"
            value={message}
            onChange={e => setMessage(e.target.value)}
            className="min-h-[150px] resize-none"
          />

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={handleCancel}
              disabled={isPending}
            >
              取消
            </Button>
            <Button
              type="button"
              onClick={handleSubmit}
              disabled={isPending || !sentiment || !message.trim()}
            >
              {isPending ? '提交中…' : '提交'}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
