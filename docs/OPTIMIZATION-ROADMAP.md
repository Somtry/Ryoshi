# Ryoshi 优化路线图(优先级文档)

> 基于 2026-09-08 对全项目的代码审查(后端全部模块 + 前端关键链路 + 构建产物)整理。
> 项目主体(协议、流式、持久化、BYOK、认证、限流、观测)已完成且测试全绿;
> 本文档列出遗留缺陷、性能优化点与推荐功能,并给出执行顺序。

---

## 优先级定义

| 级别 | 含义 | 判断标准 |
|---|---|---|
| **P0** | 上线阻塞 | 安全漏洞,或用户可见的数据错误/丢失;不修则不能对外部署 |
| **P1** | 高价值低风险 | 影响部署、成本或日常体验;一两天内可完成,风险可控 |
| **P2** | 体验跃升 | 新能力,直接提升产品竞争力;需要设计,工作量 1 天以上 |
| **P3** | 打磨 | 性能与工程卫生;不紧急,按需穿插 |

工作量:S < 1h,M = 半天,L = 1~2 天。

---

## 总览

| ID | 问题 | 级别 | 类型 | 工作量 | 一句话 |
|---|---|---|---|---|---|
| P0-1 | 云端访客限流被"合桶" | P0 | 安全 | S | 所有匿名访客共享每天 10 次配额 |
| P0-2 | fetch 工具无 SSRF 防护 | P0 | 安全 | M | 可被抓去访问内网/云 metadata |
| P0-3 | regenerate 后旧回答"复活" | P0 | 数据一致性 | M | 刷新后被删的回答重新出现 |
| P0-4 | 点"停止"丢失已生成内容 | P0 | 数据一致性 | M | 中断的回答不落库,刷新即消失 |
| P0-5 | /relay 端点后端未实现 | P0 | 功能缺陷 | M | 前端分析请求 404,README 与实际不符 |
| P1-1 | reasoning 思考链整条链路是死的 | P1 | 功能缺陷 | M | 帧模型/前端组件/DB 列都齐了,只差产出 |
| P1-2 | CORS 硬编码 localhost | P1 | 部署阻塞 | S | 部署到任何服务器都要改代码 |
| P1-3 | ruff 89 错 / tsc 63 错 / 零前端测试 | P1 | 质量债 | M | build 不做类型检查,欠账会持续累积 |
| P1-4 | CI 流水线缺失 | P1 | 质量债 | S | 没有任何东西挡回归 |
| P1-5 | Redis"搜索缓存"只存在于注释 | P1 | 成本 | M | 相同 query 全价重复打搜索源 |
| P1-6 | httpx client 每请求新建 | P1 | 性能 | S | 每次搜索都完整 TCP+TLS 握手 |
| P1-7 | BYOK 用户被静态模型清单锁死 | P1 | 体验 | S | 直配 OpenAI key 只能选 gpt-4o-mini |
| P2-1 | 多模态图片输入(假支持) | P2 | 功能 | L | 上传图片后模型根本看不到图 |
| P2-2 | LLM 生成会话标题 | P2 | 功能 | M | 现在标题=首条消息截断 255 字 |
| P2-3 | Generative UI 未点亮 | P2 | 功能 | L | 前端组件齐全,prompt 指引被注释 |
| P2-4 | PDF 抓取支持 | P2 | 功能 | S~M | 现在遇 PDF 直接抛错 |
| P2-5 | /feedback 与 /upload 无限流 | P2 | 安全 | S | 匿名可无限灌反馈、刷 S3 存储 |
| P3-1 | 前端单 chunk 2.3MB | P3 | 性能 | S | gzip 702KB,首屏慢 |
| P3-2 | uvicorn 单 worker | P3 | 性能 | S | tiktoken 是 CPU-bound,会卡 event loop |
| P3-3 | 长工具执行期间无 SSE 心跳 | P3 | 稳定性 | S | 30s 搜索期间零字节,中间层可能掐连接 |
| P3-4 | 每条消息重建模型客户端 | P3 | 性能 | M | 重复 DB 查询 + TLS 握手 |
| P3-5 | print() 换 logging | P3 | 工程卫生 | S | 无访问日志,排障困难 |
| P3-6 | pre-commit 钩子 | P3 | 工程卫生 | S | 防质量债再攒 |
| P3-7 | MODEL_CONTEXT_WINDOWS 过时 | P3 | 体验 | S | 未知模型默认 16k 窗口偏保守 |
| P3-8 | 聊天导出 / 对话内搜索 | P3 | 功能 | M~L | Markdown/JSON 导出 + pg_trgm 检索 |

