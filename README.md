# Ryoshi

> AI 驱动的生成式 UI 搜索引擎 —— Python 后端 + React 前端。

Ryoshi 是在开源项目 morhpic 的基础上,用 **Python(FastAPI + LangGraph)** 重写后端、保留 **React** 前端演化而来的自有项目。启动效果与原站一致,后端则是一套干净、可读、方便长期改造的 Python 工程。

## 架构

```
┌───────────────────────────────┐      ┌────────────────────────────────┐
│ apps/web (前端)                │      │ apps/server (后端)              │
│ Vite + React 19 + shadcn/ui   │ SSE  │ FastAPI + LangGraph             │
│ 原 morhpic 组件几乎原样保留     │◀────▶│ 智能体 / 搜索 / 数据库 / 流式     │
└───────────────────────────────┘      └────────────────────────────────┘
        │                                        │
        └──────────────┬─────────────────────────┘
                       ▼
        PostgreSQL · Redis · SearXNG   (docker-compose 一键起)
```

- **前端**：保留原项目的 React 组件与样式（聊天界面、流式渲染、Generative UI),仅把路由从 Next.js App Router 迁到 React Router,API 指向 Python 后端
- **后端**：Python 3.12 + FastAPI,智能体用 LangGraph 编排,ORM 用 SQLAlchemy 2.0,链路追踪 Langfuse、行为分析 PostHog

## 目录

```
apps/
  web/        # React 前端(Vite + React Router)
  server/     # Python 后端(FastAPI + LangGraph)
packages/
  protocol/   # SSE 流式协议契约(前后端共享)
docs/
  PLAN.md     # 完整改造计划
docker-compose.yaml
```

## 快速开始

### 后端(Python,需要 uv)

```bash
cd apps/server
uv sync                                    # 装依赖(自动下载 Python 3.12)
uv run uvicorn ryoshi.main:app --reload    # 起服务,http://localhost:8000
curl http://localhost:8000/health          # 冒烟测试
```

### 前端(React,需要 pnpm)

```bash
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

后端环境变量统一 `RYOSHI_` 前缀(对应原项目 `MORPHIC_` 前缀)。核心变量:

| 变量 | 说明 |
|---|---|
| `DATABASE_URL` | PostgreSQL 连接串 |
| `REDIS_URL` | Redis 连接串 |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / `GOOGLE_GENERATIVE_AI_API_KEY` | AI 提供商密钥(配其一即可起步) |
| `TAVILY_API_KEY` / `SEARXNG_BASE_URL` 等 | 搜索提供商 |
| `ENABLE_AUTH` | 是否启用 Supabase 认证(默认关,匿名模式) |
| `RYOSHI_CLOUD_DEPLOYMENT` | 是否云端部署(云端强制认证) |

完整说明见 [docs/PLAN.md](./docs/PLAN.md)。

## 开发进度

本项目处于从 morhpic 迁移的进行中,按阶段推进:

- [x] **阶段 0** · 地基:Python 骨架跑通 `/health`、前端拷贝、全量品牌替换
- [ ] **阶段 1** · 数据层:SQLAlchemy 模型 + Alembic 迁移
- [ ] **阶段 2** · 协议契约:UIMessageStream SSE 逆向 + Python 实现
- [ ] **阶段 3** · 最小闭环:Quick 模式端到端提问
- [ ] **阶段 4** · 能力补全:Adaptive / 多搜索源 / 上传 / 认证 / 分享
- [ ] **阶段 5** · 观测与打磨:Langfuse + PostHog + 三层限流
- [ ] **阶段 6** · 验收与文档

## 许可

基于 Apache-2.0 协议的 morhpic 项目演化而来,详见 LICENSE。
