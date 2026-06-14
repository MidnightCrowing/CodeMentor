"""
LLM 服务封装。

- 统一封装 OpenAI 兼容接口调用
- 对上层返回简洁、安全的错误提示
- 详细诊断信息写入日志，便于排查
"""

from __future__ import annotations

import json
import logging
import time
from collections import OrderedDict
from collections.abc import AsyncGenerator
import hashlib
import re

from openai import APIError, APITimeoutError, AsyncOpenAI, NotFoundError

from app.core.config import settings
from app.core.prompts import (
    ANALYSIS_SYSTEM_PROMPT,
    CHAT_SYSTEM_PROMPT,
    CLASSIFY_SYSTEM_PROMPT,
    SUMMARIZE_REPORT_PROMPT,
    TITLE_SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)
ai_logger = logging.getLogger("ai")


class LLMServiceError(Exception):
    """向调用方返回的安全错误信息。"""


_client = AsyncOpenAI(
    api_key=settings.chat_api_key,
    base_url=settings.chat_base_url,
    timeout=settings.llm_timeout,
)

_classify_client = AsyncOpenAI(
    api_key=settings.classify_api_key or settings.chat_api_key,
    base_url=settings.classify_base_url,
    timeout=settings.llm_timeout,
)

_CLASSIFY_CACHE_TTL_SECONDS = 10 * 60
_CLASSIFY_CACHE_MAX_SIZE = 512
_classify_cache: OrderedDict[str, tuple[float, bool]] = OrderedDict()

_PROGRAMMING_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"```|`[^`]+`",
        r"\b[\w-]+\.(py|js|ts|tsx|jsx|java|go|rs|cs|cpp|c|h|html|css|sql|json|ya?ml|toml)\b",
        r"\b(traceback|exception|warning|segmentation fault|stack trace)\b",
        r"\b[a-zA-Z_][a-zA-Z0-9_]*(Error|Exception)\b",
        r"\b[a-zA-Z_][a-zA-Z0-9_]*\s*\([^)]*\)",
        r"\b(select|insert|update|delete|create|alter|drop)\s+.+\b(from|table|where|into)\b",
        r"\b(npm|pnpm|yarn|pip|git|docker|kubectl|uvicorn|pytest|poetry|conda)\s+[\w.-]",
    )
)

_PROGRAMMING_TERMS: dict[str, int] = {
    "python": 2,
    "java": 2,
    "javascript": 2,
    "typescript": 2,
    "c++": 2,
    "c#": 2,
    "golang": 2,
    "go语言": 2,
    "rust": 2,
    "php": 2,
    "swift": 2,
    "kotlin": 2,
    "html": 2,
    "css": 2,
    "sql": 2,
    "fastapi": 2,
    "flask": 2,
    "django": 2,
    "spring": 2,
    "react": 2,
    "vue": 2,
    "node": 2,
    "sqlalchemy": 2,
    "pydantic": 2,
    "pytest": 2,
    "asyncio": 2,
    "heapq": 2,
    "mro": 2,
    "c3": 2,
    "lru": 2,
    "semaphore": 2,
    "boundedsemaphore": 2,
    "deepcopy": 2,
    "postgres": 2,
    "postgresql": 2,
    "mysql": 2,
    "redis": 2,
    "docker": 2,
    "kubernetes": 2,
    "k8s": 2,
    "git": 2,
    "github": 2,
    "linux": 2,
    "nginx": 2,
    "api": 2,
    "http": 2,
    "websocket": 2,
    "json": 2,
    "yaml": 2,
    "leetcode": 2,
    "list": 2,
    "tuple": 2,
    "dict": 2,
    "set": 2,
    "string": 2,
    "math": 2,
    "range": 2,
    "ramge": 2,
    "pop": 2,
    "del": 2,
    "pow": 2,
    "format": 2,
    "len": 2,
    "print": 2,
    "num": 1,
    "算法": 2,
    "代码": 2,
    "编程": 2,
    "程序": 2,
    "函数": 2,
    "数据库": 2,
    "数据处理": 2,
    "前端": 2,
    "后端": 2,
    "报错": 2,
    "异常": 2,
    "编译": 2,
    "调试": 2,
    "部署": 2,
    "递归": 2,
    "爬虫": 2,
    "脚本": 2,
    "正则": 2,
    "接口": 2,
    "元组": 2,
    "列表": 2,
    "集合": 2,
    "字典": 2,
    "字符串": 2,
    "缩进": 2,
    "循环": 2,
    "偶数": 2,
    "默认参数": 2,
    "可变对象": 2,
    "优先队列": 2,
    "方法解析顺序": 2,
    "线性化": 2,
    "事件循环": 2,
    "浅拷贝": 2,
    "深拷贝": 2,
    "兔子繁殖": 2,
    "变量": 1,
    "数组": 1,
    "链表": 1,
    "队列": 1,
    "哈希": 1,
    "框架": 1,
    "模块": 1,
    "类": 1,
    "对象": 1,
    "继承": 1,
    "协程": 1,
    "线程": 1,
    "进程": 1,
    "路由": 1,
    "中间件": 1,
    "事务": 1,
    "索引": 1,
    "缓存": 1,
    "token": 1,
    "session": 1,
    "cookie": 1,
    "参数": 1,
    "返回值": 1,
    "依赖": 1,
    "版本": 1,
    "调用": 1,
    "键": 1,
}