---

## P0 — 上线阻塞 ✅(2026-09-08 全部完成)

> 实施记录:分支 `fix/p0-stage`,57 个单测全绿。以下原文保留作为问题档案,
> 每项末尾的「实施结果」记录实际落地情况与对原方案的修正。

### P0-1 云端访客限流被"合桶"(安全)✅

- **位置**: `apps/server/src/ryoshi/api/chat.py:194`(`request.client.host`)、`apps/server/Dockerfile`(uvicorn 启动参数)
- **问题**: 生产流量经 nginx 反代后,`request.client.host` 拿到的是 **nginx 容器 IP** 而非真实用户 IP。后果:云端部署时所有匿名访客共享同一个 Redis 限流 key(`rl:guest:chat:<nginx-ip>`),**全站一天只能匿名提问 10 次**,超过后所有访客被批量 401。
- **方案**:
  1. Dockerfile 的 CMD 加 `--proxy-headers --forwarded-allow-ips='*'`(内网 compose 网络内信任 nginx);
  2. `chat.py` 的 IP 取值改为优先读 `X-Forwarded-For` 第一个值,兜底 `request.client.host`(直接裸跑 uvicorn 的场景)。
- **验收**: compose 起全栈,带伪造 `X-Forwarded-For` 头并发请求,Redis 里应出现多个不同 IP 的 `rl:guest:chat:*` key。
- **依赖**: 无。
- **实施结果**: ✅ Dockerfile 加 `--proxy-headers --forwarded-allow-ips`(compose 私网段);
  `chat.py` 新增 `_client_ip()`。**对原方案的安全修正:XFF 取"最后一个"条目而非第一个**——
  客户端可自带伪造 XFF,nginx 只追加不清洗,取第一个等于允许攻击者自选限流桶。
  6 条单测锁定取值语义(含伪造场景)。

### P0-2 fetch 工具无 SSRF 防护(安全)✅

- **位置**: `apps/server/src/ryoshi/tools/fetch.py:81`
- **问题**: `fetch_url` 可抓任意 URL,包括 `http://localhost:8000/api/keys`、`http://169.254.169.254/`(云 metadata)、内网服务。云端部署时模型可被搜索结果中的内容诱导去抓内网——keys.py 的 discover-models 已实现完整私网检查(带 DNS 解析后再校验 IP,防 DNS rebinding),直接复用。
- **方案**: 把 `apps/server/src/ryoshi/api/keys.py:233` 起的私网 IP 检查抽成 `ryoshi/netguard.py`(或 `tools/_net.py`),fetch_url 在发起请求前校验目标 IP,命中私网段即拒绝;discover-models 改为调用同一实现。
- **验收**: 单测覆盖 `localhost` / `127.0.0.1` / `10.x` / `169.254.169.254` / 指向私网 IP 的域名( rebinding 用已解析 IP 校验);正常公网 URL 不受影响。
- **依赖**: 无。
- **实施结果**: ✅ 新建 `ryoshi/netguard.py`(私网段清单在 keys.py 基础上补 0.0.0.0/8、
  CGNAT、IPv4-mapped IPv6 归一化)。fetch_url 比原方案更进一步:**resolve_safe_address
  解析后以 IP 直连**(Host/SNI 仍传域名)堵死 DNS rebinding;重定向逐跳手动跟随并重新校验
  (防公网 302 → 内网)。keys.py 删除自有实现改为复用(DNS 解析也改为异步,不再阻塞
  event loop)。26 条单测 + 真实网络冒烟(私网全拦截、example.com 正常)。

### P0-3 regenerate 后旧回答"复活"(数据一致性)✅

