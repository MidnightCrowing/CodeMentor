from app.services.llm_service import _build_classify_messages, _classify_locally


def test_build_classify_messages_includes_history():
    history = [
        {"role": "user", "content": "我在写一个 Flask 接口"},
        {"role": "assistant", "content": "先把完整报错贴出来"},
    ]

    messages = _build_classify_messages("这个 NoneType 报错怎么改？", history)

    assert messages[0]["role"] == "system"
    assert messages[1:] == [
        {"role": "user", "content": "我在写一个 Flask 接口"},
        {"role": "assistant", "content": "先把完整报错贴出来"},
        {"role": "user", "content": "这个 NoneType 报错怎么改？"},
    ]


def test_build_classify_messages_filters_invalid_history_items():
    history = [
        {"role": "system", "content": "ignore me"},
        {"role": "user", "content": ""},
        {"role": "assistant", "content": None},
        {"role": "user", "content": "上一轮我在问 SQLAlchemy session"},
    ]

    messages = _build_classify_messages("这个事务为什么没提交？", history)

    assert messages[1:] == [
        {"role": "user", "content": "上一轮我在问 SQLAlchemy session"},
        {"role": "user", "content": "这个事务为什么没提交？"},
    ]


def test_classify_locally_detects_programming_question():
    result = _classify_locally("如何用 Python 实现二分查找？")

    assert result is True


def test_classify_locally_detects_obvious_non_programming_question():
    result = _classify_locally("今天天气怎么样？")

    assert result is False


def test_classify_locally_does_not_match_short_english_terms_inside_words():
    result = _classify_locally("What is the capital of France?")

    assert result is None


def test_classify_locally_uses_programming_history_for_follow_up():
    history = [
        {"role": "user", "content": "我在写一个 FastAPI 接口，返回 500 报错"},
        {"role": "assistant", "content": "先检查 traceback 和路由依赖。"},
    ]

    result = _classify_locally("这个怎么改？", history)

    assert result is True


def test_classify_locally_allows_short_learning_replies_with_programming_history():
    history = [
        {"role": "user", "content": "解释一下 Python 字典的键和值"},
        {"role": "assistant", "content": "字典用键来查找对应的值。"},
    ]

    assert _classify_locally("键", history) is True
    assert _classify_locally("需要", history) is True


def test_classify_locally_allows_study_support_with_programming_history():
    history = [
        {"role": "user", "content": "python考试怎么办"},
        {"role": "assistant", "content": "先按基础语法、循环、函数和列表整理复习。"},
    ]

    assert _classify_locally("明天考试，还没有好好准备怎么办", history) is True
    assert _classify_locally("帮我整理笔记", history) is True


def test_classify_locally_rejects_obvious_non_programming_topics():
    assert _classify_locally("四级有啥知识点") is False
    assert _classify_locally("北京一天买多少杯咖啡") is False


def test_classify_locally_allows_python_fragment_terms():
    assert _classify_locally("pop") is True
    assert _classify_locally("ramge") is True
    assert _classify_locally("兔子繁殖问题") is True
