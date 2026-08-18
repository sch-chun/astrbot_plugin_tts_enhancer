from abc import ABC, abstractmethod
from pathlib import Path

from typing import Any, Optional
from astrbot.core.agent.tool import FunctionTool


class TTSProviderAdapter(ABC):
    """
    TTS 供应商适配器抽象基类
    
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

    # ———————— 语音合成 ————————

    def __init__(self, entry: dict):
        """
        初始化 TTS 供应商适配器
        
        Args:
            entry (dict): 包含 TTS 供应商配置信息的字典，必须包含 __template_key 字段
                         用于标识和加载对应的文档模板
        """
        self.entry = entry
        self.template_key = entry.get("__template_key", "unknown")
        self.docs_content = self._load_docs()

    def _load_docs(self) -> str:
        """
        根据 template_key 加载对应的 Markdown 文档
        
        从 docs 目录下加载与 template_key 同名的 markdown 文档文件。
        如果文档不存在，返回空字符串。
        
        Returns:
            str: 文档内容字符串，如果文档不存在则返回空字符串
        """
        docs_path = Path(__file__).parent / "docs" / f"{self.template_key}.md"
        if docs_path.exists():
            return docs_path.read_text(encoding="utf-8")
        return ""

    @abstractmethod
    def get_subagent_system_prompt(self, raw_tts_text: str) -> str:
        """
        生成 SubAgent 的系统提示词
        
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
        """
        返回用于 TTS 参数增强的 Function Tool
        
        返回一个 FunctionTool 实例，用于增强 TTS 参数。
        如果适配器不支持 Function Calling，可以返回 None 或重写此方法。
        
        Returns:
            Optional[FunctionTool]: FunctionTool 实例或 None
        """
        pass

    @abstractmethod
    def parse_subagent_response(self, response_data: Any) -> dict:
        """
        解析 SubAgent 返回的数据
        
        将 SubAgent 返回的响应数据解析为标准格式。
        
        Args:
            response_data (Any): SubAgent 返回的原始响应数据
            
        Returns:
            dict: 解析后的数据字典，包含处理后的 TTS 参数
        """
        pass

    @abstractmethod
    async def call_api(self, text: str, raw_params: dict, config: dict) -> str:
        """
        调用 TTS API
        
        调用具体的 TTS 服务 API 进行语音合成。
        这是一个异步方法，需要实现具体的 API 调用逻辑。
        
        Args:
            text (str): 要合成的文本内容
            raw_params (dict): 原始的 TTS 参数
            config (dict): API 配置信息
            
        Returns:
            str: 合成后的音频文件路径或音频内容
        """
        pass

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """
        验证 TTS 参数是否合法
        
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
        """
        清洗 TTS 参数
        
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
        """
        创建语音

        调用 TTS API 进行语音合成，并返回合成结果。

        Args:
            params (dict): TTS 参数字典

        Returns:
            dict: 包含合成结果的字典
        """
        raise NotImplementedError

    async def list_voice(self, **kwargs) -> dict:
        """
        列出语音

        调用 TTS API 列出已有的语音，并返回结果。

        Args:
            由供应商自定义

        Returns:
            dict: 包含语音列表结果的字典
        """
        raise NotImplementedError

    async def delete_voice(self, **kwargs) -> bool:
        """
        删除语音

        调用 TTS API 删除指定的语音，并返回删除结果。

        Args:
            由供应商自定义

        Returns:
            bool: 删除结果，True 表示删除成功，False 表示删除失败
        """
        raise NotImplementedError

    # ————————————————————————
