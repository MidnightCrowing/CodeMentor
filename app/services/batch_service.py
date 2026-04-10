"""
批量推理服务封装，用于离线分析任务。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from openai import APIError, APITimeoutError, AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)
ai_logger = logging.getLogger("ai")


def _log_batch_call(action: str, elapsed_ms: int, ok: bool, extra: dict | None = None) -> None:
    payload = {
        "action": action,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
    }
    if extra:
        payload.update(extra)
    ai_logger.info("AI_BATCH_CALL %s", payload)


def _get_id(obj: Any) -> str | None:
    if obj is None:
        return None
    if hasattr(obj, "id"):
        return getattr(obj, "id")
    if isinstance(obj, dict):
        return obj.get("id") or obj.get("data", {}).get("id")
    return None


def _ensure_client() -> AsyncOpenAI:
    if not settings.batch_api_key:
        raise ValueError("未配置 BATCH_API_KEY")
    return AsyncOpenAI(
        api_key=settings.batch_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
    )


async def upload_batch_input(file_path: Path) -> str:
    """上传 batch 输入文件，返回 `file_id`。"""
    client = _ensure_client()
    start = time.perf_counter()
    try:
        with open(file_path, "rb") as f:
            uploaded = await client.files.create(file=f, purpose="batch")
        file_id = _get_id(uploaded)
        if not file_id:
            raise RuntimeError("上传 batch 输入文件失败：未返回 file_id")
        _log_batch_call("upload_input", int((time.perf_counter() - start) * 1000), True)
        return file_id
    except (APITimeoutError, APIError) as exc:
        _log_batch_call(
            "upload_input",
            int((time.perf_counter() - start) * 1000),
            False,
            {"error": "api"},
        )
        logger.error("Batch 输入文件上传失败: %s", exc, exc_info=True)
        raise


async def create_batch(
    input_file_id: str,
    model: str,
    completion_window: str = "24h",
    metadata: dict | None = None,
) -> dict:
    """创建 batch 任务，返回 batch 对象。"""
    client = _ensure_client()
    start = time.perf_counter()
    try:
        batch = await client.batches.create(
            input_file_id=input_file_id,
            endpoint="/v1/chat/completions",
            completion_window=completion_window,
            metadata=metadata or {},
            extra_body={"replace": {"model": model}},
        )
        _log_batch_call(
            "create_batch",
            int((time.perf_counter() - start) * 1000),
            True,
            {"model": model},
        )
        batch_id = _get_id(batch)
        logger.info("Batch 创建成功: batch_id=%s 模型=%s", batch_id, model)
        return batch if isinstance(batch, dict) else batch.model_dump()
    except (APITimeoutError, APIError) as exc:
        _log_batch_call(
            "create_batch",
            int((time.perf_counter() - start) * 1000),
            False,
            {"error": "api", "model": model},
        )
        logger.error("Batch 创建失败: 模型=%s 错误=%s", model, exc, exc_info=True)
        raise


async def retrieve_batch(batch_id: str) -> dict:
    client = _ensure_client()
    start = time.perf_counter()
    try:
        batch = await client.batches.retrieve(batch_id)
        _log_batch_call("retrieve_batch", int((time.perf_counter() - start) * 1000), True)
        return batch if isinstance(batch, dict) else batch.model_dump()
    except (APITimeoutError, APIError) as exc:
        _log_batch_call(
            "retrieve_batch",
            int((time.perf_counter() - start) * 1000),
            False,
            {"error": "api"},
        )
        logger.error("Batch 状态获取失败: batch_id=%s 错误=%s", batch_id, exc, exc_info=True)
        raise


async def download_file_content(file_id: str) -> bytes:
    client = _ensure_client()
    start = time.perf_counter()
    try:
        content = await client.files.content(file_id)
        if isinstance(content, bytes):
            _log_batch_call("download_file", int((time.perf_counter() - start) * 1000), True)
            return content
        if hasattr(content, "read"):
            _log_batch_call("download_file", int((time.perf_counter() - start) * 1000), True)
            return content.read()
        if hasattr(content, "content"):
            _log_batch_call("download_file", int((time.perf_counter() - start) * 1000), True)
            return content.content  # type: ignore[return-value]
        raise RuntimeError("无法解析下载文件内容")
    except (APITimeoutError, APIError) as exc:
        _log_batch_call(
            "download_file",
            int((time.perf_counter() - start) * 1000),
            False,
            {"error": "api"},
        )
        logger.error("Batch 文件下载失败: file_id=%s 错误=%s", file_id, exc, exc_info=True)
        raise
