import { Model } from '@/lib/types/models'

export interface ModelSelectorData {
  enabled: boolean
  modelsByProvider: Record<string, Model[]>
  selectedModelKey: string
  hasAvailableModels: boolean
  /// 后端认证模式:'anonymous' 表示 ENABLE_AUTH=false(单用户共享
  /// anonymous-user,前端应视为已登录);'authenticated' 表示需要登录。
  /// 对应原型服务端 getCurrentUserId() 在匿名模式返回 anonymous-user 的行为。
  authMode?: 'anonymous' | 'authenticated'
  /// 匿名模式下的共享用户 id(仅 authMode='anonymous' 时存在)
  anonymousUserId?: string | null
}
