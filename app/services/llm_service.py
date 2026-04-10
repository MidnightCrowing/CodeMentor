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
from collections.abc import AsyncGenerator

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
    base_url=settings.llm_base_url,
    timeout=settings.llm_timeout,
)

_classify_client = AsyncOpenAI(
    api_key=settings.classify_api_key or settings.chat_api_key,
    base_url=settings.llm_base_url,
    timeout=settings.llm_timeout,
)


def _build_messages(system_prompt: str, user_message: str) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


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


async def classify(message: str) -> bool:
    start = time.perf_counter()
    try:
        response = await _classify_client.chat.completions.create(
            model=settings.classify_model,
            messages=_build_messages(CLASSIFY_SYSTEM_PROMPT, message),
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = response.choices[0].message.content or "{}"
        result = json.loads(raw)
        _log_ai_call(
            action="classify",
            model=settings.classify_model,
            elapsed_ms=int((time.perf_counter() - start) * 1000),
            ok=True,
        )
        return bool(result.get("is_programming", False))
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
            user_message="AI 模型暂时不可用",
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
            user_message="AI 模型暂时不可用",
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
            user_message="AI 模型暂时不可用",
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
            user_message="AI 模型暂时不可用",
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
