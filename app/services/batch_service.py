"""
services/batch_service.py
=========================
批量推理服务封装（用于离线分析任务）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI, APITimeoutError, APIError

from app.core.config import settings

logger = logging.getLogger(__name__)


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
        raise ValueError("BATCH_API_KEY 未配置")
    return AsyncOpenAI(
        api_key=settings.batch_api_key,
        base_url=settings.llm_base_url,
        timeout=settings.llm_timeout,
    )


async def upload_batch_input(file_path: Path) -> str:
    """
    上传 batch 输入文件，返回 file_id。
    """
    client = _ensure_client()
    try:
        with open(file_path, "rb") as f:
            uploaded = await client.files.create(file=f, purpose="batch")
        file_id = _get_id(uploaded)
        if not file_id:
            raise RuntimeError("上传 batch 输入文件失败：未返回 file_id")
        return file_id
    except (APITimeoutError, APIError) as e:
        logger.error(f"Batch 输入文件上传失败: {e}", exc_info=True)
        raise


async def create_batch(
    input_file_id: str,
    model: str,
    completion_window: str = "24h",
    metadata: dict | None = None,
) -> dict:
    """
    创建 batch 任务，返回 batch 对象。
    """
    client = _ensure_client()
    try:
        batch = await client.batches.create(
            input_file_id=input_file_id,
            endpoint="/v1/chat/completions",
            completion_window=completion_window,
            metadata=metadata or {},
            extra_body={"replace": {"model": model}},
        )
        return batch if isinstance(batch, dict) else batch.model_dump()
    except (APITimeoutError, APIError) as e:
        logger.error(f"Batch 创建失败: {e}", exc_info=True)
        raise


async def retrieve_batch(batch_id: str) -> dict:
    client = _ensure_client()
    try:
        batch = await client.batches.retrieve(batch_id)
        return batch if isinstance(batch, dict) else batch.model_dump()
    except (APITimeoutError, APIError) as e:
        logger.error(f"Batch 状态获取失败: {e}", exc_info=True)
        raise


async def download_file_content(file_id: str) -> bytes:
    client = _ensure_client()
    try:
        content = await client.files.content(file_id)
        if isinstance(content, bytes):
            return content
        if hasattr(content, "read"):
            return content.read()
        if hasattr(content, "content"):
            return content.content  # type: ignore[return-value]
        raise RuntimeError("无法解析文件内容")
    except (APITimeoutError, APIError) as e:
        logger.error(f"Batch 文件下载失败: {e}", exc_info=True)
        raise
