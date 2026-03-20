"""
tests/test_analysis_service.py
================================
Analysis Service 纯逻辑单元测试。

测试内容（无需 API Key）：
- _format_questions(): 格式化输出是否包含 Q/A
- _chunk_questions(): 分块是否精确

集成测试（需要数据库）默认 skip。
"""

import pytest
from unittest.mock import MagicMock

from app.services.analysis_service import _format_questions, _chunk_questions
from app.models.models import Question


def _make_question(question: str, answer: str) -> Question:
    """快速创建一个测试用的 Question Mock 对象。"""
    q = MagicMock(spec=Question)
    q.question = question
    q.answer = answer
    return q


def test_format_questions_basic():
    """格式化后的文本应包含 Q: 和 A: 标记。"""
    questions = [
        _make_question("什么是列表？", "列表是有序集合..."),
        _make_question("和元组有何区别？", "元组不可变..."),
    ]
    result = _format_questions(questions)
    assert "Q: 什么是列表？" in result
    assert "A: 列表是有序集合..." in result
    assert "[1]" in result
    assert "[2]" in result


def test_chunk_questions_even():
    """20 条数据按 chunk_size=20 应得到 1 个 chunk。"""
    questions = [_make_question(f"Q{i}", f"A{i}") for i in range(20)]
    chunks = _chunk_questions(questions, chunk_size=20)
    assert len(chunks) == 1
    assert len(chunks[0]) == 20


def test_chunk_questions_overflow():
    """25 条数据按 chunk_size=20 应得到 2 个 chunk（20 + 5）。"""
    questions = [_make_question(f"Q{i}", f"A{i}") for i in range(25)]
    chunks = _chunk_questions(questions, chunk_size=20)
    assert len(chunks) == 2
    assert len(chunks[0]) == 20
    assert len(chunks[1]) == 5


def test_chunk_questions_empty():
    """空列表分块应返回空列表。"""
    result = _chunk_questions([], chunk_size=20)
    assert result == []
