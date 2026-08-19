import json
from pathlib import Path
import base64
import time

from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api.event.filter import on_llm_request, on_decorating_result
from astrbot.api.message_components import Plain, Record
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.agent.tool import ToolSet
from astrbot.core import logger
from astrbot.api.web import request, json_response, error_response, file_response
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .src.config import TTSEnhancerConfig
from .src.sub_agent import TTSSubAgent
from .src.tts_parser import split_by_tts_tags, TTS_START_TAG, TTS_END_TAG
from .src.file_server import TempFileServer, add_server, get_server, remove_server
from .providers import ProviderFactory

from typing import Optional


class TTSEnhancerPlugin(Star):
    """
    TTS Enhancer —— 多供应商智能语音合成插件

    架构：主模型输出 <tts> 标签 → SubAgent 增强语音参数 → Provider Adapter 调用 API。
    """
    def __init__(self, context: Context, config: Optional[dict] = None):
        super().__init__(context, config)
        self.config = TTSEnhancerConfig(config)
        self.providers = self.config.get_providers()
        self.sub_agent = TTSSubAgent(context, config)

        self._register_routes()

        self.plugin_data_path = Path(get_astrbot_data_path()) / "plugin_data" / self.name
        (self.plugin_data_path / "uploads").mkdir(parents=True, exist_ok=True)
        (self.plugin_data_path / "audio").mkdir(parents=True, exist_ok=True)
