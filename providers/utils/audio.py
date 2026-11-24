"""音频处理工具模块。

提供音频时长获取、校验与裁剪功能，并定义各 TTS 模型/用途的预设约束常量。
依赖 pydub 库进行音频处理，若未安装则相关功能将降级或失效。
"""
import hashlib
import os

from datetime import datetime
from pathlib import Path

from typing import Any, Optional, Tuple

from astrbot.api import logger

try:
    from pydub import AudioSegment
    from pydub.utils import mediainfo
except ImportError:
    AudioSegment = None
    mediainfo = None
    logger.warning("pydub 不可用，音频时长校验与裁剪功能将失效")


def get_audio_duration(file_path: str) -> Optional[float]:
    """获取音频时长（秒）。

    优先用 ffprobe（mediainfo）；失败时用 pydub 兜底。pydub 对 WAV 使用
    标准库后端，无需 ffmpeg 即可读取时长；MP3/OGG 仍需 ffmpeg 解码。

    Args:
        file_path: 音频文件路径

    Returns:
        音频时长（秒）；两种方式都读不到时返回 None
    """
    if mediainfo is not None:
        try:
            info = mediainfo(file_path)
            duration = info.get("duration")
            if duration is not None:
                return float(duration)
        except Exception as e:
            # 有 pydub 兜底，ffprobe 失败不算最终失败，降级为 debug 避免噪声。
            logger.debug(f"ffprobe 读取时长失败，尝试 pydub 兜底: {file_path}, {e}")

    if AudioSegment is not None:
        try:
            duration_ms = len(AudioSegment.from_file(file_path))
            return duration_ms / 1000.0 if duration_ms > 0 else None
        except Exception as e:
            logger.debug(f"pydub 读取时长失败: {file_path}, {e}")
    return None


def validate_audio_duration(
    file_path: str,
    min_sec: Optional[float] = None,
    max_sec: Optional[float] = None,
) -> Tuple[bool, str]:
    """校验音频时长是否在指定范围内。

    Args:
        file_path: 音频文件路径
        min_sec: 允许的最小时长（秒），为 None 则不检查下限
        max_sec: 允许的最大时长（秒），为 None 则不检查上限

    Returns:
        元组 (是否合法, 错误提示信息)，合法时信息为空字符串
    """
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

        logger.info(
            f"音频已裁剪: {original_duration_ms/1000:.1f}s -> {target_ms/1000:.1f}s, 保存至 {new_path}"
        )
        return str(new_path)

    except Exception as e:
        raise RuntimeError(f"音频裁剪失败: {e}")


def save_audio_bytes(data_dir: str, content: bytes, fmt: str = "mp3") -> str:
    """将音频字节写入本地文件并返回路径。

    Args:
        data_dir: 音频保存目录，为空时返回空字符串。
        content: 音频二进制内容。
        fmt: 音频文件扩展名（如 "wav"、"mp3"），默认 "mp3"。

    Returns:
        保存后的音频文件路径，失败时返回空字符串。
    """
    if not data_dir:
        logger.error("未找到 _data_dir")
        return ""

    try:
        dir_path = Path(data_dir)
        dir_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filepath = dir_path / f"tts_{timestamp}.{fmt}"
        filepath.write_bytes(content)
    except Exception as e:
        logger.error(f"保存音频失败: {e}")
        return ""

    logger.debug(f"TTS 音频已保存: {filepath}")
    return str(filepath)


class Base64FileCache:
    """音频文件 → Base64 文本的磁盘缓存，供参考音频类供应商复用。

    缓存键由「源文件路径摘要 + mtime + size」构成，源文件不变即可复用；
    ``key_parts`` 让适配器把影响产物内容的业务参数（如时长上限、裁剪余量、
    大小上限）纳入键，避免参数变化后命中陈旧缓存。

    写入采用同目录临时文件 + ``os.replace`` 原子替换，进程被杀不会留下
    半截缓存被永久命中。每次写入后按 mtime 淘汰最旧条目，只保留最近
    ``max_entries`` 个，避免换文件后旧缓存无限堆积。

    Args:
        cache_dir: 缓存目录（由适配器按供应商隔离）。
        key_parts: 附加到缓存键的业务参数，值的字符串表示参与键计算。
        max_entries: 最多保留的缓存条目数，<= 0 表示不淘汰。
    """

    def __init__(
        self,
        cache_dir: Path,
        key_parts: Optional[dict[str, Any]] = None,
        max_entries: int = 20,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.key_parts = dict(key_parts or {})
        self.max_entries = max_entries

    def path_for(self, source: Path) -> Path:
        """按源文件状态与业务参数计算缓存文件路径。"""
        source = Path(source)
        stat = source.stat()
        digest = hashlib.sha1(str(source.resolve()).encode("utf-8")).hexdigest()[:12]
        parts = [digest, str(stat.st_mtime_ns), str(stat.st_size)]
        parts += [f"{k}{v}" for k, v in sorted(self.key_parts.items())]
        return self.cache_dir / f"{'_'.join(parts)}.b64"

    def load(self, source: Path) -> Optional[str]:
        """命中缓存则返回 Base64 文本（ASCII），否则返回 None。"""
        cache_file = self.path_for(source)
        if not cache_file.is_file():
            return None
        try:
            encoded = cache_file.read_text(encoding="ascii")
        except (OSError, UnicodeError) as exc:
            logger.debug(f"读取音频缓存失败，将重新编码: {cache_file.name}, {exc}")
            return None
        logger.debug(f"命中音频缓存: {cache_file.name}")
        return encoded

    def save(self, source: Path, encoded: str) -> Path:
        """原子写入 Base64 文本并执行 LRU 淘汰，返回缓存文件路径。"""
        cache_file = self.path_for(source)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_file = cache_file.with_name(f".{cache_file.name}.{os.getpid()}.tmp")
        try:
            tmp_file.write_text(encoded, encoding="ascii")
            os.replace(tmp_file, cache_file)
        finally:
            tmp_file.unlink(missing_ok=True)
        logger.debug(f"音频已编码缓存: {cache_file.name}")
        self._prune()
        return cache_file

    def _prune(self) -> None:
        """按 mtime 淘汰最旧缓存，只保留最近 max_entries 个。"""
        if self.max_entries <= 0:
            return
        try:
            files = sorted(
                self.cache_dir.glob("*.b64"),
                key=lambda p: p.stat().st_mtime_ns,
            )
            for stale in files[:-self.max_entries]:
                stale.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"清理音频缓存失败（不影响合成）: {exc}")


# ========== 各模型/用途的预设约束常量 ==========

class AudioConstraints:
    """音频时长约束常量，供各适配器复用。

    包含 MiniMax、百炼（Qwen-Audio-TTS / CosyVoice / Qwen-TTS）等
    模型的音频克隆与示例音频时长限制。
    """

    # MiniMax
    MINIMAX_CLONE_MIN = 10.0       # 主音频最短 10 秒
    MINIMAX_CLONE_MAX = 300.0      # 主音频最长 5 分钟
    MINIMAX_PROMPT_MAX = 8.0       # 示例音频最长 8 秒（不可裁剪，需报错）

    # 百炼（Qwen-Audio-TTS / CosyVoice / Qwen-TTS）
    BAILIAN_CLONE_MIN = 10.0       # 推荐 10~20 秒，强制至少 10 秒
    BAILIAN_CLONE_MAX = 60.0       # 最长不超过 60 秒

    # 百炼音频生成（qwen-audio-3.1-tts-next）
    QWEN_AUDIO_NEXT_MAX = 30.0     # 单条参考音频最长 30 秒
