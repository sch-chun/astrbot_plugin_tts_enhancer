"""Fish Audio Drama 3 TTS 适配器。"""

from typing import Any

from ._fish_audio import FishAudioAdapter


class FishAudioDrama3Adapter(FishAudioAdapter):
    DISPLAY_NAME = "Fish Audio Drama 3"
    MODEL_NAME = "drama-3"
    SUPPORTS_LOUDNESS_NORMALIZATION = False

    def get_tool_schema(self) -> Any:
        return self.build_enhance_tool(
            "为 Fish Audio Drama 3 语音合成提供增强参数。"
            "在 text 中用方括号自然语言指导表演、音效和停顿，"
            "用成对标签控制局部表演。"
            "支持的成对标签：<whisper>、<emphasis>、<soft>、<fast>、<slow>、"
            "<stress>、<forceful>。"
            "实验性局部语言切换标签示例：<french>、<spanish>、<german>、"
            "<japanese>、<chinese>、<korean>、<italian>。",
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "最终合成文本，保留台词并用方括号加入导演指令，"
                            "如 '[barely holding it together] I am fine. "
                            "[shaky breath] Really.'。"
                            "局部控制可用 <whisper>...</whisper>、"
                            "<emphasis>...</emphasis> 等成对标签。"
                        ),
                    },
                    "speed": {
                        "type": "number",
                        "description": "整体语速，范围 0.5~2.0，默认 1.0；局部速度优先用文本指令。",
                    },
                    "volume": {
                        "type": "number",
                        "description": "整体音量，单位 dB，默认 0；范围 -20~20。",
                    },
                    "language": {
                        "type": "string",
                        "description": (
                            "BCP-47 语言标签，仅控制数字/日期/单位读法，不改变口音；"
                            "混合语种文本建议留空。"
                        ),
                    },
                },
                "required": ["text"],
            },
        )

    def get_subagent_system_prompt(self) -> str:
        return (
            "你是 Fish Audio Drama 3 的配音导演，负责调用 `tts_enhance` 工具生成最终合成文本。\n"
            "- 保留用户台词原意，不擅自改写；导演指令只写在方括号内，不要当作台词朗读。\n"
            "- 用简洁自然语言描述情绪、意图、节奏或对象，可写在句子/短语前，如 "
            "[像是在强忍着眼泪，却努力笑着]、[slow, dangerously quiet]。\n"
            "- 笑声、叹气、呼吸和停顿写在发生位置，如 [shaky breath]、[small laugh]、[short pause]。\n"
            "- 只改变局部时用成对标签：<whisper>、<emphasis>、<soft>、<fast>、<slow>、"
            "<stress>、<forceful>。\n"
            "- 用户明确要求句中切换语言时，可用 <french>...</french> 等语言标签包住对应短语；"
            "该能力实验性，不要主动使用。\n"
            "- 避免堆叠冲突指令；普通聊天不必过度表演。speed/volume 仅在用户要求整体调整时使用。\n"
            "直接调用工具，不要额外解释。\n\n"
            "参考能力说明：\n"
            f"{self.docs_content}"
        )
