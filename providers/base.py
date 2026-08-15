from abc import ABC, abstractmethod
from pathlib import Path


class TTSProviderAdapter(ABC):
    def __init__(self, entry: dict):
        self.entry = entry
        self.template_key = entry.get("__template_key", "unknown")
        self.docs_content = self._load_docs()

    def _load_docs(self) -> str:
        """根据 template_key 加载对应的 Markdown 文档。"""
        docs_path = Path(__file__).parent / "docs" / f"{self.template_key}.md"
        if docs_path.exists():
            return docs_path.read_text(encoding="utf-8")
        return ""

    @abstractmethod
    def get_subagent_system_prompt(self, raw_tts_text: str) -> str:
        pass

    @abstractmethod
    def parse_subagent_response(self, response_data) -> dict:
        pass

    @abstractmethod
    async def call_api(self, text: str, raw_params: dict, config: dict) -> str:
        pass

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass
    