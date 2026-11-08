"""百炼 Qwen Audio 3.1 TTS 适配器"""

from ._bailian_speech_synthesizer import BailianSpeechSynthesizerAdapter


class BailianQwenAudio3_1TTSAdapter(BailianSpeechSynthesizerAdapter):
    DISPLAY_NAME = "百炼 Qwen Audio 3.1 TTS"
    """百炼 Qwen Audio 3.1 TTS 适配器"""

    MODEL_NAME = "qwen-audio-3.1-tts"
    