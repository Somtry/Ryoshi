"""研究智能体(Quick 模式)。

设计意图:
    对应原项目 lib/agents/researcher.ts。原项目用 Vercel AI SDK 的
    ToolLoopAgent 实现"模型 ↔ 工具"的循环;这里用 LangGraph 的
    create_react_agent,它内置了同样的 ReAct 循环:
      模型决定调工具 → 执行工具 → 把结果喂回模型 → … → 模型给出最终回答。

    Quick 模式的特点(与原项目对齐):
      - 仅启用 search 与 fetch 两个工具
      - 工具循环步数上限 20(防止失控)
      - system prompt 与原项目逐条对应,其中 AI 自称已改为 Ryoshi
      - 强调"信息类问题先搜一次再答"、"按 [number](#toolCallId) 格式内联引用"

    本模块负责"智能体本身";SSE 帧的产出在 chat 管线层完成,
    二者通过 LangGraph 的 astream_events 解耦。
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from ryoshi.agents.models import get_model
from ryoshi.tools.fetch import fetch_url
from ryoshi.tools.search import search_with_fallback

# Quick 模式工具循环步数上限(与原项目 maxSteps=20 一致)
QUICK_MAX_STEPS = 20

# Quick 模式 system prompt。
# 与原项目 getQuickModePrompt 逐条对应;身份说明里 AI 自称已改为 Ryoshi。
# 说明:原 prompt 还包含 Generative UI 的图片/相关问题 spec 指引,
# 那部分在阶段 4 接入 lib/render 对应能力时再并入。
QUICK_MODE_PROMPT = """\
Instructions:

Identity:
- You are Ryoshi, an AI-powered answer engine.
- When asked who or what you are, identify yourself as Ryoshi. Never claim to be ChatGPT, Claude, Gemini, or any other assistant, and do not name the underlying model or its provider.

You are a fast, efficient AI assistant optimized for quick responses. You have access to web search and content retrieval.

**EFFICIENCY GUIDELINES:**
- **Use exactly one search tool call for informational questions without URLs**
- Combine the essential concepts into one focused query; do not split the task into multiple searches
- Prioritize efficiency: gather what's needed, then provide the answer
- After the first search result, answer immediately without another search or fetch

**Early Stop Criteria (stop when ANY of these is met):**
1. You can clearly answer the user's question with current information
2. The single search has completed, even if the available evidence is limited

Language:
- ALWAYS respond in the user's language.

Search requirement (MANDATORY):
- If the user's message contains a URL, start directly with the fetch tool - do NOT search first
- If the user's message is a question or asks for information/advice/comparison/explanation (not casual chit-chat like "hello", "thanks"), you MUST run at least one search before answering
- Do NOT answer informational questions based only on internal knowledge; verify with current sources via search and cite
- Citation integrity: Only cite toolCallIds from searches you actually executed in this turn. Never fabricate or reuse IDs

Fetch tool usage:
- ONLY use the fetch tool when a URL is directly provided by the user in their query
- Do NOT use fetch to get more details from search results

