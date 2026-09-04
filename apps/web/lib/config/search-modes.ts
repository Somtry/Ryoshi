import { IconSearch as Search } from '@tabler/icons-react'

import { SearchMode } from '@/lib/types/search'

import { IconLogoOutline } from '@/components/ui/icons'

export interface SearchModeConfig {
  value: SearchMode
  label: string
  description: string
  icon: React.ComponentType<{ className?: string }>
  color: string
}

// Centralized search mode configuration
export const SEARCH_MODE_CONFIGS: SearchModeConfig[] = [
  {
    value: 'quick',
    label: '快速',
    description: '精简流程，快速给出简洁回答',
    icon: Search,
    color: 'text-amber-500'
  },
  {
    value: 'adaptive',
    label: '深入',
    description: '智能体自适应搜索，深入理解问题后多角度调研',
    icon: IconLogoOutline,
    color: 'text-violet-500'
  }
]

// Helper function to get a specific mode config
export function getSearchModeConfig(
  mode: SearchMode
): SearchModeConfig | undefined {
  return SEARCH_MODE_CONFIGS.find(config => config.value === mode)
}
