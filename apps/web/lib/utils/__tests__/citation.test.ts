import { describe, expect, it } from 'vitest'

import { extractCitationMaps, isCitationLabel } from '@/lib/utils/citation'
import type { UIMessage } from '@/lib/types/ai'

/**
 * citation 工具函数是"引用上标 → 来源详情"交互的核心:
 * [number](#toolCallId) 的渲染完全依赖这里把 tool 部件抽成
 * toolCallId → {序号: 搜索结果} 的映射。锁定其行为。
 */

const makeSearchPart = (
  toolCallId: string,
  results: Array<{ title: string; url: string; content: string }>
) => ({
  type: 'tool-search' as const,
  toolCallId,
  state: 'output-available' as const,
  input: { query: '测试' },
  output: { state: 'complete', results, images: [], query: '测试' }
})

describe('isCitationLabel', () => {
  it('识别普通 toolCallId 形态', () => {
    expect(isCitationLabel('call_abc123')).toBe(true)
    expect(isCitationLabel('toolu_xyz')).toBe(true)
  })

  it('拒绝 URL 与普通文本(非引用标签)', () => {
    expect(isCitationLabel('https://example.com')).toBe(false)
    expect(isCitationLabel('hello world')).toBe(false)
  })
})

describe('extractCitationMaps', () => {
  it('把一次搜索的输出抽成 序号→结果 映射', () => {
    const message = {
      id: 'm1',
      role: 'assistant',
      parts: [
        makeSearchPart('call_1', [
          { title: '结果一', url: 'https://a.com', content: '...' },
          { title: '结果二', url: 'https://b.com', content: '...' }
        ])
      ]
    } as unknown as UIMessage

    const maps = extractCitationMaps(message)
    expect(maps['call_1']).toBeDefined()
    expect(maps['call_1'][1]).toMatchObject({
      title: '结果一',
      url: 'https://a.com'
    })
    expect(maps['call_1'][2]).toMatchObject({
      title: '结果二',
      url: 'https://b.com'
    })
  })

  it('无搜索部件时返回空映射', () => {
    const message = {
      id: 'm2',
      role: 'assistant',
      parts: [{ type: 'text', text: '纯文本回答' }]
    } as unknown as UIMessage
    expect(extractCitationMaps(message)).toEqual({})
  })
})
