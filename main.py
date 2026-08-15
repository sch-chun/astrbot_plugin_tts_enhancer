import re
from pathlib import Path

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api.event.filter import on_llm_request, on_decorating_result
from astrbot.api.message_components import Plain, Record
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import ToolSet
from astrbot.core import logger

from .sub_agent import TTSSubAgent
from .providers import ProviderFactory

# ─── TTS 标签正则 ───
TTS_PATTERN = re.compile(r"<tts>(.*?)</tts>", re.DOTALL)
TTS_START_TAG = "<tts>"
TTS_END_TAG = "</tts>"
BOUNDARY_SEPARATORS = "$"
BOUNDARY_SEPARATOR_PATTERN = re.compile(rf"[{re.escape(BOUNDARY_SEPARATORS)}]+$")
LEADING_BOUNDARY_SEPARATOR_PATTERN = re.compile(
    rf"^[{re.escape(BOUNDARY_SEPARATORS)}]+"
)


class TTSEnhancerPlugin(Star):
    """TTS Enhancer —— 多供应商智能语音合成插件

    架构：主模型输出 <tts> 标签 → SubAgent 增强语音参数 → Provider Adapter 调用 API
    """

    def __init__(self, context: Context, config: dict = None):
        super().__init__(context, config)
        self.config = config or {}
        self.providers = self._load_providers()
        self.sub_agent = TTSSubAgent(context, config)

    def _load_providers(self) -> list:
        """加载并排序 providers"""
        providers_raw = self.config.get("providers", [])
        return sorted(providers_raw, key=lambda x: x.get("priority", 100))

    @staticmethod
    def _trim_boundary_separators(text: str, *, leading: bool = False) -> str:
        if leading:
            return LEADING_BOUNDARY_SEPARATOR_PATTERN.sub("", text)
        return BOUNDARY_SEPARATOR_PATTERN.sub("", text)

    @classmethod
    def _append_text_segment(cls, segments: list[dict], text: str) -> None:
        stripped = text.strip()
        if not stripped:
            return
        if segments and segments[-1]["type"] == "tts":
            stripped = cls._trim_boundary_separators(stripped, leading=True).strip()
        stripped = cls._trim_boundary_separators(stripped).strip()
        if stripped:
            segments.append({"type": "text", "content": stripped})

    @classmethod
    def _split_by_tts_tags(cls, text: str) -> list[dict]:
        segments = []
        cursor = 0
        text_length = len(text)

        while cursor < text_length:
            start = text.find(TTS_START_TAG, cursor)
            end = text.find(TTS_END_TAG, cursor)

            if start == -1 and end == -1:
                cls._append_text_segment(segments, text[cursor:])
                break
            if end != -1 and (start == -1 or end < start):
                cls._append_text_segment(segments, text[cursor:end])
                cursor = end + len(TTS_END_TAG)
                continue
            if start > cursor:
                cls._append_text_segment(segments, text[cursor:start])
            if start == -1:
                break
            end = text.find(TTS_END_TAG, start + len(TTS_START_TAG))
            if end == -1:
                cls._append_text_segment(segments, text[start + len(TTS_START_TAG):])
                break
            tts_content = text[start + len(TTS_START_TAG): end].strip()
            tts_content = cls._trim_boundary_separators(
                cls._trim_boundary_separators(tts_content, leading=True),
            ).strip()
            if tts_content:
                segments.append({"type": "tts", "content": tts_content})
            cursor = end + len(TTS_END_TAG)

        if not segments:
            stripped = text.replace(TTS_START_TAG, "").replace(TTS_END_TAG, "").strip()
            if stripped:
                segments.append({"type": "text", "content": stripped})
        return segments

    def _get_cfg(self, key: str, default=None):
        return self.config.get(key, default)

    @on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, request: ProviderRequest):
        tts_prompt = self._get_cfg("tts_prompt", "")
        if not tts_prompt:
            return
        request.system_prompt += f"\n{tts_prompt}"

    @on_decorating_result(priority=13)
    async def on_decorate(self, event: AstrMessageEvent):
        result = event.get_result()
        if not result or not result.chain:
            return

        has_tts_tag = any(
            isinstance(comp, Plain)
            and (TTS_START_TAG in comp.text or TTS_END_TAG in comp.text)
            for comp in result.chain
        )
        if not has_tts_tag:
            return

        context_messages = self._get_context_messages(event)

        new_chain = []
        modified = False
        for comp in result.chain:
            if isinstance(comp, Plain) and (
                TTS_START_TAG in comp.text or TTS_END_TAG in comp.text
            ):
                components = await self._process_tts_text(comp.text, event, context_messages)
                new_chain.extend(components)
                modified = True
            else:
                new_chain.append(comp)

        if modified:
            result.chain = new_chain

    def _get_context_messages(self, event: AstrMessageEvent) -> list[dict]:
        context_window = self._get_cfg("context_window", 3)
        messages = []
        try:
            session_id = event.unified_msg_origin
            provider = self.context.get_using_provider(session_id)
            if provider and hasattr(provider, 'conversation_history'):
                history = provider.conversation_history.get(session_id, [])
                for msg in history[-context_window * 2:]:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            c.get("text", "") for c in content if isinstance(c, dict)
                        )
                    messages.append({"role": role, "content": str(content)[:200]})
        except Exception:
            pass
        return messages

    async def _process_tts_text(
        self,
        text: str,
        event: AstrMessageEvent,
        context_messages: list[dict],
    ) -> list:
        segments = self._split_by_tts_tags(text)
        components = []

        for seg in segments:
            if seg["type"] == "text":
                components.append(Plain(seg["content"]))
            elif seg["type"] == "tts":
                audio_component = await self._synthesize(seg["content"], event, context_messages)
                if audio_component:
                    components.append(audio_component)
                    if self._get_cfg("dual_output", False):
                        components.append(Plain(seg["content"]))
                else:
                    components.append(Plain(seg["content"]))
        return components

    async def _synthesize(
        self,
        raw_text: str,
        event: AstrMessageEvent,
        context_messages: list[dict],
    ) -> Record | None:
        """按优先级尝试所有供应商，集成 SubAgent 工具调用。"""
        providers = self._get_sorted_providers()
        last_error = None
        for entry in providers:
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter:
                continue

            # 检查是否有文档
            has_docs = bool(adapter.docs_content)
            enable_enhance = self.config.get("enable_enhance", True) and has_docs

            # 无文档：降级为纯文本，直接调用 API
            if not enable_enhance:
                logger.warning(f"供应商 {entry.get('provider_type')} 缺少文档，降级为纯文本请求")
                try:
                    audio_path = await adapter.call_api(
                        text=raw_text,
                        raw_params={},   # 不传任何额外参数
                        config=entry
                    )
                    if audio_path:
                        return Record.fromFileSystem(audio_path, text=raw_text)
                except Exception as e:
                    logger.warning(f"纯文本 TTS 失败: {e}")
                    continue
            else:

                # 准备 SubAgent 工具（如果启用增强）
                tool_set = None
                if self.config.get("enable_enhance", True):
                    # 适配器应实现 get_tool_schema()
                    if hasattr(adapter, "get_tool_schema"):
                        tool = adapter.get_tool_schema()
                        tool_set = ToolSet(tools=[tool])
                    else:
                        logger.warning(f"适配器 {adapter.provider_name} 不支持工具调用")

                # 调用 SubAgent
                api_params = None
                enhanced_text = raw_text
                try:
                    sys_prompt = adapter.get_subagent_system_prompt(raw_text)
                    result = await self.sub_agent.call(
                        event,
                        sys_prompt,
                        raw_text,
                        context_messages,
                        tool_set=tool_set
                    )
                    if result and isinstance(result, dict):
                        api_params = adapter.parse_subagent_response(result)
                        if api_params and "text" in api_params:
                            enhanced_text = api_params["text"]
                            logger.debug(f"SubAgent 增强: {raw_text[:30]}... -> {enhanced_text[:30]}...")
                        else:
                            logger.warning("SubAgent 返回参数缺少 text，使用原始文本")
                    else:
                        logger.warning("SubAgent 未返回有效参数，使用原始文本")
                except Exception as e:
                    logger.warning(f"SubAgent 增强失败: {e}，使用原始文本")

                # 调用 TTS API
                try:
                    audio_path = await adapter.call_api(
                        text=enhanced_text,
                        raw_params=api_params or {},   # 包含所有工具参数
                        config=entry
                    )
                    if audio_path:
                        logger.info(f"TTS 合成成功，供应商: {entry.get('provider_type')}")
                        return Record.fromFileSystem(audio_path, text=enhanced_text)
                except Exception as e:
                    last_error = e
                    logger.warning(f"供应商 {entry.get('provider_type')} 失败: {e}，尝试下一个")

            if last_error:
                logger.error(f"所有 TTS 供应商均失败: {last_error}")
            return None
