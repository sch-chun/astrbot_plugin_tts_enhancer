"""百炼 CosyVoice V3.5 适配器"""

from ._bailian_speech_synthesizer import BailianSpeechSynthesizerAdapter


class BailianCosyVoiceV3_5Adapter(BailianSpeechSynthesizerAdapter):
    DISPLAY_NAME = "百炼 Cosyvoice-V3.5"
    """百炼 CosyVoice V3.5 适配器"""

    MODEL_NAME = "cosyvoice-v3.5"
    VALID_LANGS = ["zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi"]
    