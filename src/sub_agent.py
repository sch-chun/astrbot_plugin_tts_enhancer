"""TTS SubAgent —— 支持 Function Calling 的结构化参数生成。"""

import traceback

from typing import Any, Optional

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
from astrbot.core.provider import Provider
from astrbot.core.agent.tool import ToolSet
from astrbot.core import logger


class TTSSubAgent:
    """
    TTS 子代理类，用于生成文本转语音的参数。
    
    该类通过调用大语言模型来生成 TTS 所需的参数，支持通过 Function Calling
    输出结构化参数，也支持从普通文本响应中提取参数。
    """
    def __init__(self, context: Context, config: Optional[dict] = None):
        """
        初始化TTS子代理。
        
        Args:
            context (Context): Star 上下文对象，用于获取 provider 等资源
            config (Optional[dict]): 配置字典，包含 enhance_llm_provider 等配置项
        """
        self.context = context
        self.config = config or {}

    async def call(
        self,
        event: AstrMessageEvent,
        system_prompt: str,
        user_message: str,
        context_messages: Optional[list[dict[str, str]]] = None,
        persona: str = "",
        tool_set: Optional[ToolSet] = None,
    ) -> Optional[dict[str, Any]]:
        """
        调用 LLM 生成 TTS 参数。

        Args:
            event (AstrMessageEvent): 消息事件对象，包含会话信息
            system_prompt (str): 系统提示词，用于指导 LLM 生成 TTS 参数
            user_message (str): 用户输入的消息内容
            context_messages (Optional[list[dict[str, str]]]): 对话上下文消息列表，每个消息包含 role 和 content
            tool_set (Optional[ToolSet]): 可用的工具集，包含 TTS 增强相关的工具函数

        Returns:
            Optional[dict[str, Any]]: 成功时返回包含 TTS 参数的字典，失败时返回 None
            返回的字典可能包含以下键：
                - text (str): 需要转换为语音的文本内容
                - 其他 TTS 相关参数（根据工具调用结果而定）

        Raises:
            无直接抛出的异常，所有异常都会被捕获并记录日志

        Note:
            1. 优先使用工具调用方式获取 TTS 参数
            2. 如果工具调用失败，会降级到文本解析方式
            3. 如果都失败，返回 None
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

            # 构建完整用户提示
            full_prompt = ""
            if persona:
                full_prompt = f"说话人人格：{persona}\n\n"
            if context_messages:

                # 生成摘要
                summary_lines = []
                for msg in context_messages:
                    role = msg.get("role", "user")
                    content = msg.get("content", "")
                    if content:
                        summary_lines.append(f"[{role}] {content}")
                if summary_lines:
                    summary = "\n".join(summary_lines)
                    full_prompt += (
                        f"以下是最近的对话上下文，请参考判断合适的语音风格：\n\n"
                        f"{summary}\n\n"
                        f"---\n\n"
                    )
            full_prompt += f"现在，请为以下文本合成语音（调用 tts_enhance 工具）：\n{user_message}"
            logger.debug(f"TTS SubAgent: 用户提示：\n{full_prompt}")

            # 构建请求
            response = await provider.text_chat(
                prompt=full_prompt,
                session_id=session_id,
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
