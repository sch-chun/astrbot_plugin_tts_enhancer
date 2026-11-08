"""astrbot_plugin_tts_enhancer - 多供应商智能语音合成插件

本模块为 AstrBot 提供 TTS（Text-to-Speech）增强功能，支持多供应商智能语音合成。
"""

from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.event.filter import on_decorating_result, on_llm_request
from astrbot.api.message_components import Plain
from astrbot.api.star import Context, Star
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .src.config import TTSEnhancerConfig
from .src.routes.file import register_file
from .src.routes.kv import register_kv
from .src.routes.records import register_records
from .src.routes.voice import register_voice
from .src.synthesis_store import SynthesisRecordStore
from .src.tools import SendVoiceTool
from .src.tts_parser import TTS_END_TAG, TTS_START_TAG, split_by_tts_tags
from .src.tts_service import TTSService


class TTSEnhancerPlugin(Star):
    """TTS Enhancer —— 多供应商智能语音合成插件

    架构：主模型输出 <tts> 标签 → SubAgent 增强语音参数 → Provider Adapter 调用 API。

    Args:
        context (Context): 插件上下文对象，提供与 AstrBot 核心交互的能力。
        config (Optional[dict]): 插件配置字典，默认为 None。

    Attributes:
        config (TTSEnhancerConfig): TTS 增强配置对象。
        providers (list): TTS 供应商配置列表。
        plugin_data_path (Path): 插件数据存储路径。
        tts_service (TTSService): TTS 核心服务实例。
    """

    def __init__(self, context: Context, config: dict | None = None) -> None:
        """初始化 TTS Enhancer 插件。

        依次完成数据目录初始化、核心服务初始化、LLM Tool 注册和 Web API 路由注册。

        Args:
            context (Context): 插件上下文对象。
            config (Optional[dict]): 插件配置字典。
        """
        super().__init__(context, config)
        self.config = TTSEnhancerConfig(config)
        self.providers = self.config.get_providers()
        logger.info(
            f"TTS Enhancer: 已加载 {len(self.providers)} 个 TTS 供应商。"
        )

        # 初始化数据目录
        self.plugin_data_path = (
            Path(get_astrbot_data_path()) / "plugin_data" / self.name
        )
        (self.plugin_data_path / "uploads").mkdir(parents=True, exist_ok=True)
        (self.plugin_data_path / "audio").mkdir(parents=True, exist_ok=True)

        # 合成记录存储：落盘所有合成过的语音，供「合成记录」管理页使用
        synthesis_records_dir = self.plugin_data_path / "synthesis_records"
        synthesis_records_dir.mkdir(parents=True, exist_ok=True)
        # 0 或负数 = 关闭落盘；正整数 = 保留最近 N 份（不支持「不限制」）。
        # 负数在此统一钳为 0，避免「-1 不限制」语义在多处打架。
        # 注意：不能用 `or 50` 兜底，否则会把 0 误判成「未配置」而变成 50。
        _max_raw = self.config.get("synthesis_record_max", 50)
        try:
            synthesis_max = int(_max_raw)
        except (TypeError, ValueError):
            synthesis_max = 50
        if synthesis_max < 0:
            synthesis_max = 0
        self.synthesis_store = SynthesisRecordStore(
            records_dir=synthesis_records_dir,
            kv=self,
            max_records=synthesis_max,
        )

        # 初始化核心服务
        self.tts_service = TTSService(
            context=self.context,
            providers=self.providers,
            config=self.config,
            audio_data_dir=self.plugin_data_path / "audio",
            synthesis_store=self.synthesis_store,
        )

        # 注册 Tool
        send_voice_tool = SendVoiceTool(tts_service=self.tts_service)
        self.context.add_llm_tools(send_voice_tool)

        # 注册路由
        self._register_routes()

    async def initialize(self) -> None:
        """插件激活时由 AstrBot 调用：执行一次性启动对账。

        对齐磁盘音频文件与 KV 索引，清理孤儿文件与悬挂索引项，保证「合成记录」
        管理页的数据一致（详见 ``SynthesisRecordStore.reconcile``）。任何异常都
        被静默吞掉，绝不影响插件正常激活。
        """
        await super().initialize()
        if self.synthesis_store is not None:
            try:
                removed = await self.synthesis_store.reconcile()
                if removed:
                    logger.info(
                        f"[TTS Enhancer] 启动对账清理 {removed} 条孤儿/悬挂记录"
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"[TTS Enhancer] 启动对账失败（已跳过）: {exc}")

    def _resolve_uploads_path(self, file_id: str) -> Path:
        """将 file_id 解析为 uploads 目录下的绝对路径，并二次确认未越权。

        即使 _validate_file_id 已过滤掉绝大多数危险字符，这里仍做 resolve() 后
        的父目录比较，作为防御性编程。

        Args:
            file_id: 已通过 _validate_file_id 校验的文件标识符。

        Returns:
            uploads 目录下的目标绝对路径。

        Raises:
            ValueError: 解析后的路径逃逸出 uploads 目录。
        """
        uploads_dir = (self.plugin_data_path / "uploads").resolve()
        target = (uploads_dir / file_id).resolve()
        if uploads_dir != target.parent:
            raise ValueError(f"file_id 越权访问: {file_id!r}")
        return target

    async def _process_tts_text(
        self,
        text: str,
        event: AstrMessageEvent,
        context_messages: list[dict],
    ) -> list:
        """处理包含 TTS 标签的文本，将其转换为消息组件列表。

        Args:
            text (str): 包含 TTS 标签的原始文本。
            event (AstrMessageEvent): 消息事件对象。
            context_messages (list[dict]): 上下文消息列表。

        Returns:
            list: 包含 Plain 文本组件和 Record 音频组件的列表。若 TTS 合成失败，则降级为 Plain 文本组件。
        """
        segments = split_by_tts_tags(text)
        components = []

        for seg in segments:
            if seg["type"] == "text":
                components.append(Plain(seg["content"]))
            elif seg["type"] == "tts":
                audio_component = await self.tts_service.synthesize(
                    seg["content"], event, context_messages
                )
                if audio_component:
                    components.append(audio_component)
                    if self.config.get("dual_output", False):
                        components.append(Plain(seg["content"]))
                else:
                    components.append(Plain(seg["content"]))
        return components

    # ———————— 事件钩子 ————————

    @on_llm_request()
    async def on_llm_req(
        self, event: AstrMessageEvent, request: ProviderRequest
    ) -> None:
        """处理 LLM 请求事件，将配置中的 TTS 提示词追加到系统提示词中。

        Args:
            event (AstrMessageEvent): 消息事件对象。
            request (ProviderRequest): 提供者请求对象，包含系统提示词等信息。

        Returns:
            None: 若未配置 TTS 提供商或提示词则直接返回，否则将提示词追加至系统提示词后无显式返回。
        """
        if not self.providers:
            logger.warning("未配置 TTS 提供商，跳过 TTS 提示词追加")
            return
        tts_prompt = self.config.get("tts_prompt", "")
        if not tts_prompt:
            logger.warning("未配置 TTS 提示词，模型可能不会进行 TTS 生成")
            return
        request.system_prompt += f"\n{tts_prompt}"

    @on_decorating_result(priority=13)
    async def on_decorate(self, event: AstrMessageEvent) -> None:
        """处理消息结果装饰事件，提取并处理文本中的 TTS 标签。

        检查消息链中的纯文本组件是否包含 TTS 标签，若存在则进行
        TTS 处理并替换原文本组件。

        Args:
            event (AstrMessageEvent): 消息事件对象，包含待处理的消息结果链。

        Returns:
            None
        """
        result = event.get_result()
        if not result or not result.chain:
            return

        # 检查消息链中是否存在 TTS 标签
        has_tts_tag = any(
            isinstance(comp, Plain)
            and (TTS_START_TAG in comp.text or TTS_END_TAG in comp.text)
            for comp in result.chain
        )
        if not has_tts_tag:
            return

        context_messages = await self.tts_service.get_context_messages(event)

        # 遍历消息链，处理包含 TTS 标签的文本组件
        new_chain = []
        modified = False
        for comp in result.chain:
            if isinstance(comp, Plain) and (
                TTS_START_TAG in comp.text or TTS_END_TAG in comp.text
            ):
                # 替换为 TTS 处理后的组件列表
                components = await self._process_tts_text(
                    comp.text, event, context_messages
                )
                new_chain.extend(components)
                modified = True
            else:
                new_chain.append(comp)

        # 若有修改，则更新消息结果链
        if modified:
            result.chain = new_chain

    # ————————————————————————

    def _register_routes(self) -> None:
        """注册 Web API 路由（按职责拆分到 ``src/routes`` 各模块）。

        各路由组以闭包捕获 ``self``，分别由对应 ``register_*(self)`` 注册：
            - voice   : 供应商列表 + 音色 CRUD + 预览；
            - file    : 音频上传 + 供应商文件管理；
            - kv      : 通用键值存储；
            - records : 合成记录管理 + 管理页背景图。
        """
        register_voice(self)
        register_file(self)
        register_kv(self)
        register_records(self)
