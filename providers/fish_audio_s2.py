"""Fish Audio S2 / S2-Pro TTS 适配器。"""

from typing import Any

from astrbot.api import logger

from ._fish_audio import MAX_SPEED, MIN_SPEED, S2_MODELS, FishAudioAdapter


class FishAudioS2Adapter(FishAudioAdapter):
    DISPLAY_NAME = "Fish Audio S2"
    SUPPORTED_MODELS = S2_MODELS

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        logger.debug(
            f"Initialized FishAudioS2Adapter with template_key={self.template_key}"
        )

    def get_tool_schema(self) -> Any:
        return self.build_enhance_tool(
            "为 Fish Audio 语音合成提供增强参数。"
            "情绪/风格请用方括号标记直接写进 text（如 [happy]、[warm and happy]），"
            "可跨句改变；音效或停顿可用 [laughing]、[break] 等标记；"
            "语速、音量与语言用对应字段控制。"
            "官方参考标签枚举："
            "基础情绪 [happy]、[sad]、[angry]、[excited]、[calm]、[nervous]、"
            "[confident]、[surprised]、[satisfied]、[delighted]、[scared]、"
            "[worried]、[upset]、[frustrated]、[depressed]、[empathetic]、"
            "[embarrassed]、[disgusted]、[moved]、[proud]、[relaxed]、"
            "[grateful]、[curious]、[sarcastic]；"
            "高级情绪 [disdainful]、[unhappy]、[anxious]、[hysterical]、"
            "[indifferent]、[uncertain]、[doubtful]、[confused]、[disappointed]、"
            "[regretful]、[guilty]、[ashamed]、[jealous]、[envious]、[hopeful]、"
            "[optimistic]、[pessimistic]、[nostalgic]、[lonely]、[bored]、"
            "[contemptuous]、[sympathetic]、[compassionate]、[determined]、[resigned]；"
            "语调 [in a hurry tone]、[shouting]、[screaming]、[whispering]、"
            "[soft tone]、[emphasis]；"
            "音效 [laughing]、[chuckling]、[sobbing]、[crying loudly]、[sighing]、"
            "[groaning]、[panting]、[gasping]、[yawning]、[snoring]、[clear throat]；"
            "氛围与停顿 [audience laughing]、[background laughter]、[crowd laughing]、"
            "[break]、[long-break]。以上为参考枚举，仍可写自然语言描述。",
            {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": (
                            "合成文本。情绪/风格标记直接写进文本，"
                            "如 '[happy] 今天天气真好'、'[angry][shouting] 出去！'；"
                            "支持自然语言描述（'[warm and happy]'）与多标记组合（每句最多约 3 个）。"
                        ),
                    },
                    "speed": {
                        "type": "number",
                        "description": f"语速，范围 {MIN_SPEED}~{MAX_SPEED}，默认 1.0。",
                    },
                    "volume": {
                        "type": "number",
                        "description": "音量，单位 dB，默认 0；正数更响、负数更轻。",
                    },
                    "language": {
                        "type": "string",
                        "description": (
                            "BCP-47 语言标签，"
                            "仅控制数字/日期/单位的口语化读法，不改变口音或音质。"
                        ),
                    },
                },
                "required": ["text"],
            },
        )

    def get_subagent_system_prompt(self) -> str:
        return (
            "你是语音合成参数优化助手，负责为 Fish Audio 准备合成参数。"
            "Fish Audio 通过文本内联方括号标记表达情绪与风格，请调用 `tts_enhance` 工具：\n"
            "- text 必填，为待合成文本；情绪/风格标记（如 [happy]、[warm and happy]）"
            "直接写进 text，可跨句改变，每句最多约 3 个；\n"
            "- 笑声、叹气等音效和 [break]/[long-break] 停顿放在实际发生的位置；\n"
            f"- speed 可选，语速 {MIN_SPEED}~{MAX_SPEED}；\n"
            "- volume 可选，音量 dB（默认 0，正数更响、负数更轻）；\n"
            "- language 可选，BCP-47 标签，仅控制数字/日期/单位读法（不影响口音/音质）。\n"
            "根据对话内容与情绪，为合适的句子加 [标记] 来表达语气/情绪。直接调用工具，不要额外解释。\n\n"
            "参考能力说明：\n"
            f"{self.docs_content}"
        )
