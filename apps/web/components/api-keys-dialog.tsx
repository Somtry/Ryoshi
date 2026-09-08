'use client'

/// BYOK(Bring Your Own Key)设置对话框。
///
/// 设计意图:
///   对应后端 /api/keys 接口。登录用户在这里为每个 AI provider 配置自己的
///   API key,后端构造模型时优先使用用户密钥,环境变量仅作兜底。
///
///   展示策略:
///     - 已配置的 provider 显示掩码 key(••••••••abcd),可删除或重新填写覆盖
///     - 未配置的 provider 显示"Add key"按钮,展开成表单
///     - openai-compatible:填 key + base_url → 点"获取模型"拉取列表 → 勾选保存
///
///   安全约束:
///     - 密钥只在提交时经 HTTPS 发给后端,绝不回显明文
///     - 所有请求经 apiFetch 自动携带 Supabase JWT

import { useCallback, useEffect, useState } from 'react'

import {
  IconCheck as Check,
  IconChevronDown as ChevronDown,
  IconKey as Key,
  IconPlus as Plus,
  IconRefresh as RefreshCw,
  IconTrash as Trash2
} from '@tabler/icons-react'
import { toast } from 'sonner'

import { apiFetch } from '@/lib/api-client'
import { BYOK_KEYS_UPDATED_EVENT } from '@/lib/events'
import { cn } from '@/lib/utils'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PasswordInput } from '@/components/ui/password-input'
import { Separator } from '@/components/ui/separator'
import { Spinner } from '@/components/ui/spinner'

/// 与后端 agents/models.py 的 BYOK_PROVIDERS 对齐
const PROVIDERS = [
  {
    id: 'openai',
    name: 'OpenAI',
    hint: 'platform.openai.com/api-keys',
    needsEndpoint: false
  },
  {
    id: 'anthropic',
    name: 'Anthropic',
    hint: 'console.anthropic.com',
    needsEndpoint: false
  },
  {
    id: 'google',
    name: 'Google Gemini',
    hint: 'aistudio.google.com/apikey',
    needsEndpoint: false
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    hint: 'platform.deepseek.com',
    needsEndpoint: false
  },
  {
    id: 'openai-compatible',
    name: 'OpenAI Compatible',
    hint: 'DeepSeek / Moonshot / 自建等任意兼容端点',
    needsEndpoint: true
  }
] as const

type ProviderId = (typeof PROVIDERS)[number]['id']

interface KeySummary {
  provider: ProviderId
  masked_key: string
  base_url: string | null
  models: string[] | null
  provider_name: string | null
  enabled: boolean
}

interface KeyListResponse {
  keys: KeySummary[]
  providers: ProviderId[]
}

interface DiscoveredModel {
  id: string
  name: string
  description?: string
}