- **位置**: `apps/server/src/ryoshi/api/chat.py:71`(`messageId` 字段定义了但从未使用)
- **问题**: 前端重新生成/编辑消息时 `trigger='regenerate-message'` 并带上要替换的消息 id,后端没有删除被替换的旧 assistant 消息(upsert 只按新 id 生效)。用户刷新页面后,被 regenerate 掉的旧回答重新出现在历史里。
- **方案**: 在 `event_stream` 开头处理 `req.trigger == 'regenerate-message'` 且 `req.messageId` 存在时:删除该消息**及其后所有消息**(对齐前端语义——重新生成会丢弃其后全部轮次),再写入新回答。persistence 层新增 `delete_message_and_after(session, chat_id, message_id)`。
- **验收**: 对已有 4 轮消息的会话 regenerate 第 2 轮回答 → 刷新后只剩 1 轮问答 + 新回答;被替换回答不再出现。
- **依赖**: 无。
- **实施结果**: ✅ persistence 层新增 `delete_message_and_after`(用 (created_at, id) 双键
  定位"之后",同秒消息一并纳入防尾巴);chat.py 在 `build_model_messages` 之前调用
  (删除先于历史加载,被删内容不会进入模型上下文)。实施前核实了 AI SDK
  regenerate 语义:messageId 可为 assistant(重试)或 user(编辑重发)id,前端在本地
  截断消息列表。6 条单测(内存 SQLite 跑真实 persistence 代码,新增 dev 依赖 aiosqlite)。

### P0-4 点"停止"丢失已生成内容(数据一致性)✅

- **位置**: `apps/server/src/ryoshi/chat/stream.py:228`(`except Exception` 不捕获 `asyncio.CancelledError`)
- **问题**: 客户端断开(SSE 连接关闭)时生成器收到 `CancelledError`(BaseException),当前 except 接不住 → `on_assistant_message` 回调不执行 → 中断的回答完全不落库。用户点了停止、或网络闪断,刷新后当前轮消失。
- **方案**: `agent_stream_to_frames` 外层改用 `try/except (Exception, asyncio.CancelledError)/finally`:finally 里若已收集到任何 parts,组装部分消息调用 `on_assistant_message`(带 `finishReason='aborted'` 类似标记);Cancel 场景先持久化再 re-raise,让 uvicorn 正常收尾。
- **依赖**: 无。
- **实施结果**: ✅ **对原方案的关键修正**:实测断开时 Starlette 对生成器注入的是
  `GeneratorExit` 而非 CancelledError,且 async generator 被 aclose 后**禁止再 await**——
  在生成器 finally 里持久化会触发 "async generator ignored GeneratorExit"。
  改为两层结构:`agent_stream_to_frames` 新增 `stream_handle` 参数,finally 只把部分消息
  快照(dict 引用)挂到 handle 上;路由层 `event_stream` 的 finally 检查 handle,未持久化
  则以 `asyncio.create_task` fire-and-forget 落库(不挂起,两种断开路径都安全,upsert
  幂等防双写)。**超出原方案的顺带修复**:错误路径(模型抛错)现在也持久化已收集的
  部分内容(metadata 带 error 字段),用户刷新能看到"答了一半 + 报错"。
  try 块扩到第一个 yield 之前(断在 start 帧也有快照),变量初始化提到 try 外
  (finally 引用安全)。3 条新单测覆盖断开/正常/错误路径。

### P0-5 /relay 端点后端未实现(功能缺陷)✅

- **位置**: 前端 `apps/web/lib/analytics/posthog-client.ts:23`;代理链 `apps/web/vite.config.ts` + `apps/web/nginx.conf` 都把 `/relay` 转发到后端;后端 `main.py` 无此路由;README 声称"后端 server 也实现了这套"
- **问题**: US cloud PostHog 用户的分析请求打到 `/relay/*` → 404。本地开发与自部署(恰是最常见的两种场景)下前端事件全部丢失。
- **方案**: 后端加一个通配路由 `POST/GET /relay/{path:path}`,httpx 转发到 `https://us.i.posthog.com/{path}`(透传 body 与必要 header,去掉 hop-by-hop header);或者——更简单——前端 `posthog-client.ts` 改为直连 PostHog host,删除三处 relay 配置。二选一,推荐前者(保留"隐藏 PostHog 域名"的原设计意图)。
- **验收**: 配置 PostHog key 后起全栈,浏览器 Network 里 `/relay/e` 与 `/relay/i/vt/` 返回 2xx;PostHog 后台能看到事件。
- **依赖**: 无。
- **实施结果**: ✅ 按推荐方案新建 `ryoshi/api/relay.py`(GET/POST/OPTIONS 通配,
  剥 hop-by-hop header,固定目标 PostHog US——不是开放代理,无 SSRF 面),注册进
  main.py。真机验证:`/relay/e` 400(fake key 被 PostHog 拒绝=转发成功)、
  `/relay/decide` 200(query 透传)、不存在路径返回上游 404 而非本地 404。

