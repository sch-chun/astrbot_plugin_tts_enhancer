"""SynthesisRecordStore 单元测试（纯函数 / 落盘逻辑，不启动 AstrBot）。

覆盖：
- add 落盘音频 + 写入 KV 元数据 + 倒序列表
- get_record / get_audio_bytes 往返
- delete 删除记录与音频文件
- clear 清空并回报删除条数
- record_from_base64 解码 / 非法 / 超限 / 关闭
- 最多保留份数的 LRU 淘汰（删除最旧 + 删文件）
- 安全 id 白名单拒绝路径穿越
- 关闭状态下 add 跳过但既有记录仍可读

注意：元数据走内存版 FakeKV（模拟 AstrBot 官方 KV），音频文件仍落盘到 tmp_path，
与实现一致——不引入任何 file 版 index.json 兜底。
"""

import base64

from astrbot_plugin_tts_enhancer.src.synthesis_store import (
    SOURCE_CHAT,
    SOURCE_PREVIEW,
    SynthesisRecordStore,
)

SAMPLE = b"\x00\x01\x02ID3fake-audio-bytes"


class FakeKV:
    """内存版 KV，模拟 AstrBot 官方 KV 的 get_kv_data / put_kv_data 接口。"""

    def __init__(self) -> None:
        self._data: dict = {}

    async def get_kv_data(self, key: str, default):
        return self._data.get(key, default)

    async def put_kv_data(self, key: str, value) -> None:
        self._data[key] = value


