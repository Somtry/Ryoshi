# Ryoshi

> AI 驱动的生成式 UI 搜索引擎 —— Python 后端 + React 前端。

Ryoshi 是在开源项目 morhpic 的基础上，用 **Python(FastAPI + LangGraph)** 重写后端、保留 **React** 前端演化而来的自有项目。启动效果与原站一致，后端则是一套干净、可读、方便长期改造的 Python 工程。

## 架构

```
浏览器(React SPA)
  │
  │  HTTP + SSE (UIMessageStream 协议)
  ▼
FastAPI (apps/server) ─── LangGraph 智能体
  │                          │
  ├── PostgreSQL (聊天历史)   ├── search 工具(Tavily/SearXNG/Brave/Exa,含降级)
  ├── Redis (限流/缓存)       ├── fetch 工具(网页正文提取)
  ├── S3/R2 (文件上传)       ├── todoWrite/askQuestion(adaptive 模式)
  ├── Langfuse (链路追踪)     └── 上下文窗口截断
  └── PostHog (行为分析)
```

- **前端**：保留原项目的 React 组件与样式（聊天界面、流式渲染、Generative UI)，从 Next.js App Router 迁到 Vite + React Router,API 指向 Python 后端
- **后端**:Python 3.12 + FastAPI，智能体用 LangGraph 编排，ORM 用 SQLAlchemy 2.0，链路追踪 Langfuse、行为分析 PostHog

## 快速开始

### 本地开发（推荐）

```bash
# 终端 1: Python 后端
cd apps/server
uv sync                                    # 装依赖(自动下载 Python 3.12)
uv run uvicorn ryoshi.main:app --reload    # http://localhost:8000

# 终端 2: React 前端
cd apps/web
pnpm install
pnpm dev                                   # http://localhost:3000
```

### 全栈 Docker

```bash
cp .env.local.example .env.local   # 配置至少一个 AI 提供商密钥
docker compose up -d               # 起 postgres/redis/searxng/server/web
# 访问 http://localhost:3000
```

## 环境变量

核心变量（完整清单见 `.env.local.example`):

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | PostgreSQL 连接串（asyncpg 驱动） |
| `REDIS_URL` | Redis 连接串 |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_GENERATIVE_AI_API_KEY` | AI 提供商密钥（配其一即可起步） |
| `OPENAI_COMPATIBLE_*` | 通用 OpenAI 兼容端点（DeepSeek 等） |
| `TAVILY_API_KEY` / `BRAVE_API_KEY` / `EXA_API_KEY` / `SEARXNG_BASE_URL` | 搜索提供商（Tavily 默认，失败自动降级） |
| `ENABLE_AUTH` | 是否启用 Supabase 认证（默认关，匿名模式） |
| `SUPABASE_URL` / `SUPABASE_JWT_SECRET` | Supabase 项目地址与 JWT 密钥 |
| `RYOSHI_CLOUD_DEPLOYMENT` | 云端部署（强制认证 + 限流 + 分析） |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | 链路追踪（可选） |

## 如何新增工具 / 模型 / 搜索源

### 新增工具

```python
# apps/server/src/ryoshi/agents/researcher.py

@tool("myTool")  # 注意:名称用 camelCase,与前端 tool-myTool 对应
async def my_tool(query: str) -> dict:
    """工具描述(会进入模型 prompt)。"""
    return {"result": "..."}
```

然后在 `create_quick_researcher` 或 `create_adaptive_researcher` 的 tools 列表中加上它。前端在 `tool-section.tsx` 中注册渲染分支。

### 新增模型

在 `agents/models.py` 的 `get_model` 中加一个 provider 分支，并在 `api/models.py` 的 `_STATIC_MODELS` 中声明可用模型。

### 新增搜索源

在 `tools/search.py` 中继承 `SearchProvider` 协议，实现 `_search` 方法，然后在 `_PROVIDERS` 字典中注册。降级链自动生效。

## 开发进度

- [x] **阶段 0** · 地基：Python 骨架、前端拷贝、品牌替换
- [x] **阶段 1** · 数据层：SQLAlchemy 模型 + Alembic 迁移
- [x] **阶段 2** · 协议契约：UIMessageStream SSE 逆向 + Python 实现
- [x] **阶段 3** · 最小闭环：Quick 模式端到端提问
- [x] **阶段 4** · 能力补全：Adaptive / 多搜索源 / 上传 / 认证 / 分享 / 笔记 / 反馈
- [x] **阶段 5** · 观测与打磨：Langfuse + PostHog + 三层限流
- [x] **阶段 6** · 验收与文档

## 许可

基于 Apache-2.0 协议的 morhpic 项目演化而来，详见 LICENSE。
