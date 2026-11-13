import BailianSpeechSynthesizer from './common/bailian_speech_synthesizer.js';

export default {
    name: 'BailianQwenAudio3_0',
    props: ['entries', 'bridge', 'templateKey'],
    components: { BailianSpeechSynthesizer },
    setup(props) {
        const t = (k, fb) => props.bridge && props.bridge.t ? props.bridge.t('views.tts_studio.components.' + k, fb) : fb;
        const config = {
            displayName: '百炼 Qwen Audio 3.0 TTS',
            supportedLanguages: [
                'zh','en','fr','de','ja','ko','ru','pt','th','id','vi','es','it','ms','fil','ar'
            ],
            availableModels: ['flash', 'plus'],
            supportsSystemVoices: true,
            systemVoiceHelpLink: 'https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list',
            designHelpLink: 'https://help.aliyun.com/zh/model-studio/voice-design-user-guide',
            
            // 系统音色相关链接列表（用于显示多个链接）
            systemVoiceLinks: [
                {
                    label: t('sysVoiceList', '系统音色列表'),
                    url: 'https://help.aliyun.com/zh/model-studio/qwen-audio-tts-voice-list'
                },
                { label: t('basicVoiceRef', '基础音色参考库'), url: 'https://qwenaudio.tairitsu.work' }
            ]
        };
        return { config };
    },
    template: /*html*/ `
        <BailianSpeechSynthesizer 
            :entries="entries" 
            :bridge="bridge" 
            :templateKey="templateKey" 
            :providerConfig="config" 
        />
    `
};
