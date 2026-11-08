from abc import ABC, abstractmethod
from pathlib import Path
import json
import re
import unicodedata

from typing import Optional

from astrbot.api import logger
from astrbot.core.agent.tool import FunctionTool
from mcp.types import CallToolResult, TextContent


class TTSProviderAdapter(ABC):
    """TTS 供应商适配器抽象基类

    该类定义了所有 TTS 供应商适配器必须实现的「核心」接口和基础功能：
    参数验证/清洗、能力文档加载、与 SubAgent 交互的工具构建、以及合成 API 调用。

    抽象方法（所有适配器必须实现）：
    - get_subagent_system_prompt: 生成 SubAgent 的系统提示词
    - get_tool_schema: 返回 TTS 参数增强的 Function Tool
    - call_api: 调用具体的 TTS API

    可选能力（见 ``providers.mixins``，按需多继承，缺失即视为不支持）：
    - VoiceManageable: 音色创建 / 列表 / 删除；
    - FileManageable: 供应商侧文件上传 / 列表 / 获取 / 删除。
    基类不再为可选能力提供 NotImplementedError 兜底，让「不支持」成为结构上的
    能力缺失，路由侧用 ``hasattr`` 检测并返回 501。
    """

    # 文档文件名（不含 .md 后缀）。子类可覆盖，实现多供应商共享同一份能力文档。
    # 默认回退到 __template_key。
    DOCS_KEY: Optional[str] = None

    # ———————— 语音合成 ————————

    def __init__(self, entry: dict) -> None:
        """初始化 TTS 供应商适配器
        
        Args:
            entry (dict): 包含 TTS 供应商配置信息的字典，必须包含 __template_key 字段
                         用于标识和加载对应的文档模板
        """
        self.entry = entry
        self.template_key = entry.get("__template_key", "unknown")
        self.docs_content = self._load_docs()

    @property
    def docs_key(self) -> str:
        """返回用于加载能力文档的文件名（不含后缀）。

        优先使用子类声明的 DOCS_KEY，缺省回退到 template_key。
        """
        return self.DOCS_KEY or self.template_key

    def _load_docs(self) -> str:
        """根据 docs_key 加载对应的 Markdown 文档
        
        从 docs 目录下加载与 docs_key 同名的 markdown 文档文件。
        如果文档不存在，返回空字符串。
        
        Returns:
            str: 文档内容字符串，如果文档不存在则返回空字符串
        """
        docs_path = Path(__file__).parent / "docs" / f"{self.docs_key}.md"
        if docs_path.exists():
            return docs_path.read_text(encoding="utf-8")
        logger.warning(f"文档文件 {docs_path} 不存在，该供应商增强能力可能将不可用")
        return ""

    @abstractmethod
    def get_subagent_system_prompt(self) -> str:
        """生成 SubAgent 的系统提示词
        
        根据原始 TTS 文本生成适合 SubAgent 使用的系统提示词。
        提示词应该包含必要的上下文信息和指导。
        
        Args:
            raw_tts_text (str): 原始的 TTS 文本内容
            
        Returns:
            str: 生成的系统提示词
        """
        pass

    @abstractmethod
    def get_tool_schema(self) -> Optional[FunctionTool]:
        """返回用于 TTS 参数增强的 Function Tool
        
        返回一个 FunctionTool 实例，用于增强 TTS 参数。
        如果适配器不支持 Function Calling，可以返回 None 或重写此方法。
        
        Returns:
            Optional[FunctionTool]: FunctionTool 实例或 None
        """
        pass

    async def _handle_enhance_tool(self, **kwargs) -> CallToolResult:
        """tts_enhance 工具的实际 handler。

        由 ``build_enhance_tool`` 挂到 ``FunctionTool.handler``。
        合法返回 ``isError=False``（清洗后的参数 JSON）；
        非法返回 ``isError=True``（中文错误提示）。
        TTSSubAgent 据此驱动重试。
        """
        is_valid, err = self.validate_params(kwargs)
        if is_valid:
            payload = json.dumps(self.sanitize_params(kwargs), ensure_ascii=False)
            return CallToolResult(
                isError=False, content=[TextContent(type="text", text=payload)]
            )
        return CallToolResult(
            isError=True,
            content=[
                TextContent(
                    type="text",
                    text=f"参数格式错误：{err}。请修正后重新调用 tts_enhance 工具。",
                )
            ],
        )

    def build_enhance_tool(self, description: str, parameters: dict) -> FunctionTool:
        """构造 tts_enhance 工具并挂上校验 handler。

        统一固定工具名，避免各适配器重复写 FunctionTool 与接线。
        """
        tool = FunctionTool(
            name="tts_enhance", description=description, parameters=parameters
        )
        tool.handler = self._handle_enhance_tool
        return tool

    @abstractmethod
    async def call_api(
        self, text: str, raw_params: dict, config: dict, voice_id: Optional[str] = None
    ) -> str:
        """调用 TTS API
        
        调用具体的 TTS 服务 API 进行语音合成。
        这是一个异步方法，需要实现具体的 API 调用逻辑。
        
        Args:
            text (str): 要合成的文本内容
            raw_params (dict): 原始的 TTS 参数
            config (dict): API 配置信息
            voice_id (Optional[str]): 显示传入的音色 ID，覆盖 config 中的音色 ID 用于音色预览等功能
            
        Returns:
            str: 合成后的音频文件路径或音频内容
        """
        pass

    async def ensure_catalog_ready(self, timeout: int | None = None) -> None:
        """合成前等待供应商预热（如目录拉取）就绪。

        基类默认无操作；需要预热的供应商（如 ElevenLabs v4 的 audio_effects 目录）
        应覆写此方法，按配置超时有界等待，超时则不暴露对应参数但继续后台预热。
        ``tts_service`` 在构建工具 schema / SubAgent 提示词前统一调用，对所有适配
        器安全（无操作适配器零成本）。
        """
        return None

    # ————————————————————————

    # ———————— 参数验证 ————————

    @staticmethod
    def _as_float(value) -> float | None:
        """将参数值安全转换为 float。

        接受 int / float / 可解析的字符串；排除 bool；无法解析时返回 None。

        Args:
            value: 待转换的参数值，类型未知。

        Returns:
            转换成功返回 float；bool 或无法解析的值返回 None。
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                return None
        return None

    @staticmethod
    def _as_int(value) -> int | None:
        """将参数值安全转换为 int（整数语义）。

        接受 int 与整型浮点（如 80.0）；排除 bool；非整型浮点（80.5）
        与无法解析的字符串返回 None。

        Args:
            value: 待转换的参数值，类型未知。

        Returns:
            转换成功返回 int；bool、非整型数值或无法解析的值返回 None。
        """
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value) if value.is_integer() else None
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return None
        return None

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """验证 TTS 参数是否合法
        
        对传入的 TTS 参数进行验证，确保参数符合要求。
        子类可以重写此方法实现具体的参数验证逻辑。
        
        Args:
            params (dict): 需要验证的 TTS 参数字典
            
        Returns:
            tuple[bool, str]: 验证结果，第一个元素表示是否验证通过，
                              第二个元素是错误信息（验证失败时）或空字符串
        """
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """清洗 TTS 参数
        
        对传入的 TTS 参数进行清洗和规范化处理，确保参数符合 API 要求。
        子类可以重写此方法实现具体的参数清洗逻辑。
        
        Args:
            params (dict): 需要清洗的 TTS 参数字典
            
        Returns:
            dict: 清洗后的参数字典
        """
        return params

    # ————————————————————————

    # ———————— 通用校验工具 ————————

    @staticmethod
    def validate_voice_id(
        voice_id: str,
        min_len: int = 8,
        max_len: int = 256,
        pattern: str = r'^[A-Za-z][A-Za-z0-9\-_]*[A-Za-z0-9]$'
    ) -> None:
        """校验 voice_id 格式
        
        默认：8-256个字符，以字母开头，只允许字母、数字、连字符和下划线，以字母或数字结尾。
        可通过参数自定义规则。

        Args:
            voice_id (str): 需要校验的 voice_id
            min_len (int): voice_id 最小长度，默认 8
            max_len (int): voice_id 最大长度，默认 256
            pattern (str): voice_id 正则表达式模式
        """
        if not voice_id:
            return  # 允许空值，由调用方决定是否必填
        if not (min_len <= len(voice_id) <= max_len):
            raise ValueError(f"voice_id 长度必须为 {min_len} ~ {max_len}，当前 {len(voice_id)}")
        if not re.match(pattern, voice_id):
            raise ValueError(f"voice_id 格式不合法，必须匹配正则表达式：{pattern}")

    def _count_text_chars(self, text: str) -> int:
        """计算文本字符数。

        按东亚宽度规则计数：宽字符（W）与全角字符（F）计 2，其余计 1。
        子类可覆盖此方法以实现不同的计数规则。

        Args:
            text (str): 需要计算的文本内容

        Returns:
            int: 文本字符数
        """
        if not text:
            return 0
        count = 0
        for ch in text:

            # 'W' = 宽（CJK 汉字/假名/韩文/多数 emoji），'F' = 全角（全角标点与全角字母）
            if unicodedata.east_asian_width(ch) in ("W", "F"):
                count += 2
            else:
                count += 1
        return count

    def validate_text_length(
        self,
        text: Optional[str],
        min_len: int = 0,
        max_len: int = 200,
        field_name: str = "文本"
    ) -> None:
        """校验文本长度（使用 _count_text_chars 方法计算）
        
        Args:
            text (Optional[str]): 需要校验的文本内容
            min_len (int): 文本最小长度，默认 0
            max_len (int): 文本最大长度，默认 200
            field_name (str): 字段名称，用于错误提示，默认 "文本"
        """
        if not text:
            return

        char_count = self._count_text_chars(text)
        if not (min_len <= char_count <= max_len):
            raise ValueError(f"{field_name} 长度必须为 {min_len} ~ {max_len}，当前 {char_count}")