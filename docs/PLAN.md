# Ryoshi 改造计划

> 本文档是 Ryoshi 项目的总体改造蓝图。
> 目标：将开源 AI 搜索引擎 morhpic（Next.js + TypeScript）迁移为 **Python 后端 + React 前端** 的自有项目，启动效果与原站一致，并作为长期演进的技术基底。

---

## 一、项目定位

这次改造**不是**对 morhpic 的逐行翻译复刻，而是分三步走：

1. **理解内核** —— 读懂 morhpic 的核心机制（流式协议、智能体循环、消息管线）
2. **干净重写** —— 用 Python 原生能力重新设计后端，砍掉为适配 Vercel AI SDK 而产生的技术债
3. **自主演进** —— 得到一个完全掌控、方便长期改造的项目基底

### 为什么不逐行翻译

morhpic 的 SSE 流式管线（`lib/streaming/` 下 20 多个 helper）有大量复杂度来自"适配 Vercel AI SDK 的特有协议"，而非业务必需。Python 后端将基于 **LangGraph** 的原生能力重新设计这条管线，做到**逻辑等价但代码量大幅精简**，且每一行都能被真正理解——这比翻译过来的、连原作者都嫌绕的代码更适合长期演进。

---

## 二、目标与边界

| 项 | 约定 |
|---|---|
| 工作目录 | `/Users/chenshui/code/Ryoshi`（**绝不修改 morhpic 源码**，所有产出在此目录） |
| 最终效果 | 启动后与 morhpic 的界面 / 交互 / 流式体验一致 |
| 项目名 | 全量 `morphic` → `Ryoshi`（代码、注释、AI 自称、Docker 服务名、数据库名、环境变量） |
| 注释语言 | 全部中文，且是**讲清设计意图的教学级注释**，不是逐行翻译 |
| 前端 | 保留 React（约 1.7 万行），仅改 API 地址 + 流式对接 |
| 后端 | Python 3.12 + FastAPI + LangGraph，重新设计而非翻译 |
| 可观测性 | Langfuse 链路追踪 + PostHog 分析，全部保留（使用 Python SDK） |
| 数据库 | PostgreSQL 表结构照搬，SQLAlchemy 2.0 + Alembic |
| 搜索 | 多 provider：Tavily / SearXNG / Brave / Exa，含失败降级 |

### 用户侧体验：零变化

浏览器里的一切——聊天界面、流式打字效果、搜索结果卡片、图片网格、追问按钮、侧栏历史、模型选择器、深浅色主题——**像素级不变**。前端只认 SSE 流的数据格式，不关心流由 Node 还是 Python 生成。

唯一变化是本地启动方式：

```bash
# 原项目
bun dev                              # 单进程全包

# Ryoshi
uvicorn ryoshi.main:app --reload     # 终端 1：Python 后端 (:8000)
bun dev --cwd apps/web               # 终端 2：前端 (:3000)

# Docker 部署体验不变
docker compose up -d                 # 起全部服务，访问 http://localhost:3000
```

---

## 三、技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| Web 框架 | **FastAPI** | Python 主流，异步一流，原生支持 SSE 流式响应 |
| 智能体 | **LangGraph** | 对应原 `ToolLoopAgent`：工具循环、步数上限、流式输出内置 |
| 模型接入 | LangChain 模型层 / 官方 SDK | OpenAI / Anthropic / Google / Ollama 全覆盖 |
| ORM | **SQLAlchemy 2.0** + Alembic | 对应 Drizzle，表结构直接照搬 |
| 搜索 SDK | `tavily-python`、`exa-py`，Brave 走 HTTP | 官方 SDK |
| 缓存 / 限流 | `redis-py` | 现有逻辑平移 |
| 认证 | Supabase JWT 校验（`python-jose`） | Supabase 继续沿用 |
| 链路追踪 | `langfuse` Python SDK | 对应原 Langfuse 集成 |
| 行为分析 | `posthog` Python SDK | 对应原 posthog-node |
| 依赖管理 | **uv** | 现代 Python 包管理，锁文件可复现 |
| 前端 | 保留现有 Vite + React 19 + shadcn/ui | 原样保留，仅改 API 层 |

### 模块映射（morhpic → Ryoshi）

