"""
services/llm_service.py
========================
LLM 服务封装层（核心模块）。

职责：
- 封装所有对 OpenAI API 的调用，外部模块不直接操作 openai 包
- 提供三种调用模式：
  1. classify()    前置轻量分类（是否为编程问题），不走流式
  2. chat_stream() 主对话，流式生成，AsyncGenerator 形式
  3. analyze()     离线分析，不走流式，要求返回严格 JSON

设计原则：
- 所有调用必须设置 timeout（来自 settings.llm_timeout）
- 超时或网络异常统一封装为 LLMServiceError
- 与 schemas、models 层完全解耦：只接收/返回基础 Python 类型和 dict

测试入口：tests/test_llm_service.py
"""

import json
import logging
from collections.abc import AsyncGenerator

from openai import AsyncOpenAI, APITimeoutError, APIError

from app.core.config import settings

logger = logging.getLogger(__name__)


# 自定义异常
class LLMServiceError(Exception):
    """LLM 调用失败时抛出，携带可读的错误信息。"""
    pass


# 客户端单例
# 模块级单例，避免每次请求重复创建连接
_client = AsyncOpenAI(
    api_key=settings.openai_api_key,
    base_url=settings.llm_base_url,
    timeout=settings.llm_timeout,
)


# 工具函数
def _build_messages(system_prompt: str, user_message: str) -> list[dict]:
    """
    构建标准 OpenAI messages 数组。

    Args:
        system_prompt: 系统提示词
        user_message:  用户消息内容

    Returns:
        messages 列表，格式为 [{"role": ..., "content": ...}, ...]
    """
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


# 前置分类
_CLASSIFY_SYSTEM_PROMPT = """
你是一个严格的问题分类器。
判断用户的问题是否属于编程/技术类问题。

你只能以如下 JSON 格式回复，不允许有任何其他内容：
{"is_programming": true}
或
{"is_programming": false}

"编程/技术类问题"定义：
- 涉及代码、算法、数据结构、框架、工具、调试等
- NOT 编程：问天气、问历史、问日常生活等
""".strip()


