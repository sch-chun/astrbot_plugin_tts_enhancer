"""TTS Provider 适配器抽象基类。"""

from abc import ABC, abstractmethod


class TTSProviderAdapter(ABC):
    """TTS 供应商适配器抽象基类。"""

    def __init__(self, config: dict = None):
        self.config = config or {}

    @abstractmethod
    def get_subagent_system_prompt(self, context_messages: list[dict], raw_tts_text: str) -> str:
        pass

    @abstractmethod
    def parse_subagent_response(self, response_text: str) -> dict:
        pass

    @abstractmethod
    async def call_api(self, text: str, raw_params: dict, config: dict) -> str:
        pass

    def _get_provider_config(self, config: dict, key: str, default=None):
        provider_name = self.provider_name
        providers_config = config.get("providers_config", {})
        provider_cfg = providers_config.get(provider_name, {})
        return provider_cfg.get(key, config.get(key, default))

    @property
    @abstractmethod
    def provider_name(self) -> str:
        pass

    @staticmethod
    def _try_parse_json(text: str) -> dict | None:
        import json
        import re

        text = text.strip()
        try:
            return json.loads(text)
        except Exception:
            pass

        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                pass

        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass

        return None
