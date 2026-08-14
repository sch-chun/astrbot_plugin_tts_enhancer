"""阿里云 CosyVoice 适配器。"""

import httpx
from datetime import datetime
from pathlib import Path

from astrbot.core import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .base import TTSProviderAdapter


class AliCosyVoiceAdapter(TTSProviderAdapter):
    """阿里云 CosyVoice 供应商适配器。"""

    _API_ENDPOINT = (
        "https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/audio/tts/SpeechSynthesizer"
    )

    @property
    def provider_name(self) -> str:
        return "ali_cosyvoice"

    def get_subagent_system_prompt(self, context_messages: list[dict], raw_tts_text: str) -> str:
        return f"""你是语音合成助手，正在为阿里云 CosyVoice 准备语音参数。

该模型支持通过自然语言指令控制语音表现力。

【指令控制能力】
- 描述性别、年龄、音调（高/中/低）、语速（快/中/慢）
- 描述情感（开朗/沉稳/温柔/严肃/活泼/冷静/治愈）
- 描述声音特点（有磁性/清脆/沙哑/圆润/甜美/浑厚/有力）
- 指定方言（如"请用河南话表达"）

【输出格式】
返回 JSON 对象：
{{
  "text": "原文内容（保持不变）",
  "instruction": "自然语言指令描述"
}}

【指令示例】
- "语速较快，带有明显的上扬语调，适合介绍时尚产品"
- "沉稳的中年男性，语速缓慢，音色低沉有磁性"
- "温柔知性的女性，语调平和，适合有声书朗读"
- "请用河南话表达"

【规则】
1. 指令文本不超过 100 字符
2. 指令应具体而非模糊
3. 根据对话上下文判断合适的语音风格
4. 只返回 JSON，不要任何额外解释

请为以下文本生成语音参数：「{raw_tts_text}」"""

    def parse_subagent_response(self, response_text: str) -> dict:
        parsed = self._try_parse_json(response_text)
        if parsed and "text" in parsed:
            return parsed
        return {"text": response_text.strip().replace("<tts>", "").replace("</tts>", ""),
                "instruction": ""}

    async def call_api(self, text: str, raw_params: dict, config: dict) -> str:
        api_key = self._get_provider_config(config, "api_key", "")
        workspace_id = self._get_provider_config(config, "workspace_id", "")
        model = self._get_provider_config(config, "model", "cosyvoice-v3-flash")
        voice = self._get_provider_config(config, "voice", "longanyang")
        format_type = self._get_provider_config(config, "format", "wav")
        sample_rate = self._get_provider_config(config, "sample_rate", 24000)

        instruction = raw_params.get("instruction", "") or self._get_provider_config(config, "instruction", "")

        if not api_key or not workspace_id:
            logger.error("CosyVoice: api_key 或 workspace_id 未配置")
            return ""

        url = self._API_ENDPOINT.format(workspace_id=workspace_id)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "input": {
                "text": text,
                "voice": voice,
                "format": format_type,
                "sample_rate": sample_rate,
            },
        }
        if instruction:
            payload["input"]["instruction"] = instruction

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()

            audio_url = data.get("output", {}).get("audio", {}).get("url")
            if not audio_url:
                logger.error(f"CosyVoice API 未返回音频 URL: {data}")
                return ""

            return await self._download_audio(audio_url, format_type)

        except Exception as e:
            logger.error(f"CosyVoice 合成失败: {e}")
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

            logger.info(f"CosyVoice 音频已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.error(f"下载音频失败: {e}")
            return ""
