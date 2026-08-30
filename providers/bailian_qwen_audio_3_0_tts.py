"""百炼 Qwen Audio 3.0 TTS 适配器"""

from ._bailian_speech_synthesizer import BailianSpeechSynthesizerAdapter


class BailianQwenAudio3_0TTSAdapter(BailianSpeechSynthesizerAdapter):
    """百炼 Qwen Audio 3.0 TTS 适配器"""

    MODEL_NAME = "qwen-audio-3.0-tts"