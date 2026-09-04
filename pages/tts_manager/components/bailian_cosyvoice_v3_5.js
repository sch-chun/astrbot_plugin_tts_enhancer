import BailianSpeechSynthesizer from './bailian_speech_synthesizer.js';

export default {
    name: 'BailianCosyvoiceV3_5',
    props: ['entries', 'bridge', 'templateKey'],
    components: { BailianSpeechSynthesizer },
    setup(props) {
        const config = {
            displayName: '百炼 CosyVoice V3.5',
            supportedLanguages: ['zh','en','fr','de','ja','ko','ru','pt','th','id','vi'],
            supportsSystemVoices: false,   // 不支持系统音色
            systemVoiceHelpLink: '',       // 不显示系统音色链接
            designHelpLink: 'https://help.aliyun.com/zh/model-studio/voice-design-user-guide'
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
