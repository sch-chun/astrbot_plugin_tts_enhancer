"""TTS SubAgent —— 支持 Function Calling 的结构化参数生成。"""

import traceback

from typing import Any, Optional

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
from astrbot.core.provider import Provider
from astrbot.core.agent.tool import ToolSet
from astrbot.core import logger


class TTSSubAgent:
    def __init__(self, context: Context, config: Optional[dict] = None):
        self.context = context
        self.config = config or {}

    async def call(
        self,
        event: AstrMessageEvent,
        system_prompt: str,
        user_message: str,
        context_messages: Optional[list[dict[str, str]]] = None,
        tool_set: Optional[ToolSet] = None,
    ) -> Optional[dict[str, Any]]:
        """
        调用 LLM 生成 TTS 参数。

        :param tool_set: 如果提供，LLM 将通过 Function Calling 输出结构化参数。
        :return: 如果 LLM 调用了工具，返回工具参数字典；否则返回 None。
        """
        try:
            session_id = event.unified_msg_origin

            # 获取增强模型 Provider
            provider_name = self.config.get("enhance_llm_provider", "")
            if provider_name:
                provider = self.context.get_provider_by_id(provider_name)
                if not provider:
                    logger.warning(f"未找到指定的增强模型 '{provider_name}'，降级为当前会话模型")
                    provider = self.context.get_using_provider(session_id)
            else:
                provider = self.context.get_using_provider(session_id)

            if not provider:
                logger.error("TTS SubAgent: 无法获取 LLM Provider")
                return None
            elif not isinstance(provider, Provider):
                logger.error("TTS SubAgent: LLM Provider 不是 Provider 类型")
                return None

            # 构建上下文列表
            contexts = []
            if context_messages:
                summary = "\n".join(
                    f"[{msg['role']}] {msg['content']}" for msg in context_messages if msg.get("content")
                )
                if summary.strip():
                    contexts.append({
                        "role": "user",
                        "content": f"以下是最近的对话上下文，请参考判断合适的语音风格：\n\n{summary}\n\n---"
                    })
                    contexts.append({
                        "role": "assistant",
                        "content": "我已了解上下文，请提供需要增强的文本。"
                    })

            # 构建请求
            response = await provider.text_chat(
                prompt=user_message,
                session_id=session_id,
                contexts=contexts,
                system_prompt=system_prompt,
                func_tool=tool_set
            )

            # 检查工具调用
            if hasattr(response, "tools_call_name") and response.tools_call_name:
                for name, args in zip(response.tools_call_name, response.tools_call_args):
                    if name == "tts_enhance":
                        return args
                    
                # 如果有工具调用但不是 tts_enhance，可忽略或警告
                logger.warning(f"SubAgent 调用了未预期的工具: {response.tools_call_name}")
            else:

                # 没有工具调用，尝试从文本中提取（降级）
                if hasattr(response, "completion_text") and response.completion_text:
                    text = response.completion_text.strip()
                    if text:

                        # 返回一个简单的字典，仅包含 text
                        return {"text": text}

            return None

        except Exception as e:
            logger.error(f"TTS SubAgent 调用失败: {e}")
            logger.debug(traceback.format_exc())
            return None
