"""合成记录存储模块。

负责把每一次 TTS 合成结果落盘，并保存元数据（来源、供应商、时间、文本等），
供前端「合成记录」管理页查看、播放与删除。所有写入均经 asyncio.Lock 串行化，
避免并发合成时元数据互相覆盖；删除 / 取音频时复用安全文件名白名单，
防止路径穿越。

存储分层（遵循 AstrBot 规范：小元数据走官方 KV，大文件落 plugin_data）：
- **元数据**（记录列表：来源 / 供应商 / 时间 / 文本 / 格式 / 时长 / 体积 /
  params / config / file）存放于 AstrBot 官方 KV（单 key ``synthesis_index``，
  按插件命名空间自动隔离），由 ``kv``（插件的 ``put_kv_data`` / ``get_kv_data``）
  承载。
- **音频二进制**仍是体积较大的文件，落盘到 ``records_dir``（plugin_data 下），
  KV 不适合塞 MB 级音频，故不进 KV。
"""

import asyncio
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from astrbot.api import logger

# 合成来源（source）常量与中文标签
SOURCE_CHAT = "chat"  # 聊天语音（发给某个 UMO / Agent 发送）
SOURCE_PREVIEW = "preview"  # 音色预览（/voice/preview）
SOURCE_DESIGN_PREVIEW = "design_preview"  # 设计试听（声音设计创建时的试听音频）
SOURCE_AGENT = "agent"  # Agent 主动发送语音（send_voice_to_user）

SOURCE_LABELS: dict[str, str] = {
    SOURCE_CHAT: "聊天语音",
    SOURCE_PREVIEW: "音色预览",
    SOURCE_DESIGN_PREVIEW: "设计试听",
    SOURCE_AGENT: "Agent 发送",
}

# 元数据存放在官方 KV 的 key；整份记录列表作为该 key 的值（KV 不支持列举，
# 故用单 key 存全量列表，list / 淘汰 / 删除均在内存中改完回写）。
KV_INDEX_KEY = "synthesis_index"

# 允许落盘且出现在文件名中的音频扩展名白名单
_ALLOWED_AUDIO_EXT = {
    "mp3",
    "wav",
    "m4a",
    "aac",
    "ogg",
    "flac",
    "webm",
    "opus",
    "pcm",
    "mp4",
}

# 记录 id 与安全文件名共用同一白名单（首字符非点，禁止 "." / ".." / 路径分隔符）
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$")

# 单次经 record 接口提交的音频体积上限（25 MiB），防止滥用
_MAX_RECORD_BYTES = 25 * 1024 * 1024


def _normalize_ext(fmt: str) -> str:
    """把任意 format 字符串规整为白名单内的扩展名。

    Args:
        fmt: 原始扩展名或 MIME 子类型，可为空。

    Returns:
        白名单内的小写扩展名；不在白名单时回退为 "mp3"。
    """
    ext = (fmt or "").strip().lstrip(".").lower()
    return ext if ext in _ALLOWED_AUDIO_EXT else "mp3"


def build_config_snapshot(entry: dict) -> dict:
    """从供应商配置抽取非敏感的配置快照，供合成记录展示。

    仅保留音色 / 格式 / 采样率 / 模型等渲染用字段，**绝不**包含 api_key、
    workspace_id 等密钥。这里忠实地记录配置原值，**不做任何供应商特有的解析**
    （例如百炼从音色 ID 反推模型后缀的逻辑属于该供应商适配器，不应耦合进通用层），
    以便记录也能暴露配置问题（如 model 填错、格式与供应商不匹配等）。

    Args:
        entry: 供应商配置字典。

    Returns:
        配置快照 dict；无任何可记录字段时返回空 dict。
    """
    snapshot: dict = {}
    voice = entry.get("voice") or ""
    if voice:
        snapshot["voice"] = voice
    fmt = entry.get("format")
    if fmt:
        snapshot["format"] = fmt
    sample_rate = entry.get("sample_rate")
    if sample_rate is not None:
        snapshot["sample_rate"] = sample_rate
    model = entry.get("model")
    if model:
        snapshot["model"] = model
    return snapshot


