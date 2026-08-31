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


def build_initial_messages(user_text: str) -> list[HumanMessage]:
    """构造首轮输入。Quick 模式从单条用户消息开始。"""
    return [HumanMessage(content=user_text)]
