from app.services.llm_service import _build_classify_messages


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
