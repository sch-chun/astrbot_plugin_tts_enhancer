from abc import ABC, abstractmethod
from pathlib import Path
import re

from typing import Optional

from astrbot.api import logger
from astrbot.core.agent.tool import FunctionTool


class TTSProviderAdapter(ABC):
    """TTS 供应商适配器抽象基类
    
    该类定义了所有 TTS 供应商适配器必须实现的接口和基础功能。
    每个具体的 TTS 供应商都需要继承这个基类并实现所有抽象方法。
    
    主要功能：
    - 提供 TTS 参数验证和清洗
    - 管理供应商特定的文档内容
    - 定义与 SubAgent 交互的接口
    - 提供 API 调用的抽象方法
    
    抽象方法：
    - get_subagent_system_prompt: 生成 SubAgent 的系统提示词
    - get_tool_schema: 返回 TTS 参数增强的 Function Tool
    - parse_subagent_response: 解析 SubAgent 返回的数据
    - call_api: 调用具体的 TTS API
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

    # ————————————————————————

    # ———————— 参数验证 ————————

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

    # ———————— 音色管理 ————————

    async def create_voice(self, params: dict) -> dict:
        """创建语音

        调用 TTS API 进行语音合成，并返回合成结果。

        Args:
            params (dict): TTS 参数字典

        Returns:
            dict: 包含合成结果的字典
        """
        raise NotImplementedError

    async def list_voice(self, **kwargs) -> dict:
        """列出语音

        调用 TTS API 列出已有的语音，并返回结果。

        Args:
            由供应商自定义

        Returns:
            dict: 包含语音列表结果的字典
        """
        raise NotImplementedError

    async def delete_voice(self, **kwargs) -> bool:
        """删除语音

        调用 TTS API 删除指定的语音，并返回删除结果。

        Args:
            由供应商自定义

        Returns:
            bool: 删除结果，True 表示删除成功，False 表示删除失败
        """
        raise NotImplementedError

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
        
        默认 CJK 统一汉字（0x4E00-0x9FFF）按2字符。
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

            # CJK 统一汉字范围
            if 0x4E00 <= ord(ch) <= 0x9FFF:
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