---

## P1 — 高价值低风险

### P1-1 reasoning 思考链整条链路是死的(功能缺陷)

- **位置**: 帧模型 `chat/frames.py:49-64` 已定义 ReasoningStart/Delta/End;前端 `reasoning-section.tsx` 在等数据;DB 有 `reasoning_text` 列;但 `chat/stream.py` 的 `on_chat_model_stream` 分支只抽 `chunk.content`,丢弃 `additional_kwargs.reasoning_content`
- **问题**: DeepSeek-R1 等推理模型的思考链完全不展示、不落库。所有基础设施就位,只差事件翻译这一步。
- **方案**: `stream.py` 处理 `on_chat_model_stream` 时检查 `chunk.additional_kwargs.get("reasoning_content")`(OpenAI 兼容端点惯例)与 Anthropic 的 thinking block,产出 reasoning-start/delta/end 帧,并在 collected_parts 里追加 `{"type": "reasoning", ...}` 部件(persistence 已支持该类型)。
- **验收**: 用 deepseek-reasoner 提问,前端渲染思考过程折叠区;刷新后思考链仍在(从 DB 还原);非推理模型无任何行为变化。
- **依赖**: 无。**注意与 P1-7 联动**——模型清单放开后才有推理模型可选。

### P1-2 CORS 硬编码 localhost(部署阻塞)

- **位置**: `apps/server/src/ryoshi/main.py:62`
- **方案**: 新增配置项 `allowed_origins`(逗号分隔,默认 `http://localhost:3000,http://127.0.0.1:3000`),`.env.local.example` 同步补充说明;生产同域(nginx 反代)时留空即可不走 CORS。
- **验收**: 配置自定义域名后,跨域请求带 cookie 成功;不配置时行为与现状一致。
- **依赖**: 无。

### P1-3 质量债清零:ruff 89 错 / tsc 63 错 / 零前端测试

- **现状**:
  - ruff:41 E501(prompt 长行,加 per-file-ignores 豁免)、31 B008(FastAPI `Depends()` 惯用法误报,配置 ignore)、9 B904 + 3 F401 + 3 I001 + RUF012/RUF100(真问题,修)
  - tsc 63 错:主要是 `next/navigation`/`next/link` shim 缺类型声明(vite alias 能跑,tsc 不认识),加 `lib/next-shim/*.d.ts`;其余逐个修
  - `jsdom` 在 `dependencies`(应移到 devDependencies);vitest 配置存在但**零个测试文件**
- **方案**: 分三步——① 配置层面豁免误报(E501/B008);② 修真问题(B904/F401 等 + tsc 全绿);③ 补前端冒烟测试(至少 1 个:citation 工具函数 + smoother 行为)。
- **验收**: `ruff check src` 0 错;`tsc --noEmit` 0 错;`vitest run` 通过;`jsdom` 移入 devDependencies 后 build 仍通过。
- **依赖**: P1-4(CI)要把这些检查固化,否则还会烂回去。

### P1-4 CI 流水线(质量债)

- **现状**: 无 `.github/`。
- **方案**: 一个 workflow,PR 与 push 时跑:`ruff check` + `pytest`(server)、`tsc --noEmit` + `vitest run` + `pnpm build`(web)。Python 3.12 + Node 20 + pnpm 缓存。
- **验收**: 故意提交一个 ruff 错误,CI 红灯拦截。
- **依赖**: P1-3 先清零,CI 才能直接全绿启用(否则首日即红,形同虚设)。

