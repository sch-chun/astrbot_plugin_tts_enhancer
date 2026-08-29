"""TTS 标签解析工具"""

import re


# ======== TTS 标签正则 ========

TTS_PATTERN = re.compile(r"<tts>(.*?)</tts>", re.DOTALL)
TTS_START_TAG = "<tts>"
TTS_END_TAG = "</tts>"
BOUNDARY_SEPARATORS = "$"
BOUNDARY_SEPARATOR_PATTERN = re.compile(rf"[{re.escape(BOUNDARY_SEPARATORS)}]+$")
LEADING_BOUNDARY_SEPARATOR_PATTERN = re.compile(
    rf"^[{re.escape(BOUNDARY_SEPARATORS)}]+"
)

# ========================


def _trim_boundary_separators(text: str, *, leading: bool = False) -> str:
    """移除文本中的边界分隔符。

    Args:
        text (str): 需要处理的文本。
        leading (bool, optional): 是否只移除前导边界分隔符。默认为 False，即移除尾随边界分隔符。

    Returns:
        str: 移除边界分隔符后的文本。
    """
    if leading:
        return LEADING_BOUNDARY_SEPARATOR_PATTERN.sub("", text)
    return BOUNDARY_SEPARATOR_PATTERN.sub("", text)


def _append_text_segment(segments: list[dict], text: str) -> None:
    """将文本段添加到分段列表中。

    会对文本进行去除首尾空白字符处理。如果前一个分段是 TTS 类型，
    则会去除当前文本的前导边界分隔符。随后去除尾部边界分隔符。
    如果处理后文本非空，则将其作为文本分段添加到列表中。

    Args:
        segments (list[dict]): 已有的分段列表，每个分段为包含 'type' 和 'content' 的字典。
        text (str): 待处理和添加的原始文本字符串。
    """
    stripped = text.strip()
    if not stripped:
        return
    if segments and segments[-1]["type"] == "tts":
        stripped = _trim_boundary_separators(stripped, leading=True).strip()
    stripped = _trim_boundary_separators(stripped).strip()
    if stripped:
        segments.append({"type": "text", "content": stripped})


def split_by_tts_tags(text: str) -> list[dict]:
    """将包含 <tts>...</tts> 标签的文本分割为文本段和 TTS 段的列表。

    Args:
        text (str): 待解析的原始文本。

    Returns:
        list[dict]: 分割后的片段列表，每个片段为字典，包含 'type' ('text' 或 'tts') 和 'content'。
    """
    segments = []
    cursor = 0
    text_length = len(text)

    while cursor < text_length:
        start = text.find(TTS_START_TAG, cursor)
        end = text.find(TTS_END_TAG, cursor)

        # 未找到任何标签，剩余部分作为纯文本
        if start == -1 and end == -1:
            _append_text_segment(segments, text[cursor:])
            break

        # 孤立的结束标签优先处理，将其之前的内容作为纯文本
        if end != -1 and (start == -1 or end < start):
            _append_text_segment(segments, text[cursor:end])
            cursor = end + len(TTS_END_TAG)
            continue

        # 开始标签前存在纯文本，将其追加
        if start > cursor:
            _append_text_segment(segments, text[cursor:start])
        if start == -1:
            break

        # 查找与当前开始标签配对的结束标签
        end = text.find(TTS_END_TAG, start + len(TTS_START_TAG))
        if end == -1:
            _append_text_segment(segments, text[start + len(TTS_START_TAG):])
            break

        # 提取标签内容并清理首尾边界分隔符及空白
        tts_content = text[start + len(TTS_START_TAG): end].strip()
        tts_content = _trim_boundary_separators(
            _trim_boundary_separators(tts_content, leading=True),
        ).strip()
        if tts_content:
            segments.append({"type": "tts", "content": tts_content})
        cursor = end + len(TTS_END_TAG)

    # 兜底处理：若未解析出任何片段，移除所有标签后作为纯文本
    if not segments:
        stripped = text.replace(TTS_START_TAG, "").replace(TTS_END_TAG, "").strip()
        if stripped:
            segments.append({"type": "text", "content": stripped})
    return segments