interface ApiKeysDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ApiKeysDialog({ open, onOpenChange }: ApiKeysDialogProps) {
  const [loading, setLoading] = useState(false)
  const [keys, setKeys] = useState<KeySummary[]>([])
  /// 当前展开编辑表单的 provider;null 表示全部收起
  const [editingProvider, setEditingProvider] = useState<ProviderId | null>(null)
  const [deletingProvider, setDeletingProvider] = useState<ProviderId | null>(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const data = await apiFetch<KeyListResponse>('/api/keys')
      setKeys(data.keys)
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : '加载 API 密钥失败'
      )
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (open) {
      void refresh()
      setEditingProvider(null)
    }
  }, [open, refresh])

  const keysByProvider = new Map(keys.map(k => [k.provider, k]))

  const handleDelete = async (provider: ProviderId) => {
    setDeletingProvider(provider)
    try {
      await apiFetch(`/api/keys/${provider}`, { method: 'DELETE' })
      toast.success('API 密钥已删除')
      // 触发事件通知所有页面刷新模型列表
      window.dispatchEvent(new CustomEvent(BYOK_KEYS_UPDATED_EVENT))
      await refresh()
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : '删除 API 密钥失败'
      )
    } finally {
      setDeletingProvider(null)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>API 密钥</DialogTitle>
          <DialogDescription>
            在这里配置你自己的 AI 服务商密钥。密钥加密存储，不会明文展示。
          </DialogDescription>
        </DialogHeader>

        {loading && keys.length === 0 ? (
          <div className="flex justify-center py-8">
            <Spinner />
          </div>
        ) : (
          <div className="grid gap-1">
            {PROVIDERS.map((p, idx) => {
              const existing = keysByProvider.get(p.id)
              const isEditing = editingProvider === p.id
              return (
                <div key={p.id}>
                  {idx > 0 && <Separator className="my-1" />}
                  <ProviderRow
                    provider={p}
                    existing={existing}
                    isEditing={isEditing}
                    isDeleting={deletingProvider === p.id}
                    onEdit={() =>
                      setEditingProvider(isEditing ? null : p.id)
                    }
                    onCancel={() => setEditingProvider(null)}
                    onDelete={() => handleDelete(p.id)}
                    onSaved={async () => {
                      setEditingProvider(null)
                      await refresh()
                    }}
                  />
                </div>
              )
            })}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

interface ProviderRowProps {
  provider: (typeof PROVIDERS)[number]
  existing: KeySummary | undefined
  isEditing: boolean
  isDeleting: boolean
  onEdit: () => void
  onCancel: () => void
  onDelete: () => void
  onSaved: () => Promise<void>
}

/// 各 provider 的默认 base_url(用于模型发现)
const PROVIDER_BASE_URLS: Record<ProviderId, string> = {
  openai: 'https://api.openai.com/v1',
  anthropic: 'https://api.anthropic.com',
  google: 'https://generativelanguage.googleapis.com',
  deepseek: 'https://api.deepseek.com',
  'openai-compatible': ''
}

function ProviderRow({
  provider,
  existing,
  isEditing,
  isDeleting,
  onEdit,
  onCancel,
  onDelete,
  onSaved
}: ProviderRowProps) {
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [providerName, setProviderName] = useState('')
  const [saving, setSaving] = useState(false)
  const [fetchingModels, setFetchingModels] = useState(false)
  /// 从端点拉取到的模型列表
  const [discoveredModels, setDiscoveredModels] = useState<DiscoveredModel[]>([])
  /// 用户勾选的模型 id 列表
  const [selectedModels, setSelectedModels] = useState<string[]>([])
  /// 手动输入的模型 id(列表拉取之外的补充,如 provider 未列出的新模型)
  const [manualModelInput, setManualModelInput] = useState('')

  // 展开编辑时,若是覆盖已有 key,预填 endpoint 字段(key 本身不回显)
  useEffect(() => {
    if (isEditing) {
      setApiKey('')
      setBaseUrl(existing?.base_url ?? '')
      setProviderName(existing?.provider_name ?? '')
      // 已有配置时,把已选模型填回来
      setSelectedModels(existing?.models ?? [])
      // 清空待拉取状态,避免显示旧数据
      setDiscoveredModels([])
    }
  }, [isEditing, existing])

  // apiKey 或 baseUrl 变化时清空已拉取的模型列表,防止基于过时数据保存
  useEffect(() => {
    setDiscoveredModels([])
  }, [apiKey, baseUrl])

  const handleFetchModels = async () => {
    // 编辑已有配置时,如果用户没填新 key,用已有 key(传 null 让后端知道)
    // 新配置时必须填 key
    if (!existing && !apiKey.trim()) {
      toast.error('请先输入 API 密钥')
      return
    }

    // openai-compatible 需要 base_url,其他 provider 用默认 URL
    const effectiveBaseUrl = provider.needsEndpoint
      ? baseUrl.trim()
      : PROVIDER_BASE_URLS[provider.id]

    if (provider.needsEndpoint && !baseUrl.trim()) {
      toast.error('请先输入 Base URL')
      return
    }

    setFetchingModels(true)
    try {
      const data = await apiFetch<{ models: DiscoveredModel[] }>(
        '/api/keys/discover-models',
        {
          method: 'POST',
          body: JSON.stringify({
            // 已有配置且没填新 key → 传 null,后端用已有 key
            api_key: apiKey.trim() || null,
            base_url: effectiveBaseUrl,
            provider: provider.id
          })
        }
      )
      setDiscoveredModels(data.models)
      if (data.models.length === 0) {
        toast.info('没有发现可用模型')
      } else {
        toast.success(`发现 ${data.models.length} 个模型`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '获取模型列表失败')
      setDiscoveredModels([])
    } finally {
      setFetchingModels(false)
    }
  }

  const toggleModel = (modelId: string) => {
    setSelectedModels(prev =>
      prev.includes(modelId)
        ? prev.filter(id => id !== modelId)
        : [...prev, modelId]
    )
  }

  /// 手动添加模型 id:provider 的 /models 列表未必包含全部可用模型
  /// (尤其 openai/anthropic 新模型上线滞后),允许用户直接填 id 追加
  const handleAddManualModel = () => {
    const id = manualModelInput.trim()
    if (!id) return
    if (selectedModels.includes(id)) {
      toast.info('该模型已在列表中')
      return
    }
    setSelectedModels(prev => [...prev, id])
    setManualModelInput('')
  }

  const handleSave = async () => {
    if (selectedModels.length === 0) {
      toast.error('请至少选择一个模型')
      return
    }
    // When editing an existing key, apiKey can be empty (keep existing key)
    if (!existing && !apiKey.trim()) {
      toast.error('请填写 API 密钥')
      return
    }
    if (provider.needsEndpoint && !baseUrl.trim()) {
      toast.error('请填写 Base URL')
      return
    }

    setSaving(true)
    try {
      // api_key 为 null 表示保留已有密钥(仅当已存在时)
      const apiKeyToSend = apiKey.trim() || (existing ? null : apiKey.trim())
      await apiFetch(`/api/keys/${provider.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          api_key: apiKeyToSend,
          ...(provider.needsEndpoint
            ? {
                base_url: baseUrl.trim(),
                // 后端期望 JSON 数组字符串
                models: JSON.stringify(selectedModels),
                provider_name: providerName.trim() || null
              }
            : {
                models: JSON.stringify(selectedModels)
              })
        })
      })
      toast.success(`${provider.name} 密钥已保存`)
      // 触发事件通知所有页面刷新模型列表
      window.dispatchEvent(new CustomEvent(BYOK_KEYS_UPDATED_EVENT))
      await onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save key')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Key className="size-4 shrink-0 text-muted-foreground" />
          <div className="min-w-0 flex-1">
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-medium">{provider.name}</span>
              {existing && (
                <span className="truncate font-mono text-xs text-muted-foreground">
                  {existing.masked_key}
                </span>
              )}
            </div>
            <p className="truncate text-xs text-muted-foreground">
              {existing
                ? existing.provider === 'openai-compatible'
                  ? `${existing.provider_name || 'OpenAI Compatible'} · ${existing.models?.length || 0} 个模型`
                  : provider.hint
                : provider.hint}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {existing && !isEditing && (
            <Button
              variant="ghost"
              size="icon"
              className="size-8 text-muted-foreground hover:text-destructive"
              onClick={onDelete}
              disabled={isDeleting}
              title="删除密钥"
            >
              {isDeleting ? <Spinner /> : <Trash2 className="size-4" />}
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1 px-2"
            onClick={onEdit}
            aria-expanded={isEditing}
          >
            {isEditing ? (
              <>
                <ChevronDown className="size-3.5 rotate-180" />
                取消
              </>
            ) : existing ? (
              <>
                <ChevronDown className="size-3.5" />
                更换
              </>
            ) : (
              <>
                <Plus className="size-3.5" />
                添加密钥
              </>
            )}
          </Button>
        </div>
      </div>

      {isEditing && (
        <div className="mt-3 grid gap-3 rounded-md border bg-muted/40 p-3">
          <div className="grid gap-1.5">
            <Label htmlFor={`key-${provider.id}`} className="text-xs">
              API 密钥 {existing && <span className="text-muted-foreground">（留空则保持不变）</span>}
            </Label>
            <PasswordInput
              id={`key-${provider.id}`}
              placeholder={
                existing ? '输入新密钥，留空则不修改' : 'sk-...'
              }
              value={apiKey}
              onChange={e => setApiKey(e.target.value)}
              autoComplete="off"
            />
          </div>

          {provider.needsEndpoint && (
            <div className="grid gap-1.5">
              <Label htmlFor={`base-${provider.id}`} className="text-xs">
                Base URL
              </Label>
              <Input
                id={`base-${provider.id}`}
                placeholder="https://api.deepseek.com"
                value={baseUrl}
                onChange={e => setBaseUrl(e.target.value)}
                autoComplete="off"
              />
            </div>
          )}

          <div className="grid gap-1.5">
            <div className="flex items-center justify-between">
              <Label className="text-xs">可用模型</Label>
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-7 gap-1.5 text-xs"
                onClick={handleFetchModels}
                disabled={
                  fetchingModels ||
                  (!apiKey.trim() && !existing) ||
                  (provider.needsEndpoint && !baseUrl.trim())
                }
              >
                {fetchingModels ? (
                  <Spinner className="size-3" />
                ) : (
                  <RefreshCw className="size-3" />
                )}
                获取模型列表
              </Button>
            </div>

            {discoveredModels.length > 0 && (
              <div className="max-h-40 overflow-y-auto rounded-md border bg-background p-2">
                {discoveredModels.map(model => (
                  <label
                    key={model.id}
                    className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 hover:bg-muted"
                  >
                    <Checkbox
                      checked={selectedModels.includes(model.id)}
                      onCheckedChange={() => toggleModel(model.id)}
                    />
                    <span className="text-sm">{model.name}</span>
                    {model.description && (
                      <span className="text-xs text-muted-foreground">
                        {model.description}
                      </span>
                    )}
                  </label>
                ))}
              </div>
            )}

            {/* 手动添加模型:provider 列表未覆盖(新模型/灰度模型)时直填 id */}
            <div className="flex gap-2">
              <Input
                value={manualModelInput}
                onChange={e => setManualModelInput(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    handleAddManualModel()
                  }
                }}
                placeholder="手动添加模型 id（如 gpt-5.2、deepseek-reasoner）"
                className="h-8 text-xs"
              />
              <Button
                type="button"
                variant="outline"
                size="sm"
                className="h-8 shrink-0"
                onClick={handleAddManualModel}
                disabled={!manualModelInput.trim()}
              >
                添加
              </Button>
            </div>

            {selectedModels.length > 0 && (
              <div className="rounded-md border bg-muted/20 p-2 text-xs">
                <p className="font-medium text-muted-foreground mb-1">
                  已选模型（{selectedModels.length}）：
                </p>
                <div className="flex flex-wrap gap-1">
                  {selectedModels.map(m => (
                    <span
                      key={m}
                      className="inline-flex items-center gap-1 rounded bg-secondary px-1.5 py-0.5 text-xs"
                    >
                      {m}
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-foreground"
                        onClick={() => toggleModel(m)}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {provider.needsEndpoint && (
            <div className="grid gap-1.5">
              <Label htmlFor={`name-${provider.id}`} className="text-xs">
                显示名称（可选）
              </Label>
              <Input
                id={`name-${provider.id}`}
                placeholder="DeepSeek"
                value={providerName}
                onChange={e => setProviderName(e.target.value)}
                autoComplete="off"
              />
            </div>
          )}

          <div className="flex justify-end">
            <Button
              size="sm"
              className="gap-1.5"
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? <Spinner /> : <Check className="size-4" />}
              保存
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