### P1-5 Redis 搜索缓存(成本)

- **位置**: `config.py:44` 与 docker-compose 注释都声称 Redis 用于"搜索缓存 + 限流",实际只有限流
- **方案**: `tools/search.py` 的 `search_with_fallback` 外包一层缓存:key = `sc:{provider}:{md5(query)}:{max_results}:{depth}`,TTL 15min;命中直接返回(带 `cached: true` 标记可选);Redis 不可用时静默穿透(与限流同样的降级哲学)。注意:仅在非本地开发或始终启用均可,缓存对正确性无害(Tavily 结果本就有波动)。
- **验收**: 同一 query 连续两次提问,第二次不发出出站 HTTP(mock 断言);Redis 停掉后搜索仍正常。
- **依赖**: 无。

### P1-6 httpx client 复用(性能)

- **位置**: `tools/search.py`(4 个 provider 各自 `async with httpx.AsyncClient()`)、`tools/fetch.py:87`、`auth/__init__.py:104`
- **问题**: 每次搜索/抓取/JWKS 拉取都完整 TCP+TLS 握手,高并发下延迟与句柄开销明显。
- **方案**: 模块级共享 `httpx.AsyncClient`(或挂在 app.state,main.py lifespan 里创建/关闭);工具函数改为引用。
- **验收**: 功能回归(搜索/抓取/登录全部正常);lifespan 关闭时无 unclosed client 告警。
- **依赖**: 无。

### P1-7 BYOK 用户被静态模型清单锁死(体验)

- **位置**: `apps/server/src/ryoshi/api/models.py` 的 `_STATIC_MODELS`
- **问题**: BYOK 直配 OpenAI key 的用户只能选 `gpt-4o-mini`;配 Anthropic 只有 haiku。用户自己的 key 却用不了新模型。
- **方案**: `openai`/`anthropic`/`google` 的 BYOK 用户走与 `openai-compatible` 相同的"自定义模型 id"输入(前端 api-keys-dialog 已有该交互模式);静态清单仅作下拉建议。校验逻辑复用现有 allowed_models 分支。
- **验收**: BYOK 用户自填 `gpt-5.2`(任意 id)后,模型选择器出现且能正常对话;env 密钥用户不受影响。
- **依赖**: 无。联动 P1-1(放开后可选推理模型)、P3-7(窗口表)。

---

## P2 — 体验跃升功能

### P2-1 多模态图片输入(最大体验跃升)

- **位置**: `apps/server/src/ryoshi/api/chat.py:88`(`_extract_user_text` 把图片附件变成一行 `[附件: xxx](url)` 文本)
- **问题**: 当前是"假支持"——模型只看到一行文字,看不到图片内容,最多去 fetch 那个 S3 URL。上传按钮、预览、持久化全部就位,唯独模型收不到图。
- **方案**: 构造 LangChain 消息时,把 `file` parts(mediaType 为 `image/*`)映射为多模态 content block(`{"type": "image_url", "image_url": {"url": <S3 url>}}`,Anthropic/Gemini 同理由 LangChain 归一);文本仍走 text part。需改 `build_model_messages` 与 `_extract_user_text` 的分工(一个管展示/持久化,一个管喂模型)。PDF 附件暂以 fetch 失败处理(见 P2-4)。
- **验收**: 上传一张截图问"这张图里是什么",回答准确描述图片内容;文本-only 对话零变化;不支持多模态的模型(如 deepseek-chat)收到图片时给出友好提示而非报错。
- **依赖**: 无。工作量最大的一项(L),但价值最高。

### P2-2 LLM 生成会话标题

- **位置**: `apps/server/src/ryoshi/db/persistence.py:248`(标题 = 首条消息截断 255 字)
- **方案**: assistant 回答落库后,fire-and-forget 用小模型生成 ≤20 字标题并 `UPDATE chats`(Langfuse 已有 trace 关联惯例,沿用其异步模式);失败保留原文截断兜底。
- **验收**: 新会话一轮问答完成后,侧栏标题在数秒内变为 LLM 生成的短标题;模型不可用时标题退化为现状行为。
- **依赖**: 无。

### P2-3 Generative UI 点亮(图片网格 / 追问问题)

