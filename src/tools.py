"""TTS Agent Tool —— 让 AI 在 Agent Loop 中主动调用发送语音"""

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.message.message_event_result import MessageChain

from .tts_service import TTSService

from typing import Any


@dataclass
class SendVoiceTool(FunctionTool[AstrAgentContext]):
    """发送语音消息的工具"""
    tts_service: Any = None
    name: str = "send_voice_to_user"
    description: str = (
        "将文本转换为语音并发送给用户。"
        "适用场景：用户要求语音播报、朗读长文本、发送语音消息等。"
        "工具会自动根据文本内容和对话上下文规划合适的语音情感和参数。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "需要转换为语音的文本内容。"
                },
                "session": {
                    "type": "string",
                    "description": (
                        "可选。留空则使用当前会话。"
                        "使用 'platform_id:message_type:session_id' 格式指定其他会话。"
                    ),
                }
            },
            "required": ["text"],
        }
    )

    def __post_init__(self):
        if self.tts_service is None:
            raise ValueError("TTS Service is required")

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs
    ) -> ToolExecResult:
        """执行语音发送"""
        assert self.tts_service is not None, "TTS Service is required"
        text = kwargs.get("text")
        if not text:
            return "错误：缺少 text 参数"

        # 获取当前会话
        event = context.context.event
        current_session = event.unified_msg_origin

        # session 处理
        session = kwargs.get("session") or current_session

        # 获取上下文
        context_messages = await self.tts_service.get_context_messages(event)

        # 合成语音
        audio_component = await self.tts_service.synthesize(
            raw_text=text,
            event=event,
            context_messages=context_messages,
        )

        if audio_component:
            
            # 发送语音消息
            message_chain = MessageChain()
            message_chain.chain.append(audio_component)
            star_context = context.context.context
            try:
                await star_context.send_message(session, message_chain)
            except Exception as e:
                return f"发送语音消息失败：{e}"
            return f"已成功发送语音消息，内容：{text[:50]}..."
        else:
            return "语音合成失败，请检查 TTS 配置或稍后重试。"
