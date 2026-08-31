"""流式平滑器(复刻 AI SDK 的 smoothStream)。

设计意图:
    大模型吐出的文本增量往往是一大段一大段的(尤其非流式聚合或工具整理后),
    直接转发会显得"一卡一卡"。smoothStream 把这些大块放进缓冲区,按"词"
    重新切成小份、每份间隔一个固定小延迟再发出去,制造出连贯的打字机效果。

    这里逐行复刻 ai@7.0.66 的 smoothStream({ chunking: 'word' }):
      - 切词正则  word: /\\S+\\s+/m   (一个非空白"词" + 其后的空白)
      - 每片延迟  delayInMs = 10ms

    ⚠️ 中文说明:该正则是按"空格分词"设计的,对英文天然合适;对中文,
    "词"之间没有空格,缓冲区会一直攒到遇到空白(标点后的空格、换行)才切出。
    因此纯中文长句的平滑效果弱于英文——这与原项目表现一致(原项目也是同一
    正则)。若未来要优化中文手感,可在此引入按字符/按标点的切分,但需注意
    保持与原站"英文按词"行为兼容。
"""

import asyncio
import re
from collections.abc import AsyncIterator

# 与 AI SDK CHUNKING_REGEXPS.word 一致:非空白串 + 其后空白
_WORD_PATTERN = re.compile(r"\S+\s+", re.MULTILINE)

# 与 AI SDK 默认 delayInMs 一致
DEFAULT_DELAY_MS = 10


def detect_chunk(buffer: str) -> str | None:
    """从缓冲区头部检测出一个可发送的"词片"。

    对应 AI SDK 中 detectChunk 的正则分支:返回"匹配点之前的内容 + 匹配本身",
    即缓冲区开头到第一个完整词(含尾随空白)为止。无完整词则返回 None。
    """
    if not buffer:
        return None
    match = _WORD_PATTERN.search(buffer)
    if not match:
        return None
    # 发送从开头到该词末尾的内容(对应 slice(0, match.index) + match[0])
    return buffer[: match.start()] + match.group(0)


async def smooth_text(
    deltas: AsyncIterator[str],
    delay_ms: int = DEFAULT_DELAY_MS,
) -> AsyncIterator[str]:
    """把原始文本增量流平滑为按词的小增量流。

    输入:模型/管线产生的原始文本块(可能很大)。
    输出:按词切分、每片间隔 delay_ms 的小文本块。

    用法:
        async for piece in smooth_text(raw_deltas):
            yield TextDelta(id=tid, delta=piece)
    """
    buffer = ""
    async for chunk in deltas:
        buffer += chunk
        # 循环切出缓冲区里所有完整的词
        while (piece := detect_chunk(buffer)) is not None:
            yield piece
            buffer = buffer[len(piece):]
            await asyncio.sleep(delay_ms / 1000)
    # 流结束:冲刷缓冲区里剩余的尾巴(最后一个词后可能无空白)
    if buffer:
        yield buffer