async def classify(message: str) -> bool:
    """
    前置轻量分类：判断用户问题是否为编程类问题。

    使用 classify_model（轻量低成本），要求 JSON 输出。
    超时或解析失败时抛出 LLMServiceError。

    Args:
        message: 学生原始提问文本

    Returns:
        True 表示是编程问题，False 表示不是

    Raises:
        LLMServiceError: 调用失败或返回非法 JSON
    """
    try:
        response = await _client.chat.completions.create(
            model=settings.classify_model,
            messages=_build_messages(_CLASSIFY_SYSTEM_PROMPT, message),
            response_format={"type": "json_object"},
            temperature=0,  # 分类任务不需要随机性
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        return bool(result.get("is_programming", False))

    except APITimeoutError as e:
        logger.error(f"模型调用超时: {e}", exc_info=True)
        raise LLMServiceError("模型调用超时，请稍后重试")
    except (APIError, json.JSONDecodeError) as e:
        logger.error(f"模型调用失败: {e}", exc_info=True)
        raise LLMServiceError("模型调用失败：服务异常或配置错误")


# 流式对话
_CHAT_SYSTEM_PROMPT = """
你是一位专业的编程助教，专门帮助学生解答代码相关问题。
请用简洁、准确的语言回答，并在适当时给出代码示例。
只回答编程和技术相关的问题。
""".strip()


async def chat_stream(
    message: str,
    history: list[dict] | None = None,
    enable_thinking: bool = True,
    model_id: str | None = None,
) -> AsyncGenerator[tuple[str, str, dict | None], None]:
    """
    主对话：流式生成 AI 回答（支持深度思考阶段）。

    通过 AsyncGenerator 逐块 yield 内容片段。

    Args:
        message: 学生当前提问
        history: 可选的历史对话列表，格式 [{"role": "user/assistant", "content": "..."}]

    Yields:
        (chunk_type: str, chunk_data: str, usage: dict | None)
        - chunk_type 可能是 "content" 或 "reasoning" 或 "done"
        - 正常内容块："content", "文本内容", None
        - 思考内容块："reasoning", "思考内容", None
        - 结束信号："done", "", {"model": str, "total_tokens": int}

    Raises:
        LLMServiceError: 调用失败或超时
    """
    messages: list[dict] = [{"role": "system", "content": _CHAT_SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    try:
        target_model = model_id if model_id else settings.chat_model
        req_kwargs = {
            "model": target_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "extra_body": {"enable_thinking": enable_thinking} if enable_thinking is not None else {}
        }
        
        stream = await _client.chat.completions.create(**req_kwargs)

        usage_info: dict | None = None

        async for chunk in stream:
            # 末尾 chunk 携带 usage 信息
            if chunk.usage:
                usage_info = {
                    "model": target_model,
                    "total_tokens": chunk.usage.total_tokens,
                }

            delta = chunk.choices[0].delta if chunk.choices else None
            if delta:
                content = delta.content
                # 兼容不同提供商的 reasoning_content 取值
                if enable_thinking:
                    reasoning_content = getattr(delta, "reasoning_content", None)
                    if not reasoning_content and hasattr(delta, "model_extra") and delta.model_extra:
                        reasoning_content = delta.model_extra.get("reasoning_content")

                    if reasoning_content:
                        yield "reasoning", reasoning_content, None
                
                if content:
                    yield "content", content, None

        # 最后 yield 结束信号（携带 usage）
        yield "done", "", usage_info

    except APITimeoutError as e:
        logger.error(f"模型调用超时: {e}", exc_info=True)
        raise LLMServiceError("模型调用超时")
    except APIError as e:
        logger.error(f"模型调用失败: {e}", exc_info=True)
        raise LLMServiceError("模型调用失败：服务异常或配置错误")


# 离线分析（严格 JSON 输出）
_ANALYSIS_SYSTEM_PROMPT = """
你是一个学习行为分析系统。
根据提供的学生问答记录，生成结构化的学习分析结果。

你必须以如下 JSON 格式输出，不允许有任何其他内容：
{
  "analysis_text": "对学生今日学习表现的自然语言总结（2-4句）",
  "analysis_json": {
    "initiative": "high 或 medium 或 low",
    "depth": "high 或 medium 或 low",
    "topic": "今日主要讨论的编程主题（简短关键词）"
  }
}

initiative（主动性）判断标准：
- high: 问题多样、主动追问
- medium: 正常提问频率
- low: 问题极少或过于简单

depth（深度）判断标准：
- high: 涉及原理、有追问、举一反三
- medium: 正常提问
- low: 仅问表面、没有追问
""".strip()


async def analyze(questions_text: str) -> dict:
    """
    离线分析：根据问答记录生成固化结构的学习行为分析。

    输入为拼接好的问答文本（调用方负责分段压缩），
    返回包含 analysis_text 和 analysis_json 的字典。

    Args:
        questions_text: 拼接好的本段问答记录文本

    Returns:
        {
            "analysis_text": str,
            "analysis_json": {"initiative": ..., "depth": ..., "topic": ...},
            "model": str,
            "total_tokens": int,
        }

    Raises:
        LLMServiceError: 调用失败、超时或返回非法 JSON
    """
    try:
        response = await _client.chat.completions.create(
            model=settings.analysis_model,
            messages=_build_messages(_ANALYSIS_SYSTEM_PROMPT, questions_text),
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)

        return {
            "analysis_text": result.get("analysis_text", ""),
            "analysis_json": result.get("analysis_json", {}),
            "model": settings.analysis_model,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        }

    except APITimeoutError as e:
        logger.error(f"模型调用超时: {e}", exc_info=True)
        raise LLMServiceError("模型调用超时")
    except (APIError, json.JSONDecodeError) as e:
        logger.error(f"模型调用失败: {e}", exc_info=True)
        raise LLMServiceError("模型调用失败：服务异常或配置错误")


async def summarize_report(daily_summaries: str) -> str:
    """
    教师端：汇总多天的 daily_analysis_text，生成完整学习报告。

    Args:
        daily_summaries: 拼接好的多天分析文本（调用方负责限制 ≤30 天）

    Returns:
        LLM 生成的完整汇总报告文本

    Raises:
        LLMServiceError: 调用失败或超时
    """
    system = (
        "你是一名教育数据分析师，请根据以下多天的学生学习分析日志，"
        "生成一份完整、客观的学习能力评估报告。"
        "报告应包括：整体表现、进步趋势、薄弱点与建议，约 300-500 字。"
    )
    try:
        response = await _client.chat.completions.create(
            model=settings.analysis_model,
            messages=_build_messages(system, daily_summaries),
            temperature=0.5,
        )
        return response.choices[0].message.content or ""

    except APITimeoutError as e:
        logger.error(f"模型调用超时: {e}", exc_info=True)
        raise LLMServiceError("模型调用超时")
    except APIError as e:
        logger.error(f"模型调用失败: {e}", exc_info=True)
        raise LLMServiceError("模型调用失败：服务异常或配置错误")
