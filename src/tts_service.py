"""TTS 核心服务层 —— 供 Plugin 和 Tool 共同调用"""

import asyncio
import json
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Record
from astrbot.api.star import Context

from ..providers import ProviderFactory
from ..providers.utils.audio import get_audio_duration
from .config import TTSEnhancerConfig
from .livingmemory_bridge import LivingMemoryBridge
from .sub_agent import TTSSubAgent
from .synthesis_store import (
    SOURCE_CHAT,
    SOURCE_PREVIEW,
    SynthesisRecordStore,
    build_config_snapshot,
)


class TTSService:
    """TTS 合成服务

    负责管理 TTS 供应商、上下文消息获取、人格解析以及核心的文本转语音合成流程。
    """

    def __init__(
        self,
        context: Context,
        providers: list,
        config: TTSEnhancerConfig,
        audio_data_dir: Path,
        synthesis_store: SynthesisRecordStore | None = None,
    ) -> None:
        """
        初始化 TTS 服务实例。

        Args:
            context: AstrBot 上下文对象，用于访问会话和人格管理器等。
            providers: TTS 供应商配置列表。
            config: TTS 增强配置对象。
            audio_data_dir: 音频数据存储目录路径。
            synthesis_store: 合成记录存储实例；为 None 时跳过落盘记录。
        """
        self.context = context
        self.providers = providers
        self.config = config
        self.audio_data_dir = audio_data_dir
        self.synthesis_store = synthesis_store
        # 后台落盘任务集合：避免 asyncio.create_task 产生的任务被 GC 提前回收。
        self._record_tasks: set[asyncio.Task] = set()
        self.sub_agent = TTSSubAgent(context, config.raw_config)
        # LivingMemory 桥接：合成前召回长期记忆作为 SubAgent 上下文（未安装时自动降级）
        self.lm_bridge = LivingMemoryBridge(context)

    async def get_context_messages(self, event: AstrMessageEvent) -> list[dict]:
        """获取上下文消息（按对话轮次，即 user 消息的条数）

        Args:
            event: 消息事件对象，用于获取会话标识。

        Returns:
            包含历史消息字典的列表，每条消息包含 'role' 和 'content' 键。
        """
        context_window = self.config.get("context_window", 10)
        if not isinstance(context_window, int) or context_window <= 0:
            return []

        messages = []
        try:
            session_id = event.unified_msg_origin
            conv_mgr = self.context.conversation_manager
            if conv_mgr:
                conv_id = await conv_mgr.get_curr_conversation_id(session_id)
                if conv_id:
                    conv = await conv_mgr.get_conversation(session_id, conv_id)
                    if conv and conv.history:
                        history = json.loads(conv.history)
                        collected = []
                        user_count = 0

                        # 从最近的消息开始向前遍历
                        for msg in reversed(history):
                            role = msg.get("role", "user")
                            content = msg.get("content", "")

                            # 只保留有内容的消息（避免空消息干扰计数）
                            if content:
                                collected.append(
                                    {"role": role, "content": str(content)}
                                )
                                if role == "user":
                                    user_count += 1

                                    # 当收集到第 context_window 条 user 消息时停止
                                    if user_count >= context_window:
                                        break

                        # 恢复时间顺序（旧的在前，新的在后）
                        messages = list(reversed(collected))
        except Exception as e:
            logger.warning(f"获取上下文消息失败: {e}")

        return messages

    async def get_current_persona(self, event: AstrMessageEvent) -> tuple[str, str]:
        """获取当前会话的人格提示词与人格 ID

        Args:
            event: 消息事件对象，用于获取会话标识和平台名称。

        Returns:
            (prompt, persona_id) 元组；未生效人格时两者均为空字符串。
        """
        umo = event.unified_msg_origin

        # 拿到当前 conversation 绑定的 persona_id
        # conv_mgr 可能未就绪（与 get_context_messages 保持一致，先判空）
        conv_mgr = self.context.conversation_manager
        conversation_persona_id = None
        if conv_mgr:
            conv_id = await conv_mgr.get_curr_conversation_id(umo)
            conversation = (
                await conv_mgr.get_conversation(umo, conv_id) if conv_id else None
            )
            conversation_persona_id = conversation.persona_id if conversation else None

        # 解析最终生效的人格（persona_manager 同样可能未就绪）
        persona_mgr = self.context.persona_manager
        if not persona_mgr:
            logger.warning("persona_manager 未就绪，跳过人格解析")
            return "", ""

        (
            persona_id,
            persona,
            _force,
            _webchat,
        ) = await persona_mgr.resolve_selected_persona(
            umo=umo,
            conversation_persona_id=conversation_persona_id,
            platform_name=event.get_platform_name(),
        )

        if persona:
            return persona.get("prompt", ""), persona_id or ""
        return "", persona_id or ""

    async def synthesize(
        self,
        raw_text: str,
        event: AstrMessageEvent,
        context_messages: list[dict],
    ) -> Record | None:
        """核心合成方法

        Args:
            raw_text: 待合成文本
            event: 消息事件
            context_messages: 上下文消息列表

        Returns:
            Record 对象或 None
        """
        if not self.providers:
            logger.warning("没有配置任何 TTS 供应商")
            return None

        # 解析当前人格（失败时降级为空，避免异常冒泡中断整条消息装饰）
        try:
            persona, persona_id = await self.get_current_persona(event)
        except Exception as e:
            logger.warning(f"解析当前人格失败: {e}，降级为通用音色")
            persona, persona_id = "", ""
        logger.debug(f"persona: {persona}")

        # 长期记忆检索：合成前召回 LivingMemory 相关上下文，供 SubAgent 判断语音风格。
        # 召回条数 top_k <= 0 即视为关闭；任何失败都降级为空，不阻塞 TTS 合成。
        memory_context = ""
        top_k = int(self.config.get("memory_retrieval_top_k", 0) or 0)
        if top_k > 0:
            try:
                strategy = str(
                    self.config.get("memory_retrieval_query_strategy", "user_message")
                    or "user_message"
                ).strip()
                prefix = str(
                    self.config.get("memory_retrieval_prefix", "") or ""
                ).strip()
                if strategy == "prefix":
                    query = prefix
                else:
                    query = raw_text
                recalled = await self.lm_bridge.recall_for_tts(
                    event=event, query=query, top_k=top_k
                )
                if recalled:
                    memory_context = recalled
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"TTS 长期记忆检索失败（已降级）: {exc}")
                memory_context = ""

        # 人格专属音色：绑定了当前 persona_id 的供应商
        bound = [
            e
            for e in self.providers
            if persona_id and e.get("persona_id") == persona_id
        ]
        # 通用兜底音色：未绑定任何人格的供应商
        unbound = [e for e in self.providers if not e.get("persona_id")]
        ordered_providers = bound + unbound

        # 候选为空：供应商均绑定到其他人格且无通用兜底音色，需提示而非静默失败
        if not ordered_providers:
            logger.warning(
                "当前人格未匹配到可用音色：供应商均绑定到其他人格且无通用兜底音色，本次不合成语音"
            )
            return None

        for idx, entry in enumerate(ordered_providers):
            if bound and idx == len(bound):
                logger.warning("人格专属音色均失败，回退到通用音色")

            entry_name = self.config.get_entry_name(entry, idx)
            audio_path, final_text = await self._synthesize_one(
                entry,
                raw_text,
                entry_name,
                event=event,
                enhance=self.config.get("enable_enhance", True),
                persona=persona,
                context_messages=context_messages,
                memory_context=memory_context,
                source=SOURCE_CHAT,
            )
            if audio_path:
                return Record.fromFileSystem(audio_path, text=final_text)

        if bound and not unbound:
            logger.warning("人格专属音色均失败，且未配置通用兜底音色")
        else:
            logger.error("所有 TTS 供应商均失败")
        return None

    async def _synthesize_one(
        self,
        entry: dict,
        raw_text: str,
        entry_name: str,
        *,
        event: AstrMessageEvent | None = None,
        enhance: bool = False,
        persona: str = "",
        context_messages: list[dict] | None = None,
        memory_context: str = "",
        voice_id: str | None = None,
        source: str = SOURCE_CHAT,
    ) -> tuple[str | None, str]:
        """单供应商合成一步（聊天与预览共用）。

        聊天路径（``synthesize``）对每个候选供应商调用本方法；预览路径
        （``preview_synthesize``）对指定供应商调用本方法。两者仅在选择供应商、
        是否注入人格 / 上下文上有差异，单供应商的合成流程（配置快照 → 可选
        SubAgent 增强 → 调用 API → 落盘记录）完全一致，借由此方法统一。

        Args:
            entry: 供应商配置 dict。
            raw_text: 待合成文本。
            entry_name: 供应商显示名（用于日志与记录）。
            event: 聊天事件（用于解析会话标识与记录来源）；预览为 None。
            enhance: 是否允许本供应商走 SubAgent 增强（还需该供应商有文档）。
                聊天路径传全局 enable_enhance；预览路径传前端开关。
            persona: 说话人人格（仅聊天路径注入）。
            context_messages: 对话上下文（仅聊天路径注入）。
            memory_context: 长期记忆上下文（仅聊天路径注入）。
            voice_id: 显式音色 ID（预览场景覆盖配置音色）；聊天为 None。
            source: 合成记录来源类别。

        Returns:
            (audio_path, final_text)：成功时 audio_path 为音频路径，final_text 为
            实际合成文本（增强后或原文）；失败时 audio_path 为 None。
        """
        entry_with_data_dir = dict(entry)
        entry_with_data_dir["_data_dir"] = str(self.audio_data_dir)

        adapter = ProviderFactory.get_adapter(entry_with_data_dir)
        if not adapter:
            return None, raw_text

        # 配置快照：本次合成实际使用的供应商配置（不含密钥），供记录展示。
        config_snapshot = build_config_snapshot(entry)

        # 增强仅在「允许增强 且 该供应商带能力文档」时生效；否则纯文本降级。
        has_docs = bool(adapter.docs_content)
        do_enhance = bool(enhance) and has_docs
        if not do_enhance:
            if bool(enhance) and not has_docs:
                logger.warning(f"供应商 {entry_name} 缺少文档，降级为纯文本请求")
            try:
                audio_path = await adapter.call_api(
                    text=raw_text,
                    raw_params={},
                    config=entry_with_data_dir,
                    voice_id=voice_id,
                )
            except Exception as e:
                logger.warning(f"纯文本 TTS 失败 ({entry_name}): {e}")
                return None, raw_text
            if audio_path:
                self._spawn_record(
                    audio_path,
                    raw_text,
                    entry_name,
                    event,
                    source,
                    config=config_snapshot,
                )
                return audio_path, raw_text
            # call_api 返回空串（而非抛异常）时同样视为失败，交由调用方换下一个。
            return None, raw_text

        # 准备 SubAgent 工具
        tool_set = None
        if hasattr(adapter, "get_tool_schema"):
            # 合成前按供应商配置超时有界等待预热（如 Eleven audio_effects 目录）：
            # 等到则本合成把对应参数拼进 schema 与提示词，等不到本次不暴露但预热
            # 继续后台跑。基类默认无操作（同步/非预热适配器零成本），仅当适配器
            # 确实提供该异步钩子时才调用，对测试替身/MagicMock 友好。
            hook = getattr(adapter, "ensure_catalog_ready", None)
            if callable(hook) and asyncio.iscoroutinefunction(hook):
                await hook()
            tool = adapter.get_tool_schema()
            if tool:
                from astrbot.core.agent.tool import ToolSet

                tool_set = ToolSet(tools=[tool])

        session_id = event.unified_msg_origin if event is not None else None
        current_context = context_messages.copy() if context_messages else []
        # SubAgent 内部完成「工具执行 + 校验 + role:tool 重试」；
        # 成功返回合法（或末轮清洗后）参数 dict，失败兜底返回 None。
        try:
            api_params = await self.sub_agent.call(
                adapter.get_subagent_system_prompt(),
                raw_text,
                session_id,
                context_messages=current_context,
                persona=persona,
                tool_set=tool_set,
                adapter=adapter,
                max_attempts=2,
                memory_context=memory_context,
            )
        except Exception as e:
            logger.warning(f"SubAgent 调用异常: {e}")
            api_params = None
        if api_params is None or not isinstance(api_params, dict):
            api_params = None

        enhanced_text = raw_text
        # SubAgent 可能返回空 text；此时保留原文，否则会带着空文本去请求 TTS API
        if api_params and api_params.get("text"):
            enhanced_text = api_params["text"]

        # 调用 API
        try:
            audio_path = await adapter.call_api(
                text=enhanced_text,
                raw_params=api_params or {},
                config=entry_with_data_dir,
                voice_id=voice_id,
            )
            if audio_path:
                logger.info(f"TTS 合成成功，供应商: {entry_name}")
                self._spawn_record(
                    audio_path,
                    enhanced_text,
                    entry_name,
                    event,
                    source,
                    params=api_params,
                    config=config_snapshot,
                )
                return audio_path, enhanced_text
        except Exception as e:
            logger.warning(f"供应商 {entry_name} TTS API 失败: {e}，尝试下一个")
        return None, raw_text

    async def preview_synthesize(
        self,
        entry: dict,
        entry_name: str,
        text: str,
        voice_id: str,
        enhance: bool,
        source: str = SOURCE_PREVIEW,
    ) -> tuple[str | None, str | None]:
        """预览合成（复用 ``_synthesize_one``），返回 (audio_path, 格式扩展名)。

        与聊天路径的区别：指定单一供应商与音色、无会话 / 人格 / 上下文、可显式
        开关 SubAgent 增强（默认关闭；开启时若未配置 ``enhance_llm_provider`` 则
        回退到默认聊天模型）。

        Args:
            entry: 供应商配置 dict。
            entry_name: 供应商显示名。
            text: 预览文本。
            voice_id: 预览音色 ID。
            enhance: 是否走 SubAgent 增强（前端开关）。
            source: 合成记录来源类别。

        Returns:
            (audio_path, ext)：成功时 audio_path 为音频路径，ext 为扩展名（不含点）；
            失败时两者为 None。
        """
        audio_path, _final_text = await self._synthesize_one(
            entry,
            text,
            entry_name,
            enhance=enhance,
            voice_id=voice_id,
            source=source,
        )
        if not audio_path:
            return None, None
        ext = Path(audio_path).suffix.lstrip(".") or "mp3"
        return audio_path, ext

    def _spawn_record(
        self,
        audio_path: str,
        text: str,
        provider: str,
        event: AstrMessageEvent | None,
        source: str = SOURCE_CHAT,
        params: dict | None = None,
        config: dict | None = None,
    ) -> None:
        """后台触发一次合成记录落盘，绝不阻塞调用方（TTS 主链路）。

        通过 ``asyncio.create_task`` 把 :meth:`_record_synthesis` 派发到事件循环，
        立即返回；落盘本身的阻塞 IO（文件拷贝、时长探测）会在其内部经
        ``asyncio.to_thread`` 卸载到线程，进一步避免占用事件循环。任务引用保存在
        ``self._record_tasks`` 中，完成后自动移除，防止被提前回收。
        """
        if self.synthesis_store is None or self.synthesis_store.max_records <= 0:
            return
        task = asyncio.create_task(
            self._record_synthesis(
                audio_path, text, provider, event, source, params, config
            )
        )
        self._record_tasks.add(task)
        task.add_done_callback(self._record_tasks.discard)

    async def _record_synthesis(
        self,
        audio_path: str,
        text: str,
        provider: str,
        event: AstrMessageEvent | None,
        source: str = SOURCE_CHAT,
        params: dict | None = None,
        config: dict | None = None,
    ) -> None:
        """把一次成功的合成结果落盘为合成记录（后台任务，失败静默跳过）。

        由 :meth:`_spawn_record` 经 ``asyncio.create_task`` 调用，因此任何异常都
        不应冒泡影响当次 TTS 合成。内部所有阻塞 IO（直接拷贝音频文件、探测音频
        时长）均经 ``asyncio.to_thread`` 卸载到线程，不占用事件循环。

        Args:
            audio_path: 合成产生的音频文件绝对路径。
            text: 实际合成的文本（增强后）。
            provider: 命中并成功的供应商显示名。
            event: 消息事件，用于提取 UMO 作为来源补充信息；可为 None。
            source: 合成来源（见 synthesis_store.SOURCE_* 常量）。
            params: AI 增强参数（指令 / 音量 / 语速 / 音调 / 语言提示等，由
                SubAgent 增强得出）；为 None 时记空 dict。
            config: 本次合成使用的供应商配置快照（音色 / 格式 / 采样率 / 模型等，
                不含密钥）；为 None 时记空 dict。
        """
        if self.synthesis_store is None or self.synthesis_store.max_records <= 0:
            return
        try:
            # 音频时长探测（mediainfo/ffprobe 子进程）放到线程，避免阻塞循环。
            duration = None
            try:
                duration = await asyncio.to_thread(get_audio_duration, audio_path)
            except Exception:  # noqa: BLE001
                duration = None
            detail = ""
            if event is not None:
                detail = getattr(event, "unified_msg_origin", "") or ""
            # 直接按源文件路径落盘（shutil.copyfile），省去读回内存那一步。
            await self.synthesis_store.add_from_path(
                source_path=audio_path,
                source=source,
                provider=provider,
                text=text,
                fmt=Path(audio_path).suffix.lstrip(".") or "mp3",
                source_detail=detail,
                duration=duration,
                params=params,
                config=config,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"合成记录落盘失败（已跳过）: {exc}")
