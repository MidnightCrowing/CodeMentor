"""
聊天服务测试。

覆盖内容：
- `NON_PROGRAMMING_ANSWER` 常量非空
- `_sse()` 输出符合 SSE 规范
- `chat_stream_generator()` 的集成测试占位
"""

import json

import pytest

from app.services.chat_service import NON_PROGRAMMING_ANSWER, _sse


def test_non_programming_answer_not_empty():
    """固定拒答文案不能为空。"""
    assert NON_PROGRAMMING_ANSWER
    assert len(NON_PROGRAMMING_ANSWER) > 10


def test_sse_content_format():
    """SSE content 格式应包含 type 和 data。"""
    result = _sse("content", data="测试内容")
    assert result.startswith("data: ")
    assert result.endswith("\n\n")
    payload = json.loads(result.replace("data: ", "").strip())
    assert payload["type"] == "content"
    assert payload["data"] == "测试内容"


def test_sse_done_format():
    """SSE done 格式应包含 type=done。"""
    result = _sse("done")
    payload = json.loads(result.replace("data: ", "").strip())
    assert payload["type"] == "done"


def test_sse_error_format():
    """SSE error 格式应包含 message 字段。"""
    result = _sse("error", message="超时")
    payload = json.loads(result.replace("data: ", "").strip())
    assert payload["type"] == "error"
    assert payload["message"] == "超时"


@pytest.mark.asyncio
@pytest.mark.skip(reason="需要真实数据库和 API Key，保留为手动集成测试")
async def test_chat_stream_generator_non_programming():
    """
    非编程问题应返回固定拒答内容，并最终输出 done 事件。
    """
    from app.core.database import AsyncSessionLocal
    from app.services.chat_service import chat_stream_generator

    events: list[dict] = []
    async with AsyncSessionLocal() as db:
        async for chunk in chat_stream_generator(
            user_id="test_user",
            session_id="test_session",
            dialog_id=None,
            message="今天天气怎么样？",
            enable_thinking=False,
            model_id=None,
            db=db,
        ):
            payload = json.loads(chunk.replace("data: ", "").strip())
            events.append(payload)

    assert any(event["type"] == "done" for event in events)
    content_events = [event for event in events if event["type"] == "content"]
    combined = "".join(event["data"] for event in content_events)
    assert "编程" in combined or "代码" in combined
