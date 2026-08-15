"""TTS SubAgent —— 支持 Function Calling 的结构化参数生成。"""

import traceback
from typing import Any, Dict, List, Optional

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import ToolSet
from astrbot.core import logger


class TTSSubAgent:
    def __init__(self, context: Context, config: dict = None):
        self.context = context
        self.config = config or {}

    async def call(
        self,
        event: AstrMessageEvent,
        system_prompt: str,
        user_message: str,
        context_messages: Optional[List[Dict[str, str]]] = None,
        tool_set: Optional[ToolSet] = None,
    ) -> Optional[Dict[str, Any]]:
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
                provider = self._get_provider_by_name(provider_name, session_id)
                if not provider:
                    logger.warning(f"未找到指定的增强模型 '{provider_name}'，降级为当前会话模型")
                    provider = self.context.get_using_provider(session_id)
            else:
                provider = self.context.get_using_provider(session_id)

            if not provider:
                logger.error("TTS SubAgent: 无法获取 LLM Provider")
                return None

            # 构建消息
            messages = []
            if context_messages:
                summary = "\n".join(
                    f"[{msg['role']}] {msg['content']}" for msg in context_messages if msg.get("content")
                )
                if summary.strip():
                    messages.append({
                        "role": "user",
                        "content": f"以下是最近的对话上下文，请参考判断合适的语音风格：\n\n{summary}\n\n---"
                    })
                    messages.append({
                        "role": "assistant",
                        "content": "我已了解上下文，请提供需要增强的文本。"
                    })

            messages.append({
                "role": "user",
                "content": f"请为以下文本生成 TTS 合成参数：\n\n{user_message}"
            })

            # 构建请求
            request = ProviderRequest(
                messages=messages,
                system_prompt=system_prompt,
                session_id=session_id,
                func_tool=tool_set,   # 传入工具集
            )

            response = await provider.request(request)

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

    def _get_provider_by_name(self, name: str, session_id: str):
        """尝试通过名称获取 Provider"""
        try:
            return self.context.provider_manager.get_provider(name)
        except AttributeError:
            pass
        try:
            return self.context.get_provider(name)
        except Exception:
            return None
        