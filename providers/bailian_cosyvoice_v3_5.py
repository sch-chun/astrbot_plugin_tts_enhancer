"""百炼 CosyVoice V3.5 适配器"""

from ._bailian_speech_synthesizer import BailianSpeechSynthesizerAdapter


class BailianCosyVoiceV3_5Adapter(BailianSpeechSynthesizerAdapter):
    DISPLAY_NAME = "百炼 Cosyvoice-V3.5"
    """百炼 CosyVoice V3.5 适配器"""

    MODEL_NAME = "cosyvoice-v3.5"
    VALID_LANGS = ["zh", "en", "fr", "de", "ja", "ko", "ru", "pt", "th", "id", "vi"]

    # 官方文档：AIGC 隐性标识仅 cosyvoice-v3-flash / v3-plus / v2 支持，v3.5 不在范围内。
    # 配置项已移除；此处兜底忽略旧配置中残留的 enable_aigc_tag。
    SUPPORTS_AIGC_TAG = False