- **位置**: `agents/researcher.py:32-33`(prompt 里的 spec 指引被注释,"阶段 4 再并入"但未并入);前端 `spec-fence-block.tsx`、图片网格、follow-up 组件全部就绪
- **方案**: 参照原项目 morhpic 的 prompt,把 image grid 与 related questions 的输出 spec 加回 QUICK/ADAPTIVE prompt;后端无需改动(search 工具已返回 `images`)。需验证前端 spec 解析路径与 DB data-* 部件持久化(persistence 已支持 `data-` 前缀)。
- **验收**: 问"推荐几个好看的编程字体"出现图片网格;回答末尾出现可点击的追问按钮;刷新后两者从 DB 正确还原。
- **依赖**: 无;建议在 P1-5(缓存)之后做,迭代 prompt 时省搜索费。

### P2-4 PDF 抓取支持

- **位置**: `tools/fetch.py:85-109`(遇 `application/pdf` 直接抛 `不支持的内容类型`)
- **方案**: 首选 Jina Reader(`https://r.jina.ai/{url}`,免费无 key,HTTP GET 即回 Markdown 文本,十几行);备选本地 `pypdf`(无网络依赖但解析质量差)。注意 Jina 也要过 P0-2 的 SSRF 检查。
- **验收**: 直接贴一个 arxiv PDF 链接提问,能基于 PDF 内容作答;HTML 抓取路径无回归。
- **依赖**: P0-2(SSRF 检查先行)。

### P2-5 /feedback 与 /upload 限流(安全,仅云端)

- **位置**: `api/feedback.py`(无限流)、`api/upload.py`(无限流)
- **问题**: 云端开放时匿名用户可无限灌反馈(写库)、无限上传 5MB 文件进 S3(存储账单攻击)。
- **方案**: 复用 ratelimit 模块加两个 scope:`feedback`(IP,10 次/天)、`upload`(IP,50 次/天),同样仅云端生效。
- **验收**: 云端模式下第 11 条 feedback 返回 429;非云端行为不变。
- **依赖**: P0-1(IP 解析必须先修对,否则同样合桶)。

---

## P3 — 性能与打磨(按需穿插)

### P3-1 前端 chunk 拆分
`vite.config.ts` 加 `build.rollupOptions.output.manualChunks`,把 katex(字体+库)与 @tabler/icons 拆独立 chunk;2.3MB 主 chunk 首屏可减约一半。S。

### P3-2 uvicorn 多 worker
Dockerfile CMD 加 `--workers 2`(或按 CPU);tiktoken 编码是 CPU-bound,单 worker 会卡 SSE 流。注意 JWKS/PostHog 客户端均为模块级单例,多 worker 天然安全。S。

### P3-3 SSE 心跳
`stream.py` 在工具执行期间(>15s 无输出)周期发 `: keepalive\n\n` 注释行,防 nginx/中间层掐空闲连接。S。

### P3-4 模型客户端缓存
`agents/models.py` 按 `(user_id, provider, model)` lru 缓存已构造的 ChatModel(密钥变更时失效),省每条消息一次 DB 查询 + provider TLS。M。

### P3-5 print → logging
全后端统一 `logging`(uvicorn 已配好 handler),`main.py` 加请求访问日志中间件。S。

### P3-6 pre-commit
`.pre-commit-config.yaml`:ruff(server)+ prettier(web);配合 P1-4 CI 双保险。S。

### P3-7 MODEL_CONTEXT_WINDOWS 更新
`chat/context_window.py` 的表只覆盖 5 个旧模型;未知模型默认 16k 偏保守,deepseek-v4/gpt-5 等实际 128k+,长对话被过早截断。改为"未知模型默认 64k + 已知表覆盖"更稳妥。S。联动 P1-7。

### P3-8 聊天导出 / 对话内搜索
导出:后端拼 Markdown/JSON 的 `GET /api/chats/{id}/export`(纯字符串拼接,M)。搜索:PostgreSQL `pg_trgm` 扩展 + messages 全文索引(M~L)。优先级最低,用户量起来再做。

---

## 建议执行批次

