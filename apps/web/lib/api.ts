/// 统一的后端 API 地址配置。
///
/// 设计意图:
///   原项目是 Next.js 前后端同域,API 路径写死为 "/api/xxx";
///   Ryoshi 前后端分离(前端 :3000,后端 :8000),需要一个集中的地方
///   决定 API 打到哪。开发期经 Vite 代理转发到 :8000,保持代码里
///   仍写 "/api/xxx" 不变;若将来要直连,改这里或 vite.config 的代理即可。

/// 后端 API 的基础路径。默认走同源(Vite 开发代理负责转发到 :8000)。
export const API_BASE = ''

/// 聊天流式接口地址。chat.tsx 里 DefaultChatTransport 的 api 参数用它。
export const CHAT_API = `${API_BASE}/api/chat`
