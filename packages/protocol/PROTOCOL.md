# Ryoshi SSE 流式协议契约

> 本文件是前后端之间**唯一不可随意更改**的对接契约。
> 前端 React 代码(Vercel AI SDK 的 `useChat`)只认这套格式;Python 后端必须逐字节对齐。
> 内容逆向自 morhpic 实际依赖的 `ai@7.0.66`(Vercel AI SDK v7)源码,非凭文档猜测。

---

## 一、传输层:SSE over HTTP

- 协议:**Server-Sent Events**,HTTP 长连接,服务端单向推送
- 每个事件一行 `data: ` 前缀 + JSON,以**空行**(`\n\n`)分隔
- 流结束发一行 `data: [DONE]`

### 响应头(逐字对齐)

```
content-type: text/event-stream
cache-control: no-cache
connection: keep-alive
x-vercel-ai-ui-message-stream: v1
x-accel-buffering: no        # 禁用 nginx 缓冲,否则流式变"攒批"
```

### 线格式

```
data: {"type":"start","messageId":"..."}\n
\n
data: {"type":"text-start","id":"..."}\n
\n
data: {"type":"text-delta","id":"...","delta":"你好"}\n
\n
...更多帧...\n
data: {"type":"finish","finishReason":"stop"}\n
\n
data: [DONE]\n
\n
```

源码依据(`ai@7.0.66` 的 `JsonToSseTransformStream`):

```js
transform(part, controller) {
  controller.enqueue(`data: ${JSON.stringify(part)}\n\n`)
},
flush(controller) {
  controller.enqueue("data: [DONE]\n\n")
}
```

---

## 二、消息帧类型(UIMessageChunk)

每帧是一个 JSON 对象,`type` 字段判别。完整联合类型如下(★ = morhpic 实际用到):

### 文本

| type | 字段 | 说明 |
|---|---|---|
| ★ `text-start` | `id` | 一个文本块开始(id 关联后续 delta) |
| ★ `text-delta` | `id`, `delta` | 文本增量(流式打字的主体) |
| ★ `text-end` | `id` | 文本块结束 |

### 推理过程(模型思考链)

| type | 字段 | 说明 |
|---|---|---|
| `reasoning-start` / `reasoning-delta` / `reasoning-end` | `id`, `delta` | 同文本三件套,但渲染为"思考过程" |

### 工具调用

| type | 字段 | 说明 |
|---|---|---|
| ★ `tool-input-start` | `toolCallId`, `toolName` | 工具调用开始 |
| `tool-input-delta` | `toolCallId`, `inputTextDelta` | 工具入参流式增量 |
| ★ `tool-input-available` | `toolCallId`, `toolName`, `input` | 工具入参就绪 |
| ★ `tool-output-available` | `toolCallId`, `output` | 工具返回结果 |
| `tool-output-error` | `toolCallId`, `errorText` | 工具执行失败 |

morhpic 的工具名:`search` / `fetch` / `askQuestion` / `todoWrite` / `todoRead`。

### 来源引用(搜索结果的引用标注)

| type | 字段 | 说明 |
|---|---|---|
| ★ `source-url` | `sourceId`, `url`, `title?` | 一个网页来源 |
| `source-document` | `sourceId`, `mediaType`, `title`, `filename?` | 一个文档来源 |

### 文件

| type | 字段 | 说明 |
|---|---|---|
| ★ `file` | `url`, `mediaType` | 用户上传的附件回显 |

### 自定义数据部件(Generative UI 的载体)

格式:`type` 为 `` `data-${NAME}` ``,带 `id?` / `data` / `transient?`。
morhpic 实际使用的 `data-*` 类型:

| type | 用途 |
|---|---|
| `data-pastedContent` | 用户粘贴的大段内容(进入模型上下文) |
| `data-quotedContext` | 用户引用的一段上文 |
| `data-noteContext` | 作为上下文的笔记 |
| `data-sourceUrl` | 用户指定的目标 URL |

> **Generative UI 的 spec 走文本通道**:AI 在回答正文里输出一个特殊代码块
> (```spec ... ```),前端流式解析渲染成组件,**不依赖专门的 data 帧**。
> 详见 `apps/web/lib/render/`(原 `lib/render/`)。

### 流控制

| type | 字段 | 说明 |
|---|---|---|
| ★ `start` | `messageId?`, `messageMetadata?` | 整条消息开始(首帧) |
| `start-step` / `finish-step` | — | 一个 agent 步的起止 |
| ★ `finish` | `finishReason?`, `messageMetadata?` | 整条消息结束 |
| `abort` | `reason?` | 中止 |
| ★ `error` | `errorText` | 流出错 |
| `message-metadata` | `messageMetadata` | 元数据更新(traceId / searchMode / modelId) |

---

## 三、一次典型问答的帧序列(Quick 模式)

```
start                  {messageId, messageMetadata:{traceId, searchMode, modelId}}
start-step
tool-input-start       {toolCallId: "call_1", toolName: "search"}
tool-input-available   {toolCallId: "call_1", toolName: "search", input: {query: "..."}}
tool-output-available  {toolCallId: "call_1", output: {results: [...], images: [...]}}
source-url             {sourceId, url, title}          # 每个搜索结果一条
source-url             ...
finish-step
start-step
text-start             {id: "t1"}
text-delta             {id: "t1", delta: "根据"}
text-delta             {id: "t1", delta: "搜索结果"}
... 按词平滑输出 ...
text-end               {id: "t1"}
finish-step
finish                 {finishReason: "stop"}
[DONE]
```

---

## 四、流式平滑(smoothStream)

原项目用 AI SDK 的 `smoothStream({ chunking: 'word' })`,把模型吐出的较大块
按"词"再切成小增量,制造流畅打字机效果。Python 后端必须复刻这一行为,
否则回答会一段段"蹦"出来而非连贯打字。实现见
`apps/server/src/ryoshi/chat/smoother.py`。

---

## 五、前端如何消费(只读参考)

前端 `useChat`(来自 `@ai-sdk/react`)内部:
1. `fetch` 发起 POST,读取 `response.body` 的字节流
2. 按 SSE 行拆帧,`JSON.parse` 每个 `data:` 载荷
3. 依据 `type` 增量更新内部的 UIMessage.parts 数组
4. React 重渲染,把 parts 渲染成文本 / 工具卡片 / 来源列表 / spec 组件

**因此后端的唯一职责:产出与上面完全一致的帧流。** 其余(模型选型、工具循环、
持久化)前端一律不关心——这正是后端能整体换成 Python 的原因。
