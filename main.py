import re
import json

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api.event.filter import on_llm_request, on_decorating_result
from astrbot.api.message_components import Plain, Record
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import ToolSet
from astrbot.core import logger

from .sub_agent import TTSSubAgent
from .providers import ProviderFactory

from typing import Optional


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

    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context, config)
        self.config = config or {}
        self.providers = self._load_providers()
        self.sub_agent = TTSSubAgent(context, config)

    def _load_providers(self) -> list:
        """加载并排序 providers"""
        providers_raw = self.config.get("providers", [])
        if not providers_raw:
            logger.warning("TTS Enhancer: 配置中未找到任何 TTS 供应商（providers 为空），请检查插件配置")
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

    @on_llm_request()
    async def on_llm_req(self, event: AstrMessageEvent, request: ProviderRequest):
        tts_prompt = self.config.get("tts_prompt", "")
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

        context_messages = await self._get_context_messages(event)

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

    async def _get_context_messages(self, event: AstrMessageEvent) -> list[dict]:
        context_window = self.config.get("context_window", 10)
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
                        recent = history[-context_window * 2:] if context_window > 0 else []
                        for msg in recent:
                            role = msg.get("role", "user")
                            content = msg.get("content", "")
                            if content:
                                messages.append({"role": role, "content": str(content)[:200]})
        except Exception as e:
            logger.warning(f"获取上下文消息失败: {e}")
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
                    if self.config.get("dual_output", False):
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
        """按优先级尝试所有供应商，集成 SubAgent 工具调用 + 参数验证重试"""
        if not self.providers:
            logger.warning("没有配置任何 TTS 供应商，请在插件配置中添加 providers 条目")
            return None
        
        last_error = None
        for entry in self.providers:
            adapter = ProviderFactory.get_adapter(entry)
            if not adapter:
                continue

            # 检查是否有文档
            has_docs = bool(adapter.docs_content)
            enable_enhance = self.config.get("enable_enhance", True) and has_docs

            # 无文档：降级为纯文本，直接调用 API
            if not enable_enhance:
                logger.warning(f"供应商 {entry.get('__template_key', 'unknown')} 缺少文档，降级为纯文本请求")
                try:
                    audio_path = await adapter.call_api(
                        text=raw_text,
                        raw_params={},
                        config=entry
                    )
                    if audio_path:
                        return Record.fromFileSystem(audio_path, text=raw_text)
                except Exception as e:
                    logger.warning(f"纯文本 TTS 失败: {e}")
                    continue

            # 准备 SubAgent 工具
            tool_set = None
            if hasattr(adapter, "get_tool_schema"):
                tool = adapter.get_tool_schema()
                if tool:
                    tool_set = ToolSet(tools=[tool])
                else:
                    logger.warning(f"适配器 {entry.get('__template_key', 'unknown')} 的 get_tool_schema 返回 None，不启用工具")
            else:
                logger.warning(f"适配器 {entry.get('__template_key', 'unknown')} 不支持工具调用")

            # 复制上下文，用于重试时追加错误信息
            current_context = context_messages.copy() if context_messages else []
            api_params = None
            max_attempts = 2
            attempt = 0

            # --- SubAgent 调用循环（含参数验证与重试） ---
            while attempt < max_attempts:
                try:
                    sys_prompt = adapter.get_subagent_system_prompt(raw_text)
                    result = await self.sub_agent.call(
                        event,
                        sys_prompt,
                        raw_text,
                        current_context,
                        tool_set=tool_set
                    )

                    if result and isinstance(result, dict):
                        temp_params = adapter.parse_subagent_response(result)
                        is_valid, err_msg = adapter.validate_params(temp_params)

                        if is_valid:
                            api_params = temp_params
                            logger.debug(f"SubAgent 参数验证通过 (尝试 {attempt+1})")
                            break
                        else:
                            if attempt == max_attempts - 1:

                                # 最后一次尝试：清理非法参数
                                logger.warning(f"SubAgent 参数验证失败，清理非法参数: {err_msg}")
                                api_params = adapter.sanitize_params(temp_params)
                                break
                            else:

                                # 非最后一次：将 AI 回复和错误反馈追加到上下文
                                current_context.append({
                                    "role": "assistant",
                                    "content": f"我尝试调用 tts_enhance，参数为：{json.dumps(temp_params, ensure_ascii=False)}"
                                })
                                current_context.append({
                                    "role": "user",
                                    "content": f"参数格式错误：{err_msg}。请检查参数范围并仅调用 tts_enhance 工具修正。"
                                })
                                logger.info(f"SubAgent 参数验证失败，要求重试 ({attempt+1}/{max_attempts}): {err_msg}")
                                attempt += 1
                                continue
                    else:

                        # 未返回有效结构
                        if attempt == max_attempts - 1:
                            logger.warning("SubAgent 未返回有效结构，使用原始文本")
                            break
                        else:
                            current_context.append({
                                "role": "assistant",
                                "content": "我尝试调用 tts_enhance，但未返回有效结构。"
                            })
                            current_context.append({
                                "role": "user",
                                "content": "请检查你的 tts_enhance 工具调用，并确保返回有效的结构。"
                            })
                            logger.info(f"SubAgent 未返回有效结构，要求重试 ({attempt+1}/{max_attempts})")
                            attempt += 1
                            continue

                except Exception as e:

                    # SubAgent 调用异常
                    logger.warning(f"SubAgent 调用异常 (尝试 {attempt+1}): {e}")
                    if attempt == max_attempts - 1:
                        break

                    # 追加异常信息到上下文并重试
                    current_context.append({
                        "role": "user",
                        "content": f"调用过程中出现异常：{e}，请重新调用 tts_enhance 工具。"
                    })
                    attempt += 1
                    continue

            # --- 提取最终文本 ---
            enhanced_text = raw_text
            if api_params and "text" in api_params:
                enhanced_text = api_params["text"]

            # --- 打印增强参数（若配置开启）---
            if self.config.get("log_enhanced_params", False) and api_params:
                logger.info(f"增强参数: {json.dumps(api_params, ensure_ascii=False)}")

            # --- 调用 TTS API ---
            try:
                audio_path = await adapter.call_api(
                    text=enhanced_text,
                    raw_params=api_params or {},
                    config=entry
                )
                if audio_path:
                    logger.info(f"TTS 合成成功，供应商: {entry.get('__template_key', 'unknown')}")
                    return Record.fromFileSystem(audio_path, text=enhanced_text)
            except Exception as e:
                last_error = e
                logger.warning(f"供应商 {entry.get('__template_key', 'unknown')} TTS API 失败: {e}，尝试下一个")

        if last_error:
            logger.error(f"所有 TTS 供应商均失败: {last_error}")
        return None
