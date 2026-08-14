"""阿里云 Qwen-Audio-TTS 适配器。"""

import httpx
from datetime import datetime
from pathlib import Path

from astrbot.core import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .base import TTSProviderAdapter


class AliQwenAudioAdapter(TTSProviderAdapter):
    """阿里云 Qwen-Audio-TTS 供应商适配器。"""

    _API_ENDPOINT = (
        "https://{workspace_id}.cn-beijing.maas.aliyuncs.com"
        "/api/v1/services/audio/tts/SpeechSynthesizer"
    )

    CONTROL_TAGS = [
        "[sad]", "[amazed]", "[deep and loud shouting]", "[trembling]",
        "[angry]", "[excited]", "[sarcastic]", "[curious]",
        "[like dracula]", "[bored]", "[tired]", "[singing]",
        "[scornful]", "[shouting]", "[asmr]", "[panicked]",
        "[mischievously]", "[empathetic]", "[whispers]", "[reluctantly]",
        "[crying]", "[serious]", "[very slowly]", "[very fast]",
    ]

    SOUND_TAGS = [
        "[gasp]", "[sighing]", "[clears throat]", "[giggles]",
        "[laughing]", "[cough]", "[snorts]",
    ]

    @property
    def provider_name(self) -> str:
        return "ali_qwen_audio"

    def get_subagent_system_prompt(self, context_messages: list[dict], raw_tts_text: str) -> str:
        tags_list = "\n".join(f"  - {tag}" for tag in self.CONTROL_TAGS)
        sound_list = "\n".join(f"  - {tag}" for tag in self.SOUND_TAGS)

        return f"""你是语音合成助手，正在为阿里云 Qwen-Audio-TTS 准备语音文本。

该模型支持在文本中直接嵌入情感标签控制语音表现，标签作用于其后的文本，直到遇到下一个标签。

【控制类标签】（设定情感/风格，作用于后续文本）：
{tags_list}

【富语言类标签】（在当前位置插入拟声效果，不影响前后文本）：
{sound_list}

【使用规则】
1. 根据对话上下文的情感，为文本添加合适的情感标签
2. 可在合适位置插入富语言标签（如笑声、叹息）
3. 标签直接嵌入文本中，不要有任何额外解释或标记
4. 保持原文内容不变，只添加标签
5. 不要添加 <tts> 标签，只返回纯文本

【示例】
输入：今天天气真好
输出：[excited]今天天气真好

输入：我很难过，因为考试没考好
输出：[sad]我很难过，因为考试没考好[sighing]

输入：太棒了！我们一起出去玩吧
输出：[excited]太棒了！[laughing]我们一起出去玩吧

请增强以下文本：「{raw_tts_text}」
只返回增强后的纯文本，不要有任何额外解释。"""

    def parse_subagent_response(self, response_text: str) -> dict:
        text = response_text.strip()
        text = text.replace("<tts>", "").replace("</tts>", "")
        return {"text": text}

    async def call_api(self, text: str, raw_params: dict, config: dict) -> str:
        api_key = self._get_provider_config(config, "api_key", "")
        workspace_id = self._get_provider_config(config, "workspace_id", "")
        model = self._get_provider_config(config, "model", "qwen-audio-3.0-tts-flash")
        voice = self._get_provider_config(config, "voice", "longanhuan_v3.6")
        instruction = self._get_provider_config(config, "instruction", "")
        format_type = self._get_provider_config(config, "format", "wav")
        sample_rate = self._get_provider_config(config, "sample_rate", 24000)

        if not api_key or not workspace_id:
            logger.error("Qwen-Audio-TTS: api_key 或 workspace_id 未配置")
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
                logger.error(f"Qwen-Audio-TTS API 未返回音频 URL: {data}")
                return ""

            return await self._download_audio(audio_url, format_type)

        except Exception as e:
            logger.error(f"Qwen-Audio-TTS 合成失败: {e}")
            return ""

    async def _download_audio(self, url: str, fmt: str) -> str:
        try:
            data_dir = Path(get_astrbot_data_path()) / "tts_enhancer"
            data_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            filename = f"tts_{timestamp}.{fmt}"
            filepath = data_dir / filename

            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                filepath.write_bytes(resp.content)

            logger.info(f"TTS 音频已保存: {filepath}")
            return str(filepath)

        except Exception as e:
            logger.error(f"下载音频失败: {e}")
            return ""
