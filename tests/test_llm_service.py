"""
tests/test_llm_service.py
==========================
LLM Service 测试集。

测试内容：
- classify(): 返回 bool 类型，超时时抛出 LLMServiceError
- chat_stream(): 能正常流式 yield 内容，最后一块为 ("", usage_dict)
- analyze(): 返回必须包含 analysis_text 和 analysis_json，结构固化
- summarize_report(): 返回非空字符串

⚠️ 运行此测试需要：
1. 在 .env 中填写真实的 OPENAI_API_KEY
2. 网络可访问到 OpenAI API 或你配置的代理地址
3. pytest 和 pytest-asyncio 已安装

运行方式：
    pytest tests/test_llm_service.py -v
"""

import pytest
import pytest_asyncio  # noqa: F401

from app.services.llm_service import (
    classify,
    chat_stream,
    analyze,
    summarize_report,
    LLMServiceError,
)


@pytest.mark.asyncio
async def test_classify_programming_question():
    """正常编程问题应返回 True。"""
    result = await classify("如何用 Python 实现二分查找？")
    assert result is True


@pytest.mark.asyncio
async def test_classify_non_programming_question():
    """非编程问题应返回 False。"""
    result = await classify("今天天气怎么样？")
    assert result is False


@pytest.mark.asyncio
async def test_chat_stream_yields_content():
    """
    流式调用应能 yield 出内容块，
    且最后一块的 content 为空字符串，usage 不为 None。
    """
    chunks: list[tuple] = []
    async for content, usage in chat_stream("用 Python 写一个 Hello World 程序"):
        chunks.append((content, usage))

    assert len(chunks) > 1, "应当至少有一个内容块和一个结束块"

    # 检查结束块
    last_content, last_usage = chunks[-1]
    assert last_content == ""
    assert last_usage is not None
    assert "total_tokens" in last_usage
    assert "model" in last_usage


@pytest.mark.asyncio
async def test_analyze_returns_fixed_structure():
    """analyze() 返回必须包含固化结构的字段。"""
    questions_text = """
[1] Q: 如何理解递归？
A: 递归是函数调用自身的过程...

[2] Q: 能给个斐波那契的例子吗？
A: def fib(n): return n if n <= 1 else fib(n-1) + fib(n-2)
""".strip()

    result = await analyze(questions_text)

    assert "analysis_text" in result
    assert "analysis_json" in result
    assert isinstance(result["analysis_text"], str)
    assert len(result["analysis_text"]) > 0

    aj = result["analysis_json"]
    assert "initiative" in aj
    assert "depth" in aj
    assert aj["initiative"] in ("high", "medium", "low")
    assert aj["depth"] in ("high", "medium", "low")


@pytest.mark.asyncio
async def test_summarize_report_returns_string():
    """summarize_report() 应返回非空字符串。"""
    fake_summaries = """
【2026-03-01】该学生今日提出了 3 个关于循环的问题，主动性较高。
【2026-03-02】学生主要询问了函数的定义，提问较表面。
""".strip()

    result = await summarize_report(fake_summaries)
    assert isinstance(result, str)
    assert len(result) > 50  # 报告应有实质内容
