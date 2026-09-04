export type ShortcutDefinition = {
  id: string
  key: string
  meta: boolean
  shift: boolean
  /** If true, ignore shiftKey state when matching (for keys like / that require Shift on some layouts) */
  ignoreShift?: boolean
  description: string
}

export const SHORTCUTS = {
  toggleSidebar: {
    id: 'toggleSidebar',
    key: 'b',
    meta: true,
    shift: false,
    description: '打开 / 收起侧边栏'
  },
  newChat: {
    id: 'newChat',
    key: 'o',
    meta: true,
    shift: true,
    description: '新对话'
  },
  toggleTheme: {
    id: 'toggleTheme',
    key: 'd',
    meta: true,
    shift: true,
    description: '切换主题'
  },
  copyMessage: {
    id: 'copyMessage',
    key: 'c',
    meta: true,
    shift: true,
    description: '复制最新一条回答'
  },
  toggleSearchMode: {
    id: 'toggleSearchMode',
    key: 'm',
    meta: true,
    shift: true,
    description: '切换搜索模式'
  },
  showShortcuts: {
    id: 'showShortcuts',
    key: '/',
    meta: true,
    shift: false,
    ignoreShift: true,
    description: '显示键盘快捷键'
  }
} as const satisfies Record<string, ShortcutDefinition>

export const SHORTCUT_EVENTS = {
  newChat: 'shortcut:new-chat',
  copyMessage: 'shortcut:copy-message',
  showShortcuts: 'shortcut:show-shortcuts'
} as const

export function formatShortcutKeys(shortcut: ShortcutDefinition): string[] {
  const isMac =
    typeof navigator !== 'undefined' &&
    navigator.userAgent.toLowerCase().includes('mac')
  const keys: string[] = []
  keys.push(isMac ? '⌘' : 'Ctrl')
  if (shortcut.shift) keys.push('Shift')
  keys.push(shortcut.key.toUpperCase())
  return keys
}

export function matchesShortcut(
  event: KeyboardEvent,
  shortcut: ShortcutDefinition
): boolean {
  if (event.repeat) return false
  if (event.altKey) return false
  const shiftMatch = shortcut.ignoreShift
    ? true
    : event.shiftKey === shortcut.shift
  return (
    event.key.toLowerCase() === shortcut.key &&
    (event.metaKey || event.ctrlKey) === shortcut.meta &&
    shiftMatch
  )
}
