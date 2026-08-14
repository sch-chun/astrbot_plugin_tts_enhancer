"""MiniMax TTS 适配器。"""

import httpx
from datetime import datetime
from pathlib import Path

from astrbot.core import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .base import TTSProviderAdapter


class MiniMaxAdapter(TTSProviderAdapter):
    """MiniMax TTS 供应商适配器。"""

    _API_ENDPOINT = (
        "https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/aigc/multimodal-generation/generation"
    )

    _EMOTIONS = [
        "happy", "sad", "angry", "scary", "hurt", "depressed",
        "disgusted", "surprised", "touching", "fear", "sweet",
        "cool", "crazy", "serious", "neutral",
    ]

    @property
    def provider_name(self) -> str:
        return "minimax"

    def get_subagent_system_prompt(self, context_messages: list[dict], raw_tts_text: str) -> str:
        emotions_list = ", ".join(self._EMOTIONS)

        return f"""你是语音合成助手，正在为 MiniMax Speech API 准备参数。

该模型通过结构化 JSON 控制语音的情感、语速、音调和音量。

【支持的 emotion 值】
{emotions_list}

【输出格式】
返回严格的 JSON 对象：
{{
  "text": "原文内容",
  "emotion": "happy",
  "speed": 1.0,
  "pitch": 0,
  "vol": 1.0
}}

【参数说明】
- emotion: 从上方列表选择
- speed: 语速 0.5-2.0，1.0 为正常
- pitch: 音调 -12 到 12，0 为正常
- vol: 音量 0-10，1.0 为正常

【规则】
1. 根据对话上下文选择最合适的情感
2. 语速和音调应与情感匹配
3. 保持原文内容不变
4. 只返回 JSON

请为以下文本生成语音参数：「{raw_tts_text}」"""

    def parse_subagent_response(self, response_text: str) -> dict:
        parsed = self._try_parse_json(response_text)
        if parsed and "text" in parsed:
            return parsed
        return {"text": response_text.strip()}

    async def call_api(self, text: str, raw_params: dict, config: dict) -> str:
        api_key = self._get_provider_config(config, "api_key", "")
        workspace_id = self._get_provider_config(config, "workspace_id", "")
        model = self._get_provider_config(config, "model", "MiniMax/speech-2.8-hd")
        voice_id = self._get_provider_config(config, "voice_id", "male-qn-qingse")
        format_type = self._get_provider_config(config, "format", "mp3")
        sample_rate = self._get_provider_config(config, "sample_rate", 32000)

        if not api_key or not workspace_id:
            logger.error("MiniMax TTS: api_key 或 workspace_id 未配置")
            return ""

        url = self._API_ENDPOINT.format(workspace_id=workspace_id)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        voice_setting = {
            "voice_id": voice_id,
            "speed": raw_params.get("speed", 1.0),
            "vol": raw_params.get("vol", 1.0),
            "pitch": raw_params.get("pitch", 0),
            "emotion": raw_params.get("emotion", "neutral"),
        }

        payload = {
            "model": model,
            "input": {
                "text": text,
                "voice_setting": voice_setting,
                "audio_setting": {
                    "sample_rate": sample_rate,
                    "bitrate": 128000,
                    "format": format_type,
                    "channel": 1,
                },
            },
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            audio_data = data.get("output", {}).get("audio", {})
            audio_url = audio_data.get("url")
            audio_b64 = audio_data.get("data")

            if audio_b64:
                return await self._save_base64_audio(audio_b64, format_type)
            elif audio_url:
                return await self._download_audio(audio_url, format_type)
            else:
                logger.error(f"MiniMax API 未返回音频: {data}")
                return ""

        except Exception as e:
            logger.error(f"MiniMax 合成失败: {e}")
            return ""

    async def _download_audio(self, url: str, fmt: str) -> str:
        try:
            data_dir = Path(get_astrbot_data_path()) / "tts_enhancer"
            data_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filepath = data_dir / f"tts_{timestamp}.{fmt}"

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                filepath.write_bytes(resp.content)

            logger.info(f"MiniMax 音频已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"下载音频失败: {e}")
            return ""

    async def _save_base64_audio(self, b64_data: str, fmt: str) -> str:
        try:
            import base64

            data_dir = Path(get_astrbot_data_path()) / "tts_enhancer"
            data_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filepath = data_dir / f"tts_{timestamp}.{fmt}"

            filepath.write_bytes(base64.b64decode(b64_data))
            logger.info(f"MiniMax 音频已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"保存 base64 音频失败: {e}")
            return ""
