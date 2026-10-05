"""TTS 核心服务层 —— 供 Plugin 和 Tool 共同调用"""

import json
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Record
from astrbot.api.star import Context

from ..providers import ProviderFactory
from .config import TTSEnhancerConfig
from .sub_agent import TTSSubAgent


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

            entry_with_data_dir = dict(entry)
            entry_with_data_dir["_data_dir"] = str(self.audio_data_dir)

            adapter = ProviderFactory.get_adapter(entry_with_data_dir)
            if not adapter:
                continue

            # 检查文档是否存在
            has_docs = bool(adapter.docs_content)
            enable_enhance = self.config.get("enable_enhance", True) and has_docs

            # 无文档降级
            if not enable_enhance:
                logger.warning(f"供应商 {entry_name} 缺少文档，降级为纯文本请求")
                try:
                    audio_path = await adapter.call_api(
                        text=raw_text, raw_params={}, config=entry_with_data_dir
                    )
                    if audio_path:
                        return Record.fromFileSystem(audio_path, text=raw_text)
                except Exception as e:
                    logger.warning(f"纯文本 TTS 失败 ({entry_name}): {e}")
                    continue
                # call_api 返回空串（而非抛异常）时同样视为失败：
                # 缺少文档的供应商本就不该走增强流程，直接换下一个，避免白白调用一次 LLM。
                continue

            # 准备 SubAgent 工具
            tool_set = None
            if hasattr(adapter, "get_tool_schema"):
                tool = adapter.get_tool_schema()
                if tool:
                    from astrbot.core.agent.tool import ToolSet

                    tool_set = ToolSet(tools=[tool])

            current_context = context_messages.copy() if context_messages else []
            # SubAgent 内部完成「工具执行 + 校验 + role:tool 重试」；
            # 成功返回合法（或末轮清洗后）参数 dict，失败兜底返回 None。
            try:
                api_params = await self.sub_agent.call(
                    event,
                    adapter.get_subagent_system_prompt(),
                    raw_text,
                    current_context,
                    persona,
                    tool_set=tool_set,
                    adapter=adapter,
                    max_attempts=2,
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

            if self.config.get("log_enhanced_params", False) and api_params:
                try:
                    logger.info(
                        f"增强参数: {json.dumps(api_params, ensure_ascii=False)}"
                    )
                except (TypeError, ValueError):
                    logger.warning("增强参数含不可序列化对象，跳过日志输出")

            # 调用 API
            try:
                audio_path = await adapter.call_api(
                    text=enhanced_text,
                    raw_params=api_params or {},
                    config=entry_with_data_dir,
                )
                if audio_path:
                    logger.info(f"TTS 合成成功，供应商: {entry_name}")
                    return Record.fromFileSystem(audio_path, text=enhanced_text)
            except Exception as e:
                logger.warning(f"供应商 {entry_name} TTS API 失败: {e}，尝试下一个")

        if bound and not unbound:
            logger.warning("人格专属音色均失败，且未配置通用兜底音色")
        else:
            logger.error("所有 TTS 供应商均失败")
        return None
