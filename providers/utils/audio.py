"""音频处理工具模块。

提供音频时长获取、校验与裁剪功能，并定义各 TTS 模型/用途的预设约束常量。
依赖 pydub 库进行音频处理，若未安装则相关功能将降级或失效。
"""
import base64
import binascii
import hashlib
import os
import threading
import uuid

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

    缓存键由「源文件路径摘要 + mtime + size + 键版本」构成，源文件不变即可复用；
    ``key_parts`` 让适配器把影响产物内容的业务参数（如时长上限、裁剪余量、
    大小上限）纳入键，避免参数变化后命中陈旧缓存。由于产物完全由「源文件状态
    + 业务参数」决定，键里**不再**需要 trim / raw 之类的冗余标记。

    写入采用同目录临时文件 + ``os.replace`` 原子替换，进程被杀不会留下半截
    缓存被永久命中；读取时做轻量完整性校验（严格 Base64 解码），坏文件直接
    删除并重新编码。每次写入后按 mtime 淘汰最旧条目（只保留最近 ``max_entries``
    个），并顺手清理旧键格式文件，避免换文件后旧缓存无限堆积。

    临时文件名带 pid + 线程 id + 随机后缀：同一进程内多个线程并发写同一个
    缓存键（如两条消息同时预热同一份参考音频）时不会互相覆盖临时文件，
    也就不会把半截内容 ``os.replace`` 成正式缓存。

    安全边界：只操作 ``cache_dir`` 这一层目录下的 ``*.b64`` 文件，绝不递归、
    绝不触碰用户上传目录，因此不会误删用户文件。

    Args:
        cache_dir: 缓存目录（由适配器按供应商隔离）。
        key_parts: 附加到缓存键的业务参数，值的字符串表示参与键计算。
        max_entries: 最多保留的缓存条目数，<= 0 表示不按数量淘汰。
    """

    # 缓存键版本：键中固定带上该标记，非本版本的遗留文件在 ``_prune`` 中清理。
    KEY_VERSION = "v2"

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
        parts = [digest, str(stat.st_mtime_ns), str(stat.st_size), self.KEY_VERSION]
        parts += [f"{k}{v}" for k, v in sorted(self.key_parts.items())]
        return self.cache_dir / f"{'_'.join(parts)}.b64"

    def load(self, source: Path) -> Optional[str]:
        """命中且内容完整时返回 Base64 文本（ASCII），否则返回 None。

        坏文件（非 ASCII / 非严格 Base64 / 空文件）会被删除，调用方随后重新
        编码并回写，不会把半截内容当成有效缓存使用。
        """
        try:
            cache_file = self.path_for(source)
        except OSError as exc:
            # 源文件在解析后被删除/不可读：按未命中处理，交给调用方重新编码。
            logger.debug(f"源文件不可用，缓存未命中: {source}, {exc}")
            return None
        if not cache_file.is_file():
            return None
        try:
            encoded = cache_file.read_text(encoding="ascii")
        except (OSError, UnicodeError) as exc:
            logger.debug(f"读取音频缓存失败，将重新编码: {cache_file.name}, {exc}")
            self._discard(cache_file)
            return None
        text = encoded.strip()
        if not self._is_complete(text):
            logger.warning(f"音频缓存内容不完整，已删除并重新编码: {cache_file.name}")
            self._discard(cache_file)
            return None
        logger.debug(f"命中音频缓存: {cache_file.name}")
        return text

    @staticmethod
    def _is_complete(text: str) -> bool:
        """轻量完整性校验：非空、长度为 4 的倍数且能按严格 Base64 解码。"""
        if not text or len(text) % 4 != 0:
            return False
        try:
            base64.b64decode(text, validate=True)
        except (binascii.Error, ValueError):
            return False
        return True

    def save(self, source: Path, encoded: str) -> Path:
        """原子写入 Base64 文本并执行淘汰，返回缓存文件路径。

        写入失败（磁盘满 / 权限不足）只告警不抛异常：缓存是优化项，
        不应因此丢掉已经准备好的参考音频。
        """
        cache_file = self.path_for(source)
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            # 临时文件名唯一化（pid + 线程 id + 随机后缀）：同进程内并发写同一
            # 缓存键时不会互相覆盖，避免把半截内容发布成正式缓存。
            tmp_file = cache_file.with_name(
                f".{cache_file.name}.{os.getpid()}.{threading.get_ident()}"
                f".{uuid.uuid4().hex[:8]}.tmp"
            )
            try:
                tmp_file.write_text(encoded, encoding="ascii")
                os.replace(tmp_file, cache_file)
            finally:
                tmp_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning(f"写入音频缓存失败（不影响合成）: {cache_file.name}, {exc}")
            return cache_file
        logger.debug(f"音频已编码缓存: {cache_file.name}")
        self._prune()
        return cache_file

    def _discard(self, cache_file: Path) -> None:
        """删除损坏缓存（仅在确认是本缓存目录内的 .b64 文件时才动手）。"""
        if cache_file.parent != self.cache_dir or cache_file.suffix != ".b64":
            return
        try:
            cache_file.unlink(missing_ok=True)
        except OSError as exc:
            logger.debug(f"删除损坏的音频缓存失败: {cache_file.name}, {exc}")

    def _is_legacy(self, cache_file: Path) -> bool:
        """判断是否旧键格式文件（键中缺少当前 ``KEY_VERSION`` 段）。

        旧格式为 ``{digest}_{mtime}_{size}.b64``（MiMo）与
        ``{digest}_{mtime}_{size}_{trim|raw}.b64``（百炼音频生成）；两者都没有
        版本段。段数少于 3 的文件不像本缓存的键，保守起见不碰。
        """
        stem = cache_file.name
        if stem.endswith(".b64"):
            stem = stem[: -len(".b64")]
        parts = stem.split("_")
        if len(parts) < 3:
            return False
        if len(parts) == 3:
            return True
        return parts[3] != self.KEY_VERSION

    def _prune(self) -> None:
        """清理旧键格式缓存，并按 mtime 淘汰最旧条目（只保留最近 N 条）。"""
        if not self.cache_dir.is_dir():
            return
        try:
            files = [path for path in self.cache_dir.glob("*.b64") if path.is_file()]
            legacy = [path for path in files if self._is_legacy(path)]
            current = sorted(
                (path for path in files if not self._is_legacy(path)),
                key=lambda path: path.stat().st_mtime_ns,
            )
            stale = list(legacy)
            if self.max_entries > 0 and len(current) > self.max_entries:
                stale.extend(current[: -self.max_entries])
            for path in stale:
                path.unlink(missing_ok=True)
            if stale:
                logger.debug(f"清理 {len(stale)} 个过期音频缓存")
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
