"""
utils/sse_utils.py
===================
SSE（Server-Sent Events）格式化工具模块。

为各个涉及到流式数据推送的服务提供一致的拼装格式标准。
"""

import json

def format_sse(type_: str, **kwargs) -> str:
    """
    格式化单条 SSE 消息。

    规范：
    - 返回事件格式均符合前端与后端约定的特殊 JSON Event-Stream 风格。
    
    Args:
        type_:  消息类型，例如 "content" / "done" / "error" / "session_meta"
        **kwargs: 附加字段（如 data=, message=, session_id= 等）

    Returns:
        符合 SSE 协议结尾包含两次换行的字符串，如：
            data: {"type": "content", "data": "xxx"}\n\n
    """
    payload = {"type": type_, **kwargs}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
