"""
tests/test_chat_service.py
===========================
Chat Service 测试集。

测试内容：
- NON_PROGRAMMING_ANSWER 常量存在且非空
- _sse() 格式化函数输出符合 SSE 规范
- chat_stream_generator() 的 SSE 事件流完整性：
  - 非编程问题：直接返回固定提示并触发 done
  - 编程问题：逐块返回 content，最后返回 done

⚠️ 需要真实 API Key 才能运行 generator 相关测试。
"""

import json
import pytest

from app.services.chat_service import (
    NON_PROGRAMMING_ANSWER,
    _sse,
)


# ── 纯函数单元测试（无需 API Key）───────────────────────────
def test_non_programming_answer_not_empty():
    """固定拒答文本不能为空。"""
    assert NON_PROGRAMMING_ANSWER
    assert len(NON_PROGRAMMING_ANSWER) > 10


def test_sse_content_format():
    """SSE content 格式应符合: data: {"type": "content", "data": "xxx"}\\n\\n"""
    result = _sse("content", data="测试内容")
    assert result.startswith("data: ")
    assert result.endswith("\n\n")
    payload = json.loads(result.replace("data: ", "").strip())
    assert payload["type"] == "content"
    assert payload["data"] == "测试内容"


def test_sse_done_format():
    """SSE done 格式应符合: data: {"type": "done"}\\n\\n"""
    result = _sse("done")
    payload = json.loads(result.replace("data: ", "").strip())
    assert payload["type"] == "done"


def test_sse_error_format():
    """SSE error 格式应包含 message 字段。"""
    result = _sse("error", message="超时")
    payload = json.loads(result.replace("data: ", "").strip())
    assert payload["type"] == "error"
    assert payload["message"] == "超时"


# ── 集成测试（需要 API Key + 数据库）────────────────────────
# 若无真实环境可 skip
@pytest.mark.asyncio
@pytest.mark.skip(reason="需要真实数据库和 API Key，手动运行")
async def test_chat_stream_generator_non_programming():
    """
    非编程问题应产出固定拒答内容，且必须是 done 类型结束。
    运行前需要提供真实的数据库连接和 API Key。
    """
    from app.core.database import AsyncSessionLocal
    from app.services.chat_service import chat_stream_generator

    events: list[dict] = []
    async with AsyncSessionLocal() as db:
        async for chunk in chat_stream_generator(
            user_id="test_user",
            session_id="test_session",
            message="今天天气怎么样？",
            db=db,
        ):
            payload = json.loads(chunk.replace("data: ", "").strip())
            events.append(payload)

    assert any(e["type"] == "done" for e in events)
    # 非编程问题的 content 应包含固定拒答文本的部分内容
    content_events = [e for e in events if e["type"] == "content"]
    combined = "".join(e["data"] for e in content_events)
    assert "编程" in combined or "代码" in combined
