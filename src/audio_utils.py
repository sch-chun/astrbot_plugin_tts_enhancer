import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

try:
    from pydub import AudioSegment
    from pydub.utils import mediainfo
except ImportError:
    AudioSegment = None
    mediainfo = None
    logger.warning("pydub 不可用，音频时长校验与裁剪功能将失效")


def get_audio_duration(file_path: str) -> Optional[float]:
    """获取音频时长（秒）。"""
    if mediainfo is None:
        return None
    try:
        info = mediainfo(file_path)
        duration = info.get("duration")
        if duration is not None:
            return float(duration)
    except Exception as e:
        logger.error(f"读取音频时长失败: {file_path}, 错误: {e}")
    return None


def validate_audio_duration(
    file_path: str,
    min_sec: Optional[float] = None,
    max_sec: Optional[float] = None,
) -> Tuple[bool, str]:
    """校验音频时长是否在指定范围内。"""
    duration = get_audio_duration(file_path)
    if duration is None:
        return False, "无法获取音频时长，请确认文件为有效的音频格式（mp3/m4a/wav）"

    if min_sec is not None and duration < min_sec - 0.01:
        return False, f"音频时长 {duration:.1f}s 短于要求的最小值 {min_sec}s"
    if max_sec is not None and duration > max_sec + 0.01:
        return False, f"音频时长 {duration:.1f}s 超过允许的最大值 {max_sec}s"

    return True, ""


def trim_audio_to_max(
    file_path: str,
    max_sec: float,
    margin: float = 0.5,
    output_dir: Optional[str] = None
) -> str:
    """将音频裁剪至指定最大时长（保留开头部分），并返回新文件路径。

    Args:
        file_path: 原始音频文件路径
        max_sec: 目标最大时长（秒），实际裁剪为 max_sec - margin 以留余量
        margin: 余量（秒），默认 0.5 秒，确保严格小于限制
        output_dir: 输出目录，默认与原始文件同目录

    Returns:
        裁剪后的文件路径

    Raises:
        RuntimeError: 如果 pydub 不可用或处理失败
    """
    if AudioSegment is None:
        raise RuntimeError("pydub 未安装，无法进行音频裁剪")

    src_path = Path(file_path)
    if not src_path.exists():
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 计算裁剪目标毫秒数（留 margin 余量）
    target_ms = int((max_sec - margin) * 1000)
    if target_ms <= 0:
        raise ValueError(f"max_sec ({max_sec}) 太小，无法裁剪")

    try:
        # 加载音频
        audio = AudioSegment.from_file(str(src_path))
        original_duration_ms = len(audio)

        if original_duration_ms <= target_ms:
            # 实际上不需要裁剪（保护逻辑，但调用前应已判断）
            return str(src_path)

        # 裁剪：取前 target_ms 毫秒
        trimmed = audio[:target_ms]

        # 确定输出路径
        if output_dir:
            out_dir = Path(output_dir)
        else:
            out_dir = src_path.parent

        out_dir.mkdir(parents=True, exist_ok=True)
        # 生成文件名：原文件名_trimmed.{ext}
        stem = src_path.stem
        ext = src_path.suffix
        new_path = out_dir / f"{stem}_trimmed{ext}"

        # 导出（保持原格式）
        trimmed.export(str(new_path), format=src_path.suffix.lstrip('.'))

        logger.info(f"音频已裁剪: {original_duration_ms/1000:.1f}s -> {target_ms/1000:.1f}s, 保存至 {new_path}")
        return str(new_path)

    except Exception as e:
        raise RuntimeError(f"音频裁剪失败: {e}")


# ========== 各模型/用途的预设约束常量 ==========

class AudioConstraints:
    """音频时长约束常量，供各适配器复用"""

    # MiniMax
    MINIMAX_CLONE_MIN = 10.0       # 主音频最短 10 秒
    MINIMAX_CLONE_MAX = 300.0      # 主音频最长 5 分钟
    MINIMAX_PROMPT_MAX = 8.0       # 示例音频最长 8 秒（不可裁剪，需报错）

    # 百炼（Qwen-Audio-TTS / CosyVoice / Qwen-TTS）
    BAILIAN_CLONE_MIN = 10.0       # 推荐 10~20 秒，强制至少 10 秒
    BAILIAN_CLONE_MAX = 60.0       # 最长不超过 60 秒