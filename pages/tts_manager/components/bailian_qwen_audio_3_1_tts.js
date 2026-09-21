import BailianSpeechSynthesizer from './common/bailian_speech_synthesizer.js';

export default {
    name: 'BailianQwenAudio3_1',
    props: ['entries', 'bridge', 'templateKey'],
    components: { BailianSpeechSynthesizer },
    setup(props) {
        const config = {
            displayName: '百炼 Qwen Audio 3.1 TTS',
            supportedLanguages: [
                'zh','en','fr','de','ja','ko','ru','pt','th','id','vi','es','it','ms','fil','ar'
            ],
            availableModels: ['flash'],  // 当前仅支持 Flash
            supportsSystemVoices: true,
            systemVoiceHelpLink: 'https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list',
            designHelpLink: 'https://help.aliyun.com/zh/model-studio/voice-design-user-guide',
            
            // 系统音色相关链接列表（用于显示多个链接）
            systemVoiceLinks: [
                {
                    label: '系统音色列表',
                    url: 'https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list'
                }
            ]
        };
        return { config };
    },
    template: `
        <BailianSpeechSynthesizer
            :entries="entries" 
            :bridge="bridge" 
            :templateKey="templateKey" 
            :providerConfig="config" 
        />
    `
};
