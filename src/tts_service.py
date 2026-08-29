"""TTS 核心服务层 —— 供 Plugin 和 Tool 共同调用"""
import json
from pathlib import Path

from astrbot.api.message_components import Record
from astrbot.core import logger

from .sub_agent import TTSSubAgent
from ..providers import ProviderFactory

from typing import Optional
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
from .config import TTSEnhancerConfig


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
    ) -> None:
        """
        初始化 TTS 服务实例。

        Args:
            context: AstrBot 上下文对象，用于访问会话和人格管理器等。
            providers: TTS 供应商配置列表。
            config: TTS 增强配置对象。
            audio_data_dir: 音频数据存储目录路径。
        """
        self.context = context
        self.providers = providers
        self.config = config
        self.audio_data_dir = audio_data_dir
        self.sub_agent = TTSSubAgent(context, config.raw_config)

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
                                collected.append({"role": role, "content": str(content)})
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

    async def get_current_persona(self, event: AstrMessageEvent) -> str:
        """获取当前会话的人格提示词

        Args:
            event: 消息事件对象，用于获取会话标识和平台名称。

        Returns:
            当前生效的人格提示词字符串，若未配置则返回空字符串。
        """
        umo = event.unified_msg_origin

        # 拿到当前 conversation 绑定的 persona_id
        conv_mgr = self.context.conversation_manager
        conv_id = await conv_mgr.get_curr_conversation_id(umo)
        conversation = await conv_mgr.get_conversation(umo, conv_id) if conv_id else None
        conversation_persona_id = conversation.persona_id if conversation else None

        # 解析最终生效的人格
        (persona_id, persona, _force, _webchat) = await self.context.persona_manager.resolve_selected_persona(
            umo=umo,
            conversation_persona_id=conversation_persona_id,
            platform_name=event.get_platform_name(),
        )

        if persona:
            return persona.get("prompt", "")
        return ""

    async def synthesize(
        self,
        raw_text: str,
        event: AstrMessageEvent,
        context_messages: list[dict],
    ) -> Optional[Record]:
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

        for idx, entry in enumerate(self.providers):
            entry_name = self.config.get_entry_name(entry, idx)

            adapter = ProviderFactory.get_adapter(entry)
            if not adapter:
                continue

            entry_with_data_dir = dict(entry)
            entry_with_data_dir["_data_dir"] = str(self.audio_data_dir)

            # 检查文档是否存在
            has_docs = bool(adapter.docs_content)
            enable_enhance = self.config.get("enable_enhance", True) and has_docs

            # 无文档降级
            if not enable_enhance:
                logger.warning(f"供应商 {entry_name} 缺少文档，降级为纯文本请求")
                try:
                    audio_path = await adapter.call_api(
                        text=raw_text,
                        raw_params={},
                        config=entry_with_data_dir
                    )
                    if audio_path:
                        return Record.fromFileSystem(audio_path, text=raw_text)
                except Exception as e:
                    logger.warning(f"纯文本 TTS 失败 ({entry_name}): {e}")
                    continue

            # 准备 SubAgent 工具
            tool_set = None
            if hasattr(adapter, "get_tool_schema"):
                tool = adapter.get_tool_schema()
                if tool:
                    from astrbot.core.agent.tool import ToolSet
                    tool_set = ToolSet(tools=[tool])

            current_context = context_messages.copy() if context_messages else []
            api_params = None
            max_attempts = 2
            attempt = 0

            while attempt < max_attempts:
                try:
                    sys_prompt = adapter.get_subagent_system_prompt()
                    persona = await self.get_current_persona(event)
                    logger.debug(f"persona: {persona}")
                    result = await self.sub_agent.call(
                        event,
                        sys_prompt,
                        raw_text,
                        current_context,
                        persona,
                        tool_set=tool_set
                    )

                    if result and isinstance(result, dict):
                        temp_params = adapter.parse_subagent_response(result)
                        is_valid, err_msg = adapter.validate_params(temp_params)

                        if is_valid:
                            api_params = temp_params
                            break
                        else:
                            if attempt == max_attempts - 1:
                                logger.warning(f"清理非法参数: {err_msg}")
                                api_params = adapter.sanitize_params(temp_params)
                                break
                            else:
                                current_context.append({
                                    "role": "assistant",
                                    "content": f"我尝试调用 tts_enhance，参数为：{json.dumps(temp_params, ensure_ascii=False)}"
                                })
                                current_context.append({
                                    "role": "user",
                                    "content": f"参数格式错误：{err_msg}。请检查参数范围并仅调用 tts_enhance 工具修正。"
                                })
                                attempt += 1
                                continue
                    else:
                        if attempt == max_attempts - 1:
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
                            attempt += 1
                            continue
                except Exception as e:
                    logger.warning(f"SubAgent 调用异常 (尝试 {attempt+1}): {e}")
                    if attempt == max_attempts - 1:
                        break
                    current_context.append({
                        "role": "user",
                        "content": f"调用过程中出现异常：{e}，请重新调用 tts_enhance 工具。"
                    })
                    attempt += 1
                    continue

            enhanced_text = raw_text
            if api_params and "text" in api_params:
                enhanced_text = api_params["text"]

            if self.config.get("log_enhanced_params", False) and api_params:
                logger.info(f"增强参数: {json.dumps(api_params, ensure_ascii=False)}")

            # 调用 API
            try:
                audio_path = await adapter.call_api(
                    text=enhanced_text,
                    raw_params=api_params or {},
                    config=entry_with_data_dir
                )
                if audio_path:
                    logger.info(f"TTS 合成成功，供应商: {entry_name}")
                    return Record.fromFileSystem(audio_path, text=enhanced_text)
            except Exception as e:
                logger.warning(f"供应商 {entry_name} TTS API 失败: {e}，尝试下一个")

        logger.error(f"所有 TTS 供应商均失败")
        return None
    