```
批次 4 · 打磨 ✅ 已完成(2026-09-09)
  P3-1(chunk 拆分:主 chunk 2244KB→480KB)→ P3-2(多 worker,
  WORKERS 环境变量可调)→ P3-3(SSE 心跳 15s)→ P3-7(窗口表
  前缀匹配 + 未知默认 128k)→ P3-5(logging + 访问日志中间件)→
  P3-6(pre-commit 配置)→ P3-4(模型实例缓存 5min TTL,换 key
  指纹失效)→ P3-8(导出 API:md/json)
  P3-1 成果:manualChunks 六分组,主 chunk -79%,大依赖长期缓存

批次 1 · 安全与数据一致性冲刺 ✅ 已完成(2026-09-08)
  P0-1 → P0-2 → P0-3 → P0-4 → P0-5

批次 2 · 稳定与质量冲刺 ✅ 已完成(2026-09-08)
  P1-3(清零)→ P1-4(CI 固化)→ P1-2 → P1-6
  → P1-1 → P1-7 → P1-5
  实施备注:
  - P1-1 根因比预想深:langchain-openai 1.6.0 会丢弃流式 delta 的
    reasoning_content,需 ReasoningCapableChatOpenAI 子类在转换钩子
    里补回;帧产出与落库已就绪(6 条单测锁定)
  - P1-7 后端能力本已齐全,补的是前端"手动添加模型 id"入口
  - P1-5 修复真 bug:缓存写入 key 用 results.query(源会改写)导致
    永不命中,改为 query_override

批次 3 · 体验跃升冲刺 ✅ 已完成(2026-09-09)
  P2-1(多模态)→ P2-2(标题)→ P2-3(Generative UI)
  → P2-4(PDF)→ P2-5(限流补齐)
  实施备注:
  - P2-1 带视觉能力检测:不支持图片的模型(deepseek-chat 等)降级为
    文本说明而非 API 报错;未知名默认放行
  - P2-4 双路径:Jina Reader 在部分网络(如国内)不可达,加 pypdf
    本地解析兜底(下载也走 SSRF 校验+重定向),真机验证 arxiv 成功
  - P2-5 顺带把 IP 提取统一到 ratelimit.client_ip_from_request
    (原 chat.py 私有函数迁出共用)

批次 4 · 打磨(按需)
  P3-* 任意穿插;P3-7 建议跟在批次 2 的 P1-7 后顺手做
```

**依赖关系一览**:

- P1-4(CI)← P1-3(先清零再固化)
- P2-5(开放接口限流)← P0-1(IP 解析修对)
- P2-4(PDF/Jina)← P0-2(SSRF 检查先行)
- P1-1(推理链)⇢ P1-7(模型放开后才有推理模型可选)
- P3-7(窗口表)⇢ P1-7(同一处体验)

**只做三件事的最小方案**(若时间有限):
1. P0-1 + P0-2(安全:限流合桶 + SSRF)
2. P2-1(多模态:最大体验跃升)
3. P0-3 + P0-4(数据一致性:regenerate 清理 + 中断持久化)

---

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-09-08 | 初版,基于全项目代码审查 |
| 2026-09-08 | P0 全部完成(分支 `fix/p0-stage`):5 项修复落地,新增 41 条单测(总 57),改动文件 ruff 全绿;详见各项「实施结果」 |
| 2026-09-08 | 批次 2(P1)全部完成(分支 `feat/p1-stage`):7 项落地——质量债清零(ruff 83→0 / tsc 63→0)、CI 流水线、CORS 可配置、httpx 共享连接池、reasoning 思考链全链路打通、BYOK 手动模型 id、Redis 搜索缓存(含写入 key 错位 bug 修复)。测试 57→67;详见各项「实施结果」 |
| 2026-09-09 | 批次 3(P2)全部完成(分支 `feat/p2-stage`):多模态图片输入、LLM 会话标题、Generative UI spec、PDF 双路径抓取、feedback/upload 限流。测试 67→80 |
| 2026-09-09 | 批次 4(P3)全部完成(分支 `feat/p3-stage`):chunk 拆分(-79%)、多 worker、SSE 心跳、窗口表前缀匹配、logging+访问日志、pre-commit、模型实例缓存、导出 API。测试 80→90。**路线图全部完成** |
