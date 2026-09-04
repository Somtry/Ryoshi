'use client'

import { useEffect, useRef, useState } from 'react'

import {
  IconBulb as Bulb,
  IconPencil as Pencil,
  IconScale as Scale,
  IconSearch as Search,
  IconSettings as Settings,
  IconTool as Tool,
  type TablerIcon
} from '@tabler/icons-react'

import { captureClient } from '@/lib/analytics/posthog-client'
import { cn } from '@/lib/utils'

import { Button } from './ui/button'

// Constants for timing delays
const FOCUS_OUT_DELAY_MS = 100 // Delay to ensure focus has actually moved

interface ActionCategory {
  icon: TablerIcon
  label: string
  key: string
}

const actionCategories: ActionCategory[] = [
  {
    icon: Scale,
    label: '帮我选',
    key: 'decide'
  },
  {
    icon: Tool,
    label: '修问题',
    key: 'troubleshoot'
  },
  {
    icon: Settings,
    label: '怎么做',
    key: 'howto'
  },
  {
    icon: Bulb,
    label: '学明白',
    key: 'understand'
  },
  {
    icon: Pencil,
    label: '写一个',
    key: 'create'
  }
]

// Onboarding examples are tuned to showcase grounded, GenUI-rich answers
// (images, comparison tables, structured depth) for concrete, self-contained
// tasks — the patterns that correlate with follow-up in real usage. Keep each
// example self-contained (no "my notes"/"this file" referencing absent context).
const promptSamples: Record<string, string[]> = {
  troubleshoot: [
    '车子能打着火但马上熄火，电子设备都正常，怎么回事？',
    '同一网络下笔记本 Wi-Fi 老掉线但手机没事，怎么修？',
    '养了一周的天然酵母一直不发，哪里出问题了？',
    'Next.js 本地正常但生产构建报 "Module not found"'
  ],
  howto: [
    '怎么把照片从 Google Photos 完整导出并保留相册？',
    '如何用 Proxmox 搭建一台家庭自托管服务器？',
    '怎么把一整个文件夹的 .txt 批量转成干净的 HTML？',
    '如何用 Plex 搭建家庭影音服务器串流电影？'
  ],
  decide: [
    '特斯拉和 Rivian，我该买哪辆？',
    '久坐腰疼，升降桌和普通桌哪个更值得买？',
    '预算 7000 元以内，旅行用微单怎么选？',
    '做个人知识库，Notion 和 Obsidian 选哪个？'
  ],
  understand: [
    '极光是怎么形成的？',
    '恐龙灭绝的真正原因是什么？',
    '核电站到底是怎么发电的？',
    // Timely slot — refresh seasonally (currently WWDC 2026).
    '苹果在 WWDC 2026 上发布了什么？'
  ],
  create: [
    '出一份 5 道题的古罗马知识小测验，附 A–D 选项',
    '帮我起草一份读书会活动策划大纲',
    '制定一份省钱的一周高蛋白饮食计划',
    '设计一份新手每周 3 练的健身分化计划'
  ]
}

interface ActionButtonsProps {
  onSelectPrompt: (prompt: string) => void
  onCategoryClick: (category: string) => void
  inputRef?: React.RefObject<HTMLTextAreaElement>
  className?: string
}

export function ActionButtons({
  onSelectPrompt,
  onCategoryClick,
  inputRef,
  className
}: ActionButtonsProps) {
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const handleCategoryClick = (category: ActionCategory) => {
    setActiveCategory(category.key)
    onCategoryClick(category.label)
    captureClient('example_category_opened', { category: category.key })
  }

  const handlePromptClick = (prompt: string) => {
    captureClient('example_prompt_clicked', {
      category: activeCategory,
      prompt
    })
    setActiveCategory(null)
    onSelectPrompt(prompt)
  }

  const resetToButtons = () => {
    setActiveCategory(null)
  }

  // Handle Escape key and clicks outside (including focus loss)
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && activeCategory) {
        resetToButtons()
      }
    }

    const handleClickOutside = (e: MouseEvent) => {
      if (
        containerRef.current &&
        !containerRef.current.contains(e.target as Node)
      ) {
        if (activeCategory) {
          // Check if click is not on the input field
          if (!inputRef?.current?.contains(e.target as Node)) {
            resetToButtons()
          }
        }
      }
    }

    const handleFocusOut = () => {
      // Check if focus is moving outside both the container and input
      setTimeout(() => {
        const activeElement = document.activeElement
        if (
          activeCategory &&
          !containerRef.current?.contains(activeElement) &&
          activeElement !== inputRef?.current
        ) {
          resetToButtons()
        }
      }, FOCUS_OUT_DELAY_MS)
    }

    document.addEventListener('keydown', handleEscape)
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('focusout', handleFocusOut)

    return () => {
      document.removeEventListener('keydown', handleEscape)
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('focusout', handleFocusOut)
    }
  }, [activeCategory, inputRef])

  // Max height for samples (4 items up to 2 lines each + padding); overflow scrolls
  const containerHeight = 'h-[232px]'

  return (
    <div
      ref={containerRef}
      className={cn('relative', containerHeight, className)}
    >
      <div className="relative h-full">
        {/* Action buttons */}
        <div
          className={cn(
            'absolute inset-0 flex items-start justify-center pt-2 transition-opacity duration-[180ms] ease-[var(--motion-ease-out)]',
            activeCategory ? 'opacity-0 pointer-events-none' : 'opacity-100'
          )}
        >
          <div className="flex flex-wrap justify-center gap-2 px-2">
            {actionCategories.map(category => {
              const Icon = category.icon
              return (
                <Button
                  key={category.key}
                  type="button"
                  variant="outline"
                  size="sm"
                  className={cn(
                    'flex items-center gap-2 whitespace-nowrap rounded-full',
                    'text-xs sm:text-sm px-3 sm:px-4'
                  )}
                  onClick={() => handleCategoryClick(category)}
                >
                  <Icon className="h-3 w-3 sm:h-4 sm:w-4" />
                  <span>{category.label}</span>
                </Button>
              )
            })}
          </div>
        </div>

        {/* Prompt samples */}
        <div
          className={cn(
            'absolute inset-0 space-y-1 overflow-y-auto py-1 transition-opacity duration-[180ms] ease-[var(--motion-ease-out)]',
            !activeCategory ? 'opacity-0 pointer-events-none' : 'opacity-100'
          )}
        >
          {activeCategory &&
            promptSamples[activeCategory]?.map((prompt, index) => (
              <button
                key={index}
                type="button"
                className={cn(
                  'w-full rounded-md px-3 py-2 text-left text-sm',
                  'transition-colors duration-[140ms] ease-[var(--motion-ease-out)] hover:bg-muted',
                  'flex items-center gap-2 group'
                )}
                onClick={() => handlePromptClick(prompt)}
              >
                <Search className="h-3 w-3 text-muted-foreground flex-shrink-0 group-hover:text-foreground" />
                <span className="line-clamp-2">{prompt}</span>
              </button>
            ))}
        </div>
      </div>
    </div>
  )
}