```
lib/agents/researcher.ts        → apps/server/src/ryoshi/agents/researcher.py (LangGraph)
lib/tools/search.ts + providers → apps/server/src/ryoshi/tools/search.py
lib/tools/fetch.ts              → apps/server/src/ryoshi/tools/fetch.py
lib/streaming/ (20+ helper)     → apps/server/src/ryoshi/chat/pipeline.py (重新设计)
lib/db/schema.ts                → apps/server/src/ryoshi/db/models.py (SQLAlchemy)
app/api/chat/route.ts           → apps/server/src/ryoshi/api/chat.py (FastAPI + SSE)
lib/rate-limit/                 → apps/server/src/ryoshi/ratelimit/ (Redis)
lib/auth/                       → apps/server/src/ryoshi/auth/ (Supabase JWT)
lib/render/catalog.ts           → spec 校验移至后端 Pydantic,前端渲染代码不动
instrumentation.ts (Langfuse)   → apps/server/src/ryoshi/observability/tracing.py
lib/analytics/ (PostHog)        → apps/server/src/ryoshi/observability/analytics.py
```

---

## 四、目录结构

```
/Users/chenshui/code/Ryoshi/
├── apps/
│   ├── web/                        # React 前端（从 morhpic 拷贝后改造）
│   │   ├── components/             # 原样保留，中文注释
│   │   ├── hooks/                  # 原样保留
│   │   ├── lib/
│   │   │   └── api.ts              # 新增：统一 API 客户端，指向 :8000
│   │   ├── app/ 或 src/            # 页面（RSC 改为客户端数据加载）
│   │   └── vite.config.ts          # 新增：开发代理到 Python 后端
│   └── server/                     # Python 后端（全新）
│       ├── pyproject.toml          # uv 管理
│       └── src/ryoshi/
│           ├── main.py             # FastAPI 入口
│           ├── api/                # 路由：chat / chats / upload / feedback / share
│           ├── agents/             # LangGraph 研究智能体（quick / adaptive 双模式）
│           ├── tools/              # search / fetch / todo / question
│           ├── chat/               # 消息管线（准备 / 截断 / 持久化 / SSE 生成）
│           ├── db/                 # SQLAlchemy 模型 + Alembic 迁移
│           ├── auth/               # Supabase JWT 校验 + 匿名模式
│           ├── ratelimit/          # Redis 限流
│           └── observability/      # Langfuse + PostHog
├── packages/
│   └── protocol/                   # SSE 消息协议契约（TS 类型 + Python 模型共享）
├── docs/
│   └── PLAN.md                     # 本文档
├── docker-compose.yaml             # postgres + redis + searxng + server + web
└── README.md                       # 中文：架构图 + 如何演进
```

---

## 五、分阶段任务

### 阶段 0 · 地基（不动逻辑，先让骨架能跑）

1. 创建 `/Users/chenshui/code/Ryoshi`，`git init`
2. 拷贝 morhpic 前端相关代码到 `apps/web`；拷贝 `docker-compose`、数据库 schema 作参考
3. **全量品牌替换** `morphic` → `Ryoshi`：
   - 代码与包名（`package.json`、目录）
   - **AI 自称**：`lib/agents/prompts/search-mode-prompts.ts` 中 "You are Morphic…" → "You are Ryoshi…"（不改这里 AI 仍会自称 Morphic）
   - 环境变量前缀 `MORPHIC_*` → `RYOSHI_*`（如 `MORPHIC_CLOUD_DEPLOYMENT`）
   - Docker 服务名、数据库名、compose project 名
   - UI 文案、文档、配置
4. 搭建 Python 后端骨架：FastAPI 跑通 `GET /health`，uv 管理依赖
5. `docker-compose` 起 postgres / redis / searxng，验证连通

### 阶段 1 · 数据层

6. SQLAlchemy 模型：照搬 `chats / messages / parts / notes / files / feedback` 六张表
   - 含行级安全（RLS）策略
   - 每张表配中文注释讲清职责
7. Alembic 初始化迁移，与原 Drizzle schema 对齐
8. 数据访问层（对应 `lib/actions/`）：loadChat / saveMessage / 历史查询

### 阶段 2 · 协议契约（成败关键，最先钉死）

