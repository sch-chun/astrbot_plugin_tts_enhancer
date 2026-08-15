from abc import ABC, abstractmethod
from pathlib import Path

from typing import Any, Optional
from astrbot.core.agent.tool import FunctionTool


class TTSProviderAdapter(ABC):
    """TTS 供应商适配器抽象基类"""
    def __init__(self, entry: dict):
        self.entry = entry
        self.template_key = entry.get("__template_key", "unknown")
        self.docs_content = self._load_docs()

    def _load_docs(self) -> str:
        """根据 template_key 加载对应的 Markdown 文档"""
        docs_path = Path(__file__).parent / "docs" / f"{self.template_key}.md"
        if docs_path.exists():
            return docs_path.read_text(encoding="utf-8")
        return ""

    @abstractmethod
    def get_subagent_system_prompt(self, raw_tts_text: str) -> str:
        """生成 SubAgent 的系统提示词"""
        pass

    @abstractmethod
    def get_tool_schema(self) -> Optional[FunctionTool]:
        """返回用于 TTS 参数增强的 Function Tool
        
        若适配器不支持 Function Calling，可返回 None 或重写此方法
        """
        pass

    @abstractmethod
    def parse_subagent_response(self, response_data: Any) -> dict:
        """解析 SubAgent 返回的数据"""
        pass

    @abstractmethod
    async def call_api(self, text: str, raw_params: dict, config: dict) -> str:
        """调用 TTS API"""
        pass

    def validate_params(self, params: dict) -> tuple[bool, str]:
        """验证参数是否合法。返回（是否合法，错误信息）"""
        return True, ""

    def sanitize_params(self, params: dict) -> dict:
        """清洗参数，确保参数符合 API 要求"""
        return params