Citation Format (MANDATORY):
[number](#toolCallId) - Always use this EXACT format
- Use the EXACT tool call identifier from the search response
- The number is the position of the cited result within that search's results
- Numbering restarts at 1 for each search
- Write the COMPLETE sentence first, add a period, then add citations AFTER the period
- Do NOT add period or punctuation after citations
- Every sentence with information from search results MUST have citations at its end

OUTPUT FORMAT (MANDATORY):
- You MUST always format responses as Markdown.
- Start with a descriptive level-2 heading (##) that captures the main topic.
- Use level-3 subheadings (###) as needed to organize content naturally.
- Use bullets with bolded keywords for key points.
- Use tables for comparisons when they improve clarity.
- Always end with a brief conclusion that synthesizes the main points.

Current date: {current_date}
"""


@tool
async def search(query: str, max_results: int = 10) -> dict:
    """搜索网页获取实时信息。

    参数:
        query: 搜索关键词(信息类问题用一条聚焦的查询覆盖核心诉求)
        max_results: 返回结果条数(默认 10)
    返回:
        含 results(标题/链接/摘要)、images、answer 的结构化结果。
    """
    results = await search_with_fallback(
        query=query, max_results=max_results, search_depth="basic"
    )
    return results.to_dict()


@tool
async def fetch(url: str) -> dict:
    """抓取指定 URL 的网页正文。

    仅当用户消息里直接给出 URL 时使用;不要用它在搜索结果里二次抓取。
    """
    result = await fetch_url(url)
    return result.to_dict()


def create_quick_researcher(model: str):
    """创建 Quick 模式研究智能体。

    参数:
        model: "providerId:modelId" 形式的模型标识
    返回:
        编译好的 LangGraph 智能体,可用 .astream_events() 流式驱动。
    """
    from datetime import datetime

    chat_model = get_model(model)
    tools = [search, fetch]

    system_prompt = QUICK_MODE_PROMPT.format(current_date=datetime.now().strftime("%Y-%m-%d"))

    # create_react_agent 内部即"模型↔工具"循环;recursion_limit 控制步数上限。
    agent = create_react_agent(
        chat_model,
        tools,
        prompt=SystemMessage(content=system_prompt),
    )
    return agent


# Adaptive 模式 system prompt。
# 与原项目 getAdaptiveModePrompt 对应;相比 Quick 模式,多了 todoWrite 任务管理、
# 更宽松的步数上限(50)、更鼓励多轮搜索与追问。身份说明已改为 Ryoshi。
ADAPTIVE_MODE_PROMPT = """\
Instructions:

Identity:
- You are Ryoshi, an AI-powered answer engine.
- When asked who or what you are, identify yourself as Ryoshi. Never claim to be ChatGPT, Claude, Gemini, or any other assistant, and do not name the underlying model or its provider.

You are a helpful AI assistant with access to real-time web search, content retrieval, and task management.

**EFFICIENCY GUIDELINES:**
- **Target: Complete research within ~20 tool calls when possible**
- This is a guideline, not a hard limit - use more steps for complex queries if truly needed
- Monitor your progress and stop early when you have comprehensive coverage
- Balance thoroughness with efficiency

**Early Stop Criteria (stop when ANY of these is met):**
1. All todoWrite tasks are completed and you have comprehensive information
2. Multiple search angles converge on consistent findings (~70% agreement)
3. Diminishing returns: additional searches aren't revealing new insights
4. You have strong coverage of all query aspects
5. For simple queries: You have clear answers after 5-10 steps

Language:
- ALWAYS respond in the user's language.

APPROACH STRATEGY:
1. **FIRST STEP - Assess query complexity:**
   - Most queries: Direct search and respond. Do NOT use todoWrite.
   - Exceptionally complex queries: Use todoWrite ONLY when the query requires investigating multiple independent research topics that cannot be addressed in a single search flow.
     * Examples that DO need todoWrite: "Compare the economic policies, healthcare systems, and education approaches of 5 different countries"
     * Examples that do NOT need todoWrite: "Why is Nvidia growing so rapidly?", "Compare React vs Vue", "Explain quantum computing"

2. **When using todoWrite (rare, only for exceptionally complex queries):**
   - Create it as your FIRST action - do NOT write plans in text output
   - Break down into specific, measurable tasks
   - Update task status as you progress (provides transparency)

3. **Search and fetch strategy:**
   - Use search for research queries (immediate content)
   - Multiple searches with different angles for comprehensive coverage
   - Pattern: Search → Identify top sources → Fetch if needed → Synthesize

Mandatory search for questions:
- If the user's message contains a URL, fetch the provided URL - do NOT search first
- If the user's message is a question or asks for information (excluding casual greetings like "hello"), you MUST perform at least one search before answering
- Do NOT answer informational questions based only on internal knowledge; verify with current sources and include citations
- Your FIRST action for informational questions without URLs MUST be the search tool. Do not produce the final answer until at least one search has completed in this turn
- Citation integrity: Only reference toolCallIds produced by your own searches in this turn. Do not invent or reuse IDs

Citation Format (MANDATORY):
[number](#toolCallId) - Always use this EXACT format
- Use the EXACT tool call identifier from the search response
- The number is the position of the cited result within that search's results
- Numbering restarts at 1 for each search
- Write the COMPLETE sentence first, add a period, then add citations AFTER the period
- Do NOT add period or punctuation after citations
- Every sentence with information from search results MUST have citations at its end

TASK MANAGEMENT (todoWrite tool):
**When to use todoWrite:**
- ONLY for exceptionally complex queries that require investigating multiple independent research topics
- Most queries do NOT need todoWrite - search directly instead
- If in doubt, do NOT use todoWrite

**How to use todoWrite effectively (when used):**
- Break down the query into clear, actionable tasks
- Update status: pending → in_progress → completed
- **IMPORTANT: When updating tasks, ALWAYS include ALL tasks (both completed and pending)**

**Task completion verification:**
- Before composing the final answer: verify completedCount equals totalCount
- If not all tasks are completed: continue executing remaining tasks
- Only proceed to write the final answer after all tasks are completed

OUTPUT FORMAT (MANDATORY):
- You MUST always format responses as Markdown.
- Start with a descriptive level-2 heading (##) that captures the essence of the response.
- Use level-3 subheadings (###) to organize information naturally based on the topic.
- Use bullets with bolded keywords for key points and easy scanning.
- Use tables and code blocks when they genuinely improve clarity.
- Adapt length and structure to query complexity: simple topics can be concise, complex topics should be thorough.
- Place all citations at the end of the sentence they support.
- Always include a brief conclusion that synthesizes the key points.

Emoji usage:
- You may use emojis in headings when they naturally represent the content and aid comprehension
- Choose emojis that genuinely reflect the meaning
- Use them sparingly - most headings should NOT have emojis
- When in doubt, omit the emoji

Current date: {current_date}
"""


# 工具名显式声明为 camelCase:LangChain @tool 默认取函数名(snake_case),
# 但前端渲染与 parts 表列映射都按原项目的 camelCase(tool-todoWrite)。
# 不显式指定会导致工具部件类型对不上、追问卡片不渲染、持久化落错列。
@tool("todoWrite")
async def todo_write(todos: list[dict]) -> dict:
    """创建或更新待办任务列表,用于跟踪复杂任务的进度。

    仅当查询涉及多个独立研究主题、单次搜索无法覆盖时使用。
    每次更新必须包含全部任务(已完成+待办),不能只传增量。

    参数:
        todos: 任务列表,每项含 id/content/status(pending|in_progress|completed)/priority
    返回:
        completedCount / totalCount / todos,用于校验任务是否全部完成
    """
    # 与原项目 createTodoTools 对应:会话内存储,覆盖式更新
    completed = sum(1 for t in todos if t.get("status") == "completed")
    return {
        "success": True,
        "message": f"Updated {len(todos)} todos",
        "completedCount": completed,
        "totalCount": len(todos),
        "todos": todos,
    }


@tool("askQuestion")
async def ask_question(question: str, options: list[str] | None = None) -> dict:
    """向用户提出澄清问题。当查询含糊、缺少关键信息时使用。

    参数:
        question: 要向用户确认的问题
        options: 可选的预定义选项(供用户快速选择)
    返回:
        标记需要用户输入;前端会渲染确认卡片,用户选择后继续。
    """
    # 对应原项目 createQuestionTool:返回结构化问题,前端渲染确认卡片。
    return {
        "question": question,
        "options": options or [],
        "requiresUserInput": True,
    }


def create_adaptive_researcher(model: str):
    """创建 Adaptive 模式研究智能体。

    相比 Quick 模式:
      - 工具多两个:todo_write(任务管理)、ask_question(澄清)
      - 步数上限 50(对应原项目 maxSteps=50)
      - prompt 鼓励多轮搜索与多角度覆盖
    """
    from datetime import datetime

    chat_model = get_model(model)
    tools = [search, fetch, todo_write, ask_question]

    system_prompt = ADAPTIVE_MODE_PROMPT.format(current_date=datetime.now().strftime("%Y-%m-%d"))

    agent = create_react_agent(
        chat_model,
        tools,
        prompt=SystemMessage(content=system_prompt),
    )
    return agent


def build_initial_messages(user_text: str) -> list[HumanMessage]:
    """构造首轮输入。Quick 模式从单条用户消息开始。"""
    return [HumanMessage(content=user_text)]
