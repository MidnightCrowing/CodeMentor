"""
utils/text_utils.py
===================
文本处理工具模块。

提供文本清洗、过滤等辅助函数，例如在流式交互后去除非必要的模型内部思考过程标签。
"""

import re

def remove_think_tags(text: str) -> str:
    """
    移除文本中的 <think>...</think> 和 <thinking>...</thinking> 标签及其内容。
    忽略大小写，并支持跨行匹配。

    Args:
        text (str): 待处理的原始文本。

    Returns:
        str: 移除思考标签后的文本。
    """
    if not text:
        return text

    # 使用 re.DOTALL (re.S) 使 . 能够匹配包括换行符在内的所有字符
    # 使用 re.IGNORECASE (re.I) 忽略大小写
    pattern = re.compile(
        r'<(think|thinking)>.*?</\1>',
        re.DOTALL | re.IGNORECASE
    )
    
    # 替换匹配到的内容为空字符串
    cleaned_text = pattern.sub('', text)
    # 顺便去除多余的首尾空白字符
    return cleaned_text.strip()