class SynthesisRecordStore:
    """合成记录存储。

    每条记录由一份音频文件 + 一条 KV 元数据组成。音频文件以
    ``rec_<毫秒时间戳>_<随机>.<ext>`` 命名；元数据（整份记录列表）存放于官方 KV
    的 ``synthesis_index`` key 下。支持按最多保留份数自动淘汰最旧记录。
    """

    def __init__(
        self,
        records_dir: Path,
        kv,
        max_records: int = 50,
    ) -> None:
        """初始化存储。

        Args:
            records_dir: 音频文件存放根目录（元数据在 KV，不在本目录）。
            kv: AstrBot 官方 KV 适配对象，需提供 ``async get_kv_data(key, default)``
                与 ``async put_kv_data(key, value)``（插件 Star 实例即满足）。
            max_records: 最多保留份数，语义如下：
                ``0`` 或负数表示关闭落盘（不记录新合成，但既有记录仍可查看 / 删除）；
                正整数表示仅保留最近 N 份，超出后自动删除最旧的。
                不支持「不限制」，以避免无上限地占满磁盘。
        """
        self.records_dir = Path(records_dir)
        self.kv = kv
        self.max_records = max_records
        self._lock = asyncio.Lock()
        self.records_dir.mkdir(parents=True, exist_ok=True)

    # —————— 配置热更新（AstrBot 重载插件时重建实例，这里主要给测试用） ——————

    def set_max_records(self, value: int) -> None:
        """更新最多保留份数（0 或负数关闭落盘 / 正整数保留最近 N 份）。

        负数会被钳为 0（关闭落盘），本存储层不支持「不限制」。
        """
        self.max_records = value if value > 0 else 0

    # —————— 元数据读写（走官方 KV，单 key 存全量列表） ——————

    async def _read_index(self) -> list[dict]:
        """从 KV 读取记录列表；缺失 / 非列表时返回空列表。"""
        data = await self.kv.get_kv_data(KV_INDEX_KEY, [])
        return data if isinstance(data, list) else []

    async def _write_index(self, records: list[dict]) -> None:
        """把记录列表整体写回 KV。"""
        await self.kv.put_kv_data(KV_INDEX_KEY, records)

    def _delete_file(self, filename: str | None) -> None:
        """按文件名删除音频文件；文件名非法时直接跳过（防御路径穿越）。"""
        if not filename:
            return
        if not _SAFE_ID_RE.match(filename):
            return
        try:
            (self.records_dir / filename).unlink(missing_ok=True)
        except OSError:
            pass

    # —————— 公开接口（各自加锁，互不嵌套调用） ——————

    async def add(
        self,
        *,
        audio_bytes: bytes,
        source: str,
        provider: str,
        text: str,
        fmt: str,
        source_detail: str = "",
        duration: float | None = None,
        params: dict | None = None,
        config: dict | None = None,
    ) -> dict | None:
        """写入一条合成记录（落盘音频 + 写入 KV 元数据），并执行保留份数淘汰。

        Args:
            audio_bytes: 音频二进制内容。
            source: 合成来源（见本模块 SOURCE_* 常量）。
            provider: 供应商显示名。
            text: 合成文本。
            fmt: 音频格式（扩展名或 MIME 子类型）。
            source_detail: 来源补充信息（如 UMO 标识）。
            duration: 音频时长（秒），可为 None。
            params: AI 增强参数（指令 / 音量 / 语速 / 音调 / 语言提示等），由
                SubAgent 增强得出；预览路径无增强时为 None，记为空 dict。
            config: 本次合成使用的供应商配置快照（音色 / 格式 / 采样率 / 模型等，
                不含 api_key / workspace_id 等密钥）；为 None 时记为空 dict。

        Returns:
            成功时返回记录 dict；已关闭（max_records<=0）/ 空音频时返回 None。
        """
        if self.max_records <= 0 or not audio_bytes:
            return None
        ext = _normalize_ext(fmt)
        async with self._lock:
            records = await self._read_index()
            rec_id = f"rec_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
            filename = f"{rec_id}.{ext}"
            dest = self.records_dir / filename
            # 落盘音频：写文件是阻塞 IO，卸载到线程，避免卡住事件循环。
            try:
                await asyncio.to_thread(dest.write_bytes, audio_bytes)
            except OSError as exc:
                logger.warning(f"合成记录音频落盘失败（已跳过）: {exc}")
                return None
            record = {
                "id": rec_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "source_detail": source_detail or "",
                "provider": provider or "",
                "text": text or "",
                "format": ext,
                "duration": duration,
                "size": len(audio_bytes),
                "file": filename,
                "params": params or {},
                "config": config or {},
            }
            records.append(record)
            # 超出保留上限：按时间升序淘汰最旧的，并删除其音频文件。
            # max_records 已被调用方钳为 >=0，仅正整数生效；0 表示已关闭。
            if self.max_records > 0 and len(records) > self.max_records:
                records.sort(key=lambda r: r.get("created_at", ""))
                excess = records[: len(records) - self.max_records]
                for old in excess:
                    self._delete_file(old.get("file"))
                records = records[len(records) - self.max_records :]
            try:
                await self._write_index(records)
            except Exception as exc:  # noqa: BLE001
                # KV 索引写回失败：回滚刚写入的音频文件，避免产生孤儿文件。
                self._delete_file(filename)
                logger.warning(f"合成记录索引写回失败，已回滚音频文件: {exc}")
                return None
            return record

    async def add_from_path(
        self,
        *,
        source_path: str,
        source: str,
        provider: str,
        text: str,
        fmt: str,
        source_detail: str = "",
        duration: float | None = None,
        params: dict | None = None,
        config: dict | None = None,
    ) -> dict | None:
        """从已有音频文件直接落盘一条合成记录（省去读回内存那一步）。

        与 :meth:`add` 不同，本方法用 ``shutil.copyfile`` 把 ``source_path``
        直接拷贝到 ``records_dir``，避免「先 read_bytes 再 write_bytes」带来的
        双倍磁盘 IO；所有阻塞 IO（拷贝 / 索引写回）均经 ``asyncio.to_thread``
        卸载到线程，绝不阻塞事件循环。索引写回失败时同样回滚刚写入的音频文件。

        Args:
            source_path: 已有音频文件的绝对路径（合成器产出的临时文件）。
            source: 合成来源（见本模块 SOURCE_* 常量）。
            provider: 供应商显示名。
            text: 合成文本。
            fmt: 音频格式（扩展名或 MIME 子类型）。
            source_detail: 来源补充信息（如 UMO 标识）。
            duration: 音频时长（秒），可为 None。
            params: AI 增强参数；为 None 时记为空 dict。
            config: 本次合成使用的供应商配置快照；为 None 时记为空 dict。

        Returns:
            成功时返回记录 dict；已关闭（max_records<=0）/ 源文件缺失或为空时返回 None。
        """
        if self.max_records <= 0 or not source_path:
            return None
        src = Path(source_path)
        # 前置校验：源文件必须存在且非空，避免拷空文件或异常。
        try:
            if not src.is_file() or src.stat().st_size == 0:
                return None
        except OSError:
            return None
        ext = _normalize_ext(fmt)
        async with self._lock:
            records = await self._read_index()
            rec_id = f"rec_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
            filename = f"{rec_id}.{ext}"
            dest = self.records_dir / filename
            # 直接拷贝源文件（阻塞 IO，卸载到线程）。
            try:
                await asyncio.to_thread(shutil.copyfile, str(src), str(dest))
            except OSError as exc:
                logger.warning(f"合成记录音频落盘失败（已跳过）: {exc}")
                return None
            record = {
                "id": rec_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "source_detail": source_detail or "",
                "provider": provider or "",
                "text": text or "",
                "format": ext,
                "duration": duration,
                "size": dest.stat().st_size,
                "file": filename,
                "params": params or {},
                "config": config or {},
            }
            records.append(record)
            if self.max_records > 0 and len(records) > self.max_records:
                records.sort(key=lambda r: r.get("created_at", ""))
                excess = records[: len(records) - self.max_records]
                for old in excess:
                    self._delete_file(old.get("file"))
                records = records[len(records) - self.max_records :]
            try:
                await self._write_index(records)
            except Exception as exc:  # noqa: BLE001
                self._delete_file(filename)
                logger.warning(f"合成记录索引写回失败，已回滚音频文件: {exc}")
                return None
            return record

    async def reconcile(self) -> int:
        """启动对账：对齐磁盘音频与 KV 索引，清理孤儿文件与悬挂索引项。

        - 孤儿文件：``records_dir`` 中存在、但未被任何索引记录引用的音频文件
          （多因历史 KV 写失败 / 索引被清空而产生），予以删除。
        - 悬挂索引项：索引中引用的音频文件在磁盘已缺失的记录，从索引剔除并
          写回，避免管理页列出无法播放的条目。

        安全护栏：当索引整体为空（或读取异常）时，**不**删除任何磁盘文件——
        此时无法可靠区分「确实无记录」与「索引暂不可达」，保守起见保留磁盘文件。

        Returns:
            被清理的条目总数（孤儿文件数 + 悬挂索引项数）。
        """
        async with self._lock:
            records = await self._read_index()
            if not isinstance(records, list) or not records:
                # 索引为空：保守跳过，避免误删磁盘上可能仍有效的音频。
                return 0
            referenced = {
                r.get("file") for r in records if isinstance(r, dict) and r.get("file")
            }
            try:
                on_disk = [p for p in self.records_dir.iterdir() if p.is_file()]
            except OSError:
                on_disk = []
            removed = 0
            # 1) 孤儿文件：磁盘有、索引未引用。仅动本模块产出的音频文件
            #    （以 "rec_" 前缀开头且扩展名在白名单内），绝不误删其它文件
            #    （如 .txt / 临时文件 / 非 rec_ 前缀的文件）。
            for p in on_disk:
                name = p.name
                if not name.startswith("rec_"):
                    continue
                suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if suffix not in _ALLOWED_AUDIO_EXT:
                    continue
                if name not in referenced:
                    try:
                        p.unlink()
                        removed += 1
                    except OSError:
                        pass
            # 2) 悬挂索引项：索引有、磁盘文件缺失 → 剔除并写回索引。
            alive: list[dict] = []
            for r in records:
                fname = r.get("file")
                if (
                    fname
                    and _SAFE_ID_RE.match(fname)
                    and (self.records_dir / fname).is_file()
                ):
                    alive.append(r)
                else:
                    removed += 1
            if len(alive) != len(records):
                try:
                    await self._write_index(alive)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"合成记录对账后索引写回失败: {exc}")
            return removed

    async def list_records(self) -> list[dict]:
        """返回全部记录，按合成时间倒序（最新在前）。"""
        async with self._lock:
            records = await self._read_index()
            records.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            return records

    async def get_record(self, rec_id: str) -> dict | None:
        """按 id 取单条记录；id 非法或不存在时返回 None。"""
        if not _SAFE_ID_RE.match(rec_id or ""):
            return None
        async with self._lock:
            for r in await self._read_index():
                if r.get("id") == rec_id:
                    return r
            return None

    async def get_audio_bytes(self, rec_id: str) -> bytes | None:
        """按 id 读取音频字节；id / 文件名非法或文件缺失时返回 None。"""
        if not _SAFE_ID_RE.match(rec_id or ""):
            return None
        async with self._lock:
            rec = None
            for r in await self._read_index():
                if r.get("id") == rec_id:
                    rec = r
                    break
            if not rec:
                return None
            filename = rec.get("file")
            if not filename or not _SAFE_ID_RE.match(filename):
                return None
            try:
                return (self.records_dir / filename).read_bytes()
            except OSError:
                return None

    async def delete(self, rec_id: str) -> bool:
        """删除单条记录（含音频文件）。

        Args:
            rec_id: 待删除记录 id。

        Returns:
            删除成功（记录确实存在）返回 True，否则 False。
        """
        if not _SAFE_ID_RE.match(rec_id or ""):
            return False
        async with self._lock:
            records = await self._read_index()
            target = next((r for r in records if r.get("id") == rec_id), None)
            if target is None:
                return False
            self._delete_file(target.get("file"))
            await self._write_index([r for r in records if r.get("id") != rec_id])
            return True

    async def clear(self) -> int:
        """清空全部记录，返回被删除的条数。"""
        async with self._lock:
            records = await self._read_index()
            count = len(records)
            for r in records:
                self._delete_file(r.get("file"))
            await self._write_index([])
            return count

    async def record_from_base64(
        self,
        *,
        audio_base64: str,
        source: str,
        provider: str,
        text: str,
        fmt: str,
        source_detail: str = "",
        duration: float | None = None,
    ) -> dict | None:
        """从 base64 音频数据写入一条记录（供前端回传的试听音频等场景）。

        Args:
            audio_base64: 标准 base64 字符串（不含 data: 前缀）。
            uew: 其余字段含义同 :meth:`add`。

        Returns:
            成功时返回记录 dict；解码失败 / 体积超限 / 已关闭（max_records<=0）时返回 None。
        """
        if self.max_records <= 0 or not audio_base64:
            return None
        try:
            audio_bytes = __import__("base64").b64decode(audio_base64, validate=True)
        except Exception:
            return None
        if len(audio_bytes) > _MAX_RECORD_BYTES:
            return None
        return await self.add(
            audio_bytes=audio_bytes,
            source=source,
            provider=provider,
            text=text,
            fmt=fmt,
            source_detail=source_detail,
            duration=duration,
        )
