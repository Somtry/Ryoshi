/// Supabase 公开配置的读取(Vite 环境变量)。
///
/// 原项目用 Next 的 NEXT_PUBLIC_* 前缀;SPA 用 Vite 的 VITE_* 前缀,
/// 经 import.meta.env 在构建期注入。

export function getSupabasePublishableKey(): string | undefined {
  return import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined
}

export function hasSupabasePublicConfig(): boolean {
  return Boolean(
    import.meta.env.VITE_SUPABASE_URL && getSupabasePublishableKey()
  )
}