_FOLLOW_UP_TERMS = (
    "这个",
    "上面",
    "刚才",
    "继续",
    "怎么改",
    "哪里错",
    "为什么错",
    "修一下",
    "是的",
    "需要",
    "好的",
    "可以",
    "对",
    "键",
    "？",
    "?",
    "思考",
    "慢",
    "考试",
    "怎么办",
    "整理笔记",
)
_GREETING_TERMS = ("hello", "hello world", "hi", "hey", "你好", "您好", "在吗")
_OBVIOUS_NON_PROGRAMMING_TERMS = (
    "天气",
    "星座",
    "彩票",
    "四级",
    "六级",
    "英语",
    "咖啡",
    "电影",
    "电视剧",
    "音乐",
    "歌曲",
    "旅游",
    "酒店",
    "机票",
    "菜谱",
    "做饭",
    "减肥",
    "感情",
    "恋爱",
    "讲个笑话",
    "新闻",
)


def _is_ascii_word(term: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_]+", term))


def _build_messages(system_prompt: str, user_message: str) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


def _build_classify_messages(
    message: str,
    history: list[dict] | None = None,
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": CLASSIFY_SYSTEM_PROMPT}]
    if history:
        for item in history:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": message})
    return messages


def _normalize_classify_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _term_in_text(term: str, text: str) -> bool:
    if _is_ascii_word(term):
        return re.search(rf"(?<![a-z0-9_]){re.escape(term)}(?![a-z0-9_])", text) is not None
    return term in text


def _is_greeting(text: str) -> bool:
    normalized = _normalize_classify_text(text).strip(" !?！？。.,，")
    return normalized in _GREETING_TERMS


def _programming_score(text: str) -> int:
    normalized = _normalize_classify_text(text)
    if not normalized:
        return 0
    if any(pattern.search(normalized) for pattern in _PROGRAMMING_PATTERNS):
        return 2
    return sum(weight for term, weight in _PROGRAMMING_TERMS.items() if _term_in_text(term, normalized))


def _history_text(history: list[dict] | None, limit: int = 6) -> str:
    if not history:
        return ""
    parts: list[str] = []
    for item in history[-limit:]:
        role = item.get("role")
        content = item.get("content")
        if role in {"user", "assistant"} and isinstance(content, str) and content:
            if "专门解答编程和技术问题的助教" in content:
                continue
            parts.append(content)
    return "\n".join(parts)


def _classify_locally(message: str, history: list[dict] | None = None) -> bool | None:
    """
    Return a high-confidence local classification, or None when the LLM should decide.
    """
    normalized = _normalize_classify_text(message)
    if not normalized:
        return None

    if _is_greeting(normalized):
        return True

    score = _programming_score(normalized)
    if score >= 2:
        return True

    history_score = _programming_score(_history_text(history))
    if history_score >= 2 and any(term in normalized for term in _FOLLOW_UP_TERMS):
        return True

    if score == 0 and any(term in normalized for term in _OBVIOUS_NON_PROGRAMMING_TERMS):
        return False

    return None


def _classify_cache_key(message: str, history: list[dict] | None = None) -> str:
    history_items = []
    if history:
        for item in history[-6:]:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str) and content:
                history_items.append((role, _normalize_classify_text(content)))

    payload = {
        "message": _normalize_classify_text(message),
        "history": history_items,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_classify_cache(key: str) -> bool | None:
    entry = _classify_cache.get(key)
    if not entry:
        return None

    expires_at, value = entry
    if expires_at <= time.monotonic():
        _classify_cache.pop(key, None)
        return None

    _classify_cache.move_to_end(key)
    return value


def _set_classify_cache(key: str, value: bool) -> None:
    _classify_cache[key] = (time.monotonic() + _CLASSIFY_CACHE_TTL_SECONDS, value)
    _classify_cache.move_to_end(key)
    while len(_classify_cache) > _CLASSIFY_CACHE_MAX_SIZE:
        _classify_cache.popitem(last=False)


def _log_ai_call(
    action: str,
    model: str,
    elapsed_ms: int,
    ok: bool,
    extra: dict | None = None,
) -> None:
    payload = {
        "action": action,
        "model": model,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
    }
    if extra:
        payload.update(extra)
    ai_logger.info("AI_CALL %s", payload)


def _raise_llm_service_error(
    *,
    action: str,
    model: str,
    start: float,
    error_code: str,
    user_message: str,
    exc: Exception,
) -> None:
    _log_ai_call(
        action=action,
        model=model,
        elapsed_ms=int((time.perf_counter() - start) * 1000),
        ok=False,
        extra={"error": error_code},
    )
    logger.error(
        "大模型调用失败: 操作=%s 模型=%s 错误类型=%s 详情=%s",
        action,
        model,
        error_code,
        exc,
        exc_info=True,
    )
    raise LLMServiceError(user_message) from exc


def _title_fallback(reason: str, model: str, start: float, exc: Exception) -> str:
    _log_ai_call(
        action="title",
        model=model,
        elapsed_ms=int((time.perf_counter() - start) * 1000),
        ok=False,
        extra={"error": reason},
    )
    logger.warning(
        "会话标题生成失败: 模型=%s 错误类型=%s 详情=%s",
        model,
        reason,
        exc,
        exc_info=True,
    )
    return "新会话"


async def classify(message: str, history: list[dict] | None = None) -> bool:
    start = time.perf_counter()
    cache_key = _classify_cache_key(message, history)
    cached = _get_classify_cache(cache_key)
    if cached is not None:
        _log_ai_call(
            action="classify_cache",
            model="local",
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            ok=True,
            extra={"history_messages": len(history or [])},
        )
        return cached

    local_result = _classify_locally(message, history)
    if local_result is not None:
        _set_classify_cache(cache_key, local_result)
        _log_ai_call(
            action="classify_local",
            model="local",
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            ok=True,
            extra={"history_messages": len(history or [])},
        )
        return local_result

    try:
        response = await _classify_client.chat.completions.create(
            model=settings.classify_model,
            messages=_build_classify_messages(message, history),
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        is_programming = bool(result.get("is_programming", False))
        _set_classify_cache(cache_key, is_programming)
        _log_ai_call(
            action="classify",
            model=settings.classify_model,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            ok=True,
            extra={"history_messages": len(history or [])},
        )
        return is_programming
    except APITimeoutError as exc:
        _raise_llm_service_error(
            action="classify",
            model=settings.classify_model,
            start=start,
            error_code="timeout",
            user_message="AI 服务响应超时，请稍后重试",
            exc=exc,
        )
    except NotFoundError as exc:
        _raise_llm_service_error(
            action="classify",
            model=settings.classify_model,
            start=start,
            error_code="model_not_found",
            user_message="该模型不支持或模型不存在",
            exc=exc,
        )
    except APIError as exc:
        _raise_llm_service_error(
            action="classify",
            model=settings.classify_model,
            start=start,
            error_code="provider_error",
            user_message="AI 服务暂时不可用，请稍后重试",
            exc=exc,
        )
    except json.JSONDecodeError as exc:
        _raise_llm_service_error(
            action="classify",
            model=settings.classify_model,
            start=start,
            error_code="invalid_json",
            user_message="AI 服务返回异常，请稍后重试",
            exc=exc,
        )


async def generate_session_title(message: str) -> str:
    start = time.perf_counter()
    try:
        response = await _client.chat.completions.create(
            model=settings.title_model,
            messages=_build_messages(TITLE_SYSTEM_PROMPT, message),
            temperature=0.7,
        )
        title_text = response.choices[0].message.content or "新会话"
        _log_ai_call(
            action="title",
            model=settings.title_model,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            ok=True,
        )
        return title_text.strip(' \n"\'，。')[:10] or "新会话"
    except NotFoundError as exc:
        return _title_fallback("model_not_found", settings.title_model, start, exc)
    except (APITimeoutError, APIError, Exception) as exc:
        return _title_fallback("title_failed", settings.title_model, start, exc)


async def chat_stream(
    message: str,
    history: list[dict] | None = None,
    enable_thinking: bool = True,
    model_id: str | None = None,
) -> AsyncGenerator[tuple[str, str, dict | None], None]:
    messages: list[dict] = [{"role": "system", "content": CHAT_SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": message})

    start = time.perf_counter()
    target_model = model_id if model_id else settings.chat_model
    try:
        req_kwargs = {
            "model": target_model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "extra_body": {"enable_thinking": enable_thinking}
            if enable_thinking is not None
            else {},
        }

        stream = await _client.chat.completions.create(**req_kwargs)
        usage_info: dict | None = None

        async for chunk in stream:
            if chunk.usage:
                usage_info = {
                    "model": target_model,
                    "total_tokens": chunk.usage.total_tokens,
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                }

            delta = chunk.choices[0].delta if chunk.choices else None
            if not delta:
                continue

            content = delta.content
            if enable_thinking:
                reasoning_content = getattr(delta, "reasoning_content", None)
                if not reasoning_content and hasattr(delta, "model_extra") and delta.model_extra:
                    reasoning_content = delta.model_extra.get("reasoning_content")
                if reasoning_content:
                    yield "reasoning", reasoning_content, None

            if content:
                yield "content", content, None

        _log_ai_call(
            action="chat_stream",
            model=target_model,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            ok=True,
            extra={"total_tokens": (usage_info or {}).get("total_tokens", 0)},
        )
        yield "done", "", usage_info
    except APITimeoutError as exc:
        _raise_llm_service_error(
            action="chat_stream",
            model=target_model,
            start=start,
            error_code="timeout",
            user_message="AI 服务响应超时，请稍后重试",
            exc=exc,
        )
    except NotFoundError as exc:
        _raise_llm_service_error(
            action="chat_stream",
            model=target_model,
            start=start,
            error_code="model_not_found",
            user_message="该模型不支持或模型不存在",
            exc=exc,
        )
    except APIError as exc:
        _raise_llm_service_error(
            action="chat_stream",
            model=target_model,
            start=start,
            error_code="provider_error",
            user_message="AI 服务暂时不可用，请稍后重试",
            exc=exc,
        )


async def analyze(questions_text: str) -> dict:
    start = time.perf_counter()
    try:
        response = await _client.chat.completions.create(
            model=settings.analysis_model,
            messages=_build_messages(ANALYSIS_SYSTEM_PROMPT, questions_text),
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        _log_ai_call(
            action="analyze",
            model=settings.analysis_model,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            ok=True,
            extra={"total_tokens": response.usage.total_tokens if response.usage else 0},
        )
        return {
            "analysis_text": result.get("analysis_text", ""),
            "analysis_json": result.get("analysis_json", {}),
            "model": settings.analysis_model,
            "total_tokens": response.usage.total_tokens if response.usage else 0,
        }
    except APITimeoutError as exc:
        _raise_llm_service_error(
            action="analyze",
            model=settings.analysis_model,
            start=start,
            error_code="timeout",
            user_message="AI 服务响应超时，请稍后重试",
            exc=exc,
        )
    except NotFoundError as exc:
        _raise_llm_service_error(
            action="analyze",
            model=settings.analysis_model,
            start=start,
            error_code="model_not_found",
            user_message="该模型不支持或模型不存在",
            exc=exc,
        )
    except APIError as exc:
        _raise_llm_service_error(
            action="analyze",
            model=settings.analysis_model,
            start=start,
            error_code="provider_error",
            user_message="AI 服务暂时不可用，请稍后重试",
            exc=exc,
        )
    except json.JSONDecodeError as exc:
        _raise_llm_service_error(
            action="analyze",
            model=settings.analysis_model,
            start=start,
            error_code="invalid_json",
            user_message="AI 服务返回异常，请稍后重试",
            exc=exc,
        )


async def summarize_report(daily_summaries: str) -> dict:
    start = time.perf_counter()
    try:
        response = await _client.chat.completions.create(
            model=settings.analysis_model,
            messages=_build_messages(SUMMARIZE_REPORT_PROMPT, daily_summaries),
            response_format={"type": "json_object"},
            temperature=0.5,
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        _log_ai_call(
            action="summarize_report",
            model=settings.analysis_model,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            ok=True,
            extra={"total_tokens": response.usage.total_tokens if response.usage else 0},
        )
        return result
    except APITimeoutError as exc:
        _raise_llm_service_error(
            action="summarize_report",
            model=settings.analysis_model,
            start=start,
            error_code="timeout",
            user_message="AI 服务响应超时，请稍后重试",
            exc=exc,
        )
    except NotFoundError as exc:
        _raise_llm_service_error(
            action="summarize_report",
            model=settings.analysis_model,
            start=start,
            error_code="model_not_found",
            user_message="该模型不支持或模型不存在",
            exc=exc,
        )
    except APIError as exc:
        _raise_llm_service_error(
            action="summarize_report",
            model=settings.analysis_model,
            start=start,
            error_code="provider_error",
            user_message="AI 服务暂时不可用，请稍后重试",
            exc=exc,
        )
    except json.JSONDecodeError as exc:
        _raise_llm_service_error(
            action="summarize_report",
            model=settings.analysis_model,
            start=start,
            error_code="invalid_json",
            user_message="AI 服务返回异常，请稍后重试",
            exc=exc,
        )