def _make_store(tmp_path, max_records=50) -> SynthesisRecordStore:
    return SynthesisRecordStore(
        records_dir=tmp_path / "rec",
        kv=FakeKV(),
        max_records=max_records,
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


async def _seed(store: SynthesisRecordStore, n: int, source=SOURCE_CHAT):
    """连续写入 n 条记录，返回生成的 id 列表（按写入顺序）。"""
    ids = []
    for i in range(n):
        rec = await store.add(
            audio_bytes=SAMPLE + bytes([i]),
            source=source,
            provider="p",
            text=f"t{i}",
            fmt="mp3",
        )
        ids.append(rec["id"])
    return ids


class TestAddAndList:
    async def test_add_writes_audio_and_index(self, tmp_path):
        store = _make_store(tmp_path)
        rec = await store.add(
            audio_bytes=SAMPLE,
            source=SOURCE_CHAT,
            provider="MiniMax",
            text="你好",
            fmt="mp3",
        )
        assert rec is not None
        assert rec["source"] == SOURCE_CHAT
        assert rec["provider"] == "MiniMax"
        assert rec["text"] == "你好"
        assert rec["format"] == "mp3"
        assert rec["size"] == len(SAMPLE)
        assert rec["id"]
        # 音频文件落盘
        audio_file = tmp_path / "rec" / rec["file"]
        assert audio_file.is_file()
        assert audio_file.read_bytes() == SAMPLE
        # 元数据（KV）含该记录
        records = await store.list_records()
        assert len(records) == 1
        assert records[0]["id"] == rec["id"]

    async def test_list_is_reverse_chrono(self, tmp_path):
        store = _make_store(tmp_path)
        ids = await _seed(store, 3)
        listed = await store.list_records()
        assert [r["id"] for r in listed] == ids[::-1]

    async def test_add_normalizes_unknown_ext_to_mp3(self, tmp_path):
        store = _make_store(tmp_path)
        rec = await store.add(
            audio_bytes=SAMPLE,
            source=SOURCE_CHAT,
            provider="p",
            text="x",
            fmt="audio/wav",
        )
        assert rec["format"] == "mp3"
        assert rec["file"].endswith(".mp3")


class TestGetAndDelete:
    async def test_get_record_and_audio_roundtrip(self, tmp_path):
        store = _make_store(tmp_path)
        rec = await store.add(
            audio_bytes=SAMPLE,
            source=SOURCE_CHAT,
            provider="p",
            text="x",
            fmt="wav",
        )
        fetched = await store.get_record(rec["id"])
        assert fetched is not None
        assert fetched["text"] == "x"
        audio = await store.get_audio_bytes(rec["id"])
        assert audio == SAMPLE

    async def test_get_missing_record_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        assert await store.get_record("nope") is None
        assert await store.get_audio_bytes("nope") is None

    async def test_delete_removes_record_and_file(self, tmp_path):
        store = _make_store(tmp_path)
        rec = await store.add(
            audio_bytes=SAMPLE,
            source=SOURCE_CHAT,
            provider="p",
            text="x",
            fmt="mp3",
        )
        audio_file = tmp_path / "rec" / rec["file"]
        assert audio_file.is_file()
        ok = await store.delete(rec["id"])
        assert ok is True
        assert not audio_file.exists()
        assert await store.get_record(rec["id"]) is None

    async def test_delete_missing_returns_false(self, tmp_path):
        store = _make_store(tmp_path)
        assert await store.delete("nope") is False


class TestClear:
    async def test_clear_removes_all_and_reports_count(self, tmp_path):
        store = _make_store(tmp_path)
        await _seed(store, 4)
        deleted = await store.clear()
        assert deleted == 4
        assert await store.list_records() == []
        # 音频文件也一并删除
        assert list((tmp_path / "rec").glob("*.mp3")) == []


class TestRecordFromBase64:
    async def test_decodes_and_stores(self, tmp_path):
        store = _make_store(tmp_path)
        rec = await store.record_from_base64(
            audio_base64=_b64(SAMPLE),
            source=SOURCE_PREVIEW,
            provider="Bailian",
            text="preview",
            fmt="mp3",
        )
        assert rec is not None
        assert rec["source"] == SOURCE_PREVIEW
        assert await store.get_audio_bytes(rec["id"]) == SAMPLE

    async def test_invalid_base64_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        rec = await store.record_from_base64(
            audio_base64="not!!valid!!base64",
            source=SOURCE_PREVIEW,
            provider="p",
            text="x",
            fmt="mp3",
        )
        assert rec is None

    async def test_empty_base64_returns_none(self, tmp_path):
        store = _make_store(tmp_path)
        assert (
            await store.record_from_base64(
                audio_base64="",
                source=SOURCE_PREVIEW,
                provider="p",
                text="x",
                fmt="mp3",
            )
            is None
        )

    async def test_oversize_rejected(self, tmp_path, monkeypatch):
        import astrbot_plugin_tts_enhancer.src.synthesis_store as mod

        monkeypatch.setattr(mod, "_MAX_RECORD_BYTES", 10)
        store = _make_store(tmp_path)
        rec = await store.record_from_base64(
            audio_base64=_b64(b"x" * 20),
            source=SOURCE_PREVIEW,
            provider="p",
            text="x",
            fmt="mp3",
        )
        assert rec is None

    async def test_disabled_returns_none(self, tmp_path):
        # max_records == 0 表示关闭落盘
        store = _make_store(tmp_path, max_records=0)
        assert (
            await store.record_from_base64(
                audio_base64=_b64(SAMPLE),
                source=SOURCE_PREVIEW,
                provider="p",
                text="x",
                fmt="mp3",
            )
            is None
        )


class TestEviction:
    async def test_oldest_dropped_when_over_max(self, tmp_path):
        store = _make_store(tmp_path, max_records=2)
        ids = await _seed(store, 3)
        listed = await store.list_records()
        assert len(listed) == 2
        # 最旧的一条（ids[0]）被淘汰
        kept_ids = {r["id"] for r in listed}
        assert ids[0] not in kept_ids
        assert ids[1] in kept_ids and ids[2] in kept_ids
        # 被淘汰记录的音频文件也删除
        dropped_file = tmp_path / "rec" / f"{ids[0]}.mp3"
        assert not dropped_file.exists()
        # 保留的两条文件仍在
        assert (tmp_path / "rec" / f"{ids[2]}.mp3").exists()

    async def test_negative_max_treated_as_disabled(self, tmp_path):
        # -1（以及任何负数）不再表示「不限制」，而是按关闭处理，避免无上限占满磁盘
        store = _make_store(tmp_path, max_records=-1)
        rec = await store.add(
            audio_bytes=SAMPLE, source="chat", provider="p", text="x", fmt="mp3"
        )
        assert rec is None
        assert await store.list_records() == []

    async def test_zero_max_disabled(self, tmp_path):
        store = _make_store(tmp_path, max_records=0)
        rec = await store.add(
            audio_bytes=SAMPLE, source="chat", provider="p", text="x", fmt="mp3"
        )
        assert rec is None
        assert await store.list_records() == []

    async def test_set_max_records_takes_effect(self, tmp_path):
        store = _make_store(tmp_path, max_records=50)
        store.set_max_records(1)
        ids = await _seed(store, 3)
        assert len(await store.list_records()) == 1
        assert ids[2] in {r["id"] for r in await store.list_records()}


class TestSafeId:
    async def test_path_traversal_id_rejected(self, tmp_path):
        store = _make_store(tmp_path)
        # 这些 id 不通过白名单：不得返回记录、不得删除任意文件
        sentinel = tmp_path / "rec" / "sentinel.txt"
        sentinel.write_text("keep")
        assert await store.get_record("../sentinel.txt") is None
        assert await store.get_audio_bytes("..") is None
        assert await store.get_audio_bytes("/etc/passwd") is None
        assert await store.delete("..") is False
        assert sentinel.exists()

    async def test_empty_id_rejected(self, tmp_path):
        store = _make_store(tmp_path)
        assert await store.get_record("") is None
        assert await store.get_audio_bytes("") is None
        assert await store.delete("") is False


class TestDisabledStore:
    async def test_add_skipped_but_existing_listable(self, tmp_path):
        # 先用正常上限记录一条，再把 max_records 置 0（关闭落盘）
        store = _make_store(tmp_path, max_records=50)
        rec = await store.add(
            audio_bytes=SAMPLE,
            source=SOURCE_CHAT,
            provider="p",
            text="x",
            fmt="mp3",
        )
        store.set_max_records(0)
        # 关闭后 add 跳过
        assert (
            await store.add(
                audio_bytes=SAMPLE,
                source=SOURCE_CHAT,
                provider="p",
                text="y",
                fmt="mp3",
            )
            is None
        )
        # 既有记录仍可读 / 可删
        assert await store.list_records() == [rec]
        assert await store.delete(rec["id"]) is True