9. **逆向 morhpic 实际吐出的 UIMessageStream SSE 帧格式**：
   - `text-delta` / `tool-call` / `source` / `data-*` 等各种 part 类型
   - 写成 `packages/protocol/` 的共享契约文档 + Python Pydantic 模型
10. 实现 Python 的 SSE 生成器 + `smoothStream` 按词平滑逻辑

### 阶段 3 · 最小闭环（Quick 模式端到端）

11. 搜索工具：Tavily provider 先行（其余后补）
12. LangGraph 研究智能体：Quick 模式（search + fetch，maxSteps=20，system prompt 中 AI 自称 Ryoshi）
13. `/api/chat` 路由：消息准备 → 智能体流式 → SSE 输出 → 持久化
14. 前端对接：API 地址指向 `:8000`，Vite 代理 —— **跑通第一次提问并看到流式回答**

### 阶段 4 · 能力补全

15. Adaptive 模式（todoWrite 工具、maxSteps=50、追问工具 askQuestion）
16. 其余搜索 provider：SearXNG / Brave / Exa + 失败降级链
17. 文件上传（S3）、附件 token 估算、上下文窗口截断
18. 认证：Supabase JWT + 匿名模式 + 访客限流
19. 分享页（`/share/[id]`）：轻量 SSR 实现
20. 标题生成、相关追问、笔记、feedback

### 阶段 5 · 观测与打磨

21. Langfuse 链路追踪（traceId 贯穿智能体 + 标题生成）
22. PostHog 事件（chat 提交、turn 计算、queryShape）
23. 限流三层（访客 IP / 用户总量 / adaptive 单独）

### 阶段 6 · 验收与文档

24. 对照原站逐项验收：流式手感、组件渲染、降级、限流、错误文案
25. 中文 README：架构图、如何新增工具 / 模型 / provider（为演进铺路）
26. 关键模块补教学级注释（讲清"为什么这么设计"，而非"这是什么"）

---

## 六、关键风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| **SSE 协议对不上**导致前端渲染失败 | 致命 | 阶段 2 最先钉死契约；用 morhpic 真实输出录样本，做 Python 侧的黄金测试 |
| LangGraph 与 AI SDK 的 tool-loop 行为差异 | 高 | 阶段 3 先用最简单的 Quick 模式验证，再扩 Adaptive |
| 流式手感不一致（"蹦字"而非"打字"） | 中 | 复刻 `smoothStream` 节流逻辑，逐项 A/B 对比 |
| RSC 改 API 调用后首屏数据缺失 | 中 | 10 个 RSC 页面逐个核对数据来源，loading 态对齐 |
| 隐性行为契约丢失（降级顺序 / 429 响应 / 错误文案 / cookie 记忆） | 中 | 验收清单逐项核对 |

### 三个"可能不一样"的重点验收项

1. **流式手感**：现在是按词平滑输出，Python 侧要实现同样的节流 / 拼词逻辑
2. **SSE 消息协议**：前端 `useChat` 只认 AI SDK 的 UIMessageStream 格式，必须逐字节对齐
3. **行为细节**：搜索降级顺序、限流 429 响应体、错误提示文案、cookie 中的模型 / searchMode 记忆

---

## 七、品牌替换清单

| 位置 | 原值 | 新值 |
|---|---|---|
| 包名 / 项目名 | `morphic` | `ryoshi` |
| AI 自称（system prompt） | `You are Morphic…` | `You are Ryoshi…` |
| 页面标题 / 侧边栏 | `Morphic` | `Ryoshi` |
| 环境变量前缀 | `MORPHIC_*` | `RYOSHI_*` |
| Docker compose project | `morphic-stack` | `ryoshi-stack` |
| 数据库名 / 用户 | `morphic` | `ryoshi` |
| 元数据 URL | `https://morphic.sh` | 待定（可先用占位） |

---

## 八、执行约定

- 严格按阶段 0 → 6 推进，**阶段 3 结束即可首次提问成功**（快速获得正反馈）
- 每个阶段完成后用 git commit 固化，可回溯
- 遇到协议 / 行为不确定处，**以 morhpic 源码实际行为为准**，不凭文档猜测
- 所有注释中文，优先讲清设计意图
