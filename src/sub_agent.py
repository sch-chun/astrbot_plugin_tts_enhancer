"""TTS SubAgent —— 支持 Function Calling 的结构化参数生成。"""

import json
import traceback

from astrbot.core.provider import Provider
from astrbot.api import logger

from typing import Any, Optional
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context
from astrbot.core.agent.message import (
    AssistantMessageSegment,
    ToolCall,
    ToolCallMessageSegment,
)
from astrbot.core.agent.tool import ToolSet
from astrbot.core.provider.entities import ToolCallsResult


def _extract_tool_result(result) -> tuple[bool, str]:
    """把 tts_enhance 工具的返回值统一成 (is_error, text)。

    AstrBot 的工具既可以返回 ``str``（由执行器包成 CallToolResult），也可以直接
    返回 ``CallToolResult``。这里做兼容提取，方便上层判断成功 / 失败。

    Args:
        result: 工具 handler 的返回值。

    Returns:
        (is_error, text)：是否出错，以及结果 / 错误文本。
    """
    if hasattr(result, "isError"):  # mcp.types.CallToolResult
        text = ""
        for block in getattr(result, "content", None) or []:
            text += getattr(block, "text", "") or ""
        return bool(result.isError), text
    # str / None
    return False, result or ""


class TTSSubAgent:
    """TTS 子代理类，用于生成文本转语音的参数。

    调用大语言模型，通过 tts_enhance 工具抽取结构化参数，
    并由工具 handler 做参数校验。校验失败或工具执行异常时，
    以标准工具结果（role:"tool"）形式回灌给 LLM 重试；
    仅当模型未发起工具调用时，才以 role:"user" 提示其重新调用。
    """

    def __init__(self, context: Context, config: Optional[dict] = None):
        """初始化TTS子代理。

        Args:
            context (Context): Star 上下文对象，用于获取 provider 等资源
            config (Optional[dict]): 配置字典，包含 enhance_llm_provider 等配置项
        """
        self.context = context
        self.config = config or {}

    # —————— 内部辅助 ——————

    def _resolve_provider(self, session_id: str):
        """根据配置解析用于增强的 LLM Provider。

        Returns:
            Provider | None: 解析到的 Provider；无法解析时返回 None。
        """
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
        if not isinstance(provider, Provider):
            logger.error("TTS SubAgent: LLM Provider 不是 Provider 类型")
            return None
        return provider

    def _build_prompt(
        self, persona: str, context_messages: list[dict], user_message: str
    ) -> str:
        """组装单次 LLM 调用的完整 prompt。

        把说话人人格、历史对话上下文与待合成文本拼成一段提示词。历史消息以
        ``[role] content`` 前缀平铺，便于单轮 text_chat 携带上下文。

        Args:
            persona: 说话人人格描述。
            context_messages: 历史上下文消息列表。
            user_message: 本次待合成文本。

        Returns:
            str: 完整 prompt。
        """
        parts: list[str] = []
        if persona:
            parts.append(f"说话人人格：{persona}\n\n")

        if context_messages:
            summary_lines = []
            for msg in context_messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if content:
                    summary_lines.append(f"[{role}] {content}")
            if summary_lines:
                summary = "\n".join(summary_lines)
                parts.append(
                    f"以下是最近的对话上下文，请参考判断合适的语音风格：\n\n"
                    f"{summary}\n\n---\n\n"
                )

        parts.append(
            f"现在，请为以下文本合成语音（调用 tts_enhance 工具）：\n{user_message}"
        )
        return "".join(parts)

    def _build_tool_result(
        self, tool_call_id: str, tts_args: dict, content: str
    ) -> ToolCallsResult:
        """把一次 tts_enhance 调用及其结果打包成 ``ToolCallsResult``。

        生成 ``[assistant(tool_calls), tool(tool_call_id, content)]``，传给
        ``provider.text_chat(tool_calls_result=...)`` 即可作为工具结果回传。

        Args:
            tool_call_id: 模型本轮工具调用的 ID（来自 response.tools_call_ids）。
            tts_args: 模型传给 tts_enhance 的参数，用于重建 assistant 的 tool_calls。
            content: 工具结果文本（成功为 JSON 载荷，失败为错误描述）。

        Returns:
            ToolCallsResult: 可传给 ``text_chat`` 的结构化工具结果。
        """
        return ToolCallsResult(
            tool_calls_info=AssistantMessageSegment(
                tool_calls=[
                    ToolCall(
                        id=tool_call_id,
                        function=ToolCall.FunctionBody(
                            name="tts_enhance",
                            arguments=json.dumps(tts_args, ensure_ascii=False),
                        ),
                    )
                ]
            ),
            tool_calls_result=[
                ToolCallMessageSegment(tool_call_id=tool_call_id, content=content)
            ],
        )

    # —————— 主流程 ——————

    async def call(
        self,
        event: AstrMessageEvent,
        system_prompt: str,
        user_message: str,
        context_messages: Optional[list[dict[str, str]]] = None,
        persona: str = "",
        tool_set: Optional[ToolSet] = None,
        adapter: Any = None,
        max_attempts: int = 2,
    ) -> Optional[dict[str, Any]]:
        """调用 LLM 生成 TTS 参数（含工具执行与重试）。

        Args:
            event (AstrMessageEvent): 消息事件对象，包含会话信息
            system_prompt (str): 系统提示词，用于指导 LLM 生成 TTS 参数
            user_message (str): 用户输入的消息内容
            context_messages (Optional[list[dict[str, str]]]): 对话上下文消息列表，每个消息包含 role 和 content
            persona (str): 说话人人格描述
            tool_set (Optional[ToolSet]): 可用的工具集，包含 tts_enhance 工具
            adapter (Any): 供应商适配器，用于末轮非法参数时的清洗兜底；可为 None
            max_attempts (int): 最大尝试次数（含首次）

        Returns:
            Optional[dict[str, Any]]: 成功时返回包含 TTS 参数的字典，失败时返回 None
            返回的字典可能包含以下键：
                - text (str): 需要转换为语音的文本内容
                - 其他 TTS 相关参数（经工具校验 / 清洗后）
        """
        try:
            session_id = event.unified_msg_origin

            provider = self._resolve_provider(session_id)
            if provider is None:
                return None

            tool = tool_set.get_tool("tts_enhance") if tool_set else None
            # 真实对话历史：仅用于把上下文平铺进 prompt。
            # 插件走 prompt 模式而非 contexts 模式。
            history = list(context_messages) if context_messages else []
            # 重试时以结构化方式回传给模型的工具结果（role:"tool" 对象级循环）。
            # 为 None 表示首次调用或无需回传。
            pending_tool_result = None

            for attempt in range(max_attempts):
                prompt = self._build_prompt(persona, history, user_message)
                logger.debug(f"TTS SubAgent: 用户提示（第 {attempt + 1} 次）：\n{prompt}")

                try:
                    response = await provider.text_chat(
                        prompt=prompt,
                        session_id=session_id,
                        system_prompt=system_prompt,
                        func_tool=tool_set,
                        tool_calls_result=pending_tool_result,
                    )
                except Exception as e:
                    logger.warning(f"SubAgent LLM 调用异常 (尝试 {attempt + 1}): {e}")
                    # 基础设施异常：模型本轮未产生任何内容，直接重试即可。
                    if attempt == max_attempts - 1:
                        return None
                    pending_tool_result = None
                    continue

                # 无工具调用 → 纯文本降级（或空响应则重试）
                has_tool = bool(getattr(response, "tools_call_name", None))
                if not has_tool:
                    text = (getattr(response, "completion_text", "") or "").strip()
                    if text:
                        return {"text": text}
                    if attempt == max_attempts - 1:
                        return None
                    # 模型未发起工具调用：以用户侧指令轻量提示（非工具结果语义）
                    history.append(
                        {
                            "role": "user",
                            "content": "请务必调用 tts_enhance 工具来合成语音，不要直接返回文本。",
                        }
                    )
                    pending_tool_result = None
                    continue

                # 定位 tts_enhance 调用
                names = response.tools_call_name
                args_list = response.tools_call_args or []
                ids = getattr(response, "tools_call_ids", None) or []
                tts_args: dict = {}
                tts_id = "call_0"
                found = False
                for idx, name in enumerate(names):
                    if name == "tts_enhance":
                        tts_args = args_list[idx] if idx < len(args_list) else {}
                        tts_id = ids[idx] if idx < len(ids) else f"call_{idx}"
                        found = True
                        break
                if not found:
                    logger.warning(f"SubAgent 调用了未预期的工具: {names}")
                    return None

                # 无 handler（理论上不会发生）：直接返回原始参数兜底
                if tool is None or tool.handler is None:
                    return tts_args

                # 真正执行工具 handler，拿到标准 CallToolResult
                try:
                    result = await tool.handler(**tts_args)
                except Exception as e:
                    logger.warning(f"tts_enhance 工具执行异常 (尝试 {attempt + 1}): {e}")
                    if attempt == max_attempts - 1:
                        return None
                    # 工具执行失败属于「工具结果」语义，以 role:"tool" 结构化回灌
                    pending_tool_result = self._build_tool_result(
                        tts_id,
                        tts_args,
                        f"工具执行异常：{e}，请修正参数后重新调用 tts_enhance 工具。",
                    )
                    continue

                is_error, result_text = _extract_tool_result(result)
                if is_error:
                    if attempt == max_attempts - 1:
                        # 末轮仍非法：若有 adapter 则尽力清洗返回，否则放弃
                        if adapter is not None:
                            return adapter.sanitize_params(tts_args)
                        return None
                    # 参数校验失败：以 role:"tool" 结构化回灌，供 LLM 修正后重试
                    pending_tool_result = self._build_tool_result(
                        tts_id, tts_args, result_text
                    )
                    continue

                try:
                    return json.loads(result_text) if result_text else tts_args
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"tts_enhance 工具返回无法解析: {result_text}")
                    return tts_args

            return None

        except Exception as e:
            logger.error(f"TTS SubAgent 调用失败: {e}")
            logger.debug(traceback.format_exc())
            return None
