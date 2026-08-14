"""TTS SubAgent —— 调用 LLM 生成增强的 TTS 参数。"""

import traceback

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core import logger


class TTSSubAgent:
    """TTS 指导模型调用器。"""

    def __init__(self, context: Context, config: dict = None):
        self.context = context
        self.config = config or {}

    async def call(
        self,
        event: AstrMessageEvent,
        system_prompt: str,
        user_message: str,
        context_messages: list[dict] = None,
    ) -> str | None:
        """调用 LLM 生成增强的 TTS 参数。"""
        try:
            session_id = event.unified_msg_origin
            provider = self.context.get_using_provider(session_id)
            if not provider:
                logger.error("TTS SubAgent: 无法获取 LLM Provider")
                return None

            messages = []

            if context_messages:
                context_summary = "\n".join(
                    f"[{msg['role']}] {msg['content']}"
                    for msg in context_messages
                    if msg.get("content")
                )
                if context_summary.strip():
                    messages.append({
                        "role": "user",
                        "content": f"以下是最近的对话上下文，请参考上下文判断合适的语音情感和风格：\n\n{context_summary}\n\n---",
                    })
                    messages.append({
                        "role": "assistant",
                        "content": "好的，我已了解对话上下文，请告诉我需要增强的文本。",
                    })

            messages.append({
                "role": "user",
                "content": f"请增强以下文本的语音表现力：\n\n{user_message}",
            })

            response = await provider.text_chat(
                prompt="",
                session_id=session_id,
                contexts=messages,
                system_prompt=system_prompt,
                image_urls=[],
            )

            if response and hasattr(response, "completion_text"):
                result = response.completion_text.strip()
            elif response and isinstance(response, str):
                result = response.strip()
            else:
                result = str(response).strip() if response else None

            if not result:
                logger.warning("TTS SubAgent: LLM 返回空")
                return None

            return result

        except Exception as e:
            logger.error(f"TTS SubAgent 调用失败: {e}")
            logger.debug(traceback.format_exc())
            return None
