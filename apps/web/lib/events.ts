/// 全局事件常量。
///
/// 用于跨组件通信的自定义事件名,集中管理避免字符串漂移。

/// BYOK 密钥配置更新事件。
/// 触发时机:用户保存/删除 API key 后,通知所有页面刷新模型列表。
export const BYOK_KEYS_UPDATED_EVENT = 'ryoshi-byok-keys-updated'

/// 开新对话事件。
/// 触发时机:用户点击侧边栏 "New" 按钮,通知 Chat 组件清空消息、生成新 chatId。
export const NEW_CHAT_EVENT = 'ryoshi-new-chat'
